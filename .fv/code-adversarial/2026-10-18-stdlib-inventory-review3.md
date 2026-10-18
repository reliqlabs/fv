# Code-adversarial review: dossier / external FV argument-state isolation - 2026-10-16

- Operator: fv-code-adversary via OMP task (NOT CloseStdlibClosure worker or parent)
- Code commit reviewed: `42e5935`; declared delta base: `1e92350`
- Intent version reviewed: no version frontmatter present; canonical `docs/intent.md`, scoped to I11–I14
- Ledger version reviewed: no timestamp frontmatter present; header reports Updated `2026-10-16`
- Lens pack: execution-provenance and dependency-selection, using the six required crypto/enclave-derived lenses
- Lenses applied: 1 through 6

Citation prefixes:

- `D`: `/Users/mv/Development/burnt/dossier-wt/evidence-perf`
- `F`: `/Users/mv/Development/reliq-fv-wt/evidence-stdlib-closure`
- `T`: `F/tools/evidence-v4/evidence-v4-toolchain.ts`
- `TT`: `F/tests/r38_evidence_v4_toolchain_review.py`
- `V4`: `F/docs/execution-evidence-v4.md`
- `CR`: `F/.fv/changes/2026-10-14-execution-evidence-v4.md`

D’s dispatch still resolves the canonical intent to `docs/intent.md`. This review covers the argument-copy correction, its supported abstract values, and immediately shared analyzer state. Proposed root/Verus behavior is outside this implementation correction.

CA-03 is closed for both reported mechanisms: hypothetical visits no longer consume application visitation state, and hypothetical argument mutations no longer alter the caller’s argument list. No new finding was established in this delta. Base CA16/17 remain open and are carried below.

No commands, tests, builds, formatters, or edits were performed. Parent reports that the argument regression reproduced the old omission and that all four state-boundary methods passed after correction. The retained capture was inspected and records `ok: true`, with 41 producer file entries and 3,215 Python-runtime entries. These are regression and metadata-acceptance observations, not proof or canonical-collection evidence.

Important uncovered classes include concurrent mutation, filesystem races, resource exhaustion, upstream interpreter/package integrity, and build-cache coherence. Complete Python semantics and other adapters are outside this review.

---

## Lens 1 - Commitment coverage

| Commitment | Attacker DoFs | Bound by | Gap |
|---|---|---|---|
| Application argument-dependent imports | An inventoried but unexecuted shadow changes argument elements, slices, or list contents | T:679 now passes `copy.copy(argv)` into each hypothetical visit; T:1337–1339 retains the original request argument list for application analysis | Reported CA-03 argument-contamination mechanism corrected |
| Application path-dependent imports | Hypothetical shadow modifies its search path and populates visitation state | T:677–680 uses fresh `seen`, copied roots, and a separate `ImportPaths`; caller cache and roots are restored in `finally` | Prior CA-03 cache/path mechanism remains corrected |
| Abstract argument classifications | Argument-list subtype and classified elements influence later analysis | T:679 uses shallow copying rather than coercion to a plain list; T:750–751 defines `PathSnapshot`; T:769 defines `LiteralArgument` | No classification-erasure defect established |
| External dependency contents discovered by hypothetical or actual analysis | Selected file contents and transitive imports | T:1298–1302 retains analyzed-source hashes; T:1324–1348 preserves per-request requirement accumulation | Correction does not discard discovered dependencies |
| Per-request and cross-request inventory | Repeated command contexts and differing tool scopes | Request-local sets reset at T:1326 after prior requirements are materialized; selections and project-shadow membership remain cumulative | TT:718–739 covers retention for both request IDs; no new accumulator-loss defect established |
| Loader-helper root and imported-helper targets | Runtime root values and arguments supplied from other modules | T:1075–1089 and T:1138–1139 | Carried CA-01/02, corresponding to Base CA16/17 |

### Copy-semantics assessment

The mutable object implicated by the previous counterexample is the argument list itself. The scanner returns that list for `sys.argv` at T:876 and mutates list receivers at T:1175–1197. Copying it before each hypothetical visit prevents those writes from reaching the application list.

The shallow copy preserves the concrete list subtype and existing element classifications. It does not convert `LiteralArgument` values or list subclasses into weaker abstract values.

This conclusion is bounded to admitted representations:

- Initial request arguments are strings supplied by the command context.
- The inventory and visit keys hash tuples containing argument elements at T:649–652 and T:1295–1297.
- Nested list/dictionary elements are unhashable and cannot pass those key operations as a supported nested mutable argument structure.
- No deep-copy requirement is inferred for representations that already fail before admitted analysis.

The flags dictionary remains shared, but the inspected mutation paths act on list receivers. Attribute reads retrieve flag values at T:887; subscript and method mutation branches at T:1175–1197 do not mutate dictionary receivers. The preservation control in TT:682–683 exercises this distinction.

## Lens 2 - Clause-to-line discharge

| Clause | Expected discharge | Actual code line | Status |
|---|---|---|---|
| D I11, `docs/intent.md:25`: complete dependency/tool provenance; unsupported closure prevents PASS | Hypothetical discovery must not change application inputs used for dependency selection | T:677–680,1337–1339 | discharged for the two reported CA-03 mechanisms; overall provenance remains partial because CA16/17 are open |
| V4:229: fully model admitted selector forms or refuse | Preserve the scope and classifications of mutable analyzer inputs | T:679; T:750–751,769,876; T:1175–1197 | discharged for the inspected argument-copy boundary |
| V4:235: bind required external Python dependencies | Analyze imports under the actual command arguments | T:679 isolates hypothetical arguments; application receives original arguments at T:1338–1339 | Reported wrong-branch mechanism corrected |
| V4:243: retain discovery identities and detect changed dependencies | Selected external bytes affect the discovery identity | T:1298–1302; TT:705–716 checks selected-file membership and changed-byte identity | Mechanism present; regression execution is parent-reported |
| V4:249,251: complete transitive closure or refusal | Preserve dependency accumulators while isolating hypothetical state | T:677–680,1324–1348 | discharged for accumulator preservation in this correction; not a universal closure result |
| D I11 trust premises | Endpoint checks do not claim immutable execution or cache coherence | Canonical I11 retains these premises; CR:241 makes no canonical-evidence claim | Explicit assumptions remain |
| D I12, `docs/intent.md:32`: preserve execution recipes, observations, failures, and ownership | Metadata correction must not manufacture successful execution evidence | T:1348–1349 emits metadata; CR:241 retains pending integration qualification | No changed verdict or ownership mechanism in this delta |
| D I13/I14, `docs/intent.md:33–34`: activation separation and restricted authority | No capture result activates production or authorizes live actions | CR:241; D ledger item 40 at `.fv/ledger.md:618` | Preserved disposition |
| D ledger item 40 | Failed collection and indeterminate owner remain unresolved | Ledger:618 expressly separates isolated repairs from collection qualification | Still open; this correction does not discharge it |

## Lens 3 - Deferred cannot silently succeed

| Branch | Reachable from | Behavior | Status |
|---|---|---|---|
| Hypothetical visit and copy | `inventory_stdlib` | Copy and visit occur inside `try`; `finally` restores caller cache/roots, T:677–680 | No swallowed exception or success fallback |
| Unsupported argument key representation | Inventory/visit key construction | Unhashable nested mutable values fail at set lookup/insertion, T:649–652,1295–1297 | No silent-success path established |
| Unsupported selected stdlib loader/package/native/source | Inventory | Explicit exceptions remain at T:664–672,681 | Refusals retained |
| Deferred function analysis | Scanner | Existing deferred analysis remains separate from this correction | No new stub introduced |
| Known helper-analysis limitations | Helper specialization and imported callable handling | Root substitution and unknown imported names remain at T:1084–1086,1138–1139 | Carried CA-01/02 |

No new deferred branch returning success without analysis was identified in the bounded delta.

## Lens 4 - Who controls

| Field | Supplier | Validation | Gap |
|---|---|---|---|
| Application `argv` | Reviewed command context | Hypothetical visits receive a separate copy at T:679; application receives original request arguments at T:1338–1339 | Reported contamination corrected |
| Hypothetical `argv` | Copy of caller arguments, then admitted abstract list operations | List mutation remains local to the copied object, T:1175–1197 | No new gap established for admitted representations |
| `flags` | Derived interpreter/request configuration | Read through the flag view; inspected mutation branches do not write dictionary receivers, T:887,1175–1197 | No cross-inventory mutation established |
| `seen` and `import_roots` | Analyzer visitation and supported file loaders | Fresh/copy state restored at T:677–680 | Prior isolation retained |
| `required` and `source_inputs` | Hypothetical and application dependency analysis | Intentionally shared within each request; materialized/reset at T:1324–1348 | No new requirement loss established |
| `stdlib_selections` and project-shadow membership | Namespace inventory | Continue accumulating across requests, T:658–682 | Unchanged by argument copying |
| Helper root/imported helper arguments | Runtime callers | Name-based root substitution and loss of ordinary imported callable identity | Carried CA-01/02 |

## Lens 5 - Field-name fidelity

| Field | Implied semantic | Actual value | Status |
|---|---|---|---|
| Per-request `requirements` | Files required by analysis for the associated tool scope | Materialized from accumulated dependencies at T:1348 | No new naming mismatch; overall completeness remains bounded |
| `source_inputs` | Hashes of analyzed file bytes | Populated at T:1300–1302 | Faithful |
| `stdlib_selections` | Finder observations under inventoried search contexts | Recorded at T:658–682 | Faithful as inventory, not an executed-import trace |
| Discovery identity | Identity of retained probe output | Existing stream-hash mechanism; TT:716 checks changed selected bytes affect discovery | No independent field-name defect |
| Capture `ok` | Capture operation accepted | Retained capture records `ok: true` and tool identities | Metadata acceptance only |

No field-name finding was established.

## Lens 6 - Deferral justification audit

| Deferred finding | Justification claims | Claim audit | Verdict |
|---|---|---|---|
| CA-03, original cache/path mechanism | Hypothetical visits do not consume application visitation state or leak loader roots | T:677–680 retains fresh/copy state and restoration; TT:647–677,741–775 retain focused regressions | Closed for the reported mechanism |
| CA-03, argument residual | Hypothetical mutation cannot change application arguments | T:679 copies arguments before analysis; TT:679–716 compares actual interpreter output, required real/decoy files, and changed-real-file discovery identity | Closed for the reported residual |
| Copy classification preservation | Isolation must not erase supported argument-list classifications | `copy.copy` at T:679 preserves subtype; classified elements are retained | Supported by code semantics; no broader nested-object support inferred |
| Flags preservation | Shared flags are read-only in the analyzer | T:887 reads flags; T:1175–1197 mutates lists only; TT:682–683 supplies the preservation control | Supported for the inspected paths |
| Base CA16/17 | Remain incomplete | Explicit limitation at T:1051; mechanisms remain at T:1084–1086,1138–1139 | Accurate OPEN disposition |
| Four state methods and D capture | Regression and metadata acceptance only | Parent reports executions; retained capture was inspected; CR:241 leaves confirmation/integration checks pending | Limited evidence claim is accurate |
| Generic reuse, canonical collection, activation | Not established by isolated fixes | D I11–I14 and ledger:618 retain these boundaries | Remain unqualified |

No wrong-deferral finding was established.

---

## Finding list (consolidated)

| ID | Lens | Severity | Surface | Intent ref | Code ref | Summary | Fix |
|---|---|---|---|---|---|---|---|
| CA-01 | commitment-coverage | Major | Python helper-root selection | D I11, `docs/intent.md:25`; V4:229,235,249,251 | T:1075–1089, especially 1084–1086 | OPEN, carried Base CA16. A matching argument name is replaced with the project root without establishing its runtime value. This argument-isolation correction does not change that mechanism. | Establish the actual root value or refuse unsupported invocations. Keep fresh-provenance limits explicit. |
| CA-02 | commitment-coverage | Major | Imported Python loader helpers | D I11, `docs/intent.md:25`; V4:229,235,249,251 | T:1075–1089,1138–1139 | OPEN, carried Base CA17. Defining-file specialization does not establish targets selected by imported-helper callers; ordinary imported callable identity is discarded. | Preserve helper identity and validate caller arguments, or refuse unsupported imported-helper use. |

## Summary

- Total findings: 2 open, both carried; 0 new findings in this correction
- By severity: Critical=0 Major=2 Minor=0 Informational=0
- By lens: commitment-coverage=2 clause-to-line=0 deferred-cannot-silently-succeed=0 who-controls=0 field-name=0 deferral-justification=0
- CA-03: closed for the reported visit-cache/path-effect and argument-contamination mechanisms.
- CA21: the reported transitive split-stdlib namespace omission is addressed within the inventoried namespace and admitted selection forms. External package/native refusal and source binding remain in place. This does not establish complete Python analysis or discharge Base CA16/17.
- Recommended next step:
  1. Preserve the four state-boundary regressions during parent integration.
  2. Address Base CA16/17 separately under their reviewed implementation contract.
  3. Keep generic reuse, canonical collection, and activation unqualified; leave Dossier’s failed collection and indeterminate owner unchanged.