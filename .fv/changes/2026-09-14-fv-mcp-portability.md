# Change record: FV MCP extension-relative commands

- Date: 2026-09-14
- Classification: implementation-only
- Intent revision: none

## Description

Replace `${FV_ROOT}` MCP executable paths with extension-relative `./mcp/...` commands. OMP roots those paths at the discovered extension directory, so `/reload-plugins` works even when the existing OMP process started before `FV_ROOT` entered the shell environment. Keep `FV_ROOT` for operator-facing scripts and skill commands.

## Affected verification surface

- Quint: N/A
- Lean: N/A
- Verus: N/A
- Kani: N/A
- Tests: completed, R29 checks that every MCP executable is extension-relative and independent of inherited `FV_ROOT`
- Compose: N/A, evidence semantics unchanged

## Adversarial review

N/A, implementation-only path-resolution correction preserving the existing MCP server set and executable bytes.

## Ledger delta

- Composition theorems added/removed: none
- Axioms added/removed: none
- Coverage shift: package doctor now validates containment, existence, and executable permissions for every extension-relative MCP command

## Outstanding follow-ups

- Existing sessions still need `/reload-plugins` after extension configuration changes.
- Operator-facing `$FV_ROOT` script commands still require the session process to inherit that environment variable.
