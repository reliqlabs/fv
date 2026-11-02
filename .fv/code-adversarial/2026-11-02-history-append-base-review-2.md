**Verdict: no blocker.** `70d257f` (`tools/evidence-v4/evidence-v4-store.ts`, +39/-7) is behavior-preserving under the stated trust model.

**1. Reused tail equals `loadHistory(undefined, true)` for an unchanged directory**
- Sequence: old `snapshot.events.length + 1`, new `base.events.length + 1` (1034); the cache starts as `[...snapshot.events]` (1029) and grows by exactly the event written (1042), so lengths track the on-disk file count.
- `previous`: `loadHistory` builds the head as `{sequence, event_id, path: relative, hash: H(bytes)}` (875). The cached head after an append is `{sequence, event_id, path: reference.path, hash: reference.hash}` (1041); `immutableFile` returns `path: relative, hash: H(bytes)` where `bytes = C(event)` and it verifies the retained bytes hash to the same value before linking (250-256, 272). Chain comparison uses `equal` = canonical bytes (76-78), so key order is irrelevant. Identical.
- Events: on-disk is `validateHistoryEvent(parseJSON(C(event)))`; `C` rejects `undefined`, non-safe integers and sorts keys (476-507), so the in-memory event is canonical-equal to its round trip. `validateEventBindings` reads fields by name and uses `equal` (764-845), so the cached list drives it identically. The old code also used a fresh `cache` per append (1039 = old 1012).

**2. Guard coverage**
- Any append by another `Store` (same or other process, under the same native mutex) adds one file: `names.length !== base.events.length` (1021) forces reload. Head replacement with same count: `H(readBytes(head.path)) !== base.head.hash` (1023-1024) forces reload. ENOENT on the directory: `names = []`, mismatch, reload, and `loadHistory` reaches the same empty state (851-856).
- Not covered: substitution of a non-head file with count and head preserved. That requires external mutation, excluded by the pre-existing comment (1076, was 1044 pre-change) and by `withAppendLock` + publication lock. Nothing in the store itself deletes or rewrites history or referenced artifacts: the only mutating ops are `link/unlink` of staging (261-262), execution checkpoint `rename` into a new path (570), alias unlink with `nlink === 2` check (1192-1195), and the `current.json` rename (1416). Such corruption is still caught by `readHistory` before publication (see 4).

**3. `appendBase` cleared on every failure**
`appendUnlocked` wraps `loadAppendBase`, `validateHistoryEvent`, `validateEventBindings`, and `writeImmutableJSON` in one `try` whose `catch` sets `this.appendBase = null` and rethrows (1032-1047). The cache is updated only after `writeImmutableJSON` returns (1042-1043). A failure after `fs.link` but before return (unlink/fsync seam) leaves the file on disk and the cache null; the next append reloads via `loadHistory` and continues from the on-disk file, as the old code did. Minor, not a blocker: `readHistory` failure (1003-1009) bumps `writeEpoch` but does not clear `appendBase`, so after a full-validation failure caused by a corrupted middle event or artifact, the session keeps appending onto the chain until it ends, whereas the old code failed each append…

**4. Publication path unchanged**
`publishCurrent` (1390) → `validateGeneration` (1268) → `readHistory(manifest.history)` → `loadHistory(captured, false)`: contiguity (865), chain + event_id (869-874), `validateEventBindings` for every event (876), prefix check (882-889), attempt and observation accounting (893-895), epoch check (896). `publishRun` (1383-1385) is the same. `accountPending` still ends with `readHistory()` (1260) and still does a full `loadHistory(undefined, true)` per pending result (1213), so recovery is untouched.

**5. `latestValidation` / `snapshotValidations`**
`loadHistory` only sets them when `!allowUnaccounted` (898-903); `appendUnlocked` always called it with `allowUnaccounted = true`, so appends never refreshed them. `evidence-v4-run.ts` only consumes them through `readHistory` (385) and `selectCandidates` (540, 702, 1209), which revalidate on `writeEpoch` mismatch (1061-1075); `writeImmutableFile` still bumps `writeEpoch` per append (466). Confirmed: no dependency.

Failure scenarios checked, all handled: concurrent recovery append from a second process (count guard); head file replaced (hash guard); append crash between `link` and `unlink` (new process, cache empty, alias retirement 1170-1203); `validateEventBindings` rejection of the new event (cache dropped, one full reload on next append); history dir removed (reload, same empty result as before).

Skipped: did not run the four r38 test files or inspect them; did not inspect `withAppendLock` native mutex implementation for cross-process scope (assumed per task context). Risk: detection of silent middle-of-chain corruption now happens at the next full `readHistory` instead of the next append.

[Some lines truncated to 768 chars. Use agent://AppendBaseFable:raw:13-13 to read line 13 whole]
