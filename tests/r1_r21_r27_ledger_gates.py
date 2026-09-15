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
and fails malformed `code:` annotations loudly.

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
    check("Gate B: verdict is scoped VERIFIED[...], never bare",
          "VERIFIED[profile=bounded]" in out
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
    assumed[0]["waiver"] = {"by": "reviewer", "rationale": "upstream gnark verifier accepted"}
    code, out = gate_b(assumed, "--require", "B1,W1")
    check("Gate B: waived assumption remains visibly qualified",
          code == 0 and "VERIFIED[profile=bounded] (waived: B1)" in out)

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
