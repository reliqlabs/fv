# Code-adversarial review: Dossier external FV Darwin tree closure - 2026-10-16

- Operator: fv-code-adversary via OMP task (NOT CloseDarwinTreeClosure or parent)
- Code commit reviewed: `63c3648`; declared base `e341cce`
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
| Results | `/private/var/folders/ph/n581g1fj3tnbq8n74hp05klc0000gn/T/fv-darwin-tree-selection-tm_8xph3` |

The corrected assignment explicitly authorizes this cross-project review: F supplies the external evidence producer used by D’s I11/I12 provenance contract. V4 is the detailed implementation contract, not the canonical intent.

The inspected delta covers ordinary Darwin tree discovery, its shared native inspection dependencies, existing callers, regression cases and documentation. Commit attribution is caller-provided; working-tree equality to the declared commit was not independently established.

The parent reports three targeted methods passing after replacing protected-flag-preserving fixture copying with byte/mode copying. That infrastructure failure was not rerun or treated as a production failure.

The retained results were inspected:

- `go-distribution.json`: `ok: true`; the Go identity contains 12,362 entries and 17 discovery records.
- `quint-package.json`: `ok: true`; the Quint identity contains 4,998 entries and no discovery probes.
- `verus-distribution.json`: `ok: false`, refusing `rust_verify`’s `@rpath/librustc_driver-e03ed1db822dfa4c.dylib`.

These are retained selection observations. They do not establish a completed evidence collection, generic reuse, or activation.

Important uncovered classes include process containment, concurrency and crash recovery, resource exhaustion, access control, upstream-cache poisoning, supply-chain authenticity, and proof-to-implementation refinement.

## Delta disposition

| Surface | Disposition | Evidence |
|---|---|---|
| Base CA-24’s omitted non-system dylib edges | Addressed by refusal for the reported mechanism | T:2424-2429 enumerates tree payloads; T:1498-1513 rejects every parsed dependency outside the absolute vendor-system namespace. |
| Inferred process image or inherited rpaths | No such inference in the new tree path | The call supplies no subjects and uses `unboundPayloads`; that branch never resolves `@rpath`, `@loader_path`, or `@executable_path`. |
| Separately declared library or sysroot | Cannot override refusal | The rejection does not consult `requires`; TT:1609-1685 includes a separately declared matching library. |
| Native-free trees | New compatibility defect | Four-byte format classification confuses Java class files with fat Mach-O. CA-26. |
| System-only native trees | Supported under the declared vendor-integrity assumption | T:1508-1513; TT:1688-1739; retained Go result. |
| Verus rollout compatibility | Not delivered | Retained Verus selection refuses. A launch-context adapter remains absent. |
| Linux behavior | No new tree-refusal route reaches Linux | T:2431-2435 continues through `linuxLinkage`; existing native-adapter callers omit `unboundPayloads`. No Linux execution was performed. |

---

## Lens 1 - Commitment coverage

| Commitment | Attacker DoFs | Bound by | Gap |
|---|---|---|---|
| Ordinary tree content identity | File bytes, names, execute bits, directory membership and aliases | C:382-510 constructs the manifest; T:2502-2513 hashes files, packages and system dependencies | No new omission established in tree hashing. |
| Darwin native dependency closure | Install names, load-command kinds, rpaths and child launch context | C:139-165 extracts dependency-bearing dylib commands; T:1498-1513 refuses non-system dependencies | Base CA-24’s reported external-library omission is addressed through refusal. No supported non-system launch context is claimed. |
| Vendor-system exception | Absolute versus relative spelling, `..` traversal, prefix lookalikes | T:1509-1511 requires an absolute path and tests normalized `/usr/lib/` or `/System/Library/` prefixes | Lexical traversal outside these prefixes refuses. Actual vendor contents remain trusted under V4:245; this is not an independent OS-byte proof. |
| Discovery provenance | Selected `otool`/`xcrun`, executable bytes and probe output | T:1461-1495, 2198-2215, 2285-2292, 2487-2502 | Although the tree branch retains its original roots, helper tracking subsequently adds discovery-helper closure. No new helper-byte omission established. |
| Endpoint identity | Changes to retained files or discovery results | T:2747-2777 reconstructs identities and compares content and selection digests | Enforces detected endpoint drift only. Concurrent mutation and restored-between-checks edits remain excluded by I11/V4 assumptions. |
| Python helper root | Runtime argument supplied under the expected identifier | T:1020-1022 substitutes the project root after checking the argument’s name | Carried CA-16 remains open. |
| Imported Python helper targets | Calls and arguments outside the defining module | T:1012-1025 specializes defining-file references; T:1074-1075 discards imported callable identity | Carried CA-17 remains open. |
| Transitive split-stdlib dependencies | Indirect selection of external Python extension distributions | T:647-648 returns without transitive scanning | Carried residual CA-21 remains open. |

## Lens 2 - Clause-to-line discharge

| Clause | Expected discharge | Actual code line | Status |
|---|---|---|---|
| I11, I:25 | Complete tool/environment provenance; unsupported closure prevents PASS | T:2424-2429 and 1498-1513 | discharged for CA-24’s reported non-system tree load edges; partial overall because carried provenance gaps remain |
| I12, I:32, complete declared dependency closure | Tree membership or another declared dependency cannot manufacture launch semantics | T:1508-1513; no `requires` lookup in this branch | discharged for the new refusal boundary |
| I12, exact recipes and observations | Do not change command semantics to make Verus capture succeed | Tree scan invokes metadata discovery, not child executables, at T:1486; TT:1725-1739 checks this | discharged within the inspected delta; execution/observation machinery is outside scope |
| I13/I14, I:33-34 | Keep selection evidence separate from activation and operational authority | Identity construction returns provenance at T:2517-2529; CR:224 retains the Verus limitation | partial: this module grants no deployment authority; activation gates were not re-audited |
| V4:9; documented native-free support at `F/scripts/README.md:214-219` | Preserve ordinary non-native tree contents without treating them as unsupported native executables | T:261,276,1506-1508,2424-2427 | gap: CA-26 |
| V4:217-223, alias semantics | Preserve aliases, require canonical retained targets and reject escapes/cycles | C:430-449,480-510,519-526 | discharged for inspected manifest handling; native scanning skips aliases while ordinary canonical targets are traversed |
| V4:229, unsupported loader configuration | Reject ambient loader overrides and embedded `LC_DYLD_ENVIRONMENT` | T:1336-1338,1351; C:154 | discharged for these named forms |
| V4:225, discovery failure | Nonzero or abnormal metadata probes must fail preflight | T:2137-2173 | discharged |
| V4:243, discovery retention and revalidation | Keep exact probe identities and recheck selection | T:1485-1489,2501,2747-2777 | discharged within inspected paths |
| V4:245, vendor-integrity boundary | Bind actual platform identity while limiting the system-library exception | T:1509-1511,2506-2510 | discharged under the stated OS/vendor assumption |
| V4:249-251, incomplete closure | Missing non-system closure cannot silently produce an identity | T:1513 | discharged for the specified tree load-command surface |
| V4 S1/S2/B1/B2/T1/T2, V4:15-20 | Preserve membership, execution ownership, failure history and endpoint obligations | T:2733-2777 supplies capture/revalidation; scheduling/store enforcement is outside this delta | partial; no full invariant discharge claimed |
| L:461-462, TA-07/TA-08 | Do not turn local observations into reproducibility or operator-honesty proof | T:2517-2529 records identities; no evidence-signing or independent-host mechanism is added | partial; external assumptions remain |
| L:618, failed collection and indeterminate ownership | Repairs must not promote failed evidence or clear ownership | New code is confined to discovery/identity construction | partial; ownership was neither changed nor exercised |

The remaining protocol clauses, C-01 through C-15 composition claims, and unrelated trust assumptions are outside this bounded delta. This review does not discharge them.

### CA-26: Java class files are classified as native Mach-O payloads

`nativePayloads` accepts any regular file whose first four bytes occur in `MACHO_MAGIC` (T:248-261). That list includes `0xcafebabe` (T:276). The new ordinary-tree path then sends every such file through Mach-O load-command discovery (T:2424-2427,1506-1508).

The [Java Virtual Machine Specification §4.1](https://docs.oracle.com/javase/specs/jvms/se25/html/jvms-4.html#jvms-4.1) defines exactly the same `0xCAFEBABE` prefix for Java class files. File execute permission and suffix do not distinguish this path.

[INFERENCE, not executed] A native-free ordinary tree containing a small valid Java `.class` file is sent to `otool -l` and rejected as invalid Mach-O or as lacking load-command metadata. The failure follows through T:2137-2173 or C:148. This broadens refusal beyond the requested non-system native edges and contradicts the documented preservation of native-free trees.

The correction belongs in shared format discrimination. Validate enough structure to distinguish fat Mach-O from Java class data, without using a filename exclusion that could hide a native image. Keep malformed actual native images fail-closed. Add a native-free Java-class tree case alongside valid fat Mach-O and malformed-native cases.

## Lens 3 - Deferred cannot silently succeed

| Branch | Reachable from | Behavior | Status |
|---|---|---|---|
| Unbound non-system dependency | Ordinary Darwin tree identity | Throws `Unbound native tree launch context` at T:1513 | explicit refusal; no deferred-success result |
| Missing or malformed metadata fields | `readLoadCommands` | C:148 rejects absent blocks; C:153 rejects absent command type; C:157/161 reject absent rpath/load name | explicit refusal for these forms |
| Embedded loader environment | Any inspected Mach-O metadata | C:154 throws | explicit refusal |
| Failed metadata subprocess | Production `context.probe` | T:2137-2173 throws on error, nonzero exit, signal, timeout or cancellation | explicit refusal |
| Dylib self-identification | `LC_ID_DYLIB` in metadata | C:139-165 does not treat the image’s own install name as a dependency | correct distinction; not deferred work |
| Child rpath handling in ordinary trees | `unboundPayloads` | Rpaths are parsed for metadata validity but never used to resolve a non-system dependency | explicit refusal instead of invented launch semantics |
| Native-free files and aliases | `nativePayloads` | Ordinary nonmagic files and symlinks are skipped, then retained/validated by the manifest | intentional data handling; CA-26 affects classification |
| Transitive Python stdlib shortcut | Existing Python discovery | T:647-648 silently omits transitive analysis | carried CA-21; outside the Darwin correction |
| New TODO/stub/mock implementation branches | Changed native inspection surface | None identified | empty labeled-stub surface; this does not establish parser completeness |

Malformed metadata was assessed statically. The available regressions include `LC_DYLD_ENVIRONMENT` refusal, but do not establish exhaustive malformed-header, universal-binary, or load-command parser coverage.

## Lens 4 - Who controls

| Field | Supplier | Validation | Gap |
|---|---|---|---|
| Declaration `kind`, locator and `requires` | Reviewed project policy | T:2353-2357,2399-2423 resolves the locator and checks file/directory kind; dependency closure detects unknown IDs/cycles at T:2070-2084 | No new policy-controlled bypass established |
| Tree entry bytes, paths and aliases | Installed distribution/filesystem | C:382-510 hashes regular files and requires retained canonical alias targets | No new alias bypass established |
| `unboundPayloads` | Internal tree scanner | Only production assignment found is T:2427; C:19 adds an internal option, not a public policy field | Format discrimination defect CA-26; no new public authority field |
| Install names and rpaths | Native image author | C:146-165 parses; T:1509-1513 restricts dependencies | Non-system edges refuse regardless of `requires` |
| Discovery helper selection | Sanitized PATH/developer-tool selection | T:1461-1478 resolves and records helpers; helper closure binds their bytes | Operator/tool authenticity remains an external trust assumption |
| `system_dependencies` | Producer runtime and selected SDK | T:1631-1649 validates SDK metadata; T:2506-2510 records platform fields | No new field-control gap established |
| `digest`, `files`, `discovery` | Deterministic producer computation and successful probes | T:2501-2527; C:345-379 | No new mutable-state schema or unchecked supplied digest introduced |

## Lens 5 - Field-name fidelity

| Field | Implied semantic | Actual value | Status |
|---|---|---|---|
| `ToolIdentity.kind` | Kind of retained identity | Ordinary tree remains `tree`, T:2361,2423-2429,2519 | faithful |
| `files` | Complete retained virtual manifest | `hasher.roots(roots)` includes the declared tree and discovery-helper roots, T:2487-2502 | faithful within the existing manifest contract |
| `digest` | Content identity | Domain-separated hash of kind, files, packages and system dependencies, T:2513 | faithful |
| `discovery` | Actual discovery command/result identities | Metadata and helper probes, T:1486-1487,2501,2526 | faithful; probes are not evidence executions |
| `system_dependencies.sdk.settings_hash` | Hash of selected SDK settings bytes | T:1649 | faithful; does not claim complete SDK hashing |
| `requires` | Declared tool dependency IDs | `declaration.requires`, T:2528 | faithful; explicitly not a child launch context |
| Symlink `target` / `resolved_path` / `resolved_hash` | Literal link and retained canonical target identity | C:430-449,489-507 | faithful in inspected construction |

No new externally serialized field-name mismatch was identified. CA-26 concerns format classification, not public field naming.

## Lens 6 - Deferral justification audit

| Deferred finding | Justification claims | Claim audit | Verdict |
|---|---|---|---|
| Base CA-24 | Non-system tree linkage is addressed by refusal; `requires` does not establish launch context | T:1498-1513 and 2424-2429 support both claims. Retained Verus result shows the expected refusal | Reported omission addressed by refusal only; no compatible Verus closure delivered |
| Base CA-16 | Root-value analysis remains incomplete | T:1020-1022 still substitutes by identifier | Accurate open disposition; carried |
| Base CA-17 | Imported-helper call analysis remains incomplete | T:1012-1025,1074-1075 retain the mechanisms | Accurate open disposition; carried |
| Residual Base CA-21 | Transitive split-stdlib closure remains open for fresh provenance and reuse | T:647-648 explicitly retains that shortcut | Accurate open disposition; carried |
| Native-free compatibility statement | Native-free trees remain supported | `F/scripts/README.md:214-215` conflicts with the magic collision described above | CA-26; this is a new compatibility defect, not a wrong-deferral finding |
| D’s failed collection | Isolated repairs do not clear the original owner or promote failed evidence | L:618 expressly retains those restrictions; this delta does not modify ownership | Disposition preserved; no recovery or activation conclusion |

---

## Finding list (consolidated)

Existing base finding IDs retain their meanings. CA-26 is new in this review.

| ID | Lens | Severity | Surface | Intent ref | Code ref | Summary | Fix |
|---|---|---|---|---|---|---|---|
| CA-16 | commitment-coverage | Major | Python loader-helper root, carried | I11, I:25; V4:229,235,249-251 | T:1020-1022 | OPEN, carried. A same-named root argument is replaced with the project root without establishing its runtime value. The discovered loader target can differ from execution. | Establish the argument’s value or refuse the helper invocation. Retain the fresh-provenance restriction until corrected. |
| CA-17 | commitment-coverage | Major | Imported Python loader helpers, carried | I11, I:25; V4:229,235,249-251 | T:1012-1025,1074-1075,909-939 | OPEN, carried. Specialization covers defining-file references; imported helper identities become unknown, allowing caller-selected targets to escape that analysis. | Track specialized imported callable identities and arguments, or refuse their cross-module use and escape. |
| CA-21 | commitment-coverage | Minor | Transitive split-stdlib closure, carried residual | I11, I:25; V4:235,249-251 | T:647-648 | OPEN, carried residual. Standard-library resolution returns without inspecting transitive external-extension selection. Direct split-import refusals do not close that boundary. | Bind applicable transitive split distributions or refuse affected paths until closure is established. |
| CA-26 | clause-to-line | Minor | Ordinary Darwin tree format detection, new | I11/I12, I:25,32; V4:9,217-225; `F/scripts/README.md:214-219` | T:248-261,276,1506-1508,2424-2427; C:148 | Java class files share `CAFEBABE` with fat Mach-O and are unconditionally routed to native metadata discovery. [INFERENCE, unexecuted] A native-free Java-class tree now fails capture despite the preserved-support claim. This is false refusal, not false PASS. | Add shared structural format discrimination; retain fail-closed handling for malformed actual native images. Add Java-class, valid fat-Mach-O and malformed-native regression cases. |

## Summary

- Total findings: 4, comprising 1 new finding and 3 carried findings.
- By severity: Critical=0 Major=2 Minor=2 Informational=0.
- By lens: commitment-coverage=3 clause-to-line=1 deferred-cannot-silently-succeed=0 who-controls=0 field-name=0 deferral-justification=0.
- CA-24 disposition: the reported omitted non-system dylib closure is addressed through refusal. This does not establish Dossier rollout compatibility.
- Recommended next step:
  1. Keep CA-16/17 and residual CA-21 open as provenance blockers; correct their analysis or refuse affected forms before qualification.
  2. Correct CA-26’s shared native-format discrimination and add focused regression cases.
  3. Have the main agent run the resulting Darwin regression set and Linux compatibility checks after integration. Keep any Verus launch-context adapter as a separately reviewed change.

No commands, tests, builds, formatters, project edits, private configuration reads, or ownership changes were performed.
Generic reuse, canonical collection and activation remain unqualified; Dossier’s failed evidence and indeterminate owner remain untouched.