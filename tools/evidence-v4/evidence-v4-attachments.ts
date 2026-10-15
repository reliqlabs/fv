import * as fs from "node:fs/promises";
import { constants } from "node:fs";
import * as path from "node:path";
import { decodeUTF8, H, parseJSON, validPath, type Recipe } from "./evidence-v4-model";

const REPLAY_PREFIX = Buffer.from("REPLAY_LOCAL_EVIDENCE_REPORT ");

function collectorJSON(bytes: Uint8Array): Record<string, unknown> {
	const text = decodeUTF8(bytes);
	let out = "",
		at = 0;
	while (at < text.length) {
		if (text[at] === '"') {
			const start = at++;
			while (at < text.length) {
				const c = text[at++];
				if (c === "\\") at++;
				else if (c === '"') break;
			}
			out += text.slice(start, at);
		} else if (text[at] === "-" || /[0-9]/.test(text[at]!)) {
			const token = /^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?/.exec(text.slice(at))?.[0];
			if (!token) throw new Error("invalid collector JSON number");
			const number = Number(token);
			if (/[.eE]/.test(token) && !Number.isFinite(number)) throw new Error("nonfinite collector JSON number");
			out +=
				Number.isSafeInteger(number) && number >= 0 && !Object.is(number, -0) && !/[.eE]/.test(token)
					? token
					: JSON.stringify(`collector-number:${token}`);
			at += token.length;
		} else out += text[at++];
	}
	const value = parseJSON(Buffer.from(out));
	if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("collector report is not an object");
	return value as Record<string, unknown>;
}

export async function readContainedBytes(root: string, relative: string): Promise<Buffer> {
	if (!validPath(relative)) throw new Error(`unsafe retained path: ${relative}`);
	let current = root;
	const parts = relative.split("/");
	for (const [index, part] of parts.entries()) {
		current = path.join(current, part);
		const stat = await fs.lstat(current);
		if (stat.isSymbolicLink() || (index < parts.length - 1 && !stat.isDirectory()))
			throw new Error(`unsafe retained component: ${relative}`);
	}
	const handle = await fs.open(current, constants.O_RDONLY | constants.O_NOFOLLOW);
	try {
		const before = await handle.stat({ bigint: true });
		if (!before.isFile() || before.nlink !== 1n) throw new Error(`nonregular or aliased retained file: ${relative}`);
		const bytes = await handle.readFile();
		const after = await handle.stat({ bigint: true });
		const named = await fs.lstat(current, { bigint: true });
		if (
			before.dev !== after.dev ||
			before.ino !== after.ino ||
			before.size !== after.size ||
			before.mtimeNs !== after.mtimeNs ||
			before.ctimeNs !== after.ctimeNs ||
			named.dev !== after.dev ||
			named.ino !== after.ino ||
			named.nlink !== 1n ||
			named.isSymbolicLink() ||
			BigInt(bytes.length) !== after.size
		)
			throw new Error(`retained file moved during capture: ${relative}`);
		return bytes;
	} finally {
		await handle.close();
	}
}

export async function retainCollectorAttachments(
	root: string,
	recipe: Recipe,
	stdout: Uint8Array,
): Promise<Map<string, Uint8Array>> {
	const retained = new Map<string, Uint8Array>();
	if (recipe.attestation === null) return retained;
	const captured = Buffer.from(stdout.buffer, stdout.byteOffset, stdout.byteLength);
	const reports: { value: Record<string, unknown>; bytes: Buffer }[] = [];
	for (let offset = 0; offset < captured.length; ) {
		const newline = captured.indexOf(10, offset),
			end = newline < 0 ? captured.length : newline;
		const prefixed =
			end - offset >= REPLAY_PREFIX.length &&
			captured.compare(REPLAY_PREFIX, 0, REPLAY_PREFIX.length, offset, offset + REPLAY_PREFIX.length) === 0;
		if (prefixed || captured[offset] === 123) {
			const bytes = captured.subarray(offset + (prefixed ? REPLAY_PREFIX.length : 0), end);
			const value = collectorJSON(bytes);
			if (value.schema === "quint-witness-collector/v1" || value.schema === "dossier-replay-local-evidence-v2")
				reports.push({ value, bytes });
		}
		offset = end + 1;
	}
	if (reports.length !== 1)
		throw new Error("collector-transitive attestation requires exactly one supported original report");
	const { value: report, bytes } = reports[0]!;
	retained.set("attachments/collector-report.json", bytes);
	if (report.schema === "quint-witness-collector/v1") return retained;
	const bundle = report.bundle as Record<string, unknown> | undefined;
	if (
		!bundle ||
		typeof bundle.path !== "string" ||
		typeof bundle.sha256 !== "string" ||
		!/^[a-f0-9]{64}$/.test(bundle.sha256) ||
		!Number.isSafeInteger(bundle.size) ||
		(bundle.size as number) < 0
	)
		throw new Error("invalid original replay bundle identity");
	const directory = `.fv/evidence/artifacts/replay/sha256-${bundle.sha256}`;
	if (bundle.path !== `${directory}/manifest.json`)
		throw new Error("replay bundle path differs from original content address");
	const manifestBytes = await readContainedBytes(root, bundle.path);
	if (H(manifestBytes) !== `sha256:${bundle.sha256}` || manifestBytes.length !== bundle.size)
		throw new Error("replay bundle manifest identity mismatch");
	const manifest = collectorJSON(manifestBytes);
	if (
		manifest.schema !== "dossier-replay-retained-bundle-v2" ||
		!manifest.files ||
		typeof manifest.files !== "object" ||
		Array.isArray(manifest.files)
	)
		throw new Error("unsupported retained replay bundle");
	retained.set(`attachments/${bundle.path}`, manifestBytes);
	for (const item of Object.values(manifest.files as Record<string, unknown>)) {
		if (!item || typeof item !== "object" || Array.isArray(item)) throw new Error("invalid replay retained entry");
		const entry = item as Record<string, unknown>;
		if (
			typeof entry.sha256 !== "string" ||
			!/^[a-f0-9]{64}$/.test(entry.sha256) ||
			entry.artifact !== `sha256/${entry.sha256}` ||
			!Number.isSafeInteger(entry.size) ||
			(entry.size as number) < 0
		)
			throw new Error("invalid replay retained blob identity");
		const relative = `${directory}/${entry.artifact}`;
		const name = `attachments/${relative}`;
		if (retained.has(name)) continue;
		const blob = await readContainedBytes(root, relative);
		if (H(blob) !== `sha256:${entry.sha256}` || blob.length !== entry.size)
			throw new Error("replay retained blob identity mismatch");
		retained.set(name, blob);
	}
	return retained;
}
