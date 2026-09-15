#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
R28 — engineering baseline floors (C8).

The `floors` layer is a required layer under every profile (tested, and
therefore bounded/proved). It reads <crate>/.fv/floors.json (documented
defaults when absent) and runs three mechanical sub-checks: a cargo feature
matrix (with --workspace on workspaces), a per-public-module property-test bar,
and a per-surface fuzz-time floor. This suite drives the pure floor helpers
directly, then runs the headless runner end-to-end against fixture crates:

  below/          public module with zero in-file tests + a floors.json fuzz
                  surface with no target -> floors FAILED, run FAILED (exit 1)
  compliant/      in-file test, compiling feature matrix, no fuzz surfaces ->
                  floors passed, run VERIFIED[tested] (exit 0)
  featurefail/    a floors.json feature combo fails cargo check -> floors
                  FAILED via the feature-matrix sub-check, run FAILED (exit 1)
  fuzzunmeasured/ named surface has a target but the fuzz run is unavailable ->
                  the fuzz-time floor is unmeasurable -> floors skipped,
                  run INCOMPLETE (exit 3)
  <defaults>      the R20 minicrate (no floors.json) exercises the default
                  floors: property bar met by its inline #[test], no matrix,
                  no fuzz -> floors passed, run VERIFIED[tested] (exit 0)

The plan half covers `--plan` (fv-verification-plan/v1): validation rejections
(shell strings, absolute/escaping cwd, non-positive timeouts, non-string env),
canonical layer order, exact argv/cwd/env delivery, multi-invocation layer
failure, required-layer aggregation, and that a plan file sitting on disk stays
inert without --plan.

The custom-layer half covers plan-declared layers the pyramid has no default
for (`quint`, `mutation`): id acceptance/rejection, execution after every known
layer in lexical order, exact argv/cwd/env delivery and report shape,
required:true joining the G2 gating set (and required:false never gating),
--skip, and a types failure marking every required or declared custom layer
not_run without running an invocation.

The failure-containment half covers commands that cannot run at all: an absent
executable, a non-executable file and a vanished cwd are structured `failed`
executions (returncode -1 plus `launch_error`), never a traceback and never a
missing report; a timeout is still reported as a timeout; a report that cannot
be persisted is ERROR (exit 2) with the report still on stdout; and one
evidence_tool id may name only one invocation plan-wide.

Requires cargo. Exit 0 pass, 1 fail, 2 toolchain unavailable.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RUNNER = REPO / "scripts" / "pyramid_run.py"
FIX = REPO / "tests" / "fixtures" / "r28"
MINICRATE = REPO / "tests" / "fixtures" / "r20" / "minicrate"
PLAN_EXAMPLE = REPO / "scripts" / "verification-plan.example.json"
PLAN_SCHEMA = "fv-verification-plan/v1"

# Records the exact argv, cwd and environment the runner handed this child.
PROBE = '''\
import json
import os
import sys

log, label, code = sys.argv[1], sys.argv[2], int(sys.argv[3])
with open(log, "a", encoding="utf-8") as handle:
    handle.write(json.dumps({
        "label": label,
        "argv": sys.argv,
        "cwd": os.getcwd(),
        "declared": os.environ.get("FV_PLAN_DECLARED"),
        "inherited_path": bool(os.environ.get("PATH")),
    }) + "\\n")
sys.exit(code)
'''
FAILURES: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"  [ok]   {label}")
    else:
        suffix = f" ({detail})" if detail else ""
        print(f"  [FAIL] {label}{suffix}")
        FAILURES.append(label)


def load_runner():
    spec = importlib.util.spec_from_file_location("pyramid_run", RUNNER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run(crate: Path, profile: str, *extra: str) -> tuple[int, str]:
    proc = subprocess.run(
        ["uv", "run", "--script", str(RUNNER), "--crate", str(crate),
         "--profile", profile, *extra],
        capture_output=True, text=True, timeout=900,
    )
    return proc.returncode, proc.stdout + proc.stderr


def floors_status(crate: Path) -> tuple[str, dict]:
    """Read the layer status and sub-check statuses from the persisted report."""
    reports = sorted((crate / ".fv" / "verify").glob("headless-*.json"))
    report = json.loads(reports[-1].read_text())
    floors = report["layers"].get("floors", {})
    subs = {k: v["status"]
            for k, v in floors.get("detail", {}).get("subchecks", {}).items()}
    return floors.get("status", "MISSING"), subs


def test_pure(mod) -> None:
    print("pure floor helpers")

    # load_floors: absent file -> documented defaults.
    d = mod.load_floors(Path("/definitely/not/a/crate"))
    check("load_floors: absent floors.json -> defaults",
          d["property_tests"]["min_per_module"] == 1
          and d["fuzz"]["min_seconds"] == 30
          and d["features"]["matrix"] == []
          and d["schema"] == "fv-floors/v2", str(d))

    # load_floors: present file layers over defaults, keeps default sub-keys.
    with tempfile.TemporaryDirectory(prefix="r28-lf-") as td:
        crate = Path(td)
        (crate / ".fv").mkdir()
        (crate / ".fv" / "floors.json").write_text(
            json.dumps({"property_tests": {"min_per_module": 3}}))
        d = mod.load_floors(crate)
        check("load_floors: file section overrides default, keeps sibling keys",
              d["property_tests"]["min_per_module"] == 3
              and d["property_tests"]["require_property_tests"] is False,
              str(d["property_tests"]))
        (crate / ".fv" / "floors.json").write_text(
            json.dumps({"schema": "fv-floors/v999"}))
        rejected = False
        try:
            mod.load_floors(crate)
        except ValueError:
            rejected = True
        check("load_floors: explicit non-v2 schema rejected", rejected)

    # is_workspace.
    with tempfile.TemporaryDirectory(prefix="r28-ws-") as td:
        crate = Path(td)
        (crate / "Cargo.toml").write_text("[workspace]\nmembers = []\n")
        check("is_workspace: [workspace] table detected", mod.is_workspace(crate))
        (crate / "Cargo.toml").write_text("[package]\nname = \"x\"\n")
        check("is_workspace: plain package is not a workspace",
              not mod.is_workspace(crate))

    # count_tests / has_public_api.
    src_test = "#[test]\nfn a() {}\n"
    check("count_tests: #[test] counted", mod.count_tests(src_test) == 1)
    check("count_tests: property_only excludes bare #[test]",
          mod.count_tests(src_test, property_only=True) == 0)
    check("count_tests: proptest!/quickcheck counted under property_only",
          mod.count_tests("proptest! { fn p() {} }\nquickcheck! { fn q() {} }",
                          property_only=True) == 2)
    check("has_public_api: pub fn is public surface",
          mod.has_public_api("pub fn f() {}"))
    check("has_public_api: pub(crate) is not public surface",
          not mod.has_public_api("pub(crate) fn f() {}"))

    # modules_below_bar over the fixtures.
    status, detail = mod.modules_below_bar(FIX / "below", mod.load_floors(FIX / "below"))
    check("modules_below_bar: below fixture fails, names the module",
          status == "failed" and detail["below_bar"] == ["src/lib.rs"], str(detail))
    status, _ = mod.modules_below_bar(FIX / "compliant",
                                      mod.load_floors(FIX / "compliant"))
    check("modules_below_bar: compliant fixture passes", status == "passed", status)
    status, _ = mod.modules_below_bar(MINICRATE, mod.load_floors(MINICRATE))
    check("modules_below_bar: R20 minicrate passes under defaults",
          status == "passed", status)
    # require_property_tests raises the bar: compliant has only #[test].
    strict = mod.load_floors(FIX / "compliant")
    strict["property_tests"]["require_property_tests"] = True
    status, detail = mod.modules_below_bar(FIX / "compliant", strict)
    check("modules_below_bar: require_property_tests rejects bare #[test]",
          status == "failed" and detail["below_bar"] == ["src/lib.rs"], str(detail))

    # fuzz_surface_check.
    status, _ = mod.fuzz_surface_check(FIX / "below", [], 30, None)
    check("fuzz_surface_check: no surfaces -> not_applicable",
          status == "not_applicable", status)
    status, detail = mod.fuzz_surface_check(FIX / "below", ["parse_surface"], 30, None)
    check("fuzz_surface_check: named surface with no target -> failed",
          status == "failed" and detail["missing_targets"] == ["parse_surface"],
          str(detail))
    status, _ = mod.fuzz_surface_check(FIX / "fuzzunmeasured", ["parse_input"], 30, None)
    check("fuzz_surface_check: target present, no fuzz run -> skipped (unmeasurable)",
          status == "skipped", status)
    passed_layer = {"status": "passed", "detail": {"durations": {"parse_input": 45}}}
    status, _ = mod.fuzz_surface_check(FIX / "fuzzunmeasured", ["parse_input"], 30,
                                       passed_layer)
    check("fuzz_surface_check: duration above floor -> passed", status == "passed",
          status)
    short_layer = {"status": "passed", "detail": {"durations": {"parse_input": 5}}}
    status, detail = mod.fuzz_surface_check(FIX / "fuzzunmeasured", ["parse_input"],
                                            30, short_layer)
    check("fuzz_surface_check: duration below floor -> failed",
          status == "failed" and detail["below_floor"] == ["parse_input"], str(detail))


def test_run_cmd(mod) -> None:
    print("run_cmd failure containment (a launch failure is a result, not a crash)")
    with tempfile.TemporaryDirectory(prefix="r28-runcmd-") as td:
        root = Path(td)

        absent = mod.run_cmd(["r28-definitely-not-a-binary"], root, timeout=5)
        check("run_cmd: an absent executable returns a structured failure",
              absent["returncode"] == -1
              and "FileNotFoundError" in absent.get("launch_error", "")
              and absent["command"] == ["r28-definitely-not-a-binary"],
              str(absent))

        vanished = mod.run_cmd([sys.executable, "-c", ""], root / "gone", timeout=5)
        check("run_cmd: a cwd that no longer exists returns a structured failure",
              vanished["returncode"] == -1 and "launch_error" in vanished,
              str(vanished))

        if os.geteuid() != 0:  # root ignores the executable bit
            script = root / "not-executable.sh"
            script.write_text("#!/bin/sh\nexit 0\n")
            script.chmod(0o444)
            denied = mod.run_cmd([str(script)], root, timeout=5)
            check("run_cmd: a non-executable file returns a structured failure",
                  denied["returncode"] == -1
                  and "PermissionError" in denied.get("launch_error", ""),
                  str(denied))

        # The new launch-failure branch must not swallow the timeout branch:
        # a timeout is still a timeout, and it is not a launch error.
        slow = mod.run_cmd([sys.executable, "-c", "import time; time.sleep(30)"],
                           root, timeout=1)
        check("run_cmd: a timeout stays a timeout, not a launch error",
              slow["returncode"] == -1 and slow.get("timeout") is True
              and "launch_error" not in slow, str(slow))


def write_plan(crate: Path, layers: dict) -> tuple[Path, dict]:
    """Write <crate>/.fv/verification-plan.json; return (path, document)."""
    document = {"schema": PLAN_SCHEMA, "layers": layers}
    path = crate / ".fv" / "verification-plan.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2) + "\n")
    return path, document


def probe(crate: Path, log: Path, label: str, code: int = 0, *, cwd: str = ".",
          env: dict | None = None, tool: str | None = None) -> dict:
    """A declared invocation of the probe script: exits `code`, logs its argv."""
    execution = {
        "argv": [sys.executable, str(crate / "probe.py"), str(log), label, str(code)],
        "cwd": cwd,
        "timeout_seconds": 120,
    }
    if env is not None:
        execution["env"] = env
    if tool is not None:
        execution["evidence_tool"] = tool
    return execution


def latest_report(crate: Path) -> dict:
    reports = sorted((crate / ".fv" / "verify").glob("headless-*.json"))
    return json.loads(reports[-1].read_text())


def test_plan_pure(mod) -> None:
    print("verification-plan validation (fv-verification-plan/v1)")

    def rejects(label: str, document: object, root: Path, fragment: str) -> None:
        try:
            mod.parse_plan(document, root, source="plan.json")
        except mod.PlanError as error:
            check(label, fragment in str(error), str(error))
        else:
            check(label, False, "accepted")

    with tempfile.TemporaryDirectory(prefix="r28-plan-pure-") as td:
        root = Path(td) / "crate"
        (root / "src").mkdir(parents=True)
        outside = Path(td) / "outside"
        outside.mkdir()
        (root / "escape").symlink_to(outside, target_is_directory=True)

        def one(**kwargs) -> dict:
            execution = {"argv": ["true"], "cwd": ".", "timeout_seconds": 5}
            execution.update(kwargs)
            return {"types": {"required": True, "executions": [execution]}}

        # The shipped example is a valid plan, ordered canonically on load:
        # known pyramid layers first, then its custom layers lexically
        # (the file declares `quint` before `mutation`).
        example = mod.load_plan(PLAN_EXAMPLE, REPO)
        check("example plan: validates against the shipped schema",
              example["schema"] == PLAN_SCHEMA
              and list(example["layers"]) == ["types", "lints", "proptests",
                                              "fuzz", "kani", "mutation",
                                              "quint"],
              str(list(example["layers"])))
        check("example plan: multi-invocation layer keeps its declared order",
              [e["argv"][1] for e in example["layers"]["lints"]["executions"]]
              == ["clippy", "fmt"],
              str(example["layers"]["lints"]["executions"]))
        check("example plan: custom quint layer is required and keeps its "
              "declared invocation order",
              example["layers"]["quint"]["required"] is True
              and [e["argv"][1] for e in example["layers"]["quint"]["executions"]]
              == ["typecheck", "verify"],
              str(example["layers"]["quint"]))

        # Deterministic layer order, independent of the document's key order:
        # known layers by LAYER_ORDER, custom layers lexically after them.
        plan = mod.parse_plan({"layers": {"quint": {"required": True,
                                                    "executions": [
                                                        {"argv": ["true"], "cwd": ".",
                                                         "timeout_seconds": 5}]},
                                          "lean": {"required": False,
                                                   "executions": [
                                                       {"argv": ["true"], "cwd": ".",
                                                        "timeout_seconds": 5}]},
                                          "mutation": {"required": False,
                                                       "executions": [
                                                           {"argv": ["true"],
                                                            "cwd": ".",
                                                            "timeout_seconds": 5}]},
                                          **one()}}, root)
        check("plan: known layers ordered by the canonical pyramid order, "
              "custom layers lexically after them",
              list(plan["layers"]) == ["types", "lean", "mutation", "quint"],
              str(list(plan["layers"])))
        check("plan_layer_order: known layers canonical, custom lexical",
              mod.plan_layer_order(["quint", "lean", "mutation", "types",
                                    "quint"])
              == ["types", "lean", "mutation", "quint"],
              str(mod.plan_layer_order(["quint", "lean", "mutation", "types"])))
        check("plan: custom layer executions validate like known ones",
              plan["layers"]["quint"]["executions"][0]
              == {"argv": ["true"], "cwd": ".", "timeout_seconds": 5,
                  "env": {}, "evidence_tool": None},
              str(plan["layers"]["quint"]["executions"][0]))
        check("plan: absent schema defaults to the current version",
              plan["schema"] == PLAN_SCHEMA, plan["schema"])

        normalized = mod.parse_plan({"layers": one(cwd="./src")}, root)
        execution = normalized["layers"]["types"]["executions"][0]
        check("plan: cwd normalized to a repo-relative POSIX path",
              execution["cwd"] == "src", execution["cwd"])
        check("plan: optional env/evidence_tool default to empty/None",
              execution["env"] == {} and execution["evidence_tool"] is None,
              str(execution))

        rejects("plan: non-object document rejected", ["types"], root,
                "plan must be a JSON object")
        rejects("plan: unknown top-level key rejected",
                {"layers": one(), "profile": "tested"}, root,
                "unknown top-level key(s) ['profile']")
        rejects("plan: unsupported schema rejected",
                {"schema": "fv-verification-plan/v99", "layers": one()}, root,
                "unsupported schema")
        rejects("plan: empty layers map rejected", {"layers": {}}, root,
                "layers must be a non-empty object")
        rejects("plan: floors is not plannable (computed from floors.json)",
                {"layers": {"floors": {"required": True, "executions": [
                    {"argv": ["true"], "cwd": ".", "timeout_seconds": 5}]}}}, root,
                "not plannable")
        # A layer id the pyramid does not know names a custom layer: accepted
        # when it matches PLAN_CUSTOM_ID, rejected otherwise. `floors` stays
        # reserved (asserted above) and can never be reused as a custom id.
        for custom in ("quint", "mutation", "tla+", "spec:core", "a.b-c/d", "Q7"):
            accepted = mod.parse_plan(
                {"layers": {custom: {"required": True, "executions": [
                    {"argv": ["true"], "cwd": ".", "timeout_seconds": 5}]}}}, root)
            check(f"plan: custom layer id {custom!r} accepted",
                  list(accepted["layers"]) == [custom]
                  and accepted["layers"][custom]["required"] is True,
                  str(accepted["layers"]))
        for malformed in ("", "-lead", ".lead", "has space", "quint\n", "q$x",
                          "sp\0ec"):
            rejects(f"plan: malformed custom layer id {malformed!r} rejected",
                    {"layers": {malformed: {"required": True, "executions": [
                        {"argv": ["true"], "cwd": ".",
                         "timeout_seconds": 5}]}}}, root,
                    f"custom layer id {malformed!r} is malformed")
        rejects("plan: non-boolean required rejected",
                {"layers": {"types": {"required": "yes", "executions": [
                    {"argv": ["true"], "cwd": ".", "timeout_seconds": 5}]}}}, root,
                "required must be a boolean")
        rejects("plan: empty executions array rejected",
                {"layers": {"types": {"required": True, "executions": []}}}, root,
                "executions must be a non-empty array")
        rejects("plan: unknown execution key rejected",
                {"layers": one(shell=True)}, root, "unknown key(s) ['shell']")
        rejects("plan: shell string instead of an argv array rejected",
                {"layers": one(argv="cargo check --quiet")}, root,
                "argv must be a non-empty array of strings")
        rejects("plan: empty argv rejected", {"layers": one(argv=[])}, root,
                "argv must be a non-empty array of strings")
        rejects("plan: non-string argv word rejected",
                {"layers": one(argv=["cargo", 7])}, root,
                "argv[1] must be a non-empty string")
        rejects("plan: empty argv word rejected",
                {"layers": one(argv=["cargo", ""])}, root,
                "argv[1] must be a non-empty string")
        rejects("plan: zero timeout rejected", {"layers": one(timeout_seconds=0)},
                root, "timeout_seconds must be a positive integer")
        rejects("plan: negative timeout rejected",
                {"layers": one(timeout_seconds=-5)}, root,
                "timeout_seconds must be a positive integer")
        rejects("plan: fractional timeout rejected",
                {"layers": one(timeout_seconds=1.5)}, root,
                "timeout_seconds must be a positive integer")
        rejects("plan: boolean timeout rejected",
                {"layers": one(timeout_seconds=True)}, root,
                "timeout_seconds must be a positive integer")
        rejects("plan: missing timeout rejected",
                {"layers": {"types": {"required": True, "executions": [
                    {"argv": ["true"], "cwd": "."}]}}}, root,
                "timeout_seconds must be a positive integer")
        rejects("plan: non-object env rejected", {"layers": one(env=["A=1"])},
                root, "env must be an object mapping string to string")
        rejects("plan: non-string env value rejected",
                {"layers": one(env={"CASES": 1024})}, root,
                "must be a string without NUL")
        rejects("plan: empty env name rejected", {"layers": one(env={"": "x"})},
                root, "env name must be a non-empty string")
        rejects("plan: missing cwd rejected",
                {"layers": {"types": {"required": True, "executions": [
                    {"argv": ["true"], "timeout_seconds": 5}]}}}, root,
                "cwd must be a non-empty repo-relative string")
        rejects("plan: absolute cwd rejected", {"layers": one(cwd=str(outside))},
                root, "cwd must be repo-relative")
        rejects("plan: parent-escaping cwd rejected",
                {"layers": one(cwd="../outside")}, root,
                "cwd escapes the crate root")
        rejects("plan: nested parent-escaping cwd rejected",
                {"layers": one(cwd="src/../../outside")}, root,
                "cwd escapes the crate root")
        rejects("plan: symlink escape rejected", {"layers": one(cwd="escape")},
                root, "cwd escapes the crate root")
        rejects("plan: non-existent cwd rejected", {"layers": one(cwd="nope")},
                root, "cwd is not a directory")

        # evidence_tool names exactly one invocation: the runner keys each
        # measured duration by it, so a repeated id would merge two recorded
        # verifications into one witnessed tool instead of being rejected.
        def witnessed(tool: str) -> dict:
            return {"argv": ["true"], "cwd": ".", "timeout_seconds": 5,
                    "evidence_tool": tool}

        rejects("plan: the same evidence_tool twice in one cohort rejected",
                {"layers": {"quint": {"required": True, "executions": [
                    witnessed("quint"), witnessed("quint")]}}}, root,
                "evidence_tool 'quint' is declared twice")
        rejects("plan: the same evidence_tool across two layers rejected",
                {"layers": {
                    "types": {"required": True,
                              "executions": [witnessed("cargo-check")]},
                    "lints": {"required": True,
                              "executions": [witnessed("cargo-check")]}}}, root,
                "evidence_tool 'cargo-check' is declared twice")
        cohort = mod.parse_plan(
            {"layers": {"quint": {"required": True, "executions": [
                witnessed("quint:run1.1"), witnessed("quint:run2.1"),
                witnessed("quint")]}}}, root)
        check("plan: distinct per-run evidence_tool ids in one cohort accepted",
              [execution["evidence_tool"]
               for execution in cohort["layers"]["quint"]["executions"]]
              == ["quint:run1.1", "quint:run2.1", "quint"],
              str(cohort["layers"]["quint"]["executions"]))
        toolless = mod.parse_plan(
            {"layers": {"quint": {"required": True, "executions": [
                {"argv": ["true"], "cwd": ".", "timeout_seconds": 5},
                {"argv": ["true"], "cwd": ".", "timeout_seconds": 5}]}}}, root)
        check("plan: executions without an evidence_tool are not duplicates",
              len(toolless["layers"]["quint"]["executions"]) == 2,
              str(toolless["layers"]["quint"]["executions"]))


def test_plan_runner() -> None:
    print("headless runner under a declarative plan (--plan)")
    with tempfile.TemporaryDirectory(prefix="r28-plan-run-") as td:
        tmp = Path(td)

        # Declared out of pyramid order on purpose: execution order is canonical.
        crate = tmp / "planned"
        shutil.copytree(MINICRATE, crate)
        (crate / "probe.py").write_text(PROBE)
        log = tmp / "planned.log"
        plan, document = write_plan(crate, {
            "proptests": {"required": True,
                          "executions": [probe(crate, log, "proptests", cwd="src")]},
            "types": {"required": True,
                      "executions": [probe(crate, log, "types",
                                           env={"FV_PLAN_DECLARED": "types-value"},
                                           tool="probe-types")]},
            "lints": {"required": True,
                      "executions": [probe(crate, log, "lints-a"),
                                     probe(crate, log, "lints-b", code=3)]},
        })
        code, out = run(crate, "tested", "--plan", str(plan))
        records = [json.loads(line) for line in log.read_text().splitlines()]
        report = latest_report(crate)

        check("plan run: layers execute in canonical order, not file order",
              [r["label"] for r in records]
              == ["types", "lints-a", "lints-b", "proptests"],
              str([r["label"] for r in records]))
        declared = document["layers"]["types"]["executions"][0]["argv"]
        check("plan run: child receives exactly the declared argv",
              records[0]["argv"] == declared[1:], str(records[0]["argv"]))
        check("plan run: child runs in the declared cwd (crate root)",
              records[0]["cwd"] == str(crate.resolve()), records[0]["cwd"])
        check("plan run: declared env reaches the child",
              records[0]["declared"] == "types-value", str(records[0]["declared"]))
        check("plan run: declared env merges over the ambient environment",
              records[0]["inherited_path"] is True, str(records[0]))
        check("plan run: repo-relative subdirectory cwd honoured",
              records[-1]["cwd"] == str((crate / "src").resolve()),
              records[-1]["cwd"])
        check("plan run: declared env does not leak into sibling invocations",
              records[-1]["declared"] is None, str(records[-1]["declared"]))

        lints = report["layers"]["lints"]
        codes = [e["returncode"] for e in lints["detail"]["executions"]]
        check("plan run: every invocation runs; any non-zero fails the layer",
              lints["status"] == "failed" and codes == [0, 3],
              f"{lints['status']} {codes}")
        first = lints["detail"]["executions"][0]
        check("plan run: report records argv, cwd and timeout per invocation",
              first["command"] == document["layers"]["lints"]["executions"][0]["argv"]
              and first["cwd"] == "." and first["timeout_seconds"] == 120,
              str(first))
        types_exec = report["layers"]["types"]["detail"]["executions"][0]
        check("plan run: report records the declared env and evidence_tool",
              types_exec["env"] == {"FV_PLAN_DECLARED": "types-value"}
              and types_exec["evidence_tool"] == "probe-types", str(types_exec))
        check("plan run: failing required plan layer gates FAILED, exit 1",
              code == 1 and "FAILED" in out, f"exit={code}")
        check("plan run: report carries the plan provenance",
              report.get("plan", {}).get("schema") == PLAN_SCHEMA
              and report["plan"]["source"] == str(plan), str(report.get("plan")))
        check("plan run: unplanned layers keep their built-in behaviour",
              report["layers"]["floors"]["status"] == "passed",
              report["layers"]["floors"]["status"])

        # A plan-declared fuzz invocation names its surface via evidence_tool,
        # and its measured duration is what the C8 fuzz-time floor reads.
        for floor, expected, label in ((30, "failed", "below"), (0, "passed", "above")):
            fuzzed = tmp / f"fuzzed-{label}"
            shutil.copytree(FIX / "fuzzunmeasured", fuzzed)
            (fuzzed / "probe.py").write_text(PROBE)
            flog = tmp / f"fuzzed-{label}.log"
            floors_cfg = json.loads((fuzzed / ".fv" / "floors.json").read_text())
            floors_cfg["fuzz"]["min_seconds"] = floor
            (fuzzed / ".fv" / "floors.json").write_text(json.dumps(floors_cfg))
            plan, _ = write_plan(fuzzed, {
                "types": {"required": True, "executions": [probe(fuzzed, flog, "t")]},
                "lints": {"required": True, "executions": [probe(fuzzed, flog, "l")]},
                "proptests": {"required": True,
                              "executions": [probe(fuzzed, flog, "p")]},
                "fuzz": {"required": True,
                         "executions": [probe(fuzzed, flog, "f",
                                              tool="parse_input")]},
            })
            code, out = run(fuzzed, "tested", "--plan", str(plan))
            report = latest_report(fuzzed)
            st, subs = floors_status(fuzzed)
            durations = report["layers"]["fuzz"]["detail"]["durations"]
            check(f"plan run: fuzz duration keyed by evidence_tool ({label} floor)",
                  "parse_input" in durations, str(durations))
            check(f"plan run: C8 fuzz-time floor reads the planned duration "
                  f"({label} floor -> {expected})",
                  subs.get("fuzz_surfaces") == expected and st == expected,
                  f"exit={code} {st} {subs}")

        # required:false runs the layer but never gates the verdict.
        lenient = tmp / "lenient"
        shutil.copytree(MINICRATE, lenient)
        (lenient / "probe.py").write_text(PROBE)
        llog = tmp / "lenient.log"
        plan, _ = write_plan(lenient, {
            "types": {"required": True, "executions": [probe(lenient, llog, "t")]},
            "lints": {"required": True, "executions": [probe(lenient, llog, "l")]},
            "proptests": {"required": True,
                          "executions": [probe(lenient, llog, "p")]},
            "kani": {"required": False,
                     "executions": [probe(lenient, llog, "k", code=1)]},
        })
        code, out = run(lenient, "tested", "--plan", str(plan))
        report = latest_report(lenient)
        check("plan run: required:false layer runs but does not gate",
              code == 0 and "VERIFIED[tested]" in out
              and report["layers"]["kani"]["status"] == "failed"
              and "kani" not in report["required_layers"],
              f"exit={code} required={report['required_layers']}")

        # required:true adds a non-profile layer to the gating set.
        strict = tmp / "strict"
        shutil.copytree(MINICRATE, strict)
        (strict / "probe.py").write_text(PROBE)
        slog = tmp / "strict.log"
        plan, _ = write_plan(strict, {
            "types": {"required": True, "executions": [probe(strict, slog, "t")]},
            "lints": {"required": True, "executions": [probe(strict, slog, "l")]},
            "proptests": {"required": True, "executions": [probe(strict, slog, "p")]},
            "verus": {"required": True,
                      "executions": [probe(strict, slog, "v", code=1)]},
        })
        code, out = run(strict, "tested", "--plan", str(plan))
        report = latest_report(strict)
        check("plan run: required:true widens the gating set in canonical order",
              code == 1 and "FAILED" in out
              and report["required_layers"] == ["types", "lints", "proptests",
                                                "floors", "verus"],
              f"exit={code} required={report['required_layers']}")

        # A skipped plan layer is still a visible gating gap, not a pass.
        skipped = tmp / "skipped"
        shutil.copytree(MINICRATE, skipped)
        (skipped / "probe.py").write_text(PROBE)
        kdlog = tmp / "skipped.log"
        plan, _ = write_plan(skipped, {
            "types": {"required": True, "executions": [probe(skipped, kdlog, "t")]},
            "lints": {"required": True, "executions": [probe(skipped, kdlog, "l")]},
            "proptests": {"required": True,
                          "executions": [probe(skipped, kdlog, "p")]},
        })
        code, out = run(skipped, "tested", "--plan", str(plan), "--skip", "lints")
        report = latest_report(skipped)
        check("plan run: --skip on a planned layer is INCOMPLETE, exit 3",
              code == 3 and "INCOMPLETE" in out
              and report["layers"]["lints"]["status"] == "skipped",
              f"exit={code}")
        check("plan run: a skipped planned layer runs no invocation",
              [json.loads(line)["label"] for line in kdlog.read_text().splitlines()]
              == ["t", "p"], kdlog.read_text())

        # Legacy: a plan file on disk is inert unless --plan names it.
        legacy = tmp / "legacy"
        shutil.copytree(MINICRATE, legacy)
        write_plan(legacy, {"types": {"required": True, "executions": [
            {"argv": ["false"], "cwd": ".", "timeout_seconds": 5}]}})
        code, out = run(legacy, "tested")
        report = latest_report(legacy)
        check("legacy: plan file on disk is inert without --plan",
              code == 0 and "VERIFIED[tested]" in out and "plan" not in report
              and report["layers"]["types"]["detail"]["command"]
              == ["cargo", "check", "--quiet"], f"exit={code}")
        check("legacy: required layers unchanged without a plan",
              report["required_layers"] == ["types", "lints", "proptests", "floors"],
              str(report["required_layers"]))


def test_runner() -> None:
    print("headless runner (floors as a required layer under `tested`)")
    with tempfile.TemporaryDirectory(prefix="r28-run-") as td:
        tmp = Path(td)

        below = tmp / "below"
        shutil.copytree(FIX / "below", below)
        code, out = run(below, "tested")
        st, subs = floors_status(below)
        check("below floors: run FAILED, exit 1", code == 1 and "FAILED" in out,
              f"exit={code}")
        check("below floors: floors layer failed on property bar + fuzz surface",
              st == "failed" and subs.get("property_bar") == "failed"
              and subs.get("fuzz_surfaces") == "failed", f"{st} {subs}")

        compliant = tmp / "compliant"
        shutil.copytree(FIX / "compliant", compliant)
        code, out = run(compliant, "tested")
        st, _ = floors_status(compliant)
        check("compliant floors: run VERIFIED[tested], exit 0",
              code == 0 and "VERIFIED[tested]" in out, f"exit={code}")
        check("compliant floors: floors layer passed", st == "passed", st)

        featurefail = tmp / "featurefail"
        shutil.copytree(FIX / "featurefail", featurefail)
        code, out = run(featurefail, "tested")
        st, subs = floors_status(featurefail)
        check("featurefail floors: feature-matrix combo fails -> run FAILED, exit 1",
              code == 1 and "FAILED" in out, f"exit={code}")
        check("featurefail floors: floors failed on the feature-matrix sub-check",
              st == "failed" and subs.get("feature_matrix") == "failed",
              f"{st} {subs}")

        # Absent floors.json: the R20 minicrate under documented defaults.
        defaults = tmp / "defaults"
        shutil.copytree(MINICRATE, defaults)
        check("defaults: minicrate carries no floors.json",
              not (defaults / ".fv" / "floors.json").exists())
        code, out = run(defaults, "tested")
        st, subs = floors_status(defaults)
        check("defaults: absent floors.json -> VERIFIED[tested], exit 0",
              code == 0 and "VERIFIED[tested]" in out, f"exit={code}")
        check("defaults: floors passed (property bar met, matrix/fuzz not_applicable)",
              st == "passed" and subs.get("property_bar") == "passed"
              and subs.get("feature_matrix") == "not_applicable"
              and subs.get("fuzz_surfaces") == "not_applicable", f"{st} {subs}")

        # An unavailable fuzz run makes the fuzz-time floor unmeasurable, not a pass.
        # Use the explicit skip control so this fixture is independent of whether
        # cargo-fuzz happens to be installed on the host running the suite.
        fuzzun = tmp / "fuzzunmeasured"
        shutil.copytree(FIX / "fuzzunmeasured", fuzzun)
        code, out = run(fuzzun, "tested", "--skip", "fuzz")
        st, subs = floors_status(fuzzun)
        check("fuzzunmeasured: unavailable fuzz run -> INCOMPLETE, exit 3",
              code == 3 and "INCOMPLETE" in out, f"exit={code}")
        check("fuzzunmeasured: floors skipped on the unmeasurable fuzz surface",
              st == "skipped" and subs.get("fuzz_surfaces") == "skipped",
              f"{st} {subs}")


def test_custom_plan_layers() -> None:
    print("custom plan layers (ids the pyramid has no built-in default for)")
    with tempfile.TemporaryDirectory(prefix="r28-custom-") as td:
        tmp = Path(td)

        def fixture(name: str) -> tuple[Path, Path]:
            crate = tmp / name
            shutil.copytree(MINICRATE, crate)
            (crate / "probe.py").write_text(PROBE)
            return crate, tmp / f"{name}.log"

        def records(log: Path) -> list[dict]:
            if not log.is_file():
                return []
            return [json.loads(line) for line in log.read_text().splitlines()]

        def labels(log: Path) -> list[str]:
            return [r["label"] for r in records(log)]

        def known(crate: Path, log: Path, types_code: int = 0) -> dict:
            return {
                "types": {"required": True,
                          "executions": [probe(crate, log, "types",
                                               code=types_code)]},
                "lints": {"required": True,
                          "executions": [probe(crate, log, "lints")]},
                "proptests": {"required": True,
                              "executions": [probe(crate, log, "proptests")]},
            }

        # Exact execution + ordering + report shape. Declared custom-first and
        # quint-before-mutation on purpose: execution order is known layers in
        # pyramid order, then custom layers lexically.
        crate, log = fixture("custom")
        plan, document = write_plan(crate, {
            "quint": {"required": True, "executions": [
                probe(crate, log, "quint-a",
                      env={"FV_PLAN_DECLARED": "quint-value"},
                      tool="quint-verify"),
                probe(crate, log, "quint-b", cwd="src")]},
            "mutation": {"required": False,
                         "executions": [probe(crate, log, "mutation", code=2)]},
            **known(crate, log),
        })
        code, out = run(crate, "tested", "--plan", str(plan))
        report = latest_report(crate)
        recs = records(log)
        check("custom run: known layers run first, then custom layers lexically",
              [r["label"] for r in recs] == ["types", "lints", "proptests",
                                             "mutation", "quint-a", "quint-b"],
              str([r["label"] for r in recs]))
        declared = document["layers"]["quint"]["executions"]
        first = next(r for r in recs if r["label"] == "quint-a")
        second = next(r for r in recs if r["label"] == "quint-b")
        check("custom run: custom child receives exactly the declared argv",
              first["argv"] == declared[0]["argv"][1:], str(first["argv"]))
        check("custom run: declared env reaches the custom child, merged over "
              "the ambient environment",
              first["declared"] == "quint-value"
              and first["inherited_path"] is True, str(first))
        check("custom run: custom invocation honours its declared cwd",
              second["cwd"] == str((crate / "src").resolve()), second["cwd"])
        check("custom run: declared env does not leak into the sibling "
              "custom invocation",
              second["declared"] is None, str(second["declared"]))
        quint = report["layers"]["quint"]
        executions = quint["detail"]["executions"]
        check("custom run: custom layer uses the known plan report shape",
              quint["status"] == "passed"
              and quint["detail"]["plan"] is True
              and quint["detail"]["required"] is True
              and [e["command"] for e in executions]
              == [e["argv"] for e in declared]
              and executions[0]["env"] == {"FV_PLAN_DECLARED": "quint-value"}
              and executions[0]["evidence_tool"] == "quint-verify"
              and executions[0]["timeout_seconds"] == 120
              and executions[1]["cwd"] == "src"
              and quint["detail"]["durations"].keys() == {"quint-verify"},
              str(quint))
        check("custom run: report carries the custom layers in the plan "
              "provenance",
              list(report["plan"]["layers"]) == ["types", "lints", "proptests",
                                                 "mutation", "quint"],
              str(list(report["plan"]["layers"])))
        check("custom run: required:true custom layer joins required_layers "
              "after every known layer",
              report["required_layers"] == ["types", "lints", "proptests",
                                            "floors", "quint"],
              str(report["required_layers"]))
        check("custom run: required:false custom layer runs but never gates",
              code == 0 and "VERIFIED[tested]" in out
              and report["layers"]["mutation"]["status"] == "failed"
              and "mutation" not in report["required_layers"],
              f"exit={code} required={report['required_layers']}")

        # A required custom layer is a real G2 gate, and every invocation in it
        # runs (one evidence cohort) even after one fails.
        crate, log = fixture("customfail")
        plan, _ = write_plan(crate, {
            **known(crate, log),
            "quint": {"required": True, "executions": [
                probe(crate, log, "quint-a", tool="quint-typecheck"),
                probe(crate, log, "quint-b", code=1, tool="quint-verify")]},
            "mutation": {"required": False,
                         "executions": [probe(crate, log, "mutation")]},
        })
        code, out = run(crate, "tested", "--plan", str(plan))
        report = latest_report(crate)
        codes = [e["returncode"]
                 for e in report["layers"]["quint"]["detail"]["executions"]]
        check("custom run: failing required custom layer gates FAILED, exit 1",
              code == 1 and "FAILED" in out
              and report["layers"]["quint"]["status"] == "failed"
              and "quint" in report["required_layers"],
              f"exit={code} required={report['required_layers']}")
        check("custom run: every invocation of a custom layer runs; any "
              "non-zero fails the layer",
              codes == [0, 1]
              and labels(log) == ["types", "lints", "proptests", "mutation",
                                  "quint-a", "quint-b"],
              f"{codes} {labels(log)}")

        # --skip on a required custom layer is a visible gating gap.
        crate, log = fixture("customskip")
        plan, _ = write_plan(crate, {
            **known(crate, log),
            "quint": {"required": True,
                      "executions": [probe(crate, log, "quint-a")]},
            "mutation": {"required": False,
                         "executions": [probe(crate, log, "mutation")]},
        })
        code, out = run(crate, "tested", "--plan", str(plan), "--skip", "quint")
        report = latest_report(crate)
        check("custom run: --skip on a required custom layer is INCOMPLETE, "
              "exit 3",
              code == 3 and "INCOMPLETE" in out
              and report["layers"]["quint"]["status"] == "skipped",
              f"exit={code} {report['layers']['quint']['status']}")
        check("custom run: a skipped custom layer runs no invocation, siblings "
              "still run",
              labels(log) == ["types", "lints", "proptests", "mutation"],
              str(labels(log)))

        # A types failure invalidates everything downstream, custom layers
        # included: required and declared alike are not_run, never skipped-past.
        crate, log = fixture("customtypes")
        plan, _ = write_plan(crate, {
            **known(crate, log, types_code=1),
            "quint": {"required": True,
                      "executions": [probe(crate, log, "quint-a")]},
            "mutation": {"required": False,
                         "executions": [probe(crate, log, "mutation")]},
        })
        code, out = run(crate, "tested", "--plan", str(plan))
        report = latest_report(crate)
        check("custom run: types failure marks required and declared custom "
              "layers not_run",
              code == 1 and "FAILED" in out
              and report["layers"]["quint"]["status"] == "not_run"
              and report["layers"]["quint"]["detail"] == "types layer failed"
              and report["layers"]["mutation"]["status"] == "not_run",
              f"exit={code} "
              f"{ {k: v['status'] for k, v in report['layers'].items()} }")
        check("custom run: no custom invocation runs after a types failure",
              labels(log) == ["types"], str(labels(log)))


def test_launch_failures() -> None:
    print("unrunnable plan commands (a failed layer and a report, never a crash)")
    with tempfile.TemporaryDirectory(prefix="r28-launch-") as td:
        tmp = Path(td)

        def fixture(name: str) -> tuple[Path, Path]:
            crate = tmp / name
            shutil.copytree(MINICRATE, crate)
            (crate / "probe.py").write_text(PROBE)
            return crate, tmp / f"{name}.log"

        def known(crate: Path, log: Path) -> dict:
            return {
                "types": {"required": True,
                          "executions": [probe(crate, log, "types")]},
                "lints": {"required": True,
                          "executions": [probe(crate, log, "lints")]},
                "proptests": {"required": True,
                              "executions": [probe(crate, log, "proptests")]},
            }

        # A freshly migrated plan naming a tool this machine does not have:
        # the layer fails, the passing layers keep their results, and the run
        # reaches a verdict and a persisted report instead of a traceback.
        crate, log = fixture("missingtool")
        plan, _ = write_plan(crate, {
            **known(crate, log),
            "quint": {"required": True, "executions": [
                {"argv": ["r28-quint-not-installed", "verify", "spec/p.qnt"],
                 "cwd": ".", "timeout_seconds": 60,
                 "evidence_tool": "quint-verify"}]},
        })
        code, out = run(crate, "tested", "--plan", str(plan))
        reports = sorted((crate / ".fv" / "verify").glob("headless-*.json"))
        check("launch failure: the run reports a verdict, not a traceback",
              code == 1 and "FAILED" in out and "Traceback" not in out,
              f"exit={code} {out[-400:]}")
        check("launch failure: the report still lands", len(reports) == 1,
              str([p.name for p in reports]))
        if reports:
            report = json.loads(reports[-1].read_text())
            quint = report["layers"]["quint"]
            execution = quint["detail"]["executions"][0]
            check("launch failure: the layer is failed with a structured "
                  "execution record",
                  quint["status"] == "failed" and execution["returncode"] == -1
                  and "FileNotFoundError" in execution.get("launch_error", ""),
                  str(quint["detail"]))
            rows = quint["detail"]["launch_errors"]
            check("launch failure: launch_errors names the position, tool and "
                  "argv0",
                  len(rows) == 1
                  and {k: v for k, v in rows[0].items() if k != "error"}
                  == {"execution": 0, "evidence_tool": "quint-verify",
                      "argv0": "r28-quint-not-installed"}
                  and "FileNotFoundError" in rows[0]["error"],
                  str(quint["detail"].get("launch_errors")))
            check("launch failure: layers that ran keep their results",
                  [report["layers"][layer]["status"]
                   for layer in ("types", "lints", "proptests", "floors")]
                  == ["passed", "passed", "passed", "passed"],
                  str({k: v["status"] for k, v in report["layers"].items()}))
            check("launch failure: a required unrunnable layer gates the verdict",
                  report["verdict"] == "FAILED"
                  and "quint" in report["required_layers"],
                  f"{report['verdict']} {report['required_layers']}")

        # A non-executable file is the same class of failure, and a
        # required:false layer that cannot launch still never gates.
        if os.geteuid() != 0:  # root ignores the executable bit
            crate, log = fixture("notexecutable")
            script = crate / "not-executable.sh"
            script.write_text("#!/bin/sh\nexit 0\n")
            script.chmod(0o444)
            plan, _ = write_plan(crate, {
                **known(crate, log),
                "mutation": {"required": False, "executions": [
                    {"argv": [str(script)], "cwd": ".", "timeout_seconds": 60,
                     "evidence_tool": "mutants"}]},
            })
            code, out = run(crate, "tested", "--plan", str(plan))
            report = latest_report(crate)
            mutation = report["layers"]["mutation"]
            check("launch failure: a non-executable command fails its layer "
                  "with a permission error",
                  mutation["status"] == "failed"
                  and "PermissionError"
                  in mutation["detail"]["launch_errors"][0]["error"],
                  str(mutation["detail"].get("launch_errors")))
            check("launch failure: a required:false unrunnable layer does not "
                  "gate the verdict",
                  code == 0 and "VERIFIED[tested]" in out
                  and "mutation" not in report["required_layers"],
                  f"exit={code} required={report['required_layers']}")

        # Evidence that cannot be persisted is an infrastructure ERROR, and the
        # report itself still reaches stdout rather than vanishing.
        if os.geteuid() != 0:
            crate, log = fixture("unwritable")
            plan, _ = write_plan(crate, known(crate, log))
            verify_dir = crate / ".fv" / "verify"
            verify_dir.mkdir(parents=True)
            verify_dir.chmod(0o500)
            try:
                code, out = run(crate, "tested", "--plan", str(plan), "--json")
            finally:
                verify_dir.chmod(0o700)
            check("unpersistable report: ERROR exit 2, no traceback",
                  code == 2 and "VERDICT: ERROR" in out
                  and "cannot write the report" in out
                  and "Traceback" not in out, f"exit={code} {out[-400:]}")
            check("unpersistable report: the report still reaches stdout",
                  json.loads(out[out.index("{"):out.rindex("}") + 1])["gate"]
                  == "pyramid-headless", out[:200])
            check("unpersistable report: nothing was written",
                  not list(verify_dir.glob("headless-*.json")),
                  str(list(verify_dir.iterdir())))


def main() -> int:
    mod = load_runner()
    test_pure(mod)
    test_run_cmd(mod)
    test_plan_pure(mod)

    if shutil.which("cargo") is None:
        print("SKIP-FAIL: cargo not on PATH; live-runner half skipped",
              file=sys.stderr)
        return 2
    test_runner()
    test_plan_runner()
    test_custom_plan_layers()
    test_launch_failures()

    print()
    if FAILURES:
        print(f"R28: {len(FAILURES)} failure(s)")
        return 1
    print("R28: all assertions passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
