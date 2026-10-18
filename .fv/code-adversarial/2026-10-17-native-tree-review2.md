# Code-adversarial review: Dossier external FV native-format correction - 2026-10-17

- Operator: fv-code-adversary via OMP task (NOT CloseDarwinTreeClosure or parent)
- Code commit reviewed: `0f0a3bf`; declared base `63c3648`
- Intent version reviewed: frontmatter version absent; canonical target resolved through D’s `.fv/dispatch.json` to `docs/intent.md`
- Ledger version reviewed: frontmatter timestamp absent; document states `Updated: 2026-10-16`
- Lens pack: evidence provenance and native-loader closure, using the six required crypto/enclave lenses
- Lenses applied: 1 through 6

## Scope and evidence

| Alias | Path |
|---|---|
| D | `/Users/mv/Development/burnt/dossier-wt/evidence-perf` |
| F | `/Users/mv/Development/reliq-fv-wt/evidence-darwin-trees` |
| I | `D/docs/intent.md` |
| L | `D/.fv/ledger.md` |
| T | `F/tools/evidence-v4/evidence-v4-toolchain.ts` |
| C | `F/tools/evidence-v4/evidence-v4-toolchain-common.ts` |
| TT | `F/tests/r38_evidence_v4_toolchain_review.py` |
| V4 | `F/docs/execution-evidence-v4.md` |
| CR | `F/.fv/changes/2026-10-14-execution-evidence-v4.md` |
| Results | `/private/var/folders/ph/n581g1fj3tnbq8n74hp05klc0000gn/T/fv-darwin-tree-selection-gfgn8181` |

This review covers CA-26’s shared format discriminator, all six production callsites, allocation and parsing boundaries, regression fixtures, and documentation. F remains the external producer for D’s I11/I12 provenance contract. Proposed Dossier root/Verus clauses and any future launch-context adapter are excluded.

Commit attribution is caller-provided; working-tree equality to the declared commit was not independently established. No commands, tests, builds, formatters, edits, credential reads or live-runtime changes were performed.

The parent reports three Java declaration assertions failing before correction and all four new methods passing afterward. Those observations were accepted without rerunning them.

The retained results were read:

- Go: `ok: true`, 12,362 manifest entries and 17 discovery records.
- Quint: `ok: true`, 4,998 manifest entries and no discovery probes.
- Verus: `ok: false`, still refusing `rust_verify`’s `@rpath/librustc_driver-e03ed1db822dfa4c.dylib`.

These are metadata-selection observations, not producer evidence of a completed canonical collection.

Important uncovered classes remain process containment, concurrency/crash recovery, resource exhaustion under large inputs, access control, upstream-cache poisoning, supply-chain authenticity and proof-to-implementation refinement.

## Correction disposition

| Surface | Disposition | Evidence |
|---|---|---|
| CA-26: ordinary Java class data treated as Mach-O | Closed for the reported mechanism | C:158-225 recognizes a complete structural class envelope; C:244-251 excludes it from native inspection. TT:1679-1721 covers tree/file/executable declarations, extensionless data and native-looking names. |
| Filename or execute-bit exemptions | Not introduced | Classification uses bytes at C:228-252. Retained content hashing remains independent of native classification at T:2465-2476. |
| Fat32/fat64 images | Still routed to native inspection | Fat64 never enters Java recognition. Fat32 candidates either bypass that recognition or undergo the native-member precedence check at C:170-176. TT:1724-1765 covers both formats and both external-dependency positions. |
| Java/native ambiguity | Native-member precedence retained | C:171-176 checks bounded fat-table positions before accepting a Java envelope. TT:1808-1827 exercises an embedded native member. |
| Malformed native candidates | Continue to inspection/refusal | A failed class parse yields `"macho"`, not `null`, at C:244-252. TT:1768-1805 covers truncated magic, tables, members, class envelopes and an invalid attribute index. |
| Little-endian fat-container fixtures | Fixture reclassification justified | Apple’s `fat.h` requires big-endian container structures. The fixture’s members remain independently little-endian at TT:1641-1653. |
| CA-24 | Refusal-only closure preserved | T:1491-1499 still rejects non-system edges without deriving launch semantics from tree membership or `requires`. |
| Verus rollout compatibility | Still absent | Retained Verus selection refuses. No launch-context adapter was added. |

---

## Lens 1 - Commitment coverage

| Commitment | Attacker DoFs | Bound by | Gap |
|---|---|---|---|
| Tool content identity | Java/native bytes, names, execute bits and declaration kind | Classification affects inspection selection; T:2465-2476 still hashes the complete retained manifest | No new commitment omission identified. A Java classification does not remove the file from `files`. |
| Native dependency closure | Shared `CAFEBABE` prefix, container/member byte order, member position and embedded native data | C:139-140,170-176,228-252; T:1491-1499 | No new load-edge bypass established in the inspected discriminator. |
| Fat-image architecture coverage | External dependency in either member | Classified image still goes to `otool -l`; C:262-280 parses its load-command blocks | TT:1724-1765 covers both positions. Runtime results are parent-reported, not independently executed here. |
| Discovery provenance | Which files reach metadata inspection and resulting probe identities | T:1474-1488 retains successful probe identities; native-free class files no longer create spurious probes | No new probe, dependency, or alternate evidence path introduced. |
| Endpoint identity | Changed file content or discovery results | T:2710-2737 reconstructs and compares content/selection identities | Existing endpoint-only guarantee preserved under the no-concurrent-mutation premise. |
| Python helper root | Runtime value supplied under the expected argument name | T:1013-1015 substitutes the project root by identifier | Carried CA-16 remains open. |
| Imported Python helper targets | Calls outside the defining module | T:1005-1018 specializes defining-file references; T:1067-1068 discards imported callable identity | Carried CA-17 remains open. |
| Transitive split-stdlib dependencies | Indirect selection of external Python extensions | T:640-641 skips transitive analysis | Carried residual CA-21 remains open. |

## Lens 2 - Clause-to-line discharge

| Clause | Expected discharge | Actual code line | Status |
|---|---|---|---|
| I11, I:25; V4:249-251 | Complete provenance or explicit refusal | C:228-252 classifies; T:1491-1499 refuses unbound non-system edges | discharged for the reviewed native-format correction; partial overall because carried gaps remain |
| I12, I:32 | Preserve complete declared closure without changing command semantics | T:2387-2393 invokes the unbound tree path without a process-image subject | discharged within this correction |
| V4:9, established compatibility; README:214-227 | Preserve native-free class data without a suffix exemption | C:158-225,244-251; TT:1679-1721 | discharged for CA-26’s reported mechanism |
| V4:217-225 | Preserve file bytes, kinds and manifest semantics | T:2383-2386,2465-2491 | discharged within inspected identity construction |
| V4:229 | Unsupported native configuration cannot silently acquire a supported meaning | C:244-252 preserves native inspection when class recognition fails; C:270 rejects embedded loader environment | discharged for the inspected branches |
| V4:243 | Retain real probe provenance and revalidate selection | T:1474-1488,2464,2710-2737 | discharged within inspected paths |
| V4:245 | Limit vendor-integrity exception to system dependencies | T:1495-1499 retains absolute, normalized system-prefix checks | discharged under the declared OS/vendor trust assumption |
| V4 B1/B2/T2, V4:17-20 | Do not let classification manufacture PASS or bypass drift checks | Classifier returns only a format decision; identity/revalidation remain at T:2465-2491,2710-2737 | partial: completion, failure-history and ownership enforcement are outside this delta |
| V4 S1/S2/T1, V4:15-19 | Preserve slot coverage, ownership and durable execution ordering | No slot/store/scheduler changes in the inspected correction | partial; no new discharge of those separate components |
| I13/I14, I:33-34; L:618 | Separate local repairs from activation and recovery | CR:233 calls the results metadata checks; no recovery or deployment mechanism added | partial; operational restrictions remain unchanged |
| L:461-462, TA-07/TA-08 | Do not equate local metadata with cross-host reproducibility or operator honesty | T:2480-2491 records unsigned local identities | partial; external assumptions remain |

Unrelated protocol clauses, composition candidates and proposed root/Verus clauses are outside this bounded review.

### Shared caller audit

| Caller | Current behavior | Assessment |
|---|---|---|
| `nativePayloads`, T:239-258 | Uses `nativeFileKind`; retains ordinary files through later manifest hashing | Correct separation between inspection selection and content retention. Existing alias traversal behavior is preserved. |
| Unbound tree inspection, T:1491-1499 | Inspects only `"macho"` results | Java data skips the inappropriate probe; unresolved native candidates still reach it. |
| `processImage`, T:1502-1527 | Reuses its existing prefix through `nativeFileKind(file, prefix)` | No additional header read. A Java envelope is not accepted as a Mach-O process image. |
| Native dependency inspection, T:1528-1570 | ELF enters Linux linkage; Mach-O enters Darwin inspection; other inputs retain shebang handling | ELF routing remains explicit. No new Linux load-resolution rule introduced. |
| Preferred Node runtime, T:1740-1757 | Only recognized native candidates terminate wrapper traversal | A Java envelope no longer masquerades as a native Node runtime; unsupported wrapper handling remains a refusal. |
| Bound-launcher check, T:2242-2243 | Uses the shared classifier instead of a separate magic comparison | Java data no longer satisfies this native-format test. This does not independently prove launcher behavior. |

The search found no remaining production copy of the old Mach-O magic test outside the shared classifier.

### Allocation and parser boundaries

- Ordinary noncollision inputs require an 11-byte header allocation. The caller-supplied prefix path avoids that allocation/read.
- Thin Mach-O, ELF and fat64 detection do not read the complete file.
- A plausible `CAFEBABE` class candidate is read in full at C:249. Peak classifier memory is therefore proportional to that file’s actual size, plus a constant-pool tag array of at most 65,535 bytes.
- Serialized attribute lengths do not cause correspondingly sized allocations. `skip` checks remaining bytes before advancing at C:160-168.
- The architecture scan is capped by the available table bytes at C:171. Member offsets are checked before reading magic at C:175.
- Long/double constant-pool entries consume their reserved extra index at C:186-188. Structural pool references and final exact consumption are checked at C:195-221.
- The parser does not recursively decode attribute bodies or claim JVM semantic verification. It recognizes an envelope for format discrimination.
- No size cap or streaming implementation bounds the full-file read. Large-file memory behavior was not exercised. This is a stated resource boundary, not evidence of constant-memory discovery or a separately established intent violation.

## Lens 3 - Deferred cannot silently succeed

| Branch | Reachable from | Behavior | Status |
|---|---|---|---|
| Complete Java envelope | Shared classifier | Returns `null`; callers retain/hash the file as non-native data | Authorized format distinction, not deferred verification |
| Embedded thin native member | Java/fat collision path | `isJavaClass` returns false at C:176; classifier returns `"macho"` | Native inspection retained |
| Truncated or structurally invalid class candidate | Java/fat collision path | Range/bounds failure returns false at C:222-224; classifier returns `"macho"` | Fail-closed routing |
| Unknown constant-pool tag | Structural class parser | Returns false at C:191 | Native inspection retained |
| File-open/read error | Shared classifier | Propagates; no catch converts it to non-native success | Explicit error |
| Non-system tree load edge | Ordinary Darwin tree | Throws at T:1499 | Refusal preserved |
| New TODO/stub/mock branches | New classifier and migrated callers | None identified | Empty labeled-stub surface |
| Transitive Python stdlib shortcut | Existing Python discovery | T:640-641 returns without transitive scanning | Carried CA-21, unchanged |

`"macho"` is a request for downstream inspection, not a declaration that the file is valid or safe to execute.

## Lens 4 - Who controls

| Field | Supplier | Validation | Gap |
|---|---|---|---|
| Format prefix | Installed file bytes, or the internal process-image caller | Actual prefix length and magic checked at C:239-245 | No caller-facing classification override introduced |
| Class counts and tags | File author | Remaining-byte checks, recognized widths, tag-index checks and exact end at C:160-221 | No unchecked count-based large allocation identified |
| Class attribute lengths | File author | `skip(uint(4))` checks remaining bytes at C:199-205 | No length-driven payload allocation; full input file is already resident |
| Fat member offsets | File author | Table-position bound and member-range check at C:171-175 | No out-of-bounds read established |
| Declaration kind/name/execute mode | Reviewed policy and installed filesystem | T:2383-2386; classifier ignores suffix and execute-bit shortcuts | No new classification bypass established |
| Persisted file hash and manifest | Producer hashing | T:2465-2476 | Class recognition does not replace content hashing |
| Public policy/state fields | Existing schemas | No new serialized field added by this correction | No new stored-state control surface |

## Lens 5 - Field-name fidelity

| Field | Implied semantic | Actual value | Status |
|---|---|---|---|
| `files` | Retained installed content | Complete selected roots still passed to the hasher at T:2465 | faithful |
| `digest` | Content identity | Hash of kind, files, packages and system dependencies at T:2476 | faithful |
| `discovery` | Actual metadata probe identities | Existing native/helper probe results at T:2464,2489 | faithful; omission of a Java `otool` probe is intentional |
| `kind` | Declared/derived manifest kind | Existing identity construction at T:2482 | faithful; classifier does not rewrite Java declarations |
| `requires` | Declared dependency IDs | `declaration.requires` at T:2491 | faithful; still does not imply launch context |
| Internal `nativeFileKind` result | Routing classification | `"macho"` includes malformed native candidates requiring inspection | Appropriate for its inspected callers; not serialized as a validity assertion |

No new public field-name mismatch was identified.

## Lens 6 - Deferral justification audit

| Deferred finding | Justification claims | Claim audit | Verdict |
|---|---|---|---|
| CA-26 | Complete Java envelopes avoid native inspection; embedded native members retain precedence | C:158-252 implements these distinctions; TT:1679-1827 covers positive, malformed and ambiguity cases | Closed for the reported mechanism; no new residual finding established |
| CA-24 | Non-system native trees refuse until launch context is reviewed | T:1491-1499 retains unconditional refusal; Verus result agrees | Refusal-only closure preserved |
| Little-endian fat fixtures | Container format is big-endian even when members are little-endian | Confirmed against Apple’s public `include/mach-o/fat.h`; TT:1655-1675 controls container order separately from TT:1641-1653 | Classification justified; malformed refusal must not require a dependency-specific error |
| CA-16 | Root-value analysis remains incomplete | T:1013-1015 retains identifier-based substitution | Accurate open disposition; carried |
| CA-17 | Imported-helper call analysis remains incomplete | T:1005-1018,1067-1068 retain the mechanisms | Accurate open disposition; carried |
| Residual CA-21 | Transitive split-stdlib provenance remains incomplete | Explicit shortcut at T:640-641 | Accurate open disposition; carried |
| Dossier collection/ownership | Isolated repairs do not clear failed evidence or the indeterminate owner | L:618 retains that restriction; correction adds no recovery path | Unchanged; no activation or recovery conclusion |

---

## Finding list (consolidated)

No new finding was established in this correction. The following findings retain their prior IDs and remain carried provenance blockers.

| ID | Lens | Severity | Surface | Intent ref | Code ref | Summary | Fix |
|---|---|---|---|---|---|---|---|
| CA-16 | commitment-coverage | Major | Python loader-helper root, carried | I11, I:25; V4:229,235,249-251 | T:1013-1015 | A same-named root argument is replaced with the project root without establishing its runtime value. Discovery can bind a different target from execution. | Establish the argument value or refuse the helper invocation. |
| CA-17 | commitment-coverage | Major | Imported Python loader helpers, carried | I11, I:25; V4:229,235,249-251 | T:1005-1018,1067-1068 | Defining-file specialization and loss of imported callable identity leave caller-selected targets outside the analysis. | Track specialized imported callable identities and arguments, or refuse their cross-module use and escape. |
| CA-21 | commitment-coverage | Minor | Transitive split-stdlib closure, carried residual | I11, I:25; V4:235,249-251 | T:640-641 | Standard-library resolution still returns without inspecting transitive external-extension selection. | Bind applicable transitive split distributions or refuse affected paths until closure is established. |

## Summary

- Total findings: 3 carried; 0 new.
- By severity: Critical=0 Major=2 Minor=1 Informational=0.
- By lens: commitment-coverage=3 clause-to-line=0 deferred-cannot-silently-succeed=0 who-controls=0 field-name=0 deferral-justification=0.
- CA-26: closed for the reported Java/fat-Mach-O classification defect.
- CA-24: refusal-only closure preserved; compatible Verus discovery remains unavailable.
- Recommended next step:
  1. Retain CA-16/17 and residual CA-21 as open provenance blockers.
  2. Have the main agent perform integrated regression verification, including shared native callers and Linux routing, after all changes land.
  3. Review any root-binding or Verus launch-context extension separately before using it to qualify Dossier evidence.

No verification commands or project changes were performed. Large-file memory behavior remains unexercised.
Generic reuse, canonical collection and activation remain unqualified; the failed Dossier evidence and indeterminate owner remain untouched.