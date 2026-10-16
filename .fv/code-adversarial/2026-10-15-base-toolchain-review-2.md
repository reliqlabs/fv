# Code-adversarial review: reliq-fv evidence-v4 base toolchain, round 2 - 2026-10-15

- Operator: fv-code-adversary via OMP task (NOT the openai-codex/gpt-6.1-sol task agents FixNativeOwnership-2, FixProducerStore-2, FixSourceBindings-2, FixAdoptionDashboard-2, FixBaseToolchain, FixRustToolchain or FixProofToolchain, and NOT the parent orchestrator)
- Code commit reviewed: `6c787c20f023a132856cf5119b137be25dd2303f` (parent `aa6946f`)
- Intent version reviewed: no frontmatter. Reviewed against caller-named `F/docs/execution-evidence-v4.md` and `F/.fv/changes/2026-10-14-execution-evidence-v4.md` §"Post-commit review dispositions (2026-10-15)"
- Ledger version reviewed: absent (`F/.fv/ledger.md` does not exist)
- Lens pack: crypto/enclave, with the same supply-chain, input-closure and change-detection supplements as round 1. The delta has no cryptographic commitment surface.
- Lenses applied: 1 through 6

## Gate and evidence notes

- **Intent resolution deviates from the gate.** `F/.fv/dispatch.json` and `F/.fv/intent.md` are both absent. A strict reading of the isolation gate returns BLOCKED here. I proceeded on the caller-named normative contract, which is the same target round 1 used for this slice. The parent should decide whether F needs a dispatch entry.
- **No git or shell commands were run.** No git or shell tool was available. I did not compute `git diff aa6946f..6c787c2`. I reviewed the current working-tree files and assume they match `6c787c2` `[INFERENCE]`. Delta attribution comes from the caller and the change record.
- **Abbreviations:** `F` = PROJECT_ROOT, `T` = `F/tools/evidence-v4/evidence-v4-toolchain.ts`, `C` = `F/tools/evidence-v4/evidence-v4-toolchain-common.ts`, `V4` = `F/docs/execution-evidence-v4.md`, `Tst` = `F/tests/r38_evidence_v4_toolchain_review.py`, `D` = `/Users/mv/Development/burnt/dossier-wt/evidence-perf`.
- **Not covered:** access control, arithmetic, reentrancy, resource exhaustion (for example, hashing every whole `NODE_PATH` directory at T:982-991), crash consistency, migration, and concurrency beyond the call sites cited below.
- **Parent verification accepted as reported:** 150/150 Darwin and 114 Linux tests. None of these tests exercises the counterexamples below.

## Round-1 closure verdicts

| Round-1 | Verdict | Evidence |
|---|---|---|
| CA-01 pnpm/tsx shim chain | closed | T:895-993 runs the selection probe under `pnpm exec` (T:911). It resolves the PATH-selected shim, requires the exact pnpm template (T:933-940) and checks the entry against the package `bin` (T:924-926, 941-942). It binds `dirname`/`sed`/`uname` (T:943-948), the preferred `$basedir/node` (T:952-959), the injected `NODE_PATH` (T:960, 982-991), the Node implementation (T:973-980) and the native closure of all of them (T:1065-1073). Tst:424-446 cover it. `NODE_OPTIONS` is a separate selector that remains open: CA-10. |
| CA-02 Python import closure | partially closed | Literal `import_module` and `__import__` now resolve, and nonliteral ones raise (T:576, `expression`, `ast.Call` branch). Parent initializers are visited (`dependency`), and from-list submodules too (`from_modules`). Tst:177-190, 247-273 cover it. Still open: unmodeled import and path mechanisms (CA-09). The new guarded-absence rule adds a fail-open path (CA-08). |
| CA-03 tsx resolver order | closed | T:196-221: TypeScript parents try substitutions first (`.js` maps to `.ts`, `.tsx`, `.js`, `.jsx`) and stop at the first hit. JavaScript parents reject more than one existing candidate (T:215). Packages are collected from the selected source (T:186-193). Tst:447-468 cover it. |
| CA-04 `DYLD_*` overrides | closed for environment selectors | `assertLoaderEnvironment` (T:629-632) runs at session creation (T:1191), on every probe environment (T:1254) and on the Python, native and Node adapter contexts (T:449, 639, 996). Tst:565-586 cover it. Loader variables embedded in the binary are not covered: CA-11. |
| CA-05 helper provenance | closed | Every `context.probe` registers its executable (T:1380-1389). `helperClosure` adds each helper's native closure (T:1336-1352) to adapter identities (T:1540-1551) and to the producer (T:1421-1422). otool, xcrun and the launcher are bound (T:740-757), plutil is bound (T:871), and native roots keep their `native/` prefix in the Python and Node adapters (T:620, 1072). Tst:589-644 cover it. Side effects: CA-14 and CA-15. |
| CA-06 metadata executes project code | closed | The import-path query (T:486) and the analyzer (T:577-586) both run with `-I`, so the project cwd is not on `sys.path`. Tst:275 covers it. |
| CA-07 adapter memo aliasing | closed | The `adapter-selection` key now includes the whole declaration, application contexts and command contexts (T:1456-1462). Requirement IDs come from that declaration (T:584). Tst:646-680 cover it. |

---

## Lens 1 - Commitment coverage

| Commitment | Attacker DoFs | Bound by | Gap |
|---|---|---|---|
| `canonicalToolPath` spelling (C:78-102) | Hardlink names, symlink chains, `..` after symlinks, trailing `/` | Directory part via `realpath` (C:62-76, with POSIX `..` after symlink resolution). Basename kept. Symlinks followed with cycle detection. Directories fully `realpath`'d (C:86). | No aliasing found: different files cannot share one canonical string, because (realpath(dir), basename) names one directory entry. One file can have several spellings (hardlinks, case-insensitive APFS names). Every string-equality consumer then fails closed: C:369 `Conflicting tool root`, C:450 link escape, T:1602 and 1624-1625 binding checks. |
| Stale identity through hardlink spelling or memo | Same inode under a new name; in-place rewrite | `ToolHasher.file` keys on dev:ino and requires an equal dev/ino/size/mode/mtime/ctime stamp (C:311-358). Manifests use virtual labels, not host paths. | No finding. A content change changes ctime, so the hash is recomputed. |
| `tool-probe` memo key (T:1256-1265) | Command, cwd, environment, executable bytes | Generation, command, relative cwd, per-variable value hashes, selected path plus hash/size/mode | No finding. Generation is bumped and probes are cleared on every revalidate (T:1667-1669). |
| `adapter-selection` memo key (T:1456-1462) | Declaration, callers, environment | Includes all of them | No finding (CA-07 closed). Latent issue: per-context helper maps (T:1395) are filled only when the adapter actually runs. A second `identify(id)` in the same generation would hit `discoveries` and lose adapter helpers. Current callers do not trigger this: `capture` memoizes per id (T:1650-1656) and `revalidate` is serialized (T:1660-1666) `[INFERENCE from call sites]`. |
| `discovery-helper` key (T:1387) | Invoked path, cwd, environment | Helper bytes are rehashed in every `helperClosure` run | No finding |
| xcrun `--no-cache --find otool` binding (T:740-757) | xcode-select state, `DEVELOPER_DIR`, otool replacement | The probe output is retained, and the returned implementation is what later probes execute (`otool.invoked` at T:764). Launcher, xcrun and implementation are bound as roots and inspected. | No finding for `/usr/bin/otool`. The shim check is a literal path, so a copied xcode shim elsewhere on PATH would be executed as otool and its xcrun-selected target would not be bound. That only affects a discovery helper; Informational, not numbered. |
| Python requirement set (T:576 analyzer, consumed at T:1583-1611) | Script control flow, path mutation, guarded imports, loader APIs | Static `scan` / `walk` model | CA-08: a guarded `MissingImport` from a branch that may not run discards the success path. CA-09: several import and path mechanisms are silently ignored. |
| Node runtime selection | `NODE_OPTIONS` `--require` / `--import` / `--loader` | Not checked in T:995-1101. The proof adapter does check it (`evidence-v4-toolchain-proof.ts:323-329`). | CA-10 |
| Darwin effective linkage | `LC_DYLD_ENVIRONMENT` in the main image | `parseMachOLoadCommands` reads only dylib and rpath commands (C:118-142) | CA-11 |
| Hardlinked main image with `@executable_path` | Kernel or dyld choice of spelling | `inspect` expands with the spelling-preserved path (T:inspect `expand`) | Undecided. Needs a Darwin experiment: two hardlinks in different directories, each with a different `../lib` neighbour. No finding raised. |

## Lens 2 - Clause-to-line discharge

| Clause | Expected discharge | Actual code line | Status |
|---|---|---|---|
| V4:231 python-runtime: an unknown import dependency fails closed | Refuse whenever runtime may import code the analyzer did not resolve | T:576 `resolve` / `walk` / `catches_missing_import`; T:466 | gap: CA-08, CA-09, CA-12 |
| V4:237 node-toolchain: actual Node and tsx execution | Bind or refuse every runtime selector | T:895-1101 | partial: CA-10 |
| V4:236 and 241: only system libraries and SDK use the vendor exception | Effective non-system images attested | T:629-632, 795-857 | partial: CA-11 |
| V4:241, 245, 247: non-system runtime content identities; incomplete closure is a preflight error | Every declaration's non-system native closure bound | T:1519-1526 (Linux only), T:1540-1551 (only with probes) | gap: CA-13 |
| V4:239: probe identities retained; revalidation at every boundary | Helpers bound, change detected, discovery arrays complete | T:1336-1352, 1540-1551, 1667-1680, 1443 | partial: CA-14 (scope of requirement satisfaction), CA-15 (producer discovery array) |
| V4:239: dedupe identical probe contexts only | Keys cover every consumed input | T:1256-1265, 1456-1462 | discharged |
| V4:221-223: canonical aliases and cycle rejection | Deterministic canonical targets | C:62-102, 360-470 | discharged for the inspected construction |
| Change record, Proof row: Lake source coverage | Union of required directories and files must lie inside the recipe closure | T:1691-1701; `evidence-v4-source.ts:248-268`; run.ts:526 | discharged for Lean. Union semantics are correct; symlinks refuse; escaping or relative entries fail the `bound` check. Coverage for other families is the accepted limit. |
| User policy: refuse unsupported arrangements at discovery | Unsupported forms throw | T:205-221, 933-940, 629-632 | partial: CA-09, CA-10, CA-12 accept silently |

## Lens 3 - Deferred cannot silently succeed

| Branch | Reachable from | Behavior | Status |
|---|---|---|---|
| Guarded `MissingImport` handler (T:576 Try branch) | Any Python recipe, checker or startup hook | Accepts absence and walks only the handler | gap: CA-08 |
| Missing stdlib-named module, `resolve` `return None` | Python analyzer | Accepted. A later site-packages module with that name changes discovery output on the next run (`[INFERENCE]`, mechanism shown by Tst:192-235). | acceptable |
| Missing `NODE_PATH` directory skipped (T:983-990) | Node adapter | Absence accepted; rediscovery binds the directory once it appears | acceptable |
| `$basedir/node` absent: fall back to PATH node (T:952-959) | Node adapter | Matches the shim's `-x` test. A directory there throws. | acceptable |
| No tsx package, or compile cache disabled: no namespace (T:1087-1112) | Node adapter | Explicit null selection | acceptable |
| Python command context with a different argv[0] (T:466) | Python adapter | `continue`: the context is silently not analyzed | gap: CA-12 |
| Darwin non-adapter declaration without probes (T:1519-1551) | `identify` | No linkage closure, no error | gap: CA-13 |
| TODO, stub or mock markers | T, C | None found | none |

## Lens 4 - Who controls

| Field | Supplier | Validation | Gap |
|---|---|---|---|
| Semantic environment (`DYLD_*`, `NODE_OPTIONS`, `PYTHONWARNINGS`) | Reviewed policy | DYLD refused (T:629-632). `NODE_OPTIONS` and `PYTHONWARNINGS` unchecked. | CA-10, CA-09 |
| Recipe and checker argv | Reviewed policy | `assertCommandBound` (T:1618-1640). The Python adapter silently drops non-interpreter contexts (T:466). | CA-12 |
| Project Python sources | Project author | Static analyzer (T:576) | CA-08, CA-09 |
| `.bin` shim bytes | pnpm install | Exact template equality (T:933-940) | none |
| Lake `sourceDirectories` | Project lakefile | Readdir walk; symlinks refused; closure membership required (`evidence-v4-source.ts:248-268`) | none |
| Probe outputs (xcrun, otool, plutil) | Installed helpers | Executable bytes bound through `helperClosure` | none |

## Lens 5 - Field-name fidelity

| Field | Implied semantic | Actual value | Status |
|---|---|---|---|
| `fv-producer` `ToolIdentity.discovery` | Every discovery probe's hashes (V4:239) | `native.discovery` only (T:1443). Helper-closure probes (T:1350, 1421) are dropped; declared tools merge them (T:1555). | CA-15 |
| Error text "Python dependency lacks an explicit installed tool declaration" (T:1610) | A Python requirement | Also raised for helper and Linux-linkage requirements (T:1523, 1544-1550) | Part of CA-14 |
| `execution/*` and `discovery-helpers/<key>/*` labels | Selected execution and helper bytes | Faithful | none |
| `version.text`, discovery `stdout_hash` / `stderr_hash` | Actual streams | Faithful | none |

## Lens 6 - Deferral justification audit

| Deferred finding | Justification claims | Claim audit | Verdict |
|---|---|---|---|
| Round-1 CA-04 disposition "refused" | (a) DYLD selectors are refused before any probe | True: T:1191, 1254, 449, 639, 996; Tst:565-586 | valid for environment variables. The binary-embedded form is CA-11. |
| Change record: Rust, proof and native cut over to `canonicalToolPath` | (a) cut over; (b) native equality uses `(dev, ino)` | (a) Rust and proof file paths use it. Proof's `directory()` and the JVM walk keep `fs.realpath` for directories (`evidence-v4-toolchain-proof.ts:34, 115`), which is safe because directories cannot be hardlinked. (b) `evidence-v4-native.ts:1866-1877` compares `(dev, ino)`; the Darwin fallback also requires equal argv spelling. | valid |
| Change record: Darwin `realpath` returned nondeterministic hardlink spellings | Spelling-preserving canonicalization fixes the false conflicts | C:87-96 returns realpath(dir) + basename. Tst:556-562 assert separate spellings for a hardlink twin. | valid |
| Accepted limits: Linux group signaling; Lake coverage is Lean-only | Out of scope here | Not contradicted by the toolchain code | no wrong-deferral |

---

## Finding list (consolidated)

| ID | Lens | Severity | Surface | Intent ref | Code ref | Summary | Fix |
|---|---|---|---|---|---|---|---|
| CA-08 | commitment-coverage | Major | Python guarded-absence rule (new in this delta) | V4:231, 245, 247; user policy on false PASS | T:576: `walk` Try branch (`except MissingImport` walks only `handler.body`); If branch walks both arms when the condition is unknown; `scan` runs deferred function bodies after the module walk; `MissingImport` survives the rewrap in `walk` | A `MissingImport` from code that may not run is treated as definite failure of the whole try body. The rest of the body and `orelse` are never scanned. Counterexample (Python 3.12, `tomli` absent, `vendor_plugin` installed): `import sys` / `try:` / `if sys.version_info >= (3,11): import tomllib` / `else: import tomli as tomllib` / `import vendor_plugin` / `except ImportError: vendor_plug…
| CA-09 | commitment-coverage | Major | Python import mechanisms still unmodeled (residual of CA-02) | V4:231, 245, 247 | T:576: `walk` has no `ast.AugAssign` or `ast.Delete` branch. `For` / `While` / `With` bodies mutate copies of `search`, and `path_changes` is checked only for If/Try. Calls on non-modeled modules evaluate to UNKNOWN silently. Interpreter `-W` is accepted at T:474-477. | These forms pass without refusal: `sys.path += ['/opt/plugins']`; `del sys.path[0]` (changes shadowing); `site.addsitedir(...)`; path inserts inside `with` / `for` blocks; `runpy.run_path`, `importlib.util.spec_from_file_location(...).loader.exec_module`, `importlib.__import__`, `exec(compile(...))`; `sys.meta_path` / `sys.path_hooks`; dotted warning categories in `-W` or …
| CA-10 | commitment-coverage | Major | Node runtime selectors (pre-existing) | V4:237, 245, 247 | T:995-1101 (no check); compare `evidence-v4-toolchain-proof.ts:323-329` | The node-toolchain adapter accepts `NODE_OPTIONS` carrying `--require`, `-r`, `--import`, `--loader` or `--experimental-loader`. `[INFERENCE]` With policy environment `NODE_OPTIONS="--require /opt/hooks/trace.js"`, `pnpm exec tsx` preloads the hook, but no root binds it, so edits never invalidate. D's `.fv` has no `NODE_OPTIONS` (grep), so this is a generic producer gap with the same calibration as round-1 CA-04. | Apply the proof adapter's check in `discoverNodeAdapter` and in `selectedNodeExecution`'s environment. Add a refusal test. |
| CA-11 | commitment-coverage | Minor | Darwin loader environment embedded in the binary | V4:236, 241 | C:118-142; T inspect `commands.dependencies` loop skips `/usr/lib/` and `/System/Library/` | `LC_DYLD_ENVIRONMENT` is neither parsed nor refused. `[INFERENCE: dyld honors DYLD_*_PATH from this command in unrestricted main executables]` A main image embedding `DYLD_LIBRARY_PATH=/opt/override` that depends on `/usr/lib/libz.1.dylib` loads `/opt/override/libz.1.dylib`. Discovery skips the system install name, so the override is unbound. | Refuse `LC_DYLD_ENVIRONMENT` in `parseMachOLoadCommands` (fail closed). Add a parser test. |
| CA-12 | clause-to-line | Minor | Python command contexts skipped (pre-existing) | V4:231, 245 | T:466 `continue`; T:1618-1640 | Contexts in a python-runtime closure whose argv[0] is not the selected interpreter get no import analysis and no refusal. A hardlink-spelled interpreter is still caught by `assertCommandBound`. A wrapper is not: `["bash", "scripts/run.sh"]` with bash bound by another declaration, where `run.sh` runs `python3 check.py` importing an external module, passes with no Python requirement. | Throw instead of `continue` unless the context is the interpreter, compared by `(dev, ino)` plus spelling. Add a wrapper-command refusal test. |
| CA-13 | clause-to-line | Minor | Darwin native closure for non-adapter declarations (pre-existing) | V4:241, 247 | T:1519-1526 (Linux only); T:1540-1551 runs only when probes happened | On Darwin, an `executable` or `file` declaration with `version_command: null` hashes only its file. Its non-system dylibs (for example a Homebrew `@rpath` library) are never required, so library upgrades never invalidate. D is unaffected: every D executable declaration has a version command (`D/.fv/execution-policy.json:82-526`). | Run `discoverNativeAdapter` on Darwin for non-adapter file roots and emit `fileRequirements`, as Linux does. |
| CA-14 | clause-to-line | Minor | Helper requirement scope (new in this delta) | V4:239, 243 | T:1540-1551, 1583-1611; `closure()` excludes `fv-producer` (T:1207) | For `executable` and `file` declarations, helper-closure roots (otool, xcrun, otool launcher and their libraries) become `fileRequirements` that only the declaration's own `requires` closure can satisfy. `[INFERENCE, not executed]` D's `git` (`requires: []`, `D/.fv/execution-policy.json:82-98`) would be refused on Darwin when capture reaches `/usr/bin/otool`, with the misleading "Python dependency..." message. This fails closed but would block real Darwin collection. Tests only use null version commands for these kinds (Tst:134-137, `tests/evidence_v4_fixture.py:270-272`). | Let helper requireme…
| CA-15 | field-name | Informational | `fv-producer` discovery array (new in this delta) | V4:239 | T:1421-1422, 1443 vs T:1555 | Producer helper bytes are bound, but the helper-closure probe hashes are left out of `discovery`, unlike declared tools. | Merge `helpers.discovery` at T:1443. |

## Summary

- Total findings: 8
- By severity: Critical=0 Major=3 Minor=4 Informational=1
- By lens: commitment-coverage=4 clause-to-line=3 deferred-cannot-silently-succeed=0 who-controls=0 field-name=1 deferral-justification=0
- Round-1 closure: CA-01, CA-03, CA-05, CA-06 and CA-07 are closed. CA-04 is closed for environment selectors (embedded form is CA-11). CA-02 is partially closed (CA-09). New defects from this delta: CA-08, CA-14 and CA-15. The `canonicalToolPath` hardlink handling produced no aliasing or stale-identity finding.
- Recommended next steps, in order:
  1. CA-08: restrict guarded-absence acceptance.
  2. CA-09: refuse the unmodeled Python mechanisms.
  3. CA-10: refuse `NODE_OPTIONS` loaders in the Node adapter.
  4. Run the D plan on Darwin to confirm or clear CA-14, then fix the requirement scope and message.
  5. CA-11, CA-12, CA-13 refusals.
  6. CA-15 field merge.
  7. Then the parent reruns the v4 suites once, adding the named negative tests.

Not checked: the actual `git diff` (no shell available); dyld `LC_DYLD_ENVIRONMENT` and hardlink `@executable_path` behavior (no experiments run); proof, Rust and native internals beyond the cited lines. Risk: CA-08 and CA-09 can let a real Python-based recipe reuse stale evidence; CA-14 may block real Darwin collection.
