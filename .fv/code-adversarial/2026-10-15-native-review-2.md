# Code-adversarial review: reliq-fv evidence-perf, native ownership round 2 - 2026-10-15

- Operator: fv-code-adversary via OMP task. It is not the implementation author: not the openai-codex/gpt-6.1-sol task agents FixNativeOwnership-2, FixProducerStore-2, FixSourceBindings-2, FixAdoptionDashboard-2, FixBaseToolchain, FixRustToolchain or FixProofToolchain, and not the parent orchestrator.
- Code commit reviewed: `6c787c20f023a132856cf5119b137be25dd2303f` (parent `aa6946f`, the round-1 target)
- Intent version reviewed: `docs/execution-evidence-v4.md` has no frontmatter version. Its status line is "normative contract". This review includes the group-signal paragraph at V4:342 and the change record section "Post-commit review dispositions (2026-10-15)".
- Ledger version reviewed: absent (`F/.fv/ledger.md` does not exist)
- Lens pack: crypto/enclave, plus concurrency/process-lifetime and error-atomicity analysis
- Lenses applied: 1 through 6

## Scope and evidence limits

Aliases:
- `F` = `/Users/mv/Development/reliq-fv-wt/evidence-perf`
- `N` = `F/tools/evidence-v4/evidence-v4-native.ts`
- `R` = `F/tools/evidence-v4/evidence-v4-run.ts`
- `V4` = `F/docs/execution-evidence-v4.md`
- `CR` = `F/.fv/changes/2026-10-14-execution-evidence-v4.md` (dispositions at CR:113-129)
- `TR` = `F/tests/r38_evidence_v4_native_review.py`
- `TL` = `F/tests/r38_evidence_v4_lifecycle.py`

**Intent resolution.** `F/.fv/dispatch.json` is absent, and so is the default target `F/.fv/intent.md`. The persona's own resolution therefore produces no target. The caller named V4 and the CR disposition section as the intent, so this review uses that designation rather than a filename search. The invoking skill should decide whether to accept it. Round 1 treated V4 the same way, as a caller-designated normative dependency.

**What was not done.** No shell, git, test, build or edit was run; the available tools are read, grep and glob only. `git diff aa6946f..6c787c2` was not executed. The worktree files were read, and nobody here checked that they match `6c787c2`. The parent's results (150/150 Darwin, Linux 114 with 7 skips) are accepted as reported. Bun 1.3.14 source and XNU source are not in the reviewed tree. Claims about them are marked `[INFERENCE]`.

**Trust premises kept.** Approved commands obey the declared lifecycle (V4:330). Operator, OS and runtime are honest. There is no concurrent mutation of bound inputs. The accepted limits are not re-raised: Linux and other runtimes refuse group signaling and stay indeterminate, and Lake coverage is Lean-specific.

**Classes not covered.** Access control, arithmetic, reentrancy, migration, supply-chain authenticity, general resource exhaustion, Bun internals (waiter thread, descriptor adoption), and XNU `kinfo_proc` field semantics beyond SDK offsets.

## Round-1 closure verdicts

| Round-1 finding | Verdict | Evidence |
|---|---|---|
| CA-01: numeric PGID/SID reuse admits foreign descendants; anchor reaped before `kill(-pgid)` | **closed**, conditional on the V4:342 runtime premise | **Admission:** a new row is registered only after `requireGroupAnchor` finds a live, birth-matching original registration of the same group (N:1612-1625, N:666-680). Every owned PID is birth-rechecked each census (N:1586-1596). **Signaling:** allowed only for the producer's own direct child, which must be group leader, have `parent_pid === process.pid`, carry the same `native` handle, have `exitCode`/`signalCode` null, and pass a synchronous birth/group/session re-read with no `await` before `process.kill(-pgid)` (N:703-728). Hosted groups never receive `native` (N:1235-1239), so they are always refused. Tes…
| CA-02: Darwin census treats every zero `proc_pidinfo` as gone | **closed** for errno discipline; the new fallback has a fail-closed defect | `processTable` skips only ESRCH, sends EPERM to the restricted fallback, and throws on everything else (N:638-655). `readDarwinProcessIdentity` does the same (N:490-498). Tests: TR:269-289. New defect CA-01 below is fail-closed: it can force ERROR, never PASS. |
| CA-03: gate argv minimum rejects a one-element subject | **closed** | `args.length < 7` (N:1891); nonempty, NUL-free subject elements (N:1892). Test: TR:654. |
| Round-1 unconsolidated note: Bun descriptor adoption on `connect` throw | **not addressed** (no change) | `adopted = true` is still set before `socket.connect({fd})` (N:1160-1167). If Bun throws without taking ownership, the close handler skips closing the duplicate. Still an evidence limit, not asserted as a finding. |

---

## Lens 1 - Commitment coverage

| Commitment | Attacker DoFs | Bound by | Gap |
|---|---|---|---|
| Serialized owner record (`C(record)` via expected-byte replace) | Registrations, windows, `terminated_at` | Whole record (N:789-805) | None new. Correct serialization cannot fix wrong census input (lens 2). |
| OwnershipReceipt in NativeResult | children, windows, protocol log ref | Built from `owned`/`windows` clones (N:1794-1810) | None new. The delta changes how facts are produced, not what is bound. |
| Lock record and registry | owner/run/host/boot, file list | N:819-830, 834-853 | None new; the delta did not touch this. |
| Signatures, ReportData, application commitments | None in N | None | Empty surface: the delta adds no commitment. |

## Lens 2 - Clause-to-line discharge

| Clause | Expected discharge | Actual code line | Status |
|---|---|---|---|
| V4:342: signal only while the leader is our unreaped direct child and the runtime guarantees reaping cannot race | Capability gate plus a synchronous check-then-kill | N:704-728; `FORCED_WAITER` N:28, 708 | partial: CA-03 (waiter detection uses JS env, Bun claim not retained as evidence), CA-04 (SIGCHLD auto-reap not excluded) |
| V4:342: refuse on other runtimes and for reaped, descendant or foreign groups; work stays indeterminate | Refusal sets sticky `escaped` | N:715, 725; wrapper N:1233-1245; window N:1688, 1727-1741; dispatch block N:1018-1019; lock block N:925-926 | discharged |
| V4:340: SIGTERM, at most 5 s, then SIGKILL proven-owned; collector grace unchanged | Direct-first staged cancel | N:1275-1303 | discharged. Only the direct group gets SIGTERM; all targets are polled for `MAX_GRACE`; SIGKILL hosted targets are refused. |
| V4:340: unproven descendant termination keeps ownership indeterminate | `terminated_at` only after census proof | N:1246-1259; success loop N:1659-1670; catch N:1718-1741 | discharged |
| V4:330: never signal a foreign or ambiguously owned PID | Birth/group/session recheck; hosted groups excluded | N:693-699, 702, 716-725, 1235-1239 | discharged under the V4:342 premise |
| V4:336: verify the actual interpreter; "a reaped or reused PID alone is insufficient" | (dev,ino) image equality; leader birth check | N:1849-1888; N:681-684 | discharged |
| V4:334: exact gate wrapper | Argv grammar | N:1890-1898 | discharged |
| V4:338: lifetime window closes only after full accounting | `normalProtocol` gate | N:1673-1691 | discharged |
| CR: "Darwin census propagates every error except ESRCH. EPERM rows fall back to `KERN_PROC_PID` with bracketing snapshots." | Restricted read: vanished maps to skip, changed owned row maps to throw | N:516-590, 640-655 | partial: CA-01 (a vanished process is a zero-length success, which is treated as fatal) |
| Census over live registrations (V4:336, 338: ownership attaches to registered original groups) | Birth recheck of live registrations only | N:1586-1596 iterates all `owned`, including terminated; N:1609 skips by PID number over all `owned` | partial: CA-02 |
| CR: "Unfinished refused children are unref'd, so the producer reports ERROR" | unref plus a forced ERROR | N:1775-1776, 1786; `release` refuses retained transports at N:999 | discharged |
| CR: native executable equality compares `(dev, ino)` | bigint stat equality | N:1853-1875 | discharged. The Linux `readlink`+`stat` path fails closed on `(deleted)` and namespace paths. |
| B1: closed ownership before PASS | `closed()` gate | R:128-133, 773-781 | discharged at the native boundary |
| B2: cancelled work cannot PASS | Classification | R:773-781; N:1787-1793 | discharged |
| T2: recovery never steals live or indeterminate ownership | Same-boot refusal | N:1946-1958 | discharged. CA-01 can also make recovery census throw spuriously; a retry is possible. |
| CR known limit: Linux refuses group signaling | Platform gate | N:705 | discharged as an accepted limit |

## Lens 3 - Deferred cannot silently succeed

| Branch | Reachable from | Behavior | Status |
|---|---|---|---|
| TODO, stub, `shortcut:`, not-implemented | N | grep found none | empty |
| `signalOwned` early return when the census shows no members | Cancel and success loops | Returns without signaling (N:700-701). Termination still needs `stopped()` before `terminated_at` (N:1247). | acceptable: no proof is skipped |
| `kill` ESRCH swallowed | N:727-731 | The leader is unreaped and the group has no live member to signal. Later proof is still required. | acceptable |
| Refused or unsupported runtime | N:715, 725 | Throws; caller sets `escaped` | explicit failure |
| Unref of an unexited child | N:1776 | Forces `error` (N:1786) and retains the transport (N:999) | explicit failure |
| Restricted sysctl ESRCH branch | N:536-538 | `[INFERENCE]` Unreachable for a vanished PID on real XNU. Fails closed, which is CA-01. | dead code, fail-closed |

## Lens 4 - Who controls

| Field | Supplier | Validation | Gap |
|---|---|---|---|
| `BUN_FEATURE_FLAG_FORCE_WAITER_THREAD` presence | Host/operator environment, as seen through JS `process.env` | `Object.hasOwn(process.env, …)` at import and at call (N:28, 708) | CA-03: reads the JS view rather than the C environment Bun consulted `[INFERENCE]` |
| `process.versions.bun` | Runtime; JS-mutable | String equality with `"1.3.14"` (N:706) | Operator trust; no finding |
| Restricted census row (ppid, pgid, e_sess, start) | Kernel `kinfo_proc` | 648-byte length, pid, range checks, two-read bracketing, owned-group strictness (N:535-590) | CA-01 (vanished process misclassified). Foreign tolerance is safe: a tolerated row's pgid is never an owned group (N:564-571). |
| `OwnedRegistration.terminated_at` | Producer, after `groupStopped` | N:1246-1259 | None |
| `SpawnWindow.state` | Producer lifecycle | N:1688-1689, 1730-1741, 1762-1767 | None |
| `rawSubprocesses` | Producer, in memory | Deleted only on `exited && streamsClosed` (N:1775); `release` refuses (N:999) | None |
| Collector child `args[0]` | Collector process | Darwin fallback needs `canonicalToolPath(args[0]) === canonicalToolPath(admitted)` and an image (dev,ino) match (N:1864-1876) | None |

## Lens 5 - Field-name fidelity

| Field | Implied semantic | Actual value | Status |
|---|---|---|---|
| `terminated_at` | Original group proven stopped | Stamped only after `groupStopped` is true (N:1247-1256) | faithful, given census completeness under V4:330 |
| `spawn_windows[].state = "closed"` | No unresolved ownership | Closed only with all registrations terminated and `!escaped` (N:1688, 1730-1741) | faithful |
| `termination.cancelled` | Cancellation requested and applied | Set on request (N:1265). When delivery is refused, `error` is non-null (N:1793), so R classifies ERROR. | faithful under R's classification |
| `process_start_id` from the restricted path | Same birth token as `proc_pidinfo` | `darwin-proc-start:${p_starttime.sec}:${usec}` (N:584-589) | `[INFERENCE]` the same kernel `p_start` as `pbi_start_tv*`; a mismatch would fail closed |
| Comment N:563 "shared session token binds getsid" | (not a public field) | `[INFERENCE]` `e_sess` may be a permuted or zeroed kernel address | Not load-bearing: group/start bracketing and owned-group strictness carry safety. No finding. |

## Lens 6 - Deferral justification audit

| Deferred finding | Justification claims | Claim audit | Verdict |
|---|---|---|---|
| CR native disposition: signaling only on Darwin with Bun 1.3.14 and no forced waiter | (1) Bun reaps on the JS thread on Darwin. (2) The forced waiter is detectable. (3) Birth and status are checked synchronously before kill. | (1) Only a code comment (N:703); no pinned Bun source citation is retained. The intent adopts it as a premise (V4:342) `[INFERENCE]`. (2) Detection is by JS env only: CA-03. (3) True (N:716-728). | Holds as a declared premise; evidence gaps CA-03 and CA-04 |
| CR: unref'd refused children need operator cleanup | Producer reports ERROR instead of hanging | True (N:1776, 1786). Same-boot recovery refuses non-closed windows (N:1954-1955), so cleanup means operator action or reboot. | Holds; this raises the cost of CA-01 and CA-02 |
| CR: Linux and other runtimes leave work indeterminate (accepted) | Refusal at the platform gate | N:705; TL:436-448 gates expectations | Holds |
| Round-1 Bun descriptor adoption on `connect` throw | Bun's ownership-on-throw is unknown | Unchanged (N:1160-1167) | Still open as an evidence limit; no wrong deferral |

## Supplemental concurrency analysis (focus items)

| Surface | Result |
|---|---|
| Race-freedom of the unreaped-child signal | The span from N:716 to N:728 is synchronous FFI plus `process.kill`; no microtask boundary. If Bun reaps only on the JS thread `[INFERENCE]`, the leader PID, and so the PGID, stays reserved through the syscall. Gaps: CA-03, CA-04. |
| Forced-waiter detection | Presence check at import (N:28) and call (N:708). This is conservative for set values (Bun treats only truthy values as on). It can miss a variable deleted from `process.env` after Bun read the real environment: CA-03. |
| EPERM fallback | Bracketing is correct for live rows. A `setsid` must change pgid, and a leader cannot `setsid`, so the group comparison catches session moves regardless of `e_sess`. Tolerating a PPID-only change is correct. Foreign tolerance needs both observed groups and `getsid` outside every owned group/session, so it cannot hide an owned member. Vanished-process handling is wrong: CA-01. |
| Staged cancellation | SIGTERM goes to the direct child only (N:1275-1283), then a `MAX_GRACE` poll of all targets (N:1285-1297), then SIGKILL per target with refusal for hosted or reaped targets (N:1298-1303). If cancel arrives before registration, the target list is empty, and the gate closes without exec (N:1638-1645, 1702). |
| Release or `terminated_at` without proof | No path found. `terminated_at` needs `stopped()` (N:1247). Windows close only under `!escaped` plus all registrations terminated (N:1688, 1730-1741). Unclosed stream closure forces indeterminate (N:1762-1767). Lock release refuses indeterminate windows (N:925-926). Session release refuses unresolved windows, storage failure or retained transports (N:991-999). |

---

## Finding list (consolidated)

| ID | Lens | Severity | Surface | Intent ref | Code ref | Summary | Fix |
|---|---|---|---|---|---|---|---|
| CA-01 | clause-to-line | Minor | Darwin restricted census | CR:117 (CA-02 disposition: propagate only non-ESRCH errors); V4:340 (only unproven termination is indeterminate) | N:535-541 (also via N:497, 644); test mock TR:62-64, TR:298 | `[INFERENCE: XNU KERN_PROC_PID returns 0 with *oldlenp=0 for a missing PID; psutil documents "sysctl succeeds but len is zero, happens when process has gone away"]` A process that exits between its EPERM `proc_pidinfo` and either sysctl read gives success with length 0. The length check then throws "incomplete Darwin restricted census", and the ESRCH branch at N:537 is dead. **Counterexample:** root daemon PID R is listed, `proc_pidinfo(R)` returns EPERM (TR:388-437 shows root PIDs do), R exits, sysctl returns 0/len 0, N:54…
| CA-02 | clause-to-line | Minor | `observe` birth recheck | V4:336, 338 (ownership attaches to registered original groups; a reused PID alone is insufficient) | N:1586-1596, 1609 | The per-census birth recheck covers every registration, including `terminated_at` ones, such as released hosted collector children (N:1365-1370). `[INFERENCE]` After a released hosted leader's PID is recycled by an unrelated process during a long run, the next census finds a different birth, sets `escaped` and cancels, giving ERROR and held ownership. The PID number skip at N:1609 also spans terminated entries; today it relies on the N:1586 throw to avoid silently skipping a new descendant that reuses a terminated PID. Probably introduced with the round-1 CA-01 fix, since round 1…
| CA-03 | who-controls | Informational | Group-signal capability gate | V4:342 ("without a forced waiter thread") | N:28, 703, 708 | The forced-waiter check reads the JS `process.env` object. `[INFERENCE]` Bun reads the real C environment when it starts. Host JS that deletes the variable before this module loads would leave signaling enabled while Bun reaps on a waiter thread, reopening the reap-vs-kill race. The Bun 1.3.14 source reasoning exists only as a one-line comment (N:703); no source revision or file:line is retained in CR. Operator/host trust makes this informational. | Read the variable through FFI `getenv` at the gate (N:704-715), and record the Bun 1.3.14 source revision and `process.zig` lines in CR as the retained basis for V4:342. |
| CA-04 | clause-to-line | Informational | Group-signal capability gate | V4:342 ("runtime guarantees that reaping cannot race the signal") | N:704-728 | The gate does not exclude kernel auto-reaping. `[INFERENCE: if the producer inherits SIGCHLD=SIG_IGN or SA_NOCLDWAIT, XNU reaps exiting children without waitpid, and Bun does not reset this]` In that case `exitCode === null` does not prove the leader is unreaped. The remaining window is the synchronous N:716-N:728 span, and exploiting it also needs PID reuse plus `setsid` within that span, so practical risk is negligible. Still, the premise is assumed rather than checked. | At the gate, read `sigaction(SIGCHLD)` through the existing libSystem FFI and refuse when the handler is SIG_IGN or SA_NOCLDWAIT is set…

## Summary

- Total findings: 4
- By severity: Critical=0 Major=0 Minor=2 Informational=2
- By lens: commitment-coverage=0 clause-to-line=3 deferred-cannot-silently-succeed=0 who-controls=1 field-name=0 deferral-justification=0
- Round-1 closure: CA-01 closed (conditional on V4:342), CA-02 closed (new fail-closed CA-01), CA-03 closed. The descriptor-adoption evidence limit is unchanged.
- No path was found that releases ownership, closes a window or stamps `terminated_at` without census proof. No new false-PASS or stale-evidence path was found in the native delta.
- Recommended next step, in order:
  1. Fix CA-01 (zero-length sysctl means vanished) and correct the TR mock.
  2. Fix CA-02 (live-only birth recheck plus a birth-based skip at N:1609).
  3. Fix CA-04 (SIGCHLD disposition check at the gate).
  4. Fix CA-03 (FFI `getenv`, plus retain the Bun source citation in CR).
  5. Rerun `TR` and the native lifecycle suites in `TL` on Darwin and Linux.
- Not checked: Bun 1.3.14 reaping internals, XNU `KERN_PROC_PID` and `e_sess` behavior, and whether the worktree matches `6c787c2`, because no git or shell was available. CA-01, CA-02 and CA-04 come from reading the code; none was reproduced.
