---
name: fv-verify
description: Run the FV verification pyramid against a Rust crate. Executes layers in order from cheapest to most expensive (types → lints → property tests → fuzz → Kani → Verus → Aeneas/Lean), halts at first failure, routes failures to fv-failure-classifier, and persists a structured pyramid report under .fv/verify/. Use as the canonical verification entry point for any FV-managed Rust project.
---

## OMP deployment boundary

This skill executes in the current OMP session unless it explicitly delegates to a named FV agent. Skills and agents use separate registries.

Named agents resolve from this FV extension package. Invoke them only through OMP-native `task` or eval `agent()`. NEVER invoke OpenCode, Claude Code, or a single-shot model API.

Missing explicitly named agent? Stop and report an extension discovery defect. A self-executing skill does not imply a same-named agent.


You are orchestrating a full pyramid run of the FV verification pipeline. The pyramid principle: route every property to the cheapest tool that can verify it. Wide cheap base, narrow expensive top. Each layer's job is to either (a) verify what it can or (b) hand the unhandled remainder to the next layer.

You do not verify properties yourself. You run tools, capture results, and route failures. The verdict at each layer comes from the tool, not your interpretation.

## Assurance profiles and the run-level verdict (G2)

Every run names its **assurance profile** up front; the profile decides which layers are required and what the run-level verdict means:

- **`tested`** — types + lints + property tests + engineering baseline floors (C8) (+ fuzz when harnesses exist)
- **`bounded`** — `tested` + Kani (bounded proofs; bounds are part of the claim)
- **`proved`** — `bounded` + Verus + Aeneas/Lean (axiom-clean per the Layer 8 gate)

The run-level verdict follows the G2 truth table exactly: any required layer **failed** → run `FAILED`; otherwise any required layer skipped, not run, or without applicable evidence (e.g. zero Kani harnesses under `bounded`) → run `INCOMPLETE`; only when every required layer passed → `VERIFIED[<profile>]`. A skipped required layer is a gating gap, never a footnote — there is no "passed with gaps". `skipped` remains a visible bucket in the report; under the named profile it is also a gating one.

The deterministic layers (types, lints, property tests, fuzz, Kani, Verus) can run without an agent via the headless runner **`$FV_ROOT/scripts/pyramid_run.py --crate <path> --profile <name>`** (CI-friendly; exit 0 verified / 1 failed / 2 error / 3 incomplete). The agent flow remains responsible for failure classification and for the Aeneas/Lean layers.

## Verification plans are mandatory once they exist

A project declares its own layer commands in `<crate>/.fv/verification-plan.json` (schema `fv-verification-plan/v1`). That file is not optional configuration waiting to be pointed at: `pyramid_run.py` **auto-discovers it** and executes it whenever `--plan` is absent, and every report names where its commands came from in `plan.discovery` — `explicit`, `autodiscovered`, `absent`, or `disabled`.

- **A migrated project has a plan, so a plan run is the normal run.** `fv_migrate.py` writes one for every legacy harness it converts. Running such a project on the built-in defaults would report verification the project does not perform, so it cannot happen by omission.
- **A staged ledger is not a migrated project.** `fv_migrate.py --stage-ledger-remediation` exists for the project whose legacy ledger the current Gate A refuses: it copies `.colosseum/ledger.md` to a writable `.fv/ledger.md` and writes nothing else — no plan, no obligations manifest, no dispatch route, no history — is mutually exclusive with `--apply`, keeps `applied: false`, never overwrites an existing `.fv/ledger.md` (reported `identical` or `already-staged`), and never rewrites a citation; the repair is the operator's. A project in that state still has no `.fv/verification-plan.json`, so `plan.discovery` is `absent`, a pyramid run executes the built-in defaults, and those numbers do not stand in for the migrated project's declared layers. The operator edits `.fv/ledger.md` until the current Gate A accepts it, then re-runs the ordinary migration (dry run, then `--apply`), which adopts the edited live ledger, preserves the differing legacy ledger as history, translates an include entry naming `.colosseum/ledger.md` to bind `.fv/ledger.md`, and writes the plan this section assumes. Verify a migrated project after that run, not during staging.
- **Unusable means ERROR, never legacy.** A plan that is present but unreadable, malformed, or schema-invalid ends the run at `ERROR` (exit 2) before any layer executes; there is no fall back to the built-in layers. `fv_doctor.py` fails the same project on `project/verification-plan` rather than waiting for the next verification run to discover it.
- **`--plan <path>`** overrides discovery (one plan, explicitly chosen). **`--no-plan`** is the only escape hatch: a deliberate legacy run on the built-in defaults, recorded as `plan.discovery = "disabled"` with the ignored path named. Use it to compare a plan against the defaults, never to turn a red plan green.
- **Custom layers run.** A plan may name a layer the pyramid has no built-in default for (`quint`, `mutation`, `sanitizers`, ...). It executes after every known pyramid layer, in lexical order, with the same argv/cwd/timeout/env validation and the same report shape as a built-in layer; with `required: true` it joins the G2 gating set, which is how a tool outside the Rust pyramid becomes a gate. A plan can only tighten the verdict: `required: false` never un-requires a layer the profile already requires, and a plan naming a tool this machine lacks is a `failed` layer with a `launch_errors` row, not a skip.
- Layers the plan does not name keep their built-in defaults.

## Engineering baseline floors (C8)

Under `tested` (and therefore `bounded`/`proved`) the headless runner enforces a required **`floors`** layer: mechanical engineering-baseline checks so periphery coverage is visible rather than assumed. Floors are read from `<crate>/.fv/floors.json`; an absent or partial file falls back to documented defaults. The layer status rolls up per G2 (any failed sub-check gives `failed`; else any unmeasurable sub-check gives `skipped`/INCOMPLETE; else `passed`) and is written into the runner's JSON report (`layers.floors` plus a top-level `floors` summary) so ledger tooling can cite it.

`floors.json` (schema `fv-floors/v2`):

```json
{
  "schema": "fv-floors/v2",
  "features": {
    "matrix": [
      { "name": "default", "features": [], "no_default_features": false, "release": false },
      { "name": "no-std",  "features": ["alloc"], "no_default_features": true }
    ]
  },
  "property_tests": { "min_per_module": 1, "require_property_tests": false },
  "fuzz": { "surfaces": ["parse_header", "decode_frame"], "min_seconds": 30 }
}
```

Three mechanical sub-checks, with their defaults:

- **Feature matrix / workspace coverage.** Each declared combo runs `cargo check` with its `--features`, `--no-default-features`, and `--release` flags; `--workspace` is added when the crate root declares `[workspace]`. Any combo that fails to compile fails the layer. With no declared matrix the single default combo is already the `types` layer, so this sub-check is `not_applicable`, except that a workspace root still gets `cargo check --workspace`.
- **Property-test bar.** Every `src/**.rs` file exposing public API (`pub fn`/`struct`/`enum`/`trait`; `pub(crate)` is not public surface) must carry at least `min_per_module` in-file test functions. A test function is `#[test]`, or (when `require_property_tests` is true) only `proptest!`/`#[proptest]`/`quickcheck!`/`#[quickcheck]`. Files below the bar are listed by name. Per-file is a documented proxy for per-public-module: idiomatic Rust unit tests sit in an inline `#[cfg(test)] mod`, and attributing crate-wide tests to a specific module is not mechanically decidable. Defaults: `min_per_module` 1, `require_property_tests` false.
- **Fuzz-time floor.** Each parsing or deserialization surface named in `fuzz.surfaces` must have a `fuzz/fuzz_targets/<name>.rs` target (missing gives `failed`, a structural fact needing no cargo-fuzz), and the fuzz layer's recorded run duration must meet `min_seconds`. When cargo-fuzz is not installed the duration is unmeasurable, so this sub-check is `skipped` (INCOMPLETE), never a silent pass. Defaults: `surfaces` empty (`not_applicable`), `min_seconds` 30.

### Named higher tiers (documentation contracts, not yet mechanical)

Only the `floors` layer is enforced today. The tiers below are contracts a profile may claim; until each has a mechanical gate it must appear in the trust ledger as an explicit named assumption, never silently satisfied.

- **Sanitizers**: ASan/UBSan/TSan/MSan over the test and fuzz surfaces on a nightly toolchain, named per sanitizer with the covered target set.
- **Mutation testing**: `cargo-mutants` (or equivalent) with a minimum caught-mutant ratio per crate; the ratio and the surviving mutants are the evidence, not a single pass bit.
- **Unsafe / FFI review**: every `unsafe` block and FFI boundary carries a reviewed safety comment; the tier names the reviewer and the reviewed commit.
- **Non-Rust per-surface tiers**: each non-Rust component is an explicitly named axiom/tier with its own assurance, never silent trust. The Go gnark verifier and the frontends are the current examples; name the component, its tooling, and its evidence class (e.g. `externally-assumed` until a bridge exists) so no pyramid layer vouches for code it never touched.
- **CI self-test**: the regression suite plus the floors layer run in CI on every change, so the gate that enforces the floors is itself exercised.
- **Commit reconciliation**: each verified commit reconciles its recorded floors and evidence against the working tree, so a green run cannot drift from the code it claims to cover.

## Inputs

Ask the user for, or determine from context:

- **Crate path** — absolute path to the Rust crate root (directory containing `Cargo.toml`). Required.
- **Halt-on-failure mode** — default `true`. When `true`, the first failing layer stops the run and routes to the classifier. When `false`, all layers run regardless of failures, producing a comprehensive but slower report. Ask the user if not specified.
- **Layers to skip** — by default, all layers run. The user may exclude layers (e.g., "skip fuzz", "skip aeneas") if those tools aren't yet wired up for this project.
- **Lean extraction output directory** — for the Aeneas layer. Defaults to `<crate_path>/extracted-lean/`.

## The pyramid layers, in order

For each layer, you execute the tool, capture its result, and decide whether to advance or halt. Layer-level outcomes: `passed`, `failed`, `skipped`, `not_applicable`.

### Layer 1 — Types

Run `cargo check` from the crate root. Captures compilation errors and type errors. If this fails, no other layer is meaningful; halt regardless of halt-on-failure mode and classify.

### Layer 2 — Lints

Run `cargo clippy -- -D warnings` from the crate root. Treat warnings as failures by default; the user may downgrade to non-fatal warnings only on request.

### Layer 3 — Property tests

Run `cargo test` from the crate root. Captures behavioral failures from `proptest`, `quickcheck`, or hand-written tests. On `failed`: counterexamples come from the proptest output, not the classifier.

### Layer 4 — Fuzz (optional, off by default unless harnesses exist)

Check whether the crate has a `fuzz/` directory with `cargo-fuzz` harnesses. If so, run each harness for a short fixed duration (default 30 seconds per harness; ask user for the budget if running fuzz). Treat any panic/crash as a failure. If no fuzz harnesses exist, mark this layer `not_applicable` and proceed.

### Layer 5 — Kani

Invoke kani-mcp's `list_kani_harnesses` to inventory `#[kani::proof]` harnesses. For each, invoke `run_kani_harness` with the configured unwind bound. Mark `not_applicable` if no harnesses exist.

### Layer 6 — Verus

Invoke verus-mcp's `list_verus_annotations` to inventory Verus markers. If any are found, invoke `verify_verus_crate` against the crate. Mark `not_applicable` if no Verus annotations exist.

### Layer 7 — Aeneas extraction

Invoke aeneas-mcp's `extract_rust_to_lean(crate_path, output_dir)`. Extraction failure here is meaningful — it usually means the Rust code uses patterns Aeneas does not support. Route via classifier.

### Layer 8 — Lean theorem proving

Lean's build is proof-insensitive: a `sorry`-admitted theorem elaborates with exit 0 and only a warning, so a green build is NOT evidence that anything is proven. The gate is the axiom audit, run by the canonical tool `$FV_ROOT/scripts/lean_axiom_gate.py`:

1. **Build inside the Z2 environment.** Lean elaboration executes arbitrary metacode; building extracted or generated Lean output is code execution. Run this layer in the ephemeral worktree, never against a live tree with secrets in reach.
2. **Audit every in-scope theorem** (`#print axioms <name>`, via the gate script or `lean-lsp-mcp`'s `lean_verify`). Per-theorem outcome: proven only when the axiom set stays within the standard base (`Classical.choice`, `propext`, `Quot.sound`); any `sorryAx` means the theorem is admitted, not proven; axioms outside the base set count as visible assumptions and must be admitted explicitly (`--allow-axiom`) or the theorem is not proven.
3. **Layer verdict per G2**: `VERIFIED[axiom-clean]` only when the build succeeds AND every in-scope theorem audits clean; any sorry-admitted theorem makes the layer exactly `INCOMPLETE` (recorded as `failed` in the layer schema, never `passed`); build or audit errors are `FAILED`.

There is no text-scan fallback. Grepping source for `sorry` proves nothing (macros can hide admits, and absence of the string is not completeness); if there is no Lake project to build and audit, the layer is `failed` with reason `not-auditable`, not `passed`.

For each unproven theorem, the orchestrating agent — not this skill — is responsible for tactic-proposal loops with goedel-mcp. This skill's role is reporting the per-theorem audit table (the gate's JSON record goes in `structured_summary`) and surfacing what remains.

## Per-layer result schema

For each layer, record a structured entry:

```json
{
  "layer": "<layer name>",
  "tool": "<tool invoked>",
  "status": "passed|failed|skipped|not_applicable",
  "duration_s": <float>,
  "details": {
    "command": [...],
    "returncode": <int>,
    "stdout_preview": "<first ~500 chars>",
    "stderr_preview": "<first ~500 chars>",
    "structured_summary": <tool-specific dict, when available>
  },
  "classification": <null until failure>,
  "classification_path": <path to classifier report when failure>
}
```

## On failure

When a layer fails:

1. Record the layer's result entry with `status: "failed"`
2. Invoke the `fv-failure-classifier` subagent with:
   - The full failure output (stdout, stderr, structured summary)
   - The spec artifact relevant to this layer (the Kani harness, the Verus-annotated source, the property test, the Lean theorem, etc.)
   - The Rust source under verification
   - The intent document (check `<crate_path>/.fv/intent.md` first — canonical per CONCEPTS "Project layout" — then `<crate_path>/intent.md`, then ask the user)
3. Persist the classifier's report to `.fv/classifications/<layer>-<ISO-timestamp>.md`
4. Attach the classification path to the layer's result entry
5. If halt-on-failure: stop and produce the final pyramid report
6. If not halt-on-failure: continue to the next layer with this failure recorded

## Persistence

Operators MUST produce G1 PASS candidates with `fv_evidence_run`. Gate B recomputes the raw artifact hash and validates exit, class marker, source, intent, and manifest bindings. The producer/operator remains a stated trust boundary; this milestone does not cryptographically authenticate record authorship.

Save the full pyramid run to `<crate_path>/.fv/verify/<ISO-timestamp>.md`. Format:

```markdown
# FV verification pyramid run

- Crate: <absolute path>
- Started: <ISO timestamp>
- Completed: <ISO timestamp>
- Halt-on-failure: <true/false>
- Layers excluded: <list or "none">

## Per-layer results

| # | Layer | Status | Duration | Details |
|---|-------|--------|----------|---------|
| 1 | Types | <status> | <s> | <link or summary> |
| 2 | Lints | <status> | <s> | <link or summary> |
| ... |

## Failure classifications

<for each failed layer, embed or link the classifier's report>

## Coverage snapshot

- Layers passed: N
- Layers failed: M
- Layers skipped: K
- Layers not_applicable: L

## Suggested next action

<one of: address critical failures in layer X / proceed to proof-writing for unproven theorems / extend Verus annotations to cover gap Y / write Kani harnesses for boundary cases Z>
```

## Summarize for the user

After persisting, report:

- One-line summary: `Pyramid: <P passed> / <F failed> / <S skipped> / <NA not_applicable>`
- For each failure: layer name, classification, classifier-recommended action
- Absolute path to the full pyramid report
- One concrete suggested next step

## What you do not do

- You do not run all layers if one of the foundational layers (types, lints) failed and halt-on-failure is true. Compilation failure invalidates everything downstream.
- You do not interpret layer results yourself when they fail. Route to `fv-failure-classifier`. That subagent's classification is the answer.
- You do not skip the classifier even when the failure seems "obviously" a particular category. The whole point of the classifier is consistent, evidence-grounded routing.
- You do not modify the crate's source code. This skill is read-and-verify only.
- You do not advance past a failing layer when halt-on-failure is true, even if the failure seems unrelated to subsequent layers.

## Tool availability handling

Before running the pyramid, check that the tools each layer needs are available:

- Layer 1, 2, 3, 4: `cargo` (assume present in any Rust project context)
- Layer 5: kani-mcp's `check_kani_health()` → `ok: true`
- Layer 6: verus-mcp's `check_verus_health()` → `ok: true`
- Layer 7: aeneas-mcp's `check_aeneas_health()` → `ok: true`
- Layer 8: `lean` and `lake` on PATH (the axiom gate shells out to them); `lean-lsp-mcp` registered for interactive proof work

If a tool needed by a non-excluded layer is unavailable, mark the layer `skipped` with reason "tool unavailable" and proceed. Surface this in the summary as a coverage gap.

## Spirit

The pyramid only earns its keep when it's run consistently. Ad-hoc verification — "I ran Kani that one time" — drifts. This skill is the canonical run. Use it as a precommit gate, a CI step, or a manual checkpoint, but use it the same way each time so coverage and confidence move together.
