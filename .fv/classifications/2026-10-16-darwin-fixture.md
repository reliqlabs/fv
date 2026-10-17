CLASSIFICATION: infrastructure  |  CONFIDENCE: high

### Evidence

Paths below are relative to `/Users/mv/Development/reliq-fv-wt/evidence-darwin-trees`.

- Supplied failure report: “PermissionError errno1 at shutil.copy2('/usr/bin/true',image), copystat->chflags(dst,st.st_flags)” and “No adapter execution reached in failed test.”
- `tests/r38_evidence_v4_toolchain_review.py:1705-1707`:
  ```python
  for image in images:
      image.parent.mkdir(parents=True, exist_ok=True)
      shutil.copy2("/usr/bin/true", image)
  ```
- The adapter invocation follows fixture construction at `tests/r38_evidence_v4_toolchain_review.py:1716`:
  ```python
  result = invoke(request)
  ```
  `invoke` launches Bun through `subprocess.run` at lines 119-121.
- `scripts/README.md:214-219`: “Native-free trees and payloads with only absolute vendor-system load commands remain supported.” Non-system edges refuse with “Unbound native tree launch context”.
- `tools/evidence-v4/evidence-v4-toolchain.ts:2424-2428`:
  ```typescript
  if (process.platform === "darwin" && declaration.kind === "tree") {
      const payloads = await nativePayloads(roots);
      if (payloads.length) {
          const native = await discoverNativeAdapter(context, [], { unboundPayloads: payloads });
          result = { ...native, roots };
  ```
- `tools/evidence-v4/evidence-v4-toolchain.ts:1507-1513` checks Mach-O dependencies against absolute `/usr/lib/` and `/System/Library/` paths, otherwise throwing `Unbound native tree launch context`.

### Reasoning

The reported failure occurs while constructing the fixture, before the verification target executes. `copy2` reaches metadata propagation and fails at `chflags`; this provides no counterexample to the generic tree behavior. Route it to test-fixture infrastructure.

The strongest alternative is `code_wrong`. The fixture does contain an unsuitable copy operation for this Darwin source, but the classification concerns the code under verification. Its adapter and assertions were never reached. There is no evidence here that the generic tree implementation violates its contract, or that the contract needs revision.

The fixture needs native image contents and executable permission bits. Replicating protected source flags is unnecessary for those requirements. Removing that metadata-copy requirement preserves the test’s intended payload coverage.

### Recommended action

Replace only the fixture copy at `tests/r38_evidence_v4_toolchain_review.py:1707`:

```python
shutil.copy("/usr/bin/true", image)
```

`shutil.copy` copies file contents and permission mode without `copy2`’s `copystat` flag propagation. Keep all images, assertions, and generic tree code unchanged; do not catch and suppress the permission error.

### Meta

- Read: the failing test and invocation helper, generic Darwin tree integration and native dependency guard, `scripts/README.md` contract, and ponytail guidance.
- Unavailable: full raw traceback and runtime Python version. The supplied failure report identifies the failing operation and execution boundary sufficiently for routing.
- Diagnostic commands: none. Used read/search tools only.
- Confidence: high for infrastructure routing. The observed exception precedes adapter execution; this classification makes no claim that the unexecuted assertions pass.

Skipped edits and all verification runs as requested. The corrected fixture’s adapter outcome remains unverified.