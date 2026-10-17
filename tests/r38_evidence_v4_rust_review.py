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
    declaration:{locator:{mode:'adapter',value:input.adapter??'cargo-toolchain',cwd:'.',subject:input.subject}},
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

    def kani(self):
        home = Path(self.env["CARGO_HOME"])
        distribution = self.base / "kani"
        (distribution / "toolchain").parent.mkdir()
        (distribution / "toolchain").symlink_to(self.case.sysroot)
        (distribution / "rust-toolchain-version").write_text(
            Path(self.case.sysroot).name
        )
        (distribution / "rustc-version").write_text(
            command(self.case.rustc, "--version")
        )
        for directory in ("lib", "library", "no_core", "playback"):
            (distribution / directory).mkdir()
        for filename in (
            home / "bin/cargo-kani",
            *(
                distribution / "bin" / name
                for name in (
                    "kani-driver",
                    "kani-compiler",
                    "cbmc",
                    "goto-cc",
                    "goto-instrument",
                    "goto-analyzer",
                    "kissat",
                )
            ),
        ):
            filename.parent.mkdir(parents=True, exist_ok=True)
            filename.write_text("#!/bin/sh\nprintf 'kani 0.0.0\\n'\n")
            filename.chmod(0o755)
        (home / ".crates2.json").write_text(
            json.dumps(
                {
                    "installs": {
                        "kani-verifier 0.0.0 (registry+https://github.com/rust-lang/crates.io-index)": {
                            "bins": ["cargo-kani"]
                        }
                    }
                }
            )
        )
        self.env["KANI_HOME"] = str(distribution)
        self.env["PATH"] = str(home / "bin") + os.pathsep + self.env["PATH"]
        return home / "bin/cargo-kani"

    def capture(self, *args, env=None, entry=None, adapter="cargo-toolchain"):
        result = subprocess.run(
            [shutil.which("bun"), "--eval", PROGRAM],
            input=json.dumps(
                {
                    "root": str(self.root),
                    "subject": [entry or self.case.cargo, *(args or ("build",))],
                    "adapter": adapter,
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
            {"CARGO_BUILD_RUSTFLAGS": "--sysroot=" + self.sysroot},
            {
                "CARGO_TARGET_"
                + self.host.upper().replace("-", "_")
                + "_RUSTFLAGS": "--sysroot=" + self.sysroot
            },
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
        ):
            with self.subTest(env=env):
                self.assert_refused(
                    fixture.capture(env=env),
                    "native flag input is outside hashed roots",
                )
        internal = fixture.write("native/feature.h", "#define FEATURE 1\n")
        env = {
            "CFLAGS": "-include " + str(internal),
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
        self.assert_refused(framework.capture(), "unreviewed build-script")

    def test_ca05_literal_rustc_scripts_require_review(self):
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
            fixture.capture(env={"RUSTC": str(selected)}), "unreviewed build-script"
        )

    def test_ca06_unreviewed_lookup_mutation_refuses(self):
        fixture = CargoFixture(self)
        fixture.write(
            "build.rs",
            'use std::env::set_var as change; fn query() -> Option<()> { change("PATH", "/opt/unbound-tools"); let _ = std::process::Command::new("fv-r38-optional-helper").output().ok()?; Some(()) } fn main() { query(); }',
        )
        fixture.lock()
        self.assert_refused(fixture.capture(), "unreviewed build-script")

    def test_ca06_unreviewed_optional_absence_scripts_never_execute(self):
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
                self.assert_refused(before, "unreviewed build-script")
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
                self.assertIn("unreviewed build-script", result["error"])
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

    def test_ca07_unreviewed_forwarding_scripts_refuse_even_false_branches(self):
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
                self.assert_refused(fixture.capture(), "unreviewed build-script")
        fixture.write(
            "build.rs", FORWARDING.replace("BRANCH", f"if {atom} {{ {payload} }}")
        )
        result = fixture.capture()
        self.assert_refused(result, "unreviewed build-script")

    def test_r2_ca01_all_rustflags_and_rustdocflags_sources_refuse(self):
        fixture = CargoFixture(self)
        fixture.lock()
        target = "CARGO_TARGET_" + self.host.upper().replace("-", "_")
        for name in (
            "RUSTFLAGS",
            "CARGO_ENCODED_RUSTFLAGS",
            "CARGO_BUILD_RUSTFLAGS",
            target + "_RUSTFLAGS",
            "RUSTDOCFLAGS",
            "CARGO_ENCODED_RUSTDOCFLAGS",
            "CARGO_BUILD_RUSTDOCFLAGS",
            target + "_RUSTDOCFLAGS",
        ):
            for flags in ("--sysroot=/opt/alt-rust", "-L/opt/vendor", "--cfg=unbound"):
                with self.subTest(name=name, flags=flags):
                    self.assert_refused(
                        fixture.capture(env={name: flags}),
                        "Rust toolchain attestation:",
                    )
        for table in ("build", "target." + self.host):
            for name in ("rustflags", "rustdocflags"):
                with self.subTest(table=table, name=name):
                    fixture.write(
                        ".cargo/config.toml",
                        f'[{table}]\n{name}=["--extern","unbound=/opt/unbound.rlib"]\n',
                    )
                    self.assert_refused(fixture.capture(), "unsupported " + name)

    def test_r2_ca02_allowlist_normalizes_codegen_forms(self):
        fixture = CargoFixture(self)
        fixture.lock()
        for flags in (
            "--codegen link-arg=/opt/vendor.a",
            "--codegen=linker=/opt/ld",
            "-Cprofile-use=/opt/pgo.profdata",
            "-C profile-use=/opt/pgo.profdata",
            "--extern unbound=/opt/unbound.rlib",
            "-Zcodegen-backend=/opt/backend.so",
            "-Clinker-plugin-lto=/opt/plugin",
            "-Ctarget-feature=+crt-static",
            '--cfg=target_os="windows"',
            "-C",
            "--codegen",
            "--unknown-reviewed-later",
        ):
            with self.subTest(flags=flags):
                self.assert_refused(
                    fixture.capture(env={"RUSTFLAGS": flags}),
                    "unsupported rustflags token",
                )
        for flags in (
            "-C link-arg=--allow-undefined",
            "-Clink-arg=--allow-undefined",
            "--codegen link-arg=--allow-undefined",
            "--codegen=link-arg=--allow-undefined",
        ):
            with self.subTest(allowed=flags):
                result = fixture.capture(
                    "build",
                    "--target",
                    "wasm32-unknown-unknown",
                    env={"RUSTFLAGS": flags},
                )
                self.assertTrue(result["ok"], result)
                self.assert_refused(
                    fixture.capture(env={"RUSTFLAGS": flags}),
                    "unsupported rustflags token",
                )

    def test_r2_ca03_configured_host_linkers_refuse_with_cross_target(self):
        fixture = CargoFixture(self)
        fixture.lock()
        foreign = (
            "x86_64-unknown-linux-gnu"
            if self.host != "x86_64-unknown-linux-gnu"
            else "aarch64-unknown-linux-gnu"
        )
        key = "CARGO_TARGET_" + self.host.upper().replace("-", "_") + "_LINKER"
        self.assert_refused(
            fixture.capture("build", "--target", foreign, env={key: "/opt/host-ld"}),
            "Cargo host linker",
        )
        fixture.write(
            ".cargo/config.toml", f'[target.{self.host}]\nlinker="/opt/host-ld"\n'
        )
        self.assert_refused(
            fixture.capture("build", "--target", foreign), "Cargo host linker"
        )
        self.assert_refused(fixture.capture(), "Cargo host linker")

    def test_r2_ca04_runner_environment_and_configuration_refuse(self):
        fixture = CargoFixture(self)
        fixture.lock()
        for operation in ("test", "run", "bench"):
            with self.subTest(operation=operation):
                key = "CARGO_TARGET_" + self.host.upper().replace("-", "_") + "_RUNNER"
                self.assert_refused(
                    fixture.capture(operation, env={key: "/opt/runner"}),
                    "Cargo target runner",
                )
        for runner in ('"/opt/runner"', '["/opt/runner","--skip-tests"]'):
            fixture.write(
                ".cargo/config.toml", f"[target.{self.host}]\nrunner={runner}\n"
            )
            self.assert_refused(fixture.capture("test"), "Cargo target runner")

    def test_r2_ca05_unreviewed_library_and_file_effects_refuse(self):
        for source in (
            "fn main() { helper::run(); }",
            'fn main() { let b=std::fs::read("/opt/input").unwrap(); assert!(b.is_empty()); }',
            "fn main() {}",
        ):
            with self.subTest(source=source):
                fixture = CargoFixture(self)
                fixture.package("helper", "helper")
                fixture.write(
                    "helper/src/lib.rs",
                    'pub fn run() { std::process::Command::new("/opt/tool").status().unwrap(); }',
                )
                fixture.manifest_tail('[build-dependencies]\nhelper={path="helper"}')
                fixture.write("build.rs", source)
                fixture.lock()
                self.assert_refused(
                    fixture.capture(), "unreviewed build-script process/input closure"
                )

    def test_r2_ca05_reviewed_script_refuses_unreviewed_build_helper(self):
        self.require_registry("generic-array", "0.14.7")
        fixture = CargoFixture(self, registry=True)
        fixture.package("helper", "version_check")
        fixture.write(
            "helper/Cargo.toml",
            '[package]\nname="version_check"\nversion="0.9.5"\nedition="2021"\n',
        )
        fixture.manifest_tail(
            '[dependencies]\ngeneric-array="=0.14.7"\n[patch.crates-io]\nversion_check={path="helper"}'
        )
        fixture.lock()
        self.assert_refused(
            fixture.capture(), "unreviewed build-script dependency version_check"
        )

    def test_r2_ca06_relative_link_arguments_refuse(self):
        fixture = CargoFixture(self)
        fixture.write("native/libextra.a", "!<arch>\n")
        fixture.lock()
        for flags in (
            "-Clink-arg=native/libextra.a",
            "--codegen=link-arg=native/libextra.a",
            "-Clink-args=native/libextra.a",
        ):
            with self.subTest(flags=flags):
                self.assert_refused(
                    fixture.capture(env={"CARGO_BUILD_RUSTFLAGS": flags}),
                    "unsupported rustflags token",
                )

    def test_r2_ca07_inclusions_refuse_external_and_generated_unknown_sources(self):
        for operand in ('"/opt/keys/k.bin"', '"../../outside"', 'r#"/opt/keys/k.bin"#'):
            for form in (
                "include_bytes!({})",
                "include_str!({})",
                "include!({})",
                "#[path={}] mod outside;",
            ):
                with self.subTest(operand=operand, form=form):
                    fixture = CargoFixture(self)
                    fixture.write("src/lib.rs", form.format(operand))
                    fixture.lock()
                    self.assert_refused(
                        fixture.capture(), "Rust source inclusion is outside"
                    )
        fixture = CargoFixture(self)
        fixture.write("src/lib.rs", 'pub const DATA: &str = include_str!("data.txt");')
        fixture.write("src/data.txt", "one")
        fixture.lock()
        before = fixture.capture()
        self.assertTrue(before["ok"], before)
        fixture.write("src/data.txt", "two")
        after = fixture.capture()
        self.assertTrue(after["ok"], after)
        self.assertNotEqual(before["files"], after["files"])
        for source in (
            'const DATA: &[u8] = include_bytes!(concat!(env!("UNBOUND"), "/data"));',
            'const DATA: &[u8] = include_bytes!(concat!("/opt/", "data"));',
            '#[cfg_attr(unix, path="../../outside.rs")] mod outside;',
            'const DATA: &[u8] = zerocopy::include_value!("/opt/data");',
            '#[cfg(test)] mod tests { const DATA: &[u8] = include_bytes!("/opt/test-data"); }',
            '#[cfg_attr(serde_build_from_git, path="../../outside.rs")] mod outside;',
            'use zerocopy::include_value as read; const DATA: &[u8] = read!("/opt/input");',
        ):
            with self.subTest(source=source):
                fixture.write("src/lib.rs", source)
                self.assert_refused(fixture.capture(), "Rust")
        fixture.write(
            "src/lib.rs", 'pub const DATA: &str = include_str!("/opt/input");'
        )
        fixture.write("build.rs", "fn main() {}")
        self.assert_refused(fixture.capture(), "Rust source inclusion is outside")

    def test_r2_ca07_nested_non_rs_sources_are_scanned(self):
        fixture = CargoFixture(self)
        fixture.write("src/data.txt", "bound")
        fixture.write("src/code.txt", 'const DATA: &str = include_str!("data.txt");')
        fixture.lock()
        for root in ('include!("code.txt");', '#[path="code.txt"] mod code;'):
            with self.subTest(root=root):
                fixture.write("src/lib.rs", root)
                fixture.write(
                    "src/code.txt", 'const DATA: &str = include_str!("data.txt");'
                )
                self.assertTrue(fixture.capture()["ok"])
                fixture.write(
                    "src/code.txt", 'const DATA: &str = include_str!("/opt/unbound");'
                )
                self.assert_refused(
                    fixture.capture(), "Rust source inclusion is outside"
                )
                fixture.write(
                    "src/code.txt", 'const DATA: &str = include_str!(env!("UNBOUND"));'
                )
                self.assert_refused(
                    fixture.capture(), "unreviewed dynamic included Rust source"
                )

    def test_r2_ca07_inactive_source_reviews_require_registry_identity(self):
        for name, version, source in (
            ("cosmwasm-std", "3.0.7", "src/testing/mock.rs"),
            ("serde_derive_internals", "0.29.1", "lib.rs"),
        ):
            with self.subTest(name=name):
                self.require_registry(name, version)
                fixture = CargoFixture(self)
                fixture.manifest = fixture.manifest.replace(
                    'name="app"', f'name="{name}"'
                ).replace('version="0.1.0"', f'version="{version}"')
                fixture.write("Cargo.toml", fixture.manifest)
                installed = next(
                    (self.cargo_home / "registry/src").glob("*/" + name + "-" + version)
                )
                fixture.write(source, (installed / source).read_text())
                fixture.lock()
                self.assert_refused(
                    fixture.capture(), "Rust source inclusion is outside"
                )

    def test_r2_ca08_cfg_mutations_and_unknown_cargo_configuration_refuse(self):
        fixture = CargoFixture(self)
        fixture.lock()
        for name in ("RUSTFLAGS", "CARGO_BUILD_RUSTFLAGS"):
            self.assert_refused(
                fixture.capture(
                    env={
                        name: '--cfg target_os="windows" -Aexplicit_builtin_cfgs_in_flags'
                    }
                ),
                "unsupported rustflags token",
            )
        self.assert_refused(
            fixture.capture(env={"CARGO_UNSTABLE_HOST_CONFIG": "true"}),
            "unstable Cargo environment",
        )
        self.assert_refused(
            fixture.capture(env={"CARGO_BUILD_UNKNOWN": "true"}),
            "unsupported Cargo build environment",
        )
        self.assert_refused(
            fixture.capture(env={"CARGO_PROFILE_DEV_RUSTFLAGS": "--cfg=unbound"}),
            "Cargo profile environment",
        )
        self.assert_refused(
            fixture.capture("test", env={"RUSTDOC": "/opt/skipped-doctests"}),
            "configured rustdoc",
        )
        fixture.write(".cargo/config.toml", '[build]\nunknown="unbound"\n')
        self.assert_refused(fixture.capture(), "unsupported Cargo build configuration")
        for selector in ("cfg(unix)", "cfg (unix)", "cfg\t(unix)"):
            fixture.write(
                ".cargo/config.toml",
                "[target." + json.dumps(selector) + ']\nlinker="/opt/unbound"\n',
            )
            self.assert_refused(
                fixture.capture(), "unsupported Cargo target selection key"
            )

    def test_r2_dossier_link_variables_are_not_native_attributes(self):
        fixture = CargoFixture(self)
        fixture.write(
            "src/lib.rs",
            "pub fn copy(link: &str) { let link = link.to_owned(); drop(link); }\n",
        )
        fixture.lock()
        result = fixture.capture()
        self.assertTrue(result["ok"], result)
        fixture.write(
            "src/lib.rs",
            '#[cfg_attr(unix, link(name="unbound_vendor", kind="static"))] extern "C" {}\n',
        )
        self.assert_refused(fixture.capture(), "Rust-source native linkage")

    def test_r3_ca06_aliases_refuse_before_any_probe(self):
        fixture = CargoFixture(self)
        fixture.lock()
        for config in ('[alias]\nkani=["run"]\n', "[alias]\n"):
            fixture.write(".cargo/config.toml", config)
            result = fixture.capture()
            self.assert_refused(result, "Cargo alias configuration")
            self.assertEqual(result["probes"], [])
        fixture.write(".cargo/config.toml", "")
        fixture.write("ci/cargo.toml", '[alias]\nkani="run"\n')
        for argument in ("ci/cargo.toml", 'alias.kani="run"'):
            self.assert_refused(
                fixture.capture("build", "--config", argument),
                "Cargo alias configuration",
            )
        for name, value in (("CARGO_ALIAS_KANI", "run"), ("CARGO_ALIAS_OTHER", "")):
            result = fixture.capture(env={name: value})
            self.assert_refused(result, "Cargo alias environment")
            self.assertEqual(result["probes"], [])

    def test_r3_ca06_cargo_home_launcher_precedence_matches_cargo(self):
        fixture = CargoFixture(self)
        fixture.lock()
        home_launcher = fixture.kani()
        path_launcher = fixture.base / "path-bin/cargo-kani"
        path_launcher.parent.mkdir()
        path_launcher.write_text("#!/bin/sh\nprintf 'kani 0.0.0\\n'\n")
        path_launcher.chmod(0o755)
        original = fixture.env["PATH"].split(os.pathsep, 1)[1]
        path_only = str(path_launcher.parent) + os.pathsep + original
        result = fixture.capture(
            "kani", adapter="kani-toolchain", env={"PATH": path_only}
        )
        self.assert_refused(result, "Cargo-selected cargo-kani differs")
        self.assertEqual(result["probes"], [])
        for search, expected in (
            (fixture.env["PATH"], home_launcher),
            (
                str(path_launcher.parent) + os.pathsep + fixture.env["PATH"],
                path_launcher,
            ),
        ):
            with self.subTest(search=search):
                result = fixture.capture(
                    "kani", adapter="kani-toolchain", env={"PATH": search}
                )
                self.assertTrue(result["ok"], result)
                launcher = next(
                    root["path"]
                    for root in result["roots"]
                    if root["label"] == "config/kani-launcher"
                )
                self.assertEqual(launcher, str(expected))
        home_launcher.chmod(0o644)
        result = fixture.capture(
            "kani", adapter="kani-toolchain", env={"PATH": path_only}
        )
        self.assertTrue(result["ok"], result)
        home_launcher.chmod(0o755)
        for env in (
            {"CARGO_HOME": str(home_launcher.parent.parent) + "/../cargo-home"},
            {"PATH": path_only + os.pathsep + str(fixture.base / "unused/../bin")},
        ):
            self.assert_refused(
                fixture.capture("kani", adapter="kani-toolchain", env=env),
                "parent-traversing Cargo subcommand search paths",
            )

    def test_r3_ca04_solver_attributes_scan_graph_and_included_sources(self):
        fixture = CargoFixture(self)
        fixture.package("dependency", "dependency")
        fixture.manifest_tail('[dependencies]\ndependency={path="dependency"}')
        fixture.lock()
        fixture.kani()
        for filename, source in (
            ("src/lib.rs", '#[kani::solver(bin = "/opt/sat")] fn proof() {}'),
            (
                "dependency/src/lib.rs",
                '#[cfg_attr(kani, kani::solver(bin="/opt/sat"))] pub fn value() -> u8 { 1 }',
            ),
            ("src/proof.txt", '#[kani :: solver (bin = r#"/opt/sat"#)] fn proof() {}'),
        ):
            with self.subTest(filename=filename):
                fixture.write("src/lib.rs", 'include!("proof.txt");')
                fixture.write("dependency/src/lib.rs", "pub fn value() -> u8 { 1 }")
                fixture.write("src/proof.txt", "pub fn proof() {}")
                fixture.write(filename, source)
                self.assert_refused(
                    fixture.capture("kani", adapter="kani-toolchain"),
                    "Kani solver attribute",
                )
        fixture.write("src/lib.rs", "#[kani::solver(kissat)] fn proof() {}")
        fixture.write("src/proof.txt", '// #[kani::solver(bin="/opt/comment")]\n')
        fixture.write("dependency/src/lib.rs", "pub fn value() -> u8 { 1 }")
        result = fixture.capture("kani", adapter="kani-toolchain")
        self.assertTrue(result["ok"], result)

    def test_fresh_ca01_solver_imports_and_namespace_aliases_refuse(self):
        fixture = CargoFixture(self)
        fixture.package("dependency", "dependency")
        fixture.manifest_tail('[dependencies]\ndependency={path="dependency"}')
        fixture.lock()
        fixture.kani()
        for index, source in enumerate(
            (
                'use kani::solver; #[solver(bin="/opt/sat")] fn proof() {}',
                'use ::kani::solver as picked; #[picked(bin="/opt/sat")] fn proof() {}',
                'use kani::{proof, solver as picked}; #[picked(bin="/opt/sat")] fn proof() {}',
                'use {kani::{solver as picked}}; #[picked(bin="/opt/sat")] fn proof() {}',
                'use kani as selected; #[selected::solver(bin="/opt/sat")] fn proof() {}',
                'use kani::{self as selected}; #[selected::solver(bin="/opt/sat")] fn proof() {}',
                'use {kani as selected}; #[selected::solver(bin="/opt/sat")] fn proof() {}',
                'use kani::*; #[solver(bin="/opt/sat")] fn proof() {}',
                'use {kani::{*}}; #[solver(bin="/opt/sat")] fn proof() {}',
                'extern crate kani as selected; #[selected::solver(bin="/opt/sat")] fn proof() {}',
                '#[macro_use] extern crate kani; #[solver(bin="/opt/sat")] fn proof() {}',
                'pub use kani::solver as picked; #[picked(bin="/opt/sat")] fn proof() {}',
                'use r#kani::{r#solver as r#picked}; #[r#picked(bin="/opt/sat")] fn proof() {}',
                'use kani_macros::solver as picked; #[picked(bin="/opt/sat")] fn proof() {}',
                "use kani::solver as picked; #[picked(kissat)] fn proof() {}",
            )
        ):
            filename = ("src/lib.rs", "dependency/src/lib.rs", "src/proof.txt")[
                index % 3
            ]
            with self.subTest(filename=filename, source=source):
                fixture.write("src/lib.rs", 'include!("proof.txt");')
                fixture.write("dependency/src/lib.rs", "pub fn value() -> u8 { 1 }")
                fixture.write("src/proof.txt", "pub fn proof() {}")
                fixture.write(
                    filename, source.replace("fn proof()", "#[kani::proof] fn proof()")
                )
                self.assert_refused(
                    fixture.capture("kani", adapter="kani-toolchain"),
                    "Kani solver imports and namespace aliases",
                )

    def test_fresh_ca01_raw_and_unknown_solver_attributes_refuse(self):
        fixture = CargoFixture(self)
        fixture.package("dependency", "dependency")
        fixture.manifest_tail('[dependencies]\ndependency={path="dependency"}')
        fixture.lock()
        fixture.kani()
        for index, attribute in enumerate(
            (
                '#[kanitool::solver(bin="/opt/sat")]',
                '#[cfg_attr(kani, kanitool::solver(bin=r#"/opt/sat"#))]',
                "#[kanitool::solver(kissat)]",
                "#[r#kanitool::r#solver(kissat)]",
                '#[kani::r#solver(bin="/opt/sat")]',
                '#[solver(bin="/opt/sat")]',
                '#[selected::solver(bin="/opt/sat")]',
                "#[selected::kani::solver(kissat)]",
                "#[cfg_attr(kani, crate::kani::solver(kissat))]",
                "#[kani::solver(cadical)]",
                "#[kani::solver]",
                '#[kani::solver = "/opt/sat"]',
                '#[kani::solver{bin="/opt/sat"}]',
                '#[kani::solver(kissat, bin="/opt/sat")]',
                '#[cfg_attr(kani, unknown([]), kanitool::solver(bin="/opt/sat"))]',
            )
        ):
            filename = ("src/lib.rs", "dependency/src/lib.rs", "src/proof.txt")[
                index % 3
            ]
            with self.subTest(filename=filename, attribute=attribute):
                fixture.write("src/lib.rs", 'include!("proof.txt");')
                fixture.write("dependency/src/lib.rs", "pub fn value() -> u8 { 1 }")
                fixture.write("src/proof.txt", "pub fn proof() {}")
                fixture.write(
                    filename, "#[kani::proof]\n" + attribute + "\nfn proof() {}"
                )
                self.assert_refused(
                    fixture.capture("kani", adapter="kani-toolchain"),
                    "Kani solver attribute",
                )

    def test_fresh_ca01_canonical_pinned_solver_and_benign_tokens_survive(self):
        fixture = CargoFixture(self)
        fixture.lock()
        fixture.kani()
        fixture.write(
            "src/benign.txt",
            r"""
use kani::{any, proof};
use std::fmt::{self, Debug as DebugTrait};
#[doc = "use kani::solver as picked; #[kanitool::solver(bin=\"/opt/doc\")]"]
pub fn solver(kani: &str, kanitool: &str) {
    let solver = kanitool;
    let r#use = (kani, solver);
    let text = "use kani as picked; #[picked::solver(bin=\"/opt/string\")]";
    let raw = r##"use kani::{solver as picked}; #[kanitool::solver(bin="/opt/raw")]"##;
    let bytes = b"use kani::solver; #[solver(bin=\"/opt/bytes\")]";
    let opening = '[';
    let _ = (r#use, text, raw, bytes, opening);
}
pub fn call() { crate::solver("", ""); }
// use kani::solver as picked; #[picked(bin="/opt/comment")]
/* use kani as picked; /* nested */ #[kanitool::solver(bin="/opt/comment")] */
""",
        )
        for attribute in (
            "#[kani::solver(kissat)]",
            "#[kani :: solver ( kissat, )]",
            "#[cfg_attr(kani, kani::solver(kissat))]",
            "#[cfg_attr(kani, cfg_attr(test, ::kani::solver(kissat,)))]",
            "#[r#kani::r#solver(kissat)]",
            "#[kani /* namespace */ :: solver(/* argument */ kissat,)]",
        ):
            with self.subTest(attribute=attribute):
                fixture.write(
                    "src/lib.rs",
                    attribute
                    + '\n#[kani::proof]\nfn proof() {}\ninclude!("benign.txt");',
                )
                result = fixture.capture("kani", adapter="kani-toolchain")
                self.assertTrue(result["ok"], result)
                self.assertEqual(
                    next(
                        root["path"]
                        for root in result["roots"]
                        if root["label"] == "solver"
                    ),
                    str(Path(fixture.env["KANI_HOME"]) / "bin/kissat"),
                )

    def test_r3_ca04_kani_manifest_overrides_refuse(self):
        for scope in ("package", "workspace"):
            for value in (
                '[{}.metadata.kani.flags]\nsolver="bin=/opt/sat"',
                '[{}.metadata.kani]\nflags=["--solver=bin=/opt/sat"]',
            ):
                with self.subTest(scope=scope, value=value):
                    fixture = CargoFixture(self)
                    fixture.lock()
                    fixture.kani()
                    fixture.manifest_tail(value.format(scope))
                    self.assert_refused(
                        fixture.capture("kani", adapter="kani-toolchain"),
                        "Kani package/workspace metadata overrides",
                    )
        fixture = CargoFixture(self)
        fixture.package(
            "dependency",
            "dependency",
            tail='[package.metadata.kani.flags]\nsolver="bin=/opt/sat"',
        )
        fixture.manifest_tail('[dependencies]\ndependency={path="dependency"}')
        fixture.lock()
        fixture.kani()
        self.assert_refused(
            fixture.capture("kani", adapter="kani-toolchain"),
            "Kani package/workspace metadata overrides",
        )

    def test_r3_ca03_toolchain_files_require_only_a_channel(self):
        rustup = shutil.which("rustup")
        if not rustup:
            self.skipTest("requires rustup")
        fixture = CargoFixture(self)
        fixture.lock()
        proxy = fixture.base / "proxy/cargo"
        proxy.parent.mkdir()
        proxy.symlink_to(rustup)
        channel = Path(self.sysroot).name
        env = {
            "RUSTUP_HOME": os.environ.get("RUSTUP_HOME", str(Path.home() / ".rustup"))
        }
        for filename in ("rust-toolchain", "rust-toolchain.toml"):
            for content in (
                '[toolchain]\npath="/opt/rust-dev"\n',
                '[toolchain]\nchannel="' + channel + '"\npath="/opt/rust-dev"\n',
                '[toolchain]\nchannel="' + channel + '"\ncomponents=["clippy"]\n',
                '[toolchain]\nchannel="'
                + channel
                + '"\ntargets=["wasm32-unknown-unknown"]\n',
                '[toolchain]\nchannel="' + channel + '"\nprofile="minimal"\n',
                'unknown=true\n[toolchain]\nchannel="' + channel + '"\n',
                "[toolchain]\n",
            ):
                with self.subTest(filename=filename, content=content):
                    target = fixture.write(filename, content)
                    self.assert_refused(
                        fixture.capture(entry=str(proxy), env=env),
                        "rust-toolchain file",
                    )
            target.unlink()
        fixture.write("rust-toolchain.toml", '[toolchain]\nchannel="' + channel + '"\n')
        result = fixture.capture(entry=str(proxy), env=env)
        self.assertTrue(result["ok"], result)

    def test_r3_ca02_config_include_refuses_every_source(self):
        fixture = CargoFixture(self)
        fixture.lock()
        fixture.write(".cargo/config.toml", 'include=["/opt/shared/cargo.toml"]\n')
        self.assert_refused(fixture.capture(), "Cargo config include")
        fixture.write(".cargo/config.toml", "")
        fixture.write("ci/cargo.toml", 'include=["/opt/shared/cargo.toml"]\n')
        for argument in (
            "ci/cargo.toml",
            'include=["/opt/shared/cargo.toml"]',
            "include=[]",
        ):
            with self.subTest(argument=argument):
                result = fixture.capture("build", "--config", argument)
                self.assert_refused(result, "Cargo config include")
                self.assertEqual(result["probes"], [])

    def test_r3_ca01_cargo_features_refuse_root_and_dependency_manifests(self):
        fixture = CargoFixture(self)
        fixture.lock()
        fixture.write(
            "Cargo.toml",
            'cargo-features=["profile-rustflags"]\n'
            + fixture.manifest
            + '\n[profile.dev]\nrustflags=["@/opt/kani.args"]\n',
        )
        self.assert_refused(fixture.capture(), "manifest cargo-features")
        fixture = CargoFixture(self)
        fixture.package("dependency", "dependency")
        fixture.manifest_tail('[dependencies]\ndependency={path="dependency"}')
        fixture.lock()
        manifest = fixture.root / "dependency/Cargo.toml"
        manifest.write_text("cargo-features=[]\n" + manifest.read_text())
        self.assert_refused(fixture.capture(), "manifest cargo-features")

    def test_r3_ca05_kani_cfg_dependency_tables_refuse_before_graph_selection(self):
        for selector in (
            "cfg(kani)",
            "cfg( kani )",
            "cfg(all(unix, kani))",
            "cfg(not(kani))",
        ):
            with self.subTest(selector=selector):
                fixture = CargoFixture(self)
                fixture.package("hidden", "hidden", build="fn main() {}")
                fixture.manifest_tail(
                    "[target."
                    + json.dumps(selector)
                    + '.dependencies]\nhidden={path="hidden"}'
                )
                fixture.lock()
                fixture.kani()
                result = fixture.capture("kani", adapter="kani-toolchain")
                self.assert_refused(result, "cfg(kani)-selected dependency tables")
                self.assertFalse(
                    any(probe["command"][1:2] == ["tree"] for probe in result["probes"])
                )
        fixture = CargoFixture(self)
        fixture.package("hidden", "hidden")
        fixture.package(
            "dependency",
            "dependency",
            tail='[target."cfg(kani)".build-dependencies]\nhidden={path="../hidden"}',
        )
        fixture.manifest_tail('[dependencies]\ndependency={path="dependency"}')
        fixture.lock()
        fixture.kani()
        self.assert_refused(
            fixture.capture("kani", adapter="kani-toolchain"),
            "cfg(kani)-selected dependency tables",
        )

    def test_r3_ca07_renamed_inclusion_macros_refuse(self):
        fixture = CargoFixture(self)
        fixture.package("dependency", "dependency")
        fixture.manifest_tail('[dependencies]\ndependency={path="dependency"}')
        fixture.lock()
        fixture.write(
            "src/lib.rs",
            "pub fn copy(include: &str) { let include = include.to_owned(); drop(include); }",
        )
        self.assertTrue(fixture.capture()["ok"])
        for macro in ("include", "include_str", "include_bytes"):
            for filename in ("src/lib.rs", "dependency/src/lib.rs", "src/code.txt"):
                with self.subTest(macro=macro, filename=filename):
                    fixture.write("src/lib.rs", 'include!("code.txt");')
                    fixture.write("src/code.txt", "pub fn value() -> u8 { 1 }")
                    fixture.write("dependency/src/lib.rs", "pub fn value() -> u8 { 1 }")
                    fixture.write(
                        filename,
                        f'use core::{{{macro} as grab}}; grab!("/opt/unbound");',
                    )
                    self.assert_refused(
                        fixture.capture(), "Rust inclusion macro imports"
                    )

    def test_r3_ca08_cross_target_proc_macro_refuses_unbound_host_linker(self):
        fixture = CargoFixture(self)
        fixture.package("macro", "host-macro", proc_macro=True)
        fixture.manifest_tail('[dependencies]\nhost-macro={path="macro"}')
        fixture.lock()
        result = fixture.capture("build", "--target", "wasm32-unknown-unknown")
        self.assert_refused(
            result, "cross-target host linker requires a distinct host context"
        )

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
