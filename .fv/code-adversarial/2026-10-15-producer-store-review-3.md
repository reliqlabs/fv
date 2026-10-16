# Code-adversarial review: FV v4 evidence producer store (round 3) - 2026-10-15

- Operator: fv-code-adversary via OMP task (NOT openai-codex/gpt-6.1-sol task agents R2FixBase, R2FixRust, R2FixProof, R2FixStore, R2FixNative, R2FixAdoption, nor the parent orchestrator)
- Code commit reviewed: `34a7240` (parent `6c787c2`, the round-2 target). The caller supplied this; I did not recompute it.
- Intent version reviewed: `F/docs/execution-evidence-v4.md` has no frontmatter version. Also reviewed: `F/.fv/changes/2026-10-14-execution-evidence-v4.md:129-144` "Round-2 review dispositions (2026-10-15)".
- Ledger version reviewed: absent (`F/.fv/ledger.md` does not exist)
- Lens pack: crypto/enclave, plus concurrency/liveness, crash-durability and error-atomicity analysis
- Lenses applied: 1 through 6

## Intent resolution and scope

`F` = `/Users/mv/Development/reliq-fv-wt/evidence-perf`. `D` = `/Users/mv/Development/burnt/dossier-wt/evidence-perf`. `V4` = `F/docs/execution-evidence-v4.md`. `CR` = the change record above.

**Gate deviation.** `F/.fv/dispatch.json` does not exist. The strict canonical target, `F/.fv/intent.md`, does not exist either. Under the isolation gate that means `STATUS: BLOCKED`. I followed the caller's instruction and rounds 1-2 instead, using V4 plus the CR dispositions. The orchestrator may reject this report on gate grounds.

Code inspected: `F/tools/evidence-v4/evidence-v4-store.ts` (`store`), the store-related parts of `evidence-v4-run.ts` (`run`), `evidence-v4-policy.ts` (`policy`) and `F/tests/r38_evidence_v4_store_review.py` (`test`). Call edges led into `evidence-v4-native.ts` (`native`: lock acquisition) and `D/.fv/execution-policy.json` (resource sets). No shell was available, so I could not diff `6c787c2..34a7240`; the verdicts come from reading the current code. I ran nothing. The parent's 216/216 Darwin result is accepted as reported. Accepted limits are not re-raised.

Classes not covered: access control, arithmetic, supply chain, exhaustive resource exhaustion, real power-loss behaviour of the filesystems (fsync semantics taken as given), and native lock/ownership internals beyond the call edges listed.

## Round-2 closure verdicts

| Round-2 finding | Verdict | Evidence |
|---|---|---|
| R2-CA-01 (Minor): abnormal `raw.log` trailer was rendered before the final result classification | **closed** | `run:795`: on normal termination, raw output is built early (`normalRaw`). For normal termination, `reconstructRawOutput` ignores `result` (`store:330-336`), so the later reclassifications at `run:803,833,850` cannot change its bytes. `run:855`: on abnormal termination, raw output is built after every reclassification (UTF-8/trailer catch `run:802-806`, metadata `run:816-841`, attachments `run:845-854`). Nothing changes `result` between `:855` and `publishExecution` (`run:894`). An abnormal result can only be ERROR or CANCELLED: the initial classification is `run:778-787`, PASS→FAIL happens only on the normal branch (`run:797`), and the metadata …
| R2-CA-02 (Minor): checker/recipe resource overlap could leave an observer waiting on a session-held execution lock | **closed by refusal** | `policy:108-110` rejects any recipe resource that is also in `claim_checker.resources`. This discharges V4:354. `build_cache.resources` must be a subset of the recipe's resources (`policy:115-116`), so it is covered too. With the sets disjoint, a waiting observer (`run:966-970`) can only wait on checker resources. The other in-session holders of those resources are: preflight, which releases through `withNativeLock` before scheduling (`run:514-528,575-577`); and sibling observers, which abort `observationAbort` on any fatal error that leaves a pending result (`run:1159`) or on a release failure (`run:1171`). The sched…
| R2-CA-03 (Minor): reusing a recovered-owner snapshot skipped the durability barrier | **closed** | `store:1102-1121`: when an existing byte-equal snapshot is reused, the file is opened and `fsync`ed, then `syncAncestors(dirname → root)` runs before the FileRef is returned. Errors other than ENOENT propagate out of `withAppendLock` (`store:1174-1175`) before any history append or lock retirement. Test `test:513` injects a failure at each barrier, checks that the owner and locks are retained, then checks the order on a successful retry. |

---

## Lens 1 - Commitment coverage

| Commitment | Attacker DoFs | Bound by | Gap |
|---|---|---|---|
| `raw.log` reconstruction | stdout/stderr bytes, termination, final result | `store:322-338`; store checks at `store:577-579` on publish (`:526`, staged `:563-568`) and on read (`readExecution`) | None. The producer's value is now computed from the final `result` (R2-CA-01 closed). |
| Recovered-owner FileRef inside indeterminate events | Snapshot bytes | `store:1106-1107` byte equality; `store:822-824` reads and checks the path | None |
| History events reused during recovery | Event bytes, match predicate | `store:1182-1196`, then barriers at `:1197-1209` | None |

## Lens 2 - Clause-to-line discharge

| Clause | Expected discharge | Actual code line | Status |
|---|---|---|---|
| V4:354 checker/recipe resources disjoint; policy validation rejects | Reject at load, before discovery | `policy:108-110`, reached from `loadPolicy` at `policy:269` | discharged |
| V4:420 abnormal trailer `result=<ERROR or CANCELLED>`, never an invented exit | Trailer reflects the artifact's final result | `run:855` after final classification; `store:330-336` | discharged |
| V4:420 invalid UTF-8 / reserved trailer prevents PASS | Producer and store agree | `run:788-806`; `store:582-596` | discharged |
| V4:464 recursive barrier on recovered-owner records | Snapshot file and ancestors fsynced on create and on reuse | Create: `immutableFile` `store:261-269`. Reuse: `store:1108-1115` | discharged |
| V4:466 any barrier error prevents acknowledgement | Errors propagate before acknowledgement or retirement | `store:1174-1215`; `native` retirement runs after `account` (round-2 evidence, not re-inspected) | discharged |
| V4:492 / V4:565 preserve the snapshot and account pending results before retiring | Order: snapshot, aliases, events, then retirement | `store:1175-1176,1178-1229` | discharged |
| V4:19 T1 / V4:466 no stranded waiter after a fatal storage error (generic policy) | Unreachable by policy, or abort | Disjointness (`policy:108-110`) plus `run:1159,1171` | discharged |

## Lens 3 - Deferred cannot silently succeed

| Branch | Reachable from | Behavior | Status |
|---|---|---|---|
| TODO/stub/mock/deferred in the inspected store/run/policy regions | — | None found | Empty finding set. This does not show the code is correct. |
| `observationAbort` short-circuit | `run()` | Forces ERROR (`run:478-483`) | Fails explicitly |
| Snapshot reuse with an fsync error | `accountPending` | Throws | Fails explicitly |

## Lens 4 - Who controls

| Field | Supplier | Validation | Gap |
|---|---|---|---|
| `claim_checker.resources`, `Recipe.resources` | Reviewed policy | Disjointness at `policy:108-110` | None |
| `raw.log` bytes | Producer | Store re-derives it from the final artifact (`store:577-579`) | None |
| Recovered-owner snapshot | Producer recovery | Byte equality plus barrier on reuse (`store:1106-1115`) | None |

## Lens 5 - Field-name fidelity

| Field | Implied semantic | Actual value | Status |
|---|---|---|---|
| `raw.log` trailer `result=` | Artifact's recorded result | Final `result` (`run:855`) | faithful |
| `marker_matched` | Marker evaluated on valid streams | `run:796,856` matches `store:595` | faithful |
| `indeterminate_owner` | Durable snapshot of the dead owner | FileRef built from existing bytes after barriers (`store:1115`) | faithful |

## Lens 6 - Deferral justification audit

| Deferred finding | Justification claims | Claim audit | Verdict |
|---|---|---|---|
| R2-CA-02 refused at discovery (CR:135) | (1) A checker/recipe overlap is required for the stranded-waiter trace. (2) Policy validation rejects the overlap. (3) Dossier is unaffected. | (1) True: an observer waits only on `checker.resources` (`run:966-970`), and an execution-origin fatal error retains only recipe and key locks (`run:944-955`). (2) True: `policy:108-110`. (3) True: `D:1104-1106` plus the recipe sets listed above. | Correct refusal |
| CR:135 CA-01 "rendered after the final classification" | Claim as stated | True (`run:795,855`) | Holds |
| CR:135 CA-03 "snapshot gets a durability barrier" | Claim as stated | True (`store:1108-1115`) | Holds |

## Considered and not raised (below the convergence bar)

- **A crash between `link` and `unlink` leaves a hardlinked alias.** `immutableFile` links the staged file into place and then unlinks the staging copy (`store:261-262`). A crash between those two calls leaves the published file with nlink 2. `readBytes` (`store:189-192`) and `walk` (`store:291`) refuse nlink≠1. Recovery only removes aliases of *history* events (`retireRecoveredHistoryAliases`, `store:1122-1171`, regex `:1126`). A stale alias for a recovered-owner snapshot therefore makes recovery refuse permanently. A stale alias for an observation file (`runs/*/observations`, walked by `validateObservationAccounting`) makes every history load fail. `[INFERENCE]` Both cases fail closed and need manual removal of the `.staging-file-*` alias. Neither reuses s…
- The portable checker (`scripts/`) does not enforce V4:354. That rule only affects producer scheduling liveness; there is no retained-evidence consequence.

---

## Finding list (consolidated)

| ID | Lens | Severity | Surface | Intent ref | Code ref | Summary | Fix |
|---|---|---|---|---|---|---|---|
| — | — | — | — | — | — | No new defect meets the bar (stale reuse, false PASS, hang, data loss) in the inspected store, run-store and policy surfaces. All three round-2 findings are closed. | — |

## Summary

- Total findings: 0
- By severity: Critical=0 Major=0 Minor=0 Informational=0
- By lens: commitment-coverage=0 clause-to-line=0 deferred-cannot-silently-succeed=0 who-controls=0 field-name=0 deferral-justification=0
- Round-2 closure: CA-01 closed (`run:795,855`), CA-02 closed by refusal (`policy:108-110`, Dossier admitted), CA-03 closed (`store:1108-1115`).
- Recommended next step:
  1. The orchestrator decides whether to accept the gate deviation (no `dispatch.json` or `.fv/intent.md`).
  2. Optional: decide whether the crash-window hardlinked-alias refusal (above) is acceptable as an operator-cleanup state.
  3. Rerun `r38_evidence_v4_store_review.py` plus the lifecycle, portable and cache suites on Linux. The CA-01 regression test skips without direct group signalling (`test:142-143`), so on Linux the fix is checked only statically.

I could not diff `6c787c2..34a7240` (no shell), so anything outside the cited regions was not checked. I did not re-audit native lock or retirement internals. All deductions are static and none were reproduced.
