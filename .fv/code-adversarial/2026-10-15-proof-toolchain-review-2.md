# Code-adversarial review: FV v4 proof-toolchain adapters (round 2) - 2026-10-15

- Operator: fv-code-adversary via OMP task (NOT openai-codex/gpt-6.1-sol task agents FixNativeOwnership-2, FixProducerStore-2, FixSourceBindings-2, FixAdoptionDashboard-2, FixBaseToolchain, FixRustToolchain, FixProofToolchain, nor the parent orchestrator)
- Code commit reviewed: `6c787c20f023a132856cf5119b137be25dd2303f` (parent `aa6946f`, the round-1 target). No shell tool was available, so `git diff` was not run. The current worktree files were read, and their correspondence to `6c787c2` was not checked independently.
- Intent version reviewed: no frontmatter version. `F/.fv/dispatch.json` and `F/.fv/intent.md` are both absent. This review follows the round-1 precedent and the caller's designation: canonical target `D/docs/intent.md` via `D/.fv/dispatch.json` (`omp_native.target_spec = "docs/intent.md"`), clauses I11/I12. The normative dependency contract is `F/docs/execution-evidence-v4.md` together with `F/.fv/changes/2026-10-14-execution-evidence-v4.md` § "Post-commit review dispositions (2026-10-15)".
- Ledger version reviewed: `F/.fv/ledger.md` is absent. The D ledger was not re-read; round 1 recorded body "Updated 2026-10-08".
- Lens pack: evidence provenance and installed-tool closure, layered on the six crypto/enclave lenses, with selector-grammar and loader analysis.
- Lenses applied: 1 through 6, plus a round-1 closure table.

Path aliases: `F` = `/Users/mv/Development/reliq-fv-wt/evidence-perf`; `D` = `/Users/mv/Development/burnt/dossier-wt/evidence-perf`; `P` = `F/tools/evidence-v4/evidence-v4-toolchain-proof.ts`; `M` = `F/tools/evidence-v4/evidence-v4-lake-metadata.lean`; `S` = `F/tools/evidence-v4/evidence-v4-source.ts`; `TC` = `F/tools/evidence-v4/evidence-v4-toolchain.ts`; `R` = `F/tools/evidence-v4/evidence-v4-run.ts`; `T` = `F/tests/r38_evidence_v4_proof_review.py`; `V4` = `F/docs/execution-evidence-v4.md`; `DI` = `D/docs/intent.md`; `Q` = `/opt/homebrew/Cellar/quint/0.33.0/libexec/lib/node_modules/@informalsystems/quint/dist/src`; `L` = `/Users/mv/.elan/toolchains/leanprover--lean4---v4.33.1/src/lean/lake/Lake`.

The accepted limits were not re-raised: Linux group-signal refusal, and Lake source coverage being Lean-specific (non-`.lean` files under source and input directories). Caller-reported test results were accepted as reported and not rerun. None of the counterexamples below were executed. They are static and grounded in the cited source. Uncovered classes: concurrency/recovery, arithmetic, resource exhaustion, storage atomicity, supply-chain authenticity, and C-compiler flag closure for `moreLeancArgs`/`moreLinkArgs` (this delta did not change that, and it was not re-audited).

---

## Round-1 closure

| Round-1 ID | Fix evidence | Residual | Verdict |
|---|---|---|---|
| R1-CA-01 Lake source closure | M:38-49 emits the effective `sourceDirectories` and `inputPaths`. These match Lake's `Package.srcDir` (L/Config/Package.lean:352-353), `LeanLib.srcDir` (L/Config/LeanLib.lean:34-35) and `InputFile/InputDir.path` (L/Config/InputFile.lean:21-22,35-36). P:1008-1031 refuses anything outside the hashed roots and the project, or inside generated namespaces. S:248-268 requires each required file and every `*.lean` file under each required directory to be in the recipe closure. R:526 runs this for every physical execution before candidate selection. T:288-306,322-345 cover the stated routes. | The `..`-after-symlink spelling still bypasses the refusal (CA-05). | partially closed |
| R1-CA-02 Lake native closure | M:74-79 now checks `moreLinkObjs`/`moreLinkLibs` on the package and on every `lean_lib`/`lean_exe`. Anonymous and `extern_lib` declarations are still refused. T:308-320. | Custom facets can supply typed `Dynlib`/`FilePath` inputs through `plugins`, `dynlibs`, `needs`, `defaultFacets` and `nativeFacets`. They are neither reported nor refused (CA-01). | partially closed |
| R1-CA-03 TLC JVM loader | P:414-423 admits only `maxHeap` matching `^-Xmx[1-9][0-9]*[kKmMgG]?$` and `stackSize` matching `^-Xss…$`, and refuses every other key. This matches Q/tlc.js, which passes both values verbatim as Java argv. `parseJSON` rejects duplicate keys and uses null-prototype objects (`F/tools/evidence-v4/evidence-v4-model.ts:551-566`), so there is no divergence from Quint's `JSON.parse`. T:151-200. | The grammar applies only when the adapter declaration's own subcommand is `verify` (CA-03). The config path is resolved lexically (CA-05). The TLC classpath JAR is unvalidated when `APALACHE_JAR` is set (CA-06). | partially closed |
| R1-CA-04 Lean selector identity | P:695-718 compares, for every lean/lake recipe and check context, the canonical entry plus `selectedLean` (toolchain, home, lean, lake). `lake +B` and alternate entries are refused. T:365-397. | Recipes entered through `elan run <tc> lake …` skip the comparison yet pass `assertCommandBound` (CA-02). `leanOptions` misparses Lake's CLI grammar (CA-04). | partially closed |

## Lens 1 - Commitment coverage

| Commitment | Attacker DoFs | Bound by | Gap |
|---|---|---|---|
| Lake effective build program (tool identity + source requirements) | Custom `library_facet`/`module_facet`/`package_facet` code declared in `lakefile.lean`, selected via lib `defaultFacets`, `needs`, `nativeFacets`, `plugins`, `dynlibs` | M:13-33 builds `mkPackage cfg fileCfg`, which discards `fileCfg.facetDecls`. Lake installs them into the workspace (L/Load/Resolve.lean:73; L/Load/Workspace.lean:39; L/Load/Lean/Eval.lean:180-193). | CA-01 |
| Lake srcDir / input / path-package location | Raw `..` segments that follow a symlinked component | P:1014 and P:910-914 apply lexical `path.resolve` before `canonicalToolPath`. Lake keeps `..` raw: `FilePath.normalize` touches only separators and drive letters (`…/src/lean/Init/System/FilePath.lean:84-90`). | CA-05 |
| TLC config / APALACHE_JAR location | Same lexical `..` | P:412 and P:451-453 use `path.resolve`. Quint `readFileSync` and the `apalache-mc` shell resolve physically. | CA-05 |
| TLC classpath JAR | Manifest `Class-Path`/`INDEX.LIST` on the dist JAR that TLC actually runs | P:451-480 validates only `APALACHE_JAR \|\| default`. Q/tlc.js `findApalacheJar` always uses `apalacheDistDir(version)/apalache/lib/apalache.jar` on `-cp`. | CA-06 |
| Lean distribution selection | Recipe toolchain, entry, `-d`/`-f`/`-K`/reconfigure | P:695-760 | CA-02 and CA-04 (counted under lenses 2 and 4) |
| Quint backend closure | Recipe subcommand and backend config | P:339-348,384-391 | CA-03 (counted under lens 2) |

## Lens 2 - Clause-to-line discharge

| Clause | Expected discharge | Actual code line | Status |
|---|---|---|---|
| DI I11 complete tool provenance (`DI:25`); V4:243 "entry executable's identity alone is insufficient" | Every recipe/check that uses an identity has its actual runtime resolved | Lean: P:695-697 keeps only `lean`/`lake` basenames. TC:1618-1641 admits any argv[0] whose bytes match a file root, including `distribution/elan`. | gap: CA-02 |
| V4:231 "Subject `quint verify` additionally binds … Apalache, JVM …"; V4:227 unsupported selectors fail preflight | A verify recipe under a non-verify declaration is bound or refused | P:340-345 silently drops applications whose realpath or subcommand differ. P:346-348 and 391 then skip the backend, JVM and TLC checks. | gap: CA-03 |
| V4:227,243-245 unknown or incomplete closure fails preflight | Every Lake arrangement that affects the build is reported or refused | M:74-79 and P:858-859 (targets only) | gap: CA-01 |
| DI I12 exact recipe and dependency closure (`DI:32`) | The recipe's actual Lake selection tuple equals the declaration's | P:546-572,745-760 | partial: CA-04 |
| V4:157 prefix-closure completeness rests on the reviewed basis; Lake requirement as a defensive check | Standalone `lean` returns its direct `.lean` inputs as requirements, matching the Lake path | P:743 returns no `sourceRequirements` | Informational: CA-08 (the basis review still governs per V4:157) |
| Disposition: `.lake` excluded from the source walk | Exclude the effective generated namespaces | S:262-263 skips only directory entries named `.lake`. P:994-1005 computes the effective excludes but does not pass them on. | Informational: CA-09 (fail-closed) |
| canonicalToolPath cutover (disposition, Base row) | Deterministic spelling that admits real Lake/JVM installs | P:26-37,88-125,786-790,866-871 | discharged for JVM and Lake file paths. CA-07 [INFERENCE]: possible refusal of hardlinked elan proxies. |
| DI I13/I14 | No activation or authority change | Adapter returns metadata only (P:500,1083) | discharged within this slice |

## Lens 3 - Deferred cannot silently succeed

| Branch | Reachable from | Behavior | Status |
|---|---|---|---|
| TODO/stub/deferred markers in P, M, S | Production adapters | A grep found none | no finding |
| Unknown TLC config field or value | `identifyQuint` verify | Throws (P:421) | explicit refusal |
| Unresolved Lake target, out-of-root srcDir/input | `identifyLean` | Throws (P:858-859,1029-1030) | explicit refusal |
| Missing closure file for a required source | R:526 → S:255-257 | Throws | explicit refusal |
| Quint application with a non-matching subcommand | P:342 | Silently excluded; preflight succeeds with no backend closure | CA-03: a silent-success selector drop, not a deferred stub |

## Lens 4 - Who controls

| Field | Supplier | Validation | Gap |
|---|---|---|---|
| Lake recipe argv (`-d`, `-f`, `--packages`, `-U`) | Reviewed policy | P:546-572 recognizes only `-d x`, `--dir=x`, `-f x`, `--file=x`, `-K…`, `-R`, and exact `--packages`/`--update`. Lake also accepts `-d=x`, `-f=x`, a single argv `"--dir x"`, `--packages=f`, and `-U` (L/Util/Cli.lean:71-80,97-133; L/CLI/Main.lean:212-221,330-340). CLI overrides apply at load time (L/Load/Resolve.lean:584-587). | CA-04 |
| TLC `maxHeap`/`stackSize` | Reviewed config file | Exact memory grammar (P:414-423) | none for same-subcommand declarations |
| `APALACHE_JAR` | Sanitized env | Manifest/bootstrap checks on that JAR only | CA-05 (lexical path), CA-06 (TLC uses a different JAR) |
| Lake facets | `lakefile.lean` | None | CA-01 |
| Lean selection per application | Recipe argv, pin, Elan settings | P:695-718 for lean/lake entries only | CA-02 |

## Lens 5 - Field-name fidelity

| Field | Implied semantic | Actual value | Status |
|---|---|---|---|
| `sourceDirectories` | Effective Lake module roots | `pkg.srcDir` plus `pkg.srcDir / cfg.srcDir.normalize`, the same expression as L/Config/LeanLib.lean:34-35 | faithful |
| `inputPaths` | `input_file`/`input_dir` paths | `pkg.dir / config.path`, matching L/Config/InputFile.lean:21-22,35-36 | faithful |
| `unresolvedNativeTargets` / P:859 message "native/custom target with undiscovered callable/tool dependencies" | No callable/native input escapes discovery | Covers targets only; custom facets are callable build code and are excluded | semantically incomplete, counted once as CA-01 |
| `sourceRequirements.directories` | Directories whose Lean sources must be bound | Also receives `input_dir` paths, walked for `*.lean` only | within the accepted Lean-specific limit; no finding |

## Lens 6 - Deferral justification audit

| Deferred finding | Justification claims | Claim audit | Verdict |
|---|---|---|---|
| Disposition "Proof toolchain: CA-01 through CA-03 are refused at discovery" | (a) out-of-root srcDir refused; (b) lib/exe link objects refused; (c) unsupported TLC config refused | (a) true for direct and symlinked paths (T:288-306), false for `..`-after-symlink (CA-05). (b) true for the fields named; facets remain open (CA-01). (c) true only when the declaration's subject is `verify` (CA-03). | wrong-deferral in part: rolled into CA-01, CA-03 and CA-05, not counted separately |
| Disposition "CA-04 is fixed" | Recipe toolchain and executable compared | True for lean/lake argv[0]. False for `elan run` (CA-02) and for Lake grammar variants (CA-04). | wrong-deferral in part: rolled into CA-02 and CA-04 |
| Disposition "producer refuses any recipe whose source closure omits a required file or a `*.lean` file under a required source directory (`.lake` excluded, symlinks refused)" | Enforcement at S:248-268 | True as implemented (S:255-266, R:526) | accurate |
| Accepted limit "Lake source coverage is Lean-specific" | Non-`.lean` inputs not enforced | S:264 checks only `.lean` | consistent; not re-raised |

---

## Finding list (consolidated)

| ID | Lens | Severity | Surface | Intent ref | Code ref | Summary | Fix |
|---|---|---|---|---|---|---|---|
| CA-01 | commitment-coverage | Major | Lake custom facets (existed before the delta; the R1-CA-02 fix does not reach it) | DI I11 (`DI:25`); V4:227,243-245 | M:13-33 (facetDecls dropped), M:74-79; P:858-859; L/Load/Resolve.lean:73; L/Load/Lean/Eval.lean:180-193; L/Config/LeanLibConfig.lean (`needs`, `defaultFacets`, `nativeFacets`); L/Config/LeanConfig.lean (`dynlibs`, `plugins`) | Counterexample: a `lakefile.lean` declares a `library_facet gate` whose build code reads `/outside/flag` and fails unless it reads `ok`, and sets `lean_lib Review where defaultFacets := #[LeanLib.leanArtsFacet, `gate]`. The metadata contains no facet field and `unresolvedNativeTargets` is false. `lake build` runs `gate`. Changing `/outside/flag` changes neither the tool digest no…
| CA-02 | clause-to-line | Major | Lean selector, `elan run` | DI I11/I12; V4:235,243 | P:695-697 (basename filter), P:747 (`distribution/elan` root push in `selectedLean`); TC:1618-1641 | Counterexample: declaration `lake build` with pin A; recipe `["elan","run","leanprover/lean4:vB","lake","build"]` with the same toolchain. The basename `elan` is filtered out before any comparison. `assertCommandBound` matches `~/.elan/bin/elan` against the `distribution/elan` file root. The execution uses B while the identity records A, so changes to B escape revalidation. The same applies to any argv[0] that resolves to a bound file and is not `lean`/`lake`. | In `identifyLean`, examine every command context whose argv[0] resolves to a file in this identity. Parse `elan …
| CA-03 | clause-to-line | Major | Quint subject selection | V4:227,231,243 | P:340-345, 346-348, 384-391; D policy has separate `quint verify` and `quint run` declarations (`D/.fv/execution-policy.json:224-250`) | Counterexample: recipe `quint verify --backend=tlc --tlc-config=t.json` with toolchain `[quint-run]`, where t.json is `{"maxHeap":"-javaagent:/outside/a.jar"}`. Subjects keep only `run` applications, so `selectingVerification` is false: no Apalache, JVM or TLC check and no grammar check. `assertCommandBound` passes on the `cli` root, and Quint runs `java` with the agent. `node <cli.js> verify …` bypasses the same way through the `node/executable` root. | Refuse any command context whose argv[0] resolves to a file in this identity unless its entry …
| CA-04 | who-controls | Major | Lake CLI grammar | DI I12 (`DI:32`); V4:227,235 | P:546-572, 745-760, 880-897; L/Util/Cli.lean:71-80,97-133; L/CLI/Main.lean:212-221,275,330-340; L/Load/Resolve.lean:584-587 | (a) `lake build --packages=/tmp/o.json` remaps dependency `dep` to `{type:"path",dir:"/outside/dep"}`. Only the exact `--packages` spelling is refused. The adapter reads the manifest plus `.lake/package-overrides.json` and hashes the locked directory, while Lake builds `/outside/dep`. (b) With `lake -d=../other build`, both sides misparse identically, so the `applicationOptions` comparison passes while Lake builds `../other`. A single argv `"--dir x"` and `-f=x` behave the same way. `-U` (deprecated update) is not refused. | Mirror Lake's long/short opt…
| CA-05 | commitment-coverage | Minor | Lexical `..` before canonicalization (new code path in the delta) | V4:227,245; DI I11 | P:1014, 910-914, 412, 451-453; L FilePath.normalize/join (`…/Init/System/FilePath.lean:84-130`); S:161-163 (git-listed inputs only, so ignored `.lake/` symlinks are not seen) | Counterexample: `proofs/lean/.lake/ext` is a symlink to `/outside/a/b` and `srcDir = ".lake/ext/../../Decoy"`. Lake reads `/outside/Decoy/*.lean`. `path.resolve` collapses the path to `proofs/lean/Decoy`, a tracked decoy whose files satisfy S:248-268. Changing `/outside/Decoy` leaves the key unchanged. The same pattern defeats the TLC grammar via `--tlc-config=lnk/../cfg.json`, and affects path packages and `APALACHE_JAR`. | Pass the raw joined spelling (`is…
| CA-06 | commitment-coverage | Minor | TLC classpath JAR | V4:243 (Apalache/JVM/jars) | P:451-480; Q/tlc.js `findApalacheJar` and the `-cp jarPath` spawn | When `APALACHE_JAR` names a staged JAR, TLC still runs the dist `apalache.jar`. That JAR's bytes are hashed through the `apalache/<version>` root, but its manifest is never checked for `Class-Path`/`INDEX.LIST`, which the application class loader honours under `-cp`. A modified dist JAR's external `Class-Path` target is therefore unbound. | When backend `tlc` is selected, run the manifest checks on the dist JAR as well, or refuse `APALACHE_JAR` together with TLC. |
| CA-07 | clause-to-line | Informational | Elan proxy spelling after the cutover | Disposition, Base row | P:702-707, 747; TC:1624-1626 | [INFERENCE] If elan installs `bin/lake` and `bin/lean` as hardlinks of `bin/elan` (T:359-360 tests only symlinks), `canonicalToolPath` keeps the `bin/lake` spelling. Cross-kind applications then compare against `bin/elan`, and `assertCommandBound` requires path equality with the `distribution/elan` root, so real runs refuse. This fails closed. Deciding it needs an `lstat` of `~/.elan/bin/{elan,lake,lean}`. | Bind the resolved proxy file itself as a root, or compare `(dev, ino)` as `native.ts` does. |
| CA-08 | clause-to-line | Informational | Standalone `lean` requirements | V4:157 | P:720-743 | Direct `.lean` arguments are not returned as `sourceRequirements`, unlike the Lake path. Coverage rests solely on the reviewed basis. | Return the inputs that `lean --deps` resolves inside the project as `files`. |
| CA-09 | clause-to-line | Informational | Source walk excludes (introduced by the delta) | Disposition `.lake` exclusion | S:262-263; P:994-1005 | A custom `packagesDir` or `buildDir` inside srcDir `"."` is walked. Dependency `.lean` files or symlinks there cause a spurious refusal. Fails closed. | Pass the effective excluded namespaces into `sourceRequirements` and skip those paths. |

## Summary

- Total findings: 9
- By severity: Critical=0 Major=4 Minor=2 Informational=3
- By lens: commitment-coverage=3 clause-to-line=5 deferred-cannot-silently-succeed=0 who-controls=1 field-name=0 deferral-justification=0 (the lens-6 wrong-deferral claims are rolled into CA-01, CA-02, CA-03, CA-04 and CA-05)
- Round-1 verdicts: R1-CA-01, R1-CA-02, R1-CA-03 and R1-CA-04 are all partially closed. The stated round-1 counterexamples are now refused; the residual routes are listed above.
- Introduced by the 6c787c2 delta: CA-05 (in the new requirement path), CA-07 [INFERENCE] and CA-09. CA-01 through CA-04 and CA-06 pre-date the delta and sit on the surfaces the fixes target.
- Current D impact: D uses TOML Lake (so no facets), `lake build` and the Apalache backend. No counterexample was shown against current D artifacts. Every Major finding concerns arrangements the adapter accepts when its policy is to refuse them.
- Recommended next step: (1) refuse nonempty `facetDecls` (CA-01); (2) refuse or parse every command context bound by a Lean or Quint identity, covering `elan run`, node-entry and subcommand mismatches (CA-02, CA-03); (3) match Lake's CLI grammar exactly or allowlist exact forms, refusing `--packages=` and `-U` (CA-04); (4) stop applying lexical `path.resolve` before `canonicalToolPath` (CA-05); (5) validate the TLC dist JAR manifest (CA-06); (6) add T cases for each of these. Then rerun the proof, source and public-factory suites once and re-review.
- Not checked: the git diff itself, the D ledger, darwin-native flag closure, whether the elan proxies on this host are hardlinks (CA-07), and whether Lake/Lean keep raw `..` in module paths all the way down to file opens (CA-05 assumes they do).
