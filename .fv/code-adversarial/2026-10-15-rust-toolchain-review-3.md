# Code-adversarial review: evidence-v4 Rust toolchain adapter, round 3 - 2026-10-15

- Operator: fv-code-adversary via OMP task (NOT openai-codex/gpt-6.1-sol task agents R2FixBase, R2FixRust, R2FixProof, R2FixStore, R2FixNative or R2FixAdoption, and NOT the parent orchestrator)
- Code commit reviewed: `34a7240` (parent `6c787c2`, the round-2 target). The caller supplied the commit identity. I did not check it with Git.
- Intent version reviewed: no frontmatter version. `F/.fv/dispatch.json` and `F/.fv/intent.md` are both absent; the `.fv/` tree holds only `attacks/`, `changes/` and `code-adversarial/`. As in round 2, I used the contract the caller designated as normative: `F/docs/execution-evidence-v4.md` (V4), especially V4:227-229, 237-240, 251, 263-265, 281 and 354. I also used the round-2 disposition table at `F/.fv/changes/2026-10-14-execution-evidence-v4.md:129-142` (CR).
- Ledger version reviewed: not re-read this round. Round 2 recorded `D/.fv/ledger.md` as `Updated: 2026-10-08`. No ledger link is discharged by this adapter.
- Lens pack: crypto/enclave six-lens baseline, plus tool/input-provenance and bounded-parser lenses for the Rust adapter
- Lenses applied: 1 through 6

Abbreviations: `F`=`/Users/mv/Development/reliq-fv-wt/evidence-perf`; `D`=`/Users/mv/Development/burnt/dossier-wt/evidence-perf`; `R`=`F/tools/evidence-v4/evidence-v4-toolchain-rust.ts`; `C`=`F/tools/evidence-v4/evidence-v4-toolchain-common.ts`; `TC`=`F/tools/evidence-v4/evidence-v4-toolchain.ts`; `T38`=`F/tests/r38_evidence_v4_rust_review.py`; `CB`=`~/.rustup/toolchains/1.97.1-aarch64-apple-darwin/share/doc/rust/html/cargo/`; `KD`=`~/.kani/kani-0.67.0`. Round-2 findings are `R2-CA-0N`. New findings are `CA-0N`.

This was static inspection only. I ran no tests, builds or Git commands. The parent's 216/216 Darwin result and the real Dossier captures are accepted as reported; none of them exercises the counterexamples below. Behaviour of Cargo, rustup, rustc or Kani that is not in `CB` or `KD` is marked [INFERENCE].

## Round-2 closure verdicts

| Round-2 | Disposition (CR:139) | Evidence | Verdict |
|---|---|---|---|
| R2-CA-01 `CARGO_BUILD_RUSTFLAGS` ignored | refused | `R:1706` checks `CARGO_BUILD_RUSTFLAGS` and `CARGO_BUILD_RUSTDOCFLAGS`. `R:1691-1692` refuses unknown `CARGO_BUILD_*` keys. `T38:287,573` | **closed**. The disposition says "every rustflags source", but two more sources are still unread: CA-01 and CA-02. |
| R2-CA-02 `--codegen` and unclassified operands | refused (allowlist) | `assertReviewedRustFlags` (`R:1625-1649`) refuses every token except `-C link-arg=--allow-undefined`, and that one only for `wasm32-unknown-unknown`. It handles the `-C`, `-CX`, `--codegen` and `--codegen=` spellings. `T38:595-634` | **closed** |
| R2-CA-03 host linker in cross builds | refused | Config `[target.<host>] linker` is refused at `R:1682`; `CARGO_TARGET_<HOST>_LINKER` at `R:1697-1698`. `T38:636` | **closed** for configured linkers. The default host linker is still unbound for non-darwin/linux targets: CA-08. |
| R2-CA-04 runner | refused | `R:1681` (config) and `R:1696` (env). cfg-keyed tables are refused at `R:1676,1730`. `T38:657-671` | **closed** |
| R2-CA-05 generic build-script classifier | refused | Every build script must be fingerprint-reviewed (`R:1801`), and cc users must be `native` (`R:1804`). Every build-dependency, transitively, must be crates.io with an exact package fingerprint (`R:1480-1502`). `T38:673-707` | **closed** for packages in the discovered graph. Under Kani the graph itself can be incomplete: CA-05. |
| R2-CA-06 relative link-arg | refused | The rustflags allowlist admits no file operand. `T38:709-722` | **closed** |
| R2-CA-07 `include*!` / `#[path]` | fixed | `assertRustSourceIncludes` (`R:1157-1225`) runs for every graph package (`R:1792`) and requires literal operands inside the package. | **closed** for the literal macro names. A renamed import bypasses the scan: CA-07. |
| R2-CA-08 cfg facts | refused | `--cfg` in any rustflags source is refused by the allowlist (`R:1625-1649`). `T38:813` | **closed** |

### Focus questions

- **Is the rustflags allowlist complete across every Cargo source?** Not yet. The following sources are all checked:
  - `CARGO_ENCODED_*`, `RUSTFLAGS`/`RUSTDOCFLAGS`, `CARGO_BUILD_*` and `CARGO_TARGET_<T>_*` in the environment (`R:1699-1714`).
  - `build.*` and `target.<triple>.*` in discovered config files and in inline `--config` values (`R:1673-1684`).
  - `host.*` and config-file `profile.*.rustflags`. These need unstable gates, which are refused at `R:378-380`, `R:454` and `R:1690`.

  Two sources are still unchecked:
  - Profile `rustflags` declared in the manifest. These are enabled by `cargo-features`, which works under Kani's pinned nightly (CA-01).
  - Files pulled in through `include` from a `--config <file>` argument (CA-02).
- **Is the build-script fingerprint binding exact?** Yes. A reviewed script needs the exact crates.io source string, `name@version`, the SHA-256 of the `src_path` bytes and every listed helper file (`R:1504-1541`). Build helpers bind `Cargo.toml` plus every `.rs` file (`R:1462-1502`). Package bytes are bound in full, except `.git`, `.cargo-ok` and the target directory (`applicationGraph`, `R:791-803`).

  I grepped the installed `build.rs` of the reviewed crates in `~/.cargo/registry/src/index.crates.io-*` (first 20 of 23 matching files). Only crossbeam-utils pulls in sibling Rust files (`include!("no_atomic.rs")`, `include!("build-common.rs")`), and both are listed at `R:1351-1356`. anyhow, proc-macro2 and thiserror feed probe files to rustc. Those files are package-bound compiler inputs, not build-program code. blst's `libblst.a` check reads a package-local file, which is also package-bound. I found no exactness defect. One residual remains: scripts outside the discovered graph are never reviewed (CA-05).
- **Is the rustup driver binding correct?** It reimplements rustup's selection order: `+toolchain` > `RUSTUP_TOOLCHAIN` > for each directory, override then toolchain file > default (`R:485-511`). It then binds `rustup which --toolchain <name>` for cargo and rustc (`R:519-521`). One defect: a `rust-toolchain.toml` that uses `path` instead of `channel` silently falls back to the default toolchain (CA-03). The derived-tree path for non-adapter declarations (`TC:698-703`) uses rustup's own `rustup which <name>` in the cwd, so it does not have this defect.

---

## Lens 1 - Commitment coverage

| Commitment | Attacker DoFs | Bound by | Gap |
|---|---|---|---|
| Effective rustflags (sysroot, `@file`, `-L`, `--extern`, `--cfg`) | Every Cargo rustflags source, including manifest `[profile.*] rustflags` under `cargo-features` | Env and config checks only (`R:1652-1716`). No manifest parsing; nothing matches `cargo-features` or `RUSTC_BOOTSTRAP` in `F/tools/evidence-v4` | CA-01 |
| Cargo configuration set | Files reached through `include` from a `--config <file>` argument | `include` is refused only in the discovered-file loop (`R:429`). The CLI loop (`R:434-447`) merges `include` as an ordinary value | CA-02 |
| `cargo`/`rustc`/`sysroot` roots under rustup | `[toolchain] path` in `rust-toolchain.toml` | `R:500-511` reads only `channel`, then falls back to `default_toolchain` | CA-03 |
| Kani `solver` root | `#[kani::solver(bin = ...)]` and `[package.metadata.kani.flags]` | Only the CLI `--solver` is checked (`R:2174-2175`) | CA-04 |
| Compile-time file inclusion | Renamed imports of `include`, `include_str` and `include_bytes` | The regex `R:1196` requires the literal macro name followed by `!` | CA-07 |
| Host-unit linker, target outside darwin/linux | PATH-selected host `cc` for proc-macro dylibs | `drivers.linker` covers only the target (`R:1738-1746`) | CA-08 |
| Reviewed build programs, package identities | name/version/source/checksum, build-program bytes | `R:631-661`, `R:1462-1541`, `R:791-803` | No gap |

## Lens 2 - Clause-to-line discharge

| Clause | Expected discharge | Actual code line | Status |
|---|---|---|---|
| V4:229 "unlisted rustflags/rustdocflags tokens from any Cargo source" refuse | All rustflags sources checked | `R:1652-1716`; manifest profiles and CLI-file includes unchecked | gap: CA-01, CA-02 |
| V4:229 "configured Cargo runners and host linkers" refuse | All config files checked | Included files are unchecked (`R:434-447`) | gap: CA-02 |
| V4:237 "Resolve actual selected Cargo/compiler/sysroot" | Rustup-selected toolchain, every selector form | `R:494-521` | gap: CA-03 |
| V4:238 "CBMC/solver" for Kani | Actually selected solver | `R:2174-2175` | gap: CA-04 |
| V4:238, V4:265 "Kani must obtain that graph with its own distribution-selected pinned compiler/sysroot ... configuration" | Graph under Kani's effective cfg | Probes use `runtime.env` (`R:1999-2004,2195`) without Kani's `--cfg=kani` | gap: CA-05 |
| V4:229 "every other form refuses before dispatch" for the program behind `cargo kani` | Alias and subcommand-path selection modeled or refused | No top-level config key allowlist (`R:391-456`). Launcher resolved from PATH (`R:1933`) | gap: CA-06 |
| V4:240 "PATH-selected cc ... attested"; V4:281 | Host linker for host units | `R:1738-1746` | partial: CA-08 |
| V4:229 "unreviewed build scripts" refuse | All graph build scripts reviewed | `R:1793-1804` | discharged for the discovered graph |
| V4:263-265 source-qualified identities | Exact source strings and bytes | `R:631-661,791-803` | discharged |
| V4:251 unknown closure is a preflight error | Unmodeled forms refuse | Partly; see CA-01..CA-06 | partial |

## Lens 3 - Deferred cannot silently succeed

| Branch | Reachable from | Behavior | Status |
|---|---|---|---|
| `TODO`/stub/mock/shortcut in `R` | grep | none found | none |
| Toolchain file without `channel` | `R:503` returns `undefined` → `R:511` default | Proceeds with a different toolchain than rustup selects for `path` files | gap: CA-03 |
| `include` value from a CLI config file | `R:434-447` | Merged without error and never followed | gap: CA-02 |
| Unreviewed build script, cross-target cc host unit, external relative PATH | `R:1801`, `R:1799-1800`, `R:1003-1004` | Explicit refusal | acceptable |

## Lens 4 - Who controls

| Field | Supplier | Validation | Gap |
|---|---|---|---|
| Workspace and dependency manifests (`cargo-features`, `[profile.*] rustflags`, `[package.metadata.kani]`) | Project and dependency authors | Bytes hashed; semantics never read | CA-01, CA-04 |
| `--config <file>` contents | Recipe argv plus a repo file | No `include` check (`R:434-447`) | CA-02 |
| `rust-toolchain.toml` | Project | Only `channel` read (`R:503`) | CA-03 |
| `[alias]` table, `CARGO_ALIAS_<name>` (CB `reference/config.html:579-597`) | Config files, recipe environment | No check | CA-06 |
| Harness attributes (`#[kani::solver]`, `KD/library/kani_macros/src/lib.rs:87-94`) | Project source | Not inspected | CA-04 |

## Lens 5 - Field-name fidelity

| Field | Implied semantic | Actual value | Status |
|---|---|---|---|
| `cargo`, `rustc`, `sysroot` roots | Toolchain rustup actually runs | Default toolchain when the file uses `path` | gap, counted under CA-03 |
| `solver` root | Solver CBMC uses | Distribution kissat, even when the harness selects `bin=` | gap, counted under CA-04 |
| `config/Cargo.lock` | Lockfile Cargo resolves from | `workspace/Cargo.lock` even if `resolver.lockfile-path` is set (stable in 1.97, CB `reference/unstable.html:2106`) | observation only; metadata uses the same config, so I found no stale-reuse path |
| `cargo-incremental` namespace | Effective incremental directory | `R:2047-2061` | faithful |

## Lens 6 - Deferral justification audit

| Deferred finding | Justification claims | Claim audit | Verdict |
|---|---|---|---|
| R2-CA-01 (CR:139 "every rustflags source") | All rustflags sources refuse | False for manifest profile rustflags and for CLI-file includes | wrong in part. Counted as CA-01, CA-02 |
| R2-CA-03/04 ("host linkers, runners") | Every configured runner and host linker refuses | False for runners and linkers set in an included file. The default host `cc` is not attested on non-darwin/linux targets | wrong in part. Counted as CA-02, CA-08 |
| R2-CA-05 ("unreviewed build scripts") | Every build script that runs is reviewed | True for the discovered graph. Under Kani the graph omits `cfg(kani)` dependencies | wrong in part. Counted as CA-05 |
| R2-CA-07 ("source inclusions are scanned") | Every inclusion is scanned | False for renamed imports | wrong in part. Counted as CA-07 |
| CR:139 "Dossier's 22 build programs ... exact fingerprints" | Count and exactness | Exactness holds (focus answer above). The count cannot be checked without Dossier's resolved graph | not decidable |
| Accepted limits (Linux signaling, Lake, source CA-10, unreviewed revisions) | Out of scope | Not contradicted | no finding |

---

## Finding list (consolidated)

| ID | Lens | Severity | Surface | Intent ref | Code ref | Summary | Fix |
|---|---|---|---|---|---|---|---|
| CA-01 | commitment-coverage | Major | Manifest-declared rustflags | V4:229,237,238,251 | `R:1652-1716` (env/config only); no `cargo-features` handling in `F/tools/evidence-v4` | Kani always builds with nightly `cargo` (`KD/rust-toolchain-version` = `nightly-2025-11-21`; `R:1965-1966`), and nightly accepts `cargo-features`. Counterexample: workspace `Cargo.toml` gets `cargo-features = ["profile-rustflags"]` (CB `reference/unstable.html:971-994`) and `[profile.dev] rustflags = ["@/opt/kani.args"]`. rustc reads `/opt/kani.args`, which can supply `--cfg`, `-L` or `--extern` operands. The adapter never reads manifest profiles. Editing `/opt/kani.args` leaves the identity unchanged, so the old PASS is reused. The same works for `cargo-toolchain` with a `+nightly…
| CA-02 | commitment-coverage | Major | `--config <file>` include | V4:229,237 | `R:429` (discovered files only) vs `R:434-447` | Counterexample: recipe `cargo test --config ci/cargo.toml -p app`. `ci/cargo.toml` contains `include = ["/opt/shared/rust.toml"]`, and that file sets `[build] rustflags = ["--sysroot=/opt/alt-rust"]` or `[target.<host>] runner = "/opt/run.sh"`. `include` is stable since 1.93 (CB `reference/unstable.html:2100-2102`; `reference/config.html:442-493`). The adapter merges `include` as plain data, never loads the target, and `assertReviewedCargoConfiguration` sees no rustflags or runner. Cargo processes the include [INFERENCE: CLI config files are loaded with includes]. Edits to `/opt/shared/rust.toml` never re-key. A runner can fake PA…
| CA-03 | commitment-coverage | Major | Rustup toolchain-file selection | V4:237, V4:227 | `R:500-511` | Counterexample: repo `rust-toolchain.toml` contains `[toolchain]\npath = "/opt/rust-dev"`, and the recipe is `cargo test -p app` through the rustup proxy. `R:503` returns `undefined` for the missing `channel`, the loop breaks, and `R:511` selects `default_toolchain`. The adapter then binds that toolchain's cargo, rustc and sysroot. rustup runs `/opt/rust-dev/bin/cargo` [INFERENCE: rustup toolchain-file `path` key]. Rebuilding `/opt/rust-dev` never changes the identity, so stale PASS evidence is reused, and the `cargo`/`rustc`/`sysroot` labels name the wrong toolchain. | When a toolchain file is found, require `toolchain.channel` and refuse `path` or a mis…
| CA-04 | commitment-coverage | Major | Kani solver selection | V4:238 ("CBMC/solver") | `R:2174-2175`; `KD/library/kani_macros/src/lib.rs:87-94` | Only the CLI `--solver` is checked. A harness `#[kani::proof] #[kani::solver(bin = "/opt/homebrew/bin/kissat")]`, or `[package.metadata.kani.flags] solver = "bin=/opt/sat"`, makes CBMC run that external binary [INFERENCE: Kani `bin=` solver form and metadata flags]. The `solver` root still records the distribution kissat. Upgrading or swapping `/opt/sat` keeps the identity unchanged, so stale PASS evidence is reused. A solver that wrongly answers UNSAT yields a false VERIFICATION SUCCESSFUL. | Refuse any `kani::solver(` attribute whose argument is not a distribution solver. Refuse `package.metadata.kani` / `works…
| CA-05 | clause-to-line | Major | Kani application graph | V4:238, V4:265 | `R:1999-2004` (`runtime.env` without Kani rustflags), `R:2195-2196`, `R:731-751` | `cargo tree` and `cargo metadata --filter-platform` run without Kani's `--cfg=kani`. That cfg is set by `cargo kani` (`D/crates/contract/Cargo.toml:28-29,82-83`) and reaches Cargo through its rustflags [INFERENCE]. Cargo evaluates platform tables from `rustc --print=cfg` (CB `reference/specifying-dependencies.html:529-531`). Counterexample: `[target.'cfg(kani)'.dependencies] foo = { git = "..." }`. foo is built, but it has no `packages/<digest>` root and its build script never reaches `R:1793-1804`. Edits to its checkout never re-key. Dossier does not use such tables today. | Run the Kani tree/metadat…
| CA-06 | who-controls | Major | Program behind `cargo kani` | V4:229, V4:238 | `R:391-456` (no top-level key allowlist); `R:1933` (PATH launcher) | `[alias] kani = ["run","--manifest-path","/opt/fk/Cargo.toml","--"]` or `CARGO_ALIAS_KANI` (CB `reference/config.html:579-597`) replaces the Kani subcommand. Built-in commands cannot be aliased, but external ones can, with only a warning [INFERENCE: Cargo `expand_aliases`, rust-lang/cargo#10049]. The adapter binds the PATH `cargo-kani` and the Kani distribution, and `/opt/fk` stays unbound. The aliased program can print Kani's success line (false PASS), and edits to it never re-key. Cargo also searches `$CARGO_HOME/bin` before PATH for `cargo-<cmd>` [INFERENCE], while `R:1933` resolves PATH only. | Refuse `alias…
| CA-07 | commitment-coverage | Minor | Renamed inclusion macros | V4:237,251 | `R:1196` | `use core::include_bytes as grab; pub static K: &[u8] = grab!("/opt/keys/k.bin");` contains no `include_bytes!` token, so nothing is bound or refused. rustc reads the external file [INFERENCE: built-in macros can be imported with a rename]. `use std::include as inc; inc!("/opt/gen.rs")` splices in arbitrary code. Edits to either file never re-key. | Mark the package as dynamic (needs reviewed hash) when `include`, `include_str` or `include_bytes` appears as an identifier not followed by `!`. |
| CA-08 | commitment-coverage | Minor | Default host linker, exotic cross target | V4:240, V4:281 | `R:1738-1746` | Counterexample: `cargo build --target wasm32-unknown-unknown` on a graph with a dependency-free path proc-macro and no build scripts (any build script refuses at `R:1801`, because `R:1509-1511` reviews only darwin/linux targets). The proc-macro dylib is linked by the host PATH `cc`, but only `rust-lld` is bound. Replacing `cc` never re-keys. | When `target !== host` and the graph has host units, bind the host default linker (`cc` on darwin/linux hosts) as a `host-linker` driver, or refuse. |

## Summary

- Total findings: 8
- By severity: Critical=0 Major=6 Minor=2 Informational=0
- By lens: commitment-coverage=6 clause-to-line=1 deferred-cannot-silently-succeed=0 who-controls=1 field-name=0 deferral-justification=0. The Lens-6 wrong-in-part verdicts are counted under CA-01, CA-02, CA-05, CA-07 and CA-08.
- Round-2 closure: R2-CA-01 through R2-CA-08 are all closed for their reported forms. Residuals live in CA-01, CA-02, CA-05, CA-07 and CA-08.
- Spurious refusals of Dossier's setup: none found. Dossier's `.cargo/config.toml` has `[net]` and the wasm `--allow-undefined` rustflags, both admitted. No `rust-toolchain*` file, `cargo-features`, `--config` or `cfg(kani)` table is present. Any new top-level allowlist must admit `net`.
- Observations not raised, because I found no path to stale reuse or false PASS:
  - `CARGO_BUILD_TARGET_DIR` loses to `build.target-dir` in `cacheNamespaces` (`R:2027-2033`). This mislabels the namespace only; package exclusion uses metadata.
  - `resolver.lockfile-path` (see Lens 5).
  - If the rustup proxies were hardlinks, `canonicalToolPath` (`C:89-98`) would keep the `cargo` spelling, and `+toolchain` subjects would refuse at `R:523`. That fails closed. On this host `~/.cargo/bin/cargo` lists as 0 B, consistent with a symlink [INFERENCE].
- Recommended next step, in order:
  1. CA-02: move the include check to the merged config.
  2. CA-01: refuse `cargo-features`, `RUSTC_BOOTSTRAP` and `__CARGO_TEST_CHANNEL_OVERRIDE_DO_NOT_USE_THIS`.
  3. CA-03: require `channel` in toolchain files.
  4. CA-06: refuse aliases, add a top-level config allowlist, check launcher precedence.
  5. CA-04: solver attributes and Kani metadata flags.
  6. CA-05: Kani-cfg graph probes.
  7. CA-07, CA-08.
- Regression tests the parent should add to T38:
  - `--config` file with `include`.
  - Root manifest with `cargo-features = ["profile-rustflags"]` under a nightly selector.
  - `rust-toolchain.toml` with `path`.
  - `[alias] kani` and `CARGO_ALIAS_KANI`.
  - `#[kani::solver(bin=...)]`.
  - `[target.'cfg(kani)'.dependencies]`.
  - `use core::include_bytes as x;`.
  - wasm cross build with a path proc-macro.
- Not covered by this lens pack: concurrency, resource exhaustion, error atomicity, crate-byte supply-chain authenticity, closures of `RUSTC_WRAPPER` scripts, `KANI_HOME` path semantics, and cross-target platform filtering of build-dependencies in `cargo tree` versus metadata.

Not checked: the Kani `bin=` solver form, Kani's `--cfg=kani` transport, Cargo alias and `$CARGO_HOME/bin` precedence, rustup `path` toolchain files, and acceptance of renamed built-in macro imports. Each is marked [INFERENCE] and needs a one-fixture run to confirm. Risk: CA-01 through CA-06 each let an unchanged identity cover changed inputs, and CA-04 and CA-06 can also yield a false PASS.
