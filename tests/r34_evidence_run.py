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
const multiplexed = await tool.execute("multiplexed", {
  claim_id: "M2", command: ["./toolname"],
  evidence_class: "test-witnessed", scope: "argv[0] multiplexer probe",
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
  multiplexed: multiplexed.details,
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
// Lifecycle reports are written after the evidence they describe: a change record, an
// attack log, and a code-adversarial report all land once the run that produced the
// evidence is over. They are structural exclusions, so none of them can stale it.
await Bun.write(`${projectRoot}/.fv/changes/2026-09-15-change.md`, "change record\n");
await Bun.write(`${projectRoot}/.fv/attacks/attack-1.md`, "attack log\n");
await Bun.write(`${projectRoot}/.fv/code-adversarial/report-1.md`, "code-adversarial report\n");
const afterLifecycleReports = await probe("EXT9");
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
  afterLifecycleReports,
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

# The same differential duty for the *policy* layer: which mode a file declares, which
# entries it carries, and which candidates that selects. `fv_project.load_policy` and
# `loadInputPolicy` in tools/evidence-run.ts have to agree on all three, including the
# wording of every rejection: a mode one end reads as include and the other as exclude
# would hash two different input sets from one file and surface only as "stale record".
POLICY_FIXTURES: tuple[tuple[str, bytes, str], ...] = (
    # No directive is exclusion mode, which is what every list written before include
    # mode existed means; that compatibility is the whole reason the default is not
    # "declare a mode or be rejected".
    ("no directive stays exclusion mode", b"build/\nlogs/\n", "accept"),
    ("explicit exclude directive", b"mode: exclude\nbuild/\n", "accept"),
    ("include directive", b"mode: include\ncrates\nquint/\n", "accept"),
    ("include after comments and blanks", b"# scope\n\nmode: include\ncrates\n", "accept"),
    ("include with no space after the colon", b"mode:include\ncrates\n", "accept"),
    ("include with strippable padding", "mode:  include  \n crates \n".encode(), "accept"),
    ("include directive in mixed case prefix", b"MODE: include\ncrates\n", "accept"),
    ("include entry deduped after ./ stripping", b"mode: include\n./crates\ncrates\n", "accept"),
    ("include naming the policy file itself",
     b"mode: include\n.fv/verified-inputs.txt\ncrates\n", "accept"),
    ("include with non-ascii and astral entries",
     "mode: include\ncaf\u00e9/\n\U0001f600-astral.txt\n".encode(), "accept"),
    ("include across crlf", b"mode: include\r\ncrates\r\n", "accept"),
    # A comment is a comment even when it quotes a directive.
    ("commented-out directive", b"# mode: include\nbuild/\n", "accept"),
    # An allowlist may name the .fv tree; the structural exclusions still win inside it.
    ("include naming the whole .fv directory", b"mode: include\n.fv/\n", "accept"),
    ("empty include policy", b"mode: include\n", "reject"),
    ("include policy of comments only", b"# scope\nmode: include\n# nothing\n", "reject"),
    ("directive after an entry", b"build/\nmode: include\n", "reject"),
    ("second directive", b"mode: include\ncrates\nmode: exclude\n", "reject"),
    ("mode word in the wrong case", b"Mode: Include\ncrates\n", "reject"),
    ("unknown mode word", b"mode: allowlist\ncrates\n", "reject"),
    ("directive with no mode word", b"mode:\ncrates\n", "reject"),
    ("include entry selecting the whole project", b"mode: include\n.\n", "reject"),
    ("include entry that is absolute", b"mode: include\n/etc\n", "reject"),
    ("include entry that escapes the root", b"mode: include\n../outside\n", "reject"),
    # The character rules are the policy's rules, not the exclusion list's: they hold
    # above an include directive too.
    ("byte-order mark before an include directive",
     "\ufeffmode: include\ncrates\n".encode(), "reject"),
    ("bare carriage return under include mode", b"mode: include\ncrates\rquint\n", "reject"),
    ("tab inside an include entry", b"mode: include\ncra\ttes\n", "reject"),
    ("invalid utf-8 under include mode", b"mode: include\ncrates\xff\n", "reject"),
)

# Fixtures whose rejection text belongs to the UTF-8 decoder rather than to the policy
# grammar: Python names the offending byte and offset, this runtime says "Invalid byte
# sequence". Both refuse the file, which is the property that matters; the wording check
# below skips them rather than pinning one runtime's decoder message into the other.
RUNTIME_WORDED_REJECTIONS = frozenset({"invalid utf-8 under include mode"})

# Candidates every accepted policy is asked about, on both sides. The astral and
# private-use names are here because a path is not only ordered but *matched*, and the
# two runtimes index strings differently.
SELECTION_PROBES: tuple[str, ...] = (
    "crates/lib.rs",
    "crates",
    "cratesX/lib.rs",
    "quint/spec.qnt",
    "build/out.bin",
    "logs/run.txt",
    "README.md",
    ".fv/verified-inputs.txt",
    ".fv/intent.md",
    ".fv/evidence/records/W1.json",
    ".fv/changes/2026-09-15-change.md",
    ".fv/attacks/attack-1.md",
    ".fv/code-adversarial/report-1.md",
    ".fv/history/colosseum/ledger.md",
    "caf\u00e9/notes.md",
    "\U0001f600-astral.txt",
    "\ue000-pua.txt",
)

# Snapshot order is UTF-8 byte-wise on both sides. A JavaScript runtime's default string
# comparison is UTF-16 code-unit-wise, which sorts every astral-plane path ahead of
# U+E000..U+FFFF instead of behind it, so a repository holding both would hash to two
# snapshots with nothing naming the sort. These paths make the two orders differ.
ORDER_PROBES: tuple[str, ...] = (
    "a.txt",
    "crates/lib.rs",
    "\ue000-pua.txt",
    "\ufffd-replacement.txt",
    "\U000103a0-old-persian.txt",
    "\U0001f600-astral.txt",
    "caf\u00e9.txt",
)

# The include-mode fixture repository: an allowlist whose entries include a private-use
# and an astral-plane filename, so the end-to-end snapshot comparison exercises the
# ordering rule on real files rather than on a list of strings.
ASTRAL_INPUT = "\U0001f600-astral.txt"
PUA_INPUT = "\ue000-pua.txt"
INCLUDE_POLICY = (
    "# Verified-input policy: an allowlist, deliberately.\n"
    "mode: include\n"
    ".fv/intent.md\n"
    ".fv/obligations.json\n"
    "crates/\n"
    f"{ASTRAL_INPUT}\n"
    f"{PUA_INPUT}\n"
)

# Replays every policy fixture through the producer's own loader, answers the selection
# probes with what it derived, and reports both orderings of the ordering probes.
POLICY_HARNESS = PRELUDE + r"""
const { fixtures, probes, order } = await Bun.file(`${projectRoot}/policy-fixtures.json`).json();
const inputs = `${projectRoot}/.fv/verified-inputs.txt`;
const policies: Record<string, unknown> = {};
for (const fixture of fixtures) {
  await Bun.write(inputs, Buffer.from(fixture.hex, "hex"));
  try {
    const policy = await mod.loadInputPolicy(projectRoot);
    const selects: Record<string, boolean> = {};
    for (const probe of probes) selects[probe] = mod.policySelects(probe, policy);
    policies[fixture.label] = {
      ok: true, mode: policy.mode, prefixes: policy.prefixes,
      selectors: mod.policySelectors(policy), exclusions: mod.policyExclusions(policy),
      selects, error: "",
    };
  } catch (error) {
    policies[fixture.label] = { ok: false, mode: "", prefixes: null, selectors: null,
                                exclusions: null, selects: null, error: String(error) };
  }
}
console.log(JSON.stringify({
  policies,
  order: { utf8: mod.orderVerifiedInputs(order), codeUnit: [...order].sort() },
}));
"""

# Real repository under an include policy: what the allowlist selects, what it refuses to
# let a later write disturb, and what a revision of the allowlist itself does.
INCLUDE_HARNESS = PRELUDE + r"""
const api: any = { cwd: projectRoot, zod, exec: realExec };
const tool = await mod.default(api);
function git(...args: string[]) {
  const done = Bun.spawnSync(["git", ...args], { cwd: projectRoot });
  if (!done.success) throw new Error(`git ${args.join(" ")}: ${new TextDecoder().decode(done.stderr)}`);
}
async function probe(claim: string, scope: string) {
  try {
    const run = await tool.execute(claim, {
      claim_id: claim,
      command: ["sh", "-c", "echo 'test result: ok.'"],
      evidence_class: "test-witnessed",
      scope,
    }, undefined, {}, undefined);
    return { error: "", record: run.details.record };
  } catch (error) { return { error: String(error), record: null }; }
}
const inputsFile = `${projectRoot}/.fv/verified-inputs.txt`;
const originalPolicy = await Bun.file(inputsFile).text();
const first = await probe("INC1", "include-policy snapshot probe");
// A file no allowlist entry names is not a verified input, so editing it neither dirties
// the tree nor moves the snapshot live evidence binds to.
await Bun.write(`${projectRoot}/docs/scratch.md`, "edited outside the allowlist\n");
const afterUnlisted = await probe("INC2", "unlisted path probe");
// Lifecycle reports are written *after* the evidence they describe. They are structural
// exclusions in both modes, so writing a change record, an attack log, or a
// code-adversarial report cannot stale the run that produced them.
await Bun.write(`${projectRoot}/.fv/changes/2026-09-15-change.md`, "change record\n");
await Bun.write(`${projectRoot}/.fv/attacks/attack-1.md`, "attack log\n");
await Bun.write(`${projectRoot}/.fv/code-adversarial/report-1.md`, "code-adversarial report\n");
const afterLifecycle = await probe("INC3", "lifecycle report probe");
git("add", "-A");
git("commit", "-qm", "commit the evidence and the lifecycle reports it produced");
const afterCommit = await probe("INC4", "committed lifecycle output probe");
// An allowlisted input changing is exactly what has to move the snapshot.
await Bun.write(`${projectRoot}/crates/lib.rs`, "pub const N: u8 = 2;\n");
git("add", "-A");
git("commit", "-qm", "edit an allowlisted input");
const afterIncludedEdit = await probe("INC5", "allowlisted input edit probe");
// A new file under an allowlisted directory is an uncommitted verified input: dirt.
await Bun.write(`${projectRoot}/crates/extra.rs`, "pub const M: u8 = 3;\n");
const withNewIncluded = await probe("INC6", "new allowlisted input probe");
git("add", "-A");
git("commit", "-qm", "commit the new allowlisted input");
const afterNewIncluded = await probe("INC7", "committed new allowlisted input probe");
// The policy file selects itself, so widening the allowlist invalidates the evidence
// bound to the narrower one instead of silently re-scoping what it covered.
await Bun.write(inputsFile, originalPolicy + "docs/\n");
git("add", "-A");
git("commit", "-qm", "widen the allowlist");
const afterPolicyChange = await probe("INC8", "widened allowlist probe");
// An allowlist naming nothing would bind evidence to the policy file alone.
await Bun.write(inputsFile, "mode: include\n");
git("add", "-A");
git("commit", "-qm", "empty allowlist");
const emptyPolicy = await probe("INC9", "empty allowlist probe");
await Bun.write(inputsFile, originalPolicy);
git("add", "-A");
git("commit", "-qm", "restore the original allowlist");
const restored = await probe("INC10", "restored allowlist probe");
console.log(JSON.stringify({
  first, afterUnlisted, afterLifecycle, afterCommit, afterIncludedEdit,
  withNewIncluded, afterNewIncluded, afterPolicyChange, emptyPolicy, restored,
}));
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
    lifecycle = result.get("afterLifecycleReports", {}).get("bindings", {})
    check("a change record, attack log, and code-adversarial report written after "
          "evidence neither dirty nor move the snapshot",
          lifecycle.get("source_snapshot") == bindings.get("source_snapshot")
          and result["afterLifecycleReports"]["result"] == "PASS",
          lifecycle.get("source_snapshot"))
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


def check_policy_parity(temporary: Path) -> None:
    """Gate-side and producer-side policy parsing, selection, and ordering."""
    project = temporary / "policy-parity"
    (project / ".fv").mkdir(parents=True)
    (project / "policy-fixtures.json").write_text(json.dumps({
        "fixtures": [{"label": label, "hex": payload.hex()}
                     for label, payload, _ in POLICY_FIXTURES],
        "probes": list(SELECTION_PROBES),
        "order": list(ORDER_PROBES),
    }))
    listing = project / ".fv" / "verified-inputs.txt"
    gate_side: dict[str, dict] = {}
    for label, payload, _ in POLICY_FIXTURES:
        listing.write_bytes(payload)
        try:
            policy = fv_project.load_policy(project)
        except fv_project.ProjectError as error:
            gate_side[label] = {"ok": False, "mode": "", "prefixes": None, "selectors": None,
                                "exclusions": None, "selects": None, "error": str(error)}
            continue
        gate_side[label] = {
            "ok": True,
            "mode": policy.mode,
            "prefixes": list(policy.prefixes),
            "selectors": list(policy.selectors()),
            "exclusions": policy.exclusions(),
            "selects": {probe: policy.selects(probe) for probe in SELECTION_PROBES},
            "error": "",
        }
    harness = run_harness(temporary / "policy-harness.ts", POLICY_HARNESS, project)
    producer = harness.get("policies", {})

    def producer_error(label: str) -> str:
        return str(producer.get(label, {}).get("error", "")).removeprefix("Error: ")

    check("policy parity: the producer reports a verdict for every fixture",
          set(producer) == {label for label, _, _ in POLICY_FIXTURES},
          sorted({label for label, _, _ in POLICY_FIXTURES} ^ set(producer)))
    misjudged = [label for label, _, expect in POLICY_FIXTURES
                 if gate_side[label]["ok"] != (expect == "accept")]
    check("policy parity: Gate B's parser lands on every fixture's declared verdict",
          not misjudged, [(label, gate_side[label]["error"]) for label in misjudged])
    divergent = [label for label, _, _ in POLICY_FIXTURES
                 if producer.get(label, {}).get("ok") != gate_side[label]["ok"]]
    check("policy parity: producer and gate accept and reject the same fixtures",
          not divergent,
          [(label, gate_side[label]["error"], producer_error(label)) for label in divergent])
    for field in ("mode", "prefixes", "selectors", "exclusions"):
        unequal = [label for label, _, expect in POLICY_FIXTURES if expect == "accept"
                   and producer.get(label, {}).get(field) != gate_side[label][field]]
        check(f"policy parity: an accepted policy yields one {field} on both sides",
              not unequal,
              [(label, gate_side[label][field], producer.get(label, {}).get(field))
               for label in unequal])
    mismatched = [(label, probe) for label, _, expect in POLICY_FIXTURES if expect == "accept"
                  for probe in SELECTION_PROBES
                  if (producer.get(label, {}).get("selects") or {}).get(probe)
                  is not gate_side[label]["selects"][probe]]
    check("policy parity: both ends select the same candidates under every accepted policy",
          not mismatched, mismatched[:4])
    worded = [label for label, _, expect in POLICY_FIXTURES
              if expect == "reject" and label not in RUNTIME_WORDED_REJECTIONS
              and producer_error(label) != gate_side[label]["error"]]
    check("policy parity: both ends word every grammar rejection identically",
          not worded, [(label, gate_side[label]["error"], producer_error(label))
                       for label in worded])
    check("policy parity: invalid UTF-8 is refused by both ends, decoder wording aside",
          all(not gate_side[label]["ok"] and not producer.get(label, {}).get("ok")
              and "cannot read .fv/verified-inputs.txt" in gate_side[label]["error"]
              and "cannot read .fv/verified-inputs.txt" in producer_error(label)
              for label in RUNTIME_WORDED_REJECTIONS),
          [(label, gate_side[label]["error"], producer_error(label))
           for label in RUNTIME_WORDED_REJECTIONS])
    # The rejection has to name the cause, for the same reason the BOM rule does: an
    # unexplained stale record is what a silent policy split looks like from outside.
    for label, fragment in (
        ("empty include policy", "mode: include names no path"),
        ("directive after an entry", "mode directive must be the first non-comment line"),
        ("mode word in the wrong case", "unknown mode 'Include'"),
        ("unknown mode word", "unknown mode 'allowlist'"),
        ("byte-order mark before an include directive", "byte-order mark U+FEFF"),
        ("bare carriage return under include mode", "ambiguous line terminator '\\r'"),
    ):
        check(f"policy parity: both ends name the defect identically ({label})",
              fragment in gate_side[label]["error"] and fragment in producer_error(label),
              (gate_side[label]["error"], producer_error(label)))
    include = gate_side["include directive"]
    check("policy: an include policy selects itself, so revising it moves the snapshot",
          fv_project.VERIFIED_INPUTS_RELATIVE in include["selectors"]
          and include["selects"][fv_project.VERIFIED_INPUTS_RELATIVE]
          and (producer.get("include directive", {}).get("selectors") or [])[-1]
          == fv_project.VERIFIED_INPUTS_RELATIVE,
          (include["selectors"], producer.get("include directive", {}).get("selectors")))
    check("policy: an include policy selects nothing it does not name",
          not include["selects"]["README.md"] and not include["selects"]["cratesX/lib.rs"]
          and include["selects"]["crates/lib.rs"] and include["selects"]["quint/spec.qnt"],
          include["selects"])
    dotfv = gate_side["include naming the whole .fv directory"]
    check("policy: structural exclusions outrank an allowlist naming the .fv tree",
          dotfv["selects"][".fv/intent.md"]
          and not any(dotfv["selects"][probe] for probe in (
              ".fv/evidence/records/W1.json", ".fv/changes/2026-09-15-change.md",
              ".fv/attacks/attack-1.md", ".fv/code-adversarial/report-1.md",
              ".fv/history/colosseum/ledger.md")),
          dotfv["selects"])
    legacy = gate_side["no directive stays exclusion mode"]
    check("policy: a list with no directive keeps its exclusion meaning",
          legacy["mode"] == fv_project.MODE_EXCLUDE
          and legacy["prefixes"] == ["build/", "logs/"]
          and legacy["selects"]["README.md"] and not legacy["selects"]["build/out.bin"],
          legacy)
    check("policy: the structural defaults are identical on both sides and cover "
          "every lifecycle report directory",
          producer.get("include directive", {}).get("exclusions")
          == list(fv_project.DEFAULT_EXCLUSIONS)
          and {".fv/changes/", ".fv/attacks/", ".fv/code-adversarial/"}
          <= set(fv_project.DEFAULT_EXCLUSIONS),
          producer.get("include directive", {}).get("exclusions"))
    order = harness.get("order", {})
    check("snapshot order: both ends order astral-plane paths UTF-8 byte-wise",
          order.get("utf8") == fv_project.order_inputs(list(ORDER_PROBES)), order.get("utf8"))
    # Without this the parity above would be vacuous: it only means anything because the
    # runtime's own comparison disagrees on exactly these paths.
    check("snapshot order: the runtime's default comparison really does disagree",
          order.get("codeUnit") != order.get("utf8"), order)


def include_mode_project(temporary: Path) -> Path:
    """Repository whose verified inputs are an allowlist, astral-plane names included."""
    project = temporary / "include-mode"
    (project / ".fv").mkdir(parents=True)
    (project / "crates").mkdir()
    (project / "docs").mkdir()
    (project / ".fv" / "intent.md").write_text("# Include Intent\n")
    (project / ".fv" / "obligations.json").write_text(json.dumps({
        "version": 1,
        "invariants": [],
        # Only the claim Gate B is asked about below: a manifest naming every probe would
        # make the gate's verdict INCOMPLETE over the nine records it was never given.
        "witnesses": [{"id": "INC10", "name": "witness_inc10"}],
    }))
    (project / ".fv" / "verified-inputs.txt").write_text(INCLUDE_POLICY)
    (project / "crates" / "lib.rs").write_text("pub const N: u8 = 1;\n")
    (project / ASTRAL_INPUT).write_text("astral-plane verified input\n")
    (project / PUA_INPUT).write_text("private-use verified input\n")
    (project / "docs" / "notes.md").write_text("documentation the allowlist omits\n")
    git_repository(project)
    return project


def check_include_mode(temporary: Path) -> None:
    project = include_mode_project(temporary)
    manifest = project / ".fv" / "obligations.json"
    records = project / ".fv" / "evidence" / "records"
    result = run_harness(temporary / "include-harness.ts", INCLUDE_HARNESS, project)

    def snapshot(key: str) -> str:
        return str(((result.get(key) or {}).get("record") or {})
                   .get("bindings", {}).get("source_snapshot"))

    def verdict(key: str) -> str:
        return str(((result.get(key) or {}).get("record") or {}).get("result"))

    check("include mode produces a well-formed content snapshot",
          verdict("first") == "PASS"
          and re.fullmatch(r"sha256:[0-9a-f]{64}", snapshot("first")) is not None,
          result.get("first"))
    check("include mode: editing a path the allowlist omits neither dirties nor moves it",
          verdict("afterUnlisted") == "PASS" and snapshot("afterUnlisted") == snapshot("first"),
          result.get("afterUnlisted"))
    check("include mode: lifecycle reports written after evidence keep it fresh",
          verdict("afterLifecycle") == "PASS"
          and snapshot("afterLifecycle") == snapshot("first"),
          result.get("afterLifecycle"))
    check("include mode: committing the evidence and those reports keeps it fresh",
          verdict("afterCommit") == "PASS" and snapshot("afterCommit") == snapshot("first"),
          result.get("afterCommit"))
    check("include mode: editing an allowlisted input moves the snapshot",
          verdict("afterIncludedEdit") == "PASS"
          and snapshot("afterIncludedEdit") != snapshot("first"),
          result.get("afterIncludedEdit"))
    check("include mode: an uncommitted new file under an allowlisted directory is dirt",
          verdict("withNewIncluded") == "FAIL" and snapshot("withNewIncluded").endswith("+dirty"),
          result.get("withNewIncluded"))
    check("include mode: a committed new allowlisted input moves the snapshot",
          verdict("afterNewIncluded") == "PASS"
          and snapshot("afterNewIncluded") != snapshot("afterIncludedEdit"),
          result.get("afterNewIncluded"))
    check("include mode: widening the allowlist invalidates evidence bound to the narrow one",
          verdict("afterPolicyChange") == "PASS"
          and snapshot("afterPolicyChange") != snapshot("afterNewIncluded"),
          result.get("afterPolicyChange"))
    check("include mode: an allowlist naming no path is refused, not bound to itself",
          "names no path" in str(result.get("emptyPolicy", {}).get("error", "")),
          result.get("emptyPolicy"))
    check("include mode: restoring the allowlist restores the snapshot",
          verdict("restored") == "PASS"
          and snapshot("restored") == snapshot("afterNewIncluded"),
          (snapshot("restored"), snapshot("afterNewIncluded")))
    # The end-to-end differential: one repository, two implementations, one hash. An
    # ordering or matching difference over the astral-plane inputs shows up here and
    # nowhere else, because a snapshot is the only thing both ends publish.
    check("include mode: the gate recomputes the producer's snapshot byte for byte",
          fv_project.content_snapshot(project) == snapshot("restored"),
          (fv_project.content_snapshot(project), snapshot("restored")))
    selected = {path for path, _ in fv_project.snapshot_entries(project)}
    check("include mode: the snapshot covers exactly the allowlist plus the policy itself",
          selected == {".fv/intent.md", ".fv/obligations.json", fv_project.VERIFIED_INPUTS_RELATIVE,
                       "crates/lib.rs", "crates/extra.rs", ASTRAL_INPUT, PUA_INPUT},
          sorted(selected))

    fresh = subprocess.run(["python3", str(GATE), "--records", str(records / "INC10.json"),
                            "--root", str(project), "--manifest", str(manifest), "--json"],
                           capture_output=True, text=True)
    check("Gate B accepts an include-mode record under default freshness",
          fresh.returncode == 0, fresh.stdout + fresh.stderr)
    (project / "docs" / "notes.md").write_text("documentation edited after the run\n")
    unlisted = subprocess.run(["python3", str(GATE), "--records", str(records / "INC10.json"),
                               "--root", str(project), "--manifest", str(manifest), "--json"],
                              capture_output=True, text=True)
    check("Gate B keeps an include-mode record fresh when an unlisted path changes",
          unlisted.returncode == 0, unlisted.stdout + unlisted.stderr)
    (project / ASTRAL_INPUT).write_text("astral-plane input edited after the run\n")
    stale = subprocess.run(["python3", str(GATE), "--records", str(records / "INC10.json"),
                            "--root", str(project), "--manifest", str(manifest), "--json"],
                           capture_output=True, text=True)
    check("Gate B stales an include-mode record once an allowlisted input changes",
          stale.returncode == 3 and "stale record" in stale.stdout, stale.stdout)


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
        # rustup's `cargo` and elan's `lake` dispatch on argv[0], so a producer that
        # runs the realpath runs the multiplexer instead of the requested tool.
        dispatcher = root / "dispatcher"
        dispatcher.write_text(
            "#!/bin/sh\n"
            "case \"$(basename \"$0\")\" in\n"
            "  toolname) if [ \"$1\" = \"--version\" ]; then echo toolname-v1; "
            "else echo 'test result: ok.'; fi ;;\n"
            "  *) echo \"dispatched as $(basename \"$0\")\"; exit 1 ;;\n"
            "esac\n"
        )
        dispatcher.chmod(0o755)
        (root / "toolname").symlink_to(dispatcher)
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
        multiplexed_record = result["multiplexed"]["record"]
        check("a multiplexer dispatching on argv[0] runs as the requested tool",
              multiplexed_record["result"] == "PASS"
              and multiplexed_record["bindings"]["toolchain_digests"]["executable"]
              == str(dispatcher.resolve()), multiplexed_record["bindings"]["toolchain_digests"])
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
        check_policy_parity(Path(temporary))
        check_include_mode(Path(temporary))

    print()
    if FAILURES:
        print(f"R34: {len(FAILURES)} failure(s)")
        return 1
    print("R34: all assertions passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
