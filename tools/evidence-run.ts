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
/** Mirrors `EVIDENCE_TOOL_ID` in `scripts/check_evidence_records.py`: a cohort's tool
 * IDs are what `system_claim.required_evidence` names, so both ends agree on the shape. */
const EVIDENCE_TOOL_ID = /^[A-Za-z0-9][A-Za-z0-9._:+/-]*$/;

type ExecResult = { stdout: string; stderr: string; code: number };
type Exec = (command: string, args: string[], options: { cwd: string; signal?: AbortSignal }) => Promise<ExecResult>;
type ToolchainDigests = { executable: string; sha256: string; version: string; version_exit_code: number };

/** One requested execution, after argument validation and before the project is touched. */
type ExecutionRequest = {
	tool: string;
	command: string[];
	cwd: string | undefined;
	evidenceClass: string;
	passMarker: string | undefined;
};

/** A request whose cwd, executable identity, run id, and raw-artifact path are resolved. */
type PlannedExecution = ExecutionRequest & {
	cwdRelative: string;
	cwdAbsolute: string;
	executable: string;
	toolchainDigests: ToolchainDigests;
	runId: string;
	rawRelative: string;
	rawAbsolute: string;
};

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

type EvidenceParams = {
	claim_id: string;
	command?: string[];
	cwd?: string;
	evidence_class: string;
	scope: string;
	required?: boolean;
	pass_marker?: string;
	tool?: string;
	executions?: { tool: string; command: string[]; cwd?: string; evidence_class?: string; pass_marker?: string }[];
};

/** The cohort a call requests: either the legacy single command (with its top-level
 * `cwd`/`tool`/`pass_marker`) or an explicit `executions` array. Exactly one of the two
 * forms is accepted, so no call can leave it ambiguous which command produced the
 * record's legacy bindings. */
function cohortRequests(params: EvidenceParams): ExecutionRequest[] {
	const legacy = params.command !== undefined;
	const cohort = params.executions !== undefined;
	if (legacy === cohort) {
		throw new Error("provide exactly one of command or executions");
	}
	if (legacy) {
		const command = params.command!;
		if (command.length === 0 || command.some(part => part.length === 0)) {
			throw new Error("command must contain non-empty argv elements");
		}
		if (params.tool !== undefined && params.tool.trim().length === 0) {
			throw new Error("tool must be a non-empty evidence tool identifier");
		}
		if (params.pass_marker !== undefined && params.pass_marker.length === 0) {
			throw new Error("pass_marker must be non-empty");
		}
		return [{
			tool: params.tool?.trim() ?? path.basename(command[0]!),
			command,
			cwd: params.cwd,
			evidenceClass: params.evidence_class,
			passMarker: params.pass_marker,
		}];
	}
	if (params.cwd !== undefined || params.tool !== undefined || params.pass_marker !== undefined) {
		throw new Error("cwd, tool, and pass_marker are per-execution when executions is used");
	}
	const requested = params.executions!;
	if (requested.length === 0) throw new Error("executions must be a non-empty array");
	const requests: ExecutionRequest[] = [];
	const seen = new Set<string>();
	for (let index = 0; index < requested.length; index += 1) {
		const entry = requested[index]!;
		const where = `executions[${index}]`;
		if (entry === null || typeof entry !== "object") throw new Error(`${where} must be an object`);
		const tool = typeof entry.tool === "string" ? entry.tool.trim() : "";
		if (!EVIDENCE_TOOL_ID.test(tool)) {
			throw new Error(`${where}.tool must be an evidence tool identifier: ${JSON.stringify(entry.tool)}`);
		}
		if (seen.has(tool)) {
			throw new Error(`${where}.tool duplicates '${tool}': cohort evidence coverage would be ambiguous`);
		}
		seen.add(tool);
		if (
			!Array.isArray(entry.command) || entry.command.length === 0
			|| entry.command.some(part => typeof part !== "string" || part.length === 0)
		) {
			throw new Error(`${where}.command must contain non-empty argv elements`);
		}
		const evidenceClass = entry.evidence_class ?? params.evidence_class;
		if (!PASS_MARKERS[evidenceClass]) throw new Error(`${where}.evidence_class is unknown: ${evidenceClass}`);
		if (entry.pass_marker !== undefined && entry.pass_marker.length === 0) {
			throw new Error(`${where}.pass_marker must be non-empty`);
		}
		requests.push({
			tool,
			command: entry.command,
			cwd: entry.cwd,
			evidenceClass,
			passMarker: entry.pass_marker,
		});
	}
	return requests;
}

const factory: CustomToolFactory = pi => ({
	name: "fv_evidence_run",
	label: "FV Evidence Run",
	description: "Run one argv command, or a cohort of them atomically, and persist a hash-bound FV evidence record.",
	approval: "exec",
	parameters: pi.zod.object({
		claim_id: pi.zod.string(),
		command: pi.zod.array(pi.zod.string()).optional(),
		cwd: pi.zod.string().optional(),
		evidence_class: pi.zod.string(),
		scope: pi.zod.string(),
		required: pi.zod.boolean().optional(),
		pass_marker: pi.zod.string().optional(),
		tool: pi.zod.string().optional(),
		executions: pi.zod
			.array(
				pi.zod.object({
					tool: pi.zod.string(),
					command: pi.zod.array(pi.zod.string()),
					cwd: pi.zod.string().optional(),
					evidence_class: pi.zod.string().optional(),
					pass_marker: pi.zod.string().optional(),
				}),
			)
			.optional(),
	}),

	async execute(_toolCallId, params, _onUpdate, _ctx, signal) {
		if (!/^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(params.claim_id)) {
			throw new Error("claim_id must be a filesystem-safe identifier");
		}
		const classMarker = PASS_MARKERS[params.evidence_class];
		if (!classMarker) throw new Error(`unknown evidence_class: ${params.evidence_class}`);
		const call = params as EvidenceParams;
		const requests = cohortRequests(call);
		const isCohortCall = call.executions !== undefined;
		const exec: Exec = (command, args, options) => pi.exec(command, args, options);
		const projectRoot = await fs.realpath(path.resolve(pi.cwd));
		const timestamp = new Date().toISOString().replace(/[:.]/g, "-");
		const recordPath = path.join(projectRoot, ".fv", "evidence", "records", `${params.claim_id}.json`);

		const target = await resolveCanonicalTarget(projectRoot);
		const manifestPath = path.join(projectRoot, ".fv", "obligations.json");
		const intentHash = await requiredFileHash(target.absolute, "intent");
		const manifestHash = await requiredFileHash(manifestPath, "obligation manifest");
		const manifest = await Bun.file(manifestPath).json();

		// Resolve every execution's cwd and executable identity before running any of
		// them: a cohort with one unresolvable tool must not leave half a cohort behind.
		const planned: PlannedExecution[] = [];
		for (let index = 0; index < requests.length; index += 1) {
			const request = requests[index]!;
			const cwdAbsolute = await fs.realpath(path.resolve(projectRoot, request.cwd ?? "."));
			if (!insideRoot(projectRoot, cwdAbsolute)) {
				throw new Error("cwd must resolve inside the project root");
			}
			const requestedExecutable = request.command[0]!;
			const executableLookup = requestedExecutable.includes("/") || requestedExecutable.includes("\\")
				? path.resolve(cwdAbsolute, requestedExecutable)
				: Bun.which(requestedExecutable);
			if (!executableLookup) throw new Error(`command executable not found: ${requestedExecutable}`);
			const executable = await fs.realpath(executableLookup);
			const versionProbe = await exec(executable, ["--version"], { cwd: cwdAbsolute, signal });
			// Per-execution raw artifacts need filesystem-safe, collision-free names.
			const runId = isCohortCall
				? `${timestamp}-${index + 1}-${request.tool.replace(/[^A-Za-z0-9._-]+/g, "-")}`
				: timestamp;
			const rawRelative = path.join(".fv", "evidence", "raw", `${params.claim_id}-${runId}.log`);
			planned.push({
				...request,
				cwdAbsolute,
				cwdRelative: path.relative(projectRoot, cwdAbsolute).split(path.sep).join("/") || ".",
				executable,
				toolchainDigests: {
					executable,
					sha256: await sha256File(executable),
					version: (versionProbe.stdout + versionProbe.stderr).trim(),
					version_exit_code: versionProbe.code,
				},
				runId,
				rawRelative,
				rawAbsolute: path.join(projectRoot, rawRelative),
			});
		}

		const exclusions = await loadExclusions(projectRoot);
		const snapshot = await verifiedInputSnapshot(projectRoot, exclusions, exec, signal);
		const beforeStatus = await exec("git", ["status", "--porcelain", "--untracked-files=all", "-z"],
			{ cwd: projectRoot, signal });
		if (beforeStatus.code !== 0) throw new Error("git status failed before evidence command");
		// Bindings are checked around every execution, so a cohort whose second command
		// edits a verified input cannot ship as PASS evidence for its first.
		let dirty = dirtyVerifiedInputs(beforeStatus.stdout, exclusions).length > 0;

		const executions: Record<string, unknown>[] = [];
		const exitCodes: number[] = [];
		for (const plan of planned) {
			const run = await exec(plan.executable, plan.command.slice(1), { cwd: plan.cwdAbsolute, signal });
			const trailer = `--- fv-evidence: exit=${run.code} ---`;
			const streams = [run.stdout, run.stderr]
				.filter(stream => stream.length > 0)
				.map(stream => (stream.endsWith("\n") ? stream : stream + "\n"));
			const rawOutput = streams.join("") + trailer + "\n";
			await Bun.write(plan.rawAbsolute, rawOutput);
			const rawOutputHash = await sha256File(plan.rawAbsolute);
			const markerMatched = plan.passMarker
				? rawOutput.includes(plan.passMarker)
				: PASS_MARKERS[plan.evidenceClass]!.test(rawOutput);
			const snapshotAfter = await verifiedInputSnapshot(projectRoot, exclusions, exec, signal);
			const intentHashAfter = await requiredFileHash(target.absolute, "intent");
			const manifestHashAfter = await requiredFileHash(manifestPath, "obligation manifest");
			const afterStatus = await exec("git", ["status", "--porcelain", "--untracked-files=all", "-z"],
				{ cwd: projectRoot, signal });
			if (afterStatus.code !== 0) throw new Error("git status failed after evidence command");
			if (snapshotAfter !== snapshot || intentHashAfter !== intentHash || manifestHashAfter !== manifestHash) {
				dirty = true;
			}
			if (dirtyVerifiedInputs(afterStatus.stdout, exclusions).length > 0) dirty = true;
			exitCodes.push(run.code);
			executions.push({
				tool: plan.tool,
				evidence_class: plan.evidenceClass,
				command: plan.command,
				cwd: plan.cwdRelative,
				toolchain_digests: plan.toolchainDigests,
				raw_output_path: plan.rawRelative,
				raw_output_hash: rawOutputHash,
				result: run.code === 0 && markerMatched ? "PASS" : "FAIL",
				run_id: plan.runId,
				...(plan.passMarker ? { pass_marker: plan.passMarker } : {}),
			});
		}

		// The cohort is one atomic verdict: every execution must pass and the bindings
		// must have held still for the whole run.
		const allPassed = executions.every(execution => execution.result === "PASS");
		const result = allPassed && !dirty ? "PASS" : "FAIL";

		const requiredTargets = [
			...(Array.isArray(manifest.invariants) ? manifest.invariants : []),
			...(Array.isArray(manifest.witnesses) ? manifest.witnesses : []),
			...(Array.isArray(manifest.system_claims) ? manifest.system_claims : []),
		]
			.map(item => item?.id)
			.filter((id): id is string => typeof id === "string" && id.length > 0);
		if (requiredTargets.length === 0) throw new Error(`obligation manifest has no targets: ${manifestPath}`);

		// v2 consumers read one command and one artifact per record: the sole (or, for a
		// cohort, the first) execution is what they see.
		const primary = executions[0]!;
		const primaryPlan = planned[0]!;
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
				toolchain_digests: primary.toolchain_digests,
				command: JSON.stringify(primary.command),
				configuration: {
					cwd: primary.cwd,
					...(primaryPlan.passMarker ? { pass_marker: primaryPlan.passMarker } : {}),
				},
				seeds: null,
				raw_output_hash: primary.raw_output_hash,
				raw_output_path: primary.raw_output_path,
				executions,
				parser_schema_version: "fv-evidence-run/v3",
				run_id: timestamp,
			},
			waiver: null,
		};
		await Bun.write(recordPath, `${JSON.stringify(record, null, 2)}\n`);
		const summary = executions.length > 1
			? executions.map(execution => `  ${execution.tool}: ${execution.result}`).join("\n") + "\n"
			: "";
		return {
			content: [{
				type: "text",
				text: `${result}: ${params.claim_id}\n${summary}${path.relative(projectRoot, recordPath)}`,
			}],
			details: {
				record,
				recordPath,
				rawPath: primaryPlan.rawAbsolute,
				rawPaths: planned.map(plan => plan.rawAbsolute),
				exitCode: exitCodes[0]!,
				exitCodes,
			},
		};
	},
});

export default factory;
