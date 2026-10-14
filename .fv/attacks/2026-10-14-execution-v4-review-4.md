VERDICT: SURVIVES (the lifecycle clarification states a conditional supervision guarantee without claiming arbitrary process containment)

Paths are relative to `/Users/mv/Development/reliq-fv-wt/evidence-perf/`.

## Attacks on the revision

No concrete defect was found in this bounded delta. The added assumption is explicit, and the adjacent lifecycle rules continue to reject known uncertainty rather than converting it into successful cleanup.

### Reviewed trust boundary

The new clause requires reviewed commands and their descendants to obey the declared lifecycle:

> “They MUST NOT make undeclared group/session escapes, daemonize, or double-fork/reparent to evade supervision.” (`docs/execution-evidence-v4.md:330`)

It then limits the supervisor's claim:

> “It is not an OS sandbox: POSIX group snapshots cannot prove absence of arbitrary setsid/double-fork/reparent escapes between enumerations, and Darwin NOTE_TRACK/NOTE_CHILD support is not assumed.” (`:330`)

This is an honest approved-command/tool and OS trust boundary. It does not claim that periodic process enumeration establishes complete ancestry or that arbitrary hostile descendants remain contained. The review does not require an additional sandbox or a different platform mechanism to support that expressly limited claim.

### Consistency with retained guarantees

1. **Known escapes remain failures.** The same clause states:
   > “An observed undeclared escape or unprovable termination is ERROR/indeterminate, keeps the existing ownership/resource restrictions, and never authorizes signaling a foreign or ambiguously owned PID.” (`:330`)

   Thus the assumption cannot be used to dismiss an observed violation or release a resource whose owner is uncertain.

2. **Separate sessions still require explicit ownership.** The clarification requires registered ownership for separately sessioned children and declared identity/resource ownership for external services (`:330`). The existing Quint private-pipe protocol, gate, OS-identity validation and durable registration before ACK remain specified at `:332-338`. Ordinary direct process-group supervision is not silently substituted for that protocol.

3. **Spawn gaps still fail closed.** Pending native spawn windows remain mandatory (`:328`). The collector-lifetime window still covers the old wire's missing before-Popen event. Abnormal stop, missing registration and partial control messages remain indeterminate; known-group termination alone does not prove that unregistered work stopped (`:338`).

4. **Cancellation does not become successful completion.** Only proven-owned groups may be signalled. Timeout/cancellation cannot PASS; normal completion still requires actual normal exit, stopped owned groups and closed windows (`:340`). These guarantees are conditional on the declared command lifecycle, not a proof against an undetected malicious escape.

5. **Recovery does not acquire a new shortcut.** Pending/indeterminate windows prevent normal release (`:551`). Recovery still refuses live, foreign, changed or unprovable ownership and requires history accounting before lock retirement (`:553`). The clarification does not authorize PID-only recovery or treating a missing leader as proof that descendants stopped.

6. **Overview prose preserves the limitation.** `docs/incremental-reverification.md:238-244` and `CONCEPTS.md:288-294` repeat the approved-lifecycle assumption, the absence of an arbitrary-containment claim, and the ERROR/indeterminate treatment of observed escapes or unknown termination. The lifecycle acceptance clauses at `docs/execution-evidence-v4.md:620-621` remain consistent with those conditions.

## Counterexample directions examined

These are analytical checks, not executed tests.

- A descendant escapes between snapshots without being observed: the revision explicitly excludes arbitrary nonconforming containment from the guarantee. It does not claim that the snapshots detect this trace.
- An escape is observed before completion: the prescribed outcome is ERROR/indeterminate with ownership/resource restrictions retained, not PASS or presumed cleanup.
- A collector dies between separate-session spawn and registration: the existing lifetime window remains indeterminate. The added assumption does not make an empty registered-child list sufficient for recovery.
- A PID or group becomes ambiguously owned: the clarification retains the prohibition on signalling it. Lifecycle uncertainty does not grant authority over another process.
- A separately declared external service survives a recipe: it remains subject to its separate identity/resource boundary and is not misclassified as an owned child to kill.

No contradictory success or recovery path was found in the reviewed text.

## Disposition and prior closures

The implementation-discovered lifecycle clarification survives this bounded review. No new specification blocker is reported.

All prior contract closures remain in force, including the round-3 separation of physical checkpoint validity from per-member eligibility. This report neither reopens those findings nor establishes that their implementations are correct.

The existing nonmutation, upstream build-cache integrity, trusted retained-history completeness and filesystem durability assumptions remain assumptions. The lifecycle clarification adds no proof of command execution, continuous process containment or hardware persistence.

## META

- **Reviewer identity**: Available model metadata is `openai-codex/gpt-6-astra`, operating as an OMP-native repository-aware reviewer. Different assignment and nominal model from the supplied authors do not establish provider-family independence. Provider fallback, thinking-level attestation and calibration were unavailable.
- **Scope**: Reviewed the lifecycle clarification, native/collector registration and cancellation rules, ownership recovery, relevant operational/provenance clauses, dependent overview prose and lifecycle acceptance clauses. This was not a full re-audit or implementation review.
- **Categories attacked**: Preconditional over-strength, contradiction, temporal-state mismatch, composition failure and edge cases around escape, registration gaps, cancellation, PID ownership and recovery. No surviving finding was grounded in this delta.
- **Categories without evidence**: No additional ambiguity, coverage gap, triviality or refinement-mismatch finding was established within the bounded change. Mathematical hardness/decomposition categories are inapplicable.
- **Revision provenance**: The parent supplied the revised hashes and documentation-link result. This reviewer read the named files but did not recompute hashes or rerun checks. The reported Darwin SDK limitation is supplied implementation context; this review did not inspect the SDK or test NOTE_TRACK/NOTE_CHILD support. The contract no longer depends on that support.
- **APFS evidence limit**: The parent's reported file/nested-directory/ancestor fsync probe is not an observation made by this reviewer. Successful syscalls alone do not prove hardware durability, and no such proof is claimed here.
- **Unexercised verification**: No commands, tests, builds, gates, formatters, probes, edits, commits or process-control operations. No runtime verdict is made.
- **Implementation evidence still needed**: Exercised registration, observed-escape, uncertain-termination, cancellation and recovery behavior under the declared lifecycle boundary. Approval of this wording does not establish that any selected tool or descendant actually obeys the assumption.
- **Confidence**: High in the truthful scope and internal consistency of this bounded clarification. No runtime-proof claim is made.