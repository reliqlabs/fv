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
}
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


def _inside(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False


def _raw_artifact_defects(record: dict, repo_root: Path) -> list[str]:
    bindings = record["bindings"]
    relative = bindings.get("raw_output_path")
    if not isinstance(relative, str) or not relative.strip():
        return ["unresolvable raw artifact: missing binding raw_output_path"]
    raw_path = (repo_root / relative).resolve()
    if Path(relative).is_absolute() or not _inside(repo_root.resolve(), raw_path):
        return ["unresolvable raw artifact: path escapes repository root"]
    if not raw_path.is_file():
        return [f"unresolvable raw artifact: {relative}"]
    raw = raw_path.read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    expected = bindings.get("raw_output_hash")
    if expected != actual:
        return [f"raw output hash mismatch: stored={expected!r} recomputed={actual}"]
    text = raw.decode(errors="replace")
    canonical = "--- fv-evidence: exit=0 ---"
    trailers = [line for line in text.splitlines()
                if re.fullmatch(r"--- fv-evidence: exit=\d+ ---", line)]
    if trailers != [canonical] or not text.splitlines() or text.splitlines()[-1] != canonical:
        return ["PASS artifact must end with one unique canonical exit=0 trailer"]
    configuration = bindings.get("configuration")
    override = configuration.get("pass_marker") if isinstance(configuration, dict) else None
    if isinstance(override, str) and override:
        missing = override not in text
    else:
        try:
            missing = re.search(EVIDENCE_CLASS_PASS_MARKERS[record["evidence_class"]], text) is None
        except re.error as error:
            return [f"invalid evidence-class marker regex: {error}"]
    return [f"PASS marker absent for evidence class {record['evidence_class']}"] if missing else []


def validate_record(
    record: dict,
    expect_snapshot: str | None,
    expect_intent: str | None = None,
    expect_manifest: str | None = None,
    snapshot_exact: bool = False,
    repo_root: Path | None = None,
    obligation_kind: str | None = None,
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
    for field in BINDING_FIELDS:
        if field not in bindings:
            defects.append(f"missing binding field {field!r}")
        elif bindings[field] in ("", [], {}) or (bindings[field] is None and field not in NULLABLE):
            defects.append(f"empty binding field {field!r}")
    if bindings.get("profile") == "producer-trusted-execution":
        toolchain = bindings.get("toolchain_digests")
        valid_toolchain = (
            isinstance(toolchain, dict)
            and isinstance(toolchain.get("executable"), str)
            and bool(toolchain["executable"])
            and isinstance(toolchain.get("sha256"), str)
            and re.fullmatch(r"[0-9a-f]{64}", toolchain["sha256"]) is not None
            and isinstance(toolchain.get("version"), str)
            and isinstance(toolchain.get("version_exit_code"), int)
        )
        if not valid_toolchain:
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
    if record["result"] == "PASS" and record["evidence_class"] in EVIDENCE_CLASSES and repo_root is not None:
        defects.extend(_raw_artifact_defects(record, repo_root))
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


def load_manifest(path: Path) -> tuple[list[str], dict[str, str]]:
    manifest = json.loads(path.read_text())
    required: list[str] = []
    kinds: dict[str, str] = {}
    for collection, kind in (("invariants", "invariant"), ("witnesses", "witness")):
        for item in manifest.get(collection, []):
            claim_id = item.get("id")
            if isinstance(claim_id, str) and claim_id:
                required.append(claim_id)
                kinds[claim_id] = kind
    return required, kinds


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
        if args.manifest:
            manifest_required, obligation_kinds = load_manifest(args.manifest)
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
