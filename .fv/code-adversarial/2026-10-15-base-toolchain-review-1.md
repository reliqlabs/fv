# Code-adversarial review: dossier evidence-v4 toolchain closure - 2026-10-15

- Operator: fv-code-adversary via OMP task (NOT V4ToolchainBase)
- Code commit reviewed: `aa6946f29f6bc893cba62d58ef99efdc6d5a8716`; Dossier consumer commit `1fc3294437c294b040bc606aaa177334b8e41b8c`
- Intent version reviewed: absent from frontmatter; dispatch-resolved `docs/intent.md`, including the 2026-10-14 I11/I12 revision
- Ledger version reviewed: absent from frontmatter; inline Updated value `2026-10-08`
- Lens pack: crypto/enclave, supplemented with supply-chain, input-closure and change-detection analysis
- Lenses applied: 1 through 6

## Scope and evidence limits

Path abbreviations:

- `D` = `/Users/mv/Development/burnt/dossier-wt/evidence-perf`
- `F` = `/Users/mv/Development/reliq-fv-wt/evidence-perf`
- `T` = `F/tools/evidence-v4/evidence-v4-toolchain.ts`
- `C` = `F/tools/evidence-v4/evidence-v4-toolchain-common.ts`
- `R` = `F/tools/evidence-v4/evidence-v4-toolchain-rust.ts`
- `Run` = `F/tools/evidence-v4/evidence-v4-run.ts`
- `V4` = `F/docs/execution-evidence-v4.md`

`D/.fv/dispatch.json` resolves to `D/docs/intent.md`. F has no separate canonical intent for this review. The normative dependency contract is V4, with caller-supplied SHA-256 `825a053c2d3ba511a5f32f03168239fa24d5221195cb238865a9a1dc2ba7c0e2`. Commit attribution and that digest were supplied by the caller, not independently recomputed. No Git commands, shell commands, tests, builds, gates, edits or live operations were performed.

The primary review covers T and C. Referenced Rust package/cache selection, producer scheduling, schema/policy guards, Dossier declarations and installed tsx launcher/resolver bytes were inspected for boundary grounding. Rust build-script interpretation, proof-adapter internals, native supervision, durable storage, portable assessment and dashboard behavior were not independently audited end to end.

The parent reports the Linux and Darwin checks, five CI gates, real factory/resume exercises, actual collector exercise, all 41 Dossier tool identities plus the producer, and READY planning for 69 records/108 logical slots/82 physical executions/24 shared groups. Those observations are accepted without rerunning them. They do not exercise the counterexamples below or establish fresh canonical Dossier evidence. Static consequences not demonstrated by an execution are marked `[INFERENCE]`.

Frozen assumptions remain approved conforming child lifecycle, no concurrent external mutation, upstream build-cache integrity and complete trusted retained history. Findings concerning replacement mean replacement between producer invocations, not an excluded concurrent mutation or ABA attack. Installed launchers, imported packages and selection helpers are tool inputs, not source-correct generated products exempted by the build-cache premise.

Operator/OS/compiler authenticity remains trusted. This report establishes no cryptographic producer authentication, multi-family serving-route attestation, refinement or production activation. Important uncovered classes include protocol access control, arithmetic, reentrancy, general resource exhaustion, process-lifecycle concurrency and crash consistency. Resource declarations and cache identities were inspected, but global locking correctness was not established.

---

## Lens 1 - Commitment coverage

| Commitment | Attacker DoFs | Bound by | Gap |
|---|---|---|---|
| Regular tool-file hash | Installed bytes, size and execute bits | C:263-311 hashes bytes and checks device/inode/size/mode/mtime/ctime across the read; T:1263-1273 commits the resulting manifest | No additional file-hashing gap identified. Metadata caching remains conditional on the stated nonmutation premise. |
| Tool tree and directory-link target hashes | Root contents, empty directories, link text, canonical target and nested aliases | C:313-465 traverses ordinary roots, records links, selects canonical targets and rejects recursive target-hash cycles | No additional alias/cycle finding identified. Completeness still depends on supplying every required root. |
| Node execution identity | `.bin/tsx`, its selected Node executable, shell helper selection and injected module search paths | T:816-845 hashes package roots and PATH-selected Node; T:1330-1355 checks only the outer command executable | CA-01: the installed execution shim and its runtime selection are omitted. |
| Python dependency identity | Dynamically imported modules, `from` submodules and parent package initializers | T:501's embedded `resolve`, `scan` and `visit`; T:1296-1325 validates only reported requirements | CA-02: incomplete discovery can produce an empty requirements list or omit executable package files without refusal. |
| Node source-import closure | Which sibling source tsx resolves and the packages that source imports | T:173-215 chooses its own first-existing candidate; T:820-833 collects package roots | CA-03: discovery resolution differs from the selected installed tsx resolver. |
| Darwin native-library closure | Loader environment selecting or inserting non-system images | T:722-761 follows Mach-O install names and rpaths | CA-04: effective `DYLD_*` selection is neither bound as file content nor rejected. |
| Discovery-helper identity | PATH-selected metadata executable and its interpreter/native dependencies | T:1024-1034 puts executable bytes in a private memoization key; T:1079-1085 retains only command/output/status | CA-05: helper bytes can disappear from the persisted tool identity. |
| Source-qualified Cargo package identity | Registry source/checksum, Git URL/revision, project-relative package location and installed contents | R:625-655,768-795; T:1263-1273 | Inspected path-package construction rejects external/symlink-resolved package directories and uses source-qualified labels. Full Cargo/Kani graph correctness remains outside this slice. |
| Cache namespace identity | Effective target/build/transformation/compiler-cache paths and declared configuration bytes | T:1403-1448; R:1583-1689 | Nonempty namespace checks and canonical path hashes exist. CA-01/CA-03 can make Node discovery describe a different runtime/input path from the one actually executed. |
| Producer implementation identity | Actual source/import bytes and host runtime | T:895-1175 | Static source/runtime construction inspected; CA-05 applies to omitted native-discovery helpers. This is an unsigned content identity. |

## Lens 2 - Clause-to-line discharge

| Clause | Expected discharge | Actual code line | Status |
|---|---|---|---|
| D I11: complete current dependency/tool provenance | Unknown installed closure must prevent reuse/PASS | T:163-218,434-553,787-892,1296-1325 | gap: CA-01 through CA-05 |
| D I11: metadata must not substitute application execution for discovery; V4 adapter restriction | Inspect selection without executing project application code | T:448-469,500-509 | gap: CA-06 |
| V4 discovery deduplication, V4:237 | Deduplicate equivalent semantic discovery contexts only | T:1093-1123 versus T:1185-1191 | gap: CA-07 |
| D I11 and V4 T2: endpoint drift detection | Recompute installed selection before accepting reuse | T:1369-1397; Run:674-685 | discharged for the inspected ordering: generation increments, probes/discoveries clear, identities compare, then candidate selection occurs. This cannot recover omitted inputs. |
| V4 source-qualified package contract, V4:252-262 | Preserve source qualification and reject escaping project path packages | R:625-655,768-795 | discharged for the inspected identity/root construction; selected graph completeness is partial |
| V4 tree-manifest contract, V4:219-223 | Canonical aliases, explicit directories and cycle rejection | C:313-465 | discharged for the inspected construction |
| V4 generated-cache contract, V4:165-181 | Bind actual namespace/configuration and hold declared resources | T:1403-1448; R:1583-1689; `F/tools/evidence-v4/evidence-v4-policy.ts:112-113`; Run:611-630 | partial: namespace construction and declared-resource inclusion inspected; actual locking and all upstream selectors are outside this slice |
| V4 S1 and D I12: preserve all logical slots | Discovery must not narrow required work | Run:504-517 and full-policy preflight at :535-589 | partial: tool construction runs over complete preflight policy; full final assessment is separately owned |
| V4 S2: immutable execution ownership and reviewed sharing | Complete identity precedes shared reuse | Run:508-517,674-685 | partial: identity construction is impaired by the listed gaps; storage ownership was not re-audited |
| V4 B1 | Real completed invocation plus clean endpoints, complete provenance, ownership and history | Run:674-685,800-805 | partial: provenance boundary reviewed; completion/storage/observation enforcement outside this slice |
| V4 B2 | Stale, malformed or failed work cannot become PASS through reuse | T:1382-1390; Run:674-685 | partial: changed represented identities reject; omitted dependencies remain gaps; history barriers not re-audited |
| V4 T1 | Failure stops new dispatch and durable accounting precedes reuse | Run:594-654 | partial: scheduling callsites inspected, durability and complete in-flight accounting not established here |
| D I12: exact commands, bounds and per-member observations | Do not reduce verification work to repair performance | `F/tools/evidence-v4/evidence-v4-policy.ts:120-138`; Run:508-517 | partial: bound/argv validation inspected; observation semantics belong to another slice |
| D I13/I14 | Keep activation and operational authority separate | These modules construct identities and do not grant deployment authority | partial: no activation mechanism found in scope; canonical full gate remains separate |
| Ledger TA-08 | Disclose unsigned producer/operator trust | T:1130-1175 emits content identities without signatures | partial by explicit trust, not a cryptographic discharge |
| Ledger TA-07, TA-11 and TA-12 | Local provenance must not become cross-host or validator authenticity | Recorded installed/source/cache identities only | partial by scope; no validator authenticity or historical-chain qualification established |
| Ledger C-01 through C-15; TA-01–TA-06, TA-09–TA-10, TA-13–TA-17 | Preserve existing component and external-assumption obligations | No corresponding protocol enforcing code inspected | partial: explicitly outside this toolchain slice; none is discharged here |
| Remaining canonical protocol clauses, including I1–I10 | Preserve protocol behavior and production refusals | No protocol implementation changes or review in this assignment | partial: outside scope, not inferred correct from toolchain checks |

## Lens 3 - Deferred cannot silently succeed

| Branch | Reachable from | Behavior | Status |
|---|---|---|---|
| Unknown adapter, unsupported native platform or missing installed selection | `identify` and adapters | Throws, including T:1214-1215,565-566,800-817 | Explicit refusal |
| Missing locked package or ambiguous package snapshot | Node discovery | Throws at T:130-141,147-160 | Explicit refusal for cases it recognizes |
| Python `UNKNOWN` expressions and unhandled call forms | Production metadata scanner | T:501 accepts ordinary unknown assignments/calls without requiring import-closure resolution | Gap, consolidated as CA-02 rather than a duplicate finding |
| Missing effective declared cache namespaces | `buildCache` | Throws at T:1427-1428 | Explicit refusal |
| Null build-cache declaration | `buildCache` | Returns null at T:1404 | Contract-authorized only for recipes consuming no generated products; no independent inference of that fact was found in this method |
| Marked TODO/stub/mock/not-yet implementation | Primary production files | Targeted search found no such placeholder implementation; Python's `deferred` list is function-body scanning, not a stub | No separate marked deferred-success finding |

## Lens 4 - Who controls

| Field | Supplier | Validation | Gap |
|---|---|---|---|
| Declaration ID, kind, locator, requires, pins and version command | Reviewed policy | Policy/schema checks; T:974-990 resolves acyclic requires; T:1242-1246 checks locator kind/executability; T:1285-1289 checks acceptance pins | No additional declaration-shape finding |
| `ToolIdentity.files` and `digest` | Producer enumeration over installed files | C:263-465 plus `validateToolIdentity` | CA-01–CA-05 concern omitted required inputs, not forged hash syntax |
| `packages` | Cargo metadata plus lockfile | R:625-655; digest-qualified roots at R:768-795 | Inspected source identity and path containment checks exist |
| Python `requirements` | Embedded metadata interpreter | T:516-531 checks shape; T:1296-1325 checks explicitly reported files | CA-02: a well-shaped incomplete list is accepted |
| `discovery` and `version` | Actual probe results | T:1051-1085 rejects abnormal/nonzero probes and hashes output | CA-05: persisted output hashes do not bind every helper's bytes |
| `origins`, adapter results and identity memoization | Producer session | Per-generation rediscovery and identity comparison | CA-07: adapter-result cache key omits context that controls requirements |
| `BuildCacheIdentity.configuration` and namespace hashes | Policy paths and adapter selection | T:1403-1448; configuration enters mandatory source inputs through policy loader | Partial: exact declared bytes/path hashes are bound; actual selected execution can diverge through CA-01/CA-03 |
| `system_dependencies` | Producer OS and discovered SDK | T:1267-1272; T:764-783 | Vendor/OS authenticity remains assumed; CA-04 is outside that system-library exception |
| Resource names | Reviewed policy and adapter requirements | T:1223-1226; policy resource-subset check | Declaration consistency inspected; no proof that independently named resources always serialize a shared namespace |

## Lens 5 - Field-name fidelity

| Field | Implied semantic | Actual value | Status |
|---|---|---|---|
| Tool `digest` | Content identity of the declared complete tool closure | Hash of supplied files/packages/system metadata | Hash semantics are faithful; closure omissions are CA-01–CA-05 |
| `discovery[].stdout_hash`, `stderr_hash`, `exit_code` | Actual probe streams/status | T:1076-1085 derives them from actual native execution | Faithful; these fields do not imply a helper-executable hash |
| `version.text` | UTF-8 stdout followed by stderr, with specified outer whitespace trimming | T:1275-1283 | Faithful in inspected code |
| Link `target`, `resolved_path`, `resolved_hash`, `resolved_size`, `executable` | Literal link plus canonical target identity | C:350-361,401-431,438-465 | Faithful in inspected construction |
| `system_dependencies.sdk.settings_hash` | Exact selected settings-file bytes | T:780-782 | Faithful byte hash; helper selection has CA-05 |
| Cache `kind`, `identity_hash`, `integrity` | Selected canonical namespace or reviewed fresh namespace; upstream integrity premise | T:1435-1448 | Faithful field meanings; not proof of fresh compilation |
| `implementation_hash` | Producer implementation/import bytes, excluding runtime | T:895-961 | Matches its separate purpose; runtime is represented in the reserved identity |

No independent field-renaming or value-semantic substitution finding was identified.

## Lens 6 - Deferral justification audit

| Deferred finding | Justification claims | Claim audit | Verdict |
|---|---|---|---|
| Prior portable review's external package completeness limitation | Generic consumer cannot derive an external inventory from self-described hashes; producer must enumerate it | `D/.fv/code-adversarial/2026-10-14-v4-portable-review-2-clarification.md:9-26` states this distinction. T/C are the producer construction path; omissions here remain defects even though the consumer cannot reconstruct them | Valid consumer limitation; CA-01–CA-05 are producer findings, not reopened consumer findings |
| Prior portable path-package correction | Consumer checks every independently bound project package input | Round-3 report records the expected-inventory correction. R:633-643,768-795 supplies qualified path identities and rooted contents | No wrong-deferral established; consumer implementation was not re-reviewed for closure |
| Prior host review's unreviewed external producer prerequisite | Host closure did not establish external tool discovery correctness | `D/.fv/code-adversarial/2026-10-14-v4-host-review-2.md`, scope and Lens 6, explicitly leaves native producer closure external | Limitation remains applicable; this review supplies new producer defects |
| Nonmutation, upstream-cache and trusted-history premises | Endpoint checks do not prove continuous immutability, build correctness or nondeletion | T:1369-1397 checks endpoints; T:1448 records upstream integrity; Run checks represented identities before reuse | Valid explicit assumptions; they do not waive omitted installed inputs |
| Toolchain-specific deferred prior findings | No applicable prior deferral record located among the discovered reports | No evidence of a prior authorization to accept incomplete Python/Node/native discovery | Empty wrong-deferral finding set; no invented prior disposition |

## Supplemental lens - Supply chain

| Surface | Check | Result |
|---|---|---|
| pnpm/tsx dispatch chain | Compare actual installed shim with roots selected by the adapter | CA-01. The installed shim selects more than the package entrypoint. |
| Package authenticity versus content identity | Distinguish bytes/checksums from publisher/source authenticity | Source qualification is represented; distribution honesty remains trusted. No stronger supply-chain attestation is claimed. |
| Metadata helper executables | Follow retained output hashes back to helper bytes and runtimes | CA-05. Private probe memoization is not persisted provenance. |
| Native images | Compare static linkage with effective loader inputs | CA-04. Non-system injected/overridden images are not covered by the OS/vendor exception. |

## Supplemental lens - Input closure

| Surface | Check | Result |
|---|---|---|
| Python static and dynamic imports | Require all executable package files or explicit refusal | CA-02. Parent/submodule and dynamic forms remain incompletely handled. |
| Node resolution | Match the selected runtime's resolution order | CA-03. The installed tsx resolver supplies a concrete conflicting order. |
| Metadata-only operation | Keep application code outside discovery execution | CA-06. Ordinary Python imports from project cwd occur before static inspection. |
| Source-qualified paths and symlinks | Reject escapes and bind canonical target contents | No new finding in inspected R/C paths. |
| Other Node selectors | NODE_OPTIONS/NODE_PATH, tsconfig extends, package configuration and nonliteral imports | T contains no general closure validation for these selectors. CA-01/CA-03 cover demonstrated selection defects; exhaustive counterexamples for these additional forms were not executed or separately established in this report. |

## Supplemental lens - Change detection

| Surface | Check | Result |
|---|---|---|
| Generation revalidation before real cache use | Trace rediscovery to `selectCandidates` | T:1377-1397 and Run:674-685 have the required ordering. |
| Stable fingerprints | Change bytes without changing version/probe output | Represented file bytes invalidate. Omitted shim/helper/dependency bytes can remain invisible, CA-01–CA-05. |
| Discovery memoization equivalence | Compare every consumed context with the cache key | CA-07. Generation rollover repeats the same incomplete equivalence relation. |
| Cache namespace/resource selection | Bind configured namespaces and retain locks through execution | T:1403-1448 and Run resource callsites inspected; global locking semantics and all upstream cache selectors remain separately reviewable. |

---

## Finding list (consolidated)

| ID | Lens | Severity | Surface | Intent ref | Code ref | Summary | Fix |
|---|---|---|---|---|---|---|---|
| CA-01 | commitment-coverage | Major | Node installed execution chain | D I11 (`D/docs/intent.md:25`); V4:235,245-247 | T:789-845,1330-1355; C:512-513; `D/packages/mobile-client/node_modules/.bin/tsx:1-21`; D policy:530-554 | The adapter hashes PATH-selected Node and package directories, but never resolves or hashes the executable `pnpm exec tsx` actually selects. The inspected installed shim is outside those roots. It invokes shell helpers, sets NODE_PATH to additional absolute locations, and prefers a neighboring `.bin/node` over PATH Node. `[INFERENCE]` changing this shim or adding its preferred Node between runs can change execution while the recorded package/runtime identity stays unchanged. | Resolve the actual pnpm exec command, attest its shim and interpreter/helper chain, validate its package entrypoint, and bind the effective Node and search paths. Reject unrecognized shim forms without executing application code. Add replacement and adjacent-Node regression cases. |
| CA-02 | commitment-coverage | Major | Python import closure | D I11; V4:229,245-247 | T:501 (`resolve`, `scan`, `visit`),516-531,1296-1325 | The embedded analyzer does not fail closed for executable imports it cannot resolve. A call such as `importlib.import_module(name)` or `__import__(name)` can become UNKNOWN or an ignored expression without a requirement. `from pkg import sub` resolves only `pkg`; dotted resolution walks parent search locations but visits only the final origin. Empty package initializers therefore need not expose the submodule/parent code to the scan. `[INFERENCE]` undeclared installed Python code can affect a recipe or checker without affecting its identity. | Resolve supported literal dynamic imports, parent initializers and from-list submodule imports. Reject unresolved import mechanisms/dataflow and unsupported path/import-hook mutations. Require explicit content coverage for every executable nonstdlib input; test unknown dynamic imports and empty-initializer packages. |
| CA-03 | commitment-coverage | Major | Node/tsx resolver equivalence | D I11; V4:226,235,247 | T:173-215,820-833; `D/packages/mobile-client/node_modules/tsx/dist/register-D46fvsV_.cjs:3` (`mapTsExtensions`, `resolveTsFilename`, `createTsExtensionResolver`) | Discovery tests the literal relative path before its `.ts` replacement. The selected tsx 4.20.3 resolver tries TypeScript substitutions first for TypeScript parents: its `.js` mapping starts `.ts`, `.tsx`, then `.js`. Both sibling files may exist. `[INFERENCE]` a `.js` file with no imports can be scanned while runtime loads the sibling `.ts` that imports an installed devDependency. The adapter adds ordinary project dependencies but only discovered devDependencies, so that selected dependency's bytes can be omitted. | Use a reviewed static resolver matching the bound tsx implementation, or reject ambiguous candidates. Enumerate dependencies from the actually selected source. Test coexisting `.js`/`.ts` siblings where only the runtime-selected file imports an external devDependency. |
| CA-04 | commitment-coverage | Major | Darwin effective native linkage | D I11; V4:234,239,245-247 | T:565-783, especially 722-761; environment acceptance at `F/tools/evidence-v4/evidence-v4-model.ts:865-879` | Darwin discovery derives dependencies from load commands/rpaths without rejecting or interpreting DYLD insertion/library/framework override variables. Generic policy permits these names. Hashing the environment string binds a path, not the bytes of a selected override. `[INFERENCE]` a reviewed policy carrying DYLD_INSERT_LIBRARIES or an effective DYLD_LIBRARY_PATH can execute non-system code omitted from the manifest. D's current environment allowlist does not carry these variables; this is a generic producer gap, not an exercised Dossier exploit. | Reject unsupported DYLD selectors before any probe, or resolve and attest every effective inserted/overridden image and configuration under the selected executable context. Preserve the narrower system-library exception. |
| CA-05 | commitment-coverage | Major | Metadata helper provenance | D I11; V4:237,239,243-247 | T:659-674,773-776,545-551,844-847,1145-1150,1024-1034,1079-1085 | Probe executable bytes enter only an internal memoization key. Retained discovery entries contain command/output/status, not those bytes. Non-system otool is added as a drivers root, but Python, Node and reserved-producer wrappers retain only native non-system-library roots and drop it. PATH-selected plutil is probed without adding a root at all. `[INFERENCE]` helper replacement producing the same output is invisible to persisted identity/revalidation, and helper runtimes are not generally closed. | Retain helper executables and their runtime/native closure in the appropriate virtual manifests or explicit required declarations. Do not discard discovery-driver roots when composing adapters. Test a same-output helper replacement and an external helper interpreter/library change. |
| CA-06 | clause-to-line | Major | Metadata-only Python preflight | D I11; V4:165,226,237; assignment's prohibition on executing project application code during metadata interpretation | T:448-469,500-509 | Import-path probing runs `python -c 'import json,sys; ...'` in each application cwd; the analyzer likewise imports ordinary module names before it inspects application sources. For non-isolated subjects, cwd participates in Python import resolution. `[INFERENCE]` a project `json.py`, `ast.py` or startup module can execute during plan/discovery, before its closure is established, even if validation later fails. `-B` only prevents bytecode writes. | Bootstrap helper imports from an attested isolated runtime context, then inspect the subject's actual search/startup configuration as data. Reject startup/import-hook behavior that cannot be established statically without executing project code. Add a shadow-module sentinel regression proving plan does not execute it. |
| CA-07 | clause-to-line | Major | Adapter discovery memoization | D I11; V4:229,237,247 | T:1093-1123,1185-1221,1296-1301 | Python discovery consumes declaration ID/requires and all recipe, preflight and checker command contexts. The adapter cache key includes only locator, environment and recipe command/cwd contexts. Two Python declarations with the same locator and no recipe contexts, but different preflight/checker callers, reuse the first result. Its embedded requirement IDs also remain those of the first declaration. `[INFERENCE]` the second script's imports can avoid discovery entirely, and revalidation repeats the same aliasing each generation. | Key discovery by every semantic input it consumes, including command contexts, dependency scope and relevant recipe metadata, or separate shareable runtime discovery from per-caller application analysis. Add two-declaration tests with distinct preflight/checker imports and requires closures. |

## Summary

- Total findings: 7
- By severity: Critical=0 Major=7 Minor=0 Informational=0
- By lens: commitment-coverage=5 clause-to-line=2 deferred-cannot-silently-succeed=0 who-controls=0 field-name=0 deferral-justification=0
- Recommended next step: first bind the actual pnpm/tsx shim/runtime chain and correct Python/Node dependency resolution (CA-01–CA-03); then close Darwin loader and helper provenance (CA-04–CA-05); isolate Python metadata execution and repair discovery equivalence (CA-06–CA-07). The parent should add the named negative/positive controls, run the existing v4 toolchain/schema/cache/portable suites once after integration, and repeat the real Dossier factory plan/resume exercise without reducing commands or proof budgets. Keep fresh canonical evidence collection and production activation separate.