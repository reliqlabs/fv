#!/usr/bin/env python3
"""
check_ledger_references.py — the REFERENCE-INTEGRITY gate (Gate A of the
two-gate ledger split, C1).

This gate checks that the ledger's references hook into the live codebase:
paths resolve inside the canonical root, cited lines exist and carry real
content, annotations are well-formed. It does NOT judge whether the cited
evidence semantically discharges any claim — that is the semantic evidence
gate (`check_evidence_records.py`, Gate B), which validates claim-ID-keyed
G1 records. A ledger can pass this gate and still describe an unverified
system; passing here means only that nothing it points at has drifted.

Reference implementation for Step 8 of skills/fv-compose/SKILL.md.
Copy to <project>/.fv/scripts/ and invoke from CI on every revision.

Checks:

1. Citation resolution — every `<file>:<line>` citation in the ledger must
   point at an existing file and a line number within that file, contained
   inside the canonical root. Four citation forms are parsed explicitly
   (each may carry the `@sha256:<12hex>` binding described in 3):
       `specs/RcvSpec.lean:263`          backticked path citation
       `code: src/handle.rs:201`         fully backticked code annotation
       code: src/handle.rs:201           plain code annotation
       code: `src/my file.rs:201`        annotation with a quoted path
   A backticked path may contain spaces (the backticks delimit it); a
   plain `code:` path may not. A `code:` annotation whose value does not
   parse fails the gate loudly rather than being silently skipped.
2. Citation content sanity — the cited line must be non-empty and not a
   comment-only line (Rust `#[...]` attribute lines are valid targets).
   A citation pointing at `// TODO` is the same shape of drift as a
   missing citation.
3. Content-hash binding — every citation MUST carry an `@sha256:<12hex>`
   suffix over the cited line with trailing whitespace stripped. Missing or
   mismatched hashes fail the gate. Use `--suggest-hashes` to print the
   required suffix for each unhashed citation.
4. No vacuous pass — an empty ledger, or one containing zero citations,
   FAILS. A gate with nothing to check has checked nothing.
5. Kani coverage — every trust-chain link (an entry line under a
   `Depends on:` or `**Depends on:**` header) should carry either a
   `kani:` harness reference or a
   `kani: skipped because <reason>` annotation. Per-link misses WARN by
   default and fail under --strict-kani (use once your ledger's kani
   annotations are complete). Zero `kani:` annotations in the whole
   ledger follows the same strictness switch.
6. Axiom annotation — every `axiom:` occurrence (each one on a line, not
   just the first) must carry a meaningful justification phrase: at
   least three words, not a placeholder (TODO/tbd/n/a/...).

USAGE
    check_ledger_references.py <ledger.md> [--root <project-root>]
        [--strict-kani] [--suggest-hashes]

    --root defaults to the ledger's grandparent directory (i.e. the
    project root when the ledger lives at <project>/.fv/ledger.md).

EXIT CODES
    0 — all checks passed
    1 — at least one gate failure
    2 — usage / IO error
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# ── Citation grammar ───────────────────────────────────────────────────
# Citations are parsed explicitly, one line at a time, instead of being
# matched by a single alternation. The legacy regex was ambiguous about
# where a `code:` annotation ended: a fully backticked annotation
# (`code: src/guard.rs:2@sha256:...`) parsed as a path literally named
# "code: src/guard.rs", which then failed as a missing file, and the
# malformed-annotation check had to guess at span overlaps to avoid
# double-reporting. The parser below tokenizes each line into backticked
# spans and plain text, then reads each token against one grammar:
#
#     citation := <path> ":" <line> [ "@sha256:" <12hex> ]
#
# Backticked spans delimit the path, so it may contain spaces. In plain
# text the path runs to the next whitespace or backtick.
CODE_PREFIX = "code:"
# `code:` as an annotation marker, not the tail of a word ("barcode:").
CODE_MARK_RE = re.compile(r"(?<![A-Za-z0-9_\-])code:[ \t]*")
CITATION_BODY_RE = re.compile(
    r"^(?P<path>\S(?:.*\S)?):(?P<line>\d+)(?:@sha256:(?P<hash>[0-9a-f]{12}))?$"
)
# A bare backticked span is a citation only when its path carries a
# dot-extension; that is what separates `src/guard.rs:2` from prose ratios
# ("5:1") and from ordinary inline code (`inv_b1`). An explicit `code:`
# marker already declares intent, so extension-less paths (`code:
# Makefile:12`) are accepted there.
EXTENSION_RE = re.compile(r"\.[A-Za-z0-9]+$")
PLAIN_PATH_TOKEN_RE = re.compile(r"[^\s`]+")
# An unquoted annotation that ends a sentence or a parenthetical carries
# the punctuation into its token: `code: src/guard.rs:2@sha256:ab...cd).`
# Trailing sentence punctuation is not part of the path.
TRAILING_PUNCTUATION = ".,;:!?)]}\"'"
# A `code:` value that did not parse but still carries a
# `<path>.<ext>:<line>`-shaped substring was meant as a citation (an
# unquoted path with spaces splits at the first space).
CITATION_SHAPE_RE = re.compile(r"\S*\.[A-Za-z0-9]+:\d+")
HASH_MARKER = "@sha256:"

KANI_RE = re.compile(r"kani:\s*(?P<body>.*)$")
LINK_LINE_RE = re.compile(r"^\s*-\s+\S")

COMMENT_PREFIXES = ("//", "#", "--", "/*", "*", ";")

# Justifications that name no reason. First-word placeholders fail the
# meaningful-justification threshold regardless of length.
PLACEHOLDER_WORDS = {"todo", "tbd", "n/a", "na", "fixme", "xxx", "later", "pending", "???"}


def is_comment_only(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return True
    if stripped.startswith("#["):
        return False  # Rust attribute lines (`#[kani::proof]`) are valid targets
    return any(stripped.startswith(p) for p in COMMENT_PREFIXES)


def line_hash(line: str) -> str:
    """Content binding for a cited line: SHA-256 of the line with trailing
    whitespace stripped, truncated to 12 hex chars (hand-writable)."""
    return hashlib.sha256(line.rstrip().encode()).hexdigest()[:12]


@dataclass(frozen=True)
class Citation:
    """One parsed `<path>:<line>[@sha256:<hex>]` reference."""
    path: str
    line: int
    bound_hash: str | None


def parse_citation_body(body: str, *, require_extension: bool) -> Citation | None:
    """Parse one citation body. Returns None when `body` is not a citation
    at all (ordinary inline code, prose, a ratio)."""
    m = CITATION_BODY_RE.match(body.strip())
    if m is None:
        return None
    path = m.group("path")
    if require_extension and not EXTENSION_RE.search(path):
        return None
    return Citation(path, int(m.group("line")), m.group("hash"))


def split_code_spans(text: str) -> list[tuple[bool, str]]:
    """Tokenize a ledger line into (is_backticked, content) segments. An
    unterminated backtick leaves the rest of the line as plain text."""
    segments: list[tuple[bool, str]] = []
    pos = 0
    while True:
        opened = text.find("`", pos)
        closed = text.find("`", opened + 1) if opened >= 0 else -1
        if opened < 0 or closed < 0:
            segments.append((False, text[pos:]))
            return segments
        segments.append((False, text[pos:opened]))
        segments.append((True, text[opened + 1:closed]))
        pos = closed + 1


def looks_like_citation(token: str, value: str) -> bool:
    """Whether a `code:` value that failed to parse was nonetheless meant
    as a citation — a path-shaped first token, or a `<path>.<ext>:<line>`
    further into the value (`code: src/my file.rs:1`, where the unquoted
    space truncated the path)."""
    if any(ch in token for ch in "/.:"):
        return True
    return CITATION_SHAPE_RE.search(value) is not None


def unparseable_code_failure(value: str) -> str:
    shown = value.strip()
    if len(shown) > 80:
        shown = shown[:77] + "..."
    return (f"unparseable `code:` citation {shown!r} — expected "
            f"`code: <path>:<line>@sha256:<12hex>`; quote the whole "
            f"path:line in backticks when the path contains spaces")


def parse_line(text: str) -> tuple[list[Citation], list[str]]:
    """Explicit citation parse of one ledger line. Returns the citations in
    source order plus malformed-annotation failures (each without the
    `ledger:<n>: ` prefix)."""
    citations: list[Citation] = []
    problems: list[str] = []
    for is_backticked, content in split_code_spans(text):
        if is_backticked:
            body = content.strip()
            if body.startswith(CODE_PREFIX):
                # `code: src/guard.rs:2@sha256:...` — the whole annotation
                # is quoted, so the path may contain spaces.
                cited = parse_citation_body(body[len(CODE_PREFIX):],
                                            require_extension=False)
                if cited is not None:
                    citations.append(cited)
                else:
                    problems.append(unparseable_code_failure(body))
                continue
            cited = parse_citation_body(body, require_extension=True)
            if cited is not None:
                citations.append(cited)
            elif HASH_MARKER in body:
                # Content-bound shape with a broken binding: a truncated or
                # non-hex hash is drift, not prose. Never silently skipped.
                problems.append(
                    f"malformed content binding in citation `{body}` — expected "
                    f"`<path>:<line>@sha256:<12hex>`")
            continue
        # Each `code:` marker owns the text up to the next marker, so one
        # annotation's value can never be read as another's.
        marks = list(CODE_MARK_RE.finditer(content))
        for index, mark in enumerate(marks):
            end = marks[index + 1].start() if index + 1 < len(marks) else len(content)
            value = content[mark.end():end]
            if not value.strip():
                # A trailing `code:` takes its value from the backticked
                # span that follows (or the next line); nothing to parse.
                continue
            token_match = PLAIN_PATH_TOKEN_RE.match(value)
            token = token_match.group(0).rstrip(TRAILING_PUNCTUATION) if token_match else ""
            cited = parse_citation_body(token, require_extension=False) if token else None
            if cited is not None:
                citations.append(cited)
            elif looks_like_citation(token, value):
                problems.append(unparseable_code_failure(value))
    return citations, problems


def is_depends_header(text: str) -> bool:
    """A `Depends on:` trust-chain block header, with or without Markdown
    emphasis or a heading prefix: `Depends on:`, `**Depends on:**`,
    `**Depends on**:`, `### Depends on:`."""
    core = text.strip().lstrip("#").strip()
    if ":" not in core:
        return False
    core = core.strip("*_` ")
    if core.endswith(":"):
        core = core[:-1].strip("*_` ")
    return core.casefold() == "depends on"


def meaningful_justification(just: str) -> bool:
    just = just.strip().strip("*_`").strip()
    words = re.findall(r"[A-Za-z][A-Za-z\-']*", just)
    if len(words) < 3:
        return False
    return words[0].lower() not in PLACEHOLDER_WORDS


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("ledger", help="path to ledger.md")
    ap.add_argument("--root", default=None, help="project root that citations resolve against")
    ap.add_argument("--strict-kani", action="store_true", help="fail (not warn) on missing kani annotations")
    ap.add_argument("--suggest-hashes", action="store_true",
                    help="print the @sha256 binding suffix for every citation that lacks one")
    args = ap.parse_args()

    ledger_path = Path(args.ledger).resolve()
    if not ledger_path.exists():
        print(f"FATAL: ledger not found at {ledger_path}", file=sys.stderr)
        return 2

    root = Path(args.root).resolve() if args.root else ledger_path.parent.parent
    ledger_lines = ledger_path.read_text().splitlines()

    failures: list[str] = []
    warnings: list[str] = []
    suggestions: list[str] = []
    n_citations = 0
    n_hashed = 0
    n_axioms = 0
    n_kani = 0
    n_links = 0
    in_depends_block = False

    file_cache: dict[Path, list[str]] = {}

    def load(p: Path) -> list[str] | None:
        if p not in file_cache:
            try:
                file_cache[p] = p.read_text(errors="replace").splitlines()
            except OSError:
                file_cache[p] = None  # type: ignore[assignment]
        return file_cache[p]

    for lineno, text in enumerate(ledger_lines, start=1):
        citations, malformed = parse_line(text)
        # A `code:` annotation that does not parse is a failure, not a
        # skipped check: the gate says nothing about code it never read.
        failures.extend(f"ledger:{lineno}: {problem}" for problem in malformed)
        for citation in citations:
            rel = citation.path
            cited_line = citation.line
            bound_hash = citation.bound_hash
            n_citations += 1
            # Containment: citations resolve inside the canonical root only.
            # `..` segments are rejected textually; resolve() then also
            # catches absolute paths and symlink escapes.
            if ".." in Path(rel).parts or Path(rel).is_absolute():
                failures.append(
                    f"ledger:{lineno}: citation `{rel}:{cited_line}` — path escapes the "
                    f"canonical root (`..` or absolute path)"
                )
                continue
            target = (root / rel).resolve()
            if not target.is_relative_to(root):
                failures.append(
                    f"ledger:{lineno}: citation `{rel}:{cited_line}` — resolves outside "
                    f"the canonical root ({target}); symlink escape?"
                )
                continue
            contents = load(target)
            if contents is None:
                failures.append(
                    f"ledger:{lineno}: citation `{rel}:{cited_line}` — file not found under {root}"
                )
                continue
            if cited_line < 1 or cited_line > len(contents):
                failures.append(
                    f"ledger:{lineno}: citation `{rel}:{cited_line}` — line out of range (file has {len(contents)} lines)"
                )
                continue
            cited = contents[cited_line - 1]
            if is_comment_only(cited):
                failures.append(
                    f"ledger:{lineno}: citation `{rel}:{cited_line}` — cited line is empty or comment-only: {cited.strip()!r}"
                )
                continue
            if bound_hash:
                n_hashed += 1
                actual = line_hash(cited)
                if actual != bound_hash:
                    failures.append(
                        f"ledger:{lineno}: citation `{rel}:{cited_line}` — content hash mismatch "
                        f"(bound @sha256:{bound_hash}, line now hashes @sha256:{actual}): the cited "
                        f"line changed — moved symbol, inserted lines, or stubbed enforcement"
                    )
            else:
                failures.append(
                    f"ledger:{lineno}: citation `{rel}:{cited_line}` — missing required content hash"
                )
                if args.suggest_hashes:
                    suggestions.append(f"{rel}:{cited_line}@sha256:{line_hash(cited)}")

        # Every `axiom:` occurrence on the line is checked, not just the
        # first; each is anchored to its own justification segment.
        if "axiom:" in text:
            segments = text.split("axiom:")[1:]
            for seg in segments:
                n_axioms += 1
                just = seg.split("axiom:")[0]
                # a following annotation on the same line ends the phrase
                just = re.split(r"\b(?:code|kani):", just)[0]
                if not meaningful_justification(just):
                    failures.append(
                        f"ledger:{lineno}: `axiom:` annotation without a meaningful "
                        f"justification phrase (got {just.strip()!r}; need at least "
                        f"three words, no placeholder)"
                    )

        km = KANI_RE.search(text)
        if km:
            n_kani += 1
            body = km.group("body").strip()
            if body.startswith("skipped") and "because" not in body:
                msg = f"ledger:{lineno}: `kani: skipped` without a `because <reason>` clause"
                (failures if args.strict_kani else warnings).append(msg)

        # Per-link Kani coverage: every entry line of a `Depends on:` block
        # is a trust-chain link and must carry `kani:` (harness or explicit
        # skip). Warn by default; gate under --strict-kani.
        if is_depends_header(text):
            in_depends_block = True
        elif in_depends_block:
            if LINK_LINE_RE.match(text):
                n_links += 1
                if "kani:" not in text:
                    msg = (f"ledger:{lineno}: trust-chain link without `kani:` harness "
                           f"reference or explicit skip: {text.strip()[:80]!r}")
                    (failures if args.strict_kani else warnings).append(msg)
            elif text.strip():
                in_depends_block = False

    # No vacuous pass: a ledger with nothing to check has checked nothing.
    if n_citations == 0:
        failures.append(
            "ledger contains no code citations — empty or prose-only ledgers FAIL, "
            "they do not vacuously pass"
        )

    if n_kani == 0:
        msg = "ledger contains no `kani:` annotations — trust-chain links lack harness coverage or explicit skips"
        (failures if args.strict_kani else warnings).append(msg)

    print(f"Citations checked: {n_citations} ({n_hashed} content-bound)")
    print(f"Axiom annotations: {n_axioms}")
    print(f"Kani annotations:  {n_kani}")
    print(f"Trust-chain links: {n_links}")
    for w in warnings:
        print(f"WARN: {w}")
    for f in failures:
        print(f"FAIL: {f}")
    if suggestions:
        print("\nContent-hash suggestions (append to the citation):")
        for s in suggestions:
            print(f"  {s}")
    if failures:
        print(f"\nGATE FAILED: {len(failures)} failure(s)")
        return 1
    print("\nGATE PASSED (reference integrity only — semantic evidence is "
          "check_evidence_records.py's gate)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
