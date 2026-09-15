#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""R14: proof CLI contracts against the locked BOM.

Two halves. The BOM half asserts that every pinned external tool still
advertises the flags `bom.json` records and still reports its pinned version.
The local half asserts the CLI contracts this repo's own scripts owe their
callers — currently `pyramid_run.py --plan`, whose fv-verification-plan/v1
input is validated fail-closed before any layer runs (a bad plan is ERROR,
exit 2, never a silently-legacy run). That includes custom layer ids: a plan
may name a layer the pyramid has no default for (`quint`), but the id must
match the documented pattern and may not be a reserved id (`floors`). Local
scripts are not BOM-pinned tools, so their contracts are asserted here
directly.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BOM = json.loads((REPO / "bom.json").read_text())
FAILURES: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"  [ok]   {label}")
    else:
        print(f"  [FAIL] {label}" + (f" ({detail})" if detail else ""))
        FAILURES.append(label)


def help_output(command: str) -> str:
    result = subprocess.run([*command.split(), "--help"], capture_output=True, text=True, timeout=120)
    return result.stdout + result.stderr


RUNNER = REPO / "scripts" / "pyramid_run.py"
PLAN_SCHEMA = "fv-verification-plan/v1"


def run_runner(crate: Path, *extra: str) -> tuple[int, str]:
    result = subprocess.run(
        [sys.executable, str(RUNNER), "--crate", str(crate),
         "--profile", "tested", *extra],
        capture_output=True, text=True, timeout=300,
    )
    return result.returncode, result.stdout + result.stderr


def plan_document(**execution) -> dict:
    declared = {"argv": ["true"], "cwd": ".", "timeout_seconds": 5}
    declared.update(execution)
    return {"schema": PLAN_SCHEMA,
            "layers": {"types": {"required": True, "executions": [declared]}}}


def check_pyramid_plan_cli() -> None:
    """`pyramid_run.py --plan`: advertised flag plus fail-closed rejections."""
    help_text = subprocess.run([sys.executable, str(RUNNER), "--help"],
                               capture_output=True, text=True,
                               timeout=120).stdout
    check("`pyramid_run.py` supports --plan", "--plan" in help_text)
    check("`pyramid_run.py --plan` names its schema in --help",
          PLAN_SCHEMA in help_text)
    check("`pyramid_run.py --plan` advertises custom layers in --help",
          "custom layers" in help_text)

    with tempfile.TemporaryDirectory(prefix="r14-plan-") as td:
        root = Path(td)
        crate = root / "crate"
        crate.mkdir()
        (crate / "Cargo.toml").write_text(
            "[package]\nname = \"planless\"\nversion = \"0.1.0\"\nedition = \"2021\"\n")
        (root / "outside").mkdir()
        plan = crate / "plan.json"

        def rejected(label: str, document: object, fragment: str) -> None:
            plan.write_text(json.dumps(document))
            code, output = run_runner(crate, "--plan", str(plan))
            check(label,
                  code == 2 and "VERDICT: ERROR" in output and fragment in output,
                  f"exit={code} {output.strip().splitlines()[:2]}")

        rejected("`--plan`: parent-escaping cwd rejected as ERROR",
                 plan_document(cwd="../outside"), "cwd escapes the crate root")
        rejected("`--plan`: absolute cwd rejected as ERROR",
                 plan_document(cwd=str(root / "outside")),
                 "cwd must be repo-relative")
        rejected("`--plan`: shell string instead of argv rejected as ERROR",
                 plan_document(argv="cargo check --quiet"),
                 "argv must be a non-empty array of strings")
        rejected("`--plan`: non-positive timeout rejected as ERROR",
                 plan_document(timeout_seconds=0),
                 "timeout_seconds must be a positive integer")
        rejected("`--plan`: non-string env value rejected as ERROR",
                 plan_document(env={"PROPTEST_CASES": 1024}),
                 "must be a string without NUL")
        rejected("`--plan`: unsupported schema rejected as ERROR",
                 {**plan_document(), "schema": "fv-verification-plan/v99"},
                 "unsupported schema")
        rejected("`--plan`: computed floors layer rejected as ERROR",
                 {"schema": PLAN_SCHEMA, "layers": {"floors": {
                     "required": True,
                     "executions": [{"argv": ["true"], "cwd": ".",
                                     "timeout_seconds": 5}]}}},
                 "not plannable")
        for malformed in ("-quint", "qu int", "quint$"):
            rejected(f"`--plan`: malformed custom layer id {malformed!r} "
                     "rejected as ERROR",
                     {"schema": PLAN_SCHEMA, "layers": {malformed: {
                         "required": True,
                         "executions": [{"argv": ["true"], "cwd": ".",
                                         "timeout_seconds": 5}]}}},
                     f"custom layer id {malformed!r} is malformed")

        plan.write_text("{not json")
        code, output = run_runner(crate, "--plan", str(plan))
        check("`--plan`: malformed JSON rejected as ERROR",
              code == 2 and "malformed JSON" in output, f"exit={code}")
        code, output = run_runner(crate, "--plan", str(crate / "absent.json"))
        check("`--plan`: missing plan file rejected as ERROR",
              code == 2 and "cannot read plan" in output, f"exit={code}")


def main() -> int:
    check_pyramid_plan_cli()

    if shutil.which("quint") is None:
        print("SKIP-FAIL: quint not on PATH", file=sys.stderr)
        return 1 if FAILURES else 2
    for command, flags in BOM["cli_contracts"].items():
        output = help_output(command)
        for flag in flags:
            check(f"`{command}` supports {flag}", flag in output)
    live_quint = subprocess.run(["quint", "--version"], capture_output=True, text=True).stdout.strip()
    quint_pin = BOM["tools"]["quint"]
    check(f"quint version matches BOM pin {quint_pin}", live_quint == quint_pin, f"live={live_quint}")

    if shutil.which("cargo-kani"):
        live = subprocess.run(["cargo", "kani", "--version"], capture_output=True, text=True).stdout.strip()
        pin = BOM["tools"]["cargo-kani"]
        check(f"cargo-kani version matches BOM pin {pin}", pin in live, f"live={live}")
    if shutil.which("lean"):
        result = subprocess.run(["lean", "--version"], capture_output=True, text=True)
        if result.returncode == 0:
            live = result.stdout.strip()
            pin = BOM["tools"]["lean"]
            check(f"lean version matches BOM pin {pin}", pin in live, f"live={live}")

    for mcp_script in sorted((REPO / "mcp").glob("*/[a-z]*_mcp.py")):
        head = mcp_script.read_text()[:500]
        if "mcp>=" in head:
            check(f"{mcp_script.relative_to(REPO)}: mcp dep upper-bounded", 'mcp>=1.2.0,<2' in head)
        if "httpx>=" in head:
            check(f"{mcp_script.relative_to(REPO)}: httpx dep upper-bounded", 'httpx>=0.27.0,<1' in head)
    print()
    if FAILURES:
        print(f"R14: {len(FAILURES)} failure(s)")
        return 1
    print("R14: all assertions passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
