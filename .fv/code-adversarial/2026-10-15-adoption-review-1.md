# Code-adversarial review: Dossier / FV v4 installer and dashboard adoption - 2026-10-15

- Operator: fv-code-adversary via OMP task (NOT V4InstallerAdoption, V4DashboardAdoption)
- Code commit reviewed: `aa6946f29f6bc893cba62d58ef99efdc6d5a8716`; Dossier consumer commit `1fc3294437c294b040bc606aaa177334b8e41b8c`
- Intent version reviewed: no frontmatter version; dispatch-resolved `docs/intent.md`, including the 2026-10-14 I11/I12 revision
- Ledger version reviewed: no frontmatter timestamp; body declares Updated `2026-10-08`
- Lens pack: crypto/enclave, supplemented with migration, compatibility and reporting-truthfulness lenses
- Lenses applied: 1 through 6, followed by supplemental lenses 7 through 9

## Scope and evidence limits

Path aliases:

- `D` = `/Users/mv/Development/burnt/dossier-wt/evidence-perf`
- `F` = `/Users/mv/Development/reliq-fv-wt/evidence-perf`
- `Intent` = `D/docs/intent.md`
- `Ledger` = `D/.fv/ledger.md`
- `V4` = `F/docs/execution-evidence-v4.md`
- `init`, `project`, `doctor`, `dashboard`, `consumer`, `gate` = the corresponding `F/scripts/fv_init.py`, `fv_project.py`, `fv_doctor.py`, `coverage_dashboard.py`, `fv_evidence_v4.py`, `check_evidence_records.py`

`D/.fv/dispatch.json` explicitly selects `docs/intent.md`. No separate FV intent was invented. The dependency contract is V4, with caller-supplied SHA-256 `825a053c2d3ba511a5f32f03168239fa24d5221195cb238865a9a1dc2ba7c0e2`. Commit attribution and that digest were supplied by the caller; this reviewer did not independently calculate them.

The primary review covers the four assigned scripts and `F/templates/evidence-run-v4.example.json`. Supporting inspection followed their calls into the shared portable validator, Gate B root discovery, the public factory's schema dispatch, installer documentation and relevant tests. Native supervision, scheduling, crash recovery and tool-discovery implementations were not independently audited in this slice.

No commands, tests, builds, gates, formatters, live operations or file writes were performed. The parent-reported Linux/Darwin regression results, CI gates, public-factory acceptance and actual stored-only dashboard smoke are accepted as scoped observations without rerunning them. In particular, the smoke's `binding=not-recomputed` and `COVERED` output is consistent with the inspected implementation. It is not fresh canonical Dossier evidence.

The review preserves the approved-command lifecycle premise, no-concurrent-external-mutation premise, upstream build/cache integrity, trusted complete retained history and operator/OS/compiler trust. Hashes do not authenticate execution or prove history nondeletion. Endpoint agreement does not detect arbitrary ABA changes. Neither this review nor the reported tests establish production activation, refinement or served-route independence. This is independent-agent review within one model family, not multi-family attestation.

Important uncovered classes include native concurrency and resource locking, process escape containment, durability under actual crashes, resource exhaustion, compiler/supply-chain authenticity and protocol authorization/arithmetic/reentrancy. Migration inspection here concerns validator installation and evidence compatibility, not Dossier contract storage migration.

---

## Lens 1 - Commitment coverage

| Commitment | Attacker DoFs | Bound by | Gap |
|---|---|---|---|
| Installed validator identity | Installed helper bytes, missing files, substituted copy | `doctor:74-75,433-453` compares each installed file with its canonical counterpart; `project:33-39` supplies the shared five-file inventory | Byte equality is checked. It is not source authentication or safe-write containment; CA-01 concerns the installer write boundary. |
| Canonical target and verified-input snapshot | Dispatch target, include/exclude entries, selected file bytes and path order | `project:98-186,355-433,467-567`; v4 policy additionally requires the dispatch-resolved target at `consumer:1221-1227` | Existing snapshot construction remains distinct from v4's stronger source validation. No new commitment omission identified in the inspected project helper. |
| Run, claim and artifact references | Pointer target, run ID, supplied claim contents, raw bytes, reference path/hash/size | `consumer:75-145,1954-1976,2059-2137,2614-2668` validates contained regular files, immutable owner paths, exact references and canonical claim identity | Dashboard delegates to these checks rather than projecting v4 into legacy bindings. |
| Execution descriptor and sharing membership | Recipe, members, distinct association, class, common bindings and recorded tool/environment identity | `consumer:1433-1478`, reached from assessment at `consumer:2739-2763` | Stored-only mode checks recorded structure and common bindings. Current source closure/package checks conditional on a current scan are not performed and are not advertised as performed. |
| Observation and retained-history commitments | Member outcome, request/reference substitution, later failure and cross-key history | `consumer:1481-1649,1761-1847,1865-1951,2780-2844,2914-2952` | Shared semantic validation remains the source of dashboard outcomes. History completeness remains an explicit assumption. |
| Public dashboard report | Counts, status, class, binding and coverage qualification | `dashboard:820-881,942-970`; qualified verdict originates at `consumer:3009-3021` | Reports are not cryptographic commitments. Counter truthfulness has CA-03. |

No additional signature or enclave ReportData construction occurs in this installer/dashboard slice.

## Lens 2 - Clause-to-line discharge

| Clause | Expected discharge | Actual code line | Status |
|---|---|---|---|
| Intent I11: prior evidence cannot be rewritten or rebound | Refresh changes only installed scripts; retained records and reviews stay untouched | `init:39-64,412-424`; preservation promise at `F/INSTALL.md:132-139` | partial: nominal write set is correct, but existing filesystem aliases escape it, CA-01 |
| Intent I11: dependency-scoped reuse and declared operational trust | A descriptive dashboard cannot claim local cache eligibility or current source verification | `dashboard:823-827,867-871`; `consumer:2355-2377,3009-3021` | discharged for display boundary; actual cache reuse is outside this slice |
| Intent I12: preserve v3 behavior/default and separate opt-in v4 | Versioned factory branch; no generated v4 policy or automatic evidence conversion | `F/tools/evidence-run.ts:587-648`; `init:428-464`; template lines 1-5 | partial: factory/default separation is present; dashboard CLI path compatibility regresses, CA-02 |
| Intent I12 / V4 S1: complete logical assessment after selection or failure | Expand canonical requirements and policy slots independently of selected evidence | `consumer:2380-2449,2461-2489`; `dashboard:828-865` | discharged for inspected expansion; error-path counters contradict retained rows, CA-03 |
| Intent I12 / V4 S2: sharing cannot inflate actual invocations | Preserve each association and distinguish unique referenced artifacts, dispatches and cache hits | `consumer:2517-2523,2605-2611,2954`; `dashboard:945-956` | discharged on completed assessment paths; early-error accounting is partial, CA-03 |
| Intent I12 / V4 B1: own observations and class/tool/dependency coverage | Use the portable validator's member outcomes and compatibility checks | `consumer:1193-1219,2703-2724,2780-2879,2955-2969`; `dashboard:823-865` | discharged at the inspected consumer/display seam; stored-only mode does not independently rerun observations |
| Intent I12 / V4 B2: later genuine failures block earlier success | Evaluate complete retained barriers by canonical claim/tool identity | `consumer:1865-1951,2578-2582,2680-2702,2914-2952` | discharged for inspected routing; trusted-store completeness remains assumed |
| Intent I12: FAIL precedence | Required validated failure outranks missing work and operational errors | `consumer:2970-3008,3024-3036`; `dashboard:872-880` | discharged for the inspected validated-failure paths; no weaker dashboard verdict introduced |
| V4 T1: dispatch stopping and durable ordering | Producer halts new work and accounts for in-flight work | Dashboard reads retained outcomes through `consumer:2479-2523`; it dispatches no recipes | partial: producer enforcement is outside this slice |
| V4 T2: ownership recovery and endpoint limitations | No stolen ownership or implied continuous immutability | Stored receipt validation is reached through `_execution`; provenance at `consumer:2364-2377` | partial: native recovery is outside this slice; assumptions are disclosed |
| V4 exact-schema dispatch | Reject unknown/mixed v4 envelopes before legacy unwrapping | `consumer:1979-2056,2059-2137`; `dashboard:1044-1061` | discharged for inspected v4 discriminators and mixed-envelope paths; path preparation has CA-02 |
| V4 dashboard reporting, lines 560-567 | Stored-only binding, no freshness/reuse claim, complete defects and separate work counts | `dashboard:823-827,849-871,942-970`; `consumer:2355-2377,3009-3021` | partial: correct qualification and defect retention; CA-03 affects error-path counts |
| Intent I13: scoped evidence is not activation | Preserve full canonical assessment and explicitly qualified selection | `consumer:2380-2410,3015-3021` | discharged for report scope; external activation prerequisites remain unproved |
| Intent I14: preserve authority/runtime restrictions | Installer and display do not activate mobile/runtime or perform live operations | Script-refresh early return at `init:412-424`; stored assessment flags at `dashboard:823-825` | discharged within assigned paths |
| Ledger C-01 through C-15 | Do not convert bounded/local evidence into a proved system conjunction | `consumer:2390-2410,2955-3021`; Ledger introduction and candidate trust boundaries | partial by design: all fifteen candidate conjunctions remain outside this slice's discharge claim |
| Ledger TA-08 | Do not claim unsigned local evidence authenticates the operator | `consumer:2295-2307,2364-2377`; `doctor:433-453` establishes only copy equality | assumption retained, not cryptographically discharged |
| Ledger TA-01 through TA-07 and TA-09 through TA-17 | Preserve platform, cryptographic, custody, deployment, consensus and release assumptions | No enforcing implementation in these assigned scripts | outside slice; not discharged by installation, planning or coverage output |
| Other canonical protocol clauses: I1-I10, RS1-RS6, A1-A5/B/C1-C5/D1-D4, PV1-PV5, G1/G2, private-v2 transitions, S1-S7, B1-B19/B2t/Q-B19, PS1-PS7, PB1-PB12 and NG-1 through NG-21 | Protocol implementation and qualification, not evidence-dashboard substitution | Dossier protocol/runtime code is not assigned here | outside slice; no protocol correctness or activation conclusion |

## Lens 3 - Deferred cannot silently succeed

| Branch | Reachable from | Behavior | Status |
|---|---|---|---|
| Stored-only assessment | `build_v4_dashboard` | Explicitly disables source recomputation and observation execution, retains `coverage_only`, `reusable:false`, retained-receipt provenance and qualified `COVERED` (`dashboard:823-825`; `consumer:2355-2377,3009-3021`) | Intent-authorized descriptive mode, not deferred verification success |
| Invalid/missing v4 evidence | Schema discovery and assessment | Error handling returns nonzero and names defects (`dashboard:1045-1060`; `consumer:3024-3036`) | Explicit non-success; CA-03 concerns its counts |
| Doctor's Zod stub | Package factory-load diagnostic | Checks import/factory shape and reports `factories load`; it does not execute an evidence call (`doctor:125-137`) | Diagnostic limitation. It cannot establish compatibility with the actual host schema; the parent's separate real-factory exercise is distinct evidence. |
| Missing refresh prerequisites | `--refresh-project-scripts` | Missing canonical files or invalid project root return failure (`init:403-418`) | Explicit non-success |
| Production TODO/stub/deferred implementation | Targeted search of all four primary scripts | No production branch deferring evidence work while returning an evidence PASS was identified | Empty finding set for this lens |

## Lens 4 - Who controls

| Field | Supplier | Validation | Gap |
|---|---|---|---|
| Refresh project root | CLI operator | Existing-directory resolution (`project:90-95`; `init:412-418`) | Root normalization alone does not validate destination components. |
| `.fv/scripts/<canonical-name>` destination object | Existing project filesystem | `exists()`, parent `mkdir`, then `shutil.copy2` (`init:45-51`) | CA-01: symlinks and hardlinks can redirect an authorized script refresh into protected intent, policy, history or external files. |
| Canonical script names and source bytes | FV checkout | Shared fixed inventory and source-presence precheck (`project:33-39`; `init:403-410`) | FV checkout authenticity remains trusted; no new operator-authentication claim. |
| Dispatch target | Project-owned dispatch | Type, containment, regular-file and target checks (`project:98-186`); v4 target equality (`consumer:1221-1227`) | No new target-resolution gap identified in the inspected v4 call path. |
| Verified-input policy | Project author | Include/exclude parser and structural exclusions (`project:355-433`); refresh does not intentionally call its writer | CA-01 can violate preservation through an alias; ordinary initializer behavior is a different command path. |
| Evidence policy, recipes, observation bindings and classes | Reviewed project policy | `_policy` checks membership, duplicate IDs, pointers, compatibility and canonical manifest agreement (`consumer:1037-1270`) | Dashboard relies on the shared checker and retained policy; it does not replace project observation semantics. |
| Stored claim/run/history values | Trusted producer/store | Reference, identity, schema, membership and history validation through `assess_v4` | Complete-store/nonfabrication trust remains explicit. |
| Counts and rendered status | Shared validator, then dashboard | Normal-path aggregation and display (`consumer:2447-2449,2517-2523,2954-2986`; `dashboard:867-970`) | CA-03: exceptional exits bypass counter aggregation. |

## Lens 5 - Field-name fidelity

| Field | Implied semantic | Actual value | Status |
|---|---|---|---|
| `binding`, `freshness`, `reusable`, `pass_semantics` | Whether current inputs or reuse eligibility were established | `not-recomputed`, `false` reuse eligibility and explicit stored-only wording (`consumer:2355-2367`; `dashboard:867-871,942-944`) | Faithful |
| `verdict` | Scoped coverage versus independently recomputed verification | `COVERED[profile=producer-trusted-execution-v4; binding=not-recomputed]` on a successful stored-only assessment (`consumer:3009-3021`) | Faithful; no stored PASS promoted to fresh VERIFIED |
| `validation`, observation provenance and recheck count | Validator implementation and whether member observations were rerun | `portable-checker`, `retained-receipts-only`, `observations_rechecked:false`, count zero | Faithful when read together; no local-producer-cache claim |
| `logical_associations` | Number of policy claim/tool associations represented | Sum of expanded slot rows (`consumer:2447-2449`) | Faithful once policy expansion succeeds |
| `unique_physical_executions` | Distinct validated execution artifacts referenced by the assessed generation | Set of artifact paths from work and claim references (`consumer:2605-2611,2740-2741,2954`) | Separate from logical associations; no independent-seed claim |
| `actual_dispatches`, `cache_hits` | New referenced physical work versus reuse in the selected run | Work entries with `cache=miss` and an execution reference; work entries with `cache=hit` (`consumer:2517-2523`) | Faithful on normal assessment paths; not a lifetime process/probe count |
| `missing_associations`, `failed_associations`, `error_associations`, `cancelled_associations` | Counts corresponding to displayed association states | Initialized to zero, populated only near normal completion (`consumer:2308-2318,2970-2986`) | CA-03: early errors can leave all counters zero beside nonempty MISSING rows. |
| Record/slot class, result and dependency gaps | Declared evidence type, assessed own outcome and dependency coverage | Shared-validator rows plus presentation aliases (`dashboard:841-865`) | No independent weaker verdict found |
| Doctor `project gate current` | Installed bytes equal canonical bytes | SHA-256 comparison (`doctor:440-453`) | Faithful as copy freshness only; not evidence freshness, executable provenance or activation |

## Lens 6 - Deferral justification audit

| Deferred finding | Justification claims | Claim audit | Verdict |
|---|---|---|---|
| Prior evidence-architecture F1/F2/F4 | Class fidelity, artifact ownership and unreadable-slot retention must survive adoption | V4 uses `_policy`, descriptor/reference checks and preexpanded slot rows; dashboard calls the shared assessment (`consumer:1193-1219,1433-1478,2408-2449,2614-2888`; `dashboard:823-865`) | No wrong-deferral finding. CA-03 is a distinct error-path reporting defect. |
| Aggregate evidence classes have no total strength lattice | Compatibility must be checked per obligation and per execution; inventing a total order would misstate assurance | Recorded rationale in `F/.fv/changes/2026-09-15-colosseum-shadow-migration.md:439`; compatibility checks remain at `consumer:1193-1206` | Justification remains consistent with inspected code. |
| Prior portable reviews 1-3 | Earlier observation-transport, outside-policy history and cutoff findings are closed | Current dashboard still reaches the same shared outcome/history helpers; round-3 report was read | No reopened finding in this display slice; this is not a new audit of the complete portable implementation. |
| External registry/git provenance, nonmutation, generated-cache integrity and history completeness | These are explicit trust boundaries, not properties proved by hashes | Current report provenance retains those limits (`consumer:2364-2377`) | No false discharge claim identified. |
| Ledger activation and refinement obligations | Local fixtures, planning and scoped coverage do not close C-14/C-15 or external prerequisites | Intent I13 and Ledger remain explicit; dashboard's verdict is qualified coverage | Unresolved prerequisites remain unresolved. No wrong-deferral finding. |

## Lens 7 - Migration and preservation

| Surface | Required preservation | Inspected behavior | Result |
|---|---|---|---|
| Script-only refresh | Intent, policy, dispatch, OMP config, evidence and history unchanged | Early branch installs only the five canonical names and returns before ordinary initialization (`init:403-424`) | Correct nominal write set; CA-01 defeats physical containment. |
| Existing include/exclude policies | Refresh does not normalize or widen policy | The refresh branch never calls `install_verified_inputs`; installer tests cover both modes (`F/tests/r29_omp_integration.py:186-252`) | No intentional policy migration found. |
| V3 evidence and quarantined history | No conversion into v4 checkpoints or rebinding | Refresh has no evidence parser/writer; template is a request only | Preserved under nonaliased destinations; CA-01 remains. |
| Runtime versus installed helpers | Updating validators does not silently select another runtime | Refresh returns before extension config changes; `F/INSTALL.md:141-144` distinguishes runtime updates | Boundary is explicit. |

## Lens 8 - Compatibility and path discovery

| Surface | Expected behavior | Inspected behavior | Result |
|---|---|---|---|
| No schema version | Existing v3 factory route | `F/tools/evidence-run.ts:610-648` retains the legacy branch and `pi.exec` transport | No default-v4 switch found. |
| Explicit v4 | Strict policy-backed call with no legacy override fields | Versioned union and execution dispatch at `F/tools/evidence-run.ts:614-632`; plan-only example | No downgrade fallback found. |
| Unknown/mixed v4 input | Fail closed before unwrapping | `consumer:1979-2056`; negative fixtures at `F/tests/m4_v4_coverage.py:478-522` | Inspected routing fails closed. |
| Cwd-relative CLI records path outside project cwd | Infer project from the named file, then read that same file | Root inference resolves against cwd, but v4 detection prepends the inferred root to the original relative spelling (`gate:617-622`; `consumer:2013-2017`) | CA-02; dashboard exits before legacy loading too. |
| Absolute records paths / project-root cwd | Resolve to intended contained evidence | Existing tests use absolute evidence paths with `cwd=fixture.root` (`F/tests/m4_v4_coverage.py:58-70`) | These fixtures do not cover CA-02's cross-cwd path. |

## Lens 9 - Reporting truthfulness

| Surface | Required distinction | Inspected behavior | Result |
|---|---|---|---|
| Stored versus fresh | COVERED/not-recomputed versus independently recomputed verification | Explicit mode flags and qualified verdict | Correct in inspected successful path and consistent with parent smoke. |
| Shared execution versus member observations | One physical invocation may have different member outcomes | Independent slot results and separate physical set | No inflated physical count identified on completed paths. |
| Genuine failure versus missing/cancelled work | Failure stays visible and cannot become PASS | Shared barrier/outcome helpers and failure-first final verdict | No weaker dashboard verdict introduced. |
| Early structural/binding error | Unknown/unassessed work cannot masquerade as zero missing/error work | Exception return skips association counter aggregation while rows remain MISSING | CA-03. |
| Read-only coverage | No recipe, checker re-execution or evidence publication | `recompute=False, recheck_observations=False`; inspected path reads retained files | No evidence-writing or subprocess path identified for stored dashboard assessment. Doctor probes are separate diagnostics. |

---

## Finding list (consolidated)

| ID | Lens | Severity | Surface | Intent ref | Code ref | Summary | Fix |
|---|---|---|---|---|---|---|---|
| CA-01 | who-controls; migration | Major | Script-only validator refresh | Intent I11/I12, `Intent:25,32`; V4 compatibility, `V4:9-11`; explicit preservation contract `F/INSTALL.md:132-139` | `init:39-64,412-424` | Refresh always calls the copy helper with `force=True`. The helper uses `exists()`, `mkdir()` and `shutil.copy2()` without rejecting symlinked components, symlink destinations or hardlinked files. [INFERENCE] If `.fv/scripts/fv_project.py` is a symlink to `../../docs/intent.md`, refresh truncates the canonical intent and replaces it with Python source, then reports success. A hardlink to protected evidence/history has the same destructive effect. A symlinked scripts directory can redirect writes outside the project. This needs no concurrent mutation or ABA race. | Preflight the complete five-file destination set before any copy: require contained real directories and regular nonaliased destinations, rejecting symlinks and hardlinks. Replace each allowed script name using a fresh sibling file and rename rather than truncating an existing inode. Add preservation regressions for file symlinks, ancestor symlinks and hardlinks to intent/history. |
| CA-02 | clause-to-line; compatibility | Minor | Dashboard CLI path/root discovery | Intent I12 preserved v3 behavior, `Intent:32`; `V4:9-11`; dashboard public file/directory CLI, `dashboard:143-157` | `dashboard:1044-1056`; `gate:617-622`; `consumer:1954-1959,2013-2017` | Root inference interprets `--records` relative to the process cwd, then detection interprets the same unmodified relative argument relative to the discovered project root. [INFERENCE] From `/work`, `--records p/.fv/evidence/v4/current.json` discovers `/work/p` but tries `/work/p/p/.fv/evidence/v4/current.json`. The dashboard returns ERROR for a valid existing file. The new unconditional detector also breaks the analogous legacy-v3 dashboard invocation before `load_records` runs. | Normalize CLI paths once against the invocation cwd before root discovery/detection, preserving v4's rejection of symlink components. Keep the helper's repo-relative API contract explicit. Audit the Gate B v4 callsite using the same helper. Add v3/v4 CLI cases from parent and nested working directories, alongside absolute-path cases. |
| CA-03 | field-name; reporting-truthfulness | Minor | Dashboard work counters on early assessment failure | Intent I12 full logical assessment, `Intent:32`; V4 S1, `V4:15`; dashboard count contract, `V4:567` | `consumer:2308-2318,2408-2455,2970-2986,3024-3036`; `dashboard:867-870,945-956` | Association counters start at zero and are populated only on the normal path near the end of assessment. The exception path returns them unchanged after logical rows may already have been expanded. [INFERENCE] A readable run whose common binding differs from the loaded policy produces N displayed MISSING slots and `logical_associations=N`, yet `missing_associations=0` and all other association-outcome counters zero. The ERROR verdict prevents a false PASS, but the work summary contradicts its own rows and understates unavailable coverage. | Finalize association counts from retained rows on every return path in the shared validator. If a metric was not assessed, represent that explicitly rather than as a measured zero. Keep the dashboard consuming the shared result. Add a post-expansion common-binding/structural-error regression asserting row/count agreement in JSON and text. |

## Summary

- Total findings: 3
- By severity: Critical=0 Major=1 Minor=2 Informational=0
- By lens: commitment-coverage=0 clause-to-line=1 deferred-cannot-silently-succeed=0 who-controls=1 field-name=1 deferral-justification=0
- Supplemental overlap: migration=1 compatibility=1 reporting-truthfulness=1; these are the same three findings, not additional findings.
- Recommended next step: (1) Close CA-01's destructive refresh aliasing before recommending script-only refresh. (2) Correct CA-02's CLI path normalization without weakening containment. (3) Correct CA-03 in the shared validator's error-path accounting. The parent should run the new regressions, `tests/r29_omp_integration.py`, `tests/r32_resolver_contract.py`, `tests/m4_v4_coverage.py` and the affected portable/legacy consumer suites after the fixes land. Retain separate full-canonical evidence and activation gates.