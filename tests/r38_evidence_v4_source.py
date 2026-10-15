#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""R38 source closure, global inventory and filesystem safety."""

from __future__ import annotations

import os
import shutil
import sys
import unittest

from evidence_v4_fixture import EvidenceV4Fixture


class SourceClosure(unittest.TestCase):
    def passing(self, fixture):
        result = fixture.run()
        self.assertEqual(result["result"], "PASS", result)
        report, code = fixture.assess()
        self.assertEqual(code, 0, report)
        return fixture.artifacts()[-1][1], fixture.claims()[0]["executions"][0][
            "execution"
        ]

    def test_related_committed_content_invalidates_but_unrelated_content_reuses(self):
        with EvidenceV4Fixture() as fixture:
            before_artifact, before = self.passing(fixture)
            fixture.write("notes/unrelated.txt", "changed existing unrelated content\n")
            fixture.commit("unsigned unrelated existing content")
            result = fixture.run()
            self.assertEqual(result["result"], "PASS", result)
            self.assertEqual(fixture.count(), 1)
            self.assertEqual(fixture.claims()[0]["executions"][0]["execution"], before)
            self.assertEqual(fixture.manifest()["work"][0]["cache"], "hit")
            current_source = fixture.manifest()["source_before"]
            self.assertEqual(
                current_source["inventory_hash"],
                before_artifact["source_before"]["inventory_hash"],
            )
            self.assertNotEqual(
                current_source["source_snapshot"],
                before_artifact["source_before"]["source_snapshot"],
            )
            report, code = fixture.assess()
            self.assertEqual(code, 0, report)
            fixture.write("src/value.txt", "changed related source\n")
            fixture.commit("unsigned related content")
            result = fixture.run()
            self.assertEqual(result["result"], "PASS", result)
            self.assertEqual(fixture.count(), 2)
            after = fixture.claims()[0]["executions"][0]["execution"]
            self.assertNotEqual(after["execution_key"], before["execution_key"])
            artifact = next(
                value
                for path, value in fixture.artifacts()
                if str(path.relative_to(fixture.root)) == after["path"]
            )
            self.assertNotEqual(
                artifact["descriptor"]["closure"]["hash"],
                before_artifact["descriptor"]["closure"]["hash"],
            )
            report, code = fixture.assess()
            self.assertEqual(code, 0, report)

    def test_inventory_add_delete_rename_and_execute_bit_invalidate_narrow_closure(
        self,
    ):
        for name in ("add", "delete", "rename", "execute-bit"):
            with self.subTest(mutation=name), EvidenceV4Fixture() as fixture:
                baseline, previous = self.passing(fixture)
                unrelated = fixture.root / "notes/unrelated.txt"
                if name == "add":
                    fixture.write("notes/added.txt", "unrelated addition\n")
                elif name == "delete":
                    unrelated.unlink()
                elif name == "rename":
                    unrelated.rename(fixture.root / "notes/renamed.txt")
                else:
                    unrelated.chmod(0o755)
                fixture.commit("unsigned global inventory " + name)
                result = fixture.run()
                self.assertEqual(result["result"], "PASS", result)
                self.assertEqual(fixture.count(), 2)
                self.assertEqual(fixture.manifest(result)["work"][0]["cache"], "miss")
                current = fixture.claims(result)[0]["executions"][0]["execution"]
                self.assertNotEqual(current["execution_key"], previous["execution_key"])
                artifact = next(
                    value
                    for path, value in fixture.artifacts()
                    if str(path.relative_to(fixture.root)) == current["path"]
                )
                self.assertNotEqual(
                    artifact["source_before"]["inventory_hash"],
                    baseline["source_before"]["inventory_hash"],
                )
                self.assertEqual(
                    artifact["descriptor"]["closure"]["hash"],
                    baseline["descriptor"]["closure"]["hash"],
                )
                report, code = fixture.assess()
                self.assertEqual(code, 0, report)

    def test_dirty_selected_content_staged_and_untracked_reject_before_reuse(self):
        for mutation in (
            "unstaged-related",
            "unstaged-unrelated",
            "staged",
            "untracked",
            "deleted",
            "renamed",
        ):
            with self.subTest(mutation=mutation), EvidenceV4Fixture() as fixture:
                self.passing(fixture)
                if mutation == "unstaged-related":
                    fixture.write("src/value.txt", "dirty related\n")
                elif mutation == "unstaged-unrelated":
                    fixture.write(
                        "notes/unrelated.txt", "dirty outside recipe closure\n"
                    )
                elif mutation == "staged":
                    fixture.write(
                        "notes/unrelated.txt", "staged outside recipe closure\n"
                    )
                    fixture.git_command("add", "notes/unrelated.txt")
                elif mutation == "untracked":
                    fixture.write("notes/new.txt", "selected untracked\n")
                elif mutation == "deleted":
                    (fixture.root / "notes/unrelated.txt").unlink()
                else:
                    (fixture.root / "notes/unrelated.txt").rename(
                        fixture.root / "notes/renamed.txt"
                    )
                plan = fixture.plan()
                self.assertEqual(plan["result"], "ERROR", plan)
                result = fixture.run()
                self.assertEqual(result["result"], "ERROR", result)
                self.assertEqual(fixture.count(), 1)
                self.assertEqual(len(fixture.artifacts()), 1)
                report, code = fixture.assess()
                self.assertNotEqual(code, 0, report)

    def test_clean_symlink_hardlink_and_unsafe_inventory_fail_closed(self):
        for mutation in (
            "file-symlink",
            "directory-symlink",
            "hardlink-alias",
            "newline-name",
            "backslash-name",
            "tilde-name",
        ):
            with self.subTest(mutation=mutation), EvidenceV4Fixture() as fixture:
                self.passing(fixture)
                if mutation == "file-symlink":
                    (fixture.root / "src/link.txt").symlink_to("value.txt")
                elif mutation == "directory-symlink":
                    (fixture.root / "notes/link").symlink_to(
                        "../src", target_is_directory=True
                    )
                elif mutation == "hardlink-alias":
                    os.link(
                        fixture.root / "src/value.txt", fixture.root / "notes/alias.txt"
                    )
                else:
                    name = {
                        "newline-name": "notes/bad\nname.txt",
                        "backslash-name": "notes/bad\\name.txt",
                        "tilde-name": "~unsafe.txt",
                    }[mutation]
                    fixture.write(name, "unsafe path\n")
                fixture.commit("unsigned unsafe input fixture " + mutation)
                result = fixture.run()
                self.assertEqual(result["result"], "ERROR", result)
                self.assertEqual(fixture.count(), 1)
                self.assertEqual(len(fixture.artifacts()), 1)

    def test_policy_symlink_and_escaping_call_paths_reject(self):
        for path in (
            "/absolute-policy.json",
            "../outside.json",
            "~policy",
            "a/../policy",
            "a//policy",
            "a\\policy",
        ):
            with self.subTest(path=path), EvidenceV4Fixture() as fixture:
                result = fixture.call(
                    call={
                        "schema_version": "fv-evidence-run/v4",
                        "policy": path,
                        "mode": "run",
                    }
                )
                self.assertEqual(result["result"], "ERROR", result)
                self.assertEqual(fixture.count(), 0)
        with EvidenceV4Fixture() as fixture:
            policy_path = fixture.root / fixture.policy_path
            outside = fixture.temporary / "outside-policy.json"
            outside.write_bytes(policy_path.read_bytes())
            policy_path.unlink()
            policy_path.symlink_to(outside)
            fixture.commit("unsigned symlink policy fixture")
            result = fixture.run()
            self.assertEqual(result["result"], "ERROR", result)
            self.assertEqual(fixture.count(), 0)

    def test_missing_basis_prefix_and_unknown_closure_reject_before_evidence(self):
        for mutation in ("missing-basis", "missing-prefix", "unknown-mode"):
            with self.subTest(mutation=mutation), EvidenceV4Fixture() as fixture:
                closure = fixture.policy["recipes"][0]["source_closure"]
                if mutation == "missing-basis":
                    closure["basis"] = [".fv/missing-basis.json"]
                elif mutation == "missing-prefix":
                    closure["prefixes"] = ["fixture/", "missing/", "src/"]
                else:
                    closure["mode"] = "infer-from-success"
                fixture.save_policy("unsigned malformed closure fixture")
                result = fixture.run()
                self.assertEqual(result["result"], "ERROR", result)
                self.assertEqual(fixture.count(), 0)
                self.assertEqual(fixture.artifacts(), [])


if __name__ == "__main__":
    if not all(shutil.which(name) for name in ("bun", "git", "sh")):
        print("INCOMPLETE: R38 requires Bun, Git and POSIX sh")
        sys.exit(2)
    sys.exit(
        0
        if unittest.TextTestRunner(verbosity=2)
        .run(unittest.defaultTestLoader.loadTestsFromTestCase(SourceClosure))
        .wasSuccessful()
        else 1
    )
