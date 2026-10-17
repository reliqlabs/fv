#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""R38: actual v4 process ownership, durable checkpoints and failure barriers."""

from __future__ import annotations

import contextlib
import copy
import hashlib
import json
import os
import queue
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from evidence_v4_fixture import EvidenceV4Fixture

REPO = Path(__file__).resolve().parents[1]
TIMEOUT = 120
DRIVER = REPO / "tests" / "evidence_v4_lifecycle_driver.ts"
COLLECTOR = REPO / "tests" / "evidence_v4_owned_collector.py"
CANCEL_STDOUT = b"before cancellation\n"
CANCEL_STDERR = b"before cancellation stderr\n"


def read_json(path: Path) -> dict:
    return json.loads(path.read_bytes())


def wait_for(predicate, *, process=None, diagnostics=None, label="condition"):
    deadline = time.monotonic() + TIMEOUT
    wake = threading.Event()
    while True:
        value = predicate()
        if value:
            return value
        if process is not None and process.poll() is not None:
            if diagnostics is not None:
                detail = diagnostics()
            else:
                stdout, stderr = process.communicate(timeout=TIMEOUT)
                detail = f"stdout:\n{stdout}\nstderr:\n{stderr}"
            raise AssertionError(
                f"producer exited before {label}: {process.returncode}\n{detail}"
            )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            detail = "" if diagnostics is None else "\n" + diagnostics()
            raise AssertionError(f"deadline waiting for {label}{detail}")
        wake.wait(min(0.02, remaining))


def history(fixture) -> list[dict]:
    return [
        read_json(path)
        for path in sorted((fixture.evidence_root / "history").glob("*.json"))
    ]


def claims_by_id(fixture, result=None) -> dict[str, dict]:
    return {record["claim_id"]: record for record in fixture.claims(result)}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def execution_events(fixture, result=None) -> list[dict]:
    events = [event for event in history(fixture) if event["kind"] == "execution"]
    return (
        events
        if result is None
        else [event for event in events if event["result"] == result]
    )


def outcome(report, claim_id: str) -> str:
    rows = report["per_claim"]
    if isinstance(rows, dict):
        return rows[claim_id]["result"]
    return next(row["result"] for row in rows if row["claim_id"] == claim_id)


def mutate_policy(fixture, update) -> dict:
    policy = copy.deepcopy(fixture.policy)
    update(policy)
    fixture.policy = policy
    fixture.save_policy("lifecycle fixture policy")
    return policy


def slot(record: dict, recipe_id="recipe-1") -> dict:
    return next(item for item in record["executions"] if item["recipe_id"] == recipe_id)


@unittest.skipUnless(os.name == "posix", "v4 requires POSIX process ownership")
class EvidenceV4History(unittest.TestCase):
    def test_actual_failure_blocks_resume_until_later_actual_success(self):
        with EvidenceV4Fixture(claims=("A",)) as fixture:
            first = fixture.run(jobs=1)
            self.assertEqual(first["result"], "PASS", first)
            old_ref = slot(claims_by_id(fixture, first)["A"])["execution"]
            old_path = fixture.root / old_ref["path"]
            old_bytes = old_path.read_bytes()
            first_pass = execution_events(fixture, "PASS")[-1]

            fixture.set_control(exit_code=17)
            failed = fixture.run(resume=False, jobs=1)
            self.assertEqual(failed["result"], "FAIL", failed)
            failure = execution_events(fixture, "FAIL")[-1]
            self.assertGreater(failure["sequence"], first_pass["sequence"])
            self.assertEqual(fixture.count(), 2)

            resumed = fixture.run(resume=True, jobs=1)
            self.assertEqual(resumed["result"], "FAIL", resumed)
            self.assertEqual(fixture.count(), 3, "resume resurrected pre-failure PASS")
            self.assertNotEqual(
                slot(claims_by_id(fixture, resumed)["A"])["execution"], old_ref
            )
            report, code = fixture.assess(records_path=first["run"]["path"])
            self.assertNotEqual(code, 0, report)
            self.assertEqual(outcome(report, "A"), "FAIL", report)

            fixture.set_control(exit_code=0)
            later = fixture.run(resume=True, jobs=1)
            self.assertEqual(later["result"], "PASS", later)
            self.assertEqual(fixture.count(), 4)
            later_pass = execution_events(fixture, "PASS")[-1]
            self.assertGreater(later_pass["sequence"], failure["sequence"])
            self.assertNotEqual(
                slot(claims_by_id(fixture, later)["A"])["execution"], old_ref
            )
            self.assertEqual(old_path.read_bytes(), old_bytes)
            report, code = fixture.assess()
            self.assertEqual(code, 0, report)

    def test_shared_member_failures_are_independent_and_full_scope_survives_selection(
        self,
    ):
        with EvidenceV4Fixture(claims=("C-01", "C-02", "C-04")) as fixture:
            fixture.set_control(observation_fail=["C-04"])
            first = fixture.run(jobs=1)
            self.assertEqual(first["result"], "FAIL", first)
            records = claims_by_id(fixture, first)
            self.assertEqual(
                {key: value["result"] for key, value in records.items()},
                {"C-01": "PASS", "C-02": "PASS", "C-04": "FAIL"},
            )
            physical = execution_events(fixture, "PASS")
            self.assertEqual(len(physical), 1)
            events = history(fixture)
            observed = {
                event["claim_id"]: event
                for event in events
                if event["kind"] == "observation"
            }
            self.assertEqual(set(observed), set(records))
            self.assertEqual(observed["C-01"]["result"], "PASS")
            self.assertEqual(observed["C-02"]["result"], "PASS")
            self.assertEqual(observed["C-04"]["result"], "FAIL")
            self.assertLess(physical[0]["sequence"], observed["C-01"]["sequence"])
            self.assertLess(observed["C-01"]["sequence"], observed["C-02"]["sequence"])
            self.assertLess(observed["C-02"]["sequence"], observed["C-04"]["sequence"])
            shared_ref = slot(records["C-01"])["execution"]
            self.assertTrue(
                all(
                    slot(value)["execution"] == shared_ref for value in records.values()
                )
            )
            retained = {path: digest(path) for path, _ in fixture.artifacts()}

            fixture.set_control(observation_fail=[])
            before = len(history(fixture))
            report, code = fixture.assess(
                records_path=first["run"]["path"], recheck_observations=True
            )
            self.assertNotEqual(code, 0, report)
            self.assertEqual(outcome(report, "C-04"), "FAIL", report)
            self.assertEqual(
                len(history(fixture)), before, "assessment invented a clearing event"
            )
            self.assertEqual(fixture.count(), 1)

            selected = fixture.run(records=["C-01"], resume=True, jobs=1)
            self.assertEqual(selected["result"], "FAIL", selected)
            selected_records = claims_by_id(fixture, selected)
            self.assertEqual(set(selected_records), set(records))
            self.assertEqual(selected_records["C-01"]["result"], "PASS")
            self.assertEqual(selected_records["C-04"]["result"], "FAIL")
            self.assertEqual(slot(selected_records["C-01"])["execution"], shared_ref)
            self.assertEqual(
                fixture.count(), 1, "unselected failed sibling forced shared redispatch"
            )
            self.assertEqual(
                selected["manifest"]["required_records"], ["C-01", "C-02", "C-04"]
            )
            self.assertTrue(slot(selected_records["C-04"])["blocking_events"])
            report, code = fixture.assess()
            self.assertNotEqual(code, 0, report)
            self.assertEqual(outcome(report, "C-01"), "PASS", report)
            self.assertEqual(outcome(report, "C-02"), "PASS", report)
            self.assertEqual(outcome(report, "C-04"), "FAIL", report)

            repaired = fixture.run(records=["C-04"], resume=True, jobs=1)
            self.assertEqual(repaired["result"], "PASS", repaired)
            self.assertEqual(fixture.count(), 2)
            repair_records = claims_by_id(fixture, repaired)
            self.assertTrue(
                all(value["result"] == "PASS" for value in repair_records.values())
            )
            repair_event = execution_events(fixture, "PASS")[-1]
            self.assertGreater(repair_event["sequence"], observed["C-04"]["sequence"])
            self.assertEqual({path: digest(path) for path in retained}, retained)

    def test_execution_failure_fans_out_to_every_recorded_member(self):
        with EvidenceV4Fixture(claims=("C-01", "C-02", "C-04")) as fixture:
            first = fixture.run(jobs=1)
            self.assertEqual(first["result"], "PASS", first)
            fixture.set_control(exit_code=9)
            failed = fixture.run(records=["C-01"], resume=False, jobs=1)
            self.assertEqual(failed["result"], "FAIL", failed)
            records = claims_by_id(fixture, failed)
            self.assertEqual(set(records), {"C-01", "C-02", "C-04"})
            self.assertTrue(
                all(record["result"] == "FAIL" for record in records.values())
            )
            event = execution_events(fixture, "FAIL")[-1]
            self.assertEqual(
                {member["claim_id"] for member in event["members"]}, set(records)
            )
            self.assertTrue(
                all(slot(record)["blocking_events"] for record in records.values())
            )
            report, code = fixture.assess(records_path=first["run"]["path"])
            self.assertNotEqual(code, 0, report)
            self.assertTrue(
                all(outcome(report, claim) == "FAIL" for claim in records), report
            )

    def test_policy_key_rollback_cannot_erase_failure(self):
        with EvidenceV4Fixture(claims=("A",)) as fixture:
            first = fixture.run(jobs=1)
            self.assertEqual(first["result"], "PASS", first)
            original = (fixture.root / fixture.policy_path).read_bytes()
            first_key = slot(claims_by_id(fixture, first)["A"])["execution"][
                "execution_key"
            ]
            mutate_policy(
                fixture,
                lambda policy: policy["recipes"][0].update(
                    determinism={
                        "mode": "fixed",
                        "rationale": "second reviewed fixture identity",
                    }
                ),
            )
            fixture.set_control(exit_code=6)
            failed = fixture.run(resume=False, jobs=1)
            self.assertEqual(failed["result"], "FAIL", failed)
            failure = execution_events(fixture, "FAIL")[-1]
            self.assertNotEqual(failure["execution_key"], first_key)
            fixture.set_control(exit_code=0)
            other_key_pass = fixture.run(resume=True, jobs=1)
            self.assertEqual(other_key_pass["result"], "PASS", other_key_pass)
            self.assertEqual(fixture.count(), 3)
            self.assertNotEqual(
                slot(claims_by_id(fixture, other_key_pass)["A"])["execution"][
                    "execution_key"
                ],
                first_key,
            )
            fixture.set_control(exit_code=6)

            fixture.policy = json.loads(original)
            fixture.save_policy("restore first reviewed fixture identity")
            plan = fixture.plan(records=["A"])
            self.assertEqual(plan["result"], "READY", plan)
            self.assertEqual(plan["physical_slots"][0]["execution_key"], first_key)
            self.assertNotEqual(plan["physical_slots"][0]["cache"], "eligible")
            report, code = fixture.assess(records_path=first["run"]["path"])
            self.assertNotEqual(code, 0, report)
            self.assertEqual(outcome(report, "A"), "FAIL", report)
            resumed = fixture.run(resume=True, jobs=1)
            self.assertEqual(resumed["result"], "FAIL", resumed)
            self.assertEqual(fixture.count(), 4)
            fixture.set_control(exit_code=0)
            repaired = fixture.run(resume=True, jobs=1)
            self.assertEqual(repaired["result"], "PASS", repaired)
            self.assertEqual(fixture.count(), 5)
            self.assertGreater(
                execution_events(fixture, "PASS")[-1]["sequence"], failure["sequence"]
            )


class LifecycleDriver:
    def __init__(self, request: dict, *, environment=None):
        self.root = Path(request["cwd"]) if "cwd" in request else None
        self.stderr = tempfile.TemporaryFile(mode="w+")
        self.messages = queue.Queue()
        self.stdout_chunks: list[str] = []
        self.capture_lock = threading.Lock()
        env = dict(os.environ if environment is None else environment)
        self.process = subprocess.Popen(
            [shutil.which("bun") or "bun", str(DRIVER)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self.stderr,
            text=True,
            env=env,
        )
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()
        self.process.stdin.write(json.dumps(request) + "\n")
        self.process.stdin.flush()

    def _read(self):
        try:
            for line in self.process.stdout:
                with self.capture_lock:
                    self.stdout_chunks.append(line)
                try:
                    self.messages.put(json.loads(line))
                except json.JSONDecodeError:
                    self.messages.put({"event": "invalid-output", "line": line})
        finally:
            self.messages.put({"event": "eof"})

    def diagnostics(self):
        if self.process.poll() is not None:
            self.reader.join(timeout=TIMEOUT)
        with self.capture_lock:
            stdout = "".join(self.stdout_chunks)
        stderr = os.pread(
            self.stderr.fileno(), os.fstat(self.stderr.fileno()).st_size, 0
        ).decode("utf-8", errors="backslashreplace")
        pending = (
            "\nstdout capture has not reached EOF"
            if self.reader.is_alive() and self.process.poll() is not None
            else ""
        )
        return f"stdout:\n{stdout}\nstderr:\n{stderr}{pending}"

    def receive(self, event=None):
        deadline = time.monotonic() + TIMEOUT
        while True:
            try:
                value = self.messages.get(
                    timeout=max(0.001, deadline - time.monotonic())
                )
            except queue.Empty as error:
                raise AssertionError(
                    f"deadline waiting for driver {event}\n{self.diagnostics()}"
                ) from error
            if value["event"] in ("error", "invalid-output", "eof"):
                detail = self.diagnostics()
                if value["event"] != "error":
                    raise AssertionError(
                        f"driver stopped before {event}: {value}\n{detail}"
                    )
                return {**value, "diagnostics": detail}
            if event is None or value["event"] == event:
                return value

    def send(self, command):
        self.process.stdin.write(command + "\n")
        self.process.stdin.flush()

    def close(self):
        registered = []
        if self.root is not None:
            with contextlib.suppress(OSError, json.JSONDecodeError):
                registered = read_json(owner_path(self.root))["children"]
        if self.process.poll() is None:
            with contextlib.suppress(BrokenPipeError):
                self.send("abort")
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                for recorded in registered:
                    actual = identity(recorded["pid"])
                    if (
                        actual is not None
                        and actual["process_start_id"] == recorded["process_start_id"]
                        and actual["process_group"] == recorded["process_group"]
                    ):
                        with contextlib.suppress(ProcessLookupError):
                            os.killpg(recorded["process_group"], signal.SIGKILL)
                self.process.kill()
        self.process.wait(timeout=TIMEOUT)
        self.reader.join(timeout=TIMEOUT)
        self.process.stdin.close()
        self.process.stdout.close()
        self.stderr.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def driver_result(request, *, environment=None):
    with LifecycleDriver(request, environment=environment) as driver:
        result = driver.receive("result")
        driver.process.wait(timeout=TIMEOUT)
        return result


def owner_path(root):
    return root / ".fv/evidence/v4/locks/publication.lock"


def native_environment(root):
    cache = root / ".fv/evidence/native-cache"
    cache.mkdir(parents=True, exist_ok=True)
    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(root),
        "XDG_CACHE_HOME": str(cache),
    }


def direct_group_signals_supported(environment=None):
    environment = os.environ if environment is None else environment
    if (
        sys.platform != "darwin"
        or "BUN_FEATURE_FLAG_FORCE_WAITER_THREAD" in environment
    ):
        return False
    version = subprocess.run(
        [shutil.which("bun") or "bun", "--version"],
        env=environment,
        capture_output=True,
        text=True,
        timeout=TIMEOUT,
        check=True,
    )
    return version.stdout.strip() == "1.3.14"


def emit_before_cancellation(fixture):
    def configure(policy):
        command = policy["recipes"][0]["command"]
        policy["recipes"][0]["command"] = [
            fixture.shell,
            "-c",
            'printf "before cancellation\\n"; printf "before cancellation stderr\\n" >&2; exec "$@"',
            "fixture-cancel",
            *command,
        ]

    mutate_policy(fixture, configure)


def cleanup_native_processes(root, extra=()):
    registered = [item for item in extra if item is not None]
    with contextlib.suppress(OSError, json.JSONDecodeError):
        registered.extend(read_json(owner_path(root))["children"])
    for recorded in registered:
        actual = identity(recorded["pid"])
        if (
            actual is not None
            and actual["process_start_id"] == recorded["process_start_id"]
            and actual["process_group"] == recorded["process_group"]
        ):
            with contextlib.suppress(ProcessLookupError):
                os.killpg(recorded["process_group"], signal.SIGKILL)


def identity(pid):
    result = driver_result({"mode": "identity", "pid": pid})
    if result["event"] == "error":
        raise AssertionError(result)
    return result["identity"]


def event(fixture, name, recipe_id=None):
    return next(
        (
            item
            for item in fixture.events()
            if item["event"] == name
            and (recipe_id is None or item["recipe_id"] == recipe_id)
        ),
        None,
    )


@unittest.skipUnless(os.name == "posix", "v4 requires POSIX process ownership")
class EvidenceV4Scheduling(unittest.TestCase):
    def test_normal_exit_allows_bounded_descendant_drain(self):
        for child_finishes in (True, False):
            with self.subTest(child_finishes=child_finishes):
                with EvidenceV4Fixture(claims=("A",)) as fixture:
                    fixture.set_control(
                        spawn_child=True,
                        await_child=False,
                        wait_for_gate="parent-release",
                        child_gate="parent-release"
                        if child_finishes
                        else "child-release",
                        child_delay_ms=1000 if child_finishes else 0,
                    )
                    process = fixture.start_call(jobs=1, resume=False)
                    try:
                        child = wait_for(
                            lambda: event(fixture, "child-started"),
                            process=process,
                            label="same-group descendant",
                        )
                        child_pid = child.get("child_pid", child["pid"])
                        wait_for(
                            lambda: any(
                                entry["pid"] == child_pid
                                for entry in read_json(owner_path(fixture.root))[
                                    "children"
                                ]
                            ),
                            process=process,
                            label="registered descendant",
                        )
                        fixture.release("parent-release")
                        result = fixture.finish_call(process)
                        self.assertEqual(
                            result["result"],
                            "PASS" if child_finishes else "ERROR",
                            result,
                        )
                        artifact = fixture.artifacts()[-1][1]
                        self.assertEqual(artifact["termination"]["exit_code"], 0)
                        windows = artifact["ownership"]["spawn_windows"]
                        if child_finishes:
                            self.assertTrue(
                                all(window["state"] == "closed" for window in windows),
                                artifact,
                            )
                            self.assertTrue(
                                all(
                                    entry["terminated_at"]
                                    for entry in artifact["ownership"]["children"]
                                ),
                                artifact,
                            )
                            self.assertIsNone(identity(child_pid))
                        else:
                            self.assertIn("surviving descendants", result["reason"])
                            self.assertTrue(
                                any(
                                    window["state"] == "indeterminate"
                                    for window in windows
                                ),
                                artifact,
                            )
                            self.assertIsNotNone(identity(child_pid))
                    finally:
                        fixture.release("parent-release")
                        fixture.release("child-release")
                        if process.poll() is None:
                            fixture.finish_call(process)
                        wait_for(
                            lambda: event(fixture, "child-finished"),
                            label="descendant completion",
                        )

    def test_fail_fast_preserves_first_checkpoint_and_unadmitted_work(self):
        with EvidenceV4Fixture(claims=("A",), recipe_count=3) as fixture:
            fixture.set_control("recipe-2", exit_code=7)
            failed = fixture.run(jobs=1)
            self.assertEqual(failed["result"], "FAIL", failed)
            work = {item["recipe_id"]: item for item in failed["manifest"]["work"]}
            self.assertEqual(work["recipe-1"]["state"], "PASS")
            self.assertEqual(work["recipe-2"]["state"], "FAIL")
            self.assertEqual(work["recipe-3"]["state"], "MISSING")
            self.assertIsNone(work["recipe-3"]["execution"])
            self.assertEqual(fixture.count("recipe-3"), 0)
            first_ref = work["recipe-1"]["execution"]
            first_bytes = (fixture.root / first_ref["path"]).read_bytes()
            fixture.set_control("recipe-2", exit_code=0)
            resumed = fixture.run(jobs=1, resume=True)
            self.assertEqual(resumed["result"], "PASS", resumed)
            resumed_work = {
                item["recipe_id"]: item for item in resumed["manifest"]["work"]
            }
            self.assertEqual(resumed_work["recipe-1"]["execution"], first_ref)
            self.assertEqual(resumed_work["recipe-1"]["cache"], "hit")
            self.assertEqual(fixture.count("recipe-1"), 1)
            self.assertEqual(fixture.count("recipe-2"), 2)
            self.assertEqual(fixture.count("recipe-3"), 1)
            self.assertEqual(
                (fixture.root / first_ref["path"]).read_bytes(), first_bytes
            )

    def test_jobs_are_bounded_by_actual_start_finish_order(self):
        with EvidenceV4Fixture(claims=("A",), recipe_count=4) as fixture:
            for index in range(1, 5):
                fixture.set_control(f"recipe-{index}", wait_for_gate=f"job-{index}")
            process = fixture.start_call(jobs=2)
            try:
                wait_for(
                    lambda: (
                        sum(item["event"] == "started" for item in fixture.events())
                        == 2
                    ),
                    process=process,
                    label="two admitted recipes",
                )
                starts = [
                    item for item in fixture.events() if item["event"] == "started"
                ]
                self.assertEqual(len(starts), 2)
                for item in starts:
                    fixture.release("job-" + item["recipe_id"].split("-")[-1])
                wait_for(
                    lambda: (
                        sum(item["event"] == "started" for item in fixture.events())
                        == 4
                    ),
                    process=process,
                    label="remaining admitted recipes",
                )
                for index in range(1, 5):
                    fixture.release(f"job-{index}")
                result = fixture.finish_call(process)
                self.assertEqual(result["result"], "PASS", result)
                active = set()
                maximum = 0
                for item in fixture.events():
                    if item["event"] == "started":
                        active.add(item["pid"])
                        maximum = max(maximum, len(active))
                        self.assertLessEqual(len(active), 2, fixture.events())
                    elif item["event"] == "finished":
                        active.remove(item["pid"])
                self.assertEqual(maximum, 2)
                self.assertFalse(active)
            finally:
                if process.poll() is None:
                    fixture.cancel(process)
                    fixture.finish_call(process)

    def test_resources_and_exclusive_recipe_serialize_actual_invocations(self):
        with EvidenceV4Fixture(claims=("A",), recipe_count=4) as fixture:

            def configure(policy):
                policy["recipes"][0]["resources"] = ["r38-shared"]
                policy["recipes"][2]["resources"] = ["r38-shared"]
                policy["recipes"][3]["exclusive"] = True

            mutate_policy(fixture, configure)
            for index in range(1, 5):
                fixture.set_control(f"recipe-{index}", wait_for_gate=f"serial-{index}")
            process = fixture.start_call(jobs=2)
            try:
                wait_for(
                    lambda: (
                        event(fixture, "started", "recipe-1")
                        and event(fixture, "started", "recipe-2")
                    ),
                    process=process,
                    label="independent initial recipes",
                )
                fixture.release("serial-2")
                wait_for(
                    lambda: (
                        event(fixture, "observation")
                        and any(
                            item["execution"] is not None
                            and item["execution"]["execution_key"]
                            == artifact["execution_key"]
                            for item in execution_events(fixture, "PASS")
                            for _, artifact in fixture.artifacts()
                            if artifact["descriptor"]["recipe"]["recipe_id"]
                            == "recipe-2"
                        )
                    ),
                    process=process,
                    label="independent durable checkpoint",
                )
                self.assertEqual(fixture.count("recipe-3"), 0)
                self.assertEqual(fixture.count("recipe-4"), 0)
                fixture.release("serial-1")
                wait_for(
                    lambda: event(fixture, "started", "recipe-3"),
                    process=process,
                    label="serialized recipe",
                )
                self.assertEqual(fixture.count("recipe-4"), 0)
                fixture.release("serial-3")
                wait_for(
                    lambda: event(fixture, "started", "recipe-4"),
                    process=process,
                    label="exclusive recipe",
                )
                fixture.release("serial-4")
                result = fixture.finish_call(process)
                self.assertEqual(result["result"], "PASS", result)
                active = {}
                for item in fixture.events():
                    if item["event"] == "started":
                        recipe = item["recipe_id"]
                        self.assertNotIn("recipe-4", active.values())
                        if recipe == "recipe-4":
                            self.assertFalse(active)
                        if recipe in ("recipe-1", "recipe-3"):
                            self.assertFalse(
                                {"recipe-1", "recipe-3"}.intersection(active.values())
                            )
                        active[item["pid"]] = recipe
                    elif item["event"] == "finished":
                        del active[item["pid"]]
                self.assertFalse(active)
            finally:
                if process.poll() is None:
                    fixture.cancel(process)
                    fixture.finish_call(process)

    def test_concurrent_publication_writer_is_refused_without_stealing(self):
        with EvidenceV4Fixture(claims=("A",)) as fixture:
            fixture.set_control(wait_for_gate="writer")
            process = fixture.start_call(jobs=1)
            try:
                wait_for(
                    lambda: event(fixture, "started"),
                    process=process,
                    label="first writer invocation",
                )
                original = owner_path(fixture.root).read_bytes()
                other = fixture.run(jobs=1, resume=False)
                self.assertEqual(other["result"], "ERROR", other)
                self.assertEqual(fixture.count(), 1)
                self.assertEqual(owner_path(fixture.root).read_bytes(), original)
                fixture.release("writer")
                result = fixture.finish_call(process)
                self.assertEqual(result["result"], "PASS", result)
            finally:
                if process.poll() is None:
                    fixture.cancel(process)
                    fixture.finish_call(process)

    def test_real_cancellation_retains_bytes_and_kills_owned_process_group(self):
        with EvidenceV4Fixture(claims=("A",)) as fixture:
            emit_before_cancellation(fixture)
            fixture.set_control(
                wait_for_gate="cancel", spawn_child=True, child_gate="cancel-child"
            )
            can_signal = direct_group_signals_supported()
            before = descendant = None
            process = fixture.start_call(jobs=1)
            try:
                started = wait_for(
                    lambda: event(fixture, "started"),
                    process=process,
                    label="running evidence",
                )
                child = wait_for(
                    lambda: event(fixture, "child-started"),
                    process=process,
                    label="owned descendant",
                )
                before = identity(started["pid"])
                descendant = identity(child.get("child_pid", child["pid"]))
                self.assertIsNotNone(before)
                self.assertIsNotNone(descendant)
                self.assertEqual(before["process_group"], descendant["process_group"])
                fixture.cancel(process)
                cancelled = fixture.finish_call(process)
                self.assertEqual(
                    cancelled["result"],
                    "CANCELLED" if can_signal else "ERROR",
                    cancelled,
                )
                if can_signal:
                    self.assertIsNone(identity(started["pid"]))
                    self.assertIsNone(identity(child.get("child_pid", child["pid"])))
                self.assertFalse(execution_events(fixture, "PASS"))
                artifact = fixture.artifacts()[-1][1]
                self.assertEqual(
                    artifact["result"], "CANCELLED" if can_signal else "ERROR"
                )
                self.assertTrue(artifact["termination"]["cancelled"])
                self.assertEqual(
                    (fixture.root / artifact["stdout"]["path"]).read_bytes(),
                    CANCEL_STDOUT,
                )
                self.assertEqual(
                    (fixture.root / artifact["stderr"]["path"]).read_bytes(),
                    CANCEL_STDERR,
                )
                if can_signal:
                    self.assertTrue(
                        all(
                            row["terminated_at"] is not None
                            for row in artifact["ownership"]["children"]
                        )
                    )
                    self.assertTrue(
                        all(
                            row["state"] == "closed"
                            for row in artifact["ownership"]["spawn_windows"]
                        )
                    )
                    fixture.set_control(spawn_child=False)
                    resumed = fixture.run(resume=True)
                    self.assertEqual(resumed["result"], "PASS", resumed)
                    self.assertEqual(fixture.count(), 2)
                else:
                    self.assertIn(
                        "process-lifetime capability", cancelled["reason"], cancelled
                    )
                    self.assertTrue(
                        any(
                            row["terminated_at"] is None
                            for row in artifact["ownership"]["children"]
                        ),
                        artifact,
                    )
                    self.assertTrue(
                        any(
                            row["state"] == "indeterminate"
                            for row in artifact["ownership"]["spawn_windows"]
                        ),
                        artifact,
                    )
                    retained = read_json(owner_path(fixture.root))
                    self.assertTrue(
                        any(
                            row["state"] == "indeterminate"
                            for row in retained["spawn_windows"]
                        ),
                        retained,
                    )
                    resumed = fixture.run(resume=True)
                    self.assertEqual(resumed["result"], "ERROR", resumed)
                    self.assertEqual(fixture.count(), 1)
            finally:
                cleanup_native_processes(fixture.root, [before, descendant])
                if process.poll() is None:
                    fixture.cancel(process)
                    try:
                        process.communicate(timeout=30)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.communicate(timeout=5)


@unittest.skipUnless(os.name == "posix", "v4 requires POSIX process ownership")
class EvidenceV4NativeOwnership(unittest.TestCase):
    def test_dead_unchanged_owner_is_recovered_and_live_owner_is_refused(self):
        with tempfile.TemporaryDirectory(prefix="r38-owner-") as directory:
            root = Path(directory).resolve(strict=True)
            environment = native_environment(root)
            with LifecycleDriver(
                {"mode": "owner-hold", "cwd": str(root)}, environment=environment
            ) as driver:
                owner = driver.receive("owner")["owner"]
                refused = driver_result(
                    {"mode": "recover", "cwd": str(root), "owner": owner},
                    environment=environment,
                )
                self.assertEqual(refused["event"], "error", refused)
                self.assertEqual(read_json(owner_path(root)), owner)
                driver.send("exit")
                driver.process.wait(timeout=TIMEOUT)
                self.assertIsNone(identity(owner["pid"]))
                recovered = driver_result(
                    {"mode": "recover", "cwd": str(root), "owner": owner},
                    environment=environment,
                )
                self.assertTrue(recovered.get("recovered"), recovered)
                self.assertFalse(owner_path(root).exists())
                snapshot = read_json(
                    root
                    / ".fv/evidence/v4/recovered-owners"
                    / (owner["owner_id"] + ".json")
                )
                self.assertEqual(snapshot, owner)
                with LifecycleDriver(
                    {"mode": "owner-hold", "cwd": str(root)}, environment=environment
                ) as successor:
                    next_owner = successor.receive("owner")["owner"]
                    self.assertNotEqual(next_owner["owner_id"], owner["owner_id"])
                    successor.send("abort")
                    self.assertTrue(successor.receive("result").get("released"))

    def test_recovery_refuses_changed_owner_unknown_host_and_spawn_window(self):
        for attack in ("changed-owner", "unknown-host", "indeterminate-window"):
            with (
                self.subTest(attack=attack),
                tempfile.TemporaryDirectory(prefix="r38-owner-") as directory,
            ):
                root = Path(directory).resolve(strict=True)
                environment = native_environment(root)
                with LifecycleDriver(
                    {"mode": "owner-hold", "cwd": str(root)}, environment=environment
                ) as driver:
                    original = driver.receive("owner")["owner"]
                    driver.send("exit")
                    driver.process.wait(timeout=TIMEOUT)
                malicious = copy.deepcopy(original)
                expected = copy.deepcopy(original)
                if attack == "changed-owner":
                    malicious["owner_id"] = "00000000-0000-4000-8000-000000000001"
                elif attack == "unknown-host":
                    malicious["host_id"] = "sha256:" + "0" * 64
                    expected = malicious
                else:
                    malicious["spawn_windows"] = [
                        {
                            "window_id": "00000000-0000-4000-8000-000000000002",
                            "protocol": "native-direct/v1",
                            "execution_key": None,
                            "attempt_id": None,
                            "parent": None,
                            "state": "indeterminate",
                        }
                    ]
                    expected = malicious
                owner_path(root).write_text(
                    json.dumps(
                        malicious,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                )
                before = owner_path(root).read_bytes()
                refused = driver_result(
                    {"mode": "recover", "cwd": str(root), "owner": expected},
                    environment=environment,
                )
                self.assertEqual(refused["event"], "error", refused)
                self.assertEqual(owner_path(root).read_bytes(), before)
                self.assertFalse(
                    list((root / ".fv/evidence/v4/recovered-owners").glob("*.json"))
                )

    def test_child_birth_identity_mismatch_never_signals_that_pid(self):
        with tempfile.TemporaryDirectory(prefix="r38-birth-") as directory:
            root = Path(directory).resolve(strict=True)
            environment = native_environment(root)
            with LifecycleDriver(
                {"mode": "owner-hold", "cwd": str(root)}, environment=environment
            ) as driver:
                owner = driver.receive("owner")["owner"]
                driver.send("exit")
                driver.process.wait(timeout=TIMEOUT)
            child = subprocess.Popen(
                [
                    sys.executable,
                    "-I",
                    "-B",
                    "-c",
                    "import sys; sys.stdin.buffer.read()",
                ],
                stdin=subprocess.PIPE,
                start_new_session=True,
            )
            try:
                actual = identity(child.pid)
                self.assertIsNotNone(actual)
                recorded = dict(
                    actual,
                    process_start_id=actual["process_start_id"] + ":different-birth",
                )
                owner["children"] = [recorded]
                owner_path(root).write_text(
                    json.dumps(
                        owner, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                    )
                )
                before = owner_path(root).read_bytes()
                refused = driver_result(
                    {"mode": "recover", "cwd": str(root), "owner": owner},
                    environment=environment,
                )
                self.assertEqual(refused["event"], "error", refused)
                self.assertIsNone(
                    child.poll(),
                    "recovery signalled a PID with a different birth identity",
                )
                self.assertEqual(owner_path(root).read_bytes(), before)
            finally:
                if child.poll() is None:
                    child.kill()
                child.wait(timeout=TIMEOUT)
                child.stdin.close()

    def test_private_pipe_collector_acknowledges_before_exec_and_closes_release(self):
        with tempfile.TemporaryDirectory(prefix="r38-collector-") as directory:
            root = Path(directory).resolve(strict=True)
            control = root / "control"
            control.mkdir()
            environment = native_environment(root)
            request = {
                "mode": "native",
                "cwd": str(root),
                "environment": environment,
                "command": [
                    str(Path(sys.executable).resolve()),
                    "-I",
                    "-B",
                    str(COLLECTOR),
                    "collector",
                    str(control),
                ],
                "ownership_protocol": "dossier-quint-private-pipes/v1",
            }
            with LifecycleDriver(request, environment=environment) as driver:
                driver.receive("owner")
                response = driver.receive("result")
                self.assertEqual(response["event"], "result", response)
                value = response["value"]
                self.assertEqual(value["termination"]["exit_code"], 0, value)
                self.assertIsNone(value["error"], value)
                driver.process.wait(timeout=TIMEOUT)
            gated = read_json(control / "gated.json")
            acknowledged = read_json(control / "acknowledged.json")
            subject = read_json(control / "subject.json")
            released = read_json(control / "released.json")
            self.assertFalse(
                acknowledged["subject_present"], "subject executed before durable ACK"
            )
            self.assertEqual(subject["pid"], gated["pid"])
            self.assertEqual(subject["pid"], subject["pgid"])
            self.assertEqual(subject["pid"], subject["sid"])
            self.assertEqual(released["code"], 0)
            self.assertIsNone(identity(subject["pid"]))
            receipt = value["ownership"]
            self.assertEqual(len(receipt["children"]), 2, receipt)
            hosted = next(
                row
                for row in receipt["children"]
                if row["process"]["pid"] == subject["pid"]
            )
            self.assertEqual(hosted["process"]["parent_pid"], gated["collector_pid"])
            self.assertTrue(
                all(row["terminated_at"] is not None for row in receipt["children"])
            )
            self.assertTrue(
                all(row["state"] == "closed" for row in receipt["spawn_windows"])
            )
            self.assertIsNotNone(receipt["protocol_log"])

    def test_cancellation_stops_separate_session_collector_child(self):
        with tempfile.TemporaryDirectory(prefix="r38-collector-cancel-") as directory:
            root = Path(directory).resolve(strict=True)
            control = root / "control"
            control.mkdir()
            (control / "hold").touch()
            os.mkfifo(control / "release.fifo")
            environment = native_environment(root)
            can_signal = direct_group_signals_supported(environment)
            request = {
                "mode": "native",
                "cwd": str(root),
                "environment": environment,
                "command": [
                    str(Path(sys.executable).resolve()),
                    "-I",
                    "-B",
                    str(COLLECTOR),
                    "collector",
                    str(control),
                ],
                "ownership_protocol": "dossier-quint-private-pipes/v1",
            }
            subject = None
            subject_identity = None
            collector = None
            with LifecycleDriver(request, environment=environment) as driver:
                try:
                    driver.receive("owner")
                    wait_for(
                        lambda: (control / "subject.json").exists(),
                        process=driver.process,
                        diagnostics=driver.diagnostics,
                        label="gated subject exec",
                    )
                    subject = read_json(control / "subject.json")
                    subject_identity = identity(subject["pid"])
                    gated = read_json(control / "gated.json")
                    collector = identity(gated["collector_pid"])
                    self.assertNotEqual(collector["process_group"], subject["pgid"])
                    self.assertIsNotNone(identity(subject["pid"]))
                    driver.send("abort")
                    response = driver.receive("result")
                    self.assertEqual(response["event"], "result", response)
                    value = response["value"]
                    self.assertTrue(value["termination"]["cancelled"], value)
                    self.assertNotEqual(value["termination"]["exit_code"], 0)
                    self.assertIn("test result: ok.", value["stdout"])
                    driver.process.wait(timeout=TIMEOUT)
                    if can_signal:
                        self.assertIsNone(identity(subject["pid"]))
                        self.assertIsNone(identity(gated["collector_pid"]))
                        self.assertTrue(
                            all(
                                row["terminated_at"] is not None
                                for row in value["ownership"]["children"]
                            )
                        )
                    else:
                        self.assertIn(
                            "process-lifetime capability", value["error"], value
                        )
                        self.assertTrue(
                            any(
                                row["terminated_at"] is None
                                for row in value["ownership"]["children"]
                            ),
                            value,
                        )
                    receipt = value["ownership"]
                    known_windows = {row["window_id"] for row in receipt["children"]}
                    windows = {
                        row["window_id"]: row for row in receipt["spawn_windows"]
                    }
                    self.assertTrue(known_windows, receipt)
                    self.assertTrue(known_windows.issubset(windows), receipt)
                    self.assertTrue(
                        all(
                            windows[window_id]["state"]
                            == ("closed" if can_signal else "indeterminate")
                            for window_id in known_windows
                        ),
                        receipt,
                    )
                    lifetimes = [
                        row
                        for window_id, row in windows.items()
                        if window_id not in known_windows
                    ]
                    self.assertEqual(len(lifetimes), 1, receipt)
                    self.assertEqual(
                        lifetimes[0]["protocol"], "dossier-quint-private-pipes/v1"
                    )
                    self.assertEqual(lifetimes[0]["state"], "indeterminate")
                    release_failure = driver.receive("error")
                    self.assertEqual(release_failure["event"], "error", release_failure)
                    self.assertEqual(
                        len(release_failure["native_results"]), 1, release_failure
                    )
                    self.assertEqual(
                        release_failure["native_results"][0]["ownership"], receipt
                    )
                    driver.process.wait(timeout=TIMEOUT)
                    self.assertNotEqual(driver.process.returncode, 0)
                    retained_owner = read_json(owner_path(root))
                    self.assertEqual(retained_owner, release_failure["owner"])
                    self.assertEqual(retained_owner["owner_id"], receipt["owner_id"])
                    if can_signal:
                        self.assertFalse(retained_owner["children"], retained_owner)
                    else:
                        self.assertTrue(retained_owner["children"], retained_owner)
                    self.assertEqual(
                        {
                            row["window_id"]: row
                            for row in retained_owner["spawn_windows"]
                        },
                        windows,
                    )
                finally:
                    cleanup_native_processes(root, [subject_identity, collector])


@unittest.skipUnless(os.name == "posix", "v4 requires POSIX process ownership")
class EvidenceV4StoreFailures(unittest.TestCase):
    def test_invalid_policy_paths_fail_before_any_evidence_invocation(self):
        for bad in ("../outside", "/absolute", "source//double", "source/./dot"):
            with self.subTest(path=bad), EvidenceV4Fixture(claims=("A",)) as fixture:
                mutate_policy(
                    fixture,
                    lambda policy: policy["recipes"][0]["source_closure"].update(
                        prefixes=[bad]
                    ),
                )
                rejected = fixture.run()
                self.assertEqual(rejected["result"], "ERROR", rejected)
                self.assertEqual(fixture.count(), 0)
                self.assertFalse(fixture.artifacts())

    def test_corrupt_or_aliased_cache_is_error_without_redispatch(self):
        for attack in (
            "truncated-raw",
            "symlink-raw",
            "hardlink-raw",
            "missing-history",
            "corrupt-history",
            "unknown-history",
        ):
            with (
                self.subTest(attack=attack),
                EvidenceV4Fixture(claims=("A",)) as fixture,
            ):
                passed = fixture.run(jobs=1)
                self.assertEqual(passed["result"], "PASS", passed)
                pointer = (fixture.evidence_root / "current.json").read_bytes()
                artifact = fixture.artifacts()[0][1]
                raw = fixture.root / artifact["raw_output"]["path"]
                if attack == "truncated-raw":
                    raw.write_bytes(raw.read_bytes()[:-1])
                elif attack in ("symlink-raw", "hardlink-raw"):
                    alias = fixture.control_dir / "raw-alias.bin"
                    alias.write_bytes(raw.read_bytes())
                    raw.unlink()
                    if attack == "symlink-raw":
                        raw.symlink_to(alias)
                    else:
                        os.link(alias, raw)
                else:
                    events = sorted((fixture.evidence_root / "history").glob("*.json"))
                    if attack == "missing-history":
                        self.assertGreater(len(events), 1)
                        events[0].unlink()
                    elif attack == "corrupt-history":
                        events[-1].write_bytes(b'{"schema_version":')
                    else:
                        (
                            fixture.evidence_root / "history" / "unexpected.json"
                        ).write_text("{}")
                result = fixture.run(resume=True, jobs=1)
                self.assertEqual(result["result"], "ERROR", result)
                self.assertEqual(
                    fixture.count(),
                    1,
                    "corruption became a miss and was silently recollected",
                )
                self.assertEqual(
                    (fixture.evidence_root / "current.json").read_bytes(), pointer
                )
                report, code = fixture.assess()
                self.assertNotEqual(code, 0, report)

    def test_storage_symlink_never_redirects_publication(self):
        with EvidenceV4Fixture(claims=("A",)) as fixture:
            outside = fixture.control_dir / "outside-store"
            outside.mkdir()
            fixture.evidence_root.symlink_to(outside, target_is_directory=True)
            result = fixture.run()
            self.assertEqual(result["result"], "ERROR", result)
            self.assertEqual(fixture.count(), 0)
            self.assertFalse(list(outside.iterdir()))

    def test_crash_at_real_artifact_or_history_syscall_never_creates_cache_pass(self):
        cuts = (
            ("write", "after", r"/executions/.*stdout\.bin$"),
            ("rename", "after", r"/executions/"),
            ("write", "after", r"/v4/\.staging-file-[0-9]{20}\.json-"),
        )
        for operation, phase, path in cuts:
            with (
                self.subTest(operation=operation, path=path),
                EvidenceV4Fixture(claims=("A",)) as fixture,
            ):
                request = {
                    "mode": "crash-run",
                    "cwd": str(fixture.root),
                    "operation": operation,
                    "phase": phase,
                    "path": path,
                    "call": {
                        "schema_version": "fv-evidence-run/v4",
                        "policy": fixture.policy_path,
                        "mode": "run",
                        "jobs": 1,
                        "resume": False,
                    },
                }
                with LifecycleDriver(
                    request, environment=fixture.process_environment()
                ) as driver:
                    barrier = driver.receive("barrier")
                    self.assertEqual(barrier["event"], "barrier", barrier)
                    self.assertEqual(fixture.count(), 1)
                    self.assertFalse((fixture.evidence_root / "current.json").exists())
                    owner = read_json(owner_path(fixture.root))
                    self.assertTrue(owner["pending_results"], owner)
                    self.assertTrue(
                        all(
                            window["state"] == "closed"
                            for window in owner["spawn_windows"]
                        )
                    )
                    driver.process.kill()
                    driver.process.wait(timeout=TIMEOUT)
                before = fixture.count()
                refused = fixture.run(resume=True, jobs=1)
                self.assertEqual(refused["result"], "ERROR", refused)
                self.assertEqual(fixture.count(), before)
                recovered = driver_result(
                    {"mode": "recover", "cwd": str(fixture.root), "owner": owner},
                    environment=fixture.process_environment(),
                )
                self.assertTrue(recovered.get("recovered"), recovered)
                self.assertFalse(
                    any(event["result"] == "PASS" for event in history(fixture))
                )
                self.assertTrue(
                    any(event["kind"] == "indeterminate" for event in history(fixture))
                )
                resumed = fixture.run(resume=True, jobs=1)
                self.assertEqual(resumed["result"], "PASS", resumed)
                self.assertEqual(fixture.count(), before + 1)
                newest = execution_events(fixture, "PASS")[-1]
                cutoff = max(
                    event["sequence"]
                    for event in history(fixture)
                    if event["kind"] == "indeterminate"
                )
                self.assertGreater(newest["sequence"], cutoff)


@unittest.skipUnless(os.name == "posix", "v4 requires POSIX process ownership")
class EvidenceV4LifecycleEdges(unittest.TestCase):
    def test_first_failure_with_inflight_work_never_admits_later_recipe(self):
        with EvidenceV4Fixture(claims=("A",), recipe_count=3) as fixture:
            fixture.set_control("recipe-1", exit_code=5, wait_for_gate="fail")
            fixture.set_control("recipe-2", wait_for_gate="inflight")
            process = fixture.start_call(jobs=2)
            try:
                wait_for(
                    lambda: (
                        event(fixture, "started", "recipe-1")
                        and event(fixture, "started", "recipe-2")
                    ),
                    process=process,
                    label="admitted failure and inflight recipe",
                )
                fixture.release("fail")
                wait_for(
                    lambda: execution_events(fixture, "FAIL"),
                    process=process,
                    label="durable failure",
                )
                self.assertEqual(fixture.count("recipe-3"), 0)
                fixture.release("inflight")
                result = fixture.finish_call(process)
                self.assertEqual(result["result"], "FAIL", result)
                work = {row["recipe_id"]: row for row in result["manifest"]["work"]}
                self.assertEqual(work["recipe-3"]["state"], "MISSING")
                self.assertIsNone(work["recipe-3"]["execution"])
                self.assertEqual(fixture.count("recipe-3"), 0)
                self.assertIn(work["recipe-2"]["state"], ("PASS", "CANCELLED"))
            finally:
                if process.poll() is None:
                    fixture.cancel(process)
                    fixture.finish_call(process)

    def test_selected_resume_does_not_drop_unrun_required_claim(self):
        with EvidenceV4Fixture(claims=("A", "B"), distinct=True) as fixture:
            selected = fixture.run(records=["A"], jobs=1)
            self.assertEqual(selected["result"], "INCOMPLETE", selected)
            self.assertEqual(fixture.count(), 1)
            resumed = fixture.run(records=["A"], resume=True, jobs=1)
            self.assertEqual(resumed["result"], "INCOMPLETE", resumed)
            self.assertEqual(fixture.count(), 1)
            records = claims_by_id(fixture, resumed)
            self.assertEqual(set(records), {"A", "B"})
            self.assertEqual(records["A"]["result"], "PASS")
            self.assertEqual(records["B"]["result"], "INCOMPLETE")
            self.assertEqual(slot(records["B"])["state"], "MISSING")
            self.assertIsNone(slot(records["B"])["execution"])
            report, code = fixture.assess()
            self.assertNotEqual(code, 0, report)
            self.assertEqual(report["required_claims"], ["A", "B"])
            self.assertEqual(outcome(report, "B"), "INCOMPLETE")

    def test_global_resource_sets_serialize_across_roots_without_partial_locks(self):
        with tempfile.TemporaryDirectory(prefix="r38-global-lock-") as directory:
            base = Path(directory).resolve(strict=True)
            roots = [base / name for name in ("worktree-a", "worktree-b", "worktree-c")]
            for root in roots:
                root.mkdir()
            environment = native_environment(base)
            request = {
                "mode": "resource-hold",
                "cwd": str(roots[0]),
                "environment": environment,
                "resources": ["r38-a", "r38-shared"],
            }
            with LifecycleDriver(request, environment=environment) as first:
                self.assertTrue(first.receive("resources")["acquired"])
                locks = base / ".fv/evidence/native-cache/fv-evidence-v4/locks"
                original = {path.name: path.read_bytes() for path in locks.iterdir()}
                self.assertEqual(len(original), 2)
                refused = driver_result(
                    {
                        "mode": "resource-hold",
                        "cwd": str(roots[1]),
                        "environment": environment,
                        "resources": ["r38-b", "r38-shared"],
                    },
                    environment=environment,
                )
                self.assertFalse(refused.get("acquired"), refused)
                self.assertEqual(
                    {path.name: path.read_bytes() for path in locks.iterdir()}, original
                )
                with LifecycleDriver(
                    {
                        "mode": "resource-hold",
                        "cwd": str(roots[2]),
                        "environment": environment,
                        "resources": ["r38-b"],
                    },
                    environment=environment,
                ) as independent:
                    self.assertTrue(
                        independent.receive("resources")["acquired"],
                        "partial conflicting resource acquisition leaked",
                    )
                    independent.send("abort")
                    self.assertTrue(independent.receive("result")["released"])
                first.send("abort")
                self.assertTrue(first.receive("result")["released"])
            self.assertFalse(list(locks.iterdir()))
            with LifecycleDriver(
                {
                    "mode": "resource-hold",
                    "cwd": str(roots[1]),
                    "environment": environment,
                    "resources": ["r38-b", "r38-shared"],
                },
                environment=environment,
            ) as after:
                self.assertTrue(after.receive("resources")["acquired"])
                after.send("abort")
                self.assertTrue(after.receive("result")["released"])

    def test_four_native_gates_handle_backpressure_and_abort_with_closed_ownership(
        self,
    ):
        for cancelled in (False, True):
            with (
                self.subTest(cancelled=cancelled),
                tempfile.TemporaryDirectory(
                    prefix="r38-native-backpressure-"
                ) as directory,
            ):
                root = Path(directory).resolve(strict=True)
                control = root / "control"
                control.mkdir()
                environment = native_environment(root)
                can_signal = direct_group_signals_supported(environment)
                public = "\n" * (40 * 1024)
                environment["FV_NATIVE_TRANSPORT_PUBLIC"] = public
                public_hash = hashlib.sha256(public.encode("utf-8")).hexdigest()
                commands = []
                gate_handles = []
                try:
                    for index in range(4):
                        gate = control / f"gate-{index}.fifo"
                        os.mkfifo(gate)
                        gate_handles.append(os.open(gate, os.O_RDWR | os.O_NONBLOCK))
                        commands.append(
                            [
                                str(Path(sys.executable).resolve()),
                                "-I",
                                "-B",
                                str(COLLECTOR),
                                "backpressure",
                                str(control),
                                str(index),
                            ]
                        )
                    request = {
                        "mode": "native-concurrent",
                        "cwd": str(root),
                        "commands": commands,
                        "environment": environment,
                        "timeout_seconds": 30,
                    }
                    with LifecycleDriver(
                        request, environment=native_environment(root)
                    ) as driver:
                        owner = driver.receive("owner")
                        self.assertEqual(owner["event"], "owner", owner)
                        wait_for(
                            lambda: all(
                                (control / f"ready-{index}.json").exists()
                                for index in range(4)
                            ),
                            process=driver.process,
                            diagnostics=driver.diagnostics,
                            label="four concurrent native children behind release gates",
                        )
                        ready = [
                            read_json(control / f"ready-{index}.json")
                            for index in range(4)
                        ]
                        self.assertEqual(len({item["pid"] for item in ready}), 4)
                        self.assertTrue(
                            all(item["public_bytes"] == 40 * 1024 for item in ready)
                        )
                        self.assertTrue(
                            all(item["public_hash"] == public_hash for item in ready)
                        )
                        if cancelled:
                            driver.send("abort")
                        else:
                            for handle in gate_handles:
                                self.assertEqual(os.write(handle, b"1"), 1)
                        response = driver.receive("result")
                        unresolved = cancelled and not can_signal
                        if unresolved:
                            self.assertEqual(response["event"], "error", response)
                            self.assertIn(
                                "native ownership is unresolved", response["reason"]
                            )
                            values = [
                                {
                                    **value,
                                    "stdout": bytes(value["stdout"]["data"]).decode(),
                                    "stderr": bytes(value["stderr"]["data"]).decode(),
                                }
                                for value in response["native_results"]
                            ]
                            self.assertTrue(owner_path(root).exists())
                            self.assertTrue(
                                all(
                                    window["state"] == "indeterminate"
                                    for window in response["owner"]["spawn_windows"]
                                ),
                                response,
                            )
                        else:
                            self.assertEqual(response["event"], "result", response)
                            self.assertTrue(response["released"], response)
                            values = response["values"]
                            self.assertFalse(owner_path(root).exists())
                        self.assertEqual(len(values), 4)
                        driver.process.wait(timeout=TIMEOUT)
                        self.assertEqual(driver.process.returncode != 0, unresolved)
                        for index, value in enumerate(values):
                            self.assertEqual(value["stderr"], "")
                            self.assertFalse(value["termination"]["timed_out"], value)
                            self.assertEqual(
                                value["termination"]["cancelled"], cancelled
                            )
                            if cancelled:
                                self.assertEqual(value["stdout"], "")
                                self.assertNotEqual(
                                    value["termination"]["exit_code"], 0
                                )
                            else:
                                self.assertIsNone(value["error"], value)
                                self.assertEqual(
                                    value["stdout"],
                                    f"native-backpressure:{index}:{len(public)}:{public_hash}\n",
                                )
                                self.assertEqual(
                                    value["termination"]["exit_code"], 0, value
                                )
                                self.assertIsNone(value["termination"]["signal"])
                            receipt = value["ownership"]
                            self.assertTrue(receipt["children"], receipt)
                            self.assertTrue(receipt["spawn_windows"], receipt)
                            self.assertIn(
                                ready[index]["pid"],
                                [row["process"]["pid"] for row in receipt["children"]],
                            )
                            if unresolved:
                                self.assertIn(
                                    "process-lifetime capability", value["error"], value
                                )
                                self.assertTrue(
                                    any(
                                        row["terminated_at"] is None
                                        for row in receipt["children"]
                                    ),
                                    receipt,
                                )
                                self.assertTrue(
                                    all(
                                        row["state"] == "indeterminate"
                                        for row in receipt["spawn_windows"]
                                    ),
                                    receipt,
                                )
                            else:
                                self.assertTrue(
                                    all(
                                        row["terminated_at"] is not None
                                        for row in receipt["children"]
                                    )
                                )
                                self.assertTrue(
                                    all(
                                        row["state"] == "closed"
                                        for row in receipt["spawn_windows"]
                                    )
                                )
                finally:
                    cleanup_native_processes(root)
                    for handle in gate_handles:
                        os.close(handle)

    def test_timeout_after_printed_marker_retains_actual_abnormal_termination(self):
        with tempfile.TemporaryDirectory(prefix="r38-timeout-") as directory:
            root = Path(directory).resolve(strict=True)
            environment = native_environment(root)
            can_signal = direct_group_signals_supported(environment)
            command = [
                str(Path(sys.executable).resolve()),
                "-I",
                "-B",
                "-c",
                "import signal; print('test result: ok.', flush=True); signal.pause()",
            ]
            try:
                response = driver_result(
                    {
                        "mode": "native",
                        "cwd": str(root),
                        "command": command,
                        "environment": environment,
                        "timeout_seconds": 2,
                    },
                    environment=environment,
                )
                self.assertEqual(response["event"], "result", response)
                value = response["value"]
                self.assertIn("test result: ok.", value["stdout"])
                self.assertTrue(value["termination"]["timed_out"], value)
                self.assertNotEqual(value["termination"]["exit_code"], 0)
                self.assertTrue(value["ownership"]["children"])
                if can_signal:
                    self.assertTrue(
                        all(
                            row["terminated_at"] is not None
                            for row in value["ownership"]["children"]
                        )
                    )
                    self.assertTrue(
                        all(
                            row["state"] == "closed"
                            for row in value["ownership"]["spawn_windows"]
                        )
                    )
                else:
                    self.assertIn(
                        value["error"],
                        (
                            "native invocation deadline expired",
                            "refusing group signal without a retained process-lifetime capability",
                        ),
                        value,
                    )
                    self.assertTrue(
                        any(
                            row["terminated_at"] is None
                            for row in value["ownership"]["children"]
                        ),
                        value,
                    )
                    self.assertTrue(
                        all(
                            row["state"] == "indeterminate"
                            for row in value["ownership"]["spawn_windows"]
                        ),
                        value,
                    )
                    self.assertTrue(owner_path(root).exists())
            finally:
                cleanup_native_processes(root)

    def test_pointer_faults_report_pre_and_post_replacement_without_rollback_claim(
        self,
    ):
        for state in ("pre-replace-error", "post-replace-error"):
            with self.subTest(state=state), EvidenceV4Fixture(claims=("A",)) as fixture:
                first = fixture.run(jobs=1)
                self.assertEqual(first["result"], "PASS", first)
                old = (fixture.evidence_root / "current.json").read_bytes()
                retained = {path: digest(path) for path, _ in fixture.artifacts()}
                request = {
                    "mode": "fault-run",
                    "cwd": str(fixture.root),
                    "call": {
                        "schema_version": "fv-evidence-run/v4",
                        "policy": fixture.policy_path,
                        "mode": "run",
                        "jobs": 1,
                        "resume": True,
                    },
                }
                if state == "pre-replace-error":
                    request.update(
                        operation="rename", phase="before", path=r"/current\.json$"
                    )
                else:
                    request.update(
                        operation="fsync",
                        phase="before",
                        path=r"/v4$",
                        arm_path=r"/current\.json$",
                    )
                response = driver_result(
                    request, environment=fixture.process_environment()
                )
                self.assertEqual(response["event"], "result", response)
                self.assertTrue(response["reached"])
                result = response["value"]
                self.assertEqual(result["result"], "ERROR", result)
                self.assertEqual(result["publication"]["state"], state)
                self.assertIsNotNone(result["publication"]["candidate"])
                self.assertEqual(result["manifest"]["result"], "PASS")
                if state == "pre-replace-error":
                    self.assertEqual(
                        (fixture.evidence_root / "current.json").read_bytes(), old
                    )
                else:
                    self.assertNotEqual(
                        (fixture.evidence_root / "current.json").read_bytes(), old
                    )
                    self.assertEqual(
                        fixture.current()["run"], result["publication"]["candidate"]
                    )
                self.assertEqual({path: digest(path) for path in retained}, retained)
                self.assertEqual(fixture.count(), 1)


if __name__ == "__main__":
    if (
        os.name != "posix"
        or sys.platform not in ("darwin", "linux")
        or not shutil.which("bun")
        or not shutil.which("git")
    ):
        print("INCOMPLETE: lifecycle regressions require Darwin/Linux, Bun and Git")
        raise SystemExit(2)
    unittest.main()
