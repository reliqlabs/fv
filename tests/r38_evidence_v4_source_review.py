#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""R38 review regressions for canonical record sets and source bindings."""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from evidence_v4_fixture import EvidenceV4Fixture, REPO

sys.path.insert(0, str(REPO / "scripts"))
import fv_evidence_v4 as portable
import fv_evidence_v4_schema as schema
import fv_project

MODULES = REPO / "tools/evidence-v4"
PROGRAM = (
    "const model = await import("
    + json.dumps((MODULES / "evidence-v4-model.ts").as_uri())
    + ");\nconst policy = await import("
    + json.dumps((MODULES / "evidence-v4-policy.ts").as_uri())
    + ");\nconst source = await import("
    + json.dumps((MODULES / "evidence-v4-source.ts").as_uri())
    + ");\n"
    + r"""
const validators = {
  Policy: model.validatePolicyStructure,
  PackageIdentity: model.validatePackageIdentity,
  ClaimRecord: model.validateClaimRecord,
  EnvironmentIdentity: model.validateEnvironmentIdentity,
  ToolIdentity: model.validateToolIdentity,
  OwnedProcess: model.validateOwnedProcess,
  Owner: model.validateOwnerRecord,
  ObservationCheck: model.validateObservationCheck,
  PlanResult: model.validatePlanResult,
  RunManifest: model.validateRunManifest,
};
const results = [];
for (const request of await Bun.stdin.json()) {
  try {
    if (request.op === 'validate') {
      const value = validators[request.shape](request.value);
      results.push({ok: true, canonical_hex: Buffer.from(model.C(value)).toString('hex')});
    } else if (request.op === 'prefix') {
      results.push({ok: true, selected: source.prefixSelects(request.path, request.prefix)});
    } else if (request.op === 'requirements') {
      const closure = {files: request.bound.map((path) => ({path}))};
      await source.assertSourceRequirements(request.root, closure, request.required);
      results.push({ok: true});
    } else {
      const loaded = await policy.loadPolicy(request.root, request.policy, request.target);
      if (request.op === 'load') {
        results.push({ok: true, common: loaded.common});
      } else if (request.op === 'capture') {
        const probe = async (command, cwd) => {
          const child = Bun.spawn({cmd: command, cwd, stdout: 'pipe', stderr: 'pipe'});
          const [stdout, stderr, exit_code] = await Promise.all([
            new Response(child.stdout).arrayBuffer(),
            new Response(child.stderr).arrayBuffer(),
            child.exited,
          ]);
          return {stdout: Buffer.from(stdout), stderr: Buffer.from(stderr), exit_code};
        };
        const state = await source.captureInputState(request.root, loaded, probe);
        results.push({ok: true, state, closure: source.sourceClosure(
          state, loaded.policy.recipes[0], source.commonBindingPaths(loaded))});
      } else throw Error('unknown source vector operation');
    }
  } catch (error) {
    results.push({ok: false, reason: String(error)});
  }
}
process.stdout.write(JSON.stringify(results));
"""
)
HASH = schema.H(b"review-vector")
UUID = "00000000-0000-4000-8000-000000000001"
UTC = "2026-10-15T00:00:00.000Z"


def native(requests):
    result = subprocess.run(
        [shutil.which("bun"), "--eval", PROGRAM],
        input=json.dumps(requests, ensure_ascii=True),
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode:
        raise AssertionError(result.stdout + result.stderr)
    return json.loads(result.stdout)


def changed(value, field, replacement):
    result = copy.deepcopy(value)
    current = result
    for component in field[:-1]:
        current = current[component]
    current[field[-1]] = replacement
    return result


def tool_identity():
    value = {
        "id": "review-tool",
        "kind": "executable",
        "locator": {"mode": "path", "value": "/recorded/tool"},
        "files": [
            {"path": ".", "kind": "file", "hash": HASH, "size": 1, "executable": True}
        ],
        "packages": [],
        "version": None,
        "discovery": [],
        "system_dependencies": {
            "os": "linux",
            "arch": "arm64",
            "release": "review",
            "sdk": None,
        },
        "requires": [],
    }
    return identify_tool(value)


def identify_tool(value):
    value["digest"] = schema.D(
        "tool-content",
        {
            key: value[key]
            for key in ("kind", "files", "packages", "system_dependencies")
        },
    )
    return value


class SourceReview(unittest.TestCase):
    def assert_vectors(self, vectors):
        results = native(
            [
                {"op": "validate", "shape": shape, "value": value}
                for label, shape, value, accepted in vectors
            ]
        )
        for (label, shape, value, accepted), result in zip(
            vectors, results, strict=True
        ):
            with self.subTest(field=label):
                self.assertEqual(result["ok"], accepted, result)
                if accepted:
                    schema.validate(shape, value)
                    self.assertEqual(
                        bytes.fromhex(result["canonical_hex"]), schema.C(value)
                    )
                else:
                    with self.assertRaises(ValueError):
                        schema.validate(shape, value)

    def test_b_before_a_plan_and_run_sort_sets_without_reordering_policy_work(self):
        with EvidenceV4Fixture(claims=("B", "A"), distinct=True) as fixture:
            for selector in (None, ["A", "B"]):
                with self.subTest(selector=selector):
                    plan = fixture.plan(records=selector)
                    self.assertEqual(plan["result"], "READY", plan)
                    self.assertEqual(plan["selected_records"], ["A", "B"])
                    self.assertEqual(plan["required_records"], ["A", "B"])
                    self.assertEqual(
                        [
                            slot["distinct_slot"]["claim_id"]
                            for slot in plan["physical_slots"]
                        ],
                        ["B", "A"],
                    )
                    self.assert_vectors([("plan", "PlanResult", plan, True)])
                    result = fixture.run(records=selector)
                    self.assertEqual(result["result"], "PASS", result)
                    manifest = fixture.manifest(result)
                    self.assertEqual(manifest["selected_records"], ["A", "B"])
                    self.assertEqual(manifest["required_records"], ["A", "B"])
                    self.assertEqual(
                        [row["claim_id"] for row in manifest["claims"]], ["B", "A"]
                    )
                    self.assertEqual(
                        [row["distinct_slot"]["claim_id"] for row in manifest["work"]],
                        ["B", "A"],
                    )
                    self.assert_vectors([("manifest", "RunManifest", manifest, True)])
                    report, code = fixture.assess()
                    self.assertEqual(code, 0, report)
            self.assertEqual(fixture.count(), 2)
            self.assertEqual(
                [row["claim_id"] for row in fixture.policy["records"]], ["B", "A"]
            )

    def test_dispatch_target_resolution_matches_python_for_canonical_and_unsafe_paths(
        self,
    ):
        with EvidenceV4Fixture() as fixture:
            intent = fixture.root / ".fv/intent.md"
            (fixture.root / "intent-alias").symlink_to(".fv", target_is_directory=True)
            root_alias = fixture.temporary / "project-alias"
            root_alias.symlink_to(fixture.root, target_is_directory=True)
            cases = [
                (str(intent), fixture.root, None),
                (".fv/./intent.md", fixture.root, str(intent)),
                ("unused/../.fv/intent.md", fixture.root, ".fv//intent.md"),
                (".fv//intent.md", fixture.root, None),
                ("intent-alias/intent.md", fixture.root, None),
                (str(intent), root_alias, ".fv/./intent.md"),
                (" ", fixture.root, None),
            ]
            for target, root, caller in cases:
                with self.subTest(target=target, root=root, caller=caller):
                    fixture.write(
                        ".fv/dispatch.json", {"omp_native": {"target_spec": target}}
                    )
                    expected = fv_project.repo_relative(
                        root, fv_project.resolve_target(root)
                    )
                    result = native(
                        [
                            {
                                "op": "load",
                                "root": str(root),
                                "policy": fixture.policy_path,
                                **({"target": caller} if caller is not None else {}),
                            }
                        ]
                    )[0]
                    self.assertTrue(result["ok"], result)
                    self.assertEqual(result["common"]["intent_path"], expected)
                    self.assertEqual(
                        result["common"]["intent_hash"], schema.H(intent.read_bytes())
                    )
                    reader = portable.Reader(root)
                    self.assertEqual(
                        portable._policy(reader, fixture.policy_path)[1],
                        result["common"],
                    )

            outside = fixture.temporary / "outside-intent.md"
            outside.write_text("outside\n", encoding="utf-8")
            (fixture.root / ".fv/intent-link.md").symlink_to("intent.md")
            (fixture.root / "outside-alias").symlink_to(
                fixture.temporary, target_is_directory=True
            )
            fixture.write("~literal/intent.md", "literal tilde target\n")
            for target in (
                str(outside),
                "../outside-intent.md",
                ".fv/intent-link.md",
                "outside-alias/outside-intent.md",
                "~literal/intent.md",
                "./~literal/intent.md",
                ".fv",
                ".fv/missing.md",
            ):
                with self.subTest(unsafe_target=target):
                    fixture.write(
                        ".fv/dispatch.json", {"omp_native": {"target_spec": target}}
                    )
                    with self.assertRaises((ValueError, OSError)):
                        fv_project.resolve_target(fixture.root)
                    result = native(
                        [
                            {
                                "op": "load",
                                "root": str(fixture.root),
                                "policy": fixture.policy_path,
                            }
                        ]
                    )[0]
                    self.assertFalse(result["ok"], result)
            fixture.write(
                ".fv/dispatch.json", {"omp_native": {"target_spec": ".fv/intent.md"}}
            )
            other = fixture.write(".fv/other-intent.md", "different intent\n")
            mismatch = native(
                [
                    {
                        "op": "load",
                        "root": str(fixture.root),
                        "policy": fixture.policy_path,
                        "target": str(other),
                    }
                ]
            )[0]
            self.assertFalse(mismatch["ok"], mismatch)
            self.assertIn("caller target differs", mismatch["reason"])

    def test_generic_nonempty_fields_accept_nul_with_native_python_canonical_agreement(
        self,
    ):
        text = "bounded\0text é\n"
        vectors = []
        with EvidenceV4Fixture() as fixture:
            for field in (
                ("records", 0, "scope"),
                ("recipes", 0, "determinism", "rationale"),
                ("recipes", 0, "pass_marker"),
            ):
                vectors.append(
                    (str(field), "Policy", changed(fixture.policy, field, text), True)
                )
            policy = copy.deepcopy(fixture.policy)
            policy["toolchains"][0]["version_command"] = ["version"]
            policy["toolchains"][0]["version_cwd"] = "."
            policy["toolchains"][0]["accept"]["version_contains"] = [text]
            vectors.append(("version literal", "Policy", policy, True))
            common = native(
                [
                    {
                        "op": "load",
                        "root": str(fixture.root),
                        "policy": fixture.policy_path,
                    }
                ]
            )[0]["common"]
            slot = fixture.policy["records"][0]["executions"][0]
            claim = {
                "schema_version": "fv-evidence-run/v4",
                "run_id": UUID,
                "claim_id": "A",
                "required": True,
                "evidence_class": "test-witnessed",
                "scope": text,
                "common": common,
                "executions": [
                    {
                        "slot_id": slot["slot_id"],
                        "tool": slot["tool"],
                        "recipe_id": slot["recipe_id"],
                        "evidence_class": "test-witnessed",
                        "execution": None,
                        "state": "MISSING",
                        "reason": None,
                        "observation_binding": slot["observation_binding"],
                        "blocking_events": [],
                        "observation": None,
                    }
                ],
                "result": "INCOMPLETE",
                "waiver": None,
            }
            claim["record_id"] = schema.D("claim-record", claim)
            vectors.append(("claim scope", "ClaimRecord", claim, True))
        package = {
            "name": "review",
            "version": "1.0.0",
            "source": {
                "kind": "registry",
                "id": "registry+review",
                "checksum": "a" * 64,
            },
        }
        for field in (("name",), ("version",), ("source", "id")):
            vectors.append(
                (str(field), "PackageIdentity", changed(package, field, text), True)
            )
        revision = "a" * 40
        package["source"] = {
            "kind": "git",
            "id": text + "#" + revision,
            "revision": revision,
        }
        vectors.append(("git source ID", "PackageIdentity", package, True))
        self.assert_vectors(vectors)

    def test_os_bound_strings_and_scalar_boundaries_reject_in_both_languages(self):
        vectors = []
        with EvidenceV4Fixture() as fixture:
            for field in (
                ("environment", "platforms", 0, "os"),
                ("environment", "platforms", 0, "arch"),
                ("recipes", 0, "command", 0),
                ("recipes", 0, "cwd"),
                ("intent_path",),
                ("environment", "set", "PATH"),
            ):
                vectors.append(
                    (
                        str(field),
                        "Policy",
                        changed(fixture.policy, field, "a\0b"),
                        False,
                    )
                )
            for field in (
                ("records", 0, "scope"),
                ("recipes", 0, "determinism", "rationale"),
                ("recipes", 0, "pass_marker"),
            ):
                for invalid in ("", "\ud800"):
                    vectors.append(
                        (
                            str(field),
                            "Policy",
                            changed(fixture.policy, field, invalid),
                            False,
                        )
                    )
            for control in ("\0", "\n", "\x85"):
                for field in (
                    ("recipes", 0, "resources"),
                    ("preflight", 0, "resources"),
                ):
                    vectors.append(
                        (
                            str(field),
                            "Policy",
                            changed(fixture.policy, field, ["resource" + control]),
                            False,
                        )
                    )
            vectors.append(
                (
                    "argv permits scalar controls",
                    "Policy",
                    changed(
                        fixture.policy,
                        ("recipes", 0, "command"),
                        ["tool", "argument\né"],
                    ),
                    True,
                )
            )
        environment = {
            "os": "linux",
            "arch": "arm64",
            "release": "review",
            "variables": [],
        }
        for field in ("os", "arch", "release"):
            vectors.append(
                (
                    "environment " + field,
                    "EnvironmentIdentity",
                    changed(environment, (field,), "a\0b"),
                    False,
                )
            )
            tool = changed(tool_identity(), ("system_dependencies", field), "a\0b")
            vectors.append(
                ("tool system " + field, "ToolIdentity", identify_tool(tool), False)
            )
        tool = tool_identity()
        tool["system_dependencies"]["sdk"] = {
            "version": "sdk\0version",
            "settings_hash": HASH,
        }
        vectors.append(("SDK version", "ToolIdentity", identify_tool(tool), False))
        for locator in (
            {"mode": "command", "value": "tool\0name"},
            {"mode": "path", "value": "/tool\0path"},
            {
                "mode": "command-relative",
                "value": "tool\0name",
                "parent_levels": 0,
                "subpath": ".",
            },
        ):
            vectors.append(
                (
                    "locator " + locator["mode"],
                    "ToolIdentity",
                    changed(tool_identity(), ("locator",), locator),
                    False,
                )
            )
        for kind in ("symlink-file", "symlink-directory"):
            tool = tool_identity()
            tool["kind"] = "tree"
            target = (
                {
                    "path": "target",
                    "kind": "file",
                    "hash": HASH,
                    "size": 1,
                    "executable": True,
                }
                if kind == "symlink-file"
                else {"path": "target", "kind": "directory"}
            )
            link = {
                "path": "alias",
                "kind": kind,
                "target": "target\0name",
                "resolved_path": "target",
                "resolved_hash": HASH
                if kind == "symlink-file"
                else schema.D("tool-directory", {"entries": []}),
            }
            if kind == "symlink-file":
                link.update(resolved_size=1, executable=True)
            tool["files"] = [link, target]
            vectors.append(
                (kind + " target", "ToolIdentity", identify_tool(tool), False)
            )
        process = {
            "pid": 1,
            "process_start_id": "start\0id",
            "process_group": 1,
            "session_id": 1,
            "parent_pid": 1,
        }
        vectors.append(("owned process start", "OwnedProcess", process, False))
        owner = {
            "schema_version": "fv-evidence-owner/v1",
            "owner_id": UUID,
            "host_id": HASH,
            "boot_id": HASH,
            "pid": 1,
            "process_start_id": "start\0id",
            "run_id": UUID,
            "created_at": UTC,
            "children": [],
            "spawn_windows": [],
            "pending_results": [],
        }
        vectors.append(("owner start", "Owner", owner, False))
        state = {
            "verified_inputs_policy_hash": HASH,
            "inventory_hash": schema.D("inventory", []),
            "source_snapshot": schema.H(b""),
            "clean": True,
            "files": [],
        }
        ref = {"path": "review.bin", "hash": HASH, "size": 1}
        check = {
            "schema_version": "fv-observation-check/v1",
            "request": ref,
            "response": None,
            "started_at": UTC,
            "finished_at": UTC,
            "termination": {
                "exit_code": None,
                "signal": "SIG\0TERM",
                "timed_out": False,
                "cancelled": False,
            },
            "stdout": ref,
            "stderr": ref,
            "source_before": state,
            "source_after": None,
            "toolchain": [],
            "result": "ERROR",
            "reason": "terminated",
        }
        vectors.append(("termination signal", "ObservationCheck", check, False))
        self.assert_vectors(vectors)

    def test_directory_prefix_requires_descendants_and_capture_agrees_with_python(self):
        pairs = [
            ("x", "x/"),
            ("x/child", "x/"),
            ("x", "x"),
            ("xy/child", "x/"),
            ("x/child", "x"),
        ]
        results = native(
            [{"op": "prefix", "path": name, "prefix": prefix} for name, prefix in pairs]
        )
        for (name, prefix), result in zip(pairs, results, strict=True):
            with self.subTest(path=name, prefix=prefix):
                self.assertEqual(
                    result["selected"], fv_project.matches_prefixes(name, [prefix])
                )
        with EvidenceV4Fixture() as fixture:
            fixture.write("x", "regular file\n")
            fixture.policy["recipes"][0]["source_closure"]["prefixes"] = ["x/"]
            fixture.save_policy("unsigned regular-file directory-prefix fixture")
            request = {
                "op": "capture",
                "root": str(fixture.root),
                "policy": fixture.policy_path,
            }
            result = native([request])[0]
            self.assertFalse(result["ok"], result)
            self.assertIn("missing/uncovered closure prefix: x/", result["reason"])
            reader = portable.Reader(fixture.root)
            policy, common, mandatory, *_ = portable._policy(
                reader, fixture.policy_path
            )
            with self.assertRaisesRegex(ValueError, "prefix has no covered source"):
                portable._current_inputs(reader, policy, mandatory)
            (fixture.root / "x").unlink()
            fixture.write("x/child", "actual descendant\n")
            fixture.commit("unsigned actual directory-prefix fixture")
            result = native([request])[0]
            self.assertTrue(result["ok"], result)
            reader = portable.Reader(fixture.root)
            policy, common, mandatory, *_ = portable._policy(
                reader, fixture.policy_path
            )
            state = portable._current_inputs(reader, policy, mandatory)
            self.assertEqual(result["state"], state)
            self.assertEqual(
                result["closure"],
                portable._effective_closure(policy["recipes"][0], state, common),
            )
            self.assertIn(
                "x/child", [entry["path"] for entry in result["closure"]["files"]]
            )

    def test_tool_source_requirements_must_lie_inside_recipe_closure(self):
        with tempfile.TemporaryDirectory(prefix="r38-requirements-") as directory:
            root = Path(directory).resolve(strict=True)
            for relative in (
                "lean/A.lean",
                "lean/sub/B.lean",
                "lean/.lake/C.lean",
                "lean/notes.txt",
                "lakefile.toml",
            ):
                (root / relative).parent.mkdir(parents=True, exist_ok=True)
                (root / relative).write_text("x\n")
            bound = ["lakefile.toml", "lean/A.lean", "lean/sub/B.lean"]
            required = {"directories": ["lean"], "files": ["lakefile.toml"]}
            cases = [
                (bound, required, None),
                (bound[:2], required, "lean/sub/B.lean"),
                (bound[1:], required, "lakefile.toml"),
                (bound, {"directories": ["."], "files": []}, None),
            ]
            results = native(
                [
                    {"op": "requirements", "root": str(root), "bound": b, "required": r}
                    for b, r, _ in cases
                ]
            )
            for (_, _, missing), result in zip(cases, results):
                if missing is None:
                    self.assertTrue(result["ok"], result)
                else:
                    self.assertFalse(result["ok"])
                    self.assertIn(
                        f"outside recipe closure: {missing}", result["reason"]
                    )
            (root / "lean/link.lean").symlink_to(root / "lean/A.lean")
            [linked] = native(
                [
                    {
                        "op": "requirements",
                        "root": str(root),
                        "bound": bound,
                        "required": required,
                    }
                ]
            )
            self.assertFalse(linked["ok"])
            self.assertIn(
                "symlink inside tool source directory: lean/link.lean", linked["reason"]
            )


if __name__ == "__main__":
    if not all(shutil.which(name) for name in ("bun", "git", "sh")):
        print("INCOMPLETE: R38 requires Bun, Git and POSIX sh")
        sys.exit(2)
    sys.exit(0 if unittest.main(exit=False, verbosity=2).result.wasSuccessful() else 1)
