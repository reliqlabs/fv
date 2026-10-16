# Code-adversarial review: reliq-fv evidence-perf, native ownership round 3 - 2026-10-15

- Operator: fv-code-adversary via OMP task (NOT the openai-codex/gpt-6.1-sol task agents R2FixBase, R2FixRust, R2FixProof, R2FixStore, R2FixNative or R2FixAdoption, and NOT the parent orchestrator)
- Code commit reviewed: `34a7240` (parent `6c787c2`, the round-2 target)
- Intent version reviewed: `docs/execution-evidence-v4.md` has no frontmatter version; its status is "normative contract". Includes the new paragraphs at V4:225-227 and the change record section "Round-2 review dispositions (2026-10-15)".
- Ledger version reviewed: absent (`F/.fv/ledger.md` does not exist)
- Lens pack: crypto/enclave, plus concurrency/process-lifetime and error-atomicity analysis
- Lenses applied: 1 through 6

## Scope and evidence limits

Aliases:
- `F` = `/Users/mv/Development/reliq-fv-wt/evidence-perf`
- `N` = `F/tools/evidence-v4/evidence-v4-native.ts`
- `V4` = `F/docs/execution-evidence-v4.md`
- `CR` = `F/.fv/changes/2026-10-14-execution-evidence-v4.md` (round-2 dispositions start at CR:129)
- `TR` = `F/tests/r38_evidence_v4_native_review.py`
- `R2` = `F/.fv/code-adversarial/2026-10-15-native-review-2.md`

**Intent resolution.** `F/.fv/dispatch.json` is absent, and so is the default target `F/.fv/intent.md`. A glob of `F/.fv/*` lists only `changes/`. Following the persona's own resolution would therefore give `STATUS: BLOCKED`. The caller named V4 and the CR section as the normative intent, and rounds 1 and 2 used the same designation, so this review does too. The invoking skill should decide whether to accept that.

**What was not done.** No shell, git, test or build was run; only read, grep and glob were available. `git diff 6c787c2..34a7240` was not executed. The worktree files were read, and nobody here checked that they match `34a7240`. The parent's verification (216/216 Darwin tests; real Dossier captures admitted) is accepted as reported. Bun 1.3.14 source and XNU source are not in the tree. Claims about them are marked `[INFERENCE]`.

**Trust premises kept.** Approved commands obey the declared lifecycle and make no undeclared group or session escapes (V4:334). Operator, OS and runtime are honest. Accepted limits are not re-raised: Linux and other runtimes refuse group signaling.

**Not covered by this pack.** Access control, arithmetic, reentrancy, migration, supply-chain authenticity, general resource exhaustion (for example the growth of owner-record rewrites as many members register), Bun internals, and XNU PID allocation and `kinfo_proc` semantics beyond SDK offsets. The derived-native-identity and allowlist paragraphs (V4:225-226) are enforced in `evidence-v4-source.ts` and the toolchain adapters, which are outside this slice. `N` does not implement them.

## Round-2 closure verdicts

| Round-2 finding | Verdict | Evidence |
|---|---|---|
| CA-01: a zero-length `KERN_PROC_PID` read was treated as a fatal incomplete census | **closed** | `if (length.readBigUInt64LE() === 0n) return null;` at N:548 runs before the 648-byte check at N:549-550, on both bracketing reads. The ESRCH branch is kept (N:545-546). Tests: TR:478-496 cover zero length on the first and the second read, through both `readProcessIdentity` and `groupStopped`. TR:508 and TR:525-531 now expect `gone` to count as stopped. |
| CA-02: the per-census birth recheck and the PID-number skip covered terminated registrations | **partially closed** | Terminated registrations are now excluded from census input (N:1594), from the group map (N:1600), from the birth recheck (N:1604, plus a re-check after the await at N:1606), from the skip, which is now birth-based (N:1631), and from anchor selection (N:1637). Test TR:237-313 covers released-hosted PID reuse, both foreign and descendant. **Residual:** the same false escape still fires for an exited but not-yet-terminated member of a live group whose PID is reused. This is new finding CA-01. |
| CA-03: forced-waiter detection used the JS `process.env` | **closed** | libc `getenv` is bound at N:322. It is sampled when the library loads (N:348-349) and re-read at the gate (N:725-726). The JS-env checks are kept as extra refusals (N:28, 716-717). TR:355-385 shows that JS deletion, before or after import, leaves libc `getenv` set and signaling refused. The Bun revision (`0d9b296af`, `process.zig:312-315`) is retained only as a code comment (N:712). CR:133 does not cite it. That is a documentation gap and cannot cause a false PASS, so it is not re-raised. |
| CA-04: kernel auto-reaping was not excluded | **closed** | `sigaction(20, NULL, &old)` at N:729 uses the LP64 layout: handler at 0, flags at 12, size 16. It refuses on `SIG_IGN` (1) or `SA_NOCLDWAIT` (0x20) at N:731-732. The check runs synchronously before the identity re-read and `kill` (N:733-748), with no `await` in between. Tests: TR:387-422 (mocked, including an unavailable disposition) and TR:424-454 (real libSystem `sigaction` on Darwin, with the old disposition restored). |
| Rounds 1-2 evidence limit: Bun descriptor adoption when `connect` throws | **unchanged, not a finding** | `adopted = true` is still set before `socket.connect` (N:1182-1190). The new `socket.destroy()` on throw (N:1187-1188) shuts the transport down without closing the duplicate fd. Worst case is an fd leak inside an ERROR path that is already bounded (N:1774-1777). No stale evidence and no hang. |

---

## Lens 1 - Commitment coverage

| Commitment | Attacker DoFs | Bound by | Gap |
|---|---|---|---|
| Serialized owner record (expected-bytes replace) | Registrations, windows, `terminated_at` | The whole record (unchanged from round 2) | None. The delta changes which registrations the census reads, not what is serialized. |
| OwnershipReceipt in NativeResult | children, spawn_windows, protocol_log | `clone(owned)`, `clone(windows)`, `H(logBytes)` (N:1819-1826) | None |
| Gate payload `C({file, argv, cwd, environment})` | argv, env, cwd | N:1659-1663 | None. Unchanged. |
| Signatures, ReportData, application commitments | None in N | None | Empty surface. The delta adds no commitment. |

## Lens 2 - Clause-to-line discharge

| Clause | Expected discharge | Actual code line | Status |
|---|---|---|---|
| V4:346: signal only while the leader is our unreaped direct child and reaping cannot race | Capability gate, libc waiter check, SIGCHLD disposition check, synchronous re-read, then kill | N:713-732, 733-748 | discharged. The remaining premise is the Bun reaping behaviour cited at N:712 `[INFERENCE: Bun source not in tree]`. |
| V4:346: refuse on other runtimes and for reaped, descendant or foreign groups; work stays indeterminate | Throw; the caller sets `escaped` | N:724, 726, 730, 732, 742; N:1258-1261 | discharged |
| CR:133 "A zero-length `KERN_PROC_PID` snapshot means the process vanished" | Return null on zero length | N:548 | discharged |
| CR:133 "Terminated registrations are ignored" | Census, recheck, skip and anchor use only live registrations | N:1594, 1600, 1604-1606, 1631, 1637 | discharged in `observe`. The signal path still passes every registration (N:1255). That only tightens the restricted-row foreign tolerance (N:560-566), which fails closed. No finding. |
| V4:563: pair each PID with an actual birth identity; V4:344: unproven termination stays indeterminate, so proven termination should not | A different birth at a registered PID means the original exited | N:1607-1613 throws `escaped` on any birth mismatch of a live registration; N:681-685 does the same in the anchor | **partial: CA-01** |
| V4:340: on release, verify the original group is terminated; a reaped or reused PID alone is insufficient | `groupStopped` before stamping | N:1263-1279, 1382-1387 | discharged under V4:334. `terminated()` stamps every registration of the group without re-reading each member. A registered member that had moved to a new group would be stamped, and is now no longer rechecked, because the CA-02 fix skips terminated entries. That needs an undeclared group escape, which V4:334 forbids, so it is not a finding. |
| V4:344: normal completion requires all owned groups stopped and all windows closed | `normalProtocol` gate | N:1694-1709 | discharged |
| V4:563-565, T2: recovery never steals live or indeterminate ownership | Same-boot refusal of non-closed windows | N:1972-1975 | discharged |
| B1/B2 at the native boundary: no PASS without closed ownership; cancelled work never PASSes | Window state plus error | N:1706-1709, 1806-1811 | discharged on the native side. The run-layer classification was not re-read this round. |

## Lens 3 - Deferred cannot silently succeed

| Branch | Reachable from | Behavior | Status |
|---|---|---|---|
| TODO, stub, `shortcut:`, not-implemented | N | None found in the reviewed regions | empty |
| Zero-length restricted read returns null (N:548) | census, identity, `groupStopped` | Treats the process as gone. `[INFERENCE: XNU KERN_PROC_PID gives zero length only for a missing PID]` | acceptable. It records no termination proof for a live process. |
| `signalOwned` returns early when there are no group members (N:710) | cancel and success loops | No signal sent; `terminated_at` still needs `stopped()` (N:1264) | acceptable |
| `kill` ESRCH swallowed (N:744-748) | gate | Later proof is still required | acceptable |
| SIGCHLD query fails (N:729-730) | gate | Throws, which sets `escaped` | explicit failure |

## Lens 4 - Who controls

| Field | Supplier | Validation | Gap |
|---|---|---|---|
| Forced-waiter state | libc environment at load and at the gate | `getenv` is non-null at N:349 or N:725; the JS env is also checked (N:28, 717) | None. Native code calling `unsetenv` is covered by operator trust. |
| SIGCHLD disposition | Process signal state | Read synchronously at the gate (N:729-732) | None. A concurrent native thread changing it is covered by runtime trust. |
| `OwnedRegistration` for observed group members | Producer census (N:1625-1643) | Group membership plus an anchor | CA-01: entries outlive their processes and are rechecked against later, unrelated occupants of the same PID |
| `terminated_at` | Producer after `groupStopped` | N:1263-1279 | None |

## Lens 5 - Field-name fidelity

| Field | Implied semantic | Actual value | Status |
|---|---|---|---|
| `terminated_at` | Group proven stopped | Stamped only after `stopped()` (N:1264-1273) | faithful under V4:334 |
| `spawn_windows[].state` | Ownership resolution | N:1706-1707, 1748-1758 | faithful. CA-01 can push it to `indeterminate` spuriously, which fails closed. |
| `termination.cancelled` | Cancellation requested | N:1281-1283; error forced at N:1806-1811 | faithful |
| `forcedWaiter` (internal) | Bun's real waiter mode | libc `getenv` presence | faithful and conservative. Any value refuses; Bun may treat only truthy values as on `[INFERENCE]`. |

## Lens 6 - Deferral justification audit

| Deferred finding | Justification claims | Claim audit | Verdict |
|---|---|---|---|
| CR:133 native disposition | (1) A zero-length snapshot means vanished. (2) Terminated registrations are ignored. (3) The waiter flag comes from the real startup environment. (4) Signaling refuses on SIG_IGN or SA_NOCLDWAIT. | (1) N:548, true. (2) True in `observe`; N:1255 still passes every registration to `signalOwned`, which is stricter and fails closed. (3) The flag is read through libc `getenv` when the library first loads, not literally at startup. TR:355-385 shows JS deletion does not affect it. Whether Bun's own startup read matches libc `environ` is `[INFERENCE]`. (4) N:727-732, true. | Holds. Claim (2) fixes the round-2 counterexample but not the wider class: see CA-01. |
| CR known limit: unfinished refused children need operator cleanup | ERROR rather than a hang | N:1786-1789, 1804; same-boot recovery refuses non-closed windows (N:1972-1973) | Holds. This raises the cost of CA-01, because one spurious `indeterminate` window blocks further dispatch (N:1035), resource release (N:942) and same-boot recovery. |
| CR known limit: Linux refuses group signaling | Platform gate | N:714 | Holds (accepted) |

---

## Finding list (consolidated)

| ID | Lens | Severity | Surface | Intent ref | Code ref | Summary | Fix |
|---|---|---|---|---|---|---|---|
| CA-01 | clause-to-line | Minor | `observe` birth recheck and `requireGroupAnchor` | V4:563 (PID paired with birth identity); V4:344 (only unproven termination is indeterminate); R2 CA-02 | N:1603-1614, N:675-688 (reached from N:1635-1638 and N:711); registration of observed members at N:1625-1643 | The CA-02 fix skips only `terminated_at` entries. Each observed member of a live owned group (every rustc, cc or build script that cargo runs inside the direct group) stays registered after it exits, until the whole group is terminated. Every later census re-reads that PID. If the number has been reused by an unrelated process, `!sameProcess` throws "owned process birth or group identity changed". The anchor path throws the same way when the first matching regis…

## Summary

- Total findings: 1
- By severity: Critical=0 Major=0 Minor=1 Informational=0
- By lens: commitment-coverage=0 clause-to-line=1 deferred-cannot-silently-succeed=0 who-controls=0 field-name=0 deferral-justification=0
- Round-2 closure: CA-01 closed, CA-02 partially closed (residual is CA-01 above), CA-03 closed, CA-04 closed. The descriptor-adoption evidence limit is unchanged and not a finding.
- No path was found in `N` that reuses stale evidence, claims PASS falsely, hangs or loses data. `terminated_at`, window closing and lock release still all require a census proof (N:1264, 1694-1709, 942, 1035, 1972-1975). The only new fail-closed defect is the spurious ERROR in CA-01.
- Recommended next step:
  1. Fix CA-01: treat a different birth as "exited" in the `observe` recheck and in `requireGroupAnchor`, and add the TR case.
  2. Rerun `TR` and the native lifecycle suites on Darwin and Linux.
  3. Optional, documentation only: cite Bun `0d9b296af` `process.zig:312-315` in CR:133 next to the V4:346 premise.

Not checked: the actual `34a7240` diff (no git available), Bun 1.3.14 reaping and env-read internals, XNU PID allocation, and the run layer (R) classification. CA-01 comes from reading the code and was not reproduced. How often Dossier hits it depends on run length and system process churn `[INFERENCE]`.
