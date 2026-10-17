# Code-adversarial review: Dossier isolated hybrid toolchain union - 2026-10-16

- Operator: fv-code-adversary via OMP task (NOT HybridBase, HybridProof, or the parent orchestrator)
- Code commit reviewed: `2c7bd3c`, caller-declared base `e36b939`
- Intent version reviewed: frontmatter version absent; canonical target is `D/docs/intent.md`, resolved through `D/.fv/dispatch.json`
- Ledger version reviewed: frontmatter timestamp absent; document states `Updated: 2026-10-08`
- Lens pack: evidence provenance, loader/input closure, and installed-tool identity, using all six required crypto/enclave lenses
- Lenses applied: 1 through 6

## Scope and evidence

| Alias | Path |
|---|---|
| D | `/Users/mv/Development/burnt/dossier-wt/evidence-perf` |
| F | `/Users/mv/Development/reliq-fv-wt/evidence-hybrid-union` |
| T | `F/tools/evidence-v4/evidence-v4-toolchain.ts` |
| C | `F/tools/evidence-v4/evidence-v4-toolchain-common.ts` |
| TT | `F/tests/r38_evidence_v4_toolchain_review.py` |
| P | `F/tools/evidence-v4/evidence-v4-toolchain-proof.ts` |
| R | `F/tools/evidence-v4/evidence-v4-run.ts` |
| V4 | `F/docs/execution-evidence-v4.md` |
| CR | `F/.fv/changes/2026-10-14-execution-evidence-v4.md` |

The review inspected T, C, TT, the command-gate callers in R, and the directly connected Quint application checks in P. Canonical intent clauses I11–I14 govern this slice; V4 supplies its detailed producer contract. This report does not discharge Dossier’s protocol implementation or its complete integration ledger.

Commit attribution is caller-provided. Working-tree equality to `2c7bd3c` was not independently checked.

No commands, tests, builds, formatters, edits, or process changes were performed. The parent’s 112 passing integrated tests and temporary-project READY/PASS, one shared dispatch, and portable-checker exit 0 are accepted as reported observations. They do not establish complete loader closure or generic reuse qualification.

The installed producer remains `e36b939`. The reported real Dossier collection stopped ERROR at native ownership; that separate repair is outside this review.

Important uncovered classes include process containment, concurrent mutation and crash recovery, resource exhaustion, upstream cache poisoning, supply-chain authenticity, and proof/model-to-implementation refinement.

## Disposition of the requested fixes

| Surface | Disposition | Evidence and limit |
|---|---|---|
| Base CA-18 | Reported direct-runtime and recognizable hardlink bypasses addressed | T:2430–2487 requires matching Python/Node family declarations; T:1898–1899 rejects Node environment overrides at session creation. TT:492–551 covers direct interpreters and hardlink aliases discoverable through PATH. This is not universal identification of arbitrary renamed/copied interpreters or arbitrary launchers. |
| Base CA-19 | Reported source-format bypass addressed | T:602–603 rejects non-`.py` entries; T:660–661 rejects unsupported explicit loader targets; T:1139–1145 rejects unsupported source origins. Explicitly declared external extension/bytecode inputs remain a separate admitted category. |
| Base CA-20 | Incomplete | Direct opaque-module access and the named stdlib loaders refuse, but opaque values can lose their classification through dictionary construction. See CA-03. |
| Base CA-22 | Reported literal-cwd and symlink cases addressed | T:734–737 uses command cwd; T:1140–1141 rejects symlinked source; T:1185 uses the resolved entry directory. TT:430–453 covers the reported cases. |
| Base CA-23 | Reported explicit hidden-interpreter wrapper addressed | T:482–500 inspects arguments before allowing `otherCommandBound` to skip a context. TT:455–490 covers a bound native launcher carrying the interpreter and script as arguments. This does not model arbitrary launcher internals. |
| Base CA-25 | pnpm configuration case addressed; child-runtime claim incomplete | T:1578–1598 checks pnpm configuration and the pnpm selection probe. The actual preferred Node probe at T:1662 reports only `process.execPath`. See CA-05. |
| Quint family gate | Reported omission/subcommand/wrapper cases addressed | T:2490–2528 identifies the installed package, requires its direct declared CLI and a matching adapter/subcommand. P:349–359 checks actual application contexts. TT:553–614 contains the relevant negative cases. |
| Rustup inode selection | Requested selection correction supported | C:115–123 recognizes a sibling Rustup hardlink by device/inode; T:1308–1325 requires the selector to be the same executable before retaining `rustup which`. T:2300–2337 constructs the derived identity. |
| Indexed file-root alias correction | Supported in both consumers | T:2404–2416 and T:2570–2587 require an exact origin path or matching file-root device/inode, followed by retained file-kind/hash/size/executable equality. A different-path independent copy satisfies neither origin condition. |
| Explicitly open boundaries | Remain OPEN | Base CA-16, CA-17, transitive CA-21, and generic CA-24 are carried below. The frozen review’s whole-pnpm-store finding also remains present. |

---

## Lens 1 - Commitment coverage

| Commitment | Attacker DoFs | Bound by | Gap |
|---|---|---|---|
| Tool content identity | Installed file bytes, sizes, execute bits, virtual paths, package identities, platform/SDK | T:2362–2387; C:338–390 | Discovered files are bound. Completeness remains conditional on discovery. |
| Indexed file-root membership | Alternate pathname, independent copy, hardlink alias, changed contents or permissions | T:1909–1923 records origin inode and manifest; T:2404–2416 and T:2570–2587 compare membership plus content metadata | No additional gap established in the requested correction. Directory roots still require an actual retained entry; hardlink equivalence does not widen directory membership. |
| Python helper root | Runtime value passed as the helper’s root argument | T:977–979 checks the identifier and substitutes `Path(root)` | CA-01, carried Base CA-16. |
| Imported helper targets | Calls and arguments in another module | T:969–982 specializes defining-file calls; T:1020–1021 discards imported callable identity | CA-02, carried Base CA-17. |
| Opaque Python module references | Container/default/alias transport of a `sys.modules` result | Direct accesses guarded at T:772–809 and direct call arguments at T:869–871 | CA-03. The generic expression fallback at T:904–908 omits the new opaque sentinels and can turn a dictionary containing an opaque module into `UNKNOWN`. |
| Python stdlib closure | Transitive standard-library imports selecting external split distributions | T:635 refuses direct `tkinter`/`dbm`; T:646–647 skips transitive stdlib scanning | CA-04, carried transitive Base CA-21. |
| pnpm and selected Node execution | Configuration-injected options, preferred runtime wrapper, preload path and bytes | T:1578–1598 checks pnpm selection; T:1640–1669 accepts and probes the preferred runtime | CA-05. Actual child options are absent from the preferred-runtime probe. |
| Rustup-selected driver | Hardlink spelling, selector substitution, selected compiler bytes | C:115–123; T:1308–1325; T:2300–2337 | No additional gap established for the requested hardlink correction. |
| Producer implementation and probes | Imported producer files, helper executables, changed probe output | T:1829–1890, T:1985–2050, T:2165–2218, T:2612–2628 | Source and exact stream identities are retained. These commitments do not attest operator honesty or prove that an omitted dependency was irrelevant. |

### CA-03: opaque-module classification is lost through a dictionary

A concrete source form is:

`import importlib, sys`

`holder = {"loader": sys.modules["importlib"]}`

`holder["loader"].import_module("external_plugin")`

The subscript produces `OPAQUE_MODULE` at T:796. Dictionary expressions reach T:904–908, whose escape check excludes `OPAQUE_MODULE`, `SYS_MODULES`, and `MODULE_LOOKUP`; the dictionary becomes `UNKNOWN`. The later lookup and call consequently remain unknown instead of refusing or recording `external_plugin`.

[INFERENCE] With `external_plugin` available through an external import path, this permits an unrecorded runtime import. This counterexample was derived statically, not executed. It does not depend on Base CA-16/17, transitive stdlib behavior, or concurrent mutation.

TT:352–377 covers direct access, direct assignment, reflection, and permitted registry bookkeeping. It lacks container/default-argument escape cases.

### CA-05: the actual preferred Node runtime can inject unrecorded options

The admitted fixture already uses a shell wrapper at `node_modules/.bin/node` (TT:1043–1048). Consider the same wrapper with:

`exec /absolute/path/to/node --require /external/hook.cjs "$@"`

T:1640–1644 selects that wrapper. T:1662–1669 probes only `process.execPath`, then binds the resulting Node executable. The earlier `execArgv` check runs under `pnpm exec process.execPath`, before the preferred wrapper is selected. Native inspection binds the wrapper and its shebang interpreter, but does not interpret shell-body Node arguments (T:1463–1485).

[INFERENCE] A quiet preload can run during discovery and evidence execution without its bytes entering the selected closure; the recorded runtime probe can remain identical when those external bytes change. No concurrent mutation is needed: differing stable installations suffice. This counterexample was not executed.

CR:164 therefore overstates the implementation when it says selected child runtime options are checked and retained. TT:1060–1072 tests a synthetic pnpm configuration refusal, not this preferred-runtime path.

## Lens 2 - Clause-to-line discharge

Statuses apply to this producer slice. “Partial” includes obligations whose enforcement lies outside the inspected modules.

| Clause | Expected discharge | Actual code line | Status |
|---|---|---|---|
| D I11, `docs/intent.md:25`: complete tool provenance; unsupported closure prevents PASS | Discover applicable inputs or refuse | T:2390–2421 validates emitted requirements, but cannot recover omitted requirements | gap: CA-01 through CA-06 |
| D I11: endpoint drift checks under explicit operational assumptions | Recompute content and selection identities | T:2605–2633; C:338–390 | discharged for discovered inputs; closure remains partial |
| D I12, `docs/intent.md:32`: exact command/cwd and complete dependency coverage | Gate every preflight, checker, and evidence command | R:508–526; T:2430–2590 | partial: gate is connected; identified loader omissions remain |
| D I12: all slots, observations, ownership and failure barriers survive sharing | Preserve downstream execution/store obligations | R:513–526 materializes each physical descriptor | partial: complete store/ownership semantics are outside this slice |
| D I13, `docs/intent.md:33`: no activation upgrade | Tool admission cannot discharge activation | No activation authority is introduced in T/C | partial: full activation checker not re-audited |
| D I14, `docs/intent.md:34`: no expanded deployment authority | Discovery remains within producer scope | T:1985–2050 executes bounded discovery probes | discharged within the reviewed surface |
| V4:227: derived Rustup/native identities | Retain selected file, approved derived roots and successful selector probe | T:1308–1325, T:2300–2337 | discharged for inspected hardlink selection |
| V4:229,235: Python loader refusal and external-package closure | Unknown loader dependencies refuse | T:633–647, T:754–908, T:933–1145 | gap: CA-01 through CA-04 |
| V4:229,241: effective Node runtime closure | Refuse unmodeled options and bind actual selected runtime | T:1578–1669 | partial: CA-05 |
| V4:236,249: Quint family/backend coverage | Direct CLI and matching subcommand adapter | T:2490–2528; P:328–359 | discharged for the inspected gate |
| V4:231,241: no whole-store enumeration | Capture selected package/search-path closure only | T:1682–1694 adds the entire virtual store | gap: CA-07, carried frozen-review CA-02 |
| V4:243: retain exact probes and revalidate selection | Successful bounded probes and exact identity comparison | T:1985–2050, T:2612–2628 | discharged within inspected paths |
| V4:245,249,251: non-system native dependencies | Discover applicable native dependencies for every admitted declaration kind | T:2289–2296 skips Darwin non-adapter trees | gap: CA-06, carried Base CA-24 |
| V4 S1/S2 | Complete membership and immutable ownership | Descriptor handoff at R:513–526 | partial; store implementation outside scope |
| V4 B1/B2 | Real completed work and complete admissible provenance | Command gate at R:508–516; closure validation at T:2390–2421 | partial; closure gaps prevent a general qualification conclusion |
| V4 T1/T2 | Stop on failure, preserve ownership, reject endpoint drift | T:2612–2628 rejects discovered drift | partial; scheduling/ownership not re-audited |
| Ledger C-01 through C-09 | Preserve bounded/projection limitations | Producer identity/gate changes do not provide model-to-code bridges | partial; all candidate conjunctions remain INCOMPLETE |
| Ledger C-10 through C-15 | Preserve SDK, runtime, receipt and replay boundaries | No discharge in T/C; selected local evidence does not establish full runtime or historical-chain provenance | partial; unchanged |
| Ledger TA-07/TA-08 | Preserve host-evidence and operator-honesty limits | Local hashes/probes at T:1985–2050, T:2362–2387 | partial; no independent attestation of operator honesty |
| Ledger TA-01–TA-06 and TA-09–TA-17 | Preserve external platform, custody, chain, release and clock assumptions | No discharge in the target modules | partial; outside this slice and unchanged |
| V4:163–165 operational/cache/store premises | No assumption that endpoint equality proves continuous immutability, cache correctness, or complete discovery | C:338–390 and T:2605–2633 implement endpoint-oriented checks | partial by design; no new premise is established by hardlink acceptance |

## Lens 3 - Deferred cannot silently succeed

| Branch | Reachable from | Behavior | Status |
|---|---|---|---|
| Root-by-name helper specialization | Python source discovery | Substitutes project root without establishing argument value | gap: carried CA-01 |
| Imported specialized helper | Python imports and subsequent calls | Callable identity becomes unknown; additional target arguments are not discharged | gap: carried CA-02 |
| Generic expression fallback containing opaque module values | Python dictionary expressions | Returns unknown instead of refusing the escape | gap: CA-03 |
| Transitive stdlib shortcut | Python import resolution | Returns without scanning transitive imports | gap: carried CA-04 |
| Darwin non-adapter tree shortcut | Ordinary `tree` declarations | Hashes tree without discovering external native linkage | gap: carried CA-06 |
| Unsupported Python entry/explicit loader formats | Direct entry and static loader discovery | Throws | explicit refusal for the reviewed cases |
| Explicit interpreter hidden in bound launcher argv | Python command-context discovery | Throws before `otherCommandBound` can skip it | explicit refusal for the reviewed case |
| `deferred` function-body worklist | Python function analysis | Worklist is drained at T:1125–1136 | Not an implementation stub; remaining analysis gaps are identified separately |
| Other TODO/stub/mock/not-implemented branches | T and C text search | No additional explicit placeholder-success branch found | No additional finding; this does not establish complete closure |

The comments at T:943 and T:2289 describe the open boundaries in reuse terms. Their effects also apply to fresh provenance. Disabling resume does not turn an undiscovered input into an attested input.

## Lens 4 - Who controls

| Field | Supplier | Validation | Gap |
|---|---|---|---|
| Declaration IDs, locators, `requires` | Reviewed policy | T:1930–1947 resolves an acyclic closure; T:2259–2287 validates selected root kind | Cannot compensate for omitted runtime dependencies |
| Command argv/cwd | Reviewed policy | R:508–516 calls the gate for every check and physical recipe; T:2430–2559 checks recognized families | Reported family omissions tightened; arbitrary launcher semantics remain outside this gate |
| `origins[].base`, `.inode`, `.directory`, `.exclude` | Producer filesystem observations and root descriptors | T:1909–1923; consumers at T:2404–2416 and T:2570–2587 | No additional gap established in indexed alias membership |
| `fileMaps` | Hashed manifest | Exact regular-file entry and content metadata equality at both consumers | No hash-only acceptance of a different-path independent copy |
| Python module objects and loader arguments | Project/installed Python source | Abstract interpreter and refusal checks | CA-01 through CA-04 |
| pnpm configuration | Project/user package-manager configuration | T:1578–1598 queries effective configuration and selection | Reported configuration case addressed; actual wrapper-injected runtime options remain CA-05 |
| Preferred `node` executable | Installed `.bin` contents | Executability/file check, wrapper hash, executable-only probe | CA-05 |
| Discovery stdout/stderr | Selected approved tools | Bounded successful invocation and exact hashes at T:1985–2050 | Relies on tool/operator honesty; no filtering introduced |
| Acceptance digest pins | Policy author | T:2377–2381 | Empty pins record installed identity without authenticating a release |
| Cache namespaces and trust labels | Adapter discovery and reviewed policy | T:2657–2703 canonicalizes selections and rejects conflicting roles | Upstream cache integrity remains assumed; no fresh-compilation claim |

## Lens 5 - Field-name fidelity

| Field | Implied semantic | Actual value | Status |
|---|---|---|---|
| `ToolIdentity.digest` | Content identity of recorded tool manifest | `D("tool-content", {kind, files, packages, system_dependencies})`, T:2376 | faithful; incomplete discovery is a separate defect |
| `discovery[].command/cwd` | Actual probe invocation and cwd | T:2042–2049 | faithful |
| `stdout_hash` / `stderr_hash` | Exact captured streams | T:2045–2046 | faithful; no normalization added |
| `origins[].inode` | Device/inode identity for local membership | BigInt stat pair at T:1912–1917 | faithful; internal state, not portable content identity |
| `native/drivers/cargo-0` / `rustc-0` | Driver selected by retained Rustup lookup | T:1320–1327 and T:2327–2337 | faithful for inspected selection path |
| `resolved_path`, `resolved_hash`, `resolved_size` | Canonical manifest target and its recorded content | C:481–550 | faithful in inspected implementation |
| `execution/node-runtime` | Runtime executable reported by selected Node | T:1662–1671 | faithful as an executable field; it does not claim or encode effective startup options |
| `execution/node-store/<index>` | Captured virtual-store view | Entire store root at T:1691 | Accurate name; prohibited capture breadth is CA-07 |
| `BuildCacheIdentity.integrity` | Declared upstream integrity premise | Literal `upstream-build-system`, T:2702 | faithful assumption label |

No separate field-name finding was established. CR:164 is an overstatement of checked behavior, addressed under CA-05 and lens 6.

## Lens 6 - Deferral justification audit

| Deferred finding | Justification claims | Claim audit | Verdict |
|---|---|---|---|
| Base CA-16/17 | Root-value and cross-module analysis remain incomplete | T:969–979 and T:1020–1021 retain the mechanisms | OPEN; accurate disposition. Carry CA-01/02 without presenting them as new discoveries |
| Base CA-18/19 | Family gates and source-format refusals address reported bypasses | T:602–603, T:1139–1145, T:2430–2487; TT:330–350,492–551 | Supported for reported cases; no universal interpreter-identification claim |
| Base CA-20 | Reported direct opaque and stdlib forms refuse; no general interpreter analysis claimed | Direct cases refuse, but new opaque values are missing from existing escape checks | Incomplete closure; CA-03 is a newly identified residual of the existing finding |
| Base CA-21 | Startup-hook imports use request paths; direct split imports refuse; transitive paths stay open | T:635,646–647,1153–1157,1177–1185 | Accurate partial disposition; CA-04 remains OPEN |
| Base CA-22/23 | Literal cwd, symlinked source, and explicit hidden-interpreter wrapper contexts handled | T:482–500,734–737,1140–1141; TT:430–490 | Supported for reported cases |
| Base CA-24 | Generic Darwin tree linkage remains open | T:2289–2296 still omits discovery for that kind | OPEN; CA-06. No-resume and frozen-installation observations do not close the generic defect |
| Base CA-25 | Effective pnpm and selected child runtime options checked and retained | First claim supported by T:1578–1598; second contradicted by the executable-only probe at T:1662 | Partial implementation claim is overstated; CA-05 |
| Frozen review CA-02 | Whole pnpm store capture remains an excessive-capture defect | T:1691 still registers the entire store; C:452–464 recursively traverses it | OPEN; CA-07, not a new discovery |
| Indexed-origin correction | File-root aliases require device/inode and retained content metadata; independent copies refuse | Both consumers implement those checks; TT:1587–1600 tests alias acceptance and independent-copy rejection | Supported within the existing nonmutation premise |
| Integrated test/smoke results | Isolated integration exercised; generic reuse and activation remain unqualified | CR:170 states these limits; parent reports the same boundary | Accurate limited evidence claim |

### Nonmutation-premise assessment

No unsafe widening was established in the indexed-origin correction itself:

- File-root alias eligibility uses the captured device/inode pair.
- Both consumers additionally require retained hash, size, executable bit, and regular-file kind.
- File hashing still checks inode and metadata stamps, including change times, before and after reads.
- Revalidation still compares content and exact discovery identities.

These checks do not provide a continuous immutable filesystem view, and they do not claim one. The counterexamples in CA-03 and CA-05 require no concurrent writer. Treating them, or carried CA-01/02/04/06, as harmless under `no_concurrent_mutation` would expand that premise into an unsupported assumption of complete dependency discovery.

---

## Finding list (consolidated)

IDs are local to this report. Prior IDs remain attached to avoid rediscovery or accidental closure. Counts use each finding’s primary lens.

| ID | Lens | Severity | Surface | Intent ref | Code ref | Summary | Fix |
|---|---|---|---|---|---|---|---|
| CA-01 | commitment-coverage | Major | Python loader-helper root | D I11; V4:229,235,249,251 | T:969–979 | OPEN, carried Base CA-16. A same-named root argument is replaced with the project root without establishing its runtime value. The analyzer can bind a different loader target from the execution. | Establish the root argument’s value or refuse the helper invocation. Preserve this as an explicit fresh-provenance blocker where applicable. |
| CA-02 | commitment-coverage | Major | Imported Python loader helpers | D I11; V4:229,235,249,251 | T:969–982,1020–1021,867–908 | OPEN, carried Base CA-17. Specialization covers defining-file calls; imported helpers become unknown, so additional caller-selected targets can escape analysis. | Retain imported helper identity and validate arguments, or refuse imported specialized-helper calls/escapes. |
| CA-03 | commitment-coverage | Minor | Opaque Python module escape | D I11; V4:229,235,251 | T:796,904–908,1022–1028; TT:352–377 | Incomplete Base CA-20 fix. `{"loader": sys.modules["importlib"]}` becomes unknown because the fallback escape check omits the new opaque sentinels. A subsequent `import_module` call is neither rejected nor bound. Static counterexample; not executed. | Extend existing escape/default/container checks to the new sentinels, or preserve their classification through supported containers. Add the dictionary counterexample while retaining permitted registry bookkeeping. |
| CA-04 | commitment-coverage | Minor | Transitive split-stdlib closure | D I11; V4:235,249,251 | T:633–647 | OPEN, carried transitive Base CA-21. Direct split imports refuse, but standard-library modules still short-circuit without examining transitive external-extension dependencies. | Bind the applicable transitive split distributions or refuse the relevant entry paths until their closure is established. |
| CA-05 | commitment-coverage | Minor | Preferred Node runtime options | D I11; V4:229,241,249,251; CR:164 | T:1582–1598,1640–1669,1463–1485; TT:1043–1048,1060–1095 | Incomplete Base CA-25 boundary and newly identified residual counterexample. pnpm’s probe checks one process; the selected preferred Node wrapper can inject `--require` or `NODE_OPTIONS`, while its own probe reports only the executable. External preload bytes can remain unbound. Static counterexample; not executed. | Refuse unmodeled preferred-runtime wrappers or admit only a reviewed wrapper form whose effective options are checked. Validate the actual selected runtime’s effective options and add a wrapper-preload negative regression. Correct CR:164’s closure claim. |
| CA-06 | clause-to-line | Minor | Darwin non-adapter trees | D I11; V4:245,249,251 | T:2289–2296 | OPEN, carried Base CA-24 and frozen-review CA-01. Darwin tree declarations do not discover native children’s external linkage. This review does not establish exposure in D’s exact installed tree. | Discover native children in their actual launch contexts, emit required external dependencies, or refuse unsupported trees. Keep generic qualification open. |
| CA-07 | clause-to-line | Minor | pnpm virtual-store capture | D I11; V4:231,241 | T:1682–1694; C:452–464; TT:1097–1147 | OPEN, carried frozen-review CA-02. One selected NODE_PATH entry registers and recursively hashes the entire pnpm store, including unrelated packages. Demonstrated mechanism is excessive capture and possible false refusal, not false PASS. | Retain the store as an escape boundary while registering only selected canonical targets. Add an unrelated-store-change exclusion regression. |

## Summary

- Total findings: 7, comprising 2 incomplete claimed fixes with newly identified residual counterexamples and 5 explicitly carried findings.
- By severity: Critical=0 Major=2 Minor=5 Informational=0.
- By lens: commitment-coverage=5 clause-to-line=2 deferred-cannot-silently-succeed=0 who-controls=0 field-name=0 deferral-justification=0.
- Requested integration correction: both indexed-origin consumers retain device/inode-qualified file-root aliasing plus hash/size/executable equality. No independent-copy acceptance or new nonmutation-premise widening was established.
- Recommended next step:
  1. Keep Base CA-16/17 and transitive CA-21/generic CA-24 OPEN; do not qualify affected fresh provenance from no-resume or READY.
  2. Patch opaque-module escape handling and preferred-runtime Node option handling, with the focused negative regressions above.
  3. Correct the child-runtime closure statement and the comments that frame discovery omissions only as reuse limitations.
  4. Address whole-store enumeration separately.
  5. Have the parent run the affected suites and renew Dossier admission after the separate native-ownership repair. Preserve the distinction between isolated smoke evidence, installed lineage, full collection, generic reuse, and activation.

Not checked: independent commit/install equality, execution of the new counterexamples, real-pnpm configuration semantics, or D’s exact transitive Python/native dependency inventory.
Risk: stable, fresh execution can still have incomplete provenance; endpoint equality and passing integration tests do not close omitted-input paths.