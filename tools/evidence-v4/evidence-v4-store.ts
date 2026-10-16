import { constants, type Stats } from "node:fs";
import * as fs from "node:fs/promises";
import path from "node:path";
import { randomUUID } from "node:crypto";
import {
	C,
	D,
	H,
	parseJSON,
	utf8Compare,
	validateFileRef,
	validateExecutionRef,
	validateExecutionArtifact,
	validateExecutionDescriptor,
	validateHistoryEvent,
	validateHistoryView,
	validateOwnerRecord,
	validateClaimRecord,
	validateRunManifest,
	validateCurrentPointer,
	validateObservationCheck,
	validateObservationRequest,
	validateObservationResponse,
	validateInputState,
	validateToolIdentity,
	type FileRef,
	type ExecutionRef,
	type ExecutionArtifact,
	type ExecutionDescriptor,
	type HistoryEvent,
	type HistoryRef,
	type HistoryView,
	type ClaimRecord,
	type RunManifest,
	type OwnerRecord,
	type Recipe,
	type ObservationResponse,
} from "./evidence-v4-model.ts";

const BASE = ".fv/evidence/v4";
const HASH = /^sha256:[0-9a-f]{64}$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const RESERVED = /^--- fv-evidence(?:-v4)?: (?:exit=|result=).* ---$/;
const LINES = /\r\n|[\n\r\v\f\x1c-\x1e\u0085\u2028\u2029]/;
const decoder = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true });
export const HISTORY_BINDING = "retained-store-completeness-assumed" as const;
export type Member = ExecutionDescriptor["members"][number];
export type HistorySnapshot = { view: HistoryView; events: HistoryEvent[] };
export type Publication = {
	state: "not-attempted" | "pre-replace-error" | "post-replace-error" | "durable";
	candidate: FileRef | null;
};
export type StoreOptions = {
	withAppendLock?: <T>(fn: () => Promise<T>) => Promise<T>;
	syscallBarrier?: (
		operation: "write" | "fsync" | "rename",
		path: string,
		phase: "before" | "after",
	) => void | Promise<void>;
};
export type CandidateSelection = {
	member: Member;
	candidate: { execution: ExecutionRef; artifact: ExecutionArtifact; sequence: number; observation: FileRef } | null;
	blocking_events: HistoryRef[];
	state: "PASS" | "FAIL" | "ERROR" | "MISSING";
};
export type MemberCandidate = CandidateSelection;
type EventInput = Omit<HistoryEvent, "event_id" | "sequence" | "previous">;
type Termination = ExecutionArtifact["termination"];
type ExecutionValidation = Map<string, { reference: ExecutionRef; artifact: Promise<ExecutionArtifact> }>;
type SnapshotValidation = { snapshot: HistorySnapshot; epoch: number; executions: ExecutionValidation };

function fail(message: string): never {
	throw new Error(`v4 store: ${message}`);
}
function equal(a: unknown, b: unknown): boolean {
	return Buffer.from(C(a)).equals(Buffer.from(C(b)));
}
function without<T extends object, K extends keyof T>(value: T, key: K): Omit<T, K> {
	const copy = { ...value };
	delete copy[key];
	return copy;
}
function freezeRecord<T>(value: T): T {
	if (value !== null && typeof value === "object" && !Object.isFrozen(value)) {
		for (const child of Object.values(value)) freezeRecord(child);
		Object.freeze(value);
	}
	return value;
}
function safePath(relative: string): string {
	if (
		!relative ||
		relative.startsWith("~") ||
		relative.startsWith("/") ||
		/[\\\x00-\x1f\x7f-\x9f]/u.test(relative) ||
		relative.split("/").some((part) => !part || part === "." || part === "..")
	)
		fail(`unsafe path ${JSON.stringify(relative)}`);
	return relative;
}
function under(relative: string, prefix: string): boolean {
	return relative.startsWith(`${prefix}/`);
}
function errorCode(error: unknown): string | undefined {
	return (error as NodeJS.ErrnoException)?.code;
}
function owned(stat: Stats, file: string): void {
	if (typeof process.getuid === "function" && stat.uid !== process.getuid())
		fail(`file is not producer-owned: ${file}`);
}
async function rootPath(root: string): Promise<string> {
	const absolute = path.resolve(root);
	const stat = await fs.lstat(absolute);
	if (!stat.isDirectory() || stat.isSymbolicLink()) fail("project root is not a real directory");
	const real = await fs.realpath(absolute);
	if (real !== absolute) fail("project root traverses a symlink");
	return real;
}
async function checkedPath(root: string, relative: string, missingLeaf = false): Promise<string> {
	safePath(relative);
	let current = root;
	const parts = relative.split("/");
	for (let index = 0; index < parts.length; index++) {
		current = path.join(current, parts[index]!);
		let stat;
		try {
			stat = await fs.lstat(current);
		} catch (error) {
			if (missingLeaf && index === parts.length - 1 && errorCode(error) === "ENOENT") return current;
			throw error;
		}
		if (stat.isSymbolicLink()) fail(`symlink in output path: ${relative}`);
		if (index < parts.length - 1 && !stat.isDirectory()) fail(`non-directory path component: ${relative}`);
		if (relative === BASE || relative.startsWith(`${BASE}/`)) owned(stat, current);
	}
	return current;
}
async function seam<T>(
	options: StoreOptions,
	operation: "write" | "fsync" | "rename",
	file: string,
	action: () => Promise<T>,
): Promise<T> {
	await options.syscallBarrier?.(operation, file, "before");
	const result = await action();
	await options.syscallBarrier?.(operation, file, "after");
	return result;
}
async function syncDirectory(absolute: string, options: StoreOptions): Promise<void> {
	const handle = await fs.open(absolute, constants.O_RDONLY | constants.O_DIRECTORY | constants.O_NOFOLLOW);
	try {
		await seam(options, "fsync", absolute, () => handle.sync());
	} finally {
		await handle.close();
	}
}
async function syncAncestors(root: string, absolute: string, options: StoreOptions): Promise<void> {
	let current = absolute;
	while (true) {
		await syncDirectory(current, options);
		if (current === root) return;
		const next = path.dirname(current);
		if (next === current || !current.startsWith(`${root}${path.sep}`)) fail("directory escaped root");
		current = next;
	}
}
async function mkdirDurable(root: string, relative: string, options: StoreOptions): Promise<void> {
	safePath(relative);
	let current = root;
	for (const part of relative.split("/")) {
		const parent = current;
		current = path.join(current, part);
		try {
			await fs.mkdir(current, { mode: 0o700 });
			await syncDirectory(current, options);
			await syncAncestors(root, parent, options);
		} catch (error) {
			if (errorCode(error) !== "EEXIST") throw error;
			const stat = await fs.lstat(current);
			if (!stat.isDirectory() || stat.isSymbolicLink()) fail(`unsafe existing directory: ${current}`);
			if (current.startsWith(path.join(root, BASE))) owned(stat, current);
		}
	}
}
export async function durableMkdir(root: string, relative: string): Promise<void> {
	await mkdirDurable(await rootPath(root), relative, {});
}
async function readBytes(root: string, relative: string): Promise<Buffer> {
	const absolute = await checkedPath(root, relative);
	const before = await fs.lstat(absolute);
	if (!before.isFile() || before.nlink !== 1) fail(`nonregular or hardlinked output: ${relative}`);
	owned(before, relative);
	const handle = await fs.open(absolute, constants.O_RDONLY | constants.O_NOFOLLOW);
	try {
		const opened = await handle.stat();
		if (opened.dev !== before.dev || opened.ino !== before.ino || opened.nlink !== 1)
			fail(`output changed while opening: ${relative}`);
		const bytes = await handle.readFile();
		const after = await handle.stat();
		const named = await fs.lstat(absolute);
		if (
			after.dev !== named.dev ||
			after.ino !== named.ino ||
			after.size !== before.size ||
			after.mtimeMs !== before.mtimeMs ||
			after.ctimeMs !== before.ctimeMs ||
			named.nlink !== 1
		)
			fail(`output changed while reading: ${relative}`);
		return bytes;
	} finally {
		await handle.close();
	}
}
export async function readFileRef(root: string, reference: FileRef): Promise<Buffer> {
	validateFileRef(reference);
	const bytes = await readBytes(await rootPath(root), reference.path);
	if (bytes.length !== reference.size || H(bytes) !== reference.hash)
		fail(`reference bytes mismatch: ${reference.path}`);
	return bytes;
}
async function writeNew(root: string, relative: string, bytes: Uint8Array, options: StoreOptions): Promise<FileRef> {
	const parent = path.posix.dirname(safePath(relative));
	if (parent !== ".") await mkdirDurable(root, parent, options);
	const absolute = await checkedPath(root, relative, true);
	const handle = await fs.open(
		absolute,
		constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | constants.O_NOFOLLOW,
		0o600,
	);
	try {
		await seam(options, "write", absolute, () => handle.writeFile(bytes));
		await seam(options, "fsync", absolute, () => handle.sync());
	} finally {
		await handle.close();
	}
	await syncAncestors(root, path.dirname(absolute), options);
	return { path: relative, hash: H(bytes), size: bytes.byteLength };
}
async function immutableFile(
	root: string,
	relative: string,
	bytes: Uint8Array,
	options: StoreOptions,
): Promise<FileRef> {
	const expectedHash = H(bytes),
		expectedSize = bytes.byteLength;
	const parent = path.posix.dirname(safePath(relative));
	if (parent !== ".") await mkdirDurable(root, parent, options);
	const temporary = `${BASE}/.staging-file-${path.posix.basename(relative)}-${randomUUID()}`;
	await writeNew(root, temporary, bytes, options);
	const retained = await readBytes(root, temporary);
	if (retained.length !== expectedSize || H(retained) !== expectedHash)
		fail("actual immutable bytes differ before publication");
	const target = await checkedPath(root, relative, true);
	const source = await checkedPath(root, temporary);
	if ((await fs.stat(path.dirname(source))).dev !== (await fs.stat(path.dirname(target))).dev)
		fail("cross-filesystem immutable publication");
	// link is the exclusive publication primitive for a single file. Unlink before acknowledgment.
	await fs.link(source, target);
	await fs.unlink(source);
	const finalHandle = await fs.open(target, constants.O_RDONLY | constants.O_NOFOLLOW);
	try {
		await seam(options, "fsync", target, () => finalHandle.sync());
	} finally {
		await finalHandle.close();
	}
	await syncAncestors(root, path.dirname(target), options);
	return { path: relative, hash: expectedHash, size: expectedSize };
}
export async function writeImmutableFile(root: string, relative: string, bytes: Uint8Array): Promise<FileRef> {
	return immutableFile(await rootPath(root), relative, bytes, {});
}
export async function writeImmutableJSON(root: string, relative: string, value: unknown): Promise<FileRef> {
	return writeImmutableFile(root, relative, C(value));
}
async function walk(root: string, relative: string): Promise<string[]> {
	const absolute = await checkedPath(root, relative);
	const stat = await fs.lstat(absolute);
	if (!stat.isDirectory()) fail(`expected directory: ${relative}`);
	const files: string[] = [];
	for (const entry of (await fs.readdir(absolute)).sort(utf8Compare)) {
		const child = `${relative}/${entry}`;
		const childPath = await checkedPath(root, child);
		const info = await fs.lstat(childPath);
		if (info.isDirectory()) files.push(...(await walk(root, child)));
		else if (info.isFile() && info.nlink === 1) {
			owned(info, child);
			files.push(child);
		} else fail(`unsafe stored entry: ${child}`);
	}
	return files;
}
async function treeSync(root: string, relative: string, options: StoreOptions): Promise<void> {
	const absolute = await checkedPath(root, relative);
	for (const entry of await fs.readdir(absolute)) {
		const child = `${relative}/${entry}`;
		const file = await checkedPath(root, child);
		const stat = await fs.lstat(file);
		if (stat.isDirectory()) await treeSync(root, child, options);
		else {
			if (!stat.isFile() || stat.nlink !== 1) fail(`unsafe checkpoint entry: ${child}`);
			owned(stat, file);
			const handle = await fs.open(file, constants.O_RDONLY | constants.O_NOFOLLOW);
			try {
				await seam(options, "fsync", file, () => handle.sync());
			} finally {
				await handle.close();
			}
		}
	}
	await syncDirectory(absolute, options);
}
export async function fsyncTree(root: string, relative: string): Promise<void> {
	const real = await rootPath(root);
	await treeSync(real, relative, {});
	await syncAncestors(real, path.dirname(path.join(real, relative)), {});
}
function normalized(stream: Uint8Array): Buffer {
	const bytes = Buffer.from(stream);
	return bytes.length && bytes[bytes.length - 1] !== 10 ? Buffer.concat([bytes, Buffer.from("\n")]) : bytes;
}
export function reconstructRawOutput(
	stdout: Uint8Array,
	stderr: Uint8Array,
	termination: Termination,
	result: ExecutionArtifact["result"],
): Buffer {
	const normal =
		termination.exit_code !== null && termination.signal === null && !termination.timed_out && !termination.cancelled;
	if (!normal && result !== "ERROR" && result !== "CANCELLED")
		throw new Error("abnormal termination has normal result");
	const trailer = normal
		? `--- fv-evidence: exit=${termination.exit_code} ---\n`
		: `--- fv-evidence-v4: result=${result} ---\n`;
	return Buffer.concat([normalized(stdout), normalized(stderr), Buffer.from(trailer)]);
}
export function markerMatches(raw: Uint8Array | string, recipe: Recipe): boolean {
	const text = typeof raw === "string" ? raw : decoder.decode(raw);
	if (recipe.pass_marker !== null) return text.includes(recipe.pass_marker);
	const zero = "--- fv-evidence: exit=0 ---";
	const defaults: Record<string, string[]> = {
		"code-enforced": [zero],
		"proof-discharged": ["VERIFICATION:- SUCCESSFUL", "Build completed successfully", zero],
		"bounded-checked": ["[ok]", "VERIFICATION:- SUCCESSFUL", "No violation found"],
		"test-witnessed": ["test result: ok."],
		"conformance-tested": ["CONFORMANCE: PASS", "CONFORMANCE_TESTED: PASS", "test result: ok.", zero],
	};
	return (defaults[recipe.evidence_class] ?? []).some((marker) => text.includes(marker));
}
export function barrierApplies(event: HistoryEvent, member: Member): boolean {
	if (event.result !== "FAIL" && event.kind !== "indeterminate") return false;
	if (event.kind === "observation" || (event.kind === "indeterminate" && event.claim_id !== null)) {
		return event.members.some(
			(item) =>
				item.claim_id === event.claim_id &&
				item.slot_id === event.slot_id &&
				item.claim_id === member.claim_id &&
				item.tool === member.tool,
		);
	}
	return event.members.some((item) => item.claim_id === member.claim_id && item.tool === member.tool);
}
function executionDirectory(key: string, attempt: string): string {
	if (!HASH.test(key) || !UUID.test(attempt)) fail("invalid execution identity");
	return `${BASE}/executions/${key.slice(7)}/${attempt}`;
}
function assertToolchainIdentity(tools: ExecutionDescriptor["toolchain"]): void {
	tools.forEach(validateToolIdentity);
	const indexed = new Map(tools.map((tool) => [tool.id, tool]));
	const visited = new Set<string>(),
		active = new Set<string>();
	const visit = (id: string): void => {
		if (active.has(id)) fail("tool dependency cycle");
		if (visited.has(id)) return;
		const tool = indexed.get(id);
		if (!tool) fail(`tool dependency missing: ${id}`);
		active.add(id);
		for (const dependency of tool.requires) visit(dependency);
		if (
			(tool.version !== null && tool.version.exit_code !== 0) ||
			tool.discovery.some((probe) => probe.exit_code !== 0)
		)
			fail("tool has unsuccessful discovery provenance");
		active.delete(id);
		visited.add(id);
	};
	for (const tool of tools) visit(tool.id);
}
function assertArtifactIdentity(artifact: ExecutionArtifact, expected?: ExecutionDescriptor): void {
	if (expected && !equal(artifact.descriptor, expected)) fail("candidate descriptor differs from current descriptor");
	const descriptor = artifact.descriptor;
	const producer = descriptor.toolchain.find((tool) => tool.id === "fv-producer");
	if (!producer) fail("execution lacks producer tool identity");
	const implementation = producer.files
		.filter((file) => file.kind === "file" && file.path.startsWith("implementation/"))
		.map((file) => ({ path: file.path.slice("implementation/".length), hash: file.kind === "file" ? file.hash : "" }));
	if (!implementation.length || D("producer-implementation", implementation) !== artifact.producer.implementation_hash)
		fail("producer implementation binding mismatch");
	const closure = descriptor.closure;
	if (
		artifact.source_before.verified_inputs_policy_hash !== descriptor.verified_inputs_policy_hash ||
		artifact.source_before.inventory_hash !== descriptor.inventory_hash
	)
		fail("artifact source/descriptor mismatch");
	for (const file of closure.files) {
		if (!artifact.source_before.files.some((source) => equal(source, file)))
			fail(`closure member missing from original input state: ${file.path}`);
	}
	if (closure.mode === "verified-inputs" && !equal(closure.files, artifact.source_before.files))
		fail("whole-source closure omits original inputs");
	for (const binding of [
		{ path: descriptor.common.intent_path, hash: descriptor.common.intent_hash },
		{ path: descriptor.common.manifest_path, hash: descriptor.common.manifest_hash },
		...descriptor.common.definition_files,
	]) {
		if (!artifact.source_before.files.some((file) => file.path === binding.path && file.hash === binding.hash))
			fail("common binding differs from original input state");
	}
	const receipt = artifact.ownership;
	const windowIds = new Set(receipt.spawn_windows.map((window) => window.window_id));
	for (const registration of receipt.children) {
		if (!windowIds.has(registration.window_id)) fail("registration references unknown window");
		if (
			registration.registered_at < artifact.started_at ||
			registration.registered_at > artifact.finished_at ||
			(registration.terminated_at !== null &&
				(registration.terminated_at < registration.registered_at || registration.terminated_at > artifact.finished_at))
		)
			fail("registration outside execution interval");
	}
	if (artifact.result === "PASS") {
		if (
			!receipt.children.length ||
			!receipt.spawn_windows.length ||
			receipt.children.some((child) => child.terminated_at === null) ||
			receipt.spawn_windows.some(
				(window) =>
					window.state !== "closed" ||
					window.execution_key !== artifact.execution_key ||
					window.attempt_id !== artifact.attempt_id,
			)
		)
			fail("PASS ownership not completely closed");
		if (descriptor.recipe.ownership_protocol !== null && receipt.protocol_log === null)
			fail("hosted ownership missing protocol log");
		if (descriptor.recipe.attestation !== null && !artifact.attachments.length)
			fail("collector attestation has no retained attachments");
	}
}

export class Store {
	readonly root: string;
	readonly options: StoreOptions;
	private writeEpoch = 0;
	private readonly snapshotValidations = new WeakMap<HistorySnapshot, SnapshotValidation>();
	private latestValidation: SnapshotValidation | undefined;
	constructor(root: string, options: StoreOptions = {}) {
		this.root = root;
		this.options = options;
	}
	async writeImmutableFile(relative: string, bytes: Uint8Array): Promise<FileRef> {
		this.writeEpoch++;
		return immutableFile(this.root, relative, bytes, this.options);
	}
	async writeImmutableJSON(relative: string, value: unknown): Promise<FileRef> {
		return this.writeImmutableFile(relative, C(value));
	}
	async readFileRef(reference: FileRef): Promise<Buffer> {
		return readFileRef(this.root, reference);
	}
	async durableMkdir(relative: string): Promise<void> {
		this.writeEpoch++;
		await mkdirDurable(this.root, relative, this.options);
	}
	async fsyncTree(relative: string): Promise<void> {
		await treeSync(this.root, relative, this.options);
		await syncAncestors(this.root, path.dirname(path.join(this.root, relative)), this.options);
	}
	async publishExecution(
		input: Omit<ExecutionArtifact, "artifact_id">,
		files: ReadonlyMap<string, Uint8Array>,
	): Promise<ExecutionRef> {
		this.writeEpoch++;
		const artifact = validateExecutionArtifact({ ...input, artifact_id: D("execution-artifact", input) });
		assertArtifactIdentity(artifact);
		const destination = executionDirectory(artifact.execution_key, artifact.attempt_id);
		const parent = path.posix.dirname(destination);
		await this.durableMkdir(parent);
		const staging = `${parent}/.staging-${randomUUID()}`;
		await this.durableMkdir(staging);
		await this.durableMkdir(`${staging}/attachments`);
		const references = [artifact.stdout, artifact.stderr, artifact.raw_output, ...artifact.attachments];
		if (artifact.ownership.protocol_log !== null) {
			const prior = references.find((reference) => reference.path === artifact.ownership.protocol_log!.path);
			if (prior && !equal(prior, artifact.ownership.protocol_log))
				fail("ownership log contradicts attachment reference");
			if (!prior) references.push(artifact.ownership.protocol_log);
		}
		const expectedFiles = new Map(
			references.map((reference) => [reference.path.slice(destination.length + 1), reference]),
		);
		if (expectedFiles.size !== references.length || files.size !== expectedFiles.size)
			fail("checkpoint files do not match owned references");
		for (const [relative, bytes] of files) {
			safePath(relative);
			const reference = expectedFiles.get(relative);
			if (
				!reference ||
				reference.path !== `${destination}/${relative}` ||
				reference.size !== bytes.byteLength ||
				reference.hash !== H(bytes)
			)
				fail(`checkpoint file mismatch: ${relative}`);
			if (!["stdout.bin", "stderr.bin", "raw.log"].includes(relative) && !under(relative, "attachments"))
				fail("extra file outside attachment namespace");
			await writeNew(this.root, `${staging}/${relative}`, bytes, this.options);
		}
		if (
			artifact.stdout.path !== `${destination}/stdout.bin` ||
			artifact.stderr.path !== `${destination}/stderr.bin` ||
			artifact.raw_output.path !== `${destination}/raw.log`
		)
			fail("wrong fixed stream paths");
		this.validateStreams(artifact, files.get("stdout.bin")!, files.get("stderr.bin")!, files.get("raw.log")!);
		const bytes = C(artifact);
		await writeNew(this.root, `${staging}/execution.json`, bytes, this.options);
		const stagedStreams = new Map<string, Buffer>();
		for (const [relative, reference] of expectedFiles) {
			const retained = await readBytes(this.root, `${staging}/${relative}`);
			if (retained.length !== reference.size || H(retained) !== reference.hash)
				fail("actual staged bytes differ from execution reference");
			if (relative === "stdout.bin" || relative === "stderr.bin" || relative === "raw.log")
				stagedStreams.set(relative, retained);
		}
		if (!(await readBytes(this.root, `${staging}/execution.json`)).equals(Buffer.from(bytes)))
			fail("actual artifact JSON differs from canonical identity");
		const actualFiles = (await walk(this.root, staging)).sort(utf8Compare);
		if (
			!equal(
				actualFiles,
				[...expectedFiles.keys()]
					.map((relative) => `${staging}/${relative}`)
					.concat(`${staging}/execution.json`)
					.sort(utf8Compare),
			)
		)
			fail("unbound files in staged execution");
		this.validateStreams(
			artifact,
			stagedStreams.get("stdout.bin")!,
			stagedStreams.get("stderr.bin")!,
			stagedStreams.get("raw.log")!,
		);
		await this.fsyncTree(staging);
		const target = await checkedPath(this.root, destination, true);
		try {
			await fs.lstat(target);
			fail("attempt already exists");
		} catch (error) {
			if (errorCode(error) !== "ENOENT") throw error;
		}
		const stagePath = await checkedPath(this.root, staging);
		if ((await fs.stat(stagePath)).dev !== (await fs.stat(path.dirname(target))).dev)
			fail("cross-filesystem checkpoint publication");
		this.writeEpoch++;
		await seam(this.options, "rename", target, () => fs.rename(stagePath, target));
		await syncAncestors(this.root, path.dirname(target), this.options);
		return {
			execution_key: artifact.execution_key,
			artifact_id: artifact.artifact_id,
			path: `${destination}/execution.json`,
			hash: H(bytes),
		};
	}
	private validateStreams(artifact: ExecutionArtifact, stdout: Uint8Array, stderr: Uint8Array, raw: Uint8Array): void {
		if (!Buffer.from(raw).equals(reconstructRawOutput(stdout, stderr, artifact.termination, artifact.result)))
			fail("raw output reconstruction mismatch");
		let valid = true;
		let marked = false;
		try {
			for (const stream of [stdout, stderr])
				if (
					decoder
						.decode(stream)
						.split(LINES)
						.some((line) => RESERVED.test(line))
				)
					valid = false;
			marked = valid && markerMatches(raw, artifact.descriptor.recipe);
		} catch {
			valid = false;
		}
		if (artifact.marker_matched !== marked) fail("marker evaluation mismatch");
		if (artifact.result === "PASS" && (!valid || !marked)) fail("PASS invalid UTF-8/reserved trailer/marker");
	}
	async readExecution(reference: ExecutionRef, expected?: ExecutionDescriptor): Promise<ExecutionArtifact> {
		validateExecutionRef(reference);
		const destination = executionDirectory(reference.execution_key, reference.path.split("/").at(-2)!);
		if (reference.path !== `${destination}/execution.json`) fail("noncanonical execution path");
		const bytes = await readBytes(this.root, reference.path);
		if (H(bytes) !== reference.hash) fail("execution reference hash mismatch");
		const artifact = validateExecutionArtifact(parseJSON(bytes));
		if (
			artifact.artifact_id !== reference.artifact_id ||
			artifact.execution_key !== reference.execution_key ||
			artifact.attempt_id !== destination.split("/").at(-1)
		)
			fail("execution reference identity mismatch");
		assertArtifactIdentity(artifact, expected);
		if (
			artifact.stdout.path !== `${destination}/stdout.bin` ||
			artifact.stderr.path !== `${destination}/stderr.bin` ||
			artifact.raw_output.path !== `${destination}/raw.log`
		)
			fail("execution streams escape owner");
		const refs = [artifact.stdout, artifact.stderr, artifact.raw_output, ...artifact.attachments];
		for (const attachment of artifact.attachments)
			if (!under(attachment.path, `${destination}/attachments`)) fail("attachment escapes execution owner");
		if (artifact.ownership.protocol_log !== null) {
			if (!under(artifact.ownership.protocol_log.path, `${destination}/attachments`))
				fail("ownership protocol log escapes owner");
			if (!refs.some((ref) => equal(ref, artifact.ownership.protocol_log))) refs.push(artifact.ownership.protocol_log);
		}
		if (new Set(refs.map((ref) => ref.path)).size !== refs.length) fail("duplicate execution file ownership");
		const retained = new Map<string, Buffer>();
		for (const ref of refs) retained.set(ref.path, await this.readFileRef(ref));
		const actual = (await walk(this.root, destination)).sort(utf8Compare);
		const wanted = [...refs.map((ref) => ref.path), reference.path].sort(utf8Compare);
		if (!equal(actual, wanted)) fail("execution tree contains unbound or missing files");
		this.validateStreams(
			artifact,
			retained.get(artifact.stdout.path)!,
			retained.get(artifact.stderr.path)!,
			retained.get(artifact.raw_output.path)!,
		);
		return artifact;
	}
	private async retainedExecution(reference: ExecutionRef, cache: ExecutionValidation): Promise<ExecutionArtifact> {
		const prior = cache.get(reference.path);
		if (prior) {
			if (!equal(prior.reference, reference)) fail("contradictory references to one immutable execution");
			return prior.artifact;
		}
		const artifact = this.readExecution(reference).then(freezeRecord);
		cache.set(reference.path, { reference, artifact });
		return artifact;
	}
	private async observationResult(event: HistoryEvent, cache: ExecutionValidation): Promise<void> {
		if (!event.execution) fail("observation event missing execution");
		if (event.observation === null) {
			if (event.result === "PASS" || event.result === "FAIL") fail("observation assessment missing durable receipt");
			return;
		}
		const bytes = await this.readFileRef(event.observation);
		const check = validateObservationCheck(parseJSON(bytes));
		const prefix = event.observation.path.slice(0, -"check.json".length);
		if (
			!new RegExp(
				`^\\.fv/evidence/v4/runs/${UUID.source.slice(1, -1)}/observations/[A-Za-z0-9][A-Za-z0-9._-]*/${UUID.source.slice(1, -1)}/$`,
			).test(prefix) ||
			event.observation.path !== `${prefix}check.json` ||
			check.request.path !== `${prefix}request.json` ||
			check.stdout.path !== `${prefix}stdout.bin` ||
			check.stderr.path !== `${prefix}stderr.bin`
		)
			fail("observation files escape fixed owner directory");
		const requestBytes = await this.readFileRef(check.request);
		const request = validateObservationRequest(parseJSON(requestBytes));
		await this.readFileRef(check.stdout);
		await this.readFileRef(check.stderr);
		if (request.claim_id !== event.claim_id || !prefix.endsWith(`/${request.claim_id}/${request.request_id}/`))
			fail("observation request member/path mismatch");
		const selected = request.slots.find((slot) => slot.slot_id === event.slot_id);
		if (!selected || !equal(selected.execution, event.execution)) fail("observation selected execution mismatch");
		const execution = await this.retainedExecution(event.execution, cache);
		if (
			execution.result !== "PASS" ||
			!equal(request.common, execution.descriptor.common) ||
			request.policy_hash !== execution.descriptor.common.policy_hash ||
			request.policy_path !== execution.descriptor.common.policy_path
		)
			fail("observation request provenance mismatch");
		if (
			!event.members.some(
				(member) =>
					member.claim_id === request.claim_id && member.slot_id === selected.slot_id && member.tool === selected.tool,
			)
		)
			fail("observation tool/member mismatch");
		if (!(request.created_at <= check.started_at && check.started_at <= check.finished_at))
			fail("observation check interval mismatch");
		if (check.source_after !== null) validateInputState(check.source_after);
		validateInputState(check.source_before);
		assertToolchainIdentity(check.toolchain);
		if (check.response === null) {
			if (event.result !== check.result || event.result === "PASS" || event.result === "FAIL")
				fail("observation missing response claims an assessment");
			return;
		}
		if (check.response.path !== `${prefix}response.json`) fail("response escapes request directory");
		const responseBytes = await this.readFileRef(check.response);
		let response: ObservationResponse;
		try {
			response = validateObservationResponse(parseJSON(responseBytes));
			if (
				response.request_id !== request.request_id ||
				response.request_hash !== H(requestBytes) ||
				response.claim_id !== request.claim_id ||
				!equal(
					response.slots.map((slot) => slot.slot_id),
					request.slots.map((slot) => slot.slot_id),
				)
			)
				fail("observation response/request mismatch");
			if (
				!(
					check.started_at <= response.started_at &&
					response.started_at <= response.finished_at &&
					response.finished_at <= check.finished_at
				)
			)
				fail("observation response interval mismatch");
		} catch (error) {
			if ((event.result === "ERROR" || event.result === "CANCELLED") && event.result === check.result) return;
			throw error;
		}
		const result = response.slots.find((slot) => slot.slot_id === event.slot_id)!.result;
		const normal =
			check.termination.exit_code === 0 &&
			check.termination.signal === null &&
			!check.termination.timed_out &&
			!check.termination.cancelled;
		if (event.result === "PASS" || event.result === "FAIL") {
			if (
				!normal ||
				event.result !== result ||
				!check.source_after ||
				!check.source_before.clean ||
				!check.source_after.clean ||
				!equal(check.source_before, check.source_after)
			)
				fail("observation assessed result has invalid receipt");
			if (
				selected.recipe_id !== execution.descriptor.recipe.recipe_id ||
				check.source_before.inventory_hash !== execution.descriptor.inventory_hash ||
				check.source_before.verified_inputs_policy_hash !== execution.descriptor.verified_inputs_policy_hash ||
				execution.descriptor.closure.files.some(
					(file) => !check.source_before.files.some((source) => equal(file, source)),
				)
			)
				fail("observation source/recipe binding mismatch");
			if (
				!equal(
					check.toolchain.find((tool) => tool.id === "fv-producer"),
					execution.descriptor.toolchain.find((tool) => tool.id === "fv-producer"),
				)
			)
				fail("observation producer binding mismatch");
		} else if (event.result !== check.result && !(event.result === "ERROR" && result === "ERROR"))
			fail("observation error result mismatch");
	}
	private async validateEventBindings(
		event: HistoryEvent,
		previous: readonly HistoryEvent[],
		cache: ExecutionValidation = new Map(),
	): Promise<void> {
		const sameAttempt = previous.filter(
			(item) => item.execution_key === event.execution_key && item.attempt_id === event.attempt_id,
		);
		if (event.kind === "execution") {
			if (
				sameAttempt.some(
					(item) => item.kind === "execution" || (item.kind === "indeterminate" && item.claim_id === null),
				)
			)
				fail("duplicate or previously indeterminate actual execution");
			if (
				event.claim_id !== null ||
				event.slot_id !== null ||
				event.observation !== null ||
				event.indeterminate_owner !== null
			)
				fail("execution event has observation/recovery fields");
			if (event.execution !== null) {
				const artifact = await this.retainedExecution(event.execution, cache);
				if (
					artifact.execution_key !== event.execution_key ||
					artifact.attempt_id !== event.attempt_id ||
					artifact.result !== event.result ||
					!equal(artifact.descriptor.members, event.members)
				)
					fail("history execution/member/result mismatch");
			} else if (event.result === "PASS") fail("unbacked execution PASS");
			return;
		}
		if ((event.claim_id === null) !== (event.slot_id === null)) fail("partial history member selection");
		if (
			event.claim_id !== null &&
			!event.members.some((member) => member.claim_id === event.claim_id && member.slot_id === event.slot_id)
		)
			fail("history selects absent original member");
		const actual = sameAttempt.find((item) => item.kind === "execution");
		if (event.kind === "observation" || event.claim_id !== null) {
			if (!actual || actual.result !== "PASS" || !equal(actual.members, event.members))
				fail("observation precedes actual matching execution");
		}
		if (event.kind === "observation") {
			if (event.claim_id === null || event.indeterminate_owner !== null || !equal(actual!.execution, event.execution))
				fail("observation execution/member mismatch");
			await this.observationResult(event, cache);
			return;
		}
		if (
			event.result !== "ERROR" ||
			!event.indeterminate_owner ||
			event.execution !== null ||
			event.observation !== null
		)
			fail("invalid indeterminate event");
		const owner = validateOwnerRecord(parseJSON(await this.readFileRef(event.indeterminate_owner)));
		if (event.indeterminate_owner.path !== `${BASE}/recovered-owners/${owner.owner_id}.json`)
			fail("recovered owner path mismatch");
		const pending = owner.pending_results.find(
			(item) =>
				item.execution_key === event.execution_key &&
				item.attempt_id === event.attempt_id &&
				item.claim_id === event.claim_id &&
				item.slot_id === event.slot_id &&
				equal(item.members, event.members),
		);
		if (!pending || (pending.kind === "execution") !== (event.claim_id === null && event.slot_id === null))
			fail("indeterminate event lacks original pending membership");
		if (
			sameAttempt.some(
				(item) =>
					item.kind === "indeterminate" &&
					item.claim_id === event.claim_id &&
					item.slot_id === event.slot_id &&
					equal(item.indeterminate_owner, event.indeterminate_owner),
			)
		)
			fail("duplicate indeterminate pending result");
	}
	private async loadHistory(captured: HistoryView | undefined, allowUnaccounted: boolean): Promise<HistorySnapshot> {
		const epoch = this.writeEpoch;
		let names: string[];
		try {
			names = await fs.readdir(await checkedPath(this.root, `${BASE}/history`));
		} catch (error) {
			if (errorCode(error) !== "ENOENT") throw error;
			names = [];
		}
		names.sort(utf8Compare);
		const view: HistoryView = { head: null, events: [] };
		const events: HistoryEvent[] = [];
		const cache: ExecutionValidation = new Map();
		const accounted = new Map<string, HistoryEvent>();
		for (let index = 0; index < names.length; index++) {
			const sequence = index + 1;
			const name = `${String(sequence).padStart(20, "0")}.json`;
			if (names[index] !== name) fail("history is not a contiguous canonical sequence");
			const relative = `${BASE}/history/${name}`;
			const bytes = await readBytes(this.root, relative);
			const event = validateHistoryEvent(parseJSON(bytes));
			if (
				event.sequence !== sequence ||
				!equal(event.previous, view.head) ||
				D("history-event", without(event, "event_id")) !== event.event_id
			)
				fail("history hash chain mismatch");
			const reference: HistoryRef = { sequence, event_id: event.event_id, path: relative, hash: H(bytes) };
			await this.validateEventBindings(event, events, cache);
			if (event.kind === "execution" || (event.kind === "indeterminate" && event.claim_id === null))
				accounted.set(`${event.execution_key}/${event.attempt_id}`, event);
			events.push(event);
			view.events.push(reference);
			view.head = reference;
		}
		if (captured !== undefined) {
			validateHistoryView(captured);
			if (
				captured.events.length > view.events.length ||
				!equal(captured.events, view.events.slice(0, captured.events.length)) ||
				!equal(captured.head, captured.events.at(-1) ?? null)
			)
				fail("captured history is not a retained prefix");
		}
		if (!allowUnaccounted) {
			await this.validateAttemptAccounting(accounted, cache);
			await this.validateObservationAccounting(events, cache);
		}
		if (epoch !== this.writeEpoch) fail("store changed during retained-history validation");
		const snapshot = freezeRecord({ view, events });
		if (!allowUnaccounted) {
			const validation = { snapshot, epoch, executions: cache };
			this.snapshotValidations.set(snapshot, validation);
			this.latestValidation = validation;
		}
		return snapshot;
	}
	private async validateAttemptAccounting(
		accounted: ReadonlyMap<string, HistoryEvent>,
		cache: ExecutionValidation,
	): Promise<void> {
		let keys: string[];
		try {
			keys = await fs.readdir(await checkedPath(this.root, `${BASE}/executions`));
		} catch (error) {
			if (errorCode(error) === "ENOENT") return;
			throw error;
		}
		for (const key of keys) {
			if (!/^[0-9a-f]{64}$/.test(key)) fail("unknown execution-key entry");
			const directory = `${BASE}/executions/${key}`;
			for (const attempt of await fs.readdir(await checkedPath(this.root, directory))) {
				if (/^\.staging-[0-9a-f-]+$/.test(attempt)) {
					await walk(this.root, `${directory}/${attempt}`);
					continue;
				}
				if (!UUID.test(attempt)) fail("unknown attempt directory");
				const relative = `${directory}/${attempt}/execution.json`;
				const bytes = await readBytes(this.root, relative);
				const artifact = validateExecutionArtifact(parseJSON(bytes));
				await this.retainedExecution(
					{ execution_key: `sha256:${key}`, artifact_id: artifact.artifact_id, path: relative, hash: H(bytes) },
					cache,
				);
				const event = accounted.get(`sha256:${key}/${attempt}`);
				if (!event) fail("committed execution has no retained history accounting");
				if (
					!equal(event.members, artifact.descriptor.members) ||
					(event.kind === "execution" && event.result !== artifact.result)
				)
					fail("committed execution contradicts retained membership/outcome");
			}
		}
	}
	private async validateObservationAccounting(
		events: readonly HistoryEvent[],
		cache: ExecutionValidation,
	): Promise<void> {
		let runs: string[];
		try {
			runs = await fs.readdir(await checkedPath(this.root, `${BASE}/runs`));
		} catch (error) {
			if (errorCode(error) === "ENOENT") return;
			throw error;
		}
		for (const run of runs) {
			if (!UUID.test(run)) fail("unknown retained run directory");
			const directory = `${BASE}/runs/${run}/observations`;
			let files: string[];
			try {
				files = await walk(this.root, directory);
			} catch (error) {
				if (errorCode(error) === "ENOENT") continue;
				throw error;
			}
			for (const file of files) {
				if (!file.endsWith("/check.json")) continue;
				const bytes = await readBytes(this.root, file);
				const check = validateObservationCheck(parseJSON(bytes));
				const request = validateObservationRequest(parseJSON(await this.readFileRef(check.request)));
				for (const slot of request.slots) {
					const backed = events.some(
						(event) =>
							event.kind === "observation" &&
							event.observation?.path === file &&
							event.observation.hash === H(bytes) &&
							event.claim_id === request.claim_id &&
							event.slot_id === slot.slot_id &&
							equal(event.execution, slot.execution),
					);
					if (backed) continue;
					const artifact = await this.retainedExecution(slot.execution, cache);
					let recovered = false;
					for (const event of events) {
						if (
							event.kind !== "indeterminate" ||
							!event.indeterminate_owner ||
							event.execution_key !== artifact.execution_key ||
							event.attempt_id !== artifact.attempt_id ||
							event.claim_id !== request.claim_id ||
							event.slot_id !== slot.slot_id
						)
							continue;
						const owner = validateOwnerRecord(parseJSON(await this.readFileRef(event.indeterminate_owner)));
						if (owner.run_id === run) {
							recovered = true;
							break;
						}
					}
					if (!recovered) fail("committed observation has no retained history accounting");
				}
			}
		}
	}
	async readHistory(captured?: HistoryView): Promise<HistorySnapshot> {
		try {
			return await this.loadHistory(captured, false);
		} catch (error) {
			this.writeEpoch++;
			throw error;
		}
	}
	private async appendUnlocked(input: EventInput): Promise<HistoryRef> {
		const snapshot = await this.loadHistory(undefined, true);
		const unsigned = { ...input, sequence: snapshot.events.length + 1, previous: snapshot.view.head };
		const event = validateHistoryEvent({ ...unsigned, event_id: D("history-event", unsigned) });
		const relative = `${BASE}/history/${String(event.sequence).padStart(20, "0")}.json`;
		await this.validateEventBindings(event, snapshot.events);
		const reference = await this.writeImmutableJSON(relative, event);
		return { sequence: event.sequence, event_id: event.event_id, path: reference.path, hash: reference.hash };
	}
	async appendHistory(input: EventInput): Promise<HistoryRef> {
		if (!this.options.withAppendLock) fail("history append requires native owner/append mutex");
		return this.options.withAppendLock(() => this.appendUnlocked(input));
	}
	async selectCandidates(
		descriptor: ExecutionDescriptor,
		selectedMembers: readonly Member[],
		retained?: HistorySnapshot,
	): Promise<CandidateSelection[]> {
		validateExecutionDescriptor(descriptor);
		let validation = retained === undefined ? undefined : this.snapshotValidations.get(retained);
		if (validation && validation.epoch !== this.writeEpoch) {
			const latest = this.latestValidation;
			if (
				latest &&
				latest.epoch === this.writeEpoch &&
				retained!.view.events.length <= latest.snapshot.view.events.length &&
				equal(retained!.view.events, latest.snapshot.view.events.slice(0, retained!.view.events.length))
			)
				validation = latest;
			else validation = undefined;
		}
		if (!validation) {
			const scanned = await this.readHistory(retained?.view);
			validation = this.snapshotValidations.get(scanned)!;
		}
		// Session reuse relies on trusted immutable storage and no external mutation.
		const snapshot = validation.snapshot;
		const key = D("execution-key", descriptor);
		const candidates: { event: HistoryEvent; artifact: ExecutionArtifact }[] = [];
		for (const event of snapshot.events) {
			if (
				event.kind !== "execution" ||
				event.result !== "PASS" ||
				event.execution_key !== key ||
				event.execution === null
			)
				continue;
			// Corruption is an error even when a newer candidate would otherwise win.
			const artifact = await this.retainedExecution(event.execution, validation.executions);
			if (!equal(artifact.descriptor, descriptor)) fail("candidate descriptor differs from current descriptor");
			candidates.push({ event, artifact });
		}
		if (validation.epoch !== this.writeEpoch) fail("store changed during cache selection");
		return selectedMembers.map((member) => {
			if (!descriptor.members.some((item) => equal(item, member))) fail("selected member absent from full descriptor");
			const blockers = snapshot.events.filter((event) => barrierApplies(event, member));
			const cutoff = blockers.at(-1)?.sequence ?? 0;
			let candidate: CandidateSelection["candidate"] = null;
			for (const item of candidates) {
				if (item.event.sequence <= cutoff) continue;
				const observations = snapshot.events.filter(
					(event) =>
						event.kind === "observation" &&
						event.result === "PASS" &&
						event.sequence > item.event.sequence &&
						event.execution_key === key &&
						event.attempt_id === item.event.attempt_id &&
						event.claim_id === member.claim_id &&
						event.slot_id === member.slot_id,
				);
				const observation = observations.at(-1)?.observation;
				if (observation)
					candidate = {
						execution: item.event.execution!,
						artifact: item.artifact,
						sequence: item.event.sequence,
						observation,
					};
			}
			const blocking_events = blockers.map((event) => snapshot.view.events[event.sequence - 1]!);
			return {
				member,
				candidate,
				blocking_events,
				state: candidate
					? "PASS"
					: blockers.some((event) => event.result === "FAIL")
						? "FAIL"
						: cutoff
							? "ERROR"
							: "MISSING",
			};
		});
	}
	async preserveRecoveredOwner(input: OwnerRecord): Promise<FileRef> {
		const owner = validateOwnerRecord(input);
		const relative = `${BASE}/recovered-owners/${owner.owner_id}.json`;
		const bytes = C(owner);
		try {
			const existing = await readBytes(this.root, relative);
			if (!existing.equals(Buffer.from(bytes))) fail("recovered owner immutable snapshot differs");
			return { path: relative, hash: H(existing), size: existing.length };
		} catch (error) {
			if (errorCode(error) !== "ENOENT") throw error;
		}
		return this.writeImmutableFile(relative, bytes);
	}
	private async retireRecoveredHistoryAliases(owner: OwnerRecord): Promise<void> {
		const base = await checkedPath(this.root, BASE);
		for (const name of await fs.readdir(base)) {
			if (!/^\.staging-file-[0-9]{20}\.json-[0-9a-f-]+$/.test(name)) continue;
			const temporary = `${BASE}/${name}`;
			const file = await checkedPath(this.root, temporary);
			const stat = await fs.lstat(file);
			if (!stat.isFile()) fail("unsafe abandoned history staging entry");
			owned(stat, temporary);
			if (stat.nlink === 1) continue;
			if (stat.nlink !== 2) fail("unprovable abandoned history aliases");
			const handle = await fs.open(file, constants.O_RDONLY | constants.O_NOFOLLOW);
			let bytes: Buffer;
			try {
				const opened = await handle.stat();
				if (opened.dev !== stat.dev || opened.ino !== stat.ino || opened.nlink !== 2) fail("abandoned staging changed");
				bytes = await handle.readFile();
			} finally {
				await handle.close();
			}
			const event = validateHistoryEvent(parseJSON(bytes));
			if (
				event.event_id !== D("history-event", without(event, "event_id")) ||
				!owner.pending_results.some(
					(pending) =>
						pending.kind === event.kind &&
						pending.execution_key === event.execution_key &&
						pending.attempt_id === event.attempt_id &&
						pending.claim_id === event.claim_id &&
						pending.slot_id === event.slot_id &&
						equal(pending.members, event.members),
				)
			)
				fail("abandoned history alias is not owned by recovered pending result");
			const target = await checkedPath(this.root, `${BASE}/history/${String(event.sequence).padStart(20, "0")}.json`);
			const targetStat = await fs.lstat(target);
			if (!targetStat.isFile() || targetStat.dev !== stat.dev || targetStat.ino !== stat.ino || targetStat.nlink !== 2)
				fail("abandoned history alias target mismatch");
			this.writeEpoch++;
			await fs.unlink(file);
			const finalHandle = await fs.open(target, constants.O_RDONLY | constants.O_NOFOLLOW);
			try {
				await seam(this.options, "fsync", target, () => finalHandle.sync());
			} finally {
				await finalHandle.close();
			}
			await syncAncestors(this.root, path.dirname(target), this.options);
		}
	}
	async accountPending(owner: OwnerRecord): Promise<HistoryRef[]> {
		if (!this.options.withAppendLock) fail("recovery requires native owner/append mutex");
		return this.options.withAppendLock(async () => {
			const preserved = await this.preserveRecoveredOwner(owner);
			await this.retireRecoveredHistoryAliases(owner);
			const result: HistoryRef[] = [];
			for (const pending of owner.pending_results) {
				const snapshot = await this.loadHistory(undefined, true);
				const unresolvedOwnership = owner.spawn_windows.some(
					(window) =>
						window.execution_key === pending.execution_key &&
						window.attempt_id === pending.attempt_id &&
						window.state !== "closed",
				);
				const existing = snapshot.events.find(
					(event) =>
						event.execution_key === pending.execution_key &&
						event.attempt_id === pending.attempt_id &&
						event.claim_id === pending.claim_id &&
						event.slot_id === pending.slot_id &&
						((!unresolvedOwnership &&
							event.kind === pending.kind &&
							(pending.kind === "execution" ||
								event.observation?.path.startsWith(`${BASE}/runs/${owner.run_id}/observations/`))) ||
							(event.kind === "indeterminate" && equal(event.indeterminate_owner, preserved))),
				);
				if (existing) {
					const reference = snapshot.view.events[existing.sequence - 1]!;
					const absolute = await checkedPath(this.root, reference.path);
					const handle = await fs.open(absolute, constants.O_RDONLY | constants.O_NOFOLLOW);
					try {
						await seam(this.options, "fsync", absolute, () => handle.sync());
					} finally {
						await handle.close();
					}
					await syncAncestors(this.root, path.dirname(absolute), this.options);
					result.push(reference);
					continue;
				}
				result.push(
					await this.appendUnlocked({
						schema_version: "fv-evidence-history/v1",
						kind: "indeterminate",
						execution_key: pending.execution_key,
						attempt_id: pending.attempt_id,
						members: pending.members,
						execution: null,
						claim_id: pending.claim_id,
						slot_id: pending.slot_id,
						observation: null,
						indeterminate_owner: preserved,
						result: "ERROR",
					}),
				);
			}
			await this.readHistory();
			return result;
		});
	}
	async publishClaim(input: Omit<ClaimRecord, "record_id">): Promise<FileRef> {
		const claim = validateClaimRecord({ ...input, record_id: D("claim-record", input) });
		return this.writeImmutableJSON(`${BASE}/runs/${claim.run_id}/claims/${claim.claim_id}.json`, claim);
	}
	private async validateGeneration(manifest: RunManifest): Promise<void> {
		const history = await this.readHistory(manifest.history);
		if (
			manifest.policy_path !== manifest.common.policy_path ||
			manifest.policy_hash !== manifest.common.policy_hash ||
			manifest.started_at > manifest.finished_at
		)
			fail("run common/time binding mismatch");
		const states: { required: boolean; result: ClaimRecord["result"] }[] = [];
		for (const entry of manifest.claims) {
			if (entry.record.path !== `${BASE}/runs/${manifest.run_id}/claims/${entry.claim_id}.json`)
				fail("claim reference outside run");
			const claim = validateClaimRecord(parseJSON(await this.readFileRef(entry.record)));
			if (
				claim.run_id !== manifest.run_id ||
				claim.claim_id !== entry.claim_id ||
				!equal(claim.common, manifest.common) ||
				D("claim-record", without(claim, "record_id")) !== claim.record_id
			)
				fail("claim canonical/common identity mismatch");
			for (const slot of claim.executions) {
				for (const blocker of slot.blocking_events)
					if (!equal(history.view.events[blocker.sequence - 1], blocker))
						fail("claim failure reference is not retained history");
				if (slot.execution !== null) {
					const artifact = await this.readExecution(slot.execution);
					if (
						!equal(artifact.descriptor.common, claim.common) ||
						artifact.descriptor.recipe.recipe_id !== slot.recipe_id ||
						artifact.descriptor.recipe.evidence_class !== slot.evidence_class ||
						!artifact.descriptor.members.some(
							(member) =>
								member.claim_id === claim.claim_id && member.slot_id === slot.slot_id && member.tool === slot.tool,
						)
					)
						fail("claim execution association mismatch");
					if (slot.state === "PASS" && artifact.result !== "PASS")
						fail("claim PASS references unsuccessful physical work");
				} else if (slot.state === "PASS") fail("claim PASS lacks execution");
				if (slot.observation !== null) {
					const check = validateObservationCheck(parseJSON(await this.readFileRef(slot.observation.check)));
					if (!equal(check.response, slot.observation.response)) fail("claim response reference differs from receipt");
					if (slot.state === "PASS" && slot.observation.result !== "PASS")
						fail("claim PASS lacks passing own observation");
					const event = history.events.find(
						(item) =>
							item.kind === "observation" &&
							equal(item.observation, slot.observation!.check) &&
							item.claim_id === claim.claim_id &&
							item.slot_id === slot.slot_id &&
							item.result === slot.observation!.result &&
							equal(item.execution, slot.execution),
					);
					if (!event) fail("claim observation has no matching retained event");
				} else if (slot.state === "PASS") fail("claim PASS lacks member observations");
				const member = { claim_id: claim.claim_id, slot_id: slot.slot_id, tool: slot.tool };
				const blockers = history.events.filter((event) => barrierApplies(event, member));
				const cutoff = blockers.at(-1)?.sequence ?? 0;
				if (slot.state === "PASS") {
					const actual = history.events.find(
						(event) => event.kind === "execution" && event.result === "PASS" && equal(event.execution, slot.execution),
					);
					if (!actual || actual.sequence <= cutoff) fail("claim PASS predates own canonical failure cutoff");
					if (
						!history.events.some(
							(event) =>
								event.kind === "observation" &&
								event.result === "PASS" &&
								event.sequence > actual.sequence &&
								event.claim_id === claim.claim_id &&
								event.slot_id === slot.slot_id &&
								equal(event.execution, slot.execution),
						)
					)
						fail("claim PASS lacks subsequent own observation");
				} else if (blockers.some((event) => event.result === "FAIL") && slot.state !== "FAIL")
					fail("claim hides an unsuperseded canonical failure");
			}
			const memberResult = claim.executions.some((slot) => slot.state === "FAIL")
				? "FAIL"
				: claim.executions.every((slot) => slot.state === "PASS")
					? "PASS"
					: "INCOMPLETE";
			// Dependency/tool coverage can keep a claim incomplete after its own members pass.
			if (memberResult === "PASS" ? claim.result === "FAIL" : claim.result !== memberResult)
				fail("claim result contradicts member states");
			states.push({ required: claim.required, result: claim.result });
		}
		for (const required of manifest.required_records)
			if (!manifest.claims.some((claim) => claim.claim_id === required)) fail("run omits a required claim");
		for (const check of manifest.preflight.checks)
			for (const ref of [check.stdout, check.stderr]) if (ref !== null) await this.readFileRef(ref);
		for (const work of manifest.work)
			if (work.execution !== null) {
				const artifact = await this.readExecution(work.execution);
				if (
					work.execution_key !== artifact.execution_key ||
					work.recipe_id !== artifact.descriptor.recipe.recipe_id ||
					!equal(work.distinct_slot, artifact.descriptor.distinct_slot)
				)
					fail("run work association mismatch");
			}
		if (states.some((claim) => claim.required && claim.result === "FAIL") && manifest.result !== "FAIL")
			fail("run erases a required claim failure");
		if (
			manifest.result === "PASS" &&
			(states.some((claim) => claim.required && claim.result !== "PASS") ||
				!manifest.source_before ||
				!manifest.source_after ||
				!manifest.source_before.clean ||
				!manifest.source_after.clean ||
				!equal(manifest.source_before, manifest.source_after))
		)
			fail("run PASS has missing/unstable requirements");
	}
	async publishRun(input: RunManifest): Promise<FileRef> {
		const manifest = validateRunManifest(input);
		await this.validateGeneration(manifest);
		const result = await this.writeImmutableJSON(`${BASE}/runs/${manifest.run_id}/run.json`, manifest);
		await this.fsyncTree(`${BASE}/runs/${manifest.run_id}`);
		return result;
	}
	async publishCurrent(candidate: FileRef): Promise<Publication> {
		this.writeEpoch++;
		let replaced = false;
		let validatedCandidate: FileRef | null = null;
		try {
			const manifest = validateRunManifest(parseJSON(await this.readFileRef(candidate)));
			if (candidate.path !== `${BASE}/runs/${manifest.run_id}/run.json`) fail("pointer candidate is not immutable run");
			validatedCandidate = candidate;
			await this.validateGeneration(manifest);
			await this.fsyncTree(`${BASE}/runs/${manifest.run_id}`);
			const pointer = validateCurrentPointer({
				schema_version: "fv-evidence-current/v1",
				run_id: manifest.run_id,
				run: candidate,
			});
			const temporary = `${BASE}/.current-${randomUUID()}.json`;
			await writeNew(this.root, temporary, C(pointer), this.options);
			const target = await checkedPath(this.root, `${BASE}/current.json`, true);
			try {
				const stat = await fs.lstat(target);
				if (!stat.isFile() || stat.nlink !== 1) fail("unsafe current pointer");
				owned(stat, target);
			} catch (error) {
				if (errorCode(error) !== "ENOENT") throw error;
			}
			await this.options.syscallBarrier?.("rename", target, "before");
			await fs.rename(await checkedPath(this.root, temporary), target);
			replaced = true;
			await this.options.syscallBarrier?.("rename", target, "after");
			await syncAncestors(this.root, path.dirname(target), this.options);
			return { state: "durable", candidate };
		} catch {
			return { state: replaced ? "post-replace-error" : "pre-replace-error", candidate: validatedCandidate };
		}
	}
}

export async function openEvidenceStore(root: string, options: StoreOptions = {}): Promise<Store> {
	return new Store(await rootPath(root), options);
}
