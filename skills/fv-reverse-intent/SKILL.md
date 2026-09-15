---
name: fv-reverse-intent
description: Reconstruct a FV intent document from an existing codebase via distillation. Reads source code, CLAUDE.md / AGENTS.md, README, commit history, and existing tests to draft an intent document for a system whose intent is implicit in code — then walks the user through revising and committing it. Use when bringing FV to an existing system (the common case); for new-system authoring use the elicitation-mode `fv-intent` skill instead.
---

## OMP deployment boundary

This skill executes in the current OMP session unless it explicitly delegates to a named FV agent. Skills and agents use separate registries.

Named agents resolve from this FV extension package. Invoke them only through OMP-native `task` or eval `agent()`. NEVER invoke OpenCode, Claude Code, or a single-shot model API.

Missing explicitly named agent? Stop and report an extension discovery defect. A self-executing skill does not imply a same-named agent.


You are reconstructing a **FV intent document** from a system that already exists in code. The two intent-authoring modes:

- **Elicitation** (`fv-intent`) — author intent forward, from human conversation, before the system is built
- **Distillation** (this skill) — extract intent backward, from an implementation that already runs

This is the distillation skill. The implementation predates the methodology; intent is implicit in code, comments, commit history, and reviewer memory.

## Why this skill exists

Most real verification work starts from a system that already runs. Intent is encoded in:

- the source itself (function signatures, error types, panics, validation)
- developer-facing docs (CLAUDE.md, AGENTS.md, README, architectural notes)
- the commit log (the *why* of past decisions)
- the test suite (the lived definition of "correct")
- reviewer judgment that has never been written down

Forcing elicitation-mode authoring on an existing system either (a) silently bypasses the intent step or (b) produces a fictional intent doc disconnected from how the system actually behaves. Neither anchors downstream verification. Distillation bridges the gap by reading what *is* and asking the team to commit to what *should be*.

## The artifact's purpose

Same as `fv-intent`: a precise, human-anchored statement of what the system should do, structured for downstream specs to encode formally. The difference is the *direction* of authoring: you read what is, then ask whether what is matches what should be. Discrepancies are the most valuable output — they surface places where the code embodies a default the team has never explicitly endorsed.

## Your operating mode

You work in two passes: **extraction** (read the artifacts, draft the intent) then **revision** (walk the user through the draft, surfacing tensions and asking them to commit to the *intended* behavior, not necessarily the *implemented* behavior).

The user invoked this skill expecting both passes. Do not skip the second — the value is in the revision, not in the extraction.

## Step 1: Locate the artifacts

Ask the user for, or determine from context:

- **Target scope** — which module, crate, or service is this intent for? Reverse-intent should be narrow; if the answer is "the whole monorepo," push back and pick a single coherent surface (one crate, one bounded subsystem).
- **Code root** — absolute path to the directory you should read.
- **Auxiliary docs** — paths to relevant CLAUDE.md, AGENTS.md, README, ARCHITECTURE.md, ADRs. Default: walk the code root and pick up anything matching those names.
- **Output location** — the canonical target declared by `<project>/.fv/dispatch.json` under `omp_native.target_spec`, where `<project>` is the FV project root containing the code root. When that key (or that file) is absent, the canonical target is `<project>/.fv/intent.md`. `target_spec` is persisted repo-relative to the project root: resolve it against the project root, not the current working directory, and accept an absolute value only when it resolves inside the project root. Do not apply a fixed search order over candidate filenames. Confirm before overwriting; if the user picks a different path, tell them the project's `target_spec` must be updated to that repo-relative path or downstream stages keep reading the old target.

If a document already exists at the resolved target, ask whether this is a refresh (read existing, fold in changes) or a starting-fresh authoring (rename or back up the existing file first). Do not silently overwrite a prior intent doc.

The same rule is implemented once in `$FV_ROOT/scripts/fv_project.py` as `resolve_target(project_root)` (copied into `<project>/.fv/scripts/` by the initializer). It raises on a missing, directory, or escaping target, so use it after saving to confirm downstream stages resolve the document you just wrote; do not reimplement the resolution.

## Step 2: Extraction pass

You produce a *draft* intent document from the artifacts alone, without yet talking to the user about behavior. Be honest: you are inferring intent from evidence, not channeling it.

Read systematically:

1. **Top-level docs first.** CLAUDE.md and README capture the framing the team has already written down. Use them as the spine.
2. **Public API surface.** Function signatures, error types, public types, trait bounds. The signature is a (partial) spec — note what types reject, what errors are returned, what postconditions are implied.
3. **Validation and error paths.** What does the code check on entry? What does it return when the check fails? Those are failure modes already present in the implementation.
4. **Invariants in struct construction.** Constructors, builders, `try_from`, smart-constructor patterns. Each is an implementation-side enforcement of an invariant; the intent doc should name it.
5. **Tests.** Existing tests define the *lived* definition of correct. Property tests are especially valuable — they encode invariants the team thought worth checking.
6. **Commit log.** `git log -p --follow` on the key files surfaces the *why* behind non-obvious decisions. Recent commits are most relevant; ancient history is usually noise.
7. **Comments named `// SAFETY:` / `// INVARIANT:` / `// NOTE:`.** Treat these as primary sources — they are intent the team paused to record.

Draft each intent section based on what the artifacts say:

- **System Identity** — name (crate name + module path), scope (what surface the intent covers), one-sentence purpose (extracted or inferred)
- **Behaviors** — for each public function, one happy-path and one error-path concrete example, lifted from tests where possible
- **Structured behavior blocks (Section 2.5)** — for state-machine systems, distil every observable transition. The implementation embodies a set of transitions whether the team has explicitly named them or not; surfacing each as a `From → Trigger → Requires → Produces → To` block makes them auditable. Source these by walking handler functions, state machines, and the `match` arms over enum states.
- **Invariants** — every constructor-enforced property, every `// INVARIANT:` comment, every property test predicate. Tag each behavioral invariant as `state` or `temporal` — the same discipline the elicitation skill enforces, applied retroactively. If the code embodies a temporal property encoded only as a state check, surface it as a `TENSION:` block in Step 3: that is the `temporal_state_mismatch` waiting to be acknowledged.
- **Failure Modes** — every error type, every panic, every `return Err(...)` path; classify recoverable vs. terminal
- **Non-Goals** — inferred from absence: things the code clearly does not do, often documented as "we don't handle X" in comments or README. **Mark every inferred non-goal `PROVISIONAL:`** — absence of code is evidence the team never got to something, not evidence they decided to exclude it. A provisional non-goal is not a committed claim until Step 3 confirms it with the user.
- **Trust Boundaries** — every `unsafe` block, every external call, every `&dyn Trait` boundary; what the code trusts the caller / runtime to provide
- **Performance Bounds** — only if surfaced by tests, benchmarks, or comments
- **Concrete Scenarios** — derived from integration tests if present; otherwise narrative walkthroughs of the most common code paths

Each section should annotate its provenance — every claim is tagged with `(from: <file>:<line>)` or `(inferred from: <evidence>)`. This makes the revision pass productive: the user can see *why* you said what you said, and accept, edit, or reject each item.

## Step 3: Revision pass — surface tensions

Walk the user through the draft, section by section. For each section:

1. Read the draft back, with provenance annotations visible
2. Ask: *is this what the system should do, or is this what the code currently does?* These are different questions; the answer matters.
3. For every inference where the answer is "the code does this but I'm not sure it should," mark it as a `TENSION:` block in the document. These are the highest-value findings — places where the code embodies a default the team has never explicitly endorsed.
4. For ambiguous behavior (e.g., the code panics on empty input but no test pins this down), ask the user whether the intended behavior is panic, error, or graceful default. Update the draft accordingly.
5. For Non-Goals: ask whether each inferred exclusion is intentional or accidental. Accidental exclusions are bugs-in-waiting; intentional ones are valuable spec boundaries. **A `PROVISIONAL:` non-goal is a gate, not a formality**: it converts to a committed Non-Goal only on the user's explicit confirmation in this pass. If the user cannot decide, it stays `PROVISIONAL:` and also gets a `TBD:` marker (Step 4) naming what's unresolved — it does not silently become a committed claim by default, and this is on the critical path for any system (e.g. bidboard) that enters the methodology through this skill: a spec writer downstream must not encode an unconfirmed absence as a hard boundary.

The revision pass is conversational. Resist the urge to power through it — surfacing one real tension per session is worth more than producing a clean-looking document.

## Step 4: Capture open questions

By the end of the revision pass, some questions will be unresolved. Record each as a `TBD:` marker in the document with:

- The specific question
- Why it matters (which downstream spec depends on the answer)
- The user's current best guess, if any

These become work items for the team's review, separate from the methodology. Do not paper over them.

## Step 5: Save and surface the surprises

Before saving, sweep the Non-Goals section: no entry may remain tagged `PROVISIONAL:` in the committed document. Every one must be either confirmed (tag removed, now a committed Non-Goal) or converted to a `TBD:` marker in Open Questions if the user could not decide. Do not save a document with an unresolved `PROVISIONAL:` non-goal silently standing in as a committed claim.

Write the document to the resolved target path. Confirm the save succeeded by reading the file back.

Then summarize for the user:

- Path to the saved file relative to the project root, and whether it matches the project's `target_spec` (flag the mismatch explicitly when it does not)
- **Tensions surfaced** — count of `TENSION:` blocks, with one-line summary of each. These are the most valuable output of this skill.
- **TBDs recorded** — count of open questions
- **Sections that came clean** — sections where the code and the (claimed) intent agreed, with no tensions
- A suggested next step. Typically:
  - If many tensions surfaced: resolve them before any spec writing; spec'ing tension is wasted work
  - If TBDs dominate: a focused team discussion to resolve them, then re-run this skill
  - If the document is clean: proceed to `fv-adversarial` against the intent itself before drafting specs

## Acceptance criteria

- Every claim in the document traces to a `(from: <file>:<line>)` citation, a user statement, or an `(inferred from: <evidence>)` marker.
- **No Non-Goal in the saved document is tagged `PROVISIONAL:`.** Every inferred exclusion was either explicitly confirmed by the user in Step 3 (and the tag removed) or demoted to a `TBD:` marker in Open Questions. This is a hard gate, not a style preference — it is on the critical path for any brownfield system (e.g. bidboard) entering the methodology through this skill, where an unconfirmed absence must not be encoded downstream as a hard spec boundary.
- The revision pass (Step 3) ran section by section; extraction alone was not treated as sufficient.
- At least one `TENSION:` block exists, or its absence is justified (the code and claimed intent genuinely agreed everywhere — rare, and worth double-checking before accepting).
- Every `TBD:` marker states the specific question, why it matters downstream, and the user's current best guess if any.

## What you do not do

- You do not invent intent the artifacts do not support. Every claim must trace to either a file/line/commit, a user statement during the revision pass, or an explicit `(inferred)` marker that the user accepted.
- You do not silently treat the implemented behavior as the intended behavior. The whole point of the revision pass is to ask the user to commit, not to assume.
- You do not skip the revision pass even when extraction looks complete. The revision is where the value lives.
- You do not write specs, fix code, or run verification. Those come later.

## Failure modes

- **The code is too large to read in full.** Ask the user to narrow scope. Reverse-intent on a 50k-line crate is hopeless; on a 500-line module it is achievable. Push back early.
- **Auxiliary docs contradict the code.** Surface this as a tension rather than picking one as canonical. The team needs to know.
- **The user cannot answer "what should this do?" for some behavior.** This is a `TBD:`. Not a failure — it is the skill working correctly.
- **The user wants to skip the revision pass.** Push back. The extraction-only output is a fiction; the methodology is bounded by the quality of the intent doc, and an unrevised reverse-extraction is not it.

## Spirit

The implemented system already has an opinion about how it should behave. That opinion is hidden in code, comments, and reviewer memory. Your job is to surface it, ask the team to commit to it (or revise it), and write it down where downstream verification can use it. The tensions you find are the methodology's most valuable contribution to a brownfield system — every one is a place where the team has been deferring a decision they didn't know they were deferring.
