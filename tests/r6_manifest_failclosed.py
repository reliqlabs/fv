#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
R6 — manifest fail-closed control flow in fv_run.py (E4, contract G2), plus the
canonical-target / verified-input-snapshot contract shared by fv_project.py and
Gate B (check_evidence_records.py).

Zero-voice manifests are invalid runs everywhere they could be read;
duplicate voice ids are rejected at init and at load; an all-errored
`wait` exits nonzero (all-terminal is not success when zero voices
completed); `synthesize` refuses pending/errored inputs without an
explicit --allow-partial and labels the output PARTIAL when overridden;
zero completed voices cannot be synthesized at all; `reset` retains the
prior attempt in the voice's history instead of erasing it.

Project-binding half: the dispatch target may be an external doc
(docs/intent.md) and Gate B binds intent to it rather than to .fv/intent.md;
the verified-input snapshot is stable across a commit of unchanged content and
invalidates records when a verified input changes; targets that escape the
project root (or are missing, a directory, or a symlink) are rejected; evidence,
verify, panel, and declared exclusion outputs never enter the snapshot; and v2
records still validate under explicit --expect-snapshot/--allow-unbound.

Exit 0 pass, 1 fail.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RUN = REPO / "scripts" / "fv_run.py"
GATE_B = REPO / "scripts" / "check_evidence_records.py"
FAILURES: list[str] = []

sys.path.insert(0, str(REPO / "scripts"))
import fv_project  # noqa: E402  module under test


def check(label: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"  [ok]   {label}")
    else:
        suffix = f" ({detail})" if detail else ""
        print(f"  [FAIL] {label}{suffix}")
        FAILURES.append(label)


def crun(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["uv", "run", "--script", str(RUN), *args],
                          capture_output=True, text=True, timeout=120)


def gate_b(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["uv", "run", "--script", str(GATE_B), *args],
                          capture_output=True, text=True, timeout=180)


def git(project: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "user.email=r6@fv.test", "-c", "user.name=r6",
                    "-c", "commit.gpgsign=false", *args],
                   cwd=project, capture_output=True, text=True, check=True, timeout=60)


def git_out(project: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=project, capture_output=True,
                          text=True, check=True, timeout=60).stdout.strip()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rejects(spec: str, project: Path) -> bool:
    try:
        fv_project.resolve_target(project, spec)
    except fv_project.ProjectError:
        return True
    return False


def build_project(root: Path) -> Path:
    """Git project whose canonical target is an external docs/intent.md."""
    project = root / "proj"
    for relative in ("src", "docs", ".fv"):
        (project / relative).mkdir(parents=True)
    (project / "src" / "lib.rs").write_text("pub fn ok() -> bool { true }\n")
    (project / "docs" / "intent.md").write_text(
        "# external intent\n\nC1: the canonical target may live outside .fv\n")
    (project / ".fv" / "intent.md").write_text("# decoy intent\n")
    (project / ".fv" / "dispatch.json").write_text(json.dumps(
        {"omp_native": {"project_root": ".", "target_spec": "docs/intent.md"}},
        indent=2) + "\n")
    (project / ".fv" / "obligations.json").write_text(json.dumps(
        {"invariants": [{"id": "A1", "statement": "ok() holds"}]}, indent=2) + "\n")
    (project / ".fv" / "verified-inputs.txt").write_text(
        "# project exclusions\n\n  build/  \n")
    git(project, "init", "-q")
    git(project, "add", "-A")
    git(project, "commit", "-qm", "init")
    return project


def write_record(project: Path, snapshot: str, intent_hash: str,
                 schema: str = "fv-evidence-run/v3") -> Path:
    """Write a single PASS record for A1 under .fv/evidence; returns its directory."""
    raw = project / ".fv" / "evidence" / "raw" / "A1.log"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text("fixture check\n--- fv-evidence: exit=0 ---\n")
    records = project / ".fv" / "evidence" / "records"
    records.mkdir(parents=True, exist_ok=True)
    record = {
        "claim_id": "A1",
        "required": True,
        "evidence_class": "code-enforced",
        "result": "PASS",
        "scope": "r6 fixture invariant",
        "bindings": {
            "source_snapshot": snapshot,
            "intent_hash": intent_hash,
            "intent_path": "docs/intent.md",
            "obligation_manifest_hash": sha256_file(project / ".fv" / "obligations.json"),
            "profile": "r6-fixture",
            "required_targets": ["A1"],
            "environment_policy": "r6-fixture-local",
            "toolchain_digests": {"python": sys.version.split()[0]},
            "command": json.dumps(["true"]),
            "configuration": {"cwd": "."},
            "seeds": None,
            "raw_output_hash": sha256_file(raw),
            "raw_output_path": ".fv/evidence/raw/A1.log",
            "parser_schema_version": schema,
            "run_id": "r6-1",
        },
        "waiver": None,
    }
    (records / "A1.json").write_text(json.dumps(record, indent=2) + "\n")
    return records


def resolver_checks(root: Path, project: Path) -> None:
    target = fv_project.resolve_target(project)
    check("resolver: dispatch target_spec resolves to external docs/intent.md",
          target == (project / "docs" / "intent.md").resolve(), str(target))
    check("resolver: resolved target round-trips to a repo-relative target_spec",
          fv_project.relative_target_spec(project, target) == "docs/intent.md")
    check("resolver: target_spec that does not exist yet is still relativizable",
          fv_project.relative_target_spec(project, project / ".fv" / "intent-new.md")
          == ".fv/intent-new.md")
    check("resolver: legacy absolute target inside the project root is accepted",
          fv_project.resolve_target(project, str(project / "docs" / "intent.md")) == target)

    plain = root / "plain"
    (plain / ".fv").mkdir(parents=True)
    (plain / ".fv" / "intent.md").write_text("# default target\n")
    check("resolver: missing dispatch.json defaults to .fv/intent.md",
          fv_project.resolve_target(plain) == (plain / ".fv" / "intent.md").resolve())
    (plain / ".fv" / "dispatch.json").write_text(
        json.dumps({"omp_native": {"project_root": "."}}, indent=2) + "\n")
    check("resolver: dispatch without target_spec defaults to .fv/intent.md",
          fv_project.resolve_target(plain) == (plain / ".fv" / "intent.md").resolve()
          and fv_project.declared_target_spec(plain) is None)
    (plain / ".fv" / "dispatch.json").write_text("{not json")
    check("resolver: malformed dispatch.json fails closed",
          rejects_route(plain))

    outside = root / "outside.md"
    outside.write_text("# not in the project\n")
    for label, spec in (("relative parent escape", "../outside.md"),
                        ("absolute path outside root", str(outside)),
                        ("nonexistent file", "docs/nope.md"),
                        ("directory", ".fv"),
                        ("empty spec", "   ")):
        check(f"resolver rejects target: {label}", rejects(spec, project))
    link = project / "docs" / "linked-intent.md"
    link.symlink_to(project / "docs" / "intent.md")
    try:
        check("resolver rejects target: symlink", rejects("docs/linked-intent.md", project))
    finally:
        link.unlink()


def rejects_route(project: Path) -> bool:
    try:
        fv_project.dispatch_route(project)
    except fv_project.ProjectError:
        return True
    return False


def snapshot_checks(project: Path) -> str:
    """Snapshot semantics; returns the snapshot of the committed project."""
    initial = fv_project.content_snapshot(project)
    check("snapshot: well-formed sha256 content snapshot",
          fv_project.is_content_snapshot(initial), initial)
    check("snapshot: recomputation is deterministic",
          fv_project.content_snapshot(project) == initial)

    head = git_out(project, "rev-parse", "HEAD")
    extra = project / "src" / "extra.rs"
    extra.write_text("pub const N: u8 = 1;\n")
    untracked = fv_project.content_snapshot(project)
    check("snapshot: untracked unignored file enters the snapshot", untracked != initial)
    git(project, "add", "-A")
    git(project, "commit", "-qm", "extra")
    committed = fv_project.content_snapshot(project)
    check("snapshot: stable across a commit of unchanged content",
          committed == untracked and git_out(project, "rev-parse", "HEAD") != head)

    for relative in (".fv/evidence/raw/noise.log", ".fv/verify/report.json",
                     ".fv/panels/run.json", ".colosseum/intent.md"):
        path = project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("noise\n")
    check("snapshot: default exclusions keep evidence/verify/panel outputs out",
          fv_project.content_snapshot(project) == committed)
    (project / "build").mkdir()
    (project / "build" / "out.bin").write_bytes(b"\x00\x01")
    check("snapshot: declared build/ exclusion keeps build output out",
          fv_project.content_snapshot(project) == committed)
    stray = project / "src" / "stray.rs"
    stray.write_text("pub const M: u8 = 2;\n")
    check("snapshot: unexcluded new input changes the snapshot",
          fv_project.content_snapshot(project) != committed)
    stray.unlink()

    check("exclusions: blank and # lines ignored, ./ stripped",
          fv_project.parse_exclusions("# comment\n\n  ./tmp/  \nlogs/\n") == ["tmp/", "logs/"])
    check("exclusions: defaults union the declared list",
          set(fv_project.DEFAULT_EXCLUSIONS) <= set(fv_project.load_exclusions(project))
          and "build/" in fv_project.load_exclusions(project))
    for bad in ("/etc/", "../outside/", "."):
        rejected = False
        try:
            fv_project.parse_exclusions(bad + "\n")
        except fv_project.ProjectError:
            rejected = True
        check(f"exclusions reject entry {bad!r}", rejected)
    check("snapshot: component-wise exclusion does not swallow sibling prefixes",
          fv_project.is_excluded("build/out.bin", ["build"])
          and not fv_project.is_excluded("buildout.bin", ["build"]))

    symlinked = project / "src" / "link.rs"
    symlinked.symlink_to(project / "src" / "lib.rs")
    rejected = False
    try:
        fv_project.content_snapshot(project)
    except fv_project.ProjectError:
        rejected = True
    symlinked.unlink()
    check("snapshot: symlinked verified input fails closed", rejected)
    return committed


def gate_checks(project: Path, snapshot: str) -> None:
    manifest = project / ".fv" / "obligations.json"
    intent = fv_project.target_hash(project)

    def run_gate(*extra: str) -> subprocess.CompletedProcess:
        return gate_b("--records", str(project / ".fv" / "evidence" / "records"),
                      "--manifest", str(manifest), "--root", str(project), *extra)

    write_record(project, snapshot, intent)
    result = run_gate("--json")
    report = json.loads(result.stdout) if result.stdout.strip().startswith("{") else {}
    check("Gate B: default binding verifies a record bound to the content snapshot",
          result.returncode == 0 and "VERIFIED" in result.stderr,
          f"exit={result.returncode} {result.stdout[-300:]}{result.stderr[-200:]}")
    check("Gate B: report names the resolved external target and expected snapshot",
          report.get("intent_path") == "docs/intent.md"
          and report.get("expected_snapshot") == snapshot,
          f"{report.get('intent_path')!r} {report.get('expected_snapshot')!r}")

    write_record(project, snapshot, sha256_file(project / ".fv" / "intent.md"))
    result = run_gate()
    check("Gate B: record bound to .fv/intent.md is stale when dispatch names docs/intent.md",
          result.returncode == 3 and "stale record: bound to intent" in result.stdout,
          f"exit={result.returncode}")

    write_record(project, snapshot, intent)
    lib = project / "src" / "lib.rs"
    lib.write_text("pub fn ok() -> bool { 1 == 1 }\n")
    result = run_gate()
    check("Gate B: changing a verified input invalidates the record",
          result.returncode == 3 and "stale record: bound to snapshot" in result.stdout,
          f"exit={result.returncode}")

    rebound = fv_project.content_snapshot(project)
    write_record(project, rebound, intent)
    git(project, "add", "-A")
    git(project, "commit", "-qm", "change")
    result = run_gate()
    check("Gate B: freshness survives committing the inputs the record is bound to",
          result.returncode == 0, f"exit={result.returncode} {result.stdout[-300:]}")

    dispatch = project / ".fv" / "dispatch.json"
    original = dispatch.read_text()
    dispatch.write_text(json.dumps(
        {"omp_native": {"project_root": ".", "target_spec": "../outside.md"}}, indent=2) + "\n")
    result = run_gate()
    check("Gate B: escaping dispatch target fails closed",
          result.returncode == 2 and "escapes project root" in (result.stdout + result.stderr),
          f"exit={result.returncode}")
    dispatch.write_text(original)

    head = git_out(project, "rev-parse", "HEAD")
    write_record(project, head, intent, "fv-evidence-run/v2")
    result = run_gate("--expect-snapshot", head[:7], "--expect-intent", intent)
    check("Gate B: v2 record validates under explicit --expect-snapshot prefix",
          result.returncode == 0, f"exit={result.returncode} {result.stdout[-300:]}")
    result = run_gate("--allow-unbound")
    check("Gate B: --allow-unbound still accepts an unbound v2 record",
          result.returncode == 0, f"exit={result.returncode}")
    result = run_gate()
    check("Gate B: default freshness rejects a v2 record with a migration hint",
          result.returncode == 3 and "predates verified-input snapshots" in result.stdout,
          f"exit={result.returncode}")


def project_binding_checks() -> None:
    with tempfile.TemporaryDirectory(prefix="r6-project-") as td:
        root = Path(td).resolve()
        project = build_project(root)
        resolver_checks(root, project)
        gate_checks(project, snapshot_checks(project))


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="r6-") as td:
        tmp = Path(td)
        target = tmp / "intent.md"
        target.write_text("# intent\n")

        r = crun("init", str(target), "--voices=", "--owners=")
        check("init: empty --voices rejected",
              r.returncode != 0 and "zero-voice" in (r.stdout + r.stderr))

        r = crun("init", str(target), "--voices=a,a", "--owners=a:omp")
        check("init: duplicate voice ids rejected",
              r.returncode != 0 and "duplicate" in (r.stdout + r.stderr))

        # Hand-built zero-voice manifest: every reader must refuse it.
        zero_dir = tmp / "zero"
        zero_dir.mkdir()
        (zero_dir / "run.json").write_text(json.dumps(
            {"run_id": "z", "target": str(target), "created": "t", "voices": [],
             "synthesis": {"file": "synthesis.md", "harness": "x", "status": "pending"}}))
        for sub in (["status", str(zero_dir)],
                    ["wait", str(zero_dir), "--timeout=3"],
                    ["synthesize", str(zero_dir)]):
            r = crun(*sub)
            check(f"zero-voice manifest refused by `{sub[0]}`",
                  r.returncode != 0 and "zero voices" in (r.stdout + r.stderr),
                  f"exit={r.returncode}")

        # Real run: two voices.
        run_dir = tmp / "run"
        r = crun("init", str(target), "--voices=v1,v2",
                 "--owners=v1:omp,v2:omp", f"--run-dir={run_dir}")
        check("init: two-voice run created", r.returncode == 0, r.stderr[-200:])

        # All-errored wait -> nonzero (zero evidence).
        crun("error", str(run_dir), "--voice=v1", "--detail=HTTP 500", "--elapsed=1")
        crun("error", str(run_dir), "--voice=v2", "--detail=timeout", "--elapsed=2")
        r = crun("wait", str(run_dir), "--timeout=3")
        check("wait: all-errored run exits nonzero with INCOMPLETE",
              r.returncode == 2 and "INCOMPLETE" in (r.stdout + r.stderr),
              f"exit={r.returncode}")

        # Zero completed voices: synthesize refuses even with override.
        r = crun("synthesize", str(run_dir), "--allow-partial")
        check("synthesize: zero completed voices refused even with --allow-partial",
              r.returncode != 0 and "zero completed" in (r.stdout + r.stderr))

        # Reset v1, complete it; history must retain the errored attempt.
        crun("reset", str(run_dir), "--voice=v1")
        manifest = json.loads((run_dir / "run.json").read_text())
        v1 = next(v for v in manifest["voices"] if v["id"] == "v1")
        check("reset: prior errored attempt retained in history",
              len(v1.get("history", [])) == 1
              and v1["history"][0]["status"] == "error"
              and v1["history"][0]["error_detail"] == "HTTP 500")

        (run_dir / v1["file"]).write_text("## Attacks\n\nVERDICT: BREAKS\n")
        crun("complete", str(run_dir), "--voice=v1", "--elapsed=3",
             "--finish-reason=stop")

        # One complete + one errored: refused without override, labeled with.
        r = crun("synthesize", str(run_dir))
        check("synthesize: errored voice refused without --allow-partial",
              r.returncode != 0 and "--allow-partial" in (r.stdout + r.stderr))
        r = crun("synthesize", str(run_dir), "--allow-partial")
        synth = (run_dir / "synthesis-input.md").read_text() \
            if (run_dir / "synthesis-input.md").exists() else ""
        check("synthesize: --allow-partial produces PARTIAL-labeled output",
              r.returncode == 0 and "PARTIAL SYNTHESIS INPUT" in synth
              and "coverage gap" in synth,
              f"exit={r.returncode}")

        # Mixed-terminal wait: one complete + one errored is exit 0 (evidence exists).
        r = crun("wait", str(run_dir), "--timeout=3")
        check("wait: terminal run with at least one completion exits 0",
              r.returncode == 0, f"exit={r.returncode}")

    project_binding_checks()

    print()
    if FAILURES:
        print(f"R6: {len(FAILURES)} failure(s)")
        return 1
    print("R6: all assertions passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
