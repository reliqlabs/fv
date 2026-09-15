#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
M1 — coverage dashboard, sourced from typed G1 evidence, G2-conformant (M1).

coverage_dashboard.py renders a per-required-claim coverage view over G1
evidence records: it is not a gate, but its own surface must never violate
G2 — no unqualified "VERIFIED" token, ever. This suite exercises the
dashboard against a fixture set covering every claim disposition (PASS,
FAIL, INCOMPLETE, missing-record, waived assumption, unwaived assumption),
checks coverage counts and the per-evidence_class breakdown, checks the
run-level verdict against the G2 truth table, checks `--check` catches
its own would-be violations (proven directly against the token-discipline
regex, not just trivially green on already-clean fixtures), and checks
the M5 versioned-envelope input shape is accepted identically to a bare
list.

It also exercises the system_claim obligation kind: a system claim is
always part of the manifest-derived required set, is covered only when
every required_evidence tool ID PASSed in its record's execution cohort,
and reports an evidence gap or a dependency gap rather than a bare PASS
when it is not. Those cases are built in a temporary directory, so this
suite owns them without editing the shared m1 fixture set.

No external toolchain required. Exit 0 pass, 1 fail.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DASHBOARD = REPO / "scripts" / "coverage_dashboard.py"
FIXTURES = REPO / "tests" / "fixtures" / "m1"
FAILURES: list[str] = []

ALL_CLAIMS = "B1,B2,B3,B4,W1,S1"

# Mirrors the dashboard's own BARE_VERIFIED regex. Kept independent here
# so this suite proves the token-discipline rule itself, not just that
# --check happens to pass on inputs that were never going to trip it.
BARE_VERIFIED = re.compile(r"VERIFIED(?!\[)")


def check(label: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"  [ok]   {label}")
    else:
        suffix = f" ({detail})" if detail else ""
        print(f"  [FAIL] {label}{suffix}")
        FAILURES.append(label)


def run(records: Path, *extra: str) -> tuple[int, str, str]:
    proc = subprocess.run(
        ["uv", "run", "--script", str(DASHBOARD), "--records", str(records), *extra],
        capture_output=True, text=True, timeout=60,
    )
    return proc.returncode, proc.stdout, proc.stderr


def run_json(records: Path, *extra: str) -> tuple[int, dict, str]:
    code, out, err = run(records, "--json", *extra)
    try:
        payload = json.loads(out)
    except json.JSONDecodeError as e:
        return code, {"_parse_error": str(e), "_stdout": out}, err
    return code, payload, err


def row(dashboard: dict, claim_id: str) -> dict:
    for r in dashboard["rows"]:
        if r["claim_id"] == claim_id:
            return r
    raise KeyError(claim_id)


# ── system-claim fixture builders ───────────────────────────────────────
# Built here rather than in tests/fixtures/m1 so this suite can vary one
# dimension per case (which cohort tool PASSed, which dependency held)
# without multiplying shared fixture files.

SYSTEM_MANIFEST = {
    "version": 1,
    "invariants": [{"id": "B1", "name": "inv_b1"}],
    "witnesses": [{"id": "W1", "name": "witness_w1"}],
    "system_claims": [{
        "id": "SC1",
        "name": "claim_end_to_end",
        "depends_on": ["B1", "W1"],
        "required_evidence": ["quint", "kani"],
    }],
}


def execution(tool: str, result: str) -> dict:
    """One v3 cohort entry, shaped as the evidence producer writes it."""
    return {
        "tool": tool,
        "evidence_class": "bounded-checked",
        "command": [tool, "verify"],
        "cwd": ".",
        "toolchain_digests": {"executable": f"/usr/bin/{tool}",
                              "sha256": "4" * 64, "version": "1.0.0",
                              "version_exit_code": 0},
        "raw_output_path": f".fv/evidence/{tool}.txt",
        "raw_output_hash": "5" * 64,
        "result": result,
        "run_id": f"m1-system-{tool}",
    }


def record(claim_id: str, *, result: str = "PASS",
           evidence_class: str = "bounded-checked",
           executions: list[dict] | None = None) -> dict:
    bindings = {
        "source_snapshot": "aaaaaaa1+worktree-clean",
        "intent_hash": "1" * 64,
        "obligation_manifest_hash": "2" * 64,
        "profile": "bounded",
        "required_targets": ["B1", "W1", "SC1"],
        "environment_policy": "z2-worktree",
        "toolchain_digests": {"quint": "0.32.0"},
        "command": f"verify {claim_id}",
        "configuration": {"max_steps": 10},
        "seeds": None,
        "raw_output_hash": "3" * 64,
        "parser_schema_version": "quint-cli-0.32",
        "run_id": f"m1-system-{claim_id}",
    }
    if executions is not None:
        bindings["executions"] = executions
    return {"claim_id": claim_id, "required": True,
            "evidence_class": evidence_class, "result": result,
            "scope": f"scope for {claim_id}", "bindings": bindings,
            "waiver": None}


def write_json(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload, indent=2))
    return path


def system_records(tmp: Path, name: str, *,
                   b1: str = "PASS", w1: str = "PASS",
                   cohort: list[dict] | None = None,
                   claim_result: str = "PASS",
                   include_claim: bool = True) -> Path:
    """A records file for the SYSTEM_MANIFEST obligations, varying the
    dependency results and the system claim's execution cohort."""
    records = [record("B1", result=b1),
               record("W1", result=w1, evidence_class="test-witnessed")]
    if include_claim:
        records.append(record("SC1", result=claim_result, executions=cohort))
    return write_json(tmp / f"{name}.json", records)


def main() -> int:
    records = FIXTURES / "records.json"
    envelope = FIXTURES / "records-envelope.json"
    records_dir = FIXTURES / "records_dir"
    manifest = FIXTURES / "obligations.json"
    manifest_empty = FIXTURES / "obligations-empty.json"

    # ── (a) coverage counts + per-class breakdown, mixed fixture ────────
    code, d, err = run_json(records, "--require", ALL_CLAIMS)
    mixed_code = code
    check("mixed set: exit 1 (FAILED, a required claim FAILs)", code == 1)
    s = d.get("summary", {})
    check("mixed set: total_required == 6", s.get("total_required") == 6)
    check("mixed set: pass == 2 (B1, W1)", s.get("pass") == 2)
    check("mixed set: fail == 1 (B2)", s.get("fail") == 1)
    check("mixed set: incomplete == 1 (B3)", s.get("incomplete") == 1)
    check("mixed set: missing == 1 (B4)", s.get("missing") == 1)
    check("mixed set: invalid == 0", s.get("invalid") == 0)
    check("mixed set: unwaived_assumption == 1 (S1)",
          s.get("unwaived_assumption") == 1)
    check("mixed set: waived_or_assumed == ['W1']",
          s.get("waived_or_assumed") == ["W1"])
    by_class = s.get("by_evidence_class", {})
    check("per-class: bounded-checked pass=1 fail=1",
          by_class.get("bounded-checked") == {"pass": 1, "fail": 1, "incomplete": 0, "other": 0})
    check("per-class: test-witnessed incomplete=1",
          by_class.get("test-witnessed") == {"pass": 0, "fail": 0, "incomplete": 1, "other": 0})
    check("per-class: externally-assumed pass=1 (waived)",
          by_class.get("externally-assumed") == {"pass": 1, "fail": 0, "incomplete": 0, "other": 0})
    check("per-class: unverified other=1 (unwaived assumption, not a pass)",
          by_class.get("unverified") == {"pass": 0, "fail": 0, "incomplete": 0, "other": 1})

    # ── (b) missing required claims surface as gaps ─────────────────────
    b4 = row(d, "B4")
    check("B4 (no record) -> status missing-record", b4["status"] == "missing-record")
    check("B4 gap row carries no evidence_class", b4["evidence_class"] is None)
    s1 = row(d, "S1")
    check("S1 (unverified PASS, no waiver) -> status unwaived-assumption, not PASS",
          s1["status"] == "unwaived-assumption")
    w1 = row(d, "W1")
    check("W1 (externally-assumed PASS, waived) -> status PASS, waived=true",
          w1["status"] == "PASS" and w1["waived"] is True)

    # ── (c) verdict matches G2 truth table ───────────────────────────────
    check("mixed set verdict is exactly 'FAILED'", d.get("verdict") == "FAILED")

    code, d2, err2 = run_json(records, "--require", "B1,W1")
    check("all-PASS subset (B1,W1): exit 0", code == 0)
    check("all-PASS subset: verdict is scoped VERIFIED[...]",
          d2.get("verdict", "").startswith("VERIFIED[")
          and d2.get("verdict") == "VERIFIED[profile=bounded] (waived: W1)")
    check("all-PASS subset: verdict is never bare VERIFIED",
          not BARE_VERIFIED.search(d2.get("verdict", "")))

    code, _, err3 = run(records, "--require", "B2")
    check("FAIL-only claim -> exit 1", code == 1)
    check("FAIL-only claim -> stderr verdict FAILED", "VERDICT: FAILED" in err3)

    code, _, err4 = run(records, "--require", "B4")
    check("missing-only claim -> exit 3", code == 3)
    check("missing-only claim -> stderr verdict INCOMPLETE", "VERDICT: INCOMPLETE" in err4)

    code, _, err5 = run(records, "--manifest", str(manifest_empty))
    check("empty manifest (no invariants/witnesses) -> exit 3 INCOMPLETE",
          code == 3 and "VERDICT: INCOMPLETE" in err5)

    code, _, err6 = run(records, "--require", "")
    check("--require '' (no claim set named at all) -> exit 2, an error not a pass",
          code == 2)

    # ── stdout hygiene: --json stdout is pure JSON, nothing else ────────
    code, out_json, _ = run(records, "--require", ALL_CLAIMS, "--json")
    try:
        json.loads(out_json)
        clean_json_stdout = True
    except json.JSONDecodeError:
        clean_json_stdout = False
    check("--json stdout parses as JSON with no stray progress lines",
          clean_json_stdout)
    check("--json stdout never contains the literal token 'VERDICT:' "
          "(that's stderr-only)", "VERDICT:" not in out_json)

    # ── (d) --check passes on the dashboard's own output, every fixture ─
    for label, require_arg in (
        ("mixed set", ALL_CLAIMS),
        ("all-PASS subset", "B1,W1"),
        ("FAIL-only", "B2"),
        ("missing-only", "B4"),
    ):
        code, out, err = run(records, "--require", require_arg, "--check")
        check(f"--check clean on {label}", code == 0 and "CHECK: clean" in err)

    # ── (e) prove --check's underlying mechanism actually catches a leak
    # by asserting the token-discipline regex directly: it must flag a
    # bare VERIFIED and must NOT flag a properly scoped one. This is the
    # control that shows a real violation would be caught, not merely
    # that clean fixtures stay clean.
    check("token discipline: bare 'VERDICT: VERIFIED' IS flagged",
          bool(BARE_VERIFIED.search("VERDICT: VERIFIED")))
    check("token discipline: trailing bare VERIFIED IS flagged",
          bool(BARE_VERIFIED.search("some prose says VERIFIED here")))
    check("token discipline: scoped 'VERIFIED[profile=bounded]' is NOT flagged",
          not BARE_VERIFIED.search("VERDICT: VERIFIED[profile=bounded]"))
    check("token discipline: scoped with visible waiver suffix is NOT flagged",
          not BARE_VERIFIED.search(
              "VERIFIED[profile=bounded] (waived: W1)"))
    # cross-check against every line the dashboard actually emits for the
    # all-PASS fixture, across text, stderr, and --json renderings: the
    # word VERIFIED must appear at least once (it's the real verdict) and
    # every occurrence must be immediately followed by '['.
    code, text_out, text_err = run(records, "--require", "B1,W1")
    _, json_out, json_err = run(records, "--require", "B1,W1", "--json")
    combined = "\n".join([text_out, text_err, json_out, json_err])
    verified_occurrences = [m.start() for m in re.finditer("VERIFIED", combined)]
    check("dashboard output actually contains VERIFIED at least once "
          "(the check above isn't vacuous)", len(verified_occurrences) > 0)
    check("every VERIFIED occurrence in real output is immediately scoped",
          not BARE_VERIFIED.search(combined))

    # ── (f) versioned envelope accepted, equals bare-list result ────────
    code_env, d_env, _ = run_json(envelope, "--require", ALL_CLAIMS)
    check("versioned envelope: exit code matches bare-list",
          code_env == mixed_code and code_env == 1)
    d_env_norm = dict(d_env)
    d_env_norm["records"] = str(records)  # only the echoed input path differs
    check("versioned envelope: dashboard payload identical to bare-list input",
          d_env_norm == d)

    # ── directory loading + --manifest derivation (bonus coverage) ──────
    code, d_dir, _ = run_json(records_dir, "--require", "B1,B2,B3,W1,S1")
    check("directory of *.json records loads and aggregates", code == 1
          and d_dir.get("summary", {}).get("total_required") == 5)

    code, d_man, _ = run_json(records, "--manifest", str(manifest))
    check("--manifest derives required IDs from invariants[]+witnesses[]",
          d_man.get("required_claims") == ["B1", "B2", "B3", "B4", "W1", "S1"])

    # ── (g) no drift from the semantic gate ─────────────────────────────
    # The dashboard mirrors check_evidence_records.py's validator and G2
    # verdict logic. Run both on identical inputs and require the verdicts
    # to agree, so a future change to the gate that isn't mirrored here
    # fails loudly instead of drifting silently.
    gate = REPO / "scripts" / "check_evidence_records.py"

    def gate_verdict(*extra: str) -> str:
        gate_extra = [*extra]
        if "--manifest" in gate_extra:
            gate_extra += ["--expect-manifest", "2" * 64]
        proc = subprocess.run(
            ["uv", "run", "--script", str(gate), "--records", str(records),
             "--allow-unbound", *gate_extra, "--json"],
            capture_output=True, text=True, timeout=60)
        try:
            return json.loads(proc.stdout)["verdict"]
        except (json.JSONDecodeError, KeyError):
            return f"<gate-error rc={proc.returncode}>"

    for label, extra in (("mixed", ["--require", ALL_CLAIMS]),
                         ("all-PASS", ["--require", "B1,W1"]),
                         ("FAIL-only", ["--require", "B2"]),
                         ("missing-only", ["--require", "B4"]),
                         ("via-manifest", ["--manifest", str(manifest)])):
        _, dj, _ = run_json(records, *extra)
        gv = gate_verdict(*extra)
        check(f"no drift vs semantic gate ({label})",
              dj.get("verdict") == gv,
              f"dashboard={dj.get('verdict')} gate={gv}")

    # ── (h) system claims are reported, and only pass on a full cohort ──
    with tempfile.TemporaryDirectory() as raw_tmp:
        tmp = Path(raw_tmp)
        sys_manifest = write_json(tmp / "obligations-system.json", SYSTEM_MANIFEST)
        full_cohort = [execution("quint", "PASS"), execution("kani", "PASS")]

        # fully covered: every required_evidence tool PASSed, both
        # dependencies hold.
        covered = system_records(tmp, "covered", cohort=full_cohort)
        code, d_sc, err_sc = run_json(covered, "--manifest", str(sys_manifest))
        check("system claim joins the manifest-derived required set",
              d_sc.get("required_claims") == ["B1", "W1", "SC1"],
              f"required={d_sc.get('required_claims')}")
        check("system claim carries obligation_kind 'system_claim'",
              d_sc.get("obligation_kinds", {}).get("SC1") == "system_claim")
        sc1 = row(d_sc, "SC1")
        check("fully-covered system claim -> status PASS", sc1["status"] == "PASS",
              f"status={sc1['status']}")
        check("fully-covered system claim: per-tool coverage all PASS",
              sc1["evidence_coverage"] == {"quint": "PASS", "kani": "PASS"})
        check("fully-covered system claim: no evidence gaps",
              sc1["evidence_gaps"] == [] and sc1["non_passing_executions"] == [])
        check("fully-covered system claim: dependencies covered, none unevaluated",
              sc1["dependency_gaps"] == []
              and sc1["dependencies_not_evaluated"] == [])
        check("fully-covered system claim -> exit 0, scoped VERIFIED[...]",
              code == 0 and d_sc.get("verdict", "").startswith("VERIFIED["),
              f"rc={code} verdict={d_sc.get('verdict')}")
        check("fully-covered system claim counted in summary.system_claims",
              d_sc["summary"]["system_claims"]["total"] == 1
              and d_sc["summary"]["system_claims"]["covered"] == ["SC1"])
        check("system claim appears in summary.by_obligation_kind",
              d_sc["summary"]["by_obligation_kind"].get("system_claim")
              == {"pass": 1, "fail": 0, "gap": 0})

        # coverage gap: a required tool never ran.
        partial = system_records(tmp, "partial-cohort",
                                 cohort=[execution("quint", "PASS")])
        code, d_gap, err_gap = run_json(partial, "--manifest", str(sys_manifest))
        gap_row = row(d_gap, "SC1")
        check("required tool with no execution -> status evidence-gap, not PASS",
              gap_row["status"] == "evidence-gap", f"status={gap_row['status']}")
        check("missing tool named in evidence_gaps",
              gap_row["evidence_gaps"] == ["kani"])
        check("missing tool's observed result is 'no-execution'",
              gap_row["evidence_coverage"] == {"quint": "PASS",
                                               "kani": "no-execution"})
        check("evidence gap -> exit 3 INCOMPLETE (a gap is never a pass)",
              code == 3 and d_gap.get("verdict") == "INCOMPLETE",
              f"rc={code} verdict={d_gap.get('verdict')}")
        check("evidence gap counted in summary.evidence_gap",
              d_gap["summary"]["evidence_gap"] == 1)
        check("evidence gap listed in summary.system_claims.evidence_gaps",
              d_gap["summary"]["system_claims"]["evidence_gaps"]
              == {"SC1": ["kani"]}
              and d_gap["summary"]["system_claims"]["covered"] == [])

        # coverage gap: a required tool ran and did not PASS.
        failed_tool = system_records(
            tmp, "failed-tool",
            cohort=[execution("quint", "PASS"), execution("kani", "FAIL")])
        code, d_ft, _ = run_json(failed_tool, "--manifest", str(sys_manifest))
        ft_row = row(d_ft, "SC1")
        check("required tool FAIL inside a PASS record -> evidence-gap",
              ft_row["status"] == "evidence-gap")
        check("failed required tool's observed result is surfaced, not hidden",
              ft_row["evidence_coverage"]["kani"] == "FAIL"
              and ft_row["evidence_gaps"] == ["kani"]
              and ft_row["non_passing_executions"] == ["kani"])
        check("failed cohort member -> INCOMPLETE bucket, never FAILED",
              code == 3 and d_ft.get("verdict") == "INCOMPLETE",
              f"rc={code} verdict={d_ft.get('verdict')}")

        # coverage gap: cohort is atomic, so a non-required execution that
        # did not PASS is still a gap even though both required tools did.
        extra_bad = system_records(
            tmp, "extra-nonpass",
            cohort=[*full_cohort, execution("verus", "INCOMPLETE")])
        code, d_xb, _ = run_json(extra_bad, "--manifest", str(sys_manifest))
        xb_row = row(d_xb, "SC1")
        check("non-required cohort execution that did not PASS -> evidence-gap",
              xb_row["status"] == "evidence-gap" and code == 3,
              f"status={xb_row['status']} rc={code}")
        check("non-passing extra execution is named",
              xb_row["evidence_gaps"] == []
              and xb_row["non_passing_executions"] == ["verus"])

        # v2-shaped record: no cohort at all cannot demonstrate coverage.
        no_cohort = system_records(tmp, "no-cohort", cohort=None)
        code, d_nc, _ = run_json(no_cohort, "--manifest", str(sys_manifest))
        nc_row = row(d_nc, "SC1")
        check("system claim record with no executions -> evidence-gap",
              nc_row["status"] == "evidence-gap" and code == 3,
              f"status={nc_row['status']} rc={code}")
        check("cohort-less record reports every required tool as a gap",
              nc_row["evidence_gaps"] == ["quint", "kani"]
              and nc_row["executions"] is None)

        # dependency gap: the cohort is complete but a dependency is not
        # covered in this run.
        dep_incomplete = system_records(tmp, "dep-incomplete", w1="INCOMPLETE",
                                        cohort=full_cohort)
        code, d_dep, _ = run_json(dep_incomplete, "--manifest", str(sys_manifest))
        dep_row = row(d_dep, "SC1")
        check("uncovered dependency -> status dependency-gap despite full cohort",
              dep_row["status"] == "dependency-gap"
              and dep_row["evidence_gaps"] == [],
              f"status={dep_row['status']}")
        check("uncovered dependency is named", dep_row["dependency_gaps"] == ["W1"])
        check("dependency gap -> exit 3 INCOMPLETE",
              code == 3 and d_dep.get("verdict") == "INCOMPLETE")
        check("dependency gap listed in summary.system_claims.dependency_gaps",
              d_dep["summary"]["dependency_gap"] == 1
              and d_dep["summary"]["system_claims"]["dependency_gaps"]
              == {"SC1": ["W1"]})

        # a FAILing dependency still yields the run-level FAILED verdict on
        # its own row; the claim row shows why it is not covered.
        dep_failed = system_records(tmp, "dep-failed", b1="FAIL",
                                    cohort=full_cohort)
        code, d_df, _ = run_json(dep_failed, "--manifest", str(sys_manifest))
        check("FAILing dependency -> run verdict FAILED (exit 1)",
              code == 1 and d_df.get("verdict") == "FAILED",
              f"rc={code} verdict={d_df.get('verdict')}")
        check("FAILing dependency named on the system claim row",
              row(d_df, "SC1")["dependency_gaps"] == ["B1"])

        # --require subset: dependencies outside the required set are
        # reported as not evaluated, never counted as covered or as gaps.
        code, d_sub, _ = run_json(dep_incomplete, "--manifest", str(sys_manifest),
                                  "--require", "SC1")
        sub_row = row(d_sub, "SC1")
        check("--require subset keeps the manifest's cohort requirement",
              sub_row["required_evidence"] == ["quint", "kani"]
              and sub_row["evidence_gaps"] == [])
        check("dependency outside the required set is reported unevaluated",
              sub_row["dependencies_not_evaluated"] == ["B1", "W1"]
              and sub_row["dependency_gaps"] == [])
        check("--require subset of a covered system claim -> exit 0",
              code == 0 and d_sub.get("verdict", "").startswith("VERIFIED["),
              f"rc={code} verdict={d_sub.get('verdict')}")

        # a system claim with no record is a missing-record gap, not an
        # omitted row.
        absent = system_records(tmp, "claim-absent", include_claim=False)
        code, d_abs, _ = run_json(absent, "--manifest", str(sys_manifest))
        check("system claim without a record -> missing-record row, exit 3",
              row(d_abs, "SC1")["status"] == "missing-record"
              and d_abs["summary"]["missing"] == 1 and code == 3)

        # --require naming an ID the manifest does not declare is an error,
        # not a silently unkinded row.
        code, _, err_unknown = run(covered, "--manifest", str(sys_manifest),
                                   "--require", "SC9")
        check("--require ID absent from manifest -> exit 2 ERROR",
              code == 2 and "VERDICT: ERROR" in err_unknown)

        # an unreadable system_claims collection stops the run instead of
        # rendering a required set with the system claims dropped.
        for label, payload in (
            ("system_claims not an array",
             {**SYSTEM_MANIFEST, "system_claims": {"id": "SC1"}}),
            ("system claim missing required_evidence",
             {**SYSTEM_MANIFEST,
              "system_claims": [{"id": "SC1", "depends_on": ["B1"]}]}),
            ("system claim with no id",
             {**SYSTEM_MANIFEST,
              "system_claims": [{"depends_on": ["B1"],
                                 "required_evidence": ["quint"]}]}),
            ("system claim id colliding with an invariant",
             {**SYSTEM_MANIFEST,
              "system_claims": [{"id": "B1", "depends_on": ["W1"],
                                 "required_evidence": ["quint"]}]}),
        ):
            bad = write_json(tmp / "obligations-bad.json", payload)
            code, out_bad, err_bad = run(covered, "--manifest", str(bad))
            check(f"unusable manifest ({label}) -> exit 2 ERROR, nothing rendered",
                  code == 2 and "VERDICT: ERROR" in err_bad and out_bad == "",
                  f"rc={code}")

        # text rendering shows the kind and the cohort detail
        _, text_sc, _ = run(partial, "--manifest", str(sys_manifest))
        for needle in ("system_claim", "system claims:", "SC1 [evidence-gap]",
                       "quint=PASS", "kani=no-execution",
                       "missing PASS evidence: kani"):
            check(f"text render shows {needle!r}", needle in text_sc)

        for label, path in (("covered", covered), ("evidence gap", partial),
                            ("dependency gap", dep_incomplete),
                            ("no cohort", no_cohort)):
            code, _, err_chk = run(path, "--manifest", str(sys_manifest), "--check")
            check(f"--check clean on system-claim fixture ({label})",
                  code == 0 and "CHECK: clean" in err_chk)

    print()
    if FAILURES:
        print(f"M1: {len(FAILURES)} failure(s)")
        return 1
    print("M1: all assertions passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
