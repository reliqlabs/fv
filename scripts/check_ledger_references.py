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
   `Depends on:` or `**Depends on:**` header) should carry a `kani:`
   annotation that PARSES as coverage, not merely contain the text
   "kani:" somewhere. Three bodies are accepted:
       `kani: <harness_fn>`  — a harness named in the spelling the
           convention prescribes: `snake_case` (`bounded_ops_hold`) or
           `module::harness`. This gate holds no harness catalog, so it
           cannot confirm the name exists; what it insists on is a name
           shaped like the convention rather than an arbitrary word.
       `kani: <path>:<line>` — the harness cited by location, alone or
           beside a name (`kani: merkle at src/merkle.rs:42`). A bare
           single-segment identifier is coverage ONLY in this form: on
           its own no shape test separates a harness name from a status
           word ("pass", "fine", "exempt"), so the gate fails closed and
           asks for the locator.
       `kani: skipped because <reason>` — a closed-list reason
           (off-chain, Verus-only, axiom, out-of-scope, covered by
           cross-layer-ledger byte-equality test) or a justification of
           at least three words with no placeholder first word.
   `kani: n/a`, `kani: none`, `kani: TODO`, `kani: pending`,
   `kani: covered`, `kani: -`, an unlocated bare word (`kani: pass`,
   `kani: fine`, `kani: exempt`, `kani: merkle`), a bare
   `kani: skipped`, and the text "kani:" inside another word
   ("barkani:") or inside a Rust path (`#[kani::proof]`) are not
   coverage. A `Depends on:` block ends at a
   blank line, a heading, or any non-entry line, so an unrelated later
   bullet list is never counted as trust-chain links; across a blank
   line only a list indented deeper than the header continues (see
   find_trust_chain_links for that boundary and the reason it is drawn
   there rather than reopening the block for any later bullet).
   Per-link misses and unparseable bodies WARN by default and fail
   under --strict-kani (use once your ledger's kani annotations are
   complete). Zero parsed `kani:` annotations in the whole ledger
   follows the same strictness switch.
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

# ── Kani annotation grammar ────────────────────────────────────────────
# `kani:` is an annotation marker only as a whole word with a single
# colon: `barkani:` is the tail of another word, and `kani::proof` is the
# Rust attribute path a ledger cites by name. Neither is coverage.
KANI_MARK_RE = re.compile(r"(?<![A-Za-z0-9_\-])kani:(?!:)[ \t]*")
# A `code:`/`axiom:` annotation further along the line ends a kani body
# (and symmetrically, a `code:`/`kani:` marker ends an axiom phrase).
OTHER_ANNOTATION_MARK_RE = re.compile(r"(?<![A-Za-z0-9_\-])(?:code|axiom):(?!:)")
AXIOM_BODY_END_RE = re.compile(r"(?<![A-Za-z0-9_\-])(?:code|kani):(?!:)")
# The body is parsed against one grammar instead of being substring-
# searched, so a placeholder or a stray mention cannot pass as coverage:
#
#     kani_body    := "skipped" "because" <reason>
#                   | <qualified-ref> [ <qualifier> ]
#                   | [ <word> ... ] <locator> [ <word> ... ]
#     qualified-ref := <ident> ("::" <ident>)+
#                   | <ident> with an internal "_"
#     locator       := <path> "." <ext> ":" <line> [ "@sha256:" <12hex> ]
#
# The grammar is deliberately fail-closed on a BARE single-segment
# identifier (`merkle`, `verifyMerkle`, `pass`, `fine`, `exempt`).
# Accepting one was a fail-open widening: this gate holds no harness
# catalog — Gate A checks references, it never runs cargo-kani or reads
# a discovered-harness list — so nothing downstream ever confirms the
# named harness exists, and no shape test distinguishes a one-word
# harness name from a one-word status word. A closed denylist
# (NON_HARNESS_TOKENS below) cannot close that: it is an enumeration of
# the spellings someone thought of, and every word outside it
# ("pass", "fine", "maybe", "irrelevant") discharged the per-link Kani
# obligation on its own.
#
# So a bare identifier needs evidence that it names something real, and
# the only evidence available at this layer is a `<path>:<line>`
# locator that parses: `kani: merkle at src/merkle.rs:42` is coverage,
# `kani: merkle` is not. The two established spellings stay accepted
# unlocated because they carry structure a status word does not: the
# `<link_id>_<assertion>` snake_case of skills/fv-compose Step 3 and a
# `::`-qualified path. Their residue is named and bounded — a
# `_`-joined non-name (`will_do_later`) still reads as coverage unless
# the denylist carries its spelling, which is why every known
# placeholder spelling stays enumerated below and is refused even when
# a locator accompanies it. Rejecting the convention's own spelling
# instead would fail every in-repo ledger, so the denylist remains
# load-bearing there and nowhere else.
SKIPPED_BODY_RE = re.compile(r"skipped?\b[\s:,\-]*because\b\s*(?P<reason>.*)$",
                             re.IGNORECASE | re.DOTALL)
SKIP_FIRST_WORDS = {"skip", "skipped"}
FIRST_WORD_RE = re.compile(r"[A-Za-z][A-Za-z\-']*")
HARNESS_PATH_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:::[A-Za-z_][A-Za-z0-9_]*)*")
# Wrappers a ledger puts around a locator: Markdown emphasis, inline
# code, brackets. Stripped before the locator is parsed.
LOCATOR_WRAPPERS = "([{<`\"'*_"
# Tokens with the identifier shape (or nearly) that name no harness.
# This list is no longer the whole defence against a placeholder — the
# locator requirement above refuses every unlocated bare word, listed
# or not — so it is what it can be: an enumeration of the spellings
# that must never read as coverage even when they carry a locator or an
# internal `_`. Compared case-folded with surrounding `_` stripped, so
# `NOT_APPLICABLE` and `_none_` are caught. A false rejection here is
# loud and names its remedy; a false acceptance is silent, so the list
# errs towards rejecting.
NON_HARNESS_TOKENS = {
    "n_a", "na", "not_applicable", "not_run", "no_harness", "none", "no",
    "to_do", "todo", "tbd", "fixme", "xxx", "later", "pending", "unknown",
    "missing", "gap", "skip", "skipped", "see_above", "same_as_above",
    "as_above", "covered", "coverage", "covers", "verified", "verifies",
    "proven", "proved", "checked", "tested", "passing", "done", "ok",
    "okay", "yes", "y", "n", "nil", "null", "nope", "partial", "planned",
    "future", "soon", "wip", "unverified", "uncovered", "manual",
    "review", "see", "above", "below", "ditto", "same", "idem",
}
# The closed-list skip reasons of skills/fv-compose Step 5. They are
# shorter than the three-word justification threshold but are the
# documented, reviewable vocabulary, so they are accepted by name.
CLOSED_LIST_SKIP_REASONS = (
    "off-chain",
    "verus-only",
    "axiom",
    "out-of-scope",
    "covered by cross-layer-ledger byte-equality test",
)

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


def skip_reason_ok(reason: str) -> bool:
    """Whether a `kani: skipped because <reason>` reason is reviewable: a
    closed-list reason (optionally elaborated) or a meaningful phrase."""
    normalized = re.sub(r"\s+", " ", reason.strip().strip("*_`").strip()).casefold()
    normalized = normalized.rstrip(".;,")
    for closed in CLOSED_LIST_SKIP_REASONS:
        if normalized.startswith(closed):
            # Accepted alone or elaborated ("off-chain, the frontend ...").
            tail = normalized[len(closed):len(closed) + 1]
            if not (tail.isalnum() or tail == "-"):
                return True
    return meaningful_justification(reason)


def harness_locator(text: str) -> Citation | None:
    """The `<path>.<ext>:<line>` locator a kani body carries, if any.

    Each whitespace-separated word is unwrapped (brackets, backticks,
    Markdown emphasis, sentence punctuation) and parsed against the
    citation grammar, so a locator has to PARSE rather than merely look
    path-shaped: `src/m.rs:42` and `(src/m.rs:42@sha256:0123456789ab).`
    are locators, `src/m.rs:42x` and the prose ratio `5:1` are not.

    The locator's target is not resolved here. Resolution belongs to the
    citation loop, and a kani locator is deliberately not registered as
    a citation: it would inherit the mandatory `@sha256:` binding, which
    no ledger writes on a harness pointer. What the locator buys is a
    reviewable pointer into the tree where an arbitrary word would
    otherwise stand.
    """
    for word in text.split():
        candidate = word
        previous = None
        while candidate != previous:
            previous = candidate
            candidate = candidate.strip(LOCATOR_WRAPPERS).rstrip(TRAILING_PUNCTUATION)
        if not candidate:
            continue
        cited = parse_citation_body(candidate, require_extension=True)
        if cited is not None:
            return cited
    return None


def kani_body_problem(body: str) -> str | None:
    """Parse one `kani:` annotation body against the coverage grammar.
    Returns None when the body IS coverage, else the failure text (without
    the `ledger:<n>: ` prefix)."""
    text = body.strip().strip("*_`").strip()
    if not text:
        return ("empty `kani:` annotation — name a harness or write "
                "`kani: skipped because <reason>`")
    first_word = FIRST_WORD_RE.match(text)
    if first_word is not None and first_word.group(0).casefold() in SKIP_FIRST_WORDS:
        m = SKIPPED_BODY_RE.match(text)
        if m is None:
            return "`kani: skipped` without a `because <reason>` clause"
        reason = m.group("reason")
        if not skip_reason_ok(reason):
            return (f"`kani: skipped because` with no reviewable reason (got "
                    f"{reason.strip()[:60]!r}) — use a closed-list reason "
                    f"({', '.join(CLOSED_LIST_SKIP_REASONS)}) or at least "
                    f"three words, no placeholder")
        return None
    token = text.split()[0].rstrip(TRAILING_PUNCTUATION)
    locator = harness_locator(text)
    # `kani: crates/q/src/lib.rs:42` — the harness cited by location.
    if token and parse_citation_body(token, require_extension=True) is not None:
        return None
    if HARNESS_PATH_RE.fullmatch(token):
        name = token.casefold().strip("_")
        if not name or name in NON_HARNESS_TOKENS:
            # A placeholder spelling is refused even with a locator: a
            # body that asserts absence ("none") or coverage ("covered")
            # names no harness however well it points at code.
            return (f"`kani:` annotation naming neither a harness nor an explicit "
                    f"skip (got {text[:60]!r}) — {token!r} is a placeholder, "
                    f"not a harness name; write `kani: <harness_fn>` "
                    f"(`snake_case` or `module::harness`), "
                    f"`kani: <path>:<line>`, or `kani: skipped because <reason>`")
        # `kani: bounded_ops_hold`, `kani: harnesses::bounded_ops` — the
        # two spellings of skills/fv-compose Step 3, accepted unlocated.
        if "::" in token or "_" in name:
            return None
        # `kani: merkle at src/merkle.rs:42` — a bare single-segment name
        # is coverage only with a locator beside it.
        if locator is not None:
            return None
        return (f"`kani:` annotation naming a bare {token!r} with nothing that "
                f"resolves it (got {text[:60]!r}) — a one-word body is not "
                f"coverage on its own: this gate holds no harness catalog, so "
                f"nothing distinguishes a harness name from a status word. "
                f"Write `kani: {token} at <path>:<line>`, spell the harness "
                f"`snake_case` or `module::harness`, or write "
                f"`kani: skipped because <reason>`")
    # `kani: check at src/guard.rs:5@sha256:...` — a phrase plus a locator.
    if locator is not None:
        return None
    return (f"`kani:` annotation naming neither a harness nor an explicit skip "
            f"(got {text[:60]!r}) — write `kani: <harness_fn>` (a Rust name: "
            f"`snake_case` or `module::harness`), `kani: <path>:<line>`, a bare "
            f"name with a `<path>:<line>` locator beside it, or "
            f"`kani: skipped because <reason>`")


def kani_annotations(text: str) -> list[str]:
    """Bodies of every `kani:` annotation on the line, in source order.
    Each marker owns the text up to the next annotation marker, so one
    annotation's body can never be read as another's."""
    bodies: list[str] = []
    marks = list(KANI_MARK_RE.finditer(text))
    for index, mark in enumerate(marks):
        end = marks[index + 1].start() if index + 1 < len(marks) else len(text)
        body = text[mark.end():end]
        other = OTHER_ANNOTATION_MARK_RE.search(body)
        bodies.append(body[:other.start()] if other else body)
    return bodies


def indent_width(text: str) -> int:
    return len(text) - len(text.lstrip())


def is_heading(text: str) -> bool:
    return text.lstrip().startswith("#")


def find_trust_chain_links(lines: list[str]) -> set[int]:
    """1-based line numbers of the entry lines of every `Depends on:`
    block.

    A block runs from its header to the first of: a blank line, a Markdown
    heading, a further `Depends on:` header, or any nonblank line that is
    not a list entry. Without the blank-line close the block ran to the
    next prose line, so an unrelated later bullet list was counted as
    trust-chain links — inflating the link count and fabricating per-link
    Kani failures on bullets that are not links at all.

    The one continuation across a blank line is a loose list nested under
    the header: entries indented strictly deeper than the header keep the
    block open. A bullet back at (or left of) the header's indentation
    starts a new list and is not a link.

    That last sentence is the contract choice, not an oversight, and it
    is the one shape where this function trades away a true link. A
    post-blank bullet at the header's own indentation is ambiguous: it
    reads equally as a further entry of an unindented loose list or as
    the first bullet of the next prose list. Only one reading can be
    taken, and reopening the block for it is the old behaviour — a blank
    line would never close anything, so every later bullet in the
    section would be counted as a trust-chain link and hard-fail
    per-link Kani coverage on lines that are not links. Closing is
    preferred because its failure mode is bounded and visible: the
    reported "Trust-chain links" total falls below the number of entries
    actually written, and indenting the entries under the header (the
    convention of skills/fv-compose/SKILL.md Step 3, which every
    in-repo ledger follows) restores them. The residual exposure is
    fail-open — an unindented post-blank entry escapes the per-link Kani
    check — and is accepted here rather than moved onto every ordinary
    bullet list in the ledger. tests/r1_r21_r27_ledger_gates.py pins
    both halves of the trade.
    """
    links: set[int] = set()
    header_indent: int | None = None
    index = 0
    total = len(lines)
    while index < total:
        text = lines[index]
        if is_depends_header(text):
            header_indent = indent_width(text)
        elif header_indent is not None:
            if not text.strip():
                nxt = index + 1
                while nxt < total and not lines[nxt].strip():
                    nxt += 1
                loose_continuation = (
                    nxt < total
                    and LINK_LINE_RE.match(lines[nxt]) is not None
                    and indent_width(lines[nxt]) > header_indent
                )
                if not loose_continuation:
                    header_indent = None
            elif is_heading(text) or LINK_LINE_RE.match(text) is None:
                header_indent = None
            else:
                links.add(index + 1)
        index += 1
    return links


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
    link_lines = find_trust_chain_links(ledger_lines)

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
                just = AXIOM_BODY_END_RE.split(just)[0]
                if not meaningful_justification(just):
                    failures.append(
                        f"ledger:{lineno}: `axiom:` annotation without a meaningful "
                        f"justification phrase (got {just.strip()!r}; need at least "
                        f"three words, no placeholder)"
                    )

        # Kani annotations are parsed, not substring-matched: a body that
        # names no harness and no reviewable skip is a diagnostic, and it
        # never counts as coverage for the line or for the ledger.
        kani_covered = False
        for body in kani_annotations(text):
            problem = kani_body_problem(body)
            if problem is None:
                n_kani += 1
                kani_covered = True
            else:
                (failures if args.strict_kani else warnings).append(
                    f"ledger:{lineno}: {problem}")

        # Per-link Kani coverage: every entry line of a `Depends on:` block
        # is a trust-chain link and must carry a parsed `kani:` annotation
        # (harness reference or explicit skip). Warn by default; gate under
        # --strict-kani.
        if lineno in link_lines:
            n_links += 1
            if not kani_covered:
                msg = (f"ledger:{lineno}: trust-chain link without `kani:` harness "
                       f"reference or explicit skip: {text.strip()[:80]!r}")
                (failures if args.strict_kani else warnings).append(msg)

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
