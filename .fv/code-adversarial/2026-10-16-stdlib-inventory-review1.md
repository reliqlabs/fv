# Code-adversarial review: dossier / external FV stdlib closure - 2026-10-16

- Operator: fv-code-adversary via OMP task (NOT CloseStdlibClosure worker or parent)
- Code commit reviewed: `62301ca`; declared base: `e341cce`
- Intent version reviewed: no version frontmatter present; canonical `docs/intent.md`, scoped to I11–I14
- Ledger version reviewed: no timestamp frontmatter present; header reports Updated `2026-10-16`
- Lens pack: execution-provenance and dependency-selection, applying the six required crypto/enclave-derived lenses
- Lenses applied: 1 through 6

The corrected project root is Dossier. Its `.fv/dispatch.json` resolves the canonical target to `docs/intent.md`. The implementation is the external FV producer in the separately assigned worktree.

Citation prefixes:

- `D`: `/Users/mv/Development/burnt/dossier-wt/evidence-perf`
- `F`: `/Users/mv/Development/reliq-fv-wt/evidence-stdlib-closure`
- `T`: `F/tools/evidence-v4/evidence-v4-toolchain.ts`
- `TT`: `F/tests/r38_evidence_v4_toolchain_review.py`
- `V4`: `F/docs/execution-evidence-v4.md`
- `CR`: `F/.fv/changes/2026-10-14-execution-evidence-v4.md`

Scope is the stdlib-inventory delta and its immediate dependency-selection consumers. This is not a review of Dossier’s protocol, all Python semantics, or all producer adapters. Important uncovered classes include concurrent mutation, filesystem race exploitation, resource exhaustion, upstream interpreter/package integrity, and build-cache correctness. D I11 expressly assumes no concurrent external mutation and trusted upstream cache behavior.

The author-reported nine targeted methods passing are accepted as observations, without rerunning them. The retained capture was inspected: it records `ok: true`, `fv-producer`, and a `python-runtime` identity containing 3,215 file entries and 91 discovery records. That establishes recorded metadata acceptance, not dependency completeness or proof validity.

---

## Lens 1 - Commitment coverage

| Commitment | Attacker DoFs | Bound by | Gap |
|---|---|---|---|
| Interpreter-declared stdlib selection | Search-path order, available names, selected origins, package locations, shadow files | T:646–677 enumerates `sys.stdlib_module_names`, retaining absent and selected entries; T:2237–2239 hashes probe streams; T:2800–2825 compares discovery and content identities during revalidation | Namespace selection is recorded. Import-time path effects are not faithfully carried from inventory scanning to subsequent application scanning: CA-03. |
| External source-module contents | Bytes and transitive imports of an external selected `.py` module | T:672–675 calls `external` and `visit`; T:1407 returns file requirements; T:2585–2617 requires an actual matching installed declaration and content metadata | No additional gap established for a source module whose admitted analysis does not lose path effects. |
| Project stdlib-shadow contents | Project file selected instead of the installed stdlib module | T:673 records the file; T:1408 and T:2833–2853 expose source requirements | Shadow file identity is retained, but later imports selected by that shadow’s path mutation can be omitted: CA-03. |
| Native stdlib and runtime linkage | Native payloads, external symlink targets, linked libraries | T:678–692 inventories native candidates and permits only the exact configured runtime-library exception; T:1388–1404 submits native inputs and adds discovered roots | No broad runtime-prefix exemption found. External stdlib-native selection independently refuses at T:669–671. Framework hash-binding regression exists at TT:675–689. |
| Loader-helper root | Runtime value passed under a matching parameter name | T:1078–1081 substitutes `Path(root)` after checking identifier spelling | CA-01, carried Base CA-16. |
| Imported loader-helper targets | Cross-module helper calls and their arguments | T:1070–1084 specializes defining-file references; T:1130–1131 loses ordinary imported callable identity | CA-02, carried Base CA-17. |

### CA-03: inventory scanning consumes the visit cache without propagating import-time path effects

The new inventory calls:

`visit(origin, ImportPaths(search), cwd, argv, name, flags, project)`

at T:675. This scans a selected shadow using a separate path list. The same `visit` implementation records its key in the request-wide `seen` set at T:1291–1293. That key contains the path values and module name, without distinguishing an inventory scan from an actual application import.

An ordinary application import later enters `dependency` at T:712–717. Its `visit` receives the application’s path list, but the matching `seen` key returns immediately. The copied inventory path list’s mutations are not replayed into the application list.

A static counterexample uses only admitted source files and a straight-line project path insertion:

| File | Contents |
|---|---|
| `main.py` | `import colorsys` followed by `import chosen` |
| Project `colorsys.py` | `import sys`; `from pathlib import Path`; `sys.path.insert(0, str(Path(__file__).parent / "plugins"))` |
| Project `chosen.py` | `VALUE = 0` |
| `plugins/chosen.py` | `import external_plugin` |
| External `external_plugin.py` | Arbitrary dependency outside the project |

[INFERENCE] For a normal non-isolated file invocation where `colorsys` is not already imported, CPython imports the project shadow, prepends `plugins`, and then imports `plugins/chosen.py`. The analyzer inventories the shadow first, changes only its copied path list, and caches that visit. The later application import skips those effects and resolves the root `chosen.py`. `chosen` is not a stdlib namespace member, so inventorying every stdlib name under the copied path state does not discover it.

The relevant path insertion is explicitly admitted at T:1177–1188. This counterexample uses neither root-by-name helper specialization nor imported loader helpers. It is a new delta defect, separate from CA16/17.

The runtime consequence has not been executed. The cache collision and discarded path-effect mechanism are directly visible in the cited code. A parent-run regression should exercise the counterexample, require refusal or correct dependency capture, and confirm that changing `external_plugin.py` invalidates the affected identity.

## Lens 2 - Clause-to-line discharge

Only clauses and trust links crossing the assigned external-producer boundary are included.

| Clause | Expected discharge | Actual code line | Status |
|---|---|---|---|
| D I11, `docs/intent.md:25`: complete tool/environment provenance; unsupported closure prevents PASS | Every admitted dependency is bound or discovery refuses | T:646–717,1291–1293,1388–1408,2585–2617 | partial: CA-01/02 remain; CA-03 adds an omitted-dependency path |
| D I11: endpoint drift checks, without immutable-sandbox or cache-coherence claims | Recompute identities and compare at required boundaries | T:2800–2825 | discharged for the inspected comparison mechanism; it cannot detect inputs omitted from discovery |
| V4:229: model only supported selectors and static project-file forms | Preserve the effects of admitted path mutations, or refuse them | T:675,1177–1188,1291–1293 | gap: CA-03 |
| V4:235: resolve selected Python runtime and bind required external imports | Runtime roots, explicit file requirements, fail-closed external selection | T:663–676,1381–1408,2585–2617 | partial: ordinary inventory/file binding is present; import sequencing remains unsound |
| V4:243: retain probe identities and revalidate selection | Positive and negative selection changes affect comparison | T:657–661,677,1346–1356,2237–2239,2800–2825 | discharged for the inspected metadata path |
| V4:245,249,251: non-system runtime content and complete transitive closure | Native content/linkage or explicit refusal | T:669–692,1388–1404 | partial: the named external split-native hole is refused; this is not a proof of arbitrary Python loading behavior |
| D I12, `docs/intent.md:32`: preserve recipes, observations, failure barriers, and owner protocol | Inventory work must not manufacture successful execution evidence | T:1346–1408 returns adapter metadata; CR:224 calls capture metadata acceptance only | No changed execution-verdict mechanism found in this delta; complete I12 enforcement is outside this slice |
| D I13/I14, `docs/intent.md:33–34`: activation separation and restricted authority | No capture/test result activates production or authorizes live operations | CR:224; D ledger:618 | Preserved in the reviewed disposition; no activation claim follows |
| D ledger item 40, `.fv/ledger.md:618` | Failed collection and indeterminate ownership remain unresolved | Metadata-only adapter return at T:1403–1408; CR:224 | Preserved; isolated producer changes do not discharge this ledger obligation |
| D I11 trust premises | No concurrent mutation; declared upstream cache correctness | T:2800–2825 performs endpoint comparison only | Explicit assumptions, not code-proved guarantees |

## Lens 3 - Deferred cannot silently succeed

| Branch | Reachable from | Behavior | Status |
|---|---|---|---|
| Unknown/namespace/unsupported stdlib loader | `inventory_stdlib` | Raises at T:663–664 | Explicit refusal |
| Selected external stdlib package or native distribution | `inventory_stdlib` | Raises at T:666–671 | Explicit refusal |
| External stdlib source format outside admitted `.py` form | `inventory_stdlib` | Raises at T:676 | Explicit refusal |
| Native candidate outside runtime roots | `inventory_native_stdlib` | Raises unless it is the exact configured runtime library, T:690–692 | Explicit bounded exception |
| Deferred function-body analysis | `scan` | Processes queued functions and refuses unsupported deferred path mutation, T:1267–1278 | This is deferred analysis work, not a success-returning stub |
| Known open loader-helper semantics | Helper specialization and ordinary imported-call handling | Root substitution and unknown imported-call semantics still allow discovery to continue, T:1046,1070–1084,1130–1131 | Carried CA-01/02 |
| Inventory-populated `seen` entry | Later ordinary import | Returns without replaying copied path effects, T:1291–1293 | CA-03; counted under commitment coverage |

No new TODO/mock placeholder was identified in the inspected delta. The silent-success concern is an analysis-state error rather than a labeled stub.

## Lens 4 - Who controls

| Field | Supplier | Validation | Gap |
|---|---|---|---|
| `stdlib_selections[].paths`, `import_roots`, `modules` | Reviewed command/environment configuration, interpreter finder results, project path mutations | T:646–677 records selections; T:789–801 constrains project paths; T:1177–1188 admits bounded mutations | CA-03: recorded hypothetical path states do not preserve the application’s actual import effects |
| `project_stdlib_files` | Selected source origins within the project | T:673 adds selected files; T:1284–1289 refuses symlinked/unsupported source; T:1408 exposes requirements | File membership itself is validated; downstream selections remain affected by CA-03 |
| `requirements[].ids/files` | Command tool closure and analyzer-discovered external files | T:1320–1343 constructs requirements; T:2585–2617 checks declaration membership and bytes | Omitted dependencies cannot reach this validation: CA-01/02/03 |
| `stdlib_native` | Installed runtime directory entries and sysconfig selection | T:678–692 checks roots and the exact exception; T:1388–1404 performs native discovery | No additional control-validation gap established in this delta |
| `source_inputs` | Bytes read by static analysis | T:1295–1297 hashes bytes; T:1343 retains them in probe output | Hashes establish the analyzed bytes, not correctness of the analyzer’s selected dependency set |
| Helper root argument | Application source and runtime caller | Identifier-name check at T:1080 | CA-01, carried |
| Imported helper arguments | Application caller in another module | Ordinary imported names become `UNKNOWN`, T:1130–1131 | CA-02, carried |

## Lens 5 - Field-name fidelity

| Field | Implied semantic | Actual value | Status |
|---|---|---|---|
| `stdlib_selections[].modules[].origin` / `realpath` / `locations` | Finder-selected origin, canonical file path, and package search locations | Directly populated from specs at T:659–661 | Faithful to a finder observation; not an executed-import trace |
| Absent module row | No selection under the observed search state | `origin: null`, `locations: null` at T:657–658 | Faithful |
| `project_stdlib_files` | Project files shadowing interpreter-declared stdlib names | T:673 | Faithful |
| `stdlib_native` | Native candidates inventoried beneath runtime directory views | T:678–692 | Faithful as an inventory; does not imply every entry was loaded |
| `fileRequirements` / `sourceRequirements` | Required external tool files / project source files | T:1407–1408 | Category separation is faithful; completeness is CA-03 |
| Discovery `stdout_hash` | Digest of actual probe stdout | T:2238 | Faithful; hashing output does not establish semantic completeness |
| Capture `ok` | Capture operation accepted | Retained capture records `ok: true` and tool identities | No evidence that this field asserts a proof PASS |

No independent field-name mismatch was established.

## Lens 6 - Deferral justification audit

| Deferred finding | Justification claims | Claim audit | Verdict |
|---|---|---|---|
| Base CA-16 | Root-value analysis remains incomplete | Explicit shortcut at T:1046; name-based substitution remains at T:1078–1081 | Accurate OPEN disposition; carried CA-01 |
| Base CA-17 | Imported-helper analysis remains incomplete | Defining-file specialization and loss of imported callable identity remain at T:1070–1084,1130–1131 | Accurate OPEN disposition; carried CA-02 |
| Base CA-21 | Inventory all interpreter-declared stdlib names; retain absent selections; bind source shadows; refuse external package/native forms | T:654–676 implements these mechanisms. The named split-native selection is now caught without scanning every transitive stdlib importer. However, inventory scanning shares `seen` with application import analysis and discards copied path effects | Original namespace omission is addressed for stable search-state resolution. Do not mark the supported-form closure complete: CA-03 |
| Exact framework-library correction | Initial refusal came from the configured runtime library outside roots; exemption is exact, with content/linkage retained | T:679–692 compares one canonical configured library; T:1388–1404 supplies native candidates; TT:675–689 checks the library hash | Code supports the narrow correction; no surrounding-directory exemption found |
| Nine targeted methods and actual D capture | Regression and metadata acceptance only | Tests cover split source/package/native selection, absent names, path history, builtin/frozen precedence, and framework bytes at TT:541–739. Retained capture contains successful metadata identities | Limited claim is accurate. These cases do not exercise CA-03 |
| Other generic boundaries | Remain unqualified | CR:210,224 and D ledger:618 retain limitations | Not reopened or closed by this slice; no broader qualification inferred |

No separate wrong-deferral finding is assigned. The change record does not claim complete Python analysis or final qualification.

---

## Finding list (consolidated)

| ID | Lens | Severity | Surface | Intent ref | Code ref | Summary | Fix |
|---|---|---|---|---|---|---|---|
| CA-01 | commitment-coverage | Major | Python helper-root selection | D I11, `docs/intent.md:25`; V4:229,235,249,251 | T:1070–1084, especially 1078–1081 | OPEN, carried Base CA-16. Matching argument spelling is treated as proof that its runtime value is the project root. This can bind a different file from the executed loader target. | Establish the root argument’s value or refuse the invocation. Retain the fresh-provenance limitation. |
| CA-02 | commitment-coverage | Major | Imported Python loader helpers | D I11, `docs/intent.md:25`; V4:229,235,249,251 | T:1070–1084,1130–1131,967–1001 | OPEN, carried Base CA-17. Defining-file specialization does not establish targets supplied through imported helper calls; ordinary imported callable identity is discarded. | Preserve specialized helper identity across imports and validate caller arguments, or refuse unsupported imported-helper use. |
| CA-03 | commitment-coverage | Major | Inventory/application analysis-state interaction | D I11, `docs/intent.md:25`; V4:229,235,249,251 | T:675,712–717,1177–1188,1291–1293,1331–1333 | NEW. Inventory scans project stdlib shadows using copied import paths while populating the same `seen` cache used by actual application imports. A later import skips the shadow’s path effects and can resolve a subsequent nonstdlib import to the wrong file, omitting its external dependency. Static counterexample detailed above; not executed. | Separate inventory visitation from application import-state analysis, or retain and correctly apply admitted import effects. Add a regression with a path-mutating stdlib shadow followed by competing project modules and an external dependency. |

## Summary

- Total findings: 3, comprising 2 carried findings and 1 new defect
- By severity: Critical=0 Major=3 Minor=0 Informational=0
- By lens: commitment-coverage=3 clause-to-line=0 deferred-cannot-silently-succeed=0 who-controls=0 field-name=0 deferral-justification=0
- CA21 disposition: the original transitive split-stdlib namespace omission is addressed by whole-namespace selection and explicit external-native/package refusal. Supported-form closure is still incomplete because CA-03 loses admitted import-time path effects.
- Recommended next step:
  1. Correct CA-03’s shared visitation/path-effect mechanism and have the parent exercise the supplied regression.
  2. Keep Base CA16/17 open until argument values and imported-helper targets are established or refused.
  3. Preserve Dossier’s failed collection, indeterminate ownership, and unqualified generic reuse/canonical collection/activation dispositions.

Not checked: no commands, tests, builds, formatters, or live runtime operations were executed; this report does not attest the complete working tree against the declared commit.
Risk: the new inventory can record plausible tool identities while omitting a dependency selected by an admitted source shadow’s import-time path mutation.