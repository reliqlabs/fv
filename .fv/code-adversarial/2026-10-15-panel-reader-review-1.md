# Code-adversarial review: dossier FV/OMP panel-reader compatibility - 2026-10-15

- Operator: fv-code-adversary via OMP task (NOT parent orchestrator)
- Code commit reviewed: FV925d800d421b9c1ca805ab72bc82a9edc32d1569 plus OMPb8699054e09476c734df58776ace46434741a7d7, as supplied by the caller. Inspection used the supplied working-tree paths; commit-to-tree correspondence was not independently checked.
- Intent version reviewed: absent from frontmatter. Canonical target resolved through `.fv/dispatch.json` to `docs/intent.md`; active dossier-v2.1, proposed dossier-v3, with the 2026-10-14 evidence-performance amendment.
- Ledger version reviewed: absent from frontmatter; body records `Updated: 2026-10-08` and subsequent integration notes.
- Lens pack: crypto/enclave, supplemented with configuration precedence, SDK exposure, model-lineage provenance and backward-compatibility checks.
- Lenses applied: 1 through 6

## Scope and evidence

Path aliases used in citations:

- `D` = `/Users/mv/Development/burnt/dossier-wt/evidence-perf`
- `F` = `/Users/mv/Development/reliq-fv-wt/evidence-perf`
- `O` = `/Users/mv/Development/personal/oh-my-pi-fv-panel/packages/coding-agent/src`
- `C` = `/Users/mv/Development/personal/oh-my-pi-fv-panel/packages/catalog/src`

Primary inspection covered `F/tools/panel-resolver.ts`, `F/tests/r32_resolver_contract.py` and `O/panel/index.ts`. Supporting inspection traced their registered setting, effective Settings reads, panel parser/resolver, classifier, root SDK export and custom-tool dependency injection. Compatibility is treated as established.

The applicable Dossier obligations are evidence provenance, preservation of existing behavior and limits on assurance claims: `D/docs/intent.md:25,32-34`, ledger TA-07/TA-08 at `D/.fv/ledger.md:460-461`, and its incomplete composition status at `D/.fv/ledger.md:5-15`. The concrete reader contract is `F/INSTALL.md:31-34`; R32's real-OMP requirement is `F/INSTALL.md:341-345`. Dossier's cryptographic and on-chain clauses are outside this compatibility repair and are not discharged here.

The parent reports successful package checking, 41 panel tests, real root-SDK role lookup, R32 and legacy/preferred/missing-reader smokes. Those observations are accepted as parent-reported evidence. This reviewer ran no tests, builds, commands or live operations and changed no files. No external model dispatch or served-route independence was exercised. This native-agent review makes no multi-family diversity claim.

Important uncovered classes remain: extension authorization, concurrent settings mutation during dispatch, provider-side routing authenticity, resource exhaustion, supply-chain authenticity and downstream evidence publication/error atomicity. The six required lenses do not establish those properties.

---

## Lens 1 - Commitment coverage

| Commitment | Attacker DoFs | Bound by | Gap |
|---|---|---|---|
| OMP lineup SHA-256 exported as `lineup_hash` | Configured member ordering, selected route, model identity, effort, persona identifier, strategy and family floor | `O/panel/config.ts:367-382` hashes strategy, floor and ordered member index/selector/modelId/family/thinking/persona. `O/panel/runtime.ts:231-243` computes it after resolution and family validation; `F/tools/panel-resolver.ts:124` forwards it. | No omission identified within the lineup-identity contract. |
| Boundary between lineup identity and complete FV run identity | Role label, mode, synthesizer, timeout, calibration text, unused candidates, reader implementation and provider's eventual serving choice | These are not all covered by `panelLineupHash`; the returned roster carries several separately at `F/tools/panel-resolver.ts:119-126`. | The lineup hash is insufficient as a complete run, tool-provenance or served-route attestation. This repair does not claim otherwise. D I11 and TA-08 remain separate obligations. |
| Signatures, ReportData and persistent evidence commitments in the three primary paths | None | The resolver returns roster JSON at `F/tools/panel-resolver.ts:128-131`; the other paths export APIs or construct test fixtures. | No such commitment surface exists in this slice. No Dossier cryptographic commitment was reviewed. |

## Lens 2 - Clause-to-line discharge

| Clause | Expected discharge | Actual code line | Status |
|---|---|---|---|
| `F/INSTALL.md:31-32`: registered reader | Obtain effective panel settings through OMP's registered handle | `F/tools/panel-resolver.ts:49-55`; existing handle at `O/panel/settings.ts:4-6` | discharged at the inspected call boundary |
| `F/INSTALL.md:33`: released legacy reader | Preserve `Settings.get("panel")` where the registered reader is unavailable | `F/tools/panel-resolver.ts:56-57` | discharged by retained branch; legacy execution is parent-reported |
| `F/INSTALL.md:34`: missing reader fails closed | Refuse before role resolution when neither reader exists | `F/tools/panel-resolver.ts:58-62` | discharged |
| Reader export requirement, `F/INSTALL.md:31-34` | Make the existing registered handle reachable through the injected public SDK | `O/panel/index.ts:38`, `O/index.ts:37-38`, `O/extensibility/custom-tools/loader.ts:143-154` | discharged by source trace; root-SDK lookup is parent-reported |
| OMP-owned effective settings and resolver, `F/.fv/changes/2026-09-14-omp-owned-panels.md:9,22` | Preserve OMP configuration precedence and delegate role/model selection | `F/tools/panel-resolver.ts:55-68`; `O/config/registry.ts:636-645`; `O/config/settings.ts:864-865,3935-3944` | discharged for settings selection; no parallel FV merge implementation introduced |
| OMP-owned family policy, same change record `:9,18` | Derive lineage through OMP and reject invalid independence/floor claims | `O/panel/config.ts:20-23,325-355`; `O/panel/runtime.ts:214-219,239` | discharged for configured/resolved identity; actual serving identity remains unexercised |
| `F/INSTALL.md:341-345`: R32 uses real OMP | Import actual implementation rather than fabricate panel resolution | `F/tests/r32_resolver_contract.py:22-34,40-53` | discharged for imports and Settings construction; registry availability/authentication remain test doubles at `:60` |
| D I11, `D/docs/intent.md:25`: provenance and evidence limits | Do not convert roster resolution or local fixture results into fresh producer evidence or runtime attestation | `F/tools/panel-resolver.ts:119-131` returns a roster only; `F/tests/r32_resolver_contract.py:60-64` returns fixture results | partial: this slice preserves the distinction; complete producer/tool provenance is outside its implementation |
| D I12, `D/docs/intent.md:32`: independent observations and fixed evidence scope | Do not treat repeated labels or fixture models as independent execution evidence | Family collision rejection at `O/panel/config.ts:342-355`; test assertion at `F/tests/r32_resolver_contract.py:179-181` | partial: resolves lineage policy only; no execution-independence claim discharged |
| D I13/I14, `D/docs/intent.md:33-34` | Keep activation, production behavior and authority unchanged | Primary production path performs setting reads, resolution, registry-file read and JSON return at `F/tools/panel-resolver.ts:37-131` | discharged within this repair's boundary; broader activation gates were not re-reviewed |
| Ledger TA-07/TA-08 and incomplete C-01 through C-15 | Keep local execution limits, operator honesty and missing composition links explicit | Resolver delegates to injected OMP APIs at `F/tools/panel-resolver.ts:38-40,64-78`; fixture registry is supplied at `F/tests/r32_resolver_contract.py:60` | partial: trusted dependency boundary remains; no external assumption or composition candidate is discharged |

## Lens 3 - Deferred cannot silently succeed

| Branch | Reachable from | Behavior | Status |
|---|---|---|---|
| Missing parser, role resolver or lineup resolver | Tool execution | Throws before reading configuration, `F/tools/panel-resolver.ts:38-45` | explicit refusal |
| Missing session settings | Tool execution | Throws at `F/tools/panel-resolver.ts:47` | explicit refusal |
| Neither supported setting reader exists | Tool execution | Throws at `F/tools/panel-resolver.ts:58-59` | explicit refusal |
| Registered reader throws, or returns malformed panel content | Preferred-reader path | No catch substitutes the legacy reader; parsing follows directly at `F/tools/panel-resolver.ts:55-61` | no silent fallback identified |
| Unknown role, unavailable model, unknown/duplicate lineage or unmet floor | Delegated OMP resolution | Rejects at `O/panel/config.ts:280-289,325-355` and `O/panel/runtime.ts:186-201` | explicit refusal |
| Missing synthesizer or invalid timeout | Tool execution | Throws at `F/tools/panel-resolver.ts:112-116` | explicit refusal |
| Missing Bun or OMP source for R32 | Test runner | Returns 2, with no substitute resolver, `F/tests/r32_resolver_contract.py:114-123` | explicit incomplete execution |
| Production TODO/stub/mock/deferred implementation | Three primary paths and registered-setting declaration | Targeted search found none. The fixture registry at `F/tests/r32_resolver_contract.py:44-60` is test-only. | Empty deferred-success finding set for this slice |

## Lens 4 - Who controls

The production repair adds no persisted state. This table covers the existing stored configuration and registry values it consumes.

| Field | Supplier | Validation | Gap |
|---|---|---|---|
| `panel.roles`, `panel.personas`, `panel.defaultRole` | OMP global/project/config-overlay/runtime settings suppliers | Registered record read at `O/panel/settings.ts:6`; structural parsing at `O/panel/config.ts:229-273`; own-key role lookup at `:280-289` | No new validation bypass identified. FV parses either reader's result at `F/tools/panel-resolver.ts:61`. |
| Role strategy, members and `minFamilies` | Configuration author | Member parsing at `O/panel/config.ts:103-146`; role parsing at `:148-192`; resolved-family checks at `:325-355` | No new gap identified. Provider count is not used as lineage count. |
| Candidate model, fallbacks and effort | Configuration author; actual selection through OMP model registry | `O/panel/runtime.ts:174-219` resolves candidates, checks configured authentication and validates effort | Registry/provider authenticity remains trusted. This is not served-route attestation. |
| Registry voice ID, selector, effort and calibration text | FV package maintainer | Exact requested selector and effort must match before calibration is copied, `F/tools/panel-resolver.ts:81-109` | Package contents remain a trust input. Fallback and changed-effort routes receive `pending`; no new unconditional calibration promotion found. |
| `role`, `mode`, synthesizer and seat timeout | Tool caller | Zod shape at `F/tools/panel-resolver.ts:30-35`; OMP resolution at `:62-78`; finite positive timeout at `:114-116` | No new gap identified within the reader repair. |
| Fixture model IDs/providers and authentication result | Test author | Models contain classifier inputs at `F/tests/r32_resolver_contract.py:44-51`; real OMP classifier supplies lineage | Fixture authentication is deliberately always true at `:60`. It cannot support credential or live-provider claims. |

## Lens 5 - Field-name fidelity

| Field | Implied semantic | Actual value | Status |
|---|---|---|---|
| Public `cfgPanel` export | Existing registered panel-setting handle | `O/panel/index.ts:38` re-exports `O/panel/settings.ts:6` | faithful; no second registration or alternate default introduced |
| `role`, `mode` | Selected role and requested FV operation mode | `role.roleId`, `params.mode`, `F/tools/panel-resolver.ts:120-121` | faithful |
| `seat_id` | FV seat identifier | Explicit synthesizer ID, matching voice ID or ordinal fallback, `F/tools/panel-resolver.ts:97,125-126` | faithful; not a provider identity |
| `requested_selector` | Candidate submitted to OMP that actually resolved | `member.requestedSelector`, `F/tools/panel-resolver.ts:105`; selected candidate recorded at `O/panel/runtime.ts:179-183` | faithful to OMP semantics; may be a selected fallback rather than the initial preference |
| `resolved_provider`, `resolved_model` | Resolved transport provider and qualified route selector | Provider prefix and complete `member.selector`, `F/tools/panel-resolver.ts:94,106-107`; formatter at `O/config/model-resolver.ts:180-185,208-211` | faithful to resolution-time identity; no actual-serving claim |
| `declared_family`, `resolved_family` | OMP's lineage label used for quorum | Both use `member.family`, `F/tools/panel-resolver.ts:104,108`; OMP derives the classifier's `class` at `O/panel/config.ts:20-23` | faithful to the FV/OMP contract; these are broad lineage classes, not transport providers or model revisions |
| `thinking_level`, `calibration` | Resolved effort and applicable retained calibration | `member.thinking` or empty string; exact selector/effort calibration guard, `F/tools/panel-resolver.ts:100-109` | no new semantic drift identified; empty effort is not a measured effective effort |
| `min_families`, `seat_timeout_seconds` | Requested/default floor and configured positive timeout | Role floor or 2, validated timeout, `F/tools/panel-resolver.ts:114-123` | unchanged; neither field claims observed completed-family count or elapsed duration |
| `lineup_hash`, `seats`, `synthesizer` | Resolved panel identity and roster entries | OMP hash plus mapped lineup and separately resolved synthesizer, `F/tools/panel-resolver.ts:124-126` | faithful within the hash scope stated in Lens 1 |
| Tool `content` and `details` | Text and structured representations of the same roster | `JSON.stringify(roster)` and `roster`, `F/tools/panel-resolver.ts:128-131` | consistent at construction |

## Lens 6 - Deferral justification audit

| Deferred finding | Justification claims | Claim audit | Verdict |
|---|---|---|---|
| No reader-specific prior deferred finding located | Searches of D's audit/current evidence-performance reviews and F's FV records found no prior `cfgPanel`/reader deferral | Relevant F history describes ownership and calibration boundaries; it does not waive missing-reader failure or authorize synthetic family metadata | Empty reader-specific wrong-deferral finding set |
| Prior OMP-owned-panel cutover, `F/.fv/changes/2026-09-14-omp-owned-panels.md:9,18,22` | OMP owns effective configuration, model selection, family policy and hashing; unavailable capabilities refuse | Delegation remains at `F/tools/panel-resolver.ts:55-78`; parser/family/hash enforcement remains in OMP | Source supports the stated ownership boundary. Historical omission of adversarial review is not treated as evidence. |
| Calibration limits, `F/.fv/changes/2026-09-15-panel-roster-update.md:20-22,44` | Successor routes are pending; historical calibration does not attest a new route | Exact selector/effort guard remains at `F/tools/panel-resolver.ts:100-103`; fallback-pending assertion remains at `F/tests/r32_resolver_contract.py:166-171` | No wrong-deferral identified. No current serving-route attestation was exercised. |
| D ledger TA-07/TA-08 and incomplete composition | Local fixtures and mutually consistent local records do not prove environment portability, operator honesty or composition | This resolver emits roster data only; R32 uses controlled model availability/authentication at `F/tests/r32_resolver_contract.py:60` | Limitations remain applicable. This repair closes none of those external prerequisites. |

## Supplemental boundary checks

| Check | Evidence | Assessment |
|---|---|---|
| Reader preference when both APIs exist | `F/tools/panel-resolver.ts:49-57` | A callable registered handle wins. The legacy branch is reached only when that handle is unavailable or unusable. |
| Failure precedence | `F/tools/panel-resolver.ts:55-61` | A failing preferred reader or failing parse does not silently select another configuration source. |
| Effective configuration precedence | `O/config/registry.ts:260-278,636-645`; `O/config/settings.ts:864-865,3935-3944` | The handle reads the supplied session's merged settings, preserving global < project < config overlay < runtime ordering and child overlay behavior. No global singleton or direct configuration-file read was added. |
| Public API reachability | `O/panel/index.ts:38`; `O/index.ts:38`; `O/extensibility/custom-tools/loader.ts:143-154` | The existing handle reaches the public root namespace injected into custom tools. Its declaration was already imported by the panel runtime at `O/panel/runtime.ts:36`. |
| Provider versus family | `O/panel/config.ts:20-23,342-355`; `F/tests/r32_resolver_contract.py:87-91,179-181` | `openai/gpt-5` and `openai-codex/gpt-5` must collide as one lineage despite distinct providers. The fixture no longer supplies an identity metadata answer. |
| Released-reader compatibility | `F/tools/panel-resolver.ts:56-57`; `F/INSTALL.md:31-34` | Legacy call shape remains intact. Parent reports its smoke succeeded; this review did not execute an older OMP installation. |
| Durable regression coverage | `F/tests/r32_resolver_contract.py:38-64,187-189` | R32 exercises the real current reader and missing panel API. It does not independently encode both-reader precedence, legacy-only reading, or missing-reader-with-resolver-APIs-present. Parent reports separate smokes for these paths. This is a retention recommendation, not an established implementation violation. |

---

## Finding list (consolidated)

| ID | Lens | Severity | Surface | Intent ref | Code ref | Summary | Fix |
|---|---|---|---|---|---|---|---|
| None | All six | N/A | Scoped FV/OMP compatibility boundary | References above | References above | No evidence-backed defect identified in the inspected repair. | No corrective patch prescribed by this review. |

## Summary

- Total findings: 0
- By severity: Critical=0 Major=0 Minor=0 Informational=0
- By lens: commitment-coverage=0 clause-to-line=0 deferred-cannot-silently-succeed=0 who-controls=0 field-name=0 deferral-justification=0
- Recommended next step: retain the parent's reported verification artifacts against both supplied commits. Preserve the legacy-only, both-reader-preference and missing-reader smokes as durable regression cases, including preferred-reader failure without fallback. Keep runtime serving identity, multi-family independence, fresh Dossier evidence collection and activation qualification as separate unexercised obligations.