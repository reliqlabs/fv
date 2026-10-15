import * as fs from "node:fs/promises";
import * as path from "node:path";
import { randomUUID } from "node:crypto";
import {
	C,
	H,
	decodeUTF8,
	parseJSON,
	utf8Compare,
	validateObservationRequest,
	validateObservationResponse,
	validateObservationCheck,
	validatePlanResult,
	validateRunResult,
	type V4Call,
	type InputState,
	type ExecutionDescriptor,
	type ExecutionRef,
	type ExecutionArtifact,
	type FileRef,
	type Producer,
	type PendingResult,
	type ObservationCheck,
	type ClaimRecord,
	type RunManifest,
	type PlanResult,
	type RunResult,
	type Result,
	type Owner,
	type BuildCacheIdentity,
} from "./evidence-v4-model";
import {
	loadPolicy,
	validateCall,
	expandPolicy,
	safeDirectoryPath,
	type LoadedPolicy,
	type ExpandedExecution,
	type ExpandedSlot,
} from "./evidence-v4-policy";
import {
	buildEnvironment,
	captureInputState,
	sameInputState,
	materializeDescriptor,
	descriptorKeys,
	type SanitizedEnvironment,
} from "./evidence-v4-source";
import {
	createNativeSession,
	recoverOwner,
	type NativeSession,
	type NativeLock,
	type NativeResult,
} from "./evidence-v4-native";
import { createToolchainSession, producerImplementationHash, type ToolchainSession } from "./evidence-v4-toolchain";
import {
	openEvidenceStore,
	reconstructRawOutput,
	markerMatches,
	barrierApplies,
	type Store,
	type StoreOptions,
	type HistorySnapshot,
	type CandidateSelection,
} from "./evidence-v4-store";
import { readContainedBytes, retainCollectorAttachments } from "./evidence-v4-attachments";

const BASE = ".fv/evidence/v4";
const EMPTY_TERMINATION = { exit_code: null, signal: null, timed_out: false, cancelled: false };
const LINE_BREAKS = /\r\n|[\n\r\v\f\x1c-\x1e\u0085\u2028\u2029]/;
const RESERVED_TRAILER = /^--- fv-evidence(?:-v4)?: (?:exit=|result=).* ---$/;
type Host = { cwd: string };
type SlotAssessment = ClaimRecord["executions"][number];
type Work = RunManifest["work"][number];
type Physical = {
	expansion: ExpandedExecution;
	descriptor: ExecutionDescriptor | null;
	work: Work;
	candidates: CandidateSelection[];
	cacheEligibility: PlanResult["physical_slots"][number]["cache"];
};
type BarrierOptions = Pick<StoreOptions, "syscallBarrier">;

function message(error: unknown): string {
	return error instanceof Error ? error.message : String(error);
}
type OperationFailure = { error: unknown };
async function releaseNativeLock(lock: NativeLock, failure: OperationFailure | null): Promise<void> {
	try {
		await lock.release();
	} catch (cleanup) {
		if (failure)
			throw new AggregateError(
				[failure.error, cleanup],
				`${message(failure.error)}; native lock release failed: ${message(cleanup)}`,
				{ cause: failure.error },
			);
		throw cleanup;
	}
}
async function withNativeLock<T>(lock: NativeLock, operation: () => Promise<T>): Promise<T> {
	let failure: OperationFailure | null = null;
	try {
		return await operation();
	} catch (error) {
		failure = { error };
		throw error;
	} finally {
		await releaseNativeLock(lock, failure);
	}
}
function equal(a: unknown, b: unknown): boolean {
	return H(C(a)) === H(C(b));
}
function now(): string {
	return new Date().toISOString();
}
function normal(result: NativeResult): boolean {
	return (
		result.termination.exit_code !== null &&
		result.termination.signal === null &&
		!result.termination.timed_out &&
		!result.termination.cancelled
	);
}
function closed(result: NativeResult): boolean {
	return (
		result.ownership.children.every((child) => child.terminated_at !== null) &&
		result.ownership.spawn_windows.every((window) => window.state === "closed")
	);
}
function fileRef(relative: string, bytes: Uint8Array): FileRef {
	return { path: relative, hash: H(bytes), size: bytes.length };
}
function slotKey(claim: string, slot: string): string {
	return `${claim}\0${slot}`;
}
function observationRef(check: FileRef, receipt: ObservationCheck): NonNullable<SlotAssessment["observation"]> {
	return { check, response: receipt.response, result: receipt.result };
}
class Serial {
	private tail: Promise<unknown> = Promise.resolve();
	run<T>(operation: () => Promise<T>): Promise<T> {
		const result = this.tail.then(operation);
		this.tail = result.catch(() => {});
		return result;
	}
}

export function runEvidenceV4(host: Host, value: unknown, signal?: AbortSignal): Promise<PlanResult | RunResult> {
	return runNative(host, value, {}, signal);
}

// This seam observes actual storage syscalls; it cannot supply processes, bytes or results.
export function runEvidenceV4WithStoreOptions(
	host: Host,
	value: unknown,
	options: BarrierOptions,
	signal?: AbortSignal,
): Promise<PlanResult | RunResult> {
	if (Object.keys(options).some((key) => key !== "syscallBarrier"))
		throw new Error("unsupported native storage observation option");
	return runNative(host, value, options, signal);
}

export async function recoverEvidenceV4Owner(host: Host, expectedOwner: Owner): Promise<void> {
	const root = await fs.realpath(path.resolve(host.cwd));
	await recoverOwner({
		cwd: root,
		expectedOwner,
		account: async (owner, withAppendLock) => {
			const store = await openEvidenceStore(root, { withAppendLock });
			await store.accountPending(owner);
		},
	});
}

async function runNative(
	host: Host,
	value: unknown,
	options: BarrierOptions,
	signal?: AbortSignal,
): Promise<PlanResult | RunResult> {
	const call = validateCall(value);
	const root = await fs.realpath(path.resolve(host.cwd));
	const loaded = await loadPolicy(root, call.policy);
	const expanded = expandPolicy(loaded.policy);
	const records = loaded.policy.records.map((record) => record.claim_id);
	const selected = call.records ?? records;
	for (const claim of selected) if (!records.includes(claim)) throw new Error(`unknown policy record: ${claim}`);
	const jobs = call.jobs ?? loaded.policy.jobs.default;
	if (jobs > loaded.policy.jobs.max) throw new Error(`jobs exceeds reviewed maximum ${loaded.policy.jobs.max}`);
	const producer: Producer = {
		name: "fv_evidence_run",
		schema_version: "fv-evidence-run/v4",
		implementation_hash: await producerImplementationHash(),
		host_contract: "fv-producer-host/v1",
	};
	return new Invocation(root, call, loaded, expanded.executions, selected, jobs, producer, options, signal).run();
}

class Invocation {
	private readonly runId = randomUUID();
	private readonly startedAt = now();
	private readonly selectedSet: Set<string>;
	private readonly resources: string[];
	private readonly physical: Physical[];
	private readonly assessments = new Map<string, SlotAssessment>();
	private readonly checkpoint = new Serial();
	private session: NativeSession | null = null;
	private store: Store | null = null;
	private tools: ToolchainSession | null = null;
	private environment: SanitizedEnvironment | null = null;
	private baseline: InputState | null = null;
	private finalSource: InputState | null = null;
	private history: HistorySnapshot = { view: { head: null, events: [] }, events: [] };
	private halted = false;
	private operationalError: string | null = null;
	private readonly operationalFailures = new Set<string>();
	private observationBarrier = 0;
	private preflight: RunManifest["preflight"];

	constructor(
		private root: string,
		private call: V4Call,
		private loaded: LoadedPolicy,
		executions: ExpandedExecution[],
		private selected: string[],
		private jobs: number,
		private producer: Producer,
		private options: BarrierOptions,
		private signal?: AbortSignal,
	) {
		this.selectedSet = new Set(selected);
		this.resources = [
			...new Set([
				...loaded.policy.recipes.flatMap((recipe) => recipe.resources),
				...loaded.policy.preflight.flatMap((check) => check.resources),
				...loaded.policy.claim_checker.resources,
			]),
		].sort(utf8Compare);
		this.physical = executions.map((expansion) => ({
			expansion,
			descriptor: null,
			candidates: [],
			cacheEligibility: "not-checked",
			work: {
				recipe_id: expansion.recipe.recipe_id,
				distinct_slot: expansion.distinct,
				execution_key: null,
				execution: null,
				state: "MISSING",
				cache: "not-checked",
				reason: expansion.members.some((member) => this.selectedSet.has(member.claim_id))
					? "preflight-failed"
					: "not-selected",
			},
		}));
		for (const physical of this.physical)
			for (const slot of physical.expansion.slots)
				this.assessments.set(slotKey(slot.claim_id, slot.slot_id), {
					slot_id: slot.slot_id,
					tool: slot.tool,
					recipe_id: slot.recipe_id,
					evidence_class: slot.recipe.evidence_class,
					execution: null,
					state: "MISSING",
					reason: this.selectedSet.has(slot.claim_id) ? "preflight-failed" : "not-selected",
					observation_binding: slot.record.executions.find((entry) => entry.slot_id === slot.slot_id)!
						.observation_binding,
					blocking_events: [],
					observation: null,
				});
		this.preflight = {
			result: "ERROR",
			reason: "preflight-not-completed",
			checks: loaded.policy.preflight.map((check) => ({
				id: check.id,
				result: "MISSING",
				termination: { ...EMPTY_TERMINATION },
				stdout: null,
				stderr: null,
				reason: "preflight-not-dispatched",
			})),
		};
	}

	private fail(error: unknown): void {
		this.halted = true;
		if (error instanceof AggregateError && error.errors.length > 0) {
			for (const cause of error.errors) this.fail(cause);
			return;
		}
		if (this.cancellationCause(error)) return;
		const detail = message(error);
		if (this.operationalFailures.has(detail)) return;
		this.operationalFailures.add(detail);
		this.operationalError = this.operationalError === null ? detail : `${this.operationalError}; ${detail}`;
	}
	private cancelled(): boolean {
		return this.signal?.aborted === true;
	}
	private cancellationCause(error: unknown): boolean {
		if (!this.cancelled()) return false;
		const seen = new Set<object>();
		while (error !== null && typeof error === "object" && !seen.has(error)) {
			seen.add(error);
			if (error instanceof Error) {
				if (error === this.signal?.reason || error.name === "AbortError") return true;
				error = error.cause;
				continue;
			}
			const result = error as Partial<NativeResult>;
			return (
				result.error === null &&
				result.termination?.cancelled === true &&
				result.ownership != null &&
				Array.isArray(result.ownership.children) &&
				Array.isArray(result.ownership.spawn_windows) &&
				closed(result as NativeResult)
			);
		}
		return false;
	}
	private requireSession(): NativeSession {
		if (!this.session) throw new Error("native session unavailable");
		return this.session;
	}
	private requireStore(): Store {
		if (!this.store) throw new Error("durable store unavailable");
		return this.store;
	}
	private requireTools(): ToolchainSession {
		if (!this.tools) throw new Error("toolchain session unavailable");
		return this.tools;
	}
	private requireEnvironment(): SanitizedEnvironment {
		if (!this.environment) throw new Error("sanitized environment unavailable");
		return this.environment;
	}
	private requireBaseline(): InputState {
		if (!this.baseline) throw new Error("initial input state unavailable");
		return this.baseline;
	}
	private async input(): Promise<InputState> {
		const env = this.requireEnvironment().env;
		return captureInputState(
			this.root,
			this.loaded,
			async (command, cwd, signal) => {
				const result = await this.requireSession().run({ command, cwd, environment: env, timeoutSeconds: 60, signal });
				if (result.error || !normal(result) || !closed(result))
					throw new Error(
						`source metadata ${JSON.stringify(command)}: ${result.error ?? "source metadata process did not close normally"}`,
						{ cause: result },
					);
				return { stdout: result.stdout, stderr: result.stderr, exit_code: result.termination.exit_code };
			},
			this.signal,
		);
	}
	private async stableInput(): Promise<InputState> {
		const input = await this.input();
		if (!sameInputState(this.requireBaseline(), input))
			throw new Error("verified input state moved or became dirty during invocation");
		return input;
	}
	private environmentAfter(): SanitizedEnvironment["identity"] {
		const identity = buildEnvironment(this.loaded.policy).identity;
		if (!equal(identity, this.requireEnvironment().identity))
			throw new Error("semantic environment moved during invocation");
		return identity;
	}
	private async snapshotHistory(): Promise<HistorySnapshot> {
		return this.checkpoint.run(async () => (this.history = await this.requireStore().readHistory()));
	}

	async run(): Promise<PlanResult | RunResult> {
		try {
			this.environment = buildEnvironment(this.loaded.policy);
			this.session = await createNativeSession({ cwd: this.root, runId: this.runId, signal: this.signal });
			this.store = await openEvidenceStore(this.root, {
				...this.options,
				withAppendLock: (fn) => this.requireSession().withAppendLock(fn),
			});
			this.baseline = await this.input();
			if (!this.baseline.clean) throw new Error("verified inputs are dirty");
			this.tools = createToolchainSession({
				root: this.root,
				policy: this.loaded.policy,
				env: this.environment.env,
				session: this.session,
				signal: this.signal,
			});
			if ((await this.tools.implementationHash()) !== this.producer.implementation_hash)
				throw new Error("producer implementation moved before preflight");
			await this.preflightAll();
		} catch (error) {
			this.fail(error);
			this.preflight.result = this.cancelled() ? "CANCELLED" : "ERROR";
			this.preflight.reason = message(error);
		}
		if (this.call.mode === "plan") {
			await this.finishSession();
			return validatePlanResult({
				schema_version: "fv-evidence-plan/v1",
				policy_path: this.loaded.path,
				policy_hash: this.loaded.hash,
				result:
					this.operationalError === null && this.preflight.result === "PASS" && !this.cancelled() ? "READY" : "ERROR",
				reason: this.operationalError ?? this.preflight.reason ?? (this.cancelled() ? "invocation cancelled" : null),
				required_records: this.loaded.policy.records
					.filter((record) => record.required)
					.map((record) => record.claim_id),
				selected_records: this.selected,
				canonical_required_targets: this.loaded.common.required_targets,
				jobs: this.jobs,
				physical_slots: this.physical.map((physical) => ({
					recipe_id: physical.expansion.recipe.recipe_id,
					distinct_slot: physical.expansion.distinct,
					members: physical.expansion.members,
					execution_key: physical.work.execution_key,
					resources: physical.expansion.recipe.resources,
					exclusive: physical.expansion.recipe.exclusive,
					cache: physical.cacheEligibility,
				})),
			});
		}
		if (!this.halted) await this.schedule();
		if (this.session) {
			await this.session.drain().catch((error) => this.fail(error));
			const ownerBeforeFinal = this.session.owner;
			if (
				!this.cancelled() &&
				this.baseline &&
				this.tools &&
				!ownerBeforeFinal.pending_results.length &&
				!ownerBeforeFinal.children.length &&
				ownerBeforeFinal.spawn_windows.every((window) => window.state === "closed")
			) {
				try {
					const resources = await this.session.tryAcquireResources(this.resources, this.requireEnvironment().env);
					if (!resources) throw new Error("final toolchain resource ownership conflict");
					await withNativeLock(resources, async () => {
						const tools = this.requireTools();
						await tools.revalidate();
						this.environmentAfter();
						if ((await tools.implementationHash()) !== this.producer.implementation_hash)
							throw new Error("producer implementation moved");
						this.finalSource = await this.stableInput();
					});
				} catch (error) {
					this.fail(error);
				}
			}
			const owner = this.session.owner;
			if (
				owner.children.length ||
				owner.pending_results.length ||
				owner.spawn_windows.some((window) => window.state !== "closed")
			)
				this.fail("native ownership or pending history remains unresolved");
		}
		if (this.store) {
			try {
				await this.snapshotHistory();
			} catch (error) {
				this.fail(error);
			}
			await this.assessFullHistory().catch((error) => this.fail(error));
		}
		const result = await this.publish();
		await this.finishSession();
		if (this.operationalError && result.result === "PASS")
			return validateRunResult({ ...result, result: "ERROR", reason: this.operationalError });
		if (this.cancelled() && result.result === "PASS")
			return validateRunResult({ ...result, result: "CANCELLED", reason: "invocation cancelled after collection" });
		if (this.operationalError) return validateRunResult({ ...result, reason: this.operationalError });
		return result;
	}

	private async preflightAll(): Promise<void> {
		const tools = this.requireTools(),
			env = this.requireEnvironment();
		try {
			await this.snapshotHistory();
		} catch (error) {
			for (const physical of this.physical) physical.cacheEligibility = "corrupt";
			throw error;
		}
		await this.requireStore().writeImmutableFile(
			`${BASE}/runs/${this.runId}/preflight/storage.bin`,
			Buffer.from(this.runId),
		);
		const resources = await this.requireSession().tryAcquireResources(this.resources, env.env);
		if (!resources) throw new Error("preflight resource ownership conflict");
		await withNativeLock(resources, async () => {
			const allTools = await tools.capture();
			for (const check of [...this.loaded.policy.preflight, this.loaded.policy.claim_checker]) {
				await safeDirectoryPath(this.root, check.cwd);
				await tools.assertCommandBound(check.command, check.cwd, check.toolchain);
			}
			for (const physical of this.physical) {
				const recipe = physical.expansion.recipe;
				await safeDirectoryPath(this.root, recipe.cwd);
				await tools.assertCommandBound(recipe.command, recipe.cwd, recipe.toolchain);
				physical.descriptor = materializeDescriptor({
					loaded: this.loaded,
					input: this.requireBaseline(),
					recipe,
					distinct: physical.expansion.distinct,
					environment: env.identity,
					toolchains: allTools,
					buildCache: await tools.buildCache(recipe),
				});
				physical.work.execution_key = descriptorKeys(physical.descriptor).execution_key;
			}
		});
		for (const physical of this.physical) {
			try {
				physical.candidates = await this.checkpoint.run(() =>
					this.requireStore().selectCandidates(physical.descriptor!, physical.expansion.members, this.history),
				);
				const selected = physical.candidates.filter((member) => this.selectedSet.has(member.member.claim_id));
				physical.cacheEligibility = (selected.length ? selected : physical.candidates).every(
					(member) => member.candidate,
				)
					? "eligible"
					: "miss";
			} catch (error) {
				physical.cacheEligibility = "corrupt";
				throw error;
			}
		}
		for (const [index, check] of this.loaded.policy.preflight.entries()) {
			if (this.cancelled()) throw this.signal?.reason ?? new Error("cancelled before preflight dispatch");
			const entry = this.preflight.checks[index]!;
			const resources = await this.requireSession().acquireResources(check.resources, env.env, this.signal);
			try {
				await withNativeLock(resources, async () => {
					await tools.revalidate(check.toolchain);
					this.environmentAfter();
					await this.stableInput();
					const actual = await this.requireSession().run({
						command: check.command,
						cwd: await safeDirectoryPath(this.root, check.cwd),
						environment: env.env,
						timeoutSeconds: check.timeout_seconds,
						signal: this.signal,
					});
					entry.termination = actual.termination;
					entry.stdout = await this.requireStore().writeImmutableFile(
						`${BASE}/runs/${this.runId}/preflight/${check.id}/stdout.bin`,
						actual.stdout,
					);
					entry.stderr = await this.requireStore().writeImmutableFile(
						`${BASE}/runs/${this.runId}/preflight/${check.id}/stderr.bin`,
						actual.stderr,
					);
					decodeUTF8(actual.stdout);
					decodeUTF8(actual.stderr);
					await tools.revalidate(check.toolchain);
					this.environmentAfter();
					await this.stableInput();
					if (actual.error || !normal(actual) || !closed(actual) || actual.termination.exit_code !== 0)
						throw new Error(actual.error ?? `preflight ${check.id} did not complete successfully`);
					entry.result = "PASS";
					entry.reason = null;
				});
			} catch (error) {
				entry.result = this.cancelled() ? "CANCELLED" : "ERROR";
				entry.reason = message(error);
				throw error;
			}
		}
		await this.stableInput();
		const finalResources = await this.requireSession().tryAcquireResources(this.resources, env.env);
		if (!finalResources) throw new Error("post-preflight resource ownership conflict");
		await withNativeLock(finalResources, async () => {
			await tools.revalidate();
			this.environmentAfter();
			await this.stableInput();
		});
		this.preflight.result = "PASS";
		this.preflight.reason = null;
		for (const physical of this.physical)
			if (physical.expansion.members.some((member) => this.selectedSet.has(member.claim_id)))
				physical.work.reason = "halted-before-dispatch";
	}

	private async schedule(): Promise<void> {
		const queue = this.physical.filter((physical) =>
			physical.expansion.members.some((member) => this.selectedSet.has(member.claim_id)),
		);
		const active = new Set<Promise<void>>();
		let exclusive = false;
		try {
			while (queue.length || active.size) {
				if (this.cancelled()) this.halted = true;
				let admitted = false;
				if (!this.halted && !exclusive && this.observationBarrier === 0)
					for (let index = 0; index < queue.length && active.size < this.jobs; ) {
						const physical = queue[index]!;
						if (physical.expansion.recipe.exclusive && active.size) {
							index++;
							continue;
						}
						const resources = await this.requireSession().tryAcquireResources(
							physical.expansion.recipe.resources,
							this.requireEnvironment().env,
						);
						if (!resources) {
							index++;
							continue;
						}
						if (this.halted || this.cancelled()) {
							await resources.release();
							this.halted = true;
							break;
						}
						queue.splice(index, 1);
						admitted = true;
						if (physical.expansion.recipe.exclusive) exclusive = true;
						const work = this.executePhysical(physical, resources)
							.catch((error) => {
								const detail = message(error),
									prior = physical.work.reason;
								physical.work.reason =
									prior && physical.work.state !== "MISSING" && !detail.includes(prior)
										? `${prior}; ${detail}`
										: detail;
								this.fail(error);
							})
							.finally(() => {
								active.delete(work);
								if (physical.expansion.recipe.exclusive) exclusive = false;
							});
						active.add(work);
						if (exclusive || this.halted || this.observationBarrier) break;
					}
				if (active.size) await Promise.race(active);
				else if (queue.length && !this.halted && !admitted)
					await new Promise<void>((resolve) => setTimeout(resolve, 50));
				else if (this.halted) break;
			}
		} catch (error) {
			this.fail(error);
		} finally {
			await Promise.all(active);
		}
		for (const physical of queue)
			physical.work.reason = this.cancelled() ? "cancelled-before-dispatch" : "halted-before-dispatch";
	}

	private async executePhysical(physical: Physical, resources: NativeLock): Promise<void> {
		const descriptor = physical.descriptor!,
			key = physical.work.execution_key!,
			recipe = descriptor.recipe;
		const session = this.requireSession(),
			store = this.requireStore();
		let keyLock: NativeLock | null = null,
			resourceHeld = true,
			resourceReleaseAttempted = false,
			operationFailure: OperationFailure | null = null,
			pending: PendingResult | null = null,
			barrier = false;
		try {
			keyLock = await session.acquireKey(key, this.signal);
			if (this.halted || this.cancelled()) {
				physical.work.reason = this.cancelled() ? "cancelled-before-dispatch" : "halted-before-dispatch";
				return;
			}
			await this.stableInput();
			const toolsBefore = await this.requireTools().revalidate(recipe.toolchain);
			if (
				!equal(descriptor.toolchain, toolsBefore) ||
				!equal(descriptor.build_cache, await this.requireTools().buildCache(recipe))
			)
				throw new Error("execution toolchain or cache selection changed before dispatch");
			this.environmentAfter();
			physical.candidates = await this.checkpoint.run(() =>
				store.selectCandidates(descriptor, physical.expansion.members),
			);
			const selected = physical.candidates.filter((candidate) => this.selectedSet.has(candidate.member.claim_id));
			if (this.call.resume !== false && selected.every((candidate) => candidate.candidate !== null)) {
				physical.work.cache = "hit";
				physical.work.state = "PASS";
				physical.work.reason = null;
				physical.work.execution = selected.reduce((a, b) => (a.candidate!.sequence > b.candidate!.sequence ? a : b))
					.candidate!.execution;
				resourceReleaseAttempted = true;
				await resources.release();
				resourceHeld = false;
				this.observationBarrier++;
				barrier = true;
				for (const selection of selected)
					await this.observe(
						physical.expansion.slots.find(
							(slot) => slot.claim_id === selection.member.claim_id && slot.slot_id === selection.member.slot_id,
						)!,
						selection.candidate!.execution,
						selection.candidate!.artifact,
					);
				return;
			}
			physical.work.cache = "miss";
			const before = await this.stableInput();
			if (this.halted || this.cancelled()) {
				physical.work.reason = this.cancelled() ? "cancelled-before-dispatch" : "halted-before-dispatch";
				return;
			}
			const attempt = randomUUID();
			pending = {
				kind: "execution",
				execution_key: key,
				attempt_id: attempt,
				members: descriptor.members,
				claim_id: null,
				slot_id: null,
			};
			await session.beginPending(pending);
			let actual: NativeResult;
			try {
				actual = await session.run({
					command: recipe.command,
					cwd: await safeDirectoryPath(this.root, recipe.cwd),
					environment: this.requireEnvironment().env,
					timeoutSeconds: recipe.timeout_seconds,
					signal: this.signal,
					executionKey: key,
					attemptId: attempt,
					ownershipProtocol: recipe.ownership_protocol,
				});
			} catch (error) {
				this.fail(error);
				physical.work.state = this.cancellationCause(error) ? "CANCELLED" : "ERROR";
				physical.work.reason = message(error);
				await this.checkpoint.run(() =>
					store.appendHistory({
						schema_version: "fv-evidence-history/v1",
						kind: "execution",
						execution_key: key,
						attempt_id: attempt,
						members: descriptor.members,
						execution: null,
						claim_id: null,
						slot_id: null,
						observation: null,
						indeterminate_owner: null,
						result: physical.work.state as Result,
					}),
				);
				if (session.owner.spawn_windows.every((window) => window.state === "closed")) {
					await session.clearPending(pending);
					pending = null;
				}
				return;
			}
			this.observationBarrier++;
			barrier = true;
			let result: Result =
				actual.error || !closed(actual)
					? "ERROR"
					: actual.termination.cancelled
						? "CANCELLED"
						: !normal(actual)
							? "ERROR"
							: actual.termination.exit_code !== 0
								? "FAIL"
								: "PASS";
			let reason: string | null = actual.error ?? (result === "PASS" ? null : `execution ${result.toLowerCase()}`);
			let marker = false;
			const raw = reconstructRawOutput(actual.stdout, actual.stderr, actual.termination, result);
			try {
				for (const bytes of [actual.stdout, actual.stderr])
					if (
						decodeUTF8(bytes)
							.split(LINE_BREAKS)
							.some((line) => RESERVED_TRAILER.test(line))
					)
						throw new Error("command emitted a reserved evidence trailer");
				marker = markerMatches(raw, recipe);
				if (result === "PASS" && !marker) {
					result = "FAIL";
					reason = "required pass marker was absent";
				}
			} catch (error) {
				result = "ERROR";
				reason = message(error);
				marker = false;
			}
			if (result !== "PASS") this.halted = true;
			if (result === "ERROR") this.fail(reason ?? "execution error");
			let after: InputState | null = null,
				toolchainAfter: ExecutionArtifact["toolchain_after"] = null,
				environmentAfter: ExecutionArtifact["environment_after"] = null,
				buildCacheAfter: BuildCacheIdentity = null;
			if (!this.cancelled()) {
				try {
					toolchainAfter = await this.requireTools().revalidate(recipe.toolchain);
					environmentAfter = this.environmentAfter();
					buildCacheAfter = await this.requireTools().buildCache(recipe);
					if (!equal(toolchainAfter, descriptor.toolchain) || !equal(buildCacheAfter, descriptor.build_cache))
						throw new Error("execution toolchain or cache selection moved");
					after = await this.stableInput();
				} catch (error) {
					if (this.cancellationCause(error)) {
						after = null;
						toolchainAfter = null;
						environmentAfter = null;
						buildCacheAfter = null;
						if (result === "PASS") {
							result = "CANCELLED";
							reason = "execution completion metadata cancelled";
						}
					} else {
						this.fail(error);
						if (result !== "FAIL") result = "ERROR";
						reason = reason === null ? message(error) : `${reason}; completion metadata: ${message(error)}`;
					}
				}
			} else if (result === "PASS") {
				result = "CANCELLED";
				reason = "invocation cancelled before execution completion metadata";
			}
			const files = new Map<string, Uint8Array>([
				["stdout.bin", actual.stdout],
				["stderr.bin", actual.stderr],
				["raw.log", raw],
			]);
			try {
				for (const [name, bytes] of await retainCollectorAttachments(this.root, recipe, actual.stdout))
					files.set(name, bytes);
			} catch (error) {
				if (result === "PASS") {
					result = "ERROR";
					reason = message(error);
					this.fail(error);
				}
			}
			const directory = `${BASE}/executions/${key.slice(7)}/${attempt}`;
			const ownership = { ...actual.ownership };
			if (ownership.protocol_log) {
				const bytes = await store.readFileRef(ownership.protocol_log);
				files.set("attachments/ownership-protocol.log", bytes);
				ownership.protocol_log = fileRef(`${directory}/attachments/ownership-protocol.log`, bytes);
			}
			const unsigned: Omit<ExecutionArtifact, "artifact_id"> = {
				schema_version: "fv-execution-artifact/v1",
				execution_key: key,
				attempt_id: attempt,
				producer: this.producer,
				descriptor,
				started_at: actual.startedAt,
				finished_at: actual.finishedAt,
				source_before: before,
				source_after: after,
				toolchain_after: toolchainAfter,
				environment_after: environmentAfter,
				stdout: fileRef(`${directory}/stdout.bin`, actual.stdout),
				stderr: fileRef(`${directory}/stderr.bin`, actual.stderr),
				raw_output: fileRef(`${directory}/raw.log`, files.get("raw.log")!),
				attachments: [...files.entries()]
					.filter(([name]) => name.startsWith("attachments/"))
					.map(([name, bytes]) => fileRef(`${directory}/${name}`, bytes))
					.sort((a, b) => utf8Compare(a.path, b.path)),
				ownership,
				build_cache_after: buildCacheAfter,
				termination: actual.termination,
				marker_matched: marker,
				result,
				reason,
			};
			if (result !== "PASS") {
				physical.work.state = result;
				physical.work.reason = reason;
				for (const slot of physical.expansion.slots)
					Object.assign(this.assessments.get(slotKey(slot.claim_id, slot.slot_id))!, { state: result, reason });
			}
			const reference = await this.checkpoint.run(async () => {
				const reference = await store.publishExecution(unsigned, files);
				await store.appendHistory({
					schema_version: "fv-evidence-history/v1",
					kind: "execution",
					execution_key: key,
					attempt_id: attempt,
					members: descriptor.members,
					execution: reference,
					claim_id: null,
					slot_id: null,
					observation: null,
					indeterminate_owner: null,
					result,
				});
				if (closed(actual)) {
					await session.clearPending(pending!);
					pending = null;
				}
				return reference;
			});
			physical.work.execution = reference;
			physical.work.state = result;
			physical.work.reason = reason;
			for (const slot of physical.expansion.slots)
				Object.assign(this.assessments.get(slotKey(slot.claim_id, slot.slot_id))!, {
					execution: reference,
					state: result === "PASS" ? "MISSING" : result,
					reason: result === "PASS" ? "awaiting-member-observation" : reason,
				});
			if (closed(actual)) {
				resourceReleaseAttempted = true;
				await resources.release();
				resourceHeld = false;
			}
			if (result === "PASS") {
				const artifact = await this.checkpoint.run(() => store.readExecution(reference, descriptor));
				for (const slot of physical.expansion.slots) await this.observe(slot, reference, artifact);
			}
		} catch (error) {
			operationFailure = { error };
			this.fail(error);
			throw error;
		} finally {
			if (barrier) this.observationBarrier--;
			if (pending === null) {
				const failure =
					operationFailure ??
					(physical.work.state === "FAIL" || physical.work.state === "ERROR" || physical.work.state === "CANCELLED"
						? { error: new Error(physical.work.reason ?? `execution ${physical.work.state}`) }
						: null);
				if (resourceHeld && !resourceReleaseAttempted) await releaseNativeLock(resources, failure);
				if (keyLock && (!resourceHeld || !resourceReleaseAttempted)) await releaseNativeLock(keyLock, failure);
			}
		}
	}

	private async observe(slot: ExpandedSlot, execution: ExecutionRef, artifact: ExecutionArtifact): Promise<void> {
		const store = this.requireStore(),
			session = this.requireSession(),
			checker = this.loaded.policy.claim_checker;
		const assessment = this.assessments.get(slotKey(slot.claim_id, slot.slot_id))!;
		assessment.execution = execution;
		const requestId = randomUUID(),
			directory = `${BASE}/runs/${this.runId}/observations/${slot.claim_id}/${requestId}`;
		let resources: NativeLock | null = null,
			operationFailure: OperationFailure | null = null,
			pending: PendingResult | null = null;
		try {
			resources = await session.acquireResources(checker.resources, this.requireEnvironment().env, this.signal);
			const tools = await this.requireTools().revalidate(checker.toolchain);
			this.environmentAfter();
			const before = await this.stableInput();
			const request = validateObservationRequest({
				schema_version: "fv-claim-observation-request/v1",
				request_id: requestId,
				policy_path: this.loaded.path,
				policy_hash: this.loaded.hash,
				common: this.loaded.common,
				claim_id: slot.claim_id,
				created_at: now(),
				slots: [
					{
						slot_id: slot.slot_id,
						tool: slot.tool,
						recipe_id: slot.recipe_id,
						execution,
						observation_binding: assessment.observation_binding,
					},
				],
			});
			const requestRef = await store.writeImmutableJSON(`${directory}/request.json`, request);
			const requestBytes = await store.readFileRef(requestRef);
			const responsePath = `${directory}/response.json`;
			try {
				await fs.lstat(path.join(this.root, responsePath));
				throw new Error("observation response already exists");
			} catch (error) {
				if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
			}
			pending = {
				kind: "observation",
				execution_key: execution.execution_key,
				attempt_id: artifact.attempt_id,
				members: artifact.descriptor.members,
				claim_id: slot.claim_id,
				slot_id: slot.slot_id,
			};
			await session.beginPending(pending);
			const actual = await session.run({
				command: [
					...checker.command,
					"--request",
					path.join(this.root, requestRef.path),
					"--response",
					path.join(this.root, responsePath),
				],
				cwd: await safeDirectoryPath(this.root, checker.cwd),
				environment: this.requireEnvironment().env,
				timeoutSeconds: checker.timeout_seconds,
				signal: this.signal,
				executionKey: execution.execution_key,
				attemptId: artifact.attempt_id,
			});
			let result: Result =
					actual.error || !closed(actual) ? "ERROR" : actual.termination.cancelled ? "CANCELLED" : "ERROR",
				reason: string | null = actual.error;
			let responseRef: FileRef | null = null,
				after: InputState | null = null,
				responseBytes: Buffer | null = null;
			try {
				responseBytes = await readContainedBytes(this.root, responsePath);
			} catch (error) {
				if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
			}
			if (responseBytes !== null) {
				await store.fsyncTree(directory);
				responseRef = fileRef(responsePath, responseBytes);
			}
			let metadataStarted = false,
				responseOutcome: Result | null = null;
			try {
				const contents = await fs.readdir(path.join(this.root, directory));
				if (contents.some((name) => name !== "request.json" && name !== "response.json"))
					throw new Error("checker left extra response or temporary files");
				if (!(await store.readFileRef(requestRef)).equals(requestBytes))
					throw new Error("checker replaced observation request bytes");
				decodeUTF8(actual.stdout);
				decodeUTF8(actual.stderr);
				if (actual.error || !closed(actual))
					throw new Error(actual.error ?? "observation ownership remains unresolved");
				if (actual.termination.cancelled) {
					result = "CANCELLED";
					reason = "observation checker cancelled";
				} else {
					const completed = normal(actual) && actual.termination.exit_code === 0;
					if (completed && responseBytes === null) throw new Error("observation response is missing");
					const response = completed ? validateObservationResponse(parseJSON(responseBytes!)) : null;
					if (response) {
						if (
							response.request_id !== requestId ||
							response.request_hash !== requestRef.hash ||
							response.claim_id !== slot.claim_id ||
							!equal(
								response.slots.map((member) => member.slot_id),
								request.slots.map((member) => member.slot_id),
							)
						)
							throw new Error("observation response does not bind exact request slots");
						if (
							!(
								request.created_at <= actual.startedAt &&
								actual.startedAt <= response.started_at &&
								response.started_at <= response.finished_at &&
								response.finished_at <= actual.finishedAt
							)
						)
							throw new Error("observation response interval lies outside actual checker invocation");
						responseOutcome = response.slots[0]!.result;
					}
					if (this.cancelled()) {
						if (!response) throw new Error("observation checker did not exit normally with zero");
						result = responseOutcome === "ERROR" ? "ERROR" : "CANCELLED";
						reason =
							result === "ERROR"
								? response.slots[0]!.reason
								: "invocation cancelled before observation completion metadata";
					} else {
						metadataStarted = true;
						const afterTools = await this.requireTools().revalidate(checker.toolchain);
						this.environmentAfter();
						if (!equal(tools, afterTools)) throw new Error("observation checker toolchain moved");
						after = await this.stableInput();
						if (!response) throw new Error("observation checker did not exit normally with zero");
						result = response.slots[0]!.result;
						reason = response.slots[0]!.reason;
					}
				}
			} catch (error) {
				if (metadataStarted && this.cancellationCause(error) && normal(actual) && actual.termination.exit_code === 0) {
					after = null;
					result = responseOutcome === "ERROR" ? "ERROR" : "CANCELLED";
					reason =
						responseOutcome === "ERROR"
							? "observation checker reported ERROR"
							: "observation completion metadata cancelled";
				} else {
					result = "ERROR";
					reason = reason === null ? message(error) : `${reason}; observation completion: ${message(error)}`;
				}
			}
			if (result !== "PASS") this.halted = true;
			if (result === "ERROR") this.fail(reason ?? "observation error");
			const stdout = await store.writeImmutableFile(`${directory}/stdout.bin`, actual.stdout),
				stderr = await store.writeImmutableFile(`${directory}/stderr.bin`, actual.stderr);
			const receipt = validateObservationCheck({
				schema_version: "fv-observation-check/v1",
				request: requestRef,
				response: responseRef,
				started_at: actual.startedAt,
				finished_at: actual.finishedAt,
				termination: actual.termination,
				stdout,
				stderr,
				source_before: before,
				source_after: after,
				toolchain: tools,
				result,
				reason,
			});
			const checkRef = await this.checkpoint.run(async () => {
				const reference = await store.writeImmutableJSON(`${directory}/check.json`, receipt);
				await store.appendHistory({
					schema_version: "fv-evidence-history/v1",
					kind: "observation",
					execution_key: execution.execution_key,
					attempt_id: artifact.attempt_id,
					members: artifact.descriptor.members,
					execution,
					claim_id: slot.claim_id,
					slot_id: slot.slot_id,
					observation: reference,
					indeterminate_owner: null,
					result,
				});
				if (closed(actual)) {
					await session.clearPending(pending!);
					pending = null;
				}
				return reference;
			});
			Object.assign(assessment, { state: result, reason, observation: observationRef(checkRef, receipt) });
		} catch (error) {
			operationFailure = { error };
			assessment.state = this.cancellationCause(error) ? "CANCELLED" : "ERROR";
			assessment.reason = message(error);
			this.fail(error);
		} finally {
			if (resources && pending === null) {
				const failure =
					operationFailure ??
					(assessment.state === "FAIL" || assessment.state === "ERROR" || assessment.state === "CANCELLED"
						? { error: new Error(assessment.reason ?? `observation ${assessment.state}`) }
						: null);
				await releaseNativeLock(resources, failure);
			}
		}
	}

	private retainKnownBarriers(physical: Physical): void {
		for (const member of physical.expansion.members) {
			const events = this.history.events.filter((event) => barrierApplies(event, member));
			const assessment = this.assessments.get(slotKey(member.claim_id, member.slot_id))!;
			assessment.blocking_events = events.map((event) => this.history.view.events[event.sequence - 1]!);
			if (events.length) {
				assessment.state = events.some((event) => event.result === "FAIL") ? "FAIL" : "ERROR";
				assessment.reason = "retained-barrier-without-current-eligibility";
			}
		}
	}
	private async assessFullHistory(): Promise<void> {
		const store = this.requireStore();
		let corrupted = false;
		for (const physical of this.physical) {
			if (!physical.descriptor || corrupted) {
				this.retainKnownBarriers(physical);
				continue;
			}
			let selections: CandidateSelection[];
			try {
				selections = await this.checkpoint.run(() =>
					store.selectCandidates(physical.descriptor!, physical.expansion.members, this.history),
				);
			} catch (error) {
				corrupted = true;
				this.fail(error);
				this.retainKnownBarriers(physical);
				continue;
			}
			for (const selection of selections) {
				const assessment = this.assessments.get(slotKey(selection.member.claim_id, selection.member.slot_id))!;
				assessment.blocking_events = selection.blocking_events;
				if (selection.state === "FAIL" || selection.state === "ERROR") {
					assessment.state = selection.state;
					assessment.reason =
						selection.state === "FAIL" ? "unsuperseded-retained-failure" : "indeterminate-retained-ownership";
				} else if (selection.candidate && (assessment.state === "MISSING" || assessment.state === "PASS")) {
					try {
						const receipt = validateObservationCheck(
							parseJSON(await store.readFileRef(selection.candidate.observation)),
						);
						assessment.execution = selection.candidate.execution;
						assessment.state = "PASS";
						assessment.reason = null;
						assessment.observation = observationRef(selection.candidate.observation, receipt);
					} catch (error) {
						assessment.state = "ERROR";
						assessment.reason = message(error);
						corrupted = true;
						this.fail(error);
						this.retainKnownBarriers(physical);
						break;
					}
				}
			}
		}
	}

	private async publish(): Promise<RunResult> {
		const claims: Omit<ClaimRecord, "record_id">[] = this.loaded.policy.records.map((record) => {
			const executions = record.executions.map((slot) => this.assessments.get(slotKey(record.claim_id, slot.slot_id))!);
			return {
				schema_version: "fv-evidence-run/v4",
				run_id: this.runId,
				claim_id: record.claim_id,
				required: record.required,
				evidence_class: record.evidence_class,
				scope: record.scope,
				common: this.loaded.common,
				executions,
				result: executions.some((slot) => slot.state === "FAIL")
					? "FAIL"
					: executions.every((slot) => slot.state === "PASS")
						? "PASS"
						: "INCOMPLETE",
				waiver: null,
			};
		});
		const byClaim = new Map(claims.map((claim) => [claim.claim_id, claim]));
		for (let remaining = claims.length; remaining > 0; remaining--) {
			let changed = false;
			for (const claim of claims)
				if (
					claim.result === "PASS" &&
					(this.loaded.dependencies[claim.claim_id] ?? []).some(
						(dependency) => byClaim.get(dependency)?.result !== "PASS",
					)
				) {
					claim.result = "INCOMPLETE";
					changed = true;
				}
			if (!changed) break;
		}
		const required = claims.filter((claim) => claim.required);
		let result: RunManifest["result"] = required.some((claim) => claim.result === "FAIL")
			? "FAIL"
			: this.operationalError || this.preflight.result === "ERROR"
				? "ERROR"
				: this.cancelled() || this.preflight.result === "CANCELLED"
					? "CANCELLED"
					: required.some((claim) => claim.result !== "PASS") || !this.baseline || !this.finalSource
						? "INCOMPLETE"
						: "PASS";
		let reason =
			result === "PASS"
				? null
				: (this.operationalError ??
					(result === "FAIL"
						? "required claim has a retained failure"
						: result === "CANCELLED"
							? "invocation cancelled"
							: "required work is incomplete"));
		let manifest: RunManifest | null = null,
			run: FileRef | null = null;
		const publication: RunResult["publication"] = { state: "not-attempted", candidate: null };
		if (!this.store)
			return validateRunResult({
				schema_version: "fv-evidence-run-result/v1",
				result,
				run,
				manifest,
				publication,
				reason,
			});
		try {
			const store = this.requireStore(),
				refs: RunManifest["claims"] = [];
			for (const claim of claims) refs.push({ claim_id: claim.claim_id, record: await store.publishClaim(claim) });
			manifest = {
				schema_version: "fv-evidence-batch/v1",
				run_id: this.runId,
				policy_path: this.loaded.path,
				policy_hash: this.loaded.hash,
				common: this.loaded.common,
				producer: this.producer,
				trust_assumptions: this.loaded.policy.trust_assumptions,
				history: this.history.view,
				started_at: this.startedAt,
				finished_at: now(),
				jobs: this.jobs,
				selected_records: this.selected,
				required_records: required.map((claim) => claim.claim_id),
				source_before: this.baseline,
				source_after: this.finalSource,
				preflight: this.preflight,
				work: this.physical.map((physical) => physical.work),
				claims: refs,
				result,
				reason,
			};
			run = await store.publishRun(manifest);
			Object.assign(publication, await store.publishCurrent(run));
			if (publication.state !== "durable") {
				result = "ERROR";
				this.fail(`current pointer ${publication.state}`);
				reason = this.operationalError;
			}
		} catch (error) {
			result = "ERROR";
			this.fail(error);
			reason = this.operationalError ?? message(error);
		}
		return validateRunResult({
			schema_version: "fv-evidence-run-result/v1",
			result,
			run,
			manifest,
			publication,
			reason,
		});
	}
	private async finishSession(): Promise<void> {
		if (!this.session) return;
		try {
			await this.session.drain();
			await this.session.release();
		} catch (error) {
			this.fail(error);
		}
	}
}
