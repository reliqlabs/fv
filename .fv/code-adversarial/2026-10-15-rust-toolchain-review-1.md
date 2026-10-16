# Code-adversarial review: dossier evidence-v4 Rust toolchain adapter - 2026-10-15

- Operator: fv-code-adversary via OMP task (NOT V4RustToolchains)
- Code commit reviewed: `aa6946f29f6bc893cba62d58ef99efdc6d5a8716`; Dossier consumer commit supplied: `1fc3294437c294b040bc606aaa177334b8e41b8c`
- Intent version reviewed: absent from frontmatter. Canonical target is `D/docs/intent.md`, resolved through `D/.fv/dispatch.json`; relevant evidence revision is dated 2026-10-14.
- Ledger version reviewed: frontmatter timestamp absent; body reports `Updated: 2026-10-08` and a 2026-10-12 integration-adoption note.
- Lens pack: crypto/enclave six-lens baseline, supplemented by tool/input provenance and bounded-parser/dataflow lenses
- Lenses applied: 1 through 6, then supplemental lenses 7 and 8

## Scope and evidence limits

Path abbreviations used throughout this report:

- `D` = `/Users/mv/Development/burnt/dossier-wt/evidence-perf`
- `F` = `/Users/mv/Development/reliq-fv-wt/evidence-perf`
- `R` = `F/tools/evidence-v4/evidence-v4-toolchain-rust.ts`
- `T` = `F/tools/evidence-v4/evidence-v4-toolchain.ts`
- `V4` = `F/docs/execution-evidence-v4.md`

The canonical intent is Dossier's intent. `V4` is its supplied normative dependency contract, not a substitute canonical intent. The caller supplied its SHA-256 as `825a053c2d3ba511a5f32f03168239fa24d5221195cb238865a9a1dc2ba7c0e2`; this review did not recompute that digest or use Git to establish checkout identity.

Primary inspection covered the complete Rust adapter, its adapter interface, native-driver discovery, probe/revalidation boundary, package-policy consumer checks, and relevant prior dispositions. Findings concern admitted tool/input closure, including accepted selectors beyond the currently reported Dossier contexts. No finding asserts that the parent-reported 20 Rust captures exercised these counterexamples.

This was read-only static inspection. No tests, builds, gates, formatters, shell commands, Git commands, discovery probes, or live operations ran. Counterexample outcomes marked `[INFERENCE]` are deductions from the cited control flow, not reproduced executions. Parent-reported test results and READY planning remain scoped context. They do not supply fresh canonical Dossier evidence or establish completeness.

The accepted premises remain unchanged: conforming owned child lifecycle; no concurrent external mutation or ABA guarantee; upstream generated-cache integrity; complete trusted retained history; producer/operator, OS and compiler authenticity. None excuses omitting an actual input from the selected closure. The counterexamples below can change an external input between producer invocations and keep it stable throughout each invocation, so they do not require violating the nonmutation premise.

Important uncovered classes include protocol authorization, arithmetic safety, reentrancy, resource exhaustion, crash/error atomicity, migration, and distribution authenticity. Native lifecycle, immutable-store/history correctness, member observations, dashboard behavior and production activation are separate boundaries, not discharged here. Agent separation does not establish served-route or provider-family independence.

---

## Lens 1 - Commitment coverage

| Commitment | Attacker DoFs | Bound by | Gap |
|---|---|---|---|
| Source-qualified package root | Package name/version, registry URL/checksum, Git URL/revision, path location | Exact metadata/lock matching and `D("cargo-package", identity)` at `R:625-655,765-779`; installed file roots enter `D("tool-content", ...)` at `T:1260-1272` | No source-label collision identified. Installed-content enumeration remains distinct from archive or upstream authenticity. |
| Selected Rust sysroot | Stable `RUSTFLAGS` selecting an external sysroot; contents of that sysroot | `R:533,1717-1728` binds the compiler's default queried sysroot; flag processing at `R:1309-1342` does not resolve or reject `--sysroot` | CA-01: selected distribution libraries can be outside the commitment. |
| Selected application package set | Singular example/test/benchmark selectors and their dev-only dependencies | `R:345-350` accepts singular selectors; `R:733-737` includes dev edges only for test/bench operations or plural selectors | CA-02: accepted commands such as `cargo build --example demo` omit consumed dev-dependency roots. |
| Native compile/link inputs | External header, archive, object or linker-script contents at unchanged paths | `R:1331-1333,1459-1462` forwards flags; `T:612-659,759-780` binds selected executables, their runtime dependencies and SDK settings | CA-03: forwarding an input path to a dry-run probe does not hash that input's bytes. |
| Cross-target native dependencies | Distinct host/target compiler, archiver and linker selections | Package-ID graph at `R:743-762`; one global target passed through `R:1758-1769`; one driver map at `R:1293-1307,1436-1478` | CA-04: host-built dependency units have no separate native context. |
| Optional-process absence observation | PATH entries, package working directory, candidate executable presence | Probe hashes PATH, cwd and candidate names at `R:947-960`; generation changes clear probe caches at `T:1373-1397` | Re-probing exists. CA-06 remains because the probe uses the adapter cwd, not the build-script package cwd. |
| Build-cache namespace identity | Target selection, profile, output-directory configuration | `R:1592-1632`; path hashes at `T:1429-1448`; generated roots excluded at `R:1779-1789` | CA-08: the incremental role can name the wrong subdirectory. Generated-product correctness remains explicitly trusted. |

## Lens 2 - Clause-to-line discharge

| Clause | Expected discharge | Actual code line | Status |
|---|---|---|---|
| D I11, `D/docs/intent.md:25` | Reuse requires complete current dependency/tool/environment provenance; unsupported closure prevents PASS | `R:1693-1795`, with omissions detailed in CA-01 through CA-07 | gap |
| D I12, `D/docs/intent.md:32` | Preserve exact commands, bounds and every logical observation | Adapter reads the subject at `R:261-386`; evidence execution and observation publication are not implemented in this file | partial: no proof-command reduction found here; scheduling/observations remain separate review obligations |
| D I13 and I14, `D/docs/intent.md:33-34` | Scoped assurance grants no activation or deployment authority | `R:1791-1796` returns adapter data only | partial: no activation route in this slice; canonical gate and runtime refusals were not re-reviewed |
| V4 S1 | Complete policy-slot expansion and assessment | No slot-expansion implementation in the assigned adapter | partial: outside this slice |
| V4 S2 | Shared work requires complete matching execution identity | Package/tool identity construction at `R:625-655,765-797`; `T:1260-1272` | partial: hashing exists, but closure gaps undermine completeness |
| V4 B1 | PASS rests on completed invocation plus matching complete endpoints and provenance | Adapter supplies roots/discovery at `R:1791-1796`; current tool comparison at `T:1381-1397` | partial: the compared identity can omit actual inputs; completion/store/ownership are separate boundaries |
| V4 B2 | Stale or malformed work cannot become PASS through reuse | Revalidation compares current digest/discovery at `T:1381-1397` | partial: changes outside the enumerated roots can be invisible; history barriers are outside scope |
| V4 T1 | Stop dispatch on first failure and durably account for work | Adapter throws through `R:16-18`; scheduler/store not reviewed | partial |
| V4 T2 and operational premises, `V4:159-165` | Revalidate endpoints without claiming continuous nonmutation or cache correctness | Generation-scoped revalidation at `T:1373-1404`; generated products excluded at `R:1779-1789` | partial by declared trust; no new ABA or cache-coherence proof claimed |
| Cargo/Kani selected runtime, `V4:233-234,261` | Actual compiler/sysroot and application graph under the selected context | Rustup selection at `R:461-539`; Kani pin/version/sysroot checks at `R:1516-1558`; graph at `R:658-797` | partial: Kani pinned-runtime checks are present; CA-01, CA-02 and CA-04 affect complete selection |
| Package identity, `V4:259-261` | Source-qualified identities plus actual installed source bytes | `R:625-655,765-797` | discharged for the inspected identity construction; graph completeness is separately deficient |
| Native closure and unknown selection, `V4:245-247,277` | Bind selected native inputs or fail preflight | `R:1365-1434`; native discovery at `T:563-780` | gap: CA-03 through CA-07 |
| Effective cache namespaces, `V4:167-178` | Bind actual target/build/incremental/compiler-cache selection | `R:1583-1686` | partial: explicit cache rejection and selection exist; CA-08 remains |
| Ledger TA-08, `D/.fv/ledger.md:454` | Operator honesty remains an assumption; local hashes do not authenticate execution | `T:1260-1292` constructs unsigned content/probe identities | partial by explicit trust; no cryptographic producer authentication claimed |
| Ledger C-01 through C-15 | Adapter identity must not promote incomplete component conjunctions to refinement or activation | `R:1791-1796` emits no composition verdict | partial: every candidate remains outside this adapter's discharge scope |
| Ledger TA-01 through TA-07 and TA-09 through TA-17 | Preserve external platform, cryptographic, governance, consensus, custody and qualification assumptions | No enforcing protocol code inspected in this slice | partial: no assumption is discharged by tool hashes |
| Remaining D protocol clauses, including I1-I10, RS1-RS6, S/B/Q-B19, PV/PS/PB clauses, behavior blocks and activation requirements | Protocol implementations must enforce their own clauses | No primary enforcing protocol line in the assigned Rust adapter | partial: explicitly outside the assigned implementation review, not inferred satisfied |

## Lens 3 - Deferred cannot silently succeed

| Branch | Reachable from | Behavior | Status |
|---|---|---|---|
| Unsupported TOML/configuration, source kinds, target forms and Kani solver choices | `discoverRustAdapter` | Explicit throws at `R:35-36,428,452-453,655,1733-1736` | Explicit refusal inspected. |
| Missing installed compiler/distribution/package inputs | Runtime and graph discovery | Reads/realpath failures propagate; `requiredReal` throws at `R:208-214`; Kani checks installed paths before launcher use at `R:1521-1548` | No missing-input fabricated bytes found. |
| Unsupported native provider chain | Metadata-forwarding classification | Missing provider or cycle throws at `R:1427-1434` | Explicit refusal exists, but its trusted-provider base case is too broad under CA-05. |
| Unclassified build-script process expression | Native scan | `Command::new(variable)` with a non-optional execution suffix reaches `continue` at `R:1397-1398` | CA-05: unsupported work can be admitted. This is fail-open classification, not a labeled TODO. |
| Compiler/process and package-name exceptions | Native scan | Selected literal commands bypass checking at `R:1392`; name-based native admission at `R:1372-1383` | CA-05: success of classification does not establish the work's closure. |
| Runtime-only adapter | `subject` has only entry or entry plus toolchain | Returns runtime roots with empty packages/cache namespaces at `R:280-282,1737-1754` | Deliberate supported mode, not a stub. Its use must satisfy the separate complete-application/incorporated-collector obligation in `V4:261`; no general application-completeness conclusion follows. |
| Explicit TODO/stub/mock implementation | Primary Rust adapter | No labeled deferred implementation found in the targeted search | No separate finding from a labeled deferred-success branch. |

## Lens 4 - Who controls

| Field | Supplier | Validation | Gap |
|---|---|---|---|
| Subject operation, packages, features, target, profile and selectors | Reviewed policy | Closed flag handling at `R:261-386`; offline locked metadata/tree at `R:658-742` | CA-02 and CA-08 are semantic application mismatches after syntax acceptance. |
| Cargo configuration and path bases | Filesystem configuration plus policy argv | TOML parsing, hierarchy/CLI merging, selected file roots and explicit unsupported forms at `R:389-458` | Flags may still select unbound inputs under CA-01/CA-03. |
| `PackageIdentity` fields | Actual Cargo metadata joined to Cargo.lock | Exact source-qualified match, checksum/revision grammar, project containment at `R:625-655` | No separate supplier-validation defect identified. Source authenticity remains trust. |
| `attestationFeatures`, `attestationDependencies` | Cargo tree and metadata resolve nodes | Package display disambiguation at `R:586-620`; features unioned by package ID and direct normal edges recorded at `R:743-762` | CA-04: package identity does not distinguish host/target compilation units. |
| `nativeProviders` and `forwardedProviders` | Classifier applied to package-controlled source/metadata | Name-based admission at `R:1371-1383`; provider-ID/prefix checks at `R:1269-1277` | CA-05 and CA-07: provider membership or syntax fragments do not establish complete effects. |
| Optional command selector and absence | Build-script source, PATH and filesystem | Restricted names and access checks at `R:947-979`; direct RUSTC helper recognition at `R:981-998` | CA-06: lookup context differs from Cargo's actual package cwd. |
| Native flags and drivers | Cargo config, semantic environment, package selection | Driver resolution and probes at `R:1290-1356,1436-1478`; `T:572-657` | CA-03/CA-04/CA-05. |
| Cache namespaces | CLI, environment, configuration and metadata | Canonicalization and supported compiler-cache checks at `R:1583-1686` | CA-08; product integrity is trusted, not byte-proved. |
| Persisted tool digest/discovery/system fields | Producer derived from adapter output and actual probes | `T:1260-1292`, revalidated at `T:1373-1404` | Correctly hashing an incomplete root set does not close the omissions above. |

## Lens 5 - Field-name fidelity

| Field | Implied semantic | Actual value | Status |
|---|---|---|---|
| `packages[].source` and `packages/<digest>` | Exact source-qualified package identity | Exact lock/metadata source plus real contained path identity at `R:625-655,765-779` | No separate naming drift identified. |
| `sysroot` | Libraries selected by the effective compiler invocation | Default `rustc --print sysroot` result, without effective rustflags at `R:533,1717-1728` | CA-01, counted under commitment coverage. |
| `discovery[].cwd` and optional probe's cwd hash | Actual probe cwd | Adapter cwd through `T:1094-1122` and `R:976` | Truthful about the probe itself; CA-06 is its invalid use as evidence of build-script lookup. |
| `cargo-incremental` namespace | Actual selected incremental cache location | Synthesized from raw `selected.target` and profile mapping at `R:1614-1624` | CA-08: config/env-selected targets are omitted; bench defaults are mapped to debug. |
| `integrity:"upstream-build-system"` | Declared generated-cache trust | `T:1443-1449`, with generated roots excluded by `R:1779-1789` | No fresh-compilation meaning is assigned by this slice. |
| `nativeProviders` internal set | Provider already has a supported complete closure | Membership granted from package name and a declared cc dependency at `R:1371-1378` | CA-05, counted under clause-to-line. |

## Lens 6 - Deferral justification audit

| Deferred finding | Justification claims | Claim audit | Verdict |
|---|---|---|---|
| Prior FV2, generated-product provenance | Effective cache selection is bound; upstream freshness/product integrity is assumed; no fresh compilation is claimed | Disposition: `F/.fv/changes/2026-10-14-execution-evidence-v4.md:48`; contract: `V4:165-178`; implementation excludes generated roots at `R:1779-1789` | Trust-based deferral remains explicit. CA-08 concerns incorrect selection metadata, not a demand for a fresh build. |
| Prior FV3, endpoint ABA | Continuous immutability is not established; concurrent external mutation is excluded | Disposition at the same change record `:49`; `V4:163`; generation-based revalidation at `T:1373-1404` | No wrong-deferral finding. Counterexamples here require no concurrent mutation. |
| Prior FV5/D2, Kani application dependencies | Contract now requires the pinned compiler and full application/build/native graph | Change record `:51`; prior review-2 `F/.fv/attacks/2026-10-14-execution-v4-review-2.md:30`; implementation `R:1516-1580,1757-1769` | Prior closure was explicitly contract-level. Current implementation gaps are CA-02/CA-04/CA-05, not evidence that the earlier report claimed implementation completeness. |
| Prior D3, native Cargo compiler/linker | Actual selected native dependencies must be bound; SDK trust does not exempt selected binaries | Change record `:57`; `V4:277`; implementation `R:1365-1478` | Requirement remains intact. CA-03 through CA-07 show incomplete implementation, not an authorized deferral. |
| Unrelated protocol/audit residuals in D's ledger | Named runtime, platform, refinement and activation work remains incomplete | `D/.fv/ledger.md:446-463,559-600` | Outside this adapter slice. No claim that these residuals were closed or re-audited. |

No independently grounded `wrong-deferral` finding was identified in the relevant prior dispositions.

## Lens 7 - Tool/input provenance

| Boundary | Required provenance | Inspected evidence | Result |
|---|---|---|---|
| Rustup shim to Cargo/rustc | Preserve dispatch semantics and identify installed selected binaries | Settings/override/toolchain-file resolution and rustup `which` at `R:461-539`; selected rustc override at `R:1705-1728` | Selection machinery exists. CA-01 covers unhandled effective sysroot selection; CA-05 covers the separate literal `rustc` process exemption. |
| Kani launcher to pinned toolchain/backend/solver | Distribution-selected compiler, matching sysroot and backend bytes | `R:1516-1580` verifies pin/version/sysroot and adds distribution/backend/solver roots | No separate missing-pin finding. This does not prove compiler authenticity or complete application/native closure. |
| Registry/Git/path identity to installed content | Keep source identity separate from content identity | `R:625-655,765-797` | Construction inspected; CA-02 can omit entire required packages. |
| Optional process to an absence conclusion | Actual package cwd and effective search context, rechecked at boundaries | `R:947-979`; probe defaults `T:1094-1122`; generation reset `T:1373-1397` | CA-06. |
| Native compiler to headers/link inputs | Applicable external file bytes, not just executable dependencies | `R:1331-1333,1459-1462`; `T:612-659,759-780` | CA-03. |
| Application/build units to native driver selection | Separate host and target contexts where applicable | `R:743-762,1436-1478,1758-1769` | CA-04. |
| Installed identity to portable consumer | Consumer validates retained provenance without discovering producer tools on CI | `F/scripts/fv_evidence_v4.py:340-429,581-650` checks roots/package consistency | These structural checks do not supply bytes the producer omitted. No full portable-consumer review is claimed. |

## Lens 8 - Bounded-parser/dataflow

| Parser/classifier | Required invariant | Inspected behavior | Result |
|---|---|---|---|
| Cargo TOML subset | Reject unsupported syntax rather than invent values | `R:30-198` uses explicit parsing and rejection | No specific additional TOML counterexample reported. This is not a general TOML conformance proof. |
| Singleton links-only rebuild script | Entire script fits the harmless bounded grammar | `R:1000-1043` tokenizes the complete function and permits only rerun directives; source-link scan at `R:1093-1113` | Bounded full-consumption check exists. Its protection applies only to the branch that calls it. |
| Cargo RUSTC selector | Command operand really denotes Cargo's selected compiler | Direct/helper recognition at `R:981-998`; selected compiler query at `R:1400-1406` | Supported query path binds the selected compiler. The separate literal-name bypass and unclassified process forms remain CA-05. |
| Metadata forwarding provider | Exact direct source-qualified provider plus complete provider closure | `R:1269-1277,1427-1434` checks direct IDs, prefix ambiguity and recursive closure | Useful checks, but the provider base case is CA-05 and branch pruning is CA-07. |
| Target-infeasible branch pruning | Prove the entire condition false before removing effects | `R:1173-1202` searches for a false equality subexpression, without proving its Boolean context | CA-07: equality-to-false inversion makes a removed branch reachable. |
| General build-script/native source scan | Every admitted effect is classified; unknown effects refuse | `R:1365-1425` uses selected regexes and package-name exceptions; source-link scan is limited to one links branch | CA-05. |

---

## Finding list (consolidated)

| ID | Lens | Severity | Surface | Intent ref | Code ref | Summary | Fix |
|---|---|---|---|---|---|---|---|
| CA-01 | commitment-coverage | Major | build-pipeline | D I11 (`D/docs/intent.md:25`); `V4:233-234,245-247,261` | `R:533,1309-1342,1717-1728` | Effective rustflags may select a different sysroot, but the adapter commits only the default queried sysroot. | Resolve effective compiler flags before root selection. Bind the selected sysroot, or reject sysroot-changing forms until supported. |
| CA-02 | commitment-coverage | Major | build-pipeline | D I11; `V4:233-234,259-261` | `R:345-350,733-737,743-779` | Singular target selectors are accepted but do not enable dev edges, omitting dependencies used by examples/tests/benchmarks under build/check/run. | Derive dependency kinds from every accepted target selector; include singular forms and preserve the actual target-selection semantics. |
| CA-03 | commitment-coverage | Major | cross-layer native inputs | D I11; `V4:233-236,245-247,277` | `R:1331-1342,1459-1462,1478`; `T:612-659,759-780` | External native input paths in accepted compiler/linker flags are not converted to content roots or rejected. | Add a bounded native-input resolver for supported flags and transitive headers/link inputs; reject unclassified input-bearing flags. |
| CA-04 | commitment-coverage | Major | host/target build boundary | D I11; `V4:233-234,261,277` | `R:743-762,1293-1307,1436-1478,1758-1769` | A package-level union graph and one global target driver map omit distinct host native tool selection for build/proc-macro dependency units. | Preserve host/target unit contexts and attest each selected driver/configuration/closure, or refuse unsupported mixed contexts. |
| CA-05 | clause-to-line | Major | build-script/native classifier | D I11; `V4:245-247,277` | `R:1365-1425`, especially `1372-1383,1392,1397-1398`; `R:1093-1113` | Unknown process/linkage effects can be admitted; package names substitute for bounded behavior classification and complete provider closure. | Use complete bounded classifiers with fail-closed residual handling. Remove name-only exemptions, classify all consumed source effects, and bind literal compiler commands to their actual selected executable. |
| CA-06 | clause-to-line | Major | optional process discovery | D I11; `V4:233-234,239,277` | `R:947-979,1395,1421`; `T:1094-1122` | Absence is probed in adapter cwd rather than the build script's package cwd, so relative PATH entries can select a real unbound executable during the build. | Probe the exact package execution cwd and search environment; support external installed-package probe locations without misrepresenting recorded cwd, or reject contexts that cannot be represented. |
| CA-07 | clause-to-line | Major | bounded-parser/dataflow | D I11; `V4:245-247,277` | `R:1173-1202,1234-1268,1384-1389` | Metadata-forwarding classification erases a branch after finding a false equality anywhere in its condition, including an equality whose false result is inverted to true. | Parse a closed Boolean grammar and prove the complete condition false. Leave unknown conditions intact and require full effect validation. |
| CA-08 | field-name | Minor | generated-cache provenance | D I11; `V4:167-178` | `R:288,1614-1624,1731-1734,1770-1778` | `cargo-incremental` can identify the wrong target/profile subdirectory despite claiming effective cache selection. | Pass resolved target-selection state and Cargo's effective profile/output mapping to cache discovery; correct bench mapping and configuration/environment target handling. |

### Counterexample details and parent-owned checks

#### CA-01: rustflags-selected sysroot

The rustflags loop handles linker options and rejects several external-linkage options, but ignores `--sysroot` and `--sysroot=...`. Both runtime discovery and configured-RUSTC discovery query `--print sysroot` without those flags. The resulting default path becomes the sole `sysroot` root.

[INFERENCE] An accepted Cargo context with `RUSTFLAGS="--sysroot /opt/alternate-rust"` can consume library bytes under `/opt/alternate-rust` while only the default distribution is hashed. Changing those external library bytes between invocations can leave the recorded closure unchanged. The upstream cache-integrity premise does not repair omitted source/tool inputs.

Parent check: capture a real Cargo context selecting a compatible alternate sysroot, change a consumed alternate library without changing its path, and require invalidation or explicit preflight refusal. The Rust documentation explicitly defines `--sysroot` as overriding the distribution-crate location: https://doc.rust-lang.org/rustc/command-line-arguments.html#--sysroot-override-the-system-root.

#### CA-02: singular selectors omit dev dependencies

`selection()` stores `--test`, `--example` and `--bench`, but `applicationGraph()` tests only `--tests`, `--examples`, `--benches` and `--all-targets` when the operation is not already test/bench. The full metadata response is used for lookup; only packages returned by the narrower tree enter `graph` and receive roots.

[INFERENCE] `cargo build --example demo` with a registry dev-dependency used only by that example admits a graph lacking that dependency. An offline metadata success does not restore the missing root. The same mismatch applies to accepted singular test/bench selectors on build/check where Cargo uses dev dependencies.

Parent check: compare singular and plural selectors using a real example with an external dev-only package, then mutate that installed package between captures. Cargo documents dev dependencies as inputs to tests, examples and benchmarks: https://doc.rust-lang.org/cargo/reference/specifying-dependencies.html#development-dependencies.

#### CA-03: native input paths are not content identities

`-C link-arg=...` and `-C link-args=...` are forwarded into `flags`; CFLAGS are forwarded similarly. The native helper probes empty `/dev/null` inputs with `-###`, records selected executables/configuration, and inspects runtime linkage of those executables. It does not enumerate external headers or static link inputs mentioned by those flags.

[INFERENCE] `CFLAGS="-include /opt/site/feature.h"` can affect an admitted native compilation without binding `feature.h`. Likewise, `RUSTFLAGS="-C link-arg=/opt/vendor/libextra.a"` can consume a non-system archive whose bytes are absent from the roots. A stable dry-run command line only commits the path. Changing the external file between producer invocations need not change the probe output or tool digest.

Parent checks: exercise both cases with actual files; inspect the manifest for their exact content hashes and require mutation invalidation. Do not substitute SDK/vendor integrity for non-system files.

#### CA-04: host-built dependencies need their own native context

The graph is keyed only by package ID. Features are unioned, and no host/target unit role survives into `nativeDependencies`. That function receives the application target once and selects only that target's linker and CC/AR context.

[INFERENCE] A cross-target application whose build dependency uses an admitted native provider can compile that dependency for the host using `HOST_CC` or a host-qualified CC, while the adapter binds only the target compiler. This requires no hostile tool or process escape. It is ordinary Cargo host-tool execution. Distinct host linker configuration is similarly absent from the selected driver map.

Parent check: use a real cross-target graph with a native build dependency and distinct host/target compiler paths. Require both identities and mutate the host tool independently. Refusal is acceptable until the adapter supports the full unit distinction.

#### CA-05: fail-open residual effects and name-only provider admission

Three concrete paths bypass the stated unknown-closure rule:

1. A package without `links` and without a cc build dependency can contain `let tool = "/opt/helper"; std::process::Command::new(tool).status().unwrap();`. The variable-command regex matches, but line 1398 continues because the suffix is not the optional-output form. No closure is added and no refusal follows.
2. Any package named `ring`, `blst`, `blake3` or `aws-lc-sys` with a cc build dependency enters the native-provider base case without a source-qualified behavior match. For example, a same-named path package can select an external compiler through `cc::Build::compiler(...)`; the adapter still starts from its generic CC/default selection. `system-configuration-sys` also bypasses the links-script classifier solely by name.
3. The Rust-source native-linkage scan is invoked only in the non-exempt links branch. Packages with no custom build target never enter that loop, so ordinary `#[link(...)]` sources are not subjected to that closure check. Literal `Command::new("rustc")` is also skipped even when Cargo's selected `RUSTC` differs from PATH's rustc.

[INFERENCE] These forms can reach ordinary evidence execution with an incomplete tool/input identity. Source hashing records the script text, but does not bind the external program or library it selects. The conforming-child premise constrains lifecycle, not dependency completeness.

Parent checks: add real negative contexts for a variable command with `.status()`, an aliased/helper process constructor, a same-name path native provider, a no-build-script `#[link]` package, and differing PATH rustc versus configured RUSTC. Unknown forms must refuse before evidence dispatch. Do not execute arbitrary build scripts merely to discover their effects.

#### CA-06: optional absence uses the wrong cwd

The absence probe carefully checks each PATH candidate and is rerun after generation changes. However, `bindOptionalProcessAbsence` receives neither package manifest directory nor a cwd override. `context.probe` defaults to the adapter locator's cwd. Cargo runs each build script in its own package root, as documented at https://doc.rust-lang.org/cargo/reference/build-scripts.html#inputs-to-the-build-script.

[INFERENCE] With a relative PATH component such as `../helpers`, the helper may be absent relative to the workspace/adapter cwd and present relative to a registry package directory. The adapter admits absence; the build script executes the helper. A helper adjacent to the registry package can lie outside every declared package root. Empty PATH components create the same context mismatch.

Parent checks: test nested path packages and external registry package roots with relative and empty PATH entries, plus an unchanged-context absent-to-present transition between captures. The latter verifies that the existing re-probe mechanism remains effective after the cwd correction.

#### CA-07: a false subexpression does not imply a false condition

For an otherwise accepted metadata-forwarding script, add a condition of this form on Linux:

`if (env::var("CARGO_CFG_TARGET_OS").as_deref() == Ok("windows")) == false { let bytes = std::fs::read("/opt/provider-input").unwrap(); assert!(bytes.is_empty()); }`

The condition contains neither `!` nor `||`. The equality scanner finds `target_os == windows`, marks it impossible, and deletes the entire body before validating permitted calls. The complete condition is true on Linux. The external read is neither a process regex match nor a native-link directive, so the later scans do not restore the lost effect.

[INFERENCE] The wrapper can retain its valid forwarding functions and provider identity while consuming an unbound external file. Changing that file from empty to nonempty between invocations can change actual build success while the adapter's input identity remains unchanged.

Parent checks: use the complete otherwise-admitted forwarding fixture with this reachable branch, equivalent nested Boolean forms, and an actually impossible positive-control branch. Require explicit refusal or complete closure, without running arbitrary build code during discovery.

#### CA-08: incremental-cache provenance has incorrect target/profile mapping

`targetValue` resolves CLI, `CARGO_BUILD_TARGET`, config and host at `R:1731-1734`, but cache discovery receives `selected`, not the effective target-selection state. Its incremental path adds a target component only when the CLI supplied `--target`. It also assigns `test` to both test and bench operations, then maps that to `debug`; Cargo's bench profile inherits release.

[INFERENCE] Config/env-selected targets can be recorded as `buildDir/debug/incremental` instead of the target-qualified location. Default bench can be recorded under debug instead of release. The broader target/build namespace is still recorded, which limits the demonstrated impact to inaccurate subnamespace provenance; this report does not claim a standalone stale-PASS exploit from this defect.

Parent checks: compare CLI/config/environment target selection, default bench, explicit bench profile and custom profiles against actual Cargo output locations. Preserve argv and the declared upstream-cache premise.

## Summary

- Total findings: 8
- By severity: Critical=0 Major=7 Minor=1 Informational=0
- By lens: commitment-coverage=4 clause-to-line=3 deferred-cannot-silently-succeed=0 who-controls=0 field-name=1 deferral-justification=0
- Supplemental lenses map to the same findings; they add no duplicate count.
- Recommended next step: close selected sysroot and graph omissions (CA-01/CA-02), native input and host-unit omissions (CA-03/CA-04), fail-open classifier paths and lookup/dataflow errors (CA-05/CA-06/CA-07), then correct cache namespace provenance (CA-08). Parent should run the listed real counterexamples and the existing adapter/boundary regression suites after changes, then obtain an independent re-review before external audit. No review-pass or production-activation conclusion is made.