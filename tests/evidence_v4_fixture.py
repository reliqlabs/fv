"""Real-process v4 fixtures. Commits in these temporary repositories are unsigned."""

from __future__ import annotations

import copy
import json
import os
import platform
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SUPPORT = REPO / "tests" / "evidence_v4_fixture.ts"
GATE = REPO / "scripts" / "check_evidence_records.py"


def load_json(path: str | Path) -> dict:
    return json.loads(Path(path).read_bytes())


def rewrite_json(path: str | Path, value: object) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _portable():
    scripts = str(REPO / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import fv_evidence_v4

    return fv_evidence_v4


def reidentify_claim(value: dict) -> dict:
    result = copy.deepcopy(value)
    result.pop("record_id", None)
    result["record_id"] = _portable().D("claim-record", result)
    return result


def reidentify_artifact(value: dict) -> dict:
    result = copy.deepcopy(value)
    result.pop("artifact_id", None)
    result["artifact_id"] = _portable().D("execution-artifact", result)
    return result


class EvidenceV4Fixture:
    def __init__(
        self, claims=("A", "B"), *, distinct=False, randomized=False, recipe_count=1
    ):
        bun = shutil.which("bun")
        git = shutil.which("git")
        shell = shutil.which("sh")
        if not bun or not git or not shell:
            raise RuntimeError("fixture requires Bun, Git and POSIX sh")
        if not claims or recipe_count < 1:
            raise ValueError("fixture needs claims and recipes")
        if randomized and not distinct:
            raise ValueError("randomized fixture repeats must be owner-distinct")
        self.bun = str(Path(bun).resolve())
        self.git = str(Path(git).resolve())
        self.shell = str(Path(shell).resolve())
        self._temporary = tempfile.TemporaryDirectory(prefix="fv-v4-fixture-")
        self.temporary = Path(self._temporary.name).resolve(strict=True)
        self.root = self.temporary / "project"
        self.root.mkdir()
        self.policy_path = ".fv/execution-policy.json"
        self.evidence_root = self.root / ".fv/evidence/v4"
        self.control_dir = self.root / ".fv/evidence/fixture-control"
        self.control_dir.mkdir(parents=True)
        self._processes: list[subprocess.Popen] = []
        self.tool_path = self.temporary / "fixture-tool"
        self.tool_path.write_text(
            "#!"
            + self.shell
            + "\nexec "
            + shlex.quote(self.bun)
            + ' fixture/fixture.ts program "$@"\n',
            encoding="utf-8",
        )
        self.tool_path.chmod(0o755)
        self.write(".gitignore", ".fv/evidence/\n")
        self.write(
            ".fv/intent.md",
            "# Fixture intent\nEvery required member has an actual positive source witness.\n",
        )
        self.write(
            ".fv/dispatch.json",
            {"omp_native": {"project_root": ".", "target_spec": ".fv/intent.md"}},
        )
        self.write(".fv/verified-inputs.txt", "mode: exclude\n")
        self.write("src/value.txt", "fixture-source-v1\n")
        self.write("notes/unrelated.txt", "unrelated-existing-v1\n")
        self.write("fixture/fixture.ts", SUPPORT.read_bytes())
        self.write(
            "tools/evidence-v4/evidence-v4-model.ts",
            (REPO / "tools/evidence-v4/evidence-v4-model.ts").read_bytes(),
        )
        self.write(
            ".fv/obligations.json",
            {
                "version": 1,
                "invariants": [],
                "witnesses": [
                    {"id": claim, "name": "witness_" + claim, "required": True}
                    for claim in claims
                ],
            },
        )
        toolchains = [
            self._tool("bun", self.bun),
            self._tool("git", self.git),
            self._tool("sh", self.shell),
            self._tool("fixture-tool", str(self.tool_path), requires=["bun", "sh"]),
        ]
        if sys.platform == "darwin":
            toolchains.insert(
                3,
                {
                    "id": "native",
                    "kind": "tree",
                    "locator": {
                        "mode": "adapter",
                        "value": "darwin-native",
                        "cwd": ".",
                        "subject": [self.bun, self.git, self.shell],
                    },
                    "version_command": None,
                    "version_cwd": None,
                    "requires": [],
                    "accept": {"sha256": [], "version_contains": []},
                },
            )
        tools = sorted(tool["id"] for tool in toolchains)
        check_tools = sorted(tool for tool in tools if tool != "fixture-tool")
        recipes = []
        for index in range(1, recipe_count + 1):
            recipes.append(
                {
                    "recipe_id": f"recipe-{index}",
                    "command": [str(self.tool_path), f"recipe-{index}"],
                    "cwd": ".",
                    "evidence_class": "test-witnessed",
                    "pass_marker": "test result: ok.",
                    "timeout_seconds": 30,
                    "determinism": {
                        "mode": "distinct" if distinct else "fixed",
                        "rationale": "The positive witness is a fixed source and sanitized-environment digest; distinct repeats retain separate owners.",
                    },
                    "source_closure": {
                        "mode": "prefixes",
                        "prefixes": ["fixture/", "src/", "tools/"],
                        "basis": [".fv/fixture-contract.json"],
                    },
                    "toolchain": tools,
                    "resources": [f"fixture-counter-{index}"],
                    "exclusive": False,
                    "bounds": {"samples": None, "max_steps": None, "seed": None},
                    "attestation": None,
                    "build_cache": None,
                    "ownership_protocol": None,
                    "retained_environment": [],
                }
            )
            if randomized:
                recipes[-1]["command"].append("--randomized")
        os_name = (
            "darwin"
            if sys.platform == "darwin"
            else "linux"
            if sys.platform.startswith("linux")
            else sys.platform
        )
        arch = {"aarch64": "arm64", "x86_64": "x64"}.get(
            platform.machine(), platform.machine()
        )
        self.policy = {
            "schema_version": "fv-execution-policy/v1",
            "policy_id": "real-process-fixture",
            "verified_inputs": ".fv/verified-inputs.txt",
            "intent_path": ".fv/intent.md",
            "manifest_path": ".fv/obligations.json",
            "definition_files": [
                ".fv/fixture-contract.json",
                "fixture/fixture.ts",
                "tools/evidence-v4/evidence-v4-model.ts",
            ],
            "environment": {
                "mode": "sanitized",
                "platforms": [{"os": os_name, "arch": arch}],
                "inherit": ["FV_FIXTURE_PUBLIC"],
                "set": {"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
                "identity": ["FV_FIXTURE_PUBLIC", "PATH"],
            },
            "toolchains": toolchains,
            "preflight": [
                {
                    "id": "fixture-preflight",
                    "command": [
                        self.bun,
                        "fixture/fixture.ts",
                        "checker",
                        "--preflight",
                    ],
                    "cwd": ".",
                    "resources": [],
                    "toolchain": check_tools,
                    "timeout_seconds": 30,
                }
            ],
            "claim_checker": {
                "id": "fixture-observations",
                "command": [self.bun, "fixture/fixture.ts", "checker"],
                "cwd": ".",
                "resources": [],
                "toolchain": check_tools,
                "timeout_seconds": 30,
            },
            "recipes": recipes,
            "records": [
                {
                    "claim_id": claim,
                    "required": True,
                    "evidence_class": "test-witnessed",
                    "scope": "actual deterministic source witness",
                    "executions": [
                        {
                            "slot_id": f"slot-{index}",
                            "recipe_id": f"recipe-{index}",
                            "tool": f"fixture-{index}",
                            "observation_binding": {
                                "path": ".fv/fixture-contract.json",
                                "pointer": f"/observations/{claim}/slot-{index}",
                            },
                        }
                        for index in range(1, recipe_count + 1)
                    ],
                }
                for claim in claims
            ],
            "jobs": {"default": 2, "max": 4},
            "trust_assumptions": {
                "no_concurrent_mutation": True,
                "build_cache_integrity": "upstream-build-system",
                "retained_history_integrity": "trusted-producer-store",
            },
        }
        cache_home = self.temporary / "cache"
        cache_home.mkdir()
        self.policy["environment"]["set"]["XDG_CACHE_HOME"] = str(cache_home)
        self.policy["environment"]["identity"].append("XDG_CACHE_HOME")
        self.save_policy()
        self.git_command("init", "--quiet")
        self.git_command("config", "core.filemode", "true")
        self.commit("unsigned initial regression fixture")

    @staticmethod
    def _tool(name: str, path: str, *, requires=()) -> dict:
        return {
            "id": name,
            "kind": "executable",
            "locator": {"mode": "path", "value": path},
            "version_command": None,
            "version_cwd": None,
            "requires": list(requires),
            "accept": {"sha256": [], "version_contains": []},
        }

    def __enter__(self):
        return self

    def __exit__(self, *_):
        try:
            for process in self._processes:
                if process.poll() is None:
                    self.cancel(process)
                    try:
                        self.finish_call(process, timeout=15)
                    except (RuntimeError, subprocess.TimeoutExpired):
                        process.kill()
                        process.wait(timeout=5)
        finally:
            self._temporary.cleanup()

    def write(self, relative: str, data: bytes | str | object) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, bytes):
            path.write_bytes(data)
        elif isinstance(data, str):
            path.write_text(data, encoding="utf-8")
        else:
            rewrite_json(path, data)
        return path

    def save_policy(self, commit_message: str | None = None) -> None:
        self.write(self.policy_path, self.policy)
        self.write(
            ".fv/fixture-contract.json",
            {
                "schema_version": "fv-fixture-contract/v1",
                "dependency_basis": {
                    "complete": True,
                    "source": ["fixture/", "src/", "tools/"],
                    "external_runtime": "declared toolchain",
                    "unrelated": "notes/ is not consumed by the evidence recipe",
                },
                "recipes": self.policy["recipes"],
                "observations": {
                    record["claim_id"]: {
                        slot["slot_id"]: {
                            "recipe_id": slot["recipe_id"],
                            "tool": slot["tool"],
                            "kind": "source-witness",
                            "witness_count": 1,
                        }
                        for slot in record["executions"]
                    }
                    for record in self.policy["records"]
                },
            },
        )
        if commit_message:
            self.commit(commit_message)

    def git_command(self, *args: str) -> subprocess.CompletedProcess:
        environment = {
            **os.environ,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
        }
        return subprocess.run(
            [
                self.git,
                "-c",
                "core.hooksPath=" + os.devnull,
                "-c",
                "commit.gpgsign=false",
                "-c",
                "user.name=Unsigned FV Fixture",
                "-c",
                "user.email=unsigned-fixture@example.invalid",
                *args,
            ],
            cwd=self.root,
            env=environment,
            capture_output=True,
            text=True,
            check=True,
        )

    def commit(self, message: str = "unsigned regression fixture change") -> None:
        self.git_command("add", "-A")
        self.git_command(
            "commit", "--quiet", "--no-gpg-sign", "--allow-empty", "-m", message
        )

    def set_control(self, recipe_id="recipe-1", **fields) -> None:
        rewrite_json(self.control_dir / (recipe_id + ".json"), fields)

    def release(self, gate: str) -> None:
        path = self.control_dir / "gates" / gate
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"1")

    def events(self) -> list[dict]:
        path = self.control_dir / "events.jsonl"
        if not path.exists():
            return []
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line
        ]

    def count(self, recipe_id="recipe-1") -> int:
        path = self.control_dir / (recipe_id + ".count")
        return int(path.read_text()) if path.exists() else 0

    def process_environment(self, env=None) -> dict[str, str]:
        environment = dict(os.environ)
        environment.pop("FV_FIXTURE_PUBLIC", None)
        for name, value in (env or {}).items():
            if value is None:
                environment.pop(name, None)
            else:
                environment[name] = str(value)
        return environment

    def compile_host_driver(self) -> Path:
        executable = self.temporary / "compiled-fixture-host"
        result = subprocess.run(
            [
                self.bun,
                "build",
                "--compile",
                str(SUPPORT),
                "--outfile",
                str(executable),
            ],
            cwd=REPO,
            env=self.process_environment({"BUN_BE_BUN": None}),
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"fixture host compilation exited {result.returncode}: {result.stdout}\n{result.stderr}"
            )
        return executable.resolve(strict=True)

    def start_call(
        self,
        mode="run",
        *,
        records=None,
        jobs=None,
        resume=None,
        env=None,
        signal_after_ms=None,
        call=None,
        driver=None,
    ) -> subprocess.Popen:
        request = (
            {
                "schema_version": "fv-evidence-run/v4",
                "policy": self.policy_path,
                "mode": mode,
            }
            if call is None
            else copy.deepcopy(call)
        )
        for name, value in (("records", records), ("jobs", jobs), ("resume", resume)):
            if value is not None:
                request[name] = value
        environment = self.process_environment(env)
        driver_command = (
            [self.bun, str(SUPPORT)]
            if driver is None
            else [str(Path(driver).resolve(strict=True))]
        )
        process = subprocess.Popen(
            [
                *driver_command,
                "driver",
                str(self.root),
                str(REPO / "tools/evidence-v4/evidence-v4-run.ts"),
            ],
            cwd=self.root,
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self._processes.append(process)
        payload = {"call": request}
        if signal_after_ms is not None:
            payload["signal_after_ms"] = signal_after_ms
        process.stdin.write(json.dumps(payload) + "\n")
        process.stdin.flush()
        return process

    @staticmethod
    def cancel(process: subprocess.Popen) -> None:
        if process.poll() is None and process.stdin and not process.stdin.closed:
            try:
                process.stdin.write("abort\n")
                process.stdin.flush()
            except BrokenPipeError:
                pass

    def finish_call(self, process: subprocess.Popen, *, timeout=120) -> dict:
        stdout, stderr = process.communicate(timeout=timeout)
        if process.returncode != 0:
            raise RuntimeError(
                f"native fixture driver exited {process.returncode}: {stdout}\n{stderr}"
            )
        lines = stdout.splitlines()
        if len(lines) != 1:
            raise RuntimeError(
                f"native driver did not return one result: {stdout}\n{stderr}"
            )
        result = json.loads(lines[0])
        return result

    def call(self, mode="run", **options) -> dict:
        return self.finish_call(self.start_call(mode, **options))

    def plan(self, **options) -> dict:
        return self.call("plan", **options)

    def run(self, **options) -> dict:
        return self.call("run", **options)

    def current(self) -> dict:
        return load_json(self.evidence_root / "current.json")

    def manifest(self, result=None) -> dict:
        if result is not None:
            manifest = result.get("manifest")
            if manifest is None:
                raise RuntimeError("run returned no manifest")
            return manifest
        return load_json(self.root / self.current()["run"]["path"])

    def claims(self, result=None) -> list[dict]:
        return [
            load_json(self.root / entry["record"]["path"])
            for entry in self.manifest(result)["claims"]
        ]

    def artifacts(self) -> list[tuple[Path, dict]]:
        return [
            (path, load_json(path))
            for path in sorted(self.evidence_root.glob("executions/*/*/execution.json"))
        ]

    def assess(
        self,
        *,
        recompute=True,
        recheck_observations=True,
        records_path=None,
        require=None,
    ) -> tuple[dict, int]:
        return _portable().assess_v4(
            self.root,
            records_path or self.evidence_root / "current.json",
            self.root / ".fv/obligations.json",
            require,
            recompute=recompute,
            recheck_observations=recheck_observations,
        )

    def gate(self, *, records_path=None, extra=()) -> subprocess.CompletedProcess:
        return subprocess.run(
            [
                sys.executable,
                str(GATE),
                "--root",
                str(self.root),
                "--manifest",
                str(self.root / ".fv/obligations.json"),
                "--records",
                str(records_path or self.evidence_root / "current.json"),
                "--json",
                *extra,
            ],
            cwd=self.root,
            capture_output=True,
            text=True,
        )
