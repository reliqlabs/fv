#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
coverage_dashboard — a per-claim coverage view over G1 evidence records
(M1; contracts G1/G2).

Gate B (`check_evidence_records.py`) answers one question per run: does
every required claim PASS. This tool answers the question underneath
that one: for each required claim, what evidence backs it, at what
evidence_class, with what result, waived or not — and which required
claims have no record at all. It is a read-only view, not a gate: it
renders the same G1 records Gate B would consume and computes the same
G2 verdict, but its purpose is visibility into coverage, not enforcement.

RECORD SCHEMA — Gate B's own, imported from it. `check_evidence_records`
is loaded as a sibling module and its field lists, enums, obligation/class
compatibility table, v3 cohort shape and record-level rules are used
directly, so the two tools cannot drift into two schemas. What the
dashboard applies is every Gate B rule that needs no repository access:
field presence, enum membership, waiver attribution, obligation/class
compatibility (record level and per execution), the v3 cohort's structure,
the legacy bindings' derivation from `executions[0]`, the `+dirty` PASS
rejection, the producer profile and manifest-matching `required_targets`
a cohort-schema record must declare, the obligation manifest a record is
bound to, and cross-claim raw-artifact identity across the whole required
set.

Two of those bind only when `--manifest` names the manifest the run is
judged against, exactly as in Gate B: the `required_targets` comparison,
and the `obligation_manifest_hash` check, whose expectation is that
manifest's own bytes (`check_evidence_records.manifest_binding`). Under
`--require` alone there is no declared obligation set, so neither binds and
no obligation kind is known either — the same three blind spots Gate B has
when it is given `--require` and no manifest. Gate B additionally accepts
`--expect-manifest` to pin that hash by hand; this tool always derives it,
since a coverage view has no reason to be told what the manifest it was
handed hashes to.

A pre-cohort (v2) record is exempt from the cohort-schema rules and from
artifact identity, the same carve-out Gate B makes, and its own `profile`
string reaches the verdict scope verbatim in both tools — the producer
profile is pinned for cohort-schema records only.

The artifact reads — path containment, raw-output digest recomputation,
PASS markers — need the repository root Gate B resolves, and so does
snapshot and intent freshness, which is recomputed against the current
tree. Those are the gate's alone: a record may therefore be INCOMPLETE
there and PASS here, which this tool discloses as its `not-recomputed`
binding mode in the payload and the summary line. That asymmetry is the
only one; the reverse —
covered here, rejected there — is what the shared rules and the shared
manifest grammar rule out.

This tool additionally accepts the M5 forward-compat versioned envelope: a
top-level JSON object carrying a `records` key, e.g.
`{"ledger_schema_version": "...", "records": [...]}`.
A bare list or a bare single record object is treated as unversioned.

OBLIGATION KINDS AND SYSTEM CLAIMS

An obligation manifest declares three collections: `invariants`,
`witnesses`, and `system_claims`. All three contribute required claim
IDs, so a system claim is a first-class row here and is never dropped
from the required set — a coverage view that silently omitted the claims
spanning several tools would report the highest-level trust claims in
the project as covered by omission.

A system claim additionally declares:
    depends_on         invariant/witness IDs it rests on
    required_evidence  tool/layer IDs its evidence cohort must contain

and its record's `bindings.executions` cohort (v3) names the tool and
result of each execution behind it. Per the same rule Gate B applies, a
system claim is covered only when every `required_evidence` tool ID
appears among executions whose result is PASS. Two coverage gaps are
therefore visible here that no single-record view can express:

    evidence-gap     some required_evidence tool never PASSed in the
                     cohort (it failed, was INCOMPLETE, or never ran at
                     all — including a v2 record that carries no cohort),
                     or some execution in the cohort did not PASS even
                     though the required tools did: a cohort is atomic, so
                     a non-PASS or unreadable execution beside the required
                     ones is still a gap. The atomicity half applies to
                     every record that carries a cohort, not only to system
                     claims: an invariant whose record PASSes over a
                     FAILing execution is the same unearned coverage, and
                     Gate B rejects it as an invalid record
    dependency-gap   the record and its whole cohort PASS, but an
                     invariant or witness the claim depends_on is not
                     itself covered in this run

Both are gaps, so both land in the INCOMPLETE bucket and the INCOMPLETE
verdict, exactly like a missing record. Dependencies the run did not
evaluate (a `--require` subset that omits them) are reported as
not-evaluated rather than counted either way. Manifest validation itself
belongs to Gate B; this tool assumes a validated manifest and re-reads
only the stable IDs, each ID's kind, and each system claim's
depends_on/required_evidence. When it cannot read those, it exits ERROR
instead of rendering a partial required set.

G2 HONESTY (this tool's own conformance obligation)

Per G2, "VERIFIED" is never a bare token; it always carries a scope,
e.g. `VERIFIED[profile=bounded]`. The scope stays the profile alone, the
same token this view has always emitted, because `binding` is a Gate B
wire field: minting a value of it here would read as a freshness
discipline this tool never runs. What this view did *not* do is stated
where it cannot be mistaken for that field. The `bindings:` summary line
and the payload's own `binding` key both say `not-recomputed`, since it
reads records and never recomputes the verified-input snapshot or the
intent hash. Individual claim rows never
render as "verified" either — a claim's row shows its evidence_class and
result (PASS/FAIL/INCOMPLETE/missing-record/duplicate-record/invalid/
unwaived-assumption/evidence-gap/dependency-gap), never an unqualified
verdict word. `--check` scans this tool's own rendered output (table,
verdict banner, and JSON payload) and exits nonzero if a bare `VERIFIED`
(not immediately followed by `[`) would ever appear — the R26-style
self-conformance guarantee applied to the dashboard surface itself.

VERDICT (same G2 truth table as check_evidence_records.py; exit code)
    FAILED       (1)  any required claim has a valid record with result FAIL
    INCOMPLETE   (3)  any required claim is missing a record or has two or
                      more records, or its record is invalid, or its record
                      result is INCOMPLETE, or it rests on externally-assumed
                      or unverified evidence — at the record level or in any
                      cohort execution — without a waiver, or it is a system
                      claim with an evidence or dependency gap, or the
                      required-claims list is empty
    VERIFIED[..] (0)  every required claim PASSes; scope names the profile,
                      the payload names the binding mode, and every waived
                      claim is listed
    ERROR        (2)  unreadable records/manifest, a manifest whose claim
                      IDs cannot be read or that declares an obligation ID
                      the evidence producer could never write a record for,
                      a --require ID absent from the given manifest, or
                      neither --require nor --manifest

USAGE
    coverage_dashboard.py --records <file.json|dir> \\
        --require B1,B2,W1 [--json]
    coverage_dashboard.py --records <file.json|dir> \\
        --manifest <obligations.json> [--json]
    coverage_dashboard.py --records <file.json|dir> --require B1,W1 --check

--require names the claim IDs the active profile requires (or pass
--manifest <obligations.json> to derive them from an E3 obligation
manifest's invariant/witness/system_claim IDs). Passing both narrows the
run to the named subset while keeping the manifest's obligation kinds and
system-claim cohort requirements, so a system claim named by --require is
still judged against its required_evidence. --json prints the structured
dashboard to stdout with nothing else on stdout; text mode prints a
readable table to stdout. In both modes the verdict banner goes to stderr
only. --check runs in self-conformance mode: it prints CHECK: ... to
stderr and exits 0 if the rendered output is clean, 1 if a bare VERIFIED
leaked.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_evidence_records as gate  # noqa: E402  sibling Gate B: one schema, not two

# Gate B's schema, read rather than restated. A record shape the gate rejects
# structurally must never render as covered here, and the only way to keep
# that true across future edits is to share the definitions.
EVIDENCE_CLASSES = gate.EVIDENCE_CLASSES
RESULTS = gate.RESULTS
TOP_FIELDS = gate.TOP_FIELDS
BINDING_FIELDS = gate.BINDING_FIELDS
NULLABLE = gate.NULLABLE  # keys whose value may be null (the key stays mandatory)
EVIDENCE_SCHEMA_V3 = gate.EVIDENCE_SCHEMA_V3
V3_BINDING_FIELDS = gate.V3_BINDING_FIELDS
EXECUTION_FIELDS = gate.EXECUTION_FIELDS
EVIDENCE_TOOL_ID = gate.EVIDENCE_TOOL_ID
OBLIGATION_EVIDENCE_COMPATIBILITY = gate.OBLIGATION_EVIDENCE_COMPATIBILITY
# Manifest collections, in the order their IDs join the required set.
OBLIGATION_COLLECTIONS = gate.OBLIGATION_COLLECTIONS

ASSUMED_CLASSES = gate.ASSUMED_CLASSES
# Producer records name their artifacts by claim and run id; Gate B holds them
# to it, so the dashboard must read the same rule or it would cover a record
# the gate rejects for artifact substitution.
PRODUCER_PROFILE = gate.PRODUCER_PROFILE
PRODUCER_ARTIFACT = gate.PRODUCER_ARTIFACT

SYSTEM_CLAIM = "system_claim"
# Observed cohort result for a required_evidence tool that never ran.
NO_EXECUTION = "no-execution"
# Freshness discipline this tool reports in its payload and summary line, but
# never in the verdict scope: Gate B's scope field carries recomputed|pinned|
# unbound, and the dashboard recomputes nothing, so it states a mode of its own
# outside that field rather than borrowing one that would overstate the check.
BINDING_MODE = "not-recomputed"

# Per-claim statuses that mean the claim is not covered by a passing
# record. Drives both the run verdict and the "incomplete" summary bucket.
GAP_STATUSES = {"missing-record", "duplicate-record", "invalid", "INCOMPLETE",
                "unwaived-assumption", "evidence-gap", "dependency-gap"}

UNSCOPED_VERDICT_RE = re.compile(r"VERIFIED(?!\[)")  # a bare, unqualified verdict


class ManifestError(Exception):
    """The manifest cannot yield a required-claim set this tool may render."""


def _execution_state(record: dict) -> dict:
    """Cross-execution state a cohort is judged against: one tool and one
    artifact per execution, plus the producer-naming rule when the record
    claims the producer profile."""
    bindings = record["bindings"]
    return {
        "claim_id": record["claim_id"],
        "producer": bindings.get("profile") == PRODUCER_PROFILE,
        "seen_tools": set(),
        "seen_paths": {},
    }


def _execution_defects(execution: object, index: int, state: dict,
                       obligation_kind: str | None) -> list[str]:
    """One v3 cohort entry, by the rules that need no repository access.

    Mirrors check_evidence_records._execution_defects minus the artifact read
    (containment, digest recomputation, PASS marker), which needs the repo root
    the gate resolves. Adds nothing the gate does not also apply."""
    label = f"executions[{index}] "
    if not isinstance(execution, dict):
        return [f"{label}is not an object"]
    missing = [field for field in EXECUTION_FIELDS if field not in execution]
    if missing:
        return [f"{label}missing field {field!r}" for field in missing]
    defects: list[str] = []
    tool = execution["tool"]
    if not isinstance(tool, str) or EVIDENCE_TOOL_ID.fullmatch(tool) is None:
        defects.append(f"{label}malformed evidence tool id {tool!r}")
    elif tool in state["seen_tools"]:
        defects.append(f"{label}duplicate evidence tool {tool!r}: "
                       "cohort coverage is ambiguous")
    else:
        state["seen_tools"].add(tool)
    klass = execution["evidence_class"]
    if klass not in EVIDENCE_CLASSES:
        defects.append(f"{label}unknown evidence_class {klass!r}")
    elif obligation_kind is not None:
        # The record's declared class says nothing about the strength of the
        # artifact behind each execution; an invariant discharged by a
        # witness-only execution is the record class lying about the cohort.
        compatible = OBLIGATION_EVIDENCE_COMPATIBILITY.get(obligation_kind)
        if compatible is None or klass not in compatible:
            defects.append(f"{label}incompatible evidence class {klass!r} "
                           f"for obligation kind {obligation_kind!r}")
    command = execution["command"]
    if (not isinstance(command, list) or not command
            or any(not isinstance(part, str) or not part for part in command)):
        defects.append(f"{label}command is not a nonempty argv array of "
                       f"nonempty strings: {command!r}")
    cwd = execution["cwd"]
    if not isinstance(cwd, str) or not cwd.strip():
        defects.append(f"{label}cwd is not a repo-relative path: {cwd!r}")
    if not gate._valid_toolchain(execution["toolchain_digests"]):
        defects.append(f"{label}lacks resolved executable identity")
    result = execution["result"]
    if result not in RESULTS:
        defects.append(f"{label}unknown result {result!r}")
    # A non-PASS execution beneath a PASS record is Gate B's defect and this
    # tool's `evidence-gap` status: same verdict, but the row keeps naming the
    # execution that did not pass instead of collapsing to "invalid".
    run_id = execution["run_id"]
    if not isinstance(run_id, str) or not run_id.strip():
        defects.append(f"{label}run_id is empty")
    raw_relative = execution["raw_output_path"]
    if isinstance(raw_relative, str) and raw_relative:
        # One artifact per execution, and — for producer records — the artifact
        # this execution's run id names. Without both, one PASS log discharges
        # a whole cohort.
        first = state["seen_paths"].setdefault(raw_relative, index)
        if first != index:
            defects.append(f"{label}raw_output_path {raw_relative!r} duplicates "
                           f"executions[{first}]: one artifact cannot discharge "
                           "two executions")
        if state["producer"] and isinstance(run_id, str):
            expected = PRODUCER_ARTIFACT.format(claim_id=state["claim_id"],
                                                run_id=run_id)
            if raw_relative != expected:
                defects.append(f"{label}raw_output_path {raw_relative!r} is not "
                               f"this run's producer artifact {expected!r}")
    marker = execution.get("pass_marker")
    if "pass_marker" in execution and (not isinstance(marker, str) or not marker):
        defects.append(f"{label}pass_marker is empty")
    return defects


def _derivation_defects(bindings: dict, primary: dict) -> list[str]:
    """The legacy record-level bindings must be executions[0]'s, verbatim.

    Same rule as check_evidence_records._cohort_defects: a record whose legacy
    half describes a different run than its cohort reads as two different
    claims depending on which half a consumer trusts."""
    defects: list[str] = []
    if (bindings.get("raw_output_path") != primary.get("raw_output_path")
            or bindings.get("raw_output_hash") != primary.get("raw_output_hash")):
        defects.append("legacy raw-output bindings are not derived from executions[0]")
    command = bindings.get("command")
    if isinstance(command, str):
        try:
            command = json.loads(command)
        except json.JSONDecodeError:
            command = None
    if command != primary.get("command"):
        defects.append("legacy command binding is not derived from executions[0]")
    configuration = bindings.get("configuration")
    declared_cwd = configuration.get("cwd") if isinstance(configuration, dict) else None
    if declared_cwd != primary.get("cwd"):
        defects.append("legacy configuration.cwd binding is not derived from executions[0]")
    declared_marker = (configuration.get("pass_marker")
                       if isinstance(configuration, dict) else None)
    if declared_marker != primary.get("pass_marker"):
        defects.append("legacy configuration.pass_marker binding is not derived "
                       "from executions[0]")
    return defects


def validate_record(rec: object, obligation_kind: str | None = None,
                    expect_required_targets: tuple[str, ...] | None = None,
                    expect_manifest: str | None = None) -> list[str]:
    """Structural defects per the G1 schema, using check_evidence_records'
    own constants and rules. Empty list means the record is structurally
    sound as far as a view without repository access can tell.

    `expect_required_targets` is the manifest's complete obligation set and
    `expect_manifest` is that manifest's content hash, both threaded in by the
    caller: a cohort-schema record's own `required_targets`, and any record's
    own `obligation_manifest_hash`, are assertions until something compares
    them to the manifest the run is judged against."""
    if not isinstance(rec, dict):
        return ["record is not an object"]
    defects = [f"missing field {field!r}" for field in TOP_FIELDS if field not in rec]
    if defects:
        return defects
    if not isinstance(rec["claim_id"], str) or not rec["claim_id"]:
        defects.append("claim_id is empty")
    if not isinstance(rec["required"], bool):
        defects.append("required is not boolean")
    if rec["evidence_class"] not in EVIDENCE_CLASSES:
        defects.append(f"unknown evidence_class {rec['evidence_class']!r}")
    if rec["result"] not in RESULTS:
        defects.append(f"unknown result {rec['result']!r}")
    if not isinstance(rec["scope"], str) or not rec["scope"].strip():
        defects.append("scope is empty")
    defects.extend(gate._waiver_defects(rec["waiver"]))
    bindings = rec["bindings"]
    if not isinstance(bindings, dict):
        defects.append("bindings is not an object")
        return defects
    schema_v3 = gate.is_schema_v3(rec)
    for field in BINDING_FIELDS + (V3_BINDING_FIELDS if schema_v3 else ()):
        if field not in bindings:
            defects.append(f"missing binding field {field!r}")
        elif bindings[field] in ("", [], {}) or \
                (bindings[field] is None and field not in NULLABLE):
            defects.append(f"empty binding field {field!r}")
    defects.extend(gate._asserted_field_defects(bindings, schema_v3))
    if bindings.get("profile") == PRODUCER_PROFILE and not gate._valid_toolchain(
            bindings.get("toolchain_digests")):
        defects.append("producer evidence lacks resolved executable identity")
    if defects:
        return defects
    # Record-text rules that need no repository access, so the gate's verdict on
    # them is reproducible here: a snapshot the producer watched move cannot carry
    # a PASS, a record bound to another obligation manifest is stale against this
    # run's, and a cohort-schema record is producer-written by construction.
    defects.extend(gate.dirty_snapshot_defects(rec))
    defects.extend(gate.manifest_binding_defects(bindings, expect_manifest))
    if schema_v3:
        defects.extend(gate.v3_producer_defects(bindings, expect_required_targets))
    if obligation_kind is not None:
        compatible = OBLIGATION_EVIDENCE_COMPATIBILITY.get(obligation_kind)
        if compatible is None or rec["evidence_class"] not in compatible:
            defects.append(f"incompatible evidence class {rec['evidence_class']!r} "
                           f"for obligation kind {obligation_kind!r}")
    if not schema_v3:
        return defects
    executions = bindings.get("executions")
    if not isinstance(executions, list) or not executions:
        defects.append("bindings.executions is not a nonempty array")
        return defects
    state = _execution_state(rec)
    cohort_defects: list[str] = []
    for index, execution in enumerate(executions):
        cohort_defects.extend(_execution_defects(execution, index, state,
                                                 obligation_kind))
    if cohort_defects:
        return defects + cohort_defects
    return defects + _derivation_defects(bindings, executions[0])


def unwrap(data: object) -> list[dict]:
    """A bare list/object is unversioned. An object carrying a `records`
    key is the M5 versioned envelope; unwrap it. Either way, return a
    flat list of record objects."""
    if isinstance(data, dict) and "records" in data:
        data = data["records"]
    if isinstance(data, list):
        return data
    return [data]


def load_records(path: Path) -> list[dict]:
    if path.is_dir():
        records = []
        for p in sorted(path.glob("*.json")):
            records.extend(unwrap(json.loads(p.read_text())))
        return records
    return unwrap(json.loads(path.read_text()))


def _id_list(claim_id: str, field: str, value: object) -> list[str]:
    """The nonempty ID list a system claim declares, deduplicated in declared
    order. Gate B rejects malformed and duplicate entries; the dashboard only
    needs to refuse to guess when the field is unreadable."""
    if not isinstance(value, list) or not value:
        raise ManifestError(
            f"system_claim {claim_id!r}: {field} is not a nonempty array")
    ids: list[str] = []
    for entry in value:
        if not isinstance(entry, str) or not entry.strip():
            raise ManifestError(
                f"system_claim {claim_id!r}: {field} contains a malformed id {entry!r}")
        if entry not in ids:
            ids.append(entry)
    return ids


def load_manifest(path: Path) -> tuple[list[str], dict[str, str], dict[str, dict]]:
    """Required claim IDs, each ID's obligation kind, and each system claim's
    depends_on/required_evidence — read from all three obligation collections.

    Gate B owns manifest validation. This reader duplicates none of it beyond
    what a coverage view must know, but it raises rather than skipping a
    collection or an entry it cannot read: silently dropping a system claim
    would understate the required set and overstate coverage.
    """
    manifest = json.loads(path.read_text())
    if not isinstance(manifest, dict):
        raise ManifestError("manifest is not an object")
    required: list[str] = []
    kinds: dict[str, str] = {}
    system_claims: dict[str, dict] = {}
    for collection, kind in OBLIGATION_COLLECTIONS:
        entries = manifest.get(collection, [])
        if not isinstance(entries, list):
            raise ManifestError(f"{collection} is not an array")
        for index, item in enumerate(entries):
            claim_id = item.get("id") if isinstance(item, dict) else None
            if not isinstance(claim_id, str) or not claim_id.strip():
                raise ManifestError(
                    f"{collection}[{index}] declares no usable id")
            # Gate B's two id grammars, read from it: an id outside the obligation
            # grammar is malformed, and an id outside the producer's claim_id
            # grammar could never have a record written for it. Gate B makes both
            # an ERROR, so a manifest it refuses to load cannot render here as a
            # required set with missing-record rows.
            if gate.OBLIGATION_ID.fullmatch(claim_id) is None:
                raise ManifestError(
                    f"{collection}[{index}] has malformed id {claim_id!r}")
            if gate.PRODUCER_CLAIM_ID.fullmatch(claim_id) is None:
                raise ManifestError(
                    f"{collection}[{index}] id {claim_id!r} is not usable by the "
                    "evidence producer: obligation ids must match "
                    "[A-Za-z0-9][A-Za-z0-9._-]*")
            if claim_id in kinds:
                raise ManifestError(
                    f"duplicate obligation id {claim_id!r} in {collection} "
                    f"(already declared as {kinds[claim_id]})")
            required.append(claim_id)
            kinds[claim_id] = kind
            if kind == SYSTEM_CLAIM:
                system_claims[claim_id] = {
                    "depends_on": _id_list(claim_id, "depends_on",
                                           item.get("depends_on")),
                    "required_evidence": _id_list(claim_id, "required_evidence",
                                                  item.get("required_evidence")),
                }
    return required, kinds, system_claims


def executions_of(rec: dict) -> list[dict] | None:
    """The record's v3 evidence cohort as tool/result/evidence_class triples,
    or None when the record carries no `bindings.executions` at all (a v2
    record, still accepted, but unable to demonstrate cohort coverage).

    An entry whose shape cannot be read keeps its slot with null fields. It is
    an invalid execution, never an absent one: dropping it would hide the very
    cohort member Gate B rejects the record for."""
    bindings = rec.get("bindings")
    raw = bindings.get("executions") if isinstance(bindings, dict) else None
    if not isinstance(raw, list):
        return None
    cohort = []
    for index, entry in enumerate(raw):
        fields = entry if isinstance(entry, dict) else {}
        readable = {field: value if isinstance(value, str) else None
                    for field, value in (
                        ("tool", fields.get("tool")),
                        ("result", fields.get("result")),
                        ("evidence_class", fields.get("evidence_class")))}
        cohort.append({"index": index, **readable})
    return cohort


def non_passing_executions(cohort: list[dict] | None) -> list[str]:
    """Every cohort entry that did not PASS, named by tool id, or by position
    when the entry itself is unreadable.

    A cohort is atomic: one execution that did not PASS defeats the record it
    sits under, whether or not the claim's required tools are covered without
    it, and an entry whose tool or result cannot be read is not a passing one.
    Gate B rejects both shapes outright; here they surface as a named gap."""
    names: list[str] = []
    for entry in cohort or []:
        if entry["tool"] is not None and entry["result"] == "PASS":
            continue
        names.append(entry["tool"] or f"executions[{entry['index']}]")
    return names


def cohort_coverage(
    required_evidence: list[str], cohort: list[dict] | None
) -> tuple[dict[str, str], list[str]]:
    """Observed result per required tool ID, and the required tool IDs with no
    PASS behind them.

    A tool that ran more than once counts as covered if any of its executions
    PASSed; a tool that never ran reads as no-execution. Entries whose tool id
    is unreadable cannot cover anything, so they are left out here and reported
    by non_passing_executions instead.
    """
    observed: dict[str, list[str | None]] = {}
    for entry in cohort or []:
        if entry["tool"] is None:
            continue
        observed.setdefault(entry["tool"], []).append(entry["result"])
    coverage: dict[str, str] = {}
    gaps: list[str] = []
    for tool in required_evidence:
        results = observed.get(tool)
        if results is None:
            coverage[tool] = NO_EXECUTION
        elif "PASS" in results:
            coverage[tool] = "PASS"
        else:
            coverage[tool] = next((r for r in results if r), "unknown")
        if coverage[tool] != "PASS":
            gaps.append(tool)
    return coverage, gaps


def evaluate_claim(cid: str, by_claim: dict[str, dict],
                   kinds: dict[str, str] | None = None,
                   system_claims: dict[str, dict] | None = None,
                   duplicates: frozenset[str] | set[str] = frozenset(),
                   expect_required_targets: tuple[str, ...] | None = None,
                   expect_manifest: str | None = None,
                   cited: dict[str, set[str]] | None = None) -> dict:
    kinds = kinds or {}
    system_claims = system_claims or {}
    kind = kinds.get(cid)
    rec = by_claim.get(cid)
    cohort: list[dict] | None = None
    assumed: list[str] = []
    if cid in duplicates:
        # Gate B refuses to pick a winner between two records for one claim,
        # and a view that silently rendered the last one would report coverage
        # the gate calls ambiguous.
        row = {"claim_id": cid, "status": "duplicate-record",
               "evidence_class": None, "result": None, "scope": None,
               "waived": False,
               "defects": ["duplicate records for claim_id (ambiguous)"]}
    elif rec is None:
        row = {"claim_id": cid, "status": "missing-record", "evidence_class": None,
               "result": None, "scope": None, "waived": False, "defects": []}
    else:
        cohort = executions_of(rec)
        defects = validate_record(rec, kind, expect_required_targets,
                                  expect_manifest)
        # One artifact cannot discharge two claims. The rule spans records, so it
        # is the caller's index that decides it, not this record's own bindings.
        defects.extend(gate.shared_artifact_defects(cid, rec, cited or {}))
        if defects:
            row = {"claim_id": cid, "status": "invalid",
                   "evidence_class": rec.get("evidence_class"),
                   "result": rec.get("result"), "scope": rec.get("scope"),
                   "waived": False, "defects": defects}
        else:
            klass, result, scope = rec["evidence_class"], rec["result"], rec["scope"]
            waived = bool(rec["waiver"])
            # The assumption rule quantifies over the whole cohort: a record
            # declaring a strong class cannot launder an unverified or
            # externally-assumed execution into a PASS.
            for entry in cohort or []:
                if entry["evidence_class"] not in ASSUMED_CLASSES:
                    continue
                name = entry["tool"] or f"executions[{entry['index']}]"
                assumed.append(f"{name}={entry['evidence_class']}")
            if result == "FAIL":
                status = "FAIL"
            elif result == "INCOMPLETE":
                status = "INCOMPLETE"
            elif (klass in ASSUMED_CLASSES or assumed) and not waived:
                status = "unwaived-assumption"
            else:
                status = "PASS"
            row = {"claim_id": cid, "status": status, "evidence_class": klass,
                   "result": result, "scope": scope, "waived": waived,
                   "defects": []}
    row["obligation_kind"] = kind
    row["executions"] = cohort
    row["assumed_executions"] = assumed
    row["non_passing_executions"] = non_passing_executions(cohort)
    # Cohort atomicity is not a system-claim privilege: an invariant whose
    # record PASSes over a FAILing execution is the same unearned coverage,
    # and Gate B calls it invalid either way.
    if row["status"] == "PASS" and row["non_passing_executions"]:
        row["status"] = "evidence-gap"
    if kind != SYSTEM_CLAIM:
        return row
    spec = system_claims.get(cid, {})
    required_evidence = spec.get("required_evidence")
    row["required_evidence"] = required_evidence
    if required_evidence is None:
        # Named as a system claim without a manifest entry declaring which
        # tools its cohort must contain: the cohort is still rendered, but
        # coverage is undeclared rather than assumed satisfied.
        row["evidence_coverage"] = None
        row["evidence_gaps"] = None
    else:
        coverage, gaps = cohort_coverage(required_evidence, row["executions"])
        row["evidence_coverage"] = coverage
        row["evidence_gaps"] = gaps
        if row["status"] == "PASS" and gaps:
            row["status"] = "evidence-gap"
    row["depends_on"] = spec.get("depends_on")
    row["dependency_gaps"] = []
    row["dependencies_not_evaluated"] = []
    return row


def apply_dependency_coverage(rows: list[dict]) -> None:
    """A system claim is no better covered than the obligations it rests on.

    Only dependencies this run actually evaluated count: a dependency outside
    the required set is reported as not-evaluated, never silently as covered.
    A dependency that *is* required and not passing already drives the run
    verdict on its own row, so marking the claim here adds visibility without
    diverging from Gate B's verdict.
    """
    status_by_claim = {row["claim_id"]: row["status"] for row in rows}
    for row in rows:
        if row.get("obligation_kind") != SYSTEM_CLAIM:
            continue
        gaps: list[str] = []
        unevaluated: list[str] = []
        for dependency in row.get("depends_on") or []:
            status = status_by_claim.get(dependency)
            if status is None:
                unevaluated.append(dependency)
            elif status != "PASS":
                gaps.append(dependency)
        row["dependency_gaps"] = gaps
        row["dependencies_not_evaluated"] = unevaluated
        if row["status"] == "PASS" and gaps:
            row["status"] = "dependency-gap"


def summarize(rows: list[dict]) -> dict:
    status_key = {"PASS": "pass", "FAIL": "fail", "INCOMPLETE": "incomplete",
                  "missing-record": "missing", "duplicate-record": "duplicate",
                  "invalid": "invalid",
                  "unwaived-assumption": "unwaived_assumption",
                  "evidence-gap": "evidence_gap",
                  "dependency-gap": "dependency_gap"}
    result_key = {"PASS": "pass", "FAIL": "fail", "INCOMPLETE": "incomplete"}
    counts = {v: 0 for v in status_key.values()}
    waived_or_assumed = []
    by_class: dict[str, dict[str, int]] = {}
    by_execution_class: dict[str, dict[str, int]] = {}
    assumed_executions: dict[str, list[str]] = {}
    by_kind: dict[str, dict[str, int]] = {}
    for row in rows:
        counts[status_key[row["status"]]] += 1
        if row["waived"]:
            waived_or_assumed.append(row["claim_id"])
        if row.get("assumed_executions"):
            assumed_executions[row["claim_id"]] = row["assumed_executions"]
        kind_bucket = by_kind.setdefault(row.get("obligation_kind") or "unknown",
                                        {"pass": 0, "fail": 0, "gap": 0})
        if row["status"] == "PASS":
            kind_bucket["pass"] += 1
        elif row["status"] == "FAIL":
            kind_bucket["fail"] += 1
        else:
            kind_bucket["gap"] += 1
        # Per-execution classes are counted separately from the record's own:
        # a cohort's weakest artifact is invisible in the record class, which
        # is exactly the strength a reader would otherwise over-read.
        for entry in row.get("executions") or []:
            bucket = by_execution_class.setdefault(
                entry["evidence_class"] or "unreadable",
                {"pass": 0, "fail": 0, "incomplete": 0, "other": 0})
            bucket[result_key.get(entry["result"] or "", "other")] += 1
        klass = row["evidence_class"]
        if klass is None:
            continue
        bucket = by_class.setdefault(
            klass, {"pass": 0, "fail": 0, "incomplete": 0, "other": 0})
        if row["status"] == "PASS":
            bucket["pass"] += 1
        elif row["status"] == "FAIL":
            bucket["fail"] += 1
        elif row["status"] == "INCOMPLETE":
            bucket["incomplete"] += 1
        else:
            bucket["other"] += 1
    system_rows = [r for r in rows if r.get("obligation_kind") == SYSTEM_CLAIM]
    system_claims = {
        "total": len(system_rows),
        "covered": sorted(r["claim_id"] for r in system_rows
                          if r["status"] == "PASS"),
        "evidence_gaps": {r["claim_id"]: r["evidence_gaps"]
                          for r in system_rows if r.get("evidence_gaps")},
        "dependency_gaps": {r["claim_id"]: r["dependency_gaps"]
                            for r in system_rows if r.get("dependency_gaps")},
        "non_passing_executions": {r["claim_id"]: r["non_passing_executions"]
                                   for r in system_rows
                                   if r.get("non_passing_executions")},
    }
    return {
        "total_required": len(rows),
        **counts,
        "waived_or_assumed": sorted(waived_or_assumed),
        "by_evidence_class": by_class,
        "by_execution_evidence_class": by_execution_class,
        "assumed_executions": assumed_executions,
        "by_obligation_kind": by_kind,
        "system_claims": system_claims,
    }


def compute_verdict(rows: list[dict], by_claim: dict[str, dict],
                     required: list[str]) -> tuple[str, int]:
    if not required:
        return "INCOMPLETE", 3
    if any(r["status"] == "FAIL" for r in rows):
        return "FAILED", 1
    if any(r["status"] in GAP_STATUSES for r in rows):
        return "INCOMPLETE", 3
    profiles = sorted({by_claim[r["claim_id"]]["bindings"]["profile"] for r in rows})
    # The scope names the profile and nothing else. BINDING_MODE is disclosed in
    # the payload and the summary line instead, so this token neither claims a
    # freshness discipline it never ran nor invents a `binding` value that a
    # Gate B consumer would have to learn to parse.
    scope = f"profile={'/'.join(profiles)}"
    waived = sorted(r["claim_id"] for r in rows if r["waived"])
    verdict = f"VERIFIED[{scope}]"
    if waived:
        verdict += f" (waived: {','.join(waived)})"
    return verdict, 0


def build_dashboard(records_path: Path, required: list[str],
                     records: list[dict], kinds: dict[str, str] | None = None,
                     system_claims: dict[str, dict] | None = None,
                     dependency_expansion: dict[str, list[str]] | None = None,
                     expect_required_targets: tuple[str, ...] | None = None,
                     expect_manifest: str | None = None
                     ) -> tuple[dict, int]:
    kinds = kinds or {}
    by_claim: dict[str, dict] = {}
    duplicates: set[str] = set()
    for rec in records:
        cid = rec.get("claim_id") if isinstance(rec, dict) else None
        if isinstance(cid, str):
            if cid in by_claim:
                duplicates.add(cid)
            by_claim[cid] = rec
    # Built over the judged set exactly as Gate B builds it, before any row is
    # evaluated: a substituted artifact is only visible across records.
    cited = gate.cited_artifact_index(required, by_claim)
    rows = [evaluate_claim(cid, by_claim, kinds, system_claims, duplicates,
                           expect_required_targets, expect_manifest, cited)
            for cid in required]
    apply_dependency_coverage(rows)
    summary = summarize(rows)
    verdict, code = compute_verdict(rows, by_claim, required)
    dashboard = {
        "gate": "coverage-dashboard",
        "records": str(records_path),
        "binding": BINDING_MODE,
        "required_claims": required,
        "dependency_expansion": dependency_expansion or {},
        "obligation_kinds": {cid: kinds[cid] for cid in required if cid in kinds},
        "rows": rows,
        "summary": summary,
        "verdict": verdict,
    }
    return dashboard, code


def render_system_claims(rows: list[dict]) -> list[str]:
    """Per-system-claim cohort detail: which required tool IDs PASSed, which
    did not, and which dependencies are uncovered or unevaluated."""
    system_rows = [r for r in rows if r.get("obligation_kind") == SYSTEM_CLAIM]
    if not system_rows:
        return []
    lines = ["", "system claims:"]
    for row in system_rows:
        lines.append(f"  {row['claim_id']} [{row['status']}]")
        coverage = row.get("evidence_coverage")
        if coverage is None:
            cohort = row.get("executions") or []
            observed = " ".join(f"{e['tool'] or '?'}={e['result'] or 'unknown'}"
                                for e in cohort) or "none recorded"
            lines.append("    required_evidence: not declared by manifest; "
                         f"executions: {observed}")
        else:
            lines.append("    required_evidence: " + " ".join(
                f"{tool}={coverage[tool]}" for tool in row["required_evidence"]))
            if row["evidence_gaps"]:
                lines.append("    missing PASS evidence: "
                             + ", ".join(row["evidence_gaps"]))
        # Printed for both branches: a cohort entry that did not PASS is a
        # defect whether or not the manifest declared what the cohort needs.
        if row["non_passing_executions"]:
            lines.append("    cohort executions that did not PASS: "
                         + ", ".join(sorted(row["non_passing_executions"])))
        if row.get("dependency_gaps"):
            lines.append("    dependencies not covered: "
                         + ", ".join(row["dependency_gaps"]))
        if row.get("dependencies_not_evaluated"):
            lines.append("    dependencies not evaluated this run: "
                         + ", ".join(row["dependencies_not_evaluated"]))
    return lines


def render_text(dashboard: dict) -> str:
    lines = [f"{'CLAIM':<10} {'KIND':<14} {'STATUS':<20} {'CLASS':<20} "
             f"{'WAIVED':<7} SCOPE"]
    for row in dashboard["rows"]:
        lines.append(
            f"{row['claim_id']:<10} "
            f"{(row.get('obligation_kind') or '-'):<14} "
            f"{row['status']:<20} "
            f"{(row['evidence_class'] or '-'):<20} "
            f"{('yes' if row['waived'] else 'no'):<7} "
            f"{row['scope'] or '-'}"
        )
    s = dashboard["summary"]
    lines.append("")
    lines.append(
        f"required={s['total_required']} pass={s['pass']} fail={s['fail']} "
        f"incomplete={s['incomplete']} missing={s['missing']} "
        f"duplicate={s['duplicate']} invalid={s['invalid']} "
        f"unwaived-assumption={s['unwaived_assumption']} "
        f"evidence-gap={s['evidence_gap']} "
        f"dependency-gap={s['dependency_gap']}"
    )
    lines.append(f"bindings: {BINDING_MODE} (snapshot and intent freshness are "
                 "Gate B's to recompute; this view reads records only)")
    if s["waived_or_assumed"]:
        lines.append(f"waived-or-assumed: {', '.join(s['waived_or_assumed'])}")
    lines.append("by evidence_class:")
    for klass, c in sorted(s["by_evidence_class"].items()):
        lines.append(f"  {klass}: pass={c['pass']} fail={c['fail']} "
                      f"incomplete={c['incomplete']} other={c['other']}")
    if s["by_execution_evidence_class"]:
        lines.append("by execution evidence_class:")
        for klass, c in sorted(s["by_execution_evidence_class"].items()):
            lines.append(f"  {klass}: pass={c['pass']} fail={c['fail']} "
                          f"incomplete={c['incomplete']} other={c['other']}")
    if s["assumed_executions"]:
        lines.append("assumed-class executions:")
        for cid, entries in sorted(s["assumed_executions"].items()):
            lines.append(f"  {cid}: {', '.join(entries)}")
    lines.append("by obligation kind:")
    for kind, c in sorted(s["by_obligation_kind"].items()):
        lines.append(f"  {kind}: pass={c['pass']} fail={c['fail']} gap={c['gap']}")
    lines.extend(render_system_claims(dashboard["rows"]))
    return "\n".join(lines)


def verdict_line(verdict: str) -> str:
    return f"VERDICT: {verdict}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--records", required=True, type=Path)
    ap.add_argument("--require", default=None,
                    help="comma-separated claim IDs the profile requires; on its "
                         "own it declares no obligation set, so obligation kinds, "
                         "required_targets and manifest freshness do not bind")
    ap.add_argument("--manifest", type=Path, default=None,
                    help="obligation manifest: the required claim IDs, their "
                         "kinds, each record's expected required_targets, and the "
                         "manifest hash records must be bound to")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--check", action="store_true",
                     help="self-conformance: exit nonzero if this tool's own "
                          "rendered output would ever emit a bare VERIFIED")
    args = ap.parse_args()

    try:
        records = load_records(args.records)
    except (OSError, json.JSONDecodeError) as e:
        print(f"ERROR: cannot read records: {e}", file=sys.stderr)
        print(verdict_line("ERROR"), file=sys.stderr)
        return 2

    manifest_required: list[str] = []
    kinds: dict[str, str] = {}
    system_claims: dict[str, dict] = {}
    # The manifest's complete obligation set, captured before --require narrows the
    # judged set: it is what a cohort-schema record must declare as required_targets.
    # Beside it, that manifest's content hash — the expectation every record's
    # obligation_manifest_hash is judged against, derived from the bytes this run
    # was handed rather than read back off the records. Without --manifest neither
    # expectation exists, exactly as in Gate B.
    expected_targets: tuple[str, ...] | None = None
    expect_manifest: str | None = None
    if args.manifest:
        try:
            manifest_required, kinds, system_claims = load_manifest(args.manifest)
            expected_targets = tuple(manifest_required)
            expect_manifest = gate.manifest_binding(args.manifest)
        except ManifestError as e:
            print(f"ERROR: malformed obligation manifest: {e}", file=sys.stderr)
            print(verdict_line("ERROR"), file=sys.stderr)
            return 2
        except (OSError, json.JSONDecodeError) as e:
            print(f"ERROR: cannot read manifest: {e}", file=sys.stderr)
            print(verdict_line("ERROR"), file=sys.stderr)
            return 2

    required: list[str] = []
    if args.require:
        required = [c.strip() for c in args.require.split(",") if c.strip()]
    elif args.manifest:
        required = manifest_required
    else:
        print("ERROR: pass --require or --manifest — a dashboard with no "
              "required claims covers nothing", file=sys.stderr)
        print(verdict_line("ERROR"), file=sys.stderr)
        return 2

    if args.manifest and args.require:
        unknown = sorted(set(required) - set(kinds))
        if unknown:
            print(f"ERROR: required claims absent from manifest: {unknown}",
                  file=sys.stderr)
            print(verdict_line("ERROR"), file=sys.stderr)
            return 2

    # A required system claim drags its dependencies into the required set, the
    # same expansion Gate B performs: judging the composition while leaving the
    # invariants and witnesses under it unevaluated would report the parts as
    # covered by omission. depends_on names invariants and witnesses only, so
    # one pass is the transitive closure.
    dependency_expansion: dict[str, list[str]] = {}
    if args.manifest and args.require:
        for cid in list(required):
            if kinds.get(cid) != SYSTEM_CLAIM:
                continue
            added = [dep for dep in system_claims.get(cid, {}).get("depends_on", ())
                     if dep not in required]
            if added:
                dependency_expansion[cid] = added
                required.extend(added)

    dashboard, code = build_dashboard(args.records, required, records, kinds,
                                      system_claims, dependency_expansion,
                                      expected_targets, expect_manifest)

    if args.check:
        text = render_text(dashboard)
        vline = verdict_line(dashboard["verdict"])
        payload = json.dumps(dashboard, indent=2)
        blob = "\n".join([text, vline, payload])
        offending = [ln for ln in blob.splitlines() if UNSCOPED_VERDICT_RE.search(ln)]
        if offending:
            print("CHECK: bare VERIFIED token found in dashboard output:",
                  file=sys.stderr)
            for ln in offending:
                print(f"  {ln}", file=sys.stderr)
            return 1
        print("CHECK: clean, no bare VERIFIED token in dashboard output",
              file=sys.stderr)
        return 0

    if args.json:
        print(json.dumps(dashboard, indent=2))
    else:
        print(render_text(dashboard))
    print(verdict_line(dashboard["verdict"]), file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
