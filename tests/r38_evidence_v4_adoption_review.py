#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6,<7"]
# ///
"""R38 adoption findings: refresh containment, CLI paths and error counters."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "tests"))

import fv_project
from evidence_v4_fixture import EvidenceV4Fixture, rewrite_json
from fv_evidence_v4 import H

INIT = REPO / "scripts/fv_init.py"
DASHBOARD = REPO / "scripts/coverage_dashboard.py"
GATE = REPO / "scripts/check_evidence_records.py"


def cli(script: Path, cwd: Path, *args: object) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(script), *(str(arg) for arg in args)],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=120,
    )


class RefreshContainment(unittest.TestCase):
    def make_project(self, temporary: Path) -> tuple[Path, list[Path]]:
        project = temporary / "project"
        scripts = project / ".fv/scripts"
        scripts.mkdir(parents=True)
        preserved = []
        for relative, content in (
            ("docs/intent.md", b"# Canonical intent\nPreserve these exact bytes.\n"),
            (".fv/history/retained.json", b'{ "retained": true }\n'),
            (".fv/verified-inputs.txt", b"mode: include\ndocs/intent.md\n"),
            (".fv/dispatch.json", b'{ "opaque": "preserve" }\n'),
            (".fv/scripts/local.py", b"# Project-owned helper\n"),
        ):
            path = project / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            preserved.append(path)
        for name in fv_project.PROJECT_SCRIPT_NAMES:
            (scripts / name).write_bytes(f"# Stale {name}\n".encode())
        return project, preserved

    def test_refresh_rejects_aliased_destinations_before_writing(self):
        for arrangement in (
            "file-symlink",
            "dangling-symlink",
            "scripts-symlink",
            "fv-symlink",
            "intent-hardlink",
            "history-hardlink",
        ):
            with (
                self.subTest(arrangement=arrangement),
                tempfile.TemporaryDirectory() as name,
            ):
                temporary = Path(name).resolve()
                project, preserved = self.make_project(temporary)
                scripts = project / ".fv/scripts"
                destination = scripts / fv_project.PROJECT_SCRIPT_NAMES[-1]
                intent = project / "docs/intent.md"
                history = project / ".fv/history/retained.json"
                protected = {path: path.read_bytes() for path in preserved}
                if arrangement == "scripts-symlink":
                    external = temporary / "external-scripts"
                    scripts.rename(external)
                    scripts.symlink_to(external, target_is_directory=True)
                elif arrangement == "fv-symlink":
                    external = temporary / "external-fv"
                    (project / ".fv").rename(external)
                    (project / ".fv").symlink_to(external, target_is_directory=True)
                else:
                    destination.unlink()
                    if arrangement == "file-symlink":
                        destination.symlink_to(intent)
                    elif arrangement == "dangling-symlink":
                        destination.symlink_to(project / "docs/missing.md")
                    else:
                        os.link(
                            intent if arrangement == "intent-hardlink" else history,
                            destination,
                        )
                installed = {
                    path: path.read_bytes()
                    for path in (
                        scripts / name for name in fv_project.PROJECT_SCRIPT_NAMES
                    )
                    if path.exists()
                }
                proc = cli(INIT, temporary, project, "--refresh-project-scripts")
                self.assertEqual(
                    {path: path.read_bytes() for path in protected},
                    protected,
                    proc.stdout + proc.stderr,
                )
                self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
                self.assertIn("FATAL:", proc.stdout)
                self.assertIn(
                    "multiply-linked"
                    if arrangement.endswith("hardlink")
                    else "symlink",
                    proc.stdout,
                )
                self.assertEqual(
                    {
                        path: path.read_bytes()
                        for path in (
                            scripts / name for name in fv_project.PROJECT_SCRIPT_NAMES
                        )
                        if path.exists()
                    },
                    installed,
                )
                self.assertFalse((project / "docs/missing.md").exists())

    def test_refresh_replaces_only_canonical_helpers_without_truncating_old_inodes(
        self,
    ):
        with tempfile.TemporaryDirectory() as name, ExitStack() as handles:
            temporary = Path(name).resolve()
            project, preserved = self.make_project(temporary)
            scripts = project / ".fv/scripts"
            protected = {path: path.read_bytes() for path in preserved}
            original_names = {path.name for path in scripts.iterdir()}
            opened = {
                name: handles.enter_context((scripts / name).open("rb"))
                for name in fv_project.PROJECT_SCRIPT_NAMES
            }
            old_bytes = {name: (scripts / name).read_bytes() for name in opened}
            proc = cli(INIT, temporary, project, "--refresh-project-scripts")
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            for name, handle in opened.items():
                with self.subTest(helper=name):
                    self.assertEqual(
                        (scripts / name).read_bytes(),
                        (REPO / "scripts" / name).read_bytes(),
                    )
                    self.assertEqual(handle.read(), old_bytes[name])
            self.assertEqual({path: path.read_bytes() for path in protected}, protected)
            self.assertEqual({path.name for path in scripts.iterdir()}, original_names)


class CwdRelativeRecords(unittest.TestCase):
    def test_v4_dashboard_and_gate_accept_parent_relative_records_without_resolving_links(
        self,
    ):
        with EvidenceV4Fixture() as fixture:
            result = fixture.run(jobs=1)
            self.assertEqual(result["result"], "PASS", result)
            current = fixture.evidence_root / "current.json"
            for script, extra in ((DASHBOARD, ()), (GATE, ("--allow-unbound",))):
                for records in (current.relative_to(fixture.root.parent), current):
                    with self.subTest(script=script.name, records=records):
                        proc = cli(
                            script,
                            fixture.root.parent,
                            "--records",
                            records,
                            *extra,
                            "--json",
                        )
                        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
                        report = json.loads(proc.stdout)
                        self.assertTrue(
                            report["verdict"].startswith("COVERED["), report
                        )
                        self.assertEqual(set(report["required_claims"]), {"A", "B"})
                        self.assertEqual(report["repo_root"], str(fixture.root))
                        self.assertEqual(report["counts"]["logical_associations"], 2)
                alias = fixture.evidence_root / (script.stem + "-alias.json")
                alias.symlink_to(current.name)
                directory_alias = fixture.evidence_root.parent / (
                    script.stem + "-alias"
                )
                directory_alias.symlink_to(
                    fixture.evidence_root.name, target_is_directory=True
                )
                for records in (alias, directory_alias / current.name):
                    with self.subTest(script=script.name, symlink=records):
                        proc = cli(
                            script,
                            fixture.root.parent,
                            "--records",
                            records.relative_to(fixture.root.parent),
                            *extra,
                            "--json",
                        )
                        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
                        self.assertIn("VERDICT: ERROR", proc.stderr)
                        self.assertIn("symlink", proc.stdout + proc.stderr)
            self.assertEqual(fixture.count(), 1)

    def test_v3_dashboard_and_gate_accept_parent_relative_file_and_directory(self):
        with tempfile.TemporaryDirectory() as name:
            temporary = Path(name).resolve()
            project = temporary / "project"
            intent = project / ".fv/intent.md"
            intent.parent.mkdir(parents=True)
            intent.write_bytes(b"# Legacy canonical intent\n")
            raw = b"--- fv-evidence: exit=0 ---\n"
            raw_hash = hashlib.sha256(raw).hexdigest()
            raw_path = ".fv/evidence/raw/A-r38-legacy.log"
            (project / raw_path).parent.mkdir(parents=True)
            (project / raw_path).write_bytes(raw)
            execution = {
                "tool": "fixture",
                "evidence_class": "code-enforced",
                "command": ["fixture", "verify"],
                "cwd": ".",
                "toolchain_digests": {
                    "executable": str(Path(sys.executable).resolve()),
                    "sha256": "4" * 64,
                    "version": "fixture",
                    "version_exit_code": 0,
                },
                "raw_output_path": raw_path,
                "raw_output_hash": raw_hash,
                "result": "PASS",
                "run_id": "r38-legacy",
            }
            records = project / ".fv/evidence/records/A.json"
            rewrite_json(
                records,
                {
                    "claim_id": "A",
                    "required": True,
                    "evidence_class": "code-enforced",
                    "result": "PASS",
                    "scope": "legacy CLI path regression",
                    "waiver": None,
                    "bindings": {
                        "source_snapshot": "sha256:" + "a" * 64,
                        "intent_path": ".fv/intent.md",
                        "intent_hash": hashlib.sha256(intent.read_bytes()).hexdigest(),
                        "obligation_manifest_hash": "2" * 64,
                        "profile": "producer-trusted-execution",
                        "required_targets": ["A"],
                        "environment_policy": "omp-extension-tool",
                        "toolchain_digests": execution["toolchain_digests"],
                        "command": json.dumps(execution["command"]),
                        "configuration": {"cwd": "."},
                        "seeds": None,
                        "raw_output_hash": raw_hash,
                        "raw_output_path": raw_path,
                        "parser_schema_version": "fv-evidence-run/v3",
                        "run_id": "r38-legacy",
                        "executions": [execution],
                    },
                },
            )
            for script, extra in ((DASHBOARD, ()), (GATE, ("--allow-unbound",))):
                for path in (records, records.parent):
                    for spelling in (path.relative_to(temporary), path):
                        with self.subTest(script=script.name, records=spelling):
                            proc = cli(
                                script,
                                temporary,
                                "--records",
                                spelling,
                                "--require",
                                "A",
                                *extra,
                                "--json",
                            )
                            self.assertEqual(
                                proc.returncode, 0, proc.stdout + proc.stderr
                            )
                            report = json.loads(proc.stdout)
                            self.assertTrue(
                                report["verdict"].startswith("VERIFIED["), report
                            )
                            self.assertEqual(report["required_claims"], ["A"])


class EarlyErrorCounts(unittest.TestCase):
    def test_post_expansion_binding_and_interval_errors_count_missing_rows_in_json_and_text(
        self,
    ):
        with EvidenceV4Fixture() as fixture:
            result = fixture.run(jobs=1)
            self.assertEqual(result["result"], "PASS", result)
            original = fixture.manifest(result)
            run_path = fixture.root / result["run"]["path"]
            for defect in ("binding", "interval"):
                with self.subTest(defect=defect):
                    manifest = copy.deepcopy(original)
                    if defect == "binding":
                        manifest["common"]["intent_hash"] = H(b"mismatched intent")
                        expected = "run common/policy/trust binding mismatch"
                    else:
                        manifest["finished_at"] = "1970-01-01T00:00:00.000Z"
                        expected = "invalid run interval or scheduling bound"
                    rewrite_json(run_path, manifest)
                    report, code = fixture.assess(
                        records_path=run_path,
                        recompute=False,
                        recheck_observations=False,
                    )
                    self.assertEqual(code, 2, report)
                    self.assertEqual(report["verdict"], "ERROR")
                    self.assertIn(expected, report["errors"])
                    slots = [
                        slot
                        for row in report["per_claim"]
                        for slot in row["executions"]
                    ]
                    self.assertEqual(len(slots), 2)
                    self.assertTrue(all(slot["state"] == "MISSING" for slot in slots))
                    self.assertEqual(
                        report["counts"]["logical_associations"], len(slots)
                    )
                    self.assertEqual(
                        report["counts"]["missing_associations"], len(slots)
                    )
                    for key in (
                        "failed_associations",
                        "error_associations",
                        "cancelled_associations",
                    ):
                        self.assertEqual(report["counts"][key], 0)
                    proc = cli(DASHBOARD, fixture.root, "--records", run_path, "--json")
                    self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
                    dashboard = json.loads(proc.stdout)
                    self.assertEqual(dashboard["verdict"], "ERROR")
                    self.assertEqual(dashboard["counts"], report["counts"])
                    self.assertEqual(
                        sum(len(row["executions"]) for row in dashboard["rows"]),
                        len(slots),
                    )
                    text = cli(DASHBOARD, fixture.root, "--records", run_path)
                    self.assertEqual(text.returncode, 2, text.stdout + text.stderr)
                    self.assertIn(
                        "association-work: missing=2 failed=0 error=0 cancelled=0",
                        text.stdout,
                    )
                    self.assertIn("VERDICT: ERROR", text.stderr)


if __name__ == "__main__":
    unittest.main()
