# Code-adversarial review: Dossier v4 schema, policy and source bindings - 2026-10-15

- Operator: fv-code-adversary via OMP task (NOT V4SchemaBindings)
- Code commit reviewed: `aa6946f29f6bc893cba62d58ef99efdc6d5a8716`; Dossier consumer commit `1fc3294437c294b040bc606aaa177334b8e41b8c`. Commit attribution is caller-supplied; no git commands were executed.
- Intent version reviewed: no frontmatter version; dispatch-resolved `D/docs/intent.md`, including the 2026-10-14 I11/I12 revision.
- Ledger version reviewed: no frontmatter timestamp; body declares Updated `2026-10-08`.
- Lens pack: crypto/enclave commitment lenses, supplemented with serialization, path-safety and evidence-freshness checks.
- Lenses applied: 1 through 6, followed by the three requested supplemental lenses.

## Scope and evidence limits

Path aliases in this report:

- `D` = `/Users/mv/Development/burnt/dossier-wt/evidence-perf`
- `F` = `/Users/mv/Development/reliq-fv-wt/evidence-perf`
- `M` = `F/tools/evidence-v4/evidence-v4-model.ts`
- `P` = `F/tools/evidence-v4/evidence-v4-policy.ts`
- `S` = `F/tools/evidence-v4/evidence-v4-source.ts`
- `R` = `F/tools/evidence-v4/evidence-v4-run.ts`
- `PY` = `F/scripts/fv_evidence_v4_schema.py`
- `PC` = `F/scripts/fv_evidence_v4.py`
- `V4` = `F/docs/execution-evidence-v4.md`

`D/.fv/dispatch.json` names `docs/intent.md`. The dependency contract is V4, with caller-supplied SHA-256 `825a053c2d3ba511a5f32f03168239fa24d5221195cb238865a9a1dc2ba7c0e2`. No separate F intent was assumed. The digest was not independently recomputed in this read-only review.

The primary review covers M, P and S. Runner, Python consumer/schema, existing source-policy helpers and Dossier policy/checker sections were inspected where their interfaces determine the meaning of those files. Native supervision, durable storage, history arbitration, installed-tool discovery and dashboard rendering were not independently re-audited.

Four Minor findings concern supported policy/configuration shapes and producer-consumer agreement. No finding establishes an unearned PASS for the current Dossier policy. Its record order is already sorted, its dispatch target is already repo-relative, and its inspected string/prefix declarations do not exercise these counterexamples.

No tests, builds, formatters, gates, shell commands, edits or live operations were performed. Counterexamples below are static deductions, labeled `[INFERENCE]`; they are not reproduced executions. The parent's reported Linux/Darwin checks, public-factory exercises, collector exercise and complete native plan are accepted as scoped observations without rerunning them. They do not constitute fresh canonical Dossier evidence or production activation.

The inspected policy projection contains 69 records, 108 logical associations and 82 recipe objects. Its 24 shared groups are fixed recipes; distinct recipes retain one owner-specific member each. EX-004 retains its three members and full fixed-seed witness command. Cargo tests, mobile tests, replay collectors and owner-specific Quint collectors remain distinct. Dossier's incorporated checker compares every original member and recipe field and checks the 69/108/82/24 inventory at `D/.fv/scripts/evidence_v4_observations.py:160-324`.

Important uncovered classes include authorization outside the evidence API, scheduler concurrency, resource exhaustion, crash/error atomicity, migration, supply-chain authenticity and native process escape/recovery. The approved-command lifecycle, no-concurrent-mutation, upstream build/cache integrity and complete trusted retained-history premises remain assumptions. Endpoint equality does not detect ABA; hashes do not authenticate the operator or prove history nondeletion. Actual served-route independence remains unexercised. This report makes no multi-family attestation claim.

---

## Lens 1 - Commitment coverage

| Commitment | Attacker DoFs | Bound by | Gap |
|---|---|---|---|
| Canonical bytes and domain hashes | Object order, Unicode spelling, escapes, number spelling, duplicate keys, null versus absence | `M:455-611`: scalar validation, unsigned UTF-8 key ordering, fixed control escaping, safe integer checks, duplicate-rejecting parser and `fv-evidence-v4/<label>\0` domains | No commitment omission identified. CA-03 concerns field acceptance across languages, not different canonical bytes for an accepted value. |
| Policy and common bindings | Recipes, classes, observations, checker definitions, intent, manifest, dispatch and canonical target inventory | `P:343-413`; `S:41-50,176-198`: canonical policy hash and exact-byte definition/intent/manifest/dispatch hashes | All declared common inputs enter the descriptor. CA-02 prevents some valid canonical targets from loading. Completeness of incorporated definitions remains a reviewed/project-checker obligation. |
| Global source inventory and snapshot | Added/deleted/renamed paths, executable bits, source bytes, verified-input selection | `S:92-223`; `M:1283-1298`: global path/executable inventory, exact verified-input-policy hash and v3-compatible path/NUL/content-hash/LF snapshot | No omitted field identified within the selected plus mandatory inventory. |
| Dependency closure | Closure mode, prefixes, basis, relevant bytes, common inputs and cache configuration | `S:227-244`; `M:1300-1309` | Fields are committed. CA-04 identifies a prefix interpretation mismatch before hashing. Semantic transitive completeness is not inferred from successful execution. |
| Environment | Reviewed variable names, presence, public values and OS identity | `S:245-289`: exact inherit/set union, set precedence, per-value H and OS/architecture/release | No ambient-union omission identified. Value safety depends on review of the allowed sources. |
| Execution key | Recipe semantics, all fixed members or one distinct association, global inventory, closure, environment, toolchain, cache selection | `S:291-379`; `M:1389-1428` | No missing descriptor field identified. UUIDs, times and caller selection are deliberately excluded. Whole-tree content remains an endpoint check rather than a narrow-closure key component. |
| Package, tool and directory-link identities | Package source/revision, retained files, executable bits, directory aliases and system boundary | `M:942-980,1321-1387` | Source-qualified package domains, target consistency, recursive directory hashes and cycle checks are present. Actual external enumeration is outside this slice and remains producer-trusted. |
| Execution, claim and history identities | Altered result/termination, references, source endpoints, member identity and predecessor sequence | `M:1430-1465,1484-1511,1542-1560` | Canonical object identities are recomputed. Byte/reference ownership and complete-store enumeration require the storage/consumer layers; these validators alone do not discharge those boundaries. |

There is no signature or enclave ReportData construction in this slice. Its hashes provide consistency bindings, not cryptographic producer authentication.

## Lens 2 - Clause-to-line discharge

| Clause | Expected discharge | Actual code line | Status |
|---|---|---|---|
| I11; V4 JSON/canonical-byte grammar | Exact parsing and cross-language identity semantics | `M:455-611,630-638,825-859`; `PY:57-145,269-310,791-793` | partial: canonical byte construction agrees by inspection; CA-03 identifies differing nonempty-string domains. |
| I11; V4 canonical intent binding | Bind the dispatch-resolved target in repo-relative form | `P:265-288`; `PC:1225-1231` | gap: CA-02. Producer compares the raw dispatch spelling rather than its resolved repo-relative target. |
| I12; V4 ordered policy arrays versus sorted set arrays | Preserve scheduling/claim order while emitting canonical ID sets | `P:152-190`; `M:1196-1197,1245-1247`; `R:189-190,413-416,1291-1292` | gap: CA-01. Valid nonsorted policy order leaks into set-valued result fields. |
| I12; V4 S1 | Preserve every logical association and full policy assessment | `P:138-190`; `R:1209-1251`; Dossier checker `:160-324` | discharged for expansion and the inspected aggregation seam; CA-01 can prevent serialization of otherwise valid generic-policy results. |
| I12; V4 S2 | Share only fixed recipes; distinct associations have distinct identity | `P:164-189`; `M:1394-1405`; `S:300-308` | discharged for the reviewed expansion. No output-hash-based merging occurs. |
| I12; exact bounds and original observations | Preserve argv, seeds, sample/depth limits and each member's definition | `P:120-137,351-369`; Dossier checker `:211-300` | discharged for these checks. The generic three-option check is supplemented by Dossier's complete original-recipe comparison. |
| I11; V4 source closure/path grammar | Reject unsafe sources and use the existing prefix semantics | `P:193-222`; `S:37-40,52-86,200-215,227-244` | partial: source containment/type/link checks are present; CA-04 covers trailing-slash prefix disagreement. |
| I11; V4 B1 | PASS requires stable clean source and bound provenance | `S:224-226,309-377`; `M:1430-1465`; `R:363-373,380-397,552-582` | partial: this slice enforces identity and endpoint legs; actual completion, ownership and durability need neighboring implementations. |
| I12; V4 B2 | Missing/malformed/cancelled work cannot become PASS; failures survive selection | `M:1439-1465,1520-1540,1542-1560`; `R:1209-1251` | partial: local PASS consistency and full aggregation inspected; complete retained-history cutoff enforcement is outside this slice. |
| V4 T1 | Failure stops dispatch; durable execution/history precede subsequent work | Typed history/receipt fields at `M:292-349,1077-1098` | partial: schema representation is present; ordering/durability is not proved by a data shape. |
| V4 T2 | Do not steal ownership; detect endpoint drift without claiming continuous immutability | `S:52-86,224-226`; `R:363-373`; ownership schemas `M:1018-1057` | partial: source drift checks inspected; native liveness/recovery remains outside scope. |
| I13 | Scoped evidence must not become activation | Full canonical target binding `P:392-400`; Dossier separate assessments `D/.fv/scripts/check_integration_evidence.py:579-590` | discharged at the inspected scope boundary; no activation exercise or full Gate B refresh claimed. |
| I14 | Preserve runtime refusal and operational authority limits | Primary files contain evidence configuration/binding logic, with no protocol activation path | unchanged by this slice; protocol/runtime enforcement was not re-audited. |
| Ledger C-01 through C-09 | Preserve bounded composition obligations and missing refinement links | Policy/member expansion `P:152-190`; ledger C-01 through C-09 | partial: associations are preserved; this implementation does not prove the protocol conjunctions. |
| Ledger C-10, C-11, C-12, C-13, C-14, C-15 | Preserve their separate mobile, wire, registry, private-operation, receipt and runtime/replay limits | Canonical inventory `P:293-341,400`; ledger respective candidates | partial: inventory binding only. All six candidates retain their ledger limitations. |
| Ledger TA-08 | Do not claim unsigned local evidence authenticates its producer | Hash-only machinery `M:517-523`; explicit assumptions `M:774-778` | partial by declared trust, not cryptographically discharged. |
| V4 nonmutation/cache/store assumptions | Record and bind the exact operational premises | `M:774-778,895-905,984-1008`; `P:391`; `S:325-337` | discharged as explicit declarations/bindings, not proof that the premises hold. |
| Ledger TA-01, TA-02, TA-03, TA-04, TA-05, TA-06, TA-07, TA-09, TA-10, TA-11, TA-12, TA-13, TA-14, TA-15, TA-16, TA-17 | Preserve platform, cryptographic, custody, provenance and activation assumptions | Ledger external trust-assumption inventory | partial/outside this slice: no discharge asserted. |
| Remaining canonical protocol clauses | I1-I10; A1-A5/B/C1-C5/D1-D4 and RS1-RS6; S1-S7, B1-B19/B2t/Q-B19; private-v2 clauses and qualification requirements | Protocol implementations are outside the named code roots | outside this review's discharge scope. These clauses remain obligations of their existing components, not missing implementations in the evidence producer. |

## Lens 3 - Deferred cannot silently succeed

| Branch | Reachable from | Behavior | Status |
|---|---|---|---|
| Unknown or malformed JSON/schema value | Policy, call and retained-object parsing | Explicit errors for duplicate keys, invalid scalar/number grammar, unknown fields and missing fields at `M:528-611,696-727` | No deferred-success branch identified. |
| No reviewed prefix basis | Descriptor closure construction | Falls back to all verified inputs at `S:227-244` | Explicitly authorized conservative fallback; does not manufacture a narrow closure. |
| Missing dispatch configuration | `loadPolicy` | Uses `.fv/intent.md`; other read errors propagate at `P:265-283` | Authorized absence default, subject to CA-02's resolution issue. |
| Missing verified-input file | `captureInputState` | Uses the existing default parser policy and domain-separated default-policy identity at `S:99-112` | Authorized absence default. Missing mandatory source is still rejected. |
| Missing recipe, tool, observation pointer, cache configuration or dirty source | Policy loading and descriptor materialization | Throws at `P:69-79,142-149,223-237`; `S:309-337` | Explicit failure. |
| Schema union alternatives | Exact object validation | Failed alternatives are tried, then the union throws at `M:718-727` | Catching a failed alternative does not return a default success. |
| Production-reachable TODO/stub/mock implementation in the three primary files | Primary-file search and inspection | No matching deferred implementation branch found | Empty deferred-success finding set. `mock-attestation` inside reviewed Dossier test argv is an explicit test recipe, not a producer stub. |

## Lens 4 - Who controls

| Field | Supplier | Validation | Gap |
|---|---|---|---|
| Call `schema_version`, `policy`, `mode`, `records`, `jobs`, `resume` | Caller | Exact shape and ID/path/set grammar at `M:1230-1239`; membership/job ceiling at `R:185-193` | No command/class/marker override. CA-01 affects default selection serialization. |
| Policy paths, records, required flags, classes, dependencies and tool associations | Reviewed repository policy/manifest | `P:60-149,293-341`; exact Dossier member checks | No owner-specific randomized association is removed. |
| Recipe command/cwd/marker/timeout/bounds/determinism/attestation/cache/ownership/retained-environment fields | Reviewed policy | Exact schema, option agreement, tool graph, pointer resolution and incorporated checker at `P:81-137,343-390` | Semantic determinism and closure completeness require review; neither is inferred from a nonempty rationale. |
| Closure `mode`, `prefixes`, `basis` | Reviewed policy | `P:107-112`; `S:200-215,227-244` | CA-04: a trailing-slash prefix can be satisfied by a regular file of the same basename. |
| Common policy/intent/manifest/definition/dispatch hashes and target list | Producer reading repository files | `P:343-413`; recaptured at `S:176-198` | CA-02 concerns target resolution; no caller-supplied hash shortcut found. |
| Input `files`, hashes, sizes, executable bits, inventory, snapshot and clean flag | Filesystem and Git metadata | Containment, regular type, link count, inode alias tracking, before/after metadata and status processing at `S:52-223` | No additional grounded finding under the frozen nonmutation premise. |
| Child environment values and identity | Reviewed inherit names plus public literals; runtime supplies inherited values | Null-prototype map, exact union, override precedence, NUL/scalar checks and hashed presence/value at `S:245-289` | No extra ambient capture. This does not classify arbitrary values as nonsecret. |
| Descriptor members/distinct slot/toolchain/cache | Policy expansion and attested tool session | `S:300-377`; `M:1389-1428` | Missing identities and mismatched declarations reject. Completeness of installed enumeration is a separate adapter obligation. |
| Retained artifact/history/owner/observation/claim/run fields | Native producer, checker and trusted retained store | Exact schemas and intrinsic consistency at `M:1018-1592` | Shape validation is not OS provenance, immutable-file ownership or complete-history proof; those boundaries remain external to this slice. |

## Lens 5 - Field-name fidelity

| Field | Implied semantic | Actual value | Status |
|---|---|---|---|
| `policy_hash` versus `intent_hash`, `manifest_hash`, definition hashes | Parsed policy identity versus exact source bytes | `D("policy", policy)` versus H of file bytes at `P:391-400` | Faithful. |
| `inventory_hash` versus `source_snapshot` | Global path/mode identity versus whole selected content | `S:216-223` | Faithful; inventory deliberately excludes content hashes. |
| `closure.mode`, `prefixes`, `basis`, `files`, `hash` | Effective dependency closure actually bound into the key | `S:227-244` records whole-input fallback explicitly | Faithful effective-mode reporting; CA-04 concerns prefix selection. |
| Environment `present`, `value_hash` | Presence and hashed value, not disclosed plaintext | `S:266-276`; `M:1312-1317` | Faithful. |
| `members`, `distinct_slot` | Full fixed membership or one owner/slot association | `P:160-190`; `S:367-369` | Faithful. |
| `required_targets`, `required_records`, `selected_records` | Canonical manifest inventory, policy requirements and dispatch selection | `P:400`; `R:189-190,413-417,1291-1292` | Membership meanings remain distinct. CA-01 concerns canonical ordering rather than mislabeled membership. |
| `clean` | Selected source is clean according to the prescribed Git scan | `S:155-171` | Does not claim continuous immutability or cache correctness. |
| PASS and publication fields | Eligible completion versus durable run publication | `M:1439-1465,1571-1592` | Intrinsic checks retain the distinction; actual durable publication is not reviewed here. |

No additional name-to-value semantic substitution was identified.

## Lens 6 - Deferral justification audit

| Deferred finding | Justification claims | Claim audit | Verdict |
|---|---|---|---|
| Prior external registry/git completeness clarification | Generic retained hashes do not reveal an independent complete external inventory; producer construction remains under TA-08 | `D/.fv/code-adversarial/2026-10-14-v4-portable-review-2-clarification.md`; `M:942-980,1321-1387` retains identities/manifests, not archive or Git-object preimages | Valid limitation within this slice. No demand for a new authentication format. |
| Endpoint ABA and generated-cache correctness | Equal endpoints cannot prove absence of restored edits or source-to-product correctness | `S:52-86,224-226`; cache selection binding `S:325-337`; V4 operational assumptions | Justification matches the inspected mechanism. No wrong-deferral finding. |
| Portable reviews 1-3 closure | Earlier consumer omissions and receipt/history defects were corrected | Round-3 report and clarification were read; the parent states these reviews are closed | Closure is retained as prior scoped evidence, not independently re-established for all neighboring code. |
| Immutable architecture review F1/F2/F12 constraints | Class downgrade, undeclared output substitution and pre-baseline probes must remain blocked | `P:326-341`, `P:152-190`, `S:291-377`, `R:380-397` | Inspected class, expansion and baseline legs remain present. Raw ownership and full history require their own review. |
| Historical F15/F17 scope notes | Earlier schemas trusted some record assertions and did not expand dependency coverage | V4 fixes assumption literals/waiver shape, canonical targets and dependency inclusion at `M:774-778,1181-1184`; `P:315-341,400` | No current silent reliance on those historical scope notes identified in this slice. |
| Native containment, durability and activation deferrals | Approved lifecycle and filesystem guarantees are bounded; canonical evidence/activation remain separate | Current contract and change-record dispositions explicitly retain these limits | Not discharged here and not treated as successful verification. |

No production-reachable deferred finding was found to be justified by a false claim in the inspected primary implementation.

## Supplemental lens - Serialization agreement

| Surface | Evidence | Result |
|---|---|---|
| C/H/D, integer tokens, Unicode ordering and duplicate keys | `M:455-611`; `PY:28-145`; existing vectors `F/tests/r38_evidence_v4_schema.py:128-210` | No canonical-byte disagreement identified by inspection. Tests were read, not run. |
| Ordered records versus result ID sets | `M:884-905,1196-1197,1245-1247`; `R:189-190,413-416,1291-1292` | CA-01. |
| Nonempty scalar strings versus command-safe strings | `M:630-638,825-859`; `PY:269-310,791-793,826-831` | CA-03. |
| Incorporated arbitrary-precision collector data | V4 JSON grammar explicitly excludes child attachment schemas from C | No new collector reserialization path found in the three primary files. Attachment handling remains a separate review boundary. |

## Supplemental lens - Path safety

| Surface | Evidence | Result |
|---|---|---|
| Source/cwd lexical containment and symlink components | `M:614-625`; `P:193-222` | Unsafe lexical paths, symlink components and nonregular sources reject. |
| Hardlinks and source aliases | `S:59-85` | Link-count and device/inode checks reject aliases; metadata drift during hashing rejects. |
| Canonical dispatch target | `P:265-288`; `F/scripts/fv_project.py:152-181` | CA-02. |
| Directory-prefix semantics | `S:37-40,200-215`; `F/tools/evidence-run.ts:243-249`; `PC:1384-1392,1415-1420` | CA-04. |
| Output/artifact safety | Shapes declare safe paths; actual file operations belong to storage/native layers | Not re-audited. No output-path safety conclusion is inferred from the schema alone. |

## Supplemental lens - Freshness

| Surface | Evidence | Result |
|---|---|---|
| Complete selected inventory plus mandatory bindings | `S:113-154,176-198` | Mandatory definitions are added independently of include selection; selected gitlinks/unmerged paths reject. |
| Dirty source, including outside a narrow closure | `S:155-171,224-226,309` | Cleanliness is global to selected inputs; a narrow recipe does not narrow the dirty check. |
| Add/delete/rename/executable-bit invalidation | `S:216-223,370-372` | Global inventory enters every execution descriptor. |
| Clean unrelated content changes | `S:227-244,364-376` | Whole snapshot is excluded from narrow execution identity, while the runner still compares whole invocation endpoints. |
| Baseline and endpoint sequencing | `R:380-397,552-582`; `S:224-226` | Baseline precedes tool capture/version/preflight work at the inspected seam. Full native lifecycle and failure-history eligibility remain outside this review. |
| Trust limits | I11; V4 operational/cache/store assumptions | No ABA, fresh-compilation, producer-authentication or deletion-resistant-history claim is supported by these hashes alone. |

---

## Finding list (consolidated)

| ID | Lens | Severity | Surface | Intent ref | Code ref | Summary | Fix |
|---|---|---|---|---|---|---|---|
| CA-01 | clause-to-line | Minor | Policy/model/runner serialization | I12; V4 Canonical bytes, especially `V4:43`, and callable PlanResult/RunManifest contracts | `M:884-905,1196-1197,1245-1247`; `P:152-190`; `R:189-190,413-416,1291-1292` | Policy records intentionally preserve reviewed order, but the runner copies that order into set-valued `required_records` and default `selected_records`. Both schemas require UTF-8-sorted sets. A valid policy ordered B then A therefore cannot produce a valid plan/run report. | Sort copied ID-set projections with `utf8Compare`. Preserve policy record, physical work and claim-file order. Add B-before-A policy tests for plan, default selection and explicit sorted selection. |
| CA-02 | clause-to-line | Minor | Canonical target boundary | I11; `V4:122` requires the dispatch-resolved canonical target; established resolver permits contained absolute targets | `P:265-288`; `F/scripts/fv_project.py:152-181`; `PC:1225-1231` | Producer `loadPolicy` compares `policy.intent_path` with the raw dispatch string. A contained absolute target accepted and normalized by the canonical Python resolver cannot equal the required repo-relative Policy Path. Equivalent normalized relative spellings also disagree. | Resolve dispatch against the real project root, enforce containment and component safety, then compare the canonical repo-relative path. Match existing resolver semantics without expanding `~`. Add native/Python parity cases. |
| CA-03 | clause-to-line | Minor | TypeScript/Python schema boundary | I11/I12; `V4:24-26,32-43` scalar-string grammar and `V4:110` nonempty scope; boundary acceptance checklist | `M:630-638,825-859`; `PY:269-310,791-793,826-831` | TypeScript `nonempty` accepts all nonempty Unicode-scalar strings, including escaped NUL in `scope` or a determinism rationale. Python reuses TEXT, which additionally forbids NUL, for those fields and for argv. Thus a contract-valid policy value accepted by the producer's schema is rejected by its portable schema. | Separate generic nonempty scalar strings from NUL-free argv/OS strings in Python and retain explicit field-specific restrictions. Add differential vectors for scope, rationale, marker and argv. Do not globally weaken command validation. |
| CA-04 | who-controls | Minor | Source closure/path selection | I11; `V4:26,138-140,157-159` requires existing verified-input prefix semantics and covered prefixes | `S:37-40,200-215,227-244`; `F/tools/evidence-run.ts:243-249`; `PC:1384-1392,1415-1420` | `prefixSelects` strips a final slash and allows equality with the basename. The existing helper and portable checker interpret `x/` as descendants only. A regular file `x` can satisfy the producer's required `x/` prefix and enter its closure, while the portable checker rejects that prefix as uncovered. | Reuse the existing trailing-slash versus bare-component matching semantics. Reject a directory-designating prefix whose endpoint is not a directory. Add file `x`/prefix `x/` and real directory `x/child` parity cases. |

### Static counterexamples and impact

1. **CA-01:** `[INFERENCE]` Use a valid reviewed policy with required records in order `B, A`, each with an ordinary valid execution. `validatePolicy` and `expandPolicy` preserve that order. With no call selector, the runner emits both ID sets as `["B","A"]`; with an explicit sorted selector, `required_records` is still unsorted. `validatePlanResult` rejects the plan. On a run, collection can precede failure to serialize/publish the manifest. This is a supported-policy availability/publication defect, not an erased obligation or false PASS.
2. **CA-02:** `[INFERENCE]` Set dispatch `target_spec` to `<real-project-root>/docs/intent.md` while the policy correctly contains `intent_path:"docs/intent.md"`. Python resolves the same contained file and normalizes it to the policy path. P instead throws before loading the intent bytes. No path escape is required.
3. **CA-03:** `[INFERENCE]` Replace a fixture record's scope with JSON string `"bounded\u0000scope"`, leaving commands, classes and observations unchanged. M accepts it and C escapes the scalar as required. `PY.validate("Policy", value)` rejects its scope through TEXT. A stricter project-specific checker may reject earlier; the generic schema mismatch exists independently of that choice. No affected current-Dossier run is claimed.
4. **CA-04:** `[INFERENCE]` In a clean fixture, let regular selected file `x` exist and declare a nonempty-basis prefix closure containing `x/`. The native coverage check succeeds because `prefixSelects("x","x/")` is true; its component walk checks for symlinks without requiring this endpoint to be a directory. Python's established matching helper finds no descendant and rejects. Existing Dossier directory prefixes do not exhibit this shape.

The findings are Minor because they fail closed or prevent acceptance of evidence at an interface. None of these traces demonstrates weakened proof bounds, lost owner-specific random coverage, unauthorized sharing or a successful canonical gate on invalid current-Dossier evidence.

## Summary

- Total findings: 4
- By severity: Critical=0 Major=0 Minor=4 Informational=0
- By lens: commitment-coverage=0 clause-to-line=3 deferred-cannot-silently-succeed=0 who-controls=1 field-name=0 deferral-justification=0
- Supplemental lens mapping: serialization=CA-01/CA-03; path-safety=CA-02/CA-04; freshness=no additional finding.
- Recommended next step: correct result-set ordering, normalize canonical targets, align field-specific string validation, then restore existing trailing-slash prefix semantics. The parent should add the cited differential/end-to-end counterexamples and run the affected schema/source/public-factory/portable suites once after integration. Preserve every current Dossier member, randomized owner-specific recipe, argv, seed, sample/depth bound and activation restriction. Native/storage/history review and fresh canonical evidence remain separate requirements.