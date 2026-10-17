# Code-adversarial review: Dossier evidence-producer boundary repairs - 2026-10-16

- Operator: fv-code-adversary via OMP task (NOT parent orchestrator)
- Code commit reviewed: `f630af8`, following repair `6214def`, baseline `e36b939`. Commit identifiers supplied by the caller; inspected worktree contents were not independently compared with Git objects.
- Intent version reviewed: frontmatter version absent. Canonical target resolved through `D/.fv/dispatch.json` to `D/docs/intent.md`; producer-relevant clauses I11–I14.
- Ledger version reviewed: frontmatter timestamp absent; ledger states `Updated: 2026-10-08`.
- Lens pack: crypto/enclave, supplemented by concurrency/process-lifetime, loader-boundary and error-propagation analysis.
- Lenses applied: 1 through 6.

## Scope and evidence

Aliases:

- `D` = `/Users/mv/Development/burnt/dossier-wt/evidence-perf`
- `F` = `/Users/mv/Development/reliq-fv-wt/evidence-collection-fix`
- `N` = `F/tools/evidence-v4/evidence-v4-native.ts`
- `R` = `F/tools/evidence-v4/evidence-v4-run.ts`
- `P` = `F/scripts/fv_evidence_v4.py`
- `V4` = `F/docs/execution-evidence-v4.md`
- `CR` = `F/.fv/changes/2026-10-14-execution-evidence-v4.md`
- `NR` = `F/tests/r38_evidence_v4_native_review.py`
- `LR` = `F/tests/r38_evidence_v4_lifecycle.py`
- `PR` = `F/tests/r38_evidence_v4_portable.py`

The review covers natural post-exit cleanup, retained-member termination proof, canonical minimum tool coverage, associated regressions and the “Fresh collection boundary repairs” change record. Relevant callers and persistence checks were traced. It does not re-audit Dossier’s protocol implementation or the complete producer provenance system.

The parent’s observation that 24 targeted methods passed is accepted as supplied evidence. No commands were rerun.

The isolated smoke receipt at `/var/folders/ph/n581g1fj3tnbq8n74hp05klc0000gn/T/fv-normal-exit-smoke-HR4NDe/result.json` records the unchanged Quint argv, exit zero, no timeout/cancellation, `error: null`, three terminated registrations and a closed direct window. Its stdout contains `No violation found (61112ms)`. This is native lifecycle evidence only. The receipt has null execution-key/attempt scope and does not establish canonical evidence acceptance or session-file removal.

Important uncovered classes include general authorization, arithmetic, migration, resource exhaustion, dependency authenticity, complete loader provenance, runtime internals and mechanized model-to-code correspondence. OS/runtime honesty and the approved-command lifecycle premise remain assumptions.

---

## Lens 1 - Commitment coverage

| Commitment | Attacker DoFs | Bound by | Gap |
|---|---|---|---|
| Direct launch frame | Selected executable, argv, cwd and semantic environment | `C({file, argv, cwd, environment})` at `N:1666-1672` | No omitted launch field identified in this repair. |
| Serialized owner | Child identities, windows, pending results and lifecycle transitions | Whole-record canonical serialization and expected-byte replacement at `N:801-815`; termination mutation at `N:1271-1285` | No new unbound ownership field identified. Correct serialization still depends on correct OS observations. |
| Execution artifact | Output bytes, termination, ownership, descriptor and result | `R:840-889`; whole-artifact digest at `evidence-v4-store.ts:481-485` | Ownership is retained in the hashed artifact. Natural completion does not replace it with an exit-code-only receipt. |
| Declared claim-tool associations | Additional tools, slot IDs, recipe bindings and omitted canonical tools | Canonical subset check at `P:1290-1295`; exact declared slot sequence and per-slot binding checks at `P:2725-2800` | The relaxed set comparison does not remove extra declared slots from assessment. |
| Signatures and enclave ReportData | No applicable surface in the bounded repair | None | Empty application-cryptography surface; no enclave commitment conclusion is drawn. |

## Lens 2 - Clause-to-line discharge

Statuses below concern the inspected producer boundary. `partial` identifies a broader obligation that this repair cannot discharge.

| Clause | Expected discharge | Actual code line | Status |
|---|---|---|---|
| D I11: valid source/tool/cache provenance | Completion remains subject to endpoint and toolchain validation | `R:814-834` | partial; completion checks remain, while generic provenance qualification is outside this repair. |
| D I12: preserve exact recipes and bounds | Cleanup must not rewrite the subject invocation | `N:1666-1676`; smoke receipt’s exact argv | discharged for the inspected boundary. |
| D I12 and V4 S1: preserve all logical slots | Canonical minimum plus every policy-declared slot | `P:1290-1295,2496-2524,2725-2800,2971-2984` | discharged for minimum coverage and full declared-slot assessment. |
| V4 S2: execution-owned raw bytes | Retain actual stdout/stderr under their execution | `N:1472-1484,1797-1820`; `R:840-881` | discharged for the inspected capture/publication handoff. |
| V4 B1: closed ownership before PASS | Prove stopped groups and original registered births before retirement | `N:1238-1285,1684-1689`; `R:128-133,773-782` | discharged under the declared OS and command-lifecycle assumptions. |
| V4 B2; D I12: cancelled or timed-out work cannot PASS | Preserve interruption flags and reject normal-success classification | `N:1288-1292,1410-1417,1529-1547,1818-1820`; `R:120-125,773-782` | discharged by code inspection. |
| V4 T1: failure propagation and durable accounting | Halt dispatch, retain actual result/history, clear pending only after closure | `R:811-812,895-931`; `N:1031-1032` | discharged for the inspected failure handoff; complete scheduling proof remains outside scope. |
| V4 T2: no live/indeterminate ownership theft | Retain resources/session and refuse same-boot recovery of nonclosed windows | `N:938-939,1003-1012,1968-1981` | discharged for the inspected guards. |
| V4:334: observed escapes cannot count as termination | Check retained original births even after the old group becomes empty | `N:1238-1255` | discharged for registered members surviving the observer gap. |
| V4:344: bounded cleanup and output draining | Use the existing grace and require drained streams/control | `N:27,1299-1328,1687-1693` | discharged. Five seconds is a grace interval, not an overall upper bound on every cleanup phase combined. |
| V4:346: signal only with a retained lifetime capability | Keep runtime, birth, session and unreaped-child checks | `N:692-755` | discharged at the wrapper; Bun’s underlying reaping guarantee remains an external premise. |
| D I13/I14: activation and authority separation | Local repair/smoke must not promote failed evidence or authorize deployment | `R:773-782`; `CR:154-164` | partial by scope; no activation or deployment operation was performed. |
| Ledger C-01 through C-15 | Preserve incomplete composition claims | `D/.fv/ledger.md` candidate statuses; local execution classification at `R:773-782` | partial; none of these composition candidates is discharged by this repair. |
| Ledger TA-08 and other trust assumptions | Preserve evidence-producer honesty and external platform/protocol assumptions | Unsigned local artifact construction at `R:863-889`; ledger trust-boundary inventory | partial by explicit trust. TA-01–TA-07 and TA-09–TA-17 are outside this producer correction. |

## Lens 3 - Deferred cannot silently succeed

| Branch | Reachable from | Behavior | Status |
|---|---|---|---|
| TODO/stub/mock/deferred implementation in the changed production paths | Native completion and portable coverage | No such production-success branch identified by source search | Empty deferred-success finding set. |
| Post-exit group remains alive | Normal cleanup | `terminated()` throws; error cleanup retains unresolved ownership (`N:1271-1272,1687-1689,1738-1760`) | Explicit failure. |
| Registered original birth survives outside the stopped group | Post-exit polling or final termination proof | Throws and sets sticky `escaped` (`N:1248-1255`) | Explicit failure. |
| Signal capability unavailable | Cancellation/error cleanup | Refuses signaling; sticky uncertainty remains (`N:692-755,1258-1268`) | Explicit failure, including unsupported runtimes. |
| Streams/control cannot be drained | Normal or abnormal cleanup | Error and/or indeterminate windows (`N:1691-1693,1728-1760,1782-1787`) | No timeout-based fabricated closure. |
| Canonical required tool missing | Portable policy loading | Subset check fails (`P:1290-1295`) | Explicit rejection. |
| Additional declared slot lacks valid evidence | Full claim assessment | Slot remains missing/error; all-slot conjunction prevents PASS (`P:2777-2800,2971-2984`) | No silent omission. |

## Lens 4 - Who controls

| Field | Supplier | Validation | Gap |
|---|---|---|---|
| Process PID, birth, parent, group and session | OS; collector supplies a candidate PID on its private channel | OS identity reads, direct-child checks, hosted gate checks and live-anchor checks (`N:477-515,675-690,1349-1371,1582-1590`) | No new weakly validated supplier identified. |
| `registered_at`, `window_id` | Producer | Serialized registration before admission (`N:1224-1236`) | None identified in scope. |
| `terminated_at` | Producer termination proof | Empty original group plus no surviving unfinished original member (`N:1238-1285`) | None identified for the repaired observer-gap case. |
| Window state | Producer lifecycle | Sticky escape state, stream completion and registration accounting (`N:1695-1711,1747-1760`) | Later natural exit does not clear prior uncertainty. |
| Exit status and interruption flags | Native exit event, deadline and abort callbacks | Actual event capture and explicit flags (`N:1461-1466,1288-1292,1410-1417,1529-1547`) | None identified. |
| Canonical `required_evidence` | Reviewed manifest | Portable subset check and producer membership loop (`P:1290-1295`; `evidence-v4-policy.ts:355-358`) | Extra tools are permitted; missing required tools are rejected. |
| Additional policy executions | Reviewed policy | Every declared slot is expanded and assessed (`P:2496-2524,2725-2800`) | No optional-extra-slot interpretation introduced. |
| Original failed owner | Retained producer record | Expected serialized owner, host/boot and nonclosed-window recovery guards (`N:1949-1983`) | This correction grants no recovery authority over the failed owner. |

## Lens 5 - Field-name fidelity

| Field | Implied semantic | Actual value | Status |
|---|---|---|---|
| `terminated_at` | Observed termination of the registered original process/group | Set only after `stopped()` succeeds; matching group/session registrations retire together (`N:1271-1285`) | Faithful in the inspected path. |
| `spawn_windows[].state = "closed"` | Accounted ownership closure | Requires termination and stream/protocol conditions; sticky escape blocks closure (`N:1695-1711,1747-1760`) | Faithful under the declared lifecycle premise. |
| `termination.exit_code` | Direct subject’s exit status | Native exit event (`N:1461-1466`) | Faithful; zero does not imply evidence PASS. |
| `termination.timed_out`, `cancelled` | Deadline or cancellation occurred | Dedicated callbacks and retained flags (`N:1288-1292,1410-1417,1529-1547`) | Faithful. |
| Execution `result` | Producer evidence outcome | Error/ownership checks precede status and marker acceptance (`R:773-812`) | Faithful. Historical exit-zero artifacts remain ERROR. |
| `required_evidence` | Minimum canonical tool coverage | Required subset of policy tools (`P:1290-1295`) | Faithful; every extra declared slot remains conjunctive. |
| Smoke `error: null` | Native invocation completed without recorded native error | Isolated native result, without canonical execution binding | Faithful only at native scope; it must not be labeled canonical PASS. |

## Lens 6 - Deferral justification audit

| Deferred finding | Justification claims | Claim audit | Verdict |
|---|---|---|---|
| Prior classifier’s retained-anchor redesign recommendation | Post-exit signaling needs an unreaped anchor; successful natural completion may avoid signaling entirely | `N:1684-1689` waits without signaling, then requires termination proof; signal guard remains at `N:692-755` | Bounded alternative is supported. It does not provide active cleanup of surviving post-exit descendants. |
| Prior native round-3 CA-01: false escape on reused member PID | A different birth must not be treated as the original process escaping | `N:679-685,1612-1620` distinguish original birth from replacement; `NR:237-359` covers reused-member admission and anchor behavior | Current code addresses the cited case. |
| Earlier assumption that group emptiness sufficed despite a registered member escaping | Approved commands prohibit escapes; group emptiness was used to stamp all registrations | Current `N:1238-1255` checks unfinished original members independently. `NR:691-764` exercises a real `setsid()` after the last observer census | The earlier limitation is no longer relied upon for registered survivors. |
| Unsupported-runtime signaling remains refused | Without the runtime capability, signaling is unsafe; error reporting must preserve ownership | `N:711-742,1792-1794,1805-1813`; `NR:877-910` retains uncertainty after later exit | Deferral remains explicit and fail-closed. |
| Original failed collection remains unrecoverable on the same boot | Later disappearance, source fixes and unrelated smoke success cannot close its historical indeterminate window | Same-boot guard at `N:1968-1981`; original EX-001 receipt retains its indeterminate window and ERROR | Supported. No retirement or promotion was performed. |
| Generic provenance, cross-run reuse and activation remain unqualified | Local lifecycle/coverage checks do not establish those broader claims | `CR:150,160-164`; D I11–I14 and ledger incomplete statuses | Preserved as outstanding work; no wrong-deferral finding established in this slice. |

## Concurrency and loader supplement

| Boundary | Adversarial case | Evidence and disposition |
|---|---|---|
| Observer shutdown → natural drain | Registered child calls `setsid()` after periodic observation stops | `stopped()` now checks the surviving original birth after group emptiness. The regression waits for post-exit polling before releasing the escape (`NR:724-738`). It requires an error, release refusal and an indeterminate window. |
| Proof → retirement | A caller reaches `terminated()` without a successful preceding poll | `terminated()` performs its own `stopped()` check (`N:1271-1272`); it does not trust the loop’s prior result. |
| PID reuse | Leader number recycled, versus unrelated replacement of a former member | Leader mismatch refuses termination proof (`N:687-690`). Member checks compare birth identity; foreign replacement is not signaled. These cases must remain distinct. |
| Cancellation/deadline during cleanup | Marker or exit zero precedes interruption | Flags remain active until final cleanup; `R:120-125,773-782` excludes interrupted success. Existing cancellation and timeout tests cover retained bytes and abnormal outcomes (`LR:750-850,1608-1668`). No separate interruption-during-natural-drain experiment was supplied. |
| Native result → session/resource/history | Ownership failure follows a successful solver result | Dispatch/release guards remain; `R:895-931` persists the actual result and clears pending/releases resources only for closed ownership. Original EX-001 and EX-002 receipts still report ERROR. |
| Policy loader → portable assessment | Canonical minimum is smaller than the reviewed slot set | `PR:403-442` covers extra-slot success, extra-slot observation failure and missing-canonical-tool rejection on both paths. |
| Exact executable boundary | Repair changes invocation semantics to obtain completion | Launch serialization retains executable, argv, cwd and environment (`N:1666-1672`). No retry, shell wrapper or changed Quint bound was introduced by the inspected completion path. Complete toolchain/loader qualification remains outside scope. |

The new termination check covers retained registered members. It does not create continuous process containment: an unregistered descendant that escapes entirely between censuses remains outside the guarantee expressly stated in V4:334.

---

## Finding list (consolidated)

| ID | Lens | Severity | Surface | Intent ref | Code ref | Summary | Fix |
|---|---|---|---|---|---|---|---|
| None | — | — | Bounded repair | — | — | No actionable defect with both intent and code evidence was established in the inspected repair. | No patch requested by this review. |

## Summary

- Total findings: 0
- By severity: Critical=0 Major=0 Minor=0 Informational=0
- By lens: commitment-coverage=0 clause-to-line=0 deferred-cannot-silently-succeed=0 who-controls=0 field-name=0 deferral-justification=0
- Recommended next step: parent performs the planned frozen-tree regression verification, including lifecycle cancellation/deadline, native-review and portable coverage suites. Preserve the failed owner and artifacts; keep cross-run reuse disabled and generic provenance/activation unqualified.
- Evidence limit: the supplied 24-method result and isolated smoke support the bounded correction. They do not establish canonical collection success, universal process containment or complete producer correctness.

Skipped command execution, builds, tests, formatting, file edits and process operations. The historical owner remains unresolved; the successful smoke supplies no authority to retire it or promote its failed evidence.