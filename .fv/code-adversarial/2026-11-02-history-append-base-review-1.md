# Code-adversarial review: fv evidence-v4 store (history append base) - 2026-11-02

- Operator: fv-code-adversary via OMP task (NOT the `perf/history-append-base` implementation author; `IMPLEMENTATION_AUTHOR` was not named by the caller, only "the author" of commit `70d257f`; proceeding on the same gate deviation prior reviews recorded, orchestrator to accept)
- Code commit reviewed: 70d257f (delta vs c81de3d, `tools/evidence-v4/evidence-v4-store.ts`; the pre-change text was not readable through my tools, so statements about old behavior derive from the caller's description and the surviving call shapes, marked `[INFERENCE]` where load-bearing)
- Intent version reviewed: absent (`fv/.fv/dispatch.json` and `fv/.fv/intent.md` do not exist; caller-named intent = store invariants in `evidence-v4-store.ts` and `tests/r38_evidence_v4_*.py`)
- Ledger version reviewed: absent
- Lens pack: storage-integrity / hash-chained append-only log (not crypto/enclave). Uncovered classes: cross-process filesystem semantics outside POSIX local disks (NFS stale listings), resource exhaustion, supply chain.
- Lenses applied: 1 through 6

Path shorthand: `S` = `fv/tools/evidence-v4/evidence-v4-store.ts`, `R` = `fv/tools/evidence-v4/evidence-v4-run.ts`, `N` = `fv/tools/evidence-v4/evidence-v4-native.ts`, `M` = `fv/tools/evidence-v4/evidence-v4-model.ts`.

---

## Verdict

**No blocker.** Evidence published by this version is as trustworthy at publication as before. Every publication-gating validation is unchanged and runs over the full on-disk history with accounting enabled: `R:477` (`snapshotHistory` → `S:1003-1005` `readHistory` → `loadHistory(captured,false)`), `R:1198-1210` (`assessFullHistory` → `selectCandidates`, which falls through to `readHistory` at `S:1072-1073` whenever `writeEpoch` moved, and every append moves it at `S:467`), `R:1338` → `S:1385` `validateGeneration` → `S:1269` `readHistory(manifest.history)`, `R:1339` → `S:1398` again before the current pointer. The cached base only decides `sequence` and `previous` of the next event and the `previous` list fed to `validateEventBindings`; the written event is s…

What changed is detection latency for out-of-band mutation, not detection itself. Findings below are Minor/Informational.

## Assignment items

### (1) Writers of `.fv/evidence/v4/history/`

| Writer | Where | Old reload caught | New guard (`S:1013-1027`) |
|---|---|---|---|
| This session's `appendUnlocked` → `immutableFile` (`S:1040`, `S:241-271`: O_EXCL temp in `BASE/`, `link` to `history/<seq>.json`, `unlink` temp) | in-process, serialized by `withAppendLock` (`N:820-823`, a promise chain, in-process only) | n/a | Tracked by `base.events.push`/`base.head` (`S:1042-1043`); guard passes |
| Recovery `accountPending` → `appendUnlocked` (`S:1245`) | separate `Store` instance (`R:174`), separate owner, runs under the dead owner's lock with the owner-bytes guard (`N:2030-2036`); cannot coexist with a live producer on the same owner because `publication.lock` is O_EXCL (`N:24`, `N:1951`) | n/a | If it ever interleaved: count changes → reload at `S:1029` |
| `retireRecoveredHistoryAliases` (`S:1163-1204`) | unlinks the stale alias in `BASE/`, fsyncs the history target; content and count unchanged | n/a | Nothing to catch; a cached base cannot hold an aliased head because the aliasing append already threw and cleared it (`S:1046`) |
| Another producer process | excluded by `publication.lock` | caught via count/chain | count change caught; count-preserving edits not caught until next full load |
| External/human/corruption: rewrite of an older event, rename swap, delete+junk, artifact rewrite | outside the stated trust model (`S:1076`, `S:459`) | caught at the next append (`S:865`, `S:869-874`, `S:626`) `[INFERENCE: old code ran loadHistory per append]` | not caught at append; caught at the next epoch-gated `selectCandidates` (`S:1060-1073`), `R:477`, `S:1269` |

No in-tree code deletes, renames, or rewrites anything under `history/` (`fs.unlink`/`fs.rename` sites: `S:262` temp only, `S:570` execution staging, `S:1195` alias in `BASE/`, `S:1416` current pointer, `N:253,258,2093` lock files).

### (2) Count equal + head hash match while an older event was replaced

Yes, the guard accepts that state. Concrete scenarios, all requiring an external writer:

- Rewrite `history/00000000000000000005.json` while the base holds 10 events: `readdir` count 10, head file 10 hashes to cached hash → `unchanged` (`S:1022-1026`) → event 11 written with `previous` = ref of 10, which is still correct for the on-disk head. Caught later at `S:869-874` ("history hash chain mismatch": event 6's `previous.hash` ≠ `H(new bytes of 5)`), first at the next `selectCandidates` full reload (`S:1072-1073`, triggered because `S:467` bumped the epoch), then `R:477`, then `S:1269` at both `S:1385` and `S:1398`.
- Swap names 05↔06: same name set, count equal → reuse. Caught at `S:870` (`event.sequence !== sequence`).
- Delete 03, add `zz.json`: count equal, `names.includes(head)` true → reuse. Caught at `S:865` ("not a contiguous canonical sequence"). Side effect: the next append targets `<N+1>.json` which does not exist, so it succeeds; if instead `<N+1>.json` had been planted, `fs.link` at `S:261` throws EEXIST and the O_EXCL temp from `S:250` leaks in `BASE/` (nlink 1, skipped by `S:1172`). Pre-existing leak path, now reachable one step earlier (Informational, CA-05).
- Rewrite an older execution artifact (not history): reuse. Caught by `readExecution` hash check (`S:626`) through `retainedExecution` during the next full `loadHistory` (`S:876`) or candidate scan (`S:1086`).

None of these produce a publishable store: `validateGeneration` runs the full chain and accounting (`S:896-900`) before `run.json` and before the current pointer.

### (3) Failure paths

- Exception after `writeImmutableJSON` succeeded, before `base.events.push`: no such window. `S:1040` resolves, `S:1041` is a synchronous object literal, `S:1042` pushes into a spread copy (`S:1030`, never frozen), `S:1043` assigns a plain field. The only in-window throw would be a frozen `base.events`, which the spread prevents.
- Exception inside `writeImmutableJSON` after `link` succeeded (`unlink` or fsync failure, `S:262-268`, or a `syscallBarrier` seam): `appendBase = null` (`S:1046`), error propagates; disk may hold `<N+1>.json` with nlink 2. Next append → full `loadHistory` → `readBytes` fails at `S:192` ("hardlinked"). Caller leaves the pending result in the owner record and the session fails at `R:470-475`. Same as before; recovery via `S:1163-1204`.
- Cancellation mid-append: `checkpoint.run` is a bare promise chain (`R:145-148`) and `withAppendLock` likewise (`N:820-823`); neither interrupts an in-flight append. A process kill leaves the disk cases above; in-memory state is gone with the process. Unchanged.
- Recovery path `S:1212` calling `loadHistory` directly while a base is cached: the recovery `Store` is constructed fresh per `recoverEvidenceV4Owner` (`R:174`), so `appendBase` starts null. Within the loop, after the first `appendUnlocked` populates the base, later iterations call full `loadHistory` for the `existing` search and then reuse the base under the same lock; both views agree because nothing else writes under that lock. `S:1260` `readHistory()` closes the loop with full validation. Correct, and recovery still pays a full reload per pending result (cost unchanged, not a trust issue).
- `readHistory` failure mid-session (`S:1007`) bumps the epoch but does not clear `appendBase`. With history corruption, the old code refused every subsequent append `[INFERENCE]`; the new code keeps appending well-formed events on top of a chain already known broken until the session ends in ERROR. Not a trust gap (publication still fails at `S:1269`), but a fail-fast regression (CA-01).

### (4) Memory and ordering

- `loadHistory` returns `freezeRecord({view, events})` (`S:901`): the array and each event are deep-frozen. `S:1030` copies the array (`[...snapshot.events]`) so `push` works; elements stay frozen. Snapshots built with `allowUnaccounted=true` are not registered in `snapshotValidations` (`S:902-906`), so the discarded snapshot is garbage; the base holds one reference per event for the session, the same working set a single append previously held transiently.
- Events pushed at `S:1042` are **not** frozen and alias caller objects: `validateHistoryEvent` returns its input (`M:1476-1479`), and `S:1036` spreads `input`, so `event.members === descriptor.members` (`R:764`, `R:913`) and `event.execution === reference` (`R:907-914`). Current callers never mutate these after the call (`R:524` builds the descriptor once; no `members.push/splice/sort` in `R`), so the base is consistent with disk today. A future mutation would make `S:800-806` (`equal(actual.members, …)`, `equal(actual!.execution, …)`) judge against in-memory state that differs from the canonical bytes, and the discrepancy would surface only at the next full reload (CA-02).
- `head` at `S:1041` has the same four fields as `loadHistory`'s reference (`S:875`) and `C` sorts keys (`M:496-500`), so `D("history-event", unsigned)` with `previous: base.head` is identical whether the head came from disk or from the previous in-session append. `reference.size` is deliberately not carried into the head.

### (5) Artifact reads for the new event

`validateEventBindings(event, base.events)` at `S:1039` uses the default fresh cache (`S:765`). `[INFERENCE: the default parameter exists only for this caller, so the old append path also validated the new event with a fresh cache.]` Reads for the new event are therefore unchanged: execution events with `execution !== null` read the full artifact tree through `retainedExecution` → `readExecution` (`S:681-690`, `S:622-664`: hash, identity, attempt-id, stream and tree checks); observation events read check/request/stdout/stderr/response and the artifact (`S:691-760`); indeterminate events read the recovered owner (`S:822-823`). "No cache PASS without a backed artifact" for the appended event is enforced at `S:787-792`/`S:794` and `S:807` exactly as before. Wha…

---

## Lens 1 - Commitment coverage

| Commitment | Attacker DoFs | Bound by | Gap |
|---|---|---|---|
| `event_id = D("history-event", unsigned)` (`S:1037`) | `sequence`, `previous` now sourced from the cached base | `previous` is the hash-verified on-disk head (`S:1022-1025`); `sequence = names.length + 1` equals the on-disk count | None: the new event commits to the true head file |
| `HistoryRef.hash` of the new head (`S:1041`) | none; `immutableFile` returns `H(bytes)` after re-reading staged bytes (`S:247-251`) | next guard compares `H(readBytes(head.path))` to it | None |
| Chain links 1..N-1 at append time | external rewrite/rename/delete of non-head files | not bound by the guard; bound at every `loadHistory(…,false)` | Latency only (CA-01, CA-03) |

## Lens 2 - Clause-to-line discharge

| Clause | Expected discharge | Actual code line | Status |
|---|---|---|---|
| Append-only, contiguous, hash-chained history | contiguous names, `previous` equals prior ref, `event_id` recomputed | `S:865`, `S:869-874`; at append `S:1036-1037` chained to verified head | discharged at publication; `partial` at append (older links unverified between appends) |
| No cache PASS without a backed artifact | every candidate artifact read and hash-checked | `S:1086` → `S:681-690` → `S:626`; appended PASS at `S:787-794`, `S:807` | discharged |
| Publication only after full validation | `readHistory(captured,false)` with accounting before `run.json` and current pointer | `S:1269` via `S:1385`, `S:1398`; `S:896-900` | discharged |
| Appends serialized under the owner/append mutex | `withAppendLock` required | `S:1051-1052`, `N:820-823` | discharged (in-process; cross-process by `publication.lock` `N:1951`) |
| Session reuse assumes trusted immutable storage | documented | `S:459`, `S:1076` | discharged as an assumption; the assumption now also covers history files between appends (CA-03) |
| Failed append drops cached tail | `appendBase = null` on any throw | `S:1045-1047` | discharged; `readHistory` failure does not drop it (`S:1007`) (CA-01) |

## Lens 3 - Deferred cannot silently succeed

| Branch | Reachable from | Behavior | Status |
|---|---|---|---|
| TODO/stub/mock in the diff | none found in `S:459-460`, `S:1011-1049` | n/a | Empty: the diff adds no deferred branches |
| `unchanged` guard true with a stale non-head file | external mutation only | append succeeds; failure deferred to next full load | Explicit failure later (`S:865-874`); no silent success at publication |
| Guard's reload/failure branches | `S:1027-1031`, `S:1045-1047` | no test exercises them | CA-04 |

## Lens 4 - Who controls

| Field | Supplier | Validation | Gap |
|---|---|---|---|
| `appendBase.head` | `loadHistory` head (`S:1030`) or own write (`S:1043`) | re-hashed from disk each append (`S:1025`) | none |
| `appendBase.events[i]` (reloaded) | disk via `loadHistory` | frozen, chain + bindings validated | none |
| `appendBase.events[i]` (pushed in session) | caller `input` (`R:759-770`, `R:908-920`, `R:1142-1155`) | schema + bindings at `S:1037-1039`; object aliases caller data, unfrozen | CA-02 |
| `names` | `fs.readdir` (`S:1016`) | count and head membership only; no canonical-name check | CA-03 |

## Lens 5 - Field-name fidelity

| Field | Implied semantic | Actual value | Status |
|---|---|---|---|
| `HistoryRef.hash` returned by `appendHistory` | hash of the on-disk event bytes | `reference.hash` from `immutableFile` after read-back (`S:247-251`, `S:1041`) | fidelity holds |
| `HistoryRef.sequence` | position in contiguous history | `names.length + 1` (`S:1036`) | holds under trusted storage; see CA-03 |
| No public JSON/proto/event fields changed in the diff | | | empty |

## Lens 6 - Deferral justification audit

| Deferred finding | Justification claims | Claim audit | Verdict |
|---|---|---|---|
| None in `.fv/code-adversarial/2026-10-15-producer-store-review-3.md` or `2026-10-16-collection-boundary-review1.md` concern the append path | | | Empty: no prior deferral touches `appendUnlocked`/`loadHistory` cost |

---

## Finding list (consolidated)

| ID | Lens | Severity | Surface | Intent ref | Code ref | Summary | Fix |
|---|---|---|---|---|---|---|---|
| CA-01 | 2 | Minor | `readHistory` failure during a session | fail-fast on known history corruption | `S:1003-1010`, `S:1045-1047` | `readHistory` bumps the epoch on failure but leaves `appendBase`; subsequent appends keep building on a chain already observed broken until session end. Old per-append reload refused `[INFERENCE]`. Publication still blocked at `S:1269`. | Add `this.appendBase = null;` beside `this.writeEpoch++` at `S:1007` |
| CA-02 | 4 | Minor | in-session cached events | base must mirror canonical bytes | `S:1042`, `M:1476-1479`, `R:764`, `R:913` | Pushed events alias caller objects and are unfrozen, unlike `loadHistory` events (`S:901`). Benign today (no caller mutation found), latent divergence between base and disk. | `base.events.push(freezeRecord(event))` (note: freezes the shared `descriptor.members`/`reference`), or push `validateHistoryEvent(parseJSON(C(event)))` |
| CA-03 | 1/2 | Minor | out-of-band history or artifact mutation between appends | append-only hash chain | `S:1022-1026` vs `S:865-874`, `S:626` | Count + head hash accepts rewrite/rename/delete+junk of non-head files and artifact rewrites; detection moves from the next append to the next epoch-gated `selectCandidates` or `R:477`. Within the stated trust model (`S:459`, `S:1076`). Cost: a tampered store can run for hours before the ERROR. | Accept and extend the `S:459` comment to say the tail is trusted between appends; optionally a tamper-between-appends test asserting ERROR at publication |
| CA-04 | 3 | Minor | test coverage of new branches | new non-trivial branch needs a check | `S:1013-1031`, `S:1045-1047`; `fv/tests/r38_evidence_v4_store_review.py:598-660` | Only the reuse branch is exercised (implicitly, by multi-append runs and `accountPending`). No test covers reload after an out-of-band append (count change), head-hash mismatch, or base drop after a failed append. | One `store_review` test: append via store A, append via a second `openEvidenceStore` on the same root, append via A again and assert `sequence === 3` and a clean `readHistory()`; a second case forcing a throw in `validateEventBindings` and asserting the next append still succeeds |
| CA-05 | 3 | Informational | EEXIST at `fs.link` when `<N+1>.json` exists despite count N | staging hygiene | `S:250`, `S:261`, `S:1172` | Temp `.staging-file-<seq>.json-<uuid>` leaks in `BASE/` with nlink 1; skipped by alias retirement, harmless to validation. Pre-existing; the old path would have failed at `S:865` before writing the temp `[INFERENCE]`. Requires external deletion. | None required; if desired, `unlink(source)` in a `catch` around `S:261` |

## Summary

- Total findings: 5
- By severity: Critical=0 Major=0 Minor=4 Informational=1
- By lens: commitment-coverage=0 clause-to-line=2 deferred-cannot-silently-succeed=2 who-controls=1 field-name=0 deferral-justification=0 (CA-03 counted under clause-to-line)
- Recommended next step: (1) CA-01 one-line `appendBase = null` at `S:1007`; (2) CA-04 guard-branch test; (3) CA-02 freeze or copy on push; (4) CA-03 comment update. None gates merge.
- Evidence limit: the pre-change source was not readable here; "old reload caught" claims rest on the caller's description of `loadHistory(undefined, true)` per append and on the surviving `validateEventBindings` default parameter.

Skipped: did not read the test bodies of `r38_evidence_v4_lifecycle.py`/`cache.py` beyond grep, and did not inspect `Serial`/abort handling in `R` beyond `R:145-148`. Risk: the `[INFERENCE]` items about old behavior, if wrong, only change which findings are regressions versus pre-existing; they do not change the verdict.

[Some lines truncated to 768 chars. Use agent://AppendBaseAdversary:raw:16-16 to read line 16 whole; cut lines run to line 61, each read the same way]
