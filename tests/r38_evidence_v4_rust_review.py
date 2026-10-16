#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""R38 Rust discovery regressions using temporary crates and real Cargo probes.

Native-driver closure has separate coverage; this adapter boundary records the
requested drivers without executing package build scripts or proof commands.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MODULE = REPO / "tools/evidence-v4/evidence-v4-toolchain-rust.ts"
COMMON = REPO / "tools/evidence-v4/evidence-v4-toolchain-common.ts"
PROGRAM = (
    "const {discoverRustAdapter}=await import(" + json.dumps(MODULE.as_uri()) + ");\n"
    "const {ToolHasher,canonicalToolPath}=await import("
    + json.dumps(COMMON.as_uri())
    + ");\n"
    + r"""
const fs = await import('node:fs/promises');
const path = await import('node:path');
const {spawnSync} = await import('node:child_process');
const input = await Bun.stdin.json();
const probes = [];
const nativeSelections = [];
const resolveCommand = async (command, cwd=input.root) => {
  const candidates = command.includes(path.sep) ? [path.resolve(cwd,command)] : input.env.PATH.split(path.delimiter).map(entry=>path.resolve(cwd,entry,command));
  for (const invoked of candidates) {
    try { const realpath=await canonicalToolPath(invoked); await fs.access(invoked,fs.constants.X_OK); return {invoked,realpath}; }
    catch(error) { if(!['ENOENT','ENOTDIR','EACCES'].includes(error.code)) throw error; }
  }
  throw Error('Executable not found: '+command);
};
try {
  const result=await discoverRustAdapter({
    root:input.root,cwd:input.root,cwdRelative:'.',subject:input.subject,effectiveEnv:input.env,
    declaration:{locator:{mode:'adapter',value:'cargo-toolchain',cwd:'.',subject:input.subject}},
    applicationContexts:[],
    resolveCommand,
    probe:async(command,options={})=>{
      const cwd=options.cwd??input.root,env=options.env??input.env;
      const child=spawnSync(command[0],command.slice(1),{cwd,env,maxBuffer:32*1024*1024});
      if(child.error)throw child.error;
      probes.push({command,cwd,env:{PATH:env.PATH,RUSTC:env.RUSTC,CARGO_MANIFEST_DIR:env.CARGO_MANIFEST_DIR},...(command[1]==='-e'?{stdout:child.stdout.toString()}: {})});
      const identity={command,cwd:path.relative(input.root,cwd)||'.',stdout_hash:'sha256:'+new Bun.CryptoHasher('sha256').update(child.stdout).digest('hex'),stderr_hash:'sha256:'+new Bun.CryptoHasher('sha256').update(child.stderr).digest('hex'),exit_code:child.status};
      if(child.status!==0)throw Error('Probe failed: '+command.join(' ')+'\n'+child.stderr.toString());
      return {stdout:child.stdout,stderr:child.stderr,code:child.status,identity};
    },
    native:async(subject,options)=>{nativeSelections.push({subject,options});return {roots:[]};},
  });
  const files=await new ToolHasher().roots(result.roots.filter(root=>root.label.startsWith('packages/')));
  process.stdout.write(JSON.stringify({ok:true,...result,files,probes,nativeSelections}));
} catch(error) {
  process.stdout.write(JSON.stringify({ok:false,error:error instanceof Error?error.message:String(error),probes,nativeSelections}));
}
"""
)


def command(*args, cwd=None, env=None):
    result = subprocess.run(
        args, cwd=cwd, env=env, capture_output=True, text=True, timeout=60
    )
    if result.returncode:
        raise AssertionError(result.stdout + result.stderr)
    return result.stdout.strip()


class CargoFixture:
    def __init__(self, case, *, registry=False):
        self.case = case
        self.temporary = tempfile.TemporaryDirectory(prefix="fv-v4-rust-review-")
        case.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.root = self.base / "project"
        self.root.mkdir()
        self.env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(
                (
                    "CARGO_",
                    "RUST",
                    "CC",
                    "CXX",
                    "HOST_",
                    "TARGET_",
                    "AWS_LC_",
                    "SCCACHE",
                )
            )
            and key not in ("CFLAGS", "AR", "LDFLAGS")
        }
        self.env["PATH"] = (
            str(Path(case.rustc).parent)
            + os.pathsep
            + os.environ.get("PATH", "/usr/bin:/bin")
        )
        self.env["RUSTUP_AUTO_INSTALL"] = "0"
        self.env["CARGO_HOME"] = str(
            case.cargo_home if registry else self.base / "cargo-home"
        )
        self.manifest = '[package]\nname="app"\nversion="0.1.0"\nedition="2021"\n\n[workspace]\nresolver="2"\n'
        self.write("Cargo.toml", self.manifest)
        self.write("src/lib.rs", "pub fn value() -> u8 { 1 }\n")

    def write(self, name, text):
        target = self.root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        return target

    def manifest_tail(self, text):
        self.manifest += "\n" + text + "\n"
        self.write("Cargo.toml", self.manifest)

    def package(self, relative, name, *, build=None, tail="", proc_macro=False):
        manifest = f'[package]\nname="{name}"\nversion="0.1.0"\nedition="2021"\n'
        if proc_macro:
            manifest += "\n[lib]\nproc-macro=true\n"
        self.write(relative + "/Cargo.toml", manifest + "\n" + tail)
        self.write(
            relative + "/src/lib.rs",
            "pub fn value() -> u8 { 1 }\n"
            if not proc_macro
            else "extern crate proc_macro;\n",
        )
        if build is not None:
            self.write(relative + "/build.rs", build)

    def lock(self):
        command(
            self.case.cargo,
            "generate-lockfile",
            "--offline",
            cwd=self.root,
            env=self.env,
        )

    def capture(self, *args, env=None, entry=None):
        result = subprocess.run(
            [shutil.which("bun"), "--eval", PROGRAM],
            input=json.dumps(
                {
                    "root": str(self.root),
                    "subject": [entry or self.case.cargo, *(args or ("build",))],
                    "env": {**self.env, **(env or {})},
                }
            ),
            capture_output=True,
            text=True,
            timeout=90,
        )
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        return json.loads(result.stdout)


FORWARDING = r"""
use std::env;
fn main() {
    let dependency = if cfg!(feature = "provider") { "aws-lc-sys" } else { panic!("provider missing") };
    collect(dependency);
    BRANCH
}
fn collect(dependency: &str) {
    let prefix = if dependency == "aws-lc-sys" { "DEP_AWS_LC_" } else { "DEP_OTHER_" };
    let mut selected = String::default();
    let mut candidates = vec![];
    for (name, value) in std::env::vars() {
        if !selected.is_empty() {
            forward(&selected, &name, &value);
            continue;
        }
        if let Some(version) = name.strip_prefix(prefix) {
            if let Some(version) = version.strip_suffix("_INCLUDE") {
                selected = format!("{prefix}{version}_");
                forward(&selected, &name, &value);
            } else {
                candidates.push((name, value));
            }
        }
    }
    assert!(!selected.is_empty(), "missing provider metadata");
    for (name, value) in candidates {
        forward(&selected, &name, &value);
    }
}
fn forward(selected: &str, name: &str, value: &str) {
    assert!(!selected.is_empty(), "empty metadata prefix");
    if let Some(key) = name.strip_prefix(selected) {
        eprintln!("cargo:rerun-if-env-changed={name}");
        let key = key.to_lowercase();
        println!("cargo:{key}={value}");
    }
}
"""


class RustReview(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cargo = (
            command(shutil.which("rustup"), "which", "cargo")
            if shutil.which("rustup")
            else str(Path(shutil.which("cargo")).resolve())
        )
        cls.rustc = (
            command(shutil.which("rustup"), "which", "rustc")
            if shutil.which("rustup")
            else str(Path(shutil.which("rustc")).resolve())
        )
        cls.host = next(
            line.removeprefix("host: ")
            for line in command(cls.rustc, "-vV").splitlines()
            if line.startswith("host: ")
        )
        cls.sysroot = command(cls.rustc, "--print", "sysroot")
        cls.cargo_home = Path(os.environ.get("CARGO_HOME", str(Path.home() / ".cargo")))

    def assert_refused(self, result, message):
        self.assertFalse(result["ok"], result)
        self.assertIn(message, result["error"], result)
        self.assertEqual(result["nativeSelections"], [], result)

    def require_registry(self, name, version):
        if not list(
            (self.cargo_home / "registry/src").glob("*/" + name + "-" + version)
        ):
            self.skipTest(
                f"requires installed offline registry fixture {name} {version}"
            )

    def test_hardlinked_cargo_keeps_each_selected_spelling(self):
        fixture = CargoFixture(self)
        fixture.lock()
        first = fixture.base / "hardlinked-a/cargo"
        second = fixture.base / "hardlinked-b/cargo"
        dispatch = fixture.base / "dispatch/cargo"
        for filename in (first, second, dispatch):
            filename.parent.mkdir()
        first.write_text("#!/bin/sh\nexec " + json.dumps(self.cargo) + ' "$@"\n')
        first.chmod(0o755)
        os.link(first, second)
        dispatch.symlink_to(second)
        self.assertEqual(first.stat().st_ino, second.stat().st_ino)
        self.assertEqual(first.stat().st_nlink, 2)
        for selected, expected in (
            (first, first),
            (second, second),
            (dispatch, second),
            (first, first),
            (second, second),
        ):
            with self.subTest(selected=selected):
                result = fixture.capture(entry=str(selected))
                self.assertTrue(result["ok"], result)
                cargo = next(
                    root["path"] for root in result["roots"] if root["label"] == "cargo"
                )
                self.assertEqual(cargo, str(expected))
                self.assertTrue(
                    any(
                        probe["command"][0] == str(expected)
                        for probe in result["probes"]
                    )
                )

    def test_ca01_sysroot_flags_refuse_all_effective_sources(self):
        fixture = CargoFixture(self)
        fixture.lock()
        for env in (
            {"RUSTFLAGS": "--sysroot " + self.sysroot},
            {"CARGO_ENCODED_RUSTFLAGS": "--sysroot=" + self.sysroot},
        ):
            with self.subTest(env=env):
                self.assert_refused(fixture.capture(env=env), "rustflags --sysroot")
        fixture.write(
            ".cargo/config.toml",
            "[build]\nrustflags=" + json.dumps(["--sysroot", self.sysroot]) + "\n",
        )
        self.assert_refused(fixture.capture(), "rustflags --sysroot")

    def test_ca02_singular_selectors_include_dev_dependency_edges(self):
        fixture = CargoFixture(self)
        fixture.package("dev-only", "dev-only")
        fixture.manifest_tail('[dev-dependencies]\ndev-only={path="dev-only"}')
        fixture.write("examples/demo.rs", "fn main() { let _ = dev_only::value(); }\n")
        fixture.write(
            "tests/integration.rs",
            "#[test] fn test_value() { assert_eq!(dev_only::value(),1); }\n",
        )
        fixture.write("benches/perf.rs", "fn main() { let _ = dev_only::value(); }\n")
        fixture.lock()
        for selector, name in (
            ("--example", "demo"),
            ("--test", "integration"),
            ("--bench", "perf"),
        ):
            with self.subTest(selector=selector):
                result = fixture.capture("build", selector, name)
                self.assertTrue(result["ok"], result)
                self.assertIn(
                    "dev-only", [package["name"] for package in result["packages"]]
                )
                self.assertTrue(
                    any(
                        probe["command"][-1:] == ["normal,build,dev"]
                        for probe in result["probes"]
                        if probe["command"][1:2] == ["tree"]
                    ),
                    result,
                )

    def test_ca03_external_native_inputs_refuse_and_bound_inputs_hash(self):
        fixture = CargoFixture(self)
        fixture.lock()
        outside = fixture.base / "outside"
        outside.mkdir()
        header = outside / "feature.h"
        header.write_text("#define FEATURE 1\n")
        archive = outside / "libextra.a"
        archive.write_bytes(b"!<arch>\n")
        for env in (
            {"CFLAGS": "-include " + str(header)},
            {"CFLAGS": "-I" + str(outside)},
            {"RUSTFLAGS": "-C link-arg=" + str(archive)},
            {"RUSTFLAGS": "-C link-arg=-Wl,--version-script," + str(header)},
        ):
            with self.subTest(env=env):
                self.assert_refused(
                    fixture.capture(env=env),
                    "native flag input is outside hashed roots",
                )
        internal = fixture.write("native/feature.h", "#define FEATURE 1\n")
        internal_archive = fixture.write("native/libextra.a", "!<arch>\n")
        env = {
            "CFLAGS": "-include " + str(internal),
            "RUSTFLAGS": "-C link-arg=" + str(internal_archive),
        }
        before = fixture.capture(env=env)
        self.assertTrue(before["ok"], before)
        internal.write_text("#define FEATURE 2\n")
        after = fixture.capture(env=env)
        self.assertTrue(after["ok"], after)
        self.assertNotEqual(before["files"], after["files"])
        excluded = fixture.write("target/feature.h", "#define FEATURE 3\n")
        self.assert_refused(
            fixture.capture(env={"CFLAGS": "-include " + str(excluded)}),
            "native flag input is outside hashed roots",
        )

    def test_ca04_cross_target_host_native_dependencies_refuse(self):
        for proc_macro in (False, True):
            with self.subTest(proc_macro=proc_macro):
                fixture = CargoFixture(self)
                fixture.package("cc", "cc")
                fixture.package(
                    "native",
                    "ring",
                    build="fn main() { let _ = cc::value(); }\n",
                    tail='[build-dependencies]\ncc={path="../cc"}\n',
                )
                if proc_macro:
                    fixture.package(
                        "host",
                        "host-macro",
                        proc_macro=True,
                        tail='[dependencies]\nring={path="../native"}\n',
                    )
                    fixture.manifest_tail('[dependencies]\nhost-macro={path="host"}')
                else:
                    fixture.manifest_tail('[build-dependencies]\nring={path="native"}')
                    fixture.write("build.rs", "fn main() {}\n")
                fixture.lock()
                target = (
                    "x86_64-unknown-linux-gnu"
                    if self.host != "x86_64-unknown-linux-gnu"
                    else "aarch64-unknown-linux-gnu"
                )
                self.assert_refused(
                    fixture.capture("build", "--target", target),
                    "distinct host context",
                )

    def test_ca05_unknown_command_forms_refuse(self):
        scripts = (
            'fn main() { let tool="/opt/fixture-helper"; std::process::Command::new(tool).status().unwrap(); }',
            'use std::process::Command as Run; fn main() { Run::new("/opt/fixture-helper").status().unwrap(); }',
            'fn helper(name: &str) { std::process::Command::new(name).status().unwrap(); } fn main() { helper("/opt/fixture-helper"); }',
            "mod helper; fn main() { helper::run(); }",
            'use std::process::Command; fn main() { let make=Command::new; make("/opt/fixture-helper").status().unwrap(); }',
            'macro_rules! cfg { ($($t:tt)*) => { true } } fn query() -> Option<()> { let tool=if cfg!(target_os="windows") { "fv-r38-shadow-one" } else { "fv-r38-shadow-two" }; let _ = std::process::Command::new(tool).output().ok()?; Some(()) } fn main() { query(); }',
            'mod env { pub fn var_os(_: &str) -> Option<&str> { Some("/opt/unbound-rustc") } } fn query() -> Option<()> { let rustc=env::var_os("RUSTC")?; let _ = std::process::Command::new(rustc).arg("--version").output().ok()?; Some(()) } fn main() { query(); }',
        )
        for script in scripts:
            with self.subTest(script=script):
                fixture = CargoFixture(self)
                fixture.write("build.rs", script)
                fixture.write(
                    "helper.rs",
                    'pub fn run() { std::process::Command::new("/opt/fixture-helper").status().unwrap(); }',
                )
                fixture.lock()
                result = fixture.capture()
                self.assertFalse(result["ok"], result)
                self.assertIn("build-script process", result["error"])
                self.assertEqual(result["nativeSelections"], [])

    def test_ca05_same_name_path_providers_and_source_linkage_refuse(self):
        fixture = CargoFixture(self)
        fixture.manifest = fixture.manifest.replace('name="app"', 'name="ring"')
        fixture.write("Cargo.toml", fixture.manifest)
        fixture.package("cc", "cc")
        fixture.write(
            "cc/src/lib.rs",
            "pub struct Build; impl Build { pub fn new() -> Self { Self } pub fn compiler(&mut self, _: &str) -> &mut Self { self } }",
        )
        fixture.manifest_tail('[build-dependencies]\ncc={path="cc"}')
        fixture.write(
            "build.rs", 'fn main() { cc::Build::new().compiler("/opt/unbound-cc"); }'
        )
        fixture.lock()
        self.assert_refused(
            fixture.capture(), "unresolved native build-script compiler selection"
        )
        linked = CargoFixture(self)
        linked.write(
            "src/lib.rs",
            '#[link(name="unbound_vendor",kind="static")] extern "C" { pub fn vendor(); }\n',
        )
        linked.lock()
        self.assert_refused(linked.capture(), "Rust-source native linkage")
        framework = CargoFixture(self)
        framework.manifest = framework.manifest.replace(
            'name="app"', 'name="system-configuration-sys"'
        ).replace('edition="2021"', 'edition="2021"\nlinks="forged"')
        framework.write("Cargo.toml", framework.manifest)
        framework.write(
            "build.rs", 'fn main() { let _ = std::fs::read("/opt/unbound-input"); }'
        )
        framework.lock()
        self.assert_refused(framework.capture(), "unresolved native linkage")

    def test_ca05_literal_rustc_must_match_selected_rustc(self):
        fixture = CargoFixture(self)
        fixture.write(
            "build.rs",
            'use std::process::Command; fn query() -> Option<()> { let _ = Command::new("rustc").arg("--version").output().ok()?; Some(()) } fn main() { query(); }',
        )
        selected = fixture.base / "selected-rustc"
        selected.write_text("#!/bin/sh\nexec " + json.dumps(self.rustc) + ' "$@"\n')
        selected.chmod(0o755)
        fixture.lock()
        self.assert_refused(
            fixture.capture(env={"RUSTC": str(selected)}), "literal rustc differs"
        )

    def test_ca06_aliased_lookup_environment_mutation_refuses(self):
        fixture = CargoFixture(self)
        fixture.write(
            "build.rs",
            'use std::env::set_var as change; fn query() -> Option<()> { change("PATH", "/opt/unbound-tools"); let _ = std::process::Command::new("fv-r38-optional-helper").output().ok()?; Some(()) } fn main() { query(); }',
        )
        fixture.lock()
        self.assert_refused(fixture.capture(), "optional process lookup is changed")

    def test_ca06_optional_absence_uses_package_cwd_and_reprobes(self):
        for entry in ("../helpers", ""):
            with self.subTest(entry=entry):
                fixture = CargoFixture(self)
                name = "fv-r38-optional-helper"
                fixture.package(
                    "nested/member",
                    "member",
                    build=f'use std::process::Command; fn query() -> Option<()> {{ let _ = Command::new("{name}").output().ok()?; Some(()) }} fn main() {{ query(); }}',
                )
                fixture.manifest_tail('[dependencies]\nmember={path="nested/member"}')
                fixture.lock()
                env = {"PATH": entry + os.pathsep + fixture.env["PATH"]}
                before = fixture.capture(env=env)
                self.assertTrue(before["ok"], before)
                lookup = [
                    probe
                    for probe in before["probes"]
                    if probe["command"][1:2] == ["-e"]
                ]
                self.assertEqual(len(lookup), 1, before)
                self.assertEqual(Path(lookup[0]["cwd"]), fixture.root / "nested/member")
                self.assertEqual(
                    lookup[0]["env"]["CARGO_MANIFEST_DIR"],
                    str(fixture.root / "nested/member"),
                )
                observation = json.loads(lookup[0]["stdout"])
                self.assertEqual(
                    observation["cwd_hash"],
                    "sha256:"
                    + hashlib.sha256(
                        str(fixture.root / "nested/member").encode()
                    ).hexdigest(),
                )
                self.assertEqual(
                    observation["path_hash"],
                    "sha256:" + hashlib.sha256(env["PATH"].encode()).hexdigest(),
                )
                self.assertEqual(
                    len(observation["candidates"]), len(env["PATH"].split(os.pathsep))
                )
                self.assertTrue(
                    all(
                        candidate["absent"] is True
                        for candidate in observation["candidates"]
                    )
                )
                helper_dir = fixture.root / (
                    "nested/helpers" if entry else "nested/member"
                )
                helper_dir.mkdir(parents=True, exist_ok=True)
                helper = helper_dir / name
                marker = fixture.base / "optional-helper-executed"
                helper.write_text(
                    "#!/bin/sh\nprintf ran > " + json.dumps(str(marker)) + "\nexit 0\n"
                )
                helper.chmod(0o755)
                result = fixture.capture(env=env)
                self.assertFalse(
                    marker.exists(), "discovery executed the optional helper"
                )
                self.assertFalse(result["ok"], result)
                self.assertIn("optional executable", result["error"])
                self.assertEqual(result["nativeSelections"], [])

    def test_ca06_external_package_relative_and_empty_path_refuse(self):
        self.require_registry("libc", "0.2.186")
        fixture = CargoFixture(self, registry=True)
        fixture.manifest_tail('[dependencies]\nlibc="=0.2.186"')
        fixture.lock()
        for entry in ("../helpers", ""):
            with self.subTest(entry=entry):
                self.assert_refused(
                    fixture.capture(
                        env={"PATH": entry + os.pathsep + fixture.env["PATH"]}
                    ),
                    "requires absolute nonempty PATH",
                )

    def test_ca07_only_complete_false_conditions_eliminate_branches(self):
        self.require_registry("aws-lc-sys", "0.44.0")
        for name, version in (
            ("libc", "0.2.186"),
            ("find-msvc-tools", "0.1.9"),
            ("jobserver", "0.1.34"),
        ):
            self.require_registry(name, version)
        fixture = CargoFixture(self, registry=True)
        fixture.manifest = fixture.manifest.replace(
            'edition="2021"', 'edition="2021"\nlinks="wrapper"'
        )
        fixture.write("Cargo.toml", fixture.manifest)
        fixture.manifest_tail(
            '[features]\ndefault=["provider"]\nprovider=[]\n[dependencies]\naws-lc-sys="=0.44.0"\nlibc="=0.2.186"\nfind-msvc-tools="=0.1.9"\njobserver="=0.1.34"'
        )
        fixture.write("build.rs", FORWARDING.replace("BRANCH", ""))
        fixture.lock()
        atom = 'env::var("CARGO_CFG_TARGET_OS").as_deref() == Ok("windows")'
        payload = 'let bytes = std::fs::read("/opt/provider-input").unwrap(); assert!(bytes.is_empty());'
        for condition in (
            f"({atom}) == false",
            f"(({atom}) == false) == true",
            f"({atom}) != true",
            f"({atom}) & false",
        ):
            with self.subTest(condition=condition):
                fixture.write(
                    "build.rs",
                    FORWARDING.replace("BRANCH", f"if {condition} {{ {payload} }}"),
                )
                self.assert_refused(
                    fixture.capture(), "unresolved native linkage in app"
                )
        fixture.write(
            "build.rs", FORWARDING.replace("BRANCH", f"if {atom} {{ {payload} }}")
        )
        result = fixture.capture()
        self.assertTrue(result["ok"], result)

    def test_ca08_incremental_target_and_bench_profile_selection(self):
        fixture = CargoFixture(self)
        fixture.lock()
        for operation, extra, profile in (
            ("bench", (), "release"),
            ("build", ("--profile", "bench"), "release"),
            ("build", ("--profile", "test"), "debug"),
        ):
            with self.subTest(operation=operation, extra=extra):
                result = fixture.capture(operation, *extra)
                self.assertTrue(result["ok"], result)
                selected = next(
                    item["path"]
                    for item in result["cacheNamespaces"]
                    if item["role"] == "cargo-incremental"
                )
                self.assertEqual(
                    Path(selected), fixture.root / "target" / profile / "incremental"
                )
        for source in ("cli", "env", "config"):
            with self.subTest(source=source):
                fixture.write(
                    ".cargo/config.toml",
                    "[build]\ntarget=" + json.dumps(self.host) + "\n"
                    if source == "config"
                    else "",
                )
                result = fixture.capture(
                    "build",
                    *(("--target", self.host) if source == "cli" else ()),
                    env={"CARGO_BUILD_TARGET": self.host} if source == "env" else {},
                )
                self.assertTrue(result["ok"], result)
                selected = next(
                    item["path"]
                    for item in result["cacheNamespaces"]
                    if item["role"] == "cargo-incremental"
                )
                self.assertEqual(
                    Path(selected),
                    fixture.root / "target" / self.host / "debug" / "incremental",
                )
        fixture.manifest_tail('[profile.review]\ninherits="release"')
        custom = fixture.capture("build", "--profile", "review")
        self.assertTrue(custom["ok"], custom)
        selected = next(
            item["path"]
            for item in custom["cacheNamespaces"]
            if item["role"] == "cargo-incremental"
        )
        self.assertEqual(
            Path(selected),
            fixture.root / "target" / self.host / "review" / "incremental",
        )


if __name__ == "__main__":
    if not all(shutil.which(name) for name in ("bun", "cargo", "rustc")):
        print("INCOMPLETE: R38 Rust review regressions require Bun, Cargo and rustc")
        sys.exit(2)
    unittest.main(verbosity=2)
