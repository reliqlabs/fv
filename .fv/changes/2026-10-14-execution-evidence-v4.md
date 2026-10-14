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
