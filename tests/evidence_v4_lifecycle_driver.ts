import { createInterface } from "node:readline";
import { randomUUID } from "node:crypto";
import { createNativeSession, readProcessIdentity, recoverOwner } from "../tools/evidence-v4/evidence-v4-native.ts";
import { openEvidenceStore } from "../tools/evidence-v4/evidence-v4-store.ts";
import { runEvidenceV4WithStoreOptions } from "../tools/evidence-v4/evidence-v4-run.ts";

const lines = createInterface({ input: process.stdin });
const iterator = lines[Symbol.asyncIterator]();
const initial = await iterator.next();
if (initial.done) throw new Error("missing lifecycle request");
const request = JSON.parse(initial.value);
const abort = new AbortController();
const controls = (async () => {
	for await (const line of iterator) {
		if (line === "abort") abort.abort();
		if (line === "exit") process.exit(0);
	}
})();
void controls;
const emit = (value: unknown) => console.log(JSON.stringify(value));
let nativeFailure: { native_results: unknown[]; owner: unknown } | undefined;
try {
	if (request.mode === "identity") {
		emit({ event: "result", identity: await readProcessIdentity(request.pid) });
	} else if (request.mode === "recover") {
		await recoverOwner({
			cwd: request.cwd,
			expectedOwner: request.owner,
			account: async (owner, withAppendLock) => {
				const store = await openEvidenceStore(request.cwd, { withAppendLock });
				await store.accountPending(owner);
			},
		});
		emit({ event: "result", recovered: true });
	} else if (request.mode === "crash-run" || request.mode === "fault-run") {
		let reached = false;
		let armed = !request.arm_path;
		const result = await runEvidenceV4WithStoreOptions(
			{ cwd: request.cwd },
			request.call,
			{
				syscallBarrier: async (operation, path, phase) => {
					if (
						request.arm_path &&
						operation === "rename" &&
						phase === "after" &&
						new RegExp(request.arm_path).test(path)
					)
						armed = true;
					if (
						!armed ||
						reached ||
						operation !== request.operation ||
						phase !== request.phase ||
						!new RegExp(request.path).test(path)
					)
						return;
					reached = true;
					emit({ event: "barrier", operation, path, phase });
					if (request.mode === "fault-run") throw new Error("injected storage barrier failure");
					await new Promise<void>(() => {});
				},
			},
			abort.signal,
		);
		emit({ event: "result", value: result, reached });
	} else {
		const session = await createNativeSession({ cwd: request.cwd, runId: randomUUID(), signal: abort.signal });
		emit({ event: "owner", owner: session.owner });
		if (request.mode === "resource-hold") {
			const lock = await session.tryAcquireResources(request.resources, request.environment);
			emit({ event: "resources", acquired: lock !== null });
			if (lock) {
				try {
					await new Promise<void>((resolve) => abort.signal.addEventListener("abort", () => resolve(), { once: true }));
				} finally {
					await lock.release();
				}
			}
			await session.release();
			emit({ event: "result", acquired: lock !== null, released: true });
		} else if (request.mode === "native-concurrent") {
			if (!Array.isArray(request.commands) || request.commands.length !== 4)
				throw new Error("concurrent fixture requires four commands");
			const completed = new Array<Awaited<ReturnType<typeof session.run>> | null>(4).fill(null);
			try {
				const values = await Promise.all(
					(request.commands as string[][]).map(async (command, index) => {
						const value = await session.run({
							command,
							cwd: request.cwd,
							environment: request.environment,
							timeoutSeconds: request.timeout_seconds ?? 30,
							signal: abort.signal,
						});
						completed[index] = value;
						return value;
					}),
				);
				await session.drain();
				await session.release();
				emit({
					event: "result",
					released: true,
					values: values.map((value) => ({
						...value,
						stdout: value.stdout.toString("utf8"),
						stderr: value.stderr.toString("utf8"),
					})),
				});
			} catch (error) {
				abort.abort();
				try {
					await session.drain();
					await session.release();
				} finally {
					nativeFailure = { native_results: completed, owner: session.owner };
				}
				throw error;
			}
		} else if (request.mode === "owner-hold") {
			await new Promise<void>((resolve) => abort.signal.addEventListener("abort", () => resolve(), { once: true }));
			await session.release();
			emit({ event: "result", released: true });
		} else {
			const completed: unknown[] = [];
			try {
				const value = await session.run({
					command: request.command,
					cwd: request.cwd,
					environment: request.environment,
					timeoutSeconds: request.timeout_seconds ?? 15,
					ownershipProtocol: request.ownership_protocol ?? null,
					signal: abort.signal,
				});
				completed.push(value);
				await session.drain();
				emit({
					event: "result",
					value: { ...value, stdout: value.stdout.toString("utf8"), stderr: value.stderr.toString("utf8") },
				});
			} finally {
				try {
					await session.release();
				} catch (error) {
					nativeFailure = { native_results: completed, owner: session.owner };
					throw error;
				}
			}
		}
	}
} catch (error) {
	emit({ event: "error", reason: String(error), stack: error instanceof Error ? error.stack : null, ...nativeFailure });
	process.exitCode = 1;
} finally {
	lines.close();
	process.stdin.destroy();
}
