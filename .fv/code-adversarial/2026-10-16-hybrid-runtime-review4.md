# Code-adversarial review: Dossier bounded Python refusal correction - 2026-10-16

- Operator: fv-code-adversary via OMP task (NOT the parent orchestrator, FixHybridResiduals, HybridBase, or HybridProof)
- Code commit reviewed: `c149b15`, delta against previously reviewed `9852d48`
- Intent version reviewed: frontmatter version absent; canonical target remains `D/docs/intent.md`, resolved through `D/.fv/dispatch.json`
- Ledger version reviewed: frontmatter timestamp absent; document states `Updated: 2026-10-16`
- Lens pack: evidence provenance and Python loader/input closure, using all six required crypto/enclave lenses
- Lenses applied: 1 through 6

## Scope and evidence

| Alias | Path |
|---|---|
| D | `/Users/mv/Development/burnt/dossier-wt/evidence-perf` |
| F | `/Users/mv/Development/reliq-fv-wt/evidence-hybrid-union` |
| T | `F/tools/evidence-v4/evidence-v4-toolchain.ts` |
| TT | `F/tests/r38_evidence_v4_toolchain_review.py` |
| V4 | `F/docs/execution-evidence-v4.md` |
| CR | `F/.fv/changes/2026-10-14-execution-evidence-v4.md` |
| Capture | `/var/folders/ph/n581g1fj3tnbq8n74hp05klc0000gn/T/fv-hybrid-runtime-selection-2tsNVA/identities.json` |

This delta reviews the explicit class-comprehension refusal and shared selector-propagation predicate. Prior reports remain immutable. Existing finding IDs retain their meanings; CA-09 identifies an additional statement-dispatch omission.

No commands, tests, builds, formatters, edits, or process changes were performed. Commit attribution is caller-provided; working-tree equality to `c149b15` was not independently established.

The parent reports ten failed assertions before correction, 48 passing toolchain methods afterward, and successful actual Dossier Python/Node capture. These observations are accepted without rerunning them.

The retained Capture contains `python-runtime`, `mobile-node-toolchain`, and the producer/dependency identities. It is metadata evidence, not a complete execution or qualification verdict.

The ledger still records Gate B as STALE, all 15 composition candidates as INCOMPLETE, and the fresh v4 attempt as ERROR with two ERROR physical slots and 80 MISSING slots. This delta does not clear those states.

Important uncovered classes remain process containment, concurrency/crash recovery, resource exhaustion, upstream-cache poisoning, supply-chain authenticity, and proof/model-to-implementation refinement.

## Delta disposition

| Surface | Disposition | Evidence |
|---|---|---|
| CA-03’s reported class-comprehension expression | Closed by explicit refusal for expressions reached by the analyzer | T:773 rejects list, set, dictionary and generator comprehensions in class scope. TT:428–443 covers all four kinds. |
| CA-08’s reported known-selector branch loss | Closed for the reviewed joins | T:697 supplies the shared classification; T:1035–1041 and T:1186 preserve it across branch and exception joins. TT:453–471 covers class/non-class if, loop and try forms. |
| Module/function comprehensions | Remain admitted under existing analysis | T:773 is class-context-specific; TT:444–451 retains ordinary module and method comprehension examples. This does not qualify general comprehension analysis. |
| Coverage of unsupported statement forms | New gap | `ast.Match` has no dispatch branch or explicit rejection. Its nested statements can bypass both import discovery and the new class-comprehension refusal. CA-09. |
| Prior CA-05 and CA-07 | Prior mechanism closures unchanged by this delta | Node-wrapper and selected-store corrections are outside the changed Python predicate/refusal paths. No broader qualification is inferred. |
| Four generic carried findings | Remain OPEN | Base CA-16/17, transitive CA-21 and generic CA-24 remain explicitly documented and implemented as incomplete boundaries. |

---

## Lens 1 - Commitment coverage

| Commitment | Attacker DoFs | Bound by | Gap |
|---|---|---|---|
| Class-comprehension loader values | Comprehension kind, outer opaque binding, class-local shadow | Explicit class-context refusal at T:773 | Reported direct expression blocked; unvisited statement bodies remain CA-09 |
| Known and opaque selector propagation | Selector assignment inside conditional, loop or exception paths | Shared `runtime_selector` at T:697; propagation at T:1035–1041,1186 | Reported CA-08 classification mismatch removed |
| Python import closure | Imports and loader expressions inside nested executable statements | `walk` handles named statement classes at T:1042–1204 | CA-09: `match` bodies are omitted |
| Registry snapshot/restoration | Literal keys, saved opaque values, restoration | Restricted snapshot handling at T:783–787 and existing opaque stores/iteration | Existing controls retained; no new registry-name exception |
| Root-by-name helper targets | Runtime root argument | T:1020–1022 substitutes the project root | Carried CA-01 |
| Imported helper targets | Caller-selected target outside defining-file specialization | T:1012–1025,1074–1075 | Carried CA-02 |
| Transitive split-stdlib inputs | External extension selected indirectly through stdlib | T:647–648 | Carried CA-04 |

### CA-09: unhandled statement bodies bypass the bounded refusal

The new class-comprehension check is reached only when `expression()` visits the comprehension. A `match` statement can prevent that visit:

    import importlib, sys
    loader = sys.modules["importlib"]
    class Holder:
        loader = 1
        match 1:
            case 1:
                saved = [loader for _ in (0,)]
    Holder.saved[0].import_module("external_plugin")

The relevant control flow is:

1. `calls()` at T:1028–1034 deliberately stops before nested `ast.stmt` children.
2. `walk()` has no `ast.Match` branch and no final refusal for unhandled statement kinds.
3. The case-body assignment is therefore not passed to `expression()`, so T:773 never sees its comprehension.
4. The class symbol table identifies `saved` as assigned, but T:1157 checks an absent analysis binding as `UNKNOWN`.
5. Runtime evaluates the comprehension using the outer `loader`; subsequent class-field access remains unknown to the analyzer.

The same omission needs no class or opaque module to lose an input:

    match 1:
        case 1:
            import external_plugin

[INFERENCE] With `external_plugin` installed on an external import path, these forms execute an import that discovery neither records nor refuses. The counterexamples were derived statically and were not executed.

This is a broader statement-coverage defect, separate from the corrected expression-level CA-03 and classification-level CA-08 mechanisms. No `match` regression was found in TT. It requires no concurrent mutation and does not depend on the four generic carried findings.

## Lens 2 - Clause-to-line discharge

Statuses concern this delta and its immediate dependencies.

| Clause | Expected discharge | Actual code line | Status |
|---|---|---|---|
| D I11, `docs/intent.md:25`: unsupported closure prevents PASS | Every applicable import is bound or the unsupported form refuses | T:1042–1204 silently omits an unhandled `match` body | gap: CA-09 |
| V4:229: unmodeled forms refuse | Unsupported class comprehensions reject before evidence dispatch | T:773 | discharged for visited expressions; partial overall because CA-09 can bypass visitation |
| V4:235,251: unknown nonstdlib dependencies fail closed | Static imports inside executable bodies must be analyzed or refused | T:1028–1034,1042–1204 | gap: CA-09 |
| V4:229: selector escape refusal and propagation agree | Known and opaque selectors retain dangerous classification at joins | T:697–699,1035–1041,1186 | discharged for the reported CA-08 mismatch |
| V4:243: exact probes and endpoint revalidation | Preserve recorded discovery identities and reject drift | No change to hashing/revalidation in this scoped correction | unchanged; does not detect undiscovered inputs |
| V4:163–165: operational/cache assumptions remain explicit | Stable bytes must not be treated as proof of complete closure | T:647,986,2407; CR:186 | explicit residual limits retained |
| D I12, `docs/intent.md:32` | Preserve command/cwd, bounds, slots and observations | Correction is confined to discovery classification/refusal | partial; execution/store semantics not re-audited |
| D I13/I14, `docs/intent.md:33–34` | No activation or expanded authority from metadata acceptance | CR:184–186 retains limited claims | partial; no activation discharge |
| V4 S1/S2 | Complete membership and immutable execution ownership | No new enforcement in this delta | partial; unchanged outside this slice |
| V4 B1/B2 | Complete admissible provenance; no stale/unrun promotion | Python closure analysis remains incomplete | partial |
| V4 T1/T2 | Failure/ownership discipline and drift rejection | No native-ownership correction in this delta | partial; prior ownership failure remains separate |
| Ledger C-01 through C-15 | Preserve incomplete bounded/projection conjunctions | No refinement or historical-chain provenance artifact added | partial; all remain INCOMPLETE |
| Ledger TA-07/TA-08 | Preserve host-evidence and operator-honesty limits | Capture contains unsigned local metadata | partial; no independent operator attestation |
| Ledger TA-01–TA-06, TA-09–TA-17 | Preserve external platform, custody, chain, release and time premises | No discharge in this delta | partial; unchanged |

## Lens 3 - Deferred cannot silently succeed

| Branch | Reachable from | Behavior | Status |
|---|---|---|---|
| Visited class comprehension | Class assignment/default/expression analysis | Throws at T:773 | Explicit refusal; reported CA-03 expression addressed |
| Unhandled `ast.Match` | Module, class or function statement analysis | Falls through without visiting case-body statements or rejecting the construct | gap: CA-09 |
| Known-selector branch/exception join | Supported control-flow analysis | `retain_selectors` uses the same predicate as refusal | Reported CA-08 mechanism addressed |
| Ordinary module/function comprehension | Existing expression analysis | Continues under existing analysis; no class-context rejection | Deliberately admitted; not a general soundness claim |
| Literal-key registry snapshot and restoration | Supported collector source | Opaque representation preserved | Existing admitted form retained |
| Root-by-name/imported helper shortcuts | Python loader discovery | Incomplete target analysis still succeeds | Carried CA-01/02 |
| Transitive stdlib shortcut | Import resolution | Returns without transitive scanning | Carried CA-04 |
| Darwin ordinary-tree shortcut | Non-adapter tool capture | Tree hashing proceeds without native-child linkage closure | Carried CA-06 |

The new class-comprehension shortcut is correctly fail-closed when reached. CA-09 concerns the statement dispatcher’s failure to reach or reject executable subtrees.

## Lens 4 - Who controls

| Field | Supplier | Validation | Gap |
|---|---|---|---|
| Python statement kind and nested bodies | Project or installed Python source | Explicit branches in `walk` | CA-09: unsupported executable statement forms lack a fail-closed boundary |
| Runtime-selector classification | Analyzer-derived | T:697 combines opaque and known selector classes | Shared classification now consistent at the reviewed joins |
| Class-scope marker | Analyzer | T:1152–1153 establishes `CLASS_GLOBALS`; T:773 checks it | Effective for visited comprehensions |
| Class-written/imported symbols | Python source, classified by `symtable` | T:1154–1157 | Identifies written names, but cannot recover values from unvisited bodies |
| Registry snapshot keys and values | Python source and module registry | Literal-key construction and opaque-value rules | No hardcoded module-name exception introduced |
| Recorded tool identity and probe output | Local producer/runtime | Existing content and exact stream hashes | Metadata acceptance still depends on complete discovery and operator honesty |
| Operational/cache/store premises | Reviewed policy/operator | Explicit declarations | Successful capture does not prove these premises or input completeness |

## Lens 5 - Field-name fidelity

| Field | Implied semantic | Actual value | Status |
|---|---|---|---|
| `runtime_selector()` | Opaque or known runtime selector | Union predicate at T:697 | faithful |
| `retain_selectors()` | Preserve tracked selectors across a supported join | Applies `runtime_selector` at T:1035–1037 | faithful for the reviewed classification fix |
| `CLASS_GLOBALS` | Enclosing lexical scope for class-related analysis | Existing enclosing-scope reference | Internal analysis field; no serialized-field drift |
| Class symbol inventory | Names assigned/imported in the class | Python symbol-table result | faithful; incomplete body visitation is CA-09 |
| Capture tool IDs/digests | Named captured metadata identities | Contains `python-runtime`, `mobile-node-toolchain`, and dependencies | faithful; no proof-result semantics |

No separate field-name finding was established.

## Lens 6 - Deferral justification audit

| Deferred finding | Justification claims | Claim audit | Verdict |
|---|---|---|---|
| CA-03 bounded correction | Four class-comprehension kinds refuse; no new comprehension interpreter | T:773 and TT:428–443 support the direct forms | Reported mechanism addressed. Blanket refusal coverage is limited by new CA-09 |
| CA-08 correction | Propagation and refusal use one runtime-selector predicate | T:697–699,1035–1041,1186; TT:453–471 | Closed for the reported classification mismatch |
| Unsupported-form posture | Unmodeled executable forms refuse | `walk` lacks a final unsupported-statement rejection; `match` bodies are skipped | Contradicted by CA-09 |
| Module/function comprehension preservation | Existing ordinary comprehensions remain admitted | Class-specific guard and TT:444–451 | Supported for tested examples; no general interpreter qualification |
| Base CA-16/17 | Root-value/imported-helper analysis remains incomplete | T:1012–1025,1074–1075 | OPEN; carried |
| Transitive Base CA-21 | Transitive split-stdlib paths remain open | T:647–648 | OPEN; carried |
| Generic Base CA-24 | Darwin ordinary-tree linkage remains open | T:2407 onward | OPEN; carried |
| Reported 48-method suite and actual capture | Regression and metadata acceptance only | TT contains the named vectors; Capture contains named identities; CR preserves limits | Supported as limited evidence; does not decide the new counterexamples |

### Nonmutation premise

No new relaxation of the nonmutation premise was identified in the predicate/refusal changes. CA-09 operates on stable source and installed files. Endpoint equality cannot repair an import omitted from discovery.

The four carried generic findings likewise retain fresh-provenance implications. Disabling reuse does not discharge them.

---

## Finding list (consolidated)

CA-03 and CA-08’s reported mechanisms are addressed. CA-05 and CA-07 retain their prior scoped closures. CA-09 is a newly identified statement-dispatch defect, not a claim that this commit introduced the omission.

| ID | Lens | Severity | Surface | Intent ref | Code ref | Summary | Fix |
|---|---|---|---|---|---|---|---|
| CA-01 | commitment-coverage | Major | Python helper root | D I11; V4:229,235,249,251 | T:1012–1022 | OPEN, carried Base CA-16. Runtime root values are replaced with the project root based on identifier spelling. | Establish the argument value or refuse the invocation; retain fresh-provenance limits. |
| CA-02 | commitment-coverage | Major | Imported loader helpers | D I11; V4:229,235,249,251 | T:1012–1025,1074–1075 | OPEN, carried Base CA-17. Defining-file specialization does not establish targets selected by imported-helper callers. | Preserve helper identity and validate arguments, or refuse unsupported imported-helper use. |
| CA-09 | deferred-cannot-silently-succeed | Major | Unhandled Python statement bodies | D I11; V4:229,235,251 | T:1028–1034,1042–1204,1154–1157; TT:428–471 | New. `ast.Match` has no dispatch branch or refusal; nested case-body statements are skipped. This admits an ordinary external import without recording it and also bypasses the class-comprehension rejection. Static counterexamples; not executed. | Make statement admission explicit: reject unmodeled executable statement kinds, including `Match`, instead of falling through. Retain only intentionally harmless statement forms. Add direct-import and nested-class-comprehension refusal regressions. |
| CA-04 | commitment-coverage | Minor | Transitive split-stdlib closure | D I11; V4:235,249,251 | T:647–648 | OPEN, carried transitive Base CA-21. Transitive standard-library paths remain unscanned. | Bind applicable split distributions or refuse unsupported paths. |
| CA-06 | clause-to-line | Minor | Darwin non-adapter tree linkage | D I11; V4:245,249,251 | T:2407 onward | OPEN, carried generic Base CA-24. Ordinary Darwin trees omit native children’s external linkage. Exposure in D’s exact installation is not established here. | Discover native dependencies in actual launch contexts or refuse unsupported trees. |

## Summary

- Total active findings: 5, comprising 4 explicitly carried findings and 1 newly identified statement-dispatch defect.
- By severity: Critical=0 Major=3 Minor=2 Informational=0.
- By lens: commitment-coverage=3 clause-to-line=1 deferred-cannot-silently-succeed=1 who-controls=0 field-name=0 deferral-justification=0.
- Delta closure: the direct class-comprehension counterexamples now refuse, and the known-selector join mismatch is corrected. Unsupported statement bodies still bypass those safeguards through CA-09.
- Recommended next step:
  1. Add a fail-closed statement-admission boundary rather than another expression-specific exception.
  2. Have the parent exercise the direct `match` import and nested class-comprehension counterexamples, retaining the existing ordinary-comprehension and registry-restoration controls.
  3. Keep Base CA-16/17, transitive CA-21 and generic CA-24 OPEN, including their fresh-provenance limits.

No general provenance, generic reuse, canonical collection, or activation qualification is established.