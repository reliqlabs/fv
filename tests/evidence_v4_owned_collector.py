"""Private-pipe collector fixture with the reviewed gated transport."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import select
import signal
import subprocess
import sys
from pathlib import Path

OWNED_CHILD_START = r"""
import os, sys
fd = int(sys.argv[1])
ready = os.read(fd, 1)
os.close(fd)
if ready != b'1':
    sys.exit(125)
os.execvpe(sys.argv[2], sys.argv[2:], os.environ)
"""


def publish(directory: Path, name: str, value: dict) -> None:
    target = directory / name
    staging = directory / (name + ".pending")
    with staging.open("x") as stream:
        json.dump(value, stream)
        stream.flush()
        os.fsync(stream.fileno())
    os.link(staging, target)
    staging.unlink()


def main() -> int:
    mode, directory_text = sys.argv[1:3]
    directory = Path(directory_text)
    if mode == "backpressure":
        index = int(sys.argv[3])
        public = os.environ["FV_NATIVE_TRANSPORT_PUBLIC"]
        if public != "\n" * (40 * 1024):
            return 23
        public_hash = hashlib.sha256(public.encode("utf-8")).hexdigest()
        publish(
            directory,
            f"ready-{index}.json",
            {
                "pid": os.getpid(),
                "public_bytes": len(public),
                "public_hash": public_hash,
            },
        )
        with (directory / f"gate-{index}.fifo").open("rb", buffering=0) as stream:
            if stream.read(1) != b"1":
                return 24
        print(f"native-backpressure:{index}:{len(public)}:{public_hash}", flush=True)
        return 0
    if mode == "subject":
        print("test result: ok.", flush=True)
        publish(
            directory,
            "subject.json",
            {"pid": os.getpid(), "pgid": os.getpgrp(), "sid": os.getsid(0)},
        )
        if (directory / "hold").exists():
            with (directory / "release.fifo").open("rb", buffering=0) as stream:
                if stream.read(1) != b"1":
                    return 19
        return 0

    descriptors = os.environ.get("DOSSIER_QUINT_OWNERSHIP_FDS")
    if descriptors != "3,4":
        raise RuntimeError("private ownership descriptors were not supplied")
    event_fd, ack_fd = map(int, descriptors.split(","))

    def notify(event: str, pid: int) -> None:
        os.write(event_fd, json.dumps({"event": event, "pgid": pid}).encode() + b"\n")
        ready, _, _ = select.select([ack_fd], [], [], 15)
        if not ready or os.read(ack_fd, 1) != b"1":
            raise RuntimeError("host did not acknowledge ownership transition")

    gate_read, gate_write = os.pipe()
    command = [
        sys.executable,
        "-I",
        "-B",
        str(Path(__file__).resolve()),
        "subject",
        str(directory),
    ]
    process = subprocess.Popen(
        [sys.executable, "-I", "-B", "-c", OWNED_CHILD_START, str(gate_read), *command],
        start_new_session=True,
        pass_fds=(gate_read,),
        stdin=subprocess.DEVNULL,
    )
    os.close(gate_read)
    publish(directory, "gated.json", {"pid": process.pid, "collector_pid": os.getpid()})
    cancelled = False

    def cancel(_signum, _frame):
        nonlocal cancelled
        cancelled = True
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGTERM)

    signal.signal(signal.SIGTERM, cancel)
    signal.signal(signal.SIGINT, cancel)
    try:
        notify("owned", process.pid)
        publish(
            directory,
            "acknowledged.json",
            {
                "pid": process.pid,
                "subject_present": (directory / "subject.json").exists(),
            },
        )
        os.write(gate_write, b"1")
        os.close(gate_write)
        gate_write = -1
        try:
            code = process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            code = process.wait(timeout=5)
        notify("released", process.pid)
        publish(
            directory,
            "released.json",
            {"pid": process.pid, "code": code, "cancelled": cancelled},
        )
        return 128 if cancelled else code
    finally:
        if gate_write >= 0:
            os.close(gate_write)
        if process.poll() is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
