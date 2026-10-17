# Change record: execution evidence v4 contract

- Date: 2026-10-14
- Classification: intent-touching. The opt-in producer changes artifact ownership, execution reuse, failure/checkpoint lifecycle and producer/checker trust boundaries. Existing v3 behavior is preserved.
- Compatibility posture: established.
- Authority: the user-authorized measured evidence-performance scope. FV has no project intent document; the additive behavior is specified in `docs/execution-evidence-v4.md` rather than silently revising a prior evidence format.
- Worktree: FV `evidence-perf`, base `1333d16`. Original FV and the Dossier `combined` worktree are outside this change; their running old-format collection is untouched.

## Contract delta

`docs/execution-evidence-v4.md` defines the reviewed policy, versioned native/factory call, canonical hashing bytes, source/environment/tool identities, execution descriptors and immutable execution/claim/run artifacts. It specifies deterministic sharing, early full-policy preflight, atomic checkpoints, selective resume, scoped freshness and bounded independent scheduling with default jobs two. Unclassified/nonfixed-random repetitions remain distinct. Matching output cannot authorize artifact substitution.

The existing factory signature remains callable. V3 keeps its pi.exec transport unchanged; native v4 owns the real POSIX subprocess supervisor, sanitized environment, deadlines, process groups, byte capture and cancellation for evidence and checker/probe calls. It requires no on_spawn extension from ordinary OMP and permits no caller-supplied fake execution fallback.

Source closure is transitive and reviewed; unknown closure falls back to all verified inputs. Global inventory, policy/intent/manifest/claim definitions and clean endpoint state remain bindings. Detected drift, symlinks and dirty inputs fail closed; scans do not prove absence of ABA. Nonmutation, upstream generated-cache integrity and retained-store completeness are explicit trust. Actual producer/transitive verifier and selected native compiler/linker identities are attested, with a bounded OS/vendor package-integrity boundary. Primary environment identity is hash-only; reviewed public existing collector fields and reserved control-only ownership transport are scoped exceptions.

Local cache revalidation compares actual installed tools/environment. Portable checking compares recorded producer provenance under policy and recomputes current source/artifact/claim bindings without requiring Darwin tools on Ubuntu. The observation checker has a bounded file-request/file-response protocol; every shared member retains separate named/nonvacuity/collector checks. Cached collector freshness compares to the original immutable execution interval, never a later claim aggregation time.

Every success checkpoints before later work; failures, missing work, cancellation, corrupt caches and publication errors cannot become PASS. Ownership is explicit and recoverable only for a proven dead unchanged owner. Resource conflicts serialize, replay is exclusive, and first failure halts admission of new work. Exact selection cannot narrow the final required policy or canonical activation assessment. A dashboard that only reads records reports `binding=not-recomputed` and separates logical associations from actual physical invocations.

`docs/incremental-reverification.md` and `CONCEPTS.md` explicitly scope their existing whole-snapshot, unique claim-artifact and no-partial-cohort-reuse rules to v3, then describe the separate opt-in v4 behavior. The ledger envelope and existing v3 API, defaults, truth tables and artifacts are unchanged. Prior review files remain immutable.

## Dossier boundary

The peer-owned Dossier policy adopts the contract's field shapes, seven closed policy adapter families, version-probe cwd, sanitized environment identity, sorted set arrays, finite observation-check timeout and implicit producer identity. It preserves all 69 records and 108 logical claim/tool associations, exact existing argv/classes/markers, named observations, sample/step/seed budgets and activation boundaries. The policy author's inventory reports 82 physical recipes after explicit conservative sharing; this contract does not claim that any of them executed. Cargo tests, pnpm, replay and owner-specific collectors remain distinct under that policy.

## Affected verification surface

- Producer: `tools/evidence-run.ts` versioned API, real subprocess host, full preflight, fingerprints, immutable artifacts, scheduling and ownership.
- Consumer: `scripts/check_evidence_records.py` independent canonical identity/source/reference/class and final-scope validation.
- Dashboard: `scripts/coverage_dashboard.py` v4 schema fidelity, logical/physical counts and nonrecomputed freshness disclosure.
- Dossier host/checker/collectors: policy equality, 69/108 expansion, member observations, child provenance and original execution-time freshness.
- Regression constraints from immutable `.fv/code-adversarial/2026-09-15-evidence-architecture.json`: F1 per-execution class downgrade; F2 output substitution across commands/tools; F4 dashboard schema drift; F12 version-probe source mutation.
- Quint/Lean/Verus/Kani proof statements: no model, theorem, annotation, harness, seed or bound change authorized by this contract.
- Compose: claim conjunction, required tool/dependency coverage and full activation stay intact; explicit execution ownership/sharing and local-versus-portable validation are new trust edges.

## Evidence and review status

This assignment edited only the four owned documentation/change paths. No implementation file, prior review, live system or running collector was changed. No gate, test, build, lint, formatter, commit or push was run. The parent reported six baseline FV suites passing at the base; that report is accepted without rerunning and does not verify v4.

## Review-1 dispositions

Both immutable execution-v4-review-1 reports returned BREAKS. All listed general-contract findings and the Dossier native-compiler finding were accepted. This revision changes the contract and overview prose; it does not claim that a new review or implementation check passed.

| Finding | Disposition |
| --- | --- |
| FV1 / D1, older PASS masking later failure | Added globally ordered retained execution/observation/indeterminate events, current complete-history checks and canonical claim/tool cutoffs across keys/renaming/selection. Only a later actual matching invocation with relevant PASS observations is eligible. Prior bytes remain immutable; hashes do not authenticate nondeletion or an export's latestness. |
| FV2, generated build products | Bound effective cache selection/configuration/resources and declared upstream build-system/product/freshness integrity. Existing argv is preserved. No fresh compilation or content-bound generated-cache proof is claimed. |
| FV3, endpoint ABA | Replaced continuous-nonmutation promises with matching endpoint scans, detected-drift enforcement and a disclosed no-uncoordinated-mutation assumption. No OS sandbox/watch mechanism is added. |
| FV4 / D4, collector separate sessions | Specified existing private FD3/4 variable/channel, unchanged owned/released wire, gated exec after durable OS-validated ACK, lifetime spawn windows, pending-result accounting and no unproven orphan cleanup. V3 transport remains unchanged. |
| FV5 / D2, Kani application dependencies | Kani's adapter covers exact registry/git/path application and build graph/configuration under its actual pinned compiler, including native tool selection. Ambient Cargo metadata is insufficient. |
| FV6, package-root identity ambiguity | Canonical source-qualified PackageIdentity and digest root labels replace checksum interpolation. Added observed canonical byte/hash documentation vectors for the real Quartz dependency and an explicitly illustrative alternate source; these are not producer evidence. |
| FV7, directory links | Separate regular/directory/file-link/directory-link entries, canonical root-relative targets, ordinary root views, nonflattened aliases, acyclic traversal and reconstructible target-directory digests. |
| FV8 / D5, retained public environment | Primary identity stays hash-only. Exact existing collector bytes may retain only explicitly reviewed public emitted fields under per-recipe allowlists; secrets/ambient dumps and report redaction remain forbidden. |
| FV9, nested/ancestor durability | All files and every nested/modified directory are flushed bottom-up, with durable ancestor creation and same-filesystem rename barriers before acknowledgment. Supported storage semantics are an explicit boundary. |
| FV10, replacement followed by fsync error | Publication has pre-replacement, post-replacement-error and durable states. Only pre-replacement error promises the old pointer. Post-replacement error returns ERROR and declares old/new durable outcome indeterminate; pointer visibility is not publication success. |
| D3, native Cargo compiler/linker | Cargo/Kani closures include actual cc/build-script/target/config/env-selected driver/linker/wrapper/native dependencies. xcrun is used only when actually selected. SDK/system-package trust does not replace selected native binary identity. |

Shared schema changes: Policy.trust_assumptions; Recipe.build_cache/ownership_protocol/retained_environment; ExecutionDescriptor.build_cache; ToolIdentity.packages and typed directory-link entries; execution ownership/cache-after receipt; Owner children/windows/PendingResults; HistoryEvent/HistoryRef/HistoryView and claim blocking_events; RunManifest trust/history; RunResult publication state. Dossier adopted the policy fields while retaining 69 records, 108 logical associations, 82 recipe objects and exact argv/bounds/classes/markers. Source snapshots, legacy v3 calls/transport/artifacts and prior reviews were not changed.

## Review-2 bounded correction

The FV review-2 report closed the ten original findings at contract level and accepted the explicit trust boundaries, then reported a contradiction in aggregate shared-member eligibility. The parent reports Dossier review-2 SURVIVES; this author did not rerun either review.

Corrected only the quantifier and associated reuse prose: physical checkpoint validity is separate from eligibility for each canonical claim/tool association. Physical execution FAIL applies to its recorded members; observation FAIL applies only to its selected member. Complete descriptor membership and retained history remain intact. An unaffected selected association may revalidate/reuse a shared checkpoint while a blocked unselected member remains FAIL in full assessment. A selected blocked member can require one new actual shared dispatch, with every member observation retained and assessed separately. No schema, recipe argv/bound, v3 behavior or closed trust-boundary subject changed.

Added the exact EX-004 analytical acceptance trace: physical PASS10, C-01 PASS11, C-02 PASS12, C-04 observation FAIL13. C-01/C-02 may keep sequence10; C-04 cannot clear its barrier by rechecking sequence10 and needs a later actual invocation plus its own PASS observation. Selection of C-01 does not force a C-04 rerun; full policy remains FAIL. This is a required trace, not exercised evidence.

## Native lifecycle operational boundary

The parent reports that actual Darwin SDK NOTE_TRACK/NOTE_CHILD support is unavailable and that POSIX snapshots cannot prove absence of arbitrary setsid/double-fork/reparent escapes between enumerations. This observation is accepted without rerunning checks.

Added one bounded native-lifecycle trust clarification: reviewed approved commands obey declared lifecycle and do not make undeclared group/session escapes or daemonize to evade supervision. Separate-session children require explicit registered ownership; external services require independently declared identity/resource ownership. The native supervisor remains responsible for owned-group cleanup, private-pipe gates/registration, durable windows and indeterminate recovery. Observed escapes/unknown termination remain ERROR/indeterminate; foreign or ambiguously owned PIDs cannot be signaled. Arbitrary malicious/nonconforming containment is outside the producer/OS/tool trust boundary, and no sandbox is promised. Matching overview prose carries the same limit.

No policy/schema field, model, argv, bound, v3 behavior or settled trust-boundary subject changed. Independent delta review and union verification remain with the parent. No tests, builds, gates, formatters, commits or live-system operations ran for this clarification.

## Pinned no-witness Quint completion basis

Accepted the parent's implementation-source observations without rerunning checks: pinned evaluator simulator.rs outer loop205 runs 1..=samples; init failure270-280 and violation311-320 return false; errors/panics326-360 fail; whole-loop success365-371 records samples. main.rs336-349 supplies samples=nruns and explicit seed selects serial execution;591-595 maps true to Success and false to Violation. Installed commandWrapper.js300-334 rejects signal/nonzero, and cliCommands.js358-374 permits success only for native status ok. Step=false may end one trace while the outer loop continues. The no-witness CLI output exposes elapsedMs/rounded traces-per-second, not an exact count.

Narrowly qualified the observation clause: exact complete counts remain required where printed, with all witness summaries unchanged. For this reviewed pinned native no-witness path, attested tool success semantics plus exact argv and normal-zero artifact PASS may establish declared-budget completion. Observations label declared_samples, completion_basis="quint-0.33.0/evaluator-v0.7.0-ok-full-budget" and exact_count_reported=false; no observed exact count is invented. Rates/timing are diagnostic text only, never count reconstruction or heuristic budget gates. Unknown/weaker/unsupported backend semantics fail closed.

DossierV4Observations supplied the matching summary literal and pinned simulator/main blob grounding. It reports a parent-authorized v4-only binaryManager.js selector pin and confirms default Rust selection and normal-success mapping. The clause explicitly retains upstream/source-to-binary distribution honesty and actual tool attestation as trust, not binary authentication. No schema, recipe, model, seed,100000/other sample budget, step bound or v3 behavior changed. Overview text already states member-specific checks without requiring an unprinted count and is intentionally unchanged. No tests, builds, gates, formatters, commits or live-system operations ran; independent bounded review remains with the parent.

## Parent implementation checks

The actual public factory and installed OMP Zod facade completed plan, run and unchanged-input resume with the legacy execution callback set to reject use. Results were READY, PASS and PASS. The shared fixture executed once, retained the same immutable artifact on resume, and passed the portable checker with profile `producer-trusted-execution-v4`.

The complete v4 schema/source/cache/lifecycle/portable and dashboard regression batch passed on Linux arm64. Native ownership cases also passed on Darwin; compiled Bun-host execution and controlled cancellation/resume were exercised on both platforms. Linux cancellation uses a real init reaper: a diagnostic container with sleep as PID1 retained zombies and correctly could not prove group termination.

Seven existing ledger, installer, v3 producer, migration, rehearsal and example suites passed. Dossier passed 72 checker tests, eight host tests, 61 collector tests and Gate A with 322 content-bound citations. Installer refresh remained script-only; the actual OMP discovery surface contained only the two public tool factories.

Dossier host and portable-consumer reviews are closed, with reports and corrections retained in its optimization branch. Those reviews used distinct agents from the implementation authors but one provider family; they do not establish multi-family independence or review of the external native producer.

The actual complete Dossier native plan reached READY with 69 records, 108 logical slots, 82 physical recipes and 24 shared groups. Metadata captured all 41 declared tool identities plus the producer identity with the staged backend. Native producer code review and fresh canonical v4 collection remain pending. No model, recipe, seed, sample/depth bound or activation prerequisite was reduced. The original installed runtime is unchanged.

The complete Darwin regression run passed 36 of 38 suites. The two failures were the installed Quint version differing from the BOM and the current OMP registry-based settings API. Both pass targeted reruns with an isolated Quint 0.32.0 and the approved OMP/FV panel bridge. The five required CI structure gates passed. A later Linux rerun overlapped a Rust-adapter edit and is not union acceptance evidence.

Public-factory acceptance with the real OMP schema facade exercised unchanged and unrelated-content reuse, relevant-content invalidation, required-failure admission stopping and checkpoint resume. Four successful calls produced two physical executions. A three-recipe failure stopped before the third recipe; resume retained the first checkpoint byte for byte and ended with execution counts 1,2,1. Both scenarios passed the portable gate.

## Original collection diagnosis and staged backend repair

The original legacy host emitted its final FAILED verdict but remained alive after all cohort/checker calls. Its scoped report contains 44 PASS, 22 FAIL and three missing records among 69 required claims. Retained-log analysis traced the 20 leaf failures and two derived system failures to Apalache 0.62.1 rejecting the private-v2 IR at Jackson's 20,000,000-character string limit, before proof checking. The three missing records also retained ownership-pipe EPIPE errors. These outcomes were read from retained output, not rerun or reclassified as proof counterexamples.

The user subsequently authorized closing that completed host. Its PID, birth identity, parent, command and cwd were checked before SIGTERM; the existing wrapper then recorded host exit 143 and checker exit 1. Outputs and installed tools were preserved. Isolated release/crash, signal-listener, Bash/file-output and repeated forced-GC scenarios exited normally. The legacy Bun keepalive cause remains unresolved; no speculative source patch was applied.

The user approved an isolated backend fix. Compiling the unchanged model produced 49,923,516 JSON bytes. A staged launcher raises only Jackson's string limit to 67,108,864 and delegates to the unchanged Apalache main. Archive comparison retained 31,119 entries byte for byte; the only added class is the launcher, with Main-Class and Created-By manifest changes. The installed JAR was not replaced.

Staged JAR SHA-256: `68c3d272f913e2450c1ef3a714d4baefdc1854b7103cf4c88d52995bf03efbfa`. Original JAR SHA-256: `880c0b2b72354816f12e9a9755829f2907071e9a181ffea1937954c23d54739d`. Source SHA-256: `9c9e7fc0839b29839bd9430876a2ec29de785194bdd0285dbc3c6a7d0d35c65a`.

The staged backend completed `invPS7` at the unchanged four-step bound with exit zero, using a private server endpoint and the unchanged model hash `6739f855e1712e19ae142d5765556bb44f47fd4e25fc4e217447a42517223663`. This is isolated toolchain acceptance, not canonical claim evidence or production activation. Deployment still requires explicit tool/environment binding and fresh affected evidence.

## Post-commit review dispositions (2026-10-15)

Seven independent code reviews of `aa6946f` are retained under `.fv/code-adversarial/2026-10-15-*-review-1.md`. The user chose to fix findings that could let a real Dossier run reuse stale evidence and to refuse unsupported arrangements at discovery. Authors were `openai-codex/gpt-6.1-sol` task agents; reviewers were `fv-code-adversary` agents. Third-family review is outstanding.

| Slice | Disposition |
|---|---|
| Native ownership | CA-01: group signaling only for our unreaped direct child on Darwin with source-checked Bun 1.3.14 and no forced waiter thread. Birth and status are checked synchronously before `kill(-pgid)`. Every other runtime, and reaped, descendant or foreign groups, is refused with sticky indeterminate ownership. Unfinished refused children are unref'd, so the producer reports ERROR instead of hanging; they need operator cleanup. CA-02: Darwin census propagates every error except ESRCH. EPERM rows fall back to `KERN_PROC_PID` with bracketing snapshots. CA-03: gate argv grammar fixed. Cancellation now signals the direct child first and waits the existing grace before refusing survivors. |
| Producer store | CA-01: fatal observation errors stop fresh and cached member loops and admitted waiters. CA-02: recovery fsyncs the event, its directory and ancestors before retiring the pending result. The abnormal raw-output trailer now renders the artifact's own result, matching the portable checker. |
| Source bindings | CA-01 through CA-04 fixed: UTF-8 record-set ordering, canonical dispatch targets, NONEMPTY versus NUL-free OS strings, and directory-prefix semantics. |
| Adoption/dashboard | CA-01 through CA-03 fixed: alias-safe helper refresh by rename, cwd-relative `--records`, and association counts on early-error returns. |
| Base toolchain | CA-01 through CA-03 and CA-05 through CA-07 fixed; CA-04 (`DYLD_*` overrides) is refused. Tool file canonicalization uses `canonicalToolPath`, because Darwin `realpath` returned nondeterministic hardlink spellings for `/usr/bin` developer shims, producing false `Conflicting tool root` and identity-drift errors. Rust, proof and native adapters were cut over too; native executable equality compares `(dev, ino)`. |
| Rust toolchain | CA-01, CA-03 and CA-04 are refused at discovery. CA-02 and CA-05 through CA-08 are fixed. Build-script providers bind crates.io identity plus exact build-source fingerprints, so unreviewed provider revisions refuse. |
| Proof toolchain | CA-01 through CA-03 are refused at discovery. CA-04 is fixed. Lake reports effective project source requirements, and the producer refuses any recipe whose source closure omits a required file or a `*.lean` file under a required source directory (`.lake` excluded, symlinks refused). |

Known limits: Linux and other runtimes cannot cancel owned process groups and leave work indeterminate. Lake source coverage is Lean-specific. Three Linux runs reported reversed or out-of-range observation intervals once and did not recur. Retained ns bounds suggest wall-clock stepping in the container VM; fail-closed, cause unproven.

## Round-2 review dispositions (2026-10-15)

Reviews of `6c787c2` are retained as `.fv/code-adversarial/2026-10-15-*-review-2.md`: 44 findings, 14 Major, none Critical. Repeated findings in the toolchain adapters led to an allowlist policy. Discovery now accepts only configuration forms it fully binds and refuses the rest. The contract states this, along with derived native tool identities and checker/recipe resource disjointness. Authors were `openai-codex/gpt-6.1-sol` task agents. The parent wrote the TS derived-identity check in `evidence-v4-source.ts`. Reviewers were `fv-code-adversary` agents; third-family review is outstanding.

| Slice | Disposition |
|---|---|
| Native | CA-01..CA-04 fixed. A zero-length `KERN_PROC_PID` snapshot means the process vanished. Terminated registrations are ignored. The waiter flag comes from the real startup environment. Signaling refuses when SIGCHLD is ignored or `SA_NOCLDWAIT` is set. |
| Store | CA-01 fixed: abnormal raw output is rendered after the final classification. CA-02 refused: checker resources must be disjoint from recipe resources. CA-03 fixed: the recovered-owner snapshot gets a durability barrier. |
| Adoption | CA-01..CA-04 fixed: `..` record paths are normalized lexically, unassessed counters are null, staged helpers are fsynced, and alias checks are skipped for untouched helpers. CA-05 refused: refresh requires existing `.fv` state. Source CA-10 is an accepted limit (Unicode whitespace divergence fails closed). |
| Base toolchain | CA-08..CA-12 refused at discovery: one-import guarded absence, a path-mutation allowlist with statically resolved project loaders, nonempty `NODE_OPTIONS`, `LC_DYLD_ENVIRONMENT`, and shell/unbound Python launchers. CA-13..CA-15 fixed: Darwin non-system dylibs and rustup-selected drivers are bound in derived tree identities, and helper bytes and probes are bound. |
| Rust toolchain | CA-01..CA-06 and CA-08 refused at discovery: every rustflags source, allowlisted codegen tokens, host linkers, runners, unreviewed build scripts, relative link operands and cfg mutations. CA-07 fixed: source inclusions are scanned. Dossier's 22 build programs are admitted under exact fingerprints. |
| Proof toolchain and Lake sources | Proof CA-01, CA-03..CA-05 and Source CA-06, CA-09 refused at discovery: a restricted Lake DSL and CLI, no package overrides, symlink-before-`..` traversal, and Lean commands without an adapter. Proof CA-02, CA-06..CA-09 and Source CA-05, CA-07, CA-08, CA-11 fixed: `elan run` selector equality, the TLC classpath manifest, inode proxy equality, direct `.lean` subjects required, all files under input directories required, case-variant `.lean` files required, and generated namespaces and `.git` skipped in the walk. |

Real captures of Dossier's `git`, `python-runtime` (checker plus both collectors), Cargo/Kani (EX-002, EX-003) and Lean declarations were admitted after these changes. Operational cost: a dependency update that touches a build script, or an unmodeled configuration form, now fails discovery until it is reviewed.

## JVM discovery determinism (2026-10-16)

Classification: implementation-only. Full Dossier planning at `936b350` failed final revalidation with identical Quint backend content digests and different JVM discovery stderr hashes. Retained executions showed the sole difference was `java.vm.compressedOopsMode`, alternating between `Zero based` and `Non-zero based`. The hashes were `9e36c1998e1173d222a7f12f3178598503a4c7a953b7fb0529f2f286c4bd6b77` and `80556ae92d0635c1e08f4a8dba5e3ba76f6cba8b1ffa9a48c798293e7f57f52d`.

The properties-discovery JVM now uses `-XX:-UseCompressedOops`. Solver invocations and proof bounds are unchanged; exact discovery-output comparison remains enforced. The paired real-JVM regression failed before the fix and passed afterward. The proof adapter suite passed 34 tests; three existing helper-byte/native-binding/pnpm-boundary regressions passed. A full direct producer plan returned READY in 409,561 ms with 69 required records and 82 physical slots. This is preflight evidence only, not a proof result or activation verdict.

The earlier indexed-origin/file lookup correction remains in the installed lineage; this change also supplies its missing `ToolFile` type import. General cross-run reuse is not qualified by these checks. Dossier's host explicitly disables it while the remaining round-3 findings stay open.

## Isolated hybrid integration (2026-10-16)

Classification: implementation-only, enforcing the existing provenance/refusal contract. HybridBase and HybridProof supplied independent changes; the parent integrated them on `perf/evidence-hybrid-union`, separate from installed producer `e36b939`. The affected boundary is producer tool/source discovery and its TS/Python validation parity. No protocol model, solver recipe, seed, bound, assurance class or activation prerequisite changes.

| Prior finding | Implementation disposition |
|---|---|
| Base CA-16, CA-17 | Open: root-by-name and imported-helper argument/target analysis remain incomplete. |
| Base CA-18, CA-19 | Runtime-family gates and hardlink aliases are checked; unsupported Python source/loader formats refuse. |
| Base CA-20 | Dictionary/container escape corrected; the class-namespace follow-up is implemented and awaiting final confirmation. |
| Base CA-21 | Partial: reviewed startup-hook imports use actual request paths; direct split-stdlib imports refuse. Transitive split-stdlib paths remain open. |
| Base CA-22, CA-23 | Literal loader paths use command cwd; symlinked Python source and hidden interpreter-wrapper contexts refuse. |
| Base CA-24 | Generic Darwin tree linkage remains open. Dossier's separately retained frozen-installation disposition does not close it. |
| Base CA-25 | Configuration and actual preferred-runtime option checks are closed for the reported mechanisms by runtime review 2. |
| Proof CA-01..CA-04 | Quint family/subcommand gates, symlink-safe Lake `-d`, absolute Apalache JAR selection and Elan nearest-directory precedence are implemented. |
| Source CA-12..CA-14 | Unbound prebuilt imports refuse; generated-path Lean sources remain mandatory; Rustup hardlink selection and derived-tree validation match the retained selector and Python byte checks. |

The first integrated run reported two Rustup hardlink binding failures. Indexed origin checks now accept a file-root alias only when its device/inode and captured hash/size/executable bit match; an independent byte-identical copy still refuses. Both affected checks passed afterward. A duplicate type-only import introduced by integration was removed after the formatter rejected it.

The frozen integrated toolchain/proof/source/adoption suites passed 112 tests. An actual temporary project returned plan READY, run PASS, one physical dispatch for claims A and B, and portable-checker exit 0. These checks do not qualify generic reuse. The installed producer is unchanged.

Independent reports are retained verbatim as `.fv/code-adversarial/2026-10-16-hybrid-runtime-review1.md` and `2026-10-16-hybrid-proof-source-review1.md`. Runtime review retained five known findings and found two incomplete claimed fixes, totaling two Major and five Minor findings. Proof/source review closed the seven original mechanisms and identified one Minor selector-spelling discrepancy. Runtime CA-03, CA-05 and CA-07 remain under correction; the four generic loader/tree boundaries remain open.

The selector-spelling discrepancy was reproduced for terminal `/.` in the locator and Rustup probe executable. Python now uses the same non-normalizing POSIX basename behavior as TS. Both negative vectors failed before and passed after, with ordinary absolute and trailing-slash preservation cases. A separate smoke using the actual captured Cargo identity accepted the original witness and rejected both terminal-dot mutations. Independent confirmation review returned zero findings and closed this defect; its report is `.fv/code-adversarial/2026-10-16-hybrid-selector-parity-review2.md`.

## Fresh collection boundary repairs (2026-10-16)

Classification: implementation-only. Dossier run `a84f2846-5b3e-4054-bc4c-f3c6e64ab054` used project `6e02b8f`, producer `e36b939`, `jobs: 2` and `resume: false`. EX-001 and EX-002 exited zero and printed their prescribed markers, but both retained artifacts are ERROR. The first lost ownership closure at post-exit cleanup; its indeterminate window then blocked the second execution's completion metadata. The final portable report separately rejected additional reviewed tool slots.

The independent failure-classifier report is retained verbatim in Dossier `.fv/code-adversarial/2026-10-16-fresh-ownership-classification.md`. It classifies the ownership failure as infrastructure and identifies post-exit signalling through a guard that requires an unreaped leader. Its proposed retained-anchor redesign was not needed for the bounded natural-drain path: normal exit now uses the existing five-second termination grace without attempting an impossible group signal. Surviving groups still fail termination proof and retain indeterminate ownership. Cancellation/deadline signalling, runtime capability checks, PID/birth checks and proof bounds are unchanged.

The portable checker now treats canonical `required_evidence` as the required subset, matching the producer and legacy checker. Additional declared slots remain required and their failure still fails the claim. No canonical tool may be omitted.

The new minimum-coverage regression passed acceptance with an extra slot, failure of that extra slot, and missing-tool rejection on both consumer and producer paths. The 21 native-review methods passed. The new real lifecycle regression passed both natural child completion and surviving-child refusal after correcting its owner-record fixture field. An isolated invocation of the unchanged EX-001 Quint recipe returned exit zero, `No violation found`, closed ownership and successful session release. That smoke is not canonical claim evidence.

An additional real-process regression moved a registered child into a new session during the post-exit grace. Group emptiness alone incorrectly returned no native error. Termination proof now checks every retained, unfinished member of that group for a surviving original birth before retiring it. The escaped-child regression then passed, alongside the natural-drain and surviving-child cases. The final targeted union passed 24 methods, and the unchanged EX-001 smoke again completed with all three registered processes terminated and its window closed. No signal is sent to an escaped or reaped process.

The original failed run and pending owner remain unchanged. Its indeterminate spawn window prevents same-boot recovery under the existing contract. Neither successful smoke output nor this source correction retires that owner or promotes either failed artifact. Independent post-commit review of `f630af8` returned zero findings; its complete report is `.fv/code-adversarial/2026-10-16-collection-boundary-review1.md`. Full regression verification remains pending.

## Fresh Kani selector aliases (2026-10-16)

Classification: implementation-only. The independent fresh-selector review's CA-01 showed that literal `kani::solver(...)` matching missed imported aliases and compiler-tool attributes. The existing source scanner now refuses solver imports/re-exports, Kani aliases/globs/`extern crate`, raw `kanitool::solver`, and unknown solver-attribute forms. Canonical `kani::solver(kissat)` remains admitted, including raw identifier spelling, comments, a trailing comma and `cfg_attr` nesting. Ordinary solver-named variables/functions and literal/comment text remain admitted.

The two negative regression methods produced 28 failed assertions against a frozen copy of installed `e36b939`. The corrected Rust suite passed 38 methods, including 36 new refusal/preservation subcases across root, dependency and included source files. Actual metadata capture admitted Dossier's EX-002 Kani and EX-003 Cargo contexts; its retained Kani `solver` root matches `distribution/bin/kissat`, hash `sha256:6cbea531c356468c23872474053de41e8c281cec0d7e4189f80b3524101c9aaf`, 423416 executable bytes.

This bounded scanner conservatively refuses unrelated solver imports/attributes. Arbitrary macro-generated selectors remain outside its closure; no generic provenance, reuse or activation qualification follows. No Dossier source, installed runtime, proof recipe or bound changed. Independent reviews cover the named literal routes and preservation corrections only.

Review of `8020b89` is retained verbatim as `.fv/code-adversarial/2026-10-16-fresh-solver-review1.md`. It found no remaining named literal selector bypass but identified two Minor over-refusals: the raw `r#kissat` argument and Unicode identifiers containing a keyword spelling. Six preservation assertions failed before correction. Both pinned-solver checks now accept the exact raw identifier; declaration-keyword recognition uses Rust's Unicode identifier-continuation boundaries. The corrected suite passed 39 methods, and actual EX-002/EX-003 metadata capture still succeeded. Confirmation review of `1c15dc3` returned zero findings and closed both Minor defects; its report is `.fv/code-adversarial/2026-10-16-fresh-solver-review2.md`.

## Hybrid runtime residual corrections (2026-10-16)

Runtime review CA-03, CA-05 and CA-07 are implemented by FixHybridResiduals. Opaque Python selectors remain classified through container/default/return/assignment paths. The actual preferred Node runtime's options and argv are checked; only native executables and reviewed transparent shell-wrapper chains are admitted. pnpm store roots are narrowed to selected canonical symlink targets and their dependency closure while preserving the store escape boundary.

Three regression methods produced 22 failed assertions against the pre-correction `2c7bd3c` adapters. The initial corrected suite passed 45 methods, but actual Dossier Python discovery then refused its module-registry snapshot/restore. The follow-up admits only literal-key snapshots, key iteration and direct two-name `.items()` iteration; values remain opaque, including after restoration. There is no module-name exception. The final suite passed 46 methods, and actual capture admitted both Dossier `mobile-node-toolchain` and `python-runtime`. This is metadata acceptance, not proof evidence or a fresh full-policy collection.

Runtime review 2 closed CA-05 and CA-07, while retaining CA-03 through class namespace publication. The report is `.fv/code-adversarial/2026-10-16-hybrid-runtime-review2.md`. Four class-publication assertions failed before correction. Further lexical-scope cases exposed three escapes and one false refusal, also corrected. Python symbol tables now identify class-written names; method, nested-class and lambda lookup retains the enclosing lexical scope. The shared escape guard covers opaque and known import selectors. Unresolved namespace forms refuse. The complete toolchain suite again passed 46 methods, the direct/snapshot class cases passed, and actual Dossier Python/Node capture succeeded. Class correction confirmation remains pending.

Runtime review 3 identified a remaining class-comprehension escape and CA-08's inconsistent known-selector branch propagation. Ten assertions failed before correction. Class comprehensions now refuse as unsupported; module/function comprehensions remain admitted. Propagation and refusal use the same runtime-selector predicate across conditionals, loops and exception joins. The complete suite passed 48 methods, and actual Dossier Python/Node capture succeeded again. The report is `.fv/code-adversarial/2026-10-16-hybrid-runtime-review3.md`; final bounded-refusal confirmation remains pending.

Runtime review 4 closed the reported CA-03 expression and CA-08 join mechanisms, then identified CA-09: unhandled statement bodies could bypass discovery. The statement dispatcher now refuses unsupported forms, including `match`, exception groups and type aliases, and checks expressions in `assert` and `raise`. The regression retains ordinary supported control flow. The complete suite passed 49 methods, and actual Dossier Python/Node metadata capture succeeded at `fv-hybrid-runtime-selection-qKMxp3`. Review 4 is retained as `.fv/code-adversarial/2026-10-16-hybrid-runtime-review4.md`. Confirmation review of `7c3891c` closed CA-09 with no new bounded-delta findings; its complete report is `2026-10-16-hybrid-runtime-review5.md`.

Root-value CA-16, imported-helper CA-17, transitive split-stdlib CA-21 and generic Darwin-tree CA-24 remain open, including their fresh-provenance implications. No generic reuse or activation qualification is claimed.

## Final integration isolation (2026-10-16)

While preparing this worktree, the collection-repair merge was accidentally executed in the installed FV checkout. That checkout was clean and its new merge had only `e36b939` and `437beea` as parents. The merge is preserved as `765025e` on `perf/evidence-collection-recovered-merge`; `git reset --keep` restored the installed checkout to `e36b939`. No Dossier record or lock was modified by that operation. Subsequent integration merges run only in `evidence-final-union`.

The final integration combines the independently reviewed native/coverage and Kani corrections with the hybrid adapter changes. Full frozen-tree regression verification and the residual runtime re-review remain pending. The original Dossier owner remains blocked; this integration does not authorize recovery or promote failed evidence.
