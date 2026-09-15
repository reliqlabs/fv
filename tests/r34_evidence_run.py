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
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TOOL = REPO / "tools" / "evidence-run.ts"
GATE = REPO / "scripts" / "check_evidence_records.py"
RESOLVER = REPO / "scripts" / "fv_project.py"
FAILURES: list[str] = []

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
const intentDrift = await tool.execute("intent-drift", {
  claim_id: "I1",
  command: ["sh", "-c", "printf '# Changed Intent\\n' > .fv/intent.md; echo 'test result: ok.'"],
  evidence_class: "test-witnessed", scope: "intent drift probe",
}, undefined, {}, undefined);
let escapeError = "";
try {
  await tool.execute("escape", {
    claim_id: "E1", command: ["sh", "-c", "echo 'test result: ok.'"], cwd: "escape",
    evidence_class: "test-witnessed", scope: "symlink escape probe",
  }, undefined, {}, undefined);
} catch (error) { escapeError = String(error); }
console.log(JSON.stringify({
  passing: passing.details, failing: failing.details, dirty: dirtyResult.details,
  customMarker: customMarker.details, relativeExecutable: relativeExecutable.details,
  namedTool: namedTool.details, intentDrift: intentDrift.details, escapeError,
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
console.log(JSON.stringify({ first, afterEvidenceCommit, afterExcludedOutput }));
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
const clean = await attempt("CLN1", "docs/intent.md");
await Bun.write(`${projectRoot}/src.txt`, "modified outside the evidence run\n");
const dirtyVerified = await probeCurrent("DRT1", "dirty verified input probe");
git("checkout", "--", "src.txt");
symlinkSync(`${projectRoot}/docs/intent.md`, `${projectRoot}/docs/link.md`);
const symlinkTarget = await attempt("SYM1", "docs/link.md");
unlinkSync(`${projectRoot}/docs/link.md`);
await writeDispatch("docs/intent.md");
symlinkSync("../outside.md", `${projectRoot}/linked.md`);
const symlinkInput = await probeCurrent("LNK1", "symlinked verified input probe");
console.log(JSON.stringify({
  absoluteInside, missing, defaulted, directory, escaping,
  clean, dirtyVerified, symlinkTarget, symlinkInput,
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
    else:
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

        missing = json.loads(passing_path.read_text())
        missing["bindings"]["raw_output_path"] = ".fv/evidence/raw/does-not-exist.log"
        missing_path = root / "missing.json"
        missing_path.write_text(json.dumps(missing))
        checked = gate(missing_path, root, "W1")
        check("missing raw artifact rejected", checked.returncode == 3 and "unresolvable raw artifact" in checked.stdout, checked.stdout)

        wrong = json.loads(passing_path.read_text())
        wrong["bindings"]["raw_output_hash"] = "0" * 64
        wrong_path = root / "wrong-hash.json"
        wrong_path.write_text(json.dumps(wrong))
        checked = gate(wrong_path, root, "W1")
        check("wrong raw hash rejected", checked.returncode == 3 and "raw output hash mismatch" in checked.stdout, checked.stdout)

        marker_raw = state / "evidence" / "raw" / "marker-absent.log"
        marker_raw.write_text("command completed\n--- fv-evidence: exit=0 ---\n")
        absent = json.loads(passing_path.read_text())
        absent["bindings"]["raw_output_path"] = str(marker_raw.relative_to(root))
        absent["bindings"]["raw_output_hash"] = hashlib.sha256(marker_raw.read_bytes()).hexdigest()
        absent_path = root / "marker-absent.json"
        absent_path.write_text(json.dumps(absent))
        checked = gate(absent_path, root, "W1")
        check("missing class marker rejected", checked.returncode == 3 and "PASS marker absent" in checked.stdout, checked.stdout)

        exit_raw = state / "evidence" / "raw" / "forged-exit.log"
        exit_raw.write_text("test result: ok.\n--- fv-evidence: exit=7 ---\n")
        forged = json.loads(passing_path.read_text())
        forged["bindings"]["raw_output_path"] = str(exit_raw.relative_to(root))
        forged["bindings"]["raw_output_hash"] = hashlib.sha256(exit_raw.read_bytes()).hexdigest()
        forged["bindings"]["configuration"] = {"pass_marker": ".*"}
        forged_path = root / "forged-exit.json"
        forged_path.write_text(json.dumps(forged))
        checked = gate(forged_path, root, "W1")
        check("record-controlled regex cannot mask nonzero exit",
              checked.returncode == 3 and "canonical exit=0 trailer" in checked.stdout,
              checked.stdout)
        conflicting_raw = state / "evidence" / "raw" / "conflicting-exit.log"
        conflicting_raw.write_text("test result: ok.\n--- fv-evidence: exit=7 ---\n--- fv-evidence: exit=0 ---\n")
        conflicting = json.loads(passing_path.read_text())
        conflicting["bindings"]["raw_output_path"] = str(conflicting_raw.relative_to(root))
        conflicting["bindings"]["raw_output_hash"] = hashlib.sha256(conflicting_raw.read_bytes()).hexdigest()
        conflicting_path = root / "conflicting-exit.json"
        conflicting_path.write_text(json.dumps(conflicting))
        checked = gate(conflicting_path, root, "W1")
        check("conflicting exit trailers rejected",
              checked.returncode == 3 and "one unique canonical exit=0 trailer" in checked.stdout,
              checked.stdout)

        incompatible = json.loads(passing_path.read_text())
        incompatible["claim_id"] = "B1"
        incompatible_path = root / "incompatible.json"
        incompatible_path.write_text(json.dumps(incompatible))
        checked = gate(incompatible_path, root, "", manifest)
        check("incompatible obligation class rejected", "incompatible evidence class" in checked.stdout, checked.stdout)

        check_external_target(Path(temporary))

    print()
    if FAILURES:
        print(f"R34: {len(FAILURES)} failure(s)")
        return 1
    print("R34: all assertions passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
