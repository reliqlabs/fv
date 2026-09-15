# FV concepts

The names and ideas this methodology uses. Authoritative; SKILLs and docs use these terms.

## The five pillars

The five complementary trust mechanisms FV composes. Always referred to by name, not number.

| Pillar | What it does |
|---|---|
| **Formal verification** | Mechanistic proofs; real guarantees, not statistical confidence |
| **Adversarial generation** | One model produces, another attacks. Adversaries beat consensus for correctness work |
| **Substrate constraints** | Types, ownership, linters, sanitizers — cheap, deterministic, deny whole bug classes |
| **Empirical validation** | Property tests, fuzzing, bounded model checking — covers regions formal methods can't reach |
| **Boundary discipline** | Narrow trusted/untrusted interfaces; verified core, contained periphery |

## The verification pyramid

Cheap to expensive, exec and spec axes. Each property routes to the cheapest tool that can verify it.

**Exec axis** (against real Rust, cheap → expensive):
Types → Lints → Property tests → Fuzzing → Kani → Verus → Aeneas → Lean

**Spec axis** (upstream of code, when system-level reasoning matters):
Quint / TLA+ → Lean (math, refinement)

## The workflow

Ten stages. Each stage produces an artifact that anchors the next.

1. **Intent doc** — human-written source of truth
2. **Tracer prototype** — fast throwaway, proves the design is feasible
3. **Intent revision** — informed by tracer
4. **System spec** — Quint/TLA+ when distributed semantics matter
5. **Implementation spec** — Lean specs and/or Verus annotations
6. **Spec adversarial review** — multi-model attack on each spec draft
7. **Implementation** — Rust against validated specs
8. **Verification** — the pyramid runs continuously
9. **Failure classification** — spec wrong / code wrong / prover stuck / tool mismatch / state-space blowup / infrastructure (`INDETERMINATE` when the evidence cannot decide)
10. **Coverage dashboard** — per-function trust calibration

Steps are sequential; later additions get *names*, not fractional numbers. If a step gets inserted between two existing steps, it earns a real name and a real position.

## The SKILLs

The verbs you actually run. Each is a SKILL the harness can invoke.

| SKILL | Verb | Stage |
|---|---|---|
| `fv-intent` | Author an intent doc forward (elicitation) | 1 |
| `fv-reverse-intent` | Distill an intent doc from existing code | 1 (retro) |
| `fv-adversarial` | Run spec adversarial review with intent + Quint trace generation | 6 |
| `fv-code-adversarial` | Read implementation against intent through six lenses | between 7 and 8 |
| `fv-lifecycle-adversary` | Red-team multi-tx admin features against Quint | when contract gains admin features |
| `fv-verify` | Run the verification pyramid | 8 |
| `fv-compose` | Maintain cross-component trust ledger with code-line citations | 8 (continuous) |
| `fv-change` | Upstream-first change loop with re-verification | when changing a spec'd project |

## Project layout

Canonical locations within a FV-managed project. Skills cite these; do not invent alternatives per skill.

- `<project>/.fv/dispatch.json` → `omp_native.target_spec` — **the canonical intent/target declaration**. Its value is the intent document, persisted repo-relative to the project root; when the key is absent the target is `<project>/.fv/intent.md`. A skill that needs the intent resolves the declaration against the project root (never the cwd, never a fixed search order); an absolute value is valid only when it resolves inside the project root, and a missing, directory, symlink, or escaping target is an error, not a cue to look elsewhere. A project that wants the intent visible at top level declares `target_spec: "intent.md"` rather than relying on a fallback. `scripts/fv_project.py` (`resolve_target`, or `fv_project.py target --root <project>`) is the one implementation of these rules; installs also carry it at `<project>/.fv/scripts/fv_project.py`.
- `<project>/.fv/intent.md` — the default location of the intent document, used when `dispatch.json` declares no `target_spec`
- `<project>/.fv/ledger.md` — the trust ledger
- `<project>/.fv/attacks/` — spec adversarial reports, verbatim (`fv-adversarial`)
- `<project>/.fv/code-adversarial/` — code adversarial review reports (`fv-code-adversarial`)
- `<project>/.fv/lifecycle-adversary/` — lifecycle red-team reports (`fv-lifecycle-adversary`)
- `<project>/.fv/changes/` — change impact reports (`fv-change`)
- `<project>/.fv/verify/` — pyramid run reports (`fv-verify`)
- `<project>/.fv/classifications/` — failure-classifier reports (`fv-verify`)
- `<project>/.fv/evidence/` — typed G1 evidence records, one JSON per claim ID (`fv-compose`, Gate B)
- `<project>/.fv/scripts/` — project-local copies of dispatch + CI-gate scripts
- `<fv>/agents/` — static OMP agents loaded from the extension package

## The trust ledger

A project's `.fv/ledger.md` records every cross-component trust claim with:
- the named theorem
- the tools that contribute (Quint property, Lean theorem, Verus annotation, Kani harness)
- code-line citations for each link
- axiom inventory (which axioms each theorem's closure depends on)

`fv-compose` maintains it. CI gates fail when a link drifts from executable code.

## Trust-assumption categories

Each axiom in a project's trust closure falls into one of these. Always referred to by name.

| Category | What it means |
|---|---|
| **Standard cryptographic assumption** | Reduces to a textbook primitive (EUF-CMA, DDH, collision resistance, etc.) |
| **Deployment-side commitment** | Deployer-side runtime obligation (collateral freshness, rotation, well-formedness) |
| **Parser-layout assertion** | Pins a parser output to a specific window of input bytes; cross-checked against production code |
| **Bundled trust boundary** | Multiple primitives wrapped into one axiom for convenience; cleanup target |
| **Over-strength** | Asserts more than reality warrants; usually a refactoring target |
| **Impossibility / vacuity** | Assertion holds vacuously or asserts the impossible; bug |
| **External module dependency** | Trust assumption supplied by an upstream component, named explicitly |
| **Lean standard** | `propext`, `Classical.choice`, `Quot.sound` — accepted ambient |
| **Predicate carrier** | Opaque predicate with no asserted truth value; bookkeeping only |
| **Completeness** | The verifier accepts genuinely valid inputs; typically the dual of soundness |

The first four are the ones cleanup work moves *toward* (named primitives, named commitments, narrow assertions). The next two are what cleanup moves *away from*.

## Adversarial review findings

Findings are tagged inline with severity:

- **Critical** — soundness gap, allows attacks past the verifier
- **High** — audit-transparency gap, misleads reviewers about what's trusted
- **Medium** — methodology / framing tightening
- **Low** — cosmetic / docstring honesty

Inside a single review, findings are numbered (Critical 1, Critical 2, High 1, ...). Across reviews, findings are referred to by the practice they targeted (e.g., "the `signed_by_qe` decomposition critique") rather than by review-internal labels.

## Naming rules

Three rules to keep the namespace cheap to learn.

1. **No cycle numbers.** Git commits are the chronology. Commit messages carry the descriptive title. There is no "Cycle 7.5" — there is the commit whose title is "axiom demotion via DCAP reference verifier". (Exemption: the `Round: <N>` field in an attack report's metadata header is an ordinal within one spec's attack series — "the third attack against this intent" — not project chronology. It stays.)
2. **No fractional steps.** A step inserted later gets a name, not `Step 4.5`. If the name doesn't fit, the step shape was wrong.
3. **No alphabetical asks.** Methodology improvements live in `methodology-improvements.md` under their practice name (e.g., "system-of-intents shape", "per-section adversarial dispatch", "ghost-variable encoding"). Historical letter labels (Ask A, Ask AB) remain in archive only.

## Where the historical labels live

For traceability only — never load-bearing for new work.

- `archive/` — old MEMORY snapshots
- `methodology-improvements.md` — current improvements; previous "Ask X" labels appear in a single archive table at the end mapping old label → current practice name
- Per-project `.fv/ledger.md` — frozen historical artifacts (e.g., Quartz's `Cycle 7.x` ledger entries) — stay as-is; they are the audit trail
