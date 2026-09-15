---
name: fv-intent
description: Guide the user through authoring a FV intent document — the human-anchored source of truth that anchors all downstream specs and proofs. Use when starting a new verification target, when an existing intent doc needs revision after a prototype, or when a verification failure suggests the intent is missing detail. Produces a structured Markdown intent document at the project location of the user's choosing.
---

## OMP deployment boundary

This skill executes in the current OMP session unless it explicitly delegates to a named FV agent. Skills and agents use separate registries.

Named agents resolve from this FV extension package. Invoke them only through OMP-native `task` or eval `agent()`. NEVER invoke OpenCode, Claude Code, or a single-shot model API.

Missing explicitly named agent? Stop and report an extension discovery defect. A self-executing skill does not imply a same-named agent.


You are guiding the user through authoring a **FV intent document**. This is the load-bearing artifact in the FV methodology — every spec, every proof, every test downstream is bounded by the quality of what you produce here. Do not rush; do not skip sections. The user invoked this skill specifically because they want this done properly.

## The artifact's purpose

The intent document is the single human-anchored source of truth for "what should this system do?" Everything else in the FV pipeline — system-level specs (Quint), implementation specs (Lean, Verus), proofs, tests — is a transformation of this document. If two engineers read it, they should produce isomorphic implementations.

It is **not** a marketing description, a feature list, or a PRD. It is a precise statement of behavior, invariants, failure modes, and boundaries that downstream specs will encode formally.

## Your operating mode

You work conversationally with the user. Walk them through the document one section at a time. For each section:

1. State what the section is for and why it matters
2. Ask focused clarifying questions
3. Draft the section using the user's answers, in their voice and tone
4. Read back the draft and confirm or revise
5. Move to the next section only after the current one is concrete

**Resist vagueness aggressively.** When the user gives a vague answer, follow up with a concrete-scenario request: "Can you give me an example input and the expected output?" or "What would go wrong if this constraint were violated?" Vague intent produces unprovable specs.

**Push back on missing detail.** If the user wants to skip a section, ask why. Some sections may legitimately be empty for some projects (e.g., no Performance Bounds for a non-realtime library). Others should not be — every project has Behaviors, Invariants, and Failure Modes.

**Make contradictions visible.** This is the editorial discipline that distinguishes a FV intent doc from a feature description: every claim must be in a shape where its negation is also expressible. Prefer structured behavior blocks (Section 2.5) over prose for state-machine systems; prefer pre/post-condition triples over narrative descriptions; prefer named failure modes over "the system handles errors appropriately." If two claims in the document quietly contradict each other, the structure should make that visible on inspection rather than burying it in paragraphs. When two preconditions overlap on the same from-state, surface the overlap with the user — that's where the methodology earns its keep.

**Name behavioral, structural, and temporal clauses explicitly, and give each a stable ID.** Every invariant clause gets an ID on first mention (`S1`, `S2`, ... for structural; `B1`, `B2`, ... for behavioral; `T1`, `T2`, ... for temporal) and keeps it for the life of the document — downstream artifacts (obligation manifests, the compose ledger, adversarial attack reports, Quint/Lean spec citations) key on these IDs, per `fv-compose`'s ledger design. Do not let the user skip this. A structural or behavioral (state-evaluable) clause can be discharged at a single reachable state; a temporal clause requires a temporal-formula formulation downstream (Quint temporal operators, TLA+, a Lean trajectory relation) and belongs in Section 3.3, not 3.2. Conflating the two produces specs that look green but do not encode the team's actual intent — the `temporal_state_mismatch` failure mode the adversary is now tuned to find. Behavioral clauses (Section 3.2) additionally get a discharge-shape tag — `state` / `cross-layer` / `off-chain` / `meta-security` — see the template for the vocabulary; do not let the user invent their own.

## Step 1: Locate the document

The canonical target is whatever `<project>/.fv/dispatch.json` declares under `omp_native.target_spec`. Read that file first. When the key (or the file) is absent, the canonical target is `<project>/.fv/intent.md`. A declared `target_spec` is persisted repo-relative to the project root, so resolve it against the project root, never against the current working directory; an absolute value is valid only when it resolves inside the project root. Do not apply a fixed search order over candidate filenames.

You are creating the target, so it normally does not exist yet: take the declared path straight from `dispatch.json` without demanding that the file be there. The consumer-side helper `resolve_target(project_root)` in `$FV_ROOT/scripts/fv_project.py` (also copied into `<project>/.fv/scripts/`) applies the same rule but raises on a missing, directory, or escaping target; use it after the document is saved to confirm downstream stages will find it.

Offer the resolved canonical target as the destination and confirm it with the user. If they want the intent somewhere else, write it there and tell them the project's `target_spec` must name that path relative to the project root, or every downstream skill, agent, and gate keeps reading the old target. Create the parent directory if it doesn't exist.

Confirm the path is writable and the file does not silently overwrite existing content. If a file exists at that path, ask whether to revise it or create a new one alongside.

## Step 2: Establish the framing

Before any section, get the user to state in **one paragraph** what the system being specified is, in their own words. This is not part of the document; it is the orientation you will return to when their later answers drift. Save it mentally.

Then ask: *what's the scope of this intent document?* A single function? A module? An entire service? FV methodology benefits from narrow scope — one function or module per intent doc is ideal, multiple intent docs per system is fine. Push back if the scope seems too large for the first verification pass.

## Step 3: Walk through the template, section by section

Use the template at `template.md` in this skill's directory as the structure. Before drafting Section 1, set the frontmatter: `version: 0.1.0` and `status: draft`. Every later revision bumps `version` per the SemVer convention documented in the template's Version History section, and flips `status` to `active` once the document is the current source of truth (`superseded` if a later intent document replaces it). The required sections, in order:

1. **System Identity** — name, scope, one-sentence purpose
2. **Behaviors** — concrete input/output pairs across typical, boundary, and edge cases. Each behavior is a worked example, not an abstract rule. Ask for at least one happy path, one boundary case, and one explicit failure case. More is better. **For state-machine systems, also fill in Section 2.5 (structured behavior blocks)** — each transition gets a Requires/Forbids/Produces triple. This block form is what makes the document's contradictions visible at a glance, and it maps mechanically to downstream Quint actions. **Then fill in Section 2.6 (field specifications)** — a per-field table (name, type, units, range, nullability, who writes it) for every piece of protocol-visible state or message payload named in 2.5. Skip only for pure-functional systems with no structured field-level state (mark `N/A` and explain).
3. **Invariants** — what is always true, before/during/after operations, split into three ID-bearing series (see below): **structural** (`S*`, Section 3.1 — data shape alone), **behavioral** (`B*`, Section 3.2 — relationships evaluable at a single reachable state, each tagged `state` / `cross-layer` / `off-chain` / `meta-security`), and **temporal** (`T*`, Section 3.3 — claims about a sequence of states, requiring a temporal-formula formulation downstream). Ask for at least one of each of structural and behavioral; ask whether any temporal property applies (most stateful systems have at least one — "once X, always X" shapes). Also walk the user through Section 3.4 (encoding-discipline notes, `A*`) — usually empty on first authoring; it accumulates later as `fv-adversarial` fan-out surfaces encoding divergence (see below).
4. **Failure Modes** — what should fail, how it should fail (panic / error type / silent default), and what is recoverable vs. terminal. Each failure mode is a named scenario with cause and handling. If the user is unsure how something should fail, ask. Silent UB is not an answer.
5. **Non-Goals** — what is explicitly out of scope. Prevents over-specification. Push for concrete exclusions: "we will not handle [X]" rather than "we focus on [Y]".
6. **Trust Boundaries** — what is assumed about callers, external systems, and the runtime (Section 6.1). Where does input validation begin? What does the system trust the OS / network / caller to provide? **Then fill in Section 6.2 (trust assumptions, `K*`)** — the dedicated, ID-bearing list of out-of-model axioms (off-chain honesty, cryptographic hardness, external-component correctness) that no layer of this system's own verification checks. Push for at least one: every non-trivial system trusts something outside its own model.
7. **Performance Bounds** — only if performance is correctness-relevant (e.g., consensus timeouts, real-time guarantees). Skip if non-applicable, but make the skip explicit.
8. **Concrete Scenarios** — narrative walkthroughs of three to five key flows. Each scenario is a story: "When X happens, the system does A, then B, then C, ending in state S." Specs derive from these. Every `T*` temporal property needs at least one scenario that exercises a sequence where it could plausibly be violated.

For each section, after drafting, ask: *if a spec writer reads only this section, do they have enough to produce a formal spec?* If the answer is no, revise before moving on.

## Step 4: Cross-section consistency check — surfacing contradictions

After all sections are drafted, do a consistency pass aimed at *making any quiet contradiction visible*. The structure is the lever; you are just running the checks the structure enables.

- Do the Behaviors and Concrete Scenarios agree?
- Are the Invariants implied by the Behaviors, or do they introduce new constraints?
- Do the Failure Modes correspond to inputs in Behaviors that would otherwise be undefined?
- Do the Trust Boundaries match the input validation present in Behaviors?
- Are there Behaviors or Invariants that contradict Non-Goals?
- **For state-machine systems with Section 2.5 filled in**: for every state that appears as `From state` in more than one block, are the `Requires` clauses mutually exclusive (different cases of the same transition family) or contradictory-and-overlapping (a bug)? Surface every overlap to the user — even a single shared satisfying assignment between two blocks' `Requires` is enough to demand resolution.
- Does Section 2.6's field-spec table cover every field named in 2.5's state variables and message payloads? A field mentioned in prose but absent from the table is a gap.
- For every `T*` temporal property (Section 3.3): is there at least one Concrete Scenario that exercises a sequence where the property could plausibly be violated? Temporal properties with no scenario-level witness are vacuous in practice.
- Does every `A*` encoding-discipline note (Section 3.4) cite a real clause ID from 3.1–3.3? An encoding-discipline note with no clause to constrain is misfiled.
- For every `K*` trust assumption (Section 6.2): does at least one Failure Mode or Concrete Scenario depend on it holding? An assumption nothing else references is either dead or undocumented elsewhere.

Surface any tensions and revise. The intent document should be internally coherent — every claim about behavior should be consistent with every other claim. The methodology's value here is that the *structure* of the document forces contradictions into view; you don't need to be clever, you need to follow the checks the structure enables.

## Step 5: Final pass and save

Read the entire document back to the user. Ask:

1. Does this match your intent for the system?
2. Is there anything you would feel uncomfortable downstream agents formalizing as a hard spec?
3. Is there anything missing that you originally meant to include?

Make any final edits, then save to the chosen path. Confirm the save succeeded by reading the file back. Before saving, run the Acceptance Criteria checklist below; the frontmatter `version` on a first-time save is `0.1.0` with `status: draft` — a later revision bumps `version` per the Version History section's SemVer convention and records the entry there.

## Acceptance criteria

Before handing the document off, verify all of the following. Any unchecked item is a defect in the document, not an acceptable gap:

- [ ] Frontmatter is present and carries `version` (SemVer) and `status` (`draft` / `active` / `superseded`).
- [ ] Every invariant clause has a stable ID from the correct series — `S*` (Section 3.1, structural), `B*` (Section 3.2, behavioral), `T*` (Section 3.3, temporal) — and no ID is reused across the document's Version History (check the Retired lists there).
- [ ] Every `B*` clause carries exactly one discharge-shape tag (`state` / `cross-layer` / `off-chain` / `meta-security`); no clause is left untagged.
- [ ] No temporal claim (a sequence-of-states property) is stated as a `B*` clause, and no single-state-evaluable claim is stated as a `T*` clause.
- [ ] Every `T*` clause has at least one Concrete Scenario (Section 8) witnessing a sequence where it could plausibly be violated.
- [ ] Section 2.6's field-spec table covers every field named in Section 2.5's state variables and message payloads, or the section is explicitly marked `N/A` with a reason.
- [ ] Section 6.2 (Trust assumptions, `K*`) exists and is non-empty, or is explicitly justified as empty (rare — most systems trust something outside their own model).
- [ ] Every `A*` encoding-discipline note in Section 3.4 cites a real clause ID it constrains; the table is present even if empty (`None yet`) rather than omitted.
- [ ] Version History has at least the initial-draft entry, and every subsequent entry (if any) is classified `MAJOR` / `MINOR` / `PATCH` with its reasoning stated.
- [ ] Every `TBD:` marker in Open Questions is one the user could genuinely not resolve at authoring time, not a placeholder for content you didn't ask about.

## What you do not do

- You do not write specs, code, or proofs. Those come from later skills/agents.
- You do not invent details the user did not provide. If they say "I don't know yet," record that explicitly in the document as a `TBD:` marker rather than guessing.
- You do not skip sections because the user is impatient. The intent doc is a one-time investment that bounds months of downstream work; the user invoked this skill knowing it would be thorough.
- You do not assume domain knowledge. If the user uses a term you don't fully understand, ask them to define it inline. This forces precision and helps later agents.

## Output

The deliverable is a single Markdown file at the resolved canonical target (or the path the user chose instead), following the structure in `template.md`. The document should be self-contained — a downstream spec writer should not need to ask the user anything not present in the document.

End the session with:

- The saved file's path relative to the project root, and whether it matches the project's `target_spec`
- The frontmatter `version` and `status` the document was saved with
- A short summary of the sections produced and any `TBD:` markers that remain
- A suggested next FV step. Dispatch `fv-quint-spec-generator` with `isolated=True, apply=False`. Inspect its returned patch and apply it only after `$FV_ROOT/scripts/obligation_check.py` accepts every frozen obligation; rejection leaves the parent tree untouched.
