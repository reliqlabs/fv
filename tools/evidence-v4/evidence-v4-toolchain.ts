import * as fs from "node:fs/promises";
import * as path from "node:path";
import * as os from "node:os";
import { fileURLToPath } from "node:url";
import { D, H, parseJSON, utf8Compare, validateToolIdentity } from "./evidence-v4-model";
import type {
	BuildCacheIdentity,
	Cwd,
	Hash,
	Policy,
	Recipe,
	ToolDeclaration,
	ToolDiscovery,
	ToolFile,
	ToolIdentity,
} from "./evidence-v4-model";
import type { NativeSession } from "./evidence-v4-native";
import {
	ELFReader,
	ToolHasher,
	canonicalToolPath,
	isRustupProxy,
	inside,
	packageRoots,
	probeJSON,
	probeText,
	parseMachOLoadCommands,
	readPackage,
	resolvePackage,
} from "./evidence-v4-toolchain-common";
import type { LinuxELF } from "./evidence-v4-toolchain-common";
import type {
	AdapterContext,
	AdapterResult,
	CacheNamespaceSelection,
	NativeAdapterOptions,
	ProbeResult,
	ToolRoot,
} from "./evidence-v4-toolchain-common";
import { discoverRustAdapter } from "./evidence-v4-toolchain-rust";
import { identifyQuint, identifyLean } from "./evidence-v4-toolchain-proof";
import { resolvePointer, safeSourcePath } from "./evidence-v4-policy";

export type ToolchainSessionOptions = {
	root: string;
	policy: Policy;
	env: Record<string, string>;
	session: NativeSession;
	signal?: AbortSignal;
	implementationFiles?: readonly string[];
};
export type ToolchainSession = {
	capture(ids?: readonly string[]): Promise<ToolIdentity[]>;
	revalidate(ids?: readonly string[]): Promise<ToolIdentity[]>;
	buildCache(recipe: Recipe): Promise<BuildCacheIdentity>;
	implementationHash(): Promise<Hash>;
	resolveCommand(command: string, cwd?: string): Promise<{ invoked: string; realpath: string }>;
	assertCommandBound(command: readonly string[], cwd: string, ids: readonly string[]): Promise<void>;
	sourceRequirements(recipe: Recipe): Promise<{
		directories: string[];
		files: string[];
		inputDirectories: string[];
		excludedPaths: string[];
	}>;
};

async function packageDirectory(file: string): Promise<string> {
	let directory = path.dirname(file);
	for (;;) {
		try {
			await fs.access(path.join(directory, "package.json"));
			return directory;
		} catch (error) {
			if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
		}
		const parent = path.dirname(directory);
		if (parent === directory) throw new Error(`No installed package for ${file}`);
		directory = parent;
	}
}
async function canonicalNamespace(value: string): Promise<string> {
	let current = path.resolve(value),
		suffix: string[] = [];
	for (;;) {
		try {
			return path.join(await canonicalToolPath(current), ...suffix);
		} catch (error) {
			if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
		}
		const parent = path.dirname(current);
		if (parent === current) throw new Error(`Cannot resolve cache namespace: ${value}`);
		suffix.unshift(path.basename(current));
		current = parent;
	}
}

function pnpmLockMappings(bytes: string): Record<string, any> {
	const root: Record<string, any> = {},
		stack: { indent: number; value: Record<string, any> }[] = [{ indent: -1, value: root }];
	for (const line of bytes.split(/\r?\n/u)) {
		if (!line.trim() || line.trimStart().startsWith("#") || line.trimStart().startsWith("- ")) continue;
		const match = /^( *)(?:'([^']*)'|"([^"]*)"|([^:]+)): *(.*)$/u.exec(line);
		if (!match) throw new Error("Unsupported pnpm lock mapping syntax");
		const indent = match[1].length,
			key = match[2] ?? match[3] ?? match[4],
			raw = match[5];
		if (indent % 2 !== 0 || /[&*]|^!/u.test(raw)) throw new Error("Unsupported pnpm lock alias/tag");
		while (stack[stack.length - 1].indent >= indent) stack.pop();
		const parent = stack[stack.length - 1].value;
		if (Object.prototype.hasOwnProperty.call(parent, key)) throw new Error("Duplicate pnpm lock key");
		if (!raw || raw === "{}") {
			const child: Record<string, any> = {};
			parent[key] = child;
			stack.push({ indent, value: child });
		} else
			parent[key] =
				raw.startsWith("'") && raw.endsWith("'") ? raw.slice(1, -1) : raw.startsWith('"') ? JSON.parse(raw) : raw;
	}
	return root;
}
async function validateLockedNodePackages(
	context: AdapterContext,
	roots: readonly ToolRoot[],
	project: Record<string, any>,
): Promise<void> {
	const lock = pnpmLockMappings(await fs.readFile(path.join(context.cwd, "pnpm-lock.yaml"), "utf8"));
	if (lock.lockfileVersion !== "9.0" || !lock.snapshots || !lock.importers?.["."])
		throw new Error("Unsupported pnpm lock selection");
	const snapshots = lock.snapshots as Record<string, any>,
		importer = lock.importers["."] as Record<string, any>;
	const selectedVersion = (value: unknown): string => {
		if (typeof value !== "string") throw new Error("Missing pnpm locked dependency version");
		return value.split("(", 1)[0];
	};
	for (const [section, declared] of Object.entries(project))
		if (["dependencies", "devDependencies", "optionalDependencies"].includes(section)) {
			for (const name of Object.keys(declared as Record<string, unknown>)) {
				const installed = await resolvePackage(name, context.cwd);
				if (!installed) {
					if (section !== "optionalDependencies") throw new Error("Missing lock-selected project dependency " + name);
					continue;
				}
				const manifest = await readPackage(installed),
					entry = importer[section]?.[name];
				if (
					!entry ||
					entry.specifier !== (declared as Record<string, unknown>)[name] ||
					selectedVersion(entry.version) !== manifest.version
				)
					throw new Error("Project dependency differs from reviewed lock selection: " + name);
			}
		}
	for (const root of roots) {
		const manifest = await readPackage(root.path),
			key = manifest.name + "@" + manifest.version;
		const candidates = Object.keys(snapshots).filter((name) => name === key || name.startsWith(key + "("));
		if (candidates.length !== 1) throw new Error("Ambiguous or absent locked package snapshot: " + key);
		const snapshot = snapshots[candidates[0]];
		for (const section of ["dependencies", "optionalDependencies"])
			for (const [name, version] of Object.entries(snapshot[section] ?? {})) {
				const installed = await resolvePackage(name, root.path);
				if (!installed) {
					if (section === "dependencies") throw new Error("Missing installed locked package edge " + name);
					continue;
				}
				const dependency = await readPackage(installed);
				if (selectedVersion(version) !== dependency.version)
					throw new Error("Installed package edge differs from lock selection: " + key + " -> " + name);
			}
	}
}

async function importedNodePackages(context: AdapterContext, entryFiles: readonly string[]): Promise<string[]> {
	const host = (
		globalThis as unknown as {
			Bun: { Transpiler: new (options: { loader: string }) => { scanImports(code: string): { path: string }[] } };
		}
	).Bun;
	const extensions: Record<string, readonly string[]> = {
		".js": [".ts", ".tsx", ".js", ".jsx"],
		".jsx": [".tsx", ".ts", ".jsx", ".js"],
		".cjs": [".cts"],
		".mjs": [".mts"],
	};
	const visited = new Set<string>(),
		packages = new Set<string>();
	const visit = async (file: string): Promise<void> => {
		const real = await canonicalToolPath(file);
		if (visited.has(real)) return;
		visited.add(real);
		const imports = new host.Transpiler({ loader: /\.[cm]?tsx?$/u.test(real) ? "ts" : "js" }).scanImports(
			await fs.readFile(real, "utf8"),
		);
		for (const imported of imports) {
			if (imported.path.startsWith("node:")) continue;
			if (!imported.path.startsWith(".")) {
				const name = imported.path.startsWith("@")
					? imported.path.split("/").slice(0, 2).join("/")
					: imported.path.split("/")[0];
				const installed = await resolvePackage(name, path.dirname(real));
				if (!installed) throw new Error("Unknown Node import dependency: " + imported.path);
				packages.add(installed);
				continue;
			}
			const base = path.resolve(path.dirname(real), imported.path),
				extension = path.extname(base),
				tsParent = /\.[cm]?tsx?$/u.test(real),
				substitutions = (extensions[extension] ?? []).map((value) => base.slice(0, -extension.length) + value),
				suffixes = [".ts", ".tsx", ".jsx", ".js", ".json"].map((value) => base + value),
				candidates = [
					...new Set([
						...(tsParent ? [...substitutions, ...suffixes, base] : [base, ...substitutions, ...suffixes]),
						path.join(base, "index.ts"),
						path.join(base, "index.tsx"),
						path.join(base, "index.js"),
					]),
				];
			let selected: string | undefined;
			for (const candidate of candidates) {
				try {
					if ((await fs.stat(candidate)).isFile()) {
						if (selected) throw new Error("Ambiguous Node source import from a JavaScript parent: " + imported.path);
						selected = candidate;
						if (tsParent) break;
					}
				} catch (error) {
					if (!["ENOENT", "ENOTDIR"].includes((error as NodeJS.ErrnoException).code ?? "")) throw error;
				}
			}
			if (!selected) throw new Error("Unresolved Node source import: " + imported.path);
			if (/\.[cm]?[jt]sx?$/u.test(selected)) await visit(selected);
		}
	};
	for (const file of entryFiles) await visit(file);
	return [...packages];
}
async function nativePayloads(roots: readonly ToolRoot[]): Promise<string[]> {
	const files: string[] = [],
		seen = new Set<string>();
	const visit = async (file: string, root: ToolRoot, relative: string): Promise<void> => {
		if (root.exclude?.some((ex) => relative === ex || relative.startsWith(ex.replace(/\/$/u, "") + "/"))) return;
		const stat = await fs.lstat(file);
		if (stat.isSymbolicLink()) return;
		if (stat.isDirectory()) {
			for (const name of await fs.readdir(file))
				await visit(path.join(file, name), root, relative ? relative + "/" + name : name);
			return;
		}
		if (!stat.isFile() || stat.size < 4) return;
		const real = await canonicalToolPath(file);
		if (seen.has(real)) return;
		seen.add(real);
		const handle = await fs.open(real, "r"),
			magic = Buffer.alloc(4);
		try {
			await handle.read(magic, 0, 4, 0);
		} finally {
			await handle.close();
		}
		if (MACHO_MAGIC.includes(magic.readUInt32BE()) || magic.readUInt32BE() === 0x7f454c46) files.push(real);
	};
	for (const root of roots) await visit(await canonicalToolPath(root.path), root, "");
	return files;
}
const LINUX_SYSTEM_PREFIXES = [
	"/lib/",
	"/lib32/",
	"/lib64/",
	"/libx32/",
	"/usr/lib/",
	"/usr/lib32/",
	"/usr/lib64/",
	"/usr/libx32/",
];
const MACHO_MAGIC = [0xfeedface, 0xcefaedfe, 0xfeedfacf, 0xcffaedfe, 0xcafebabe, 0xbebafeca, 0xcafebabf, 0xbfbafeca];
function linuxSystemPath(file: string): boolean {
	return LINUX_SYSTEM_PREFIXES.some((prefix) => file.startsWith(prefix));
}
function glibcCache(bytes: Buffer): Map<string, { path: string; hwcap: bigint }[]> {
	const start = bytes.indexOf(Buffer.from("glibc-ld.so.cache1.1")),
		entries = new Map<string, { path: string; hwcap: bigint }[]>();
	if (start < 0 || os.endianness() !== "LE" || start + 48 > bytes.length)
		throw new Error("Unsupported ld.so.cache format");
	const count = bytes.readUInt32LE(start + 20),
		base = start + 48;
	if (base + count * 24 > bytes.length) throw new Error("Corrupt ld.so.cache entries");
	const text = (offset: number): string => {
		const at = start + offset,
			end = bytes.indexOf(0, at);
		if (at >= bytes.length || end < 0) throw new Error("Corrupt ld.so.cache string");
		return new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(bytes.subarray(at, end));
	};
	for (let index = 0; index < count; index++) {
		const at = base + index * 24,
			key = text(bytes.readUInt32LE(at + 4)),
			list = entries.get(key) ?? [];
		list.push({ path: text(bytes.readUInt32LE(at + 8)), hwcap: bytes.readBigUInt64LE(at + 16) });
		entries.set(key, list);
	}
	return entries;
}
async function optionalFile(file: string): Promise<Buffer | null> {
	try {
		return await fs.readFile(file);
	} catch (error) {
		if ((error as NodeJS.ErrnoException).code === "ENOENT") return null;
		throw error;
	}
}
async function linuxLinkage(context: AdapterContext, files: readonly string[]): Promise<ToolRoot[]> {
	if (context.effectiveEnv.LD_PRELOAD !== undefined || context.effectiveEnv.LD_AUDIT !== undefined)
		throw new Error("Unattested dynamic loader preload/audit selection");
	const preload = await optionalFile("/etc/ld.so.preload");
	if (preload && preload.toString("utf8").trim()) throw new Error("Unattested /etc/ld.so.preload selection");
	const reader = new ELFReader(),
		roots: ToolRoot[] = [],
		visited = new Set<string>(),
		libraryPath =
			context.effectiveEnv.LD_LIBRARY_PATH === undefined ? [] : context.effectiveEnv.LD_LIBRARY_PATH.split(/[:;]/u);
	if (libraryPath.some((entry) => !entry)) throw new Error("Unsupported current-directory LD_LIBRARY_PATH entry");
	let cache: Map<string, { path: string; hwcap: bigint }[]> | null | undefined;
	const matching = async (candidate: string, image: LinuxELF): Promise<string | null> => {
		let real: string;
		try {
			real = await canonicalToolPath(candidate);
			if (!(await fs.stat(real)).isFile()) return null;
		} catch (error) {
			if (["ENOENT", "ENOTDIR"].includes((error as NodeJS.ErrnoException).code ?? "")) return null;
			throw error;
		}
		const selected = await reader.read(real);
		return selected && selected.machine === image.machine && selected.bits === image.bits ? real : null;
	};
	const searchDirectories = async (
		directories: readonly string[],
		name: string,
		image: LinuxELF,
	): Promise<string | null> => {
		for (const directory of directories) {
			if (!directory || !path.isAbsolute(directory))
				throw new Error("Unsupported relative dynamic library search path: " + directory);
			if (!linuxSystemPath(directory + "/")) {
				try {
					await fs.access(path.join(directory, "glibc-hwcaps"));
					throw new Error("Ambiguous glibc-hwcaps selection in " + directory);
				} catch (error) {
					if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
				}
			}
			const selected = await matching(path.join(directory, name), image);
			if (selected) return selected;
		}
		return null;
	};
	const visit = async (file: string, inherited: readonly string[]): Promise<void> => {
		const real = await canonicalToolPath(file);
		if (visited.has(real)) return;
		visited.add(real);
		const image = await reader.read(real);
		if (!image) return;
		const origin = path.dirname(real),
			expand = (entry: string): string => {
				if (/\$(?:\{?(?:LIB|PLATFORM)\b)/u.test(entry)) throw new Error("Unsupported dynamic search token in " + real);
				return entry.replace(/\$(?:ORIGIN\b|\{ORIGIN\})/gu, origin);
			};
		const musl = image.interpreter !== null && path.basename(image.interpreter).startsWith("ld-musl-");
		if (image.interpreter) {
			const interpreter = await canonicalToolPath(image.interpreter);
			if (!linuxSystemPath(interpreter))
				roots.push({ label: "non-system-libraries/" + encodeURIComponent(image.interpreter), path: interpreter });
			await visit(interpreter, []);
		}
		const chain = [...(image.runpath.length ? [] : image.rpath.map(expand)), ...inherited],
			rpath = image.runpath.length ? [] : chain,
			runpath = image.runpath.map(expand);
		for (const needed of image.needed) {
			let selected: string | null = null;
			if (needed.includes("/")) {
				if (!path.isAbsolute(needed)) throw new Error("Unsupported relative DT_NEEDED path in " + real);
				selected = await matching(needed, image);
			} else if (musl) {
				const arch = path
					.basename(image.interpreter!)
					.replace(/^ld-musl-/u, "")
					.replace(/\.so\.1$/u, "");
				const configured = await optionalFile("/etc/ld-musl-" + arch + ".path");
				const system = configured
					? configured.toString("utf8").split(/[:\n]/u).filter(Boolean)
					: ["/lib", "/usr/local/lib", "/usr/lib"];
				selected = await searchDirectories(
					[...libraryPath.filter(Boolean), ...rpath, ...runpath, ...system],
					needed,
					image,
				);
			} else {
				selected = await searchDirectories([...rpath, ...libraryPath.filter(Boolean), ...runpath], needed, image);
				if (!selected) {
					if (cache === undefined) {
						const bytes = await optionalFile("/etc/ld.so.cache");
						cache = bytes ? glibcCache(bytes) : null;
					}
					const candidates: { path: string; hwcap: bigint }[] = [];
					for (const entry of cache?.get(needed) ?? []) {
						const real = await matching(entry.path, image);
						if (real) candidates.push({ path: real, hwcap: entry.hwcap });
					}
					if (candidates.some((entry) => entry.hwcap !== 0n) && new Set(candidates.map((entry) => entry.path)).size > 1)
						throw new Error("Ambiguous hardware-capability library selection: " + needed);
					selected = candidates[0]?.path ?? null;
				}
				if (!selected) {
					const triplet =
						image.machine === 62 ? "x86_64-linux-gnu" : image.machine === 183 ? "aarch64-linux-gnu" : null;
					selected = await searchDirectories(
						[
							...(triplet ? ["/lib/" + triplet, "/usr/lib/" + triplet] : []),
							...(image.bits === 64 ? ["/lib64", "/usr/lib64"] : []),
							"/lib",
							"/usr/lib",
						],
						needed,
						image,
					);
				}
			}
			if (!selected) throw new Error("Unresolved dynamic library " + needed + " from " + real);
			if (!linuxSystemPath(selected))
				roots.push({ label: "non-system-libraries/" + encodeURIComponent(needed), path: selected });
			await visit(selected, chain);
		}
	};
	for (const file of files) await visit(file, []);
	return roots;
}
async function mappedRuntimeModules(): Promise<ToolRoot[]> {
	const reader = new ELFReader(),
		roots: ToolRoot[] = [],
		seen = new Set<string>(),
		executable = await canonicalToolPath(process.execPath);
	for (const line of (await fs.readFile("/proc/self/maps", "utf8")).split("\n")) {
		const match = /^\S+ \S+ \S+ \S+ (\d+)\s+(\/.*)$/u.exec(line);
		if (!match || match[1] === "0") continue;
		const mappedPath = match[2];
		if (mappedPath.startsWith("/memfd:") || mappedPath.startsWith("/dev/")) continue;
		if (mappedPath.endsWith(" (deleted)")) throw new Error("Producer runtime maps a replaced file: " + mappedPath);
		const real = await canonicalToolPath(mappedPath);
		if (seen.has(real) || real === executable || linuxSystemPath(real)) continue;
		seen.add(real);
		if (await reader.read(real)) roots.push({ label: "runtime/mapped/" + H(Buffer.from(real)).slice(7), path: real });
	}
	return roots;
}

export async function discoverPythonAdapter(context: AdapterContext): Promise<AdapterResult> {
	if (context.subject.length !== 1) throw new Error("Python runtime subject must select one interpreter");
	assertLoaderEnvironment(context.effectiveEnv);
	const selected = await context.resolveCommand(context.subject[0]);
	const requests: {
		file?: string;
		code?: string;
		module?: string;
		cwd: string;
		ids: readonly string[];
		argv: string[];
		startup_paths: string[];
		startup: string[];
		flags: { isolated: boolean; safe_path: boolean; no_site: boolean; no_user_site: boolean };
	}[] = [];
	const pathDiscovery: ToolDiscovery[] = [];
	const importPathQuery =
		"import json,os,site,sys; print(json.dumps({'paths':sys.path,'user_site':site.getusersitepackages(),'global_sites':site.getsitepackages(),'user_allowed':(sys.prefix==sys.base_prefix or sys.base_prefix in site.PREFIXES) and (not hasattr(os,'getuid') or (os.getuid()==os.geteuid() and os.getgid()==os.getegid()))},sort_keys=True))";
	for (const command of context.commandContexts ?? []) {
		const actual = await context.resolveCommand(command.subject[0], command.cwd);
		const [actualStat, selectedStat] = await Promise.all([fs.stat(actual.realpath), fs.stat(selected.realpath)]);
		if (
			actual.realpath !== selected.realpath ||
			actualStat.dev !== selectedStat.dev ||
			actualStat.ino !== selectedStat.ino
		) {
			for (const token of command.subject.slice(1)) {
				if (token === "-m" || token === "-c" || token.endsWith(".py"))
					throw new Error("Unsupported Python command wrapper: " + command.subject[0]);
				if (token.startsWith("-")) continue;
				const target = await context.resolveCommand(token, command.cwd).catch((error) => {
					if (/^Executable (?:not found:|absent from sanitized PATH:)/u.test(error.message)) return null;
					throw error;
				});
				if (target) {
					const stat = await fs.stat(target.realpath);
					if (stat.dev === selectedStat.dev && stat.ino === selectedStat.ino)
						throw new Error("Unsupported Python command wrapper: " + command.subject[0]);
				}
			}
			if (await context.otherCommandBound?.(command)) continue;
			throw new Error("Unsupported Python command wrapper: " + command.subject[0]);
		}
		const options: string[] = [];
		let index = 1,
			switches = "";
		while (index < command.subject.length) {
			const arg = command.subject[index];
			if (arg === "-c" || arg === "-m" || arg === "--" || !arg.startsWith("-")) break;
			if (/^-[BIEsSPOuqb]+$/u.test(arg)) {
				options.push(arg);
				switches += arg;
				index++;
			} else if (arg === "-X" || arg === "-W" || /^-[XW]./u.test(arg)) {
				throw new Error("Unsupported Python interpreter selection: " + arg);
			} else throw new Error("Unsupported Python interpreter selection: " + arg);
		}
		if (command.subject[index] === "--") index++;
		const entry = command.subject[index];
		if (!entry) throw new Error("Python application entry point is absent");
		const query = await context.probe([selected.invoked, "-I", ...options, "-B", "-c", importPathQuery], {
			cwd: command.cwd,
		});
		pathDiscovery.push(query.identity);
		const metadata = probeJSON<{ paths: string[]; user_site: string; global_sites: string[]; user_allowed: boolean }>(
			query,
		);
		if (
			!Array.isArray(metadata.paths) ||
			metadata.paths.some((value) => typeof value !== "string") ||
			typeof metadata.user_site !== "string" ||
			!Array.isArray(metadata.global_sites) ||
			metadata.global_sites.some((value) => typeof value !== "string") ||
			typeof metadata.user_allowed !== "boolean"
		)
			throw new Error("Incomplete Python import-path metadata");
		const isolated = switches.includes("I"),
			ignoreEnvironment = isolated || switches.includes("E"),
			safe_path = isolated || switches.includes("P") || (!ignoreEnvironment && !!context.effectiveEnv.PYTHONSAFEPATH),
			flags = {
				isolated,
				safe_path,
				no_site: switches.includes("S"),
				no_user_site:
					!metadata.user_allowed ||
					isolated ||
					switches.includes("s") ||
					(!ignoreEnvironment && !!context.effectiveEnv.PYTHONNOUSERSITE),
			},
			paths = metadata.paths.map((value) => path.resolve(command.cwd, value)),
			startup: string[] = [];
		if (!ignoreEnvironment)
			for (const name of ["PYTHONHOME", "PYTHONPLATLIBDIR"])
				if (context.effectiveEnv[name] !== undefined)
					throw new Error("Cannot isolate effective Python runtime-path override: " + name);
		if (!ignoreEnvironment && context.effectiveEnv.PYTHONWARNINGS)
			throw new Error("Unsupported Python runtime selector: PYTHONWARNINGS");
		if (
			!switches.includes("S") &&
			!isolated &&
			!switches.includes("s") &&
			(ignoreEnvironment || !context.effectiveEnv.PYTHONNOUSERSITE) &&
			metadata.user_allowed &&
			(
				await fs.stat(metadata.user_site).catch((error) => {
					if ((error as NodeJS.ErrnoException).code === "ENOENT") return null;
					throw error;
				})
			)?.isDirectory()
		) {
			const userPaths = [metadata.user_site];
			for (const name of (await fs.readdir(metadata.user_site)).sort(utf8Compare)) {
				if (!name.endsWith(".pth")) continue;
				const file = path.join(metadata.user_site, name);
				startup.push(file);
				for (const line of (await fs.readFile(file, "utf8")).split(/\r?\n/u)) {
					if (!line.trim() || line.startsWith("#")) continue;
					if (/^import[ \t]/u.test(line))
						throw new Error("Cannot isolate executable Python user-site startup: " + file);
					const selected = path.resolve(metadata.user_site, line.trimEnd());
					try {
						await fs.access(selected);
						if (!userPaths.includes(selected)) userPaths.push(selected);
					} catch (error) {
						if (!["ENOENT", "ENOTDIR"].includes((error as NodeJS.ErrnoException).code ?? "")) throw error;
					}
				}
			}
			const firstGlobal = paths.findIndex((value) => metadata.global_sites.includes(value));
			paths.splice(firstGlobal < 0 ? paths.length : firstGlobal, 0, ...userPaths);
		}
		if (!ignoreEnvironment && context.effectiveEnv.PYTHONPATH !== undefined)
			paths.unshift(
				...context.effectiveEnv.PYTHONPATH.split(path.delimiter).map((value) => path.resolve(command.cwd, value)),
			);
		const common = { cwd: command.cwd, ids: command.toolchain, startup_paths: paths, flags, startup };
		if (entry === "-c") {
			if (!command.subject[index + 1]) throw new Error("Python inline source is absent");
			requests.push({ ...common, code: command.subject[index + 1], argv: ["-c", ...command.subject.slice(index + 2)] });
		} else if (entry === "-m") {
			if (!command.subject[index + 1]) throw new Error("Python module selection is absent");
			requests.push({
				...common,
				module: command.subject[index + 1],
				argv: ["-m", ...command.subject.slice(index + 2)],
			});
		} else {
			const file = path.resolve(command.cwd, entry);
			if (!file.endsWith(".py")) throw new Error("Unsupported Python source entry: " + file);
			requests.push({ ...common, file, argv: [entry, ...command.subject.slice(index + 1)] });
		}
	}
	const code = String.raw`
import ast,hashlib,importlib.machinery,json,os,pathlib,site,sys,sysconfig
root=os.path.realpath(sys.argv[1]); requests=json.loads(sys.argv[2]); stdlib=os.path.realpath(sysconfig.get_path('stdlib')); extensions=os.path.realpath(sysconfig.get_config_var('DESTSHARED')); startup=[]; startup_hooks=set(); required=set(); seen=set(); active=set(); import_roots=[]
def within(base,p): return p==base or p.startswith(base+os.sep)
for p in sys.path:
 if p and os.path.isdir(p) and (p in site.getsitepackages() or p==site.getusersitepackages()): startup.extend(os.path.join(p,n) for n in sorted(os.listdir(p)) if n.endswith('.pth'))
for n in ('site','sitecustomize','usercustomize'):
 m=sys.modules.get(n)
 if m is not None and getattr(m,'__file__',None):
  file=os.path.realpath(m.__file__); startup.append(file)
  if n in ('sitecustomize','usercustomize'): startup_hooks.add(file)
venv=os.path.join(sys.prefix,'pyvenv.cfg')
if os.path.isfile(venv): startup.append(venv)
startup.extend(file for request in requests for file in request.get('startup',[]))
startup=set(os.path.realpath(p) for p in startup)
def standard_input(p):
 return (within(stdlib,p) and 'site-packages' not in os.path.relpath(p,stdlib).split(os.sep)) or within(extensions,p)
def external(p):
 p=os.path.realpath(p)
 if not within(root,p) and not standard_input(p) and p not in startup: required.add(p)
class MissingImport(RuntimeError):
 def __init__(self,name):
  self.module=name; super().__init__('unknown Python import dependency: '+name)
def catches_missing_import(handler,scope):
 if handler.type is None: return False
 types=handler.type.elts if isinstance(handler.type,ast.Tuple) else [handler.type]
 return any(isinstance(value,ast.Name) and value.id not in scope and value.id in ('ImportError','ModuleNotFoundError') for value in types)
def resolve(name,search,parents=None):
 parts=name.split('.')
 if parts[0] in ('tkinter','dbm'): raise RuntimeError('unsupported Python split-formula stdlib dependency: '+name)
 if name in ('pickle','_pickle','shelve','pydoc','logging.config'): raise RuntimeError('unsupported dynamic Python loader API: '+name)
 if parts[0] in sys.builtin_module_names: return None
 selected=None
 for index,part in enumerate(parts):
  selected=importlib.machinery.PathFinder.find_spec('.'.join(parts[:index+1]),search)
  if selected is None and index==0 and import_roots: selected=importlib.machinery.PathFinder.find_spec(parts[0],list(reversed(import_roots)))
  if selected is None:
   if parts[0] in sys.stdlib_module_names: return None
   if index==0: raise MissingImport(name)
   raise RuntimeError('unknown Python import dependency: '+name)
  # shortcut: transitive stdlib imports are unscanned; bind split-extension distributions before claiming startup closure.
  if index==0 and parts[0] in sys.stdlib_module_names and selected.origin and standard_input(os.path.realpath(selected.origin)): return None
  if parents is not None: parents.append(('.'.join(parts[:index+1]),selected))
  search=selected.submodule_search_locations
  if index<len(parts)-1 and search is None: raise RuntimeError('unknown Python package dependency: '+name)
 return selected

def dependency(name,search,cwd,argv,flags,project):
 parents=[]; spec=resolve(name,search,parents)
 for module,selected in parents:
  if selected.origin not in (None,'built-in','frozen'):
   external(selected.origin); visit(selected.origin,search,cwd,argv,module,flags,project)
 return spec

def visit_loaded(file,paths,cwd,argv,name,flags):
 if not file.endswith('.py'): raise RuntimeError('unsupported Python source loader target: '+file)
 directory=os.path.dirname(file); added=directory not in import_roots
 if added: import_roots.append(directory)
 try: visit(file,paths,cwd,argv,name,flags,True)
 finally:
  if added: import_roots.pop()

def from_modules(spec,names,search,cwd,argv,flags,project):
 if spec is None or spec.submodule_search_locations is None: return
 for name in names:
  if name=='*':
   if spec.origin and spec.origin.endswith('.py'):
    with open(spec.origin,encoding='utf-8') as stream: tree=ast.parse(stream.read())
    for node in tree.body:
     if isinstance(node,ast.Assign) and any(isinstance(target,ast.Name) and target.id=='__all__' for target in node.targets):
      try: exports=ast.literal_eval(node.value)
      except (ValueError,TypeError): raise RuntimeError('unresolved Python from-import export list')
      if not isinstance(exports,(list,tuple)) or any(not isinstance(item,str) for item in exports): raise RuntimeError('unresolved Python from-import export list')
      from_modules(spec,exports,search,cwd,argv,flags,project)
   continue
  selected=importlib.machinery.PathFinder.find_spec(spec.name+'.'+name,spec.submodule_search_locations)
  if selected is not None: dependency(spec.name+'.'+name,search,cwd,argv,flags,project)

UNKNOWN=object()
class PathSnapshot(list):
 __slots__=()

SYS=object(); PATHLIB=object(); OS=object(); OSPATH=object(); PATH_FACTORY=object(); IMPORTLIB=object(); IMPORT_MODULE=object(); BUILTIN_IMPORT=object(); BUILTINS=object(); IMPORT_UTIL=object(); SPEC_FACTORY=object(); MODULE_FACTORY=object(); PROJECT_INPUT=object(); FORBIDDEN=object(); REFLECTION=object(); RUNPY=object(); RUN_PATH=object()
SYS_MODULES=object(); MODULE_LOOKUP=object(); OPAQUE_MODULE=object(); LOGGING=object()
class ProjectLocation:
 def __init__(self,file): self.file=file
class LoadSpec:
 def __init__(self,file): self.file=file
class LoadedModule: pass
class LiteralArgument(str): pass
class UnknownArgv: pass
class PathMethod:
 def __init__(self,receiver,method): self.receiver=receiver; self.method=method
SAFE_SYS=('path','argv','flags','modules','version','version_info','platform','executable','prefix','base_prefix','exec_prefix','base_exec_prefix','stdout','stderr','stdin','exit','maxsize','byteorder','implementation','getdefaultencoding','getfilesystemencoding','getrecursionlimit','setrecursionlimit','exc_info','exception','warnoptions')
def module_value(module,name,paths,argv,flags):
 if module is LOGGING: return FORBIDDEN if name=='config' else UNKNOWN
 if module is SYS:
  if name not in SAFE_SYS: raise RuntimeError('unsupported Python runtime selector: sys.'+name)
  return {'path':paths,'argv':argv,'flags':flags,'modules':SYS_MODULES}.get(name,UNKNOWN)
 if module is IMPORTLIB:
  if name not in ('import_module','util'): raise RuntimeError('unsupported dynamic Python loader API: importlib.'+name)
  return IMPORT_MODULE if name=='import_module' else IMPORT_UTIL
 if module is IMPORT_UTIL:
  if name not in ('spec_from_file_location','module_from_spec'): raise RuntimeError('unsupported dynamic Python loader API: importlib.util.'+name)
  return SPEC_FACTORY if name=='spec_from_file_location' else MODULE_FACTORY
 if module is RUNPY:
  if name!='run_path': raise RuntimeError('unsupported dynamic Python loader API: runpy.'+name)
  return RUN_PATH
 if module is BUILTINS:
  if name=='__import__': return BUILTIN_IMPORT
  if name in ('exec','eval','compile'): return FORBIDDEN
  if name in ('getattr','setattr','delattr','vars'): return REFLECTION
  raise RuntimeError('unsupported Python builtin API: '+name)
 if module is FORBIDDEN: raise RuntimeError('unsupported dynamic Python loader API: '+name)
 return UNKNOWN

def project_path(value,cwd):
 if value is UNKNOWN or not isinstance(value,(str,pathlib.Path)): raise RuntimeError('unresolved Python import-path mutation')
 candidate=os.path.abspath(os.path.join(cwd,str(value)))
 real=os.path.realpath(candidate)
 if not within(root,candidate) or not within(root,real): raise RuntimeError('external Python import-path mutation: '+str(value))
 current=root
 for part in os.path.relpath(candidate,root).split(os.sep):
  if part=='.': continue
  current=os.path.join(current,part)
  if os.path.islink(current): raise RuntimeError('symlinked Python import-path mutation: '+current)
 return real

def loader_location(node,values,paths,cwd,argv,flags):
 def literal(value):
  if not isinstance(value,str) or os.path.isabs(value): raise RuntimeError('unresolved Python loader location')
  return project_path(value,cwd)
 def sibling(part):
  if isinstance(part,ast.Call) and not part.keywords:
   if expression(part.func,values,paths,cwd,argv,flags) is PATH_FACTORY and len(part.args)==1 and isinstance(part.args[0],ast.Name) and part.args[0].id=='__file__': return True
   if isinstance(part.func,ast.Attribute) and part.func.attr=='with_name' and len(part.args)==1 and isinstance(part.args[0],ast.Constant) and isinstance(part.args[0].value,str): return sibling(part.func.value)
  if isinstance(part,ast.Attribute) and part.attr=='parent': return sibling(part.value)
  if isinstance(part,ast.BinOp) and isinstance(part.op,ast.Div) and isinstance(part.right,ast.Constant) and isinstance(part.right.value,str) and not os.path.isabs(part.right.value): return sibling(part.left)
  return False
 if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id=='str' and node.func.id not in values and len(node.args)==1 and not node.keywords: return loader_location(node.args[0],values,paths,cwd,argv,flags)
 if isinstance(node,ast.Constant) and isinstance(node.value,str): return literal(node.value)
 value=expression(node,values,paths,cwd,argv,flags)
 if isinstance(value,ProjectLocation): return value.file
 if isinstance(node,ast.Name) and isinstance(value,LiteralArgument): return literal(value)
 if sibling(node) and isinstance(value,pathlib.Path): return project_path(str(value),root)
 if isinstance(node,ast.Subscript) and isinstance(node.value,ast.Attribute) and node.value.attr=='argv' and expression(node.value.value,values,paths,cwd,argv,flags) is SYS and isinstance(node.slice,ast.Constant) and node.slice.value==0 and '__loader_argv__' in values: return values['__loader_argv__']
 raise RuntimeError('unresolved Python loader location')

def expression(node,values,paths,cwd,argv,flags):
 if isinstance(node,ast.Constant): return node.value
 if isinstance(node,ast.Name): return values.get(node.id,UNKNOWN)
 if isinstance(node,(ast.List,ast.Tuple)):
  items=[expression(item,values,paths,cwd,argv,flags) for item in node.elts]
  if any(item is paths or isinstance(item,PathMethod) or any(item is module for module in (SYS,IMPORTLIB,IMPORT_UTIL,BUILTINS,RUNPY,FORBIDDEN,IMPORT_MODULE,BUILTIN_IMPORT,SPEC_FACTORY,MODULE_FACTORY,RUN_PATH,PROJECT_INPUT)) for item in items): raise RuntimeError('unsupported Python runtime-selector escape')
  return UNKNOWN if any(item is UNKNOWN for item in items) else items
 if isinstance(node,ast.UnaryOp) and isinstance(node.op,ast.USub):
  operand=expression(node.operand,values,paths,cwd,argv,flags)
  return -operand if isinstance(operand,int) and not isinstance(operand,bool) else UNKNOWN
 if isinstance(node,ast.BinOp):
  left=expression(node.left,values,paths,cwd,argv,flags); right=expression(node.right,values,paths,cwd,argv,flags)
  if isinstance(node.op,ast.Div) and isinstance(left,pathlib.Path) and isinstance(right,(str,pathlib.Path)): return left/right
  if isinstance(node.op,ast.Add) and isinstance(left,str) and isinstance(right,str): return left+right
  return UNKNOWN
 if isinstance(node,ast.Attribute):
  base=expression(node.value,values,paths,cwd,argv,flags)
  if base is LOGGING: return module_value(base,node.attr,paths,argv,flags)
  if base is OPAQUE_MODULE: raise RuntimeError('unsupported opaque Python module access')
  if base is SYS_MODULES:
   if node.attr not in ('get','pop'): raise RuntimeError('unsupported Python module registry API: '+node.attr)
   return MODULE_LOOKUP
  if base is SYS and node.attr=='argv': return values.get('__argv__',argv)
  if any(base is module for module in (SYS,IMPORTLIB,IMPORT_UTIL,BUILTINS,FORBIDDEN,RUNPY)): return module_value(base,node.attr,paths,argv,flags)
  if base is paths or isinstance(base,PathSnapshot):
   if node.attr not in ('insert','append','copy'): raise RuntimeError('unsupported Python import-path mutation: '+node.attr)
   return PathMethod(base,node.attr)
  if isinstance(base,LoadSpec):
   if node.attr=='loader': return base
   if node.attr=='exec_module': return base
   raise RuntimeError('unsupported dynamic Python loader API: '+node.attr)
  if base is PATHLIB and node.attr=='Path': return PATH_FACTORY
  if base is OS and node.attr=='path': return OSPATH
  if isinstance(base,dict) and base is flags: return base.get(node.attr,UNKNOWN)
  if isinstance(base,pathlib.Path) and node.attr in ('parent','parents','name','stem','suffix'): return getattr(base,node.attr)
  return UNKNOWN
 if isinstance(node,ast.Slice):
  bounds=[None if item is None else expression(item,values,paths,cwd,argv,flags) for item in (node.lower,node.upper,node.step)]
  if any(item is UNKNOWN or (item is not None and (not isinstance(item,int) or isinstance(item,bool))) for item in bounds) or bounds[2]==0: return UNKNOWN
  return slice(*bounds)
 if isinstance(node,ast.Subscript):
  base=expression(node.value,values,paths,cwd,argv,flags); index=expression(node.slice,values,paths,cwd,argv,flags)
  if base is SYS_MODULES: return OPAQUE_MODULE
  if base is OPAQUE_MODULE: raise RuntimeError('unsupported opaque Python module access')
  if base is UNKNOWN or index is UNKNOWN: return UNKNOWN
  if base is BUILTINS: return module_value(base,index,paths,argv,flags)
  try:
   value=base[index]
   return PathSnapshot(value) if isinstance(index,slice) and (base is paths or isinstance(base,PathSnapshot)) else value
  except (IndexError,KeyError,TypeError): return UNKNOWN
 if isinstance(node,ast.Call):
  target=expression(node.func,values,paths,cwd,argv,flags)
  if target is OPAQUE_MODULE: raise RuntimeError('unsupported opaque Python module call')
  if target is MODULE_LOOKUP:
   for argument in [*node.args,*[keyword.value for keyword in node.keywords]]: expression(argument,values,paths,cwd,argv,flags)
   return OPAQUE_MODULE
  if target is FORBIDDEN: raise RuntimeError('unsupported dynamic Python loader API')
  if isinstance(target,PathMethod):
   if not isinstance(node.func,ast.Attribute): raise RuntimeError('unsupported Python import-path method alias')
   if target.method=='copy' and not node.args and not node.keywords: return PathSnapshot(target.receiver)
   return UNKNOWN
  if target is PROJECT_INPUT:
   if node.keywords or len(node.args)!=2: raise RuntimeError('unresolved Python loader location')
   base=expression(node.args[0],values,paths,cwd,argv,flags); relative=expression(node.args[1],values,paths,cwd,argv,flags)
   if base is UNKNOWN or relative is UNKNOWN: return UNKNOWN
   if base!=pathlib.Path(root) or not isinstance(relative,str) or os.path.isabs(relative): raise RuntimeError('unresolved Python loader location')
   return ProjectLocation(project_path(relative,root))
  if target is SPEC_FACTORY:
   if node.keywords or len(node.args)!=2: raise RuntimeError('unresolved Python loader location')
   file=loader_location(node.args[1],values,paths,cwd,argv,flags)
   if not os.path.isfile(file): raise RuntimeError('Python loader target is absent: '+file)
   module=expression(node.args[0],values,paths,cwd,argv,flags)
   if not isinstance(module,str): raise RuntimeError('unresolved Python loader module name')
   effective_argv=values.get('__argv__',argv)
   visit_loaded(file,paths,cwd,effective_argv if isinstance(effective_argv,list) else [],module,flags)
   return LoadSpec(file)
  if target is RUN_PATH:
   if len(node.args)!=1 or any(keyword.arg not in ('run_name',) for keyword in node.keywords): raise RuntimeError('unsupported dynamic Python loader API: runpy.run_path')
   file=loader_location(node.args[0],values,paths,cwd,argv,flags)
   if not os.path.isfile(file): raise RuntimeError('Python loader target is absent: '+file)
   run_name=next((expression(keyword.value,values,paths,cwd,argv,flags) for keyword in node.keywords if keyword.arg=='run_name'),'<run_path>')
   if not isinstance(run_name,str): raise RuntimeError('unresolved Python loader run name')
   effective_argv=values.get('__argv__',argv)
   visit_loaded(file,paths,cwd,effective_argv if isinstance(effective_argv,list) else [],run_name,flags)
   return UNKNOWN
  if target is MODULE_FACTORY:
   if node.keywords or len(node.args)!=1 or not isinstance(expression(node.args[0],values,paths,cwd,argv,flags),LoadSpec): raise RuntimeError('unresolved Python loader module spec')
   return LoadedModule()
  if isinstance(target,LoadSpec):
   if not isinstance(node.func,ast.Attribute) or node.func.attr!='exec_module' or node.keywords or len(node.args)!=1 or not isinstance(expression(node.args[0],values,paths,cwd,argv,flags),LoadedModule): raise RuntimeError('unsupported dynamic Python loader API')
   return UNKNOWN
  if target is IMPORT_MODULE or target is BUILTIN_IMPORT:
   arguments={keyword.arg:keyword.value for keyword in node.keywords}
   name_node=node.args[0] if node.args else arguments.get('name')
   name=expression(name_node,values,paths,cwd,argv,flags) if name_node is not None else UNKNOWN
   if not isinstance(name,str): raise RuntimeError('unresolved dynamic Python import')
   if target is IMPORT_MODULE and name.startswith('.'):
    package_node=node.args[1] if len(node.args)>1 else arguments.get('package')
    package=expression(package_node,values,paths,cwd,argv,flags) if package_node is not None else UNKNOWN
    if not isinstance(package,str): raise RuntimeError('unresolved dynamic Python import package')
    level=len(name)-len(name.lstrip('.')); parts=package.split('.')
    if level>len(parts): raise RuntimeError('unresolved dynamic Python import package')
    name='.'.join(parts[:len(parts)-level+1])+name[level-1:]
   if target is BUILTIN_IMPORT:
    level_node=node.args[4] if len(node.args)>4 else arguments.get('level')
    if level_node is not None and expression(level_node,values,paths,cwd,argv,flags)!=0: raise RuntimeError('unresolved relative dynamic Python import')
   spec=dependency(name,paths,cwd,argv,flags,True)
   if target is BUILTIN_IMPORT:
    from_node=node.args[3] if len(node.args)>3 else arguments.get('fromlist')
    names=expression(from_node,values,paths,cwd,argv,flags) if from_node is not None else []
    if not isinstance(names,(list,tuple)) or any(not isinstance(item,str) for item in names): raise RuntimeError('unresolved dynamic Python import from-list')
    from_modules(spec,names,paths,cwd,argv,flags,True)
   return UNKNOWN
  args=[expression(arg,values,paths,cwd,argv,flags) for arg in node.args]
  keywords={keyword.arg:expression(keyword.value,values,paths,cwd,argv,flags) for keyword in node.keywords}
  if target is REFLECTION and args and (any(args[0] is module for module in (SYS,SYS_MODULES,OPAQUE_MODULE,IMPORTLIB,IMPORT_UTIL,BUILTINS,FORBIDDEN,paths)) or isinstance(args[0],(PathSnapshot,LoadSpec))): raise RuntimeError('unsupported reflective Python runtime selector')
  if any(any(arg is module for module in (SYS,IMPORTLIB,IMPORT_UTIL,BUILTINS,RUNPY,FORBIDDEN,IMPORT_MODULE,BUILTIN_IMPORT,SPEC_FACTORY,MODULE_FACTORY,RUN_PATH,PROJECT_INPUT)) for arg in [*args,*keywords.values()]): raise RuntimeError('unsupported Python runtime-selector escape')
  if any(arg is SYS_MODULES or arg is MODULE_LOOKUP or arg is OPAQUE_MODULE for arg in [*args,*keywords.values()]): raise RuntimeError('unsupported opaque Python module escape')
  if any(arg is paths or isinstance(arg,(PathSnapshot,PathMethod)) for arg in args) and not (isinstance(node.func,ast.Name) and node.func.id in ('list','len','tuple') and node.func.id not in values): raise RuntimeError('unsupported Python import-path escape')
  if any(arg is UNKNOWN for arg in args) or any(value is UNKNOWN for value in keywords.values()): return UNKNOWN
  target=expression(node.func,values,paths,cwd,argv,flags)
  if target is PATH_FACTORY and not keywords and len(args)<=1:
   return pathlib.Path(args[0]) if args and isinstance(args[0],(str,pathlib.Path)) else pathlib.Path('.') if not args else UNKNOWN
  if isinstance(node.func,ast.Name) and node.func.id=='list' and node.func.id not in values and len(args)==1 and not keywords and (args[0] is paths or isinstance(args[0],PathSnapshot)): return PathSnapshot(args[0])
  if isinstance(node.func,ast.Name) and node.func.id=='str' and node.func.id not in values and len(args)==1 and not keywords:
   return str(args[0]) if isinstance(args[0],(str,pathlib.Path,int)) else UNKNOWN
  if isinstance(node.func,ast.Attribute):
   base=expression(node.func.value,values,paths,cwd,argv,flags); method=node.func.attr
   if (base is paths or isinstance(base,PathSnapshot)) and method=='copy' and not args and not keywords: return PathSnapshot(base)
   if base is PATH_FACTORY and method=='cwd' and not args and not keywords: return pathlib.Path(cwd)
   if isinstance(base,pathlib.Path):
    if method in ('exists','is_dir','is_file') and not args and not keywords:
     candidate=os.path.abspath(os.path.join(cwd,str(base)))
     return getattr(pathlib.Path(project_path(candidate,cwd)),method)() if within(root,candidate) else UNKNOWN
    if method=='resolve' and not args and set(keywords)<=set(['strict']) and isinstance(keywords.get('strict',False),bool):
     return (base if base.is_absolute() else pathlib.Path(cwd)/base).resolve(strict=keywords.get('strict',False))
    if method=='absolute' and not args and not keywords: return pathlib.Path(os.path.abspath(os.path.join(cwd,str(base))))
    if method in ('joinpath','with_name','with_suffix') and not keywords and all(isinstance(arg,str) for arg in args): return getattr(base,method)(*args)
   if base is OSPATH and not keywords and all(isinstance(arg,str) for arg in args):
    if method=='join': return os.path.join(*args)
    if method=='dirname' and len(args)==1: return os.path.dirname(args[0])
    if method in ('abspath','realpath','normpath') and len(args)==1:
     value=os.path.join(cwd,args[0]) if not os.path.isabs(args[0]) else args[0]
     return getattr(os.path,method)(value)
  return UNKNOWN
 if isinstance(node,ast.Compare) and len(node.ops)==1:
  left=expression(node.left,values,paths,cwd,argv,flags); right=expression(node.comparators[0],values,paths,cwd,argv,flags)
  if left is UNKNOWN or right is UNKNOWN: return UNKNOWN
  if isinstance(node.ops[0],ast.Eq): return left==right
  if isinstance(node.ops[0],ast.NotEq): return left!=right
 for child in ast.iter_child_nodes(node):
  if isinstance(child,ast.expr):
   value=expression(child,values,paths,cwd,argv,flags)
   if value is paths or isinstance(value,(PathSnapshot,PathMethod)) or any(value is module for module in (SYS,IMPORTLIB,IMPORT_UTIL,BUILTINS,RUNPY,FORBIDDEN,IMPORT_MODULE,BUILTIN_IMPORT,SPEC_FACTORY,MODULE_FACTORY,RUN_PATH,PROJECT_INPUT)): raise RuntimeError('unsupported Python runtime-selector escape')
 return UNKNOWN

def argv_changes(node,scope,paths,cwd,argv,flags):
 selected=scope.get('__argv__',argv)
 for part in ast.walk(node):
  if isinstance(part,ast.Call) and isinstance(part.func,ast.Attribute) and expression(part.func.value,scope,paths,cwd,argv,flags) is selected and part.func.attr!='copy': return True
  targets=part.targets if isinstance(part,(ast.Assign,ast.Delete)) else [part.target] if isinstance(part,(ast.AnnAssign,ast.AugAssign)) else []
  for target in targets:
   if isinstance(target,ast.Attribute) and target.attr=='argv' and expression(target.value,scope,paths,cwd,argv,flags) is SYS: return True
   if isinstance(target,ast.Subscript) and expression(target.value,scope,paths,cwd,argv,flags) is selected: return True
 return False

def path_changes(node,scope,paths,cwd,argv,flags):
 for part in ast.walk(node):
  if isinstance(part,ast.Call):
   target=expression(part.func,scope,paths,cwd,argv,flags)
   if isinstance(target,PathMethod) and target.method!='copy': return True
  targets=part.targets if isinstance(part,(ast.Assign,ast.Delete)) else [part.target] if isinstance(part,(ast.AnnAssign,ast.AugAssign)) else []
  for target in targets:
   base=expression(target.value,scope,paths,cwd,argv,flags) if isinstance(target,(ast.Attribute,ast.Subscript)) else expression(target,scope,paths,cwd,argv,flags)
   if base is SYS and isinstance(target,ast.Attribute) and target.attr=='path': return True
   if base is paths or isinstance(base,PathSnapshot): return True
 return False


def scan(source,directory,paths=None,cwd=None,argv=None,filename=None,name='__main__',flags=None,project=True):
 paths=paths if paths is not None else [os.path.abspath(p or os.getcwd()) for p in sys.path]
 cwd=cwd or os.getcwd(); argv=argv if argv is not None else list(sys.argv)
 flags=flags or dict(isolated=bool(sys.flags.isolated),safe_path=bool(getattr(sys.flags,'safe_path',False)))
 values={'__name__':name,'__import__':BUILTIN_IMPORT,'__builtins__':BUILTINS,'exec':FORBIDDEN,'eval':FORBIDDEN,'compile':FORBIDDEN,'getattr':REFLECTION,'setattr':REFLECTION,'delattr':REFLECTION,'vars':REFLECTION}
 if filename is not None: values['__file__']=filename
 tree=ast.parse(source,filename=filename or '<inline cwd='+cwd+'>')
 parents={child:parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
 functions={node.name:node for node in tree.body if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef))}
 specializations={}
 # shortcut: helper roots and cross-module calls need a value-bound loader contract before cross-run reuse is sound.
 for function in functions.values():
  args=[arg.arg for arg in function.args.posonlyargs+function.args.args]
  for call in ast.walk(function):
   if not isinstance(call,ast.Call) or not isinstance(call.func,ast.Attribute) or call.func.attr not in ('spec_from_file_location','run_path'): continue
   location=call.args[1] if call.func.attr=='spec_from_file_location' and len(call.args)>1 else call.args[0] if call.args else None
   if not isinstance(location,ast.Name): continue
   parameter=location.id; input_name=None; root_parameter=None
   assignments=[node for node in function.body if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name) and node.targets[0].id==parameter]
   if assignments:
    assignment=assignments[0].value
    if len(assignments)!=1 or not isinstance(assignment,ast.Call) or not isinstance(assignment.func,ast.Name) or len(assignment.args)!=2 or assignment.keywords or not all(isinstance(arg,ast.Name) for arg in assignment.args): raise RuntimeError('unresolved Python loader helper location')
    input_name=assignment.func.id; root_parameter=assignment.args[0].id; parameter=assignment.args[1].id
    helper=functions.get(input_name)
    if helper is None or len(helper.body)<2: raise RuntimeError('unresolved Python loader input helper')
    helper_args=[arg.arg for arg in helper.args.args]
    first,last=helper.body[0],helper.body[-1]
    if len(helper_args)!=2 or not isinstance(first,ast.Assign) or len(first.targets)!=1 or not isinstance(first.targets[0],ast.Name) or not isinstance(first.value,ast.BinOp) or not isinstance(first.value.op,ast.Div) or not isinstance(first.value.left,ast.Name) or first.value.left.id!=helper_args[0] or not isinstance(first.value.right,ast.Name) or first.value.right.id!=helper_args[1] or not isinstance(last,ast.Return) or not isinstance(last.value,ast.Name) or last.value.id!=first.targets[0].id: raise RuntimeError('unresolved Python loader input helper')
    for guard in helper.body[1:-1]:
     if any(isinstance(part,(ast.NamedExpr,ast.Await,ast.Yield,ast.YieldFrom)) for part in ast.walk(guard)): raise RuntimeError('unresolved Python loader input helper')
     if not isinstance(guard,ast.If) or guard.orelse or not guard.body or any(not isinstance(statement,ast.Raise) for statement in guard.body): raise RuntimeError('unresolved Python loader input helper')
     for probe in ast.walk(guard.test):
      if isinstance(probe,ast.Call) and (not isinstance(probe.func,ast.Attribute) or not isinstance(probe.func.value,ast.Name) or probe.func.value.id!=first.targets[0].id or probe.func.attr not in ('is_symlink','resolve','is_file') or probe.args or probe.keywords): raise RuntimeError('unresolved Python loader input helper')
    values[input_name]=PROJECT_INPUT
   if parameter not in args or (root_parameter is not None and root_parameter not in args): raise RuntimeError('unresolved Python loader helper parameter')
   relative_index=args.index(parameter); cases=[]
   for reference in ast.walk(tree):
    if not isinstance(reference,ast.Name) or reference.id!=function.name: continue
    parent=parents.get(reference)
    if not isinstance(parent,ast.Call) or parent.func is not reference or parent.keywords or len(parent.args)!=len(args): raise RuntimeError('unsupported Python loader helper alias')
    relative=parent.args[relative_index]
    if not isinstance(relative,ast.Constant) or not isinstance(relative.value,str): raise RuntimeError('non-literal Python loader helper location')
    case={arg:LiteralArgument(value.value) if isinstance(value,ast.Constant) and isinstance(value.value,str) else value.value if isinstance(value,ast.Constant) else UNKNOWN for arg,value in zip(args,parent.args)}
    if root_parameter is not None:
     root_argument=parent.args[args.index(root_parameter)]
     if not isinstance(root_argument,ast.Name) or root_argument.id!=root_parameter: raise RuntimeError('unresolved Python loader project root')
     case[root_parameter]=pathlib.Path(root)
    cases.append(case)
   if not cases: raise RuntimeError('unresolved Python loader helper call sites')
   specializations[function]=cases
 deferred=[]
 def calls(node):
  if isinstance(node,ast.Call): yield node
  for child in ast.iter_child_nodes(node):
   if not isinstance(child,ast.stmt): yield from calls(child)
 def walk(nodes,scope,search,allow_path=True):
  for node in nodes:
   try:
    if not allow_path and not isinstance(node,ast.Try) and path_changes(node,scope,search,cwd,argv,flags): raise RuntimeError('unsupported non-straightline Python import-path mutation')
    if not isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)) and argv_changes(node,scope,search,cwd,argv,flags): scope.pop('__loader_argv__',None)
    for call in calls(node):
     target=expression(call.func,scope,search,cwd,argv,flags)
     if isinstance(target,PathMethod) and target.method!='copy' and not (isinstance(node,ast.Expr) and node.value is call): raise RuntimeError('unsupported nested Python import-path mutation')
     expression(call,scope,search,cwd,argv,flags)
    if isinstance(node,(ast.Import,ast.ImportFrom)):
     names=[alias.name for alias in node.names] if isinstance(node,ast.Import) else [node.module] if node.module else [alias.name for alias in node.names]
     standards={}
     for module in names:
      lookup=search
      if isinstance(node,ast.ImportFrom) and node.level:
       base=directory
       for _ in range(node.level-1): base=os.path.dirname(base)
       lookup=[base]
      spec=dependency(module,lookup,cwd,argv,flags,project)
      standards[module]=spec is None or spec.origin in (None,'built-in','frozen')
      if isinstance(node,ast.ImportFrom) and node.module: from_modules(spec,[alias.name for alias in node.names],lookup,cwd,argv,flags,project)
     if isinstance(node,ast.Import):
      for alias in node.names: scope[alias.asname or alias.name.split('.')[0]]={'sys':SYS,'pathlib':PATHLIB,'os':OS,'os.path':OSPATH,'importlib':IMPORTLIB,'importlib.util':IMPORT_UTIL,'importlib.machinery':FORBIDDEN,'importlib.abc':FORBIDDEN,'builtins':BUILTINS,'runpy':RUNPY,'site':FORBIDDEN,'pkgutil':FORBIDDEN,'zipimport':FORBIDDEN,'imp':FORBIDDEN,'logging':LOGGING}.get(alias.name if alias.asname else alias.name.split('.')[0],UNKNOWN) if standards[alias.name] else UNKNOWN
     elif node.module in ('sys','builtins','importlib','importlib.util','runpy','site','pkgutil','zipimport','imp','logging') and standards.get(node.module,False):
      module={'sys':SYS,'builtins':BUILTINS,'importlib':IMPORTLIB,'importlib.util':IMPORT_UTIL,'runpy':RUNPY,'site':FORBIDDEN,'pkgutil':FORBIDDEN,'zipimport':FORBIDDEN,'imp':FORBIDDEN,'logging':LOGGING}[node.module]
      for alias in node.names:
       if module is SYS and alias.name=='path': raise RuntimeError('unsupported Python import-path alias')
       scope[alias.asname or alias.name]=module_value(module,alias.name,search,argv,flags)
     elif node.module and node.module.startswith('importlib.') and standards.get(node.module,False):
      raise RuntimeError('unsupported dynamic Python loader API: '+node.module)
     elif node.module=='pathlib' and standards.get(node.module,False):
      for alias in node.names: scope[alias.asname or alias.name]=PATH_FACTORY if alias.name=='Path' else UNKNOWN
     else:
      for alias in node.names: scope[alias.asname or alias.name]=UNKNOWN
    elif isinstance(node,(ast.Assign,ast.AnnAssign)):
     value=expression(node.value,scope,search,cwd,argv,flags) if node.value else UNKNOWN
     targets=node.targets if isinstance(node,ast.Assign) else [node.target]
     for target in targets:
      if isinstance(target,ast.Name):
       if value is search: raise RuntimeError('unsupported Python import-path alias')
       scope[target.id]=value
      elif value is search or isinstance(value,(PathSnapshot,PathMethod)) or any(value is module for module in (SYS,IMPORTLIB,IMPORT_UTIL,BUILTINS,RUNPY,FORBIDDEN,IMPORT_MODULE,BUILTIN_IMPORT,SPEC_FACTORY,MODULE_FACTORY,RUN_PATH,PROJECT_INPUT)):
       if not isinstance(target,ast.Subscript): raise RuntimeError('unsupported Python import-path escape')
       receiver=expression(target.value,scope,search,cwd,argv,flags)
       if receiver is not search and not isinstance(receiver,PathSnapshot): raise RuntimeError('unsupported Python import-path escape')
       index=expression(target.slice,scope,search,cwd,argv,flags)
       if not isinstance(index,slice) or index.start not in (None,0) or index.stop is not None or index.step not in (None,1): raise RuntimeError('unsupported Python sys.path partial subscript mutation')
       receiver[index]=list(value)
      elif isinstance(target,ast.Attribute) and expression(target.value,scope,search,cwd,argv,flags) is SYS:
       if target.attr=='path': raise RuntimeError('unsupported Python sys.path assignment')
       if target.attr=='argv':
        scope['__argv__']=value if isinstance(value,list) else UnknownArgv()
        scope.pop('__loader_argv__',None)
        if isinstance(node.value,ast.List) and node.value.elts:
         try: scope['__loader_argv__']=loader_location(node.value.elts[0],scope,search,cwd,argv,flags)
         except RuntimeError: pass
       elif target.attr not in SAFE_SYS: raise RuntimeError('unsupported Python runtime selector: sys.'+target.attr)
      elif isinstance(target,ast.Subscript):
       receiver=expression(target.value,scope,search,cwd,argv,flags)
       if receiver is search or isinstance(receiver,PathSnapshot):
        index=expression(target.slice,scope,search,cwd,argv,flags)
        if not isinstance(index,slice) or index.start not in (None,0) or index.stop is not None or index.step not in (None,1): raise RuntimeError('unsupported Python sys.path partial subscript mutation')
        if value is search or isinstance(value,PathSnapshot): restored=list(value)
        elif isinstance(value,list): restored=[project_path(item,cwd) for item in value]
        else: raise RuntimeError('unresolved Python sys.path slice restoration')
        receiver[index]=restored
       elif isinstance(receiver,list):
        index=expression(target.slice,scope,search,cwd,argv,flags)
        if index is UNKNOWN or value is UNKNOWN: receiver[:]=[UNKNOWN]
        else:
         try: receiver[index]=value
         except (IndexError,TypeError,ValueError): receiver[:]=[UNKNOWN]
    elif isinstance(node,ast.Expr) and isinstance(node.value,ast.Call):
     call=node.value
     receiver=expression(call.func.value,scope,search,cwd,argv,flags) if isinstance(call.func,ast.Attribute) else UNKNOWN
     if isinstance(call.func,ast.Attribute) and isinstance(receiver,list):
      args=[expression(arg,scope,search,cwd,argv,flags) for arg in call.args]
      bounded=receiver is search or isinstance(receiver,PathSnapshot)
      if call.keywords or any(item is UNKNOWN for item in args):
       if bounded: raise RuntimeError('unresolved Python import-path/list mutation')
       receiver[:]=[UNKNOWN]; continue
      normalize=lambda item: project_path(item,cwd) if bounded else item
      if call.func.attr=='insert' and len(args)==2 and isinstance(args[0],int) and not isinstance(args[0],bool): receiver.insert(args[0],normalize(args[1]))
      elif call.func.attr=='append' and len(args)==1: receiver.append(normalize(args[0]))
      elif call.func.attr=='copy' and not args: continue
      else:
       if bounded: raise RuntimeError('unresolved Python import-path/list mutation')
       receiver[:]=[UNKNOWN]
    elif isinstance(node,(ast.AugAssign,ast.Delete)):
     for target in node.targets if isinstance(node,ast.Delete) else [node.target]:
      if isinstance(target,ast.Attribute): expression(target,scope,search,cwd,argv,flags)
     if path_changes(node,scope,search,cwd,argv,flags): raise RuntimeError('unsupported Python import-path mutation')
    elif isinstance(node,ast.If):
     condition=expression(node.test,scope,search,cwd,argv,flags)
     if isinstance(condition,bool): walk(node.body if condition else node.orelse,scope,search,allow_path)
     else:
      if path_changes(node,scope,search,cwd,argv,flags): raise RuntimeError('unresolved conditional Python import-path setup')
      walk(node.body,dict(scope),list(search),False); walk(node.orelse,dict(scope),list(search),False)
    elif isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):
     for default in [*node.args.defaults,*node.args.kw_defaults]:
      value=expression(default,scope,search,cwd,argv,flags) if default is not None else UNKNOWN
      if value is search or any(value is module for module in (SYS,IMPORTLIB,IMPORT_UTIL,BUILTINS,RUNPY,FORBIDDEN,IMPORT_MODULE,BUILTIN_IMPORT,SPEC_FACTORY,MODULE_FACTORY,RUN_PATH,PROJECT_INPUT)): raise RuntimeError('unsupported Python runtime-selector default argument')
     deferred.append((node,scope))
    elif isinstance(node,ast.ClassDef): walk(node.body,dict(scope),search,allow_path)
    elif isinstance(node,ast.Try):
     if not node.handlers:
      mutates=path_changes(node,scope,search,cwd,argv,flags)
      if mutates:
       restores=[]
       for statement in node.finalbody:
        if isinstance(statement,ast.Assign) and len(statement.targets)==1 and isinstance(statement.targets[0],ast.Subscript):
         target=statement.targets[0]; receiver=expression(target.value,scope,search,cwd,argv,flags); index=expression(target.slice,scope,search,cwd,argv,flags); value=expression(statement.value,scope,search,cwd,argv,flags)
         if receiver is search and isinstance(index,slice) and index.start is None and index.stop is None and index.step is None and isinstance(value,PathSnapshot) and list(value)==list(search): restores.append(statement); continue
        if path_changes(statement,scope,search,cwd,argv,flags): raise RuntimeError('unsupported exceptional Python import-path restoration')
       if len(restores)!=1: raise RuntimeError('unsupported exceptional Python import-path restoration')
      walk(node.body,scope,search,mutates); walk(node.orelse,scope,search,mutates); walk(node.finalbody,scope,search,mutates)
     else:
      if path_changes(node,scope,search,cwd,argv,flags): raise RuntimeError('unresolved exceptional Python import-path setup')
      body_scope=dict(scope); body_search=list(search)
      try: walk(node.body,body_scope,body_search,False)
      except MissingImport as error:
       if len(node.body)!=1 or not isinstance(node.body[0],ast.Import) or len(node.body[0].names)!=1 or node.body[0].names[0].name!=error.module: raise RuntimeError('unsupported guarded Python import absence') from error
       handler=next((handler for handler in node.handlers if catches_missing_import(handler,scope)),None)
       if handler is None: raise
       walk(handler.body,body_scope,body_search,False)
      else:
       for handler in node.handlers: walk(handler.body,dict(scope),list(search),False)
       walk(node.orelse,body_scope,body_search,False)
      walk(node.finalbody,scope,search,False)
    elif isinstance(node,(ast.For,ast.AsyncFor,ast.While,ast.With,ast.AsyncWith)):
     if path_changes(node,scope,search,cwd,argv,flags): raise RuntimeError('unsupported block Python import-path mutation')
     walk(node.body,dict(scope),list(search),False)
     if hasattr(node,'orelse'): walk(node.orelse,dict(scope),list(search),False)
   except (RuntimeError,TypeError,ValueError,OSError) as error:
    if isinstance(error,MissingImport): raise
    raise RuntimeError(f"{filename or '<inline cwd='+cwd+'>'}:{getattr(node,'lineno','?')}: {error}") from error
 walk(tree.body,values,paths)
 while deferred:
  function,outer=deferred.pop(0); local=dict(outer)
  for arg in function.args.posonlyargs+function.args.args+function.args.kwonlyargs: local[arg.arg]=UNKNOWN
  if function.args.vararg: local[function.args.vararg.arg]=UNKNOWN
  if function.args.kwarg: local[function.args.kwarg.arg]=UNKNOWN
  for case in specializations.get(function,[{}]):
   selected=dict(local); selected.update(case)
   for statement in function.body:
    if not isinstance(statement,ast.Try) and path_changes(statement,selected,paths,cwd,argv,flags): raise RuntimeError('unsupported deferred Python import-path mutation')
   function_paths=list(paths)
   walk(function.body,selected,function_paths,False)
   if function_paths!=paths: raise RuntimeError('unsupported deferred Python import-path mutation')

source_inputs={}
def visit(file,paths=None,cwd=None,argv=None,name='__main__',flags=None,project=True):
 real=os.path.realpath(file)
 if os.path.abspath(file)!=real: raise RuntimeError('unsupported symlinked Python source: '+file)
 if not real.endswith('.py'):
  if real.endswith(tuple(importlib.machinery.EXTENSION_SUFFIXES)+('.pyc',)) and not within(root,real):
   external(real); return
  raise RuntimeError('unsupported Python source target: '+file)
 key=(real,tuple(paths or sys.path),tuple(import_roots),cwd,tuple(argv or ()),name,tuple(sorted((flags or {}).items())))
 if key in seen: return
 seen.add(key)
 if real.endswith('.py'):
  with open(real,'rb') as stream: data=stream.read()
  source_inputs[real]='sha256:'+hashlib.sha256(data).hexdigest()
  # Only this hook's path effects are selected by the isolated runtime query.
  if not project and real in startup_hooks and hashlib.sha256(data).hexdigest() in ('1a773d37457f89ca5d3b7c96541eb8e32e72e47d6c6d48b6428d81e3e7ddafff',):
   for statement in ast.parse(data).body:
    if isinstance(statement,(ast.Import,ast.ImportFrom)):
     names=[alias.name for alias in statement.names] if isinstance(statement,ast.Import) else [statement.module]
     for imported in names: dependency(imported,paths if paths is not None else list(sys.path),cwd,argv,flags,False)
   return
  if (real,name) in active: return
  active.add((real,name))
  try: scan(data.decode('utf-8'),os.path.dirname(real),paths,cwd,argv,real,name,flags,project)
  finally: active.remove((real,name))

for module in list(sys.modules.values()):
 file=getattr(module,'__file__',None)
 if file: external(file)
for p in startup:
 if p.endswith('.py') and (p in startup_hooks or not standard_input(p)): visit(p,project=False)
 elif p.endswith('.pth'):
  with open(p,'rb') as stream: data=stream.read()
  source_inputs[p]='sha256:'+hashlib.sha256(data).hexdigest()
  for line in data.decode('utf-8').splitlines():
   if line.startswith(('import ','import'+chr(9))): scan(line,os.path.dirname(p),project=False)
requirements=[dict(ids=json.loads(sys.argv[3]),files=sorted(required),paths=list(sys.path),inputs=sorted(source_inputs.items()))]
for request in requests:
 required=set(); seen=set(); source_inputs={}; startup_search=list(request['startup_paths'])
 if not request['flags'].get('no_site',False):
  hooks=['sitecustomize']+([] if request['flags'].get('no_user_site',False) else ['usercustomize'])
  for name in hooks:
   spec=importlib.machinery.PathFinder.find_spec(name,startup_search)
   if spec is not None and spec.origin not in (None,'built-in','frozen'):
    external(spec.origin)
    # Bootstrap hook path setup is already reflected in the interpreter query.
    visit(spec.origin,startup_search,request['cwd'],request['argv'],name,request['flags'],project=os.path.realpath(spec.origin) not in startup_hooks)
 paths=([] if request['flags']['safe_path'] else [os.path.dirname(os.path.realpath(request['file'])) if 'file' in request else request['cwd']])+startup_search
 if 'file' in request: visit(request['file'],paths,request['cwd'],request['argv'],flags=request['flags'])
 elif 'code' in request: scan(request['code'],request['cwd'],paths,request['cwd'],request['argv'],flags=request['flags'])
 else:
  spec=dependency(request['module'],paths,request['cwd'],request['argv'],request['flags'],True)
  if spec is not None:
   if spec.submodule_search_locations:
    if spec.origin not in (None,'built-in','frozen'): external(spec.origin); visit(spec.origin,paths,request['cwd'],request['argv'],request['module'],request['flags'])
    main=importlib.machinery.PathFinder.find_spec(request['module']+'.__main__',spec.submodule_search_locations)
    if main is None or main.origin is None: raise RuntimeError('unknown Python module entry point: '+request['module'])
    external(main.origin); visit(main.origin,paths,request['cwd'],[main.origin]+request['argv'][1:],'__main__',request['flags'])
   elif spec.origin not in (None,'built-in','frozen'):
    external(spec.origin); visit(spec.origin,paths,request['cwd'],[spec.origin]+request['argv'][1:],'__main__',request['flags'])
 requirements.append(dict(ids=request['ids'],files=sorted(required),paths=paths,inputs=sorted(source_inputs.items())))
print(json.dumps(dict(executable=os.path.realpath(sys.executable),stdlib=stdlib,extensions=extensions,startup=sorted(startup),requirements=requirements),sort_keys=True))
`;
	const result = await context.probe([
		selected.invoked,
		"-I",
		"-B",
		"-c",
		code,
		context.root,
		JSON.stringify(requests),
		JSON.stringify([context.declaration.id, ...context.declaration.requires]),
	]);
	const data = probeJSON<{
		executable: string;
		stdlib: string;
		extensions: string;
		startup: string[];
		requirements: { ids: string[]; files: string[] }[];
	}>(result);
	if (
		!data.executable ||
		!data.stdlib ||
		!data.extensions ||
		!Array.isArray(data.startup) ||
		!Array.isArray(data.requirements) ||
		data.requirements.some(
			(value) =>
				!Array.isArray(value.ids) ||
				!Array.isArray(value.files) ||
				value.ids.some((id) => typeof id !== "string") ||
				value.files.some((file) => typeof file !== "string"),
		)
	)
		throw new Error("Incomplete selected Python runtime");
	const roots: ToolRoot[] = [
		{ label: "executable", path: data.executable },
		{ label: "stdlib", path: data.stdlib, exclude: ["site-packages"] },
		{ label: "extension-modules", path: data.extensions },
	];
	for (const [index, file] of data.startup.entries())
		roots.push({ label: `startup/${index}/${path.basename(file)}`, path: file });
	const native = await context.native([
		...(await nativePayloads(roots)),
		...data.requirements.flatMap((value) => value.files.filter((file) => /\.(?:so(?:\.\d+)*|dylib|node)$/u.test(file))),
	]);
	roots.push(...native.roots.map((root) => ({ ...root, label: `native/${root.label}` })));
	return {
		roots,
		discovery: [...new Set([...pathDiscovery, result.identity, ...(native.discovery ?? [])])],
		sdk: native.sdk,
		fileRequirements: data.requirements,
	};
}

function assertLoaderEnvironment(environment: Readonly<Record<string, string>>): void {
	for (const name of Object.keys(environment))
		if (/^(?:DYLD_|__XPC_DYLD_)/u.test(name)) throw new Error("Unsupported dynamic loader override: " + name);
}

function assertNodeEnvironment(environment: Readonly<Record<string, string>>): void {
	for (const name of ["NODE_OPTIONS", "npm_config_node_options"])
		if (environment[name]) throw new Error("Unsupported Node runtime selector: " + name);
}

export async function discoverNativeAdapter(
	context: AdapterContext,
	subjects = context.subject,
	options: NativeAdapterOptions = {},
): Promise<AdapterResult> {
	assertLoaderEnvironment(context.effectiveEnv);
	if (process.platform !== "darwin" && process.platform !== "linux")
		throw new Error("Native linkage discovery requires Darwin or Linux");
	const cwd = options.cwd ?? context.cwd;
	const roots: ToolRoot[] = [],
		discovery: ToolDiscovery[] = [];
	const selected = new Map<string, { invoked: string; realpath: string; args: readonly string[] }>();
	const drivers: Record<string, string | readonly string[]> = { ...options.drivers };
	for (const [index, subject] of subjects.entries())
		drivers[`${path.basename(subject).replace(/[^A-Za-z0-9._-]/gu, "_")}-${index}`] = subject;
	for (const [role, value] of Object.entries(drivers).sort(([a], [b]) => utf8Compare(a, b))) {
		const argv = typeof value === "string" ? [value] : [...value];
		if (!argv.length || argv.some((arg) => !arg || arg.includes("\0")))
			throw new Error(`Invalid native driver: ${role}`);
		let command = path.isAbsolute(argv[0])
			? { invoked: argv[0], realpath: await canonicalToolPath(argv[0]) }
			: await context.resolveCommand(argv[0], cwd);
		if (!(await fs.stat(command.realpath)).isFile()) throw new Error(`Native input is not a file: ${argv[0]}`);
		const name = path.basename(argv[0]);
		if (name === "xcrun" && argv.length > 1) {
			const selector: string[] = [];
			let index = 1;
			while (index < argv.length && argv[index].startsWith("-")) {
				if (!["--sdk", "-sdk", "--toolchain", "-toolchain"].includes(argv[index]) || !argv[index + 1])
					throw new Error("Unsupported xcrun selection");
				selector.push(argv[index], argv[index + 1]);
				index += 2;
			}
			if (!argv[index]) throw new Error("xcrun driver is absent");
			const xcrun = command.invoked;
			const probe = await context.probe([command.invoked, ...selector, "--find", argv[index]], { cwd });
			discovery.push(probe.identity);
			roots.push({ label: `drivers/${role}-xcrun`, path: command.realpath });
			command = await context.resolveCommand(probeText(probe).trim(), cwd);
			argv.splice(0, index + 1, command.invoked);
			const sdk = await context.probe([xcrun, ...selector, "--show-sdk-path"], { cwd });
			discovery.push(sdk.identity);
			options = { ...options, sdk: probeText(sdk).trim() };
		}

		if (["cargo", "rustc"].includes(name) && (await isRustupProxy(command))) {
			const rustup = await context
				.resolveCommand(path.join(path.dirname(command.invoked), "rustup"), cwd)
				.catch((error) => {
					if (/^Executable (?:not found:|absent from sanitized PATH:)/u.test(error.message))
						return context.resolveCommand("rustup", cwd);
					throw error;
				});
			const [proxyStat, selectorStat] = await Promise.all([fs.stat(command.realpath), fs.stat(rustup.realpath)]);
			if (proxyStat.dev !== selectorStat.dev || proxyStat.ino !== selectorStat.ino)
				throw new Error("Rustup selector differs from the actual native proxy: " + command.invoked);
			const probe = await context.probe([rustup.invoked, "which", name], { cwd });
			discovery.push(probe.identity);
			command = { invoked: command.invoked, realpath: await canonicalToolPath(probeText(probe).trim()) };
		}
		selected.set(role, { ...command, args: argv.slice(1) });
		roots.push({ label: `drivers/${role}`, path: command.realpath });
	}
	let sdkPath = options.sdk ?? context.effectiveEnv.SDKROOT;
	for (const [role, driver] of selected) {
		if (!/^(?:clang(?:\+\+)?(?:-\d+)?|cc|c\+\+|gcc(?:-\d+)?|g\+\+(?:-\d+)?)$/u.test(path.basename(driver.invoked)))
			continue;
		const flags = [...driver.args, ...(options.flags ?? [])];
		if (options.target && !flags.some((flag) => flag === "-target" || flag.startsWith("--target=")))
			flags.push("-target", options.target);
		if (options.sdk && !flags.includes("-isysroot")) flags.push("-isysroot", options.sdk);
		const trace = await context.probe([driver.invoked, ...flags, "-###", "-fsyntax-only", "-x", "c", "/dev/null"], {
			cwd,
		});
		discovery.push(trace.identity);
		const linkerTrace = await context.probe(
			[driver.invoked, ...flags, "-###", "-x", "none", "/dev/null", "-o", "/dev/null"],
			{ cwd },
		);
		discovery.push(linkerTrace.identity);
		const decoder = new TextDecoder("utf-8", { fatal: true }),
			text = decoder.decode(trace.stderr) + decoder.decode(linkerTrace.stderr);
		for (const match of text.matchAll(/^(?:Configuration file:|Reading specs from) (.+)$/gmu)) {
			const config = await canonicalToolPath(match[1].replace(/^"|"$/gu, ""));
			roots.push({ label: `drivers/${role}-configuration/${H(Buffer.from(config)).slice(7)}`, path: config });
		}

		const quoted = [...text.matchAll(/"([^"\n]+)"/gu)].map((match) => match[1]);
		for (let i = 0; i < quoted.length; i++) {
			if (["-isysroot", "-syslibroot"].includes(quoted[i])) {
				const candidate = quoted[i + 1];
				if (candidate && candidate !== "/") sdkPath = candidate;
			}
			if (
				path.isAbsolute(quoted[i]) &&
				/(?:^|\/)(?:clang(?:\+\+)?(?:-\d+)?|gcc(?:-\d+)?|g\+\+(?:-\d+)?|ld|ld64|ld\.lld|as|ar)$/u.test(quoted[i])
			)
				roots.push({
					label: `drivers/${role}-selected-${path.basename(quoted[i]).replace(/[^A-Za-z0-9._-]/gu, "_")}`,
					path: await canonicalToolPath(quoted[i]),
				});
		}
		for (const program of ["ld", "as", "ar"]) {
			const probe = await context.probe([driver.invoked, ...flags, `-print-prog-name=${program}`], { cwd });
			discovery.push(probe.identity);
			const name = probeText(probe).trim();
			if (!name || /\r|\n/u.test(name)) throw new Error(`Ambiguous selected ${program}`);
			const binary = await context.resolveCommand(name, cwd);
			roots.push({ label: `drivers/${role}-${program}`, path: binary.realpath });
		}
	}
	const visited = new Set<string>(),
		elfFiles: string[] = [];
	const loadCommands = new Map<string, Promise<ReturnType<typeof parseMachOLoadCommands>>>();
	let otoolSelection: Promise<{ invoked: string; realpath: string }> | undefined;
	const selectedOtool = (): Promise<{ invoked: string; realpath: string }> => {
		otoolSelection ??= (async () => {
			let tool = await context.resolveCommand("otool", cwd);
			if (tool.realpath === "/usr/bin/otool") {
				roots.push({ label: "drivers/discovery-otool-launcher", path: tool.realpath });
				const xcrun = await context.resolveCommand("xcrun", cwd);
				roots.push({ label: "drivers/discovery-xcrun", path: xcrun.realpath });
				const selection = await context.probe([xcrun.invoked, "--no-cache", "--find", "otool"], { cwd });
				discovery.push(selection.identity);
				const implementation = probeText(selection).trim();
				if (!path.isAbsolute(implementation)) throw new Error("Unresolved installed otool implementation");
				const selected = await context.resolveCommand(implementation, cwd);
				if (selected.realpath === tool.realpath) throw new Error("xcrun returned the otool launcher");
				tool = selected;
			}
			roots.push({ label: "drivers/discovery-otool", path: tool.realpath });
			return tool;
		})();
		return otoolSelection;
	};
	const readLoadCommands = async (image: string): Promise<ReturnType<typeof parseMachOLoadCommands>> => {
		let pending = loadCommands.get(image);
		if (!pending) {
			pending = (async () => {
				const otool = await selectedOtool();
				const loads = await context.probe([otool.invoked, "-l", image], { cwd });
				discovery.push(loads.identity);
				try {
					return parseMachOLoadCommands(probeText(loads));
				} catch (error) {
					throw new Error(`${error instanceof Error ? error.message : String(error)}: ${image}`);
				}
			})();
			loadCommands.set(image, pending);
		}
		return pending;
	};
	// @executable_path names the process image, which for a shebang script is its interpreter.
	const processImage = async (file: string, depth = 0): Promise<string> => {
		const handle = await fs.open(file, "r");
		const head = Buffer.alloc(256);
		let length: number;
		try {
			({ bytesRead: length } = await handle.read(head, 0, 256, 0));
		} finally {
			await handle.close();
		}
		if (length >= 4 && MACHO_MAGIC.includes(head.readUInt32BE(0))) return file;
		const prefix = head.subarray(0, length).toString("utf8");
		if (!prefix.startsWith("#!") || depth > 2) throw new Error(`Unsupported native process image: ${file}`);
		const tokens = prefix
			.split("\n", 1)[0]
			.slice(2)
			.trim()
			.split(/[ \t]+/u);
		const interpreter =
			path.basename(tokens[0]) === "env"
				? tokens.length === 2
					? tokens[1]
					: (() => {
							throw new Error(`Unsupported native shebang: ${file}`);
						})()
				: tokens[0];
		return processImage((await context.resolveCommand(interpreter, cwd)).realpath, depth + 1);
	};
	const inspect = async (file: string, executable: string, inheritedRpaths: readonly string[] = []): Promise<void> => {
		const real = await canonicalToolPath(file);
		const executableTarget = path.isAbsolute(executable)
			? await canonicalToolPath(executable)
			: (await context.resolveCommand(executable, cwd)).realpath;
		const inputContext = D("native-input-context", {
			image: real,
			executable: executableTarget,
			rpaths: inheritedRpaths,
		});
		if (visited.has(inputContext)) return;
		const handle = await fs.open(real, "r");
		let magic: Buffer;
		try {
			magic = Buffer.alloc(4);
			await handle.read(magic, 0, 4, 0);
		} finally {
			await handle.close();
		}
		const word = magic.readUInt32BE(0);
		if (process.platform === "linux" && word === 0x7f454c46) {
			visited.add(inputContext);
			elfFiles.push(real);
			return;
		}
		if (process.platform !== "darwin" || !MACHO_MAGIC.includes(word)) {
			visited.add(inputContext);
			const prefix = (await fs.readFile(real)).subarray(0, 256).toString("utf8");
			if (prefix.startsWith("#!")) {
				const line = prefix.split("\n", 1)[0].slice(2).trim();
				const tokens = line.split(/[ \t]+/u);
				let interpreter = tokens[0];
				if (path.basename(interpreter) === "env") {
					if (tokens.length !== 2) throw new Error(`Unsupported native shebang: ${real}`);
					const envRuntime = await context.resolveCommand(interpreter, cwd);
					roots.push({ label: "drivers/shebang-env", path: envRuntime.realpath });
					await inspect(envRuntime.realpath, envRuntime.realpath);
					interpreter = tokens[1];
				}
				const runtime = await context.resolveCommand(interpreter, cwd);
				const label = `drivers/shebang-${path.basename(runtime.realpath)}`;
				roots.push({ label, path: runtime.realpath });
				await inspect(runtime.realpath, runtime.realpath);
			}
			return;
		}
		const executableReal = real === executableTarget ? real : await processImage(executableTarget);
		const commands = await readLoadCommands(real);
		const expand = (value: string, loader = real): string =>
			path.resolve(
				cwd,
				value
					.replace(/^@loader_path/u, path.dirname(loader))
					.replace(/^@executable_path/u, path.dirname(executableReal)),
			);
		const inherited =
			inheritedRpaths.length > 0 || real === executableReal
				? inheritedRpaths
				: (await readLoadCommands(executableReal)).rpaths.map((value) => expand(value, executableReal));
		const rpaths = [...new Set([...commands.rpaths.map((value) => expand(value)), ...inherited])];
		const loadContext = D("native-load-context", { image: real, executable: executableReal, rpaths });
		if (visited.has(loadContext)) {
			visited.add(inputContext);
			return;
		}
		visited.add(loadContext);
		visited.add(inputContext);
		for (const install of commands.dependencies) {
			if (install.startsWith("/usr/lib/") || install.startsWith("/System/Library/")) continue;
			let candidates: string[];
			if (install.startsWith("@rpath/")) candidates = rpaths.map((root) => path.join(root, install.slice(7)));
			else candidates = [expand(install)];
			const existing: string[] = [];
			for (const candidate of candidates) {
				try {
					existing.push(await canonicalToolPath(candidate));
				} catch (error) {
					if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
				}
			}
			const targets = [...new Set(existing)];
			if (targets.length !== 1) throw new Error(`Unresolved or ambiguous native library ${install} from ${real}`);
			if (targets[0].startsWith("/usr/lib/") || targets[0].startsWith("/System/Library/")) continue;
			roots.push({ label: `non-system-libraries/${encodeURIComponent(install)}`, path: targets[0] });
			await inspect(targets[0], executableReal, rpaths);
		}
	};
	let sdk: AdapterResult["sdk"] = null;
	if (sdkPath && process.platform !== "darwin") throw new Error("SDK selection is Darwin-only");
	if (sdkPath) {
		const real = await canonicalToolPath(sdkPath);
		let settings = path.join(real, "SDKSettings.json"),
			data: Record<string, any>;
		try {
			data = parseJSON(await fs.readFile(settings)) as Record<string, any>;
		} catch (error) {
			if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
			settings = path.join(real, "SDKSettings.plist");
			const plutil = await context.resolveCommand("plutil", cwd);
			roots.push({ label: "drivers/discovery-plutil", path: plutil.realpath });
			const probe = await context.probe([plutil.invoked, "-convert", "json", "-o", "-", settings], { cwd });
			discovery.push(probe.identity);
			data = probeJSON(probe);
		}
		const version = data.Version;
		if (typeof version !== "string" || !version) throw new Error("Selected SDK lacks version identity");
		sdk = { version, settings_hash: H(await fs.readFile(settings)) };
		roots.push({ label: "sdk-settings", path: settings });
	}
	for (let index = 0; index < roots.length; index++) {
		const input = roots[index];
		if (input.label.startsWith("drivers/"))
			await inspect(
				input.path,
				/\.(?:node|dylib|so(?:\.\d+)*)$/u.test(input.path) ? (subjects[0] ?? input.path) : input.path,
			);
	}
	if (elfFiles.length) roots.push(...(await linuxLinkage(context, elfFiles)));
	return { roots, discovery, sdk };
}

const PNPM_NODE_SHIM =
	'#!/bin/sh\nbasedir=$(dirname "$(echo "$0" | sed -e \'s,\\\\,/,g\')")\n\ncase `uname` in\n    *CYGWIN*|*MINGW*|*MSYS*)\n        if command -v cygpath > /dev/null 2>&1; then\n            basedir=`cygpath -w "$basedir"`\n        fi\n    ;;\nesac\n\nif [ -z "$NODE_PATH" ]; then\n  export NODE_PATH="__FV_NODE_PATH__"\nelse\n  export NODE_PATH="__FV_NODE_PATH__:$NODE_PATH"\nfi\nif [ -x "$basedir/node" ]; then\n  exec "$basedir/node"  "__FV_ENTRY__" "$@"\nelse\n  exec node  "__FV_ENTRY__" "$@"\nfi\n';
async function selectedNodeExecution(
	context: AdapterContext,
	launcher: string,
	entry: string,
): Promise<{
	roots: ToolRoot[];
	discovery: ToolDiscovery[];
	node: string;
	environment: Record<string, string>;
	native: string[];
}> {
	assertNodeEnvironment(context.effectiveEnv);
	const configured = await context.probe([launcher, "config", "get", "node-options"]);
	if (!["", "undefined", "null"].includes(probeText(configured).trim()))
		throw new Error("Unsupported pnpm-injected Node runtime selectors");
	const name = context.subject[2];
	const code = `const fs=require('node:fs'),path=require('node:path');const select=name=>{for(const directory of process.env.PATH.split(path.delimiter)){const file=path.resolve(directory,name);try{fs.accessSync(file,fs.constants.X_OK);if(fs.statSync(file).isFile())return file;}catch(error){if(!['ENOENT','ENOTDIR','EACCES'].includes(error.code))throw error;}}return null;};console.log(JSON.stringify({path:process.env.PATH,nodeOptions:process.env.NODE_OPTIONS??'',execArgv:process.execArgv,executables:Object.fromEntries([${JSON.stringify(name)},'node','dirname','sed','uname'].map(name=>[name,select(name)]))}));`;
	const probe = await context.probe([launcher, "exec", process.execPath, "-e", code]);
	const selection = probeJSON<{
		path: string;
		nodeOptions: string;
		execArgv: string[];
		executables: Record<string, string | null>;
	}>(probe);
	if (
		typeof selection.nodeOptions !== "string" ||
		selection.nodeOptions ||
		!Array.isArray(selection.execArgv) ||
		selection.execArgv.length !== 2 ||
		!["-e", "--eval"].includes(selection.execArgv[0]) ||
		selection.execArgv[1] !== code
	)
		throw new Error("Unsupported pnpm-injected Node runtime selectors");
	if (
		typeof selection.path !== "string" ||
		!selection.executables ||
		!path.isAbsolute(selection.executables[name] ?? "")
	)
		throw new Error("Cannot resolve pnpm exec executable selection");
	const shim = selection.executables[name]!,
		real = await canonicalToolPath(shim),
		manifest = await readPackage(entry),
		bin = typeof manifest.bin === "string" ? manifest.bin : manifest.bin?.[name];
	if (typeof bin !== "string") throw new Error("Selected Node package has no executable declaration");
	const expected = await canonicalToolPath(path.resolve(entry, bin));
	if (!inside(entry, expected)) throw new Error("Selected Node executable escapes its package");
	const roots: ToolRoot[] = [{ label: "execution/shim", path: shim }],
		discovery = [configured.identity, probe.identity],
		native = [launcher, shim],
		environment: Record<string, string> = { ...context.effectiveEnv, PATH: selection.path };
	let node = selection.executables.node,
		nodePath = environment.NODE_PATH ?? "";
	if (real !== expected) {
		const source = (await fs.readFile(real, "utf8")).replace(/\r\n/gu, "\n"),
			injected = /^  export NODE_PATH="([^"$\r\n]*)"$/mu.exec(source)?.[1],
			target = /^  exec "\$basedir\/node"  "(\$basedir\/[^"$\r\n]+)" "\$@"$/mu.exec(source)?.[1];
		if (
			injected === undefined ||
			!target ||
			source !== PNPM_NODE_SHIM.replaceAll("__FV_NODE_PATH__", injected).replaceAll("__FV_ENTRY__", target)
		)
			throw new Error("Cannot resolve unsupported pnpm Node execution shim: " + shim);
		if ((await canonicalToolPath(path.resolve(path.dirname(shim), target.slice("$basedir/".length)))) !== expected)
			throw new Error("pnpm execution shim selects a different package entry point");
		for (const helper of ["dirname", "sed", "uname"]) {
			const executable = selection.executables[helper];
			if (!executable || !path.isAbsolute(executable)) throw new Error("Unresolved pnpm shim helper: " + helper);
			roots.push({ label: "execution/helpers/" + helper, path: executable });
			native.push(executable);
		}
		const host = await context.probe([selection.executables.uname!], { env: environment });
		discovery.push(host.identity);
		if (probeText(host).trim() !== (process.platform === "darwin" ? "Darwin" : "Linux"))
			throw new Error("Unsupported pnpm shim host selection");
		const preferred = path.join(path.dirname(shim), "node");
		try {
			await fs.access(preferred, fs.constants.X_OK);
			if (!(await fs.stat(preferred)).isFile()) throw new Error("Preferred pnpm shim Node is not a file");
			node = preferred;
		} catch (error) {
			if (!["ENOENT", "ENOTDIR", "EACCES"].includes((error as NodeJS.ErrnoException).code ?? "")) throw error;
		}
		nodePath = injected + (nodePath ? path.delimiter + nodePath : "");
	} else {
		const shebang = /^#!\s*(?:\/usr\/bin\/env node|(\/[^\s]+\/node))\r?$/u.exec(
			(await fs.readFile(real, "utf8")).split("\n", 1)[0],
		);
		if (!shebang) throw new Error("Cannot resolve selected Node executable runtime");
		if (shebang[1]) node = shebang[1];
	}
	if (!node || !path.isAbsolute(node)) throw new Error("Cannot resolve pnpm execution Node runtime");
	await fs.access(node, fs.constants.X_OK);
	roots.push({ label: "execution/node", path: node });
	native.push(node);
	environment.NODE_PATH = nodePath;
	assertNodeEnvironment(environment);
	const runtime = await context.probe([node, "-p", "JSON.stringify({executable:process.execPath})"], {
		env: environment,
	});
	discovery.push(runtime.identity);
	const executable = probeJSON<{ executable: string }>(runtime).executable;
	if (typeof executable !== "string" || !path.isAbsolute(executable))
		throw new Error("Cannot resolve preferred Node implementation executable");
	await fs.access(executable, fs.constants.X_OK);
	roots.push({ label: "execution/node-runtime", path: executable });
	native.push(executable);
	const stores = new Set<string>();
	for (const [index, directory] of nodePath.split(path.delimiter).filter(Boolean).entries()) {
		const selected = path.resolve(context.cwd, directory);
		try {
			if (!(await fs.stat(selected)).isDirectory())
				throw new Error("Node module search entry is not a directory: " + selected);
			let store = selected;
			while (
				path.dirname(store) !== store &&
				!(path.basename(store) === ".pnpm" && path.basename(path.dirname(store)) === "node_modules")
			)
				store = path.dirname(store);
			let linkBoundary: string | undefined;
			if (path.basename(store) === ".pnpm" && path.basename(path.dirname(store)) === "node_modules") {
				linkBoundary = await canonicalToolPath(store);
				if (!inside(linkBoundary, await canonicalToolPath(selected)))
					throw new Error("Node module search entry escapes pnpm virtual store: " + selected);
				if (!stores.has(linkBoundary)) {
					stores.add(linkBoundary);
					roots.push({ label: "execution/node-store/" + index, path: linkBoundary, linkBoundary });
				}
			}
			roots.push({ label: "execution/node-path/" + index, path: selected, linkBoundary });
		} catch (error) {
			if (!["ENOENT", "ENOTDIR"].includes((error as NodeJS.ErrnoException).code ?? "")) throw error;
		}
	}
	return { roots, discovery, node, environment, native };
}

export async function discoverNodeAdapter(context: AdapterContext): Promise<AdapterResult> {
	assertLoaderEnvironment(context.effectiveEnv);
	assertNodeEnvironment(context.effectiveEnv);
	if (path.basename(context.subject[0] ?? "") !== "pnpm" || context.subject[1] !== "exec" || !context.subject[2])
		throw new Error("Unsupported Node toolchain subject");
	const launcher = await context.resolveCommand(context.subject[0]),
		shebang = /^#!\s*(?:\/usr\/bin\/env node|(\/[^\s]+\/node))\r?$/u.exec(
			(await fs.readFile(launcher.realpath, "utf8")).split("\n", 1)[0],
		);
	if (!shebang) throw new Error("Cannot resolve pnpm launcher Node runtime");
	const node = await context.resolveCommand(shebang[1] ?? "node");
	const managerRoot = await packageDirectory(launcher.realpath),
		manager = await readPackage(managerRoot);
	const project = await readPackage(context.cwd);
	if (
		typeof project.packageManager !== "string" ||
		!/^pnpm@\d+\.\d+\.\d+(?:\+sha\d+\.[0-9a-f]+)?$/u.test(project.packageManager)
	)
		throw new Error("Node context needs an exact pnpm packageManager selection");
	const version = project.packageManager.slice(5).split("+", 1)[0];
	let pnpmRoot: string,
		corepackRoot: string | null = null;
	const discovery: ToolDiscovery[] = [];
	const runtime = await context.probe([node.invoked, "-p", "JSON.stringify({executable:process.execPath})"]);
	discovery.push(runtime.identity);
	const nodeImplementation = probeJSON<{ executable: string }>(runtime).executable;
	if (typeof nodeImplementation !== "string" || !path.isAbsolute(nodeImplementation))
		throw new Error("Cannot resolve pnpm Node implementation executable");
	if (manager.name === "corepack") {
		corepackRoot = managerRoot;
		const corepack = path.join(managerRoot, "dist/lib/corepack.cjs");
		const code = `const fs=require('fs'),path=require('path'),{createRequire}=require('module');const file=process.argv[1],req=createRequire(file),m={exports:{}};new Function('require','module','exports','__filename','__dirname',fs.readFileSync(file,'utf8')+'\\nmodule.exports.__fv={getInstallFolder};')(req,m,m.exports,file,path.dirname(file));const root=path.join(m.exports.__fv.getInstallFolder(),'pnpm',process.argv[2]);console.log(JSON.stringify({root,metadata:JSON.parse(fs.readFileSync(path.join(root,'.corepack'),'utf8'))}));`;
		const probe = await context.probe([node.invoked, "-e", code, corepack, version]);
		discovery.push(probe.identity);
		const selection = probeJSON<{ root: string; metadata: { locator?: { name: string; reference: string } } }>(probe);
		if (
			selection.metadata.locator?.name !== "pnpm" ||
			selection.metadata.locator.reference.split("+", 1)[0] !== version
		)
			throw new Error("Corepack selected pnpm metadata mismatch");
		pnpmRoot = await canonicalToolPath(selection.root);
	} else if (manager.name === "pnpm" && manager.version === version) pnpmRoot = managerRoot;
	else throw new Error("pnpm launcher does not select the project packageManager");
	const pnpmManifest = await readPackage(pnpmRoot);
	if (pnpmManifest.name !== "pnpm" || pnpmManifest.version !== version)
		throw new Error("Selected pnpm distribution mismatch");
	const entry = await resolvePackage(context.subject[2], context.cwd);
	if (!entry) throw new Error(`Missing installed ${context.subject[2]} package`);
	const entries = [entry];
	for (const name of Object.keys(project.dependencies ?? {}).sort(utf8Compare)) {
		const selected = await resolvePackage(name, context.cwd);
		if (!selected) throw new Error(`Missing installed project package: ${name}`);
		entries.push(selected);
	}
	const sourceFiles = context.subject
		.slice(3)
		.filter((value) => !value.startsWith("-") && /\.[cm]?[jt]sx?$/u.test(value))
		.map((value) => path.resolve(context.cwd, value));
	entries.push(...(await importedNodePackages(context, sourceFiles)));
	const packages = await packageRoots(context, entries);
	await validateLockedNodePackages(context, packages, project);
	const execution = await selectedNodeExecution(context, launcher.invoked, entry);
	const roots: ToolRoot[] = [
		{ label: "node", path: node.realpath },
		{ label: "pnpm-node-runtime", path: nodeImplementation },
		{ label: "pnpm", path: pnpmRoot, exclude: ["node_modules"] },
		...packages,
		...execution.roots,
	];
	if (corepackRoot) roots.push({ label: "corepack", path: corepackRoot, exclude: ["node_modules"] });
	roots.push(...(await packageRoots(context, [pnpmRoot, ...(corepackRoot ? [corepackRoot] : [])])));
	const executionContext: AdapterContext = {
		...context,
		effectiveEnv: execution.environment,
		resolveCommand: (command, cwd) => context.resolveCommand(command, cwd, execution.environment),
		probe: (command, settings) => context.probe(command, { env: execution.environment, ...settings }),
	};
	const native = await discoverNativeAdapter(executionContext, [...execution.native, ...(await nativePayloads(roots))]);
	roots.push(...native.roots.map((root) => ({ ...root, label: `native/${root.label}` })));
	discovery.push(...execution.discovery, ...(native.discovery ?? []));
	const pnpmBin = typeof pnpmManifest.bin === "string" ? pnpmManifest.bin : pnpmManifest.bin?.pnpm;
	if (typeof pnpmBin !== "string" || !pnpmBin) throw new Error("Selected pnpm package has no declared executable");
	const pnpmExecutable = await canonicalToolPath(path.resolve(pnpmRoot, pnpmBin));
	if (!inside(pnpmRoot, pnpmExecutable)) throw new Error("Selected pnpm executable escapes its distribution");
	const pnpmVersion = await context.probe([node.invoked, pnpmExecutable, "--version"]);
	discovery.push(pnpmVersion.identity);
	if (probeText(pnpmVersion).trim() !== version)
		throw new Error("Actual pnpm version differs from selected distribution");
	const cacheNamespaces: CacheNamespaceSelection[] = [];
	const tsx = packages.find((root) => root.label.startsWith("packages/tsx/"));
	if (tsx) {
		const directory = path.join(tsx.path, "dist"),
			candidates: string[] = [];
		for (const name of await fs.readdir(directory))
			if (name.endsWith(".cjs")) {
				const file = path.join(directory, name),
					source = await fs.readFile(file, "utf8");
				if (
					source.includes("exports.tmpdir=") &&
					source.includes('require("node:os")') &&
					source.includes(".tmpdir()") &&
					!["mkdir", "writeFile", "unlink", "rename", "exec(", "spawn("].some((name) => source.includes(name))
				)
					candidates.push(file);
			}
		if (candidates.length !== 1) throw new Error("Cannot establish selected tsx transformation cache module");
		const code =
			"const value=require(process.argv[1]).tmpdir;if(typeof value!=='string')throw Error('cache path missing');console.log(JSON.stringify({path:value}));";
		const probe = await context.probe([execution.node, "-e", code, candidates[0]], { env: execution.environment });
		discovery.push(probe.identity);
		cacheNamespaces.push({
			role: "node-transformations",
			kind: "selected-path",
			path: probeJSON<{ path: string }>(probe).path,
		});
	}
	const code =
		"const mod=require('module');if(typeof mod.enableCompileCache!=='function')throw Error('unsupported pnpm compile-cache runtime');const result=mod.enableCompileCache();if(result.status===mod.constants.compileCacheStatus.DISABLED)console.log(JSON.stringify({path:null}));else{if(typeof result.directory!=='string')throw Error('compiler cache selection failed');console.log(JSON.stringify({path:result.directory}));}";
	const compileCache = await context.probe([node.invoked, "-e", code]);
	discovery.push(compileCache.identity);
	const compilerNamespace = probeJSON<{ path: string | null }>(compileCache).path;
	if (compilerNamespace !== null)
		cacheNamespaces.push({ role: "node-compiler-cache", kind: "selected-path", path: compilerNamespace });

	return { roots, discovery, sdk: native.sdk, cacheNamespaces };
}

async function producerImplementationSources(
	implementationFiles: readonly string[] = [],
): Promise<{ roots: ToolRoot[]; hash: Hash }> {
	const directory = path.dirname(fileURLToPath(import.meta.url)),
		visited = new Set<string>(),
		roots: ToolRoot[] = [],
		files: { path: string; hash: Hash }[] = [];
	const host = (
		globalThis as unknown as {
			Bun?: {
				Transpiler: new (options: {
					loader: string;
				}) => { scanImports(code: string): { path: string; kind: string }[] };
			};
		}
	).Bun;
	if (!host) throw new Error("Producer import discovery requires the actual Bun host");
	const visit = async (file: string): Promise<void> => {
		const real = await canonicalToolPath(file);
		if (visited.has(real)) return;
		visited.add(real);
		const bytes = await fs.readFile(real),
			name = inside(path.dirname(directory), real)
				? path.relative(path.dirname(directory), real).split(path.sep).join("/")
				: `external/${H(Buffer.from(real)).slice(7)}/${path.basename(real)}`;
		roots.push({ label: `implementation/${name}`, path: real });
		files.push({ path: name, hash: H(bytes) });
		if (!/\.(?:ts|js|mjs|cjs)$/u.test(real)) return;
		const imports = new host.Transpiler({ loader: real.endsWith(".ts") ? "ts" : "js" }).scanImports(
			new TextDecoder("utf-8", { fatal: true }).decode(bytes),
		);
		for (const imported of imports) {
			const specifier = imported.path;
			if (specifier.startsWith("node:")) continue;
			if (!specifier.startsWith(".")) throw new Error(`Unattested producer package import: ${specifier}`);
			const base = path.resolve(path.dirname(real), specifier);
			let selected: string | null = null;
			for (const candidate of [
				base,
				base + ".ts",
				base + ".js",
				path.join(base, "index.ts"),
				path.join(base, "index.js"),
			]) {
				try {
					if ((await fs.stat(candidate)).isFile()) {
						selected = candidate;
						break;
					}
				} catch (error) {
					if (!["ENOENT", "ENOTDIR"].includes((error as NodeJS.ErrnoException).code ?? "")) throw error;
				}
			}
			if (!selected) throw new Error(`Missing producer import: ${specifier}`);
			await visit(selected);
		}
	};
	await visit(path.join(directory, "..", "evidence-run.ts"));
	for (const file of implementationFiles) await visit(path.resolve(directory, file));
	await visit(path.join(directory, "evidence-v4-lake-metadata.lean"));
	files.sort((a, b) => utf8Compare(a.path, b.path));
	return { roots, hash: D("producer-implementation", files) };
}
export async function producerImplementationHash(implementationFiles?: readonly string[]): Promise<Hash> {
	return (await producerImplementationSources(implementationFiles)).hash;
}

export function createToolchainSession(options: ToolchainSessionOptions): ToolchainSession {
	const { root, policy, session, signal } = options,
		env = { ...options.env };
	assertLoaderEnvironment(env);
	assertNodeEnvironment(env);
	const hasher = new ToolHasher(),
		identities = new Map<string, ToolIdentity>(),
		adapters = new Map<string, AdapterResult>(),
		origins = new Map<
			string,
			{ label: string; base: string; inode: string; directory: boolean; exclude?: readonly string[] }[]
		>(),
		fileMaps = new Map<string, Map<string, ToolFile>>();
	const setOrigins = async (id: string, roots: readonly ToolRoot[], files: readonly ToolFile[]): Promise<void> => {
		const views: { label: string; base: string; inode: string; directory: boolean; exclude?: readonly string[] }[] = [];
		for (const view of roots) {
			const base = await canonicalToolPath(view.path),
				stat = await fs.stat(base, { bigint: true });
			views.push({
				label: view.label,
				base,
				inode: `${stat.dev}:${stat.ino}`,
				directory: stat.isDirectory(),
				exclude: view.exclude,
			});
		}
		origins.set(id, views);
		fileMaps.set(id, new Map(files.map((file) => [file.path, file])));
	};
	let generation = 0,
		revalidationTail: Promise<void> = Promise.resolve();
	const probes = new Map<string, Promise<ProbeResult>>(),
		discoveries = new Map<string, Promise<AdapterResult>>();
	const declarations = new Map(policy.toolchains.map((tool) => [tool.id, tool]));
	const closure = (ids: readonly string[]): string[] => {
		const result = new Set<string>(),
			active = new Set<string>();
		const visit = (id: string): void => {
			if (result.has(id)) return;
			if (id === "fv-producer") throw new Error("Policy cannot reference fv-producer");
			if (active.has(id)) throw new Error(`Toolchain cycle: ${id}`);
			const declaration = declarations.get(id);
			if (!declaration) throw new Error(`Unknown toolchain ${id}`);
			active.add(id);
			for (const required of declaration.requires) visit(required);
			active.delete(id);
			result.add(id);
		};
		for (const id of ids) visit(id);
		return [...result].sort(utf8Compare);
	};
	const resolveCommand = async (
		command: string,
		cwd = root,
		environment = env,
	): Promise<{ invoked: string; realpath: string }> => {
		if (!command || command.includes("\0") || command.startsWith("~")) throw new Error("Invalid executable selection");
		const directory = path.resolve(root, cwd),
			candidates = command.includes(path.sep)
				? [path.resolve(directory, command)]
				: environment.PATH === undefined
					? []
					: environment.PATH.split(path.delimiter).map((entry) => path.resolve(directory, entry, command));
		for (const invoked of candidates) {
			try {
				const realpath = await canonicalToolPath(invoked),
					stat = await fs.stat(realpath);
				if (!stat.isFile()) continue;
				await fs.access(invoked, fs.constants.X_OK);
				return { invoked, realpath };
			} catch (error) {
				if (!["ENOENT", "ENOTDIR", "EACCES"].includes((error as NodeJS.ErrnoException).code ?? "")) throw error;
			}
		}
		throw new Error(`Executable absent from sanitized PATH: ${command}`);
	};
	const relativeCwd = (cwd: string): Cwd => {
		const relative = path.relative(root, cwd).split(path.sep).join("/");
		if (!inside(root, cwd)) throw new Error("Probe cwd escapes root");
		return (relative || ".") as Cwd;
	};
	const probe = async (
		command: readonly string[],
		settings: { cwd?: string; env?: Record<string, string> } = {},
	): Promise<ProbeResult> => {
		const cwd = settings.cwd ?? root,
			environment = settings.env ?? env;
		assertLoaderEnvironment(environment);
		const selected = await resolveCommand(command[0], cwd, environment);
		const key = D("tool-probe", {
			generation,
			command: [...command],
			cwd: relativeCwd(cwd),
			environment: Object.entries(environment)
				.sort(([a], [b]) => utf8Compare(a, b))
				.map(([name, value]) => ({ name, hash: H(Buffer.from(value)) })),
			executable: selected.realpath,
			...(await hasher.file(selected.realpath)),
		});
		let result = probes.get(key);
		if (!result) {
			result = (async () => {
				let execution: Awaited<ReturnType<NativeSession["run"]>>;
				try {
					execution = await session.run({ command: [...command], cwd, environment, timeoutSeconds: 30, signal });
				} catch (error) {
					const detail = error instanceof Error ? error.message : String(error);
					throw new Error(
						`Tool discovery invocation failed: ${JSON.stringify(command)} (cwd=${relativeCwd(cwd)}): ${detail}`,
						{ cause: error },
					);
				}
				const termination = execution.termination;
				if (
					execution.error ||
					termination.exit_code !== 0 ||
					termination.signal ||
					termination.timed_out ||
					termination.cancelled
				) {
					const diagnostics = (
						[
							["stdout", execution.stdout],
							["stderr", execution.stderr],
						] as const
					)
						.map(([name, bytes]) => {
							let text: string;
							try {
								text = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(bytes);
							} catch {
								text = "<invalid UTF-8>";
							}
							return `${name} (${H(bytes)}, ${bytes.length} bytes):\n${text}`;
						})
						.join("\n");
					throw new Error(
						`Tool discovery failed: ${JSON.stringify(command)} (cwd=${relativeCwd(cwd)}; termination=${JSON.stringify(termination)}; error=${execution.error ?? "none"})\n${diagnostics}`,
						{ cause: execution },
					);
				}
				return {
					stdout: execution.stdout,
					stderr: execution.stderr,
					code: termination.exit_code,
					identity: {
						command: [...command],
						cwd: relativeCwd(cwd),
						stdout_hash: H(execution.stdout),
						stderr_hash: H(execution.stderr),
						exit_code: termination.exit_code,
					},
				};
			})();
			probes.set(key, result);
		}
		return result;
	};
	const helperSelections = new WeakMap<
		AdapterContext,
		Map<
			string,
			{
				command: string;
				cwd: string;
				environment: Record<string, string>;
			}
		>
	>();
	const helperClosure = async (context: AdapterContext): Promise<AdapterResult> => {
		const roots: ToolRoot[] = [],
			discovery: ToolDiscovery[] = [];
		for (const [key, helper] of helperSelections.get(context) ?? []) {
			const selectedContext = {
				...context,
				cwd: helper.cwd,
				effectiveEnv: helper.environment,
				resolveCommand: (command: string, cwd = helper.cwd) => resolveCommand(command, cwd, helper.environment),
				probe: (command: readonly string[], settings: { cwd?: string; env?: Record<string, string> } = {}) =>
					context.probe(command, { cwd: helper.cwd, env: helper.environment, ...settings }),
			};
			const native = await discoverNativeAdapter(selectedContext, [helper.command]);
			roots.push(...native.roots.map((value) => ({ ...value, label: `discovery-helpers/${key}/${value.label}` })));
			discovery.push(...(native.discovery ?? []));
		}
		return { roots, discovery };
	};
	const contextFor = (declaration: ToolDeclaration): AdapterContext => {
		const locator = declaration.locator;
		const cwdRelative = locator.mode === "adapter" ? locator.cwd : (declaration.version_cwd ?? ".");
		const cwd = path.resolve(root, cwdRelative);
		const applicationContexts = policy.recipes
			.filter((recipe) => closure(recipe.toolchain).includes(declaration.id))
			.map((recipe) => ({ recipe, subject: recipe.command, cwd: path.resolve(root, recipe.cwd) }));
		const commandContexts = [
			...applicationContexts.map((value) => ({
				subject: value.subject,
				cwd: value.cwd,
				toolchain: value.recipe.toolchain,
			})),
			...[...policy.preflight, policy.claim_checker]
				.filter((check) => closure(check.toolchain).includes(declaration.id))
				.map((check) => ({ subject: check.command, cwd: path.resolve(root, check.cwd), toolchain: check.toolchain })),
		];
		const helpers = new Map<string, { command: string; cwd: string; environment: Record<string, string> }>();
		const context: AdapterContext = {
			root,
			cwd,
			cwdRelative,
			subject: locator.mode === "adapter" ? locator.subject : [],
			effectiveEnv: env,
			declaration,
			signal,
			session,
			applicationContexts,
			commandContexts,
			otherCommandBound: async (command) => {
				const selected = await resolveCommand(command.subject[0], command.cwd);
				if (
					[command.subject[0], selected.realpath].some((value) =>
						/^(?:sh|bash|dash|zsh|fish|csh|tcsh|ksh|env|busybox)$/u.test(path.basename(value)),
					)
				)
					return false;
				for (const id of closure(command.toolchain)) {
					if (id === declaration.id) continue;
					const other = declarations.get(id)!,
						locator = other.locator;
					if (locator.mode === "adapter") {
						if (locator.value === "python-runtime" || !locator.subject.length) continue;
						if (
							(await resolveCommand(locator.subject[0], path.resolve(root, locator.cwd))).realpath === selected.realpath
						)
							return true;
					} else if (other.kind === "executable" || other.kind === "file") {
						const file =
							locator.mode === "command"
								? (await resolveCommand(locator.value, path.resolve(root, other.version_cwd ?? "."))).realpath
								: locator.mode === "path"
									? await canonicalToolPath(path.resolve(root, locator.value))
									: null;
						if (file !== selected.realpath) continue;
						const handle = await fs.open(file, "r"),
							magic = Buffer.alloc(4);
						try {
							await handle.read(magic, 0, 4, 0);
						} finally {
							await handle.close();
						}
						if (MACHO_MAGIC.includes(magic.readUInt32BE()) || magic.readUInt32BE() === 0x7f454c46) return true;
					}
				}
				return false;
			},
			probe: async (command, settings) => {
				const selectedCwd = settings?.cwd ?? cwd,
					environment = settings?.env ?? env,
					selected = await resolveCommand(command[0], selectedCwd, environment);
				const key = D("discovery-helper", { invoked: selected.invoked, cwd: selectedCwd, environment }).slice(7);
				helpers.set(key, { command: selected.invoked, cwd: selectedCwd, environment });
				return probe(command, { cwd, ...settings });
			},
			resolveCommand: (command, selectedCwd, environment) =>
				resolveCommand(command, selectedCwd ?? cwd, environment ?? env),
			native: (subject, settings) => discoverNativeAdapter(context, subject, settings),
		};
		helperSelections.set(context, helpers);
		return context;
	};
	const producer = async (): Promise<ToolIdentity> => {
		const source = await producerImplementationSources(options.implementationFiles),
			roots = source.roots;
		const declaration = {
			id: "fv-producer",
			kind: "tree",
			locator: { mode: "adapter", value: "producer-runtime", cwd: ".", subject: ["fv_evidence_run"] },
			requires: [],
			version_command: null,
			version_cwd: null,
			accept: { sha256: [], version_contains: [] },
		} as unknown as ToolDeclaration;
		const context = contextFor(declaration);
		let native: AdapterResult = { roots: [] };
		if (process.platform === "darwin" || process.platform === "linux")
			native = await discoverNativeAdapter(context, [process.execPath]);
		else throw new Error("Producer non-system runtime linkage discovery is unsupported on this OS");
		roots.push(
			{ label: "runtime/executable", path: process.execPath },
			...native.roots.map((value) => ({ ...value, label: `runtime/${value.label}` })),
		);
		if (process.platform === "linux") roots.push(...(await mappedRuntimeModules()));
		const version = await context.probe([process.execPath, "--version"]);
		const helpers = await helperClosure(context);
		roots.push(...helpers.roots);
		const files = await hasher.roots(roots),
			system_dependencies = {
				os: process.platform,
				arch: process.arch,
				release: os.release(),
				sdk: native.sdk ?? null,
			};
		await setOrigins("fv-producer", roots, files);
		return {
			id: "fv-producer",
			kind: "tree",
			locator: declaration.locator as ToolIdentity["locator"],
			digest: D("tool-content", { kind: "tree", files, packages: [], system_dependencies }),
			files,
			packages: [],
			version: {
				...version.identity,
				text: new TextDecoder("utf-8", { fatal: true })
					.decode(Buffer.concat([version.stdout, version.stderr]))
					.replace(/^[ \t\r\n]+|[ \t\r\n]+$/gu, ""),
			},
			discovery: [...new Set([...(native.discovery ?? []), ...(helpers.discovery ?? [])])],
			system_dependencies,
			requires: [],
		};
	};
	const identify = async (id: string): Promise<ToolIdentity> => {
		if (id === "fv-producer") return producer();
		const declaration = declarations.get(id);
		if (!declaration) throw new Error(`Unknown toolchain ${id}`);
		const context = contextFor(declaration),
			locator = declaration.locator;
		let roots: ToolRoot[], result: AdapterResult | undefined;
		let identityKind = declaration.kind;
		if (locator.mode === "adapter") {
			const key = D("adapter-selection", {
				generation,
				declaration,
				environment: env,
				applications: context.applicationContexts,
				commands: context.commandContexts,
			});
			let promise = discoveries.get(key);
			if (!promise) {
				promise = (async () => {
					switch (locator.value) {
						case "python-runtime":
							return discoverPythonAdapter(context);
						case "darwin-native":
							if (process.platform !== "darwin") throw new Error("darwin-native requires Darwin");
							const declaredNative = await discoverNativeAdapter(context, context.subject, {
								drivers: { compiler: context.effectiveEnv.CC ?? "cc" },
							});
							if (!declaredNative.sdk || !declaredNative.roots.some((root) => root.label === "sdk-settings"))
								throw new Error("Declared darwin-native family has no actual selected SDK settings");
							return declaredNative;
						case "node-toolchain":
							return discoverNodeAdapter(context);
						case "cargo-toolchain":
						case "kani-toolchain":
							return discoverRustAdapter(context);
						case "quint-backends":
							return identifyQuint(context);
						case "lean-toolchain":
							return identifyLean(context);
						default:
							throw new Error(`Unknown tool adapter: ${locator.value}`);
					}
				})();
				discoveries.set(key, promise);
			}
			result = await promise;
			roots = [...result.roots];
			adapters.set(id, result);
			for (const resource of result.resourceRequirements ?? [])
				for (const application of context.applicationContexts)
					if (!application.recipe.resources.includes(resource))
						throw new Error(`Missing adapter resource ${resource} for ${application.recipe.recipe_id}`);
			await result.preDispatch?.();
		} else {
			let selected: string;
			if (locator.mode === "command") selected = (await resolveCommand(locator.value, context.cwd)).realpath;
			else if (locator.mode === "path") {
				if (locator.value.startsWith("~")) throw new Error("Tool paths cannot expand HOME");
				selected = await canonicalToolPath(path.resolve(root, locator.value));
			} else {
				let parent = path.dirname((await resolveCommand(locator.value, context.cwd)).realpath);
				for (let count = 0; count < locator.parent_levels; count++) {
					const next = path.dirname(parent);
					if (next === parent) throw new Error("Command-relative locator ascends beyond root");
					parent = next;
				}
				selected = await canonicalToolPath(path.resolve(parent, locator.subpath));
			}
			const stat = await fs.stat(selected);
			if (declaration.kind === "tree" ? !stat.isDirectory() : !stat.isFile())
				throw new Error(`Tool locator kind mismatch: ${id}`);
			if (declaration.kind === "executable") await fs.access(selected, fs.constants.X_OK);
			roots = [{ label: ".", path: selected }];
			// shortcut: Darwin tree child launch environments remain unmodeled; bind actual launcher context before enabling reuse.
			if (process.platform === "linux") {
				const linked = await linuxLinkage(context, await nativePayloads(roots));
				if (linked.length) {
					result = { roots, fileRequirements: [{ ids: [id], files: linked.map((value) => value.path) }] };
					adapters.set(id, result);
				}
			} else if (process.platform === "darwin" && declaration.kind !== "tree") {
				const invoked =
					locator.mode === "command"
						? (await resolveCommand(locator.value, context.cwd)).invoked
						: path.resolve(root, locator.value);
				const rustupDriver =
					locator.mode !== "command-relative" &&
					["cargo", "rustc"].includes(path.basename(locator.value)) &&
					(await isRustupProxy({ invoked, realpath: selected }));
				const native = await discoverNativeAdapter(
					context,
					rustupDriver
						? [locator.mode === "command" ? locator.value : path.resolve(root, locator.value)]
						: await nativePayloads(roots),
				);
				const linked = native.roots.filter(
					(value) =>
						!value.label.startsWith("drivers/discovery-") && value.label !== "sdk-settings" && value.path !== selected,
				);
				if (
					linked.some(
						(value) =>
							!value.label.startsWith("non-system-libraries/") &&
							!(rustupDriver && value.label === `drivers/${path.basename(locator.value)}-0`),
					)
				)
					throw new Error("Unsupported non-adapter native driver closure: " + id);
				if (linked.length) {
					identityKind = "tree";
					roots = [
						{ label: "selected-file", path: selected },
						...linked.map((value) => ({ ...value, label: `native/${value.label}` })),
					];
				}
				result = { ...native, roots };
				adapters.set(id, result);
			}
		}
		let version: ToolIdentity["version"] = null;
		if (declaration.version_command) {
			const observed = await context.probe(declaration.version_command, {
				cwd: path.resolve(root, declaration.version_cwd!),
			});
			version = {
				...observed.identity,
				text: new TextDecoder("utf-8", { fatal: true, ignoreBOM: true })
					.decode(Buffer.concat([observed.stdout, observed.stderr]))
					.replace(/^[ \t\r\n]+|[ \t\r\n]+$/gu, ""),
			};
		}
		const helpers = await helperClosure(context);
		if (declaration.kind === "tree") roots.push(...helpers.roots);
		else if (helpers.roots.length) {
			result ??= { roots };
			result.fileRequirements = [
				...(result.fileRequirements ?? []),
				{
					ids: [id, ...declaration.requires],
					files: helpers.roots.map((value) => value.path),
					shared: true,
				},
			];
			adapters.set(id, result);
		}
		const discovery = [...(result?.discovery ?? []), ...(helpers.discovery ?? [])];
		const files = await hasher.roots(roots),
			packages = [
				...new Map((result?.packages ?? []).map((value) => [D("cargo-package", value), value])).values(),
			].sort((a, b) => utf8Compare(D("cargo-package", a), D("cargo-package", b))),
			system_dependencies = {
				os: process.platform,
				arch: process.arch,
				release: os.release(),
				sdk: result?.sdk ?? null,
			};
		await setOrigins(id, roots, files);
		const digest = D("tool-content", { kind: identityKind, files, packages, system_dependencies });
		if (declaration.accept.sha256.length && !declaration.accept.sha256.includes(digest))
			throw new Error(`Unaccepted installed tool digest: ${id}`);
		for (const required of declaration.accept.version_contains)
			if (!version?.text.includes(required)) throw new Error(`Unaccepted installed tool version: ${id}`);
		return {
			id,
			kind: identityKind,
			locator,
			digest,
			files,
			packages,
			version,
			discovery: [...new Set(discovery)],
			system_dependencies,
			requires: declaration.requires,
		};
	};
	const validateRequiredFiles = async (ids: readonly string[]): Promise<void> => {
		for (const id of ids)
			for (const requirement of adapters.get(id)?.fileRequirements ?? []) {
				const scope = closure(requirement.ids);
				if (!scope.every((selected) => ids.includes(selected))) continue;
				// Discovery helpers may be bound by the producer or another captured command dependency.
				if (requirement.shared) scope.push(...ids.filter((selected) => !scope.includes(selected)));
				for (const required of requirement.files) {
					const real = await canonicalToolPath(required),
						bytes = await hasher.file(real),
						stat = await fs.stat(real, { bigint: true }),
						inode = `${stat.dev}:${stat.ino}`;
					let bound = false;
					for (const selected of scope)
						for (const view of origins.get(selected) ?? []) {
							if (!view.directory ? view.base !== real && view.inode !== inode : !inside(view.base, real)) continue;
							const relative = view.directory ? path.relative(view.base, real).split(path.sep).join("/") : "";
							if (view.exclude?.some((ex) => relative === ex || relative.startsWith(ex.replace(/\/$/u, "") + "/")))
								continue;
							const virtual = relative ? (view.label === "." ? relative : view.label + "/" + relative) : view.label,
								entry = fileMaps.get(selected)?.get(virtual);
							if (
								entry?.kind === "file" &&
								entry.hash === bytes.hash &&
								entry.size === bytes.size &&
								entry.executable === bytes.executable
							)
								bound = true;
						}
					if (!bound)
						throw new Error(
							`Tool dependency lacks an explicit installed tool declaration: ${required} (tool=${id}; scope=${scope.join(",")})`,
						);
				}
			}
	};
	const selectedIds = (ids?: readonly string[]): string[] =>
		[...closure(ids ?? policy.toolchains.map((value) => value.id)), "fv-producer"].sort(utf8Compare);
	return {
		resolveCommand,
		async assertCommandBound(command, cwd, ids) {
			cwd = path.resolve(root, cwd);
			const actual = await resolveCommand(command[0], cwd);
			const scope = closure(ids),
				name = path.basename(command[0]),
				directory = path.dirname(actual.realpath);
			const actualStat = await fs.stat(actual.realpath);
			const sameExecutable = async (file: string): Promise<boolean> => {
				const stat = await fs.stat(file);
				return stat.dev === actualStat.dev && stat.ino === actualStat.ino;
			};
			const hasFamily = (family: string): boolean =>
				scope.some((id) => {
					const locator = declarations.get(id)!.locator;
					return locator.mode === "adapter" && locator.value === family;
				});
			const matchesFamilyCommand = async (family: string): Promise<boolean> => {
				for (const id of scope) {
					const locator = declarations.get(id)!.locator;
					if (
						locator.mode === "adapter" &&
						locator.value === family &&
						locator.subject.length &&
						(family !== "node-toolchain" || (command[1] === "exec" && command[2] === locator.subject[2])) &&
						(await resolveCommand(locator.subject[0], path.resolve(root, locator.cwd))).realpath === actual.realpath
					)
						return true;
				}
				return false;
			};
			const names = [name, path.basename(actual.realpath)];
			const quintFiles = [actual.realpath];
			if (!names.some((value) => /^(?:Python|python(?:\d+(?:\.\d+)*)?|pypy\d*|node(?:js)?|pnpm|quint)$/u.test(value)))
				for (const hint of ["python3", "python", "pypy3", "node", "nodejs", "pnpm", "quint"]) {
					const selected = await resolveCommand(hint, cwd).catch((error) => {
						if (/^Executable absent from sanitized PATH:/u.test(error.message)) return null;
						throw error;
					});
					if (selected && (await sameExecutable(selected.realpath))) {
						names.push(hint);
						if (hint === "quint") quintFiles.push(selected.realpath);
						break;
					}
				}
			const handle = await fs.open(actual.realpath, "r"),
				head = Buffer.alloc(256);
			let length: number;
			try {
				({ bytesRead: length } = await handle.read(head, 0, head.length, 0));
			} finally {
				await handle.close();
			}
			const prefix = head.subarray(0, length).toString("utf8").split("\n", 1)[0];
			const pythonCommand =
				names.some((value) => /^(?:Python|python(?:\d+(?:\.\d+)*)?|pypy\d*)$/u.test(value)) ||
				/^#!.*(?:\/| )(?:python(?:\d+(?:\.\d+)*)?|pypy\d*)(?: |$)/u.test(prefix);
			if (pythonCommand && !(await matchesFamilyCommand("python-runtime")))
				throw new Error("Python command requires a python-runtime adapter");
			for (const token of command.slice(1)) {
				if (token.startsWith("-")) continue;
				const candidate = path.resolve(cwd, token);
				const stat = await fs.stat(candidate).catch((error) => {
					if (["ENOENT", "ENOTDIR"].includes(error.code ?? "")) return null;
					throw error;
				});
				if (stat?.isFile()) quintFiles.push(await canonicalToolPath(candidate));
			}
			let quintCommand = false;
			for (const file of quintFiles) {
				const packageRoot = await packageDirectory(file).catch((error) => {
					if (/^No installed package for /u.test(error.message)) return null;
					throw error;
				});
				if (!packageRoot) continue;
				const manifest = await readPackage(packageRoot);
				if (manifest.name !== "@informalsystems/quint") continue;
				quintCommand = true;
				const bin = typeof manifest.bin === "string" ? manifest.bin : manifest.bin?.quint;
				if (typeof bin !== "string") throw new Error("Installed Quint package has no CLI declaration");
				const cli = await canonicalToolPath(path.resolve(packageRoot, bin));
				if (!inside(packageRoot, cli) || actual.realpath !== cli)
					throw new Error(
						"Unsupported Quint wrapper or package-internal command; quint-backends requires the direct installed CLI",
					);
				let matched = false;
				for (const id of scope) {
					const locator = declarations.get(id)!.locator;
					if (
						locator.mode === "adapter" &&
						locator.value === "quint-backends" &&
						locator.subject[1] === command[1] &&
						(await resolveCommand(locator.subject[0], path.resolve(root, locator.cwd))).realpath === cli
					)
						matched = true;
				}
				if (!matched) throw new Error("Quint command requires a matching quint-backends adapter");
			}
			if (!quintCommand && names.some((value) => value === "quint"))
				throw new Error("Quint command requires an installed package and matching quint-backends adapter");
			const nodeCommand =
				names.some((value) => /^(?:node(?:js)?|pnpm|corepack)$/u.test(value)) ||
				/^#!.*(?:\/| )node(?: |$)/u.test(prefix);
			if (nodeCommand) {
				if (!quintCommand && !(await matchesFamilyCommand("node-toolchain")))
					throw new Error("Node command requires a node-toolchain adapter");
				if (!quintCommand && names.some((value) => /^(?:node(?:js)?)$/u.test(value)))
					throw new Error("Unsupported direct Node command outside its selected package-manager context");
			}
			if (names.some((value) => value === "cargo" || value === "rustc")) {
				const family = name === "cargo" && command[1] === "kani" ? "kani-toolchain" : "cargo-toolchain";
				if (!hasFamily(family)) throw new Error("Rust command requires a " + family + " adapter");
			}
			const leanCommand =
				["lean", "lake"].includes(name) ||
				(name === "elan" &&
					command[1] === "run" &&
					command.slice(3).some((arg) => ["lean", "lake"].includes(path.basename(arg)))) ||
				(
					await Promise.all(
						["lean", "lake"].map((tool) =>
							fs.stat(path.join(directory, tool)).then(
								(stat) => stat.isFile(),
								() => false,
							),
						),
					)
				).every(Boolean);
			if (
				leanCommand &&
				!scope.some((id) => {
					const locator = declarations.get(id)!.locator;
					return locator.mode === "adapter" && locator.value === "lean-toolchain";
				})
			)
				throw new Error("Lean/Lake command requires a lean-toolchain adapter");
			await this.capture(ids);
			const bytes = await hasher.file(actual.realpath),
				stat = await fs.stat(actual.realpath, { bigint: true }),
				inode = `${stat.dev}:${stat.ino}`;
			for (const id of closure(ids))
				for (const view of origins.get(id) ?? []) {
					if (
						(!view.directory && view.base !== actual.realpath && view.inode !== inode) ||
						(view.directory && !inside(view.base, actual.realpath))
					)
						continue;
					const relative = view.directory ? path.relative(view.base, actual.realpath).split(path.sep).join("/") : "";
					if (view.exclude?.some((ex) => relative === ex || relative.startsWith(ex.replace(/\/$/u, "") + "/")))
						continue;
					const virtual = relative ? (view.label === "." ? relative : view.label + "/" + relative) : view.label;
					const entry = fileMaps.get(id)?.get(virtual);
					if (
						entry?.kind === "file" &&
						entry.hash === bytes.hash &&
						entry.size === bytes.size &&
						entry.executable === bytes.executable
					)
						return;
				}
			throw new Error("Command executable is absent from its declared toolchain closure: " + command[0]);
		},
		async capture(ids) {
			const result: ToolIdentity[] = [],
				selected = selectedIds(ids);
			for (const id of selected) {
				let identity = identities.get(id);
				if (!identity) {
					identity = validateToolIdentity(await identify(id));
					identities.set(id, identity);
				}
				result.push(identity);
			}
			await validateRequiredFiles(selected);
			return result;
		},
		async revalidate(ids) {
			const previous = revalidationTail;
			let release!: () => void;
			revalidationTail = new Promise((resolve) => {
				release = resolve;
			});
			await previous;
			try {
				generation++;
				probes.clear();
				discoveries.clear();
				const result: ToolIdentity[] = [];
				for (const id of selectedIds(ids)) {
					const before = identities.get(id),
						after = validateToolIdentity(await identify(id));
					if (
						before &&
						(before.digest !== after.digest ||
							D("tool-selection", { version: before.version, discovery: before.discovery }) !==
								D("tool-selection", { version: after.version, discovery: after.discovery }))
					)
						throw new Error(`Installed tool selection or bytes changed: ${id}`);
					identities.set(id, after);
					result.push(after);
				}
				await validateRequiredFiles(selectedIds(ids));
				return result;
			} finally {
				release();
			}
		},
		async implementationHash() {
			return producerImplementationHash(options.implementationFiles);
		},
		async sourceRequirements(recipe) {
			await this.capture(recipe.toolchain);
			const directories = new Set<string>(),
				files = new Set<string>(),
				inputDirectories = new Set<string>(),
				excludedPaths = new Set<string>();
			for (const id of closure(recipe.toolchain)) {
				const required = adapters.get(id)?.sourceRequirements;
				required?.directories.forEach((value) => directories.add(value));
				required?.files.forEach((value) => files.add(value));
				required?.inputDirectories?.forEach((value) => inputDirectories.add(value));
				required?.excludedPaths?.forEach((value) => excludedPaths.add(value));
			}
			return {
				directories: [...directories].sort(utf8Compare),
				files: [...files].sort(utf8Compare),
				inputDirectories: [...inputDirectories].sort(utf8Compare),
				excludedPaths: [...excludedPaths].sort(utf8Compare),
			};
		},
		async buildCache(recipe) {
			if (!recipe.build_cache) return null;
			const configuration = [];
			for (const file of recipe.build_cache.configuration)
				configuration.push({ path: file, hash: H(await fs.readFile(path.join(root, file))) });
			configuration.sort((a, b) => utf8Compare(a.path, b.path));
			await this.capture(recipe.toolchain);
			let selected: CacheNamespaceSelection[] = [];
			for (const id of closure(recipe.toolchain)) selected.push(...(adapters.get(id)?.cacheNamespaces ?? []));
			if (recipe.build_cache.system === "replay") {
				if (!recipe.attestation) throw new Error("Replay cache requires incorporated collector attestation");
				const incorporated = resolvePointer(
					parseJSON(await fs.readFile(await safeSourcePath(root, recipe.attestation.path))),
					recipe.attestation.pointer,
				) as Record<string, unknown>;
				if (
					typeof incorporated.replay_collector !== "string" ||
					!recipe.command.includes(incorporated.replay_collector) ||
					typeof incorporated.replay_runtime_outputs !== "string" ||
					!incorporated.replay_runtime_outputs.includes("The collector creates fresh external work/cache/input trees")
				)
					throw new Error("Incorporated collector has no reviewed fresh replay namespace guarantee");
				selected = [{ role: "replay-work", kind: "producer-fresh" }];
			}
			if (!selected.length)
				throw new Error(`No effective ${recipe.build_cache.system} cache namespace for ${recipe.recipe_id}`);
			const namespaces = new Map<
				string,
				{ role: string; kind: "selected-path" | "producer-fresh"; identity_hash: Hash }
			>();
			for (const value of selected) {
				const identity_hash =
					value.kind === "producer-fresh"
						? D("cache-namespace-fresh", { recipe_id: recipe.recipe_id, role: value.role })
						: H(Buffer.from(await canonicalNamespace(value.path)));
				const prior = namespaces.get(value.role);
				if (prior && prior.identity_hash !== identity_hash)
					throw new Error(`Conflicting effective cache namespace ${value.role}`);
				namespaces.set(value.role, { role: value.role, kind: value.kind, identity_hash });
			}
			return {
				system: recipe.build_cache.system,
				configuration,
				namespaces: [...namespaces.values()].sort((a, b) => utf8Compare(a.role, b.role)),
				integrity: "upstream-build-system",
			};
		},
	};
}
