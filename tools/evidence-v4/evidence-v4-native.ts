import * as fs from "node:fs/promises";
import * as syncFs from "node:fs";
import * as path from "node:path";
import { EventEmitter } from "node:events";
import { constants as osConstants } from "node:os";
import type { FileHandle } from "node:fs/promises";
import { randomUUID } from "node:crypto";
import { Readable } from "node:stream";
import type { Writable } from "node:stream";
import { Socket } from "node:net";
import type { SocketConnectOpts } from "node:net";
import { C, D, H, parseJSON, utf8Compare, validateOwnerRecord, validatePendingResult } from "./evidence-v4-model.ts";
import { canonicalToolPath } from "./evidence-v4-toolchain-common.ts";
import type {
	OwnedProcess,
	SpawnWindow,
	PendingResult,
	OwnerRecord,
	OwnedRegistration,
	OwnershipReceipt,
} from "./evidence-v4-model.ts";

const BASE = ".fv/evidence/v4";
const OWNER = `${BASE}/locks/publication.lock`;
const CONTROL = "DOSSIER_QUINT_OWNERSHIP_FDS";
const TRANSPORT_CONTROL = "BUN_BE_BUN";
const MAX_GRACE = 5000;
const FORCED_WAITER = Object.hasOwn(process.env, "BUN_FEATURE_FLAG_FORCE_WAITER_THREAD");
const WAITER_VARIABLE = Buffer.from("BUN_FEATURE_FLAG_FORCE_WAITER_THREAD\0");
const GATE = String.raw`
const fs = require("node:fs"), ffi = require("bun:ffi");
const libc = process.platform === "darwin" ? "/usr/lib/libSystem.B.dylib" : fs.readFileSync("/proc/self/maps", "utf8").split("\n").map(line => line.trim().split(/\s+/).at(-1) || "").find(file => /\/(?:libc\.so(?:\.[0-9]+)*|libc-[^/]+\.so|ld-musl-[^/]+\.so\.[0-9]+)$/.test(file));
if (!libc || !["arm64", "x64"].includes(process.arch)) throw new Error("native exec ABI unavailable");
const library = ffi.dlopen(libc, {
  execve: { args: [ffi.FFIType.ptr, ffi.FFIType.ptr, ffi.FFIType.ptr], returns: ffi.FFIType.i32 },
  ioctl: { args: [ffi.FFIType.i32, ffi.FFIType.u64], returns: ffi.FFIType.i32 },
});
const FIOCLEX = process.platform === "darwin" ? 0x20006601 : 0x5451;
const FIONCLEX = process.platform === "darwin" ? 0x20006602 : 0x5450;
if (library.symbols.ioctl(7, FIOCLEX) !== 0) throw new Error("exec failure channel close-on-exec failed");
fs.writeSync(6, Buffer.from("1"));
try {
  const byte = Buffer.alloc(1);
  if (fs.readSync(5, byte, 0, 1, null) !== 1 || byte[0] !== 49) process.exit(125);
  const readExact = buffer => {
    let offset = 0;
    while (offset < buffer.length) {
      const count = fs.readSync(5, buffer, offset, buffer.length - offset, null);
      if (count <= 0) throw new Error("incomplete native launch frame");
      offset += count;
    }
  };
  const header = Buffer.alloc(8); readExact(header);
  const length = header.readBigUInt64BE(0);
  if (length === 0n || length > BigInt(Number.MAX_SAFE_INTEGER)) throw new Error("invalid native launch frame length");
  const bytes = Buffer.allocUnsafe(Number(length)); readExact(bytes);
  const payload = JSON.parse(bytes.toString("utf8")); fs.closeSync(5); fs.closeSync(6);
  if (typeof payload.file !== "string" || !payload.file || payload.file.includes("\0") || !Array.isArray(payload.argv) || !payload.argv.length || payload.argv.some(value => typeof value !== "string" || !value || value.includes("\0"))) throw new Error("invalid native exec argv");
  if (!payload.environment || typeof payload.environment !== "object" || Array.isArray(payload.environment)) throw new Error("invalid native exec environment");
  const environment = Object.entries(payload.environment);
  if (environment.some(([name, value]) => !/^[A-Za-z_][A-Za-z0-9_]*$/.test(name) || typeof value !== "string" || value.includes("\0"))) throw new Error("invalid native exec environment");
  if (typeof payload.cwd !== "string" || payload.cwd.includes("\0")) throw new Error("invalid native exec cwd");
  process.chdir(payload.cwd);
  const file = Buffer.from(payload.file + "\0"), args = payload.argv.map(value => Buffer.from(value + "\0")), env = environment.map(([name, value]) => Buffer.from(name + "=" + value + "\0"));
  const argv = new BigUint64Array(args.length + 1), envp = new BigUint64Array(env.length + 1);
  args.forEach((value, index) => argv[index] = BigInt(ffi.ptr(value)));
  env.forEach((value, index) => envp[index] = BigInt(ffi.ptr(value)));
  globalThis.__fvNativeExecRetained = { library, file, args, env, argv, envp };
  const allowed = new Set(process.argv[1] === "dossier-quint-private-pipes/v1" ? [0, 1, 2, 3, 4] : [0, 1, 2]);
  const directory = process.platform === "darwin" ? "/dev/fd" : "/proc/self/fd";
  for (const name of fs.readdirSync(directory)) {
    if (!/^[0-9]+$/.test(name)) continue;
    const fd = Number(name);
    if (allowed.has(fd)) continue;
    if (library.symbols.ioctl(fd, FIOCLEX) !== 0) {
      try { fs.fstatSync(fd); } catch (failure) { if (failure && failure.code === "EBADF") continue; throw failure; }
      throw new Error("native descriptor close-on-exec failed");
    }
  }
  for (const fd of allowed) if (library.symbols.ioctl(fd, FIONCLEX) !== 0) throw new Error("native intended descriptor inheritance failed: " + fd);
  const result = library.symbols.execve(ffi.ptr(file), ffi.ptr(argv), ffi.ptr(envp));
  throw new Error("native libc execve returned " + result);
} catch (failure) {
  const bytes = Buffer.from(failure instanceof Error ? failure.message : String(failure));
  fs.writeSync(7, bytes); fs.writeSync(2, bytes); fs.closeSync(7); process.exit(125);
}
`;
const COLLECTOR_GATE =
	"\nimport os, sys\nfd = int(sys.argv[1])\nready = os.read(fd, 1)\nos.close(fd)\nif ready != b'1':\n    sys.exit(125)\nos.execvpe(sys.argv[2], sys.argv[2:], os.environ)\n";

export interface NativeSessionOptions {
	cwd: string;
	runId: string;
	signal?: AbortSignal;
}
export interface NativeRunOptions {
	command: readonly string[];
	cwd?: string;
	environment: Record<string, string>;
	timeoutSeconds: number | null;
	signal?: AbortSignal;
	executionKey?: string;
	attemptId?: string;
	ownershipProtocol?: null | "dossier-quint-private-pipes/v1";
}
export interface NativeResult {
	stdout: Buffer;
	stderr: Buffer;
	startedAt: string;
	finishedAt: string;
	termination: { exit_code: number | null; signal: string | null; timed_out: boolean; cancelled: boolean };
	ownership: OwnershipReceipt;
	error: string | null;
	transportArgv: string[];
}
export interface NativeLock {
	release(): Promise<void>;
}
export type NativeAppendLock = <T>(fn: () => Promise<T>) => Promise<T>;
export interface RecoveryOptions {
	cwd: string;
	expectedOwner: OwnerRecord;
	account: (owner: OwnerRecord, withAppendLock: NativeAppendLock) => Promise<void>;
}

type LockRecord = {
	schema_version: "fv-evidence-lock/v1";
	owner_id: string;
	owner_file: string;
	host_id: string;
	boot_id: string;
	run_id: string;
};
type LockEntry = { file: string; bytes: Buffer };
type ProcessRow = { pid: number; ppid: number; pgid: number };
interface NativeSubprocess {
	pid: number;
	stdout: ReadableStream<Uint8Array>;
	stderr: ReadableStream<Uint8Array>;
	stdio: readonly unknown[];
	exited: Promise<number>;
	exitCode: number | null;
	signalCode: string | number | null;
	unref(): void;
}
interface NativeRuntime {
	spawn(options: {
		cmd: readonly string[];
		cwd: string;
		env: Record<string, string>;
		detached: boolean;
		stdio: readonly string[];
	}): NativeSubprocess;
}
interface ControlEndpoint {
	socket: Socket;
	connected: Promise<void>;
	drained: Promise<void>;
	end(bytes?: Uint8Array): Promise<void>;
	connect(): void;
}
const message = (error: unknown) => (error instanceof Error ? error.message : String(error));
const clone = <T>(value: T): T => JSON.parse(JSON.stringify(value));
const now = () => new Date().toISOString();
const finishTime = () => new Date(Date.now() + 1).toISOString();
function abort(signal?: AbortSignal): void {
	if (signal?.aborted)
		throw signal.reason instanceof Error ? signal.reason : new DOMException("native operation cancelled", "AbortError");
}
function sleep(ms: number, signal?: AbortSignal): Promise<void> {
	abort(signal);
	const { promise, resolve, reject } = Promise.withResolvers<void>();
	const stop = () => {
		clearTimeout(timer);
		reject(
			signal?.reason instanceof Error ? signal.reason : new DOMException("native operation cancelled", "AbortError"),
		);
	};
	const timer = setTimeout(() => {
		signal?.removeEventListener("abort", stop);
		resolve();
	}, ms);
	signal?.addEventListener("abort", stop, { once: true });
	return promise;
}
async function waitWithin(work: Promise<void>, milliseconds: number): Promise<boolean> {
	const timeout = Promise.withResolvers<boolean>();
	const timer = setTimeout(() => timeout.resolve(false), milliseconds);
	try {
		return await Promise.race([work.then(() => true), timeout.promise]);
	} finally {
		clearTimeout(timer);
	}
}
async function syncDirectory(directory: string): Promise<void> {
	const handle = await fs.open(directory, "r");
	try {
		await handle.sync();
	} finally {
		await handle.close();
	}
}
async function safeDirectory(directory: string): Promise<void> {
	const absolute = path.resolve(directory);
	let current = path.parse(absolute).root;
	for (const part of absolute.slice(current.length).split(path.sep).filter(Boolean)) {
		const parent = current;
		current = path.join(current, part);
		try {
			await fs.mkdir(current, { mode: 0o700 });
			await syncDirectory(current);
			await syncDirectory(parent);
		} catch (error) {
			if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error;
		}
		const st = await fs.lstat(current);
		if (!st.isDirectory() || st.isSymbolicLink()) throw new Error(`unsafe lock directory: ${current}`);
	}
}
async function checkedBytes(file: string): Promise<Buffer> {
	if ((await fs.realpath(path.dirname(file))) !== path.resolve(path.dirname(file)))
		throw new Error("symlinked ownership file parent");
	const st = await fs.lstat(file);
	if (!st.isFile() || st.isSymbolicLink() || st.nlink !== 1) throw new Error(`unsafe ownership file: ${file}`);
	const handle = await fs.open(file, syncFs.constants.O_RDONLY | syncFs.constants.O_NOFOLLOW);
	try {
		const opened = await handle.stat();
		if (opened.dev !== st.dev || opened.ino !== st.ino || opened.nlink !== 1)
			throw new Error("ownership file changed while opening");
		return await handle.readFile();
	} finally {
		await handle.close();
	}
}
async function exclusiveFile(file: string, bytes: Uint8Array): Promise<void> {
	await safeDirectory(path.dirname(file));
	const handle = await fs.open(file, "wx", 0o600);
	try {
		await handle.writeFile(bytes);
		await handle.sync();
	} finally {
		await handle.close();
	}
	await syncDirectory(path.dirname(file));
}
async function replaceFile(file: string, bytes: Uint8Array, expected: Uint8Array): Promise<void> {
	if (!Buffer.from(await checkedBytes(file)).equals(Buffer.from(expected)))
		throw new Error("ownership changed before replacement");
	const temporary = `${file}.${randomUUID()}.tmp`;
	await exclusiveFile(temporary, bytes);
	if (!Buffer.from(await checkedBytes(file)).equals(Buffer.from(expected)))
		throw new Error("ownership changed during replacement");
	await fs.rename(temporary, file);
	await syncDirectory(path.dirname(file));
}
async function removeMatching(entry: LockEntry): Promise<void> {
	if (!(await checkedBytes(entry.file)).equals(entry.bytes)) throw new Error("refusing to retire changed lock");
	await fs.unlink(entry.file);
	await syncDirectory(path.dirname(entry.file));
}

type NativeAddress = number;
type NativeAddressOf = (view: ArrayBufferView) => NativeAddress;
interface NativeMemoryReader {
	i32(address: NativeAddress, offset: number): number;
}
interface NativeSocketABI {
	shutdown(fd: number, how: 0 | 1 | 2): number;
	dup(fd: number): number;
	ioctl(fd: number, request: number | bigint): number;
}
interface NativeControlABI extends NativeSocketABI {
	currentErrno(): number;
}
interface DarwinSystemABI extends NativeSocketABI {
	__error(): NativeAddress;
	getsid(pid: number): number;
	getenv(name: NativeAddress): NativeAddress | null;
	sigaction(signal: number, action: NativeAddress | null, previous: NativeAddress | null): number;
	gethostuuid(output: NativeAddress, timeout: NativeAddress): number;
	sysctlbyname(
		name: NativeAddress,
		output: NativeAddress | null,
		outputSize: NativeAddress | null,
		input: NativeAddress | null,
		inputSize: number,
	): number;
	sysctl(
		name: NativeAddress,
		count: number,
		output: NativeAddress | null,
		outputSize: NativeAddress | null,
		input: NativeAddress | null,
		inputSize: number,
	): number;
}
interface DarwinProcessABI {
	proc_pidinfo(pid: number, flavor: number, argument: number | bigint, output: NativeAddress, size: number): number;
	proc_pidpath(pid: number, output: NativeAddress, size: number): number;
	proc_listpids(kind: number, selector: number, output: NativeAddress | null, size: number): number;
}
interface DarwinNativeABI extends DarwinSystemABI, DarwinProcessABI, NativeControlABI {
	ptr: NativeAddressOf;
	forcedWaiter: boolean;
}
interface LinuxControlABI extends NativeSocketABI {
	__errno_location(): NativeAddress;
}
let darwinLibrary: Promise<DarwinNativeABI> | undefined;
let darwinSymbols: DarwinNativeABI | undefined;
async function darwin(): Promise<DarwinNativeABI> {
	if (!darwinLibrary)
		darwinLibrary = (async () => {
			// Darwin birth identity requires a platform-only FFI module.
			const moduleName = "bun:ffi";
			const { dlopen, ptr, FFIType, read } = await import(moduleName);
			// Bun FFI exposes process-local view addresses and signed 32-bit memory reads.
			const addressOf = ptr as NativeAddressOf;
			const memory = read as NativeMemoryReader;
			const library = dlopen("/usr/lib/libSystem.B.dylib", {
				getsid: { args: [FFIType.i32], returns: FFIType.i32 },
				getenv: { args: [FFIType.ptr], returns: FFIType.ptr },
				sigaction: { args: [FFIType.i32, FFIType.ptr, FFIType.ptr], returns: FFIType.i32 },
				shutdown: { args: [FFIType.i32, FFIType.i32], returns: FFIType.i32 },
				__error: { args: [], returns: FFIType.ptr },
				dup: { args: [FFIType.i32], returns: FFIType.i32 },
				ioctl: { args: [FFIType.i32, FFIType.u64], returns: FFIType.i32 },
				gethostuuid: { args: [FFIType.ptr, FFIType.ptr], returns: FFIType.i32 },
				sysctlbyname: { args: [FFIType.ptr, FFIType.ptr, FFIType.ptr, FFIType.ptr, FFIType.u64], returns: FFIType.i32 },
				sysctl: {
					args: [FFIType.ptr, FFIType.u32, FFIType.ptr, FFIType.ptr, FFIType.ptr, FFIType.u64],
					returns: FFIType.i32,
				},
			});
			// These fixed dlopen descriptors match the Darwin libSystem C ABI.
			const system = library.symbols as DarwinSystemABI;
			const processes = dlopen("/usr/lib/libproc.dylib", {
				proc_pidinfo: { args: [FFIType.i32, FFIType.i32, FFIType.u64, FFIType.ptr, FFIType.i32], returns: FFIType.i32 },
				proc_pidpath: { args: [FFIType.i32, FFIType.ptr, FFIType.u32], returns: FFIType.i32 },
				proc_listpids: { args: [FFIType.u32, FFIType.u32, FFIType.ptr, FFIType.i32], returns: FFIType.i32 },
			});
			// These fixed dlopen descriptors match the SDK libproc function ABI.
			const processInfo = processes.symbols as DarwinProcessABI;
			darwinSymbols = {
				...system,
				...processInfo,
				ptr: addressOf,
				// Bun's JS env mutations do not change the libc environment consulted at startup.
				forcedWaiter: system.getenv(addressOf(WAITER_VARIABLE)) !== null,
				currentErrno: () => memory.i32(system.__error(), 0),
			};
			return darwinSymbols;
		})();
	return darwinLibrary;
}
let linuxControlLibrary: Promise<NativeControlABI> | undefined;
async function controlLibrary(): Promise<NativeControlABI> {
	if (process.platform === "darwin") return darwin();
	if (!linuxControlLibrary)
		linuxControlLibrary = (async () => {
			// Native socket shutdown is platform-specific; launch stays with Bun.
			const moduleName = "bun:ffi",
				{ dlopen, FFIType, read } = await import(moduleName);
			// Bun FFI reads the C runtime thread-local errno as a signed 32-bit integer.
			const memory = read as NativeMemoryReader;
			const maps = await fs.readFile("/proc/self/maps", "utf8");
			const libraries = maps.split("\n").map((line) => line.trim().split(/\s+/).at(-1) ?? "");
			const libc = libraries.find((file) =>
				/\/(?:libc\.so(?:\.[0-9]+)*|libc-[^/]+\.so|ld-musl-[^/]+\.so\.[0-9]+)$/.test(file),
			);
			if (!libc) throw new Error("selected Linux socket shutdown ABI unavailable");
			const library = dlopen(libc, {
				shutdown: { args: [FFIType.i32, FFIType.i32], returns: FFIType.i32 },
				__errno_location: { args: [], returns: FFIType.ptr },
				dup: { args: [FFIType.i32], returns: FFIType.i32 },
				ioctl: { args: [FFIType.i32, FFIType.u64], returns: FFIType.i32 },
			});
			// These fixed dlopen descriptors match the selected Linux libc socket ABI.
			const system = library.symbols as LinuxControlABI;
			return { ...system, currentErrno: () => memory.i32(system.__errno_location(), 0) };
		})();
	return linuxControlLibrary;
}
class NativeChild extends EventEmitter {
	readonly pid: number;
	readonly stdout: Readable;
	readonly stderr: Readable;
	readonly stdio: (Readable | Writable | null)[];
	constructor(readonly native: NativeSubprocess) {
		super();
		this.pid = native.pid;
		this.stdout = Readable.fromWeb(native.stdout);
		this.stderr = Readable.fromWeb(native.stderr);
		this.stdio = [null, this.stdout, this.stderr];
		let terminal = false,
			closed = false,
			drains = 0;
		let code: number | null = null,
			signal: string | null = null;
		const publishClose = () => {
			if (!closed && terminal && drains === 2) {
				closed = true;
				this.emit("close", code, signal);
			}
		};
		for (const stream of [this.stdout, this.stderr]) {
			let drained = false;
			const finish = () => {
				if (!drained) {
					drained = true;
					drains++;
					publishClose();
				}
			};
			stream.once("end", finish);
			stream.once("close", finish);
			stream.once("error", (failure) => {
				this.emit("error", failure);
				finish();
			});
		}
		void native.exited.then(
			(actual) => {
				terminal = true;
				const actualSignal = native.signalCode;
				if (typeof actualSignal === "string") signal = actualSignal;
				else if (typeof actualSignal === "number" && actualSignal > 0)
					signal =
						Object.entries(osConstants.signals).find(([, value]) => value === actualSignal)?.[0] ??
						"SIG" + actualSignal;
				if (signal === null) code = actual;
				this.emit("exit", code, signal);
				publishClose();
			},
			(failure) => {
				terminal = true;
				this.emit("error", failure);
				publishClose();
			},
		);
	}
}
async function machineIdentity(): Promise<{ host_id: string; boot_id: string }> {
	if (process.platform === "linux") {
		let host: Buffer;
		try {
			host = await fs.readFile("/etc/machine-id");
		} catch {
			host = await fs.readFile("/var/lib/dbus/machine-id");
		}
		const boot = await fs.readFile("/proc/sys/kernel/random/boot_id");
		if (!host.toString().trim() || !boot.toString().trim()) throw new Error("missing real host/boot identity");
		return { host_id: H(host), boot_id: H(boot) };
	}
	if (process.platform !== "darwin") throw new Error("v4 requires Darwin or Linux POSIX ownership");
	const lib = await darwin();
	const host = Buffer.alloc(16),
		timeout = Buffer.alloc(16);
	timeout.writeBigInt64LE(5n, 0);
	if (lib.gethostuuid(lib.ptr(host), lib.ptr(timeout)) !== 0) throw new Error("gethostuuid failed");
	const boot = Buffer.alloc(128),
		length = Buffer.alloc(8);
	length.writeBigUInt64LE(BigInt(boot.length));
	const name = Buffer.from("kern.bootsessionuuid\0");
	if (lib.sysctlbyname(lib.ptr(name), lib.ptr(boot), lib.ptr(length), null, 0) !== 0)
		throw new Error("boot session identity unavailable");
	return { host_id: H(host), boot_id: H(boot.subarray(0, Number(length.readBigUInt64LE()))) };
}

export async function readProcessIdentity(pid: number): Promise<OwnedProcess | null> {
	if (!Number.isSafeInteger(pid) || pid <= 0) throw new Error("invalid process PID");
	if (process.platform === "linux") {
		let stat: string;
		try {
			stat = await fs.readFile(`/proc/${pid}/stat`, "utf8");
		} catch (error) {
			if ((error as NodeJS.ErrnoException).code === "ENOENT") return null;
			throw error;
		}
		const close = stat.lastIndexOf(")");
		const fields = stat
			.slice(close + 2)
			.trim()
			.split(/\s+/);
		if (close < 0 || fields.length < 20 || !/^\d+$/.test(fields[19]))
			throw new Error("unreadable Linux process birth identity");
		return {
			pid,
			parent_pid: Number(fields[1]),
			process_group: Number(fields[2]),
			session_id: Number(fields[3]),
			process_start_id: `linux-proc-startticks:${fields[19]}`,
		};
	}
	if (process.platform !== "darwin") throw new Error("unsupported native process identity");
	return readDarwinProcessIdentity(pid, await darwin());
}
function readDarwinProcessIdentity(pid: number, lib: DarwinNativeABI): OwnedProcess | null {
	const info = Buffer.alloc(136);
	const count = lib.proc_pidinfo(pid, 3, 0, lib.ptr(info), info.length);
	if (count <= 0) {
		const errno = lib.currentErrno();
		if (errno === osConstants.errno.ESRCH) return null;
		if (errno === osConstants.errno.EPERM)
			return restrictedDarwinProcess(pid, lib, Buffer.alloc(648), Buffer.alloc(8), new Int32Array([1, 14, 1, pid]));
		throw new Error(`unavailable birth identity for PID ${pid}: bytes=${count} errno=${errno}`);
	}
	if (count !== info.length || info.readUInt32LE(12) !== pid)
		throw new Error(`incomplete Darwin process birth identity for PID ${pid}: bytes=${count}`);
	const sid = lib.getsid(pid);
	if (sid <= 0) {
		const errno = lib.currentErrno();
		if (errno === osConstants.errno.ESRCH) return null;
		throw new Error(`unavailable Darwin process session identity for PID ${pid}: errno=${errno}`);
	}
	return {
		pid,
		parent_pid: info.readUInt32LE(16),
		process_group: info.readUInt32LE(100),
		session_id: sid,
		process_start_id: `darwin-proc-start:${info.readBigUInt64LE(120)}:${info.readBigUInt64LE(128)}`,
	};
}
function restrictedDarwinProcess(
	pid: number,
	lib: DarwinNativeABI,
	info: Buffer,
	length: Buffer,
	mib: Int32Array,
	owned: readonly OwnedProcess[] = [],
): OwnedProcess | null {
	if (process.arch !== "arm64" && process.arch !== "x64") throw new Error("unsupported Darwin restricted census ABI");
	let ppid = 0,
		pgid = 0,
		sid = 0,
		session = 0n,
		startSeconds = 0n,
		startMicros = 0;
	for (let attempt = 0; attempt < 2; attempt++) {
		mib[3] = pid;
		length.writeBigUInt64LE(BigInt(info.length));
		if (lib.sysctl(lib.ptr(mib), mib.length, lib.ptr(info), lib.ptr(length), null, 0) !== 0) {
			const errno = lib.currentErrno();
			if (errno === osConstants.errno.ESRCH) return null;
			throw new Error(`unavailable Darwin restricted census for PID ${pid}: errno=${errno}`);
		}
		if (length.readBigUInt64LE() === 0n) return null;
		// LP64 SDK kinfo_proc: sizeof=648, p_pid=40, e_sess=304, e_ppid=560, e_pgid=564.
		if (length.readBigUInt64LE() !== 648n || info.readInt32LE(40) !== pid)
			throw new Error(`incomplete Darwin restricted census for PID ${pid}`);
		const currentParent = info.readInt32LE(560),
			currentGroup = info.readInt32LE(564),
			currentSession = info.readBigUInt64LE(304),
			currentSeconds = info.readBigInt64LE(0),
			currentMicros = info.readInt32LE(8);
		if (
			currentParent < 0 ||
			currentGroup <= 0 ||
			currentSeconds < 0n ||
			currentMicros < 0 ||
			currentMicros >= 1_000_000
		)
			throw new Error(`invalid Darwin restricted census for PID ${pid}`);
		if (attempt === 0) {
			sid = lib.getsid(pid);
			if (sid <= 0) {
				const errno = lib.currentErrno();
				if (errno === osConstants.errno.ESRCH) return null;
				throw new Error(`unavailable Darwin restricted session for PID ${pid}: errno=${errno}`);
			}
		} else {
			// A shared session token binds getsid across both observations, including foreign PID reuse.
			const foreign =
				owned.length > 0 &&
				currentSession === session &&
				owned.every(
					(process) =>
						process.process_group !== pgid && process.process_group !== currentGroup && process.session_id !== sid,
				);
			if (
				!foreign &&
				(currentGroup !== pgid ||
					currentSession !== session ||
					currentSeconds !== startSeconds ||
					currentMicros !== startMicros)
			)
				throw new Error(`changed Darwin restricted census identity for PID ${pid}`);
		}
		ppid = currentParent;
		pgid = currentGroup;
		session = currentSession;
		startSeconds = currentSeconds;
		startMicros = currentMicros;
	}
	return {
		pid,
		parent_pid: ppid,
		process_group: pgid,
		session_id: sid,
		process_start_id: `darwin-proc-start:${startSeconds}:${startMicros}`,
	};
}
function processTable(owned: readonly OwnedProcess[] = []): ProcessRow[] {
	const rows: ProcessRow[] = [];
	if (process.platform === "linux") {
		for (const entry of syncFs.readdirSync("/proc")) {
			if (!/^\d+$/.test(entry)) continue;
			let stat: string;
			try {
				stat = syncFs.readFileSync("/proc/" + entry + "/stat", "utf8");
			} catch (failure) {
				if ((failure as NodeJS.ErrnoException).code === "ENOENT" || (failure as NodeJS.ErrnoException).code === "ESRCH")
					continue;
				throw failure;
			}
			const end = stat.lastIndexOf(")"),
				fields = stat
					.slice(end + 2)
					.trim()
					.split(/\s+/);
			if (end < 0 || fields.length < 20) throw new Error("incomplete Linux process census");
			rows.push({ pid: Number(entry), ppid: Number(fields[1]), pgid: Number(fields[2]) });
		}
		return rows;
	}
	if (process.platform !== "darwin" || !darwinSymbols) throw new Error("native process census unavailable");
	const lib = darwinSymbols,
		estimated = lib.proc_listpids(1, 0, null, 0);
	if (estimated <= 0) throw new Error("Darwin process census sizing failed");
	let size = Math.max(4096, estimated * 2),
		buffer: Buffer,
		used: number;
	for (;;) {
		if (size > 16 * 1024 * 1024) throw new Error("Darwin process census exceeds bounded storage");
		buffer = Buffer.alloc(size);
		used = lib.proc_listpids(1, 0, lib.ptr(buffer), buffer.length);
		if (used <= 0 || used % 4 !== 0) throw new Error("Darwin process census failed");
		if (used < buffer.length) break;
		size *= 2;
	}
	const info = Buffer.alloc(136),
		restricted = Buffer.alloc(648),
		length = Buffer.alloc(8),
		mib = new Int32Array([1, 14, 1, 0]);
	for (let offset = 0; offset < used; offset += 4) {
		const pid = buffer.readInt32LE(offset);
		if (pid <= 0) continue;
		const count = lib.proc_pidinfo(pid, 3, 0, lib.ptr(info), info.length);
		if (count <= 0) {
			const errno = lib.currentErrno();
			if (errno === osConstants.errno.ESRCH) continue;
			if (errno === osConstants.errno.EPERM) {
				const identity = restrictedDarwinProcess(pid, lib, restricted, length, mib, owned);
				if (!identity) continue;
				const row: ProcessRow & { sid: number } = {
					pid: identity.pid,
					ppid: identity.parent_pid,
					pgid: identity.process_group,
					sid: identity.session_id,
				};
				rows.push(row);
				continue;
			}
			throw new Error(`unavailable Darwin process census identity for PID ${pid}: bytes=${count} errno=${errno}`);
		}
		if (count !== info.length || info.readUInt32LE(12) !== pid)
			throw new Error("incomplete Darwin process census identity");
		rows.push({ pid, ppid: info.readUInt32LE(16), pgid: info.readUInt32LE(100) });
	}
	return rows;
}
function sameProcess(a: OwnedProcess, b: OwnedProcess): boolean {
	return a.pid === b.pid && a.process_start_id === b.process_start_id;
}
async function requireGroupAnchor(identity: OwnedProcess, known: readonly OwnedProcess[]): Promise<void> {
	for (const previous of known) {
		if (previous.process_group !== identity.process_group || previous.session_id !== identity.session_id) continue;
		const current = await readProcessIdentity(previous.pid);
		if (!current || !sameProcess(previous, current)) continue;
		if (current.process_group !== previous.process_group || current.session_id !== previous.session_id)
			throw new Error("owned process birth or group identity changed");
		return;
	}
	throw new Error("no original live birth identity anchors the surviving group");
}
async function groupStopped(identity: OwnedProcess): Promise<boolean> {
	const leader = await readProcessIdentity(identity.pid);
	if (leader && !sameProcess(leader, identity)) throw new Error("owned PID was reused before termination proof");
	return !processTable([identity]).some((row) => row.pgid === identity.process_group);
}
async function signalOwned(
	identity: OwnedProcess,
	signal: NodeJS.Signals,
	known: readonly OwnedProcess[],
	native?: NativeSubprocess,
): Promise<void> {
	const leader = await readProcessIdentity(identity.pid);
	if (
		leader &&
		(!sameProcess(leader, identity) ||
			leader.process_group !== identity.process_group ||
			leader.session_id !== identity.session_id)
	)
		throw new Error("refusing signal to changed process identity");
	const members = processTable(known).filter((row) => row.pgid === identity.process_group);
	if (!members.length) return;
	await requireGroupAnchor(identity, known);
	// Bun 0d9b296af src/runtime/api/bun/process.zig:312-315 reaps and updates status on the JS thread.
	if (
		process.platform !== "darwin" ||
		process.versions.bun !== "1.3.14" ||
		FORCED_WAITER ||
		Object.hasOwn(process.env, "BUN_FEATURE_FLAG_FORCE_WAITER_THREAD") ||
		!darwinSymbols ||
		!native ||
		native.pid !== identity.pid ||
		identity.pid !== identity.process_group ||
		identity.parent_pid !== process.pid
	)
		throw new Error("refusing group signal without a retained process-lifetime capability");
	if (darwinSymbols.forcedWaiter || darwinSymbols.getenv(darwinSymbols.ptr(WAITER_VARIABLE)) !== null)
		throw new Error("refusing group signal with a native forced waiter thread");
	// LP64 Darwin sigaction: handler=0, mask=8, flags=12, sizeof=16.
	const disposition = Buffer.alloc(16);
	if (darwinSymbols.sigaction(20, null, darwinSymbols.ptr(disposition)) !== 0)
		throw new Error(`refusing group signal without SIGCHLD disposition: errno=${darwinSymbols.currentErrno()}`);
	if (disposition.readBigUInt64LE(0) === 1n || (disposition.readUInt32LE(12) & 0x0020) !== 0)
		throw new Error("refusing group signal with automatic SIGCHLD reaping");
	const current = readDarwinProcessIdentity(identity.pid, darwinSymbols);
	if (
		!current ||
		!sameProcess(current, identity) ||
		current.process_group !== identity.process_group ||
		current.session_id !== identity.session_id ||
		native.exitCode !== null ||
		native.signalCode !== null
	)
		throw new Error("refusing group signal without the original unreaped direct child");
	// No await: the original leader stays live or unreaped through kill(-pgid).
	try {
		process.kill(-identity.process_group, signal);
	} catch (failure) {
		if ((failure as NodeJS.ErrnoException).code !== "ESRCH") throw failure;
	}
}
async function resolveCommand(
	command: readonly string[],
	cwd: string,
	environment: Record<string, string>,
): Promise<string> {
	if (!command.length || command.some((value) => typeof value !== "string" || !value || value.includes("\0")))
		throw new Error("invalid native argv");
	const entry = command[0];
	const candidates = entry.includes("/")
		? [path.resolve(cwd, entry)]
		: (environment.PATH ?? "").split(path.delimiter).map((part) => path.resolve(cwd, part || ".", entry));
	for (const candidate of candidates) {
		try {
			const stat = await fs.stat(candidate);
			if (!stat.isFile()) continue;
			await fs.access(candidate, syncFs.constants.X_OK);
			return candidate;
		} catch (error) {
			if (!["ENOENT", "ENOTDIR", "EACCES"].includes((error as NodeJS.ErrnoException).code ?? "")) throw error;
		}
	}
	throw new Error(`native command not found: ${entry}`);
}
function validateEnvironment(environment: Record<string, string>): void {
	if (Object.hasOwn(environment, CONTROL)) throw new Error(`reserved native control environment: ${CONTROL}`);
	for (const [name, value] of Object.entries(environment))
		if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(name) || typeof value !== "string" || value.includes("\0"))
			throw new Error("invalid native environment");
}
function globalRoot(environment: Record<string, string>): string {
	const base = environment.XDG_CACHE_HOME ?? (environment.HOME ? path.join(environment.HOME, ".cache") : null);
	if (!base || !path.isAbsolute(base))
		throw new Error("global resources require identity-bound absolute XDG_CACHE_HOME or HOME");
	return path.join(base, "fv-evidence-v4", "locks");
}

export class NativeSession {
	readonly cwd: string;
	private record: OwnerRecord;
	private ownerBytes: Buffer;
	private serial: Promise<unknown> = Promise.resolve();
	private appends: Promise<unknown> = Promise.resolve();
	private locks = new Map<string, LockEntry>();
	private running = new Set<Promise<NativeResult>>();
	private rawSubprocesses = new Map<string, NativeSubprocess>();

	private released = false;
	private storageFailed = false;
	private readonly signal?: AbortSignal;
	constructor(cwd: string, owner: OwnerRecord, bytes: Buffer, signal?: AbortSignal) {
		this.cwd = cwd;
		this.record = owner;
		this.ownerBytes = bytes;
		this.signal = signal;
	}
	get owner(): OwnerRecord {
		return clone(this.record);
	}
	private async mutate(change: () => void): Promise<void> {
		const work = this.serial.then(async () => {
			if (this.released) throw new Error("native owner already released");
			change();
			const bytes = Buffer.from(C(this.record));
			try {
				await replaceFile(path.join(this.cwd, OWNER), bytes, this.ownerBytes);
			} catch (failure) {
				this.storageFailed = true;
				throw failure;
			}
			this.ownerBytes = bytes;
		});
		this.serial = work.catch(() => {});
		await work;
	}
	async withAppendLock<T>(fn: () => Promise<T>): Promise<T> {
		const work = this.appends.then(fn);
		this.appends = work.catch(() => {});
		return work;
	}
	async beginPending(pending: PendingResult): Promise<void> {
		validatePendingResult(pending);
		await this.mutate(() => {
			if (this.record.pending_results.some((item) => Buffer.from(C(item)).equals(Buffer.from(C(pending)))))
				throw new Error("duplicate pending result");
			this.record.pending_results.push(clone(pending));
		});
	}
	async clearPending(pending: PendingResult): Promise<void> {
		await this.mutate(() => {
			const index = this.record.pending_results.findIndex((item) =>
				Buffer.from(C(item)).equals(Buffer.from(C(pending))),
			);
			if (index < 0) throw new Error("pending result ownership mismatch");
			this.record.pending_results.splice(index, 1);
		});
	}
	private lockBytes(): Buffer {
		return Buffer.from(
			C({
				schema_version: "fv-evidence-lock/v1",
				owner_id: this.record.owner_id,
				owner_file: path.join(this.cwd, OWNER),
				host_id: this.record.host_id,
				boot_id: this.record.boot_id,
				run_id: this.record.run_id,
			} satisfies LockRecord),
		);
	}
	private async tryLocks(files: string[]): Promise<NativeLock | null> {
		if (files.some((file) => this.locks.has(file))) return null;
		const bytes = this.lockBytes(),
			acquired: LockEntry[] = [];
		const registry = path.join(this.cwd, BASE + "/locks/" + this.record.owner_id + ".locks.json");
		const planned = [...new Set([...this.locks.keys(), ...files])]
			.sort(utf8Compare)
			.map((file) => ({ file, hash: H(bytes) }));
		const serialized = Buffer.from(C(planned));
		try {
			await replaceFile(registry, serialized, await checkedBytes(registry));
		} catch (failure) {
			if ((failure as NodeJS.ErrnoException).code !== "ENOENT") {
				this.storageFailed = true;
				throw failure;
			}
			try {
				await exclusiveFile(registry, serialized);
			} catch (storage) {
				this.storageFailed = true;
				throw storage;
			}
		}
		for (const file of files) {
			try {
				await exclusiveFile(file, bytes);
			} catch (failure) {
				if ((failure as NodeJS.ErrnoException).code !== "EEXIST") {
					this.storageFailed = true;
					throw failure;
				}
				try {
					let original: Buffer;
					try {
						original = await checkedBytes(file);
					} catch (race) {
						if ((race as NodeJS.ErrnoException).code === "ENOENT") return null;
						throw race;
					}
					const lock = parseJSON(original) as LockRecord;
					if (
						!lock ||
						typeof lock !== "object" ||
						Object.keys(lock).sort().join(",") !== "boot_id,host_id,owner_file,owner_id,run_id,schema_version" ||
						lock.schema_version !== "fv-evidence-lock/v1" ||
						typeof lock.owner_file !== "string" ||
						!path.isAbsolute(lock.owner_file)
					)
						throw new Error("malformed existing resource/key lock");
					try {
						const owner = validateOwnerRecord(parseJSON(await checkedBytes(lock.owner_file)));
						if (
							owner.owner_id !== lock.owner_id ||
							owner.host_id !== lock.host_id ||
							owner.boot_id !== lock.boot_id ||
							owner.run_id !== lock.run_id
						)
							throw new Error("orphan or changed resource/key owner");
					} catch (ownerFailure) {
						try {
							if (!(await checkedBytes(file)).equals(original)) return null;
						} catch (race) {
							if ((race as NodeJS.ErrnoException).code === "ENOENT") return null;
							throw race;
						}
						throw ownerFailure;
					}
				} finally {
					for (const entry of acquired.toReversed()) {
						await removeMatching(entry);
						this.locks.delete(entry.file);
					}
				}
				return null;
			}
			const entry = { file, bytes };
			acquired.push(entry);
			this.locks.set(file, entry);
		}
		let done = false;
		return {
			release: async () => {
				if (done) return;
				await this.serial;
				if (this.record.spawn_windows.some((window) => window.state === "indeterminate"))
					throw new Error("indeterminate ownership retains resource locks");
				for (const entry of acquired.toReversed()) {
					await removeMatching(entry);
					this.locks.delete(entry.file);
				}
				done = true;
			},
		};
	}
	async acquireKey(key: string, signal?: AbortSignal): Promise<NativeLock> {
		if (!/^sha256:[a-f0-9]{64}$/.test(key)) throw new Error("invalid execution key lock");
		const file = path.join(this.cwd, `${BASE}/locks/key-${key.slice(7)}.lock`);
		for (;;) {
			abort(signal ?? this.signal);
			const lock = await this.withAppendLock(() => this.tryLocks([file]));
			if (lock) return lock;
			await sleep(50, signal ?? this.signal);
		}
	}
	async tryAcquireResources(ids: readonly string[], environment: Record<string, string>): Promise<NativeLock | null> {
		validateEnvironment(environment);
		if (ids.some((id) => !id || id.includes("\0")) || new Set(ids).size !== ids.length)
			throw new Error("invalid resource set");
		if (!ids.length) return { release: async () => {} };
		const root = globalRoot(environment);
		await safeDirectory(root);
		return this.withAppendLock(async () => {
			if (this.record.spawn_windows.some((window) => window.state === "indeterminate"))
				throw new Error("indeterminate ownership prevents resource admission");
			const admission = await this.tryLocks([path.join(root, ".admission")]);
			if (!admission) return null;
			try {
				return await this.tryLocks(
					[...ids].sort(utf8Compare).map((id) => path.join(root, D("lock-resource", id).slice(7))),
				);
			} finally {
				await admission.release();
			}
		});
	}
	async acquireResources(
		ids: readonly string[],
		environment: Record<string, string>,
		signal?: AbortSignal,
	): Promise<NativeLock> {
		for (;;) {
			abort(signal ?? this.signal);
			const lock = await this.tryAcquireResources(ids, environment);
			if (lock) return lock;
			await sleep(50, signal ?? this.signal);
		}
	}
	run(options: NativeRunOptions): Promise<NativeResult> {
		const work = this.runOwned(options);
		this.running.add(work);
		void work.finally(() => this.running.delete(work)).catch(() => {});
		return work;
	}
	async drain(): Promise<void> {
		await Promise.allSettled([...this.running]);
		await this.serial;
		await this.appends;
	}
	async release(): Promise<void> {
		await this.drain();
		if (
			this.storageFailed ||
			this.record.children.length ||
			this.record.spawn_windows.some((window) => window.state !== "closed") ||
			this.record.pending_results.length
		)
			throw new Error("native ownership is unresolved");
		if (this.locks.size) throw new Error("native resource/key locks remain held");
		if (this.rawSubprocesses.size) throw new Error("native subprocess transports remain owned");
		await removeMatching({ file: path.join(this.cwd, OWNER), bytes: this.ownerBytes });
		this.released = true;
	}
	private async runOwned(options: NativeRunOptions): Promise<NativeResult> {
		abort(this.signal);
		abort(options.signal);
		validateEnvironment(options.environment);
		if (options.timeoutSeconds !== null && (!Number.isFinite(options.timeoutSeconds) || options.timeoutSeconds <= 0))
			throw new Error("native deadline must be finite positive or null");
		if ((options.executionKey === undefined) !== (options.attemptId === undefined))
			throw new Error("native attempt and key must be supplied together");
		if (
			options.executionKey &&
			!this.record.pending_results.some(
				(item) => item.execution_key === options.executionKey && item.attempt_id === options.attemptId,
			)
		)
			throw new Error("actual invocation requires durable PendingResult");
		if (this.record.spawn_windows.some((item) => item.state === "indeterminate"))
			throw new Error("indeterminate ownership prevents native dispatch");

		const cwd = options.cwd ? path.resolve(this.cwd, options.cwd) : this.cwd;
		const file = await resolveCommand(options.command, cwd, options.environment);
		const protocol = options.ownershipProtocol ?? null;
		if (protocol !== null && protocol !== "dossier-quint-private-pipes/v1")
			throw new Error("unsupported ownership protocol");
		const startedAt = now();
		const window: SpawnWindow = {
			window_id: randomUUID(),
			protocol: "native-direct/v1",
			execution_key: options.executionKey ?? null,
			attempt_id: options.attemptId ?? null,
			parent: null,
			state: "pending",
		};
		const lifetime: SpawnWindow | null = protocol
			? { ...window, window_id: randomUUID(), protocol, state: "pending" }
			: null;
		const owned: OwnedRegistration[] = [],
			windows: SpawnWindow[] = lifetime ? [window, lifetime] : [window];
		await this.mutate(() => this.record.spawn_windows.push(...windows));
		const stdout: Buffer[] = [],
			stderr: Buffer[] = [];
		let child: NativeChild | undefined,
			direct: OwnedProcess | null = null;
		let endGate: ((bytes?: Uint8Array) => Promise<void>) | undefined;
		let directRegistered = false,
			stdoutEnded = false,
			stderrEnded = false,
			escaped = false;
		const extraStreams: (Readable | Writable)[] = [];
		const extraClosures: Promise<void>[] = [];
		const interruption = Promise.withResolvers<never>();
		void interruption.promise.catch(() => {});
		let control: NativeControlABI;
		const descriptors = new Map<number, { dev: number; ino: number; closed: number }>();
		const shutdownBorrowed = (fd: number, how: 0 | 1 | 2) => {
			const expected = descriptors.get(fd);
			if (!expected) throw new Error("unregistered native control descriptor");
			const requested = how === 0 ? 1 : how === 1 ? 2 : 3,
				missing = requested & ~expected.closed;
			if (!missing) return;
			const actual = syncFs.fstatSync(fd);
			if (actual.dev !== expected.dev || actual.ino !== expected.ino)
				throw new Error("native control descriptor ownership changed: fd=" + fd);
			const direction = missing === 1 ? 0 : missing === 2 ? 1 : 2;
			if (control.shutdown(fd, direction) !== 0) {
				const errno = control.currentErrno();
				if (errno !== osConstants.errno.ENOTCONN)
					throw new Error("native control half-close failed: fd=" + fd + " how=" + direction + " errno=" + errno);
			}
			expected.closed |= requested;
		};
		const createEndpoint = (raw: number, readable: boolean): ControlEndpoint => {
			const duplicate = control.dup(raw);
			if (duplicate < 0) throw new Error("native control duplication failed: errno=" + control.currentErrno());
			const FIOCLEX = process.platform === "darwin" ? 0x20006601 : 0x5451;
			if (control.ioctl(duplicate, FIOCLEX) !== 0) {
				const errno = control.currentErrno();
				syncFs.closeSync(duplicate);
				throw new Error("control duplicate close-on-exec failed: errno=" + errno);
			}
			const duplicateIdentity = syncFs.fstatSync(duplicate);
			const socket = new Socket({ allowHalfOpen: true });
			const connected = Promise.withResolvers<void>(),
				drained = Promise.withResolvers<void>(),
				finished = Promise.withResolvers<void>(),
				closed = Promise.withResolvers<void>();
			let ended = false,
				didConnect = false,
				didFinish = false,
				adopted = false;
			let endCompletion: Promise<void> | undefined;
			socket.once("connect", () => {
				didConnect = true;
				connected.resolve();
			});
			socket.once("end", () => {
				ended = true;
				drained.resolve();
			});
			socket.once("finish", () => {
				didFinish = true;
				finished.resolve();
			});
			socket.on("error", (failure) => {
				connected.reject(failure);
				drained.reject(failure);
				finished.reject(failure);
				error ??= message(failure);
				cancelOwned("error");
			});
			socket.once("close", () => {
				if (!adopted) {
					try {
						const actual = syncFs.fstatSync(duplicate);
						if (actual.dev !== duplicateIdentity.dev || actual.ino !== duplicateIdentity.ino)
							throw new Error("unadopted control duplicate ownership changed");
						syncFs.closeSync(duplicate);
					} catch (failure) {
						error ??= message(failure);
					}
				}
				if (!didConnect) connected.reject(new Error("native control connection closed before admission"));
				if (!didFinish) finished.reject(new Error("native control socket closed before finish"));
				if (!ended && readable) {
					const failure = new Error("native control socket closed before EOF");
					drained.reject(failure);
					error ??= failure.message;
					cancelOwned("error");
				}
				closed.resolve();
			});
			void connected.promise.catch(() => {});
			void drained.promise.catch(() => {});
			void finished.promise.catch(() => {});
			extraStreams.push(socket);
			extraClosures.push(closed.promise);
			return {
				socket,
				connected: connected.promise,
				drained: drained.promise,
				end(bytes) {
					if (endCompletion) return endCompletion;
					const written = Promise.withResolvers<void>();
					endCompletion = Promise.all([written.promise, finished.promise]).then(() => {
						shutdownBorrowed(raw, 1);
					});
					void endCompletion.catch((failure) => {
						error ??= message(failure);
						cancelOwned("error");
					});
					try {
						socket.end(bytes ?? Buffer.alloc(0), written.resolve);
					} catch (failure) {
						written.reject(failure);
					}
					return endCompletion;
				},
				connect() {
					if (adopted) throw new Error("native control endpoint already adopted");
					adopted = true;
					// Bun exposes an existing-fd connect overload beyond Node's typings.
					try {
						socket.connect({ fd: duplicate } as unknown as SocketConnectOpts);
					} catch (failure) {
						socket.destroy();
						throw failure;
					}
				},
			};
		};
		let error: string | null = null,
			timedOut = false,
			cancelled = false,
			exited = false,
			code: number | null = null,
			exitSignal: string | null = null;
		let cancellationCause: unknown;
		const retainError = (failure: unknown) => {
			const detail = message(failure);
			error = error === null ? detail : error + "; " + detail;
		};
		let protocolFailed = false,
			protocolEnd = false,
			controlBuffer = Buffer.alloc(0),
			controlChain = Promise.resolve();
		const hosted = new Map<number, OwnedRegistration>();
		const transportArgv = [process.execPath, "-e", GATE, ...(protocol ? [protocol] : [])];
		const logRelative = `${BASE}/ownership/${this.record.owner_id}/${window.window_id}.jsonl`;
		let log: FileHandle | undefined;
		let logBytes = Buffer.alloc(0),
			logValid = true;
		if (protocol) {
			await exclusiveFile(path.join(this.cwd, logRelative), logBytes);
			log = await fs.open(
				path.join(this.cwd, logRelative),
				syncFs.constants.O_APPEND | syncFs.constants.O_WRONLY | syncFs.constants.O_NOFOLLOW,
			);
		}
		const persistLog = async (bytes: Buffer) => {
			if (!log) throw new Error("missing protocol log");
			try {
				await log.writeFile(bytes);
				await log.sync();
				logBytes = Buffer.concat([logBytes, bytes]);
			} catch (failure) {
				logValid = false;
				throw failure;
			}
		};
		const register = async (identity: OwnedProcess, targetWindow: SpawnWindow) => {
			const entry: OwnedRegistration = {
				process: identity,
				window_id: targetWindow.window_id,
				registered_at: now(),
				terminated_at: null,
			};
			await this.mutate(() => {
				targetWindow.state = "active";
				this.record.children.push(identity);
				owned.push(entry);
			});
			return entry;
		};
		const stopped = async (identity: OwnedProcess) => {
			try {
				return await groupStopped(identity);
			} catch (failure) {
				escaped = true;
				throw failure;
			}
		};
		const signal = async (identity: OwnedProcess, value: NodeJS.Signals) => {
			try {
				await signalOwned(
					identity,
					value,
					owned.map((item) => item.process),
					direct && sameProcess(identity, direct) ? child?.native : undefined,
				);
			} catch (failure) {
				escaped = true;
				throw failure;
			}
		};
		const terminated = async (entry: OwnedRegistration) => {
			if (!(await stopped(entry.process))) throw new Error("owned process group has surviving descendants");
			const finished = owned.filter(
				(item) =>
					!item.terminated_at &&
					item.process.process_group === entry.process.process_group &&
					item.process.session_id === entry.process.session_id,
			);
			await this.mutate(() => {
				const at = finishTime();
				for (const item of finished) item.terminated_at = at;
				this.record.children = this.record.children.filter(
					(item) => !finished.some((registration) => sameProcess(item, registration.process)),
				);
			});
		};
		let killWork: Promise<void> | undefined;
		const cancelOwned = (reason: "timeout" | "cancelled" | "error") => {
			if (reason === "timeout") timedOut = true;
			if (reason === "cancelled") cancelled = true;
			if (reason === "error") interruption.reject(new Error(error ?? "native control operation failed"));
			if (!killWork)
				killWork = (async () => {
					const groups = new Map<number, OwnedRegistration>();
					for (const entry of owned)
						if (!entry.terminated_at && !groups.has(entry.process.process_group))
							groups.set(entry.process.process_group, entry);
					const targets = [...groups.values()];
					const until = performance.now() + MAX_GRACE;
					for (const entry of targets) {
						// Give the collector the existing grace to stop its own registered groups.
						if (!direct || !sameProcess(entry.process, direct)) continue;
						try {
							await signal(entry.process, "SIGTERM");
						} catch (failure) {
							error ??= message(failure);
						}
					}
					while (performance.now() < until) {
						const remaining = await Promise.all(
							targets.map(async (entry) => {
								try {
									return !(await stopped(entry.process));
								} catch (failure) {
									error ??= message(failure);
									return true;
								}
							}),
						);
						if (!remaining.some(Boolean)) return;
						await sleep(Math.min(25, Math.max(0, until - performance.now())));
					}
					for (const entry of targets) {
						try {
							if (!(await stopped(entry.process))) await signal(entry.process, "SIGKILL");
						} catch (failure) {
							error ??= message(failure);
						}
					}
				})();
			void killWork.catch((failure) => {
				error ??= message(failure);
			});
		};
		const controlMessage = async (bytes: Buffer, ack: Writable) => {
			const value = parseJSON(bytes) as { event: string; pgid: number };
			if (
				!value ||
				typeof value !== "object" ||
				Object.keys(value).sort().join(",") !== "event,pgid" ||
				!Number.isSafeInteger(value.pgid) ||
				value.pgid <= 0 ||
				!["owned", "released"].includes(value.event)
			)
				throw new Error("malformed private ownership message");
			if (!direct) throw new Error("collector is not registered");
			const currentCollector = await readProcessIdentity(direct.pid);
			if (
				!currentCollector ||
				!sameProcess(currentCollector, direct) ||
				currentCollector.process_group !== direct.process_group ||
				currentCollector.session_id !== direct.session_id
			)
				throw new Error("collector birth/group/session changed");
			if (value.event === "owned") {
				if (hosted.has(value.pgid)) throw new Error("duplicate private ownership registration");
				const identity = await readProcessIdentity(value.pgid);
				if (
					!identity ||
					identity.pid !== identity.process_group ||
					identity.pid !== identity.session_id ||
					identity.parent_pid !== direct.pid
				)
					throw new Error("foreign private ownership registration");
				await verifyCollectorGate(identity.pid, direct.pid, file);
				const again = await readProcessIdentity(value.pgid);
				if (
					!again ||
					!sameProcess(identity, again) ||
					again.parent_pid !== direct.pid ||
					again.process_group !== identity.process_group ||
					again.session_id !== identity.session_id
				)
					throw new Error("collector child changed before registration");
				const hostedWindow: SpawnWindow = {
					window_id: randomUUID(),
					protocol: "dossier-quint-private-pipes/v1",
					execution_key: window.execution_key,
					attempt_id: window.attempt_id,
					parent: direct,
					state: "pending",
				};
				await this.mutate(() => {
					this.record.spawn_windows.push(hostedWindow);
					windows.push(hostedWindow);
				});
				const registration = await register(identity, hostedWindow);
				hosted.set(value.pgid, registration);
			} else {
				const registration = hosted.get(value.pgid);
				if (!registration || registration.terminated_at) throw new Error("out-of-order private ownership release");
				await terminated(registration);
				await this.mutate(() => {
					windows.find((item) => item.window_id === registration.window_id)!.state = "closed";
				});
			}
			if (protocolFailed || timedOut || cancelled)
				throw new Error("private ownership acknowledgement after cancellation refused");
			const acknowledgement = Promise.withResolvers<void>();
			ack.write(Buffer.from("1"), (failure) => (failure ? acknowledgement.reject(failure) : acknowledgement.resolve()));
			await acknowledgement.promise;
		};
		let deadline: NodeJS.Timeout | undefined;
		let observer: NodeJS.Timeout | undefined;
		let observationWork = Promise.resolve();
		const possibleHosted = new Set<number>();
		let exitPromise: Promise<void> | undefined;
		let drainPromise: Promise<void> | undefined;
		const signals = [...new Set([this.signal, options.signal].filter((item): item is AbortSignal => !!item))];
		const onAbort = () => {
			const signal = signals.find((item) => item.aborted);
			cancellationCause ??=
				signal?.reason instanceof Error ? signal.reason : new DOMException("native operation cancelled", "AbortError");
			interruption.reject(cancellationCause);
			cancelOwned("cancelled");
			void endGate?.();
		};
		try {
			for (const signal of signals) abort(signal);
			const environment = { ...options.environment, ...(protocol ? { [CONTROL]: "3,4" } : {}) };
			const runtime = (globalThis as unknown as { Bun?: NativeRuntime }).Bun;
			if (!runtime) throw new Error("native Bun subprocess runtime unavailable");
			control = await controlLibrary();
			const native = runtime.spawn({
				cmd: transportArgv,
				cwd: path.parse(cwd).root,
				env: { [TRANSPORT_CONTROL]: "1" },
				detached: true,
				stdio: ["ignore", "pipe", "pipe", "pipe", "pipe", "pipe", "pipe", "pipe"],
			});
			this.rawSubprocesses.set(window.window_id, native);
			child = new NativeChild(native);
			const handles = [3, 4, 5, 6, 7].map((index) => {
				const fd = native.stdio[index];
				if (typeof fd !== "number" || !Number.isSafeInteger(fd) || fd < 0)
					throw new Error("native control descriptor unavailable");
				const stat = syncFs.fstatSync(fd);
				descriptors.set(fd, { dev: stat.dev, ino: stat.ino, closed: 0 });
				return fd;
			});
			const gateEndpoint = createEndpoint(handles[2], false),
				readyEndpoint = createEndpoint(handles[3], true),
				execEndpoint = createEndpoint(handles[4], true);
			const eventEndpoint = protocol ? createEndpoint(handles[0], true) : null,
				ackEndpoint = protocol ? createEndpoint(handles[1], false) : null;
			const endpoints = [
				gateEndpoint,
				readyEndpoint,
				execEndpoint,
				...(eventEndpoint && ackEndpoint ? [eventEndpoint, ackEndpoint] : []),
			];
			const terminal = Promise.withResolvers<void>(),
				streamDrain = Promise.withResolvers<void>();
			exitPromise = terminal.promise;
			drainPromise = streamDrain.promise;
			child.once("error", (failure) => {
				terminal.reject(failure);
				streamDrain.resolve();
			});
			child.once("exit", (exitCode, signal) => {
				exited = true;
				code = exitCode;
				exitSignal = signal;
				terminal.resolve();
			});
			child.once("close", () => streamDrain.resolve());
			void exitPromise.catch(() => {});
			(child.stdout as Readable)
				.on("data", (bytes: Buffer) => stdout.push(bytes))
				.on("error", (failure) => {
					error ??= message(failure);
					cancelOwned("error");
				});
			(child.stderr as Readable)
				.on("data", (bytes: Buffer) => stderr.push(bytes))
				.on("error", (failure) => {
					error ??= message(failure);
					cancelOwned("error");
				});
			child.stdout.once("end", () => {
				stdoutEnded = true;
			});
			child.stderr.once("end", () => {
				stderrEnded = true;
			});
			endGate = gateEndpoint.end;
			const gateReady = Promise.withResolvers<void>();
			void gateReady.promise.catch(() => {});
			let readyBytes = 0;
			readyEndpoint.socket.on("data", (bytes: Buffer) => {
				readyBytes += bytes.length;
				if (readyBytes !== 1 || bytes.length !== 1 || bytes[0] !== 49) {
					const failure = new Error("invalid direct launch gate");
					gateReady.reject(failure);
					error ??= failure.message;
					cancelOwned("error");
				} else gateReady.resolve();
			});
			const readiness = readyEndpoint.drained;
			const execBytes: Buffer[] = [];
			execEndpoint.socket.on("data", (bytes: Buffer) => execBytes.push(bytes));
			const execStatus = execEndpoint.drained.then(() => Buffer.concat(execBytes));
			drainPromise = Promise.all([drainPromise, readiness, execStatus]).then(() => {});
			void drainPromise.catch(() => {});
			void readiness.then(() => {
				if (readyBytes !== 1) {
					const failure = new Error("incomplete direct launch gate");
					gateReady.reject(failure);
					error ??= failure.message;
					cancelOwned("error");
				}
			}, gateReady.reject);
			child.once("error", gateReady.reject);
			for (const signal of signals) signal.addEventListener("abort", onAbort, { once: true });
			if (options.timeoutSeconds !== null) {
				const began = performance.now(),
					seconds = options.timeoutSeconds;
				const tick = () => {
					const remaining = seconds - (performance.now() - began) / 1000;
					if (remaining > 0) {
						deadline = setTimeout(tick, Math.min(remaining, 2147483.647) * 1000);
						return;
					}
					cancelOwned("timeout");
					void endGate?.();
					const failure = new Error("native invocation deadline expired");
					gateReady.reject(failure);
					interruption.reject(failure);
				};
				tick();
			}
			if (protocol) {
				const events = eventEndpoint!.socket,
					ack = ackEndpoint!.socket;
				drainPromise = Promise.all([drainPromise, eventEndpoint!.drained]).then(() => {});
				void drainPromise.catch(() => {});
				const protocolError = (failure: unknown) => {
					error ??= message(failure);
					if (protocolFailed) return;
					protocolFailed = true;
					void ackEndpoint!.end();
					cancelOwned("error");
				};
				events.on("data", (bytes: Buffer) => {
					controlChain = controlChain.then(() => persistLog(bytes)).catch(protocolError);
					if (protocolFailed) return;
					controlBuffer = Buffer.concat([controlBuffer, bytes]);
					for (;;) {
						const lf = controlBuffer.indexOf(10);
						if (lf < 0) {
							if (controlBuffer.length > 4096) protocolError(new Error("oversized private ownership message"));
							break;
						}
						const line = controlBuffer.subarray(0, lf);
						controlBuffer = controlBuffer.subarray(lf + 1);
						if (line.length > 4096 || !line.length) {
							protocolError(new Error("invalid private ownership frame"));
							break;
						}
						controlChain = controlChain
							.then(() => {
								if (protocolFailed) throw new Error("private ownership protocol already failed");
								return controlMessage(line, ack);
							})
							.catch(protocolError);
					}
				});
				events.once("end", () => {
					protocolEnd = true;
					if (controlBuffer.length) protocolError(new Error("partial private ownership message"));
				});
				events.once("error", protocolError);
				ack.once("error", protocolError);
			}
			for (const signal of signals) if (signal.aborted) onAbort();
			abort(this.signal);
			abort(options.signal);
			for (const endpoint of endpoints) endpoint.connect();
			await Promise.race([Promise.all(endpoints.map((endpoint) => endpoint.connected)), interruption.promise]);
			await Promise.race([gateReady.promise, interruption.promise]);
			if (!child.pid) throw new Error("native spawn returned no PID");
			direct = await readProcessIdentity(child.pid);
			if (
				!direct ||
				direct.parent_pid !== process.pid ||
				direct.process_group !== child.pid ||
				direct.session_id !== child.pid
			)
				throw new Error("direct child ownership could not be proven");
			await register(direct, window);
			directRegistered = true;

			if (lifetime)
				await this.mutate(() => {
					lifetime.parent = direct;
					lifetime.state = "active";
				});

			const observe = async () => {
				let rows: ProcessRow[];
				try {
					rows = processTable(owned.filter((entry) => !entry.terminated_at).map((entry) => entry.process));
				} catch (failure) {
					escaped = true;
					throw failure;
				}
				const groups = new Map(
					owned.filter((entry) => !entry.terminated_at).map((entry) => [entry.process.process_group, entry]),
				);
				const descendants = new Set<number>();
				for (const entry of owned) {
					if (entry.terminated_at) continue;
					const current = await readProcessIdentity(entry.process.pid);
					if (entry.terminated_at || !current || !sameProcess(current, entry.process)) continue;
					if (
						current.process_group !== entry.process.process_group ||
						current.session_id !== entry.process.session_id
					) {
						escaped = true;
						throw new Error("owned process birth or group identity changed during enumeration");
					}
					descendants.add(current.pid);
				}
				let changed = true;
				while (changed) {
					changed = false;
					for (const row of rows)
						if (descendants.has(row.ppid) && !descendants.has(row.pid)) {
							descendants.add(row.pid);
							changed = true;
						}
				}
				for (const row of rows) {
					const group = groups.get(row.pgid);
					if (group) {
						const identity = await readProcessIdentity(row.pid);
						if (!identity) continue;
						if (owned.some((entry) => !entry.terminated_at && sameProcess(entry.process, identity))) continue;
						if (identity.process_group !== row.pgid || identity.session_id !== group.process.session_id)
							throw new Error("descendant session changed during enumeration");
						try {
							await requireGroupAnchor(
								group.process,
								owned.filter((entry) => !entry.terminated_at).map((entry) => entry.process),
							);
						} catch (failure) {
							escaped = true;
							throw failure;
						}
						await register(identity, windows.find((item) => item.window_id === group.window_id)!);
					} else if (descendants.has(row.pid)) {
						if (protocol && row.ppid === direct!.pid) possibleHosted.add(row.pid);
						else throw new Error("unregistered descendant escaped owned groups");
					}
				}
			};
			observer = setInterval(() => {
				observationWork = observationWork.then(observe).catch((failure) => {
					escaped = true;
					error ??= message(failure);
					cancelOwned("error");
				});
			}, 50);
			let payload: Buffer | undefined;
			if (!cancelled && !timedOut) {
				const bytes = C({ file, argv: [...options.command], cwd, environment });
				payload = Buffer.allocUnsafe(9 + bytes.byteLength);
				payload[0] = 49;
				payload.writeBigUInt64BE(BigInt(bytes.byteLength), 1);
				payload.set(bytes, 9);
			}
			await Promise.race([gateEndpoint.end(payload), interruption.promise]);
			const execFailure = await Promise.race([execStatus, interruption.promise]);
			if (execFailure.byteLength)
				throw new Error("native exec transport: " + new TextDecoder("utf-8", { fatal: true }).decode(execFailure));
			await Promise.race([exitPromise, interruption.promise]);
			clearInterval(observer);
			await observationWork;
			await observe().catch((failure) => {
				escaped = true;
				throw failure;
			});
			if (killWork) await killWork;
			for (const entry of owned) {
				if (entry.terminated_at) continue;
				if (!(await stopped(entry.process))) {
					await signal(entry.process, "SIGTERM");
					const until = performance.now() + MAX_GRACE;
					while (performance.now() < until && !(await stopped(entry.process))) await sleep(25);
					if (!(await stopped(entry.process))) await signal(entry.process, "SIGKILL");
				}
				const until = performance.now() + 5000;
				while (performance.now() < until && !(await stopped(entry.process))) await sleep(25);
				await terminated(entry);
			}
			if (!(await waitWithin(drainPromise!, MAX_GRACE)))
				throw new Error("output/control drain has unproven descendants");
			await controlChain;
			if (!stdoutEnded || !stderrEnded) throw new Error("native output closed before EOF");
			const normalProtocol =
				!escaped &&
				(!protocol ||
					(code !== null &&
						exitSignal === null &&
						!timedOut &&
						!cancelled &&
						!protocolFailed &&
						protocolEnd &&
						!controlBuffer.length &&
						[...possibleHosted].every((pid) => hosted.has(pid)) &&
						[...hosted.values()].every((item) => item.terminated_at)));
			await this.mutate(() => {
				window.state = escaped ? "indeterminate" : "closed";
				if (lifetime) lifetime.state = normalProtocol ? "closed" : "indeterminate";
			});
			if (!normalProtocol) error ??= "collector lifetime has an unresolved registration window";
		} catch (failure) {
			if (!cancelled || failure !== cancellationCause) error ??= message(failure);
			clearInterval(observer);
			void endGate?.();
			cancelOwned("error");
			if (killWork)
				try {
					await killWork;
				} catch (cleanup) {
					retainError(cleanup);
				}
			if (exitPromise)
				await waitWithin(
					exitPromise.catch(() => {}),
					MAX_GRACE,
				);
			await observationWork;
			let streamsDrained = false;
			if (drainPromise) {
				try {
					streamsDrained = await waitWithin(drainPromise, MAX_GRACE);
				} catch (drainFailure) {
					retainError(drainFailure);
				}
			}
			await controlChain;
			for (const entry of owned)
				if (!entry.terminated_at) {
					try {
						if (await stopped(entry.process)) await terminated(entry);
					} catch (cleanup) {
						retainError(cleanup);
					}
				}
			for (const stream of [...(child?.stdio ?? []), ...extraStreams]) stream?.destroy();
			const complete =
				directRegistered && exited && !escaped && !this.storageFailed && streamsDrained && stdoutEnded && stderrEnded;
			try {
				await this.mutate(() => {
					for (const item of windows) {
						if (item.state === "closed") continue;
						const registrations = owned.filter((entry) => entry.window_id === item.window_id);
						item.state =
							item !== lifetime &&
							complete &&
							registrations.length > 0 &&
							registrations.every((entry) => entry.terminated_at !== null)
								? "closed"
								: "indeterminate";
					}
				});
			} catch (storage) {
				retainError(storage);
			}
		} finally {
			clearTimeout(deadline);
			clearInterval(observer);
			for (const signal of signals) signal.removeEventListener("abort", onAbort);
			for (const fd of descriptors.keys()) {
				try {
					shutdownBorrowed(fd, 2);
				} catch (failure) {
					error ??= message(failure);
				}
			}
			for (const stream of extraStreams) stream.destroy();
			const streamsClosed = await waitWithin(
				Promise.all(extraClosures).then(() => {}),
				MAX_GRACE,
			);
			if (!streamsClosed) {
				error ??= "native control stream closure is unproven";
				try {
					await this.mutate(() => {
						for (const item of windows) item.state = "indeterminate";
					});
				} catch (failure) {
					retainError(failure);
				}
			}
			await controlChain;
			if (log) await log.close();
			// Retained ownership blocks release; a live child must not block error reporting.
			if (exited && streamsClosed) this.rawSubprocesses.delete(window.window_id);
			else if (!exited) child?.native.unref();
		}
		const out = Buffer.concat(stdout),
			err = Buffer.concat(stderr);
		try {
			new TextDecoder("utf-8", { fatal: true }).decode(out);
			new TextDecoder("utf-8", { fatal: true }).decode(err);
		} catch {
			error ??= "invalid UTF-8 process output";
		}
		if (!exited) error ??= "native process did not reach a drained terminal state";
		if (
			cancelled &&
			(this.storageFailed ||
				windows.some((item) => item.state !== "closed") ||
				owned.some((item) => item.terminated_at === null))
		)
			error ??= "cancelled ownership is unresolved";
		return {
			stdout: out,
			stderr: err,
			startedAt,
			finishedAt: finishTime(),
			termination: { exit_code: code, signal: exitSignal, timed_out: timedOut, cancelled },
			error,
			transportArgv,
			ownership: {
				schema_version: "fv-execution-ownership/v1",
				owner_id: this.record.owner_id,
				children: clone(owned),
				spawn_windows: clone(windows),
				protocol_log: protocol && logValid ? { path: logRelative, hash: H(logBytes), size: logBytes.length } : null,
			},
		};
	}
}

async function verifyCollectorGate(pid: number, collectorPid: number, admittedExecutable: string): Promise<void> {
	const executable = async (selectedPid: number): Promise<string> => {
		if (process.platform === "linux") return fs.readlink(`/proc/${selectedPid}/exe`);
		const lib = await darwin(),
			buffer = Buffer.alloc(4096);
		const count = lib.proc_pidpath(selectedPid, lib.ptr(buffer), buffer.length);
		if (count <= 0) throw new Error("collector interpreter identity unavailable");
		return new TextDecoder("utf-8", { fatal: true }).decode(buffer.subarray(0, buffer.indexOf(0)));
	};
	const command = async (selectedPid: number): Promise<string[]> => {
		if (process.platform === "linux") {
			const bytes = await fs.readFile(`/proc/${selectedPid}/cmdline`);
			if (!bytes.length || bytes.at(-1) !== 0) throw new Error("incomplete collector gate argv");
			return new TextDecoder("utf-8", { fatal: true }).decode(bytes.subarray(0, -1)).split("\0");
		}
		const lib = await darwin(),
			buffer = Buffer.alloc(1024 * 1024),
			length = Buffer.alloc(8),
			mib = new Int32Array([1, 49, selectedPid]);
		length.writeBigUInt64LE(BigInt(buffer.length));
		if (lib.sysctl(lib.ptr(mib), 3, lib.ptr(buffer), lib.ptr(length), null, 0) !== 0)
			throw new Error("collector gate argv unavailable");
		const argc = buffer.readInt32LE(0);
		let offset = 4;
		if (argc <= 0 || argc > 65536) throw new Error("invalid collector gate argc");
		while (offset < buffer.length && buffer[offset] !== 0) offset++;
		while (offset < buffer.length && buffer[offset] === 0) offset++;
		const args: string[] = [];
		for (let index = 0; index < argc; index++) {
			const end = buffer.indexOf(0, offset);
			if (end < 0) throw new Error("incomplete collector gate argv");
			args.push(buffer.subarray(offset, end).toString("utf8"));
			offset = end + 1;
		}
		return args;
	};
	const args = await command(pid),
		collectorArgs = await command(collectorPid);
	const childExecutable = await executable(pid),
		collectorExecutable = await executable(collectorPid);
	const [childImage, collectorImage] = await Promise.all([
		fs.stat(childExecutable, { bigint: true }),
		fs.stat(collectorExecutable, { bigint: true }),
	]);
	let matched =
		childImage.isFile() &&
		collectorImage.isFile() &&
		childImage.dev === collectorImage.dev &&
		childImage.ino === collectorImage.ino;
	let admittedCanonical: string | null = null,
		argvCanonical: string | null = null;
	if (!matched && process.platform === "darwin" && path.isAbsolute(args[0] ?? "")) {
		[admittedCanonical, argvCanonical] = await Promise.all([
			canonicalToolPath(admittedExecutable),
			canonicalToolPath(args[0]),
		]);
		const admittedImage = await fs.stat(admittedCanonical, { bigint: true });
		matched =
			childImage.isFile() &&
			admittedImage.isFile() &&
			childImage.dev === admittedImage.dev &&
			childImage.ino === admittedImage.ino &&
			argvCanonical === admittedCanonical;
	}
	if (!matched)
		throw new Error(
			"collector child uses a different actual interpreter: " +
				JSON.stringify({
					child: { pid, executable: childExecutable, argv0: args[0] ?? null },
					collector: { pid: collectorPid, executable: collectorExecutable, argv0: collectorArgs[0] ?? null },
					admitted: {
						executable: admittedExecutable,
						canonical: admittedCanonical,
						child_argv0_canonical: argvCanonical,
					},
				}),
		);
	if (
		args.length < 7 ||
		args.some((value) => !value || value.includes("\0")) ||
		args[1] !== "-I" ||
		args[2] !== "-B" ||
		args[3] !== "-c" ||
		args[4] !== COLLECTOR_GATE ||
		!/^\d+$/.test(args[5])
	)
		throw new Error("child is not behind the approved collector gate");
}
export async function createNativeSession(options: NativeSessionOptions): Promise<NativeSession> {
	abort(options.signal);
	if (process.platform !== "darwin" && process.platform !== "linux")
		throw new Error("native v4 requires POSIX Darwin/Linux");
	if (!/^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/.test(options.runId))
		throw new Error("invalid native run UUID");
	const cwd = await fs.realpath(options.cwd);
	await safeDirectory(path.join(cwd, `${BASE}/locks`));
	const identity = await readProcessIdentity(process.pid);
	if (!identity) throw new Error("producer birth identity unavailable");
	const machine = await machineIdentity();
	const owner: OwnerRecord = {
		schema_version: "fv-evidence-owner/v1",
		owner_id: randomUUID(),
		...machine,
		pid: identity.pid,
		process_start_id: identity.process_start_id,
		run_id: options.runId,
		created_at: now(),
		children: [],
		spawn_windows: [],
		pending_results: [],
	};
	const bytes = Buffer.from(C(owner));
	await exclusiveFile(path.join(cwd, OWNER), bytes);
	return new NativeSession(cwd, owner, bytes, options.signal);
}

export async function recoverOwner(options: RecoveryOptions): Promise<void> {
	validateOwnerRecord(options.expectedOwner);
	const cwd = await fs.realpath(options.cwd),
		file = path.join(cwd, OWNER),
		expected = Buffer.from(C(options.expectedOwner));
	if (!(await checkedBytes(file)).equals(expected))
		throw new Error("recovery owner differs from expected serialized owner");
	const guard = {
		file: path.join(cwd, `${BASE}/locks/recovery.lock`),
		bytes: Buffer.from(C({ owner_id: options.expectedOwner.owner_id, recovery_id: randomUUID() })),
	};
	await exclusiveFile(guard.file, guard.bytes);
	try {
		const owner = options.expectedOwner,
			machine = await machineIdentity();
		if (owner.host_id !== machine.host_id) throw new Error("remote/unknown ownership recovery refused");
		const previousBoot = owner.boot_id !== machine.boot_id;
		if (!previousBoot) {
			const process = await readProcessIdentity(owner.pid);
			if (process)
				throw new Error(
					process.process_start_id === owner.process_start_id
						? "live owner recovery refused"
						: "reused owner PID recovery refused",
				);
			if (owner.spawn_windows.some((window) => window.state !== "closed"))
				throw new Error("unprovable pending/gated/unregistered window recovery refused");
			for (const child of owner.children)
				if (!(await groupStopped(child))) throw new Error("live owned descendants recovery refused");
		}
		if (!(await checkedBytes(file)).equals(expected)) throw new Error("owner changed during recovery");
		const preserved = path.join(cwd, `${BASE}/recovered-owners/${owner.owner_id}.json`);
		try {
			await exclusiveFile(preserved, expected);
		} catch (failure) {
			if ((failure as NodeJS.ErrnoException).code !== "EEXIST" || !(await checkedBytes(preserved)).equals(expected))
				throw failure;
		}
		let appendTail: Promise<unknown> = Promise.resolve();
		const withAppendLock: NativeAppendLock = (fn) => {
			const work = appendTail.then(async () => {
				if (!(await checkedBytes(file)).equals(expected) || !(await checkedBytes(guard.file)).equals(guard.bytes))
					throw new Error("recovery append guard changed");
				return fn();
			});
			appendTail = work.catch(() => {});
			return work;
		};
		await options.account(clone(owner), withAppendLock);
		await appendTail;
		if (!(await checkedBytes(file)).equals(expected)) throw new Error("owner changed before retirement");
		const registry = path.join(cwd, `${BASE}/locks/${owner.owner_id}.locks.json`);
		let entries: { file: string; hash: string }[] = [];
		try {
			entries = parseJSON(await checkedBytes(registry)) as typeof entries;
		} catch (error) {
			if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
		}
		if (
			!Array.isArray(entries) ||
			entries.some(
				(entry, index) =>
					!entry ||
					typeof entry !== "object" ||
					Object.keys(entry).sort().join(",") !== "file,hash" ||
					typeof entry.file !== "string" ||
					!path.isAbsolute(entry.file) ||
					path.resolve(entry.file) !== entry.file ||
					!/^sha256:[a-f0-9]{64}$/.test(entry.hash) ||
					(index > 0 && utf8Compare(entries[index - 1].file, entry.file) >= 0),
			)
		)
			throw new Error("malformed recovery lock registry");
		for (const entry of entries) {
			let bytes: Buffer;
			try {
				bytes = await checkedBytes(entry.file);
			} catch (error) {
				if ((error as NodeJS.ErrnoException).code === "ENOENT") continue;
				throw error;
			}
			const lock = parseJSON(bytes) as LockRecord;
			if (lock.owner_id !== owner.owner_id) continue;
			if (
				H(bytes) !== entry.hash ||
				lock.schema_version !== "fv-evidence-lock/v1" ||
				lock.owner_file !== file ||
				lock.host_id !== owner.host_id ||
				lock.boot_id !== owner.boot_id ||
				lock.run_id !== owner.run_id
			)
				throw new Error("resource lock recovery identity mismatch");
			await removeMatching({ file: entry.file, bytes });
		}
		const retired = path.join(cwd, `${BASE}/locks/retired-${owner.owner_id}.lock`);
		if (!(await checkedBytes(file)).equals(expected)) throw new Error("owner changed before atomic retirement");
		try {
			await fs.lstat(retired);
			throw new Error("owner retirement already exists");
		} catch (error) {
			if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
		}
		await fs.rename(file, retired);
		await syncDirectory(path.dirname(file));
	} finally {
		await removeMatching(guard);
	}
}
