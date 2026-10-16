# Code-adversarial review: FV v4 evidence producer, adoption/dashboard round 3 - 2026-10-15

- Operator: fv-code-adversary via OMP task (NOT openai-codex/gpt-6.1-sol task agents R2FixBase, R2FixRust, R2FixProof, R2FixStore, R2FixNative, R2FixAdoption, or the parent orchestrator)
- Code commit reviewed: 34a7240 (parent 6c787c2, the round-2 target). The caller supplied the commit. I had no shell, so I computed no diff, and every citation points at the current worktree.
- Intent version reviewed: `docs/execution-evidence-v4.md` has no frontmatter version. I also used `.fv/changes/2026-10-14-execution-evidence-v4.md` §"Round-2 review dispositions (2026-10-15)", lines 129-141.
- Ledger version reviewed: absent. `F/.fv/ledger.md` does not exist.
- Lens pack: crypto/enclave, plus migration/preservation, path-discovery compatibility and reporting-truthfulness lenses, as in rounds 1 and 2
- Lenses applied: 1 through 6

## Intent resolution and scope

`F/.fv/dispatch.json` is absent. The gate's literal canonical target, `F/.fv/intent.md`, is also absent (glob: "Path not found"). Rounds 1 and 2 had the same problem. Strictly, the gate requires BLOCKED here. I proceeded on the intent targets the caller named explicitly: V4 and the change record (CR). That is a caller-supplied target, not a fallback search, and the invoking skill should record the deviation.

Aliases used below:
- `F` = PROJECT_ROOT
- `init` = `F/scripts/fv_init.py`
- `dash` = `F/scripts/coverage_dashboard.py`
- `gate` = `F/scripts/check_evidence_records.py`
- `v4` = `F/scripts/fv_evidence_v4.py`
- `T` = `F/tests/r38_evidence_v4_adoption_review.py`
- `D` = `/Users/mv/Development/burnt/dossier-wt/evidence-perf`

I ran nothing. The parent's 216/216 Darwin result and the real Dossier captures are accepted as reported.

Convergence bar for this round: a defect is raised only if it can make a real run reuse stale evidence, claim PASS falsely, hang, or lose data. A spelling that is already refused is not a finding. A spurious refusal of Dossier's actual setup is a finding.

Uncovered classes: concurrency and locking, real crash and power-loss behavior, resource exhaustion, and supply-chain authenticity of the FV checkout. `DerivedNativeToolIdentity` (`T:530-781`, `v4:285-370`) sits in this test file but belongs to the base-toolchain slice. I read its tests but did not audit `_tool` or the TS `derivedNativeTree`.

---

## Lens 1 - Commitment coverage

| Commitment | Attacker DoFs | Bound by | Gap |
|---|---|---|---|
| Installed helper set (`fv_project.py:33-39`) | Destination alias, staged bytes, durability, partially replaced set | Whole-set preflight before any write (`init:84-111`). Untouched helpers are skipped only when not forced (`init:96-97`). Each file is staged in the same directory, file-fsynced (`init:62-63`), swapped with `replace` (`init:64`), then the parent and grandparent directories are fsynced (`init:66-71`). | None. The set is still replaced file by file, but a failure part-way now lists what was replaced before the FATAL line (`init:519-523`, test `T:219-281`). |
| Records path to file read | `--records` spelling, `..`, symlinks, cwd | `.absolute()` with the physical cwd (`dash:1209`, `gate:961`). Lexical `normpath` then containment (`v4:2033-2034`). Every component of the normalized relative path goes through `_regular` (`v4:76-89`). | None. Lexical `normpath` drops a `link/..` pair, so a spelling that crosses a symlink and then `..` names, physically, a different file from the one read. The file actually read is still a symlink-free, contained regular file, and recompute-mode freshness applies to it. No stale reuse or false PASS path follows. Not filed. |
| Dashboard and gate counts | Counter values on error returns | `_report` initializes the physical and logical counters to `None` (`v4:2384-2388`). They are assigned only after assessment (`v4:2523-2525`, `v4:2593-2599`, `v4:3030`). The association counters are recounted in `finally`. | None |

The delta adds no hash, signature or ReportData construction.

## Lens 2 - Clause-to-line discharge

| Clause | Expected discharge | Actual code line | Status |
|---|---|---|---|
| CR:134 "`..` record paths are normalized lexically" plus round-2 CA-01 (nested and sibling cwd) | Nested- and sibling-cwd `..` spellings work for v4, as they do for v3, and symlink checks are kept | `v4:2033`. Unit cases: `T:317-340`. CLI cases for dashboard and gate, from nested and sibling cwds, for a file and a directory, with a symlink alias refused: `T:391-434`. v3 cases: `T:436+`. | discharged |
| CR:134 "unassessed counters are null"; V4:575 separate logical and physical counts | Counts that were not assessed are not shown as measured zeros, in JSON or in text | `v4:2384-2388`. Text renders `None` as `not-assessed` (`dash:1082-1091`). Tests: `T:817-834` (post-expansion: physical counters `None`, text at `T:851-855`) and `T:857-881` (pre-expansion: all four `None`). | discharged |
| CR:134 "staged helpers are fsynced" | Staged file is fsynced before rename, directories after; partial replacement is reported | `init:62-71`, `init:519-523`, `init:558-562`. Tests: `T:177-217` (event order), `T:219-281` (copy failure and directory-sync failure both list replaced helpers before FATAL). | discharged |
| CR:134 "alias checks are skipped for untouched helpers" | Non-force init does not refuse existing linked helpers it would not write | `init:96-97`. Test: `T:283-313` (symlink and hardlink helpers are skipped and inodes kept). | discharged for helper files. The directory checks at `init:84-94` still refuse a symlinked `.fv` or `.fv/scripts` on non-force init with nothing to write. That fails closed. I found no evidence that this is Dossier's arrangement (`D/.fv/scripts/` lists as a directory holding regular helpers [INFERENCE: lstat not observed]). Not filed. |
| CR:134 "CA-05 refused: refresh requires existing `.fv` state"; INSTALL.md:134-135 | Refresh does not create project state | `init:514-517` runs before the preflight. Test: `T:167-175` (project directory stays empty). | discharged |
| V4:9 / V4:13 exact-schema dispatch, fail closed | v4 never downgrades to v3; unknown or mixed schemas are errors | `gate:967-980` (V4Error → ERROR). `gate:981-983` routes OSError to the legacy loader. A v4 run object lacks the legacy fields and is reported as `missing field` (`gate:618-621`), so the claim is not PASS. `dash:1212-1217` returns ERROR. | discharged |
| V4:575 "MUST report `binding:"not-recomputed"` and MUST NOT present a stored PASS as fresh" | Dashboard assessment is stored-only | `dash:924-933` passes `recompute=False`; the binding check is at `dash:934-935`. `pass_semantics` is set at `dash:989-992`. | discharged |

## Lens 3 - Deferred cannot silently succeed

| Branch | Reachable from | Behavior | Status |
|---|---|---|---|
| Refresh without `.fv` | `init:514-517` | FATAL, exit 1, nothing written | Explicit non-success |
| Refresh mid-sequence `OSError` (copy, file fsync, replace, directory fsync) | `init:43-73` → `init:519-523` | Lists replaced helpers, then FATAL, exit 1. The staged temp file is unlinked in `finally` (`init:72-73`). | Explicit non-success |
| `detect_v4` reads the physical path while its `_read_entry` reads the lexical path | `v4:2096-2132` | If the lexical file is missing, `_read_entry` raises OSError. The gate then takes the legacy path (`gate:981-983`), the v4 object fails legacy validation, and the result is not PASS. The dashboard returns ERROR. If the lexical file exists but is not v4, `_load_run` fails and the result is ERROR. | No silent success |
| `assess_v4` exception path | `v4:3086-3100` | FAILED or ERROR. Counters are either assessed or `None`. | Explicit non-success |
| Production TODO/stub search over the four scripts | none | none found | Empty |

## Lens 4 - Who controls

| Field | Supplier | Validation | Gap |
|---|---|---|---|
| `.fv` and `.fv/scripts` directory objects | Project filesystem | `.fv` must exist in refresh mode (`init:514`). `lstat` rejects symlinks and non-directories (`init:84-94`). | None |
| Destination helper inodes | Project filesystem | Checked only when they will be written (`init:96-111`). `replace` swaps the directory entry. | None |
| `--records` | CLI operator | `.absolute()`, then `normpath`, containment, per-component `_regular` (`v4:2029-2052`) | None at the convergence bar. An absolute spelling through a symlinked ancestor of the project (for example `/tmp`) still fails closed with "outside project root" (`v4:2034` against the resolved root at `gate:739`). This is pre-existing, and round 2 did not file it. Dossier sits under `/Users/mv/Development/...`, and relative spellings use the physical `getcwd`, so no refusal of Dossier's setup was found [INFERENCE: symlink status of Dossier's ancestors not observed]. |
| `--root` (gate) | CLI operator | `.resolve()` (`gate:965`) | None new |

## Lens 5 - Field-name fidelity

| Field | Implied semantic | Actual value | Status |
|---|---|---|---|
| `logical_associations`, `unique_physical_executions`, `actual_dispatches`, `cache_hits` | Measured counts, or absent when not measured | `None` until assigned (`v4:2384-2388`). Rendered as `not-assessed` in text (`dash:1082-1085`). | Faithful |
| `missing/failed/error/cancelled_associations` | Slot-state counts | Recounted from `per_claim` in `finally` | Faithful. On a pre-expansion error they read 0 next to `logical_associations=null`; that is consistent, since there are zero rows. |
| `records` | Records path the operator named | `str(records_path)`, the absolute spelling (`v4:2366`, `dash:989`) | Faithful to the spelling. The normalized relative path that was actually read is not reported. That only matters for the contrived symlink-then-`..` spelling in Lens 1. Not filed. |
| `repo_root` | Physical project root | `str(reader.root)` | Faithful |

## Lens 6 - Deferral justification audit

| Deferred finding | Justification claims | Claim audit | Verdict |
|---|---|---|---|
| Round-2 CA-05 "refused: refresh requires existing `.fv` state" | (1) Refresh refuses when `.fv` is absent. (2) Nothing is created. | (1) `init:514-517`. (2) The refusal runs before `install_project_scripts`, and `T:167-175` asserts the project directory stays empty. | Holds |
| CR:134 "Source CA-10 is an accepted limit" | User-accepted limit | Not re-raised by policy | Not audited |
| CR:127 Linux/other runtimes leave work indeterminate | Audited in round 2 | Not in this delta | Not re-audited |
| Round-2 Lens 3 [INFERENCE] that the legacy loader cannot PASS a v4 shape | A v4 object has no legacy record fields | `gate:618-621` reports `missing field` for every absent field, so the record is invalid and the claim is not PASS | Holds; the inference is now confirmed from code |

---

## Round-2 closure

| Round-2 finding | Verdict | Evidence |
|---|---|---|
| CA-01 (Minor, `..` spellings ERROR for v4) | **closed** | `v4:2033` normalizes before containment (`v4:2034`) and before `_regular` (`v4:2052`). The original counterexample (`../.fv/evidence/v4/current.json` from cwd `P/docs`) and the sibling-cwd spelling are covered for both CLIs and for file and directory records (`T:391-434`). A symlink component that survives normalization is still refused (`T:337-338`, `T:422-433`). |
| CA-02 (Informational, measured zeros for unassessed counters) | **closed** | `v4:2384-2388` initializes the four counters to `None`. They are assigned only on the assessed path. The text renderer shows `not-assessed` (`dash:1082-1085`). JSON and text are asserted at `T:817-855` and `T:857-881`. |
| CA-03 (Informational, partial refresh unreported, no fsync) | **closed** | File fsync before `replace` and directory fsync after it (`init:62-71`, order asserted at `T:177-217`). Replaced helpers are printed before FATAL in both refresh and ordinary init (`init:519-523`, `init:558-562`). The copy-failure and directory-sync-failure cases are asserted at `T:219-281`. The set is still non-atomic across files, but it is now reported and fails closed. |
| CA-04 (Informational, non-force init refuses untouched linked helpers) | **closed for helpers** | `init:96-97` skips the alias checks for destinations that will not be written. Asserted at `T:283-313`. Residual, not filed: the directory-level symlink refusal stays unconditional (`init:84-94`). INSTALL.md:124-136 still does not list the refusals. |
| CA-05 (Informational, refresh creates `.fv` state) | **closed (refused)** | `init:514-517`; `T:167-175` |

---

## Finding list (consolidated)

| ID | Lens | Severity | Surface | Intent ref | Code ref | Summary | Fix |
|---|---|---|---|---|---|---|---|

No defect in this slice met the convergence bar: stale-evidence reuse, false PASS, hang, data loss, or spurious refusal of Dossier's actual setup. These residuals are recorded above as non-findings so the parent can decide whether they matter:

- Lexical `..` normalization can diverge from the physical path. That needs a symlink-then-`..` spelling, and the file read is still fully validated (Lens 1, Lens 5).
- A symlinked `.fv` or `.fv/scripts` is still refused on non-force init (Lens 2).
- An absolute `--records` through a symlinked ancestor of the project is refused. This is pre-existing (Lens 4).
- INSTALL.md does not document the refresh refusals.

## Summary

- Total findings: 0
- By severity: Critical=0 Major=0 Minor=0 Informational=0
- By lens: commitment-coverage=0 clause-to-line=0 deferred-cannot-silently-succeed=0 who-controls=0 field-name=0 deferral-justification=0
- Round-2 closure: CA-01, CA-02, CA-03 and CA-05 closed; CA-04 closed for helpers, with the directory-level residual left unfiled.
- Recommended next step:
  1. No code patch is required in this slice at the convergence bar.
  2. Optional: document the refresh symlink and hardlink refusals in INSTALL.md:124-136.
  3. The parent should run `tests/r38_evidence_v4_adoption_review.py`, `tests/m4_v4_coverage.py` and the v3 gate suites (`r6`, `r34`, `m1`) on 34a7240, if they are not already part of the reported 216/216.

This report does not certify the slice as correct. An empty finding list means only that the inspected surface produced nothing at this bar.

Not checked: I computed no diff against 6c787c2 and ran nothing. I did not observe the symlink status of Dossier's ancestors or of `.fv/scripts` (the [INFERENCE] rows). `_tool` and `derivedNativeTree` were outside this slice.
Risk: helpers are still replaced one file at a time. A failure part-way leaves a mixed set, which is now reported but not rolled back.
