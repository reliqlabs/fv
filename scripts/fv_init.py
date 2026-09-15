#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6,<7"]
# ///
"""Scaffold project-local FV state for the OMP extension package."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import fv_project  # noqa: E402  canonical project-root and target resolution

PROJECT_SCRIPT_NAMES = (
    "check_ledger_references.py",
    "check_evidence_records.py",
    "fv_project.py",
)
VERIFIED_INPUTS_HEADER = (
    "# Verified-input policy for the FV evidence content snapshot.\n"
    "# Blank lines and # comments are ignored; directory prefixes end in /.\n"
    "# This file declares exclusion mode: the prefixes below are kept out of the\n"
    "# snapshot and everything else git reports is a verified input. A project that\n"
    "# wants an allowlist instead writes `mode: include` as its first non-comment\n"
    "# line and lists the paths in scope; this initializer never rewrites one.\n"
)
CONFIG_EXAMPLE = REPO / "scripts" / "dispatch.config.example.json"
PANEL_SETTINGS = REPO / "templates" / "omp-panel.json"
PACKAGE_REQUIREMENTS = (
    REPO / "agents",
    REPO / "skills",
    REPO / "tools",
    REPO / ".mcp.json",
)


def _copy_owned_file(
    source: Path,
    destination: Path,
    force: bool,
    results: list[tuple[str, Path]],
) -> None:
    existed = destination.exists()
    if existed and not force:
        results.append(("skip", destination))
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    results.append(("overwrote" if existed else "wrote", destination))


def build_dispatch_json(target_spec: str) -> str:
    config = json.loads(CONFIG_EXAMPLE.read_text())
    route = config["omp_native"]
    route["project_root"] = "."
    route["target_spec"] = target_spec
    return json.dumps(config, indent=2, ensure_ascii=False) + "\n"


def portable_target_spec(project: Path, declared: str) -> str:
    """Normalize a declared target to the repo-relative form dispatch stores.

    The candidate is resolved first so a symlinked ancestor (``/var`` on macOS)
    is not mistaken for an escape from the resolved project root.
    """
    candidate = Path(declared).expanduser()
    if not candidate.is_absolute():
        candidate = project / candidate
    return fv_project.relative_target_spec(project, candidate.resolve())


def install_verified_inputs(
    project: Path,
    force: bool,
    results: list[tuple[str, Path]],
) -> list[str]:
    """Seed or complete the project's verified-input policy.

    A project with no policy gets the default exclusion-mode file. An existing
    exclusion-mode policy keeps its own entries and gains any frozen default it
    dropped, which is the historical behaviour. An existing *include*-mode policy
    is left byte for byte, ``--force`` included: its entries name the paths in
    scope, so appending FV's exclusion prefixes would declare generated output to
    be verified input, and replacing it with exclusion defaults would silently
    widen what every later record claims to cover. The frozen prefixes apply
    structurally in both modes, so nothing is lost by leaving the file alone.
    """
    destination = project / ".fv" / "verified-inputs.txt"
    defaults = fv_project.InputPolicy(fv_project.MODE_EXCLUDE, fv_project.DEFAULT_EXCLUSIONS)
    default_text = fv_project.render_policy(defaults, VERIFIED_INPUTS_HEADER)
    if not destination.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(default_text)
        results.append(("wrote", destination))
        return []
    try:
        # Decoded from bytes with no newline translation, as fv_project does: a lone
        # CR that the policy grammar rejects must not be rewritten into an LF here.
        text = destination.read_bytes().decode("utf-8")
        policy = fv_project.parse_policy(text)
    except (OSError, UnicodeDecodeError, fv_project.ProjectError) as error:
        if not force:
            return [f"{destination}: {error}; use --force to replace it"]
        destination.write_text(default_text)
        results.append(("overwrote", destination))
        return []
    if policy.mode == fv_project.MODE_INCLUDE:
        results.append(("skip", destination))
        return []
    if force:
        destination.write_text(default_text)
        results.append(("overwrote", destination))
        return []
    missing = [prefix for prefix in defaults.prefixes if prefix not in policy.prefixes]
    if not missing:
        results.append(("skip", destination))
        return []
    # The frozen prefixes apply whether or not they are listed; restoring them
    # keeps the file an honest record. Project-specific entries stay untouched.
    if text and not text.endswith("\n"):
        text += "\n"
    destination.write_text(text + "".join(f"{prefix}\n" for prefix in missing))
    results.append(("updated", destination))
    return []


def install_dispatch_config(
    project: Path,
    target_spec: str,
    explicit_target: bool,
    force: bool,
    results: list[tuple[str, Path]],
) -> list[str]:
    destination = project / ".fv" / "dispatch.json"
    canonical = json.loads(build_dispatch_json(target_spec))
    existed = destination.exists()
    if not existed or force:
        destination.write_text(json.dumps(canonical, indent=2, ensure_ascii=False) + "\n")
        results.append(("overwrote" if existed else "wrote", destination))
        return []
    try:
        current = json.loads(destination.read_text())
    except (OSError, json.JSONDecodeError) as error:
        return [f"{destination}: invalid JSON ({error}); use --force to replace it"]
    if set(current) != {"omp_native"} or not isinstance(current.get("omp_native"), dict):
        return [f"{destination}: legacy dispatch schema; use --force to replace it"]
    current_route = current["omp_native"]
    canonical_route = canonical["omp_native"]
    changed = False
    for key, value in canonical_route.items():
        if key in ("project_root", "target_spec"):
            continue
        if current_route.get(key) != value:
            current_route[key] = value
            changed = True
    # Scaffolded state must survive a clone or a move: the canonical root is
    # whatever project the caller names, so stored roots are always ".".
    if current_route.get("project_root") != ".":
        current_route["project_root"] = "."
        changed = True
    declared = current_route.get("target_spec")
    if explicit_target or not isinstance(declared, str) or not declared.strip():
        spec = target_spec
    else:
        try:
            spec = portable_target_spec(project, declared)
        except fv_project.ProjectError as error:
            return [
                f"{destination}: target_spec {declared!r} is not inside {project} ({error}); "
                "pass --target-spec or --force to replace it"
            ]
    if current_route.get("target_spec") != spec:
        current_route["target_spec"] = spec
        changed = True
    if changed:
        destination.write_text(json.dumps(current, indent=2, ensure_ascii=False) + "\n")
        results.append(("updated", destination))
    else:
        results.append(("skip", destination))
    return []


ISOLATION_MODES = {
    "none", "auto", "apfs", "btrfs", "zfs", "reflink",
    "overlayfs", "projfs", "block-clone", "rcopy",
}


def _block_end(lines: list[str], start: int) -> int:
    for index in range(start + 1, len(lines)):
        stripped = lines[index].strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not lines[index][0].isspace() and not stripped.startswith("-"):
            return index
    return len(lines)


def _write_lines(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n")


def install_extension_config(
    project: Path,
    force: bool,
    results: list[tuple[str, Path]],
) -> list[str]:
    destination = project / ".omp" / "config.yml"
    destination.parent.mkdir(parents=True, exist_ok=True)
    extension = str(REPO)
    if not destination.exists():
        _write_lines(destination, ["extensions:", f"  - {json.dumps(extension)}"])
        results.append(("wrote", destination))
        return []
    try:
        data = yaml.safe_load(destination.read_text()) or {}
    except (OSError, yaml.YAMLError) as error:
        return [f"{destination}: invalid YAML ({error})"]
    if not isinstance(data, dict):
        return [f"{destination}: configuration root must be a mapping"]
    extensions = data.get("extensions")
    if extensions is not None and (
        not isinstance(extensions, list)
        or not all(isinstance(item, str) for item in extensions)
    ):
        return [f"{destination}: extensions must be a string array"]
    if isinstance(extensions, list) and extension in extensions:
        results.append(("skip", destination))
        return []
    lines = destination.read_text().splitlines()
    start = next((i for i, line in enumerate(lines) if line.startswith("extensions:")), None)
    if start is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines.extend(["extensions:", f"  - {json.dumps(extension)}"])
    else:
        tail = lines[start].partition(":")[2].strip()
        if tail:
            updated = [*(extensions or []), extension]
            lines[start] = "extensions: " + json.dumps(updated)
        else:
            end = _block_end(lines, start)
            item_indents = {
                line[:len(line) - len(line.lstrip())]
                for line in lines[start + 1:end]
                if line.lstrip().startswith("-")
            }
            if len(item_indents) > 1:
                return [f"{destination}: inconsistent extensions indentation"]
            indent = next(iter(item_indents), "  ")
            lines.insert(end, f"{indent}- {json.dumps(extension)}")
    _write_lines(destination, lines)
    results.append(("updated", destination))
    return []


def install_isolation_config(
    project: Path,
    results: list[tuple[str, Path]],
) -> list[str]:
    destination = project / ".omp" / "config.yml"
    try:
        data = yaml.safe_load(destination.read_text()) or {}
    except (OSError, yaml.YAMLError) as error:
        return [f"{destination}: invalid YAML ({error})"]
    if not isinstance(data, dict):
        return [f"{destination}: configuration root must be a mapping"]
    task = data.get("task")
    if task is not None and not isinstance(task, dict):
        return [f"{destination}: task must be a mapping"]
    isolation = task.get("isolation") if isinstance(task, dict) else None
    if isolation is not None and not isinstance(isolation, dict):
        return [f"{destination}: task.isolation must be a mapping"]
    mode = isolation.get("mode") if isinstance(isolation, dict) else None
    if mode is not None and mode not in ISOLATION_MODES:
        return [f"{destination}: unsupported task.isolation.mode {mode!r}"]
    if mode in ISOLATION_MODES - {"none"}:
        return []

    lines = destination.read_text().splitlines()
    task_start = next((i for i, line in enumerate(lines) if line.startswith("task:")), None)
    if task is not None and task_start is None:
        return [f"{destination}: unsupported noncanonical task syntax"]
    if task_start is not None and lines[task_start].strip() != "task:":
        return [f"{destination}: unsupported inline task syntax"]
    if task_start is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines.extend(["task:", "  isolation:", "    mode: auto"])
    else:
        task_end = _block_end(lines, task_start)
        isolation_start = next(
            (i for i in range(task_start + 1, task_end)
             if lines[i].startswith("  isolation:")),
            None,
        )
        if isolation is not None and isolation_start is None:
            return [f"{destination}: unsupported noncanonical task.isolation syntax"]
        if isolation_start is not None and lines[isolation_start].strip() != "isolation:":
            return [f"{destination}: unsupported inline task.isolation syntax"]
        if isolation_start is None:
            child_indents = [
                len(line) - len(line.lstrip())
                for line in lines[task_start + 1:task_end]
                if line.strip() and not line.lstrip().startswith("#")
            ]
            if child_indents and min(child_indents) != 2:
                return [f"{destination}: unsupported task indentation"]
            lines[task_start + 1:task_start + 1] = ["  isolation:", "    mode: auto"]
        else:
            isolation_end = next(
                (i for i in range(isolation_start + 1, task_end)
                 if lines[i].strip() and len(lines[i]) - len(lines[i].lstrip()) <= 2),
                task_end,
            )
            mode_line = next(
                (i for i in range(isolation_start + 1, isolation_end)
                 if lines[i].startswith("    mode:")),
                None,
            )
            if mode is not None and mode_line is None:
                return [f"{destination}: unsupported task.isolation.mode indentation"]
            if mode_line is None:
                lines.insert(isolation_start + 1, "    mode: auto")
            else:
                lines[mode_line] = "    mode: auto"
    _write_lines(destination, lines)
    results.append(("updated", destination))
    return []

def install_panel_config(
    project: Path,
    results: list[tuple[str, Path]],
) -> list[str]:
    """Install FV's default role into OMP settings without owning OMP's file."""
    destination = project / ".omp" / "config.yml"
    expected = json.loads(PANEL_SETTINGS.read_text())
    try:
        data = yaml.safe_load(destination.read_text()) or {}
    except (OSError, yaml.YAMLError) as error:
        return [f"{destination}: invalid YAML ({error})"]
    if not isinstance(data, dict):
        return [f"{destination}: configuration root must be a mapping"]
    panel = data.get("panel")
    if panel is None:
        lines = destination.read_text().splitlines()
        if lines and lines[-1].strip():
            lines.append("")
        rendered = yaml.safe_dump({"panel": expected}, sort_keys=False).rstrip().splitlines()
        lines.extend(rendered)
        _write_lines(destination, lines)
        results.append(("updated", destination))
        return []
    if not isinstance(panel, dict) or not isinstance(panel.get("roles"), dict):
        return [f"{destination}: panel.roles must be a mapping"]
    role = panel["roles"].get("fv-canonical")
    if not isinstance(role, dict):
        return [f"{destination}: configure panel.roles.fv-canonical in OMP settings"]
    members = role.get("members")
    floor = role.get("minFamilies")
    if role.get("strategy") != "independent" or not isinstance(members, list) or len(members) < 2:
        return [f"{destination}: panel.roles.fv-canonical must be independent with at least two members"]
    if not isinstance(floor, int) or floor < 1 or floor > len(members):
        return [f"{destination}: panel.roles.fv-canonical has an invalid minFamilies floor"]
    # OMP owns an existing role. Candidate and thinking customization is valid;
    # the FV tool and doctor use the effective role rather than repinning it to
    # this initializer seed.
    results.append(("skip", destination))
    return []


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project", type=Path, help="project root to scaffold")
    parser.add_argument(
        "--target-spec",
        type=Path,
        default=None,
        help="spec or intent path inside the project, absolute or project-relative "
             "(default: .fv/intent.md, or the target already declared in .fv/dispatch.json)",
    )
    parser.add_argument("--force", action="store_true", help="replace FV-owned project state")
    args = parser.parse_args()

    required = [
        CONFIG_EXAMPLE,
        PANEL_SETTINGS,
        *PACKAGE_REQUIREMENTS,
        *(REPO / "scripts" / name for name in PROJECT_SCRIPT_NAMES),
    ]
    missing = [path for path in required if not path.exists()]
    if missing:
        print(f"FATAL: canonical files missing: {missing}")
        return 1

    project = args.project.resolve()
    project.mkdir(parents=True, exist_ok=True)
    try:
        project = fv_project.resolve_project_root(project)
        target_spec = (
            fv_project.DEFAULT_TARGET_SPEC
            if args.target_spec is None
            else portable_target_spec(project, str(args.target_spec))
        )
    except fv_project.ProjectError as error:
        print(f"FATAL: {error}")
        return 1
    results: list[tuple[str, Path]] = []
    errors: list[str] = []

    # Every generated-output directory the structural exclusions cover, so a lifecycle
    # report has a home that cannot stale the evidence the report describes.
    for subdirectory in ("attacks", "verify", "evidence", "scripts", "panels",
                         "changes", "code-adversarial"):
        (project / ".fv" / subdirectory).mkdir(parents=True, exist_ok=True)
    for name in PROJECT_SCRIPT_NAMES:
        source = REPO / "scripts" / name
        _copy_owned_file(source, project / ".fv" / "scripts" / name, args.force, results)
    errors.extend(install_dispatch_config(
        project, target_spec, args.target_spec is not None, args.force, results,
    ))
    errors.extend(install_verified_inputs(project, args.force, results))
    errors.extend(install_extension_config(project, args.force, results))
    errors.extend(install_isolation_config(project, results))
    if not errors:
        errors.extend(install_panel_config(project, results))

    marker = project / ".fv" / "harness"
    if not marker.exists() or args.force:
        existed = marker.exists()
        marker.write_text("omp\n")
        results.append(("overwrote" if existed else "wrote", marker))
    elif marker.read_text() != "omp\n":
        errors.append(f"{marker}: non-OMP scaffold marker; use --force to replace it")
    else:
        results.append(("skip", marker))

    for action, path in results:
        print(f"  [{action:>9}] {path.relative_to(project)}")
    for error in errors:
        print(f"  [    ERROR] {error}")
    try:
        effective_spec = fv_project.declared_target_spec(project) or fv_project.DEFAULT_TARGET_SPEC
    except fv_project.ProjectError:
        effective_spec = target_spec
    print(f"\nScaffolded {project} for the FV OMP extension at {REPO}")
    print(f'  dispatch project_root is "." and target_spec is {effective_spec}')
    if not (project / effective_spec).is_file():
        print(f"  target_spec {effective_spec} does not exist yet; create it before running FV gates")
    print("\nNext steps:")
    print(f"  1. Export FV_ROOT={REPO} and optional proof-tool binary variables.")
    print("  2. Start OMP in the project and run `/reload-plugins` in any session already open.")
    print("  3. Invoke workflows with `/skill:fv-*`.")
    print(f"  4. Run uv run --script {REPO / 'scripts' / 'fv_doctor.py'} --project {project}.")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
