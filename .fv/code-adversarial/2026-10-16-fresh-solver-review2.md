# Code-adversarial review: Dossier / FV selector preservation delta - 2026-10-16

- Operator: fv-code-adversary via OMP task (NOT Main, the delta author; NOT FixFreshSolverAliases, the original correction author)
- Code commit reviewed: `1c15dc3`, caller-supplied; delta against reviewed `8020b89`
- Intent version reviewed: no frontmatter version; canonical target resolves through D `.fv/dispatch.json` to `D/docs/intent.md`
- Ledger version reviewed: no frontmatter timestamp; current ledger states `Updated: 2026-10-16`
- Lens pack: crypto/enclave baseline, supplemented by Rust selector/loader analysis and concurrency/ownership boundaries
- Lenses applied: 1 through 6

## Scope and evidence

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
| Prior | `F/.fv/code-adversarial/2026-10-16-fresh-solver-review1.md` |

This review covers only the two preservation corrections requested after review of `8020b89`:

1. Optional `r#` on the exact kissat argument in both solver allowlists.
2. Unicode identifier-continuation boundaries around declaration keywords.

The original report remains immutable. Its broader scope limits and deliberate conservative refusals remain applicable.

No commands, tests, builds, formatters, process signals or edits were performed. The supplied commit identifier was not independently checked against historical Git blobs.

Caller-observed evidence, accepted without rerunning:

- Six preservation assertions failed before correction.
- All 39 Rust-adapter methods passed after correction.
- Actual Dossier EX-002 and EX-003 metadata capture succeeded again.

I inspected the new retained artifact:

`/var/folders/ph/n581g1fj3tnbq8n74hp05klc0000gn/T/fv-real-solver-selection-ePvvk0/identities.json`

EX-002 again records both `distribution/bin/kissat` and `solver` with:

- Hash: `sha256:6cbea531c356468c23872474053de41e8c281cec0d7e4189f80b3524101c9aaf`
- Size: `423416`
- Executable: `true`

These are metadata-capture observations. No proof execution, actual per-harness solver selection or activation conclusion follows.

Important uncovered classes include arbitrary macro expansion, whole-system authorization, arithmetic, resource exhaustion, migration, supply-chain authenticity, store crash consistency and OS process-lifetime correctness. Separate Python loader/root-binding, split-stdlib and Darwin dependency-closure findings are outside this delta.

---

## Lens 1 - Commitment coverage

| Commitment | Attacker DoFs | Bound by | Gap |
|---|---|---|---|
| Canonical pinned solver argument | Ordinary versus raw identifier spelling; alternate name, extra arguments or external binary selector | `R:1242` admits only optional `r#` followed by exact `kissat`, optional trailing comma and closing parenthesis; `R:1248` independently anchors the complete argument | No new gap identified. The relaxation adds the same identifier spelling, not another solver. |
| Import-mediated solver selection | Actual declaration keywords versus keyword-shaped text inside identifiers | Unicode-aware declaration boundaries at `R:1220`; existing declaration-content refusals at `R:1223-1226` | No new bypass identified in the delta. Genuine `use` and `extern crate` declarations remain scanned. |
| Retained solver file identity | Installed file content and executable metadata | Both matching entries in the new EX-002 capture | The recorded kissat identity is preserved. Runtime solver selection remains a separate question. |
| Expansion-generated selector | Macro substitution or procedural generation | No expansion closure added; limitation remains at `R:1228` and `C:158` | Remains unqualified, outside this delta’s closure. |

The raw argument acceptance remains exact: `r#kissat` is admitted, while the changed expressions do not admit a different solver name, an additional argument or `bin=...`.

## Lens 2 - Clause-to-line discharge

Discharge statuses concern this delta only. They do not discharge Dossier’s protocol implementation or composition candidates.

| Clause | Expected discharge | Actual code line | Status |
|---|---|---|---|
| Acceptance: raw identifiers and canonical pinned kissat; `C:154,160` | Preserve `kani::solver(r#kissat)` and nested `cfg_attr` spelling without changing the selected root | `R:1242,1248`; tests at `RT:1121-1122,1125-1139` | discharged for prior CA-01 |
| Acceptance: ordinary solver-named identifiers; `C:154,160` | Avoid recognizing `use` inside Unicode or raw identifiers | `R:1220`; tests at `RT:1142-1154` | discharged for prior CA-02 |
| I11, `I:25`; V4 tool-closure contract | Retain refusal of unsupported literal selectors | `R:1223-1226,1244-1248` | discharged for the changed admission boundary; generic expansion closure remains partial |
| I12, `I:32` | Preserve recipe arguments, proof bounds, observations and failure barriers | Delta changes source admission only; preservation tests invoke discovery | partial: execution/history enforcement is outside this delta |
| I13–I14, `I:33-34` | No activation or deployment authority follows from local corrections | `C:158,160`; current failure annotation at `L:13,618` | discharged as a scope restriction |
| V4 S1/S2 and B1/B2 | Metadata capture cannot substitute for immutable, completed execution evidence | No execution-artifact or claim-publication change in the reviewed delta | partial: obligations remain with the producer |
| V4 T1/T2; I12 failure history | Preserve indeterminate ownership and failed collection | `L:618` explicitly retains the original owner and pending result | partial: no ownership implementation was re-audited |
| I11 nonmutation/cache premises | Do not infer continuous immutability or fresh compilation from endpoint/capture success | No such mechanism is added by `R:1220,1242,1248` | partial: external premises remain |
| Ledger C-01 through C-15 and TA-08 | Preserve incomplete composition and unsigned-evidence limitations | `L:8-15,618`; delta adds no composition or attestation mechanism | partial: no candidate or trust assumption is discharged |

### Prior CA-01 closure: raw kissat argument

Both checks now admit the raw spelling:

- Attribute-level canonical removal: `R:1242`
- Secondary argument validation: `R:1248`

The tests add both:

- `#[kani::solver(r#kissat)]`
- `#[cfg_attr(kani, kani::solver(r#kissat,))]`

Each successful preservation case still asserts that the `solver` root equals the fixture distribution’s `bin/kissat`, at `RT:1132-1139`.

This closes the reported mismatch between Rust’s raw identifier semantics and the adapter’s exact pinned-solver admission. The parent’s reported test result supplies exercised regression evidence; this reviewer did not execute Kani or the adapter.

### Prior CA-02 closure: Unicode keyword boundaries

The declaration matcher now uses:

`(?<![#\p{XID_Continue}])(?:use|extern\s+crate)(?!\p{XID_Continue})`

with Unicode mode.

At `R:1220`:

- The preceding `é` prevents matching the `use` suffix inside `réuse`.
- A following combining accent prevents treating `use\u0301` as the keyword `use`.
- The preceding `#` continues to exclude the raw identifier `r#use`.

`RT:1142-1154` places each spelling in an ordinary function with a `solver` parameter and checks discovery through both Cargo and Kani adapters.

This closes the reported keyword-boundary defect. It does not turn the scanner into a complete Rust parser or remove the separately documented conservative import/attribute refusals.

## Lens 3 - Deferred cannot silently succeed

| Branch | Reachable from | Behavior | Status |
|---|---|---|---|
| Newly admitted raw kissat spelling | Source attribute scan | Proceeds only after exact pinned-identifier matching | No deferred work or fake success introduced |
| Ordinary Unicode/raw function names | Source declaration scan | No longer misclassified as imports; normal scanning continues | Corrected false refusal |
| Actual solver imports and namespace aliases | Source declaration scan | Existing `fail` calls remain at `R:1223-1226` | Explicit refusal retained |
| Unsupported literal solver attributes | Attribute scan | Existing residual-token refusal remains at `R:1244-1245` | Explicit refusal retained |
| Arbitrary generated selectors | Existing documented scanner limitation | No expansion analysis added | Remains unqualified |

No new deferred, mock or stub production branch was identified in the reviewed delta. Test-fixture discovery success remains distinct from proof success.

## Lens 4 - Who controls

No persistent state fields are added by this delta.

| Field | Supplier | Validation | Gap |
|---|---|---|---|
| Solver argument spelling | Harness author | Exact optional-raw kissat checks at `R:1242,1248` | Prior CA-01 closed |
| Declaration keyword location | Source author | Unicode identifier-continuation boundaries and raw-identifier exclusion at `R:1220` | Prior CA-02 closed |
| Contents of genuine imports | Source author | Existing solver/namespace refusal at `R:1223-1226` | No new relaxation |
| Solver-root metadata | Existing adapter construction and installed distribution | Preservation assertion at `RT:1132-1139`; repeated real capture contains matching kissat entries | No root-selection change identified |
| Test capture result | Discovery wrapper | Existing adapter success/error result | Does not establish completed verification |

## Lens 5 - Field-name fidelity

| Field | Implied semantic | Actual value | Status |
|---|---|---|---|
| `solver` | Bound solver dependency | Distribution kissat, unchanged in fixture assertion and retained capture | Faithful as dependency identity |
| `distribution/bin/kissat` | Installed kissat executable bytes | Same recorded hash, size and executable flag as the `solver` entry | No mismatch identified |
| Test `ok` | Adapter discovery succeeded | Result of discovery, not Kani proof execution | Meaning unchanged |
| Change-record raw/Unicode correction claims | Both reported preservation defects are corrected | Checks at `R:1220,1242,1248`; targeted cases at `RT:1121-1122,1142-1154` | Supported within the stated delta |

No public schema, event, storage field or serialization change is introduced by this delta. The `solver` label still does not prove that an unannotated harness executed kissat rather than the backend’s default solver.

## Lens 6 - Deferral justification audit

| Deferred finding | Justification claims | Claim audit | Verdict |
|---|---|---|---|
| Prior CA-01, Minor: raw kissat rejected | Both allowlists now accept optional `r#` on the exact argument | Both code sites inspected; direct and nested preservation tests retain solver-root assertion | Closed for the reported defect |
| Prior CA-02, Minor: Unicode identifier misread as `use` | Declaration recognition now respects Unicode identifier continuation before and after keywords | Matcher inspected; `réuse`, `use\u0301` and `r#use` tested through both adapter families | Closed for the reported defect |
| Earlier fresh-selector CA-01, Major | Named literal import, alias, reexport and compiler-tool routes were corrected | This delta does not remove their existing refusals | Prior scoped closure retained; no broader closure asserted |
| Arbitrary macro expansion | Remains outside the scanner’s closure | `R:1228`; `C:158`; no expansion phase introduced | Accurate limitation, still unqualified |
| Generic producer provenance and activation | Local corrections and captures do not qualify either | `C:158`; `L:13,618` retain failed evidence and incomplete claims | Restriction retained |
| Failed run `a84f2846` | Original owner and pending result remain untouched; same-boot recovery refuses | Explicit current ledger annotation at `L:618` | No promotion or recovery authorization |

No wrong-deferral finding was identified in this delta.

## Concurrency and loader supplement

| Boundary | Delta effect | Disposition |
|---|---|---|
| Source reading versus later execution | Only lexical admission changes | Continuous nonmutation and upstream-cache integrity remain assumptions |
| Solver loading | Adds one equivalent identifier spelling; does not change roots or command construction | No new loader route identified; generic loader provenance remains outside scope |
| Ownership and failure barriers | No ownership, lock or recovery code reviewed or changed by this delta | `a84f2846` remains indeterminate; same-boot recovery remains blocked |
| Cross-run reuse | No reuse change | D’s disabled cross-run reuse remains required |
| Installed runtime | Work is in F | Installed `e36b939` is not changed or qualified by this report |
| Proof and activation evidence | Tests and metadata capture only | Cannot supersede the failed collection or activate Dossier |

Deliberate existing over-refusals remain: unrelated imports named `solver`, benign attributes mentioning `solver`, Kani aliases/globs, imported kissat selector attributes and direct `kanitool::solver(kissat)`. These are outside the two corrections and remain documented in the original report and `C:158`.

---

## Finding list (consolidated)

| ID | Lens | Severity | Surface | Intent ref | Code ref | Summary | Fix |
|---|---|---|---|---|---|---|---|

No new findings in the reviewed delta. Prior CA-01 and CA-02 are closed for their reported preservation defects. An empty finding list does not establish whole-system correctness or generic provenance closure.

## Summary

- Total findings: 0
- By severity: Critical=0 Major=0 Minor=0 Informational=0
- By lens: commitment-coverage=0 clause-to-line=0 deferred-cannot-silently-succeed=0 who-controls=0 field-name=0 deferral-justification=0
- Recommended next step:
  1. Record both Minor findings from the `8020b89` review as closed by `1c15dc3`, retaining the original report unchanged.
  2. Preserve the literal-only scope and documented conservative refusals. Do not extend closure to arbitrary macro expansion or broader producer provenance.
  3. Keep failed run `a84f2846`, its indeterminate owner and pending result intact. No smoke, test or metadata capture authorizes same-boot recovery, reuse or activation.

Skipped: command execution, historical blob comparison, real Kani proof execution and broad loader/concurrency re-audit.  
Risk: both preservation defects are corrected, but the failed collection and wider provenance boundaries remain unresolved.