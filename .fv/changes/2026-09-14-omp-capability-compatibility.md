# Change record: OMP capability-based compatibility

- Date: 2026-09-14
- Classification: intent-touching
- Intent revision: none; this repository has no FV intent document, and its sole user authorized a clean pre-release contract cutover

## Description

Remove OMP from the exact proof-tool version pins. FV now records `omp --version` as provenance and decides host compatibility from the versioned bridge contract in `bom.json`: the contract version and every required capability must match, while additive capabilities are accepted. Proof tools remain exactly pinned because their accepted syntax, artifacts, and solver behavior can vary by release.

## Affected verification surface

- Quint: N/A
- Lean: N/A
- Verus: N/A
- Kani: N/A
- Tests: completed, R29 covers different OMP semver, additive capabilities, missing capabilities, false capabilities, and incompatible contract versions
- Compose: N/A, project evidence and composition verdict semantics unchanged

## Adversarial review

N/A for pre-release clean cutover approved by the sole user. Fail-closed cases are explicit tests rather than compatibility shims.

## Ledger delta

- Composition theorems added/removed: none
- Axioms added/removed: none
- Coverage shift: OMP compatibility moves from semver equality to a versioned required-capability subset

## Outstanding follow-ups

- Add an FV intent document before treating this repository itself as an FV-managed target.
