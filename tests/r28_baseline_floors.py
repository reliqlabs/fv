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

Requires cargo. Exit 0 pass, 1 fail, 2 toolchain unavailable.
"""
from __future__ import annotations

import importlib.util
import json
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

        # The shipped example is a valid plan, ordered canonically on load.
        example = mod.load_plan(PLAN_EXAMPLE, REPO)
        check("example plan: validates against the shipped schema",
              example["schema"] == PLAN_SCHEMA
              and list(example["layers"]) == ["types", "lints", "proptests",
                                              "fuzz", "kani"],
              str(list(example["layers"])))
        check("example plan: multi-invocation layer keeps its declared order",
              [e["argv"][1] for e in example["layers"]["lints"]["executions"]]
              == ["clippy", "fmt"],
              str(example["layers"]["lints"]["executions"]))

        # Deterministic layer order, independent of the document's key order.
        plan = mod.parse_plan({"layers": {"lean": {"required": False,
                                                   "executions": [
                                                       {"argv": ["true"], "cwd": ".",
                                                        "timeout_seconds": 5}]},
                                          **one()}}, root)
        check("plan: layers ordered by the canonical pyramid order",
              list(plan["layers"]) == ["types", "lean"], str(list(plan["layers"])))
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
        rejects("plan: unknown layer name rejected",
                {"layers": {"miri": {"required": True, "executions": [
                    {"argv": ["true"], "cwd": ".", "timeout_seconds": 5}]}}}, root,
                "'miri' is not plannable")
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


def main() -> int:
    mod = load_runner()
    test_pure(mod)
    test_plan_pure(mod)

    if shutil.which("cargo") is None:
        print("SKIP-FAIL: cargo not on PATH; live-runner half skipped",
              file=sys.stderr)
        return 2
    test_runner()
    test_plan_runner()

    print()
    if FAILURES:
        print(f"R28: {len(FAILURES)} failure(s)")
        return 1
    print("R28: all assertions passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
