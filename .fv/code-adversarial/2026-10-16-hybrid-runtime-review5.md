# Code-adversarial review: Dossier Python statement-admission correction - 2026-10-16

- Operator: fv-code-adversary via OMP task (NOT the parent orchestrator, FixHybridResiduals, HybridBase, or HybridProof)
- Code commit reviewed: `7c3891c`, delta against previously reviewed `c149b15`
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
| Capture | `/var/folders/ph/n581g1fj3tnbq8n74hp05klc0000gn/T/fv-hybrid-runtime-selection-qKMxp3/identities.json` |

This is a bounded review of CA-09’s statement-dispatch correction, its immediate expression-handling dependencies, tests, and change record. Earlier reports remain immutable.

No commands, tests, builds, formatters, edits, or process changes were performed. The commit ID and signed-commit status are caller-provided; working-tree/commit equality and the signature were not independently checked.

The parent reports that all 49 toolchain methods passed and actual Dossier Python/Node metadata capture succeeded. These observations are accepted without rerunning them.

The retained Capture contains:

- `python-runtime`: 3,214 manifest entries and 91 discovery identities.
- `mobile-node-toolchain`: 10,213 manifest entries and 223 discovery identities.
- The reserved producer identity and declared Node dependencies.

These are retained metadata identities. They do not establish a complete execution verdict, generic reuse qualification, or activation.

The canonical ledger remains explicit: Gate B is STALE, all 15 composition candidates are INCOMPLETE, and the fresh v4 attempt returned ERROR with two ERROR physical slots and 80 MISSING slots. This correction does not clear that failed collection or its ownership state.

Important uncovered classes remain process containment, concurrency/crash recovery, resource exhaustion, upstream-cache poisoning, supply-chain authenticity, and proof/model-to-implementation refinement.

## Delta disposition

CA-09 is closed for the reported mechanism.

At T:1206–1207, a statement that has not matched an implemented handler now raises `unsupported Python statement`, except for the explicit bodyless forms `Pass`, `Break`, `Continue`, `Global`, and `Nonlocal`. `Match`, `TryStar`, and `TypeAlias` therefore cannot silently skip their executable contents.

`Assert` and `Raise` receive explicit expression handling at T:1204–1205. Their expressions pass through both `expression()` and the shared selector-escape check.

No new defect was established in this bounded delta. This does not establish correctness of the complete Python abstract interpreter or of all previously admitted statement semantics.

| Prior finding or boundary | Disposition |
|---|---|
| CA-09: unhandled statement bodies | Closed for the reported omission and supplied `match` counterexamples |
| CA-03: reported class-publication/comprehension mechanisms | Earlier scoped closures retained; unsupported class comprehensions still refuse |
| CA-08: known-selector branch propagation | Earlier scoped closure retained |
| CA-05: preferred Node runtime options | Earlier scoped closure retained; not re-audited in this Python-only delta |
| CA-07: whole pnpm-store enumeration | Earlier scoped closure retained; not re-audited in this Python-only delta |
| Base CA-16/17, transitive CA-21, generic CA-24 | OPEN, explicitly carried below |

---

## Lens 1 - Commitment coverage

| Commitment | Attacker DoFs | Bound by | Gap |
|---|---|---|---|
| Imports or loaders inside previously unhandled statement bodies | Statement kind and nested executable contents | T:1206–1207 refuses any statement lacking an implemented handler or explicit bodyless admission | CA-09 mechanism closed |
| `assert` and `raise` expressions | Test, message, exception and cause expressions containing selectors or calls | T:1204–1205 invokes `expression_children`, `expression`, and `refuse_opaque`; helper at T:764–767 and predicate at T:697–699 | No new omission established in this delta |
| Class-comprehension selector exposure | Comprehension nested in an unsupported `match` body | Unsupported statement now refuses before acceptance; direct visited class comprehensions still refuse at T:773 | Reported bypass closed |
| Known and opaque selector identity | Selector transported through supported branches or exceptions | Shared predicate at T:697; retention at T:1035–1041 and T:1186 | Earlier CA-08 correction retained |
| Root-by-name helper targets | Runtime value of a helper’s root argument | T:1020–1022 substitutes the project root based on identifier spelling | Carried CA-01 |
| Imported helper targets | Caller-selected targets outside defining-file specialization | T:1012–1025,1074–1075 | Carried CA-02 |
| Transitive split-stdlib inputs | External extension selected indirectly through stdlib | T:647–648 | Carried CA-04 |

No hashing, manifest-membership, or alias-acceptance relaxation is part of the inspected correction. The change adds refusal and expression inspection; it does not supply missing dependencies for the carried findings.

## Lens 2 - Clause-to-line discharge

Statuses apply to the bounded correction and its immediate dependencies.

| Clause | Expected discharge | Actual code line | Status |
|---|---|---|---|
| D I11, `docs/intent.md:25`: unsupported closure prevents PASS | Unhandled executable statement forms must not silently omit inputs | T:1206–1207 | discharged for CA-09 |
| V4:229: unmodeled forms refuse | `Match`, exception-group statements and type aliases cannot pass an unhandled dispatcher branch | T:1206–1207 | discharged for inspected statement kinds |
| V4:235,251: unknown nonstdlib dependencies fail closed | Nested imports must be analyzed or the containing unsupported form must reject | Existing handlers plus the final refusal at T:1206–1207 | discharged for the reported skipped-body mechanism; partial for the complete interpreter |
| V4:229: selector escapes refuse | Inspect admitted `Assert`/`Raise` expression fields | T:1204–1205; T:697–699 | discharged within the added handlers |
| V4:243: retain exact probes and reject discovered drift | No weakening of discovery identity or revalidation | No change to those mechanisms in this bounded correction | unchanged; omitted inputs remain a separate issue |
| V4:163–165: operational/cache premises remain explicit | Stable endpoints must not substitute for complete closure or fresh compilation | Residual comments at T:647,986,2411; CR:188 | explicit limits retained |
| D I12, `docs/intent.md:32` | Preserve execution argv/cwd, bounds, slots and observations | Correction is confined to discovery admission | partial; execution/store semantics not re-audited |
| D I13/I14, `docs/intent.md:33–34` | No activation or expanded authority from metadata acceptance | CR:186–188 retains qualification limits | partial; no activation discharge |
| V4 S1/S2 | Complete slot membership and immutable execution ownership | No new enforcement in this delta | partial; unchanged outside this slice |
| V4 B1/B2 | Complete admissible provenance; no stale/unrun promotion | CA-09 refuses; other input-closure gaps remain | partial |
| V4 T1/T2 | Failure/ownership discipline and endpoint drift rejection | No native-ownership or recovery correction in this delta | partial; failed collection remains separate |
| Ledger C-01 through C-15 | Preserve bounded/projection limitations and incomplete conjunctions | No refinement or historical-chain provenance artifact added | partial; all remain INCOMPLETE |
| Ledger TA-07/TA-08 | Preserve host-evidence and operator-honesty limits | Capture contains unsigned local metadata and probe identities | partial; no independent operator attestation |
| Ledger TA-01–TA-06, TA-09–TA-17 | Preserve external platform, custody, chain, release and time premises | No discharge in this delta | partial; unchanged |

## Lens 3 - Deferred cannot silently succeed

| Branch | Reachable from | Behavior | Status |
|---|---|---|---|
| Unhandled statement kind | Python module, class or deferred function analysis | Raises at T:1206–1207 | CA-09 closed |
| `Match` containing an ordinary external import | Statement dispatcher | Reaches unsupported-statement refusal | Explicit refusal |
| Class `Match` containing a comprehension | Class body analysis | Containing statement refuses; no silent unknown class field is accepted through this mechanism | Explicit refusal |
| `TryStar` exception-group body | Statement dispatcher | Not handled as ordinary `Try`; reaches final refusal | Explicit refusal |
| `TypeAlias` | Statement dispatcher on a supporting Python parser | Reaches final refusal | Explicit refusal |
| `Assert` / `Raise` | Supported statement analysis | Expressions analyzed and selector escapes checked | Explicit handling |
| `Pass`, `Break`, `Continue`, `Global`, `Nonlocal` | Final admission branch | Explicitly admitted as bodyless statements | No skipped nested body; full semantics are not newly verified |
| Direct class comprehension | Expression analysis | Raises at T:773 | Existing unsupported-form refusal retained |
| Root-by-name/imported helper shortcuts | Python loader discovery | Incomplete target analysis can still succeed | Carried CA-01/02 |
| Transitive stdlib shortcut | Import resolution | Returns without transitive scanning | Carried CA-04 |
| Darwin ordinary-tree shortcut | Non-adapter tool capture | Hashes tree without native-child linkage closure | Carried CA-06 |

The new final branch closes the specific silent-success path rather than adding individual exceptions for the counterexample spellings.

## Lens 4 - Who controls

| Field | Supplier | Validation | Gap |
|---|---|---|---|
| Statement kind and nested bodies | Project or installed Python source | Implemented handler or explicit final refusal | Reported CA-09 omission closed |
| `assert`/`raise` expression values | Python source | Expression analysis plus shared selector refusal | No new gap established in the added handlers |
| Bodyless statement kind | Python source | Exact five-kind admission at T:1206 | No executable child body is omitted by these nodes |
| Class namespace symbols | Python source, classified by `symtable` | Existing class written/imported-name checks at T:1154–1157 | No longer receives unknown values merely because a `match` body was silently skipped |
| Selector classifications | Analyzer-derived | Shared `runtime_selector` predicate | Earlier branch-propagation correction retained |
| Captured identities and probe hashes | Local producer/runtime | Existing content and selection binding | Does not independently establish complete discovery or operator honesty |
| Operational/cache/store premises | Reviewed policy/operator | Explicit declarations | Successful capture does not prove these premises |

## Lens 5 - Field-name fidelity

| Field | Implied semantic | Actual value | Status |
|---|---|---|---|
| Unsupported-statement diagnostic | The unhandled AST statement kind | `type(node).__name__` at T:1207 | faithful |
| `runtime_selector()` | Opaque or known runtime selector | Union predicate at T:697 | faithful |
| `retain_selectors()` | Preserve classified selectors across supported joins | Shared predicate at T:1035–1037 | faithful within the existing analysis |
| Capture tool IDs/digests | Named captured metadata identities | Includes `python-runtime`, `mobile-node-toolchain`, and dependencies | faithful; no proof-result semantics |
| Public JSON/storage fields introduced by this correction | New externally visible state | None introduced | No additional field surface to audit |

No field-name finding was established.

## Lens 6 - Deferral justification audit

| Deferred finding | Justification claims | Claim audit | Verdict |
|---|---|---|---|
| CA-09 correction | Unsupported statement forms refuse rather than falling through | T:1206–1207 supplies a general final refusal | Closed for the reported mechanism |
| Added `Assert`/`Raise` handling | Their expressions are checked | T:1204–1205 traverses expression children and applies selector refusal | Supported by code inspection |
| Supported ordinary control flow retained | Existing forms continue through their handlers; bodyless statements explicitly admitted | TT:487–497 supplies a positive control; existing dispatcher handlers remain | Supported for the named control |
| Earlier CA-03/CA-08 closures | Class comprehensions refuse; selector propagation uses the shared classification | T:773,697,1035–1041,1186 | Scoped closures retained |
| Base CA-16/17 | Root-value and imported-helper analysis remain incomplete | T:1012–1025,1074–1075 | OPEN; carried |
| Transitive Base CA-21 | Transitive split-stdlib paths remain open | T:647–648 | OPEN; carried |
| Generic Base CA-24 | Ordinary Darwin tree linkage remains open | T:2411 onward | OPEN; carried |
| Reported 49-method suite and actual metadata capture | Regression/metadata acceptance only | TT contains the named regression; Capture contains named identities; CR retains qualification limits | Accurate limited claim |

### Test and evidence limits

TT:473–485 covers ordinary `match` imports, nested class/`match` comprehensions, exception-group bodies, and type aliases. It asserts refusal, without requiring a particular diagnostic.

Consequently, on Python versions that cannot parse a supplied syntax form, that negative case may reject during parsing rather than exercise T:1207. Code inspection establishes the dispatcher’s refusal for parsed unsupported nodes; the reported aggregate test count alone does not distinguish those routes.

The positive control retains global/nonlocal declarations, assertions, loop control, ordinary exception handling and `pass`. It is acceptance coverage, not a proof of complete control-flow or namespace semantics.

### Nonmutation premise

No widening of the existing nonmutation premise was identified. This correction does not relax content checks or use stable endpoints to excuse unknown inputs.

The four carried findings retain their fresh-provenance implications. Stable execution and disabled reuse cannot compensate for undiscovered dependencies.

---

## Finding list (consolidated)

No new delta finding was established. CA-09 is closed for the reported statement-dispatch omission. All entries below are existing generic findings, carried without claiming this correction introduced them.

| ID | Lens | Severity | Surface | Intent ref | Code ref | Summary | Fix |
|---|---|---|---|---|---|---|---|
| CA-01 | commitment-coverage | Major | Python helper root | D I11; V4:229,235,249,251 | T:1012–1022 | OPEN, carried Base CA-16. Runtime root values are replaced with the project root based on identifier spelling. | Establish the argument value or refuse the invocation; retain fresh-provenance limits. |
| CA-02 | commitment-coverage | Major | Imported loader helpers | D I11; V4:229,235,249,251 | T:1012–1025,1074–1075 | OPEN, carried Base CA-17. Defining-file specialization does not establish targets selected by imported-helper callers. | Preserve helper identity and validate arguments, or refuse unsupported imported-helper use. |
| CA-04 | commitment-coverage | Minor | Transitive split-stdlib closure | D I11; V4:235,249,251 | T:647–648 | OPEN, carried transitive Base CA-21. Transitive standard-library paths remain unscanned. | Bind applicable split distributions or refuse unsupported paths. |
| CA-06 | clause-to-line | Minor | Darwin non-adapter tree linkage | D I11; V4:245,249,251 | T:2411 onward | OPEN, carried generic Base CA-24. Ordinary Darwin trees omit native children’s external linkage. Exposure in D’s exact installation is not established here. | Discover native dependencies in actual launch contexts or refuse unsupported trees. |

## Summary

- Total active findings: 4, all explicitly carried; new delta findings: 0.
- By severity: Critical=0 Major=2 Minor=2 Informational=0.
- By lens: commitment-coverage=3 clause-to-line=1 deferred-cannot-silently-succeed=0 who-controls=0 field-name=0 deferral-justification=0.
- Closure: CA-09’s unhandled-statement fallthrough is closed. Unsupported class comprehensions, `match`, exception-group statements and type aliases retain explicit refusal rather than receiving incomplete new interpretation.
- Recommended next step:
  1. Record CA-09’s scoped closure while preserving the previous reports.
  2. Keep Base CA-16/17, transitive CA-21 and generic CA-24 OPEN until separately reviewed corrections or installation-specific discharge evidence exist.
  3. Keep isolated metadata acceptance and regression results separate from the failed canonical collection and its ownership state.

No general provenance, generic reuse, canonical collection, or activation qualification is established.