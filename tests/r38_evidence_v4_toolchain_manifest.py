#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""R38 self-contained Apalache manifest and reviewed bootstrap eligibility."""

from __future__ import annotations


import json
import shutil
import subprocess
import sys

import unittest

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MODULE = REPO / "tools/evidence-v4/evidence-v4-toolchain-proof.ts"
MANIFEST = "META-INF/MANIFEST.MF"
TOOL_MAIN = "at.forsyte.apalache.tla.Tool"
TOOL_ENTRY = "at/forsyte/apalache/tla/Tool.class"
BOOTSTRAP_MAIN = "fv.compat.ApalacheJsonLimits"
BOOTSTRAP_ENTRY = "fv/compat/ApalacheJsonLimits.class"
BOOTSTRAP_HASH = (
    "sha256:61601b896f7e5d42937f1f029cc27722b2a142940781d451e4b1b393052508ec"
)
PROGRAM = (
    "const {parseApalacheJarManifest,validateApalacheBootstrapHash}="
    "await import(" + json.dumps(MODULE.as_uri()) + ");\n"
    + r"""
const inputs = await Bun.stdin.json();
const results = inputs.map(input => {
  try {
    if (input.op === 'hash') {
      validateApalacheBootstrapHash(input.hash);
      return {ok:true};
    }
    if (input.op !== 'manifest') throw Error('Unknown manifest test operation');
    return {ok:true,value:parseApalacheJarManifest(input.entries,input.manifest)};
  } catch (error) {
    return {ok:false,error:error instanceof Error ? error.message : String(error)};
  }
});
process.stdout.write(JSON.stringify(results));
"""
)


def native(requests: list[dict]) -> list[dict]:
    result = subprocess.run(
        [shutil.which("bun"), "--eval", PROGRAM],
        input=json.dumps(requests, ensure_ascii=True),
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode:
        raise AssertionError(result.stdout + result.stderr)
    return json.loads(result.stdout)


def manifest(main=TOOL_MAIN, attributes=(), newline="\r\n") -> str:
    return newline.join(
        ["Manifest-Version: 1.0", "Main-Class: " + main, *attributes, "", ""]
    )


def request(value: str, entries=None) -> dict:
    return {
        "op": "manifest",
        "manifest": value,
        "entries": [MANIFEST, TOOL_ENTRY] if entries is None else entries,
    }





class ManifestClosure(unittest.TestCase):
    def assert_rejected(self, requests):
        results = native(requests)
        self.assertEqual(len(results), len(requests))
        for value, result in zip(requests, results, strict=True):
            with self.subTest(value=value):
                self.assertFalse(result["ok"], result)

    def test_standard_manifest_metadata_and_line_endings(self):
        attributes = (
            "Specification-Title: apalache",
            "Specification-Version: 0.62.1",
            "Specification-Vendor: Apalache Development Team",
            "Implementation-Title: apalache",
            "Implementation-Version: 0.62.1",
            "Implementation-Vendor: Apalache Development Team",
            "Implementation-Vendor-Id: org.apalache-mc",
            "Implementation-URL: https://github.com/apalache-mc/apalache",
            "Created-By: 27",
            "Build-Jdk: 27",
            "Build-Jdk-Spec: 27",
            "Automatic-Module-Name: apalache",
            "Enable-Native-Access: ALL-UNNAMED",
        )
        results = native(
            [request(manifest(attributes=attributes, newline=eol)) for eol in ("\r\n", "\n", "\r")]
        )
        for result in results:
            self.assertTrue(result["ok"], result)
            self.assertEqual(
                result["value"], {"mainClass": TOOL_MAIN, "bootstrapEntry": None}
            )

    def test_continuations_and_case_insensitive_attribute_names(self):
        value = (
            "mAnIfEsT-vErSiOn: 1.0\r\n"
            "mAiN-cLaSs: at.forsyte.apalache.\r\n"
            " tla.Tool\r\n"
            "Implementation-Title: Apalache \r\n"
            " model checker\r\n\r\n"
        )
        result = native([request(value)])[0]
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["value"]["mainClass"], TOOL_MAIN)

    def test_external_classpath_is_never_an_eligible_layout(self):
        values = (
            "Class-Path: adjacent.jar",
            "cLaSs-PaTh: adjacent.jar",
            "Class-Path: ",
            "Class-Path: adjacent-\r\n backend.jar",
        )
        self.assert_rejected([request(manifest(attributes=(value,))) for value in values])

    

    def test_jar_index_and_loader_manifest_arrangements_reject(self):
        self.assert_rejected([
            request(manifest(), [MANIFEST, TOOL_ENTRY, entry])
            for entry in ("META-INF/INDEX.LIST", "meta-inf/index.list")
        ])
        attributes = (
            "Boot-Class-Path: adjacent.jar",
            "Launcher-Agent-Class: example.Agent",
            "Premain-Class: example.Agent",
            "Agent-Class: example.Agent",
            "Loader-Path: ../libraries",
            "Multi-Release: true",
            "Multi-Release: false",
            "Add-Exports: java.base/java.lang=ALL-UNNAMED",
        )
        self.assert_rejected([request(manifest(attributes=(value,))) for value in attributes])
        self.assert_rejected([request(manifest(attributes=("Enable-Native-Access: other.module",)))])

    def test_manifest_and_entrypoint_ambiguity_rejects(self):
        self.assert_rejected([
            request(manifest(), []),
            request(manifest(), [TOOL_ENTRY]),
            request(manifest(), [MANIFEST, MANIFEST, TOOL_ENTRY]),
            request(manifest(), [MANIFEST, "meta-inf/manifest.mf", TOOL_ENTRY]),
            request(manifest(), ["meta-inf/manifest.mf", TOOL_ENTRY]),
        ])
        self.assert_rejected([
            request(manifest(), [MANIFEST]),
            request(manifest(), [MANIFEST, TOOL_ENTRY, TOOL_ENTRY]),
        ])
        self.assert_rejected([
            request(manifest(main="org.springframework.boot.loader.JarLauncher")),
            request(manifest(main="org.codehaus.plexus.classworlds.launcher.Launcher")),
        ])

    def test_malformed_duplicate_or_named_section_manifests_reject(self):
        values = (
            "Manifest-Version: 1.0\nMain-Class: " + TOOL_MAIN,
            "Manifest-Version: 1.0\nMain-Class:" + TOOL_MAIN + "\n\n",
            " continuation\n" + manifest(),
            manifest() + " continuation\n",
            manifest() + "Name: nested/\nClass-Path: adjacent.jar\n\n",
            manifest(attributes=("mAiN-cLaSs: " + TOOL_MAIN,)),
            manifest(attributes=("MANIFEST-VERSION: 1.0",)),
            manifest(attributes=("Implementation-Title: invalid\0value",)),
            manifest().replace("Manifest-Version: 1.0\r\n", ""),
            manifest().replace("Manifest-Version: 1.0", "Manifest-Version: 2.0"),
            manifest().replace("Main-Class: " + TOOL_MAIN + "\r\n", ""),
            "\ufeff" + manifest(),
        )
        self.assert_rejected([request(value) for value in values])

    def test_reviewed_bootstrap_requires_one_class_and_exact_digest(self):
        selected = request(
            manifest(main=BOOTSTRAP_MAIN), [MANIFEST, TOOL_ENTRY, BOOTSTRAP_ENTRY]
        )
        result = native([selected])[0]
        self.assertTrue(result["ok"], result)
        self.assertEqual(
            result["value"],
            {"mainClass": BOOTSTRAP_MAIN, "bootstrapEntry": BOOTSTRAP_ENTRY},
        )
        self.assert_rejected([
            request(manifest(main=BOOTSTRAP_MAIN)),
            request(
                manifest(main=BOOTSTRAP_MAIN),
                [MANIFEST, TOOL_ENTRY, BOOTSTRAP_ENTRY, BOOTSTRAP_ENTRY],
            ),
        ])
        hashes = native(
            [
                {"op": "hash", "hash": BOOTSTRAP_HASH},
                {"op": "hash", "hash": BOOTSTRAP_HASH[:-1] + "0"},
                {"op": "hash", "hash": "sha256:" + "0" * 64},
                {"op": "hash", "hash": ""},
            ]
        )
        self.assertTrue(hashes[0]["ok"], hashes[0])
        for result in hashes[1:]:
            self.assertFalse(result["ok"], result)
            
        self.assert_rejected([
            request(
                manifest(
                    main=BOOTSTRAP_MAIN,
                    attributes=("Class-Path: adjacent.jar",),
                ),
                [MANIFEST, TOOL_ENTRY, BOOTSTRAP_ENTRY],
            )
        ])


if __name__ == "__main__":
    if not shutil.which("bun"):
        print("INCOMPLETE: R38 manifest regressions require Bun")
        sys.exit(2)
    sys.exit(
        0
        if unittest.TextTestRunner(verbosity=2)
        .run(unittest.defaultTestLoader.loadTestsFromTestCase(ManifestClosure))
        .wasSuccessful()
        else 1
    )
