# Dogfood evidence manifests (C9)

A dogfood evidence manifest is an immutable, per-project JSON record of what was
actually run and what was actually captured when the methodology was exercised
against a real project. It exists so a project can be cited as methodology
evidence only when its evidence is portable and checkable, not on the strength
of prose recollection.

## The rule

A project is described as a **dogfood observation** until a manifest with
`status: manifested` exists for it. Only `manifested` projects may be cited as
methodology evidence (in the README, in reports, in the coverage dashboard).
Everything else is an observation: useful, real, and driving the next iteration,
but not yet portable evidence.

- `status: observation` — a partially-captured record. Load-bearing bindings
  (commit, hashes, seeds, raw-report hashes, bounds) may be `null` because they
  were never recorded at run time. Honest nulls are required; do not backfill a
  plausible value you cannot verify.
- `status: manifested` — every required field carries a real, verifiable value:
  a pinned commit and dirty-tree hash, intent and spec hashes, exact commands,
  recorded tool and voice versions, bounds, seeds, and raw-report hashes. A
  manifest promotes from `observation` to `manifested` only by capturing the
  missing evidence, never by relabeling.

## Schema (`fv-dogfood-evidence/v2`)

One JSON object per project. Every listed key is required; values may be `null`
only in an `observation`-status manifest and only where the evidence was never
captured. See [`templates/dogfood-evidence.example.json`](../templates/dogfood-evidence.example.json)
for a filled-in observation.

| Field | Meaning |
|---|---|
| `schema` | `fv-dogfood-evidence/v2` |
| `status` | `observation` \| `manifested` (the rule above) |
| `project` | project name |
| `scope` | one-line description of what was exercised |
| `generated_at` | ISO-8601 UTC timestamp the manifest was written |
| `commits[]` | each `{ repo, commit, dirty_tree_hash, verified_input_snapshot, note }` exercised; `verified_input_snapshot` is the `sha256:<hex>` content snapshot a v3 record binds as `source_snapshot` (the commit id is provenance only) |
| `intent` | `{ path, dispatch_target_spec, version, sha256, note }` (G1 `intent_hash`); `path` is the repo-relative canonical target a record carries as `intent_path`, `dispatch_target_spec` the `.fv/dispatch.json` `omp_native.target_spec` it was resolved from (`null` = the `.fv/intent.md` default); include `version_prior_for_ledger` when a ledger lags the intent |
| `specs[]` | each `{ kind, path, version, sha256, note }` (Quint / Lean / Verus / Kani source) |
| `commands[]` | each `{ stage, command, note }`; `reference_script` when a dispatch script drove it (G1 `command`) |
| `tool_versions` | pinned tool digests; MUST carry `_cite` pointing at [`bom.json`](../bom.json) (G1 `toolchain_digests`) |
| `model_versions` | `{ _cite, voices, note }`; cite `registry/voices.json` once it exists (C4, forthcoming) |
| `bounds` | bounded-check depths (e.g. `apalache_max_steps`, `kani_unwind`) (G1 `configuration`) |
| `seeds` | per-tool seeds (e.g. `quint_run`) (G1 `seeds`) |
| `raw_reports[]` | each `{ stage, path, sha256, note }` pointing at the captured report (G1 `raw_output_hash`) |
| `canonical_paths_exercised[]` | each `{ stage, ran, evidence }`: which skills/stages ran, and which did NOT (gaps are evidence too) |
| `evidence_records` | `{ path, parser_schema_version, invariants_recorded, witnesses_recorded, system_claims_recorded, note }`: where the per-claim `fv-evidence-run/v3` records live and which obligations they cover; `system_claims_recorded` entries name the `required_evidence` tool IDs their cohort covers |
| `verification_plan` | `{ path, schema, note }`: the project's `fv-verification-plan/v1` document, or `null` when the pyramid ran on built-in defaults |
| `waivers[]` | accepted assumptions or human waivers, if any |
| `notes` | free-form provenance and honesty notes |

The manifest is a per-project provenance envelope. Its fields map onto the
per-claim G1 binding set enforced by
[`scripts/check_evidence_records.py`](../scripts/check_evidence_records.py):
`commits[].verified_input_snapshot` → `source_snapshot`, `intent.path` →
`intent_path`, `intent.sha256` → `intent_hash`, `tool_versions` →
`toolchain_digests`, `bounds` → `configuration`, `seeds` → `seeds`, and
`raw_reports[].sha256` → `raw_output_hash`. The two are complementary: the
manifest records project-level provenance once, and per-claim G1 records carry
the same bindings per trust claim. `check_evidence_records.py` reads G1 record
sets, not this manifest, so it does not consume the manifest directly; a
manifest is the envelope that makes a project's G1 records reproducible.

## Per-claim evidence records (`fv-evidence-run/v3`)

The `fv_evidence_run` tool ([`tools/evidence-run.ts`](../tools/evidence-run.ts))
is the only producer of G1 records. It writes one record per claim at
`.fv/evidence/records/<claim_id>.json`, one raw log per execution at
`.fv/evidence/raw/<claim_id>-<run_id>.log`, and binds both to the source and
intent state it observed. Gate B consumes those records; prose does not.

A record is `{ claim_id, required, evidence_class, result, scope, bindings,
waiver }`. Its `bindings` object carries, in this order:

| Binding | Meaning |
|---|---|
| `source_snapshot` | `sha256:<hex>` verified-input content snapshot, with a `+dirty` suffix when a non-excluded path was modified around the run |
| `intent_path` | repo-relative canonical target the record is bound to |
| `intent_hash` | SHA-256 over that target's bytes |
| `obligation_manifest_hash` | SHA-256 over `.fv/obligations.json` bytes |
| `profile` | `producer-trusted-execution` for producer output |
| `required_targets` | obligation IDs declared by the manifest at run time |
| `environment_policy` | `omp-extension-tool` |
| `toolchain_digests` | `{ executable, sha256, version, version_exit_code }` of the resolved launched executable |
| `command` | JSON-encoded argv string (the legacy single-command view) |
| `configuration` | `{ cwd }`, plus `pass_marker` when one was declared |
| `seeds` | per-tool seeds, or `null` |
| `raw_output_hash` | SHA-256 over the raw log bytes |
| `raw_output_path` | repo-relative raw log path |
| `executions` | nonempty execution cohort (below) |
| `parser_schema_version` | `fv-evidence-run/v3` |
| `run_id` | the run's timestamp; for a cohort, the cohort-wide timestamp |

Each `executions` entry is `{ tool, evidence_class, command (argv array), cwd
(repo-relative), toolchain_digests, raw_output_path, raw_output_hash, result,
run_id }` plus optional `pass_marker`. `tool` is the evidence tool ID that
`required_evidence` names, so it is set explicitly whenever the launched
executable is not the tool (`cargo` launching `cargo kani` is `cargo-kani`).
Per-execution `run_id` is the cohort timestamp for a single-command run, and
`<timestamp>-<n>-<tool-slug>` (`n` 1-based) for cohort entries; nothing is
concatenated, each execution keeps its own log and its own digests.

The record-level legacy bindings are derived from `executions[0]` verbatim:
`command` is its argv JSON-encoded, `raw_output_path`, `raw_output_hash`, and
`toolchain_digests` are its own, `configuration.cwd` is its `cwd`, and
`configuration.pass_marker` is present only when `executions[0]` declared one.
Gate B enforces that derivation for v3 records. Record-level `run_id` stays the
cohort timestamp. Because the record-level PASS-marker check runs against
`executions[0]`'s log, set record-level `evidence_class` to
`executions[0].evidence_class`.

`result` is `PASS` only when every execution's own `result` is `PASS` and the
bindings stayed stable across the whole cohort: identical snapshot, intent hash,
and obligation-manifest hash before and after, and no dirty verified inputs. Any
drift downgrades the record to `FAIL` while each execution keeps its own
verdict. Every PASS raw log must end with exactly one canonical
`--- fv-evidence: exit=0 ---` trailer and must match the evidence class's PASS
marker, or the declared `pass_marker` when one is given. Gate B applies that to
each execution's own log under that execution's own class, rejects a non-PASS
execution beneath a PASS record, and rejects a cohort that repeats a `tool` ID
because coverage would be ambiguous.

Gate B judges the cohort, not only the record's declared fields:

- Each execution's `evidence_class` must be admissible for the obligation's
  kind, not merely the record's. A `test-witnessed` execution under an
  invariant is rejected (`executions[i] incompatible evidence class ... for
  obligation kind ...`) however strong the record calls itself.
- Assumed evidence is assumed wherever it sits. If the record's class or any
  execution's class is `externally-assumed` or `unverified`, the claim cannot
  PASS without a waiver, and the message names every source
  (`record=code-enforced` is not a defence for `verus=unverified`).
- A `waiver` is a JSON object naming a nonempty `id`, `approver` and `scope`.
  Bare `true` is rejected, and so is an object that omits or blanks any of the
  three: `{"id": "WV-1"}` names a waiver nobody granted and nothing bounds, so
  it cannot carry an assumption to a PASS. An attributable waiver still can,
  and the verdict discloses it as `(waived: <claim>)`.
- One artifact discharges one execution, and one execution of one claim. Two
  executions may not cite the same `raw_output_path`; no two records in the
  judged set may cite the same artifact either, so a single PASS log cannot
  cover a second claim. Under `profile: producer-trusted-execution` each path
  must be exactly `.fv/evidence/raw/<claim_id>-<execution run_id>.log`, the
  name the producer writes. `fv-evidence-run/v2` records keep the legacy
  tolerance and are exempt from the cross-record rule.
- A PASS record may not be bound to a `+dirty` snapshot, in any comparison
  mode. A FAIL record may: the dirt is why it failed.
- A v3 cohort record must declare `profile: producer-trusted-execution`. v3 is
  producer-written by construction, and any other profile would otherwise dodge
  the producer artifact-naming and toolchain-identity rules keyed to it.
- Record-asserted provenance is shape-checked. `profile` must be a bare token
  (`[A-Za-z0-9][A-Za-z0-9._+/-]*`) because it is copied verbatim into the
  verdict scope, `required_targets` must be a nonempty array of obligation IDs,
  and `intent_hash`, `obligation_manifest_hash`, `environment_policy`,
  `parser_schema_version` and `run_id` must be nonempty strings. For a v3
  record `intent_path` must be one too: resolving it under the repository root
  needs the tree, but whether it is a path at all is record text, so both tools
  refuse a cohort record whose canonical target is an object or a list.
- With `--manifest`, a record's `obligation_manifest_hash` must equal the SHA-256
  of that manifest's bytes, and a v3 record's `required_targets` must equal the
  manifest's complete required-obligation set. Both expectations are derived
  from the manifest the run is judged against rather than read back off the
  record. Gate B also accepts `--expect-manifest` to pin the hash by hand;
  `coverage_dashboard.py` only derives it. Without `--manifest` there is no
  declared obligation set, so neither comparison and no per-execution
  obligation-kind check binds — on either tool.

### Invoking the producer

`fv_evidence_run` always takes `claim_id`, `evidence_class` (the record-level
class), `scope`, and optional `required` (default `true`). Beyond those it takes
exactly one of two mutually exclusive forms; passing neither or both errors with
`provide exactly one of command or executions`.

- Single command: `command` (argv array of nonempty strings) plus optional
  `cwd`, `tool`, and `pass_marker`. Produces a one-entry cohort.
- Cohort: `executions`, a nonempty array of
  `{ tool, command, evidence_class?, cwd?, pass_marker? }`. `tool` is required,
  matches `[A-Za-z0-9][A-Za-z0-9._:+/-]*`, and must be unique within the cohort;
  `evidence_class` defaults to the record-level class, `cwd` to `"."`, and
  `pass_marker` to the class marker. Top-level `cwd`, `tool`, and `pass_marker`
  are rejected in this form: they are per-execution.

A per-entry `evidence_class` governs that entry's PASS marker, its
`executions[i].evidence_class` field, and its admissibility for the obligation
kind. The record-level `evidence_class` stays whatever the top-level parameter
said, which is why a cohort should pass the class of its first execution — and
why declaring a strong record class over a weak execution buys nothing: the
waiver rule and the compatibility table both read the executions.

There is deliberately **no total strength ordering over evidence classes**, so
a record-level class is never checked for being "at least as strong as" the
cohort it heads. Nothing ranks `proof-discharged` against `bounded-checked`
against `conformance-tested` in a way that survives a reader disagreeing with
the ranking, and a synthetic lattice would sit between an obligation and its
evidence while looking authoritative. Disclosure plus per-execution
admissibility is what holds instead: every execution's class is recorded, each
is checked against the obligation kind's allowed set, an assumed or unverified
class anywhere in the cohort blocks PASS without a waiver, and the coverage
dashboard reports `by_execution_evidence_class` and `assumed_executions` beside
`by_evidence_class` so a cohort's weakest class is visible rather than hidden
behind the record's. A record class that overstates its cohort *within* one
kind's allowed set is therefore disclosed, not rejected.

### The verified-input snapshot

`source_snapshot` is not a commit id. It is `sha256:<hex>` computed over the
project's verified inputs: every tracked-or-untracked, unignored file
(`git ls-files --cached --others --exclude-standard -z`) minus the exclusion
prefixes, sorted by UTF-8 path bytes, hashed as repo-relative POSIX path, NUL,
file-content SHA-256 hex, newline. Symlinked candidates and candidates resolving
outside the project root are rejected.

Exclusion prefixes are the always-applied structural defaults
`.fv/evidence/`, `.fv/verify/`, `.fv/panels/`, `.fv/history/`,
`.fv/.migrate-staging/` and `.colosseum/`, unioned with
`.fv/verified-inputs.txt`, whose blank and `#` lines are ignored and whose
directory entries end in `/`. A project's file only ever *adds* prefixes; it
cannot drop a default. That is what makes evidence production self-stable
(writing and committing a record cannot move the snapshot the record is bound
to), keeps quarantined pre-FV history under `.fv/history/` from perturbing a
fresh run, and keeps a migration's staging tree under `.fv/.migrate-staging/`
out of the binding. The defaults live in `fv_project.DEFAULT_EXCLUSIONS` and
are mirrored in `tools/evidence-run.ts`, so the gate and the producer hash the
same input set.

The producer snapshots before and after the cohort and compares; Gate B
recomputes the current snapshot and compares again. So a record is fresh only
while the verified inputs it was produced against are byte-identical.

### A single-execution invariant record

One command, one execution, one raw log. Angle-bracketed values are
placeholders: the producer writes real digests and the gate recomputes them.

```json
{
  "claim_id": "A1",
  "required": true,
  "evidence_class": "bounded-checked",
  "result": "PASS",
  "scope": "proof_no_tied_elimination: no candidate is eliminated while tied for the minimum tally",
  "bindings": {
    "source_snapshot": "sha256:<64 hex over the verified inputs>",
    "intent_path": "docs/intent.md",
    "intent_hash": "<64 hex over docs/intent.md bytes>",
    "obligation_manifest_hash": "<64 hex over .fv/obligations.json bytes>",
    "profile": "producer-trusted-execution",
    "required_targets": ["A1", "W1", "S1"],
    "environment_policy": "omp-extension-tool",
    "toolchain_digests": {
      "executable": "/Users/dev/.cargo/bin/cargo",
      "sha256": "<64 hex over the cargo binary>",
      "version": "cargo 1.89.0",
      "version_exit_code": 0
    },
    "command": "[\"cargo\",\"kani\",\"--harness\",\"proof_no_tied_elimination\"]",
    "configuration": { "cwd": "contracts/rcv" },
    "seeds": null,
    "raw_output_hash": "<64 hex over the raw log>",
    "raw_output_path": ".fv/evidence/raw/A1-2026-09-15T11-42-07-311Z.log",
    "executions": [
      {
        "tool": "cargo-kani",
        "evidence_class": "bounded-checked",
        "command": ["cargo", "kani", "--harness", "proof_no_tied_elimination"],
        "cwd": "contracts/rcv",
        "toolchain_digests": {
          "executable": "/Users/dev/.cargo/bin/cargo",
          "sha256": "<64 hex over the cargo binary>",
          "version": "cargo 1.89.0",
          "version_exit_code": 0
        },
        "raw_output_path": ".fv/evidence/raw/A1-2026-09-15T11-42-07-311Z.log",
        "raw_output_hash": "<64 hex over the raw log>",
        "result": "PASS",
        "run_id": "2026-09-15T11-42-07-311Z"
      }
    ],
    "parser_schema_version": "fv-evidence-run/v3",
    "run_id": "2026-09-15T11-42-07-311Z"
  },
  "waiver": null
}
```

`intent_path` is `docs/intent.md` because `.fv/dispatch.json` declares
`omp_native.target_spec: "docs/intent.md"`; absent that declaration it is
`.fv/intent.md`. It is always repo-relative POSIX, resolved under the project
root, and a target that is missing, a directory, a symlink, or outside the root
is rejected before anything runs. `toolchain_digests` identifies the launched
executable (`cargo`), which is why `tool` names the evidence tool
(`cargo-kani`).

### A multi-execution system claim record

A system claim is discharged by a cohort, not by one command. Declare it in
`.fv/obligations.json` beside the invariants and witnesses it composes:

```json
{
  "version": 1,
  "invariants": [
    { "id": "A1", "statement": "No candidate is eliminated while tied for the minimum tally" }
  ],
  "witnesses": [
    { "id": "W1", "name": "witness_full_ballot_exhaustion" }
  ],
  "system_claims": [
    {
      "id": "S1",
      "statement": "Protocol model, proved tally core, and contract entry point agree on eliminated-candidate ordering",
      "depends_on": ["A1", "W1"],
      "required_evidence": ["quint", "verus", "cargo-kani"]
    }
  ]
}
```

The cohort record covers all three tool IDs in one atomic run, under one
snapshot:

```json
{
  "claim_id": "S1",
  "required": true,
  "evidence_class": "bounded-checked",
  "result": "PASS",
  "scope": "Tabulation composition: Quint protocol invariant, Verus-proved tally core, and Kani-bounded contract entry point agree on eliminated-candidate ordering",
  "bindings": {
    "source_snapshot": "sha256:<the same 64 hex as every other record in this run>",
    "intent_path": "docs/intent.md",
    "intent_hash": "<64 hex over docs/intent.md bytes>",
    "obligation_manifest_hash": "<64 hex over .fv/obligations.json bytes>",
    "profile": "producer-trusted-execution",
    "required_targets": ["A1", "W1", "S1"],
    "environment_policy": "omp-extension-tool",
    "toolchain_digests": {
      "executable": "/opt/homebrew/bin/quint",
      "sha256": "<64 hex over the quint binary>",
      "version": "0.32.0",
      "version_exit_code": 0
    },
    "command": "[\"quint\",\"verify\",\"specs/rcv.qnt\",\"--invariant\",\"eliminationOrderAgrees\"]",
    "configuration": { "cwd": "." },
    "seeds": null,
    "raw_output_hash": "<64 hex over the quint log>",
    "raw_output_path": ".fv/evidence/raw/S1-2026-09-15T11-58-02-104Z-1-quint.log",
    "executions": [
      {
        "tool": "quint",
        "evidence_class": "bounded-checked",
        "command": ["quint", "verify", "specs/rcv.qnt", "--invariant", "eliminationOrderAgrees"],
        "cwd": ".",
        "toolchain_digests": {
          "executable": "/opt/homebrew/bin/quint",
          "sha256": "<64 hex over the quint binary>",
          "version": "0.32.0",
          "version_exit_code": 0
        },
        "raw_output_path": ".fv/evidence/raw/S1-2026-09-15T11-58-02-104Z-1-quint.log",
        "raw_output_hash": "<64 hex over the quint log>",
        "result": "PASS",
        "run_id": "2026-09-15T11-58-02-104Z-1-quint"
      },
      {
        "tool": "verus",
        "evidence_class": "proof-discharged",
        "command": ["verus", "crates/tally/src/lib.rs"],
        "cwd": ".",
        "toolchain_digests": {
          "executable": "/Users/dev/.verus/bin/verus",
          "sha256": "<64 hex over the verus binary>",
          "version": "verus 0.2026.07",
          "version_exit_code": 0
        },
        "raw_output_path": ".fv/evidence/raw/S1-2026-09-15T11-58-02-104Z-2-verus.log",
        "raw_output_hash": "<64 hex over the verus log>",
        "result": "PASS",
        "run_id": "2026-09-15T11-58-02-104Z-2-verus",
        "pass_marker": "verification results:: 41 verified, 0 errors"
      },
      {
        "tool": "cargo-kani",
        "evidence_class": "bounded-checked",
        "command": ["cargo", "kani", "--harness", "proof_elimination_order_matches_model"],
        "cwd": "contracts/rcv",
        "toolchain_digests": {
          "executable": "/Users/dev/.cargo/bin/cargo",
          "sha256": "<64 hex over the cargo binary>",
          "version": "cargo 1.89.0",
          "version_exit_code": 0
        },
        "raw_output_path": ".fv/evidence/raw/S1-2026-09-15T11-58-02-104Z-3-cargo-kani.log",
        "raw_output_hash": "<64 hex over the kani log>",
        "result": "PASS",
        "run_id": "2026-09-15T11-58-02-104Z-3-cargo-kani"
      }
    ],
    "parser_schema_version": "fv-evidence-run/v3",
    "run_id": "2026-09-15T11-58-02-104Z"
  },
  "waiver": null
}
```

The record-level bindings are `executions[0]`'s (quint): its argv as `command`,
its log as `raw_output_path`/`raw_output_hash`, its digests, its `cwd`. Quint
declared no `pass_marker`, so `configuration` carries only `cwd` even though the
Verus execution declared one. Record-level `run_id` is the cohort timestamp,
while each execution's `run_id` is suffixed `-<n>-<tool-slug>` and names its own
log.

### `required_evidence` semantics

- IDs match `[A-Za-z0-9][A-Za-z0-9._:+/-]*` and must be nonempty and
  duplicate-free. `"cargo kani"` is rejected; name the tool ID `cargo-kani` and
  pass it as the execution's `tool`.
- Coverage is a Gate B condition: a `system_claim` record PASSes only when every
  `required_evidence` tool ID appears among executions whose `result` is `PASS`.
  A cohort missing `verus` cannot discharge `S1` no matter how green the rest is.
- Extra executions not named in `required_evidence` are allowed, and they are
  validated like any other: they must also be `PASS` for the record to be
  `PASS`.
- `depends_on` is nonempty, duplicate-free, and names declared invariants and
  witnesses only, never another claim. That makes a dependency cycle
  unrepresentable. A duplicate obligation ID, an unknown dependency, a
  dependency on another claim, or a malformed list makes the whole manifest an
  ERROR (exit 2), not a single failing claim.
- Dependencies still need their own records. `S1` passing does not discharge
  `A1` or `W1`; every required obligation carries its own record, bound to the
  same snapshot. `--require S1` does not narrow that away: Gate B and
  `coverage_dashboard.py` both expand a required system claim's `depends_on`
  into the required set and report the expansion under `dependency_expansion`,
  so a missing invariant record reads as INCOMPLETE rather than as nothing at
  all.

### Listing the records in the manifest

`evidence_records` is how the envelope points at the records above. A
`manifested` project fills it in; the shipped example leaves the lists empty
because verified-rcv produced no v3 record at all:

```json
{
  "evidence_records": {
    "path": ".fv/evidence/records/",
    "parser_schema_version": "fv-evidence-run/v3",
    "invariants_recorded": [
      { "claim_id": "A1", "tool": "cargo-kani", "result": "PASS" }
    ],
    "witnesses_recorded": [
      { "claim_id": "W1", "tool": "cargo-test", "result": "PASS" }
    ],
    "system_claims_recorded": [
      {
        "claim_id": "S1",
        "required_evidence": ["quint", "verus", "cargo-kani"],
        "executions": ["quint", "verus", "cargo-kani"],
        "result": "PASS"
      }
    ],
    "note": "All records bound to the snapshot in commits[0].verified_input_snapshot."
  }
}
```

Every listed record must validate under
`check_evidence_records.py --records .fv/evidence/records --manifest .fv/obligations.json`
with no `--expect-snapshot` and no `--allow-unbound`. A manifest whose listed
records only validate under those flags is an `observation`, not `manifested`.

### v2 compatibility is explicit-only

`fv-evidence-run/v2` records bound `source_snapshot` to a git commit id. Default
freshness is v3: with neither `--expect-snapshot` nor `--allow-unbound`, Gate B
recomputes the current verified-input snapshot and requires an exact match, so a
v2 record is reported stale with a hint naming its `parser_schema_version`. A v2
record validates only under an explicit invocation:

- `--expect-snapshot <commit> --expect-intent <hash>`: compare against the
  supplied values instead of recomputing; the snapshot matches by prefix unless
  `--snapshot-exact` is passed.
- `--allow-unbound`: skip source and intent binding entirely. Every other check
  (raw-artifact resolution, hash recomputation, PASS markers, obligation
  compatibility, cohort coverage) still runs.

One expected snapshot applies to the whole record set, so a mixed v2/v3 set
cannot be validated in one pass. Re-run the v2 claims through `fv_evidence_run`
rather than loosening the gate for the v3 records around them.

### Verdict banners

Both consumers of these records answer in one line, and neither ever prints a
bare `VERIFIED`:

```
VERDICT: VERIFIED[profile=producer-trusted-execution; binding=recomputed]
VERDICT: VERIFIED[profile=bounded; binding=not-recomputed] (waived: W1)
```

`profile` is the slash-joined set of profiles the judged records declare.
`binding` is what the tool did about freshness, and it is the field to read
before trusting the rest:

| `binding` | Emitted by | Meaning |
|---|---|---|
| `recomputed` | Gate B | the verified-input snapshot and the intent hash were recomputed this run and matched |
| `pinned` | Gate B | `--expect-snapshot` / `--expect-intent` supplied the values; nothing was recomputed |
| `unbound` | Gate B | `--allow-unbound`: source and intent binding skipped entirely |
| `not-recomputed` | `coverage_dashboard.py` | a read-only view over records; it recomputes nothing by design |

Waived claims are listed after the bracket so the scope stays a machine-readable
field list. A CI step that greps the banner can therefore tell an evidence-bound
VERIFIED from one earned with the freshness checks switched off, which the bare
`VERIFIED[profile=...]` form could not express.

`coverage_dashboard.py` renders the same records per claim. Its statuses are
`PASS`, `FAIL`, `INCOMPLETE`, `missing-record`, `duplicate-record`, `invalid`,
`unwaived-assumption`, `evidence-gap` (a required tool never PASSed, or an
execution in the cohort did not PASS) and `dependency-gap` (the cohort PASSes
but a `depends_on` obligation is not covered). It imports Gate B's schema module
and applies every Gate B rule that needs no repository access: field presence,
enums, waiver attribution, per-execution class compatibility, the
assumed-evidence rule over record and executions, the `+dirty` PASS rejection,
the `intent_path` shape check, the `obligation_manifest_hash` comparison,
per-record and cross-record artifact identity, the producer artifact-naming
rule, the v3 profile rule, the `required_targets`-equals-manifest rule, the
producible obligation-id rule when loading a manifest, and the legacy bindings'
derivation from `executions[0]`.

The only Gate B checks it does not run are the artifact reads — path
containment, digest recomputation, and PASS markers — which need the repository
root, plus snapshot and intent freshness, which needs the current tree. That is
what `binding=not-recomputed` says, and it is why the dashboard cannot report
coverage for a record Gate B rejects without reading the repository.

Two limits are shared rather than closed, and they are limits of the invocation,
not of one tool:

- Under `--require` with no `--manifest` there is no declared obligation set, so
  the `obligation_manifest_hash` comparison, the `required_targets` comparison
  and the obligation-kind checks do not bind in either tool. Name the manifest
  to get them.
- A `fv-evidence-run/v2` record keeps its own `profile` string, and that string
  reaches the verdict scope verbatim in both tools. Only a cohort-schema record
  is pinned to `producer-trusted-execution`, so a `VERIFIED[profile=...]` over
  v2 records says what the record asserted, not what a producer earned.

### Verification plans

When a project declares its layer commands instead of inheriting the pyramid's
built-in defaults, it does so in a `fv-verification-plan/v1` document at
`.fv/verification-plan.json` and names it in the manifest's
`verification_plan.path`.
[`scripts/verification-plan.example.json`](../scripts/verification-plan.example.json)
is the shipped example; `pyramid_run.py --plan <path>` executes it:

```json
{
  "schema": "fv-verification-plan/v1",
  "layers": {
    "types": {
      "required": true,
      "executions": [
        {
          "argv": ["cargo", "check", "--quiet", "--all-targets"],
          "cwd": ".",
          "timeout_seconds": 900,
          "env": { "CARGO_TERM_COLOR": "never" },
          "evidence_tool": "cargo-check"
        }
      ]
    },
    "lints": {
      "required": true,
      "executions": [
        {
          "argv": ["cargo", "clippy", "--quiet", "--all-targets", "--", "-D", "warnings"],
          "cwd": ".",
          "timeout_seconds": 900,
          "evidence_tool": "cargo-clippy"
        },
        {
          "argv": ["cargo", "fmt", "--check"],
          "cwd": ".",
          "timeout_seconds": 120,
          "evidence_tool": "cargo-fmt"
        }
      ]
    }
  }
}
```

`executions` is nonempty and ordered: every invocation runs, and any non-zero
exit fails the layer. `argv` is an argv array, never a shell string; `cwd` stays
repo-relative; `timeout_seconds` is a positive integer; declared `env` merges
over the subprocess environment without mutating the ambient one. Layers the
plan does not name keep the built-in defaults, and without `--plan` the runner
is the legacy runner. `evidence_tool` names the evidence tool ID the execution
stands for, which is how a plan execution and a `required_evidence` entry are
matched by name.

## verified-rcv ledger regeneration

Regenerating verified-rcv's integration ledger against its current intent
(v0.3.15; the ledger was generated at v0.3.5) is pending work in the
**verified-rcv repository itself** and is out of scope for the fv repo.
The example manifest records the staleness as an observation; it does not
regenerate anything.

## Producing a manifest

1. Copy `templates/dogfood-evidence.example.json` into the project at
   `.fv/dogfood-evidence.json`.
2. Fill every field from captured evidence. Where you have no captured value,
   leave `null` and keep `status: observation`.
3. Produce the per-claim records with `fv_evidence_run` - one per invariant and
   witness, one cohort per system claim - and list them under
   `evidence_records`, with `parser_schema_version` and the snapshot they share.
4. Record `verified_input_snapshot` per repo, the repo-relative `intent.path`
   and its `dispatch_target_spec`, and `verification_plan.path` when the project
   declares its layers.
5. Capture the missing bindings (commit, hashes, seeds, bounds, raw-report
   hashes) on the next run, then flip `status` to `manifested`. A manifest may
   claim `manifested` only when every listed record validates under
   `check_evidence_records.py` without `--allow-unbound`.
6. Only then may the project be cited as methodology evidence.

---

Licensed under the Apache License, Version 2.0. See [`LICENSE`](../LICENSE);
Copyright 2026 Reliq.
