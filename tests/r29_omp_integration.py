#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6,<7"]
# ///
"""R29: static OMP extension package and single-harness initializer."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
FAILURES: list[str] = []
AGENTS = {
    "fv-panelist",
    "fv-panel-synthesizer",
    "fv-spec-adversary",
    "fv-code-adversary",
    "fv-failure-classifier",
    "fv-quint-spec-generator",
}
RESTRICTED = AGENTS - {"fv-quint-spec-generator"}


def check(label: str, condition: bool, detail: object = "") -> None:
    if condition:
        print(f"  [ok]   {label}")
    else:
        print(f"  [FAIL] {label}" + (f" ({detail})" if detail else ""))
        FAILURES.append(label)


def frontmatter(path: Path) -> dict:
    text = path.read_text()
    _, block, _ = text.split("---", 2)
    return yaml.safe_load(block)


def main() -> int:
    files = sorted((REPO / "agents").glob("*.md"))
    check("six static package agents", {path.stem for path in files} == AGENTS)
    check("no generated body sources", not list((REPO / "agents").glob("*-body.md")))
    for path in files:
        data = frontmatter(path)
        name = path.stem
        check(f"{name}: frontmatter name matches", data.get("name") == name)
        if name in RESTRICTED:
            check(f"{name}: hard restriction enabled", data.get("restrictTools") is True)
            check(f"{name}: read-only tools", data.get("tools") == ["read", "grep", "glob"])
        else:
            check(f"{name}: generator remains unrestricted", "restrictTools" not in data)
            check(
                f"{name}: generator authoring tools",
                data.get("tools") == ["read", "grep", "glob", "bash", "write", "edit"],
            )

    check("package panel resolver exists", (REPO / "tools" / "panel-resolver.ts").is_file())
    check("package MCP manifest exists", (REPO / ".mcp.json").is_file())
    mcp_manifest = json.loads((REPO / ".mcp.json").read_text())
    check(
        "MCP executables are extension-relative and independent of FV_ROOT inheritance",
        all(
            isinstance(server.get("command"), str)
            and server["command"].startswith("./mcp/")
            and "${FV_ROOT}" not in server["command"]
            for server in mcp_manifest.get("mcpServers", {}).values()
        ),
        mcp_manifest,
    )
    help_run = subprocess.run(
        ["uv", "run", "--script", str(REPO / "scripts" / "fv_init.py"), "--help"],
        capture_output=True,
        text=True,
    )
    check("initializer help succeeds", help_run.returncode == 0)
    check("initializer exposes no harness selector", "--harness" not in help_run.stdout)

    with tempfile.TemporaryDirectory(prefix="fv-r29-") as temporary:
        project = Path(temporary) / "project"
        (project / ".omp").mkdir(parents=True)
        existing_extension = str(REPO) + "-backup"
        (project / ".omp" / "config.yml").write_text(
            f"# preserve this comment\n# package path appears here too: {REPO}\n"
            f"extensions:\n    - {json.dumps(existing_extension)}\n"
            "model: example/model\nproviders:\n  openai-codex:\n    codeMode: on\n"
        )
        target = project / "intent.md"
        target.write_text("# Intent\n")
        command = [
            "uv",
            "run",
            "--script",
            str(REPO / "scripts" / "fv_init.py"),
            str(project),
            "--target-spec",
            str(target),
        ]
        first = subprocess.run(command, capture_output=True, text=True)
        second = subprocess.run(command, capture_output=True, text=True)
        check("initializer first run succeeds", first.returncode == 0, first.stderr)
        check("initializer rerun succeeds", second.returncode == 0, second.stderr)
        check("initializer tells existing sessions to reload the full extension snapshot",
              "/reload-plugins" in first.stdout and "/mcp reload" not in first.stdout,
              first.stdout)

        config = yaml.safe_load((project / ".omp" / "config.yml").read_text())
        extension_values = config["extensions"]
        check("existing extension preserved", existing_extension in extension_values)
        check("package extension added once by exact value", extension_values.count(str(REPO)) == 1)
        check("unrelated config preserved", config.get("model") == "example/model")
        check("initializer enables isolated subagents",
              config.get("task", {}).get("isolation", {}).get("mode") == "auto", config)
        panel_seed = json.loads((REPO / "templates" / "omp-panel.json").read_text())
        check("initializer installs fv-canonical in OMP panel settings",
              config.get("panel", {}).get("roles", {}).get("fv-canonical")
              == panel_seed["roles"]["fv-canonical"], config.get("panel"))
        check("initializer writes no FV-owned panel profile",
              not (project / ".fv" / "panel-profiles.json").exists())
        config_text = (project / ".omp" / "config.yml").read_text()
        check("initializer preserves comments and YAML 1.2-like enum scalars",
              "# preserve this comment" in config_text and "codeMode: on" in config_text,
              config_text)
        dispatch = json.loads((project / ".fv" / "dispatch.json").read_text())
        check("dispatch top level is omp_native only", set(dispatch) == {"omp_native"})
        route = dispatch["omp_native"]
        check("dispatch project root is portable", route["project_root"] == ".")
        check("dispatch target spec is repo-relative", route["target_spec"] == "intent.md")
        check("no project agent copies", not (project / ".omp" / "agents").exists())
        check("no project skill copies", not (project / ".omp" / "skills").exists())
        check("no project tool copies", not (project / ".omp" / "tools").exists())
        check("no project MCP copy", not (project / ".omp" / "mcp.json").exists())

        verified_inputs = project / ".fv" / "verified-inputs.txt"
        frozen = (".fv/evidence/", ".fv/verify/", ".fv/panels/", ".colosseum/")
        seeded = verified_inputs.read_text()
        check("initializer seeds frozen verified-input exclusions",
              all(f"{prefix}\n" in seeded for prefix in frozen), seeded)
        verified_inputs.write_text(seeded + "build/\n")
        kept = subprocess.run(command, capture_output=True, text=True)
        check("initializer preserves project verified-input entries",
              kept.returncode == 0 and "build/\n" in verified_inputs.read_text(),
              verified_inputs.read_text())
        verified_inputs.write_text("build/\n")
        restored = subprocess.run(command, capture_output=True, text=True)
        restored_text = verified_inputs.read_text()
        check("initializer restores frozen exclusions dropped from the list",
              restored.returncode == 0 and "build/\n" in restored_text
              and all(f"{prefix}\n" in restored_text for prefix in frozen),
              restored_text)

        # Older scaffolds stored absolute inside-project paths. A rerun without
        # --target-spec must migrate them instead of resetting the declaration.
        default_command = command[:5]
        legacy_route = dict(route)
        legacy_route["project_root"] = str(project.resolve())
        legacy_route["target_spec"] = str(target.resolve())
        (project / ".fv" / "dispatch.json").write_text(
            json.dumps({"omp_native": legacy_route}, indent=2) + "\n")
        migrated_run = subprocess.run(default_command, capture_output=True, text=True)
        migrated = json.loads((project / ".fv" / "dispatch.json").read_text())["omp_native"]
        check("initializer migrates legacy inside-project absolute paths",
              migrated_run.returncode == 0 and migrated["project_root"] == "."
              and migrated["target_spec"] == "intent.md",
              migrated_run.stdout + json.dumps(migrated))
        outside_target = Path(temporary) / "outside-intent.md"
        outside_target.write_text("# Intent\n")
        escaping = subprocess.run(
            [*default_command, "--target-spec", str(outside_target)],
            capture_output=True, text=True)
        check("initializer rejects a target outside the project",
              escaping.returncode == 1
              and json.loads((project / ".fv" / "dispatch.json").read_text())
                  ["omp_native"]["target_spec"] == "intent.md",
              escaping.stdout + escaping.stderr)

        registry = json.loads((REPO / "registry" / "voices.json").read_text())
        canonical = next(profile for profile in registry["profiles"] if profile["name"] == "canonical-4")
        voices = {voice["id"]: voice for voice in registry["voices"]}
        # Exercise the same candidate fallback Gula uses: the canonical
        # synthetic GLM route is absent, while the profile's second candidate
        # is available with its provider-specific ladder.
        catalog = {"models": [
            {"selector": voices[seat["id"]]["omp_model"],
             "thinking": voices[seat["id"]].get("omp_thinking_ladder")}
            for seat in canonical["voices"] if seat["id"] != "glm-5.2"
        ]}
        catalog["models"].append({
            "selector": "fireworks/glm-5.2",
            "thinking": ["low", "high", "max"],
        })
        bom = json.loads((REPO / "bom.json").read_text())
        required_contract = bom["omp_contract"]
        contract = {
            "version": required_contract["version"],
            **required_contract["required"],
            # Additive OMP capabilities must not break FV compatibility.
            "futureCapability": True,
        }

        def write_omp_stub(path: Path, payload: object, version: str = "omp/99.0.0",
                           cwd: Path | None = None) -> Path:
            path.write_text("\n".join([
                "#!/usr/bin/env python3",
                "import os, sys",
                f"version = {version!r}",
                f"contract = {json.dumps(payload)!r}",
                f"catalog = {json.dumps(catalog)!r}",
                f"panel = {json.dumps(panel_seed)!r}",
                f"expected_cwd = {str((cwd or project).resolve())!r}",
                "catalog_out = catalog if os.getcwd() == expected_cwd else '{\"models\": []}'",
                "print(version if '--version' in sys.argv else "
                "contract if '--agent-bridge-contract' in sys.argv else "
                "panel if 'config' in sys.argv and 'panel' in sys.argv else catalog_out)",
            ]) + "\n")
            path.chmod(0o755)
            return path

        doctor = REPO / "scripts" / "fv_doctor.py"
        omp_stub = write_omp_stub(Path(temporary) / "omp-stub", contract)
        checked = subprocess.run(
            ["uv", "run", "--script", str(doctor), "--project", str(project),
             "--omp", str(omp_stub), "--json"],
            env={**os.environ, "FV_ROOT": str(REPO)},
            capture_output=True, text=True,
        )
        checked_report = json.loads(checked.stdout)
        check("doctor accepts a different OMP version with the required capability subset",
              checked.returncode == 0 and checked_report["status"] == "PASS"
              and any(item["name"] == "omp" and item["detail"] == "omp/99.0.0"
                      for item in checked_report["findings"]),
              checked.stdout + checked.stderr)
        check("doctor accepts additive bridge capabilities",
              any(item["name"] == "omp-agent-bridge-contract" and item["status"] == "ok"
                  for item in checked_report["findings"]), checked.stdout)
        check("doctor accepts the first available canonical panel candidate",
              any(item["name"] == "omp-model-contract" and item["status"] == "ok"
                      and "member-3->fireworks/glm-5.2" in item["detail"]
                      for item in checked_report["findings"]), checked.stdout)
        check("doctor resolves the canonical target through the shared helper",
              any(item["name"] == "target-spec" and item["status"] == "ok"
                  and item["detail"].endswith("intent.md")
                  for item in checked_report["findings"])
              and any(item["name"] == "portable-state" and item["status"] == "ok"
                      for item in checked_report["findings"]), checked.stdout)
        check("doctor requires the project copy of the resolver",
              any(item["name"] == "fv_project.py" and item["status"] == "ok"
                  for item in checked_report["findings"]), checked.stdout)

        missing_capability = dict(contract)
        missing_capability.pop("perCallTimeout")
        bad_capability_stub = write_omp_stub(
            Path(temporary) / "omp-missing-capability", missing_capability)
        bad_capability = subprocess.run(
            ["uv", "run", "--script", str(doctor), "--project", str(project),
             "--omp", str(bad_capability_stub), "--json"],
            env={**os.environ, "FV_ROOT": str(REPO)}, capture_output=True, text=True,
        )
        bad_capability_report = json.loads(bad_capability.stdout)
        check("doctor fails when a required OMP capability is missing",
              bad_capability.returncode == 1
              and any(item["name"] == "omp-agent-bridge-contract" and item["status"] == "fail"
                      and "perCallTimeout" in item["detail"]
                      for item in bad_capability_report["findings"]), bad_capability.stdout)

        false_capability = dict(contract)
        false_capability["perCallTimeout"] = False
        false_capability_stub = write_omp_stub(
            Path(temporary) / "omp-false-capability", false_capability)
        false_capability_run = subprocess.run(
            ["uv", "run", "--script", str(doctor), "--project", str(project),
             "--omp", str(false_capability_stub), "--json"],
            env={**os.environ, "FV_ROOT": str(REPO)}, capture_output=True, text=True,
        )
        false_capability_report = json.loads(false_capability_run.stdout)
        check("doctor fails when a required OMP capability is false",
              false_capability_run.returncode == 1
              and any(item["name"] == "omp-agent-bridge-contract" and item["status"] == "fail"
                      and "perCallTimeout=False" in item["detail"]
                      for item in false_capability_report["findings"]),
              false_capability_run.stdout)

        wrong_version_contract = dict(contract)
        wrong_version_contract["version"] = required_contract["version"] + 1
        wrong_contract_stub = write_omp_stub(
            Path(temporary) / "omp-wrong-contract-version", wrong_version_contract)
        wrong_contract = subprocess.run(
            ["uv", "run", "--script", str(doctor), "--project", str(project),
             "--omp", str(wrong_contract_stub), "--json"],
            env={**os.environ, "FV_ROOT": str(REPO)}, capture_output=True, text=True,
        )
        wrong_contract_report = json.loads(wrong_contract.stdout)
        check("doctor fails on an incompatible OMP bridge-contract version",
              wrong_contract.returncode == 1
              and any(item["name"] == "omp-agent-bridge-contract" and item["status"] == "fail"
                      and "contract version" in item["detail"]
                      for item in wrong_contract_report["findings"]), wrong_contract.stdout)
        missing_omp = subprocess.run(
            ["uv", "run", "--script", str(doctor), "--project", str(project),
             "--omp", str(Path(temporary) / "missing-omp"), "--json"],
            env={**os.environ, "FV_ROOT": str(REPO)},
            capture_output=True, text=True,
        )
        check("doctor fails when the selected OMP executable is missing",
              missing_omp.returncode == 1
              and any(item["name"] == "omp" and item["status"] == "fail"
                      for item in json.loads(missing_omp.stdout)["findings"]),
              missing_omp.stdout + missing_omp.stderr)
        wrong_root = subprocess.run(
            ["uv", "run", "--script", str(doctor), "--project", str(project),
             "--omp", str(omp_stub), "--json"],
            capture_output=True, text=True,
            env={**os.environ, "FV_ROOT": str(Path(temporary) / "wrong-root")},
        )
        check("doctor rejects FV_ROOT pointing at another checkout",
              wrong_root.returncode == 1
              and any(item["name"] == "FV_ROOT-paths" and item["status"] == "fail"
                      for item in json.loads(wrong_root.stdout)["findings"]),
              wrong_root.stdout + wrong_root.stderr)
        config_path = project / ".omp" / "config.yml"
        config_path.write_text(config_path.read_text().replace("mode: auto", "mode: rcopy"))
        preserved_mode = subprocess.run(command, capture_output=True, text=True)
        preserved_config = yaml.safe_load(config_path.read_text())
        check("initializer preserves an explicit valid isolation backend",
              preserved_mode.returncode == 0
              and preserved_config["task"]["isolation"]["mode"] == "rcopy",
              config_path.read_text())
        customized = config_path.read_text().replace(
            "model: openai-codex/gpt-5.6-sol", "model: custom/provider-model", 1)
        config_path.write_text(customized)
        customized_run = subprocess.run(command, capture_output=True, text=True)
        check("initializer accepts a structurally valid customized OMP panel role",
              customized_run.returncode == 0 and config_path.read_text() == customized,
              customized_run.stdout + customized_run.stderr)

        # Clone portability: relocated state must resolve without a rewrite,
        # and a rerun at the new path must leave OMP's own config alone.
        moved = Path(temporary) / "moved-project"
        dispatch_before = (project / ".fv" / "dispatch.json").read_text()
        shutil.move(str(project), str(moved))
        moved_init = subprocess.run(
            ["uv", "run", "--script", str(REPO / "scripts" / "fv_init.py"), str(moved)],
            capture_output=True, text=True)
        check("initializer rerun after a move keeps dispatch byte-identical",
              moved_init.returncode == 0
              and (moved / ".fv" / "dispatch.json").read_text() == dispatch_before,
              moved_init.stdout + moved_init.stderr)
        check("moved project preserves the customized OMP panel config",
              (moved / ".omp" / "config.yml").read_text() == customized,
              (moved / ".omp" / "config.yml").read_text())
        moved_stub = write_omp_stub(Path(temporary) / "omp-moved", contract, cwd=moved)
        moved_doctor = subprocess.run(
            ["uv", "run", "--script", str(doctor), "--project", str(moved),
             "--omp", str(moved_stub), "--json"],
            env={**os.environ, "FV_ROOT": str(REPO)}, capture_output=True, text=True)
        moved_report = json.loads(moved_doctor.stdout)
        check("doctor passes against the relocated project",
              moved_doctor.returncode == 0 and moved_report["status"] == "PASS",
              moved_doctor.stdout + moved_doctor.stderr)
        check("relocated project resolves its canonical target",
              any(item["name"] == "target-spec" and item["status"] == "ok"
                  and item["detail"].endswith("intent.md")
                  for item in moved_report["findings"]), moved_doctor.stdout)
        shutil.move(str(moved), str(project))
        config_path.write_text(config_path.read_text().replace("mode: rcopy", "mode: bogus"))
        invalid_mode = subprocess.run(command, capture_output=True, text=True)
        check("initializer rejects an invalid isolation backend",
              invalid_mode.returncode == 1 and "unsupported task.isolation.mode" in invalid_mode.stdout,
              invalid_mode.stdout + invalid_mode.stderr)
        inline_config = (
            f"extensions:\n  - {json.dumps(str(REPO))}\n"
            "task: { isolation: { mode: none } }\n"
        )
        config_path.write_text(inline_config)
        inline_mode = subprocess.run(command, capture_output=True, text=True)
        check("initializer rejects inline isolation syntax without mutating it",
              inline_mode.returncode == 1
              and "unsupported inline task syntax" in inline_mode.stdout
              and config_path.read_text() == inline_config,
              inline_mode.stdout + inline_mode.stderr)

    quickstart = (REPO / "QUICKSTART.md").read_text()
    for skill in sorted(path.parent.name for path in (REPO / "skills").glob("*/SKILL.md")):
        check(f"quickstart uses skill namespace for {skill}", f"/skill:{skill}" in quickstart or skill in {"fv-boundary", "fv-lifecycle-adversary"})

    print()
    if FAILURES:
        print(f"R29: {len(FAILURES)} failure(s)")
        return 1
    print("R29: all assertions passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
