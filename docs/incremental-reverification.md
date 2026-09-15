# Incremental re-verification and the ledger envelope (M5)

Scaffolding for the system-of-intents change loop. This document defines the
ledger schema envelope, the rule for reusing component evidence when a system
changes, and how the assurance tiers map onto non-Rust components. It is the
reference the `fv-boundary` skill and `fv-change` point at when
they bound the blast radius of a change.

Status: the bidboard system-of-intents run this scaffolding is built for has
NOT been run. This document specifies the mechanism; no system verdict is
claimed here.

## The ledger envelope

The two-gate ledger (C1) consumes G1 evidence records. On their own, records are
a bare JSON list. M5 wraps a record set in a versioned envelope:

```json
{
  "ledger_schema_version": "fv-ledger/v2",
  "records": [ { "claim_id": "...", "...": "..." } ]
}
```

- A bare list (or a bare single record object) is **unversioned** (`unversioned/v0`).
  It is still valid input to the gates; the difference is that an unversioned
  ledger cannot participate in schema-aware reuse below.
- `scripts/check_ledger_version.py` validates only the envelope's version field:
  exit 0 for a recognized version or for a bare/unversioned ledger (with a
  warning), exit 2 for an object that carries a `ledger_schema_version` the
  toolchain does not know, or that carries a `records` key with no version.
- `scripts/check_evidence_records.py` and `scripts/coverage_dashboard.py` both
  read either shape: their `unwrap` step flattens an envelope to its `records`
  list, so a versioned ledger and its equivalent bare list gate to the identical
  verdict. The version field never changes a verdict; it only lets a change-loop
  pass tell a schema migration apart from an ordinary source change.

Recognized versions live in `check_ledger_version.py`'s `KNOWN_VERSIONS`. A new
schema version is added there deliberately, the same way tool pins move in
`bom.json`: a forward-incompatible ledger fails loudly rather than being read
under the wrong assumptions.

## What a change invalidates

A G1 record binds its evidence to a `source_snapshot`, an `intent_hash`, an
`obligation_manifest_hash`, a `profile`, a toolchain digest set, and the exact
command, configuration, and seeds. A `fv-evidence-run/v3` record additionally
binds `intent_path` (the canonical target, repo-relative) and an `executions`
cohort. Any of these drifting makes the record stale. For a single component the
rule is: if the component's `source_snapshot` no longer matches the tree, its
records must be re-earned.

`source_snapshot` is a **verified-input content snapshot**: `sha256:<hex>` over
every candidate `git ls-files --cached --others --exclude-standard` reports that
the project's verified-input policy selects, hashed as path + NUL +
content-hash per input in sorted path order (CONCEPTS.md, "The verified-input
content snapshot"). The policy is `.fv/verified-inputs.txt`: an exclusion list
(the historical shape, and what a file carrying no `mode:` directive means) or a
`mode: include` allowlist that names the paths in scope, with nine structural
output exclusions applying in either mode. Five consequences for reuse:

- **Reuse is decided by content, not by commit identity.** A commit that
  rewrites history, a rebase, a fresh clone, or a second worktree does not
  invalidate anything as long as the verified inputs' bytes are unchanged.
  Conversely a purely uncommitted edit *does* invalidate, so a dirty tree cannot
  reuse evidence earned before the edit: the edit is already inside the hash.
- **A dirty-earned record is never reusable.** When git reports a verified
  input as modified, or when the snapshot / intent hash / manifest hash moves
  between two executions of one run, the producer records the snapshot as
  `sha256:<hex>+dirty` and the record's result is FAIL. A `+dirty` binding is
  therefore not a weaker PASS to reuse; it is an unusable record, and the run
  has to be repeated on a settled tree.
- **A reuse decision must read the binding mode, not the verdict word.** Gate B
  discloses its freshness discipline in the `binding` field of its report:
  `recomputed` means the verified-input snapshot and the intent hash were
  recomputed this run and matched, `pinned` means an operator-supplied
  `--expect-snapshot` / `--expect-intent` was compared instead, and `unbound`
  means `--allow-unbound` switched the comparison off. Only `recomputed` is
  evidence that the records still match the tree, so a pinned or unbound PASS is
  not a reuse license. The verdict token says so without reading the JSON: a
  recomputed run keeps the plain `VERIFIED[profile=...]` form, while a pinned or
  unbound run qualifies its scope
  (`VERIFIED[profile=...; binding=pinned]`, `VERIFIED[profile=...; binding=unbound]`).
  The coverage dashboard recomputes nothing and never qualifies its scope; its
  payload and `bindings:` summary line report `not-recomputed`, which is not a
  reuse license either.
- **The input policy is part of the binding's meaning.** FV's own generated
  output (`.fv/evidence/`, `.fv/verify/`, `.fv/panels/`, `.fv/changes/`,
  `.fv/attacks/`, `.fv/code-adversarial/`), quarantined pre-FV history
  (`.fv/history/`, `.colosseum/`), and a shadow migration's staging tree
  (`.fv/.migrate-staging/`) are the nine structural exclusions, applied in
  either policy mode whether or not a project file names them. So writing
  evidence never invalidates the evidence being written; writing the change
  record, attack log, or code-adversarial report that *describes* a verified
  state afterwards does not stale that state's evidence; migrated history never
  perturbs a fresh run; quarantining more legacy history later cannot
  retroactively stale a reusable record; and a migration interrupted mid-apply
  cannot stale one by leaving its staging directory behind. Everything else the
  policy says is a binding input. Adding an exclusion prefix changes which files
  the snapshot covers, which changes the snapshot: it is a binding change, and
  every record bound to the old input set is stale. Editing a `mode: include`
  allowlist is the same change from the other side, and it is self-announcing:
  the allowlist selects the policy file itself, so the edit is already inside
  the hash rather than silently re-scoping what the old evidence covers.
- **The snapshot is whole-tree, so per-component reuse needs the boundary.**
  One project-wide hash cannot say *which* component moved. That is exactly what
  decomposition supplies: the per-component source set below is what makes the
  snapshot's movement attributable, rather than invalidating every record in the
  system on any edit anywhere.

Decomposition (via `fv-boundary`) turns that per-component rule into a
bounded re-verification strategy for the whole system. When a system changes,
re-verify only:

1. **Every component whose own source changed.** Its `source_snapshot` binding is
   stale, so its records are stale, regardless of its neighbors.
2. **Every component that assumes (`A*`) a guarantee (`G*`) whose meaning
   changed.** A neighbor discharges the assumption; if that neighbor's guarantee
   is unchanged in effect, the assumption still holds and the assuming
   component's evidence is reusable. If the guarantee changed, the assumption is
   in question and the assuming component re-runs.

A component's evidence is **reusable across a system change** exactly when both
hold:

- its `source_snapshot` binding still matches the current tree for that
  component, and
- every `A*` clause it depends on is still discharged by an unchanged `G*` clause
  (or a still-waived `K*` trust assumption).

Everything else re-runs. The `ledger_schema_version` is checked first: a schema
migration invalidates the reuse computation itself (the record shape changed), so
a version bump forces a full re-verification pass regardless of source snapshots.

### System claim cohorts do not partially reuse

A `system_claim` obligation names a `depends_on` set of declared
invariants/witnesses and a `required_evidence` set of tool/layer IDs. It is
discharged by an **evidence cohort**: a v3 record whose `bindings.executions`
array carries one entry per command (tool, evidence class, argv, repo-relative
cwd, toolchain digests, raw-output path and hash, result, run ID). The claim
PASSes only when every `required_evidence` tool appears among PASS executions,
and the record itself PASSes only when every execution PASSed and every binding
held still across the whole run.

That conjunction fixes the reuse rule for system claims:

- **The cohort is the unit of reuse, not the execution.** A cohort record is
  reusable when its bindings still hold, and stale otherwise. There is no
  reusing the Quint execution while re-running the Kani one: the two shared one
  snapshot, one intent hash, and one manifest hash, and the record's verdict is
  the conjunction. Re-earning a system claim means re-running its whole cohort
  and writing a new record.
- **Any member's invalidation invalidates the claim.** A verified-input content
  change, a tool whose re-run now FAILs, a tool dropped from `required_evidence`
  coverage, or a `depends_on` obligation that lost its own evidence each take
  the claim out of PASS. The coverage dashboard distinguishes the shapes:
  `evidence-gap` (a required tool never PASSed, its cohort is absent, or some
  other execution in the cohort did not PASS) from `dependency-gap` (a fully
  PASSing cohort whose dependency is uncovered).
- **Reuse is per-artifact, so a re-run writes new artifacts.** Each execution
  commits to its own raw-output path and hash; two executions of a cohort may
  not cite one artifact, and no two claims may cite one either. Re-earning a
  claim therefore produces a fresh `.fv/evidence/raw/<claim_id>-<run_id>.log`
  per execution rather than re-pointing the old record at a shared log, and a
  reused record stays bound to the artifact bytes it was earned against.
- **A cross-component system claim is reusable only when every contributing
  component is.** The claim's inputs span components, so its cohort's
  whole-tree `source_snapshot` moves whenever any contributor's source moves.
  In blast-radius terms: a system claim re-runs whenever any component named in
  its `depends_on` closure re-runs, even when the component that changed is one
  its own guarantee does not mention. This is the cost of a claim no single tool
  makes; it is also why claims should be scoped to the components that actually
  compose, not to the whole system by default.
- **A manifest edit is a binding change.** `depends_on` and `required_evidence`
  live in the obligation manifest, so adding or removing either moves
  `obligation_manifest_hash` and stales every record bound to it — including the
  cohorts of claims the edit did not mention.

### Worked shape

Given components C1, C2, C3 with `G1(C1) ⟶ A1(C2)` and `G3(C3) ⟶ A2(C1)`:

- Edit only C3's internals, C3's guarantee `G3` unchanged in effect: re-verify C3
  (source changed); C1 reuses (its `A2` still discharged by an unchanged `G3`);
  C2 reuses (untouched). Blast radius: 1 of 3.
- Edit C1 in a way that changes `G1`: re-verify C1 (source changed) and C2 (its
  `A1` rests on the changed `G1`). C3 reuses. Blast radius: 2 of 3.
- Bump `ledger_schema_version`: re-verify all. Blast radius: 3 of 3.

The composition itself is recorded as a G1 record whose `required_targets` are the
boundary obligations (the `A*`-discharged-by-`G*` pairs), so the system verdict is
re-derivable from the reused component records plus the (possibly re-run) changed
ones, under the same G2 truth table.

## Non-Rust assurance tiers

The assurance profiles are contracts on evidence strength, not Rust bindings.
A component reaches a tier with whatever tool delivers that strength for its
language. The tiers are:

- **tested** — types plus lints plus property tests plus a fuzz surface, per the
  engineering floors (C8, `.fv/floors.json`).
- **bounded** — a bounded model check or bounded proof: the property holds up to
  a stated bound (depth, steps, input size), and the bound is named in scope.
- **proved** — an unbounded proof: the property holds for all inputs, discharged
  by a proof assistant or a refinement.

The tool that backs each tier is language-specific; the tier contract is not.
One non-Rust example, for a component written in a language checked by a
TLA+ / Apalache model and exercised by a fuzzer:

| Tier | Rust backing (reference) | Example non-Rust backing |
|------|--------------------------|--------------------------|
| tested | cargo test, proptest, cargo-fuzz | language test runner, a property-test library, a fuzzer (e.g. AFL, libFuzzer bindings) |
| bounded | Kani, Verus (bounded) | Apalache bounded check of a TLA+/Quint model; a bounded SMT harness |
| proved | Verus, Aeneas/Lean | a Lean/Isabelle/Coq proof; a refinement from spec to the component's implementation |

This is strategy, not a completed port: it states how a non-Rust component would
earn each tier and how its guarantee then discharges a neighbor's assumption. No
non-Rust component has been carried through the pyramid in this repository yet; a
cross-axis guarantee is labeled `conformance-tested` (G3) until a refinement
exists, exactly as for Rust.

## What is scaffolded versus run

Scaffolded here and in `fv-boundary` / `templates/system-intent.template.md`:
the boundary skill, the system-intent template, the ledger version field, the
reuse rule, and the tier mapping.

Not run: the bidboard system-of-intents verification, the actual non-Rust
component ports, and any refinement upgrading a `conformance-tested` boundary to
`REFINEMENT_VERIFIED`. Those are the M5 execution and M7 items; this document
exists so that run has a defined mechanism to follow, and claims no result from
it.
