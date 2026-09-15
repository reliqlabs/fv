#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
pyramid_run — headless runner for the deterministic pyramid layers (E4, G2).

Runs the layers that need no agent (types, lints, property tests, fuzz,
Kani, Verus) so the pyramid can gate CI. The agent remains responsible for
failure classification and for the Aeneas/Lean layers (extraction and the
axiom gate run in the agent flow; see fv-verify SKILL Layer 7-8 and
scripts/lean_axiom_gate.py).

ASSURANCE PROFILES (named, G2-scoped)
    tested   types + lints + proptests + floors (+ fuzz when harnesses exist)
    bounded  tested + kani            (bounded proofs; bounds are per-harness)
    proved   bounded + verus + lean   (lean is NOT runnable headless: under
             this profile the headless runner always reports INCOMPLETE and
             names the layers the agent flow must supply)

ENGINEERING BASELINE FLOORS (C8, required under every profile)
    The `floors` layer reads <crate>/.fv/floors.json when present and
    falls back to DEFAULT_FLOORS otherwise. Three mechanical sub-checks:
      feature_matrix  cargo check over each declared --features/--no-default-
                      features/--release combo (with --workspace when the
                      crate root is a [workspace]); any combo that fails to
                      compile fails the layer. No declared matrix -> the
                      default combo is the `types` layer (not_applicable),
                      except a workspace still gets `cargo check --workspace`.
      property_bar    every src/*.rs file that exposes public API (pub fn /
                      struct / enum / trait) must carry at least
                      min_per_module in-file test functions (#[test], or only
                      proptest!/quickcheck when require_property_tests). Files
                      below the bar are listed by name and fail the layer.
      fuzz_surfaces   each parsing/deserialization surface named in floors.json
                      must have a fuzz_targets/<name>.rs target (missing ->
                      failed); the recorded fuzz duration must meet min_seconds
                      (cargo-fuzz absent -> unmeasurable -> skipped/INCOMPLETE).
    The layer's aggregate follows G2: any failed sub-check -> failed; else any
    unmeasurable (skipped) sub-check -> skipped; else passed. Named higher
    tiers (sanitizers, mutation testing, unsafe/FFI review, non-Rust per-
    surface tiers) are documentation contracts in the verify SKILL, not yet
    mechanical here.

VERDICT AGGREGATION (the G2 truth table, exact)
    any required layer failed                      -> FAILED      (exit 1)
    else any required layer skipped / not run /
         not_applicable                            -> INCOMPLETE  (exit 3)
    else all required layers passed                -> VERIFIED[<profile>] (exit 0)
    runner/tool infrastructure error               -> ERROR       (exit 2)

A skipped required layer is a gating gap, not a footnote: there is no
"passed with gaps". Fuzz is required only when fuzz harnesses exist;
kani/verus with zero harnesses/annotations under a profile that requires
them is INCOMPLETE (no bounded evidence is not evidence).

VERIFICATION PLANS (--plan, fv-verification-plan/v1)
    `--plan PATH` reads a declarative plan (conventionally
    <crate>/.fv/verification-plan.json) whose `layers` map names the layers
    whose commands the project declares instead of inheriting the built-in
    defaults:
        {"schema": "fv-verification-plan/v1",
         "layers": {"types": {"required": true, "executions": [
            {"argv": ["cargo", "check", "--quiet"], "cwd": ".",
             "timeout_seconds": 600, "env": {"RUSTFLAGS": "-Dwarnings"},
             "evidence_tool": "cargo-check"}]}}}
    Contract, fail-closed — a malformed plan is ERROR (exit 2), never a
    silently-legacy run:
      * argv is a non-empty array of non-empty strings. There are no shell
        strings: argv is executed directly, with no shell, no word splitting
        and no glob expansion.
      * cwd is repo-relative and must resolve to an existing directory inside
        the crate root. Absolute paths, `..` segments and symlink escapes are
        rejected.
      * timeout_seconds is a positive integer (per invocation).
      * env, when present, maps string to string. It is merged over the
        runner's own environment for that child process only; the runner never
        mutates its own environment, and declared names never leak into
        sibling invocations.
      * evidence_tool, when present, names the tool the invocation witnesses.
        On the `fuzz` layer it also names the fuzz surface whose measured
        duration feeds the C8 fuzz-time floor.
      * `floors` is not plannable: it is computed from .fv/floors.json, and a
        declared command could not enforce the C8 baseline. It is the only
        reserved layer id.
      * any other id the pyramid does not know names a CUSTOM layer, and must
        match PLAN_CUSTOM_ID ([A-Za-z0-9][A-Za-z0-9._:+/-]*). A custom layer
        has no built-in default — it exists only because the plan declares it
        (`quint`, `mutation`, `sanitizers`, ...) — and its executions get
        exactly the same argv/cwd/timeout/env validation, execution and report
        shape as a known layer's.
    Known plan-declared layers run in the canonical pyramid order
    (LAYER_ORDER), then custom layers run in lexical order, both independent
    of their order in the file (see plan_layer_order). Every invocation in a
    layer runs (a layer is one evidence cohort); the layer fails when any
    invocation exits non-zero or times out. `required: true` adds a layer to
    the gating set — a custom layer included, which is how a tool outside the
    Rust pyramid becomes a G2 gate; `required: false` is non-gating but never
    un-requires a layer the profile already requires: a plan can only tighten
    the verdict. A types failure invalidates everything downstream, so every
    required or declared layer that has not run — custom layers included — is
    recorded not_run.
    Layers the plan does not name keep every built-in default, and without
    --plan the runner is byte-for-byte the legacy runner.

USAGE
    pyramid_run.py --crate <path> --profile tested|bounded|proved
        [--skip <layer>]... [--fuzz-seconds 30] [--plan <path>] [--json]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path

PROFILES: dict[str, list[str]] = {
    "tested":  ["types", "lints", "proptests", "floors"],
    "bounded": ["types", "lints", "proptests", "floors", "kani"],
    "proved":  ["types", "lints", "proptests", "floors", "kani", "verus", "lean"],
}

# Canonical layer order: the pyramid runs cheapest-first and a types failure
# invalidates everything below it. Plan-declared known layers execute in this
# order; plan-declared custom layers execute after them, lexically.
LAYER_ORDER: tuple[str, ...] = (
    "types", "lints", "proptests", "fuzz", "floors", "kani", "verus", "lean",
)

PLAN_SCHEMA = "fv-verification-plan/v1"
PLAN_RELATIVE = ".fv/verification-plan.json"

# `floors` is computed from .fv/floors.json (C8), so it is reserved: it can be
# neither declared as a known layer nor reused as a custom layer id.
PLAN_RESERVED_LAYERS: tuple[str, ...] = ("floors",)

# The known (built-in) plannable layers.
PLAN_LAYERS: tuple[str, ...] = tuple(
    name for name in LAYER_ORDER if name not in PLAN_RESERVED_LAYERS)

# Any other layer id is a custom layer: a project-declared tool the pyramid
# has no default for. Ids stay filesystem-, JSON- and report-key-safe.
PLAN_CUSTOM_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:+/-]*")

_PLAN_TOP_KEYS = ("schema", "layers")
_PLAN_LAYER_KEYS = ("required", "executions")
_PLAN_EXEC_KEYS = ("argv", "cwd", "timeout_seconds", "env", "evidence_tool")

TERMINAL_OK = "passed"

FLOORS_SCHEMA = "fv-floors/v2"

# Documented defaults applied when <crate>/.fv/floors.json is absent or
# omits a section. Sections present in the file layer over these.
DEFAULT_FLOORS: dict = {
    "schema": FLOORS_SCHEMA,
    "features": {"matrix": []},
    "property_tests": {"min_per_module": 1, "require_property_tests": False},
    "fuzz": {"surfaces": [], "min_seconds": 30},
}

_WORKSPACE_RE = re.compile(r"^\s*\[workspace\]", re.MULTILINE)
_PUB_ITEM_RE = re.compile(r"\bpub\s+(?:fn|struct|enum|trait)\b")
_TEST_ATTR_RE = re.compile(r"#\[\s*test\s*\]")
_PROPTEST_RE = re.compile(r"\bproptest\s*!|#\[\s*proptest\b")
_QUICKCHECK_RE = re.compile(r"\bquickcheck\s*!|#\[\s*quickcheck\b")


def load_floors(crate: Path) -> dict:
    """Read <crate>/.fv/floors.json, layering present sections over
    DEFAULT_FLOORS. Absent file -> documented defaults (a pure function)."""
    cfg = {k: (dict(v) if isinstance(v, dict) else v)
           for k, v in DEFAULT_FLOORS.items()}
    path = crate / ".fv" / "floors.json"
    if path.is_file():
        user = json.loads(path.read_text())
        if "schema" in user and user["schema"] != FLOORS_SCHEMA:
            raise ValueError(
                f"{path}: unsupported schema {user['schema']!r}; expected {FLOORS_SCHEMA!r}"
            )
        for section in ("features", "property_tests", "fuzz"):
            if isinstance(user.get(section), dict):
                cfg[section] = {**cfg[section], **user[section]}
    return cfg


def is_workspace(crate: Path) -> bool:
    """True when the crate root's Cargo.toml declares a [workspace] table."""
    toml = crate / "Cargo.toml"
    return toml.is_file() and bool(_WORKSPACE_RE.search(toml.read_text()))


def count_tests(src: str, property_only: bool = False) -> int:
    """Count test functions in a source file: proptest!/quickcheck always,
    bare #[test] only when property_only is False."""
    n = len(_PROPTEST_RE.findall(src)) + len(_QUICKCHECK_RE.findall(src))
    if not property_only:
        n += len(_TEST_ATTR_RE.findall(src))
    return n


def has_public_api(src: str) -> bool:
    """True when a file declares public API (pub fn/struct/enum/trait).
    pub(crate)/pub(super) are not public surface and do not match."""
    return bool(_PUB_ITEM_RE.search(src))


def modules_below_bar(crate: Path, cfg: dict) -> tuple[str, dict]:
    """Property-test bar: every src/*.rs file exposing public API needs at
    least min_per_module in-file test functions. Per-file is a documented
    proxy for per-public-module — idiomatic Rust unit tests live in an inline
    #[cfg(test)] mod, and attributing crate-wide tests to a module is not
    mechanically decidable. Returns (status, detail)."""
    pt = cfg.get("property_tests", {})
    minimum = int(pt.get("min_per_module", 1))
    property_only = bool(pt.get("require_property_tests", False))
    src_dir = crate / "src"
    if not src_dir.is_dir():
        return "not_applicable", {"reason": "no src/ directory"}
    public_modules: list[str] = []
    below: list[str] = []
    for f in sorted(src_dir.rglob("*.rs")):
        text = f.read_text(errors="replace")
        if not has_public_api(text):
            continue
        rel = str(f.relative_to(crate))
        public_modules.append(rel)
        if count_tests(text, property_only) < minimum:
            below.append(rel)
    detail = {"min_per_module": minimum, "require_property_tests": property_only,
              "public_modules": public_modules, "below_bar": below}
    if not public_modules:
        return "not_applicable", {"reason": "no public modules under src/", **detail}
    return ("failed" if below else TERMINAL_OK), detail


def fuzz_surface_check(crate: Path, surfaces: list[str], min_seconds: int,
                       fuzz_layer: dict | None) -> tuple[str, dict]:
    """Fuzz-time floor. Each named surface needs a fuzz_targets/<name>.rs
    target (missing -> failed, a structural fact independent of cargo-fuzz).
    The duration floor is read from the runner's fuzz layer; when cargo-fuzz
    is absent the fuzz layer did not run to completion, so the duration is
    unmeasurable -> skipped (INCOMPLETE), never a silent pass."""
    if not surfaces:
        return "not_applicable", {"surfaces": []}
    targets_dir = crate / "fuzz" / "fuzz_targets"
    missing = [s for s in surfaces if not (targets_dir / f"{s}.rs").is_file()]
    if missing:
        return "failed", {"surfaces": surfaces, "missing_targets": missing}
    fstatus = (fuzz_layer or {}).get("status")
    if fstatus != TERMINAL_OK:
        return "skipped", {"surfaces": surfaces, "min_seconds": min_seconds,
                           "reason": f"fuzz duration unmeasurable "
                                     f"(fuzz layer status={fstatus})"}
    durations = ((fuzz_layer or {}).get("detail") or {}).get("durations", {})
    short = [s for s in surfaces if durations.get(s, 0) < min_seconds]
    if short:
        return "failed", {"surfaces": surfaces, "min_seconds": min_seconds,
                          "below_floor": short, "durations": durations}
    return TERMINAL_OK, {"surfaces": surfaces, "min_seconds": min_seconds,
                         "durations": durations}


def floors_layer(crate: Path, cfg: dict, workspace: bool,
                 fuzz_layer: dict | None) -> tuple[str, dict]:
    """Run the three floor sub-checks and aggregate per G2 (failed dominates;
    else unmeasurable/skipped; else passed). Returns (status, detail)."""
    subchecks: dict[str, dict] = {}

    matrix = cfg.get("features", {}).get("matrix") or []
    if not matrix:
        if workspace:
            r = run_cmd(["cargo", "check", "--workspace", "--quiet"], crate)
            subchecks["feature_matrix"] = {
                "status": TERMINAL_OK if r["returncode"] == 0 else "failed",
                "combos": [{"name": "workspace-default", "result": r}]}
        else:
            subchecks["feature_matrix"] = {
                "status": "not_applicable",
                "reason": "no matrix declared; default combo is the types layer"}
    else:
        combos = []
        fm_status = TERMINAL_OK
        for combo in matrix:
            cmd = ["cargo", "check", "--quiet"]
            if workspace:
                cmd.append("--workspace")
            if combo.get("no_default_features"):
                cmd.append("--no-default-features")
            feats = combo.get("features") or []
            if feats:
                cmd += ["--features", ",".join(feats)]
            if combo.get("release"):
                cmd.append("--release")
            r = run_cmd(cmd, crate)
            if r["returncode"] != 0:
                fm_status = "failed"
            combos.append({"name": combo.get("name") or ",".join(feats) or "default",
                           "release": bool(combo.get("release")), "result": r})
        subchecks["feature_matrix"] = {"status": fm_status, "combos": combos}

    pb_status, pb_detail = modules_below_bar(crate, cfg)
    subchecks["property_bar"] = {"status": pb_status, **pb_detail}

    fuzz_cfg = cfg.get("fuzz", {})
    fz_status, fz_detail = fuzz_surface_check(
        crate, fuzz_cfg.get("surfaces") or [],
        int(fuzz_cfg.get("min_seconds", 30)), fuzz_layer)
    subchecks["fuzz_surfaces"] = {"status": fz_status, **fz_detail}

    statuses = [v["status"] for v in subchecks.values()]
    if "failed" in statuses:
        agg = "failed"
    elif "skipped" in statuses:
        agg = "skipped"
    else:
        agg = TERMINAL_OK
    return agg, {"floors_schema": cfg.get("schema"), "workspace": workspace,
                 "subchecks": subchecks}


def aggregate_verdict(profile: str, required: list[str],
                      statuses: dict[str, str]) -> tuple[str, int]:
    """Pure G2 aggregation. `statuses` maps layer -> passed|failed|skipped|
    not_applicable|not_run. Only `required` layers gate the verdict."""
    gating = {layer: statuses.get(layer, "not_run") for layer in required}
    if any(s == "failed" for s in gating.values()):
        return "FAILED", 1
    if any(s != TERMINAL_OK for s in gating.values()):
        return "INCOMPLETE", 3
    return f"VERIFIED[{profile}]", 0


def run_cmd(cmd: list[str], cwd: Path, timeout: int = 1800,
            env: dict[str, str] | None = None) -> dict:
    """Run argv directly — never a shell string. `env` is merged over the
    runner's own environment for this child only; os.environ is untouched."""
    child_env = {**os.environ, **env} if env else None
    t0 = time.monotonic()
    try:
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                              timeout=timeout, env=child_env)
        return {"command": cmd, "returncode": proc.returncode,
                "duration_s": round(time.monotonic() - t0, 1),
                "stdout_preview": proc.stdout[-500:],
                "stderr_preview": proc.stderr[-500:]}
    except subprocess.TimeoutExpired:
        return {"command": cmd, "returncode": -1, "timeout": True,
                "duration_s": round(time.monotonic() - t0, 1)}


class PlanError(ValueError):
    """Any rejection of a verification plan's schema, layers, or executions."""


def plan_layer_order(names: Iterable[str]) -> list[str]:
    """Execution/report order for a set of layer ids: the known pyramid layers
    in LAYER_ORDER (cheapest-first, types gating everything below it), then the
    custom layers lexically. Lexical is the only total order available for ids
    the pyramid knows nothing about, and it keeps runs and reports
    deterministic regardless of the plan file's key order."""
    unique = set(names)
    return [*(name for name in LAYER_ORDER if name in unique),
            *sorted(name for name in unique if name not in LAYER_ORDER)]


def _plan_cwd(root: Path, raw: object, where: str) -> str:
    """Validate a declared repo-relative cwd; return its normalized form.

    A plan may only name directories inside the crate root: absolute paths,
    `..` segments, symlink escapes and non-directories are all rejected.
    `root` must already be resolved."""
    if not isinstance(raw, str) or not raw.strip():
        raise PlanError(f"{where}: cwd must be a non-empty repo-relative string, "
                        f"got {raw!r}")
    candidate = Path(raw)
    if candidate.is_absolute():
        raise PlanError(f"{where}: cwd must be repo-relative, got absolute {raw!r}")
    if ".." in candidate.parts:
        raise PlanError(f"{where}: cwd escapes the crate root: {raw!r}")
    resolved = (root / candidate).resolve()
    if resolved != root and root not in resolved.parents:
        raise PlanError(f"{where}: cwd escapes the crate root: {raw!r} -> {resolved}")
    if not resolved.is_dir():
        raise PlanError(f"{where}: cwd is not a directory: {raw!r}")
    return resolved.relative_to(root).as_posix() or "."


def _plan_env(raw: object, where: str) -> dict[str, str]:
    """Validate an optional env mapping of string to string."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise PlanError(f"{where}: env must be an object mapping string to string, "
                        f"got {type(raw).__name__}")
    env: dict[str, str] = {}
    for name, value in raw.items():
        if not isinstance(name, str) or not name or "=" in name or "\0" in name:
            raise PlanError(f"{where}: env name must be a non-empty string without "
                            f"'=' or NUL, got {name!r}")
        if not isinstance(value, str) or "\0" in value:
            raise PlanError(f"{where}: env[{name!r}] must be a string without NUL, "
                            f"got {value!r}")
        env[name] = value
    return env


def _plan_execution(root: Path, raw: object, where: str) -> dict:
    """Validate one declared invocation. No shell strings, no ambient escapes."""
    if not isinstance(raw, dict):
        raise PlanError(f"{where}: execution must be an object")
    unknown = sorted(set(raw) - set(_PLAN_EXEC_KEYS))
    if unknown:
        raise PlanError(f"{where}: unknown key(s) {unknown}; "
                        f"allowed {list(_PLAN_EXEC_KEYS)}")
    argv = raw.get("argv")
    if not isinstance(argv, list) or not argv:
        raise PlanError(f"{where}: argv must be a non-empty array of strings "
                        f"(a shell string is not a command), got {argv!r}")
    for index, word in enumerate(argv):
        if not isinstance(word, str) or not word or "\0" in word:
            raise PlanError(f"{where}: argv[{index}] must be a non-empty string "
                            f"without NUL, got {word!r}")
    timeout = raw.get("timeout_seconds")
    if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout <= 0:
        raise PlanError(f"{where}: timeout_seconds must be a positive integer, "
                        f"got {timeout!r}")
    tool = raw.get("evidence_tool")
    if tool is not None and (not isinstance(tool, str) or not tool.strip()):
        raise PlanError(f"{where}: evidence_tool must be a non-empty string when "
                        f"present, got {tool!r}")
    return {"argv": list(argv),
            "cwd": _plan_cwd(root, raw.get("cwd"), where),
            "timeout_seconds": timeout,
            "env": _plan_env(raw.get("env"), where),
            "evidence_tool": tool}


def parse_plan(document: object, root: Path, source: str = "<plan>") -> dict:
    """Validate a fv-verification-plan/v1 document against the crate `root`.

    Returns {"schema", "source", "layers"} where `layers` is ordered by
    plan_layer_order — known layers in LAYER_ORDER, then custom layers
    lexically — regardless of the document's key order. Pure apart from the
    directory-existence checks on each declared cwd."""
    root = Path(root).resolve()
    if not isinstance(document, dict):
        raise PlanError(f"{source}: plan must be a JSON object")
    unknown = sorted(set(document) - set(_PLAN_TOP_KEYS))
    if unknown:
        raise PlanError(f"{source}: unknown top-level key(s) {unknown}; "
                        f"allowed {list(_PLAN_TOP_KEYS)}")
    schema = document.get("schema", PLAN_SCHEMA)
    if schema != PLAN_SCHEMA:
        raise PlanError(f"{source}: unsupported schema {schema!r}; "
                        f"expected {PLAN_SCHEMA!r}")
    declared = document.get("layers")
    if not isinstance(declared, dict) or not declared:
        raise PlanError(f"{source}: layers must be a non-empty object")
    for name in declared:
        if name in PLAN_LAYERS:
            continue
        if name in PLAN_RESERVED_LAYERS:
            raise PlanError(
                f"{source}: layer {name!r} is not plannable (it is computed "
                f"from .fv/floors.json, not declared); known layers "
                f"{list(PLAN_LAYERS)}")
        if not isinstance(name, str) or not PLAN_CUSTOM_ID.fullmatch(name):
            raise PlanError(
                f"{source}: custom layer id {name!r} is malformed; expected "
                f"{PLAN_CUSTOM_ID.pattern} or a known layer "
                f"{list(PLAN_LAYERS)}")
    layers: dict[str, dict] = {}
    for name in plan_layer_order(declared):
        spec = declared[name]
        where = f"{source}: layers.{name}"
        if not isinstance(spec, dict):
            raise PlanError(f"{where}: layer must be an object")
        unknown = sorted(set(spec) - set(_PLAN_LAYER_KEYS))
        if unknown:
            raise PlanError(f"{where}: unknown key(s) {unknown}; "
                            f"allowed {list(_PLAN_LAYER_KEYS)}")
        required = spec.get("required")
        if not isinstance(required, bool):
            raise PlanError(f"{where}: required must be a boolean, got {required!r}")
        executions = spec.get("executions")
        if not isinstance(executions, list) or not executions:
            raise PlanError(f"{where}: executions must be a non-empty array")
        layers[name] = {
            "required": required,
            "executions": [
                _plan_execution(root, execution, f"{where}.executions[{index}]")
                for index, execution in enumerate(executions)
            ],
        }
    return {"schema": PLAN_SCHEMA, "source": source, "layers": layers}


def load_plan(path: str | Path, root: Path) -> dict:
    """Read and validate a plan file; every rejection is a PlanError."""
    path = Path(path)
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as error:
        raise PlanError(f"cannot read plan {path}: {error}") from error
    except json.JSONDecodeError as error:
        raise PlanError(f"{path}: malformed JSON: {error}") from error
    return parse_plan(document, root, source=str(path))


def run_plan_execution(execution: dict, root: Path) -> dict:
    """Execute one declared invocation with its declared cwd, timeout and env."""
    result = run_cmd(execution["argv"], root / execution["cwd"],
                     timeout=execution["timeout_seconds"],
                     env=execution["env"] or None)
    record = {**result, "cwd": execution["cwd"],
              "timeout_seconds": execution["timeout_seconds"],
              "env": dict(sorted(execution["env"].items()))}
    if execution["evidence_tool"]:
        record["evidence_tool"] = execution["evidence_tool"]
    return record


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--crate", required=True, type=Path)
    ap.add_argument("--profile", required=True, choices=sorted(PROFILES))
    ap.add_argument("--skip", action="append", default=[],
                    help="skip a layer (a skipped REQUIRED layer gates the "
                         "run to INCOMPLETE — visible, not forgiven)")
    ap.add_argument("--fuzz-seconds", type=int, default=30)
    ap.add_argument("--plan", type=Path, default=None,
                    help=f"{PLAN_SCHEMA} document (conventionally "
                         f"{PLAN_RELATIVE}) declaring per-layer argv/cwd/"
                         "timeout_seconds/env, for known pyramid layers and "
                         "for custom layers the plan names itself; layers it "
                         "does not name keep their built-in defaults")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    crate = args.crate.resolve()
    if not (crate / "Cargo.toml").is_file():
        print(f"ERROR: no Cargo.toml at {crate}", file=sys.stderr)
        print("\nVERDICT: ERROR", file=sys.stderr)
        return 2

    plan_layers: dict[str, dict] = {}
    plan_report: dict | None = None
    if args.plan is not None:
        try:
            plan = load_plan(args.plan, crate)
        except PlanError as error:
            print(f"ERROR: {error}", file=sys.stderr)
            print("\nVERDICT: ERROR", file=sys.stderr)
            return 2
        plan_layers = plan["layers"]
        plan_report = {"schema": plan["schema"], "source": plan["source"],
                       "layers": plan_layers}
    if shutil.which("cargo") is None:
        print("ERROR: cargo not on PATH", file=sys.stderr)
        print("\nVERDICT: ERROR", file=sys.stderr)
        return 2

    required = list(PROFILES[args.profile])
    has_fuzz = (crate / "fuzz").is_dir()
    if has_fuzz and "fuzz" not in required:
        required.insert(3, "fuzz")  # fuzz is required exactly when harnesses exist
    # A plan may only widen the gating set: `required: true` adds a layer —
    # custom layers included — and `required: false` never un-requires a layer
    # the profile already requires.
    planned = [name for name, spec in plan_layers.items() if spec["required"]]
    if planned:
        required = plan_layer_order(set(required) | set(planned))

    layers: dict[str, dict] = {}
    statuses: dict[str, str] = {}

    def record(layer: str, status: str, detail: dict | str = "") -> None:
        statuses[layer] = status
        layers[layer] = {"status": status, "detail": detail}
        print(f"  [{status:>14}] {layer}", file=sys.stderr)

    def plan_layer(layer: str) -> bool:
        """Run a plan-declared layer; True when the plan owns this layer.

        Every declared invocation runs (the layer is one evidence cohort) and
        the layer fails when any of them exits non-zero or times out."""
        spec = plan_layers.get(layer)
        if spec is None:
            return False
        if layer in args.skip:
            record(layer, "skipped", "skipped by flag")
            return True
        results: list[dict] = []
        durations: dict[str, float] = {}
        status = TERMINAL_OK
        for execution in spec["executions"]:
            result = run_plan_execution(execution, crate)
            results.append(result)
            if result["returncode"] != 0:
                status = "failed"
            if execution["evidence_tool"]:
                durations[execution["evidence_tool"]] = result.get("duration_s", 0)
        record(layer, status, {"plan": True, "required": spec["required"],
                               "executions": results, "durations": durations})
        return True

    def cargo_layer(layer: str, cmd: list[str]) -> None:
        if plan_layer(layer):
            return
        if layer in args.skip:
            record(layer, "skipped", "skipped by flag")
            return
        r = run_cmd(cmd, crate)
        record(layer, TERMINAL_OK if r["returncode"] == 0 else "failed", r)

    cargo_layer("types", ["cargo", "check", "--quiet"])
    if statuses.get("types") == "failed":
        # Compilation failure invalidates everything downstream.
        for layer in plan_layer_order([*required, *plan_layers]):
            if layer not in statuses:
                record(layer, "not_run", "types layer failed")
    else:
        cargo_layer("lints", ["cargo", "clippy", "--quiet", "--", "-D", "warnings"])
        cargo_layer("proptests", ["cargo", "test", "--quiet"])

        if plan_layer("fuzz"):
            pass
        elif "fuzz" in required or has_fuzz:
            if "fuzz" in args.skip:
                record("fuzz", "skipped", "skipped by flag")
            elif not has_fuzz:
                record("fuzz", "not_applicable", "no fuzz/ harnesses")
            elif shutil.which("cargo-fuzz") is None:
                record("fuzz", "skipped", "cargo-fuzz not installed")
            else:
                lst = run_cmd(["cargo", "fuzz", "list"], crate)
                targets = [t for t in lst.get("stdout_preview", "").split() if t]
                results = [run_cmd(["cargo", "fuzz", "run", t, "--",
                                    f"-max_total_time={args.fuzz_seconds}"],
                                   crate, timeout=args.fuzz_seconds + 300)
                           for t in targets]
                ok = targets and all(r["returncode"] == 0 for r in results)
                durations = {t: r.get("duration_s", 0)
                             for t, r in zip(targets, results)}
                record("fuzz", TERMINAL_OK if ok else "failed",
                       {"targets": targets, "durations": durations,
                        "results": results})

        if "floors" in required:
            if "floors" in args.skip:
                record("floors", "skipped", "skipped by flag")
            else:
                try:
                    cfg = load_floors(crate)
                except (OSError, ValueError, json.JSONDecodeError) as error:
                    record("floors", "failed", {"error": str(error)})
                else:
                    status, detail = floors_layer(
                        crate, cfg, is_workspace(crate), layers.get("fuzz"))
                    record("floors", status, detail)

        if plan_layer("kani"):
            pass
        elif "kani" in required:
            if "kani" in args.skip:
                record("kani", "skipped", "skipped by flag")
            elif shutil.which("cargo-kani") is None:
                record("kani", "skipped", "cargo-kani not installed")
            else:
                src = subprocess.run(["grep", "-r", "-l", "kani::proof", "src"],
                                     cwd=crate, capture_output=True, text=True)
                if src.returncode != 0:
                    record("kani", "not_applicable", "no #[kani::proof] harnesses")
                else:
                    r = run_cmd(["cargo", "kani"], crate)
                    record("kani", TERMINAL_OK if r["returncode"] == 0 else "failed", r)

        if plan_layer("verus"):
            pass
        elif "verus" in required:
            if "verus" in args.skip:
                record("verus", "skipped", "skipped by flag")
            elif shutil.which("cargo-verus") is None and shutil.which("verus") is None:
                record("verus", "skipped", "verus not installed")
            else:
                r = run_cmd(["cargo", "verus", "verify"], crate)
                record("verus", TERMINAL_OK if r["returncode"] == 0 else "failed", r)

        if plan_layer("lean"):
            pass
        elif "lean" in required:
            record("lean", "not_run",
                   "Aeneas extraction + lean_axiom_gate.py are agent-flow layers; "
                   "the headless runner cannot supply them")

        # Custom layers have no built-in default — the plan is their only
        # definition — so they run exactly as declared, after every known
        # pyramid layer, in lexical order (plan_layers is already ordered).
        for layer in plan_layers:
            if layer not in LAYER_ORDER:
                plan_layer(layer)

    verdict, code = aggregate_verdict(args.profile, required, statuses)

    report = {
        "gate": "pyramid-headless",
        "crate": str(crate),
        "profile": args.profile,
        "required_layers": required,
        **({"plan": plan_report} if plan_report is not None else {}),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "layers": layers,
        "floors": layers.get("floors", {}).get("detail", {}),
        "verdict": verdict,
    }
    out_dir = crate / ".fv" / "verify"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"headless-{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H%M%SZ')}.json"
    out_path.write_text(json.dumps(report, indent=2) + "\n")

    if args.json:
        print(json.dumps(report, indent=2))
    print(f"\nreport: {out_path}", file=sys.stderr)
    print(f"VERDICT: {verdict}", file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
