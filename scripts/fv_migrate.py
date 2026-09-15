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
    preserved-history
        every other regular file, byte-for-byte, under
        `.fv/history/colosseum/<path relative to .colosseum>`. That includes
        the legacy per-claim evidence under `.colosseum/evidence/`: a v1/v2
        record is history, and copying one into `.fv/evidence/` would present
        it as a live `fv-evidence-run/v3` record it cannot satisfy.
    unsupported
        a non-regular or unreadable file, an unknown or malformed legacy
        schema, a malformed claim, a legacy verification layer no plan
        execution can carry, or a destination that already exists with
        different content.

OBLIGATIONS
    Legacy `obligations.json` carries only `{claim_id, required}`; the
    dependency structure lives in `g1-claims.json`. The two are joined into one
    FV manifest: each legacy claim becomes a `system_claims` entry whose
    `depends_on` is its `required_targets` verbatim (a colon-bearing target is
    already a legal obligation id) and whose `required_evidence` is its
    `layers`. Each distinct target is synthesized as its own obligation:
    `proptest:`/`test`-prefixed targets are witnesses, every other prefix is an
    invariant. `scope`, `waiver`, `evidence_class`, `profile`, and
    `environment_policy` are retained rather than summarized.

VERIFICATION PLAN
    `colosseum-layer-runs/v2` records one shell string per layer. Only a simple
    semicolon-separated sequence of argv words is representable as an
    `fv-verification-plan/v1` execution list, so each segment is split with
    `shlex` and any shell operator or expansion character makes the layer
    unsupported — wrapping it back in `sh -c` would launder the shell the plan
    schema exists to exclude. Legacy names that have a pyramid equivalent are
    renamed to it (`proptest` -> `proptests`); every other legacy layer keys
    the plan under its own id, which `fv-verification-plan/v1` accepts as a
    custom layer, so `quint` migrates as the layer `quint` instead of being
    dropped. A recorded layer that cannot be translated at all — a command no
    argv represents, a cwd that is missing or escapes the root, a malformed
    environment, or an id the schema reserves (`floors`) — is unsupported and
    blocks the whole migration: a plan that silently omits a layer the legacy
    manifest recorded would present unrun verification as complete, so no
    partial plan is written.

VERIFIED INPUTS
    Legacy `verified-inputs.txt` is an include list: its entries name the paths
    in scope. `.fv/verified-inputs.txt` is an exclusion list, the exact
    opposite, and inverting an include list would mean enumerating the
    complement of the repository. The legacy list is therefore preserved as
    history and FV's conservative defaults are written instead.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shlex
import sys
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
# A required target the legacy manifest discharged with a test rather than a
# checked invariant becomes a witness.
WITNESS_PREFIXES = frozenset({"proptest", "proptests"})

# Any of these in a command segment means a shell, not an argv: redirection,
# pipes, substitution, globbing, grouping, background, or word expansion. The
# separator `;` is not listed because the segments are split on it first.
SHELL_CHARACTERS = frozenset("|&<>$`(){}[]*?~!\n\r\\\0")

VERIFIED_INPUTS_HEADER = (
    "# Verified-input exclusion prefixes for the FV evidence content snapshot.\n"
    "# Blank lines and # comments are ignored; directory prefixes end in /.\n"
    "#\n"
    "# Migrated from .colosseum/verified-inputs.txt, which was an include list:\n"
    "# its entries named the paths in scope, the opposite of what this file\n"
    "# means. Inverting an include list would mean enumerating the complement of\n"
    "# the repository, so the legacy list is kept verbatim as history at\n"
    "# .fv/history/colosseum/verified-inputs.txt and this file starts from FV's\n"
    "# conservative defaults. Imported history is excluded: those bytes are a\n"
    "# record of past runs, not an input any layer reads.\n"
)

OBLIGATIONS_NOTE = (
    "Migrated by scripts/fv_migrate.py. Each system claim is a legacy "
    "colosseum-g1-claims claim: depends_on is its required_targets, "
    "required_evidence is its layers. Invariants and witnesses are the "
    "synthesized required targets; no evidence record is migrated, so every "
    "obligation here is uncovered until a fv-evidence-run/v3 record binds it."
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

    def as_json(self) -> dict:
        return {"path": self.path, "action": self.action, "sha256": sha256_bytes(self.data)}


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


def split_command(command: str) -> tuple[list[list[str]] | None, str]:
    """Translate a legacy shell string into argv lists, or explain the refusal.

    Only a semicolon-separated sequence of plain argv words is representable:
    every other shell construct is rejected rather than re-wrapped in `sh -c`,
    which would reintroduce the shell the plan schema exists to exclude.
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
        self._writes: dict[str, PlannedWrite] = {}
        self._history_skip: set[str] = set()
        self._legacy_files: list[str] = []
        self._required_layers: set[str] | None = None

    # ---- bookkeeping -----------------------------------------------------

    def _mapped(self, source: str, destination: str, detail: str, *, verbatim: bool = False) -> None:
        self.artifacts.append(Artifact(source, MAPPED, destination, detail))
        if verbatim:
            # The bytes already survive at the mapped destination; a second
            # identical copy under history would preserve nothing new.
            self._history_skip.add(source)

    def _preserved(self, source: str, detail: str) -> None:
        self.artifacts.append(Artifact(source, PRESERVED, self._history_path(source), detail))

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

    def _plan_write(self, path: str, data: bytes) -> None:
        """Record intended bytes for one `.fv` destination."""
        if not path.startswith(".fv/"):
            raise MigrationError(f"refusing to write outside .fv: {path}")
        existing = self._writes.get(path)
        if existing is not None:
            if existing.data != data:
                raise MigrationError(f"two sources disagree about {path}")
            return
        self._writes[path] = PlannedWrite(path, data)

    # ---- inventory -------------------------------------------------------

    def _scan(self) -> None:
        if not self.legacy.is_dir() or self.legacy.is_symlink():
            raise MigrationError(f"{self.legacy}: no legacy .colosseum directory to migrate")

        def walk(directory: Path) -> None:
            for entry in sorted(directory.iterdir(), key=lambda item: item.name):
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

    def _ledger_intent(self) -> str | None:
        """The external intent the ledger cites, when it exists on disk.

        A legacy `.colosseum/intent.md` is frequently a pointer stub whose
        normative text lives elsewhere; migrating the stub as the dispatch
        target would bind evidence to a file that states nothing.
        """
        ledger = f"{LEGACY_DIRNAME}/{LEGACY_LEDGER}"
        if ledger not in self._legacy_files:
            return None
        try:
            text = (self.project / ledger).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        counts: dict[str, int] = {}
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
            counts[spec] = counts.get(spec, 0) + 1
        if not counts:
            return None
        # Most-cited wins; lexicographic order breaks a tie deterministically.
        return min(counts, key=lambda spec: (-counts[spec], spec))

    def _migrate_ledger(self) -> None:
        relative = f"{LEGACY_DIRNAME}/{LEGACY_LEDGER}"
        if relative not in self._legacy_files:
            return
        data = self._read_bytes(relative)
        if data is None:
            return
        self._plan_write(".fv/ledger.md", data)
        self._mapped(relative, ".fv/ledger.md", "legacy ledger, verbatim", verbatim=True)

    def _migrate_intent(self) -> str | None:
        """Choose the dispatch target and report how the legacy intent got there."""
        relative = f"{LEGACY_DIRNAME}/{LEGACY_INTENT}"
        present = relative in self._legacy_files
        external = self._ledger_intent()
        if external is not None:
            if present:
                self._mapped(
                    relative,
                    ".fv/dispatch.json",
                    f"ledger cites {external}, which exists: dispatch targets it instead of this "
                    "entrypoint; the entrypoint's bytes are preserved as history",
                )
            return external
        if not present:
            return None
        data = self._read_bytes(relative)
        if data is None:
            return None
        self._plan_write(".fv/intent.md", data)
        self._mapped(
            relative,
            ".fv/intent.md",
            "no ledger-cited external intent: this document becomes the dispatch target",
            verbatim=True,
        )
        return fv_project.DEFAULT_TARGET_SPEC

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
            if route.get("project_root") == "." and route.get("target_spec") == target_spec:
                # Already canonical. Re-serializing would rewrite a file this
                # migration did not author purely to change its formatting, so
                # the intended bytes are the bytes already there.
                self._plan_write(".fv/dispatch.json", existing)
                return
            route["project_root"] = "."
            route["target_spec"] = target_spec
            self._plan_write(".fv/dispatch.json", canonical_json(current))
            return
        config = json.loads((REPO / "scripts" / "dispatch.config.example.json").read_text())
        config["omp_native"]["project_root"] = "."
        config["omp_native"]["target_spec"] = target_spec
        self._plan_write(".fv/dispatch.json", canonical_json(config))

    # ---- verified inputs -------------------------------------------------

    def _migrate_verified_inputs(self) -> None:
        prefixes = [*fv_project.DEFAULT_EXCLUSIONS, HISTORY_EXCLUSION]
        body = "".join(f"{prefix}\n" for prefix in _dedup(prefixes))
        self._plan_write(".fv/verified-inputs.txt", (VERIFIED_INPUTS_HEADER + body).encode("utf-8"))
        relative = f"{LEGACY_DIRNAME}/{LEGACY_VERIFIED_INPUTS}"
        if relative in self._legacy_files:
            self._preserved(
                relative,
                "include list, semantically inverted from .fv/verified-inputs.txt: kept verbatim as "
                "history while FV's conservative exclusion defaults are written fresh",
            )

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
        system_claims: list[dict] = []
        required_layers: set[str] = set()

        for claim_id in ordered_ids:
            claim = detail_index.get(claim_id)
            if claim is None:
                self._unsupported(
                    f"{obligations_rel}#claims.{claim_id}",
                    f"required by {LEGACY_OBLIGATIONS} with no {LEGACY_CLAIMS} entry: its "
                    "depends_on and required_evidence cannot be derived",
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
            if claim_id in targets:
                self._unsupported(
                    f"{claims_rel}#claims.{claim_id}",
                    "required_targets names the claim itself: a system claim cannot depend on a claim",
                )
                continue
            for target in targets:
                prefix = target.split(":", 1)[0]
                bucket = witnesses if prefix in WITNESS_PREFIXES or prefix.startswith("test") else invariants
                bucket.setdefault(target, set()).add(claim_id)
            entry: dict = {"id": claim_id, "required": required_flags.get(claim_id, False)}
            scope = claim.get("scope")
            if isinstance(scope, dict) and isinstance(scope.get("statement"), str):
                entry["statement"] = scope["statement"]
            if isinstance(claim.get("evidence_class"), str):
                entry["evidence_class"] = claim["evidence_class"]
            entry["depends_on"] = targets
            entry["required_evidence"] = layers
            if isinstance(scope, dict):
                entry["scope"] = scope
            if isinstance(claim.get("waiver"), dict):
                entry["waiver"] = claim["waiver"]
            system_claims.append(entry)
            if entry["required"]:
                required_layers.update(layers)

        self._required_layers = required_layers
        collision = sorted(set(invariants) & set(witnesses))
        if collision:
            self._unsupported(
                f"{claims_rel}#claims",
                f"required target(s) {collision} classify as both invariant and witness",
            )
        if not system_claims:
            for relative, present in ((obligations_rel, has_obligations), (claims_rel, has_claims)):
                if present:
                    self._preserved(
                        relative,
                        "no legacy claim could be converted: kept as history, no obligation manifest "
                        "is written",
                    )
            return

        sources = [relative for relative, present in ((claims_rel, has_claims), (obligations_rel, has_obligations)) if present]
        migration: dict = {"source": sorted(sources), "note": OBLIGATIONS_NOTE}
        if isinstance(profile, str):
            migration["profile"] = profile
        if isinstance(environment_policy, str):
            migration["environment_policy"] = environment_policy
        manifest = {
            "version": 1,
            "invariants": [
                {"id": target, "statement": self._target_statement(target, claim_ids)}
                for target, claim_ids in sorted(invariants.items())
            ],
            "witnesses": [
                {
                    "id": target,
                    "name": target.split(":", 1)[1],
                    "statement": self._target_statement(target, claim_ids),
                }
                for target, claim_ids in sorted(witnesses.items())
            ],
            "system_claims": system_claims,
            "migration": migration,
        }
        self._plan_write(".fv/obligations.json", canonical_json(manifest))
        converted = ", ".join(entry["id"] for entry in system_claims)
        if has_claims:
            self._mapped(
                claims_rel,
                ".fv/obligations.json",
                f"{len(system_claims)} legacy claim(s) converted to system_claims ({converted}); "
                f"{len(invariants)} invariant(s) and {len(witnesses)} witness(es) synthesized from "
                "required_targets",
            )
        if has_obligations:
            self._mapped(
                obligations_rel,
                ".fv/obligations.json",
                "legacy required-claim set: contributes the `required` flag of each system claim",
            )

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
        document = self._read_json(relative)
        if document is None:
            return
        if not isinstance(document, dict):
            self._unsupported(relative, "document is not an object")
            return
        schema = document.get("schema")
        version = document.get("version")
        if schema != LAYER_RUNS_SCHEMA or version != LAYER_RUNS_VERSION:
            self._unsupported(
                relative,
                f"unknown run manifest {schema!r} version {version!r}, expected "
                f"{LAYER_RUNS_SCHEMA!r} version {LAYER_RUNS_VERSION}",
            )
            return
        runs = document.get("runs")
        if not isinstance(runs, list) or not runs:
            self._unsupported(relative, "runs is not a nonempty array")
            return

        layers: dict[str, dict[str, list[dict]]] = {}
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
            layers.setdefault(planned, {}).setdefault(legacy_layer, []).extend(executions)

        if blocked:
            # Never a partial plan: one recorded layer missing from the plan
            # would let a later pyramid run report every declared layer green
            # while the verification the legacy manifest recorded never ran.
            self._unsupported(
                relative,
                f"layer(s) {', '.join(_dedup(blocked))} cannot be translated into "
                f"fv-verification-plan/v1 execution(s), see the {relative}#layers.* row(s): no "
                "partial plan is written, since a plan omitting a recorded layer would present "
                "unrun verification as complete",
            )
            return

        document_layers: dict[str, dict] = {}
        for planned in pyramid_run.plan_layer_order(layers):
            groups = layers[planned]
            executions = []
            for legacy_layer, recorded in groups.items():
                total = len(recorded)
                for index, execution in enumerate(recorded, start=1):
                    # `a; b; c` reports c's exit status, so the layer's recorded
                    # result came from its last segment: that segment carries the
                    # bare layer id every migrated required_evidence entry names,
                    # and each earlier step gets a distinct id so one cohort never
                    # declares the same tool twice.
                    tool = legacy_layer if index == total else f"{legacy_layer}:{index}"
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

        plan = {"schema": pyramid_run.PLAN_SCHEMA, "layers": document_layers}
        self._plan_write(".fv/verification-plan.json", canonical_json(plan))
        translated = ", ".join(
            f"{'+'.join(layers[planned])} -> {planned}" for planned in document_layers
        )
        custom = [planned for planned in document_layers if planned not in pyramid_run.PLAN_LAYERS]
        detail = f"colosseum-layer-runs/v2 command strings translated to argv executions ({translated})"
        if custom:
            detail += (
                f"; {', '.join(custom)} declared as fv-verification-plan/v1 custom layer(s), having "
                "no built-in pyramid step of their own"
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
            self._plan_write(self._history_path(relative), data)
            if relative not in classified:
                self._preserved(relative, "legacy history, byte-for-byte")

    # ---- preflight -------------------------------------------------------

    def _preflight(self) -> None:
        for path, write in sorted(self._writes.items()):
            destination = self.project / path
            if destination.is_symlink():
                self.conflicts.append(f"{path}: destination is a symlink")
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
            except OSError as error:
                self.conflicts.append(f"{path}: destination is unreadable ({error})")
                write.action = "conflict"
                continue
            if current == write.data:
                write.action = "identical"
            else:
                self.conflicts.append(
                    f"{path}: exists with different content "
                    f"(have sha256:{sha256_bytes(current)}, would write sha256:{sha256_bytes(write.data)})"
                )
                write.action = "conflict"

    def build(self) -> None:
        self._scan()
        target_spec = self._migrate_intent()
        self._migrate_ledger()
        self._migrate_obligations()
        self._migrate_plan()
        self._migrate_verified_inputs()
        self._migrate_dispatch(target_spec)
        self._preserve_history()
        self._preflight()

    # ---- results ---------------------------------------------------------

    @property
    def blocked(self) -> bool:
        return bool(self.unsupported or self.conflicts)

    def writes(self) -> list[PlannedWrite]:
        return [self._writes[path] for path in sorted(self._writes)]

    def apply(self) -> list[str]:
        """Write every pending destination. Never called on a blocked run."""
        if self.blocked:
            raise MigrationError("refusing to apply a blocked migration")
        written: list[str] = []
        for write in self.writes():
            if write.action != "create":
                continue
            destination = self.project / write.path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(write.data)
            written.append(write.path)
        return written

    def report(self, mode: str) -> dict:
        counts = {name: 0 for name in CLASSIFICATIONS}
        for artifact in self.artifacts:
            counts[artifact.classification] += 1
        return {
            "schema": REPORT_SCHEMA,
            "project_root": self.project.as_posix(),
            "mode": mode,
            "status": "blocked" if self.blocked else "ok",
            "counts": counts,
            "artifacts": [
                artifact.as_json()
                for artifact in sorted(self.artifacts, key=lambda item: (item.source, item.classification))
            ],
            "writes": [write.as_json() for write in self.writes()],
            "conflicts": sorted(self.conflicts),
            "unsupported": sorted(self.unsupported),
        }


def render_text(report: dict) -> str:
    actions: dict[str, int] = {}
    for write in report["writes"]:
        actions[write["action"]] = actions.get(write["action"], 0) + 1
    lines = [
        f"FV shadow migration ({report['mode']}) of {report['project_root']}",
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
    for label, entries in (("unsupported", report["unsupported"]), ("conflicts", report["conflicts"])):
        for entry in entries:
            lines.append(f"  [{label}] {entry}")
    if report["status"] == "blocked":
        lines.append("VERDICT: BLOCKED (nothing written; resolve the entries above)")
    elif report["mode"] == "apply":
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

    applied = args.apply and not migration.blocked
    if applied:
        try:
            migration.apply()
        except (MigrationError, OSError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 1
    report = migration.report("apply" if applied else "dry-run")
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(render_text(report))
    if migration.blocked:
        if args.apply and not args.json:
            print("nothing was written: --apply refuses a blocked migration", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
