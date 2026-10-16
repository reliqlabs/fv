#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""R38 native review: birth-bound ownership, census errors and collector argv."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from r38_evidence_v4_lifecycle import driver_result, native_environment

REPO = Path(__file__).resolve().parents[1]
MODULE = REPO / "tools/evidence-v4/evidence-v4-native.ts"
MODEL = REPO / "tools/evidence-v4/evidence-v4-model.ts"
COMMON = REPO / "tools/evidence-v4/evidence-v4-toolchain-common.ts"
SEAMS = r"""
// Test-local exports leave the producer's public API unchanged.
export const review = {
  darwin, processTable, groupStopped, signalOwned, verifyCollectorGate, COLLECTOR_GATE,
  setIdentity(value) { readProcessIdentity = value; },
  setTable(value) { processTable = value; },
  setDarwin(value) { darwinSymbols = value; darwinLibrary = Promise.resolve(value); },
};
"""
PRELUDE = r"""
const input = await Bun.stdin.json();
const { constants } = await import('node:os');
const { randomUUID } = await import('node:crypto');
const emit = value => process.stdout.write(JSON.stringify(value));
const identity = (pid, group = pid, parent = process.pid) => ({
  pid, parent_pid: parent, process_group: group, session_id: group,
  process_start_id: 'darwin-proc-start:1:0',
});
function kernel(records, failed = {}, restricted = {}) {
  let errno = 0;
  const reads = new Map();
  return {
    ptr: value => value,
    currentErrno: () => errno,
    proc_pidinfo(pid, _flavor, _argument, output) {
      if (Object.hasOwn(failed, pid)) { errno = failed[pid]; return 0; }
      const value = records[pid];
      if (!value) { errno = constants.errno.ESRCH; return 0; }
      output.fill(0);
      output.writeUInt32LE(pid, 12);
      output.writeUInt32LE(value.parent_pid, 16);
      output.writeUInt32LE(value.process_group, 100);
      const birth = value.process_start_id.split(':');
      output.writeBigUInt64LE(BigInt(birth.at(-2)), 120);
      output.writeBigUInt64LE(BigInt(birth.at(-1)), 128);
      return 136;
    },
    getsid: pid => records[pid]?.session_id ?? restricted[pid]?.session_id ?? -1,
    sysctl(mib, _count, output, length) {
      const pid = mib[3], value = restricted[pid];
      if (!value || value.error) { errno = value?.error ?? constants.errno.EPERM; return -1; }
      const count = (reads.get(pid) ?? 0) + 1;
      reads.set(pid, count);
      output.fill(0);
      output.writeInt32LE(pid, 40);
      output.writeInt32LE(value.reparented && count > 1 ? 1 : value.parent_pid, 560);
      output.writeInt32LE(count > 1 && value.nextGroup ? value.nextGroup : value.process_group, 564);
      output.writeBigUInt64LE(BigInt(count > 1 && value.nextSession ? value.nextSession : value.session_id), 304);
      output.writeBigInt64LE(value.changed && count > 1 ? 2n : 1n, 0);
      length.writeBigUInt64LE(value.short ? 640n : 648n);
      return 0;
    },
    proc_listpids(_kind, _selector, output) {
      const pids = [...new Set([...Object.keys(records), ...Object.keys(failed)])].map(Number);
      if (output) pids.forEach((pid, index) => output.writeInt32LE(pid, 4 * index));
      return 4 * pids.length;
    },
  };
}
async function finish(session, value) {
  let releaseError = null;
  try { await session.release(); } catch (error) { releaseError = String(error); }
  return { ...value, stdout: value.stdout.toString('utf8'), stderr: value.stderr.toString('utf8'),
    releaseError, owner: session.owner };
}
"""


def native(program: str, request=None) -> dict:
    with tempfile.TemporaryDirectory(prefix="r38-native-review-") as directory:
        module = Path(directory) / "native.ts"
        module.write_text(
            MODULE.read_text()
            .replace('"./evidence-v4-model.ts"', json.dumps(str(MODEL)))
            .replace('"./evidence-v4-toolchain-common.ts"', json.dumps(str(COMMON)))
            + SEAMS
        )
        command = (
            "const native = await import("
            + json.dumps(module.as_uri())
            + ");\n"
            + PRELUDE
            + program
        )
        result = subprocess.run(
            [shutil.which("bun"), "--eval", command],
            input=json.dumps(request or {}),
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        return json.loads(result.stdout)


COLLECTOR = r"""
import json, os, subprocess, sys
GATE = "\nimport os, sys\nfd = int(sys.argv[1])\nready = os.read(fd, 1)\nos.close(fd)\nif ready != b'1':\n    sys.exit(125)\nos.execvpe(sys.argv[2], sys.argv[2:], os.environ)\n"
events, acknowledgements = map(int, os.environ["DOSSIER_QUINT_OWNERSHIP_FDS"].split(","))
def notify(event, pid):
    os.write(events, json.dumps({"event": event, "pgid": pid}).encode() + b"\n")
    if os.read(acknowledgements, 1) != b"1":
        raise RuntimeError("missing durable ownership acknowledgement")
read_gate, write_gate = os.pipe()
subject = sys.argv[1:]
if subject[-1:] == ["--empty-test-arg"]:
    subject[-1] = ""
child = subprocess.Popen(
    [sys.executable, "-I", "-B", "-c", GATE, str(read_gate), *subject],
    start_new_session=True, pass_fds=(read_gate,), stdin=subprocess.DEVNULL,
)
os.close(read_gate)
try:
    notify("owned", child.pid)
    os.write(write_gate, b"1")
    os.close(write_gate)
    write_gate = -1
    code = child.wait(timeout=10)
    notify("released", child.pid)
    sys.exit(code)
finally:
    if write_gate >= 0:
        os.close(write_gate)
    child.wait(timeout=10)
"""


@unittest.skipUnless(
    shutil.which("bun") and sys.platform in ("darwin", "linux"),
    "native ownership requires Bun on Darwin or Linux",
)
class NativeReview(unittest.TestCase):
    def test_recycled_leader_does_not_admit_foreign_descendant(self):
        self.assert_foreign_not_admitted("recycled")

    def test_last_anchor_exit_does_not_admit_same_number_group(self):
        self.assert_foreign_not_admitted("lost")

    def assert_foreign_not_admitted(self, mode):
        with tempfile.TemporaryDirectory(prefix="r38-recycled-") as directory:
            root = Path(directory).resolve()
            result = native(
                r"""
const realIdentity = native.readProcessIdentity;
const realTable = native.review.processTable;
const foreign = Bun.spawn({cmd: [input.python, '-c', 'import time; time.sleep(60)'],
  detached: true, stdout: 'ignore', stderr: 'ignore'});
try {
  const foreignBirth = await realIdentity(foreign.pid);
  const session = await native.createNativeSession({cwd: input.cwd, runId: randomUUID()});
  const realSpawn = Bun.spawn;
  let directPid, census = 0, recycled = false;
  Bun.spawn = options => { const child = realSpawn(options); directPid = child.pid; return child; };
  native.review.setTable(owned => {
    if (census++ !== 0) return realTable(owned);
    recycled = true;
    return [{pid: directPid, ppid: process.pid, pgid: directPid},
      {pid: foreign.pid, ppid: directPid, pgid: directPid}];
  });
  native.review.setIdentity(async pid => {
    if (recycled && pid === directPid) {
      if (input.mode === 'lost') return null;
      recycled = false;
      return {...identity(directPid), process_start_id: 'recycled-leader-birth'};
    }
    if (recycled && pid === foreign.pid)
      return {...foreignBirth, process_group: directPid, session_id: directPid};
    return realIdentity(pid);
  });
  const interval = globalThis.setInterval;
  globalThis.setInterval = (fn, _delay, ...args) => interval(fn, 60000, ...args);
  const value = await session.run({command: [input.true], environment: input.environment,
    timeoutSeconds: null});
  Bun.spawn = realSpawn;
  globalThis.setInterval = interval;
  emit({...await finish(session, value), foreignPid: foreign.pid,
    foreignStillLive: foreign.exitCode === null && foreign.signalCode === null});
} finally {
  foreign.kill('SIGKILL');
  await foreign.exited;
}
""",
                {
                    "cwd": str(root),
                    "environment": native_environment(root),
                    "mode": mode,
                    "python": str(Path(sys.executable).resolve()),
                    "true": shutil.which("true"),
                },
            )
            self.assertTrue(result["foreignStillLive"], result)
            self.assertNotIn(
                result["foreignPid"],
                [item["process"]["pid"] for item in result["ownership"]["children"]],
                result,
            )
            self.assertTrue(result["releaseError"], result)
            self.assertTrue(
                any(
                    window["state"] == "indeterminate"
                    for window in result["ownership"]["spawn_windows"]
                ),
                result,
            )

    def test_signal_refuses_recycled_reaped_descendant_foreign_and_unchecked_runtime(
        self,
    ):
        result = native(r"""
const originalKill = process.kill;
const results = [];
for (const mode of ['recycled', 'reaped', 'descendant', 'foreign', 'version', 'platform', 'waiter']) {
  if (mode === 'waiter') process.env.BUN_FEATURE_FLAG_FORCE_WAITER_THREAD = '1';
  Object.defineProperty(process, 'platform', {value: mode === 'platform' ? 'linux' : 'darwin'});
  Object.defineProperty(process.versions, 'bun', {value: mode === 'version' ? '0.0.0' : '1.3.14'});
  const leader = identity(41001, 41001, mode === 'foreign' ? 999 : process.pid);
  const survivor = identity(41002, 41001, 1);
  const records = mode === 'reaped' ? {[survivor.pid]: survivor} : {[leader.pid]: leader};
  native.review.setIdentity(async pid => records[pid] ?? null);
  native.review.setTable(() => Object.values(records).map(value => ({
    pid: value.pid, ppid: value.parent_pid, pgid: value.process_group,
  })));
  const current = mode === 'recycled'
    ? {...leader, process_start_id: 'darwin-proc-start:2:0'} : leader;
  native.review.setDarwin(kernel({[leader.pid]: current}));
  const calls = [];
  process.kill = (...args) => { calls.push(args); return true; };
  let error = null;
  try {
    await native.review.signalOwned(leader, 'SIGTERM', Object.values(records),
      mode === 'descendant' ? undefined : {
        pid: leader.pid, exitCode: mode === 'reaped' ? 0 : null, signalCode: null,
      });
  } catch (failure) { error = String(failure); }
  results.push({mode, error, calls});
}
process.kill = originalKill;
emit({results});
""")
        for row in result["results"]:
            with self.subTest(mode=row["mode"]):
                self.assertTrue(row["error"], row)
                self.assertEqual(row["calls"], [], row)

    def test_darwin_census_zero_skips_only_esrch(self):
        result = native(r"""
Object.defineProperty(process, 'platform', {value: 'darwin'});
const results = [];
for (const errno of [constants.errno.EACCES, constants.errno.EPERM, constants.errno.EINVAL, constants.errno.ESRCH]) {
  native.review.setDarwin(kernel({}, {41002: errno}));
  let stopped = null, error = null;
  try { stopped = await native.review.groupStopped(identity(41001)); }
  catch (failure) { error = String(failure); }
  results.push({errno, stopped, error});
}
emit({results, esrch: constants.errno.ESRCH});
""")
        for row in result["results"]:
            with self.subTest(errno=row["errno"]):
                if row["errno"] == result["esrch"]:
                    self.assertTrue(row["stopped"], row)
                    self.assertIsNone(row["error"], row)
                else:
                    self.assertIsNone(row["stopped"], row)
                    self.assertIn("errno=" + str(row["errno"]), row["error"], row)

    def test_darwin_eperm_preserves_owned_birth_and_excludes_foreign_churn(self):
        result = native(r"""
Object.defineProperty(process, 'platform', {value: 'darwin'});
const results = [];
for (const mode of ['outside', 'group', 'session', 'sysctl-error', 'gone', 'short',
  'foreign-birth', 'owned-birth', 'foreign-group', 'owned-group', 'foreign-parent', 'owned-parent', 'session-change']) {
  const inGroup = ['group', 'owned-birth', 'owned-group', 'owned-parent'].includes(mode);
  const row = identity(41002, inGroup ? 41001 : 42001);
  if (mode === 'session') row.session_id = 41001;
  if (mode === 'sysctl-error') row.error = constants.errno.EIO;
  if (mode === 'gone') row.error = constants.errno.ESRCH;
  if (mode === 'short') row.short = true;
  if (mode.endsWith('-birth')) row.changed = true;
  if (mode.endsWith('-group')) row.nextGroup = 42002;
  if (mode.endsWith('-parent')) row.reparented = true;
  if (mode === 'session-change') row.nextSession = 42002;
  native.review.setDarwin(kernel({}, {41002: constants.errno.EPERM}, {41002: row}));
  let stopped = null, error = null;
  try { stopped = await native.review.groupStopped(identity(41001)); }
  catch (failure) { error = String(failure); }
  results.push({mode, stopped, error});
}
emit({results});
""")
        for row in result["results"]:
            with self.subTest(mode=row["mode"]):
                if row["mode"] in (
                    "outside",
                    "session",
                    "gone",
                    "foreign-birth",
                    "foreign-group",
                    "foreign-parent",
                ):
                    self.assertTrue(row["stopped"], row)
                    self.assertIsNone(row["error"], row)
                elif row["mode"] in ("group", "owned-parent"):
                    self.assertFalse(row["stopped"], row)
                    self.assertIsNone(row["error"], row)
                else:
                    self.assertIsNone(row["stopped"], row)
                    self.assertTrue(row["error"], row)

    def test_darwin_eperm_identity_requires_stable_birth_group_and_session(self):
        result = native(r"""
Object.defineProperty(process, 'platform', {value: 'darwin'});
const results = [];
for (const mode of ['stable', 'parent', 'birth', 'group', 'session']) {
  const row = identity(41002, 41001);
  if (mode === 'parent') row.reparented = true;
  if (mode === 'birth') row.changed = true;
  if (mode === 'group') row.nextGroup = 42001;
  if (mode === 'session') row.nextSession = 42001;
  native.review.setDarwin(kernel({}, {41002: constants.errno.EPERM}, {41002: row}));
  let observed = null, error = null;
  try { observed = await native.readProcessIdentity(41002); }
  catch (failure) { error = String(failure); }
  results.push({mode, observed, error, expected: identity(41002, 41001, mode === 'parent' ? 1 : process.pid)});
}
emit({results});
""")
        for row in result["results"]:
            with self.subTest(mode=row["mode"]):
                if row["mode"] in ("stable", "parent"):
                    self.assertEqual(row["observed"], row["expected"], row)
                    self.assertIsNone(row["error"], row)
                else:
                    self.assertIsNone(row["observed"], row)
                    self.assertTrue(row["error"], row)

    @unittest.skipUnless(sys.platform == "darwin", "Darwin compiler discovery")
    def test_real_darwin_cc_discovery_releases_native_ownership(self):
        with tempfile.TemporaryDirectory(prefix="r38-native-cc-") as directory:
            root = Path(directory).resolve()
            result = native(
                r"""
const session = await native.createNativeSession({cwd: input.cwd, runId: randomUUID()});
const value = await session.run({command: ['/usr/bin/cc', '-print-prog-name=ld'],
  environment: input.environment, timeoutSeconds: 30});
emit(await finish(session, value));
""",
                {"cwd": str(root), "environment": native_environment(root)},
            )
            self.assertEqual(result["termination"]["exit_code"], 0, result)
            self.assertIsNone(result["error"], result)
            self.assertIsNone(result["releaseError"], result)
            self.assertEqual(Path(result["stdout"].strip()).name, "ld", result)
            self.assertTrue(
                all(
                    window["state"] == "closed"
                    for window in result["ownership"]["spawn_windows"]
                ),
                result,
            )
            self.assertFalse((root / ".fv/evidence/v4/locks/publication.lock").exists())

    @unittest.skipUnless(sys.platform == "darwin", "Darwin root-owned process census")
    def test_real_darwin_eperm_system_pid_is_censused_without_owning_it(self):
        result = native(
            r"""
const lib = await native.review.darwin();
const estimate = lib.proc_listpids(1, 0, null, 0);
const pids = Buffer.alloc(Math.max(4096, estimate * 2));
const used = lib.proc_listpids(1, 0, lib.ptr(pids), pids.length);
if (used <= 0 || used >= pids.length) throw Error('incomplete real test process census');
const info = Buffer.alloc(136);
const kinfo = Buffer.alloc(648), length = Buffer.alloc(8), mib = new Int32Array([1, 14, 1, 0]);
let denied = null;
for (const pid of [1, ...Array.from({length: used / 4}, (_, index) => pids.readInt32LE(4 * index))]) {
  if (pid <= 0) continue;
  if (lib.proc_pidinfo(pid, 3, 0, lib.ptr(info), info.length) > 0 ||
      lib.currentErrno() !== constants.errno.EPERM) continue;
  mib[3] = pid;
  length.writeBigUInt64LE(BigInt(kinfo.length));
  if (lib.sysctl(lib.ptr(mib), mib.length, lib.ptr(kinfo), lib.ptr(length), null, 0) === 0 &&
      length.readBigUInt64LE() === 648n && kinfo.readInt32LE(40) === pid && kinfo.readUInt32LE(420) === 0) {
    denied = pid;
    break;
  }
}
if (denied === null) throw Error('host has no permission-restricted system PID');
const child = Bun.spawn({cmd: [input.python, '-c', 'import time; time.sleep(60)'],
  detached: true, stdout: 'ignore', stderr: 'ignore'});
try {
  const birth = await native.readProcessIdentity(child.pid);
  const rows = native.review.processTable([birth]);
  const row = rows.find(value => value.pid === denied);
  const stopped = await native.review.groupStopped(birth);
  mib[3] = denied;
  length.writeBigUInt64LE(BigInt(kinfo.length));
  if (lib.sysctl(lib.ptr(mib), mib.length, lib.ptr(kinfo), lib.ptr(length), null, 0) !== 0)
    throw Error('real restricted process sysctl failed');
  emit({row, stopped, expected: {pid: denied, ppid: kinfo.readInt32LE(560),
    pgid: kinfo.readInt32LE(564), sid: lib.getsid(denied)},
    uid: kinfo.readUInt32LE(420), group: birth.process_group, session: birth.session_id});
} finally {
  child.kill('SIGKILL');
  await child.exited;
}
""",
            {"python": str(Path(sys.executable).resolve())},
        )
        self.assertEqual(result["uid"], 0, result)
        self.assertEqual(result["row"], result["expected"], result)
        self.assertFalse(result["stopped"], result)
        self.assertNotEqual(result["row"]["pgid"], result["group"], result)
        self.assertNotEqual(result["row"]["sid"], result["session"], result)

    def test_census_error_stays_indeterminate_after_later_complete_census(self):
        with tempfile.TemporaryDirectory(prefix="r38-census-error-") as directory:
            root = Path(directory).resolve()
            result = native(
                r"""
const session = await native.createNativeSession({cwd: input.cwd, runId: randomUUID()});
const realTable = native.review.processTable;
let failed = false;
native.review.setTable(owned => {
  if (!failed) { failed = true; throw Error('unavailable Darwin process census identity: errno=13'); }
  return realTable(owned);
});
const interval = globalThis.setInterval;
globalThis.setInterval = (fn, _delay, ...args) => interval(fn, 60000, ...args);
const value = await session.run({command: [input.true], environment: input.environment, timeoutSeconds: null});
globalThis.setInterval = interval;
emit(await finish(session, value));
""",
                {
                    "cwd": str(root),
                    "environment": native_environment(root),
                    "true": shutil.which("true"),
                },
            )
            self.assertIn("errno=13", result["error"], result)
            self.assertTrue(result["releaseError"], result)
            self.assertTrue(
                all(
                    window["state"] == "indeterminate"
                    for window in result["ownership"]["spawn_windows"]
                ),
                result,
            )
            self.assertTrue((root / ".fv/evidence/v4/locks/publication.lock").exists())

    def test_unchecked_runtime_cancel_is_indeterminate_even_after_child_exits(self):
        with tempfile.TemporaryDirectory(prefix="r38-runtime-cancel-") as directory:
            root = Path(directory).resolve()
            result = native(
                r"""
const controller = new AbortController();
const session = await native.createNativeSession({cwd: input.cwd, runId: randomUUID()});
const ready = input.cwd + '/ready';
const work = session.run({command: [input.python, '-c',
  'import pathlib,sys,time; pathlib.Path(sys.argv[1]).write_text("ready"); time.sleep(0.4)', ready],
  environment: input.environment, timeoutSeconds: null, signal: controller.signal});
while (!await Bun.file(ready).exists()) await Bun.sleep(5);
Object.defineProperty(process.versions, 'bun', {value: '0.0.0'});
controller.abort();
emit(await finish(session, await work));
""",
                {
                    "cwd": str(root),
                    "environment": native_environment(root),
                    "python": str(Path(sys.executable).resolve()),
                },
            )
            self.assertTrue(result["termination"]["cancelled"], result)
            self.assertTrue(result["error"], result)
            self.assertTrue(result["releaseError"], result)
            self.assertTrue(
                any(
                    window["state"] == "indeterminate"
                    for window in result["ownership"]["spawn_windows"]
                ),
                result,
            )

    def test_reaped_real_leader_cannot_authorize_survivor_group_signal(self):
        result = native(
            r"""
const originalKill = process.kill;
const parent = Bun.spawn({
  cmd: [input.python, '-c',
    'import os,sys,time; pid=os.fork(); ' +
    '\nif pid == 0:\n os.close(0); os.close(1); os.close(2); time.sleep(60); os._exit(0)' +
    '\nprint(pid, flush=True); sys.stdin.buffer.read(1); os._exit(0)'],
  detached: true, stdin: 'pipe', stdout: 'pipe', stderr: 'ignore',
});
let survivorPid;
try {
  const reader = parent.stdout.getReader();
  const ready = await reader.read();
  survivorPid = Number(new TextDecoder().decode(ready.value).trim());
  reader.releaseLock();
  const birth = await native.readProcessIdentity(parent.pid);
  parent.stdin.write('1');
  parent.stdin.end();
  await parent.exited;
  const survivor = await native.readProcessIdentity(survivorPid);
  const calls = [];
  process.kill = (...args) => { calls.push(args); return true; };
  let error = null;
  try { await native.review.signalOwned(birth, 'SIGTERM', [birth, survivor], parent); }
  catch (failure) { error = String(failure); }
  const after = await native.readProcessIdentity(survivorPid);
  emit({error, calls, leaderGone: await native.readProcessIdentity(parent.pid) === null,
    survivorPreserved: after?.process_start_id === survivor.process_start_id});
} finally {
  process.kill = originalKill;
  if (survivorPid) {
    try { originalKill(survivorPid, 'SIGKILL'); } catch (error) { if (error.code !== 'ESRCH') throw error; }
  }
  if (parent.exitCode === null && parent.signalCode === null) parent.kill('SIGKILL');
  await parent.exited;
}
""",
            {"python": str(Path(sys.executable).resolve())},
        )
        self.assertTrue(result["leaderGone"], result)
        self.assertTrue(result["survivorPreserved"], result)
        self.assertTrue(result["error"], result)
        self.assertEqual(result["calls"], [], result)

    @unittest.skipUnless(
        sys.platform == "darwin", "Darwin source-checked child capability"
    )
    def test_darwin_unreaped_direct_child_can_be_signalled(self):
        result = native(
            r"""
if (process.versions.bun !== '1.3.14' || Object.hasOwn(process.env, 'BUN_FEATURE_FLAG_FORCE_WAITER_THREAD')) {
  emit({unsupported: true});
}
else {
  const child = Bun.spawn({cmd: [input.python, '-c', 'import time; time.sleep(60)'],
    detached: true, stdout: 'ignore', stderr: 'ignore'});
  try {
    const birth = await native.readProcessIdentity(child.pid);
    await native.review.signalOwned(birth, 'SIGTERM', [birth], child);
    await child.exited;
    emit({signal: child.signalCode});
  } finally {
    if (child.exitCode === null && child.signalCode === null) child.kill('SIGKILL');
    await child.exited;
  }
}
""",
            {"python": str(Path(sys.executable).resolve())},
        )
        if result.get("unsupported"):
            self.skipTest("Bun version has no source-checked signaling capability")
        self.assertEqual(result["signal"], "SIGTERM", result)

    def test_hardlinked_collector_images_match_without_rebinding_argv0(self):
        with tempfile.TemporaryDirectory(prefix="r38-native-hardlinks-") as directory:
            root = Path(directory).resolve()
            first = root / "python-first"
            second = root / "python-second"
            different = root / "different-image"
            alias = root / "python-alias"
            shutil.copyfile(shutil.which("true"), first)
            second.hardlink_to(first)
            shutil.copyfile(first, different)
            alias.symlink_to(second.name)
            result = native(
                r"""
const fs = await import('node:fs/promises');
const { canonicalToolPath } = await import(input.common);
const spellings = [];
for (let pass = 0; pass < 3; pass++)
  spellings.push(await Promise.all([input.first, input.second, input.alias].map(canonicalToolPath)));
Object.defineProperty(process, 'platform', {value: 'darwin'});
const results = [];
for (const mode of ['hardlink', 'different', 'admitted', 'argv-hardlink']) {
  const childImage = input.first;
  const collectorImage = mode === 'hardlink' ? input.second : input.different;
  const argv0 = mode === 'admitted' ? input.first : mode === 'argv-hardlink' ? input.second : 'python';
  const args = [argv0, '-I', '-B', '-c', native.review.COLLECTOR_GATE, '9', input.true];
  native.review.setDarwin({
    ptr: value => value,
    proc_pidpath(pid, output) {
      const value = pid === 41001 ? childImage : collectorImage;
      return output.write(value + '\0');
    },
    sysctl(mib, _count, output, length) {
      const command = mib[2] === 41001 ? args : [collectorImage, 'collector.py'];
      const image = mib[2] === 41001 ? childImage : collectorImage;
      output.writeInt32LE(command.length, 0);
      let offset = 4;
      offset += output.write(image + '\0\0', offset);
      for (const argument of command) offset += output.write(argument + '\0', offset);
      length.writeBigUInt64LE(BigInt(offset));
      return 0;
    },
  });
  let error = null;
  try { await native.review.verifyCollectorGate(41001, 41002, input.first); }
  catch (failure) { error = String(failure); }
  results.push({mode, error});
}
const a = await fs.stat(input.first, {bigint: true}), b = await fs.stat(input.second, {bigint: true});
emit({spellings, sameImage: a.dev === b.dev && a.ino === b.ino, results});
""",
                {
                    "common": COMMON.as_uri(),
                    "first": str(first),
                    "second": str(second),
                    "different": str(different),
                    "alias": str(alias),
                    "true": shutil.which("true"),
                },
            )
            self.assertTrue(result["sameImage"], result)
            self.assertEqual(
                result["spellings"],
                [[str(first), str(second), str(second)]] * 3,
                result,
            )
            for row in result["results"]:
                with self.subTest(mode=row["mode"]):
                    if row["mode"] in ("hardlink", "admitted"):
                        self.assertIsNone(row["error"], row)
                    else:
                        self.assertIn("different actual interpreter", row["error"], row)

    def test_one_element_subject_passes_collector_gate_and_empty_argument_rejects(self):
        for malformed in (False, True):
            with (
                self.subTest(malformed=malformed),
                tempfile.TemporaryDirectory(prefix="r38-gate-argv-") as directory,
            ):
                root = Path(directory).resolve()
                collector = root / "collector.py"
                collector.write_text(COLLECTOR)
                subject = [shutil.which("true")]
                if malformed:
                    subject.append("--empty-test-arg")
                response = driver_result(
                    {
                        "mode": "native",
                        "cwd": str(root),
                        "environment": native_environment(root),
                        "command": [
                            str(Path(sys.executable).resolve()),
                            "-I",
                            "-B",
                            str(collector),
                            *subject,
                        ],
                        "ownership_protocol": "dossier-quint-private-pipes/v1",
                    }
                )
                if malformed:
                    self.assertEqual(response["event"], "result", response)
                    value = response["value"]
                    self.assertIn("approved collector gate", value["error"], value)
                    lifetime = next(
                        window
                        for window in value["ownership"]["spawn_windows"]
                        if window["protocol"] == "dossier-quint-private-pipes/v1"
                    )
                    self.assertEqual(lifetime["state"], "indeterminate", value)
                    self.assertEqual(len(value["ownership"]["children"]), 1, value)
                    self.assertTrue(
                        (root / ".fv/evidence/v4/locks/publication.lock").exists()
                    )
                else:
                    self.assertEqual(response["event"], "result", response)
                    value = response["value"]
                    self.assertIsNone(value["error"], value)
                    self.assertEqual(value["termination"]["exit_code"], 0, value)
                    self.assertTrue(
                        all(
                            window["state"] == "closed"
                            for window in value["ownership"]["spawn_windows"]
                        ),
                        value,
                    )
                    self.assertEqual(len(value["ownership"]["children"]), 2, value)


if __name__ == "__main__":
    unittest.main()
