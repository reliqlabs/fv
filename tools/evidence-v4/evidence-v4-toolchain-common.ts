import * as fs from "node:fs/promises";
import * as path from "node:path";
import { createHash } from "node:crypto";
import { D, H, parseJSON, utf8Compare } from "./evidence-v4-model";
import type { Cwd, Hash, PackageIdentity, Recipe, ToolDeclaration, ToolDiscovery, ToolFile } from "./evidence-v4-model";
import type { NativeSession } from "./evidence-v4-native";

export type ToolRoot = { label: string; path: string; exclude?: readonly string[]; linkBoundary?: string };
export type CacheNamespaceSelection =
	| { role: string; kind: "selected-path"; path: string }
	| { role: string; kind: "producer-fresh" };
export type NativeAdapterOptions = {
	cwd?: string;
	target?: string;
	host?: string;
	sdk?: string;
	flags?: readonly string[];
	drivers?: Record<string, string | readonly string[]>;
};
export type ProbeResult = { stdout: Buffer; stderr: Buffer; code: number; identity: ToolDiscovery };
export type AdapterResult = {
	roots: ToolRoot[];
	packages?: PackageIdentity[];
	discovery?: ToolDiscovery[];
	sdk?: { version: string; settings_hash: Hash } | null;
	cacheNamespaces?: CacheNamespaceSelection[];
	preDispatch?: () => Promise<void>;
	resourceRequirements?: readonly string[];
	fileRequirements?: readonly { ids: readonly string[]; files: readonly string[]; shared?: boolean }[];
	sourceRequirements?: {
		directories: readonly string[];
		files: readonly string[];
		inputDirectories?: readonly string[];
		excludedPaths?: readonly string[];
	};
};
export type AdapterContext = {
	root: string;
	cwd: string;
	cwdRelative: Cwd;
	subject: readonly string[];
	effectiveEnv: Readonly<Record<string, string>>;
	declaration: ToolDeclaration;
	signal?: AbortSignal;
	session: NativeSession;
	applicationContexts: readonly { recipe: Recipe; subject: readonly string[]; cwd: string }[];
	commandContexts?: readonly { subject: readonly string[]; cwd: string; toolchain: readonly string[] }[];
	otherCommandBound?(command: {
		subject: readonly string[];
		cwd: string;
		toolchain: readonly string[];
	}): Promise<boolean>;
	probe(command: readonly string[], options?: { cwd?: string; env?: Record<string, string> }): Promise<ProbeResult>;
	resolveCommand(
		command: string,
		cwd?: string,
		environment?: Record<string, string>,
	): Promise<{ invoked: string; realpath: string }>;
	native(subject: readonly string[], options?: NativeAdapterOptions): Promise<AdapterResult>;
};

export function probeText(result: ProbeResult): string {
	const decoder = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true });
	return decoder.decode(result.stdout);
}
export function probeJSON<T = unknown>(result: ProbeResult): T {
	return parseJSON(result.stdout) as T;
}
export function inside(root: string, value: string): boolean {
	return value === root || value.startsWith(root + path.sep);
}
async function canonicalDirectory(value: string): Promise<string> {
	const parts = value.split(path.sep);
	if (!parts.includes("..")) return fs.realpath(value);
	let directory = path.isAbsolute(value) ? path.parse(value).root : ".",
		pending: string[] = [];
	for (const part of parts) {
		if (!part || part === ".") continue;
		if (part === "..") {
			// Resolve preceding symlinks before applying the parent traversal.
			directory = path.dirname(await fs.realpath(path.join(directory, ...pending)));
			pending = [];
		} else pending.push(part);
	}
	return fs.realpath(path.join(directory, ...pending));
}

export async function canonicalToolPath(value: string): Promise<string> {
	let current = value,
		links: Set<string> | undefined;
	for (;;) {
		if (!current) return fs.realpath(current);
		const directory = await canonicalDirectory(path.dirname(current)),
			file = path.join(directory, path.basename(current)),
			stat = await fs.lstat(file);
		if (stat.isDirectory()) return fs.realpath(file);
		// Darwin realpath can return another hardlink spelling for developer shims.
		if (!stat.isSymbolicLink()) {
			if (current.endsWith(path.sep)) {
				const error = new Error("Tool path is not a directory: " + current) as NodeJS.ErrnoException;
				error.code = "ENOTDIR";
				throw error;
			}
			return file;
		}
		links ??= new Set<string>();
		if (links.has(file)) throw new Error("Tool symlink cycle: " + file);
		links.add(file);
		const target = await fs.readlink(file);
		current =
			(path.isAbsolute(target) ? target : directory + path.sep + target) + (current.endsWith(path.sep) ? path.sep : "");
	}
}

export function toolPath(value: string): string {
	if (value === ".") return value;
	if (
		!value ||
		value.startsWith("/") ||
		value.startsWith("~") ||
		/[\\\x00-\x1f\x7f-\x9f]/u.test(value) ||
		value.split("/").some((p) => !p || p === "." || p === "..")
	)
		throw new Error(`Invalid tool path: ${value}`);
	return value;
}

const MACHO_DYLIB_LOAD_COMMANDS: Record<string, true> = {
	LC_LOAD_DYLIB: true,
	LC_LOAD_WEAK_DYLIB: true,
	LC_REEXPORT_DYLIB: true,
	LC_LOAD_UPWARD_DYLIB: true,
	LC_LAZY_LOAD_DYLIB: true,
};
export function parseMachOLoadCommands(text: string): { dependencies: string[]; rpaths: string[] } {
	const blocks = text.split(/^[ \t]*Load command [0-9]+[ \t]*$/gmu);
	if (blocks.length === 1) throw new Error("Mach-O load-command metadata is absent");
	const dependencies: string[] = [],
		rpaths: string[] = [];
	for (const block of blocks.slice(1)) {
		const command = /^[ \t]*cmd (LC_[A-Z0-9_]+)[ \t]*$/mu.exec(block)?.[1];
		if (!command) throw new Error("Mach-O load-command type is absent");
		if (command === "LC_DYLD_ENVIRONMENT") throw new Error("Unsupported Mach-O LC_DYLD_ENVIRONMENT");
		if (command === "LC_RPATH") {
			const rpath = /^[ \t]*path (.+?) \(offset [0-9]+\)[ \t]*$/mu.exec(block)?.[1];
			if (!rpath) throw new Error("Mach-O LC_RPATH path is absent");
			rpaths.push(rpath);
		} else if (MACHO_DYLIB_LOAD_COMMANDS[command]) {
			const dependency = /^[ \t]*name (.+?) \(offset [0-9]+\)[ \t]*$/mu.exec(block)?.[1];
			if (!dependency) throw new Error("Mach-O dylib load name is absent: " + command);
			dependencies.push(dependency);
		}
	}
	return { dependencies, rpaths };
}

export type LinuxELF = {
	machine: number;
	bits: 32 | 64;
	interpreter: string | null;
	soname: string | null;
	needed: readonly string[];
	rpath: readonly string[];
	runpath: readonly string[];
};
export class ELFReader {
	private readonly cache = new Map<string, { stamp: string; value: LinuxELF | null }>();
	async read(file: string): Promise<LinuxELF | null> {
		const before = await fs.stat(file, { bigint: true });
		if (!before.isFile()) throw new Error("ELF input is not a regular file: " + file);
		if (before.size > BigInt(Number.MAX_SAFE_INTEGER)) throw new Error("Oversize ELF input: " + file);
		const size = Number(before.size),
			stamp = [before.dev, before.ino, before.size, before.mode, before.mtimeNs, before.ctimeNs].join(":"),
			key = before.dev + ":" + before.ino;
		const cached = this.cache.get(key);
		if (cached?.stamp === stamp) return cached.value;
		const handle = await fs.open(file, "r");
		let value: LinuxELF | null = null;
		try {
			const opened = await handle.stat({ bigint: true });
			if (opened.dev !== before.dev || opened.ino !== before.ino) throw new Error("ELF changed while opening: " + file);
			const read = async (offset: number, length: number): Promise<Buffer> => {
				if (
					!Number.isSafeInteger(offset) ||
					!Number.isSafeInteger(length) ||
					offset < 0 ||
					length < 0 ||
					offset + length > size
				)
					throw new Error("ELF metadata escapes file: " + file);
				const bytes = Buffer.alloc(length);
				let done = 0;
				while (done < length) {
					const result = await handle.read(bytes, done, length - done, offset + done);
					if (!result.bytesRead) throw new Error("Truncated ELF metadata: " + file);
					done += result.bytesRead;
				}
				return bytes;
			};
			const header = await read(0, Math.min(64, size));
			if (header.length >= 4 && header[0] === 0x7f && header[1] === 0x45 && header[2] === 0x4c && header[3] === 0x46) {
				const bits = header[4] === 1 ? 32 : header[4] === 2 ? 64 : 0,
					little = header[5] === 1;
				if (!bits || ![1, 2].includes(header[5]) || header[6] !== 1 || header.length < (bits === 64 ? 64 : 52))
					throw new Error("Unsupported ELF encoding: " + file);
				const u16 = (bytes: Buffer, offset: number) =>
					little ? bytes.readUInt16LE(offset) : bytes.readUInt16BE(offset);
				const u32 = (bytes: Buffer, offset: number) =>
					little ? bytes.readUInt32LE(offset) : bytes.readUInt32BE(offset);
				const u64 = (bytes: Buffer, offset: number) =>
					little ? bytes.readBigUInt64LE(offset) : bytes.readBigUInt64BE(offset);
				const safe = (number: bigint): number => {
					if (number > BigInt(Number.MAX_SAFE_INTEGER)) throw new Error("Oversize ELF metadata: " + file);
					return Number(number);
				};
				const machine = u16(header, 18),
					type = u16(header, 16);
				if (type !== 1 && type !== 2 && type !== 3) throw new Error("Unsupported ELF image type: " + file);
				const phoff = bits === 64 ? safe(u64(header, 32)) : u32(header, 28),
					stride = u16(header, bits === 64 ? 54 : 42),
					count = u16(header, bits === 64 ? 56 : 44);
				if (count === 0xffff || (count && stride < (bits === 64 ? 56 : 32)))
					throw new Error("Unsupported ELF program-header encoding: " + file);
				const programs = await read(phoff, stride * count),
					loads: { address: bigint; offset: number; size: number }[] = [];
				let interpreter: string | null = null,
					dynamic: { offset: number; size: number } | null = null;
				const decode = (bytes: Buffer): string => {
					const end = bytes.indexOf(0);
					if (end < 0) throw new Error("Unterminated ELF string: " + file);
					return new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(bytes.subarray(0, end));
				};
				for (let index = 0; index < count; index++) {
					const base = index * stride,
						kind = u32(programs, base),
						offset = bits === 64 ? safe(u64(programs, base + 8)) : u32(programs, base + 4),
						address = bits === 64 ? u64(programs, base + 16) : BigInt(u32(programs, base + 8)),
						length = bits === 64 ? safe(u64(programs, base + 32)) : u32(programs, base + 16);
					if (offset + length > size) throw new Error("ELF segment escapes file: " + file);
					if (kind === 1) loads.push({ address, offset, size: length });
					if (kind === 2) {
						if (dynamic) throw new Error("Duplicate ELF dynamic segment: " + file);
						dynamic = { offset, size: length };
					}
					if (kind === 3) {
						if (interpreter) throw new Error("Duplicate ELF interpreter: " + file);
						interpreter = decode(await read(offset, length));
					}
				}
				const neededOffsets: number[] = [];
				let sonameOffset: number | null = null,
					rpathOffset: number | null = null,
					runpathOffset: number | null = null,
					stringAddress: bigint | null = null,
					stringSize = 0;
				if (dynamic) {
					const bytes = await read(dynamic.offset, dynamic.size),
						step = bits === 64 ? 16 : 8;
					let terminated = false;
					for (let offset = 0; offset + step <= bytes.length; offset += step) {
						const tag = bits === 64 ? u64(bytes, offset) : BigInt(u32(bytes, offset)),
							raw = bits === 64 ? u64(bytes, offset + 8) : BigInt(u32(bytes, offset + 4));
						if (tag === 0n) {
							terminated = true;
							break;
						}
						if (tag === 1n) neededOffsets.push(safe(raw));
						else if (tag === 5n) stringAddress = raw;
						else if (tag === 10n) stringSize = safe(raw);
						else if (tag === 14n) sonameOffset = safe(raw);
						else if (tag === 15n) rpathOffset = safe(raw);
						else if (tag === 29n) runpathOffset = safe(raw);
					}
					if (!terminated) throw new Error("Unterminated ELF dynamic segment: " + file);
				}
				const string = async (offset: number): Promise<string> => {
					if (stringAddress === null || offset >= stringSize)
						throw new Error("Missing ELF dynamic string table: " + file);
					const segment = loads.find(
						(load) => stringAddress! >= load.address && stringAddress! < load.address + BigInt(load.size),
					);
					if (!segment) throw new Error("ELF dynamic string table is not file-backed: " + file);
					const begin = segment.offset + safe(stringAddress - segment.address) + offset,
						remaining = stringSize - offset,
						chunks: Buffer[] = [];
					let consumed = 0;
					while (consumed < remaining) {
						const bytes = await read(begin + consumed, Math.min(1024, remaining - consumed));
						const end = bytes.indexOf(0);
						chunks.push(end < 0 ? bytes : bytes.subarray(0, end));
						if (end >= 0)
							return new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(
								chunks.length === 1 ? chunks[0] : Buffer.concat(chunks),
							);
						consumed += bytes.length;
					}
					throw new Error("Unterminated ELF dynamic string: " + file);
				};
				const needed: string[] = [];
				for (const offset of neededOffsets) needed.push(await string(offset));
				value = {
					machine,
					bits: bits as 32 | 64,
					interpreter,
					soname: sonameOffset === null ? null : await string(sonameOffset),
					needed,
					rpath: rpathOffset === null ? [] : (await string(rpathOffset)).split(":"),
					runpath: runpathOffset === null ? [] : (await string(runpathOffset)).split(":"),
				};
			}
		} finally {
			await handle.close();
		}
		const after = await fs.stat(file, { bigint: true });
		if ([after.dev, after.ino, after.size, after.mode, after.mtimeNs, after.ctimeNs].join(":") !== stamp)
			throw new Error("ELF changed during discovery: " + file);
		this.cache.set(key, { stamp, value });
		return value;
	}
}

export class ToolHasher {
	private readonly bytes = new Map<string, { stamp: string; hash: Hash; size: number; executable: boolean }>();
	private readonly readBuffers: Buffer[] = [];
	async file(file: string): Promise<{ hash: Hash; size: number; executable: boolean }> {
		const before = await fs.stat(file, { bigint: true });
		if (!before.isFile()) throw new Error(`Tool input is not a regular file: ${file}`);
		const stamp = [before.dev, before.ino, before.size, before.mode, before.mtimeNs, before.ctimeNs].join(":");
		const key = `${before.dev}:${before.ino}`;
		const cached = this.bytes.get(key);
		if (cached?.stamp === stamp) return { hash: cached.hash, size: cached.size, executable: cached.executable };
		if (before.size > BigInt(Number.MAX_SAFE_INTEGER)) throw new Error(`Oversize tool file: ${file}`);
		const digest = createHash("sha256");
		const handle = await fs.open(file, "r");
		let buffer: Buffer | undefined;
		try {
			const opened = await handle.stat({ bigint: true });
			if (opened.dev !== before.dev || opened.ino !== before.ino)
				throw new Error(`Tool changed while opening: ${file}`);
			buffer = this.readBuffers.pop() ?? Buffer.allocUnsafe(64 * 1024);
			const expectedSize = Number(before.size);
			let offset = 0;
			while (offset < expectedSize) {
				const length = Math.min(buffer.length, expectedSize - offset);
				const { bytesRead } = await handle.read(buffer, 0, length, offset);
				if (bytesRead === 0) throw new Error(`Tool truncated while hashing: ${file}`);
				digest.update(bytesRead === buffer.length ? buffer : buffer.subarray(0, bytesRead));
				offset += bytesRead;
			}
			if (offset !== expectedSize || (await handle.read(buffer, 0, 1, offset)).bytesRead !== 0)
				throw new Error(`Tool size changed while hashing: ${file}`);
		} finally {
			try {
				await handle.close();
			} finally {
				if (buffer) this.readBuffers.push(buffer);
			}
		}
		const after = await fs.stat(file, { bigint: true });
		const afterStamp = [after.dev, after.ino, after.size, after.mode, after.mtimeNs, after.ctimeNs].join(":");
		if (afterStamp !== stamp) throw new Error(`Tool changed while hashing: ${file}`);
		const value = {
			stamp,
			hash: `sha256:${digest.digest("hex")}` as Hash,
			size: Number(before.size),
			executable: (before.mode & 0o111n) !== 0n,
		};
		this.bytes.set(key, value);
		return { hash: value.hash, size: value.size, executable: value.executable };
	}
	async roots(roots: readonly ToolRoot[]): Promise<ToolFile[]> {
		const views: {
			label: string;
			real: string;
			directory: boolean;
			exclude: readonly string[];
			linkBoundary?: string;
		}[] = [];
		const labels = new Map<string, string>();
		for (const root of roots) {
			toolPath(root.label);
			const real = await canonicalToolPath(root.path);
			const stat = await fs.stat(real);
			if (!stat.isDirectory() && !stat.isFile()) throw new Error(`Unsupported tool root: ${root.path}`);
			if (labels.has(root.label)) {
				if (labels.get(root.label) !== real) throw new Error(`Conflicting tool root: ${root.label}`);
				continue;
			}
			labels.set(root.label, real);
			views.push({
				label: root.label,
				real,
				directory: stat.isDirectory(),
				exclude: root.exclude ?? [],
				linkBoundary: root.linkBoundary === undefined ? undefined : await canonicalToolPath(root.linkBoundary),
			});
		}
		views.sort((a, b) => utf8Compare(a.label, b.label));
		const entries = new Map<string, ToolFile>();
		const pending: { virtual: string; real: string; target: string; directory: boolean }[] = [];
		const insert = (entry: ToolFile) => {
			const prior = entries.get(entry.path);
			if (prior && D("tool-entry", prior) !== D("tool-entry", entry))
				throw new Error(`Conflicting tool entry: ${entry.path}`);
			entries.set(entry.path, entry);
		};
		const parents = (name: string) => {
			let parent = path.posix.dirname(name);
			while (parent !== ".") {
				insert({ path: parent, kind: "directory" });
				parent = path.posix.dirname(parent);
			}
		};
		for (const view of views) {
			parents(view.label);
			const active = new Set<string>();
			const walk = async (actual: string, virtual: string, relative: string): Promise<void> => {
				if (view.exclude.some((ex) => relative === ex || relative.startsWith(ex.replace(/\/$/u, "") + "/"))) return;
				const stat = await fs.lstat(actual, { bigint: true });
				if (stat.isSymbolicLink()) {
					const target = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(
						await fs.readlink(actual, { encoding: "buffer" }),
					);
					if (target.includes("\0")) throw new Error(`Invalid tool symlink target: ${actual}`);
					const real = await canonicalToolPath(actual);
					if (view.linkBoundary && !inside(view.linkBoundary, real))
						throw new Error(`Tool symlink escapes root boundary: ${virtual}`);
					const resolved = await fs.stat(real);
					if (!resolved.isFile() && !resolved.isDirectory())
						throw new Error(`Invalid tool symlink target kind: ${actual}`);
					pending.push({ virtual, real, target, directory: resolved.isDirectory() });
					return;
				}
				if (stat.isFile()) {
					insert({ path: virtual, kind: "file", ...(await this.file(actual)) });
					return;
				}
				if (!stat.isDirectory()) throw new Error(`Unsupported tool entry: ${actual}`);
				const key = `${stat.dev}:${stat.ino}`;
				if (active.has(key)) throw new Error(`Tool directory containment cycle: ${actual}`);
				active.add(key);
				insert({ path: virtual, kind: "directory" });
				const names = (await fs.readdir(actual, { encoding: "buffer" })).map((name) =>
					new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(name),
				);
				names.sort(utf8Compare);
				for (const name of names) {
					toolPath(name);
					await walk(
						path.join(actual, name),
						virtual === "." ? name : `${virtual}/${name}`,
						relative ? `${relative}/${name}` : name,
					);
				}
				const after = await fs.lstat(actual, { bigint: true });
				if (
					after.dev !== stat.dev ||
					after.ino !== stat.ino ||
					after.mtimeNs !== stat.mtimeNs ||
					after.ctimeNs !== stat.ctimeNs
				)
					throw new Error(`Tool directory changed during traversal: ${actual}`);
				active.delete(key);
			};
			await walk(view.real, view.label, "");
		}
		for (const link of pending) {
			const candidates = views.filter((view) =>
				view.directory ? inside(view.real, link.real) : view.real === link.real,
			);
			candidates.sort(
				(a, b) => b.real.split(path.sep).length - a.real.split(path.sep).length || utf8Compare(a.label, b.label),
			);
			const selected = candidates[0];
			if (!selected) throw new Error(`Tool symlink escapes declared roots: ${link.virtual}`);
			const relative = path.relative(selected.real, link.real).split(path.sep).join("/");
			const resolvedPath = relative
				? selected.label === "."
					? relative
					: `${selected.label}/${relative}`
				: selected.label;
			const targetEntry = entries.get(resolvedPath);
			if (link.directory) {
				if (targetEntry?.kind !== "directory") throw new Error(`Missing canonical tool directory: ${resolvedPath}`);
				insert({
					path: link.virtual,
					kind: "symlink-directory",
					target: link.target,
					resolved_path: resolvedPath,
					resolved_hash: H(new Uint8Array()),
				});
			} else {
				if (targetEntry?.kind !== "file") throw new Error(`Missing canonical tool file: ${resolvedPath}`);
				insert({
					path: link.virtual,
					kind: "symlink-file",
					target: link.target,
					resolved_path: resolvedPath,
					resolved_hash: targetEntry.hash,
					resolved_size: targetEntry.size,
					executable: targetEntry.executable,
				});
			}
		}
		return reconstructDirectoryHashes([...entries.values()]);
	}
}

export function reconstructDirectoryHashes(files: readonly ToolFile[]): ToolFile[] {
	const entries = new Map(files.map((entry) => [entry.path, { ...entry }] as [string, ToolFile]));
	if (entries.size !== files.length) throw new Error("Duplicate tool manifest path");
	const active = new Set<string>(),
		hashes = new Map<string, Hash>();
	const directoryHash = (directory: string): Hash => {
		const cached = hashes.get(directory);
		if (cached) return cached;
		if (entries.get(directory)?.kind !== "directory") throw new Error(`Missing tool directory: ${directory}`);
		if (active.has(directory)) throw new Error(`Tool symlink hash cycle: ${directory}`);
		active.add(directory);
		const prefix = directory === "." ? "" : directory + "/";
		const descendants: ToolFile[] = [];
		for (const [name, entry] of entries) {
			if (name === directory || !name.startsWith(prefix)) continue;
			if (entry.kind === "symlink-directory") entry.resolved_hash = directoryHash(entry.resolved_path);
			if (entry.kind === "symlink-file") {
				const target = entries.get(entry.resolved_path);
				if (
					target?.kind !== "file" ||
					target.hash !== entry.resolved_hash ||
					target.size !== entry.resolved_size ||
					target.executable !== entry.executable
				)
					throw new Error(`Contradictory tool file alias: ${name}`);
			}
			descendants.push({ ...entry, path: name.slice(prefix.length) });
		}
		descendants.sort((a, b) => utf8Compare(a.path, b.path));
		active.delete(directory);
		const hash = D("tool-directory", { entries: descendants });
		hashes.set(directory, hash);
		return hash;
	};
	for (const entry of entries.values())
		if (entry.kind === "symlink-directory") entry.resolved_hash = directoryHash(entry.resolved_path);
	return [...entries.values()].sort((a, b) => utf8Compare(a.path, b.path));
}
export async function hashToolRoots(roots: readonly ToolRoot[], hasher = new ToolHasher()): Promise<ToolFile[]> {
	return hasher.roots(roots);
}

export async function readPackage(directory: string): Promise<Record<string, any>> {
	return parseJSON(await fs.readFile(path.join(directory, "package.json"))) as Record<string, any>;
}
export async function resolvePackage(name: string, from: string): Promise<string | null> {
	if (!/^(?:@[A-Za-z0-9._-]+\/)?[A-Za-z0-9._-]+$/u.test(name)) throw new Error(`Invalid package name: ${name}`);
	let cursor = from;
	for (;;) {
		const candidate = path.join(cursor, "node_modules", name);
		try {
			const real = await canonicalToolPath(candidate);
			if ((await fs.stat(path.join(real, "package.json"))).isFile()) return real;
		} catch (error) {
			if ((error as NodeJS.ErrnoException).code !== "ENOENT" && (error as NodeJS.ErrnoException).code !== "ENOTDIR")
				throw error;
		}
		const parent = path.dirname(cursor);
		if (parent === cursor) return null;
		cursor = parent;
	}
}
export async function packageRoots(context: AdapterContext, entryRoots: readonly string[]): Promise<ToolRoot[]> {
	const roots: ToolRoot[] = [],
		visited = new Set<string>(),
		labels = new Map<string, string>();
	const visit = async (directory: string): Promise<void> => {
		const real = await canonicalToolPath(directory);
		if (visited.has(real)) return;
		visited.add(real);
		const manifest = await readPackage(real);
		if (
			typeof manifest.name !== "string" ||
			typeof manifest.version !== "string" ||
			!manifest.name ||
			!manifest.version
		)
			throw new Error(`Missing installed package identity: ${real}`);
		const label = `packages/${manifest.name}/${manifest.version}`;
		toolPath(label);
		if (labels.has(label) && labels.get(label) !== real) throw new Error(`Ambiguous installed package: ${label}`);
		labels.set(label, real);
		roots.push({ label, path: real, exclude: ["node_modules"] });
		const required = new Set([
			...Object.keys(manifest.dependencies ?? {}),
			...Object.keys(manifest.peerDependencies ?? {}).filter(
				(name) => manifest.peerDependenciesMeta?.[name]?.optional !== true,
			),
		]);
		const optional = new Set(Object.keys(manifest.optionalDependencies ?? {}));
		for (const name of [...new Set([...required, ...optional, ...Object.keys(manifest.peerDependencies ?? {})])].sort(
			utf8Compare,
		)) {
			const selected = await resolvePackage(name, real);
			if (!selected) {
				if (required.has(name) && !optional.has(name))
					throw new Error(`Missing installed dependency ${name} of ${manifest.name}`);
				continue;
			}
			await visit(selected);
		}
	};
	for (const root of entryRoots) await visit(root);
	return roots.sort((a, b) => utf8Compare(a.label, b.label));
}
