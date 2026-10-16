#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""M4 coverage over native-produced v4 evidence and rejection mutations."""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "tests"))

import coverage_dashboard as dashboard
from evidence_v4_fixture import (
    EvidenceV4Fixture,
    load_json,
    reidentify_claim,
    rewrite_json,
)
from fv_evidence_v4 import H
from r38_evidence_v4_lifecycle import (
    CANCEL_STDOUT,
    CANCEL_STDERR,
    cleanup_native_processes,
    direct_group_signals_supported,
    emit_before_cancellation,
    owner_path,
)

DASHBOARD = REPO / "scripts" / "coverage_dashboard.py"


def current_path(fixture) -> Path:
    return fixture.evidence_root / "current.json"


def rows_by_id(report: dict) -> dict[str, dict]:
    return {row["claim_id"]: row for row in report["rows"]}


def snapshot(fixture) -> dict[str, bytes]:
    return {
        str(path.relative_to(fixture.evidence_root)): path.read_bytes()
        for path in fixture.evidence_root.rglob("*")
        if path.is_file()
    }


def view(fixture, records_path=None, require=None):
    return dashboard.build_v4_dashboard(
        fixture.root, records_path or current_path(fixture), require=require
    )


def cli(fixture, records_path=None, *args):
    return subprocess.run(
        [
            sys.executable,
            str(DASHBOARD),
            "--records",
            str(records_path or current_path(fixture)),
            *args,
        ],
        cwd=fixture.root,
        capture_output=True,
        text=True,
        timeout=60,
    )


def file_ref(path: Path, root: Path) -> dict:
    data = path.read_bytes()
    return {
        "path": path.relative_to(root).as_posix(),
        "hash": H(data),
        "size": len(data),
    }


def mutate_claim(fixture, result, claim_id, mutate):
    """Rebind references after corrupting real output, so hashes do not mask the defect."""
    manifest = copy.deepcopy(fixture.manifest(result))
    entry = next(item for item in manifest["claims"] if item["claim_id"] == claim_id)
    path = fixture.root / entry["record"]["path"]
    record = load_json(path)
    mutate(record)
    rewrite_json(path, reidentify_claim(record))
    entry["record"] = file_ref(path, fixture.root)
    manifest_path = fixture.root / result["run"]["path"]
    rewrite_json(manifest_path, manifest)
    pointer = fixture.current()
    pointer["run"] = file_ref(manifest_path, fixture.root)
    rewrite_json(current_path(fixture), pointer)


@unittest.skipUnless(os.name == "posix", "v4 requires POSIX process ownership")
class CoverageV4(unittest.TestCase):
    def produce(self, fixture, **kwargs):
        result = fixture.run(jobs=1, **kwargs)
        self.assertEqual(result["result"], "PASS", result)
        self.assertIsNotNone(result["run"], result)
        return result

    def test_current_run_and_claim_keep_full_logical_scope_and_one_dispatch(self):
        with EvidenceV4Fixture() as fixture:
            result = self.produce(fixture)
            claim_path = (
                fixture.root / fixture.manifest(result)["claims"][0]["record"]["path"]
            )
            paths = (
                current_path(fixture),
                fixture.root / result["run"]["path"],
                claim_path,
            )
            for path in paths:
                with self.subTest(path=path):
                    proc = cli(fixture, path, "--json")
                    self.assertEqual(proc.returncode, 0, proc.stderr)
                    report = json.loads(proc.stdout)
                    self.assertEqual(report["binding"], "not-recomputed")
                    self.assertIn("binding=not-recomputed", report["verdict"])
                    self.assertEqual(set(report["required_claims"]), {"A", "B"})
                    self.assertEqual({r["status"] for r in report["rows"]}, {"PASS"})
                    self.assertEqual(report["counts"]["logical_associations"], 2)
                    self.assertEqual(report["counts"]["unique_physical_executions"], 1)
                    self.assertEqual(report["counts"]["actual_dispatches"], 1)
                    self.assertEqual(report["counts"]["cache_hits"], 0)
                    self.assertTrue(
                        all(len(r["executions"]) == 1 for r in report["rows"])
                    )
            self.assertEqual(fixture.count(), 1)

    def test_stored_view_executes_nothing_and_does_not_write_evidence(self):
        with EvidenceV4Fixture() as fixture:
            self.produce(fixture)
            before = snapshot(fixture)
            events = fixture.events()
            with (
                patch(
                    "subprocess.run",
                    side_effect=AssertionError("dashboard executed a process"),
                ),
                patch(
                    "subprocess.Popen",
                    side_effect=AssertionError("dashboard spawned a process"),
                ),
            ):
                report, code = view(fixture)
                text = dashboard.render_text(report)
            self.assertEqual(code, 0, report)
            self.assertEqual(report["binding"], "not-recomputed")
            self.assertIn("stored-only", report["pass_semantics"])
            self.assertIn("freshness and reuse eligibility are not assessed", text)
            self.assertEqual(snapshot(fixture), before)
            self.assertEqual(fixture.events(), events)
            self.assertEqual(fixture.count(), 1)

    def test_resume_counts_hits_separately_from_actual_dispatches(self):
        with EvidenceV4Fixture() as fixture:
            self.produce(fixture)
            self.produce(fixture, resume=True)
            report, code = view(fixture)
            self.assertEqual(code, 0, report)
            self.assertEqual(report["counts"]["logical_associations"], 2)
            self.assertEqual(report["counts"]["unique_physical_executions"], 1)
            self.assertEqual(report["counts"]["actual_dispatches"], 0)
            self.assertEqual(report["counts"]["cache_hits"], 1)
            self.assertEqual(fixture.count(), 1)
            self.assertEqual(
                report["summary"]["by_execution_evidence_class"]["test-witnessed"][
                    "pass"
                ],
                2,
            )

    def test_shared_member_observation_failure_does_not_fail_its_sibling(self):
        with EvidenceV4Fixture() as fixture:
            fixture.set_control(observation_fail=["B"])
            result = fixture.run(jobs=1)
            self.assertEqual(result["result"], "FAIL", result)
            report, code = view(fixture)
            rows = rows_by_id(report)
            self.assertEqual(code, 1, report)
            self.assertEqual(report["verdict"], "FAILED")
            self.assertEqual(rows["A"]["status"], "PASS")
            self.assertEqual(rows["B"]["status"], "FAIL")
            self.assertEqual(report["counts"]["unique_physical_executions"], 1)
            self.assertEqual(report["counts"]["actual_dispatches"], 1)
            self.assertEqual(report["counts"]["failed_associations"], 1)
            self.assertEqual(
                rows["A"]["executions"][0]["execution"],
                rows["B"]["executions"][0]["execution"],
            )
            self.assertEqual(
                rows["B"]["executions"][0]["observation"]["result"], "FAIL"
            )
            self.assertEqual(fixture.count(), 1)

    def test_selected_cached_member_keeps_unselected_member_failure_in_full_view(self):
        with EvidenceV4Fixture() as fixture:
            fixture.set_control(observation_fail=["B"])
            first = fixture.run(jobs=1)
            self.assertEqual(first["result"], "FAIL", first)
            fixture.set_control(observation_fail=[])
            selected = fixture.run(records=["A"], resume=True, jobs=1)
            self.assertEqual(selected["result"], "FAIL", selected)
            report, code = view(fixture)
            rows = rows_by_id(report)
            self.assertEqual(code, 1, report)
            self.assertEqual(set(report["required_claims"]), {"A", "B"})
            self.assertEqual(rows["A"]["status"], "PASS")
            self.assertEqual(rows["B"]["status"], "FAIL")
            self.assertTrue(rows["B"]["executions"][0]["blocking_events"])
            self.assertEqual(report["counts"]["logical_associations"], 2)
            self.assertEqual(report["counts"]["actual_dispatches"], 0)
            self.assertEqual(report["counts"]["cache_hits"], 1)
            self.assertEqual(fixture.count(), 1)

    def test_fail_fast_keeps_missing_work_and_full_required_fail_precedence(self):
        with EvidenceV4Fixture(recipe_count=2) as fixture:
            fixture.set_control(exit_code=7)
            result = fixture.run(jobs=1)
            self.assertEqual(result["result"], "FAIL", result)
            report, code = view(fixture)
            self.assertEqual(code, 1, report)
            self.assertEqual(report["verdict"], "FAILED")
            self.assertEqual(report["counts"]["logical_associations"], 4)
            self.assertEqual(report["counts"]["unique_physical_executions"], 1)
            self.assertEqual(report["counts"]["actual_dispatches"], 1)
            self.assertEqual(report["counts"]["failed_associations"], 2)
            self.assertEqual(report["counts"]["missing_associations"], 2)
            self.assertTrue(all(len(row["executions"]) == 2 for row in report["rows"]))
            self.assertEqual(fixture.count("recipe-1"), 1)
            self.assertEqual(fixture.count("recipe-2"), 0)

    def test_error_work_is_separate_from_failed_and_missing_work(self):
        for control in ("invalid_utf8", "reserved_trailer"):
            with self.subTest(control=control), EvidenceV4Fixture() as fixture:
                fixture.set_control(**{control: True})
                result = fixture.run(jobs=1)
                self.assertEqual(result["result"], "ERROR", result)
                self.assertIsNotNone(result["run"], result)
                report, code = view(fixture, fixture.root / result["run"]["path"])
                self.assertNotEqual(code, 0, report)
                self.assertEqual(report["counts"]["logical_associations"], 2)
                self.assertEqual(report["counts"]["unique_physical_executions"], 1)
                self.assertEqual(report["counts"]["actual_dispatches"], 1)
                self.assertEqual(report["counts"]["error_associations"], 2)
                self.assertEqual(report["counts"]["failed_associations"], 0)
                self.assertEqual(report["counts"]["missing_associations"], 0)
                self.assertTrue(all(row["status"] != "PASS" for row in report["rows"]))
                self.assertEqual(fixture.count(), 1)

    def test_cancelled_actual_work_is_retained_and_counted_separately(self):
        with EvidenceV4Fixture() as fixture:
            emit_before_cancellation(fixture)
            fixture.set_control(wait_for_gate="dashboard-cancel")
            can_signal = direct_group_signals_supported()
            process = fixture.start_call(jobs=1)
            try:
                deadline = time.monotonic() + 60
                while not any(
                    event["event"] == "started" for event in fixture.events()
                ):
                    if process.poll() is not None or time.monotonic() >= deadline:
                        self.fail("actual gated recipe did not start")
                    time.sleep(0.01)
                fixture.cancel(process)
                result = fixture.finish_call(process)
                self.assertEqual(
                    result["result"], "CANCELLED" if can_signal else "ERROR", result
                )
                self.assertIsNotNone(result["run"], result)
                artifact = fixture.artifacts()[-1][1]
                self.assertTrue(artifact["termination"]["cancelled"], artifact)
                self.assertEqual(
                    (fixture.root / artifact["stdout"]["path"]).read_bytes(),
                    CANCEL_STDOUT,
                )
                self.assertEqual(
                    (fixture.root / artifact["stderr"]["path"]).read_bytes(),
                    CANCEL_STDERR,
                )
                if not can_signal:
                    self.assertIn(
                        "process-lifetime capability", result["reason"], result
                    )
                    self.assertTrue(
                        any(
                            window["state"] == "indeterminate"
                            for window in artifact["ownership"]["spawn_windows"]
                        ),
                        artifact,
                    )
                    retained = load_json(owner_path(fixture.root))
                    self.assertTrue(
                        any(
                            window["state"] == "indeterminate"
                            for window in retained["spawn_windows"]
                        ),
                        retained,
                    )
                report, code = view(fixture, fixture.root / result["run"]["path"])
                self.assertNotEqual(code, 0, report)
                self.assertEqual(report["counts"]["logical_associations"], 2)
                self.assertEqual(
                    report["counts"]["unique_physical_executions"],
                    1,
                    {"report": report, "artifact": artifact, "result": result},
                )
                self.assertEqual(report["counts"]["actual_dispatches"], 1)
                diagnostic = {
                    "counts": report["counts"],
                    "verdict": report["verdict"],
                    "errors": report.get("errors"),
                    "per_claim": report["per_claim"],
                    "producer_work": result["manifest"]["work"],
                    "saved_claims": [
                        {
                            "claim_id": claim["claim_id"],
                            "result": claim["result"],
                            "executions": claim["executions"],
                        }
                        for claim in fixture.claims(result)
                    ],
                }
                self.assertEqual(
                    report["counts"]["cancelled_associations"],
                    2 if can_signal else 0,
                    json.dumps(diagnostic, indent=2),
                )
                self.assertEqual(report["counts"]["failed_associations"], 0)
                self.assertEqual(
                    report["counts"]["error_associations"], 0 if can_signal else 2
                )
                self.assertTrue(all(row["status"] != "PASS" for row in report["rows"]))
                self.assertEqual(fixture.count(), 1)
            finally:
                cleanup_native_processes(fixture.root)
                if process.poll() is None:
                    fixture.cancel(process)
                    try:
                        process.communicate(timeout=30)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.communicate(timeout=5)

    def test_later_history_failure_blocks_an_older_stored_pass_for_all_members(self):
        with EvidenceV4Fixture() as fixture:
            first = self.produce(fixture)
            fixture.set_control(exit_code=9)
            failed = fixture.run(resume=False, jobs=1)
            self.assertEqual(failed["result"], "FAIL", failed)
            report, code = view(fixture, fixture.root / first["run"]["path"])
            self.assertEqual(code, 1, report)
            self.assertEqual({row["status"] for row in report["rows"]}, {"FAIL"})
            self.assertTrue(
                all(row["executions"][0]["blocking_events"] for row in report["rows"])
            )
            self.assertEqual(fixture.count(), 2)

    def test_cross_key_failure_barrier_survives_restoring_old_policy(self):
        with EvidenceV4Fixture(claims=("A",)) as fixture:
            first = self.produce(fixture)
            original = (fixture.root / fixture.policy_path).read_bytes()
            original_definitions = {
                path: (fixture.root / path).read_bytes()
                for path in fixture.policy["definition_files"]
            }
            fixture.policy["recipes"][0]["determinism"]["rationale"] = (
                "second reviewed fixture identity"
            )
            fixture.save_policy(commit_message="change fixture recipe identity")
            fixture.set_control(exit_code=6)
            failed = fixture.run(resume=False, jobs=1)
            self.assertEqual(failed["result"], "FAIL", failed)
            self.assertNotEqual(
                first["manifest"]["work"][0]["execution_key"],
                failed["manifest"]["work"][0]["execution_key"],
            )
            fixture.policy = json.loads(original)
            fixture.save_policy(commit_message="restore original fixture policy")
            self.assertEqual(
                (fixture.root / fixture.policy_path).read_bytes(), original
            )
            for path, contents in original_definitions.items():
                self.assertEqual((fixture.root / path).read_bytes(), contents, path)
            report, code = view(fixture, fixture.root / first["run"]["path"])
            self.assertEqual(code, 1, report)
            self.assertEqual(rows_by_id(report)["A"]["status"], "FAIL")
            self.assertTrue(rows_by_id(report)["A"]["executions"][0]["blocking_events"])
            self.assertEqual(fixture.count(), 2)

    def test_dependency_gap_preserves_own_pass_and_required_failure(self):
        with EvidenceV4Fixture(claims=("A", "B", "C")) as fixture:
            obligations_path = fixture.root / ".fv" / "obligations.json"
            obligations = load_json(obligations_path)
            system = next(
                item for item in obligations["witnesses"] if item["id"] == "C"
            )
            obligations["witnesses"] = [
                item for item in obligations["witnesses"] if item["id"] != "C"
            ]
            system.update(depends_on=["A", "B"], required_evidence=["fixture-1"])
            obligations.setdefault("system_claims", []).append(system)
            rewrite_json(obligations_path, obligations)
            fixture.commit("declare fixture composition dependencies")
            fixture.set_control(observation_fail=["B"])
            result = fixture.run(jobs=1)
            self.assertEqual(result["result"], "FAIL", result)
            report, code = view(fixture, require=["C"])
            rows = rows_by_id(report)
            self.assertEqual(set(report["required_claims"]), {"A", "B", "C"})
            self.assertEqual(code, 1, report)
            self.assertEqual(rows["B"]["status"], "FAIL")
            self.assertEqual(rows["C"]["status"], "dependency-gap")
            self.assertEqual(rows["C"]["dependency_gaps"], ["B"])
            self.assertEqual(rows["C"]["evidence_coverage"], {"fixture-1": "PASS"})
            self.assertEqual(report["counts"]["logical_associations"], 3)
            self.assertEqual(report["counts"]["actual_dispatches"], 1)

    def test_malformed_and_missing_slots_remain_visible_defects(self):
        mutations = {
            "missing-slot": (
                lambda record: record.update(executions=[]),
                "missing or malformed canonical slot",
            ),
            "unreadable-slot": (
                lambda record: record["executions"].__setitem__(0, None),
                "missing or malformed canonical slot",
            ),
            "missing-observation": (
                lambda record: record["executions"][0].update(observation=None),
                "physical PASS lacks own member observation",
            ),
            "missing-reference": (
                lambda record: record["executions"][0].update(execution=None),
                "slot PASS/FAIL has no actual receipt/barrier",
            ),
        }
        for name, (mutate, expected_error) in mutations.items():
            with self.subTest(mutation=name), EvidenceV4Fixture() as fixture:
                result = self.produce(fixture)
                mutate_claim(fixture, result, "B", mutate)
                report, code = view(fixture)
                rows = rows_by_id(report)
                text = dashboard.render_text(report)
                self.assertEqual(code, 2, report)
                self.assertEqual(report["verdict"], "ERROR", report)
                self.assertEqual(set(rows), {"A", "B"}, report)
                self.assertEqual(rows["A"]["status"], "PASS", report)
                self.assertEqual(rows["B"]["status"], "INCOMPLETE", report)
                self.assertEqual(len(rows["B"]["executions"]), 1, report)
                slot = rows["B"]["executions"][0]
                self.assertEqual(slot["state"], "ERROR", report)
                self.assertIn(expected_error, slot["defects"], report)
                self.assertIn(f"  ! B/fixture-1: {expected_error}", text, report)
                self.assertIn("B/slot-1 tool=fixture-1 state=ERROR", text, report)
                self.assertEqual(report["counts"]["logical_associations"], 2, report)
                self.assertEqual(report["counts"]["error_associations"], 1, report)
                self.assertEqual(report["counts"]["failed_associations"], 0, report)
                self.assertEqual(report["counts"]["actual_dispatches"], 1, report)
                self.assertEqual(fixture.count(), 1)

    def test_genuine_required_fail_precedes_another_members_malformed_slot(self):
        with EvidenceV4Fixture() as fixture:
            fixture.set_control(observation_fail=["A"])
            result = fixture.run(jobs=1)
            self.assertEqual(result["result"], "FAIL", result)
            mutate_claim(
                fixture, result, "B", lambda record: record.update(executions=[])
            )
            report, code = view(fixture)
            rows = rows_by_id(report)
            self.assertEqual(code, 1, report)
            self.assertEqual(report["verdict"], "FAILED", report)
            self.assertEqual(rows["A"]["status"], "FAIL", report)
            self.assertEqual(rows["B"]["status"], "INCOMPLETE", report)
            self.assertIn(
                "  ! B/fixture-1: missing or malformed canonical slot",
                dashboard.render_text(report),
                report,
            )
            self.assertEqual(report["counts"]["logical_associations"], 2, report)

    def test_record_and_slot_class_downgrades_are_not_covered(self):
        mutations = {
            "record-class": (
                lambda record: record.update(evidence_class="code-enforced"),
                "B: claim identity/class/scope/common differs from policy",
            ),
            "slot-class": (
                lambda record: record["executions"][0].update(
                    evidence_class="code-enforced"
                ),
                "B/fixture-1: claim slot tool/recipe/observation/class differs from policy",
            ),
            "unverified-slot": (
                lambda record: record["executions"][0].update(
                    evidence_class="unverified"
                ),
                "B: ClaimRecord.executions[0].evidence_class: invalid enum value",
            ),
        }
        for name, (mutate, expected_error) in mutations.items():
            with self.subTest(mutation=name), EvidenceV4Fixture() as fixture:
                result = self.produce(fixture)
                mutate_claim(fixture, result, "B", mutate)
                report, code = view(fixture)
                rows = rows_by_id(report)
                self.assertEqual(code, 2, report)
                self.assertEqual(report["verdict"], "ERROR", report)
                self.assertEqual(rows["A"]["status"], "PASS", report)
                self.assertEqual(rows["B"]["status"], "INCOMPLETE", report)
                self.assertIn(expected_error, report["errors"], report)
                self.assertIn(
                    f"  ! {expected_error}", dashboard.render_text(report), report
                )
                self.assertEqual(report["counts"]["logical_associations"], 2, report)
                self.assertEqual(report["counts"]["error_associations"], 1, report)
                self.assertEqual(fixture.count(), 1)

    def test_unknown_and_mixed_schemas_never_fall_back_to_legacy(self):
        with EvidenceV4Fixture() as fixture:
            result = self.produce(fixture)
            pointer = fixture.current()
            mutations = (
                {**pointer, "schema_version": "fv-evidence-current/v99"},
                {**pointer, "records": fixture.claims(result)},
                {
                    "ledger_schema_version": "fv-ledger/v2",
                    "records": fixture.claims(result),
                },
                [
                    fixture.claims(result)[0],
                    {"schema_version": "fv-evidence-run/v3", "claim_id": "B"},
                ],
            )
            for value in mutations:
                with self.subTest(value=value):
                    rewrite_json(current_path(fixture), value)
                    proc = cli(fixture, None, "--json")
                    self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
                    self.assertIn("VERDICT: ERROR", proc.stderr)
            rewrite_json(current_path(fixture), pointer)
            self.assertEqual(fixture.count(), 1)

    def test_legacy_bindings_mixed_into_v4_claim_are_a_defect(self):
        with EvidenceV4Fixture() as fixture:
            result = self.produce(fixture)
            mutate_claim(
                fixture,
                result,
                "B",
                lambda record: record.update(
                    bindings={"profile": "fv-evidence-run/v3", "executions": []}
                ),
            )
            report, code = view(fixture)
            row = rows_by_id(report)["B"]
            self.assertEqual(code, 2, report)
            self.assertEqual(report["verdict"], "ERROR", report)
            self.assertEqual(row["status"], "INCOMPLETE", report)
            expected_error = "ClaimRecord: missing [], unknown ['bindings']"
            self.assertIn(expected_error, row["defects"], report)
            self.assertIn(
                f"  ! B: {expected_error}", dashboard.render_text(report), report
            )
            self.assertEqual(report["counts"]["logical_associations"], 2, report)
            self.assertEqual(fixture.count(), 1)


if __name__ == "__main__":
    unittest.main()
