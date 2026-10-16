# Code-adversarial review: FV v4 evidence producer store (round 2) - 2026-10-15

- Operator: fv-code-adversary via OMP task (NOT openai-codex/gpt-6.1-sol task agents FixNativeOwnership-2, FixProducerStore-2, FixSourceBindings-2, FixAdoptionDashboard-2, FixBaseToolchain, FixRustToolchain, FixProofToolchain, nor the parent orchestrator)
- Code commit reviewed: `6c787c20f023a132856cf5119b137be25dd2303f` (round-1 target `aa6946f`); the caller supplied this attribution and it was not recomputed
- Intent version reviewed: `F/docs/execution-evidence-v4.md` has no frontmatter version (Status line: "normative contract for the opt-in `fv-evidence-run/v4` producer"). Also reviewed: `F/.fv/changes/2026-10-14-execution-evidence-v4.md:113-127` "Post-commit review dispositions (2026-10-15)"
- Ledger version reviewed: absent (`F/.fv/ledger.md` does not exist)
- Lens pack: crypto/enclave, supplemented with concurrency/liveness, crash-durability and error-atomicity analysis
- Lenses applied: 1 through 6

## Intent resolution and scope

`F` = `/Users/mv/Development/reliq-fv-wt/evidence-perf`. `V4` = `F/docs/execution-evidence-v4.md`. `CR` = the change record above.

**Gate deviation, stated explicitly.** `F/.fv/dispatch.json` is absent. The strict canonical target is therefore `F/.fv/intent.md`, and that file is also absent. Under the agent's isolation gate this resolves to `STATUS: BLOCKED`. This review instead uses the normative contract the caller named (V4 plus the CR dispositions). Round 1 did the same thing (`2026-10-15-producer-store-review-1.md`), going through `D/.fv/dispatch.json` → `D/docs/intent.md` with V4 as the normative dependency. The orchestrator may reject this report on gate grounds.

Code inspected:
- `F/tools/evidence-v4/evidence-v4-store.ts` (`store`)
- `F/tools/evidence-v4/evidence-v4-run.ts` (`run`), store-related parts
- `F/tests/r38_evidence_v4_store_review.py` (`test`)

Cited call edges led into:
- `evidence-v4-native.ts` (`native`): lock acquisition and recovery
- `F/scripts/fv_evidence_v4.py` (`py`): `_raw`
- `D/.fv/execution-policy.json`: resource sets

No `git diff` was possible, because no shell was available in this session. Closure verdicts come from current-code reads. No commands, tests or builds were run. The parent's 150/150 Darwin and 114-test Linux results are accepted as reported. Accepted known limits are not re-raised: Linux and other runtimes refuse group signaling and stay indeterminate (V4:342; CR:127), and Lake coverage is Lean-specific.

Uncovered classes: access control, arithmetic, supply chain, exhaustive resource exhaustion, and actual power-loss behavior of the filesystems (fsync semantics are taken as given).

## Round-1 closure verdicts

| Round-1 finding | Verdict | Evidence |
|---|---|---|
| R1-CA-01 (Major): a swallowed fatal observation error strands the next shared member on a session-held checker lock | **closed for observation-originated fatal errors**; residual sibling below as new CA-02 | `run:1148-1154`: the catch marks ERROR, calls `fail`, aborts `observationAbort` when `pending !== null` or the error is not a cancellation, then **rethrows**. The fresh member loop (`run:928`) and the cached loop (`run:707-716`) no longer continue after a fatal error. Admitted waiters pass `AbortSignal.any([this.signal, this.observationAbort.signal])` into `acquireResources` (`run:960-964`), and `native:165-172,966-977` abort the poll loop. A release failure also aborts (`run:1164-1166`). A semantic FAIL still returns normally, so the remaining members…
| R1-CA-02 (Minor): recovery accepts a visible history event without repeating its durability barrier | **closed for the history event**; same-class residual on the recovered-owner snapshot below as new CA-03 | `store:1190-1201`: for an existing matching event, recovery opens it, `fsync`s the file, then calls `syncAncestors(history dir → root)` before pushing the ref. Errors propagate out of `withAppendLock`. `native:1977-2032` calls `account` before any lock removal or owner rename. So a barrier failure leaves the owner and its locks in place. Tests: `test:312` (barrier order before retirement) and `test:363` (a barrier failure keeps pending owner and locks). |
| Trailer change (CR:119): abnormal trailer renders the artifact's own result | **store/portable agreement achieved; producer construction is inconsistent**, see new CA-01 | `store:324-338` and `py:791-809` (caller `py:898` passes `artifact["result"]`) are byte-identical in rule. But `run:784` builds `raw` from the provisional `result`, and `run:785-802` can then change CANCELLED to ERROR. |

---

## Lens 1 - Commitment coverage

| Commitment | Attacker DoFs | Bound by | Gap |
|---|---|---|---|
| `raw.log` reconstruction | Command stdout/stderr bytes, termination fields, artifact result | `store:324-338` (trailer from termination normality plus `result`); `store:577-579` checks raw against the artifact's own termination/result; `py:791-809,898` match it | No coverage gap: every DoF is bound. CA-01 concerns the producer computing the value from a pre-final result. That is an internal-consistency defect, not an unbound field. |
| History event (recovered existing event) | Event bytes, sequence, chain, pending match | Unchanged hash-chain validation at `store:846-899`; the match predicate at `store:1176-1189` binds key, attempt, claim, slot, kind, and run-scoped observation path or preserved owner | None identified |
| Indeterminate event `indeterminate_owner` | Recovered owner bytes | `store:822-824` reads and validates the owner snapshot by FileRef and path | No binding gap. CA-03 concerns its durability, which a hash cannot establish. |

## Lens 2 - Clause-to-line discharge

| Clause | Expected discharge | Actual code line | Status |
|---|---|---|---|
| V4:19 T1, "in-flight work is accounted for"; V4:462, "On storage failure return ERROR" (observation origin) | Fatal observation error ends member iteration and wakes same-session waiters | `run:1148-1154,960-964,707-716,928`; `native:966-977` | discharged |
| V4:19 T1 / V4:462 (execution-checkpoint origin) | Execution storage failure with retained resources must not strand an admitted observer waiting on an overlapping resource | `run:930-946`: catch rethrows but never aborts `observationAbort`; finally retains locks when `pending !== null`; `native:846`: a session-held lock returns null and the poll repeats | **partial**: CA-02 |
| V4:462: semantic member FAIL keeps observing siblings | Do not abort on a completed FAIL | `run:1106` sets `halted` only; observe returns normally | discharged |
| V4:460: any barrier error prevents acknowledgment and PASS cache eligibility | Existing visible event re-synced before acknowledgment | `store:1190-1201` | discharged |
| V4:486: "Failure to durably account for the window keeps history/ownership ERROR" | Every artifact the recovery event depends on is durable before retirement | History event: `store:1190-1201` discharged. Recovered owner snapshot: `store:1104-1114` returns an existing snapshot without any barrier. | **partial**: CA-03 |
| V4:559: account pending results before retirement | `account` precedes lock removal and owner rename | `native:1977-2032`; `run:168-178` | discharged |
| V4:414: abnormal trailer `result=<ERROR or CANCELLED>`, never an invented exit | Trailer reflects the artifact's result | `store:330-336`; `py:802-808` | discharged in store and portable checker |
| V4:340: "Invalid UTF-8 is ERROR with exact captured bytes retained"; V4:462: "Retain failure/error/cancellation artifacts/events when storage works" | A cancelled run with invalid UTF-8 or a reserved trailer publishes an ERROR artifact | `run:784` computes `raw` with `result="CANCELLED"`; `run:798-802` sets `result="ERROR"`; `store:527,577-579` throw "raw output reconstruction mismatch" before rename | **gap**: CA-01 |
| V4:18 B2 / V4:460: no PASS or cache eligibility after a barrier failure | Visible but non-durable events cannot yield PASS | Run level: `run:291-302` (fail → `operationalError`) plus `run:1258-1266` (manifest ERROR). Cache: `store:1063-1074` requires a subsequent PASS observation, and observe reruns the checker on a hit (`run:707-716`). Without recovery, the unaccounted receipt/attempt fails `validateAttemptAccounting` / `validateObservationAccounting` (`store:900-998`). | discharged; no PASS path found |

## Lens 3 - Deferred cannot silently succeed

| Branch | Reachable from | Behavior | Status |
|---|---|---|---|
| TODO/stub/mock/deferred in the delta | store, run delta | None found in the inspected regions | Empty finding set. This does not establish correctness. |
| `observationAbort` short-circuit | `run()` after collection | Forces `result: "ERROR"` (`run:478-483`) | Explicit failure, not silent success |
| Recovery existing-event branch | `recoverEvidenceV4Owner` | Now performs barriers; a barrier error throws | Explicit failure |

## Lens 4 - Who controls

| Field | Supplier | Validation | Gap |
|---|---|---|---|
| `raw.log` bytes | Producer, from actual streams and the then-current `result` | Store revalidates against the final artifact result (`store:577-579`) | CA-01: the producer supplies a value its own store rejects |
| `claim_checker.resources` and `Recipe.resources` | Reviewed policy | No disjointness rule (`policy:100-113`; V4:532 allows any reviewed IDs) | CA-02 needs an overlap. The Dossier checker uses only `project-checker` (`D/.fv/execution-policy.json:1104-1106`) and no Dossier recipe holds it, so Dossier does not exhibit it. |
| Recovered owner snapshot | Producer recovery | Byte equality only on reuse (`store:1104-1114`) | CA-03: durability is not re-established on reuse |
| PendingResult (observation/execution) | Producer | Retained on storage failure (`run:1147,936`) | None new |

## Lens 5 - Field-name fidelity

| Field | Implied semantic | Actual value | Status |
|---|---|---|---|
| `raw.log` trailer `result=` | The artifact's recorded result | Store/portable: `artifact.result`. Producer: the pre-reclassification result. | Never persisted, because the store rejects the mismatch, so no published artifact carries an unfaithful trailer. Counted under CA-01. |
| `RunResult.result` after an observation fatal | Operational outcome | ERROR (`run:478-483`); the manifest result is ERROR via `operationalError` (`run:1258-1263`) | faithful |
| SlotAssessment `state` after a fatal error with an appended FAIL event | Retained association outcome | Set to ERROR in the catch (`run:1150`), then restored to FAIL from history (`run:1221-1226`) | faithful after full assessment |

## Lens 6 - Deferral justification audit

| Deferred finding | Justification claims | Claim audit | Verdict |
|---|---|---|---|
| CR:119 Producer store disposition (treated as a closure claim, not a deferral) | (1) Fatal observation errors stop fresh and cached loops and admitted waiters. (2) Recovery fsyncs the event, its directory and ancestors before retirement. (3) The abnormal trailer renders the artifact's own result, matching the portable checker. | (1) True for observation-originated errors (`run:1148-1154`); the claim does not cover execution-originated errors (CA-02). (2) True (`store:1190-1201`). (3) True for store/py; false at the producer construction site `run:784`, where the result can still change (CA-01). | No wrong-deferral. Claim (3) is overstated; counted under CA-01. |
| Accepted limits (CR:127): Linux group-signal refusal, Lake-only coverage | Out of slice | Not contradicted by the inspected store/run code | Not re-raised |

---

## Finding list (consolidated)

| ID | Lens | Severity | Surface | Intent ref | Code ref | Summary | Fix |
|---|---|---|---|---|---|---|---|
| CA-01 | clause-to-line (also lens 6, CR:119 claim 3) | Minor | Producer execution artifact construction | V4:340, V4:414, V4:462 | `run:776-788`, especially `:784` (`raw` built from the provisional `result`); `run:785-802` (CANCELLED → ERROR on invalid UTF-8 or reserved trailer); `run:816-829` (metadata error: `if (result !== "FAIL") result = "ERROR"`); `store:527,577-579` | **New, introduced by the trailer change.** The trailer now depends on `result`, but the producer renders it before its final classification. `[INFERENCE]` Counterexample: the user cancels mid-write and the child is killed while emitting a multibyte character. Termination is `cancelled`, ownership is closed, initial `result=CANCELLED`, and `raw` ends with `result=CANCELLED`. `decodeUTF8…
| CA-02 | clause-to-line | Minor | Producer scheduling liveness (generic policy) | V4:19 T1, V4:462, V4:496 | `run:888-911` (checkpoint throw leaves `pending`); `run:930-946` (catch rethrows without aborting `observationAbort`; finally retains locks while `pending !== null`); `run:960-964` (waiter signal = user signal plus `observationAbort` only); `native:846` (session-held lock → null), `native:966-977` (unbounded poll); `run:657-660` (scheduler awaits all active work) | **Residual sibling of R1-CA-01, not covered by the fix.** Policy validation lets `claim_checker.resources` overlap a recipe's resources. `[INFERENCE]` Counterexample: the checker and recipe A both hold `R`, jobs=2. Physical B passes, then B's `observe` polls for `R` while A runs. A's `publ…
| CA-03 | clause-to-line | Minor | Recovery durability | V4:460, V4:486, V4:559 | `store:1104-1114` (`preserveRecoveredOwner` returns an existing snapshot without fsync of the file or `recovered-owners/`); consumers `store:822-824,989`; retirement `native:2023-2032` | **Pre-existing; same class as R1-CA-02 and not reached by its fix.** `[INFERENCE]` Counterexample: recovery attempt 1 writes `recovered-owners/<id>.json`; `immutableFile` links it, then `syncAncestors` fails (`store:269`), and recovery aborts correctly. Attempt 2 finds the visible snapshot byte-equal and returns it with no barrier. It appends an indeterminate event (barriers on the history dir only) and retires the owner. A later power loss can drop the never-synced directory entry while the ev…

## Summary

- Total findings: 3
- By severity: Critical=0 Major=0 Minor=3 Informational=0
- By lens: commitment-coverage=0 clause-to-line=3 deferred-cannot-silently-succeed=0 who-controls=0 field-name=0 deferral-justification=0 (CA-01 also contradicts CR:119 claim 3; that overlap is not counted twice)
- Round-1 closure: R1-CA-01 closed for observation-origin errors (execution-origin sibling is CA-02); R1-CA-02 closed for history events (owner-snapshot sibling is CA-03). Store and portable checker agree on the trailer rule; the producer site is CA-01.
- No PASS or cache eligibility was found reachable after a barrier failure in the inspected paths. A run-level fatal error forces ERROR. A cache hit requires a subsequent PASS observation event and reruns the checker. Unaccounted receipts and attempts fail history validation until recovery.
- Recommended next step:
  1. CA-01: move the `raw` construction after final classification, and test cancellation with invalid UTF-8 or a reserved trailer.
  2. CA-02: abort `observationAbort` on an execution fatal error that leaves a pending result, and test overlapping resources.
  3. CA-03: add barriers on recovered-owner snapshot reuse, and test the retry.
  4. Then rerun `r38_evidence_v4_store_review.py`, `r38_evidence_v4_lifecycle.py`, the portable and cache suites, and `m4_v4_coverage.py`.
- Not checked: the aa6946f..6c787c2 diff itself (no shell available); native internals beyond lock and recovery call edges. All counterexamples are static deductions and were not reproduced. The gate deviation in the scope section must be accepted before this report counts as the round-2 record.
