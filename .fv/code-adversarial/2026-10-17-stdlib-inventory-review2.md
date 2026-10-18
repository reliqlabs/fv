# Code-adversarial review: dossier / external FV stdlib state correction - 2026-10-16

- Operator: fv-code-adversary via OMP task (NOT CloseStdlibClosure worker or parent)
- Code commit reviewed: `1e92350`; declared delta base: `62301ca`
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

D’s dispatch still selects `docs/intent.md`. This re-review covers CA-03’s correction and shared-state consequences. Proposed root/Verus contract drafts are not treated as implemented obligations of this correction.

The original visit-cache/path-effect mechanism is corrected. CA-03 remains open through a newly identified shared-`argv` residual: hypothetical shadow analysis can mutate the application’s argument list before application scanning and eliminate a real dependency branch.

No commands, tests, builds, formatters, or edits were performed. Parent-reported observations are two pre-correction missing-dependency failures, three corrected regression methods, and 59 passing toolchain methods. The new retained capture was inspected and records `ok: true`, with `fv-producer` and `python-runtime` identities. These observations do not establish complete dependency provenance.

Important uncovered classes include concurrent mutation, filesystem races, resource exhaustion, upstream interpreter/package integrity, and cache coherence. This review does not qualify arbitrary Python semantics or other producer adapters.

---

## Lens 1 - Commitment coverage

| Commitment | Attacker DoFs | Bound by | Gap |
|---|---|---|---|
| Application import selection after hypothetical inventory | Shadow-module contents and admitted path mutations | T:675–680 creates fresh `seen`, copies `import_roots`, and restores both caller objects in `finally` | Original CA-03 cache-consumption mechanism is corrected. |
| Argument-dependent import selection | An inventoried shadow mutates `sys.argv`; application branches on its actual arguments | T:679 still passes the original `argv` object; T:1042 preserves that object; T:876 exposes it as `sys.argv` | CA-03 residual: speculative mutation reaches application analysis and can omit a real external dependency. |
| Per-request external requirements and analyzed-source hashes | Dependencies found by hypothetical and application visits | T:1298–1302 retains analyzed bytes; T:1324–1348 materializes requirements and resets request-local accumulators | The correction does not discard these accumulators. TT:679–700 checks both request scopes. |
| Inventory selection metadata and project-shadow membership | Available names, selected files, request/path states | T:649–682 retains selection state and project files; T:1337 inventories each request | No new accumulator-loss defect established. Metadata can still describe analysis based on contaminated arguments. |
| Loader-root scope | Fallback roots introduced while analyzing supported file loaders | T:677–680 copies/restores root objects; T:724–731 maintains scoped push/pop | No new root-restoration defect established. TT:702–736 checks dependency capture and refusal of escaped fallback roots. |
| Helper root and imported helper targets | Runtime root values and cross-module arguments | T:1075–1089 and T:1138–1139 | Carried CA-01/02, corresponding to Base CA16/17. |

### CA-03 residual: hypothetical inventory mutates the real request’s `argv`

The correction isolates `seen` and `import_roots`, but passes `argv` unchanged at T:679. The scanner retains the supplied list at T:1042. Reading `sys.argv` returns that list at T:876, and ordinary subscript assignment mutates it at T:1175–1179.

Request processing inventories shadows before analyzing the application, passing the same `request['argv']` to both operations at T:1337–1339.

A static counterexample uses this arrangement:

| Input | Contents |
|---|---|
| Invocation | `python main.py actual` |
| Project `colorsys.py`, never imported by the application | `import sys` followed by `sys.argv[1] = "inventory"` |
| `main.py` | `import sys`; if `sys.argv[1] == "actual"`, import `real_plugin`; otherwise import `decoy_plugin` |
| External module path | Contains both `real_plugin.py` and `decoy_plugin.py` |

Analysis sequence grounded in the code:

1. Request inventory considers project `colorsys.py` because it shadows an interpreter-declared stdlib name.
2. Its hypothetical visit assigns `"inventory"` into the actual request list.
3. `finally` restores only `seen` and `import_roots`.
4. Application scanning receives the changed list.
5. Equality is evaluated concretely at T:1004–1011. T:1202–1203 scans only the selected branch.
6. The analyzer selects `decoy_plugin`, despite the actual invocation supplying `"actual"` and never importing `colorsys`.

[INFERENCE] With ordinary startup that does not independently import this shadow, execution imports `real_plugin`; discovery can omit it and accept a declaration set binding only `decoy_plugin`. Changing the omitted external file would then leave the discovered closure unchanged.

This runtime consequence was not executed. The shared object, mutation, ordering, and branch pruning are directly visible in the cited code. The counterexample does not use helper-root substitution, imported loader helpers, reflection, or an unsupported loader.

The concrete fix belongs at the hypothetical-visit boundary: isolate mutable argument state as well as import state, while preserving the intended shared dependency/source accumulators. Add a regression where an unimported shadow mutates arguments and the application chooses between two external imports.

## Lens 2 - Clause-to-line discharge

| Clause | Expected discharge | Actual code line | Status |
|---|---|---|---|
| D I11, `docs/intent.md:25`: complete dependency/tool provenance; unsupported closure prevents PASS | Hypothetical discovery cannot change the effective application inputs used for dependency selection | T:679,876,1042,1175–1179,1337–1339 | gap: CA-03 shared-argument residual |
| V4:229: fully model admitted selector forms or refuse | Admitted mutable selector state must have correct scope | T:675–680 isolates cache/roots; argument list remains shared | partial |
| V4:235: bind required external Python dependencies | Capture imports selected under the real command context | T:1004–1011,1202–1203 uses concrete conditions; T:1337–1339 supplies contaminated arguments | partial: CA-03 can prune the real dependency branch |
| V4:243: retain selection identities and revalidate | Changed actual dependency bytes affect the compared identity | T:1298–1302 records analyzed source hashes; unchanged revalidation consumes discovery identities | partial: hashing cannot identify an omitted input |
| V4:249,251: complete transitive closure or preflight refusal | All admitted external dependencies are required | T:717–722 discovers imports; T:1324–1348 retains requirement sets | partial: CA-01/02 remain, and CA-03 can select the wrong import |
| D I11: endpoint/nonmutation and upstream-cache premises | Avoid stronger sandbox/cache-correctness claims | CR’s state-correction section retains provenance limits | Explicit assumptions remain; this correction does not discharge them |
| D I12, `docs/intent.md:32`: unchanged recipes, observations, failures, and ownership | Metadata correction must not manufacture successful execution evidence | T:1348–1349 emits inventory metadata; CR’s correction section records tests/capture only | No changed execution-verdict mechanism found in this slice |
| D I13/I14, `docs/intent.md:33–34`: activation separation and restricted authority | No capture result activates production or authorizes live action | CR’s correction section; D ledger item 40 at `.fv/ledger.md:618` | Preserved disposition |
| D ledger item 40 | Failed collection and indeterminate owner remain unresolved | CR explicitly leaves installed FV, failed collection, and owner untouched | Preserved; no new canonical evidence qualification |

## Lens 3 - Deferred cannot silently succeed

| Branch | Reachable from | Behavior | Status |
|---|---|---|---|
| Hypothetical source visit | `inventory_stdlib` | `try/finally` restores saved cache/root objects; no exception suppression, T:677–680 | Correct restoration for those two objects; CA-03 covers the omitted argument object |
| Unsupported selected loader/package/native/source | Stdlib inventory | Explicit exceptions remain at T:664–672,681 | No silent-success stub |
| Recursive source visit | `visit` | Existing active recursion guard and removal remain at T:1310–1313 | No new placeholder behavior established |
| Known helper-analysis limitations | Loader specialization and ordinary imported names | Name-based root substitution and unknown imported callable handling remain | Carried CA-01/02 |
| Argument mutation during hypothetical analysis | Source assignment followed by application scan | Mutates shared list without refusal, T:1175–1179; branch analysis continues at T:1202–1203 | CA-03; counted under commitment coverage |

No new labeled TODO/mock implementation branch was found in the bounded correction.

## Lens 4 - Who controls

| Field | Supplier | Validation | Gap |
|---|---|---|---|
| Request `argv` | Reviewed command initially; hypothetical project shadow can mutate the analyzer’s list | T:679 passes it by reference; T:876,1042,1179 preserve and mutate that reference | CA-03: speculative source can replace effective analysis input without changing the actual command |
| `seen` | Analyzer visitation | Fresh set per hypothetical source visit; caller object restored at T:677–680 | Original pollution mechanism corrected |
| `import_roots` | Supported file-loader analysis | Copied at T:678; restored at T:680; push/pop at T:724–731 | No new scope escape established |
| `required`, `source_inputs` | Hypothetical and actual source analysis | Accumulate through the request; materialize before request reset at T:1324–1348 | Intended sharing preserved |
| `inventory_seen` | Analyzer’s path/context inventory | Key includes paths, roots, cwd, argument values, flags, and project mode at T:649–652; reset per request at T:1326 | Does not prevent mutation of the original argument object after key construction |
| `stdlib_selections`, `project_stdlib_files` | Inventory output across requests | Append/add semantics at T:658–682 | No new loss of accumulated selections established |
| Helper root/imported helper arguments | Application callers | Root-name substitution and ordinary imported-name abstraction | Carried CA-01/02 |

## Lens 5 - Field-name fidelity

| Field | Implied semantic | Actual value | Status |
|---|---|---|---|
| Discovery stream identity | Hash of what the analyzer emitted | Existing probe-output identity mechanism | No independent naming mismatch; semantic incompleteness is CA-03 |
| Per-request `requirements` | Dependencies found for the associated tool IDs | Materialized from the request’s accumulated set at T:1348 | Association preserved; actual-command completeness is not established |
| `source_inputs` | Hashes of analyzed files | Populated from read bytes at T:1300–1302 | Faithful to analyzed bytes |
| `project_stdlib_files` | Selected project shadows | Added at T:674 and retained across requests | Faithful |
| Capture `ok` | Capture operation accepted | Retained capture reports `ok: true` and tool identities | Metadata acceptance only |

No separate field-name finding was established.

## Lens 6 - Deferral justification audit

| Deferred finding | Justification claims | Claim audit | Verdict |
|---|---|---|---|
| Prior CA-03 cache/path mechanism | Hypothetical visits no longer consume application `seen`; caller loader roots are restored | T:677–680 supports both claims. TT:647–677 checks sequential versus unimported shadows and dependency-byte changes | Original mechanism corrected |
| CA-03 shared-state consequences | Inventory preserves caller analysis state | Only cache and roots are isolated; `argv` remains shared at T:679 and mutable at T:1179 | Incomplete closure; retain CA-03 for the newly identified argument residual |
| Requirement/source accumulation | Dependencies survive inventory visits and per-request reset | T:1324–1348 preserves materialization/reset order; TT:679–700 checks both request IDs | Supported for the inspected mechanism |
| Scoped loader roots | Nested file-loader analysis does not leak a fallback root | T:677–680,724–731; TT:702–736 | Supported for the inspected mechanism |
| Base CA16/17 | Remain incomplete | T:1051 explicitly retains the limitation; T:1084–1086 and T:1138–1139 preserve it | Accurate OPEN disposition; carried CA-01/02 |
| Reported 59 methods and actual D capture | Regression and metadata acceptance only | Parent reports test results; inspected capture contains `ok: true`, 41 producer entries, and 3,215 Python entries | Limited observation; existing new tests do not cover hypothetical argument mutation |
| Failed D collection and indeterminate owner | Isolated corrections do not clear historical failure/ownership | D ledger:618 and CR correction section | Accurate retained limitation |

The incomplete isolation is counted once as CA-03, rather than duplicated as a wrong-deferral finding. CR leaves independent confirmation pending.

---

## Finding list (consolidated)

| ID | Lens | Severity | Surface | Intent ref | Code ref | Summary | Fix |
|---|---|---|---|---|---|---|---|
| CA-01 | commitment-coverage | Major | Python helper-root selection | D I11, `docs/intent.md:25`; V4:229,235,249,251 | T:1075–1089, especially 1084–1086 | OPEN, carried Base CA16. A matching argument name is replaced with the project root without establishing its runtime value. This correction does not change that mechanism. | Establish the root argument value or refuse unsupported invocations. Keep fresh-provenance limits explicit. |
| CA-02 | commitment-coverage | Major | Imported Python loader helpers | D I11, `docs/intent.md:25`; V4:229,235,249,251 | T:1075–1089,1138–1139 | OPEN, carried Base CA17. Defining-file specialization does not establish targets selected by imported-helper callers; ordinary imported callable identity is discarded. | Preserve helper identity and validate caller arguments, or refuse unsupported imported-helper use. |
| CA-03 | commitment-coverage | Major | Hypothetical inventory/application state | D I11, `docs/intent.md:25`; V4:229,235,249,251 | T:677–680,876,1042,1175–1179,1202–1203,1337–1339 | PARTIAL correction, newly identified residual. Fresh visitation state fixes the previous path-effect loss, but speculative shadow analysis still mutates the actual request’s `argv`. An unimported shadow can cause application analysis to choose a different import branch and omit an external runtime dependency. Static counterexample above; not executed. | Isolate mutable argument state at the hypothetical-visit boundary while retaining dependency/source accumulators. Add unimported-shadow argument-mutation coverage and a changed-real-dependency invalidation check. |

## Summary

- Total findings: 3 open, comprising 2 carried base findings and 1 partially corrected finding with a newly identified residual
- By severity: Critical=0 Major=3 Minor=0 Informational=0
- By lens: commitment-coverage=3 clause-to-line=0 deferred-cannot-silently-succeed=0 who-controls=0 field-name=0 deferral-justification=0
- Original CA-03 disposition: visit-cache consumption and copied-path-effect loss are corrected; shared argument-state contamination prevents full closure.
- CA21 disposition: namespace inventory and external split-package/native refusal remain implemented, but supported-form provenance is not fully closed while CA-03 remains.
- Recommended next step:
  1. Isolate hypothetical argument state and have the parent exercise the supplied argument-dependent import counterexample.
  2. Retain the sequential path-effect, duplicate-request accumulation, and scoped-loader-root regressions.
  3. Keep Base CA16/17, generic reuse qualification, canonical collection, and activation open. Preserve Dossier’s failed collection and indeterminate owner unchanged.