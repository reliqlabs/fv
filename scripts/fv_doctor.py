#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6,<7"]
# ///
"""Fail-closed OMP extension and project-state doctor."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
import yaml

REPO = Path(__file__).resolve().parents[1]
EXPECTED_AGENTS = {
    "fv-panelist",
    "fv-panel-synthesizer",
    "fv-spec-adversary",
    "fv-code-adversary",
    "fv-failure-classifier",
    "fv-quint-spec-generator",
}
EXPECTED_SKILLS = {
    "fv-adversarial",
    "fv-boundary",
    "fv-change",
    "fv-code-adversarial",
    "fv-compose",
    "fv-intent",
    "fv-lifecycle-adversary",
    "fv-panel",
    "fv-reverse-intent",
    "fv-verify",
}
EXPECTED_MCP = {"kani", "quint", "verus", "aeneas", "goedel", "lm-studio"}
ISOLATION_MODES = {
    "auto", "apfs", "btrfs", "zfs", "reflink",
    "overlayfs", "projfs", "block-clone", "rcopy",
}



@dataclass
class Finding:
    category: str
    name: str
    status: str
    detail: str


class Report:
    def __init__(self) -> None:
        self.findings: list[Finding] = []

    def add(self, category: str, name: str, status: str, detail: str) -> None:
        self.findings.append(Finding(category, name, status, detail))

    @property
    def failed(self) -> bool:
        return any(finding.status == "fail" for finding in self.findings)

    @property
    def warned(self) -> bool:
        return any(finding.status == "warn" for finding in self.findings)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_package(report: Report) -> None:
    for directory in ("agents", "skills", "tools"):
        path = REPO / directory
        report.add("package", directory, "ok" if path.is_dir() else "fail", str(path))
    agents = {path.stem for path in (REPO / "agents").glob("*.md")}
    missing_agents = sorted(EXPECTED_AGENTS - agents)
    report.add(
        "package",
        "agents",
        "fail" if missing_agents else "ok",
        f"missing={missing_agents}" if missing_agents else "all static agents resolvable",
    )
    skills = {path.parent.name for path in (REPO / "skills").glob("*/SKILL.md")}
    missing_skills = sorted(EXPECTED_SKILLS - skills)
    report.add(
        "package",
        "skills",
        "fail" if missing_skills else "ok",
        f"missing={missing_skills}" if missing_skills else "all skills resolvable",
    )
    required_tools = {"panel-resolver.ts", "evidence-run.ts"}
    found_tools = {path.name for path in (REPO / "tools").glob("*.ts")}
    missing_tools = sorted(required_tools - found_tools)
    report.add(
        "package",
        "custom-tools",
        "fail" if missing_tools else "ok",
        f"missing={missing_tools}" if missing_tools else "panel resolver and evidence runner present",
    )
    if not missing_tools and shutil.which("bun"):
        paths = [str(REPO / "tools" / name) for name in sorted(required_tools)]
        script = (
            "const stub={}; for(const k of ['optional','array','enum','record','object','string','number','boolean']) stub[k]=()=>stub; "
            "stub.parse=x=>x; const zod=new Proxy(stub,{get:(t,k)=>k in t?t[k]:()=>stub}); "
            f"for(const p of {json.dumps(paths)}){{const m=await import(p); const tool=await m.default({{cwd:{json.dumps(str(REPO))},zod}}); "
            "if(!tool||typeof tool.execute!=='function'||!tool.name) throw new Error('invalid custom tool '+p);}"
        )
        loaded = subprocess.run(["bun", "-e", script], capture_output=True, text=True)
        report.add("package", "custom-tool-load", "ok" if loaded.returncode == 0 else "fail",
                   "factories load" if loaded.returncode == 0 else (loaded.stderr or loaded.stdout).strip())
    elif not missing_tools:
        report.add("package", "custom-tool-load", "fail",
                   "bun unavailable; cannot validate custom tool factories")
    validator = subprocess.run(
        ["uv", "run", "--script", str(REPO / "scripts" / "validate_frontmatter.py")],
        capture_output=True,
        text=True,
    )
    report.add(
        "package",
        "frontmatter",
        "ok" if validator.returncode == 0 else "fail",
        (validator.stdout + validator.stderr).strip().splitlines()[-1]
        if (validator.stdout + validator.stderr).strip() else "no output",
    )
    try:
        registry = json.loads((REPO / "registry" / "voices.json").read_text())
        generator = load_module("doctor_roster", REPO / "scripts" / "gen_roster_docs.py")
        expected_route = generator.render_omp_native_config(registry)
        generated_route = json.loads(
            (REPO / "scripts" / "dispatch.config.example.json").read_text()
        )["omp_native"]
        generated_route = {
            key: value for key, value in generated_route.items()
            if key not in {"project_root", "target_spec"}
        }
        panel_profiles = json.loads((REPO / "templates" / "omp-panel.json").read_text())["profiles"]
        expected_voices = {voice["model"]: voice for voice in expected_route["voices"]}
        profile_errors = []
        for profile_name, profile in panel_profiles.items():
            for seat in [*profile["seats"], profile["synthesizer"]]:
                candidates = seat.get("candidates")
                expected = expected_voices.get(candidates[0]) if candidates else None
                if expected is None:
                    profile_errors.append(f"{profile_name}/{seat['seat_id']}: unknown primary candidate")
                    continue
                if seat.get("thinking_level") != expected.get("thinking_level"):
                    profile_errors.append(f"{profile_name}/{seat['seat_id']}: thinking level drift")
                if not seat.get("candidates") or seat["candidates"][0] != expected["model"]:
                    profile_errors.append(f"{profile_name}/{seat['seat_id']}: primary candidate drift")
        route_current = generated_route == expected_route and not profile_errors
        report.add(
            "package", "registry-routes", "ok" if route_current else "fail",
            "full generated OMP routes and panel profiles current"
            if route_current else "; ".join(profile_errors) or "generated OMP route drift",
        )
    except (OSError, KeyError, ValueError, json.JSONDecodeError, SystemExit) as error:
        report.add("package", "registry-routes", "fail", str(error))


def check_mcp(report: Report) -> None:
    path = REPO / ".mcp.json"
    try:
        config = json.loads(path.read_text())
        servers = config.get("mcpServers")
    except (OSError, json.JSONDecodeError) as error:
        report.add("mcp", "manifest", "fail", str(error))
        return
    if not isinstance(servers, dict):
        report.add("mcp", "manifest", "fail", "mcpServers is not an object")
        return
    missing = sorted(EXPECTED_MCP - set(servers))
    report.add("mcp", "manifest", "fail" if missing else "ok", f"missing={missing}" if missing else "six package servers configured")
    fv_root = os.environ.get("FV_ROOT")
    root_ok = bool(fv_root) and Path(fv_root).expanduser().resolve() == REPO.resolve()
    report.add(
        "mcp", "FV_ROOT-paths", "ok" if root_ok else "fail",
        "FV_ROOT resolves to this package" if root_ok else "FV_ROOT does not resolve to this package",
    )
    bad_paths = []
    for name, server in servers.items():
        command = server.get("command") if isinstance(server, dict) else None
        if not isinstance(command, str) or not command.startswith("./"):
            bad_paths.append(name)
            continue
        resolved = (REPO / command).resolve()
        try:
            resolved.relative_to(REPO.resolve())
        except ValueError:
            bad_paths.append(name)
            continue
        if not resolved.is_file() or not os.access(resolved, os.X_OK):
            bad_paths.append(name)
    report.add(
        "mcp", "extension-relative-paths", "fail" if bad_paths else "ok",
        f"invalid extension-relative commands={bad_paths}" if bad_paths
        else "all commands resolve inside the extension root and are executable",
    )


def configured_extension(config_path: Path) -> bool:
    try:
        config = yaml.safe_load(config_path.read_text())
    except (OSError, yaml.YAMLError):
        return False
    if not isinstance(config, dict) or not isinstance(config.get("extensions"), list):
        return False
    expected = REPO.resolve()
    return any(isinstance(item, str) and Path(item).expanduser().resolve() == expected
               for item in config["extensions"])

def configured_isolation(config_path: Path) -> bool:
    try:
        config = yaml.safe_load(config_path.read_text())
    except (OSError, yaml.YAMLError):
        return False
    if not isinstance(config, dict) or not isinstance(config.get("task"), dict):
        return False
    isolation = config["task"].get("isolation")
    return (
        isinstance(isolation, dict)
        and isolation.get("mode") in ISOLATION_MODES
    )
def check_project(report: Report, project: Path) -> None:
    state = project / ".fv"
    if not state.is_dir():
        report.add("project", "state", "fail", f"missing {state}")
        return
    config = project / ".omp" / "config.yml"
    report.add(
        "project",
        "extensions-entry",
        "ok" if configured_extension(config) else "fail",
        f"{config} must list {REPO}",
    )
    report.add(
        "project",
        "subagent-isolation",
        "ok" if configured_isolation(config) else "fail",
        f"{config} must set task.isolation.mode to a non-none mode",
    )
    marker = state / "harness"
    report.add(
        "project",
        "harness",
        "ok" if marker.is_file() and marker.read_text().strip() == "omp" else "fail",
        "expected .fv/harness = omp",
    )

    dispatch_path = state / "dispatch.json"
    try:
        dispatch = json.loads(dispatch_path.read_text())
        checker = load_module("check_dispatch_config", REPO / "scripts" / "check_dispatch_config.py")
        errors = checker.validate(dispatch, require_paths=False, base=project)
    except (OSError, json.JSONDecodeError, RuntimeError) as error:
        errors = [str(error)]
    report.add(
        "project",
        "dispatch",
        "fail" if errors else "ok",
        "; ".join(errors) if errors else "omp_native block valid",
    )

    project_profile = state / "panel-profiles.json"
    template_profile = REPO / "templates" / "omp-panel.json"
    try:
        profile = json.loads(project_profile.read_text())
        registry = json.loads((REPO / "registry" / "voices.json").read_text())
        canonical = next(item for item in registry["profiles"] if item["name"] == "canonical-4")
        generator = load_module("gen_roster_docs", REPO / "scripts" / "gen_roster_docs.py")
        computed_hash = generator.profile_content_hash(canonical)
        expected_pin = f"canonical-4@{computed_hash}"
        profile_errors = []
        if canonical.get("content_hash") != computed_hash:
            profile_errors.append(
                f"registry content_hash={canonical.get('content_hash')!r}, recomputed {computed_hash!r}"
            )
        if profile.get("registry_profile") != expected_pin:
            profile_errors.append(
                f"registry_profile={profile.get('registry_profile')!r}, expected {expected_pin!r}"
            )
        if sha256(project_profile) != sha256(template_profile):
            profile_errors.append("project panel profile differs from package template")
    except (OSError, json.JSONDecodeError, StopIteration) as error:
        profile_errors = [str(error)]
    report.add(
        "project",
        "panel-profile",
        "fail" if profile_errors else "ok",
        "; ".join(profile_errors) if profile_errors else "profile and registry hash aligned",
    )

    for name in ("check_evidence_records.py", "check_ledger_references.py"):
        installed = state / "scripts" / name
        canonical = REPO / "scripts" / name
        current = installed.is_file() and sha256(installed) == sha256(canonical)
        report.add(
            "project",
            name,
            "ok" if current else "fail",
            "project gate current" if current else "missing or stale project gate copy",
        )


def check_toolchain(report: Report, project: Path, omp_command: str = "omp") -> None:
    bom = json.loads((REPO / "bom.json").read_text())
    omp_path = Path(omp_command)
    omp = str(omp_path.resolve()) if omp_path.is_file() else shutil.which(omp_command)
    commands = {
        "omp": [omp or omp_command, "--version"],
        "quint": ["quint", "--version"],
        "uv": ["uv", "--version"],
        "lean": ["lean", "--version"],
        "cargo-kani": ["cargo", "kani", "--version"],
    }
    for name, command in commands.items():
        executable = command[0] if name != "cargo-kani" else "cargo-kani"
        if (name == "omp" and omp is None) or (name != "omp" and shutil.which(executable) is None):
            detail = f"not found: {omp_command}" if name == "omp" else "not on PATH"
            report.add("toolchain", name, "fail" if name == "omp" else "warn", detail)
            continue
        result = subprocess.run(command, capture_output=True, text=True)
        output = (result.stdout + result.stderr).strip()
        pin = bom["tools"].get(name)
        if result.returncode != 0:
            report.add("toolchain", name, "warn", output or "version probe failed")
        elif pin and pin not in output:
            status = "warn" if name == "uv" else "fail"
            report.add("toolchain", name, status, f"live={output!r}, pin={pin!r}")
        else:
            report.add("toolchain", name, "ok", output)
    if omp is None:
        return
    contract = subprocess.run(
        [omp, "--agent-bridge-contract"], cwd=project,
        capture_output=True, text=True,
    )
    expected_contract = {
        "version": 1,
        "restrictTools": True,
        "perCallModel": True,
        "perCallTimeout": True,
        "servedModel": True,
        "servedFamily": True,
        "panelLineupFreeze": True,
    }
    try:
        contract_data = json.loads(contract.stdout) if contract.returncode == 0 else None
    except json.JSONDecodeError:
        contract_data = None
    report.add(
        "toolchain", "omp-agent-bridge-contract",
        "ok" if contract_data == expected_contract else "fail",
        "bridge capabilities present, including panel lineup freeze"
        if contract_data == expected_contract
        else (contract.stdout + contract.stderr).strip() or "agent bridge contract unavailable",
    )
    catalog = subprocess.run(
        [omp, "models", "--json", "-e", str(REPO)],
        cwd=project, capture_output=True, text=True,
    )
    if catalog.returncode != 0:
        report.add("toolchain", "omp-model-contract", "fail",
                   (catalog.stdout + catalog.stderr).strip() or "omp models failed")
        return
    try:
        models = {item["selector"]: item for item in json.loads(catalog.stdout)["models"]}
        registry = json.loads((REPO / "registry" / "voices.json").read_text())
        canonical = next(item for item in registry["profiles"] if item["name"] == "canonical-4")
        errors = []
        for seat in canonical["voices"]:
            voice = next(item for item in registry["voices"] if item["id"] == seat["id"])
            live = models.get(voice["omp_model"])
            if live is None:
                errors.append(f"{voice['id']}: model unavailable ({voice['omp_model']})")
                continue
            expected_ladder = voice.get("omp_thinking_ladder")
            if expected_ladder is not None and live.get("thinking") != expected_ladder:
                errors.append(
                    f"{voice['id']}: thinking ladder live={live.get('thinking')!r} expected={expected_ladder!r}"
                )
        report.add("toolchain", "omp-model-contract", "fail" if errors else "ok",
                   "; ".join(errors) if errors else "canonical models and thinking ladders available")
    except (KeyError, StopIteration, json.JSONDecodeError) as error:
        report.add("toolchain", "omp-model-contract", "fail", f"invalid OMP model catalog: {error}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--omp", default="omp", help="OMP executable path or command (default: omp)")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--strict", action="store_true", help="promote warnings to failures")
    args = parser.parse_args()
    project = args.project.resolve()
    report = Report()
    check_package(report)
    check_mcp(report)
    check_project(report, project)
    check_toolchain(report, project, args.omp)
    failed = report.failed or (args.strict and report.warned)
    if args.json:
        print(json.dumps({"status": "FAIL" if failed else "PASS", "findings": [asdict(item) for item in report.findings]}, indent=2))
    else:
        for finding in report.findings:
            print(f"  [{finding.status:>4}] {finding.category}/{finding.name}: {finding.detail}")
        print("\nDOCTOR " + ("FAILED" if failed else "PASSED"))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
