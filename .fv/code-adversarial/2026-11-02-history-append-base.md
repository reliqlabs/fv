# History append base (2026-11-02)

Commits `70d257f` and `5e4223b` on `perf/history-append-base`. `Store.appendUnlocked` reloaded and re-validated the whole history, including every referenced artifact, on every append. On the Dossier store (930 events, 1.9 GB of artifacts, about 170 appends per collection) that was 4 to 10 minutes per slot, about 14 of 17.5 hours per collection, measured from event timestamps against execution start and finish.

The store now keeps a validated tail across appends in one session: before each append it re-reads the history directory and reuses the tail only if the entry count is unchanged and the cached head file still hashes to the cached head hash; otherwise, after any append failure, and after any failed full read it reloads through `loadHistory` as before. The new event is validated with `validateEventBindings` against the cached events exactly as before, and pushed events are frozen canonical copies. Full chain validation with accounting is unchanged at session start, before `publishCurrent`, at `publishRun` and in `assessFullHistory`.

Reviews (retained verbatim beside this note, both no blocker): `2026-11-02-history-append-base-review-1.md` (fv-code-adversary, five minor findings, all applied in `5e4223b` except CA-05 which needs no change) and `2026-11-02-history-append-base-review-2.md` (Fable, one hardening, applied). Tests: `r38_evidence_v4_store_review.py` 9 OK (new guard test), `r38_evidence_v4_cache.py` 9 OK, `r38_evidence_v4_portable.py` 12 OK, `r38_evidence_v4_lifecycle.py` 26 OK.

Trust scope: between appends the tail trusts the immutable store; out-of-band mutation of a non-head event or an artifact is detected at the next full read rather than at the next append, and publication still fails on it.
