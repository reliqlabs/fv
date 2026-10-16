# Code-adversarial review: evidence-v4 Rust toolchain adapter, round 2 - 2026-10-15

- Operator: fv-code-adversary via OMP task (NOT openai-codex/gpt-6.1-sol task agents FixRustToolchain, FixBaseToolchain, FixProofToolchain, FixNativeOwnership-2, FixProducerStore-2, FixSourceBindings-2 or FixAdoptionDashboard-2, and NOT the parent orchestrator)
- Code commit reviewed: `6c787c20f023a132856cf5119b137be25dd2303f` (parent `aa6946f`, the round-1 target). The caller supplied the commit identity. I did not check it with Git.
- Intent version reviewed: no frontmatter version. `F/.fv/dispatch.json` and `F/.fv/intent.md` are both absent. I followed the round-1 resolution: `D/.fv/dispatch.json` → `D/docs/intent.md` (I11 at `:25`, 2026-10-14 revision at `:1575`). The caller designated `F/docs/execution-evidence-v4.md` (V4) as the normative contract, together with the disposition table at `F/.fv/changes/2026-10-14-execution-evidence-v4.md:113-127`.
- Ledger version reviewed: `D/.fv/ledger.md` has no frontmatter timestamp. The body says `Updated: 2026-10-08` (`:5`).
- Lens pack: crypto/enclave six-lens baseline, plus tool/input-provenance and bounded-parser lenses for the Rust adapter
- Lenses applied: 1 through 6

Abbreviations: `F`=`/Users/mv/Development/reliq-fv-wt/evidence-perf`; `D`=`/Users/mv/Development/burnt/dossier-wt/evidence-perf`; `R`=`F/tools/evidence-v4/evidence-v4-toolchain-rust.ts`; `C`=`F/tools/evidence-v4/evidence-v4-toolchain-common.ts`; `T38`=`F/tests/r38_evidence_v4_rust_review.py`; `V4`=`F/docs/execution-evidence-v4.md`; `CR`=`F/.fv/changes/2026-10-14-execution-evidence-v4.md`; `CB`=`~/.rustup/toolchains/1.97.1-aarch64-apple-darwin/share/doc/rust/html/cargo/reference/`. Round-1 findings are labelled `R1-CA-0N`. New findings are `CA-0N`.

This was static inspection only. I ran no tests, builds or Git commands. The parent-reported test results (150/150 Darwin, Linux 114 with 7 skips) are accepted as reported. They do not exercise the counterexamples below. Statements about Cargo or rustc internals that are not documented in `CB` are marked [INFERENCE].

## Round-1 closure verdicts

| Round-1 | Disposition (`CR:124`) | Evidence | Verdict |
|---|---|---|---|
| R1-CA-01 rustflags-selected sysroot | refused | `R:2102-2103` refuses `--sysroot` in `CARGO_ENCODED_RUSTFLAGS`, `RUSTFLAGS`, `CARGO_TARGET_<T>_RUSTFLAGS` and config `target.<T>`/`build.rustflags` (`R:2083-2091`). Cargo's documented fourth source, env `CARGO_BUILD_RUSTFLAGS` (`CB/config.html:718,724-733`), is never read. `T38:282-296` tests only RUSTFLAGS, ENCODED and config. | **partially closed**: CA-01 |
| R1-CA-02 singular selectors omit dev edges | fixed | `R:347-351` records `--test/--example/--bench`. `R:738-744` adds `dev` edges for them. Cargo needs no dev edges for `--bin`. | **closed** |
| R1-CA-03 native input paths | refused | `assertBoundNativeFlags` (`R:1956-2037`) binds or refuses paths in CFLAGS/CXXFLAGS/LDFLAGS (`R:2076-2081`), `-C link-arg(s)` (`R:2107-2108,2119`) and cc/aws-lc flags (`R:2377`). `-L/-l/@/llvm-args` are refused (`R:2109-2117`). The long form `--codegen` and other input-bearing rustflags are not classified, and the CA-01 env source bypasses this check entirely. | **partially closed**: CA-01, CA-02, CA-06 |
| R1-CA-04 host/target native contexts | refused | `R:776-787` marks host units. `R:2159-2160` refuses cc-using host units when cross-compiling. The host linker used for build scripts and proc-macros (`target.<host>.linker`, `CARGO_TARGET_<HOST>_LINKER`) is still unbound. Round 1 named this explicitly. | **partially closed**: CA-03 |
| R1-CA-05 fail-open classifier, name-based providers | fixed | The variable-command fall-through is gone (`R:2244-2247`). Native providers now need the exact crates.io source plus a build-program fingerprint (`R:1918-1954`). Packages without a build script get a link-directive scan (`R:2144-2151`). A literal `rustc` must equal the selected RUSTC (`R:2218-2219`). The residual check is still a textual denylist over `build.rs` (`R:2312-2322`), so effects reached through a build-dependency library, or through file reads, are admitted. | **partially closed**: CA-05 |
| R1-CA-06 absence probe cwd | fixed | `R:1002-1011` probes in the package directory, which is Cargo's build-script cwd, when the package is inside the project. External packages must have absolute, nonempty PATH entries. The expected-result check at `R:1013-1034` includes cwd and PATH hashes. | **closed** |
| R1-CA-07 equality-inversion pruning | fixed | A complete recursive-descent grammar (`R:1323-1411`) requires full consumption (`position === tokens.length`). Unknown atoms return `undefined`. Pruning happens only when the result is exactly `false` (`R:1445`). The round-1 `== false` form now evaluates to true (`T38:580-584`). Remaining issue: the cfg facts come from a probe that leaves out effective rustflags. | **closed** for the reported defect. Residual: CA-08 |
| R1-CA-08 incremental namespace | fixed | The effective target comes from CLI, then `CARGO_BUILD_TARGET`, then config (`R:2641-2645`), and is passed to `cacheNamespaces` (`R:2672-2681`). Profile mapping: test/dev → debug, bench → release, custom → its own name (`R:2520-2524`). | **closed** |

### Focus questions

- **Fingerprint allowlist: source-qualified and exact?** Yes. A same-name path or git provider cannot pass.
  - `reviewedBuildScript` returns `undefined` unless `pkg.source` equals the literal `registry+https://github.com/rust-lang/crates.io-index` and the target is darwin or linux gnu/musl (`R:1923-1927`).
  - It then requires an exact `name@version` entry with a SHA-256 of the `build.rs` bytes plus listed helper files (`R:1950-1954`). aws-lc-sys additionally hashes the full `builder/**/*.rs` set and requires `main.rs` byte equality (`R:1928-1948`).
  - The non-Windows link-source allowlist has the same source and target gate. It also requires no `--cfg` in the observed rustflags, and hashes `Cargo.toml` plus every `.rs` file (`R:1216-1249`).
  - A path or git `ring` with a cc build-dependency reaches `R:2162` and refuses (`T38:423-456`).
  - Limits: the fingerprint covers the build program, not the rest of the crate. Those other files are still content-bound through `packages/<digest>` (`R:808`), so tampering changes the identity. I did not check the pinned hashes against upstream crate bytes. That crates.io sparse and source-replaced packages report the canonical source string is [INFERENCE]. If they did not, the result is a refusal.
- **Boolean cfg pruner**: the grammar and its full-consumption rule are sound for the accepted forms. The remaining issue is the cfg facts it evaluates against (CA-08).
- **Absence probing**: closed, as in the table above.
- **canonicalToolPath cutover**: `R` has no remaining `fs.realpath`. `requiredReal` and `canonicalNamespace` call `canonicalToolPath` (`R:209-226`). For regular files, `canonicalToolPath` keeps the hardlink spelling and canonicalizes only the parent directories (`C:78-104`). Path comparisons in `R` use the same function on both sides (`R:1216-1218`, `R:1966-1979`). The one visible behaviour change also fails closed: the literal-rustc equality at `R:2219` refuses when PATH `rustc` is a rustup proxy hardlink rather than the toolchain binary. No new defect found.

---

## Lens 1 - Commitment coverage

| Commitment | Attacker DoFs | Bound by | Gap |
|---|---|---|---|
| Selected sysroot and rustflags-selected inputs | Every documented rustflags source | `R:2083-2117` reads ENCODED, RUSTFLAGS, `CARGO_TARGET_<T>_RUSTFLAGS` and config only | CA-01: `CARGO_BUILD_RUSTFLAGS` is ignored |
| Rustflags input operands | `--codegen OPT`, `-C profile-use=`, `--extern name=path`, `--codegen linker=` | `R:2104-2117` recognises only `-C`/`-C<opt>` spellings and refuses only `-L/-l/@/llvm-args/--sysroot` | CA-02 |
| Host-unit linker in cross builds | `target.<host>.linker`, `CARGO_TARGET_<HOST>_LINKER` | `drivers.linker` comes from `targets[target]` only (`R:2052-2068`). The host table is read only for links overrides (`R:2156`) | CA-03 |
| Test/run/bench runner | `target.<T>.runner`, `CARGO_TARGET_<T>_RUNNER` (`CB/config.html:1423-1432`) | No reference anywhere in `F/tools/evidence-v4` (grep `runner`: no matches) | CA-04 |
| Relative link-arg resolution | Same-named file at a different cwd | Bound against `context.cwd` (`R:2119`) | CA-06 [INFERENCE] |
| Compile-time file inclusion | `include_bytes!/include_str!/include!` with absolute or escaping paths | `hasNativeSourceLinkage` skips `include!` in links-only mode and never matches `include_bytes!/include_str!` (`R:1181-1200`) | CA-07 |
| Package identity, reviewed build programs | name/version/source/checksum, build-source bytes | `R:630-661`, `R:1918-1954` | No gap. Source-qualified and exact (see focus questions). |
| Cache namespaces | target/profile/build-dir | `R:2488-2532` | Closed (R1-CA-08) |

## Lens 2 - Clause-to-line discharge

| Clause | Expected discharge | Actual code line | Status |
|---|---|---|---|
| D I11 (`D/docs/intent.md:25`), V4:247 "unknown or incomplete transitive tool closure is a preflight error" | Every unclassified effect refuses at discovery | `R:2203-2322` denylist over `build.rs` text only | gap: CA-05 |
| V4:233 cargo-toolchain: actual selected sysroot and flags | Effective rustflags resolved from all Cargo sources | `R:2083-2117` | gap: CA-01, CA-02 |
| V4:236,277: Rust configured linkers attested as selected | Host and target linkers both bound | `R:2052-2068,2106` | gap: CA-03 |
| V4:233 "native build-script/compiler/linker/wrapper dependencies"; V4:245 | Cargo-selected execution programs are part of identity | Runner absent | gap: CA-04 |
| V4:245-247 bounded classifier for target-infeasible branches | Prune only under Cargo's actual cfg | `R:1323-1411` grammar sound. cfg probe `R:1434` omits rustflags | partial: CA-08 |
| V4:259 source-qualified identities | Exact source strings | `R:630-661`, `R:1923-1924`, `R:1223` | discharged |
| V4:233 dev-dependency graph for selected targets | Include dev edges for singular selectors | `R:738-744` | discharged |
| V4:167-178 effective cache namespaces | Target/profile/build-dir from actual selection | `R:2500-2532,2641-2681` | discharged |
| Optional-process absence (V4:239 revalidation) | Probe in the actual lookup context | `R:1002-1034` | discharged |
| Path canonicalization (`CR:123`) | Deterministic tool-path identities | `C:78-104`; `R:209-226` | discharged. One fail-closed availability effect at `R:2219` |
| Ledger TA-08, C-01..C-15, TA-01..TA-17; D I1-I10 and other protocol clauses | Outside this adapter | No enforcing code in `R` | partial by scope. Nothing discharged here |

## Lens 3 - Deferred cannot silently succeed

| Branch | Reachable from | Behavior | Status |
|---|---|---|---|
| Unreviewed provider revision (crates.io, wrong hash) | `reviewedBuildScript` → `undefined` → `R:2162` | Explicit refusal | acceptable |
| Generic build script with no recognised token | `nativeDependencies` falls through after `R:2322` | Returns success without classifying library calls or file I/O | gap: CA-05 |
| Cross-target cc host unit | `R:2159-2160` | Explicit refusal | acceptable |
| Cross target without native packages | `R:2337` skips the whole host/target driver block | Admits the host linker without binding it | gap: CA-03 |
| Optional-process probe on an external package with relative PATH | `R:1003-1004` | Explicit refusal | acceptable |
| `TODO`/stub/mock in `R` | targeted read | none found | none |

## Lens 4 - Who controls

| Field | Supplier | Validation | Gap |
|---|---|---|---|
| Semantic environment (`CARGO_BUILD_RUSTFLAGS`, `CARGO_TARGET_<T>_RUNNER`, `CARGO_TARGET_<HOST>_LINKER`) | Reviewed recipe environment (`F/tools/evidence-v4/evidence-v4-source.ts:277-281`, no name allowlist) | The adapter mirrors only a subset of Cargo's env-config keys | CA-01, CA-03, CA-04 |
| Rustflags tokens | Env/config | Partial option recognition (`R:2101-2117`) | CA-02 |
| Build-dependency library behavior | Package graph | Not inspected | CA-05 |
| cfg facts for pruning and `cfg!` selection | `rustc --print cfg --target` probe (`R:1434`, `R:2295`) | Effective rustflags omitted | CA-08 |
| Allowlisted provider identity | crates.io source string plus file hashes | Exact (`R:1923-1954`) | none |

## Lens 5 - Field-name fidelity

| Field | Implied semantic | Actual value | Status |
|---|---|---|---|
| `sysroot` root | Sysroot selected by the effective invocation | Default probe. Correct only if every rustflags source is refused (CA-01) | partial, counted under CA-01 |
| `native/linker` driver | The linker Cargo selects | Target-triple linker only. Wrong when `--codegen linker=` is used (CA-02) | partial, counted under CA-02 and CA-03 |
| `cargo-incremental` namespace | Effective incremental directory | `R:2529-2532` with effective target and profile | faithful |
| absence-probe `cwd_hash` | Probe cwd | Package dir or `context.cwd`, matching what was run (`R:1009,1018-1019`) | faithful |

## Lens 6 - Deferral justification audit

| Deferred finding | Justification claims | Claim audit | Verdict |
|---|---|---|---|
| R1-CA-01 "refused at discovery" (`CR:124`) | Every sysroot-changing rustflags source refuses | False for `CARGO_BUILD_RUSTFLAGS` (`R:2083-2091`; `CB/config.html:718`) | wrong in part. Counted as CA-01 |
| R1-CA-03 "refused at discovery" | Every input-bearing native/rustflags operand is bound or refuses | False for `--codegen`, `-C profile-use`, `--extern` (`R:2104-2117`) | wrong in part. Counted as CA-02 |
| R1-CA-04 "refused at discovery" | Every cross-target host native selection refuses | True only for cc-using packages. The host linker is not covered (`R:2052-2068,2159`) | wrong in part. Counted as CA-03 |
| R1-CA-05 "fixed"; "unreviewed provider revisions refuse" | Provider revisions refuse. Unknown effects refuse | First claim true (`R:1923-1954,2162`). Second claim false for library-mediated and file-read effects | partial. Counted as CA-05 |
| Accepted limits (Linux group signaling, Lake Lean-only) | Outside the Rust adapter | Not contradicted by `R` | no finding |

---

## Finding list (consolidated)

| ID | Lens | Severity | Surface | Intent ref | Code ref | Summary | Fix |
|---|---|---|---|---|---|---|---|
| CA-01 | commitment-coverage | Major | rustflags source resolution | D I11; V4:233,247; `CR:124` | `R:2083-2117,2151`; `T38:282-296` | Cargo's documented `build.rustflags` env form `CARGO_BUILD_RUSTFLAGS` (`CB/config.html:718`, source 4 at `:731`) is never read. With no ENCODED, RUSTFLAGS or target rustflags set, `CARGO_BUILD_RUSTFLAGS="--sysroot=/opt/alt-rust"` gives the adapter an empty `rustArguments`. It records only the default sysroot while rustc links `/opt/alt-rust` libraries. Mutating those between invocations leaves the identity unchanged, which allows stale reuse. The same env defeats the `-L/-l/@` refusal, `-Clink-arg` binding (R1-CA-03) and the `--cfg` guard at `R:2151`. | Read `CARGO_BUILD_RUSTFLAGS` as `build.rustflags`, with env taking prece…
| CA-02 | commitment-coverage | Major | rustflags operand classifier | D I11; V4:233,247,277 | `R:2101-2119` | Only `-C X` and `-CX` are recognised. `RUSTFLAGS="--codegen link-arg=/opt/vendor/libextra.a"` passes both tokens unclassified: neither is pushed to `flags` nor refused. That is the round-1 counterexample in its long-option spelling. `--codegen linker=/opt/ld` selects a linker that never enters `drivers`. `-C profile-use=/opt/pgo.profdata` and `--extern foo=/opt/libfoo.rlib` are compile inputs outside every root. | Normalise `--codegen`/`--codegen=` to `-C`. Switch to an allowlisted rustflags grammar that refuses unknown options and input-bearing codegen options (`profile-use`, `linker-plugin-lto`, `--extern`, `-Z*`). |
| CA-03 | commitment-coverage | Major | host linker, cross target | D I11; V4:236 ("Rust configured linkers must be attested"), V4:277 | `R:2052-2068,2156,2159,2337` | Example: host `aarch64-apple-darwin`, `cargo build --target x86_64-apple-darwin`, config `[target.aarch64-apple-darwin] linker="/opt/hostlink/cc"`. Every build script and proc-macro is linked by `/opt/hostlink/cc` (`CB/config.html:1416-1417`: the linker for the triple being compiled for). The adapter binds only `targets[target].linker` (the default `cc`). The config bytes are hashed, but the host linker's bytes are not. The R1-CA-04 refusal at `R:2159` covers only cc-using packages. | When target ≠ host, resolve and bind a `host-linker` driver (env, then config, then default), or refuse cross-…
| CA-04 | commitment-coverage | Major | Cargo runner | D I11; V4:233,245,247 | Absent: no `runner` handling in `F/tools/evidence-v4` | `cargo test/run/bench` executes each binary through `target.<T>.runner` or `CARGO_TARGET_<T>_RUNNER` (`CB/config.html:1423-1432`). The runner decides what actually runs, yet it is not in ToolIdentity. Example: with `CARGO_TARGET_<HOST>_RUNNER=/opt/run.sh`, a PASS recorded while `run.sh` is `exec "$@"` stays reusable after `run.sh` changes, because the env value and config bytes are unchanged. | Resolve the runner (env, then `target.<triple>.runner`; cfg forms already refuse) and bind it as a driver with its closure, or refuse any runner. |
| CA-05 | clause-to-line | Major | generic build-script classifier | D I11; V4:247,277 | `R:2153-2322` (denylist at `2312-2322`); `R:2144-2151` scans library sources only for link attributes | A build script that is not fingerprint-reviewed, has no `links`, and has no direct `cc` build-dependency is admitted if its text has no `Command/process/.status(` tokens or a `pkg_config|cmake|bindgen|vcpkg::` prefix. Example 1: path build-dependency `helper` with `pub fn run(){ std::process::Command::new("/opt/tool").status().unwrap(); }` in its lib, and app `build.rs`: `fn main(){ helper::run(); }`. The helper's library source is never scanned for processes, so `/opt/tool` is unbound. Example 2: `build.rs` containing `let b=std::fs::read("/opt/input").unwrap(); asser…
| CA-06 | commitment-coverage | Minor | relative link-arg resolution | V4:277 | `R:2119` (resolves against `context.cwd`) | [INFERENCE] Cargo runs rustc for workspace members with cwd set to the workspace root, so the linker resolves a relative `-Clink-arg=libextra.a` there. The adapter checks `context.cwd/libextra.a`. With the recipe cwd set to a member directory and a virtual workspace root, the bound file and the consumed file differ. | Resolve rustflags paths against Cargo's rustc cwd, or refuse relative link-arg operands. |
| CA-07 | commitment-coverage | Minor | compile-time file inclusion | D I11; V4:245,247 | `R:1181-1200` (`include!` skipped when `sourceLinksOnly`; `include_bytes!/include_str!` never matched); packages with build scripts are not scanned | `static K:&[u8]=include_bytes!("/opt/keys/k.bin");` in a path package makes rustc read a file outside every root and outside the project source closure. Pre-existing; round 1 missed it. | Refuse `include*!` and `#[path]` operands that are absolute or escape the package root, for all graph packages. |
| CA-08 | clause-to-line | Minor | cfg facts for pruning and `cfg!` selection | V4:245-247 | `R:1433-1445`; `R:2294-2299` (cfg probes without rustflags); compare the `--cfg` guard used only at `R:2151` | Cargo derives `CARGO_CFG_*` from the target cfg including effective rustflags, joining multiple values with commas (`CB/environment-variables.html:437-458`; rustflags inclusion is [INFERENCE]). Example, no `--target`: `RUSTFLAGS='--cfg target_os="windows"'` plus the rustc lint allowance [INFERENCE: `explicit_builtin_cfgs_in_flags`]. The pruner evaluates `!(env::var("CARGO_CFG_TARGET_OS").as_deref()==Ok("linux"))` as false and deletes the block before template matching. At runtime `CARGO_CFG_TARGET_OS="linux,windows"`, so the block, which may contain arbitrar…

## Summary

- Total findings: 8
- By severity: Critical=0 Major=5 Minor=3 Informational=0
- By lens: commitment-coverage=6 clause-to-line=2 deferred-cannot-silently-succeed=0 who-controls=0 field-name=0 deferral-justification=0. Lens-6 wrong-in-part dispositions are counted under CA-01, CA-02, CA-03 and CA-05.
- Round-1 closure: closed = R1-CA-02, R1-CA-06, R1-CA-07, R1-CA-08. Partially closed = R1-CA-01, R1-CA-03, R1-CA-04, R1-CA-05. Not closed = none.
- Highest severity: CA-01 (`CARGO_BUILD_RUSTFLAGS` bypasses the sysroot, linkage and `--cfg` refusals), CA-02 (`--codegen` long form and unclassified input-bearing rustflags), CA-03 (host linker unbound in cross builds).
- Recommended next step, in order:
  1. CA-01 and CA-02: one effective-rustflags resolver with an allowlist grammar, plus refusal of unmirrored `CARGO_*` config env keys. This also covers CA-04's env path.
  2. CA-04: bind or refuse the runner.
  3. CA-03: host-linker driver or refusal.
  4. CA-05: fail-closed generic build-script path.
  5. CA-08, CA-06, CA-07.
- Regression tests the parent should add: `CARGO_BUILD_RUSTFLAGS` with `--sysroot`, `-L` and `--cfg`; `--codegen link-arg=` and `--codegen linker=`; `CARGO_TARGET_<HOST>_LINKER` with `--target` set to a different darwin triple; `CARGO_TARGET_<HOST>_RUNNER` on `cargo test`; a path build-dependency spawning a process from library code, and a `build.rs` with `std::fs::read`. After the fixes, run them together with `T38` and the existing v4 toolchain suites.
- Not covered by this lens pack: concurrency, resource exhaustion, error atomicity, crate-byte supply-chain authenticity, and the input closure of arbitrary `RUSTC_WRAPPER` scripts, which are bound as executables only. Also not covered: [INFERENCE] `CARGO_UNSTABLE_*` env forms on nightly, including Kani's pinned nightly, which bypass the file-only `[unstable]` refusal at `R:454`.

Not checked: pinned allowlist hashes against upstream crate bytes; the rustc lint name and version in CA-08; Cargo's rustc cwd in CA-06. Risk: CA-01 through CA-05 each let an unchanged evidence identity cover changed inputs, so a real run could reuse stale evidence.
