import * as fs from "node:fs/promises";
import { createHash } from "node:crypto";
import { createReadStream } from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { loadInputPolicy, policySelects, orderVerifiedInputs } from "../evidence-run";
import {
	C,
	D,
	H,
	decodeUTF8,
	parseJSON,
	utf8Compare,
	validPath,
	validateEnvironmentIdentity,
	validateExecutionDescriptor,
	type BuildCacheIdentity,
	type Closure,
	type DistinctSlot,
	type EnvironmentIdentity,
	type ExecutionDescriptor,
	type InputState,
	type Policy,
	type Recipe,
	type SourceFile,
	type ToolIdentity,
} from "./evidence-v4-model";
import { expandPolicy, safeSourcePath, type LoadedPolicy } from "./evidence-v4-policy";
export { safeSourcePath } from "./evidence-v4-policy";

export type SourceProbe = (
	command: string[],
	cwd: string,
	signal?: AbortSignal,
) => Promise<{ stdout: Buffer; stderr: Buffer; exit_code: number | null }>;
export type SanitizedEnvironment = { env: Record<string, string>; identity: EnvironmentIdentity };
export function prefixSelects(relative: string, prefix: string): boolean {
	const base = prefix.endsWith("/") ? prefix.slice(0, -1) : prefix;
	return relative === base || relative.startsWith(base + "/");
}
export function commonBindingPaths(loaded: LoadedPolicy): string[] {
	return [
		...new Set([
			loaded.path,
			loaded.policy.intent_path,
			loaded.policy.manifest_path,
			...loaded.policy.definition_files,
			...(loaded.common.dispatch_hash === null ? [] : [".fv/dispatch.json"]),
		]),
	].sort(utf8Compare);
}
async function hashSource(
	root: string,
	relative: string,
	aliases: Map<string, string>,
	signal?: AbortSignal,
): Promise<SourceFile> {
	if (signal?.aborted) throw signal.reason ?? new Error("source capture cancelled");
	const absolute = await safeSourcePath(root, relative);
	const before = await fs.lstat(absolute, { bigint: true });
	if (before.nlink !== 1n) throw new Error(`hardlinked source: ${relative}`);
	const identity = `${before.dev}:${before.ino}`;
	const prior = aliases.get(identity);
	if (prior !== undefined) throw new Error(`aliased source: ${relative} and ${prior}`);
	aliases.set(identity, relative);
	const hasher = createHash("sha256");
	let size = 0;
	const stream = createReadStream(absolute, { signal });
	for await (const chunk of stream) {
		hasher.update(chunk);
		size += chunk.length;
	}
	const after = await fs.lstat(absolute, { bigint: true });
	if (
		before.dev !== after.dev ||
		before.ino !== after.ino ||
		before.size !== after.size ||
		before.mtimeNs !== after.mtimeNs ||
		before.ctimeNs !== after.ctimeNs ||
		before.mode !== after.mode ||
		after.nlink !== 1n ||
		!after.isFile()
	)
		throw new Error(`source moved during capture: ${relative}`);
	if (!Number.isSafeInteger(size) || BigInt(size) !== before.size) throw new Error(`source size changed: ${relative}`);
	return { path: relative, hash: `sha256:${hasher.digest("hex")}`, size, executable: (before.mode & 0o111n) !== 0n };
}
function nulFields(bytes: Buffer, label: string): string[] {
	const text = decodeUTF8(bytes);
	if (text && !text.endsWith("\0")) throw new Error(`unterminated ${label} output`);
	return text ? text.slice(0, -1).split("\0") : [];
}
export async function captureInputState(
	root: string,
	loaded: LoadedPolicy,
	probe: SourceProbe,
	signal?: AbortSignal,
): Promise<InputState> {
	const realRoot = await fs.realpath(root);
	const inputPolicy = await loadInputPolicy(realRoot);
	let verifiedPolicyHash: string;
	try {
		await fs.lstat(path.join(realRoot, loaded.policy.verified_inputs));
		verifiedPolicyHash = H(await fs.readFile(await safeSourcePath(realRoot, loaded.policy.verified_inputs)));
	} catch (error) {
		if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
		verifiedPolicyHash = D("verified-inputs-default", {
			mode: "exclude",
			prefixes: [],
			structural: inputPolicy.structural,
		});
	}
	const mandatory = new Set(loaded.mandatoryPaths);
	for (const relative of mandatory)
		if (inputPolicy.structural.some((prefix) => prefixSelects(relative, prefix)))
			throw new Error(`mandatory source is structural output: ${relative}`);
	try {
		await fs.lstat(path.join(realRoot, loaded.policy.verified_inputs));
		mandatory.add(loaded.policy.verified_inputs);
	} catch (error) {
		if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
	}
	const selected = (relative: string): boolean => mandatory.has(relative) || policySelects(relative, inputPolicy);
	async function git(args: string[]): Promise<Buffer> {
		const result = await probe(["git", ...args], realRoot, signal);
		decodeUTF8(result.stderr);
		if (result.exit_code !== 0) throw new Error(`git ${args[0]} failed during source capture`);
		return result.stdout;
	}
	const listed = nulFields(await git(["ls-files", "--cached", "--others", "--exclude-standard", "-z"]), "git ls-files");
	const candidates = new Set<string>();
	for (const relative of listed) {
		if (!selected(relative)) continue;
		if (!validPath(relative)) throw new Error(`unsafe git source path: ${relative}`);
		if (candidates.has(relative)) throw new Error(`duplicate git source path: ${relative}`);
		candidates.add(relative);
	}
	for (const relative of mandatory) candidates.add(relative);
	for (const entry of nulFields(await git(["ls-files", "--stage", "-z"]), "git stage")) {
		const parsed = /^([0-7]{6}) [0-9a-f]+ ([0-3])\t([\s\S]+)$/.exec(entry);
		if (!parsed) throw new Error("malformed git stage output");
		const relative = parsed[3]!;
		const descendantSelected =
			[...mandatory].some((name) => name.startsWith(relative + "/")) ||
			(inputPolicy.mode === "include" && inputPolicy.prefixes.some((name) => name.startsWith(relative + "/")));
		if (
			parsed[1] === "160000" &&
			(selected(relative) || descendantSelected) &&
			!inputPolicy.structural.some((prefix) => prefixSelects(relative, prefix))
		)
			throw new Error(`selected gitlink: ${relative}`);
		if (!selected(relative)) continue;
		if (!validPath(relative)) throw new Error(`unsafe tracked path: ${relative}`);
		if (parsed[2] !== "0") throw new Error(`unmerged selected source: ${relative}`);
	}
	const status = nulFields(await git(["status", "--porcelain", "--untracked-files=all", "-z"]), "git status");
	let clean = true;
	for (let i = 0; i < status.length; i++) {
		const entry = status[i]!;
		if (entry.length < 4 || entry[2] !== " ") throw new Error("malformed git status output");
		const paths = [entry.slice(3)];
		if (/[RC]/.test(entry.slice(0, 2))) {
			const previous = status[++i];
			if (!previous) throw new Error("missing git rename source");
			paths.push(previous);
		}
		for (const relative of paths)
			if (selected(relative)) {
				if (!validPath(relative)) throw new Error(`unsafe changed source path: ${relative}`);
				clean = false;
			}
	}
	const aliases = new Map<string, string>();
	const files: SourceFile[] = [];
	for (const relative of orderVerifiedInputs([...candidates]))
		files.push(await hashSource(realRoot, relative, aliases, signal));
	const byPath = new Map(files.map((f) => [f.path, f]));
	const expected = [
		...loaded.common.definition_files,
		{ path: loaded.policy.intent_path, hash: loaded.common.intent_hash },
		{ path: loaded.policy.manifest_path, hash: loaded.common.manifest_hash },
	];
	if (loaded.common.dispatch_hash !== null)
		expected.push({ path: ".fv/dispatch.json", hash: loaded.common.dispatch_hash });
	for (const binding of expected)
		if (byPath.get(binding.path)?.hash !== binding.hash) throw new Error(`common binding moved: ${binding.path}`);
	if (D("policy", parseJSON(await fs.readFile(await safeSourcePath(realRoot, loaded.path)))) !== loaded.hash)
		throw new Error("reviewed policy moved");
	const verifiedFile = byPath.get(loaded.policy.verified_inputs);
	if (verifiedFile && verifiedFile.hash !== verifiedPolicyHash)
		throw new Error("verified-input policy moved during capture");
	if (loaded.common.dispatch_hash === null) {
		try {
			await fs.lstat(path.join(realRoot, ".fv/dispatch.json"));
			throw new Error("dispatch configuration appeared after policy load");
		} catch (error) {
			if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
		}
	}
	for (const recipe of loaded.policy.recipes) {
		for (const basis of recipe.source_closure.basis)
			if (!byPath.has(basis)) throw new Error(`uncovered closure basis: ${basis}`);
		for (const prefix of recipe.source_closure.prefixes) {
			if (!files.some((file) => prefixSelects(file.path, prefix)))
				throw new Error(`missing/uncovered closure prefix: ${prefix}`);
			const relative = prefix.endsWith("/") ? prefix.slice(0, -1) : prefix;
			let current = realRoot;
			for (const component of relative.split("/")) {
				current = path.join(current, component);
				const stat = await fs.lstat(current);
				if (stat.isSymbolicLink()) throw new Error(`symlink closure prefix: ${prefix}`);
			}
		}
	}
	const snapshot = createHash("sha256");
	for (const file of files) snapshot.update(file.path, "utf8").update("\0").update(file.hash.slice(7)).update("\n");
	return {
		verified_inputs_policy_hash: verifiedPolicyHash,
		inventory_hash: D(
			"inventory",
			files.map(({ path, executable }) => ({ path, executable })),
		),
		source_snapshot: `sha256:${snapshot.digest("hex")}`,
		clean,
		files,
	};
}
export function sameInputState(a: InputState, b: InputState): boolean {
	return a.clean && b.clean && H(C(a)) === H(C(b));
}
export function sourceClosure(input: InputState, recipe: Recipe, commonPaths: readonly string[]): Closure {
	const { basis } = recipe.source_closure;
	const mode = recipe.source_closure.mode === "prefixes" && basis.length ? "prefixes" : "verified-inputs";
	const prefixes = mode === "prefixes" ? [...recipe.source_closure.prefixes] : [];
	const mandatory = new Set([...commonPaths, ...basis, ...(recipe.build_cache?.configuration ?? [])]);
	const files =
		mode === "verified-inputs"
			? [...input.files]
			: input.files.filter(
					(file) => mandatory.has(file.path) || prefixes.some((prefix) => prefixSelects(file.path, prefix)),
				);
	for (const relative of mandatory)
		if (!files.some((file) => file.path === relative)) throw new Error(`missing closure binding: ${relative}`);
	const value = { mode, prefixes, basis: [...basis], files };
	return { ...value, hash: D("source-closure", value) };
}
export function buildEnvironment(
	policy: Policy,
	ambient: NodeJS.ProcessEnv | Record<string, string | undefined> = process.env,
): SanitizedEnvironment {
	const env: Record<string, string> = Object.create(null);
	const names = [...new Set([...policy.environment.inherit, ...Object.keys(policy.environment.set)])].sort(utf8Compare);
	if (H(C(names)) !== H(C(policy.environment.identity)))
		throw new Error("environment identity differs from semantic union");
	if (names.includes("DOSSIER_QUINT_OWNERSHIP_FDS"))
		throw new Error("reserved ownership variable cannot be semantic environment");
	for (const name of policy.environment.inherit) if (ambient[name] !== undefined) env[name] = ambient[name]!;
	for (const [name, value] of Object.entries(policy.environment.set)) env[name] = value;
	for (const [name, value] of Object.entries(env)) {
		if (value.includes("\0")) throw new Error(`NUL environment value: ${name}`);
		C(value);
	}
	const platform = { os: os.platform(), arch: os.arch(), release: os.release() };
	if (!policy.environment.platforms.some((p) => p.os === platform.os && p.arch === platform.arch))
		throw new Error(`unsupported producer platform: ${platform.os}/${platform.arch}`);
	return {
		env,
		identity: {
			...platform,
			variables: names.map((name) => ({
				name,
				present: Object.hasOwn(env, name),
				value_hash: Object.hasOwn(env, name) ? H(Buffer.from(env[name]!, "utf8")) : null,
			})),
		},
	};
}
export function validateEnvironmentBinding(policy: Policy, identity: EnvironmentIdentity): EnvironmentIdentity {
	validateEnvironmentIdentity(identity);
	if (!policy.environment.platforms.some((platform) => platform.os === identity.os && platform.arch === identity.arch))
		throw new Error("environment platform is not reviewed");
	if (H(C(identity.variables.map((variable) => variable.name))) !== H(C(policy.environment.identity)))
		throw new Error("environment variable set differs from policy");
	const variables = new Map(identity.variables.map((variable) => [variable.name, variable]));
	for (const [name, value] of Object.entries(policy.environment.set)) {
		const variable = variables.get(name);
		if (!variable?.present || variable.value_hash !== H(Buffer.from(value, "utf8")))
			throw new Error(`environment literal hash mismatch: ${name}`);
	}
	return identity;
}
export function materializeDescriptor(options: {
	loaded: LoadedPolicy;
	input: InputState;
	recipe: Recipe;
	distinct: DistinctSlot | null;
	environment: EnvironmentIdentity;
	toolchains: ToolIdentity[];
	buildCache: BuildCacheIdentity;
}): ExecutionDescriptor {
	const { loaded, input, recipe, distinct, environment, toolchains, buildCache } = options;
	const expansion = expandPolicy(loaded.policy).executions.find(
		(e) => e.recipe.recipe_id === recipe.recipe_id && H(C(e.distinct)) === H(C(distinct)),
	);
	if (!expansion || H(C(expansion.recipe)) !== H(C(recipe)))
		throw new Error("descriptor recipe/distinct slot is not reviewed expansion");
	if (!input.clean) throw new Error("dirty source cannot materialize reusable descriptor");
	const declarations = new Map(loaded.policy.toolchains.map((t) => [t.id, t]));
	const ids = new Set<string>(["fv-producer"]);
	function include(id: string): void {
		if (ids.has(id)) return;
		const declaration = declarations.get(id);
		if (!declaration) throw new Error(`unknown descriptor tool ${id}`);
		ids.add(id);
		declaration.requires.forEach(include);
	}
	recipe.toolchain.forEach(include);
	const identities = new Map(toolchains.map((t) => [t.id, t]));
	if (identities.size !== toolchains.length) throw new Error("duplicate available tool identity");
	const toolchain = [...ids].sort(utf8Compare).map((id) => {
		const identity = identities.get(id);
		if (!identity) throw new Error(`missing descriptor tool identity: ${id}`);
		return identity;
	});
	if (
		(recipe.build_cache === null) !== (buildCache === null) ||
		(recipe.build_cache && buildCache?.system !== recipe.build_cache.system)
	)
		throw new Error("descriptor build-cache selection mismatch");
	if (buildCache !== null) {
		const files = new Map(input.files.map((file) => [file.path, file.hash]));
		const configuration = recipe.build_cache!.configuration.map((path) => ({ path, hash: files.get(path) }));
		if (configuration.some((file) => file.hash === undefined) || H(C(configuration)) !== H(C(buildCache.configuration)))
			throw new Error("build-cache configuration binding mismatch");
	}
	validateEnvironmentBinding(loaded.policy, environment);
	for (const identity of toolchain) {
		if (
			identity.system_dependencies.os !== environment.os ||
			identity.system_dependencies.arch !== environment.arch ||
			identity.system_dependencies.release !== environment.release
		)
			throw new Error(`tool platform differs from environment: ${identity.id}`);
		if (identity.id === "fv-producer") continue;
		const declaration = declarations.get(identity.id)!;
		if (
			identity.kind !== declaration.kind ||
			H(C(identity.locator)) !== H(C(declaration.locator)) ||
			H(C(identity.requires)) !== H(C(declaration.requires))
		)
			throw new Error(`tool identity differs from declaration: ${identity.id}`);
		if ((declaration.version_command === null) !== (identity.version === null))
			throw new Error(`tool version missing/unexpected: ${identity.id}`);
		if (
			identity.version &&
			(H(C(identity.version.command)) !== H(C(declaration.version_command)) ||
				identity.version.cwd !== declaration.version_cwd ||
				declaration.accept.version_contains.some((text) => !identity.version!.text.includes(text)))
		)
			throw new Error(`tool version binding mismatch: ${identity.id}`);
		if (declaration.accept.sha256.length && !declaration.accept.sha256.includes(identity.digest))
			throw new Error(`tool digest not accepted: ${identity.id}`);
	}
	return validateExecutionDescriptor({
		schema_version: "fv-execution-descriptor/v1",
		common: loaded.common,
		recipe,
		members: expansion.members.map((member) => ({ ...member })),
		distinct_slot: distinct,
		verified_inputs_policy_hash: input.verified_inputs_policy_hash,
		inventory_hash: input.inventory_hash,
		closure: sourceClosure(input, recipe, commonBindingPaths(loaded)),
		environment,
		toolchain,
		build_cache: buildCache,
	});
}
export function descriptorKeys(descriptor: ExecutionDescriptor): { common_key: string; execution_key: string } {
	return { common_key: D("common-bindings", descriptor.common), execution_key: D("execution-key", descriptor) };
}
