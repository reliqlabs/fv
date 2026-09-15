# FV quickstart

FV is an OMP extension package. OMP discovers its `agents/`, `skills/`, `tools/`, and `.mcp.json` directly from this checkout.

## Prerequisites

- OMP with extension-package discovery and `restrictTools` support
- Python 3.11+ and `uv`
- Rust for Rust verification targets
- Optional proof tools for the pyramid layers you use: Quint, Kani, Verus, Aeneas/Charon, Lean

## Initialize a project

```bash
export FV_ROOT=/absolute/path/to/fv
uv run --script "$FV_ROOT/scripts/fv_init.py" /absolute/path/to/project
```

The initializer writes project state under `.fv/` and adds the FV checkout to `.omp/config.yml` `extensions:`. It does not copy package agents, skills, tools, or MCP definitions into the project.

After adding or changing the extension root, reload OMP's complete extension
snapshot in every already-running session:

```text
/reload-plugins
```

This reloads skills, agents, tools, hooks, commands, and MCP. `/mcp reload`
alone does not rediscover a newly added extension. New OMP sessions discover
the configured root at startup.

## Workflow

1. New-system intent: `/skill:fv-intent`.
2. Existing-system intent: `/skill:fv-reverse-intent`.
3. Multi-component boundaries: `/skill:fv-boundary`.
4. Quint authoring: dispatch `fv-quint-spec-generator` with `isolated=True, apply=False`; apply its patch only after `$FV_ROOT/scripts/obligation_check.py` accepts it.
5. Spec attack: `/skill:fv-adversarial`.
6. Implementation verification: `/skill:fv-verify`.
7. Code review: `/skill:fv-code-adversarial` through an independent `agent()` child.
8. Composition ledger: `/skill:fv-compose`.
9. Later changes: `/skill:fv-change`.
10. Multi-model planning or milestone review: `/skill:fv-panel`.

Skills execute in the current session. Named agents use OMP `task` or eval `agent()`; skill and agent namespaces are separate.

## Evidence gates

Produce G1 execution records through `fv_evidence_run`. Gate B resolves the raw artifact, recomputes its SHA-256 hash, validates the exit and class markers, and binds the manifest. Producer/operator honesty remains an explicit trust assumption; cryptographic signing is outside this milestone. Gate A requires content hashes on ledger citations.

```bash
python3 .fv/scripts/check_ledger_references.py .fv/ledger.md
python3 .fv/scripts/check_evidence_records.py --records .fv/evidence/records --manifest .fv/obligations.json
```

Run the project doctor after initialization:

```bash
uv run --script "$FV_ROOT/scripts/fv_doctor.py" --project /absolute/path/to/project
```

Historical calibration directories preserve prior transport evidence. They are archives, not operator instructions.
