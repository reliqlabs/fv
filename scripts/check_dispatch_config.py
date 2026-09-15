#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Validate the OMP-native FV dispatch config."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
ROUTE_HASH_RE = re.compile(r"^sha256:[0-9a-f]{16}$")
ROUTE_GRADES = {"attested", "unattested", "degraded", "errored", "contaminated", "not-run"}
ROUTE_FIELDS = (
    "project_root",
    "target_spec",
    "profile",
    "agent",
    "thinking_policy",
    "calibration",
    "voices",
    "route_hash",
)
VOICE_FIELDS = (
    "id",
    "model",
    "family",
    "thinking_level",
    "dispatch_selector",
    "calibration",
    "route_grade",
)


def valid_slug(value: object) -> bool:
    return isinstance(value, str) and bool(SLUG_RE.fullmatch(value)) and ".." not in value


def route_hash(route: dict) -> str:
    normalized = {
        "agent": route["agent"],
        "thinking_policy": route["thinking_policy"],
        "voices": sorted(
            (
                {
                    "id": voice["id"],
                    "model": voice["model"],
                    "thinking_level": voice.get("thinking_level"),
                }
                for voice in route["voices"]
            ),
            key=lambda voice: voice["id"],
        ),
    }
    blob = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(blob.encode()).hexdigest()[:16]


def project_base(config_path: Path) -> Path:
    """Directory a relative ``project_root`` is measured from.

    A project's config lives at ``<project>/.fv/dispatch.json``, so
    ``project_root: "."`` names the project root, not the ``.fv`` directory
    holding the config. Configs kept anywhere else resolve against their own
    directory, which keeps ad-hoc and example configs checkable in place.
    """
    parent = config_path.parent
    return parent.parent if parent.name == ".fv" else parent


def path_errors(route: dict, root: Path) -> list[str]:
    """Resolve and check the declared project root and target spec.

    ``root`` is the project-root base from :func:`project_base`. The target is
    measured from the *resolved* project root, so a moved project with a
    repo-relative config keeps validating. Legacy absolute values are honoured
    as written, but a target outside the project root is an escape.
    """
    project_value = route["project_root"]
    target_value = route["target_spec"]
    if not isinstance(project_value, str) or not isinstance(target_value, str):
        return []
    project = Path(project_value)
    if not project.is_absolute():
        project = root / project
    project = project.resolve()
    errors: list[str] = []
    if not project.is_dir():
        errors.append(f"project_root does not exist: {project_value}")
    target = Path(target_value)
    if not target.is_absolute():
        target = project / target
    target = target.resolve()
    if not target.is_file():
        errors.append(f"target_spec does not exist: {target_value}")
    elif not target.is_relative_to(project):
        errors.append(f"target_spec escapes project_root: {target_value}")
    return errors


def validate(config: dict, *, require_paths: bool = False, base: Path | None = None) -> list[str]:
    errors: list[str] = []
    if set(config) != {"omp_native"}:
        errors.append("top level must contain only 'omp_native'")
    route = config.get("omp_native")
    if not isinstance(route, dict):
        return [*errors, "missing omp_native object"]
    for field in ROUTE_FIELDS:
        if field not in route:
            errors.append(f"missing omp_native.{field}")
    if errors:
        return errors
    for field in ROUTE_FIELDS:
        if field == "voices":
            continue
        if not isinstance(route[field], str) or not route[field]:
            errors.append(f"omp_native.{field} must be a non-empty string")
    if not ROUTE_HASH_RE.fullmatch(route.get("route_hash", "")):
        errors.append("omp_native.route_hash is invalid")

    voices = route["voices"]
    if not isinstance(voices, list) or not voices:
        errors.append("omp_native.voices must be a non-empty list")
        voices = []
    ids: list[str] = []
    for index, voice in enumerate(voices):
        if not isinstance(voice, dict):
            errors.append(f"omp_native.voices[{index}] must be an object")
            continue
        missing = [field for field in VOICE_FIELDS if field not in voice]
        if missing:
            errors.append(f"omp_native.voices[{index}] missing {missing}")
            continue
        if not valid_slug(voice["id"]):
            errors.append(f"voice id {voice['id']!r} is not a valid slug")
        ids.append(voice["id"])
        for field in ("model", "family", "dispatch_selector", "calibration"):
            if not isinstance(voice[field], str) or not voice[field]:
                errors.append(f"voice {voice['id']!r} field {field} must be non-empty")
        level = voice["thinking_level"]
        if level is not None and (not isinstance(level, str) or not level):
            errors.append(f"voice {voice['id']!r} thinking_level must be string or null")
        expected_selector = f"{voice['model']}:{level}" if level else voice["model"]
        if voice["dispatch_selector"] != expected_selector:
            errors.append(f"voice {voice['id']!r} dispatch_selector mismatch")
        if voice["route_grade"] not in ROUTE_GRADES:
            errors.append(f"voice {voice['id']!r} route_grade is invalid")
    duplicates = sorted({voice_id for voice_id in ids if ids.count(voice_id) > 1})
    if duplicates:
        errors.append(f"duplicate voice id(s): {duplicates}")
    if voices and all(field in route for field in ("agent", "thinking_policy", "route_hash")):
        expected = route_hash(route)
        if route["route_hash"] != expected:
            errors.append(
                f"OMP route hash drift: stored={route['route_hash']} recomputed={expected}"
            )
    if require_paths:
        errors.extend(path_errors(route, base or Path.cwd()))
    return errors


def check_file(path: Path, require_paths: bool) -> list[str]:
    try:
        config = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        return [f"cannot parse {path}: {error}"]
    return validate(config, require_paths=require_paths, base=project_base(path))


def selftest() -> int:
    example = REPO / "scripts" / "dispatch.config.example.json"
    base = json.loads(example.read_text())
    checks = []
    checks.append(("example config validates", not validate(base)))
    missing = json.loads(example.read_text())
    del missing["omp_native"]["target_spec"]
    checks.append(("missing target_spec rejected", any("target_spec" in item for item in validate(missing))))
    duplicate = json.loads(example.read_text())
    duplicate["omp_native"]["voices"].append(dict(duplicate["omp_native"]["voices"][0]))
    checks.append(("duplicate voice id rejected", any("duplicate voice id" in item for item in validate(duplicate))))
    with tempfile.TemporaryDirectory(prefix="dispatch-paths-") as td:
        alpha = Path(td) / "alpha"
        (alpha / ".fv").mkdir(parents=True)
        (alpha / ".fv" / "intent.md").write_text("# intent\n")
        config_path = alpha / ".fv" / "dispatch.json"
        config_path.write_text(json.dumps(base))
        checks.append((
            "repo-relative project config passes --require-paths",
            not check_file(config_path, True),
        ))
        beta = Path(td) / "beta"
        alpha.rename(beta)
        checks.append((
            "the same config still passes after the project moves",
            not check_file(beta / ".fv" / "dispatch.json", True),
        ))
    ok = True
    for label, passed in checks:
        print(f"  [{'ok' if passed else 'FAIL'}] {label}")
        ok &= passed
    print("\nDISPATCH-CONFIG SELFTEST " + ("PASSED" if ok else "FAILED"))
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("config", nargs="?", type=Path)
    parser.add_argument("--require-paths", action="store_true")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        return selftest()
    if not args.config:
        parser.error("name a dispatch config or pass --selftest")
    errors = check_file(args.config, args.require_paths)
    for error in errors:
        print(f"FAIL: {error}")
    if errors:
        print(f"\nDISPATCH-CONFIG INVALID: {len(errors)} problem(s)")
        return 1
    print(f"DISPATCH-CONFIG VALID: {args.config}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
