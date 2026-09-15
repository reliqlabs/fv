#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""R35: the non-destructive shadow migration of `.colosseum` into `.fv`.

`scripts/fv_migrate.py` is the one tool that reads a legacy tree, and the
property that makes it safe to run on a project whose trust artifacts are the
only record of past verification is that it cannot lose or rewrite anything:

  * dry run is the default and writes nothing at all;
  * `--apply` writes only under `.fv/`, and `.colosseum/` stays byte-identical
    (asserted with a digest over the whole legacy tree, before and after);
  * every legacy file is classified exactly once as mapped, preserved-history,
    or unsupported, so a file can never be silently dropped;
  * an unsupported artifact or a conflicting destination blocks the run in
    preflight, before the first byte is written;
  * every layer the legacy run manifest recorded reaches the plan, custom
    layer ids included, and a layer no plan execution can carry blocks the run
    instead of being quietly left out of a partial plan;
  * every synthesized obligation id is directly usable as an
    `fv_evidence_run` `claim_id`, so no obligation needs renaming by hand
    after the migration, and two legacy ids that would share one record path
    block the run instead of being silently merged or suffixed;
  * re-applying is byte-idempotent, and a destination that already exists with
    different content fails instead of being overwritten.

The semantic translations are asserted against their real consumers rather
than against a copy of the expected JSON: the migrated obligation manifest must
load under `check_evidence_records.load_manifest`, and the migrated plan must
load under `pyramid_run.load_plan`. A translation the gate or the runner would
reject is not a migration.

Exit 0 pass, 1 fail.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import check_evidence_records  # noqa: E402  the gate the manifest must satisfy
import fv_project  # noqa: E402  the exclusion parser the new list must satisfy
import pyramid_run  # noqa: E402  the runner the migrated plan must satisfy

MIGRATE = REPO / "scripts" / "fv_migrate.py"
EVIDENCE_RUN = REPO / "tools" / "evidence-run.ts"
FAILURES: list[str] = []

MAPPED = "mapped"
PRESERVED = "preserved-history"
UNSUPPORTED = "unsupported"


def check(label: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"  [ok]   {label}")
    else:
        print(f"  [FAIL] {label}" + (f" ({detail})" if detail else ""))
        FAILURES.append(label)


def evidence_claim_id_pattern() -> re.Pattern[str]:
    """The `claim_id` shape the real evidence producer accepts.

    Read out of `tools/evidence-run.ts` instead of restated here: that guard
    is what decides whether a migrated obligation can be discharged at all, so
    a copy of it in this test would keep passing after the producer moved.
    """
    source = EVIDENCE_RUN.read_text()
    match = re.search(r"/(\^\[[^/]+\$)/\.test\(params\.claim_id\)", source)
    if match is None:
        raise AssertionError(f"no claim_id guard found in {EVIDENCE_RUN}")
    return re.compile(match.group(1))


def migrated_id(target: str) -> str:
    """The id a `<layer>:<name>` legacy target migrates to, for a target whose
    two parts already carry only characters an evidence claim id allows: the
    colon separator becomes a dot. Spelled out rather than imported from
    `fv_migrate` so the expectation does not restate the implementation."""
    layer, separator, name = target.partition(":")
    if not separator:
        raise AssertionError(f"{target!r} carries no '<layer>:<name>' prefix")
    return f"{layer}.{name}"



# --------------------------------------------------------------------------
# fixtures: a dossier-shaped legacy project
# --------------------------------------------------------------------------

LEDGER = """# Ledger

## C-01
- Intent S7 at `docs/intent.md:313`; `code: crates/contract/src/machine/mod.rs:157`
- **Depends on:** `kani: merkle_promotion_not_duplication`

## C-02
- Intent B18 at `docs/intent.md:339`; `code: crates/contract/src/machine/mod.rs:694`
"""

INTENT_STUB = """# Intent: dossier
The canonical intent document is [`docs/intent.md`](../docs/intent.md). Read
that file; this one carries no normative text.
"""

VERIFIED_INPUTS = """# Paths whose contents can change what a verification layer decides.
#
# An include list, deliberately.
crates
quint
proofs
Cargo.toml
docs/intent.md
.colosseum/obligations.json
"""

OBLIGATIONS = {
    "schema": "colosseum-obligations",
    "version": 1,
    "claims": [
        {"claim_id": "C-01", "required": True},
        {"claim_id": "C-02", "required": True},
        {"claim_id": "C-03", "required": False},
    ],
}

G1_CLAIMS = {
    "schema": "colosseum-g1-claims",
    "version": 1,
    "profile": "dossier-bounded-composition/v1",
    "environment_policy": "single-host observation, unrecorded environment (TA-07)",
    "claims": [
        {
            "claim_id": "C-01",
            "evidence_class": "bounded-checked",
            "layers": ["quint", "kani", "proptest"],
            "required_targets": [
                "quint:invS7",
                "kani:merkle_promotion_not_duplication",
                "proptest:op_sequences_preserve_invariants",
            ],
            "scope": {
                "statement": "Every admission leaves entries_root canonical.",
                "discharged": ["quint invS7 holds exhaustively to depth 7"],
            },
            "waiver": {"excluded": ["no refinement argument links model to Rust"]},
        },
        {
            "claim_id": "C-02",
            "evidence_class": "bounded-checked",
            "layers": ["quint", "proptest"],
            "required_targets": [
                "quint:invB18",
                "proptest:op_sequences_preserve_invariants",
            ],
            "scope": {"statement": "The sentinel occurs only after a failed finalization."},
            "waiver": {"excluded": ["bounded Kani domain"]},
        },
        {
            "claim_id": "C-03",
            "evidence_class": "proved",
            "layers": ["lean", "verus"],
            "required_targets": [
                "lean:Dossier.KeyLineage.admitted_key_survives",
                "verus:key_lineage_contract",
            ],
            "scope": {"statement": "An admitted key survives every accepted trace."},
        },
    ],
}

QUINT_COMMAND = (
    "quint typecheck quint/dossier.qnt; "
    "quint run quint/dossier.qnt --invariant allInvariants --max-steps 24; "
    "quint verify quint/dossier.qnt --invariant allInvariants --max-steps 7"
)
PROPTEST_COMMAND = "cargo test -p dossier-contract --features mock-attestation --test property"

LAYER_RUNS = {
    "schema": "colosseum-layer-runs",
    "version": 2,
    "generated": "2026-09-15T01:21:48Z",
    "source_snapshot": "916401cb23d88057a79d85778eb597f991725f78",
    "runs": [
        {
            "layer": "kani",
            "cwd": ".",
            "environment": {},
            "command": "cargo kani -p dossier-contract --features verification",
            "exit_status": 0,
        },
        {
            "layer": "lean",
            "cwd": "proofs/lean",
            "environment": {},
            "command": "lake build",
            "exit_status": 0,
        },
        {
            "layer": "proptest",
            "cwd": ".",
            "environment": {"CARGO_TARGET_DIR": "/private/tmp/dossier-evidence/target"},
            "command": PROPTEST_COMMAND,
            "exit_status": 0,
        },
        {
            "layer": "quint",
            "cwd": ".",
            "environment": {},
            "command": QUINT_COMMAND,
            "exit_status": 0,
        },
        {
            "layer": "verus",
            "cwd": ".",
            "environment": {},
            "command": "verus proofs/verus/key_lineage.rs",
            "exit_status": 0,
        },
    ],
}

LEGACY_EVIDENCE = {
    "claim_id": "C-01",
    "parser_schema_version": "colosseum-evidence/v1",
    "result": "PASS",
}


def write_json(path: Path, document: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2) + "\n")


def scaffold(root: Path) -> Path:
    """A dossier-shaped legacy project: external intent, ledger citing it,
    split obligation manifests, a v2 run manifest, and history in every
    historical directory the legacy layout used."""
    legacy = root / ".colosseum"
    (root / "docs").mkdir(parents=True, exist_ok=True)
    (root / "docs" / "intent.md").write_text("# dossier intent\n\nS7. Roots stay canonical.\n")
    (root / "proofs" / "lean").mkdir(parents=True, exist_ok=True)
    legacy.mkdir(parents=True, exist_ok=True)
    (legacy / "intent.md").write_text(INTENT_STUB)
    (legacy / "ledger.md").write_text(LEDGER)
    (legacy / "verified-inputs.txt").write_text(VERIFIED_INPUTS)
    write_json(legacy / "obligations.json", OBLIGATIONS)
    write_json(legacy / "g1-claims.json", G1_CLAIMS)
    write_json(legacy / "evidence" / "runs" / "layer-runs.json", LAYER_RUNS)
    (legacy / "evidence" / "runs" / "quint.log").write_text("quint ok\n")
    write_json(legacy / "evidence" / "g1" / "C-01.json", LEGACY_EVIDENCE)
    (legacy / "evidence" / "kani-2026-08-26.md").write_text("kani prose evidence\n")
    (legacy / "attacks").mkdir(exist_ok=True)
    (legacy / "attacks" / "intent-2026-08-24.md").write_text("adversary round 1\n")
    (legacy / "attacks" / "panel" / "claude.md").parent.mkdir(exist_ok=True)
    (legacy / "attacks" / "panel" / "claude.md").write_text("voice artifact\n")
    (legacy / "changes").mkdir(exist_ok=True)
    (legacy / "changes" / "2026-09-14-record-storage.json").write_text('{"change": "storage"}\n')
    (legacy / "code-adversarial").mkdir(exist_ok=True)
    (legacy / "code-adversarial" / "2026-09-11-pr-review.md").write_text("six lenses\n")
    (legacy / "classifications").mkdir(exist_ok=True)
    (legacy / "classifications" / "ledger-2026-09-15.md").write_text("spec-wrong\n")
    (legacy / "verify").mkdir(exist_ok=True)
    (legacy / "verify" / "2026-09-14.md").write_text("pyramid report\n")
    (legacy / "scripts" / "__pycache__").mkdir(parents=True, exist_ok=True)
    (legacy / "scripts" / "run_verification_layers.sh").write_text("#!/usr/bin/env bash\nset -euo pipefail\n")
    (legacy / "scripts" / "__pycache__" / "emit.cpython-314.pyc").write_bytes(b"\x00\x01\x02binary")
    return legacy


def legacy_files(root: Path) -> set[str]:
    return {
        path.relative_to(root).as_posix()
        for path in (root / ".colosseum").rglob("*")
        if path.is_file() and not path.is_symlink()
    }


def tree_digest(path: Path) -> str:
    """Content digest over a whole tree: any byte change moves it."""
    digest = hashlib.sha256()
    for file in sorted(p for p in path.rglob("*") if p.is_file()):
        digest.update(file.relative_to(path).as_posix().encode())
        digest.update(b"\0")
        digest.update(hashlib.sha256(file.read_bytes()).digest())
        digest.update(b"\n")
    return digest.hexdigest()


def migrate(project: Path, *flags: str) -> tuple[int, str, str]:
    result = subprocess.run(
        [sys.executable, str(MIGRATE), str(project), *flags],
        capture_output=True, text=True, timeout=300,
    )
    return result.returncode, result.stdout, result.stderr


def report_of(project: Path, *flags: str) -> tuple[int, dict, str]:
    code, out, err = migrate(project, "--json", *flags)
    try:
        return code, json.loads(out), err
    except json.JSONDecodeError:
        return code, {}, out + err


def artifact_of(report: dict, source: str) -> dict | None:
    for artifact in report.get("artifacts", []):
        if artifact["source"] == source:
            return artifact
    return None


# --------------------------------------------------------------------------
# dry run
# --------------------------------------------------------------------------

def check_dry_run(tmp: Path) -> None:
    """The default run inventories everything and writes nothing."""
    root = tmp / "dry"
    scaffold(root)
    before = tree_digest(root)
    code, report, err = report_of(root)
    check("dry run exits 0 on a clean legacy tree", code == 0, f"exit={code} {err[-200:]}")
    check("dry run reports schema and mode",
          report.get("schema") == "fv-migration-report/v1" and report.get("mode") == "dry-run",
          f"{report.get('schema')} {report.get('mode')}")
    check("dry run status is ok", report.get("status") == "ok", str(report.get("unsupported")))
    check("dry run writes nothing at all",
          not (root / ".fv").exists() and tree_digest(root) == before)
    check("dry run still plans every write it would make",
          len(report["writes"]) > 0
          and all(write["action"] == "create" for write in report["writes"]),
          str({write["action"] for write in report["writes"]}))
    check("dry run plans writes only under .fv/",
          all(write["path"].startswith(".fv/") for write in report["writes"]),
          str([w["path"] for w in report["writes"] if not w["path"].startswith(".fv/")]))

    classified = [a["source"] for a in report["artifacts"] if "#" not in a["source"]]
    files = legacy_files(root)
    check("every legacy file is classified exactly once",
          sorted(classified) == sorted(files),
          f"missing={sorted(files - set(classified))} extra={sorted(set(classified) - files)}")
    check("no legacy file is classified twice",
          len(classified) == len(set(classified)))
    check("every classification is one of the three literals",
          {a["classification"] for a in report["artifacts"]} <= {MAPPED, PRESERVED, UNSUPPORTED},
          str({a["classification"] for a in report["artifacts"]}))
    check("counts agree with the artifact rows",
          report["counts"] == {
              name: sum(1 for a in report["artifacts"] if a["classification"] == name)
              for name in (MAPPED, PRESERVED, UNSUPPORTED)},
          str(report["counts"]))

    text_code, text_out, _ = migrate(root)
    check("text report names the dry run and the verdict",
          text_code == 0 and "dry run" in text_out and "VERDICT: OK" in text_out,
          text_out[-160:])
    json_code, json_out, json_err = migrate(root, "--json")
    check("--json emits only the JSON document on stdout",
          json_code == 0 and json_out.startswith("{") and json_out.rstrip().endswith("}")
          and json.loads(json_out) == report and json_err == "",
          json_out[:80] + json_err[-160:])

    first = migrate(root, "--json")[1]
    second = migrate(root, "--json")[1]
    check("the JSON report is byte-deterministic across runs", first == second)
    check("the JSON report is key-sorted",
          list(json.loads(first)) == sorted(json.loads(first)))


# --------------------------------------------------------------------------
# mapping
# --------------------------------------------------------------------------

def check_mapping(tmp: Path) -> None:
    """Each mapped artifact reaches the destination the FV layout expects."""
    root = tmp / "mapping"
    scaffold(root)
    code, report, err = report_of(root, "--apply")
    check("apply exits 0 and reports mode apply",
          code == 0 and report.get("mode") == "apply", f"exit={code} {err[-200:]}")

    expected = {
        ".colosseum/ledger.md": ".fv/ledger.md",
        ".colosseum/intent.md": ".fv/dispatch.json",
        ".colosseum/obligations.json": ".fv/obligations.json",
        ".colosseum/g1-claims.json": ".fv/obligations.json",
        ".colosseum/evidence/runs/layer-runs.json": ".fv/verification-plan.json",
    }
    for source, destination in expected.items():
        artifact = artifact_of(report, source)
        check(f"{source} is mapped to {destination}",
              artifact is not None and artifact["classification"] == MAPPED
              and artifact["destination"] == destination,
              str(artifact))
    check("exactly those five artifacts are mapped",
          sorted(a["source"] for a in report["artifacts"] if a["classification"] == MAPPED)
          == sorted(expected),
          str(sorted(a["source"] for a in report["artifacts"] if a["classification"] == MAPPED)))

    check("the ledger is copied verbatim",
          (root / ".fv/ledger.md").read_text() == (root / ".colosseum/ledger.md").read_text())
    check("a verbatim mapped file is not duplicated into history",
          not (root / ".fv/history/colosseum/ledger.md").exists())

    route = json.loads((root / ".fv/dispatch.json").read_text())["omp_native"]
    check("dispatch stores the repo-relative external intent the ledger cites",
          route["target_spec"] == "docs/intent.md" and route["project_root"] == ".",
          str({k: route.get(k) for k in ("project_root", "target_spec")}))
    check("the resolved dispatch target is the external intent",
          fv_project.resolve_target(root) == (root / "docs/intent.md").resolve())
    check("the pointer stub is not promoted to .fv/intent.md",
          not (root / ".fv/intent.md").exists())
    check("the pointer stub's bytes are preserved as history",
          (root / ".fv/history/colosseum/intent.md").read_text()
          == (root / ".colosseum/intent.md").read_text())

    # Fallback: no ledger citation, so the legacy entrypoint is the target.
    plain = tmp / "plain"
    scaffold(plain)
    (plain / ".colosseum/ledger.md").write_text("# Ledger\n\nNo citations.\n")
    (plain / "docs/intent.md").unlink()
    code, report, err = report_of(plain, "--apply")
    artifact = artifact_of(report, ".colosseum/intent.md")
    check("without a cited external intent the legacy intent becomes .fv/intent.md",
          code == 0 and artifact is not None and artifact["destination"] == ".fv/intent.md"
          and (plain / ".fv/intent.md").read_text() == (plain / ".colosseum/intent.md").read_text(),
          f"exit={code} {artifact}")
    check("the fallback dispatch target is .fv/intent.md",
          json.loads((plain / ".fv/dispatch.json").read_text())["omp_native"]["target_spec"]
          == ".fv/intent.md")


def check_history(tmp: Path) -> None:
    """Legacy history is preserved byte-for-byte and never as live state."""
    root = tmp / "history"
    scaffold(root)
    code, report, err = report_of(root, "--apply")
    check("apply exits 0", code == 0, f"exit={code} {err[-200:]}")

    for relative in sorted(legacy_files(root)):
        artifact = artifact_of(report, relative)
        if artifact is None or artifact["classification"] != PRESERVED:
            continue
        preserved = root / ".fv/history/colosseum" / relative[len(".colosseum/"):]
        check(f"{relative} is preserved byte-for-byte",
              artifact["destination"] == preserved.relative_to(root).as_posix()
              and preserved.is_file()
              and preserved.read_bytes() == (root / relative).read_bytes(),
              str(artifact))

    check("a compiled cache is history, not an unsupported artifact",
          artifact_of(report, ".colosseum/scripts/__pycache__/emit.cpython-314.pyc")["classification"]
          == PRESERVED)
    check("the legacy runner script is history, not a translated plan source",
          artifact_of(report, ".colosseum/scripts/run_verification_layers.sh")["classification"]
          == PRESERVED)
    check("legacy per-claim evidence never becomes a live v3 record",
          not (root / ".fv/evidence").exists()
          and (root / ".fv/history/colosseum/evidence/g1/C-01.json").is_file())
    check("the legacy evidence record keeps its legacy schema in history",
          json.loads((root / ".fv/history/colosseum/evidence/g1/C-01.json").read_text())
          ["parser_schema_version"] == "colosseum-evidence/v1")
    check("nested history directories are recreated",
          (root / ".fv/history/colosseum/attacks/panel/claude.md").read_text() == "voice artifact\n")


def check_verified_inputs(tmp: Path) -> None:
    """The include list is history; the exclusion list is written fresh."""
    root = tmp / "inputs"
    scaffold(root)
    code, report, err = report_of(root, "--apply")
    artifact = artifact_of(report, ".colosseum/verified-inputs.txt")
    check("the legacy include list is preserved history, not mapped",
          code == 0 and artifact is not None and artifact["classification"] == PRESERVED,
          str(artifact))
    check("the legacy include list survives verbatim",
          (root / ".fv/history/colosseum/verified-inputs.txt").read_text() == VERIFIED_INPUTS)

    text = (root / ".fv/verified-inputs.txt").read_text()
    prefixes = fv_project.parse_exclusions(text)
    check("the new exclusion list parses under fv_project",
          all(prefix in prefixes for prefix in fv_project.DEFAULT_EXCLUSIONS),
          str(prefixes))
    check("imported history is excluded from the verified-input snapshot",
          ".fv/history/" in prefixes, str(prefixes))
    check("no legacy include entry is copied into the exclusion list",
          not {"crates", "quint", "proofs", "Cargo.toml", "docs/intent.md"} & set(prefixes),
          str(prefixes))
    check("the exclusion list explains the inversion",
          "include list" in text and "history" in text)
    check("loaded exclusions cover the legacy tree and imported history",
          fv_project.is_excluded(".colosseum/ledger.md", prefixes)
          and fv_project.is_excluded(".fv/history/colosseum/ledger.md", prefixes))


# --------------------------------------------------------------------------
# obligations
# --------------------------------------------------------------------------

def check_obligations(tmp: Path) -> None:
    """Legacy claims become a manifest the evidence gate accepts."""
    root = tmp / "obligations"
    scaffold(root)
    code, report, err = report_of(root, "--apply")
    check("apply exits 0", code == 0, f"exit={code} {err[-200:]}")
    manifest = json.loads((root / ".fv/obligations.json").read_text())

    claims = {claim["id"]: claim for claim in manifest["system_claims"]}
    check("every legacy claim becomes a system claim",
          sorted(claims) == ["C-01", "C-02", "C-03"], str(sorted(claims)))
    check("depends_on is the migrated required_targets, in legacy order",
          claims["C-01"]["depends_on"]
          == [migrated_id(target) for target in G1_CLAIMS["claims"][0]["required_targets"]],
          str(claims["C-01"]["depends_on"]))
    check("depends_on carries no legacy colon-bearing target",
          not any(":" in dependency for claim in manifest["system_claims"]
                  for dependency in claim["depends_on"]),
          str([claim["depends_on"] for claim in manifest["system_claims"]]))
    check("an already-safe legacy claim id gets no synthesized legacy_id",
          all("legacy_id" not in claim for claim in manifest["system_claims"]),
          str([claim.get("legacy_id") for claim in manifest["system_claims"]]))
    check("required_evidence is the legacy layer list, not the target prefixes",
          claims["C-01"]["required_evidence"] == ["quint", "kani", "proptest"],
          str(claims["C-01"]["required_evidence"]))
    check("the required flag comes from the legacy obligations file",
          claims["C-01"]["required"] is True and claims["C-03"]["required"] is False,
          f"{claims['C-01']['required']} {claims['C-03']['required']}")
    check("scope is retained verbatim",
          claims["C-01"]["scope"] == G1_CLAIMS["claims"][0]["scope"])
    check("waiver is retained verbatim",
          claims["C-01"]["waiver"] == G1_CLAIMS["claims"][0]["waiver"])
    check("evidence_class is retained",
          claims["C-03"]["evidence_class"] == "proved")
    check("a claim without a legacy waiver gets no synthesized one",
          "waiver" not in claims["C-03"], str(claims["C-03"].get("waiver")))

    invariants = {item["id"] for item in manifest["invariants"]}
    witnesses = {item["id"] for item in manifest["witnesses"]}
    check("a proptest target becomes a witness",
          witnesses == {"proptest.op_sequences_preserve_invariants"}, str(witnesses))
    check("every non-test target becomes an invariant",
          invariants == {"quint.invS7", "quint.invB18",
                         "kani.merkle_promotion_not_duplication",
                         "lean.Dossier.KeyLineage.admitted_key_survives",
                         "verus.key_lineage_contract"},
          str(invariants))
    check("a target shared by two claims is synthesized once",
          len(manifest["witnesses"]) == 1
          and "C-01" in manifest["witnesses"][0]["statement"]
          and "C-02" in manifest["witnesses"][0]["statement"],
          str(manifest["witnesses"]))
    check("a witness carries the bare legacy target name",
          manifest["witnesses"][0]["name"] == "op_sequences_preserve_invariants")

    synthesized = manifest["invariants"] + manifest["witnesses"]
    legacy_targets = [target for claim in G1_CLAIMS["claims"]
                      for target in claim["required_targets"]]
    check("every synthesized obligation retains its exact legacy target",
          sorted(item["legacy_id"] for item in synthesized) == sorted(set(legacy_targets)),
          str([item.get("legacy_id") for item in synthesized]))
    check("each legacy_id is the target the migrated id came from",
          all(item["id"] == migrated_id(item["legacy_id"]) for item in synthesized),
          str([(item["id"], item.get("legacy_id")) for item in synthesized]))
    safe = evidence_claim_id_pattern()
    every_id = [item["id"] for item in synthesized + manifest["system_claims"]]
    check("every migrated id is a claim_id the evidence producer accepts",
          all(safe.fullmatch(identifier) for identifier in every_id),
          str([identifier for identifier in every_id if not safe.fullmatch(identifier)]))

    prefixes = tmp / "obligations-prefixes"
    scaffold(prefixes)
    write_json(prefixes / ".colosseum/g1-claims.json",
               {**G1_CLAIMS,
                "claims": [{**G1_CLAIMS["claims"][0],
                            "required_targets": ["test:roundtrip", "tests:decode",
                                                 "proptests:sequences", "kani:bounded"],
                            "layers": ["kani", "proptest"]},
                           *G1_CLAIMS["claims"][1:]]})
    code, _, err = report_of(prefixes, "--apply")
    converted = json.loads((prefixes / ".fv/obligations.json").read_text())
    check("every test-family prefix becomes a witness and the rest invariants",
          code == 0
          and {item["id"] for item in converted["witnesses"]}
          >= {"test.roundtrip", "tests.decode", "proptests.sequences"}
          and "kani.bounded" in {item["id"] for item in converted["invariants"]},
          f"exit={code} witnesses="
          f"{[i['id'] for i in converted['witnesses']]} {err[-120:]}")
    check("legacy profile and environment policy are retained",
          manifest["migration"]["profile"] == G1_CLAIMS["profile"]
          and manifest["migration"]["environment_policy"] == G1_CLAIMS["environment_policy"],
          str(manifest["migration"]))
    check("the manifest names both legacy sources",
          manifest["migration"]["source"]
          == [".colosseum/g1-claims.json", ".colosseum/obligations.json"],
          str(manifest["migration"]["source"]))

    required, kinds, evidence = check_evidence_records.load_manifest(root / ".fv/obligations.json")
    check("the migrated manifest loads under the evidence gate",
          set(claims) <= set(required) and invariants <= set(required)
          and witnesses <= set(required),
          str(required))
    check("the gate agrees on the obligation kinds",
          kinds["C-01"] == "system_claim"
          and kinds["quint.invS7"] == "invariant"
          and kinds["proptest.op_sequences_preserve_invariants"] == "witness",
          str(kinds))
    check("the gate reads each claim's required evidence tools",
          evidence == {"C-01": ["quint", "kani", "proptest"],
                       "C-02": ["quint", "proptest"],
                       "C-03": ["lean", "verus"]},
          str(evidence))

    for source in (".colosseum/obligations.json", ".colosseum/g1-claims.json"):
        artifact = artifact_of(report, source)
        check(f"{source} is reported as mapped with a detail",
              artifact["classification"] == MAPPED and artifact["detail"],
              str(artifact))
    check("the converted claim ids are named in the g1 detail",
          all(claim in artifact_of(report, ".colosseum/g1-claims.json")["detail"]
              for claim in ("C-01", "C-02", "C-03")),
          artifact_of(report, ".colosseum/g1-claims.json")["detail"])


# --------------------------------------------------------------------------
# obligation ids: dischargeable as written, traceable to the legacy target
# --------------------------------------------------------------------------

def with_claims(root: Path, claims: list[dict]) -> None:
    """Replace both legacy manifests with one claim set, all required."""
    write_json(root / ".colosseum/g1-claims.json", {**G1_CLAIMS, "claims": claims})
    write_json(root / ".colosseum/obligations.json",
               {**OBLIGATIONS,
                "claims": [{"claim_id": claim["claim_id"], "required": True}
                           for claim in claims]})


def check_obligation_ids(tmp: Path) -> None:
    """Every migrated id is one `fv_evidence_run` can discharge unchanged.

    The producer writes `.fv/evidence/records/<claim_id>.json`, so a legacy
    `<layer>:<name>` target is a path and not an id at all. The migration maps
    it into the producer's alphabet, keeps the exact legacy spelling in
    `legacy_id`, and refuses -- rather than suffixes -- a normalization that
    would put two legacy obligations on one record path.
    """
    safe = evidence_claim_id_pattern()

    rust = tmp / "ids-rust"
    scaffold(rust)
    rust_targets = ["verus:dossier::state::Machine::key_lineage",
                    "lean:Dossier.KeyLineage.admitted_key_survives"]
    with_claims(rust, [{**G1_CLAIMS["claims"][2],
                        "required_targets": rust_targets,
                        "layers": ["verus", "lean"]}])
    code, _, err = report_of(rust, "--apply")
    manifest = json.loads((rust / ".fv/obligations.json").read_text())
    ids = {item["legacy_id"]: item["id"] for item in manifest["invariants"]}
    check("a Rust `::` path target normalizes into the producer's alphabet",
          code == 0
          and ids.get("verus:dossier::state::Machine::key_lineage")
          == "verus.dossier-state-Machine-key_lineage",
          f"exit={code} {ids} {err[-120:]}")
    check("a dotted dossier target keeps its dots",
          ids.get("lean:Dossier.KeyLineage.admitted_key_survives")
          == "lean.Dossier.KeyLineage.admitted_key_survives", str(ids))
    check("depends_on names the normalized ids in legacy target order",
          manifest["system_claims"][0]["depends_on"]
          == [ids[target] for target in rust_targets],
          str(manifest["system_claims"][0]["depends_on"]))

    every_id = [item["id"] for item in
                manifest["invariants"] + manifest["witnesses"] + manifest["system_claims"]]
    records = rust / ".fv/evidence/records"
    records.mkdir(parents=True, exist_ok=True)
    for identifier in every_id:
        record = records / f"{identifier}.json"
        check(f"{identifier} is one filename, not a path",
              record.parent == records and safe.fullmatch(identifier), str(record))
        record.write_text(json.dumps({"claim_id": identifier, "required": True,
                                      "evidence_class": "proved", "result": "PASS"}) + "\n")
    loaded = {record["claim_id"] for record in check_evidence_records.load_records(records)}
    check("a record written at <id>.json is the record the gate reads back",
          loaded == set(every_id), str(sorted(loaded ^ set(every_id))))

    def refuses(name: str, claims: list[dict], *expected: str) -> None:
        root = tmp / f"ids-{name}"
        scaffold(root)
        with_claims(root, claims)
        dry_code, dry_report, _ = report_of(root)
        code, report, _ = report_of(root, "--apply")
        check(f"{name}: the run is blocked and exits 1",
              dry_code == 1 and dry_report.get("status") == "blocked" and code == 1,
              f"dry={dry_code} apply={code} status={dry_report.get('status')}")
        check(f"{name}: no .fv tree is written", not (root / ".fv").exists())
        check(f"{name}: one refusal names every id the migration refused to guess",
              any(all(fragment in entry for fragment in expected)
                  for entry in report["unsupported"]),
              str(report["unsupported"]))

    refuses("colliding-targets-one-claim",
            [{**G1_CLAIMS["claims"][0],
              "required_targets": ["quint:inv-S7", "quint:inv:S7"],
              "layers": ["quint"]}],
            "quint.inv-S7", "quint:inv-S7", "quint:inv:S7")
    refuses("colliding-targets-two-claims",
            [{**G1_CLAIMS["claims"][0], "required_targets": ["quint:inv-S7"],
              "layers": ["quint"]},
             {**G1_CLAIMS["claims"][1], "required_targets": ["quint:inv:S7"],
              "layers": ["quint"]}],
            "quint.inv-S7", "quint:inv-S7", "quint:inv:S7")
    refuses("colliding-claim-ids",
            [{**G1_CLAIMS["claims"][0], "claim_id": "C.01"},
             {**G1_CLAIMS["claims"][1], "claim_id": "C:01"}],
            "C.01", "C:01")
    refuses("target-normalizing-to-nothing",
            [{**G1_CLAIMS["claims"][0],
              "required_targets": ["quint:", "kani:bounded"],
              "layers": ["quint", "kani"]}],
            "quint:", "empty evidence record id")
    refuses("claim-id-normalizing-to-nothing",
            [{**G1_CLAIMS["claims"][0], "claim_id": "C:"}],
            "C:", "empty evidence record id")


# --------------------------------------------------------------------------
# verification plan
# --------------------------------------------------------------------------

def check_plan(tmp: Path) -> None:
    """Legacy shell strings become argv executions the runner can load."""
    root = tmp / "plan"
    scaffold(root)
    code, report, err = report_of(root, "--apply")
    check("apply exits 0", code == 0, f"exit={code} {err[-200:]}")
    document = json.loads((root / ".fv/verification-plan.json").read_text())
    check("the plan declares the v1 schema",
          document["schema"] == "fv-verification-plan/v1", str(document.get("schema")))
    check("legacy proptest is renamed to the built-in pyramid layer",
          "proptests" in document["layers"] and "proptest" not in document["layers"],
          str(sorted(document["layers"])))
    check("every plan layer id is a known layer or a valid custom id",
          all(name in pyramid_run.PLAN_LAYERS
              or (name not in pyramid_run.PLAN_RESERVED_LAYERS
                  and pyramid_run.PLAN_CUSTOM_ID.fullmatch(name))
              for name in document["layers"]),
          str(sorted(document["layers"])))
    check("every recorded legacy layer reaches the plan, quint included",
          set(document["layers"]) == {"proptests", "kani", "verus", "lean", "quint"},
          str(sorted(document["layers"])))
    check("the plan keys its layers in runner execution order",
          list(document["layers"]) == pyramid_run.plan_layer_order(document["layers"]),
          str(list(document["layers"])))

    plan = pyramid_run.load_plan(root / ".fv/verification-plan.json", root)
    check("the migrated plan loads under pyramid_run",
          sorted(plan["layers"]) == sorted(document["layers"]), str(sorted(plan["layers"])))

    proptests = document["layers"]["proptests"]["executions"]
    check("a single-command layer becomes one argv execution",
          len(proptests) == 1 and proptests[0]["argv"] == PROPTEST_COMMAND.split(),
          str(proptests))
    check("the recorded environment is carried as declared env",
          proptests[0]["env"] == {"CARGO_TARGET_DIR": "/private/tmp/dossier-evidence/target"},
          str(proptests[0].get("env")))
    check("a layer with no recorded environment declares no env",
          "env" not in document["layers"]["kani"]["executions"][0],
          str(document["layers"]["kani"]["executions"][0]))
    check("the recorded cwd is carried repo-relative",
          document["layers"]["lean"]["executions"][0]["cwd"] == "proofs/lean",
          str(document["layers"]["lean"]["executions"][0]))
    check("every execution declares a positive timeout",
          all(isinstance(execution["timeout_seconds"], int) and execution["timeout_seconds"] > 0
              for layer in document["layers"].values()
              for execution in layer["executions"]))
    check("a single-execution layer carries the bare legacy layer id as its tool",
          document["layers"]["kani"]["executions"][0]["evidence_tool"] == "kani"
          and document["layers"]["lean"]["executions"][0]["evidence_tool"] == "lean",
          str(document["layers"]["kani"]["executions"][0]))
    check("a layer required by no required claim is not gating",
          document["layers"]["lean"]["required"] is False
          and document["layers"]["kani"]["required"] is True,
          str({name: spec["required"] for name, spec in document["layers"].items()}))

    quint = document["layers"]["quint"]
    check("a legacy layer with no built-in step becomes a custom plan layer",
          [execution["argv"] for execution in quint["executions"]]
          == [segment.split() for segment in QUINT_COMMAND.split("; ")],
          str([execution["argv"] for execution in quint["executions"]]))
    check("the custom layer's segments carry distinct tools ending in the bare id",
          [execution["evidence_tool"] for execution in quint["executions"]]
          == ["quint:1", "quint:2", "quint"],
          str([execution["evidence_tool"] for execution in quint["executions"]]))
    check("a custom layer named by a required claim gates",
          quint["required"] is True, str(quint["required"]))
    check("the runner loads the custom layer as one cohort",
          len(plan["layers"]["quint"]["executions"]) == 3, str(plan["layers"].get("quint")))

    artifact = artifact_of(report, ".colosseum/evidence/runs/layer-runs.json")
    check("the run manifest is mapped to the plan",
          artifact["classification"] == MAPPED
          and artifact["destination"] == ".fv/verification-plan.json", str(artifact))
    check("the custom layer is named in the mapped detail",
          "quint -> quint" in artifact["detail"], artifact["detail"])
    check("no translated layer gets a deviation row",
          [item["source"] for item in report["artifacts"] if "#layers." in item["source"]] == [],
          str([item["source"] for item in report["artifacts"] if "#layers." in item["source"]]))
    check("the run manifest's own bytes still survive in history",
          json.loads((root / ".fv/history/colosseum/evidence/runs/layer-runs.json").read_text())
          == LAYER_RUNS)
    text = migrate(root)[1]
    check("the text report names the mapped plan without listing bulk history",
          ".fv/verification-plan.json" in text
          and ".colosseum/attacks/intent-2026-08-24.md" not in text,
          text[:400])

    # A semicolon sequence becomes one execution per segment, in order.
    multi = tmp / "plan-multi"
    scaffold(multi)
    runs = json.loads(json.dumps(LAYER_RUNS))
    for run in runs["runs"]:
        if run["layer"] == "kani":
            run["command"] = "cargo kani --harness a; cargo kani --harness b; cargo kani --harness c"
    write_json(multi / ".colosseum/evidence/runs/layer-runs.json", runs)
    code, report, err = report_of(multi, "--apply")
    executions = json.loads((multi / ".fv/verification-plan.json").read_text())["layers"]["kani"]["executions"]
    check("each semicolon segment becomes its own execution in source order",
          code == 0 and [execution["argv"][-1] for execution in executions] == ["a", "b", "c"],
          f"exit={code} {[e['argv'] for e in executions]}")
    check("the last segment carries the bare layer id and earlier ones are distinct",
          [execution["evidence_tool"] for execution in executions] == ["kani:1", "kani:2", "kani"],
          str([e["evidence_tool"] for e in executions]))
    check("no cohort declares the same evidence tool twice",
          len({execution["evidence_tool"] for execution in executions}) == len(executions))
    check("the multi-execution plan still loads under pyramid_run",
          len(pyramid_run.load_plan(multi / ".fv/verification-plan.json", multi)
              ["layers"]["kani"]["executions"]) == 3)

    # Two legacy names that rename onto the same plan layer share one cohort,
    # and each keeps its own bare evidence tool id: required_evidence names the
    # legacy id, so collapsing them onto one id would leave a claim undischargeable.
    merged = tmp / "plan-merged"
    scaffold(merged)
    runs = json.loads(json.dumps(LAYER_RUNS))
    runs["runs"].append({"layer": "proptests", "cwd": ".", "environment": {},
                         "command": "cargo test -p dossier-contract --test regression",
                         "exit_status": 0})
    write_json(merged / ".colosseum/evidence/runs/layer-runs.json", runs)
    code, report, err = report_of(merged, "--apply")
    document = json.loads((merged / ".fv/verification-plan.json").read_text())
    tools = [execution["evidence_tool"]
             for execution in document["layers"]["proptests"]["executions"]]
    check("two legacy layers renaming onto one plan layer share one cohort",
          code == 0 and len(document["layers"]["proptests"]["executions"]) == 2
          and tools == ["proptest", "proptests"],
          f"exit={code} {tools} {err[-160:]}")

    # Quoted arguments survive tokenization.
    quoted = tmp / "plan-quoted"
    scaffold(quoted)
    runs = json.loads(json.dumps(LAYER_RUNS))
    for run in runs["runs"]:
        if run["layer"] == "verus":
            run["command"] = 'verus --log "key lineage.rs"'
    write_json(quoted / ".colosseum/evidence/runs/layer-runs.json", runs)
    code, report, err = report_of(quoted, "--apply")
    argv = json.loads((quoted / ".fv/verification-plan.json").read_text())["layers"]["verus"]["executions"][0]["argv"]
    check("a quoted argument becomes one argv word",
          code == 0 and argv == ["verus", "--log", "key lineage.rs"], f"exit={code} {argv}")

    # A recorded cwd that no longer exists blocks, even for a layer no required
    # claim names: a plan silently missing `lean` would report the pyramid
    # green while the proof build the legacy manifest recorded never ran.
    stale = tmp / "plan-stale-cwd"
    scaffold(stale)
    shutil.rmtree(stale / "proofs/lean")
    dry_code, dry_report, _ = report_of(stale)
    code, report, err = report_of(stale, "--apply")
    row = artifact_of(report, ".colosseum/evidence/runs/layer-runs.json#layers.lean")
    check("a layer whose recorded cwd is gone blocks the run, required or not",
          dry_code == 1 and dry_report.get("status") == "blocked" and code == 1
          and not (stale / ".fv").exists()
          and row is not None and row["classification"] == UNSUPPORTED
          and "proofs/lean" in row["detail"],
          f"dry={dry_code} apply={code} {row}")
    check("no partial plan is even proposed when one layer cannot be translated",
          not any(write["path"] == ".fv/verification-plan.json" for write in report["writes"])
          and artifact_of(report, ".colosseum/evidence/runs/layer-runs.json")["classification"]
          == UNSUPPORTED,
          str([write["path"] for write in report["writes"]]))

    # A manifest whose only layer has no built-in pyramid step still migrates.
    custom_only = tmp / "plan-custom-only"
    scaffold(custom_only)
    write_json(custom_only / ".colosseum/evidence/runs/layer-runs.json",
               {**LAYER_RUNS, "runs": [run for run in LAYER_RUNS["runs"] if run["layer"] == "quint"]})
    code, report, err = report_of(custom_only, "--apply")
    document = json.loads((custom_only / ".fv/verification-plan.json").read_text())
    check("a manifest of only custom layers still produces a gating plan",
          code == 0 and list(document["layers"]) == ["quint"]
          and document["layers"]["quint"]["required"] is True,
          f"exit={code} {sorted(document.get('layers', {}))} {err[-160:]}")
    check("the custom-only plan loads under pyramid_run",
          list(pyramid_run.load_plan(custom_only / ".fv/verification-plan.json", custom_only)
               ["layers"]) == ["quint"])

    # A legacy layer whose id the plan schema reserves cannot be declared.
    reserved = tmp / "plan-reserved-id"
    scaffold(reserved)
    runs = json.loads(json.dumps(LAYER_RUNS))
    runs["runs"].append({"layer": "floors", "cwd": ".", "environment": {},
                         "command": "cargo test --all-features", "exit_status": 0})
    write_json(reserved / ".colosseum/evidence/runs/layer-runs.json", runs)
    code, report, err = report_of(reserved, "--apply")
    row = artifact_of(report, ".colosseum/evidence/runs/layer-runs.json#layers.floors")
    check("a legacy layer reusing a reserved plan id blocks instead of being dropped",
          code == 1 and not (reserved / ".fv").exists()
          and row is not None and row["classification"] == UNSUPPORTED
          and "reserved" in row["detail"],
          f"exit={code} {row}")


# --------------------------------------------------------------------------
# unsupported artifacts
# --------------------------------------------------------------------------

def check_unsupported(tmp: Path) -> None:
    """Every unsupported artifact blocks the run before any write."""
    def mutate(name: str, apply_mutation) -> tuple[int, dict, Path]:
        root = tmp / f"unsupported-{name}"
        scaffold(root)
        apply_mutation(root)
        dry_code, dry_report, _ = report_of(root)
        apply_code, apply_report, _ = report_of(root, "--apply")
        check(f"{name}: dry run is blocked and exits 1",
              dry_code == 1 and dry_report.get("status") == "blocked",
              f"exit={dry_code} status={dry_report.get('status')}")
        check(f"{name}: apply exits 1 and writes nothing",
              apply_code == 1 and not (root / ".fv").exists(),
              f"exit={apply_code} .fv={(root / '.fv').exists()}")
        check(f"{name}: the offending artifact is classified unsupported",
              any(a["classification"] == UNSUPPORTED for a in apply_report["artifacts"])
              and apply_report["unsupported"],
              str(apply_report.get("unsupported")))
        return apply_code, apply_report, root

    def shell_pipe(root: Path) -> None:
        runs = json.loads(json.dumps(LAYER_RUNS))
        for run in runs["runs"]:
            if run["layer"] == "kani":
                run["command"] = "cargo kani -p dossier-contract | tee kani.log"
        write_json(root / ".colosseum/evidence/runs/layer-runs.json", runs)

    _, report, _ = mutate("shell-pipe", shell_pipe)
    check("shell-pipe: the refusal names the layer and the construct",
          any("#layers.kani" in entry and "|" in entry for entry in report["unsupported"]),
          str(report["unsupported"]))

    for label, command in (
        ("shell-and", "cargo kani && cargo test"),
        ("shell-redirect", "cargo kani > kani.log"),
        ("shell-subst", "cargo kani --harness $(cat harness)"),
        ("shell-glob", "verus proofs/verus/*.rs"),
        ("shell-backtick", "cargo kani --harness `cat harness`"),
        ("shell-tilde", "verus ~/proofs/key_lineage.rs"),
        ("shell-unbalanced-quote", 'verus "proofs/key_lineage.rs'),
        ("shell-empty", "   "),
    ):
        def replace(root: Path, command=command) -> None:
            runs = json.loads(json.dumps(LAYER_RUNS))
            for run in runs["runs"]:
                if run["layer"] in ("kani", "verus"):
                    run["command"] = command
            write_json(root / ".colosseum/evidence/runs/layer-runs.json", runs)
        mutate(label, replace)

    mutate("symlink", lambda root: (root / ".colosseum/link.md").symlink_to(root / "docs/intent.md"))
    mutate("dangling-symlink", lambda root: (root / ".colosseum/gone.md").symlink_to(root / "nowhere.md"))
    mutate("fifo", lambda root: os.mkfifo(root / ".colosseum/pipe"))

    mutate("unknown-obligations-schema",
           lambda root: write_json(root / ".colosseum/obligations.json",
                                   {**OBLIGATIONS, "schema": "colosseum-obligations/v9"}))
    mutate("unknown-claims-version",
           lambda root: write_json(root / ".colosseum/g1-claims.json", {**G1_CLAIMS, "version": 9}))
    mutate("malformed-json",
           lambda root: (root / ".colosseum/g1-claims.json").write_text("{not json"))
    mutate("claims-not-an-array",
           lambda root: write_json(root / ".colosseum/g1-claims.json",
                                   {**G1_CLAIMS, "claims": {"C-01": {}}}))
    mutate("missing-required-targets",
           lambda root: write_json(
               root / ".colosseum/g1-claims.json",
               {**G1_CLAIMS, "claims": [{**G1_CLAIMS["claims"][0], "required_targets": []},
                                        *G1_CLAIMS["claims"][1:]]}))
    mutate("missing-layers",
           lambda root: write_json(
               root / ".colosseum/g1-claims.json",
               {**G1_CLAIMS, "claims": [{**G1_CLAIMS["claims"][0], "layers": []},
                                        *G1_CLAIMS["claims"][1:]]}))
    mutate("unprefixed-target",
           lambda root: write_json(
               root / ".colosseum/g1-claims.json",
               {**G1_CLAIMS, "claims": [{**G1_CLAIMS["claims"][0],
                                         "required_targets": ["invS7"]},
                                        *G1_CLAIMS["claims"][1:]]}))
    mutate("duplicate-claim-id",
           lambda root: write_json(
               root / ".colosseum/g1-claims.json",
               {**G1_CLAIMS, "claims": [*G1_CLAIMS["claims"], G1_CLAIMS["claims"][0]]}))
    mutate("non-boolean-required",
           lambda root: write_json(
               root / ".colosseum/obligations.json",
               {**OBLIGATIONS, "claims": [{"claim_id": "C-01", "required": "yes"},
                                          *OBLIGATIONS["claims"][1:]]}))
    mutate("unknown-run-manifest-version",
           lambda root: write_json(root / ".colosseum/evidence/runs/layer-runs.json",
                                   {**LAYER_RUNS, "version": 3}))
    mutate("non-string-environment",
           lambda root: write_json(
               root / ".colosseum/evidence/runs/layer-runs.json",
               {**LAYER_RUNS,
                "runs": [{**run, "environment": {"JOBS": 4}} if run["layer"] == "kani" else run
                         for run in LAYER_RUNS["runs"]]}))

    def quint_unparseable(root: Path) -> None:
        runs = json.loads(json.dumps(LAYER_RUNS))
        for run in runs["runs"]:
            if run["layer"] == "quint":
                run["command"] = 'quint verify "quint/dossier.qnt'
        write_json(root / ".colosseum/evidence/runs/layer-runs.json", runs)

    _, report, _ = mutate("required-layer-unparseable-command", quint_unparseable)
    check("required-layer-unparseable-command: the refusal names the layer and the claim's need",
          any("#layers.quint" in entry and "requires" in entry for entry in report["unsupported"]),
          str(report["unsupported"]))
    check("required-layer-unparseable-command: the run manifest is unsupported, never mapped",
          any(item["source"].endswith("runs/layer-runs.json")
              and item["classification"] == UNSUPPORTED for item in report["artifacts"]),
          str([item for item in report["artifacts"]
               if item["source"].endswith("runs/layer-runs.json")]))

    def quint_without_cwd(root: Path) -> None:
        runs = json.loads(json.dumps(LAYER_RUNS))
        for run in runs["runs"]:
            if run["layer"] == "quint":
                del run["cwd"]
        write_json(root / ".colosseum/evidence/runs/layer-runs.json", runs)

    _, report, _ = mutate("required-layer-missing-cwd", quint_without_cwd)
    check("required-layer-missing-cwd: the refusal names the absent cwd",
          any("#layers.quint" in entry and "cwd" in entry for entry in report["unsupported"]),
          str(report["unsupported"]))

    mutate("required-layer-escaping-cwd",
           lambda root: write_json(
               root / ".colosseum/evidence/runs/layer-runs.json",
               {**LAYER_RUNS,
                "runs": [{**run, "cwd": "../elsewhere"} if run["layer"] == "quint" else run
                         for run in LAYER_RUNS["runs"]]}))
    mutate("malformed-layer-name",
           lambda root: write_json(
               root / ".colosseum/evidence/runs/layer-runs.json",
               {**LAYER_RUNS,
                "runs": [{**run, "layer": "-quint"} if run["layer"] == "quint" else run
                         for run in LAYER_RUNS["runs"]]}))

    _, report, _ = mutate(
        "claim-without-detail",
        lambda root: (root / ".colosseum/g1-claims.json").unlink())
    check("claim-without-detail: every orphaned required claim is named",
          sum(1 for entry in report["unsupported"] if "#claims." in entry) == 3,
          str(report["unsupported"]))


# --------------------------------------------------------------------------
# apply, idempotency, conflicts
# --------------------------------------------------------------------------

def check_apply_and_idempotency(tmp: Path) -> None:
    root = tmp / "apply"
    scaffold(root)
    legacy_before = tree_digest(root / ".colosseum")
    project_before = {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*") if path.is_file()
    }

    code, report, err = report_of(root, "--apply")
    check("apply exits 0 and reports ok", code == 0 and report["status"] == "ok",
          f"exit={code} {err[-200:]}")
    check("apply leaves .colosseum byte-identical",
          tree_digest(root / ".colosseum") == legacy_before)
    after = {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*") if path.is_file()
    }
    touched = {path for path, digest in after.items() if project_before.get(path) != digest}
    check("apply touches nothing outside .fv/",
          all(path.startswith(".fv/") for path in touched), str(sorted(touched)))
    check("no pre-existing file is modified",
          all(after[path] == digest for path, digest in project_before.items()),
          str(sorted(path for path, digest in project_before.items() if after[path] != digest)))
    check("every planned write exists with the reported digest",
          all((root / write["path"]).is_file()
              and hashlib.sha256((root / write["path"]).read_bytes()).hexdigest() == write["sha256"]
              for write in report["writes"]),
          str([write["path"] for write in report["writes"]
               if not (root / write["path"]).is_file()]))
    check("the written set is exactly the planned set",
          {path.relative_to(root).as_posix() for path in (root / ".fv").rglob("*") if path.is_file()}
          == {write["path"] for write in report["writes"]})

    applied = tree_digest(root / ".fv")
    second_code, second_report, _ = report_of(root, "--apply")
    check("re-applying exits 0 and changes no byte",
          second_code == 0 and tree_digest(root / ".fv") == applied,
          f"exit={second_code}")
    check("re-applying reports every destination as identical",
          {write["action"] for write in second_report["writes"]} == {"identical"},
          str({write["action"] for write in second_report["writes"]}))
    check("re-applying plans the same destinations",
          [write["path"] for write in second_report["writes"]]
          == [write["path"] for write in report["writes"]])
    check("a dry run after apply is also all-identical",
          {write["action"] for write in report_of(root)[1]["writes"]} == {"identical"})
    check("re-applying leaves .colosseum byte-identical",
          tree_digest(root / ".colosseum") == legacy_before)


def check_conflicts(tmp: Path) -> None:
    """A destination that already differs fails; equal bytes are idempotent."""
    root = tmp / "conflict"
    scaffold(root)
    (root / ".fv").mkdir()
    (root / ".fv/ledger.md").write_text("a different ledger\n")
    dry_code, dry_report, _ = report_of(root)
    check("a differing destination blocks the dry run",
          dry_code == 1 and dry_report["status"] == "blocked"
          and any(".fv/ledger.md" in entry for entry in dry_report["conflicts"]),
          f"exit={dry_code} {dry_report.get('conflicts')}")
    check("the conflicting write is reported with action conflict",
          any(write["path"] == ".fv/ledger.md" and write["action"] == "conflict"
              for write in dry_report["writes"]),
          str([w for w in dry_report["writes"] if w["path"] == ".fv/ledger.md"]))
    apply_code, _, _ = report_of(root, "--apply")
    check("apply refuses and leaves the differing destination untouched",
          apply_code == 1 and (root / ".fv/ledger.md").read_text() == "a different ledger\n",
          f"exit={apply_code}")
    check("a blocked apply writes no other destination",
          not (root / ".fv/obligations.json").exists()
          and not (root / ".fv/history").exists())

    (root / ".fv/ledger.md").write_text((root / ".colosseum/ledger.md").read_text())
    code, report, _ = report_of(root, "--apply")
    check("a destination with equal bytes is idempotent, not a conflict",
          code == 0 and report["status"] == "ok"
          and any(write["path"] == ".fv/ledger.md" and write["action"] == "identical"
                  for write in report["writes"]),
          f"exit={code} {report.get('conflicts')}")

    # A directory or a symlink where a file must go is a conflict, not a crash.
    for label, place in (
        ("directory", lambda path: path.mkdir(parents=True)),
        ("symlink", lambda path: path.symlink_to(path.parent / "elsewhere.md")),
    ):
        blocked = tmp / f"conflict-{label}"
        scaffold(blocked)
        (blocked / ".fv").mkdir()
        place(blocked / ".fv/ledger.md")
        code, report, _ = report_of(blocked, "--apply")
        check(f"a {label} at a destination blocks the run",
              code == 1 and report["status"] == "blocked"
              and any(".fv/ledger.md" in entry for entry in report["conflicts"]),
              f"exit={code} {report.get('conflicts')}")

    # Dispatch is updated in place, so a foreign target is a conflict.
    existing = tmp / "conflict-dispatch"
    scaffold(existing)
    (existing / ".fv").mkdir()
    write_json(existing / ".fv/dispatch.json",
               {"omp_native": {"project_root": ".", "target_spec": "docs/other-intent.md"}})
    before = (existing / ".fv/dispatch.json").read_bytes()
    code, report, _ = report_of(existing, "--apply")
    check("a dispatch declaring another target blocks the run",
          code == 1 and any(".fv/dispatch.json" in entry for entry in report["conflicts"])
          and (existing / ".fv/dispatch.json").read_bytes() == before,
          f"exit={code} {report.get('conflicts')}")

    canonical = tmp / "conflict-dispatch-ok"
    scaffold(canonical)
    (canonical / ".fv").mkdir()
    (canonical / ".fv/dispatch.json").write_text(
        json.dumps({"omp_native": {"project_root": ".", "target_spec": "docs/intent.md",
                                   "profile": "local"}}, indent=4) + "\n")
    before = (canonical / ".fv/dispatch.json").read_bytes()
    code, report, _ = report_of(canonical, "--apply")
    check("a dispatch already naming the migrated target is left byte-identical",
          code == 0 and (canonical / ".fv/dispatch.json").read_bytes() == before
          and any(write["path"] == ".fv/dispatch.json" and write["action"] == "identical"
                  for write in report["writes"]),
          f"exit={code} {[w for w in report['writes'] if 'dispatch' in w['path']]}")

    unreadable = tmp / "conflict-dispatch-json"
    scaffold(unreadable)
    (unreadable / ".fv").mkdir()
    (unreadable / ".fv/dispatch.json").write_text("{not json")
    code, report, _ = report_of(unreadable, "--apply")
    check("an unreadable dispatch blocks the run instead of being overwritten",
          code == 1 and (unreadable / ".fv/dispatch.json").read_text() == "{not json",
          f"exit={code} {report.get('conflicts')}")


def check_cli(tmp: Path) -> None:
    root = tmp / "cli"
    scaffold(root)
    code, out, err = migrate(root)
    check("the text report is not JSON", code == 0 and not out.strip().startswith("{"))
    check("--help advertises the three-part CLI surface",
          all(flag in subprocess.run([sys.executable, str(MIGRATE), "--help"],
                                     capture_output=True, text=True).stdout
              for flag in ("PROJECT", "--apply", "--json")))
    missing = subprocess.run([sys.executable, str(MIGRATE)], capture_output=True, text=True)
    check("a missing PROJECT is a usage error", missing.returncode == 2, f"exit={missing.returncode}")
    absent = migrate(tmp / "no-such-project")
    check("an unresolvable PROJECT exits 2", absent[0] == 2, f"exit={absent[0]}")
    bare = tmp / "bare"
    bare.mkdir()
    code, out, err = migrate(bare)
    check("a project without .colosseum exits 1 and explains itself",
          code == 1 and ".colosseum" in err, f"exit={code} {err[-120:]}")
    file_project = tmp / "not-a-dir.txt"
    file_project.write_text("x\n")
    check("a PROJECT that is not a directory exits 2", migrate(file_project)[0] == 2)


def main() -> int:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw).resolve()
        print("dry run")
        check_dry_run(tmp)
        print("mapping")
        check_mapping(tmp)
        print("history")
        check_history(tmp)
        print("verified inputs")
        check_verified_inputs(tmp)
        print("obligations")
        check_obligations(tmp)
        print("obligation ids")
        check_obligation_ids(tmp)
        print("verification plan")
        check_plan(tmp)
        print("unsupported artifacts")
        check_unsupported(tmp)
        print("apply and idempotency")
        check_apply_and_idempotency(tmp)
        print("conflicts")
        check_conflicts(tmp)
        print("cli")
        check_cli(tmp)
    print()
    if FAILURES:
        print(f"R35: {len(FAILURES)} failure(s)")
        for failure in FAILURES:
            print(f"  - {failure}")
        return 1
    print("R35: all assertions passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
