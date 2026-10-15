#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""R38 strict JSON, canonical bytes and recorded tool identity semantics."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

from evidence_v4_fixture import EvidenceV4Fixture, REPO, SUPPORT

sys.path.insert(0, str(REPO / "scripts"))
import fv_evidence_v4_schema as schema


def oracle_c(value) -> bytes:
    if value is None:
        return b"null"
    if type(value) is bool:
        return b"true" if value else b"false"
    if type(value) is int:
        return str(value).encode("ascii")
    if isinstance(value, str):
        escaped = "".join(
            '\\"'
            if char == '"'
            else "\\\\"
            if char == "\\"
            else f"\\u{ord(char):04x}"
            if ord(char) < 32
            else char
            for char in value
        )
        return ('"' + escaped + '"').encode("utf-8")
    if isinstance(value, list):
        return b"[" + b",".join(oracle_c(entry) for entry in value) + b"]"
    if isinstance(value, dict):
        return (
            b"{"
            + b",".join(
                oracle_c(key) + b":" + oracle_c(value[key])
                for key in sorted(value, key=lambda key: key.encode("utf-8"))
            )
            + b"}"
        )
    raise TypeError(value)


def oracle_h(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def oracle_d(label: str, value) -> str:
    return oracle_h(
        ("fv-evidence-v4/" + label).encode("utf-8") + b"\0" + oracle_c(value)
    )


def native(requests: list[dict]) -> list[dict]:
    result = subprocess.run(
        [
            shutil.which("bun"),
            str(SUPPORT),
            "schema",
            str(REPO / "tools/evidence-v4/evidence-v4-toolchain-common.ts"),
        ],
        input=json.dumps(requests, ensure_ascii=True),
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise AssertionError(result.stdout + result.stderr)
    return json.loads(result.stdout)


def identity(files: list[dict], packages=()) -> dict:
    value = {
        "id": "tree-vector",
        "kind": "tree",
        "locator": {"mode": "path", "value": "/illustrative/recorded-root"},
        "files": sorted(
            copy.deepcopy(files), key=lambda entry: entry["path"].encode("utf-8")
        ),
        "packages": sorted(
            copy.deepcopy(list(packages)),
            key=lambda package: oracle_d("cargo-package", package),
        ),
        "version": None,
        "discovery": [],
        "system_dependencies": {
            "os": "darwin",
            "arch": "arm64",
            "release": "fixture-vector",
            "sdk": None,
        },
        "requires": [],
    }
    value["digest"] = oracle_d(
        "tool-content",
        {
            key: value[key]
            for key in ("kind", "files", "packages", "system_dependencies")
        },
    )
    return value


class SchemaVectors(unittest.TestCase):
    def assert_valid_both(self, shape, value):
        schema.validate(shape, value)
        result = native([{"op": "validate", "shape": shape, "value": value}])[0]
        self.assertTrue(result["ok"], result)
        self.assertEqual(bytes.fromhex(result["canonical_hex"]), oracle_c(value))

    def assert_rejected_both(self, shape, values):
        results = native(
            [{"op": "validate", "shape": shape, "value": value} for value in values]
        )
        for value, result in zip(values, results, strict=True):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    schema.validate(shape, value)
                self.assertFalse(result["ok"], result)

    def test_canonical_unicode_controls_order_and_safe_integer_limits(self):
        values = [
            {"z": None, "a": "é\n"},
            {"😀": 2, "\ue000": 1, "é": 3, "a": 4},
            {
                "é": "composed",
                "e\u0301": "decomposed",
                "slash": "/",
                "lines": "\u2028\u2029",
            },
            {"controls": "".join(chr(code) for code in range(32)), "quotes": '"\\'},
            [0, 9007199254740991, True, False, None, {"exit_code": -9007199254740991}],
            {"__proto__": {"x": 1}, "constructor": 0},
            {"astral": "\U0001f4a9", "nul": "\0", "empty": []},
        ]
        results = native(
            [{"op": "canonical", "label": "vector", "value": value} for value in values]
        )
        for value, result in zip(values, results, strict=True):
            with self.subTest(value=value):
                expected = oracle_c(value)
                self.assertTrue(result["ok"], result)
                self.assertEqual(bytes.fromhex(result["canonical_hex"]), expected)
                self.assertEqual(schema.C(value), expected)
                self.assertEqual(result["hash"], oracle_h(expected))
                self.assertEqual(schema.H(expected), result["hash"])
                self.assertEqual(result["domain"], oracle_d("vector", value))
                self.assertEqual(schema.D("vector", value), result["domain"])
        self.assertEqual(oracle_c(values[0]), b'{"a":"\xc3\xa9\\u000a","z":null}')
        self.assertEqual(
            schema.H(b""),
            "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        )

    def test_strict_lexical_vectors_have_native_python_equality(self):
        valid = [
            b'{"n":9007199254740991}',
            b'{"exit_code":-9007199254740991}',
            b' {"a":"\\ud83d\\ude00"}\n',
            b'{"\\u0061":1}',
            b'{"__proto__":{"x":1}}',
        ]
        invalid = [
            b'{"n":-0}',
            b'{"n":1e0}',
            b'{"n":1E+0}',
            b'{"n":1.0}',
            b'{"n":01}',
            b'{"n":+1}',
            b'{"n":-1}',
            b'{"n":9007199254740992}',
            b'{"exit_code":-9007199254740992}',
            b'{"a":1,"a":2}',
            b'{"a":1,"\\u0061":2}',
            b'{"outer":{"a":1,"a":2}}',
            b'{"s":"\\ud800"}',
            b'{"s":"\\udfff"}',
            b'{"s":"\\ud800x"}',
            b'{"s":"\xff"}',
            b"\xef\xbb\xbf{}",
            b'{"n":NaN}',
            b'{"n":Infinity}',
            b'{"s":"\x01"}',
            b"{}{}",
            b'{"a":1,}',
        ]
        results = native(
            [{"op": "parse", "hex": data.hex()} for data in valid + invalid]
        )
        for data, result in zip(valid, results[: len(valid)], strict=True):
            with self.subTest(data=data):
                value = schema.parse_json(data)
                self.assertTrue(result["ok"], result)
                self.assertEqual(
                    bytes.fromhex(result["canonical_hex"]), oracle_c(value)
                )
                self.assertEqual(schema.C(value), oracle_c(value))
        for data, result in zip(invalid, results[len(valid) :], strict=True):
            with self.subTest(data=data):
                with self.assertRaises(ValueError):
                    schema.parse_json(data)
                self.assertFalse(result["ok"], result)

    def test_exact_call_union_rejects_unknown_fields_aliases_and_unsorted_sets(self):
        valid = {
            "schema_version": "fv-evidence-run/v4",
            "policy": ".fv/execution-policy.json",
            "mode": "run",
            "records": ["A", "B"],
            "resume": False,
            "jobs": 1,
        }
        self.assert_valid_both("V4Call", valid)
        malformed = []
        for fields in (
            {"schema_version": "fv-evidence-run/v3"},
            {"schema_version": "fv-evidence-run/v5"},
            {"command": ["sh", "-c", "true"]},
            {"required": False},
            {"mode": "resume"},
            {"records": ["B", "A"]},
            {"records": ["A", "A"]},
            {"records": []},
            {"jobs": 0},
            {"policy": "a/../policy.json"},
            {"policy": "a\\policy.json"},
        ):
            malformed.append({**valid, **fields})
        self.assert_rejected_both("V4Call", malformed)

    def test_actual_directory_links_keep_alias_entries_and_canonical_targets(self):
        with EvidenceV4Fixture() as fixture:
            tree = fixture.control_dir / "tooltree"
            (tree / "real/empty").mkdir(parents=True)
            (tree / "real/file.bin").write_bytes(b"actual-tool-bytes\n")
            (tree / "alias").symlink_to("real", target_is_directory=True)
            (tree / "file-link").symlink_to("real/file.bin")
            files = native(
                [
                    {
                        "op": "roots",
                        "roots": [
                            {"label": "root", "path": str(tree)},
                            {"label": "nested", "path": str(tree / "real")},
                            {"label": "twin", "path": str(tree / "real")},
                        ],
                    }
                ]
            )[0]
            self.assertTrue(files["ok"], files)
            entries = {entry["path"]: entry for entry in files["files"]}
            self.assertEqual(entries["root/alias"]["kind"], "symlink-directory")
            self.assertEqual(entries["root/alias"]["target"], "real")
            self.assertEqual(entries["root/alias"]["resolved_path"], "nested")
            self.assertFalse(any(path.startswith("root/alias/") for path in entries))
            self.assertEqual(
                entries["root/file-link"]["resolved_path"], "nested/file.bin"
            )
            descendants = [
                {**entry, "path": path.removeprefix("nested/")}
                for path, entry in entries.items()
                if path.startswith("nested/")
            ]
            self.assertEqual(
                entries["root/alias"]["resolved_hash"],
                oracle_d(
                    "tool-directory",
                    {
                        "entries": sorted(
                            descendants, key=lambda entry: entry["path"].encode()
                        )
                    },
                ),
            )
            self.assertIn("nested/empty", entries)
            self.assertIn("twin/empty", entries)
            value = identity(files["files"])
            self.assert_valid_both("ToolIdentity", value)
            mutations = []
            for field, replacement in (
                ("resolved_hash", "sha256:" + "0" * 64),
                ("resolved_path", "missing"),
            ):
                changed = copy.deepcopy(files["files"])
                next(entry for entry in changed if entry["path"] == "root/alias")[
                    field
                ] = replacement
                mutations.append(identity(changed))
            changed = copy.deepcopy(files["files"])
            next(entry for entry in changed if entry["path"] == "root/file-link")[
                "resolved_size"
            ] += 1
            mutations.append(identity(changed))
            changed = copy.deepcopy(files["files"])
            changed.append(
                {
                    "path": "root/alias/copied.bin",
                    "kind": "file",
                    "hash": oracle_h(b"actual-tool-bytes\n"),
                    "size": 18,
                    "executable": False,
                }
            )
            mutations.append(identity(changed))
            self.assert_rejected_both("ToolIdentity", mutations)
            (tree / "real/cycle").symlink_to("..", target_is_directory=True)
            cyclic = native(
                [{"op": "roots", "roots": [{"label": "root", "path": str(tree)}]}]
            )[0]
            self.assertFalse(cyclic["ok"], cyclic)
            (tree / "real/cycle").unlink()
            (tree / "external").symlink_to(fixture.temporary, target_is_directory=True)
            escaped = native(
                [{"op": "roots", "roots": [{"label": "root", "path": str(tree)}]}]
            )[0]
            self.assertFalse(escaped["ok"], escaped)

    def test_empty_directory_alias_hash_and_cycles_are_independent(self):
        files = [
            {"path": "root", "kind": "directory"},
            {"path": "root/empty", "kind": "directory"},
            {
                "path": "root/alias",
                "kind": "symlink-directory",
                "target": "empty",
                "resolved_path": "root/empty",
                "resolved_hash": oracle_d("tool-directory", {"entries": []}),
            },
        ]
        self.assert_valid_both("ToolIdentity", identity(files))
        changed = copy.deepcopy(files)
        next(entry for entry in changed if entry["path"] == "root/alias")[
            "resolved_path"
        ] = "root"
        self.assert_rejected_both("ToolIdentity", [identity(changed)])

    def test_source_qualified_packages_bind_exact_sources_and_roots(self):
        revision = "0f15877d30d434c90cf8414cdde66700bf52a4eb"
        package = {
            "name": "quartz-zkdcap",
            "source": {
                "id": f"git+https://github.com/reliqlabs/quartz.git?rev={revision}#{revision}",
                "kind": "git",
                "revision": revision,
            },
            "version": "0.5.1",
        }
        other = copy.deepcopy(package)
        other["source"]["id"] = (
            f"git+https://example.org/quartz.git?rev={revision}#{revision}"
        )
        expected = [
            "ac5e5c59f396cab6328fb1650a2c58cddd35343fbc53a5ce381fd4c2178debf4",
            "26a1d5ea320b20b87e6ff3bf895cd3ba7bcddfdb8b030be9ccfec2c7f9825e09",
        ]
        vectors = native(
            [
                {"op": "canonical", "label": "cargo-package", "value": value}
                for value in (package, other)
            ]
        )
        for value, root, result in zip(
            (package, other), expected, vectors, strict=True
        ):
            self.assert_valid_both("PackageIdentity", value)
            self.assertEqual(result["domain"], "sha256:" + root)
            self.assertEqual(schema.D("cargo-package", value), "sha256:" + root)
        roots = [
            {"path": "packages", "kind": "directory"},
            *[{"path": "packages/" + root, "kind": "directory"} for root in expected],
        ]
        self.assert_valid_both("ToolIdentity", identity(roots, [package, other]))
        missing_root = identity(roots[:-1], [package, other])
        self.assert_rejected_both(
            "ToolIdentity", [missing_root, identity(roots, [package, package])]
        )
        registry = {
            "name": "same",
            "version": "1.0.0",
            "source": {
                "kind": "registry",
                "id": "registry+https://example.invalid/index",
                "checksum": "a" * 64,
            },
        }
        self.assert_valid_both("PackageIdentity", registry)
        self.assert_valid_both(
            "PackageIdentity",
            {
                "name": "path-pkg",
                "version": "1.0.0",
                "source": {"kind": "path", "path": "crates/path-pkg"},
            },
        )
        malformed = [
            copy.deepcopy(package),
            copy.deepcopy(registry),
            {
                "name": "path-pkg",
                "version": "1",
                "source": {"kind": "path", "path": "../escape"},
            },
        ]
        malformed[0]["source"]["revision"] = "1" * 40
        malformed[1]["source"]["checksum"] = "sha256:" + "a" * 64
        self.assert_rejected_both("PackageIdentity", malformed)


if __name__ == "__main__":
    if not all(shutil.which(name) for name in ("bun", "git", "sh")):
        print("INCOMPLETE: R38 requires Bun, Git and POSIX sh")
        sys.exit(2)
    sys.exit(
        0
        if unittest.TextTestRunner(verbosity=2)
        .run(unittest.defaultTestLoader.loadTestsFromTestCase(SchemaVectors))
        .wasSuccessful()
        else 1
    )
