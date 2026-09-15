# Roadmap: status and remaining work

Last updated: 2026-09-15. This is the handoff document. It records where the
2026-07-11 remediation plan of record stands, what remains before the repo may
call itself dependable by its own exit criteria, and who each remaining item
waits on. A new maintainer or session should be able to resume from this file
alone.

## Where things stand

All in-repo phases of the remediation plan are implemented, tested, and
committed on `main`, one commit per item:

| Phase | Items | State |
|---|---|---|
| Phase 0 (containment) | Z1-Z4: deny-first dispatch profiles, worktree + preflight isolation, injection containment, adjudication guard | done |
| P0 (evidence honesty) | E1-E7: Quint/Lean evidence classes, dispatch fail-closed, manifest concurrency, obligation quality, CLI/packaging contracts | done |
| P1 (mechanisms) | C1-C10: two-gate ledger (G1/G2), conformance bridge (G3), critique loop (G4), voice registry, MCP hardening, skill sweep, intent template, baseline floors, dogfood evidence, repository CI | done |
| P2 instruments | M1 coverage dashboard, M2 self-measurement, M3 recall scorer + pre-registered benchmark protocol, M5 boundary skill / system-intent / ledger versioning | done |
| M3 live calibration | `calibration/2026-07-13-r1`: blinded seeded-defect run, six scoreable voices | done |
| OMP-native integration | ModelRegistry-backed adversary fan-out, generated routes, fail-closed session-root gate, live-tree preflight, process-local fallback suppression, failure-isolated evidence, initializer/doctor support (R29/R30/R33) | implemented on `feature/omp-integration`; the canonical 4-voice run is recorded at `calibration/2026-07-28-r3/`. Native calibration remains pending at the route level: one voice is attested and cited; two are unattested and one degraded. |
| OMP-native deliberation panel | Three-wave `fv-panel` skill (drafts → blinded cross-review → synthesis): family/coverage quorum, randomized-label blinding + deferred identity, brief + git target-drift gating (binary-safe, full-digest, `.fv`-excluded), harness-aware doctor, `project-plan` + `milestone-review` modes (R31, ~50 assertions incl. a real Gate B end-to-end; R32 resolver dispatch-identity contract executed under Bun) | committed on `feature/omp-integration`; **`project-plan` live-verified** project-rooted (`calibration/2026-07-23-omp-panel-e2e/`, 3-family COMPLETE) but uncalibrated; **`milestone-review` EXPERIMENTAL** — evidence-bound fail-closed guard + Gate B `--expect-intent`/`--snapshot-exact`/dup-rejection are correct and deterministically tested, but not yet run against a real project's itf_replay G1 records + live panel; roster-resolver extension live-verified in a real OMP session (`calibration/2026-07-24-resolver-live/`: `ctx.models.family` distinctness positive + negative, canonical `provider/id` dispatch identity, both active seats serving real inference at `:max`); active roster is Sol+GLM (min_families=2) with Fable/Kimi-k3 pending; full three-wave run on that roster and calibration pending |
| Migration readiness | Canonical `target_spec` resolution, verified-input content snapshots, Gate A citation grammar, `system_claims` + evidence cohorts, configurable/custom verification layers, non-destructive `.colosseum` shadow migration with quarantined legacy evidence | delivered 2026-09-15 (`f2d0556`, `9eb3709`, `b1003a3`, `8508604`, `5dc765e`, `d5ce1c2`); code-adversarial pass and closure reviews complete; local and Gula CI PASS; real dossier dry run PASS with 0 unsupported/conflicts and unchanged `.colosseum`; no shadow state applied |

Gate: `./scripts/ci.py` validates frontmatter, agent policy, roster drift,
documentation links, dispatch configuration, fixture tracking, and the full
regression suite. OMP-native dispatch uses structured `agent()` calls and
extension custom tools; retired subprocess-runner behavior remains only in
historical calibration artifacts.

The default adversarial panel is pinned as
`canonical-4@sha256:0f73580ef4e3fdf2`: `claude-agent` (Fable 5, or the
strongest available Opus when Fable is absent), `gpt-5.6-sol`, `glm-5.2`, and
`kimi-k3`. Each seat has its own cited reference-transport calibration.
`registry/voices.json` is the source of truth; roster docs are generated from it
by `scripts/gen_roster_docs.py`.

OMP has a native multi-voice transport through its eval `agent()` bridge. The
exact ModelRegistry routes and their content hash are generated into
`.fv/dispatch.json`; the `fv-adversarial` skill preflights the
live tree, binds the target hash, runs bounded adversary agents, and preserves
partial evidence. Native dispatch validates the OMP session root and records
filesystem isolation as unverified because subagent filesystems are not confined.

The four-voice native run at `calibration/2026-07-28-r3/` produced usable
outputs, but it did not validate the whole native route. Its registry grades are
machine-readable: `kimi-k3` is `attested` and carries its native citation;
`claude-agent` and `gpt-5.6-sol` are `unattested`; `glm-5.2` is `degraded`.
The generated profile therefore remains `calibration: "pending"`. Native
calibration never inherits the reference OMP or Claude Code claim.

Future calibration runs must use `scripts/omp_calibration_session.py`. It
appends a process-local `retry.fallbackChains` suppression overlay to any caller
`PI_CONFIG_FILES`, prechecks the effective OMP configuration, archives the
overlay, precheck, and launch record, then passes the same overlay to OMP. A
successful precheck prevents retry fallback for the selected routes before any
model call, making the route condition decidable without mutating user or
project settings.

## Exit criteria scoreboard

The plan of record's "dependable" gate has ten criteria. Current state:

| # | Criterion | State |
|---|---|---|
| 1 | No control-plane path succeeds with zero valid evidence | satisfied (R1-R6, R20) |
| 2 | Obligations have stable IDs + typed G1 records; manifests frozen | satisfied (R9, R19, R27) |
| 3 | Evidence bound to snapshot/intent/manifest/tools/seeds/hashes | satisfied (R27) |
| 4 | Lean and Quint evidence classes honest | satisfied (R7, R8) |
| 5 | Least-privilege external-model execution + injection fixtures | satisfied (R10-R12; deny-first confirmed live) |
| 6 | Cross-axis claims labeled conformance-tested until refinement exists | satisfied (R24; R26's scoped-verdict half is asserted only where a verdict is observable — see "Test-quality cleanup" below — and no repo-wide label sweep guards a future emitter) |
| 7 | Critique loop exercised once on a REAL contested finding, recorded per G4 | satisfied (`dogfood/jobq-2026-07-13/ADJUDICATION.md`: panel attack on jobq; F2 finite-arithmetic gap retained OPEN under G4, corroborated by the W5 Aeneas proof) |
| 8 | Skills/agents/wrappers pass pinned validators | satisfied (R13) |
| 9 | Known-good reference project passes; known-bad variants fail at intended gates | satisfied (R22, `tests/fixtures/r22/` jobq project + `tests/r22_reference_project.py`) |
| 10 | Prospective benchmark shows benefit at reported cost; independent replication | half-open — the benchmark RAN 2026-07-14 (`calibration/2026-07-14-bench1/RESULTS.md`) and the published result is NEGATIVE: no arm beat single-voice recall on the two-crate corpus, so the "shows benefit" clause is currently unmet on the evidence; independent replication still needed |

## Remaining work

### W1. R22 reference project — DONE 2026-07-13

`tests/fixtures/r22/`: the `jobq` crate (single-worker queue, bounded
retries) with INTENT.md, Quint spec, obligations manifest, floors,
hash-bound ledger, and a conformance adapter that path-depends on the real
library. Verified live at authoring time: 6 tests, clippy clean, Apalache
depth-12 on B1-B4, W1 witness trace, 5/5 conformance traces, kani bounded
proof, `VERIFIED[tested]` and `VERIFIED[bounded]`. `tests/r22_reference_project.py`
runs the good project through every gate and six known-bad mutations that
each fail at exactly their intended gate while another stays green. Still
useful as: the W2 benchmark target, the W5 proof target, and the place to
exercise criterion 7's real contested finding (panel attack on the intent
has NOT been run yet; only the mechanical gates have).

### W2. M3 prospective benchmark (owner: maintainer/agent; API cost)

The pre-registered design is `docs/benchmark-protocol.md`; the instrument is
`scripts/recall_score.py`; the worked example is `calibration/2026-07-13-r1`.
Needs, in order:

1. A fresh held-out seeded corpus. The r1 corpus is burned by publication and
   was too easy (three of four scoreable voices ceilinged at 8/8). The next
   corpus must discriminate: cross-file interactions, concurrency, spec-level
   omissions, symptom far from root cause. Multiple targets preferred.
   Stronger design: a second party authors the corpus so the orchestrator is
   also blind (pairs with W4).
2. The five arms run blinded over it: ordinary review, single model, repeated
   same-model, multi-family panel, adversarial panel with critique loop.
3. Results published with negative results and cost accounting, per protocol.

DONE 2026-07-14: all five arms ran over the held-out two-crate corpus and
the results are published at `calibration/2026-07-14-bench1/RESULTS.md`,
definition-of-done met including its hardest clause: the published headline
is the arm where the panel failed to beat the baseline (every arm scored
0.8 union on beta and 1.0 on alpha; the panel bought zero recall at 3-6x
dispatch cost; the one reentrancy defect was a universal blind spot).
Remaining for a stronger W2 iteration, not blockers: a second-party
corpus (pairs with W4), larger targets, reentrancy-weighted defect
classes, and a token-accounting dispatch path.

### W3. M4 panel optimization (owner: maintainer/agent; blocked on W2)

No new machinery. Recompose the panel strictly from W2's per-voice
recall/diversity/cost data. Any membership change moves the profile
content-hash; prior panels stay pinnable.

### W4. M6 independent replication (owner: user + external party)

The gate for "validated" returning to the README. Needs:

1. DONE 2026-07-14: `main` is pushed to the repository remote and
   CI is green there, so a replicator's fresh clone matches what local CI
   gates (two broken-clone bugs found and fixed on the way; see the CI
   section).
2. An independent person/team who follows INSTALL.md + QUICKSTART.md on their
   machine (`fv_doctor` validates their environment), runs the workflow
   on a target, and returns their evidence trail.
3. Optional but recommended: they author the W2 corpus, closing the
   orchestrator-blindness gap.

The replication protocol exists at `docs/replication-protocol.md` — what to
run, what to return, and how results get recorded
(`replications/<date>-<party>/`, manifest conventions, and the
"validated" gate as a conjunction of a merged replication and published
benchmark results).

### W5. M7 refinement proofs — refinement PROVED 2026-07-14; emission gated

Feasibility spike DONE 2026-07-13, refinement proof DONE 2026-07-14
(`docs/m7-feasibility.md` narrative, `spikes/2026-07-13-m7-aeneas/` Lean
source + repro; heavy build outputs held outside the repo, paths in the
`m7-aeneas-toolchain` memory). jobq extracts to Lean with zero crate
changes (Charon + Aeneas) and `JobqRefinement.lean` now PROVES the
extracted model refines the strengthened Quint transition relation,
forward direction, at CAPACITY=2: 18 theorems, sorry-free, standard axioms
only (`[propext, Classical.choice, Quot.sound]`, independently
re-verified). The five spec invariants are proved inductive over the
transcribed `QStep`, `R` is the `U32.val`-as-Int simulation relation, and
per-action forward-simulation lemmas give `rust_refines_spec` so
`rust_b1..b4` transfer to every reachable extracted state
(`NonVacuity.lean` rules out vacuity). The finite-arithmetic gap (F2) is
carried as scope, not resolved: lemmas are ok-conditioned via
`UScalar.add_equiv`/`sub_equiv`, so totality at u32::MAX is not claimed
(F2 stays OPEN).

What remains before `REFINEMENT_VERIFIED` is ever emitted: (1) a
Quint-line citation gate binding each action definition in
`JobqRefinement.lean` to the action's line range in `jobq.qnt`, so the
hand-written transcription cannot drift from the spec silently — this is
the blocker; (2) the label, when built, must be scoped, e.g.
`REFINEMENT_VERIFIED[forward, CAPACITY=2, ok-conditioned, finite-arith
excluded per F2]`, never bare (G3, R26). Optional extensions: two-sided
refinement (reverse simulation + guard alignment, ~10 lemmas), other
capacities, and resolving F2 with checked-arithmetic Quint modeling. The
doctor still reports Verus not installed; install it if the Verus layer
should participate.

### W6. Housekeeping (owner: user unless noted)

- `gpt-5.6-pro`: blocked by an account-level error at dispatch ("not supported
  when using Codex with a ChatGPT account"). When the account is fixed, one
  dispatch + score calibrates it (agent).
- `deepseek-v4-flash`: requires the local ds4 endpoint (DwarfStar4 at
  `http://127.0.0.1:8000`) to be running; then calibrate on the W2 corpus.
- `gemini-3.1-pro-preview`: requires `GOOGLE_GENERATIVE_AI_API_KEY` (or an
  omp Google credential); then calibrate on the W2 corpus.
- `fv_doctor` OAuth false-warn: FIXED 2026-07-13 (checks all three
  omp credential paths, not just env vars).
- Push `main`: DONE 2026-07-14 (repository remote). The
  `scratchpad/` private review narrative is gitignored so a stray
  `git add -A` can never sweep it into a push.

### jobq spec strengthening — DONE 2026-07-14 except F2 (commit 61e6588)

The 2026-07-13 panel attack on the R22 fixture
(`dogfood/jobq-2026-07-13/ADJUDICATION.md`) found real spec-quality gaps in
our own reference project; the dogfood loop closed by fixing them (INTENT
v1.1, `specs/jobq.qnt`, obligations B5/W2, rebound ledger, adapter, R22
suite):
- F1: `inv_b3` is now the biconditional (idle => attempts 0, running =>
  1..MAX) plus `inv_nonneg`, so the invariant set stands alone;
- F3+F6: `CAPACITY` parameterized (`jobqP` module), verified at 2 and 4,
  default 2 made distinct from MAX_ATTEMPTS 3; both former mutants
  (constant swap, capacity pin) now produce counterexamples;
- F4: terminal monotonicity encoded with ghost prev-counters as required
  target B5; the `clawback` mutant now fails verify;
- F7: failure-path witness W2 (`witness_b1_failed`) added as an obligation;
- F5: INTENT K3 scopes error VALUES out of replay conformance (rejection is
  modeled as action absence; error enums are unit-tested and ledger-cited);
- F8 (process): panel attack copies must carry the full project.
- **F2 remains OPEN**, by design, as the recorded contested finding (Quint
  proves conservation over unbounded int; the code is u32). Resolving it
  needs either checked-arithmetic Quint modeling or a justified
  submission-bound trust assumption, plus new evidence, not a vote.

Also fixed in the same push (c363545): a latent broken-clone bug the
strengthening surfaced. The global `.fv/` gitignore had hidden every
fixture manifest (r22 obligations/ledger/floors, four r28 floors.json) from
git, so local CI passed while fresh clones failed r22/r28. Negated the
ignore for `tests/fixtures/`, tracked the seven manifests, and added a
`fixture-tracking` CI check (verified by cloning fresh and running r22
green off the clone) so an untracked fixture can never ship a broken clone
again.

### GitHub Actions CI — green since 2026-07-14 (commits 4de698d, 82477ae)

The `fv-ci` workflow had failed on every push since it was added on
2026-07-12: four suites hard-failed on the toolchain-less runner instead of
degrading to the INCOMPLETE the workflow was designed to tolerate. Local
`ci.py` never saw it because this machine has the tools. Fixes:

- `m3b`: stub invoked via `sys.executable` instead of a bare `python3` that
  `uv run` on a bare runner may not expose; a missing summary degrades to
  SKIP instead of a traceback.
- `r16/r17/r18`: probe for `cargo-kani` itself, not plain `cargo` (stock
  runners ship cargo without kani).

Getting past those exposed a SECOND broken-clone bug of the c363545 class:
`tests/fixtures/m3b/target` (a review-TARGET fixture, not a build dir) was
swallowed by the global Rust `target/` ignore, so fresh clones had no
benchmark target. The fixture is now tracked, and the fixture-tracking
check was replaced by `scripts/check_fixture_tracking.py` (self-tested),
which also flags ignore-HIDDEN fixtures — the blind spot both clone bugs
shared, since `git ls-files --others --exclude-standard` never lists
ignored files. Real build/run artifacts (a `target/` next to a Cargo.toml,
`.fv/verify/`) stay tolerated. Verified off a fresh clone and on
the live runner; both workflow jobs green.

### Migration readiness — DELIVERED 2026-09-15 (commits f2d0556, 9eb3709, b1003a3)

Authority for this work is the user-authorized migration requirements given in
the session that produced these commits, not an intent revision: this repository
declares no `.fv/intent.md`. Those requirements are restated in the committed
change record `.fv/changes/2026-09-15-colosseum-shadow-migration.md`, which is
the durable statement `f2d0556`, `9eb3709`, and `b1003a3` were checked against.

Delivered:

- **Canonical target.** `.fv/dispatch.json` → `omp_native.target_spec` is the
  one intent/target declaration, resolved against the project root by
  `scripts/fv_project.py` (`resolve_target`). Missing spec defaults to
  `.fv/intent.md`; an absolute spec is valid only inside the project root; a
  missing, directory, symlink, or escaping target is an error. The initializer
  writes `project_root: "."` and a repo-relative spec. The old "root
  `intent.md` as recognized alternative" fallback is gone — declare it.
- **Verified-input content snapshot.** `.fv/verified-inputs.txt` is an
  exclusion-prefix list over `git ls-files --cached --others
  --exclude-standard`; the snapshot is `sha256:<hex>` over sorted
  path + NUL + content-hash lines. `.fv/evidence/`, `.fv/verify/`,
  `.fv/panels/`, `.fv/history/`, `.fv/.migrate-staging/`, and `.colosseum/`
  are structural defaults in `fv_project.DEFAULT_EXCLUSIONS`, mirrored in
  `tools/evidence-run.ts`, that no project file can drop; a non-regular
  verified input is classified instead of
  opened, and a list whose line terminators the Python and TypeScript parsers
  would read differently is rejected on both ends. `tools/evidence-run.ts`
  recomputes the snapshot (plus the intent and manifest hashes) before the
  toolchain probes and around every execution; Gate B recomputes and demands
  an exact match unless `--expect-snapshot` / `--expect-intent` /
  `--allow-unbound` are passed, and discloses which discipline ran in the
  verdict scope as `binding=recomputed|pinned|unbound`. A `+dirty` snapshot
  cannot PASS in any comparison mode. Evidence no longer binds to a commit id
  plus a dirty flag.
- **Gate A citation grammar.** `scripts/check_ledger_references.py` parses four
  citation forms explicitly instead of one ambiguous alternation: a `code:`
  value that looks like a citation but does not parse now fails loudly, a
  broken `@sha256:` binding is drift rather than prose, and `**Depends on:**` /
  `### Depends on:` blocks are recognized, so per-link Kani coverage fires on
  real ledgers it previously skipped entirely. A `kani:` body is parsed
  against a grammar rather than searched for as a substring — any
  identifier-shaped harness name, a `path:line` locator, or
  `skipped because <reason>` with a reviewable reason. A bare identifier is a
  valid harness name, so the closed `NON_HARNESS_TOKENS` list — matched
  case-folded with surrounding `_` stripped, catching `NOT_APPLICABLE` and
  `_none_` alike — is the whole defence against a placeholder, and an
  identifier-shaped one is rejected by name (`'<tok>' is a placeholder, not a
  harness name`) while a non-identifier body such as `n/a` or `-` gets the
  generic rejection. A bare `kani: skipped` is not coverage either, and two
  separate guards keep the marker honest: a negative lookbehind for
  `barkani:` and `(?!:)` for `kani::proof`, the second being what leaves the
  Rust attribute path citable by name. A `Depends on:` block ends at a blank
  line, a heading, a further
  `Depends on:` header, or any non-entry line, so an unrelated later bullet
  list is no longer counted as a trust-chain link. Across a blank line only a
  list indented deeper than the header continues the block; a bullet at the
  header's own indentation after a blank line is deliberately not readmitted,
  because that shape is exactly the unrelated prose bullet the old latch
  miscounted. The residual is fail-open and recorded as a contract choice
  rather than guessed at: a ledger that means to continue a link list indents
  its entries under the header, which is what `fv-compose` Step 3 prescribes.
- **System claims and evidence cohorts.** `obligations.json` accepts
  `system_claims` (`depends_on` over declared obligations, `required_evidence`
  over tool IDs). `fv-evidence-run/v3` adds `intent_path` and a nonempty
  `executions` array; a cohort's verdict is atomic — every execution PASSes and
  every binding holds still, or the record is FAIL. The obligation/class
  compatibility table and the unwaived-assumption rule quantify over the whole
  cohort, and one raw artifact discharges exactly one execution of one claim.
  A system claim PASSes only when every required tool appears among PASS
  executions, and judging one through `--require` pulls its `depends_on`
  obligations into the required set; `coverage_dashboard.py` distinguishes
  `evidence-gap` from `dependency-gap` and applies Gate B's own v3 cohort
  schema, so the two tools cannot disagree about which records are valid.
  v2 records remain accepted.
- **Configurable and custom verification layers.** `pyramid_run.py --plan`
  reads `fv-verification-plan/v1`: per-layer `required` plus argv/cwd/timeout/env
  executions, no shell strings, escapes and ambient env mutation rejected.
  Non-reserved layer ids are accepted as custom layers, run after the known
  `LAYER_ORDER` in lexical order, join `required_layers` when `required: true`,
  and go `not_run` under a types failure like any other layer. A malformed plan
  is exit 2 before any layer runs, and an execution naming an absent
  executable is a recorded `failed` layer with a `launch_error` rather than a
  traceback that suppresses the whole report.
- **Portability.** Target declarations, execution `cwd`s, and `intent_path`
  are repo-relative and containment-checked; evidence binds to content, not to
  a commit. A record earned in one clone is checkable in another with the same
  content, and absolute paths cannot leak into a persisted trust artifact.
- **Shadow migration.** `scripts/fv_migrate.py PROJECT [--apply] [--json]`
  defaults to dry run, writes only under `.fv/` on `--apply`, and leaves
  `.colosseum/` byte-identical. Ledger, intent (including an external canonical
  intent reached through a legacy pointer stub), joined
  `obligations.json` + `g1-claims.json` → `system_claims`, and recorded layer
  runs → a verification plan are mapped; everything else is preserved history;
  anything untranslatable is `unsupported` and blocks the run before any write.
  A legacy layer named in a `system_claim.required_evidence` — `quint` included
  — migrates as a custom layer rather than being dropped. Obligation and claim
  ids are normalized deterministically (`quint:invS7` to `quint.invS7`) so every
  migrated id is directly usable as an `fv_evidence_run` `claim_id`, each
  rewritten obligation carries `legacy_id` for traceability, and colliding or
  empty normalized ids block the run instead of being suffixed apart. The
  dispatch target is elected from the legacy pointer stub first and the
  ledger's citations only second — never by frequency of mention in legacy
  prose — with two or more surviving candidates, or none, blocking; the
  elected `target_spec` is a top-level report field. `--apply` stages every
  write under `.fv/.migrate-staging/<pid>-<random>/` and then moves each into
  place, moving an existing destination aside into the same staging tree so a
  rollback renames its own inode back with mode, ownership and timestamps
  intact, rolling back what
  already moved if one fails, refuses a destination path that crosses a
  symlink at any component (`.fv` itself included) or an unwritable
  destination directory, and prints the report even on failure with each
  write's action (`written`, `rolled-back`, `failed`, `lost`, `pending`), where
  `lost` is a destination whose original could not be renamed back.
  `.fv/dispatch.json` is adopted rather than refused: an existing route keeps
  every field except the `project_root` and `target_spec` the migration owns.
  A claim key with no typed slot survives under `legacy_fields` and is named
  in a deviation row, an evidence tool no migrated execution can produce is
  `unsupported`, and a layer any migrated claim names is written
  `required: true`. That completeness check is intentionally blocking in the
  degenerate case too: a legacy tree with claims but no recorded
  `evidence/runs/layer-runs.json` declares no executions at all, so its
  claims name evidence the plan cannot produce and the migration refuses
  until the runs are recorded or the claims stop naming unrunnable layers.
  A migrated manifest whose claims can never be discharged would read as
  "evidence missing" forever instead of "never runnable here". `--apply` is
  byte-idempotent; `--json` emits a
  deterministic `fv-migration-report/v1` naming the requested mode and
  whether it applied.
- **Old-evidence quarantine.** Legacy `.colosseum/evidence/` records are never
  copied into `.fv/evidence/`: a v1/v2 record cannot satisfy v3 bindings, so it
  is preserved byte-for-byte under `.fv/history/colosseum/` and classified
  `preserved-history`. `.fv/history/` and the migrator's staging prefix
  `.fv/.migrate-staging/` are both structural default exclusions in
  `fv_project.DEFAULT_EXCLUSIONS` and its `tools/evidence-run.ts` mirror, so
  neither quarantined history nor a staging tree can perturb fresh evidence,
  even after `fv_init --force` rewrites the project's exclusion file. A
  migration killed outright strands one
  `.fv/.migrate-staging/<pid>-<random>/` directory, and a rollback that could
  not put a destination back keeps its own deliberately, since the aside-moved
  original inode is then the only copy of the replaced bytes and the error
  names the retained directory. Either residue is snapshot-excluded, cannot
  collide with a later run, and is safe to delete once accounted for. Nothing
  sweeps it, deliberately: no later run can distinguish a dead staging tree
  from a live migration's, or from a rollback's surviving originals. The legacy
  *include*-shaped `verified-inputs.txt` is preserved as history rather than
  inverted, and FV's conservative exclusion defaults are written instead.

Focused verification (orchestrator-run, all PASS; enumerated per phase in the
change record): `py_compile` over changed Python modules plus
`r1_r21_r27_ledger_gates`, `r2_r5_concurrency_containment`,
`r6_manifest_failclosed`, `r29_omp_integration`, `r30_omp_native_dispatch`,
`r31_omp_panel`, `r34_evidence_run`, `m1_coverage`, `r14_cli_contracts`,
`r28_baseline_floors`, `r20_verdict_truth_table`, `r35_colosseum_migration`,
`r36_dossier_rehearsal`, with `git diff --check` clean.

Test-quality cleanup in the same set: `r24_r26_conformance` drops its three
R26 label-sweep checks, which grepped `scripts/*.py` and the doc sources for
`REFINEMENT_VERIFIED` and for an unscoped `VERIFIED`. A banned-substring scan
over source text is not the contract — a docstring or a comment trips it and a
renamed emitter evades it — so it is not restored in any form. What is asserted
instead is every place a verdict is actually observable: `r24_r26_conformance`
still checks that a conformance scope survives Gate B aggregation (the JSON
verdict starts `VERIFIED[` and the per-claim scope carries the replay
parameters); `r1_r21_r27_ledger_gates` checks that Gate B emits
`VERIFIED[profile=...; binding=unbound]` and never a bare `VERDICT: VERIFIED`;
`r6_manifest_failclosed` checks that `recomputed`, `pinned`, and `unbound` are
each disclosed in the scope; `m1_coverage` pins the dashboard's exact scope, exercises
the bare-versus-scoped token discipline, and runs the dashboard's `--check`
self-scan over a repository-shaped fixture; and `coverage_dashboard.py --check`
scans its own table, banner, and JSON payload for an unscoped verdict. The gap this leaves is stated rather than papered
over: no check now watches a *new* emitter anywhere in the repository, so a
future script printing a bare `VERIFIED` or an unscoped `REFINEMENT_VERIFIED`
would be caught by review, not by a test. R24's conformance-bridge assertions
are unchanged.

The code-adversarial pass is complete: `.fv/code-adversarial/2026-09-15-evidence-architecture.json`
(17 findings: 1 HIGH, 4 MEDIUM, 1 MEDIUM-LOW, 1 LOW-MEDIUM, 8 LOW, 2 INFO) and
`.fv/code-adversarial/2026-09-15-shadow-migration.json` (15 findings: 2 high,
2 medium-high, 6 medium, 3 low-medium, 2 low). All 32 findings have corrections
in the current **uncommitted** set across `check_evidence_records.py`,
`coverage_dashboard.py`, `fv_project.py`, `fv_migrate.py`, `pyramid_run.py`,
`check_ledger_references.py`, `tools/evidence-run.ts`, and their suites; the
two documentation findings (a status string spelled `coverage-gap` in four
documents the dashboard has always emitted as `evidence-gap`, and stale line
citations in the change record) are fixed where they live, and the citations
are now symbol names so a later refactor cannot silently invalidate them.

Those corrections were then re-reviewed by two further read-only operators,
neither the author of the corrections. The migration surface came back
**15/15 original findings resolved**, with five observations recorded rather
than hidden: the `Depends on:` loose-list residue above, the
claims-without-a-run-manifest block above, a single-identifier Kani harness
name the grammar now accepts, rollback restoring a pre-existing destination's
bytes but not its mode, and the staging-directory residue above. The last two
of those are closed in the final wave — rollback now moves the original aside
into the staging tree, so putting it back is a rename of its own inode and
carries mode, ownership and timestamps with it, and `.fv/.migrate-staging/`
became a structural snapshot exclusion. The evidence surface came back with
ten findings resolved on both the producer and the consumer, and five resolved
on one side only; those residues were assigned to the same wave: Gate B rules
the coverage dashboard did not mirror (the `+dirty` PASS rejection and
cross-claim artifact identity), a manifest-id fidelity divergence where the
two tools disagreed on the exit code for a manifest Gate B rejects, and a
UTF-8 BOM in `.fv/verified-inputs.txt` parsing differently in Python and
TypeScript.

That wave is now in the worktree: the dashboard calls Gate B's own
`dirty_snapshot_defects`, `shared_artifact_defects`, and `v3_producer_defects`,
its manifest loader rejects an obligation id outside either id grammar with the
same exit 2 Gate B uses, both exclusion parsers reject a `U+FEFF` byte-order
mark, and `m1_coverage`'s parity matrix grew to eleven mutations — cross-claim
artifact reuse, `+dirty` PASS, a non-producer cohort profile, and both
`required_targets` mismatches among them — each asserted against both tools
with identical defect text, with the Gate B side in `r6_manifest_failclosed`.
The final correction wave was probed by fresh read-only closure agents. Their
evidence parity sweep found no Gate B/dashboard exit-code or defect-text
divergence, and their migration closure check found no new high/medium
fail-open or data-loss issue. Full `scripts/ci.py` passes locally and on Gula.

A read-only dry run against the real dossier project returned `status: ok`: 5
mapped artifacts, 173 preserved-history files, 0 unsupported, 0 conflicts, and
`docs/intent.md` as the elected target. The complete `.colosseum` digest was
unchanged. **No real legacy project has been cut over:** no `--apply` was run,
and migrated projects must still re-earn v3 evidence before Gate B can pass.

## Suggested sequence

W1, W2, and W5 are done; W3 waits on a discriminating W2-iteration corpus.
The repo is pushed and CI is green, so W4 now waits only on an external
party picking up `docs/replication-protocol.md`. Remaining W6 items land
whenever their inputs appear (account fix, ds4 endpoint, Google credential).

## Provenance

The full remediation plan of record (contracts G1-G5, phases Z/E/C/M, fixtures
R1-R28, exit criteria) came out of a five-round dual-agent adversarial review
closed 2026-07-11. Its narrative lives outside the repo; everything actionable
from it is either implemented (see the scoreboard) or captured above. Fixture
map: `tests/README.md`. Voice evidence: `registry/voices.json` and
`calibration/2026-07-13-r1/README.md`.
