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
- `check_evidence_records.py`: Gate B, including raw-artifact resolution, SHA-256 recomputation, PASS markers, and obligation compatibility.
- `obligation_check.py`: validates the frozen obligation manifest against generated specifications.
- `lean_axiom_gate.py`: rejects prohibited Lean axioms.
- `check_ledger_version.py`: validates the ledger version envelope.
- `check_fixture_tracking.py`: fails when required fixtures are untracked.
- `ci.py`: runs the default fail-closed gate set. `INCOMPLETE` fails unless `--tolerate-incomplete` is explicit.

## OMP orchestration

- `skills/fv-adversarial/omp_fanout.py`: failure-isolated adversarial fan-out over the generated `omp_native` route.
- `skills/fv-panel/omp_panel.py`: blinded draft, cross-review, and synthesis panel engine.
- `omp_calibration_session.py`: starts an OMP session with fallback suppression for selected calibration routes.
- `fv_run.py`: durable run-state manifest for local artifact coordination.

## Measurement and conformance

- `pyramid_run.py`: verification pyramid runner.
- `coverage_dashboard.py`: per-claim evidence status.
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
