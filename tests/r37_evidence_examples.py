#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""R37: the shipped v3 evidence examples are machine-validated, not illustrated.

`templates/evidence-records.example.json` and `templates/obligations.example.json`
ship placeholder digests because no file in this repository can carry a real one:
a record's bindings are digests over one project tree and over the executables of
one machine. This suite materializes them - the project layout the example
declares, a git repository over it, the raw logs it declares, a stub executable
per launched binary, and then the bindings recomputed from all of that - and runs
Gate B over the result with no --allow-unbound and no pinned expectations. A
VERIFIED verdict is the assertion; nothing here reads the examples as text.

Three negative controls keep that verdict from being vacuous: a tampered raw log,
a cohort missing one of S1's required tools, and a moved verified input.
"""
from __future__ import annotations

import copy
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
GATE = REPO / "scripts" / "check_evidence_records.py"
RECORDS_EXAMPLE = REPO / "templates" / "evidence-records.example.json"
OBLIGATIONS_EXAMPLE = REPO / "templates" / "obligations.example.json"
FAILURES: list[str] = []

sys.path.insert(0, str(REPO / "scripts"))
import check_evidence_records as gate_module  # noqa: E402  the gate whose rules the examples must satisfy
import fv_project  # noqa: E402  the snapshot and target resolver Gate B recomputes with


def check(label: str, condition: bool, detail: object = "") -> None:
    if condition:
        print(f"  [ok]   {label}")
    else:
        print(f"  [FAIL] {label}" + (f" ({detail})" if detail else ""))
        FAILURES.append(label)


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def git_repository(project: Path) -> None:
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    for key, value in (("user.email", "r37@example.test"), ("user.name", "R37"),
                       ("commit.gpgsign", "false")):
        subprocess.run(["git", "-C", str(project), "config", key, value], check=True)
    subprocess.run(["git", "-C", str(project), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(project), "commit", "-qm", "fixture"], check=True)


def build_project(root: Path, example: dict) -> Path:
    """The tree the example declares, as a committed git repository."""
    plan = example["_materialization"]
    project = root / "example-project"
    for relative, content in plan["project_layout"].items():
        path = project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    # The manifest's bytes are what obligation_manifest_hash binds, so it is copied
    # rather than re-serialized: a reformatting round-trip would be a different hash.
    shutil.copyfile(OBLIGATIONS_EXAMPLE, project / ".fv" / "obligations.json")
    git_repository(project)
    return project


def write_raw_artifacts(project: Path, example: dict) -> None:
    """Every declared raw log, as captured lines plus the one canonical trailer."""
    plan = example["_materialization"]
    trailer = plan["raw_artifact_trailer"]
    for relative, lines in plan["raw_artifacts"].items():
        path = project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(f"{line}\n" for line in [*lines, trailer]))


def stub_executables(root: Path, example: dict) -> dict[str, dict[str, str]]:
    """A real file per launched binary: the executable identity a record binds.

    The examples name cargo, quint, and verus, none of which a CI host is required
    to have. What the record binds is a path and a content digest, so a stub file
    the suite writes and hashes is the same kind of evidence as the real binary's -
    and, unlike a literal digest, it is recomputable here.
    """
    binaries = {execution["command"][0]
                for record in example["records"]
                for execution in record["bindings"]["executions"]}
    directory = root / "toolchain"
    directory.mkdir(parents=True, exist_ok=True)
    resolved: dict[str, dict[str, str]] = {}
    for binary in sorted(binaries):
        path = directory / binary
        path.write_text(f"#!/bin/sh\n# {binary} stand-in for R37 executable identity\n")
        path.chmod(0o755)
        resolved[binary] = {"executable": str(path), "sha256": digest(path.read_bytes())}
    return resolved


def materialize(example: dict, project: Path,
                executables: dict[str, dict[str, str]]) -> dict:
    """Replace every declared placeholder with the value it stands for."""
    materialized = copy.deepcopy(example)
    snapshot = fv_project.content_snapshot(project)
    intent_hash = fv_project.target_hash(project)
    manifest_hash = digest((project / ".fv" / "obligations.json").read_bytes())
    for record in materialized["records"]:
        bindings = record["bindings"]
        bindings["source_snapshot"] = snapshot
        bindings["intent_hash"] = intent_hash
        bindings["obligation_manifest_hash"] = manifest_hash
        for execution in bindings["executions"]:
            execution["toolchain_digests"].update(executables[execution["command"][0]])
            execution["raw_output_hash"] = digest(
                (project / execution["raw_output_path"]).read_bytes())
        # The record-level bindings are executions[0]'s verbatim; deriving them here
        # rather than filling them separately is the rule Gate B enforces.
        primary = bindings["executions"][0]
        bindings["toolchain_digests"] = copy.deepcopy(primary["toolchain_digests"])
        bindings["raw_output_hash"] = primary["raw_output_hash"]
    return materialized


def publish(project: Path, payload: dict, directory: str) -> Path:
    """Write a record set under .fv/evidence/, which no snapshot ever includes."""
    records = project / ".fv" / "evidence" / directory
    records.mkdir(parents=True, exist_ok=True)
    (records / "evidence-records.example.json").write_text(
        json.dumps(payload, indent=2) + "\n")
    return records


def run_gate(records: Path, project: Path) -> tuple[int, dict, str]:
    """Gate B at its default freshness discipline: it recomputes, nothing is pinned."""
    run = subprocess.run(
        ["python3", str(GATE), "--records", str(records), "--root", str(project),
         "--manifest", str(project / ".fv" / "obligations.json"), "--json"],
        capture_output=True, text=True)
    try:
        report = json.loads(run.stdout)
    except json.JSONDecodeError:
        report = {}
    return run.returncode, report, run.stderr


def defects(report: dict, claim_id: str) -> str:
    for entry in report.get("per_claim", []):
        if entry.get("claim_id") == claim_id:
            return "; ".join(entry.get("defects", [])) or entry.get("status", "")
    return ""


def check_examples(root: Path) -> None:
    example = json.loads(RECORDS_EXAMPLE.read_text())
    project = build_project(root, example)
    write_raw_artifacts(project, example)
    executables = stub_executables(root, example)
    materialized = materialize(example, project, executables)

    required, kinds, claim_evidence, claim_depends = gate_module.load_manifest(
        project / ".fv" / "obligations.json")
    check("the obligation example declares one invariant and one system claim",
          kinds == {"A1": "invariant", "S1": "system_claim"}, kinds)
    check("S1 requires evidence from three tools and depends on A1",
          claim_evidence == {"S1": ["quint", "verus", "cargo-kani"]}
          and claim_depends == {"S1": ["A1"]},
          (claim_evidence, claim_depends))
    check("the record example covers every declared obligation",
          sorted(record["claim_id"] for record in example["records"]) == sorted(required),
          (required, [record["claim_id"] for record in example["records"]]))
    check("materialization leaves no placeholder behind",
          "<" not in json.dumps(materialized["records"]),
          [field for field in json.dumps(materialized["records"]).split('"') if "<" in field])

    records = publish(project, materialized, "records")
    code, report, banner = run_gate(records, project)
    check("Gate B answers VERIFIED over the materialized examples",
          code == 0, (code, report.get("incomplete"), report.get("failed")))
    check("the verdict is the unqualified producer-profile banner",
          banner.strip() == "VERDICT: VERIFIED[profile=producer-trusted-execution]", banner.strip())
    check("the verdict was earned against recomputed bindings",
          report.get("binding") == "recomputed"
          and report.get("expected_snapshot") == materialized["records"][0]["bindings"]["source_snapshot"]
          and report.get("intent_path") == ".fv/intent.md",
          (report.get("binding"), report.get("intent_path")))
    check("both claims pass on their own record",
          [(entry["claim_id"], entry["status"]) for entry in report.get("per_claim", [])]
          == [("A1", "PASS"), ("S1", "PASS")], report.get("per_claim"))

    # Control 0: the shipped placeholders are not a tolerated dialect. The example
    # says a record carrying one is rejected; this is that claim.
    code, report, _ = run_gate(publish(project, example, "records-placeholder"), project)
    check("the unmaterialized example is rejected rather than tolerated",
          code == 3 and all(defects(report, claim) for claim in ("A1", "S1")),
          (code, defects(report, "A1")))

    # Control 1: the artifacts are hash-bound, so the PASS survives only while the
    # logs are the bytes the records committed to.
    quint_log = project / ".fv" / "evidence" / "raw" / "S1-2026-09-15T11-58-02-104Z-1-quint.log"
    original = quint_log.read_bytes()
    quint_log.write_bytes(original.replace(b"No violation found", b"No violation found "))
    code, report, _ = run_gate(records, project)
    check("a tampered raw log invalidates the system claim",
          code == 3 and "raw output hash mismatch" in defects(report, "S1"),
          (code, defects(report, "S1")))
    quint_log.write_bytes(original)

    # Control 2: required_evidence is a coverage condition, not a label. Dropping the
    # Verus execution leaves executions[0] - and every legacy binding derived from
    # it - untouched, so only the coverage rule can reject what remains.
    uncovered = copy.deepcopy(materialized)
    cohort = uncovered["records"][1]["bindings"]["executions"]
    uncovered["records"][1]["bindings"]["executions"] = [
        execution for execution in cohort if execution["tool"] != "verus"]
    code, report, _ = run_gate(publish(project, uncovered, "records-uncovered"), project)
    check("a cohort missing a required tool cannot discharge the system claim",
          code == 3
          and "system claim missing PASS evidence from required tools ['verus']" in defects(report, "S1"),
          (code, defects(report, "S1")))

    # Control 3: the snapshot is the project's verified inputs, so moving one stales
    # every record bound to it. This is what --allow-unbound would have hidden.
    (project / "specs" / "rcv.qnt").write_text("module rcv {\n  val eliminationOrderAgrees = false\n}\n")
    code, report, _ = run_gate(records, project)
    check("moving a verified input stales both records",
          code == 3
          and all("stale record: bound to snapshot" in defects(report, claim)
                  for claim in ("A1", "S1")),
          (code, defects(report, "A1"), defects(report, "S1")))


def main() -> int:
    if shutil.which("git") is None:
        print("SKIP-FAIL: git not on PATH; the verified-input snapshot is not computable")
        return 2
    print("R37: shipped v3 evidence examples")
    with tempfile.TemporaryDirectory() as temporary:
        check_examples(Path(temporary))
    print()
    if FAILURES:
        print(f"R37: {len(FAILURES)} failure(s)")
        return 1
    print("R37: all assertions passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
