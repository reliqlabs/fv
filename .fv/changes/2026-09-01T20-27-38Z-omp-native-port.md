# Change record: OMP-native port

- Date: 2026-09-01T20:27:38Z
- Classification: intent-touching
- Intent revision: none; this repository had no canonical `.fv/intent.md`, so the approved `fv-omp-native-plan.md` was the change authority

## Description

Port FV from retired subprocess and OpenCode integration to an OMP extension package. The change adds static restricted agents, OMP eval-agent model and timeout controls, ModelRegistry-backed panel routing, producer-trusted evidence execution, current-state Gate B binding, OMP-only initialization and doctor checks, and exhaustive CI semantics.

The final namespace is `fv`: `/skill:fv-*`, `fv-*` agents, `fv_*` tools,
`FV_ROOT`, and `.fv/` state. This is an intentional breaking cutover with no
legacy aliases or persisted-state migration. FV-owned versioned schemas moved
from v1 to v2; historical calibration and archive artifacts remain byte-faithful.

## Affected verification surface

- Quint: N/A; no protocol state-machine claim changed.
- Lean: N/A; no theorem statement or proof changed.
- Verus: N/A; no annotation changed.
- Kani: N/A; no harness changed.
- Tests: completed. OMP discovery, restriction containment, eval timeout/model forwarding, prelude positional compatibility, panel quorum/provenance, initializer/doctor, evidence artifact/freshness/path validation, reference project, registry drift, and strict/tolerant CI contracts were exercised.
- Compose: completed as N/A. No composition theorem or axiom was added, removed, or weakened. Runtime trust boundaries are recorded below.

## Adversarial review

- Initial independent code-adversarial review: `agent://IndependentOMP-nativeportreview`
- Independent trust-delta review: `agent://Independenttrustdeltareview`
- Final trust-closure review: `agent://TrustClosure` — PASS, no remaining High, Medium, or Low finding.
- Findings addressed in code, tests, or explicit trust-boundary documentation.

Accepted trust boundaries:

- Evidence records are producer/operator trusted. Hash binding detects artifact drift; it does not authenticate the producer or prove semantic correspondence between a command and claim.
- Subagent filesystem isolation remains explicitly unverified.
- Historical calibration evidence is transport-specific and does not silently attest a current OMP route.

## Ledger delta

- Composition theorems added/removed: none.
- Axioms added/removed: none.
- Coverage shift: added OMP extension discovery, restricted-agent containment, per-call model/timeout routing, served-route model-family comparison, raw artifact archival and integrity, automatic source/intent/manifest freshness binding, executable identity, symlink confinement, Track A capability probing, live model-ladder drift checks, and fail-closed doctor coverage.

## Environment closure

- Installed and selected `leanprover/lean4:v4.29.0`, matching the BOM.
- Linked `~/.local/bin/omp` to the current Oh My Pi source CLI.
- R7 passed, the fresh-project doctor passed, all 29 regression suites passed, and strict CI passed all six checks.

## Outstanding follow-ups

- None for the approved OMP-native port scope.
