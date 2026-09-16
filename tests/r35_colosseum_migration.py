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
  * `--apply` writes only under the real `.fv/`, and `.colosseum/` stays
    byte-identical (asserted with a digest over the whole legacy tree, before
    and after), including when a symlink sits at `.fv`, at any component
    below it, or at the fixed staging prefix every migrated byte passes
    through before any destination sees it -- whether that link points out of
    the project or into `.colosseum/` itself;
  * every legacy file is classified exactly once as mapped, preserved-history,
    or unsupported, so a file can never be silently dropped, and a legacy
    field with no typed slot in the migrated manifest is carried under
    explicit provenance and named in a deviation row;
  * an unsupported artifact or a conflicting destination blocks the run in
    preflight, before the first byte is written, and an apply that fails
    after preflight rolls back and still reports each destination's fate,
    putting a destination it had already replaced back by renaming the
    original inode into place, so the file's mode and the rest of its
    metadata return with its bytes; a move-aside that itself fails is
    reported as the failed write it is rather than as a lost destination,
    because the file never moved;
  * the legacy `.colosseum/ledger.md` is run against the current Gate A
    (`scripts/check_ledger_references.py`, `--root PROJECT`, default
    strictness) before anything is mapped, because a ledger the project's
    own copied gate accepted is not automatically one the current gate
    accepts: an unbound or stale citation, a comment-only cited line, a
    prose-only ledger and a ledger the gate cannot read at all each block
    the run with one bounded `.colosseum/ledger.md#gate-a` row, write
    nothing, and leave the legacy bytes alone -- the readiness of the
    ledger is reported, never repaired here;
  * a refused ledger is a dead end unless the operator gets something they
    may edit, so the refusal names `--stage-ledger-remediation` and that
    mode copies `.colosseum/ledger.md` to `.fv/ledger.md` and nothing else:
    one write, no obligations, no plan, no history, no claim that a
    migration happened, never overwriting a copy already there, and
    refused outright when the source is not a regular file or the
    destination cannot be written without following a link;
  * a regular `.fv/ledger.md` is thereafter the project's live ledger, not a
    destination: the current gate judges that file, a pass keeps its bytes
    exactly as the operator left them even though they differ from the
    legacy ledger, the legacy ledger becomes history like every other legacy
    file, the include entry that named it follows the content to
    `.fv/ledger.md`, and a live ledger the gate still refuses blocks at
    `.fv/ledger.md#gate-a` -- the path the operator can actually fix;
  * a hard-killed apply strands nothing a verified-input snapshot hashes: the
    staging tree sits under one fixed, structurally excluded prefix, with a
    unique subdirectory per run that no later apply reuses or disturbs, and a
    concurrent run that removes the shared prefix mid-startup is retried and
    then named rather than turned into a partial write;
  * the dispatch target comes from the pointer stub before the ledger, and
    an ambiguous or absent target blocks rather than being elected by
    mention frequency;
  * every layer the legacy run manifest recorded reaches the plan, custom
    layer ids included; a layer no plan execution can carry blocks the run
    instead of being quietly left out of a partial plan; and a claim whose
    `required_evidence` no migrated execution can produce blocks the same
    way, including when the legacy tree recorded no run manifest at all, so
    no migration publishes required obligations against a project with no
    declared execution;
  * a layer any migrated claim names gates the migrated pyramid, whatever the
    legacy `required` flag said;
  * every synthesized obligation id is directly usable as an
    `fv_evidence_run` `claim_id`, so no obligation needs renaming by hand
    after the migration, and two legacy ids that would share one record path
    block the run instead of being silently merged or suffixed;
  * re-applying is byte-idempotent; a destination that already exists with
    different content fails instead of being overwritten, except
    `.fv/dispatch.json`, which is adopted by rewriting only the two fields
    the migration owns and keeping the mode the existing file carried.

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
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import check_evidence_records  # noqa: E402  the gate the manifest must satisfy
import fv_project  # noqa: E402  the policy parser the migrated list must satisfy
import pyramid_run  # noqa: E402  the runner the migrated plan must satisfy

MIGRATE = REPO / "scripts" / "fv_migrate.py"
EVIDENCE_RUN = REPO / "tools" / "evidence-run.ts"
GATE_A = REPO / "scripts" / "check_ledger_references.py"
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
    match = re.search(r"const CLAIM_ID = /(\^\[[^/]+\$)/", source) or re.search(
        r"/(\^\[[^/]+\$)/\.test\(params\.claim_id\)", source)
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

# The files a fixture ledger cites. Gate A resolves every citation against
# the project root, requires an `@sha256` content binding, and refuses a
# cited line that is empty or comment-only, so the fixture carries real
# files with real citable lines instead of plausible prose.
INTENT_FILE = "docs/intent.md"
CODE_FILE = "crates/contract/src/machine/mod.rs"
INTENT_S7 = "S7. Roots stay canonical."
INTENT_B18 = "B18. The sentinel occurs only after a failed finalization."
CODE_ADMIT = "        self.entries_root = recompute_root(&self.entries);"
CODE_FINALIZE = "        self.sentinel = Sentinel::AfterFailure;"
CODE_COMMENT = "    // admission recomputes the canonical root"

INTENT_DOC = f"""# dossier intent

{INTENT_S7}

{INTENT_B18}
"""

CODE_DOC = f"""use crate::merkle::recompute_root;

impl Machine {{
{CODE_COMMENT}
    pub fn admit(&mut self) -> Result<()> {{
{CODE_ADMIT}
        Ok(())
    }}

    pub fn finalize(&mut self) -> Result<()> {{
{CODE_FINALIZE}
        Ok(())
    }}
}}
"""


def line_hash(line: str) -> str:
    """Gate A's content binding: sha256 of the rstripped line, 12 hex chars.
    Spelled out rather than imported so a fixture citation cannot inherit a
    binding the gate stopped computing that way."""
    return hashlib.sha256(line.rstrip().encode()).hexdigest()[:12]


def line_number(root: Path, relative: str, text: str) -> int:
    lines = (root / relative).read_text().splitlines()
    matches = [index for index, line in enumerate(lines, start=1) if line == text]
    if len(matches) != 1:
        raise AssertionError(f"{relative}: {text!r} appears {len(matches)} times")
    return matches[0]


def cite(root: Path, relative: str, text: str, *, bind: str | None = "") -> str:
    """A citation of a known line in one of the three shapes Gate A tells
    apart: content-bound to the line as it stands (the default), unbound
    (`bind=None`), or bound to the binding given."""
    location = f"{relative}:{line_number(root, relative, text)}"
    if bind is None:
        return location
    return f"{location}@sha256:{bind or line_hash(text)}"


def ledger_text(root: Path) -> str:
    """The ledger the fixture carries: every citation resolves under the
    project root and carries the binding the current Gate A requires, so a
    migration of this project is never blocked on ledger readiness."""
    return (
        "# Ledger\n"
        "\n"
        "## C-01\n"
        f"- Intent S7 at `{cite(root, INTENT_FILE, INTENT_S7)}`; "
        f"`code: {cite(root, CODE_FILE, CODE_ADMIT)}`\n"
        "- **Depends on:** `kani: merkle_promotion_not_duplication`\n"
        "\n"
        "## C-02\n"
        f"- Intent B18 at `{cite(root, INTENT_FILE, INTENT_B18)}`; "
        f"`code: {cite(root, CODE_FILE, CODE_FINALIZE)}`\n"
    )


def code_only_ledger(root: Path, *prose: str) -> str:
    """A Gate-A-clean ledger that cites code only and names no canonical
    intent document, so the ledger elects no dispatch target and whatever
    `prose` says is the only thing an election can read in it."""
    lines = ["# Ledger", ""]
    lines.extend(prose)
    if prose:
        lines.append("")
    lines += [
        "## C-01",
        f"- `code: {cite(root, CODE_FILE, CODE_ADMIT)}`; "
        "`kani: merkle_promotion_not_duplication`",
    ]
    return "\n".join(lines) + "\n"


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
    (root / "docs" / "intent.md").write_text(INTENT_DOC)
    code = root / CODE_FILE
    code.parent.mkdir(parents=True, exist_ok=True)
    code.write_text(CODE_DOC)
    (root / "proofs" / "lean").mkdir(parents=True, exist_ok=True)
    legacy.mkdir(parents=True, exist_ok=True)
    (legacy / "intent.md").write_text(INTENT_STUB)
    (legacy / "ledger.md").write_text(ledger_text(root))
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


def write_row(report: dict, path: str) -> dict | None:
    for write in report.get("writes", []):
        if write.get("path") == path:
            return write
    return None


def fv_entries(root: Path) -> set[str]:
    """Everything under a real `.fv`, as project-relative paths. A `.fv` that
    is a symlink or not a directory holds nothing this migration wrote."""
    fv = root / ".fv"
    if fv.is_symlink() or not fv.is_dir():
        return set()
    return {path.relative_to(root).as_posix() for path in fv.rglob("*")}


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
        ".colosseum/verified-inputs.txt": ".fv/verified-inputs.txt",
    }
    for source, destination in expected.items():
        artifact = artifact_of(report, source)
        check(f"{source} is mapped to {destination}",
              artifact is not None and artifact["classification"] == MAPPED
              and artifact["destination"] == destination,
              str(artifact))
    check("exactly those six artifacts are mapped",
          sorted(a["source"] for a in report["artifacts"] if a["classification"] == MAPPED)
          == sorted(expected),
          str(sorted(a["source"] for a in report["artifacts"] if a["classification"] == MAPPED)))

    check("the ledger is copied verbatim",
          (root / ".fv/ledger.md").read_text() == (root / ".colosseum/ledger.md").read_text())
    check("a verbatim mapped file is not duplicated into history",
          not (root / ".fv/history/colosseum/ledger.md").exists())
    check("the ledger mapping says its citations are not re-rooted",
          "citation" in artifact_of(report, ".colosseum/ledger.md")["detail"],
          artifact_of(report, ".colosseum/ledger.md")["detail"])

    route = json.loads((root / ".fv/dispatch.json").read_text())["omp_native"]
    check("dispatch stores the repo-relative external intent the stub names",
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
    (plain / ".colosseum/ledger.md").write_text(code_only_ledger(plain))
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
    check("the dry-run report names the elected dispatch target as its own field",
          report_of(root)[1]["target_spec"] == "docs/intent.md"
          and report_of(plain)[1]["target_spec"] == ".fv/intent.md",
          f"{report_of(root)[1].get('target_spec')} {report_of(plain)[1].get('target_spec')}")

    # The stub is a declaration; the ledger is prose about the project. A
    # ledger paragraph naming a superseded document three times must not
    # outvote the entrypoint's own pointer, or the migration binds every
    # future evidence record to the wrong trust root.
    superseded = tmp / "intent-superseded"
    scaffold(superseded)
    (superseded / "docs/old-intent.md").write_text("# superseded\n")
    (superseded / ".colosseum/ledger.md").write_text(code_only_ledger(
        superseded,
        "Superseded: docs/old-intent.md, docs/old-intent.md, docs/old-intent.md.",
        "Current: docs/intent.md."))
    code, report, err = report_of(superseded, "--apply")
    check("the pointer stub outranks every ledger mention",
          code == 0 and report["target_spec"] == "docs/intent.md"
          and json.loads((superseded / ".fv/dispatch.json").read_text())
          ["omp_native"]["target_spec"] == "docs/intent.md",
          f"exit={code} {report.get('target_spec')} {err[-160:]}")

    # Ambiguity is a refusal, not a vote, in whichever document decides.
    for label, stub, prose, source in (
        ("stub", "# Intent\nSee `docs/intent.md` or `docs/old-intent.md`.\n",
         (), ".colosseum/intent.md#intent"),
        ("ledger", "# Intent\nThe canonical document is elsewhere.\n",
         ("See docs/intent.md and docs/old-intent.md.",),
         ".colosseum/ledger.md#intent"),
    ):
        ambiguous = tmp / f"intent-ambiguous-{label}"
        scaffold(ambiguous)
        (ambiguous / "docs/old-intent.md").write_text("# other\n")
        (ambiguous / ".colosseum/intent.md").write_text(stub)
        (ambiguous / ".colosseum/ledger.md").write_text(
            code_only_ledger(ambiguous, *prose))
        dry_code, dry_report, _ = report_of(ambiguous)
        code, report, _ = report_of(ambiguous, "--apply")
        row = artifact_of(report, source)
        check(f"two cited intents in the {label} block the run instead of electing one",
              dry_code == 1 and dry_report["status"] == "blocked" and code == 1
              and not (ambiguous / ".fv").exists()
              and report["target_spec"] is None
              and row is not None and row["classification"] == UNSUPPORTED,
              f"dry={dry_code} apply={code} {row}")

    # No entrypoint and no citation is not a silent no-op: the migrated
    # project would resolve no target at all.
    rootless = tmp / "intent-absent"
    scaffold(rootless)
    (rootless / ".colosseum/intent.md").unlink()
    (rootless / ".colosseum/ledger.md").write_text(code_only_ledger(rootless))
    (rootless / "docs/intent.md").unlink()
    dry_code, dry_report, _ = report_of(rootless)
    code, report, _ = report_of(rootless, "--apply")
    check("a legacy tree with no dispatch target blocks instead of migrating",
          dry_code == 1 and dry_report["status"] == "blocked" and code == 1
          and not (rootless / ".fv").exists()
          and report["target_spec"] is None
          and any("#intent" in entry and "no dispatch target" in entry
                  for entry in report["unsupported"]),
          f"dry={dry_code} apply={code} {report.get('unsupported')}")


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

    # A legacy helper arriving non-executable is a history copy that cannot
    # be replayed, so the executable bit travels with the bytes.
    executable = tmp / "history-modes"
    scaffold(executable)
    script = executable / ".colosseum/scripts/run_verification_layers.sh"
    script.chmod(0o755)
    code, _, err = report_of(executable, "--apply")
    copied = executable / ".fv/history/colosseum/scripts/run_verification_layers.sh"
    plain_copy = executable / ".fv/history/colosseum/attacks/intent-2026-08-24.md"
    check("an executable legacy helper stays executable in history",
          code == 0 and copied.stat().st_mode & 0o111 == 0o111
          and copied.read_bytes() == script.read_bytes(),
          f"exit={code} {oct(copied.stat().st_mode & 0o777)} {err[-120:]}")
    check("a non-executable legacy file gains no execute bit",
          plain_copy.stat().st_mode & 0o111 == 0,
          oct(plain_copy.stat().st_mode & 0o777))

    # A directory the inventory cannot list is an unsupported row, not a
    # traceback: its files cannot be classified, so none of them can be
    # claimed to have been preserved.
    locked = tmp / "history-unreadable-dir"
    scaffold(locked)
    blocked_dir = locked / ".colosseum/sealed"
    blocked_dir.mkdir()
    (blocked_dir / "note.md").write_text("sealed\n")
    blocked_dir.chmod(0o000)
    try:
        code, report, err = report_of(locked, "--apply")
        check("an unlistable legacy directory blocks with a row, not a traceback",
              code == 1 and report.get("status") == "blocked"
              and any(".colosseum/sealed" in entry and "cannot be listed" in entry
                      for entry in report.get("unsupported", []))
              and "Traceback" not in err,
              f"exit={code} {err[-160:]}")
        check("nothing is written for an inventory that could not complete",
              not (locked / ".fv").exists())
    finally:
        blocked_dir.chmod(0o755)


def check_verified_inputs(tmp: Path) -> None:
    """The legacy include list is translated into FV include mode, not inverted."""
    root = tmp / "inputs"
    scaffold(root)
    code, report, err = report_of(root, "--apply")
    artifact = artifact_of(report, ".colosseum/verified-inputs.txt")
    check("the legacy include list is mapped to the FV policy, not just history",
          code == 0 and artifact is not None and artifact["classification"] == MAPPED
          and artifact["destination"] == ".fv/verified-inputs.txt",
          f"exit={code} {artifact} {err[-200:]}")
    check("the legacy include list still survives verbatim as history",
          (root / ".fv/history/colosseum/verified-inputs.txt").read_text() == VERIFIED_INPUTS)

    policy = fv_project.load_policy(root)
    check("the migrated policy is include mode",
          policy.mode == fv_project.MODE_INCLUDE, policy.mode)
    selectors = set(policy.selectors())
    check("every legacy source root is carried across verbatim",
          {"crates", "quint", "proofs", "Cargo.toml"} <= selectors, sorted(selectors))
    check("the legacy manifest entry binds the FV artifact its content migrated to",
          ".fv/obligations.json" in selectors
          and not [entry for entry in selectors if entry.startswith(".colosseum/")],
          sorted(selectors))
    check("the canonical target and the migrated plan are bound",
          {"docs/intent.md", ".fv/verification-plan.json"} <= selectors, sorted(selectors))
    check("the policy binds itself, so revising it invalidates bound evidence",
          policy.selects(".fv/verified-inputs.txt"), sorted(selectors))
    check("a source a layer reads is selected",
          policy.selects("crates/contract/src/lib.rs") and policy.selects("docs/intent.md"))
    check("nothing outside the translated list is selected",
          not policy.selects("README.md") and not policy.selects(".colosseum/ledger.md")
          and not policy.selects(".fv/history/colosseum/ledger.md"))
    check("the policy explains the translation",
          "include" in (root / ".fv/verified-inputs.txt").read_text())

    # Blocking cases: a policy that binds nothing a layer reads would leave
    # evidence fresh across every source edit, so it is refused outright.
    for name, legacy, expected in (
        ("history-only", "# legacy\n.colosseum/evidence\n.colosseum/attacks/\n",
         "selects nothing any layer reads"),
        ("comment-only", "# nothing in scope\n#\n", "declares no entries"),
        ("malformed", "crates\n/etc/passwd\n", "not a parseable verified-input policy"),
    ):
        blocked = tmp / f"inputs-{name}"
        scaffold(blocked)
        (blocked / ".colosseum/verified-inputs.txt").write_text(legacy)
        code, report, err = report_of(blocked, "--apply")
        check(f"a {name} legacy include list blocks the migration",
              code == 1 and report.get("status") == "blocked"
              and any(expected in entry for entry in report.get("unsupported", [])),
              f"exit={code} {report.get('unsupported')}")
        check(f"nothing is written for a {name} legacy include list",
              not (blocked / ".fv/verified-inputs.txt").exists())


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

    # A legacy claim carrying fields this translation has no slot for is a
    # lossy translation: the fields survive under explicit provenance and the
    # report names them, instead of the manifest implying the claim came
    # across whole.
    retained = tmp / "obligations-retained"
    scaffold(retained)
    lossy = {**G1_CLAIMS["claims"][0],
             "scope": "admission keeps root canonical",
             "waiver": "WAIVED pending a Lean proof",
             "evidence_class": 123,
             "status": "waived",
             "notes": "see attacks/2026-08-24",
             "required_targets_optional": ["kani:h2"]}
    write_json(retained / ".colosseum/g1-claims.json",
               {**G1_CLAIMS, "environment_policy": {"hosts": 1},
                "claims": [lossy, *G1_CLAIMS["claims"][1:]]})
    code, lossy_report, err = report_of(retained, "--apply")
    lossy_manifest = json.loads((retained / ".fv/obligations.json").read_text())
    carried = {claim["id"]: claim for claim in lossy_manifest["system_claims"]}["C-01"]
    row = artifact_of(lossy_report, ".colosseum/g1-claims.json#claims.C-01")
    check("a legacy field with no typed slot is carried, not dropped",
          code == 0
          and carried.get("legacy_fields", {}).get("waiver") == "WAIVED pending a Lean proof"
          and carried["legacy_fields"]["status"] == "waived"
          and carried["legacy_fields"]["notes"] == "see attacks/2026-08-24"
          and carried["legacy_fields"]["required_targets_optional"] == ["kani:h2"]
          and carried["legacy_fields"]["evidence_class"] == 123
          and carried["legacy_fields"]["scope"] == "admission keeps root canonical",
          f"exit={code} {json.dumps(carried, sort_keys=True)[:300]} {err[-120:]}")
    check("an untypeable legacy field never occupies the typed slot",
          "waiver" not in carried and "scope" not in carried
          and "evidence_class" not in carried,
          str(sorted(carried)))
    check("the drop is reported as a deviation row naming every field",
          row is not None and row["classification"] == MAPPED
          and all(name in row["detail"] for name in
                  ("waiver", "status", "notes", "required_targets_optional")),
          str(row))
    document_row = artifact_of(lossy_report, ".colosseum/g1-claims.json#document")
    check("an untypeable document field is carried under migration provenance",
          lossy_manifest["migration"]["legacy_fields"] == {"environment_policy": {"hosts": 1}}
          and "environment_policy" not in lossy_manifest["migration"]
          and document_row is not None,
          str(lossy_manifest["migration"]))
    check("the migrated manifest with retained fields still loads under the gate",
          bool(check_evidence_records.load_manifest(retained / ".fv/obligations.json")[0]))
    check("a claim whose fields all have slots gets no legacy_fields and no row",
          all("legacy_fields" not in claim for claim in manifest["system_claims"])
          and not [item for item in report["artifacts"] if "#claims." in item["source"]],
          str([item["source"] for item in report["artifacts"] if "#claims." in item["source"]]))

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

    required, kinds, evidence, depends = check_evidence_records.load_manifest(
        root / ".fv/obligations.json")
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
    check("the gate reads each claim's dependencies",
          depends["C-01"] == [migrated_id(target)
                              for target in G1_CLAIMS["claims"][0]["required_targets"]],
          str(depends.get("C-01")))

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
    check("every layer some migrated claim names gates, required flag or not",
          all(document["layers"][name]["required"] is True
              for name in ("kani", "lean", "quint", "verus", "proptests")),
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
    check("the mapped detail carries the run manifest's provenance",
          all(fragment in artifact["detail"] for fragment in
              (".colosseum/evidence/runs/layer-runs.json",
               LAYER_RUNS["generated"], LAYER_RUNS["source_snapshot"], "quint=0")),
          artifact["detail"])
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
    # Its claim set names only that layer: a claim requiring evidence the plan
    # cannot produce is its own refusal, asserted further down.
    custom_only = tmp / "plan-custom-only"
    scaffold(custom_only)
    with_claims(custom_only, [{**G1_CLAIMS["claims"][0],
                               "required_targets": ["quint:invS7"], "layers": ["quint"]}])
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

    # A recorded layer no claim names runs but does not gate, and the mapped
    # detail says so: the operator has to be able to see which recorded
    # verification the migrated pyramid will not fail on.
    unnamed = tmp / "plan-unnamed-layer"
    scaffold(unnamed)
    runs = json.loads(json.dumps(LAYER_RUNS))
    runs["runs"].append({"layer": "mutation", "cwd": ".", "environment": {},
                         "command": "cargo mutants --check", "exit_status": 0})
    write_json(unnamed / ".colosseum/evidence/runs/layer-runs.json", runs)
    code, report, err = report_of(unnamed, "--apply")
    document = json.loads((unnamed / ".fv/verification-plan.json").read_text())
    check("a recorded layer no migrated claim names is not gating",
          code == 0 and document["layers"]["mutation"]["required"] is False
          and document["layers"]["quint"]["required"] is True,
          f"exit={code} " + str({name: spec["required"]
                                 for name, spec in document["layers"].items()}))
    check("the mapped detail names every layer written required: false",
          "mutation written required: false"
          in artifact_of(report, ".colosseum/evidence/runs/layer-runs.json")["detail"],
          artifact_of(report, ".colosseum/evidence/runs/layer-runs.json")["detail"])

    # Two independently recorded runs of one layer are a merge, not a
    # sequence: the `<layer>:<index>` last-segment scheme would assert a
    # relation the legacy manifest never stated.
    twice = tmp / "plan-two-runs"
    scaffold(twice)
    runs = json.loads(json.dumps(LAYER_RUNS))
    runs["runs"].append({"layer": "quint", "cwd": ".", "environment": {},
                         "command": "quint verify quint/other.qnt", "exit_status": 0})
    write_json(twice / ".colosseum/evidence/runs/layer-runs.json", runs)
    code, report, err = report_of(twice, "--apply")
    document = json.loads((twice / ".fv/verification-plan.json").read_text())
    tools = [execution["evidence_tool"] for execution in document["layers"]["quint"]["executions"]]
    row = artifact_of(report, ".colosseum/evidence/runs/layer-runs.json#layers.quint")
    check("two recorded runs of one layer key their executions by run",
          code == 0 and tools == ["quint:run1.1", "quint:run1.2", "quint:run1.3", "quint"],
          f"exit={code} {tools} {err[-160:]}")
    check("no cohort declares the same evidence tool twice across runs",
          len(set(tools)) == len(tools), str(tools))
    check("the merge of two recorded runs is reported as a deviation row",
          row is not None and row["classification"] == MAPPED
          and row["destination"] == ".fv/verification-plan.json"
          and "merged" in row["detail"],
          str(row))
    check("the two-run plan still loads under pyramid_run",
          len(pyramid_run.load_plan(twice / ".fv/verification-plan.json", twice)
              ["layers"]["quint"]["executions"]) == 4)

    # A claim whose required evidence no migrated execution produces blocks:
    # the no-omission rule runs from the claim to the plan as well.
    uncovered = tmp / "plan-uncovered-evidence"
    scaffold(uncovered)
    write_json(uncovered / ".colosseum/evidence/runs/layer-runs.json",
               {**LAYER_RUNS,
                "runs": [run for run in LAYER_RUNS["runs"] if run["layer"] != "quint"]})
    dry_code, dry_report, _ = report_of(uncovered)
    code, report, err = report_of(uncovered, "--apply")
    row = artifact_of(report, ".colosseum/g1-claims.json#claims.C-01.required_evidence")
    check("a claim requiring evidence no migrated run can produce blocks the migration",
          dry_code == 1 and dry_report["status"] == "blocked" and code == 1
          and not (uncovered / ".fv").exists()
          and row is not None and row["classification"] == UNSUPPORTED
          and "quint" in row["detail"],
          f"dry={dry_code} apply={code} {row}")

    # The same rule with nothing recorded at all: a legacy tree that carries
    # claims but never produced an `evidence/runs/layer-runs.json` migrates to
    # a manifest whose required evidence no plan can produce, because there is
    # no plan. That blocks, deliberately: a status-ok migration here would
    # publish required obligations against a project with no declared
    # execution, which is exactly the coverage claim the migration must not
    # invent. The refusal is pinned here so it cannot be relaxed back into an
    # ok migration without this assertion failing, and the message must name
    # the remedy -- record the run manifest, or drop the claims' layers.
    unrecorded = tmp / "plan-no-run-manifest"
    scaffold(unrecorded)
    (unrecorded / ".colosseum/evidence/runs/layer-runs.json").unlink()
    dry_code, dry_report, _ = report_of(unrecorded)
    code, report, err = report_of(unrecorded, "--apply")
    row = artifact_of(report, ".colosseum/g1-claims.json#claims.C-01.required_evidence")
    check("a claim manifest with no recorded run at all blocks, and writes nothing",
          dry_code == 1 and dry_report["status"] == "blocked" and code == 1
          and not (unrecorded / ".fv").exists()
          and row is not None and row["classification"] == UNSUPPORTED,
          f"dry={dry_code} apply={code} {row}")
    check("the refusal distinguishes an absent run manifest from an incomplete one",
          row is not None and "records no evidence/runs/layer-runs.json" in row["detail"]
          and "the run manifest" in row["detail"],
          str(row.get("detail") if row else None))

    # The same shape one spelling apart: the claim says `proptests`, the run
    # manifest recorded `proptest`, so the migrated evidence tool matches no
    # required_evidence entry.
    spelling = tmp / "plan-spelling"
    scaffold(spelling)
    with_claims(spelling, [{**G1_CLAIMS["claims"][0],
                            "required_targets": ["proptests:sequences"],
                            "layers": ["proptests"]}])
    code, report, err = report_of(spelling, "--apply")
    check("a claim naming a layer the run manifest spells differently blocks",
          code == 1 and not (spelling / ".fv").exists()
          and any("required_evidence" in entry and "proptests" in entry
                  for entry in report["unsupported"]),
          f"exit={code} {report['unsupported'][:1]}")

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

    # Tokenizing into words is not being argv. An assignment prefix and a
    # cwd-mutating builtin both carry no character in SHELL_CHARACTERS and
    # both split cleanly, so nothing but an explicit refusal stops them: the
    # first would exec a binary named `PROPTEST_CASES=4096`, and the second
    # would run `/usr/bin/cd`, exit 0, and leave the real command at the
    # wrong working directory.
    for label, command, fragment in (
        ("env-assignment-prefix", "PROPTEST_CASES=4096 cargo kani -p dossier-contract",
         "environment assignment"),
        ("cd-segment", "cd proofs/lean; cargo kani", "builtin 'cd'"),
        ("export-segment", "export RUSTFLAGS=-C; cargo kani", "builtin 'export'"),
        ("source-segment", "source ./env.sh; cargo kani", "builtin 'source'"),
    ):
        def assign(root: Path, command=command) -> None:
            runs = json.loads(json.dumps(LAYER_RUNS))
            for run in runs["runs"]:
                if run["layer"] == "kani":
                    run["command"] = command
            write_json(root / ".colosseum/evidence/runs/layer-runs.json", runs)
        _, report, root = mutate(label, assign)
        check(f"{label}: the refusal names the construct no argv represents",
              any("#layers.kani" in entry and fragment in entry
                  for entry in report["unsupported"]),
              str(report["unsupported"]))
        check(f"{label}: no plan is written for the rest of the layers",
              not any(write["path"] == ".fv/verification-plan.json"
                      for write in report["writes"]),
              str([write["path"] for write in report["writes"]]))

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
    check("a successful apply reports every destination as written",
          {write["action"] for write in report["writes"]} == {"written"},
          str({write["action"] for write in report["writes"]}))
    check("the apply report distinguishes what was asked from what happened",
          report["requested_mode"] == "apply" and report["applied"] is True
          and report["mode"] == "apply" and report["error"] is None,
          str({key: report.get(key) for key in ("requested_mode", "applied", "mode", "error")}))
    check("the report carries no absolute machine path",
          report["project_root"] == "."
          and not any(str(value).startswith("/") for value in
                      [write["path"] for write in report["writes"]]),
          str(report["project_root"]))
    check("the text report still names the real project directory",
          str(root) in migrate(root)[1], migrate(root)[1][:120])
    check("no staging directory survives the apply",
          not [path for path in (root / ".fv").rglob("*") if "staging" in path.name],
          str([path.name for path in (root / ".fv").rglob("*") if "staging" in path.name]))

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
    """A destination that already differs fails; equal bytes are idempotent.

    `.fv/ledger.md` is deliberately not the subject here. It is the one
    destination a pre-existing regular file claims as the live candidate
    rather than conflicts with, because that file is how an operator
    remediates a ledger the current gate refuses; check_live_ledger_
    remediation owns it. Every other destination is refused on sight.
    """
    root = tmp / "conflict"
    scaffold(root)
    (root / ".fv").mkdir()
    (root / ".fv/obligations.json").write_text('{"schema": "hand-written"}\n')
    dry_code, dry_report, _ = report_of(root)
    check("a differing destination blocks the dry run",
          dry_code == 1 and dry_report["status"] == "blocked"
          and any(".fv/obligations.json" in entry for entry in dry_report["conflicts"]),
          f"exit={dry_code} {dry_report.get('conflicts')}")
    check("the conflicting write is reported with action conflict",
          (write_row(dry_report, ".fv/obligations.json") or {}).get("action") == "conflict",
          str(write_row(dry_report, ".fv/obligations.json")))
    apply_code, _, _ = report_of(root, "--apply")
    check("apply refuses and leaves the differing destination untouched",
          apply_code == 1
          and (root / ".fv/obligations.json").read_text() == '{"schema": "hand-written"}\n',
          f"exit={apply_code}")
    check("a blocked apply writes no other destination",
          not (root / ".fv/verification-plan.json").exists()
          and not (root / ".fv/history").exists())
    check("a blocked --apply says an apply was requested and refused",
          dry_report["requested_mode"] == "dry-run"
          and report_of(root, "--apply")[1]["requested_mode"] == "apply"
          and report_of(root, "--apply")[1]["applied"] is False,
          str({key: report_of(root, "--apply")[1].get(key)
               for key in ("requested_mode", "applied", "mode")}))

    # Equal bytes from a project this migration never ran in: the manifest a
    # twin fixture migrates to is the same document, since every path it
    # records is project-relative, so a destination already carrying it is
    # the idempotent case rather than a conflict.
    twin = tmp / "conflict-twin"
    scaffold(twin)
    report_of(twin, "--apply")
    (root / ".fv/obligations.json").write_bytes(
        (twin / ".fv/obligations.json").read_bytes())
    code, report, _ = report_of(root, "--apply")
    check("a destination with equal bytes is idempotent, not a conflict",
          code == 0 and report["status"] == "ok"
          and (write_row(report, ".fv/obligations.json") or {}).get("action") == "identical",
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

    # Dispatch is the one destination that is adopted rather than refused: a
    # project initialized before the migration already carries a route, and
    # blocking on it would make every such project unmigratable without
    # moving the file aside. Only the two fields the migration owns change.
    existing = tmp / "conflict-dispatch"
    scaffold(existing)
    (existing / ".fv").mkdir()
    write_json(existing / ".fv/dispatch.json",
               {"omp_native": {"project_root": "/absolute/elsewhere",
                               "target_spec": "docs/other-intent.md",
                               "profile": "canonical-4@sha256:abc"},
                "panel": {"roster": ["a", "b"]}})
    (existing / ".fv/dispatch.json").chmod(0o600)
    narrowed = (existing / ".fv/dispatch.json").stat()
    dry_code, dry_report, _ = report_of(existing)
    check("an existing dispatch with another target is adopted, not refused",
          dry_code == 0 and dry_report["status"] == "ok"
          and any(write["path"] == ".fv/dispatch.json" and write["action"] == "adopt"
                  for write in dry_report["writes"]),
          f"exit={dry_code} {[w for w in dry_report['writes'] if 'dispatch' in w['path']]}")
    check("the adoption names the route it rewrote",
          any(write["path"] == ".fv/dispatch.json"
              and "docs/other-intent.md" in write.get("detail", "")
              and "docs/intent.md" in write.get("detail", "")
              for write in dry_report["writes"]),
          str([w.get("detail") for w in dry_report["writes"] if "dispatch" in w["path"]]))
    code, report, err = report_of(existing, "--apply")
    adopted = json.loads((existing / ".fv/dispatch.json").read_text())
    check("adoption rewrites exactly the two fields the migration owns",
          code == 0 and adopted["omp_native"]["target_spec"] == "docs/intent.md"
          and adopted["omp_native"]["project_root"] == "."
          and adopted["omp_native"]["profile"] == "canonical-4@sha256:abc"
          and adopted["panel"] == {"roster": ["a", "b"]},
          f"exit={code} {json.dumps(adopted, sort_keys=True)} {err[-160:]}")
    # The adoption replaces the inode, so the existing file's mode has to be
    # carried across deliberately: a route an operator narrowed must not come
    # back at the umask default because two of its fields were rewritten.
    adopted_stat = (existing / ".fv/dispatch.json").stat()
    check("the adopted destination keeps the mode the operator gave it",
          adopted_stat.st_mode & 0o7777 == narrowed.st_mode & 0o7777
          and adopted_stat.st_ino != narrowed.st_ino,
          f"mode {oct(narrowed.st_mode & 0o7777)} -> {oct(adopted_stat.st_mode & 0o7777)}, "
          f"inode {narrowed.st_ino} -> {adopted_stat.st_ino}")
    check("the adopted project resolves the migrated target",
          fv_project.resolve_target(existing) == (existing / "docs/intent.md").resolve())
    check("re-running after an adoption is byte-idempotent",
          report_of(existing, "--apply")[0] == 0
          and {write["action"] for write in report_of(existing)[1]["writes"]} == {"identical"},
          str({write["action"] for write in report_of(existing)[1]["writes"]}))

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


def check_containment(tmp: Path) -> None:
    """No write leaves the real `.fv` tree, whatever the path is made of.

    `mkdir(parents=True)` and an ordinary open both follow symlinks, so a
    link at any component -- `.fv` itself included -- is the one way the
    "only `.fv` is written" and ".colosseum stays byte-identical" promises
    break at the same time. The destination-is-a-symlink case is covered in
    check_conflicts; these are the intermediate components.
    """
    outside = tmp / "containment-outside"
    outside.mkdir()
    root = tmp / "containment-fv-symlink"
    scaffold(root)
    (root / ".fv").symlink_to(outside)
    code, report, _ = report_of(root, "--apply")
    check("a symlinked .fv blocks every write",
          code == 1 and report["status"] == "blocked"
          and all(write["action"] == "conflict" for write in report["writes"])
          and any(".fv is a symlink" in entry for entry in report["conflicts"]),
          f"exit={code} {report.get('conflicts', [])[:1]}")
    check("nothing lands outside the project through the symlink",
          [path for path in outside.rglob("*")] == [],
          str([path.name for path in outside.rglob("*")]))

    nested = tmp / "containment-history-symlink"
    scaffold(nested)
    (nested / ".fv").mkdir()
    (nested / ".colosseum/imported").mkdir()
    (nested / ".fv/history").symlink_to(nested / ".colosseum/imported")
    legacy_before = tree_digest(nested / ".colosseum")
    code, report, _ = report_of(nested, "--apply")
    check("a symlinked intermediate component blocks the run",
          code == 1 and report["status"] == "blocked"
          and any(".fv/history is a symlink" in entry for entry in report["conflicts"]),
          f"exit={code} {report.get('conflicts', [])[:1]}")
    check("the legacy tree stays byte-identical behind the link",
          tree_digest(nested / ".colosseum") == legacy_before
          and list((nested / ".colosseum/imported").iterdir()) == [],
          str(sorted(p.name for p in (nested / ".colosseum/imported").iterdir())))


def check_staging_containment(tmp: Path) -> None:
    """The staging prefix is a write path, so containment must hold for it.

    `.fv/.migrate-staging` is a fixed name, and every migrated byte is
    written through it before any destination sees it. Anything with write
    access to `.fv` -- an operator moving staging onto a tmpfs, a restore, an
    rsync -- can therefore leave a symlink at it long before a migration
    runs, and no destination path crosses that link, so the per-destination
    guards never look at it. A link there breaks the same two promises a link
    at `.fv` breaks: the bytes leave the tree this migration may write, and
    they can land inside the legacy tree it promises to leave alone.
    """
    outside = tmp / "staging-outside"
    outside.mkdir()
    escaping = tmp / "staging-symlink-outside"
    scaffold(escaping)
    (escaping / ".fv").mkdir()
    (escaping / ".fv/.migrate-staging").symlink_to(outside)
    code, report, _ = report_of(escaping, "--apply")
    check("a staging prefix symlinked out of the project blocks the run",
          code == 1 and report["status"] == "blocked"
          and any(".fv/.migrate-staging" in entry and "is a symlink" in entry
                  for entry in report["conflicts"]),
          f"exit={code} {report.get('conflicts', [])[:2]}")
    check("no migrated byte is staged outside the project through the link",
          list(outside.rglob("*")) == [] and not (escaping / ".fv/obligations.json").exists(),
          str([path.name for path in outside.rglob("*")]))

    into_legacy = tmp / "staging-symlink-legacy"
    scaffold(into_legacy)
    (into_legacy / ".fv").mkdir()
    (into_legacy / ".colosseum/imported").mkdir()
    (into_legacy / ".fv/.migrate-staging").symlink_to(into_legacy / ".colosseum/imported")
    legacy_before = tree_digest(into_legacy / ".colosseum")
    code, report, _ = report_of(into_legacy, "--apply")
    check("a staging prefix symlinked into the legacy tree blocks the run",
          code == 1 and report["status"] == "blocked"
          and any(".fv/.migrate-staging" in entry and "is a symlink" in entry
                  for entry in report["conflicts"]),
          f"exit={code} {report.get('conflicts', [])[:2]}")
    check("the legacy tree stays byte-identical behind the staging symlink",
          tree_digest(into_legacy / ".colosseum") == legacy_before
          and list((into_legacy / ".colosseum/imported").rglob("*")) == [],
          str(sorted(path.name for path in (into_legacy / ".colosseum/imported").rglob("*"))))

    not_a_directory = tmp / "staging-not-a-directory"
    scaffold(not_a_directory)
    (not_a_directory / ".fv").mkdir()
    (not_a_directory / ".fv/.migrate-staging").write_text("not a directory\n")
    code, report, _ = report_of(not_a_directory, "--apply")
    check("a staging prefix that is not a directory blocks in preflight",
          code == 1 and report["status"] == "blocked"
          and any(".fv/.migrate-staging" in entry and "not a directory" in entry
                  for entry in report["conflicts"])
          and not (not_a_directory / ".fv/obligations.json").exists(),
          f"exit={code} {report.get('conflicts', [])[:2]}")

    unwritable = tmp / "staging-unwritable"
    scaffold(unwritable)
    (unwritable / ".fv/.migrate-staging").mkdir(parents=True)
    (unwritable / ".fv/.migrate-staging").chmod(0o500)
    try:
        code, report, _ = report_of(unwritable, "--apply")
        check("an unwritable staging prefix blocks in preflight, before any write",
              code == 1 and report["status"] == "blocked"
              and any(".fv/.migrate-staging" in entry and "not writable" in entry
                      for entry in report["conflicts"])
              and not (unwritable / ".fv/obligations.json").exists(),
              f"exit={code} {report.get('conflicts', [])[:2]}")
    finally:
        # A run that removed the prefix instead of blocking is the failure the
        # check above reports; restoring permissions must not bury it in a
        # traceback from the cleanup.
        if (unwritable / ".fv/.migrate-staging").is_dir():
            (unwritable / ".fv/.migrate-staging").chmod(0o755)

    # The prefix can also be replaced between the preflight and the writes,
    # which is the one shape preflight cannot see. The apply has to refuse
    # before it stages a byte rather than discover it afterwards.
    raced = tmp / "staging-symlink-raced"
    scaffold(raced)
    planted = tmp / "staging-raced-outside"
    planted.mkdir()
    probe = tmp / "staging_toctou_probe.py"
    probe.write_text(
        "import json, sys\n"
        f"sys.path.insert(0, {str(REPO / 'scripts')!r})\n"
        "from pathlib import Path\n"
        "import fv_migrate\n"
        "project, target = Path(sys.argv[1]), Path(sys.argv[2])\n"
        "migration = fv_migrate.Migration(project)\n"
        "migration.build()\n"
        "(project / '.fv').mkdir(exist_ok=True)\n"
        "(project / '.fv' / '.migrate-staging').symlink_to(target)\n"
        "failure = None\n"
        "try:\n"
        "    migration.apply()\n"
        "except (fv_migrate.MigrationError, OSError) as error:\n"
        "    failure = str(error)\n"
        "print(json.dumps(migration.report(requested='apply', applied=False, error=failure)))\n")
    result = subprocess.run([sys.executable, str(probe), str(raced), str(planted)],
                            capture_output=True, text=True, timeout=300)
    report = json.loads(result.stdout) if result.stdout.startswith("{") else {}
    check("a staging prefix replaced after preflight is refused at apply time",
          "staging path is a symlink" in (report.get("error") or ""),
          (report.get("error") or result.stderr[-200:])[:200])
    check("not one byte is staged through the planted link",
          list(planted.rglob("*")) == []
          and {write["action"] for write in report.get("writes", [])} == {"pending"},
          str([path.name for path in planted.rglob("*")])
          + str(sorted({write["action"] for write in report.get("writes", [])})))


def write_rollback_probe(path: Path) -> Path:
    """Write a probe that drives a preflight-clean apply into its rollback.

    `.fv/history` loses write permission between the build and the apply,
    which is the one failure preflight cannot see, so the rollback is reached
    without patching the migrator. The probe prints the report of the failed
    apply: that report is the only enumeration of what happened to each
    destination.
    """
    path.write_text(
        "import json, sys\n"
        f"sys.path.insert(0, {str(REPO / 'scripts')!r})\n"
        "from pathlib import Path\n"
        "import fv_migrate\n"
        "project = Path(sys.argv[1])\n"
        "migration = fv_migrate.Migration(project)\n"
        "migration.build()\n"
        "(project / '.fv' / 'history').chmod(0o500)\n"
        "failure = None\n"
        "try:\n"
        "    migration.apply()\n"
        "except (fv_migrate.MigrationError, OSError) as error:\n"
        "    failure = str(error)\n"
        "report = migration.report(requested='apply', applied=False, error=failure)\n"
        "(project / '.fv' / 'history').chmod(0o755)\n"
        "print(json.dumps(report))\n")
    return path


def check_apply_atomicity(tmp: Path) -> None:
    """A preflight-clean apply that fails mid-way leaves no partial state and
    still reports what happened to every destination."""
    unwritable = tmp / "atomic-unwritable"
    scaffold(unwritable)
    (unwritable / ".fv/history").mkdir(parents=True)
    (unwritable / ".fv/history").chmod(0o500)
    try:
        code, report, _ = report_of(unwritable, "--apply")
        check("an unwritable destination directory blocks in preflight, before any write",
              code == 1 and report["status"] == "blocked"
              and any("not writable" in entry for entry in report["conflicts"])
              and not (unwritable / ".fv/dispatch.json").exists(),
              f"exit={code} {report.get('conflicts', [])[:1]}")
    finally:
        (unwritable / ".fv/history").chmod(0o755)

    # A failure preflight cannot see: the directory loses write permission
    # between the preflight and the writes. The apply must roll back and the
    # report must still be produced, naming each destination's real fate.
    racing = tmp / "atomic-rollback"
    scaffold(racing)
    (racing / ".fv/history").mkdir(parents=True)
    probe = write_rollback_probe(tmp / "atomic_probe.py")
    result = subprocess.run([sys.executable, str(probe), str(racing)],
                            capture_output=True, text=True, timeout=300)
    report = json.loads(result.stdout) if result.stdout.startswith("{") else {}
    actions = {write["action"] for write in report.get("writes", [])}
    left = sorted(path.relative_to(racing).as_posix()
                  for path in (racing / ".fv").rglob("*") if path.is_file())
    check("a mid-apply failure still produces a report",
          bool(report) and report.get("error"), result.stdout[:120] + result.stderr[-200:])
    check("the report enumerates what happened to each destination",
          actions <= {"failed", "lost", "pending", "rolled-back", "written"}
          and "rolled-back" in actions and "failed" in actions
          and "lost" not in actions,
          str(sorted(actions)))
    check("the rollback leaves no partially migrated .fv tree", left == [], str(left))
    check("a rolled-back apply is not reported as applied",
          report.get("applied") is False and report.get("mode") == "dry-run"
          and report.get("requested_mode") == "apply",
          str({key: report.get(key) for key in ("applied", "mode", "requested_mode")}))
    rerun_code, rerun_report, _ = report_of(racing, "--apply")
    check("the project is still migratable after a rolled-back apply",
          rerun_code == 0 and rerun_report["status"] == "ok"
          and (racing / ".fv/obligations.json").is_file(),
          f"exit={rerun_code} {rerun_report.get('conflicts')}")


def check_rollback_restores_metadata(tmp: Path) -> None:
    """A rollback puts a replaced destination back as the file it was.

    `.fv/dispatch.json` is the one destination an apply replaces instead of
    refusing, so it is the only file a rollback has to restore rather than
    remove. Restoring its bytes is not enough: a file re-created from saved
    bytes carries the umask's mode and a new identity, which is how an apply
    that failed halfway silently widens the permissions of a route an
    operator narrowed. The original is therefore moved aside and renamed
    back, and the whole inode is what this asserts returned.
    """
    root = tmp / "rollback-metadata"
    scaffold(root)
    (root / ".fv/history").mkdir(parents=True)
    dispatch = root / ".fv/dispatch.json"
    dispatch.write_text(json.dumps(
        {"omp_native": {"project_root": ".", "target_spec": "docs/other.md"}}, indent=2) + "\n")
    dispatch.chmod(0o640)
    os.utime(dispatch, (1700000000, 1700000000))
    before_bytes = dispatch.read_bytes()
    before = dispatch.stat()

    probe = write_rollback_probe(tmp / "metadata_probe.py")
    result = subprocess.run([sys.executable, str(probe), str(root)],
                            capture_output=True, text=True, timeout=300)
    report = json.loads(result.stdout) if result.stdout.startswith("{") else {}
    row = next((write for write in report.get("writes", [])
                if write["path"] == ".fv/dispatch.json"), {})
    after = dispatch.stat()
    check("the destination the apply replaced is reported as rolled back",
          row.get("action") == "rolled-back",
          str(row) + result.stdout[:80] + result.stderr[-200:])
    check("a rollback restores the replaced destination's bytes",
          dispatch.read_bytes() == before_bytes)
    check("a rollback restores the replaced destination's mode",
          after.st_mode & 0o7777 == before.st_mode & 0o7777,
          f"{oct(before.st_mode & 0o7777)} -> {oct(after.st_mode & 0o7777)}")
    check("a rollback renames the original inode back rather than rewriting it",
          after.st_ino == before.st_ino and after.st_mtime == before.st_mtime,
          f"inode {before.st_ino} -> {after.st_ino}, "
          f"mtime {before.st_mtime} -> {after.st_mtime}")
    check("a finished rollback leaves no staging tree behind",
          not (root / ".fv/.migrate-staging").exists(),
          sorted(path.as_posix() for path in (root / ".fv/.migrate-staging").rglob("*"))[:3]
          if (root / ".fv/.migrate-staging").exists() else "")

    # A rollback that cannot finish must not destroy what it was holding.
    # The staged original is the only copy of a replaced destination, so the
    # staging tree is dropped only once every restore succeeded; here the
    # move back is made to fail, and the original has to remain recoverable
    # and the report has to say the destination is gone rather than claim it
    # was put back.
    unfinished = tmp / "rollback-unfinished"
    scaffold(unfinished)
    (unfinished / ".fv").mkdir()
    route = unfinished / ".fv/dispatch.json"
    route.write_text(json.dumps(
        {"omp_native": {"project_root": ".", "target_spec": "docs/other.md"}}, indent=2) + "\n")
    route.chmod(0o640)
    route_bytes = route.read_bytes()
    failing = tmp / "unfinished_probe.py"
    failing.write_text(
        "import json, os, sys\n"
        f"sys.path.insert(0, {str(REPO / 'scripts')!r})\n"
        "from pathlib import Path\n"
        "import fv_migrate\n"
        "real = os.replace\n"
        "def failing(source, destination):\n"
        "    if str(destination).endswith('.fv/dispatch.json'):\n"
        "        raise OSError(5, 'simulated I/O error')\n"
        "    return real(source, destination)\n"
        "migration = fv_migrate.Migration(Path(sys.argv[1]))\n"
        "migration.build()\n"
        "os.replace = failing\n"
        "failure = None\n"
        "try:\n"
        "    migration.apply()\n"
        "except (fv_migrate.MigrationError, OSError) as error:\n"
        "    failure = str(error)\n"
        "os.replace = real\n"
        "print(json.dumps(migration.report(requested='apply', applied=False, error=failure)))\n")
    result = subprocess.run([sys.executable, str(failing), str(unfinished)],
                            capture_output=True, text=True, timeout=300)
    report = json.loads(result.stdout) if result.stdout.startswith("{") else {}
    row = next((write for write in report.get("writes", [])
                if write["path"] == ".fv/dispatch.json"), {})
    check("a destination the rollback could not restore is reported lost, not rolled back",
          row.get("action") == "lost" and ".fv/dispatch.json" in (report.get("error") or ""),
          str(row) + (report.get("error") or result.stderr[-200:])[:200])
    staged = sorted(path for path in (unfinished / ".fv/.migrate-staging").rglob("saved/*")
                    if path.is_file())
    check("an unfinished rollback keeps the replaced original recoverable",
          [path.read_bytes() for path in staged] == [route_bytes]
          and all(path.stat().st_mode & 0o7777 == 0o640 for path in staged),
          str([(path.name, oct(path.stat().st_mode & 0o7777)) for path in staged]))


def check_aside_failure(tmp: Path) -> None:
    """A move-aside that fails leaves its destination exactly where it was.

    The rollback restores a replaced destination by renaming the original
    inode back, so the apply may record that it is holding an original only
    once the aside actually happened. Fail the aside itself and the file
    never moved: reporting it `lost` would send an operator to a saved copy
    that does not exist, and would keep a staging tree holding nothing
    forever on the strength of that claim, since nothing ever sweeps a
    retained staging tree.
    """
    root = tmp / "aside-failure"
    scaffold(root)
    (root / ".fv").mkdir()
    dispatch = root / ".fv/dispatch.json"
    dispatch.write_text(json.dumps(
        {"omp_native": {"project_root": ".", "target_spec": "docs/other.md"}}, indent=2) + "\n")
    dispatch.chmod(0o640)
    before_bytes = dispatch.read_bytes()
    before = dispatch.stat()
    probe = tmp / "aside_probe.py"
    probe.write_text(
        "import json, os, sys\n"
        f"sys.path.insert(0, {str(REPO / 'scripts')!r})\n"
        "from pathlib import Path\n"
        "import fv_migrate\n"
        "real = os.replace\n"
        "def failing(source, destination):\n"
        "    # Fail only the aside: its target is the staging copy under\n"
        "    # saved/, never a real destination under .fv.\n"
        "    if 'saved' in Path(destination).parts:\n"
        "        raise OSError(28, 'simulated no space left on device')\n"
        "    return real(source, destination)\n"
        "migration = fv_migrate.Migration(Path(sys.argv[1]))\n"
        "migration.build()\n"
        "os.replace = failing\n"
        "failure = None\n"
        "try:\n"
        "    migration.apply()\n"
        "except (fv_migrate.MigrationError, OSError) as error:\n"
        "    failure = str(error)\n"
        "os.replace = real\n"
        "print(json.dumps(migration.report(requested='apply', applied=False, error=failure)))\n")
    result = subprocess.run([sys.executable, str(probe), str(root)],
                            capture_output=True, text=True, timeout=300)
    report = json.loads(result.stdout) if result.stdout.startswith("{") else {}
    actions = {write["action"] for write in report.get("writes", [])}
    row = next((write for write in report.get("writes", [])
                if write["path"] == ".fv/dispatch.json"), {})
    after = dispatch.stat()
    check("a destination whose move-aside failed is reported failed, not lost",
          row.get("action") == "failed" and "lost" not in actions
          and "no longer present" not in (report.get("error") or ""),
          str(row) + (report.get("error") or result.stderr[-200:])[:200])
    check("the destination whose move-aside failed is still the file it was",
          dispatch.read_bytes() == before_bytes and after.st_ino == before.st_ino
          and after.st_mode & 0o7777 == before.st_mode & 0o7777,
          f"inode {before.st_ino} -> {after.st_ino}, "
          f"mode {oct(before.st_mode & 0o7777)} -> {oct(after.st_mode & 0o7777)}")
    check("an apply that held no original retains no staging tree",
          not (root / ".fv/.migrate-staging").exists(),
          str(sorted(path.as_posix()
                     for path in (root / ".fv/.migrate-staging").rglob("*"))[:3])
          if (root / ".fv/.migrate-staging").exists() else "")
    rerun_code, rerun_report, _ = report_of(root, "--apply")
    check("the project is still migratable after a failed move-aside",
          rerun_code == 0 and rerun_report["status"] == "ok"
          and (root / ".fv/obligations.json").is_file(),
          f"exit={rerun_code} {rerun_report.get('conflicts')}")


def check_staging_race(tmp: Path) -> None:
    """Concurrent migrations of one project share only the staging prefix.

    Every run drops that prefix once it is empty, so a sibling can remove it
    between this run's `mkdir` and its `mkdtemp`. That is a race, not a
    failure: the prefix is recreated and the attempt repeated. A prefix that
    keeps vanishing is named as the concurrent migration it is instead of
    surfacing as `ENOENT` on a temp path, and writes nothing either way.
    """
    probe = tmp / "staging_race_probe.py"
    probe.write_text(
        "import json, sys, tempfile\n"
        f"sys.path.insert(0, {str(REPO / 'scripts')!r})\n"
        "from pathlib import Path\n"
        "import fv_migrate\n"
        "project, budget = Path(sys.argv[1]), int(sys.argv[2])\n"
        "real, calls = tempfile.mkdtemp, []\n"
        "def racing(*args, **kwargs):\n"
        "    calls.append(1)\n"
        "    if len(calls) <= budget:\n"
        "        # exactly what a sibling run's own cleanup does to the prefix\n"
        "        Path(kwargs['dir']).rmdir()\n"
        "        raise FileNotFoundError(2, 'No such file or directory')\n"
        "    return real(*args, **kwargs)\n"
        "tempfile.mkdtemp = racing\n"
        "migration = fv_migrate.Migration(project)\n"
        "migration.build()\n"
        "failure = None\n"
        "try:\n"
        "    migration.apply()\n"
        "except (fv_migrate.MigrationError, OSError) as error:\n"
        "    failure = str(error)\n"
        "tempfile.mkdtemp = real\n"
        "print(json.dumps({'report': migration.report(requested='apply',\n"
        "                                             applied=failure is None, error=failure),\n"
        "                  'calls': len(calls),\n"
        "                  'attempts': fv_migrate.STAGING_ATTEMPTS}))\n")

    transient = tmp / "staging-race-transient"
    scaffold(transient)
    result = subprocess.run([sys.executable, str(probe), str(transient), "1"],
                            capture_output=True, text=True, timeout=300)
    payload = json.loads(result.stdout) if result.stdout.startswith("{") else {}
    report = payload.get("report", {})
    check("a prefix a sibling removed mid-startup is recreated and the apply proceeds",
          report.get("error") is None and payload.get("calls") == 2
          and {write["action"] for write in report.get("writes", [])} == {"written"}
          and (transient / ".fv/obligations.json").is_file(),
          f"calls={payload.get('calls')} {str(report.get('error'))[:160]} "
          f"{sorted({write['action'] for write in report.get('writes', [])})}"
          f"{result.stderr[-160:]}")
    check("the retried run leaves no staging tree behind",
          not (transient / ".fv/.migrate-staging").exists())

    persistent = tmp / "staging-race-persistent"
    scaffold(persistent)
    result = subprocess.run([sys.executable, str(probe), str(persistent), "99"],
                            capture_output=True, text=True, timeout=300)
    payload = json.loads(result.stdout) if result.stdout.startswith("{") else {}
    report = payload.get("report", {})
    check("a prefix that keeps vanishing is reported as the concurrent migration it is",
          "another migration of this project removed the shared staging prefix"
          in (report.get("error") or "")
          and payload.get("calls") == payload.get("attempts"),
          (report.get("error") or result.stderr[-200:])[:200]
          + f" calls={payload.get('calls')} attempts={payload.get('attempts')}")
    check("the named race writes nothing and leaves no .fv tree behind",
          report.get("applied") is False
          and {write["action"] for write in report.get("writes", [])} == {"pending"}
          and not (persistent / ".fv").exists(),
          str(sorted({write["action"] for write in report.get("writes", [])}))
          + (str(sorted(path.name for path in (persistent / ".fv").rglob("*")))
             if (persistent / ".fv").exists() else ""))


def check_killed_apply_residue(tmp: Path) -> None:
    """A hard-killed apply strands only snapshot-excluded residue.

    `SIGKILL` runs no rollback and no cleanup, so whatever the staging tree
    held at that moment stays on disk. What keeps it from invalidating the
    evidence a later run binds is where it lives: one fixed prefix the
    verified-input snapshot excludes structurally -- before the migrated
    exclusion list exists, since the kill may precede it -- with a unique
    subdirectory per run, so no later apply inherits or disturbs it.
    """
    root = tmp / "killed-apply"
    scaffold(root)
    probe = tmp / "killed_apply_probe.py"
    probe.write_text(
        "import os, signal, sys\n"
        f"sys.path.insert(0, {str(REPO / 'scripts')!r})\n"
        "from pathlib import Path\n"
        "import fv_migrate\n"
        "migration = fv_migrate.Migration(Path(sys.argv[1]))\n"
        "migration.build()\n"
        "real, seen = os.replace, []\n"
        "def killing(source, destination):\n"
        "    seen.append(destination)\n"
        "    if len(seen) == 3:\n"
        "        os.kill(os.getpid(), signal.SIGKILL)\n"
        "    return real(source, destination)\n"
        "os.replace = killing\n"
        "migration.apply()\n")
    result = subprocess.run([sys.executable, str(probe), str(root)],
                            capture_output=True, text=True, timeout=300)
    check("the probe really was killed mid-apply, not merely failed",
          result.returncode == -signal.SIGKILL,
          f"exit={result.returncode} {result.stderr[-200:]}")
    left = sorted(path.relative_to(root).as_posix()
                  for path in (root / ".fv").rglob("*") if path.is_file())
    destinations = {write["path"] for write in report_of(root)[1].get("writes", [])}
    residue = [path for path in left if path not in destinations]
    unexcluded = [path for path in residue
                  if not fv_project.is_excluded(path, fv_project.DEFAULT_EXCLUSIONS)]
    check("a hard kill leaves residue behind at all, so the claim is not vacuous",
          bool(residue), str(left[:3]))
    check("every stranded byte is excluded from the snapshot structurally",
          not unexcluded, str(unexcluded[:3]))
    check("the stranded residue sits under one fixed prefix",
          len({"/".join(path.split("/")[:2]) for path in residue}) == 1,
          str(sorted({"/".join(path.split("/")[:2]) for path in residue})))
    check("the migrated project's own policy selects none of it either",
          not [path for path in residue if fv_project.load_policy(root).selects(path)])

    stranded_before = {path: (root / path).read_bytes() for path in residue}
    runs_before = {path.split("/")[2] for path in residue}
    rerun_code, rerun_report, _ = report_of(root, "--apply")
    check("the project is still migratable after a hard-killed apply",
          rerun_code == 0 and rerun_report["status"] == "ok"
          and (root / ".fv/obligations.json").is_file(),
          f"exit={rerun_code} {rerun_report.get('conflicts')}")
    after = sorted(path.relative_to(root).as_posix()
                   for path in (root / ".fv/.migrate-staging").rglob("*") if path.is_file())
    check("a later apply does not disturb the killed run's staging tree",
          {path: (root / path).read_bytes() for path in after} == stranded_before,
          str(sorted(set(after) ^ set(stranded_before))[:3]))
    check("a later apply stages under its own subdirectory and removes it",
          {path.split("/")[2] for path in after} == runs_before,
          str(sorted({path.split("/")[2] for path in after})))


# --------------------------------------------------------------------------
# ledger readiness: the current Gate A, not the one the project copied
# --------------------------------------------------------------------------

GATE_A_SOURCE = ".colosseum/ledger.md#gate-a"
# One artifact row carrying an excerpt, not the gate's whole transcript. The
# ceiling is the point: a row wide enough for a handful of truncated refusal
# lines and the sentence that frames them, and no wider however many
# citations the gate refused.
DIAGNOSTIC_LIMIT = 3000
LEGACY_GATE_COPY = ".colosseum/scripts/check_ledger_references.py"
LEGACY_GATE_SOURCE = (
    "#!/usr/bin/env python3\n"
    '"""The project-local Gate A copy that predates the FV scripts: it read\n'
    'the ledger for shape only, so an unbound or stale citation passed."""\n'
    "raise SystemExit(0)\n"
)

# The remediation path out of a refused ledger. `.colosseum/` is history this
# migration never writes, so a refusal there is unactionable until the
# operator has a writable copy; the staging flag is how they get exactly one.
STAGE_FLAG = "--stage-ledger-remediation"
STAGE_MODE = "stage-ledger-remediation"
LIVE_LEDGER = ".fv/ledger.md"
LIVE_GATE_A_SOURCE = f"{LIVE_LEDGER}#gate-a"
LEGACY_LEDGER_ENTRY = ".colosseum/ledger.md"
# Every other live artifact a full migration authors. A staging run copies
# one file, so a stage report that names any of these is claiming a
# migration it did not perform.
OTHER_FV_ARTIFACTS = (".fv/obligations.json", ".fv/verification-plan.json",
                      ".fv/verified-inputs.txt", ".fv/dispatch.json", ".fv/history/")


def gate_a_over(ledger: Path, project: Path) -> tuple[int, str]:
    """The current extension gate over one ledger file, invoked the way the
    migration's readiness check must invoke it: default strictness, `--root`
    at the project."""
    result = subprocess.run(
        [sys.executable, str(GATE_A), str(ledger), "--root", str(project)],
        capture_output=True, text=True, timeout=300,
    )
    return result.returncode, result.stdout + result.stderr


def run_gate_a(project: Path) -> tuple[int, str]:
    """The current extension gate over the legacy ledger."""
    return gate_a_over(project / LEGACY_LEDGER_ENTRY, project)


def gate_a_fragments(output: str) -> list[str]:
    """Distinctive pieces of the gate's own first refusal line: the locator
    and the explanation. The migrated diagnostic must quote the gate rather
    than paraphrase it; which side of the em dash survives truncation is the
    migration's business, so either counts."""
    for line in output.splitlines():
        if line.startswith("FAIL: "):
            reason = line[len("FAIL: "):]
            return [piece.strip()[:24] for piece in reason.split("\u2014")
                    if len(piece.strip()) > 8]
    return []


def ledger_missing_hash(root: Path) -> str:
    """Citations with no content binding: the shape a ledger written against
    the older copied gate carries, since that gate required none."""
    return (
        "# Ledger\n\n## C-01\n"
        f"- Intent S7 at `{cite(root, INTENT_FILE, INTENT_S7, bind=None)}`; "
        f"`code: {cite(root, CODE_FILE, CODE_ADMIT, bind=None)}`\n"
    )


def ledger_stale_hash(root: Path) -> str:
    """A citation bound to the line the file used to carry: still a binding,
    no longer the content."""
    return (
        "# Ledger\n\n## C-01\n"
        f"- Intent S7 at `{cite(root, INTENT_FILE, INTENT_S7)}`; "
        f"`code: {cite(root, CODE_FILE, CODE_ADMIT, bind=line_hash(CODE_FINALIZE))}`\n"
    )


def ledger_comment_only(root: Path) -> str:
    """A citation that resolves to a comment line: whatever enforcement it
    named has moved, and the line it points at decides nothing."""
    return (
        "# Ledger\n\n## C-01\n"
        f"- Intent S7 at `{cite(root, INTENT_FILE, INTENT_S7)}`; "
        f"`code: {cite(root, CODE_FILE, CODE_COMMENT)}`\n"
    )


def ledger_prose_only(root: Path) -> str:
    """A ledger with nothing to check at all: the copied gate's vacuous pass."""
    return ("# Ledger\n\nEvery claim is discharged by the runs recorded under\n"
            "`evidence/runs`. No citations.\n")


def ledger_malformed_binding(root: Path) -> str:
    """A binding that is not one: truncated hex, which the copied gate read as
    prose and the current gate reads as drift it cannot check."""
    return (
        "# Ledger\n\n## C-01\n"
        f"- Intent S7 at `{cite(root, INTENT_FILE, INTENT_S7)}`; "
        f"`{cite(root, CODE_FILE, CODE_ADMIT, bind='abc123')}`\n"
    )


def ledger_many_failures(root: Path, count: int = 120) -> str:
    """A ledger whose every citation is refused: one row must not carry one
    diagnostic per refusal."""
    lines = ["# Ledger", "", "## C-01"]
    citation = cite(root, CODE_FILE, CODE_ADMIT, bind=None)
    lines += [f"- `code: {citation}`" for _ in range(count)]
    return "\n".join(lines) + "\n"


def check_gate_a_readiness(tmp: Path) -> None:
    """The migration runs the current Gate A over the legacy ledger before it
    maps anything.

    A legacy project carries its own copy of the gate under
    `.colosseum/scripts/`, and that copy is older than the rules the current
    one enforces: it accepted a citation with no content binding, a binding
    that no longer matches, a citation into a comment, and a ledger with
    nothing to check. Such a ledger is not migratable -- copied verbatim to
    `.fv/ledger.md` it fails the first FV gate run against it -- so it blocks
    with one bounded row instead of being rewritten here or landing as-is.
    The fixture's own ledger passes, so readiness never blocks a clean tree.
    """
    clean = tmp / "gate-a-clean"
    scaffold(clean)
    gate_code, gate_out = run_gate_a(clean)
    check("the fixture ledger passes the current Gate A as written",
          gate_code == 0, gate_out[-400:])
    dry_code, dry_report, dry_err = report_of(clean)
    check("a Gate-A-clean legacy ledger migrates with no readiness row",
          dry_code == 0 and dry_report.get("status") == "ok"
          and artifact_of(dry_report, GATE_A_SOURCE) is None,
          f"exit={dry_code} {dry_report.get('unsupported')} {dry_err[-200:]}")
    apply_code, apply_report, apply_err = report_of(clean, "--apply")
    mapped = artifact_of(apply_report, ".colosseum/ledger.md")
    check("a Gate-A-clean ledger is still mapped verbatim to .fv/ledger.md",
          apply_code == 0 and mapped is not None
          and mapped["classification"] == MAPPED
          and mapped["destination"] == ".fv/ledger.md"
          and (clean / ".fv/ledger.md").read_text()
          == (clean / ".colosseum/ledger.md").read_text(),
          f"exit={apply_code} {mapped} {apply_err[-200:]}")

    for label, build in (
        ("missing-hash", ledger_missing_hash),
        ("stale-hash", ledger_stale_hash),
        ("comment-only", ledger_comment_only),
        ("prose-only", ledger_prose_only),
        ("malformed-binding", ledger_malformed_binding),
    ):
        root = tmp / f"gate-a-{label}"
        scaffold(root)
        copied_gate = root / LEGACY_GATE_COPY
        copied_gate.write_text(LEGACY_GATE_SOURCE)
        ledger = root / ".colosseum/ledger.md"
        ledger.write_text(build(root))
        legacy_before = tree_digest(root / ".colosseum")
        project_before = tree_digest(root)

        copied = subprocess.run(
            [sys.executable, str(copied_gate), str(ledger), "--root", str(root)],
            capture_output=True, text=True, timeout=300)
        check(f"{label}: the project's own copied gate accepts this ledger",
              copied.returncode == 0, f"exit={copied.returncode}")
        gate_code, gate_out = run_gate_a(root)
        check(f"{label}: the current Gate A refuses this ledger",
              gate_code == 1, f"exit={gate_code} {gate_out[-300:]}")
        fragments = gate_a_fragments(gate_out)

        for mode, flags in (("dry run", ()), ("apply", ("--apply",))):
            code, report, err = report_of(root, *flags)
            row = artifact_of(report, GATE_A_SOURCE)
            detail = (row or {}).get("detail") or ""
            ledger_row = artifact_of(report, ".colosseum/ledger.md")
            sources = [entry["source"] for entry in report.get("artifacts", [])]
            check(f"{label}: the {mode} is blocked on ledger readiness",
                  code == 1 and report.get("status") == "blocked"
                  and row is not None and row["classification"] == UNSUPPORTED
                  and row.get("destination") is None,
                  f"exit={code} {row} {err[-200:]}")
            check(f"{label}: the {mode} sources the block at {GATE_A_SOURCE}",
                  any(GATE_A_SOURCE in entry for entry in report.get("unsupported", [])),
                  str(report.get("unsupported"))[:300])
            check(f"{label}: the {mode} diagnostic is bounded",
                  0 < len(detail) <= DIAGNOSTIC_LIMIT, f"{len(detail)} chars")
            check(f"{label}: the {mode} diagnostic quotes the gate's refusal",
                  bool(fragments) and any(piece in detail for piece in fragments),
                  f"{fragments} :: {detail[:200]}")
            check(f"{label}: the {mode} refusal names the way to act on it",
                  STAGE_FLAG in detail,
                  detail[-240:])
            check(f"{label}: the {mode} proposes no .fv/ledger.md write",
                  not any(write["path"] == ".fv/ledger.md"
                          for write in report.get("writes", [])),
                  str([w for w in report.get("writes", []) if "ledger" in w["path"]]))
            check(f"{label}: the refused ledger is still classified exactly once",
                  sources.count(".colosseum/ledger.md") == 1
                  and ledger_row is not None
                  and ledger_row["classification"] != MAPPED,
                  str(ledger_row))
            check(f"{label}: the {mode} writes nothing at all",
                  not (root / ".fv").exists() and tree_digest(root) == project_before)
            check(f"{label}: the {mode} leaves the legacy tree byte-identical",
                  tree_digest(root / ".colosseum") == legacy_before)

    # Boundedness has to bite: the row must not grow with the number of
    # refusals, or a ledger whose every citation is unbound turns one report
    # row into the gate's whole transcript. The two ledgers below differ in
    # nothing but how many times the same refused citation appears, so the
    # comparison isolates the count from the length of a refusal line.
    few = tmp / "gate-a-few-failures"
    scaffold(few)
    (few / ".colosseum/ledger.md").write_text(ledger_many_failures(few, count=2))
    small = (artifact_of(report_of(few)[1], GATE_A_SOURCE) or {}).get("detail") or ""

    many = tmp / "gate-a-many-failures"
    scaffold(many)
    (many / ".colosseum/ledger.md").write_text(ledger_many_failures(many))
    gate_code, gate_out = run_gate_a(many)
    code, report, err = report_of(many)
    rows = [entry for entry in report.get("artifacts", [])
            if entry["source"] == GATE_A_SOURCE]
    detail = rows[0]["detail"] if rows else ""
    check("a ledger of refused citations blocks on exactly one readiness row",
          gate_code == 1 and code == 1 and report.get("status") == "blocked"
          and len(rows) == 1, f"gate={gate_code} exit={code} rows={len(rows)} {err[-200:]}")
    check("the diagnostic does not grow with the number of refusals",
          0 < len(small) and 0 < len(detail) <= DIAGNOSTIC_LIMIT
          and len(detail) <= 3 * len(small)
          and len(detail) < len(gate_out) // 3,
          f"two refusals {len(small)} chars, {len(gate_out)} of gate output "
          f"reported as {len(detail)}")

    # Infrastructure, not a verdict: a ledger the gate cannot read is a
    # failure of the check, so it blocks without claiming the bytes were
    # judged. Injected as a ledger that is not UTF-8, which is what the real
    # legacy trees produced when an editor wrote one region in latin-1.
    unreadable = tmp / "gate-a-unreadable"
    scaffold(unreadable)
    (unreadable / ".colosseum/ledger.md").write_bytes(
        "# Ledger\n\n## C-01\n- `code: ".encode()
        + cite(unreadable, CODE_FILE, CODE_ADMIT).encode()
        + b"`  \xff\xfe reviewed by M\xfcller\n")
    legacy_before = tree_digest(unreadable / ".colosseum")
    project_before = tree_digest(unreadable)
    for mode, flags in (("dry run", ()), ("apply", ("--apply",))):
        code, report, err = report_of(unreadable, *flags)
        row = artifact_of(report, GATE_A_SOURCE)
        detail = (row or {}).get("detail") or ""
        check(f"a ledger the gate cannot read blocks the {mode}",
              code == 1 and report.get("status") == "blocked"
              and row is not None and row["classification"] == UNSUPPORTED,
              f"exit={code} {row} {err[-200:]}")
        check(f"the {mode} diagnostic stays bounded when the check cannot run",
              0 < len(detail) <= DIAGNOSTIC_LIMIT, f"{len(detail)} chars")
        check(f"the {mode} quotes no verdict the gate never reached",
              "GATE FAILED" not in detail and "FAIL:" not in detail, detail[:200])
        check(f"the {mode} on an unreadable ledger writes nothing",
              not (unreadable / ".fv").exists()
              and tree_digest(unreadable) == project_before
              and tree_digest(unreadable / ".colosseum") == legacy_before)


# --------------------------------------------------------------------------
# ledger remediation: stage a writable copy, edit it, then migrate
# --------------------------------------------------------------------------

def replace_legacy_ledger(project: Path, how: str) -> None:
    """Make `.colosseum/ledger.md` something a byte copy cannot read."""
    ledger = project / LEGACY_LEDGER_ENTRY
    ledger.unlink()
    if how == "symlink":
        ledger.symlink_to(Path("..") / "docs" / "intent.md")
    elif how == "directory":
        ledger.mkdir()


def check_stage_ledger_remediation(tmp: Path) -> None:
    """`--stage-ledger-remediation` hands the operator one writable file.

    A legacy ledger the current Gate A refuses cannot be repaired where it
    lies: `.colosseum/` is history this migration promises never to write,
    so the refusal is unactionable on its own and the migration would be a
    dead end for exactly the projects that need it. Staging is the narrowest
    way out -- one byte-identical copy of `.colosseum/ledger.md` at
    `.fv/ledger.md`, no obligations, no plan, no dispatch, no history, and
    no claim that a migration happened -- so what the operator edits is a
    file they own, and the legacy bytes stay the record they were.
    """
    root = tmp / "stage"
    scaffold(root)
    legacy = root / LEGACY_LEDGER_ENTRY
    legacy.write_text(ledger_missing_hash(root))
    legacy_bytes = legacy.read_bytes()
    legacy_before = tree_digest(root / ".colosseum")
    project_before = tree_digest(root)

    code, report, err = report_of(root)
    refusal = (artifact_of(report, GATE_A_SOURCE) or {}).get("detail") or ""
    check("a refused legacy ledger blocks the regular run",
          code == 1 and report.get("status") == "blocked" and bool(refusal),
          f"exit={code} {err[-160:]}")
    check("the refusal sends the operator to the staging flag",
          STAGE_FLAG in refusal, refusal[-240:])
    check("the blocked run leaves the operator nothing to edit",
          not (root / ".fv").exists() and tree_digest(root) == project_before)

    stage_code, stage_out, stage_err = migrate(root, "--json", STAGE_FLAG)
    stage_report = json.loads(stage_out) if stage_out.startswith("{") else {}
    staged = root / LIVE_LEDGER
    check("staging exits 0 and copies the legacy ledger verbatim",
          stage_code == 0 and staged.is_file() and not staged.is_symlink()
          and staged.read_bytes() == legacy_bytes,
          f"exit={stage_code} {stage_err[-200:]}")
    check("staging copies exactly one file and nothing else",
          fv_entries(root) == {LIVE_LEDGER}, sorted(fv_entries(root)))
    check("staging leaves the legacy tree byte-identical",
          tree_digest(root / ".colosseum") == legacy_before)
    check("the staged copy is writable by the operator who has to edit it",
          os.access(staged, os.W_OK), oct(staged.stat().st_mode & 0o7777))

    row = write_row(stage_report, LIVE_LEDGER) or {}
    check("the stage report declares the mode it was asked for and claims no apply",
          stage_report.get("requested_mode") == STAGE_MODE
          and stage_report.get("mode") == STAGE_MODE
          and stage_report.get("applied") is False
          and stage_report.get("status") == "ok",
          str({key: stage_report.get(key)
               for key in ("requested_mode", "mode", "applied", "status")}))
    check("the stage report names exactly the one write it made",
          [write.get("path") for write in stage_report.get("writes", [])] == [LIVE_LEDGER]
          and row.get("action") == "written"
          and row.get("sha256") == hashlib.sha256(legacy_bytes).hexdigest(),
          str(stage_report.get("writes")))
    copied = artifact_of(stage_report, LEGACY_LEDGER_ENTRY) or {}
    check("the stage report classifies the one file it read",
          len(stage_report.get("artifacts", [])) == 1
          and copied.get("classification") == MAPPED
          and copied.get("destination") == LIVE_LEDGER,
          str(stage_report.get("artifacts")))
    serialized = json.dumps(stage_report, sort_keys=True)
    check("the stage report claims no full migration",
          not [name for name in OTHER_FV_ARTIFACTS if name in serialized]
          and stage_report.get("target_spec") is None
          and stage_report.get("counts", {}).get(UNSUPPORTED) == 0,
          str([name for name in OTHER_FV_ARTIFACTS if name in serialized]))

    # Determinism, asserted across two projects rather than two runs of one:
    # a stage report is a copy of one file's identity, and nothing about the
    # machine it ran on belongs in it.
    twin = tmp / "stage-twin"
    scaffold(twin)
    (twin / LEGACY_LEDGER_ENTRY).write_text(ledger_missing_hash(twin))
    twin_out = migrate(twin, "--json", STAGE_FLAG)[1]
    check("the stage JSON is deterministic and carries no machine path",
          twin_out == stage_out and str(root) not in stage_out,
          stage_out[:200] if twin_out != stage_out else str(root))
    check("the stage JSON is key-sorted",
          list(json.loads(stage_out)) == sorted(json.loads(stage_out)))

    text_root = tmp / "stage-text"
    scaffold(text_root)
    (text_root / LEGACY_LEDGER_ENTRY).write_text(ledger_missing_hash(text_root))
    text_code, text_out, _ = migrate(text_root, STAGE_FLAG)
    check("the stage text report names the one file and claims no applied migration",
          text_code == 0 and not text_out.strip().startswith("{")
          and LIVE_LEDGER in text_out and "VERDICT: STAGED" in text_out
          and "VERDICT: APPLIED" not in text_out
          and not [name for name in OTHER_FV_ARTIFACTS if name in text_out],
          text_out[-240:])

    # Re-staging is where an operator's work is at risk: the destination
    # exists because the last run made it, and the bytes in it are the ones
    # they came to write.
    code, report, err = report_of(root, STAGE_FLAG)
    row = write_row(report, LIVE_LEDGER) or {}
    check("re-staging an unedited copy reports it identical and rewrites nothing",
          code == 0 and row.get("action") == "identical"
          and staged.read_bytes() == legacy_bytes
          and fv_entries(root) == {LIVE_LEDGER},
          f"exit={code} {row}")

    edited = ledger_text(root).encode()
    staged.write_bytes(edited)
    code, report, err = report_of(root, STAGE_FLAG)
    row = write_row(report, LIVE_LEDGER) or {}
    check("re-staging never overwrites the edit the operator came here to make",
          code == 0 and staged.read_bytes() == edited
          and row.get("action") == "already-staged",
          f"exit={code} {row}")
    check("the already-staged run is a report, not a write",
          report.get("status") == "ok" and report.get("applied") is False
          and fv_entries(root) == {LIVE_LEDGER}
          and tree_digest(root / ".colosseum") == legacy_before,
          str({key: report.get(key) for key in ("status", "applied")}))

    # A source that is not a regular file has no bytes to copy, and guessing
    # at one -- following the link, walking the directory -- would stage
    # something the legacy tree never recorded as its ledger.
    for how in ("missing", "symlink", "directory"):
        broken = tmp / f"stage-legacy-{how}"
        scaffold(broken)
        replace_legacy_ledger(broken, how)
        before = tree_digest(broken)
        code, report, err = report_of(broken, STAGE_FLAG)
        check(f"staging a {how} legacy ledger fails and stages nothing",
              code == 1 and report.get("status") == "blocked"
              and not (broken / ".fv").exists() and tree_digest(broken) == before,
              f"exit={code} {err[-160:]}")
        check(f"staging a {how} legacy ledger names the file it could not copy",
              any(LEGACY_LEDGER_ENTRY in entry for entry in report.get("unsupported", [])),
              str(report.get("unsupported"))[:240])

    # Staging writes into `.fv`, so it inherits every protection a
    # destination gets: one narrow copy is still a copy that must not leave
    # the tree it is allowed to write, and must never be written through a
    # link somebody else planted.
    outside = tmp / "stage-outside"
    outside.mkdir()
    planted = outside / "ledger.md"
    planted.write_text("a file the migration may not touch\n")
    planted_bytes = planted.read_bytes()

    escaping = tmp / "stage-fv-symlink"
    scaffold(escaping)
    (escaping / ".fv").symlink_to(outside)
    escaping_legacy = tree_digest(escaping / ".colosseum")
    code, report, err = report_of(escaping, STAGE_FLAG)
    check("staging through a symlinked .fv is refused",
          code == 1 and report.get("status") == "blocked"
          and any(LIVE_LEDGER in entry for entry in report.get("conflicts", [])),
          f"exit={code} {report.get('conflicts')}")
    check("nothing is staged outside the project through a symlinked .fv",
          planted.read_bytes() == planted_bytes
          and sorted(path.name for path in outside.rglob("*")) == ["ledger.md"]
          and tree_digest(escaping / ".colosseum") == escaping_legacy,
          str(sorted(path.name for path in outside.rglob("*"))))

    linked = tmp / "stage-destination-symlink"
    scaffold(linked)
    (linked / ".fv").mkdir()
    (linked / LIVE_LEDGER).symlink_to(planted)
    code, report, err = report_of(linked, STAGE_FLAG)
    check("staging onto a symlinked destination is refused",
          code == 1 and report.get("status") == "blocked"
          and any(LIVE_LEDGER in entry for entry in report.get("conflicts", [])),
          f"exit={code} {report.get('conflicts')}")
    check("the symlink target keeps its bytes and the link is still a link",
          planted.read_bytes() == planted_bytes and (linked / LIVE_LEDGER).is_symlink(),
          planted.read_bytes()[:60])

    not_a_directory = tmp / "stage-fv-not-a-directory"
    scaffold(not_a_directory)
    (not_a_directory / ".fv").write_text("not a directory\n")
    code, report, err = report_of(not_a_directory, STAGE_FLAG)
    check("staging into a .fv that is not a directory is refused",
          code == 1 and report.get("status") == "blocked"
          and any(LIVE_LEDGER in entry for entry in report.get("conflicts", []))
          and (not_a_directory / ".fv").read_text() == "not a directory\n",
          f"exit={code} {report.get('conflicts')}")

    unwritable = tmp / "stage-fv-unwritable"
    scaffold(unwritable)
    (unwritable / ".fv").mkdir()
    (unwritable / ".fv").chmod(0o500)
    try:
        code, report, err = report_of(unwritable, STAGE_FLAG)
        check("staging into an unwritable .fv is refused in preflight",
              code == 1 and report.get("status") == "blocked"
              and any(LIVE_LEDGER in entry for entry in report.get("conflicts", []))
              and fv_entries(unwritable) == set(),
              f"exit={code} {report.get('conflicts')}")
    finally:
        if (unwritable / ".fv").is_dir():
            (unwritable / ".fv").chmod(0o755)

    # The two modes answer different questions and write different amounts,
    # so a run cannot be both: silently preferring one would either skip the
    # migration the operator asked for or perform one they did not.
    both = tmp / "stage-and-apply"
    scaffold(both)
    before = tree_digest(both)
    code, _, err = migrate(both, STAGE_FLAG, "--apply")
    check("staging and applying in one run is a usage error that writes nothing",
          code == 2 and STAGE_FLAG in err and not (both / ".fv").exists()
          and tree_digest(both) == before,
          f"exit={code} {err[-160:]}")


def check_live_ledger_remediation(tmp: Path) -> None:
    """The remediation loop end to end: block, stage, edit, migrate.

    Once `.fv/ledger.md` exists as a regular file it is the project's live
    ledger, not a destination waiting to be overwritten: the migration runs
    the current Gate A against that file, and a pass means the operator has
    already answered the question the legacy ledger failed. Its bytes are
    kept exactly as they are -- differing from the legacy ledger is the
    whole point of the edit -- the legacy ledger is preserved as history
    like every other legacy file, and the include entry that named
    `.colosseum/ledger.md` follows the content to where it now lives. A live
    ledger the gate still refuses blocks at its own path, because that is
    the file the operator can edit.
    """
    root = tmp / "remediation"
    scaffold(root)
    # The legacy include list names the legacy ledger, so the translated
    # policy has to follow the content rather than drop the entry.
    (root / ".colosseum/verified-inputs.txt").write_text(
        VERIFIED_INPUTS + f"{LEGACY_LEDGER_ENTRY}\n")
    legacy = root / LEGACY_LEDGER_ENTRY
    legacy.write_text(ledger_missing_hash(root))
    legacy_bytes = legacy.read_bytes()
    legacy_before = tree_digest(root / ".colosseum")
    check("the project starts from a ledger the current Gate A refuses",
          gate_a_over(legacy, root)[0] == 1)

    stage_code = migrate(root, STAGE_FLAG)[0]
    staged = root / LIVE_LEDGER
    check("staging gives the operator a writable copy to work on",
          stage_code == 0 and staged.is_file() and os.access(staged, os.W_OK),
          f"exit={stage_code}")

    # The edit: the same two claims, now content-bound, which is exactly
    # what the gate refused the legacy file for.
    edited = ledger_text(root).encode()
    staged.write_bytes(edited)
    gate_code, gate_out = gate_a_over(staged, root)
    check("the edited ledger passes the current Gate A where it lies",
          gate_code == 0 and edited != legacy_bytes, gate_out[-240:])

    dry_code, dry_report, dry_err = report_of(root)
    check("the regular dry run proceeds on the remediated ledger",
          dry_code == 0 and dry_report.get("status") == "ok"
          and dry_report.get("conflicts") == [] and dry_report.get("unsupported") == [],
          f"exit={dry_code} {dry_report.get('conflicts')} "
          f"{dry_report.get('unsupported')} {dry_err[-160:]}")
    check("neither ledger raises a readiness row once the live one is clean",
          artifact_of(dry_report, LIVE_GATE_A_SOURCE) is None
          and artifact_of(dry_report, GATE_A_SOURCE) is None,
          str([entry["source"] for entry in dry_report.get("artifacts", [])
               if "#" in entry["source"]]))
    row = write_row(dry_report, LIVE_LEDGER) or {}
    check("the dry run proposes the operator's bytes for .fv/ledger.md, not the legacy ones",
          row.get("action") == "identical"
          and row.get("sha256") == hashlib.sha256(edited).hexdigest(),
          f"{row} against {hashlib.sha256(edited).hexdigest()}")

    code, report, err = report_of(root, "--apply")
    check("the apply completes on a remediated project",
          code == 0 and report.get("status") == "ok" and report.get("applied") is True,
          f"exit={code} {report.get('conflicts')} {err[-200:]}")
    check("the operator's edited bytes are exactly what is still on disk",
          staged.read_bytes() == edited, staged.read_bytes()[:80])
    history = root / ".fv/history/colosseum/ledger.md"
    check("the superseded legacy ledger is preserved as history, byte for byte",
          history.is_file() and history.read_bytes() == legacy_bytes,
          history.read_bytes()[:80] if history.is_file() else "missing")
    ledger_row = artifact_of(report, LEGACY_LEDGER_ENTRY)
    check("the legacy ledger is classified history, never mapped over the live file",
          ledger_row is not None and ledger_row["classification"] == PRESERVED
          and ledger_row["destination"] == ".fv/history/colosseum/ledger.md",
          str(ledger_row))
    check("the legacy tree is byte-identical after the remediated migration",
          tree_digest(root / ".colosseum") == legacy_before)
    gate_code, gate_out = gate_a_over(staged, root)
    check("the migrated project starts gate-clean at .fv/ledger.md",
          gate_code == 0, gate_out[-300:])

    policy = fv_project.load_policy(root)
    selectors = set(policy.selectors())
    check("the include entry that named the legacy ledger selects the live one",
          LIVE_LEDGER in selectors and policy.selects(LIVE_LEDGER)
          and not [entry for entry in selectors if entry.startswith(".colosseum/")],
          sorted(selectors))
    check("no imported history byte becomes a verified input",
          not policy.selects(".fv/history/colosseum/ledger.md"), sorted(selectors))

    fv_before = tree_digest(root / ".fv")
    code, report, err = report_of(root, "--apply")
    check("re-applying a remediated project changes nothing",
          code == 0 and report.get("status") == "ok"
          and {write["action"] for write in report.get("writes", [])} == {"identical"}
          and tree_digest(root / ".fv") == fv_before
          and staged.read_bytes() == edited
          and tree_digest(root / ".colosseum") == legacy_before,
          f"exit={code} {sorted({w['action'] for w in report.get('writes', [])})}")

    # A live ledger the gate accepts wins even when the legacy ledger would
    # have passed too: the project's own file is the project's ledger, and
    # differing bytes are not a conflict to be resolved by overwriting it.
    preferred = tmp / "remediation-preferred"
    scaffold(preferred)
    (preferred / ".fv").mkdir()
    live = preferred / LIVE_LEDGER
    live.write_text(code_only_ledger(preferred, "Reviewed 2026-09-15 after the migration."))
    live_bytes = live.read_bytes()
    legacy_kept = (preferred / LEGACY_LEDGER_ENTRY).read_bytes()
    check("the live and legacy ledgers genuinely differ", live_bytes != legacy_kept)
    code, report, err = report_of(preferred, "--apply")
    check("a live ledger the gate accepts is kept, not overwritten by the legacy one",
          code == 0 and report.get("status") == "ok" and report.get("conflicts") == []
          and live.read_bytes() == live_bytes,
          f"exit={code} {report.get('conflicts')} {err[-200:]}")
    check("the superseded legacy ledger is history rather than a conflict",
          (preferred / ".fv/history/colosseum/ledger.md").read_bytes() == legacy_kept
          and (artifact_of(report, LEGACY_LEDGER_ENTRY) or {}).get("classification") == PRESERVED,
          str(artifact_of(report, LEGACY_LEDGER_ENTRY)))

    # Staged but not yet edited: the operator has the file and the gate
    # still refuses it, so the block moves to the path they can fix.
    stuck = tmp / "remediation-unedited"
    scaffold(stuck)
    (stuck / LEGACY_LEDGER_ENTRY).write_text(ledger_missing_hash(stuck))
    migrate(stuck, STAGE_FLAG)
    staged_bytes = (stuck / LIVE_LEDGER).read_bytes()
    stuck_before = tree_digest(stuck)
    for mode, flags in (("dry run", ()), ("apply", ("--apply",))):
        code, report, err = report_of(stuck, *flags)
        row = artifact_of(report, LIVE_GATE_A_SOURCE)
        detail = (row or {}).get("detail") or ""
        check(f"a staged but unedited ledger blocks the {mode} at its own path",
              code == 1 and report.get("status") == "blocked"
              and row is not None and row["classification"] == UNSUPPORTED
              and row.get("destination") is None,
              f"exit={code} {row} {err[-160:]}")
        check(f"the {mode} block names the writable file to edit",
              LIVE_LEDGER in detail, detail[:240])
        check(f"the {mode} judges the live ledger instead of the legacy one",
              artifact_of(report, GATE_A_SOURCE) is None
              and [entry["source"] for entry in report.get("artifacts", [])
                   ].count(LIVE_GATE_A_SOURCE) == 1,
              str([entry["source"] for entry in report.get("artifacts", [])
                   if "#gate-a" in entry["source"]]))
        check(f"the blocked {mode} rewrites neither the staged copy nor anything else",
              (stuck / LIVE_LEDGER).read_bytes() == staged_bytes
              and fv_entries(stuck) == {LIVE_LEDGER}
              and tree_digest(stuck) == stuck_before,
              sorted(fv_entries(stuck)))

    # A symlink is not a live candidate however clean the file behind it is:
    # adopting one would bind the project's trust artifact to bytes outside
    # the tree, and writing through one would leave `.fv` entirely.
    symlinked = tmp / "remediation-live-symlink"
    scaffold(symlinked)
    elsewhere = tmp / "remediation-live-symlink-target.md"
    elsewhere.write_text(code_only_ledger(symlinked, "Not the project's own ledger."))
    elsewhere_bytes = elsewhere.read_bytes()
    (symlinked / ".fv").mkdir()
    (symlinked / LIVE_LEDGER).symlink_to(elsewhere)
    check("the file behind the link would itself pass the gate",
          gate_a_over(elsewhere, symlinked)[0] == 0,
          gate_a_over(elsewhere, symlinked)[1][-200:])
    code, report, err = report_of(symlinked, "--apply")
    check("a symlink at .fv/ledger.md is never adopted as the live ledger",
          code == 1 and report.get("status") == "blocked"
          and any(LIVE_LEDGER in entry for entry in report.get("conflicts", []))
          and artifact_of(report, LIVE_GATE_A_SOURCE) is None,
          f"exit={code} {report.get('conflicts')}")
    check("the link is left a link and its target keeps its bytes",
          (symlinked / LIVE_LEDGER).is_symlink()
          and elsewhere.read_bytes() == elsewhere_bytes,
          elsewhere.read_bytes()[:80])


def check_cli(tmp: Path) -> None:
    root = tmp / "cli"
    scaffold(root)
    code, out, err = migrate(root)
    check("the text report is not JSON", code == 0 and not out.strip().startswith("{"))
    check("--help advertises every flag the CLI answers to",
          all(flag in subprocess.run([sys.executable, str(MIGRATE), "--help"],
                                     capture_output=True, text=True).stdout
              for flag in ("PROJECT", "--apply", "--json", STAGE_FLAG)))
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
        print("ledger readiness")
        check_gate_a_readiness(tmp)
        print("ledger remediation staging")
        check_stage_ledger_remediation(tmp)
        print("live ledger remediation")
        check_live_ledger_remediation(tmp)
        print("apply and idempotency")
        check_apply_and_idempotency(tmp)
        print("conflicts")
        check_conflicts(tmp)
        print("containment")
        check_containment(tmp)
        print("staging containment")
        check_staging_containment(tmp)
        print("apply atomicity")
        check_apply_atomicity(tmp)
        print("rollback restores metadata")
        check_rollback_restores_metadata(tmp)
        print("move-aside failure")
        check_aside_failure(tmp)
        print("staging race")
        check_staging_race(tmp)
        print("killed-apply residue")
        check_killed_apply_residue(tmp)
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
