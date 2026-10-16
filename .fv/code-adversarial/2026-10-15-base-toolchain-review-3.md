# Code-adversarial review: reliq-fv evidence-v4 base toolchain, round 3 - 2026-10-15

- Operator: fv-code-adversary via OMP task (NOT the openai-codex/gpt-6.1-sol task agents R2FixBase, R2FixRust, R2FixProof, R2FixStore, R2FixNative, R2FixAdoption, and NOT the parent orchestrator)
- Code commit reviewed: `34a7240` (parent `6c787c2`)
- Intent version reviewed: no frontmatter. Reviewed against the caller-named `F/docs/execution-evidence-v4.md` (V4:229 derived identities, V4:231 allowlist refusals) and `F/.fv/changes/2026-10-14-execution-evidence-v4.md` §"Round-2 review dispositions (2026-10-15)" (CR:129-139)
- Ledger version reviewed: absent (`F/.fv/ledger.md` does not exist)
- Lens pack: crypto/enclave, plus the input-closure, supply-chain and change-detection supplements from rounds 1-2. This slice has no cryptographic commitment surface. Lens 1 is applied to the tool-identity and import-closure binding.
- Lenses applied: 1 through 6

## Gate and evidence notes

- **Intent resolution deviates from the gate.** `F/.fv/dispatch.json` and `F/.fv/intent.md` are both absent, so a strict reading of the gate returns BLOCKED. As in rounds 1-2, I used the caller-named normative contract.
- **No shell or git was used.** I reviewed the working tree and assume it matches `34a7240` `[INFERENCE]`. I could not compute the sha256 of the local Homebrew `sitecustomize.py` to compare with the allowlisted `1a773d37…`. The parent's admitted python-runtime capture of D is consistent with a match `[INFERENCE]`.
- **Abbreviations:** `F` = PROJECT_ROOT; `T` = `F/tools/evidence-v4/evidence-v4-toolchain.ts`; `C` = `…-toolchain-common.ts`; `Tst` = `F/tests/r38_evidence_v4_toolchain_review.py`; `D` = `/Users/mv/Development/burnt/dossier-wt/evidence-perf`; `HB` = `/opt/homebrew/Cellar/python@3.14/3.14.8/Frameworks/Python.framework/Versions/3.14/lib/python3.14/sitecustomize.py`. The whole Python analyzer is the single string at T:590; I cite its function names.
- **Accepted limits, not re-raised:** Python project files loaded inside the root are covered only by the recipe source closure, because Lake coverage is Lean-specific. Linux group signaling. Source CA-10. Unreviewed build scripts.
- **Not covered:** ctypes and other native loads made by Python code; stale `__pycache__` bytecode (`unchecked-hash` pycs) executed instead of the bound source; concurrency, resource exhaustion and crash consistency.

## Round-2 closure verdicts

| Round-2 | Verdict | Evidence |
|---|---|---|
| CA-08 guarded absence | closed | T:590 `walk` Try branch. `MissingImport` is accepted only when the try body is exactly one `ast.Import` of the missing name. Otherwise it raises "unsupported guarded Python import absence". Tst:197-207 cover the round-2 counterexample and its variants. |
| CA-09 unmodeled import and path mechanisms | partially closed | Every listed form now refuses: AugAssign and Delete via `path_changes`, `site` / `pkgutil` / `zipimport` / `importlib.machinery` mapped to FORBIDDEN, `exec` / `eval` / `compile`, `sys.meta_path` and `sys.path_hooks` outside `SAFE_SYS`, and `-W` / `-X` / `PYTHONWARNINGS` (T:500-503, 533-534). Tst:209-271 cover them. The replacement allowlist for "statically resolved project loaders" still admits unbound inputs: CA-16, CA-17, CA-19, CA-20, CA-22. |
| CA-10 `NODE_OPTIONS` | closed inside node-toolchain | `assertNodeEnvironment` (T:648-651) runs at T:925, 992 and 1018. Tst:450-471 cover it. Outside the adapter: CA-18 (direct `node` commands) and CA-25 (pnpm configuration). |
| CA-11 `LC_DYLD_ENVIRONMENT` | closed | C:143 throws. Unknown command types throw at C:142. Tst:473-483 cover it. |
| CA-12 wrapper contexts | partially closed | Shell basenames are refused (T:1407-1412, Tst:391-399). Bound non-shell launchers are skipped as "not a Python invocation" (T:1413-1438, 478): CA-23. A Python interpreter declared without the python-runtime adapter is never analyzed: CA-18. |
| CA-13 Darwin non-adapter dylibs | closed for `executable` / `file` | T:1588-1618 builds the derived tree (`selected-file` plus `native/non-system-libraries/*`, optionally a rustup driver) and refuses other drivers. This matches V4:229. Tst:897, 976 cover it. Non-adapter `tree` declarations still drop external dylibs: CA-24. |
| CA-14 helper requirement scope | closed | Helper roots carry `shared: true` (T:1639-1646), and `validateRequiredFiles` widens the scope to every captured id, including `fv-producer` (T:1684, 1716). Tst:1037-1068 cover it. |
| CA-15 producer discovery | closed | T:1504 merges `helpers.discovery`. |

---

## Lens 1 - Commitment coverage

| Commitment | Attacker DoFs | Bound by | Gap |
|---|---|---|---|
| Loader-helper specialization (`scan` pre-pass, T:590) | Runtime value of the helper's root argument | Only a syntactic check: the call-site argument must be an `ast.Name` whose id equals the parameter name. Then `case[root_parameter]=pathlib.Path(root)`. | CA-16 |
| Loader-helper call sites | Calls from other modules, or via `from m import helper` | `ast.walk(tree)` over the defining file only. In other modules, the imported name or attribute is UNKNOWN and calling it is silent. | CA-17 |
| Dynamic imports through unmodeled objects | `sys.modules[...]`; stdlib import-by-name APIs | `module_value(SYS,'modules')` returns UNKNOWN. Stdlib modules short-circuit to `None` in `resolve` and are never scanned. | CA-20 |
| Exact-hash Homebrew hook skip (`visit`, `1a773d37…`) | Request search path (`PYTHONPATH`) and split-formula directories | Skipping is sound for the file's own sys.path effects, because the `-I` query runs the same bytes with the same `os.environ`. It is unsound for the hook's own imports and for stdlib packages that import split-formula extensions. | CA-21 |
| Loader and entry path anchors | Command cwd different from root; symlinked entry script | `loader_location.literal` resolves against `root`. `visit` sets `__file__` to the realpath, and the analyzer's `sys.path[0]` is the unresolved dirname. | CA-22 |
| Node runtime selection under `pnpm exec` | pnpm `node-options` configuration | The selection probe (T:927) prints only PATH and executables | CA-25 `[INFERENCE]` |
| Derived Darwin identity (T:1588-1618) | Non-system dylibs, rustup driver | Exactly the V4:229 roots | No finding for `executable` / `file` |
| Mach-O load commands (C:136-157) | `LC_DYLD_ENVIRONMENT`, unknown commands | Refused | none |

## Lens 2 - Clause-to-line discharge

| Clause | Expected discharge | Actual code line | Status |
|---|---|---|---|
| V4:231 Python path mutations and loaders outside the static project-file forms refuse | Each admitted loader target equals the runtime target | T:590 `loader_location`, specialization, `visit` | gap: CA-16, CA-17, CA-19, CA-22 |
| V4:237, 253 unknown import dependency fails closed; incomplete closure is a preflight error | Every Python invocation is analyzed or refused | T:452-479 (only commands whose closure contains python-runtime); `assertCommandBound` T:1721-1760 has a Lean-only adapter rule | gap: CA-18, CA-23 |
| V4:231 nonempty `NODE_OPTIONS` refuses | Checked for every Node execution | Adapters only (T:925, 992, 1018). The session check T:1213 is DYLD-only. | gap: CA-18, CA-25 |
| V4:229 derived non-adapter identities | Darwin executable/file → derived tree | T:1588-1618 | discharged |
| V4:247, 253 non-system runtime content identities | Applies to every declaration kind | Linux: T:1582-1586 (any kind). Darwin: `tree` drops `native.roots` (T:1603-1617). | gap: CA-24 |
| V4:231 `DYLD_*` and `LC_DYLD_ENVIRONMENT` | Refused | T:643-646, 1213, 1276; C:143 | discharged |
| V4:245 probe identities retained | Helper probes in discovery | T:1504, 1649 | discharged |

## Lens 3 - Deferred cannot silently succeed

| Branch | Reachable from | Behavior | Status |
|---|---|---|---|
| `visit`: `if real.endswith('.py'):` with no else (T:590) | Entry scripts (T:585), `runpy.run_path` / `spec_from_file_location` targets (`visit_loaded`), `-m` origins | Records nothing, scans nothing, succeeds | gap: CA-19 |
| `otherCommandBound` returns true (T:478 `continue`) | Any non-shell bound launcher | Python context skipped | gap: CA-23 |
| Darwin `tree` branch `result = { ...native, roots }` (T:1617) | Non-adapter tree declarations | External dylibs discarded | gap: CA-24 |
| Guarded single-import absence | Python analyzer | Explicit, narrow, and revalidated (Tst:500) | acceptable |
| `loader target is absent` | Loader resolver | Throws | acceptable |
| TODO / stub / mock markers | T, C | None found | none |

## Lens 4 - Who controls

| Field | Supplier | Validation | Gap |
|---|---|---|---|
| Recipe argv (`--root`, entry path, launcher) | Reviewed policy | `assertCommandBound` checks argv[0] only (T:1722). The loader root is unchecked. | CA-16, CA-19, CA-23 |
| Toolchain declarations (python3 as plain `executable`) | Reviewed policy | No family-adapter requirement except Lean (T:1745-1746) | CA-18 |
| Python env selectors | Reviewed policy | Denylist: `PYTHONHOME`, `PYTHONPLATLIBDIR`, `PYTHONWARNINGS` (T:529-534). `PYTHONPATH` modeled. | CA-21 (`PYTHONPATH` shadowing under the hook). Not numbered (Informational): `PYTHONCASEOK` makes the Darwin importer case-insensitive only when the environment is honored, while the analyzer runs `-I`. Fix: an env allowlist. |
| Project Python sources | Project author | Static analyzer | CA-16, CA-17, CA-19, CA-20, CA-22 |
| pnpm configuration files | User / project | Not read | CA-25 |

## Lens 5 - Field-name fidelity

| Field | Implied semantic | Actual value | Status |
|---|---|---|---|
| Derived `selected-file` / `native/non-system-libraries/<encoded>` / `native/drivers/{cargo,rustc}-0` | V4:229 | T:1605-1615 labels match | none |
| `fv-producer.discovery` | All probes | T:1504 | none (CA-15 closed) |
| Requirement error text "Tool dependency lacks…" (T:1708) | Generic | Correct for helpers and Python | none |

## Lens 6 - Deferral justification audit

| Deferred finding | Justification claims | Claim audit | Verdict |
|---|---|---|---|
| CR base row: "path-mutation allowlist with statically resolved project loaders" (CA-09) | (a) path mutations allowlisted; (b) loaders statically resolved | (a) True for the listed forms. (b) False: the root is bound by identifier (CA-16), cross-module calls are invisible (CA-17), non-`.py` targets are unscanned (CA-19), anchors are wrong (CA-22). | partially false; carried by CA-16, 17, 19, 22 |
| CR: "nonempty `NODE_OPTIONS` refused" | Refused at discovery | True only inside node adapters | partially false; CA-18 |
| CR: "shell/unbound Python launchers refused" (CA-12) | Shells and unbound launchers refuse | Literally true. Bound non-shell launchers pass. | valid as worded; gap is CA-23 |
| CR: "Darwin non-system dylibs bound in derived tree identities" (CA-13) | All non-adapter declarations | True for executable/file. Trees drop them. | partially false; CA-24 |
| Accepted limits | Out of scope | Not contradicted | none |

---

## Finding list (consolidated)

| ID | Lens | Severity | Surface | Intent ref | Code ref | Summary | Fix |
|---|---|---|---|---|---|---|---|
| CA-16 | commitment-coverage | Major | Loader-helper root binding | V4:231, 237 | T:590 `scan` specialization: `if not isinstance(root_argument,ast.Name) or root_argument.id!=root_parameter: raise …; case[root_parameter]=pathlib.Path(root)`. Tst:273-314 accepts `def check(root): return _module(root,'loaded.py','loaded')` with `root` an arbitrary parameter. | The analyzer assumes any variable named `root` is the project root. Counterexample: `check.py` defines D's `_input` / `_module` shapes, then `root = Path(sys.argv[1]); _module(root, "plugin.py", "plugin")`. Recipe `["python3","check.py","/Users/x/old-checkout"]`. The analyzer visits `<project>/plugin.py`; the runtime execs `old-checkout/plugin.py`, which imports `vendor_plugin`. Neither file nor import …
| CA-17 | commitment-coverage | Major | Loader helpers called from other modules | V4:231, 237 | T:590 `functions={…tree.body…}`; call sites from `ast.walk(tree)` of the defining file only. `walk` ImportFrom else-branch binds UNKNOWN. In `expression`, a Call on an UNKNOWN target returns UNKNOWN. | Counterexample: `loader.py` (beside `check.py`) defines `_input` / `_module` and calls `_module(root,"a.py","a")` once, so specialization succeeds. `check.py`: `from loader import _module; _module(Path(__file__).resolve().parent, "b.py", "b")`. `b.py` imports `vendor_plugin`. `b.py` is never visited and `vendor_plugin` is never required. | Record specialized `(origin, name)` pairs. Refuse any import, attribute access or alias of a specialized helper from another mo…
| CA-18 | clause-to-line | Major | Interpreter commands without their family adapter | V4:231, 237, 243, 251, 253 | Python contexts come only from commands whose closure contains the python-runtime declaration (T:1384-1398). `assertCommandBound` has a Lean-only adapter rule (T:1745). Session env check is DYLD-only (T:1213). | (a) `{"id":"py","kind":"executable","locator":{"mode":"command","value":"python3"},"requires":[]}` with recipe `["python3","check.py"]`. check.py's site-packages imports, stdlib and startup files are never analyzed or bound. `pip install -U vendor_plugin` leaves every digest unchanged. (b) Recipe `["node","check.mjs"]` with a `node` executable declaration and policy env `NODE_OPTIONS="--require /opt/hooks/trace.js"`: admitted, and the h…
| CA-19 | deferred-cannot-silently-succeed | Major | Non-`.py` entry and loader targets | V4:237, 253 | T:590 `visit`: scanning is guarded by `if real.endswith('.py'):` with no else. T:585 accepts any entry path. `RUN_PATH` checks only `os.path.isfile`. | CPython runs extensionless scripts, directories with `__main__.py` and zipapps. Counterexamples: `["python3","tools/gate"]` (no suffix, `import vendor_plugin`); `runpy.run_path(str(Path(__file__).with_name("collect")))`; `python3 app.pyz`. All are admitted with no requirement. | In `visit`, raise unless the file is `.py`. External extension or bytecode modules stay required-and-declared. Refuse directory and zip entries. |
| CA-20 | commitment-coverage | Minor | Dynamic imports through unmodeled objects | V4:231, 237 | T:590 `module_value`: `SAFE_SYS` includes `modules` and returns UNKNOWN. Stdlib `resolve` returns `None` without scanning. | `sys.modules["importlib"].import_module("vendor_plugin")` passes. So does `import logging.config; logging.config.dictConfig({"version":1,"handlers":{"h":{"class":"vendor_plugin.Handler"}}})`, which imports through `__import__` in stdlib. `pickle.load` and `pydoc.locate` behave the same way. None is refused. | Make `sys.modules` reads opaque: refuse attribute access or calls on values read from it. D's `.get`, `pop`, stores and `sys.modules[__name__]` stay legal. Map the stdlib import-by-name modules (`pickle`, `shelve`, `logging.config`, `…
| CA-21 | commitment-coverage | Minor | Exact-hash Homebrew hook skip | V4:237, 242 | T:590 `visit`: `if not project and real in startup_hooks and sha256 in ('1a773d…',): return`. HB lines 4-7 `import re, os, site, sys`; HB tail `sys.path.append(f"/opt/homebrew/opt/python-{tk,gdbm}@3.14/libexec")`. | (a) Policy env `PYTHONPATH=/opt/shadow` containing `re.py`, with a command without `-I`/`-E`. At startup the hook's `import re` loads `/opt/shadow/re.py`, because PYTHONPATH precedes stdlib. The analyzer never resolves the skipped hook's imports. `[INFERENCE: re not yet in sys.modules when the hook runs; check with -X importtime]` (b) With Homebrew `python-tk@3.14` installed, `import tkinter` short-circuits as stdlib, but the runtime loads `_tkinter.*.so` from t…
| CA-22 | commitment-coverage | Minor | Path anchors differ from CPython | V4:237 | T:590 `loader_location.literal` → `project_path(value, root)`; `visit` sets `__file__` to the realpath; requests use `paths=[dirname(request['file'])]` with an unresolved T:585 path | (a) Command cwd `sub/`, `spec_from_file_location("m","helper.py")`, with both `helper.py` and `sub/helper.py` present: the analyzer scans root's copy, the runtime loads cwd's. (b) `tools/check.py` symlinked to `vendor/gate/check.py`: CPython sets `sys.path[0]` to the resolved dir and `__file__` to the unresolved path, and the analyzer does the reverse. `import helper` and `Path(__file__).with_name(...)` then select different files. D's Python commands use cwd `.` and unlinked scripts. | Resolve …
| CA-23 | clause-to-line | Minor | Bound non-shell launchers (residual of CA-12) | V4:237, 251 | T:1405-1440: shell basename denylist, then `true` for any bound Mach-O/ELF; T:478 `continue` | `["arch","-arm64","python3","check.py"]` with toolchain `["arch","python"]`, where `arch` is a path declaration of `/usr/bin/arch` (universal Mach-O): skipped. `nice`, `time`, `nohup` and `caffeinate` behave the same. check.py's imports are unbound. | Refuse a bound launcher context when any argv token resolves (dev/ino) to the selected interpreter or names a `.py` / `-m` / `-c` entry. D's `pnpm exec tsx` contexts contain no such token. |
| CA-24 | clause-to-line | Minor | Darwin non-adapter `tree` declarations | V4:247, 253 | T:1603-1617: `linked` applied only when `kind !== "tree"`; `result = { ...native, roots }` replaces `native.roots`; `discoverNativeAdapter` returns no `fileRequirements` (T:906). Linux emits them for any kind (T:1582-1586). | A `command-relative` tree whose `bin/z3` links `/opt/homebrew/opt/gmp/lib/libgmp.10.dylib`: upgrading gmp never invalidates. D has three non-adapter trees (`verus-distribution`, `go-distribution`, `quint-package`). None is among the reported admitted captures, so whether this case also produces a spurious refusal (`@rpath` resolved with an arbitrary `subjects[0]`) is undetermined. | For Darwin trees, emit `fileRequirements` for linked roots outside…
| CA-25 | commitment-coverage | Minor | pnpm-injected Node options | V4:231, 243 | T:927 selection probe runs under `pnpm exec` but does not report `process.env.NODE_OPTIONS` or `process.execArgv` | `[INFERENCE: pnpm applies the node-options config to exec children]` `node-options=--require /opt/hooks/trace.js` in `~/.npmrc` or the project `.npmrc` preloads an unbound hook into tsx. No such file exists for D. | Add `NODE_OPTIONS` and `execArgv` to the probe output and refuse nonempty values. Run one experiment to confirm. |

## Summary

- Total findings: 10 new (CA-16 to CA-25)
- By severity: Critical=0 Major=4 Minor=6 Informational=0
- By lens: commitment-coverage=6 clause-to-line=3 deferred-cannot-silently-succeed=1 who-controls=0 field-name=0 deferral-justification=0 (lens 6's partially false claims are carried by the findings above)
- Round-2 closure: CA-08, CA-11, CA-14 and CA-15 are closed. CA-10 and CA-13 are closed in their stated scope, with residuals CA-18, CA-24 and CA-25. CA-09 and CA-12 are partially closed (CA-16, 17, 19, 20, 22, 23). Within this slice I found no spurious refusal of D's reported captures. D's non-adapter Darwin trees are unverified (CA-24).
- On the two focus areas:
  - **Static-loader resolver:** it can admit unbound inputs. The root is matched by name only (CA-16), helpers called from other modules are invisible (CA-17), and non-`.py` targets are never scanned (CA-19).
  - **Exact-hash `sitecustomize` allowlist:** it is sound for the hook's own `sys.path` effects. It is not sound for the hook's own imports or for stdlib packages that load from the split-formula directories it adds (CA-21).
- Recommended next steps, in order:
  1. CA-19: raise on non-`.py` sources in `visit`.
  2. CA-16 and CA-17: bind the loader root by value and refuse cross-module helper use. Keep D's checker admitted.
  3. CA-18: require the family adapter for Python and Node runtimes, and refuse `NODE_OPTIONS` at session creation.
  4. CA-23, CA-20, CA-21, CA-22: the refusal tightenings above.
  5. CA-24: emit Darwin tree linkage requirements, then capture D's verus-distribution.
  6. CA-25: run the pnpm experiment and extend the probe.
  7. The parent reruns the v4 suites once, with one negative test per finding.

Not checked: the sha256 of the local Homebrew hook, pnpm's `node-options` behavior, CPython startup import order for `re`, and the Mach-O load commands in D's verus tree. All four need a shell or an experiment. Risk: CA-16 to CA-19 let a real Python recipe reuse stale evidence without any discovery refusal.
