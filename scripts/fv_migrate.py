#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
fv_migrate — shadow-migrate a legacy `.colosseum` project into `.fv`.

The migration is non-destructive by construction: every write lands under
`.fv/`, `.colosseum/` is only ever read, and a dry run is the default. It is a
*shadow* migration because the legacy tree stays in place, byte-identical, and
remains the auditable original for everything the translation cannot carry
across.

USAGE
    scripts/fv_migrate.py PROJECT [--apply] [--json]

    PROJECT     project root holding `.colosseum/`
    --apply     write the migration (only under `.fv/`); default is dry-run
    --json      emit the deterministic JSON report instead of the text report

    Exit 0 when the report's status is `ok`, 1 when it is `blocked` (or the
    legacy tree cannot be inventoried at all), 2 for a usage error or an
    unresolvable PROJECT.

INVENTORY
    Every source artifact is reported as exactly one of `mapped`,
    `preserved-history`, or `unsupported`; a run that cannot classify an
    artifact is a blocked run, never a partial write. Sub-artifact rows
    (`<file>#layers.<name>`, `<file>#claims.<id>`) are emitted only for an item
    inside a mapped file that deviates from its file's mapping, so a lossy
    translation names what it dropped instead of implying the file came across
    whole.

    mapped
        `.colosseum/ledger.md`                  -> `.fv/ledger.md` (verbatim)
        `.colosseum/intent.md`                  -> the dispatch target
        `.colosseum/obligations.json`           -> `.fv/obligations.json`
        `.colosseum/g1-claims.json`             -> `.fv/obligations.json`
        `.colosseum/evidence/runs/layer-runs.json`
                                                -> `.fv/verification-plan.json`
        `.colosseum/verified-inputs.txt`         -> `.fv/verified-inputs.txt`
                                                   (translated, and also kept
                                                   verbatim under history)
    preserved-history
        every other regular file, byte-for-byte, under
        `.fv/history/colosseum/<path relative to .colosseum>`. That includes
        the legacy per-claim evidence under `.colosseum/evidence/`: a v1/v2
        record is history, and copying one into `.fv/evidence/` would present
        it as a live `fv-evidence-run/v3` record it cannot satisfy. A history
        copy carries the bytes and the executable bit; no other mode bit, no
        ownership, no timestamp, and no empty legacy directory is represented,
        because the inventory is an inventory of files.
    unsupported
        a non-regular or unreadable file, a directory that cannot be listed,
        an unknown or malformed legacy schema, a malformed claim, a legacy
        verification layer no plan execution can carry, a claim whose
        `required_evidence` no migrated execution can produce, an ambiguous or
        absent dispatch target, or a destination that already exists with
        different content.

DISPATCH TARGET
    The canonical intent is elected from the legacy pointer stub first and
    from the ledger only second: a stub is a declaration, ledger prose is not.
    `.colosseum/intent.md` is read and a `*intent.md` path it cites that
    resolves under the project root becomes the dispatch target; only when the
    stub cites none does the ledger's citations decide. Two or more distinct
    surviving candidates in whichever document decides are unsupported and
    block the run -- frequency of mention in untrusted legacy prose must never
    pick between trust roots -- and so is no candidate at all, since a
    migrated project whose `target_spec` names nothing cannot resolve a target
    for any gate, producer, or skill. The elected spec is a top-level
    `target_spec` field of the report, not only a sentence inside a detail
    string, so a dry-run consumer can check the decision.

OBLIGATIONS
    Legacy `obligations.json` carries only `{claim_id, required}`; the
    dependency structure lives in `g1-claims.json`. The two are joined into one
    FV manifest: each legacy claim becomes a `system_claims` entry whose
    `depends_on` is its `required_targets` and whose `required_evidence` is its
    `layers`. Each distinct target is synthesized as its own obligation:
    `proptest:`/`test`-prefixed targets are witnesses, every other prefix is an
    invariant. `scope`, `waiver`, `evidence_class`, `profile`, and
    `environment_policy` are retained rather than summarized. A claim key this
    translation has no typed slot for -- an unknown key, or one of those keys
    carrying a type its slot cannot hold -- is carried verbatim under the
    claim's `legacy_fields` and named in a `#claims.<id>` deviation row, so a
    dropped `waiver` can neither vanish nor be implied to have come across as
    a waiver. Document-level keys other than `schema`, `version`, `claims`,
    `profile`, and `environment_policy` are named in a `#document` row; the
    document itself survives in history.

    Every synthesized id is the id `fv_evidence_run` will discharge it under.
    That tool writes `.fv/evidence/records/<claim_id>.json`, so a legacy
    `<layer>:<name>` target is not usable as an id: it becomes
    `<layer>.<name>` with every character outside `[A-Za-z0-9._-]` collapsed
    to a single `-` (`quint:invS7` -> `quint.invS7`,
    `verus:contract::state::Machine` -> `verus.contract-state-Machine`), and
    the exact legacy target is kept in `legacy_id`. `depends_on` names the
    migrated ids, so the manifest is dischargeable as written and nothing has
    to be renamed after the migration. A legacy id that normalizes to nothing,
    and any two legacy ids that normalize to the same id, are unsupported: one
    record path cannot stand for two obligations, and a disambiguating suffix
    no legacy artifact names would have to be invented.

VERIFICATION PLAN
    `colosseum-layer-runs/v2` records one shell string per layer. Only a simple
    semicolon-separated sequence of argv words is representable as an
    `fv-verification-plan/v1` execution list, so each segment is split with
    `shlex` and any shell operator or expansion character makes the layer
    unsupported -- wrapping it back in `sh -c` would launder the shell the plan
    schema exists to exclude. Tokenizing into words is not the same as being
    argv: a leading `NAME=VALUE` assignment and a segment whose `argv[0]` is a
    builtin whose effect dies with the process (`cd`, `export`, `source`,
    `eval`, ...) are shell state changes, not commands, and are refused for
    the same reason. A `cd` in particular would otherwise execute
    `/usr/bin/cd`, exit 0, and silently move the recorded command to a
    different working directory.

    Legacy names that have a pyramid equivalent are renamed to it (`proptest`
    -> `proptests`); every other legacy layer keys the plan under its own id,
    which `fv-verification-plan/v1` accepts as a custom layer, so `quint`
    migrates as the layer `quint` instead of being dropped. A recorded layer
    that cannot be translated at all -- a command no argv represents, a cwd
    that is missing or escapes the root, a malformed environment, or an id the
    schema reserves (`floors`) -- is unsupported and blocks the whole
    migration: a plan that silently omits a layer the legacy manifest recorded
    would present unrun verification as complete, so no partial plan is
    written. The completeness rule runs in both directions: an evidence tool
    some migrated claim's `required_evidence` names and no migrated execution
    produces is equally unsupported, since the migrated project would declare
    a claim its own plan can never discharge. A legacy tree that recorded no
    `evidence/runs/layer-runs.json` at all is that same case at its limit and
    is refused the same way, deliberately: the plan declares nothing, so every
    claim naming a layer is undischargeable, and a status-ok migration would
    publish required obligations against a project with no declared execution.
    The remedy is in the refusal: record the run manifest, or drop the layers
    from the claims that name them. It is not a shape to relax into an ok
    migration -- the coverage it would assert is the one thing the migration
    must never invent.

    A layer is written `required: true` when any migrated claim names it, not
    only when a claim the legacy `obligations.json` marked required does:
    Gate B demands evidence for every declared obligation regardless of that
    flag, and a custom layer outside the plan's `required` set can fail while
    the pyramid still reports VERIFIED. Two independent recorded runs of one
    layer are merged into one cohort, which the `<layer>:<index>`
    last-segment scheme cannot describe, so their executions are keyed
    `<layer>:run<k>.<i>` and the merge is reported as a `#layers.<name>`
    deviation row.

VERIFIED INPUTS
    Legacy `verified-inputs.txt` is an include list: its entries name the paths
    in scope. FV include mode means exactly that, so the list is translated
    rather than inverted -- inverting it would mean enumerating the complement
    of the repository, which is what the legacy project adopted an include list
    to avoid. `.fv/verified-inputs.txt` is written with `mode: include` as its
    first non-comment line, and every legacy entry is carried across:

      - a source root (`crates`, `quint`, `proofs`, `Cargo.toml`,
        `Cargo.lock`, ...) is kept verbatim, since both files grade paths the
        same way;
      - an entry naming a legacy manifest binds the FV artifact that
        manifest's content migrated to -- `.colosseum/obligations.json` and
        `.colosseum/g1-claims.json` bind `.fv/obligations.json`,
        `.colosseum/evidence/runs/layer-runs.json` binds
        `.fv/verification-plan.json` -- because the legacy tree is
        structurally excluded and its own bytes become history. The mapping is
        read from this run's inventory, so an entry only ever binds an
        artifact this migration actually wrote;
      - an entry naming legacy bytes that migrate to history alone binds
        nothing and is reported as a `#<entry>` deviation row, rather than
        silently narrowing the policy;
      - the elected canonical target is bound whether or not the legacy list
        named it, since it is the document every migrated evidence record
        binds to, and so are whichever of `.fv/obligations.json` and
        `.fv/verification-plan.json` this run wrote: FV reads them to decide
        what each layer must discharge and what command discharges it, which
        is what the legacy list bound `.colosseum/obligations.json` for;
      - `.fv/verified-inputs.txt` binds itself, so editing the policy
        invalidates the evidence bound to it.

    The emitted bytes are read back through the same parser the gate and the
    producer use before they are planned: a lost mode directive would
    republish the policy as an exclusion list binding the whole repository
    minus a few source roots. A legacy list that is not valid UTF-8, does not
    parse under the path grammar, declares no entries at all, or whose every
    entry translates to nothing is unsupported and blocks the migration. The
    last case is the one worth stating: the policy would still bind the
    canonical target and the migrated manifests, so it would be a valid
    include policy, and the evidence bound to it would survive every edit to
    the sources a layer actually decides on. The exact legacy list is
    preserved verbatim at `.fv/history/colosseum/verified-inputs.txt` whatever
    the translation did with it. A legacy tree that recorded no include list at
    all has nothing to translate and gets FV's conservative exclusion defaults.

APPLY
    `--apply` is all-or-nothing. Preflight refuses a destination whose path
    crosses a symlink at any component -- `.fv` itself included, since both
    `mkdir` and an ordinary open follow one -- a destination that exists with
    different content, and a destination directory that is not writable. The
    writes themselves are staged under `.fv/.migrate-staging/<run>/` in full
    and then moved into place with `os.replace`, which does not follow a
    symlink at the final name. A destination that already exists is moved
    aside into the same staging tree before the new bytes land, so a failure
    during the moves renames the original inode back and restores its mode,
    ownership and timestamps together with its bytes, none of which writing
    saved bytes into a fresh file reproduces. An aside that itself fails left
    its destination untouched, so that write is `failed` and not `lost`, and
    nothing is held back. Each write's reported action is what happened to it
    (`written`, `rolled-back`, `failed`, `lost`, `pending`), and the report is
    printed even when the apply fails, because it is the only enumeration of
    what landed.

    The staging prefix is every byte's first destination, so it is held to the
    same containment rule as a real one: preflight refuses a symlinked or
    unwritable `.fv/.migrate-staging`, and the apply re-checks the prefix and
    the run directory it creates under it before the first staged byte, since
    the prefix is a fixed name anything with write access to `.fv` can replace
    with a link. The prefix is also structurally excluded from the
    verified-input snapshot, and every run stages under its own unique
    subdirectory of it. A hard kill between the first and the last move
    therefore strands only snapshot-excluded residue: it cannot move a
    snapshot, no later or concurrent run reuses it, and nothing collects it.
    Concurrent migrations of one project share only the prefix, and each drops
    it once it is empty, so a sibling removing it while this run creates its
    own directory is retried and then reported as the race it is.

    `.fv/dispatch.json` is the single destination adopted rather than
    refused: an existing route keeps every field except the `project_root`
    and `target_spec` this migration owns, reported as the `adopt` action
    with the before and after in the write's detail, and keeps its mode --
    the replacement is a fresh inode, so a route an operator narrowed must
    not come back at the umask default. Refusing it instead would make every
    project already initialized by `fv_init` unmigratable without moving the
    file aside.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import fv_project  # noqa: E402  canonical project-root, target, and exclusion rules
import pyramid_run  # noqa: E402  single source of truth for the plan schema

REPORT_SCHEMA = "fv-migration-report/v1"
LEGACY_DIRNAME = ".colosseum"
HISTORY_RELATIVE = ".fv/history/colosseum"
HISTORY_EXCLUSION = ".fv/history/"
# Fixed staging prefix, one unique subdirectory per run. Fixed so a single
# exclusion prefix covers it, and per-run so concurrent migrations never
# stage into each other and no run inherits a killed run's residue.
STAGING_RELATIVE = ".fv/.migrate-staging"
STAGING_EXCLUSION = ".fv/.migrate-staging/"
# A fixed prefix is also a name something can replace with a symlink long
# before any migration runs, so it is preflighted and guarded exactly like a
# destination. It is shared, too: every concurrent migration of one project
# removes it once it is empty, so a sibling removing it between this run's
# `mkdir` and its `mkdtemp` is an ordinary race, retried this many times
# before the race is reported as itself rather than as ENOENT on a temp path.
STAGING_ATTEMPTS = 5

MAPPED = "mapped"
PRESERVED = "preserved-history"
UNSUPPORTED = "unsupported"
CLASSIFICATIONS = (MAPPED, PRESERVED, UNSUPPORTED)

LEGACY_OBLIGATIONS = "obligations.json"
LEGACY_CLAIMS = "g1-claims.json"
LEGACY_INTENT = "intent.md"
LEGACY_LEDGER = "ledger.md"
LEGACY_VERIFIED_INPUTS = "verified-inputs.txt"
LEGACY_LAYER_RUNS = "evidence/runs/layer-runs.json"

OBLIGATIONS_SCHEMA = "colosseum-obligations"
CLAIMS_SCHEMA = "colosseum-g1-claims"
LAYER_RUNS_SCHEMA = "colosseum-layer-runs"
LAYER_RUNS_VERSION = 2

# Legacy layer id -> the built-in pyramid layer that runs it. A legacy layer
# absent here has no built-in equivalent and keys the plan under its own id as
# an fv-verification-plan/v1 custom layer, so it is neither renamed onto a
# wrong built-in nor dropped.
LEGACY_PLAN_LAYERS = {
    "proptest": "proptests",
}
# Legacy manifests record no timeout, so every migrated execution inherits one
# conservative ceiling rather than a fabricated per-layer table.
MIGRATED_TIMEOUT_SECONDS = 3600

# check_evidence_records.OBLIGATION_ID / EVIDENCE_TOOL_ID: an obligation id or
# evidence tool id the gate will accept.
OBLIGATION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]*")
EVIDENCE_TOOL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:+/-]*")
# tools/evidence-run.ts: the only claim_id shape the evidence producer accepts.
# It writes `.fv/evidence/records/<claim_id>.json` and
# `.fv/evidence/raw/<claim_id>-<run_id>.log`, so a `:` or a `/` in an id is not
# a name but a path: an obligation id outside this alphabet cannot be
# discharged at all. Every id this migration synthesizes matches it.
EVIDENCE_CLAIM_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
# One maximal run of characters no evidence claim id may carry.
UNSAFE_ID_RUN = re.compile(r"[^A-Za-z0-9._-]+")
# A required target the legacy manifest discharged with a test rather than a
# checked invariant becomes a witness.
WITNESS_PREFIXES = frozenset({"proptest", "proptests"})

# Any of these in a command segment means a shell, not an argv: redirection,
# pipes, substitution, globbing, grouping, background, or word expansion. The
# separator `;` is not listed because the segments are split on it first.
SHELL_CHARACTERS = frozenset("|&<>$`(){}[]*?~!\n\r\\\0")
# A leading `NAME=VALUE` word is a shell assignment prefix, not argv[0]:
# executing the segment as argv would look for a binary of that literal name.
# The recorded environment has its own `environment` object beside the
# command, and the plan schema its own `env` field, so lifting the assignment
# would be inventing a second, unrecorded source of environment.
ENV_ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
# argv[0]s whose whole effect is a change to shell state that dies with the
# process, plus the builtins that interpret further shell text. `cd` is the
# motivating case: /usr/bin/cd exists on a POSIX system, so `cd crates/core;
# cargo verus verify` would split into two argv executions, the first exiting
# 0 without doing anything and the second running at the wrong cwd -- a
# recorded command silently translated into a different one.
SHELL_ONLY_COMMANDS = frozenset({
    ".", ":", "alias", "bg", "builtin", "cd", "chdir", "command", "declare",
    "disown", "eval", "exec", "exit", "export", "fg", "hash", "jobs", "let",
    "local", "logout", "popd", "pushd", "read", "readonly", "return", "set",
    "shift", "shopt", "source", "suspend", "times", "trap", "type", "typeset",
    "ulimit", "umask", "unalias", "unset", "wait",
})

# Legacy claim keys this translation places in a typed slot of a migrated
# system_claim. Every other key, and every one of these carrying a type its
# slot cannot hold, is carried verbatim under `legacy_fields` and named in a
# deviation row: a lossy translation must say what it could not interpret.
CLAIM_CONSUMED_KEYS = frozenset({
    "claim_id", "required_targets", "layers", "scope", "waiver", "evidence_class",
})
# Document-level keys of a legacy claim manifest this translation reads.
CLAIMS_DOCUMENT_KEYS = frozenset({
    "schema", "version", "claims", "profile", "environment_policy",
})

# Written only when the legacy tree recorded no include list at all: there is
# nothing to translate, so the migrated project starts from FV's conservative
# exclusion defaults.
VERIFIED_INPUTS_EXCLUSION_HEADER = (
    "# Verified-input exclusion prefixes for the FV evidence content snapshot.\n"
    "# The mode directive below is the first non-comment line; the entries under\n"
    "# it are the paths the snapshot does not bind. Blank lines and # comments\n"
    "# are ignored; directory prefixes end in /.\n"
    "#\n"
    "# The legacy tree recorded no .colosseum/verified-inputs.txt, so there was\n"
    "# no include list to translate and this file starts from FV's conservative\n"
    "# defaults. Imported history is excluded: those bytes are a record of past\n"
    "# runs, not an input any layer reads.\n"
)

# Written whenever the legacy tree did record an include list. The legacy file
# and FV include mode mean the same thing, so the entries are translated, not
# inverted: inverting would mean enumerating the complement of the repository.
VERIFIED_INPUTS_INCLUDE_HEADER = (
    "# Verified-input include policy for the FV evidence content snapshot.\n"
    "# The mode directive below is the first non-comment line; the entries under\n"
    "# it are the only paths the snapshot binds. Blank lines and # comments are\n"
    "# ignored; directory prefixes end in /.\n"
    "#\n"
    "# Translated from .colosseum/verified-inputs.txt, which was already an\n"
    "# include list: FV include mode means the same thing, so each legacy entry\n"
    "# is carried across rather than inverted into the complement of the\n"
    "# repository. An entry naming a legacy manifest binds the FV artifact its\n"
    "# content migrated to instead, because the legacy bytes themselves become\n"
    "# snapshot-excluded history. The exact legacy list is kept verbatim at\n"
    "# .fv/history/colosseum/verified-inputs.txt.\n"
    "#\n"
    "# This file binds itself, so editing the policy invalidates the evidence\n"
    "# bound to it. FV's structural output exclusions still apply before include\n"
    "# matching, so no FV or legacy output can stale a record.\n"
)

# FV artifacts this migration authors that verification itself reads: the
# obligation manifest says what each layer must discharge and the plan says
# what command discharges it. A translated include policy binds whichever of
# them the run wrote, on the same ground the legacy list bound
# `.colosseum/obligations.json`: editing one changes what a layer decides.
MIGRATED_VERIFIED_ARTIFACTS = (".fv/obligations.json", ".fv/verification-plan.json")

OBLIGATIONS_NOTE = (
    "Migrated by scripts/fv_migrate.py. Each system claim is a legacy "
    "colosseum-g1-claims claim: depends_on is its required_targets, "
    "required_evidence is its layers. Invariants and witnesses are the "
    "synthesized required targets, each keyed by the evidence-run-safe id its "
    "legacy `<layer>:<name>` target maps to (`quint:invS7` -> `quint.invS7`), "
    "with the exact legacy spelling kept in `legacy_id`; no evidence record "
    "is migrated, so every obligation here is uncovered until an "
    "fv-evidence-run/v3 record binds it."
)


class MigrationError(Exception):
    """The legacy tree cannot be inventoried: no report can be produced."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(document: object) -> bytes:
    """Deterministic pretty JSON bytes, stable across runs and platforms."""
    return (json.dumps(document, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


@dataclass(frozen=True)
class Artifact:
    source: str
    classification: str
    destination: str | None
    detail: str

    def as_json(self) -> dict:
        return {
            "source": self.source,
            "classification": self.classification,
            "destination": self.destination,
            "detail": self.detail,
        }


@dataclass
class PlannedWrite:
    path: str
    data: bytes
    action: str = "create"
    # A history copy carries its source's executable bit; None leaves the
    # umask default, which is what every synthesized artifact wants.
    mode: int | None = None
    # `.fv/dispatch.json` is the one destination this migration may rewrite
    # rather than refuse: it adopts an existing route instead of replacing it.
    adopt: bool = False
    detail: str = ""

    def as_json(self) -> dict:
        row = {"path": self.path, "action": self.action, "sha256": sha256_bytes(self.data)}
        if self.detail:
            row["detail"] = self.detail
        return row


@dataclass
class _Moved:
    """One destination the apply has already touched, and what putting it
    back takes: the original inode moved aside (`None` when the destination
    did not exist) and whether the new bytes actually landed."""
    write: PlannedWrite
    destination: Path
    original: Path | None = None
    landed: bool = False


def _dedup(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _id_strings(value: object, pattern: re.Pattern[str]) -> list[str] | None:
    """A nonempty, deduplicated list of well-formed ids, or None on a defect."""
    if not isinstance(value, list) or not value:
        return None
    for entry in value:
        if not isinstance(entry, str) or pattern.fullmatch(entry) is None:
            return None
    ids = _dedup(value)
    return ids or None


def _safe_id_part(raw: str) -> str:
    """One id part with every unsafe run collapsed to a single `-`.

    Separators are stripped from both ends so a part can only start and end on
    an alphanumeric: `EVIDENCE_CLAIM_ID` requires it of the first character,
    and a trailing `-` or `.` would otherwise make two legacy names that
    differ only in punctuation look like distinct ids while resolving to the
    same record file.
    """
    return UNSAFE_ID_RUN.sub("-", raw).strip("._-")


def evidence_claim_id(legacy: str) -> str | None:
    """The evidence-run-safe obligation id `legacy` migrates to, or None.

    A legacy `<layer>:<name>` target becomes `<layer>.<name>`, and every
    character outside the evidence-run alphabet collapses to a single `-`, so
    `quint:invS7` -> `quint.invS7`, `kani:proof_harness` ->
    `kani.proof_harness`, `verus:contract::state::Machine` ->
    `verus.contract-state-Machine`. The mapping is total and deterministic:
    the migrated manifest is directly dischargeable by `fv_evidence_run` with
    no post-migration rename.

    It is deliberately not injective -- `verus:contract::state` and
    `verus:contract-state` both land on `verus.contract-state` -- because the
    alternative is an invented disambiguating suffix that no legacy artifact,
    ledger citation, or operator expectation names. The caller blocks on the
    collision instead.

    None means the legacy id carries no alphanumeric in some part (`quint:` or
    `:invS7` or `::`): there is no id to synthesize and nothing is guessed.
    """
    layer, separator, name = legacy.partition(":")
    parts = [_safe_id_part(layer)]
    if separator:
        parts.append(_safe_id_part(name))
    if not all(parts):
        return None
    migrated = ".".join(parts)
    return migrated if EVIDENCE_CLAIM_ID.fullmatch(migrated) else None


def _own(owners: dict[str, list[str]], migrated: str, legacy: str) -> None:
    """Record that `legacy` migrates to `migrated`, in first-seen order.

    An id with more than one owner is a collision the migration refuses: the
    two legacy obligations would share one evidence record path.
    """
    legacies = owners.setdefault(migrated, [])
    if legacy not in legacies:
        legacies.append(legacy)



def _uninterpreted_claim_fields(claim: dict) -> dict:
    """Legacy claim fields the migration cannot place in a typed slot.

    Two kinds, both silent losses otherwise: a key this translation knows
    nothing about (`status`, `notes`, `required_targets_optional`), and a key
    it does know carrying a type its slot cannot hold (a `waiver` string
    where the manifest shape is an object). The caller carries the result
    verbatim under the migrated claim's `legacy_fields` and names it in a
    deviation row: the manifest is the only artifact a later auditor reads,
    so a legacy record of what a claim excluded must not disappear from it.
    """
    carried = {key: value for key, value in claim.items() if key not in CLAIM_CONSUMED_KEYS}
    for key, expected in (("scope", dict), ("waiver", dict), ("evidence_class", str)):
        if key in claim and not isinstance(claim[key], expected):
            carried[key] = claim[key]
    return dict(sorted(carried.items()))


def split_command(command: str) -> tuple[list[list[str]] | None, str]:
    """Translate a legacy shell string into argv lists, or explain the refusal.

    Only a semicolon-separated sequence of plain argv words is representable:
    every other shell construct is rejected rather than re-wrapped in `sh -c`,
    which would reintroduce the shell the plan schema exists to exclude.
    Tokenizing into words is not sufficient. A segment that assigns an
    environment variable or runs a builtin whose effect dies with the process
    is shell state, not a command, and the executions the plan schema
    describes cannot carry either: both are refused here rather than
    translated into an argv that means something else.
    """
    if not isinstance(command, str) or not command.strip():
        return None, f"command must be a non-empty string, got {command!r}"
    executions: list[list[str]] = []
    for segment in command.split(";"):
        if not segment.strip():
            continue  # a trailing or doubled separator carries no command
        offending = sorted(SHELL_CHARACTERS.intersection(segment))
        if offending:
            return None, (
                f"segment {segment.strip()!r} uses shell construct(s) "
                f"{''.join(offending)!r}: no argv represents it"
            )
        try:
            argv = shlex.split(segment, posix=True)
        except ValueError as error:
            return None, f"segment {segment.strip()!r} does not tokenize: {error}"
        if not argv or any(not word for word in argv):
            return None, f"segment {segment.strip()!r} tokenizes to no command"
        if ENV_ASSIGNMENT.match(argv[0]):
            return None, (
                f"segment {segment.strip()!r} begins with the environment assignment "
                f"{argv[0]!r}: an assignment prefix is shell state and not argv[0], and the "
                "run's own `environment` object is the only environment this translation "
                "carries"
            )
        if argv[0] in SHELL_ONLY_COMMANDS:
            return None, (
                f"segment {segment.strip()!r} runs the shell builtin {argv[0]!r}, whose effect "
                "does not survive the process that runs it: no argv represents it, and "
                "executing it as one would silently drop what the recorded command did"
            )
        executions.append(argv)
    if not executions:
        return None, f"command {command!r} carries no argv"
    return executions, ""


class Migration:
    """One migration of one project: inventory, intended writes, preflight."""

    def __init__(self, project: Path) -> None:
        self.project = project
        self.legacy = project / LEGACY_DIRNAME
        self.artifacts: list[Artifact] = []
        self.unsupported: list[str] = []
        self.conflicts: list[str] = []
        # The dispatch target this migration elected, reported as its own
        # field so a dry-run consumer never has to parse a detail string to
        # learn which document the migrated project will bind evidence to.
        self.target_spec: str | None = None
        self._writes: dict[str, PlannedWrite] = {}
        self._history_skip: set[str] = set()
        self._legacy_files: list[str] = []
        # Every layer any migrated claim names, or None when no claim
        # manifest converted: the sentinel means "no claim says otherwise",
        # under which every recorded layer gates.
        self._required_layers: set[str] | None = None
        # Legacy claim id -> its required_evidence, for the plan-completeness
        # check that runs once both manifests have been translated.
        self._claim_layers: dict[str, list[str]] = {}
        # Evidence tool ids the migrated plan declares, or None when no plan
        # was translated at all.
        self._plan_tools: set[str] | None = None
        self._plan_blocked = False

    # ---- bookkeeping -----------------------------------------------------

    def _mapped(self, source: str, destination: str, detail: str, *, verbatim: bool = False) -> None:
        self.artifacts.append(Artifact(source, MAPPED, destination, detail))
        if verbatim:
            # The bytes already survive at the mapped destination; a second
            # identical copy under history would preserve nothing new.
            self._history_skip.add(source)

    def _preserved(self, source: str, detail: str) -> None:
        self.artifacts.append(Artifact(source, PRESERVED, self._history_path(source), detail))

    def _deviation(self, source: str, destination: str, detail: str) -> None:
        """One `<file>#<item>` row: part of a mapped file that did reach the
        destination, but not with the meaning the file's mapping implies."""
        self.artifacts.append(Artifact(source, MAPPED, destination, detail))

    def _unsupported(self, source: str, detail: str) -> None:
        self.artifacts.append(Artifact(source, UNSUPPORTED, None, detail))
        self.unsupported.append(f"{source}: {detail}")

    def _history_path(self, source: str) -> str:
        """Where a legacy path's bytes land. A `#fragment` names an item inside
        a file, so it is dropped: the destination is the file that holds it."""
        relative = source.split("#", 1)[0]
        if relative.startswith(LEGACY_DIRNAME + "/"):
            relative = relative[len(LEGACY_DIRNAME) + 1 :]
        return f"{HISTORY_RELATIVE}/{relative}"

    def _plan_write(self, path: str, data: bytes, *, mode: int | None = None,
                    adopt: bool = False, detail: str = "") -> None:
        """Record intended bytes for one `.fv` destination."""
        if not path.startswith(".fv/"):
            raise MigrationError(f"refusing to write outside .fv: {path}")
        existing = self._writes.get(path)
        if existing is not None:
            if existing.data != data:
                raise MigrationError(f"two sources disagree about {path}")
            return
        self._writes[path] = PlannedWrite(path, data, mode=mode, adopt=adopt, detail=detail)

    # ---- inventory -------------------------------------------------------

    def _scan(self) -> None:
        if not self.legacy.is_dir() or self.legacy.is_symlink():
            raise MigrationError(f"{self.legacy}: no legacy .colosseum directory to migrate")

        def walk(directory: Path) -> None:
            try:
                entries = sorted(directory.iterdir(), key=lambda item: item.name)
            except OSError as error:
                self._unsupported(
                    directory.relative_to(self.project).as_posix(),
                    f"directory cannot be listed: {error}; the files under it cannot be "
                    "inventoried, so none of them can be classified",
                )
                return
            for entry in entries:
                relative = entry.relative_to(self.project).as_posix()
                if entry.is_symlink():
                    self._unsupported(
                        relative,
                        "symlink: copying it would either duplicate its target's bytes under a "
                        "different identity or leave a dangling link",
                    )
                elif entry.is_dir():
                    walk(entry)
                elif entry.is_file():
                    self._legacy_files.append(relative)
                else:
                    self._unsupported(relative, "not a regular file: no bytes to preserve")

        walk(self.legacy)

    def _read_bytes(self, relative: str) -> bytes | None:
        try:
            return (self.project / relative).read_bytes()
        except OSError as error:
            self._unsupported(relative, f"unreadable: {error}")
            return None

    def _read_json(self, relative: str) -> object | None:
        data = self._read_bytes(relative)
        if data is None:
            return None
        try:
            return json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            self._unsupported(relative, f"not readable JSON: {error}")
            return None

    def _has(self, relative_to_legacy: str) -> bool:
        return f"{LEGACY_DIRNAME}/{relative_to_legacy}" in self._legacy_files

    # ---- intent and ledger ----------------------------------------------

    def _cited_intents(self, text: str) -> list[str]:
        """Every distinct `*intent.md` path cited in `text` that resolves to a
        file under the project root, in first-cited order."""
        specs: list[str] = []
        for match in re.findall(r"[\w./-]*intent\.md", text):
            candidate = match.lstrip("./") if match.startswith("./") else match
            if not candidate or candidate.startswith(LEGACY_DIRNAME + "/"):
                continue
            if Path(candidate).is_absolute() or ".." in Path(candidate).parts:
                continue
            try:
                resolved = fv_project.resolve_target(self.project, candidate)
            except fv_project.ProjectError:
                continue
            spec = fv_project.relative_target_spec(self.project, resolved)
            if spec not in specs:
                specs.append(spec)
        return specs

    def _external_intent(self) -> tuple[str | None, bool]:
        """The external canonical intent, and whether the election was refused.

        A legacy `.colosseum/intent.md` is frequently a pointer stub whose
        normative text lives elsewhere; migrating the stub as the dispatch
        target would bind evidence to a file that states nothing. The stub is
        therefore read first and decides on its own: it is a declaration, and
        the ledger is prose about the project, so a ledger sentence must never
        outrank the entrypoint's own pointer. The ledger decides only when the
        stub cites nothing at all.

        Whichever document decides, two or more distinct surviving candidates
        are a refusal rather than a vote. Counting mentions would let the
        arrangement of legacy prose -- a "Superseded:" paragraph naming an old
        document three times -- pick the trust root every future evidence
        record binds to.
        """
        stub = f"{LEGACY_DIRNAME}/{LEGACY_INTENT}"
        ledger = f"{LEGACY_DIRNAME}/{LEGACY_LEDGER}"
        for source, present in ((stub, stub in self._legacy_files),
                                (ledger, ledger in self._legacy_files)):
            if not present:
                continue
            try:
                text = (self.project / source).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            candidates = self._cited_intents(text)
            if not candidates:
                continue
            if len(candidates) > 1:
                self._unsupported(
                    f"{source}#intent",
                    f"cites {len(candidates)} existing canonical intents ({', '.join(candidates)}): "
                    "the dispatch target is the root every migrated evidence record binds to, and "
                    "nothing in the legacy tree ranks one citation over another, so the ambiguity "
                    "is resolved in the legacy artifact rather than guessed here",
                )
                return None, True
            return candidates[0], False
        return None, False

    def _migrate_ledger(self) -> None:
        relative = f"{LEGACY_DIRNAME}/{LEGACY_LEDGER}"
        if relative not in self._legacy_files:
            return
        data = self._read_bytes(relative)
        if data is None:
            return
        self._plan_write(".fv/ledger.md", data)
        self._mapped(
            relative,
            ".fv/ledger.md",
            "legacy ledger, verbatim: the bytes are preserved exactly, so any citation written "
            f"relative to {LEGACY_DIRNAME}/ still points where it did and now resolves from "
            ".fv/ledger.md instead. Gate A reports such a citation as unresolvable rather than "
            "reading it as prose, so re-rooting them is the first post-migration edit",
            verbatim=True,
        )

    def _migrate_intent(self) -> str | None:
        """Choose the dispatch target and report how the legacy intent got there."""
        relative = f"{LEGACY_DIRNAME}/{LEGACY_INTENT}"
        present = relative in self._legacy_files
        external, refused = self._external_intent()
        if external is not None:
            if present:
                self._mapped(
                    relative,
                    ".fv/dispatch.json",
                    f"the canonical intent is {external}, which exists: dispatch targets it "
                    "instead of this entrypoint; the entrypoint's bytes are preserved as history",
                )
            return external
        if present and not refused:
            data = self._read_bytes(relative)
            if data is None:
                return None
            self._plan_write(".fv/intent.md", data)
            self._mapped(
                relative,
                ".fv/intent.md",
                "no cited external intent: this document becomes the dispatch target",
                verbatim=True,
            )
            return fv_project.DEFAULT_TARGET_SPEC
        if not refused:
            self._unsupported(
                f"{LEGACY_DIRNAME}#intent",
                f"no dispatch target can be established: there is no {LEGACY_DIRNAME}/"
                f"{LEGACY_INTENT} and no document cites an existing canonical intent, so the "
                "migrated project would declare no target_spec and every gate, evidence run and "
                "skill would fail to resolve one",
            )
        return None

    def _migrate_dispatch(self, target_spec: str | None) -> None:
        if target_spec is None:
            return
        destination = self.project / ".fv" / "dispatch.json"
        if destination.is_file() and not destination.is_symlink():
            try:
                existing = destination.read_bytes()
                current = json.loads(existing.decode("utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
                self.conflicts.append(f".fv/dispatch.json: exists and is not readable JSON ({error})")
                return
            if not isinstance(current, dict) or not isinstance(current.get("omp_native"), dict):
                self.conflicts.append(".fv/dispatch.json: exists without an omp_native route")
                return
            route = current["omp_native"]
            before_root = route.get("project_root")
            before_target = route.get("target_spec")
            if before_root == "." and before_target == target_spec:
                # Already canonical. Re-serializing would rewrite a file this
                # migration did not author purely to change its formatting, so
                # the intended bytes are the bytes already there.
                self._plan_write(".fv/dispatch.json", existing)
                return
            # The one destination that is adopted rather than refused. A
            # project already carrying a dispatch.json has a route this
            # migration must not discard, so only the two fields the migration
            # owns are rewritten and everything else -- other omp_native keys,
            # other top-level keys -- is kept exactly as written. Refusing
            # here instead would make every fv_init-initialized project
            # unmigratable without manually moving the file aside.
            route["project_root"] = "."
            route["target_spec"] = target_spec
            self._plan_write(
                ".fv/dispatch.json",
                canonical_json(current),
                adopt=True,
                detail=(
                    f"existing route adopted: target_spec {before_target!r} -> {target_spec!r}, "
                    f"project_root {before_root!r} -> '.'; every other field of the existing "
                    "dispatch is kept"
                ),
            )
            return
        config = json.loads((REPO / "scripts" / "dispatch.config.example.json").read_text())
        config["omp_native"]["project_root"] = "."
        config["omp_native"]["target_spec"] = target_spec
        self._plan_write(".fv/dispatch.json", canonical_json(config))

    # ---- verified inputs -------------------------------------------------

    def _live_destination(self, source: str) -> str | None:
        """The live `.fv` artifact one legacy file's content migrated into.

        Read out of this migration's own inventory rather than from a second
        table of legacy-to-FV paths: an include entry must bind whatever this
        run actually wrote, and an inventory row is the only thing that knows
        it. `.fv/dispatch.json` is excluded because it is the declaration of
        the target, not a document a layer reads; the entry that named the
        legacy intent binds the elected target itself instead.
        """
        for artifact in self.artifacts:
            if artifact.classification != MAPPED or "#" in artifact.source:
                continue
            if artifact.source != source or artifact.destination is None:
                continue
            if artifact.destination == ".fv/dispatch.json":
                continue
            if artifact.destination in self._writes:
                return artifact.destination
        return None

    def _translate_include_entry(self, entry: str) -> tuple[str | None, str]:
        """The FV path one legacy include entry binds, plus why it binds it.

        A path outside `.colosseum/` is a source root and is kept verbatim:
        legacy include mode and FV include mode mean the same thing, so there
        is nothing to translate about `crates` or `Cargo.lock`. A path inside
        `.colosseum/` cannot stay: the legacy tree is structurally excluded
        from the snapshot, and its bytes become history. Such an entry binds
        the FV artifact its content migrated to, or nothing at all, and
        nothing at all is reported rather than silently narrowing the policy.
        """
        if entry != LEGACY_DIRNAME and not entry.startswith(LEGACY_DIRNAME + "/"):
            return entry, ""
        legacy_path = entry.rstrip("/") or entry
        if legacy_path == f"{LEGACY_DIRNAME}/{LEGACY_INTENT}":
            if self.target_spec is not None:
                return self.target_spec, ""
            return None, (
                "names the legacy intent entrypoint, and this migration elected no dispatch "
                "target, so there is no canonical document for the entry to bind"
            )
        destination = self._live_destination(legacy_path)
        if destination is not None:
            return destination, ""
        # The bare legacy directory has no `_history_path` of its own: its
        # files land under the history root, and that is what the entry named.
        history = (HISTORY_RELATIVE if legacy_path == LEGACY_DIRNAME
                   else self._history_path(legacy_path))
        return None, (
            f"names legacy bytes this migration preserves under {history} rather than mapping "
            "to a live FV artifact, and imported history is structurally excluded from the "
            "snapshot: a record of past runs is not an input a layer reads, so the translated "
            "policy binds nothing for this entry"
        )

    def _migrate_verified_inputs(self) -> None:
        relative = f"{LEGACY_DIRNAME}/{LEGACY_VERIFIED_INPUTS}"
        if relative not in self._legacy_files:
            # Nothing to translate. Both explicit prefixes are structural
            # defaults, so `_dedup` normally drops them; they are named anyway
            # because this migrator is what quarantines legacy history under
            # one and what strands residue under the other, and an
            # exclusion-mode project list may only ever add prefixes.
            prefixes = _dedup([*fv_project.DEFAULT_EXCLUSIONS, HISTORY_EXCLUSION,
                               STAGING_EXCLUSION])
            policy = fv_project.InputPolicy(fv_project.MODE_EXCLUDE, tuple(prefixes))
            self._plan_write(
                fv_project.VERIFIED_INPUTS_RELATIVE,
                policy.render(header=VERIFIED_INPUTS_EXCLUSION_HEADER).encode("utf-8"),
            )
            return

        data = self._read_bytes(relative)
        if data is None:
            return
        try:
            legacy = fv_project.parse_policy(data.decode("utf-8"))
        except UnicodeDecodeError as error:
            self._unsupported(
                relative,
                f"not valid UTF-8 ({error}): the entries cannot be read as paths, and a "
                "replacement character in a translated policy would bind a path that does "
                "not exist",
            )
            return
        except fv_project.ProjectError as error:
            self._unsupported(
                relative,
                f"not a parseable verified-input policy ({error}): the same grammar governs "
                "the translated FV policy, so an entry FV would reject cannot be carried "
                "across as one",
            )
            return
        if not legacy.prefixes:
            self._unsupported(
                relative,
                "declares no entries: an include list naming nothing binds nothing, and a "
                "policy translated from it would narrow the snapshot to the canonical target "
                "alone while every layer's real inputs went unbound. Record the paths the "
                "layers read, or delete the file to migrate onto FV's exclusion defaults",
            )
            return

        selected: list[str] = []
        rewrites: list[str] = []
        # Paths the translation binds that the legacy list did not name.
        bound: list[str] = []
        # Entries that bind nothing, held back until the translation is known
        # to produce a policy: a deviation row describes part of a mapped
        # file, and a blocked translation maps nothing.
        dropped: list[tuple[str, str]] = []
        for entry in legacy.prefixes:
            translated, refusal = self._translate_include_entry(entry)
            if translated is None:
                dropped.append((entry, refusal))
                continue
            if translated != entry:
                rewrites.append(f"{entry} -> {translated}")
            if translated not in selected:
                selected.append(translated)
        if not selected:
            self._unsupported(
                relative,
                "every entry names legacy bytes that migrate to snapshot-excluded history, so "
                "the translation selects nothing any layer reads: the policy would bind only "
                "the artifacts this migration authored, and the evidence bound to it would "
                "survive every edit to the sources a layer actually decides on. Name the "
                "sources in the legacy list, or delete it to migrate onto FV's exclusion "
                "defaults; inverting the list into exclusions is not the fallback, since that "
                "would enumerate the complement of the repository",
            )
            return
        # The canonical target is bound whether or not the legacy list named
        # it: it is the document every migrated evidence record binds to, so a
        # policy that left it unselected would let the trust root change under
        # evidence that still validated. The two migrated manifests are bound
        # on the same ground -- FV reads them to decide what a layer must
        # discharge and what command discharges it, which is what the legacy
        # list bound `.colosseum/obligations.json` for. Only those this run
        # actually wrote are named; an unwritten one would be an entry
        # matching nothing.
        for artifact in (self.target_spec, *MIGRATED_VERIFIED_ARTIFACTS):
            if artifact is None or artifact in selected:
                continue
            if artifact in MIGRATED_VERIFIED_ARTIFACTS and artifact not in self._writes:
                continue
            selected.append(artifact)
            bound.append(artifact)

        try:
            policy = fv_project.InputPolicy(fv_project.MODE_INCLUDE, tuple(selected))
        except fv_project.ProjectError as error:
            raise MigrationError(
                f"{fv_project.VERIFIED_INPUTS_RELATIVE}: the translated include policy over "
                f"{selected} is invalid ({error})"
            ) from error
        rendered = policy.render(header=VERIFIED_INPUTS_INCLUDE_HEADER)
        # The emitted bytes are read back through the same parser the gate and
        # the producer use, not trusted: the mode directive is one line whose
        # loss would silently republish this policy as an exclusion list that
        # binds the whole repository minus a handful of source roots.
        try:
            written = fv_project.parse_policy(rendered)
        except fv_project.ProjectError as error:
            raise MigrationError(
                f"{fv_project.VERIFIED_INPUTS_RELATIVE}: the translated policy does not parse "
                f"({error})"
            ) from error
        if written.mode != fv_project.MODE_INCLUDE or written.prefixes != policy.prefixes:
            raise MigrationError(
                f"{fv_project.VERIFIED_INPUTS_RELATIVE}: the translated policy reads back as "
                f"{written.mode} mode over {list(written.prefixes)}, not include mode over "
                f"{list(policy.prefixes)}"
            )
        if fv_project.VERIFIED_INPUTS_RELATIVE not in written.selectors():
            raise MigrationError(
                f"{fv_project.VERIFIED_INPUTS_RELATIVE}: the translated policy does not bind "
                "itself, so a policy edit would not invalidate the evidence bound to it"
            )
        self._plan_write(fv_project.VERIFIED_INPUTS_RELATIVE, rendered.encode("utf-8"))
        self._mapped(
            relative,
            fv_project.VERIFIED_INPUTS_RELATIVE,
            f"legacy include list translated to FV include mode over {len(policy.prefixes)} "
            f"entr{'y' if len(policy.prefixes) == 1 else 'ies'} "
            f"({', '.join(policy.prefixes)}): both files mean the same thing, so source roots "
            "are kept verbatim instead of inverted into exclusions"
            + (f"; legacy manifest paths rebound to the FV artifacts their content migrated to "
               f"({'; '.join(rewrites)})" if rewrites else "")
            + (f"; {', '.join(bound)} bound beyond the legacy list: the canonical target and "
               "the migrated manifests are what FV reads to decide what each layer must "
               "discharge and what command discharges it" if bound else "")
            + f"; {fv_project.VERIFIED_INPUTS_RELATIVE} binds itself, so editing the policy "
            "invalidates the evidence bound to it. The exact legacy list is kept verbatim as "
            "history",
        )
        for entry, refusal in dropped:
            self._deviation(f"{relative}#{entry}", fv_project.VERIFIED_INPUTS_RELATIVE, refusal)

    # ---- obligations -----------------------------------------------------

    def _legacy_claim_index(
        self, relative: str, schema: str
    ) -> tuple[dict[str, dict], dict] | None:
        """`claims` as an ordered id -> claim map, plus the whole document."""
        document = self._read_json(relative)
        if document is None:
            return None
        if not isinstance(document, dict):
            self._unsupported(relative, "document is not an object")
            return None
        # A legacy document that declares neither `schema` nor `version` is
        # accepted as the manifest its canonical path says it is. The file is
        # only ever read at `.colosseum/<name>`, which the legacy layout fixes
        # -- an unrelated JSON document does not live there -- and the oldest
        # legacy trees predate both keys. A declared value that disagrees is
        # still unsupported.
        declared = document.get("schema")
        if declared is not None and declared != schema:
            self._unsupported(relative, f"unknown schema {declared!r}, expected {schema!r}")
            return None
        version = document.get("version")
        if version is not None and version != 1:
            self._unsupported(relative, f"unknown {schema} version {version!r}, expected 1")
            return None
        claims = document.get("claims")
        if not isinstance(claims, list):
            self._unsupported(relative, "claims is not an array")
            return None
        index: dict[str, dict] = {}
        for position, claim in enumerate(claims):
            if not isinstance(claim, dict):
                self._unsupported(f"{relative}#claims[{position}]", "claim is not an object")
                continue
            claim_id = claim.get("claim_id")
            if not isinstance(claim_id, str) or OBLIGATION_ID.fullmatch(claim_id) is None:
                self._unsupported(f"{relative}#claims[{position}]", f"malformed claim_id {claim_id!r}")
                continue
            if claim_id in index:
                self._unsupported(f"{relative}#claims.{claim_id}", "duplicate claim_id")
                continue
            index[claim_id] = claim
        return index, document

    def _migrate_obligations(self) -> None:
        obligations_rel = f"{LEGACY_DIRNAME}/{LEGACY_OBLIGATIONS}"
        claims_rel = f"{LEGACY_DIRNAME}/{LEGACY_CLAIMS}"
        has_obligations = obligations_rel in self._legacy_files
        has_claims = claims_rel in self._legacy_files
        if not has_obligations and not has_claims:
            return

        required_flags: dict[str, bool] = {}
        obligations_order: list[str] = []
        if has_obligations:
            loaded = self._legacy_claim_index(obligations_rel, OBLIGATIONS_SCHEMA)
            if loaded is None:
                return
            index, _ = loaded
            for claim_id, claim in index.items():
                required = claim.get("required")
                required_flags[claim_id] = required is True
                obligations_order.append(claim_id)
                if not isinstance(required, bool):
                    self._unsupported(
                        f"{obligations_rel}#claims.{claim_id}",
                        f"required must be a boolean, got {required!r}",
                    )

        detail_index: dict[str, dict] = {}
        profile: object = None
        environment_policy: object = None
        if has_claims:
            loaded = self._legacy_claim_index(claims_rel, CLAIMS_SCHEMA)
            if loaded is None:
                return
            detail_index, document = loaded
            profile = document.get("profile")
            environment_policy = document.get("environment_policy")

        ordered_ids = _dedup([*detail_index, *obligations_order])
        invariants: dict[str, set[str]] = {}
        witnesses: dict[str, set[str]] = {}
        # legacy target -> the evidence-run-safe id it migrates to, and the
        # reverse map every migrated id is registered in so a normalization
        # that would put two legacy ids on one record path can be refused.
        target_ids: dict[str, str] = {}
        owners: dict[str, list[str]] = {}
        system_claims: list[dict] = []
        # Every layer any migrated claim names. Gate B requires evidence for
        # each declared obligation whatever the legacy `required` flag said,
        # so a layer a claim names has to gate the pyramid too; deriving the
        # plan's `required` from the flag alone would leave a migrated custom
        # layer able to fail while the runner still reports VERIFIED.
        claimed_layers: set[str] = set()

        for claim_id in ordered_ids:
            claim = detail_index.get(claim_id)
            if claim is None:
                self._unsupported(
                    f"{obligations_rel}#claims.{claim_id}",
                    f"required by {LEGACY_OBLIGATIONS} with no {LEGACY_CLAIMS} entry: its "
                    "depends_on and required_evidence cannot be derived",
                )
                continue
            migrated_claim = evidence_claim_id(claim_id)
            if migrated_claim is None:
                self._unsupported(
                    f"{claims_rel}#claims.{claim_id}",
                    f"claim_id {claim_id!r} normalizes to an empty evidence record id: no "
                    ".fv/evidence/records/<id>.json path could discharge it",
                )
                continue
            targets = _id_strings(claim.get("required_targets"), OBLIGATION_ID)
            if targets is None:
                self._unsupported(
                    f"{claims_rel}#claims.{claim_id}",
                    f"required_targets is not a nonempty array of obligation ids: "
                    f"{claim.get('required_targets')!r}",
                )
                continue
            layers = _id_strings(claim.get("layers"), EVIDENCE_TOOL_ID)
            if layers is None:
                self._unsupported(
                    f"{claims_rel}#claims.{claim_id}",
                    f"layers is not a nonempty array of evidence tool ids: {claim.get('layers')!r}",
                )
                continue
            unprefixed = [target for target in targets if ":" not in target]
            if unprefixed:
                self._unsupported(
                    f"{claims_rel}#claims.{claim_id}",
                    f"required_target(s) {unprefixed} carry no '<layer>:<name>' prefix: witness and "
                    "invariant cannot be told apart",
                )
                continue
            migrated_targets: list[tuple[str, str]] = []
            unmappable: list[str] = []
            for target in targets:
                migrated = evidence_claim_id(target)
                if migrated is None:
                    unmappable.append(target)
                else:
                    migrated_targets.append((target, migrated))
            if unmappable:
                self._unsupported(
                    f"{claims_rel}#claims.{claim_id}",
                    f"required_target(s) {unmappable} normalize to an empty evidence record id: no "
                    ".fv/evidence/records/<id>.json path could discharge them",
                )
                continue
            depends_on = _dedup([migrated for _, migrated in migrated_targets])
            if migrated_claim in depends_on:
                self._unsupported(
                    f"{claims_rel}#claims.{claim_id}",
                    "required_targets names the claim itself: a system claim cannot depend on a claim",
                )
                continue
            for target, migrated in migrated_targets:
                prefix = target.split(":", 1)[0]
                bucket = witnesses if prefix in WITNESS_PREFIXES or prefix.startswith("test") else invariants
                bucket.setdefault(target, set()).add(claim_id)
                target_ids[target] = migrated
                _own(owners, migrated, target)
            _own(owners, migrated_claim, claim_id)
            entry: dict = {"id": migrated_claim}
            if migrated_claim != claim_id:
                entry["legacy_id"] = claim_id
            entry["required"] = required_flags.get(claim_id, False)
            scope = claim.get("scope")
            if isinstance(scope, dict) and isinstance(scope.get("statement"), str):
                entry["statement"] = scope["statement"]
            if isinstance(claim.get("evidence_class"), str):
                entry["evidence_class"] = claim["evidence_class"]
            entry["depends_on"] = depends_on
            entry["required_evidence"] = layers
            if isinstance(scope, dict):
                entry["scope"] = scope
            if isinstance(claim.get("waiver"), dict):
                entry["waiver"] = claim["waiver"]
            uninterpreted = _uninterpreted_claim_fields(claim)
            if uninterpreted:
                entry["legacy_fields"] = uninterpreted
                self._deviation(
                    f"{claims_rel}#claims.{claim_id}",
                    ".fv/obligations.json",
                    f"legacy field(s) {', '.join(uninterpreted)} have no typed slot in a "
                    f"system_claim: carried verbatim under system_claims[{migrated_claim!r}]"
                    ".legacy_fields rather than summarized or dropped, since a legacy waiver or "
                    "status is exactly what a later auditor reads this manifest for",
                )
            system_claims.append(entry)
            self._claim_layers[claim_id] = layers
            claimed_layers.update(layers)

        collision = sorted(set(invariants) & set(witnesses))
        if collision:
            self._unsupported(
                f"{claims_rel}#claims",
                f"required target(s) {collision} classify as both invariant and witness",
            )
        for migrated, legacies in sorted(owners.items()):
            if len(legacies) > 1:
                self._unsupported(
                    f"{claims_rel}#ids.{migrated}",
                    f"legacy ids {legacies} all normalize to the obligation id {migrated!r}: one "
                    ".fv/evidence/records/<id>.json record cannot discharge two obligations, and a "
                    "disambiguating suffix no legacy artifact names would be invented, so the "
                    "colliding names must be resolved in the legacy manifest first",
                )
        if not system_claims:
            # `_required_layers` deliberately stays None here: nothing
            # converted, so no claim says which layers matter, and the plan
            # must fall back to "every recorded layer gates" rather than read
            # an empty set as "no layer gates".
            for relative, present in ((obligations_rel, has_obligations), (claims_rel, has_claims)):
                if present:
                    self._preserved(
                        relative,
                        "no legacy claim could be converted: kept as history, no obligation manifest "
                        "is written",
                    )
            return
        self._required_layers = claimed_layers

        sources = [relative for relative, present in ((claims_rel, has_claims), (obligations_rel, has_obligations)) if present]
        migration: dict = {"source": sorted(sources), "note": OBLIGATIONS_NOTE}
        legacy_document: dict = {}
        for name, value in (("profile", profile), ("environment_policy", environment_policy)):
            if isinstance(value, str):
                migration[name] = value
            elif value is not None:
                # The key is known but its value is not a statement this
                # manifest can carry in the same slot; it is kept verbatim
                # instead of being dropped or stringified.
                legacy_document[name] = value
        if has_claims:
            unknown = sorted(set(document) - CLAIMS_DOCUMENT_KEYS)
            if unknown or legacy_document:
                if legacy_document:
                    migration["legacy_fields"] = dict(sorted(legacy_document.items()))
                named = sorted({*unknown, *legacy_document})
                self._deviation(
                    f"{claims_rel}#document",
                    ".fv/obligations.json",
                    f"document-level field(s) {', '.join(named)} are not part of the migrated "
                    "manifest's shape: "
                    + ("the typed ones are carried under migration.legacy_fields; " if legacy_document else "")
                    + f"the document itself survives byte-for-byte at {self._history_path(claims_rel)}",
                )
        manifest = {
            "version": 1,
            "invariants": [
                self._obligation(target, target_ids[target], claim_ids, witness=False)
                for target, claim_ids in sorted(invariants.items(),
                                                key=lambda item: target_ids[item[0]])
            ],
            "witnesses": [
                self._obligation(target, target_ids[target], claim_ids, witness=True)
                for target, claim_ids in sorted(witnesses.items(),
                                                key=lambda item: target_ids[item[0]])
            ],
            "system_claims": system_claims,
            "migration": migration,
        }
        self._plan_write(".fv/obligations.json", canonical_json(manifest))
        converted = ", ".join(
            entry["id"] if "legacy_id" not in entry else f"{entry['legacy_id']} -> {entry['id']}"
            for entry in system_claims
        )
        if has_claims:
            self._mapped(
                claims_rel,
                ".fv/obligations.json",
                f"{len(system_claims)} legacy claim(s) converted to system_claims ({converted}); "
                f"{len(invariants)} invariant(s) and {len(witnesses)} witness(es) synthesized from "
                "required_targets, each keyed by the evidence-run-safe id its legacy target maps "
                "to and carrying that target in legacy_id",
            )
        if has_obligations:
            self._mapped(
                obligations_rel,
                ".fv/obligations.json",
                "legacy required-claim set: contributes the `required` flag of each system claim",
            )

    def _obligation(self, target: str, migrated: str, claim_ids: set[str],
                    *, witness: bool) -> dict:
        """One synthesized obligation: the migrated id, the legacy target it
        came from, and a witness's bare legacy name (which `obligation_check`
        resolves against the specification, so it is never normalized)."""
        entry: dict = {"id": migrated}
        if migrated != target:
            entry["legacy_id"] = target
        if witness:
            entry["name"] = target.split(":", 1)[1]
        entry["statement"] = self._target_statement(target, claim_ids)
        return entry

    @staticmethod
    def _target_statement(target: str, claim_ids: set[str]) -> str:
        layer, name = target.split(":", 1)
        return (
            f"{layer} target {name}, a required target of legacy claim(s) "
            f"{', '.join(sorted(claim_ids))} migrated from {LEGACY_DIRNAME}/{LEGACY_CLAIMS}"
        )

    # ---- verification plan ----------------------------------------------

    def _plan_cwd(self, raw: object) -> tuple[str | None, str]:
        if not isinstance(raw, str) or not raw.strip():
            return None, f"cwd must be a non-empty repo-relative string, got {raw!r}"
        candidate = Path(raw)
        if candidate.is_absolute():
            return None, f"cwd {raw!r} is absolute"
        if ".." in candidate.parts:
            return None, f"cwd {raw!r} escapes the project root"
        resolved = (self.project / candidate).resolve()
        if resolved != self.project and self.project not in resolved.parents:
            return None, f"cwd {raw!r} escapes the project root"
        if not resolved.is_dir():
            return None, f"cwd {raw!r} is not a directory in this project"
        return resolved.relative_to(self.project).as_posix() or ".", ""

    @staticmethod
    def _plan_env(raw: object) -> tuple[dict[str, str] | None, str]:
        if raw is None:
            return {}, ""
        if not isinstance(raw, dict):
            return None, f"environment must be an object, got {type(raw).__name__}"
        env: dict[str, str] = {}
        for name, value in raw.items():
            if not isinstance(name, str) or not name or "=" in name or "\0" in name:
                return None, f"environment name {name!r} is not a usable variable name"
            if not isinstance(value, str) or "\0" in value:
                return None, f"environment[{name!r}] must be a string without NUL, got {value!r}"
            env[name] = value
        return env, ""

    def _migrate_plan(self) -> None:
        relative = f"{LEGACY_DIRNAME}/{LEGACY_LAYER_RUNS}"
        if relative not in self._legacy_files:
            return
        # A run manifest that cannot be read at all already blocks with its
        # own row; `_plan_blocked` keeps the claim-to-plan completeness check
        # from restating that one defect once per claim.
        document = self._read_json(relative)
        if document is None:
            self._plan_blocked = True
            return
        if not isinstance(document, dict):
            self._plan_blocked = True
            self._unsupported(relative, "document is not an object")
            return
        schema = document.get("schema")
        version = document.get("version")
        if schema != LAYER_RUNS_SCHEMA or version != LAYER_RUNS_VERSION:
            self._plan_blocked = True
            self._unsupported(
                relative,
                f"unknown run manifest {schema!r} version {version!r}, expected "
                f"{LAYER_RUNS_SCHEMA!r} version {LAYER_RUNS_VERSION}",
            )
            return
        runs = document.get("runs")
        if not isinstance(runs, list) or not runs:
            self._plan_blocked = True
            self._unsupported(relative, "runs is not a nonempty array")
            return

        # planned layer id -> legacy layer id -> one execution list per
        # recorded run. Runs stay separate: two independent runs of one layer
        # are a merge this translation has to report, not a sequence.
        layers: dict[str, dict[str, list[list[dict]]]] = {}
        blocked: list[str] = []
        for position, run in enumerate(runs):
            if not isinstance(run, dict):
                self._unsupported(f"{relative}#runs[{position}]", "run is not an object")
                blocked.append(f"runs[{position}]")
                continue
            legacy_layer = run.get("layer")
            if not isinstance(legacy_layer, str) or EVIDENCE_TOOL_ID.fullmatch(legacy_layer) is None:
                self._unsupported(f"{relative}#runs[{position}]", f"malformed layer {legacy_layer!r}")
                blocked.append(f"runs[{position}]")
                continue
            planned = LEGACY_PLAN_LAYERS.get(legacy_layer, legacy_layer)
            executions, refusal = self._plan_executions(planned, run)
            if executions is None:
                self._unsupported(
                    f"{relative}#layers.{legacy_layer}", self._layer_refusal(legacy_layer, refusal)
                )
                blocked.append(legacy_layer)
                continue
            layers.setdefault(planned, {}).setdefault(legacy_layer, []).append(executions)

        if blocked:
            # Never a partial plan: one recorded layer missing from the plan
            # would let a later pyramid run report every declared layer green
            # while the verification the legacy manifest recorded never ran.
            self._plan_blocked = True
            self._unsupported(
                relative,
                f"layer(s) {', '.join(_dedup(blocked))} cannot be translated into "
                f"fv-verification-plan/v1 execution(s), see the {relative}#layers.* row(s): no "
                "partial plan is written, since a plan omitting a recorded layer would present "
                "unrun verification as complete",
            )
            return

        document_layers: dict[str, dict] = {}
        merged: list[tuple[str, int]] = []
        for planned in pyramid_run.plan_layer_order(layers):
            groups = layers[planned]
            executions = []
            for legacy_layer, recorded_runs in groups.items():
                runs_of_layer = len(recorded_runs)
                if runs_of_layer > 1:
                    merged.append((legacy_layer, runs_of_layer))
                for run_index, recorded in enumerate(recorded_runs, start=1):
                    total = len(recorded)
                    for index, execution in enumerate(recorded, start=1):
                        # `a; b; c` reports c's exit status, so one recorded
                        # run's result came from its last segment: that segment
                        # carries the bare layer id every migrated
                        # required_evidence entry names, and each earlier step
                        # gets a distinct id so one cohort never declares the
                        # same tool twice. Across two independently recorded
                        # runs there is no last-segment relation to inherit, so
                        # those ids name their run instead of pretending to be
                        # steps of one command.
                        if run_index == runs_of_layer and index == total:
                            tool = legacy_layer
                        elif runs_of_layer == 1:
                            tool = f"{legacy_layer}:{index}"
                        else:
                            tool = f"{legacy_layer}:run{run_index}.{index}"
                        entry = {
                            "argv": execution["argv"],
                            "cwd": execution["cwd"],
                            "timeout_seconds": execution["timeout_seconds"],
                            "evidence_tool": tool,
                        }
                        if execution["env"]:
                            entry["env"] = execution["env"]
                        executions.append(entry)
            required = True if self._required_layers is None else bool(
                set(groups) & self._required_layers
            )
            document_layers[planned] = {"required": required, "executions": executions}

        tools = [execution["evidence_tool"]
                 for layer in document_layers.values() for execution in layer["executions"]]
        repeated = sorted({tool for tool in tools if tools.count(tool) > 1})
        if repeated:
            # The runner keys per-tool results by this id, so two executions
            # sharing one would silently collapse into a single reported
            # result. Only a legacy layer named like a synthesized step id can
            # reach this, and inventing a suffix would name a tool no legacy
            # artifact does.
            self._plan_blocked = True
            self._unsupported(
                relative,
                f"evidence tool id(s) {', '.join(repeated)} would be declared by more than one "
                "execution: one id cannot stand for two recorded verifications, and the colliding "
                "legacy layer names must be resolved in the run manifest first",
            )
            return

        plan = {"schema": pyramid_run.PLAN_SCHEMA, "layers": document_layers}
        self._plan_write(".fv/verification-plan.json", canonical_json(plan))
        self._plan_tools = set(tools)
        for legacy_layer, runs_of_layer in merged:
            self._deviation(
                f"{relative}#layers.{legacy_layer}",
                ".fv/verification-plan.json",
                f"{runs_of_layer} independently recorded runs of layer {legacy_layer!r} are merged "
                "into one plan cohort: the legacy manifest states no relation between them, so "
                f"their executions are keyed {legacy_layer}:run<k>.<segment> and only the last "
                f"execution of the last recorded run carries the bare id {legacy_layer!r} that "
                "required_evidence names",
            )
        translated = ", ".join(
            f"{'+'.join(layers[planned])} -> {planned}" for planned in document_layers
        )
        custom = [planned for planned in document_layers if planned not in pyramid_run.PLAN_LAYERS]
        not_gating = [planned for planned, spec in document_layers.items() if not spec["required"]]
        detail = f"colosseum-layer-runs/v2 command strings translated to argv executions ({translated})"
        if custom:
            detail += (
                f"; {', '.join(custom)} declared as fv-verification-plan/v1 custom layer(s), having "
                "no built-in pyramid step of their own"
            )
        if not_gating:
            detail += (
                f"; {', '.join(not_gating)} written required: false, named by no migrated claim, so "
                "a failure there does not gate the pyramid verdict"
            )
        provenance = [f"{name}={document[name]!r}" for name in ("generated", "source_snapshot")
                      if isinstance(document.get(name), str)]
        statuses = [f"{run.get('layer')}={run.get('exit_status')}" for run in runs
                    if isinstance(run, dict) and "exit_status" in run]
        detail += (
            f"; translated from {relative}"
            + (f" ({', '.join(provenance)})" if provenance else "")
            + (f", recorded exit status(es) {', '.join(statuses)}" if statuses else "")
            + ", which fv-verification-plan/v1 has no field for: the recorded results are history, "
            "not evidence, and the plan declares only what to run"
        )
        self._mapped(relative, ".fv/verification-plan.json", detail)

    def _plan_executions(self, planned: str, run: dict) -> tuple[list[dict] | None, str]:
        """One recorded run as plan executions, or the refusal that blocks it."""
        if planned in pyramid_run.PLAN_RESERVED_LAYERS:
            return None, (
                f"plan layer id {planned!r} is reserved: the runner computes it from "
                ".fv/floors.json and rejects it as a declared layer"
            )
        if (
            planned not in pyramid_run.PLAN_LAYERS
            and pyramid_run.PLAN_CUSTOM_ID.fullmatch(planned) is None
        ):
            return None, f"plan layer id {planned!r} is not a usable {pyramid_run.PLAN_SCHEMA} layer id"
        cwd, refusal = self._plan_cwd(run.get("cwd"))
        if cwd is None:
            return None, refusal
        env, refusal = self._plan_env(run.get("environment"))
        if env is None:
            return None, refusal
        argvs, refusal = split_command(run.get("command"))
        if argvs is None:
            return None, refusal
        return [
            {"argv": argv, "cwd": cwd, "timeout_seconds": MIGRATED_TIMEOUT_SECONDS, "env": env}
            for argv in argvs
        ], ""

    def _layer_refusal(self, legacy_layer: str, refusal: str) -> str:
        """Why one untranslatable layer blocks the migration rather than being
        quietly left out of the plan."""
        if self._required_layers is not None and legacy_layer in self._required_layers:
            return (
                f"{refusal}: a migrated system claim requires {legacy_layer!r} evidence, and no plan "
                "execution can produce it"
            )
        return (
            f"{refusal}: no plan execution can carry layer {legacy_layer!r}, and a plan omitting a "
            "recorded layer would present unrun verification as complete"
        )

    # ---- history ---------------------------------------------------------

    def _preserve_history(self) -> None:
        classified = {artifact.source for artifact in self.artifacts}
        for relative in self._legacy_files:
            if relative in self._history_skip:
                continue
            data = self._read_bytes(relative)
            if data is None:
                continue
            # The executable bit is the one mode bit that changes what a
            # preserved file *is*: a legacy helper script arriving
            # non-executable is a history copy that cannot be replayed.
            try:
                executable = bool((self.project / relative).stat().st_mode & 0o111)
            except OSError:
                executable = False
            self._plan_write(self._history_path(relative), data,
                             mode=0o755 if executable else None)
            if relative not in classified:
                self._preserved(relative, "legacy history, byte-for-byte")

    # ---- completeness ----------------------------------------------------

    def _check_required_evidence(self) -> None:
        """Every tool a migrated claim requires must be producible by the plan.

        The no-omission rule already runs from the recorded layers to the
        plan. This is the other direction: a `system_claim` whose
        `required_evidence` names a tool no migrated execution declares is a
        claim the migrated project can never discharge, which is unrun
        verification presented as complete one artifact upstream.
        """
        if self._plan_blocked or not self._claim_layers:
            return
        claims_rel = f"{LEGACY_DIRNAME}/{LEGACY_CLAIMS}"
        produced = self._plan_tools or set()
        for claim_id, layers in self._claim_layers.items():
            missing = [layer for layer in layers if layer not in produced]
            if not missing:
                continue
            self._unsupported(
                f"{claims_rel}#claims.{claim_id}.required_evidence",
                f"required_evidence {missing} names no execution the migrated plan declares "
                + (
                    f"(the legacy tree records no {LEGACY_LAYER_RUNS}, so the plan declares "
                    "nothing at all)"
                    if self._plan_tools is None
                    else f"(declared evidence tools: {', '.join(sorted(produced))})"
                )
                + ": the migrated claim would require evidence no migrated run can produce, so "
                "the legacy manifests must agree on the tool's spelling, or the run manifest "
                "must record it, before the migration can be honest about coverage",
            )

    # ---- preflight -------------------------------------------------------

    def _preflight(self) -> None:
        self._preflight_staging()
        for path, write in sorted(self._writes.items()):
            destination = self.project / path
            symlinked = self._symlinked_component(path)
            if symlinked is not None:
                # Both `mkdir(parents=True)` and an open on the final name
                # follow symlinks, so a link anywhere on the path -- `.fv`
                # itself included -- is how a write lands outside the only
                # tree this migration may touch, or inside the legacy tree it
                # promises to leave byte-identical.
                self.conflicts.append(
                    f"{path}: {symlinked} is a symlink; a write through it would leave the .fv "
                    "tree this migration is allowed to write"
                )
                write.action = "conflict"
                continue
            unwritable = self._unwritable_ancestor(path)
            if unwritable is not None:
                self.conflicts.append(
                    f"{path}: {unwritable} is not writable, so this destination cannot be created"
                )
                write.action = "conflict"
                continue
            if destination.is_dir():
                self.conflicts.append(f"{path}: destination is a directory")
                write.action = "conflict"
                continue
            if not destination.exists():
                for parent in destination.parents:
                    if parent == self.project:
                        break
                    if parent.exists() and not parent.is_dir():
                        self.conflicts.append(
                            f"{path}: {parent.relative_to(self.project).as_posix()} is not a directory"
                        )
                        write.action = "conflict"
                        break
                continue
            try:
                current = destination.read_bytes()
                current_mode = destination.stat().st_mode & 0o7777
            except OSError as error:
                self.conflicts.append(f"{path}: destination is unreadable ({error})")
                write.action = "conflict"
                continue
            if current == write.data:
                write.action = "identical"
            elif write.adopt:
                # The one adopted destination: an existing dispatch keeps its
                # route and has only the two fields this migration owns
                # rewritten, so a project initialized before the migration is
                # migratable without moving the file aside. The replacement is
                # a staged inode, so the existing file's mode is carried over
                # deliberately: adopting two fields of a route an operator
                # narrowed must not widen it to the umask default, and a
                # failed apply already restores the mode exactly.
                write.action = "adopt"
                write.mode = current_mode
            else:
                self.conflicts.append(
                    f"{path}: exists with different content "
                    f"(have sha256:{sha256_bytes(current)}, would write sha256:{sha256_bytes(write.data)})"
                )
                write.action = "conflict"

    def _preflight_staging(self) -> None:
        """Refuse a staging prefix that cannot hold this run's bytes safely.

        `.fv/.migrate-staging` is a fixed name and every migrated byte is
        written through it before any destination sees it, so it is a write
        path in its own right: a symlink at it (or at `.fv`) routes the whole
        migration out of the only tree this tool may write, and an unwritable
        or non-directory prefix aborts the apply after the report has already
        promised a clean run. Both block here, with zero bytes written,
        exactly as a destination in the same shape does.
        """
        if not self._writes:
            return
        symlinked = self._symlinked_component(STAGING_RELATIVE)
        if symlinked is not None:
            self.conflicts.append(
                f"{STAGING_RELATIVE}: {symlinked} is a symlink; every migrated byte is staged "
                "under this prefix first, so a write through it would leave the .fv tree this "
                "migration is allowed to write"
            )
            return
        staging_root = self.project / STAGING_RELATIVE
        if staging_root.exists() and not staging_root.is_dir():
            self.conflicts.append(
                f"{STAGING_RELATIVE}: staging prefix exists and is not a directory, so no run "
                "can stage under it"
            )
            return
        # The run directory is what gets created, so the prefix itself is the
        # ancestor that has to be writable once it exists -- checking only its
        # parent would pass a prefix nothing can stage into.
        unwritable = self._unwritable_ancestor(f"{STAGING_RELATIVE}/run")
        if unwritable is not None:
            self.conflicts.append(
                f"{STAGING_RELATIVE}: {unwritable} is not writable, so this migration cannot "
                "stage its writes"
            )

    def _symlinked_component(self, path: str) -> str | None:
        """The first component of `path`, from the project root down, that is
        a symlink. A symlink to a directory answers `is_dir()`, so only this
        test keeps a write inside the real `.fv` tree."""
        current = self.project
        for part in Path(path).parts:
            current = current / part
            if current.is_symlink():
                return current.relative_to(self.project).as_posix()
        return None

    def _unwritable_ancestor(self, path: str) -> str | None:
        """The nearest existing ancestor directory of `path` that cannot be
        written, so the common permission failure blocks in preflight with
        zero writes instead of aborting halfway through an apply."""
        current = (self.project / path).parent
        while not current.exists() and current != self.project:
            current = current.parent
        if not current.exists() or not os.access(current, os.W_OK | os.X_OK):
            return current.relative_to(self.project).as_posix() or "."
        return None

    def build(self) -> None:
        self._scan()
        self.target_spec = self._migrate_intent()
        self._migrate_ledger()
        self._migrate_obligations()
        self._migrate_plan()
        # Both manifests are translated by now, so the claim-to-plan
        # direction of the no-omission rule can finally be checked.
        self._check_required_evidence()
        self._migrate_verified_inputs()
        self._migrate_dispatch(self.target_spec)
        self._preserve_history()
        self._preflight()

    # ---- results ---------------------------------------------------------

    @property
    def blocked(self) -> bool:
        return bool(self.unsupported or self.conflicts)

    def writes(self) -> list[PlannedWrite]:
        return [self._writes[path] for path in sorted(self._writes)]

    def apply(self) -> list[str]:
        """Write every pending destination, all of them or none of them.

        Every byte is first written into a staging tree under
        `.fv/.migrate-staging/<run>/`, so a failure while producing content
        touches no destination at all; the destinations are then moved into
        place with `os.replace`, which does not follow a symlink at the final
        component. A destination that already exists is moved aside into the
        same staging tree before the new bytes land, so putting it back is a
        rename of its own inode and restores its mode, ownership and
        timestamps along with its bytes -- none of which writing saved bytes
        into a fresh file reproduces. A failure during the moves puts back
        every destination already touched, so an interrupted apply cannot
        leave a half-migrated project, and each write's action records what
        actually happened to it.

        The staging prefix is fixed and structurally excluded from the
        verified-input snapshot, and each run stages under its own unique
        subdirectory of it: a hard kill between the first and the last move
        strands residue that no snapshot hashes and no other run reuses.
        Because the prefix is a fixed name, it is re-checked for containment
        here -- together with the run directory created under it -- before the
        first staged byte, so the "only `.fv` is written" invariant does not
        depend on nothing having replaced the prefix with a symlink since
        preflight looked.
        """
        if self.blocked:
            raise MigrationError("refusing to apply a blocked migration")
        pending = [write for write in self.writes() if write.action in ("create", "adopt")]
        if not pending:
            return []
        staging_root = self.project / STAGING_RELATIVE
        created: list[Path] = []
        touched: list[_Moved] = []
        current: PlannedWrite | None = None
        staging: Path | None = None
        try:
            # A unique subdirectory, not the pid: a pid recurs, so a killed
            # run's residue must never be a tree a later run stages into or
            # has to tell apart from its own.
            staging = self._make_run_directory(staging_root, created)
            for write in pending:
                current = write
                staged = staging / "new" / Path(write.path).relative_to(".fv")
                staged.parent.mkdir(parents=True, exist_ok=True)
                staged.write_bytes(write.data)
                if write.mode is not None:
                    os.chmod(staged, write.mode)
            for write in pending:
                current = write
                destination = self.project / write.path
                created.extend(self._make_dirs(destination.parent))
                self._guard_destination(destination)
                moved = _Moved(write, destination)
                touched.append(moved)
                if destination.is_file():
                    # Move the original inode aside rather than copy its
                    # bytes: the rename back is what returns the file's mode
                    # and the rest of its metadata with its content.
                    aside = staging / "saved" / Path(write.path).relative_to(".fv")
                    aside.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(destination, aside)
                    # Recorded only once the rename returned: an aside that
                    # failed left its destination exactly where it was, so the
                    # rollback must not be told it is holding an original it
                    # never took, which would report an intact file as lost
                    # and retain an empty staging tree for it forever.
                    moved.original = aside
                os.replace(staging / "new" / Path(write.path).relative_to(".fv"), destination)
                moved.landed = True
        except (OSError, MigrationError) as error:
            stranded, lost = self._rollback(touched)
            if not (stranded or lost):
                # Only a rollback that finished may drop the staging tree: it
                # holds the one copy of the original inode of every
                # destination this apply replaced.
                self._discard_staging(staging, staging_root)
            self._remove_created(created)
            landed = {moved.write.path for moved in touched if moved.landed}
            for write in pending:
                if write.path in stranded:
                    write.action = "written"
                elif write.path in lost:
                    write.action = "lost"
                elif write.path in landed:
                    write.action = "rolled-back"
                elif current is not None and write.path == current.path:
                    write.action = "failed"
                else:
                    write.action = "pending"
            raise MigrationError(
                f"{error}; every destination already written was rolled back"
                + (f", except {', '.join(sorted(stranded))}" if stranded else "")
                + (f"; no longer present: {', '.join(sorted(lost))}" if lost else "")
                + (f"; the originals this apply replaced are kept under {staging}"
                   if (stranded or lost) and staging is not None else "")
            ) from error
        self._discard_staging(staging, staging_root)
        for moved in touched:
            moved.write.action = "written"
        return [moved.write.path for moved in touched]

    @staticmethod
    def _make_dirs(directory: Path) -> list[Path]:
        """Create `directory` and report the components this call created, so
        a rollback removes exactly what the apply added and nothing else."""
        missing: list[Path] = []
        current = directory
        while not current.exists():
            missing.append(current)
            parent = current.parent
            if parent == current:
                break
            current = parent
        made: list[Path] = []
        for path in reversed(missing):
            path.mkdir()
            made.append(path)
        return made

    def _guard_destination(self, destination: Path) -> None:
        """Refuse a destination whose real parent is outside `.fv`.

        Preflight already rejects a symlinked path component; this is the
        same invariant enforced structurally at the moment of the write, so
        the "only `.fv` is written" guarantee does not rest on a string
        prefix and a check made earlier.
        """
        root = (self.project / ".fv").resolve()
        parent = destination.parent.resolve()
        if parent != root and root not in parent.parents:
            raise MigrationError(
                f"{destination}: resolved parent {parent} is outside {root}"
            )
        if destination.is_symlink():
            raise MigrationError(f"{destination}: destination became a symlink")

    def _guard_staging(self, path: Path) -> None:
        """Refuse a staging path that is a symlink or resolves outside `.fv`.

        Every migrated byte is written here before any destination sees it,
        so the staging prefix carries the same containment obligation as a
        destination -- and more exposure, because its name is fixed and
        therefore plantable long before a migration runs. `mkdir` and an
        ordinary open both follow a link, and `_make_dirs` treats an existing
        link to a directory as already created, so only this test keeps the
        staged bytes inside the real `.fv` tree.
        """
        root = (self.project / ".fv").resolve()
        shown = path.relative_to(self.project).as_posix()
        if path.is_symlink():
            raise MigrationError(
                f"{shown}: staging path is a symlink, so every migrated byte would be staged "
                f"outside {root}"
            )
        resolved = path.resolve()
        if resolved != root and root not in resolved.parents:
            raise MigrationError(
                f"{shown}: staging path resolves to {resolved}, outside {root}"
            )

    def _make_run_directory(self, staging_root: Path, created: list[Path]) -> Path:
        """This run's own staging subdirectory under the shared prefix.

        The prefix is shared by every concurrent migration of one project and
        each of them removes it once it is empty, so a sibling finishing
        between this run's `mkdir` and its `mkdtemp` is an ordinary race, not
        a failure: the prefix is recreated and the attempt repeated. A prefix
        that keeps vanishing is reported as the concurrent migration it is,
        with nothing written, rather than as `ENOENT` on a temp path nobody
        can map back to a cause.
        """
        for _ in range(STAGING_ATTEMPTS):
            self._guard_staging(staging_root)
            created.extend(self._make_dirs(staging_root))
            try:
                run = Path(tempfile.mkdtemp(prefix=f"{os.getpid()}-", dir=staging_root))
            except FileNotFoundError:
                continue
            # The prefix could have been swapped for a link between the guard
            # above and this call, in which case the directory just created is
            # real but sits somewhere else entirely.
            try:
                self._guard_staging(run)
            except MigrationError:
                try:
                    run.rmdir()
                except OSError:
                    pass  # nothing was staged into it; it is not ours to force
                raise
            return run
        raise MigrationError(
            f"{STAGING_RELATIVE}: another migration of this project removed the shared staging "
            f"prefix {STAGING_ATTEMPTS} times while this run was creating its own directory; "
            "nothing was written -- re-run once no other migration of it is in flight"
        )

    @staticmethod
    def _rollback(touched: list[_Moved]) -> tuple[set[str], set[str]]:
        """Put back every destination the apply already touched.

        Returns the paths whose new bytes could not be removed -- they stay
        in the report as `written` -- and the paths whose original could not
        be renamed back, which are absent and reported as `lost`. Neither
        set is emptied silently: the caller keeps the staging tree when
        either is non-empty, because it holds the only copy of the originals.
        """
        stranded: set[str] = set()
        lost: set[str] = set()
        for moved in reversed(touched):
            try:
                if moved.original is not None:
                    # A rename, not a rewrite: the destination gets its own
                    # inode back, so its mode, ownership and timestamps
                    # return with its bytes.
                    os.replace(moved.original, moved.destination)
                elif moved.landed:
                    moved.destination.unlink()
            except OSError:
                (stranded if moved.landed else lost).add(moved.write.path)
        return stranded, lost

    @staticmethod
    def _discard_staging(staging: Path | None, staging_root: Path) -> None:
        """Remove this run's staging tree, and the shared staging prefix once
        no concurrent run holds a directory under it."""
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)
        try:
            staging_root.rmdir()
        except OSError:
            pass  # a concurrent run still stages there, or it is already gone

    @staticmethod
    def _remove_created(created: list[Path]) -> None:
        """Remove the directories this apply created, deepest first. One that
        is not empty holds something the rollback could not undo, or a
        concurrent run's staging tree; either way it stays."""
        for directory in reversed(created):
            try:
                directory.rmdir()
            except OSError:
                pass  # not empty, or already gone with the staging tree

    def report(self, *, requested: str, applied: bool, error: str | None = None) -> dict:
        counts = {name: 0 for name in CLASSIFICATIONS}
        for artifact in self.artifacts:
            counts[artifact.classification] += 1
        return {
            "schema": REPORT_SCHEMA,
            # Repo-relative by construction: an absolute machine path in a
            # report an operator captures is exactly what the portability
            # rule keeps out of a persisted trust artifact. The human render
            # names the real directory.
            "project_root": ".",
            "mode": "apply" if applied else "dry-run",
            "requested_mode": requested,
            "applied": applied,
            "target_spec": self.target_spec,
            "status": "blocked" if self.blocked else "ok",
            "error": error,
            "counts": counts,
            "artifacts": [
                artifact.as_json()
                for artifact in sorted(self.artifacts, key=lambda item: (item.source, item.classification))
            ],
            "writes": [write.as_json() for write in self.writes()],
            "conflicts": sorted(self.conflicts),
            "unsupported": sorted(self.unsupported),
        }


def render_text(report: dict, root: str | None = None) -> str:
    actions: dict[str, int] = {}
    for write in report["writes"]:
        actions[write["action"]] = actions.get(write["action"], 0) + 1
    requested = report.get("requested_mode", report["mode"])
    mode = report["mode"] if requested == report["mode"] else f"{requested} requested, not applied"
    lines = [
        f"FV shadow migration ({mode}) of {root or report['project_root']}",
        f"  dispatch target: {report.get('target_spec') or 'none'}",
        "  classified: " + "  ".join(f"{name}={report['counts'][name]}" for name in CLASSIFICATIONS),
        "  writes: " + (
            "  ".join(f"{action}={count}" for action, count in sorted(actions.items())) or "none"
        ),
    ]
    for artifact in report["artifacts"]:
        # Bulk history is a count, not 174 lines of listing. A deviation row
        # (`<file>#<item>`) is what a reader has to see: it names the part of a
        # mapped file the translation did not carry across.
        if artifact["classification"] == PRESERVED and "#" not in artifact["source"]:
            continue
        arrow = f" -> {artifact['destination']}" if artifact["destination"] else ""
        lines.append(f"  [{artifact['classification']}] {artifact['source']}{arrow}")
        lines.append(f"      {artifact['detail']}")
    for write in report["writes"]:
        if write.get("detail"):
            lines.append(f"  [{write['action']}] {write['path']}")
            lines.append(f"      {write['detail']}")
    for label, entries in (("unsupported", report["unsupported"]), ("conflicts", report["conflicts"])):
        for entry in entries:
            lines.append(f"  [{label}] {entry}")
    if report.get("error"):
        lines.append(f"  [error] {report['error']}")
        lines.append("VERDICT: FAILED (see each write's action above; whatever the rollback "
                     "could not undo is named in the error)")
    elif report["status"] == "blocked":
        lines.append("VERDICT: BLOCKED (nothing written; resolve the entries above)")
    elif report["applied"]:
        lines.append("VERDICT: APPLIED")
    else:
        lines.append("VERDICT: OK (dry run; re-run with --apply to write)")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="fv_migrate.py",
        description="Shadow-migrate a legacy .colosseum project into .fv (dry run by default).",
    )
    parser.add_argument("project", metavar="PROJECT", help="project root holding .colosseum/")
    parser.add_argument("--apply", action="store_true",
                        help="write the migration; only .fv is written and .colosseum is never touched")
    parser.add_argument("--json", action="store_true",
                        help="emit the deterministic JSON report instead of the text report")
    args = parser.parse_args(argv)

    try:
        project = fv_project.resolve_project_root(args.project)
    except fv_project.ProjectError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2

    migration = Migration(project)
    try:
        migration.build()
    except MigrationError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    requested = "apply" if args.apply else "dry-run"
    applied = args.apply and not migration.blocked
    failure: str | None = None
    if applied:
        try:
            migration.apply()
        except (MigrationError, OSError) as error:
            # The report is the only enumeration of what landed and what did
            # not, so an apply failure prints it rather than replacing it
            # with one errno.
            failure = str(error)
            applied = False
    report = migration.report(requested=requested, applied=applied, error=failure)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(render_text(report, root=project.as_posix()))
    if failure is not None:
        print(f"ERROR: {failure}", file=sys.stderr)
        return 1
    if migration.blocked:
        if args.apply and not args.json:
            print("nothing was written: --apply refuses a blocked migration", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
