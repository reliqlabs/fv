#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
R6 — manifest fail-closed control flow in fv_run.py (E4, contract G2), plus the
canonical-target / verified-input-snapshot contract shared by fv_project.py and
Gate B (check_evidence_records.py).

Zero-voice manifests are invalid runs everywhere they could be read;
duplicate voice ids are rejected at init and at load; an all-errored
`wait` exits nonzero (all-terminal is not success when zero voices
completed); `synthesize` refuses pending/errored inputs without an
explicit --allow-partial and labels the output PARTIAL when overridden;
zero completed voices cannot be synthesized at all; `reset` retains the
prior attempt in the voice's history instead of erasing it.

Project-binding half: the dispatch target may be an external doc
(docs/intent.md) and Gate B binds intent to it rather than to .fv/intent.md;
the verified-input snapshot is stable across a commit of unchanged content and
invalidates records when a verified input changes; targets that escape the
project root (or are missing, a directory, a symlink, or ``~``-prefixed) are
rejected; evidence, verify, panel, quarantined-history, and declared exclusion
outputs never enter the snapshot; a verified input that is not a regular file is
classified instead of hanging the hash; an exclusion list carrying a byte-order
mark, a control character, or a line break the Python and TypeScript parsers
would read differently is rejected outright while non-ASCII path entries stay
legal; and v2 records still validate under explicit
--expect-snapshot/--allow-unbound, which the verdict scope discloses as
binding=pinned/unbound rather than recomputed.

System-claim half: obligations.json may declare system_claims, which Gate B
aggregates into the required-claim set with kind system_claim; a claim whose
depends_on or required_evidence list is empty, duplicated, unknown, or
malformed makes the whole manifest an ERROR, an obligation id the evidence
producer could never write a record for is an ERROR too, dependencies name
invariants and witnesses only (so no dependency cycle between claims is
representable), --require on a system claim also requires what it depends on,
and manifests with no system_claims gate exactly as before.

Cohort honesty: each execution's evidence class is judged against the obligation
kind and against the waiver rule, and each PASS artifact belongs to exactly one
execution of one claim.

Cohort provenance: the cohort schema is the producer's, so a v3 record must
declare the producer profile and, as required_targets, exactly the obligation set
the manifest the run is judged against declares - neither read back off the
record. A v2 record predates both rules and keeps its own profile and its own
target list, which is what the v2 cases exercise.

Record attribution: the waiver is the only thing that turns an assumed claim into
a PASS, so it must name a nonempty id, approver and scope - a bare flag, an id
alone, an arbitrary object, or a blank field is refused, while an attributable
waiver still passes. A record is judged stale against the obligation manifest the
run is handed, and the canonical target path it asserts has to be a string before
anything resolves it. All three are record text, so they bind with or without a
repository tree.

Exit 0 pass, 1 fail.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RUN = REPO / "scripts" / "fv_run.py"
GATE_B = REPO / "scripts" / "check_evidence_records.py"
FAILURES: list[str] = []

sys.path.insert(0, str(REPO / "scripts"))
import fv_project  # noqa: E402  module under test


def check(label: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"  [ok]   {label}")
    else:
        suffix = f" ({detail})" if detail else ""
        print(f"  [FAIL] {label}{suffix}")
        FAILURES.append(label)


def crun(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["uv", "run", "--script", str(RUN), *args],
                          capture_output=True, text=True, timeout=120)


def gate_b(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["uv", "run", "--script", str(GATE_B), *args],
                          capture_output=True, text=True, timeout=180)


def git(project: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "user.email=r6@fv.test", "-c", "user.name=r6",
                    "-c", "commit.gpgsign=false", *args],
                   cwd=project, capture_output=True, text=True, check=True, timeout=60)


def git_out(project: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=project, capture_output=True,
                          text=True, check=True, timeout=60).stdout.strip()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rejects(spec: str, project: Path) -> bool:
    try:
        fv_project.resolve_target(project, spec)
    except fv_project.ProjectError:
        return True
    return False


def build_project(root: Path) -> Path:
    """Git project whose canonical target is an external docs/intent.md."""
    project = root / "proj"
    for relative in ("src", "docs", ".fv"):
        (project / relative).mkdir(parents=True)
    (project / "src" / "lib.rs").write_text("pub fn ok() -> bool { true }\n")
    (project / "docs" / "intent.md").write_text(
        "# external intent\n\nC1: the canonical target may live outside .fv\n")
    (project / ".fv" / "intent.md").write_text("# decoy intent\n")
    (project / ".fv" / "dispatch.json").write_text(json.dumps(
        {"omp_native": {"project_root": ".", "target_spec": "docs/intent.md"}},
        indent=2) + "\n")
    (project / ".fv" / "obligations.json").write_text(json.dumps(
        {"invariants": [{"id": "A1", "statement": "ok() holds"}]}, indent=2) + "\n")
    (project / ".fv" / "verified-inputs.txt").write_text(
        "# project exclusions\n\n  build/  \n")
    git(project, "init", "-q")
    git(project, "add", "-A")
    git(project, "commit", "-qm", "init")
    return project


# Evidence class and raw-log marker each fixture tool's execution produces.
TOOL_EVIDENCE = {
    "kani": ("bounded-checked", "No violation found"),
    "verus": ("proof-discharged", "VERIFICATION:- SUCCESSFUL"),
}


def cohort_for(tools: list[str]) -> list[dict]:
    """One execution spec per tool, each carrying the marker its class demands."""
    specs = []
    for tool in tools:
        evidence_class, marker = TOOL_EVIDENCE.get(tool, ("code-enforced", ""))
        specs.append({"tool": tool, "evidence_class": evidence_class, "marker": marker,
                      "command": [tool, "--check"]})
    return specs


def manifest_targets(project: Path) -> list[str]:
    """Every obligation id the project's manifest declares, in Gate B's order.

    The producer asserts the whole declared set as `required_targets`, and both
    Gate B and the coverage dashboard now diff that assertion against the manifest
    the run is judged against, so a v3 fixture has to carry the set rather than the
    one claim it happens to be about.
    """
    manifest = json.loads((project / ".fv" / "obligations.json").read_text())
    ids: list[str] = []
    for collection in ("invariants", "witnesses", "system_claims"):
        entries = manifest.get(collection)
        if not isinstance(entries, list):
            continue
        ids.extend(item["id"] for item in entries
                   if isinstance(item, dict) and isinstance(item.get("id"), str))
    return ids


def write_record(project: Path, snapshot: str, intent_hash: str,
                 schema: str = "fv-evidence-run/v3", claim_id: str = "A1",
                 evidence_class: str = "code-enforced", marker: str = "",
                 cohort: list[dict] | None = None) -> Path:
    """Write a single PASS record under .fv/evidence; returns the records directory.

    A cohort spec is {tool, evidence_class?, marker?, command?, cwd?, result?}. Each
    execution gets its own raw artifact, and the record's legacy bindings are derived
    from the first execution exactly as the producer derives them.

    A v3 record is producer-written by definition, so it is written the producer's
    way throughout: the producer profile, `<claim>-<run_id>.log` artifacts, and the
    manifest's complete obligation set as `required_targets`. A v2 record predates
    all three and keeps the legacy shape, which is what the v2 cases exercise.
    """
    raw_dir = project / ".fv" / "evidence" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    specs = cohort if cohort else [{"tool": "true", "marker": marker, "command": ["true"]}]
    executions: list[dict] = []
    producer = schema == "fv-evidence-run/v3"
    for index, spec in enumerate(specs):
        run_id = f"r6-{claim_id}-{index}"
        name = f"{claim_id}-{run_id}.log"
        raw = raw_dir / name
        result = spec.get("result", "PASS")
        line = spec.get("marker", marker)
        raw.write_text("fixture check\n"
                       + (f"{line}\n" if line else "")
                       + f"--- fv-evidence: exit={0 if result == 'PASS' else 7} ---\n")
        executions.append({
            "tool": spec["tool"],
            "evidence_class": spec.get("evidence_class", evidence_class),
            "command": list(spec.get("command", ["true"])),
            "cwd": spec.get("cwd", "."),
            "toolchain_digests": {
                "executable": f"/usr/bin/{spec['tool']}",
                "sha256": hashlib.sha256(spec["tool"].encode()).hexdigest(),
                "version": "r6-fixture",
                "version_exit_code": 0,
            },
            "raw_output_path": f".fv/evidence/raw/{name}",
            "raw_output_hash": sha256_file(raw),
            "result": result,
            "run_id": run_id,
        })
    records = project / ".fv" / "evidence" / "records"
    records.mkdir(parents=True, exist_ok=True)
    primary = executions[0]
    bindings = {
        "source_snapshot": snapshot,
        "intent_hash": intent_hash,
        "intent_path": "docs/intent.md",
        "obligation_manifest_hash": sha256_file(project / ".fv" / "obligations.json"),
        "profile": "producer-trusted-execution" if producer else "r6-fixture",
        "required_targets": manifest_targets(project) if producer else [claim_id],
        "environment_policy": "r6-fixture-local",
        "toolchain_digests": primary["toolchain_digests"],
        "command": json.dumps(primary["command"]),
        "configuration": {"cwd": primary["cwd"]},
        "seeds": None,
        "raw_output_hash": primary["raw_output_hash"],
        "raw_output_path": primary["raw_output_path"],
        "parser_schema_version": schema,
        "run_id": f"r6-{claim_id}",
    }
    # Only v3 carries the execution cohort; a v2 record is exactly what it always was.
    if producer:
        bindings["executions"] = executions
    record = {
        "claim_id": claim_id,
        "required": True,
        "evidence_class": evidence_class,
        "result": "PASS",
        "scope": f"r6 fixture obligation {claim_id}",
        "bindings": bindings,
        "waiver": None,
    }
    (records / f"{claim_id}.json").write_text(json.dumps(record, indent=2) + "\n")
    return records


def resolver_checks(root: Path, project: Path) -> None:
    target = fv_project.resolve_target(project)
    check("resolver: dispatch target_spec resolves to external docs/intent.md",
          target == (project / "docs" / "intent.md").resolve(), str(target))
    check("resolver: resolved target round-trips to a repo-relative target_spec",
          fv_project.relative_target_spec(project, target) == "docs/intent.md")
    check("resolver: target_spec that does not exist yet is still relativizable",
          fv_project.relative_target_spec(project, project / ".fv" / "intent-new.md")
          == ".fv/intent-new.md")
    check("resolver: legacy absolute target inside the project root is accepted",
          fv_project.resolve_target(project, str(project / "docs" / "intent.md")) == target)

    plain = root / "plain"
    (plain / ".fv").mkdir(parents=True)
    (plain / ".fv" / "intent.md").write_text("# default target\n")
    check("resolver: missing dispatch.json defaults to .fv/intent.md",
          fv_project.resolve_target(plain) == (plain / ".fv" / "intent.md").resolve())
    (plain / ".fv" / "dispatch.json").write_text(
        json.dumps({"omp_native": {"project_root": "."}}, indent=2) + "\n")
    check("resolver: dispatch without target_spec defaults to .fv/intent.md",
          fv_project.resolve_target(plain) == (plain / ".fv" / "intent.md").resolve()
          and fv_project.declared_target_spec(plain) is None)
    (plain / ".fv" / "dispatch.json").write_text("{not json")
    check("resolver: malformed dispatch.json fails closed",
          rejects_route(plain))

    outside = root / "outside.md"
    outside.write_text("# not in the project\n")
    for label, spec in (("relative parent escape", "../outside.md"),
                        ("absolute path outside root", str(outside)),
                        ("nonexistent file", "docs/nope.md"),
                        ("directory", ".fv"),
                        ("empty spec", "   "),
                        ("home-relative spec", "~/intent.md"),
                        ("bare tilde", "~"),
                        ("other user's home", "~someone/intent.md")):
        check(f"resolver rejects target: {label}", rejects(spec, project))
    # ~ is rejected, never expanded: expanding it here while the producer resolves
    # it under the project root would bind the two ends to different files.
    tilde_dir = project / "~"
    tilde_dir.mkdir()
    (tilde_dir / "intent.md").write_text("# home-shaped decoy\n")
    try:
        check("resolver rejects target: ~ is never expanded, even when <root>/~ exists",
              rejects("~/intent.md", project))
    finally:
        (tilde_dir / "intent.md").unlink()
        tilde_dir.rmdir()
    link = project / "docs" / "linked-intent.md"
    link.symlink_to(project / "docs" / "intent.md")
    try:
        check("resolver rejects target: symlink", rejects("docs/linked-intent.md", project))
    finally:
        link.unlink()


def rejects_route(project: Path) -> bool:
    try:
        fv_project.dispatch_route(project)
    except fv_project.ProjectError:
        return True
    return False


def snapshot_checks(project: Path) -> str:
    """Snapshot semantics; returns the snapshot of the committed project."""
    initial = fv_project.content_snapshot(project)
    check("snapshot: well-formed sha256 content snapshot",
          fv_project.is_content_snapshot(initial), initial)
    check("snapshot: recomputation is deterministic",
          fv_project.content_snapshot(project) == initial)

    head = git_out(project, "rev-parse", "HEAD")
    extra = project / "src" / "extra.rs"
    extra.write_text("pub const N: u8 = 1;\n")
    untracked = fv_project.content_snapshot(project)
    check("snapshot: untracked unignored file enters the snapshot", untracked != initial)
    git(project, "add", "-A")
    git(project, "commit", "-qm", "extra")
    committed = fv_project.content_snapshot(project)
    check("snapshot: stable across a commit of unchanged content",
          committed == untracked and git_out(project, "rev-parse", "HEAD") != head)

    for relative in (".fv/evidence/raw/noise.log", ".fv/verify/report.json",
                     ".fv/panels/run.json", ".fv/history/colosseum/legacy-record.json",
                     ".colosseum/intent.md"):
        path = project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("noise\n")
    check("snapshot: default exclusions keep evidence/verify/panel/history outputs out",
          fv_project.content_snapshot(project) == committed)
    # Quarantining legacy history is structural, not a project-file favour: dropping
    # the entry must visibly change the snapshot, so a project that never declares it
    # still cannot have its evidence invalidated by one.
    without_history = tuple(entry for entry in fv_project.DEFAULT_EXCLUSIONS
                            if entry != ".fv/history/")
    check("snapshot: .fv/history/ is a structural default exclusion",
          ".fv/history/" in fv_project.DEFAULT_EXCLUSIONS
          and fv_project.content_snapshot(project, fv_project.DEFAULT_EXCLUSIONS)
          != fv_project.content_snapshot(project, without_history))
    (project / "build").mkdir()
    (project / "build" / "out.bin").write_bytes(b"\x00\x01")
    check("snapshot: declared build/ exclusion keeps build output out",
          fv_project.content_snapshot(project) == committed)
    stray = project / "src" / "stray.rs"
    stray.write_text("pub const M: u8 = 2;\n")
    check("snapshot: unexcluded new input changes the snapshot",
          fv_project.content_snapshot(project) != committed)
    stray.unlink()

    check("exclusions: blank and # lines ignored, ./ stripped",
          fv_project.parse_exclusions("# comment\n\n  ./tmp/  \nlogs/\n") == ["tmp/", "logs/"])
    check("exclusions: defaults union the declared list",
          set(fv_project.DEFAULT_EXCLUSIONS) <= set(fv_project.load_exclusions(project))
          and "build/" in fv_project.load_exclusions(project))
    for bad in ("/etc/", "../outside/", "."):
        rejected = False
        try:
            fv_project.parse_exclusions(bad + "\n")
        except fv_project.ProjectError:
            rejected = True
        check(f"exclusions reject entry {bad!r}", rejected)
    # Python splits or strips these; JS's split("\n")/trim() do not. Accepting one
    # would make the gate and the producer hash different input sets.
    for label, text in (("lone CR", "logs/\rtmp/\n"),
                        ("vertical tab", "logs/\x0btmp/\n"),
                        ("form feed", "logs/\x0ctmp/\n"),
                        ("file separator", "logs/\x1ctmp/\n"),
                        ("next line", "logs/\x85tmp/\n"),
                        ("line separator", "logs/\u2028tmp/\n")):
        rejected = False
        try:
            fv_project.parse_exclusions(text)
        except fv_project.ProjectError:
            rejected = True
        check(f"exclusions reject ambiguous line terminator: {label}", rejected)
    check("exclusions: CRLF stays legal and parses like LF",
          fv_project.parse_exclusions("logs/\r\ntmp/\r\n") == ["logs/", "tmp/"])
    # A byte-order mark survives Python's utf-8 decode and is dropped by a JavaScript
    # runtime's, so a list carrying one would exclude build/ in the producer and hash
    # it in the gate, with nothing in either report naming the parse as the cause.
    for label, text in (("leading BOM", "\ufeffbuild/\n"),
                        ("BOM on a comment line", "\ufeff# generated\nbuild/\n"),
                        ("interior BOM", "build/\n\ufefflogs/\n")):
        message = ""
        try:
            fv_project.parse_exclusions(text)
        except fv_project.ProjectError as error:
            message = str(error)
        check(f"exclusions reject a byte-order mark: {label}",
              "byte-order mark U+FEFF" in message, message)
    # Every control character that is not a terminator: \x1f is stripped on the Python
    # side only, \t is invisible inside an entry, \x00 cannot occur in a path at all.
    for label, text in (("tab inside an entry", "bu\tild/\n"), ("leading tab", "\tbuild/\n"),
                        ("unit separator", "build/\x1f\n"), ("nul", "build/\x00\n"),
                        ("delete", "build/\x7f\n"), ("C1 control", "build/\x9f\n")):
        message = ""
        try:
            fv_project.parse_exclusions(text)
        except fv_project.ProjectError as error:
            message = str(error)
        check(f"exclusions reject control character: {label}",
              "control character" in message, message)
    # Rejecting the BOM and the controls must not cost legitimate Unicode: a non-ASCII
    # entry is a normal prefix and excludes the directory it names.
    unicode_entry = fv_project.parse_exclusions("# unicode paths stay legal\n\u65e5\u672c\u8a9e/\n")
    unicode_dir = project / "\u65e5\u672c\u8a9e"
    unicode_dir.mkdir()
    (unicode_dir / "out.bin").write_bytes(b"\x02\x03")
    try:
        check("exclusions: a non-ASCII path entry parses and excludes its directory",
              unicode_entry == ["\u65e5\u672c\u8a9e/"]
              and fv_project.is_excluded("\u65e5\u672c\u8a9e/out.bin", unicode_entry)
              and fv_project.content_snapshot(
                  project,
                  [*fv_project.DEFAULT_EXCLUSIONS, "build/", *unicode_entry]) == committed,
              unicode_entry)
    finally:
        (unicode_dir / "out.bin").unlink()
        unicode_dir.rmdir()
    check("snapshot: component-wise exclusion does not swallow sibling prefixes",
          fv_project.is_excluded("build/out.bin", ["build"])
          and not fv_project.is_excluded("buildout.bin", ["build"]))

    symlinked = project / "src" / "link.rs"
    symlinked.symlink_to(project / "src" / "lib.rs")
    rejected = False
    try:
        fv_project.content_snapshot(project)
    except fv_project.ProjectError:
        rejected = True
    symlinked.unlink()
    check("snapshot: symlinked verified input fails closed", rejected)

    fifo = project / "src" / "extra.rs"
    original = fifo.read_bytes()
    fifo.unlink()
    os.mkfifo(fifo)
    rejected = ""
    try:
        fv_project.content_snapshot(project)
    except fv_project.ProjectError as error:
        rejected = str(error)
    finally:
        fifo.unlink()
        fifo.write_bytes(original)
    # Opening a FIFO blocks until a writer appears: classify it, never hash it.
    check("snapshot: tracked path replaced by a FIFO is rejected, not opened",
          "not a regular file" in rejected, rejected)
    return committed


def gate_checks(project: Path, snapshot: str) -> None:
    manifest = project / ".fv" / "obligations.json"
    intent = fv_project.target_hash(project)

    def run_gate(*extra: str) -> subprocess.CompletedProcess:
        return gate_b("--records", str(project / ".fv" / "evidence" / "records"),
                      "--manifest", str(manifest), "--root", str(project), *extra)

    write_record(project, snapshot, intent)
    result = run_gate("--json")
    report = json.loads(result.stdout) if result.stdout.strip().startswith("{") else {}
    check("Gate B: default binding verifies a record bound to the content snapshot",
          result.returncode == 0 and "VERIFIED" in result.stderr,
          f"exit={result.returncode} {result.stdout[-300:]}{result.stderr[-200:]}")
    check("Gate B: report names the resolved external target and expected snapshot",
          report.get("intent_path") == "docs/intent.md"
          and report.get("expected_snapshot") == snapshot,
          f"{report.get('intent_path')!r} {report.get('expected_snapshot')!r}")
    # A VERIFIED that recomputed both bindings and one that was handed them, or told
    # to skip them, are different claims: the scope has to say which one this is.
    check("Gate B: recomputed freshness is disclosed as binding=recomputed",
          "VERIFIED[profile=producer-trusted-execution; binding=recomputed]" in result.stderr
          and report.get("binding") == "recomputed",
          f"{result.stderr[-200:]} {report.get('binding')!r}")

    result = run_gate("--expect-snapshot", snapshot)
    check("Gate B: operator-pinned freshness is disclosed as binding=pinned",
          result.returncode == 0
          and "VERIFIED[profile=producer-trusted-execution; binding=pinned]" in result.stderr,
          f"exit={result.returncode} {result.stderr[-200:]}")
    result = run_gate("--allow-unbound", "--json")
    report = json.loads(result.stdout) if result.stdout.strip().startswith("{") else {}
    check("Gate B: skipped freshness is disclosed as binding=unbound, not as a plain VERIFIED",
          result.returncode == 0
          and "VERIFIED[profile=producer-trusted-execution; binding=unbound]" in result.stderr
          and report.get("intent_path") is None,
          f"exit={result.returncode} {result.stderr[-200:]}")

    records_dir = project / ".fv" / "evidence" / "records"

    def mutate_a1(label: str, mutate, fragment: str, *extra: str,
                  expected: int = 3) -> None:
        """Rebind a fresh A1 record, corrupt one asserted field, expect a rejection."""
        write_record(project, snapshot, intent)
        record_path = records_dir / "A1.json"
        record = json.loads(record_path.read_text())
        mutate(record)
        record_path.write_text(json.dumps(record, indent=2) + "\n")
        result = run_gate(*extra)
        check(f"Gate B rejects record: {label}",
              result.returncode == expected and fragment in result.stdout,
              f"exit={result.returncode} {result.stdout[-300:]}")

    # The producer never writes PASS while dirty; nothing made that marker binding on
    # a hand-written record, and prefix mode used to let it through.
    mutate_a1("PASS bound to a +dirty snapshot, under prefix matching",
              lambda record: record["bindings"].update(source_snapshot=snapshot + "+dirty"),
              "PASS record bound to a dirty snapshot", "--expect-snapshot", snapshot)
    mutate_a1("PASS bound to a +dirty snapshot, under --allow-unbound",
              lambda record: record["bindings"].update(source_snapshot=snapshot + "+dirty"),
              "PASS record bound to a dirty snapshot", "--allow-unbound")
    # intent_hash is compared; the path beside it is what a reader follows to find
    # the intent, so a contained-but-wrong path is drift, not decoration.
    mutate_a1("intent_path names a file other than the resolved canonical target",
              lambda record: record["bindings"].update(intent_path=".fv/intent.md"),
              "stale record: bound to intent path '.fv/intent.md'")
    mutate_a1("waiver is a bare flag rather than an attributable object",
              lambda record: record.update(waiver=True),
              "waiver is not an object: True")
    mutate_a1("waiver names an id and nothing else",
              lambda record: record.update(waiver={"id": "WV-1"}),
              "waiver is not attributable: ['approver', 'scope'] missing or blank")
    mutate_a1("waiver object names nobody and nothing",
              lambda record: record.update(waiver={"by": "", "rationale": ""}),
              "waiver is not attributable: ['id', 'approver', 'scope'] missing or blank")
    mutate_a1("waiver scope is present but blank",
              lambda record: record.update(waiver={"id": "WV-1", "approver": "reviewer",
                                                   "scope": "   "}),
              "waiver is not attributable: ['scope'] missing or blank")
    # The rule is attribution, not the presence of the key: a waiver that says who
    # allowed what still carries an assumption to a PASS, visibly.
    mutate_a1("attributable waiver carries an assumed claim, and is disclosed",
              lambda record: record.update(
                  evidence_class="externally-assumed",
                  waiver={"id": "WV-1", "approver": "reviewer",
                          "scope": "upstream acceptance, this release only"}),
              "PASS-waived", expected=0)
    # Containment needs the repository root, but whether the canonical target is a
    # string at all is record text: it is judged with the other asserted fields, so
    # a consumer without the tree refuses the same record this gate does.
    mutate_a1("intent_path is an object rather than a path",
              lambda record: record["bindings"].update(
                  intent_path={"path": "docs/intent.md"}),
              "binding field 'intent_path' is not a nonempty string",
              "--allow-unbound")
    # The expectation is the hash of the manifest this run was handed, never read
    # back off the record: evidence earned against another obligation set answers
    # another question.
    mutate_a1("record bound to another obligation manifest",
              lambda record: record["bindings"].update(
                  obligation_manifest_hash="0" * 64),
              "stale record: bound to obligation manifest", "--allow-unbound")
    # The profile lands verbatim in the verdict scope: a record must not be able to
    # mint a second scope field claiming the freshness discipline it skipped.
    mutate_a1("profile forges a second verdict-scope field",
              lambda record: record["bindings"].update(
                  profile="r6-fixture; binding=recomputed"),
              "malformed profile 'r6-fixture; binding=recomputed'", "--allow-unbound")
    mutate_a1("required_targets is not a list of obligation ids",
              lambda record: record["bindings"].update(required_targets=["A1", 7]),
              "required_targets is not a nonempty array of obligation ids")
    mutate_a1("run_id is not a string",
              lambda record: record["bindings"].update(run_id=7),
              "binding field 'run_id' is not a nonempty string")
    # Only the producer writes the cohort schema, and every rule that binds a
    # producer record keys off the profile: a v3 record naming another profile would
    # keep the cohort's coverage power while opting out of them.
    mutate_a1("cohort-schema record declaring a profile the producer never writes",
              lambda record: record["bindings"].update(profile="bounded"),
              "not the producer profile 'producer-trusted-execution'")
    # required_targets was record-asserted and read by nothing: the expectation now
    # comes from the manifest the run is judged against, not from the record.
    mutate_a1("required_targets is not the manifest's declared obligation set",
              lambda record: record["bindings"].update(required_targets=["Z9"]),
              "required_targets is not the obligation manifest's required set: "
              "missing ['A1'], unexpected ['Z9']")
    mutate_a1("required_targets repeats a declared obligation",
              lambda record: record["bindings"].update(required_targets=["A1", "A1"]),
              "required_targets repeats an obligation id")

    write_record(project, snapshot, intent)

    write_record(project, snapshot, sha256_file(project / ".fv" / "intent.md"))
    result = run_gate()
    check("Gate B: record bound to .fv/intent.md is stale when dispatch names docs/intent.md",
          result.returncode == 3 and "stale record: bound to intent" in result.stdout,
          f"exit={result.returncode}")

    write_record(project, snapshot, intent)
    lib = project / "src" / "lib.rs"
    lib.write_text("pub fn ok() -> bool { 1 == 1 }\n")
    result = run_gate()
    check("Gate B: changing a verified input invalidates the record",
          result.returncode == 3 and "stale record: bound to snapshot" in result.stdout,
          f"exit={result.returncode}")

    rebound = fv_project.content_snapshot(project)
    write_record(project, rebound, intent)
    git(project, "add", "-A")
    git(project, "commit", "-qm", "change")
    result = run_gate()
    check("Gate B: freshness survives committing the inputs the record is bound to",
          result.returncode == 0, f"exit={result.returncode} {result.stdout[-300:]}")

    dispatch = project / ".fv" / "dispatch.json"
    original = dispatch.read_text()
    dispatch.write_text(json.dumps(
        {"omp_native": {"project_root": ".", "target_spec": "../outside.md"}}, indent=2) + "\n")
    result = run_gate()
    check("Gate B: escaping dispatch target fails closed",
          result.returncode == 2 and "escapes project root" in (result.stdout + result.stderr),
          f"exit={result.returncode}")
    dispatch.write_text(original)

    head = git_out(project, "rev-parse", "HEAD")
    write_record(project, head, intent, "fv-evidence-run/v2")
    result = run_gate("--expect-snapshot", head[:7], "--expect-intent", intent)
    check("Gate B: v2 record validates under explicit --expect-snapshot prefix",
          result.returncode == 0, f"exit={result.returncode} {result.stdout[-300:]}")
    result = run_gate("--allow-unbound")
    check("Gate B: --allow-unbound still accepts an unbound v2 record",
          result.returncode == 0, f"exit={result.returncode}")
    result = run_gate()
    check("Gate B: default freshness rejects a v2 record with a migration hint",
          result.returncode == 3 and "predates verified-input snapshots" in result.stdout,
          f"exit={result.returncode}")

    # The cohort-schema rules are v3's: a v2 record keeps its own profile and its
    # own narrow target list, which is the whole point of the explicit escape hatch.
    record_path = project / ".fv" / "evidence" / "records" / "A1.json"
    legacy = json.loads(record_path.read_text())
    legacy["bindings"].update(profile="legacy-local", required_targets=["Z9"])
    record_path.write_text(json.dumps(legacy, indent=2) + "\n")
    result = run_gate("--allow-unbound")
    check("Gate B: v2 record keeps its own profile and required_targets",
          result.returncode == 0
          and "VERIFIED[profile=legacy-local; binding=unbound]" in result.stderr,
          f"exit={result.returncode} {result.stdout[-300:]}{result.stderr[-200:]}")


def write_manifest(project: Path, payload: dict) -> Path:
    manifest = project / ".fv" / "obligations.json"
    manifest.write_text(json.dumps(payload, indent=2) + "\n")
    return manifest


def system_claim(claim_id: str = "S1", depends_on: object = ("A1", "W1"),
                 required_evidence: object = ("kani", "verus")) -> dict:
    return {
        "id": claim_id,
        "statement": f"{claim_id} composes its dependencies",
        "depends_on": list(depends_on) if isinstance(depends_on, tuple) else depends_on,
        "required_evidence": (list(required_evidence) if isinstance(required_evidence, tuple)
                              else required_evidence),
    }


def claim_manifest(system_claims: object, **overrides: object) -> dict:
    payload: dict = {
        "version": 1,
        "invariants": [{"id": "A1", "statement": "ok() holds"}],
        "witnesses": [{"id": "W1", "name": "witness_w1"}],
        "system_claims": system_claims,
    }
    payload.update(overrides)
    return payload


# Per-claim evidence class and the raw-log marker its class demands.
CLAIM_EVIDENCE = {
    "A1": ("code-enforced", ""),
    "W1": ("test-witnessed", "test result: ok."),
    "S1": ("proof-discharged", ""),
    "S2": ("bounded-checked", "No violation found"),
}


def system_claim_checks() -> None:
    """System claims are aggregated as required obligations and validated structurally."""
    with tempfile.TemporaryDirectory(prefix="r6-claims-") as td:
        project = build_project(Path(td).resolve())
        manifest = project / ".fv" / "obligations.json"
        intent = fv_project.target_hash(project)
        records = project / ".fv" / "evidence" / "records"

        def run_gate(*extra: str) -> subprocess.CompletedProcess:
            return gate_b("--records", str(records), "--manifest", str(manifest),
                          "--root", str(project), *extra)

        def stage(payload: dict, claims: tuple[str, ...],
                  cohorts: dict[str, list[dict]] | None = None) -> None:
            """Freeze a manifest, then bind one fresh record per named claim.

            A system claim's record defaults to a cohort covering exactly the tool IDs
            its declared required_evidence names, which is what Gate B demands of a
            PASS system claim.
            """
            write_manifest(project, payload)
            snapshot = fv_project.content_snapshot(project)
            declared: dict[str, list[str]] = {}
            if isinstance(payload.get("system_claims"), list):
                for item in payload["system_claims"]:
                    if isinstance(item, dict) and isinstance(item.get("required_evidence"), list):
                        declared[item.get("id")] = item["required_evidence"]
            if records.is_dir():
                for stale in records.glob("*.json"):
                    stale.unlink()
            for claim in claims:
                evidence_class, marker = CLAIM_EVIDENCE[claim]
                cohort = (cohorts or {}).get(claim)
                if cohort is None and claim in declared:
                    cohort = cohort_for(declared[claim])
                write_record(project, snapshot, intent, claim_id=claim,
                             evidence_class=evidence_class, marker=marker, cohort=cohort)

        def mutate_s1(label: str, mutate, fragment: str) -> None:
            """Re-stage a covering cohort, corrupt one property of it, expect INCOMPLETE."""
            stage(claim_manifest([system_claim()]), ("A1", "W1", "S1"))
            record_path = records / "S1.json"
            record = json.loads(record_path.read_text())
            mutate(record)
            record_path.write_text(json.dumps(record, indent=2) + "\n")
            result = run_gate()
            check(f"Gate B rejects cohort: {label}",
                  result.returncode == 3 and fragment in result.stdout,
                  f"exit={result.returncode} {result.stdout[-300:]}")

        def drop_verus(record: dict) -> None:
            executions = record["bindings"]["executions"]
            record["bindings"]["executions"] = [e for e in executions if e["tool"] != "verus"]

        def tamper_second_artifact(record: dict) -> None:
            second = record["bindings"]["executions"][1]
            (project / second["raw_output_path"]).write_text(
                "forged verus run\nVERIFICATION:- SUCCESSFUL\n--- fv-evidence: exit=0 ---\n")

        def share_artifact(record: dict) -> None:
            first, second = record["bindings"]["executions"][:2]
            second["raw_output_path"] = first["raw_output_path"]
            second["raw_output_hash"] = first["raw_output_hash"]

        def foreign_artifact(record: dict) -> None:
            """A cohort entry citing a well-formed artifact of a different run.

            The bytes and the hash are real, so nothing but the producer's naming
            rule stands between this record and a PASS: an artifact named for
            another run id is another run's evidence however well-shaped it is."""
            second = record["bindings"]["executions"][1]
            foreign = ".fv/evidence/raw/S1-r6-S1-9.log"
            (project / foreign).write_bytes(
                (project / second["raw_output_path"]).read_bytes())
            second["raw_output_path"] = foreign

        stage(claim_manifest([system_claim()]), ("A1", "W1", "S1"))
        result = run_gate("--json")
        report = json.loads(result.stdout) if result.stdout.strip().startswith("{") else {}
        check("Gate B: system claim is required and verifies alongside its dependencies",
              result.returncode == 0 and "VERIFIED" in result.stderr,
              f"exit={result.returncode} {result.stdout[-300:]}{result.stderr[-200:]}")
        check("Gate B: system claim enters required claims with kind system_claim",
              report.get("required_claims") == ["A1", "S1", "W1"]
              and report.get("obligation_kinds", {}).get("S1") == "system_claim"
              and report.get("obligation_kinds", {}).get("A1") == "invariant",
              f"{report.get('required_claims')} {report.get('obligation_kinds')}")
        check("Gate B: report names each system claim's required evidence tools",
              report.get("required_evidence", {}).get("S1") == ["kani", "verus"],
              str(report.get("required_evidence")))

        stage(claim_manifest([system_claim()]), ("A1", "W1"))
        result = run_gate()
        check("Gate B: declared system claim without a record is INCOMPLETE",
              result.returncode == 3 and "S1: no record" in result.stdout,
              f"exit={result.returncode} {result.stdout[-200:]}")

        stage(claim_manifest([system_claim(required_evidence=("kani",))]), ("A1", "W1", "S1"),
              {"S1": cohort_for(["kani", "verus"])})
        result = run_gate()
        check("Gate B: executions beyond required_evidence do not block a PASS",
              result.returncode == 0, f"exit={result.returncode} {result.stdout[-300:]}")

        stage(claim_manifest([system_claim()]), ("A1", "W1", "S1"),
              {"A1": cohort_for(["cargo-check", "clippy"])})
        result = run_gate()
        check("Gate B: a non-system claim may carry several valid executions",
              result.returncode == 0, f"exit={result.returncode} {result.stdout[-300:]}")

        # The record class is the claim's; each artifact is a tool's. A cohort whose
        # kani log never says "test result: ok." still discharges a test-witnessed claim.
        stage(claim_manifest([system_claim(required_evidence=("kani",))]), ("A1", "W1"))
        write_record(project, fv_project.content_snapshot(project), intent, claim_id="S1",
                     evidence_class="test-witnessed", cohort=cohort_for(["kani"]))
        result = run_gate()
        check("Gate B: each cohort artifact is judged by the class that produced it",
              result.returncode == 0, f"exit={result.returncode} {result.stdout[-300:]}")

        mutate_s1("required tool has no execution", drop_verus,
                  "missing PASS evidence from required tools ['verus']")
        mutate_s1("v2-shaped system claim record covers no tool",
                  lambda record: (record["bindings"].pop("executions"),
                                  record["bindings"].update(parser_schema_version="fv-evidence-run/v2")),
                  "missing PASS evidence from required tools")
        mutate_s1("v3 record without an execution cohort",
                  lambda record: record["bindings"].pop("executions"),
                  "missing binding field 'executions'")
        mutate_s1("failed execution beneath a PASS record",
                  lambda record: record["bindings"]["executions"][1].update(result="FAIL"),
                  "executions[1] result 'FAIL' cannot appear beneath a PASS record")
        mutate_s1("duplicate evidence tool",
                  lambda record: record["bindings"]["executions"][1].update(tool="kani"),
                  "executions[1] duplicate evidence tool 'kani'")
        mutate_s1("tampered second artifact", tamper_second_artifact,
                  "executions[1] raw output hash mismatch")
        mutate_s1("execution cwd escapes the repository",
                  lambda record: record["bindings"]["executions"][1].update(cwd="../outside"),
                  "executions[1] cwd escapes repository root")
        mutate_s1("malformed execution argv",
                  lambda record: record["bindings"]["executions"][1].update(command="verus src/lib.rs"),
                  "executions[1] command is not a nonempty argv array")
        mutate_s1("legacy command binding not derived from the first execution",
                  lambda record: record["bindings"].update(command=json.dumps(["unrelated"])),
                  "legacy command binding is not derived from executions[0]")

        # The record class is the claim's, so it cannot be the thing the waiver rule
        # and the compatibility table read: a cohort entry is where the strength is.
        mutate_s1("unverified execution beneath a stronger record class",
                  lambda record: record["bindings"]["executions"][0].update(
                      evidence_class="unverified"),
                  "assumed or unverified evidence cannot PASS without a waiver "
                  "(kani=unverified)")
        mutate_s1("externally-assumed execution beneath a stronger record class",
                  lambda record: record["bindings"]["executions"][1].update(
                      evidence_class="externally-assumed"),
                  "without a waiver (verus=externally-assumed)")
        mutate_s1("one artifact cited by two executions of the same cohort",
                  share_artifact,
                  "duplicates executions[0]: one artifact cannot discharge two executions")
        mutate_s1("cohort entry citing an artifact from another run",
                  foreign_artifact, "is not this run's producer artifact")

        # A witness-class execution says a trace exists, never that an invariant holds.
        stage(claim_manifest([system_claim()]), ("A1", "W1", "S1"),
              {"A1": [{"tool": "cargo-test", "evidence_class": "test-witnessed",
                       "marker": "test result: ok.", "command": ["cargo", "test"]}]})
        result = run_gate()
        check("Gate B: witness-only execution cannot discharge an invariant",
              result.returncode == 3
              and "executions[0] incompatible evidence class 'test-witnessed' "
                  "for obligation kind 'invariant'" in result.stdout,
              f"exit={result.returncode} {result.stdout[-300:]}")

        # The cohort-schema rules, on the claim whose cohort spans several tools:
        # a v3 record is producer-written, and its required_targets is the manifest's
        # declared set rather than whatever the record asserts.
        mutate_s1("cohort record declaring a profile the producer never writes",
                  lambda record: record["bindings"].update(profile="bounded"),
                  "not the producer profile 'producer-trusted-execution'")
        mutate_s1("required_targets omitting a declared obligation",
                  lambda record: record["bindings"].update(
                      required_targets=["A1", "W1"]),
                  "required_targets is not the obligation manifest's required set: "
                  "missing ['S1'], unexpected []")
        mutate_s1("required_targets naming an obligation no manifest declares",
                  lambda record: record["bindings"].update(
                      required_targets=["A1", "W1", "S1", "Z9"]),
                  "required_targets is not the obligation manifest's required set: "
                  "missing [], unexpected ['Z9']")

        # One PASS log cannot be spent twice: the second claim to cite it is reading
        # evidence that was earned for another obligation.
        stage(claim_manifest([system_claim()]), ("A1", "W1", "S1"))
        witness = json.loads((records / "W1.json").read_text())
        borrowed = witness["bindings"]["executions"][0]
        invariant_path = records / "A1.json"
        invariant = json.loads(invariant_path.read_text())
        invariant["bindings"]["executions"][0].update(
            raw_output_path=borrowed["raw_output_path"],
            raw_output_hash=borrowed["raw_output_hash"])
        invariant["bindings"].update(raw_output_path=borrowed["raw_output_path"],
                                     raw_output_hash=borrowed["raw_output_hash"])
        invariant_path.write_text(json.dumps(invariant, indent=2) + "\n")
        result = run_gate()
        check("Gate B: one raw artifact cannot discharge two claims",
              result.returncode == 3
              and "is also cited by claim(s) ['W1']" in result.stdout,
              f"exit={result.returncode} {result.stdout[-300:]}")

        # --require narrows the judged set; a system claim still drags in the
        # obligations it composes, or the run would report VERIFIED for parts it
        # never looked at.
        stage(claim_manifest([system_claim()]), ("S1",))
        result = run_gate("--require", "S1", "--json")
        report = json.loads(result.stdout) if result.stdout.strip().startswith("{") else {}
        check("Gate B: --require on a system claim also requires its dependencies",
              result.returncode == 3
              and report.get("required_claims") == ["A1", "S1", "W1"]
              and report.get("dependency_expansion", {}).get("S1") == ["A1", "W1"]
              and "A1: no record" in result.stdout,
              f"exit={result.returncode} {report.get('required_claims')}")
        stage(claim_manifest([system_claim()]), ("A1", "W1", "S1"))
        result = run_gate("--require", "S1")
        check("Gate B: --require on a system claim passes once its dependencies are earned",
              result.returncode == 0, f"exit={result.returncode} {result.stdout[-300:]}")

        legacy = {"version": 1,
                  "invariants": [{"id": "A1", "name": "inv_a1"}],
                  "witnesses": [{"id": "W1", "name": "witness_w1"}]}
        stage(legacy, ("A1", "W1"))
        result = run_gate("--json")
        report = json.loads(result.stdout) if result.stdout.strip().startswith("{") else {}
        check("Gate B: manifest without system_claims still verifies unchanged",
              result.returncode == 0 and report.get("required_claims") == ["A1", "W1"],
              f"exit={result.returncode} {report.get('required_claims')}")

        def rejects_manifest(label: str, payload: dict, fragment: str) -> None:
            write_manifest(project, payload)
            result = run_gate()
            check(f"Gate B rejects manifest: {label}",
                  result.returncode == 2 and fragment in result.stdout,
                  f"exit={result.returncode} {result.stdout[-200:]}")

        nested = [system_claim(depends_on=("A1", "S2")), system_claim("S2", depends_on=("W1",))]
        mutual = [system_claim(depends_on=("S2",)), system_claim("S2", depends_on=("S1",))]
        for label, payload, fragment in (
            ("id duplicated across collections",
             claim_manifest([system_claim("A1", depends_on=("W1",))]),
             "duplicate obligation id 'A1'"),
            # The producer's claim_id grammar has no ':', so such an obligation could
            # never have a record written for it: it would read missing-record forever.
            ("obligation id the evidence producer could never write a record for",
             claim_manifest([system_claim(depends_on=("W1",))],
                            invariants=[{"id": "verus:contract::Machine", "statement": "x"}]),
             "id 'verus:contract::Machine' is not usable by the evidence producer"),
            ("system claim id outside the producer's claim_id grammar",
             claim_manifest([system_claim("S1:composed")]),
             "id 'S1:composed' is not usable by the evidence producer"),
            ("system_claims is not an array",
             claim_manifest({"S1": system_claim()}), "system_claims is not an array"),
            ("invariants entry is not an object",
             claim_manifest([system_claim()], invariants=["A1"]), "invariants[0] is not an object"),
            ("system claim entry is not an object",
             claim_manifest(["S1"]), "system_claims[0] is not an object"),
            ("system claim without an id",
             claim_manifest([{"depends_on": ["A1"], "required_evidence": ["kani"]}]),
             "has malformed id None"),
            ("blank system claim id",
             claim_manifest([system_claim("  ")]), "has malformed id '  '"),
            ("missing depends_on",
             claim_manifest([system_claim(depends_on=None)]),
             "depends_on is not a nonempty array"),
            ("empty depends_on",
             claim_manifest([system_claim(depends_on=[])]),
             "depends_on is not a nonempty array"),
            ("depends_on is a bare string",
             claim_manifest([system_claim(depends_on="A1")]),
             "depends_on is not a nonempty array"),
            ("duplicate dependency",
             claim_manifest([system_claim(depends_on=("A1", "A1"))]),
             "depends_on repeats 'A1'"),
            ("unknown dependency",
             claim_manifest([system_claim(depends_on=("A1", "Z9"))]),
             "depends on undeclared obligation 'Z9'"),
            ("dependency on another system claim", claim_manifest(nested),
             "depends_on names invariants and witnesses only"),
            ("mutually dependent system claims", claim_manifest(mutual),
             "depends_on names invariants and witnesses only"),
            ("self-dependent system claim",
             claim_manifest([system_claim(depends_on=("S1",))]),
             "depends_on names invariants and witnesses only"),
            ("empty required_evidence",
             claim_manifest([system_claim(required_evidence=[])]),
             "required_evidence is not a nonempty array"),
            ("duplicate required_evidence",
             claim_manifest([system_claim(required_evidence=("kani", "kani"))]),
             "required_evidence repeats 'kani'"),
            ("malformed evidence id",
             claim_manifest([system_claim(required_evidence=("cargo kani",))]),
             "required_evidence[0] is malformed: 'cargo kani'"),
            ("non-string evidence id",
             claim_manifest([system_claim(required_evidence=[7])]),
             "required_evidence[0] is malformed: 7"),
        ):
            rejects_manifest(label, payload, fragment)


def project_binding_checks() -> None:
    with tempfile.TemporaryDirectory(prefix="r6-project-") as td:
        root = Path(td).resolve()
        project = build_project(root)
        resolver_checks(root, project)
        gate_checks(project, snapshot_checks(project))


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="r6-") as td:
        tmp = Path(td)
        target = tmp / "intent.md"
        target.write_text("# intent\n")

        r = crun("init", str(target), "--voices=", "--owners=")
        check("init: empty --voices rejected",
              r.returncode != 0 and "zero-voice" in (r.stdout + r.stderr))

        r = crun("init", str(target), "--voices=a,a", "--owners=a:omp")
        check("init: duplicate voice ids rejected",
              r.returncode != 0 and "duplicate" in (r.stdout + r.stderr))

        # Hand-built zero-voice manifest: every reader must refuse it.
        zero_dir = tmp / "zero"
        zero_dir.mkdir()
        (zero_dir / "run.json").write_text(json.dumps(
            {"run_id": "z", "target": str(target), "created": "t", "voices": [],
             "synthesis": {"file": "synthesis.md", "harness": "x", "status": "pending"}}))
        for sub in (["status", str(zero_dir)],
                    ["wait", str(zero_dir), "--timeout=3"],
                    ["synthesize", str(zero_dir)]):
            r = crun(*sub)
            check(f"zero-voice manifest refused by `{sub[0]}`",
                  r.returncode != 0 and "zero voices" in (r.stdout + r.stderr),
                  f"exit={r.returncode}")

        # Real run: two voices.
        run_dir = tmp / "run"
        r = crun("init", str(target), "--voices=v1,v2",
                 "--owners=v1:omp,v2:omp", f"--run-dir={run_dir}")
        check("init: two-voice run created", r.returncode == 0, r.stderr[-200:])

        # All-errored wait -> nonzero (zero evidence).
        crun("error", str(run_dir), "--voice=v1", "--detail=HTTP 500", "--elapsed=1")
        crun("error", str(run_dir), "--voice=v2", "--detail=timeout", "--elapsed=2")
        r = crun("wait", str(run_dir), "--timeout=3")
        check("wait: all-errored run exits nonzero with INCOMPLETE",
              r.returncode == 2 and "INCOMPLETE" in (r.stdout + r.stderr),
              f"exit={r.returncode}")

        # Zero completed voices: synthesize refuses even with override.
        r = crun("synthesize", str(run_dir), "--allow-partial")
        check("synthesize: zero completed voices refused even with --allow-partial",
              r.returncode != 0 and "zero completed" in (r.stdout + r.stderr))

        # Reset v1, complete it; history must retain the errored attempt.
        crun("reset", str(run_dir), "--voice=v1")
        manifest = json.loads((run_dir / "run.json").read_text())
        v1 = next(v for v in manifest["voices"] if v["id"] == "v1")
        check("reset: prior errored attempt retained in history",
              len(v1.get("history", [])) == 1
              and v1["history"][0]["status"] == "error"
              and v1["history"][0]["error_detail"] == "HTTP 500")

        (run_dir / v1["file"]).write_text("## Attacks\n\nVERDICT: BREAKS\n")
        crun("complete", str(run_dir), "--voice=v1", "--elapsed=3",
             "--finish-reason=stop")

        # One complete + one errored: refused without override, labeled with.
        r = crun("synthesize", str(run_dir))
        check("synthesize: errored voice refused without --allow-partial",
              r.returncode != 0 and "--allow-partial" in (r.stdout + r.stderr))
        r = crun("synthesize", str(run_dir), "--allow-partial")
        synth = (run_dir / "synthesis-input.md").read_text() \
            if (run_dir / "synthesis-input.md").exists() else ""
        check("synthesize: --allow-partial produces PARTIAL-labeled output",
              r.returncode == 0 and "PARTIAL SYNTHESIS INPUT" in synth
              and "coverage gap" in synth,
              f"exit={r.returncode}")

        # Mixed-terminal wait: one complete + one errored is exit 0 (evidence exists).
        r = crun("wait", str(run_dir), "--timeout=3")
        check("wait: terminal run with at least one completion exits 0",
              r.returncode == 0, f"exit={r.returncode}")

    project_binding_checks()
    system_claim_checks()

    print()
    if FAILURES:
        print(f"R6: {len(FAILURES)} failure(s)")
        return 1
    print("R6: all assertions passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
