# Code-adversarial review: Dossier evidence v4 isolated proof/source adapters - 2026-10-16

- Operator: fv-code-adversary via OMP task (NOT HybridBase, HybridProof, or parent orchestrator)
- Code commit reviewed: `2c7bd3c`, base `e36b939`, as supplied. Reviewed worktree files; commit-to-worktree equality was not independently checked.
- Intent version reviewed: no frontmatter version. Canonical target is `D/docs/intent.md`, resolved through `D/.fv/dispatch.json` → `omp_native.target_spec`.
- Ledger version reviewed: frontmatter timestamp absent; body states `Updated: 2026-10-08`.
- Lens pack: crypto/enclave lenses, supplemented with loader/input-closure and execution-provenance analysis.
- Lenses applied: 1 through 6.
- Method: static inspection only. No commands, tests, builds, edits, or process changes.

## Scope and evidence

| Alias | Path |
|---|---|
| D | `/Users/mv/Development/burnt/dossier-wt/evidence-perf` |
| F | `/Users/mv/Development/reliq-fv-wt/evidence-hybrid-union` |
| DI | `D/docs/intent.md` |
| V4 | `F/docs/execution-evidence-v4.md` |
| CR | `F/.fv/changes/2026-10-14-execution-evidence-v4.md` |
| P | `F/tools/evidence-v4/evidence-v4-toolchain-proof.ts` |
| S | `F/tools/evidence-v4/evidence-v4-source.ts` |
| TC | `F/tools/evidence-v4/evidence-v4-toolchain.ts` |
| C | `F/tools/evidence-v4/evidence-v4-toolchain-common.ts` |
| PC | `F/scripts/fv_evidence_v4.py` |
| PT | `F/tests/r38_evidence_v4_proof_review.py` |
| ST | `F/tests/r38_evidence_v4_source_review.py` |
| TT | `F/tests/r38_evidence_v4_toolchain_review.py` |

The seven named prior defects are closed for their original mechanisms. One new Minor TS/Python selector-validation discrepancy remains; derived-native parity is therefore partial.

The parent’s reported 112 passing integrated tests and temporary-project plan READY, run PASS, one shared dispatch, and portable exit 0 are accepted as reported observations. They were not rerun and do not establish general cache-reuse qualification.

Important uncovered classes: scheduler concurrency, resource exhaustion, ownership recovery, storage/error atomicity, supply-chain authenticity, arbitrary wrapper analysis, and non-Lean runtime data dependencies. Dossier protocol authorization, arithmetic, migration, and enclave security are outside this adapter review.

---

## Lens 1 - Commitment coverage

| Commitment | Attacker DoFs | Bound by | Gap |
|---|---|---|---|
| Quint application/backend identity | CLI selection, subcommand, backend/configuration arguments, omitted adapter | TC:2497-2526 requires the installed CLI and matching adapter/subcommand. P:349-359 collects its actual application contexts; P:360-499 binds selected backends/configuration. | Original ProofCA01 closed. Generic wrapper analysis is not qualified. |
| Application Lake workspace | `-d`/`--dir` spelling, symlink-before-`..` traversal | P:38-47 checks components before traversal; P:888-909 applies it to application directories and compares effective contexts. | Original ProofCA02 closed. |
| Apalache JAR | Relative environment value and differing recipe cwd | P:465-473 refuses relative `APALACHE_JAR` and binds the selected absolute file. | Original ProofCA03 closed. |
| Elan-selected distribution | CLI override, environment, directory overrides, ancestor pins | P:760-788 performs nearest-directory selection and checks actual `elan which` results against the selected installation. | Original ProofCA04 closed. |
| Lake source closure | Prebuilt search paths; Lean sources placed in generated namespaces | P:1190-1245 adds overlapping Lean files to mandatory requirements and restricts prebuilt search paths. S:262-285 enforces membership. | Original SourceCA12/13 closed within the declared cache-integrity boundary. |
| Derived native tool identity | Launcher, selected Rustup driver, dylibs, recorded selector | C:115-123 detects sibling hardlinks; TC:1308-1324 binds the selected driver; S:331-389 validates derived shape and bytes. | Original SourceCA14 closed. Selector-validation parity has new CA-01 below. |

These hashes establish recorded content identity. They do not authenticate the operator, prove source-to-binary correspondence, or independently establish generated-cache integrity.

## Lens 2 - Clause-to-line discharge

| Clause | Expected discharge | Actual code line | Status |
|---|---|---|---|
| DI I11, V4:249-251: complete applicable tool closure | Refuse a recognizable Quint command without matching backend discovery | TC:2497-2526; P:349-359 | discharged for inspected direct CLI/package-entry surfaces |
| DI I12, V4:239: actual cwd/tool selection | Bind the workspace and Lean distribution used by the application | P:760-788, 829-841, 888-909 | discharged for reviewed selector grammar |
| V4:138, 153: complete source dependency closure | Required source inputs cannot disappear behind generated-output exclusions | P:1165-1208; S:262-285; run preflight at `evidence-v4-run.ts:526` | discharged for enumerated Lean sources/input targets |
| V4:163-177: declared upstream-cache boundary | Permit generated imports only in selected Lake cache namespaces under a declared Lake recipe | P:1212-1245; TC:2659-2695 | discharged for inspected permission check; upstream product correctness remains assumed |
| V4:227: derived roots, driver selection, producer/checker agreement | Same accepted selector spellings and derived identity constraints | S:378-386 versus PC:354-368 | partial: CA-01 |
| V4:229: unsupported configuration refuses | Reject unsupported Lake constructs, loader options, and TLC arguments | P:328-329, 426-438, 505-507, 624-689, 1007-1008, 1247-1249 | discharged for inspected allowlists |
| V4 B1/B2 and DI I11: no unsupported closure becomes reusable PASS | Validate command, descriptor and required sources before candidate lookup | `evidence-v4-run.ts:508-533` | partial: this review discharges the adapter/source preflight seam only |
| DI I12 and V4 S1/S2/T1/T2: membership, ownership, failure history and recovery | Preserve the full execution/claim lifecycle | Outside these adapters | partial; no lifecycle qualification |
| DI I13/I14: activation separation and bounded authority | Do not promote local adapter checks into deployment authority | No activation changes in inspected files | unchanged; no activation discharge claimed |
| Ledger C-01 through C-15 | Fresh evidence and each candidate’s missing composition links | Adapter identities supply provenance inputs only | partial; all existing INCOMPLETE statuses retained |
| Ledger TA-08 | Independent authenticity of unsigned local evidence | No signature/authentication mechanism in this slice | open assumption, unchanged |
| Ledger TA-01..TA-07 and TA-09..TA-17 | Their separately named platform, behavioral, custody and deployment premises | Outside this slice | unchanged; no discharge claimed |

The JVM heap-reference correction remains present at P:508-514: discovery uses `-XX:-UseCompressedOops`. PT:384-414 retains the paired heap-mode regression. This review did not establish byte-for-byte equality with the base commit or rerun the JVM check.

## Lens 3 - Deferred cannot silently succeed

| Branch | Reachable from | Behavior | Status |
|---|---|---|---|
| Missing/mismatched Quint adapter | Recipe/check command binding | Throws before ordinary file-origin acceptance, TC:2497-2526 | explicit refusal |
| Relative `APALACHE_JAR` | Verification backend discovery | Throws, P:465-466 | explicit refusal |
| Unbound prebuilt search directory | Lake metadata discovery | Throws unless attested installed input or exact permitted generated library directory, P:1238-1245 | explicit refusal |
| Lean source under a generated exclusion | Lake source discovery, then recipe preflight | Added to `sourceRequirements.files`; omission throws, P:1190-1208 and S:262-265 | no silent omission found for the original case |
| Unsupported Lake target/configuration | Metadata/configuration discovery | Throws, P:624-689, 1007-1008, 1247-1249 | explicit refusal |
| TODO/stub/mock/deferred implementation branches in P and S | Searched production targets | No such markers found | empty deferred-implementation surface in these two files |
| Generic Darwin tree linkage | Non-adapter tree identity | Existing shortcut remains at TC:2285-2286 | previously open BaseCA24; not closed or counted as new |

## Lens 4 - Who controls

| Field | Supplier | Validation | Gap |
|---|---|---|---|
| Quint CLI/subcommand | Reviewed policy author | Installed package entry and adapter-subcommand equality, TC:2504-2523 | none found in named mechanism |
| Lake directory selector | Reviewed recipe/check argv | Component-wise symlink refusal and effective-context equality, P:888-909 | none found |
| `APALACHE_JAR` | Sanitized policy environment | Absolute-path requirement, physical input-path checks, manifest/bootstrap validation, P:465-499 | none found in relative-path mechanism |
| Elan override DB/pin | Local installation and project configuration | Per-directory DB-before-pin selection; unforced probes absent a CLI selector, P:760-788 | none found in original precedence mechanism |
| `initialLeanPath` / `initialSourcePath` | Lake environment metadata | Attested-root coverage; exact generated-library equality only for permitted library paths, P:1212-1245 | none found in original arbitrary-prebuilt mechanism |
| Generated exclusions and required files | Lake configuration plus adapter derivation | Overlapping `.lean` files become explicit required inputs; input-directory exclusions cannot silently drop contents, P:1176-1208; S:267-285 | none found in original exclusion mechanism |
| Rustup driver/probe identity | Local selector during production; retained JSON during portable checking | Inode detection and selected-driver binding; independent recorded-shape validation | CA-01: Python normalizes selector spelling differently from TS |

No separate persistent state machine exists in P or S. Their externally retained state is the descriptor/tool/source identity assembled downstream.

## Lens 5 - Field-name fidelity

| Field | Implied semantic | Actual value | Status |
|---|---|---|---|
| `sourceRequirements.files` | Individually mandatory source inputs | Direct Lean subjects, explicit input files, and Lean files found within generated exclusions | faithful, P:849-855, 1181-1208 |
| `sourceRequirements.inputDirectories` | Directories whose complete file contents are inputs | Input targets, walked with `all=true` | faithful, P:1181-1187; S:267-285 |
| `sourceRequirements.excludedPaths` | Namespaces skipped by the ordinary module walk | Effective generated namespaces; explicit required files are checked first | faithful only as part of the paired discovery/enforcement contract, P:1146-1208; S:262-276 |
| `selected-file` | Selected launcher/file bytes | Actual selected file root | faithful, TC:2323-2330 |
| `native/drivers/{cargo,rustc}-0` | Rustup-selected driver bytes | Successful `which` result, separately hashed | faithful, TC:1308-1324 |
| `discovery.command` | Exact probe argv | Retained exact argv; Python’s family check interprets terminal `/.` differently | CA-01, counted under lens 2 |
| `ToolIdentity.digest` | Content identity | Kind, files, packages and system dependencies; discovery remains a separately retained field | faithful, TC:2360-2386; no authentication claim |

## Lens 6 - Deferral justification audit

### Exact prior-finding dispositions

| Deferred finding | Justification claims | Claim audit | Verdict |
|---|---|---|---|
| ProofCA01, Major | Every recognized Quint command needs the matching CLI/subcommand adapter | TC:2497-2526 closes the adapter-omission path. P:349-359 checks application subcommands. PT:237-255 covers omitted adapters; TT:553-614 covers wrong subcommand, aliased CLI and wrapper/internal entry refusal. | closed |
| ProofCA02, Minor | Application Lake `-d` is symlink-safe | P:888-896 now uses `inputPath`; P:38-47 checks a symlink before applying later `..`. PT:630-646 covers malicious spellings and ordinary `-d .`. | closed |
| ProofCA03, Minor | Relative JAR selection cannot bind the wrong cwd | P:465-466 refuses it outright. PT:357-367 supplies different adapter/application directories. | closed |
| ProofCA04, Minor | Nearest-directory selection checks override DB before pin; probes do not force the modelled selection | P:761-768 implements the directory ordering. P:777 forces `ELAN_TOOLCHAIN` only for explicit CLI selection. P:778-788 validates actual selections. PT:648-673 covers nearer pin and same-directory override. | closed |
| SourceCA12, Major | Arbitrary prebuilt imports refuse; exact declared Lake generated library path remains usable | P:1238-1245 requires attested input coverage or exact `generatedLibraries` membership with `declaredLakeCache`. PT:800-856 covers arbitrary paths, no-cache refusal, exact-cache permission, and an additional unmatched check context. | closed |
| SourceCA13, Minor | Generated exclusions cannot hide Lean sources | P:1190-1208 scans overlapping excluded namespaces and records `.lean` files explicitly. S:262-265 checks these before exclusions. PT:858-915 covers nested/custom/default namespaces and missing closure entries. | closed |
| SourceCA14, Minor | Hardlinked Rustup proxies bind their selected driver; direct Rust commands cannot omit their family adapter | C:115-123 uses inode identity; TC:1308-1324 retains selector discovery and driver bytes; TC:2535-2538 adds the family gate. TT:616-638, 1369-1475 covers detection, family refusal and derived drivers. | closed for the original hardlink/adapter-omission defect |
| Accompanying derived-native parity claim | TS and Python now apply equivalent byte, executable, encoding and driver-selection checks | Byte/executable/library-encoding checks align in S:340-371 and PC:326-389. ST:788-906 contains paired vectors. Selector basename interpretation still differs. | partial: new CA-01 |
| Generic Python provenance | BaseCA16/17 remain open; BaseCA21 transitive split-stdlib closure remains open | CR §Isolated hybrid integration explicitly retains these limits. Their implementations were not independently requalified here. | open, unchanged |
| Generic Darwin provenance | BaseCA24 remains open despite frozen-installation restrictions | CR §Isolated hybrid integration and TC:2285-2286 retain the limitation. | open, unchanged |

The Elan regression uses two selector names linked to the same physical distribution, PT:579-590. It checks chosen selector labels but cannot independently demonstrate rejection when an unforced probe returns a physically different distribution. The production containment check is present at P:786-788; that negative experiment remains unexercised by this reviewer.

No separate wrong-deferral finding is added for the historical claims. CA-01 bounds the new parity claim.

---

## Finding list (consolidated)

| ID | Lens | Severity | Surface | Intent ref | Code ref | Summary | Fix |
|---|---|---|---|---|---|---|---|
| CA-01 | clause-to-line | Minor | Portable derived-native Rustup selector validation | DI I11; V4:26, 227 | S:378-386; PC:354-368; ST:850-906 | `[INFERENCE]` Python `Path(...).name` collapses terminal `/.`, while TS `path.basename(...)` returns `"."`. Consequently, Python accepts selector spellings that TS rejects, including a purported successful Rustup probe whose executable ends in `/rustup/.`. The paired vectors do not cover these spellings. | Use the same non-normalizing POSIX basename semantics on both sides for the locator and discovery executable. Extend paired vectors with terminal `/.` for both fields, retaining ordinary absolute and trailing-slash cases. |

### CA-01 counterexample and impact bound

Start with the valid `selected-driver` identity in ST:850-875, keeping its nonempty executable launcher/driver files and successful three-token probe.

Two independent mutations expose the discrepancy:

1. Change the locator in both declaration and identity to `{mode:"path", value:"/recorded/cargo/."}`.
   - Python’s check at PC:354 sees basename `cargo`.
   - TS’s check at S:378 sees basename `.` and refuses.

2. Keep the valid `cargo` locator and change the recorded probe to `["/recorded/rustup/.", "which", "cargo"]`.
   - Python’s check at PC:366 sees `rustup`.
   - TS’s check at S:383 sees `.` and refuses.

These strings are admitted by the locator/command string grammar: `evidence-v4-model.ts:745-749,783-785` and `fv_evidence_v4_schema.py:231-240`. The discrepancy is in semantic identity validation.

This is an unexecuted static counterexample. It establishes a checker-parity defect, not a demonstrated stale-PASS execution. An honest producer cannot successfully execute a regular Rustup file through a terminal `/.`; no real Dossier impact is established. The portable checker nevertheless accepts a purported selector witness outside the TS acceptance set.

## Summary

- Total findings: 1 new; previously open generic findings are retained separately.
- By severity: Critical=0 Major=0 Minor=1 Informational=0.
- By lens: commitment-coverage=0 clause-to-line=1 deferred-cannot-silently-succeed=0 who-controls=0 field-name=0 deferral-justification=0.
- Prior dispositions: ProofCA01..04 closed; SourceCA12..14 closed for their original mechanisms. Derived-native TS/Python parity remains partial through CA-01.
- Recommended next step:
  1. Align the two selector-basename checks and add the two paired negative vectors.
  2. Have the parent exercise the focused source-parity regression after correction.
  3. Optionally strengthen the Elan regression with physically distinct installed selections to exercise the unforced mismatch refusal.
  4. Keep generic Python/Darwin provenance work, the native-ownership collection repair, and any subsequent full Dossier admission as separate gates.

Not checked: command execution, commit/worktree equality, full Dossier collection, or general cache reuse. The installed runtime remains `e36b939`; the reported native-ownership ERROR remains unresolved by this review.
Risk: these closure dispositions do not qualify activation, production provenance, or reuse across the previously open generic loader boundaries.