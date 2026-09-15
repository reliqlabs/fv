#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""R36: end-to-end .colosseum -> .fv migration rehearsal on a dossier-shaped project.

The fixture reproduces the artifact shapes observed in the real dossier
integration project rather than a reduced schema: an external canonical
intent (`docs/intent.md`) with a pointer stub at `.colosseum/intent.md`, a
ledger whose trust-chain links are bold `**Depends on:**` blocks carrying
backticked `code:`/`kani:` citations bound to 12-hex line hashes, a
`colosseum-obligations` claim list of C-01..C-09, a `colosseum-g1-claims`
map with per-claim layers and `<layer>:<target>` required targets (one of
them a Rust `::` path, as the real project spells its Verus targets), an
include-list `verified-inputs.txt` (the shape FV include mode translates
rather than inverts), a `colosseum-layer-runs` v2 manifest whose commands are
semicolon-joined shell strings, and the historical attacks / changes /
code-adversarial / classifications / verify / evidence / scripts trees
(including a non-UTF-8 `.pyc`, which a byte-faithful copier must survive).

No proof tool is required: every layer command invokes `tools/probe.py`,
so the migrated plan can be executed for real without quint, kani, verus
or lean on PATH.

What this suite holds the migration to:

  * dry-run writes nothing at all, and its inventory classifies every
    regular file under `.colosseum/` exactly once;
  * `.colosseum/` is byte-identical after every stage (dry-run, apply,
    re-apply, fv_init, move);
  * the canonical target becomes the ledger-referenced external
    `docs/intent.md` with a portable `project_root` of ".";
    ledger, obligation manifest and verification plan carry the exact
    converted semantics (depends_on/required_evidence, semicolon ->
    N executions in source order, a known legacy layer renamed to its
    plannable pyramid key and `quint` carried as a custom plan layer), the
    plan's `evidence_tool` ids cover the union of every claim's
    `required_evidence`, and the plan loads -- and runs -- through the only
    consumer that reads it;
  * a required legacy layer that cannot be translated blocks the run:
    dry-run reports it unsupported and writes nothing instead of
    downgrading it to history;
  * every obligation the manifest declares is keyed by an id
    `fv_evidence_run` accepts, so a migrated claim is dischargeable with no
    post-migration rename, while the exact legacy `<layer>:<name>` target
    survives in `legacy_id`;
  * legacy G1 records are history, never live v3 records, and imported
    bytes are never verified inputs;
  * the legacy include list is translated into an FV include policy, not
    replaced by a broad exclusion list: every source root survives, the
    legacy manifest entries bind the FV artifacts they migrated to, and the
    policy binds itself;
  * the staging residue a hard-killed apply strands moves no verified-input
    snapshot, asserted against the real git-backed snapshot this project
    has rather than against a parsed exclusion list;
  * re-apply is byte-idempotent;
  * Gate A passes on the converted ledger under --strict-kani;
  * Gate B is INCOMPLETE for exactly one reason -- every required claim
    awaits a v3 record -- and not because the manifest is malformed;
  * fv_init completes the shadow without rewriting a migrated byte;
  * moving the project preserves dispatch resolution and both gates.

Exit 0 pass, 1 fail, 2 toolchain unavailable.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import fv_project  # noqa: E402  canonical target + verified-input semantics
import pyramid_run  # noqa: E402  the only consumer of a verification plan

MIGRATE = REPO / "scripts" / "fv_migrate.py"
GATE_A = REPO / "scripts" / "check_ledger_references.py"
GATE_B = REPO / "scripts" / "check_evidence_records.py"
INIT = REPO / "scripts" / "fv_init.py"
RESOLVER = REPO / "scripts" / "fv_project.py"
EVIDENCE_RUN = REPO / "tools" / "evidence-run.ts"

FAILURES: list[str] = []

CLASSIFICATIONS = {"mapped", "preserved-history", "unsupported"}
# A legacy layer whose name collides with a known pyramid layer is renamed on
# the way in (`proptest` -> `proptests`); every other legacy layer keeps its
# own id and executes as a custom plan layer, so no layer a claim requires can
# be dropped from the plan.
LEGACY_PLAN_LAYERS = {"proptest": "proptests", "kani": "kani",
                      "verus": "verus", "lean": "lean", "quint": "quint"}
MIGRATED_TIMEOUT = 3600
FV_DEFAULT_EXCLUSIONS = (".fv/evidence/", ".fv/verify/", ".fv/panels/", ".colosseum/")
HISTORY_EXCLUSION = ".fv/history/"
HISTORY_ROOT = ".fv/history/colosseum"
# The fixed prefix an apply stages under, one unique subdirectory per run. A
# hard kill leaves the tree behind, so the snapshot must exclude it.
STAGING_ROOT = ".fv/.migrate-staging"
STAGING_EXCLUSION = ".fv/.migrate-staging/"
PROFILE = "dossier-bounded-composition/v1"
ENVIRONMENT_POLICY = (
    "single-host observation, unrecorded environment (TA-07); every layer ran "
    "locally on one machine and no run pins its host toolchain beyond the "
    "digests recorded here"
)
# The id each legacy target must be keyed under in the migrated manifest. A
# `<layer>:<name>` target becomes `<layer>.<name>`; a name carrying anything
# the evidence producer's id alphabet excludes is spelled out here rather than
# computed, so the expectation never restates the migration's normalization.
MIGRATED_ID_OVERRIDES = {
    "verus:dossier::key_lineage::preserved": "verus.dossier-key_lineage-preserved",
}
SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


def check(label: str, condition: bool, detail: object = "") -> None:
    if condition:
        print(f"  [     pass] {label}")
    else:
        print(f"  [     FAIL] {label}" + (f" -- {detail}" if detail != "" else ""))
        FAILURES.append(label)


# ── hashing helpers ────────────────────────────────────────────────────


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def line_hash(line: str) -> str:
    """Gate A's content binding: sha256 of the rstripped line, 12 hex chars."""
    return hashlib.sha256(line.rstrip().encode()).hexdigest()[:12]


def fake_digest(label: str) -> str:
    """A stable sha256-shaped string for legacy manifests that are never rerun."""
    return "sha256:" + hashlib.sha256(label.encode()).hexdigest()


def file_map(root: Path) -> dict[str, str]:
    """Repo-relative POSIX path -> content digest for every regular file."""
    return {
        path.relative_to(root).as_posix(): sha256_bytes(path.read_bytes())
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }


def tree_hash(root: Path) -> str:
    """One digest over a whole tree: path, NUL, content digest, newline."""
    digest = hashlib.sha256()
    for relative, content in sorted(file_map(root).items()):
        digest.update(relative.encode())
        digest.update(b"\0")
        digest.update(content.encode())
        digest.update(b"\n")
    return digest.hexdigest()


# ── process helpers ────────────────────────────────────────────────────


def run(command: list[str], cwd: Path | None = None,
        env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(command, cwd=None if cwd is None else str(cwd),
                          env=env, capture_output=True, text=True, timeout=600)


def migrate(project: Path, *extra: str) -> subprocess.CompletedProcess:
    return run(["python3", str(MIGRATE), str(project), *extra])


def migrate_json(project: Path, *extra: str) -> tuple[subprocess.CompletedProcess, dict]:
    result = migrate(project, "--json", *extra)
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError:
        report = {}
    return result, report


def gate_a(project: Path, *extra: str) -> subprocess.CompletedProcess:
    return run(["python3", str(GATE_A), str(project / ".fv" / "ledger.md"),
                "--root", str(project), *extra])


def gate_b(project: Path, *extra: str) -> tuple[subprocess.CompletedProcess, dict]:
    result = run(["python3", str(GATE_B),
                  "--records", str(project / ".fv" / "evidence" / "records"),
                  "--manifest", str(project / ".fv" / "obligations.json"),
                  "--root", str(project), "--json", *extra])
    start = result.stdout.find("{")
    try:
        report = json.loads(result.stdout[start:]) if start >= 0 else {}
    except json.JSONDecodeError:
        report = {}
    return result, report


def resolver(project: Path, command: str) -> dict:
    result = run(["python3", str(RESOLVER), command, "--root", str(project), "--json"])
    if result.returncode != 0:
        return {"error": (result.stdout + result.stderr).strip()}
    return json.loads(result.stdout)


def git(project: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(project), *args], check=True,
                   capture_output=True, text=True)


# ── the dossier-shaped legacy project ──────────────────────────────────

# One row per composition candidate, mirroring the real project's nine.
# `targets` are `<layer>:<name>` strings exactly as the legacy g1 claim map
# spells them, and their order is the order `depends_on` must preserve
# (C-07 deliberately names its proptest target first).
CLAIMS: list[dict] = [
    {
        "id": "C-01", "anchor": "S7", "title": "S7 Merkle-root freshness",
        "layers": ["quint", "kani", "proptest"],
        "targets": ["quint:invS7", "kani:merkle_promotion_not_duplication",
                    "proptest:op_sequences_preserve_invariants"],
        "statement": ("Every successful admission or revocation leaves entries_root equal "
                      "to the canonical root of the live entry map"),
        "code_line": "        self.entries_root = recompute_root(&self.entries);",
        "boundary": ("The Quint abstraction equates a map value with the implementation "
                     "Merkle root, so the model-to-code relation is assumed."),
    },
    {
        "id": "C-02", "anchor": "B18", "title": "B18 sentinel and failure-reason discipline",
        "layers": ["quint", "kani", "proptest"],
        "targets": ["quint:invB18", "kani:sentinel_domain_separation",
                    "proptest:root_never_collides_with_empty_or_sentinels"],
        "statement": ("The snapshot-unavailable sentinel occurs only for a failed "
                      "snapshot_unavailable finalization after the retention floor"),
        "code_line": "        return Err(FailReason::SnapshotUnavailable);",
        "boundary": ("The bounded Kani domain does not discharge the complete B18 "
                     "temporal disjunction."),
    },
    {
        "id": "C-03", "anchor": "S6", "title": "S6 key-rotation structure",
        "layers": ["quint", "proptest"],
        "targets": ["quint:invS6", "quint:invRotationDueImpliesPreAdmissionsExpired",
                    "quint:invPolicyHistoryMonotonic",
                    "proptest:op_sequences_preserve_invariants"],
        "statement": ("A pending rotation requires an existing key, has one slot, and "
                      "fixes unlock_time at proposed_at plus the rotation delay"),
        "code_line": "        self.pending_rotation = Some(PendingRotation::new(now));",
        "boundary": "No mechanized refinement links the rotation model to the executable machine.",
    },
    {
        "id": "C-04", "anchor": "A5", "title": "A5 identifier and capacity discipline",
        "layers": ["quint", "proptest"],
        "targets": ["quint:invIds", "quint:invPendingAdmissionCaps",
                    "proptest:op_sequences_preserve_invariants"],
        "statement": ("Entry identifiers stay unique and pending admissions never exceed "
                      "the declared count and byte caps"),
        "code_line": "        ensure_capacity(self.pending.len(), PENDING_ADMISSION_CAP)?;",
        "boundary": "Capacity bounds are checked at the model's abstraction, not over persisted bytes.",
    },
    {
        "id": "C-05", "anchor": "K3", "title": "K3 key lineage across accepted transitions",
        "layers": ["lean", "verus", "quint", "proptest"],
        "targets": ["lean:Dossier.KeyLineage.admitted_key_survives_accepted_transitions",
                    "verus:dossier::key_lineage::preserved", "quint:invKeyLineage",
                    "proptest:op_sequences_preserve_invariants"],
        "statement": ("An admitted key survives every accepted transition and no accepted "
                      "transition rebinds a live key"),
        "code_line": "        debug_assert!(self.keys.contains_key(&admitted.key_id));",
        "boundary": "The Lean development and the Rust machine are related by inspection only.",
    },
    {
        "id": "C-06", "anchor": "S9", "title": "S9 finalized-record immutability",
        "layers": ["quint", "proptest"],
        "targets": ["quint:invFinalizedImmutable", "proptest:op_sequences_preserve_invariants"],
        "statement": "A finalized record is never rewritten by a later transition",
        "code_line": "        if record.finalized { return Err(FailReason::AlreadyFinal); }",
        "boundary": "Immutability is observed over sampled sequences, not proved over all of them.",
    },
    {
        "id": "C-07", "anchor": "S10", "title": "S10 finalized disclosure stability",
        "layers": ["quint", "proptest"],
        "targets": ["proptest:op_sequences_preserve_invariants",
                    "quint:invFinalizedDisclosuresStable"],
        "statement": "Disclosures attached to a finalized record stay byte-stable",
        "code_line": "        self.disclosures.retain(|d| !d.record.finalized);",
        "boundary": "Stability is asserted over the model's disclosure set, not over stored chunks.",
    },
    {
        "id": "C-08", "anchor": "D4", "title": "D4 derivation-path injectivity",
        "layers": ["kani"],
        "targets": ["kani:derivation_path_prefix_and_injectivity"],
        "statement": ("Derivation paths are prefix-free and injective over the bounded "
                      "identifier domain"),
        "code_line": "        let path = derive_path(domain, index).expect(\"bounded domain\");",
        "boundary": "Injectivity is proved over the bounded domain Kani explores, not all inputs.",
    },
    {
        "id": "C-09", "anchor": "Q7", "title": "Q7 staged envelope well-formedness",
        "layers": ["quint", "kani", "proptest"],
        "targets": ["quint:invStagedEnvelopesWellFormed", "kani:envelope_well_formed_bounded",
                    "proptest:op_sequences_preserve_invariants"],
        "statement": "Every staged envelope is well-formed before it can be finalized",
        "code_line": "        validate_envelope(&staged).map_err(FailReason::Envelope)?;",
        "boundary": "Well-formedness is bounded by the envelope sizes the harness enumerates.",
    },
]

# Target -> the source file that must carry a citable definition line. The
# proptest split across two files mirrors the real ledger.
TARGET_FILES = {
    "quint": "quint/dossier.qnt",
    "kani": "crates/contract/src/verification.rs",
    "lean": "proofs/lean/KeyLineage.lean",
    "verus": "proofs/verus/key_lineage.rs",
}
PROPTEST_FILES = {
    "root_never_collides_with_empty_or_sentinels":
        "crates/contract/tests/property/merkle_props.rs",
}
PROPTEST_DEFAULT_FILE = "crates/contract/tests/property/machine_props.rs"

PROBE = '''#!/usr/bin/env python3
"""Stand-in for a real verification tool: records its argv and exits 0.

Every legacy layer command in this fixture invokes this probe, so the
migration can be rehearsed end to end without quint, kani, verus or lean on
PATH. The log path comes from R36_PROBE_LOG and lives outside the project,
so running a migrated plan never perturbs the verified-input snapshot.
"""
import os
import sys

argv = " ".join(sys.argv[1:])
log = os.environ.get("R36_PROBE_LOG")
if log:
    with open(log, "a", encoding="utf-8") as handle:
        handle.write(f"{os.getcwd()}\\t{argv}\\n")
print(f"probe: {argv}")
print("test result: ok.")
'''

# Legacy layer runs. Commands are semicolon-joined shell strings exactly as
# the real colosseum-layer-runs/v2 manifest records them; the proptest layer
# carries a declared environment and a quoted argument, and quint keeps the
# two-segment `typecheck; run` shape whose id no known pyramid layer owns.
LAYER_RUNS = [
    {"layer": "kani", "cwd": ".", "environment": {},
     "command": "python3 tools/probe.py kani --features verification "
                "--harness merkle_promotion_not_duplication"},
    {"layer": "lean", "cwd": "proofs/lean", "environment": {},
     "command": "python3 ../../tools/probe.py lean build"},
    {"layer": "proptest", "cwd": ".",
     "environment": {"CARGO_TARGET_DIR": "target/r36-rehearsal"},
     "command": "python3 tools/probe.py build --features mock-attestation; "
                "python3 tools/probe.py test --features mock-attestation --test property "
                "--message 'property suite ok'"},
    {"layer": "quint", "cwd": ".", "environment": {},
     "command": "python3 tools/probe.py typecheck quint/dossier.qnt; "
                "python3 tools/probe.py run quint/dossier.qnt --invariant allInvariants "
                "--max-steps 24 --max-samples 100000 --witnesses wEntryAdmitted wRotated "
                "wSentinelUsed"},
    {"layer": "verus", "cwd": ".", "environment": {},
     "command": "python3 tools/probe.py verus proofs/verus/key_lineage.rs"},
]

LEGACY_INCLUDE_LIST = ("crates", "quint", "proofs", "Cargo.toml", "Cargo.lock",
                       "docs/intent.md", ".colosseum/obligations.json",
                       ".colosseum/g1-claims.json")


def target_layer(target: str) -> str:
    return target.split(":", 1)[0]


def target_name(target: str) -> str:
    return target.split(":", 1)[1]


def migrated_id(target: str) -> str:
    """The evidence-run-safe id the migrated manifest must key `target` under."""
    if target in MIGRATED_ID_OVERRIDES:
        return MIGRATED_ID_OVERRIDES[target]
    name = target_name(target)
    if SAFE_NAME.fullmatch(name) is None:
        raise AssertionError(
            f"{target!r} carries a name outside the evidence id alphabet and has no "
            "spelled-out expectation in MIGRATED_ID_OVERRIDES")
    return f"{target_layer(target)}.{name}"


def evidence_claim_id_pattern() -> re.Pattern[str]:
    """The `claim_id` shape the real evidence producer accepts.

    Read out of `tools/evidence-run.ts` instead of restated here: that guard
    decides whether a migrated obligation can be discharged at all, so a copy
    of it in this test would keep passing after the producer moved.
    """
    source = EVIDENCE_RUN.read_text()
    match = re.search(r"const CLAIM_ID = /(\^\[[^/]+\$)/", source) or re.search(
        r"/(\^\[[^/]+\$)/\.test\(params\.claim_id\)", source)
    if match is None:
        raise AssertionError(f"no claim_id guard found in {EVIDENCE_RUN}")
    return re.compile(match.group(1))


def target_file(target: str) -> str:
    layer = target_layer(target)
    if layer == "proptest":
        return PROPTEST_FILES.get(target_name(target), PROPTEST_DEFAULT_FILE)
    return TARGET_FILES[layer]


def definition_line(target: str) -> str:
    """The citable source line a target resolves to."""
    layer, name = target_layer(target), target_name(target)
    if layer == "quint":
        return f"  val {name} = entriesRootMatches(state)"
    if layer == "kani":
        return f"fn {name}(input: BoundedInput) {{"
    if layer == "proptest":
        return f"fn {name}(operations: Vec<Operation>) {{"
    if layer == "lean":
        short = name.rsplit(".", 1)[-1]
        return f"theorem {short} (s : State) : admitted s -> survives s := by"
    return f"pub fn {name}(state: &State) -> bool {{"


def build_sources(project: Path) -> None:
    """Every file a citation, a layer command or a verified input names."""
    files: dict[str, list[str]] = {}

    def add(relative: str, lines: list[str]) -> None:
        files.setdefault(relative, []).extend(lines)

    add("README.md", ["# dossier", "", "Bounded-composition integration fixture.", ""])
    add("Cargo.toml", ["[workspace]", 'members = ["crates/contract"]', ""])
    add("Cargo.lock", ['version = 4', "", "[[package]]", 'name = "dossier-contract"',
                       'version = "0.1.0"', ""])
    add("docs/intent.md", ["# Intent: dossier", "",
                           "## Normative clauses", ""])
    for claim in CLAIMS:
        add("docs/intent.md", [f"{claim['anchor']}. {claim['statement']}.", ""])
    add("docs/intent.md", ["## Construction failures", "",
                           "Q-B19. A 120000 entry in head_tree is a construction failure.", ""])

    add("crates/contract/src/machine/mod.rs",
        ["use crate::merkle::recompute_root;", "", "impl Machine {"])
    for claim in CLAIMS:
        add("crates/contract/src/machine/mod.rs",
            [f"    pub fn step_{claim['id'].lower().replace('-', '_')}(&mut self, now: u64) -> Result<()> {{",
             claim["code_line"], "        Ok(())", "    }"])
    add("crates/contract/src/machine/mod.rs", ["}", ""])

    header = {
        "crates/contract/src/verification.rs": ["#![cfg(feature = \"verification\")]", ""],
        PROPTEST_DEFAULT_FILE: ["use proptest::prelude::*;", ""],
        "crates/contract/tests/property/merkle_props.rs": ["use proptest::prelude::*;", ""],
        "quint/dossier.qnt": ["module dossier {"],
        "proofs/lean/KeyLineage.lean": ["namespace Dossier.KeyLineage", ""],
        "proofs/verus/key_lineage.rs": ["use vstd::prelude::*;", ""],
    }
    for relative, lines in header.items():
        add(relative, lines)

    seen: set[str] = set()
    for claim in CLAIMS:
        for target in claim["targets"]:
            if target in seen:
                continue
            seen.add(target)
            relative = target_file(target)
            body = "    assert!(invariant_holds(&state));"
            if target_layer(target) == "quint":
                add(relative, [definition_line(target)])
                continue
            if target_layer(target) == "lean":
                add(relative, [definition_line(target), "  simp [admitted, survives]", ""])
                continue
            if target_layer(target) == "kani":
                add(relative, ["#[kani::proof]", definition_line(target), body, "}", ""])
                continue
            add(relative, [definition_line(target), body, "}", ""])

    add("quint/dossier.qnt", ["  val allInvariants = true", "}", ""])
    add("proofs/lean/KeyLineage.lean", ["end Dossier.KeyLineage", ""])
    add("proofs/lean/lakefile.lean", ["import Lake", "open Lake DSL", "", "package dossier"])
    add("tools/probe.py", PROBE.splitlines())

    for relative, lines in files.items():
        path = project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n")
    (project / "tools" / "probe.py").chmod(0o755)


def cite(project: Path, relative: str, line_text: str) -> str:
    """A content-bound `<path>:<line>@sha256:<12hex>` citation for a known line."""
    lines = (project / relative).read_text().splitlines()
    matches = [index for index, text in enumerate(lines, start=1) if text == line_text]
    if len(matches) != 1:
        raise AssertionError(f"{relative}: {line_text!r} appears {len(matches)} times")
    return f"{relative}:{matches[0]}@sha256:{line_hash(line_text)}"


def build_ledger(project: Path) -> str:
    """The dossier ledger shape: bold Depends-on blocks, backticked citations."""
    out = [
        "# Colosseum integration ledger",
        f"- Project: `{project}`",
        "- Formal composition baseline: `ede07b2`; record-v1 boundary added 2026-09-14.",
        "- Updated: `2026-09-14`",
        "- Compared against: first emission at `8ee4ea3`",
        "- Mechanized cross-tool composition theorems: **0**",
        f"- Gate B (typed execution evidence): VERIFIED for profile {PROFILE}",
        f"- Composition candidates inventoried below: **{len(CLAIMS)}**, all **INCOMPLETE**",
        "- Cross-axis label: **UNVERIFIED**. No ITF replay or mechanized refinement",
        "  argument exists in this snapshot.",
        "",
        "`INCOMPLETE` means that named artifacts form a candidate chain, not that their",
        "conjunction has been proved.",
        "",
        "## Composition candidates",
        "",
    ]
    for claim in CLAIMS:
        intent_citation = cite(project, "docs/intent.md",
                               f"{claim['anchor']}. {claim['statement']}.")
        code_citation = cite(project, "crates/contract/src/machine/mod.rs",
                             claim["code_line"])
        kani_targets = [t for t in claim["targets"] if target_layer(t) == "kani"]
        kani_note = (f"kani: {target_name(kani_targets[0])}" if kani_targets
                     else "kani: skipped because this candidate has no bounded harness")
        out += [
            f"### {claim['id']}. {claim['title']}",
            f"**Statement:** {claim['statement']}.",
            f"**Status:** **INCOMPLETE**. Intent, spec and runtime artifacts exist; the G1",
            "record joins the bounded runs without a mechanized composition theorem.",
            "**Depends on:**",
            f"- Intent {claim['anchor']} at `{intent_citation}`; "
            f"`code: {code_citation}`; `{kani_note}`",
        ]
        for target in claim["targets"]:
            layer, name = target_layer(target), target_name(target)
            citation = cite(project, target_file(target), definition_line(target))
            if layer == "kani":
                note = f"kani: {name}"
            else:
                note = (f"kani: skipped because the {layer} layer is "
                        f"{'sampled, not bounded' if layer == 'proptest' else 'unbounded'}")
            evidence = ("[EVIDENCED 2026-08-26; `.colosseum/evidence/quint-2026-08-26.md`]"
                        if layer == "quint" else "[EVIDENCED 2026-09-02]")
            out.append(f"- {layer.capitalize()} `{name}` at `{citation}` {evidence}; `{note}`")
        out += [
            "",
            "| Conjunct | Status | Source |",
            "|---|---|---|",
            f"| {claim['statement']} | candidate chain | `{claim['id']}` |",
            "",
            f"**Trust boundary:** {claim['boundary']}",
            "**Bundle cardinality:** 0",
            "",
        ]
    out += [
        "## Residual assumptions",
        "",
        "- axiom: the Merkle abstraction equates a model map value with the implementation",
        "  root, assumed without a mechanized refinement argument",
        "",
    ]
    return "\n".join(out) + "\n"


def legacy_g1_record(claim: dict, commands: list[str]) -> dict:
    """A legacy G1 record: parser_schema_version 1, layer-keyed configuration."""
    layers = claim["layers"]
    return {
        "claim_id": claim["id"],
        "required": True,
        "evidence_class": "bounded-checked",
        "result": "PASS",
        "scope": {
            "statement": claim["statement"],
            "discharged": [f"{target_layer(t)} {target_name(t)} observed in the recorded run"
                           for t in claim["targets"]],
        },
        "waiver": {"excluded": [claim["boundary"]]},
        "bindings": {
            "parser_schema_version": 1,
            "profile": PROFILE,
            "environment_policy": ENVIRONMENT_POLICY,
            "command": commands,
            "required_targets": claim["targets"],
            "run_id": "+".join(f"{layer}-20260915T012148Z" for layer in layers),
            "seeds": None,
            "source_snapshot": "916401cb23d88057a79d85778eb597f991725f78",
            "intent_hash": fake_digest(f"intent-{claim['id']}"),
            "obligation_manifest_hash": fake_digest("obligations"),
            "raw_output_hash": fake_digest(f"raw-{claim['id']}"),
            "toolchain_digests": {layer: fake_digest(f"tool-{layer}") for layer in layers},
            "configuration": {
                "claim_map_hash": fake_digest("g1-claims"),
                "layers": layers,
                "layer_cwds": {layer: cwd_of(layer) for layer in layers},
                "layer_environments": {layer: environment_of(layer) for layer in layers},
                "layer_output_hashes": {layer: fake_digest(f"log-{layer}") for layer in layers},
                "run_manifest_path": ".colosseum/evidence/runs/layer-runs.json",
                "run_manifest_hash": fake_digest("layer-runs"),
                "run_host": "Darwin 25.6.0 arm64",
                "runs_generated": "2026-09-15T01:21:48Z",
                "runner_hash": fake_digest("runner"),
                "verified_inputs_hash": fake_digest("verified-inputs"),
            },
        },
    }


def run_of(layer: str) -> dict:
    return next(entry for entry in LAYER_RUNS if entry["layer"] == layer)


def cwd_of(layer: str) -> str:
    return run_of(layer)["cwd"]


def environment_of(layer: str) -> dict:
    return dict(run_of(layer)["environment"])


def command_of(layer: str) -> str:
    return run_of(layer)["command"]


def build_colosseum(project: Path) -> None:
    """The legacy state tree, in the shapes the real project carries."""
    colosseum = project / ".colosseum"
    for name in ("attacks", "changes", "code-adversarial", "classifications",
                 "verify", "evidence/g1", "evidence/runs", "scripts/__pycache__"):
        (colosseum / name).mkdir(parents=True, exist_ok=True)

    (colosseum / "intent.md").write_text(
        "# Intent: dossier\n"
        "The canonical intent document is [`docs/intent.md`](../docs/intent.md). Read\n"
        "that file; this one carries no normative text.\n"
        "\n"
        "This entrypoint is a regular file rather than a symlink: a tracked symlink\n"
        "here made the deterministic-evidence run unconstructible.\n"
    )
    (colosseum / "ledger.md").write_text(build_ledger(project))
    (colosseum / "obligations.json").write_text(json.dumps({
        "schema": "colosseum-obligations",
        "version": 1,
        "claims": [{"claim_id": claim["id"], "required": True} for claim in CLAIMS],
    }, indent=2) + "\n")
    (colosseum / "g1-claims.json").write_text(json.dumps({
        "schema": "colosseum-g1-claims",
        "version": 1,
        "profile": PROFILE,
        "environment_policy": ENVIRONMENT_POLICY,
        "claims": [{
            "claim_id": claim["id"],
            "evidence_class": "bounded-checked",
            "layers": claim["layers"],
            "required_targets": claim["targets"],
            "scope": {
                "statement": claim["statement"],
                "discharged": [
                    f"{target_layer(t)} {target_name(t)} observed in the recorded run"
                    for t in claim["targets"]
                ],
            },
            "waiver": {"excluded": [claim["boundary"]]},
        } for claim in CLAIMS],
    }, indent=1) + "\n")
    (colosseum / "verified-inputs.txt").write_text(
        "# Paths whose contents can change what a verification layer decides.\n"
        "#\n"
        "# An include list, deliberately: under an exclude-everything-else rule a\n"
        "# README fix staled all nine records for a change no layer reads.\n"
        "#\n"
        "# In scope, with the layer that reads it:\n"
        "#   crates                        proptest, Kani\n"
        "#   quint                         Quint typecheck/run\n"
        "#   proofs                        Lean, Verus\n"
        + "".join(f"{entry}\n" for entry in LEGACY_INCLUDE_LIST)
    )

    runs = colosseum / "evidence" / "runs"
    runs.joinpath("layer-runs.json").write_text(json.dumps({
        "schema": "colosseum-layer-runs",
        "version": 2,
        "generated": "2026-09-15T01:21:48Z",
        "host": "Darwin 25.6.0 arm64",
        "source_snapshot": "916401cb23d88057a79d85778eb597f991725f78",
        "verified_inputs_hash": fake_digest("verified-inputs"),
        "runner_hash": fake_digest("runner"),
        "runs": [{
            "command": entry["command"],
            "cwd": entry["cwd"],
            "environment": entry["environment"],
            "exit_status": 0,
            "layer": entry["layer"],
            "log": f"{entry['layer']}.log",
            "raw_output_hash": fake_digest(f"log-{entry['layer']}"),
            "run_id": f"{entry['layer']}-20260915T012148Z",
            "runner_hash": fake_digest("runner"),
            "source_snapshot": "916401cb23d88057a79d85778eb597f991725f78",
            "toolchain_digests": {entry["layer"]: fake_digest(f"tool-{entry['layer']}")},
            "toolchain_versions": {entry["layer"]: f"{entry['layer']} 1.0.0"},
            "verified_inputs_hash": fake_digest("verified-inputs"),
        } for entry in LAYER_RUNS],
    }, indent=4) + "\n")
    for entry in LAYER_RUNS:
        runs.joinpath(f"{entry['layer']}.log").write_text(
            f"$ {entry['command']}\ntest result: ok.\n"
            f"--- fv-evidence: exit=0 ---\n")

    g1 = colosseum / "evidence" / "g1"
    for claim in CLAIMS:
        commands = [command_of(layer) for layer in claim["layers"]]
        g1.joinpath(f"{claim['id']}.json").write_text(
            json.dumps(legacy_g1_record(claim, commands), indent=2) + "\n")
    g1.joinpath("README.md").write_text(
        "# Typed G1 evidence records\n\n"
        "One record per required claim in `.colosseum/obligations.json`.\n")
    for name, body in (
        ("quint-2026-08-26.md", "# Quint layer evidence\n\nRun EVIDENCED 2026-08-26.\n"),
        ("kani-2026-08-26.md", "# Kani layer evidence\n\nRun EVIDENCED 2026-08-26.\n"),
        ("vouch-vlayer-2026-08-28.md", "# Fetched collateral\n\nProse, not a G1 record.\n"),
    ):
        (colosseum / "evidence" / name).write_text(body)

    prose = {
        "attacks": ["2026-09-14-record-storage-intent.md",
                    "intent-2026-08-26T10-58-16Z.md",
                    "quint-registry-2026-08-26T09-56-13Z.md"],
        "changes": ["2026-08-31-pr-review-fixes.md", "2026-09-11-pr-review-closure.md"],
        "code-adversarial": ["2026-09-14-record-storage-code-adversary.md",
                             "2026-09-14-trust-anchor-recheck.md"],
        "classifications": ["ledger-2026-09-15-record-storage.md",
                            "q-b19-cold-cache-2026-09-15.md"],
        "verify": ["2026-08-25T07-12-31Z.md", "2026-09-14-record-storage.md"],
    }
    for directory, names in prose.items():
        for name in names:
            (colosseum / directory / name).write_text(
                f"# {directory}: {name}\n\nHistorical record, preserved verbatim.\n")
    for directory, name, payload in (
        ("attacks", "2026-09-11-integration-intent-round1.json",
         {"round": 1, "findings": ["under-specified retention floor"]}),
        ("changes", "2026-09-14-record-storage.json",
         {"classification": "intent-touching", "source_pr": 11,
          "decisions": {"layout": "raw chunks", "capacity": "persisted counts"}}),
    ):
        (colosseum / directory / name).write_text(json.dumps(payload, indent=2) + "\n")

    scripts = colosseum / "scripts"
    for name in ("check_evidence_records.py", "check_ledger_references.py",
                 "emit_evidence_records.py"):
        scripts.joinpath(name).write_text(
            f"#!/usr/bin/env python3\n"
            f'"""Legacy {name}: the project-local gate that predates the FV scripts."""\n'
            "raise SystemExit(0)\n")
    scripts.joinpath("run_verification_layers.sh").write_text(
        "#!/usr/bin/env bash\n"
        "# Run every verification layer and emit a machine-readable run manifest.\n"
        "set -euo pipefail\n"
        "layers=(lean verus proptest kani quint)\n"
    )
    # Non-UTF-8 bytes: a byte-faithful copier must carry these unchanged.
    scripts.joinpath("__pycache__/emit_evidence_records.cpython-311.pyc").write_bytes(
        b"\xa7\x0d\x0d\x0a\x00\x00\x00\x00legacy-cache\xff\xfe\x00\x01")


def build_project(root: Path) -> Path:
    project = root / "dossier-integration"
    project.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(project)], check=True,
                   capture_output=True, text=True)
    git(project, "config", "user.email", "fixture@example.com")
    git(project, "config", "user.name", "R36 fixture")
    build_sources(project)
    build_colosseum(project)
    git(project, "add", "-A")
    git(project, "commit", "-qm", "dossier integration fixture")
    return project


# ── expectations derived from the legacy inputs ─────────────────────────


def expected_plan_layers() -> dict[str, dict]:
    """The plan the legacy manifest must translate into.

    Every legacy layer is translated: one whose id a known pyramid layer owns
    is renamed (`proptest` -> `proptests`), and every other one -- `quint`
    here -- keeps its legacy id as a custom plan layer. A semicolon-joined
    command becomes one execution per segment in source order; the last
    execution carries the bare legacy layer id (the segment whose exit status
    the legacy runner reported) and earlier ones a 1-based suffix, so a cohort
    never repeats an evidence tool id. A layer is gating when some required
    claim names it -- which, in the dossier shape every layer is named by,
    pins every translated layer to required.
    """
    named = required_evidence_union()
    layers: dict[str, dict] = {}
    for entry in LAYER_RUNS:
        legacy = entry["layer"]
        segments = [segment.strip() for segment in entry["command"].split(";")]
        executions = []
        for index, segment in enumerate(segments, start=1):
            execution = {
                "argv": shlex.split(segment),
                "cwd": entry["cwd"],
                "timeout_seconds": MIGRATED_TIMEOUT,
                "evidence_tool": legacy if index == len(segments) else f"{legacy}:{index}",
            }
            if entry["environment"]:
                execution["env"] = dict(entry["environment"])
            executions.append(execution)
        layers[LEGACY_PLAN_LAYERS.get(legacy, legacy)] = {"required": legacy in named,
                                                          "executions": executions}
    return layers


def required_evidence_union() -> set[str]:
    """Every evidence tool id some claim's required_evidence names."""
    return {layer for claim in CLAIMS for layer in claim["layers"]}


def expected_plan_order(names: object) -> list[str]:
    """Plan execution order: known pyramid layers first, then custom ids."""
    known = [name for name in pyramid_run.LAYER_ORDER if name in names]
    return known + sorted(name for name in names
                          if name not in pyramid_run.LAYER_ORDER)


def expected_obligation_ids() -> tuple[list[str], list[str]]:
    """Synthesized (invariant ids, witness ids): the migrated id of every
    distinct required target, deduped and sorted as the manifest declares
    them."""
    invariants: set[str] = set()
    witnesses: set[str] = set()
    for claim in CLAIMS:
        for target in claim["targets"]:
            (witnesses if target_layer(target) in ("proptest", "test")
             else invariants).add(migrated_id(target))
    return sorted(invariants), sorted(witnesses)


def expected_legacy_targets() -> list[str]:
    """Every distinct legacy required target, in first-seen order."""
    seen: list[str] = []
    for claim in CLAIMS:
        for target in claim["targets"]:
            if target not in seen:
                seen.append(target)
    return seen


def claims_requiring(target: str) -> list[str]:
    return sorted(claim["id"] for claim in CLAIMS if target in claim["targets"])


def legacy_files(project: Path) -> set[str]:
    return {
        path.relative_to(project).as_posix()
        for path in (project / ".colosseum").rglob("*")
        if path.is_file() and not path.is_symlink()
    }


def outside_files(project: Path) -> dict[str, str]:
    """Every tracked-source byte the migration must leave alone."""
    return {path: content for path, content in file_map(project).items()
            if not path.startswith((".fv/", ".git/"))}


# ── stages ─────────────────────────────────────────────────────────────


def check_dry_run(project: Path, colosseum_hash: str) -> dict:
    plain = migrate(project)
    check("dry-run exits 0 on a dossier-shaped project", plain.returncode == 0,
          (plain.stdout + plain.stderr)[-400:])
    check("dry-run writes no .fv tree", not (project / ".fv").exists())

    result, report = migrate_json(project)
    check("dry-run --json reports status ok in dry-run mode",
          result.returncode == 0 and report.get("status") == "ok"
          and report.get("mode") == "dry-run",
          f"exit={result.returncode} {str(report)[:200]}")
    check("dry-run --json still writes nothing", not (project / ".fv").exists())
    check("dry-run report carries no absolute machine path",
          report.get("project_root") == "."
          and not any(str(entry.get("path", "")).startswith("/")
                      for entry in report.get("writes", [])),
          report.get("project_root"))
    check("the text report still names the resolved project root",
          str(project) in plain.stdout, plain.stdout.splitlines()[:1])
    check("dry-run report names the elected dispatch target",
          report.get("target_spec") == "docs/intent.md", report.get("target_spec"))

    artifacts = report.get("artifacts", [])
    sources = [entry.get("source") for entry in artifacts]
    file_rows = {source for source in sources if "#" not in str(source)}
    check("inventory classifies every legacy file exactly once",
          file_rows == legacy_files(project) and len(sources) == len(set(sources)),
          sorted(legacy_files(project) ^ file_rows))
    check("every classification is one of the three literals",
          {entry.get("classification") for entry in artifacts} <= CLASSIFICATIONS,
          sorted({str(entry.get("classification")) for entry in artifacts}))
    check("no legacy artifact is unsupported in this shape",
          [entry["source"] for entry in artifacts
           if entry.get("classification") == "unsupported"] == [])
    tally = Counter(entry["classification"] for entry in artifacts)
    check("counts tally every classification literal, zeros included",
          report.get("counts") == {name: tally.get(name, 0) for name in CLASSIFICATIONS},
          report.get("counts"))
    check("artifacts are sorted by source", sources == sorted(sources))
    writes = report.get("writes", [])
    paths = [entry.get("path") for entry in writes]
    check("writes are sorted and land only under .fv/",
          paths == sorted(paths) and paths
          and all(str(path).startswith(".fv/") for path in paths),
          paths[:5])
    check("dry-run reports every write as a create",
          {entry.get("action") for entry in writes} == {"create"},
          sorted({str(entry.get("action")) for entry in writes}))
    check("dry-run reports no conflicts and nothing unsupported",
          report.get("conflicts") == [] and report.get("unsupported") == [],
          f"{report.get('conflicts')} {report.get('unsupported')}")
    return report


def check_blocked_before_writes(root: Path, project: Path) -> None:
    """A non-regular legacy file is unsupported, and apply writes nothing."""
    copy = root / "blocked-copy"
    shutil.copytree(project, copy, symlinks=True)
    (copy / ".colosseum" / "intent-link.md").symlink_to(Path("..") / "docs" / "intent.md")
    result, report = migrate_json(copy, "--apply")
    check("apply on an unsupported legacy artifact exits 1",
          result.returncode == 1, f"exit={result.returncode}")
    check("blocked report names the unsupported artifact",
          report.get("status") == "blocked"
          and any(".colosseum/intent-link.md" in str(entry)
                  for entry in report.get("unsupported", [])),
          f"{report.get('status')} {report.get('unsupported')}")
    check("blocked apply writes no .fv tree at all", not (copy / ".fv").exists())


def mutate_layer_run(copy: Path, layer: str, changes: dict) -> None:
    """Rewrite one run of a copied legacy layer-runs manifest."""
    path = copy / ".colosseum" / "evidence" / "runs" / "layer-runs.json"
    document = json.loads(path.read_text())
    document["runs"] = [{**entry, **changes} if entry["layer"] == layer else entry
                        for entry in document["runs"]]
    path.write_text(json.dumps(document, indent=4) + "\n")


def check_untranslatable_required_layer(root: Path, project: Path) -> None:
    """A required legacy layer that cannot be translated blocks the run.

    `quint` is named by C-01's required_evidence (and by seven other claims),
    so dropping it from the plan would publish a manifest whose required
    evidence the plan can never produce. An unparseable command and a
    recorded cwd that no longer exists are therefore unsupported -- blocking,
    in dry-run as well as under --apply -- and never a preserved-history
    deviation that leaves the rest of the plan looking complete.
    """
    source = ".colosseum/evidence/runs/layer-runs.json#layers.quint"
    mutations = (
        ("unparseable command",
         {"command": "python3 tools/probe.py typecheck 'quint/dossier.qnt"}),
        ("missing cwd", {"cwd": "quint/workdir-that-no-longer-exists"}),
    )
    for index, (label, changes) in enumerate(mutations):
        copy = root / f"untranslatable-quint-{index}"
        shutil.copytree(project, copy, symlinks=True)
        mutate_layer_run(copy, "quint", changes)
        legacy_hash = tree_hash(copy / ".colosseum")
        before = file_map(copy)

        result, report = migrate_json(copy)
        rows = {entry["source"]: entry for entry in report.get("artifacts", [])}
        check(f"{label}: dry-run is blocked, not ok",
              result.returncode == 1 and report.get("status") == "blocked"
              and report.get("mode") == "dry-run",
              f"exit={result.returncode} {report.get('status')} {report.get('mode')}")
        check(f"{label}: the report names the quint layer unsupported",
              any(source in str(entry) for entry in report.get("unsupported", [])),
              report.get("unsupported"))
        check(f"{label}: the quint row classifies as unsupported",
              rows.get(source, {}).get("classification") == "unsupported",
              rows.get(source, {}))
        downgraded = [row for row in rows.values()
                      if row.get("classification") == "preserved-history"
                      and ("#layers." in str(row.get("source", ""))
                           or "untranslated" in str(row.get("detail", "")))]
        check(f"{label}: quint is never downgraded to preserved history",
              not downgraded, downgraded[:2])
        check(f"{label}: the blocked dry-run writes nothing at all",
              not (copy / ".fv").exists() and file_map(copy) == before
              and tree_hash(copy / ".colosseum") == legacy_hash,
              sorted(set(file_map(copy)) ^ set(before))[:5])

        applied, apply_report = migrate_json(copy, "--apply")
        check(f"{label}: --apply refuses the same run before any write",
              applied.returncode == 1 and apply_report.get("status") == "blocked"
              and not (copy / ".fv").exists() and file_map(copy) == before,
              f"exit={applied.returncode} {apply_report.get('status')} "
              f"{sorted(set(file_map(copy)) ^ set(before))[:5]}")


def check_apply(project: Path, dry_report: dict, colosseum_hash: str,
                outside_before: dict[str, str]) -> dict:
    result, report = migrate_json(project, "--apply")
    check("apply exits 0", result.returncode == 0,
          f"exit={result.returncode} {result.stderr[-300:]}")
    check("apply reports status ok in apply mode",
          report.get("status") == "ok" and report.get("mode") == "apply",
          f"{report.get('status')} {report.get('mode')}")
    check("dry-run predicted exactly the writes apply performed",
          [(entry["path"], entry["sha256"]) for entry in report.get("writes", [])]
          == [(entry["path"], entry["sha256"]) for entry in dry_report.get("writes", [])])
    check("every planned create is reported as written after the apply",
          {entry["action"] for entry in dry_report.get("writes", [])} == {"create"}
          and {entry["action"] for entry in report.get("writes", [])} == {"written"},
          sorted({str(entry.get("action")) for entry in report.get("writes", [])}))
    check("the apply report distinguishes request from outcome",
          report.get("requested_mode") == "apply" and report.get("applied") is True
          and report.get("error") is None,
          {key: report.get(key) for key in ("requested_mode", "applied", "error")})
    check("no staging directory survives the apply",
          not [path for path in (project / ".fv").rglob("*") if "staging" in path.name],
          [path.name for path in (project / ".fv").rglob("*") if "staging" in path.name])
    for entry in report.get("writes", []):
        path = project / entry["path"]
        if not path.is_file():
            check(f"apply wrote {entry['path']}", False, "missing")
            return report
    check("every write digest matches the bytes on disk",
          all(sha256_bytes((project / entry["path"]).read_bytes()) == entry.get("sha256")
              for entry in report.get("writes", [])))
    check("apply wrote nothing outside .fv/",
          outside_files(project) == outside_before,
          sorted(set(outside_files(project).items()) ^ set(outside_before.items()))[:4])
    return report


def check_target(project: Path, report: dict) -> None:
    dispatch = json.loads((project / ".fv" / "dispatch.json").read_text())
    route = dispatch.get("omp_native", {})
    check("dispatch stores the ledger-referenced external intent as the target",
          route.get("target_spec") == "docs/intent.md", route.get("target_spec"))
    check("dispatch stores a portable project_root",
          route.get("project_root") == ".", route.get("project_root"))
    check("the migration does not invent a .fv/intent.md",
          not (project / ".fv" / "intent.md").exists())
    resolved = resolver(project, "target")
    check("the canonical resolver agrees on docs/intent.md",
          resolved.get("target_spec") == "docs/intent.md"
          and resolved.get("declared") == "docs/intent.md", resolved)
    rows = {entry["source"]: entry for entry in report.get("artifacts", [])}
    stub = rows.get(".colosseum/intent.md", {})
    check("the legacy intent stub maps to dispatch",
          stub.get("classification") == "mapped"
          and stub.get("destination") == ".fv/dispatch.json", stub)


def check_ledger(project: Path, report: dict) -> None:
    migrated = (project / ".fv" / "ledger.md").read_bytes()
    legacy = (project / ".colosseum" / "ledger.md").read_bytes()
    check("the ledger is carried over byte-for-byte", migrated == legacy)
    row = {entry["source"]: entry for entry in report.get("artifacts", [])}.get(
        ".colosseum/ledger.md", {})
    check("the ledger is reported as mapped to .fv/ledger.md",
          row.get("classification") == "mapped" and row.get("destination") == ".fv/ledger.md",
          row)


def check_manifest(project: Path) -> None:
    manifest = json.loads((project / ".fv" / "obligations.json").read_text())
    claims = {entry["id"]: entry for entry in manifest.get("system_claims", [])}
    check("every legacy claim becomes a system claim, ids verbatim",
          [entry["id"] for entry in manifest.get("system_claims", [])]
          == [claim["id"] for claim in CLAIMS],
          sorted(claims))
    depends_ok, evidence_ok, retained_ok = True, True, True
    for claim in CLAIMS:
        entry = claims.get(claim["id"], {})
        depends_ok &= entry.get("depends_on") == [migrated_id(target)
                                                 for target in claim["targets"]]
        evidence_ok &= entry.get("required_evidence") == claim["layers"]
        retained_ok &= (entry.get("required") is True
                        and entry.get("evidence_class") == "bounded-checked"
                        and entry.get("scope", {}).get("statement") == claim["statement"]
                        and entry.get("waiver", {}).get("excluded") == [claim["boundary"]])
    check("depends_on names each claim's migrated targets in source order", depends_ok,
          claims.get("C-07", {}).get("depends_on"))
    check("required_evidence is the claim's layer list, not its target prefixes", evidence_ok,
          claims.get("C-01", {}).get("required_evidence"))
    check("scope, waiver, evidence_class and required survive the conversion", retained_ok,
          claims.get("C-01", {}))
    check("an already-safe legacy claim id is kept, not restated in legacy_id",
          all("legacy_id" not in entry for entry in manifest.get("system_claims", [])),
          [entry.get("legacy_id") for entry in manifest.get("system_claims", [])])

    invariants, witnesses = expected_obligation_ids()
    declared_invariants = [entry["id"] for entry in manifest.get("invariants", [])]
    declared_witnesses = [entry["id"] for entry in manifest.get("witnesses", [])]
    check("proptest targets are synthesized as witnesses, sorted and deduped",
          declared_witnesses == witnesses, declared_witnesses)
    check("every other target is synthesized as an invariant, sorted and deduped",
          declared_invariants == invariants, declared_invariants)
    check("no obligation id is declared twice across collections",
          len(set(declared_invariants) | set(declared_witnesses))
          == len(declared_invariants) + len(declared_witnesses))

    synthesized = manifest.get("invariants", []) + manifest.get("witnesses", [])
    by_legacy = {entry.get("legacy_id"): entry for entry in synthesized}
    check("every synthesized obligation retains the exact legacy target it came from",
          sorted(by_legacy) == sorted(expected_legacy_targets()),
          sorted(set(by_legacy) ^ set(expected_legacy_targets())))
    check("each legacy target is keyed under the id its migration produces",
          all(by_legacy[target]["id"] == migrated_id(target)
              for target in expected_legacy_targets() if target in by_legacy),
          [(target, by_legacy.get(target, {}).get("id"))
           for target in expected_legacy_targets()
           if by_legacy.get(target, {}).get("id") != migrated_id(target)])
    check("a witness keeps the unnormalized legacy target name",
          all(entry["name"] == target_name(entry["legacy_id"])
              for entry in manifest.get("witnesses", [])),
          [(entry.get("name"), entry.get("legacy_id"))
           for entry in manifest.get("witnesses", [])])
    safe = evidence_claim_id_pattern()
    every_id = [entry["id"] for entry in synthesized + manifest.get("system_claims", [])]
    check("every migrated id is a claim_id the evidence producer accepts",
          bool(every_id) and all(safe.fullmatch(identifier) for identifier in every_id),
          [identifier for identifier in every_id if not safe.fullmatch(identifier)])

    grounded = all(
        target_name(entry["legacy_id"]) in entry.get("statement", "")
        and target_layer(entry["legacy_id"]) in entry.get("statement", "")
        and all(claim_id in entry.get("statement", "")
                for claim_id in claims_requiring(entry["legacy_id"]))
        for entry in synthesized
    )
    check("each synthesized statement names its layer, legacy target and requiring claims",
          grounded,
          by_legacy.get("kani:derivation_path_prefix_and_injectivity", {}).get("statement"))
    check_record_filenames(project, every_id)
    provenance = json.dumps(manifest.get("migration", {}))
    check("the migration block retains the legacy profile, policy and sources",
          PROFILE in provenance and ENVIRONMENT_POLICY in provenance
          and ".colosseum/g1-claims.json" in provenance
          and ".colosseum/obligations.json" in provenance, provenance[:300])


def check_record_filenames(project: Path, every_id: list[str]) -> None:
    """Each migrated id is usable as the record filename the producer derives.

    `tools/evidence-run.ts` joins the id straight onto
    `.fv/evidence/records/` and `.fv/evidence/raw/`, so an id carrying a path
    separator would write outside the directory it is supposed to land in, and
    one carrying a colon is not a portable filename at all. The records are
    written into a scratch tree beside the project: the rehearsed project's
    own records directory has to stay empty for the Gate B stage.
    """
    records = project.parent / "record-filenames" / ".fv" / "evidence" / "records"
    records.mkdir(parents=True, exist_ok=True)
    for identifier in every_id:
        record = records / f"{identifier}.json"
        if record.parent != records:
            check("every migrated id is one filename, not a path", False, identifier)
            return
        record.write_text(json.dumps({"claim_id": identifier, "result": "PASS"}) + "\n")
        raw = records.parent.parent / "raw" / f"{identifier}-run-1.log"
        raw.parent.mkdir(parents=True, exist_ok=True)
        raw.write_text("PASS\n")
    written = sorted(path.name for path in records.iterdir())
    check("every migrated id is one filename, not a path",
          written == sorted(f"{identifier}.json" for identifier in every_id), written[:4])
    read_back = {json.loads(path.read_text())["claim_id"] for path in records.glob("*.json")}
    check("a record written at <id>.json is the record a records glob reads back",
          read_back == set(every_id), sorted(read_back ^ set(every_id))[:4])


def check_plan(project: Path, report: dict, probe_log: Path) -> None:
    plan_path = project / ".fv" / "verification-plan.json"
    plan = json.loads(plan_path.read_text())
    expected = expected_plan_layers()
    check("the plan declares fv-verification-plan/v1",
          plan.get("schema") == "fv-verification-plan/v1", plan.get("schema"))
    check("every legacy layer is declared, known names renamed and custom ids kept",
          set(plan.get("layers", {})) == set(expected), sorted(plan.get("layers", {})))
    check("quint survives as a custom plan layer rather than being dropped",
          "quint" in plan.get("layers", {}), sorted(plan.get("layers", {})))
    check("each translated layer carries exactly its converted executions",
          plan.get("layers") == expected,
          json.dumps(plan.get("layers", {}).get("quint"), sort_keys=True)[:400])
    required_union = required_evidence_union()
    missing = sorted(layer for layer in required_union
                     if LEGACY_PLAN_LAYERS.get(layer, layer) not in plan.get("layers", {}))
    check("every layer some claim requires is a plan layer, none omitted",
          not missing, missing)
    downgraded = sorted(
        layer for layer in required_union
        if plan.get("layers", {}).get(LEGACY_PLAN_LAYERS.get(layer, layer), {})
        .get("required") is not True)
    check("no required layer is downgraded to required: false", not downgraded, downgraded)
    tools = [execution.get("evidence_tool")
             for layer in plan.get("layers", {}).values()
             for execution in layer.get("executions", [])]
    check("the plan's evidence_tool ids cover every claim's required evidence",
          required_union <= set(tools), sorted(required_union - set(tools)))
    check("no evidence_tool id is declared twice across the plan",
          len(tools) == len(set(tools)),
          sorted(tool for tool in set(tools) if tools.count(tool) > 1))
    executions = [execution for layer in plan.get("layers", {}).values()
                  for execution in layer.get("executions", [])]
    check("no execution is a shell string or a wrapped sh -c",
          all(";" not in argument for execution in executions
              for argument in execution.get("argv", []))
          and all(execution.get("argv", [""])[0] not in ("sh", "bash", "zsh")
                  for execution in executions))

    # The only consumer of a plan must be able to load what the migration wrote.
    try:
        loaded = pyramid_run.load_plan(plan_path, project)
        error = ""
    except pyramid_run.PlanError as failure:
        loaded, error = {}, str(failure)
    check("pyramid_run loads the migrated plan", error == "", error)
    order = expected_plan_order(expected)
    check("the loaded plan runs known layers in pyramid order, then custom ids",
          list(loaded.get("layers", {})) == order, list(loaded.get("layers", {})))
    check("the loaded plan keeps every execution in source order",
          [[execution["argv"] for execution in layer["executions"]]
           for layer in loaded.get("layers", {}).values()]
          == [[execution["argv"] for execution in expected[name]["executions"]]
              for name in order],
          list(loaded.get("layers", {})))

    # Executed for real: the semicolon split must run as N argv invocations,
    # and a custom layer executes exactly like a known one.
    probe_log.write_text("")
    ran = []
    for name in expected_plan_order(plan.get("layers", {})):
        for execution in plan["layers"][name]["executions"]:
            environment = {**os.environ, **execution.get("env", {}),
                           "R36_PROBE_LOG": str(probe_log)}
            outcome = run(execution["argv"], cwd=project / execution["cwd"], env=environment)
            ran.append((name, outcome.returncode, outcome.stdout))
    check("every declared layer contributed at least one execution",
          {name for name, _, _ in ran} == set(expected),
          sorted(set(expected) - {name for name, _, _ in ran}))
    check("every migrated execution runs as written and exits 0",
          ran and all(code == 0 for _, code, _ in ran),
          [(name, code) for name, code, _ in ran if code != 0])
    # The probe logs its own argv tail, so the comparison is against the legacy
    # command minus the interpreter and the script path.
    logged = [line.split("\t") for line in probe_log.read_text().splitlines()]
    proptest_segments = [segment.strip() for segment in command_of("proptest").split(";")]
    check("the two proptest segments ran in source order, neither dropped",
          [" ".join(shlex.split(segment)[2:]) for segment in proptest_segments]
          == [argv for _, argv in logged if "--features mock-attestation" in argv],
          [argv for _, argv in logged])
    quint_segments = [segment.strip() for segment in command_of("quint").split(";")]
    check("every quint segment ran in source order, neither dropped",
          [" ".join(shlex.split(segment)[2:]) for segment in quint_segments]
          == [argv for _, argv in logged if "quint/dossier.qnt" in argv],
          [argv for _, argv in logged])
    check("a declared layer cwd is honoured",
          any(Path(cwd).resolve() == (project / "proofs" / "lean").resolve()
              for cwd, _ in logged), [cwd for cwd, _ in logged])

    rows = {entry["source"]: entry for entry in report.get("artifacts", [])}
    manifest_row = rows.get(".colosseum/evidence/runs/layer-runs.json", {})
    check("the layer-runs manifest is reported as mapped to the plan",
          manifest_row.get("classification") == "mapped"
          and manifest_row.get("destination") == ".fv/verification-plan.json", manifest_row)
    check("no layer is reported as a deviation: every one came across",
          not [source for source in rows if "#layers." in source],
          [(source, rows[source].get("classification"))
           for source in rows if "#layers." in source])
    check("the mapped detail names quint among the translated layers",
          "quint" in str(manifest_row.get("detail", "")), manifest_row.get("detail"))


def check_verified_inputs(project: Path) -> None:
    """The legacy include list becomes an FV include policy, not an exclusion list."""
    policy = fv_project.load_policy(project)
    check("the migrated policy declares include mode",
          policy.mode == fv_project.MODE_INCLUDE, policy.mode)
    selectors = set(policy.selectors())
    source_roots = {entry for entry in LEGACY_INCLUDE_LIST
                    if not entry.startswith(".colosseum/")}
    check("every legacy source root is carried across verbatim",
          source_roots <= selectors, sorted(source_roots - selectors))
    check("the legacy manifest entries bind the FV artifacts they migrated to",
          ".fv/obligations.json" in selectors
          and ".fv/verification-plan.json" in selectors
          and not [entry for entry in selectors if entry.startswith(".colosseum/")],
          sorted(selectors))
    check("the policy binds itself, so revising it moves the snapshot",
          policy.selects(fv_project.VERIFIED_INPUTS_RELATIVE), sorted(selectors))
    check("the structural output exclusions still apply under include mode",
          set(FV_DEFAULT_EXCLUSIONS) <= set(policy.exclusions())
          and HISTORY_EXCLUSION in policy.exclusions()
          and STAGING_EXCLUSION in policy.exclusions(),
          policy.exclusions())
    legacy_copy = project / HISTORY_ROOT / "verified-inputs.txt"
    check("the legacy include list survives verbatim as history",
          legacy_copy.is_file()
          and legacy_copy.read_bytes()
          == (project / ".colosseum" / "verified-inputs.txt").read_bytes())
    inputs = resolver(project, "inputs")
    paths = {entry["path"] for entry in inputs} if isinstance(inputs, list) else set()
    check("the snapshot binds the sources a layer reads",
          {"docs/intent.md", "quint/dossier.qnt"} <= paths, sorted(paths)[:8])
    check("the snapshot binds the policy itself",
          fv_project.VERIFIED_INPUTS_RELATIVE in paths, sorted(paths)[:8])
    check("the snapshot binds the migrated manifests",
          {".fv/obligations.json", ".fv/verification-plan.json"} <= paths, sorted(paths)[:8])
    # The reason the legacy project wrote an include list, preserved by the
    # translation: a tracked file no layer reads cannot stale a record.
    check("a tracked path the policy does not name is not a verified input",
          "README.md" not in paths and not policy.selects("README.md"),
          sorted(paths)[:8])
    check("no imported or legacy byte is a verified input",
          not [path for path in paths
               if path.startswith(".colosseum/") or path.startswith(".fv/history/")],
          [path for path in paths if path.startswith((".colosseum/", ".fv/history/"))][:5])


def check_killed_staging_residue(project: Path) -> None:
    """Staging residue cannot move the snapshot evidence is bound to.

    A hard-killed apply runs no cleanup, so its staging tree stays on disk
    under `.fv/.migrate-staging/<run>/`. This project is a real git
    repository with real verified inputs, which makes it the place the claim
    is testable end to end rather than by reading an exclusion list: the
    snapshot every evidence record binds to must be the same digit for digit
    before the residue appears, while it sits there, and after it is removed.
    The residue is synthesized here instead of produced by a kill, because
    what is under test is the snapshot, not the kill -- R35 kills a real
    apply and asserts the residue lands nowhere else.
    """
    before = fv_project.content_snapshot(project)
    staging = project / STAGING_ROOT / "4242-abcdefgh"
    (staging / "new").mkdir(parents=True)
    (staging / "new" / "obligations.json").write_text('{"strand": "half-staged"}\n')
    (staging / "saved").mkdir()
    (staging / "saved" / "dispatch.json").write_text('{"strand": "replaced original"}\n')
    during = fv_project.content_snapshot(project)
    entries = [path for path, _ in fv_project.snapshot_entries(project)]
    check("staging residue does not move the verified-input snapshot",
          during == before, f"{before} -> {during}")
    check("no staged or saved byte is a verified input",
          not [path for path in entries if path.startswith(STAGING_ROOT)],
          [path for path in entries if path.startswith(STAGING_ROOT)][:3])
    check("git would otherwise have offered the residue as a candidate",
          any(path.startswith(STAGING_ROOT) for path in fv_project.candidate_paths(project)),
          [path for path in fv_project.candidate_paths(project)
           if path.startswith(".fv/")][:3])
    shutil.rmtree(project / STAGING_ROOT)
    check("removing the residue by hand does not move it either",
          fv_project.content_snapshot(project) == before)


def check_history(project: Path, report: dict) -> None:
    rows = {entry["source"]: entry for entry in report.get("artifacts", [])}
    mismatched, misplaced = [], []
    for source in sorted(legacy_files(project)):
        row = rows.get(source, {})
        if row.get("classification") != "preserved-history":
            continue
        destination = row.get("destination")
        if not isinstance(destination, str) or not destination.startswith(".fv/"):
            misplaced.append(source)
            continue
        copied = project / destination
        if not copied.is_file() or copied.read_bytes() != (project / source).read_bytes():
            mismatched.append(source)
    check("every preserved artifact is copied byte-for-byte", not mismatched, mismatched[:5])
    check("preserved artifacts land under .fv/", not misplaced, misplaced[:5])
    pyc = project / HISTORY_ROOT / "scripts/__pycache__/emit_evidence_records.cpython-311.pyc"
    check("a non-UTF-8 legacy artifact survives the copy",
          pyc.is_file() and pyc.read_bytes()
          == (project / ".colosseum" / "scripts" / "__pycache__"
              / "emit_evidence_records.cpython-311.pyc").read_bytes())
    for directory in ("attacks", "changes", "code-adversarial", "classifications",
                      "verify", "evidence/g1"):
        legacy = project / ".colosseum" / directory
        copied = project / HISTORY_ROOT / directory
        names = {path.name for path in legacy.iterdir() if path.is_file()}
        check(f"legacy {directory} history is complete",
              copied.is_dir() and names <= {path.name for path in copied.iterdir()},
              sorted(names - {path.name for path in copied.iterdir()})
              if copied.is_dir() else "missing")


def check_no_live_legacy_records(project: Path) -> None:
    records = project / ".fv" / "evidence" / "records"
    existing = sorted(path.name for path in records.glob("*.json")) if records.is_dir() else []
    check("the migration publishes no live evidence record", existing == [], existing)
    live = [path for path in (project / ".fv" / "evidence").rglob("*.json")] \
        if (project / ".fv" / "evidence").exists() else []
    legacy_shaped = [path.relative_to(project).as_posix() for path in live
                     if "colosseum" in path.read_text(errors="replace")
                     or '"parser_schema_version": 1' in path.read_text(errors="replace")]
    check("no legacy-shaped record is visible under .fv/evidence", not legacy_shaped,
          legacy_shaped[:5])
    for claim in CLAIMS:
        copied = project / HISTORY_ROOT / "evidence" / "g1" / f"{claim['id']}.json"
        if not copied.is_file():
            check("legacy G1 records are kept as history", False, claim["id"])
            return
    check("legacy G1 records are kept as history", True)


def check_gate_a(project: Path) -> None:
    result = gate_a(project)
    check("Gate A passes on the converted ledger",
          result.returncode == 0 and "GATE PASSED" in result.stdout,
          (result.stdout + result.stderr)[-500:])
    check("Gate A pass names its scope only",
          "reference integrity only" in result.stdout)
    check("Gate A checked real content-bound citations",
          any(line.startswith("Citations checked:") and " (0 content-bound)" not in line
              for line in result.stdout.splitlines()),
          result.stdout.splitlines()[:2])
    strict = gate_a(project, "--strict-kani")
    check("Gate A passes under --strict-kani (every link carries kani:)",
          strict.returncode == 0, (strict.stdout + strict.stderr)[-500:])


def check_gate_b(project: Path, stage: str) -> dict:
    records = project / ".fv" / "evidence" / "records"
    records.mkdir(parents=True, exist_ok=True)
    result, report = gate_b(project)
    statuses = {entry["claim_id"]: entry["status"] for entry in report.get("per_claim", [])}
    check(f"{stage}: Gate B returns INCOMPLETE (exit 3)",
          result.returncode == 3 and report.get("verdict") == "INCOMPLETE",
          f"exit={result.returncode} {report.get('verdict')}")
    check(f"{stage}: the manifest itself is accepted (no ERROR)",
          "malformed obligation manifest" not in result.stdout
          and result.returncode != 2, result.stdout[:300])
    check(f"{stage}: every required claim is INCOMPLETE only for a missing record",
          statuses and set(statuses.values()) == {"missing-record"},
          sorted(set(statuses.values())))
    check(f"{stage}: Gate B requires every migrated claim",
          {claim["id"] for claim in CLAIMS} <= set(report.get("required_claims", [])),
          report.get("required_claims"))
    kinds = report.get("obligation_kinds", {})
    check(f"{stage}: migrated claims enter the required set as system claims",
          all(kinds.get(claim["id"]) == "system_claim" for claim in CLAIMS),
          {claim["id"]: kinds.get(claim["id"]) for claim in CLAIMS})
    evidence = report.get("required_evidence", {})
    check(f"{stage}: Gate B reads each claim's required evidence tools",
          all(evidence.get(claim["id"]) == claim["layers"] for claim in CLAIMS),
          {claim["id"]: evidence.get(claim["id"]) for claim in CLAIMS[:2]})
    check(f"{stage}: Gate B binds evidence to the migrated external target",
          report.get("intent_path") == "docs/intent.md", report.get("intent_path"))
    check(f"{stage}: no claim is reported failed",
          report.get("failed") == [], report.get("failed"))
    return report


def check_idempotent(project: Path, colosseum_hash: str, before: dict[str, str]) -> None:
    result, report = migrate_json(project, "--apply")
    check("re-apply exits 0 with status ok",
          result.returncode == 0 and report.get("status") == "ok",
          f"exit={result.returncode} {report.get('status')}")
    check("re-apply reports every write as already identical",
          {entry.get("action") for entry in report.get("writes", [])} == {"identical"},
          sorted({str(entry.get("action")) for entry in report.get("writes", [])}))
    check("re-apply reports no conflict", report.get("conflicts") == [],
          report.get("conflicts"))
    check("re-apply changes not a single .fv byte",
          file_map(project / ".fv") == before,
          sorted(set(file_map(project / ".fv").items()) ^ set(before.items()))[:4])
    check("re-apply keeps .colosseum byte-identical",
          tree_hash(project / ".colosseum") == colosseum_hash)


def check_fv_init(project: Path, colosseum_hash: str, before: dict[str, str]) -> None:
    if shutil.which("uv") is None:
        check("fv_init completes the shadow", False, "uv not on PATH")
        return
    result = run(["uv", "run", "--script", str(INIT), str(project)])
    check("fv_init exits 0 on a migrated project", result.returncode == 0,
          (result.stdout + result.stderr)[-500:])
    after = file_map(project / ".fv")
    migrated = ("ledger.md", "obligations.json", "verification-plan.json",
                "verified-inputs.txt")
    check("fv_init rewrites no migrated artifact",
          all(after.get(name) == before.get(name) for name in migrated),
          [name for name in migrated if after.get(name) != before.get(name)])
    check("fv_init rewrites no imported history byte",
          {path: digest for path, digest in after.items() if path.startswith("history/")}
          == {path: digest for path, digest in before.items() if path.startswith("history/")})
    route = json.loads((project / ".fv" / "dispatch.json").read_text())["omp_native"]
    check("fv_init preserves the migrated canonical target",
          route.get("target_spec") == "docs/intent.md" and route.get("project_root") == ".",
          route)
    check("fv_init completes the FV shadow",
          (project / ".fv" / "scripts" / "fv_project.py").is_file()
          and (project / ".fv" / "panels").is_dir()
          and (project / ".fv" / "harness").read_text() == "omp\n")
    legacy_script = project / HISTORY_ROOT / "scripts" / "check_evidence_records.py"
    live_script = project / ".fv" / "scripts" / "check_evidence_records.py"
    check("the legacy project-local gate stays history, not a live FV script",
          legacy_script.read_bytes()
          == (project / ".colosseum" / "scripts" / "check_evidence_records.py").read_bytes()
          and live_script.is_file()
          and live_script.read_bytes() != legacy_script.read_bytes())
    check("fv_init keeps .colosseum byte-identical",
          tree_hash(project / ".colosseum") == colosseum_hash)


def check_move(root: Path, project: Path, colosseum_hash: str,
               fv_before: dict[str, str]) -> None:
    moved = root / "relocated" / "dossier-integration"
    moved.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(project), str(moved))
    resolved = resolver(moved, "target")
    check("dispatch resolution survives a move",
          resolved.get("target_spec") == "docs/intent.md"
          and Path(resolved.get("target", "")).resolve()
          == (moved / "docs" / "intent.md").resolve(), resolved)
    check("the move rewrote no .fv byte", file_map(moved / ".fv") == fv_before)
    check("the move kept .colosseum byte-identical",
          tree_hash(moved / ".colosseum") == colosseum_hash)
    result = gate_a(moved, "--strict-kani")
    check("Gate A still passes from the new location", result.returncode == 0,
          (result.stdout + result.stderr)[-400:])
    check_gate_b(moved, "after move")


def check_intent_election(root: Path, project: Path) -> None:
    """The dispatch target comes from the stub, and ambiguity blocks.

    The dossier ledger is long prose that names documents many times. If the
    election counted mentions, a "Superseded:" paragraph could outvote the
    entrypoint's own pointer and bind every migrated evidence record to a
    document the project stopped maintaining.
    """
    superseded = root / "intent-superseded"
    shutil.copytree(project, superseded, symlinks=True)
    (superseded / "docs" / "old-intent.md").write_text("# superseded dossier intent\n")
    ledger = superseded / ".colosseum" / "ledger.md"
    ledger.write_text(
        "## Superseded\n\nSee docs/old-intent.md, docs/old-intent.md and docs/old-intent.md.\n\n"
        + ledger.read_text())
    result, report = migrate_json(superseded)
    check("the pointer stub outranks every ledger mention of another intent",
          result.returncode == 0 and report.get("target_spec") == "docs/intent.md",
          f"exit={result.returncode} {report.get('target_spec')}")

    ambiguous = root / "intent-ambiguous"
    shutil.copytree(project, ambiguous, symlinks=True)
    (ambiguous / "docs" / "old-intent.md").write_text("# superseded dossier intent\n")
    (ambiguous / ".colosseum" / "intent.md").write_text(
        "# Intent: dossier\nThe canonical intent document is [`docs/intent.md`]"
        "(../docs/intent.md), or `docs/old-intent.md` while the move finishes.\n")
    legacy_hash = tree_hash(ambiguous / ".colosseum")
    result, report = migrate_json(ambiguous, "--apply")
    check("a stub citing two existing intents blocks instead of electing one",
          result.returncode == 1 and report.get("status") == "blocked"
          and report.get("target_spec") is None
          and any("#intent" in str(entry) for entry in report.get("unsupported", [])),
          f"exit={result.returncode} {report.get('unsupported')}")
    check("the ambiguous run writes nothing and touches no legacy byte",
          not (ambiguous / ".fv").exists()
          and tree_hash(ambiguous / ".colosseum") == legacy_hash)


def check_write_containment(root: Path, project: Path, colosseum_hash: str) -> None:
    """A symlinked `.fv` component cannot carry a write out of the FV tree.

    The digest assertions elsewhere in this suite only fire if a write can
    reach `.colosseum` at all; this is the shape that made that reachable.
    """
    for label, link, target in (
        ("fv-root", Path(".fv"), Path("..") / "escaped"),
        ("history", Path(".fv") / "history", Path("..") / ".colosseum" / "imported"),
    ):
        copy = root / f"containment-{label}"
        shutil.copytree(project, copy, symlinks=True)
        (copy / "escaped").mkdir(exist_ok=True)
        (copy / ".colosseum" / "imported").mkdir(exist_ok=True)
        (copy / link).parent.mkdir(parents=True, exist_ok=True)
        (copy / link).symlink_to(target)
        legacy_hash = tree_hash(copy / ".colosseum")
        result, report = migrate_json(copy, "--apply")
        check(f"{label}: a symlinked .fv component blocks every write",
              result.returncode == 1 and report.get("status") == "blocked"
              and any("is a symlink" in str(entry) for entry in report.get("conflicts", [])),
              f"exit={result.returncode} {report.get('conflicts', [])[:1]}")
        check(f"{label}: nothing landed outside the FV tree",
              tree_hash(copy / ".colosseum") == legacy_hash
              and not list((copy / "escaped").rglob("*"))
              and not list((copy / ".colosseum" / "imported").rglob("*")),
              sorted(path.name for path in (copy / "escaped").rglob("*")))
    check("the untouched project's legacy tree is still the one that was read",
          tree_hash(project / ".colosseum") == colosseum_hash)


def check_uncovered_required_evidence(root: Path, project: Path) -> None:
    """A claim whose required evidence no migrated run can produce blocks.

    Eight of the nine dossier claims name `quint`. Dropping its recorded run
    leaves a manifest whose required evidence the migrated plan can never
    produce -- the same defect as omitting a recorded layer, one artifact
    upstream -- so it is unsupported rather than a status-ok migration.
    """
    copy = root / "uncovered-evidence"
    shutil.copytree(project, copy, symlinks=True)
    path = copy / ".colosseum" / "evidence" / "runs" / "layer-runs.json"
    document = json.loads(path.read_text())
    document["runs"] = [entry for entry in document["runs"] if entry["layer"] != "quint"]
    path.write_text(json.dumps(document, indent=4) + "\n")
    before = file_map(copy)
    result, report = migrate_json(copy, "--apply")
    rows = [entry for entry in report.get("unsupported", []) if "required_evidence" in str(entry)]
    check("a claim requiring an unrecorded layer blocks the migration",
          result.returncode == 1 and report.get("status") == "blocked" and rows,
          f"exit={result.returncode} {report.get('unsupported', [])[:1]}")
    check("every claim that names the missing layer is reported, none summarized",
          len(rows) == len([claim for claim in CLAIMS if "quint" in claim["layers"]]),
          f"{len(rows)} rows")
    check("the blocked run writes nothing at all",
          not (copy / ".fv").exists() and file_map(copy) == before)


def check_dispatch_adoption(root: Path, project: Path) -> None:
    """An existing dispatch keeps its route; only the two owned fields move."""
    copy = root / "dispatch-adoption"
    shutil.copytree(project, copy, symlinks=True)
    (copy / ".fv").mkdir(parents=True, exist_ok=True)
    (copy / ".fv" / "dispatch.json").write_text(json.dumps({
        "omp_native": {"project_root": "/absolute/elsewhere",
                       "target_spec": ".fv/intent.md",
                       "profile": "canonical-4@sha256:deadbeef"},
        "panel": {"roster": ["alpha", "beta"]},
    }, indent=2) + "\n")
    result, report = migrate_json(copy, "--apply")
    route = json.loads((copy / ".fv" / "dispatch.json").read_text())
    check("an existing dispatch is adopted rather than blocking the migration",
          result.returncode == 0 and report.get("status") == "ok"
          and any(entry["path"] == ".fv/dispatch.json" and entry["action"] == "written"
                  and "adopted" in entry.get("detail", "")
                  for entry in report.get("writes", [])),
          f"exit={result.returncode} "
          f"{[e for e in report.get('writes', []) if 'dispatch' in e['path']]}")
    check("adoption rewrites only project_root and target_spec",
          route["omp_native"]["target_spec"] == "docs/intent.md"
          and route["omp_native"]["project_root"] == "."
          and route["omp_native"]["profile"] == "canonical-4@sha256:deadbeef"
          and route["panel"] == {"roster": ["alpha", "beta"]},
          json.dumps(route, sort_keys=True))
    resolved = resolver(copy, "target")
    check("the adopted project resolves the migrated target",
          resolved.get("target_spec") == "docs/intent.md", resolved)


def main() -> int:
    for binary in ("git", "python3"):
        if shutil.which(binary) is None:
            print(f"SKIP-FAIL: {binary} not on PATH; the rehearsal could not run",
                  file=sys.stderr)
            return 2
    if not MIGRATE.exists():
        print(f"  [     FAIL] scripts/fv_migrate.py is missing at {MIGRATE}")
        print("\nVERDICT: FAILED (1 failure)")
        return 1

    with tempfile.TemporaryDirectory(prefix="r36-dossier-") as temporary:
        root = Path(temporary).resolve()
        project = build_project(root)
        colosseum_hash = tree_hash(project / ".colosseum")
        outside_before = outside_files(project)
        print("\n── dry run ──────────────────────────────────────────────")
        dry_report = check_dry_run(project, colosseum_hash)
        check_blocked_before_writes(root, project)
        check_untranslatable_required_layer(root, project)
        check_intent_election(root, project)
        check_write_containment(root, project, colosseum_hash)
        check_uncovered_required_evidence(root, project)
        check_dispatch_adoption(root, project)

        print("\n── apply ────────────────────────────────────────────────")
        report = check_apply(project, dry_report, colosseum_hash, outside_before)
        check_target(project, report)
        check_ledger(project, report)
        check_manifest(project)
        check_plan(project, report, root / "probe-runs.log")
        check_verified_inputs(project)
        check_killed_staging_residue(project)
        check_history(project, report)
        check_no_live_legacy_records(project)

        print("\n── gates ────────────────────────────────────────────────")
        check_gate_a(project)
        check_gate_b(project, "after apply")

        print("\n── idempotence, shadow, relocation ──────────────────────")
        fv_state = file_map(project / ".fv")
        check_idempotent(project, colosseum_hash, fv_state)
        check_fv_init(project, colosseum_hash, fv_state)
        check_move(root, project, colosseum_hash, file_map(project / ".fv"))

    print()
    if FAILURES:
        print(f"VERDICT: FAILED ({len(FAILURES)}: {', '.join(FAILURES[:6])}"
              f"{', ...' if len(FAILURES) > 6 else ''})")
        return 1
    print("VERDICT: PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
