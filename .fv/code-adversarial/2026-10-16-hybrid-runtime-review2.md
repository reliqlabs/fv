# Code-adversarial review: Dossier hybrid runtime residual corrections - 2026-10-16

- Operator: fv-code-adversary via OMP task (NOT FixHybridResiduals, HybridBase, HybridProof, or the parent orchestrator)
- Code commit reviewed: `e5fec11`, delta against previously reviewed `2c7bd3c`
- Intent version reviewed: frontmatter version absent; canonical target remains `D/docs/intent.md`, resolved through `D/.fv/dispatch.json`
- Ledger version reviewed: frontmatter timestamp absent; document states `Updated: 2026-10-16`
- Lens pack: evidence provenance, loader/input closure, and installed-tool identity, using all six required crypto/enclave lenses
- Lenses applied: 1 through 6

## Scope and evidence

| Alias | Path |
|---|---|
| D | `/Users/mv/Development/burnt/dossier-wt/evidence-perf` |
| F | `/Users/mv/Development/reliq-fv-wt/evidence-hybrid-union` |
| T | `F/tools/evidence-v4/evidence-v4-toolchain.ts` |
| C | `F/tools/evidence-v4/evidence-v4-toolchain-common.ts` |
| TT | `F/tests/r38_evidence_v4_toolchain_review.py` |
| V4 | `F/docs/execution-evidence-v4.md` |
| CR | `F/.fv/changes/2026-10-14-execution-evidence-v4.md` |
| Capture | `/var/folders/ph/n581g1fj3tnbq8n74hp05klc0000gn/T/fv-hybrid-runtime-selection-bz1Jmw/identities.json` |

This delta reviews the prior runtime report’s CA-03, CA-05 and CA-07 corrections, their tests, and the retained selected-runtime capture. Finding IDs retain their meanings from the original report. That report remains immutable.

Commit attribution is caller-provided; working-tree equality to `e5fec11` was not independently established. No commands, tests, builds, formatters, edits, or process changes were performed.

The parent reports:

- Three regression methods produced 22 failed assertions against frozen `2c7bd3c`.
- The final corrected suite passed 46 methods.
- Actual Dossier discovery initially exposed a legitimate module-registry restoration refusal.
- After correcting that refusal, actual `mobile-node-toolchain` and `python-runtime` capture succeeded.

The retained JSON contains both named identities and the actual selected Node probe command requesting `executable`, `nodeOptions`, and `execArgv`, with recorded exit code zero and exact stream hashes. It contains metadata identities, not evidence executions or a complete policy verdict.

The updated ledger explicitly retains the failed canonical collection: run `a84f2846-5b3e-4054-bc4c-f3c6e64ab054` returned ERROR, with two ERROR physical slots and 80 MISSING slots. Its native-ownership failure and subsequent portable-checker rejection are not discharged by this delta.

Important uncovered classes remain process containment, concurrency/crash recovery, resource exhaustion, upstream-cache poisoning, supply-chain authenticity, and proof/model-to-implementation refinement.

## Delta disposition

| Prior finding | Disposition | Evidence |
|---|---|---|
| CA-03, opaque Python selector escape | Original dictionary/default/return forms addressed; finding remains OPEN through a class-namespace escape | T:690–696,774–776,935–938,1066–1068,1127–1140 add propagation/refusal. T:1136–1137 incorrectly treats an explicitly assigned class attribute as harmless when its abstract value equals an outer binding. |
| CA-05, preferred Node wrapper options | Closed for the reported mechanism | T:1721–1747 validates the complete transparent-wrapper chain before the selected-runtime probe. T:1750–1768 checks actual child options, exact probe argv, and executable correspondence. TT:1172–1201 exercises preload/environment injection refusal before its marker is written. |
| CA-07, whole pnpm-store enumeration | Closed for the reported mechanism | T:1782–1790 preserves the store boundary without registering it as a content root. C:625–672 registers selected canonical link targets and package dependencies, refusing whole-store selection. TT:1226–1309 covers unrelated-store exclusion, transitive dependency changes, and escape rejection. |
| CA-01 / Base CA-16 | OPEN, carried | Root-by-name substitution remains at T:1007–1009. |
| CA-02 / Base CA-17 | OPEN, carried | Defining-file specialization remains at T:999–1012; imported names become unknown at T:1057–1058. |
| CA-04 / transitive Base CA-21 | OPEN, carried | T:647–648 still skips transitive stdlib analysis. |
| CA-06 / generic Base CA-24 | OPEN, carried | T:2385–2392 still skips Darwin native-child discovery for ordinary trees. |

The Node and pnpm closures above are specific to the reviewed mechanisms. They do not qualify generic reuse, complete Dossier provenance, a canonical collection, or activation.

---

## Lens 1 - Commitment coverage

| Commitment | Attacker DoFs | Bound by | Gap |
|---|---|---|---|
| Opaque Python module references | Dictionary/list/default/return transport; assignments; class attributes | `opaque`/`refuse_opaque` at T:690–696; container checks at T:774–776,935–938; statement checks at T:1059–1068,1127–1140 | CA-03 remains: same-valued class assignments escape the final class check |
| Literal-key module-registry snapshot | Literal module-name tuple/list, saved values, iteration, restoration | T:769–773 restricts construction; T:821 returns opaque values; T:833–834 restricts `.items()`; T:1170–1175 binds iteration values as opaque | Direct indexing/use and restoration paths retain opacity. A snapshot can still escape through CA-03’s class path |
| Preferred Node runtime chain | Wrapper body, target pathname, injected environment/options, final executable | T:1721–1747 admits only native executables or exact transparent shell-wrapper forms; T:1750–1768 checks child state | Prior CA-05 mechanism closed; no additional defect established in this chain |
| Selected pnpm linked targets | Symlink destination, transitive declared packages, bytes beneath selected views | C:632–653 selects canonical targets and package closure; T:1788–1790 adds these roots | Prior CA-07 whole-store registration removed |
| Store containment | Link escaping the store or selecting the store itself | C:633–634,663–670; retained hasher check at C:435–437 | Explicit refusal |
| Symlink target commitment | Alias spelling, target manifest entry, target content | C:478–515 maps to retained canonical entries; directory hashes reconstructed afterward | Existing target-binding mechanism retained |
| File-root hardlink membership | Different path to the same inode; independent copy with identical bytes | T:2493–2513 and T:2661–2683 require origin eligibility plus retained hash/size/executable equality | No regression established; independent-copy equality alone remains insufficient |
| Root-by-name Python loader | Actual root argument value | T:1007–1009 substitutes project root by identifier | Carried CA-01 |
| Imported helper invocation | Caller-selected target outside defining-file calls | T:999–1012,1057–1058 | Carried CA-02 |
| Transitive stdlib inputs | External extension distribution selected indirectly | T:647–648 | Carried CA-04 |

### CA-03 residual: explicit class assignment is confused with inherited analysis state

The following valid Python source exposes the remaining mechanism:

    import importlib, sys
    loader = sys.modules["importlib"]
    class Holder:
        loader = loader
    Holder.loader.import_module("external_plugin")

The analysis proceeds as follows:

1. T:820 classifies `sys.modules["importlib"]` as `OPAQUE_MODULE`.
2. T:1062–1065 stores that value under the outer name `loader`.
3. T:1135 copies the outer analysis scope into the class-local scope.
4. The class assignment stores the same sentinel under the same name.
5. T:1136–1137 checks only names absent from the outer scope or values whose object identity differs. It therefore skips this explicitly published class attribute.
6. The resulting `Holder` object has no tracked opaque-field identity. Its attribute lookup and call fall through the unknown-value paths at T:787–809 and T:895–925.

[INFERENCE] With `external_plugin` available on an external import path, the runtime imports it while discovery neither records that dependency nor refuses this source. This counterexample was derived statically and was not executed.

The newly admitted snapshot representation has the same escape:

    import importlib, sys
    saved = {name: sys.modules.get(name) for name in ("importlib",)}
    class Holder:
        saved = saved
    Holder.saved["importlib"].import_module("external_plugin")

Here the copied `ModuleSnapshot` object is identical in the outer and local analysis scopes, so the class guard skips it as well.

This is one residual finding with two forms. It does not require a module-name exception, Base CA-16/17, transitive stdlib imports, or concurrent mutation. TT:379–416 tests a new class-local name, but not explicit assignment under an already opaque outer name. TT:418–475 checks direct snapshot escapes without this class transport.

## Lens 2 - Clause-to-line discharge

Statuses concern the delta and its immediate dependencies. They do not discharge the complete Dossier intent.

| Clause | Expected discharge | Actual code line | Status |
|---|---|---|---|
| D I11, `docs/intent.md:25`: unsupported closure prevents PASS | Unknown Python loader dependencies must refuse or be bound | T:1133–1137 permits the class escape | gap: CA-03; carried CA-01/02/04/06 also remain |
| V4:229,235,251: refuse unsupported Python loaders and unknown nonstdlib dependencies | Opaque selectors cannot become callable unknown objects | T:690–696,774–776,935–938,1066–1068,1133–1137 | partial: reported dictionary path fixed; class publication remains |
| V4:229: nonempty Node options and unmodeled selectors refuse | Reject option-bearing preferred wrappers before probing them | T:1721–1747 | discharged for reviewed wrapper forms |
| V4:241,243: actual selected runtime and retained probes | Check the child actually selected by the shim | T:1750–1768 | discharged for this correction |
| V4:231,241: no whole-store enumeration | Register selected targets and dependencies, retain containment boundary separately | T:1782–1790; C:625–672 | discharged for prior CA-07 mechanism |
| V4:219–223: canonical alias targets and content hashes | Selected link targets must exist in the retained manifest | C:478–515 and directory-hash reconstruction | discharged in inspected path |
| V4:243: endpoint identity revalidation | Recompute discovered identities and exact probe selection | T:2701–2731 | discharged for discovered inputs; completeness remains partial |
| V4:163–165: operational and cache assumptions remain explicit | Do not equate stable bytes with complete provenance or fresh compilation | C:338–378; T:2701–2731; residual comments at T:647,973,2385 | partial by design; no additional premise established |
| D I12, `docs/intent.md:32`: preserve execution argv/cwd, bounds, slots and observations | Discovery corrections do not rewrite evidence execution | T:1750–1753 constructs a separate metadata probe; this delta does not discharge scheduling/store behavior | partial; no changed evidence-command claim established |
| D I13/I14, `docs/intent.md:33–34` | No activation or authority upgrade | No activation mechanism in the reviewed corrections; CR:180–182 explicitly limits metadata acceptance | partial; activation remains outside this delta |
| V4 S1/S2 | Preserve slot membership and immutable ownership | No new enforcement in these adapter corrections | partial; prior store obligations unchanged |
| V4 B1/B2 | Complete admissible provenance and no stale/unrun promotion | Membership checks at T:2485–2519; remaining discovery gaps above | partial |
| V4 T1/T2 | Failure/ownership discipline and endpoint drift rejection | T:2701–2731 covers discovered drift only | partial; native ownership is not repaired here |
| Ledger C-01 through C-15 | Retain bounded/projection limitations and incomplete conjunctions | No model-to-code or chain-provenance discharge in T/C | partial; all remain INCOMPLETE |
| Ledger TA-07/TA-08 | Preserve host-evidence and operator-honesty limits | Capture contains unsigned local identities and probe hashes | partial; no independent operator attestation |
| Ledger TA-01–TA-06 and TA-09–TA-17 | Preserve external platform, custody, chain, release and time assumptions | No discharge in this delta | partial; unchanged |

## Lens 3 - Deferred cannot silently succeed

| Branch | Reachable from | Behavior | Status |
|---|---|---|---|
| Class-local opaque assignment equal to outer abstract binding | Python source analysis | Class guard skips the exported value; later class use becomes unknown | gap: CA-03 |
| Literal-key registry snapshot | Python collector snapshot/restore | Produces `ModuleSnapshot`; accesses and item iteration produce opaque values | Acceptable admitted form except for the separate class escape |
| Unsupported snapshot shape or escape | Python comprehensions, containers, defaults and direct accesses | Generic expression/default checks refuse opaque values | Explicit refusal for inspected forms |
| Option-bearing preferred Node wrapper | Selected Node runtime | Fails exact wrapper grammar before selected-runtime probe | Explicit refusal; prior CA-05 closed |
| Wrapper cycle | Preferred runtime chain | Throws at T:1734 | Explicit refusal |
| Whole-store or escaping selected target | pnpm linked-root discovery | Throws at C:633–634,669–670 | Explicit refusal |
| Root-by-name/imported-helper shortcuts | Python loader discovery | Still admit analysis without establishing complete runtime targets | Carried CA-01/02 |
| Transitive stdlib shortcut | Python import resolution | Returns without transitive scanning | Carried CA-04 |
| Darwin ordinary-tree shortcut | Non-adapter tree discovery | Tree hashing proceeds without native-child closure | Carried CA-06 |

The deferred Python function-body worklist remains actual analysis work, not an implementation stub. Its existence does not discharge the identified gaps.

## Lens 4 - Who controls

| Field | Supplier | Validation | Gap |
|---|---|---|---|
| Opaque selector classifications | Analyzer-derived from Python source | Central `opaque` predicate, explicit refusal and propagation | CA-03 at class namespace publication |
| Snapshot module keys | Python source author | Literal string tuple/list and restricted comprehension at T:770–773 | No hardcoded module-name exception found |
| Snapshot values and restored values | Interpreter module registry | Abstracted as opaque; item binding at T:1175; registry-only opaque assignment at T:1066–1068 | Direct restoration preserves classification; class transport remains CA-03 |
| Preferred wrapper body/target | Installed runtime files | Exact complete-body grammar, absolute target, cycle check and native endpoint | No additional gap established for prior CA-05 |
| Actual Node options and `execArgv` | Selected child process | Empty options, exact two-argument probe spelling, expected expression, matching executable at T:1754–1768 | Checked and retained through exact probe identity |
| pnpm store boundary | Producer-derived canonical store path | T:1783–1786; C:633,669 | Boundary remains enforced |
| Selected linked roots | Directory/link topology and installed manifests | C:632–653; package closure via `packageRoots` | No whole-store root registered by the corrected path |
| Local origin inode and manifest entries | Producer filesystem observations | Both indexed consumers retain physical-origin and byte-metadata checks | No new hash-only alias acceptance |
| Trust assumptions | Reviewed policy/operator | Declared operational, cache and store premises | Not proved by successful capture or endpoint equality |

## Lens 5 - Field-name fidelity

| Field | Implied semantic | Actual value | Status |
|---|---|---|---|
| Probe `nodeOptions` | Effective selected process `NODE_OPTIONS` | `process.env.NODE_OPTIONS ?? ""`, T:1751 | faithful |
| Probe `execArgv` | Effective runtime arguments | `process.execArgv`, T:1751 | faithful |
| Probe `executable` | Selected process executable | `process.execPath`, compared with the inspected chain endpoint at T:1767 | faithful |
| `execution/node-wrapper-target/<n>` | Inspected target at a wrapper-chain step | Canonical target added at T:1744–1746 | faithful |
| `execution/node-store/<index>/<relative-target>` | Selected canonical target view within the store | C:636–640 constructs label from the boundary-relative target | faithful; no longer denotes a recursively captured whole-store root |
| Symlink `resolved_path` and content fields | Canonical retained target and its bytes | C:478–515 | faithful in inspected path |
| `ModuleSnapshot` / `ModuleSnapshotItems` | Internal bounded registry snapshot and item view | T:691–694,773,834 | Internal abstractions, not public serialized fields |

No separate field-name finding was established. The earlier child-runtime-options overstatement is corrected by actual code; the remaining opaque-selector completeness claim is qualified by CA-03.

## Lens 6 - Deferral justification audit

| Deferred finding | Justification claims | Claim audit | Verdict |
|---|---|---|---|
| Prior CA-03 | Opaque selectors remain classified through container/default/return/assignment paths | Original dictionary/default/return paths now refuse. Class assignments are checked only when abstract values differ from the copied outer scope | Incomplete correction. Keep CA-03 OPEN with the class counterexample |
| Prior CA-05 | Actual preferred runtime options/argv checked; unmodeled wrappers refuse before execution | Complete wrapper inspection precedes selected-runtime probing; child state and executable correspondence are checked | Closed for the reported mechanism |
| Prior CA-07 | Store roots narrowed to selected canonical targets and dependency closure; escapes still refuse | T:1788–1790 and C:625–672 implement this separation; existing manifest alias checks remain | Closed for the reported mechanism |
| Base CA-16/17 | Root-value/imported-helper analysis remains incomplete | T:999–1009,1057–1058 retain those mechanisms | OPEN; accurate deferral, not new findings |
| Transitive Base CA-21 | Direct split imports refuse, transitive closure remains open | T:647–648 still skips transitive stdlib scanning | OPEN; accurate deferral |
| Generic Base CA-24 | Darwin tree linkage remains open | T:2385–2392 retains the omitted discovery path | OPEN; accurate deferral |
| Registry-restoration compatibility correction | Literal-key snapshot, key iteration and two-name item iteration admitted without module-name exception | T:770–773,1170–1175; TT:418–475 exercises alternate literal names and direct escapes | Supported within those forms; class export is not covered |
| Reported 46-method suite and selected D capture | Regression and metadata acceptance only | Tests inspect the named negative/positive forms; Capture contains the named tool identities and effective-runtime probe identity | Limited claim supported; no complete collection or qualification follows |
| Fresh-provenance limits | Open loader/tree defects affect fresh collection as well as reuse | Comments at T:647,973,2385 and CR:182 now say this explicitly | Accurate; no reuse-only deferral remains in these comments |

### Nonmutation premise

No unsafe widening of `no_concurrent_mutation` was established in the Node, store-selection, or indexed-origin corrections:

- Wrapper selection is inspected before the selected-runtime probe.
- Selected targets remain content-hashed and subject to endpoint revalidation.
- Store containment remains separate from capture breadth.
- Both indexed-origin consumers still require retained hash, size, executable bit and regular-file kind after physical-origin eligibility.

The class counterexample needs no concurrent writer. Neither does the underlying omission in the four explicitly open loader/tree findings. Stable inputs can still be incompletely discovered.

---

## Finding list (consolidated)

These IDs preserve the original report’s identities. CA-05 and CA-07 are closed and therefore absent from the active finding table.

| ID | Lens | Severity | Surface | Intent ref | Code ref | Summary | Fix |
|---|---|---|---|---|---|---|---|
| CA-01 | commitment-coverage | Major | Python helper root | D I11; V4:229,235,249,251 | T:999–1009 | OPEN, carried Base CA-16. Root argument identity is accepted by name and replaced with the project root without establishing its runtime value. | Bind the actual root value or refuse the invocation. Retain fresh-provenance limits until discharged. |
| CA-02 | commitment-coverage | Major | Imported Python loader helpers | D I11; V4:229,235,249,251 | T:999–1012,1057–1058 | OPEN, carried Base CA-17. Defining-file specialization does not establish caller-selected targets through imported helpers. | Preserve helper identity and validate caller arguments, or refuse unsupported imported-helper use. |
| CA-03 | commitment-coverage | Minor | Opaque selector class publication | D I11; V4:229,235,251; CR:178 | T:1062–1068,1133–1137; TT:379–475 | Original dictionary escape fixed, but an opaque outer name explicitly assigned under the same class-local name is skipped because its abstract object identity is unchanged. `Holder.loader` or `Holder.saved[...]` becomes unknown and can invoke an unrecorded external import. Newly identified static residual; not executed. | Track names actually written in the class namespace and reject opaque values exported under those names, even when equal to an outer binding. Add direct-opaque and snapshot same-name class regressions while preserving legitimate registry restoration. |
| CA-04 | commitment-coverage | Minor | Transitive split-stdlib closure | D I11; V4:235,249,251 | T:647–648 | OPEN, carried transitive Base CA-21. Direct split imports refuse; transitive standard-library paths remain unscanned. | Bind applicable external split distributions or refuse unsupported paths. Do not infer closure from selected capture success. |
| CA-06 | clause-to-line | Minor | Darwin non-adapter trees | D I11; V4:245,249,251 | T:2385–2392 | OPEN, carried generic Base CA-24. Ordinary Darwin trees still omit native children’s external linkage. Actual exposure in D’s selected installation is not established by this review. | Discover dependencies in actual launch contexts or refuse unsupported trees. Preserve the generic fresh-provenance limitation. |

## Summary

- Total active findings: 5, comprising 4 explicitly carried findings and 1 incomplete correction with a newly identified residual counterexample.
- By severity: Critical=0 Major=2 Minor=3 Informational=0.
- By lens: commitment-coverage=4 clause-to-line=1 deferred-cannot-silently-succeed=0 who-controls=0 field-name=0 deferral-justification=0.
- Delta closure: CA-05 and CA-07 closed for their reported mechanisms. CA-03’s original dictionary mechanism is addressed, but the finding remains OPEN through class namespace publication.
- Recommended next step:
  1. Correct class-written-name tracking for opaque selectors and snapshots.
  2. Have the parent add and run the two same-name class regressions alongside the existing registry-restoration cases.
  3. Keep Base CA-16/17, transitive CA-21 and generic CA-24 OPEN, including their fresh-provenance implications.
  4. Retain the separation between selected metadata capture, isolated regression evidence, canonical collection, generic reuse qualification and activation.

No generic reuse, canonical collection, or activation qualification is established.