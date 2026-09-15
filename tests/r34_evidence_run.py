#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""R34: producer-trusted evidence records and Gate B artifact validation."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TOOL = REPO / "tools" / "evidence-run.ts"
GATE = REPO / "scripts" / "check_evidence_records.py"
RESOLVER = REPO / "scripts" / "fv_project.py"
FAILURES: list[str] = []

sys.path.insert(0, str(REPO / "scripts"))
import fv_project  # noqa: E402  the gate-side half of the exclusion-parser mirror

PRELUDE = r"""
import { realpathSync, symlinkSync, unlinkSync } from "node:fs";
const [, , toolPath, projectRoot] = process.argv;
const mod = await import(toolPath);
const stub: any = {};
for (const key of ["optional", "array", "describe", "min", "max", "default", "nullable"]) stub[key] = () => stub;
const zod: any = new Proxy(stub, { get: (target, key) => key in target ? target[key] : () => stub });
async function realExec(command: string, args: string[], options: any = {}) {
  const child = Bun.spawn([command, ...args], { cwd: options.cwd, stdout: "pipe", stderr: "pipe" });
  const [stdout, stderr, code] = await Promise.all([
    new Response(child.stdout).text(),
    new Response(child.stderr).text(),
    child.exited,
  ]);
  return { stdout, stderr, code, killed: false };
}
"""

# Stubbed Git: exercises producer semantics (markers, drift, executable identity)
# without a repository. The verified-input listing names the fixture's real files,
# so the snapshot is computed over real content.
HARNESS = PRELUDE + r"""
let dirty = false;
const listed = [".fv/intent.md", ".fv/obligations.json", "harness.ts", "probe", "sub/probe"];
const api: any = {
  cwd: projectRoot,
  zod,
  async exec(command: string, args: string[], options: any = {}) {
    if (command === "git" && args[0] === "ls-files") {
      return { stdout: listed.join("\0") + "\0", stderr: "", code: 0, killed: false };
    }
    if (command === "git" && args[0] === "status") {
      return { stdout: dirty ? " M src.ts\0" : "", stderr: "", code: 0, killed: false };
    }
    return realExec(command, args, options);
  },
};
const tool = await mod.default(api);
const passing = await tool.execute("pass", {
  claim_id: "W1",
  command: ["sh", "-c", "echo 'test result: ok.'"],
  evidence_class: "test-witnessed",
  scope: "passing shell probe",
}, undefined, {}, undefined);
const failing = await tool.execute("fail", {
  claim_id: "B1",
  command: ["sh", "-c", "echo failed >&2; exit 7"],
  evidence_class: "bounded-checked",
  scope: "failing shell probe",
}, undefined, {}, undefined);
dirty = true;
const dirtyResult = await tool.execute("dirty", {
  claim_id: "D1", command: ["sh", "-c", "echo 'test result: ok.'"],
  evidence_class: "test-witnessed", scope: "dirty source probe",
}, undefined, {}, undefined);
dirty = false;
const customMarker = await tool.execute("custom", {
  claim_id: "C1", command: ["sh", "-c", "echo CUSTOM_OK"],
  evidence_class: "test-witnessed", scope: "custom marker probe", pass_marker: "CUSTOM_OK",
}, undefined, {}, undefined);
const relativeExecutable = await tool.execute("relative", {
  claim_id: "R1", command: ["./probe"], cwd: "sub",
  evidence_class: "test-witnessed", scope: "relative executable probe",
}, undefined, {}, undefined);
const namedTool = await tool.execute("named", {
  claim_id: "N1", command: ["sh", "-c", "echo 'test result: ok.'"],
  evidence_class: "test-witnessed", scope: "named evidence tool probe", tool: "quint",
}, undefined, {}, undefined);
const cohort = await tool.execute("cohort", {
  claim_id: "S1", evidence_class: "bounded-checked", scope: "atomic evidence cohort probe",
  executions: [
    { tool: "kani", command: ["sh", "-c", "echo 'No violation found'"] },
    { tool: "verus", command: ["sh", "-c", "echo 'VERIFICATION:- SUCCESSFUL'"],
      evidence_class: "proof-discharged" },
  ],
}, undefined, {}, undefined);
const cohortFailure = await tool.execute("cohort-fail", {
  claim_id: "S2", evidence_class: "bounded-checked", scope: "failing cohort member probe",
  executions: [
    { tool: "kani", command: ["sh", "-c", "echo 'No violation found'"] },
    { tool: "verus", command: ["sh", "-c", "echo broken >&2; exit 3"],
      evidence_class: "proof-discharged" },
  ],
}, undefined, {}, undefined);
async function rejected(params: any) {
  try {
    await tool.execute("reject", params, undefined, {}, undefined);
    return "";
  } catch (error) { return String(error); }
}
const base = { evidence_class: "test-witnessed", scope: "argument rejection probe" };
const rejections = {
  neither: await rejected({ claim_id: "X1", ...base }),
  both: await rejected({ claim_id: "X2", ...base, command: ["sh", "-c", "true"],
                         executions: [{ tool: "kani", command: ["sh", "-c", "true"] }] }),
  emptyCohort: await rejected({ claim_id: "X3", ...base, executions: [] }),
  duplicateTool: await rejected({ claim_id: "X4", ...base, executions: [
    { tool: "kani", command: ["sh", "-c", "true"] },
    { tool: "kani", command: ["sh", "-c", "true"] }] }),
  malformedArgv: await rejected({ claim_id: "X5", ...base,
                                  executions: [{ tool: "kani", command: [] }] }),
  blankArgvElement: await rejected({ claim_id: "X6", ...base,
                                     executions: [{ tool: "kani", command: ["sh", ""] }] }),
  malformedTool: await rejected({ claim_id: "X7", ...base,
                                  executions: [{ tool: "cargo kani", command: ["sh", "-c", "true"] }] }),
  topLevelCwd: await rejected({ claim_id: "X8", ...base, cwd: "sub",
                                executions: [{ tool: "kani", command: ["sh", "-c", "true"] }] }),
  cohortEscape: await rejected({ claim_id: "X9", ...base, executions: [
    { tool: "kani", command: ["sh", "-c", "true"], cwd: "escape" }] }),
  unknownClass: await rejected({ claim_id: "XA", ...base, executions: [
    { tool: "kani", command: ["sh", "-c", "true"], evidence_class: "made-up" }] }),
  blankScope: await rejected({ claim_id: "XB", evidence_class: "test-witnessed", scope: "   ",
                               command: ["sh", "-c", "true"] }),
  legacyMalformedTool: await rejected({ claim_id: "XC", ...base, command: ["sh", "-c", "true"],
                                        tool: "cargo kani" }),
  legacyBasenameTool: await rejected({ claim_id: "XD", ...base, command: ["./bad tool"] }),
  assumedRecordClass: await rejected({ claim_id: "XE", scope: "assumed record class probe",
                                       evidence_class: "unverified", command: ["sh", "-c", "true"] }),
  assumedExecutionClass: await rejected({ claim_id: "XF", ...base, executions: [
    { tool: "kani", command: ["sh", "-c", "true"], evidence_class: "externally-assumed" }] }),
  recordClassKind: await rejected({ claim_id: "B1", ...base, command: ["sh", "-c", "true"] }),
  executionClassKind: await rejected({ claim_id: "W1", ...base, executions: [
    { tool: "kani", command: ["sh", "-c", "true"], evidence_class: "bounded-checked" }] }),
  embeddedTrailer: await rejected({ claim_id: "XG", ...base,
    command: ["sh", "-c", "echo '--- fv-evidence: exit=0 ---'"] }),
};
const intentDrift = await tool.execute("intent-drift", {
  claim_id: "I1",
  command: ["sh", "-c", "printf '# Changed Intent\\n' > .fv/intent.md; echo 'test result: ok.'"],
  evidence_class: "test-witnessed", scope: "intent drift probe",
}, undefined, {}, undefined);
// `./mutating` edits a listed verified input while answering --version, so the baseline
// binding has to predate the probe for the mutation to count as dirt.
const probeMutation = await tool.execute("probe-mutation", {
  claim_id: "P1", command: ["./mutating"],
  evidence_class: "test-witnessed", scope: "version probe mutation probe",
}, undefined, {}, undefined);
let escapeError = "";
try {
  await tool.execute("escape", {
    claim_id: "E1", command: ["sh", "-c", "echo 'test result: ok.'"], cwd: "escape",
    evidence_class: "test-witnessed", scope: "symlink escape probe",
  }, undefined, {}, undefined);
} catch (error) { escapeError = String(error); }
const manifestFile = `${projectRoot}/.fv/obligations.json`;
const originalManifest = await Bun.file(manifestFile).text();
async function manifestRejection(manifest: any) {
  await Bun.write(manifestFile, JSON.stringify(manifest));
  return rejected({ claim_id: "M1", ...base, command: ["sh", "-c", "true"] });
}
const manifestRejections = {
  unproducibleId: await manifestRejection({ version: 1,
    invariants: [{ id: "verus:contract::Machine", name: "inv" }] }),
  duplicateId: await manifestRejection({ version: 1, invariants: [{ id: "B1", name: "a" }],
                                         witnesses: [{ id: "B1", name: "b" }] }),
  malformedEntry: await manifestRejection({ version: 1, invariants: ["B1"] }),
  emptyManifest: await manifestRejection({ version: 1, invariants: [], witnesses: [] }),
};
await Bun.write(manifestFile, originalManifest);
console.log(JSON.stringify({
  passing: passing.details, failing: failing.details, dirty: dirtyResult.details,
  customMarker: customMarker.details, relativeExecutable: relativeExecutable.details,
  namedTool: namedTool.details, intentDrift: intentDrift.details, escapeError,
  cohort: cohort.details, cohortFailure: cohortFailure.details, rejections,
  probeMutation: probeMutation.details, manifestRejections,
}));
"""

# Real repository: canonical target resolution against a declared external
# target_spec, and snapshot stability across committing the evidence itself.
SNAPSHOT_HARNESS = PRELUDE + r"""
const api: any = { cwd: projectRoot, zod, exec: realExec };
const tool = await mod.default(api);
function git(...args: string[]) {
  const done = Bun.spawnSync(["git", ...args], { cwd: projectRoot });
  if (!done.success) throw new Error(`git ${args.join(" ")}: ${new TextDecoder().decode(done.stderr)}`);
}
async function probe(claim: string) {
  const run = await tool.execute(claim, {
    claim_id: claim,
    command: ["sh", "-c", "echo 'test result: ok.'"],
    evidence_class: "test-witnessed",
    scope: "verified-input snapshot probe",
  }, undefined, {}, undefined);
  return run.details.record;
}
const first = await probe("EXT1");
git("add", "-A");
git("commit", "-qm", "commit the evidence the producer just wrote");
const afterEvidenceCommit = await probe("EXT2");
await Bun.write(`${projectRoot}/.fv/verify/2026-09-15.md`, "generated pyramid report\n");
await Bun.write(`${projectRoot}/build/out.bin`, "generated build artifact\n");
const afterExcludedOutput = await probe("EXT3");
// Quarantined legacy history is a structural exclusion, so pulling it into the worktree
// must neither dirty the tree nor move the snapshot live evidence binds to.
await Bun.write(`${projectRoot}/.fv/history/colosseum/legacy-record.json`, "{}\n");
const afterQuarantinedHistory = await probe("EXT4");
const inputsFile = `${projectRoot}/.fv/verified-inputs.txt`;
const originalInputs = await Bun.file(inputsFile).text();
// Only the list itself is committed, so the untracked build output stays untracked: if a
// list revision stopped excluding build/, that output would show up as dirt.
async function relistExcluded(claim: string, list: string) {
  await Bun.write(inputsFile, list);
  git("add", ".fv/verified-inputs.txt");
  git("commit", "-qm", `exclusion list for ${claim}`);
  try {
    return { error: "", record: await probe(claim) };
  } catch (error) { return { error: String(error), record: null }; }
}
// CRLF is the one non-LF terminator both parsers agree on, and the padding characters
// str.strip removes have to come off in the producer too, or the two ends exclude
// different prefixes from the same list. U+00A0 is padding both strip; the control
// characters str.strip also removes are rejected outright instead.
const afterCrlfList = await relistExcluded("EXT5", "# project-generated output\r\nbuild/\r\n");
const afterPaddedList = await relistExcluded("EXT6", "# project-generated output\nbuild/\u00a0\n");
// A bare CR is a line break to str.splitlines and not to split("\n"), so the two
// implementations would hash different file sets. Both refuse the list instead.
const ambiguous = await relistExcluded("EXT7", "# project-generated output\nbuild/\rdocs/\n");
// A leading BOM is dropped by this runtime's decode and kept by Python's, so silently
// accepting it would exclude build/ here and hash it in the gate, reported only as a
// stale record. The producer reads the list with ignoreBOM and refuses it.
const bomList = await relistExcluded("EXT8", "\ufeff# project-generated output\nbuild/\n");
await Bun.write(inputsFile, originalInputs);
git("add", ".fv/verified-inputs.txt");
git("commit", "-qm", "restore exclusion list");
console.log(JSON.stringify({
  first, afterEvidenceCommit, afterExcludedOutput, afterQuarantinedHistory,
  afterCrlfList, afterPaddedList, ambiguousList: ambiguous.error, bomList: bomList.error,
}));
"""

# Real repository: target-resolution rejections, dirty verified inputs, and
# symlinked verified inputs. Every probe commits its dispatch change first so a
# successful probe still runs against a clean tree.
RESOLUTION_HARNESS = PRELUDE + r"""
const api: any = { cwd: projectRoot, zod, exec: realExec };
const tool = await mod.default(api);
function git(...args: string[]) {
  const done = Bun.spawnSync(["git", ...args], { cwd: projectRoot });
  if (!done.success) throw new Error(`git ${args.join(" ")}: ${new TextDecoder().decode(done.stderr)}`);
}
async function probeCurrent(claim: string, scope: string) {
  try {
    const run = await tool.execute(claim, {
      claim_id: claim,
      command: ["sh", "-c", "echo 'test result: ok.'"],
      evidence_class: "test-witnessed",
      scope,
    }, undefined, {}, undefined);
    return { error: "", record: run.details.record };
  } catch (error) {
    return { error: String(error), record: null };
  }
}
async function writeDispatch(spec: string | null) {
  const route: any = { project_root: "." };
  if (spec !== null) route.target_spec = spec;
  await Bun.write(`${projectRoot}/.fv/dispatch.json`, JSON.stringify({ omp_native: route }, null, 2) + "\n");
}
async function attempt(claim: string, spec: string | null) {
  await writeDispatch(spec);
  git("add", "-A");
  git("commit", "-qm", `dispatch ${claim}`);
  return probeCurrent(claim, "canonical target probe");
}
// An absolute target_spec is compared against the resolved project root, so the
// declaration has to name the resolved path (/private/... on macOS).
const absoluteInside = await attempt("ABS1", `${realpathSync(projectRoot)}/docs/intent.md`);
const missing = await attempt("MIS1", "docs/nope.md");
const defaulted = await attempt("DEF1", null);
const directory = await attempt("DIR1", "docs");
const escaping = await attempt("ESC1", "../outside.md");
const tilde = await attempt("TIL1", "~/intent.md");
const clean = await attempt("CLN1", "docs/intent.md");
await Bun.write(`${projectRoot}/src.txt`, "modified outside the evidence run\n");
const dirtyVerified = await probeCurrent("DRT1", "dirty verified input probe");
git("checkout", "--", "src.txt");
// A tracked path whose worktree entry is a FIFO is still a candidate: reading it would
// block forever, so it has to be classified before any digest is taken.
const fifo = Bun.spawnSync(["sh", "-c", "rm -f src.txt && mkfifo src.txt"], { cwd: projectRoot });
if (!fifo.success) throw new Error("mkfifo failed");
const fifoInput = await probeCurrent("FIF1", "non-regular verified input probe");
Bun.spawnSync(["sh", "-c", "rm -f src.txt"], { cwd: projectRoot });
await Bun.write(`${projectRoot}/src.txt`, "clean\n");
symlinkSync(`${projectRoot}/docs/intent.md`, `${projectRoot}/docs/link.md`);
const symlinkTarget = await attempt("SYM1", "docs/link.md");
unlinkSync(`${projectRoot}/docs/link.md`);
await writeDispatch("docs/intent.md");
symlinkSync("../outside.md", `${projectRoot}/linked.md`);
const symlinkInput = await probeCurrent("LNK1", "symlinked verified input probe");
console.log(JSON.stringify({
  absoluteInside, missing, defaulted, directory, escaping, tilde,
  clean, dirtyVerified, fifoInput, symlinkTarget, symlinkInput,
}));
"""

# One rule for `.fv/verified-inputs.txt`, two implementations that must agree
# character by character: `fv_project.load_exclusions` (what Gate B hashes with) and
# `loadExclusions` in tools/evidence-run.ts (what the producer hashes with). A fixture
# either side reads differently is a silent snapshot split that surfaces only as
# "stale record", with nothing naming the parse, so the payloads are declared as bytes
# here and replayed verbatim on both sides. LF and CRLF separate entries; every other
# control character, and a byte-order mark anywhere in the file, is rejected; every
# other Unicode character is a legal path character.
EXCLUSION_FIXTURES: tuple[tuple[str, bytes, str], ...] = (
    ("lf-separated entries", b"build/\nlogs/\n", "accept"),
    ("crlf-separated entries", b"build/\r\nlogs/\r\n", "accept"),
    ("crlf and lf mixed", b"build/\r\nlogs/\n", "accept"),
    ("no trailing newline", b"build/", "accept"),
    ("comments, blank lines, ./ prefix, ascii padding", b"# generated\n\n  ./build/  \n", "accept"),
    ("unicode whitespace padding", "\u00a0build/\u3000\n".encode(), "accept"),
    ("non-ascii path entry", "caf\u00e9/\u65e5\u672c\u8a9e/\n".encode(), "accept"),
    # Not a control and not a BOM: kept verbatim by both, so it excludes exactly the
    # path that carries it. Pins the boundary of the rule.
    ("zero-width format character", "build\u200b/\n".encode(), "accept"),
    ("leading byte-order mark", "\ufeffbuild/\n".encode(), "reject"),
    ("byte-order mark on a comment line", "\ufeff# generated\nbuild/\n".encode(), "reject"),
    ("interior byte-order mark", "build/\n\ufefflogs/\n".encode(), "reject"),
    ("bare carriage return", b"build/\rlogs/\n", "reject"),
    ("vertical tab", b"build/\x0b\n", "reject"),
    ("form feed", b"build/\x0c\n", "reject"),
    ("file separator", b"build/\x1c\n", "reject"),
    ("group separator", b"build/\x1d\n", "reject"),
    ("record separator", b"build/\x1e\n", "reject"),
    ("unit separator", b"build/\x1f\n", "reject"),
    ("next line", "build/\u0085\n".encode(), "reject"),
    ("line separator", "build/\u2028\n".encode(), "reject"),
    ("paragraph separator", "build/\u2029\n".encode(), "reject"),
    ("tab inside an entry", b"bu\tild/\n", "reject"),
    ("leading tab", b"\tbuild/\n", "reject"),
    ("nul", b"build/\x00\n", "reject"),
    ("delete", b"build/\x7f\n", "reject"),
    ("c1 control", "build/\u009f\n".encode(), "reject"),
    ("invalid utf-8", b"build/\xff\n", "reject"),
    ("absolute entry", b"/etc/\n", "reject"),
    ("parent escape", b"../outside/\n", "reject"),
    ("whole-project entry", b".\n", "reject"),
)

# Replays every fixture through the producer's own parser and reports what it derived.
EXCLUSION_HARNESS = PRELUDE + r"""
const fixtures = await Bun.file(`${projectRoot}/fixtures.json`).json();
const inputs = `${projectRoot}/.fv/verified-inputs.txt`;
const results: Record<string, unknown> = {};
for (const fixture of fixtures) {
  await Bun.write(inputs, Buffer.from(fixture.hex, "hex"));
  try {
    results[fixture.label] = { ok: true, prefixes: await mod.loadExclusions(projectRoot), error: "" };
  } catch (error) {
    results[fixture.label] = { ok: false, prefixes: null, error: String(error) };
  }
}
console.log(JSON.stringify(results));
"""


def check(label: str, condition: bool, detail: object = "") -> None:
    if condition:
        print(f"  [ok]   {label}")
    else:
        print(f"  [FAIL] {label}" + (f" ({detail})" if detail else ""))
        FAILURES.append(label)


def gate(record: Path, root: Path, required: str, manifest: Path | None = None) -> subprocess.CompletedProcess:
    command = ["python3", str(GATE), "--records", str(record), "--root", str(root),
               "--allow-unbound", "--json"]
    if manifest:
        command += ["--manifest", str(manifest)]
    if required:
        command += ["--require", required]
    return subprocess.run(command, capture_output=True, text=True)


def git_repository(project: Path) -> None:
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    for key, value in (("user.email", "r34@example.test"), ("user.name", "R34"),
                       ("commit.gpgsign", "false")):
        subprocess.run(["git", "-C", str(project), "config", key, value], check=True)
    subprocess.run(["git", "-C", str(project), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(project), "commit", "-qm", "fixture"], check=True)


def run_harness(harness: Path, source: str, project: Path) -> dict:
    harness.write_text(source)
    run = subprocess.run(["bun", "run", str(harness), str(TOOL), str(project)],
                         capture_output=True, text=True, timeout=180)
    lines = run.stdout.strip().splitlines()
    check(f"{harness.stem} executes under Bun", run.returncode == 0 and bool(lines), run.stderr)
    return json.loads(lines[-1]) if lines else {}


def check_exclusion_parity(temporary: Path) -> None:
    """Gate-side and producer-side exclusion parsing, fixture for fixture."""
    project = temporary / "exclusion-parity"
    (project / ".fv").mkdir(parents=True)
    (project / "fixtures.json").write_text(json.dumps(
        [{"label": label, "hex": payload.hex()} for label, payload, _ in EXCLUSION_FIXTURES]))
    listing = project / ".fv" / "verified-inputs.txt"
    gate: dict[str, dict] = {}
    for label, payload, _ in EXCLUSION_FIXTURES:
        listing.write_bytes(payload)
        try:
            gate[label] = {"ok": True, "prefixes": fv_project.load_exclusions(project), "error": ""}
        except fv_project.ProjectError as error:
            gate[label] = {"ok": False, "prefixes": None, "error": str(error)}
    producer = run_harness(temporary / "exclusion-harness.ts", EXCLUSION_HARNESS, project)

    check("exclusion parity: the producer reports a verdict for every fixture",
          set(producer) == {label for label, _, _ in EXCLUSION_FIXTURES},
          sorted(set(label for label, _, _ in EXCLUSION_FIXTURES) ^ set(producer)))
    misjudged = [label for label, _, expect in EXCLUSION_FIXTURES
                 if gate[label]["ok"] != (expect == "accept")]
    check("exclusion parity: Gate B's parser lands on every fixture's declared verdict",
          not misjudged, [(label, gate[label]["error"]) for label in misjudged])
    divergent = [label for label, _, _ in EXCLUSION_FIXTURES
                 if producer.get(label, {}).get("ok") != gate[label]["ok"]]
    check("exclusion parity: producer and gate accept and reject the same fixtures",
          not divergent,
          [(label, gate[label]["error"], producer.get(label, {}).get("error")) for label in divergent])
    unequal = [label for label, _, expect in EXCLUSION_FIXTURES if expect == "accept"
               and producer.get(label, {}).get("prefixes") != gate[label]["prefixes"]]
    check("exclusion parity: an accepted list yields one exclusion set on both sides",
          not unequal,
          [(label, gate[label]["prefixes"], producer.get(label, {}).get("prefixes")) for label in unequal])
    # The rejection has to name the cause: a BOM that only one side dropped used to
    # surface as an unexplained stale record, which is the whole reason for the rule.
    for label, fragment in (("leading byte-order mark", "byte-order mark U+FEFF"),
                            ("interior byte-order mark", "byte-order mark U+FEFF"),
                            ("tab inside an entry", "control character '\\t'"),
                            ("unit separator", "control character '\\x1f'"),
                            ("bare carriage return", "ambiguous line terminator '\\r'")):
        producer_error = str(producer.get(label, {}).get("error", ""))
        check(f"exclusion parity: both ends name the defect identically ({label})",
              fragment in gate[label]["error"] and fragment in producer_error,
              (gate[label]["error"], producer_error))
    check("exclusion parity: the frozen defaults are identical on both sides",
          producer.get("lf-separated entries", {}).get("prefixes", [])[:len(fv_project.DEFAULT_EXCLUSIONS)]
          == list(fv_project.DEFAULT_EXCLUSIONS),
          producer.get("lf-separated entries"))


def external_target_project(temporary: Path) -> Path:
    """Repository whose canonical target lives outside .fv, with a project exclusion."""
    project = temporary / "external"
    (project / ".fv").mkdir(parents=True)
    (project / "docs").mkdir()
    (project / "docs" / "intent.md").write_text("# External Intent\n")
    (project / ".fv" / "dispatch.json").write_text(
        json.dumps({"omp_native": {"project_root": ".", "target_spec": "docs/intent.md"}}, indent=2) + "\n")
    (project / ".fv" / "obligations.json").write_text(json.dumps({
        "version": 1,
        "invariants": [],
        "witnesses": [{"id": "EXT1", "name": "witness_ext1"}],
    }))
    (project / ".fv" / "verified-inputs.txt").write_text("# project-generated output\nbuild/\n")
    (project / "src.txt").write_text("clean\n")
    (temporary / "outside.md").write_text("# Outside the project\n")
    git_repository(project)
    return project


def check_external_target(temporary: Path) -> None:
    project = external_target_project(temporary)
    intent = project / "docs" / "intent.md"
    manifest = project / ".fv" / "obligations.json"
    records = project / ".fv" / "evidence" / "records"
    result = run_harness(temporary / "snapshot-harness.ts", SNAPSHOT_HARNESS, project)
    first = result.get("first", {})
    bindings = first.get("bindings", {})
    check("declared external target_spec binds the repo-relative intent path",
          bindings.get("intent_path") == "docs/intent.md"
          and bindings.get("intent_hash") == hashlib.sha256(intent.read_bytes()).hexdigest(),
          bindings)
    check("producer emits the v3 record schema",
          bindings.get("parser_schema_version") == "fv-evidence-run/v3", bindings)
    check("source binding is a verified-input content snapshot, not a commit id",
          re.fullmatch(r"sha256:[0-9a-f]{64}", str(bindings.get("source_snapshot"))) is not None,
          bindings.get("source_snapshot"))
    executions = bindings.get("executions") or []
    check("single-command run records one execution cohort entry",
          len(executions) == 1
          and executions[0]["tool"] == "sh"
          and executions[0]["command"] == ["sh", "-c", "echo 'test result: ok.'"]
          and executions[0]["cwd"] == "."
          and executions[0]["result"] == "PASS"
          and executions[0]["raw_output_path"] == bindings.get("raw_output_path")
          and executions[0]["raw_output_hash"] == bindings.get("raw_output_hash")
          and executions[0]["run_id"] == bindings.get("run_id"),
          executions)
    committed = result.get("afterEvidenceCommit", {}).get("bindings", {})
    check("committing the produced evidence does not move the snapshot",
          committed.get("source_snapshot") == bindings.get("source_snapshot")
          and result["afterEvidenceCommit"]["result"] == "PASS",
          committed.get("source_snapshot"))
    excluded = result.get("afterExcludedOutput", {}).get("bindings", {})
    check("excluded generated output neither dirties nor moves the snapshot",
          excluded.get("source_snapshot") == bindings.get("source_snapshot")
          and result["afterExcludedOutput"]["result"] == "PASS",
          excluded.get("source_snapshot"))
    history = result.get("afterQuarantinedHistory", {}).get("bindings", {})
    check("quarantined .fv/history neither dirties nor moves the snapshot",
          history.get("source_snapshot") == bindings.get("source_snapshot")
          and result["afterQuarantinedHistory"]["result"] == "PASS",
          history.get("source_snapshot"))
    check("a CRLF exclusion list still parses, so build/ stays excluded",
          result.get("afterCrlfList", {}).get("record", {}).get("result") == "PASS",
          result.get("afterCrlfList"))
    check("an entry padded with str.strip whitespace still excludes build/",
          result.get("afterPaddedList", {}).get("record", {}).get("result") == "PASS",
          result.get("afterPaddedList"))
    check("a bare-CR exclusion list is refused instead of parsed two ways",
          "ambiguous line terminator '\\r'" in result.get("ambiguousList", ""),
          result.get("ambiguousList"))
    # The producer's runtime drops a leading BOM on decode and Gate B keeps it, so the
    # list has to be refused rather than read: otherwise the two ends exclude different
    # prefixes and every record reads "stale record" with no cause named.
    check("a BOM-prefixed exclusion list is refused rather than silently stripped",
          "byte-order mark U+FEFF" in result.get("bomList", ""),
          result.get("bomList"))

    fresh = subprocess.run(["python3", str(GATE), "--records", str(records / "EXT1.json"),
                            "--root", str(project), "--manifest", str(manifest), "--json"],
                           capture_output=True, text=True)
    check("Gate B accepts a committed v3 record under default freshness",
          fresh.returncode == 0, fresh.stdout + fresh.stderr)
    (project / "src.txt").write_text("drifted\n")
    stale = subprocess.run(["python3", str(GATE), "--records", str(records / "EXT1.json"),
                            "--root", str(project), "--manifest", str(manifest), "--json"],
                           capture_output=True, text=True)
    check("Gate B rejects a v3 record once a verified input changes",
          stale.returncode == 3 and "stale record" in stale.stdout, stale.stdout)
    (project / "src.txt").write_text("clean\n")

    resolution = run_harness(temporary / "resolution-harness.ts", RESOLUTION_HARNESS, project)
    absolute = resolution.get("absoluteInside", {})
    check("absolute target_spec inside the project root resolves repo-relative",
          absolute.get("record", {}).get("bindings", {}).get("intent_path") == "docs/intent.md"
          and absolute["record"]["result"] == "PASS", absolute)
    check("missing declared target rejected",
          "target_spec does not exist" in resolution.get("missing", {}).get("error", ""), resolution)
    check("absent target_spec falls back to .fv/intent.md",
          "target_spec does not exist: .fv/intent.md" in resolution.get("defaulted", {}).get("error", ""),
          resolution)
    check("directory target rejected",
          "target_spec is a directory" in resolution.get("directory", {}).get("error", ""), resolution)
    check("escaping target_spec rejected",
          "escapes project root" in resolution.get("escaping", {}).get("error", ""), resolution)
    check("symlinked target_spec rejected",
          "target_spec is a symlink" in resolution.get("symlinkTarget", {}).get("error", ""), resolution)
    check("tilde-prefixed target_spec rejected rather than expanded",
          "target_spec must not start with '~'" in resolution.get("tilde", {}).get("error", ""),
          resolution.get("tilde"))
    clean = resolution.get("clean", {}).get("record", {}) or {}
    check("restored relative target_spec produces PASS on a clean tree",
          clean.get("result") == "PASS"
          and clean.get("bindings", {}).get("intent_path") == "docs/intent.md"
          and re.fullmatch(r"sha256:[0-9a-f]{64}", str(clean.get("bindings", {}).get("source_snapshot"))) is not None,
          resolution.get("clean"))
    dirty_verified = resolution.get("dirtyVerified", {}).get("record", {}) or {}
    check("modified verified input cannot produce PASS evidence",
          dirty_verified.get("result") == "FAIL"
          and str(dirty_verified.get("bindings", {}).get("source_snapshot")).endswith("+dirty"),
          resolution.get("dirtyVerified"))
    check("non-regular verified input rejected instead of read",
          "verified input is not a regular file: src.txt" in resolution.get("fifoInput", {}).get("error", ""),
          resolution.get("fifoInput"))
    check("symlinked verified input rejected before evidence is written",
          "verified input is a symlink" in resolution.get("symlinkInput", {}).get("error", ""),
          resolution.get("symlinkInput"))


def main() -> int:
    if shutil.which("bun") is None:
        print("SKIP-FAIL: bun not on PATH")
        return 2
    if not RESOLVER.is_file():
        print(f"SKIP-FAIL: missing {RESOLVER}")
        return 2
    with tempfile.TemporaryDirectory(prefix="r34-") as temporary:
        root = Path(temporary) / "project"
        state = root / ".fv"
        state.mkdir(parents=True)
        (state / "intent.md").write_text("# Intent\n")
        manifest = state / "obligations.json"
        manifest.write_text(json.dumps({
            "version": 1,
            "invariants": [{"id": "B1", "name": "inv_b1"}],
            "witnesses": [{"id": "W1", "name": "witness_w1"}],
            "system_claims": [{"id": "S1", "statement": "the cohort composes",
                               "depends_on": ["B1", "W1"],
                               "required_evidence": ["kani", "verus"]}],
        }))
        outside = Path(temporary) / "outside"
        outside.mkdir()
        (root / "escape").symlink_to(outside, target_is_directory=True)
        root_probe = root / "probe"
        root_probe.write_text("#!/bin/sh\necho root-probe\n")
        root_probe.chmod(0o755)
        sub = root / "sub"
        sub.mkdir()
        sub_probe = sub / "probe"
        sub_probe.write_text(
            "#!/bin/sh\n"
            "if [ \"$1\" = \"--version\" ]; then echo sub-probe-v1; "
            "else echo 'test result: ok.'; fi\n"
        )
        sub_probe.chmod(0o755)
        # Answering --version mutates a listed verified input, which only registers as
        # dirt when the baseline binding predates the probe.
        mutating = root / "mutating"
        mutating.write_text(
            "#!/bin/sh\n"
            "if [ \"$1\" = \"--version\" ]; then printf 'probe-mutation\\n' >> probe; "
            "echo mutating-v1; else echo 'test result: ok.'; fi\n"
        )
        mutating.chmod(0o755)
        harness = root / "harness.ts"
        harness.write_text(HARNESS)
        run = subprocess.run(
            ["bun", "run", str(harness), str(TOOL), str(root)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        lines = run.stdout.strip().splitlines()
        check("evidence tool executes under Bun", run.returncode == 0 and bool(lines), run.stderr)
        result = json.loads(lines[-1]) if lines else {}
        passing_path = state / "evidence" / "records" / "W1.json"
        failing_path = state / "evidence" / "records" / "B1.json"
        check("passing record persisted", passing_path.is_file())
        check("failing record persisted", failing_path.is_file())
        passing = json.loads(passing_path.read_text())
        failing = json.loads(failing_path.read_text())
        check("producer marks matching exit-zero probe PASS", passing["result"] == "PASS", result)
        check("default canonical target is .fv/intent.md",
              passing["bindings"]["intent_path"] == ".fv/intent.md", passing["bindings"])
        check("dirty source cannot produce PASS evidence",
              result.get("dirty", {}).get("record", {}).get("result") == "FAIL", result)
        check("custom pass marker replaces the evidence-class marker",
              result.get("customMarker", {}).get("record", {}).get("result") == "PASS", result)
        check("intent drift during execution cannot produce PASS evidence",
              result.get("intentDrift", {}).get("record", {}).get("result") == "FAIL", result)
        check("intent drift during execution moves the verified-input snapshot",
              str(result.get("intentDrift", {}).get("record", {})
                  .get("bindings", {}).get("source_snapshot")).endswith("+dirty"), result)
        check("declared evidence tool overrides the executable basename",
              result.get("namedTool", {}).get("record", {})
              .get("bindings", {}).get("executions", [{}])[0].get("tool") == "quint", result)
        check("producer records resolved executable identity",
              set(passing["bindings"]["toolchain_digests"]) ==
              {"executable", "sha256", "version", "version_exit_code"}, passing)
        relative_binding = result["relativeExecutable"]["record"]["bindings"]["toolchain_digests"]
        check("relative command executes the same binary whose digest is recorded",
              relative_binding["executable"] == str(sub_probe.resolve())
              and result["relativeExecutable"]["record"]["result"] == "PASS", relative_binding)
        custom_path = state / "evidence" / "records" / "C1.json"
        custom_checked = gate(custom_path, root, "C1")
        check("Gate B accepts a produced custom-marker PASS record",
              custom_checked.returncode == 0, custom_checked.stdout + custom_checked.stderr)
        check("cwd symlink escape rejected before execution",
              "inside the project root" in result.get("escapeError", ""), result)
        check("producer marks nonzero probe FAIL", failing["result"] == "FAIL", result)
        valid = gate(passing_path, root, "W1")
        check("Gate B accepts produced PASS record", valid.returncode == 0, valid.stdout + valid.stderr)
        failed = gate(failing_path, root, "B1")
        check("Gate B reports produced failing probe", failed.returncode == 1 and "FAILED" in failed.stdout, failed.stdout)

        run_id = passing["bindings"]["run_id"]

        def mutation(name: str, mutated_run_id: str, digest: str, marker: str = "") -> Path:
            """Rebind the record's artifact, legacy fields and sole execution together.

            Rebinding all three keeps each probe isolated to one property instead of
            tripping the legacy-derivation check, and a producer artifact is named
            `<claim_id>-<run_id>.log`, so swapping the artifact swaps the run id with it
            or the artifact-naming check fires first.
            """
            record = json.loads(passing_path.read_text())
            binding = record["bindings"]
            execution = binding["executions"][0]
            relative = f".fv/evidence/raw/W1-{mutated_run_id}.log"
            binding["raw_output_path"] = execution["raw_output_path"] = relative
            binding["raw_output_hash"] = execution["raw_output_hash"] = digest
            binding["run_id"] = execution["run_id"] = mutated_run_id
            if marker:
                binding["configuration"]["pass_marker"] = execution["pass_marker"] = marker
            path = root / f"{name}.json"
            path.write_text(json.dumps(record))
            return path

        checked = gate(mutation("missing", "does-not-exist", "0" * 64), root, "W1")
        check("missing raw artifact rejected",
              checked.returncode == 3 and "unresolvable raw artifact" in checked.stdout, checked.stdout)

        checked = gate(mutation("wrong-hash", run_id, "0" * 64), root, "W1")
        check("wrong raw hash rejected",
              checked.returncode == 3 and "raw output hash mismatch" in checked.stdout, checked.stdout)

        marker_raw = state / "evidence" / "raw" / "W1-marker-absent.log"
        marker_raw.write_text("command completed\n--- fv-evidence: exit=0 ---\n")
        checked = gate(mutation("marker-absent", "marker-absent",
                                hashlib.sha256(marker_raw.read_bytes()).hexdigest()), root, "W1")
        check("missing class marker rejected",
              checked.returncode == 3 and "PASS marker absent" in checked.stdout, checked.stdout)

        exit_raw = state / "evidence" / "raw" / "W1-forged-exit.log"
        exit_raw.write_text("test result: ok.\n--- fv-evidence: exit=7 ---\n")
        checked = gate(mutation("forged-exit", "forged-exit",
                                hashlib.sha256(exit_raw.read_bytes()).hexdigest(), marker=".*"),
                       root, "W1")
        check("record-controlled regex cannot mask nonzero exit",
              checked.returncode == 3 and "canonical exit=0 trailer" in checked.stdout,
              checked.stdout)

        conflicting_raw = state / "evidence" / "raw" / "W1-conflicting-exit.log"
        conflicting_raw.write_text("test result: ok.\n--- fv-evidence: exit=7 ---\n--- fv-evidence: exit=0 ---\n")
        checked = gate(mutation("conflicting-exit", "conflicting-exit",
                                hashlib.sha256(conflicting_raw.read_bytes()).hexdigest()), root, "W1")
        check("conflicting exit trailers rejected",
              checked.returncode == 3 and "one unique canonical exit=0 trailer" in checked.stdout,
              checked.stdout)

        incompatible = json.loads(passing_path.read_text())
        incompatible["claim_id"] = "B1"
        incompatible_path = root / "incompatible.json"
        incompatible_path.write_text(json.dumps(incompatible))
        checked = gate(incompatible_path, root, "", manifest)
        check("incompatible obligation class rejected", "incompatible evidence class" in checked.stdout, checked.stdout)

        check("legacy single-command record still carries exactly one execution",
              len(passing["bindings"]["executions"]) == 1
              and json.loads(passing["bindings"]["command"])
              == passing["bindings"]["executions"][0]["command"]
              and passing["bindings"]["executions"][0]["run_id"] == passing["bindings"]["run_id"],
              passing["bindings"])

        cohort_path = state / "evidence" / "records" / "S1.json"
        cohort_record = json.loads(cohort_path.read_text())
        cohort_bindings = cohort_record["bindings"]
        executions = cohort_bindings["executions"]
        check("cohort run records one execution per requested command",
              cohort_record["result"] == "PASS"
              and [execution["tool"] for execution in executions] == ["kani", "verus"]
              and [execution["result"] for execution in executions] == ["PASS", "PASS"]
              and [execution["evidence_class"] for execution in executions]
              == ["bounded-checked", "proof-discharged"], executions)
        check("each cohort execution persists its own hash-bound raw artifact",
              len({execution["raw_output_path"] for execution in executions}) == 2
              and len({execution["run_id"] for execution in executions}) == 2
              and all((root / execution["raw_output_path"]).is_file() for execution in executions)
              and all(hashlib.sha256((root / execution["raw_output_path"]).read_bytes()).hexdigest()
                      == execution["raw_output_hash"] for execution in executions),
              [execution["raw_output_path"] for execution in executions])
        check("cohort legacy bindings are derived from the first execution",
              json.loads(cohort_bindings["command"]) == executions[0]["command"]
              and cohort_bindings["raw_output_path"] == executions[0]["raw_output_path"]
              and cohort_bindings["raw_output_hash"] == executions[0]["raw_output_hash"]
              and cohort_bindings["toolchain_digests"] == executions[0]["toolchain_digests"]
              and cohort_bindings["configuration"]["cwd"] == executions[0]["cwd"], cohort_bindings)
        # Requiring a system claim now requires its dependencies too, and this fixture's
        # dependency records are the failing and passing single-command probes, so the
        # claim under test is read from its own row rather than from the run's exit code.
        cohort_checked = gate(cohort_path, root, "S1", manifest)
        cohort_rows = json.loads(cohort_checked.stdout).get("per_claim", [])
        cohort_row = next((row for row in cohort_rows if row.get("claim_id") == "S1"), {})
        check("Gate B accepts a cohort covering every required_evidence tool",
              cohort_row.get("status") == "PASS" and not cohort_row.get("defects"),
              cohort_checked.stdout + cohort_checked.stderr)

        failure_record = json.loads((state / "evidence" / "records" / "S2.json").read_text())
        check("one failing execution fails the whole cohort record",
              failure_record["result"] == "FAIL"
              and [execution["result"] for execution
                   in failure_record["bindings"]["executions"]] == ["PASS", "FAIL"],
              failure_record)

        def cohort_mutation(name: str, mutate) -> subprocess.CompletedProcess:
            record = json.loads(cohort_path.read_text())
            mutate(record)
            path = root / f"cohort-{name}.json"
            path.write_text(json.dumps(record))
            return gate(path, root, "S1", manifest)

        checked = cohort_mutation("missing-tool", lambda record: record["bindings"]["executions"].pop(1))
        check("cohort missing a required tool cannot discharge the system claim",
              checked.returncode == 3
              and "missing PASS evidence from required tools ['verus']" in checked.stdout,
              checked.stdout)
        checked = cohort_mutation("duplicate-tool",
                                  lambda record: record["bindings"]["executions"][1].update(tool="kani"))
        check("duplicate cohort tool ids rejected as ambiguous coverage",
              checked.returncode == 3 and "duplicate evidence tool 'kani'" in checked.stdout,
              checked.stdout)
        checked = cohort_mutation("cwd-escape",
                                  lambda record: record["bindings"]["executions"][1].update(cwd="../outside"))
        check("cohort execution cwd outside the repository rejected",
              checked.returncode == 3 and "executions[1] cwd escapes repository root" in checked.stdout,
              checked.stdout)
        checked = cohort_mutation(
            "malformed-argv",
            lambda record: record["bindings"]["executions"][1].update(command="sh -c true"))
        check("cohort execution with a shell string instead of argv rejected",
              checked.returncode == 3
              and "executions[1] command is not a nonempty argv array" in checked.stdout,
              checked.stdout)
        checked = cohort_mutation(
            "forged-pass",
            lambda record: record["bindings"]["executions"][1].update(result="FAIL"))
        check("a FAIL execution cannot hide beneath a PASS cohort record",
              checked.returncode == 3
              and "cannot appear beneath a PASS record" in checked.stdout, checked.stdout)

        second_raw = root / executions[1]["raw_output_path"]
        original_raw = second_raw.read_bytes()
        second_raw.write_text(
            "forged verus proof\nVERIFICATION:- SUCCESSFUL\n--- fv-evidence: exit=0 ---\n")
        checked = gate(cohort_path, root, "S1", manifest)
        check("tampering with a later cohort artifact is caught",
              checked.returncode == 3
              and "executions[1] raw output hash mismatch" in checked.stdout, checked.stdout)
        second_raw.write_bytes(original_raw)

        rejections = result.get("rejections", {})
        for label, key, fragment in (
            ("neither command nor executions", "neither", "exactly one of command or executions"),
            ("both command and executions", "both", "exactly one of command or executions"),
            ("an empty executions array", "emptyCohort", "executions must be a non-empty array"),
            ("a duplicate cohort tool", "duplicateTool", "duplicates 'kani'"),
            ("an empty cohort argv", "malformedArgv", "command must contain non-empty argv elements"),
            ("a blank cohort argv element", "blankArgvElement",
             "command must contain non-empty argv elements"),
            ("a malformed cohort tool id", "malformedTool", "must be an evidence tool identifier"),
            ("top-level cwd beside executions", "topLevelCwd", "per-execution when executions is used"),
            ("a cohort cwd escaping the project root", "cohortEscape", "inside the project root"),
            ("an unknown per-execution evidence class", "unknownClass", "evidence_class is unknown"),
            ("a blank scope", "blankScope", "scope must describe what the evidence covers"),
            ("a malformed declared tool id", "legacyMalformedTool",
             "tool must be an evidence tool identifier"),
            ("a malformed tool id derived from the executable basename", "legacyBasenameTool",
             "tool must be an evidence tool identifier"),
            ("an assumed record evidence class it cannot waive", "assumedRecordClass",
             "evidence_class 'unverified' cannot be produced"),
            ("an assumed per-execution evidence class it cannot waive", "assumedExecutionClass",
             "executions[0].evidence_class 'externally-assumed' cannot be produced"),
            ("a record class incompatible with the obligation kind", "recordClassKind",
             "evidence_class 'test-witnessed' cannot discharge invariant 'B1'"),
            ("an execution class incompatible with the obligation kind", "executionClassKind",
             "executions[0].evidence_class 'bounded-checked' cannot discharge witness 'W1'"),
            ("output carrying the producer's own trailer sentinel", "embeddedTrailer",
             "printed a reserved '--- fv-evidence: exit=N ---' trailer line"),
        ):
            check(f"producer rejects {label}", fragment in rejections.get(key, ""),
                  rejections.get(key))

        probe_mutation = result.get("probeMutation", {}).get("record", {}) or {}
        check("a verified input mutated by a --version probe cannot produce PASS evidence",
              probe_mutation.get("result") == "FAIL"
              and str(probe_mutation.get("bindings", {}).get("source_snapshot")).endswith("+dirty"),
              result.get("probeMutation"))

        manifest_rejections = result.get("manifestRejections", {})
        for label, key, fragment in (
            ("an obligation id no record file could ever carry", "unproducibleId",
             "id \"verus:contract::Machine\" is not usable by the evidence producer"),
            ("a manifest with duplicate obligation ids", "duplicateId", "duplicates id 'B1'"),
            ("a manifest obligation entry that is not an object", "malformedEntry",
             "invariants[0] is not an object"),
            ("a manifest declaring no obligations", "emptyManifest", "has no targets"),
        ):
            check(f"producer rejects {label}", fragment in manifest_rejections.get(key, ""),
                  manifest_rejections.get(key))

        check_external_target(Path(temporary))
        check_exclusion_parity(Path(temporary))

    print()
    if FAILURES:
        print(f"R34: {len(FAILURES)} failure(s)")
        return 1
    print("R34: all assertions passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
