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

The initializer writes project state under `.fv/`, adds the FV checkout to `.omp/config.yml` `extensions:`, and installs the default `fv-canonical` role under OMP's `panel.roles` settings. It does not copy package agents, skills, tools, MCP definitions, or panel profiles into `.fv/`.

After adding or changing the extension root, reload OMP's complete extension
snapshot in every already-running session:

```text
/reload-plugins
```

This reloads skills, agents, tools, hooks, commands, and MCP. `/mcp reload`
alone does not rediscover a newly added extension. New OMP sessions discover
the configured root at startup.

## Migrating a legacy Colosseum project

`scripts/fv_migrate.py` shadow-migrates a legacy tree into `.fv/`. Dry run is the
default and the deterministic JSON report is what you read first:

```bash
uv run --script "$FV_ROOT/scripts/fv_migrate.py" /absolute/path/to/project --json
```

Exit 0 is `status: ok`, 1 is `status: blocked` (or a legacy tree that cannot be
inventoried), 2 a usage error or an unresolvable project root. Omit `--json` for
the same report as text.

### Reading the report

- `counts` and `artifacts[]`: every legacy file is classified exactly once as
  `mapped`, `preserved-history`, or `unsupported`. A sub-artifact row
  (`<file>#layers.<name>`, `<file>#claims.<id>`, `<file>#ids.<id>`) appears only
  when an item inside an otherwise-mapped file deviates from its file's mapping,
  so it names what the translation did not carry.
- `unsupported[]`: a non-regular or unreadable file, an unknown or malformed
  legacy schema, a malformed claim, a verification layer no argv execution can
  represent, two legacy targets whose obligation ids collide after
  normalization, a target that normalizes to an empty id, or a destination
  already holding different content. Any entry here blocks the run.
- `conflicts[]`: a `.fv/` destination that exists with different content (both
  hashes are printed), is a directory or a symlink, or sits under a non-directory
  parent.
- `writes[]`: every intended path under `.fv/` with `action` `create`,
  `identical`, or `conflict`, plus the SHA-256 of the bytes that would be written.

`status` is `blocked` whenever `unsupported` or `conflicts` is nonempty. Resolve
the named entries (fix the legacy artifact, or move the conflicting `.fv/` file
aside), then re-run the dry run. `--apply` refuses a blocked migration and writes
nothing.

### Applying the shadow state

```bash
uv run --script "$FV_ROOT/scripts/fv_migrate.py" /absolute/path/to/project --apply
```

Every write lands under `.fv/`:

- `.colosseum/ledger.md` to `.fv/ledger.md`, verbatim.
- `.colosseum/intent.md` to `.fv/intent.md` as the dispatch target. When the
  ledger cites an external intent document that exists, dispatch targets that
  instead and the legacy entrypoint's bytes go to history only.
- `.colosseum/obligations.json` plus `.colosseum/g1-claims.json` to
  `.fv/obligations.json`. Each legacy claim becomes a `system_claims` entry whose
  `depends_on` is its `required_targets` under the id normalization below and
  whose `required_evidence` is its `layers`; each distinct target is synthesized
  as an invariant, or as a witness when its prefix is `proptest`/`test`.
- `.colosseum/evidence/runs/layer-runs.json` to `.fv/verification-plan.json`.
- `.fv/verified-inputs.txt` with FV's conservative exclusion defaults plus
  `.fv/history/`. The legacy file is an include list, the exact opposite, so it is
  kept as history rather than inverted.
- `.fv/dispatch.json` with `project_root` `"."` and a repo-relative `target_spec`.
  An existing `dispatch.json` keeps its route and has only those two fields
  rewritten; one that is already canonical is left byte-identical.
- `.fv/history/colosseum/<path relative to .colosseum>`: every other legacy file,
  byte-for-byte.

Two properties hold by construction:

- **Migration never treats legacy evidence as live v3 evidence.** Legacy
  per-claim records under `.colosseum/evidence/` are `preserved-history` and land
  only under `.fv/history/colosseum/`, never under `.fv/evidence/`. Gate B reads
  `.fv/evidence/records`, so no migrated byte can discharge an obligation. The
  migrated manifest states it: every obligation is uncovered until an
  `fv-evidence-run/v3` record binds it.
- **Migration never deletes legacy state.** `.colosseum/` is only ever read and
  stays byte-identical; the tool has no flag that removes it. Re-running `--apply`
  is byte-idempotent: unchanged destinations report `action: identical`, and a
  destination that differs is a conflict, not an overwrite.

### Custom plan layers

A legacy layer with a pyramid equivalent is renamed to it (`proptest` becomes
`proptests`). Every other legacy layer keys the plan under its own id as an
`fv-verification-plan/v1` custom layer, so `quint` migrates as the layer `quint`
instead of being dropped. Custom layers get the same argv/`cwd`/`timeout_seconds`/
`env` validation and report shape as built-in layers and run after them in lexical
order. A layer named by any legacy claim that `obligations.json` marked
`required` is written `required: true`, which puts it in the G2 gating set; when
no legacy claim manifest exists, every migrated layer is required. A layer that
cannot be translated is `unsupported` and blocks the migration, and no partial
plan is written. The untranslatable cases: shell operators or expansions in the
recorded command, a missing or escaping `cwd`, a malformed environment, the
reserved id `floors`.

A legacy `a; b; c` command becomes three executions in one layer. The last
segment carries the bare layer id as its `evidence_tool` (`quint`), because its
exit status is what the legacy manifest recorded; earlier segments get
`quint:1`, `quint:2`, so one cohort never declares the same tool twice.

### Initialize OMP settings after applying

Migration writes project state only. Run the initializer afterwards for the OMP
side:

```bash
uv run --script "$FV_ROOT/scripts/fv_init.py" /absolute/path/to/project
```

It merges the FV checkout into `.omp/config.yml` `extensions:`, installs
`fv-canonical` under OMP's `panel.roles`, copies the Gate A/B validators and
`fv_project.py` into `.fv/scripts/`, and writes `.fv/harness`. Without
`--target-spec` it preserves the migrated `target_spec`, and it only appends
exclusion defaults missing from `.fv/verified-inputs.txt`. Do not pass `--force`
after a migration: it replaces FV-owned state, including the migrated dispatch
target and the `.fv/history/` exclusion. Then run `/reload-plugins` in every
already-running OMP session.

### Review the converted claims and the verification plan

```bash
mkdir -p .fv/evidence/records
python3 "$FV_ROOT/scripts/coverage_dashboard.py" \
  --records .fv/evidence/records --manifest .fv/obligations.json
```

The dashboard errors (exit 2) if the records directory does not exist, and on a
freshly migrated project every row is `missing-record` with each
`required_evidence` tool reported `no-execution`: exit 3, `VERDICT: INCOMPLETE`.
That is the honest state, since no migrated byte is evidence.

Read each `system_claims` entry in `.fv/obligations.json` against
`.fv/history/colosseum/g1-claims.json` and confirm its `depends_on` and
`required_evidence` are the claim you meant; the migration retains `scope`,
`waiver`, `evidence_class`, `profile`, and `environment_policy` rather than
summarizing them. Then rehearse the migrated plan before trusting it:

```bash
uv run --script "$FV_ROOT/scripts/pyramid_run.py" \
  --crate /absolute/path/to/crate --profile bounded \
  --plan .fv/verification-plan.json --json
```

Every migrated execution inherits one conservative `timeout_seconds` ceiling
(3600) because the legacy manifest recorded no timeout. Layers the plan does not
name keep the built-in defaults.

### Re-run every required evidence cohort

Nothing is verified until the evidence is re-produced. Through `fv_evidence_run`,
against the current verified inputs:

- one record per invariant and per witness, using the single-`command` form;
- one cohort per system claim, using the `executions` form, covering every
  `required_evidence` tool ID. A claim PASSes only when each named tool has a PASS
  execution, so a claim whose legacy layers include `quint` needs a `quint`
  execution in its cohort.

```json
{
  "claim_id": "C-01",
  "evidence_class": "bounded-checked",
  "scope": "Every admission leaves entries_root canonical.",
  "executions": [
    { "tool": "quint", "command": ["quint", "verify", "quint/dossier.qnt"] },
    { "tool": "kani", "command": ["cargo", "kani", "-p", "dossier-contract"] },
    { "tool": "proptest", "command": ["cargo", "test", "-p", "dossier-contract", "--test", "property"] }
  ]
}
```

The migrated plan's `evidence_tool` ids are the names `required_evidence` matches
against, so the plan tells you which command stands for which tool ID. Field
shapes and the full worked cohort are in
[docs/dogfood-evidence.md](./docs/dogfood-evidence.md).

Migrated obligation ids are normalized deterministically from the legacy
`required_targets`, so every one is directly usable as an `fv_evidence_run`
`claim_id`. The legacy target splits at its first colon; within each part every
run of characters outside `[A-Za-z0-9._-]` collapses to a single `-` and leading
and trailing `.`, `_`, `-` are stripped; the id is `<layer>.<name>`. So
`quint:invS7` becomes `quint.invS7`, `kani:proof_harness` becomes
`kani.proof_harness`, and `verus:contract::state::Machine` becomes
`verus.contract-state-Machine`. Legacy claim ids normalize by the same rule.
Every migrated id therefore matches the `[A-Za-z0-9][A-Za-z0-9._-]*` that
`.fv/evidence/records/<claim_id>.json` requires, and no post-migration rename is
needed to cover an obligation with a producer-written record.

Traceability and collisions:

- Every obligation whose id was rewritten carries `legacy_id` with the exact
  legacy string; a migrated witness also keeps the unnormalized legacy target
  name as its `name`. `legacy_id` is absent when the legacy id needed no rewrite.
- `system_claims.depends_on` names the normalized ids, in legacy
  `required_targets` order.
- Nothing is suffixed to break a tie. Two legacy targets that normalize to one
  id, or a target that normalizes to nothing, become `unsupported` rows naming
  every legacy string involved, so the migration blocks instead of writing a
  manifest in which one record would shadow another obligation.

### Gate A and Gate B

```bash
python3 .fv/scripts/check_ledger_references.py .fv/ledger.md
python3 .fv/scripts/check_evidence_records.py \
  --records .fv/evidence/records --manifest .fv/obligations.json
```

The ledger arrives verbatim, so Gate A rechecks its citations against the FV
project: each must resolve inside the project root and carry an
`@sha256:<12hex>` binding over the cited line. Use `--suggest-hashes` to print the
suffix for every unhashed citation, and repoint citations that still name legacy
paths. Run Gate B with neither `--expect-snapshot` nor `--allow-unbound`: default
freshness is v3, and loosening the gate to admit the legacy v1/v2 records is
exactly the laundering the shadow migration exists to prevent.

### Moving or cloning a migrated project

Migrated state is portable: `project_root` is `"."`, `target_spec` and every plan
`cwd` are repo-relative, and the verified-input snapshot hashes repo-relative
paths and file contents, not absolute locations or a commit id. Cloning or moving
the project leaves dispatch valid and the snapshot unchanged, so a record stays
fresh as long as the verified-input bytes are identical. `.colosseum/` is a
built-in exclusion prefix and the migration adds `.fv/history/`, so carrying the
legacy tree and its imported copy along does not move the snapshot.

### Retain the legacy tree until parity is explicitly accepted

Keep the legacy tree in place. It remains the auditable original for everything
the translation could not carry, and it is the only record of the legacy evidence.
Parity acceptance is an operator decision, not a tool output: reach it only when
the dry-run report has no `unsupported` or `conflicts` rows, the converted claims
and plan have been reviewed against the legacy artifacts, every required cohort
has been re-run, and Gate A and Gate B pass without `--expect-snapshot` or
`--allow-unbound`. Removing `.colosseum/` after that is a manual step; no FV
command does it.

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
