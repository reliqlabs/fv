# FV concepts

The names and ideas this methodology uses. Authoritative; SKILLs and docs use these terms.

## The five pillars

The five complementary trust mechanisms FV composes. Always referred to by name, not number.

| Pillar | What it does |
|---|---|
| **Formal verification** | Mechanistic proofs; real guarantees, not statistical confidence |
| **Adversarial generation** | One model produces, another attacks. Adversaries beat consensus for correctness work |
| **Substrate constraints** | Types, ownership, linters, sanitizers — cheap, deterministic, deny whole bug classes |
| **Empirical validation** | Property tests, fuzzing, bounded model checking — covers regions formal methods can't reach |
| **Boundary discipline** | Narrow trusted/untrusted interfaces; verified core, contained periphery |

## The verification pyramid

Cheap to expensive, exec and spec axes. Each property routes to the cheapest tool that can verify it.

**Exec axis** (against real Rust, cheap → expensive):
Types → Lints → Property tests → Fuzzing → Kani → Verus → Aeneas → Lean

**Spec axis** (upstream of code, when system-level reasoning matters):
Quint / TLA+ → Lean (math, refinement)

## The workflow

Ten stages. Each stage produces an artifact that anchors the next.

1. **Intent doc** — human-written source of truth
2. **Tracer prototype** — fast throwaway, proves the design is feasible
3. **Intent revision** — informed by tracer
4. **System spec** — Quint/TLA+ when distributed semantics matter
5. **Implementation spec** — Lean specs and/or Verus annotations
6. **Spec adversarial review** — multi-model attack on each spec draft
7. **Implementation** — Rust against validated specs
8. **Verification** — the pyramid runs continuously
9. **Failure classification** — spec wrong / code wrong / prover stuck / tool mismatch / state-space blowup / infrastructure (`INDETERMINATE` when the evidence cannot decide)
10. **Coverage dashboard** — per-function trust calibration

Steps are sequential; later additions get *names*, not fractional numbers. If a step gets inserted between two existing steps, it earns a real name and a real position.

## The SKILLs

The verbs you actually run. Each is a SKILL the harness can invoke.

| SKILL | Verb | Stage |
|---|---|---|
| `fv-intent` | Author an intent doc forward (elicitation) | 1 |
| `fv-reverse-intent` | Distill an intent doc from existing code | 1 (retro) |
| `fv-adversarial` | Run spec adversarial review with intent + Quint trace generation | 6 |
| `fv-code-adversarial` | Read implementation against intent through six lenses | between 7 and 8 |
| `fv-lifecycle-adversary` | Red-team multi-tx admin features against Quint | when contract gains admin features |
| `fv-verify` | Run the verification pyramid | 8 |
| `fv-compose` | Maintain cross-component trust ledger with code-line citations | 8 (continuous) |
| `fv-change` | Upstream-first change loop with re-verification | when changing a spec'd project |

## Project layout

Canonical locations within a FV-managed project. Skills cite these; do not invent alternatives per skill.

- `<project>/.fv/dispatch.json` → `omp_native.target_spec` — **the canonical intent/target declaration**. Its value is the intent document, persisted repo-relative to the project root; when the key is absent the target is `<project>/.fv/intent.md`. A skill that needs the intent resolves the declaration against the project root (never the cwd, never a fixed search order); an absolute value is valid only when it resolves inside the project root, and a missing, directory, symlink, or escaping target is an error, not a cue to look elsewhere. A project that wants the intent visible at top level declares `target_spec: "intent.md"` rather than relying on a fallback. `scripts/fv_project.py` (`resolve_target`, or `fv_project.py target --root <project>`) is the one implementation of these rules; installs also carry it at `<project>/.fv/scripts/fv_project.py`.
- `<project>/.fv/intent.md` — the default location of the intent document, used when `dispatch.json` declares no `target_spec`
- `<project>/.fv/ledger.md` — the trust ledger
- `<project>/.fv/attacks/` — spec adversarial reports, verbatim (`fv-adversarial`)
- `<project>/.fv/code-adversarial/` — code adversarial review reports (`fv-code-adversarial`)
- `<project>/.fv/lifecycle-adversary/` — lifecycle red-team reports (`fv-lifecycle-adversary`)
- `<project>/.fv/changes/` — change impact reports (`fv-change`)
- `<project>/.fv/verify/` — pyramid run reports (`fv-verify`)
- `<project>/.fv/classifications/` — failure-classifier reports (`fv-verify`)
- `<project>/.fv/evidence/` — typed G1 evidence records, one JSON per claim ID (`fv-compose`, Gate B)
- `<project>/.fv/scripts/` — project-local copies of dispatch + CI-gate scripts
- `<project>/.fv/verified-inputs.txt` — the verified-input **exclusion** list that defines the content snapshot (below)
- `<project>/.fv/verification-plan.json` — optional `fv-verification-plan/v1` layer configuration read by `pyramid_run.py --plan`
- `<project>/.fv/history/colosseum/` — quarantined pre-FV artifacts, byte-for-byte, written by `scripts/fv_migrate.py`; history, never live evidence, and excluded from the content snapshot by a structural default rather than by a project declaration
- `<fv>/agents/` — static OMP agents loaded from the extension package

## The trust ledger

A project's `.fv/ledger.md` records every cross-component trust claim with:
- the named theorem
- the tools that contribute (Quint property, Lean theorem, Verus annotation, Kani harness)
- code-line citations for each link, under a `Depends on:` header whose entries
  are indented beneath it; the block ends at the first blank line, heading, or
  nonblank non-entry line, so unrelated later bullets are not read as links
- axiom inventory (which axioms each theorem's closure depends on)

`fv-compose` maintains it. CI gates fail when a link drifts from executable code.

## The verified-input content snapshot

What a G1 evidence record binds its verdict to. A *verified input* is a file
whose content could change what a verification run concludes; the snapshot is a
single hash over all of them, so a record names the exact tree state it was
earned against rather than a commit plus a dirty flag.

- **The input set is an exclusion list.** `.fv/verified-inputs.txt` holds
  path prefixes to *exclude* (blank and `#` lines ignored, directory entries
  end in `/`). Six prefixes are structural defaults, applied whether or not
  any file declares them: `.fv/evidence/`, `.fv/verify/`, `.fv/panels/`,
  `.fv/history/`, `.fv/.migrate-staging/`, and `.colosseum/`. A project's file
  only ever *adds* prefixes to them, so quarantined history and a migration's
  staging tree cannot perturb the snapshot even after `fv_init --force`
  rewrites the project file — the guarantee is a property of the defaults, not
  of a line the migration happened to write. Everything else that
  `git ls-files --cached --others --exclude-standard` reports is a verified
  input. Exclusion, not inclusion, is the safe default: a newly added source
  file is in scope automatically, and only FV's own generated output and
  quarantined history sit outside it. Entries are separated by LF or CRLF
  only: any other break character the Python and TypeScript parsers would
  split differently is rejected on both ends rather than yielding two
  exclusion sets from one list.
- **A verified input must be a regular file.** A tracked path whose worktree
  entry is a symlink, a FIFO, or any other non-regular file is classified as
  an error instead of being opened, so a snapshot can never block forever on
  a reader that never arrives. Directory entries (submodule gitlinks) are
  skipped; they are verified by their own repository.
- **The snapshot is content, not identity.** `sha256:<hex>` over, for each
  input in sorted repo-relative POSIX-path order, the path, a NUL byte, the
  file's content SHA-256 in hex, and a newline. Symlinks and paths resolving
  outside the project root are rejected rather than hashed.
- **It is checked around every execution, not once per run.** The producer
  recomputes the snapshot, the intent hash, and the obligation-manifest hash
  after each command. A command that edits a verified input therefore cannot
  ship as PASS evidence — not for itself, and not for an earlier command in the
  same record.
- **A moving tree is recorded, not tolerated.** If git reports a verified input
  as modified, or if the snapshot, intent hash, or manifest hash moves between
  two executions of one run, the record's snapshot is written as
  `sha256:<hex>+dirty` and its result is FAIL. Evidence earned against a moving
  tree is unusable by construction rather than quietly weaker.
- **The gate recomputes it, and says so.** Gate B computes the current
  snapshot and, by default, requires an exact match; `--expect-snapshot`,
  `--expect-intent`, and `--allow-unbound` are the explicit, visible ways to
  validate a record against something else. Which discipline ran is part of
  the verdict rather than a flag only the operator saw:
  `VERIFIED[profile=...; binding=recomputed]` for the default,
  `binding=pinned` when a snapshot or intent hash was supplied instead of
  recomputed, and `binding=unbound` under `--allow-unbound`. A reader who
  greps the banner can no longer mistake a pinned or unbound run for an
  evidence-bound one. The coverage dashboard, which reads records and never
  recomputes anything, says `binding=not-recomputed` for the same reason.
  A record whose snapshot carries the `+dirty` marker cannot PASS in any
  comparison mode, so the producer's honesty marker is enforced rather than
  advisory.
- **It is portable.** Two clones or worktrees with the same content produce the
  same snapshot, so evidence earned in one is checkable in another. This is
  what makes a G1 record a transferable artifact instead of a claim about one
  machine.

`scripts/fv_project.py` (`content_snapshot`, `is_content_snapshot`,
`load_exclusions`) is the rule's Python implementation; the gates and the
doctor call it rather than reimplementing it, and the TypeScript producer
(`tools/evidence-run.ts`) mirrors the same byte-for-byte rule so producer and
gate bind identically.

## System claims and evidence cohorts

A **system claim** is an obligation no single tool discharges. It lives in
`obligations.json` beside `invariants` and `witnesses`, and carries:

- `id` — its stable obligation ID
- `depends_on` — the declared invariants/witnesses it rests on
- `required_evidence` — the tool/layer IDs whose evidence it needs

An **evidence cohort** is what discharges one: an `fv-evidence-run/v3` record
whose `bindings.executions` array holds one entry per command, each with its
tool, evidence class, argv, repo-relative cwd, toolchain digests, raw-output
path and hash, result, and run ID. A single-command record is a cohort of one.

Three rules make a cohort a real conjunction rather than a bag of results:

1. **A cohort's verdict is atomic.** The record PASSes only when *every*
   execution PASSes and every binding — snapshot, intent hash, manifest hash —
   held still across the whole run. A partially-passing cohort is a FAIL
   record, not a partial credit. The obligation/class compatibility table
   applies per execution too, so a witness-only class cannot hide inside an
   invariant's cohort, and an `externally-assumed` or `unverified` class
   anywhere in the record — declared class or any execution's — needs a
   waiver to PASS.
   The record-level class is *not* ranked against its executions: there is no
   total strength ordering over evidence classes, and inventing one would put
   a synthetic lattice between an obligation and its evidence. Admissibility
   is checked per execution against the obligation kind, and every execution's
   class is disclosed — the coverage dashboard reports
   `by_execution_evidence_class` and `assumed_executions` beside the record
   classes — so a record class that overstates its cohort inside one kind's
   allowed set is visible rather than silently accepted as the cohort's class.
2. **One artifact discharges one execution.** Each execution commits to its
   own raw-output path and hash; two executions of a cohort may not cite the
   same artifact, and no two claims in a run may cite one either. A record
   written under the producer profile must name the artifact the producer
   would have written, `.fv/evidence/raw/<claim_id>-<run_id>.log`, so a
   single passing log cannot be pointed at from everywhere.
3. **A system claim PASSes only under full tool coverage.** Every ID in
   `required_evidence` must appear among the cohort's PASS executions. The
   coverage dashboard names the two ways this fails: `evidence-gap` (a
   required tool never PASSed, or carries no cohort at all, or some other
   execution in the cohort did not PASS) and `dependency-gap` (the cohort
   fully PASSes but a `depends_on` obligation is itself uncovered). Judging a
   system claim through `--require` pulls its `depends_on` obligations into
   the required set, so a composition is never reported VERIFIED while its
   parts went unexamined.

Because the claim is a conjunction, **anything that invalidates one member
invalidates the claim.** A content-snapshot change, a re-run of a single tool
that now FAILs, a dropped tool from the cohort, or a `depends_on` obligation
losing its own evidence each take the system claim out of PASS; it is re-earned
by re-running the cohort, not by patching the one execution that moved.

## Shadow migration of a legacy tree

A **shadow migration** brings a pre-FV `.colosseum` project under FV without
touching it: `scripts/fv_migrate.py PROJECT [--apply]` reads the legacy tree,
writes only under `.fv/`, and leaves `.colosseum/` byte-identical as the
auditable original for everything the translation cannot carry. Dry run is the
default. Every legacy file is classified exactly once as `mapped`,
`preserved-history`, or `unsupported`, and any `unsupported` row or
destination conflict blocks the run rather than producing a partial `.fv/`.

- **The write is staged, and a failed write rolls back.** `--apply` builds
  every destination under `.fv/.migrate-staging/<pid>-<random>/` in full, then
  moves each into place with `os.replace`, which does not follow a symlink at
  the final name. A destination that already exists is moved aside into the
  same staging tree first, so putting it back is a rename of its own inode and
  carries its mode, ownership and timestamps along with its bytes. A failure
  part-way through the moves rolls back every destination already moved, and
  the report is printed even when the apply fails — each write's action says
  what happened to it (`written`, `rolled-back`, `failed`, `lost`,
  `pending`), `lost` being a destination whose original could not be renamed
  back and is therefore absent — because the report is the only enumeration of
  what landed. Preflight refuses a destination whose path
  crosses a symlink at *any* component (`.fv` itself included) and a
  destination directory that is not writable, so the common failures block
  with zero writes. A completed apply and a completed rollback both remove the
  staging tree; a rollback that could not put a destination back keeps it
  deliberately, because the aside-moved original inode is then the only copy of
  the replaced bytes, and the error names the retained directory. A migration
  killed outright also leaves one `.fv/.migrate-staging/<pid>-<random>/`
  directory behind. Either way the residue is snapshot-excluded, never collides
  with a later run, and is safe to delete once its contents are accounted for.
  Nothing garbage-collects it: a sweep would have to decide that another
  process's staging tree is dead, and guessing that wrong would delete a live
  migration's bytes or a rollback's only surviving originals.
- **The dispatch target is elected from a declaration, never from prose
  frequency.** The legacy pointer stub decides first; the ledger's citations
  decide only when the stub cites nothing. Two or more surviving candidates,
  or none at all, are `unsupported` and block. The elected `target_spec` is a
  top-level field of the migration report, so a dry-run consumer can check
  the decision without parsing a detail string.
- **Legacy evidence becomes history, not evidence.** v1/v2 records under
  `.colosseum/evidence/` are preserved byte-for-byte under
  `.fv/history/colosseum/<path>` and never placed where Gate B would read
  them as live `fv-evidence-run/v3` evidence. `.fv/history/` is a structural
  snapshot exclusion, so quarantining them cannot invalidate fresh evidence.
- **A lossy translation names what it dropped.** Migrated obligation ids are
  normalized into the shape the evidence producer can discharge, with the
  legacy string kept in `legacy_id` and any collision or empty normalization
  blocking. Claim keys with no typed slot survive under `legacy_fields` and
  are named in a `#claims.<id>` deviation row; a merged layer, a dropped
  document key, and an adopted `dispatch.json` route are each reported the
  same way. Silence is never the record of a translation choice.
- **A claim whose evidence the migrated plan cannot produce blocks the
  migration.** Every `required_evidence` tool is checked back against the
  translated plan; a tool no migrated execution produces is `unsupported`,
  including the case where the legacy tree recorded no run manifest at all and
  the plan therefore declares nothing. A legacy project with claims but no
  recorded runs is consequently unmigratable until either its runs are
  recorded in `.colosseum/evidence/runs/layer-runs.json` or the claims stop
  naming layers nothing can run. That is the intended direction: the
  alternative is a migrated manifest whose claims can never be discharged,
  which reads as "evidence missing" rather than "this claim was never
  runnable here".

## Trust-assumption categories

Each axiom in a project's trust closure falls into one of these. Always referred to by name.

| Category | What it means |
|---|---|
| **Standard cryptographic assumption** | Reduces to a textbook primitive (EUF-CMA, DDH, collision resistance, etc.) |
| **Deployment-side commitment** | Deployer-side runtime obligation (collateral freshness, rotation, well-formedness) |
| **Parser-layout assertion** | Pins a parser output to a specific window of input bytes; cross-checked against production code |
| **Bundled trust boundary** | Multiple primitives wrapped into one axiom for convenience; cleanup target |
| **Over-strength** | Asserts more than reality warrants; usually a refactoring target |
| **Impossibility / vacuity** | Assertion holds vacuously or asserts the impossible; bug |
| **External module dependency** | Trust assumption supplied by an upstream component, named explicitly |
| **Lean standard** | `propext`, `Classical.choice`, `Quot.sound` — accepted ambient |
| **Predicate carrier** | Opaque predicate with no asserted truth value; bookkeeping only |
| **Completeness** | The verifier accepts genuinely valid inputs; typically the dual of soundness |

The first four are the ones cleanup work moves *toward* (named primitives, named commitments, narrow assertions). The next two are what cleanup moves *away from*.

## Adversarial review findings

Findings are tagged inline with severity:

- **Critical** — soundness gap, allows attacks past the verifier
- **High** — audit-transparency gap, misleads reviewers about what's trusted
- **Medium** — methodology / framing tightening
- **Low** — cosmetic / docstring honesty

Inside a single review, findings are numbered (Critical 1, Critical 2, High 1, ...). Across reviews, findings are referred to by the practice they targeted (e.g., "the `signed_by_qe` decomposition critique") rather than by review-internal labels.

## Naming rules

Three rules to keep the namespace cheap to learn.

1. **No cycle numbers.** Git commits are the chronology. Commit messages carry the descriptive title. There is no "Cycle 7.5" — there is the commit whose title is "axiom demotion via DCAP reference verifier". (Exemption: the `Round: <N>` field in an attack report's metadata header is an ordinal within one spec's attack series — "the third attack against this intent" — not project chronology. It stays.)
2. **No fractional steps.** A step inserted later gets a name, not `Step 4.5`. If the name doesn't fit, the step shape was wrong.
3. **No alphabetical asks.** Methodology improvements live in `methodology-improvements.md` under their practice name (e.g., "system-of-intents shape", "per-section adversarial dispatch", "ghost-variable encoding"). Historical letter labels (Ask A, Ask AB) remain in archive only.

## Where the historical labels live

For traceability only — never load-bearing for new work.

- `archive/` — old MEMORY snapshots
- `methodology-improvements.md` — current improvements; previous "Ask X" labels appear in a single archive table at the end mapping old label → current practice name
- Per-project `.fv/ledger.md` — frozen historical artifacts (e.g., Quartz's `Cycle 7.x` ledger entries) — stay as-is; they are the audit trail
