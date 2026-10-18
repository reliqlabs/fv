CLASSIFICATION: spec_wrong  |  CONFIDENCE: high

### Evidence

Repository paths below are relative to `/Users/mv/Development/reliq-fv-wt/evidence-darwin-trees`.

- `artifact://20938` reports:
  ```text
  {'before': True, 'tests': 4, 'failures': 9, 'errors': 0, 'skipped': 0, ...}
  {'before': False, 'tests': 4, 'failures': 6, 'errors': 0, 'skipped': 0, ...}
  ```
  All six remaining failures specify `little=True`, covering both `wide=False` and `wide=True`. Their returned error is:
  ```text
  Mach-O load-command metadata is absent: .../installed/fat-images/data.class
  ```
- Apple’s authoritative [`include/mach-o/fat.h`, lines 36-37](https://github.com/apple-oss-distributions/cctools/blob/main/include/mach-o/fat.h#L36-L37):
  > All structures defined here are always written and read to/from disk  
  > in big-endian order.

  The same header defines:
  ```c
  #define FAT_CIGAM    0xbebafeca /* NXSwapLong(FAT_MAGIC) */
  #define FAT_CIGAM_64 0xbfbafeca /* NXSwapLong(FAT_MAGIC_64) */
  ```
- `tests/r38_evidence_v4_toolchain_review.py:1655-1675` writes the fat header and architecture table using:
  ```python
  endian = "<" if little else ">"
  ```
  Both `struct.pack_into` operations use that selected byte order.
- `_macho_bytes`, at `tests/r38_evidence_v4_toolchain_review.py:1629-1653`, independently writes the embedded Mach-O header and load commands using `"<8I"` and `"<6I"`.
- `tests/r38_evidence_v4_toolchain_review.py:1731-1753` includes both outer byte orders in the valid-image test. It requires `result["ok"]` for system-only fixtures and `"Unbound native tree launch context"` for external-edge fixtures.
- `tools/evidence-v4/evidence-v4-toolchain-common.ts:262-264`:
  ```typescript
  const blocks = text.split(/^[ \t]*Load command [0-9]+[ \t]*$/gmu);
  if (blocks.length === 1) throw new Error("Mach-O load-command metadata is absent");
  ```
- `scripts/README.md:223-227` states:
  > Native members take precedence in ambiguous data. Truncated or  
  > unrecognized native-magic contents still require native metadata inspection;

### Reasoning

The `little=True` fixtures violate Apple’s on-disk fat-container format. That format requires big-endian fat headers and architecture tables for both fat32 and fat64. `FAT_CIGAM` constants describe byte-swapped magic values; their existence does not authorize little-endian serialization of those structures.

The test conflates the container’s byte order with its members’ byte order. Its embedded ARM64 and x86_64 Mach-O images are already little-endian, including when `little=False`. A big-endian fat container with those little-endian members retains the intended architecture and load-command coverage.

The failing specification is therefore the test’s expectation that these malformed containers receive valid-image treatment. Two cases demand successful capture; four demand a particular dependency-refusal diagnostic even though metadata interpretation has already failed. Refusal remains faithful to the documented contract.

The strongest alternative is `tool_mismatch`, interpreting this as a valid format unsupported by `otool`. Apple’s explicit serialization rule excludes that interpretation for these fixtures. The evidence also does not establish a production parser bug: the supplied result shows missing recognizable load-command metadata, without raw `otool` output demonstrating valid load commands that the parser discarded.

### Recommended action

Correct the fixture classification: use only big-endian outer headers/tables in `test_ca26_fat_macho_tree_inspects_all_slices_and_refuses_external_edges`, retaining both fat32/fat64, both architectures, and both external-dependency positions. Move the little-endian-container cases into malformed-input coverage and require refusal without prescribing a particular error string.

Keep `_macho_bytes` little-endian. No production-source change is justified by these six failures.

### Meta

- Artifacts read: `artifact://20938`; fixture helpers, valid-fat assertions and malformed-input assertions; `nativeFileKind`, load-command parser and adapter probe path; current README contract; Apple’s public `fat.h`.
- Unavailable: raw `otool` stdout/stderr for the failing fixtures and the exact installed tool version. These would explain its diagnostic presentation, but are unnecessary to decide the format-validity question.
- Diagnostic commands: none. Only artifact, source and documentation reads/searches.
- Confidence: high because the fixture’s serialization directly contradicts Apple’s explicit on-disk requirement, and all six reported residual failures share that serialization choice.

No edits or test runs performed. Correcting the fixture expectations does not independently prove the broader native discriminator correct.
