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

RECORD SCHEMA — identical to check_evidence_records.py (see that file's
docstring for the full field list). This tool additionally accepts the
M5 forward-compat versioned envelope: a top-level JSON object carrying a
`records` key, e.g. `{"ledger_schema_version": "...", "records": [...]}`.
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

    evidence-gap     the record PASSes, but some required_evidence tool
                     never PASSed in the cohort (it failed, was
                     INCOMPLETE, or never ran at all — including a v2
                     record that carries no cohort), or some execution
                     in the cohort did not PASS even though the required
                     tools did: a cohort is atomic, so a non-PASS
                     execution beside the required ones is still a gap
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
e.g. `VERIFIED[profile=bounded; waived-or-assumed=W1]`. Individual claim
rows never render as "verified" either — a claim's row shows its
evidence_class and result (PASS/FAIL/INCOMPLETE/missing-record/invalid/
unwaived-assumption/evidence-gap/dependency-gap), never an unqualified
verdict word. `--check` scans this tool's own rendered output (table,
verdict banner, and JSON payload) and exits nonzero if a bare `VERIFIED`
(not immediately followed by `[`) would ever appear — the R26-style
self-conformance guarantee applied to the dashboard surface itself.

VERDICT (same G2 truth table as check_evidence_records.py; exit code)
    FAILED       (1)  any required claim has a valid record with result FAIL
    INCOMPLETE   (3)  any required claim is missing a record, or its record
                      is invalid, or its record result is INCOMPLETE, or it
                      rests on externally-assumed/unverified evidence
                      without a waiver, or it is a system claim with an
                      evidence or dependency gap, or the required-claims
                      list is empty
    VERIFIED[..] (0)  every required claim PASSes; scope names the profile
                      and every waived or externally-assumed claim
    ERROR        (2)  unreadable records/manifest, a manifest whose claim
                      IDs cannot be read, a --require ID absent from the
                      given manifest, or neither --require nor --manifest

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

EVIDENCE_CLASSES = {
    "code-enforced", "proof-discharged", "bounded-checked", "test-witnessed",
    "conformance-tested", "externally-assumed", "unverified",
}
RESULTS = {"PASS", "FAIL", "INCOMPLETE"}
ASSUMED_CLASSES = {"externally-assumed", "unverified"}
TOP_FIELDS = ("claim_id", "required", "evidence_class", "result", "scope",
              "bindings", "waiver")
BINDING_FIELDS = (
    "source_snapshot", "intent_hash", "obligation_manifest_hash", "profile",
    "required_targets", "environment_policy", "toolchain_digests", "command",
    "configuration", "seeds", "raw_output_hash", "parser_schema_version",
    "run_id",
)
# Keys whose value may be null (the key itself is still mandatory).
NULLABLE = {"seeds", "waiver"}

# Manifest collections, in the order their IDs join the required set.
# Same three collections and kind names Gate B derives obligations from.
OBLIGATION_COLLECTIONS = (
    ("invariants", "invariant"),
    ("witnesses", "witness"),
    ("system_claims", "system_claim"),
)
SYSTEM_CLAIM = "system_claim"
# Observed cohort result for a required_evidence tool that never ran.
NO_EXECUTION = "no-execution"

# Per-claim statuses that mean the claim is not covered by a passing
# record. Drives both the run verdict and the "incomplete" summary bucket.
GAP_STATUSES = {"missing-record", "invalid", "INCOMPLETE", "unwaived-assumption",
                "evidence-gap", "dependency-gap"}

UNSCOPED_VERDICT_RE = re.compile(r"VERIFIED(?!\[)")  # a bare, unqualified verdict


class ManifestError(Exception):
    """The manifest cannot yield a required-claim set this tool may render."""


def validate_record(rec: dict) -> list[str]:
    """Structural defects per the G1 schema (mirrors check_evidence_records.py's
    validate_record). Empty list means the record is valid."""
    defects = []
    for field in TOP_FIELDS:
        if field not in rec:
            defects.append(f"missing field {field!r}")
    if defects:
        return defects
    if rec["evidence_class"] not in EVIDENCE_CLASSES:
        defects.append(f"unknown evidence_class {rec['evidence_class']!r}")
    if rec["result"] not in RESULTS:
        defects.append(f"unknown result {rec['result']!r}")
    if not isinstance(rec["scope"], str) or not rec["scope"].strip():
        defects.append("scope is empty")
    bindings = rec["bindings"]
    if not isinstance(bindings, dict):
        defects.append("bindings is not an object")
        return defects
    for field in BINDING_FIELDS:
        if field not in bindings:
            defects.append(f"missing binding field {field!r}")
        elif bindings[field] in ("", [], {}) or \
                (bindings[field] is None and field not in NULLABLE):
            defects.append(f"empty binding field {field!r}")
    return defects


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
    record, still accepted, but unable to demonstrate cohort coverage)."""
    bindings = rec.get("bindings")
    raw = bindings.get("executions") if isinstance(bindings, dict) else None
    if not isinstance(raw, list):
        return None
    cohort = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        tool = entry.get("tool")
        cohort.append({
            "tool": tool if isinstance(tool, str) else None,
            "result": entry.get("result") if isinstance(entry.get("result"), str) else None,
            "evidence_class": entry.get("evidence_class")
            if isinstance(entry.get("evidence_class"), str) else None,
        })
    return cohort


def cohort_coverage(
    required_evidence: list[str], cohort: list[dict] | None
) -> tuple[dict[str, str], list[str], list[str]]:
    """Observed result per required tool ID, the required tool IDs with no PASS
    behind them, and every tool in the cohort with a non-PASS execution.

    A tool that ran more than once counts as covered if any of its executions
    PASSed; a tool that never ran reads as no-execution. The third list exists
    because a cohort is atomic: an execution that did not PASS is a defect even
    when it is not one of the required tools, so it cannot be dropped from the
    view just because required_evidence is satisfied without it.
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
    non_passing = [tool for tool, results in observed.items()
                   if any(r != "PASS" for r in results)]
    return coverage, gaps, non_passing


def evaluate_claim(cid: str, by_claim: dict[str, dict],
                   kinds: dict[str, str] | None = None,
                   system_claims: dict[str, dict] | None = None) -> dict:
    kinds = kinds or {}
    system_claims = system_claims or {}
    kind = kinds.get(cid)
    rec = by_claim.get(cid)
    if rec is None:
        row = {"claim_id": cid, "status": "missing-record", "evidence_class": None,
               "result": None, "scope": None, "waived": False, "defects": []}
    else:
        defects = validate_record(rec)
        if defects:
            row = {"claim_id": cid, "status": "invalid",
                   "evidence_class": rec.get("evidence_class"),
                   "result": rec.get("result"), "scope": rec.get("scope"),
                   "waived": False, "defects": defects}
        else:
            klass, result, scope = rec["evidence_class"], rec["result"], rec["scope"]
            waived = bool(rec["waiver"])
            if result == "FAIL":
                status = "FAIL"
            elif result == "INCOMPLETE":
                status = "INCOMPLETE"
            elif klass in ASSUMED_CLASSES and not waived:
                status = "unwaived-assumption"
            else:
                status = "PASS"
            row = {"claim_id": cid, "status": status, "evidence_class": klass,
                   "result": result, "scope": scope, "waived": waived,
                   "defects": []}
    row["obligation_kind"] = kind
    if kind != SYSTEM_CLAIM:
        return row
    spec = system_claims.get(cid, {})
    required_evidence = spec.get("required_evidence")
    row["required_evidence"] = required_evidence
    row["executions"] = executions_of(rec) if rec is not None else None
    if required_evidence is None:
        # Named as a system claim without a manifest entry declaring which
        # tools its cohort must contain: the cohort is still rendered, but
        # coverage is undeclared rather than assumed satisfied.
        row["evidence_coverage"] = None
        row["evidence_gaps"] = None
        row["non_passing_executions"] = None
    else:
        coverage, gaps, non_passing = cohort_coverage(
            required_evidence, row["executions"])
        row["evidence_coverage"] = coverage
        row["evidence_gaps"] = gaps
        row["non_passing_executions"] = non_passing
        if row["status"] == "PASS" and (gaps or non_passing):
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
                  "missing-record": "missing", "invalid": "invalid",
                  "unwaived-assumption": "unwaived_assumption",
                  "evidence-gap": "evidence_gap",
                  "dependency-gap": "dependency_gap"}
    counts = {v: 0 for v in status_key.values()}
    waived_or_assumed = []
    by_class: dict[str, dict[str, int]] = {}
    by_kind: dict[str, dict[str, int]] = {}
    for row in rows:
        counts[status_key[row["status"]]] += 1
        if row["waived"]:
            waived_or_assumed.append(row["claim_id"])
        kind_bucket = by_kind.setdefault(row.get("obligation_kind") or "unknown",
                                        {"pass": 0, "fail": 0, "gap": 0})
        if row["status"] == "PASS":
            kind_bucket["pass"] += 1
        elif row["status"] == "FAIL":
            kind_bucket["fail"] += 1
        else:
            kind_bucket["gap"] += 1
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
    scope = f"profile={'/'.join(profiles)}"
    waived = sorted(r["claim_id"] for r in rows if r["waived"])
    verdict = f"VERIFIED[{scope}]"
    if waived:
        verdict += f" (waived: {','.join(waived)})"
    return verdict, 0


def build_dashboard(records_path: Path, required: list[str],
                     records: list[dict], kinds: dict[str, str] | None = None,
                     system_claims: dict[str, dict] | None = None) -> tuple[dict, int]:
    kinds = kinds or {}
    by_claim: dict[str, dict] = {}
    for rec in records:
        cid = rec.get("claim_id") if isinstance(rec, dict) else None
        if isinstance(cid, str):
            by_claim[cid] = rec
    rows = [evaluate_claim(cid, by_claim, kinds, system_claims) for cid in required]
    apply_dependency_coverage(rows)
    summary = summarize(rows)
    verdict, code = compute_verdict(rows, by_claim, required)
    dashboard = {
        "gate": "coverage-dashboard",
        "records": str(records_path),
        "required_claims": required,
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
        f"invalid={s['invalid']} unwaived-assumption={s['unwaived_assumption']} "
        f"evidence-gap={s['evidence_gap']} "
        f"dependency-gap={s['dependency_gap']}"
    )
    if s["waived_or_assumed"]:
        lines.append(f"waived-or-assumed: {', '.join(s['waived_or_assumed'])}")
    lines.append("by evidence_class:")
    for klass, c in sorted(s["by_evidence_class"].items()):
        lines.append(f"  {klass}: pass={c['pass']} fail={c['fail']} "
                      f"incomplete={c['incomplete']} other={c['other']}")
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
                    help="comma-separated claim IDs the profile requires")
    ap.add_argument("--manifest", type=Path, default=None,
                    help="derive required claim IDs from an obligation manifest")
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
    if args.manifest:
        try:
            manifest_required, kinds, system_claims = load_manifest(args.manifest)
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

    dashboard, code = build_dashboard(args.records, required, records, kinds,
                                      system_claims)

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
