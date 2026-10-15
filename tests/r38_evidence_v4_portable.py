#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""R38 portable-consumer regressions from the independent CA-01 through CA-04 review."""

from __future__ import annotations

import copy
import os
import shutil
import subprocess
import sys
import time
import unittest
import uuid
from datetime import datetime, timezone

from evidence_v4_fixture import (
    EvidenceV4Fixture,
    REPO,
    load_json,
    reidentify_artifact,
    reidentify_claim,
    rewrite_json,
)

sys.path.insert(0, str(REPO / "scripts"))
import fv_evidence_v4 as portable
from fv_evidence_v4_schema import C, D, H, V4Error, validate


BASE = ".fv/evidence/v4"


def file_ref(fixture, path):
    data = path.read_bytes()
    return {
        "path": path.relative_to(fixture.root).as_posix(),
        "hash": H(data),
        "size": len(data),
    }


def rows(report):
    return {row["claim_id"]: row for row in report["per_claim"]}


def events(fixture):
    return [
        load_json(path)
        for path in sorted((fixture.evidence_root / "history").glob("*.json"))
    ]


def store_bytes(fixture):
    return {
        path.relative_to(fixture.evidence_root).as_posix(): path.read_bytes()
        for path in fixture.evidence_root.rglob("*")
        if path.is_file()
    }


def restore_store(fixture, snapshot):
    shutil.rmtree(fixture.evidence_root)
    for relative, data in snapshot.items():
        path = fixture.evidence_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def map_refs(value, replacements):
    if isinstance(value, list):
        return [map_refs(entry, replacements) for entry in value]
    if not isinstance(value, dict):
        return value
    if "path" in value and "hash" in value and value["path"] in replacements:
        return copy.deepcopy(replacements[value["path"]])
    return {key: map_refs(entry, replacements) for key, entry in value.items()}


def rewrite_consistent_store(fixture, *, tool_change=None, check_changes=None):
    """Mutate real retained reports and rebind hashes so byte corruption cannot mask a semantic defect."""
    documents = {}
    for path in fixture.evidence_root.rglob("*.json"):
        value = load_json(path)
        if isinstance(value, dict):
            documents[path.relative_to(fixture.root).as_posix()] = value
    replacements = {}
    keys = {}
    check_changes = check_changes or {}

    def write_document(relative, value):
        path = fixture.root / relative
        rewrite_json(path, value)
        reference = file_ref(fixture, path)
        replacements[relative] = reference
        return reference

    def change_tools(tools):
        if tool_change is not None:
            for tool in tools:
                tool_change(tool)

    for relative, original in documents.items():
        if original.get("schema_version") != "fv-execution-artifact/v1":
            continue
        artifact = copy.deepcopy(original)
        change_tools(artifact["descriptor"]["toolchain"])
        if artifact["toolchain_after"] is not None:
            change_tools(artifact["toolchain_after"])
        old_key = artifact["execution_key"]
        new_key = D("execution-key", artifact["descriptor"])
        old_directory = relative.rsplit("/", 1)[0]
        new_directory = f"{BASE}/executions/{new_key[7:]}/{artifact['attempt_id']}"
        if new_directory != old_directory:
            destination = fixture.root / new_directory
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(fixture.root / old_directory, destination)
            shutil.rmtree(fixture.root / old_directory)
        for field in ("stdout", "stderr", "raw_output"):
            artifact[field]["path"] = (
                new_directory + artifact[field]["path"][len(old_directory) :]
            )
        for attachment in artifact["attachments"]:
            attachment["path"] = (
                new_directory + attachment["path"][len(old_directory) :]
            )
        protocol = artifact["ownership"]["protocol_log"]
        if protocol is not None:
            protocol["path"] = new_directory + protocol["path"][len(old_directory) :]
        for window in artifact["ownership"]["spawn_windows"]:
            window["execution_key"] = new_key
        artifact["execution_key"] = new_key
        artifact = reidentify_artifact(artifact)
        target = fixture.root / new_directory / "execution.json"
        rewrite_json(target, artifact)
        replacements[relative] = {
            "execution_key": new_key,
            "artifact_id": artifact["artifact_id"],
            "path": target.relative_to(fixture.root).as_posix(),
            "hash": H(target.read_bytes()),
        }
        keys[old_key] = new_key

    request_hashes = {}
    for relative, original in documents.items():
        if original.get("schema_version") == "fv-claim-observation-request/v1":
            request = map_refs(original, replacements)
            request_hashes[request["request_id"]] = write_document(relative, request)[
                "hash"
            ]
    for relative, original in documents.items():
        if original.get("schema_version") == "fv-claim-observations/v1":
            response = copy.deepcopy(original)
            response["request_hash"] = request_hashes[response["request_id"]]
            write_document(relative, response)
    for relative, original in documents.items():
        if original.get("schema_version") == "fv-observation-check/v1":
            check = map_refs(original, replacements)
            change_tools(check["toolchain"])
            if relative in check_changes:
                check_changes[relative](check)
            write_document(relative, check)

    history = []
    for relative in sorted(documents):
        original = documents[relative]
        if original.get("schema_version") != "fv-evidence-history/v1":
            continue
        event = map_refs(original, replacements)
        event["execution_key"] = keys.get(
            event["execution_key"], event["execution_key"]
        )
        event["previous"] = history[-1] if history else None
        event.pop("event_id")
        event["event_id"] = D("history-event", event)
        reference = write_document(relative, event)
        reference.pop("size")
        reference.update(sequence=event["sequence"], event_id=event["event_id"])
        replacements[relative] = reference
        history.append(reference)
    for relative, original in documents.items():
        if original.get("schema_version") == "fv-evidence-run/v4":
            write_document(relative, reidentify_claim(map_refs(original, replacements)))
    for relative, original in documents.items():
        if original.get("schema_version") == "fv-evidence-batch/v1":
            manifest = map_refs(original, replacements)
            for work in manifest["work"]:
                if work["execution_key"] is not None:
                    work["execution_key"] = keys.get(
                        work["execution_key"], work["execution_key"]
                    )
            write_document(relative, manifest)
    for relative, original in documents.items():
        if original.get("schema_version") == "fv-evidence-current/v1":
            write_document(relative, map_refs(original, replacements))


def recompute_tool(tool):
    tool["files"].sort(key=lambda entry: entry["path"].encode("utf-8"))
    tool["digest"] = D(
        "tool-content",
        {
            key: tool[key]
            for key in ("kind", "files", "packages", "system_dependencies")
        },
    )


def empty_producer_runtime(tool):
    if tool["id"] == "fv-producer":
        tool["files"] = [
            entry for entry in tool["files"] if not entry["path"].startswith("runtime/")
        ]
        recompute_tool(tool)


def add_empty_configuration_directories(tool):
    if tool["id"] == "fv-producer":
        for name in ("implementation/empty-config", "runtime/empty-config"):
            if not any(entry["path"] == name for entry in tool["files"]):
                tool["files"].append({"path": name, "kind": "directory"})
        recompute_tool(tool)


def input_state_after_drift(check):
    after = copy.deepcopy(check["source_before"])
    entry = next(row for row in after["files"] if row["path"] == "src/value.txt")
    data = b"detected-original-checker-source-drift\n"
    entry.update(hash=H(data), size=len(data))
    after["source_snapshot"] = H(
        b"".join(
            row["path"].encode("utf-8")
            + b"\0"
            + row["hash"][7:].encode("ascii")
            + b"\n"
            for row in after["files"]
        )
    )
    check["source_after"] = after


def utc_now(*, finish=False):
    milliseconds = time.time_ns() // 1_000_000 + (1 if finish else 0)
    return (
        datetime.fromtimestamp(milliseconds / 1000, timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def write_actual_aggregate_failure(fixture, result):
    """Invoke the existing checker on two real PASS executions and retain its actual mixed response."""
    manifest = fixture.manifest(result)
    claim = fixture.claims(result)[0]
    original_check = load_json(
        fixture.root / claim["executions"][0]["observation"]["check"]["path"]
    )
    request_id = str(uuid.uuid4())
    relative = f"{BASE}/runs/{manifest['run_id']}/observations/A/{request_id}"
    directory = fixture.root / relative
    directory.mkdir(parents=True)
    request = {
        "schema_version": "fv-claim-observation-request/v1",
        "request_id": request_id,
        "policy_path": manifest["policy_path"],
        "policy_hash": manifest["policy_hash"],
        "common": manifest["common"],
        "claim_id": "A",
        "created_at": utc_now(),
        "slots": [
            {
                key: slot[key]
                for key in (
                    "slot_id",
                    "tool",
                    "recipe_id",
                    "execution",
                    "observation_binding",
                )
            }
            for slot in claim["executions"]
        ],
    }
    request_path = directory / "request.json"
    request_path.write_bytes(C(request))
    response_path = directory / "response.json"
    environment = {
        name: os.environ[name]
        for name in fixture.policy["environment"]["inherit"]
        if name in os.environ
    }
    environment.update(fixture.policy["environment"]["set"])
    started = utc_now()
    command = fixture.policy["claim_checker"]["command"]
    completed = subprocess.run(
        [*command, "--request", str(request_path), "--response", str(response_path)],
        cwd=fixture.root,
        env=environment,
        capture_output=True,
        timeout=fixture.policy["claim_checker"]["timeout_seconds"],
        check=False,
    )
    finished = utc_now(finish=True)
    if completed.returncode != 0:
        raise AssertionError((completed.returncode, completed.stdout, completed.stderr))
    response = load_json(response_path)
    if [entry["result"] for entry in response["slots"]] != ["PASS", "FAIL"]:
        raise AssertionError(response)
    for field in ("stdout", "stderr"):
        (directory / (field + ".bin")).write_bytes(getattr(completed, field))
    check = {
        "schema_version": "fv-observation-check/v1",
        "request": file_ref(fixture, request_path),
        "response": file_ref(fixture, response_path),
        "started_at": started,
        "finished_at": finished,
        "termination": {
            "exit_code": 0,
            "signal": None,
            "timed_out": False,
            "cancelled": False,
        },
        "stdout": file_ref(fixture, directory / "stdout.bin"),
        "stderr": file_ref(fixture, directory / "stderr.bin"),
        "source_before": manifest["source_after"],
        "source_after": manifest["source_after"],
        "toolchain": original_check["toolchain"],
        "result": "FAIL",
        "reason": "actual mixed member response",
    }
    validate("ObservationCheck", check)
    check_path = directory / "check.json"
    rewrite_json(check_path, check)
    check_ref = file_ref(fixture, check_path)
    history = copy.deepcopy(manifest["history"]["events"])
    for slot, observed in zip(claim["executions"], response["slots"], strict=True):
        artifact = load_json(fixture.root / slot["execution"]["path"])
        event = {
            "schema_version": "fv-evidence-history/v1",
            "sequence": len(history) + 1,
            "previous": history[-1],
            "kind": "observation",
            "execution_key": artifact["execution_key"],
            "attempt_id": artifact["attempt_id"],
            "members": artifact["descriptor"]["members"],
            "execution": slot["execution"],
            "claim_id": "A",
            "slot_id": slot["slot_id"],
            "observation": check_ref,
            "indeterminate_owner": None,
            "result": observed["result"],
        }
        event["event_id"] = D("history-event", event)
        event_path = (
            fixture.evidence_root / "history" / f"{event['sequence']:020d}.json"
        )
        rewrite_json(event_path, event)
        reference = file_ref(fixture, event_path)
        reference.pop("size")
        reference.update(sequence=event["sequence"], event_id=event["event_id"])
        history.append(reference)
        slot["observation"] = {
            "check": check_ref,
            "response": check["response"],
            "result": observed["result"],
        }
        slot["state"] = observed["result"]
        slot["blocking_events"] = [reference] if observed["result"] == "FAIL" else []
        slot["reason"] = observed["reason"]
    claim["result"] = "FAIL"
    claim_path = fixture.root / manifest["claims"][0]["record"]["path"]
    rewrite_json(claim_path, reidentify_claim(claim))
    manifest["claims"][0]["record"] = file_ref(fixture, claim_path)
    manifest["history"] = {"head": history[-1], "events": history}
    manifest["finished_at"] = finished
    manifest["result"] = "FAIL"
    manifest["reason"] = "actual mixed member response"
    manifest_path = fixture.root / result["run"]["path"]
    rewrite_json(manifest_path, manifest)
    pointer = fixture.current()
    pointer["run"] = file_ref(fixture, manifest_path)
    rewrite_json(fixture.evidence_root / "current.json", pointer)
    return check


@unittest.skipUnless(os.name == "posix", "v4 requires POSIX process ownership")
class PortableReviewRegressions(unittest.TestCase):
    def produce_pass(self, fixture):
        result = fixture.run(jobs=1)
        self.assertEqual(result["result"], "PASS", result)
        self.assertEqual(result["publication"]["state"], "durable", result)
        report, code = fixture.assess()
        self.assertEqual(code, 0, report)
        self.assertTrue(
            all(row["result"] == "PASS" for row in report["per_claim"]), report
        )
        return result

    def test_ca01_required_runtime_root_cannot_be_empty(self):
        with EvidenceV4Fixture(claims=("A",)) as fixture:
            self.produce_pass(fixture)
            artifact = fixture.artifacts()[0][1]
            producer = next(
                tool
                for tool in artifact["descriptor"]["toolchain"]
                if tool["id"] == "fv-producer"
            )
            self.assertTrue(
                any(
                    entry["kind"] == "file" and entry["path"].startswith("runtime/")
                    for entry in producer["files"]
                )
            )
            rewrite_consistent_store(fixture, tool_change=empty_producer_runtime)
            for recompute in (False, True):
                with self.subTest(recompute=recompute):
                    report, code = fixture.assess(
                        recompute=recompute, recheck_observations=recompute
                    )
                    self.assertEqual(code, 2, report)
                    self.assertEqual(report["verdict"], "ERROR", report)
                    self.assertNotEqual(rows(report)["A"]["result"], "PASS", report)
                    self.assertEqual(fixture.count(), 1)

    def test_ca01_empty_configuration_directories_do_not_discard_real_runtime_bytes(
        self,
    ):
        with EvidenceV4Fixture(claims=("A",)) as fixture:
            self.produce_pass(fixture)
            opaque_before = sorted(
                path.read_bytes()
                for path in fixture.evidence_root.rglob("*.json")
                if not isinstance(load_json(path), dict)
            )
            rewrite_consistent_store(
                fixture, tool_change=add_empty_configuration_directories
            )
            opaque_after = sorted(
                path.read_bytes()
                for path in fixture.evidence_root.rglob("*.json")
                if not isinstance(load_json(path), dict)
            )
            self.assertEqual(
                opaque_after,
                opaque_before,
                "nonprotocol JSON bytes were changed by reidentification",
            )
            for recompute in (False, True):
                with self.subTest(recompute=recompute):
                    report, code = fixture.assess(
                        recompute=recompute, recheck_observations=recompute
                    )
                    self.assertEqual(code, 0, report)
                    self.assertEqual(rows(report)["A"]["result"], "PASS", report)
                    self.assertFalse(report["errors"], report)

    def test_ca01_source_qualified_package_requires_retained_source_bytes(self):
        with EvidenceV4Fixture(claims=("A",)) as fixture:
            package_dir = "tools/fixture-package"
            fixture.write(
                package_dir + "/Cargo.toml",
                '[package]\nname = "fixture-package"\nversion = "0.1.0"\nedition = "2021"\n',
            )
            fixture.write(
                package_dir + "/src/lib.rs",
                "pub mod required;\npub fn witness() -> bool { required::value() }\n",
            )
            fixture.write(
                package_dir + "/src/required.rs", "pub fn value() -> bool { true }\n"
            )
            fixture.write(
                package_dir + "/README.md",
                "Bound package inventory includes this tracked file.\n",
            )
            fixture.commit("portable package source fixture")
            self.produce_pass(fixture)
            artifact = fixture.artifacts()[0][1]
            source = artifact["source_before"]
            producer = next(
                tool
                for tool in artifact["descriptor"]["toolchain"]
                if tool["id"] == "fv-producer"
            )
            host = next(
                entry
                for entry in producer["files"]
                if entry["kind"] == "file"
                and entry["path"].startswith("runtime/")
                and entry["executable"]
            )
            package = {
                "name": "fixture-package",
                "version": "0.1.0",
                "source": {"kind": "path", "path": package_dir},
            }
            label = "packages/" + D("cargo-package", package)[7:]
            files = [
                {**host, "path": "cargo"},
                {**host, "path": "rustc"},
                {"path": "sysroot", "kind": "directory"},
                {**host, "path": "sysroot/runtime.bin"},
                {"path": "config", "kind": "directory"},
                {"path": "packages", "kind": "directory"},
                {"path": label, "kind": "directory"},
            ]
            tool = {
                "id": "package-context",
                "kind": "tree",
                "locator": {
                    "mode": "adapter",
                    "value": "cargo-toolchain",
                    "cwd": ".",
                    "subject": [
                        "cargo",
                        "check",
                        "--manifest-path",
                        package_dir + "/Cargo.toml",
                    ],
                },
                "files": files,
                "packages": [package],
                "version": None,
                "discovery": [],
                "system_dependencies": producer["system_dependencies"],
                "requires": [],
            }
            declaration = {
                key: copy.deepcopy(tool[key])
                for key in ("id", "kind", "locator", "requires")
            }
            declaration.update(
                version_command=None,
                version_cwd=None,
                accept={"sha256": [], "version_contains": []},
            )
            complete = copy.deepcopy(tool)
            complete["files"].append({"path": label + "/src", "kind": "directory"})
            for entry in source["files"]:
                if entry["path"].startswith(package_dir + "/"):
                    complete["files"].append(
                        {
                            **entry,
                            "kind": "file",
                            "path": label + entry["path"][len(package_dir) :],
                        }
                    )
            for candidate in (tool, complete):
                recompute_tool(candidate)
            portable._tool(complete, declaration, artifact["descriptor"]["environment"])
            portable._package_policy(portable.Reader(fixture.root), [complete], source)
            with self.assertRaises(V4Error):
                portable._tool(tool, declaration, artifact["descriptor"]["environment"])
                portable._package_policy(portable.Reader(fixture.root), [tool], source)
            omissions = {
                "manifest-only": {
                    entry["path"]
                    for entry in complete["files"]
                    if entry["kind"] == "file"
                    and entry["path"].startswith(label + "/")
                    and entry["path"] != label + "/Cargo.toml"
                },
                "missing-crate-root": {label + "/src/lib.rs"},
                "missing-required-module": {label + "/src/required.rs"},
                "missing-bound-readme": {label + "/README.md"},
            }
            for name, omitted in omissions.items():
                with self.subTest(package_inventory=name):
                    incomplete = copy.deepcopy(complete)
                    incomplete["files"] = [
                        entry
                        for entry in incomplete["files"]
                        if entry["path"] not in omitted
                    ]
                    recompute_tool(incomplete)
                    portable._tool(
                        incomplete, declaration, artifact["descriptor"]["environment"]
                    )
                    if name == "missing-crate-root":
                        self.assertTrue(
                            any(
                                entry["path"] == label + "/src/required.rs"
                                for entry in incomplete["files"]
                            )
                        )
                        self.assertTrue(
                            any(
                                entry["path"] == label + "/README.md"
                                for entry in incomplete["files"]
                            )
                        )
                    with self.assertRaises(V4Error):
                        portable._package_policy(
                            portable.Reader(fixture.root), [incomplete], source
                        )

    def test_ca02_embedded_pass_cannot_override_broken_original_checker_receipt(self):
        variants = (
            (
                "nonzero-exit",
                "ERROR",
                {
                    "exit_code": 1,
                    "signal": None,
                    "timed_out": False,
                    "cancelled": False,
                },
                None,
            ),
            (
                "signal",
                "ERROR",
                {
                    "exit_code": None,
                    "signal": "SIGTERM",
                    "timed_out": False,
                    "cancelled": False,
                },
                None,
            ),
            (
                "cancelled",
                "CANCELLED",
                {
                    "exit_code": None,
                    "signal": "SIGTERM",
                    "timed_out": False,
                    "cancelled": True,
                },
                None,
            ),
            (
                "timeout",
                "ERROR",
                {
                    "exit_code": None,
                    "signal": "SIGTERM",
                    "timed_out": True,
                    "cancelled": False,
                },
                None,
            ),
            (
                "missing-post-state",
                "ERROR",
                None,
                lambda check: check.update(source_after=None),
            ),
            (
                "dirty-post-state",
                "ERROR",
                None,
                lambda check: check["source_after"].update(clean=False),
            ),
            ("changed-post-state", "ERROR", None, input_state_after_drift),
            ("operational-error", "ERROR", None, None),
        )
        with EvidenceV4Fixture(claims=("A",)) as fixture:
            self.produce_pass(fixture)
            check_path = fixture.claims()[0]["executions"][0]["observation"]["check"][
                "path"
            ]
            snapshot = store_bytes(fixture)
            for name, result, termination, post_state in variants:
                with self.subTest(case=name):
                    restore_store(fixture, snapshot)

                    def corrupt(check):
                        check["result"] = result
                        check["reason"] = "retained transport failure: " + name
                        if termination is not None:
                            check["termination"] = termination
                        if post_state is not None:
                            post_state(check)

                    rewrite_consistent_store(
                        fixture, check_changes={check_path: corrupt}
                    )
                    for recompute in (False, True):
                        with self.subTest(recompute=recompute):
                            before = sum(
                                event["event"] == "observation"
                                for event in fixture.events()
                            )
                            retained = store_bytes(fixture)
                            report, code = fixture.assess(
                                recompute=recompute, recheck_observations=recompute
                            )
                            self.assertEqual(code, 2, report)
                            self.assertEqual(report["verdict"], "ERROR", report)
                            self.assertNotEqual(
                                rows(report)["A"]["result"], "PASS", report
                            )
                            self.assertEqual(
                                sum(
                                    event["event"] == "observation"
                                    for event in fixture.events()
                                ),
                                before,
                                "a fresh checker call rehabilitated a broken original receipt",
                            )
                            self.assertEqual(store_bytes(fixture), retained)
                            self.assertEqual(fixture.count(), 1)

    def test_ca02_member_pass_remains_eligible_with_valid_aggregate_failure(self):
        with EvidenceV4Fixture(claims=("A",), recipe_count=2) as fixture:
            result = self.produce_pass(fixture)
            fixture.set_control("recipe-2", observation_fail=["A"])
            check = write_actual_aggregate_failure(fixture, result)
            self.assertEqual(check["termination"]["exit_code"], 0)
            self.assertEqual(check["source_before"], check["source_after"])
            for recompute in (False, True):
                with self.subTest(recompute=recompute):
                    report, code = fixture.assess(
                        recompute=recompute, recheck_observations=recompute
                    )
                    self.assertEqual(code, 1, report)
                    self.assertEqual(report["verdict"], "FAILED", report)
                    slots = {
                        slot["slot_id"]: slot
                        for slot in rows(report)["A"]["executions"]
                    }
                    self.assertEqual(slots["slot-1"]["state"], "PASS", report)
                    self.assertEqual(slots["slot-2"]["state"], "FAIL", report)
                    self.assertFalse(report["errors"], report)
                    self.assertEqual(fixture.count("recipe-1"), 1)
                    self.assertEqual(fixture.count("recipe-2"), 1)

    def test_ca03_outside_policy_canonical_failure_precedes_policy_preflight_error(
        self,
    ):
        for failure_kind in ("execution", "observation"):
            with (
                self.subTest(failure=failure_kind),
                EvidenceV4Fixture(
                    claims=("A", "B"), distinct=failure_kind == "execution"
                ) as fixture,
            ):
                if failure_kind == "execution":
                    fixture.set_control(outcomes=[{"exit_code": 0}, {"exit_code": 17}])
                else:
                    fixture.set_control(observation_fail=["B"])
                failed = fixture.run(jobs=1)
                self.assertEqual(failed["result"], "FAIL", failed)
                report, code = fixture.assess(
                    recompute=False, recheck_observations=False
                )
                self.assertEqual(code, 1, report)
                self.assertEqual(rows(report)["A"]["result"], "PASS", report)
                self.assertEqual(rows(report)["B"]["result"], "FAIL", report)
                history_before = store_bytes(fixture)
                genuine = [
                    event
                    for event in events(fixture)
                    if event["kind"] == failure_kind and event["result"] == "FAIL"
                ]
                self.assertTrue(genuine)
                fixture.policy["records"] = [
                    record
                    for record in fixture.policy["records"]
                    if record["claim_id"] == "A"
                ]
                fixture.save_policy("reviewed fixture assurance selection")
                fixture.set_control()
                selected = fixture.run(records=["A"], jobs=1)
                self.assertEqual(selected["result"], "ERROR", selected)
                self.assertIsNotNone(selected["run"], selected)
                self.assertEqual(
                    selected["manifest"]["preflight"]["result"], "ERROR", selected
                )
                for recompute in (False, True):
                    with self.subTest(recompute=recompute):
                        report, code = fixture.assess(
                            recompute=recompute, recheck_observations=recompute
                        )
                        self.assertEqual(code, 1, report)
                        self.assertEqual(report["verdict"], "FAILED", report)
                        self.assertEqual(set(report["required_claims"]), {"A", "B"})
                        self.assertEqual(rows(report)["B"]["result"], "FAIL", report)
                        self.assertTrue(
                            any(
                                message.startswith("B:") for message in report["failed"]
                            ),
                            report,
                        )
                for relative, data in history_before.items():
                    if relative.startswith(("history/", "executions/")):
                        self.assertEqual(
                            (fixture.evidence_root / relative).read_bytes(), data
                        )

    def test_ca03_outside_policy_missing_claim_is_not_fabricated_failure(self):
        with EvidenceV4Fixture(claims=("A", "B"), distinct=True) as fixture:
            self.produce_pass(fixture)
            fixture.policy["records"] = [
                record
                for record in fixture.policy["records"]
                if record["claim_id"] == "A"
            ]
            fixture.save_policy(
                "reviewed fixture assurance selection without retained failure"
            )
            selected = fixture.run(records=["A"], jobs=1)
            self.assertEqual(selected["result"], "ERROR", selected)
            report, code = fixture.assess(recompute=False, recheck_observations=False)
            self.assertNotEqual(code, 0, report)
            self.assertEqual(rows(report)["B"]["result"], "INCOMPLETE", report)
            self.assertFalse(
                any(message.startswith("B:") for message in report["failed"]), report
            )

    def test_ca04_known_error_does_not_cut_off_earlier_actual_success(self):
        with EvidenceV4Fixture(claims=("A",)) as fixture:
            first = self.produce_pass(fixture)
            old_ref = fixture.claims(first)[0]["executions"][0]["execution"]
            fixture.set_control(invalid_utf8=True)
            error = fixture.run(resume=False, jobs=1)
            self.assertEqual(error["result"], "ERROR", error)
            self.assertTrue(
                any(
                    event["kind"] == "execution" and event["result"] == "ERROR"
                    for event in events(fixture)
                )
            )
            self.assertFalse(
                any(event["kind"] == "indeterminate" for event in events(fixture))
            )
            for recompute in (False, True):
                with self.subTest(recompute=recompute):
                    report, code = fixture.assess(
                        records_path=first["run"]["path"],
                        recompute=recompute,
                        recheck_observations=recompute,
                    )
                    self.assertEqual(code, 0, report)
                    self.assertEqual(rows(report)["A"]["result"], "PASS", report)
                    self.assertEqual(
                        rows(report)["A"]["executions"][0]["blocking_events"], []
                    )
            fixture.set_control()
            resumed = fixture.run(resume=True, jobs=1)
            self.assertEqual(resumed["result"], "PASS", resumed)
            self.assertEqual(
                fixture.claims(resumed)[0]["executions"][0]["execution"], old_ref
            )
            self.assertEqual(resumed["manifest"]["work"][0]["cache"], "hit", resumed)
            self.assertEqual(fixture.count(), 2)
            report, code = fixture.assess()
            self.assertEqual(code, 0, report)
            self.assertEqual(rows(report)["A"]["executions"][0]["blocking_events"], [])

    def test_ca04_fully_accounted_cancellation_is_not_an_indeterminate_barrier(self):
        with EvidenceV4Fixture(claims=("A",)) as fixture:
            first = self.produce_pass(fixture)
            old_ref = fixture.claims(first)[0]["executions"][0]["execution"]
            fixture.set_control(wait_for_gate="portable-cancel")
            process = fixture.start_call(resume=False, jobs=1)
            deadline = time.monotonic() + 120
            while not any(
                event["event"] == "started" and event.get("invocation") == 2
                for event in fixture.events()
            ):
                if process.poll() is not None:
                    self.fail("producer exited before cancellable fixture admission")
                if time.monotonic() >= deadline:
                    self.fail("producer did not admit cancellable fixture")
                time.sleep(0.02)
            fixture.cancel(process)
            cancelled = fixture.finish_call(process)
            self.assertEqual(cancelled["result"], "CANCELLED", cancelled)
            artifact = next(
                artifact
                for _, artifact in fixture.artifacts()
                if artifact["result"] == "CANCELLED"
            )
            self.assertTrue(
                all(
                    window["state"] == "closed"
                    for window in artifact["ownership"]["spawn_windows"]
                )
            )
            self.assertTrue(
                all(
                    child["terminated_at"] is not None
                    for child in artifact["ownership"]["children"]
                )
            )
            self.assertFalse(
                any(event["kind"] == "indeterminate" for event in events(fixture))
            )
            for recompute in (False, True):
                with self.subTest(recompute=recompute):
                    report, code = fixture.assess(
                        records_path=first["run"]["path"],
                        recompute=recompute,
                        recheck_observations=recompute,
                    )
                    self.assertEqual(code, 0, report)
                    self.assertEqual(rows(report)["A"]["result"], "PASS", report)
                    self.assertEqual(
                        rows(report)["A"]["executions"][0]["blocking_events"], []
                    )
            fixture.set_control()
            resumed = fixture.run(resume=True, jobs=1)
            self.assertEqual(resumed["result"], "PASS", resumed)
            self.assertEqual(resumed["manifest"]["work"][0]["cache"], "hit", resumed)
            self.assertEqual(
                fixture.claims(resumed)[0]["executions"][0]["execution"], old_ref
            )
            self.assertEqual(fixture.count(), 2)
            report, code = fixture.assess()
            self.assertEqual(code, 0, report)

    def test_ca04_genuine_failure_still_blocks_earlier_success(self):
        with EvidenceV4Fixture(claims=("A",)) as fixture:
            first = self.produce_pass(fixture)
            fixture.set_control(exit_code=7)
            failed = fixture.run(resume=False, jobs=1)
            self.assertEqual(failed["result"], "FAIL", failed)
            report, code = fixture.assess(
                records_path=first["run"]["path"],
                recompute=False,
                recheck_observations=False,
            )
            self.assertEqual(code, 1, report)
            self.assertEqual(rows(report)["A"]["result"], "FAIL", report)
            self.assertTrue(
                rows(report)["A"]["executions"][0]["blocking_events"], report
            )


if __name__ == "__main__":
    unittest.main()
