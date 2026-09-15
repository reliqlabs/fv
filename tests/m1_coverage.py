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

Finally it pins cross-gate parity directly. The dashboard shares Gate B's
schema module, so a record Gate B rejects structurally must never render
as covered here. Section (i) builds a real repository-shaped evidence set
(records, obligation manifest, raw artifacts with matching digests) in a
temporary root, runs both tools over it, and asserts the anti-drift
property in the direction that matters: the dashboard exits 0 only where
Gate B does. The mutations are the ones an adversary named — a v3 record
with no cohort, an unreadable cohort entry, a strong record class over an
unverified execution, a witness-class execution under an invariant, a
bare `true` waiver, a waiver naming an id and nothing else, two records
for one claim, one raw artifact cited by two claims, a PASS bound to a
`+dirty` snapshot, a cohort record claiming a profile the producer never
writes, `required_targets` that omits a declared obligation or names an
undeclared one, a record bound to another obligation manifest, and an
`intent_path` that is not a path at all. For every record-level rule both
tools own, the case also requires the two defect lists to be identical, so
agreement on the exit code cannot hide two different reasons. One case is
a layer up: an obligation ID the producer could never write a record for
must be ERROR(2) in both tools, never a required set with missing-record
rows in one and an ERROR in the other.

The parity runs both ways: a pre-cohort (v2) record with its own profile,
its own `required_targets` and an artifact another claim also cites must
still pass both tools, so the cohort-schema rules cannot leak into the
legacy shape in one tool and not the other. Two documented boundaries are
asserted symmetric rather than closed: a v2 record's own profile reaches
the verdict scope in both tools, and under `--require` with no manifest
neither the obligation-manifest binding nor `required_targets` binds in
either tool — naming the manifest is what turns the same records into a
rejection on both sides.

No external toolchain required. Exit 0 pass, 1 fail.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DASHBOARD = REPO / "scripts" / "coverage_dashboard.py"
GATE = REPO / "scripts" / "check_evidence_records.py"
FIXTURES = REPO / "tests" / "fixtures" / "m1"
FAILURES: list[str] = []

ALL_CLAIMS = "B1,B2,B3,B4,W1,S1"

# Mirrors the dashboard's own BARE_VERIFIED regex. Kept independent here
# so this suite proves the token-discipline rule itself, not just that
# --check happens to pass on inputs that were never going to trip it.
BARE_VERIFIED = re.compile(r"VERIFIED(?!\[)")
# VERIFIED[<field>; <field>] optionally followed by the waiver suffix.
SCOPED_VERDICT = re.compile(
    r"^VERIFIED\[(?P<scope>[^\]]*)\](?: \(waived: (?P<waived>[^)]*)\))?$")


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

# The manifest these fixtures are judged against, written beside them: both
# tools derive a record's expected obligation_manifest_hash from the manifest
# bytes they are handed, so the records have to be bound to this file.
SYSTEM_MANIFEST_NAME = "obligations-system.json"

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


def execution(tool: str, result: str,
              evidence_class: str = "bounded-checked",
              claim: str = "SC1") -> dict:
    """One v3 cohort entry, shaped as the evidence producer writes it.

    The artifact is named the producer's own way, `<claim>-<run_id>.log`: a
    cohort record declares the producer profile and both tools hold that
    profile to the naming rule, so a plausible-looking stand-in would not be
    the shape either tool actually has to judge."""
    run_id = f"m1-system-{tool}"
    return {
        "tool": tool,
        "evidence_class": evidence_class,
        "command": [tool, "verify"],
        "cwd": ".",
        "toolchain_digests": {"executable": f"/usr/bin/{tool}",
                              "sha256": "4" * 64, "version": "1.0.0",
                              "version_exit_code": 0},
        "raw_output_path": f".fv/evidence/raw/{claim}-{run_id}.log",
        "raw_output_hash": "5" * 64,
        "result": result,
        "run_id": run_id,
    }


def record(claim_id: str, *, result: str = "PASS",
           evidence_class: str = "bounded-checked",
           executions: list[dict] | None = None,
           waiver: dict | None = None,
           manifest_hash: str = "2" * 64) -> dict:
    bindings = {
        "source_snapshot": "aaaaaaa1+worktree-clean",
        "intent_hash": "1" * 64,
        "obligation_manifest_hash": manifest_hash,
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
        # A cohort record is a v3 record: it is producer-written, so it carries
        # the producer profile and the canonical target, and derives its legacy
        # bindings from executions[0]. Both tools reject a cohort record that
        # does not, so a fixture skipping any of it would not be the shape they
        # actually have to judge.
        primary = executions[0]
        bindings.update({
            "intent_path": ".fv/intent.md",
            "parser_schema_version": "fv-evidence-run/v3",
            "profile": "producer-trusted-execution",
            "executions": executions,
            "command": json.dumps(primary["command"]),
            "configuration": {"cwd": primary["cwd"]},
            "toolchain_digests": primary["toolchain_digests"],
            "raw_output_path": primary["raw_output_path"],
            "raw_output_hash": primary["raw_output_hash"],
        })
    return {"claim_id": claim_id, "required": True,
            "evidence_class": evidence_class, "result": result,
            "scope": f"scope for {claim_id}", "bindings": bindings,
            "waiver": waiver}


def verdict_parts(verdict: str) -> dict:
    """A verdict banner split into the parts the two tools must agree on.

    They disagree on `binding` by construction — Gate B recomputes the
    snapshot, is pinned to one, or is told to skip it, while the dashboard
    never recomputes anything — so the binding mode is compared separately,
    never folded into the equality."""
    match = SCOPED_VERDICT.match(verdict)
    if match is None:
        return {"kind": verdict, "profiles": [], "waived": [], "binding": None}
    fields: dict[str, str] = {}
    for part in match.group("scope").split(";"):
        key, _, value = part.strip().partition("=")
        if key:
            fields[key] = value
    waived = match.group("waived") or ""
    return {
        "kind": "VERIFIED",
        "profiles": sorted(p for p in fields.get("profile", "").split("/") if p),
        "waived": sorted(w for w in waived.split(",") if w),
        "binding": fields.get("binding"),
    }


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
    manifest_hash = hashlib.sha256(
        (tmp / SYSTEM_MANIFEST_NAME).read_bytes()).hexdigest()
    records = [record("B1", result=b1, manifest_hash=manifest_hash),
               record("W1", result=w1, evidence_class="test-witnessed",
                      manifest_hash=manifest_hash)]
    if include_claim:
        records.append(record("SC1", result=claim_result, executions=cohort,
                              manifest_hash=manifest_hash))
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
          d2.get("verdict") == "VERIFIED[profile=bounded; binding=not-recomputed]"
          " (waived: W1)", f"verdict={d2.get('verdict')}")
    check("all-PASS subset: verdict discloses that no binding was recomputed",
          verdict_parts(d2.get("verdict", ""))["binding"] == "not-recomputed")
    check("all-PASS subset: payload echoes the same binding mode",
          d2.get("binding") == "not-recomputed")
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
    # The dashboard imports check_evidence_records.py's schema and mirrors its
    # G2 verdict logic. Run both on identical inputs and require the verdicts
    # to agree on kind, profile and waivers, so a gate change that is not
    # mirrored here fails loudly instead of drifting silently. `binding` is
    # the one field that must differ: Gate B recomputes the snapshot, is
    # pinned to one, or is told to skip it, while the dashboard never
    # recomputes anything and says so.
    # The shared fixture records predate the obligation-manifest binding and
    # carry a placeholder hash. Both tools now derive that expectation from the
    # manifest bytes they are handed and neither side of this comparison is told
    # what to expect, so the manifest-derived case runs on a copy rebound to the
    # manifest itself: otherwise the case would measure the staleness rule
    # instead of the verdict logic it exists to compare.
    with tempfile.TemporaryDirectory() as raw_rebound:
        rebound = Path(raw_rebound) / "records.json"
        rebound_records = json.loads(records.read_text())
        for rec in rebound_records:
            rec["bindings"]["obligation_manifest_hash"] = hashlib.sha256(
                manifest.read_bytes()).hexdigest()
        write_json(rebound, rebound_records)

        def gate_run(source: Path, *extra: str) -> tuple[int, str]:
            proc = subprocess.run(
                ["uv", "run", "--script", str(GATE), "--records", str(source),
                 "--allow-unbound", *extra, "--json"],
                capture_output=True, text=True, timeout=60)
            try:
                return proc.returncode, json.loads(proc.stdout)["verdict"]
            except (json.JSONDecodeError, KeyError):
                return proc.returncode, f"<gate-error rc={proc.returncode}>"

        for label, source, extra in (
            ("mixed", records, ["--require", ALL_CLAIMS]),
            ("all-PASS", records, ["--require", "B1,W1"]),
            ("FAIL-only", records, ["--require", "B2"]),
            ("missing-only", records, ["--require", "B4"]),
            ("via-manifest", rebound, ["--manifest", str(manifest)]),
        ):
            dash_code, dj, _ = run_json(source, *extra)
            gate_code, gv = gate_run(source, *extra)
            dash_parts = verdict_parts(dj.get("verdict", ""))
            gate_parts = verdict_parts(gv)
            comparable = {key: value for key, value in dash_parts.items()
                          if key != "binding"}
            check(f"no drift vs semantic gate ({label})",
                  dash_code == gate_code
                  and comparable == {key: value for key, value in gate_parts.items()
                                     if key != "binding"},
                  f"dashboard={dj.get('verdict')} rc={dash_code} "
                  f"gate={gv} rc={gate_code}")
            if dash_parts["kind"] == "VERIFIED":
                check(f"both tools disclose their binding mode ({label})",
                      dash_parts["binding"] == "not-recomputed"
                      and gate_parts["binding"] == "unbound",
                      f"dashboard={dash_parts['binding']} gate={gate_parts['binding']}")

    # ── (h) system claims are reported, and only pass on a full cohort ──
    with tempfile.TemporaryDirectory() as raw_tmp:
        tmp = Path(raw_tmp)
        sys_manifest = write_json(tmp / SYSTEM_MANIFEST_NAME, SYSTEM_MANIFEST)
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

        # --require naming a system claim pulls its depends_on into the
        # required set, exactly as Gate B does: a composition judged without
        # its parts would report them covered by omission.
        code, d_sub, _ = run_json(dep_incomplete, "--manifest", str(sys_manifest),
                                  "--require", "SC1")
        sub_row = row(d_sub, "SC1")
        check("--require subset keeps the manifest's cohort requirement",
              sub_row["required_evidence"] == ["quint", "kani"]
              and sub_row["evidence_gaps"] == [])
        check("--require SC1 expands depends_on into the required set",
              d_sub.get("dependency_expansion") == {"SC1": ["B1", "W1"]}
              and d_sub.get("required_claims") == ["SC1", "B1", "W1"],
              f"expansion={d_sub.get('dependency_expansion')} "
              f"required={d_sub.get('required_claims')}")
        check("expanded dependency is judged, so its INCOMPLETE record is a gap",
              sub_row["dependency_gaps"] == ["W1"]
              and sub_row["dependencies_not_evaluated"] == [],
              f"gaps={sub_row['dependency_gaps']} "
              f"unevaluated={sub_row['dependencies_not_evaluated']}")
        check("--require subset with an uncovered dependency -> exit 3",
              code == 3 and d_sub.get("verdict") == "INCOMPLETE",
              f"rc={code} verdict={d_sub.get('verdict')}")

        # The same subset over a fully covered set still passes, so the rule
        # above is the dependency's state, not the expansion itself.
        code, d_sub_ok, _ = run_json(covered, "--manifest", str(sys_manifest),
                                     "--require", "SC1")
        check("--require subset of a fully covered system claim -> exit 0",
              code == 0 and d_sub_ok.get("verdict", "").startswith("VERIFIED["),
              f"rc={code} verdict={d_sub_ok.get('verdict')}")

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

    # ── (i) cross-gate parity on repository-shaped v3 evidence ──────────
    # (g) compares verdicts on the shared v2 fixture set. This section builds
    # a real evidence tree — obligation manifest, v3 records, raw artifacts
    # whose digests match — so Gate B can run every check it has, then mutates
    # one thing at a time. The property under test is directional: whatever
    # else the two tools report, the dashboard may exit 0 only where Gate B
    # does. Anything weaker lets a coverage view bless evidence its own gate
    # rejects.
    with tempfile.TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        (root / ".fv").mkdir()
        parity_manifest = write_json(root / ".fv" / "obligations.json", {
            "version": 1,
            "invariants": [{"id": "A1", "name": "inv_a1"}],
            "witnesses": [{"id": "W1", "name": "wit_w1"}],
            "system_claims": [{"id": "SC1", "name": "claim_sc1",
                               "depends_on": ["A1", "W1"],
                               "required_evidence": ["quint", "kani"]}],
        })
        manifest_hash = hashlib.sha256(parity_manifest.read_bytes()).hexdigest()
        # One artifact body that satisfies every evidence class's PASS marker,
        # so a case varies the class without also varying whether the log
        # matches it. Exactly one canonical trailer, last line.
        artifact_body = ("No violation found\n[ok]\ntest result: ok.\n"
                         "VERIFICATION:- SUCCESSFUL\nCONFORMANCE: PASS\n"
                         "--- fv-evidence: exit=0 ---\n")
        artifact_hash = hashlib.sha256(artifact_body.encode()).hexdigest()

        def parity_execution(claim: str, tool: str, *, result: str = "PASS",
                             evidence_class: str = "bounded-checked") -> dict:
            # Producer artifact naming: Gate B requires
            # .fv/evidence/raw/<claim_id>-<run_id>.log under the
            # producer-trusted-execution profile, so the fixture is the shape
            # a real run writes rather than a plausible-looking stand-in.
            run_id = f"parity-{claim}-{tool}"
            relative = f".fv/evidence/raw/{claim}-{run_id}.log"
            artifact = root / relative
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_text(artifact_body)
            return {
                "tool": tool,
                "evidence_class": evidence_class,
                "command": [tool, "verify", claim],
                "cwd": ".",
                "toolchain_digests": {"executable": f"/usr/bin/{tool}",
                                      "sha256": "7" * 64, "version": "1.0.0",
                                      "version_exit_code": 0},
                "raw_output_path": relative,
                "raw_output_hash": artifact_hash,
                "result": result,
                "run_id": run_id,
            }

        def parity_record(claim: str, executions: list[dict], *,
                          evidence_class: str, waiver: object = None) -> dict:
            primary = executions[0]
            return {
                "claim_id": claim,
                "required": True,
                "evidence_class": evidence_class,
                "result": "PASS",
                "scope": f"parity scope for {claim}",
                "bindings": {
                    "source_snapshot": "sha256:" + "a" * 64,
                    "intent_path": ".fv/intent.md",
                    "intent_hash": "1" * 64,
                    "obligation_manifest_hash": manifest_hash,
                    "profile": "producer-trusted-execution",
                    "required_targets": ["A1", "W1", "SC1"],
                    "environment_policy": "omp-extension-tool",
                    "toolchain_digests": primary["toolchain_digests"],
                    "command": json.dumps(primary["command"]),
                    "configuration": {"cwd": primary["cwd"]},
                    "seeds": None,
                    "raw_output_hash": primary["raw_output_hash"],
                    "raw_output_path": primary["raw_output_path"],
                    "executions": executions,
                    "parser_schema_version": "fv-evidence-run/v3",
                    "run_id": f"parity-{claim}",
                },
                "waiver": waiver,
            }

        def parity_set() -> dict[str, dict]:
            """The covering evidence set: one record per obligation, each with
            a cohort Gate B accepts end to end."""
            return {
                "A1": parity_record(
                    "A1", [parity_execution("A1", "kani")],
                    evidence_class="bounded-checked"),
                "W1": parity_record(
                    "W1", [parity_execution("W1", "cargo-test",
                                            evidence_class="test-witnessed")],
                    evidence_class="test-witnessed"),
                "SC1": parity_record(
                    "SC1", [parity_execution("SC1", "quint"),
                            parity_execution("SC1", "kani")],
                    evidence_class="bounded-checked"),
            }

        def run_parity(name: str, by_claim: dict[str, dict]) -> tuple:
            """Both tools over one records directory. Returns
            (dashboard rc, dashboard payload, gate rc, gate verdict, gate report)."""
            directory = root / "sets" / name
            directory.mkdir(parents=True, exist_ok=True)
            for index, rec in enumerate(by_claim.values()):
                write_json(directory / f"{index}-{rec['claim_id']}.json", rec)
            dash_code, payload, _ = run_json(directory, "--manifest",
                                             str(parity_manifest))
            proc = subprocess.run(
                ["uv", "run", "--script", str(GATE), "--records", str(directory),
                 "--root", str(root), "--manifest", str(parity_manifest),
                 "--allow-unbound", "--json"],
                capture_output=True, text=True, timeout=60)
            try:
                gate_report = json.loads(proc.stdout)
                gate_verdict_text = gate_report["verdict"]
            except (json.JSONDecodeError, KeyError):
                gate_report = {}
                gate_verdict_text = f"<gate-error rc={proc.returncode}>"
            return dash_code, payload, proc.returncode, gate_verdict_text, gate_report

        def gate_defects(report: dict, claim: str) -> list[str]:
            """Gate B's defect list for one claim, or []."""
            for entry in report.get("per_claim", []):
                if entry.get("claim_id") == claim:
                    return entry.get("defects") or []
            return []

        def unverified_execution(by_claim: dict[str, dict]) -> dict:
            """A1's cohort re-declared at a weaker class than the record's."""
            by_claim["A1"] = parity_record(
                "A1", [parity_execution("A1", "kani",
                                        evidence_class="unverified")],
                evidence_class="code-enforced")
            return by_claim

        def witness_class_under_invariant(by_claim: dict[str, dict]) -> dict:
            by_claim["A1"] = parity_record(
                "A1", [parity_execution("A1", "kani",
                                        evidence_class="test-witnessed")],
                evidence_class="bounded-checked")
            return by_claim

        def no_cohort(by_claim: dict[str, dict]) -> dict:
            del by_claim["SC1"]["bindings"]["executions"]
            return by_claim

        def unreadable_cohort_entry(by_claim: dict[str, dict]) -> dict:
            stray = parity_execution("SC1", "verus")
            stray["tool"] = 123
            by_claim["SC1"]["bindings"]["executions"].append(stray)
            return by_claim

        def failing_execution(by_claim: dict[str, dict]) -> dict:
            by_claim["SC1"]["bindings"]["executions"].append(
                parity_execution("SC1", "verus", result="FAIL"))
            return by_claim

        def bare_true_waiver(by_claim: dict[str, dict]) -> dict:
            by_claim["W1"] = parity_record(
                "W1", [parity_execution("W1", "gnark",
                                        evidence_class="externally-assumed")],
                evidence_class="externally-assumed", waiver=True)
            return by_claim

        def shared_artifact(by_claim: dict[str, dict]) -> dict:
            """A1 cites the artifact W1 already earned.

            W1's own row is the pure witness of the rule: its record is untouched
            and its only defect is that a second claim now cites its log."""
            borrowed = by_claim["W1"]["bindings"]["executions"][0]
            by_claim["A1"]["bindings"]["executions"][0].update(
                raw_output_path=borrowed["raw_output_path"],
                raw_output_hash=borrowed["raw_output_hash"])
            by_claim["A1"]["bindings"].update(
                raw_output_path=borrowed["raw_output_path"],
                raw_output_hash=borrowed["raw_output_hash"])
            return by_claim

        def dirty_pass(by_claim: dict[str, dict]) -> dict:
            """The producer's own marker for a tree that moved under the run."""
            bindings = by_claim["A1"]["bindings"]
            bindings["source_snapshot"] = bindings["source_snapshot"] + "+dirty"
            return by_claim

        def non_producer_profile(by_claim: dict[str, dict]) -> dict:
            """A cohort record claiming a profile the producer never writes: it
            would keep the cohort schema while opting out of the producer rules
            keyed off the profile."""
            by_claim["A1"]["bindings"]["profile"] = "bounded"
            return by_claim

        def required_targets_short(by_claim: dict[str, dict]) -> dict:
            by_claim["A1"]["bindings"]["required_targets"] = ["A1", "SC1"]
            return by_claim

        def required_targets_extra(by_claim: dict[str, dict]) -> dict:
            by_claim["A1"]["bindings"]["required_targets"] = ["A1", "W1", "SC1",
                                                              "Z9"]
            return by_claim

        def foreign_manifest(by_claim: dict[str, dict]) -> dict:
            """A1's evidence bound to some other obligation manifest.

            The expectation is the hash of the manifest both tools were handed,
            so it is derivable with no repository access — and must be derived
            on both sides, or a coverage view reports evidence earned against a
            different obligation set as coverage of this one."""
            by_claim["A1"]["bindings"]["obligation_manifest_hash"] = "0" * 64
            return by_claim

        def unreadable_intent_path(by_claim: dict[str, dict]) -> dict:
            """The canonical target as an object rather than a path.

            Containment needs the repository root, but "is it a string at all"
            is record text, so the shape half belongs to both tools."""
            by_claim["A1"]["bindings"]["intent_path"] = {"path": ".fv/intent.md"}
            return by_claim

        def bare_id_waiver(by_claim: dict[str, dict]) -> dict:
            """A waiver carrying an id and nothing else: it names no approver
            and no scope, so it authorizes nobody to assume anything."""
            by_claim["W1"] = parity_record(
                "W1", [parity_execution("W1", "gnark",
                                        evidence_class="externally-assumed")],
                evidence_class="externally-assumed", waiver={"id": "WV-9"})
            return by_claim

        def named_waiver(by_claim: dict[str, dict]) -> dict:
            by_claim["W1"] = parity_record(
                "W1", [parity_execution("W1", "gnark",
                                        evidence_class="externally-assumed")],
                evidence_class="externally-assumed",
                waiver={"id": "WV-9", "approver": "reviewer",
                        "scope": "upstream gnark acceptance"})
            return by_claim

        baseline_code, baseline, gate_baseline_code, gate_baseline, _ = run_parity(
            "baseline", parity_set())
        check("parity baseline: covering v3 evidence -> dashboard exit 0",
              baseline_code == 0, f"rc={baseline_code} "
              f"verdict={baseline.get('verdict')}")
        check("parity baseline: covering v3 evidence -> Gate B exit 0",
              gate_baseline_code == 0, f"rc={gate_baseline_code} "
              f"verdict={gate_baseline}")
        base_parts = verdict_parts(baseline.get("verdict", ""))
        gate_base_parts = verdict_parts(gate_baseline)
        check("parity baseline: same verdict kind, profile and waivers",
              {k: v for k, v in base_parts.items() if k != "binding"}
              == {k: v for k, v in gate_base_parts.items() if k != "binding"},
              f"dashboard={baseline.get('verdict')} gate={gate_baseline}")
        check("parity baseline: binding modes are distinct and both disclosed",
              base_parts["binding"] == "not-recomputed"
              and gate_base_parts["binding"] == "unbound",
              f"dashboard={base_parts['binding']} gate={gate_base_parts['binding']}")

        # (label, mutation, claim whose row carries it, that row's dashboard
        # status, defect fragment both tools must name). A fragment is given
        # wherever the defect is a record-level rule both tools own, so the case
        # proves the shared rule rather than a coincidence of exit codes.
        for label, mutate, claim, expected_status, fragment in (
            ("v3 record with no cohort", no_cohort, "SC1", "invalid", None),
            ("unreadable cohort tool id", unreadable_cohort_entry, "SC1",
             "invalid", None),
            ("FAILing execution beneath a PASS record", failing_execution,
             "SC1", "evidence-gap", None),
            ("unverified execution under a code-enforced record",
             unverified_execution, "A1", "unwaived-assumption", None),
            ("witness-class execution under an invariant",
             witness_class_under_invariant, "A1", "invalid", None),
            ("bare true waiver on assumed evidence", bare_true_waiver, "W1",
             "invalid", "waiver is not an object"),
            # One artifact, two claims: W1's record is untouched, so its row is
            # the rule itself rather than a side effect of A1's mutation.
            ("cross-claim artifact reuse", shared_artifact, "W1", "invalid",
             "evidence cannot be shared between claims"),
            ("+dirty PASS record", dirty_pass, "A1", "invalid",
             "PASS record bound to a dirty snapshot"),
            ("cohort record with a non-producer profile", non_producer_profile,
             "A1", "invalid", "not the producer profile"),
            ("required_targets omitting a declared obligation",
             required_targets_short, "A1", "invalid", "missing ['W1']"),
            ("required_targets naming an undeclared obligation",
             required_targets_extra, "A1", "invalid", "unexpected ['Z9']"),
            ("record bound to another obligation manifest", foreign_manifest,
             "A1", "invalid", "bound to obligation manifest"),
            ("intent_path that is not a path", unreadable_intent_path, "A1",
             "invalid", "binding field 'intent_path' is not a nonempty string"),
            ("waiver naming an id and nothing else", bare_id_waiver, "W1",
             "invalid", "waiver is not attributable"),
        ):
            dash_code, payload, gate_code, gate_text, gate_json = run_parity(
                label.replace(" ", "-"), mutate(parity_set()))
            check(f"parity ({label}): dashboard reports INCOMPLETE, not coverage",
                  dash_code == 3 and payload.get("verdict") == "INCOMPLETE",
                  f"rc={dash_code} verdict={payload.get('verdict')}")
            check(f"parity ({label}): the row names the defect on {claim}",
                  row(payload, claim)["status"] == expected_status,
                  f"status={row(payload, claim)['status']}")
            check(f"parity ({label}): Gate B rejects the same evidence",
                  gate_code == 3, f"rc={gate_code} verdict={gate_text}")
            check(f"parity ({label}): dashboard never passes where Gate B does not",
                  not (dash_code == 0 and gate_code != 0),
                  f"dashboard rc={dash_code} gate rc={gate_code}")
            if fragment is None:
                continue
            dash_defects = row(payload, claim).get("defects") or []
            gate_list = gate_defects(gate_json, claim)
            check(f"parity ({label}): both tools report the same defect text",
                  any(fragment in defect for defect in dash_defects)
                  and sorted(dash_defects) == sorted(gate_list),
                  f"dashboard={dash_defects} gate={gate_list}")

        # The cohort-schema rules and artifact identity are v3's. A pre-cohort
        # record predates all of them and only validates under an explicit
        # freshness escape hatch, so both tools keep the legacy tolerance: its own
        # profile, its own target list, and one log cited by several claims. The
        # dashboard must not be stricter than the gate either.
        legacy_artifact = ".fv/evidence/raw/legacy-shared.log"
        (root / legacy_artifact).write_text(artifact_body)
        legacy_dir = root / "sets" / "v2-legacy"
        legacy_dir.mkdir(parents=True, exist_ok=True)
        for claim, klass in (("A1", "bounded-checked"), ("W1", "test-witnessed")):
            legacy = parity_record(claim, [parity_execution(claim, "quint")],
                                   evidence_class=klass)
            bindings = legacy["bindings"]
            del bindings["executions"]
            bindings.update(parser_schema_version="fv-evidence-run/v2",
                            profile="legacy-bounded",
                            required_targets=["Z9"],
                            command="quint verify",
                            configuration={"max_steps": 10},
                            raw_output_path=legacy_artifact,
                            raw_output_hash=artifact_hash)
            write_json(legacy_dir / f"{claim}.json", legacy)
        v2_code, v2_payload, _ = run_json(legacy_dir, "--manifest",
                                          str(parity_manifest),
                                          "--require", "A1,W1")
        v2_gate = subprocess.run(
            ["uv", "run", "--script", str(GATE), "--records", str(legacy_dir),
             "--root", str(root), "--manifest", str(parity_manifest),
             "--require", "A1,W1", "--allow-unbound", "--json"],
            capture_output=True, text=True, timeout=60)
        check("parity (v2 carve-out): both tools accept a pre-cohort record with "
              "its own profile, its own required_targets, and a shared artifact",
              v2_code == 0 and v2_gate.returncode == 0,
              f"dashboard rc={v2_code} verdict={v2_payload.get('verdict')} "
              f"gate rc={v2_gate.returncode} {v2_gate.stdout[-200:]}")
        check("parity (v2 carve-out): both name the record's own profile",
              verdict_parts(v2_payload.get("verdict", ""))["profiles"]
              == ["legacy-bounded"]
              and verdict_parts(json.loads(v2_gate.stdout or "{}")
                                .get("verdict", ""))["profiles"]
              == ["legacy-bounded"],
              f"dashboard={v2_payload.get('verdict')} gate={v2_gate.stdout[-200:]}")

        # The documented limit of --require on its own, asserted symmetric: with
        # no manifest there is no declared obligation set, so neither the
        # obligation-manifest binding nor required_targets binds in either tool.
        # Naming the manifest is what turns the same records into a rejection on
        # both sides, which is what keeps this a boundary and not a divergence.
        loose_dir = root / "sets" / "require-only"
        loose_dir.mkdir(parents=True, exist_ok=True)
        for index, rec in enumerate(foreign_manifest(parity_set()).values()):
            write_json(loose_dir / f"{index}-{rec['claim_id']}.json", rec)

        def loose_pair(*extra: str) -> tuple[int, int]:
            dash_rc, _, _ = run_json(loose_dir, *extra)
            gate = subprocess.run(
                ["uv", "run", "--script", str(GATE), "--records", str(loose_dir),
                 "--root", str(root), "--allow-unbound", "--json", *extra],
                capture_output=True, text=True, timeout=60)
            return dash_rc, gate.returncode

        loose_code, loose_gate_code = loose_pair("--require", "A1,W1,SC1")
        check("parity (--require without --manifest): manifest freshness binds in "
              "neither tool",
              loose_code == 0 and loose_gate_code == 0,
              f"dashboard rc={loose_code} gate rc={loose_gate_code}")
        pinned_code, pinned_gate_code = loose_pair("--manifest",
                                                   str(parity_manifest))
        check("parity (--manifest named): the same records are stale in both tools",
              pinned_code == 3 and pinned_gate_code == 3,
              f"dashboard rc={pinned_code} gate rc={pinned_gate_code}")

        # The same assumed-class evidence with a real waiver passes both, so
        # the rule above is the waiver's absence, not the class alone.
        waived_code, waived, gate_waived_code, gate_waived, _ = run_parity(
            "named-waiver", named_waiver(parity_set()))
        check("parity (named waiver): assumed evidence PASSes both tools",
              waived_code == 0 and gate_waived_code == 0,
              f"dashboard rc={waived_code} gate rc={gate_waived_code} "
              f"gate verdict={gate_waived}")
        check("parity (named waiver): both name W1 as waived",
              verdict_parts(waived.get("verdict", ""))["waived"] == ["W1"]
              and verdict_parts(gate_waived)["waived"] == ["W1"],
              f"dashboard={waived.get('verdict')} gate={gate_waived}")

        # --require naming only the system claim: both tools expand depends_on
        # into the required set, so a missing invariant record cannot hide
        # behind the composition that rests on it.
        partial_set = parity_set()
        del partial_set["A1"]
        subset_dir = root / "sets" / "require-subset"
        subset_dir.mkdir(parents=True, exist_ok=True)
        for index, rec in enumerate(partial_set.values()):
            write_json(subset_dir / f"{index}-{rec['claim_id']}.json", rec)
        sub_code, sub_payload, _ = run_json(subset_dir, "--manifest",
                                            str(parity_manifest), "--require", "SC1")
        sub_gate = subprocess.run(
            ["uv", "run", "--script", str(GATE), "--records", str(subset_dir),
             "--root", str(root), "--manifest", str(parity_manifest),
             "--require", "SC1", "--allow-unbound", "--json"],
            capture_output=True, text=True, timeout=60)
        sub_gate_report = json.loads(sub_gate.stdout) if sub_gate.stdout else {}
        check("parity (--require system claim): same dependency expansion",
              sub_payload.get("dependency_expansion")
              == sub_gate_report.get("dependency_expansion")
              == {"SC1": ["A1", "W1"]},
              f"dashboard={sub_payload.get('dependency_expansion')} "
              f"gate={sub_gate_report.get('dependency_expansion')}")
        check("parity (--require system claim): missing dependency record is a "
              "gap in both tools",
              sub_code == 3 and sub_gate.returncode == 3
              and row(sub_payload, "A1")["status"] == "missing-record",
              f"dashboard rc={sub_code} gate rc={sub_gate.returncode}")

        # Two records for one claim: Gate B refuses to choose between them.
        duplicated = parity_set()
        duplicate_dir = root / "sets" / "duplicate"
        duplicate_dir.mkdir(parents=True, exist_ok=True)
        for index, rec in enumerate(duplicated.values()):
            write_json(duplicate_dir / f"{index}-{rec['claim_id']}.json", rec)
        second = parity_record("A1", [parity_execution("A1", "quint")],
                               evidence_class="bounded-checked")
        write_json(duplicate_dir / "9-A1-again.json", second)
        dup_code, dup_payload, _ = run_json(duplicate_dir, "--manifest",
                                            str(parity_manifest))
        dup_gate = subprocess.run(
            ["uv", "run", "--script", str(GATE), "--records", str(duplicate_dir),
             "--root", str(root), "--manifest", str(parity_manifest),
             "--allow-unbound", "--json"],
            capture_output=True, text=True, timeout=60)
        check("parity (duplicate records): dashboard reports duplicate-record",
              dup_code == 3 and row(dup_payload, "A1")["status"] == "duplicate-record",
              f"rc={dup_code} status={row(dup_payload, 'A1')['status']}")
        check("parity (duplicate records): Gate B is INCOMPLETE too",
              dup_gate.returncode == 3, f"rc={dup_gate.returncode}")

        # Manifest grammar, not record content: an obligation ID the evidence
        # producer could never write a record for makes the manifest unusable.
        # Gate B calls that an ERROR, so a view that rendered it as a required
        # set with missing-record rows would report a weaker failure than the
        # gate for the same input — the same drift, one layer up.
        baseline_dir = root / "sets" / "baseline"
        for label, claim_id in (("outside the producer's claim_id grammar",
                                 "verus:contract::Machine"),
                                ("outside the obligation id grammar", "A 1")):
            unusable = write_json(root / ".fv" / "obligations-unusable.json", {
                "version": 1,
                "invariants": [{"id": claim_id, "name": "inv_bad"}],
                "witnesses": [{"id": "W1", "name": "wit_w1"}],
            })
            bad_code, bad_out, bad_err = run(baseline_dir, "--manifest",
                                             str(unusable))
            bad_gate = subprocess.run(
                ["uv", "run", "--script", str(GATE), "--records",
                 str(baseline_dir), "--root", str(root), "--manifest",
                 str(unusable), "--allow-unbound"],
                capture_output=True, text=True, timeout=60)
            check(f"parity (manifest id {label}): both tools exit 2 ERROR",
                  bad_code == 2 and bad_gate.returncode == 2 and bad_out == "",
                  f"dashboard rc={bad_code} gate rc={bad_gate.returncode}")
            check(f"parity (manifest id {label}): both name the same reason",
                  "malformed obligation manifest: invariants[0]" in bad_err
                  and "malformed obligation manifest: invariants[0]"
                  in bad_gate.stdout,
                  f"dashboard={bad_err.strip()[:120]} "
                  f"gate={bad_gate.stdout.strip()[:120]}")

        for label, path in (("baseline", root / "sets" / "baseline"),
                            ("duplicate records", duplicate_dir)):
            code, _, err_chk = run(path, "--manifest", str(parity_manifest),
                                   "--check")
            check(f"--check clean on parity fixture ({label})",
                  code == 0 and "CHECK: clean" in err_chk)

    print()
    if FAILURES:
        print(f"M1: {len(FAILURES)} failure(s)")
        return 1
    print("M1: all assertions passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
