#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""R38 proof adapter source, native target, TLC and Lean selector refusals."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MODULE = REPO / "tools/evidence-v4/evidence-v4-toolchain-proof.ts"
PROGRAM = (
    "const {identifyLean,identifyQuint}=await import("
    + json.dumps(MODULE.as_uri())
    + ");\n"
    + "const {canonicalToolPath}=await import("
    + json.dumps(MODULE.with_name("evidence-v4-toolchain-common.ts").as_uri())
    + ");\n"
    + r"""
const path = await import('node:path');
const input = await Bun.stdin.json();
const resolveCommand = async (name, cwd = input.cwd) => {
  const invoked = input.commands?.[name] ?? (name.includes('/') ? path.resolve(cwd, name) : Bun.which(name, {PATH:input.env.PATH}));
  if (!invoked) throw Error('Missing fixture executable: ' + name);
  return {invoked, realpath:await canonicalToolPath(invoked)};
};
const context = {
  root:input.root, cwd:input.cwd, cwdRelative:'.', subject:input.subject,
  effectiveEnv:input.env, declaration:{id:'proof'}, session:{},
  applicationContexts:(input.applications ?? []).map(app => ({...app,recipe:{resources:[]}})),
  commandContexts:input.checks === undefined ? undefined : [...(input.applications ?? []), ...input.checks],
  resolveCommand,
  // Native closure has its own adapter tests; these tests exercise proof configuration admission.
  native:async () => ({roots:[],packages:[],discovery:[],sdk:null}),
  probe:async (command, options = {}) => {
    const child = Bun.spawn(command, {cwd:options.cwd ?? input.cwd,env:options.env ?? input.env,stdout:'pipe',stderr:'pipe'});
    const [out, err, code] = await Promise.all([new Response(child.stdout).arrayBuffer(),new Response(child.stderr).arrayBuffer(),child.exited]);
    const stdout = Buffer.from(out), stderr = Buffer.from(err);
    if (code !== 0) throw Error('Probe failed: ' + command.join(' ') + '\n' + stderr.toString() + stdout.toString());
    return {stdout,stderr,code,identity:{command:[...command],cwd:'.',stdout_hash:'sha256:'+'0'.repeat(64),stderr_hash:'sha256:'+'0'.repeat(64),exit_code:code}};
  },
};
try {
  const result = await (input.adapter === 'quint' ? identifyQuint(context) : identifyLean(context));
  process.stdout.write(JSON.stringify({ok:true,sourceRequirements:result.sourceRequirements,roots:result.roots}));
} catch (error) {
  process.stdout.write(JSON.stringify({ok:false,error:error instanceof Error ? error.message : String(error)}));
}
"""
)


def discover(request: dict) -> dict:
    result = subprocess.run(
        [shutil.which("bun"), "--eval", PROGRAM],
        input=json.dumps(request),
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode:
        raise AssertionError(result.stdout + result.stderr)
    return json.loads(result.stdout)


@unittest.skipUnless(
    shutil.which("bun") and shutil.which("node"), "requires Bun and Node"
)
class TlcConfiguration(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="fv-proof-tlc-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        package = self.root / "quint"
        source = package / "dist"
        (source / "rust").mkdir(parents=True)
        (package / "package.json").write_text(
            json.dumps(
                {
                    "name": "@informalsystems/quint",
                    "version": "fixture",
                    "bin": {"quint": "dist/cli.js"},
                }
            )
        )
        cli = source / "cli.js"
        cli.write_text("#!/usr/bin/env node\n")
        cli.chmod(0o755)
        (source / "config.js").write_text(
            "exports.apalacheDistDir=()=>" + json.dumps(str(self.root)) + ";\n"
            "exports.rustEvaluatorDir=()=>" + json.dumps(str(self.root)) + ";\n"
        )
        (source / "apalache.js").write_text(
            "exports.DEFAULT_APALACHE_VERSION_TAG='fixture';\n"
        )
        (source / "rust/binaryManager.js").write_text(
            "let executable = 'evaluator'; exports.QUINT_EVALUATOR_VERSION='fixture';\n"
        )
        (self.root / "evaluator").write_text("#!/bin/sh\nexit 0\n")
        (self.root / "evaluator").chmod(0o755)
        self.config = self.root / "tlc.json"
        self.request = {
            "adapter": "quint",
            "root": str(self.root),
            "cwd": str(self.root),
            "subject": [
                str(cli),
                "run",
                "--backend=rust",
                "--tlc-config",
                str(self.config),
            ],
            "env": {"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
        }

    def configuration(self, value):
        self.config.write_text(json.dumps(value))
        return discover(self.request)

    def test_hardlinked_evaluator_preserves_selected_executable_spelling(self):
        evaluator = self.root / "evaluator"
        alias = self.root / "evaluator-alias"
        os.link(evaluator, alias)
        self.assertEqual(evaluator.stat().st_ino, alias.stat().st_ino)
        binary_manager = self.root / "quint/dist/rust/binaryManager.js"
        for selected in (evaluator, alias, evaluator, alias):
            with self.subTest(selected=selected.name):
                binary_manager.write_text(
                    "let executable = "
                    + json.dumps(selected.name)
                    + "; exports.QUINT_EVALUATOR_VERSION='fixture';\n"
                )
                result = self.configuration({})
                self.assertTrue(result["ok"], result)
                recorded = [
                    root["path"]
                    for root in result["roots"]
                    if root["label"] == "evaluator/executable"
                ]
                self.assertEqual(recorded, [str(selected)])

    def test_tlc_memory_fields_reject_jvm_loader_and_argument_file_values(self):
        for key in ("maxHeap", "stackSize"):
            for value in (
                "-javaagent:/outside/agent.jar",
                "@/outside/java.args",
                "-agentpath:/outside/agent.so",
                "-Xmx8G -javaagent:/outside/agent.jar",
            ):
                with self.subTest(key=key, value=value):
                    result = self.configuration({key: value})
                    self.assertFalse(result["ok"], result)
                    self.assertIn(
                        "TLC configuration field or memory-size", result["error"]
                    )

    def test_tlc_rejects_other_fields_and_non_size_values(self):
        values = [
            {"workers": "auto"},
            {"jar": "/outside/tlc.jar"},
            {"maxHeap": "-Xss8G"},
            {"stackSize": "-Xmx8G"},
            {"maxHeap": "-Xmx0"},
            {"stackSize": "-Xss-1m"},
            {"maxHeap": "-Xmx8G\n"},
            {"stackSize": "-Xss1.5m"},
            {"maxHeap": 8},
            {"stackSize": None},
        ]
        for value in values:
            with self.subTest(value=value):
                result = self.configuration(value)
                self.assertFalse(result["ok"], result)
                self.assertIn("TLC configuration field or memory-size", result["error"])

    def test_tlc_accepts_only_supported_memory_size_fields(self):
        for value in (
            {},
            {"maxHeap": "-Xmx8G", "stackSize": "-Xss515m"},
            {"maxHeap": "-Xmx1024", "stackSize": "-Xss64K"},
        ):
            with self.subTest(value=value):
                self.assertTrue((result := self.configuration(value))["ok"], result)
        result = self.configuration(
            {"maxHeap": "-Xmx8G", "stackSize": "-javaagent:/outside/agent.jar"}
        )
        self.assertFalse(result["ok"], result)
        self.assertIn("TLC configuration field or memory-size", result["error"])


def lean_installation():
    candidates = []
    lean = shutil.which("lean")
    if lean:
        result = subprocess.run(
            [lean, "--print-prefix"], capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            candidates.append(Path(result.stdout.strip()))
    candidates.extend(
        sorted(
            (Path.home() / ".elan/toolchains").glob("leanprover--lean4---v*"),
            reverse=True,
        )
    )
    for candidate in candidates:
        if (
            not (candidate / "bin/lean").is_file()
            or not (candidate / "bin/lake").is_file()
        ):
            continue
        result = subprocess.run(
            [str(candidate / "bin/lean"), "--version"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        version = re.search(
            r"version ([0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?),",
            result.stdout + result.stderr,
        )
        if result.returncode == 0 and version and version[1] == "4.33.1":
            return candidate.resolve(), "leanprover/lean4:v4.33.1"
    raise unittest.SkipTest("requires the reviewed Lean/Lake 4.33.1 distribution")


@unittest.skipUnless(shutil.which("bun"), "requires Bun")
class LakeConfiguration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.distribution, cls.selection = lean_installation()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="fv-proof-lake-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.root = self.base / "project"
        self.root.mkdir()
        (self.root / "lake-manifest.json").write_text(
            json.dumps(
                {
                    "version": "1.2.0",
                    "name": "Review",
                    "packagesDir": ".lake/packages",
                    "packages": [],
                }
            )
        )
        (self.base / "outside").mkdir()
        (self.base / "outside/Review.lean").write_text("def outsideValue := 1\n")
        (self.base / "outside.o").write_bytes(b"outside native input")
        self.request = {
            "adapter": "lean",
            "root": str(self.root),
            "cwd": str(self.root),
            "subject": [str(self.distribution / "bin/lake"), "build"],
            "env": {
                "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                "ELAN_TOOLCHAIN": self.selection,
                "LAKE_CACHE_DIR": str(self.base / "cache"),
            },
        }

    def toml(self, package="", target=""):
        (self.root / "lakefile.toml").write_text(
            'name = "Review"\n' + package + '\n[[lean_lib]]\nname = "Review"\n' + target
        )

    def lean_config(self, body):
        (self.root / "lakefile.lean").write_text(
            "import Lake\nopen Lake DSL\npackage Review\n" + body
        )

    def assert_refused(self, expected):
        result = discover(self.request)
        self.assertFalse(result["ok"], result)
        self.assertIn(expected, result["error"])

    def test_package_srcdir_outside_hashed_roots_is_refused(self):
        self.toml(package='srcDir = "../outside"\n')
        self.assert_refused("srcDir resolves outside hashed input roots")

    def test_library_srcdir_outside_hashed_roots_is_refused(self):
        self.toml(target='srcDir = "../outside"\n')
        self.assert_refused("srcDir resolves outside hashed input roots")

    def test_symlink_srcdir_outside_hashed_roots_is_refused(self):
        (self.root / "linked").symlink_to(
            self.base / "outside", target_is_directory=True
        )
        self.toml(target='srcDir = "linked"\n')
        self.assert_refused("srcDir resolves outside hashed input roots")

    def test_srcdir_in_generated_namespace_is_refused(self):
        (self.root / ".lake/build").mkdir(parents=True)
        self.toml(target='srcDir = ".lake/build"\n')
        self.assert_refused("srcDir resolves outside hashed input roots")

    def test_target_level_link_objects_and_libraries_are_refused(self):
        for kind in ("lean_lib", "lean_exe"):
            for field in ("moreLinkObjs", "moreLinkLibs"):
                with self.subTest(kind=kind, field=field):
                    self.lean_config(
                        'input_file native where\n  path := "native.o"\n'
                        + kind
                        + " Review where\n  "
                        + field
                        + " := #[{key := .packageTarget .anonymous `native}]\n"
                    )
                    (self.root / "native.o").write_bytes(b"native input")
                    self.assert_refused("native/custom target")

    def test_input_file_outside_hashed_roots_is_refused(self):
        self.lean_config(
            'input_file native where\n  path := "../outside.o"\nlean_lib Review\n'
        )
        self.assert_refused("input target resolves outside hashed input roots")

    def test_symlink_input_file_outside_hashed_roots_is_refused(self):
        (self.root / "native.o").symlink_to(self.base / "outside.o")
        self.lean_config(
            'input_file native where\n  path := "native.o"\nlean_lib Review\n'
        )
        self.assert_refused("input target resolves outside hashed input roots")

    def test_project_inputs_are_returned_as_relative_source_requirements(self):
        (self.root / "src").mkdir()
        (self.root / "native.o").write_bytes(b"native input")
        self.lean_config(
            'input_file native where\n  path := "native.o"\nlean_lib Review where\n  srcDir := "src"\n'
        )
        result = discover(self.request)
        self.assertTrue(result["ok"], result)
        self.assertEqual(
            result["sourceRequirements"],
            {"directories": [".", "src"], "files": ["native.o"]},
        )

    def elan_launcher(self):
        elan = shutil.which("elan")
        if not elan:
            raise unittest.SkipTest("requires installed Elan for selector comparisons")
        home = self.base / "elan"
        (home / "toolchains").mkdir(parents=True)
        (home / "bin").mkdir()
        for token in ("review-a", "review-b"):
            (home / "toolchains" / token).symlink_to(
                self.distribution, target_is_directory=True
            )
        for name in ("elan", "lean", "lake"):
            (home / "bin" / name).symlink_to(Path(elan).resolve())
        self.request["env"]["ELAN_HOME"] = str(home)
        self.request["env"].pop("ELAN_TOOLCHAIN", None)
        return home / "bin"

    def test_recipe_toolchain_selector_mismatch_is_refused(self):
        self.toml()
        launcher = self.elan_launcher() / "lake"
        self.request["subject"] = [str(launcher), "+review-a", "build"]
        self.request["applications"] = [
            {"subject": [str(launcher), "+review-b", "build"], "cwd": str(self.root)}
        ]
        self.assert_refused("selected application toolchain")

    def test_preflight_toolchain_selector_mismatch_is_refused(self):
        self.toml()
        launcher = self.elan_launcher() / "lake"
        self.request["subject"] = [str(launcher), "+review-a", "build"]
        self.request["checks"] = [
            {"subject": [str(launcher), "+review-b", "build"], "cwd": str(self.root)}
        ]
        self.assert_refused("selected application toolchain")

    def test_recipe_entry_executable_mismatch_is_refused(self):
        self.toml()
        alternate = self.base / "alternate/lake"
        alternate.parent.mkdir()
        alternate.write_text("#!/bin/sh\nexit 0\n")
        alternate.chmod(0o755)
        self.request["applications"] = [
            {"subject": [str(alternate), "build"], "cwd": str(self.root)}
        ]
        self.assert_refused("selected application executable")

    def test_matching_recipe_selector_and_executable_remain_admitted(self):
        self.toml()
        self.request["applications"] = [
            {"subject": self.request["subject"], "cwd": str(self.root)}
        ]
        result = discover(self.request)
        self.assertTrue(result["ok"], result)
        self.assertEqual(
            result["sourceRequirements"], {"directories": ["."], "files": []}
        )


if __name__ == "__main__":
    unittest.main()
