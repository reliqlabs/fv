# Change record: canonical panel roster update

- Date: 2026-09-15
- Classification: intent-touching configuration change
- Authority: user-requested canonical roster: GPT-6 Astra, Claude Fable 5.1, GLM 5.3, and Kimi K3
- Compatibility posture: established. The `fv-canonical` role name, four-seat shape, independent strategy, and `minFamilies: 4` contract remain unchanged.

## Configuration

The OMP-owned `panel.roles.fv-canonical` seed now resolves:

1. `openai-codex/gpt-6-astra:xhigh`
2. `anthropic/claude-fable-5-1:xhigh`
3. `fireworks/glm-5.3:high`, with `ollama-cloud/glm-5.3` as the availability fallback
4. `synthetic/hf:moonshotai/Kimi-K3:high`, with `fireworks/kimi-k3` as the availability fallback

OMP's live lineup resolver returned the distinct families `openai`, `anthropic`, `glm`, and `kimi`, satisfying `minFamilies: 4`, with lineup hash `sha256:b9ef78fd0563443db4c7c0b8d66d6427ef1ea74645d87a80f489786dc392e3cc`.

## Calibration boundary

Kimi K3 retains its exact-route attested calibration. Fable 5.1, GPT-6 Astra, and GLM 5.3 are new exact routes with `omp_calibration: pending` and `omp_route_grade: not-run`. Historical predecessor evidence is retained only as lineage context. It does not calibrate or attest the successor routes.

## Updated artifacts

- `templates/omp-panel.json`
- `registry/voices.json`
- generated roster blocks and `scripts/dispatch.config.example.json`
- manual roster guidance in `skills/fv-adversarial/SKILL.md`, `skills/fv-panel/SKILL.md`, and `ROADMAP.md`
- integration fixtures for GLM fallback, customized panel preservation, native dispatch, and scoped calibration suppression

## Verification

- `scripts/gen_roster_docs.py --check`: PASS
- `tests/r0_registry_docs.py`: PASS
- `tests/r29_omp_integration.py`: PASS
- `tests/r31_omp_panel.py`: PASS
- `tests/r32_resolver_contract.py`: PASS
- `tests/r30_omp_native_dispatch.py`: PASS
- `tests/r33_omp_calibration_session.py`: PASS
- Fresh-project `omp config get panel`: exact requested roster and effort levels
- Fresh-project `fv_doctor.py`: PASS, including effective model availability and thinking-level checks
- Live OMP `resolvePanelLineup`: four distinct resolved families and persisted lineup hash
- Full `scripts/ci.py`: PASS, 6 checks

No route-calibration run was performed. The three pending routes must remain labeled pending until measured and attested.
