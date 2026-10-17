# Code-adversarial review: Dossier / FV fresh Kani selector correction - 2026-10-16

- Operator: fv-code-adversary via OMP task (NOT FixFreshSolverAliases)
- Code commit reviewed: `8020b89`, caller-supplied; baseline `e36b939`
- Intent version reviewed: no frontmatter version; canonical target resolves through D `.fv/dispatch.json` to `D/docs/intent.md`
- Ledger version reviewed: no frontmatter timestamp; ledger states `Updated: 2026-10-08`
- Lens pack: crypto/enclave baseline, supplemented by Rust selector/loader analysis and concurrency/ownership boundaries
- Lenses applied: 1 through 6

## Scope and evidence

Path abbreviations:

| Name | Path |
|---|---|
| D | `/Users/mv/Development/burnt/dossier-wt/evidence-perf` |
| F | `/Users/mv/Development/reliq-fv-wt/evidence-fresh-rust` |
| I | `D/docs/intent.md` |
| L | `D/.fv/ledger.md` |
| V4 | `F/docs/execution-evidence-v4.md` |
| R | `F/tools/evidence-v4/evidence-v4-toolchain-rust.ts` |
| RT | `F/tests/r38_evidence_v4_rust_review.py` |
| C | `F/.fv/changes/2026-10-14-execution-evidence-v4.md` |
| Prior | `D/.fv/code-adversarial/2026-10-16-fresh-selector-review.md` |

The review covers the selector correction, its source-scanning callers, regression fixtures and the “Fresh Kani selector aliases” change-record section. The caller’s acceptance requirements supplement the producer contract: preserve canonical pinned kissat, support raw identifiers, and retain ordinary solver-named identifiers and literals.

This was a read-only static review. No commands, builds, tests, formatters, process signals or project writes were performed. Historical Git blobs were not independently compared with the supplied worktree.

Caller-observed evidence is accepted without rerunning it:

- 38 Rust-adapter methods passed, including 36 new subcases.
- Two negative methods against frozen `e36b939` produced 28 failing assertions.
- Actual Dossier EX-002 and EX-003 metadata capture succeeded.

I inspected the retained `identities.json`. EX-002 contains both `distribution/bin/kissat` and `solver` as executable files with size `423416` and hash:

`sha256:6cbea531c356468c23872474053de41e8c281cec0d7e4189f80b3524101c9aaf`

That establishes what the capture recorded. It does not establish execution of a proof or which solver a completed proof used.

Two Minor acceptance gaps remain. No additional literal import/direct-tool selector bypass was identified in the inspected forms. Arbitrary macro expansion remains outside this correction’s closure.

Important uncovered classes include whole-system authorization, arithmetic, reentrancy, resource exhaustion, migration, store crash consistency, supply-chain authenticity and OS process-lifetime correctness. The separate Python loader/root-binding, split-stdlib and Darwin dependency-closure findings are not discharged here.

---

## Lens 1 - Commitment coverage

| Commitment | Attacker DoFs | Bound by | Gap |
|---|---|---|---|
| Kani solver tool root | Source-selected solver, CLI solver, installation location and installed bytes | `R:2093-2117` retains distribution, backend and kissat roots; CLI restriction at `R:2287-2288`; source checks at `R:1220-1248` | No remaining bypass identified for the inspected literal import/direct-tool forms. Expansion-generated selectors remain unqualified. |
| Imported solver attributes | Direct imports, renaming, grouped/nested use trees, public reexports and raw identifier spelling | Declaration scan at `R:1220-1226`; regressions at `RT:1011-1049` | These forms refuse, including imports whose later attribute name no longer contains `solver`. |
| Namespace-mediated solver attributes | Kani aliases, `self as`, globs and `extern crate` | `R:1223-1226`; `RT:1022-1033` | Named forms refuse. The scanner deliberately does not resolve whether an unrelated import named `solver` denotes a function or a macro. |
| Direct compiler-tool attributes | `kanitool::solver`, raw spelling, arguments and nested `cfg_attr` token groups | Complete square-bracket scan and residual-token refusal at `R:1229-1245`; `RT:1051-1089` | Inspected forms refuse, including a selector following another nested `[]` group. |
| Application source closure | Selector in root package, dependency or included non-`.rs` source | Package traversal at `R:1333-1368`; included-source recursion at `R:1369-1374`; caller at `R:1877` | The same selector checks reach these surfaces. The new cases rotate among the three locations; they are not a Cartesian test of every spelling at every location. |
| Exact-source exception hashes | Dependency content, inactive test/git source and reviewed inclusion sources | Selector checks precede inactive-source trimming at `R:1218-1253`; traversal calls the checks before accepting reviewed source hashes | No selector exemption introduced by those exceptions. |
| Retained EX-002 solver identity | Installed file bytes and executable metadata | Retained capture’s two matching entries; fixed roots at `R:2107-2113` | Matching identities are observed in the artifact. Fresh proof success and general provenance do not follow. |

The literal attribute allowlist has an over-refusal for `r#kissat`, described as CA-01 below. It does not admit an unbound alternate solver.

## Lens 2 - Clause-to-line discharge

Statuses apply to this correction’s evidence boundary. They do not discharge Dossier protocol clauses or composition candidates.

| Clause | Expected discharge | Actual code line | Status |
|---|---|---|---|
| I11, `I:25`; V4 adapter contract, `V4:227-251` | Bind actual tool closure or refuse unsupported selection | `R:1220-1248,2093-2117` | partial: named literal selector routes refuse; arbitrary expansion remains outside the closure |
| Acceptance: direct/grouped/nested imports, aliases, globs, extern crate and reexports; `C:154` | Refuse selectors that cannot be resolved safely | `R:1220-1226`; `RT:1011-1049` | discharged for the named literal forms |
| Acceptance: raw `kanitool` attributes and nested token groups; `C:154` | Refuse direct-tool and unknown solver forms throughout the attribute | `R:1229-1245`; `RT:1051-1089` | discharged for inspected forms |
| Acceptance: raw identifiers and canonical pinned kissat; `C:154` | Preserve semantically identical raw spelling of the pinned selector | `R:1242,1247-1248`; `RT:1115-1121` | partial: CA-01, raw solver argument `r#kissat` is omitted |
| Acceptance: ordinary solver-named identifiers; `C:154` | Do not reinterpret ordinary function/parameter syntax as an import | `R:1220-1226`; `RT:1091-1114` | partial: CA-02, ASCII keyword boundaries match inside Unicode identifiers |
| Acceptance: literals and comments; `C:154` | Ignore selector-looking text inside literals/comments | `R:1091-1140`; `RT:1098-1113` | discharged for the represented ordinary/raw/byte string, character and comment cases |
| I12, `I:32` | Preserve recipes, observations, failure history and ownership requirements | Reviewed selector path adds refusals; regression capture calls discovery only at `RT:46-63` | partial: no execution/history implementation was re-audited |
| I13–I14, `I:33-34` | No activation, deployment or authority expansion | Correction’s stated boundary at `C:158`; reviewed scanner has no activation or deployment operation | discharged for this correction’s scope |
| V4 S1/S2, `V4:15-16` | Preserve logical slots and immutable execution ownership | No slot or execution-artifact code is changed by the reviewed scanner | partial: maintained as external obligations |
| V4 B1/B2, `V4:17-18` | Metadata/refusal tests cannot become execution PASS | Fixture returns discovery results at `RT:46-65`; actual capture is an identity artifact | partial: these artifacts do not discharge invocation completion |
| V4 T1/T2, `V4:19-20` | Preserve failure barriers and indeterminate ownership | No ownership-recovery implementation is in this correction | partial: failed run `a84f2846` remains blocked under the assignment’s preserved state |
| I11 operational premises; `V4:160-175` | Nonmutation and upstream-cache integrity remain assumptions | Source reads and namespace selection do not prove continuous immutability or fresh compilation | partial: assumptions retained |
| Ledger C-01 through C-15 | Do not promote incomplete composition from adapter evidence | `L:7-14`; scoped discovery return at `R:2347-2353` | partial: every candidate remains outside this correction’s discharge |
| Ledger TA-08 | Retain operator-honesty premise for unsigned local evidence | `L:462`; supplied capture is an unsigned local artifact | partial: not discharged |
| Ledger TA-01 through TA-07 and TA-09 through TA-17 | Preserve their platform, cryptographic, operational and deployment limits | `L:453-471`; no corresponding enforcement is added in the reviewed scanner | partial: outside this correction |

### CA-01: raw pinned solver argument is rejected

Consider:

`#[kani::proof] #[kani::solver(r#kissat)] fn proof() { assert!(true); }`

The Rust Reference’s [raw-identifier rule](https://doc.rust-lang.org/reference/identifiers.html#raw-identifiers) states that `r#` is not part of the actual identifier. Installed Kani’s macro forwards the argument token stream into `kanitool::solver` without changing the selected argument: `/Users/mv/.kani/kani-0.67.0/library/kani_macros/src/lib.rs:467-477,593`. Kani 0.67.0’s [solver parser](https://github.com/model-checking/kani/blob/kani-0.67.0/kani-compiler/src/kani_middle/attributes.rs#L1029-L1042) obtains `meta_item.ident().as_str()` and parses that identifier as the solver.

The adapter’s canonical-removal expression accepts optional `r#` on `kani` and `solver`, but requires literal `kissat` at `R:1242`. Its second check also requires literal `kissat` at `R:1248`.

[INFERENCE] The example is rejected by adapter discovery despite naming the same pinned solver. This was derived statically, not executed. The preservation test contains `r#kani::r#solver(kissat)` but no `r#kissat` case.

This is a remaining acceptance gap, not a claim that this spelling worked at baseline.

### CA-02: Unicode identifiers can be mistaken for `use` declarations

Consider this ordinary function, with no import or attribute:

`pub fn réuse(solver: u8) -> u8 { solver }`

The identifier `réuse` is valid under Rust’s Unicode identifier rules. At `R:1220`, JavaScript’s `\w` does not recognize `é` as an identifier continuation. Consequently, `(?<![#\w])use\b` matches the suffix `use` inside `réuse`. The declaration-shaped match then includes the parameter `solver`, causing `R:1223-1226` to reject it.

[INFERENCE] A package containing that function is refused as containing a Kani solver import. This was derived statically, not executed. The same shared source path runs for Cargo and Kani contexts at `R:1877`.

The existing benign-token fixture covers `r#use`, ordinary ASCII names and literals, but no Unicode identifier containing a keyword-shaped suffix.

## Lens 3 - Deferred cannot silently succeed

| Branch | Reachable from | Behavior | Status |
|---|---|---|---|
| Recognized unsupported imports/aliases | Application/dependency/included-source scanning | Calls `fail`, which throws; `R:1220-1226` | Explicit refusal |
| Unknown literal solver attribute | Attribute scanning | Throws at `R:1244-1245` | Explicit refusal |
| Unclassifiable source or unterminated attribute | Source scanning | Throws at `R:1219,1238` | Explicit refusal |
| Generated-selector limitation | Literal scanner’s documented shortcut, `R:1228` | Does not expand macros or establish an expansion closure | Unqualified surface; no generic fail-closed expansion claim |
| Fixture Kani executables | Test-only `CargoFixture.kani`, `RT:152-199` | Fake version-producing executables support discovery tests | Not production-reachable through this fixture; not proof-execution evidence |
| Reviewed `mock.rs` entries | Dependency source exceptions at `R:1200-1203` | Exact filenames/hashes; selector scan still occurs before inactive-test trimming | No deferred verification success in this mechanism |

No additional production TODO/stub returning success was identified in the inspected correction. The generated-selector limitation remains material.

## Lens 4 - Who controls

The correction adds no persistent state fields. Its inputs and returned identity fields still cross trust boundaries.

| Field | Supplier | Validation | Gap |
|---|---|---|---|
| Rust source text | Project and selected dependency authors | Literal/comment stripping, import refusal and attribute checks at `R:1091-1140,1218-1248` | CA-01 and CA-02 are over-refusals; expansion closure remains unqualified |
| Included-source path | Source author | Package containment and exclusions at `R:1257-1271`; recursive scan at `R:1369-1374` | No new gap identified in the named included-source cases |
| Canonical solver argument | Harness author | Two spelling-based kissat allowlists at `R:1242,1248` | CA-01 |
| CLI solver | Reviewed subject argv | Non-kissat selection refuses at `R:2287-2288` | No change or new gap identified |
| `solver` root path | Installed Kani distribution selected by environment/configuration | Distribution/compiler checks at `R:2048-2092`; required path and root at `R:2093-2113` | Captured root preserved; this does not prove runtime selection for every harness |
| Source exception identities | Producer-maintained reviewed hashes | Exact-content comparisons and subsequent checks at `R:1344-1384` | No new selector bypass identified |
| Test `ok`, `error`, roots and probe arrays | Test wrapper around real discovery | Discovery result or caught error at `RT:46-65` | Test result means adapter capture/refusal, not Kani proof completion |

## Lens 5 - Field-name fidelity

| Field | Implied semantic | Actual value | Status |
|---|---|---|---|
| `solver` root | Bound solver dependency in the Kani context | Distribution `bin/kissat` at `R:2112`; retained capture agrees | Faithful as a dependency identity; not evidence that every harness executed kissat |
| `backend` root | Bound CBMC backend | Distribution `bin/cbmc` at `R:2111` | Faithful in inspected construction |
| `packages` | Source-qualified selected application graph | Graph identities returned by `discoverRustAdapter`, `R:2347-2353` | No field-population change in this correction |
| `discovery` | Recorded discovery probes | Ordered runtime/graph/native probe identities returned by discovery | No proof-result semantics added |
| Test `ok:true` | Adapter capture succeeded | Successful `discoverRustAdapter` and package-root hashing at `RT:46-65` | Faithful within the test harness |
| Change-record “raw identifier spelling” | Raw spellings preserve canonical pinned selection | Raw namespace/macro spelling is tested; raw argument spelling is rejected | CA-01; documentation claim is broader than implemented coverage |

Kani 0.67.0’s [driver](https://github.com/model-checking/kani/blob/kani-0.67.0/kani-driver/src/call_cbmc.rs#L269-L307) gives CLI selection precedence, then uses a harness selection, otherwise its default. Its default is CaDiCaL. Retaining kissat alongside CBMC therefore does not establish that an unannotated Dossier harness runs kissat.

## Lens 6 - Deferral justification audit

| Deferred finding | Justification claims | Claim audit | Verdict |
|---|---|---|---|
| Prior CA-01: imported/renamed solver attributes | Imports and reexports are now refused before a renamed attribute can escape detection | `R:1220-1226`; direct, grouped, nested, raw and reexport regressions at `RT:1011-1049` | Closed for those literal forms |
| Prior CA-01: namespace indirection | Aliases, globs and extern-crate routes refuse | Same declaration check; named examples in `RT:1022-1033` | Closed for named literal routes |
| Prior CA-01: direct `kanitool::solver` | All attribute token groups are scanned, including raw spelling and nested brackets | `R:1229-1245`; `RT:1051-1089` | Closed for inspected literal forms |
| Preservation claim | Raw canonical kissat and ordinary solver identifiers remain supported | `C:154`; implementation and tests omit the two cases detailed above | Incomplete: CA-01 and CA-02 |
| Arbitrary macro-generated selectors | Remain outside the bounded scanner’s closure | `R:1228`; `C:158`; no expansion phase exists in the reviewed path | Accurate limitation; not a justification for generic provenance qualification |
| No generic reuse/activation qualification | Tests and metadata capture do not refresh failed collection or production evidence | `C:158`; fixture is discovery-only; retained artifact contains identities | Valid scope restriction |
| Other prior loader/native findings | Remain separate and open | Prior explicitly retains those boundaries; this correction is confined to Rust selector scanning | Not closed and not recounted as new findings |

Prior CA-01 is therefore closed only for the enumerated literal import, namespace and compiler-tool attribute routes. Its broader concern, that an arbitrary accepted Rust program cannot select an unbound solver, is not discharged.

### Remaining expansion-dependent bypass

The following schematic source illustrates the excluded boundary:

`macro_rules! choose { ($name:ident) => { #[kani::proof] #[kanitool::$name(bin="/opt/sat")] fn proof() { assert!(false); } }; } choose!(solver);`

The literal attribute contains `$name`, while the literal `solver` appears in a macro invocation outside an attribute or import.

[INFERENCE] The reviewed scanner does not reject this selector construction, and expansion supplies the direct-tool selector that the compiler recognizes. No expansion or proof experiment was run. This is recorded as the explicitly excluded macro-expansion limitation, not as a newly discovered literal-route defect or evidence of a false proof result.

### Deliberate remaining over-refusals

The correction also refuses:

- An unrelated function import such as `use crate::math::solver;`.
- A benign attribute mentioning a function named `solver`, such as a Kani stub target.
- Kani namespace aliases or globs even if they are used only for `proof` or `any`.
- Imported solver attributes even when their argument is kissat.
- Direct `kanitool::solver(kissat)`.

These follow from `R:1220-1245` and are acknowledged by `C:158`. They are not separately counted as undisclosed defects. They must remain visible when describing the supported source subset.

## Concurrency and loader supplement

| Boundary | Inspected evidence | Disposition |
|---|---|---|
| Source read versus later compilation | Scanner reads package files; V4 requires nonmutation and upstream-cache integrity | No continuous-immutability or fresh-compilation claim |
| Solver loader closure | Fixed roots and source refusals; retained kissat byte identity | Named literal correction supported; runtime loading and expansion are not qualified universally |
| Failed run `a84f2846` | Assignment fixes its owner as indeterminate | Remains preserved; same-boot recovery is blocked |
| Cross-run reuse | Assignment retains D’s no-reuse posture | No recommendation to enable reuse |
| Smoke/capture promotion | Capture artifact records tool identities; tests exercise discovery | Neither supersedes failed collection nor supplies proof/activation evidence |
| Installed runtime | Correction is in F; installed runtime remains `e36b939` per caller | No installed-runtime change or qualification inferred |

---

## Finding list (consolidated)

| ID | Lens | Severity | Surface | Intent ref | Code ref | Summary | Fix |
|---|---|---|---|---|---|---|---|
| CA-01 | clause-to-line | Minor | Canonical pinned solver admission | Acceptance: raw identifiers and pinned kissat; `C:154`; V4 §Scope and compatibility | `R:1242,1247-1248`; `RT:1115-1121`; Kani 0.67.0 `attributes.rs:1029-1042` | `#[kani::solver(r#kissat)]` denotes the pinned solver, but both allowlists require the non-raw argument spelling. Existing tests cover raw namespace/macro names only. This is a remaining acceptance gap, with no unbound-solver admission demonstrated. | Accept the raw spelling of the exact kissat identifier in both checks. Add direct and nested `cfg_attr` preservation cases that assert the same solver root. |
| CA-02 | clause-to-line | Minor | Rust import-token recognition | Acceptance: ordinary solver-named identifiers; `C:154`; V4 §Scope and compatibility | `R:1220-1226,1877`; `RT:1091-1114` | ASCII regex boundaries match `use` inside a valid Unicode identifier such as `réuse`. An ordinary `solver` parameter then triggers the import refusal, including in Cargo contexts. | Use Rust-compatible identifier boundaries when recognizing declaration keywords. Add a benign Unicode-identifier case with a solver-named parameter for Cargo and Kani discovery. |

## Summary

- Total findings: 2
- By severity: Critical=0 Major=0 Minor=2 Informational=0
- By lens: commitment-coverage=0 clause-to-line=2 deferred-cannot-silently-succeed=0 who-controls=0 field-name=0 deferral-justification=0
- Recommended next step:
  1. Correct the raw kissat argument and Unicode keyword-boundary over-refusals; add the targeted preservation regressions.
  2. Have the parent run the Rust-adapter suite once after edits freeze. Any real Kani compatibility experiment must remain separate from D’s failed collection.
  3. Record prior CA-01 as closed for the named literal routes only. Retain the macro-expansion, loader and generic provenance exclusions.
  4. Preserve `a84f2846`, its indeterminate ownership and D’s disabled cross-run reuse. Do not infer proof success or activation from metadata capture.

Skipped: command execution, historical blob comparison, arbitrary macro expansion and whole-system ownership/loader verification.  
Risk: the bounded literal correction does not qualify generic fresh-PASS provenance, permit same-boot recovery or activate any Dossier capability.