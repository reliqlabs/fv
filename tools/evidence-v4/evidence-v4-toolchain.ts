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
	ToolIdentity,
} from "./evidence-v4-model";
import type { NativeSession } from "./evidence-v4-native";
import {
	ELFReader,
	ToolHasher,
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
			return path.join(await fs.realpath(current), ...suffix);
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
	const visited = new Set<string>(),
		packages = new Set<string>();
	const visit = async (file: string): Promise<void> => {
		const real = await fs.realpath(file);
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
				candidates = [
					base,
					base.replace(/\.[cm]?js$/u, ".ts"),
					base + ".ts",
					base + ".js",
					path.join(base, "index.ts"),
					path.join(base, "index.js"),
				];
			let selected: string | undefined;
			for (const candidate of candidates) {
				try {
					if ((await fs.stat(candidate)).isFile()) {
						selected = candidate;
						break;
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
		const real = await fs.realpath(file);
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
	for (const root of roots) await visit(await fs.realpath(root.path), root, "");
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
			real = await fs.realpath(candidate);
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
		const real = await fs.realpath(file);
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
			const interpreter = await fs.realpath(image.interpreter);
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
		executable = await fs.realpath(process.execPath);
	for (const line of (await fs.readFile("/proc/self/maps", "utf8")).split("\n")) {
		const match = /^\S+ \S+ \S+ \S+ (\d+)\s+(\/.*)$/u.exec(line);
		if (!match || match[1] === "0") continue;
		const mappedPath = match[2];
		if (mappedPath.startsWith("/memfd:") || mappedPath.startsWith("/dev/")) continue;
		if (mappedPath.endsWith(" (deleted)")) throw new Error("Producer runtime maps a replaced file: " + mappedPath);
		const real = await fs.realpath(mappedPath);
		if (seen.has(real) || real === executable || linuxSystemPath(real)) continue;
		seen.add(real);
		if (await reader.read(real)) roots.push({ label: "runtime/mapped/" + H(Buffer.from(real)).slice(7), path: real });
	}
	return roots;
}

export async function discoverPythonAdapter(context: AdapterContext): Promise<AdapterResult> {
	if (context.subject.length !== 1) throw new Error("Python runtime subject must select one interpreter");
	const selected = await context.resolveCommand(context.subject[0]);
	const requests: {
		file?: string;
		code?: string;
		module?: string;
		cwd: string;
		ids: readonly string[];
		argv: string[];
		paths: string[];
		flags: { isolated: boolean; safe_path: boolean };
	}[] = [];
	const pathDiscovery: ToolDiscovery[] = [];
	const importPathQuery =
		"import json,sys; print(json.dumps({'paths':sys.path,'flags':{'isolated':bool(sys.flags.isolated),'safe_path':bool(getattr(sys.flags,'safe_path',False))}},sort_keys=True))";
	for (const command of context.commandContexts ?? []) {
		if ((await context.resolveCommand(command.subject[0], command.cwd)).realpath !== selected.realpath) continue;
		const options: string[] = [];
		let index = 1;
		while (index < command.subject.length) {
			const arg = command.subject[index];
			if (arg === "-c" || arg === "-m" || arg === "--" || !arg.startsWith("-")) break;
			if (/^-[BIEsSPOuqb]+$/u.test(arg)) {
				options.push(arg);
				index++;
			} else if (arg === "-X" || arg === "-W") {
				if (!command.subject[index + 1]) throw new Error("Python interpreter option value is absent");
				options.push(arg, command.subject[index + 1]);
				index += 2;
			} else throw new Error("Unsupported Python interpreter selection: " + arg);
		}
		if (command.subject[index] === "--") index++;
		const entry = command.subject[index];
		if (!entry) throw new Error("Python application entry point is absent");
		const query = await context.probe([selected.invoked, ...options, "-B", "-c", importPathQuery], {
			cwd: command.cwd,
		});
		pathDiscovery.push(query.identity);
		const metadata = probeJSON<{ paths: string[]; flags: { isolated: boolean; safe_path: boolean } }>(query);
		if (
			!Array.isArray(metadata.paths) ||
			metadata.paths.some((value) => typeof value !== "string") ||
			!metadata.flags ||
			typeof metadata.flags.isolated !== "boolean" ||
			typeof metadata.flags.safe_path !== "boolean"
		)
			throw new Error("Incomplete Python import-path metadata");
		const paths = metadata.paths.map((value) => path.resolve(command.cwd, value));
		const common = { cwd: command.cwd, ids: command.toolchain, paths, flags: metadata.flags };
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
			if (!metadata.flags.safe_path) paths[0] = path.dirname(file);
			requests.push({ ...common, file, argv: [entry, ...command.subject.slice(index + 1)] });
		}
	}
	const code =
		"import ast,hashlib,importlib.machinery,json,os,pathlib,site,sys,sysconfig\nroot=os.path.realpath(sys.argv[1]); requests=json.loads(sys.argv[2]); stdlib=os.path.realpath(sysconfig.get_path('stdlib')); extensions=os.path.realpath(sysconfig.get_config_var('DESTSHARED')); startup=[]; startup_hooks=set(); required=set(); seen=set()\ndef within(base,p): return p==base or p.startswith(base+os.sep)\nfor p in sys.path:\n if p and os.path.isdir(p) and (p in site.getsitepackages() or p==site.getusersitepackages()): startup.extend(os.path.join(p,n) for n in sorted(os.listdir(p)) if n.endswith('.pth'))\nfor n in ('site','sitecustomize','usercustomize'):\n m=sys.modules.get(n)\n if m is not None and getattr(m,'__file__',None):\n  file=os.path.realpath(m.__file__); startup.append(file)\n  if n in ('sitecustomize','usercustomize'): startup_hooks.add(file)\nvenv=os.path.join(sys.prefix,'pyvenv.cfg')\nif os.path.isfile(venv): startup.append(venv)\nstartup=set(os.path.realpath(p) for p in startup)\ndef standard_input(p):\n return (within(stdlib,p) and 'site-packages' not in os.path.relpath(p,stdlib).split(os.sep)) or within(extensions,p)\ndef external(p):\n p=os.path.realpath(p)\n if not within(root,p) and not standard_input(p) and p not in startup: required.add(p)\ndef resolve(name,search):\n parts=name.split('.')\n if parts[0] in sys.builtin_module_names: return None\n selected=None\n for index,part in enumerate(parts):\n  selected=importlib.machinery.PathFinder.find_spec(part,search)\n  if selected is None:\n   if parts[0] in sys.stdlib_module_names: return None\n   raise RuntimeError('unknown Python import dependency: '+name)\n  if index==0 and parts[0] in sys.stdlib_module_names and selected.origin and standard_input(os.path.realpath(selected.origin)): return None\n  search=selected.submodule_search_locations\n  if index<len(parts)-1 and search is None: raise RuntimeError('unknown Python package dependency: '+name)\n return selected\n\nUNKNOWN=object()\nclass PathSnapshot(list):\n __slots__=()\n\nSYS=object(); PATHLIB=object(); OS=object(); OSPATH=object(); PATH_FACTORY=object()\ndef project_path(value,cwd):\n if value is UNKNOWN or not isinstance(value,(str,pathlib.Path)): raise RuntimeError('unresolved Python import-path mutation')\n candidate=os.path.abspath(os.path.join(cwd,str(value)))\n real=os.path.realpath(candidate)\n if not within(root,candidate) or not within(root,real): raise RuntimeError('external Python import-path mutation: '+str(value))\n current=root\n for part in os.path.relpath(candidate,root).split(os.sep):\n  if part=='.': continue\n  current=os.path.join(current,part)\n  if os.path.islink(current): raise RuntimeError('symlinked Python import-path mutation: '+current)\n return real\n\ndef expression(node,values,paths,cwd,argv,flags):\n if isinstance(node,ast.Constant): return node.value\n if isinstance(node,ast.Name): return values.get(node.id,UNKNOWN)\n if isinstance(node,(ast.List,ast.Tuple)):\n  items=[expression(item,values,paths,cwd,argv,flags) for item in node.elts]\n  return UNKNOWN if any(item is UNKNOWN for item in items) else items\n if isinstance(node,ast.UnaryOp) and isinstance(node.op,ast.USub):\n  operand=expression(node.operand,values,paths,cwd,argv,flags)\n  return -operand if isinstance(operand,int) and not isinstance(operand,bool) else UNKNOWN\n if isinstance(node,ast.BinOp):\n  left=expression(node.left,values,paths,cwd,argv,flags); right=expression(node.right,values,paths,cwd,argv,flags)\n  if isinstance(node.op,ast.Div) and isinstance(left,pathlib.Path) and isinstance(right,(str,pathlib.Path)): return left/right\n  if isinstance(node.op,ast.Add) and isinstance(left,str) and isinstance(right,str): return left+right\n  return UNKNOWN\n if isinstance(node,ast.Attribute):\n  base=expression(node.value,values,paths,cwd,argv,flags)\n  if base is SYS: return {'path':paths,'argv':argv,'flags':flags}.get(node.attr,UNKNOWN)\n  if base is PATHLIB and node.attr=='Path': return PATH_FACTORY\n  if base is OS and node.attr=='path': return OSPATH\n  if isinstance(base,dict) and base is flags: return base.get(node.attr,UNKNOWN)\n  if isinstance(base,pathlib.Path) and node.attr in ('parent','parents','name','stem','suffix'): return getattr(base,node.attr)\n  return UNKNOWN\n if isinstance(node,ast.Slice):\n  bounds=[None if item is None else expression(item,values,paths,cwd,argv,flags) for item in (node.lower,node.upper,node.step)]\n  if any(item is UNKNOWN or (item is not None and (not isinstance(item,int) or isinstance(item,bool))) for item in bounds) or bounds[2]==0: return UNKNOWN\n  return slice(*bounds)\n if isinstance(node,ast.Subscript):\n  base=expression(node.value,values,paths,cwd,argv,flags); index=expression(node.slice,values,paths,cwd,argv,flags)\n  if base is UNKNOWN or index is UNKNOWN: return UNKNOWN\n  try:\n   value=base[index]\n   return PathSnapshot(value) if isinstance(index,slice) and (base is paths or isinstance(base,PathSnapshot)) else value\n  except (IndexError,KeyError,TypeError): return UNKNOWN\n if isinstance(node,ast.Call):\n  args=[expression(arg,values,paths,cwd,argv,flags) for arg in node.args]\n  keywords={keyword.arg:expression(keyword.value,values,paths,cwd,argv,flags) for keyword in node.keywords}\n  if any(arg is UNKNOWN for arg in args) or any(value is UNKNOWN for value in keywords.values()): return UNKNOWN\n  target=expression(node.func,values,paths,cwd,argv,flags)\n  if target is PATH_FACTORY and not keywords and len(args)<=1:\n   return pathlib.Path(args[0]) if args and isinstance(args[0],(str,pathlib.Path)) else pathlib.Path('.') if not args else UNKNOWN\n  if isinstance(node.func,ast.Name) and node.func.id=='list' and node.func.id not in values and len(args)==1 and not keywords and (args[0] is paths or isinstance(args[0],PathSnapshot)): return PathSnapshot(args[0])\n  if isinstance(node.func,ast.Name) and node.func.id=='str' and node.func.id not in values and len(args)==1 and not keywords:\n   return str(args[0]) if isinstance(args[0],(str,pathlib.Path,int)) else UNKNOWN\n  if isinstance(node.func,ast.Attribute):\n   base=expression(node.func.value,values,paths,cwd,argv,flags); method=node.func.attr\n   if (base is paths or isinstance(base,PathSnapshot)) and method=='copy' and not args and not keywords: return PathSnapshot(base)\n   if base is PATH_FACTORY and method=='cwd' and not args and not keywords: return pathlib.Path(cwd)\n   if isinstance(base,pathlib.Path):\n    if method in ('exists','is_dir','is_file') and not args and not keywords:\n     candidate=os.path.abspath(os.path.join(cwd,str(base)))\n     return getattr(pathlib.Path(project_path(candidate,cwd)),method)() if within(root,candidate) else UNKNOWN\n    if method=='resolve' and not args and set(keywords)<=set(['strict']) and isinstance(keywords.get('strict',False),bool):\n     return (base if base.is_absolute() else pathlib.Path(cwd)/base).resolve(strict=keywords.get('strict',False))\n    if method=='absolute' and not args and not keywords: return pathlib.Path(os.path.abspath(os.path.join(cwd,str(base))))\n    if method in ('joinpath','with_name','with_suffix') and not keywords and all(isinstance(arg,str) for arg in args): return getattr(base,method)(*args)\n   if base is OSPATH and not keywords and all(isinstance(arg,str) for arg in args):\n    if method=='join': return os.path.join(*args)\n    if method=='dirname' and len(args)==1: return os.path.dirname(args[0])\n    if method in ('abspath','realpath','normpath') and len(args)==1:\n     value=os.path.join(cwd,args[0]) if not os.path.isabs(args[0]) else args[0]\n     return getattr(os.path,method)(value)\n  return UNKNOWN\n if isinstance(node,ast.Compare) and len(node.ops)==1:\n  left=expression(node.left,values,paths,cwd,argv,flags); right=expression(node.comparators[0],values,paths,cwd,argv,flags)\n  if left is UNKNOWN or right is UNKNOWN: return UNKNOWN\n  if isinstance(node.ops[0],ast.Eq): return left==right\n  if isinstance(node.ops[0],ast.NotEq): return left!=right\n return UNKNOWN\n\ndef path_changes(node,scope,paths,cwd,argv,flags):\n for part in ast.walk(node):\n  if isinstance(part,ast.Call) and isinstance(part.func,ast.Attribute) and (expression(part.func.value,scope,paths,cwd,argv,flags) is paths or isinstance(expression(part.func.value,scope,paths,cwd,argv,flags),PathSnapshot)): return True\n  if isinstance(part,ast.Assign):\n   for target in part.targets:\n    if isinstance(target,ast.Attribute) and target.attr=='path' and expression(target.value,scope,paths,cwd,argv,flags) is SYS: return True\n return False\n\ndef scan(source,directory,paths=None,cwd=None,argv=None,filename=None,name='__main__',flags=None,project=True):\n paths=paths if paths is not None else [os.path.abspath(p or os.getcwd()) for p in sys.path]\n cwd=cwd or os.getcwd(); argv=argv if argv is not None else list(sys.argv)\n flags=flags or dict(isolated=bool(sys.flags.isolated),safe_path=bool(getattr(sys.flags,'safe_path',False)))\n values={'__name__':name}\n if filename is not None: values['__file__']=filename\n deferred=[]\n def walk(nodes,scope,search):\n  for node in nodes:\n   try:\n    if isinstance(node,(ast.Import,ast.ImportFrom)):\n     names=[alias.name for alias in node.names] if isinstance(node,ast.Import) else [node.module] if node.module else [alias.name for alias in node.names]\n     standards={}\n     for module in names:\n      lookup=search\n      if isinstance(node,ast.ImportFrom) and node.level:\n       base=directory\n       for _ in range(node.level-1): base=os.path.dirname(base)\n       lookup=[base]\n      spec=resolve(module,lookup)\n      if spec is not None and spec.origin not in (None,'built-in','frozen'):\n       standards[module]=False; external(spec.origin); visit(spec.origin,search,cwd,argv,module,flags,project)\n      else: standards[module]=True\n     if isinstance(node,ast.Import):\n      for alias in node.names: scope[alias.asname or alias.name.split('.')[0]]={'sys':SYS,'pathlib':PATHLIB,'os':OS,'os.path':OSPATH}.get(alias.name,UNKNOWN) if standards[alias.name] else UNKNOWN\n     elif node.module=='pathlib' and standards.get(node.module,False):\n      for alias in node.names: scope[alias.asname or alias.name]=PATH_FACTORY if alias.name=='Path' else UNKNOWN\n     else:\n      for alias in node.names: scope[alias.asname or alias.name]=UNKNOWN\n    elif isinstance(node,(ast.Assign,ast.AnnAssign)):\n     value=expression(node.value,scope,search,cwd,argv,flags) if node.value else UNKNOWN\n     targets=node.targets if isinstance(node,ast.Assign) else [node.target]\n     for target in targets:\n      if isinstance(target,ast.Name): scope[target.id]=value\n      elif isinstance(target,ast.Attribute) and target.attr=='path' and expression(target.value,scope,search,cwd,argv,flags) is SYS:\n       if not project: continue\n       if not isinstance(value,list): raise RuntimeError('unresolved Python sys.path assignment')\n       search[:]=list(value) if value is search or isinstance(value,PathSnapshot) else [project_path(item,cwd) for item in value]\n      elif isinstance(target,ast.Subscript):\n       receiver=expression(target.value,scope,search,cwd,argv,flags)\n       if receiver is search or isinstance(receiver,PathSnapshot):\n        if not project: continue\n        index=expression(target.slice,scope,search,cwd,argv,flags)\n        if not isinstance(index,slice) or index.start not in (None,0) or index.stop is not None or index.step not in (None,1): raise RuntimeError('unsupported Python sys.path partial subscript mutation')\n        if value is search or isinstance(value,PathSnapshot): restored=list(value)\n        elif isinstance(value,list): restored=[project_path(item,cwd) for item in value]\n        else: raise RuntimeError('unresolved Python sys.path slice restoration')\n        receiver[index]=restored\n       elif isinstance(receiver,list):\n        index=expression(target.slice,scope,search,cwd,argv,flags)\n        if index is UNKNOWN or value is UNKNOWN: receiver[:]=[UNKNOWN]\n        else:\n         try: receiver[index]=value\n         except (IndexError,TypeError,ValueError): receiver[:]=[UNKNOWN]\n    elif isinstance(node,ast.Expr) and isinstance(node.value,ast.Call):\n     call=node.value\n     receiver=expression(call.func.value,scope,search,cwd,argv,flags) if isinstance(call.func,ast.Attribute) else UNKNOWN\n     if isinstance(call.func,ast.Attribute) and isinstance(receiver,list):\n      if not project: continue\n      args=[expression(arg,scope,search,cwd,argv,flags) for arg in call.args]\n      bounded=receiver is search or isinstance(receiver,PathSnapshot)\n      if call.keywords or any(item is UNKNOWN for item in args):\n       if bounded: raise RuntimeError('unresolved Python import-path/list mutation')\n       receiver[:]=[UNKNOWN]; continue\n      normalize=lambda item: project_path(item,cwd) if bounded else item\n      if call.func.attr=='insert' and len(args)==2 and isinstance(args[0],int) and not isinstance(args[0],bool): receiver.insert(args[0],normalize(args[1]))\n      elif call.func.attr=='append' and len(args)==1: receiver.append(normalize(args[0]))\n      elif call.func.attr=='extend' and len(args)==1 and isinstance(args[0],list): receiver.extend(normalize(item) for item in args[0])\n      elif call.func.attr=='copy' and not args: continue\n      else:\n       if bounded: raise RuntimeError('unresolved Python import-path/list mutation')\n       receiver[:]=[UNKNOWN]\n    elif isinstance(node,ast.If):\n     condition=expression(node.test,scope,search,cwd,argv,flags)\n     if isinstance(condition,bool): walk(node.body if condition else node.orelse,scope,search)\n     else:\n      if project and path_changes(node,scope,search,cwd,argv,flags): raise RuntimeError('unresolved conditional Python import-path setup')\n      walk(node.body,dict(scope),list(search)); walk(node.orelse,dict(scope),list(search))\n    elif isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):\n     deferred.append((node,scope))\n    elif isinstance(node,ast.ClassDef): walk(node.body,dict(scope),search)\n    elif isinstance(node,ast.Try):\n     if not node.handlers:\n      walk(node.body,scope,search); walk(node.orelse,scope,search); walk(node.finalbody,scope,search)\n     else:\n      if project and path_changes(node,scope,search,cwd,argv,flags): raise RuntimeError('unresolved exceptional Python import-path setup')\n      walk(node.body,dict(scope),list(search))\n      for handler in node.handlers: walk(handler.body,dict(scope),list(search))\n      walk(node.orelse,dict(scope),list(search)); walk(node.finalbody,scope,search)\n    elif isinstance(node,(ast.For,ast.AsyncFor,ast.While,ast.With,ast.AsyncWith)):\n     walk(node.body,dict(scope),list(search))\n     if hasattr(node,'orelse'): walk(node.orelse,dict(scope),list(search))\n   except (RuntimeError,TypeError,ValueError,OSError) as error:\n    raise RuntimeError(f\"{filename or '<inline cwd='+cwd+'>'}:{getattr(node,'lineno','?')}: {error}\") from error\n walk(ast.parse(source,filename=filename or '<inline cwd='+cwd+'>').body,values,paths)\n while deferred:\n  function,outer=deferred.pop(0); local=dict(outer)\n  for arg in function.args.posonlyargs+function.args.args+function.args.kwonlyargs: local[arg.arg]=UNKNOWN\n  if function.args.vararg: local[function.args.vararg.arg]=UNKNOWN\n  if function.args.kwarg: local[function.args.kwarg.arg]=UNKNOWN\n  walk(function.body,local,list(paths))\n\nsource_inputs={}\ndef visit(file,paths=None,cwd=None,argv=None,name='__main__',flags=None,project=True):\n real=os.path.realpath(file)\n if real in seen: return\n seen.add(real)\n if real.endswith('.py'):\n  with open(real,'rb') as stream: data=stream.read()\n  source_inputs[real]='sha256:'+hashlib.sha256(data).hexdigest()\n  scan(data.decode('utf-8'),os.path.dirname(real),paths,cwd,argv,real,name,flags,project)\n\nfor module in list(sys.modules.values()):\n file=getattr(module,'__file__',None)\n if file: external(file)\nfor p in startup:\n if p.endswith('.py') and (p in startup_hooks or not standard_input(p)): visit(p,project=False)\n elif p.endswith('.pth'):\n  with open(p,'rb') as stream: data=stream.read()\n  source_inputs[p]='sha256:'+hashlib.sha256(data).hexdigest()\n  for line in data.decode('utf-8').splitlines():\n   if line.startswith(('import ','import'+chr(9))): scan(line,os.path.dirname(p),project=False)\nrequirements=[dict(ids=json.loads(sys.argv[3]),files=sorted(required),paths=list(sys.path),inputs=sorted(source_inputs.items()))]\nfor request in requests:\n required=set(); seen=set(); source_inputs={}; paths=list(request['paths'])\n if 'file' in request: visit(request['file'],paths,request['cwd'],request['argv'],flags=request['flags'])\n elif 'code' in request: scan(request['code'],request['cwd'],paths,request['cwd'],request['argv'],flags=request['flags'])\n else:\n  spec=resolve(request['module'],paths)\n  if spec is not None:\n   if spec.submodule_search_locations:\n    if spec.origin not in (None,'built-in','frozen'): external(spec.origin); visit(spec.origin,paths,request['cwd'],request['argv'],request['module'],request['flags'])\n    main=importlib.machinery.PathFinder.find_spec(request['module']+'.__main__',spec.submodule_search_locations)\n    if main is None or main.origin is None: raise RuntimeError('unknown Python module entry point: '+request['module'])\n    external(main.origin); visit(main.origin,paths,request['cwd'],[main.origin]+request['argv'][1:],'__main__',request['flags'])\n   elif spec.origin not in (None,'built-in','frozen'):\n    external(spec.origin); visit(spec.origin,paths,request['cwd'],[spec.origin]+request['argv'][1:],'__main__',request['flags'])\n requirements.append(dict(ids=request['ids'],files=sorted(required),paths=paths,inputs=sorted(source_inputs.items())))\nprint(json.dumps(dict(executable=os.path.realpath(sys.executable),stdlib=stdlib,extensions=extensions,startup=sorted(startup),requirements=requirements),sort_keys=True))";
	const result = await context.probe([
		selected.invoked,
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
	for (const root of native.roots)
		if (root.label.startsWith("non-system-libraries/"))
			roots.push({
				label: `extension-modules/native/${root.label.slice("non-system-libraries/".length)}`,
				path: root.path,
			});
	return {
		roots,
		discovery: [...new Set([...pathDiscovery, result.identity, ...(native.discovery ?? [])])],
		sdk: native.sdk,
		fileRequirements: data.requirements,
	};
}

export async function discoverNativeAdapter(
	context: AdapterContext,
	subjects = context.subject,
	options: NativeAdapterOptions = {},
): Promise<AdapterResult> {
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
			? { invoked: argv[0], realpath: await fs.realpath(argv[0]) }
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

		if (["cargo", "rustc"].includes(name) && path.basename(command.realpath).startsWith("rustup")) {
			const rustup = await context.resolveCommand("rustup", cwd);
			const probe = await context.probe([rustup.invoked, "which", name], { cwd });
			discovery.push(probe.identity);
			command = { invoked: command.invoked, realpath: await fs.realpath(probeText(probe).trim()) };
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
			const config = await fs.realpath(match[1].replace(/^"|"$/gu, ""));
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
					path: await fs.realpath(quoted[i]),
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
	const nativeFiles = roots.filter((root) => root.label.startsWith("drivers/")).map((root) => root.path);
	const visited = new Set<string>(),
		elfFiles: string[] = [];
	const loadCommands = new Map<string, Promise<ReturnType<typeof parseMachOLoadCommands>>>();
	const readLoadCommands = async (image: string): Promise<ReturnType<typeof parseMachOLoadCommands>> => {
		let pending = loadCommands.get(image);
		if (!pending) {
			pending = (async () => {
				const otool = await context.resolveCommand("otool", cwd);
				if (!otool.realpath.startsWith("/usr/bin/") && !otool.realpath.startsWith("/Library/Developer/"))
					roots.push({ label: "drivers/discovery-otool", path: otool.realpath });
				const loads = await context.probe([otool.invoked, "-l", image], { cwd });
				discovery.push(loads.identity);
				return parseMachOLoadCommands(probeText(loads));
			})();
			loadCommands.set(image, pending);
		}
		return pending;
	};
	const inspect = async (file: string, executable: string, inheritedRpaths: readonly string[] = []): Promise<void> => {
		const real = await fs.realpath(file);
		const executableReal = path.isAbsolute(executable)
			? await fs.realpath(executable)
			: (await context.resolveCommand(executable, cwd)).realpath;
		const inputContext = D("native-input-context", {
			image: real,
			executable: executableReal,
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
					interpreter = tokens[1];
				}
				const runtime = await context.resolveCommand(interpreter, cwd);
				const label = `drivers/shebang-${path.basename(runtime.realpath)}`;
				roots.push({ label, path: runtime.realpath });
				await inspect(runtime.realpath, runtime.realpath);
			}
			return;
		}
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
					existing.push(await fs.realpath(candidate));
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
	for (const file of nativeFiles)
		await inspect(file, /\.(?:node|dylib|so(?:\.\d+)*)$/u.test(file) ? (subjects[0] ?? file) : file);
	if (elfFiles.length) roots.push(...(await linuxLinkage(context, elfFiles)));
	let sdk: AdapterResult["sdk"] = null;
	if (sdkPath && process.platform !== "darwin") throw new Error("SDK selection is Darwin-only");
	if (sdkPath) {
		const real = await fs.realpath(sdkPath);
		let settings = path.join(real, "SDKSettings.json"),
			data: Record<string, any>;
		try {
			data = parseJSON(await fs.readFile(settings)) as Record<string, any>;
		} catch (error) {
			if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
			settings = path.join(real, "SDKSettings.plist");
			const plutil = await context.resolveCommand("plutil", cwd);
			const probe = await context.probe([plutil.invoked, "-convert", "json", "-o", "-", settings], { cwd });
			discovery.push(probe.identity);
			data = probeJSON(probe);
		}
		const version = data.Version;
		if (typeof version !== "string" || !version) throw new Error("Selected SDK lacks version identity");
		sdk = { version, settings_hash: H(await fs.readFile(settings)) };
		roots.push({ label: "sdk-settings", path: settings });
	}
	return { roots, discovery, sdk };
}

export async function discoverNodeAdapter(context: AdapterContext): Promise<AdapterResult> {
	if (path.basename(context.subject[0] ?? "") !== "pnpm" || context.subject[1] !== "exec" || !context.subject[2])
		throw new Error("Unsupported Node toolchain subject");
	const node = await context.resolveCommand("node"),
		launcher = await context.resolveCommand(context.subject[0]);
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
		pnpmRoot = await fs.realpath(selection.root);
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
	const roots: ToolRoot[] = [
		{ label: "node", path: node.realpath },
		{ label: "pnpm", path: pnpmRoot, exclude: ["node_modules"] },
		...packages,
	];
	if (corepackRoot) roots.push({ label: "corepack", path: corepackRoot, exclude: ["node_modules"] });
	roots.push(...(await packageRoots(context, [pnpmRoot, ...(corepackRoot ? [corepackRoot] : [])])));
	const native = await context.native(await nativePayloads(roots));
	roots.push(...native.roots.filter((root) => root.label.startsWith("non-system-libraries/")));
	discovery.push(...(native.discovery ?? []));
	const pnpmBin = typeof pnpmManifest.bin === "string" ? pnpmManifest.bin : pnpmManifest.bin?.pnpm;
	if (typeof pnpmBin !== "string" || !pnpmBin) throw new Error("Selected pnpm package has no declared executable");
	const pnpmExecutable = await fs.realpath(path.resolve(pnpmRoot, pnpmBin));
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
		const probe = await context.probe([node.invoked, "-e", code, candidates[0]]);
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
		const real = await fs.realpath(file);
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
	const hasher = new ToolHasher(),
		identities = new Map<string, ToolIdentity>(),
		adapters = new Map<string, AdapterResult>(),
		origins = new Map<string, ToolRoot[]>();
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
	const resolveCommand = async (command: string, cwd = root): Promise<{ invoked: string; realpath: string }> => {
		if (!command || command.includes("\0") || command.startsWith("~")) throw new Error("Invalid executable selection");
		const directory = path.resolve(root, cwd),
			candidates = command.includes(path.sep)
				? [path.resolve(directory, command)]
				: env.PATH === undefined
					? []
					: env.PATH.split(path.delimiter).map((entry) => path.resolve(directory, entry, command));
		for (const invoked of candidates) {
			try {
				const realpath = await fs.realpath(invoked),
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
			environment = settings.env ?? env,
			selected = await resolveCommand(command[0], cwd);
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
			probe: (command, settings) => probe(command, { cwd, ...settings }),
			resolveCommand: (command, selectedCwd) => resolveCommand(command, selectedCwd ?? cwd),
			native: (subject, settings) => discoverNativeAdapter(context, subject, settings),
		};
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
			...native.roots
				.filter((value) => value.label.startsWith("non-system-libraries/"))
				.map((value) => ({ ...value, label: `runtime/${value.label}` })),
		);
		if (process.platform === "linux") roots.push(...(await mappedRuntimeModules()));
		const version = await context.probe([process.execPath, "--version"]);
		const files = await hasher.roots(roots),
			system_dependencies = {
				os: process.platform,
				arch: process.arch,
				release: os.release(),
				sdk: native.sdk ?? null,
			};
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
			discovery: native.discovery ?? [],
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
		if (locator.mode === "adapter") {
			const key = D("adapter-selection", {
				generation,
				locator,
				environment: env,
				contexts: context.applicationContexts.map((value) => ({ command: value.subject, cwd: relativeCwd(value.cwd) })),
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
			roots = result.roots;
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
				selected = await fs.realpath(path.resolve(root, locator.value));
			} else {
				let parent = path.dirname((await resolveCommand(locator.value, context.cwd)).realpath);
				for (let count = 0; count < locator.parent_levels; count++) {
					const next = path.dirname(parent);
					if (next === parent) throw new Error("Command-relative locator ascends beyond root");
					parent = next;
				}
				selected = await fs.realpath(path.resolve(parent, locator.subpath));
			}
			const stat = await fs.stat(selected);
			if (declaration.kind === "tree" ? !stat.isDirectory() : !stat.isFile())
				throw new Error(`Tool locator kind mismatch: ${id}`);
			if (declaration.kind === "executable") await fs.access(selected, fs.constants.X_OK);
			roots = [{ label: ".", path: selected }];
			if (process.platform === "linux") {
				const linked = await linuxLinkage(context, await nativePayloads(roots));
				if (linked.length) {
					result = { roots, fileRequirements: [{ ids: [id], files: linked.map((value) => value.path) }] };
					adapters.set(id, result);
				}
			}
		}
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
		origins.set(id, roots);
		const digest = D("tool-content", { kind: declaration.kind, files, packages, system_dependencies });
		let version: ToolIdentity["version"] = null;
		if (declaration.version_command) {
			const observed = await probe(declaration.version_command, { cwd: path.resolve(root, declaration.version_cwd!) });
			version = {
				...observed.identity,
				text: new TextDecoder("utf-8", { fatal: true, ignoreBOM: true })
					.decode(Buffer.concat([observed.stdout, observed.stderr]))
					.replace(/^[ \t\r\n]+|[ \t\r\n]+$/gu, ""),
			};
		}
		if (declaration.accept.sha256.length && !declaration.accept.sha256.includes(digest))
			throw new Error(`Unaccepted installed tool digest: ${id}`);
		for (const required of declaration.accept.version_contains)
			if (!version?.text.includes(required)) throw new Error(`Unaccepted installed tool version: ${id}`);
		return {
			id,
			kind: declaration.kind,
			locator,
			digest,
			files,
			packages,
			version,
			discovery: [...new Set(result?.discovery ?? [])],
			system_dependencies,
			requires: declaration.requires,
		};
	};
	const validateRequiredFiles = async (ids: readonly string[]): Promise<void> => {
		for (const id of ids)
			for (const requirement of adapters.get(id)?.fileRequirements ?? []) {
				const scope = closure(requirement.ids);
				if (!scope.every((selected) => ids.includes(selected))) continue;
				for (const required of requirement.files) {
					const real = await fs.realpath(required),
						bytes = await hasher.file(real);
					let bound = false;
					for (const selected of scope)
						for (const view of origins.get(selected) ?? []) {
							const base = await fs.realpath(view.path),
								stat = await fs.stat(base);
							if (stat.isFile() ? base !== real : !inside(base, real)) continue;
							const relative = stat.isDirectory() ? path.relative(base, real).split(path.sep).join("/") : "";
							if (view.exclude?.some((ex) => relative === ex || relative.startsWith(ex.replace(/\/$/u, "") + "/")))
								continue;
							const virtual = relative ? (view.label === "." ? relative : view.label + "/" + relative) : view.label,
								entry = identities.get(selected)?.files.find((file) => file.path === virtual);
							if (
								entry?.kind === "file" &&
								entry.hash === bytes.hash &&
								entry.size === bytes.size &&
								entry.executable === bytes.executable
							)
								bound = true;
						}
					if (!bound) throw new Error("Python dependency lacks an explicit installed tool declaration: " + required);
				}
			}
	};
	const selectedIds = (ids?: readonly string[]): string[] =>
		[...closure(ids ?? policy.toolchains.map((value) => value.id)), "fv-producer"].sort(utf8Compare);
	return {
		resolveCommand,
		async assertCommandBound(command, cwd, ids) {
			const actual = await resolveCommand(command[0], cwd),
				bytes = await hasher.file(actual.realpath);
			await this.capture(ids);
			for (const id of closure(ids))
				for (const view of origins.get(id) ?? []) {
					const base = await fs.realpath(view.path),
						stat = await fs.stat(base);
					if ((stat.isFile() && base !== actual.realpath) || (stat.isDirectory() && !inside(base, actual.realpath)))
						continue;
					const relative = stat.isDirectory() ? path.relative(base, actual.realpath).split(path.sep).join("/") : "";
					if (view.exclude?.some((ex) => relative === ex || relative.startsWith(ex.replace(/\/$/u, "") + "/")))
						continue;
					const virtual = relative ? (view.label === "." ? relative : view.label + "/" + relative) : view.label;
					const entry = identities.get(id)?.files.find((file) => file.path === virtual);
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
