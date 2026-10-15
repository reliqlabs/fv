import { appendFileSync, existsSync, lstatSync, mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { isDeepStrictEqual } from "node:util";
import { createInterface } from "node:readline";
import {
	C,
	D,
	H,
	parseJSON,
	validateExecutionArtifact,
	validateObservationRequest,
	validatePackageIdentity,
	validatePolicyStructure,
	validateToolIdentity,
	validateV4Call,
} from "../tools/evidence-v4/evidence-v4-model";
import type { ExecutionRef, FileRef } from "../tools/evidence-v4/evidence-v4-model";
import type { Subprocess } from "bun";

type ToolRoot = { label: string; path: string };

async function runProgram() {
	type Controls = {
		child_gate?: string;
		child_delay_ms?: number;
		spawn_child?: boolean;
		await_child?: boolean;
		wait_for_gate?: string;
		delay_ms?: number;
		invalid_utf8?: boolean;
		reserved_trailer?: boolean;
		emit_witness?: boolean;
		marker_only?: boolean;
		stderr?: string;
		exit_code?: number;
		outcomes?: Controls[];
	};
	function parseControls(value: unknown): Controls {
		if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("invalid controls");
		const result: Controls = {};
		for (const [name, item] of Object.entries(value)) {
			if (["child_gate", "wait_for_gate", "stderr"].includes(name)) {
				if (typeof item !== "string") throw new Error("invalid string control");
				Object.assign(result, { [name]: item });
			} else if (["child_delay_ms", "delay_ms", "exit_code"].includes(name)) {
				if (typeof item !== "number" || !Number.isSafeInteger(item)) throw new Error("invalid integer control");
				Object.assign(result, { [name]: item });
			} else if (
				["spawn_child", "await_child", "invalid_utf8", "reserved_trailer", "emit_witness", "marker_only"].includes(name)
			) {
				if (typeof item !== "boolean") throw new Error("invalid boolean control");
				Object.assign(result, { [name]: item });
			} else if (name === "outcomes") {
				if (!Array.isArray(item)) throw new Error("invalid outcomes");
				result.outcomes = item.map(parseControls);
			} else if (name !== "observation_fail") throw new Error("unknown control " + name);
		}
		return result;
	}

	const root = process.cwd();
	const controlRoot = join(root, ".fv/evidence/fixture-control");
	const recipe = process.argv[3];
	mkdirSync(controlRoot, { recursive: true });
	const hash = (bytes: Uint8Array | string) => "sha256:" + new Bun.CryptoHasher("sha256").update(bytes).digest("hex");
	const event = (name: string, extra: Record<string, unknown> = {}) =>
		appendFileSync(
			join(controlRoot, "events.jsonl"),
			JSON.stringify({ event: name, recipe_id: recipe, pid: process.pid, ...extra }) + "\n",
		);
	const waitGate = async (gate: string) => {
		while (!existsSync(join(controlRoot, "gates", gate))) await Bun.sleep(10);
	};
	const controls = existsSync(join(controlRoot, recipe + ".json"))
		? parseControls(JSON.parse(readFileSync(join(controlRoot, recipe + ".json"), "utf8")))
		: {};
	if (process.argv[4] === "--child") {
		event("child-started");
		if (controls.child_gate) await waitGate(controls.child_gate);
		if (controls.child_delay_ms) await Bun.sleep(controls.child_delay_ms);
		event("child-finished");
		process.exit(0);
	}
	const counter = join(controlRoot, recipe + ".count");
	const count = existsSync(counter) ? Number(readFileSync(counter, "utf8")) + 1 : 1;
	writeFileSync(counter, String(count));
	const selected = { ...controls, ...(controls.outcomes?.[count - 1] ?? {}) };
	event("started", { invocation: count });
	let child: Subprocess | undefined;
	if (selected.spawn_child) {
		child = Bun.spawn([process.execPath, "fixture/fixture.ts", "program", recipe, "--child"], {
			cwd: root,
			env: process.env,
			stdout: "ignore",
			stderr: "ignore",
		});
		event("child-created", { child_pid: child.pid });
	}
	if (selected.wait_for_gate) await waitGate(selected.wait_for_gate);
	if (selected.delay_ms) await Bun.sleep(selected.delay_ms);
	if (child && selected.await_child !== false) await child.exited;
	const witness = {
		recipe_id: recipe,
		source_hash: hash(readFileSync(join(root, "src/value.txt"))),
		public_env_hash: process.env.FV_FIXTURE_PUBLIC === undefined ? null : hash(process.env.FV_FIXTURE_PUBLIC),
		unlisted_present: process.env.FV_FIXTURE_UNLISTED !== undefined,
		transport_present: process.env.BUN_BE_BUN !== undefined,
		witness_count: 1,
		status: "observed",
	};
	const outputWitness = process.argv.includes("--randomized")
		? { ...witness, nonce: Buffer.from(crypto.getRandomValues(new Uint8Array(16))).toString("hex") }
		: witness;
	if (selected.invalid_utf8) process.stdout.write(Buffer.from([0xff]));
	if (selected.reserved_trailer) process.stdout.write("--- fv-evidence: exit=0 ---\n");
	if (selected.emit_witness !== false) {
		if (!selected.marker_only) process.stdout.write("FIXTURE_WITNESS " + JSON.stringify(outputWitness) + "\n");
		process.stdout.write("test result: ok.\n");
	}
	if (selected.stderr) process.stderr.write(String(selected.stderr));
	event("finished", { invocation: count, exit_code: selected.exit_code ?? 0 });
	process.exit(selected.exit_code ?? 0);
}

async function runChecker() {
	function object(value: unknown): Record<string, unknown> {
		if (value === null || typeof value !== "object" || Array.isArray(value)) throw new Error("expected object");
		return value as Record<string, unknown>;
	}
	const root = process.cwd();
	const policy = validatePolicyStructure(parseJSON(readFileSync(join(root, ".fv/execution-policy.json"))));
	const contract = object(parseJSON(readFileSync(join(root, ".fv/fixture-contract.json"))));
	const canonical = object(parseJSON(readFileSync(join(root, ".fv/obligations.json"))));
	const claims = ["invariants", "witnesses", "system_claims"].flatMap((kind) => {
		const collection = canonical[kind] ?? [];
		if (!Array.isArray(collection)) throw new Error("invalid canonical collection");
		return collection.map((entry: unknown) => {
			const claim = object(entry);
			if (typeof claim.id !== "string" || (claim.required !== undefined && typeof claim.required !== "boolean"))
				throw new Error("invalid canonical claim");
			const tools = claim.required_evidence ?? [];
			if (!Array.isArray(tools) || !tools.every((tool: unknown) => typeof tool === "string"))
				throw new Error("invalid canonical tools");
			return { id: claim.id, required: claim.required ?? true, tools };
		});
	});
	if (
		policy.records.length !== claims.length ||
		new Set(policy.records.map((record) => record.claim_id)).size !== claims.length
	)
		throw new Error("canonical activation coverage differs");
	if (!isDeepStrictEqual(policy.recipes, contract.recipes)) throw new Error("incorporated recipes differ");
	const observations: Record<
		string,
		Record<string, { recipe_id: string; tool: string; kind: string; witness_count: number }>
	> = {};
	for (const record of policy.records) {
		const claim = claims.find((entry) => entry.id === record.claim_id);
		if (!claim || record.required !== claim.required) throw new Error("canonical claim mismatch");
		const tools = record.executions.map((slot) => slot.tool);
		if (claim.tools.some((tool) => !tools.includes(tool))) throw new Error("canonical tool coverage missing");
		observations[record.claim_id] = {};
		for (const slot of record.executions) {
			observations[record.claim_id][slot.slot_id] = {
				recipe_id: slot.recipe_id,
				tool: slot.tool,
				kind: "source-witness",
				witness_count: 1,
			};
			if (
				slot.observation_binding.path !== ".fv/fixture-contract.json" ||
				slot.observation_binding.pointer !== `/observations/${record.claim_id}/${slot.slot_id}`
			)
				throw new Error("wrong observation pointer");
		}
	}
	if (!isDeepStrictEqual(contract.observations, observations)) throw new Error("unsupported observation contract");
	for (const recipe of policy.recipes) {
		if (
			!isDeepStrictEqual(recipe.source_closure, {
				mode: "prefixes",
				prefixes: ["fixture/", "src/", "tools/"],
				basis: [".fv/fixture-contract.json"],
			})
		)
			throw new Error("fixture dependency closure differs");
		if (recipe.bounds.samples !== null || recipe.bounds.max_steps !== null || recipe.bounds.seed !== null)
			throw new Error("fixture source witness has no sampler bounds");
	}
	if (process.argv.includes("--preflight")) {
		process.stdout.write("FIXTURE_PREFLIGHT: READY\n");
		process.exit(0);
	}
	const argument = (name: string) => {
		const index = process.argv.indexOf(name);
		if (index < 0 || !process.argv[index + 1]) throw new Error("missing " + name);
		return resolve(process.argv[index + 1]);
	};
	const requestPath = argument("--request");
	const responsePath = argument("--response");
	if (dirname(requestPath) !== dirname(responsePath) || existsSync(responsePath))
		throw new Error("invalid response destination");
	const requestBytes = readFileSync(requestPath);
	const request = validateObservationRequest(parseJSON(requestBytes));
	const started = new Date().toISOString();
	if (!request.slots.length) throw new Error("empty observation request");
	const record = policy.records.find((entry) => entry.claim_id === request.claim_id);
	if (!record) throw new Error("unknown member");
	const fileBytes = (ref: FileRef | ExecutionRef) => {
		if (ref.path.startsWith("/") || ref.path.split("/").some((part) => !part || part === "." || part === ".."))
			throw new Error("unsafe artifact reference");
		const path = resolve(root, ref.path);
		if (relative(root, path).startsWith("..")) throw new Error("escaping reference");
		let cursor = root;
		for (const part of ref.path.split("/")) {
			cursor = join(cursor, part);
			if (lstatSync(cursor).isSymbolicLink()) throw new Error("linked reference");
		}
		const stat = lstatSync(path);
		const bytes = readFileSync(path);
		if (!stat.isFile() || stat.nlink !== 1 || H(bytes) !== ref.hash || ("size" in ref && bytes.length !== ref.size))
			throw new Error("corrupt artifact reference");
		return bytes;
	};
	const seen = new Set<string>();
	const slots = request.slots.map((slot) => {
		if (seen.has(slot.slot_id)) throw new Error("duplicate observation slot");
		seen.add(slot.slot_id);
		const expected = record.executions.find((entry) => entry.slot_id === slot.slot_id);
		if (
			!expected ||
			expected.tool !== slot.tool ||
			expected.recipe_id !== slot.recipe_id ||
			!isDeepStrictEqual(expected.observation_binding, slot.observation_binding)
		)
			throw new Error("wrong member association");
		const artifact = validateExecutionArtifact(parseJSON(fileBytes(slot.execution)));
		if (
			artifact.result !== "PASS" ||
			artifact.execution_key !== slot.execution.execution_key ||
			artifact.artifact_id !== slot.execution.artifact_id ||
			!isDeepStrictEqual(artifact.descriptor.common, request.common)
		)
			throw new Error("invalid completed execution");
		const recipe = policy.recipes.find((entry) => entry.recipe_id === slot.recipe_id);
		if (
			!isDeepStrictEqual(artifact.descriptor.recipe, recipe) ||
			!artifact.descriptor.members.some(
				(member) =>
					member.claim_id === request.claim_id && member.slot_id === slot.slot_id && member.tool === slot.tool,
			)
		)
			throw new Error("wrong physical recipe/member");
		const outputBytes = fileBytes(artifact.stdout);
		const output = new TextDecoder("utf-8", { fatal: true }).decode(outputBytes);
		const lines = output.split("\n").filter((line) => line.startsWith("FIXTURE_WITNESS "));
		const witness: unknown =
			lines.length === 1 ? parseJSON(Buffer.from(lines[0].slice("FIXTURE_WITNESS ".length))) : null;
		const source = artifact.descriptor.closure.files.find((file) => file.path === "src/value.txt");
		const environment = artifact.descriptor.environment.variables.find(
			(variable) => variable.name === "FV_FIXTURE_PUBLIC",
		);
		const expectedWitness = {
			recipe_id: slot.recipe_id,
			source_hash: source?.hash,
			public_env_hash: environment?.value_hash ?? null,
			unlisted_present: false,
			transport_present: false,
			witness_count: 1,
			status: "observed",
		};
		const randomized = recipe?.command.includes("--randomized");
		const nonce = randomized && witness !== null ? object(witness).nonce : undefined;
		const randomValid = !randomized || (typeof nonce === "string" && /^[0-9a-f]{32}$/.test(nonce));
		const completeExpected = randomized ? { ...expectedWitness, nonce } : expectedWitness;
		const controlPath = join(root, ".fv/evidence/fixture-control", slot.recipe_id + ".json");
		const controls = existsSync(controlPath) ? object(parseJSON(readFileSync(controlPath))) : {};
		const failures = controls.observation_fail;
		if (
			failures !== undefined &&
			(!Array.isArray(failures) || !failures.every((id: unknown) => typeof id === "string"))
		)
			throw new Error("invalid fault controls");
		const valid = Boolean(
			source &&
				randomValid &&
				isDeepStrictEqual(witness, completeExpected) &&
				!(Array.isArray(failures) && failures.includes(request.claim_id)),
		);
		appendFileSync(
			join(root, ".fv/evidence/fixture-control/events.jsonl"),
			JSON.stringify({
				event: "observation",
				recipe_id: slot.recipe_id,
				claim_id: request.claim_id,
				pid: process.pid,
				result: valid ? "PASS" : "FAIL",
			}) + "\n",
		);
		return {
			slot_id: slot.slot_id,
			result: valid ? "PASS" : "FAIL",
			reason: valid ? null : "required positive source witness absent or fault-injected",
			observations: { witness_count: valid ? 1 : 0, source_hash: source?.hash ?? null, stdout_hash: H(outputBytes) },
		};
	});
	const response = {
		schema_version: "fv-claim-observations/v1",
		request_id: request.request_id,
		request_hash: H(requestBytes),
		claim_id: request.claim_id,
		started_at: started,
		finished_at: new Date().toISOString(),
		slots,
	};
	const temporary = join(dirname(responsePath), "response.tmp");
	writeFileSync(temporary, JSON.stringify(response) + "\n", { flag: "wx" });
	renameSync(temporary, responsePath);
}

async function runDriver() {
	const [root, producerPath] = process.argv.slice(3);
	// The test driver accepts the runner module path at runtime.
	const { runEvidenceV4 } = await import(producerPath);
	const lines = createInterface({ input: process.stdin });
	const controller = new AbortController();
	let started = false;
	lines.on("line", async (line) => {
		if (started) {
			if (line === "abort") controller.abort();
			return;
		}
		started = true;
		try {
			const { call, signal_after_ms } = JSON.parse(line);
			const timer = signal_after_ms === undefined ? undefined : setTimeout(() => controller.abort(), signal_after_ms);
			try {
				const result = await runEvidenceV4({ cwd: root }, call, controller.signal);
				process.stdout.write(JSON.stringify(result) + "\n");
			} finally {
				clearTimeout(timer);
			}
		} catch (error) {
			process.stdout.write(JSON.stringify({ result: "ERROR", reason: String(error), rejected: true }) + "\n");
		} finally {
			lines.close();
			process.stdin.destroy();
		}
	});
}

async function runSchema() {
	// The schema harness accepts its tool-root implementation module at runtime.
	const { hashToolRoots } = await import(process.argv[3]);
	const requests: unknown = JSON.parse(await Bun.stdin.text());
	if (!Array.isArray(requests)) throw new Error("vector requests must be an array");
	const results = [];
	for (const input of requests) {
		try {
			if (!input || typeof input !== "object") throw new Error("invalid vector request");
			const request = input as Record<string, unknown>;
			if (request.op === "parse") {
				if (typeof request.hex !== "string") throw new Error("missing bytes");
				const value = parseJSON(Buffer.from(request.hex, "hex"));
				results.push({
					ok: true,
					canonical_hex: Buffer.from(C(value)).toString("hex"),
					hash: H(C(value)),
					domain: D("vector", value),
				});
			} else if (request.op === "canonical") {
				if (typeof request.label !== "string") throw new Error("missing label");
				results.push({
					ok: true,
					canonical_hex: Buffer.from(C(request.value)).toString("hex"),
					hash: H(C(request.value)),
					domain: D(request.label, request.value),
				});
			} else if (request.op === "validate") {
				const validators: Record<string, (value: unknown) => unknown> = {
					ToolIdentity: validateToolIdentity,
					PackageIdentity: validatePackageIdentity,
					V4Call: validateV4Call,
				};
				if (typeof request.shape !== "string" || !validators[request.shape])
					throw new Error("unsupported vector shape");
				const value = validators[request.shape](request.value);
				results.push({ ok: true, canonical_hex: Buffer.from(C(value)).toString("hex") });
			} else if (request.op === "roots") {
				if (!Array.isArray(request.roots)) throw new Error("missing roots");
				const roots: ToolRoot[] = request.roots.map((value: unknown) => {
					if (
						!value ||
						typeof value !== "object" ||
						!("label" in value) ||
						typeof value.label !== "string" ||
						!("path" in value) ||
						typeof value.path !== "string"
					)
						throw new Error("invalid root");
					return { label: value.label, path: value.path };
				});
				results.push({ ok: true, files: await hashToolRoots(roots) });
			} else throw new Error("unknown vector operation");
		} catch (error) {
			results.push({ ok: false, reason: String(error) });
		}
	}
	process.stdout.write(JSON.stringify(results) + "\n");
}

switch (process.argv[2]) {
	case "program":
		await runProgram();
		break;
	case "checker":
		await runChecker();
		break;
	case "driver":
		await runDriver();
		break;
	case "schema":
		await runSchema();
		break;
	case "--version":
		process.stdout.write(`fv-evidence-v4-fixture-host Bun ${Bun.version}\n`);
		break;
	default:
		throw new Error("expected test-only mode: program, checker, driver or schema");
}
