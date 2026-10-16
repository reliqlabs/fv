# Code-adversarial review: FV v4 evidence producer, adoption/dashboard round 2 - 2026-10-15

- Operator: fv-code-adversary via OMP task (NOT openai-codex/gpt-6.1-sol task agents FixNativeOwnership-2, FixProducerStore-2, FixSourceBindings-2, FixAdoptionDashboard-2, FixBaseToolchain, FixRustToolchain, FixProofToolchain, or the parent orchestrator)
- Code commit reviewed: 6c787c20f023a132856cf5119b137be25dd2303f (round-1 target aa6946f). The caller supplied the commit. I did not compute a diff: I had no shell, so all code citations point at the current worktree files.
- Intent version reviewed: `docs/execution-evidence-v4.md` has no frontmatter version, only a Status line at V4:3. I also used `.fv/changes/2026-10-14-execution-evidence-v4.md` §"Post-commit review dispositions (2026-10-15)", lines 113-127.
- Ledger version reviewed: absent. `F/.fv/ledger.md` does not exist.
- Lens pack: crypto/enclave, plus migration/preservation, compatibility/path-discovery and reporting-truthfulness lenses, as in round 1
- Lenses applied: 1 through 6

## Intent resolution and scope

`F/.fv/dispatch.json` is absent, so the gate's literal canonical target is `F/.fv/intent.md`, and that file is also absent. Round 1 resolved its intent through Dossier's `D/.fv/dispatch.json`. This round is grounded in the targets the caller named explicitly: V4 and the change record. That is a caller-supplied target, not a fallback search. The invoking skill should record that deviation from the gate.

Aliases used below:
- `F` = PROJECT_ROOT
- `init` = `F/scripts/fv_init.py`
- `dash` = `F/scripts/coverage_dashboard.py`
- `gate` = `F/scripts/check_evidence_records.py`
- `v4` = `F/scripts/fv_evidence_v4.py`
- `schema` = `F/scripts/fv_evidence_v4_schema.py`
- `T-adopt` = `F/tests/r38_evidence_v4_adoption_review.py`
- `T-port` = `F/tests/r38_evidence_v4_portable.py`
- `CR` = the change record

I ran no commands, tests, builds or writes. The parent's Darwin 150/150 and Linux 114/7-skip results are accepted as reported.

Uncovered classes: native concurrency and locking, real crash/power-loss behavior, resource exhaustion, supply-chain authenticity of the FV checkout, and protocol authorization/arithmetic. Native, store, source and toolchain fixes outside this delta were followed only where a cited call led there.

---

## Lens 1 - Commitment coverage

| Commitment | Attacker DoFs | Bound by | Gap |
|---|---|---|---|
| Installed helper bytes (five `PROJECT_SCRIPT_NAMES`, `fv_project.py:33-39`) | Destination inode or alias, staged bytes, partially completed set | `init:67-100` preflights the whole set: no symlinked `.fv` or `.fv/scripts`, regular destinations only, `st_nlink==1`. `init:53-63` copies to a fresh sibling and swaps it in with `replace`. | No authentication of the FV checkout (trust premise, unchanged). The set is replaced file by file and is not durable (CA-03). |
| Records path to run manifest | `--records` spelling, symlink components, `..`, project selection | `dash:1206`, `gate:961` call `.absolute()` with no symlink resolution. `v4:1954-1978` `_read_entry` requires containment and runs `_regular`, which rejects symlinks per component (`v4:76-88`). | No new commitment omission. `..` spellings are refused (CA-01). |
| Dashboard and gate counts | Rows versus counters on error returns | The `finally` block in `assess_v4` recounts association states (`v4:3028-3041`) | Physical counters are still a measured 0 on early errors (CA-02) |

The delta adds no hash, signature or ReportData construction.

## Lens 2 - Clause-to-line discharge

| Clause | Expected discharge | Actual code line | Status |
|---|---|---|---|
| CR:122 "alias-safe helper refresh by rename" | Reject aliases before any write; replace the directory entry without truncating the old inode | `init:73-100` preflight; `init:53-63` NamedTemporaryFile in the same directory, `copy2`, `replace`, `unlink` in `finally`; tests at `T-adopt:65-140` (six arrangements) and `T-adopt:142-167` (old open handles keep their old bytes, no stray names) | discharged |
| INSTALL.md:132-136 "leaves intent, policy, dispatch, … evidence and history unchanged" | Physical containment of the refresh write set | Same as above | discharged for the alias vectors. Mid-sequence failure leaves a mixed helper set (CA-03). Refresh still creates `.fv/scripts` in a non-project directory (CA-05, pre-existing). |
| CR:122 "cwd-relative `--records`" plus V4:9 established v3 behavior | v3 and v4 read the same file the operator named, relative to the invocation cwd | `dash:1205-1210`, `gate:960-967`; `infer_repo_root` at `gate:735-743`; `detect_v4` at `v4:2013-2057` | partial: parent-cwd spellings work for v3 and v4 (`T-adopt:172-236`, `T-adopt:238-293`). Nested- or sibling-cwd `..` spellings work for v3 and ERROR for v4 (CA-01). |
| V4:569 "Report logical association counts separately from … missing/failed/cancelled work"; V4:15 S1 | Counts agree with retained rows on every return path | `v4:3028-3041` `finally` recount; tests at `T-adopt:296-358` | discharged for association counters. Physical counters still read 0 (CA-02). |
| V4:9, V4:13 exact-schema dispatch, fail closed | Unknown or mixed schemas fail closed; v3 path unchanged | `v4:1980-2010`, `v4:2048-2056`; `gate:968-981` V4Error→ERROR, `gate:982-984` legacy errors fall to `load_records` | discharged |
| V4:20 T2 and CR:127 known limit (Linux refuses group signals; work stays indeterminate) | Unsupported runtimes refuse at discovery | `tools/evidence-v4/evidence-v4-native.ts:704-711` (darwin + Bun 1.3.14 + no forced waiter) | discharged for the predicate. Portable consequences are in the CA-04 skip section. |

## Lens 3 - Deferred cannot silently succeed

| Branch | Reachable from | Behavior | Status |
|---|---|---|---|
| Refresh preflight refusal | `init:499-506` | Raises `ProjectError`, prints FATAL, exits 1 | Explicit non-success |
| Refresh mid-sequence `OSError` | `init:101-107` → `init:504-506` | Exits 1, but the replaced-file list in `results` is discarded | Non-success; the state report is missing (CA-03) |
| `assess_v4` exception path | `v4:3013-3027` | ERROR or FAILED; counts recomputed in `finally` | Explicit non-success |
| Gate legacy fallback on `OSError`/JSON errors during detection | `gate:982-984` | Goes to the legacy path. A v4 file read there cannot produce a v3 PASS because it has no `bindings` envelope. [INFERENCE: the legacy loader's handling of a v4 shape was not re-audited in this round] | No silent success found |
| T-port CA-04 skip (`T-port:855-858`) | Linux, or non-1.3.14 Bun | Test skipped | Test gate, not a production branch. See the CA-04 skip section. |
| Production TODO/stub search in the delta | All four scripts | None found | Empty |

## Lens 4 - Who controls

| Field | Supplier | Validation | Gap |
|---|---|---|---|
| `.fv`, `.fv/scripts` directory objects | Project filesystem | `lstat`: not a symlink, is a directory (`init:73-86`) | None for refresh. The ordinary non-force init also refuses now (CA-04). |
| Destination helper inodes | Project filesystem | `lstat`: not a symlink, regular file, `st_nlink==1` (`init:87-100`) | Since `replace` swaps the directory entry, a hardlink can no longer be corrupted. The nlink refusal is now stricter than needed, but fails closed. |
| `--records` | CLI operator | `.absolute()` without resolve; containment, per-component symlink check and `path()` grammar (`schema:151-164`) | `..` rejected (CA-01) |
| `--root` (gate) | CLI operator | `.resolve()` (`gate:965`) | Records are now cwd-relative even when `--root` is given. A repo-relative spelling from another cwd fails closed. Documented `--root` examples (`templates/evidence-records.example.json:53`, `docs/dogfood-evidence.md:529`) are v3, and v3 was always cwd-relative. No regression found. |
| Refresh project root | CLI operator | `resolve_project_root` checks only that the directory exists (`fv_project.py:88-91`) | Pre-existing (CA-05) |

## Lens 5 - Field-name fidelity

| Field | Implied semantic | Actual value | Status |
|---|---|---|---|
| `missing/failed/error/cancelled_associations` | Count of slots in that state | Recounted from `per_claim` slot states on every return (`v4:3028-3041`) | Faithful |
| `logical_associations` | Expanded policy slots | Set at `v4:2447-2449` after expansion. It is 0 if the exception fires before expansion. | Measured 0 when nothing was expanded (part of CA-02) |
| `actual_dispatches`, `cache_hits`, `unique_physical_executions` | Physical work in the selected run | Computed at `v4:2517-2522` and later. They stay at the initial 0 (`v4:2310-2312`) when a binding or interval check at `v4:2450-2459` raises first. The dashboard text prints them (`dash:1083-1088`). | Measured 0 for work that ran (CA-02) |
| `repo_root` | Physical project root | `str(reader.root)` (`v4:2338`); asserted in `T-adopt:194` | Faithful |
| Dashboard rows versus counts | Same population | Counts cover every policy record; dashboard rows show required claims only (`dash:941-946`) | Faithful to V4:569 (policy-wide logical counts). Not a finding: Dossier's records are all required. |

## Lens 6 - Deferral justification audit

| Deferred finding | Justification claims | Claim audit | Verdict |
|---|---|---|---|
| CR:127 Linux/other runtimes leave work indeterminate | (1) The producer refuses group signals off Darwin/1.3.14. (2) Work is left indeterminate rather than PASS. | (1) `native.ts:704-711` holds. (2) The cancelled execution is recorded as `kind:"execution"`, `result:"ERROR"` (`evidence-v4-run.ts:893-905`). The pending result is retained when ownership is not closed (`run.ts:906-909`). Resume returns ERROR (`r38_evidence_v4_lifecycle.py:771-773`). | Holds. See the CA-04 skip section for the portable consequence. |
| CR:127 Lake coverage is Lean-specific | Not in this delta | Not audited | Out of slice |
| Round 1 had no deferrals in this slice | Not applicable | Not applicable | Empty |

---

## Round-1 closure

| Round-1 finding | Verdict | Evidence |
|---|---|---|
| CA-01 (destructive refresh aliasing, Major) | **closed** | The whole-set preflight runs before any write (`init:73-100`), so every alias arrangement exits 1 with nothing written (`T-adopt:65-140`). The swap uses a same-directory temp file and `Path.replace` (`init:53-63`), which renames the entry and never opens the destination for writing. Hardlinked or open old inodes keep their bytes (`T-adopt:142-167`). The temp file is unlinked on every Python-level failure (`init:62-63`). Residuals: CA-03 and CA-04. |
| CA-02 (cwd-relative `--records`, Minor) | **partially closed** | Both CLIs call `.absolute()` before root inference and detection (`dash:1206`, `gate:961`). Symlink components stay visible to `_regular` (`v4:76-88`, test `T-adopt:206-235`). v3 file and directory spellings work from the parent cwd (`T-adopt:271-293`). Round 1's fix asked for nested-cwd cases; those still fail for v4 (CA-01 below). |
| CA-03 (counts on early-error returns, Minor) | **closed for association counters; residual Informational** | The `finally` block recomputes the four association counters from slot states on normal, exception and FAILED returns (`v4:3028-3041`). The returned dict is the same object, so the in-place update reaches callers. Binding and interval cases are tested in JSON and text (`T-adopt:296-358`). Round 1's second fix clause ("if a metric was not assessed, represent that explicitly") was not implemented for the physical counters (CA-02 below). |

## Focus answers

- **Refresh alias safety.** Symlinks at a file, a dangling target, the scripts directory or `.fv` are refused. Hardlinks are refused, and rename semantics would have protected them anyway. Each swap is atomic per file through a same-directory `rename(2)`. The swap is not atomic across the five-file set, and nothing calls `fsync` (CA-03). A pre-preflight/copy TOCTOU race stays inside the accepted no-concurrent-mutation premise.
- **cwd-relative `--records` without symlink resolution.** v3 matches the historical cwd semantics. v4 matches for spellings without `..`. `Path.cwd()` is the physical `getcwd`, so a symlinked logical cwd does not trip the symlink check. An absolute path through a symlinked ancestor above the project (macOS `/var`, `/tmp`) fails closed with "records path outside project root" (`v4:1958`), because `infer_repo_root` resolves the root (`gate:736`) while the candidate path is not resolved. That behavior already existed for absolute spellings, so it is not filed. The new tests avoid it with `Path(name).resolve()`.
- **Count finalization.** See CA-03 closure and CA-02.
- **Portable CA-04 skip** (`T-port:855-858`). It hides no consumer regression.
  - The only rule under test is `_barrier_applies`: barriers are FAIL or `kind=="indeterminate"` (`v4:1865-1868`), which is platform-independent Python.
  - On Linux, a cancellation the producer cannot signal is recorded as an `execution`/`ERROR` event (`run.ts:893-905`). That event takes the same consumer branch as `test_ca04_known_error_does_not_cut_off_earlier_actual_success` (`T-port:815-853`), which runs unskipped on Linux.
  - `test_ca04_genuine_failure_still_blocks_earlier_success` (`T-port:917-934`) is also unskipped.
  - The skipped test's unique assertions are closed spawn windows and terminated children (`T-port:879-893`). By the accepted limit, those cannot hold on Linux.
  - The skip predicate (`r38_evidence_v4_lifecycle.py:433-446`) matches the producer predicate (`native.ts:704-708`). A mismatch would show up as failures in `m4_v4_coverage.py:281-336` and `lifecycle:695-773`, which branch on the same predicate, so it would not be silent.
  - Side observation, out of slice [INFERENCE]: until a later recovery emits the `indeterminate` history event (`evidence-v4-store.ts:1205-1216`), the portable checker does not treat the refused live child as a barrier for an earlier PASS of the same key. The verdict then rests on endpoint recompute and the operator-cleanup premise in CR:119. No portable-checker test on Linux asserts this.

---

## Finding list (consolidated)

| ID | Lens | Severity | Surface | Intent ref | Code ref | Summary | Fix |
|---|---|---|---|---|---|---|---|
| CA-01 | clause-to-line | Minor | Dashboard/Gate B v4 CLI path | CR:122 "cwd-relative `--records`"; V4:9 v3 posture; round-1 CA-02 fix ("parent and nested working directories") | `dash:1206`, `gate:961` (`.absolute()` keeps `..`); `v4:1958-1959`, `v4:1978` → `_regular` → `schema:159-161` rejects `..` | Counterexample from cwd `P/docs`: `--records ../.fv/evidence/v4/current.json` becomes `P/docs/../.fv/...`. `infer_repo_root` resolves to `P`. `detect_v4` reads the file (the OS resolves `..`) and finds v4. `_read_entry` then computes `docs/../.fv/evidence/v4/current.json`, and `path()` raises "unsafe path", so the result is ERROR with exit 2. The same spelling against v3 records succeeds. From a sibling cwd, `../P/.fv/...` fails with the misleading "records p…
| CA-02 | field-name | Informational | Shared v4 counts | V4:569 separate physical counts; round-1 CA-03 fix second clause | `v4:2310-2312` initial zeros; `v4:2450-2459` raise before `v4:2517-2522`; `dash:1083-1088` | In the tested binding-mismatch case (`T-adopt:308-311`), the run has one `cache=miss` work entry with an execution reference, but JSON and text report `actual-dispatches=0 cache-hits=0 unique-physical-executions=0`. When `_load_run` or `_policy` fails, `logical_associations=0` as well. The verdict is ERROR, so no PASS is affected, but the counters claim measured zeros. | Set the unassessed physical and logical counters to `null`, or add an `assessed` flag, on exception paths. Assert it in `EarlyErrorCounts`. |
| CA-03 | who-controls | Informational | Script refresh | INSTALL.md:132-136 preservation; CR:122 | `init:101-107` sequential per-file `replace`; `init:503-506` discards `results` on FATAL; `init:53-61` no `fsync` | A mid-sequence `OSError` (ENOSPC, EACCES on file k) leaves helpers 1..k-1 new and k..5 old, and the operator gets only `FATAL: <error>` with no list of what was replaced. The order (`fv_project.py:33-39`) replaces `check_evidence_records.py` before its `fv_evidence_v4*` dependencies. [INFERENCE] With no `fsync` on the staged file or the directory, a power loss after `rename` can leave a zero-length helper on some filesystems. An empty Python gate exits 0, but `fv_doctor`'s byte-equality check would flag it. | Print `results` before the FATAL mess…
| CA-04 | who-controls (migration) | Informational | Ordinary `fv_init` (non-refresh) | V4:9 established posture; INSTALL.md:126 (non-force init preserves existing state) | `init:540` calls the same preflight with `force=args.force` | The alias preflight now also runs on a non-force ordinary init, where existing helpers would only be skipped and never written. A project whose `.fv/scripts/*.py` are symlinks to the FV checkout (equal bytes, so doctor passes) now aborts init with FATAL after the `init:531-538` subdirectory `mkdir` calls. This changes fail-closed behavior without documentation: the INSTALL.md refresh section (`INSTALL.md:124-136`) does not mention the new symlink and hardlink refusals. | Either scope the destination-alias checks to entries that…
| CA-05 | clause-to-line | Informational (pre-existing, not introduced by this fix) | Script refresh | INSTALL.md:135-136 "does not initialize missing project state" | `init:501-503`, `init:52` `mkdir(parents=True)`; `fv_project.py:88-91` | `--refresh-project-scripts` on any existing directory without `.fv` (for example, a mistyped parent) creates `.fv/scripts/` and five helpers there. | Require `project/.fv` to exist as a real directory in refresh mode before the preflight. |

## Summary

- Total findings: 5
- By severity: Critical=0 Major=0 Minor=1 Informational=4
- By lens: commitment-coverage=0 clause-to-line=2 deferred-cannot-silently-succeed=0 who-controls=2 field-name=1 deferral-justification=0
- Round-1 closure: CA-01 closed; CA-02 partially closed (CA-01 above); CA-03 closed for association counters, residual CA-02 above
- No finding lets a run reuse stale evidence or report a false PASS. The portable CA-04 skip hides no consumer regression.
- Recommended next step:
  1. Fix CA-01 (`..` handling plus nested/sibling-cwd tests for v3 and v4).
  2. Fix CA-02 (report unassessed counters as unassessed, not 0).
  3. Fix CA-03 (report partial refresh; add `fsync`).
  4. Decide CA-04 scope and update INSTALL.md.
  5. Fix CA-05.

  After the edits, the parent should rerun `tests/r38_evidence_v4_adoption_review.py`, `tests/m4_v4_coverage.py`, `tests/r29_omp_integration.py` and the v3 gate suites (`r6`, `r34`, `m1`).
- Not checked: I computed no diff against aa6946f and executed nothing. Refresh durability and the `..` counterexample were derived by reading code, not reproduced.
