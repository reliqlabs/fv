import { createHash } from "node:crypto";

export type Hash = string;
export type ID = string;
export type Path = string;
export type ToolPath = Path | ".";
export type Cwd = string;
export type ToolID = string;
export type UUID = string;
export type UTC = string;
export type Class = "code-enforced" | "proof-discharged" | "bounded-checked" | "test-witnessed" | "conformance-tested";
export type Result = "PASS" | "FAIL" | "ERROR" | "CANCELLED";
export type SlotState = Result | "MISSING";
export type Member = { claim_id: ID; slot_id: ID; tool: ToolID };
export type DistinctSlot = { claim_id: ID; slot_id: ID };
export type TrustAssumptions = {
	no_concurrent_mutation: true;
	build_cache_integrity: "upstream-build-system";
	retained_history_integrity: "trusted-producer-store";
};
export type Check = {
	id: ID;
	command: string[];
	cwd: Cwd;
	resources: string[];
	toolchain: ID[];
	timeout_seconds: number | null;
};
export type Locator =
	| { mode: "command" | "path"; value: string }
	| { mode: "command-relative"; value: string; parent_levels: number; subpath: Cwd }
	| {
			mode: "adapter";
			value:
				| "python-runtime"
				| "quint-backends"
				| "cargo-toolchain"
				| "kani-toolchain"
				| "lean-toolchain"
				| "darwin-native"
				| "node-toolchain";
			cwd: Cwd;
			subject: string[];
	  };
export type ProducerLocator = { mode: "adapter"; value: "producer-runtime"; cwd: "."; subject: ["fv_evidence_run"] };
export type ToolDeclaration = {
	id: ID;
	kind: "executable" | "file" | "tree";
	locator: Locator;
	version_command: string[] | null;
	version_cwd: Cwd | null;
	requires: ID[];
	accept: { sha256: Hash[]; version_contains: string[] };
};
export type ObservationBinding = { path: Path; pointer: string };
export type Recipe = {
	recipe_id: ID;
	command: string[];
	cwd: Cwd;
	evidence_class: Class;
	pass_marker: string | null;
	timeout_seconds: number | null;
	determinism: { mode: "fixed" | "distinct"; rationale: string };
	source_closure: { mode: "prefixes" | "verified-inputs"; prefixes: Path[]; basis: Path[] };
	toolchain: ID[];
	resources: string[];
	exclusive: boolean;
	bounds: { samples: number | null; max_steps: number | null; seed: string | null };
	attestation: (ObservationBinding & { validation: "collector-transitive" }) | null;
	build_cache: {
		mode: "upstream-integrity";
		system: "cargo" | "lake" | "node" | "replay";
		configuration: Path[];
		resources: string[];
	} | null;
	ownership_protocol: "dossier-quint-private-pipes/v1" | null;
	retained_environment: string[];
};
export type PolicyRecord = {
	claim_id: ID;
	required: boolean;
	evidence_class: Class;
	scope: string;
	executions: { slot_id: ID; recipe_id: ID; tool: ToolID; observation_binding: ObservationBinding }[];
};
export type Policy = {
	schema_version: "fv-execution-policy/v1";
	policy_id: ID;
	verified_inputs: Path;
	intent_path: Path;
	manifest_path: Path;
	definition_files: Path[];
	environment: {
		mode: "sanitized";
		platforms: { os: string; arch: string }[];
		inherit: string[];
		set: Record<string, string>;
		identity: string[];
	};
	toolchains: ToolDeclaration[];
	preflight: Check[];
	claim_checker: Check;
	recipes: Recipe[];
	records: PolicyRecord[];
	jobs: { default: 2; max: number };
	trust_assumptions: TrustAssumptions;
};
export type V4Call = {
	schema_version: "fv-evidence-run/v4";
	policy: Path;
	mode: "plan" | "run";
	records?: ID[];
	jobs?: number;
	resume?: boolean;
};
export type EvidenceV4Call = V4Call;
export type SourceFile = { path: Path; hash: Hash; size: number; executable: boolean };
export type InputState = {
	verified_inputs_policy_hash: Hash;
	inventory_hash: Hash;
	source_snapshot: Hash;
	clean: boolean;
	files: SourceFile[];
};
export type Closure = {
	mode: "prefixes" | "verified-inputs";
	prefixes: Path[];
	basis: Path[];
	files: SourceFile[];
	hash: Hash;
};
export type BuildCacheIdentity = {
	system: "cargo" | "lake" | "node" | "replay";
	configuration: { path: Path; hash: Hash }[];
	namespaces: { role: ID; kind: "selected-path" | "producer-fresh"; identity_hash: Hash }[];
	integrity: "upstream-build-system";
} | null;
export type EnvironmentIdentity = {
	os: string;
	arch: string;
	release: string;
	variables: { name: string; present: boolean; value_hash: Hash | null }[];
};
export type ToolFile =
	| { path: Path; kind: "file"; hash: Hash; size: number; executable: boolean }
	| { path: Path; kind: "directory" }
	| {
			path: Path;
			kind: "symlink-file";
			target: string;
			resolved_path: Path;
			resolved_hash: Hash;
			resolved_size: number;
			executable: boolean;
	  }
	| { path: Path; kind: "symlink-directory"; target: string; resolved_path: Path; resolved_hash: Hash };
export type PackageIdentity = {
	name: string;
	version: string;
	source:
		| { kind: "registry"; id: string; checksum: string }
		| { kind: "git"; id: string; revision: string }
		| { kind: "path"; path: Cwd };
};
export type ToolDiscovery = { command: string[]; cwd: Cwd; stdout_hash: Hash; stderr_hash: Hash; exit_code: number };
export type ToolIdentity = {
	id: ID;
	kind: "executable" | "file" | "tree";
	locator: Locator | ProducerLocator;
	digest: Hash;
	files: ToolFile[];
	packages: PackageIdentity[];
	version: (ToolDiscovery & { text: string }) | null;
	discovery: ToolDiscovery[];
	system_dependencies: {
		os: string;
		arch: string;
		release: string;
		sdk: { version: string; settings_hash: Hash } | null;
	};
	requires: ID[];
};
export type CommonBindings = {
	policy_path: Path;
	policy_hash: Hash;
	intent_path: Path;
	intent_hash: Hash;
	manifest_path: Path;
	manifest_hash: Hash;
	definition_files: { path: Path; hash: Hash }[];
	dispatch_hash: Hash | null;
	required_targets: ID[];
};
export type ExecutionDescriptor = {
	schema_version: "fv-execution-descriptor/v1";
	common: CommonBindings;
	recipe: Recipe;
	members: Member[];
	distinct_slot: DistinctSlot | null;
	verified_inputs_policy_hash: Hash;
	inventory_hash: Hash;
	closure: Closure;
	environment: EnvironmentIdentity;
	toolchain: ToolIdentity[];
	build_cache: BuildCacheIdentity;
};
export type FileRef = { path: Path; hash: Hash; size: number };
export type Producer = {
	name: "fv_evidence_run";
	schema_version: "fv-evidence-run/v4";
	implementation_hash: Hash;
	host_contract: "fv-producer-host/v1";
};
export type Termination = { exit_code: number | null; signal: string | null; timed_out: boolean; cancelled: boolean };
export type OwnedProcess = {
	pid: number;
	process_start_id: string;
	process_group: number;
	session_id: number;
	parent_pid: number;
};
export type SpawnWindow = {
	window_id: UUID;
	protocol: "native-direct/v1" | "dossier-quint-private-pipes/v1";
	execution_key: Hash | null;
	attempt_id: UUID | null;
	parent: OwnedProcess | null;
	state: "pending" | "active" | "closed" | "indeterminate";
};
export type PendingResult = {
	kind: "execution" | "observation";
	execution_key: Hash;
	attempt_id: UUID;
	members: Member[];
	claim_id: ID | null;
	slot_id: ID | null;
};
export type Owner = {
	schema_version: "fv-evidence-owner/v1";
	owner_id: UUID;
	host_id: Hash;
	boot_id: Hash;
	pid: number;
	process_start_id: string;
	run_id: UUID;
	created_at: UTC;
	children: OwnedProcess[];
	spawn_windows: SpawnWindow[];
	pending_results: PendingResult[];
};
export type OwnerRecord = Owner;
export type OwnedRegistration = {
	process: OwnedProcess;
	window_id: UUID;
	registered_at: UTC;
	terminated_at: UTC | null;
};
export type OwnershipReceipt = {
	schema_version: "fv-execution-ownership/v1";
	owner_id: UUID;
	children: OwnedRegistration[];
	spawn_windows: SpawnWindow[];
	protocol_log: FileRef | null;
};
export type ExecutionArtifact = {
	schema_version: "fv-execution-artifact/v1";
	artifact_id: Hash;
	execution_key: Hash;
	attempt_id: UUID;
	producer: Producer;
	descriptor: ExecutionDescriptor;
	started_at: UTC;
	finished_at: UTC;
	source_before: InputState;
	source_after: InputState | null;
	toolchain_after: ToolIdentity[] | null;
	environment_after: EnvironmentIdentity | null;
	stdout: FileRef;
	stderr: FileRef;
	raw_output: FileRef;
	attachments: FileRef[];
	ownership: OwnershipReceipt;
	build_cache_after: BuildCacheIdentity;
	termination: Termination;
	marker_matched: boolean;
	result: Result;
	reason: string | null;
};
export type ExecutionRef = { execution_key: Hash; artifact_id: Hash; path: Path; hash: Hash };
export type HistoryRef = { sequence: number; event_id: Hash; path: Path; hash: Hash };
export type HistoryView = { head: HistoryRef | null; events: HistoryRef[] };
export type HistoryEvent = {
	schema_version: "fv-evidence-history/v1";
	event_id: Hash;
	sequence: number;
	previous: HistoryRef | null;
	kind: "execution" | "observation" | "indeterminate";
	execution_key: Hash;
	attempt_id: UUID;
	members: Member[];
	execution: ExecutionRef | null;
	claim_id: ID | null;
	slot_id: ID | null;
	observation: FileRef | null;
	indeterminate_owner: FileRef | null;
	result: Result;
};
export type ObservationRequest = {
	schema_version: "fv-claim-observation-request/v1";
	request_id: UUID;
	policy_path: Path;
	policy_hash: Hash;
	common: CommonBindings;
	claim_id: ID;
	created_at: UTC;
	slots: {
		slot_id: ID;
		tool: ToolID;
		recipe_id: ID;
		execution: ExecutionRef;
		observation_binding: ObservationBinding;
	}[];
};
export type ObservationResponse = {
	schema_version: "fv-claim-observations/v1";
	request_id: UUID;
	request_hash: Hash;
	claim_id: ID;
	started_at: UTC;
	finished_at: UTC;
	slots: {
		slot_id: ID;
		result: "PASS" | "FAIL" | "ERROR";
		reason: string | null;
		observations: Record<string, unknown>;
	}[];
};
export type ObservationCheck = {
	schema_version: "fv-observation-check/v1";
	request: FileRef;
	response: FileRef | null;
	started_at: UTC;
	finished_at: UTC;
	termination: Termination;
	stdout: FileRef;
	stderr: FileRef;
	source_before: InputState;
	source_after: InputState | null;
	toolchain: ToolIdentity[];
	result: Result;
	reason: string | null;
};
export type ClaimRecord = {
	schema_version: "fv-evidence-run/v4";
	record_id: Hash;
	run_id: UUID;
	claim_id: ID;
	required: boolean;
	evidence_class: Class;
	scope: string;
	common: CommonBindings;
	executions: {
		slot_id: ID;
		tool: ToolID;
		recipe_id: ID;
		evidence_class: Class;
		execution: ExecutionRef | null;
		state: SlotState;
		reason: string | null;
		observation_binding: ObservationBinding;
		blocking_events: HistoryRef[];
		observation: { check: FileRef; response: FileRef | null; result: Result } | null;
	}[];
	result: "PASS" | "FAIL" | "INCOMPLETE";
	waiver: null;
};
export type RunManifest = {
	schema_version: "fv-evidence-batch/v1";
	run_id: UUID;
	policy_path: Path;
	policy_hash: Hash;
	common: CommonBindings;
	producer: Producer;
	trust_assumptions: TrustAssumptions;
	history: HistoryView;
	started_at: UTC;
	finished_at: UTC;
	jobs: number;
	selected_records: ID[];
	required_records: ID[];
	source_before: InputState | null;
	source_after: InputState | null;
	preflight: {
		result: "PASS" | "ERROR" | "CANCELLED";
		reason: string | null;
		checks: {
			id: ID;
			result: "PASS" | "ERROR" | "CANCELLED" | "MISSING";
			termination: Termination;
			stdout: FileRef | null;
			stderr: FileRef | null;
			reason: string | null;
		}[];
	};
	work: {
		recipe_id: ID;
		distinct_slot: DistinctSlot | null;
		execution_key: Hash | null;
		execution: ExecutionRef | null;
		state: SlotState;
		cache: "hit" | "miss" | "not-checked";
		reason: string | null;
	}[];
	claims: { claim_id: ID; record: FileRef }[];
	result: Result | "INCOMPLETE";
	reason: string | null;
};
export type CurrentPointer = { schema_version: "fv-evidence-current/v1"; run_id: UUID; run: FileRef };
export type PlanResult = {
	schema_version: "fv-evidence-plan/v1";
	policy_path: Path;
	policy_hash: Hash;
	result: "READY" | "ERROR";
	reason: string | null;
	required_records: ID[];
	selected_records: ID[];
	canonical_required_targets: ID[];
	jobs: number;
	physical_slots: {
		recipe_id: ID;
		distinct_slot: DistinctSlot | null;
		members: Member[];
		execution_key: Hash | null;
		resources: string[];
		exclusive: boolean;
		cache: "eligible" | "miss" | "corrupt" | "not-checked";
	}[];
};
export type Publication = {
	state: "not-attempted" | "pre-replace-error" | "post-replace-error" | "durable";
	candidate: FileRef | null;
};
export type RunResult = {
	schema_version: "fv-evidence-run-result/v1";
	result: Result | "INCOMPLETE";
	run: FileRef | null;
	manifest: RunManifest | null;
	publication: Publication;
	reason: string | null;
};

export function assertScalar(value: string): void {
	for (let i = 0; i < value.length; i++) {
		const c = value.charCodeAt(i);
		if (c >= 0xd800 && c <= 0xdbff) {
			const next = value.charCodeAt(++i);
			if (!(next >= 0xdc00 && next <= 0xdfff)) throw new Error("lone high surrogate");
		} else if (c >= 0xdc00 && c <= 0xdfff) throw new Error("lone low surrogate");
	}
}
export function utf8Compare(a: string, b: string): number {
	assertScalar(a);
	assertScalar(b);
	return Buffer.compare(Buffer.from(a, "utf8"), Buffer.from(b, "utf8"));
}
function quote(value: string): string {
	assertScalar(value);
	return (
		'"' +
		value.replace(/["\\\u0000-\u001f]/g, (c) =>
			c === '"' ? '\\"' : c === "\\" ? "\\\\" : `\\u${c.charCodeAt(0).toString(16).padStart(4, "0")}`,
		) +
		'"'
	);
}
export function C(value: unknown): Uint8Array {
	const active = new Set<object>();
	function encode(v: unknown, field?: string): string {
		if (v === null) return "null";
		if (typeof v === "string") return quote(v);
		if (typeof v === "boolean") return String(v);
		if (typeof v === "number") {
			if (!Number.isSafeInteger(v) || Object.is(v, -0) || (v < 0 && field !== "exit_code"))
				throw new Error("noncanonical integer or signed field");
			return String(v);
		}
		if (typeof v !== "object") throw new Error("unsupported canonical JSON value");
		if (active.has(v)) throw new Error("cyclic canonical JSON value");
		if (Object.getOwnPropertySymbols(v).length) throw new Error("symbol JSON key");
		active.add(v);
		let encoded: string;
		if (Array.isArray(v)) {
			if (Object.keys(v).length !== v.length || Object.keys(v).some((key, index) => key !== String(index)))
				throw new Error("sparse or extended JSON array");
			encoded = `[${v.map((entry) => encode(entry)).join(",")}]`;
		} else {
			if (Object.getPrototypeOf(v) !== Object.prototype && Object.getPrototypeOf(v) !== null)
				throw new Error("non-JSON object");
			encoded = `{${Object.keys(v)
				.sort(utf8Compare)
				.map((k) => `${quote(k)}:${encode((v as Record<string, unknown>)[k], k)}`)
				.join(",")}}`;
		}
		active.delete(v);
		return encoded;
	}
	return Buffer.from(encode(value), "utf8");
}
export function H(bytes: Uint8Array): Hash {
	return `sha256:${createHash("sha256").update(bytes).digest("hex")}`;
}
export function D(label: string, value: unknown): Hash {
	assertScalar(label);
	return `sha256:${createHash("sha256").update(`fv-evidence-v4/${label}\0`, "utf8").update(C(value)).digest("hex")}`;
}
export function decodeUTF8(bytes: Uint8Array): string {
	return new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(bytes);
}
export function parseJSON(bytes: Uint8Array): unknown {
	const text = decodeUTF8(bytes);
	let at = 0;
	const fail = (why: string): never => {
		throw new Error(`invalid v4 JSON at ${at}: ${why}`);
	};
	function whitespace(): void {
		while (/[\x20\x09\x0a\x0d]/.test(text[at] ?? "x")) at++;
	}
	function string(): string {
		const start = at++;
		while (at < text.length) {
			const c = text.charCodeAt(at++);
			if (c === 34) {
				const value = JSON.parse(text.slice(start, at)) as string;
				assertScalar(value);
				return value;
			}
			if (c < 32) fail("unescaped control");
			if (c === 92) {
				const escape = text[at++];
				if (escape === "u") {
					if (!/^[0-9a-fA-F]{4}$/.test(text.slice(at, at + 4))) fail("bad Unicode escape");
					at += 4;
				} else if (!escape || !'"\\/bfnrt'.includes(escape)) fail("bad escape");
			}
		}
		return fail("unterminated string");
	}
	function value(field?: string): unknown {
		whitespace();
		const c = text[at];
		if (c === '"') return string();
		if (c === "{") {
			at++;
			whitespace();
			const result = Object.create(null) as Record<string, unknown>;
			if (text[at] === "}") {
				at++;
				return result;
			}
			for (;;) {
				if (text[at] !== '"') fail("object key required");
				const key = string();
				whitespace();
				if (Object.hasOwn(result, key)) fail("duplicate object key");
				if (text[at++] !== ":") fail("colon required");
				result[key] = value(key);
				whitespace();
				const end = text[at++];
				if (end === "}") return result;
				if (end !== ",") fail("comma required");
				whitespace();
			}
		}
		if (c === "[") {
			at++;
			whitespace();
			const result: unknown[] = [];
			if (text[at] === "]") {
				at++;
				return result;
			}
			for (;;) {
				result.push(value());
				whitespace();
				const end = text[at++];
				if (end === "]") return result;
				if (end !== ",") fail("comma required");
			}
		}
		for (const [word, literal] of [
			["true", true],
			["false", false],
			["null", null],
		] as const) {
			if (text.startsWith(word, at)) {
				at += word.length;
				return literal;
			}
		}
		const token = /^-?(?:0|[1-9][0-9]*)/.exec(text.slice(at))?.[0];
		if (!token) return fail("value required");
		at += token.length;
		if (token === "-0" || /[.eE0-9]/.test(text[at] ?? "x")) fail("integer spelling");
		const n = Number(token);
		if (!Number.isSafeInteger(n) || (n < 0 && field !== "exit_code")) fail("integer range or signed field");
		return n;
	}
	const result = value();
	whitespace();
	if (at !== text.length) fail("trailing bytes");
	return result;
}

export function validPath(value: unknown, cwd = false, prefix = false): value is string {
	if (typeof value !== "string") return false;
	assertScalar(value);
	if (cwd && value === ".") return true;
	if (prefix && value.endsWith("/")) value = value.slice(0, -1);
	return (
		typeof value === "string" &&
		value.length > 0 &&
		!/^[\/~]|[\\\x00-\x1f\x7f-\x9f]/.test(value) &&
		value.split("/").every((c) => c !== "" && c !== "." && c !== "..")
	);
}

type Validator = (value: unknown, where: string) => void;
const error = (where: string, message: string): never => {
	throw new Error(`${where}: ${message}`);
};
const str: Validator = (v, w) => {
	if (typeof v !== "string") error(w, "expected string");
	assertScalar(v as string);
};
const nonempty: Validator = (v, w) => {
	str(v, w);
	if (v === "") error(w, "empty string");
};
const bool: Validator = (v, w) => {
	if (typeof v !== "boolean") error(w, "expected boolean");
};
const integer: Validator = (v, w) => {
	if (typeof v !== "number" || !Number.isSafeInteger(v) || Object.is(v, -0) || v < 0)
		error(w, "expected unsigned safe integer");
};
const signed: Validator = (v, w) => {
	if (typeof v !== "number" || !Number.isSafeInteger(v) || Object.is(v, -0)) error(w, "expected signed safe integer");
};
const positive: Validator = (v, w) => {
	integer(v, w);
	if (v === 0) error(w, "expected positive integer");
};
const literal =
	(...values: unknown[]): Validator =>
	(v, w) => {
		if (!values.includes(v)) error(w, "unexpected literal");
	};
const matching =
	(pattern: RegExp): Validator =>
	(v, w) => {
		str(v, w);
		if (!pattern.test(v as string)) error(w, "invalid grammar");
	};
const id = matching(/^[A-Za-z0-9][A-Za-z0-9._-]*$/);
const tool = matching(/^[A-Za-z0-9][A-Za-z0-9._:+/-]*$/);
const envName = matching(/^[A-Za-z_][A-Za-z0-9_]*$/);
const hash = matching(/^sha256:[0-9a-f]{64}$/);
const uuid = matching(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
const utc: Validator = (v, w) => {
	matching(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/)(v, w);
	const d = new Date(v as string);
	if (!Number.isFinite(d.getTime()) || d.toISOString() !== v) error(w, "invalid UTC date");
};
const pathValue: Validator = (v, w) => {
	if (!validPath(v)) error(w, "unsafe path");
};
const cwd: Validator = (v, w) => {
	if (!validPath(v, true)) error(w, "unsafe cwd");
};
const prefix: Validator = (v, w) => {
	if (!validPath(v, false, true)) error(w, "unsafe prefix");
};
const nullable =
	(validate: Validator): Validator =>
	(v, w) => {
		if (v !== null) validate(v, w);
	};
const array =
	(validate: Validator, min = 0): Validator =>
	(v, w) => {
		if (!Array.isArray(v) || v.length < min) error(w, "expected array");
		const values = v as unknown[];
		const keys = Object.keys(values);
		if (
			keys.length !== values.length ||
			keys.some((key, index) => key !== String(index)) ||
			Object.getOwnPropertySymbols(values).length
		)
			error(w, "sparse or extended JSON array");
		for (let i = 0; i < values.length; i++) validate(values[i], `${w}[${i}]`);
	};
const object =
	(fields: Record<string, Validator>, optional: string[] = []): Validator =>
	(v, w) => {
		if (v === null || typeof v !== "object" || Array.isArray(v)) error(w, "expected object");
		if (
			(Object.getPrototypeOf(v) !== Object.prototype && Object.getPrototypeOf(v) !== null) ||
			Object.getOwnPropertySymbols(v).length
		)
			error(w, "non-JSON object");
		for (const k of Object.keys(v as object)) if (!Object.hasOwn(fields, k)) error(w, `unknown field ${k}`);
		for (const [k, validate] of Object.entries(fields)) {
			if (!Object.hasOwn(v as object, k)) {
				if (!optional.includes(k)) error(w, `missing field ${k}`);
			} else validate((v as Record<string, unknown>)[k], `${w}.${k}`);
		}
	};
const union =
	(...validators: Validator[]): Validator =>
	(v, w) => {
		for (const validate of validators) {
			try {
				validate(v, w);
				return;
			} catch {}
		}
		error(w, "no matching schema");
	};
const set =
	<T = string>(validate: Validator, identify: ((v: T) => string) | undefined = undefined, min = 0): Validator =>
	(v, w) => {
		array(validate, min)(v, w);
		const keys = identify ? (v as T[]).map(identify) : (v as string[]);
		for (let i = 1; i < keys.length; i++)
			if (utf8Compare(keys[i - 1]!, keys[i]!) >= 0) error(w, "set is duplicate or not UTF-8 ordered");
	};
const unique =
	<T>(validate: Validator, identify: (v: T) => string, min = 0): Validator =>
	(v, w) => {
		array(validate, min)(v, w);
		const ids = (v as T[]).map(identify);
		if (new Set(ids).size !== ids.length) error(w, "duplicate identity");
	};
const command = array((v, w) => {
	nonempty(v, w);
	if ((v as string).includes("\0")) error(w, "NUL in argv");
}, 1);
const resource: Validator = (v, w) => {
	nonempty(v, w);
	if (/[\x00-\x1f\x7f-\x9f]/.test(v as string)) error(w, "control in resource");
};
const pointer: Validator = (v, w) => {
	str(v, w);
	if (v !== "" && (!(v as string).startsWith("/") || /~(?![01])/.test(v as string))) error(w, "invalid JSON pointer");
};
const evidenceClass = literal(
	"code-enforced",
	"proof-discharged",
	"bounded-checked",
	"test-witnessed",
	"conformance-tested",
);
const result = literal("PASS", "FAIL", "ERROR", "CANCELLED");
const slotState = literal("PASS", "FAIL", "ERROR", "CANCELLED", "MISSING");
const binding = object({ path: pathValue, pointer });
const distinct = object({ claim_id: id, slot_id: id });
const member = object({ claim_id: id, slot_id: id, tool });
const members = set<Member>(member, (v) => `${v.claim_id}\0${v.slot_id}`, 1);
const trust = object({
	no_concurrent_mutation: literal(true),
	build_cache_integrity: literal("upstream-build-system"),
	retained_history_integrity: literal("trusted-producer-store"),
});
const check = object({
	id,
	command,
	cwd,
	resources: set(resource),
	toolchain: set(id),
	timeout_seconds: nullable(positive),
});
const locator = union(
	object({ mode: literal("command", "path"), value: nonempty }),
	object({ mode: literal("command-relative"), value: nonempty, parent_levels: integer, subpath: cwd }),
	object({
		mode: literal("adapter"),
		value: literal(
			"python-runtime",
			"quint-backends",
			"cargo-toolchain",
			"kani-toolchain",
			"lean-toolchain",
			"darwin-native",
			"node-toolchain",
		),
		cwd,
		subject: command,
	}),
);
const producerLocator = object({
	mode: literal("adapter"),
	value: literal("producer-runtime"),
	cwd: literal("."),
	subject: (v, w) => {
		command(v, w);
		if ((v as string[]).length !== 1 || (v as string[])[0] !== "fv_evidence_run") error(w, "invalid producer subject");
	},
});
const toolDeclaration = object({
	id,
	kind: literal("executable", "file", "tree"),
	locator,
	version_command: nullable(command),
	version_cwd: nullable(cwd),
	requires: set(id),
	accept: object({ sha256: set(hash), version_contains: array(nonempty) }),
});
const cacheSystem = literal("cargo", "lake", "node", "replay");
const sourceClosureSchema = object({
	mode: literal("prefixes", "verified-inputs"),
	prefixes: set(prefix),
	basis: set(pathValue),
});
const recipe = object({
	recipe_id: id,
	command,
	cwd,
	evidence_class: evidenceClass,
	pass_marker: nullable(nonempty),
	timeout_seconds: nullable(positive),
	determinism: object({ mode: literal("fixed", "distinct"), rationale: nonempty }),
	source_closure: sourceClosureSchema,
	toolchain: set(id),
	resources: set(resource),
	exclusive: bool,
	bounds: object({ samples: nullable(positive), max_steps: nullable(positive), seed: nullable(str) }),
	attestation: nullable(object({ path: pathValue, pointer, validation: literal("collector-transitive") })),
	build_cache: nullable(
		object({
			mode: literal("upstream-integrity"),
			system: cacheSystem,
			configuration: set(pathValue),
			resources: set(resource),
		}),
	),
	ownership_protocol: nullable(literal("dossier-quint-private-pipes/v1")),
	retained_environment: set(envName),
});
const policyRecord = object({
	claim_id: id,
	required: bool,
	evidence_class: evidenceClass,
	scope: nonempty,
	executions: unique<PolicyRecord["executions"][number]>(
		object({ slot_id: id, recipe_id: id, tool, observation_binding: binding }),
		(v) => v.slot_id,
		1,
	),
});
const environmentPolicy = object({
	mode: literal("sanitized"),
	platforms: set<Policy["environment"]["platforms"][number]>(
		object({ os: nonempty, arch: nonempty }),
		(v) => `${v.os}\0${v.arch}`,
		1,
	),
	inherit: set(envName),
	set: (v, w) => {
		if (v === null || typeof v !== "object" || Array.isArray(v)) error(w, "expected environment literals");
		for (const [k, x] of Object.entries(v as object)) {
			envName(k, w);
			str(x, `${w}.${k}`);
			if ((x as string).includes("\0")) error(w, "NUL in environment");
		}
	},
	identity: set(envName),
});
const policySchema = object({
	schema_version: literal("fv-execution-policy/v1"),
	policy_id: id,
	verified_inputs: literal(".fv/verified-inputs.txt"),
	intent_path: pathValue,
	manifest_path: literal(".fv/obligations.json"),
	definition_files: set(pathValue),
	environment: environmentPolicy,
	toolchains: unique<ToolDeclaration>(toolDeclaration, (v) => v.id),
	preflight: unique<Check>(check, (v) => v.id),
	claim_checker: check,
	recipes: unique<Recipe>(recipe, (v) => v.recipe_id, 1),
	records: unique<PolicyRecord>(policyRecord, (v) => v.claim_id, 1),
	jobs: object({
		default: literal(2),
		max: (v, w) => {
			positive(v, w);
			if ((v as number) < 2) error(w, "jobs max below two");
		},
	}),
	trust_assumptions: trust,
});
const sourceFile = object({ path: pathValue, hash, size: integer, executable: bool });
const sourceFiles = set<SourceFile>(sourceFile, (v) => v.path);
const inputState = object({
	verified_inputs_policy_hash: hash,
	inventory_hash: hash,
	source_snapshot: hash,
	clean: bool,
	files: sourceFiles,
});
const closure = object({
	mode: literal("prefixes", "verified-inputs"),
	prefixes: set(prefix),
	basis: set(pathValue),
	files: sourceFiles,
	hash,
});
const pathHash = object({ path: pathValue, hash });
const cacheIdentity = nullable(
	object({
		system: cacheSystem,
		configuration: set<NonNullable<BuildCacheIdentity>["configuration"][number]>(pathHash, (v) => v.path),
		namespaces: set<NonNullable<BuildCacheIdentity>["namespaces"][number]>(
			object({ role: id, kind: literal("selected-path", "producer-fresh"), identity_hash: hash }),
			(v) => v.role,
			1,
		),
		integrity: literal("upstream-build-system"),
	}),
);
const environmentIdentity = object({
	os: nonempty,
	arch: nonempty,
	release: nonempty,
	variables: set<EnvironmentIdentity["variables"][number]>(
		object({ name: envName, present: bool, value_hash: nullable(hash) }),
		(v) => v.name,
	),
});
const toolFile = union(
	object({ path: cwd, kind: literal("file"), hash, size: integer, executable: bool }),
	object({ path: cwd, kind: literal("directory") }),
	object({
		path: cwd,
		kind: literal("symlink-file"),
		target: nonempty,
		resolved_path: cwd,
		resolved_hash: hash,
		resolved_size: integer,
		executable: bool,
	}),
	object({ path: cwd, kind: literal("symlink-directory"), target: nonempty, resolved_path: cwd, resolved_hash: hash }),
);
const packageIdentity = object({
	name: nonempty,
	version: nonempty,
	source: union(
		object({ kind: literal("registry"), id: nonempty, checksum: matching(/^[0-9a-f]{64}$/) }),
		object({ kind: literal("git"), id: nonempty, revision: matching(/^(?:[0-9a-f]{40}|[0-9a-f]{64})$/) }),
		object({ kind: literal("path"), path: cwd }),
	),
});
const toolDiscovery = object({ command, cwd, stdout_hash: hash, stderr_hash: hash, exit_code: signed });
const toolIdentity = object({
	id,
	kind: literal("executable", "file", "tree"),
	locator: union(locator, producerLocator),
	digest: hash,
	files: set<ToolFile>(toolFile, (v) => v.path, 1),
	packages: set<PackageIdentity>(packageIdentity, (v) => D("cargo-package", v).slice(7)),
	version: nullable(object({ command, cwd, stdout_hash: hash, stderr_hash: hash, text: str, exit_code: signed })),
	discovery: array(toolDiscovery),
	system_dependencies: object({
		os: nonempty,
		arch: nonempty,
		release: nonempty,
		sdk: nullable(object({ version: nonempty, settings_hash: hash })),
	}),
	requires: set(id),
});
const toolIdentities = set<ToolIdentity>(toolIdentity, (v) => v.id);
const common = object({
	policy_path: pathValue,
	policy_hash: hash,
	intent_path: pathValue,
	intent_hash: hash,
	manifest_path: pathValue,
	manifest_hash: hash,
	definition_files: set<CommonBindings["definition_files"][number]>(pathHash, (v) => v.path),
	dispatch_hash: nullable(hash),
	required_targets: set(id, undefined, 1),
});
const descriptor = object({
	schema_version: literal("fv-execution-descriptor/v1"),
	common,
	recipe,
	members,
	distinct_slot: nullable(distinct),
	verified_inputs_policy_hash: hash,
	inventory_hash: hash,
	closure,
	environment: environmentIdentity,
	toolchain: toolIdentities,
	build_cache: cacheIdentity,
});
const fileRef = object({ path: pathValue, hash, size: integer });
const producer = object({
	name: literal("fv_evidence_run"),
	schema_version: literal("fv-evidence-run/v4"),
	implementation_hash: hash,
	host_contract: literal("fv-producer-host/v1"),
});
const termination = object({
	exit_code: nullable(signed),
	signal: nullable(nonempty),
	timed_out: bool,
	cancelled: bool,
});
const ownedProcess = object({
	pid: positive,
	process_start_id: nonempty,
	process_group: positive,
	session_id: positive,
	parent_pid: positive,
});
const spawnWindow = object({
	window_id: uuid,
	protocol: literal("native-direct/v1", "dossier-quint-private-pipes/v1"),
	execution_key: nullable(hash),
	attempt_id: nullable(uuid),
	parent: nullable(ownedProcess),
	state: literal("pending", "active", "closed", "indeterminate"),
});
const pendingResult = object({
	kind: literal("execution", "observation"),
	execution_key: hash,
	attempt_id: uuid,
	members,
	claim_id: nullable(id),
	slot_id: nullable(id),
});
const owner = object({
	schema_version: literal("fv-evidence-owner/v1"),
	owner_id: uuid,
	host_id: hash,
	boot_id: hash,
	pid: positive,
	process_start_id: nonempty,
	run_id: uuid,
	created_at: utc,
	children: array(ownedProcess),
	spawn_windows: unique<SpawnWindow>(spawnWindow, (v) => v.window_id),
	pending_results: array(pendingResult),
});
const ownership = object({
	schema_version: literal("fv-execution-ownership/v1"),
	owner_id: uuid,
	children: array(object({ process: ownedProcess, window_id: uuid, registered_at: utc, terminated_at: nullable(utc) })),
	spawn_windows: unique<SpawnWindow>(spawnWindow, (v) => v.window_id),
	protocol_log: nullable(fileRef),
});
const executionRef = object({ execution_key: hash, artifact_id: hash, path: pathValue, hash });
const artifact = object({
	schema_version: literal("fv-execution-artifact/v1"),
	artifact_id: hash,
	execution_key: hash,
	attempt_id: uuid,
	producer,
	descriptor,
	started_at: utc,
	finished_at: utc,
	source_before: inputState,
	source_after: nullable(inputState),
	toolchain_after: nullable(toolIdentities),
	environment_after: nullable(environmentIdentity),
	stdout: fileRef,
	stderr: fileRef,
	raw_output: fileRef,
	attachments: set<FileRef>(fileRef, (v) => v.path),
	ownership,
	build_cache_after: cacheIdentity,
	termination,
	marker_matched: bool,
	result,
	reason: nullable(str),
});
const historyRef = object({ sequence: positive, event_id: hash, path: pathValue, hash });
const historyView = object({ head: nullable(historyRef), events: array(historyRef) });
const historyEvent = object({
	schema_version: literal("fv-evidence-history/v1"),
	event_id: hash,
	sequence: positive,
	previous: nullable(historyRef),
	kind: literal("execution", "observation", "indeterminate"),
	execution_key: hash,
	attempt_id: uuid,
	members,
	execution: nullable(executionRef),
	claim_id: nullable(id),
	slot_id: nullable(id),
	observation: nullable(fileRef),
	indeterminate_owner: nullable(fileRef),
	result,
});
const observationRequest = object({
	schema_version: literal("fv-claim-observation-request/v1"),
	request_id: uuid,
	policy_path: pathValue,
	policy_hash: hash,
	common,
	claim_id: id,
	created_at: utc,
	slots: unique<ObservationRequest["slots"][number]>(
		object({ slot_id: id, tool, recipe_id: id, execution: executionRef, observation_binding: binding }),
		(v) => v.slot_id,
		1,
	),
});
const jsonObject: Validator = (v, w) => {
	if (v === null || typeof v !== "object" || Array.isArray(v)) error(w, "expected observation object");
	C(v);
	const visit = (x: unknown, k?: string): void => {
		if (typeof x === "number" && x < 0 && k !== "exit_code") error(w, "negative observation integer");
		if (Array.isArray(x)) x.forEach((y) => visit(y));
		else if (x && typeof x === "object") Object.entries(x).forEach(([name, y]) => visit(y, name));
	};
	visit(v);
};
const observationResponse = object({
	schema_version: literal("fv-claim-observations/v1"),
	request_id: uuid,
	request_hash: hash,
	claim_id: id,
	started_at: utc,
	finished_at: utc,
	slots: unique<ObservationResponse["slots"][number]>(
		object({ slot_id: id, result: literal("PASS", "FAIL", "ERROR"), reason: nullable(str), observations: jsonObject }),
		(v) => v.slot_id,
		1,
	),
});
const observationCheck = object({
	schema_version: literal("fv-observation-check/v1"),
	request: fileRef,
	response: nullable(fileRef),
	started_at: utc,
	finished_at: utc,
	termination,
	stdout: fileRef,
	stderr: fileRef,
	source_before: inputState,
	source_after: nullable(inputState),
	toolchain: toolIdentities,
	result,
	reason: nullable(str),
});
const claimRecord = object({
	schema_version: literal("fv-evidence-run/v4"),
	record_id: hash,
	run_id: uuid,
	claim_id: id,
	required: bool,
	evidence_class: evidenceClass,
	scope: nonempty,
	common,
	executions: unique<ClaimRecord["executions"][number]>(
		object({
			slot_id: id,
			tool,
			recipe_id: id,
			evidence_class: evidenceClass,
			execution: nullable(executionRef),
			state: slotState,
			reason: nullable(str),
			observation_binding: binding,
			blocking_events: array(historyRef),
			observation: nullable(object({ check: fileRef, response: nullable(fileRef), result })),
		}),
		(v) => v.slot_id,
		1,
	),
	result: literal("PASS", "FAIL", "INCOMPLETE"),
	waiver: literal(null),
});
const runManifest = object({
	schema_version: literal("fv-evidence-batch/v1"),
	run_id: uuid,
	policy_path: pathValue,
	policy_hash: hash,
	common,
	producer,
	trust_assumptions: trust,
	history: historyView,
	started_at: utc,
	finished_at: utc,
	jobs: positive,
	selected_records: set(id, undefined, 1),
	required_records: set(id),
	source_before: nullable(inputState),
	source_after: nullable(inputState),
	preflight: object({
		result: literal("PASS", "ERROR", "CANCELLED"),
		reason: nullable(str),
		checks: unique<RunManifest["preflight"]["checks"][number]>(
			object({
				id,
				result: literal("PASS", "ERROR", "CANCELLED", "MISSING"),
				termination,
				stdout: nullable(fileRef),
				stderr: nullable(fileRef),
				reason: nullable(str),
			}),
			(v) => v.id,
		),
	}),
	work: array(
		object({
			recipe_id: id,
			distinct_slot: nullable(distinct),
			execution_key: nullable(hash),
			execution: nullable(executionRef),
			state: slotState,
			cache: literal("hit", "miss", "not-checked"),
			reason: nullable(str),
		}),
	),
	claims: unique<RunManifest["claims"][number]>(object({ claim_id: id, record: fileRef }), (v) => v.claim_id),
	result: literal("PASS", "FAIL", "INCOMPLETE", "ERROR", "CANCELLED"),
	reason: nullable(str),
});
const currentPointer = object({ schema_version: literal("fv-evidence-current/v1"), run_id: uuid, run: fileRef });
const call = object(
	{
		schema_version: literal("fv-evidence-run/v4"),
		policy: pathValue,
		mode: literal("plan", "run"),
		records: set(id, undefined, 1),
		jobs: positive,
		resume: bool,
	},
	["records", "jobs", "resume"],
);
const planResult = object({
	schema_version: literal("fv-evidence-plan/v1"),
	policy_path: pathValue,
	policy_hash: hash,
	result: literal("READY", "ERROR"),
	reason: nullable(str),
	required_records: set(id),
	selected_records: set(id, undefined, 1),
	canonical_required_targets: set(id, undefined, 1),
	jobs: positive,
	physical_slots: array(
		object({
			recipe_id: id,
			distinct_slot: nullable(distinct),
			members,
			execution_key: nullable(hash),
			resources: set(resource),
			exclusive: bool,
			cache: literal("eligible", "miss", "corrupt", "not-checked"),
		}),
	),
});
const runResult = object({
	schema_version: literal("fv-evidence-run-result/v1"),
	result: literal("PASS", "FAIL", "INCOMPLETE", "ERROR", "CANCELLED"),
	run: nullable(fileRef),
	manifest: nullable(runManifest),
	publication: object({
		state: literal("not-attempted", "pre-replace-error", "post-replace-error", "durable"),
		candidate: nullable(fileRef),
	}),
	reason: nullable(str),
});
function validated<T>(schema: Validator, value: unknown, name: string): T {
	schema(value, name);
	return value as T;
}
export const validatePolicyStructure = (v: unknown): Policy => validated(policySchema, v, "Policy");
export const validateV4Call = (v: unknown): V4Call => validated(call, v, "V4Call");
export const validateFileRef = (v: unknown): FileRef => validated(fileRef, v, "FileRef");
export const validateExecutionRef = (v: unknown): ExecutionRef => validated(executionRef, v, "ExecutionRef");
export const validateCommonBindings = (v: unknown): CommonBindings => validated(common, v, "CommonBindings");
export function validateInputState(v: unknown): InputState {
	const x = validated<InputState>(inputState, v, "InputState");
	if (
		x.inventory_hash !==
		D(
			"inventory",
			x.files.map(({ path, executable }) => ({ path, executable })),
		)
	)
		throw new Error("InputState inventory hash mismatch");
	const digest = createHash("sha256");
	for (const file of x.files) digest.update(file.path, "utf8").update("\0").update(file.hash.slice(7)).update("\n");
	if (x.source_snapshot !== `sha256:${digest.digest("hex")}`) throw new Error("InputState source snapshot mismatch");
	return x;
}
export function validateClosure(v: unknown): Closure {
	const x = validated<Closure>(closure, v, "Closure");
	const { hash: actual, ...value } = x;
	if (actual !== D("source-closure", value)) throw new Error("Closure hash mismatch");
	if (x.mode === "verified-inputs" && x.prefixes.length) throw new Error("whole closure has prefixes");
	if (x.mode === "prefixes" && (!x.prefixes.length || !x.basis.length))
		throw new Error("prefix closure lacks reviewed basis");
	return x;
}
export const validateEnvironmentIdentity = (v: unknown): EnvironmentIdentity => {
	const x = validated<EnvironmentIdentity>(environmentIdentity, v, "EnvironmentIdentity");
	for (const e of x.variables)
		if (e.present !== (e.value_hash !== null)) throw new Error("EnvironmentIdentity presence/hash mismatch");
	return x;
};
export const validateBuildCacheIdentity = (v: unknown): BuildCacheIdentity =>
	validated(cacheIdentity, v, "BuildCacheIdentity");
export const validatePackageIdentity = (v: unknown): PackageIdentity => {
	const x = validated<PackageIdentity>(packageIdentity, v, "PackageIdentity");
	if (x.source.kind === "git" && (!x.source.id.includes("#") || x.source.id.split("#").at(-1) !== x.source.revision))
		throw new Error("PackageIdentity git revision mismatch");
	return x;
};
export function validateToolIdentity(v: unknown): ToolIdentity {
	const x = validated<ToolIdentity>(toolIdentity, v, "ToolIdentity");
	x.packages.forEach(validatePackageIdentity);
	if ((x.version !== null && x.version.exit_code !== 0) || x.discovery.some((probe) => probe.exit_code !== 0))
		throw new Error("tool probe did not complete successfully");
	const byPath = new Map(x.files.map((file) => [file.path, file]));
	if (x.kind !== "tree" && (x.files.length !== 1 || x.files[0]!.path !== "." || x.files[0]!.kind !== "file"))
		throw new Error("non-tree tool must have one regular root file");
	if (x.kind === "executable" && (x.files[0]!.kind !== "file" || !x.files[0]!.executable))
		throw new Error("tool executable bit absent");
	for (const file of x.files) {
		let parent = file.path.includes("/") ? file.path.slice(0, file.path.lastIndexOf("/")) : null;
		while (parent !== null) {
			if (byPath.get(parent)?.kind !== "directory")
				throw new Error(`tool path has missing/non-directory parent: ${file.path}`);
			parent = parent.includes("/") ? parent.slice(0, parent.lastIndexOf("/")) : null;
		}
		if ((file.kind === "symlink-file" || file.kind === "symlink-directory") && file.target.includes("\0"))
			throw new Error("NUL symlink target");
	}
	const visiting = new Set<string>();
	const done = new Set<string>();
	function checkLink(file: ToolFile): void {
		if (file.kind !== "symlink-file" && file.kind !== "symlink-directory") return;
		if (done.has(file.path)) return;
		if (visiting.has(file.path)) throw new Error("cyclic tool target-hash graph");
		visiting.add(file.path);
		const target = byPath.get(file.resolved_path);
		if (file.kind === "symlink-file") {
			if (
				target?.kind !== "file" ||
				file.resolved_hash !== target.hash ||
				file.resolved_size !== target.size ||
				file.executable !== target.executable
			)
				throw new Error("tool symlink-file target mismatch");
		} else {
			if (target?.kind !== "directory") throw new Error("tool symlink-directory target missing");
			const prefix = file.resolved_path === "." ? "" : file.resolved_path + "/";
			const descendants = x.files.filter(
				(entry) => entry.path !== file.resolved_path && (prefix === "" || entry.path.startsWith(prefix)),
			);
			for (const entry of descendants) checkLink(entry);
			const entries = descendants
				.map((entry) => ({ ...entry, path: prefix === "" ? entry.path : entry.path.slice(prefix.length) }))
				.sort((a, b) => utf8Compare(a.path, b.path));
			if (file.resolved_hash !== D("tool-directory", { entries }))
				throw new Error("tool symlink-directory hash mismatch");
		}
		visiting.delete(file.path);
		done.add(file.path);
	}
	x.files.forEach(checkLink);
	for (const pkg of x.packages)
		if (byPath.get(`packages/${D("cargo-package", pkg).slice(7)}`)?.kind !== "directory")
			throw new Error("source-qualified package root missing");
	if (
		x.digest !==
		D("tool-content", {
			kind: x.kind,
			files: x.files,
			packages: x.packages,
			system_dependencies: x.system_dependencies,
		})
	)
		throw new Error("tool content digest mismatch");
	return x;
}
export function validateExecutionDescriptor(v: unknown): ExecutionDescriptor {
	const x = validated<ExecutionDescriptor>(descriptor, v, "ExecutionDescriptor");
	validateClosure(x.closure);
	validateEnvironmentIdentity(x.environment);
	x.toolchain.forEach(validateToolIdentity);
	if (x.recipe.determinism.mode === "fixed" && x.distinct_slot !== null)
		throw new Error("fixed descriptor has distinct slot");
	if (
		x.recipe.determinism.mode === "distinct" &&
		(x.distinct_slot === null ||
			x.members.length !== 1 ||
			x.members[0]!.claim_id !== x.distinct_slot.claim_id ||
			x.members[0]!.slot_id !== x.distinct_slot.slot_id)
	)
		throw new Error("distinct descriptor membership mismatch");
	const tools = new Map(x.toolchain.map((t) => [t.id, t]));
	const required = new Set<string>();
	const active = new Set<string>();
	function visit(id: string): void {
		if (active.has(id)) throw new Error("cyclic descriptor tool closure");
		if (required.has(id)) return;
		const identity = tools.get(id);
		if (!identity) throw new Error(`missing descriptor tool: ${id}`);
		active.add(id);
		identity.requires.forEach(visit);
		active.delete(id);
		required.add(id);
	}
	visit("fv-producer");
	x.recipe.toolchain.forEach(visit);
	if (required.size !== tools.size) throw new Error("descriptor includes undeclared tool identities");
	const producer = tools.get("fv-producer")!;
	if (producer.locator.mode !== "adapter" || producer.locator.value !== "producer-runtime")
		throw new Error("reserved producer locator mismatch");
	if (
		(x.recipe.build_cache === null) !== (x.build_cache === null) ||
		(x.recipe.build_cache && x.recipe.build_cache.system !== x.build_cache?.system)
	)
		throw new Error("descriptor cache system mismatch");
	return x;
}
export function validateExecutionArtifact(v: unknown): ExecutionArtifact {
	const x = validated<ExecutionArtifact>(artifact, v, "ExecutionArtifact");
	validateExecutionDescriptor(x.descriptor);
	validateInputState(x.source_before);
	if (x.source_after) validateInputState(x.source_after);
	if (x.toolchain_after) x.toolchain_after.forEach(validateToolIdentity);
	if (x.environment_after) validateEnvironmentIdentity(x.environment_after);
	if (x.execution_key !== D("execution-key", x.descriptor)) throw new Error("artifact execution key mismatch");
	const { artifact_id, ...value } = x;
	if (artifact_id !== D("execution-artifact", value)) throw new Error("artifact identity mismatch");
	if (x.started_at > x.finished_at) throw new Error("artifact interval reversed");
	if (
		x.result === "PASS" &&
		(!x.source_after ||
			!x.source_before.clean ||
			!x.source_after.clean ||
			H(C(x.source_before)) !== H(C(x.source_after)) ||
			x.toolchain_after === null ||
			H(C(x.descriptor.toolchain)) !== H(C(x.toolchain_after)) ||
			x.environment_after === null ||
			H(C(x.descriptor.environment)) !== H(C(x.environment_after)) ||
			H(C(x.descriptor.build_cache)) !== H(C(x.build_cache_after)) ||
			x.termination.exit_code !== 0 ||
			x.termination.signal !== null ||
			x.termination.timed_out ||
			x.termination.cancelled ||
			!x.marker_matched ||
			x.ownership.spawn_windows.some((w) => w.state !== "closed") ||
			x.ownership.children.some((c) => c.terminated_at === null))
	)
		throw new Error("artifact PASS has incomplete or inconsistent completion");
	return x;
}
export const validateOwnedProcess = (v: unknown): OwnedProcess => validated(ownedProcess, v, "OwnedProcess");
export const validateSpawnWindow = (v: unknown): SpawnWindow => validated(spawnWindow, v, "SpawnWindow");
export const validatePendingResult = (v: unknown): PendingResult => validated(pendingResult, v, "PendingResult");
export const validateOwnerRecord = (v: unknown): Owner => validated(owner, v, "Owner");
export const validateOwner = validateOwnerRecord;
export const validateOwnershipReceipt = (v: unknown): OwnershipReceipt => validated(ownership, v, "OwnershipReceipt");
export const validateHistoryRef = (v: unknown): HistoryRef => validated(historyRef, v, "HistoryRef");
export function validateHistoryView(v: unknown): HistoryView {
	const x = validated<HistoryView>(historyView, v, "HistoryView");
	for (let i = 0; i < x.events.length; i++)
		if (x.events[i]!.sequence !== i + 1) throw new Error("history view is not complete contiguous prefix");
	if (H(C(x.head)) !== H(C(x.events.at(-1) ?? null))) throw new Error("history view head mismatch");
	return x;
}
export function validateHistoryEvent(v: unknown): HistoryEvent {
	const x = validated<HistoryEvent>(historyEvent, v, "HistoryEvent");
	const { event_id, ...value } = x;
	if (event_id !== D("history-event", value)) throw new Error("history event identity mismatch");
	if ((x.sequence === 1) !== (x.previous === null) || (x.previous && x.previous.sequence !== x.sequence - 1))
		throw new Error("history predecessor sequence mismatch");
	if (
		x.kind === "execution" &&
		(x.claim_id !== null ||
			x.slot_id !== null ||
			x.observation !== null ||
			x.indeterminate_owner !== null ||
			(x.result === "PASS" && x.execution === null))
	)
		throw new Error("execution history fields mismatch");
	if (
		x.kind === "observation" &&
		(!x.members.some((m) => m.claim_id === x.claim_id && m.slot_id === x.slot_id) ||
			x.indeterminate_owner !== null ||
			(x.result === "PASS" && (x.execution === null || x.observation === null)))
	)
		throw new Error("observation history fields mismatch");
	if (x.kind === "indeterminate" && (x.result !== "ERROR" || x.indeterminate_owner === null))
		throw new Error("indeterminate history requires recovered owner and ERROR");
	return x;
}
export const validateObservationRequest = (v: unknown): ObservationRequest =>
	validated(observationRequest, v, "ObservationRequest");
export function validateObservationResponse(v: unknown): ObservationResponse {
	const x = validated<ObservationResponse>(observationResponse, v, "ObservationResponse");
	if (x.started_at > x.finished_at) throw new Error("observation response interval reversed");
	return x;
}
export function validateObservationCheck(v: unknown): ObservationCheck {
	const x = validated<ObservationCheck>(observationCheck, v, "ObservationCheck");
	validateInputState(x.source_before);
	if (x.source_after) validateInputState(x.source_after);
	x.toolchain.forEach(validateToolIdentity);
	if (x.started_at > x.finished_at) throw new Error("observation interval reversed");
	if (
		x.result === "PASS" &&
		(!x.response ||
			!x.source_before.clean ||
			!x.source_after?.clean ||
			H(C(x.source_before)) !== H(C(x.source_after)) ||
			x.termination.exit_code !== 0 ||
			x.termination.signal !== null ||
			x.termination.cancelled ||
			x.termination.timed_out)
	)
		throw new Error("observation PASS has incomplete completion");
	return x;
}
export function validateClaimRecord(v: unknown): ClaimRecord {
	const x = validated<ClaimRecord>(claimRecord, v, "ClaimRecord");
	const { record_id, ...value } = x;
	if (record_id !== D("claim-record", value)) throw new Error("claim record identity mismatch");
	const tools = new Set<string>();
	for (const slot of x.executions) {
		if (tools.has(slot.tool)) throw new Error("duplicate claim evidence tool");
		tools.add(slot.tool);
	}
	if (
		x.result === "PASS" &&
		x.executions.some(
			(slot) =>
				slot.state !== "PASS" ||
				slot.execution === null ||
				slot.observation?.result !== "PASS" ||
				slot.observation.response === null,
		)
	)
		throw new Error("claim PASS lacks eligible execution/observation");
	return x;
}
export function validateRunManifest(v: unknown): RunManifest {
	const x = validated<RunManifest>(runManifest, v, "RunManifest");
	validateHistoryView(x.history);
	if (x.source_before) validateInputState(x.source_before);
	if (x.source_after) validateInputState(x.source_after);
	if (x.started_at > x.finished_at) throw new Error("run interval reversed");
	if (x.policy_path !== x.common.policy_path || x.policy_hash !== x.common.policy_hash)
		throw new Error("run common policy mismatch");
	const claims = new Set(x.claims.map((claim) => claim.claim_id));
	if (x.required_records.some((id) => !claims.has(id))) throw new Error("run omits required claim references");
	if (
		x.result === "PASS" &&
		(!x.source_before?.clean ||
			!x.source_after?.clean ||
			H(C(x.source_before)) !== H(C(x.source_after)) ||
			x.preflight.result !== "PASS" ||
			x.preflight.checks.some((check) => check.result !== "PASS"))
	)
		throw new Error("run PASS lacks stable clean source/preflight");
	return x;
}
export const validateCurrentPointer = (v: unknown): CurrentPointer => validated(currentPointer, v, "CurrentPointer");
export function validatePlanResult(v: unknown): PlanResult {
	const x = validated<PlanResult>(planResult, v, "PlanResult");
	if (x.result === "READY" && x.physical_slots.some((slot) => slot.execution_key === null || slot.cache === "corrupt"))
		throw new Error("READY plan lacks valid slot identities");
	return x;
}
export function validateRunResult(v: unknown): RunResult {
	const x = validated<RunResult>(runResult, v, "RunResult");
	if (x.manifest) validateRunManifest(x.manifest);
	if (
		x.result === "PASS" &&
		(x.run === null ||
			x.manifest?.result !== "PASS" ||
			x.publication.state !== "durable" ||
			H(C(x.run)) !== H(C(x.publication.candidate)))
	)
		throw new Error("run PASS lacks durable publication");
	return x;
}
