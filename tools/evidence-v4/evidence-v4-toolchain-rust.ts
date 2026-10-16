import * as fs from "node:fs/promises";
import * as path from "node:path";
import { D, H, parseJSON, utf8Compare } from "./evidence-v4-model";
import type { PackageIdentity, ToolDiscovery } from "./evidence-v4-model";
import type { AdapterContext, AdapterResult, CacheNamespaceSelection, ToolRoot } from "./evidence-v4-toolchain-common";
import { canonicalToolPath, probeText } from "./evidence-v4-toolchain-common";

type Table = { [key: string]: Value };
type Value = string | number | boolean | Value[] | Table;
const UTF8 = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true });
async function readText(filename: string): Promise<string> {
	const bytes = await fs.readFile(filename);
	return UTF8.decode(bytes);
}

function fail(message: string): never {
	throw new Error(`Rust toolchain attestation: ${message}`);
}
function table(value: Value | undefined): Table {
	return value && typeof value === "object" && !Array.isArray(value) ? value : Object.create(null);
}
function string(value: Value | undefined, name: string): string | undefined {
	if (value === undefined) return undefined;
	if (typeof value !== "string") fail(`${name} must be a string`);
	return value;
}

// Cargo accepts TOML, including dotted keys, arrays and inline tables. Unsupported
// value types fail before any subject command can be dispatched.
export function parseCargoTOML(text: string): Table {
	let i = 0;
	const root: Table = Object.create(null);
	let current = root;
	const explicit = new Set<string>();
	function error(): never {
		return fail(`unsupported or malformed TOML at offset ${i}`);
	}
	function spaces(newlines = true): void {
		while (i < text.length) {
			if (text[i] === " " || text[i] === "\t" || (newlines && (text[i] === "\r" || text[i] === "\n"))) {
				i++;
				continue;
			}
			if (newlines && text[i] === "#") {
				while (i < text.length && text[i] !== "\n") i++;
				continue;
			}
			break;
		}
	}
	function quoted(): string {
		const quote = text[i++];
		const multiline = text.slice(i, i + 2) === quote + quote;
		if (multiline) {
			i += 2;
			if (text[i] === "\r") i++;
			if (text[i] === "\n") i++;
		}
		let out = "";
		while (i < text.length) {
			if (text[i] === quote && (!multiline || text.slice(i, i + 3) === quote.repeat(3))) {
				i += multiline ? 3 : 1;
				return out;
			}
			const ch = text[i++];
			if (!multiline && (ch === "\n" || ch === "\r")) error();
			if (ch.charCodeAt(0) < 32 && !["\n", "\r", "\t"].includes(ch)) error();
			if (quote === '"' && ch === "\\") {
				const escape = text[i++];
				const simple: Record<string, string> = { b: "\b", t: "\t", n: "\n", f: "\f", r: "\r", '"': '"', "\\": "\\" };
				if (Object.hasOwn(simple, escape)) out += simple[escape];
				else if (escape === "u" || escape === "U") {
					const n = escape === "u" ? 4 : 8;
					const hex = text.slice(i, i + n);
					if (!new RegExp(`^[0-9a-fA-F]{${n}}$`).test(hex)) error();
					i += n;
					const code = Number.parseInt(hex, 16);
					if (code > 0x10ffff || (code >= 0xd800 && code <= 0xdfff)) error();
					out += String.fromCodePoint(code);
				} else if (multiline && /[ \t\r\n]/.test(escape)) {
					while (/[ \t\r\n]/.test(text[i] ?? "x")) i++;
				} else error();
			} else out += ch;
		}
		return error();
	}
	function keys(): string[] {
		const result: string[] = [];
		while (true) {
			spaces(false);
			if (text[i] === '"' || text[i] === "'") result.push(quoted());
			else {
				const match = /^[A-Za-z0-9_-]+/.exec(text.slice(i));
				if (!match) error();
				result.push(match[0]);
				i += match[0].length;
			}
			spaces(false);
			if (text[i] !== ".") return result;
			i++;
		}
	}
	function parent(target: Table, names: string[]): Table {
		for (const name of names) {
			if (!Object.hasOwn(target, name)) target[name] = Object.create(null);
			let next = target[name];
			if (Array.isArray(next)) next = next[next.length - 1];
			if (!next || typeof next !== "object" || Array.isArray(next)) error();
			target = next;
		}
		return target;
	}
	function assign(target: Table, names: string[], value: Value): void {
		const leaf = names.pop()!;
		target = parent(target, names);
		if (Object.hasOwn(target, leaf)) error();
		target[leaf] = value;
	}
	function value(): Value {
		spaces();
		if (text[i] === '"' || text[i] === "'") return quoted();
		if (text[i] === "[") {
			i++;
			const array: Value[] = [];
			spaces();
			while (text[i] !== "]") {
				array.push(value());
				spaces();
				if (text[i] === ",") {
					i++;
					spaces();
				} else if (text[i] !== "]") error();
			}
			i++;
			return array;
		}
		if (text[i] === "{") {
			i++;
			const result: Table = Object.create(null);
			spaces(false);
			while (text[i] !== "}") {
				const names = keys();
				if (text[i++] !== "=") error();
				assign(result, names, value());
				spaces(false);
				if (text[i] === ",") {
					i++;
					spaces(false);
					if (text[i] === "}") error();
				} else if (text[i] !== "}") error();
			}
			i++;
			return result;
		}
		const match = /^[^\s,#\]}]+/.exec(text.slice(i));
		if (!match) error();
		i += match[0].length;
		if (match[0] === "true") return true;
		if (match[0] === "false") return false;
		if (!/^[+-]?(?:0|[1-9](?:_?[0-9])*)$/.test(match[0])) error();
		const number = Number(match[0].replaceAll("_", ""));
		if (!Number.isSafeInteger(number)) error();
		return number;
	}
	while (true) {
		spaces();
		if (i === text.length) return root;
		if (text[i] === "[") {
			i++;
			const array = text[i] === "[";
			if (array) i++;
			const names = keys();
			if (text[i++] !== "]" || (array && text[i++] !== "]")) error();
			const key = JSON.stringify(names);
			if (array) {
				const leaf = names.pop()!;
				const target = parent(root, names);
				if (!Object.hasOwn(target, leaf)) target[leaf] = [];
				if (!Array.isArray(target[leaf])) error();
				current = Object.create(null);
				(target[leaf] as Value[]).push(current);
			} else {
				if (explicit.has(key)) error();
				explicit.add(key);
				current = parent(root, names);
			}
		} else {
			const names = keys();
			if (text[i++] !== "=") error();
			assign(current, names, value());
		}
		spaces(false);
		if (text[i] === "#") {
			while (i < text.length && text[i] !== "\n") i++;
		}
		if (i < text.length && text[i] !== "\r" && text[i] !== "\n") error();
	}
}

async function exists(filename: string): Promise<boolean> {
	try {
		await fs.lstat(filename);
		return true;
	} catch (error) {
		if ((error as NodeJS.ErrnoException).code === "ENOENT") return false;
		throw error;
	}
}
async function requiredReal(filename: string): Promise<string> {
	try {
		return await canonicalToolPath(filename);
	} catch {
		return fail(`missing installed path ${filename}`);
	}
}
async function canonicalNamespace(filename: string): Promise<string> {
	const missing: string[] = [];
	let parent = path.resolve(filename);
	while (!(await exists(parent))) {
		missing.unshift(path.basename(parent));
		const next = path.dirname(parent);
		if (next === parent) fail("cannot canonicalize cache namespace");
		parent = next;
	}
	return path.join(await canonicalToolPath(parent), ...missing);
}
function beneath(root: string, filename: string): boolean {
	const rel = path.relative(root, filename);
	return rel === "" || (!rel.startsWith(`..${path.sep}`) && rel !== ".." && !path.isAbsolute(rel));
}
function merge(base: Table, overlay: Table): Table {
	for (const [key, value] of Object.entries(overlay)) {
		const previous = base[key];
		if (Array.isArray(value) && Array.isArray(previous)) base[key] = [...previous, ...value];
		else if (value && typeof value === "object" && !Array.isArray(value)) base[key] = merge(table(previous), value);
		else base[key] = value;
	}
	return base;
}

type Selection = {
	entry: string;
	toolchain?: string;
	operation?: string;
	packages: string[];
	features: string[];
	allFeatures: boolean;
	noDefaultFeatures: boolean;
	workspace: boolean;
	excludes: string[];
	manifest?: string;
	target?: string;
	targetDir?: string;
	profile: string;
	config: string[];
	configArgs: string[];
	selectors: string[];
	solver?: string;
	runtimeOnly: boolean;
};
function selection(subject: readonly string[]): Selection {
	if (!subject.length || !["cargo", "rustc"].includes(path.basename(subject[0])))
		fail("unsupported Cargo/Rust subject entry");
	const result: Selection = {
		entry: subject[0],
		packages: [],
		features: [],
		allFeatures: false,
		noDefaultFeatures: false,
		workspace: false,
		excludes: [],
		profile: "dev",
		config: [],
		configArgs: [],
		selectors: [],
		runtimeOnly: false,
	};
	let i = 1;
	if (subject[i]?.startsWith("+")) result.toolchain = subject[i++].slice(1);
	if (i === subject.length) {
		result.runtimeOnly = true;
		return result;
	}
	if (path.basename(result.entry) === "rustc") fail("rustc adapter only supports a runtime-only subject");
	result.operation = subject[i++];
	if (!["test", "build", "check", "run", "bench", "kani"].includes(result.operation))
		fail(`unsupported Cargo subject operation ${result.operation}`);
	if (result.operation === "test") result.profile = "test";
	if (result.operation === "bench") result.profile = "bench";
	for (; i < subject.length; i++) {
		const argument = subject[i];
		if (argument === "--") break;
		const equal = argument.indexOf("=");
		const flag = equal < 0 ? argument : argument.slice(0, equal);
		const next = (): string => {
			const value = equal < 0 ? subject[++i] : argument.slice(equal + 1);
			if (!value) fail(`missing ${flag} value`);
			return value;
		};
		switch (flag) {
			case "-p":
			case "--package":
				result.packages.push(next());
				break;
			case "--features":
			case "-F":
				result.features.push(next());
				break;
			case "--all-features":
				result.allFeatures = true;
				break;
			case "--no-default-features":
				result.noDefaultFeatures = true;
				break;
			case "--workspace":
				result.workspace = true;
				break;
			case "--exclude":
				result.excludes.push(next());
				break;
			case "--manifest-path":
				result.manifest = next();
				break;
			case "--target":
				if (result.target) fail("multiple Cargo targets need separate adapter contexts");
				result.target = next();
				break;
			case "--target-dir":
				result.targetDir = next();
				break;
			case "--profile":
				result.profile = next();
				break;
			case "--release":
				result.profile = "release";
				break;
			case "--config": {
				const value = next();
				result.config.push(value);
				result.configArgs.push("--config", value);
				break;
			}
			case "--solver":
				result.solver = next();
				break;
			case "--test":
			case "--bin":
			case "--example":
			case "--bench":
				result.selectors.push(flag, next());
				break;
			case "--harness":
			case "--unwind":
			case "--jobs":
			case "-j":
			case "--message-format":
				next();
				break;
			case "--lib":
			case "--tests":
			case "--bins":
			case "--examples":
			case "--benches":
			case "--all-targets":
				result.selectors.push(flag);
				break;
			case "--locked":
			case "--offline":
			case "--frozen":
			case "--quiet":
			case "-q":
			case "--verbose":
			case "-v":
			case "-vv":
			case "--exact":
			case "--nocapture":
				break;
			case "--cbmc-args":
			case "-Z":
				fail(`${flag} requires a reviewed closure-specific selector`);
			default:
				if (flag.startsWith("-")) fail(`unsupported Cargo subject selector ${flag}`);
				if (result.operation !== "test" && result.operation !== "bench")
					fail(`unexpected Cargo subject argument ${argument}`);
		}
	}
	return result;
}

type Configuration = { values: Table; roots: ToolRoot[]; bases: Map<string, string> };
async function configuration(context: AdapterContext, selected: Selection): Promise<Configuration> {
	for (const name of Object.keys(context.effectiveEnv))
		if (name.startsWith("CARGO_ALIAS_")) fail("Cargo alias environment is unsupported: " + name);
	const roots: ToolRoot[] = [];
	const bases = new Map<string, string>();
	const files: { filename: string; base: string; label: string }[] = [];
	const home =
		context.effectiveEnv.CARGO_HOME ||
		(context.effectiveEnv.HOME ? path.join(context.effectiveEnv.HOME, ".cargo") : undefined);
	async function addDirectory(directory: string, label: string): Promise<void> {
		const legacy = path.join(directory, "config");
		const modern = path.join(directory, "config.toml");
		const filename = (await exists(legacy)) ? legacy : (await exists(modern)) ? modern : undefined;
		if (filename) files.push({ filename, base: path.dirname(directory), label });
	}
	if (home) await addDirectory(path.resolve(context.cwd, home), "config/cargo-home");
	const ancestors: string[] = [];
	let ancestor = context.cwd;
	while (true) {
		ancestors.unshift(ancestor);
		const parent = path.dirname(ancestor);
		if (ancestor === parent) break;
		ancestor = parent;
	}
	for (let index = 0; index < ancestors.length; index++)
		await addDirectory(path.join(ancestors[index], ".cargo"), `config/ancestors/${index}`);
	let values: Table = Object.create(null);
	function noteBase(value: Table, base: string, prefix = ""): void {
		for (const [key, child] of Object.entries(value)) {
			const name = prefix ? `${prefix}.${key}` : key;
			if (child && typeof child === "object" && !Array.isArray(child)) noteBase(child, base, name);
			else bases.set(name, base);
		}
	}
	const seen = new Set<string>();
	for (const file of files) {
		const real = await requiredReal(file.filename);
		if (seen.has(real)) continue;
		seen.add(real);
		const value = parseCargoTOML(await readText(real));
		if (value.alias !== undefined) fail("Cargo alias configuration is unsupported");
		if (value.include !== undefined) fail("Cargo config include needs an explicit supported selection");
		merge(values, value);
		noteBase(value, file.base);
		roots.push({ label: file.label, path: real });
	}
	for (let index = 0; index < selected.config.length; index++) {
		const argument = selected.config[index];
		let value: Table;
		let base: string;
		if (argument.includes("=")) {
			value = parseCargoTOML(argument);
			base = context.cwd;
		} else {
			const filename = await requiredReal(path.resolve(context.cwd, argument));
			value = parseCargoTOML(await readText(filename));
			base = path.dirname(path.dirname(filename));
			roots.push({ label: `config/command/${index}`, path: filename });
		}
		if (value.alias !== undefined) fail("Cargo alias configuration is unsupported");
		if (value.include !== undefined) fail("Cargo config include needs an explicit supported selection");
		merge(values, value);
		noteBase(value, base);
	}
	// Cargo's config [env] alters the command environment. Attesting the outer
	// environment alone cannot establish that inner selection.
	if (Object.keys(table(values.env)).length)
		fail("Cargo [env] requires an incorporated effective-environment contract");
	if (Object.keys(table(values.unstable)).length) fail("unstable Cargo configuration is unsupported");
	return { values, roots, bases };
}
function configuredPath(context: AdapterContext, config: Configuration, key: string, value: string): string {
	const base = config.bases.get(key) || context.cwd;
	return path.resolve(base, value);
}

async function rustupSelection(
	context: AdapterContext,
	selected: Selection,
	roots: ToolRoot[],
	discovery: ToolDiscovery[],
): Promise<RustRuntime> {
	const entry = await context.resolveCommand(selected.entry);
	const build = path.basename(entry.realpath) === "rustup";
	let cargo: string;
	let rustc: string;
	const probe = async (command: string[]) => {
		const result = await context.probe(command);
		discovery.push(result.identity);
		return probeText(result).trim();
	};
	if (build) {
		const home =
			context.effectiveEnv.RUSTUP_HOME ||
			(context.effectiveEnv.HOME && path.join(context.effectiveEnv.HOME, ".rustup"));
		if (!home) fail("rustup requires a declared HOME or RUSTUP_HOME");
		const settingsFile = path.join(path.resolve(context.cwd, home), "settings.toml");
		const settings = parseCargoTOML(await readText(settingsFile));
		roots.push({ label: "config/rustup-settings", path: settingsFile });
		let named = selected.toolchain || context.effectiveEnv.RUSTUP_TOOLCHAIN;
		if (!named) {
			let dir = context.cwd;
			const overrides = table(settings.overrides);
			while (true) {
				const override = string(overrides[dir], "rustup override");
				const plain = path.join(dir, "rust-toolchain");
				const toml = path.join(dir, "rust-toolchain.toml");
				if (override) {
					named = override;
					break;
				}
				if ((await exists(plain)) || (await exists(toml))) {
					const filename = (await exists(plain)) ? plain : toml;
					const bytes = await readText(filename);
					if (filename === plain && /^[A-Za-z0-9._-]+$/.test(bytes.trim())) named = bytes.trim();
					else {
						const value = parseCargoTOML(bytes);
						const toolchain = table(value.toolchain);
						if (
							Object.keys(value).some((key) => key !== "toolchain") ||
							Object.keys(toolchain).some((key) => key !== "channel")
						)
							fail("unsupported rust-toolchain file key");
						named = string(toolchain.channel, "rust-toolchain channel");
					}
					if (!named) fail("rust-toolchain file requires a channel");
					roots.push({ label: "config/rust-toolchain", path: filename });
					break;
				}
				const parent = path.dirname(dir);
				if (parent === dir) break;
				dir = parent;
			}
			named ||= string(settings.default_toolchain, "rustup default toolchain");
		}
		if (!named || !/^[A-Za-z0-9._-]+$/.test(named)) fail("unsupported rustup toolchain name");
		const directory = path.join(path.resolve(context.cwd, home), "toolchains");
		const installed = await fs.readdir(directory);
		const matches = installed.filter((name) => name === named || name.startsWith(`${named}-`));
		if (!matches.length) fail(`selected rustup toolchain ${named} is not installed`);
		// `which` never installs. The installed-path check also precedes all shim probes.
		cargo = await probe([entry.realpath, "which", "--toolchain", named, "cargo"]);
		rustc = await probe([entry.realpath, "which", "--toolchain", named, "rustc"]);
		roots.push({ label: "config/rustup-dispatch", path: entry.realpath });
	} else {
		if (selected.toolchain) fail("+toolchain requires a rustup entry");
		if (path.basename(selected.entry) === "cargo") {
			cargo = entry.realpath;
			rustc = (await context.resolveCommand("rustc")).realpath;
		} else {
			rustc = entry.realpath;
			cargo = (await context.resolveCommand("cargo")).realpath;
		}
	}
	cargo = await requiredReal(cargo);
	rustc = await requiredReal(rustc);
	const sysroot = await requiredReal(await probe([rustc, "--print", "sysroot"]));
	const version = await probe([rustc, "-vV"]);
	const host = /^host: (.+)$/m.exec(version)?.[1];
	if (!host) fail("rustc did not identify its host");
	await probe([cargo, "-V"]);
	return { cargo, rustc, sysroot, host, nativeExecutables: build ? [cargo, entry.realpath] : [cargo] };
}

type MetadataPackage = {
	id: string;
	name: string;
	version: string;
	source: string | null;
	manifest_path: string;
	targets: { kind: string[]; src_path: string }[];
	links: string | null;
	dependencies: { name: string; kind: string | null }[];
	attestationBuildDependencies?: string[];
	attestationFeatures?: string[];
	attestationDependencies?: string[];
	attestationHost?: boolean;
};
type Metadata = {
	packages: MetadataPackage[];
	workspace_root: string;
	target_directory: string;
	workspace_members: string[];
	workspace_default_members: string[];
	resolve: {
		root: string | null;
		nodes?: { id: string; deps: { pkg: string; dep_kinds: { kind: string | null }[] }[] }[];
	} | null;
};
function metadata(bytes: Buffer): Metadata {
	const value = parseJSON(bytes) as Metadata;
	if (
		!value ||
		typeof value !== "object" ||
		!Array.isArray(value.packages) ||
		typeof value.workspace_root !== "string" ||
		typeof value.target_directory !== "string"
	)
		fail("invalid Cargo metadata");
	for (const pkg of value.packages)
		if (
			![pkg.id, pkg.name, pkg.version, pkg.manifest_path].every((x) => typeof x === "string" && x.length) ||
			!Array.isArray(pkg.targets) ||
			!Array.isArray(pkg.dependencies)
		)
			fail("invalid Cargo package metadata");
	return value;
}
function featureArgs(selected: Selection): string[] {
	const result: string[] = [];
	for (const features of selected.features) result.push("--features", features);
	if (selected.allFeatures) result.push("--all-features");
	if (selected.noDefaultFeatures) result.push("--no-default-features");
	return result;
}
function matchDisplay(display: string, packages: ReadonlyMap<string, MetadataPackage[]>): MetadataPackage {
	const match = /^([^ ]+) v([^ ]+)(.*)$/.exec(display);
	if (!match) fail(`unrecognized Cargo tree package ${display}`);
	const procMacroMarker = " (proc-macro)";
	let qualifiers = match[3];
	let procMacro = false;
	if (qualifiers.startsWith(procMacroMarker)) {
		procMacro = true;
		qualifiers = qualifiers.slice(procMacroMarker.length);
	} else if (qualifiers.endsWith(procMacroMarker)) {
		procMacro = true;
		qualifiers = qualifiers.slice(0, -procMacroMarker.length);
	}
	const sourceQualifier = /^(?: \((.*)\))?$/.exec(qualifiers);
	if (!sourceQualifier) fail(`unrecognized Cargo tree qualifiers for ${display}`);
	let candidates = (packages.get(`${match[1]}\0${match[2]}`) || []).filter(
		(pkg) => pkg.targets.some((target) => target.kind.includes("proc-macro")) === procMacro,
	);
	const location = sourceQualifier[1];
	if (location)
		candidates = candidates.filter((pkg) => {
			if (pkg.source === null) return path.dirname(pkg.manifest_path) === location;
			const source = pkg.source.replace(/^(?:registry|sparse|git)\+/, "");
			if (source === location) return true;
			const hash = source.lastIndexOf("#");
			const displayedHash = location.lastIndexOf("#");
			return (
				hash >= 0 &&
				displayedHash >= 0 &&
				source.slice(0, hash) === location.slice(0, displayedHash) &&
				source.slice(hash + 1).startsWith(location.slice(displayedHash + 1))
			);
		});
	else
		candidates = candidates.filter((pkg) => pkg.source?.startsWith("registry+") || pkg.source?.startsWith("sparse+"));
	if (candidates.length !== 1) fail(`ambiguous Cargo source for ${display}`);
	return candidates[0];
}
async function packageIdentity(
	context: AdapterContext,
	pkg: MetadataPackage,
	lock: ReadonlyMap<string, Table[]>,
): Promise<PackageIdentity> {
	const matches = lock.get(`${pkg.name}\0${pkg.version}\0${pkg.source ?? ""}`) || [];
	if (matches.length !== 1) fail(`metadata/lock disagreement for ${pkg.name} ${pkg.version}`);
	const locked = matches[0];
	if (pkg.source === null) {
		const directory = path.dirname(pkg.manifest_path);
		const real = await requiredReal(directory);
		const root = await requiredReal(context.root);
		if (path.resolve(directory) !== real || !beneath(root, real))
			fail(`symlinked or external path package ${pkg.name} requires an incorporated source closure`);
		return {
			name: pkg.name,
			version: pkg.version,
			source: { kind: "path", path: path.relative(root, real).split(path.sep).join("/") || "." },
		};
	}
	if (pkg.source.startsWith("registry+") || pkg.source.startsWith("sparse+")) {
		const checksum = string(locked.checksum, "Cargo package checksum");
		if (!checksum || !/^[0-9a-f]{64}$/.test(checksum)) fail(`missing registry checksum for ${pkg.name}`);
		return { name: pkg.name, version: pkg.version, source: { kind: "registry", id: pkg.source, checksum } };
	}
	if (pkg.source.startsWith("git+")) {
		const revision = pkg.source.slice(pkg.source.lastIndexOf("#") + 1);
		if (!/^(?:[0-9a-f]{40}|[0-9a-f]{64})$/.test(revision)) fail(`unresolved Git revision for ${pkg.name}`);
		return { name: pkg.name, version: pkg.version, source: { kind: "git", id: pkg.source, revision } };
	}
	return fail(`unsupported Cargo source ${pkg.source}`);
}

async function applicationGraph(
	context: AdapterContext,
	selected: Selection,
	cargo: string,
	env: Record<string, string>,
	target: string,
	roots: ToolRoot[],
	discovery: ToolDiscovery[],
): Promise<{ packages: PackageIdentity[]; selectedPackages: MetadataPackage[]; metadata: Metadata }> {
	if (selected.targetDir) env = { ...env, CARGO_TARGET_DIR: path.resolve(context.cwd, selected.targetDir) };
	const probe = async (args: string[]) => {
		const result = await context.probe([cargo, ...args], { env });
		discovery.push(result.identity);
		return result.stdout;
	};
	const base = ["--offline", "--locked", ...selected.configArgs];
	const manifestArgs = selected.manifest ? ["--manifest-path", path.resolve(context.cwd, selected.manifest)] : [];
	const checkedManifests = new Set<string>();
	async function checkManifest(filename: string): Promise<void> {
		const real = await requiredReal(filename);
		if (checkedManifests.has(real)) return;
		const manifest = parseCargoTOML(await readText(real));
		if (manifest["cargo-features"] !== undefined) fail("manifest cargo-features is unsupported: " + filename);
		for (const scope of ["package", "workspace"])
			if (table(table(manifest[scope]).metadata).kani !== undefined)
				fail("Kani package/workspace metadata overrides are unsupported: " + filename);
		if (selected.operation === "kani")
			for (const [key, value] of Object.entries(table(manifest.target)))
				if (
					/^\s*cfg\s*\(/.test(key) &&
					/\bkani\b/.test(key) &&
					["dependencies", "dev-dependencies", "build-dependencies"].some((kind) => Object.hasOwn(table(value), kind))
				)
					fail("cfg(kani)-selected dependency tables are unsupported: " + filename);
		checkedManifests.add(real);
	}
	if (selected.manifest) await checkManifest(path.resolve(context.cwd, selected.manifest));
	else {
		let directory = context.cwd;
		while (true) {
			const filename = path.join(directory, "Cargo.toml");
			if (await exists(filename)) {
				await checkManifest(filename);
				break;
			}
			const parent = path.dirname(directory);
			if (parent === directory) break;
			directory = parent;
		}
	}
	const first = metadata(await probe(["metadata", "--format-version", "1", "--no-deps", ...base, ...manifestArgs]));
	const workspace = await requiredReal(first.workspace_root);
	if (!beneath(await requiredReal(context.root), workspace)) fail("workspace escapes project source closure");
	await checkManifest(path.join(workspace, "Cargo.toml"));
	for (const pkg of first.packages) await checkManifest(pkg.manifest_path);
	const onePackage =
		selected.packages.length === 1
			? first.packages.filter(
					(pkg) => pkg.name === selected.packages[0] || `${pkg.name}@${pkg.version}` === selected.packages[0],
				)
			: [];
	const metadataManifest = onePackage.length === 1 ? ["--manifest-path", onePackage[0].manifest_path] : manifestArgs;
	const full = metadata(
		await probe([
			"metadata",
			"--format-version",
			"1",
			"--filter-platform",
			target,
			...base,
			...metadataManifest,
			...featureArgs(selected),
		]),
	);
	for (const pkg of full.packages) await checkManifest(pkg.manifest_path);
	const lockfile = path.join(workspace, "Cargo.lock");
	const lock = parseCargoTOML(await readText(lockfile)).package;
	if (!Array.isArray(lock)) fail("Cargo.lock lacks package entries");
	const lockedPackages = new Map<string, Table[]>();
	for (const value of lock) {
		const entry = table(value);
		const key = `${entry.name}\0${entry.version}\0${entry.source ?? ""}`;
		const entries = lockedPackages.get(key);
		if (entries) entries.push(entry);
		else lockedPackages.set(key, [entry]);
	}
	const metadataPackages = new Map<string, MetadataPackage[]>();
	for (const pkg of full.packages) {
		const key = `${pkg.name}\0${pkg.version}`;
		const entries = metadataPackages.get(key);
		if (entries) entries.push(pkg);
		else metadataPackages.set(key, [pkg]);
	}
	roots.push(
		{ label: "config/Cargo.lock", path: lockfile },
		{ label: "config/Cargo.toml", path: path.join(workspace, "Cargo.toml") },
	);
	const treeArgs = [
		"tree",
		...base,
		...manifestArgs,
		...featureArgs(selected),
		"--target",
		target,
		"--prefix",
		"none",
		"--format",
		"{p}|{f}",
		"--charset",
		"ascii",
		"--edges",
		selected.operation === "test" ||
		selected.operation === "bench" ||
		selected.selectors.some((x) =>
			["--test", "--example", "--bench", "--tests", "--examples", "--benches", "--all-targets"].includes(x),
		)
			? "normal,build,dev"
			: "normal,build",
	];
	for (const pkg of selected.packages) treeArgs.push("--package", pkg);
	if (selected.workspace) treeArgs.push("--workspace");
	for (const pkg of selected.excludes) treeArgs.push("--exclude", pkg);
	const output = UTF8.decode(await probe(treeArgs));
	const graph = new Map<string, MetadataPackage>();
	for (const line of output.split(/\r?\n/)) {
		if (!line.trim()) continue;
		const separator = line.indexOf("|");
		if (separator < 0) fail("unexpected Cargo tree output");
		const display = line.slice(0, separator).trim();
		const pkg = matchDisplay(display, metadataPackages);
		const features = line
			.slice(separator + 1)
			.replace(/ \(\*\)$/, "")
			.trim()
			.split(",")
			.filter(Boolean);
		pkg.attestationFeatures = [...new Set([...(pkg.attestationFeatures || []), ...features])].sort(utf8Compare);
		graph.set(pkg.id, pkg);
	}
	if (!graph.size) fail("empty selected Cargo application graph");
	const resolvedNodes = new Map((full.resolve?.nodes || []).map((node) => [node.id, node]));
	for (const pkg of graph.values()) {
		const node = resolvedNodes.get(pkg.id);
		pkg.attestationBuildDependencies = (node?.deps || [])
			.filter((dependency) => graph.has(dependency.pkg) && dependency.dep_kinds.some((kind) => kind.kind === "build"))
			.map((dependency) => dependency.pkg);
		if (node)
			pkg.attestationDependencies = node.deps
				.filter((dependency) => graph.has(dependency.pkg) && dependency.dep_kinds.some((kind) => kind.kind === null))
				.map((dependency) => dependency.pkg)
				.sort(utf8Compare);
	}
	const hostPackages = new Set<string>();
	for (const pkg of graph.values()) {
		if (pkg.targets.some((item) => item.kind.includes("proc-macro"))) hostPackages.add(pkg.id);
		for (const dependency of resolvedNodes.get(pkg.id)?.deps || [])
			if (graph.has(dependency.pkg) && dependency.dep_kinds.some((kind) => kind.kind === "build"))
				hostPackages.add(dependency.pkg);
	}
	for (const id of hostPackages)
		for (const dependency of resolvedNodes.get(id)?.deps || [])
			if (graph.has(dependency.pkg) && dependency.dep_kinds.some((kind) => kind.kind === null || kind.kind === "build"))
				hostPackages.add(dependency.pkg);
	for (const id of hostPackages) graph.get(id)!.attestationHost = true;
	const packages: PackageIdentity[] = [];
	const packageDigests = new Map<PackageIdentity, string>();
	const targetDirectory = path.resolve(full.target_directory);
	for (const pkg of graph.values()) {
		const identity = await packageIdentity(context, pkg, lockedPackages);
		packages.push(identity);
		const digest = D("cargo-package", identity).replace(/^sha256:/, "");
		packageDigests.set(identity, digest);
		const directory = await requiredReal(path.dirname(pkg.manifest_path));
		const exclude = [".git", ".cargo-ok"];
		if (beneath(directory, targetDirectory))
			exclude.push(path.relative(directory, targetDirectory).split(path.sep).join("/"));
		if (identity.source.kind === "path")
			exclude.push(".fv/evidence", ".fv/verify", ".fv/history", ".fv/.migrate-staging", ".colosseum");
		roots.push({ label: `packages/${digest}`, path: directory, exclude });
		// Git packages can inherit workspace configuration outside the crate directory.
		if (identity.source.kind === "git") {
			let parent = directory;
			let index = 0;
			while (true) {
				const manifest = path.join(parent, "Cargo.toml");
				if (parent !== directory && (await exists(manifest))) {
					await checkManifest(manifest);
					roots.push({ label: `config/git/${digest}/${index++}`, path: manifest });
				}
				if (await exists(path.join(parent, ".git"))) break;
				const next = path.dirname(parent);
				if (next === parent) fail(`missing Git checkout boundary for ${pkg.name}`);
				parent = next;
			}
		}
	}
	packages.sort((a, b) => utf8Compare(packageDigests.get(a)!, packageDigests.get(b)!));
	return { packages, selectedPackages: [...graph.values()], metadata: full };
}

function targetEnvironment(
	env: Readonly<Record<string, string>>,
	variable: string,
	target: string,
	host: string,
): string | undefined {
	for (const name of [
		`${variable}_${target}`,
		`${variable}_${target.replaceAll("-", "_").replaceAll(".", "_")}`,
		`${target === host ? "HOST" : "TARGET"}_${variable}`,
		variable,
	])
		if (Object.hasOwn(env, name)) return env[name];
	return undefined;
}
async function ccDriver(
	context: AdapterContext,
	selected: string,
	role: string,
	drivers: Record<string, string | readonly string[]>,
	flags: string[],
): Promise<void> {
	const raw = selected.trim();
	if (!raw) fail(`empty ${role} selection`);
	let words: string[];
	if (await exists(path.resolve(context.cwd, raw))) words = [raw];
	else words = raw.split(/\s+/);
	const wrappers: Record<string, true> = {
		ccache: true,
		sccache: true,
		distcc: true,
		icecc: true,
		cachepot: true,
		buildcache: true,
	};
	if (context.effectiveEnv.CC_KNOWN_WRAPPER_CUSTOM) wrappers[context.effectiveEnv.CC_KNOWN_WRAPPER_CUSTOM] = true;
	if (wrappers[path.basename(words[0])]) {
		if (words.length < 2) fail(`wrapper ${words[0]} lacks a compiler`);
		drivers[`${role}-wrapper`] = words.shift()!;
	}
	drivers[role] = words[0];
	flags.push(...words.slice(1));
}
async function awsLCSelection(
	context: AdapterContext,
	pkg: MetadataPackage,
	target: string,
	host: string,
	roots: ToolRoot[],
	drivers: Record<string, string | readonly string[]>,
	flags: string[],
	discovery: ToolDiscovery[],
): Promise<void> {
	const prefix = "AWS_LC_SYS_";
	const suffix = target.replaceAll("-", "_");
	const value = (name: string) =>
		context.effectiveEnv[prefix + name + "_" + suffix] ?? context.effectiveEnv[prefix + name];
	const enabled = (name: string) => {
		const setting = value(name);
		return setting !== undefined && !["0", "false", "no", ""].includes(setting.toLowerCase());
	};
	if (
		pkg.attestationFeatures?.some((feature) => ["fips", "ssl", "bindgen", "asan"].includes(feature)) ||
		["NO_PREFIX", "PREGENERATING_BINDINGS", "EXTERNAL_BINDGEN", "NO_ASM", "NO_PREGENERATED_SRC", "CMAKE_BUILDER"].some(
			enabled,
		) ||
		value("SANITIZER") ||
		value("EFFECTIVE_TARGET") ||
		value("INCLUDES")
	)
		fail("AWS-LC selector requires an unsupported generator or external source closure");
	const directory = path.dirname(pkg.manifest_path);
	if (!(await exists(path.join(directory, "src", suffix + "_crypto.rs"))) || target.includes("ohos"))
		fail(`AWS-LC has no supported pregenerated binding context for ${target}`);
	if (value("STATIC") !== undefined && !enabled("STATIC")) fail("AWS-LC dynamic build requires a CMake closure");
	if (value("SYSTEM_DIR") || value("SYSTEM_BINDINGS"))
		fail("explicit system AWS-LC selection requires an incorporated native library closure");
	if (value("USE_SYSTEM") !== undefined && enabled("USE_SYSTEM"))
		fail("required system AWS-LC selection is unsupported");
	if (value("USE_SYSTEM") === undefined || enabled("USE_SYSTEM")) {
		const generic = (name: string) => context.effectiveEnv[name + "_" + suffix] ?? context.effectiveEnv[name];
		const includeDirectories: { path: string; label: string }[] = [];
		const openssl = generic("OPENSSL_DIR");
		const include = generic("OPENSSL_INCLUDE_DIR");
		const lib = generic("OPENSSL_LIB_DIR");
		if (openssl) includeDirectories.push({ path: path.join(openssl, "include"), label: "environment" });
		if (include && (lib || openssl)) includeDirectories.push({ path: include, label: "include-environment" });
		if (!includeDirectories.length && (target === host || context.effectiveEnv.PKG_CONFIG_ALLOW_CROSS === "1")) {
			let pkgConfig: { invoked: string; realpath: string } | undefined;
			try {
				pkgConfig = await context.resolveCommand(
					targetEnvironment(context.effectiveEnv, "PKG_CONFIG", target, host) || "pkg-config",
				);
			} catch (error) {
				if ((error as Error).message.includes("not found") || (error as NodeJS.ErrnoException).code === "ENOENT")
					pkgConfig = undefined;
				else throw error;
			}
			if (pkgConfig) {
				roots.push({ label: "native/pkg-config", path: pkgConfig.realpath });
				const probe = async (args: string[]) => {
					const result = await context.probe([pkgConfig!.invoked, ...args]);
					discovery.push(result.identity);
					return probeText(result).trim();
				};
				const listed = await probe(["--list-all"]);
				const available = new Set(listed.split(/\r?\n/).map((line) => line.split(/\s+/)[0]));
				const visited = new Set<string>();
				async function bindModule(module: string): Promise<void> {
					if (visited.has(module)) return;
					visited.add(module);
					if (!/^[A-Za-z0-9_.+-]+$/.test(module)) fail("unsupported pkg-config module name");
					const pcdir = await probe(["--variable=pcfiledir", module]);
					if (!pcdir) fail("pkg-config did not identify its configuration file");
					roots.push({
						label: `config/pkg-config/${module}`,
						path: await requiredReal(path.join(pcdir, module + ".pc")),
					});
					for (const argument of ["--print-requires", "--print-requires-private"]) {
						const dependencies = await probe([argument, module]);
						for (const dependency of dependencies.split(/\r?\n/).filter(Boolean))
							await bindModule(dependency.split(/\s+/)[0]);
					}
				}
				for (const module of ["openssl", "aws-lc", "libcrypto", "libcrypto-awslc"])
					if (available.has(module)) {
						await bindModule(module);
						const cflags = await probe(["--cflags-only-I", module]);
						const paths = cflags.match(/-I[^ ]+/g) || [];
						if (paths.length) includeDirectories.push({ path: paths[0].slice(2), label: module });
					}
			}
		}
		for (const candidate of includeDirectories) {
			const marker = path.join(path.resolve(context.cwd, candidate.path), "openssl", "base.h");
			if (!(await exists(marker))) continue;
			roots.push({ label: `config/awslc-candidates/${candidate.label}`, path: await requiredReal(marker) });
			if (/^\s*#\s*define\s+OPENSSL_IS_AWSLC\b/m.test(await readText(marker)))
				fail("auto-selected system AWS-LC requires an incorporated native library closure");
		}
	}
	const compiler = value("CC");
	const cxx = value("CXX");
	const cflags = value("CFLAGS");
	if (compiler) await ccDriver(context, compiler, "awslc-compiler", drivers, flags);
	if (cxx) await ccDriver(context, cxx, "awslc-cxx", drivers, flags);
	if (cflags) flags.push(...cflags.split(/\s+/).filter(Boolean));
}
const OPTIONAL_PROCESS_ABSENCE_PROBE = [
	"const fs=require('node:fs'),crypto=require('node:crypto');",
	"if(!['darwin','linux'].includes(process.platform))throw Error('unsupported executable-search platform');",
	"if(process.getuid()!==process.geteuid()||process.getgid()!==process.getegid())throw Error('indeterminate executable access identity');",
	"if(!Object.hasOwn(process.env,'PATH'))throw Error('undeclared executable search path');",
	"if(!/^[A-Za-z0-9_.+-]+$/.test(name)||name==='.'||name==='..')throw Error('unsupported optional process name');",
	"const hash=value=>'sha256:'+crypto.createHash('sha256').update(value,'utf8').digest('hex');",
	"const cwd=process.cwd(),search=process.env.PATH,candidates=[];",
	"for(const directory of search.split(':')){",
	"const candidate=directory.startsWith('/')?directory+'/'+name:(cwd.endsWith('/')?cwd:cwd+'/')+(directory?directory+'/':'')+name;",
	"let absent=false;try{const stat=fs.statSync(candidate);if(!stat.isFile())absent=true;else{try{fs.accessSync(candidate,fs.constants.X_OK);}catch(error){if(error.code==='EACCES')absent=true;else throw Error('indeterminate optional executable access');}}}catch(error){if(['ENOENT','ENOTDIR'].includes(error.code))absent=true;else throw Error('indeterminate optional executable lookup');}",
	"if(!absent)throw Error('optional executable is present and requires a supported tool closure');",
	"candidates.push({path_hash:hash(candidate),absent:true});}",
	"console.log(JSON.stringify({platform:process.platform,cwd_hash:hash(cwd),path_hash:hash(search),candidates}));",
].join("\n");
async function bindOptionalProcessAbsence(
	context: AdapterContext,
	source: string,
	command: string,
	directory: string,
	rustc: string,
	executables: string[],
	discovery: ToolDiscovery[],
): Promise<void> {
	if (/\b(?:set_var|remove_var|set_current_dir)\b/.test(source))
		fail("optional process lookup is changed by its build script");
	if (!/^[A-Za-z0-9_.+-]+$/.test(command) || command === "." || command === "..")
		fail("unsupported optional executable search selection");
	if (!Object.hasOwn(context.effectiveEnv, "PATH")) fail("optional executable search requires a declared PATH");
	const packageCwd = beneath(context.root, directory);
	if (!packageCwd && context.effectiveEnv.PATH.split(path.delimiter).some((entry) => !path.isAbsolute(entry)))
		fail("external build-script optional process lookup requires absolute nonempty PATH entries");
	// External cwd cannot be recorded; absolute PATH entries make lookup cwd-independent.
	// Keep the selector inside the evaluated program, not in an executable operand.
	const script = "const name=" + JSON.stringify(command) + ";\n" + OPTIONAL_PROCESS_ABSENCE_PROBE;
	const result = await context.probe([process.execPath, "-e", script], {
		cwd: packageCwd ? directory : context.cwd,
		env: { ...context.effectiveEnv, RUSTC: rustc, CARGO_MANIFEST_DIR: directory },
	});
	if (result.code !== 0) fail("optional executable absence could not be established");
	const cwd = packageCwd ? directory : context.cwd,
		search = context.effectiveEnv.PATH;
	const expected = {
		platform: process.platform,
		cwd_hash: H(Buffer.from(cwd)),
		path_hash: H(Buffer.from(search)),
		candidates: search.split(path.delimiter).map((directory) => ({
			path_hash: H(
				Buffer.from(
					directory.startsWith("/")
						? directory + "/" + command
						: cwd + "/" + (directory ? directory + "/" : "") + command,
				),
			),
			absent: true,
		})),
	};
	if (
		!result.stdout.length ||
		D("optional-process-search", parseJSON(result.stdout)) !== D("optional-process-search", expected)
	)
		fail("optional executable absence probe did not report the selected search context");
	discovery.push(result.identity);
	if (!executables.includes(process.execPath)) executables.push(process.execPath);
}
function rustSourceCode(source: string): string | null {
	const rawString = /(?:b|c)?r(#{0,255})"/y;
	const character = /'(?:[^'\\\r\n]|\\(?:[nrt0\\'"]|x[0-9A-Fa-f]{2}|u\{[0-9A-Fa-f_]+\}))'/uy;
	let offset = 0,
		copied = 0,
		code = "";
	while (offset < source.length) {
		const start = offset;
		if (source.startsWith("//", offset)) {
			const end = source.indexOf("\n", offset + 2);
			offset = end < 0 ? source.length : end + 1;
		} else if (source.startsWith("/*", offset)) {
			let depth = 1;
			offset += 2;
			while (offset < source.length && depth) {
				if (source.startsWith("/*", offset)) {
					depth++;
					offset += 2;
				} else if (source.startsWith("*/", offset)) {
					depth--;
					offset += 2;
				} else offset++;
			}
			if (depth) return null;
		} else {
			rawString.lastIndex = offset;
			const raw = rawString.exec(source);
			if (raw) {
				const closing = '"' + raw[1],
					end = source.indexOf(closing, rawString.lastIndex);
				if (end < 0) return null;
				offset = end + closing.length;
			} else if (source[offset] === '"') {
				offset++;
				while (offset < source.length && source[offset] !== '"') offset += source[offset] === "\\" ? 2 : 1;
				if (offset >= source.length) return null;
				offset++;
			} else if (source[offset] === "'" && ((character.lastIndex = offset), character.test(source))) {
				offset = character.lastIndex;
			} else {
				offset++;
				continue;
			}
		}
		code += source.slice(copied, start) + " ".repeat(offset - start);
		copied = offset;
	}
	return code + source.slice(copied);
}
function hasNativeSourceLinkage(source: string, sourceLinksOnly = false, target = ""): boolean {
	const code = rustSourceCode(source);
	if (code === null) return true;
	for (const match of code.matchAll(/\b(?:link|link_args)\s*(?:\(|=)|\binclude\s*!|#\s*\[\s*path\s*=/g)) {
		if (/^link(?:_args)?\b/.test(match[0])) {
			const open = code.lastIndexOf("[", match.index);
			if (open < 0 || open < code.lastIndexOf("]", match.index) || !code.slice(0, open).trimEnd().endsWith("#"))
				continue;
		}
		if (!sourceLinksOnly) return true;
		if (!/^link(?:_args)?\b/.test(match[0])) continue;
		const attribute =
			/^link\s*\(\s*name\s*=\s*"([A-Za-z0-9_.+-]+)"\s*(?:,\s*kind\s*=\s*"(framework|dylib)"\s*)?\)/.exec(
				source.slice(match.index),
			);
		if (!attribute) return true;
		if (attribute[2] === "framework" && target.endsWith("-apple-darwin")) continue;
		if (
			["c", "m", "pthread", "dl", "rt", "util", "resolv", "objc", "c++"].includes(attribute[1]) &&
			(!attribute[2] || attribute[2] === "dylib")
		)
			continue;
		return true;
	}
	return false;
}
// These complete source snapshots place their Windows imports behind cfg(windows).
const REVIEWED_NONWINDOWS_LINK_SOURCES: Record<string, string> = {
	"find-msvc-tools@0.1.9": "sha256:ef2beb3ec38bff67c6b8ef8a70d6a28818e73f7a4cc3abd0df7b008f03f7c874",
	"find-msvc-tools@0.1.14": "sha256:22a3bba4a8a60d3a521757fdfa5cd9891d73695f65ab18da8ec9c549732902ad",
	"jobserver@0.1.34": "sha256:059bd857a7d7234832e7e498693765a9cdd3cf3f1c296701452b6fbd0fc23d5f",
	"jobserver@0.1.35": "sha256:a63c9defad34cac7f2d136298777c0a5709f905bcbe0bfb2089e76a96feb1ea5",
	"cmake@0.1.58": "sha256:1a8c1153c631ffd5a0ca9ebbf73d1a6dcda592e978824b85cbbde94eacea2864",
	"getrandom@0.2.17": "sha256:280d6782ab784ef4618985933641af51f23abb178dac57018885e77337dd3d81",
};
// Dynamic data/doc macros and their callers require exact reviewed source snapshots.
const REVIEWED_INCLUSION_SOURCES: Record<string, string> = {
	"aead@0.5.2": "sha256:356814d9ab3736d9660b8a0aa389d2cf90db49a3bc70624f2c22ba47cf01bf69",
	"aes-gcm@0.10.3": "sha256:3843e4feaa26f8538e2c30c6995bb3b915232b234f89eeec053179752142acf3",
	"aes@0.8.4": "sha256:047434ce7c24c8c6cf764e3667d8e38076c0e3407e5dccde44640ee45233f9ff",
	"aws-lc-rs@1.18.0": "sha256:8d3e6ef56f63af1236429c44a51b336e0e4712b06ad392bb08a952311589e554",
	"chacha20@0.10.2": "sha256:20ee855b7ef93ce233de7d6ab702b492e044ea397186f682f5f15cc14b003d82",
	"cipher@0.4.4": "sha256:5e19a8e10437f3a5fc0311fc001cd5e83ac787d4137524703e8709158a31bb72",
	"crc-fast@1.10.0": "sha256:5f54db9f130454a3e63e53809e8fd4c0e89171daa04ee26b64f0b16759c381c9",
	"ctr@0.9.2": "sha256:b6a125141e469a2a284abaee6e49b02f7d9568972fa9effa70b4d9c605fcc1c2",
	"derive_more-impl@2.1.1": "sha256:77427b40280488fd31be6519cac82ee45c85a587d29cc3aed358579cc7559301",
	"digest@0.10.7": "sha256:998224c165aaec9a6ba72a81c7e28cee89af3beb95bbb491e8d22413e3a3c035",
	"digest@0.11.3": "sha256:196d2e89a33dd98b340e51a9d3272415a02fd4675a62814b7fece758fe757d42",
	"ecdsa@0.16.9": "sha256:8cda5c2b2f4dbf5e61cc67654d64682a17435c358b119269ce649e8831ed0528",
	"ecdsa@0.17.0": "sha256:dccb6ee88c003d85499ffc4354ddc466be3b3ee7403f8fc860c0b4d3015803e1",
	"fs_extra@1.3.0": "sha256:75c631a4108c96632b600adbce5a610874ddad9ef61611bec2f77f134eb7d705",
	"hmac@0.12.1": "sha256:1659f82120a305396903bc020324abe38f962767d62bbb534c4c0705c981fda4",
	"hmac@0.13.0": "sha256:4c0acf23c9c095002e49e2cb246ac3729e55226f0cb7f91e4ef4cc4b24324cec",
	"p256@0.13.2": "sha256:b075f8c0b77c76bca8e06f73d18017b87e9e5c0fef3aa570002974cc8af38b07",
	"p256@0.14.0": "sha256:ab723190b284f867e0ae101cc2af19a3d55e58527fe487a5fbe9e1544e4bc30f",
	"serde_with@3.11.0": "sha256:88f54bdf7340b5670dc81668a693b417fd31622c127d7b5c459ebfea464b0144",
	"sha2@0.10.9": "sha256:ec86b36e4fb7cf990d15d0599af8ff67110e4bc5491e862c8d0f4d041b5485b8",
	"sha2@0.11.0": "sha256:eebd02fcbc76d96f8ce4b2290465e5b199c14d399a29ee2ada38a66263beb45e",
	"zerocopy@0.8.52": "sha256:91f758225d4e328f631dfa38243e7b9322a9886377aadb78747c596c97b21355",
};
// This exact dependency file ends in an inactive #[cfg(test)] module with unpackaged workspace fixtures.
const REVIEWED_INACTIVE_TEST_SOURCES: Record<string, string> = {
	"cosmwasm-std@3.0.7/src/testing/mock.rs": "sha256:07be3ab615dbd7188a72233a959c758cd6c9bd7ed0cbfe4f12ce8d7dde4f05b2",
	"cosmwasm-std@3.0.9/src/testing/mock.rs": "sha256:07be3ab615dbd7188a72233a959c758cd6c9bd7ed0cbfe4f12ce8d7dde4f05b2",
};
const REVIEWED_INACTIVE_GIT_SOURCES: Record<string, string> = {
	"serde_derive_internals@0.29.1/lib.rs": "sha256:f6b6a9432c01e8837479969e86211b71bdbe5b36eacbc4124118c4b0d635f5e5",
	"serde_derive_internals@0.30.0/lib.rs": "sha256:024e87422592d0eb7ff9d13e56b71a48f1399a0feeb3d8ad90e9e43870318535",
};
function assertRustSourceIncludes(
	source: string,
	filename: string,
	directory: string,
	excluded: readonly string[],
	generated: boolean,
	inactiveTests: boolean,
	inactiveGit: boolean,
	includedSources: Set<string>,
): boolean {
	let code = rustSourceCode(source);
	if (code === null) fail("unclassified Rust source inclusion syntax in " + filename);
	for (const match of code.matchAll(/\bkani\s*::\s*solver\s*\(([^)]*)\)/g))
		if (!/^kissat\s*,?$/.test(match[1].trim()))
			fail("Kani solver attribute requires the installed pinned kissat selection in " + filename);
	if (inactiveTests) {
		const start = code.search(/#\s*\[\s*cfg\s*\(\s*test\s*\)\s*\]\s*mod\s+tests\s*\{/);
		if (start >= 0) code = code.slice(0, start);
	}
	if (inactiveGit)
		code = code.replace(/#\s*\[\s*cfg_attr\s*\(\s*serde_build_from_git\s*,[\s\S]*?\]/g, (match) =>
			" ".repeat(match.length),
		);
	if (/\buse\b[^;]*\binclude(?:_bytes|_str)?\b/.test(code))
		fail("Rust inclusion macro imports are unsupported in " + filename);
	function bound(value: string, sourceInput: boolean): void {
		const resolved = path.resolve(path.dirname(filename), value);
		const relative = path.relative(directory, resolved).split(path.sep).join("/");
		if (
			!value ||
			path.isAbsolute(value) ||
			value.includes("\\") ||
			/[\x00-\x1f]/.test(value) ||
			!beneath(directory, resolved) ||
			excluded.some((item) => relative === item || relative.startsWith(item + "/"))
		)
			fail("Rust source inclusion is outside immutable package roots: " + value);
		if (sourceInput && !resolved.endsWith(".rs")) includedSources.add(resolved);
	}
	let dynamic =
		/\b(?:block_cipher_test|block_mode_dec_test|block_mode_enc_test|codegen_example|create_derive|generate_guide|hash_serialization_test|include_value|new_mac_test|new_resettable_mac_test|new_test|new_wycheproof_test|stream_cipher_test|test_file)\b/.test(
			code,
		);
	for (const match of code.matchAll(
		/\binclude(?:_bytes|_str)?\s*!\s*[([{]|#\s*\[\s*(?:cfg_attr\s*\([^\n;]*,\s*)?path\s*=/g,
	)) {
		const sourceInput = /^include\s*!|^#/.test(match[0]);
		const tail = source.slice(match.index! + match[0].length).trimStart();
		const literal = /^(?:"(?:[^"\\]|\\.)*"|r(#{0,255})"[\s\S]*?"\1)/.exec(tail);
		if (literal) {
			let value: string;
			if (literal[1] !== undefined) value = literal[0].slice(2 + literal[1].length, -1 - literal[1].length);
			else {
				try {
					value = parseJSON(Buffer.from(literal[0])) as string;
				} catch {
					fail("unsupported Rust inclusion string escape in " + filename);
				}
			}
			bound(value, sourceInput);
		} else if (
			generated &&
			/^concat!\(\s*env!\(\s*"OUT_DIR"\s*\)\s*,\s*"\/[A-Za-z0-9_][A-Za-z0-9_.-]*"\s*,?\s*\)/.test(tail)
		) {
			continue;
		} else {
			const concatenated = /^concat!\(\s*((?:"[^"\\]*"\s*,\s*)*"[^"\\]*"\s*,?)\s*\)/.exec(tail);
			if (concatenated)
				bound([...concatenated[1].matchAll(/"([^"\\]*)"/g)].map((item) => item[1]).join(""), sourceInput);
			else dynamic = true;
		}
	}
	return dynamic;
}

async function assertNoPackageLinkDirectives(
	pkg: MetadataPackage,
	roots: readonly ToolRoot[],
	sourceLinksOnly = false,
	target = "",
	unmodifiedTargetCfg = true,
	includesOnly = false,
	inactiveGit = false,
): Promise<void> {
	const directory = await requiredReal(path.dirname(pkg.manifest_path));
	const view = roots.find((root) => root.label.startsWith("packages/") && root.path === directory);
	if (!view) fail("missing source root for links-only package " + pkg.name);
	const reviewed =
		sourceLinksOnly &&
		unmodifiedTargetCfg &&
		pkg.source === "registry+https://github.com/rust-lang/crates.io-index" &&
		/(?:-apple-darwin|-unknown-linux-(?:gnu|musl))$/.test(target)
			? REVIEWED_NONWINDOWS_LINK_SOURCES[pkg.name + "@" + pkg.version]
			: undefined;
	const inclusionReview =
		pkg.source === "registry+https://github.com/rust-lang/crates.io-index"
			? REVIEWED_INCLUSION_SOURCES[pkg.name + "@" + pkg.version]
			: undefined;
	const files: [string, string][] =
		reviewed || inclusionReview ? [["Cargo.toml", H(await fs.readFile(pkg.manifest_path))]] : [];
	let needsInclusionReview = false;
	const includedSources = new Set<string>();
	const pending = [{ directory, relative: "" }];
	while (pending.length) {
		const current = pending.pop()!;
		for (const entry of await fs.readdir(current.directory, { withFileTypes: true })) {
			const relative = current.relative ? current.relative + "/" + entry.name : entry.name;
			if (view.exclude?.some((excluded) => relative === excluded || relative.startsWith(excluded + "/"))) continue;
			const filename = path.join(current.directory, entry.name);
			if (entry.isSymbolicLink()) fail("indeterminate links-only package source alias in " + pkg.name);
			if (entry.isDirectory()) pending.push({ directory: filename, relative });
			else if (entry.isFile() && entry.name.endsWith(".rs")) {
				const rust = await readText(filename);
				const inactiveTests =
					pkg.source === "registry+https://github.com/rust-lang/crates.io-index" &&
					H(Buffer.from(rust)) === REVIEWED_INACTIVE_TEST_SOURCES[pkg.name + "@" + pkg.version + "/" + relative];
				const reviewedGit =
					inactiveGit &&
					pkg.source === "registry+https://github.com/rust-lang/crates.io-index" &&
					H(Buffer.from(rust)) === REVIEWED_INACTIVE_GIT_SOURCES[pkg.name + "@" + pkg.version + "/" + relative];
				needsInclusionReview =
					assertRustSourceIncludes(
						rust,
						filename,
						directory,
						view.exclude || [],
						pkg.targets.some((item) => item.kind.includes("custom-build")),
						inactiveTests,
						reviewedGit,
						includedSources,
					) || needsInclusionReview;
				if (reviewed || inclusionReview) files.push([relative, H(Buffer.from(rust))]);
				if (!includesOnly && hasNativeSourceLinkage(rust, sourceLinksOnly, target) && !reviewed)
					fail("unresolved Rust-source native linkage in " + pkg.name);
			}
		}
	}
	for (const filename of includedSources) {
		const source = await readText(filename);
		if (assertRustSourceIncludes(source, filename, directory, view.exclude || [], false, false, false, includedSources))
			fail("unreviewed dynamic included Rust source in " + pkg.name);
		if (!includesOnly && hasNativeSourceLinkage(source, sourceLinksOnly, target))
			fail("unresolved included Rust-source native linkage in " + pkg.name);
	}
	if (reviewed) {
		files.sort((a, b) => utf8Compare(a[0], b[0]));
		if (H(Buffer.from(JSON.stringify(files))) !== reviewed)
			fail("unreviewed cfg-gated native linkage source in " + pkg.name);
	}
	if (needsInclusionReview) {
		files.sort((a, b) => utf8Compare(a[0], b[0]));
		if (!inclusionReview || H(Buffer.from(JSON.stringify(files))) !== inclusionReview)
			fail("unreviewed dynamic Rust source inclusion in " + pkg.name);
	}
}

// Exact installed build programs, not package names, select the bounded native/compiler cases.
const REVIEWED_BUILD_SCRIPTS: Record<
	string,
	{ kind: "native" | "compiler" | "framework" | "metadata"; hash: string; files?: Record<string, string> }
> = {
	"blst@0.3.16": { kind: "native", hash: "sha256:3b0a6eea2bf5c4d0c327fbe48f81b900e6896bdf92d4cfafcc1010d999b0fea7" },
	"blst@0.3.17": { kind: "native", hash: "sha256:3b0a6eea2bf5c4d0c327fbe48f81b900e6896bdf92d4cfafcc1010d999b0fea7" },
	"ring@0.17.14": { kind: "native", hash: "sha256:9d1928ffb1d8e15766c1c1b9ead73e4b81a21703dd25f7c27b87842a2e6e9cee" },
	"blake3@1.8.5": { kind: "native", hash: "sha256:680019541096959dba4e1b6795ecf1b17233f18d7d2450fe1c5d446d71c9cca5" },
	"system-configuration-sys@0.5.0": {
		kind: "framework",
		hash: "sha256:cf4c21c898e9671345d4684c75014189623574f9ec96414999a9db2d73b1e40f",
	},
	"system-configuration-sys@0.6.0": {
		kind: "framework",
		hash: "sha256:cf4c21c898e9671345d4684c75014189623574f9ec96414999a9db2d73b1e40f",
	},
	"anyhow@1.0.102": {
		kind: "compiler",
		hash: "sha256:89d1baedcff59822ed692d3a33f131c211a213bdec33c83f68b54110d9c64223",
	},
	"anyhow@1.0.104": {
		kind: "compiler",
		hash: "sha256:89d1baedcff59822ed692d3a33f131c211a213bdec33c83f68b54110d9c64223",
	},
	"proc-macro2@1.0.106": {
		kind: "compiler",
		hash: "sha256:baeb20b52f6b536be8657a566591a507bb2e34a45cf8baa42b135510a0c3c729",
	},
	"proc-macro2@1.0.107": {
		kind: "compiler",
		hash: "sha256:baeb20b52f6b536be8657a566591a507bb2e34a45cf8baa42b135510a0c3c729",
	},
	"libc@0.2.186": { kind: "compiler", hash: "sha256:4b348c53d0a0cd0067ef9887b50f60a1fffdc5d00dda5c0e27fae6aa0ce3dee8" },
	"getrandom@0.3.4": {
		kind: "compiler",
		hash: "sha256:d542c9c3bbc2f64a26c758eac8af16178aab52464bdd8bf0b9a767ba87665021",
	},
	"httparse@1.10.1": {
		kind: "compiler",
		hash: "sha256:eba8e341d746a6cf54249c62afe9eb237e7c21fcf9937223e894549e3a34d489",
	},
	"rustix@1.1.4": { kind: "compiler", hash: "sha256:74cb32e64aa6fe99c2496a425b016e22f4e43c438a8237966b8acae04a98eaf9" },
	"eyre@0.6.14": { kind: "compiler", hash: "sha256:85f97f403d25be35c6984f83248795cdd7fa68241a5a6f839216b33570b81469" },
	"thiserror@1.0.69": {
		kind: "compiler",
		hash: "sha256:275d0ddbb22d5f015fba360f51a48da10b6309410efe8c6ca678412b1e8c9288",
	},
	"thiserror@2.0.18": {
		kind: "compiler",
		hash: "sha256:18bf4b4af0f507c7fdfe4dbfc98b5ac3d6a5ef924f46ee56125fd8b22fd61b4c",
	},
	"rustversion@1.0.22": {
		kind: "compiler",
		hash: "sha256:6d869d2230fa9c4f8ae0df956b06438a070df276649135d4309f56eac72ddbe3",
		files: { "build/rustc.rs": "sha256:faf67033ec831d968406f5a66c475df337f7221e9d1ab3477fed3a629e1ec5bc" },
	},
	"crossbeam-utils@0.8.21": {
		kind: "compiler",
		hash: "sha256:7a7f9e56ea7fb4f78c4e532b84b9d27be719d600e85eaeb3a2f4b79a4f0b419c",
		files: {
			"build-common.rs": "sha256:502cb7494549bed6fa10ac7bea36e880eeb60290dc69b679ac5c92b376469562",
			"no_atomic.rs": "sha256:fc1baa4489d9842988bacaaa545a7d7d0e2f8b93cfa0b7d1ae31f21256e4cb0a",
		},
	},
	"ahash@0.8.12": { kind: "compiler", hash: "sha256:d7dd5428c78b80bb3c99068561641ec661f0f94defbda17f85b443e358ab6396" },
	"aws-lc-rs@1.18.0": {
		kind: "metadata",
		hash: "sha256:791f97e6abdb685bcc722342d49f2646b3146b209f68753669c178716f6cee01",
	},
	"commonware-macros-impl@2026.7.1": {
		kind: "compiler",
		hash: "sha256:3fcd6fc94492b0da173358d5c213bcfe1159060e333de0cb771a66857d0f6988",
	},
	"crossbeam-epoch@0.9.20": {
		kind: "compiler",
		hash: "sha256:e40cf96d7d7b1650f9f53a3f578633a178324dbea1d905b3f71a75b45d3982a1",
	},
	"curve25519-dalek@4.1.3": {
		kind: "compiler",
		hash: "sha256:c479ea95fa9cac8b3374564261c15cfcb110738ddcaa5e0852644b6083bd9189",
	},
	"curve25519-dalek@5.0.0": {
		kind: "compiler",
		hash: "sha256:f13e2e0acd42c676532e115850473120531beec43439b335e1753a2f026f3713",
	},
	"generic-array@0.14.7": {
		kind: "compiler",
		hash: "sha256:08fa30c4a2c1ad24fe5f987e721dfb20131f45ea5b5dc3e836dcf88a8e33248c",
	},
	"getrandom@0.4.3": {
		kind: "compiler",
		hash: "sha256:662faa06d7b2a9c5bea2c17a127a90e00b9f9b31105b0360da516e47cf816e95",
	},
	"num-traits@0.2.19": {
		kind: "compiler",
		hash: "sha256:d3969209fc1c9d201c66ed11820d0b328600d75b3971f8ceebeab04900bc0587",
	},
	"owo-colors@4.3.0": {
		kind: "compiler",
		hash: "sha256:afffaf4540849a8daf1e5a2efbb7eba25ede31c77060ca4f14dc43f8b7aadbeb",
	},
	"parking_lot_core@0.9.12": {
		kind: "compiler",
		hash: "sha256:3698c936b75f8332d9b6b30a8a6838ea116c1ff0a819a025c9ea9696e4d8ce72",
	},
	"paste@1.0.15": { kind: "compiler", hash: "sha256:dba46ae4291317fb644ba2143f44eaf54a8ab946ba1367a33d055d694715f68a" },
	"quote@1.0.45": { kind: "compiler", hash: "sha256:cd6808c02e476b09a520105e2c6f6d325cccb1ecd542cbbcc836a0ae6f6fb0f1" },
	"rayon-core@1.13.0": {
		kind: "compiler",
		hash: "sha256:fa31cb198b772600d100a7c403ddedccef637d2e6b2da431fa7f02ca41307fc6",
	},
	"ref-cast@1.0.25": {
		kind: "compiler",
		hash: "sha256:743b6af556ae46ab03ab547850bed4e96d66270b9ad29183dac0a005a801e76e",
	},
	"schemars@0.8.22": {
		kind: "compiler",
		hash: "sha256:5ef3c87640a839e95aa892c4dbc9557d8b6437caa697b53a598954cf471e2303",
	},
	"serde@1.0.228": {
		kind: "compiler",
		hash: "sha256:c99c25e1a11f3e51b61dd8c25bdbfbd090e43e5f1f2014f41f28e214dd8310d5",
	},
	"serde_core@1.0.228": {
		kind: "compiler",
		hash: "sha256:a5fdacb9913eeede5fc08f39acbd31b2508483fdc20c79d6bc274d74407a1816",
	},
	"serde_json@1.0.150": {
		kind: "compiler",
		hash: "sha256:a681e754be844c7dbef957f5d2d00b01f37c5dca160ef1055a8d8f975697a881",
	},
	"typeid@1.0.3": { kind: "compiler", hash: "sha256:688afbcaa398ea159c3481b26d74fde6ce3a675d48364d772557c8e91100de46" },
	"zerocopy@0.8.52": {
		kind: "compiler",
		hash: "sha256:916639a8cc523f6b7551c946706f551b24352cd50c84a2284ca313798bc77ee5",
	},
	"zmij@1.0.21": { kind: "compiler", hash: "sha256:13201b550236a9ff2186b5303c77341d3b0874989fdaf39613a7452e4ce57817" },
};
const REVIEWED_BUILD_HELPERS: Record<string, string> = {
	"autocfg@1.5.1": "sha256:aa7e410fca7287d61d0824601c0d3e45b9842589ff2819a74ea39d2522e6e87b",
	"cc@1.2.64": "sha256:a936b5254b323fa504bd79446fd272e14094c3bff144d3697a97bd756d0ffc39",
	"cmake@0.1.58": "sha256:1a8c1153c631ffd5a0ca9ebbf73d1a6dcda592e978824b85cbbde94eacea2864",
	"dunce@1.0.5": "sha256:2690b64863794377deb65d6af0293c6a6a1ead5f7b92d0d315f18057e532503c",
	"find-msvc-tools@0.1.9": "sha256:ef2beb3ec38bff67c6b8ef8a70d6a28818e73f7a4cc3abd0df7b008f03f7c874",
	"fs_extra@1.3.0": "sha256:75c631a4108c96632b600adbce5a610874ddad9ef61611bec2f77f134eb7d705",
	"jobserver@0.1.34": "sha256:059bd857a7d7234832e7e498693765a9cdd3cf3f1c296701452b6fbd0fc23d5f",
	"libc@0.2.186": "sha256:53979fbb809cab984c26d7b22e28b06dd76c1902c0943b7a156073047f85bed7",
	"pkg-config@0.3.34": "sha256:47068b241becabad5d8380787bf2ac205f520139c33a9930c7e20b64049942b7",
	"rustc_version@0.4.1": "sha256:70ca6d542316238ecc59e1719a7d8c561317e4e8527f4150a4fb5fc53af183c5",
	"semver@1.0.28": "sha256:995768eb9622177f303318ad015425bcc8501cc29c1baf76ff53af2572d2ec25",
	"shlex@2.0.1": "sha256:a891d7e74817dd33c7ef81b05e76351374702bf54458e27aaa219ba574e1c53e",
	"version_check@0.9.5": "sha256:0c117a46e907111ce7b768e87344be06ab64f74a3d89f94864c78db8ecf718e1",
};
async function packageRustFingerprint(pkg: MetadataPackage): Promise<string> {
	const directory = path.dirname(pkg.manifest_path);
	const files: [string, string][] = [["Cargo.toml", H(await fs.readFile(pkg.manifest_path))]];
	async function collect(parent: string, relative = ""): Promise<void> {
		for (const entry of await fs.readdir(parent, { withFileTypes: true })) {
			if (entry.name === ".git" || entry.name === "target") continue;
			const name = relative ? relative + "/" + entry.name : entry.name;
			const filename = path.join(parent, entry.name);
			if (entry.isSymbolicLink()) fail("aliased reviewed Rust source in " + pkg.name);
			if (entry.isDirectory()) await collect(filename, name);
			else if (entry.isFile() && entry.name.endsWith(".rs")) files.push([name, H(await fs.readFile(filename))]);
		}
	}
	await collect(directory);
	files.sort((a, b) => utf8Compare(a[0], b[0]));
	return H(Buffer.from(JSON.stringify(files)));
}

async function assertReviewedBuildHelpers(
	pkg: MetadataPackage,
	packages: ReadonlyMap<string, MetadataPackage>,
	checked: Set<string>,
): Promise<void> {
	for (const id of pkg.attestationBuildDependencies || []) await visit(id);
	async function visit(id: string): Promise<void> {
		if (checked.has(id)) return;
		const helper = packages.get(id);
		if (
			!helper ||
			helper.source !== "registry+https://github.com/rust-lang/crates.io-index" ||
			(await packageRustFingerprint(helper)) !== REVIEWED_BUILD_HELPERS[helper.name + "@" + helper.version]
		)
			fail("unreviewed build-script dependency " + (helper?.name || id));
		checked.add(id);
		for (const dependency of [
			...(helper.attestationDependencies || []),
			...(helper.attestationBuildDependencies || []),
		])
			await visit(dependency);
	}
}

async function reviewedBuildScript(
	pkg: MetadataPackage,
	source: string,
	target: string,
): Promise<"native" | "compiler" | "framework" | "metadata" | undefined> {
	if (
		pkg.source !== "registry+https://github.com/rust-lang/crates.io-index" ||
		!/(?:-apple-darwin|-unknown-linux-(?:gnu|musl))$/.test(target)
	)
		return undefined;
	if (pkg.name === "aws-lc-sys" && pkg.version === "0.44.0") {
		const directory = path.join(path.dirname(pkg.manifest_path), "builder");
		const files: [string, string][] = [];
		async function collect(parent: string, relative = ""): Promise<void> {
			for (const entry of await fs.readdir(parent, { withFileTypes: true })) {
				const name = relative ? relative + "/" + entry.name : entry.name,
					filename = path.join(parent, entry.name);
				if (entry.isSymbolicLink()) fail("aliased AWS-LC build source");
				if (entry.isDirectory()) await collect(filename, name);
				else if (entry.isFile() && entry.name.endsWith(".rs")) files.push([name, H(await fs.readFile(filename))]);
			}
		}
		await collect(directory);
		files.sort((a, b) => utf8Compare(a[0], b[0]));
		if (
			H(Buffer.from(JSON.stringify(files))) ===
				"sha256:1ed89edc8d2710e7eba0275fad396237d3dad9b52d29db24222d82349c0fac86" &&
			source === (await readText(path.join(directory, "main.rs")))
		)
			return "native";
		return undefined;
	}
	const reviewed = REVIEWED_BUILD_SCRIPTS[pkg.name + "@" + pkg.version];
	if (!reviewed || H(Buffer.from(source)) !== reviewed.hash) return undefined;
	for (const [relative, hash] of Object.entries(reviewed.files || {}))
		if (H(await fs.readFile(path.join(path.dirname(pkg.manifest_path), relative))) !== hash) return undefined;
	return reviewed.kind;
}
async function assertBoundNativeFlags(
	flags: readonly string[],
	roots: readonly ToolRoot[],
	directories: readonly string[],
): Promise<void> {
	let views: { root: ToolRoot; real: string; directory: boolean }[] | undefined;
	async function bound(value: string): Promise<void> {
		if (!value || /["'\\\x00-\x1f]/.test(value)) fail("unsupported native flag input path");
		if (!views) {
			views = [];
			for (const root of roots) {
				const real = await requiredReal(root.path);
				views.push({ root, real, directory: (await fs.stat(real)).isDirectory() });
			}
		}
		for (const directory of directories) {
			const filename = await requiredReal(path.resolve(directory, value));
			if (
				!views.some((view) => {
					if (view.directory ? !beneath(view.real, filename) : view.real !== filename) return false;
					const relative = path.relative(view.real, filename).split(path.sep).join("/");
					return !view.root.exclude?.some((excluded) => relative === excluded || relative.startsWith(excluded + "/"));
				})
			)
				fail("native flag input is outside hashed roots: " + value);
		}
	}
	const arguments_: string[] = [];
	for (const flag of flags) {
		if (flag.startsWith("-Wl,")) arguments_.push(...flag.slice(4).split(","));
		else if (flag !== "-Xlinker" && flag !== "-Xclang") arguments_.push(flag);
	}
	const inputOptions = [
		"-include-pch",
		"-include",
		"-imacros",
		"-isystem",
		"-iquote",
		"-idirafter",
		"-iprefix",
		"-iwithprefixbefore",
		"-iwithprefix",
		"-isysroot",
		"--sysroot",
		"-iframework",
		"-I",
		"-L",
		"-F",
		"-T",
		"--script",
		"--version-script",
		"-force_load",
		"-filelist",
		"-bundle_loader",
		"-exported_symbols_list",
		"-unexported_symbols_list",
		"-reexport_library",
		"-weak_library",
		"-rpath",
		"-specs",
		"-fplugin",
		"-fmodule-file",
		"-fprofile-use",
		"-fprofile-instr-use",
	];
	for (let index = 0; index < arguments_.length; index++) {
		const argument = arguments_[index];
		if (argument.startsWith("@") || /^-l.+/.test(argument) || argument === "-l" || argument === "-framework")
			fail("unclassified native flag input: " + argument);
		const option = inputOptions.find(
			(option) =>
				argument === option ||
				argument.startsWith(option + "=") ||
				(["-I", "-L", "-F", "-T", "-include", "-isystem", "-iquote"].includes(option) && argument.startsWith(option)),
		);
		if (option) {
			const value = argument === option ? arguments_[++index] : argument.slice(option.length).replace(/^=/, "");
			await bound(value);
		} else if (!argument.startsWith("-")) await bound(argument);
		else if (argument.includes("/") || argument.includes("\\") || /=.*\.(?:a|o|so|dylib|ld|h|pch|pcm)$/.test(argument))
			fail("unclassified native flag input: " + argument);
	}
}
function assertReviewedRustFlags(value: Value | undefined, name: string, target: string): void {
	const arguments_ =
		typeof value === "string"
			? value.split(/\s+/).filter(Boolean)
			: Array.isArray(value) && value.every((item) => typeof item === "string")
				? (value as string[])
				: value === undefined
					? []
					: fail(`unsupported ${name} value`);
	for (let index = 0; index < arguments_.length; index++) {
		const argument = arguments_[index];
		if (argument === "--sysroot" || argument.startsWith("--sysroot="))
			fail(`${name} --sysroot requires an unsupported selected-sysroot closure`);
		const codegen =
			argument === "-C" || argument === "--codegen"
				? arguments_[++index]
				: argument.startsWith("-C")
					? argument.slice(2)
					: argument.startsWith("--codegen=")
						? argument.slice(10)
						: undefined;
		if (name === "rustflags" && target === "wasm32-unknown-unknown" && codegen === "link-arg=--allow-undefined")
			continue;
		fail(`unsupported ${name} token ${argument}; only reviewed wasm --allow-undefined codegen is admitted`);
	}
}

function assertReviewedCargoConfiguration(
	context: AdapterContext,
	config: Configuration,
	target: string,
	host: string,
): void {
	const build = table(config.values.build);
	const buildKeys = [
		"target",
		"target-dir",
		"build-dir",
		"rustc",
		"rustc-wrapper",
		"rustc-workspace-wrapper",
		"rustflags",
		"rustdocflags",
		"jobs",
		"incremental",
	];
	for (const key of Object.keys(build))
		if (!buildKeys.includes(key)) fail("unsupported Cargo build configuration " + key);
	assertReviewedRustFlags(build.rustflags, "rustflags", target);
	assertReviewedRustFlags(build.rustdocflags, "rustdocflags", target);
	for (const [triple, value] of Object.entries(table(config.values.target))) {
		if (!/^[A-Za-z0-9._-]+$/.test(triple)) fail("unsupported Cargo target selection key " + triple);
		const selected = table(value);
		for (const key of Object.keys(selected))
			if (!["linker", "runner", "rustflags", "rustdocflags"].includes(key))
				fail(`unsupported Cargo target configuration ${triple}.${key}`);
		if (selected.runner !== undefined) fail("Cargo target runner is unsupported");
		if (triple === host && selected.linker !== undefined) fail("Cargo host linker is unsupported");
		assertReviewedRustFlags(selected.rustflags, "rustflags", triple);
		assertReviewedRustFlags(selected.rustdocflags, "rustdocflags", triple);
	}
	for (const [name, value] of Object.entries(context.effectiveEnv)) {
		if (name === "RUSTDOC") fail("configured rustdoc requires an unsupported selected-tool closure");
		if (name.startsWith("CARGO_PROFILE_"))
			fail("Cargo profile environment requires an explicit reviewed configuration: " + name);
		if (name.startsWith("CARGO_UNSTABLE_")) fail("unstable Cargo environment is unsupported: " + name);
		if (name.startsWith("CARGO_BUILD_") && !buildKeys.includes(name.slice(12).toLowerCase().replaceAll("_", "-")))
			fail("unsupported Cargo build environment " + name);
		const targetKey = /^CARGO_TARGET_(.+)_(LINKER|RUNNER|RUSTFLAGS|RUSTDOCFLAGS)$/.exec(name);
		if (name.startsWith("CARGO_TARGET_") && name !== "CARGO_TARGET_DIR" && !targetKey)
			fail("unsupported Cargo target environment " + name);
		if (targetKey?.[2] === "RUNNER") fail("Cargo target runner is unsupported: " + name);
		if (targetKey?.[2] === "LINKER" && targetKey[1] === host.toUpperCase().replaceAll("-", "_"))
			fail("Cargo host linker is unsupported: " + name);
		if (name === "CARGO_ENCODED_RUSTFLAGS" || name === "CARGO_ENCODED_RUSTDOCFLAGS")
			assertReviewedRustFlags(
				value ? value.split("\x1f") : [],
				name.includes("RUSTDOCFLAGS") ? "rustdocflags" : "rustflags",
				target,
			);
		else if (
			["RUSTFLAGS", "RUSTDOCFLAGS", "CARGO_BUILD_RUSTFLAGS", "CARGO_BUILD_RUSTDOCFLAGS"].includes(name) ||
			targetKey?.[2] === "RUSTFLAGS" ||
			targetKey?.[2] === "RUSTDOCFLAGS"
		)
			assertReviewedRustFlags(
				value,
				name.includes("RUSTDOCFLAGS") ? "rustdocflags" : "rustflags",
				targetKey ? targetKey[1].toLowerCase().replaceAll("_", "-") : target,
			);
	}
}

async function nativeDependencies(
	context: AdapterContext,
	config: Configuration,
	target: string,
	host: string,
	rustc: string,
	graph: MetadataPackage[],
	roots: ToolRoot[],
	executables: readonly string[],
): Promise<AdapterResult> {
	const build = table(config.values.build);
	const targets = table(config.values.target);
	if (Object.keys(targets).some((key) => key.startsWith("cfg(")))
		fail("cfg-selected Cargo linker/rustflags configuration requires an explicit supported target closure");
	const targetConfig = table(targets[target]);
	const targetKey = target.toUpperCase().replaceAll("-", "_");
	const drivers: Record<string, string | readonly string[]> = { "rust-compiler": rustc };
	const environmentLinker = context.effectiveEnv[`CARGO_TARGET_${targetKey}_LINKER`];
	const configuredLinker = string(targetConfig.linker, "Cargo linker");
	const linker = environmentLinker ?? configuredLinker;
	drivers.linker = linker
		? linker.includes(path.sep)
			? environmentLinker !== undefined
				? path.resolve(context.cwd, linker)
				: configuredPath(context, config, `target.${target}.linker`, linker)
			: linker
		: target.includes("apple-darwin") || target.includes("linux")
			? "cc"
			: "rust-lld";
	if (
		target !== host &&
		graph.some((pkg) => pkg.attestationHost || pkg.targets.some((item) => item.kind.includes("custom-build")))
	)
		fail("cross-target host linker requires a distinct host context");
	const nativeDirectories = graph
		.filter(
			(pkg) =>
				pkg.targets.some((item) => item.kind.includes("custom-build")) &&
				pkg.dependencies.some((dep) => dep.kind === "build" && dep.name === "cc"),
		)
		.map((pkg) => path.dirname(pkg.manifest_path));
	if (!nativeDirectories.length) nativeDirectories.push(context.cwd);
	for (const variable of ["CFLAGS", "CXXFLAGS", "LDFLAGS"]) {
		const value = targetEnvironment(context.effectiveEnv, variable, target, host);
		if (!value) continue;
		if (context.effectiveEnv.CC_SHELL_ESCAPED_FLAGS) fail("shell-escaped cc flags require a supported token parser");
		await assertBoundNativeFlags(value.split(/\s+/).filter(Boolean), roots, nativeDirectories);
	}
	const flags: string[] = [];
	for (const [key, environment, role] of [
		["rustc-wrapper", "RUSTC_WRAPPER", "rust-wrapper"],
		["rustc-workspace-wrapper", "RUSTC_WORKSPACE_WRAPPER", "workspace-wrapper"],
	]) {
		const environmentWrapper =
			context.effectiveEnv[environment] ??
			context.effectiveEnv[`CARGO_BUILD_${key.toUpperCase().replaceAll("-", "_")}`];
		const wrapper = environmentWrapper ?? string(build[key], key);
		if (wrapper)
			drivers[role] = wrapper.includes(path.sep)
				? environmentWrapper !== undefined
					? path.resolve(context.cwd, wrapper)
					: configuredPath(context, config, `build.${key}`, wrapper)
				: wrapper;
	}
	let native = false;
	const additionalDiscovery: ToolDiscovery[] = [];
	const absenceExecutables: string[] = [];
	const packagesById = new Map(graph.map((pkg) => [pkg.id, pkg]));
	const nativeProviders = new Set<string>();
	const forwardedProviders = new Map<string, string>();
	const checkedHelpers = new Set<string>();
	for (const pkg of graph) {
		const buildTargets = pkg.targets.filter((item) => item.kind.includes("custom-build"));
		let inactiveGit = false;
		if (pkg.name === "serde_derive_internals" && !buildTargets.length) {
			const cfg = await context.probe([rustc, "--print", "cfg", "--target", pkg.attestationHost ? host : target]);
			additionalDiscovery.push(cfg.identity);
			inactiveGit = !probeText(cfg).split(/\r?\n/).includes("serde_build_from_git");
		}
		await assertNoPackageLinkDirectives(pkg, roots, true, target, true, buildTargets.length > 0, inactiveGit);
		for (const item of buildTargets) {
			const source = await readText(item.src_path);
			const reviewed = await reviewedBuildScript(pkg, source, target);
			if (pkg.links && (Object.hasOwn(targetConfig, pkg.links) || Object.hasOwn(table(targets[host]), pkg.links)))
				fail("Cargo links override requires a supported native closure in " + pkg.name);
			const usesCC = pkg.dependencies.some((dep) => dep.kind === "build" && dep.name === "cc");
			if (!reviewed && !usesCC) fail("unreviewed build-script process/input closure in " + pkg.name);
			if (reviewed) await assertReviewedBuildHelpers(pkg, packagesById, checkedHelpers);
			if (usesCC) {
				if (reviewed !== "native") fail(`unresolved native build-script compiler selection in ${pkg.name}`);
				if (pkg.name === "blst" && !(await exists(path.join(path.dirname(pkg.manifest_path), "blst"))))
					fail("blst external source fallback requires an explicit source closure");
				if (
					pkg.name === "ring" &&
					(context.effectiveEnv.RING_PREGENERATE_ASM !== undefined ||
						(await exists(path.join(path.dirname(pkg.manifest_path), ".git"))))
				)
					fail("ring source generation requires an unsupported generator closure");
				native = true;
				nativeProviders.add(pkg.id);
				if (pkg.name === "aws-lc-sys") {
					await awsLCSelection(context, pkg, target, host, roots, drivers, flags, additionalDiscovery);
				}
				continue;
			} else if (reviewed === "compiler") {
				if (pkg.name === "libc") {
					for (const command of ["freebsd-version", "emcc"])
						await bindOptionalProcessAbsence(
							context,
							source,
							command,
							path.dirname(pkg.manifest_path),
							rustc,
							absenceExecutables,
							additionalDiscovery,
						);
				}
				continue;
			} else if (reviewed === "framework") {
				await assertNoPackageLinkDirectives(pkg, roots, true, target);
				continue;
			} else if (reviewed === "metadata") {
				const features = pkg.attestationFeatures || [];
				const name = features.includes("fips")
					? "aws-lc-fips-sys"
					: features.includes("aws-lc-sys")
						? "aws-lc-sys"
						: undefined;
				const providers = (pkg.attestationDependencies || [])
					.map((id) => packagesById.get(id))
					.filter((provider): provider is MetadataPackage => provider?.name === name && Boolean(provider.links));
				if (!name || providers.length !== 1) fail(`unresolved native linkage in ${pkg.name}`);
				forwardedProviders.set(pkg.id, providers[0].id);
				await assertNoPackageLinkDirectives(pkg, roots, true, target);
			}
		}
	}
	const visiting = new Set<string>();
	function requireNativeProvider(id: string): void {
		if (nativeProviders.has(id)) return;
		if (visiting.has(id)) fail("cyclic native metadata forwarding dependency");
		const provider = forwardedProviders.get(id);
		if (!provider) fail("native metadata provider has no supported compiler/header/library closure");
		visiting.add(id);
		requireNativeProvider(provider);
		visiting.delete(id);
		nativeProviders.add(id);
	}
	for (const id of forwardedProviders.keys()) requireNativeProvider(id);
	if (native) {
		if (
			target !== host &&
			!target.includes("apple-darwin") &&
			!targetEnvironment(context.effectiveEnv, "CC", target, host)
		)
			fail(`unresolved cross-target cc selection ${target}`);
		await ccDriver(
			context,
			targetEnvironment(context.effectiveEnv, "CC", target, host) || "cc",
			"compiler",
			drivers,
			flags,
		);
		await ccDriver(
			context,
			targetEnvironment(context.effectiveEnv, "AR", target, host) || "ar",
			"archiver",
			drivers,
			flags,
		);
		const cflags = targetEnvironment(context.effectiveEnv, "CFLAGS", target, host);
		if (cflags) {
			if (context.effectiveEnv.CC_SHELL_ESCAPED_FLAGS) fail("shell-escaped cc flags require a supported token parser");
			flags.push(...cflags.split(/\s+/).filter(Boolean));
		}
		if (Object.keys(context.effectiveEnv).some((name) => name.startsWith("CXX") && context.effectiveEnv[name]))
			await ccDriver(
				context,
				targetEnvironment(context.effectiveEnv, "CXX", target, host) || "c++",
				"cxx",
				drivers,
				flags,
			);
		const fallback = drivers["rust-wrapper"];
		if (
			!drivers["compiler-wrapper"] &&
			typeof fallback === "string" &&
			["sccache", "cachepot", "buildcache"].includes(path.basename(fallback))
		)
			drivers["compiler-wrapper"] = fallback;
	}
	await assertBoundNativeFlags(flags, roots, nativeDirectories);
	const result = await context.native(
		absenceExecutables.length ? [...executables, ...absenceExecutables] : executables,
		{ target, host, drivers, flags, sdk: context.effectiveEnv.SDKROOT },
	);
	roots.push(
		...result.roots.map((root) => ({
			...root,
			label: `native/${root.label.replace(/^drivers\//, "").replace(/^non-system-libraries\//, "libraries/")}`,
		})),
	);
	return { ...result, discovery: [...additionalDiscovery, ...(result.discovery || [])] };
}

type RustRuntime = {
	cargo: string;
	rustc: string;
	sysroot: string;
	host: string;
	env?: Record<string, string>;
	nativeExecutables?: string[];
};
async function kaniContext(
	context: AdapterContext,
	roots: ToolRoot[],
	discovery: ToolDiscovery[],
): Promise<RustRuntime> {
	const launcher = await context.resolveCommand("cargo-kani");
	const cargoHome =
		context.effectiveEnv.CARGO_HOME || (context.effectiveEnv.HOME && path.join(context.effectiveEnv.HOME, ".cargo"));
	if (!cargoHome) fail("Kani requires declared CARGO_HOME or HOME");
	const homeBin = path.join(path.resolve(context.cwd, cargoHome), "bin");
	const search = context.effectiveEnv.PATH === undefined ? [] : context.effectiveEnv.PATH.split(path.delimiter);
	const homeSelector = context.effectiveEnv.CARGO_HOME || context.effectiveEnv.HOME || "";
	if ([homeSelector, ...search].some((directory) => directory.split(path.sep).includes("..")))
		fail("parent-traversing Cargo subcommand search paths are unsupported");
	const homeComponents = homeBin
		.split(path.sep)
		.filter((part) => part && part !== ".")
		.join(path.sep);
	// Cargo preserves an explicit home-bin position in PATH instead of prepending it.
	if (
		!search.some(
			(directory) =>
				path.isAbsolute(directory) &&
				directory
					.split(path.sep)
					.filter((part) => part && part !== ".")
					.join(path.sep) === homeComponents,
		)
	)
		search.unshift(homeBin);
	let selectedLauncher: string | undefined;
	for (const directory of search) {
		const candidate = path.resolve(context.cwd, directory, "cargo-kani");
		try {
			const stat = await fs.stat(candidate);
			if (stat.isFile() && stat.mode & 0o111) {
				selectedLauncher = (await context.resolveCommand(candidate)).realpath;
				break;
			}
		} catch (error) {
			if (!["ENOENT", "ENOTDIR", "EACCES"].includes((error as NodeJS.ErrnoException).code || "")) throw error;
		}
	}
	if (selectedLauncher !== launcher.realpath) fail("Cargo-selected cargo-kani differs from the bound PATH launcher");
	const installationFile = path.join(path.resolve(context.cwd, cargoHome), ".crates2.json");
	const installations = parseJSON(await fs.readFile(installationFile)) as {
		installs?: Record<string, { bins?: string[] }>;
	};
	const installed = Object.entries(installations.installs || {}).filter(
		([key, value]) => key.startsWith("kani-verifier ") && value.bins?.includes("cargo-kani"),
	);
	if (installed.length !== 1) fail("Kani launcher installation version is ambiguous");
	const version = /^kani-verifier ([^ ]+) \(/.exec(installed[0][0])?.[1];
	if (!version || !/^\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?$/.test(version))
		fail("unsupported Kani installation version");
	const distribution = context.effectiveEnv.KANI_HOME
		? path.resolve(context.cwd, context.effectiveEnv.KANI_HOME)
		: context.effectiveEnv.HOME
			? path.join(context.effectiveEnv.HOME, ".kani", `kani-${version}`)
			: fail("Kani distribution requires declared HOME");
	// Read the existing installed distribution before invoking the launcher. A
	// missing distribution must never enter Kani's first-time setup path.
	const pinned = (await readText(path.join(distribution, "rust-toolchain-version"))).trim();
	if (!/^[A-Za-z0-9._-]+$/.test(pinned)) fail("invalid Kani pinned toolchain");
	const sysroot = await requiredReal(path.join(distribution, "toolchain"));
	if (path.basename(sysroot) !== pinned) fail("Kani toolchain symlink disagrees with installed pin");
	const rustc = await requiredReal(path.join(sysroot, "bin", "rustc"));
	const cargo = await requiredReal(path.join(sysroot, "bin", "cargo"));
	const expected = (await readText(path.join(distribution, "rustc-version"))).trim();
	const probe = async (command: string[], env?: Record<string, string>) => {
		const result = await context.probe(command, env ? { env } : undefined);
		discovery.push(result.identity);
		return probeText(result).trim();
	};
	const actual = await probe([rustc, "--version"]);
	if (actual !== expected) fail("Kani compiler differs from its pinned distribution compiler");
	const actualSysroot = await requiredReal(await probe([rustc, "--print", "sysroot"]));
	if (actualSysroot !== sysroot) fail("Kani pinned compiler selects a different sysroot");
	const host = /^host: (.+)$/m.exec(await probe([rustc, "-vV"]))?.[1];
	if (!host) fail("Kani compiler did not identify its host");
	for (const filename of [
		"bin/kani-driver",
		"bin/kani-compiler",
		"bin/cbmc",
		"bin/goto-cc",
		"bin/goto-instrument",
		"bin/goto-analyzer",
		"bin/kissat",
		"lib",
		"library",
		"no_core",
		"playback",
	])
		await requiredReal(path.join(distribution, filename));
	roots.push(
		{ label: "distribution", path: await requiredReal(distribution) },
		{ label: "sysroot", path: sysroot, exclude: ["share/doc", "share/man", "share/zsh", "lib/rustlib/src"] },
		{ label: "config/kani-launcher", path: launcher.realpath },
		{ label: "config/kani-installation", path: installationFile },
		{ label: "backend", path: path.join(distribution, "bin", "cbmc") },
		{ label: "solver", path: path.join(distribution, "bin", "kissat") },
	);
	const launchVersion = await probe([launcher.invoked, "--version"]);
	if (!launchVersion.includes(version)) fail("Kani launcher version disagrees with installed distribution");
	await probe([path.join(distribution, "bin", "cbmc"), "--version"]);
	await probe([path.join(distribution, "bin", "kissat"), "--version"]);
	const env = {
		...context.effectiveEnv,
		RUSTUP_TOOLCHAIN: pinned,
		RUSTC: rustc,
		PATH: `${path.join(sysroot, "bin")}${path.delimiter}${context.effectiveEnv.PATH || ""}`,
	};
	const nativeExecutables = [
		cargo,
		launcher.realpath,
		...["kani-driver", "kani-compiler", "cbmc", "goto-cc", "goto-instrument", "goto-analyzer", "kissat"].map((name) =>
			path.join(distribution, "bin", name),
		),
	];
	return { cargo, rustc, sysroot, host, env, nativeExecutables };
}

async function cacheNamespaces(
	context: AdapterContext,
	selected: Selection,
	config: Configuration,
	workspace: string,
	metadataTarget: string,
	selectedTarget: string | undefined,
	kani: boolean,
	roots: ToolRoot[],
): Promise<CacheNamespaceSelection[]> {
	const build = table(config.values.build);
	const configured = string(build["target-dir"], "build.target-dir");
	const target = selected.targetDir
		? path.resolve(context.cwd, selected.targetDir)
		: context.effectiveEnv.CARGO_TARGET_DIR
			? path.resolve(context.cwd, context.effectiveEnv.CARGO_TARGET_DIR)
			: configured
				? configuredPath(context, config, "build.target-dir", configured)
				: metadataTarget;
	const buildDirValue = context.effectiveEnv.CARGO_BUILD_BUILD_DIR ?? string(build["build-dir"], "build.build-dir");
	const expand = (value: string): string =>
		value
			.replaceAll("{workspace-root}", workspace)
			.replaceAll(
				"{cargo-cache-home}",
				context.effectiveEnv.CARGO_HOME ||
					(context.effectiveEnv.HOME
						? path.join(context.effectiveEnv.HOME, ".cargo")
						: fail("Cargo build-dir requires CARGO_HOME")),
			);
	const buildDir = buildDirValue ? configuredPath(context, config, "build.build-dir", expand(buildDirValue)) : target;
	if (/[{}]/.test(buildDir)) fail("unsupported Cargo build directory template");
	const profile = ["test", "dev"].includes(selected.profile)
		? "debug"
		: selected.profile === "bench"
			? "release"
			: selected.profile;
	const namespaces: CacheNamespaceSelection[] = [
		{ role: "cargo-target", kind: "selected-path", path: await canonicalNamespace(target) },
		{ role: "cargo-build", kind: "selected-path", path: await canonicalNamespace(buildDir) },
		{
			role: "cargo-incremental",
			kind: "selected-path",
			path: await canonicalNamespace(
				path.join(buildDir, ...(selectedTarget ? [selectedTarget] : []), profile, "incremental"),
			),
		},
	];
	if (kani)
		namespaces.push({
			role: "kani-work",
			kind: "selected-path",
			path: await canonicalNamespace(path.join(target, "kani")),
		});
	const wrappers = [
		context.effectiveEnv.RUSTC_WRAPPER ??
			context.effectiveEnv.CARGO_BUILD_RUSTC_WRAPPER ??
			string(build["rustc-wrapper"], "rustc-wrapper"),
		context.effectiveEnv.RUSTC_WORKSPACE_WRAPPER ??
			context.effectiveEnv.CARGO_BUILD_RUSTC_WORKSPACE_WRAPPER ??
			string(build["rustc-workspace-wrapper"], "rustc-workspace-wrapper"),
		...Object.entries(context.effectiveEnv)
			.filter(([name]) => /^(?:(?:HOST|TARGET)_)?(?:CC|CXX)(?:_|$)|^AWS_LC_SYS_(?:CC|CXX)(?:_|$)/.test(name))
			.map(([, value]) => value),
	].filter((x): x is string => Boolean(x));
	for (const wrapper of wrappers) {
		const executable = path.basename(wrapper.trim().split(/\s+/)[0]);
		if (executable === "sccache") {
			if (
				context.effectiveEnv.SCCACHE_BUCKET ||
				context.effectiveEnv.SCCACHE_REDIS ||
				context.effectiveEnv.SCCACHE_MEMCACHED ||
				context.effectiveEnv.SCCACHE_GCS_BUCKET ||
				context.effectiveEnv.SCCACHE_AZURE_CONNECTION_STRING ||
				context.effectiveEnv.SCCACHE_SERVER_UDS
			)
				fail("remote/server sccache namespace requires an incorporated cache contract");
			const home = context.effectiveEnv.HOME;
			if (!home && (!context.effectiveEnv.SCCACHE_DIR || !context.effectiveEnv.SCCACHE_CONF))
				fail("sccache cache/config namespace needs declared HOME or explicit SCCACHE_DIR/SCCACHE_CONF");
			const configFile =
				context.effectiveEnv.SCCACHE_CONF ||
				(process.platform === "darwin"
					? path.join(home!, "Library", "Application Support", "Mozilla.sccache", "config")
					: path.join(context.effectiveEnv.XDG_CONFIG_HOME || path.join(home!, ".config"), "sccache", "config"));
			let diskDirectory: string | undefined;
			if (await exists(configFile)) {
				roots.push({ label: "config/sccache", path: await requiredReal(configFile) });
				const parsed = parseCargoTOML(await readText(configFile));
				if (Object.keys(table(parsed.cache)).some((key) => key !== "disk") || parsed.dist)
					fail("remote/distributed sccache configuration requires an incorporated cache contract");
				diskDirectory = string(table(table(parsed.cache).disk).dir, "sccache cache.disk.dir");
			}
			const directory =
				context.effectiveEnv.SCCACHE_DIR ||
				diskDirectory ||
				(process.platform === "darwin"
					? path.join(home!, "Library", "Caches", "Mozilla.sccache")
					: path.join(context.effectiveEnv.XDG_CACHE_HOME || path.join(home!, ".cache"), "sccache"));
			if (!namespaces.some((item) => item.role === "compiler-cache"))
				namespaces.push({
					role: "compiler-cache",
					kind: "selected-path",
					path: await canonicalNamespace(path.resolve(context.cwd, directory)),
				});
		} else if (["ccache", "cachepot", "buildcache", "distcc", "icecc"].includes(executable))
			fail(`unresolved compiler-cache namespace for ${executable}`);
	}
	return namespaces;
}

export async function discoverRustAdapter(context: AdapterContext): Promise<AdapterResult> {
	const locator = context.declaration.locator;
	if (locator.mode !== "adapter" || !["cargo-toolchain", "kani-toolchain"].includes(locator.value))
		fail("incorrect Rust adapter family");
	const selected = selection(context.subject);
	const kani = locator.value === "kani-toolchain";
	if (kani && selected.operation !== "kani") fail("Kani adapter requires a cargo kani subject");
	if (!kani && selected.operation === "kani") fail("cargo kani requires the pinned Kani adapter");
	const roots: ToolRoot[] = [];
	const discovery: ToolDiscovery[] = [];
	const config = await configuration(context, selected);
	roots.push(...config.roots);
	const runtime = kani
		? await kaniContext(context, roots, discovery)
		: await rustupSelection(context, selected, roots, discovery);
	let rustc = runtime.rustc;
	const environmentRustc = context.effectiveEnv.RUSTC ?? context.effectiveEnv.CARGO_BUILD_RUSTC;
	const configuredRustc = environmentRustc ?? string(table(config.values.build).rustc, "build.rustc");
	if (!kani && configuredRustc) {
		rustc = (
			await context.resolveCommand(
				configuredRustc.includes(path.sep)
					? environmentRustc !== undefined
						? path.resolve(context.cwd, configuredRustc)
						: configuredPath(context, config, "build.rustc", configuredRustc)
					: configuredRustc,
			)
		).realpath;
		const result = await context.probe([rustc, "--print", "sysroot"]);
		discovery.push(result.identity);
		runtime.sysroot = await requiredReal(probeText(result).trim());
		const version = await context.probe([rustc, "-vV"]);
		discovery.push(version.identity);
		runtime.host = /^host: (.+)$/m.exec(probeText(version))?.[1] || fail("configured rustc did not identify its host");
	}
	if (!kani)
		roots.push(
			{ label: "cargo", path: runtime.cargo },
			{ label: "rustc", path: rustc },
			{ label: "sysroot", path: runtime.sysroot, exclude: ["share/doc", "share/man", "share/zsh", "lib/rustlib/src"] },
		);
	else roots.push({ label: "config/pinned-cargo", path: runtime.cargo }, { label: "config/pinned-rustc", path: rustc });
	const selectedTarget =
		selected.target ?? context.effectiveEnv.CARGO_BUILD_TARGET ?? table(config.values.build).target;
	if (selectedTarget !== undefined && (typeof selectedTarget !== "string" || !/^[A-Za-z0-9._-]+$/.test(selectedTarget)))
		fail("unsupported Cargo target selection");
	const targetValue = typeof selectedTarget === "string" ? selectedTarget : runtime.host;
	assertReviewedCargoConfiguration(context, config, targetValue, runtime.host);
	if (kani && selected.solver && selected.solver !== "kissat")
		fail(`solver ${selected.solver} is not the installed pinned Kani solver selection`);
	if (selected.runtimeOnly) {
		const native = await nativeDependencies(
			context,
			config,
			targetValue,
			runtime.host,
			rustc,
			[],
			roots,
			runtime.nativeExecutables ?? [runtime.cargo],
		);
		return {
			roots,
			packages: [],
			discovery: [...discovery, ...(native.discovery || [])],
			sdk: native.sdk ?? null,
			cacheNamespaces: [],
		};
	}
	const env = kani ? runtime.env! : { ...context.effectiveEnv, RUSTC: rustc };
	const graph = await applicationGraph(context, selected, runtime.cargo, env, targetValue, roots, discovery);
	const namespaces = await cacheNamespaces(
		context,
		selected,
		config,
		graph.metadata.workspace_root,
		graph.metadata.target_directory,
		typeof selectedTarget === "string" ? selectedTarget : undefined,
		kani,
		roots,
	);
	for (const root of roots)
		if (root.label.startsWith("packages/")) {
			const directory = await requiredReal(root.path);
			const generated = [...(root.exclude || [])];
			for (const namespace of namespaces)
				if (namespace.kind === "selected-path" && beneath(directory, namespace.path)) {
					const relative = path.relative(directory, namespace.path).split(path.sep).join("/");
					if (!relative) fail("generated cache namespace equals an immutable package source root");
					if (!generated.includes(relative)) generated.push(relative);
				}
			root.exclude = generated;
		}
	const native = await nativeDependencies(
		context,
		config,
		targetValue,
		runtime.host,
		rustc,
		graph.selectedPackages,
		roots,
		runtime.nativeExecutables ?? [runtime.cargo],
	);
	return {
		roots,
		packages: graph.packages,
		discovery: [...discovery, ...(native.discovery || [])],
		sdk: native.sdk ?? null,
		cacheNamespaces: namespaces,
	};
}
