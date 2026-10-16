# Code-adversarial review: dossier v4 proof-toolchain adapters - 2026-10-15

- Operator: fv-code-adversary via OMP task (NOT V4ProofToolchains or the integrating parent who authored ApalacheJsonLimits.java)
- Code commit reviewed: `aa6946f29f6bc893cba62d58ef99efdc6d5a8716`; consumer commit `1fc3294437c294b040bc606aaa177334b8e41b8c`. Commit attribution and frozen-worktree correspondence are caller supplied; no Git commands were executed.
- Intent version reviewed: no frontmatter version. Canonical target is `D/docs/intent.md`, resolved from `D/.fv/dispatch.json`, including the 2026-10-14 I11/I12 revision.
- Ledger version reviewed: no frontmatter timestamp; body declares Updated `2026-10-08`.
- Lens pack: evidence provenance and installed-tool closure, supplementing the six crypto/enclave lenses with loader, transitive-dependency and selector-boundary analysis.
- Lenses applied: 1 through 6, followed by the three requested supplemental lenses.

## Scope, references and evidence limits

Path aliases:

- `D` = `/Users/mv/Development/burnt/dossier-wt/evidence-perf`
- `F` = `/Users/mv/Development/reliq-fv-wt/evidence-perf`
- `P` = `F/tools/evidence-v4/evidence-v4-toolchain-proof.ts`
- `M` = `F/tools/evidence-v4/evidence-v4-lake-metadata.lean`
- `J` = `F/tools/evidence-v4/ApalacheJsonLimits.java`
- `TC` = `F/tools/evidence-v4/evidence-v4-toolchain.ts`
- `COMMON` = `F/tools/evidence-v4/evidence-v4-toolchain-common.ts`
- `V4` = `F/docs/execution-evidence-v4.md`
- `Q` = `/opt/homebrew/Cellar/quint/0.33.0/libexec/lib/node_modules/@informalsystems/quint/dist/src`
- `L` = `/Users/mv/.elan/toolchains/leanprover--lean4---v4.33.1/src/lean/lake/Lake`

The normative dependency contract is V4, with caller-supplied SHA-256 `825a053c2d3ba511a5f32f03168239fa24d5221195cb238865a9a1dc2ba7c0e2`. This review did not recompute that digest or invent a separate F intent.

The reviewed surface is installed Quint/Node/evaluator/Apalache/JVM selection and closure, Lean/Elan/Lake selection and metadata, and their integration into tool and cache identities. Relevant installed Quint 0.33.0 and Lean 4.33.1 sources were read to check actual dependency semantics.

Four grounded gaps were found in supported adapter configurations. The inspected D configuration uses `lake build`, a simple TOML library with no packages, and default Apalache verification. The counterexamples below are not claims that those alternative configurations occur in the current D policy. They concern F's accepted adapter surface and its fail-closed closure obligation. No current D evidence artifact was demonstrated to have been incorrectly reused.

No tests, builds, gates, formatters, shell commands, edits, report-file writes or live operations were performed. The parent's reported Linux/Darwin suites, gates, public-factory exercises, collector exercise and READY plan remain caller-reported evidence. They were not rerun and do not exercise the specific counterexamples below. The reported bootstrap class reproduction and isolated invPS7 depth-4 success are accepted with their stated scope; neither is a canonical D collection.

Assumptions retained: approved conforming child lifecycle, no concurrent external mutation, upstream build/cache integrity, complete trusted retained history, producer/operator honesty and OS/compiler authenticity. The counterexamples require neither concurrent mutation nor poisoned generated caches: an omitted dependency can change between completed invocations. This review does not establish cryptographic producer authentication, model-to-code refinement, actual served-route independence or production activation. Multiple same-family reviewers are not multi-family attestation.

Important uncovered classes include general authorization, concurrency and recovery, arithmetic, reentrancy, resource exhaustion, storage error atomicity, migration and supply-chain authenticity. Native ownership, immutable history, member observations, portable assessment and dashboard behavior remain separate review surfaces.

---

## Lens 1 - Commitment coverage

| Commitment | Attacker DoFs | Bound by | Gap |
|---|---|---|---|
| Quint distribution and installed Node packages | Installed CLI, dependencies, optional/peer dependencies, interpreter | `P:124-159,303-326`; recursive package roots at `COMMON:494-536`; content digest at `TC:1255-1269` | No specific omission established for the inspected default Quint package graph. This is content identity under operator trust, not package authenticity. |
| Native evaluator | Package-selected version, QUINT_HOME, selected executable and native linkage | Selection probe `P:251-266`, installed-file check and native discovery `P:375-397`; actual selector `Q/rust/binaryManager.js:25-44` and `Q/config.js:29-45` | No specific gap established in the inspected absolute-path default selection. |
| Apalache selected JAR and bootstrap | APALACHE_JAR path/bytes, manifest entrypoint, classpath/index delegation, bootstrap bytes | Selected JAR root and eligibility checks `P:419-448`; manifest restrictions `P:175-242` | Prior external Class-Path route is explicitly rejected. Bootstrap bytes must equal the fixed class digest. Arbitrary verifier implementation correctness is not established by these checks. |
| JVM distribution | PATH-selected Java, java.home, distribution files, linked roots, guarded environment overrides | `P:450-475` | Standard selected distribution is recorded. Loader-bearing TLC configuration is a separate uncovered input, CA-03. |
| Lake source/module closure | Package and library source-directory selection; source files outside package/project roots | Metadata omits source directories and module inventory (`M:35-70`); package roots use package directories (`P:905-922`); final search-path check covers initial environment paths only (`P:936-939`) | CA-01: configured external module sources can be absent from both source and tool identities. |
| Lake native input closure | Library/executable target link objects and typed dependency targets | `M:62-68` checks package-level link targets and selected declaration kinds, then emits only argument arrays; `P:801-802,940-985` trusts that projection | CA-02: library-level link-object dependencies can survive the rejection test without being enumerated. |
| TLC JVM configuration | `--tlc-config` contents, especially maxHeap/stackSize selecting an agent or argument file | Configuration file itself is hashed at `P:398-402`; deeper validation runs only for apalache-config at `P:403-416` | CA-03: the selected JVM dependency can remain unbound even though the JSON configuration is bound. |
| Effective Lean distribution identity | Recipe-specific `+toolchain` and actual entry executable | Distribution is selected from the declaration at `P:648-650`; application comparison at `P:692-706` omits toolchain and executable selection | CA-04, primarily lens 2: the committed distribution can describe a different runtime from the recipe. |
| Cache namespace identity | Effective build, library, binary, IR, configuration and artifact-cache directories | `P:882-935`; canonical selected-path hashing at `TC:1403-1448` | Namespace binding does not repair omitted source/tool inputs in CA-01, CA-02 or CA-04. Generated-product integrity remains the declared upstream assumption. |
| Discovery stream hashes and configuration-path labels | Probe output, configuration paths and selected metadata | `P:81-86`; retained probe identities and tool-selection comparison at `TC:1079-1091,1369-1398` | Hashing metadata cannot cover dependency bytes that the metadata never identifies. No collision attack is alleged. |

## Lens 2 - Clause-to-line discharge

“Partial” below includes explicitly out-of-slice obligations. It does not convert missing boundaries into a finding or a successful system verdict.

| Clause | Expected discharge | Actual code line | Status |
|---|---|---|---|
| D I11: current dependency closure and complete tool provenance (`D/docs/intent.md:25`) | Identify all consumed installed and source dependencies before reuse | `P:398-416,642-706,905-985`; `M:35-70` | partial: CA-01 through CA-04 |
| D I11: unsupported closure prevents PASS | Reject unresolved source/native/runtime selection | `P:801-802` rejects only what the helper reports; `M:62-68` has incomplete coverage | gap for CA-01/CA-02; partial overall |
| D I12: exact recipe and complete dependency closure (`D/docs/intent.md:32`) | Bind the runtime actually selected by each recipe without changing argv or proof bounds | `P:327-342,648-706`; `TC:1097-1123,1327-1352` | partial: CA-04; binding the entry launcher alone does not bind the selected Lean distribution |
| D I13: scoped evidence does not activate deployment (`D/docs/intent.md:33`) | Preserve separation between tool readiness, scoped execution and activation | Adapter returns metadata at `P:476,986`; no activation action in the primary files | discharged within this slice; final activation enforcement is outside it |
| D I14: no deployment or runtime authority (`D/docs/intent.md:34`) | No live deployment, credential or chain action | Primary files perform tool discovery and bootstrap delegation only | discharged within this slice |
| V4 S1: all logical slots retained (`V4:15`) | Full plan/final assessment membership | No slot-expansion implementation in primary files | partial: delegated boundary, not reviewed here |
| V4 S2: complete matching execution identity (`V4:16`) | Sharing/reuse must include actual tool closure | Tool digest constructed at `TC:1255-1269` from adapter roots | partial: omitted inputs in CA-01 through CA-04 |
| V4 B1: real completed invocation and admissible provenance (`V4:17`) | Provenance prerequisites fail closed before evidence becomes eligible | Installed-file checks `P:26-36`; JAR rejection `P:198-242`; Lake rejection `P:801-802` | partial: closure gaps remain; invocation/artifact/history completion is outside this slice |
| V4 B2: stale work cannot become PASS (`V4:18`) | Changed consumed inputs invalidate reuse | `TC:1369-1398` reconstructs and compares supplied identities | partial: reconstruction cannot detect omitted dependencies |
| V4 T1: stop dispatch and durably account for in-flight work (`V4:19`) | Scheduler and store enforcement | Not implemented in primary files | partial: separate native/store review |
| V4 T2: ownership and endpoint assumptions (`V4:20,163-167`) | Refuse unidentifiable services; do not claim continuous immutability | Endpoint rejection at `P:275-300`; shared resource requirement at `P:354-371` | partial: local service guard inspected; lifecycle/recovery and continuous nonmutation are not proved |
| V4 actual adapter selection (`V4:227,231,234`) | Resolve the actual selected backend and Lean/Lake distribution | `P:303-397,578-650,692-706` | partial: CA-04 |
| V4 complete non-system/transitive closure (`V4:239,243-245`) | Hash dependencies or reject unsupported arrangements | `P:398-475,801-985`; `M:62-68` | partial: CA-01 through CA-03 |
| V4 generated-cache boundary (`V4:167-179`) | Bind selection/configuration while disclosing upstream integrity | Cache namespace collection `P:882-935`; `TC:1403-1448` | partial: namespace construction inspected; upstream integrity remains assumed |
| Ledger TA-08 (`D/.fv/ledger.md:441`) | Preserve unsigned-producer/operator trust limitation | Content hashes at `TC:1269` and bootstrap equality at `P:240-241` provide no producer authentication | partial by explicit trust boundary |
| Ledger C-01 through C-09, C-14 and C-15 | Supply bounded tool execution provenance without claiming composition/refinement | Adapters identify tools; they do not discharge candidate conjunctions | partial: ledger's INCOMPLETE statuses remain |
| Ledger C-10 through C-13; TA-01 through TA-07 and TA-09 through TA-17 | Protocol, enclave, chain, custody and deployment assumptions | No primary enforcing line in these toolchain files | partial: outside this slice; no discharge claimed |
| D I1-I10, RS1-RS6, S1-S7, B1-B19/B2t/Q-B19, PV1-PV5, PS1-PS7 and PB1-PB12 | Their protocol/runtime/evidence-specific enforcement remains in the named components | No implementation review of those components in this assignment | partial: outside this slice; no new protocol finding inferred from absence here |

## Lens 3 - Deferred cannot silently succeed

| Branch | Reachable from | Behavior | Status |
|---|---|---|---|
| TODO/deferred/stub/mock/not-yet-implemented branches in P, M and J | Production adapter/bootstrap entry points | Targeted search found no such branches | Empty deferred-success finding set for the primary files |
| Unknown Quint subject/backend or unidentified interpreter | `identifyQuint` | Throws at `P:145-159,303-306,339-342,376-379` | Explicit rejection |
| Missing installed evaluator/backend or invalid selected JAR | `identifyQuint` | Requires real installed files; manifest/bootstrap failures throw (`P:395,419-448`) | Explicit rejection; discovery does not repair the installation |
| Missing selected Lean toolchain or unresolved reported native target | `identifyLean` | Throws at `P:619-625,665-666,801-802` | Explicit rejection, with CA-02 limiting the completeness of the native-target report |
| Bootstrap | Java main | Changes Jackson's string constraint and calls Apalache main (`J:5-9`); no fabricated success marker | No deferred verifier implementation |

## Lens 4 - Who controls

The primary files return identity metadata rather than persist a separate state machine. These fields feed persisted ToolIdentity and BuildCacheIdentity through TC.

| Field | Supplier | Validation | Gap |
|---|---|---|---|
| ToolIdentity id/kind/locator/requires | Reviewed policy | Declaration lookup and closure selection (`TC:1175-1189,1280-1291`) | General policy authorization and graph validation are outside this slice |
| files/digest | Installed filesystem plus adapter root selection | Regular-file/type checks, root hashing, canonical tool digest (`P:26-36`; `TC:1255-1269`) | CA-01/CA-02 omit consumed inputs; CA-04 can select the wrong runtime |
| packages | Adapter | Both proof adapters return `[]`; non-Cargo families use rooted file manifests (`P:476,986`; `V4:225`) | No field-contract gap |
| version and discovery | Actual supervised probes | Exit/stream provenance retained by TC; content and selection compared on revalidation | Completeness depends on selecting the right probes and roots |
| system_dependencies | Producer OS plus native discovery | OS/arch/release and SDK metadata at `TC:1260-1267` | OS/vendor authenticity remains trust |
| APALACHE_JAR and manifest fields | Sanitized environment and installed JAR | Exact selected-file binding, closed manifest attribute set, fixed entrypoints and bootstrap hash (`P:175-242,430-448`) | No remaining instance of the prior Class-Path override defect found in this path |
| TLC maxHeap/stackSize | Reviewed configuration file | File is hashed, but values are not constrained as JVM memory options (`P:398-416`) | CA-03 |
| Lean toolchain selection | Declaration, recipe, Elan settings and environment | Selection precedence at `P:578-638`; incomplete recipe comparison at `P:692-706` | CA-04 |
| Lake name/dependencies/dependencyOptions/configuration paths | Installed Lake evaluates the workspace configuration | Metadata shape and dependency-name checks, package-lock traversal (`P:760-879`) | CA-01/CA-02 concern omitted configuration semantics, not forged JSON |
| cache namespace roles and paths | Lake metadata plus deterministic adapter role construction | `P:882-935`; canonical namespace identity at `TC:1427-1448` | Namespace identity does not establish source closure or independently verify generated products |
| unresolvedNativeTargets | Metadata helper's projection of Lake configuration | Boolean checked at `P:801-802` | CA-02: supplier omits target-level link inputs |

## Lens 5 - Field-name fidelity

| Field | Implied semantic | Actual value | Status |
|---|---|---|---|
| `mainClass`, `bootstrapEntry` | Selected manifest entrypoint and optional reviewed bootstrap class entry | Parsed supported Main-Class and corresponding constant (`P:233-237`) | faithful |
| `APALACHE_BOOTSTRAP_HASH` | Exact admitted compiled bootstrap bytes | Fixed SHA-256 checked after extracting that class (`P:178,240-249,440-444`) | faithful; source/class reproduction is parent-reported |
| `configurationOptions` | Effective Lake configuration options | Cached trace options when applicable, otherwise requested options (`M:16-27,39`) | Consistent with inspected Lake option reuse at `L/Load/Lean/Elab.lean:264-298`; malformed traces reject conservatively |
| `dependencies`, `dependencyOptions` | Direct package dependencies and supplied configuration options | `pkg.depConfigs` (`M:50-52`) | faithful within that projection |
| `buildDirectory`, library/binary/IR/cache fields | Effective selected directories | Lake package/environment accessors (`M:40-49`) | faithful as paths; no generated-byte correctness claim |
| `nativeArguments`, `targetArguments` | Native/Lean argument arrays | Package and library/executable argument fields (`M:60-68`) | faithful as arrays, incomplete as dependency analysis; CA-02 |
| `unresolvedNativeTargets` | Whether unsupported callable/native dependencies remain | Tests package-level link targets and anonymous/ExternLib declarations only (`M:62`) | Semantically incomplete for library-level link objects, CA-02; counted once under lens 1 |
| ToolIdentity `digest` | Digest of recorded content identity | `D("tool-content", {kind,files,packages,system_dependencies})` (`TC:1269`) | faithful hash construction; closure completeness is separately defective |

## Lens 6 - Deferral justification audit

| Deferred finding | Justification claims | Claim audit | Verdict |
|---|---|---|---|
| Prior APALACHE_JAR external Class-Path finding, `D/.fv/attacks/2026-10-15-apalache-environment-review-1.md:3-37` | Selected external JAR dependencies were not closed; round 2 reports explicit rejection and exact bootstrap admission | Current `P:206,225-226,430-444` rejects JAR index/Class-Path delegation and applies bootstrap-byte equality to the selected JAR | Correction is present in the inspected Apalache path; no wrong-deferral finding |
| Round-2 limit on arbitrary replacement verifier bytecode, `D/.fv/attacks/2026-10-15-apalache-environment-review-2.md`, “Unbound bytes and native closure” | Approved tool behavior and operator honesty remain trusted; manifest checks do not prove arbitrary bytecode dependency behavior | `V4:245` permits empty extra digest pins; current JAR checks establish supported packaging, not general Java behavior | Valid stated limit. CA-03 uses the installed TLC implementation's configuration path, so it is a distinct supported-selector gap |
| External inventory completeness in portable review 3, `D/.fv/code-adversarial/2026-10-14-v4-portable-review-3.md:99-105` | Portable manifests lack independent external archive preimages; complete enumeration remains producer responsibility | Current adapters are that producer-side construction boundary; CA-01 through CA-04 identify omissions there | Deferral of independent portable reconstruction remains justified; it does not waive producer completeness |
| Mechanized composition, production activation and producer authentication | Ledger retains INCOMPLETE/stale evidence and TA-08 | Tool identification and bootstrap delegation supply none of these missing artifacts | No wrong-deferral finding; outstanding boundaries remain outstanding |

No additional deferred prior finding specific to these proof adapters was identified in the inspected records. Earlier host/portable closures are not re-certified by this slice.

## Supplemental lens - Loader boundaries

| Loader boundary | Inspection | Result |
|---|---|---|
| Quint Node entry and startup | Shebang resolution, installed package bin equality, package dependency traversal and NODE_PATH/NODE_OPTIONS guard (`P:124-159,303-326`) | Default installed route is grounded. This is not a universal Node loader audit. |
| Apalache JAR loader | Case-insensitive attributes, continuation handling, unique required entries, no named sections, no Class-Path/index/unknown loader attributes (`P:198-237`) | Prior counterexample is rejected by source. Unsupported Multi-Release and launcher-agent arrangements are outside the allowlist. |
| Reviewed Jackson bootstrap | `J:5-9` rebuilds default StreamReadConstraints, changes only maxStringLength to 67,108,864, then forwards the original args to Tool.main | No proof bound, invariant, seed or sample reduction in this source. Exact compiled-class equality is enforced by `P:240-249,440-444`. |
| TLC Java startup | Installed TLC inserts configuration-provided maxHeap/stackSize directly into Java argv (`Q/tlc.js:111-126`) | CA-03: loader-bearing values bypass the adapter's environment-only JVM guard. |
| Lean native/module loader | Explicit argument plugins are handled at `P:940-960`, but typed target dependencies and effective source paths are incompletely projected | CA-01/CA-02 |

## Supplemental lens - Transitive dependencies

| Boundary | Inspection | Result |
|---|---|---|
| Quint package to Node packages | Required, peer and optional dependency traversal, rejecting missing required packages and ambiguous name/version roots (`COMMON:494-536`) | No specific default-package omission established |
| Quint to evaluator/Apalache/JVM | Package-provided selection and installed-file checks; native roots and JVM symlink dependencies (`P:375-475`) | Default paths inspected; general closure remains limited by CA-03 |
| Lake manifest to package configuration | Reverse direct-dependency order with breadth-first expansion (`P:839-879`) matches inspected Lake order (`L/Load/Resolve.lean:190-218`) | No ordering defect established |
| Lake package to actual module files | Lake derives source paths from package/library srcDir (`L/Config/Package.lean:351-357`, `L/Config/LeanLib.lean:33-39`, `L/Config/Module.lean:86-90`) | CA-01: these effective paths are absent from the adapter projection |
| Lake library to external object inputs | Built-in input_file returns its configured path; library builds fetch moreLinkObjs (`L/Build/InputFile.lean:25-27`, `L/Build/Library.lean:89,131-136`) | CA-02: no custom target or extern_lib declaration is needed for this route |
| Adapter to portable consumer | Consumer receives the producer's recorded closure | Omitted external bytes cannot be recovered from their absence. No consumer patch or new schema is required merely to reject unsupported producer arrangements. |

## Supplemental lens - Selector boundaries

| Selector | Inspection | Result |
|---|---|---|
| APALACHE_JAR absent/empty/nonempty | `P:430-434` selects and hashes the override or default; D inherits and identities the variable (`D/.fv/execution-policy.json:37-75`) | No new current-D unset/empty defect established |
| Quint backend/version/config | Backend allowlist and package selection (`P:339-342,375-416`) | TLC is admitted, but its executable-bearing configuration is not closed, CA-03 |
| Lean declared subject versus recipe | `selectedLean` uses declaration subject; application equality checks only cwd/configuration/-K options (`P:648-650,692-706`) | CA-04 |
| Lake source and native target selectors | Installed Lake exposes more selection mechanisms than M serializes | CA-01/CA-02 |

---

## Finding list (consolidated)

| ID | Lens | Severity | Surface | Intent ref | Code ref | Summary | Fix |
|---|---|---|---|---|---|---|---|
| CA-01 | commitment-coverage | Major | build-pipeline / Lake source closure | D I11 (`D/docs/intent.md:25`); `V4:155-159,234,243-245` | `M:35-70`; `P:905-922,936-939`; actual source semantics `L/Config/Package.lean:351-357`, `L/Config/LeanLib.lean:33-39`, `L/Config/Module.lean:86-90` | Lake package/library srcDir can select module sources outside the package and project, but metadata contains neither effective source roots nor module inputs. The adapter hashes dependency package directories and checks only initial environment search paths. [INFERENCE] With an unchanged configuration pointing outside those roots, changing only an external module between invocations can leave the reusable identity unchanged. | Extend metadata to identify effective library/module source roots and consumed imports; require coverage by the verified source closure or an explicit installed-package root. Reject escaping/unsupported source layouts before reuse. |
| CA-02 | commitment-coverage | Major | build-pipeline / Lake native closure | D I11 (`D/docs/intent.md:25`); `V4:227,239,243-245` | `M:62-68`; `P:801-802,940-985`; `L/Config/LeanLib.lean:229-242`; `L/Build/Library.lean:89,131-151`; `L/Config/InputFile.lean:17-22` | unresolvedNativeTargets checks package-level moreLinkObjs/moreLinkLibs, but omits those fields on Lean libraries/executables. A library can reference a built-in input_file outside the recorded roots through moreLinkObjs; that declaration is neither anonymous nor ExternLib, and its bytes are not in the emitted argument arrays. [INFERENCE] Changing that object between invocations can evade the tool identity and permit stale reuse. | Apply the unresolved-target check to effective package and target configurations, including typed link/plugin/dynlib dependencies. Either enumerate their exact installed/input closure or reject them. Cover built-in input-file-backed objects, not only custom target declarations. |
| CA-03 | commitment-coverage | Major | build-pipeline / Quint TLC JVM loader | D I11 (`D/docs/intent.md:25`); `V4:227,231,239,243-245` | `P:339-342,398-416,454-464`; installed consumer `Q/tlc.js:105-126` | The adapter admits backend tlc and hashes tlc-config without inspecting it. Installed Quint passes maxHeap and stackSize directly as Java arguments. A value such as maxHeap=`-javaagent:/outside/reviewed-agent.jar` selects an external executable dependency that is absent from the roots and is not covered by the environment-variable guard. [INFERENCE] Replacing only that agent between invocations can leave the descriptor unchanged. | Validate the selected TLC configuration against its actual grammar. Restrict memory fields to supported memory-option forms, or explicitly resolve/hash any permitted loader-bearing dependency; reject unsupported JVM argument-file/agent selections. |
| CA-04 | clause-to-line | Major | cross-layer / Lean selector identity | D I11/I12 (`D/docs/intent.md:25,32`); `V4:227,234,243-245` | `P:527,578-638,648-650,692-706`; `TC:1097-1123,1327-1352` | The declaration selects one Lean distribution, while application validation ignores the recipe's parsed toolchain and actual executable. A declaration for lake build under toolchain A and a recipe `lake +B build` with the same cwd/configuration/-K options pass that comparison. The common launcher can still satisfy assertCommandBound. [INFERENCE] The execution can use B while its recorded libraries/compiler are A, and later changes to B can escape revalidation. | Resolve each applicable recipe/check's actual entry and complete selection tuple. Reject mismatches with the declaration or construct identities for every distinct supported context. Include toolchain, executable and reconfigure semantics; do not rewrite recipe argv. |

### Counterexample and impact qualifications

1. CA-01 is an input-enumeration defect. Falling back to all repository verified inputs cannot cover a module outside that repository. A successful Lake build would not establish closure completeness, and upstream cache integrity does not bind a source file omitted before Lake is skipped.
2. CA-02 uses Lake's ordinary built-in input_file and library link-object machinery. `L/Build/Library.lean:89` fetches those objects for static libraries, and `:131-151` fetches them for shared libraries. The helper's rejection predicate does not cover that target-level field. No malicious replacement compiler is required.
3. CA-03 uses the installed Quint implementation, not an invented replacement JAR. The supplied agent may be an ordinary approved instrumentation dependency; its executable bytes still require identity. The current D recipes do not select TLC, so this does not reopen the exact APALACHE_JAR policy-delta finding.
4. CA-04 needs a recipe-specific selector different from its adapter declaration. The current inspected D Lean recipe and declaration both use `lake build`; that concrete D pair does not demonstrate the mismatch. The generic adapter nevertheless accepts the mismatch rather than rejecting unsupported closure.

These are static, source-grounded counterexamples. Their full factory/cache effects have not been executed in this review. No claim is made that the existing canonical D store contains an affected success.

## Summary

- Total findings: 4
- By severity: Critical=0 Major=4 Minor=0 Informational=0
- By lens: commitment-coverage=3 clause-to-line=1 deferred-cannot-silently-succeed=0 who-controls=0 field-name=0 deferral-justification=0
- Recommended next step: (1) close or reject Lake external module-source layouts; (2) close target-level native input dependencies; (3) constrain or attest TLC JVM configuration; (4) compare actual Lean selectors across every applicable context. Parent-owned acceptance should then exercise unchanged-key attempts after changing only each omitted dependency, a `lake +B build` mismatch, the corresponding rejection/identity-change controls, and unchanged default D/Apalache/bootstrap behavior. Retain exact proof commands, models, seeds, samples and depths. Re-review the corrected slice before treating installed-tool closure as discharged.