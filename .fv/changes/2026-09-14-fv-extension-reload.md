# Change record: FV extension reload guidance

- Date: 2026-09-14
- Classification: implementation-only
- Intent revision: none

## Description

Correct FV installation and initializer guidance so a newly configured extension is rediscovered by an already-running OMP session. `/reload-plugins` reloads skills, commands, hooks, tools, agents, and MCP; `/mcp reload` alone cannot discover a new extension root. Use the initializer's declared PEP 723 dependencies through `uv run --script` instead of assuming system Python already has PyYAML.

## Affected verification surface

- Quint: N/A
- Lean: N/A
- Verus: N/A
- Kani: N/A
- Tests: completed, `tests/r29_omp_integration.py` checks initializer reload guidance
- Compose: N/A, no trust claim changed

## Adversarial review

N/A, implementation-only correction to installation commands and user-facing output.

## Ledger delta

- Composition theorems added/removed: none
- Axioms added/removed: none
- Coverage shift: initializer output now pins the extension rediscovery mechanism

## Outstanding follow-ups

- Replace FV's exact OMP semver gate with capability and behavioral compatibility checks in a separate intent-touching change.
