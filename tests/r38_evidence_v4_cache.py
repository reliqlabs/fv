#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""R38 cache behavior through the real producer and portable consumer."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

from evidence_v4_fixture import (
    EvidenceV4Fixture,
    load_json,
    reidentify_claim,
    rewrite_json,
)


def digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def digest_file(path: Path) -> str:
    with path.open("rb") as stream:
        return "sha256:" + hashlib.file_digest(stream, "sha256").hexdigest()


def replace_claim(fixture: EvidenceV4Fixture, claim: dict) -> None:
    pointer = fixture.current()
    manifest_path = fixture.root / pointer["run"]["path"]
    manifest = load_json(manifest_path)
    entry = next(
        row for row in manifest["claims"] if row["claim_id"] == claim["claim_id"]
    )
    path = fixture.root / entry["record"]["path"]
    rewrite_json(path, reidentify_claim(claim))
    data = path.read_bytes()
    entry["record"].update(hash=digest(data), size=len(data))
    rewrite_json(manifest_path, manifest)
    data = manifest_path.read_bytes()
    pointer["run"].update(hash=digest(data), size=len(data))
    rewrite_json(fixture.evidence_root / "current.json", pointer)


class CacheBehavior(unittest.TestCase):
    def assert_pass(self, fixture, result):
        self.assertEqual(result["result"], "PASS", result)
        self.assertEqual(result["publication"]["state"], "durable", result)
        self.assertIsNotNone(result["run"])
        report, code = fixture.assess()
        self.assertEqual(code, 0, report)
        self.assertTrue(report["per_claim"])
        self.assertTrue(
            all(row["status"] == "PASS" for row in report["per_claim"]), report
        )
        return report

    def test_declared_fixed_sharing_has_one_owner_and_each_observation(self):
        with EvidenceV4Fixture() as fixture:
            plan = fixture.plan()
            self.assertEqual(plan["result"], "READY", plan)
            self.assertEqual(fixture.count(), 0)
            self.assertEqual(fixture.artifacts(), [])
            self.assertEqual(len(plan["physical_slots"]), 1)
            self.assertEqual(
                [row["claim_id"] for row in plan["physical_slots"][0]["members"]],
                ["A", "B"],
            )
            report = self.assert_pass(fixture, fixture.run())
            self.assertEqual(fixture.count(), 1)
            claims = fixture.claims()
            self.assertEqual(len(claims), 2)
            first, second = (claim["executions"][0] for claim in claims)
            self.assertEqual(first["execution"], second["execution"])
            self.assertNotEqual(
                first["observation"]["check"]["path"],
                second["observation"]["check"]["path"],
            )
            for claim in claims:
                observation = claim["executions"][0]["observation"]
                self.assertEqual(observation["result"], "PASS")
                response = load_json(fixture.root / observation["response"]["path"])
                self.assertEqual(response["claim_id"], claim["claim_id"])
                self.assertEqual(
                    response["slots"][0]["observations"]["witness_count"], 1
                )
            self.assertEqual(report["counts"]["logical_associations"], 2)
            self.assertEqual(report["counts"]["unique_physical_executions"], 1)
            artifacts = fixture.artifacts()
            self.assertEqual(len(artifacts), 1)
            path, artifact = artifacts[0]
            self.assertEqual(artifact["termination"]["exit_code"], 0)
            self.assertTrue(artifact["ownership"]["children"])
            self.assertTrue(
                all(
                    window["state"] == "closed"
                    for window in artifact["ownership"]["spawn_windows"]
                )
            )
            for name in ("stdout", "stderr", "raw_output"):
                self.assertEqual(
                    (fixture.root / artifact[name]["path"]).parent, path.parent
                )
            self.assertEqual(len(list(fixture.evidence_root.rglob("raw.log"))), 1)
            self.assertFalse(list((fixture.evidence_root / "runs").rglob("raw.log")))

    def test_compiled_bun_host_runs_native_engine_without_transport_environment_leak(
        self,
    ):
        with EvidenceV4Fixture() as fixture:
            compiled = fixture.compile_host_driver()
            compiled_hash = digest_file(compiled)
            compiled_size = compiled.stat().st_size
            version = subprocess.run(
                [str(compiled), "--version"],
                cwd=fixture.root,
                env=fixture.process_environment({"BUN_BE_BUN": None}),
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertRegex(
                version.stdout.strip(), r"^fv-evidence-v4-fixture-host Bun [^\s]+$"
            )
            plan = fixture.plan(driver=compiled, env={"BUN_BE_BUN": None})
            self.assertEqual(plan["result"], "READY", plan)
            self.assertEqual(fixture.count(), 0)
            result = fixture.run(driver=compiled, env={"BUN_BE_BUN": None})
            self.assert_pass(fixture, result)
            self.assertEqual(fixture.count(), 1)
            claims = fixture.claims(result)
            self.assertEqual({claim["claim_id"] for claim in claims}, {"A", "B"})
            reference = claims[0]["executions"][0]["execution"]
            for claim in claims:
                self.assertEqual(claim["result"], "PASS", claim)
                self.assertEqual(len(claim["executions"]), 1)
                slot = claim["executions"][0]
                self.assertEqual(slot["execution"], reference)
                self.assertEqual(slot["state"], "PASS", slot)
                self.assertEqual(slot["observation"]["result"], "PASS", slot)
                response = load_json(
                    fixture.root / slot["observation"]["response"]["path"]
                )
                self.assertEqual(
                    response["slots"][0]["observations"]["witness_count"], 1
                )
            self.assertEqual(len(fixture.artifacts()), 1)
            artifact = fixture.artifacts()[0][1]
            producer = next(
                tool
                for tool in artifact["descriptor"]["toolchain"]
                if tool["id"] == "fv-producer"
            )
            host = next(
                entry
                for entry in producer["files"]
                if entry["path"] == "runtime/executable"
            )
            self.assertEqual(host["hash"], compiled_hash)
            self.assertEqual(host["size"], compiled_size)
            self.assertEqual(producer["version"]["text"], version.stdout.strip())
            evidence_bun = next(
                tool
                for tool in artifact["descriptor"]["toolchain"]
                if tool["id"] == "bun"
            )
            self.assertEqual(
                evidence_bun["files"][0]["hash"], digest_file(Path(fixture.bun))
            )
            self.assertTrue(artifact["ownership"]["children"])
            self.assertTrue(
                all(
                    window["state"] == "closed"
                    for window in artifact["ownership"]["spawn_windows"]
                )
            )
            retained = {}
            for name in ("stdout", "stderr", "raw_output"):
                file_ref = artifact[name]
                path = fixture.root / file_ref["path"]
                data = path.read_bytes()
                self.assertEqual(digest(data), file_ref["hash"])
                self.assertEqual(len(data), file_ref["size"])
                retained[name] = (data, path.stat().st_ino)
            witness = json.loads(
                retained["stdout"][0]
                .decode("utf-8")
                .splitlines()[0]
                .removeprefix("FIXTURE_WITNESS ")
            )
            self.assertFalse(witness["transport_present"], witness)
            self.assertEqual(witness["witness_count"], 1)
            self.assertNotIn(
                "BUN_BE_BUN",
                [
                    entry["name"]
                    for entry in artifact["descriptor"]["environment"]["variables"]
                ],
            )
            resumed = fixture.run(driver=compiled, env={"BUN_BE_BUN": None})
            self.assert_pass(fixture, resumed)
            self.assertEqual(fixture.count(), 1)
            self.assertEqual(len(fixture.artifacts()), 1)
            self.assertEqual(fixture.manifest(resumed)["work"][0]["cache"], "hit")
            self.assertEqual(
                fixture.claims(resumed)[0]["executions"][0]["execution"], reference
            )
            self.assertEqual(digest_file(compiled), compiled_hash)
            self.assertEqual(compiled.stat().st_size, compiled_size)
            for name, before in retained.items():
                path = fixture.root / artifact[name]["path"]
                self.assertEqual((path.read_bytes(), path.stat().st_ino), before)

    def test_unchanged_reuse_keeps_exact_bytes_and_does_not_dispatch(self):
        with EvidenceV4Fixture() as fixture:
            self.assert_pass(fixture, fixture.run())
            old_ref = fixture.claims()[0]["executions"][0]["execution"]
            artifact = fixture.artifacts()[0][1]
            files = {
                key: fixture.root / artifact[key]["path"]
                for key in ("stdout", "stderr", "raw_output")
            }
            bytes_before = {key: path.read_bytes() for key, path in files.items()}
            inodes = {key: path.stat().st_ino for key, path in files.items()}
            plan = fixture.plan()
            self.assertEqual(plan["result"], "READY", plan)
            self.assertEqual(plan["physical_slots"][0]["cache"], "eligible", plan)
            second = fixture.run()
            report = self.assert_pass(fixture, second)
            self.assertEqual(fixture.count(), 1)
            self.assertEqual(len(fixture.artifacts()), 1)
            self.assertEqual(fixture.claims()[0]["executions"][0]["execution"], old_ref)
            self.assertEqual(fixture.manifest()["work"][0]["cache"], "hit")
            self.assertEqual(report["counts"]["cache_hits"], 1)
            self.assertEqual(
                {key: path.read_bytes() for key, path in files.items()}, bytes_before
            )
            self.assertEqual(
                {key: path.stat().st_ino for key, path in files.items()}, inodes
            )
            third = fixture.run(resume=False)
            self.assert_pass(fixture, third)
            self.assertEqual(fixture.count(), 2)
            self.assertNotEqual(
                fixture.claims()[0]["executions"][0]["execution"]["path"],
                old_ref["path"],
            )

    def test_owner_distinct_random_repeats_never_collapse(self):
        with EvidenceV4Fixture(distinct=True, randomized=True) as fixture:
            plan = fixture.plan()
            self.assertEqual(plan["result"], "READY", plan)
            self.assertEqual(len(plan["physical_slots"]), 2)
            self.assertEqual(
                [row["distinct_slot"]["claim_id"] for row in plan["physical_slots"]],
                ["A", "B"],
            )
            self.assert_pass(fixture, fixture.run())
            self.assertEqual(fixture.count(), 2)
            refs = [claim["executions"][0]["execution"] for claim in fixture.claims()]
            self.assertEqual(len({ref["path"] for ref in refs}), 2)
            self.assertEqual(len({ref["execution_key"] for ref in refs}), 2)
            self.assertEqual(len(fixture.artifacts()), 2)
            for _, artifact in fixture.artifacts():
                output = (fixture.root / artifact["stdout"]["path"]).read_text()
                witness = json.loads(
                    output.splitlines()[0].removeprefix("FIXTURE_WITNESS ")
                )
                self.assertRegex(witness["nonce"], r"^[0-9a-f]{32}$")
            self.assert_pass(fixture, fixture.run())
            self.assertEqual(fixture.count(), 2)

    def test_actual_tool_bytes_and_sanitized_environment_change_keys(self):
        with EvidenceV4Fixture() as fixture:
            self.assert_pass(
                fixture,
                fixture.run(
                    env={
                        "FV_FIXTURE_PUBLIC": "public-one",
                        "FV_FIXTURE_UNLISTED": "not-forwarded",
                    }
                ),
            )
            first = fixture.claims()[0]["executions"][0]["execution"]
            self.assert_pass(
                fixture,
                fixture.run(
                    env={
                        "FV_FIXTURE_PUBLIC": "public-one",
                        "FV_FIXTURE_UNLISTED": "changed-unlisted",
                    }
                ),
            )
            self.assertEqual(fixture.count(), 1)
            self.assert_pass(
                fixture, fixture.run(env={"FV_FIXTURE_PUBLIC": "public-two"})
            )
            self.assertEqual(fixture.count(), 2)
            second = fixture.claims()[0]["executions"][0]["execution"]
            self.assertNotEqual(first["execution_key"], second["execution_key"])
            fixture.tool_path.write_bytes(
                fixture.tool_path.read_bytes() + b"# actual attested tool-byte change\n"
            )
            self.assert_pass(
                fixture, fixture.run(env={"FV_FIXTURE_PUBLIC": "public-two"})
            )
            self.assertEqual(fixture.count(), 3)
            third = fixture.claims()[0]["executions"][0]["execution"]
            self.assertNotEqual(second["execution_key"], third["execution_key"])
            for _, artifact in fixture.artifacts():
                environment = artifact["descriptor"]["environment"]["variables"]
                self.assertNotIn(
                    "FV_FIXTURE_UNLISTED", [entry["name"] for entry in environment]
                )
                self.assertTrue(
                    all(
                        set(entry) == {"name", "present", "value_hash"}
                        for entry in environment
                    )
                )
                self.assertNotIn("public-one", json.dumps(artifact))
                self.assertNotIn("public-two", json.dumps(artifact))

    def test_positive_marker_without_member_witness_is_fail(self):
        with EvidenceV4Fixture() as fixture:
            fixture.set_control(marker_only=True)
            result = fixture.run()
            self.assertEqual(result["result"], "FAIL", result)
            self.assertEqual(fixture.count(), 1)
            self.assertEqual(fixture.artifacts()[0][1]["result"], "PASS")
            self.assertTrue(
                all(claim["result"] == "FAIL" for claim in fixture.claims(result))
            )
            report, code = fixture.assess()
            self.assertNotEqual(code, 0, report)
            self.assertTrue(report["failed"], report)

    def test_corrupt_and_truncated_cache_are_error_without_reexecution(self):
        for mutation in ("stdout", "truncated-json", "raw-log"):
            with self.subTest(mutation=mutation), EvidenceV4Fixture() as fixture:
                self.assert_pass(fixture, fixture.run())
                artifact_path, artifact = fixture.artifacts()[0]
                if mutation == "truncated-json":
                    artifact_path.write_bytes(artifact_path.read_bytes()[:30])
                else:
                    target = (
                        fixture.root
                        / artifact["stdout" if mutation == "stdout" else "raw_output"][
                            "path"
                        ]
                    )
                    target.write_bytes(target.read_bytes() + b"corruption")
                result = fixture.run()
                self.assertEqual(result["result"], "ERROR", result)
                self.assertEqual(fixture.count(), 1)
                report, code = fixture.assess()
                self.assertNotEqual(code, 0, report)
                self.assertFalse(
                    all(row["status"] == "PASS" for row in report["per_claim"]), report
                )

    def test_reidentified_class_downgrade_and_unknown_claim_schema_reject(self):
        for mutation in ("class", "unknown", "mixed-v3"):
            with self.subTest(mutation=mutation), EvidenceV4Fixture() as fixture:
                self.assert_pass(fixture, fixture.run())
                claim = copy.deepcopy(fixture.claims()[0])
                if mutation == "class":
                    claim["evidence_class"] = "code-enforced"
                    claim["executions"][0]["evidence_class"] = "code-enforced"
                elif mutation == "unknown":
                    claim["schema_version"] = "fv-evidence-run/v999"
                else:
                    claim["bindings"] = {"parser_schema_version": "fv-evidence-run/v3"}
                replace_claim(fixture, claim)
                checked = fixture.gate()
                self.assertNotEqual(
                    checked.returncode, 0, checked.stdout + checked.stderr
                )
                report, code = fixture.assess()
                self.assertNotEqual(code, 0, report)
                self.assertTrue(report["incomplete"] or report["failed"], report)
                self.assertEqual(fixture.count(), 1)

    def test_unknown_and_mixed_call_schemas_cannot_dispatch(self):
        mutations = [
            {"schema_version": "fv-evidence-run/v999"},
            {"command": ["sh", "-c", "true"]},
            {"required": False},
            {"records": []},
        ]
        with EvidenceV4Fixture() as fixture:
            for fields in mutations:
                with self.subTest(fields=fields):
                    result = fixture.call(
                        call={
                            "schema_version": "fv-evidence-run/v4",
                            "policy": fixture.policy_path,
                            "mode": "run",
                            **fields,
                        }
                    )
                    self.assertEqual(result["result"], "ERROR", result)
                    self.assertEqual(fixture.count(), 0)
                    self.assertEqual(fixture.artifacts(), [])
            self.assertFalse((fixture.evidence_root / "current.json").exists())


if __name__ == "__main__":
    if not all(shutil.which(name) for name in ("bun", "git", "sh")):
        print("INCOMPLETE: R38 requires Bun, Git and POSIX sh")
        sys.exit(2)
    sys.exit(
        0
        if unittest.TextTestRunner(verbosity=2)
        .run(unittest.defaultTestLoader.loadTestsFromTestCase(CacheBehavior))
        .wasSuccessful()
        else 1
    )
