# Change record: OMP-owned FV panels

- Date: 2026-09-14
- Classification: intent-touching
- Intent revision: none; the FV repository has no intent artifact, and its sole user authorized a clean pre-release cutover

## Description

Remove FV-owned runtime roster profiles. FV now resolves a named role from OMP's effective `panel.roles` settings and delegates parsing, candidate selection, thinking policy, resolved-family diversity, family floors, and lineup hashing to OMP. The initializer seeds `panel.roles.fv-canonical` in project OMP configuration and writes no `.fv/panel-profiles.json`. Synthesis resolves through OMP's ordinary `@plan` model role.

## Affected verification surface

- Quint: N/A
- Lean: N/A
- Verus: N/A
- Kani: N/A
- Tests: R29 initializer/doctor ownership, R31 engine normalization, R32 real OMP settings and resolver integration
- Compose: panel lineup provenance remains hash-bound; declared-family quorum now uses OMP's resolved family directly

## Adversarial review

N/A for the clean pre-release ownership cutover. Runtime resolution fails closed when the named OMP role, session settings, model candidate, family policy, or panel API is unavailable.

## Ledger delta

- Composition theorems added/removed: none
- Axioms added/removed: none
- Coverage shift: panel definitions move from `.fv/panel-profiles.json` into OMP `panel.roles`; FV retains calibration overlay and its three-wave evidence protocol

## Outstanding follow-ups

- None for panel-definition ownership.
