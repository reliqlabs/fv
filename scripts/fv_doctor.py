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
        panel = json.loads((REPO / "templates" / "omp-panel.json").read_text())
        role = panel.get("roles", {}).get("fv-canonical", {})
        expected_voices = {voice["model"]: voice for voice in expected_route["voices"]}
        panel_errors = []
        members = role.get("members")
        if role.get("strategy") != "independent" or not isinstance(members, list):
            panel_errors.append("fv-canonical must be an independent OMP panel role")
            members = []
        if role.get("minFamilies") != len(expected_route["voices"]):
            panel_errors.append("fv-canonical family floor drift")
        if len(members) != len(expected_route["voices"]):
            panel_errors.append(
                f"fv-canonical members={len(members)}, expected={len(expected_route['voices'])}"
            )
        for index, member in enumerate(members):
            model = member.get("model") if isinstance(member, dict) else None
            candidates = model if isinstance(model, list) else [model]
            primary = candidates[0] if candidates else None
            expected = expected_voices.get(primary)
            if expected is None:
                panel_errors.append(f"fv-canonical member {index}: unknown primary candidate")
                continue
            if member.get("thinking") != expected.get("thinking_level"):
                panel_errors.append(f"fv-canonical member {index}: thinking level drift")
        route_current = generated_route == expected_route and not panel_errors
        report.add(
            "package", "registry-routes", "ok" if route_current else "fail",
            "generated OMP routes and fv-canonical panel seed current"
            if route_current else "; ".join(panel_errors) or "generated OMP route drift",
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

    config_path = project / ".omp" / "config.yml"
    try:
        config = yaml.safe_load(config_path.read_text()) or {}
        panel = config.get("panel") if isinstance(config, dict) else None
        roles = panel.get("roles") if isinstance(panel, dict) else None
        actual = roles.get("fv-canonical") if isinstance(roles, dict) else None
        members = actual.get("members") if isinstance(actual, dict) else None
        strategy = actual.get("strategy") if isinstance(actual, dict) else None
        floor = actual.get("minFamilies") if isinstance(actual, dict) else None
        panel_errors = []
        if strategy != "independent" or not isinstance(members, list) or len(members) < 2:
            panel_errors.append("OMP panel.roles.fv-canonical must be an independent role with at least two members")
        if not isinstance(floor, int) or not isinstance(members, list) or floor < 1 or floor > len(members):
            panel_errors.append("OMP panel.roles.fv-canonical has an invalid minFamilies floor")
    except (OSError, yaml.YAMLError) as error:
        panel_errors = [str(error)]
    report.add(
        "project",
        "panel-role",
        "fail" if panel_errors else "ok",
        "; ".join(panel_errors) if panel_errors else "OMP owns a structurally valid fv-canonical panel role",
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
        "java": ["java", "-version"],
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
            status = "fail" if name == "omp" else "warn"
            report.add("toolchain", name, status, output or "version probe failed")
        elif pin and pin not in output:
            status = "warn" if name == "uv" else "fail"
            report.add("toolchain", name, status, f"live={output!r}, pin={pin!r}")
        else:
            # OMP's live version is provenance. Compatibility is decided by the
            # bridge contract below, so routine tau upgrades stay admissible.
            report.add("toolchain", name, "ok", output)
    if omp is None:
        return
    contract = subprocess.run(
        [omp, "--agent-bridge-contract"], cwd=project,
        capture_output=True, text=True,
    )
    specification = bom.get("omp_contract")
    required_version = specification.get("version") if isinstance(specification, dict) else None
    required = specification.get("required") if isinstance(specification, dict) else None
    try:
        contract_data = json.loads(contract.stdout) if contract.returncode == 0 else None
    except json.JSONDecodeError:
        contract_data = None
    violations = []
    if not isinstance(contract_data, dict):
        violations.append("agent bridge contract unavailable or malformed")
    if not isinstance(required_version, int) or not isinstance(required, dict):
        violations.append("bom.json omp_contract is malformed")
    elif isinstance(contract_data, dict):
        if contract_data.get("version") != required_version:
            violations.append(
                f"contract version={contract_data.get('version')!r}, required={required_version!r}"
            )
        for capability, expected in required.items():
            if not isinstance(expected, bool):
                violations.append(f"invalid required capability value {capability}={expected!r}")
            elif contract_data.get(capability) is not expected:
                violations.append(
                    f"capability {capability}={contract_data.get(capability)!r}, required={expected!r}"
                )
    report.add(
        "toolchain", "omp-agent-bridge-contract",
        "fail" if violations else "ok",
        "; ".join(violations) if violations
        else f"required OMP bridge contract satisfied (version {required_version}); extra capabilities accepted",
    )
    catalog = subprocess.run(
        [omp, "models", "--json", "-e", str(REPO)],
        cwd=project, capture_output=True, text=True,
    )
    panel_config = subprocess.run(
        [omp, "config", "get", "panel"],
        cwd=project, capture_output=True, text=True,
    )
    if catalog.returncode != 0 or panel_config.returncode != 0:
        detail = (catalog.stdout + catalog.stderr + panel_config.stdout + panel_config.stderr).strip()
        report.add("toolchain", "omp-model-contract", "fail", detail or "OMP model/panel query failed")
        return
    try:
        models = {item["selector"]: item for item in json.loads(catalog.stdout)["models"]}
        panel = json.loads(panel_config.stdout)["roles"]["fv-canonical"]
        members = panel["members"]
        errors = []
        fallbacks = []
        for index, member in enumerate(members):
            model = member.get("model")
            fallbacks_config = member.get("fallbacks", [])
            candidates = list(model) if isinstance(model, list) else [model, *fallbacks_config]
            if not candidates or any(not isinstance(candidate, str) or not candidate for candidate in candidates):
                errors.append(f"member {index}: invalid model candidates")
                continue
            selected = next((candidate for candidate in candidates if candidate in models), None)
            if selected is None:
                errors.append(f"member {index}: no candidate available ({candidates})")
                continue
            level = member.get("thinking")
            live_ladder = models[selected].get("thinking")
            if level not in (None, "auto", "off") and (
                not isinstance(live_ladder, list) or level not in live_ladder
            ):
                errors.append(
                    f"member {index}: thinking level={level!r} unavailable for "
                    f"selected candidate {selected} ladder={live_ladder!r}"
                )
            if selected != candidates[0]:
                fallbacks.append(f"member-{index + 1}->{selected}")
        detail = "effective OMP fv-canonical candidates and thinking levels available"
        if fallbacks:
            detail += f"; fallbacks={fallbacks}"
        report.add("toolchain", "omp-model-contract", "fail" if errors else "ok",
                   "; ".join(errors) if errors else detail)
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        report.add("toolchain", "omp-model-contract", "fail", f"invalid OMP model/panel output: {error}")


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
