CLASSIFICATION: code_wrong  |  CONFIDENCE: high

### Evidence

Paths below are relative to `/Users/mv/Development/reliq-fv-wt/evidence-stdlib-closure`, except installed-runtime paths.

- `artifact://20875:26` reports:
  ```text
  File "<string>", line 82, in inventory_native_stdlib
      if not standard_input(selected): raise RuntimeError(...)
  RuntimeError: unsupported Python stdlib native distribution outside runtime roots: /opt/homebrew/Cellar/python@3.14/3.14.8/Frameworks/Python.framework/Versions/3.14/Python
  ```
  `artifact://20875:98-100`: `Ran 7 tests` and `FAILED (failures=8, errors=1)`.

- `tools/evidence-v4/evidence-v4-toolchain.ts:622-623` defines:
  ```python
  def standard_input(p):
   return (within(stdlib,p) and 'site-packages' not in os.path.relpath(p,stdlib).split(os.sep)) or within(extensions,p)
  ```
  At lines 678–689, `inventory_native_stdlib()` walks those directories with `followlinks=True`, selects extension-suffix or `.dylib` filenames, resolves each with `realpath`, and rejects every target outside those two roots.

- The installed runtime’s `lib/python3.14/_sysconfigdata__darwin_darwin.py` declares:
  ```text
  :651  'LDLIBRARY': 'Python.framework/Versions/3.14/Python',
  :975  'PYTHONFRAMEWORK': 'Python',
  :979  'PYTHONFRAMEWORKPREFIX': '/opt/homebrew/opt/python@3.14/Frameworks',
  ```
  Its `lib/python3.14/config-3.14-darwin/Makefile:3216-3220` contains:
  ```make
  frameworkinstallmaclib:
      $(LN) -fs "../../../$(PYTHONFRAMEWORK)" "$(DESTDIR)$(LIBPL)/libpython$(LDVERSION).a"
      $(LN) -fs "../../../$(PYTHONFRAMEWORK)" "$(DESTDIR)$(LIBPL)/libpython$(LDVERSION).dylib"
  ```
  A filesystem glob found `config-3.14-darwin/libpython3.14.dylib`.

- `docs/execution-evidence-v4.md:235` requires resolving “the subject interpreter's real executable, sysconfig-selected standard library and extension directory.” Line 245 states: “Non-system verifier/runtime packages, compilers, backend executables and solvers still require actual content identities.”

- `tests/r38_evidence_v4_toolchain_review.py:646-669` requires ordinary Dossier imports to succeed. Lines 595–599 require external `tkinter` packages to refuse; lines 681–717 require an external `_tkinter.so` distribution to refuse even with native linkage.

- `tools/evidence-v4/evidence-v4-toolchain.ts:1391-1403` already passes `data.stdlib_native` into `context.native(...)` and incorporates its returned roots. Lines 666–671 separately reject selected external stdlib packages and extension modules.

### Reasoning

The native inventory confuses the Python runtime library with an external stdlib distribution. The reported `.../Versions/3.14/Python` is the framework library identified by the installed interpreter’s configuration. It is outside `stdlib` and `DESTSHARED`, so `standard_input()` necessarily rejects it. [INFERENCE] The traversal reaches it through `config-3.14-darwin/libpython3.14.dylib`, consistent with both the discovered filename and CPython’s installed symlink recipe.

This rejection happens at `inventory_native_stdlib()` before namespace inventory or request analysis (`:1305-1306`). Consequently, the failures do not demonstrate defects in external-module binding, absence revalidation, shadow tracking, or startup-hook handling. Their intended checks are blocked by one unconditional bootstrap rejection.

The strongest alternative is `infrastructure`, because every test encounters the installed Homebrew interpreter. However, the artifact shows an executing Python probe reaching an explicit application guard, and the rejected target is the configured framework runtime library. The contract requires binding that runtime. Neither a missing dependency nor an unsupported verification capability explains this failure. Weakening the external-package acceptance criteria would also contradict the stated contract.

### Recommended action

Route one targeted implementation correction to `inventory_native_stdlib()` at `tools/evidence-v4/evidence-v4-toolchain.ts:678-689`: distinguish the interpreter’s configured native runtime library from external stdlib distributions.

For this framework build, derive its exact canonical library path from `PYTHONFRAMEWORKPREFIX` plus `LDLIBRARY`. Permit that exact file in the native inventory and retain it in `stdlib_native`, so the existing native-discovery path binds its bytes and dependencies. Keep the exception local to native inventory; leave `standard_input()` and the selected-package/extension refusals at `:666-671` unchanged. Do not allow the entire framework prefix, exempt all symlinks, or discard the runtime library from inventory.

The corresponding regression should require successful framework-runtime capture with the library represented in the manifest, while retaining external-package/native-distribution refusal checks. Document this exact runtime-library treatment alongside the Python adapter contract.

### Meta

- Read: bounded failure excerpts and summary; Python discovery, native payload and native dependency code; CA21 tests and fixture setup; runtime contract; installed Python sysconfig declarations and Makefile installation rules.
- Unavailable evidence: direct symlink-target metadata and a successful post-fix manifest. Neither is needed to classify the observed guard failure.
- Diagnostic commands: none. Only read, grep, and glob operations; no edits or verification reruns.
- Confidence: high for `code_wrong`. The failure identifies the rejecting predicate, and installed configuration identifies the rejected file as the framework runtime. The precise symlink traversal edge remains inferred.

Skipped builds, tests, and edits as assigned. Risk: broadening runtime-root membership would admit external resource-bearing distributions; keep the exemption exact and content-bound.