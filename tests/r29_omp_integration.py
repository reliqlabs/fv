#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6,<7"]
# ///
"""R29: static OMP extension package and single-harness initializer."""
from __future__ import annotations

import json
import os
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
        config_text = (project / ".omp" / "config.yml").read_text()
        check("initializer preserves comments and YAML 1.2-like enum scalars",
              "# preserve this comment" in config_text and "codeMode: on" in config_text,
              config_text)
        dispatch = json.loads((project / ".fv" / "dispatch.json").read_text())
        check("dispatch top level is omp_native only", set(dispatch) == {"omp_native"})
        route = dispatch["omp_native"]
        check("dispatch project root filled", route["project_root"] == str(project.resolve()))
        check("dispatch target spec filled", route["target_spec"] == str(target.resolve()))
        check("no project agent copies", not (project / ".omp" / "agents").exists())
        check("no project skill copies", not (project / ".omp" / "skills").exists())
        check("no project tool copies", not (project / ".omp" / "tools").exists())
        check("no project MCP copy", not (project / ".omp" / "mcp.json").exists())

        registry = json.loads((REPO / "registry" / "voices.json").read_text())
        canonical = next(profile for profile in registry["profiles"] if profile["name"] == "canonical-4")
        voices = {voice["id"]: voice for voice in registry["voices"]}
        catalog = {"models": [
            {"selector": voices[seat["id"]]["omp_model"],
             "thinking": voices[seat["id"]].get("omp_thinking_ladder")}
            for seat in canonical["voices"]
        ]}
        contract = {
            "version": 1, "restrictTools": True, "perCallModel": True,
            "perCallTimeout": True, "servedModel": True, "servedFamily": True,
            "panelLineupFreeze": True,
        }
        omp_stub = Path(temporary) / "omp-stub"
        omp_stub.write_text(
            "#!/usr/bin/env python3\nimport os, sys\n"
            # From the BOM, so a deliberate pin bump cannot leave this fixture
            # asserting compatibility against a version the repo no longer pins.
            f"version = {repr('omp/' + json.loads((REPO / 'bom.json').read_text())['tools']['omp'])}\n"
            f"contract = {repr(json.dumps(contract))}\n"
            f"catalog = {repr(json.dumps(catalog))}\n"
            f"expected_cwd = {repr(str(project.resolve()))}\n"
            "catalog_out = catalog if os.getcwd() == expected_cwd else '{\"models\": []}'\n"
            "print(version if '--version' in sys.argv else "
            "contract if '--agent-bridge-contract' in sys.argv else catalog_out)\n"
        )
        omp_stub.chmod(0o755)
        doctor = REPO / "scripts" / "fv_doctor.py"
        checked = subprocess.run(
            ["uv", "run", "--script", str(doctor), "--project", str(project),
             "--omp", str(omp_stub), "--json"],
            env={**os.environ, "FV_ROOT": str(REPO)},
            capture_output=True, text=True,
        )
        check("doctor accepts an explicit compatible OMP executable",
              checked.returncode == 0 and json.loads(checked.stdout)["status"] == "PASS",
              checked.stdout + checked.stderr)
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
