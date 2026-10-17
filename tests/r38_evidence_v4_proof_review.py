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
import zipfile

REPO = Path(__file__).resolve().parents[1]
MODULE = REPO / "tools/evidence-v4/evidence-v4-toolchain-proof.ts"
PROGRAM = (
    "const {identifyLean,identifyQuint}=await import("
    + json.dumps(MODULE.as_uri())
    + ");\n"
    + "const {canonicalToolPath}=await import("
    + json.dumps(MODULE.with_name("evidence-v4-toolchain-common.ts").as_uri())
    + ");\n"
    + "const registryModule = "
    + json.dumps(MODULE.with_name("evidence-v4-toolchain.ts").as_uri())
    + ";\n"
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
  applicationContexts:(input.applications ?? []).map(app => ({...app,recipe:{resources:app.resources ?? [],build_cache:app.build_cache ?? null}})),
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
  if (input.op === 'bind') {
    const {createToolchainSession} = await import(registryModule);
    const policy = {toolchains:[{id:'plain',kind:'tree',locator:{mode:'path',value:input.distribution},requires:[]}],recipes:[],preflight:[]};
    const tools = createToolchainSession({root:input.root,policy,env:input.env,session:{}});
    await tools.assertCommandBound(input.subject, '.', ['plain']);
    process.stdout.write(JSON.stringify({ok:true}));
    process.exit(0);
  }
  const result = await (input.adapter === 'quint' ? identifyQuint(context) : identifyLean(context));
  if (input.bound !== undefined) {
    const {assertSourceRequirements} = await import(registryModule.replace('evidence-v4-toolchain.ts', 'evidence-v4-source.ts'));
    await assertSourceRequirements(input.root, {files:input.bound.map(path => ({path}))}, result.sourceRequirements);
  }
  process.stdout.write(JSON.stringify({ok:true,sourceRequirements:result.sourceRequirements,roots:result.roots,discovery:result.discovery}));
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

    def test_mismatched_verify_subcommand_and_node_entry_refuse_discovery(self):
        self.config.write_text('{"maxHeap":"-javaagent:/outside/agent.jar"}')
        cli = self.request["subject"][0]
        for subject in (
            [cli, "verify", "--backend=tlc", "--tlc-config", str(self.config)],
            [
                shutil.which("node"),
                cli,
                "verify",
                "--backend=tlc",
                "--tlc-config",
                str(self.config),
            ],
        ):
            with self.subTest(subject=subject):
                self.request["applications"] = [
                    {"subject": subject, "cwd": str(self.root)}
                ]
                result = discover(self.request)
                self.assertFalse(result["ok"], result)
                self.assertRegex(result["error"], "subcommand|application entry")

    def test_quint_commands_without_backend_adapter_refuse_before_tlc_dispatch(self):
        self.config.write_text('{"maxHeap":"-javaagent:/outside/agent.jar"}')
        cli = self.request["subject"][0]
        for subcommand in ("verify", "run", "test", "typecheck", "parse", "compile"):
            for subject in (
                [cli, subcommand, "--backend=tlc", "--tlc-config", str(self.config)],
                [shutil.which("node"), cli, subcommand],
            ):
                with self.subTest(subject=subject):
                    result = discover(
                        {
                            **self.request,
                            "op": "bind",
                            "distribution": str(self.root / "quint"),
                            "subject": subject,
                        }
                    )
                    self.assertFalse(result["ok"], result)
                    self.assertIn("quint-backends", result["error"])

    def test_tlc_config_refuses_symlink_before_parent_traversal(self):
        outside = self.root / "outside/a/b"
        outside.mkdir(parents=True)
        (self.root / "linked").symlink_to(outside, target_is_directory=True)
        self.config.write_text("{}")
        self.request["subject"][-1] = "linked/../tlc.json"
        result = discover(self.request)
        self.assertFalse(result["ok"], result)
        self.assertIn("Symlink in Quint configuration path", result["error"])

    def test_node_options_accepts_no_unreviewed_tokens(self):
        self.config.write_text("{}")
        for value in (
            "--require=/outside/loader.js",
            "-r/outside/loader.js",
            "--experimental-loader=/outside/loader.js",
            "--unknown-option",
        ):
            with self.subTest(value=value):
                self.request["env"]["NODE_OPTIONS"] = value
                result = discover(self.request)
                self.assertFalse(result["ok"], result)
                self.assertIn("Node startup/module closure", result["error"])

    def verification(self):
        self.config.write_text("{}")
        self.request["subject"] = [
            self.request["subject"][0],
            "verify",
            "--backend=tlc",
            "--server-endpoint=localhost:1",
            "--tlc-config",
            str(self.config),
        ]
        self.request["applications"] = [
            {
                "subject": self.request["subject"],
                "cwd": str(self.root),
                "resources": ["quint"],
            }
        ]
        apalache = self.root / "apalache"
        (apalache / "bin").mkdir(parents=True)
        (apalache / "lib").mkdir()
        launcher = apalache / "bin/apalache-mc"
        launcher.write_text(
            '#!/bin/sh\nAPALACHE_JAR="${APALACHE_JAR:-../lib/apalache.jar}"\nexec java -jar "$APALACHE_JAR"\n'
        )
        launcher.chmod(0o755)
        java = self.root / "java/bin/java"
        java.parent.mkdir(parents=True)
        java.write_text(
            "#!/bin/sh\necho '    java.home = " + str(java.parent.parent) + "' >&2\n"
        )
        java.chmod(0o755)
        self.request["commands"] = {"java": str(java)}
        staged = self.root / "staged.jar"
        self.jar(staged)
        self.request["env"]["APALACHE_JAR"] = str(staged)
        return apalache / "lib/apalache.jar"

    def jar(self, file, manifest_extra="", index=False):
        with zipfile.ZipFile(file, "w") as jar:
            jar.writestr(
                "META-INF/MANIFEST.MF",
                "Manifest-Version: 1.0\nMain-Class: at.forsyte.apalache.tla.Tool\n"
                + manifest_extra
                + "\n",
            )
            jar.writestr("at/forsyte/apalache/tla/Tool.class", b"fixture")
            jar.writestr("com/microsoft/z3/Context.class", b"fixture")
            if index:
                jar.writestr("META-INF/INDEX.LIST", b"fixture")

    def test_tlc_classpath_jar_manifest_is_checked_with_staged_jar(self):
        jar = self.verification()
        for extra, index, expected in (
            ("Class-Path: /outside/dependency.jar\n", False, "Class-Path delegation"),
            ("", True, "index delegation"),
        ):
            with self.subTest(extra=extra, index=index):
                self.jar(jar, extra, index)
                result = discover(self.request)
                self.assertFalse(result["ok"], result)
                self.assertIn(expected, result["error"])
        self.jar(jar)
        result = discover(self.request)
        self.assertTrue(result["ok"], result)

    def test_apalache_jar_refuses_symlink_before_parent_traversal(self):
        self.jar(self.verification())
        target = self.root / "jar-outside/a/b"
        target.mkdir(parents=True)
        (self.root / "jar-link").symlink_to(target, target_is_directory=True)
        self.request["env"]["APALACHE_JAR"] = str(self.root) + "/jar-link/../staged.jar"
        result = discover(self.request)
        self.assertFalse(result["ok"], result)
        self.assertIn("Symlink in Apalache JAR path", result["error"])

    def test_relative_apalache_jar_refuses_different_application_cwd(self):
        self.jar(self.verification())
        application_cwd = self.root / "application"
        application_cwd.mkdir()
        self.jar(application_cwd / "staged.jar")
        self.request["env"]["APALACHE_JAR"] = "staged.jar"
        self.request["applications"][0]["cwd"] = str(application_cwd)
        result = discover(self.request)
        self.assertFalse(result["ok"], result)
        self.assertIn("Relative APALACHE_JAR", result["error"])

    def test_jvm_startup_environment_rejects_unreviewed_tokens(self):
        self.jar(self.verification())
        for key in (
            "JAVA_TOOL_OPTIONS",
            "JDK_JAVA_OPTIONS",
            "_JAVA_OPTIONS",
            "JVM_ARGS",
            "JVM_GC_ARGS",
        ):
            with self.subTest(key=key):
                self.request["env"][key] = "@/outside/java.args"
                result = discover(self.request)
                self.assertFalse(result["ok"], result)
                self.assertIn("Unsupported JVM startup configuration", result["error"])
                self.request["env"].pop(key)

    @unittest.skipUnless(shutil.which("java"), "requires an installed JVM")
    def test_java_discovery_is_independent_of_heap_address_layout(self):
        self.jar(self.verification())
        java = (
            str(Path(os.environ["JAVA_HOME"]) / "bin/java")
            if os.environ.get("JAVA_HOME")
            else shutil.which("java")
        )
        self.request["commands"]["java"] = java
        result = discover(self.request)
        self.assertTrue(result["ok"], result)
        [probe] = [
            entry
            for entry in result["discovery"]
            if "-XshowSettings:properties" in entry["command"]
        ]
        outputs = []
        for compressed in ("+", "-"):
            run = subprocess.run(
                [
                    java,
                    "-Xmx128m",
                    f"-XX:{compressed}UseCompressedOops",
                    *probe["command"][1:],
                ],
                cwd=self.root,
                env=self.request["env"],
                capture_output=True,
                timeout=30,
            )
            self.assertEqual(run.returncode, 0, run.stderr.decode())
            outputs.append((run.stdout, run.stderr))
        self.assertEqual(outputs[0], outputs[1])


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
        self.assert_refused("Symlink in Lake srcDir")

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
        self.assert_refused("Symlink in Lake input target")

    def test_project_inputs_are_returned_as_relative_source_requirements(self):
        (self.root / "src").mkdir()
        (self.root / "native.o").write_bytes(b"native input")
        self.lean_config(
            'input_file native where\n  path := "native.o"\nlean_lib Review where\n  srcDir := "src"\n'
        )
        result = discover(self.request)
        self.assertTrue(result["ok"], result)
        self.assertEqual(
            {
                key: result["sourceRequirements"][key]
                for key in ("directories", "files")
            },
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
            {
                key: result["sourceRequirements"][key]
                for key in ("directories", "files")
            },
            {"directories": ["."], "files": []},
        )

    def test_application_directory_refuses_symlink_before_parent_traversal(self):
        self.toml()
        outside = self.base / "external/nested"
        outside.mkdir(parents=True)
        (self.root / "link").symlink_to(outside, target_is_directory=True)
        lake = self.request["subject"][0]
        for spelling in ("link/..", "link/../project"):
            with self.subTest(directory=spelling):
                self.request["applications"] = [
                    {"subject": [lake, "-d", spelling, "build"], "cwd": str(self.root)}
                ]
                self.assert_refused("Symlink in Lake working directory")
        self.request["applications"] = [
            {"subject": [lake, "-d", ".", "build"], "cwd": str(self.root)}
        ]
        result = discover(self.request)
        self.assertTrue(result["ok"], result)

    def test_nearer_pin_beats_ancestor_elan_override_and_same_directory_override_wins(
        self,
    ):
        self.toml()
        launchers = self.elan_launcher()
        self.request["subject"] = [str(launchers / "lake"), "build"]
        (self.root / "lean-toolchain").write_text("review-b\n")
        settings = launchers.parent / "settings.toml"
        settings.write_text(
            'version = "12"\n[overrides]\n'
            + json.dumps(str(self.base))
            + ' = "review-a"\n'
        )
        result = discover(self.request)
        self.assertTrue(result["ok"], result)
        metadata = [p for p in result["discovery"] if "--run" in p["command"]]
        self.assertEqual(metadata[0]["command"][1:4], ["run", "review-b", "lean"])
        settings.write_text(
            'version = "12"\n[overrides]\n'
            + json.dumps(str(self.root))
            + ' = "review-a"\n'
        )
        result = discover(self.request)
        self.assertTrue(result["ok"], result)
        metadata = [p for p in result["discovery"] if "--run" in p["command"]]
        self.assertEqual(metadata[0]["command"][1:4], ["run", "review-a", "lean"])

    def test_custom_facets_and_unreviewed_lake_fields_are_refused(self):
        for body in (
            "library_facet gate : Unit := pure ()\nlean_lib Review\n",
            "module_facet gate : Unit := pure ()\nlean_lib Review\n",
            "package_facet gate : Unit := pure ()\nlean_lib Review\n",
            "target gate : Unit := pure ()\nlean_lib Review\n",
            "script gate := pure 0\nlean_lib Review\n",
            *(
                "lean_lib Review where\n  " + field + " := #[]\n"
                for field in (
                    "plugins",
                    "dynlibs",
                    "needs",
                    "defaultFacets",
                    "nativeFacets",
                    "unknownFutureField",
                )
            ),
        ):
            with self.subTest(body=body):
                self.lean_config(body)
                self.assert_refused("Unsupported Lake configuration construct")
        (self.root / "lakefile.lean").unlink()
        for field in (
            "plugins",
            "dynlibs",
            "needs",
            "defaultFacets",
            "nativeFacets",
            "unknownFutureField",
        ):
            with self.subTest(toml_field=field):
                self.toml(target=field + " = []\n")
                self.assert_refused("Unsupported Lake configuration key")

    def test_all_package_override_cli_forms_are_refused(self):
        self.toml()
        lake = self.request["subject"][0]
        for args in (
            ["build", "--packages=/outside/p.json"],
            ["--packages", "/outside/p.json", "build"],
            ["--packages /outside/p.json", "build"],
            ["--packages", "build"],
            ["-U", "build"],
            ["--update", "build"],
            ["-d=../outside", "build"],
            ["--dir ../outside", "build"],
            ["-f=other.lean", "build"],
            ["-Kunknown=value", "build"],
            ["--future-option", "build"],
            ["env", "lean", "Check.lean"],
        ):
            with self.subTest(args=args):
                self.request["subject"] = [lake, *args]
                self.assert_refused("Unsupported Lake application argument")

    def test_default_and_custom_lake_package_overrides_files_are_refused(self):
        self.toml()
        for lake_directory in (".lake", "custom-lake"):
            with self.subTest(directory=lake_directory):
                directory = self.root / lake_directory
                directory.mkdir(exist_ok=True)
                file = directory / "package-overrides.json"
                file.write_text('{"packages":[]}')
                if lake_directory == "custom-lake":
                    self.toml(package='lakeDir = "custom-lake"\n')
                    self.assert_refused("Unsupported Lake configuration key")
                else:
                    self.assert_refused("Unsupported Lake package overrides")
                file.unlink()

    def test_srcdir_parent_traversal_after_symlink_and_internal_alias_refuse(self):
        (self.root / "src").mkdir()
        (self.root / "link").symlink_to(self.root / "src", target_is_directory=True)
        for value in ("link", "link/../src"):
            with self.subTest(value=value):
                self.toml(target='srcDir = "' + value + '"\n')
                self.assert_refused("Symlink in Lake srcDir")

    def test_path_package_parent_traversal_after_symlink_refuses(self):
        (self.root / "src").mkdir()
        (self.root / "link").symlink_to(self.root / "src", target_is_directory=True)
        self.toml(package='[[require]]\nname = "dep"\npath = "link/../dep"\n')
        (self.root / "lake-manifest.json").write_text(
            json.dumps(
                {
                    "version": "1.2.0",
                    "name": "Review",
                    "packagesDir": ".lake/packages",
                    "packages": [{"name": "dep", "type": "path", "dir": "link/../dep"}],
                }
            )
        )
        self.assert_refused("Symlink in Lake package path")
        (self.root / "lake-manifest.json").write_text(
            json.dumps(
                {
                    "version": "1.2.0",
                    "name": "Review",
                    "packagesDir": "link/../cache",
                    "packages": [{"name": "dep", "type": "git", "rev": "0" * 40}],
                }
            )
        )
        self.assert_refused("Symlink in Lake package path")

    def test_input_dir_returns_all_file_requirements_separately(self):
        (self.root / "vectors").mkdir()
        (self.root / "vectors/case.json").write_text("{}")
        self.lean_config(
            'input_dir vectors where\n  path := "vectors"\nlean_lib Review\n'
        )
        result = discover(self.request)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["sourceRequirements"]["inputDirectories"], ["vectors"])
        self.assertNotIn("vectors", result["sourceRequirements"]["directories"])

    def test_effective_generated_namespaces_are_returned_for_source_walk(self):
        self.toml(package='packagesDir = "vendor"\nbuildDir = "compiled"\n')
        result = discover(self.request)
        self.assertTrue(result["ok"], result)
        self.assertTrue(
            {".git", "vendor", "compiled"}.issubset(
                result["sourceRequirements"]["excludedPaths"]
            )
        )

    def test_prebuilt_root_search_paths_are_not_generated_cache_products(self):
        self.toml()
        for relative in ("vendor", ".lake/build/lib/lean"):
            directory = self.root / relative
            (directory / "Ext").mkdir(parents=True)
            (directory / "Ext/Lemma.olean").write_bytes(
                b"unbound prebuilt proof object"
            )
            for name in ("LEAN_PATH", "LEAN_SRC_PATH"):
                with self.subTest(path=relative, environment=name):
                    self.request["env"][name] = str(directory)
                    self.assert_refused("unbound prebuilt imports")
                    self.request["env"].pop(name)
        result = discover(self.request)
        self.assertTrue(result["ok"], result)
        self.request["env"]["LEAN_PATH"] = str(self.distribution / "lib/lean")
        result = discover(self.request)
        self.assertTrue(result["ok"], result)

    def test_declared_lake_cache_admits_only_its_selected_generated_import_directory(
        self,
    ):
        self.toml()
        generated = self.root / ".lake/build/lib/lean"
        arbitrary = self.root / "vendor"
        for directory in (generated, arbitrary):
            directory.mkdir(parents=True)
            (directory / "Lemma.olean").write_bytes(b"proof object")
        self.request["applications"] = [
            {
                "subject": self.request["subject"],
                "cwd": str(self.root),
                "resources": ["lean-build"],
                "build_cache": {
                    "system": "lake",
                    "configuration": ["lake-manifest.json", "lakefile.toml"],
                    "resources": ["lean-build"],
                },
            }
        ]
        self.request["env"]["LEAN_PATH"] = str(generated)
        result = discover(self.request)
        self.assertTrue(result["ok"], result)
        self.request["env"]["LEAN_PATH"] = str(arbitrary)
        self.assert_refused("unbound prebuilt imports")
        self.request["env"]["LEAN_PATH"] = str(generated)
        self.request["checks"] = [
            {
                "subject": [str(self.distribution / "bin/lean"), "--version"],
                "cwd": str(self.root),
            }
        ]
        self.assert_refused("unbound prebuilt imports")

    def test_generated_namespaces_cannot_hide_lean_source_from_closure(self):
        for relative in ("Proofs/out", ".lake/build", "vendor"):
            with self.subTest(namespace=relative):
                self.toml(package='buildDir = "' + relative + '"\n')
                directory = self.root / relative
                directory.mkdir(parents=True, exist_ok=True)
                source = directory / "Helper.lean"
                source.write_text("def helper := 1\n")
                self.request["bound"] = []
                self.assert_refused(
                    "outside recipe closure: " + relative + "/Helper.lean"
                )
                self.request["bound"] = [relative + "/Helper.lean"]
                result = discover(self.request)
                self.assertTrue(result["ok"], result)
                self.assertIn(
                    relative + "/Helper.lean", result["sourceRequirements"]["files"]
                )
                source.unlink()
        self.request.pop("bound")

    def test_locked_package_input_directory_cannot_hide_generated_namespace_inputs(
        self,
    ):
        dependency = self.root / "dep"
        dependency.mkdir()
        (dependency / "lakefile.lean").write_text(
            "import Lake\nopen Lake DSL\npackage dep\n"
            'input_dir allInputs where\n  path := "."\nlean_lib Dep\n'
        )
        self.toml(package='[[require]]\nname = "dep"\npath = "dep"\n')
        (self.root / "lake-manifest.json").write_text(
            json.dumps(
                {
                    "version": "1.2.0",
                    "name": "Review",
                    "packagesDir": ".lake/packages",
                    "packages": [{"name": "dep", "type": "path", "dir": "dep"}],
                }
            )
        )
        self.assert_refused("input target contains an unhashed generated namespace")

    def test_default_lake_products_remain_excluded_but_other_lake_sources_are_bound(
        self,
    ):
        self.toml()
        product = self.root / ".lake/build/lib/lean/Review.olean"
        product.parent.mkdir(parents=True)
        product.write_bytes(b"Lake-generated proof object")
        (product.parent / "alias").symlink_to(product)
        self.request["bound"] = []
        result = discover(self.request)
        self.assertTrue(result["ok"], result)
        source = self.root / ".lake/User.lean"
        source.write_text("def userSource := 1\n")
        self.assert_refused("outside recipe closure: .lake/User.lean")
        self.request["bound"] = [".lake/User.lean"]
        result = discover(self.request)
        self.assertTrue(result["ok"], result)

    def test_elan_run_selector_mismatch_is_refused_for_recipes_and_checks(self):
        self.toml()
        launchers = self.elan_launcher()
        self.request["subject"] = [str(launchers / "lake"), "+review-a", "build"]
        for field in ("applications", "checks"):
            with self.subTest(field=field):
                self.request[field] = [
                    {
                        "subject": [
                            str(launchers / "elan"),
                            "run",
                            "review-b",
                            "lake",
                            "build",
                        ],
                        "cwd": str(self.root),
                    }
                ]
                self.assert_refused("selected application toolchain")
                self.request.pop(field)
        self.request["subject"] = [
            str(launchers / "elan"),
            "run",
            "review-b",
            "lake",
            "build",
        ]
        self.request["applications"] = [
            {
                "subject": [str(launchers / "lake"), "+review-a", "build"],
                "cwd": str(self.root),
            }
        ]
        self.assert_refused("selected application toolchain")

    def test_hardlinked_elan_proxies_and_matching_elan_run_are_admitted(self):
        self.toml()
        launchers = self.elan_launcher()
        elan = Path(shutil.which("elan")).resolve()
        for name in ("elan", "lake", "lean"):
            (launchers / name).unlink()
        shutil.copyfile(elan, launchers / "elan")
        (launchers / "elan").chmod(0o755)
        for name in ("lake", "lean"):
            os.link(launchers / "elan", launchers / name)
        (self.root / "Check.lean").write_text("def checked := 1\n")
        self.request["subject"] = [str(launchers / "lake"), "+review-a", "build"]
        self.request["applications"] = [
            {
                "subject": [
                    str(launchers / "elan"),
                    "run",
                    "review-a",
                    "lake",
                    "build",
                ],
                "cwd": str(self.root),
            },
            {
                "subject": [str(launchers / "lean"), "+review-a", "Check.lean"],
                "cwd": str(self.root),
            },
        ]
        result = discover(self.request)
        self.assertTrue(result["ok"], result)
        self.assertIn("Check.lean", result["sourceRequirements"]["files"])
        self.assertTrue(
            any(root["path"] == str(launchers / "lean") for root in result["roots"])
        )

    def test_direct_lean_subjects_are_required_with_and_without_lake(self):
        (self.root / "Check.lean").write_text("def checked := 1\n")
        lean = str(self.distribution / "bin/lean")
        self.toml()
        self.request["applications"] = [
            {"subject": [lean, "Check.lean"], "cwd": str(self.root)}
        ]
        result = discover(self.request)
        self.assertTrue(result["ok"], result)
        self.assertIn("Check.lean", result["sourceRequirements"]["files"])
        (self.root / "lake-manifest.json").unlink()
        (self.root / "lakefile.toml").unlink()
        self.request["subject"] = [lean, "Check.lean"]
        result = discover(self.request)
        self.assertTrue(result["ok"], result)
        self.assertIn("Check.lean", result["sourceRequirements"]["files"])
        (self.root / "Alias.lean").symlink_to(self.root / "Check.lean")
        self.request["applications"][0]["subject"] = [lean, "Alias.lean"]
        self.assert_refused("Symlink in Lean source input")

    def test_lean_and_lake_commands_without_adapter_refuse_at_discovery(self):
        for name in ("lake", "lean"):
            with self.subTest(name=name):
                request = {
                    **self.request,
                    "op": "bind",
                    "distribution": str(self.distribution),
                    "subject": [str(self.distribution / "bin" / name), "--version"],
                }
                result = discover(request)
                self.assertFalse(result["ok"], result)
                self.assertIn(
                    "Lean/Lake command requires a lean-toolchain adapter",
                    result["error"],
                )


if __name__ == "__main__":
    unittest.main()
