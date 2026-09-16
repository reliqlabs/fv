# Change record: real-project migration readiness — ten legacy trees, one apply-ready

- Date: 2026-09-15
- Classification: implementation-only — observational. No intent, spec, or code
  change is recorded here. This record states what the committed migrator and
  the committed Gate A say about ten real legacy `.colosseum` projects, and what
  an operator must do before each can cross into `.fv/`. The remediation
  sequence R1 prescribes uses an uncommitted working-tree capability whose own
  record is `.fv/changes/2026-09-15-colosseum-shadow-migration.md`; no project
  verdict here depends on it, because no project has used it.
- Intent revision: none. This repository declares no `.fv/intent.md`; the
  authority for the migration surface is the user-authorized migration
  requirements restated in
  `.fv/changes/2026-09-15-colosseum-shadow-migration.md`.
- Commits under observation: `f2d0556`, `9eb3709`, `b1003a3`, `8508604`,
  `5dc765e`, `d5ce1c2`, `dec002d`, plus `0fa4e22` (legacy migration input
  contracts) and `368cae0` (legacy ledgers gated before migration). `368cae0` is
  what flips the three dossier verdicts from `ok` to `blocked` and adds a row to
  quartz's and verified-rcv's already-blocked runs; the remaining five verdicts
  (clanked, colosseum, dens, travel, zkdcap) are unaffected by it.
  Also observed, and kept separate because it is not committed: the
  ledger-remediation staging surface in the working tree
  (`--stage-ledger-remediation`, plus a live `.fv/ledger.md` outranking the
  legacy ledger, described in
  `.fv/changes/2026-09-15-colosseum-shadow-migration.md`). It changes no row of
  the table below, because no project has been staged: every verdict here is
  the committed migrator at `368cae0` reading a project that carries no live
  `.fv/ledger.md`.
- Compatibility posture: established. Nothing here alters an accepted record
  format or CLI surface.

## Description

`scripts/fv_migrate.py` was run in dry-run mode against all ten `.colosseum`
projects a read-only inventory found under the deployment host's
`~/Development`. One project is apply-ready today: **zkdcap**. The other nine
are blocked, each by an input defect in its own legacy tree, in exactly three
blocker classes. No project was applied, and no project can be applied by
re-running the tool: every remaining blocker is remediated by an operator, not
by the migrator, which validates readiness and never rewrites a ledger and
never writes into `.colosseum/` at all. Two of the three classes are fixed in
the legacy tree; the ledger class is fixed in a copy the tool can stage outside
it. Nothing was staged either: `--stage-ledger-remediation` exists in the
working tree and has been run against no real project.

The remediation path itself is now toolkit capability rather than an
instruction, which changes what R1 below asks an operator to do and changes
nothing about this inventory. Staging gives the operator a writable
`.fv/ledger.md` to edit and a re-run that judges it, and the count of projects
whose own bytes let them cross into `.fv/` stays 1 of 10 until a project
actually uses it.

Two readiness facts must not be conflated, and this record keeps them apart:

- **Toolkit readiness** — whether FV's own migrator, gates, producer, and doctor
  behave as specified. Established on the deployment host by the suite and CI
  runs in "Toolkit readiness" below.
- **Project readiness** — whether a given legacy tree's own bytes let it cross
  into `.fv/` today. This is 1 of 10, and no amount of green FV CI moves it. It
  moves when an operator fixes that project's ledger citations, declares its
  canonical intent, or resolves its symlinks.

## The ten projects

Dry run, `scripts/fv_migrate.py PROJECT` with no `--apply`. `exit 0` +
`status ok` is apply-ready; `exit 1` + `status blocked` means at least one
`unsupported` or `conflict` row, and the tool refuses before proposing any
write. Every row below is the **current** preflight — the migrator at
`368cae0`, with the legacy-ledger readiness check wired in. The earlier
inventory, taken before that commit, is reported separately under "Old Gate A
versus current Gate A" and disagrees with this table on the three dossier rows
by exactly that check.

| Project | Path (host-relative) | exit | status | mapped | preserved-history | unsupported rows | conflicts | elected `target_spec` |
|---|---|---|---|---|---|---|---|---|
| zkdcap | `Development/reliq/zkdcap` | 0 | ok | 1 | 172 | 0 | 0 | `.fv/intent.md` |
| dossier | `Development/burnt/dossier` | 1 | blocked | 5 | 166 | 1 — `.colosseum/ledger.md#gate-a` | 0 | `docs/intent.md` |
| dossier-integration | `Development/burnt/dossier-integration` | 1 | blocked | 5 | 173 | 1 — `.colosseum/ledger.md#gate-a` | 0 | `docs/intent.md` |
| dossier-organization | `Development/burnt/dossier-organization` | 1 | blocked | 5 | 169 | 1 — `.colosseum/ledger.md#gate-a` | 0 | `docs/intent.md` |
| clanked | `Development/reliq/clanked` | 1 | blocked | 0 | 39 | 1 — `.colosseum#intent` | 0 | none elected |
| colosseum | `Development/reliq/colosseum` | 1 | blocked | 0 | 17 | 1 — `.colosseum#intent` | 0 | none elected |
| dens | `Development/reliq/dens` | 1 | blocked | 0 | 91 | 1 — `.colosseum#intent` | 0 | none elected |
| travel | `Development/reliq/travel` | 1 | blocked | 0 | 38 | 1 — `.colosseum#intent` | 0 | none elected |
| quartz | `Development/reliq/quartz` | 1 | blocked | 0 | 85 | 2 — `.colosseum#intent` + `.colosseum/ledger.md#gate-a` | 0 | none elected |
| verified-rcv | `Development/reliq/verified-rcv` | 1 | blocked | 1 | 376 | 6 — five `.colosseum/attacks/…` symlink rows + `.colosseum/ledger.md#gate-a` | 0 | `.fv/intent.md` |

Notes on the table, so a later reader does not over-read it:

- Zero `conflicts` in all ten. No destination path crossed a symlink at any
  component, and no destination already existed with different content. The
  blockers are all input-side.
- zkdcap's single mapped artifact is the legacy intent elected as the dispatch
  target. [INFERENCE] It has no legacy `.colosseum/ledger.md`: no `#gate-a` row
  fired for it, and that row is emitted whenever the legacy ledger exists.
- verified-rcv elected `.fv/intent.md` and is still blocked. The elected
  `target_spec` is a top-level report field regardless of verdict, so an elected
  target is not a readiness signal on its own.

## The three blocker classes

Exactly three classes account for all fifteen unsupported rows across the nine
blocked projects (5 `#gate-a` + 5 `#intent` + 5 symlink). Each is a
deliberate refusal in `scripts/fv_migrate.py`, not a crash, and each blocks
before any `.fv` write is proposed.

### 1. `<ledger>#gate-a` — the current Gate A refuses the legacy ledger

Row key: `.colosseum/ledger.md#gate-a`. Affects **dossier**,
**dossier-integration**, **dossier-organization**, **quartz**,
**verified-rcv** (5 of 10).

`.fv/ledger.md` would be the legacy ledger's bytes unchanged, and Gate A
resolves citations against the project root from either location, so migrated
readiness is decided by bytes that already exist. `368cae0` decides it at
migration time: when `.colosseum/ledger.md` exists, the extension's own
`scripts/check_ledger_references.py` is run over it with `--root PROJECT` at
default strictness, loaded from its own path and called in-process so that a
project's stale `.fv/scripts/` copy cannot be what decides readiness, and only
exit 0 permits the mapping.

The row separates two things it would be dishonest to merge: a nonzero status
the gate *returns* is a rejection of the ledger's bytes; anything that stops the
gate from returning a status at all is an infrastructure failure of the check
and says so. All five rows here are the first kind — the gate ran and refused.

Under the uncommitted staging surface the row key follows whichever ledger was
checked, `.fv/ledger.md#gate-a` for a project carrying a live ledger and
`.colosseum/ledger.md#gate-a` otherwise, and the legacy-keyed refusal points at
`--stage-ledger-remediation` for a writable copy. Every row observed here is
legacy-keyed for a reason that has nothing to do with those projects' contents:
they were produced by the committed migrator, which checks the legacy ledger
and only the legacy ledger.

The four refusal classes observed across the refused ledgers, verbatim from the
gate's own output:

- `missing required content hash` — a citation carries no `@sha256:<12hex>`
  binding.
- `cited line is empty or comment-only` — the citation resolves to a doc-comment
  or a section comment rather than to content.
- `unparseable 'code:' citation 'code:'` — a `code:` annotation with no value,
  which the current grammar fails loudly instead of skipping.
- `malformed content binding in citation '@sha256:'` — a binding suffix with no
  hex digits behind it, read as drift rather than as prose.

Failure totals on the three dossier ledgers: **39**, **39**, and **36**
failures, ending `GATE FAILED`. Per-ledger full text is not reproduced here
beyond those exemplars; the complete bounded diagnostic is in each run's
`#gate-a` row, so **re-run `fv_migrate.py PROJECT --json`** to read a project's
full refusal before remediating it.

### 2. `.colosseum#intent` — no dispatch target can be elected

Row key: `.colosseum#intent`, detail verbatim: "no dispatch target can be
established: there is no `.colosseum/intent.md` and no document cites an
existing canonical intent, so the migrated project would declare no
`target_spec` and every gate, evidence run and skill would fail to resolve one".
Affects **clanked**, **colosseum**, **dens**, **travel**, **quartz** (5 of 10).

The election rule is stub-first: `.colosseum/intent.md` is read and a
`*intent.md` path it cites that resolves under the project root becomes the
target; only when the stub cites none do the ledger's citations decide. Two or
more surviving candidates block, and so does none at all — frequency of mention
in untrusted legacy prose must never pick between trust roots. These five are
the "none at all" case.

### 3. `symlink` — a legacy file with no byte-preserving classification

Five rows, all under
`.colosseum/attacks/intent-v0.3.0-2026-05-16T121229Z/`, affecting
**verified-rcv** only:

- `shell-glm-4-7-flash.md`
- `shell-google-gemma-4-26b-a4b.md`
- `shell-kimi-k2-6.md`
- `shell-mistral-small-4-119b-2603.md`
- `shell-qwen3.6-27b-mlx.md`

Detail verbatim: "symlink: copying it would either duplicate its target's bytes
under a different identity or leave a dangling link". Every source artifact must
classify as exactly one of `mapped`, `preserved-history`, or `unsupported`; a
symlink has no honest classification, so the run blocks rather than inventing
one.

## No-write / no-apply boundary

The boundary held on all ten projects, and this record claims nothing beyond it:

- Every one of the ten runs was a **dry run**. `--apply` was invoked against no
  real project, on this host or the deployment host.
- Nothing was **staged**, either. `--stage-ledger-remediation`, the only mode
  that writes without migrating, was invoked against no real project on either
  host, so no project carries a staged `.fv/ledger.md` from this work.
- A dry run writes nothing, anywhere. No `.fv/` bytes exist in any of the ten
  projects as a result of these runs, and no shadow state exists to roll back.
- `.colosseum/` is read-only in every mode. The inventory that found the ten
  projects was read-only as well.
- A blocked run refuses before proposing any write, so the nine blocked
  projects never reached a write plan at all.
- zkdcap is apply-ready, **not applied**. Its `--apply` remains an unexercised
  path against a real project.
- The staging path is toolkit capability, not a project state: it is exercised
  only by test fixtures, and R1 below is what an operator would run, not a
  record of a run.

## Old Gate A versus current Gate A

This is why the three dossier trees read `status ok` in the first inventory and
`status blocked` now, and why quartz and verified-rcv each grew a row. It is a
contract upgrade, not a regression and not a parser crash.

| Ledger | Project's own copied Gate A | Extension's current Gate A |
|---|---|---|
| dossier | exit 0 — `OK: 138 citation(s), 41 dependency link(s), 8 axiom annotation(s)` | exit 1 — `GATE FAILED: 39 failure(s)` |
| dossier-integration | exit 0 — `OK: 147 citation(s), 41 dependency link(s), 8 axiom annotation(s)` | exit 1 — `GATE FAILED: 39 failure(s)` |
| dossier-organization | exit 0 — `OK: 139 citation(s), 41 dependency link(s), 8 axiom annotation(s)` | exit 1 — `GATE FAILED: 36 failure(s)` |
| quartz | no copied gate in the project | exit 1 |
| verified-rcv | no copied gate in the project | exit 1 |

Three things this comparison establishes:

1. **Same bytes, two verdicts.** The older copied gate accepts these ledgers;
   the current one refuses them. The refusals are the citation-grammar and
   content-binding rules the current gate added — mandatory `@sha256:<12hex>`
   bindings, loud failure on an unparseable `code:` value, drift on a malformed
   binding, and content sanity on the cited line. A ledger that passed an older
   contract is not thereby ready for the current one.
2. **The copied gates are of an older CLI vintage too.** Invoking a project's
   copy with the current CLI shape (`<ledger> --root <root>`) exits 2 with
   `unrecognized arguments`: the copies want `--ledger LEDGER`. That is exactly
   the hazard `368cae0` closes by loading the gate from its own path and calling
   it in-process — a project's stale copy must never be what decides readiness,
   and the answer must not depend on cwd, on an interpreter on PATH, or on
   quoting.
3. **The status change is the gate, not the migrator.** The first inventory ran
   the migrator *before* `368cae0` wired the ledger-readiness check, and the
   three dossier trees read `exit 0`, `status ok`, `unsupported 0`,
   `conflicts 0`, target `docs/intent.md`. The current preflight reports the
   same three trees blocked by exactly one row each,
   `.colosseum/ledger.md#gate-a`, with their mapped/preserved counts unchanged
   in shape (5 mapped; 166 / 173 / 169 preserved). Nothing about the migrator's
   classification of those trees changed; one new blocking check was applied to
   bytes that were always this way. The earlier `status ok` for
   dossier-integration recorded in
   `.fv/changes/2026-09-15-colosseum-shadow-migration.md` under "Deployment
   verification" is therefore superseded as a *readiness* claim while remaining
   accurate as a record of that run.

## Remediation categories

Three operator-owned categories. R2 and R3 are fixes in the legacy tree; R1 is
a fix in a staged copy of the ledger, since `.colosseum/` stays byte-identical
in every mode. None is a code change in this repository, and re-running the
migrator without fixing the inputs produces the same refusal.

### R1. Stage the ledger, fix its citations, re-run

Projects: **dossier**, **dossier-integration**, **dossier-organization**,
**quartz**, **verified-rcv**.

The legacy ledger cannot be edited in place: `.colosseum/` stays
byte-identical in every mode, and the migrator never rewrites a ledger
anywhere. So the remediation happens in a copy the tool stages for exactly
this, and the sequence is stage, edit, re-run.

1. **Read the refusal.** `fv_migrate.py PROJECT --json` carries the full
   `#gate-a` row with the gate's own bounded diagnostic.
2. **Stage a writable ledger.**
   `fv_migrate.py PROJECT --stage-ledger-remediation` copies
   `.colosseum/ledger.md` to `.fv/ledger.md` verbatim and proposes no other
   write: no history, no manifests, no dispatch, no verified-input policy, and
   no gate run. Run again and it reports the copy already there (`identical` or
   `already-staged`) and rewrites nothing, so a re-run never costs an edit.
3. **Edit `.fv/ledger.md`.** Content-bind every citation
   (`check_ledger_references.py --suggest-hashes` prints the required
   `@sha256:<12hex>` suffix for each unhashed one); re-point every citation
   whose target line is empty or comment-only at the line that actually carries
   the content; repair each valueless `code:` annotation to
   `code: <path>:<line>@sha256:<12hex>`, backtick-quoting the whole `path:line`
   when the path contains spaces; re-root any citation written relative to
   `.colosseum/`, which resolves from neither the legacy nor the migrated
   location.
4. **Re-run the gate, then the migration.**
   `check_ledger_references.py .fv/ledger.md --root PROJECT` must exit 0. The
   dry run then judges that same file and keys its readiness row at
   `.fv/ledger.md#gate-a` rather than at the legacy path, because a live
   `.fv/ledger.md` outranks the legacy ledger: it is the file CI checks and the
   only one of the two an operator can repair.

What the migration then does with the two ledgers: the edited bytes are kept
exactly as written (the destination reports `identical`, nothing is rewritten),
and the superseded legacy ledger is classified `preserved-history` at
`.fv/history/colosseum/ledger.md` rather than raised as a destination conflict,
since differing bytes are precisely what a remediated ledger has. An
include-mode verified-input entry naming the legacy ledger binds `.fv/ledger.md`
instead. Nothing is lost by fixing the staged copy: the legacy original survives
byte for byte in both `.colosseum/` and history.

Two cautions. A staged but unedited ledger still blocks, now at
`.fv/ledger.md#gate-a` — staging is not remediation. And this path is
uncommitted worktree state in this repository (see
`.fv/changes/2026-09-15-colosseum-shadow-migration.md`), exercised against test
fixtures only; no project in the table above has been staged.

### R2. Declare a canonical intent

Projects: **clanked**, **colosseum**, **dens**, **travel**, **quartz**.

Either add a `.colosseum/intent.md` pointer stub that cites the one canonical
`*intent.md` resolving under the project root, or author that intent first
(`fv-reverse-intent` for a system whose intent is implicit in code) and then
declare it. The declaration must leave exactly one surviving candidate:
zero blocks, and so do two or more.

### R3. Resolve the five verified-rcv symlinks — operator decision

Project: **verified-rcv**. The five links under
`.colosseum/attacks/intent-v0.3.0-2026-05-16T121229Z/` listed in blocker class 3
must be resolved by a person who knows what they were for. Two defensible
outcomes: replace each link with its target's real bytes (the attack output is
then preserved under its own identity), or delete links whose targets are
already preserved elsewhere in the tree. The migrator deliberately picks
neither — copying would publish one artifact's bytes under a second identity,
and preserving the link would put a dangling link in the history tree.

### Ordering

**quartz** carries R1 and R2; **verified-rcv** carries R1 and R3. Both blockers
must clear before either project's run reaches `status ok` — the tool reports
every unsupported row it finds, so a single re-run confirms both at once.

## Toolkit readiness

Executed on the deployment host, not inferred, and distinct from the project
readiness above:

- `tests/run_all.py`: **all 32 suites PASS.** The runner enumerates
  `tests/r*.py` + `tests/m*.py` minus itself, and refuses a zero-suite run, so
  "32" is the whole suite set rather than a filtered subset.
- `scripts/ci.py`: **6 of 6 checks PASS** — `frontmatter`, `roster-drift`,
  `doc-links`, `dispatch-config`, `fixture-tracking`, `regression` — run
  **without** `--tolerate-incomplete`, so the regression check had to pass
  outright rather than being allowed to degrade to the toolchain-incomplete
  exit 3 a bare runner is permitted.

Those two runs cover the committed migrator. The ledger-remediation staging
surface R1 now uses is uncommitted worktree state, and its evidence is narrower
and local:

- `python3 tests/r35_colosseum_migration.py`: **exit 0, 534 assertions pass,**
  59 of them in the two new phases `check_stage_ledger_remediation` (30) and
  `check_live_ledger_remediation` (29).
- `python3 tests/r36_dossier_rehearsal.py`: **exit 0, 214 assertions pass,** 41
  of them under `check_ledger_remediation`, which drives the whole stage / edit
  / re-run / apply sequence against the dossier-shaped fixture and asserts that
  `.colosseum/` stays byte-identical throughout, the operator's edited bytes are
  what remain on disk, the superseded legacy ledger is history byte for byte,
  and a re-apply changes not a byte. The two totals are separate suites with
  different per-check vocabularies, not one summed number.
- **Pending:** a full local `scripts/ci.py` run, a full `tests/run_all.py` run,
  and Gula re-validation of both over this worktree. The 32/32 and 6/6 results
  above predate the staging surface and do not cover it.

What this does and does not license: the migrator, the gates, the producer, and
the doctor behave as specified on a host with the toolchain. It says nothing
about any legacy tree's readiness, and it does not make a refused ledger ready.

## Affected verification surface

- Quint: N/A
- Lean: N/A
- Verus: N/A
- Kani: N/A
- Gates: observational only. Gate A (`check_ledger_references.py`) is the
  decision procedure whose verdict this record reports; no gate behavior is
  changed here.
- Compose: N/A

## Adversarial review

N/A — observational record, no intent or spec diff. The code surface it observes
carries its own adversarial pass and closure reviews, recorded in
`.fv/changes/2026-09-15-colosseum-shadow-migration.md`.

## Ledger delta

- Composition theorems added/removed: none
- Axioms added/removed: none
- Coverage shift: none. This record adds no trust claim; it records that 1 of 10
  real legacy projects can currently cross into `.fv/`, and that 9 are blocked
  on operator-owned input defects in three named classes.
- Capability shift, no readiness shift: the ledger blocker class now has a
  toolkit path (stage the ledger, edit the staged copy, re-run), which is what
  R1 prescribes. The apply-ready count stays 1 of 10 because no project has
  used it.

## Outstanding follow-ups

- Six of the ten rows lack `mapped` / `preserved-history` counts. A `--json`
  dry-run sweep over all ten would complete the table and capture each refused
  ledger's full bounded diagnostic in one pass.
- `--apply` against a real legacy project remains unexercised. zkdcap is the
  only candidate today, and applying it writes a dispatch declaration plus the
  migrated intent and quarantines its 172 legacy files as history.
- `--stage-ledger-remediation` against a real legacy project is likewise
  unexercised. The five R1 projects are the candidates, and staging one writes
  exactly one file, `.fv/ledger.md`, leaving that project blocked until its
  citations are fixed there.
- The staging surface itself is uncommitted worktree state whose validation is
  partial: r35 (534 assertions) and r36 (214 assertions) pass locally, and a
  full `scripts/ci.py`, a full `tests/run_all.py`, and Gula re-validation are
  pending.
- A migrated project has no `fv-evidence-run/v3` evidence until its verification
  plan is run: `preserved-history` is not live evidence. zkdcap would migrate
  with no obligations manifest and no plan at all, so it starts with nothing to
  discharge and nothing discharged.
- Nine projects wait on R1, R2, and R3. None of them is waiting on this
  repository for a code change; R1 now waits on an operator running a tool this
  repository already carries in its working tree.
