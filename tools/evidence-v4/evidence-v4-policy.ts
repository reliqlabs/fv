import * as fs from "node:fs/promises";
import * as path from "node:path";
import {
	C,
	D,
	H,
	parseJSON,
	utf8Compare,
	validPath,
	validatePolicyStructure,
	validateV4Call,
	type CommonBindings,
	type Member,
	type Policy,
	type PolicyRecord,
	type Recipe,
	type V4Call,
} from "./evidence-v4-model";

export type ObligationKind = "invariant" | "witness" | "system_claim";
export type LoadedPolicy = {
	policy: Policy;
	path: string;
	hash: string;
	common: CommonBindings;
	manifest: Record<string, unknown>;
	mandatoryPaths: string[];
	obligationKinds: Record<string, ObligationKind>;
	dependencies: Record<string, string[]>;
	requiredEvidence: Record<string, string[]>;
	requiredStatus: Record<string, boolean>;
};
export type ExpandedSlot = {
	claim_id: string;
	slot_id: string;
	tool: string;
	recipe_id: string;
	record: PolicyRecord;
	member: Member;
	recipe: Recipe;
};
export type ExpandedExecution = {
	recipe: Recipe;
	distinct: { claim_id: string; slot_id: string } | null;
	members: Member[];
	slots: ExpandedSlot[];
};
export type ExpandedPlan = { slots: ExpandedSlot[]; executions: ExpandedExecution[] };
const classes: Record<ObligationKind, readonly string[]> = {
	invariant: ["code-enforced", "proof-discharged", "bounded-checked", "conformance-tested"],
	witness: ["test-witnessed", "conformance-tested"],
	system_claim: ["code-enforced", "proof-discharged", "bounded-checked", "test-witnessed", "conformance-tested"],
};
const idPattern = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;
const toolPattern = /^[A-Za-z0-9][A-Za-z0-9._:+/-]*$/;
const reservedEnvironment = "DOSSIER_QUINT_OWNERSHIP_FDS";
export function validateCall(value: unknown): V4Call {
	return validateV4Call(value);
}
export function validatePolicy(value: unknown): Policy {
	const policy = validatePolicyStructure(value);
	const union = [...new Set([...policy.environment.inherit, ...Object.keys(policy.environment.set)])].sort(utf8Compare);
	if (H(C(union)) !== H(C(policy.environment.identity)))
		throw new Error("environment.identity is not inherit union set");
	if (union.includes(reservedEnvironment)) throw new Error("reserved ownership environment variable");
	const tools = new Map(policy.toolchains.map((t) => [t.id, t]));
	if (tools.has("fv-producer")) throw new Error("reserved fv-producer declaration");
	const visited = new Set<string>();
	const active = new Set<string>();
	function visit(id: string): void {
		if (id === "fv-producer") throw new Error("policy cannot reference fv-producer");
		if (active.has(id)) throw new Error(`cyclic toolchain requires: ${id}`);
		if (visited.has(id)) return;
		const declaration = tools.get(id);
		if (!declaration) throw new Error(`unknown toolchain: ${id}`);
		active.add(id);
		declaration.requires.forEach(visit);
		active.delete(id);
		visited.add(id);
	}
	for (const declaration of policy.toolchains) {
		visit(declaration.id);
		if ((declaration.version_command === null) !== (declaration.version_cwd === null))
			throw new Error(`version command/cwd mismatch: ${declaration.id}`);
		if (declaration.version_command === null && declaration.accept.version_contains.length)
			throw new Error(`version requirement without version command: ${declaration.id}`);
		const locator = declaration.locator;
		if (locator.mode === "command" || locator.mode === "command-relative") {
			if (locator.value.includes("/") || locator.value.includes("\\") || /[\x00-\x1f\x7f-\x9f]/.test(locator.value))
				throw new Error(`unsafe command locator: ${declaration.id}`);
		} else if (locator.mode === "path") {
			if (
				locator.value.startsWith("~") ||
				locator.value.includes("\0") ||
				(!path.isAbsolute(locator.value) && !validPath(locator.value))
			)
				throw new Error(`unsafe tool path locator: ${declaration.id}`);
		}
	}
	for (const check of [...policy.preflight, policy.claim_checker]) check.toolchain.forEach(visit);
	if (policy.preflight.some((c) => c.id === policy.claim_checker.id))
		throw new Error("claim checker and preflight IDs collide");
	if (policy.claim_checker.timeout_seconds === null) throw new Error("claim checker needs finite timeout");
	const recipes = new Map(policy.recipes.map((r) => [r.recipe_id, r]));
	const used = new Set<string>();
	for (const recipe of policy.recipes) {
		recipe.toolchain.forEach(visit);
		const overlap = recipe.resources.find((resource) => policy.claim_checker.resources.includes(resource));
		if (overlap !== undefined)
			throw new Error(`claim checker resource overlaps recipe ${recipe.recipe_id}: ${overlap}`);
		if (recipe.source_closure.mode === "verified-inputs" && recipe.source_closure.prefixes.length)
			throw new Error(`whole-input closure has prefixes: ${recipe.recipe_id}`);
		if (recipe.source_closure.mode === "prefixes" && !recipe.source_closure.prefixes.length)
			throw new Error(`prefix closure has no prefixes: ${recipe.recipe_id}`);
		if (recipe.build_cache?.resources.some((r) => !recipe.resources.includes(r)))
			throw new Error(`build cache resource not held: ${recipe.recipe_id}`);
		if (recipe.retained_environment.includes(reservedEnvironment))
			throw new Error("ownership FD cannot be retained environment");
		if (recipe.retained_environment.length && recipe.attestation === null)
			throw new Error(`retained environment without collector: ${recipe.recipe_id}`);
		if (recipe.ownership_protocol && recipe.attestation === null)
			throw new Error(`ownership protocol without collector: ${recipe.recipe_id}`);
		for (const [field, option] of [
			["samples", "--max-samples"],
			["max_steps", "--max-steps"],
			["seed", "--seed"],
		] as const) {
			const declared = recipe.bounds[field];
			const found: string[] = [];
			for (let i = 0; i < recipe.command.length; i++) {
				const arg = recipe.command[i]!;
				if (arg === option) {
					const next = recipe.command[++i];
					if (next === undefined) throw new Error(`missing ${option}`);
					found.push(next);
				} else if (arg.startsWith(`${option}=`)) found.push(arg.slice(option.length + 1));
			}
			if (found.length > 1 || (found.length && String(declared) !== found[0]) || (declared !== null && !found.length))
				throw new Error(`bounds disagree with argv: ${recipe.recipe_id}.${field}`);
		}
	}
	for (const record of policy.records) {
		const evidenceTools = new Set<string>();
		for (const slot of record.executions) {
			if (!recipes.has(slot.recipe_id)) throw new Error(`unknown recipe ${slot.recipe_id}`);
			if (evidenceTools.has(slot.tool)) throw new Error(`duplicate evidence tool in ${record.claim_id}: ${slot.tool}`);
			evidenceTools.add(slot.tool);
			used.add(slot.recipe_id);
		}
	}
	for (const recipe of policy.recipes)
		if (!used.has(recipe.recipe_id)) throw new Error(`recipe has no members: ${recipe.recipe_id}`);
	return policy;
}
export function expandPolicy(policy: Policy): ExpandedPlan {
	const recipes = new Map(policy.recipes.map((r) => [r.recipe_id, r]));
	const shared = new Map<string, ExpandedExecution>();
	const slots: ExpandedSlot[] = [];
	const executions: ExpandedExecution[] = [];
	for (const record of policy.records)
		for (const slot of record.executions) {
			const recipe = recipes.get(slot.recipe_id);
			if (!recipe) throw new Error(`unknown recipe ${slot.recipe_id}`);
			const member = { claim_id: record.claim_id, slot_id: slot.slot_id, tool: slot.tool };
			const expanded: ExpandedSlot = {
				claim_id: record.claim_id,
				slot_id: slot.slot_id,
				tool: slot.tool,
				recipe_id: slot.recipe_id,
				record,
				member,
				recipe,
			};
			slots.push(expanded);
			let execution = recipe.determinism.mode === "fixed" ? shared.get(recipe.recipe_id) : undefined;
			if (!execution) {
				execution = {
					recipe,
					distinct:
						recipe.determinism.mode === "distinct" ? { claim_id: record.claim_id, slot_id: slot.slot_id } : null,
					members: [],
					slots: [],
				};
				executions.push(execution);
				if (recipe.determinism.mode === "fixed") shared.set(recipe.recipe_id, execution);
			}
			execution.members.push(member);
			execution.slots.push(expanded);
		}
	for (const execution of executions)
		execution.members.sort((a, b) => utf8Compare(a.claim_id, b.claim_id) || utf8Compare(a.slot_id, b.slot_id));
	return { slots, executions };
}
export async function safeDirectoryPath(root: string, relative: string): Promise<string> {
	if (!validPath(relative, true)) throw new Error(`unsafe directory: ${relative}`);
	const realRoot = await fs.realpath(root);
	let current = realRoot;
	for (const component of relative === "." ? [] : relative.split("/")) {
		current = path.join(current, component);
		const stat = await fs.lstat(current);
		if (!stat.isDirectory() || stat.isSymbolicLink()) throw new Error(`unsafe directory component: ${relative}`);
	}
	const resolved = await fs.realpath(current);
	if (resolved !== realRoot && !resolved.startsWith(realRoot + path.sep))
		throw new Error(`directory escapes project root: ${relative}`);
	return resolved;
}
export async function safeSourcePath(root: string, relative: string): Promise<string> {
	if (!validPath(relative)) throw new Error(`unsafe source path: ${relative}`);
	const realRoot = await fs.realpath(root);
	let current = realRoot;
	const parts = relative.split("/");
	for (let i = 0; i < parts.length; i++) {
		current = path.join(current, parts[i]!);
		const stat = await fs.lstat(current);
		if (stat.isSymbolicLink()) throw new Error(`symlink source component: ${relative}`);
		if (i < parts.length - 1 && !stat.isDirectory()) throw new Error(`non-directory source component: ${relative}`);
		if (i === parts.length - 1 && !stat.isFile()) throw new Error(`nonregular source: ${relative}`);
	}
	const resolved = await fs.realpath(current);
	if (!resolved.startsWith(realRoot + path.sep)) throw new Error(`source escapes project root: ${relative}`);
	return resolved;
}
export function resolvePointer(document: unknown, pointer: string): Record<string, unknown> | unknown[] {
	if (pointer !== "" && (!pointer.startsWith("/") || /~(?![01])/.test(pointer)))
		throw new Error(`invalid JSON pointer: ${pointer}`);
	let current = document;
	for (const encoded of pointer === "" ? [] : pointer.slice(1).split("/")) {
		const key = encoded.replace(/~1/g, "/").replace(/~0/g, "~");
		if (current === null || typeof current !== "object") throw new Error(`missing JSON pointer: ${pointer}`);
		if (Array.isArray(current) && !/^(?:0|[1-9][0-9]*)$/.test(key))
			throw new Error(`invalid array pointer: ${pointer}`);
		if (!Object.hasOwn(current, key)) throw new Error(`missing JSON pointer: ${pointer}`);
		current = (current as Record<string, unknown>)[key];
	}
	if (current === null || typeof current !== "object")
		throw new Error(`JSON pointer must name object/array: ${pointer}`);
	return current as Record<string, unknown> | unknown[];
}
function objectValue(value: unknown, label: string): Record<string, unknown> {
	if (value === null || typeof value !== "object" || Array.isArray(value))
		throw new Error(`${label} must be an object`);
	return value as Record<string, unknown>;
}
function ids(value: unknown, label: string, pattern = idPattern): string[] {
	if (
		!Array.isArray(value) ||
		!value.length ||
		value.some((x) => typeof x !== "string" || !pattern.test(x)) ||
		new Set(value).size !== value.length
	)
		throw new Error(`${label} must be unique nonempty IDs`);
	return value as string[];
}
async function canonicalTargetPath(realRoot: string, spec: string): Promise<string> {
	const first = spec.split("/").find((component) => component !== "" && component !== ".");
	if (!path.isAbsolute(spec) && first?.startsWith("~")) throw new Error("target_spec must not start with '~'");
	const candidate = path.resolve(realRoot, spec);
	const relative = path.relative(realRoot, candidate);
	if (!validPath(relative)) throw new Error(`unsafe or escaping target_spec: ${spec}`);
	if ((await fs.lstat(candidate)).isSymbolicLink()) throw new Error(`target_spec is a symlink: ${spec}`);
	const canonical = path.relative(realRoot, await fs.realpath(candidate));
	await safeSourcePath(realRoot, canonical);
	return canonical;
}
export async function loadPolicy(root: string, policyPath: string, targetPath?: string): Promise<LoadedPolicy> {
	const absolute = await safeSourcePath(root, policyPath);
	const realRoot = await fs.realpath(root);
	const policy = validatePolicy(parseJSON(await fs.readFile(absolute)));
	const directories = new Set([
		".",
		...policy.recipes.map((r) => r.cwd),
		...policy.preflight.map((c) => c.cwd),
		policy.claim_checker.cwd,
	]);
	for (const declaration of policy.toolchains) {
		if (declaration.version_cwd !== null) directories.add(declaration.version_cwd);
		if (declaration.locator.mode === "adapter") directories.add(declaration.locator.cwd);
	}
	for (const directory of directories) await safeDirectoryPath(root, directory);
	let dispatchBytes: Buffer | null = null;
	let canonical = ".fv/intent.md";
	try {
		await fs.lstat(path.join(root, ".fv/dispatch.json"));
		dispatchBytes = await fs.readFile(await safeSourcePath(root, ".fv/dispatch.json"));
	} catch (error) {
		if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
	}
	if (dispatchBytes !== null) {
		const dispatch = objectValue(parseJSON(dispatchBytes), "dispatch");
		if (Object.hasOwn(dispatch, "omp_native")) {
			const native = objectValue(dispatch.omp_native, "omp_native");
			if (native.target_spec !== null && native.target_spec !== undefined) {
				if (typeof native.target_spec !== "string") throw new Error("dispatch target_spec is not a string");
				if (native.target_spec.trim()) canonical = native.target_spec;
			}
		}
	}
	canonical = await canonicalTargetPath(realRoot, canonical);
	if (targetPath !== undefined && (await canonicalTargetPath(realRoot, targetPath)) !== canonical)
		throw new Error("caller target differs from canonical dispatch target");
	if (policy.intent_path !== canonical) throw new Error("policy intent_path differs from canonical dispatch target");
	const intentBytes = await fs.readFile(await safeSourcePath(root, canonical));
	const manifestBytes = await fs.readFile(await safeSourcePath(root, policy.manifest_path));
	const manifest = objectValue(parseJSON(manifestBytes), "manifest");
	const obligationKinds: Record<string, ObligationKind> = Object.create(null);
	const requiredStatus: Record<string, boolean> = Object.create(null);
	const requiredEvidence: Record<string, string[]> = Object.create(null);
	const dependencies: Record<string, string[]> = Object.create(null);
	const entries = new Map<string, Record<string, unknown>>();
	for (const [collection, kind] of [
		["invariants", "invariant"],
		["witnesses", "witness"],
		["system_claims", "system_claim"],
	] as const) {
		const values = manifest[collection] ?? [];
		if (!Array.isArray(values)) throw new Error(`manifest ${collection} is not an array`);
		for (const value of values) {
			const entry = objectValue(value, collection);
			const id = entry.id;
			if (typeof id !== "string" || !idPattern.test(id) || entries.has(id))
				throw new Error(`malformed/duplicate obligation ID: ${String(id)}`);
			if (entry.required !== undefined && typeof entry.required !== "boolean")
				throw new Error(`invalid required status: ${id}`);
			entries.set(id, entry);
			obligationKinds[id] = kind;
			requiredStatus[id] = entry.required !== false;
			dependencies[id] = [];
			requiredEvidence[id] = [];
		}
	}
	if (!entries.size) throw new Error("manifest has no obligations");
	for (const [id, entry] of entries)
		if (obligationKinds[id] === "system_claim") {
			dependencies[id] = ids(entry.depends_on, `${id}.depends_on`);
			requiredEvidence[id] = ids(entry.required_evidence, `${id}.required_evidence`, toolPattern);
			for (const dependency of dependencies[id]!)
				if (!entries.has(dependency) || obligationKinds[dependency] === "system_claim")
					throw new Error(`invalid canonical dependency: ${id} -> ${dependency}`);
		}
	const records = new Map(policy.records.map((r) => [r.claim_id, r]));
	const recipes = new Map(policy.recipes.map((r) => [r.recipe_id, r]));
	for (const record of policy.records) {
		const kind = obligationKinds[record.claim_id];
		if (!kind) throw new Error(`policy names undeclared obligation: ${record.claim_id}`);
		if (record.required !== requiredStatus[record.claim_id])
			throw new Error(`required status disagrees: ${record.claim_id}`);
		if (!classes[kind].includes(record.evidence_class))
			throw new Error(`record class incompatible: ${record.claim_id}`);
		for (const slot of record.executions)
			if (!classes[kind].includes(recipes.get(slot.recipe_id)!.evidence_class))
				throw new Error(`recipe class incompatible: ${record.claim_id}/${slot.slot_id}`);
		for (const dependency of dependencies[record.claim_id]!)
			if (!records.has(dependency))
				throw new Error(`policy drops canonical dependency: ${record.claim_id}/${dependency}`);
		const tools = new Set(record.executions.map((s) => s.tool));
		for (const tool of requiredEvidence[record.claim_id]!)
			if (!tools.has(tool)) throw new Error(`policy drops required evidence: ${record.claim_id}/${tool}`);
	}
	const definitionFiles: { path: string; hash: string }[] = [];
	const mandatory = new Set([policyPath, canonical, policy.manifest_path]);
	if (dispatchBytes !== null) mandatory.add(".fv/dispatch.json");
	const documents = new Map<string, unknown>();
	for (const relative of policy.definition_files) {
		const bytes = await fs.readFile(await safeSourcePath(root, relative));
		definitionFiles.push({ path: relative, hash: H(bytes) });
		mandatory.add(relative);
	}
	for (const record of policy.records)
		for (const slot of record.executions) {
			if (!policy.definition_files.includes(slot.observation_binding.path))
				throw new Error(`observation definition is not incorporated: ${slot.observation_binding.path}`);
			mandatory.add(slot.observation_binding.path);
			if (!documents.has(slot.observation_binding.path))
				documents.set(
					slot.observation_binding.path,
					parseJSON(await fs.readFile(await safeSourcePath(root, slot.observation_binding.path))),
				);
			resolvePointer(documents.get(slot.observation_binding.path), slot.observation_binding.pointer);
		}
	for (const recipe of policy.recipes) {
		for (const relative of [...recipe.source_closure.basis, ...(recipe.build_cache?.configuration ?? [])]) {
			await safeSourcePath(root, relative);
			mandatory.add(relative);
		}
		if (recipe.attestation) {
			if (!policy.definition_files.includes(recipe.attestation.path))
				throw new Error(`collector contract is not incorporated: ${recipe.attestation.path}`);
			if (!documents.has(recipe.attestation.path))
				documents.set(
					recipe.attestation.path,
					parseJSON(await fs.readFile(await safeSourcePath(root, recipe.attestation.path))),
				);
			resolvePointer(documents.get(recipe.attestation.path), recipe.attestation.pointer);
			mandatory.add(recipe.attestation.path);
		}
	}
	// Incorporate source files named by checker argv without treating code strings as paths.
	for (const arg of policy.claim_checker.command)
		if (validPath(arg) && /\.(?:py|[cm]?js|ts|sh)$/.test(arg)) {
			const relative = policy.claim_checker.cwd === "." ? arg : `${policy.claim_checker.cwd}/${arg}`;
			if (!policy.definition_files.includes(relative))
				throw new Error(`claim checker source is not incorporated: ${relative}`);
			mandatory.add(relative);
		}
	const hash = D("policy", policy);
	const common: CommonBindings = {
		policy_path: policyPath,
		policy_hash: hash,
		intent_path: canonical,
		intent_hash: H(intentBytes),
		manifest_path: policy.manifest_path,
		manifest_hash: H(manifestBytes),
		definition_files: definitionFiles,
		dispatch_hash: dispatchBytes === null ? null : H(dispatchBytes),
		required_targets: [...entries.keys()].sort(utf8Compare),
	};
	return {
		policy,
		path: policyPath,
		hash,
		common,
		manifest,
		mandatoryPaths: [...mandatory].sort(utf8Compare),
		obligationKinds,
		dependencies,
		requiredEvidence,
		requiredStatus,
	};
}
