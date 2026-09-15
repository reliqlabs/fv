#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Canonical FV project resolution: dispatch target and verified-input snapshot.

Two contracts live here so producers, gates, and scaffolding agree byte for byte:

* the canonical verification target is ``.fv/dispatch.json`` ->
  ``omp_native.target_spec``, defaulting to ``.fv/intent.md``, always resolved
  under the project root;
* the verified-input snapshot is a deterministic content hash over git's
  tracked-and-unignored candidate set minus the declared exclusion prefixes.

Import-safe: no module-level side effects. Gate and producer copies installed
under ``<project>/.fv/scripts`` import this file from their own directory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

DISPATCH_RELATIVE = ".fv/dispatch.json"
VERIFIED_INPUTS_RELATIVE = ".fv/verified-inputs.txt"
DEFAULT_TARGET_SPEC = ".fv/intent.md"
DEFAULT_EXCLUSIONS = (".fv/evidence/", ".fv/verify/", ".fv/panels/", ".colosseum/")
SNAPSHOT_PREFIX = "sha256:"
_READ_CHUNK = 1 << 20


class ProjectError(ValueError):
    """Any rejection of a project layout, dispatch target, or snapshot input."""


def _contained(root: Path, candidate: Path) -> bool:
    return candidate == root or root in candidate.parents


def resolve_project_root(path: str | Path) -> Path:
    """Resolve a user-supplied project root to an existing absolute directory."""
    root = Path(path).expanduser().resolve()
    if not root.is_dir():
        raise ProjectError(f"project root is not a directory: {path}")
    return root


def dispatch_route(project_root: str | Path) -> dict:
    """Return ``omp_native`` from ``.fv/dispatch.json``; ``{}`` when absent."""
    root = resolve_project_root(project_root)
    dispatch = root / DISPATCH_RELATIVE
    if not dispatch.exists():
        return {}
    try:
        config = json.loads(dispatch.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ProjectError(f"cannot read {DISPATCH_RELATIVE}: {error}") from error
    if not isinstance(config, dict):
        raise ProjectError(f"{DISPATCH_RELATIVE} is not a JSON object")
    route = config.get("omp_native", {})
    if not isinstance(route, dict):
        raise ProjectError(f"{DISPATCH_RELATIVE} omp_native is not a JSON object")
    return route


def declared_target_spec(project_root: str | Path) -> str | None:
    """Return the declared ``omp_native.target_spec``, or ``None`` when unset."""
    declared = dispatch_route(project_root).get("target_spec")
    if isinstance(declared, str) and declared.strip():
        return declared
    if declared is not None and not isinstance(declared, str):
        raise ProjectError(f"{DISPATCH_RELATIVE} omp_native.target_spec is not a string")
    return None


def repo_relative(project_root: str | Path, path: str | Path) -> str:
    """Repo-relative POSIX form of ``path``; pure path math, no existence check."""
    root = resolve_project_root(project_root)
    candidate = Path(path).expanduser()
    resolved = _normalize(candidate if candidate.is_absolute() else root / candidate)
    if not _contained(root, resolved):
        raise ProjectError(f"path escapes project root: {path}")
    return resolved.relative_to(root).as_posix()


def relative_target_spec(project_root: str | Path, target: str | Path) -> str:
    """Repo-relative ``target_spec`` value to store in ``.fv/dispatch.json``."""
    return repo_relative(project_root, target)


def _normalize(path: Path) -> Path:
    """Lexically normalize ``..``/``.`` without touching the filesystem."""
    parts: list[str] = []
    for part in path.parts:
        if part == ".":
            continue
        if part == ".." and parts and parts[-1] not in ("..", path.anchor):
            parts.pop()
            continue
        parts.append(part)
    return Path(*parts) if parts else path


def resolve_target(project_root: str | Path, target_spec: str | Path | None = None) -> Path:
    """Resolve the canonical verification target for ``project_root``.

    ``target_spec`` defaults to the declared ``omp_native.target_spec`` and then
    to ``.fv/intent.md``. Relative specs resolve under the project root; an
    absolute spec is accepted only when it lands inside the project root. The
    result is an existing regular file; anything else is a ``ProjectError``.
    """
    root = resolve_project_root(project_root)
    spec = target_spec if target_spec is not None else declared_target_spec(root)
    if spec is None:
        spec = DEFAULT_TARGET_SPEC
    if not str(spec).strip():
        raise ProjectError("target_spec is empty")
    raw = Path(str(spec)).expanduser()
    candidate = raw if raw.is_absolute() else root / raw
    resolved = Path(_normalize(candidate))
    if not _contained(root, resolved):
        raise ProjectError(f"target_spec escapes project root: {spec}")
    if resolved.is_symlink():
        raise ProjectError(f"target_spec is a symlink: {spec}")
    real = resolved.resolve()
    if not _contained(root.resolve(), real):
        raise ProjectError(f"target_spec escapes project root: {spec}")
    if resolved.is_dir():
        raise ProjectError(f"target_spec is a directory: {spec}")
    if not resolved.is_file():
        raise ProjectError(f"target_spec does not exist: {spec}")
    return real


def target_hash(project_root: str | Path, target: str | Path | None = None) -> str:
    """SHA-256 hex of the canonical target's bytes."""
    resolved = resolve_target(project_root, target)
    try:
        return _file_digest(resolved)
    except OSError as error:
        raise ProjectError(f"cannot read target: {error}") from error


# Gate B and the producer both bind evidence to the target under this name.
intent_hash = target_hash


def parse_exclusions(text: str) -> list[str]:
    """Parse a verified-input exclusion list into normalized prefixes."""
    prefixes: list[str] = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("./"):
            line = line[2:]
        if not line or line in (".", "/"):
            raise ProjectError(f"{VERIFIED_INPUTS_RELATIVE}:{lineno}: entry excludes the whole project")
        if Path(line).is_absolute():
            raise ProjectError(f"{VERIFIED_INPUTS_RELATIVE}:{lineno}: absolute entry {line!r}")
        if ".." in Path(line).parts:
            raise ProjectError(f"{VERIFIED_INPUTS_RELATIVE}:{lineno}: entry escapes project root: {line!r}")
        if line not in prefixes:
            prefixes.append(line)
    return prefixes


def load_exclusions(project_root: str | Path) -> list[str]:
    """Declared exclusions unioned with the always-applied defaults.

    The defaults keep evidence, verification, and panel outputs out of the
    snapshot so writing evidence can never invalidate the evidence being
    written; a project list only adds prefixes.
    """
    root = resolve_project_root(project_root)
    prefixes = list(DEFAULT_EXCLUSIONS)
    listing = root / VERIFIED_INPUTS_RELATIVE
    if listing.is_file():
        try:
            text = listing.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            raise ProjectError(f"cannot read {VERIFIED_INPUTS_RELATIVE}: {error}") from error
        for prefix in parse_exclusions(text):
            if prefix not in prefixes:
                prefixes.append(prefix)
    return prefixes


def is_excluded(relative: str, exclusions: list[str] | tuple[str, ...]) -> bool:
    """True when ``relative`` falls under an exclusion prefix."""
    for prefix in exclusions:
        if prefix.endswith("/"):
            if relative.startswith(prefix):
                return True
        elif relative == prefix or relative.startswith(prefix + "/"):
            return True
    return False


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_READ_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def candidate_paths(project_root: str | Path) -> list[str]:
    """Git's tracked-and-unignored candidate set, repo-relative POSIX, deduped."""
    root = resolve_project_root(project_root)
    listing = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if listing.returncode != 0:
        detail = listing.stderr.decode(errors="replace").strip() or f"exit {listing.returncode}"
        raise ProjectError(f"cannot enumerate verified inputs: git ls-files failed: {detail}")
    try:
        names = listing.stdout.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ProjectError(f"git reported a non-UTF-8 path: {error}") from error
    return list(dict.fromkeys(name for name in names.split("\0") if name))


def snapshot_entries(
    project_root: str | Path,
    exclusions: list[str] | tuple[str, ...] | None = None,
) -> list[tuple[str, str]]:
    """Sorted ``(repo-relative POSIX path, content sha256)`` verified inputs."""
    root = resolve_project_root(project_root)
    prefixes = list(load_exclusions(root) if exclusions is None else exclusions)
    selected = [name for name in candidate_paths(root) if not is_excluded(name, prefixes)]
    entries: list[tuple[str, str]] = []
    for relative in sorted(selected, key=lambda name: name.encode("utf-8")):
        path = root / relative
        if path.is_symlink():
            raise ProjectError(f"verified input is a symlink: {relative}")
        resolved = Path(_normalize(path))
        if not _contained(root, resolved):
            raise ProjectError(f"verified input escapes project root: {relative}")
        if path.is_dir():
            # Submodule gitlink: its content is verified by its own repository.
            continue
        if not path.exists():
            # Tracked but deleted in the worktree; the absence is the change.
            continue
        try:
            entries.append((relative, _file_digest(path)))
        except OSError as error:
            raise ProjectError(f"cannot hash verified input {relative}: {error}") from error
    return entries


def content_snapshot(
    project_root: str | Path,
    exclusions: list[str] | tuple[str, ...] | None = None,
) -> str:
    """Deterministic ``sha256:<hex>`` snapshot of the project's verified inputs."""
    digest = hashlib.sha256()
    for relative, content_hash in snapshot_entries(project_root, exclusions):
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(content_hash.encode("ascii"))
        digest.update(b"\n")
    return SNAPSHOT_PREFIX + digest.hexdigest()


def is_content_snapshot(value: object) -> bool:
    """True for a well-formed ``sha256:<64 hex>`` snapshot string."""
    if not isinstance(value, str) or not value.startswith(SNAPSHOT_PREFIX):
        return False
    hexdigest = value[len(SNAPSHOT_PREFIX):]
    return len(hexdigest) == 64 and all(char in "0123456789abcdef" for char in hexdigest)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("target", "snapshot", "inputs", "exclusions"))
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        root = resolve_project_root(args.root)
        if args.command == "target":
            target = resolve_target(root)
            payload: object = {
                "project_root": str(root),
                "target": str(target),
                "target_spec": repo_relative(root, target),
                "declared": declared_target_spec(root),
            }
            plain = repo_relative(root, target)
        elif args.command == "snapshot":
            snapshot = content_snapshot(root)
            payload = {"project_root": str(root), "source_snapshot": snapshot}
            plain = snapshot
        elif args.command == "inputs":
            entries = snapshot_entries(root)
            payload = [{"path": path, "sha256": digest} for path, digest in entries]
            plain = "\n".join(f"{digest}  {path}" for path, digest in entries)
        else:
            payload = load_exclusions(root)
            plain = "\n".join(load_exclusions(root))
    except ProjectError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    print(json.dumps(payload, indent=2) if args.json else plain)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
