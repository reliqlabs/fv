# Code-adversarial review: dossier v4 native ownership - 2026-10-15

- Operator: fv-code-adversary via OMP task (NOT V4NativeOwnership)
- Code commit reviewed: `aa6946f29f6bc893cba62d58ef99efdc6d5a8716`
- Consumer commit supplied: `1fc3294437c294b040bc606aaa177334b8e41b8c`
- Intent version reviewed: absent from frontmatter; canonical `docs/intent.md`, including the 2026-10-14 I11/I12 evidence-performance revision
- Ledger version reviewed: absent from frontmatter; inline `Updated` value is `2026-10-08`
- Lens pack: crypto/enclave, supplemented with concurrency, process-ownership and error-atomicity analysis
- Lenses applied: 1 through 6

## Scope and evidence limits

Path aliases:

- `D` = `/Users/mv/Development/burnt/dossier-wt/evidence-perf`
- `F` = `/Users/mv/Development/reliq-fv-wt/evidence-perf`
- `N` = `F/tools/evidence-v4/evidence-v4-native.ts`
- `R` = `F/tools/evidence-v4/evidence-v4-run.ts`
- `V4` = `F/docs/execution-evidence-v4.md`

`D/.fv/dispatch.json` resolves the canonical target to `D/docs/intent.md`. F's execution-evidence contract is the caller-designated normative dependency, not a substituted canonical intent. Its supplied SHA-256 is `825a053c2d3ba511a5f32f03168239fa24d5221195cb238865a9a1dc2ba7c0e2`; this reviewer did not recompute that digest or independently check commit/worktree correspondence.

The primary implementation was inspected from launch transport through recovery. Boundary inspection followed its imports and callsites into ownership schemas, execution-result classification, artifact ownership checks, the original Dossier collector, and native lifecycle tests. This is not an independent review of the complete store, scheduler, toolchain discovery, member-observation implementation, portable checker or dashboard.

No shell commands, tests, builds, gates, formatters, edits or live operations were performed. Findings marked `[INFERENCE]` describe execution paths derived from source, not reproduced failures. The parent's reported Linux/Darwin tests, corrected targeted reruns, CI gates, real factory exercises, actual collector exercise and READY plan are accepted as scoped observations. They do not establish the additional race and error cases below or constitute new canonical D evidence.

The review preserves the approved-command lifecycle premise. No finding requires a reviewed child to perform a hostile `setsid`, daemonize or evade supervision. Ordinary process exit, PID recycling and OS query failure remain relevant. No-concurrent-mutation applies to the bound source/tool/configuration/cache inputs; it does not reserve kernel PID/PGID numbers after their original processes disappear.

Operator honesty, OS/compiler authenticity, upstream build/cache integrity and complete trusted retained history remain assumptions. Hashes provide no cryptographic producer authentication. Endpoint checks do not establish continuous nonmutation or exclude restored edits. No refinement, production activation or independently attested serving-route diversity is claimed. Multiple same-family agents are not multi-family attestation.

Important uncovered classes include protocol authorization, cryptographic implementation correctness, arithmetic/economic safety, reentrancy, migration, general resource-exhaustion resistance and supply-chain authenticity. Descriptor and process error paths were inspected, but Bun's internal descriptor-adoption/closure implementation was not available in the inspected sources; source-level wrappers alone do not prove its ownership semantics under every runtime failure.

---

## Lens 1 - Commitment coverage

| Commitment | Attacker DoFs | Bound by | Gap |
|---|---|---|---|
| Serialized publication owner | Run identity, process identity, children, spawn windows and pending results | Canonical serialization of the complete owner; expected-byte replacement; exclusive initial creation (`N:663-678,1721-1746`) | No omitted owner field identified. Correct serialization does not establish that a process was correctly attributed; CA-01 and CA-02 concern the source facts. |
| Resource/key lock record and registry hashes | Resource ID, owner/run/host/boot identity, owner-file path | Complete lock record at `N:701-712`; registry hashes at `N:715-733`; resource names use `D("lock-resource", id)` at `N:829-831` | No resource-ID or owner-field underbinding identified. The global root remains the identity-bound HOME/XDG selection required by V4. |
| Host and boot identity | Local OS machine/boot values | Exact OS-byte hashes at `N:434-459` | No caller-supplied identity substitution found. OS authenticity remains trusted. |
| Private protocol log | Collector-controlled event bytes, event order and reported PGIDs | Exact appended bytes are synced before queued message handling; receipt records their hash and size (`N:1071-1083,1377-1406,1641`) | The bytes are retained. A hash cannot establish the correctness of the associated process census. |
| Launch frame | Reviewed argv, resolved executable, cwd and semantic environment | Complete canonical frame passed over the private gate; direct `execve` receives the retained argv/env buffers (`N:54-78,1469-1476`) | No shell reconstruction or omitted launch-frame field found. This private transport is not a cryptographic execution attestation. |
| OwnershipReceipt and execution artifact | Registration/window state and protocol-log reference | Native receipt construction (`N:1636-1642`); store checks registration/window/time bindings and PASS closure (`F/tools/evidence-v4/evidence-v4-store.ts:420-447`) | Downstream checks trust producer observations. They cannot repair CA-01/CA-02 by hashing the resulting receipt. |
| Signatures, enclave ReportData and application commitments | None in this assigned module | No such commitment is produced here | Empty application-cryptography surface. Dossier quote correctness is outside this review. |

## Lens 2 - Clause-to-line discharge

“Discharged” below means an enforcing path was identified in the inspected source under the declared premises. It does not mean the whole system was verified.

| Clause | Expected discharge | Actual code line | Status |
|---|---|---|---|
| D I11: actual invocation, no copied/rebound run | Execute real commands and retain actual streams/status | `N:1257-1266,1295-1318,1477-1480,1627-1642`; `R:723-734` | discharged at the native invocation boundary |
| D I11: endpoint/cache/source provenance | Native execution must compose with current input/tool/cache validation | `R:712-734,762-790`; native module does not implement source closure | partial; full endpoint and toolchain validation assigned outside this slice |
| D I12: unchanged argv and bounds | Preserve every nonempty NUL-free argv vector, including a one-element subject | `N:607-628,54-78`; collector gate check at `N:1711-1719` | gap: CA-03 |
| D I12: durable private collector ownership before subject execution | Fresh FD3/FD4 channel, real interpreter/gate and OS identity checks, durable registration before ACK | `N:1165-1235,1251-1288,1371-1406`; `D/.fv/scripts/collect_quint_witness.py:350-376` | partial; ordering is present, but CA-03 rejects a valid gate shape |
| D I12: cancellation/unrun work cannot PASS | Preserve abnormal state and require closed ownership before success | `N:1113-1163,1241-1250,1348-1370,1559-1580,1619-1635`; `R:762-771` | partial; cancellation flags are enforced, but termination proof has CA-02 |
| D I12: retained original membership and failure barriers | Persist pending execution/observation membership before invocation; account before clearing | `N:684-699`; `R:716-734,735-755,167-176` | partial; native pending ownership is present; complete history/cutoff assessment is outside this slice |
| D I13/I14 | Evidence work must not imply activation or authorize deployment | Native APIs expose local execution/ownership only (`N:88-122,1721-1856`) | partial; no activation path found here; consumer/full gate remains a separate boundary |
| V4 S1 | Preserve every expanded logical slot and final assessment | Native module receives attempt/key scope; expansion belongs to R and policy code | partial; no full-plan discharge claimed |
| V4 S2 | One real execution owns its captured bytes and receipt | Per-invocation buffers and receipt (`N:914-917,1295-1318,1609-1642`) | discharged for native capture; immutable publication/sharing validation remains outside this slice |
| V4 B1 | Real normal completion, zero status, closed ownership and durable evidence precede PASS | `N:1480-1527`; `R:762-790`; store ownership checks `:420-447` | gap: CA-02 can make the ownership-closed input false; remaining conjuncts are cross-component |
| V4 B2 | Unknown/cancelled/corrupt work cannot become PASS | Error/indeterminate paths at `N:1530-1605`; classification at `R:762-771` | partial; explicit errors are retained, but CA-02 suppresses one OS-query failure |
| V4 T1 | Durable ownership/results and accounted in-flight work | Serialized owner writes at `N:663-682`; drain at `N:857-861`; pending-before-run at `R:716-734` | partial; complete scheduling and publication ordering not independently reviewed |
| V4 T2 and V4:330,336,340 | Never signal a foreign or ambiguously owned process group | `N:566-603`; descendant acquisition at `N:1432-1455` | gap: CA-01 |
| V4:328 | Durable launch window before actual spawn; gated direct-child registration | `N:900-913,1257-1266,1414-1424` | discharged for inspected ordering; storage/runtime failure qualification remains external |
| V4:332-336 | Private FD direction, exact control variable and durable ACK ordering | `N:629-633,925-1044,1165-1235,1251-1288,1371-1406` | discharged at wrapper/protocol ordering level; Bun descriptor-adoption failure semantics remain unproved |
| V4:338 | Abnormal collector stop retains a lifetime window | `N:908-913,1426-1430,1511-1527,1565-1578` | discharged for the inspected abnormal-stop path |
| V4:340 | Exact output bytes; invalid UTF-8 prevents PASS; deadlines do not invent normal status | `N:1295-1318,1348-1370,1609-1635`; `R:762-790` | discharged for byte/flag handling; group-termination proof is affected by CA-02 |
| V4:528-556: publication/key/global resource locks | Exclusive creation, sorted complete resource admission, no live/indeterminate theft | `N:715-845,862-873,1721-1856` | partial; lock acquisition/recovery guards inspected; group liveness inherits CA-02 |
| V4:556: recovery accounting before retirement | Preserve unchanged dead owner, account unresolved pending results, then retire locks | `N:1749-1856`; `R:167-176` | partial; ordering and live/changed-owner refusal present; Darwin group census has CA-02 |
| Ledger TA-08 | Unsigned evidence retains operator/checker honesty assumption | Local canonical records and hashes, without signature authentication (`N:663-678,701-712,1636-1642`) | partial by explicit trust; no cryptographic discharge claimed |
| Ledger C-01 through C-15 | Collection must not upgrade incomplete component conjunctions into refinement | No component-proof implementation in N; ledger retains INCOMPLETE status | partial, outside this slice |
| Ledger TA-01 through TA-07 and TA-09 through TA-17 | Preserve platform, cryptographic, deployment, provenance and time assumptions | No corresponding enforcing implementation in N | partial, outside this slice; none discharged by process supervision |
| D I1-I10, RS1-RS6, S1-S7, B1-B19/B2t, Q-B19, PV1-PV5, PS1-PS7, PB1-PB12 and remaining protocol scenarios | Enforced by their application components, not the evidence supervisor | No application enforcing code inspected for these clauses | partial, explicitly outside the assigned native slice; V4's similarly named invariants are separate |

## Lens 3 - Deferred cannot silently succeed

| Branch | Reachable from | Behavior | Status |
|---|---|---|---|
| TODO/stub/mock/deferred implementation | Primary native module | Targeted search found no such branch | Empty deferred-success finding set |
| Missing Bun, unsupported platform or unavailable native ABI | Session/launch setup | Throws; no caller-exec or fake-output fallback (`N:30,1253-1256,1723-1724`) | explicit refusal |
| Failed direct `execve` or malformed launch frame | Gate transport | Writes the failure channel and exits 125; parent promotes nonempty failure bytes to an error (`N:40-82,1477-1479`) | explicit failure |
| Timeout or abort after marker output | Native deadline/signal path | Sets timeout/cancellation state, performs owned cleanup and retains the flags (`N:1113-1163,1241-1250,1348-1370`) | explicit abnormal outcome |
| Abnormal collector EOF, malformed control or unresolved registration | Private event channel/catch path | Protocol error and indeterminate lifetime prevent successful release (`N:1371-1406,1511-1527,1565-1578,862-869`) | explicit refusal under inspected paths |
| Unknown Darwin census query result | `processTable()` | A zero result is silently skipped (`N:550-551`) | CA-02; this is a real error-handling gap, not a labeled stub |
| Recovery of live, changed, foreign-host or unresolved same-boot owner | Explicit recovery | Refuses before accounting/retirement (`N:1754-1782`) | no deferred-success path found |

## Lens 4 - Who controls

| Field | Supplier | Validation | Gap |
|---|---|---|---|
| Owner `schema_version`, `owner_id`, `run_id`, `created_at` | Producer constants/UUID/time; supplied run UUID | UUID check and canonical exclusive write (`N:1721-1746`) | No new gap identified |
| Owner `host_id`, `boot_id`, `pid`, `process_start_id` | Actual OS identity | OS APIs/procfs, with missing identity refusal (`N:434-499,1728-1738`) | OS authenticity remains trusted |
| `OwnedProcess.pid`, `process_start_id`, `process_group`, `session_id`, `parent_pid` for direct/hosted leaders | OS observations; hosted PID supplied over the private collector channel | Gated parent/group/session checks and repeated birth check (`N:1177-1202,1414-1424`) | Initial gated leader validation is present |
| Descendant `OwnedProcess` rows | Numeric process census plus subsequent PID read | Session/group equality only; existing numeric PIDs are skipped (`N:1432-1455`) | CA-01: recycled group/session numbers can supply a foreign row as newly owned |
| SpawnWindow identity/protocol/attempt/key/parent/state | Producer execution scope and lifecycle transitions | Durable pending/active/closed/indeterminate transitions (`N:900-913,1085-1100,1203-1229,1511-1527,1565-1578`) | Closure depends on census correctness, CA-02 |
| PendingResult kind/key/attempt/members/claim/slot | Runner's reviewed expansion | Schema validation and exact duplicate/removal matching (`N:684-699`; `R:716-734`) | Full policy membership validation belongs to the runner/model boundary |
| Registration `registered_at`, `terminated_at`, `window_id` | Producer clock and group-termination decision | Registration and termination persistence (`N:1085-1110`); store time/window checks | CA-02 can populate `terminated_at` without a complete census |
| Protocol `event`, `pgid` | Collector | Exact keys, event allowlist, safe positive PID, duplicate/order/parent/session/gate checks (`N:1165-1235`) | CA-03 overrestricts a legitimate transport argv |
| Semantic environment and reserved FD control | Reviewed environment; producer-created control value | Name/NUL validation, reserved variable rejection and producer injection (`N:629-633,1251`) | No ambient FD-control override found |
| Lock fields, registry `file/hash`, resource IDs | Producer identity; reviewed resource list; retained store | Exact lock identity comparison, canonical names, sorted registry, expected-byte deletion (`N:701-845,1806-1844`) | No additional lock-field validation finding identified under trusted-store/nonmutation premises |
| NativeResult stdout/stderr/times/termination/error/ownership/transportArgv | Actual streams/status plus producer lifecycle bookkeeping | Native event handling, UTF-8 check and downstream result classification (`N:380-433,1295-1318,1609-1642`; `R:762-790`) | Process attribution/termination defects remain CA-01/CA-02 |

## Lens 5 - Field-name fidelity

| Field | Implied semantic | Actual value | Status |
|---|---|---|---|
| `process_start_id` | OS process birth identity | Linux start ticks or Darwin start timeval (`N:460-499`) | faithful as a recorded observation; it is not a stable signaling handle |
| `children[].process` | Processes owned by this invocation | Direct/hosted gated identities plus census-admitted descendants | CA-01 can make this ownership label false |
| `terminated_at` | Original registered group was proven stopped | Assigned after `groupStopped()` returns true (`N:1101-1110`) | CA-02 can make the proof claim false; counted under lens 2 |
| SpawnWindow `closed` | No unresolved ownership interval remains | Native finalization predicates (`N:1511-1527,1565-1578`) | affected by CA-02; no separate finding |
| `transportArgv` | Actual wrapper command, distinct from subject argv | Bun gate invocation at `N:1059`; exact subject vector is passed separately at `N:1471` | faithful; no wrapper-as-subject substitution found |
| `termination.exit_code`, `signal`, `timed_out`, `cancelled` | Actual direct-child status and invocation interruptions | Bun terminal event plus native deadline/abort flags (`N:414-432,1289-1294,1113-1116`) | no fabricated normal exit found in these assignments |
| `stdout`, `stderr`, protocol-log `hash/size` | Exact captured bytes and retained-log commitment | Stream buffers and log bytes (`N:1295-1305,1071-1083,1609-1642`) | faithful in inspected code |
| `startedAt`, `finishedAt` | Invocation interval with millisecond containment | Start before pending/spawn work; upper-bound finish using `Date.now()+1` (`N:161-162,899,1631`) | consistent with V4's containing-millisecond interval convention |

## Lens 6 - Deferral justification audit

| Deferred finding | Justification claims | Claim audit | Verdict |
|---|---|---|---|
| Prior D host review's native ownership boundary | Native v4 lifecycle was external to that host review; abnormal collector ownership could remain indeterminate | `D/.fv/code-adversarial/2026-10-14-v4-host-review-2.md`, lens 6; current lifetime retention at `N:1511-1527,1565-1578` | The prior report did not claim native closure. CA-01/CA-02 are new native findings, not a retroactive host-review closure. |
| Prior portable review's native ownership/recovery boundary | Portable validation checks retained structure under producer/OS honesty, without historical PID lookup | `D/.fv/code-adversarial/2026-10-14-v4-portable-review-3.md`, scope and lens 2; store checks at `:420-447` | Valid boundary limitation. It does not excuse incorrect producer observations. |
| Approved lifecycle versus arbitrary hostile process containment | Approved children obey declared groups/gates; arbitrary escape containment is excluded | V4:330; native observer and indeterminate paths at `N:1432-1465,1511-1527` | Preserved. CA-01 uses ordinary exit/recycling, not hostile escape; CA-02 uses an unhandled query error. |
| Producer/store/cache/source assumptions | Local hashes do not authenticate execution, nondeletion, continuous nonmutation or generated-product correctness | D I11/I12; ledger TA-08; V4 operational and portable-validation sections | Preserved assumptions. No wrong-deferral finding identified. |
| Prior native-specific deferred finding | No native-specific deferred finding was located in the inspected relevant review records | Existing D host/portable reports explicitly excluded this implementation | Empty native-specific wrong-deferral set; absence of a prior finding is not evidence of correctness |

## Supplemental concurrency and process-ownership analysis

| Surface | Required property | Inspected mechanism | Result |
|---|---|---|---|
| Process-group lifetime across leader exit | Numeric ID reuse must not transfer ownership | `observe()` admits by numeric PGID/SID; `signalOwned()` uses separately observed identities and a later numeric `kill()` (`N:566-603,1432-1455`) | CA-01 |
| Concurrent native children | Separate launch gates, buffers, windows and private control channels | Per-call state and socket duplicates (`N:900-1044,1257-1288`); four-child backpressure test at `F/tests/r38_evidence_v4_lifecycle.py:1258-1380` | Separation present; tests inspected, not run |
| Collector registration | Subject must not execute before durable ownership ACK | Original collector gate and ACK sequence (`D/.fv/scripts/collect_quint_witness.py:350-376`); producer `N:1165-1235` | Ordering present; CA-03 affects the minimum argv boundary |
| Resource acquisition across worktrees | Complete set or no retained partial acquisition; common host lock namespace | Global admission lock, sorted set acquisition, rollback on conflict (`N:715-845`) | No additional finding in inspected paths; cross-root regression at lifecycle test `:1196-1257` |
| Key lock and member observations | Key ownership survives checkpoint and member-history work | `R:669,900-933` | Boundary wiring present; full history implementation not reviewed |

## Supplemental error-atomicity analysis

| Surface | Required property | Inspected mechanism | Result |
|---|---|---|---|
| Darwin census failure | Unknown liveness cannot become absence | Zero `proc_pidinfo` result is skipped without errno classification (`N:550-551`) | CA-02 |
| Durable owner mutation | Failed persistence cannot permit normal owner release | Expected-byte replacement and sticky storage failure (`N:663-678,862-873`) | Guard present |
| Launch failure before registration | No fabricated no-orphan conclusion | Pending window precedes spawn; catch retains indeterminate state when direct registration/drain proof is absent (`N:900-913,1565-1578`) | Guard present |
| Native exec failure | Preserve error and captured bytes rather than synthesize successful subject execution | Dedicated close-on-exec failure channel (`N:37,78-82,1477-1479`) | Guard present |
| Recovery | Account preserved original owner before releasing locks | `N:1783-1856`; production account callback `R:167-176` | Ordering present; complete group proof inherits CA-02 |
| Descriptor adoption failures | A duplicated descriptor must remain owned until transfer or explicit close | `N:945-1044` tracks duplicate identity and socket closure, but marks adoption before the existing-FD `connect` call | Not resolved by inspected sources. Bun's ownership-on-throw contract and an exercised failure case are needed before claiming this edge is closed; no consolidated finding asserted without that evidence. |

---

## Finding list (consolidated)

| ID | Lens | Severity | Surface | Intent ref | Code ref | Summary | Fix |
|---|---|---|---|---|---|---|---|
| CA-01 | clause-to-line | Major | Native process attribution and signaling | D I12 (`D/docs/intent.md:32`); V4 T2 and `V4:330,336,340` prohibit foreign/ambiguous signaling and require original process ownership | `N:566-603,1432-1455,1484-1500` | `[INFERENCE]` Ownership is not tied to a continuously retained group lifetime. The census admits a new process solely because its numeric PGID and SID equal an old registration, and skips existing numeric PIDs without checking their birth identity. After an original group disappears and its leader PID is recycled as a new session/group, a foreign child can therefore be registered under the old window. If the replacement leader is subsequently reaped, that falsely admitted child can satisfy `signalOwned()`'s known-birth anchor and be signaled. Independently, even a correctly observed final anchor may exit and be reaped between the last identity read and `process.kill(-pgid, signal)`, allowing the numeric target to be recycled. Neither schedule requires the approved command to escape its group. | Retain an OS identity/lifetime capability that prevents PGID reuse through the signal operation, or use an owned lifetime guardian plus a justified group-signaling protocol. Descendant admission must derive from a still-proven original group lifetime, not equality of recycled numeric PGID/SID values. When that proof is unavailable, refuse signaling and retain indeterminate ownership. Another pre-kill snapshot alone does not close the race. Add real-process regression coverage for original-leader exit, loss of the last anchor and foreign-group preservation. |
| CA-02 | clause-to-line | Major | Darwin process census, completion and recovery | D I12 (`D/docs/intent.md:32`); V4 B1/B2, `V4:330,340,554-556`: uncheckable termination remains indeterminate and cannot authorize PASS/release | `N:477-488,546-565,1101-1110,1484-1527,1778-1782`; `R:762-771` | `processTable()` treats every zero return from Darwin `proc_pidinfo` as a disappeared process, without checking errno. The same module's `readProcessIdentity()` correctly distinguishes ESRCH from unavailable identity. `[INFERENCE]` If a live same-group descendant produces a non-ESRCH query failure after its leader is gone, census omission can make `groupStopped()` return true. A descendant with closed output FDs does not prevent stream EOF. The producer can then stamp termination, close windows and supply a zero-exit PASS candidate, or recovery can retire ownership despite unknown surviving work. No occurrence of this OS-error condition was exercised in this review. | Apply the same fail-closed errno discipline to each Darwin census lookup: skip only a documented process-disappeared result; reject permission, unsupported, short and other unavailable observations. Propagate census failure to indeterminate ownership without releasing resources. Add Darwin coverage distinguishing disappeared processes from non-ESRCH failures while an owned group member remains alive. |
| CA-03 | clause-to-line | Minor | Collector gate argv validation | D I12 exact command preservation (`D/docs/intent.md:32`); `V4:27,334` allow nonempty argv and require the unchanged existing gate | `N:1711-1719`; `D/.fv/scripts/collect_quint_witness.py:32-40,350-360` | The approved wrapper has six transport elements before the subject: interpreter, `-I`, `-B`, `-c`, fixed gate code and gate FD. A valid one-element subject such as `[/usr/bin/true]` therefore produces seven argv elements. `verifyCollectorGate()` requires at least eight and rejects it. `[INFERENCE]` Calling the existing `ChildLifecycle`/`child()` with that valid subject fails before ACK and leaves the collector lifetime indeterminate rather than running the exact supplied command. Current multi-argument Quint coverage does not exercise this boundary. | Accept the seven-element minimum and validate the subject suffix using the existing nonempty NUL-free argv rule. Do not add a dummy argument or change collector/proof commands. Add a real original-collector lifecycle regression with a one-element subject and retain the existing malformed-gate rejection cases. |

## Summary

- Total findings: 3
- By severity: Critical=0 Major=2 Minor=1 Informational=0
- By lens: commitment-coverage=0 clause-to-line=3 deferred-cannot-silently-succeed=0 who-controls=0 field-name=0 deferral-justification=0
- Recommended next step: (1) Close CA-01's process-group lifetime attribution and signaling gap. (2) Make Darwin census errors fail closed for CA-02. (3) Correct the gate minimum for CA-03 without changing command grammar or proof budgets. The parent should exercise the new targeted process/error/argv regressions and then the existing native lifecycle suite after the corrections land. Resolve the Bun descriptor-adoption-on-throw evidence limit before making an all-error-path ownership claim. Preserve the separate store, observation, consumer and activation boundaries; this report does not establish a full-system verdict.
