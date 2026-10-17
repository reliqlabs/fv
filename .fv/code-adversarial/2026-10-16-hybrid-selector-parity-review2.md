# Code-adversarial review: Dossier evidence v4 selector-parity delta - 2026-10-16

- Operator: fv-code-adversary via OMP task (NOT parent orchestrator, the delta implementation author)
- Code commit reviewed: `005f84e`, as supplied. Reviewed worktree excerpts; commit-to-worktree equality was not independently checked.
- Intent version reviewed: no frontmatter version. Canonical target remains `D/docs/intent.md`, resolved through `D/.fv/dispatch.json` → `omp_native.target_spec`.
- Ledger version reviewed: frontmatter timestamp absent; body states `Updated: 2026-10-08`.
- Lens pack: crypto/enclave lenses supplemented with input-closure and execution-provenance validation.
- Lenses applied: 1 through 6.
- Review scope: the Python selector-basename correction, its paired regression vectors, and the unchanged TS derived-native predicate.
- Method: static reads only. No commands, tests, edits, or process changes.

## Scope and disposition

CA-01 from the preceding review is closed. Both Python selector checks now preserve terminal `/.` and agree with the TS predicate for the reported counterexamples. No new defect was found in this delta.

| Alias | Path |
|---|---|
| D | `/Users/mv/Development/burnt/dossier-wt/evidence-perf` |
| F | `/Users/mv/Development/reliq-fv-wt/evidence-hybrid-union` |
| DI | `D/docs/intent.md` |
| V4 | `F/docs/execution-evidence-v4.md` |
| PC | `F/scripts/fv_evidence_v4.py` |
| ST | `F/tests/r38_evidence_v4_source_review.py` |
| S | `F/tools/evidence-v4/evidence-v4-source.ts` |

The parent reports that both negative vectors failed before the correction and passed afterward. The parent also reports an actual captured Cargo identity was accepted unchanged and rejected after either mutation. Those observations are accepted as reported; this reviewer did not rerun them or inspect a retained smoke artifact.

Other toolchain files were not revisited. This report is separate from the original review and does not revise its record.

Important uncovered classes remain generic loader analysis, supply-chain authenticity, concurrency, resource exhaustion, storage/error atomicity, and native ownership. This delta does not qualify cache reuse or deployment activation.

---

## Lens 1 - Commitment coverage

| Commitment | Attacker DoFs | Bound by | Gap |
|---|---|---|---|
| Derived-native locator identity | Selector spelling, including trailing `/` and terminal `/.` | PC:354-356 checks the lexical basename after stripping trailing separators; S:378 uses POSIX `path.basename` | Original discrepancy closed |
| Recorded Rustup discovery | Probe executable spelling, argument count, selected driver, exit status | PC:365-373 retains the three-token, `which`, driver-name and zero-status checks, with corrected basename handling; S:379-386 supplies the corresponding TS predicate | Original discrepancy closed |
| Retained identity bytes | Locator and probe strings | The inspected correction compares strings without rewriting the recorded fields | No commitment change identified |

No hash construction, signature, or attestation format changes are present in the reviewed correction.

## Lens 2 - Clause-to-line discharge

| Clause | Expected discharge | Actual code line | Status |
|---|---|---|---|
| DI I11: complete tool provenance | Do not accept a selector witness rejected by the producer’s derived-native validator | PC:354-356, 365-373; S:378-386 | discharged for CA-01 |
| V4:26: no argv normalization | Preserve terminal `/.` when interpreting the executable name | `posixpath.basename(value.rstrip("/"))` at both Python selector checks | discharged for this delta |
| V4:227: locator basename names a retained driver | `/recorded/cargo/.` must not be interpreted as basename `cargo` | PC:354-356 versus S:378 | discharged |
| V4:227: successful Rustup selection probe | `/recorded/rustup/.` must not be interpreted as basename `rustup` | PC:365-373 versus S:383 | discharged |
| V4:227: producer/checker acceptance agreement | Paired positive and negative vectors exercise both validators | ST:788 onward, `test_derived_native_identity_matches_portable_byte_and_encoding_checks` | discharged for the reported spellings; no universal interpreter-parity proof claimed |
| Ledger TA-08: operator honesty | Independent evidence authenticity | No authentication mechanism added | unchanged assumption; outside delta |

Other intent clauses and ledger composition links have no changed enforcing surface in this correction. Their previous statuses remain unchanged.

## Lens 3 - Deferred cannot silently succeed

| Branch | Reachable from | Behavior | Status |
|---|---|---|---|
| Invalid locator basename | Portable `_tool` validation | `_check` rejects unless the basename names a retained driver, PC:354-357 | explicit refusal |
| Invalid Rustup probe basename | Portable `_tool` validation | Probe fails the predicate; absence of another valid selection probe causes rejection, PC:365-374 | explicit refusal |
| Deferred/stub behavior introduced by this delta | Inspected correction | No fallback, stub, or success-on-error branch appears | no applicable deferred branch |

## Lens 4 - Who controls

| Field | Supplier | Validation | Gap |
|---|---|---|---|
| `declaration.locator.value` and matching identity locator | Reviewed policy and retained identity | Exact declaration binding remains in PC:312-318; lexical driver-basename check at PC:354-356 | none found in delta |
| `discovery[].command[0]` | Recorded producer probe | Lexical `rustup` basename, exact argument count and `["which", name]` suffix | none found in delta |
| `discovery[].exit_code` | Recorded producer result | Must equal zero for the retained driver-selection witness | unchanged |
| Regression expectations | Test author | Both TS and Python must accept positive vectors and reject negative vectors | Both reported counterexamples are covered |

## Lens 5 - Field-name fidelity

| Field | Implied semantic | Actual value | Status |
|---|---|---|---|
| `locator.value` | Original locator spelling | Comparison strips trailing separators only for basename extraction; stored value remains unchanged | faithful |
| `discovery.command` | Original probe argv | No stored argv mutation; terminal `/.` remains significant to validation | faithful |
| `native/drivers/cargo-0` / `rustc-0` | Selected executable driver bytes | Driver byte/executable checks remain present in PC:359-363 and S:368-370 | unchanged |

The accepted trailing-slash vectors establish predicate compatibility. They do not establish that a regular executable can actually be invoked with a trailing slash.

## Lens 6 - Deferral justification audit

| Deferred finding | Justification claims | Claim audit | Verdict |
|---|---|---|---|
| Prior CA-01: Python normalizes selector basenames more broadly than TS | Replace `Path(...).name` at both affected sites with lexical POSIX basename extraction | PC now imports `posixpath` and uses `posixpath.basename(value.rstrip("/"))` for both locator and probe executable. Terminal `/.` yields `"."`; it no longer yields `cargo` or `rustup`. S:378-386 rejects those same spellings. | closed |
| Regression adequacy for CA-01 | Cover both negative mutations and preserve ordinary accepted forms | ST adds absolute Cargo locator, trailing-slash Cargo locator, terminal-`/.` Cargo rejection, trailing-slash Rustup probe and terminal-`/.` Rustup rejection. The original ordinary Rustup probe remains the positive baseline. Both validators are exercised by the existing vector loop. | supported by inspected tests |
| Parent’s captured-identity smoke | Original accepted; each mutation rejected | Reported by parent; not independently exercised here | corroborating reported evidence only |
| Previously open generic Python/Darwin provenance and collection ownership work | This correction does not close those subjects | No such claim or implementation surface is included in the inspected delta | open, unchanged |

The earlier ProofCA01..04 and SourceCA12..14 dispositions are not re-audited here. Closing this report’s prior CA-01 removes the specific derived-selector parity residual identified in the preceding review.

---

## Finding list (consolidated)

| ID | Lens | Severity | Surface | Intent ref | Code ref | Summary | Fix |
|---|---|---|---|---|---|---|---|
| None | — | — | Scoped selector-parity delta | — | — | No new finding in the inspected correction | None required for CA-01 |

## Summary

- Total findings: 0 new; prior CA-01 closed.
- By severity: Critical=0 Major=0 Minor=0 Informational=0.
- By lens: commitment-coverage=0 clause-to-line=0 deferred-cannot-silently-succeed=0 who-controls=0 field-name=0 deferral-justification=0.
- Recommended next step: retain this delta report separately, record CA-01 as closed, and continue the separately assigned wider-toolchain and native-ownership gates. No additional patch is required for the reviewed defect.
- Verification exercised by this reviewer: static inspection only. The parent’s reported negative-vector and captured-identity results were not rerun.
- Residual boundary: generic provenance gaps, the separate Dossier collection failure, general cache reuse, and activation remain unqualified.