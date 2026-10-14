VERDICT: SURVIVES (the bounded correction closes the shared-member contradiction; no new concrete defect was found in its reviewed dependencies)

Paths are relative to `/Users/mv/Development/reliq-fv-wt/evidence-perf/`.

## Attacks on the revision

No surviving findings in this bounded delta. Reviewed the corrected claim-result, physical-checkpoint, resume, failure-cutoff and final-assessment rules, together with the dependent incremental/CONCEPTS prose and acceptance cases. Prior findings remain closed at contract level under the previously reviewed assumptions.

## Disposition of the sole remaining finding

**Review 2, finding 1: CLOSED AT CONTRACT LEVEL.**

The former rule required a shared candidate to exceed every member's observation cutoff. The revised rule evaluates eligibility for the particular canonical claim/tool association while retaining the complete physical descriptor and history:

> “Eligibility of candidate E for M requires E's own actual execution PASS sequence strictly greater than M's cutoff, plus M's subsequent PASS observations referencing E. It does not require E to exceed another member's observation cutoff.” (`docs/execution-evidence-v4.md:480`)

Claim-result computation now agrees:

> “Another member's observation FAIL does not invalidate this claim's otherwise eligible reference to the shared checkpoint.” (`:414`)

This closes the counterexample without weakening the failed member's barrier.

### Analytical replay of the original counterexample

For EX-004 physical PASS at sequence 10, C-01 observation PASS at 11, C-02 PASS at 12 and C-04 observation FAIL at 13:

- C-01 and C-02 may retain and revalidate their references to sequence 10. C-04's observation failure is not their cutoff.
- C-04 remains FAIL. Observation-only rechecking of sequence 10 cannot clear its barrier.
- Selecting only C-01 permits reuse without dispatching another shared execution solely for unselected C-04.
- Full assessment still includes C-04's failure, so selection cannot turn the policy result into PASS.
- Selecting blocked C-04 requires a later actual shared invocation and C-04's own passing observations. All descriptor members are assessed separately for that new invocation.

These outcomes follow directly from `:456,480-484`. The exact sequence-10/11/12/13 trace is also required by the acceptance checklist at `:617`; the text explicitly identifies it as an analytical acceptance case rather than a reported run.

## Regression checks against the changed boundary

These are contract analyses, not executed tests.

1. **Physical failure still reaches every affected member.** The correction does not restrict a real execution failure to whichever claim happens to be selected:
   > “An execution FAIL applies to every member recorded for that execution.” (`:480`)

2. **Observation failure remains local to its association.** Both the cutoff rule and observation-recheck rule apply that failure only to its selected member (`:480-482`). This now agrees with the existing mixed-result observation rule at `:418`.

3. **Indeterminate completion follows the same distinction.** Indeterminate execution completion applies to the original pending members; indeterminate observation completion applies to its selected member (`:480`). Neither is fabricated as a genuine FAIL.

4. **Selection cannot remove descriptor members or history.** The resume clause retains complete descriptor membership and history, and defines plan/work cache decisions as selected-member reuse rather than an assertion that every descriptor member passes (`:456`). Full assessment still evaluates every required member (`:484`).

5. **Key rollback and observation-only retries remain blocked for the failed member.** The revised per-member rule preserves cross-key association matching and explicitly prohibits observation-only clearing of that member's barrier (`:480-482`).

6. **Dependent prose agrees.** `docs/incremental-reverification.md:222-232` distinguishes physical failures from member-observation failures and preserves full-assessment FAIL. `CONCEPTS.md:278-284` states the same distinction. The updated checklist at `docs/execution-evidence-v4.md:616-617` covers both physical-failure fan-out and mixed-member reuse.

## Prior closures and trust limits

The ten original findings retain their review-2 dispositions. This bounded change does not reopen them or establish their implementation.

The previously accepted limits also remain:
- Endpoint equality relies on the declared no-uncoordinated-mutation assumption; it does not prove ABA exclusion.
- Generated product correctness and freshness rely on declared upstream build-cache integrity; a real invocation does not prove fresh compilation.
- Retained-history completeness/nondeletion relies on the trusted store/export boundary; hashes do not authenticate a missing suffix.
- Producer/OS honesty remains necessary. Stored hashes and policy-conforming records do not independently prove that commands ran.

No additional sandbox, platform mechanism, schema expansion or Dossier change is required by this disposition.

## Remaining blockers

No specification blocker remains from the bounded finding reviewed here. Runtime correctness and acceptance-case execution remain unestablished by this review.

## META

- **Reviewer identity**: Available model metadata is `openai-codex/gpt-6-astra`, operating as an OMP-native repository-aware reviewer. Different reviewer assignment and nominal model from the supplied authors do not establish provider-family independence. Provider fallback, thinking-level attestation and route calibration were unavailable.
- **Review mode**: Bounded delta, as requested. Examined the corrected eligibility clauses and their dependent overview/checklist wording. This is not a new full-system audit or an implementation verdict.
- **Categories attacked**: Contradiction, over-specification, temporal-state mismatch, composition and coverage at physical/member result separation, history cutoffs, selection and retry behavior. No surviving attack was grounded in the corrected text.
- **Categories without new evidence**: No separate ambiguity, triviality, edge-case or refinement-mismatch finding emerged in this delta. Mathematical impossibility-hypothesis and disjunction/decomposition categories do not apply. Previously closed unrelated sections were not reopened.
- **Revision provenance**: The parent supplied the frozen contract/overview hashes and preservation-check results. They were not independently recomputed or rerun. Parent-reported documentation-link, Gate A and canonical 69/108 preservation results are supplied context, not runtime evidence from this reviewer.
- **Unexercised verification**: No commands, tests, builds, gates, formatters, probes or hash computations were run. No files were edited, no commits were made and no process-control operations were performed.
- **Evidence still wanted for implementation acceptance**: Real producer/consumer results for the mixed EX-004 trace, a subsequent physical FAIL affecting all recorded members, member-specific observation failure during cache revalidation, and selective retry with the full policy still retaining unselected failures. These were not provided as exercised v4 behavior.
- **Confidence**: High in closure of the sole remaining contract finding within this bounded scope. No runtime-proof claim is made.