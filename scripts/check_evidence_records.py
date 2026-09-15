#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Gate B: validate hash-bound execution evidence and aggregate G2 verdicts."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fv_project  # noqa: E402  sibling module, copied beside this gate in project installs

EVIDENCE_CLASSES = {
    "code-enforced",
    "proof-discharged",
    "bounded-checked",
    "test-witnessed",
    "conformance-tested",
    "externally-assumed",
    "unverified",
}
EVIDENCE_CLASS_PASS_MARKERS: dict[str, str] = {
    "code-enforced": r"--- fv-evidence: exit=0 ---",
    "proof-discharged": r"(?:VERIFICATION:- SUCCESSFUL|Build completed successfully|--- fv-evidence: exit=0 ---)",
    "bounded-checked": r"(?:\[ok\]|VERIFICATION:- SUCCESSFUL|No violation found)",
    "test-witnessed": r"(?:test result: ok\.|\[ok\]|\[violation\]|Invariant violated|violation found)",
    "conformance-tested": r"(?:CONFORMANCE(?:_TESTED)?: PASS|test result: ok\.|--- fv-evidence: exit=0 ---)",
    "externally-assumed": r"--- fv-evidence: exit=0 ---",
    "unverified": r"--- fv-evidence: exit=0 ---",
}
OBLIGATION_EVIDENCE_COMPATIBILITY: dict[str, frozenset[str]] = {
    "invariant": frozenset(
        {
            "code-enforced",
            "proof-discharged",
            "bounded-checked",
            "conformance-tested",
            "externally-assumed",
            "unverified",
        }
    ),
    "witness": frozenset(
        {"test-witnessed", "conformance-tested", "externally-assumed", "unverified"}
    ),
    # A system claim is discharged by a cohort of tool executions, so any
    # per-tool evidence class can appear beneath it.
    "system_claim": frozenset(EVIDENCE_CLASSES),
}
OBLIGATION_COLLECTIONS: tuple[tuple[str, str], ...] = (
    ("invariants", "invariant"),
    ("witnesses", "witness"),
    ("system_claims", "system_claim"),
)
CLAIM_DEPENDENCY_KINDS = frozenset({"invariant", "witness"})
# An assumed or unverified class asserts nothing about the system: PASSing on it
# requires an explicit waiver, wherever in the record the class appears.
ASSUMED_CLASSES = frozenset({"externally-assumed", "unverified"})
# A waiver authorizes assumed evidence, so it must be attributable: which
# waiver, granted by whom, over what. Anything less names nobody.
WAIVER_FIELDS = ("id", "approver", "scope")
OBLIGATION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]*")
# The evidence producer's claim_id grammar (fv_evidence_run). An obligation id
# outside it can never have a record written for it, so a manifest declaring one
# is unusable rather than merely unsatisfied.
PRODUCER_CLAIM_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
EVIDENCE_TOOL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:+/-]*")
# The profile is record-asserted and lands verbatim in the verdict scope, so it
# must not be able to forge a second scope field.
PROFILE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+/-]*")
PRODUCER_PROFILE = "producer-trusted-execution"
# Every producer artifact is named after the claim and the execution's own run id,
# which is what binds one artifact to exactly one execution of one claim.
PRODUCER_ARTIFACT = ".fv/evidence/raw/{claim_id}-{run_id}.log"
DIRTY_SUFFIX = "+dirty"
RESULTS = {"PASS", "FAIL", "INCOMPLETE"}
TOP_FIELDS = ("claim_id", "required", "evidence_class", "result", "scope", "bindings", "waiver")
BINDING_FIELDS = (
    "source_snapshot",
    "intent_hash",
    "obligation_manifest_hash",
    "profile",
    "required_targets",
    "environment_policy",
    "toolchain_digests",
    "command",
    "configuration",
    "seeds",
    "raw_output_hash",
    "parser_schema_version",
    "run_id",
)
NULLABLE = {"seeds", "waiver"}
EVIDENCE_SCHEMA_V3 = "fv-evidence-run/v3"
# v3 adds the canonical target path and the execution cohort that discharged the claim.
V3_BINDING_FIELDS = ("intent_path", "executions")
EXECUTION_FIELDS = (
    "tool",
    "evidence_class",
    "command",
    "cwd",
    "toolchain_digests",
    "raw_output_path",
    "raw_output_hash",
    "result",
    "run_id",
)


def _inside(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False


def _valid_toolchain(toolchain: object) -> bool:
    """A resolved executable identity: path, content digest, version, probe exit code."""
    return (
        isinstance(toolchain, dict)
        and isinstance(toolchain.get("executable"), str)
        and bool(toolchain["executable"])
        and isinstance(toolchain.get("sha256"), str)
        and re.fullmatch(r"[0-9a-f]{64}", toolchain["sha256"]) is not None
        and isinstance(toolchain.get("version"), str)
        and isinstance(toolchain.get("version_exit_code"), int)
    )


def _contained_path_defect(repo_root: Path, value: object, field: str, label: str) -> str | None:
    """A repo-relative path that stays inside the repository, or a defect."""
    if not isinstance(value, str) or not value.strip():
        return f"{label}{field} is not a repo-relative path: {value!r}"
    candidate = Path(value)
    if candidate.is_absolute() or ".." in candidate.parts:
        return f"{label}{field} escapes repository root: {value!r}"
    if not _inside(repo_root.resolve(), (repo_root / value).resolve()):
        return f"{label}{field} escapes repository root: {value!r}"
    return None


def _read_artifact(repo_root: Path, relative: object, expected: object,
                   label: str = "") -> tuple[list[str], str | None]:
    """Resolve a raw artifact inside the repository and recompute its digest.

    Returns its decoded text only when the stored hash is the file's actual hash,
    so no later check can read bytes the record does not commit to.
    """
    if not isinstance(relative, str) or not relative.strip():
        return [f"{label}unresolvable raw artifact: missing binding raw_output_path"], None
    raw_path = (repo_root / relative).resolve()
    if Path(relative).is_absolute() or not _inside(repo_root.resolve(), raw_path):
        return [f"{label}unresolvable raw artifact: path escapes repository root"], None
    if not raw_path.is_file():
        return [f"{label}unresolvable raw artifact: {relative}"], None
    raw = raw_path.read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    if expected != actual:
        return [f"{label}raw output hash mismatch: stored={expected!r} recomputed={actual}"], None
    return [], raw.decode(errors="replace")


def _pass_artifact_defects(text: str, evidence_class: object, pass_marker: object,
                           label: str = "") -> list[str]:
    """A PASS artifact carries exactly one canonical exit=0 trailer, last, plus its marker."""
    canonical = "--- fv-evidence: exit=0 ---"
    lines = text.splitlines()
    trailers = [line for line in lines
                if re.fullmatch(r"--- fv-evidence: exit=\d+ ---", line)]
    if trailers != [canonical] or not lines or lines[-1] != canonical:
        return [f"{label}PASS artifact must end with one unique canonical exit=0 trailer"]
    if isinstance(pass_marker, str) and pass_marker:
        missing = pass_marker not in text
    else:
        marker = EVIDENCE_CLASS_PASS_MARKERS.get(evidence_class) if isinstance(evidence_class, str) else None
        if marker is None:
            return [f"{label}unknown evidence class {evidence_class!r}"]
        try:
            missing = re.search(marker, text) is None
        except re.error as error:
            return [f"{label}invalid evidence-class marker regex: {error}"]
    return [f"{label}PASS marker absent for evidence class {evidence_class}"] if missing else []


def _raw_artifact_defects(record: dict, repo_root: Path) -> list[str]:
    """The record-level artifact: the sole, or a cohort's first, execution's output."""
    bindings = record["bindings"]
    defects, text = _read_artifact(repo_root, bindings.get("raw_output_path"),
                                   bindings.get("raw_output_hash"))
    if text is None:
        return defects
    configuration = bindings.get("configuration")
    override = configuration.get("pass_marker") if isinstance(configuration, dict) else None
    return _pass_artifact_defects(text, record["evidence_class"], override)


class _Cohort:
    """What a cohort entry is judged against, plus the cross-execution state.

    ``seen_tools`` and ``seen_paths`` make coverage and artifacts one-to-one: a
    tool may discharge at most one execution, and an artifact at most one
    execution, so a single PASS log cannot stand in for a whole cohort.

    Hand-written rather than a dataclass because this gate is also loaded
    directly from its path (importlib, without a sys.modules entry), which is
    where dataclasses' deferred annotation resolution breaks.
    """

    __slots__ = ("claim_id", "record_pass", "producer", "obligation_kind",
                 "seen_tools", "seen_paths")

    def __init__(self, claim_id: str, record_pass: bool, producer: bool,
                 obligation_kind: str | None = None) -> None:
        self.claim_id = claim_id
        self.record_pass = record_pass
        self.producer = producer
        self.obligation_kind = obligation_kind
        self.seen_tools: set[str] = set()
        self.seen_paths: dict[str, int] = {}


def _execution_defects(execution: object, index: int, repo_root: Path,
                       cohort: _Cohort) -> list[str]:
    """One cohort entry: tool identity, argv, contained cwd, executable identity, artifact."""
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
    elif tool in cohort.seen_tools:
        defects.append(f"{label}duplicate evidence tool {tool!r}: cohort coverage is ambiguous")
    else:
        cohort.seen_tools.add(tool)
    evidence_class = execution["evidence_class"]
    if evidence_class not in EVIDENCE_CLASSES:
        defects.append(f"{label}unknown evidence_class {evidence_class!r}")
    elif cohort.obligation_kind is not None:
        # The record's declared class is not the strength of the evidence: each
        # execution has to be admissible for the obligation it helps discharge.
        compatible = OBLIGATION_EVIDENCE_COMPATIBILITY.get(cohort.obligation_kind, frozenset())
        if evidence_class not in compatible:
            defects.append(f"{label}incompatible evidence class {evidence_class!r} "
                           f"for obligation kind {cohort.obligation_kind!r}")
    command = execution["command"]
    if (not isinstance(command, list) or not command
            or any(not isinstance(part, str) or not part for part in command)):
        defects.append(f"{label}command is not a nonempty argv array of nonempty strings: {command!r}")
    cwd_defect = _contained_path_defect(repo_root, execution["cwd"], "cwd", label)
    if cwd_defect is not None:
        defects.append(cwd_defect)
    if not _valid_toolchain(execution["toolchain_digests"]):
        defects.append(f"{label}lacks resolved executable identity")
    result = execution["result"]
    if result not in RESULTS:
        defects.append(f"{label}unknown result {result!r}")
    elif cohort.record_pass and result != "PASS":
        defects.append(f"{label}result {result!r} cannot appear beneath a PASS record")
    run_id = execution["run_id"]
    if not isinstance(run_id, str) or not run_id.strip():
        defects.append(f"{label}run_id is empty")
    raw_relative = execution["raw_output_path"]
    if isinstance(raw_relative, str) and raw_relative:
        first = cohort.seen_paths.setdefault(raw_relative, index)
        if first != index:
            defects.append(f"{label}raw_output_path {raw_relative!r} duplicates "
                           f"executions[{first}]: one artifact cannot discharge two executions")
        if cohort.producer and isinstance(run_id, str):
            expected = PRODUCER_ARTIFACT.format(claim_id=cohort.claim_id, run_id=run_id)
            if raw_relative != expected:
                defects.append(f"{label}raw_output_path {raw_relative!r} is not this run's "
                               f"producer artifact {expected!r}")
    marker = execution.get("pass_marker")
    if "pass_marker" in execution and (not isinstance(marker, str) or not marker):
        defects.append(f"{label}pass_marker is empty")
    if defects:
        return defects
    artifact_defects, text = _read_artifact(repo_root, execution["raw_output_path"],
                                            execution["raw_output_hash"], label)
    defects.extend(artifact_defects)
    if text is not None and result == "PASS":
        defects.extend(_pass_artifact_defects(text, evidence_class, marker, label))
    return defects


def _cohort_defects(record: dict, repo_root: Path, obligation_kind: str | None = None) -> list[str]:
    """Every execution of a v3 cohort, and the legacy bindings derived from its first."""
    bindings = record["bindings"]
    executions = bindings.get("executions")
    if not isinstance(executions, list) or not executions:
        return ["bindings.executions is not a nonempty array"]
    defects: list[str] = []
    cohort = _Cohort(
        claim_id=record["claim_id"],
        record_pass=record["result"] == "PASS",
        producer=bindings.get("profile") == PRODUCER_PROFILE,
        obligation_kind=obligation_kind,
    )
    for index, execution in enumerate(executions):
        defects.extend(_execution_defects(execution, index, repo_root, cohort))
    if defects:
        return defects
    # A record whose legacy fields describe a different run than its cohort would
    # gate as two different claims depending on which half a reader trusts.
    primary = executions[0]
    if (bindings.get("raw_output_path") != primary["raw_output_path"]
            or bindings.get("raw_output_hash") != primary["raw_output_hash"]):
        defects.append("legacy raw-output bindings are not derived from executions[0]")
    command = bindings.get("command")
    if isinstance(command, str):
        try:
            command = json.loads(command)
        except json.JSONDecodeError:
            command = None
    if command != primary["command"]:
        defects.append("legacy command binding is not derived from executions[0]")
    configuration = bindings.get("configuration")
    declared_cwd = configuration.get("cwd") if isinstance(configuration, dict) else None
    if declared_cwd != primary["cwd"]:
        defects.append("legacy configuration.cwd binding is not derived from executions[0]")
    declared_marker = configuration.get("pass_marker") if isinstance(configuration, dict) else None
    if declared_marker != primary.get("pass_marker"):
        defects.append("legacy configuration.pass_marker binding is not derived from executions[0]")
    return defects


def _coverage_defects(record: dict, required_evidence: list[str]) -> list[str]:
    """A system claim PASSes only when every required tool ID is a PASS execution."""
    executions = record["bindings"].get("executions")
    passing = {execution["tool"] for execution in executions
               if isinstance(execution, dict) and execution.get("result") == "PASS"
               and isinstance(execution.get("tool"), str)} if isinstance(executions, list) else set()
    uncovered = [tool for tool in required_evidence if tool not in passing]
    if not uncovered:
        return []
    return [f"system claim missing PASS evidence from required tools {uncovered}"]


def _waiver_defects(waiver: object) -> list[str]:
    """A waiver is an attributable authorization, never a bare flag.

    The waiver is the only thing that turns an assumed claim into a PASS, so it
    has to record who allowed what: ``true`` names nobody, and an object
    carrying an id alone excuses nothing an auditor could follow up. Pure record
    text, which is why every consumer of these records applies it.
    """
    if not waiver:
        return []
    if not isinstance(waiver, dict):
        return [f"waiver is not an object: {waiver!r}"]
    missing = [field for field in WAIVER_FIELDS
               if not isinstance(waiver.get(field), str) or not waiver[field].strip()]
    if missing:
        return [f"waiver is not attributable: {missing} missing or blank; an "
                f"assumed claim is waived only by a nonempty id, approver, and "
                f"scope: {waiver!r}"]
    return []


def _asserted_field_defects(bindings: dict, schema_v3: bool) -> list[str]:
    """Record-asserted binding fields, judged for shape before anything reads them.

    ``profile`` reaches the verdict scope verbatim, so a record must not be able
    to inject a second scope field into it. ``required_targets`` is compared to
    the manifest by ``v3_producer_defects`` for a cohort-schema record, and this
    is the shape check that comparison relies on; for a pre-cohort record it stays
    an unread assertion. ``intent_path`` is shape-checked here rather than beside
    the containment check that needs a repository root: whether the canonical
    target is a string at all is record text, and a consumer without the tree
    must still refuse a cohort record whose target is an object. The rest is
    provenance a later reader parses, and an ill-typed value there is drift, not
    detail.
    """
    defects: list[str] = []
    profile = bindings.get("profile")
    if not isinstance(profile, str) or PROFILE_ID.fullmatch(profile) is None:
        defects.append(f"malformed profile {profile!r}")
    targets = bindings.get("required_targets")
    if (not isinstance(targets, list) or not targets
            or any(not isinstance(target, str) or OBLIGATION_ID.fullmatch(target) is None
                   for target in targets)):
        defects.append(f"required_targets is not a nonempty array of obligation ids: {targets!r}")
    asserted = ("intent_hash", "obligation_manifest_hash", "environment_policy",
                "parser_schema_version", "run_id")
    # intent_path is the cohort schema's; a pre-cohort record never carried one.
    for name in asserted + (("intent_path",) if schema_v3 else ()):
        value = bindings.get(name)
        if not isinstance(value, str) or not value.strip():
            defects.append(f"binding field {name!r} is not a nonempty string: {value!r}")
    return defects


def dirty_snapshot_defects(record: dict) -> list[str]:
    """A PASS record bound to a snapshot the producer watched move.

    The ``+dirty`` marker is the producer reporting that a verified input changed
    while the command ran, so it blocks a PASS in every comparison mode instead of
    being advice a prefix match can wave through. It is a pure record-text rule,
    which is why every consumer of these records applies it, repository access or
    not.
    """
    snapshot = record["bindings"].get("source_snapshot")
    if record["result"] != "PASS" or not isinstance(snapshot, str):
        return []
    if not snapshot.endswith(DIRTY_SUFFIX):
        return []
    return [
        f"PASS record bound to a dirty snapshot {snapshot!r}: its verified inputs "
        "moved during the run"
    ]


def manifest_binding(path: Path) -> str:
    """The obligation-manifest expectation records are judged against.

    The manifest is an explicit CLI input, so its hash is derivable by any
    consumer holding it: deriving it needs no repository tree, and a consumer
    that skips the derivation reports coverage for evidence bound elsewhere.
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manifest_binding_defects(bindings: dict, expect_manifest: str | None) -> list[str]:
    """A record bound to an obligation set other than the one being judged.

    Evidence earned against a different manifest answers a different question,
    so it is stale here however sound it was there. Record text compared against
    a CLI input, which is why every consumer handed ``--manifest`` applies it.
    """
    declared = bindings.get("obligation_manifest_hash")
    if not expect_manifest or declared == expect_manifest:
        return []
    return [
        f"stale record: bound to obligation manifest {declared!r}, "
        f"expected {expect_manifest!r}"
    ]


def v3_producer_defects(bindings: dict,
                        expect_required_targets: tuple[str, ...] | None) -> list[str]:
    """A cohort-schema record is producer-written: hold it to the producer's scope.

    Only ``fv_evidence_run`` writes ``fv-evidence-run/v3``, and every rule that binds
    a producer record - the per-execution artifact name, the resolved executable
    identity behind the record-level bindings - keys off ``bindings.profile``. A v3
    record declaring any other profile would keep the cohort schema's coverage power
    while opting out of those rules, and would still put its own string into the
    verdict scope, so the profile is pinned rather than trusted.

    ``required_targets`` is record-asserted until something compares it. The producer
    writes every obligation its manifest declares, so the expected set is threaded in
    from the manifest this run was judged against and never read back off the record.
    """
    defects: list[str] = []
    profile = bindings.get("profile")
    if profile != PRODUCER_PROFILE:
        defects.append(f"cohort-schema record declares profile {profile!r}, not the "
                       f"producer profile {PRODUCER_PROFILE!r}")
    declared = bindings.get("required_targets")
    if expect_required_targets is None or not isinstance(declared, list):
        return defects
    if len(set(declared)) != len(declared):
        defects.append(f"required_targets repeats an obligation id: {declared!r}")
    expected = set(expect_required_targets)
    missing = sorted(expected - set(declared))
    unexpected = sorted(set(declared) - expected)
    if missing or unexpected:
        defects.append("required_targets is not the obligation manifest's required "
                       f"set: missing {missing}, unexpected {unexpected}")
    return defects


def is_schema_v3(record: object) -> bool:
    """True for a cohort-carrying record: the schema whose artifacts are per-execution."""
    bindings = record.get("bindings") if isinstance(record, dict) else None
    if not isinstance(bindings, dict):
        return False
    return bindings.get("parser_schema_version") == EVIDENCE_SCHEMA_V3 or "executions" in bindings


def validate_record(
    record: dict,
    expect_snapshot: str | None,
    expect_intent: str | None = None,
    expect_manifest: str | None = None,
    snapshot_exact: bool = False,
    repo_root: Path | None = None,
    obligation_kind: str | None = None,
    required_evidence: list[str] | None = None,
    expect_intent_path: str | None = None,
    expect_required_targets: tuple[str, ...] | None = None,
) -> list[str]:
    defects: list[str] = []
    if not isinstance(record, dict):
        return ["record is not an object"]
    for field in TOP_FIELDS:
        if field not in record:
            defects.append(f"missing field {field!r}")
    if defects:
        return defects
    if not isinstance(record["claim_id"], str) or not record["claim_id"]:
        defects.append("claim_id is empty")
    if not isinstance(record["required"], bool):
        defects.append("required is not boolean")
    if record["evidence_class"] not in EVIDENCE_CLASSES:
        defects.append(f"unknown evidence_class {record['evidence_class']!r}")
    if record["result"] not in RESULTS:
        defects.append(f"unknown result {record['result']!r}")
    if not isinstance(record["scope"], str) or not record["scope"].strip():
        defects.append("scope is empty")
    bindings = record["bindings"]
    if not isinstance(bindings, dict):
        defects.append("bindings is not an object")
        return defects
    schema_v3 = is_schema_v3(record)
    expected_fields = BINDING_FIELDS + (V3_BINDING_FIELDS if schema_v3 else ())
    for field in expected_fields:
        if field not in bindings:
            defects.append(f"missing binding field {field!r}")
        elif bindings[field] in ("", [], {}) or (bindings[field] is None and field not in NULLABLE):
            defects.append(f"empty binding field {field!r}")
    if bindings.get("profile") == PRODUCER_PROFILE and not _valid_toolchain(
        bindings.get("toolchain_digests")
    ):
        defects.append("producer evidence lacks resolved executable identity")
    defects.extend(_asserted_field_defects(bindings, schema_v3))
    defects.extend(_waiver_defects(record["waiver"]))
    if defects:
        return defects
    snapshot = bindings.get("source_snapshot")
    defects.extend(dirty_snapshot_defects(record))
    if expect_snapshot:
        matched = isinstance(snapshot, str) and (
            snapshot == expect_snapshot if snapshot_exact else snapshot.startswith(expect_snapshot)
        )
        if not matched:
            qualifier = "exactly " if snapshot_exact else ""
            hint = ""
            if fv_project.is_content_snapshot(expect_snapshot) and not fv_project.is_content_snapshot(snapshot):
                hint = (
                    f" (record schema {bindings.get('parser_schema_version')!r} predates verified-input"
                    " snapshots; pass --expect-snapshot or --allow-unbound to validate it)"
                )
            defects.append(
                f"stale record: bound to snapshot {snapshot!r}, expected {qualifier}{expect_snapshot!r}{hint}"
            )
    if expect_intent and bindings.get("intent_hash") != expect_intent:
        defects.append(
            f"stale record: bound to intent {bindings.get('intent_hash')!r}, expected {expect_intent!r}"
        )
    defects.extend(manifest_binding_defects(bindings, expect_manifest))
    if obligation_kind is not None:
        compatible = OBLIGATION_EVIDENCE_COMPATIBILITY.get(obligation_kind)
        if compatible is None or record["evidence_class"] not in compatible:
            defects.append(
                f"incompatible evidence class {record['evidence_class']!r} for obligation kind {obligation_kind!r}"
            )
    if schema_v3:
        # Repository-free producer rules, applied wherever a v3 record is read.
        defects.extend(v3_producer_defects(bindings, expect_required_targets))
    if schema_v3 and repo_root is not None:
        intent_path_defect = _contained_path_defect(repo_root, bindings.get("intent_path"),
                                                    "intent_path", "")
        if intent_path_defect is not None:
            defects.append(intent_path_defect)
        elif expect_intent_path is not None and bindings.get("intent_path") != expect_intent_path:
            # The hash is already compared; without this the path beside it is the one
            # provenance field a reader would trust and nothing checks.
            defects.append(
                f"stale record: bound to intent path {bindings.get('intent_path')!r}, "
                f"expected {expect_intent_path!r}"
            )
        defects.extend(_cohort_defects(record, repo_root, obligation_kind))
    # A v3 record's legacy artifact is its first execution's, already judged by the
    # class that produced it and pinned to these bindings by the derivation check.
    if (not schema_v3 and record["result"] == "PASS"
            and record["evidence_class"] in EVIDENCE_CLASSES and repo_root is not None):
        defects.extend(_raw_artifact_defects(record, repo_root))
    # Coverage is a PASS condition: a FAIL record already reports as FAIL.
    if required_evidence and record["result"] == "PASS":
        defects.extend(_coverage_defects(record, required_evidence))
    return defects


def unwrap(data: object) -> list[dict]:
    if isinstance(data, dict) and "records" in data:
        data = data["records"]
    return data if isinstance(data, list) else [data]


def load_records(path: Path) -> list[dict]:
    if path.is_dir():
        records: list[dict] = []
        for record_path in sorted(path.glob("*.json")):
            records.extend(unwrap(json.loads(record_path.read_text())))
        return records
    return unwrap(json.loads(path.read_text()))


def infer_repo_root(records_path: Path) -> Path:
    resolved = records_path.resolve()
    for parent in (resolved if resolved.is_dir() else resolved.parent, *resolved.parents):
        if (parent / ".fv").is_dir():
            return parent
    return Path.cwd().resolve()


class ManifestError(Exception):
    """The obligation manifest is malformed: no required-claim set can be derived."""


def _obligation_entries(manifest: dict, collection: str) -> list[tuple[str, dict]]:
    """Declared (id, obligation) pairs of one collection, or a defect."""
    raw = manifest.get(collection, [])
    if not isinstance(raw, list):
        raise ManifestError(f"{collection} is not an array")
    entries: list[tuple[str, dict]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ManifestError(f"{collection}[{index}] is not an object")
        claim_id = item.get("id")
        if not isinstance(claim_id, str) or OBLIGATION_ID.fullmatch(claim_id) is None:
            raise ManifestError(f"{collection}[{index}] has malformed id {claim_id!r}")
        if PRODUCER_CLAIM_ID.fullmatch(claim_id) is None:
            # An id the producer's claim_id grammar rejects can never have a record
            # written for it, so it would read as missing-record forever.
            raise ManifestError(
                f"{collection}[{index}] id {claim_id!r} is not usable by the evidence "
                "producer: obligation ids must match [A-Za-z0-9][A-Za-z0-9._-]*"
            )
        entries.append((claim_id, item))
    return entries


def _id_list(claim_id: str, field: str, value: object, pattern: re.Pattern[str]) -> list[str]:
    """A nonempty, duplicate-free list of well-formed IDs, or a defect."""
    if not isinstance(value, list) or not value:
        raise ManifestError(f"system_claim {claim_id!r} {field} is not a nonempty array")
    ids: list[str] = []
    for index, entry in enumerate(value):
        if not isinstance(entry, str) or pattern.fullmatch(entry) is None:
            raise ManifestError(f"system_claim {claim_id!r} {field}[{index}] is malformed: {entry!r}")
        if entry in ids:
            raise ManifestError(f"system_claim {claim_id!r} {field} repeats {entry!r}")
        ids.append(entry)
    return ids


def _validate_system_claim(claim_id: str, claim: dict,
                           kinds: dict[str, str]) -> tuple[list[str], list[str]]:
    """depends_on names declared invariants/witnesses; required_evidence names tool IDs.

    Confining dependencies to non-claim obligations is what makes a dependency
    cycle between system claims unrepresentable (a claim can never reach another
    claim, including itself), so the gate needs no cycle search. Widening
    depends_on to nested claims would require one.
    """
    dependencies = _id_list(claim_id, "depends_on", claim.get("depends_on"), OBLIGATION_ID)
    for dependency in dependencies:
        kind = kinds.get(dependency)
        if kind is None:
            raise ManifestError(
                f"system_claim {claim_id!r} depends on undeclared obligation {dependency!r}"
            )
        if kind not in CLAIM_DEPENDENCY_KINDS:
            raise ManifestError(
                f"system_claim {claim_id!r} depends on {dependency!r} of kind {kind!r}: "
                "depends_on names invariants and witnesses only"
            )
    evidence = _id_list(claim_id, "required_evidence", claim.get("required_evidence"),
                        EVIDENCE_TOOL_ID)
    return dependencies, evidence


def load_manifest(
    path: Path,
) -> tuple[list[str], dict[str, str], dict[str, list[str]], dict[str, list[str]]]:
    """Required claim IDs, their kinds, and each system claim's evidence and dependencies."""
    manifest = json.loads(path.read_text())
    if not isinstance(manifest, dict):
        raise ManifestError("manifest is not an object")
    required: list[str] = []
    kinds: dict[str, str] = {}
    system_claims: list[tuple[str, dict]] = []
    for collection, kind in OBLIGATION_COLLECTIONS:
        for claim_id, item in _obligation_entries(manifest, collection):
            if claim_id in kinds:
                raise ManifestError(
                    f"duplicate obligation id {claim_id!r} in {collection} "
                    f"(already declared as {kinds[claim_id]})"
                )
            kinds[claim_id] = kind
            required.append(claim_id)
            if kind == "system_claim":
                system_claims.append((claim_id, item))
    # Dependencies may name obligations declared later in the file, so resolve
    # every claim only once the full kind map exists.
    claim_evidence: dict[str, list[str]] = {}
    claim_depends: dict[str, list[str]] = {}
    for claim_id, item in system_claims:
        claim_depends[claim_id], claim_evidence[claim_id] = _validate_system_claim(
            claim_id, item, kinds)
    return required, kinds, claim_evidence, claim_depends


def current_source_snapshot(repo_root: Path) -> str:
    """Recompute the verified-input content snapshot records must be bound to."""
    return fv_project.content_snapshot(repo_root)


def current_intent_binding(repo_root: Path) -> tuple[str, str]:
    """Canonical target's repo-relative path and content hash."""
    target = fv_project.resolve_target(repo_root)
    return fv_project.repo_relative(repo_root, target), fv_project.target_hash(repo_root)


def _cited_artifacts(record: object) -> list[str]:
    """Repo-relative raw artifacts a record commits to, deduped within the record."""
    bindings = record.get("bindings") if isinstance(record, dict) else None
    if not isinstance(bindings, dict):
        return []
    paths = [bindings.get("raw_output_path")]
    executions = bindings.get("executions")
    if isinstance(executions, list):
        paths.extend(execution.get("raw_output_path") for execution in executions
                     if isinstance(execution, dict))
    return list(dict.fromkeys(path for path in paths if isinstance(path, str) and path))


def cited_artifact_index(required: list[str],
                         by_claim: dict[str, dict]) -> dict[str, set[str]]:
    """Which required claims cite each raw artifact, over the whole judged run."""
    cited: dict[str, set[str]] = {}
    for claim_id in required:
        for relative in _cited_artifacts(by_claim.get(claim_id)):
            cited.setdefault(relative, set()).add(claim_id)
    return cited


def shared_artifact_defects(claim_id: str, record: object,
                            cited: dict[str, set[str]]) -> list[str]:
    """Artifacts this record cites that another required claim cites too.

    One artifact cannot discharge two claims: whichever claim reads it second is
    reading evidence earned elsewhere. Enforced for cohort-schema records, whose
    artifacts are per-execution by construction; a pre-cohort record, which only
    validates at all under an explicit freshness escape hatch, keeps the legacy
    tolerance of one log cited by several claims.
    """
    if not is_schema_v3(record):
        return []
    defects: list[str] = []
    for relative in _cited_artifacts(record):
        shared = sorted(cited.get(relative, set()) - {claim_id})
        if shared:
            defects.append(f"raw artifact {relative!r} is also cited by claim(s) "
                           f"{shared}: evidence cannot be shared between claims")
    return defects


def _assumed_evidence(record: dict) -> list[str]:
    """Every place this record rests on an assumed or unverified class.

    The record's declared class is not the strength of what ran: a cohort entry
    can be ``unverified`` beneath a ``code-enforced`` record, so the waiver rule
    has to quantify over the whole record.
    """
    sources: list[str] = []
    if record.get("evidence_class") in ASSUMED_CLASSES:
        sources.append(f"record={record['evidence_class']}")
    bindings = record.get("bindings")
    executions = bindings.get("executions") if isinstance(bindings, dict) else None
    if isinstance(executions, list):
        for index, execution in enumerate(executions):
            if not isinstance(execution, dict) or execution.get("evidence_class") not in ASSUMED_CLASSES:
                continue
            tool = execution.get("tool") if isinstance(execution.get("tool"), str) else index
            sources.append(f"{tool}={execution['evidence_class']}")
    return sources


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--records", required=True, type=Path)
    parser.add_argument("--require", default=None)
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--expect-snapshot", default=None)
    parser.add_argument("--expect-intent", default=None)
    parser.add_argument("--expect-manifest", default=None)
    parser.add_argument("--snapshot-exact", action="store_true")
    parser.add_argument("--allow-unbound", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        records = load_records(args.records)
        manifest_required: list[str] = []
        obligation_kinds: dict[str, str] = {}
        claim_evidence: dict[str, list[str]] = {}
        claim_depends: dict[str, list[str]] = {}
        # The complete declared obligation set, captured before --require narrows the
        # judged set: a producer record asserts every target its manifest declared, so
        # the expectation comes from the manifest and not from the record.
        expected_targets: tuple[str, ...] | None = None
        if args.manifest:
            (manifest_required, obligation_kinds, claim_evidence,
             claim_depends) = load_manifest(args.manifest)
            expected_targets = tuple(manifest_required)
            # --expect-manifest is an operator override for judging records against
            # a manifest this run is not holding; absent it the expectation is the
            # held manifest's own bytes, which is what every other consumer derives.
            if args.expect_manifest is None:
                args.expect_manifest = manifest_binding(args.manifest)
        if args.require is not None:
            required = [claim.strip() for claim in args.require.split(",") if claim.strip()]
            if not required:
                print("ERROR: --require names no claims")
                print("\nVERDICT: ERROR")
                return 2
        elif args.manifest:
            required = manifest_required
        else:
            print("ERROR: pass --require or --manifest")
            print("\nVERDICT: ERROR")
            return 2
        unknown_required = sorted(set(required) - set(obligation_kinds)) if args.manifest else []
        if unknown_required:
            print(f"ERROR: required claims absent from manifest: {unknown_required}")
            print("\nVERDICT: ERROR")
            return 2
        # A required system claim is not discharged by its own cohort alone: judging
        # it without the invariants and witnesses it depends on would report VERIFIED
        # for a composition whose parts were never looked at.
        dependency_expansion: dict[str, list[str]] = {}
        if args.require is not None and args.manifest:
            for claim_id in list(required):
                if obligation_kinds.get(claim_id) != "system_claim":
                    continue
                added = [dependency for dependency in claim_depends.get(claim_id, ())
                         if dependency not in required]
                if added:
                    dependency_expansion[claim_id] = added
                    required.extend(added)
    except ManifestError as error:
        print(f"ERROR: malformed obligation manifest: {error}")
        print("\nVERDICT: ERROR")
        return 2
    except (OSError, json.JSONDecodeError) as error:
        print(f"ERROR: cannot read evidence inputs: {error}")
        print("\nVERDICT: ERROR")
        return 2

    required = sorted(dict.fromkeys(required))
    repo_root = args.root.resolve() if args.root else infer_repo_root(args.records)
    intent_path: str | None = None
    # The verdict must say which freshness discipline produced it: a pinned or
    # unbound run is not the same claim as a recomputed one.
    pinned = args.expect_snapshot is not None or args.expect_intent is not None
    binding = "unbound" if args.allow_unbound else ("pinned" if pinned else "recomputed")
    if not args.allow_unbound:
        try:
            if args.expect_snapshot is None:
                args.expect_snapshot = current_source_snapshot(repo_root)
                args.snapshot_exact = True
            if args.expect_intent is None:
                intent_path, args.expect_intent = current_intent_binding(repo_root)
        except (OSError, ValueError) as error:
            print(f"ERROR: cannot bind evidence to current source and intent: {error}")
            print("\nVERDICT: ERROR")
            return 2
    by_claim: dict[str, dict] = {}
    duplicates: set[str] = set()
    for record in records:
        claim_id = record.get("claim_id") if isinstance(record, dict) else None
        if isinstance(claim_id, str):
            if claim_id in by_claim:
                duplicates.add(claim_id)
            by_claim[claim_id] = record
    cited = cited_artifact_index(required, by_claim)

    failed: list[str] = []
    incomplete: list[str] = []
    waived: list[str] = []
    per_claim: list[dict] = []
    if not required:
        incomplete.append("(required-claims list is empty - invalid run)")
    for claim_id in required:
        if claim_id in duplicates:
            incomplete.append(f"{claim_id}: duplicate records for claim_id (ambiguous)")
            per_claim.append({"claim_id": claim_id, "status": "duplicate-record"})
            continue
        record = by_claim.get(claim_id)
        if record is None:
            incomplete.append(f"{claim_id}: no record")
            per_claim.append({"claim_id": claim_id, "status": "missing-record"})
            continue
        defects = validate_record(
            record,
            args.expect_snapshot,
            args.expect_intent,
            args.expect_manifest,
            args.snapshot_exact,
            repo_root,
            obligation_kinds.get(claim_id),
            claim_evidence.get(claim_id),
            intent_path,
            expected_targets,
        )
        defects.extend(shared_artifact_defects(claim_id, record, cited))
        if defects:
            incomplete.append(f"{claim_id}: invalid record ({'; '.join(defects)})")
            per_claim.append({"claim_id": claim_id, "status": "invalid", "defects": defects})
            continue
        evidence_class = record["evidence_class"]
        result = record["result"]
        assumed = _assumed_evidence(record)
        if result == "FAIL":
            failed.append(f"{claim_id}: {evidence_class} FAIL - {record['scope']}")
            per_claim.append({"claim_id": claim_id, "status": "FAIL", "evidence_class": evidence_class})
        elif result == "INCOMPLETE":
            incomplete.append(f"{claim_id}: record result INCOMPLETE")
            per_claim.append({"claim_id": claim_id, "status": "INCOMPLETE", "evidence_class": evidence_class})
        elif assumed and not record["waiver"]:
            incomplete.append(f"{claim_id}: assumed or unverified evidence cannot PASS "
                              f"without a waiver ({', '.join(assumed)})")
            per_claim.append({"claim_id": claim_id, "status": "unwaived-assumption",
                              "evidence_class": evidence_class,
                              "assumed_evidence": assumed})
        else:
            if record["waiver"]:
                waived.append(claim_id)
            per_claim.append(
                {
                    "claim_id": claim_id,
                    "status": "PASS-waived" if record["waiver"] else "PASS",
                    "evidence_class": evidence_class,
                    "scope": record["scope"],
                }
            )

    if failed:
        verdict, code = "FAILED", 1
    elif incomplete:
        verdict, code = "INCOMPLETE", 3
    else:
        profiles = sorted({by_claim[claim]["bindings"]["profile"] for claim in required})
        verdict = f"VERIFIED[profile={'/'.join(profiles)}; binding={binding}]"
        if waived:
            verdict += f" (waived: {','.join(sorted(waived))})"
        code = 0
    report = {
        "gate": "semantic-evidence",
        "records": str(args.records),
        "repo_root": str(repo_root),
        "expected_snapshot": args.expect_snapshot,
        "intent_path": intent_path,
        "binding": binding,
        "dependency_expansion": dependency_expansion,
        "required_claims": required,
        "obligation_kinds": {claim: obligation_kinds[claim] for claim in required
                             if claim in obligation_kinds},
        "required_evidence": {claim: claim_evidence[claim] for claim in required
                              if claim in claim_evidence},
        "per_claim": per_claim,
        "failed": failed,
        "incomplete": incomplete,
        "verdict": verdict,
    }
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print("required claims: " + ",".join(required))
        for entry in per_claim:
            print(f"  [{entry['status']:>18}] {entry['claim_id']} ({entry.get('evidence_class', '-')})")
        for message in failed + incomplete:
            print(f"  ! {message}")
    print(f"\nVERDICT: {verdict}", file=sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
