#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""R38: fatal observation accounting and visible-history recovery barriers."""

from __future__ import annotations

import json
import os
import re
import subprocess
import unittest
from pathlib import Path

from evidence_v4_fixture import EvidenceV4Fixture
from r38_evidence_v4_lifecycle import (
    LifecycleDriver,
    history,
    owner_path,
    read_json,
    wait_for,
)

REPO = Path(__file__).resolve().parents[1]
PROMPT_TIMEOUT = 30
DRIVER = r"""
import { existsSync, readFileSync, writeFileSync } from "node:fs";
const request = JSON.parse(readFileSync(0, "utf8"));
const { openEvidenceStore } = await import(request.modules + "/evidence-v4-store.ts");
const barriers = [];
let reached = false;
const syscallBarrier = async (operation, file, phase) => {
    if (operation === "fsync" && request.watch?.includes(file))
        barriers.push({ file, phase, owner_exists: existsSync(request.owner_path) });
    if (!reached && request.cut && operation === request.cut.operation &&
        phase === request.cut.phase && new RegExp(request.cut.pattern).test(file)) {
        reached = true;
        if (request.reached_path) writeFileSync(request.reached_path, file);
        while (request.wait_path && !existsSync(request.wait_path)) await Bun.sleep(10);
        throw new Error("injected observation storage barrier failure");
    }
};
let result;
try {
    if (request.mode === "recover") {
        const { recoverOwner } = await import(request.modules + "/evidence-v4-native.ts");
        await recoverOwner({
            cwd: request.cwd,
            expectedOwner: request.owner,
            account: async (owner, withAppendLock) => {
                const store = await openEvidenceStore(request.cwd, { withAppendLock, syscallBarrier });
                await store.accountPending(owner);
            },
        });
        result = { recovered: true };
    } else {
        const { runEvidenceV4WithStoreOptions } = await import(request.modules + "/evidence-v4-run.ts");
        result = { value: await runEvidenceV4WithStoreOptions(
            { cwd: request.cwd }, request.call, { syscallBarrier },
        ) };
    }
} catch (error) {
    result = { error: String(error) };
}
console.log(JSON.stringify({ ...result, reached, barriers }));
"""


def request_for(fixture, **fields):
    return {
        "cwd": str(fixture.root),
        "modules": str(REPO / "tools/evidence-v4"),
        "owner_path": str(owner_path(fixture.root)),
        **fields,
    }


def call_for(fixture, *, jobs=1, resume=False):
    return {
        "schema_version": "fv-evidence-run/v4",
        "policy": fixture.policy_path,
        "mode": "run",
        "jobs": jobs,
        "resume": resume,
    }


def run_driver(fixture, request):
    process = subprocess.run(
        [fixture.bun, "--eval", DRIVER],
        input=json.dumps(request),
        cwd=REPO,
        env=fixture.process_environment(),
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )
    return json.loads(process.stdout)


def checker_resource(fixture):
    fixture.policy["claim_checker"]["resources"] = ["fixture-observation-store-review"]
    fixture.save_policy("shared observation resource regression")


def visible_observation_cut(fixture):
    request = {
        "mode": "crash-run",
        "cwd": str(fixture.root),
        "operation": "fsync",
        "phase": "after",
        "path": r"/v4/history/00000000000000000002\.json$",
        "call": call_for(fixture),
    }
    with LifecycleDriver(request, environment=fixture.process_environment()) as driver:
        barrier = driver.receive("barrier")
        if barrier["event"] != "barrier":
            raise AssertionError(barrier)
        owner = read_json(owner_path(fixture.root))
        driver.process.kill()
        driver.process.wait(timeout=PROMPT_TIMEOUT)
    return owner


@unittest.skipUnless(os.name == "posix", "v4 requires POSIX process ownership")
class EvidenceV4StoreReview(unittest.TestCase):
    def assert_retained_observation(self, fixture, claim_id="A"):
        owner = read_json(owner_path(fixture.root))
        self.assertEqual(len(owner["pending_results"]), 1, owner)
        pending = owner["pending_results"][0]
        self.assertEqual(pending["kind"], "observation", owner)
        self.assertEqual(pending["claim_id"], claim_id, owner)
        self.assertFalse(owner["children"], owner)
        self.assertTrue(
            all(window["state"] == "closed" for window in owner["spawn_windows"]), owner
        )
        registry = read_json(
            fixture.evidence_root / "locks" / (owner["owner_id"] + ".locks.json")
        )
        self.assertTrue(
            any(Path(entry["file"]).exists() for entry in registry), registry
        )
        return owner

    def test_shared_observation_write_error_stops_fresh_and_cached_member_iteration(
        self,
    ):
        for resume in (False, True):
            with (
                self.subTest(resume=resume),
                EvidenceV4Fixture(claims=("A", "B")) as fixture,
            ):
                checker_resource(fixture)
                fixture.set_control(observation_fail=[] if resume else ["A"])
                first = fixture.run(jobs=1)
                self.assertEqual(first["result"], "PASS" if resume else "FAIL", first)
                observed = [
                    event
                    for event in history(fixture)
                    if event["kind"] == "observation"
                ]
                self.assertEqual(
                    [(event["claim_id"], event["result"]) for event in observed],
                    [("A", "PASS" if resume else "FAIL"), ("B", "PASS")],
                )
                self.assertFalse(owner_path(fixture.root).exists())
                fixture.set_control(observation_fail=[])
                reached = fixture.control_dir / "storage-failed"
                request = request_for(
                    fixture,
                    call=call_for(fixture, resume=resume),
                    reached_path=str(reached),
                    cut={
                        "operation": "write",
                        "phase": "before",
                        "pattern": r"/v4/\.staging-file-check\.json-",
                    },
                )
                process = subprocess.Popen(
                    [fixture.bun, "--eval", DRIVER],
                    cwd=REPO,
                    env=fixture.process_environment(),
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                try:
                    process.stdin.write(json.dumps(request))
                    process.stdin.close()
                    process.stdin = None
                    wait_for(
                        lambda: reached.exists(),
                        process=process,
                        label="observation write failure",
                    )
                    stdout, stderr = process.communicate(timeout=PROMPT_TIMEOUT)
                    self.assertEqual(process.returncode, 0, stderr)
                    result = json.loads(stdout)
                    self.assertTrue(result["reached"], result)
                    self.assertEqual(result["value"]["result"], "ERROR", result)
                    self.assertIn(
                        "injected observation storage barrier failure",
                        result["value"]["reason"],
                    )
                    owner = self.assert_retained_observation(fixture)
                    requests = list(
                        (
                            fixture.evidence_root
                            / "runs"
                            / owner["run_id"]
                            / "observations"
                        ).glob("*/*/request.json")
                    )
                    self.assertEqual(
                        [read_json(path)["claim_id"] for path in requests], ["A"]
                    )
                    self.assertEqual(fixture.count(), 1 if resume else 2)
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.communicate(timeout=PROMPT_TIMEOUT)

    def test_fatal_observation_error_stops_already_admitted_checker_waiters(self):
        with EvidenceV4Fixture(claims=("A", "B"), recipe_count=2) as fixture:
            checker_resource(fixture)
            fixture.set_control("recipe-1", wait_for_gate="first")
            fixture.set_control("recipe-2", wait_for_gate="second")
            reached = fixture.control_dir / "observation-write-paused"
            release = fixture.control_dir / "fail-observation-write"
            request = request_for(
                fixture,
                call=call_for(fixture, jobs=2),
                reached_path=str(reached),
                wait_path=str(release),
                cut={
                    "operation": "fsync",
                    "phase": "before",
                    "pattern": r"/observations/A/[^/]+/stdout\.bin$",
                },
            )
            process = subprocess.Popen(
                [fixture.bun, "--eval", DRIVER],
                cwd=REPO,
                env=fixture.process_environment(),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                process.stdin.write(json.dumps(request))
                process.stdin.close()
                process.stdin = None
                wait_for(
                    lambda: fixture.count("recipe-1") == fixture.count("recipe-2") == 1,
                    process=process,
                    label="two admitted physical recipes",
                )
                fixture.release("first")
                wait_for(
                    lambda: reached.exists(),
                    process=process,
                    label="first observation storage pause",
                )
                fixture.release("second")
                wait_for(
                    lambda: (
                        len(
                            [
                                event
                                for event in history(fixture)
                                if event["kind"] == "execution"
                            ]
                        )
                        == 2
                        and all(
                            pending["kind"] == "observation"
                            for pending in read_json(owner_path(fixture.root))[
                                "pending_results"
                            ]
                        )
                    ),
                    process=process,
                    label="inflight sibling checkpoint before checker acquisition",
                )
                release.write_bytes(b"1")
                stdout, stderr = process.communicate(timeout=PROMPT_TIMEOUT)
                self.assertEqual(process.returncode, 0, stderr)
                result = json.loads(stdout)
                self.assertEqual(result["value"]["result"], "ERROR", result)
                self.assert_retained_observation(fixture)
                self.assertEqual(
                    [
                        event["claim_id"]
                        for event in fixture.events()
                        if event["event"] == "observation"
                    ],
                    ["A"],
                )
            finally:
                fixture.release("first")
                fixture.release("second")
                release.write_bytes(b"1")
                if process.poll() is None:
                    process.kill()
                    process.communicate(timeout=PROMPT_TIMEOUT)

    def test_visible_history_recovery_resyncs_event_and_ancestors_before_retirement(
        self,
    ):
        with EvidenceV4Fixture(claims=("A", "B")) as fixture:
            checker_resource(fixture)
            owner = visible_observation_cut(fixture)
            event = fixture.evidence_root / "history" / "00000000000000000002.json"
            retained = event.read_bytes()
            expected = [
                event,
                event.parent,
                fixture.evidence_root,
                fixture.evidence_root.parent,
                fixture.root / ".fv",
                fixture.root,
            ]
            result = run_driver(
                fixture,
                request_for(
                    fixture,
                    mode="recover",
                    owner=owner,
                    watch=[str(path) for path in expected],
                ),
            )
            self.assertTrue(result.get("recovered"), result)
            self.assertEqual(
                [
                    entry["file"]
                    for entry in result["barriers"]
                    if entry["phase"] == "after"
                ],
                [str(path) for path in expected],
            )
            self.assertTrue(
                all(entry["owner_exists"] for entry in result["barriers"]), result
            )
            self.assertFalse(owner_path(fixture.root).exists())
            self.assertTrue(
                (
                    fixture.evidence_root
                    / "locks"
                    / ("retired-" + owner["owner_id"] + ".lock")
                ).exists()
            )
            self.assertEqual(event.read_bytes(), retained)
            self.assertEqual(
                [entry["kind"] for entry in history(fixture)],
                ["execution", "observation"],
            )

    def test_recovery_barrier_failure_keeps_pending_owner_and_resource_locks(self):
        with EvidenceV4Fixture(claims=("A", "B")) as fixture:
            checker_resource(fixture)
            owner = visible_observation_cut(fixture)
            owner_bytes = owner_path(fixture.root).read_bytes()
            event = fixture.evidence_root / "history" / "00000000000000000002.json"
            retained = event.read_bytes()
            registry = read_json(
                fixture.evidence_root / "locks" / (owner["owner_id"] + ".locks.json")
            )
            locks = [
                Path(entry["file"])
                for entry in registry
                if Path(entry["file"]).exists()
            ]
            self.assertTrue(locks, registry)
            for target in (event, event.parent, fixture.root):
                with self.subTest(target=target):
                    result = run_driver(
                        fixture,
                        request_for(
                            fixture,
                            mode="recover",
                            owner=owner,
                            cut={
                                "operation": "fsync",
                                "phase": "before",
                                "pattern": "^" + re.escape(str(target)) + "$",
                            },
                        ),
                    )
                    self.assertTrue(result["reached"], result)
                    self.assertIn(
                        "injected observation storage barrier failure",
                        result.get("error", ""),
                        result,
                    )
                    self.assertEqual(owner_path(fixture.root).read_bytes(), owner_bytes)
                    self.assertTrue(all(path.exists() for path in locks))
                    self.assertEqual(event.read_bytes(), retained)
            result = run_driver(
                fixture, request_for(fixture, mode="recover", owner=owner)
            )
            self.assertTrue(result.get("recovered"), result)
            self.assertFalse(owner_path(fixture.root).exists())
            self.assertTrue(all(not path.exists() for path in locks))
            self.assertEqual(event.read_bytes(), retained)


if __name__ == "__main__":
    unittest.main()
