# Code-adversarial review: FV v4 proof-toolchain adapters (round 3) - 2026-10-15

- Operator: fv-code-adversary via OMP task (NOT openai-codex/gpt-6.1-sol task agents R2FixBase, R2FixRust, R2FixProof, R2FixStore, R2FixNative, R2FixAdoption, nor the parent orchestrator)
- Code commit reviewed: `34a7240` (parent `6c787c2`, the round-2 target). No shell tool was available, so `git diff` was not run. I read the current worktree files and did not check independently that they match `34a7240`.
- Intent version reviewed: no frontmatter version.
  - `F/.fv/dispatch.json` and `F/.fv/intent.md` are both absent. Under the strict gate rule that would mean `STATUS: BLOCKED`.
  - I continued anyway, as rounds 1 and 2 did, because the caller named the targets explicitly. The normative target is `F/docs/execution-evidence-v4.md` (V4), including the new paragraphs at V4:227 and V4:229, and V4:354. It is read together with `F/.fv/changes/2026-10-14-execution-evidence-v4.md` § "Round-2 review dispositions (2026-10-15)" (CR:129-139).
  - The Dossier anchor is `D/docs/intent.md` I11/I12 (DI:25,32), reached through `D/.fv/dispatch.json:4`.
- Ledger version reviewed: absent (`F/.fv/ledger.md` does not exist).
- Lens pack: evidence provenance and installed-tool closure (selector grammar, path resolution, adapter gating), applied through the six crypto/enclave lenses.
- Lenses applied: 1 through 6, plus a round-2 closure table.
- Intended persist path: `F/.fv/code-adversarial/2026-10-15-proof-toolchain-review-3.md`

**Path aliases**

| Alias | Path |
|---|---|
| `F` | `/Users/mv/Development/reliq-fv-wt/evidence-perf` |
| `D` | `/Users/mv/Development/burnt/dossier-wt/evidence-perf` |
| `P` | `F/tools/evidence-v4/evidence-v4-toolchain-proof.ts` |
| `M` | `F/tools/evidence-v4/evidence-v4-lake-metadata.lean` |
| `TC` | `F/tools/evidence-v4/evidence-v4-toolchain.ts` |
| `S` | `F/tools/evidence-v4/evidence-v4-source.ts` |
| `T` | `F/tests/r38_evidence_v4_proof_review.py` |
| `DP` | `D/.fv/execution-policy.json` |
| `Q` | `/opt/homebrew/Cellar/quint/0.33.0/libexec/lib/node_modules/@informalsystems/quint/dist/src` |
| `L` | `~/.elan/toolchains/leanprover--lean4---v4.33.1/src/lean/lake/Lake` |

**Accepted limits, not re-raised:** Linux/other runtimes refuse group signaling; Lake coverage is Lean-specific; source-bindings CA-10; unreviewed build scripts refuse.

**Not covered:** concurrency/recovery, arithmetic, resource exhaustion, storage atomicity, supply-chain authenticity, C-flag closure for Lake native arguments, and nested collector child argv. V4:252 governs that last class through the collector contract.

None of the counterexamples below were executed.

---

## Round-2 closure

| Round-2 ID | Fix evidence | Residual | Verdict |
|---|---|---|---|
| CA-01 Lake custom facets | M:33-35 refuses nonempty `facetDecls`, scripts, default scripts and post-update hooks. M:77-92 flags package and target plugins and dynlibs, lib/exe `needs`, `extraDepTargets`, non-default `defaultFacets`/`nativeFacets`, and every non-input custom target. P:994-995 enforces the result. P:618-683 allowlists the `lakefile.lean` lines and the TOML keys for the root package and every dependency (`readMetadata` → `reviewedLakeConfig`). T:561. | none | closed |
| CA-02 `elan run` selector | P:560-570 rewrites `elan run <tc> lean\|lake …` to `[kind, +tc, …]` and refuses other elan forms. P:806-829 compares each application's actual selection (toolchain, home, lean, lake). TC:1725-1746 makes the lean-toolchain adapter mandatory for `elan run … lake` commands. T:688, T:723. | Precedence modelling inside `selectedLean`: CA-04 (new, different mechanism). | closed |
| CA-03 Quint subcommand mismatch | P:349-358 refuses any context that resolves to the declared CLI with a different subcommand, and any context that enters through the package or the `node` binary. T:211. | Commands whose closure contains no quint-backends adapter are never examined: CA-01. | closed for adapter-scoped commands; residual CA-01 |
| CA-04 Lake CLI grammar | P:579-607 is now a strict allowlist: `+tc` only at argv[1], `-d/--dir[=]`, `-f/--file[=]`, `-R`, `build`, and plain targets. `-d=x`, a single argv `"--dir x"`, `--packages=`, `-U` and `-K` all refuse. Override files are refused at P:928 and P:1022-1024. T:596, T:617. | none | closed |
| CA-05 lexical `..` after a symlink | P:38-48 (`inputPath`) refuses any symlinked component. It is used for srcDir/input paths (P:1150), path/git packages (P:1038-1040), the declaration `-d` (P:788), the config file (P:624), Quint configs (P:426), `APALACHE_JAR` (P:465) and Lean subjects (P:841). T:233, 322, 632, 640. | The application-side `-d` is still resolved lexically (P:880): CA-02. | partially closed |
| CA-06 TLC classpath JAR | P:471-477 adds the dist `lib/apalache.jar` to the manifest/bootstrap checks whenever any subject selects TLC. T:307. | none | closed |
| CA-07 hardlinked elan proxies | P:808 uses `sameFile` (dev, ino). P:821 binds the proxy file as `distribution/proxies/<hash>`. T:723. | none | closed |
| CA-08 standalone `lean` requirements | P:838-845 requires every `.lean` argv subject inside the project as a source file, with or without Lake. T:758. | none | closed |
| CA-09 walk excludes | P:1131-1144 passes effective generated namespaces plus `.git` as `excludedPaths`. S:271-276 skips them. T:678. | none | closed |

## Lens 1 - Commitment coverage

| Commitment | Attacker DoFs | Bound by | Gap |
|---|---|---|---|
| Lake workspace selected by an application | Application `-d` spelling | P:880 (`path.resolve`, lexical) compared with P:788 (`inputPath`, physical) | CA-02 |
| Apalache JAR actually executed | Relative `APALACHE_JAR` combined with a recipe cwd different from the adapter locator cwd | P:465-467 resolves against `context.cwd`. Quint spawns `apalache-mc` with no `cwd` option (Q/apalache.js:424-425), so the launcher's `-jar "$APALACHE_JAR"` resolves against the recipe's cwd. | CA-03 |
| Lean distribution selected by elan | Elan override database combined with a nearer `lean-toolchain` | P:723-725, P:752-757 | CA-04 (counted under lens 2) |
| Quint backend closure for a recipe | Recipe toolchain that omits every quint-backends adapter | TC:1720-1768 (Lean-only gate, then byte match) | CA-01 (counted under lens 2) |
| Lake facets, plugins, overrides, CLI | — | M:33-35, M:77-92; P:579-607, 618-683, 928, 1022-1024 | none |
| TLC config, dist JAR, JVM env | — | P:426-438, 471-498, 507-509 | none |

## Lens 2 - Clause-to-line discharge

| Clause | Expected discharge | Actual code line | Status |
|---|---|---|---|
| V4:229 "TLC options outside the `-Xmx`/`-Xss` grammar on any Quint path" refuse; V4:236 `quint verify` binds Apalache/JVM, `quint run` binds the evaluator; V4:249,251 an incomplete closure is a preflight error | Every recipe or check that invokes the Quint CLI either has a matching quint-backends identity or refuses | TC:1725-1746 gates only Lean/Lake. P:349-358 sees only contexts whose closure already includes the adapter (TC:1380-1392). | gap: CA-01 |
| V4:239 "Use the subject cwd's lean-toolchain/Lake selection"; DI I11/I12 | The identity's toolchain equals the one the proxy runs | P:757 ranks any ancestor override above a nearer pin | gap [INFERENCE]: CA-04 |
| V4:229 package overrides and facets refuse | Refusal at discovery | M:33-35, M:77-92; P:928, P:1022-1024 | discharged |
| CR:139 symlink-before-`..` refused | Every path that selects build input is resolved physically | P:880 | partial: CA-02 |
| CR:139 Lean commands without an adapter refuse | Gate in `assertCommandBound` | TC:1725-1746 | discharged |
| V4:354 checker/recipe resource disjointness | Validated by policy | not in this slice's code; DP checker `project-checker` vs recipe `apalache-server`/`lean-build` | no finding in scope |

## Lens 3 - Deferred cannot silently succeed

| Branch | Reachable from | Behavior | Status |
|---|---|---|---|
| TODO/stub markers in P and M | — | None found by reading | no finding |
| `subjects` falls back to the declaration subject when no direct Quint context exists (P:359) | Collector-only identities (DP:3176-3222) | Binds the declared `verify` subject. The collector child argv is fixed to `quint verify` with the default backend (`D/.fv/scripts/collect_quint_witness.py:207,268,646`). | no finding |
| Recipe invokes the Quint CLI with no quint-backends adapter in its closure | `assertCommandBound` | Succeeds on the `quint` file root. No backend work is done. | CA-01 (silent success; counted under lens 2) |

## Lens 4 - Who controls

| Field | Supplier | Validation | Gap |
|---|---|---|---|
| Application Lake argv | Reviewed policy | Grammar allowlist (P:579-607). The `-d` value is lexical for applications (P:880). | CA-02 |
| `APALACHE_JAR` | Sanitized env (inherited in DP:38) | Physical resolution and manifest checks, but against the adapter cwd only | CA-03 |
| `~/.elan/settings.toml` overrides | User | Parsed (P:533-556) and bound as configuration (P:750). Precedence is mis-modelled. | CA-04 |
| Lake config keys | Project and dependencies | Allowlist (P:618-683) plus effective-config checks (M) | none |

## Lens 5 - Field-name fidelity

| Field | Implied semantic | Actual value | Status |
|---|---|---|---|
| `unresolvedNativeTargets` | Undiscovered native/custom build code | Plugins, dynlibs, needs, facets and custom targets (M:77-92). Custom facet *declarations* are refused separately (M:33-35). | faithful |
| `distribution/proxies/<hash>` | Elan proxy file actually invoked | `entry.realpath` of the application argv[0] (P:821) | faithful |
| `sourceRequirements.excludedPaths` | Effective generated namespaces | Build, config-cache, artifact-cache, packages and barrel paths, plus `.git` (P:1131-1144) | faithful |
| `artifactCache`, `restoreArtifacts`, `configurationOptions` (M) | Emitted metadata | Not consumed by P. No semantic claim is made. | no finding |

## Lens 6 - Deferral justification audit

| Deferred finding | Justification claims | Claim audit | Verdict |
|---|---|---|---|
| CR:139 "Proof CA-01, CA-03..CA-05 … refused at discovery" | (a) restricted Lake DSL and CLI; (b) no package overrides; (c) symlink-before-`..` traversal refused | (a) true (P:579-607, 618-683). (b) true (P:928, 1022-1024). (c) true for the declaration, false for application `-d` (P:880). | wrong-deferral in part; rolled into CA-02 |
| CR:139 "Proof CA-02, CA-06..CA-09 … fixed" | `elan run` equality, TLC classpath manifest, inode proxies, direct `.lean` subjects, walk excludes | All true as cited in the closure table | accurate |
| CR:139 "Lean commands without an adapter" refused | TC:1725-1746 | True for Lean. V4:229 makes the same claim for "any Quint path", and no Quint equivalent exists. | wrong-deferral by omission; rolled into CA-01 |

---

## Finding list (consolidated)

| ID | Lens | Severity | Surface | Intent ref | Code ref | Summary | Fix |
|---|---|---|---|---|---|---|---|
| CA-01 | clause-to-line | Major | Quint commands with no quint-backends adapter | V4:229 ("on any Quint path"), V4:236, V4:249, V4:251; DI I11 | TC:1720-1768 (Lean-only gate, then a byte match on any closure root); TC:1380-1392 (adapters see only recipes whose closure includes them); P:349-358; Q/tlc.js:120-123 | Counterexample: the policy declares `quint` exactly as in DP:178-199 (executable, requires `node` and `quint-package`). Recipe `["quint","verify","spec.qnt","--backend=tlc","--tlc-config=t.json"]` has toolchain `["quint"]`, and t.json is `{"maxHeap":"-javaagent:/outside/a.jar"}`.<br>No quint-backends identity is computed for this recipe, so the TLC grammar never runs. `assertCommandBound` matches the CLI bytes against the `quint` root and returns. …
| CA-02 | commitment-coverage | Minor | Application Lake `-d` | CR:139 (symlink-before-`..` refused); V4:239; DI I12 | P:880 (`path.resolve(app.cwd, …directory)`), compared at P:883-893 with the physical `cwd` from P:788 | Counterexample: the declaration is `lake build` at cwd `proofs/lean`. The recipe is `["lake","-d","../lnk/../lean","build"]` at the same cwd, with untracked `proofs/lnk -> /tmp/evil/w`.<br>Lexically the path is `proofs/lean`, so the comparison passes. Lake opens `proofs/lnk/../lean` physically, which is `/tmp/evil/lean`, and builds that workspace.<br>The identity and source requirements bind `proofs/lean`. The walk does not cover `proofs/lnk`. Edits under `/tmp/evil/lean` neither change the key nor are verified. | Resolve with `directory(a…
| CA-03 | commitment-coverage | Minor | Relative `APALACHE_JAR` | V4:236, V4:249 (Apalache/JVM/jars) | P:465-470 (resolved against `context.cwd`); Q/apalache.js:419-425 (spawn without `cwd`); `~/.quint/apalache-dist-0.62.1/apalache/bin/apalache-mc` (`exec java … -jar "$APALACHE_JAR"`) | Counterexample: the adapter locator cwd is `"."`, a `quint verify` recipe runs at cwd `quint`, and `APALACHE_JAR=build/apalache.jar` (inherited, DP:38).<br>Discovery validates and hashes `<root>/build/apalache.jar`. The Apalache server runs `<root>/quint/build/apalache.jar`, whose bytes and manifest are unbound. Replacing that file does not change the key.<br>D's Quint recipes and collectors use cwd `"."`, so D is not affected. | Refuse a relative `APALACHE_JAR`, or resolve i…
| CA-04 | clause-to-line | Minor | Elan override precedence [INFERENCE] | V4:239; DI I11/I12 | P:723-725 (pin), P:752-757 (the longest override anywhere above cwd beats the pin). The forced `ELAN_TOOLCHAIN` probes hide the divergence. | [INFERENCE] Elan is forked from rustup. Its directory walk checks, at each level from cwd upward, the override DB and then `lean-toolchain`, and the nearest match wins.<br>Counterexample: `[overrides] "/Users/mv/Development/burnt" = "leanprover/lean4:v4.33.0"` with `proofs/lean/lean-toolchain` = `v4.33.1`, both installed. The adapter binds 4.33.0. The proxy `lake build` and `lean` run 4.33.1, so 4.33.1's bytes are unbound and the recorded verifier is wrong.<br>The Lake path probably fails closed when the two versions' Lake AP…

## Summary

- Total findings: 4
- By severity: Critical=0 Major=1 Minor=3 Informational=0
- By lens: commitment-coverage=2 clause-to-line=2 deferred-cannot-silently-succeed=0 who-controls=0 field-name=0 deferral-justification=0 (the lens-6 wrong-deferral claims are rolled into CA-01 and CA-02)
- Round-2 verdicts:
  - CA-01, CA-02, CA-04, CA-06, CA-07, CA-08 and CA-09 are closed.
  - CA-03 is closed for commands its adapter sees; its residual is new CA-01.
  - CA-05 is partially closed; its residual is new CA-02.
- Dossier impact: none of the four counterexamples matches D's current arrangement. No spurious refusal of D was found.
  - The Apalache 0.62.1 dist JAR manifest (Manifest-Version, Main-Class, Specification-*, Implementation-*, Enable-Native-Access: ALL-UNNAMED) passes `parseApalacheJarManifest`.
  - D's Lean setup was reported admitted.
- Recommended next step:
  1. Add the Quint CLI gate to `assertCommandBound` (CA-01).
  2. Use `inputPath` for the application `-d` at P:880 (CA-02).
  3. Refuse a relative `APALACHE_JAR`, or resolve it per subject cwd (CA-03).
  4. Add the unforced elan selection probe (CA-04).
  5. Add one T case for each, then rerun the proof suite once.

Not checked: the git diff itself; elan's actual precedence code (CA-04 rests on rustup lineage); D's ambient `APALACHE_JAR` value, and whether any of its path components is a symlink (P:38-48 would refuse); and whether `unzip` lists Z3 entries in the real dist JAR. No real Quint capture after round 3 was reported, so the Quint adapter's admission of D is inferred from reading the code, not observed.
