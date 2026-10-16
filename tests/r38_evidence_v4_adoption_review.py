#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6,<7"]
# ///
"""R38 adoption findings: refresh containment, CLI paths and error counters."""

from __future__ import annotations

import copy
import hashlib
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "tests"))

import fv_init
import fv_project
from evidence_v4_fixture import EvidenceV4Fixture, rewrite_json
from fv_evidence_v4 import D, H, V4Error, _read_entry, _tool

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

    def test_refresh_requires_existing_project_state_without_creating_it(self):
        with tempfile.TemporaryDirectory() as name:
            temporary = Path(name).resolve()
            project = temporary / "project"
            project.mkdir()
            proc = cli(INIT, temporary, project, "--refresh-project-scripts")
            self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
            self.assertIn("refresh requires an existing .fv directory", proc.stdout)
            self.assertEqual(list(project.iterdir()), [])

    def test_refresh_flushes_staged_helpers_before_rename_and_directories_after(self):
        with tempfile.TemporaryDirectory() as name:
            temporary = Path(name).resolve()
            project, _ = self.make_project(temporary)
            destination = project / ".fv/scripts" / fv_project.PROJECT_SCRIPT_NAMES[0]
            source = REPO / "scripts" / destination.name
            events = []
            fsync = os.fsync
            replace = Path.replace

            def record_sync(descriptor):
                info = os.fstat(descriptor)
                if stat.S_ISREG(info.st_mode):
                    events.append("file-sync")
                    self.assertEqual(
                        os.pread(descriptor, info.st_size, 0), source.read_bytes()
                    )
                else:
                    events.append(("directory-sync", info.st_ino))
                fsync(descriptor)

            def record_replace(staged, target):
                events.append("replace")
                return replace(staged, target)

            results = []
            with (
                patch.object(fv_init.os, "fsync", side_effect=record_sync),
                patch.object(Path, "replace", record_replace),
            ):
                fv_init._copy_owned_file(source, destination, True, results)
            self.assertEqual(
                events,
                [
                    "file-sync",
                    "replace",
                    ("directory-sync", destination.parent.stat().st_ino),
                    ("directory-sync", destination.parent.parent.stat().st_ino),
                ],
            )
            self.assertEqual(results, [("overwrote", destination)])

    def test_refresh_reports_partial_replacements_before_fatal_copy_or_sync_error(self):
        for defect in ("copy", "directory-sync"):
            with self.subTest(defect=defect), tempfile.TemporaryDirectory() as name:
                project, _ = self.make_project(Path(name).resolve())
                scripts = project / ".fv/scripts"
                original = {path.name: path.read_bytes() for path in scripts.iterdir()}
                copy_file, fsync = fv_init.shutil.copy2, os.fsync
                calls = 0

                def fail_copy(source, destination):
                    nonlocal calls
                    calls += 1
                    if calls == 3:
                        raise OSError("injected copy failure")
                    return copy_file(source, destination)

                def fail_directory_sync(descriptor):
                    if stat.S_ISDIR(os.fstat(descriptor).st_mode):
                        raise OSError("injected directory-sync failure")
                    return fsync(descriptor)

                output = io.StringIO()
                with (
                    patch.object(
                        sys,
                        "argv",
                        [str(INIT), str(project), "--refresh-project-scripts"],
                    ),
                    patch.object(
                        fv_init.shutil,
                        "copy2",
                        side_effect=fail_copy if defect == "copy" else copy_file,
                    ),
                    patch.object(
                        fv_init.os,
                        "fsync",
                        side_effect=fail_directory_sync
                        if defect == "directory-sync"
                        else fsync,
                    ),
                    redirect_stdout(output),
                ):
                    self.assertEqual(fv_init.main(), 1)
                text = output.getvalue()
                changed = fv_project.PROJECT_SCRIPT_NAMES[
                    : 2 if defect == "copy" else 1
                ]
                for helper in changed:
                    self.assertIn(f"[overwrote] .fv/scripts/{helper}", text)
                    self.assertLess(
                        text.index(f".fv/scripts/{helper}"), text.index("FATAL:")
                    )
                for helper in fv_project.PROJECT_SCRIPT_NAMES:
                    self.assertEqual(
                        (scripts / helper).read_bytes(),
                        (REPO / "scripts" / helper).read_bytes()
                        if helper in changed
                        else original[helper],
                    )
                self.assertIn(f"injected {defect} failure", text)
                self.assertEqual(
                    {path.name for path in scripts.iterdir()}, set(original)
                )

    def test_nonforce_init_skips_existing_symlinked_and_hardlinked_helpers(self):
        for arrangement in ("symlink", "hardlink"):
            with (
                self.subTest(arrangement=arrangement),
                tempfile.TemporaryDirectory() as name,
            ):
                temporary = Path(name).resolve()
                project = temporary / "project"
                initialized = cli(INIT, temporary, project)
                self.assertEqual(
                    initialized.returncode, 0, initialized.stdout + initialized.stderr
                )
                linked = []
                for helper in fv_project.PROJECT_SCRIPT_NAMES:
                    destination = project / ".fv/scripts" / helper
                    external = temporary / helper
                    external.write_bytes(destination.read_bytes())
                    destination.unlink()
                    if arrangement == "symlink":
                        destination.symlink_to(external)
                    else:
                        os.link(external, destination)
                    linked.append((destination, external, destination.lstat().st_ino))
                proc = cli(INIT, temporary, project)
                self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
                for destination, external, inode in linked:
                    self.assertEqual(destination.lstat().st_ino, inode)
                    self.assertEqual(destination.read_bytes(), external.read_bytes())
                    self.assertIn(
                        f"[     skip] .fv/scripts/{destination.name}", proc.stdout
                    )


class CwdRelativeRecords(unittest.TestCase):
    def test_entry_normalizes_dotdot_before_containment_and_preserves_link_checks(self):
        with tempfile.TemporaryDirectory() as name:
            temporary = Path(name).resolve()
            project = temporary / "project"
            nested = project / "docs"
            nested.mkdir(parents=True)
            (temporary / "sibling").mkdir()
            current = project / ".fv/evidence/v4/current.json"
            rewrite_json(current, {"entry": "retained"})
            for spelling in (
                nested / "../.fv/evidence/v4/current.json",
                temporary / "sibling/../project/.fv/evidence/v4/current.json",
                Path("docs/../.fv/evidence/v4/current.json"),
            ):
                with self.subTest(spelling=spelling):
                    value, relative = _read_entry(project, spelling)
                    self.assertEqual(value, {"entry": "retained"})
                    self.assertEqual(relative, ".fv/evidence/v4/current.json")
            alias = project / ".fv/evidence/alias"
            alias.symlink_to("v4", target_is_directory=True)
            with self.assertRaisesRegex(V4Error, "symlink"):
                _read_entry(project, nested / "../.fv/evidence/alias/current.json")
            with self.assertRaisesRegex(V4Error, "outside project root"):
                _read_entry(project, nested / "../../outside.json")

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

    def test_v4_dashboard_and_gate_accept_nested_and_sibling_dotdot_paths(self):
        with EvidenceV4Fixture() as fixture:
            result = fixture.run(jobs=1)
            self.assertEqual(result["result"], "PASS", result)
            current = fixture.evidence_root / "current.json"
            manifest = fixture.manifest(result)
            claims = (fixture.root / manifest["claims"][0]["record"]["path"]).parent
            sibling = fixture.temporary / "sibling"
            sibling.mkdir()
            alias = fixture.evidence_root / "records-alias"
            alias.symlink_to("runs", target_is_directory=True)
            for script, extra in ((DASHBOARD, ()), (GATE, ("--allow-unbound",))):
                for cwd in (fixture.root / "notes", sibling):
                    for records in (current, claims):
                        with self.subTest(
                            script=script.name, cwd=cwd.name, records=records
                        ):
                            spelling = os.path.relpath(records, cwd)
                            self.assertIn("..", Path(spelling).parts)
                            proc = cli(
                                script, cwd, "--records", spelling, *extra, "--json"
                            )
                            self.assertEqual(
                                proc.returncode, 0, proc.stdout + proc.stderr
                            )
                            report = json.loads(proc.stdout)
                            self.assertTrue(
                                report["verdict"].startswith("COVERED["), report
                            )
                            self.assertEqual(report["repo_root"], str(fixture.root))
                    aliased = alias / manifest["run_id"] / "run.json"
                    refused = cli(
                        script,
                        cwd,
                        "--records",
                        os.path.relpath(aliased, cwd),
                        *extra,
                        "--json",
                    )
                    self.assertEqual(
                        refused.returncode, 2, refused.stdout + refused.stderr
                    )
                    self.assertIn("symlink", refused.stdout + refused.stderr)
            self.assertEqual(fixture.count(), 1)

    def test_v3_dashboard_and_gate_accept_parent_relative_file_and_directory(self):
        with tempfile.TemporaryDirectory() as name:
            temporary = Path(name).resolve()
            project = temporary / "project"
            intent = project / ".fv/intent.md"
            nested = project / "docs"
            sibling = temporary / "sibling"
            nested.mkdir(parents=True)
            sibling.mkdir()
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
                    spellings = [
                        (temporary, path.relative_to(temporary)),
                        (temporary, path),
                        (nested, os.path.relpath(path, nested)),
                        (sibling, os.path.relpath(path, sibling)),
                    ]
                    for cwd, spelling in spellings:
                        with self.subTest(
                            script=script.name, cwd=cwd, records=spelling
                        ):
                            proc = cli(
                                script,
                                cwd,
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


class DerivedNativeToolIdentity(unittest.TestCase):
    def make_identity(self, kind):
        declaration = {
            "id": "linked-tool",
            "kind": kind,
            "locator": {"mode": "path", "value": "/reviewed/linked-tool"},
            "version_command": None,
            "version_cwd": None,
            "requires": [],
            "accept": {"sha256": [], "version_contains": []},
        }
        value = {
            "id": declaration["id"],
            "kind": "tree",
            "locator": declaration["locator"],
            "files": [
                {
                    "path": "selected-file",
                    "kind": "file",
                    "hash": H(b"tool"),
                    "size": 4,
                    "executable": kind == "executable",
                },
                {"path": "native", "kind": "directory"},
                {"path": "native/non-system-libraries", "kind": "directory"},
                {
                    "path": "native/non-system-libraries/%2Fopt%2Freviewed%2Flibfixture.dylib",
                    "kind": "file",
                    "hash": H(b"library"),
                    "size": 7,
                    "executable": False,
                },
            ],
            "packages": [],
            "version": None,
            "discovery": [],
            "system_dependencies": {
                "os": "darwin",
                "arch": "arm64",
                "release": "reviewed",
                "sdk": None,
            },
            "requires": [],
        }
        self.identify(value)
        return declaration, value

    @staticmethod
    def identify(value):
        value["files"].sort(key=lambda entry: entry["path"].encode("utf-8"))
        value["digest"] = D(
            "tool-content",
            {
                key: value[key]
                for key in ("kind", "files", "packages", "system_dependencies")
            },
        )

    def test_file_and_executable_declarations_accept_only_native_derived_tree_roots(
        self,
    ):
        for kind in ("executable", "file"):
            with self.subTest(kind=kind):
                declaration, value = self.make_identity(kind)
                _tool(value, declaration)
                single = copy.deepcopy(value)
                single["kind"] = kind
                single["files"] = [
                    {
                        **next(
                            entry
                            for entry in value["files"]
                            if entry["path"] == "selected-file"
                        ),
                        "path": ".",
                    },
                ]
                self.identify(single)
                _tool(single, declaration)
        for defect in (
            "no-native",
            "wrong-selected",
            "extra-root",
            "helper-root",
            "encoded-slash-case",
            "encoded-unreserved",
            "invalid-utf8",
            "nonexecutable",
            "empty-library",
            "wrong-platform",
            "locator-drift",
            "library-byte-drift",
        ):
            with self.subTest(defect=defect):
                declaration, value = self.make_identity("executable")
                selected = next(
                    entry
                    for entry in value["files"]
                    if entry["path"] == "selected-file"
                )
                library = next(
                    entry
                    for entry in value["files"]
                    if entry["path"].startswith("native/non-system-libraries/")
                )
                if defect == "no-native":
                    value["files"] = [selected]
                elif defect == "wrong-selected":
                    selected["path"] = "."
                elif defect == "extra-root":
                    value["files"].append({**selected, "path": "unreviewed"})
                elif defect == "helper-root":
                    value["files"].append(
                        {"path": "discovery-helpers", "kind": "directory"}
                    )
                elif defect == "encoded-slash-case":
                    library["path"] = library["path"].replace("%2F", "%2f")
                elif defect == "encoded-unreserved":
                    library["path"] = "native/non-system-libraries/%41"
                elif defect == "invalid-utf8":
                    library["path"] = "native/non-system-libraries/%FF"
                elif defect == "nonexecutable":
                    selected["executable"] = False
                elif defect == "empty-library":
                    library.update(hash=H(b""), size=0)
                elif defect == "wrong-platform":
                    value["system_dependencies"]["os"] = "linux"
                elif defect == "locator-drift":
                    value["locator"] = {"mode": "path", "value": "/other/linked-tool"}
                elif defect == "library-byte-drift":
                    library["hash"] = H(b"changed")
                if defect != "library-byte-drift":
                    self.identify(value)
                with self.assertRaises(V4Error):
                    _tool(value, declaration)

    def test_rustup_driver_only_and_library_trees_reject_unreviewed_driver_roots(self):
        for names in (("cargo-0",), ("rustc-0",), ("cargo-0", "rustc-0")):
            for libraries in (False, True):
                with self.subTest(drivers=names, libraries=libraries):
                    declaration, value = self.make_identity("executable")
                    declaration["locator"] = {
                        "mode": "path" if libraries else "command",
                        "value": "/reviewed/" + names[0][:-2]
                        if libraries
                        else names[0][:-2],
                    }
                    value["locator"] = declaration["locator"]
                    value["discovery"] = [
                        {
                            "command": ["/reviewed/rustup", "which", name[:-2]],
                            "cwd": ".",
                            "stdout_hash": H(b"selected driver"),
                            "stderr_hash": H(b""),
                            "exit_code": 0,
                        }
                        for name in names
                    ]
                    if not libraries:
                        value["files"] = [
                            entry
                            for entry in value["files"]
                            if not entry["path"].startswith(
                                "native/non-system-libraries"
                            )
                        ]
                    value["files"].append(
                        {"path": "native/drivers", "kind": "directory"}
                    )
                    value["files"].extend(
                        {
                            "path": "native/drivers/" + name,
                            "kind": "file",
                            "hash": H(b"driver"),
                            "size": 6,
                            "executable": True,
                        }
                        for name in names
                    )
                    self.identify(value)
                    _tool(value, declaration)
        for defect in (
            "unknown-driver",
            "wrong-index",
            "nonexecutable",
            "empty-driver",
            "directory-only",
            "wrong-locator",
            "wrong-locator-mode",
            "missing-probe",
            "wrong-probe-name",
            "wrong-probe-command",
            "missing-sibling-probe",
        ):
            with self.subTest(defect=defect):
                declaration, value = self.make_identity("executable")
                declaration["locator"] = {"mode": "command", "value": "cargo"}
                value["locator"] = declaration["locator"]
                value["discovery"] = [
                    {
                        "command": ["/reviewed/rustup", "which", "cargo"],
                        "cwd": ".",
                        "stdout_hash": H(b"selected driver"),
                        "stderr_hash": H(b""),
                        "exit_code": 0,
                    },
                ]
                value["files"] = [
                    entry
                    for entry in value["files"]
                    if not entry["path"].startswith("native/non-system-libraries")
                ]
                driver = {
                    "path": "native/drivers/cargo-0",
                    "kind": "file",
                    "hash": H(b"driver"),
                    "size": 6,
                    "executable": True,
                }
                value["files"].append({"path": "native/drivers", "kind": "directory"})
                if defect == "unknown-driver":
                    driver["path"] = "native/drivers/rustup-0"
                elif defect == "wrong-index":
                    driver["path"] = "native/drivers/cargo-1"
                elif defect == "nonexecutable":
                    driver["executable"] = False
                elif defect == "empty-driver":
                    driver.update(hash=H(b""), size=0)
                elif defect == "wrong-locator":
                    declaration["locator"]["value"] = "rustc"
                elif defect == "wrong-locator-mode":
                    declaration["locator"] = {
                        "mode": "command-relative",
                        "value": "cargo",
                        "parent_levels": 0,
                        "subpath": "cargo",
                    }
                    value["locator"] = declaration["locator"]
                elif defect == "missing-probe":
                    value["discovery"] = []
                elif defect == "wrong-probe-name":
                    value["discovery"][0]["command"][-1] = "rustc"
                elif defect == "wrong-probe-command":
                    value["discovery"][0]["command"][0] = "/reviewed/not-rustup"
                elif defect == "missing-sibling-probe":
                    value["files"].append({**driver, "path": "native/drivers/rustc-0"})
                if defect != "directory-only":
                    value["files"].append(driver)
                self.identify(value)
                with self.assertRaises(V4Error):
                    _tool(value, declaration)


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
                    for key in (
                        "unique_physical_executions",
                        "actual_dispatches",
                        "cache_hits",
                    ):
                        self.assertIsNone(report["counts"][key], report)
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
                    self.assertIn(
                        "unique-physical-executions=not-assessed "
                        "actual-dispatches=not-assessed cache-hits=not-assessed",
                        text.stdout,
                    )

    def test_pre_expansion_run_and_policy_errors_leave_counts_unassessed(self):
        with EvidenceV4Fixture() as fixture:
            result = fixture.run(jobs=1)
            self.assertEqual(result["result"], "PASS", result)
            run_path = fixture.root / result["run"]["path"]
            policy_path = fixture.root / fixture.policy_path
            for target in (run_path, policy_path):
                with self.subTest(target=target.name):
                    original = target.read_bytes()
                    try:
                        target.write_bytes(b"{}\n")
                        report, code = fixture.assess(
                            records_path=run_path,
                            recompute=False,
                            recheck_observations=False,
                        )
                        self.assertEqual(code, 2, report)
                        self.assertEqual(report["per_claim"], [])
                        for key in (
                            "logical_associations",
                            "unique_physical_executions",
                            "actual_dispatches",
                            "cache_hits",
                        ):
                            self.assertIsNone(report["counts"][key], report)
                    finally:
                        target.write_bytes(original)


if __name__ == "__main__":
    unittest.main()
