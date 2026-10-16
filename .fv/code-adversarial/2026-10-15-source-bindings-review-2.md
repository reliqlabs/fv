# Code-adversarial review: FV v4 evidence producer, source bindings round 2 - 2026-10-15

- Operator: fv-code-adversary via OMP task (NOT openai-codex/gpt-6.1-sol task agents FixNativeOwnership-2, FixProducerStore-2, FixSourceBindings-2, FixAdoptionDashboard-2, FixBaseToolchain, FixRustToolchain, FixProofToolchain, and NOT the parent orchestrator)
- Code commit reviewed: `6c787c20f023a132856cf5119b137be25dd2303f` (parent `aa6946f`). The caller supplied both commit IDs. I ran no git command and read the files at their current worktree state.
- Intent version reviewed: `F/docs/execution-evidence-v4.md`. It has no frontmatter version, only the "Status: normative contract" line. I also read `F/.fv/changes/2026-10-14-execution-evidence-v4.md` § "Post-commit review dispositions (2026-10-15)".
- Ledger version reviewed: absent. `F/.fv/` contains only `code-adversarial/`, `attacks/` and `changes/`.
- Lens pack: crypto/enclave commitment lenses, plus path-safety, serialization-parity and evidence-freshness checks.
- Lenses applied: 1 through 6.

**Gate deviation.** `F/.fv/dispatch.json` is absent and so is `F/.fv/intent.md`. The strict gate would therefore return `STATUS: BLOCKED`. I continued because the caller explicitly named the normative contract inside PROJECT_ROOT. The parent may discard this report if the strict gate is required.

Path aliases: `F` = `/Users/mv/Development/reliq-fv-wt/evidence-perf`, `D` = `/Users/mv/Development/burnt/dossier-wt/evidence-perf`, `S` = `F/tools/evidence-v4/evidence-v4-source.ts`, `R` = `…/evidence-v4-run.ts`, `M` = `…/evidence-v4-model.ts`, `P` = `…/evidence-v4-policy.ts`, `TP` = `…/evidence-v4-toolchain-proof.ts`, `TC` = `…/evidence-v4-toolchain.ts`, `LM` = `…/evidence-v4-lake-metadata.lean`, `PY` = `F/scripts/fv_evidence_v4_schema.py`, `PC` = `F/scripts/fv_evidence_v4.py`, `FP` = `F/scripts/fv_project.py`, `T` = `F/tests/r38_evidence_v4_source_review.py`, `V4` = `F/docs/execution-evidence-v4.md`.

Method: static reads only. I ran no tests, builds or shell commands. Every counterexample below is a static deduction and carries the label `[INFERENCE]`. I accepted the parent's results without rerunning them: 150/150 Darwin tests, and 114 Linux tests with 7 skips. I did not re-raise the accepted limits as defects (Linux group-signal refusal; "Lake source coverage is Lean-specific"). Lens 6 checks only whether the implementation agrees with them.

Classes not covered: scheduler concurrency, crash atomicity, store durability and native lifecycle (outside this slice). Also not covered: arbitrary IO during `lakefile.lean` elaboration, custom Lake facets, and `include_str` or other data reads from Lean source. I treat that last group as the accepted Lean-specific limit. Supply-chain authenticity and producer authentication (TA-08) are also uncovered.

---

## Round-1 closure verdicts

| Round-1 | Verdict | Evidence |
|---|---|---|
| CA-01 record-set ordering | **closed** | The default selection is now sorted: `R:190-191` `records.sort(utf8Compare)`. `required_records` is sorted in plan at `R:415-418` and in manifest at `R:1314`. An explicit `records` value must already be a sorted set (`M:1236`). Policy order is still kept where the schema does not require a set: `physical_slots`/`work` keep expansion order, and `claims` is `unique`, not sorted (`M:1226`). Test `T` `test_b_before_a_plan_and_run_sort_sets_without_reordering_policy_work` exercises plan, run and portable assessment with no selector and with an explicit one. |
| CA-02 canonical dispatch target | **closed** (residual Informational divergence, CA-10) | `canonicalTargetPath` (`P:252-263`) resolves against the real root. It rejects a leading `~`, unsafe or escaping relatives, and a symlink in the final component. It then takes realpath and runs `safeSourcePath`. `loadPolicy` compares that result with `policy.intent_path` (`P:296-299`). This matches `FP:152-187` + `FP:124-131` for absolute, `./`, `..`, `//`, ancestor-alias and root-alias spellings (`T` dispatch test). Unsafe targets fail on both sides. |
| CA-03 NONEMPTY vs NUL-free strings | **closed** | Python `NONEMPTY` now checks only nonemptiness (`PY:797-798`). `TEXT` adds the NUL ban (`PY:795-796`). Every field matches TS. NONEMPTY/`nonempty`: `scope` (`PY:307,568`/`M:854,1163`), `rationale`, `pass_marker` (`PY:273,275`/`M:830,832`), `version_contains` (`PY:266`/`M:817`), PackageIdentity `name`, `version`, `id` (`PY:384-388`/`M:954-958`). TEXT/`osString`: locator values, platforms, EnvironmentIdentity and system_dependencies os/arch/release, SDK version, symlink `target`, `signal`, `process_start_id`, all argv/CMD entries (`PY:231-234,327,356-358,369,378,409-412,464,491,830-833`/`M:744-748,784-785,864,931-933,945,951,973-976,1014,1020,1047`). envmap values may be empty but not contain NUL on both side…
| CA-04 directory-prefix semantics | **closed** | `prefixSelects` (`S:37-39`) now matches `FP:265-277` exactly: `x/` selects descendants only, bare `x` selects itself or its subtree. A trailing-slash prefix whose endpoint is not a directory is rejected (`S:211`). Python requires a covered descendant (`PC:1384-1391`). The gitlink structural exemption (`S:148`) uses the same rule, and Python rejects the same gitlinks (`PC:1305-1313`). Test `T` `test_directory_prefix_requires_descendants…` compares five pairs and both capture outcomes. |

## Focus answers: `assertSourceRequirements` and `sourceRequirements` wiring

Wiring: `R:519-528` runs inside full preflight for **every** physical slot (selected or not) before cache candidate selection (`R:530-544`), in both plan and run. The requirement set per recipe is the union over `closure(recipe.toolchain)` adapters (`TC:1691-1701`). Each Lean adapter derives its set from its own declaration cwd. Lake applications with a different cwd or different options are refused (`TP:745-761`). The union is therefore over-strict, never narrower than one Lake project. Results by escape route:

| Escape route asked about | Result |
|---|---|
| Ignored or untracked `.lean` under a srcDir | Fail closed. The walk reads the disk (`S:259`), and ignored files never enter `closure.files` (`S:126-135`), so `require` throws. |
| Case | Directory case: fail closed. The walk descends every directory, and a git spelling that disagrees with the on-disk spelling fails `require`. Extension case: **CA-07**. |
| Non-`.lean` inputs Lake reads | lakefile, manifest, `lean-toolchain` and package-overrides are bound as tool configuration roots (`TP:614-616,767,872-874,888`). `input_file` is enforced as a required file. `input_dir` contents are **not** enforced (**CA-05**). |
| Symlink refusal scope | Only symlinks *inside* a walked directory are refused (`S:261`). A symlinked srcDir or input path, or a symlinked ancestor, is silently canonicalized (`TP:1014`) (**CA-06**). |
| `.` root | Walks the whole tree, including `.git`, `node_modules` and custom package dirs. This fails closed, but it costs availability (**CA-11**). |
| Union across recipes | No narrowing found. It is not applied at all when the lean adapter is absent from the recipe's toolchain closure (**CA-09**), or for standalone `lean` (**CA-08**). |

---

## Lens 1 - Commitment coverage

| Commitment | Attacker DoFs | Bound by | Gap |
|---|---|---|---|
| `Closure.hash` (`S:228-244`) | Prefix set, basis, file contents and paths in the closure | `D("source-closure",{mode,prefixes,basis,files})`; prefix rule now agrees with Python (`PC:1395-1427`) | No omission in the hash itself. Its completeness relies on preflight gates, and CA-05/06/07/08 let real Lake/Lean inputs sit outside it. |
| Lake source requirements | Lake-reported srcDirs and input targets | A preflight gate only. Not committed to any descriptor, key or retained record. | Not a commitment by design. As a result, a change in *where* Lake reads, with unchanged bytes and paths, is invisible to the key (CA-06). The portable checker cannot re-verify the gate. Informational: producer-trusted. |
| Canonical target binding | Dispatch spelling | `P:252-299` to `intent_path`/`intent_hash` | Closed (CA-02). Residual parity note in CA-10. |
| Execution key, inventory, snapshot | Unchanged from round 1 | `S:214-224`; `M` descriptor | No new omission. |

No signature or ReportData exists in this slice.

## Lens 2 - Clause-to-line discharge

| Clause | Expected discharge | Actual code line | Status |
|---|---|---|---|
| V4:42 set arrays sorted by UTF-8 | Sorted `required_records`/`selected_records` | `R:191,415-419,1313-1314` | discharged (CA-01) |
| V4:24 nonempty vs V4:26 NUL-free commands | Field-specific string domains agree across TS and Python | `PY:795-798`; `M:635-638,744-748` | discharged (CA-03) |
| V4:26 component-boundary prefix rule | Match the existing verified-input rule | `S:37-39,203-212`; `FP:265-277` | discharged (CA-04) |
| V4:122/dispatch-resolved canonical target | Repo-relative realpath equality with Python | `P:252-299`; `FP:152-187` | discharged, with Informational CA-10 |
| V4:26 "All traversed source … path components MUST be non-symlinks"; V4:157 "Symlinks … always reject reuse"; disposition "symlinks refused" | Refuse symlinks on the Lake-declared srcDir/input path | `TP:1014` canonicalizes through symlinks; `S:261` checks only walked entries | **gap**, CA-06 |
| V4:138 "ignored dependency files explicitly consumed by a tool must be declared … or included"; disposition "refuses any recipe whose source closure omits a required file" | Every Lake-declared input under closure | `LM:44-49` lists `input_dir`; `TP:1029` files it under `directories`; `S:264` requires only `*.lean` | **gap**, CA-05 |
| Same, `.lean` module files | All files Lean opens as modules | `S:264` case-sensitive `endsWith(".lean")` | **partial**, CA-07 |
| V4:159 recompute before command | Preflight gate before dispatch and cache lookup | `R:526` inside `preflightAll`, before `selectCandidates` `R:533` | discharged |
| V4:155 empty basis forces whole inputs | Mode fallback | `S:230-231`; `PC:1397` | discharged |
| Preflight `.` root walk | Bounded to Lake source | `S:257-267` walks all of `.` except `.lake` | partial (fail-closed), CA-11 |
| I11/I12 (consumer intent), ledger TA-* | Outside this slice | — | not re-audited |

## Lens 3 - Deferred cannot silently succeed

| Branch | Reachable from | Behavior | Status |
|---|---|---|---|
| Adapter returns no `sourceRequirements` (all non-Lean families) | `TC:1696` `adapters.get(id)?.sourceRequirements` | No requirement, gate passes | Accepted limit ("Lean-specific") for non-Lean families |
| Standalone Lean branch (`TP:718-743`) | lean-toolchain adapter with subject `lean` and no manifest | Returns no `sourceRequirements`. The argv `.lean` subject files are never required in the closure. | **gap**, CA-08: the Lean family itself skips the gate silently |
| `lean` applications under a Lake declaration (`TP:695-717`) | Recipe `lean X.lean` sharing the Lake adapter | Only executable/toolchain identity is compared. `X.lean` is not required. | **gap**, part of CA-08 |
| Missing required directory | `S:259` `readdir` | Throws ENOENT | fail-closed |
| Unknown or symlink entry in walk | `S:261` | Throws | fail-closed |

## Lens 4 - Who controls

| Field | Supplier | Validation | Gap |
|---|---|---|---|
| Whether the Lake gate applies to a recipe | Reviewed policy author, through `recipe.toolchain` and `requires` | None. `assertCommandBound` (`TC:1618-1645`) accepts `lake` from any declaration whose roots hash the executable. | **CA-09**. D wires `lake` → `requires:["lean-toolchain"]` (`D/.fv/execution-policy.json:281-314`), so D is unaffected. |
| `sourceRequirements.directories/files` | Installed Lake evaluating the project config (`LM:38-49`) | Must be a directory or file, inside the project, outside generated namespaces, or inside a hashed tool root (`TP:1014-1029`) | Symlinks are resolved, not refused (CA-06). `input_dir` is merged with srcDirs (CA-05). |
| `closure.files` | Git inventory + mandatory bindings | `S:126-170` | No new gap |
| `target_spec` | Repo `.fv/dispatch.json` | `P:285-299` | CA-10 (Informational) |
| `call.records` | Caller | `set(id,…,1)` `M:1236`; membership `R:192` | No gap |

## Lens 5 - Field-name fidelity

| Field | Implied semantic | Actual value | Status |
|---|---|---|---|
| `sourceRequirements.directories` (`TC:57`, `TP:1008,1029`) | "Lake source directories: their `*.lean` must be bound" (`S:247` comment) | Lake srcDirs **plus** `input_dir` target paths | Mismatch. Recorded under CA-05, not counted twice. |
| Error text "tool source input outside recipe closure" | Any Lake-consumed input | Only `*.lean` and input_file | Follows CA-05 |
| `selected_records`, `required_records` | Sorted ID sets | Sorted (`R:191,418,1314`) | faithful |
| `common.intent_path` | Dispatch-resolved repo-relative target | `P:252-263` realpath-relative | faithful |

## Lens 6 - Deferral justification audit

| Deferred finding | Justification claims | Claim audit | Verdict |
|---|---|---|---|
| Accepted limit: "Lake source coverage is Lean-specific" | (a) Only the Lean family reports requirements | True: only `identifyLean` populates `sourceRequirements` (`TP:1083`). Every other adapter leaves it undefined (`TC:1696`). | valid |
| | (b) Read as "only `*.lean` files are covered" | Contradicted by the code's own scope. It enumerates `input_file`/`input_dir` as requirements (`LM:44-49`; `TP:1012`) and enforces input_file, but `input_dir` falls to the `.lean` filter. | Inconsistent; see CA-05. The parent must either state that input_dir content is accepted, or enforce/refuse it. |
| | (c) Lean family fully gated | Standalone Lean and `lean` applications are not gated (`TP:718-743`) | Claim does not hold; CA-08 |
| Disposition "symlinks refused" (proof CA-04 fix text) | Symlinks refused for required sources | Refused only inside walked trees (`S:261`). A srcDir/input-path symlink is canonicalized (`TP:1014`). Test `test_symlink_srcdir_outside…` shows only *outside* targets are refused. | Claim is partially false; CA-06 |
| Accepted limit: Linux/other runtimes refuse group signaling | — | Outside this slice | not audited |

---

## Finding list (consolidated)

| ID | Lens | Severity | Surface | Intent ref | Code ref | Summary | Fix |
|---|---|---|---|---|---|---|---|
| CA-05 | clause-to-line | Major | Lake `input_dir` coverage | V4:138,155,157; disposition "omits a required file" | `LM:44-49`; `TP:1012-1029`; `S:256-267` | `input_dir` paths are added to `directories`, and the walk requires only `*.lean` beneath them. Non-Lean files that Lake tracks as declared inputs can sit outside the closure. `[INFERENCE]` Counterexample: `input_dir vectors where path := "vectors"` with `lean_lib Proofs where needs := #[vectors]`. The recipe's prefixes cover `Proofs/` but not `vectors/`. Commit an edit to `vectors/case.json`. Inventory paths, closure hash, lakefile bytes and the Lake metadata probe output are all unchanged, so the execution key matches and the old PASS is reused. | Return `input_dir` separately and require every regul…
| CA-06 | clause-to-line | Major | Symlinked srcDir/input path | V4:26,157; disposition "symlinks refused" | `TP:1014,1028-1029`; `S:259-261` | `canonicalToolPath` resolves a project-internal symlinked srcDir/input path (or symlinked ancestor) to its target and records only the target. Nothing refuses the symlink. `[INFERENCE]` Counterexample: `srcDir = "src"`, with `proofs/lean/src -> impl-v1` gitignored or excluded by `.fv/verified-inputs.txt`. `impl-v1/` and `impl-v2/` are committed, and the prefix is `proofs/lean/`. Run 1 passes. Then `ln -sfn impl-v2 src`. Requirements move to `impl-v2` (still bound). Closure hash, inventory, lakefile and probe stdout (`…/src`) are unchanged, so the key matches and Lake's new source tree reuses the impl-v1 PASS. | In `i…
| CA-07 | clause-to-line | Minor | `.lean` suffix case | V4:138,157 | `S:264` | The suffix check is case-sensitive. `[INFERENCE]` On a case-insensitive APFS volume, `import Proofs.Lemma` opens `Proofs/Lemma.LEAN`, which the walk does not require. A narrow prefix closure that omits it reuses stale work after an edit. Lake's own globbing ignores the name, so this needs an unusual file name. | Compare the extension case-insensitively, or refuse case-variant `.lean` names inside required directories. |
| CA-08 | deferred-cannot-silently-succeed | Minor | Standalone Lean and `lean` applications | V4:155,159; Lens 6 (c) | `TP:718-743` (no `sourceRequirements`); `TP:695-717`; `TC:1696` | Lean argv subject files are never required in the closure. `[INFERENCE]` A recipe `lean Check.lean` (standalone, or sharing a Lake declaration) with a prefix closure that omits `Check.lean` reuses its PASS after `Check.lean` changes. D has no such recipe (`D/.fv/execution-policy.json:2123-2127` is `lake build` only). | Report the argv `.lean` inputs (canonical, symlink-refused) as `sourceRequirements.files` in both branches. |
| CA-09 | who-controls | Minor | Gate depends on the policy | V4:138; the user's fail-closed policy | `TC:1618-1645,1691-1701`; `R:525-526` | The Lake gate runs only when a lean-toolchain adapter is in `closure(recipe.toolchain)`. `[INFERENCE]` A recipe `lake build` bound to `{kind:"tree",locator:{mode:"path",value:"/opt/lean/…"}}` with no `requires` passes `assertCommandBound` and receives empty requirements. No refusal was found in policy or toolchain code. | Refuse recipes and checks whose resolved executable is Lean/Lake (`lake`/`lean` basename, or inside a Lean distribution) unless the closure contains a lean-toolchain adapter. |
| CA-10 | clause-to-line | Informational | Target-spec parity | V4:122 | `P:292` (`trim()`); `FP:116-121` (`strip()`); `P:262` vs `FP:180` | JS `trim` and Python `strip` use different whitespace sets. `"\uFEFF"`: TS uses the default `.fv/intent.md`, while Python raises, so the portable `_policy` (`PC:1225-1229`) fails. `"\x85"`/`"\x1c"`: Python uses the default, TS rejects. `[INFERENCE]` Darwin `realpath` case-canonicalizes, while Python's `resolve()` keeps the given case, so `.FV/INTENT.MD` binds on TS but fails the Python equality. Every divergence fails closed on one side. | Use one explicit whitespace rule (e.g. ASCII `[ \t\r\n]`) in both, and compare case-canonical paths, or reject non-canonical case. |
| CA-11 | clause-to-line | Informational | `.` root walk scope | V4:138 | `S:257-267`; `TP:997-1006` (excluded generated paths are not passed through) | With Lake's default `srcDir = "."` at the repo root, the walk enters `.git`, `node_modules` and custom packagesDirs. Any symlink there (pnpm stores, symlinked git hooks) or any vendored ignored `.lean` refuses the recipe. This fails closed and affects availability only. D's srcDir is `proofs/lean` and is unaffected. | Pass the toolchain's `excludedPaths` (`.git`, packagesDirectory, build dirs) to the walk, or refuse root-level srcDirs explicitly. |

## Summary

- Total findings: 7 new. All four round-1 findings are closed.
- By severity: Critical=0 Major=2 Minor=3 Informational=2
- By lens: commitment-coverage=0 clause-to-line=5 deferred-cannot-silently-succeed=1 who-controls=1 field-name=0 (the CA-05 mismatch is not counted twice) deferral-justification=0 (the Lens 6 contradictions are counted under CA-05, CA-06 and CA-08)
- Current Dossier impact: none of CA-05 through CA-11 is triggered by D's single Lake recipe EX-016 (`lake build` in `proofs/lean`, prefix `proofs/lean/`, lakefile without input_dir, adapter wired through `requires`). The two Major findings are generic stale-reuse paths. The user's policy says to fix those.
- Recommended next step, in order:
  1. CA-06: refuse symlinked Lake srcDir/input paths.
  2. CA-05: enforce or refuse `input_dir`.
  3. CA-08: gate standalone and application `lean` argv sources.
  4. CA-09: require the lean-toolchain adapter for Lean/Lake commands.
  5. CA-07: case-insensitive `.lean` suffix.
  6. CA-11 and CA-10 as parity and availability cleanup.
  7. Add one regression test per fix, then have the parent run the r38 source, proof and schema suites once.

I did not run any test or git diff. The Lake input_dir/`needs` tracking, the APFS case resolution and the Darwin realpath case behavior are unexecuted inferences. The intent-gate deviation above is the main process risk.
