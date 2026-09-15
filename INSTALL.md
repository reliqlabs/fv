# Installing FV for OMP

FV is an OMP extension package. The checkout is the installation root; projects reference it through `.omp/config.yml`.

## Requirements

- OMP with extension roots, static agents, custom tools, and root `.mcp.json` discovery
- Python 3.11+ with `uv`
- Git
- Rust toolchain for Rust targets

Verification tools are incremental. Install only the layers required by the target:

- Quint, its Apalache model-checking backend, and a Java runtime reachable as `java` for protocol properties
- Kani for bounded Rust checks
- Verus for deductive Rust verification
- Charon and Aeneas for Rust-to-Lean extraction
- Lean 4 and mathlib for theorem proofs
- LM Studio only when using its local MCP operations

Each MCP health check reports a missing underlying binary without treating the layer as verified.

## Install OMP

Use the repository-supported OMP build described by the Oh My Pi project, then verify:

```bash
omp --version
```

## Clone FV

```bash
git clone https://github.com/reliqlabs/fv.git /absolute/path/to/fv
export FV_ROOT=/absolute/path/to/fv
```

The root contains:

```text
agents/       static OMP agent definitions
skills/       OMP skills
 tools/       OMP custom tools
.mcp.json     proof-tool MCP servers
templates/    project-state templates
scripts/      gates, initializer, doctor, and CI
```

## Configure proof-tool binaries

MCP executables in the package `.mcp.json` use `./mcp/...` paths. OMP resolves
those paths against the discovered extension root, so reloading an extension
does not depend on the parent OMP process having inherited `FV_ROOT`.

`FV_ROOT` remains the operator-facing path used by scripts and skill commands.
Optional proof-tool binary locations stay in the environment:

```bash
export FV_ROOT=/absolute/path/to/fv
export VERUS_BIN=/absolute/path/to/verus
export CHARON_BIN=/absolute/path/to/charon
export AENEAS_BIN=/absolute/path/to/aeneas
```

Only set optional binary variables for installed layers.

## Initialize a project

```bash
uv run --script "$FV_ROOT/scripts/fv_init.py" /absolute/path/to/project
```

Optional explicit intent/spec target:

```bash
uv run --script "$FV_ROOT/scripts/fv_init.py" \
  /absolute/path/to/project \
  --target-spec .fv/intent.md
```

`--target-spec` takes a path inside the project: either project-relative (as
above) or absolute. A target outside the project root is rejected. A fresh init
without the flag declares `.fv/intent.md`; a rerun without the flag preserves
the already-declared target.

The initializer:

- creates `.fv/{attacks,verify,evidence,scripts,panels}`;
- writes the OMP-only `.fv/dispatch.json`;
- copies the Gate A/B validators and the shared `fv_project.py` target resolver into `.fv/scripts/`;
- installs the default `fv-canonical` role under OMP's project `panel.roles` settings;
- merges the FV checkout into `.omp/config.yml` `extensions:`;
- writes `.fv/harness` as `omp`.

`.fv/dispatch.json` is the project's declaration of its canonical verification
target. It is written portably: `omp_native.project_root` is `"."` and
`omp_native.target_spec` is a repo-relative POSIX path, so the file stays valid
when the project is cloned, moved, or checked out on another machine. Every
skill, agent, and gate that needs the intent resolves `target_spec` against the
project root rather than the current working directory, and uses
`.fv/intent.md` when `target_spec` is absent. A legacy absolute
`project_root`/`target_spec` pointing inside the project is still accepted and
is rewritten to the portable form on the next init run; a target that is
missing, a directory, or outside the project root is an error rather than a
silent fallback.

`fv_project.py` exposes `resolve_target(project_root)`, the single
implementation of that rule. Skills and gates call it; the read-only review
agents, which cannot execute code, read `dispatch.json` directly and apply the
same rule. Neither searches for candidate filenames.

To move the intent later, move the file and update `omp_native.target_spec` to
the new repo-relative path. Editing one without the other leaves downstream
stages reading the old target.

It does not copy package agents, skills, tools, or MCP definitions. Existing extension entries are preserved. Use `--force` only to replace FV-owned project state.

## Migrate a legacy Colosseum project

A project that already has a `.colosseum/` tree is shadow-migrated into `.fv/`
before initialization. Dry run first; it is the default:

```bash
uv run --script "$FV_ROOT/scripts/fv_migrate.py" /absolute/path/to/project --json
uv run --script "$FV_ROOT/scripts/fv_migrate.py" /absolute/path/to/project --apply
```

Exit 0 is `status: ok`; 1 is `status: blocked` or an apply that failed and rolled
back; 2 a usage error or an unresolvable project root. `--apply` writes only
under `.fv/`, refuses a blocked report, and is byte-idempotent on re-run.
`.colosseum/` is only ever read: the migration never deletes legacy state and
never copies a legacy evidence record into `.fv/evidence/`, so nothing migrated
counts as live `fv-evidence-run/v3` evidence. Legacy verification layers without
a built-in pyramid step, `quint` among them, become `fv-verification-plan/v1`
custom layers instead of being dropped.

The report (`fv-migration-report/v1`) carries `schema`, `project_root` (always
`"."`), `target_spec` (the elected dispatch target), `requested_mode`, `mode`,
`applied`, `status`, `error`, `counts`, `artifacts[]`, `writes[]`, `conflicts[]`,
and `unsupported[]`. A blocked `--apply` reports `requested_mode: apply`,
`mode: dry-run`, `applied: false`. Each entry of `writes[]` carries an `action`:
`create`, `identical`, `adopt`, `conflict` before an apply, and `written`,
`rolled-back`, `failed`, `lost`, or `pending` after one. `lost` means rollback
could not restore an original destination; the retained staging directory holds
the recoverable original.

`--apply` stages bytes under `.fv/.migrate-staging/<run>/` and moves them with
`os.replace`. A failure rolls back every completed move and still prints the
report, which is the only enumeration of what landed. The staging prefix is
structurally excluded from verified-input snapshots, including after a hard kill.
.fv/dispatch.json is the one destination adopted rather than refused:
an existing route keeps every unrelated field and has only `project_root` and
`target_spec` rewritten, so a project `fv_init` already initialized is migratable
without moving the file aside.

The dispatch target comes from the legacy pointer stub first and from the
ledger's citations only when the stub cites nothing. Blocking conditions beyond
destination conflicts: an ambiguous dispatch target (two or more distinct cited
canonical intents) or none at all, a directory under `.colosseum/` that cannot be
listed, a claim whose `required_evidence` names a tool no migrated execution
declares, a recorded command no argv represents (a shell operator, a leading
`NAME=VALUE` assignment, or a shell builtin such as `cd`), and a destination path
that crosses a symlink at any component, including `.fv` itself, or whose nearest
existing parent directory is not writable.

Run `fv_init.py` after `--apply` for the OMP-side settings. Without
`--target-spec` it preserves the migrated `target_spec` and only appends missing
exclusion defaults to `.fv/verified-inputs.txt`. Do not pass `--force` after a
migration: it replaces FV-owned project state, including the migrated dispatch
target. The `.fv/history/` exclusion prefix is structural, so `--force` cannot
drop it.

Keep `.colosseum/` until parity is explicitly accepted: the required evidence
cohorts re-run through `fv_evidence_run` and Gate A plus Gate B passing without
`--expect-snapshot` or `--allow-unbound`. The full operator sequence, including
how to read the report's `unsupported` and `conflicts` entries, is in
[QUICKSTART.md](./QUICKSTART.md#migrating-a-legacy-colosseum-project).

## Verify discovery

Start OMP in the initialized project:

```bash
omp --cwd /absolute/path/to/project
```

After adding or changing the extension root, run this in every already-running
OMP session:

```text
/reload-plugins
/mcp test
```

`/reload-plugins` rebuilds the session's skills, commands, hooks, tools,
agents, and MCP snapshot. `/mcp reload` alone does not rediscover extension
roots. New sessions discover the configured root at startup.

Invoke skills only with the skill namespace:

```text
/skill:fv-intent
/skill:fv-adversarial
/skill:fv-verify
/skill:fv-compose
/skill:fv-panel
```

Named agents use OMP `task` or eval `agent()`:

```python
agent("Review the supplied intent and implementation.", agent="fv-code-adversary")
```

The five read-only review agents set `restrictTools: true`. They receive only `read`, `grep`, `glob`, and `yield`; MCP, extension, and custom tools are disabled. The Quint generator remains unrestricted but MUST run with `isolated=True, apply=False` and its patch MUST pass `$FV_ROOT/scripts/obligation_check.py` before application.

## Verify the project

```bash
uv run --script "$FV_ROOT/scripts/fv_doctor.py" --project /absolute/path/to/project
python3 "$FV_ROOT/scripts/check_dispatch_config.py" \
  /absolute/path/to/project/.fv/dispatch.json
```

The doctor fails for missing extension configuration, package MCP wiring, package agents or skills, dispatch state, a missing or drifted OMP `panel.roles.fv-canonical` definition, an incompatible OMP bridge contract, or a panel with no available candidate at the required thinking policy. OMP compatibility is capability-based: its live version is recorded as provenance, the bridge-contract version and every capability required by `bom.json` must match, and additive capabilities are accepted. Use `--omp /absolute/path/to/omp` when verifying a source build or an executable outside `PATH`.

## CI

```bash
# Required only when `omp` is not on PATH and CI validates a source checkout.
export OMP_SOURCE=/absolute/path/to/oh-my-pi
uv run --script scripts/ci.py
```

R32 imports OMP's real panel resolver from `OMP_SOURCE`, or derives the same
checkout from the `omp` executable on `PATH`. If neither is available, that
suite reports `INCOMPLETE` rather than testing against a stand-in. CI is strict
by default, so `INCOMPLETE` fails. Use `--tolerate-incomplete` only on runners
intentionally missing proof toolchains.

Historical files under `calibration/` retain their original transport provenance. Do not use archived commands as current installation instructions.

<!-- BEGIN GENERATED: voice-roster (source: registry/voices.json via scripts/gen_roster_docs.py - do not edit by hand) -->
**Canonical OMP panel (`canonical-4@sha256:0f73580ef4e3fdf2`).**

- `anthropic/claude-fable-5:xhigh` - Anthropic; route grade `unattested`.
- `openai-codex/gpt-5.6-sol:xhigh` - OpenAI; route grade `unattested`.
- `synthetic/hf:zai-org/GLM-5.2:high` - Zhipu; route grade `degraded`.
- `synthetic/hf:moonshotai/Kimi-K3:high` - Moonshot; route grade `attested`.

Confirm every selector in OMP's `/model` picker before a milestone run.
<!-- END GENERATED: voice-roster -->
