# FV scripts

All live orchestration is OMP-native. Historical calibration artifacts retain their original provenance.

## Project setup and diagnostics

- `fv_init.py`: creates project `.fv/` state, merges the FV checkout into `.omp/config.yml` `extensions:`, and installs `fv-canonical` under OMP's `panel.roles` settings.
- `fv_migrate.py`: shadow-migrates a legacy `.colosseum` project into `.fv/`. Dry run by default; `--apply` writes only under `.fv/` and `--json` emits the deterministic report.
- `fv_doctor.py`: checks exact proof-tool pins, the required OMP capability contract (recording OMP semver as provenance), extension discovery, MCP wiring, dispatch state, static frontmatter, OMP panel-role ownership, and live model candidates.
- `validate_frontmatter.py`: validates `skills/*/SKILL.md` and static `agents/*.md` against the OMP contract.
- `check_dispatch_config.py`: validates the OMP-only `dispatch.json` schema and route hash.
- `gen_roster_docs.py`: regenerates OMP roster blocks and dispatch routes from `registry/voices.json`.

### Legacy migration reports

```bash
uv run --script scripts/fv_migrate.py /absolute/path/to/project --json
uv run --script scripts/fv_migrate.py /absolute/path/to/project --apply
```

`fv_migrate.py` reports in `fv-migration-report/v1`. Dry run is the default;
`--apply` writes only under `.fv/` and never touches `.colosseum/`.

Exit 0 is `status: ok`; 1 is `status: blocked`, a legacy tree that cannot be
inventoried, or an apply that failed and rolled back; 2 a usage error or an
unresolvable project root.

Report fields: `schema`, `project_root` (always `"."`, so a captured report
carries no absolute machine path; the text render names the real directory),
`target_spec` (the elected dispatch target, `null` when none could be elected),
`requested_mode` (`dry-run` or `apply`, what the caller asked for), `mode` (what
the run did), `applied`, `status` (`ok` or `blocked`), `error` (an apply failure
message, otherwise `null`), `counts`, `artifacts[]`, `writes[]`, `conflicts[]`,
`unsupported[]`. A blocked `--apply` reports `requested_mode: apply`, `mode:
dry-run`, `applied: false`, so a consumer can tell a refused apply from a dry run.

- Every legacy file is classified once: `mapped`, `preserved-history`, or
  `unsupported`. A `<file>#layers.<name>`, `<file>#claims.<id>`, `<file>#ids.<id>`
  or `<file>#document` row names an item inside an otherwise-mapped file that did
  not come across with the meaning the file's mapping implies.
- `unsupported[]` blocks the run: an unknown or malformed legacy schema, a
  malformed claim, a verification layer no argv execution can carry, a claim whose
  `required_evidence` names a tool no migrated execution declares, two legacy
  targets whose obligation ids collide after normalization, a target that
  normalizes to an empty id, two executions that would declare one
  `evidence_tool` id, an ambiguous dispatch target (two or more distinct canonical
  intents cited by whichever document decides), no dispatch target at all, a
  directory under `.colosseum/` that cannot be listed, an unreadable or
  non-regular file.
- `conflicts[]` blocks the run as well: a `.fv/` destination that exists with
  different content (both hashes are printed), crosses a symlink at any path
  component including `.fv` itself, is a directory, sits under a non-directory
  parent, or whose nearest existing parent directory is not writable.
  `--apply` refuses a blocked migration and writes nothing.
- `writes[]` lists each intended `.fv/` path with the SHA-256 of its bytes and an
  `action`: `create`, `identical` (byte-equal already, nothing to do), `adopt`
  (`.fv/dispatch.json` only), `conflict` (preflight refused it), or, in an apply,
  `written`, `rolled-back`, `failed`, `pending`. Re-running a successful `--apply`
  is byte-idempotent: every destination reports `identical`.
- `--apply` is all-or-nothing. Every byte is staged under `.fv/` first, then each
  destination is moved into place with `os.replace`, which does not follow a
  symlink at the final name. A failure during the moves rolls back every
  destination already moved, and the report is printed anyway because it is the
  only enumeration of what landed: `rolled-back` was undone, `failed` is the write
  that raised, `pending` never started, and `written` in a failed apply means the
  rollback itself could not undo that destination (`error` carries the reason).
- `.fv/dispatch.json` is the one destination adopted rather than refused. An
  existing route keeps every other field, other `omp_native` keys and other
  top-level keys alike, and has only the `project_root` and `target_spec` this
  migration owns rewritten; the write is reported as `adopt` with the before and
  after in its `detail`. A route already carrying `"."` and the elected
  `target_spec` is left byte-identical.
- The dispatch target is elected from the legacy pointer stub first: a `*intent.md`
  path cited by `.colosseum/intent.md` that resolves under the project root wins,
  and the ledger's citations decide only when the stub cites none. Mention
  frequency never votes. Two or more distinct candidates in whichever document
  decides is an `unsupported` row, and so is no candidate at all, since a
  `target_spec` naming nothing cannot resolve for any gate, producer, or skill.
  With no cited external intent, `.colosseum/intent.md` itself becomes
  `.fv/intent.md`. The elected spec is the report's own `target_spec` field, not
  only a sentence in a detail string.
- Mapped: `ledger.md` verbatim, the elected intent as the dispatch target,
  `obligations.json` + `g1-claims.json` to `.fv/obligations.json` `system_claims`,
  `evidence/runs/layer-runs.json` to `.fv/verification-plan.json`,
  `verified-inputs.txt` to `.fv/verified-inputs.txt`. Everything else
  is preserved under `.fv/history/colosseum/`, byte-for-byte plus the executable
  bit; no other mode bit, ownership, timestamp, or empty legacy directory is
  represented. `.fv/history/` is a structural snapshot exclusion prefix, so
  quarantined history cannot move the content snapshot evidence binds to.
- Legacy per-claim evidence is history, never live evidence: a v1/v2 record is
  copied under `.fv/history/colosseum/` and never into `.fv/evidence/`, so Gate B
  cannot see it and every migrated obligation stays uncovered until an
  `fv-evidence-run/v3` record binds it. `.colosseum/` is read-only to the tool and
  is never deleted.
- The legacy `verified-inputs.txt` is an include list, and FV include mode means
  the same thing, so it is translated rather than inverted: the migrated policy
  declares `mode: include`, keeps every legacy source root verbatim, rebinds an
  entry naming a legacy manifest to the FV artifact its content migrated to
  (`.colosseum/obligations.json` and `.colosseum/g1-claims.json` to
  `.fv/obligations.json`), and additionally binds the elected canonical target,
  whichever of `.fv/obligations.json` and `.fv/verification-plan.json` the run
  wrote, and the policy file itself. An entry naming legacy bytes that migrate to
  history alone binds nothing and is reported as a `#<entry>` deviation row. A
  legacy list that is not valid UTF-8, does not parse under the path grammar,
  declares no entries, or has no entry left to translate is `unsupported` and
  blocks the migration: a policy binding only FV's own artifacts would keep every
  record fresh across every source edit. The exact legacy list is preserved under
  `.fv/history/colosseum/` either way, and a legacy tree with no include list gets
  the exclusion-mode defaults instead.
- Legacy layers with a pyramid equivalent are renamed (`proptest` to `proptests`);
  every other layer, `quint` included, becomes an `fv-verification-plan/v1` custom
  layer that runs after the built-in layers in lexical order. A layer any migrated
  claim names is written `required: true` and joins the G2 gating set, whatever the
  legacy `required` flag said, because Gate B demands evidence for every declared
  obligation regardless of that flag; when no legacy claim converted at all, every
  recorded layer is required. An untranslatable layer blocks the migration rather
  than yielding a partial plan: shell operators or expansions in the recorded
  command, a leading `NAME=VALUE` assignment, a segment whose `argv[0]` is a
  builtin whose effect dies with the process (`cd`, `export`, `source`, `eval`,
  ...), a missing or escaping `cwd`, a malformed environment, the reserved id
  `floors`.
- A legacy `a; b; c` command becomes three executions in one layer; the last
  segment carries the bare layer id as its `evidence_tool` because its exit status
  is what the legacy manifest recorded, and earlier segments get `<layer>:<index>`.
  Two independently recorded runs of one layer have no last-segment relation to
  inherit, so they are merged into one cohort keyed `<layer>:run<k>.<segment>`
  (only the final execution keeps the bare id) and the merge is reported as a
  `#layers.<name>` deviation row.
- `scope`, `waiver`, `evidence_class`, `profile`, and `environment_policy` are
  retained rather than summarized when they carry the type the migrated manifest's
  slot holds. Any other legacy claim key, and any of those five carrying a type
  its slot cannot hold, is carried verbatim under the claim's `legacy_fields`
  (document-level keys under `migration.legacy_fields`) and named in a
  `#claims.<id>` or `#document` deviation row, so a dropped `waiver` can neither
  vanish nor be implied to have migrated as a waiver.
- Obligation and claim ids are normalized deterministically: the legacy target
  splits at its first colon, each part collapses every run of characters outside
  `[A-Za-z0-9._-]` to a single `-` and drops leading/trailing `.`, `_`, `-`, and
  the id is `<layer>.<name>` (`quint:invS7` to `quint.invS7`). Every migrated id
  is therefore directly usable as an `fv_evidence_run` `claim_id`, so no manual
  rename stands between `--apply` and producing evidence. Each rewritten
  obligation carries `legacy_id` with the exact legacy string (a witness also
  keeps the unnormalized target name as its `name`), and `system_claims.depends_on`
  names the normalized ids. Ids are never disambiguated by suffix: two legacy
  targets normalizing to one id, or a target normalizing to nothing, are
  `unsupported` rows that block the run.

Operator sequence after `--apply` (full version in
[QUICKSTART.md](../QUICKSTART.md#migrating-a-legacy-colosseum-project)):
`fv_init.py` without `--force` for the OMP settings, review the converted claims
with `coverage_dashboard.py` and the plan with `pyramid_run.py --plan`, re-run
every required cohort through `fv_evidence_run`, then Gate A and Gate B without
`--expect-snapshot` or `--allow-unbound`. Keep `.colosseum/` until that parity is
explicitly accepted.

## Verification gates

- `check_ledger_references.py`: Gate A, including required content hashes for every cited executable artifact.
- `check_evidence_records.py`: Gate B, including raw-artifact resolution, SHA-256 recomputation, PASS markers, obligation compatibility, and system-claim cohort coverage.
- `obligation_check.py`: validates the frozen obligation manifest against generated specifications.
- `lean_axiom_gate.py`: rejects prohibited Lean axioms.
- `check_ledger_version.py`: validates the ledger version envelope.
- `check_fixture_tracking.py`: fails when required fixtures are untracked.
- `ci.py`: runs the default fail-closed gate set. `INCOMPLETE` fails unless `--tolerate-incomplete` is explicit.

### Evidence records (`fv-evidence-run/v3`)

The `fv_evidence_run` tool (`tools/evidence-run.ts`) writes one record per claim at
`.fv/evidence/records/<claim_id>.json` and its raw log under `.fv/evidence/raw/`. Gate B consumes
those records; nothing else is evidence. Field-by-field shape, with a worked single-execution
invariant and a worked multi-execution system claim, is in
[`docs/dogfood-evidence.md`](../docs/dogfood-evidence.md).

- Source binding is `bindings.source_snapshot`, a verified-input content snapshot
  `sha256:<hex>` over every tracked-or-untracked, unignored, selected file (`+dirty` suffix
  when a selected path is modified), not a commit id. Which files are selected comes from
  `.fv/verified-inputs.txt`: with no `mode:` directive, or with `mode: exclude`, its entries
  are exclusion prefixes and everything else git reports is a verified input; with
  `mode: include` as its first non-comment line its entries are the allowlist, plus the
  policy file itself, so revising the policy moves the snapshot. Structural exclusion
  prefixes apply first in either mode and no project file can drop them:
  `.fv/evidence/`, `.fv/verify/`, `.fv/panels/`, `.fv/changes/`, `.fv/attacks/`,
  `.fv/code-adversarial/`, `.fv/history/`, `.fv/.migrate-staging/`, `.colosseum/`.
- Intent binding is `bindings.intent_path` (repo-relative canonical target, resolved from
  `.fv/dispatch.json` `omp_native.target_spec`, default `.fv/intent.md`) plus
  `bindings.intent_hash` over that file's bytes. `check_evidence_records.py --json` echoes the
  `intent_path` it resolved (`null` when the caller supplied `--expect-intent` or
  `--allow-unbound`), the expected snapshot, the per-claim `obligation_kinds`, and the
  `required_evidence` map it enforced.
- `bindings.executions` is the nonempty execution cohort: per entry `tool`, `evidence_class`,
  `command` argv array, repo-relative `cwd`, `toolchain_digests`, `raw_output_path`,
  `raw_output_hash`, `result`, `run_id`, and optional `pass_marker`. One raw log per execution
  (`.fv/evidence/raw/<claim_id>-<run_id>.log`); nothing is concatenated.
- The producer takes exactly one of `command` (single argv array, with optional top-level `cwd`,
  `tool`, `pass_marker`) or `executions` (nonempty array of
  `{tool, command, evidence_class?, cwd?, pass_marker?}`, unique `tool` IDs, no top-level
  `cwd`/`tool`/`pass_marker`). The single-command form records exactly one entry.
- Record-level `command`, `raw_output_path`, `raw_output_hash`, `toolchain_digests`, and
  `configuration.cwd`/`pass_marker` are derived from `executions[0]` verbatim, and Gate B enforces
  that derivation. Record-level `run_id` stays the cohort timestamp. Record `result` is PASS only
  when every execution is PASS and snapshot, intent hash, and manifest hash stayed stable across
  the cohort with no dirty verified inputs.
- Default freshness is v3: with neither `--expect-snapshot` nor `--allow-unbound`, the gate
  recomputes the current snapshot and requires an exact match, so a `fv-evidence-run/v2` record
  (commit-id source binding) is stale by default and validates only under an explicit
  `--expect-snapshot`/`--allow-unbound` invocation.
- `obligations.json` may declare `system_claims` beside `invariants` and `witnesses`. Each claim
  carries `depends_on` (nonempty, unique, naming declared invariants and witnesses only) and
  `required_evidence` (nonempty, unique tool IDs). Gate B aggregates claims into the required set
  with kind `system_claim`, and a claim PASSes only when every `required_evidence` tool ID appears
  among its PASS executions.

### Verification plans (`fv-verification-plan/v1`)

- `pyramid_run.py --plan <path>` reads a declarative plan (conventionally
  `.fv/verification-plan.json`) whose `layers` map declares, per layer, `required` plus a nonempty
  `executions` array of `{argv, cwd, timeout_seconds, env?, evidence_tool?}`. Layers the plan does
  not name keep the built-in defaults; without `--plan` the runner is the legacy runner.
- No shell strings, no ambient environment mutation: declared `env` merges over the subprocess
  environment, `cwd` must stay repo-relative, and escapes are rejected.
- One `evidence_tool` id names exactly one invocation: the same id twice anywhere in the plan is
  a rejection, not a merge, because the runner keys each measured duration by it. A plan naming a
  tool this machine does not have is a `failed` layer carrying a per-invocation `launch_errors`
  row, so an absent binary still produces a report instead of a traceback.
- Shipped example: [`verification-plan.example.json`](./verification-plan.example.json), walked
  through in [`docs/dogfood-evidence.md`](../docs/dogfood-evidence.md).

## OMP orchestration

- `skills/fv-adversarial/omp_fanout.py`: failure-isolated adversarial fan-out over the generated `omp_native` route.
- `skills/fv-panel/omp_panel.py`: blinded draft, cross-review, and synthesis panel engine.
- `omp_calibration_session.py`: starts an OMP session with fallback suppression for selected calibration routes.
- `fv_run.py`: durable run-state manifest for local artifact coordination.

## Measurement and conformance

- `pyramid_run.py`: verification pyramid runner; `--plan` executes a declared `fv-verification-plan/v1` document instead of the built-in layer defaults.
- `coverage_dashboard.py`: per-claim evidence status. `--manifest` derives required IDs from
  `invariants` + `witnesses` + `system_claims`, so every claim is a row carrying its
  `obligation_kind`. A system-claim row shows `required_evidence`, the record's execution cohort,
  and per-required-tool observed results (`evidence_coverage`, `no-execution` for a tool that
  never ran); it reports `evidence-gap` when a required tool never PASSed or any cohort execution
  did not PASS, and `dependency-gap` when the cohort is complete but a `depends_on` obligation is
  not covered this run. Both are INCOMPLETE, never PASS. `--require` may narrow a `--manifest`
  run; an ID absent from the manifest is an error.
- `self_measure.py`: yield, cost, and routing metrics over recorded artifacts.
- `recall_score.py`: seeded-defect recall scoring.
- `benchmark_run.py`: benchmark harness; callers provide the OMP-native dispatch command.
- `benchmark_run.py`, `itf_replay.py`, and `benchmark_run.py`: replay and benchmark support.
- `check_doc_links.py`: documentation-link validation.

### Voice roster

<!-- BEGIN GENERATED: voice-roster (source: registry/voices.json via scripts/gen_roster_docs.py - do not edit by hand) -->
| Voice id | OMP selector | Family | Status | OMP calibration | Route grade |
|---|---|---|---|---|---|
| `claude-agent` | `anthropic/claude-fable-5:xhigh` | Anthropic | canonical-panel | pending | unattested |
| `kimi-k2.6` | `burnt/cloudflare-100/@cf/moonshotai/kimi-k2.6` | Moonshot | candidate | pending | not-run |
| `gpt-5.6-sol` | `openai-codex/gpt-5.6-sol:xhigh` | OpenAI | canonical-panel | pending | unattested |
| `glm-5.2` | `synthetic/hf:zai-org/GLM-5.2:high` | Zhipu | canonical-panel | pending | degraded |
| `kimi-k3` | `synthetic/hf:moonshotai/Kimi-K3:high` | Moonshot | canonical-panel | Seeded-defect recall 6/7 on the held-out leasedb corpus over the OMP-NATIVE transport at synthetic/hf:moonshotai/Kimi-K3:high, blinded single pass under the deny-first fv-spec-adversary profile (calibration/2026-07-28-r3; D1 excluded for all voices as mis-specified). Cleared the pre-registered floor. The ONLY voice in that run whose served route was positively attested: its sole configured fallback target (fireworks/kimi-k3) had no usage-ledger counter, so a degrade would have created a visible entry and none appeared. Missed D8, anchoring the waiter leak at register_waiter rather than at the release site a fix would change. Transcript audited clean. Scope: one voice, one pass, one corpus, this rung only. | attested |
<!-- END GENERATED: voice-roster -->
