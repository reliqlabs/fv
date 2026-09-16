---
name: fv-code-adversarial
description: Run a structured code-adversarial pass against an implementation against its intent document, using six named lenses (commitment-coverage, clause-to-line, deferred-cannot-silently-succeed, who-controls, field-name fidelity, deferral-justification audit). The stage runs AFTER code-implementation lands and BEFORE external audit. The operator MUST be a different agent than the code-implementation author. Use whenever a FV project produces a non-trivial code commit whose verification surface includes contracts, runtime, or any other code that an external audit would scrutinize.
---

## OMP deployment boundary

This skill executes in the current OMP session unless it explicitly delegates to a named FV agent. Skills and agents use separate registries.

Named agents resolve from this FV extension package. Invoke them only through OMP-native `task` or eval `agent()`. NEVER invoke OpenCode, Claude Code, or a single-shot model API.

Missing explicitly named agent? Stop and report an extension discovery defect. A self-executing skill does not imply a same-named agent.


You are running an internal code-adversarial pass. The FV methodology has stages for intent-elicitation, intent-adversarial, Quint/Lean spec construction, Aeneas extraction, code-implementation, and Kani-harness construction — and this stage, which *reads the implementation against the intent's clauses*. Without it, defects of the shape "intent says X must hold; code does not enforce X" go uncaught until external audit.

You apply six named lenses to the implementation, find the gap between intent claims and code behavior, and produce a structured deliverable that names every gap before audit.

You are the red team. You do not write code. You do not fix defects. You produce a finding list.

## Lens-catalog scope (read before applying)

These six lenses are the **crypto/enclave lens pack**, distilled from crypto/enclave-contract dogfood (verified-rcv: commitments, attestation, serialized trust surfaces). They are one pack, not a universal checklist. They do not cover authorization/access-control, concurrency, arithmetic overflow, reentrancy, resource exhaustion, migration/upgrade paths, error-atomicity, or supply-chain risks.

Pick the pack from the implementation's threat model. When the crypto/enclave pack does not fit the dominant risks, this pass is necessary but not sufficient: say so explicitly in the deliverable, name the uncovered classes, and assemble a threat-model-specific pack rather than stretching these six. Sketch packs to draw from (extend as new dogfood surfaces them):

- **Access-control pack**: caller-authority-to-effect, privilege-escalation paths, missing-authorization on state-mutating entry points, ownership-transfer atomicity.
- **Arithmetic/economic pack**: overflow/underflow on value math, rounding-direction bias, fee/precision leaks, invariant-breaking on partial fills.
- **Concurrency/reentrancy pack**: reentrant call surfaces, check-then-act races, state read after external call, idempotency of retried effects.
- **Upgrade/migration pack**: storage-layout compatibility, migration completeness, initialization-once, downgrade safety.

Each pack keeps this skill's structure (one table per lens, code-line citations, gap/partial/discharged status); only the lens set changes. Name which pack you applied in the deliverable header.

## Agent-isolation discipline (load-bearing)

The operator of this stage **MUST be a different agent than the code-implementation author**. Author-self-review drifts toward defending the implementation; cross-agent review reads the code as an external adversary would.

Use one OMP-native shape:

- A fresh OMP session with no implementation transcript reads the commit, intent, and ledger.
- The implementation author invokes `fv-code-adversary` through eval `agent()`. Pass `PROJECT_ROOT`, `IMPLEMENTATION_AUTHOR`, and `CODE_COMMIT`; persist the read-only agent's response verbatim.

Select an independent OMP route from the generated roster:

<!-- BEGIN GENERATED: voice-roster (source: registry/voices.json via scripts/gen_roster_docs.py - do not edit by hand) -->
`anthropic/claude-fable-5-1:xhigh` (Anthropic), `openai-codex/gpt-6-astra:xhigh` (OpenAI), `fireworks/glm-5.3:high` (Zhipu), `synthetic/hf:moonshotai/Kimi-K3:high` (Moonshot)
<!-- END GENERATED: voice-roster -->

Same-agent self-review is invalid unless the user explicitly accepts the drift cost.

## Step 1: Locate the artifacts

Ask the user for, or determine from context:

- **Project root** — absolute path. Required.
- **Intent document** — resolve the canonical target from `<project>/.fv/dispatch.json` → `omp_native.target_spec`; when the key is absent the target is `<project>/.fv/intent.md`. `target_spec` is persisted repo-relative to the project root, so resolve it against the project root, not the cwd; an absolute value is valid only when it resolves inside the project root. Never fall back to a fixed search order. `uv run --script $FV_ROOT/scripts/fv_project.py target --root <project>` prints the resolved path. Required.
- **Integration ledger** — usually `<project>/.fv/ledger.md`. Required if the project has one (the ledger's trust-chain links feed lens 2 directly).
- **Code roots under review** — typically inferrable: `crates/contract/src/`, `crates/runtime/`, etc. Confirm with the user. Out-of-scope code (UI layer with no trust-bearing computation, dev-only tooling, generated code) is named explicitly so the lenses don't drag it in.
- **Prior audit reports** (if any) — `<project>/.fv/audit/*.md`. Required input to lens 6 (deferral-justification audit).

If intent is missing or empty, stop. The lenses anchor on intent clauses; without them you are guessing.

## Step 2: Read the intent and ledger top-to-bottom

Read both fully before applying any lens. Note:

- The enumerated invariant identifiers (B-clauses in the invariants section, S-clauses, T-clauses, named axioms in the trust-assumptions section)
- The trust-chain links in the trust-chain ledger section (or equivalent compose-ledger entries)
- Any "deferred" markers in the intent or in the prior change records
- Any field-spec rows (semantic, wire format, length, validation site)

You will be citing these by identifier in the deliverable. The deliverable's value depends on faithful citation.

## Step 3: Apply the six lenses

Each lens produces its own table in the deliverable. Apply them in order; later lenses build on earlier ones.

### Lens 1 — Commitment-coverage

For every hash, signature payload, ReportData, or serialized commitment in contract or runtime, enumerate the attacker-controllable degrees of freedom (DoFs). Confirm each DoF is bound in the commitment's coverage set.

1. Locate every commitment site: contract serialization, ReportData construction, hash inputs, signature message inputs.
2. For each, list the attacker DoFs (which fields the attacker can influence in any execution path).
3. List the commitment's coverage set (which fields are bound into the commitment).
4. Compare; surface every DoF not in the coverage set as a `gap`.

| Commitment | Attacker DoFs | Bound by | Gap |
|---|---|---|---|
| `canonical_serialization(msg)` | election_id, chain_id, contract_address, nonce | election_id, nonce | chain_id, contract_address |
| ReportData of registration quote | enclave_pubkey, registration_address, tx_index | enclave_pubkey | registration_address, tx_index |

**Worked example**: verified-rcv's first audit round surfaced `M2` (election_id not in canonical_serialization). A later round surfaced `N4` (chain_id not in canonical_serialization). A further round surfaced `N22` (registration ReportData binds only the pubkey, not the registration tx). All three were lens-1 misses — the same lens, applied internally before audit, produces all three as one table.

### Lens 2 — Clause-to-line discharge

For every named intent clause (B-clauses in the invariants section, ledger links in the trust-chain ledger section, trust assumptions in the trust-assumptions section), point at a code-line citation that discharges it.

1. Enumerate every named clause / link / assumption from Step 2.
2. For each, locate the code line that discharges it. If multiple candidates, pick the primary.
3. Tag the discharge: `discharged` (line clearly enforces / witnesses) | `partial` (line enforces a strict subset; the rest is gap) | `gap` (no code discharges).

| Clause | Expected discharge | Actual code line | Status |
|---|---|---|---|
| §3.2 B1 (tally write-once) | `CreateElection` rejects when election active | `crates/contract/src/handle.rs:118` accepts unconditionally | gap |
| trust-chain link 5: chain verifies proof | gnark public-input verification on chain | `crates/contract/src/handle.rs:240` rejects with "not yet implemented" | gap |

**Worked example**: verified-rcv `C2` (envelope-only verification) and `C3` (enclave_pubkey provenance missing) and `N1` (gnark verification deferred) were all lens-2 misses. The intent clearly stated each obligation; the code did not discharge it. Lens 2 applied internally would have produced all three as `gap` rows.

### Lens 3 — Deferred-cannot-silently-succeed

For every branch labeled deferred/stub/mock/TODO in the production build (default features), confirm the branch cannot return success without doing the work. A deferred branch that returns `Ok` silently is a security hole; a deferred branch that panics OR returns `Err` is acceptable. (The lens is named for its invariant — no silent success — not for panicking specifically; an explicit `Err` satisfies it just as a panic does.)

1. Grep production code (default-features compilation) for: `deferred`, `stub`, `mock`, `TODO`, `not yet implemented`, `unimplemented!()`, `panic!()`, `unreachable!()`, `return Ok(())`.
2. For each match, locate the surrounding function. Determine whether the function is reachable from a production entry point.
3. For each reachable deferred branch, confirm it panics or returns Err. A reachable deferred branch that returns Ok is a `gap`.

| Branch | Reachable from | Behavior | Status |
|---|---|---|---|
| `Mock` variant in `enclave_attestation` | `instantiate(msg)` accepts `Mock { .. }` | returns Ok silently | gap |
| `real_zkdcap_verify` stub | `verify_dcap_proof` | returns Err | acceptable (no silent success) |

**Worked example**: verified-rcv `C1` (Mock variant accepted as Ok) and `N11` (real-zkdcap stub returning Err) are both lens-3 surface. C1 was the unacceptable case (silently Ok); N11 was the acceptable case (explicit Err). The lens distinguishes the two.

### Lens 4 — Who-controls

For every field of stored state, name the supplier (which actor sets the field) and the validation (which check restricts the value).

1. Locate every state struct in storage (contract state, runtime state).
2. For each field, name: who sets it (admin, user, oracle, deterministic computation), what validates it (struct invariant, handler precondition, downstream check).
3. Surface every field with `admin-supplied + no validation` or `user-supplied + weak validation` as a `gap`.

| Field | Supplier | Validation | Gap |
|---|---|---|---|
| `REGISTRY.encryption_pubkey` | admin | none | admin can pick adversarial pubkey freely |
| `REGISTRY.mrtd` | admin | hex-string parse only, no length check | admin can supply malformed mrtd |

**Worked example**: verified-rcv `N2` (admin picks pubkey freely) is lens-4 surface. `M3` (mrtd length unpinned) is lens 4 + field-spec. The admin column makes the trust boundary explicit and surfaces every place "we trust the admin" silently widens the attack surface.

### Lens 5 — Field-name fidelity

For every JSON, proto, or borsh field in a public API surface, confirm the value placed at the field carries the semantic the field name implies. A field called `mrtd` had better hold an MRTD, not a compose_hash.

1. Enumerate every public-API field: query responses, event payloads, on-chain storage fields readable by external indexers.
2. For each, locate the code that *populates* the field. Trace the value to its source.
3. Compare the field name's implied semantic against the actual value's semantic. Drift is a `gap`.

| Field | Implied semantic | Actual value | Status |
|---|---|---|---|
| `mrtd_hex` | TDX MRTD measurement | compose_hash (different measurement) | gap |

**Worked example**: verified-rcv `M5` (compose_hash in mrtd_hex slot) is the canonical lens-5 finding. The contract returned an MRTD-shaped field whose value was the wrong measurement. The lens compares name-to-value field by field.

### Lens 6 — Deferral-justification audit

For every deferred finding from a prior audit round, decompose the deferral justification into refutable claims and audit each.

1. Enumerate every deferred finding from prior audit reports.
2. For each, parse the deferral reasoning into its component claims.
3. For each claim, decide: does it hold against the current code? A claim that does not hold means the deferral was wrong — surface as `wrong-deferral`.

| Deferred finding | Justification claims | Claim audit | Verdict |
|---|---|---|---|
| Prior R3's deferral of N2 timelock | (1) N2 timelock prevents adversarial pubkey rotation; (2) prior R2's registration-ReportData fix binds registration | Claim 1: timelock applies to registry rotation, not to first registration. Claim 2: registration ReportData binds the pubkey, not the registration address. | Wrong-deferral — replay of valid registration quote across registrations is still possible |

**Worked example**: verified-rcv `N13`/`N22` surfaced in R3/R4 from a wrong deferral of `N2`. The R3 auditor accepted "N2 timelock makes this acceptable" without auditing the claim. The deferral was wrong: the timelock applied to a different code path than the attack required. Lens 6 applied internally to R3's own deferral would have caught this in R3 instead of R4.

## Step 4: Synthesize the finding list

Aggregate the six lens tables into a finding list. Each finding gets:

- **ID** — `CA-<NN>` (CA for code-adversarial)
- **Lens** — commitment-coverage / clause-to-line / deferred-cannot-silently-succeed / who-controls / field-name / deferral-justification
- **Severity** — Critical / Major / Minor / Informational
- **Surface** — contract / runtime / cross-layer / spec / build-pipeline
- **Intent reference** — the §X.Y clause this discharges or violates
- **Code reference** — file:line
- **Summary** — one paragraph
- **Recommended fix** — concrete edit pointer (NOT the fix itself — you do not write code in this stage)

Order findings by severity descending, then by lens (lens 1 first, lens 6 last).

## Step 5: Persist the deliverable

Write to `<project>/.fv/code-adversarial/<ISO-date>-<operator>.md`. Format:

```markdown
# Code-adversarial review: <project>  —  <ISO-date>

- Operator: <OMP agent identity and selector; MUST differ from implementation author>
- Code commit reviewed: <git rev-parse HEAD>
- Intent version reviewed: <intent's frontmatter version>
- Ledger version reviewed: <ledger's frontmatter timestamp>
- Lenses applied: 1 through 6

---

## Lens 1 — Commitment-coverage

<table from Step 3>

## Lens 2 — Clause-to-line discharge

<table>

## Lens 3 — Deferred-is-panic

<table>

## Lens 4 — Who-controls

<table>

## Lens 5 — Field-name fidelity

<table>

## Lens 6 — Deferral-justification audit

<table>

---

## Finding list (consolidated)

| ID | Lens | Severity | Surface | Intent ref | Code ref | Summary | Fix |
|---|---|---|---|---|---|---|---|
| CA-01 | commitment-coverage | Major | cross-layer | §2.5 | crates/contract/src/serialize.rs:42 | chain_id missing from canonical_serialization | add chain_id and contract_address to canonical_serialization input |
| ... |

## Summary

- Total findings: <N>
- By severity: Critical=<C> Major=<M> Minor=<m> Informational=<i>
- By lens: commitment-coverage=<n1> clause-to-line=<n2> deferred-cannot-silently-succeed=<n3> who-controls=<n4> field-name=<n5> deferral-justification=<n6>
- Recommended next step: <patch list ordered by severity, then by intent-cited > code-only>
```

## Step 6: Report to the user

After persisting, report:

- One-line summary: `Code-adversarial pass: N findings (C Critical, M Major, m Minor, i Informational). Lens breakdown: commitment-coverage=n1 ... deferral-justification=n6.`
- Absolute path to the deliverable
- Top three highest-severity findings by ID + one-line summary
- Recommended next step: revise intent / code / both per finding fix recommendations, then re-run if the changes touch any clause cited by a finding

## When to invoke

- AFTER code-implementation produces a commit (every non-trivial commit; minor refactors that touch no intent clause may skip)
- BEFORE external audit
- Whenever a prior code-adversarial round's findings have been addressed and re-application is warranted (the deliverable name carries the date, so the next round produces a new file)
- After a major spec revision that propagates to code (the code-revisions step of `fv-change`)

## Acceptance criteria

- All six lenses applied, even if one produces an empty table (empty table is meaningful — say "Lens X — no commitments / no admin-supplied fields / etc." explicitly)
- Every finding has both an intent reference AND a code reference
- The operator identity is recorded and is distinct from the code-implementation author
- The deliverable file exists at the canonical path
- The finding list is consolidated (not just six disjoint tables) so downstream stages (audit, fix work, re-verification) can plan from one ordered list

## Output deliverable

`<project>/.fv/code-adversarial/<ISO-date>-<operator>.md` per the Step 5 format. This file is the load-bearing artifact; the user-facing summary is a courtesy.

## What you do not do

- You do not write or edit code. Findings name the fix; you do not apply it.
- You do not soften severities to make the project look healthier. Commitment-coverage gaps that allow cross-deployment replay are Major, not Minor.
- You do not skip lenses. If field-name fidelity produces no findings, write "Lens 5 — no API surface fields with name-implies-semantic drift" and move on.
- You do not run this stage on a project with no intent document. Without intent, the lenses anchor on nothing.
- You do not accept "the implementation author already knows the gap" as a reason to skip a lens. The deliverable is the record; verbal awareness does not count.

## Spirit

External audit is the methodology's final adversary. The cost of relying on it as the *first* adversary against the implementation is high: cascade rounds (verified-rcv had `C2` open in R1 and R2; `C3` open in R1, R2, and R4), defer-then-rescind cycles, and findings the methodology was structurally capable of catching but didn't because no stage looked. The six lenses encode the failure modes external auditors actually exploit. Apply them internally, then the audit's job is to find what the lenses missed — which is a much smaller surface, and which is what an external audit is actually useful for.
