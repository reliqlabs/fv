# Code-adversarial review: Dossier Python class-selector correction - 2026-10-16

- Operator: fv-code-adversary via OMP task (NOT the parent orchestrator, FixHybridResiduals, HybridBase, or HybridProof)
- Code commit reviewed: `9852d48`, delta against previously reviewed `e5fec11`
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
| C | `F/tools/evidence-v4/evidence-v4-toolchain-common.ts` |
| TT | `F/tests/r38_evidence_v4_toolchain_review.py` |
| V4 | `F/docs/execution-evidence-v4.md` |
| CR | `F/.fv/changes/2026-10-14-execution-evidence-v4.md` |
| Capture | `/var/folders/ph/n581g1fj3tnbq8n74hp05klc0000gn/T/fv-hybrid-runtime-selection-2zNypR/identities.json` |

This review addresses CA-03’s class-publication correction, its lexical-scope extensions, and the associated regressions. Prior reports remain immutable. Existing finding IDs retain their meanings; CA-08 identifies a separate branch-propagation defect.

No commands, tests, builds, formatters, edits, or process changes were performed. Commit attribution is caller-provided; working-tree equality to `9852d48` was not independently established.

The parent reports four reproduced class-publication failures, followed by three lexical-scope escapes and one benign-class false refusal, then 46 passing toolchain methods and successful actual Python/Node capture. Those observations are accepted without rerunning them.

The retained Capture contains `python-runtime`, `mobile-node-toolchain`, and their producer/dependency identities. It establishes retained metadata, not execution of the new counterexamples or a complete collection verdict.

The canonical ledger still records Gate B as STALE, all 15 composition candidates as INCOMPLETE, and the fresh v4 attempt as ERROR with two ERROR physical slots and 80 MISSING slots. This correction does not clear those states.

Important uncovered classes remain concurrency/crash recovery, process containment, resource exhaustion, upstream-cache poisoning, supply-chain authenticity, and proof/model-to-implementation refinement.

## Delta disposition

| Surface | Disposition | Evidence |
|---|---|---|
| Same-name opaque/registry/snapshot class assignment | Reported mechanism addressed | T:1151–1154 uses class-written/imported symbols rather than comparing abstract object identity. TT:394–397 contains direct, registry, snapshot, and conditional opaque cases. |
| Methods, nested classes, and lambdas masked by a class-local binding | Reported mechanisms addressed | T:774–778 and T:1145–1150 use the enclosing lexical scope; TT:399–401 covers the reported cases. |
| Benign inherited outer bindings and method/lambda parameter shadowing | Reported false refusal addressed | T:775–776 shadows lambda parameters; T:1146 replaces class method bindings; T:1153–1154 checks written/imported names. TT:411–425 retains the positive case. |
| Class comprehension lexical scope | Incomplete | Comprehensions still use the class-local expression fallback. An outer opaque module masked by a class-local scalar can escape through a comprehension. CA-03 remains OPEN. |
| Conditional known-selector class assignment | Gap | `refuse_opaque` covers known runtime selectors, but `retain_opaque` does not preserve them across branches. CA-08. |
| Prior CA-05 and CA-07 | Remain closed for their reviewed mechanisms | Preferred-runtime wrapper/options checks remain at T:1740–1787; selected store-root closure remains at T:1801–1809 and C:625–672. |
| Four generic carried boundaries | Remain OPEN | Base CA-16/17, transitive CA-21 and generic CA-24 are not repaired by this delta. |

---

## Lens 1 - Commitment coverage

| Commitment | Attacker DoFs | Bound by | Gap |
|---|---|---|---|
| Python class-exported opaque values | Explicit field assignment under an existing outer name | Class symbol inventory and final selector check, T:1151–1154 | Original same-value skip removed |
| Lexically captured method/lambda values | Outer selector masked by a same-named class field | T:774–778,1145–1150 | Reported method/nested-class/lambda mechanisms addressed |
| Comprehension-produced class fields | Outer opaque value, class-local shadow, comprehension body | Generic fallback evaluates children with the current `values`, T:945–948 | CA-03: comprehension body uses the wrong lexical namespace |
| Known runtime selectors assigned conditionally | Conditional assignment/import of `importlib`, `runpy`, or tracked import functions | Shared refusal predicate at T:697–698; branch retention at T:1032–1038 | CA-08: branch retention drops known selectors |
| Literal-key registry snapshots | Literal key set, saved modules, restoration | T:780–784; opaque item/access handling; registry-only opaque stores | Existing direct snapshot protections retained; class comprehensions can transport a masked outer snapshot through CA-03 |
| Tool content and endpoint selection | Discovered bytes and probe identities | Retained manifest membership checks and revalidation at T:2510–2534,2678–2702,2720 onward | No new hashing/membership relaxation identified; omitted dependencies remain unbound |
| Root-by-name helper targets | Runtime root argument | T:1009–1019 | Carried CA-01 |
| Imported helper targets | Calls outside defining-file specialization | T:1009–1022,1070–1071 | Carried CA-02 |
| Transitive split-stdlib inputs | External extension selected indirectly | T:647–648 | Carried CA-04 |

### CA-03 residual: class comprehensions still resolve against class locals

Concrete source:

    import importlib, sys
    loader = sys.modules["importlib"]
    class Holder:
        loader = 1
        saved = [loader for _ in (0,)]
    Holder.saved[0].import_module("external_plugin")

Python comprehension bodies do not resolve free names through the surrounding class namespace. The comprehension’s `loader` refers to the outer module binding, so `saved[0]` is the imported module.

The analyzer instead evaluates the comprehension through T:945–948 using the class-local `values`, where `loader` is `1`. It returns `UNKNOWN` for the comprehension. The symbol-table check correctly identifies `saved` as assigned, but T:1154 sees only `UNKNOWN` and accepts it. Later `Holder.saved[0]` likewise remains unknown.

[INFERENCE] With `external_plugin` present on an external import path, runtime imports it without discovery recording that dependency or refusing the source. This was derived statically, not executed.

The special handling at T:780–784 concerns only the restricted registry-snapshot `DictComp`; it does not establish general comprehension scope. TT:399–401 covers methods, nested classes and lambdas, but no corresponding class-comprehension case.

### CA-08: known runtime selectors disappear during branch merging

Concrete source:

    import importlib, sys
    class Holder:
        if sys.version_info.major >= 3:
            loader = importlib
    Holder.loader.import_module("external_plugin")

The condition is true on the selected Python 3 runtime. The analyzer treats `sys.version_info` as unknown through T:713 and therefore explores the branch using `walk_branch`.

Inside that branch, `loader` has the tracked `IMPORTLIB` value. However, `retain_opaque` at T:1032–1034 retains only values accepted by `opaque()`. `IMPORTLIB` is in `RUNTIME_SELECTORS`, not `OPAQUE_SELECTORS`. The branch-local binding is discarded.

The class symbol table identifies `loader` as assigned, but T:1154 receives `UNKNOWN`. The newly shared refusal guard never receives the selector that it was extended to reject.

[INFERENCE] The runtime import remains unrecorded under the same external-path setup. This counterexample was derived statically and was not executed.

TT:397 covers conditional assignment of an opaque value, and TT:398 covers unconditional assignment of a known selector. Their combination is missing. The same retention helper is used by other branch/exception paths, so the fix should address the shared merge rule rather than this class spelling.

## Lens 2 - Clause-to-line discharge

Statuses apply to this delta and its immediate dependencies.

| Clause | Expected discharge | Actual code line | Status |
|---|---|---|---|
| D I11, `docs/intent.md:25`: unsupported closure prevents PASS | Class-exported loaders must be bound or refused | T:945–948,1032–1038,1151–1154 | gap: CA-03 and CA-08 |
| V4:229,235,251: unsupported Python loaders and unknown nonstdlib dependencies refuse | Preserve dangerous selector identity until discharge/refusal | T:696–698,945–948,1032–1038 | partial |
| V4:229: class publication must not hide a tracked loader | Identify actual written/imported class names | T:1151–1154 | discharged for direct same-name publication |
| V4:229,235: runtime and analyzer select the same free binding | Methods, lambdas and comprehensions use Python lexical semantics | T:774–778,1145–1150; fallback T:945–948 | partial: comprehensions remain CA-03 |
| V4:243: retain probes and revalidate discovered identities | Exact content/selection drift rejection | T:2720 onward | unchanged; does not repair omitted inputs |
| V4:163–165: operational/cache premises remain explicit | No concurrent-mutation assumption must not substitute for closure | Residual comments T:647,983,2404; CR:184 | accurate residual disclosure; no new premise established |
| D I12, `docs/intent.md:32`: preserve commands, bounds, slots and observations | Discovery changes must not change evidence recipes or assurance classes | Reviewed correction is within Python discovery | partial; scheduling, ownership and observations not re-audited |
| D I13/I14, `docs/intent.md:33–34` | No activation or expanded authority from metadata acceptance | CR:180–184 retains limited claims | partial; no activation discharge |
| V4 S1/S2 | Complete slot membership and immutable ownership | No new enforcement in this correction | partial; unchanged outside this slice |
| V4 B1/B2 | Complete admissible provenance; no stale/unrun promotion | Selector analysis plus existing membership gates | partial; identified omissions remain |
| V4 T1/T2 | Failure/ownership discipline and drift rejection | Existing revalidation only | partial; native-ownership failure not repaired here |
| Ledger C-01 through C-15 | Preserve incomplete bounded/projection conjunctions | No model/code or historical-chain bridge in this delta | partial; all remain INCOMPLETE |
| Ledger TA-07/TA-08 | Preserve host-evidence and operator-honesty limits | Capture contains unsigned local metadata and hashes | partial; no independent operator attestation |
| Ledger TA-01–TA-06, TA-09–TA-17 | Preserve platform, custody, chain, release and time premises | No discharge in reviewed code | partial; unchanged |

## Lens 3 - Deferred cannot silently succeed

| Branch | Reachable from | Behavior | Status |
|---|---|---|---|
| Direct same-name class publication | Class body analysis | Symbol-table-selected field is checked even if equal to an outer abstract object | Explicit refusal for tracked selectors |
| Class comprehension fallback | Class assignment expression | Evaluates free names against class locals and returns unknown | gap: CA-03 |
| Known-selector branch merge | Conditional/exceptional class analysis | Discards tracked runtime-selector binding unless also classified opaque | gap: CA-08 |
| Method/lambda masked outer selector | Class function definitions | Uses enclosing lexical scope and refuses selector return/escape | Reported mechanism addressed |
| Unsupported preferred Node wrapper | Selected runtime discovery | Exact wrapper grammar rejects before selected-runtime probe | Prior CA-05 remains closed |
| Whole-store/escaping pnpm target | Linked-root discovery | Explicit refusal in C:633–634,669–670 | Prior CA-07 remains closed |
| Root-by-name/imported helper shortcuts | Python loader discovery | Still admits incomplete target analysis | Carried CA-01/02 |
| Transitive stdlib shortcut | Import resolution | Returns without transitive scanning | Carried CA-04 |
| Darwin ordinary-tree shortcut | Non-adapter tree capture | Hashes tree without native-child linkage discovery | Carried CA-06 |

No additional placeholder-success branch is asserted. The two new counterexamples are ordinary analysis paths, not TODO markers.

## Lens 4 - Who controls

| Field | Supplier | Validation | Gap |
|---|---|---|---|
| Class-written/imported names | Python source, classified by Python `symtable` | T:1151–1154 | Corrects prior object-equality test; value tracking feeding it remains incomplete |
| `CLASS_GLOBALS` analysis link | Analyzer | T:774,1145,1149–1150 | Used for lambdas/methods/nested classes; not applied to general comprehensions |
| Opaque module/snapshot values | Runtime registry, abstracted by analyzer | `opaque()` and direct escape guards | CA-03 can resolve the wrong binding before those guards |
| Known import selectors | Python imports, mapped to analyzer sentinels | `RUNTIME_SELECTORS` and shared refusal at T:690,697–698 | CA-08: branch merging uses a narrower classification |
| Lambda parameters | Python source | Parameters replaced with unknown values at T:775–776 | Reported benign shadowing handled |
| Discovery output and tool identities | Approved local runtime and producer | Retained hashes, exact selection comparison, content membership | Local metadata remains dependent on discovery completeness and operator honesty |
| Trust assumptions | Reviewed policy/operator | Explicit operational/cache/store declarations | Successful capture does not prove these premises or complete closure |

## Lens 5 - Field-name fidelity

| Field | Implied semantic | Actual value | Status |
|---|---|---|---|
| `CLASS_GLOBALS` | Enclosing lexical namespace used when class locals are not visible | Reference established at T:1149–1150 and used for methods/lambdas | Internal field; incomplete use is CA-03, not a serialized-field mismatch |
| Class `symtable` symbols | Names assigned/imported in the class namespace | Python symbol-table output at T:1151–1154 | Faithful classification |
| `opaque()` | Opaque registry/module/snapshot classifications | T:696 | Faithful name; branch merging needs the wider selector-preservation rule |
| `ToolIdentity.digest` and discovery stream hashes | Recorded tool content and exact probe output | Existing producer encoding and hashing | No field-name drift introduced |
| Capture identity IDs | Named metadata captures | Includes `python-runtime` and `mobile-node-toolchain` | Faithful; neither ID denotes a proof result |

No separate field-name finding was established.

## Lens 6 - Deferral justification audit

| Deferred finding | Justification claims | Claim audit | Verdict |
|---|---|---|---|
| CA-03 direct class-publication correction | Written/imported names replace abstract object-equality comparison | T:1151–1154 supports the claim; TT:394–397 covers original forms | Original mechanism addressed |
| CA-03 lexical extension | Methods, nested classes and lambdas use enclosing scope | T:774–778,1145–1150 supports those named forms | Supported narrowly; class comprehensions remain unmodeled and admitted |
| Shared opaque/known-selector refusal | Both classifications are rejected at escape boundaries | `refuse_opaque` does so at T:697–698; `retain_opaque` loses known selectors before the boundary | Incomplete composition; CA-08 |
| Benign-class compatibility | Unwritten inherited outer bindings and parameter shadowing no longer cause the reported refusal | Written-name checks and explicit parameter shadowing; TT:411–425 | Supported for the named positive cases |
| Base CA-16/17 | Root-value and imported-helper analysis remain incomplete | T:1009–1022,1070–1071 | OPEN; carried |
| Transitive Base CA-21 | Direct split imports refuse; transitive paths remain open | T:647–648 | OPEN; carried |
| Generic Base CA-24 | Darwin tree linkage remains open | T:2404–2411 | OPEN; carried |
| CA-05/07 prior closures | Preferred-runtime options and selected-store capture remain enforced | T:1740–1809; C:625–672 | Prior mechanism closures retained |
| Passing regressions and actual metadata capture | Limited regression/acceptance evidence, not qualification | TT covers the listed vectors; Capture retains named identities; CR retains qualification limits | Accurate limited evidence claim |

The new counterexamples do not involve concurrent mutation. No widening of the existing nonmutation premise was identified in this correction, but that premise cannot excuse either omission.

---

## Finding list (consolidated)

CA-05 and CA-07 remain closed for their previously reviewed mechanisms. CA-08 is a new finding; CA-03 remains an incomplete correction.

| ID | Lens | Severity | Surface | Intent ref | Code ref | Summary | Fix |
|---|---|---|---|---|---|---|---|
| CA-01 | commitment-coverage | Major | Python helper root | D I11; V4:229,235,249,251 | T:1009–1019 | OPEN, carried Base CA-16. Runtime root values are replaced with the project root based on identifier spelling. | Establish the argument value or refuse the invocation; preserve fresh-provenance limits. |
| CA-02 | commitment-coverage | Major | Imported loader helpers | D I11; V4:229,235,249,251 | T:1009–1022,1070–1071 | OPEN, carried Base CA-17. Defining-file specialization does not establish targets selected by imported-helper callers. | Preserve helper identity and validate arguments, or refuse unsupported imported-helper use. |
| CA-03 | commitment-coverage | Minor | Class-comprehension selector escape | D I11; V4:229,235,251 | T:771–784,945–948,1149–1154; TT:394–401 | Direct class-publication and named lexical cases are fixed, but a class comprehension evaluates an outer opaque name against the class-local shadow. Its result becomes unknown and can expose an unrecorded loader. Static counterexample; not executed. | Model comprehension lexical scopes, including their distinct outermost-iterable semantics, or refuse unmodeled comprehension forms. Add the masked-outer-loader class-comprehension regression. |
| CA-04 | commitment-coverage | Minor | Transitive split-stdlib closure | D I11; V4:235,249,251 | T:647–648 | OPEN, carried transitive Base CA-21. Transitive standard-library paths remain unscanned. | Bind applicable split distributions or refuse unsupported paths. |
| CA-08 | commitment-coverage | Minor | Known-selector branch propagation | D I11; V4:229,235,251 | T:690,696–698,1032–1038,1133–1139,1151–1154; TT:397–398 | New. The shared escape guard rejects known runtime selectors, but branch merging preserves only opaque values. Conditional `loader = importlib` is discarded, allowing an unchecked class export and subsequent import. Static counterexample; not executed. | Use one consistent dangerous-selector classification for propagation and refusal. Retain or conservatively reject known selectors across all branch/exception merges. Add conditional known-selector class and non-class regressions. |
| CA-06 | clause-to-line | Minor | Darwin non-adapter tree linkage | D I11; V4:245,249,251 | T:2404–2411 | OPEN, carried generic Base CA-24. Ordinary Darwin trees omit native children’s external linkage. Actual exposure in D’s installed tree is not established here. | Discover native dependencies in actual launch contexts or refuse unsupported trees. |

## Summary

- Total active findings: 6, comprising 4 generic carried findings, 1 incomplete correction with a new residual counterexample, and 1 new branch-propagation finding.
- By severity: Critical=0 Major=2 Minor=4 Informational=0.
- By lens: commitment-coverage=5 clause-to-line=1 deferred-cannot-silently-succeed=0 who-controls=0 field-name=0 deferral-justification=0.
- Closure determination: the reported direct class-publication, method, nested-class and lambda cases are addressed. CA-03 cannot be closed because class comprehensions remain an escape. CA-08 separately identifies inconsistent propagation of known runtime selectors.
- Recommended next step:
  1. Correct or refuse the unmodeled comprehension scope.
  2. Unify selector preservation across branch/exception merges with the shared escape classification.
  3. Have the parent exercise both supplied counterexamples and retain the existing benign-class and registry-restoration regressions.
  4. Keep Base CA-16/17, transitive CA-21 and generic CA-24 OPEN, including their fresh-provenance implications.

The retained capture and reported passing suite do not qualify generic reuse, canonical collection, or activation.