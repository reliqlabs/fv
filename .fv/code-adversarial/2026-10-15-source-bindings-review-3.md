# Code-adversarial review: FV v4 evidence producer, source bindings and Lake source requirements, round 3 - 2026-10-15

- Operator: fv-code-adversary via OMP task (NOT openai-codex/gpt-6.1-sol task agents R2FixBase, R2FixRust, R2FixProof, R2FixStore, R2FixNative, R2FixAdoption, and NOT the parent orchestrator)
- Code commit reviewed: `34a7240` (parent `6c787c2`). The caller supplied both IDs. I ran no git command and read the current worktree files.
- Intent version reviewed: `F/docs/execution-evidence-v4.md`. It has no frontmatter version, only "Status: normative contract". I read lines 227-229 (derived native identities, allowlist refusals) and line 354 (checker/recipe resource disjointness). I also read `F/.fv/changes/2026-10-14-execution-evidence-v4.md` § "Round-2 review dispositions (2026-10-15)".
- Ledger version reviewed: absent (`F/.fv/ledger.md` does not exist).
- Lens pack: crypto/enclave commitment lenses, plus path-safety, TS/Python serialization parity and evidence-freshness checks.
- Lenses applied: 1 through 6.

**Gate deviation.** `F/.fv/dispatch.json` and `F/.fv/intent.md` are both absent, so the strict gate returns `STATUS: BLOCKED`. I continued because the caller named the normative contract inside PROJECT_ROOT, the same deviation as round 2. The parent may discard this report if the strict gate is required.

Path aliases: `F` = `/Users/mv/Development/reliq-fv-wt/evidence-perf`, `D` = `/Users/mv/Development/burnt/dossier-wt/evidence-perf`, `S` = `F/tools/evidence-v4/evidence-v4-source.ts`, `R` = `…/evidence-v4-run.ts`, `T` = `…/evidence-v4-toolchain.ts`, `TP` = `…/evidence-v4-toolchain-proof.ts`, `C` = `…/evidence-v4-toolchain-common.ts`, `LM` = `…/evidence-v4-lake-metadata.lean`, `PC` = `F/scripts/fv_evidence_v4.py`, `TS` = `F/tests/r38_evidence_v4_source_review.py`, `TA` = `F/tests/r38_evidence_v4_adoption_review.py`, `V4` = `F/docs/execution-evidence-v4.md`.

Method: static reads only. Every counterexample is a static deduction marked `[INFERENCE]`. I accepted the parent's results without rerunning them (216/216 Darwin tests; real D captures admitted). These accepted limits are not re-raised: Linux group signaling, Lake coverage being Lean-specific, CA-10 whitespace divergence, and unreviewed build scripts.

Classes not covered: the scheduler, store, native lifecycle, the internals of the Rust and Kani adapters, `include_str` and other data reads during Lean elaboration (accepted limit), and shell wrappers that invoke tools no declaration names (a general policy-review boundary).

---

## Round-2 closure verdicts

| Round-2 | Verdict | Evidence |
|---|---|---|
| CA-05 `input_dir` contents | **closed** | Lake input targets that are directories now go to `inputDirectories` (`TP:1166-1170`). The walk with `all=true` requires every regular file and refuses symlinks and nonregular entries (`S:277-284`). `needs` is refused, so an input dir cannot become a hidden library dependency (`LM` `unresolvedNativeTargets`: `!config.needs.isEmpty`). Test `TS:664-683`. |
| CA-06 symlinked srcDir/input path or ancestor | **closed** | `inputPath` lstats every component from the filesystem root and refuses any symlink before applying a lexical `..` (`TP:38-47`). It is used for srcDirs and input targets (`TP:1148-1152`), package directories (`TP:1026-1040`) and Lean argv sources (`TP:840`). `assertSourceRequirements` also refuses through `safeDirectoryPath`/`safeSourcePath` (`S:263,267`). Test `TS:685-710` covers directories, files and input dirs. |
| CA-07 `.lean` suffix case | **closed** | `/\.lean$/iu` in the walk (`S:280`) and in argv subject detection (`TP:839`). Test `TS:712-726`. |
| CA-08 standalone and application `lean` subjects | **closed** | `.lean` argv subjects of every admitted `lean` application, plus the adapter subject, go into `sourceRequirements.files` before the standalone/Lake branch splits (`TP:836-846`). Standalone imports must resolve inside the selected distribution (`TP:862-871`), and other `lean` arguments are refused (`leanOptions`, `TP:582-584`). |
| CA-09 Lean/Lake command without an adapter | **closed for direct invocation** | `assertCommandBound` refuses `lean`, `lake`, `elan run … lean|lake` and any executable whose directory holds both `lean` and `lake`, unless a `lean-toolchain` adapter is in scope (`T:1724-1746`). Shell wrappers are outside this check (see uncovered classes). |
| CA-10 target-spec whitespace | accepted limit | Not re-raised. |
| CA-11 `.` root walk | **closed** for `.git` and Lake generated namespaces | The walk skips `.git`, `.lake` and the Lake-reported generated paths (`S:270-276`; `TP:1129-1147`). Non-Lake trees such as `node_modules` still fail closed (availability only, not raised). The new exclusion opens CA-13. |

## Derived native identity: TS (`S:331-373`) vs Python (`PC:305-384`) parity

| Check | TS `derivedNativeTree` | Python `_tool` | Parity |
|---|---|---|---|
| Applies only to executable/file, non-adapter, `tree`, Darwin | `S:339-343` | `PC:306-310` and `os == "darwin"` in the shape check | equal |
| Allowed entries: `selected-file` (file), `native`, `native/non-system-libraries`, `native/drivers` (directory), `native/drivers/{cargo,rustc}-0` (file), single-component library files | `S:345-352` | shape `_check` after `PC:326` | equal |
| At least one library or driver; `selected-file` present | `S:353-356` | `(libraries or drivers)` and `by_path.get("selected-file")` | equal |
| Locator mode is command/path and its basename names a present driver | `S:358-362` (`path.basename`) | `Path(...).name in driver_names` | equal (both strip a trailing `/`; `""`, `.` and `..` never match) |
| Every driver has a `[*/rustup, "which", name]` probe with exit 0 | `S:362-370` | `PC:357-370` | equal |
| `selected-file` executable and nonempty for executable declarations | absent | `PC:343-347` | Python stricter |
| Driver executable and nonempty | absent | `PC:358-361` | Python stricter |
| Library name in exact `encodeURIComponent` form, nonempty, no NUL; nonempty bytes | absent | library loop after `PC:370` | Python stricter |
| Digest recomputation | via `validateToolIdentity` | `TA` "library-byte-drift" case | equal |

Every divergence is TS-permissive and checker-strict. The TS producer cannot emit the shapes only Python rejects: it requires `X_OK` (`T:1583`), encodes with `encodeURIComponent` (`T:874`), and hashes real files. The checker therefore cannot accept what the producer would refuse, and no false PASS follows. This is a non-finding. The tests check acceptance on the Python side only (`TA:588-700`); no TS↔Python vector test exists.

---

## Lens 1 - Commitment coverage

| Commitment | Attacker DoFs | Bound by | Gap |
|---|---|---|---|
| `Closure.hash` (`S:231-246`) | Prefixes, basis, file set and bytes | `D("source-closure",…)` | No omission in the hash. Completeness depends on the Lake gate. CA-12 (LEAN_PATH olean inputs) and CA-13 (excluded generated path inside a srcDir) leave real Lake/Lean inputs outside both the closure and the tool roots. |
| Derived native `tree` digest | Selected file, dylibs, rustup driver | `D("tool-content",…)` over `selected-file` and `native/*` | The derived tree is only produced when rustup is detected by realpath basename (`T:1589-1592`). A hard-linked proxy binds only launcher bytes (CA-14). |
| Lake source requirements | srcDirs, input targets, Lean argv, exclusions | Preflight gate only, not committed | By design (producer-trusted). Not recomputed by the portable checker. |

No signature or ReportData exists in this slice.

## Lens 2 - Clause-to-line discharge

| Clause | Expected discharge | Actual code line | Status |
|---|---|---|---|
| V4:138 "ignored dependency files explicitly consumed by a tool must be declared … or included in the appropriate tool/config attestation" | Every Lake-consumed input is in the closure or a hashed tool root | srcDir `.lean`, input files and dirs: `TP:1148-1171`, `S:262-284`. `LEAN_PATH` entries anywhere under the root package are admitted with no binding (`TP:1175-1179`) | **gap**, CA-12 |
| V4:229 "Discovery binds only configuration forms it fully models; every other form refuses" | Generated-namespace exclusion never hides sources | `S:270-276` skips any Lake-reported generated path, even one strictly inside a srcDir (`TP:1129-1147`) | **gap**, CA-13 |
| V4:227 derived tree "when a cargo/rustc … locator resolves to a rustup shim"; V4:249 "launcher hashes cannot stand in for installed" bytes | Detect the shim by identity, not by spelling | `T:1589-1592` and `T:698` test `basename(realpath).startsWith("rustup")`. `canonicalToolPath` keeps a hardlink's basename (`C:88-111`) | **partial**, CA-14 |
| V4:227 "Producer and portable checker accept no other derived roots" | Same root set on both sides | `S:345-356`; `PC:318-342` | discharged (parity table) |
| V4:26/157 symlink refusal on traversed source | Refuse symlinks on every required path | `TP:38-47`; `S:263,267,277` | discharged (CA-06) |
| V4:159 recompute before command | Gate before cache selection, plan and run | `R:526` inside `preflightAll`, before `selectCandidates` at `R:531-533` | discharged |
| V4:354 checker/recipe resource disjointness | Outside this slice | — | not audited |

## Lens 3 - Deferred cannot silently succeed

| Branch | Reachable from | Behavior | Status |
|---|---|---|---|
| Non-Lean adapters return no `sourceRequirements` (`T:1825`) | Every non-Lean recipe | Gate passes | Accepted limit |
| Excluded generated path in `walk` (`S:270-276`) | Lake `buildDir`/`packagesDir`/cache set inside a srcDir | Subtree silently skipped | **gap**, CA-13 |
| `initialLeanPath` entry inside the root package (`TP:1177`) | `LEAN_PATH` set or inherited by policy | `continue`, no binding | **gap**, CA-12 |
| Non-rustup branch of a Darwin executable (`T:1593-1597`) | Hard-linked `cargo`/`rustc` proxy | Single-file identity of the launcher | **gap**, CA-14 |
| Missing required directory or nonregular entry | `S:267,279` | Throws | fail-closed |

## Lens 4 - Who controls

| Field | Supplier | Validation | Gap |
|---|---|---|---|
| `excludedPaths` | Lake config (`buildDir`, `packagesDir`, cache) via the metadata probe | Must lie inside the project; a srcDir *inside* an excluded path is refused (`TP:1163`), but not the reverse | CA-13 |
| `initialLeanPath`/`initialSourcePath` | Policy environment (`LEAN_PATH`, `LEAN_SRC_PATH`) through Lake `Env.compute` | Inside the distribution or *any* package directory, including the unhashed root package (`TP:1175-1179`) | CA-12 |
| Rustup detection | Install layout of the `cargo`/`rustc` proxy | Realpath basename only | CA-14 |
| Lean argv `.lean` subjects | Reviewed recipe argv | `inputPath`, inside the project, regular file (`TP:840-844`) | none |
| `sourceRequirements.directories`/`inputDirectories` | Lake metadata | `inputPath`, kind check, hashed-root or project containment (`TP:1148-1171`) | none |

## Lens 5 - Field-name fidelity

| Field | Implied semantic | Actual value | Status |
|---|---|---|---|
| `sourceRequirements.directories` | Lake srcDirs | srcDirs only; input dirs are split out (`TP:1166-1170`) | faithful (CA-05 mismatch closed) |
| `sourceRequirements.excludedPaths` | Generated namespaces only | Any Lake-reported generated path, which can sit inside a srcDir | Mismatch; counted under CA-13 |
| Derived `selected-file` + `native/drivers/<x>-0` | Rustup shim plus selected driver | Built only on basename detection | Counted under CA-14 |

## Lens 6 - Deferral justification audit

| Deferred finding | Justification claims | Claim audit | Verdict |
|---|---|---|---|
| Source CA-06 "refused at discovery: symlink-before-`..` traversal" | Every required path refuses symlinks | `TP:38-47`; `S:263,267,277`; `TS:685-710` | valid |
| Source CA-09 "refused: Lean commands without an adapter" | Lean/Lake commands need the adapter | `T:1724-1746` for direct, `elan run` and co-located binaries | valid as worded |
| Base CA-13..15 "rustup-selected drivers are bound in derived tree identities" | The shim is detected and its driver bound | Detection is by realpath basename (`T:1592`). The Darwin test uses a *symlink* proxy (`F/tests/r38_evidence_v4_toolchain_review.py:988`). A hardlink is untested and undetected. | Partially false; CA-14 |
| "Lake source coverage is Lean-specific" (accepted) | Only Lean reports requirements | `T:1825`; only `identifyLean` sets `sourceRequirements` | valid |
| Source CA-10 (accepted) | Divergence fails closed | Not re-audited | not raised |

---

## Finding list (consolidated)

| ID | Lens | Severity | Surface | Intent ref | Code ref | Summary | Fix |
|---|---|---|---|---|---|---|---|
| CA-12 | clause-to-line | Major | `LEAN_PATH` under the root package | V4:138, 229, 157 | `TP:1175-1179` (`all.some(pkg => inside(pkg.directory, real))` with `all[0].directory = cwd`); `TP:1131` (only `distribution` and `packages/*` are hashed); `LM` `initialLeanPath` | Discovery admits any `LEAN_PATH` entry inside the root Lake package. Nothing binds the files there: not the source walk (`.lean` only), not a tool root, not the inventory when they are ignored. `[INFERENCE: Lake appends env.initLeanPath to the search path passed to lean and loads non-workspace imports as prebuilt .olean]` Counterexample: policy `set.LEAN_PATH = "<root>/proofs/lean/vendor"`. `vendor/` is gitignored and holds `Ext/Lemma.olean`; `Dossier.lean` has `import Ext.Lemma`. Run 1 pass…
| CA-13 | clause-to-line | Minor | Generated path inside a srcDir hides sources | V4:138, 229 | `TP:1129-1147`, `TP:1163` (refuses only srcDir ⊆ excluded); `S:270-276` | The walk skips any Lake-reported `buildDir`/`packagesDir`/cache path, even one strictly inside a source directory. `[INFERENCE]` Counterexample: `proofs/lean/lakefile.toml` with `buildDir = "Proofs/out"`, `[[lean_lib]] name = "Proofs"`. `Proofs.lean` imports `Proofs.out.Helper`, and `Proofs/out/Helper.lean` is tracked. The reviewed prefixes omit `proofs/lean/Proofs/out/`. The gate skips it, so `Helper.lean` is never required. A committed edit to `Helper.lean` is a content-only change outside the closure, so the old PASS is reused. | At `TP:1145-1171`, refuse when any excluded generated path …
| CA-14 | clause-to-line | Minor | Hard-linked rustup proxy; Cargo without an adapter | V4:227, 249, 251 | `T:1589-1597`, `T:698`; `C:88-111` (hardlink basename preserved); `T:1724-1746` (only Lean commands require an adapter) | `[INFERENCE: rustup's installer links ~/.cargo/bin/{cargo,rustc} as hard links to rustup, falling back to symlinks]` On such a host, `canonicalToolPath` returns `…/cargo`, so `rustupDriver` is false. Discovery then sees the rustup binary, which links only system libraries, and records a single-file identity of the launcher. Counterexample: declaration `{id:"cargo",kind:"executable",locator:{mode:"command",value:"cargo"},version_command:null}` with recipe `cargo test` (toolchain `["cargo"]`, no cargo-toolchain adapter; nothing refuses…

## Summary

- Total findings: 3 new. Round-2 CA-05, CA-06, CA-07, CA-08 and CA-11 are closed. CA-09 is closed for direct invocation. CA-10 is an accepted limit.
- By severity: Critical=0 Major=1 Minor=2 Informational=0
- By lens: commitment-coverage=0 clause-to-line=3 deferred-cannot-silently-succeed=0 who-controls=0 field-name=0 deferral-justification=0 (the base CA-13..15 wrong claim is counted under CA-14)
- TS/Python derived-identity parity: the accepted shapes match. Python adds byte, executable and encoding checks the TS producer already guarantees by construction, so there is no false-PASS divergence.
- Dossier impact: no spurious refusal found. `proofs/lean/lakefile.toml` uses only admitted keys; `srcDir "."` holds `Dossier.lean` and `Dossier/KeyLineage.lean` under the `proofs/lean/` prefix; `.lake` is skipped; no `LEAN_PATH`. I assumed both `.lean` files are tracked; no git check was run. None of CA-12..14 triggers on D's current policy.
- Recommended next step, in order:
  1. CA-12: refuse root-package `LEAN_PATH`/`LEAN_SRC_PATH` in Lake mode.
  2. CA-13: refuse generated namespaces nested in source/input directories.
  3. CA-14: detect rustup by inode or probe, and refuse Cargo/rustc commands without an adapter.
  4. Add one fixture per fix, then have the parent run the r38 source, proof, toolchain and adoption suites once.

Not checked: Lake's handling of `LEAN_PATH` for non-workspace imports, rustup's hardlink install on the D host (check with `stat -f %i ~/.cargo/bin/cargo ~/.cargo/bin/rustup`), and the Rust adapter's binding when the proxy is undetected. All three are unexecuted inferences. The intent-gate deviation above is the main process risk.
