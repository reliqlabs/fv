import * as fs from "node:fs/promises";
import * as path from "node:path";
import { fileURLToPath } from "node:url";
import { D, parseJSON, utf8Compare } from "./evidence-v4-model";
import type { ToolDiscovery } from "./evidence-v4-model";
import { canonicalToolPath, inside, packageRoots, probeJSON, probeText } from "./evidence-v4-toolchain-common";
import type {
	AdapterContext,
	AdapterResult,
	CacheNamespaceSelection,
	ProbeResult,
	ToolRoot,
} from "./evidence-v4-toolchain-common";

const LAKE_METADATA = fileURLToPath(new URL("./evidence-v4-lake-metadata.lean", import.meta.url));

async function exists(value: string): Promise<boolean> {
	try {
		await fs.access(value);
		return true;
	} catch (error) {
		if ((error as NodeJS.ErrnoException).code === "ENOENT") return false;
		throw error;
	}
}
async function regular(value: string, executable = false): Promise<string> {
	const real = await canonicalToolPath(value),
		stat = await fs.stat(real);
	if (!stat.isFile() || (executable && (stat.mode & 0o111) === 0))
		throw new Error(`Missing installed tool file: ${value}`);
	return real;
}
async function directory(value: string): Promise<string> {
	const real = await fs.realpath(value);
	if (!(await fs.stat(real)).isDirectory()) throw new Error(`Missing installed tool directory: ${value}`);
	return real;
}
async function inputPath(base: string, value: string, label: string): Promise<string> {
	const raw = path.isAbsolute(value) ? value : `${base}${path.sep}${value}`;
	let current = path.parse(raw).root;
	for (const component of raw.slice(current.length).split(path.sep)) {
		if (!component || component === ".") continue;
		current = component === ".." ? path.dirname(current) : path.join(current, component);
		if ((await fs.lstat(current)).isSymbolicLink()) throw new Error(`Symlink in ${label}: ${value}`);
	}
	return canonicalToolPath(current);
}
async function sameFile(left: string, right: string): Promise<boolean> {
	const [a, b] = await Promise.all([fs.stat(left), fs.stat(right)]);
	return a.dev === b.dev && a.ino === b.ino;
}
function object(value: unknown, name: string): Record<string, unknown> {
	if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error(`Invalid ${name} metadata`);
	return value as Record<string, unknown>;
}
function text(value: unknown, name: string): string {
	if (typeof value !== "string" || !value || value.includes("\0")) throw new Error(`Invalid ${name} metadata`);
	return value;
}
function strings(value: unknown, name: string): string[] {
	if (!Array.isArray(value) || value.some((v) => typeof v !== "string" || !v || v.includes("\0")))
		throw new Error(`Invalid ${name} metadata`);
	return value as string[];
}
function option(argv: readonly string[], name: string): string | undefined {
	let result: string | undefined;
	const camel = name.replace(/-([a-z])/gu, (_, c: string) => c.toUpperCase());
	for (let i = 0; i < argv.length; i++) {
		const key = argv[i].split("=", 1)[0];
		if (key !== `--${name}` && key !== `--${camel}`) continue;
		if (result !== undefined) throw new Error(`Ambiguous ${name} selection`);
		const equal = argv[i].indexOf("=");
		result = equal < 0 ? argv[++i] : argv[i].slice(equal + 1);
		if (!result || result.startsWith("--")) throw new Error(`Missing ${name} selection`);
	}
	return result;
}
function prefixResult(result: AdapterResult, prefix: string): AdapterResult {
	return { ...result, roots: result.roots.map((root) => ({ ...root, label: `${prefix}/${root.label}` })) };
}
function addResult(roots: ToolRoot[], discovery: ToolDiscovery[], result: AdapterResult): void {
	roots.push(...result.roots);
	discovery.push(...(result.discovery ?? []));
}
async function probe(
	context: AdapterContext,
	discovery: ToolDiscovery[],
	command: readonly string[],
	options?: { cwd?: string; env?: Record<string, string> },
): Promise<ProbeResult> {
	const result = await context.probe(command, options);
	discovery.push(result.identity);
	return result;
}
async function configurationRoot(roots: ToolRoot[], prefix: string, value: string): Promise<void> {
	roots.push({
		label: `${prefix}/configuration/${D("tool-configuration-path", value).slice(7)}`,
		path: await regular(value),
	});
}
async function bindLinkedRoots(roots: ToolRoot[], prefix: string): Promise<void> {
	const selected = roots.filter((root) => root.label === prefix || root.label.startsWith(prefix + "/"));
	const views: { root: ToolRoot; real: string; directory: boolean }[] = [];
	for (const root of selected) {
		const real = await canonicalToolPath(root.path);
		views.push({ root, real, directory: (await fs.stat(real)).isDirectory() });
	}
	const traversed = new Set<string>();
	for (let index = 0; index < views.length; index++) {
		const view = views[index];
		const walk = async (actual: string, relative: string): Promise<void> => {
			if (view.root.exclude?.some((ex) => relative === ex || relative.startsWith(ex.replace(/\/$/u, "") + "/"))) return;
			const stat = await fs.lstat(actual);
			if (stat.isSymbolicLink()) {
				const real = await canonicalToolPath(actual),
					target = await fs.stat(real);
				if (!target.isFile() && !target.isDirectory()) throw new Error("Unsupported JVM distribution link target");
				if (views.some((candidate) => (candidate.directory ? inside(candidate.real, real) : candidate.real === real)))
					return;
				const root = { label: `${prefix}/dependencies/${D("tool-linked-path", real).slice(7)}`, path: real };
				roots.push(root);
				views.push({ root, real, directory: target.isDirectory() });
				return;
			}
			if (!stat.isDirectory()) {
				if (!stat.isFile()) throw new Error("Unsupported JVM distribution entry");
				return;
			}
			const real = await fs.realpath(actual);
			if (traversed.has(real)) return;
			traversed.add(real);
			for (const name of (await fs.readdir(actual)).sort(utf8Compare))
				await walk(path.join(actual, name), relative ? `${relative}/${name}` : name);
		};
		await walk(view.real, "");
	}
}

async function quintPackage(entry: string): Promise<string> {
	for (let cursor = path.dirname(entry); ; cursor = path.dirname(cursor)) {
		const manifestPath = path.join(cursor, "package.json");
		if (await exists(manifestPath)) {
			const manifest = object(parseJSON(await fs.readFile(manifestPath)), "Quint package");
			if (manifest.name === "@informalsystems/quint") {
				const bins = object(manifest.bin, "Quint bins");
				if ((await regular(path.resolve(cursor, text(bins.quint, "Quint entry")))) !== entry)
					throw new Error("Quint launcher does not select its installed package entry");
				return cursor;
			}
		}
		const parent = path.dirname(cursor);
		if (parent === cursor) throw new Error("Cannot identify installed Quint distribution");
	}
}
async function scriptNode(context: AdapterContext, entry: string): Promise<{ invoked: string; realpath: string }> {
	const handle = await fs.open(entry, "r");
	let header: string;
	try {
		const data = Buffer.alloc(1024);
		const { bytesRead } = await handle.read(data, 0, data.length, 0);
		header = data.subarray(0, bytesRead).toString("utf8").split("\n", 1)[0];
	} finally {
		await handle.close();
	}
	if (!header.startsWith("#!")) throw new Error("Quint entry has no identifiable Node interpreter");
	const words = header.slice(2).trim().split(/\s+/u);
	if (path.basename(words[0]) === "env") {
		if (words.length !== 2 || words[1] !== "node") throw new Error("Unsupported Quint interpreter selector");
		return context.resolveCommand("node");
	}
	if (words.length !== 1 || path.basename(words[0]) !== "node")
		throw new Error("Unsupported Quint interpreter selector");
	return context.resolveCommand(words[0]);
}
function cliDefault(source: string, command: string, flag: string): string {
	const section = source.match(
		new RegExp(`const ${command}Cmd = \\{([\\s\\S]*?)(?=\\nconst [A-Za-z]+Cmd =|\\nfunction |$)`),
	)?.[1];
	const value = section
		?.match(new RegExp(`\\.option\\(['"]${flag}['"],\\s*\\{([\\s\\S]*?)\\n\\s*\\}\\)`))?.[1]
		.match(/\bdefault:\s*['"]([^'"]+)['"]/u)?.[1];
	if (!value) throw new Error(`Cannot discover installed Quint ${command} ${flag} default`);
	return value;
}

export type ApalacheJarEntrypoint = { mainClass: string; bootstrapEntry: string | null };

const APALACHE_TOOL_MAIN = "at.forsyte.apalache.tla.Tool";
const APALACHE_TOOL_ENTRY = "at/forsyte/apalache/tla/Tool.class";
const APALACHE_BOOTSTRAP_MAIN = "fv.compat.ApalacheJsonLimits";
const APALACHE_BOOTSTRAP_ENTRY = "fv/compat/ApalacheJsonLimits.class";
const APALACHE_BOOTSTRAP_HASH = "sha256:61601b896f7e5d42937f1f029cc27722b2a142940781d451e4b1b393052508ec";
const APALACHE_MANIFEST_ATTRIBUTES: Record<string, true> = {
	"manifest-version": true,
	"main-class": true,
	"specification-title": true,
	"specification-version": true,
	"specification-vendor": true,
	"implementation-title": true,
	"implementation-version": true,
	"implementation-vendor": true,
	"implementation-vendor-id": true,
	"implementation-url": true,
	"created-by": true,
	"build-jdk": true,
	"build-jdk-spec": true,
	"automatic-module-name": true,
	"enable-native-access": true,
};

export function parseApalacheJarManifest(entries: readonly string[], manifest: string): ApalacheJarEntrypoint {
	let manifests = 0,
		toolClasses = 0,
		bootstrapClasses = 0;
	for (const entry of entries) {
		const upper = entry.toUpperCase();
		if (upper === "META-INF/MANIFEST.MF") {
			if (entry !== "META-INF/MANIFEST.MF") throw new Error("Ambiguous Apalache JAR manifest entry");
			manifests++;
		}
		if (upper === "META-INF/INDEX.LIST") throw new Error("Unsupported Apalache JAR index delegation");
		if (entry === APALACHE_TOOL_ENTRY) toolClasses++;
		if (entry === APALACHE_BOOTSTRAP_ENTRY) bootstrapClasses++;
	}
	if (manifests !== 1) throw new Error("Missing or ambiguous Apalache JAR manifest entry");
	if (manifest.includes("\0") || !/[\r\n]$/u.test(manifest)) throw new Error("Malformed Apalache JAR manifest");
	const attributes = new Map<string, string>();
	let previous: string | null = null,
		ended = false;
	for (const line of manifest.split(/\r\n|\r|\n/u)) {
		if (!line) {
			ended = true;
			previous = null;
			continue;
		}
		if (ended) throw new Error("Unsupported Apalache JAR named manifest sections");
		if (line.startsWith(" ")) {
			if (previous === null) throw new Error("Malformed Apalache JAR manifest continuation");
			attributes.set(previous, attributes.get(previous)! + line.slice(1));
			continue;
		}
		const header = /^([A-Za-z0-9][A-Za-z0-9_-]*): (.*)$/u.exec(line);
		if (!header) throw new Error("Malformed Apalache JAR manifest header");
		const name = header[1].toLowerCase();
		if (name === "class-path") throw new Error("Unsupported Apalache JAR Class-Path delegation");
		if (!Object.hasOwn(APALACHE_MANIFEST_ATTRIBUTES, name))
			throw new Error("Unsupported Apalache JAR manifest attribute: " + header[1]);
		if (attributes.has(name)) throw new Error("Duplicate Apalache JAR manifest attribute: " + header[1]);
		attributes.set(name, header[2]);
		previous = name;
	}
	if (attributes.get("manifest-version") !== "1.0") throw new Error("Unsupported Apalache JAR manifest version");
	if (attributes.has("enable-native-access") && attributes.get("enable-native-access") !== "ALL-UNNAMED")
		throw new Error("Unsupported Apalache JAR native-access arrangement");
	const mainClass = attributes.get("main-class");
	if (mainClass !== APALACHE_TOOL_MAIN && mainClass !== APALACHE_BOOTSTRAP_MAIN)
		throw new Error("Unsupported Apalache JAR entrypoint");
	if (toolClasses !== 1) throw new Error("Missing or ambiguous bundled Apalache Tool class");
	if (mainClass === APALACHE_BOOTSTRAP_MAIN && bootstrapClasses !== 1)
		throw new Error("Missing or ambiguous reviewed Apalache bootstrap class");
	return { mainClass, bootstrapEntry: mainClass === APALACHE_BOOTSTRAP_MAIN ? APALACHE_BOOTSTRAP_ENTRY : null };
}

export function validateApalacheBootstrapHash(hash: string): void {
	if (hash !== APALACHE_BOOTSTRAP_HASH) throw new Error("Unreviewed Apalache bootstrap class identity");
}

const APALACHE_BOOTSTRAP_CLASS_PROBE = String.raw`
const cp = require('node:child_process'), crypto = require('node:crypto');
const out = cp.spawnSync(process.argv[1], ['-p', process.argv[2], process.argv[3]], {maxBuffer:1048576});
if (out.error) throw out.error;
if (out.signal || out.status !== 0 || out.stderr.length) throw Error('Cannot identify Apalache bootstrap class bytes');
process.stdout.write(JSON.stringify({hash:'sha256:'+crypto.createHash('sha256').update(out.stdout).digest('hex')}));
`;
const QUINT_SELECTION_PROBE = String.raw`
const p = require('node:path'), fs = require('node:fs');
const source = process.argv[1], selectedVersion = process.argv[2];
const config = require(p.join(source, 'config.js'));
const apalache = require(p.join(source, 'apalache.js'));
const evaluator = require(p.join(source, 'rust', 'binaryManager.js'));
const version = selectedVersion || apalache.DEFAULT_APALACHE_VERSION_TAG;
if (typeof version !== 'string' || typeof evaluator.QUINT_EVALUATOR_VERSION !== 'string') throw Error('Unknown Quint backend selection');
const evaluatorSource = fs.readFileSync(p.join(source, 'rust', 'binaryManager.js'), 'utf8');
const executable = evaluatorSource.match(/let executable = ['"]([^'"]+)['"]/)[1];
if (process.platform === 'win32') throw Error('Quint POSIX backend required');
process.stdout.write(JSON.stringify({apalacheVersion:version,evaluatorVersion:evaluator.QUINT_EVALUATOR_VERSION,
 apalacheDirectory:p.join(config.apalacheDistDir(version),'apalache'),
 evaluator:p.join(config.rustEvaluatorDir(evaluator.QUINT_EVALUATOR_VERSION),executable)}));
`;
const LISTENER_PROBE = String.raw`
const cp = require('node:child_process');
const out = cp.spawnSync(process.argv[1], ['-nP','-iTCP:'+process.argv[2],'-sTCP:LISTEN','-Fpn'], {encoding:'utf8',maxBuffer:1048576});
if (out.error) throw out.error;
if (out.signal || (out.status !== 0 && out.status !== 1)) throw Error('Cannot inspect verifier listener');
if (out.status === 1 && (out.stdout || out.stderr)) throw Error('Ambiguous verifier listener inspection');
const pids = [...new Set(out.stdout.split('\n').filter(s=>/^p[0-9]+$/.test(s)).map(s=>Number(s.slice(1))))];
process.stdout.write(JSON.stringify({pids}));
`;
async function apalacheGuard(
	context: AdapterContext,
	node: string,
	endpoints: readonly string[],
	discovery: ToolDiscovery[],
): Promise<() => Promise<void>> {
	let lsof: string;
	if (await exists("/usr/sbin/lsof")) lsof = "/usr/sbin/lsof";
	else lsof = (await context.resolveCommand("lsof")).invoked;
	const check = async (retain: boolean): Promise<void> => {
		for (const endpoint of endpoints) {
			const match = /^(localhost|127\.0\.0\.1|\[::1\]):([0-9]+)$/u.exec(endpoint);
			if (!match || Number(match[2]) < 1 || Number(match[2]) > 65535)
				throw new Error(`Unidentifiable or nonlocal Apalache endpoint: ${endpoint}`);
			const result = await context.probe([node, "-e", LISTENER_PROBE, lsof, match[2]]);
			if (retain) discovery.push(result.identity);
			const metadata = object(probeJSON(result), "Apalache listener");
			if (!Array.isArray(metadata.pids) || metadata.pids.some((pid) => !Number.isSafeInteger(pid) || Number(pid) <= 0))
				throw new Error("Invalid Apalache listener identity");
			if (metadata.pids.length)
				throw new Error(
					`Apalache endpoint ${endpoint} is externally owned; its startup environment/configuration and serialized ownership are not attested`,
				);
		}
	};
	await check(true);
	return () => check(false);
}

export async function identifyQuint(context: AdapterContext): Promise<AdapterResult> {
	const subcommand = context.subject[1];
	if (!["verify", "run", "test", "typecheck", "parse", "compile"].includes(subcommand))
		throw new Error("Unsupported Quint adapter subject");
	const cli = await context.resolveCommand(context.subject[0]);
	const installed = await quintPackage(cli.realpath);
	const sourceDirectory = path.dirname(cli.realpath);
	const cliSource = await fs.readFile(cli.realpath, "utf8");
	const node = await scriptNode(context, cli.realpath);
	if (context.effectiveEnv.NODE_PATH || context.effectiveEnv.NODE_OPTIONS)
		throw new Error("Quint selects an undeclared Node startup/module closure");
	const roots: ToolRoot[] = [
		{ label: "cli", path: installed, exclude: ["node_modules"] },
		{ label: "node/executable", path: node.realpath },
	];
	const discovery: ToolDiscovery[] = [];
	roots.push(...(await packageRoots(context, [installed])));
	await probe(context, discovery, [node.invoked, "--version"]);
	addResult(roots, discovery, prefixResult(await context.native([node.invoked]), "node"));
	const contexts = context.applicationContexts ?? [];
	const subjects: { command: readonly string[]; cwd: string; resources: readonly string[] }[] = [];
	for (const application of context.commandContexts ?? contexts) {
		const entry = await context.resolveCommand(application.subject[0], application.cwd);
		if (entry.realpath === cli.realpath) {
			if (application.subject[1] !== subcommand)
				throw new Error("Quint adapter declaration does not identify the selected application subcommand");
			const recipe = contexts.find((item) => item.cwd === application.cwd && item.subject === application.subject);
			subjects.push({ command: application.subject, cwd: application.cwd, resources: recipe?.recipe.resources ?? [] });
		} else if (inside(installed, entry.realpath) || entry.realpath === node.realpath)
			throw new Error("Unsupported Quint application entry; invoke the declared Quint CLI directly");
	}
	if (!subjects.length) subjects.push({ command: context.subject, cwd: context.cwd, resources: [] });
	const selectingVerification =
		subcommand === "verify" ||
		(subcommand === "compile" && subjects.some((subject) => option(subject.command, "target") === "tlaplus"));
	if (subcommand === "verify")
		for (const subject of subjects) {
			const backend = option(subject.command, "backend") ?? cliDefault(cliSource, subcommand, "backend");
			if (backend !== "apalache" && backend !== "tlc")
				throw new Error(`Unsupported installed Quint verification backend: ${backend}`);
		}
	const endpoints = selectingVerification
		? [
				...new Set(
					subjects.map(
						(s) => option(s.command, "server-endpoint") ?? cliDefault(cliSource, subcommand, "server-endpoint"),
					),
				),
			].sort(utf8Compare)
		: [];
	const preDispatch = selectingVerification
		? await apalacheGuard(context, node.invoked, endpoints, discovery)
		: undefined;
	const resourceSubjects = contexts.filter(
		(c) =>
			c.recipe.resources.length &&
			(c.subject[1] === subcommand || path.basename(c.subject[0]) !== path.basename(context.subject[0])),
	);
	const resourceRequirements = selectingVerification
		? resourceSubjects.reduce<string[]>(
				(common, application, index) =>
					index === 0
						? [...application.recipe.resources]
						: common.filter((r) => application.recipe.resources.includes(r)),
				[],
			)
		: [];
	if (selectingVerification && !resourceRequirements.length)
		throw new Error("Apalache verification requires a shared declared resource for its selected endpoint");
	const backendSelections = new Map<string, { version: string; directory: string; evaluator: string }>();
	for (const subject of subjects) {
		if (subcommand === "run" || subcommand === "test") {
			const backend = option(subject.command, "backend") ?? cliDefault(cliSource, subcommand, "backend");
			if (backend !== "rust" && backend !== "typescript")
				throw new Error(`Unsupported installed Quint evaluator backend: ${backend}`);
			if (backend === "typescript") continue;
		}
		if (!selectingVerification && subcommand !== "run" && subcommand !== "test") continue;
		const selectionCommand = [node.invoked, "-e", QUINT_SELECTION_PROBE, sourceDirectory];
		const selectedVersion = option(subject.command, "apalache-version");
		if (selectedVersion !== undefined) selectionCommand.push(selectedVersion);
		const result = await probe(context, discovery, selectionCommand, { cwd: subject.cwd });
		const metadata = object(probeJSON(result), "Quint backend");
		const version = text(metadata.apalacheVersion, "Apalache version");
		const selected = {
			version,
			directory: text(metadata.apalacheDirectory, "Apalache distribution"),
			evaluator: text(metadata.evaluator, "Quint evaluator"),
		};
		if (backendSelections.has(version) && backendSelections.get(version)?.directory !== selected.directory)
			throw new Error("Conflicting Quint backend selection");
		backendSelections.set(version, selected);
		const evaluator = await regular(selected.evaluator, true);
		roots.push({ label: "evaluator/executable", path: evaluator });
		addResult(roots, discovery, prefixResult(await context.native([evaluator]), "evaluator"));
		for (const flag of ["apalache-config", "tlc-config"]) {
			const value = option(subject.command, flag);
			if (value) {
				const configFile = await inputPath(subject.cwd, value, "Quint configuration path");
				await configurationRoot(roots, "apalache", configFile);
				if (flag === "tlc-config") {
					const config = object(parseJSON(await fs.readFile(configFile)), "TLC configuration");
					for (const [key, value] of Object.entries(config)) {
						const valid =
							key === "maxHeap"
								? typeof value === "string" && /^-Xmx[1-9][0-9]*[kKmMgG]?$/u.test(value)
								: key === "stackSize" && typeof value === "string" && /^-Xss[1-9][0-9]*[kKmMgG]?$/u.test(value);
						if (!valid) throw new Error(`Unsupported TLC configuration field or memory-size value: ${key}`);
					}
				}
				if (flag === "apalache-config")
					await probe(
						context,
						discovery,
						[
							node.invoked,
							"-e",
							"const fs=require('node:fs');const c=JSON.parse(fs.readFileSync(process.argv[1],'utf8'));let solvers=[];function walk(v){if(!v||typeof v!=='object')return;for(const [k,x] of Object.entries(v)){if(/solver/i.test(k)&&typeof x==='string'){if(x.toLowerCase()!=='z3')throw Error('Unidentifiable nonbundled Apalache solver');solvers.push(x);}if(/^(?:executable|binary|library|jar|command)(?:[-_]?path)?$/i.test(k)&&typeof x==='string'&&x)throw Error('Unidentified external Apalache executable/library configuration');walk(x);}}walk(c);process.stdout.write(JSON.stringify({solvers}));",
							configFile,
						],
						{ cwd: subject.cwd },
					);
			}
		}
	}
	if (selectingVerification) {
		for (const selected of backendSelections.values()) {
			const apalache = await directory(selected.directory);
			const launcher = path.join(apalache, "bin", "apalache-mc");
			await regular(launcher, true);
			const launcherSource = await fs.readFile(launcher, "utf8");
			if (
				!/exec java [^\n]*-jar [^\n]*APALACHE_JAR/u.test(launcherSource) ||
				!launcherSource.includes("../lib/apalache.jar")
			)
				throw new Error("Unknown Apalache JVM launcher selection");
			roots.push({ label: `apalache/${selected.version}`, path: apalache });
			const selectedJar = await inputPath(
				context.cwd,
				context.effectiveEnv.APALACHE_JAR || path.join(apalache, "lib", "apalache.jar"),
				"Apalache JAR path",
			);
			await configurationRoot(roots, "apalache", selectedJar);
			const usesTlc =
				subcommand === "verify" &&
				subjects.some(
					(subject) => (option(subject.command, "backend") ?? cliDefault(cliSource, subcommand, "backend")) === "tlc",
				);
			const jars = new Set([selectedJar]);
			if (usesTlc) jars.add(await inputPath(apalache, "lib/apalache.jar", "TLC classpath JAR path"));
			const unzip = (await context.resolveCommand("unzip")).invoked;
			for (const selectedJar of jars) {
				const listing = await probe(context, discovery, [unzip, "-Z1", selectedJar]);
				const jarEntries = probeText(listing).split("\n").filter(Boolean);
				const manifestProbe = await probe(context, discovery, [unzip, "-p", selectedJar, "META-INF/MANIFEST.MF"]);
				const entrypoint = parseApalacheJarManifest(jarEntries, probeText(manifestProbe));
				if (entrypoint.bootstrapEntry !== null) {
					const classProbe = await probe(context, discovery, [
						node.invoked,
						"-e",
						APALACHE_BOOTSTRAP_CLASS_PROBE,
						unzip,
						selectedJar,
						entrypoint.bootstrapEntry,
					]);
					const observed = object(probeJSON(classProbe), "Apalache bootstrap class");
					validateApalacheBootstrapHash(text(observed.hash, "Apalache bootstrap class hash"));
				}
				if (!jarEntries.some((name) => /(?:com\/microsoft\/z3\/|libz3|z3java)/u.test(name)))
					throw new Error("Apalache distribution has no identifiable bundled solver closure");
			}
		}
		const shell = await context.resolveCommand("bash");
		roots.push({ label: "apalache/shell", path: shell.realpath });
		addResult(roots, discovery, prefixResult(await context.native([shell.invoked]), "apalache"));
		const java = await context.resolveCommand("java");
		for (const name of ["JAVA_TOOL_OPTIONS", "JDK_JAVA_OPTIONS", "_JAVA_OPTIONS", "JVM_ARGS", "JVM_GC_ARGS"])
			if (context.effectiveEnv[name]) throw new Error(`Unsupported JVM startup configuration in ${name}`);
		// Fix the discovery JVM's heap-reference mode; its default can vary with address placement.
		const result = await probe(context, discovery, [
			java.invoked, "-XX:-UseCompressedOops", "-XshowSettings:properties", "-version",
		]);
		const settings = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(result.stderr);
		const home = settings.match(/^\s*java\.home = (.+)\r?$/mu)?.[1]?.trim();
		if (!home) throw new Error("Cannot identify selected installed JVM");
		const javaHome = await directory(home);
		await regular(path.join(javaHome, "bin", "java"), true);
		roots.push({ label: "java/distribution", path: javaHome }, { label: "java/launcher", path: java.realpath });
		addResult(roots, discovery, prefixResult(await context.native([path.join(javaHome, "bin", "java")]), "java"));
		await bindLinkedRoots(roots, "java");
	}
	return { roots, packages: [], discovery, preDispatch, resourceRequirements };
}

type ElanSettings = { defaultToolchain?: string; overrides: Map<string, string> };
function tomlString(value: string): string {
	const stripped = value.trim();
	if (/^'[^']*'$/u.test(stripped)) return stripped.slice(1, -1);
	if (/^"(?:[^"\\]|\\.)*"$/u.test(stripped)) return JSON.parse(stripped) as string;
	throw new Error("Unsupported Elan selection configuration");
}
async function elanSettings(file: string): Promise<ElanSettings> {
	const result: ElanSettings = { overrides: new Map() };
	if (!(await exists(file))) return result;
	let section = "";
	for (const source of (await fs.readFile(file, "utf8")).split(/\r?\n/u)) {
		const line = source.trim();
		if (!line || line.startsWith("#")) continue;
		if (line.startsWith("[")) {
			if (line !== "[overrides]") throw new Error("Unsupported Elan configuration section");
			section = "overrides";
			continue;
		}
		const assignment = /^("(?:[^"\\]|\\.)*"|[^=]+)\s*=\s*(.+)$/u.exec(line);
		if (!assignment) throw new Error("Invalid Elan configuration");
		const key = assignment[1].trim();
		if (section === "overrides") result.overrides.set(tomlString(key), tomlString(assignment[2]));
		else if (key === "default_toolchain") result.defaultToolchain = tomlString(assignment[2]);
		else if (key !== "version" && key !== "telemetry") throw new Error("Unsupported Elan configuration key");
	}
	return result;
}
async function ancestorFile(start: string, name: string): Promise<string | null> {
	for (let cursor = start; ; cursor = path.dirname(cursor)) {
		const file = path.join(cursor, name);
		if (await exists(file)) return file;
		if (path.dirname(cursor) === cursor) return null;
	}
}
function leanInvocation(subject: readonly string[]): readonly string[] {
	if (path.basename(subject[0]) !== "elan") return subject;
	if (
		subject[1] !== "run" ||
		!subject[2] ||
		subject[2].startsWith("-") ||
		!["lean", "lake"].includes(subject[3]) ||
		subject[4]?.startsWith("+")
	)
		throw new Error("Unsupported Elan application selector; expected elan run <toolchain> lean|lake");
	return [subject[3], `+${subject[2]}`, ...subject.slice(4)];
}
type LeanSelectionOptions = {
	toolchain?: string;
	directory?: string;
	configuration: string;
	manifest: string;
	options: Record<string, string>;
	reconfigure: boolean;
};
function leanOptions(subject: readonly string[]): LeanSelectionOptions {
	const result: LeanSelectionOptions = {
		configuration: "lakefile",
		manifest: "lake-manifest.json",
		options: {},
		reconfigure: false,
	};
	const invocation = leanInvocation(subject);
	const lake = path.basename(invocation[0]) === "lake";
	const value = (index: number): string => {
		const token = invocation[index];
		if (!token || token.startsWith("-")) throw new Error("Invalid Lake adapter selector value");
		return token;
	};
	let commandSeen = false;
	for (let i = 1; i < invocation.length; i++) {
		const arg = invocation[i];
		if (arg.startsWith("+") && i === 1) result.toolchain = arg.slice(1);
		else if (!lake) {
			if (!["--version", "--print-prefix", "--deps", "--run"].includes(arg) && !/\.lean$/iu.test(arg))
				throw new Error(`Unsupported Lean application argument: ${arg}`);
		} else if (arg === "-d" || arg === "--dir") result.directory = value(++i);
		else if (arg.startsWith("--dir=")) result.directory = arg.slice(6);
		else if (arg === "-f" || arg === "--file") result.configuration = value(++i);
		else if (arg.startsWith("--file=")) result.configuration = arg.slice(7);
		else if (arg === "--reconfigure" || arg === "-R") result.reconfigure = true;
		else if (["--version", "--help", "-h", "-v", "--verbose", "-q", "--quiet"].includes(arg)) continue;
		else if (!commandSeen && arg === "build") commandSeen = true;
		else if (!commandSeen || !/^[A-Za-z0-9_.]+$/u.test(arg))
			throw new Error(`Unsupported Lake application argument or dependency selector: ${arg}`);
	}
	if (!result.configuration || result.directory === "" || !result.manifest || result.toolchain === "")
		throw new Error("Invalid Lake adapter selector");
	return result;
}
const LAKE_PATH_FIELDS = ["srcDir", "buildDir", "packagesDir", "leanLibDir", "nativeLibDir", "binDir", "irDir"];
const LAKE_ARGUMENT_FIELDS = [
	"weakLeanArgs",
	"moreLeanArgs",
	"weakLeancArgs",
	"moreLeancArgs",
	"weakLinkArgs",
	"moreLinkArgs",
];
async function reviewedLakeConfig(base: string, selected: string): Promise<string> {
	const value = path.extname(selected)
		? selected
		: (await exists(`${base}/${selected}.lean`))
			? selected + ".lean"
			: selected + ".toml";
	const file = await inputPath(base, value, "Lake configuration path");
	const source = await fs.readFile(file, "utf8");
	if (file.endsWith(".lean")) {
		for (const line of source.split(/\r?\n/u)) {
			if (!line.trim() || /^\s*--/u.test(line)) continue;
			if (
				/^(?:import Lake|open Lake DSL|@\[default_target\])\s*$/u.test(line) ||
				/^(?:package|lean_lib|lean_exe|input_file|input_dir) [A-Za-z_][A-Za-z0-9_]*(?: where)?\s*$/u.test(line)
			)
				continue;
			const assignment = /^\s+([A-Za-z][A-Za-z0-9]*) := ("(?:[^"\\]|\\.)*")\s*$/u.exec(line);
			if (assignment && [...LAKE_PATH_FIELDS, "path"].includes(assignment[1])) {
				JSON.parse(assignment[2]);
				continue;
			}
			throw new Error(`Unsupported Lake configuration construct or native/custom target: ${line.trim()}`);
		}
	} else if (file.endsWith(".toml")) {
		const table = object(Bun.TOML.parse(source), "Lake TOML configuration");
		const check = (value: Record<string, unknown>, keys: readonly string[]): void => {
			for (const key of Object.keys(value))
				if (!keys.includes(key)) throw new Error(`Unsupported Lake configuration key: ${key}`);
		};
		check(table, [
			"name",
			...LAKE_PATH_FIELDS,
			...LAKE_ARGUMENT_FIELDS,
			"version",
			"defaultTargets",
			"lean_lib",
			"lean_exe",
			"input_file",
			"input_dir",
			"require",
			"enableArtifactCache",
			"restoreAllArtifacts",
		]);
		for (const kind of ["lean_lib", "lean_exe", "input_file", "input_dir", "require"]) {
			if (table[kind] === undefined) continue;
			if (!Array.isArray(table[kind])) throw new Error(`Unsupported Lake configuration table: ${kind}`);
			for (const entry of table[kind] as unknown[])
				check(
					object(entry, `Lake ${kind}`),
					kind === "require"
						? ["name", "scope", "git", "rev", "path", "subDir", "version"]
						: kind.startsWith("input_")
							? ["name", "path"]
							: [
									"name",
									"srcDir",
									...LAKE_ARGUMENT_FIELDS,
									...(kind === "lean_lib" ? ["roots", "globs"] : ["root", "exeName"]),
								],
				);
		}
	} else throw new Error("Unsupported Lake configuration language");
	return file;
}

type LakeMetadata = {
	name: string;
	directory: string;
	sourceDirectories: string[];
	inputPaths: string[];
	configuration: string;
	manifest: string;
	lakeDirectory: string;
	packagesDirectory: string;
	buildDirectory: string;
	leanLibraryDirectory: string;
	nativeLibraryDirectory: string;
	binaryDirectory: string;
	irDirectory: string;
	cacheDirectory: string;
	configurationCacheDirectory: string;
	dependencies: string[];
	systemConfiguration: string | null;
	compiler: string;
	archiver: string;
	dependencyOptions: { name: string; options: Record<string, string> }[];
	nativeArguments: string[];
	leanArguments: string[];
	targetArguments: { native: string[]; lean: string[] }[];
	unresolvedNativeTargets: boolean;
	initialLeanPath: string[];
	initialSourcePath: string[];
	leanExecutable: string;
	lakeExecutable: string;
};
type SelectedLean = { home: string; lean: string; lake: string; elan: string; selection: string; entry: string };
async function selectedLean(
	context: AdapterContext,
	cwd: string,
	subject: readonly string[],
	discovery: ToolDiscovery[],
	roots: ToolRoot[],
): Promise<SelectedLean> {
	const entry = await context.resolveCommand(subject[0], cwd);
	const options = leanOptions(subject);
	const pin = await ancestorFile(cwd, "lean-toolchain");
	const pinSelection = pin ? (await fs.readFile(pin, "utf8")).trim() : undefined;
	if (pin) await configurationRoot(roots, "distribution", pin);
	const elan = path.join(path.dirname(entry.realpath), "elan");
	if (!(await exists(elan))) {
		const home = await directory(path.dirname(path.dirname(entry.realpath)));
		const lean = await regular(path.join(home, "bin", "lean"), true),
			lake = await regular(path.join(home, "bin", "lake"), true);
		const selection = options.toolchain ?? context.effectiveEnv.ELAN_TOOLCHAIN ?? pinSelection;
		if (!selection) throw new Error("Lean adapter requires an explicit subject toolchain selection");
		const prefix = probeText(await probe(context, discovery, [lean, "--print-prefix"], { cwd })).trim();
		if ((await directory(prefix)) !== home)
			throw new Error("Lean prefix conflicts with selected installed distribution");
		const pinnedVersion = /^leanprover\/lean4:v([0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?)$/u.exec(selection)?.[1];
		const versionResult = await probe(context, discovery, [lean, "--version"], { cwd });
		const version = probeText(versionResult) + new TextDecoder("utf-8", { fatal: true }).decode(versionResult.stderr);
		if (!pinnedVersion || !version.includes(`version ${pinnedVersion},`))
			throw new Error("Direct Lean distribution does not match subject lean-toolchain");
		return { home, lean, lake, elan: "", selection, entry: entry.realpath };
	}
	const configuredElanHome =
		context.effectiveEnv.ELAN_HOME ||
		(context.effectiveEnv.HOME ? path.join(context.effectiveEnv.HOME, ".elan") : null);
	if (!configuredElanHome) throw new Error("Elan selection requires an attested public HOME or ELAN_HOME");
	const elanHome = await directory(path.resolve(cwd, configuredElanHome));
	const settingsFile = path.join(elanHome, "settings.toml"),
		settings = await elanSettings(settingsFile);
	if (await exists(settingsFile)) await configurationRoot(roots, "distribution", settingsFile);
	let override: string | undefined;
	for (const [name, token] of [...settings.overrides].sort((a, b) => b[0].length - a[0].length))
		if (inside(path.resolve(name), cwd)) {
			override = token;
			break;
		}
	const selection = options.toolchain ?? context.effectiveEnv.ELAN_TOOLCHAIN ?? override ?? pinSelection;
	if (!selection) throw new Error("Lean adapter requires subject lean-toolchain; Elan default fallback is forbidden");
	const installName = selection.replace(/\//gu, "--").replace(/:/gu, "---");
	if (!installName || installName.includes(path.sep) || installName === "." || installName === "..")
		throw new Error("Invalid selected Lean toolchain");
	const installed = path.join(elanHome, "toolchains");
	if (!(await fs.readdir(installed)).includes(installName))
		throw new Error(`Selected Lean version is not installed: ${selection}`);
	const home = await directory(path.join(installed, installName));
	const env = { ...context.effectiveEnv, ELAN_TOOLCHAIN: selection };
	const lean = await regular(
		probeText(await probe(context, discovery, [elan, "which", "lean"], { cwd, env })).trim(),
		true,
	);
	const lake = await regular(
		probeText(await probe(context, discovery, [elan, "which", "lake"], { cwd, env })).trim(),
		true,
	);
	if (!inside(home, lean) || !inside(home, lake))
		throw new Error("Elan selected a different installed Lean/Lake distribution");
	roots.push({ label: "distribution/elan", path: await regular(elan, true) });
	return { home, lean, lake, elan, selection, entry: entry.realpath };
}

export async function identifyLean(context: AdapterContext): Promise<AdapterResult> {
	if (!["lake", "lean"].includes(path.basename(leanInvocation(context.subject)[0])))
		throw new Error("Unsupported Lean adapter subject");
	const roots: ToolRoot[] = [],
		discovery: ToolDiscovery[] = [],
		cacheNamespaces: CacheNamespaceSelection[] = [];
	const options = leanOptions(context.subject);
	const cwd = await directory(await inputPath(context.cwd, options.directory ?? ".", "Lake working directory"));
	const selected = await selectedLean(context, context.cwd, context.subject, discovery, roots);
	roots.push({ label: "distribution", path: selected.home, exclude: ["lake/cache"] });
	if (!inside(selected.home, selected.entry)) roots.push({ label: "distribution/entry", path: selected.entry });
	await probe(context, discovery, [selected.lean, "--version"], { cwd });
	await probe(context, discovery, [selected.lake, "--version"], { cwd });
	for (const name of ["LEAN_SYSROOT", "LAKE_HOME"])
		if (
			context.effectiveEnv[name] &&
			(await directory(path.resolve(cwd, context.effectiveEnv[name]))) !== selected.home
		)
			throw new Error(`Unbound alternate Lean distribution in ${name}`);
	if (
		context.effectiveEnv.LEAN &&
		(await context.resolveCommand(context.effectiveEnv.LEAN, cwd)).realpath !== selected.lean
	)
		throw new Error("Unbound alternate Lean executable");
	const applications = [];
	for (const application of context.commandContexts ?? context.applicationContexts ?? []) {
		const entry = await context.resolveCommand(application.subject[0], application.cwd);
		const proxy = selected.elan && (await sameFile(entry.realpath, selected.elan));
		if (
			!["lean", "lake", "elan"].includes(path.basename(application.subject[0])) &&
			!inside(selected.home, entry.realpath) &&
			!proxy
		)
			continue;
		const subject = leanInvocation(application.subject);
		const kind = path.basename(subject[0]);
		if ((kind !== "lean" && kind !== "lake") || (entry.realpath !== selected[kind] && !proxy))
			throw new Error("Lean adapter declaration does not identify the selected application executable");
		applications.push({ ...application, subject });
		if (proxy)
			roots.push({ label: `distribution/proxies/${D("lean-proxy", entry.realpath).slice(7)}`, path: entry.realpath });
		const actual = await selectedLean(context, application.cwd, application.subject, discovery, []);
		if (
			actual.selection !== selected.selection ||
			actual.home !== selected.home ||
			actual.lean !== selected.lean ||
			actual.lake !== selected.lake
		)
			throw new Error("Lean adapter declaration does not identify the selected application toolchain");
	}
	const projectRoot = await directory(context.root);
	const sourceRequirements = {
		directories: [] as string[],
		files: [] as string[],
		inputDirectories: [] as string[],
		excludedPaths: [] as string[],
	};
	for (const application of [...applications, { subject: leanInvocation(context.subject), cwd }]) {
		if (path.basename(application.subject[0]) !== "lean") continue;
		for (const value of application.subject.slice(1).filter((arg) => /\.lean$/iu.test(arg))) {
			const real = await inputPath(application.cwd, value, "Lean source input");
			if (!inside(projectRoot, real) || !(await fs.stat(real)).isFile())
				throw new Error(`Lean source input resolves outside project files: ${value}`);
			sourceRequirements.files.push(path.relative(projectRoot, real).split(path.sep).join("/"));
		}
	}
	if (
		path.basename(leanInvocation(context.subject)[0]) === "lean" &&
		!(await exists(path.join(cwd, options.manifest)))
	) {
		if ((await exists(path.join(cwd, "lakefile.lean"))) || (await exists(path.join(cwd, "lakefile.toml"))))
			throw new Error("Lake workspace has no installed lock; metadata discovery cannot resolve packages offline");
		for (const value of (context.effectiveEnv.LEAN_PATH ?? "").split(path.delimiter).filter(Boolean)) {
			if (!inside(selected.home, await directory(path.resolve(cwd, value))))
				throw new Error("Standalone Lean imports an undeclared installed package");
		}
		const leanApplications = applications.filter((app) => path.basename(app.subject[0]) === "lean");
		const inputs = leanApplications.length ? leanApplications : [{ subject: context.subject, cwd }];
		if (!inputs.some((application) => application.subject.slice(1).some((arg) => /\.lean$/iu.test(arg))))
			throw new Error("Standalone Lean adapter has no identifiable source/import subject");
		for (const application of inputs)
			for (const input of application.subject.slice(1).filter((arg) => /\.lean$/iu.test(arg))) {
				const result = await probe(
					context,
					discovery,
					[selected.lean, "--deps", await inputPath(application.cwd, input, "Lean source input")],
					{ cwd: application.cwd, env: { ...context.effectiveEnv, ELAN_TOOLCHAIN: selected.selection } },
				);
				for (const dependency of probeText(result).split(/\r?\n/u).filter(Boolean))
					if (!inside(selected.home, await regular(path.resolve(application.cwd, dependency))))
						throw new Error("Standalone Lean import requires a locked Lake package/cache context");
			}
		const native = prefixResult(await context.native([selected.lean], { cwd }), "distribution");
		addResult(roots, discovery, native);
		return { roots, packages: [], discovery, cacheNamespaces: [], sdk: native.sdk, sourceRequirements };
	}
	const applicationOptions = applications
		.filter((app) => path.basename(app.subject[0]) === "lake")
		.map((app) => ({
			cwd: path.resolve(app.cwd, leanOptions(app.subject).directory ?? "."),
			options: leanOptions(app.subject),
		}));
	if (
		applicationOptions.some(
			(app) =>
				app.cwd !== cwd ||
				app.options.configuration !== options.configuration ||
				app.options.manifest !== options.manifest ||
				app.options.reconfigure !== options.reconfigure ||
				D("lake-options", app.options.options) !== D("lake-options", options.options),
		)
	)
		throw new Error("Lean adapter declaration does not identify all selected Lake application contexts");
	const manifestFile = path.resolve(cwd, options.manifest);
	const manifest = object(parseJSON(await fs.readFile(manifestFile)), "Lake manifest");
	await configurationRoot(roots, "distribution", manifestFile);
	const entries = manifest.packages;
	if (!Array.isArray(entries)) throw new Error("Invalid locked Lake packages");
	const packages = new Map<string, Record<string, unknown>>();
	for (const value of entries) {
		const entry = object(value, "locked Lake package"),
			name = text(entry.name, "Lake package name");
		if (!/^[A-Za-z0-9][A-Za-z0-9._-]*$/u.test(name) || packages.has(name))
			throw new Error("Ambiguous Lake package name");
		if (entry.type !== "git" && entry.type !== "path") throw new Error("Unsupported locked Lake package source");
		packages.set(name, entry);
	}
	const env = { ...context.effectiveEnv, ELAN_TOOLCHAIN: selected.selection };
	// LakeInstall.ofLean and Lake.Util.NativeLib define this installed runtime path.
	const lakeRuntime = await regular(
		path.join(selected.home, "lib", "lean", `libLake_shared.${process.platform === "darwin" ? "dylib" : "so"}`),
	);
	if (!inside(selected.home, lakeRuntime)) roots.push({ label: "distribution/lake-runtime", path: lakeRuntime });
	const metadataCommand = [
		...(selected.elan ? [selected.elan, "run", selected.selection, "lean"] : [selected.lean]),
		`--load-dynlib=${lakeRuntime}`,
	];
	const readMetadata = async (
		dir: string,
		config: string,
		manifest: string,
		name: string,
		index: number,
		configOptions: Record<string, string>,
	): Promise<LakeMetadata> => {
		const configuration = await reviewedLakeConfig(dir, config);
		if (Object.keys(configOptions).length) throw new Error("Unsupported Lake configuration option keys");
		if (await exists(path.join(dir, ".lake", "package-overrides.json")))
			throw new Error("Unsupported Lake package overrides; only the installed manifest is admitted");
		const result = await probe(
			context,
			discovery,
			[
				...metadataCommand,
				"--run",
				LAKE_METADATA,
				selected.home,
				cwd,
				dir,
				config,
				manifest,
				JSON.stringify(name),
				String(index),
				JSON.stringify(configOptions),
				String(options.reconfigure),
				String(Boolean(selected.elan)),
			],
			{ cwd, env },
		);
		const raw = object(probeJSON(result), "Lake effective configuration");
		for (const key of [
			"name",
			"directory",
			"configuration",
			"configurationCacheDirectory",
			"manifest",
			"lakeDirectory",
			"packagesDirectory",
			"buildDirectory",
			"leanLibraryDirectory",
			"nativeLibraryDirectory",
			"binaryDirectory",
			"irDirectory",
			"cacheDirectory",
			"compiler",
			"archiver",
			"leanExecutable",
			"lakeExecutable",
		])
			text(raw[key], `Lake ${key}`);
		strings(raw.dependencies, "Lake dependency names");
		strings(raw.initialLeanPath, "Lean initial library path");
		strings(raw.initialSourcePath, "Lean initial source path");
		strings(raw.sourceDirectories, "Lake source directories");
		strings(raw.inputPaths, "Lake input paths");
		if (!Array.isArray(raw.dependencyOptions)) throw new Error("Invalid Lake dependency options");
		for (const value of raw.dependencyOptions) {
			const edge = object(value, "Lake dependency options");
			text(edge.name, "Lake dependency name");
			if (Object.values(object(edge.options, "Lake dependency options")).some((value) => typeof value !== "string"))
				throw new Error("Invalid Lake dependency option value");
		}
		if (
			D("lake-dependencies", raw.dependencies) !==
			D(
				"lake-dependencies",
				raw.dependencyOptions.map((value) => object(value, "Lake dependency").name),
			)
		)
			throw new Error("Inconsistent Lake dependency metadata");
		if (raw.systemConfiguration !== null) text(raw.systemConfiguration, "Lake system configuration");
		strings(raw.nativeArguments, "Lake native arguments");
		strings(raw.leanArguments, "Lake Lean arguments");
		if (typeof raw.unresolvedNativeTargets !== "boolean" || raw.unresolvedNativeTargets)
			throw new Error("Lake contains a native/custom target with undiscovered callable/tool dependencies");
		if (!Array.isArray(raw.targetArguments)) throw new Error("Invalid Lake target arguments");
		for (const value of raw.targetArguments) {
			const target = object(value, "Lake target arguments");
			strings(target.native, "Lake target native arguments");
			strings(target.lean, "Lake target Lean arguments");
		}
		const metadata = raw as unknown as LakeMetadata;
		if ((await canonicalToolPath(metadata.configuration)) !== configuration)
			throw new Error("Lake configuration selection differs from reviewed declaration");
		metadata.cacheDirectory = path.resolve(cwd, metadata.cacheDirectory);
		if (metadata.systemConfiguration) metadata.systemConfiguration = path.resolve(cwd, metadata.systemConfiguration);
		if (
			(await regular(metadata.leanExecutable, true)) !== selected.lean ||
			(await regular(metadata.lakeExecutable, true)) !== selected.lake
		)
			throw new Error("Lake selected an unattested Lean/Lake executable");
		await configurationRoot(roots, "distribution", metadata.configuration);
		if (metadata.systemConfiguration && (await exists(metadata.systemConfiguration)))
			await configurationRoot(roots, "distribution", metadata.systemConfiguration);
		return metadata;
	};
	const rootMetadata = await readMetadata(cwd, options.configuration, options.manifest, "", 0, options.options);
	const lockedPackagesDirectory =
		manifest.packagesDir === undefined || manifest.packagesDir === null
			? rootMetadata.packagesDirectory
			: text(manifest.packagesDir, "Lake packages directory");
	const overridesFile = path.join(rootMetadata.lakeDirectory, "package-overrides.json");
	if ((await exists(overridesFile)) || (await exists(path.join(cwd, ".lake", "package-overrides.json"))))
		throw new Error("Unsupported Lake package overrides; only the installed manifest is admitted");
	const selectedPackages: { name: string; directory: string; metadata: LakeMetadata }[] = [];
	const admitted = new Set<string>([rootMetadata.name]);
	const queue = [{ name: rootMetadata.name, directory: cwd, metadata: rootMetadata }];
	for (let cursor = 0; cursor < queue.length; cursor++) {
		const parent = queue[cursor];
		for (let i = parent.metadata.dependencyOptions.length - 1; i >= 0; i--) {
			const edge = parent.metadata.dependencyOptions[i],
				name = edge.name;
			if (name === parent.name) throw new Error("Lake package requires itself");
			if (admitted.has(name)) continue;
			const entry = packages.get(name);
			if (!entry) throw new Error(`Imported Lake package is missing from lock: ${name}`);
			const gitDirectory =
				entry.type === "git" ? await inputPath(cwd, `${lockedPackagesDirectory}/${name}`, "Lake package path") : null;
			const dir = await directory(
				await inputPath(
					entry.type === "path" ? cwd : gitDirectory!,
					entry.type === "path"
						? text(entry.dir, "Lake path package")
						: typeof entry.subDir === "string"
							? entry.subDir
							: ".",
					"Lake package path",
				),
			);
			if (entry.type === "git") {
				const revision = text(entry.rev, "locked Lake revision");
				if (!/^[0-9a-f]{40}$/u.test(revision)) throw new Error("Lake Git dependency is not exactly locked");
				const git = await context.resolveCommand("git", gitDirectory!);
				const actual = probeText(
					await probe(context, discovery, [git.invoked, "-C", gitDirectory!, "rev-parse", "HEAD"]),
				).trim();
				if (actual !== revision) throw new Error(`Installed Lake package does not match lock: ${name}`);
			}
			const metadata = await readMetadata(
				dir,
				typeof entry.configFile === "string" ? entry.configFile : "lakefile",
				typeof entry.manifestFile === "string" ? entry.manifestFile : "lake-manifest.json",
				name,
				queue.length,
				edge.options,
			);
			if (metadata.name !== name) throw new Error("Installed Lake package name conflicts with lock");
			admitted.add(name);
			const selectedPackage = { name, directory: dir, metadata };
			selectedPackages.push(selectedPackage);
			queue.push(selectedPackage);
		}
	}
	const all = [{ name: rootMetadata.name, directory: cwd, metadata: rootMetadata }, ...selectedPackages];
	for (let index = 0; index < all.length; index++) {
		const pkg = all[index],
			packageKey = D("lake-package-name", pkg.name).slice(7),
			role = index === 0 ? "lake-project-build" : `lake-package-build.${packageKey}`;
		cacheNamespaces.push({ role, kind: "selected-path", path: pkg.metadata.buildDirectory });
		cacheNamespaces.push({
			role: role + ".lean-library",
			kind: "selected-path",
			path: pkg.metadata.leanLibraryDirectory,
		});
		cacheNamespaces.push({
			role: role + ".native-library",
			kind: "selected-path",
			path: pkg.metadata.nativeLibraryDirectory,
		});
		cacheNamespaces.push({ role: role + ".binary", kind: "selected-path", path: pkg.metadata.binaryDirectory });
		cacheNamespaces.push({ role: role + ".ir", kind: "selected-path", path: pkg.metadata.irDirectory });
		cacheNamespaces.push({
			role: index === 0 ? "lake-project-configuration" : `lake-package-configuration.${packageKey}`,
			kind: "selected-path",
			path: pkg.metadata.configurationCacheDirectory,
		});
		if (index !== 0) {
			const excluded = [
				".git",
				...[
					pkg.metadata.buildDirectory,
					pkg.metadata.configurationCacheDirectory,
					pkg.metadata.cacheDirectory,
					pkg.metadata.packagesDirectory,
					path.join(pkg.metadata.lakeDirectory, "build.barrel"),
				]
					.map((value) => path.relative(pkg.directory, value))
					.filter(
						(relative) =>
							relative && relative !== ".." && !relative.startsWith(`..${path.sep}`) && !path.isAbsolute(relative),
					)
					.map((relative) => relative.split(path.sep).join("/")),
			];
			roots.push({ label: `packages/${pkg.name}`, path: pkg.directory, exclude: excluded });
		}
	}
	cacheNamespaces.push({ role: "lake-artifact-cache", kind: "selected-path", path: rootMetadata.cacheDirectory });
	const distributionRoot = roots.find((root) => root.label === "distribution")!;
	const distributionExclusions = [...(distributionRoot.exclude ?? [])];
	for (const namespace of cacheNamespaces)
		if (namespace.kind === "selected-path" && inside(selected.home, path.resolve(namespace.path))) {
			const relative = path.relative(selected.home, path.resolve(namespace.path)).split(path.sep).join("/");
			if (!relative || /^(?:bin|lib|include|src|share)(?:\/|$)/u.test(relative))
				throw new Error("Lake generated namespace overlaps installed distribution inputs");
			distributionExclusions.push(relative);
		}
	distributionRoot.exclude = [...new Set(distributionExclusions)].sort(utf8Compare);
	const hashedRoots = roots.filter((root) => root.label === "distribution" || root.label.startsWith("packages/"));
	const generatedPaths = [
		path.join(projectRoot, ".git"),
		...all.flatMap((pkg) => [
			pkg.metadata.buildDirectory,
			pkg.metadata.configurationCacheDirectory,
			pkg.metadata.cacheDirectory,
			pkg.metadata.packagesDirectory,
			path.join(pkg.metadata.lakeDirectory, "build.barrel"),
		]),
	];
	const excludedPaths = await Promise.all(
		generatedPaths.map(async (value) => ((await exists(value)) ? canonicalToolPath(value) : path.resolve(value))),
	);
	sourceRequirements.excludedPaths = excludedPaths
		.filter((value) => inside(projectRoot, value))
		.map((value) => path.relative(projectRoot, value).split(path.sep).join("/") || ".");
	for (const pkg of all)
		for (const [value, source] of [
			...pkg.metadata.sourceDirectories.map((value) => [value, true] as const),
			...pkg.metadata.inputPaths.map((value) => [value, false] as const),
		]) {
			const real = await inputPath(pkg.directory, value, `Lake ${source ? "srcDir" : "input target"}`);
			const stat = await fs.stat(real);
			if (source ? !stat.isDirectory() : !stat.isDirectory() && !stat.isFile())
				throw new Error(`Unsupported Lake ${source ? "srcDir" : "input target"}: ${value}`);
			if (
				hashedRoots.some(
					(root) =>
						inside(root.path, real) &&
						!root.exclude?.some((excluded) => inside(path.resolve(root.path, excluded), real)),
				)
			)
				continue;
			if (!inside(projectRoot, real) || excludedPaths.some((excluded) => inside(excluded, real)))
				throw new Error(`Lake ${source ? "srcDir" : "input target"} resolves outside hashed input roots: ${value}`);
			const relative = path.relative(projectRoot, real).split(path.sep).join("/") || ".";
			(stat.isDirectory()
				? source
					? sourceRequirements.directories
					: sourceRequirements.inputDirectories
				: sourceRequirements.files
			).push(relative);
		}
	sourceRequirements.directories = [...new Set(sourceRequirements.directories)].sort(utf8Compare);
	sourceRequirements.inputDirectories = [...new Set(sourceRequirements.inputDirectories)].sort(utf8Compare);
	sourceRequirements.files = [...new Set(sourceRequirements.files)].sort(utf8Compare);
	for (const value of [...rootMetadata.initialLeanPath, ...rootMetadata.initialSourcePath]) {
		const real = await directory(path.resolve(cwd, value));
		if (inside(selected.home, real) || all.some((pkg) => inside(pkg.directory, real))) continue;
		throw new Error("Lean search path selects an undeclared imported package");
	}
	for (const pkg of all)
		for (const args of [pkg.metadata.leanArguments, ...pkg.metadata.targetArguments.map((target) => target.lean)])
			if (args.length) throw new Error("Unsupported Lake Lean arguments; plugin and path selectors are not admitted");
	const native: AdapterResult = { roots: [], discovery: [], sdk: null };
	const nativeContexts = new Set<string>();
	for (const pkg of all)
		for (const target of [{ native: [], lean: [] }, ...pkg.metadata.targetArguments]) {
			const flags = [...pkg.metadata.nativeArguments, ...target.native];
			const key = D("lake-native-context", { compiler: pkg.metadata.compiler, archiver: pkg.metadata.archiver, flags });
			if (nativeContexts.has(key)) continue;
			nativeContexts.add(key);
			const next = prefixResult(
				await context.native([selected.lean, lakeRuntime], {
					cwd,
					drivers: { compiler: pkg.metadata.compiler, archiver: pkg.metadata.archiver },
					flags,
				}),
				`distribution/native-context/${key.slice(7)}`,
			);
			if (next.sdk) {
				if (native.sdk && D("lake-sdk", native.sdk) !== D("lake-sdk", next.sdk))
					throw new Error("Ambiguous multiple Lake SDK contexts");
				native.sdk = next.sdk;
			}
			addResult(native.roots, native.discovery!, next);
		}
	addResult(roots, discovery, native);
	return { roots, packages: [], discovery, cacheNamespaces, sdk: native.sdk, sourceRequirements };
}
