# Change record: migration readiness — portable inputs, evidence cohorts, Colosseum shadow migration

- Date: 2026-09-15
- Classification: intent-touching
- Commits: `f2d0556` (portable FV evidence inputs), `9eb3709` (composed FV evidence cohorts), `b1003a3` (safe Colosseum shadow migration), `8508604` (migrated FV claims made directly executable), `5dc765e` (migration trust boundaries hardened), `d5ce1c2` (Gula migration verification recorded), `dec002d` (this record finalized), `0fa4e22` (legacy migration input contracts completed: the closure wave described below, committed rather than the worktree state an earlier draft of this line claimed), `368cae0` (legacy ledgers gated before migration). Real-project readiness across all ten legacy trees is recorded separately in `.fv/changes/2026-09-15-real-project-readiness.md`, which owns the per-project dry-run table, the blocker classes, the old-versus-current Gate A comparison, and the Gula execution record; this record owns the migration authority and the contract.
- Authority: the **user-authorized migration requirements** given in the session that produced these commits, restated here so the authority is a committed artifact rather than an ephemeral one. Those requirements: dry run is the default and writes nothing; `--apply` writes only under `.fv/`; `.colosseum/` is read-only and stays byte-identical; legacy v1/v2 evidence is never placed where Gate B would read it as live v3 evidence; no verification layer the legacy tree recorded is silently omitted from the migrated plan; migrated obligation ids are directly usable by the evidence producer, with the legacy string retained for traceability and any id collision blocking the run; evidence binds to verified-input content rather than to a commit id, and no absolute path enters a persisted trust artifact. The working notes that carried those requirements during the session were never committed, so they are not reviewable artifacts and no claim here rests on reading them: this record, the three commits, and the tests they name are what a later reviewer reads. This extension repository declares no canonical `.fv/intent.md` (`scripts/fv_project.py` resolves a *target project's* intent, and the FV repo itself declares none), so there is no intent document to revise.
- Compatibility posture: established. Existing `fv-evidence-run/v2` records and the existing one-command CLI surface remain accepted; new producer output is `fv-evidence-run/v3`.

## Description

Six trust-surface changes plus two migration surfaces, all aimed at one property: FV's evidence must be earnable, checkable, and portable in a project whose only record of past verification is a legacy `.colosseum` tree, without that tree being touched.

### 1. Canonical target declaration

`.fv/dispatch.json` → `omp_native.target_spec` is now **the** intent/target declaration, and `scripts/fv_project.py` (`resolve_target`, `fv_project.py target --root <project>`) is the single implementation every skill, gate, and tool resolves through. The declaration is resolved against the project root, never the cwd and never a fixed search order. A missing `target_spec` defaults to `.fv/intent.md`; a relative value resolves under the project root; an absolute value is accepted only when it resolves inside the project root; a missing, directory, symlink, or escaping target is an error rather than a cue to look elsewhere. The initializer writes `project_root: "."` and a repo-relative `target_spec` (`fv_init.build_dispatch_json`, `fv_init.portable_target_spec`), and rewrites a non-portable declared spec into its repo-relative form or fails naming the project root. The former "`.fv/intent.md` canonical, root `intent.md` recognized alternative" pair is gone: a project that wants the intent at top level declares `target_spec: "intent.md"`.

### 2. Verified-input content snapshot

Evidence is bound to the content of the project's verified inputs rather than to a commit plus an opaque dirty flag. `.fv/verified-inputs.txt` is an **exclusion**-prefix list (blank and `#` lines ignored, directory entries end in `/`), defaulting to `.fv/evidence/`, `.fv/verify/`, `.fv/panels/`, `.fv/history/`, `.fv/.migrate-staging/`, `.colosseum/` (`fv_project.DEFAULT_EXCLUSIONS`). The candidate set comes from `git ls-files --cached --others --exclude-standard -z`; the snapshot is SHA-256 over, for each candidate in sorted repo-relative POSIX-path order, the path, a NUL, the file-content SHA-256 hex, and a newline, emitted as `sha256:<hex>` (`fv_project.content_snapshot`, `is_content_snapshot`). Symlinks and candidates resolving outside the root are rejected. `tools/evidence-run.ts` recomputes the snapshot, the intent hash, and the manifest hash **around every execution**, so a command that edits a verified input cannot ship as PASS evidence for itself or for an earlier execution in the same record. Gate B (`scripts/check_evidence_records.py`) recomputes the current snapshot and, by default, demands an exact match; `--expect-snapshot` / `--allow-unbound` remain the explicit escape hatches under which a v2 record still validates. As committed, the exclusion defaults were only the first three prefixes plus `.colosseum/`, and `.fv/history/` was a line the migrator wrote into the project file; the adversarial pass (evidence-architecture F5, shadow-migration F13) made `.fv/history/` a structural default, and the correction wave added the migrator's staging prefix `.fv/.migrate-staging/` beside it, so neither quarantined history nor a staging tree a killed `--apply` left behind can be dropped by `fv_init --force` or enter the binding. The same pass made a non-regular verified input a classified error rather than an open that can block forever, and made an ambiguous line terminator in the exclusion list a rejection on both ends; the correction wave extended that to a byte-order mark, which the two decoders had been disagreeing about silently.

Superseded in part by the closure wave below, committed as `0fa4e22`: the list
is now a two-mode policy (`mode: exclude`, which is what a directive-free file
such as the one this section describes means, or a self-binding `mode: include`
allowlist), the structural defaults are nine prefixes rather than six, and the
hash order is the UTF-8 bytes of the path rather than each language's string
comparison.

### 3. Gate A citation parsing

`scripts/check_ledger_references.py` replaced its single ambiguous alternation with an explicit tokenizer plus one citation grammar (`<path>:<line>[@sha256:<12hex>]`). Four citation forms are now parsed deliberately: a backticked path citation, a fully backticked `code:` annotation, a plain `code:` annotation, and a `code:` annotation with a backtick-quoted path. Consequences that matter for trust: a fully backticked `code:` annotation no longer parses as a file literally named `code: src/...` and then fails as missing; a `code:` value that did not parse but was shaped like a citation is a **loud failure** instead of a silently skipped check; a citation carrying `@sha256:` with a truncated or non-hex binding is reported as drift rather than read as prose; and `Depends on:` block detection accepts the emphasized and heading forms (`**Depends on:**`, `**Depends on**:`, `### Depends on:`), so per-link Kani coverage actually runs on a real dossier-shaped ledger instead of finding no blocks at all. Containment is unchanged: every cited path must resolve inside the canonical root.

### 4. System claims and evidence cohorts

`obligations.json` accepts `system_claims` beside `invariants` and `witnesses`. A `system_claim` carries an `id`, a nonempty unique `depends_on` naming declared invariants/witnesses, and a nonempty unique `required_evidence` naming tool/layer IDs. Gate B fails malformed claims and unknown dependencies in `_id_list` / `_validate_system_claim`, and duplicate obligation IDs in `load_manifest` (all three in `scripts/check_evidence_records.py`; this record originally cited one line range that covered only the first two, which the adversarial pass flagged as an INFO finding, and every code citation in this record is now a symbol name so a refactor moves the symbol rather than silently invalidating the citation). `fv-evidence-run/v3` bindings add `intent_path` and a nonempty `executions` array; each execution records its tool, evidence class, argv `command`, repo-relative `cwd`, executable identity/digest/version, raw-output path and hash, result, `run_id`, and optional `pass_marker`. The existing one-command API still produces exactly one execution; the new `executions` parameter produces a **cohort** whose verdict is atomic — every execution must PASS and every binding must have held still across the whole run, otherwise the record is FAIL (the cohort verdict in `fv_evidence_run`, `tools/evidence-run.ts`). A system claim PASSes only when every one of its `required_evidence` tool IDs appears among PASS executions; `scripts/coverage_dashboard.py` reports the two ways that fails (`evidence-gap` for a required tool that never PASSed or a non-PASS execution inside an otherwise-covering cohort, `dependency-gap` for a fully-PASS cohort whose dependency is uncovered). `evidence-gap` is the string the tool has always emitted; this record, `CONCEPTS.md`, `ROADMAP.md`, and `docs/incremental-reverification.md` previously spelled it `coverage-gap`, which no consumer could ever match.

### 5. Configurable verification layers, including custom layers

`scripts/pyramid_run.py --plan PATH` reads an optional `fv-verification-plan/v1` document whose `layers` map gives each layer a `required` flag and a nonempty `executions` array of `{argv, cwd, timeout_seconds, env?, evidence_tool?}`. There are no shell strings anywhere in the schema; escapes and ambient environment mutation are rejected, and declared `env` is merged over the current subprocess environment rather than replacing it. Layer ids are not restricted to the pyramid's defaults: any id matching `[A-Za-z0-9][A-Za-z0-9._:+/-]*` that is not a reserved floor is a **custom layer**. Known layers execute in `LAYER_ORDER` (cheapest first, types gating everything below), then custom layers execute in lexical order — the only total order available for project-chosen ids. A `required: true` custom layer joins the G2 `required_layers` set, every custom execution goes through the same argv/cwd/timeout/env validation and produces the same report shape, `required: false` never un-requires a layer, and a types failure marks every required or declared layer — custom included — `not_run`. A malformed plan is an ERROR with exit 2 before any layer runs; it is never a silently-legacy run.

Superseded in part by the closure wave below (`0fa4e22`): the plan is no longer
reached only through `--plan PATH`. `pyramid_run.py` auto-discovers
`<crate>/.fv/verification-plan.json`, executes it whenever `--plan` is absent,
reports its provenance in `plan.discovery`, and treats a present-but-unusable
plan as exit 2; `--no-plan` is the only way to run the built-in defaults against
a project that has one.

### 6. Portability

The three surfaces that previously assumed this machine's layout are now project-rooted and content-addressed: the target declaration (repo-relative, resolved against the project root), the evidence binding (content snapshot over git-enumerated inputs, not a commit id), and the plan's execution `cwd`s (repo-relative, escape-rejected). `intent_path` in a v3 record is itself containment-checked against the repo root by Gate B. The practical effect is that a record earned in one clone or worktree is checkable in another with the same content, and an absolute path can no longer leak into a persisted trust artifact.

### 7. Shadow migration: dry-run default, `--apply` writes only `.fv`

`scripts/fv_migrate.py PROJECT [--apply] [--json]` reads a legacy `.colosseum` tree and is non-destructive by construction: dry run is the default and writes nothing; `--apply` writes only under `.fv/`; `.colosseum/` is only ever read and stays byte-identical. Mappings: `.colosseum/ledger.md` → `.fv/ledger.md` verbatim; `.colosseum/intent.md` (or a declared external canonical intent, e.g. a `docs/intent.md` the ledger references, reached through a legacy pointer stub) → the dispatch target; `obligations.json` joined with `g1-claims.json` → `.fv/obligations.json` with each legacy claim as a `system_claims` entry (`depends_on` = its `required_targets` under the id normalization described below, `required_evidence` = its `layers`, each distinct target synthesized as an invariant or — for `proptest:`/`test`-prefixed targets — a witness, with `scope`, `waiver`, `evidence_class`, `profile`, and `environment_policy` retained rather than summarized); `evidence/runs/layer-runs.json` → `.fv/verification-plan.json`. Every source artifact is classified as exactly one of `mapped`, `preserved-history`, or `unsupported`, with sub-artifact rows (`<file>#layers.<name>`, `<file>#claims.<id>`) emitted when an item inside a mapped file deviates from its file's mapping, so a lossy translation names what it dropped. Any `unsupported` entry or destination conflict blocks the run **before any write**. Re-running `--apply` is byte-idempotent; an existing destination with different content fails. `--json` emits a deterministic `fv-migration-report/v1` report. Exit 0 `ok`, 1 `blocked`, 2 usage.

Two deliberate no-omission rules: a legacy layer command that no argv represents (any shell operator or expansion character — wrapping it back into `sh -c` would launder the shell the plan schema exists to exclude), a missing or escaping `cwd`, a malformed environment, or a reserved id (`floors`) is `unsupported` and blocks the migration, because a plan that silently omits a recorded layer would present unrun verification as complete. And every legacy layer keys the plan under its own id when it has no pyramid equivalent, so a layer named in any `system_claim.required_evidence` — `quint` in particular — migrates as a custom layer instead of being dropped or downgraded. Names with a pyramid equivalent are renamed to it (`proptest` → `proptests`).

Migrated obligation ids are usable by the evidence producer without a human edit. Legacy `required_targets` and legacy claim ids are normalized deterministically: split at the first colon, collapse every maximal run of characters outside `[A-Za-z0-9._-]` in each part to a single `-`, strip leading and trailing `.`, `_`, `-`, and join as `<layer>.<name>` (`quint:invS7` → `quint.invS7`, `verus:contract::state::Machine` → `verus.contract-state-Machine`). Every migrated id therefore satisfies the `[A-Za-z0-9][A-Za-z0-9._-]*` that `fv_evidence_run` requires for `.fv/evidence/records/<claim_id>.json`, so a migrated obligation can be covered by a producer-written record immediately after `--apply`. The alternative the requirements rejected was documenting a manual post-migration rename: an operator hand-editing obligation ids and every `depends_on` that references them is an unverified transcription step between a mapped manifest and the evidence that is supposed to bind to it. Traceability is kept in the artifact rather than in the operator's memory: each obligation whose id was rewritten carries `legacy_id` with the exact legacy string, a migrated witness keeps the unnormalized legacy target name as its `name`, and `system_claims.depends_on` names the normalized ids in legacy `required_targets` order. Collisions are never resolved by suffixing, because a suffix decides silently which of two legacy targets an evidence record binds to: two legacy ids that normalize to one id are an `unsupported` row (`.colosseum/g1-claims.json#ids.<migrated id>`) naming every colliding legacy string, and a target or claim id that normalizes to the empty string is an `unsupported` row on its owning claim (`#claims.<claim id>`). Either one blocks the migration with zero writes, like any other `unsupported` entry.

### 8. Old-evidence quarantine

Legacy per-claim evidence under `.colosseum/evidence/` is **never** copied into `.fv/evidence/`. A v1/v2 legacy record is history, and placing it in the live evidence directory would present it as an `fv-evidence-run/v3` record whose bindings it cannot satisfy. It — and every other legacy file with no mapping — is preserved byte-for-byte under `.fv/history/colosseum/<path relative to .colosseum>` and classified `preserved-history`. `.fv/history/` is added to the verified-input exclusion list, so quarantined history cannot perturb the content snapshot that fresh evidence binds to. Legacy `verified-inputs.txt` is an *include* list, the exact inverse of FV's exclusion list; inverting it would mean enumerating the complement of the repository, so it is preserved as history and FV's conservative defaults are written instead. As committed, the `.fv/history/` exclusion above was a line the migrator wrote into `.fv/verified-inputs.txt`; the adversarial corrections promote it to a structural default in `fv_project.DEFAULT_EXCLUSIONS` and the `tools/evidence-run.ts` mirror, so the guarantee no longer depends on a file `fv_init --force` rewrites. The migrator's staging prefix `.fv/.migrate-staging/` is a structural default for the same reason: `--apply` stages every write under `.fv/.migrate-staging/<pid>-<random>/`, and a completed apply or a completed rollback removes it. Two paths leave it: a migration killed outright, and a rollback that could not put a destination back, which keeps its staging tree deliberately because the aside-moved original inode is then the only copy of the replaced bytes (the error names the retained directory). A stranded staging tree that entered the snapshot would stale every live record in the project. Either residue is safe to delete once accounted for and is deliberately not swept: no later run can distinguish a dead staging tree from a concurrent migration's live one, or from a rollback's surviving originals.

Superseded in part by the closure wave below (`0fa4e22`): FV now has an include
mode, so the legacy include list is translated into it rather than
preserved-and-replaced. The legacy bytes are still kept verbatim as history, and
a legacy tree with no include list still gets the exclusion defaults.

## Affected verification surface

- Quint: N/A in this repository. The migrator's obligation-to-`quint`-layer path is exercised only against fixtures.
- Lean: N/A
- Verus: N/A
- Kani: N/A (Gate A's per-link `kani:` coverage check now fires on emphasized `Depends on:` blocks it previously skipped)
- Gates: Gate A (`check_ledger_references.py`) citation grammar and depends-block detection; Gate B (`check_evidence_records.py`) v3 bindings, snapshot recomputation, `system_claims` validation, `intent_path` containment; `pyramid_run.py` plan validation and `required_layers` composition; `coverage_dashboard.py` cohort coverage
- Compose: a system claim is now a first-class ledger obligation whose PASS is a conjunction over a named tool cohort, not a single command's exit code

## Focused verification already run

Orchestrator-run, all PASS. This is focused verification, **not** a full CI run:

- Phase 1 (portable inputs): `python py_compile` over the changed Python modules; `tests/r1_r21_r27_ledger_gates.py`, `tests/r2_r5_concurrency_containment.py`, `tests/r6_manifest_failclosed.py`, `tests/r29_omp_integration.py`, `tests/r30_omp_native_dispatch.py`, `tests/r31_omp_panel.py`, `tests/r34_evidence_run.py`
- Phase 2 (evidence cohorts): `py_compile`; `tests/r6_manifest_failclosed.py`, `tests/r34_evidence_run.py`, `tests/m1_coverage.py`, `tests/r14_cli_contracts.py`, `tests/r28_baseline_floors.py`, `tests/r20_verdict_truth_table.py`
- Migration phase, after the custom-layer and safe-id corrections: `py_compile`; `tests/r14_cli_contracts.py`, `tests/r28_baseline_floors.py`, `tests/r35_colosseum_migration.py`, `tests/r36_dossier_rehearsal.py`
- `git diff --check` clean after phases 1 and 2, and in the migration phase

`tests/r35_colosseum_migration.py` asserts the non-destructive properties directly: dry run writes nothing, `--apply` writes only under `.fv/`, and `.colosseum/` is byte-identical before and after (digest over the whole legacy tree). `tests/r36_dossier_rehearsal.py` is a **fixture** rehearsal reproducing dossier-shaped artifacts (external canonical intent with a `.colosseum/intent.md` pointer stub, bold `**Depends on:**` links with hash-bound backticked `code:`/`kani:` citations, a `colosseum-obligations` C-01..C-09 claim list, a `colosseum-g1-claims` map with per-claim layers and `<layer>:<target>` required targets).

Not claimed by the runs above: any `--apply` against a real legacy project. The
focused runs listed here predate the adversarial corrections described below,
the closure wave (`0fa4e22`), and the ledger-readiness preflight (`368cae0`).
What covers those is the Gula execution recorded under "Deployment
verification" below (`tests/run_all.py` 32 of 32 suites PASS, `scripts/ci.py` 6
of 6 PASS) plus the ten-project dry run, every one of which wrote nothing.

## Adversarial review

Completed 2026-09-15 by two read-only operators, neither the author of the code under review, each with one surface. Both reports are persisted verbatim and are the authority for the corrections below:

- `.fv/code-adversarial/2026-09-15-evidence-architecture.json` — `scripts/fv_project.py`, `tools/evidence-run.ts`, `scripts/check_evidence_records.py`, `scripts/coverage_dashboard.py` and their suites. **17 findings: 1 HIGH, 4 MEDIUM, 1 MEDIUM-LOW, 1 LOW-MEDIUM, 8 LOW, 2 INFO.**
- `.fv/code-adversarial/2026-09-15-shadow-migration.json` — `scripts/fv_migrate.py` (all lines), `scripts/pyramid_run.py`'s plan path, `scripts/check_ledger_references.py`, `scripts/fv_init.py`, and the migration docs. **15 findings: 2 high, 2 medium-high, 6 medium, 3 low-medium, 2 low.**

Evidence-architecture findings and where each correction landed:

- **F1 (HIGH)** a per-execution `evidence_class` could sit beneath a stronger record class, bypassing both the unwaived-assumption rule and the obligation/class compatibility table → `_assumed_evidence` quantifies over the record *and* every execution, `_execution_defects` applies `OBLIGATION_EVIDENCE_COMPATIBILITY` per execution against the obligation kind, `coverage_dashboard.py` imports and applies the same tables, and the producer refuses to write an assumed class at all (`rejectAssumedClass`).
- **F2 (MEDIUM)** one PASS artifact could discharge a whole cohort and every claim in a run → `raw_output_path` must be distinct across a cohort, a producer-profile record must name `.fv/evidence/raw/<claim_id>-<run_id>.log`, and a v3 artifact cited by two claims is a defect.
- **F3 (MEDIUM)** the `VERIFIED` banner was identical for a recomputed, a pinned, and an `--allow-unbound` run → the verdict scope carries `binding=recomputed|pinned|unbound` and the JSON report carries the same `binding` field. (Closure wave `0fa4e22`: only the weaker two qualify the scope, and the recomputed run keeps the unqualified `VERIFIED[profile=...]`; the report's `binding` field still names all three.)
- **F4 (MEDIUM)** the dashboard validated only the v2 binding set and skipped unreadable cohort entries, so its VERIFIED could contradict Gate B's INCOMPLETE → it imports Gate B's field lists and v3 cohort shape, requires `intent_path` and a nonempty `executions`, and counts an unreadable tool id as a non-passing cohort entry.
- **F5 (MEDIUM)** `.fv/history/` was not a structural exclusion, so `fv_init --force` pulled quarantined legacy evidence back into the snapshot and staled every live record → added to `fv_project.DEFAULT_EXCLUSIONS` and to the `tools/evidence-run.ts` mirror, together with the migrator's staging prefix `.fv/.migrate-staging/`, which made the structural defaults the six prefixes section 2 lists; the closure wave (`0fa4e22`) then took them to nine.
- **F6 (MEDIUM-LOW)** the legacy single-command branch never checked the tool id, and manifest ids outside the producer's grammar went unflagged → `EVIDENCE_TOOL_ID` is applied to `tool` and to the basename fallback, and an obligation id outside `PRODUCER_CLAIM_ID` is rejected as unusable rather than merely unsatisfied.
- **F7 (LOW-MEDIUM)** exclusion-list parsing diverged between Python and TypeScript on non-LF terminators → both ends reject an ambiguous terminator, and (in the final wave) a `U+FEFF` byte-order mark anywhere in the list, instead of deriving two exclusion sets from one list.
- **F8 (LOW)** a tracked path replaced by a FIFO hung the snapshot on both sides → a non-regular verified input is classified, never opened.
- **F9 (LOW)** no rule forbade a `+dirty` binding from PASSing under prefix comparison → a `+dirty` snapshot with `result: PASS` is rejected in every comparison mode.
- **F10 (LOW)** `intent_path` was containment-checked but never compared to the resolved canonical target → compared whenever the run recomputed the intent binding.
- **F11 (LOW)** the gate expanded `~` in `target_spec` and the producer did not → `~` is rejected on both ends, so one resolver rule remains.
- **F12 (LOW)** `--version` probes ran before the baseline snapshot, absorbing probe-induced mutation into the binding → the baseline snapshot, hashes, and git status are taken before the probe loop and re-checked after it.
- **F13 (LOW)** four documents named a dashboard status the code never emits → `evidence-gap` is the only spelling left in this record, `CONCEPTS.md`, `ROADMAP.md`, `docs/incremental-reverification.md`, and `docs/dogfood-evidence.md`; the two remaining occurrences of `coverage-gap` in the trust docs are this record's and `ROADMAP.md`'s retrospective account of the defect itself.
- **F14 (LOW)** a command echoing the trailer sentinel made the producer persist a PASS its own gate rejects → the producer refuses command output containing its own trailer line.
- **F15 (LOW)** record-asserted fields the gate trusted verbatim → a waiver must be an attributable object rather than a bare flag, and `profile` must match `PROFILE_ID` so it cannot forge a second verdict-scope field.
- **F16 (INFO)** Section 4's citation omitted the duplicate-id rejection it named → corrected in section 4 above.
- **F17 (INFO)** `--require` on a system claim judged it without the invariants and witnesses it `depends_on` → dependencies are pulled into the required set and disclosed in the report's `dependency_expansion`.

Shadow-migration findings and where each correction landed:

- **F1 (high)** the dispatch target was elected by mention frequency in legacy prose while the pointer stub that names the canonical intent was never read → the stub decides first, the ledger's citations only second, two or more surviving candidates or none at all block the run, and the elected `target_spec` is a top-level report field.
- **F2 (high)** a symlinked `.fv` ancestor let `--apply` write outside the project and mutate `.colosseum/`, with `status: ok` → preflight rejects a symlink at any path component (`.fv` itself included), and writes are staged and moved with `os.replace`, which does not follow a symlink at the final name.
- **F3 (medium-high)** legacy claim fields were silently dropped with no deviation row → an unknown key, or one of the retained keys carrying an untypable value, survives under `legacy_fields` and is named in a `#claims.<id>` row; document-level leftovers get a `#document` row.
- **F4 (medium-high)** `split_command` accepted two constructs no argv represents, a `NAME=VALUE` prefix and a `cd` segment → both are `unsupported` and block, alongside the other builtins whose effect dies with the process.
- **F5 (medium)** nothing checked `required_evidence` back against the plan, so a claim could require a tool the migrated plan can never run → an evidence tool no migrated execution produces is `unsupported`.
- **F6 (medium)** `_required_layers` was computed before the nothing-converted return, so migrated custom layers never joined the gating set → the sentinel survives that return, and a layer any migrated claim names is written `required: true`, matching what Gate B actually demands.
- **F7 (medium)** a plan execution naming an absent executable aborted `pyramid_run` with a traceback and wrote no report → `run_cmd` catches `OSError`, the layer records `failed` with a `launch_error`, and the report still lands.
- **F8 (medium)** a legacy tree with no intent and no ledger migrated to `status: ok` with no dispatch target at all → an `unsupported` row blocks the run.
- **F9 (medium)** `apply()` was not atomic and suppressed the report on `OSError`, leaving partial `.fv/` state with no enumeration → writes are staged and rolled back on failure, an existing destination is moved aside into the staging tree so its rollback is a rename of its own inode (mode, ownership and timestamps included), preflight probes writability, and the report is printed even on failure with each write's real action (`written`, `rolled-back`, `failed`, `lost`, `pending`), `lost` naming a destination whose original could not be renamed back.
- **F10 (medium)** per-link Kani coverage was satisfied by any occurrence of the substring `kani:` → the body is parsed against a fail-closed grammar: an unlocated harness must use the established `snake_case` or `module::harness` spelling; a bare single-segment name is accepted only with a resolving `path:line` locator; or the annotation must state `skipped because <reason>` with a reviewable reason. Placeholders and arbitrary bare words cannot discharge coverage.
- **F11 (low-medium)** a `Depends on:` block was never closed by a blank line, so later bullet lists were counted as trust-chain links → the block ends at a blank line, a heading, a further `Depends on:` header, or any nonblank non-entry line. One continuation is deliberate and documented in `find_trust_chain_links`: across a blank line, entries indented strictly deeper than the header keep the block open, which is the loose-list shape `skills/fv-compose/SKILL.md` Step 3 prescribes. The residual is named rather than hidden: an unindented post-blank entry is read as a new list and escapes the per-link Kani check (fail-open), which is preferred to the old behavior of hard-failing ordinary bullets, and shows up as a "Trust-chain links" total below the entries actually written. Both halves of the trade are pinned by assertions.
- **F12 (low-medium)** an existing non-canonical `.fv/dispatch.json` always blocked, making the documented rewrite path unreachable → the route is adopted, only `project_root` and `target_spec` are rewritten, and the write is reported as `adopt` with before/after in its detail.
- **F13 (low-medium)** the `.fv/history/` quarantine exclusion rested on a file `fv_init --force` overwrites → same correction as the evidence-architecture report's F5.
- **F14 (low)** two independent recorded runs of one layer were merged with one relabeled as a sub-step → executions are keyed `<layer>:run<k>.<i>` and the merge is reported as a `#layers.<name>` deviation row.
- **F15 (low)** residual reporting gaps: a blocked `--apply` reported `mode: dry-run`, and the report embedded an absolute machine path → `requested_mode` and `applied` are separate fields, and `project_root` is written as `.`.

Status of the corrections: every one of the 32 findings has a correction in the current set. Thirty are code corrections, each with a regression assertion — `tests/r6_manifest_failclosed.py`, `tests/r34_evidence_run.py`, and `tests/m1_coverage.py` for the evidence architecture; `tests/r35_colosseum_migration.py`, `tests/r36_dossier_rehearsal.py`, `tests/r28_baseline_floors.py`, and `tests/r1_r21_r27_ledger_gates.py` for the migration, plan, and Gate A surfaces. The remaining two (evidence-architecture F13 and F16) are defects in the trust documents themselves — a status string no tool emits, and line-range citations the corrections then moved — and are fixed where they live, in this record, `CONCEPTS.md`, `ROADMAP.md`, `docs/incremental-reverification.md`, and `docs/dogfood-evidence.md`. Every code citation in this record is now a symbol name rather than a line number, so the next refactor moves the symbol instead of silently invalidating the citation.

**The correction set is committed and gated.** Full local and Gula CI pass, and fresh read-only closure reviews found no remaining high/medium fail-open or data-loss issue. The dossier `status: ok` this paragraph originally also claimed is **superseded**: that dry run predates the ledger-readiness preflight of `368cae0`, and under the extension's current Gate A every dossier tree blocks on `.colosseum/ledger.md#gate-a` until its own citations are remediated. What the dry runs do still establish is non-mutation: no real `.colosseum` tree has been modified, and no real project has been shadow-applied. Per-project detail is in `.fv/changes/2026-09-15-real-project-readiness.md`.

### Post-fix review

Both correction sets were re-reviewed by two further read-only operators, neither the author of the corrections, each re-running the original findings' traces against throwaway fixtures outside the repository.

The shadow-migration surface came back **15 of 15 original findings resolved**. Subsequent closure passes tightened the remaining edges: arbitrary bare Kani words no longer count as harness coverage without a locator; rollback restores the original inode and metadata; the fixed staging prefix is structurally excluded and guarded against symlink escape before any byte is written; failed aside renames report `failed`, successful dispatch adoption preserves mode, and concurrent staging-root removal is retried or reported fail-closed.

The evidence-architecture surface came back with ten findings resolved on both the producer and the consumer — the reviewer's own rule being that a finding closes only when the runtime *and* both consumer surfaces close it — and five more resolved only on one side. Those residues were assigned to a final correction wave rather than waved through:

- Two Gate B rules the coverage dashboard did not mirror: the `+dirty` PASS rejection (F9) and cross-claim raw-artifact identity (F2). Both are record-level tests needing no repository access, so while the dashboard skipped them a substituted-artifact set or a dirty-snapshot PASS rendered as `VERIFIED` there while Gate B returned `INCOMPLETE` — the exact defect class F4 exists to close, against a parity claim the corrections had just strengthened.
- Manifest id fidelity (F6): the dashboard's manifest loader did not apply the producible-obligation-id rule, so a manifest Gate B rejects with `ERROR(2)` rendered as `missing-record` `INCOMPLETE(3)`. Both failed closed; the exit codes disagreed.
- Exclusion-parse divergence on a UTF-8 BOM (F7): neither end rejected or stripped one, and they disagreed about it — the TypeScript read drops a BOM, the Python read keeps it — so a BOM-prefixed `.fv/verified-inputs.txt` yielded two different exclusion sets, every record read stale, and nothing attributed the staleness to the parse.

That wave is committed with the rest of the set: `coverage_dashboard.validate_record` calls Gate B's own `dirty_snapshot_defects` and `v3_producer_defects`, `build_dashboard` calls `shared_artifact_defects` across the judged set, `coverage_dashboard.load_manifest` raises `ManifestError` (exit 2, matching Gate B) for an id outside either `OBLIGATION_ID` or `PRODUCER_CLAIM_ID`, and both `fv_project`'s policy parser and its `tools/evidence-run.ts` mirror reject `U+FEFF` anywhere in the list instead of each guessing. Two rules were added to *both* tools in the same wave: a cohort-schema record must declare `profile: producer-trusted-execution`, and with `--manifest` its `required_targets` must equal the manifest's complete required set, threaded in from the manifest rather than believed off the record.

Two fresh read-only closure agents then probed the final worktree. The evidence review executed 52 manifest-hash, intent-path, and waiver mutations through Gate B and the dashboard with zero exit-code or defect-text divergence; the migration review closed the staging-symlink, failed-aside, Kani-reference, adopt-mode, and staging-race traces and found no new high/medium fail-open or data-loss issue. The orchestrator reran the full local `scripts/ci.py` gate after those fixes: all six checks passed.

### Closure wave (`0fa4e22`) — committed and validated

A third wave answers the advisory findings the closure reviews left open, plus
the parity gaps those findings exposed. It is committed as `0fa4e22` across
`scripts/fv_project.py`, `tools/evidence-run.ts`, `scripts/fv_migrate.py`,
`scripts/fv_init.py`, `scripts/fv_doctor.py`, `scripts/pyramid_run.py`,
`scripts/check_evidence_records.py`, `scripts/check_ledger_references.py`,
`scripts/coverage_dashboard.py`, their suites, and the trust documents. An
earlier draft of this section described it as uncommitted worktree state with
validation pending; both claims are superseded below.

- **The verified-input list becomes a two-mode policy.**
  `.fv/verified-inputs.txt` may declare `mode: exclude` or `mode: include` as
  its first non-comment line; a file with no directive is exclusion mode, so
  every list written before this wave keeps its meaning byte for byte
  (`fv_project.parse_policy`, `fv_project.InputPolicy`, mirrored by
  `parseInputPolicy` in `tools/evidence-run.ts`). One path grammar serves both
  modes (`fv_project.matches_prefixes`): a trailing-slash entry is a literal
  prefix, a bare entry matches the path itself or the subtree beneath that whole
  directory component. A directive anywhere but the first non-comment line, and
  an include directive naming no path, are rejections rather than path entries,
  and a caller asking an include-mode file for exclusions is rejected instead of
  being told "excludes nothing" and hashing the whole repository.
- **An include policy binds itself.** `InputPolicy.selectors` adds
  `.fv/verified-inputs.txt` to the allowlist whether or not the file names
  itself, so revising the policy moves the snapshot and the evidence bound to
  the old one has to be re-earned rather than silently covering a different set
  of files.
- **Nine structural exclusions, applied before include matching.**
  `.fv/changes/`, `.fv/attacks/`, and `.fv/code-adversarial/` join the six
  prefixes section 2 lists in `fv_project.DEFAULT_EXCLUSIONS` and its
  `tools/evidence-run.ts` mirror, and `InputPolicy.selects` applies the
  structural set first in both modes, so an allowlist naming `.fv/` cannot pull
  generated output back into the snapshot. The three new prefixes are the
  lifecycle-report directories: a change record, an attack log, and a
  code-adversarial report each describe a run, so writing one must not stale the
  evidence that run earned — this record is itself an instance. `fv_init.py`
  creates `changes/` and `code-adversarial/` beside the other generated-output
  directories, so every lifecycle report has a home the snapshot ignores.
- **Snapshot ordering is UTF-8 byte-wise on both ends.**
  `fv_project.order_inputs` and `orderVerifiedInputs` sort on the encoded path
  bytes. The producer's runtime compares strings by UTF-16 code unit, which puts
  every astral-plane path ahead of U+E000..U+FFFF and so reverses UTF-8 order: a
  repository holding both would have hashed to two snapshots, one per
  implementation, with nothing naming the divergence.
- **The initializer preserves an include policy.**
  `fv_init.install_verified_inputs` leaves an include-mode file byte for byte,
  `--force` included, and reports it as `skip`. Appending FV's exclusion
  prefixes to an allowlist would declare generated output to be verified input,
  and replacing it with the exclusion defaults would widen what every existing
  record claims to cover; the frozen prefixes apply structurally in both modes,
  so nothing is lost by leaving the file alone. An exclusion-mode file still
  gains any structural default it dropped, and `--force` still replaces it.
- **A legacy include list is translated, not inverted.** Section 8's rule was
  that FV had only an exclusion list, so the legacy include list was preserved
  as history and the conservative defaults were written instead. With include
  mode available the list is carried across (`_migrate_verified_inputs`,
  `_translate_include_entry`): a source root verbatim; an entry naming a legacy
  manifest rebound to the FV artifact its content migrated to, read out of this
  run's own inventory so an entry only ever binds an artifact the run actually
  wrote; an entry naming history-only bytes reported as a `#<entry>` deviation
  row rather than silently narrowing the policy; plus the elected canonical
  target, whichever of `.fv/obligations.json` and `.fv/verification-plan.json`
  the run wrote, and the policy file itself. A legacy list that is not valid
  UTF-8, does not parse under the path grammar, declares no entries, or has no
  entry left after translation is `unsupported` and blocks the migration: a
  policy binding only the artifacts the migration authored would survive every
  edit to the sources a layer actually decides on. The emitted bytes are read
  back through the same parser the gate and the producer use before the write is
  planned, because a lost mode directive would republish the policy as an
  exclusion list binding the whole repository minus a handful of source roots.
  Inverting the list is still not the fallback, and the exact legacy list is
  still preserved verbatim at `.fv/history/colosseum/verified-inputs.txt`. A
  legacy tree that recorded no include list gets the exclusion defaults as
  before.
- **A project's verification plan is mandatory once it exists.**
  `pyramid_run.discover_plan` finds `<crate>/.fv/verification-plan.json` with no
  flag and executes it, so a migrated project cannot keep reporting the built-in
  defaults its plan replaced. Provenance is always disclosed: `plan.discovery`
  is `explicit`, `autodiscovered`, `absent`, or `disabled` in every report, and
  `plan_banner` prints one stderr line naming the source. `--no-plan` is the
  only escape hatch, recorded as `disabled` with the ignored path named; a plan
  present but unreadable or malformed is exit 2 before any layer runs, never a
  silently legacy run, and presence rather than readability is what discovery
  tests, so a dangling symlink blocks instead of falling back.
  `fv_doctor.check_verification_plan` fails the same project on
  `project/verification-plan` instead of leaving it for the next verification
  run, and the doctor's verified-input check now reports the policy by mode
  (declared and effective prefix counts under exclude mode, selected-path count
  including the policy itself under include mode) rather than a bare prefix
  count that says nothing about an allowlist.
- **A recomputed Gate B run keeps the unqualified verdict token.** The default
  discipline adds nothing to the scope: `VERIFIED[profile=...]` is a recomputed
  run, and only a weaker one qualifies it as `; binding=pinned` or
  `; binding=unbound`. The report's `binding` field still carries all three
  spellings, and the coverage dashboard names `not-recomputed` in its payload
  and summary line rather than in a verdict scope.

Validation of this wave is now recorded rather than pending, and the four
contract changes an operator can observe are each covered by it:

- **Include-mode translation.** A legacy include list migrates into
  `mode: include` (`_migrate_verified_inputs`, `_translate_include_entry`),
  re-read through the gate's and the producer's own parser before the write is
  planned; a list that cannot be translated blocks instead of being inverted or
  replaced.
- **Automatic plan discovery.** `pyramid_run.discover_plan` executes
  `<crate>/.fv/verification-plan.json` with no flag, discloses `explicit`,
  `autodiscovered`, `absent`, or `disabled` in `plan.discovery`, and exits 2 on
  a present-but-unusable plan; `--no-plan` is the only escape hatch.
- **Nine structural exclusions.** `.fv/changes/`, `.fv/attacks/`, and
  `.fv/code-adversarial/` join the six prefixes section 2 lists, applied before
  include matching in both modes, so writing a lifecycle report (this record
  included) cannot stale the evidence that run earned.
- **Default verdict compatibility.** A recomputed Gate B run keeps the
  unqualified `VERIFIED[profile=...]` token every pre-wave consumer already
  reads; only `binding=pinned` and `binding=unbound` qualify the scope, while
  the report's `binding` field still names all three disciplines.

Gula ran `tests/run_all.py` with all 32 suites PASS and `scripts/ci.py` with 6
of 6 PASS, neither with `--tolerate-incomplete`. The ten-project dry run then
exercised the same code against real legacy trees and wrote nothing. Two
boundaries are unchanged by the wave: no real legacy project has been
shadow-applied, and a migrated project still re-earns `fv-evidence-run/v3`
evidence before Gate B can pass.

### Ledger-readiness preflight (`368cae0`)

`.fv/ledger.md` is the legacy ledger's bytes unchanged, and Gate A resolves a
citation against the project root from either location, so whether a migrated
project can pass Gate A is already decided by bytes that exist before anything
is written. `368cae0` decides it there: when `.colosseum/ledger.md` exists, the
extension's own `scripts/check_ledger_references.py` is run over it at default
strictness with `--root PROJECT`, and only exit 0 permits the mapping
(`fv_migrate.run_gate_a`, `_load_gate_a`, `GATE_A_SCRIPT`). The gate is loaded
by path and called in-process, never through a shell: a stale copy earlier on
`sys.path` (a project's own `.fv/scripts/` copy is exactly that) must not be
what decides readiness, and the answer must not depend on the cwd, on an
interpreter on PATH, or on quoting. Bytecode writing is disabled during the
load, so a readiness check run against the extension repository itself writes
nothing.

The two non-pass outcomes stay distinguishable. A nonzero status the gate
*returns* is `rejected`: it read the ledger and refused it, which is a statement
about the bytes. A missing or unimportable script, an unreadable or non-UTF-8
ledger, a CLI that no longer accepts `<ledger> --root <root>`, a non-integer
return, or any other raise is `unavailable`: the check failed, and reporting
that as a ledger verdict would be inventing one. Both add a single
`.colosseum/ledger.md#gate-a` `unsupported` row carrying a bounded excerpt of
the gate's own output (capped in lines and in line length, machine paths
redacted, so the JSON report is byte-identical across checkouts), and both block
before any `.fv` write is proposed.

Nothing is rewritten: this is readiness validation, not ledger repair. The
refused ledger's bytes still reach `.fv/history/colosseum/ledger.md`,
`.colosseum/` stays byte-identical, and the remedy is stated inside the refusal
(content-bind the citations, re-root any written relative to `.colosseum/`, drop
any that cites nothing, re-run). The cost is deliberate and is the reason the
dossier claim above is superseded: a tree that migrated `status: ok` before this
commit now blocks, because handing an operator a project whose first gate run
fails on a file the report called migrated is exactly the failure mode the
preflight exists to prevent. Regression coverage is in
`tests/r35_colosseum_migration.py` and `tests/r36_dossier_rehearsal.py`.

### Deliberate choices in the correction set

Three behaviours look like defects from one side and are the intended contract; recorded here so a later reader does not "fix" them back.

- **A required claim with no recorded layer runs blocks the migration.** `required_evidence` is checked back against the translated plan, and the degenerate case is blocking too: a legacy tree with claims but no `evidence/runs/layer-runs.json` declares no executions, so its claims name evidence the plan cannot produce and the run refuses. Such a project was previously migratable with `status: ok`. The remedy is to record the runs or to stop the claims naming layers nothing can run; the alternative — migrating a manifest whose claims can never be discharged — reads forever as "evidence missing" rather than "never runnable here".
- **A blank line closes a `Depends on:` block, even for a later bullet at the header's own indentation.** Across a blank line only a list indented deeper than the header continues the block. A sibling-indent bullet after a blank line is indistinguishable from the unrelated prose bullet the old latch miscounted as a trust-chain link, so it is not readmitted. The residual is fail-open — an off-convention loose ledger loses links after the blank line — and the remedy is the two-space indent `fv-compose` Step 3 prescribes, which every fixture and the shipped ledger already use.
- **Aggregate `evidence_class` has no total strength lattice.** A record-level class is never checked for being at least as strong as the cohort it heads, because nothing ranks `proof-discharged` against `bounded-checked` against `conformance-tested` in a way that survives a reader disagreeing with the ranking, and a synthetic lattice would sit between an obligation and its evidence while looking authoritative. What holds instead is per-execution enforcement plus disclosure: every execution's class is recorded and checked against the obligation kind's allowed set, an `externally-assumed` or `unverified` class anywhere in the cohort needs a waiver, and the dashboard reports `by_execution_evidence_class` and `assumed_executions` beside the record classes. A record class that overstates its cohort inside one kind's allowed set is therefore visible, not rejected.

### Test-quality cleanup in the same set

`tests/r24_r26_conformance.py` loses its three R26 label-sweep checks: they grepped `scripts/*.py`, `README.md`, `CONCEPTS.md`, and the SKILL sources for the string `REFINEMENT_VERIFIED` and for a `VERIFIED` not followed by `[`. Those assert source text rather than observable behavior — a banned-substring scan over the repository, which a comment or a docstring can trip and a renamed emitter can evade. They are not restored, in any form: re-running their own logic over the corrected `scripts/` flags two prose lines (`fv_migrate.py`'s "the pyramid still reports VERIFIED." and its `VERIFIED INPUTS` section header), which is the scan's failure mode rather than a finding.

What is asserted instead is every place a verdict is observable, and the R26 claim in `ROADMAP.md` is narrowed to exactly that:

- `tests/r24_r26_conformance.py` — a conformance scope survives Gate B aggregation: the JSON verdict starts `VERIFIED[` and the per-claim scope still carries the replay parameters (`traces`, `depth`, `seed`).
- `tests/r1_r21_r27_ledger_gates.py` — Gate B emits `VERIFIED[profile=bounded; binding=unbound]`, and a bare `VERDICT: VERIFIED` line is absent from the same output.
- `tests/r6_manifest_failclosed.py` — `binding=recomputed`, `binding=pinned`, and `binding=unbound` are each disclosed in the scope of the run that produced them. (Closure wave `0fa4e22`: the recomputed case now asserts the unqualified `VERIFIED[profile=...]` scope plus `binding: recomputed` in the report, and only the pinned and unbound cases assert a qualified scope.)
- `tests/m1_coverage.py` — the dashboard's scope matches exactly, a bare `VERDICT: VERIFIED` is flagged where a scoped one is not, and the dashboard's own `--check` self-scan runs clean over a repository-shaped fixture.
- `scripts/coverage_dashboard.py --check` — the tool scans its own table, verdict banner, and JSON payload for an unscoped `VERIFIED` and exits nonzero if one could appear.

The gap that leaves is stated rather than papered over: nothing now watches a *new* emitter anywhere in the repository, so a future script printing a bare `VERIFIED`, or an unscoped `REFINEMENT_VERIFIED` when that label is finally built, would be caught by review rather than by a test. R24's conformance-bridge assertions are untouched.

### Corrections folded in before the pass

Two corrections were folded in before the adversarial pass ran, recorded here because each is the class of defect such a pass exists to find.

The first: the initial verification-plan implementation accepted only known pyramid layer ids, which would have made the migrator drop or downgrade a legacy `quint` layer that a `system_claim.required_evidence` names, presenting unrun verification as a complete plan. Under a corrective requirement the user authorized in the same session (folded into the Authority bullet above), every non-reserved id became an accepted custom layer, an untranslatable required layer became blocking rather than omitted, and custom layers went through the same validation, ordering, `required_layers`, and `not_run` treatment as known layers. This correction is inside `b1003a3`.

The second: the migration first carried legacy `required_targets` into obligation ids verbatim, and the documentation told the operator to hand-rename the colon-bearing ones before producing evidence. That is a defect of the same shape one level up: the trust artifact would have been mapped correctly while the path from it to a record ran through an unverified human transcription, and an operator who skipped or mistyped it would read `missing-record` for an obligation whose evidence had in fact been earned. The corrective requirement replaced the instruction with deterministic normalization in `scripts/fv_migrate.py`, `legacy_id` traceability on every rewritten obligation, and `unsupported`-and-block on any id collision or empty normalization (section 7). This correction lands after `b1003a3`; it is not covered by the focused verification runs enumerated above, and its verification is an open follow-up below.

## Ledger delta

- Composition theorems added/removed: none
- Axioms added/removed: none
- Coverage shift: evidence bindings move from commit-plus-dirty-flag to a verified-input content snapshot; a claim's evidence may now be a tool cohort rather than a single command, with one raw artifact per execution and no artifact shared between claims; a Gate B verdict now discloses its freshness discipline as `binding=recomputed|pinned|unbound`; verification layers become project-configurable, custom layers included; `.fv/history/` and the migrator's staging prefix `.fv/.migrate-staging/` become structural snapshot exclusions rather than a migrated-project convention; legacy `.colosseum` artifacts become either mapped FV artifacts or quarantined history under `.fv/history/colosseum/`; a migrated obligation's id is producer-usable by construction, with `legacy_id` carrying the legacy string and colliding ids blocking rather than being silently disambiguated
- Committed in the closure wave (`0fa4e22`): the verified-input list becomes a two-mode policy whose include form binds itself, three lifecycle-report directories join the structural exclusions so writing a report cannot stale the evidence it describes (nine prefixes in total), snapshot order becomes UTF-8 byte-wise on both ends, a legacy include list migrates into include mode instead of being preserved-and-replaced, a project verification plan becomes mandatory once present with `--no-plan` as the only escape hatch, and a Gate B verdict qualifies its scope only for the weaker freshness disciplines while a recomputed run keeps the unqualified `VERIFIED[profile=...]` token every pre-wave consumer reads
- Committed in the ledger-readiness preflight (`368cae0`): a legacy ledger the extension's current Gate A refuses, or that the gate could not be run against, is an `unsupported` row that blocks the migration rather than a mapped `.fv/ledger.md` that fails the migrated project's first gate run; a refusal and a failed check stay distinguishable (`rejected` versus `unavailable`), and neither rewrites a ledger

## Deployment verification

- **Superseded.** The earlier Gula dry run against a dossier tree (exit 0, `status: ok`, 5 mapped, 173 preserved-history, 0 unsupported, 0 conflicts, target `docs/intent.md`, legacy digest identical before and after) predates `368cae0`. It is no longer that project's current result and is kept here only as the baseline the preflight changed.
- **Current.** Gula dry-ran all ten legacy `.colosseum` trees under `~/Development`. Nothing was written, no `--apply` was run against any of them, and every legacy tree was byte-identical afterwards. `zkdcap` is `status: ok` (1 mapped, 172 preserved-history, 0 unsupported, 0 conflicts, target `.fv/intent.md`). `dossier` (5 mapped, 166 preserved), `dossier-integration` (5, 173), and `dossier-organization` (5, 169) each block on exactly one row, `.colosseum/ledger.md#gate-a`, with their targets unchanged at `docs/intent.md`. `clanked`, `colosseum`, `dens`, and `travel` each block on exactly `.colosseum#intent`. `quartz` blocks on `.colosseum#intent` plus the ledger row. `verified-rcv` blocks on five legacy attack symlinks plus the ledger row, target `.fv/intent.md`. The per-project table is in `.fv/changes/2026-09-15-real-project-readiness.md`.
- **The toolkit gates safely; the dossier projects are blocked pending their own ledger remediation.** Every non-`ok` project is a refusal to write, enumerated row by row, with the legacy tree untouched. The dossier ledgers are a contract upgrade rather than a parser regression: an older copied Gate A exits 0 on all three while the extension's current Gate A exits 1, and the preflight surfaces that difference before a write instead of after.
- Gula `tests/run_all.py`: all 32 suites PASS. Gula `scripts/ci.py`: 6 of 6 PASS. Neither run used `--tolerate-incomplete`. Local full CI passed the same six checks.
- Gula fresh-project doctor: PASS with the deployed OMP source and six verified-input exclusion prefixes, observed before `0fa4e22`. The committed structural set is nine and the doctor now reports the policy by mode rather than by a bare prefix count; that output has not been re-observed on a fresh Gula doctor run, so the suite run above is the only evidence covering it.

## Outstanding follow-ups

No toolkit implementation is outstanding. The closure wave and the ledger-readiness preflight are committed and covered by the runs above, and every remaining item is owned by a legacy project or is evidence that has to be re-earned after that project moves.

- **Ledger remediation (project-owned): `dossier`, `dossier-integration`, `dossier-organization`, `quartz`, `verified-rcv`.** Each `.colosseum/ledger.md` carries citations the current Gate A refuses. The owner content-binds them, re-roots any written relative to `.colosseum/`, drops any that cites nothing, then re-runs the dry run. The migrator never edits a ledger, so none of this is closable from this repository.
- **Canonical-intent declaration (project-owned): `clanked`, `colosseum`, `dens`, `travel`, `quartz`.** `.colosseum#intent` blocks because the tree has no `.colosseum/intent.md` and no document citing an existing canonical intent, so a migrated project would declare no `target_spec`. The owner adds the document or the citation; electing one by guess is the defect the shadow-migration review's F1 closed.
- **Legacy attack symlinks (project-owned): `verified-rcv`.** Five legacy attack entries are symlinks, which the inventory refuses rather than follows, since copying one would duplicate its target's bytes under a different identity or leave a dangling link. The owner replaces them with the bytes or removes them from the legacy tree.
- **Applying a migration.** No real project has been shadow-applied. `--apply` waits, per project, on the remediation above; a project that still blocks would refuse the apply anyway.
- **Re-earning evidence after a migration.** `preserved-history` records are not live evidence, so a migrated project holds no `fv-evidence-run/v3` record until its own plan runs and each obligation's evidence is earned against the migrated policy's snapshot. An include-mode policy binds itself, so a later revision of that policy moves the snapshot and the evidence bound to the old one is re-earned rather than silently carried.
