# Code-adversarial review: dossier v4 artifact/history producer - 2026-10-15

- Operator: fv-code-adversary via OMP task (NOT V4ArtifactHistory, V4ProducerIntegration)
- Code commit reviewed: `aa6946f29f6bc893cba62d58ef99efdc6d5a8716`
- Dossier consumer commit supplied: `1fc3294437c294b040bc606aaa177334b8e41b8c`
- Intent version reviewed: no frontmatter version exists; canonical `docs/intent.md`, including I11/I12 and the 2026-10-14 evidence-performance amendment
- Ledger version reviewed: no frontmatter timestamp exists; ledger header states Updated `2026-10-08` and contains later integration notes
- Lens pack: crypto/enclave, supplemented by evidence state-machine, concurrency, crash-durability and error-atomicity analysis
- Lenses applied: 1 through 6, followed by the additional slice lenses

## Scope and evidence limits

`D` means `/Users/mv/Development/burnt/dossier-wt/evidence-perf`. `F` means `/Users/mv/Development/reliq-fv-wt/evidence-perf`.

The canonical intent was resolved from `D/.fv/dispatch.json` to `D/docs/intent.md`. The normative dependency contract is `F/docs/execution-evidence-v4.md`, abbreviated `V4` below. Its supplied SHA-256 is `825a053c2d3ba511a5f32f03168239fa24d5221195cb238865a9a1dc2ba7c0e2`. Commit identifiers and that digest are caller-supplied; this review did not recompute them.

Primary implementation inspection covered:

- `F/tools/evidence-v4/evidence-v4-store.ts`, abbreviated `store`
- `F/tools/evidence-v4/evidence-v4-run.ts`, abbreviated `run`
- `F/tools/evidence-v4/evidence-v4-attachments.ts`, abbreviated `attachments`
- `F/tools/evidence-run.ts`, abbreviated `factory`

Cited call edges led into `evidence-v4-native.ts` (`native`), `evidence-v4-model.ts` (`model`), `evidence-v4-policy.ts` (`policy`) and `evidence-v4-source.ts` (`source`). Native inspection concentrated on pending results, resource acquisition, release and recovery. It was not a second complete audit of OS process-identity acquisition or private-pipe supervision. Installed-tool discovery internals, portable checking and dashboard rendering remain separate review surfaces.

No commands, tests, builds, formatters, git operations, live operations or file writes were performed. The parent reports successful scoped Linux/Darwin checks, CI gates, real-factory exercises, actual Quint collector ownership and a complete native plan. Those observations are accepted as supplied, without rerunning them. They do not exercise the two failure traces below or establish fresh canonical Dossier evidence. Existing test sources were inspected where cited.

The review retains the frozen premises: approved conforming child lifecycles; no concurrent external mutation or ABA guarantee; upstream build/cache integrity; complete trusted retained history; operator, OS and compiler authenticity. Hashes do not authenticate producer honesty or prove history nondeletion. No refinement, served-route independence, multi-family attestation or production activation is claimed.

Important uncovered classes include general protocol authorization, arithmetic/economic safety, reentrancy, arbitrary malicious process escape, exhaustive resource-exhaustion resistance, supply-chain authenticity and actual power-loss behavior of supported filesystems. The added lenses inspect the implementation's state transitions and requested durability barriers, not the hardware's implementation of fsync.

---

## Lens 1 - Commitment coverage

| Commitment | Attacker DoFs | Bound by | Gap |
|---|---|---|---|
| Reviewed policy and common bindings | Recipe substitution, classes, markers, bounds, observation definitions, target selection | `policy:290-410` derives manifest coverage and exact definition hashes; `source:184-200` checks loaded bindings against captured inputs | No omitted field identified in this slice. Reviewed dependency completeness remains a premise. |
| Execution key | Recipe, argv/cwd, timeout, determinism, full membership, distinct association, source closure, global inventory, environment, toolchain and cache selection | `source:299-380` constructs the full descriptor and hashes it with `D("execution-key", descriptor)` | No selection-dependent narrowing found. Run IDs and current outside-closure content are deliberately excluded under V4 Exact execution identities. |
| Artifact identity and exact file references | Altered result, termination, endpoints, ownership, attachments or output bytes | `store:480-571,595-638`; `model:1430-1462` recomputes canonical identity and completion predicates | No field-coverage gap identified. Actual invocation provenance remains producer-trusted. |
| Raw output | Printed producer trailers, invalid UTF-8, marker text, stream boundaries, fabricated exit code | `store:326-356,575-593`; `run:750-788` reconstructs streams and checks reserved lines before marker acceptance | No marker-only PASS found. Normal zero exit and completion checks remain independent requirements. |
| Collector attachments | Path substitution, manifest/blob substitution, large-number reserialization, borrowing bytes from another artifact | `attachments:8-36,38-72,75-147`; `store:488-554,610-633` retains exact bytes and constrains execution-owned paths | No reserialization of original collector reports found. Nested semantic validation belongs to the incorporated checker. |
| Observation request and receipt | Wrong member, slot, execution, request hash, response location or time interval | `run:954-1089`; `store:650-760` | Request bytes, exact member selection and original execution reference are checked. Native and checker behavior still form separate trust boundaries. |
| Ordered history | Sequence gaps, changed predecessors, wrong attempt/member binding, unindexed committed artifacts | `store:765-1008` validates the complete chain and execution/observation accounting | No hash-chain coverage gap found. CA-02 concerns durability of an already visible event, which a hash cannot establish. |
| Claim and run publication | Rebinding old failures to current source, forged PASS associations, pointer substitution | `store:1211-1372`; `run:1150-1320` | Canonical claim identity and references are checked. Pointer visibility is separately classified from durable publication. |
| Producer implementation | Different producer source/runtime under an unchanged claimed producer identity | `run:194-200,397-399`; `store:399-407` | Implementation-source binding is checked. Completeness/authenticity of the toolchain identity is an upstream slice and declared trust boundary. |

## Lens 2 - Clause-to-line discharge

Statuses below concern the assigned evidence implementation. They do not discharge the underlying Dossier protocol claims.

| Clause | Expected discharge | Actual code line | Status |
|---|---|---|---|
| D I11: actual immutable producer evidence | Run an actual native invocation and retain its output; no copied-log execution fallback | `run:730-743,831-901`; `store:480-571` | discharged for inspected construction path |
| D I11: dependency-scoped freshness | Match current full clean endpoints while allowing reuse only under the bound closure | `run:364-380,687-699,791-820`; `source:228-248,299-380` | discharged at these call boundaries; dependency analysis and installed-tool enumeration remain external |
| D I11: endpoint and upstream-cache assumptions | Do not represent endpoint equality as continuous immutability or fresh compilation | `source:228-248`; `run:1281-1288` retains policy trust assumptions | partial by explicit assumption; no stronger claim established |
| D I12 / V4 S1: full logical expansion | Retain every policy slot regardless of `records` selection | `run:239-285,1159-1236,1281-1300` | discharged for policy scope |
| D I12 / V4 S2: reviewed sharing only | Keep complete fixed-recipe membership and distinct-slot identities | `source:299-307,363-375`; `run:716-727,916-919`; `store:1035-1087` | discharged at descriptor and execution-use boundaries |
| D I12: each member's observations | Run and retain each member assessment after a fresh shared invocation | `run:916-919,938-1147` | partial: normal and semantic-failure paths retain separate observations; CA-01 blocks completion after an observation storage error |
| D I12: physical FAIL applies to all recorded members | Match every recorded canonical claim/tool association | `store:358-370`; `run:875-910` | discharged |
| D I12: observation FAIL applies only to its member | Select the historical observation's claim/slot, then match canonical claim/tool | `store:360-367` | discharged |
| D I12 / V4 B2: cross-key, renamed-slot failure barriers | Compute cutoffs by canonical claim/tool, independently of current key and selection | `store:358-370,1052-1100`; `run:1150-1204` | discharged for inspected policy associations |
| D I12: ordinary ERROR/CANCELLED is not a barrier | Only genuine FAIL or indeterminate completion contributes a cutoff | `store:359` | discharged |
| D I12: only a later actual success clears a cutoff | Require physical PASS sequence strictly after the cutoff, followed by own PASS observation | `store:1054-1082,1265-1289` | discharged; observation-only rechecking cannot rehabilitate an older physical execution |
| D I12: selected unaffected shared member may reuse | Do not redispatch because an unselected sibling has an observation failure | `run:700-714`; `store:1052-1100` | discharged; final assessment still visits all members |
| D I12: exact command, seed and proof budget | Pass the reviewed command without rewriting options | `run:732-741`; `source:363-375` | discharged at invocation boundary; recipe-definition equality is delegated to preflight/checker |
| D I12: required FAIL precedence | Aggregate required failures before operational errors, interruption and missing requirements | `run:1237-1256`; `store:1318-1329` | discharged for available full-policy assessments; storage publication can independently return ERROR as V4 requires |
| D I12: primary environment hash-only; exact public replay exception | Persist hashed primary values while retaining original allowed collector bytes | `source:250-280`; `attachments:75-147`; D policy checker declaration `:1093-1107` | partial: transport and retention inspected; public/nonsecret value qualification remains reviewed-policy/checker trust |
| D I12: private collector ownership | Require native protocol and closed retained ownership before artifact PASS | `run:740-742`; `store:429-453`; `model:1442-1461` | partial: receipt enforcement inspected; OS/private-pipe mechanism assigned separately |
| V4 B1: zero exit, marker, clean endpoints, closed ownership | Conjunction before artifact PASS | `run:750-828`; `model:1430-1462`; `store:429-453,575-593` | discharged except durability recovery issue CA-02 |
| V4 T1: checkpoint/history precede observations | Publish execution, append history, clear pending, then observe | `run:882-919` | discharged in normal path |
| V4 T1: fail-fast and accounted in-flight work | Halt new evidence dispatch and complete or retain admitted work | `run:594-651,784-786,1092-1093` | partial: normal fail-fast path inspected; CA-01 can leave the invocation waiting on its own retained lock |
| V4 T2: recovery never steals ownership | Verify expected owner and real liveness before accounting and retirement | `native:1750-1799,1833-1852` | partial: recovery call edge inspected, full identity implementation not independently reviewed |
| V4 Checkpoints / recovery: durable pending accounting before retirement | Re-establish required barriers for uncertain visible history before treating it as accounted | `store:1163-1210`; `native:1797-1799,1848-1852` | gap: CA-02 |
| V4 Callable API: public factory remains usable | Exact versioned union, ordinary factory shape, native v4 path independent of `pi.exec` | `factory:585-648`; `run:150-199` | discharged by source inspection; parent separately reports real-host exercise |
| V4 compatibility / D I12: v3 remains default and separate | Preserve legacy `pi.exec`, whole-snapshot cohort result and v3 record namespace | `factory:627-650,674-845` | discharged for inspected dispatch/storage separation; no historical byte-diff verification was performed |
| D I13: scoped result cannot activate production | Preserve canonical targets while reporting a policy batch, leaving full canonical activation to its checker | `policy:390-403`; `run:1281-1300`; V4 `:520,567-569` | partial boundary discharge; no independent activation verdict from this runner |
| D I14: no runtime/mobile authority change | Limit this implementation to evidence production | Primary files and v3/v4 factory branches | partial: no deployment or mobile path was inspected or exercised |
| Ledger C-01 through C-09; local C-14/C-15 integration legs | Preserve evidence associations without claiming composed proofs | `policy:317-343`; `run:1207-1236` | partial: aggregation inspected; ledger candidates remain INCOMPLETE |
| Ledger C-10 through C-13 and other C-14/C-15 activation obligations | Do not treat a scoped producer batch as their discharge | Complete canonical target binding at `policy:401`; separate activation requirement in D I13 | partial; outside implementation scope |
| Ledger TA-08 | Retain operator/producer honesty as a trust assumption | Unsigned canonical hashes and local files throughout `store` | partial by design; no producer authentication |
| Ledger TA-01 through TA-07 and TA-09 through TA-17 | Preserve platform, cryptographic, custody, governance, provenance and clock prerequisites | D ledger External trust-assumption inventory; no implementing enforcement in these producer files | partial; not discharged by this review |
| D I1-I10, RS1-RS6, S1-S7, B1-B19/B2t, Q-B19, PV1-PV5, PS1-PS7 and PB1-PB12 | Underlying protocol, enclave, storage and model obligations | Their enforcing components are outside the caller's code roots | partial; retained as external obligations, with no protocol-verification conclusion |

## Lens 3 - Deferred cannot silently succeed

| Branch | Reachable from | Behavior | Status |
|---|---|---|---|
| TODO, stub, mock, deferred or unimplemented branch | Four primary production files | Targeted search found no matching deferred implementation branch | Empty finding set for this lens; this does not establish correctness of implemented branches |
| Plan mode | Public v4 factory or `runEvidenceV4` | Performs preflight and returns READY/ERROR, without dispatching evidence recipes (`run:402-430`) | Explicit planning result, not evidence PASS |
| Missing session, store, tools, environment or baseline | Runner internal dependency access | Throws explicit errors (`run:328-347`) | No synthetic success fallback |
| Malformed or unsupported collector retention | Attested recipe completion | Retention errors prevent physical PASS (`attachments:96-127`; `run:834-845`) | Explicit error |
| Unsupported platform or unresolved ownership | Native session creation/release | Refuses v4 or retains ownership (`native:1729-1731,861-873`) | Explicit refusal; retained ownership is not fabricated cleanup |

## Lens 4 - Who controls

| Field | Supplier | Validation | Gap |
|---|---|---|---|
| Call schema, policy, mode, records, jobs, resume | Operator | Closed versioned schema, policy membership and maximum jobs (`factory:590-624`; `run:183-193`) | No command/class/marker override found in v4 |
| Policy records: claim ID, required, class, scope, slot/tool/recipe and observation binding | Reviewed repository policy | Canonical manifest required status, class compatibility, dependency/tool coverage and incorporated pointers (`policy:317-379`) | Reviewed definitions remain the authority |
| Descriptor common, recipe, members, distinct slot, inventory, closure, environment, toolchain, cache | Producer from policy and captured identities | `source:299-380`; `store:395-426` | No caller selection substituted for full membership |
| Artifact schema, key, attempt ID, producer and artifact ID | Producer | Generated UUID; descriptor/domain hashes; producer binding (`run:194-200,716-727,851-873`; `store:395-407,595-609`) | No independent producer authentication claimed |
| Artifact start/finish, termination, ownership | Native supervisor | Interval checks, normal completion and closed registrations/windows (`store:427-453`; `model:1439-1461`) | Native measurement accuracy remains upstream/OS trust |
| Artifact before/after source, tools, environment and cache | Producer endpoint collectors | Equality and cleanliness required for PASS (`run:791-828`; `model:1442-1461`) | Continuous nonmutation and cache correctness are assumed |
| stdout, stderr, raw output, attachment refs | Actual process/collector bytes retained by producer | Exact hashes, fixed paths, tree inventory and raw reconstruction (`store:488-554,610-638`) | No original-report reserialization found |
| Result, marker_matched and reason | Producer classification | Independent exit/completion checks and marker reconstruction (`run:750-828`; `store:575-593`) | No new semantic-substitution finding |
| Request ID, claim, slots, common bindings and creation time | Producer | Fresh request directory, exact requested slot and immutable request (`run:954-989`) | No caller-supplied request-file path |
| Response IDs, request hash, result, observations and timestamps | Reviewed checker | Exact schema/member/hash/time checks and original checker transport (`run:1020-1089`) | Semantic observation truth remains the incorporated checker boundary |
| Check stdout/stderr, termination, endpoint states and result | Native supervisor plus producer | Stored receipt and history binding (`run:1094-1132`; `store:650-760`) | CA-01: failure while storing these fields can strand the next member on a retained resource lock |
| History sequence, previous, kind, members, selected association, execution/observation/recovery refs and result | Producer under append mutex | Complete contiguous enumeration and event-specific bindings (`store:765-1008`) | CA-02: visibility of an existing event is accepted during recovery without repeating its durability barrier |
| Recovered owner and pending membership | Preserved native owner | Exact immutable owner bytes and pending association match (`store:811-840,1104-1120,1163-1210`) | No membership guessed from current policy; CA-02 affects durable accounting |
| Claim identity, scope, executions, blockers, observations, result and waiver | Producer full-policy assessment | Canonical claim hash, association/history checks; waiver is null (`run:1207-1236`; `store:1211-1304`) | No hidden per-selection claim subset found |
| Run ID, selected/required records, preflight, work, claims, endpoints, result and trust assumptions | Producer | Full generation validation and required-failure precedence (`run:1237-1300`; `store:1215-1330`) | Policy-batch result is not canonical activation |
| Current pointer and publication state | Producer filesystem operations | Validate complete generation, fsync temporary, rename, distinguish pre/post replacement errors (`store:1338-1372`) | No unconditional rollback promise found |
| Primary environment value hashes | Sanitized inherit/set union | Exact names, set precedence, NUL/scalar validation and real platform (`source:250-296`) | Hash-only storage is implemented; semantic secrecy of configured values cannot be established from a name alone |

## Lens 5 - Field-name fidelity

| Field | Implied semantic | Actual value | Status |
|---|---|---|---|
| `execution_key` versus `artifact_id` | Reusable operation identity versus one actual attempt | Descriptor hash versus full artifact hash (`source:379-380`; `store:480-486`) | faithful |
| `attempt_id`, `started_at`, `finished_at` | Original invocation identity and interval | Fresh attempt plus native timestamps; cache reuse retains original artifact (`run:716,851-860,700-714`) | faithful |
| `raw_output`, stdout and stderr refs | Retained actual byte streams and prescribed producer trailer | Exact captures and deterministic reconstruction (`run:760,831-833`; `store:326-342`) | faithful |
| `members` and `distinct_slot` | Complete reviewed physical ownership | Full expanded membership, independent of selection (`source:363-375`) | faithful |
| `blocking_events` | Historical failure/indeterminate references | Original history refs, not current-source artifacts (`run:1150-1183`) | faithful; list retains historical blockers, while eligibility decides supersession |
| Work `state` versus claim/slot `state` | Physical scheduling outcome versus association eligibility | Unselected work can remain MISSING while its claim remains FAIL from history (`run:239-259,1150-1204`) | faithful |
| Work `cache` | Selected-member reuse decision | Hit is selected-member eligibility; it does not assert every shared sibling passed (`run:700-714`) | faithful |
| `publication.state` | Whether replacement and subsequent durability completed | Distinct pre-replace, post-replace and durable states (`store:1338-1372`) | faithful in pointer publication |
| RunResult `result` versus manifest `result` | Operational publication outcome versus immutable collection result | Publication error changes direct result to ERROR without rewriting the manifest's collected FAIL/PASS (`run:1301-1320`) | faithful |
| `EnvironmentIdentity.variables[].value_hash` | Hash of the actual semantic value | H of UTF-8 value, or null when absent (`source:270-279`) | faithful |
| Collector report bytes | Original incorporated evidence, including large integers | Exact stdout slice retained; transformed numeric strings are used only for retention-side parsing (`attachments:8-36,96-101`) | faithful; original validators remain required |
| `canonical_required_targets` and `required_records` | Canonical manifest target set versus policy-required records | Separate arrays (`policy:401`; `run:410-418,1289-1290`) | faithful; no activation equivalence implied |

No additional field-name finding was established.

## Lens 6 - Deferral justification audit

| Deferred finding | Justification claims | Claim audit | Verdict |
|---|---|---|---|
| Earlier v4 D-1 barrier obligation, left to the producer review by D observations review | Cross-key canonical failures must survive selection; actual retries are required to supersede them | `store:358-370,1052-1100`; `run:1150-1204` implement the claimed association/cutoff rules | No wrong-deferral established for cutoff semantics; storage/error paths have CA-01 and CA-02 |
| D-4 native ownership obligation | Private-pipe lifecycle is mandatory; abnormal ownership may remain indeterminate | Closed receipt checks at `store:429-453`; pending/release requirements at `native:861-873` | Partial audit only. No claim that an empty child list proves an abnormal registration window safe |
| D-5 public replay attachment exception | Original reports are retained without redaction; primary environment stays hash-only | `attachments:75-147`; `source:250-280`; D observations review `:100-114` | No wrong-deferral established; secret-value qualification remains a separate pre-dispatch obligation |
| Manual transitive-input closure | A reviewed basis is required; unknown closure cannot be inferred from successful execution | `source:232-248` falls back to verified inputs without a prefix basis | No automatic-completeness claim found; actual closure enumeration remains another slice |
| D portable reviews 1-3 | Prior consumer findings closed under their clarified scope | Round-3 report records closure and explicitly separates producer/native review | No reopening or independent consumer closure claimed here |
| Ledger TA-08, TA-11/TA-12 and incomplete composition candidates | Local hashes and tests do not authenticate producer honesty, validator provenance or refinement | Current producer emits unsigned evidence and a policy-batch result; canonical activation remains separate | Declared limitations remain; no false discharge identified |

No deferred prior finding in this assigned implementation slice was shown to rest on a false justification. This table does not close unrelated protocol, Q-B19 or deployment deferrals.

## Additional lens - State-machine and concurrency

| Transition | Required property | Inspected implementation | Status |
|---|---|---|---|
| Preflight to evidence admission | Complete policy expansion and all cheap checks precede costly work | `run:383-401,486-590,594-651` | No separate finding |
| Evidence start to physical checkpoint | Pending membership precedes spawn; key/resource ownership covers execution and checkpoint | `run:716-743,882-919` | No separate finding in normal ordering |
| Physical PASS to shared observations | Every member is assessed; semantic FAIL stops later evidence admission without discarding siblings | `run:916-919,1092-1132` | Normal semantic-failure behavior is present; fatal persistence failures need a separate transition |
| Observation persistence failure to terminal run | Return operational ERROR while retaining unresolved pending ownership, without waiting on that ownership again | `run:1128-1147,916-919`; `native:714-715,838-848` | CA-01: self-deadlock |
| Failure to selective resume | Match canonical claim/tool across keys; preserve unaffected shared members | `store:358-370,1052-1100`; `run:700-714,1159-1204` | No separate finding |
| Claim completion to batch result | Dependency coverage can prevent PASS; required FAIL precedes missing/error/cancelled work | `run:1220-1256` | No separate finding |
| Cancellation to publication | Aborted work cannot become a successful direct invocation result | `run:784-828,1060-1086,471-477` | Source paths inspected; no cancellation execution performed |

### CA-01 evidence trace

[INFERENCE] Use a fixed recipe with at least two members and a nonempty checker resource set. Dossier supplies `project-checker` at `D/.fv/execution-policy.json:1093-1107`.

1. The physical invocation passes and its execution/history become durable.
2. The first member checker completes normally with closed process ownership. Its PendingResult remains set until the observation event is durable.
3. An I/O failure while writing checker stdout, check.json or its history event reaches `run:1134-1138`. `observe` records ERROR and sets `halted`, but swallows the exception.
4. Because `pending !== null`, `run:1140-1147` retains the checker resource lock. Retention itself is required for unresolved accounting.
5. The unconditional loop at `run:919` calls `observe` for the next member. Its first step at `run:950` awaits the same checker resources. `native:714-715` returns null when this session already holds a requested lock; `native:843-848` retries indefinitely unless externally cancelled.

The checker timeout does not bound this wait because the second checker has not spawned. The runner cannot reach its normal ERROR publication/return, and the live owner prevents recovery. The same retained-lock problem can affect already-admitted siblings waiting for the checker resource. This is a failure-path liveness defect, not a claim that the run incorrectly returns PASS.

The fix must distinguish a completed semantic member FAIL, after which remaining shared members still need observations, from a fatal storage/accounting failure that leaves a pending result or retained lock. Propagate the latter out of the member loop and stop same-session waiters without releasing unaccounted ownership.

## Additional lens - Crash durability

| Crash/error boundary | Required property | Inspected implementation | Status |
|---|---|---|---|
| File and ancestor creation | Flush files and modified directories before acknowledgement | `store:149-187,219-270` | Present in ordinary publication |
| Execution staging to final attempt | Complete tree, same filesystem, never overwrite existing attempt, parent barriers | `store:480-571` | Present under exclusive ownership and no external mutation premise |
| Committed attempt before history append | Unindexed success cannot become a cache entry | `store:894-936`; recovery indeterminate path `:1192-1207` | Present |
| History link visible before parent fsync | Recovery must not equate visibility with completed durability | `store:260-270,1176-1191` | CA-02 |
| Current-pointer replacement | Distinguish visible replacement from successful post-replacement barriers | `store:1338-1372`; `run:1301-1306` | Present; no rollback attempted |
| Recovered ownership retirement | Account pending history durably before retiring owner and resource locks | `store:1163-1210`; `native:1797-1852` | Partial because of CA-02 |

### CA-02 evidence trace

[INFERENCE] Let an observation receipt be fully durable, then fail or crash during its history publication after the final history name is linked and the staging alias is removed, but before the history directory is successfully fsynced.

`immutableFile` makes that interval explicit at `store:260-270`. The observation PendingResult remains in the owner because `run:1126-1129` clears it only after append success. All process windows can already be closed.

After the producer exits, recovery finds a valid visible matching event. At `store:1176-1191`, `accountPending` treats it as already accounted and continues without fsyncing the event or history directory. Its final `readHistory` is validation by reads, not a durability barrier. Preserving a recovered owner flushes the recovered-owner path and ancestors, not the sibling history directory. `native:1797-1799,1833-1852` then removes resource locks and retires the original owner.

Recovery therefore acknowledges pending accounting without completing the barrier whose failure left that pending result unresolved. A subsequent power loss may lose the event after ownership has been retired. An otherwise retained receipt can then be unaccounted with no active owner left for the ordinary recovery path. The exact post-crash filesystem outcome was not exercised. Subsequent validation is expected to fail closed on the orphan receipt, so this is classified Minor rather than as an established false-PASS exploit.

Before accepting an existing event for pending recovery, re-establish durability for that validated event and its modified directory/ancestor chain. A repeated barrier failure must retain the owner. Preserve the original event and outcome; recovery must not invent a new success.

## Additional lens - Error atomicity

| Operation | Required failure behavior | Actual behavior | Status |
|---|---|---|---|
| Artifact or history publication | No invented reference on failed publication; unresolved pending retained | `run:882-901,921-935` | Present for physical work |
| Observation publication | No receipt/reference invention; terminate invocation without consuming unresolved ownership | `run:1094-1147` | References are not invented, but CA-01 prevents normal failure completion |
| Claim dependency aggregation | Preserve own FAIL and prevent PASS when a dependency is incomplete | `run:1207-1236` | Present |
| Pointer publication failure | Direct ERROR while immutable collection result remains available | `run:1301-1320`; `store:1338-1372` | Present |
| Recovery after uncertain history publication | Repeat durability before retiring the pending owner | `store:1176-1191`; `native:1797-1852` | CA-02 |

Existing lifecycle tests cover shared-member divergence and selective reuse (`F/tests/r38_evidence_v4_lifecycle.py:145-203`), crash cuts during artifact/history construction (`:1071-1134`), first failure with in-flight work (`:1140-1175`) and pointer pre/post replacement faults (`:1418-1480`). The inspected crash cuts use a single-member fixture and do not cover a shared observation storage failure followed by another same-session checker-resource acquisition. They also do not establish recovery barriers for an already visible history event. No test result is inferred from test source.

---

## Finding list (consolidated)

| ID | Lens | Severity | Surface | Intent ref | Code ref | Summary | Fix |
|---|---|---|---|---|---|---|---|
| CA-01 | clause-to-line; state-machine/concurrency/error-atomicity | Major | Producer shared-member observation and retained resources | D `docs/intent.md:32` I12; V4 `:19,420,460,466` | F `tools/evidence-v4/evidence-v4-run.ts:916-919,950,1094-1147`; `evidence-v4-native.ts:714-715,838-848`; D `.fv/execution-policy.json:1093-1107` | An observation storage/accounting failure is swallowed while its PendingResult and checker lock remain held. The next shared member waits indefinitely for that same session-held lock, so the invocation cannot return the required operational ERROR without external cancellation. | Propagate fatal unresolved observation errors out of member iteration and wake/stop same-session waiters. Keep pending ownership retained for recovery. Continue sibling assessments only after fully accounted semantic outcomes. Add a multi-member, nonempty-resource storage-fault regression. |
| CA-02 | clause-to-line; crash-durability/error-atomicity | Minor | Recovery of visible but unacknowledged history | D `docs/intent.md:25,32` I11/I12; V4 `:456-460,466,484,557` | F `tools/evidence-v4/evidence-v4-store.ts:260-270,1163-1210`, especially `:1188-1191`; `evidence-v4-native.ts:1797-1799,1833-1852` | Recovery accepts an existing matching history event by readability and hash validation, without repeating a possibly failed history-directory durability barrier, then retires ownership. A later crash can leave retained receipts unaccounted after the owner has been removed. | Fsync the validated existing event and history directory/changed ancestors before acknowledging that pending result. Refuse retirement on barrier failure. Add recovery cuts after final history publication but before successful parent fsync. |

## Summary

- Total findings: 2
- By severity: Critical=0 Major=1 Minor=1 Informational=0
- By lens: commitment-coverage=0 clause-to-line=2 deferred-cannot-silently-succeed=0 who-controls=0 field-name=0 deferral-justification=0
- Supplemental lenses: state-machine/concurrency=1, crash-durability=1, error-atomicity=2; these are overlapping classifications, not additional findings.
- Recommended next step: first correct fatal observation-error propagation and same-session retained-lock waits; then add recovery durability barriers for existing visible events. The parent should extend and run `r38_evidence_v4_lifecycle.py` for both traces, retain shared-member selective-resume/cutoff controls, and run the existing v4 cache/portable and v3 factory regressions after the fixes. Keep canonical full activation separate from scoped producer results.