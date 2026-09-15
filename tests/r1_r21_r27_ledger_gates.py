#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
R1 + R21 + R27 — two-gate ledger enforcement (C1, contracts G1/G2).

Gate A (reference integrity, check_ledger_references.py):
R1: empty and prose-only (zero-citation) ledgers FAIL — no vacuous pass.
R21 mutations: a content-bound citation catches a moved symbol (lines
inserted above shift the target), and stubbed-out enforcement (the cited
check replaced by a trivial stub); Rust `#[...]` attribute lines are
valid citation targets; every `axiom:` occurrence needs a meaningful
justification (placeholders fail, one check per occurrence); per-link
Kani coverage gates under --strict-kani; --suggest-hashes emits binding
suffixes. Citation parsing accepts every dossier form — backticked path,
fully backticked `code: path:line@sha256:hash`, plain `code:`
annotation, `**Depends on:**` block headers — keeps containment and
content-hash checks on each, refuses prose and inline code as citations,
and fails malformed `code:` annotations loudly. `kani:` annotations are
parsed against the coverage grammar, so a placeholder body
(`n/a`/`none`/`TODO`/`n_a`/`pending`/`covered`/`-`), an unlocated bare
word (`pass`/`fine`/`exempt`/`maybe`/`nothing`/`irrelevant`, and
`merkle` too), a bare `kani: skipped`, a thin because-clause, and the
text "kani:" inside another word or inside `#[kani::proof]` are not
per-link coverage; every valid dossier form (`snake_case` harness,
`module::harness`, cited location, a bare name beside a `<path>:<line>`
locator, parenthesised bound, closed-list skip) still passes. A
`Depends on:` block closes at a blank
line or a heading, so a later unrelated bullet list is not counted as
trust-chain links, while a loose list nested under the header is; a
post-blank bullet at the header's own indentation is deliberately NOT
reopened, and both sides of that trade are pinned here.

Gate B (semantic evidence, check_evidence_records.py):
R27: a G1 record missing any binding field (or the waiver key) is
rejected; missing required claims, FAIL results, stale snapshots, and
unwaived externally-assumed evidence map to the exact G2 verdicts; the
passing verdict is scoped VERIFIED[...], never bare VERIFIED.

Exit 0 pass, 1 fail.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
GATE_A = REPO / "scripts" / "check_ledger_references.py"
GATE_B = REPO / "scripts" / "check_evidence_records.py"
FIXTURE = REPO / "tests" / "fixtures" / "r21"
FAILURES: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"  [ok]   {label}")
    else:
        suffix = f" ({detail})" if detail else ""
        print(f"  [FAIL] {label}{suffix}")
        FAILURES.append(label)


def line_hash(line: str) -> str:
    return hashlib.sha256(line.rstrip().encode()).hexdigest()[:12]


def gate_a(root: Path, ledger_text: str, *extra: str) -> tuple[int, str]:
    ledger = root / ".fv" / "ledger.md"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text(ledger_text)
    proc = subprocess.run(
        [sys.executable, str(GATE_A), str(ledger), "--root", str(root), *extra],
        capture_output=True, text=True, timeout=60)
    return proc.returncode, proc.stdout + proc.stderr


def gate_b(records, *extra: str) -> tuple[int, str]:
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(records, f)
        path = Path(f.name)
    try:
        proc = subprocess.run(
            ["uv", "run", "--script", str(GATE_B), "--records", str(path),
             "--allow-unbound", *extra],
            capture_output=True, text=True, timeout=120)
        return proc.returncode, proc.stdout + proc.stderr
    finally:
        path.unlink(missing_ok=True)


GOOD_AXIOM = "axiom: gnark verifier is upstream-trusted; no executable on-chain target."
KANI_OK = "kani: skipped because fixture exercise only."


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="r21-") as td:
        root = Path(td) / "proj"
        shutil.copytree(FIXTURE / "proj", root)
        guard = root / "src" / "guard.rs"
        guard_lines = guard.read_text().splitlines()
        h1 = line_hash(guard_lines[0])
        h = line_hash(guard_lines[1])
        h5 = line_hash(guard_lines[4])

        # ── R1: no vacuous pass ────────────────────────────────────────
        code, out = gate_a(root, "")
        check("R1: empty ledger fails", code == 1 and "no code citations" in out)
        code, out = gate_a(root, "# Ledger\n\nAll good, nothing to see. "
                                 + GOOD_AXIOM + " " + KANI_OK + "\n")
        check("R1: prose-only (zero-citation) ledger fails",
              code == 1 and "no code citations" in out)

        # ── baseline: hashed citation, good axiom, kani note ───────────
        baseline = (f"- B1 enforced at `src/guard.rs:2@sha256:{h}`. {KANI_OK}\n"
                    f"- {GOOD_AXIOM}\n")
        code, out = gate_a(root, baseline)
        check("baseline hashed ledger passes Gate A", code == 0, out[-300:])
        check("Gate A pass names its scope (reference integrity only)",
              "reference integrity only" in out)

        # ── R21: moved symbol (insert lines above the cited one) ───────
        moved = root / "src" / "guard.rs"
        original = moved.read_text()
        # non-comment insertions: the shifted target is still code-shaped,
        # so only the content hash can catch the drift
        moved.write_text("use std::fmt;\nuse std::mem;\n" + original)
        code, out = gate_a(root, baseline)
        check("R21: inserted lines above -> content-hash mismatch caught",
              code == 1 and "content hash mismatch" in out)
        moved.write_text(original)

        # ── R21: stubbed enforcement at the cited line ──────────────────
        stubbed = original.replace("    x != 0", "    true")
        moved.write_text(stubbed)
        code, out = gate_a(root, baseline)
        check("R21: stubbed enforcement -> content-hash mismatch caught",
              code == 1 and "content hash mismatch" in out)
        moved.write_text(original)

        # ── attribute lines are valid targets ──────────────────────────
        code, out = gate_a(root, f"- harness at `src/guard.rs:5@sha256:{h5}`. {KANI_OK}\n"
                                 f"- {GOOD_AXIOM}\n")
        check("R21: #[...] attribute line accepted as citation target",
              code == 0, out[-300:])

        # ── axiom anchoring + justification threshold ───────────────────
        code, out = gate_a(root, f"- B1 at `src/guard.rs:2`. {KANI_OK}\n"
                                 f"- axiom: TODO figure this out later\n")
        check("R21: placeholder axiom justification fails",
              code == 1 and "meaningful" in out)
        code, out = gate_a(root, f"- B1 at `src/guard.rs:2`. {KANI_OK}\n"
                                 f"- {GOOD_AXIOM} axiom: x\n")
        check("R21: second axiom occurrence on a line is checked too",
              code == 1 and "meaningful" in out)

        # ── per-link kani coverage ──────────────────────────────────────
        linked = (f"Depends on:\n"
                  f"  - inv_b1 at `src/guard.rs:2@sha256:{h}` [proven]  code: src/guard.rs:2@sha256:{h}  {KANI_OK}\n"
                  f"  - helper at `src/guard.rs:1@sha256:{h1}` [proven]  code: src/guard.rs:1@sha256:{h1}\n"
                  f"\n- {GOOD_AXIOM}\n")
        code, out = gate_a(root, linked)
        check("R21: link without kani warns by default",
              code == 0 and "trust-chain link without" in out)
        code, out = gate_a(root, linked, "--strict-kani")
        check("R21: link without kani fails under --strict-kani",
              code == 1 and "trust-chain link without" in out)

        # ── F10: kani: bodies are parsed, not substring-matched ─────────
        # A link line carrying `kani: n/a` satisfied the old substring
        # test, so an entirely unmeasured link read as covered.
        for placeholder in ("n/a", "none", "TODO", "-"):
            vague = (f"Depends on:\n"
                     f"- L1 at `src/guard.rs:2@sha256:{h}` kani: {placeholder}\n")
            code, out = gate_a(root, vague)
            check(f"F10: `kani: {placeholder}` is not per-link coverage",
                  code == 0 and "trust-chain link without" in out
                  and "naming neither a harness nor an explicit skip" in out,
                  out[-300:])
            code, out = gate_a(root, vague, "--strict-kani")
            check(f"F10: `kani: {placeholder}` fails under --strict-kani",
                  code == 1 and "trust-chain link without" in out, out[-300:])

        code, out = gate_a(root, f"Depends on:\n- L1 at `src/guard.rs:2@sha256:{h}`"
                                 f" kani: skipped\n", "--strict-kani")
        check("F10: bare `kani: skipped` fails without a because-clause",
              code == 1 and "without a `because <reason>` clause" in out,
              out[-300:])
        code, out = gate_a(root, f"Depends on:\n- L1 at `src/guard.rs:2@sha256:{h}`"
                                 f" kani: skipped because tbd\n", "--strict-kani")
        check("F10: `kani: skipped because <placeholder>` fails",
              code == 1 and "no reviewable reason" in out, out[-300:])

        # The text "kani:" inside another word or inside a Rust path is
        # not an annotation: it covers no link and does not discharge the
        # whole-ledger no-annotation check either.
        embedded = (f"Depends on:\n"
                    f"- L1 at `src/guard.rs:2@sha256:{h}` barkani: harness_check\n"
                    f"- L2 at `src/guard.rs:5@sha256:{h5}` enforced by `#[kani::proof]`\n")
        code, out = gate_a(root, embedded, "--strict-kani")
        check("F10: `barkani:` and `#[kani::proof]` are not kani annotations",
              code == 1 and "Kani annotations:  0" in out
              and "ledger contains no `kani:` annotations" in out, out[-400:])

        # Every valid dossier form keeps passing: a named harness, a
        # `module::harness` path, the harness cited by location, a
        # parenthesised bound, and closed-list or three-word skips.
        valid_kani = (
            "**Depends on:**\n"
            f"  - L1 at `src/guard.rs:2@sha256:{h}` kani: harness_check\n"
            f"  - L2 at `src/guard.rs:5@sha256:{h5}` kani: harnesses::harness_check\n"
            f"  - L3 at `src/guard.rs:1@sha256:{h1}` kani: src/guard.rs:5\n"
            f"  - L4 at `src/guard.rs:2@sha256:{h}` kani: invariants_hold "
            f"(bounded: 10 ops, unwind 12)\n"
            f"  - L5 at `src/guard.rs:2@sha256:{h}` kani: skipped because off-chain\n"
            f"  - L6 at `src/guard.rs:2@sha256:{h}` kani: skipped because Verus-only\n"
            f"  - L7 at `src/guard.rs:2@sha256:{h}` kani: skipped because the "
            f"ghost counters are covered by the L1 harness\n"
        )
        code, out = gate_a(root, valid_kani, "--strict-kani")
        check("F10: every valid dossier kani: form still passes",
              code == 0 and "Kani annotations:  7" in out
              and "Trust-chain links: 7" in out, out[-400:])

        # ── N3: an unlocated bare word is not coverage ──────────────────
        # An earlier pass accepted any identifier-shaped token absent
        # from NON_HARNESS_TOKENS, so per-link Kani coverage was
        # dischargeable by an arbitrary word — the closed list is an
        # enumeration of remembered spellings, and `pass`, `fine`,
        # `exempt`, `maybe`, `nothing`, `irrelevant` were never in it.
        # Gate A holds no harness catalog, so nothing else in the
        # pipeline could confirm the name. A bare single-segment token
        # now needs a `<path>:<line>` locator beside it; the
        # conventional `snake_case` and `module::harness` spellings stay
        # accepted unlocated (asserted in valid_kani above), which is
        # what keeps every existing ledger passing.
        for word in ("pass", "fine", "exempt", "maybe", "nothing",
                     "irrelevant", "somehow", "merkle", "verifyMerkle", "b2"):
            bare = ("**Depends on:**\n"
                    f"  - L1 at `src/guard.rs:2@sha256:{h}` kani: {word}\n")
            code, out = gate_a(root, bare, "--strict-kani")
            check(f"N3: unlocated bare `kani: {word}` is not per-link coverage",
                  code == 1 and "trust-chain link without" in out
                  and "not coverage on its own" in out
                  and "Kani annotations:  0" in out, out[-400:])
            code, out = gate_a(root, bare)
            check(f"N3: bare `kani: {word}` warns (not silently covers) by default",
                  code == 0 and "not coverage on its own" in out
                  and "Kani annotations:  0" in out, out[-400:])

        # The same names ARE coverage once the annotation carries a
        # locator that parses: plain, parenthesised-and-backticked, and
        # content-bound forms all resolve to a place in the tree a
        # reviewer can check, which is the evidence a bare word lacked.
        located_names = (
            "**Depends on:**\n"
            f"  - L1 at `src/guard.rs:2@sha256:{h}` kani: merkle at src/guard.rs:5\n"
            f"  - L2 at `src/guard.rs:5@sha256:{h5}` kani: verifyMerkle "
            f"(`src/guard.rs:2@sha256:{h}`)\n"
            f"  - L3 at `src/guard.rs:1@sha256:{h1}` kani: b2 at "
            f"src/guard.rs:5@sha256:{h5}\n"
        )
        code, out = gate_a(root, located_names, "--strict-kani")
        check("N3: a bare harness name plus a locator is per-link coverage",
              code == 0 and "Kani annotations:  3" in out
              and "Trust-chain links: 3" in out, out[-400:])

        # A non-parsing locator is no locator: the shape has to read as
        # `<path>.<ext>:<line>`, not merely contain a colon and digits.
        fake_locator = ("**Depends on:**\n"
                        f"  - L1 at `src/guard.rs:2@sha256:{h}` kani: merkle at 5:1\n")
        code, out = gate_a(root, fake_locator, "--strict-kani")
        check("N3: a bare name beside a prose ratio is still not coverage",
              code == 1 and "not coverage on its own" in out, out[-400:])

        for placeholder in ("none", "TODO", "n_a", "pending", "covered",
                            "NOT_APPLICABLE", "_none_"):
            vague = ("**Depends on:**\n"
                     f"  - L1 at `src/guard.rs:2@sha256:{h}` kani: {placeholder}\n")
            code, out = gate_a(root, vague, "--strict-kani")
            check(f"R3: bare `kani: {placeholder}` is still not coverage",
                  code == 1 and "trust-chain link without" in out
                  and "is a placeholder, not a harness name" in out,
                  out[-300:])

        # A placeholder is refused even beside a locator: a body that
        # asserts absence names no harness however well it points at
        # code, so the closed list outranks the locator allowance.
        located_placeholder = (
            "**Depends on:**\n"
            f"  - L1 at `src/guard.rs:2@sha256:{h}` kani: none at src/guard.rs:5\n")
        code, out = gate_a(root, located_placeholder, "--strict-kani")
        check("N3: a placeholder plus a locator is not coverage either",
              code == 1 and "is a placeholder, not a harness name" in out,
              out[-300:])

        # The name-shape rule must not move the marker: "kani:" inside
        # another word, or the Rust attribute path `kani::proof`, is
        # still no annotation even when a harness name follows it.
        embedded_bare = (
            "**Depends on:**\n"
            f"  - L1 at `src/guard.rs:2@sha256:{h}` barkani: merkle\n"
            f"  - L2 at `src/guard.rs:5@sha256:{h5}` see `#[kani::proof]` on merkle\n"
        )
        code, out = gate_a(root, embedded_bare, "--strict-kani")
        check("R3: `barkani:` and `kani::proof` are still not annotations",
              code == 1 and "Kani annotations:  0" in out
              and "ledger contains no `kani:` annotations" in out, out[-400:])

        # ── F11: a Depends on: block closes at a blank line ─────────────
        # The block used to survive a blank line, so the next bullet list
        # was read as trust-chain links: an inflated count plus a
        # fabricated per-link failure on bullets that are not links.
        trailing_list = ("**Depends on:**\n"
                         f"  - L1 at `src/guard.rs:2@sha256:{h}` kani: harness_check\n"
                         "\n"
                         "- unrelated follow-up bullet\n"
                         "- another unrelated bullet\n")
        code, out = gate_a(root, trailing_list, "--strict-kani")
        check("F11: blank line closes the block; later bullets are not links",
              code == 0 and "Trust-chain links: 1" in out
              and "trust-chain link without" not in out, out[-400:])

        section_break = ("Depends on:\n"
                         f"- L1 at `src/guard.rs:2@sha256:{h}` kani: harness_check\n"
                         "## Later section\n"
                         "- a bullet belonging to the next section\n")
        code, out = gate_a(root, section_break, "--strict-kani")
        check("F11: a heading closes the block",
              code == 0 and "Trust-chain links: 1" in out
              and "trust-chain link without" not in out, out[-400:])

        loose_block = ("**Depends on:**\n"
                       f"  - L1 at `src/guard.rs:2@sha256:{h}` kani: harness_check\n"
                       "\n"
                       f"  - L2 at `src/guard.rs:5@sha256:{h5}` kani: harness_check\n"
                       "\n"
                       "- unrelated follow-up bullet\n")
        code, out = gate_a(root, loose_block, "--strict-kani")
        check("F11: a loose list nested under the header keeps both links",
              code == 0 and "Trust-chain links: 2" in out
              and "trust-chain link without" not in out, out[-400:])

        # ── R1 (post-review): the blank-line close is a contract choice ──
        # A post-blank bullet at the header's OWN indentation is not
        # reopened, and this is the one shape where that costs a true
        # entry. Reopening it would mean a blank line never closes a
        # block — the F11 defect above, where every later bullet in the
        # section counted as a link and hard-failed per-link Kani
        # coverage. The chosen trade is bounded and visible: the reported
        # link count falls below the entries actually written, and
        # indenting them under the header (the fv-compose Step 3
        # convention) restores every link. Both halves are asserted so
        # the fail-open boundary cannot be relaxed silently.
        flat_continuation = (
            "**Depends on:**\n"
            f"- L1 at `src/guard.rs:2@sha256:{h}` kani: harness_check\n"
            "\n"
            f"- L2 at `src/guard.rs:5@sha256:{h5}` kani: harness_check\n"
        )
        code, out = gate_a(root, flat_continuation, "--strict-kani")
        check("R1: post-blank bullet at the header's indentation is not a link "
              "(deliberate: one link, no fabricated failure)",
              code == 0 and "Trust-chain links: 1" in out
              and "trust-chain link without" not in out, out[-400:])
        indented_continuation = (
            "**Depends on:**\n"
            f"  - L1 at `src/guard.rs:2@sha256:{h}` kani: harness_check\n"
            "\n"
            f"  - L2 at `src/guard.rs:5@sha256:{h5}` kani: harness_check\n"
        )
        code, out = gate_a(root, indented_continuation, "--strict-kani")
        check("R1: indenting the continuation under the header restores the link",
              code == 0 and "Trust-chain links: 2" in out, out[-400:])

        # ── dossier-shaped citation forms (explicit parser) ─────────────
        # A real fv-compose Step 3 dependency entry: bold block header,
        # `at` citations, one fully backticked `code:` annotation, one
        # plain one. The legacy alternation read the backticked annotation
        # as a path named "code: src/guard.rs" and never saw the bold
        # header, so neither the link nor its citation was checked.
        dossier = (
            "## Cross-component link — attestation binds the handle\n"
            "\n"
            "Theorem: cross_component_attestation_bind\n"
            f"Located at: `src/guard.rs:1@sha256:{h1}`\n"
            "**Depends on:**\n"
            f"  - inv_attest at `src/guard.rs:2@sha256:{h}` [Verus / proven]  "
            f"`code: src/guard.rs:2@sha256:{h}`  kani: harness_check\n"
            f"  - harness_check at `src/guard.rs:5@sha256:{h5}` [verified]  "
            f"code: src/guard.rs:5@sha256:{h5}.  kani: harness_check\n"
            f"**Trust boundary:** {GOOD_AXIOM}\n"
        )
        code, out = gate_a(root, dossier, "--strict-kani")
        check("parser: dossier entry with every citation form passes",
              code == 0 and "Citations checked: 5 (5 content-bound)" in out,
              out[-400:])
        check("parser: bold **Depends on:** header opens the link block",
              "Trust-chain links: 2" in out, out[-200:])

        bold_missing = ("**Depends on:**\n"
                        f"  - inv_attest at `src/guard.rs:2@sha256:{h}` [proven]  "
                        f"code: src/guard.rs:2@sha256:{h}\n"
                        f"\n- {GOOD_AXIOM} {KANI_OK}\n")
        code, out = gate_a(root, bold_missing)
        check("parser: bold-header link without kani warns by default",
              code == 0 and "trust-chain link without" in out, out[-300:])
        code, out = gate_a(root, bold_missing, "--strict-kani")
        check("parser: bold-header link without kani fails under --strict-kani",
              code == 1 and "trust-chain link without" in out)

        # Containment and hash checks apply to the backticked `code:` form
        # exactly as they do to a bare backticked path.
        code, out = gate_a(root, f"- L1 `code: ../outside.rs:1@sha256:{h}`. {KANI_OK}\n"
                                 f"- {GOOD_AXIOM}\n")
        check("parser: backticked `code:` citation is containment-checked",
              code == 1 and "escapes the canonical root" in out, out[-300:])
        code, out = gate_a(root, f"- L1 `code: src/guard.rs:2@sha256:{h5}`. {KANI_OK}\n"
                                 f"- {GOOD_AXIOM}\n")
        check("parser: backticked `code:` citation is hash-checked",
              code == 1 and "content hash mismatch" in out, out[-300:])
        code, out = gate_a(root, f"- L1 `code: src/guard.rs:2`. {KANI_OK}\n"
                                 f"- {GOOD_AXIOM}\n", "--suggest-hashes")
        check("parser: unhashed backticked `code:` citation demands a binding",
              code == 1 and "missing required content hash" in out
              and f"src/guard.rs:2@sha256:{h}" in out, out[-300:])

        # Malformed annotations fail loudly; they are never skipped checks.
        code, out = gate_a(root, f"- L1 `code: src/guard.rs:2@sha256:{h[:6]}`. {KANI_OK}\n"
                                 f"- {GOOD_AXIOM}\n")
        check("parser: truncated hash in a `code:` annotation is unparseable",
              code == 1 and "unparseable" in out, out[-300:])
        code, out = gate_a(root, f"- L1 code: src/my guard.rs:2@sha256:{h}. {KANI_OK}\n"
                                 f"- {GOOD_AXIOM}\n")
        check("parser: unquoted space path in a plain `code:` annotation fails",
              code == 1 and "unparseable" in out, out[-300:])
        code, out = gate_a(root, f"- L1 at `src/guard.rs:2@sha256:{h[:6]}`. {KANI_OK}\n"
                                 f"- {GOOD_AXIOM}\n")
        check("parser: truncated hash in a backticked path citation fails",
              code == 1 and "malformed content binding" in out, out[-300:])

        # Prose and ordinary inline code are not citations: this paragraph
        # carries exactly one, and the ratio, symbol names, script name and
        # `Code side:` prose must not inflate the count.
        prose = (f"- B1 holds at a `5:1` win ratio; `inv_b1` in `specs/jobq.qnt` is\n"
                 f"  checked by `check_evidence_records.py`. Code side: the guard at\n"
                 f"  `src/guard.rs:2@sha256:{h}` rejects zero. {KANI_OK}\n"
                 f"- {GOOD_AXIOM}\n")
        code, out = gate_a(root, prose)
        check("parser: prose, ratios and inline code are not citations",
              code == 0 and "Citations checked: 1 (1 content-bound)" in out,
              out[-400:])

        # ── --suggest-hashes ────────────────────────────────────────────
        code, out = gate_a(root, f"- B1 at `src/guard.rs:2`. {KANI_OK}\n"
                                 f"- {GOOD_AXIOM}\n", "--suggest-hashes")
        check("Gate A suggests the content-hash suffix",
              f"src/guard.rs:2@sha256:{h}" in out)

    # ── Gate B: R27 and the G2 truth table ─────────────────────────────
    valid = json.loads((FIXTURE / "records-valid.json").read_text())

    code, out = gate_b(valid, "--require", "B1,W1")
    check("Gate B: valid records for all required claims -> exit 0", code == 0,
          out[-300:])
    check("Gate B: verdict scope names the profile and the freshness binding",
          "VERIFIED[profile=bounded; binding=unbound]" in out
          and "VERDICT: VERIFIED\n" not in out)

    r27 = json.loads(json.dumps(valid))
    del r27[0]["bindings"]["seeds"]
    code, out = gate_b(r27, "--require", "B1,W1")
    check("R27: missing binding field rejected -> INCOMPLETE",
          code == 3 and "missing binding field 'seeds'" in out)

    r27b = json.loads(json.dumps(valid))
    del r27b[1]["waiver"]
    code, out = gate_b(r27b, "--require", "B1,W1")
    check("R27: missing waiver key rejected", code == 3 and "'waiver'" in out)

    code, out = gate_b(valid, "--require", "B1,W1,S9")
    check("Gate B: missing required claim -> INCOMPLETE",
          code == 3 and "S9: no record" in out)

    failed = json.loads(json.dumps(valid))
    failed[0]["result"] = "FAIL"
    code, out = gate_b(failed, "--require", "B1,W1")
    check("Gate B: required-claim FAIL -> FAILED exit 1",
          code == 1 and "FAILED" in out)

    code, out = gate_b(valid, "--require", "B1,W1",
                       "--expect-snapshot", "fffffff")
    check("Gate B: stale snapshot -> INCOMPLETE",
          code == 3 and "stale record" in out)

    assumed = json.loads(json.dumps(valid))
    assumed[0]["evidence_class"] = "externally-assumed"
    code, out = gate_b(assumed, "--require", "B1,W1")
    check("Gate B: unwaived externally-assumed PASS -> INCOMPLETE",
          code == 3 and "without a waiver" in out)
    assumed[0]["waiver"] = {"id": "W-B1-gnark", "approver": "reviewer",
                            "scope": "upstream gnark verifier accepted as "
                                     "externally-assumed for claim B1"}
    code, out = gate_b(assumed, "--require", "B1,W1")
    check("Gate B: waived assumption remains visibly qualified",
          code == 0 and "VERIFIED[profile=bounded; binding=unbound] (waived: B1)" in out)

    code, out = gate_b(valid, "--require", "")
    check("Gate B: empty required-claims list is an error, not a pass",
          code == 2)

    print()
    if FAILURES:
        print(f"R1/R21/R27: {len(FAILURES)} failure(s)")
        return 1
    print("R1/R21/R27: all assertions passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
