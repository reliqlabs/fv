import * as fs from "node:fs/promises";
import * as path from "node:path";
import type { CustomToolFactory } from "@oh-my-pi/pi-coding-agent";

const PASS_MARKERS: Record<string, RegExp> = {
	"code-enforced": /--- fv-evidence: exit=0 ---/,
	"proof-discharged": /(?:VERIFICATION:- SUCCESSFUL|Build completed successfully|--- fv-evidence: exit=0 ---)/,
	"bounded-checked": /(?:\[ok\]|VERIFICATION:- SUCCESSFUL|No violation found)/,
	"test-witnessed": /test result: ok\./,
	"conformance-tested": /(?:CONFORMANCE(?:_TESTED)?: PASS|test result: ok\.|--- fv-evidence: exit=0 ---)/,
	"externally-assumed": /--- fv-evidence: exit=0 ---/,
	unverified: /--- fv-evidence: exit=0 ---/,
};

/** Generated FV output. Never part of the verified-input snapshot, so producing and
 * committing evidence cannot invalidate the records it just wrote. */
const DEFAULT_EXCLUSIONS = [".fv/evidence/", ".fv/verify/", ".fv/panels/", ".colosseum/"];
const DEFAULT_TARGET_SPEC = ".fv/intent.md";
const NUL = new Uint8Array([0]);

type ExecResult = { stdout: string; stderr: string; code: number };
type Exec = (command: string, args: string[], options: { cwd: string; signal?: AbortSignal }) => Promise<ExecResult>;

async function sha256File(filePath: string): Promise<string> {
	const bytes = await Bun.file(filePath).arrayBuffer();
	return new Bun.CryptoHasher("sha256").update(bytes).digest("hex");
}

async function requiredFileHash(filePath: string, label: string): Promise<string> {
	const file = Bun.file(filePath);
	if (!(await file.exists())) throw new Error(`${label} is missing: ${filePath}`);
	return sha256File(filePath);
}

function insideRoot(root: string, candidate: string): boolean {
	return candidate === root || candidate.startsWith(root + path.sep);
}

/** `omp_native.target_spec` from `.fv/dispatch.json`, or null when unset. Mirrors
 * `fv_project.declared_target_spec`. */
async function declaredTargetSpec(projectRoot: string): Promise<string | null> {
	const dispatch = Bun.file(path.join(projectRoot, ".fv", "dispatch.json"));
	if (!(await dispatch.exists())) return null;
	let parsed: unknown;
	try {
		parsed = await dispatch.json();
	} catch (error) {
		throw new Error(`cannot read .fv/dispatch.json: ${error instanceof Error ? error.message : String(error)}`);
	}
	if (parsed === null || typeof parsed !== "object") throw new Error(".fv/dispatch.json is not a JSON object");
	if (!("omp_native" in parsed)) return null;
	const route = parsed.omp_native;
	if (route === null || typeof route !== "object") throw new Error(".fv/dispatch.json omp_native is not a JSON object");
	if (!("target_spec" in route)) return null;
	const declared = route.target_spec;
	if (declared === undefined || declared === null) return null;
	if (typeof declared !== "string") throw new Error(".fv/dispatch.json omp_native.target_spec is not a string");
	return declared.trim().length > 0 ? declared : null;
}

/** The canonical verification target: declared `target_spec` resolved under the project
 * root, else `.fv/intent.md`. Rejects escaping, symlinked, directory, and missing
 * targets exactly as `fv_project.resolve_target` does, so producer and gate bind the
 * same file. */
async function resolveCanonicalTarget(projectRoot: string): Promise<{ absolute: string; relative: string }> {
	const spec = (await declaredTargetSpec(projectRoot)) ?? DEFAULT_TARGET_SPEC;
	const resolved = path.resolve(projectRoot, spec);
	if (!insideRoot(projectRoot, resolved)) throw new Error(`target_spec escapes project root: ${spec}`);
	const info = await fs.lstat(resolved).catch(() => null);
	if (info === null) throw new Error(`target_spec does not exist: ${spec}`);
	if (info.isSymbolicLink()) throw new Error(`target_spec is a symlink: ${spec}`);
	if (info.isDirectory()) throw new Error(`target_spec is a directory: ${spec}`);
	if (!info.isFile()) throw new Error(`target_spec does not exist: ${spec}`);
	const real = await fs.realpath(resolved);
	if (!insideRoot(projectRoot, real)) throw new Error(`target_spec escapes project root: ${spec}`);
	return { absolute: real, relative: path.relative(projectRoot, real).split(path.sep).join("/") };
}

/** Exclusion prefixes: the generated-output defaults unioned with
 * `.fv/verified-inputs.txt`. Mirrors `fv_project.load_exclusions`. */
async function loadExclusions(projectRoot: string): Promise<string[]> {
	const listFile = Bun.file(path.join(projectRoot, ".fv", "verified-inputs.txt"));
	const exclusions = [...DEFAULT_EXCLUSIONS];
	if (!(await listFile.exists())) return exclusions;
	const lines = (await listFile.text()).split("\n");
	for (let index = 0; index < lines.length; index += 1) {
		const line = lines[index]!.trim();
		if (line.length === 0 || line.startsWith("#")) continue;
		const entry = line.startsWith("./") ? line.slice(2) : line;
		const location = `.fv/verified-inputs.txt:${index + 1}`;
		if (entry.length === 0 || entry === "." || entry === "/") {
			throw new Error(`${location}: entry excludes the whole project`);
		}
		if (path.isAbsolute(entry)) throw new Error(`${location}: absolute entry '${entry}'`);
		if (entry.split("/").includes("..")) throw new Error(`${location}: entry escapes project root: '${entry}'`);
		if (!exclusions.includes(entry)) exclusions.push(entry);
	}
	return exclusions;
}

/** Trailing-slash entries are literal path prefixes; bare entries match whole components. */
function isExcluded(relative: string, exclusions: readonly string[]): boolean {
	return exclusions.some(entry =>
		entry.endsWith("/") ? relative.startsWith(entry) : relative === entry || relative.startsWith(`${entry}/`),
	);
}

/** `sha256:<hex>` over every tracked-or-untracked, unignored, non-excluded file:
 * UTF-8 path, NUL, content SHA-256 hex, newline, concatenated in UTF-8 byte order. */
async function verifiedInputSnapshot(
	projectRoot: string,
	exclusions: readonly string[],
	exec: Exec,
	signal?: AbortSignal,
): Promise<string> {
	const listed = await exec("git", ["ls-files", "--cached", "--others", "--exclude-standard", "-z"], {
		cwd: projectRoot,
		signal,
	});
	if (listed.code !== 0) throw new Error("git ls-files failed while enumerating verified inputs");
	const candidates = new Set<string>();
	for (const entry of listed.stdout.split("\0")) {
		if (entry.length === 0) continue;
		if (!isExcluded(entry, exclusions)) candidates.add(entry);
	}
	const hasher = new Bun.CryptoHasher("sha256");
	const ordered = [...candidates].sort((left, right) =>
		Buffer.compare(Buffer.from(left, "utf8"), Buffer.from(right, "utf8")));
	for (const relative of ordered) {
		const absolute = path.join(projectRoot, relative);
		const info = await fs.lstat(absolute).catch(() => null);
		if (info === null) continue; // tracked but deleted in the worktree; the absence is the change
		if (info.isSymbolicLink()) throw new Error(`verified input is a symlink: ${relative}`);
		if (!insideRoot(projectRoot, absolute)) throw new Error(`verified input escapes project root: ${relative}`);
		if (info.isDirectory()) continue; // submodule gitlink: verified by its own repository
		hasher.update(relative);
		hasher.update(NUL);
		hasher.update(await sha256File(absolute));
		hasher.update("\n");
	}
	return `sha256:${hasher.digest("hex")}`;
}

/** Non-excluded paths reported by `git status --porcelain -z`. Changes confined to
 * generated FV output are not dirt. */
function dirtyVerifiedInputs(status: string, exclusions: readonly string[]): string[] {
	const fields = status.split("\0");
	const dirty: string[] = [];
	for (let index = 0; index < fields.length; index += 1) {
		const field = fields[index]!;
		if (field.length < 4) continue;
		const changed = [field.slice(3)];
		if (/[RC]/.test(field.slice(0, 2))) {
			const original = fields[index + 1];
			index += 1;
			if (original) changed.push(original);
		}
		for (const relative of changed) {
			if (!isExcluded(relative, exclusions)) dirty.push(relative);
		}
	}
	return dirty;
}

const factory: CustomToolFactory = pi => ({
	name: "fv_evidence_run",
	label: "FV Evidence Run",
	description: "Run one argv command and persist a hash-bound FV evidence record.",
	approval: "exec",
	parameters: pi.zod.object({
		claim_id: pi.zod.string(),
		command: pi.zod.array(pi.zod.string()),
		cwd: pi.zod.string().optional(),
		evidence_class: pi.zod.string(),
		scope: pi.zod.string(),
		required: pi.zod.boolean().optional(),
		pass_marker: pi.zod.string().optional(),
		tool: pi.zod.string().optional(),
	}),

	async execute(_toolCallId, params, _onUpdate, _ctx, signal) {
		if (!/^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(params.claim_id)) {
			throw new Error("claim_id must be a filesystem-safe identifier");
		}
		if (params.command.length === 0 || params.command.some(part => part.length === 0)) {
			throw new Error("command must contain non-empty argv elements");
		}
		if (params.tool !== undefined && params.tool.trim().length === 0) {
			throw new Error("tool must be a non-empty evidence tool identifier");
		}
		const classMarker = PASS_MARKERS[params.evidence_class];
		if (!classMarker) throw new Error(`unknown evidence_class: ${params.evidence_class}`);
		const exec: Exec = (command, args, options) => pi.exec(command, args, options);
		const projectRoot = await fs.realpath(path.resolve(pi.cwd));
		const commandCwd = await fs.realpath(path.resolve(projectRoot, params.cwd ?? "."));
		if (!insideRoot(projectRoot, commandCwd)) {
			throw new Error("cwd must resolve inside the project root");
		}
		const timestamp = new Date().toISOString().replace(/[:.]/g, "-");
		const rawRelative = path.join(".fv", "evidence", "raw", `${params.claim_id}-${timestamp}.log`);
		const rawPath = path.join(projectRoot, rawRelative);
		const recordPath = path.join(projectRoot, ".fv", "evidence", "records", `${params.claim_id}.json`);

		const target = await resolveCanonicalTarget(projectRoot);
		const manifestPath = path.join(projectRoot, ".fv", "obligations.json");
		const intentHash = await requiredFileHash(target.absolute, "intent");
		const manifestHash = await requiredFileHash(manifestPath, "obligation manifest");
		const manifest = await Bun.file(manifestPath).json();
		const requestedExecutable = params.command[0]!;
		const executableLookup = requestedExecutable.includes("/") || requestedExecutable.includes("\\")
			? path.resolve(commandCwd, requestedExecutable)
			: Bun.which(requestedExecutable);
		if (!executableLookup) throw new Error(`command executable not found: ${requestedExecutable}`);
		const executable = await fs.realpath(executableLookup);
		const executableHash = await sha256File(executable);
		const versionProbe = await exec(executable, ["--version"], { cwd: commandCwd, signal });

		const exclusions = await loadExclusions(projectRoot);
		const snapshot = await verifiedInputSnapshot(projectRoot, exclusions, exec, signal);
		const beforeStatus = await exec("git", ["status", "--porcelain", "--untracked-files=all", "-z"],
			{ cwd: projectRoot, signal });
		if (beforeStatus.code !== 0) throw new Error("git status failed before evidence command");

		const execution = await exec(executable, params.command.slice(1), { cwd: commandCwd, signal });
		const snapshotAfter = await verifiedInputSnapshot(projectRoot, exclusions, exec, signal);
		const intentHashAfter = await requiredFileHash(target.absolute, "intent");
		const manifestHashAfter = await requiredFileHash(manifestPath, "obligation manifest");
		const afterStatus = await exec("git", ["status", "--porcelain", "--untracked-files=all", "-z"],
			{ cwd: projectRoot, signal });
		if (afterStatus.code !== 0) throw new Error("git status failed after evidence command");
		const bindingDrift = snapshot !== snapshotAfter
			|| intentHash !== intentHashAfter || manifestHash !== manifestHashAfter;
		const dirty = dirtyVerifiedInputs(beforeStatus.stdout, exclusions).length > 0
			|| dirtyVerifiedInputs(afterStatus.stdout, exclusions).length > 0
			|| bindingDrift;
		const trailer = `--- fv-evidence: exit=${execution.code} ---`;
		const streams = [execution.stdout, execution.stderr]
			.filter(stream => stream.length > 0)
			.map(stream => (stream.endsWith("\n") ? stream : stream + "\n"));
		const rawOutput = streams.join("") + trailer + "\n";
		await Bun.write(rawPath, rawOutput);
		const rawOutputHash = await sha256File(rawPath);
		const markerMatched = params.pass_marker ? rawOutput.includes(params.pass_marker) : classMarker.test(rawOutput);
		let result = execution.code === 0 && markerMatched ? "PASS" : "FAIL";
		if (dirty && result === "PASS") result = "FAIL";

		const requiredTargets = [
			...(Array.isArray(manifest.invariants) ? manifest.invariants : []),
			...(Array.isArray(manifest.witnesses) ? manifest.witnesses : []),
		]
			.map(item => item?.id)
			.filter((id): id is string => typeof id === "string" && id.length > 0);
		if (requiredTargets.length === 0) throw new Error(`obligation manifest has no targets: ${manifestPath}`);

		const toolchainDigests = {
			executable,
			sha256: executableHash,
			version: (versionProbe.stdout + versionProbe.stderr).trim(),
			version_exit_code: versionProbe.code,
		};
		const commandCwdRelative = path.relative(projectRoot, commandCwd).split(path.sep).join("/") || ".";
		const record = {
			claim_id: params.claim_id,
			required: params.required ?? true,
			evidence_class: params.evidence_class,
			result,
			scope: params.scope,
			bindings: {
				source_snapshot: snapshot + (dirty ? "+dirty" : ""),
				intent_path: target.relative,
				intent_hash: intentHash,
				obligation_manifest_hash: manifestHash,
				profile: "producer-trusted-execution",
				required_targets: requiredTargets,
				environment_policy: "omp-extension-tool",
				toolchain_digests: toolchainDigests,
				command: JSON.stringify(params.command),
				configuration: {
					cwd: commandCwdRelative,
					...(params.pass_marker ? { pass_marker: params.pass_marker } : {}),
				},
				seeds: null,
				raw_output_hash: rawOutputHash,
				raw_output_path: rawRelative,
				executions: [
					{
						tool: params.tool ?? path.basename(requestedExecutable),
						evidence_class: params.evidence_class,
						command: params.command,
						cwd: commandCwdRelative,
						toolchain_digests: toolchainDigests,
						raw_output_path: rawRelative,
						raw_output_hash: rawOutputHash,
						result,
						run_id: timestamp,
						...(params.pass_marker ? { pass_marker: params.pass_marker } : {}),
					},
				],
				parser_schema_version: "fv-evidence-run/v3",
				run_id: timestamp,
			},
			waiver: null,
		};
		await Bun.write(recordPath, `${JSON.stringify(record, null, 2)}\n`);
		return {
			content: [{ type: "text", text: `${result}: ${params.claim_id}\n${path.relative(projectRoot, recordPath)}` }],
			details: { record, recordPath, rawPath, exitCode: execution.code },
		};
	},
});

export default factory;
