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
* the verified-input snapshot is a deterministic content hash over the candidate
  set git reports, filtered by the project's verified-input policy: an exclusion
  list (the historical shape, and the default when no mode is declared) or an
  explicit ``mode: include`` allowlist. Structural output exclusions apply in
  either mode.

Import-safe: no module-level side effects. Gate and producer copies installed
under ``<project>/.fv/scripts`` import this file from their own directory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

DISPATCH_RELATIVE = ".fv/dispatch.json"
VERIFIED_INPUTS_RELATIVE = ".fv/verified-inputs.txt"
DEFAULT_TARGET_SPEC = ".fv/intent.md"
# Generated FV output, plus quarantined legacy history and in-flight migration
# staging: excluding these structurally keeps writing evidence, writing a verification
# report, writing a lifecycle report (a change record, an attack log, a code-adversarial
# report), quarantining legacy history, or a killed migration's staging residue from
# invalidating the evidence bound to the snapshot. Applied under an include policy too,
# so an allowlist naming ``.fv/`` cannot pull generated output back in. Mirrored in
# tools/evidence-run.ts.
DEFAULT_EXCLUSIONS = (".fv/evidence/", ".fv/verify/", ".fv/panels/", ".fv/changes/",
                      ".fv/attacks/", ".fv/code-adversarial/", ".fv/history/",
                      ".fv/.migrate-staging/", ".colosseum/")
# Verified-input policy modes. ``exclude`` is the historical shape and the mode a file
# with no directive carries, so every list written before include mode existed keeps its
# meaning. Mirrored in tools/evidence-run.ts.
MODE_EXCLUDE = "exclude"
MODE_INCLUDE = "include"
POLICY_MODES = (MODE_EXCLUDE, MODE_INCLUDE)
# A mode directive is the first non-comment line or nothing. ``mode: include`` is the
# canonical spelling; ``mode:include`` and interior padding parse the same. A line whose
# casefolded form starts with this prefix but names no known mode is rejected rather
# than read as a path entry, so ``Mode: Include`` cannot silently become an allowlist
# entry that matches nothing. Mirrored in tools/evidence-run.ts.
MODE_DIRECTIVE_PREFIX = "mode:"
SNAPSHOT_PREFIX = "sha256:"
# Characters Python's ``str.splitlines``/``str.strip`` treat as line breaks or
# whitespace while JavaScript's ``split("\n")``/``trim`` do not. An exclusion list
# carrying one parses differently in the gate and the producer, which would silently
# hash different input sets, so both ends reject it instead.
AMBIGUOUS_LINE_CHARS = "\x0b\x0c\x1c\x1d\x1e\x85\u2028\u2029"
# A byte-order mark survives Python's ``utf-8`` decode as this character, while the
# WHATWG decode a JavaScript runtime performs drops a leading one, so one list would
# yield two exclusion sets with nothing to attribute the difference to. Rejected
# anywhere in the file by both ends rather than stripped by either: a BOM inside an
# entry is not a path character. Mirrored in tools/evidence-run.ts.
BOM_CHAR = "\ufeff"
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
    absolute spec is accepted only when it lands inside the project root. ``~``
    is never expanded: a spec whose first component starts with it is rejected on
    both ends, so the producer and this resolver bind the same file. The result
    is an existing regular file; anything else is a ``ProjectError``.
    """
    root = resolve_project_root(project_root)
    spec = target_spec if target_spec is not None else declared_target_spec(root)
    if spec is None:
        spec = DEFAULT_TARGET_SPEC
    if not str(spec).strip():
        raise ProjectError("target_spec is empty")
    raw = Path(str(spec))
    if raw.parts and raw.parts[0].startswith("~"):
        raise ProjectError(f"target_spec must not start with '~': {spec}")
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


def _is_control(char: str) -> bool:
    """True for a C0 control, DEL, or a C1 control character.

    No control character is a legal exclusion-list character. LF, and the CR of a
    CRLF pair, separate entries; ``AMBIGUOUS_LINE_CHARS`` are reported as
    terminators; every remaining control is either stripped by one side's
    whitespace rule only (``\\x1f``), invisible inside an entry (``\\t``), or
    unrepresentable in a path (``\\x00``). Characters above U+009F are kept
    verbatim, so a path with non-ASCII components is a legal entry. Mirrored in
    ``tools/evidence-run.ts``.
    """
    code = ord(char)
    return code <= 0x1F or 0x7F <= code <= 0x9F


def _reject_ambiguous_characters(text: str) -> None:
    """Reject every character the two parsers would read differently.

    One rule, mirrored in ``tools/evidence-run.ts``: LF and CRLF separate
    entries, and every other control character, plus a byte-order mark, is
    rejected outright rather than stripped or re-interpreted. Python and
    JavaScript disagree about which of them break lines, which of them ``strip``,
    and whether a BOM survives decoding, so accepting one would let the gate and
    the producer derive different input sets from a single policy file. Every
    other Unicode character is kept verbatim: a non-ASCII path is a legal entry.
    """
    lineno = 1
    for index, char in enumerate(text):
        if char == "\n":
            lineno += 1
            continue
        if char == "\r" and text[index + 1:index + 2] == "\n":
            continue
        if char in AMBIGUOUS_LINE_CHARS or char == "\r":
            raise ProjectError(f"{VERIFIED_INPUTS_RELATIVE}:{lineno}: "
                               f"ambiguous line terminator {char!r}; use LF")
        if char == BOM_CHAR:
            raise ProjectError(f"{VERIFIED_INPUTS_RELATIVE}:{lineno}: byte-order mark "
                               f"U+FEFF; write the list as UTF-8 without a BOM")
        if _is_control(char):
            raise ProjectError(f"{VERIFIED_INPUTS_RELATIVE}:{lineno}: "
                               f"control character {char!r}; use LF-separated entries")


def _directive_value(line: str) -> str | None:
    """The mode a directive line names, or ``None`` when it is not a directive.

    The prefix is matched case-insensitively over exactly as many characters as
    it has, so the recognition is length-stable in both languages, and the value
    is compared against ``POLICY_MODES`` verbatim afterwards: a line that looks
    like a directive but names no known mode is a rejection, never a path entry.
    """
    head = line[:len(MODE_DIRECTIVE_PREFIX)].lower()
    if head != MODE_DIRECTIVE_PREFIX:
        return None
    return line[len(MODE_DIRECTIVE_PREFIX):].strip()


def mode_directive(mode: str) -> str:
    """The canonical directive line for ``mode``, without its newline."""
    if mode not in POLICY_MODES:
        raise ProjectError(f"unknown verified-input policy mode {mode!r}")
    return f"{MODE_DIRECTIVE_PREFIX} {mode}"


def matches_prefixes(relative: str, prefixes: list[str] | tuple[str, ...]) -> bool:
    """True when ``relative`` falls under one of ``prefixes``.

    One path-matching rule for both modes: a trailing-slash entry matches a
    literal path prefix, and a bare entry matches the path itself or the subtree
    beneath that whole directory component, so ``build`` never matches
    ``buildout.bin``. Mirrored in ``tools/evidence-run.ts``.
    """
    for prefix in prefixes:
        if prefix.endswith("/"):
            if relative.startswith(prefix):
                return True
        elif relative == prefix or relative.startswith(prefix + "/"):
            return True
    return False


# One rule, two sides of a policy. The exclusion name predates include mode and is what
# the gates and migration tooling already call.
is_excluded = matches_prefixes


@dataclass(frozen=True)
class InputPolicy:
    """How a project's git candidates become its verified inputs.

    ``mode`` is ``exclude`` (the historical shape, and what a file with no
    directive means) or ``include``. ``prefixes`` are the declared repo-relative
    file-or-directory entries in file order, deduped, under one path grammar for
    both modes. ``structural`` are the generated-output prefixes that apply in
    either mode and that no project file can drop.

    Under ``include`` the policy file selects itself, so revising the allowlist
    moves the snapshot and invalidates the evidence bound to the old one instead
    of silently re-scoping what evidence covers. An include policy naming no path
    is rejected: it would select a single file, the policy, and bind evidence to
    nothing a layer reads.
    """

    mode: str
    prefixes: tuple[str, ...] = ()
    structural: tuple[str, ...] = DEFAULT_EXCLUSIONS

    def __post_init__(self) -> None:
        object.__setattr__(self, "prefixes", tuple(self.prefixes))
        object.__setattr__(self, "structural", tuple(self.structural))
        if self.mode not in POLICY_MODES:
            raise ProjectError(f"unknown verified-input policy mode {self.mode!r}")
        if self.mode == MODE_INCLUDE and not self.prefixes:
            raise ProjectError(f"{VERIFIED_INPUTS_RELATIVE}: {mode_directive(MODE_INCLUDE)} "
                               f"names no path; list the paths in scope or drop the directive")

    def selectors(self) -> tuple[str, ...]:
        """Include-mode allowlist with the policy file self-bound; empty otherwise."""
        if self.mode != MODE_INCLUDE:
            return ()
        if VERIFIED_INPUTS_RELATIVE in self.prefixes:
            return self.prefixes
        return (*self.prefixes, VERIFIED_INPUTS_RELATIVE)

    def exclusions(self) -> list[str]:
        """Exclusion prefixes that apply: structural, plus declared under exclude mode."""
        prefixes = list(self.structural)
        if self.mode == MODE_EXCLUDE:
            for prefix in self.prefixes:
                if prefix not in prefixes:
                    prefixes.append(prefix)
        return prefixes

    def selects(self, relative: str) -> bool:
        """True when candidate ``relative`` is a verified input under this policy.

        Structural exclusions are applied first in both modes, so an allowlist
        entry can never pull generated FV output back into the snapshot and make
        writing a report stale the evidence that report describes.
        """
        if matches_prefixes(relative, self.structural):
            return False
        if self.mode == MODE_INCLUDE:
            return matches_prefixes(relative, self.selectors())
        return not matches_prefixes(relative, self.prefixes)

    def render(self, header: str = "") -> str:
        """This policy as file text that parses back to an equal policy."""
        return render_policy(self, header)


def render_policy(policy: InputPolicy, header: str = "") -> str:
    """Render ``policy`` as ``.fv/verified-inputs.txt`` text.

    The mode directive is always written, in both modes: a file that declares its
    own mode cannot be misread as the other one after an edit, and ``parse_policy``
    reads the result back to an equal policy. ``header`` is emitted verbatim ahead
    of the directive and is expected to carry only comment and blank lines.
    """
    if header and not header.endswith("\n"):
        header += "\n"
    body = f"{mode_directive(policy.mode)}\n"
    body += "".join(f"{prefix}\n" for prefix in policy.prefixes)
    return header + body


def parse_policy(text: str) -> InputPolicy:
    """Parse verified-input policy text into an ``InputPolicy``.

    A ``mode:`` directive is legal only as the first non-comment line; anywhere
    else it is a rejection rather than a path entry, so a mode declared halfway
    down a file can never apply to the entries above it. With no directive the
    policy is exclusion mode, which is what every list written before include
    mode existed means. Mirrored in ``tools/evidence-run.ts``.
    """
    _reject_ambiguous_characters(text)
    mode: str | None = None
    prefixes: list[str] = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        value = _directive_value(line)
        if value is not None:
            if mode is not None or prefixes:
                raise ProjectError(f"{VERIFIED_INPUTS_RELATIVE}:{lineno}: mode directive must be "
                                   f"the first non-comment line")
            if value not in POLICY_MODES:
                raise ProjectError(f"{VERIFIED_INPUTS_RELATIVE}:{lineno}: unknown mode {value!r}; "
                                   f"write {mode_directive(MODE_INCLUDE)!r} or "
                                   f"{mode_directive(MODE_EXCLUDE)!r}")
            mode = value
            continue
        if mode is None:
            mode = MODE_EXCLUDE
        if line.startswith("./"):
            line = line[2:]
        if not line or line in (".", "/"):
            verb = "selects" if mode == MODE_INCLUDE else "excludes"
            raise ProjectError(f"{VERIFIED_INPUTS_RELATIVE}:{lineno}: "
                               f"entry {verb} the whole project")
        if Path(line).is_absolute():
            raise ProjectError(f"{VERIFIED_INPUTS_RELATIVE}:{lineno}: absolute entry {line!r}")
        if ".." in Path(line).parts:
            raise ProjectError(f"{VERIFIED_INPUTS_RELATIVE}:{lineno}: entry escapes project root: {line!r}")
        if line not in prefixes:
            prefixes.append(line)
    return InputPolicy(mode or MODE_EXCLUDE, tuple(prefixes))


def parse_exclusions(text: str) -> list[str]:
    """Declared exclusion prefixes from exclusion-mode policy text.

    Include-mode text is a rejection, not an empty exclusion list: a caller that
    asked for exclusions would otherwise treat an allowlist as "excludes nothing"
    and hash the whole repository. Such callers want ``parse_policy``.
    """
    policy = parse_policy(text)
    if policy.mode != MODE_EXCLUDE:
        raise ProjectError(f"{VERIFIED_INPUTS_RELATIVE}: declares "
                           f"{mode_directive(policy.mode)!r}; use parse_policy")
    return list(policy.prefixes)


def load_policy(project_root: str | Path) -> InputPolicy:
    """The project's verified-input policy; exclusion mode with no entries when absent.

    The bytes are decoded as strict UTF-8 with no newline translation:
    ``read_text`` would rewrite a lone ``\\r`` to ``\\n`` and hide from
    ``parse_policy`` exactly the terminator it exists to reject, and a decode
    failure is a rejection here rather than a replacement character.
    """
    root = resolve_project_root(project_root)
    listing = root / VERIFIED_INPUTS_RELATIVE
    if not listing.is_file():
        return InputPolicy(MODE_EXCLUDE)
    try:
        text = listing.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise ProjectError(f"cannot read {VERIFIED_INPUTS_RELATIVE}: {error}") from error
    return parse_policy(text)


def load_exclusions(project_root: str | Path) -> list[str]:
    """Exclusion prefixes that apply to the project, defaults included.

    The defaults keep evidence, verification, panel, lifecycle-report,
    quarantined-history, and migration-staging outputs out of the snapshot so
    writing evidence, writing a change record or attack log, quarantining legacy
    history, or abandoning a migration mid-apply can never invalidate the
    evidence being written; a project list only adds prefixes, so it cannot
    restore a default into the snapshot. Under ``mode: include`` only the
    structural defaults are exclusions and selection is the allowlist's, so what
    the snapshot covers is ``load_policy``'s answer, never this one's.
    """
    return load_policy(project_root).exclusions()


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


def order_inputs(paths: list[str] | tuple[str, ...]) -> list[str]:
    """Snapshot order: UTF-8 byte-wise, not code-unit-wise.

    A JavaScript runtime's default string comparison orders by UTF-16 code unit,
    which puts every astral-plane path (leading surrogate U+D800..U+DBFF) ahead
    of U+E000..U+FFFF, the reverse of UTF-8 byte order. Both ends sort on UTF-8
    bytes so one repository hashes to one snapshot; mirrored by
    ``orderVerifiedInputs`` in ``tools/evidence-run.ts``.
    """
    return sorted(paths, key=lambda name: name.encode("utf-8"))


def snapshot_entries(
    project_root: str | Path,
    exclusions: list[str] | tuple[str, ...] | None = None,
    policy: InputPolicy | None = None,
) -> list[tuple[str, str]]:
    """Sorted ``(repo-relative POSIX path, content sha256)`` verified inputs.

    Selection comes from ``policy``, else from the project's declared policy. An
    explicit ``exclusions`` list is the historical call shape and is honoured as
    a literal exclusion set, defaults included or not exactly as given, so a
    caller can still ask what dropping one structural prefix would do.
    """
    root = resolve_project_root(project_root)
    if exclusions is not None:
        if policy is not None:
            raise ProjectError("pass either exclusions or policy, not both")
        policy = InputPolicy(MODE_EXCLUDE, tuple(exclusions), ())
    elif policy is None:
        policy = load_policy(root)
    selected = [name for name in candidate_paths(root) if policy.selects(name)]
    entries: list[tuple[str, str]] = []
    for relative in order_inputs(selected):
        path = root / relative
        resolved = Path(_normalize(path))
        if not _contained(root, resolved):
            raise ProjectError(f"verified input escapes project root: {relative}")
        try:
            mode = path.lstat().st_mode
        except OSError:
            # Tracked but deleted in the worktree; the absence is the change.
            continue
        if stat.S_ISLNK(mode):
            raise ProjectError(f"verified input is a symlink: {relative}")
        if stat.S_ISDIR(mode):
            # Submodule gitlink: its content is verified by its own repository.
            continue
        if not stat.S_ISREG(mode):
            # A FIFO, socket, or device node has no content to hash, and opening
            # one can block forever: classify it instead of hanging the snapshot.
            raise ProjectError(f"verified input is not a regular file: {relative}")
        try:
            entries.append((relative, _file_digest(path)))
        except OSError as error:
            raise ProjectError(f"cannot hash verified input {relative}: {error}") from error
    return entries


def content_snapshot(
    project_root: str | Path,
    exclusions: list[str] | tuple[str, ...] | None = None,
    policy: InputPolicy | None = None,
) -> str:
    """Deterministic ``sha256:<hex>`` snapshot of the project's verified inputs."""
    digest = hashlib.sha256()
    for relative, content_hash in snapshot_entries(project_root, exclusions, policy):
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
    parser.add_argument("command",
                        choices=("target", "snapshot", "inputs", "exclusions", "policy"))
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
        elif args.command == "policy":
            policy = load_policy(root)
            payload = {
                "project_root": str(root),
                "mode": policy.mode,
                "prefixes": list(policy.prefixes),
                "structural": list(policy.structural),
                "selectors": list(policy.selectors()),
                "exclusions": policy.exclusions(),
            }
            plain = policy.render()
        else:
            exclusions = load_exclusions(root)
            payload = exclusions
            plain = "\n".join(exclusions)
    except ProjectError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    print(json.dumps(payload, indent=2) if args.json else plain)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
