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
from pathlib import Path
import yaml

REPO = Path(__file__).resolve().parents[1]
PROJECT_SCRIPT_NAMES = ("check_ledger_references.py", "check_evidence_records.py")
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


def build_dispatch_json(project: Path, target_spec: Path) -> str:
    config = json.loads(CONFIG_EXAMPLE.read_text())
    route = config["omp_native"]
    route["project_root"] = str(project)
    route["target_spec"] = str(target_spec)
    return json.dumps(config, indent=2, ensure_ascii=False) + "\n"


def install_dispatch_config(
    project: Path,
    target_spec: Path,
    force: bool,
    results: list[tuple[str, Path]],
) -> list[str]:
    destination = project / ".fv" / "dispatch.json"
    canonical = json.loads(build_dispatch_json(project, target_spec))
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
    if current_route.get("project_root") != str(project):
        current_route["project_root"] = str(project)
        changed = True
    if current_route.get("target_spec") != str(target_spec):
        current_route["target_spec"] = str(target_spec)
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
    missing = []
    drifted = []
    for role_id, role in expected["roles"].items():
        current = panel["roles"].get(role_id)
        if current is None:
            missing.append(role_id)
        elif current != role:
            drifted.append(role_id)
    if missing or drifted:
        return [
            f"{destination}: configure FV roles in OMP panel settings; "
            f"missing={missing}, drifted={drifted}"
        ]
    results.append(("skip", destination))
    return []


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project", type=Path, help="project root to scaffold")
    parser.add_argument(
        "--target-spec",
        type=Path,
        default=None,
        help="spec or intent path (default: <project>/.fv/intent.md)",
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
    target_spec = args.target_spec.resolve() if args.target_spec else project / ".fv" / "intent.md"
    results: list[tuple[str, Path]] = []
    errors: list[str] = []

    for subdirectory in ("attacks", "verify", "evidence", "scripts", "panels"):
        (project / ".fv" / subdirectory).mkdir(parents=True, exist_ok=True)
    for name in PROJECT_SCRIPT_NAMES:
        source = REPO / "scripts" / name
        _copy_owned_file(source, project / ".fv" / "scripts" / name, args.force, results)
    errors.extend(install_dispatch_config(project, target_spec, args.force, results))
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
    print(f"\nScaffolded {project} for the FV OMP extension at {REPO}")
    if not args.target_spec:
        print(f"  target_spec defaults to {target_spec}")
    print("\nNext steps:")
    print(f"  1. Export FV_ROOT={REPO} and optional proof-tool binary variables.")
    print("  2. Start OMP in the project and run `/reload-plugins` in any session already open.")
    print("  3. Invoke workflows with `/skill:fv-*`.")
    print(f"  4. Run uv run --script {REPO / 'scripts' / 'fv_doctor.py'} --project {project}.")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
