#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""R33: OMP calibration fallback suppression is process-scoped and auditable."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
LAUNCHER = SCRIPTS / "omp_calibration_session.py"
FAILURES: list[str] = []


def check(label: str, ok: bool, detail: object = "") -> None:
    if ok:
        print(f"[ok] {label}")
    else:
        print(f"[FAIL] {label}: {detail}")
        FAILURES.append(label)


def run(argv: list[str], *, env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, timeout=120, env=env)


def init(project: Path, *, env: dict[str, str]) -> subprocess.CompletedProcess:
    return run([
        "uv", "run", "--script", str(SCRIPTS / "fv_init.py"),
        str(project),
    ], env=env)


def fake_omp(path: Path) -> None:
    path.write_text("""#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

argv = sys.argv[1:]
config_source = (
    argv[argv.index('--config') + 1]
    if '--config' in argv
    else os.environ['PI_CONFIG_FILES']
)
config = Path(config_source.split(os.pathsep)[-1])
chains = json.loads(config.read_text())['retry']['fallbackChains']
if argv[-3:] == ['config', 'get', 'retry.fallbackChains']:
    if os.environ.get('FAKE_PRECHECK_TAINT'):
        first = next(iter(chains))
        chains[first] = ['unexpected/fallback']
    print(json.dumps(chains))
    raise SystemExit(0)
Path(os.environ['TEST_CAPTURE']).write_text(json.dumps({
    'argv': argv,
    'overlay': os.environ.get('FV_OMP_FALLBACK_OVERLAY'),
    'precheck': os.environ.get('FV_OMP_FALLBACK_PRECHECK'),
    'config_files': os.environ.get('PI_CONFIG_FILES'),
}))
raise SystemExit(int(os.environ.get('FAKE_LAUNCH_EXIT', '0')))
""")
    path.chmod(0o755)


def invoke(project: Path, evidence: Path, omp: Path, *voices: str,
           env: dict[str, str]) -> subprocess.CompletedProcess:
    return run([
        "uv", "run", "--script", str(LAUNCHER),
        "--project", str(project),
        "--evidence-dir", str(evidence),
        *(item for voice in voices for item in ("--voice", voice)),
        "--omp", str(omp), "--", "-p", "do not dispatch any agents",
    ], env=env)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="r33-omp-") as td:
        root = Path(td)
        capture = root / "capture.json"
        fake = root / "omp"
        fake_omp(fake)
        inherited_overlay = root / "inherited-overlay.json"
        inherited_overlay.write_text("{}")
        env = os.environ | {
            "TEST_CAPTURE": str(capture),
            "PI_CONFIG_FILES": str(inherited_overlay),
        }
        project = root / "project"
        seeded = init(project, env=env)
        check("OMP project init succeeds", seeded.returncode == 0, seeded.stderr[-300:])

        evidence = root / "evidence"
        evidence.mkdir()
        launched = invoke(project, evidence, fake, "claude-agent", "gpt-6-astra", env=env)
        check("scoped calibration launcher exits with OMP's result", launched.returncode == 0,
              launched.stderr[-300:])
        overlay = json.loads((evidence / "omp-fallback-suppression.json").read_text())
        expected = {
            "anthropic/claude-fable-5-1": [],
            "openai-codex/gpt-6-astra": [],
        }
        check("overlay disables only the exact selected route chains",
              overlay == {"retry": {"fallbackChains": expected}}, overlay)
        precheck = json.loads((evidence / "omp-fallback-precheck.json").read_text())
        overlay_path = str((evidence / "omp-fallback-suppression.json").resolve())
        config_sources = os.pathsep.join((str(inherited_overlay), overlay_path))
        check("precheck records the effective empty chains and binds the overlay",
              precheck["effective_fallback_chains"] == expected
              and precheck["overlay_sha256"].startswith("sha256:")
              and precheck["command"] == [str(fake), "config", "get", "retry.fallbackChains"]
              and precheck["cwd"] == str(project.resolve())
              and precheck["environment"] == {"PI_CONFIG_FILES": config_sources},
              precheck)
        launch = json.loads((evidence / "omp-fallback-launch.json").read_text())
        captured = json.loads(capture.read_text())
        precheck_path = str((evidence / "omp-fallback-precheck.json").resolve())
        check("OMP receives the recorded process-local overlay and certificate paths",
              launch["status"] == "exited" and launch["returncode"] == 0
              and launch["command"] == [str(fake), "--cwd", str(project.resolve()),
                                        "--config", overlay_path,
                                        "-p", "do not dispatch any agents"]
              and captured["overlay"] == overlay_path
              and captured["precheck"] == precheck_path
              and captured["config_files"] == config_sources,
              {"launch": launch, "captured": captured})

        tainted = root / "tainted-evidence"
        capture_before = capture.read_bytes()
        tainted.mkdir()
        tainted_env = env | {"FAKE_PRECHECK_TAINT": "1"}
        refused = invoke(project, tainted, fake, "claude-agent", env=tainted_env)
        check("launcher refuses before OMP starts when precheck exposes fallback",
              refused.returncode == 2
              and (tainted / "omp-fallback-precheck.json").is_file()
              and not (tainted / "omp-fallback-launch.json").exists()
              and capture.read_bytes() == capture_before,
              refused.stderr[-300:])

    if FAILURES:
        print(f"R33: {len(FAILURES)} failure(s)", file=sys.stderr)
        return 1
    print("R33: all assertions passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
