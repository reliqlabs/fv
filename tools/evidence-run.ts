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

/** Generated FV output, including lifecycle reports, quarantined legacy history, and
 * in-flight migration staging. Never part of the verified-input snapshot, so producing
 * and committing evidence cannot invalidate the records it just wrote, writing the change
 * record / attack log / code-adversarial report a run produces cannot stale that run's
 * evidence, quarantining more history cannot invalidate live evidence, and a killed
 * migration's staging residue cannot either. Applied under an include policy too, so an
 * allowlist naming `.fv/` cannot pull generated output back in.
 * Mirrors `fv_project.DEFAULT_EXCLUSIONS`. */
const DEFAULT_EXCLUSIONS = [".fv/evidence/", ".fv/verify/", ".fv/panels/", ".fv/changes/",
	".fv/attacks/", ".fv/code-adversarial/", ".fv/history/", ".fv/.migrate-staging/",
	".colosseum/"];
/** Verified-input policy modes. `exclude` is the historical shape and what a file with no
 * directive means, so every list written before include mode existed keeps its meaning.
 * Mirrors `fv_project.MODE_EXCLUDE` / `fv_project.MODE_INCLUDE`. */
const MODE_EXCLUDE = "exclude";
const MODE_INCLUDE = "include";
const POLICY_MODES: readonly string[] = [MODE_EXCLUDE, MODE_INCLUDE];
/** A mode directive is the first non-comment line or nothing. `mode: include` is the
 * canonical spelling; `mode:include` and interior padding parse the same. A line whose
 * lowercased head is this prefix but whose value names no known mode is rejected rather
 * than read as a path entry. Mirrors `fv_project.MODE_DIRECTIVE_PREFIX`. */
const MODE_DIRECTIVE_PREFIX = "mode:";
const VERIFIED_INPUTS_RELATIVE = ".fv/verified-inputs.txt";
const DEFAULT_TARGET_SPEC = ".fv/intent.md";
const NUL = new Uint8Array([0]);
/** Mirrors `EVIDENCE_TOOL_ID` in `scripts/check_evidence_records.py`: a cohort's tool
 * IDs are what `system_claim.required_evidence` names, so both ends agree on the shape. */
const EVIDENCE_TOOL_ID = /^[A-Za-z0-9][A-Za-z0-9._:+/-]*$/;
/** The only id shape a record file can carry, and therefore the only obligation id the
 * gate can ever see covered; `load_manifest` rejects the rest for the same reason. */
const CLAIM_ID = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;
/** Evidence that is asserted rather than checked. Gate B refuses to PASS such a record
 * without a waiver and this producer never writes one, so producing it at all would mint
 * a record whose only reachable verdict is INCOMPLETE. */
const ASSUMED_CLASSES: Record<string, true> = { "externally-assumed": true, unverified: true };
/** Mirrors `OBLIGATION_EVIDENCE_COMPATIBILITY` in `scripts/check_evidence_records.py`:
 * which classes may discharge each obligation kind. Applied to the record's class and to
 * every execution's class, so a cohort cannot smuggle a witness-only class under an
 * invariant behind a stronger record-level declaration. */
const OBLIGATION_EVIDENCE_COMPATIBILITY: Record<string, Record<string, true>> = {
	invariant: {
		"code-enforced": true,
		"proof-discharged": true,
		"bounded-checked": true,
		"conformance-tested": true,
		"externally-assumed": true,
		unverified: true,
	},
	witness: {
		"test-witnessed": true,
		"conformance-tested": true,
		"externally-assumed": true,
		unverified: true,
	},
	// A system claim is discharged by a cohort of tool executions, so any per-tool class
	// may appear beneath it.
	system_claim: {
		"code-enforced": true,
		"proof-discharged": true,
		"bounded-checked": true,
		"test-witnessed": true,
		"conformance-tested": true,
		"externally-assumed": true,
		unverified: true,
	},
};
const OBLIGATION_COLLECTIONS: readonly (readonly [string, string])[] = [
	["invariants", "invariant"],
	["witnesses", "witness"],
	["system_claims", "system_claim"],
];
/** The producer's own artifact trailer. A command that prints one of these would make the
 * artifact carry two, which Gate B rejects for any PASS execution. */
const TRAILER_LINE = /^--- fv-evidence: exit=\d+ ---$/;
/** Line terminators `str.splitlines` honours and `String.split("\n")` does not. Rejecting
 * them keeps `.fv/verified-inputs.txt` parseable to exactly one exclusion set on both
 * sides; mirrors `fv_project.AMBIGUOUS_LINE_CHARS`. CRLF stays legal. */
const AMBIGUOUS_LINE_CHARS = "\v\f\x1c\x1d\x1e\u0085\u2028\u2029";
/** A byte-order mark. Python's `utf-8` decode keeps it as a character while the WHATWG
 * decode drops a leading one, so one list would yield two exclusion sets with nothing to
 * attribute the difference to. Rejected anywhere in the file rather than stripped, which
 * is why the list below is decoded with `ignoreBOM`: the scan has to be able to see one.
 * Mirrors `fv_project.BOM_CHAR`. */
const BOM_CHAR = "\ufeff";
/** C0 controls, DEL, and C1 controls: none is a legal exclusion-list character. LF, and
 * the CR of a CRLF pair, separate entries; `AMBIGUOUS_LINE_CHARS` are reported as
 * terminators; every remaining control is either stripped by one side's whitespace rule
 * only (\x1f), invisible inside an entry (\t), or unrepresentable in a path (\x00).
 * Characters above U+009F are kept verbatim, so a path with non-ASCII components is a
 * legal entry. Mirrors `fv_project._is_control`. */
function isControlChar(char: string): boolean {
	const code = char.charCodeAt(0);
	return code <= 0x1f || (code >= 0x7f && code <= 0x9f);
}
/** Python's `repr()` of one character, so both ends name the offender identically. */
function charRepr(char: string): string {
	const code = char.charCodeAt(0);
	if (code === 0x09) return "'\\t'";
	if (code === 0x0a) return "'\\n'";
	if (code === 0x0d) return "'\\r'";
	const hex = code.toString(16);
	return code <= 0xff ? `'\\x${hex.padStart(2, "0")}'` : `'\\u${hex.padStart(4, "0")}'`;
}
/** `str.isspace()`, which `String.trim` neither contains nor is contained by: Python
 * strips \x1c-\x1f and \x85, JS strips \ufeff. Stripping exactly this set makes both
 * parsers normalize an entry identically. Its control members are unreachable now that a
 * control character is rejected outright; the class stays exact so the mirror of
 * `str.strip` can be read off it. */
const PYTHON_WHITESPACE_CLASS = "\\t\\n\\v\\f\\r\\x1c-\\x1f \\u0085\\u00a0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000";
const PYTHON_WHITESPACE = new RegExp(`^[${PYTHON_WHITESPACE_CLASS}]+|[${PYTHON_WHITESPACE_CLASS}]+$`, "gu");
/** `str.splitlines` terminators. Gate B counts an artifact's exit trailers after
 * splitting this way, so the producer detects a foreign trailer on the same boundaries. */
const PYTHON_LINE_BREAKS = /\r\n|[\n\r\v\f\x1c-\x1e\u0085\u2028\u2029]/;

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
 * root, else `.fv/intent.md`. Rejects escaping, symlinked, directory, missing, and
 * `~`-prefixed targets exactly as `fv_project.resolve_target` does, so producer and gate
 * bind the same file. Neither side expands `~`: a repo-relative declaration has no use
 * for it, and expanding on one side only would bind two different files. */
async function resolveCanonicalTarget(projectRoot: string): Promise<{ absolute: string; relative: string }> {
	const spec = (await declaredTargetSpec(projectRoot)) ?? DEFAULT_TARGET_SPEC;
	if (spec.split("/")[0]!.startsWith("~")) throw new Error(`target_spec must not start with '~': ${spec}`);
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

/** A project's verified-input policy: how git candidates become verified inputs.
 * `mode` is `exclude` (the historical shape, and what a file with no directive means) or
 * `include`; `prefixes` are the declared entries in file order; `structural` are the
 * generated-output prefixes that apply in either mode and that no project file drops.
 * Mirrors `fv_project.InputPolicy`. */
export type InputPolicy = {
	mode: string;
	prefixes: string[];
	structural: string[];
};

/** The canonical directive lines, the only two spellings a policy file is rendered with.
 * Mirrors `fv_project.mode_directive`. */
const INCLUDE_DIRECTIVE = `${MODE_DIRECTIVE_PREFIX} ${MODE_INCLUDE}`;
const EXCLUDE_DIRECTIVE = `${MODE_DIRECTIVE_PREFIX} ${MODE_EXCLUDE}`;

/** The mode a directive line names, or null when the line is not one. The prefix is
 * matched case-insensitively over exactly its own length, so recognition is length-stable
 * in both languages. Mirrors `fv_project._directive_value`. */
function directiveValue(line: string): string | null {
	if (line.slice(0, MODE_DIRECTIVE_PREFIX.length).toLowerCase() !== MODE_DIRECTIVE_PREFIX) return null;
	return line.slice(MODE_DIRECTIVE_PREFIX.length).replace(PYTHON_WHITESPACE, "");
}

/** One path-matching rule for both policy modes: a trailing-slash entry matches a literal
 * path prefix, a bare entry matches the path itself or the subtree beneath that whole
 * directory component. Mirrors `fv_project.matches_prefixes`. */
function matchesPrefixes(relative: string, prefixes: readonly string[]): boolean {
	return prefixes.some(entry =>
		entry.endsWith("/") ? relative.startsWith(entry) : relative === entry || relative.startsWith(`${entry}/`),
	);
}

/** Include-mode allowlist with the policy file self-bound, so revising the allowlist moves
 * the snapshot instead of silently re-scoping what existing evidence covers; empty under
 * exclude mode. Mirrors `fv_project.InputPolicy.selectors`. */
export function policySelectors(policy: InputPolicy): string[] {
	if (policy.mode !== MODE_INCLUDE) return [];
	if (policy.prefixes.includes(VERIFIED_INPUTS_RELATIVE)) return [...policy.prefixes];
	return [...policy.prefixes, VERIFIED_INPUTS_RELATIVE];
}

/** Exclusion prefixes that apply: structural, plus the declared ones under exclude mode.
 * Mirrors `fv_project.InputPolicy.exclusions`. */
export function policyExclusions(policy: InputPolicy): string[] {
	const prefixes = [...policy.structural];
	if (policy.mode === MODE_EXCLUDE) {
		for (const entry of policy.prefixes) if (!prefixes.includes(entry)) prefixes.push(entry);
	}
	return prefixes;
}

/** True when candidate `relative` is a verified input under `policy`. Structural
 * exclusions apply first in both modes, so an allowlist entry can never pull generated FV
 * output back into the snapshot and make writing a report stale the evidence it describes.
 * Mirrors `fv_project.InputPolicy.selects`. */
export function policySelects(relative: string, policy: InputPolicy): boolean {
	if (matchesPrefixes(relative, policy.structural)) return false;
	if (policy.mode === MODE_INCLUDE) return matchesPrefixes(relative, policySelectors(policy));
	return !matchesPrefixes(relative, policy.prefixes);
}

/** Parse verified-input policy text. A `mode:` directive is legal only as the first
 * non-comment line; anywhere else it is a rejection rather than a path entry. With no
 * directive the policy is exclusion mode. Every rejection, and its wording, mirrors
 * `fv_project.parse_policy`: a fixture the two ends read differently is a silent snapshot
 * split that surfaces only as a stale record, with nothing naming the parse.
 * Exported so the differential fixtures in `tests/r34_evidence_run.py` can hold this
 * parser and `fv_project.parse_policy` to one rule character by character. */
export function parseInputPolicy(text: string): InputPolicy {
	// LF and CRLF separate entries, and every other control character, plus a byte-order
	// mark, is rejected outright. The two languages disagree about which of them break
	// lines, which of them strip, and whether a BOM survives decoding, so accepting one
	// here would derive an input set the gate never derives and silently move the snapshot
	// on one side only.
	let lineno = 1;
	for (let at = 0; at < text.length; at += 1) {
		const char = text[at]!;
		if (char === "\n") {
			lineno += 1;
			continue;
		}
		if (char === "\r" && text[at + 1] === "\n") continue;
		const location = `${VERIFIED_INPUTS_RELATIVE}:${lineno}`;
		if (char === "\r" || AMBIGUOUS_LINE_CHARS.includes(char)) {
			throw new Error(`${location}: ambiguous line terminator ${charRepr(char)}; use LF`);
		}
		if (char === BOM_CHAR) {
			throw new Error(`${location}: byte-order mark U+FEFF; write the list as UTF-8 without a BOM`);
		}
		if (isControlChar(char)) {
			throw new Error(`${location}: control character ${charRepr(char)}; use LF-separated entries`);
		}
	}
	let mode: string | null = null;
	const prefixes: string[] = [];
	// `str.splitlines` drops a single trailing terminator and never yields a final empty
	// line for it; every other terminator it honours is already rejected above, so
	// splitting on /\r?\n/ and skipping the empty tail lands on the same line numbers.
	const lines = text.split(/\r?\n/);
	for (let index = 0; index < lines.length; index += 1) {
		let line = lines[index]!.replace(PYTHON_WHITESPACE, "");
		if (line.length === 0 || line.startsWith("#")) continue;
		const location = `${VERIFIED_INPUTS_RELATIVE}:${index + 1}`;
		const value = directiveValue(line);
		if (value !== null) {
			if (mode !== null || prefixes.length > 0) {
				throw new Error(`${location}: mode directive must be the first non-comment line`);
			}
			if (!POLICY_MODES.includes(value)) {
				throw new Error(`${location}: unknown mode '${value}'; write '${INCLUDE_DIRECTIVE}'`
					+ ` or '${EXCLUDE_DIRECTIVE}'`);
			}
			mode = value;
			continue;
		}
		if (mode === null) mode = MODE_EXCLUDE;
		if (line.startsWith("./")) line = line.slice(2);
		if (line.length === 0 || line === "." || line === "/") {
			const verb = mode === MODE_INCLUDE ? "selects" : "excludes";
			throw new Error(`${location}: entry ${verb} the whole project`);
		}
		if (path.isAbsolute(line)) throw new Error(`${location}: absolute entry '${line}'`);
		if (line.split("/").includes("..")) throw new Error(`${location}: entry escapes project root: '${line}'`);
		if (!prefixes.includes(line)) prefixes.push(line);
	}
	if (mode === MODE_INCLUDE && prefixes.length === 0) {
		throw new Error(`${VERIFIED_INPUTS_RELATIVE}: ${INCLUDE_DIRECTIVE} names no path;`
			+ " list the paths in scope or drop the directive");
	}
	return { mode: mode ?? MODE_EXCLUDE, prefixes, structural: [...DEFAULT_EXCLUSIONS] };
}

/** The project's declared policy; exclusion mode with no entries when the file is absent.
 * Mirrors `fv_project.load_policy`. */
export async function loadInputPolicy(projectRoot: string): Promise<InputPolicy> {
	const listFile = Bun.file(path.join(projectRoot, ".fv", "verified-inputs.txt"));
	if (!(await listFile.exists())) {
		return { mode: MODE_EXCLUDE, prefixes: [], structural: [...DEFAULT_EXCLUSIONS] };
	}
	let text: string;
	try {
		// `ignoreBOM` keeps a leading U+FEFF in the string, as Python's utf-8 decode does,
		// so the scan in the parser can reject it; `fatal` makes invalid UTF-8 a rejection
		// instead of a U+FFFD the gate would never see. Both mirror `read_bytes().decode`.
		text = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true })
			.decode(await listFile.arrayBuffer());
	} catch (error) {
		throw new Error(`cannot read ${VERIFIED_INPUTS_RELATIVE}: ${error instanceof Error ? error.message : String(error)}`);
	}
	return parseInputPolicy(text);
}

/** Exclusion prefixes that apply to the project. Mirrors `fv_project.load_exclusions`:
 * under `mode: include` only the structural defaults are exclusions and selection is the
 * allowlist's, so what the snapshot covers is `loadInputPolicy`'s answer, never this one's.
 * Exported for the differential fixtures in `tests/r34_evidence_run.py`. */
export async function loadExclusions(projectRoot: string): Promise<string[]> {
	return policyExclusions(await loadInputPolicy(projectRoot));
}

/** Snapshot order: UTF-8 byte-wise, not code-unit-wise. This runtime's default string
 * comparison orders by UTF-16 code unit, which puts every astral-plane path (leading
 * surrogate U+D800..U+DBFF) ahead of U+E000..U+FFFF, the reverse of UTF-8 byte order, so
 * a repository holding both would hash to two snapshots. Mirrors
 * `fv_project.order_inputs`; exported for the differential fixtures in
 * `tests/r34_evidence_run.py`. */
export function orderVerifiedInputs(paths: readonly string[]): string[] {
	return [...paths].sort((left, right) =>
		Buffer.compare(Buffer.from(left, "utf8"), Buffer.from(right, "utf8")));
}

/** `sha256:<hex>` over every candidate the policy selects: UTF-8 path, NUL, content
 * SHA-256 hex, newline, concatenated in UTF-8 byte order. */
async function verifiedInputSnapshot(
	projectRoot: string,
	policy: InputPolicy,
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
		if (policySelects(entry, policy)) candidates.add(entry);
	}
	const hasher = new Bun.CryptoHasher("sha256");
	const ordered = orderVerifiedInputs([...candidates]);
	for (const relative of ordered) {
		const absolute = path.join(projectRoot, relative);
		const info = await fs.lstat(absolute).catch(() => null);
		if (info === null) continue; // tracked but deleted in the worktree; the absence is the change
		if (info.isSymbolicLink()) throw new Error(`verified input is a symlink: ${relative}`);
		if (!insideRoot(projectRoot, absolute)) throw new Error(`verified input escapes project root: ${relative}`);
		if (info.isDirectory()) continue; // submodule gitlink: verified by its own repository
		if (!info.isFile()) throw new Error(`verified input is not a regular file: ${relative}`);
		hasher.update(relative);
		hasher.update(NUL);
		hasher.update(await sha256File(absolute));
		hasher.update("\n");
	}
	return `sha256:${hasher.digest("hex")}`;
}

/** Paths reported by `git status --porcelain -z` that the policy selects. Changes confined
 * to generated FV output, or to a file no include policy names, are not dirt. */
function dirtyVerifiedInputs(status: string, policy: InputPolicy): string[] {
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
			if (policySelects(relative, policy)) dirty.push(relative);
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

/** Gate B fires its unwaived-assumption rule on the record class and on every execution
 * class, and this producer always writes `waiver: null`, so an assumed class here could
 * only ever mint a record whose verdict is INCOMPLETE. Refuse it at the call instead. */
function rejectAssumedClass(evidenceClass: string, field: string): void {
	if (!Object.hasOwn(ASSUMED_CLASSES, evidenceClass)) return;
	throw new Error(
		`${field} '${evidenceClass}' cannot be produced: assumed evidence needs a waiver, `
		+ "which a producer-written record never carries",
	);
}

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
		// An unchecked `tool`, or an unchecked basename fallback, writes a record whose
		// tool id Gate B rejects; the cohort form has always checked it.
		const tool = params.tool === undefined ? path.basename(command[0]!) : params.tool.trim();
		if (!EVIDENCE_TOOL_ID.test(tool)) {
			throw new Error(`tool must be an evidence tool identifier: ${JSON.stringify(params.tool ?? tool)}`);
		}
		if (params.pass_marker !== undefined && params.pass_marker.length === 0) {
			throw new Error("pass_marker must be non-empty");
		}
		return [{
			tool,
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
		if (!Object.hasOwn(PASS_MARKERS, evidenceClass)) {
			throw new Error(`${where}.evidence_class is unknown: ${evidenceClass}`);
		}
		rejectAssumedClass(evidenceClass, `${where}.evidence_class`);
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

/** Every obligation id the manifest declares, with its kind, validated the way
 * `load_manifest` validates it: one object per entry, an id the producer could actually
 * write a record for, no duplicates. A record must not assert a `required_targets` set
 * drawn from a manifest its own gate refuses to load, and a silently dropped malformed
 * entry would do exactly that. */
function obligationTargets(manifest: unknown, manifestPath: string): {
	ids: string[];
	kinds: Record<string, string>;
} {
	if (manifest === null || typeof manifest !== "object" || Array.isArray(manifest)) {
		throw new Error(`obligation manifest is not a JSON object: ${manifestPath}`);
	}
	const collections = manifest as Record<string, unknown>;
	const ids: string[] = [];
	const kinds: Record<string, string> = Object.create(null);
	for (const [collection, kind] of OBLIGATION_COLLECTIONS) {
		const entries = collections[collection];
		if (entries === undefined || entries === null) continue;
		if (!Array.isArray(entries)) throw new Error(`obligation manifest ${collection} is not an array`);
		for (let index = 0; index < entries.length; index += 1) {
			const entry = entries[index];
			const where = `${collection}[${index}]`;
			if (entry === null || typeof entry !== "object" || Array.isArray(entry)) {
				throw new Error(`obligation manifest ${where} is not an object`);
			}
			const id = (entry as Record<string, unknown>).id;
			if (typeof id !== "string" || !CLAIM_ID.test(id)) {
				throw new Error(
					`obligation manifest ${where} id ${JSON.stringify(id)} is not usable by the evidence producer`,
				);
			}
			if (kinds[id] !== undefined) throw new Error(`obligation manifest ${where} duplicates id '${id}'`);
			kinds[id] = kind;
			ids.push(id);
		}
	}
	if (ids.length === 0) throw new Error(`obligation manifest has no targets: ${manifestPath}`);
	return { ids, kinds };
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
		if (!CLAIM_ID.test(params.claim_id)) {
			throw new Error("claim_id must be a filesystem-safe identifier");
		}
		if (!Object.hasOwn(PASS_MARKERS, params.evidence_class)) {
			throw new Error(`unknown evidence_class: ${params.evidence_class}`);
		}
		rejectAssumedClass(params.evidence_class, "evidence_class");
		if (params.scope.trim().length === 0) throw new Error("scope must describe what the evidence covers");
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
		const obligations = obligationTargets(manifest, manifestPath);
		// A record class compatible with the obligation kind says nothing about the
		// classes beneath it, so every execution is held to the same table Gate B uses.
		const obligationKind = obligations.kinds[params.claim_id];
		if (obligationKind !== undefined) {
			const allowed = OBLIGATION_EVIDENCE_COMPATIBILITY[obligationKind]!;
			const compatible = (field: string, evidenceClass: string) => {
				if (Object.hasOwn(allowed, evidenceClass)) return;
				throw new Error(
					`${field} '${evidenceClass}' cannot discharge ${obligationKind} '${params.claim_id}'`,
				);
			};
			compatible("evidence_class", params.evidence_class);
			for (let index = 0; index < requests.length; index += 1) {
				compatible(`executions[${index}].evidence_class`, requests[index]!.evidenceClass);
			}
		}

		// The baseline binding is taken before the `--version` probes below: a probe that
		// edits a verified input must move the snapshot like any other command instead of
		// being absorbed into the recorded pre-run state.
		const policy = await loadInputPolicy(projectRoot);
		const snapshot = await verifiedInputSnapshot(projectRoot, policy, exec, signal);
		const beforeStatus = await exec("git", ["status", "--porcelain", "--untracked-files=all", "-z"],
			{ cwd: projectRoot, signal });
		if (beforeStatus.code !== 0) throw new Error("git status failed before evidence command");
		// Bindings are checked around every execution, so a cohort whose second command
		// edits a verified input cannot ship as PASS evidence for its first.
		let dirty = dirtyVerifiedInputs(beforeStatus.stdout, policy).length > 0;

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

		// The baseline above predates the `--version` probes, so a probe that edited a
		// verified input already moves the per-execution comparison below. These two
		// cheap checks attribute the mutation to the probe phase instead of to the
		// recorded command.
		const probeStatus = await exec("git", ["status", "--porcelain", "--untracked-files=all", "-z"],
			{ cwd: projectRoot, signal });
		if (probeStatus.code !== 0) throw new Error("git status failed after toolchain version probes");
		if (dirtyVerifiedInputs(probeStatus.stdout, policy).length > 0) dirty = true;
		if ((await requiredFileHash(target.absolute, "intent")) !== intentHash) dirty = true;
		if ((await requiredFileHash(manifestPath, "obligation manifest")) !== manifestHash) dirty = true;

		const executions: Record<string, unknown>[] = [];
		const exitCodes: number[] = [];
		for (const plan of planned) {
			const run = await exec(plan.executable, plan.command.slice(1), { cwd: plan.cwdAbsolute, signal });
			const trailer = `--- fv-evidence: exit=${run.code} ---`;
			const streams = [run.stdout, run.stderr]
				.filter(stream => stream.length > 0)
				.map(stream => (stream.endsWith("\n") ? stream : stream + "\n"));
			const rawOutput = streams.join("") + trailer + "\n";
			// The trailer is this producer's own sentinel, and Gate B rejects a PASS
			// artifact carrying two of them. A command that echoes an earlier evidence
			// log would otherwise print PASS here and read as tampering at the gate.
			for (const stream of [run.stdout, run.stderr]) {
				if (!stream.split(PYTHON_LINE_BREAKS).some(line => TRAILER_LINE.test(line))) continue;
				throw new Error(
					`${plan.tool} printed a reserved '--- fv-evidence: exit=N ---' trailer line: `
					+ "the evidence artifact would carry two trailers, which Gate B rejects",
				);
			}
			await Bun.write(plan.rawAbsolute, rawOutput);
			const rawOutputHash = await sha256File(plan.rawAbsolute);
			const markerMatched = plan.passMarker
				? rawOutput.includes(plan.passMarker)
				: PASS_MARKERS[plan.evidenceClass]!.test(rawOutput);
			const snapshotAfter = await verifiedInputSnapshot(projectRoot, policy, exec, signal);
			const intentHashAfter = await requiredFileHash(target.absolute, "intent");
			const manifestHashAfter = await requiredFileHash(manifestPath, "obligation manifest");
			const afterStatus = await exec("git", ["status", "--porcelain", "--untracked-files=all", "-z"],
				{ cwd: projectRoot, signal });
			if (afterStatus.code !== 0) throw new Error("git status failed after evidence command");
			if (snapshotAfter !== snapshot || intentHashAfter !== intentHash || manifestHashAfter !== manifestHash) {
				dirty = true;
			}
			if (dirtyVerifiedInputs(afterStatus.stdout, policy).length > 0) dirty = true;
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

		const requiredTargets = obligations.ids;

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
