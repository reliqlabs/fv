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
OBLIGATION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]*")
EVIDENCE_TOOL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:+/-]*")
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


def _execution_defects(execution: object, index: int, repo_root: Path,
                       record_pass: bool, seen_tools: set[str]) -> list[str]:
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
    elif tool in seen_tools:
        defects.append(f"{label}duplicate evidence tool {tool!r}: cohort coverage is ambiguous")
    else:
        seen_tools.add(tool)
    if execution["evidence_class"] not in EVIDENCE_CLASSES:
        defects.append(f"{label}unknown evidence_class {execution['evidence_class']!r}")
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
    elif record_pass and result != "PASS":
        defects.append(f"{label}result {result!r} cannot appear beneath a PASS record")
    if not isinstance(execution["run_id"], str) or not execution["run_id"].strip():
        defects.append(f"{label}run_id is empty")
    marker = execution.get("pass_marker")
    if "pass_marker" in execution and (not isinstance(marker, str) or not marker):
        defects.append(f"{label}pass_marker is empty")
    if defects:
        return defects
    artifact_defects, text = _read_artifact(repo_root, execution["raw_output_path"],
                                            execution["raw_output_hash"], label)
    defects.extend(artifact_defects)
    if text is not None and result == "PASS":
        defects.extend(_pass_artifact_defects(text, execution["evidence_class"], marker, label))
    return defects


def _cohort_defects(record: dict, repo_root: Path) -> list[str]:
    """Every execution of a v3 cohort, and the legacy bindings derived from its first."""
    bindings = record["bindings"]
    executions = bindings.get("executions")
    if not isinstance(executions, list) or not executions:
        return ["bindings.executions is not a nonempty array"]
    defects: list[str] = []
    seen_tools: set[str] = set()
    record_pass = record["result"] == "PASS"
    for index, execution in enumerate(executions):
        defects.extend(_execution_defects(execution, index, repo_root, record_pass, seen_tools))
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


def validate_record(
    record: dict,
    expect_snapshot: str | None,
    expect_intent: str | None = None,
    expect_manifest: str | None = None,
    snapshot_exact: bool = False,
    repo_root: Path | None = None,
    obligation_kind: str | None = None,
    required_evidence: list[str] | None = None,
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
    schema_v3 = (bindings.get("parser_schema_version") == EVIDENCE_SCHEMA_V3
                 or "executions" in bindings)
    expected_fields = BINDING_FIELDS + (V3_BINDING_FIELDS if schema_v3 else ())
    for field in expected_fields:
        if field not in bindings:
            defects.append(f"missing binding field {field!r}")
        elif bindings[field] in ("", [], {}) or (bindings[field] is None and field not in NULLABLE):
            defects.append(f"empty binding field {field!r}")
    if bindings.get("profile") == "producer-trusted-execution" and not _valid_toolchain(
        bindings.get("toolchain_digests")
    ):
        defects.append("producer evidence lacks resolved executable identity")
    if defects:
        return defects
    if expect_snapshot:
        snapshot = bindings.get("source_snapshot")
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
    if expect_manifest and bindings.get("obligation_manifest_hash") != expect_manifest:
        defects.append(
            "stale record: bound to obligation manifest "
            f"{bindings.get('obligation_manifest_hash')!r}, expected {expect_manifest!r}"
        )
    if obligation_kind is not None:
        compatible = OBLIGATION_EVIDENCE_COMPATIBILITY.get(obligation_kind)
        if compatible is None or record["evidence_class"] not in compatible:
            defects.append(
                f"incompatible evidence class {record['evidence_class']!r} for obligation kind {obligation_kind!r}"
            )
    if schema_v3 and repo_root is not None:
        intent_path_defect = _contained_path_defect(repo_root, bindings.get("intent_path"),
                                                    "intent_path", "")
        if intent_path_defect is not None:
            defects.append(intent_path_defect)
        defects.extend(_cohort_defects(record, repo_root))
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


def _validate_system_claim(claim_id: str, claim: dict, kinds: dict[str, str]) -> list[str]:
    """depends_on names declared invariants/witnesses; required_evidence names tool IDs.

    Confining dependencies to non-claim obligations is what makes a dependency
    cycle between system claims unrepresentable (a claim can never reach another
    claim, including itself), so the gate needs no cycle search. Widening
    depends_on to nested claims would require one.
    """
    for dependency in _id_list(claim_id, "depends_on", claim.get("depends_on"), OBLIGATION_ID):
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
    return _id_list(claim_id, "required_evidence", claim.get("required_evidence"), EVIDENCE_TOOL_ID)


def load_manifest(path: Path) -> tuple[list[str], dict[str, str], dict[str, list[str]]]:
    """Required claim IDs, their obligation kinds, and each system claim's evidence tools."""
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
    for claim_id, item in system_claims:
        claim_evidence[claim_id] = _validate_system_claim(claim_id, item, kinds)
    return required, kinds, claim_evidence


def current_source_snapshot(repo_root: Path) -> str:
    """Recompute the verified-input content snapshot records must be bound to."""
    return fv_project.content_snapshot(repo_root)


def current_intent_binding(repo_root: Path) -> tuple[str, str]:
    """Canonical target's repo-relative path and content hash."""
    target = fv_project.resolve_target(repo_root)
    return fv_project.repo_relative(repo_root, target), fv_project.target_hash(repo_root)


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
        if args.manifest:
            manifest_required, obligation_kinds, claim_evidence = load_manifest(args.manifest)
            if args.expect_manifest is None:
                args.expect_manifest = hashlib.sha256(args.manifest.read_bytes()).hexdigest()
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
        )
        if defects:
            incomplete.append(f"{claim_id}: invalid record ({'; '.join(defects)})")
            per_claim.append({"claim_id": claim_id, "status": "invalid", "defects": defects})
            continue
        evidence_class = record["evidence_class"]
        result = record["result"]
        if result == "FAIL":
            failed.append(f"{claim_id}: {evidence_class} FAIL - {record['scope']}")
            per_claim.append({"claim_id": claim_id, "status": "FAIL", "evidence_class": evidence_class})
        elif result == "INCOMPLETE":
            incomplete.append(f"{claim_id}: record result INCOMPLETE")
            per_claim.append({"claim_id": claim_id, "status": "INCOMPLETE", "evidence_class": evidence_class})
        elif evidence_class in ("externally-assumed", "unverified") and not record["waiver"]:
            incomplete.append(f"{claim_id}: {evidence_class} evidence cannot PASS without a waiver")
            per_claim.append({"claim_id": claim_id, "status": "unwaived-assumption", "evidence_class": evidence_class})
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
        verdict = f"VERIFIED[profile={'/'.join(profiles)}]"
        if waived:
            verdict += f" (waived: {','.join(sorted(waived))})"
        code = 0
    report = {
        "gate": "semantic-evidence",
        "records": str(args.records),
        "repo_root": str(repo_root),
        "expected_snapshot": args.expect_snapshot,
        "intent_path": intent_path,
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
