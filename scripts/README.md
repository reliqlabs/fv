# FV scripts

All live orchestration is OMP-native. Historical calibration artifacts retain their original provenance.

## Project setup and diagnostics

- `fv_init.py`: creates project `.fv/` state, merges the FV checkout into `.omp/config.yml` `extensions:`, and installs `fv-canonical` under OMP's `panel.roles` settings.
- `fv_doctor.py`: checks exact proof-tool pins, the required OMP capability contract (recording OMP semver as provenance), extension discovery, MCP wiring, dispatch state, static frontmatter, OMP panel-role ownership, and live model candidates.
- `validate_frontmatter.py`: validates `skills/*/SKILL.md` and static `agents/*.md` against the OMP contract.
- `check_dispatch_config.py`: validates the OMP-only `dispatch.json` schema and route hash.
- `gen_roster_docs.py`: regenerates OMP roster blocks and dispatch routes from `registry/voices.json`.

## Verification gates

- `check_ledger_references.py`: Gate A, including required content hashes for every cited executable artifact.
- `check_evidence_records.py`: Gate B, including raw-artifact resolution, SHA-256 recomputation, PASS markers, obligation compatibility, and system-claim cohort coverage.
- `obligation_check.py`: validates the frozen obligation manifest against generated specifications.
- `lean_axiom_gate.py`: rejects prohibited Lean axioms.
- `check_ledger_version.py`: validates the ledger version envelope.
- `check_fixture_tracking.py`: fails when required fixtures are untracked.
- `ci.py`: runs the default fail-closed gate set. `INCOMPLETE` fails unless `--tolerate-incomplete` is explicit.

### Evidence records (`fv-evidence-run/v3`)

The `fv_evidence_run` tool (`tools/evidence-run.ts`) writes one record per claim at
`.fv/evidence/records/<claim_id>.json` and its raw log under `.fv/evidence/raw/`. Gate B consumes
those records; nothing else is evidence. Field-by-field shape, with a worked single-execution
invariant and a worked multi-execution system claim, is in
[`docs/dogfood-evidence.md`](../docs/dogfood-evidence.md).

- Source binding is `bindings.source_snapshot`, a verified-input content snapshot
  `sha256:<hex>` over every tracked-or-untracked, unignored, non-excluded file (`+dirty` suffix
  when a non-excluded path is modified), not a commit id. Exclusion prefixes:
  `.fv/evidence/`, `.fv/verify/`, `.fv/panels/`, `.colosseum/`, plus any listed in
  `.fv/verified-inputs.txt`.
- Intent binding is `bindings.intent_path` (repo-relative canonical target, resolved from
  `.fv/dispatch.json` `omp_native.target_spec`, default `.fv/intent.md`) plus
  `bindings.intent_hash` over that file's bytes. `check_evidence_records.py --json` echoes the
  `intent_path` it resolved (`null` when the caller supplied `--expect-intent` or
  `--allow-unbound`), the expected snapshot, the per-claim `obligation_kinds`, and the
  `required_evidence` map it enforced.
- `bindings.executions` is the nonempty execution cohort: per entry `tool`, `evidence_class`,
  `command` argv array, repo-relative `cwd`, `toolchain_digests`, `raw_output_path`,
  `raw_output_hash`, `result`, `run_id`, and optional `pass_marker`. One raw log per execution
  (`.fv/evidence/raw/<claim_id>-<run_id>.log`); nothing is concatenated.
- The producer takes exactly one of `command` (single argv array, with optional top-level `cwd`,
  `tool`, `pass_marker`) or `executions` (nonempty array of
  `{tool, command, evidence_class?, cwd?, pass_marker?}`, unique `tool` IDs, no top-level
  `cwd`/`tool`/`pass_marker`). The single-command form records exactly one entry.
- Record-level `command`, `raw_output_path`, `raw_output_hash`, `toolchain_digests`, and
  `configuration.cwd`/`pass_marker` are derived from `executions[0]` verbatim, and Gate B enforces
  that derivation. Record-level `run_id` stays the cohort timestamp. Record `result` is PASS only
  when every execution is PASS and snapshot, intent hash, and manifest hash stayed stable across
  the cohort with no dirty verified inputs.
- Default freshness is v3: with neither `--expect-snapshot` nor `--allow-unbound`, the gate
  recomputes the current snapshot and requires an exact match, so a `fv-evidence-run/v2` record
  (commit-id source binding) is stale by default and validates only under an explicit
  `--expect-snapshot`/`--allow-unbound` invocation.
- `obligations.json` may declare `system_claims` beside `invariants` and `witnesses`. Each claim
  carries `depends_on` (nonempty, unique, naming declared invariants and witnesses only) and
  `required_evidence` (nonempty, unique tool IDs). Gate B aggregates claims into the required set
  with kind `system_claim`, and a claim PASSes only when every `required_evidence` tool ID appears
  among its PASS executions.

### Verification plans (`fv-verification-plan/v1`)

- `pyramid_run.py --plan <path>` reads a declarative plan (conventionally
  `.fv/verification-plan.json`) whose `layers` map declares, per layer, `required` plus a nonempty
  `executions` array of `{argv, cwd, timeout_seconds, env?, evidence_tool?}`. Layers the plan does
  not name keep the built-in defaults; without `--plan` the runner is the legacy runner.
- No shell strings, no ambient environment mutation: declared `env` merges over the subprocess
  environment, `cwd` must stay repo-relative, and escapes are rejected.
- Shipped example: [`verification-plan.example.json`](./verification-plan.example.json), walked
  through in [`docs/dogfood-evidence.md`](../docs/dogfood-evidence.md).

## OMP orchestration

- `skills/fv-adversarial/omp_fanout.py`: failure-isolated adversarial fan-out over the generated `omp_native` route.
- `skills/fv-panel/omp_panel.py`: blinded draft, cross-review, and synthesis panel engine.
- `omp_calibration_session.py`: starts an OMP session with fallback suppression for selected calibration routes.
- `fv_run.py`: durable run-state manifest for local artifact coordination.

## Measurement and conformance

- `pyramid_run.py`: verification pyramid runner; `--plan` executes a declared `fv-verification-plan/v1` document instead of the built-in layer defaults.
- `coverage_dashboard.py`: per-claim evidence status. `--manifest` derives required IDs from
  `invariants` + `witnesses` + `system_claims`, so every claim is a row carrying its
  `obligation_kind`. A system-claim row shows `required_evidence`, the record's execution cohort,
  and per-required-tool observed results (`evidence_coverage`, `no-execution` for a tool that
  never ran); it reports `evidence-gap` when a required tool never PASSed or any cohort execution
  did not PASS, and `dependency-gap` when the cohort is complete but a `depends_on` obligation is
  not covered this run. Both are INCOMPLETE, never PASS. `--require` may narrow a `--manifest`
  run; an ID absent from the manifest is an error.
- `self_measure.py`: yield, cost, and routing metrics over recorded artifacts.
- `recall_score.py`: seeded-defect recall scoring.
- `benchmark_run.py`: benchmark harness; callers provide the OMP-native dispatch command.
- `benchmark_run.py`, `itf_replay.py`, and `benchmark_run.py`: replay and benchmark support.
- `check_doc_links.py`: documentation-link validation.

### Voice roster

<!-- BEGIN GENERATED: voice-roster (source: registry/voices.json via scripts/gen_roster_docs.py - do not edit by hand) -->
| Voice id | OMP selector | Family | Status | OMP calibration | Route grade |
|---|---|---|---|---|---|
| `claude-agent` | `anthropic/claude-fable-5:xhigh` | Anthropic | canonical-panel | pending | unattested |
| `kimi-k2.6` | `burnt/cloudflare-100/@cf/moonshotai/kimi-k2.6` | Moonshot | candidate | pending | not-run |
| `gpt-5.6-sol` | `openai-codex/gpt-5.6-sol:xhigh` | OpenAI | canonical-panel | pending | unattested |
| `glm-5.2` | `synthetic/hf:zai-org/GLM-5.2:high` | Zhipu | canonical-panel | pending | degraded |
| `kimi-k3` | `synthetic/hf:moonshotai/Kimi-K3:high` | Moonshot | canonical-panel | Seeded-defect recall 6/7 on the held-out leasedb corpus over the OMP-NATIVE transport at synthetic/hf:moonshotai/Kimi-K3:high, blinded single pass under the deny-first fv-spec-adversary profile (calibration/2026-07-28-r3; D1 excluded for all voices as mis-specified). Cleared the pre-registered floor. The ONLY voice in that run whose served route was positively attested: its sole configured fallback target (fireworks/kimi-k3) had no usage-ledger counter, so a degrade would have created a visible entry and none appeared. Missed D8, anchoring the waiter leak at register_waiter rather than at the release site a fix would change. Transcript audited clean. Scope: one voice, one pass, one corpus, this rung only. | attested |
<!-- END GENERATED: voice-roster -->
