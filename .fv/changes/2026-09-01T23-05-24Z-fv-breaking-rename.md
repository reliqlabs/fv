# Change record: FV breaking rename

- Date: 2026-09-01T23:05:24Z
- Classification: intent-touching
- Intent revision: none; the operator explicitly selected a breaking namespace cutover before any external user existed

## Description

Rename the formal-verification extension from its prior project name to the compact `fv` namespace across the repository, GitHub remote, OMP extension configuration, agents, skills, custom tools, environment variables, scripts, persisted state, schemas, fixtures, and documentation. Keep generic OMP runtime capabilities free of FV-specific naming.

## Breaking contract

- Skills: `/skill:fv-*`
- Agents: `fv-*`
- Tools: `fv_panel_resolve`, `fv_evidence_run`
- Package root: `FV_ROOT`
- Persisted state: `.fv/`
- Scripts: `fv_init.py`, `fv_doctor.py`, `fv_run.py`
- FV-owned schema contracts: v2
- Legacy aliases: none
- Legacy state migration: none

Historical `archive/`, `calibration/`, dogfood, and spike artifacts retain their recorded bytes and prior transport names. They are evidence, not live compatibility surfaces.

## Affected verification surface

- Quint: N/A; no protocol invariant changed.
- Lean: N/A; no theorem statement changed.
- Verus: N/A; no annotation changed.
- Kani: N/A; no harness changed.
- Tests: completed. All renamed fixtures, schema versions, package paths, initializer behavior, doctor checks, panel provenance, evidence gates, and CI contracts were updated.
- OMP runtime: positive subagent timeouts now clamp to at least 1 ms while exactly zero retains disable semantics.
- Persisted configuration: initializer enables isolated subagents without rewriting unrelated YAML, preserves valid explicit backends, and rejects invalid or noncanonical syntax without mutation.

## Adversarial review

- Independent final reviewer: `agent://FinalFVReview`
- Verdict: PASS
- Remaining High findings: none
- Remaining Medium findings: none
- Remaining Low findings: none

Findings closed included canonical intent/manifest drift, strict panel schemas, scaffolded isolation, project-rooted model probes, `FV_ROOT` validation, exact v2 schema rejection, package-rooted script paths, bounded positive timeouts, and non-destructive YAML mutation.

## Ledger delta

- Composition theorems added/removed: none.
- Axioms added/removed: none.
- Coverage shift: namespace and schema cutover coverage added; all existing trust claims retain their prior scope.

## Environment closure

- Local checkout: `/Users/mv/Development/reliq/fv`
- GitHub repository: `https://github.com/reliqlabs/fv`
- Git origin: `git@github.com:reliqlabs/fv.git`
- OMP global extension root: `/Users/mv/Development/reliq/fv`
- Shell environment: `FV_ROOT=/Users/mv/Development/reliq/fv`
- Lean: `leanprover/lean4:v4.29.0`

## Verification

- `bun check`: PASS
- OMP focused eval tests: PASS
- FV fresh-project doctor: PASS
- FV regression suite: 29/29 PASS
- Strict FV CI: 6/6 PASS
- Live namespace audit: no prior project-name references in live code, tests, prompts, docs, MCP configuration, or registry

## Outstanding follow-ups

- None for the approved FV breaking-cutover scope.
