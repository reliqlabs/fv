"""Independent portable validation of immutable execution evidence v4."""

from __future__ import annotations

import json
import os
import posixpath
import re
import shutil
import signal
import stat
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, unquote

import fv_project
from fv_evidence_v4_schema import (
    C,
    H,
    D,
    V4Error,
    parse_json,
    path,
    sorted_unique,
    validate,
)

BASE = ".fv/evidence/v4"
EMPTY_FILE_HASH = H(b"")
DISCRIMINATORS = {
    "fv-evidence-current/v1": "CurrentPointer",
    "fv-evidence-batch/v1": "RunManifest",
    "fv-evidence-run/v4": "ClaimRecord",
    "fv-evidence-run-result/v1": "RunResult",
}
MARKERS = {
    "code-enforced": ("--- fv-evidence: exit=0 ---",),
    "proof-discharged": (
        "VERIFICATION:- SUCCESSFUL",
        "Build completed successfully",
        "--- fv-evidence: exit=0 ---",
    ),
    "bounded-checked": ("[ok]", "VERIFICATION:- SUCCESSFUL", "No violation found"),
    "test-witnessed": ("test result: ok.",),
    "conformance-tested": (
        "CONFORMANCE: PASS",
        "CONFORMANCE_TESTED: PASS",
        "test result: ok.",
        "--- fv-evidence: exit=0 ---",
    ),
}


def _check(condition, message):
    if not condition:
        raise V4Error(message)


def _without(value, key):
    return {name: entry for name, entry in value.items() if name != key}


def _identity(value, key, label):
    _check(
        value[key] == D(label, _without(value, key)),
        f"{key} canonical identity mismatch",
    )


def _members(value):
    sorted_unique(value, lambda item: (item["claim_id"], item["slot_id"]))


def _regular(root, relative, output=False):
    path(relative)
    current = root
    parts = relative.split("/")
    for index, part in enumerate(parts):
        current /= part
        info = current.lstat()
        _check(not stat.S_ISLNK(info.st_mode), f"symlink component: {relative}")
        if index < len(parts) - 1:
            _check(stat.S_ISDIR(info.st_mode), f"non-directory component: {relative}")
    _check(stat.S_ISREG(info.st_mode), f"not a regular file: {relative}")
    if output:
        _check(info.st_nlink == 1, f"output hardlink: {relative}")
    return current, info


class Reader:
    def __init__(self, root):
        self.root = fv_project.resolve_project_root(root)
        self.inodes = {}
        self.digests = {}
        self.artifacts = {}
        self.checks = {}

    def read(self, relative, output=True):
        target, before = _regular(self.root, relative, output)
        inode = (before.st_dev, before.st_ino)
        previous = self.inodes.setdefault(inode, relative)
        _check(previous == relative, f"aliased paths: {previous}, {relative}")
        with target.open("rb") as handle:
            opened = os.fstat(handle.fileno())
            _check(
                (opened.st_dev, opened.st_ino) == inode, f"replaced file: {relative}"
            )
            data = handle.read()
            after = os.fstat(handle.fileno())
        signature = lambda info: (
            info.st_size,
            info.st_mtime_ns,
            info.st_ctime_ns,
            info.st_mode,
            info.st_nlink,
        )
        _check(
            signature(before) == signature(opened) == signature(after),
            f"mutated file: {relative}",
        )
        digest = H(data)
        if relative in self.digests:
            _check(
                self.digests[relative] == digest, f"changed immutable file: {relative}"
            )
        self.digests[relative] = digest
        return data

    def ref(self, ref, shape="FileRef"):
        validate(shape, ref)
        _check(ref["path"].startswith(BASE + "/"), "artifact outside v4 store")
        data = self.read(ref["path"])
        _check(
            self.digests[ref["path"]] == ref["hash"],
            f"byte hash mismatch: {ref['path']}",
        )
        if "size" in ref:
            _check(len(data) == ref["size"], f"byte size mismatch: {ref['path']}")
        return data

    def json_ref(self, ref, shape, refshape="FileRef"):
        value = parse_json(self.ref(ref, refshape))
        validate(shape, value)
        return value


def read_file_ref(root, ref):
    return Reader(root).ref(ref)


def _input_state(value):
    validate("InputState", value)
    sorted_unique(value["files"], lambda item: item["path"])
    entries = {item["path"]: item for item in value["files"]}
    input_policy = entries.get(fv_project.VERIFIED_INPUTS_RELATIVE)
    expected_policy_hash = (
        input_policy["hash"]
        if input_policy is not None
        else D(
            "verified-inputs-default",
            {
                "mode": "exclude",
                "prefixes": [],
                "structural": list(fv_project.DEFAULT_EXCLUSIONS),
            },
        )
    )
    _check(
        value["verified_inputs_policy_hash"] == expected_policy_hash,
        "input-policy byte identity mismatch",
    )
    _check(
        all(
            not fv_project.matches_prefixes(item["path"], fv_project.DEFAULT_EXCLUSIONS)
            for item in value["files"]
        ),
        "structural output appears in source inventory",
    )
    _check(
        value["inventory_hash"]
        == D(
            "inventory",
            [
                {"path": item["path"], "executable": item["executable"]}
                for item in value["files"]
            ],
        ),
        "input inventory hash mismatch",
    )
    snapshot = b"".join(
        item["path"].encode("utf-8") + b"\0" + item["hash"][7:].encode("ascii") + b"\n"
        for item in value["files"]
    )
    _check(value["source_snapshot"] == H(snapshot), "input source snapshot mismatch")


def _closure(value):
    validate("Closure", value)
    sorted_unique(value["prefixes"])
    sorted_unique(value["basis"])
    sorted_unique(value["files"], lambda item: item["path"])
    if value["mode"] == "verified-inputs":
        _check(not value["prefixes"], "whole-input closure has prefixes")
    else:
        _check(
            value["basis"] and value["prefixes"],
            "prefix closure has no completeness basis",
        )
    _check(
        value["hash"] == D("source-closure", _without(value, "hash")),
        "closure identity mismatch",
    )


def _environment(value, policy=None):
    validate("EnvironmentIdentity", value)
    sorted_unique(value["variables"], lambda item: item["name"])
    for item in value["variables"]:
        _check(
            item["present"] == (item["value_hash"] is not None),
            "environment presence/hash contradiction",
        )
    if policy is not None:
        env = policy["environment"]
        _check(
            {"os": value["os"], "arch": value["arch"]} in env["platforms"],
            "producer platform outside policy",
        )
        _check(
            [item["name"] for item in value["variables"]] == env["identity"],
            "environment identity names differ from policy",
        )
        variables = {item["name"]: item for item in value["variables"]}
        for name, text in env["set"].items():
            _check(
                variables[name]["present"]
                and variables[name]["value_hash"] == H(text.encode("utf-8")),
                f"policy literal environment mismatch: {name}",
            )


def _file_has_bytes(entry, *, executable=False):
    if entry is None or entry["kind"] not in ("file", "symlink-file"):
        return False
    size = entry["size"] if entry["kind"] == "file" else entry["resolved_size"]
    digest = entry["hash"] if entry["kind"] == "file" else entry["resolved_hash"]
    return (
        size > 0
        and digest != EMPTY_FILE_HASH
        and (not executable or entry["executable"])
    )


def _root_has_bytes(by_path, label, *, executable=False):
    visited = set()

    def visit(name):
        if name in visited:
            return False
        visited.add(name)
        entry = by_path.get(name)
        if entry is None:
            return False
        if _file_has_bytes(entry, executable=executable):
            return True
        if entry["kind"] == "symlink-directory":
            return visit(entry["resolved_path"])
        if entry["kind"] != "directory":
            return False
        prefix = "" if name == "." else name + "/"
        for descendant, value in by_path.items():
            if descendant == name or not descendant.startswith(prefix):
                continue
            if _file_has_bytes(value, executable=executable):
                return True
            if value["kind"] == "symlink-directory" and visit(value["resolved_path"]):
                return True
        return False

    return visit(label)


def _tool(value, declaration=None, environment=None):
    validate("ToolIdentity", value)
    by_path = {entry["path"]: entry for entry in value["files"]}
    for package in value["packages"]:
        source = package["source"]
        if source["kind"] == "git":
            _check(
                source["id"].startswith("git+"),
                "Cargo git source is not exact lock source",
            )
        elif source["kind"] == "registry":
            _check(
                source["id"].startswith("registry+"),
                "Cargo registry source is not exact lock source",
            )
    if environment is not None:
        system = value["system_dependencies"]
        _check(
            all(system[key] == environment[key] for key in ("os", "arch", "release")),
            "tool system provenance contradicts producer platform",
        )
    if declaration is not None:
        derived_tree = (
            declaration["kind"] in ("executable", "file")
            and declaration["locator"]["mode"] != "adapter"
            and value["kind"] == "tree"
        )
        _check(
            all(value[key] == declaration[key] for key in ("id", "locator", "requires"))
            and (value["kind"] == declaration["kind"] or derived_tree),
            "tool declaration binding mismatch",
        )
        if derived_tree:
            library_prefix = "native/non-system-libraries/"
            libraries = [
                entry
                for entry in value["files"]
                if entry["path"].startswith(library_prefix)
            ]
            driver_paths = {"native/drivers/cargo-0", "native/drivers/rustc-0"}
            drivers = [by_path[name] for name in driver_paths if name in by_path]
            directories = {"native", "native/non-system-libraries", "native/drivers"}
            _check(
                value["system_dependencies"]["os"] == "darwin"
                and (libraries or drivers)
                and by_path.get("selected-file", {}).get("kind") == "file"
                and all(
                    (entry["path"] == "selected-file" and entry["kind"] == "file")
                    or (entry["path"] in directories and entry["kind"] == "directory")
                    or (entry["path"] in driver_paths and entry["kind"] == "file")
                    or (
                        entry["path"].startswith(library_prefix)
                        and entry["kind"] == "file"
                    )
                    for entry in value["files"]
                ),
                "invalid derived native tool roots",
            )
            if declaration["kind"] == "executable":
                _check(
                    _file_has_bytes(by_path["selected-file"], executable=True),
                    "empty derived executable tool identity",
                )
            if drivers:
                driver_names = {
                    entry["path"].rsplit("/", 1)[-1][:-2] for entry in drivers
                }
                _check(
                    declaration["locator"]["mode"] in ("command", "path")
                    and posixpath.basename(declaration["locator"]["value"].rstrip("/"))
                    in driver_names,
                    "derived Rustup driver differs from locator",
                )
            for entry in drivers:
                _check(
                    _file_has_bytes(entry, executable=True),
                    "empty derived Rustup driver identity",
                )
                name = entry["path"].rsplit("/", 1)[-1][:-2]
                _check(
                    any(
                        len(probe["command"]) == 3
                        and posixpath.basename(probe["command"][0].rstrip("/"))
                        == "rustup"
                        and probe["command"][1:] == ["which", name]
                        and probe["exit_code"] == 0
                        for probe in value["discovery"]
                    ),
                    "derived Rustup driver has no selection probe",
                )
            for entry in libraries:
                encoded = entry["path"][len(library_prefix) :]
                try:
                    decoded = unquote(encoded, errors="strict")
                except UnicodeError as error:
                    raise V4Error("invalid derived native library root") from error
                _check(
                    "/" not in encoded
                    and decoded
                    and "\0" not in decoded
                    and quote(decoded, safe="-_.!~*'()") == encoded
                    and entry["kind"] == "file"
                    and _file_has_bytes(entry),
                    "invalid derived native library root",
                )
        version = value["version"]
        if declaration["version_command"] is None:
            _check(version is None, "undeclared version probe")
        else:
            _check(
                version is not None
                and version["command"] == declaration["version_command"]
                and version["cwd"] == declaration["version_cwd"],
                "version command/cwd differs from declaration",
            )
        accept = declaration["accept"]
        _check(
            not accept["sha256"] or value["digest"] in accept["sha256"],
            "tool digest outside allowlist",
        )
        _check(
            all(
                text in (version or {}).get("text", "")
                for text in accept["version_contains"]
            ),
            "tool version pin mismatch",
        )
    locator = value["locator"]
    if locator["mode"] == "adapter":
        family = locator["value"]
        roots = {
            "producer-runtime": (("implementation", False), ("runtime", True)),
            "python-runtime": (
                ("executable", True),
                ("stdlib", False),
                ("extension-modules", False),
                ("startup", None),
            ),
            "quint-backends": (("cli", False), ("node", True), ("evaluator", True))
            if "run" in locator["subject"]
            else (("cli", False), ("node", True), ("apalache", False), ("java", True)),
            "cargo-toolchain": (("cargo", True), ("rustc", True), ("sysroot", False)),
            "kani-toolchain": (
                ("distribution", True),
                ("sysroot", False),
                ("backend", True),
                ("solver", True),
            ),
            "lean-toolchain": (("distribution", True),),
            "darwin-native": (("sdk-settings", False),),
            "node-toolchain": (("node", True), ("corepack", False), ("pnpm", False)),
        }[family]
        for label, executable in roots:
            _check(label in by_path, f"incomplete {family} root: {label}")
            if executable is not None:
                _check(
                    _root_has_bytes(by_path, label, executable=executable),
                    f"empty {family} verifier root: {label}",
                )

        if family == "darwin-native":
            _check(
                _root_has_bytes(by_path, "drivers", executable=True),
                "Darwin adapter has no selected driver bytes",
            )
            _check(
                value["system_dependencies"]["sdk"] is not None,
                "Darwin adapter missing SDK attestation",
            )
            settings = by_path["sdk-settings"]
            _check(
                settings["kind"] == "file"
                and settings["hash"]
                == value["system_dependencies"]["sdk"]["settings_hash"],
                "SDK settings identity contradicts recorded file",
            )
        if family == "quint-backends" and "verify" in locator["subject"]:
            _check(
                any(
                    name.startswith("apalache/")
                    and name.endswith(".jar")
                    and _file_has_bytes(entry)
                    for name, entry in by_path.items()
                ),
                "Apalache verifier archive bytes missing",
            )
        if family in ("quint-backends", "node-toolchain"):
            package_roots = [
                name
                for name, entry in by_path.items()
                if entry["kind"] == "directory"
                and name.startswith("packages/")
                and (
                    (
                        len(name.split("/")) == 3
                        and not name.split("/")[1].startswith("@")
                    )
                    or (
                        len(name.split("/")) == 4 and name.split("/")[1].startswith("@")
                    )
                )
            ]
            _check(package_roots, "Node package closure missing")
            for label in package_roots:
                _check(
                    _file_has_bytes(by_path.get(label + "/package.json")),
                    "Node package manifest bytes missing: " + label,
                )
        if family == "lean-toolchain":
            for label, entry in by_path.items():
                if (
                    entry["kind"] == "directory"
                    and label.startswith("packages/")
                    and len(label.split("/")) == 2
                ):
                    _check(
                        _root_has_bytes(by_path, label),
                        "empty Lean package root: " + label,
                    )
        if family not in ("cargo-toolchain", "kani-toolchain"):
            _check(not value["packages"], "Cargo packages on unrelated adapter")
    elif value["packages"]:
        raise V4Error("Cargo packages require selected Cargo/Kani adapter")
    elif value["kind"] == "executable":
        _check(
            _file_has_bytes(by_path.get("."), executable=True),
            "empty executable tool identity",
        )
    for package in value["packages"]:
        label = "packages/" + D("cargo-package", package)[7:]
        _check(
            _file_has_bytes(by_path.get(label + "/Cargo.toml")),
            "source-qualified package manifest bytes missing: " + label,
        )


def _tools(values, declarations=None, ids=None, environment=None):
    sorted_unique(values, lambda item: item["id"])
    by_id = {item["id"]: item for item in values}
    for value in values:
        declaration = (
            declarations.get(value["id"]) if declarations is not None else None
        )
        if declarations is not None and value["id"] != "fv-producer":
            _check(declaration is not None, "undeclared tool identity")
        if value["id"] == "fv-producer":
            _check(
                value["locator"]
                == {
                    "mode": "adapter",
                    "value": "producer-runtime",
                    "cwd": ".",
                    "subject": ["fv_evidence_run"],
                },
                "reserved producer tool identity mismatch",
            )
            _check(
                not value["requires"],
                "reserved producer tool has declared dependencies",
            )
        _tool(value, declaration, environment)
    visiting = set()
    done = set()

    def visit(identifier):
        _check(identifier in by_id, f"missing tool dependency: {identifier}")
        _check(identifier not in visiting, "cyclic tool dependency graph")
        if identifier in done:
            return
        visiting.add(identifier)
        for dep in by_id[identifier]["requires"]:
            visit(dep)
        visiting.remove(identifier)
        done.add(identifier)

    if ids is not None:
        for identifier in [*ids, "fv-producer"]:
            visit(identifier)
        _check(
            done == set(by_id),
            "descriptor tool closure differs from reviewed transitive closure",
        )
    else:
        for identifier in by_id:
            visit(identifier)


def _cache(value, recipe=None, source=None):
    validate("BuildCacheIdentity", value)
    if recipe is not None:
        declared = recipe["build_cache"]
        _check(
            (declared is None) == (value is None),
            "build-cache presence differs from recipe",
        )
        if declared is None:
            return
        _check(value["system"] == declared["system"], "build-cache system mismatch")
        _check(
            [entry["path"] for entry in value["configuration"]]
            == declared["configuration"],
            "build-cache configuration coverage mismatch",
        )
    if value is not None:
        sorted_unique(value["configuration"], lambda item: item["path"])
        sorted_unique(value["namespaces"], lambda item: item["role"])
        if source is not None:
            by_path = {item["path"]: item["hash"] for item in source["files"]}
            for entry in value["configuration"]:
                _check(
                    by_path.get(entry["path"]) == entry["hash"],
                    "build-cache configuration source hash mismatch",
                )
        for namespace in value["namespaces"]:
            if namespace["kind"] == "producer-fresh" and recipe is not None:
                _check(
                    recipe["attestation"] is not None,
                    "producer-fresh namespace lacks incorporated collector guarantee",
                )
                _check(
                    namespace["identity_hash"]
                    == D(
                        "cache-namespace-fresh",
                        {"recipe_id": recipe["recipe_id"], "role": namespace["role"]},
                    ),
                    "fresh cache namespace identity mismatch",
                )


def _common(value):
    validate("CommonBindings", value)
    sorted_unique(value["definition_files"], lambda item: item["path"])
    sorted_unique(value["required_targets"])


def _owned_tree(reader, directory, expected):
    target = reader.root / directory
    found = set()
    for base, directories, files in os.walk(target, followlinks=False):
        for name in directories:
            item = Path(base) / name
            _check(not item.is_symlink(), "symlink in immutable artifact directory")
        for name in files:
            item = (Path(base) / name).relative_to(reader.root).as_posix()
            _regular(reader.root, item, True)
            found.add(item)
    _check(
        found == set(expected), "immutable execution file inventory incomplete or extra"
    )


def _tool_file_at(by_path, relative):
    """Resolve a file in the recorded canonical view without using producer OS paths."""
    current = ""
    parts = relative.split("/")
    for index, part in enumerate(parts):
        current = part if current in ("", ".") else current + "/" + part
        entry = by_path.get(current)
        if entry is None:
            return None
        if index == len(parts) - 1:
            if entry["kind"] == "symlink-file":
                entry = by_path.get(entry["resolved_path"])
            return entry if entry is not None and entry["kind"] == "file" else None
        if entry["kind"] == "symlink-directory":
            current = entry["resolved_path"]
            entry = by_path.get(current)
        if entry is None or entry["kind"] != "directory":
            return None
    return None


def _package_policy(reader, tools, source):
    import tomllib

    lock_entries = []
    for entry in source["files"]:
        if entry["path"] == "Cargo.lock" or entry["path"].endswith("/Cargo.lock"):
            data = reader.read(entry["path"], False)
            _check(H(data) == entry["hash"], "current Cargo.lock differs from closure")
            try:
                lock_entries.extend(tomllib.loads(data.decode("utf-8"))["package"])
            except (KeyError, UnicodeError, tomllib.TOMLDecodeError) as error:
                raise V4Error("invalid Cargo.lock package provenance") from error
    for tool in tools:
        if tool["locator"]["mode"] != "adapter" or tool["locator"]["value"] not in (
            "cargo-toolchain",
            "kani-toolchain",
        ):
            continue
        subject = tool["locator"]["subject"]
        runtime_only = len(subject) == 1 or (
            len(subject) == 2 and subject[1].startswith("+")
        )
        _check(
            runtime_only or tool["packages"],
            "application adapter lacks source-qualified package graph",
        )
        by_path = None
        for package in tool["packages"]:
            package_source = package["source"]
            if package_source["kind"] == "path":
                directory = package_source["path"]
                manifest = (
                    "Cargo.toml" if directory == "." else directory + "/Cargo.toml"
                )
                _regular(reader.root, manifest)
                parsed = tomllib.loads(reader.read(manifest, False).decode("utf-8"))
                declaration = parsed.get("package", {})
                _check(
                    declaration.get("name") == package["name"],
                    "path package name differs from source manifest",
                )
                version = declaration.get("version")
                if isinstance(version, str):
                    _check(
                        version == package["version"],
                        "path package version differs from source manifest",
                    )
                prefix = "" if directory == "." else directory + "/"
                label = "packages/" + D("cargo-package", package)[7:]
                if by_path is None:
                    by_path = {entry["path"]: entry for entry in tool["files"]}
                # Only independently bound inputs are required, not generated cache products.
                for expected in source["files"]:
                    if not expected["path"].startswith(prefix):
                        continue
                    virtual = label + "/" + expected["path"][len(prefix) :]
                    supplied = _tool_file_at(by_path, virtual)
                    _check(
                        supplied is not None,
                        "bound path-package input missing from tool manifest: "
                        + expected["path"],
                    )
                    _check(
                        all(
                            supplied[key] == expected[key]
                            for key in ("hash", "size", "executable")
                        ),
                        "path package bytes differ from verified source closure: "
                        + expected["path"],
                    )
                continue
            matching = [
                entry
                for entry in lock_entries
                if entry.get("name") == package["name"]
                and entry.get("version") == package["version"]
                and entry.get("source") == package_source["id"]
            ]
            _check(matching, "recorded package not selected by bound Cargo.lock source")
            if package_source["kind"] == "registry":
                _check(
                    any(
                        entry.get("checksum") == package_source["checksum"]
                        for entry in matching
                    ),
                    "registry package checksum differs from bound lock",
                )


def _descriptor(value):
    validate("ExecutionDescriptor", value)
    _common(value["common"])
    _members(value["members"])
    _closure(value["closure"])
    _environment(value["environment"])
    _tools(value["toolchain"], environment=value["environment"])
    _cache(value["build_cache"], value["recipe"])
    distinct = value["distinct_slot"]
    if value["recipe"]["determinism"]["mode"] == "fixed":
        _check(distinct is None, "fixed descriptor has distinct slot")
    else:
        _check(
            distinct is not None
            and len(value["members"]) == 1
            and all(value["members"][0][key] == distinct[key] for key in distinct),
            "distinct descriptor member mismatch",
        )


def _ownership(reader, artifact):
    receipt = artifact["ownership"]
    windows = receipt["spawn_windows"]
    _check(
        len({item["window_id"] for item in windows}) == len(windows),
        "duplicate ownership window",
    )
    by_id = {item["window_id"]: item for item in windows}
    processes = set()
    hosted = set()
    registrations = [entry["process"] for entry in receipt["children"]]
    for window in windows:
        _check(
            window["execution_key"] == artifact["execution_key"]
            and window["attempt_id"] == artifact["attempt_id"],
            "ownership window has foreign attempt scope",
        )
        if window["parent"] is not None:
            _check(
                window["parent"] in registrations,
                "ownership window parent is not retained",
            )
    for registration in receipt["children"]:
        process = registration["process"]
        identity = (process["pid"], process["process_start_id"])
        _check(identity not in processes, "duplicate retained owned process")
        processes.add(identity)
        window = by_id.get(registration["window_id"])
        _check(window is not None, "owned child refers to missing window")
        _check(
            process["pid"] == process["process_group"] == process["session_id"],
            "owned registration is not original session/group leader",
        )
        if window["parent"] is not None:
            _check(
                process["parent_pid"] == window["parent"]["pid"],
                "hosted child parent binding mismatch",
            )
            hosted.add(process["pid"])
        _check(
            registration["registered_at"] >= artifact["started_at"],
            "ownership registration before execution",
        )
        if registration["terminated_at"] is not None:
            _check(
                registration["registered_at"]
                <= registration["terminated_at"]
                <= artifact["finished_at"],
                "invalid ownership termination interval",
            )
        if artifact["result"] == "PASS":
            _check(
                registration["terminated_at"] is not None,
                "PASS has unterminated owned child",
            )
    protocol = receipt["protocol_log"]
    log = reader.ref(protocol) if protocol is not None else None
    if artifact["result"] == "PASS":
        _check(
            windows
            and receipt["children"]
            and all(item["state"] == "closed" for item in windows),
            "PASS lacks complete closed native ownership",
        )
        if artifact["descriptor"]["recipe"]["ownership_protocol"] is not None:
            _check(
                any(
                    item["protocol"] == "dossier-quint-private-pipes/v1"
                    for item in windows
                )
                and log is not None,
                "collector lacks private ownership protocol",
            )
            _check(not log or log.endswith(b"\n"), "partial ownership control message")
            owned, released = set(), set()
            for line in log.split(b"\n")[:-1]:
                _check(
                    0 < len(line) <= 4096, "invalid ownership control message length"
                )
                message = parse_json(line)
                validate(
                    {"event": ("enum", ("owned", "released")), "pgid": "positive"},
                    message,
                )
                pgid = message["pgid"]
                if message["event"] == "owned":
                    _check(
                        pgid not in owned, "duplicate private ownership registration"
                    )
                    owned.add(pgid)
                else:
                    _check(
                        pgid in owned and pgid not in released,
                        "out-of-order private ownership release",
                    )
                    released.add(pgid)
            _check(
                owned == released == hosted,
                "private protocol/retained process accounting mismatch",
            )


def _raw(stdout, stderr, termination, result):
    data = b""
    for stream in (stdout, stderr):
        if stream:
            data += stream + (b"" if stream.endswith(b"\n") else b"\n")
    normal = (
        termination["exit_code"] is not None
        and termination["signal"] is None
        and not termination["timed_out"]
        and not termination["cancelled"]
    )
    if normal:
        data += f"--- fv-evidence: exit={termination['exit_code']} ---\n".encode()
    else:
        _check(
            result in ("ERROR", "CANCELLED"), "abnormal termination has normal result"
        )
        data += f"--- fv-evidence-v4: result={result} ---\n".encode()
    return data


def _execution(reader, ref):
    if ref["path"] in reader.artifacts:
        saved_ref, artifact = reader.artifacts[ref["path"]]
        _check(saved_ref == ref, "conflicting execution reference")
        return artifact
    artifact = reader.json_ref(ref, "ExecutionArtifact", "ExecutionRef")
    _identity(artifact, "artifact_id", "execution-artifact")
    descriptor = artifact["descriptor"]
    _descriptor(descriptor)
    _check(
        artifact["execution_key"] == D("execution-key", descriptor),
        "execution key mismatch",
    )
    _check(
        ref["execution_key"] == artifact["execution_key"]
        and ref["artifact_id"] == artifact["artifact_id"],
        "execution reference canonical identities mismatch",
    )
    directory = (
        f"{BASE}/executions/{artifact['execution_key'][7:]}/{artifact['attempt_id']}"
    )
    _check(
        ref["path"] == directory + "/execution.json",
        "execution artifact owner path mismatch",
    )
    _check(
        artifact["started_at"] <= artifact["finished_at"], "reversed execution interval"
    )
    _input_state(artifact["source_before"])
    if artifact["source_after"] is not None:
        _input_state(artifact["source_after"])
    _check(
        descriptor["verified_inputs_policy_hash"]
        == artifact["source_before"]["verified_inputs_policy_hash"]
        and descriptor["inventory_hash"] == artifact["source_before"]["inventory_hash"],
        "execution source descriptor binding mismatch",
    )
    source = {item["path"]: item for item in artifact["source_before"]["files"]}
    _check(
        all(
            source.get(item["path"]) == item for item in descriptor["closure"]["files"]
        ),
        "closure not contained in original source scan",
    )
    _check(
        descriptor["closure"]
        == _effective_closure(
            descriptor["recipe"], artifact["source_before"], descriptor["common"]
        ),
        "original execution source closure is incomplete",
    )
    for entry in [
        *descriptor["common"]["definition_files"],
        {
            "path": descriptor["common"]["intent_path"],
            "hash": descriptor["common"]["intent_hash"],
        },
        {
            "path": descriptor["common"]["manifest_path"],
            "hash": descriptor["common"]["manifest_hash"],
        },
    ]:
        _check(
            entry["path"] in source and source[entry["path"]]["hash"] == entry["hash"],
            "common binding differs from original input inventory",
        )
    if descriptor["common"]["dispatch_hash"] is not None:
        _check(
            source.get(fv_project.DISPATCH_RELATIVE, {}).get("hash")
            == descriptor["common"]["dispatch_hash"],
            "dispatch binding differs from original source inventory",
        )
    _cache(descriptor["build_cache"], descriptor["recipe"], artifact["source_before"])
    streams = []
    for field, filename in (
        ("stdout", "stdout.bin"),
        ("stderr", "stderr.bin"),
        ("raw_output", "raw.log"),
    ):
        _check(
            artifact[field]["path"] == directory + "/" + filename,
            "execution stream owner path mismatch",
        )
        streams.append(reader.ref(artifact[field]))
    _check(
        streams[2]
        == _raw(streams[0], streams[1], artifact["termination"], artifact["result"]),
        "raw output differs from exact captured streams/termination",
    )
    valid_utf8 = True
    reserved = False
    text = ""
    try:
        for stream in streams[:2]:
            decoded = stream.decode("utf-8", errors="strict")
            reserved = reserved or any(
                re.fullmatch(r"--- fv-evidence(?:-v4)?: (?:exit=|result=).* ---", line)
                for line in decoded.splitlines()
            )
        text = streams[2].decode("utf-8", errors="strict")
    except UnicodeError:
        valid_utf8 = False
    _check(
        (valid_utf8 and not reserved) or artifact["result"] in ("ERROR", "CANCELLED"),
        "invalid stream grammar with normal result",
    )
    recipe = descriptor["recipe"]
    marker = recipe["pass_marker"]
    matched = (
        valid_utf8
        and not reserved
        and (
            marker in text
            if marker is not None
            else any(item in text for item in MARKERS[recipe["evidence_class"]])
        )
    )
    _check(
        artifact["marker_matched"] == matched,
        "recorded marker result differs from raw bytes",
    )
    sorted_unique(artifact["attachments"], lambda item: item["path"])
    for attachment in artifact["attachments"]:
        _check(
            attachment["path"].startswith(directory + "/attachments/"),
            "attachment has foreign execution owner",
        )
        reader.ref(attachment)
    _ownership(reader, artifact)
    producer = next(
        (item for item in descriptor["toolchain"] if item["id"] == "fv-producer"), None
    )
    _check(producer is not None, "execution has no producer identity")
    implementation = [
        {"path": item["path"][len("implementation/") :], "hash": item["hash"]}
        for item in producer["files"]
        if item["kind"] == "file" and item["path"].startswith("implementation/")
    ]
    _check(
        implementation
        and artifact["producer"]["implementation_hash"]
        == D("producer-implementation", implementation),
        "producer implementation binding mismatch",
    )
    if artifact["result"] == "PASS":
        _check(valid_utf8 and matched, "PASS invalid UTF-8 or absent marker")
        _check(
            artifact["termination"]
            == {"exit_code": 0, "signal": None, "timed_out": False, "cancelled": False},
            "PASS did not actually terminate normally with exit zero",
        )
        _check(
            artifact["source_before"]["clean"]
            and artifact["source_after"] == artifact["source_before"],
            "PASS unstable or dirty execution inputs",
        )
        _check(
            artifact["toolchain_after"] == descriptor["toolchain"]
            and artifact["environment_after"] == descriptor["environment"]
            and artifact["build_cache_after"] == descriptor["build_cache"],
            "PASS missing or changed tool/environment/cache endpoint",
        )
    elif artifact["result"] == "FAIL":
        _check(
            valid_utf8
            and artifact["termination"]["exit_code"] is not None
            and artifact["termination"]["signal"] is None
            and not artifact["termination"]["cancelled"]
            and not artifact["termination"]["timed_out"],
            "FAIL without actual normal command result",
        )
        _check(
            artifact["termination"]["exit_code"] != 0 or not matched,
            "FAIL contradicts zero exit and marker",
        )
    if artifact["toolchain_after"] is not None:
        _tools(artifact["toolchain_after"])
    if artifact["environment_after"] is not None:
        _environment(artifact["environment_after"])
    _cache(artifact["build_cache_after"])
    owned_refs = [
        ref["path"],
        artifact["stdout"]["path"],
        artifact["stderr"]["path"],
        artifact["raw_output"]["path"],
        *(entry["path"] for entry in artifact["attachments"]),
    ]
    if artifact["ownership"]["protocol_log"] is not None:
        protocol_ref = artifact["ownership"]["protocol_log"]
        _check(
            protocol_ref["path"].startswith(directory + "/attachments/"),
            "ownership protocol log has foreign execution owner",
        )
        owned_refs.append(protocol_ref["path"])
    _owned_tree(reader, directory, owned_refs)
    reader.artifacts[ref["path"]] = (ref, artifact)
    return artifact


def validate_execution_artifact(root, ref):
    return _execution(Reader(root), ref)


def _pointer(value, pointer):
    current = value
    if pointer == "":
        return current
    for token in pointer[1:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            _check(token in current, "observation pointer missing object key")
            current = current[token]
        elif isinstance(current, list):
            _check(
                re.fullmatch(r"0|[1-9][0-9]*", token) is not None
                and int(token) < len(current),
                "observation pointer missing array index",
            )
            current = current[int(token)]
        else:
            raise V4Error("observation pointer traverses scalar")
    _check(isinstance(current, (dict, list)), "observation pointer resolves to scalar")
    return current


def _policy(reader, relative, manifest_path=None):
    policy = parse_json(reader.read(relative, False))
    validate("Policy", policy)
    _check(policy["jobs"]["max"] >= 2, "policy jobs maximum below two")
    _check(
        policy["claim_checker"]["timeout_seconds"] is not None,
        "observation checker has no finite timeout",
    )
    sorted_unique(policy["definition_files"])
    env = policy["environment"]
    sorted_unique(env["platforms"], lambda item: (item["os"], item["arch"]))
    for field in ("inherit", "identity"):
        sorted_unique(env[field])
    _check(
        env["identity"]
        == sorted(
            set(env["inherit"]) | set(env["set"]), key=lambda name: name.encode("utf-8")
        ),
        "sanitized identity is not inherit union set",
    )
    _check(
        "DOSSIER_QUINT_OWNERSHIP_FDS" not in env["identity"],
        "reserved ownership control variable in semantic environment",
    )
    declarations = {}
    for declaration in policy["toolchains"]:
        identifier = declaration["id"]
        _check(
            identifier != "fv-producer" and identifier not in declarations,
            "duplicate or reserved tool declaration",
        )
        declarations[identifier] = declaration
        sorted_unique(declaration["requires"])
        sorted_unique(declaration["accept"]["sha256"])
        _check(
            (declaration["version_command"] is None)
            == (declaration["version_cwd"] is None),
            "version command/cwd null mismatch",
        )
        _check(
            declaration["version_command"] is not None
            or not declaration["accept"]["version_contains"],
            "version pin has no declared probe",
        )
    visiting = set()
    seen = set()

    def visit(identifier):
        _check(
            identifier in declarations and identifier not in visiting,
            "unknown or cyclic declared tool closure",
        )
        if identifier in seen:
            return
        visiting.add(identifier)
        for dependency in declarations[identifier]["requires"]:
            visit(dependency)
        visiting.remove(identifier)
        seen.add(identifier)

    for identifier in declarations:
        visit(identifier)
    checks = [*policy["preflight"], policy["claim_checker"]]
    _check(
        len({item["id"] for item in checks}) == len(checks),
        "duplicate policy checker ID",
    )
    for check in checks:
        sorted_unique(check["resources"])
        sorted_unique(check["toolchain"])
        for identifier in check["toolchain"]:
            visit(identifier)
    recipes = {}
    mandatory = {
        relative,
        policy["intent_path"],
        policy["manifest_path"],
        *policy["definition_files"],
    }
    if (reader.root / fv_project.DISPATCH_RELATIVE).exists():
        mandatory.add(fv_project.DISPATCH_RELATIVE)
    if (reader.root / policy["verified_inputs"]).exists():
        mandatory.add(policy["verified_inputs"])
    for recipe in policy["recipes"]:
        identifier = recipe["recipe_id"]
        _check(identifier not in recipes, "duplicate recipe ID")
        recipes[identifier] = recipe
        for field in ("toolchain", "resources", "retained_environment"):
            sorted_unique(recipe[field])
        closure = recipe["source_closure"]
        sorted_unique(closure["prefixes"])
        sorted_unique(closure["basis"])
        if closure["mode"] == "verified-inputs":
            _check(not closure["prefixes"], "whole-input recipe declares prefixes")
        mandatory.update(closure["basis"])
        for identifier in recipe["toolchain"]:
            visit(identifier)
        cache = recipe["build_cache"]
        if cache is not None:
            sorted_unique(cache["configuration"])
            sorted_unique(cache["resources"])
            _check(
                set(cache["resources"]) <= set(recipe["resources"]),
                "cache resources not held by recipe",
            )
            mandatory.update(cache["configuration"])
        attestation = recipe["attestation"]
        if attestation is not None:
            mandatory.add(attestation["path"])
        _check(
            not recipe["retained_environment"] or attestation is not None,
            "retained environment lacks collector contract",
        )
    records = {}
    members = {identifier: [] for identifier in recipes}
    for record in policy["records"]:
        _check(record["claim_id"] not in records, "duplicate policy claim ID")
        records[record["claim_id"]] = record
        _check(
            len({slot["slot_id"] for slot in record["executions"]})
            == len(record["executions"])
            and len({slot["tool"] for slot in record["executions"]})
            == len(record["executions"]),
            "duplicate claim slot/tool",
        )
        for slot in record["executions"]:
            _check(slot["recipe_id"] in recipes, "undeclared slot recipe")
            binding = slot["observation_binding"]
            mandatory.add(binding["path"])
            definition = parse_json(reader.read(binding["path"], False))
            _pointer(definition, binding["pointer"])
            members[slot["recipe_id"]].append(
                {
                    "claim_id": record["claim_id"],
                    "slot_id": slot["slot_id"],
                    "tool": slot["tool"],
                }
            )
    for identifier, entries in members.items():
        _check(entries, "recipe has no reviewed members")
        entries.sort(
            key=lambda item: (
                item["claim_id"].encode("utf-8"),
                item["slot_id"].encode("utf-8"),
            )
        )
    import check_evidence_records as legacy

    canonical = reader.root / policy["manifest_path"]
    if manifest_path is not None:
        _check(
            Path(manifest_path).resolve() == canonical.resolve(),
            "v4 manifest override is not canonical",
        )
    manifest = parse_json(reader.read(policy["manifest_path"], False))
    required, kinds, evidence, dependencies = legacy.load_manifest(canonical)
    raw_entries = {
        item["id"]: item
        for collection, _ in legacy.OBLIGATION_COLLECTIONS
        for item in manifest.get(collection, [])
    }
    for identifier, record in records.items():
        _check(identifier in kinds, "policy claim absent from canonical manifest")
        _check(
            record["required"] == raw_entries[identifier].get("required", True),
            "policy required status differs from manifest",
        )
        _check(
            record["evidence_class"]
            in legacy.OBLIGATION_EVIDENCE_COMPATIBILITY[kinds[identifier]],
            "policy record class incompatible with obligation kind",
        )
        for slot in record["executions"]:
            _check(
                recipes[slot["recipe_id"]]["evidence_class"]
                in legacy.OBLIGATION_EVIDENCE_COMPATIBILITY[kinds[identifier]],
                "recipe class incompatible with member obligation kind",
            )
        if identifier in evidence:
            _check(
                set(slot["tool"] for slot in record["executions"])
                == set(evidence[identifier]),
                "policy required evidence coverage differs from canonical manifest",
            )
        _check(
            set(dependencies.get(identifier, [])) <= set(records),
            "policy omits canonical dependency",
        )
    target = fv_project.repo_relative(
        reader.root, fv_project.resolve_target(reader.root)
    )
    _check(
        target == policy["intent_path"],
        "policy intent differs from canonical dispatch target",
    )
    if fv_project.DISPATCH_RELATIVE in mandatory:
        parse_json(reader.read(fv_project.DISPATCH_RELATIVE, False))
    for filename in mandatory:
        _check(
            not fv_project.matches_prefixes(filename, fv_project.DEFAULT_EXCLUSIONS),
            "mandatory source is structural output",
        )
        reader.read(filename, False)
    common = {
        "policy_path": relative,
        "policy_hash": D("policy", policy),
        "intent_path": target,
        "intent_hash": H(reader.read(target, False)),
        "manifest_path": policy["manifest_path"],
        "manifest_hash": H(reader.read(policy["manifest_path"], False)),
        "definition_files": [
            {"path": filename, "hash": H(reader.read(filename, False))}
            for filename in policy["definition_files"]
        ],
        "dispatch_hash": H(reader.read(fv_project.DISPATCH_RELATIVE, False))
        if fv_project.DISPATCH_RELATIVE in mandatory
        else None,
        "required_targets": sorted(
            required, key=lambda identifier: identifier.encode("utf-8")
        ),
    }
    return (
        policy,
        common,
        mandatory,
        recipes,
        records,
        members,
        declarations,
        kinds,
        evidence,
        dependencies,
    )


def _git(root, arguments):
    result = subprocess.run(
        ["git", *arguments],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    _check(
        result.returncode == 0,
        "cannot recompute git source state: "
        + result.stderr.decode("utf-8", errors="replace"),
    )
    return result.stdout


def _current_inputs(reader, policy, mandatory):
    inputs_policy = fv_project.load_policy(reader.root)
    candidates = _git(
        reader.root, ["ls-files", "--cached", "--others", "--exclude-standard", "-z"]
    )
    names = [
        entry.decode("utf-8", errors="strict")
        for entry in candidates.split(b"\0")
        if entry
    ]
    selected = {name for name in names if inputs_policy.selects(name)} | set(mandatory)
    stages = _git(reader.root, ["ls-files", "--stage", "-z"])
    for entry in stages.split(b"\0"):
        if not entry:
            continue
        header, name = entry.split(b"\t", 1)
        relative = name.decode("utf-8", errors="strict")
        descendant_selected = inputs_policy.mode == fv_project.MODE_INCLUDE and any(
            fv_project.matches_prefixes(prefix.rstrip("/"), [relative + "/"])
            for prefix in inputs_policy.prefixes
        )
        if relative in selected or descendant_selected:
            _check(
                header.split(b" ", 1)[0] != b"160000",
                "selected gitlink is not enumerated source",
            )
    files = []
    for name in fv_project.order_inputs(tuple(selected)):
        target, info = _regular(reader.root, name)
        _check(info.st_nlink == 1, "source file has hardlinks: " + name)
        data = reader.read(name, False)
        files.append(
            {
                "path": name,
                "hash": H(data),
                "size": len(data),
                "executable": bool(info.st_mode & 0o111),
            }
        )
    dirty = False
    status = _git(
        reader.root, ["status", "--porcelain", "--untracked-files=all", "-z"]
    ).split(b"\0")
    index = 0
    while index < len(status):
        entry = status[index]
        index += 1
        if not entry:
            continue
        _check(len(entry) >= 4 and entry[2:3] == b" ", "invalid git status framing")
        affected = [entry[3:].decode("utf-8", errors="strict")]
        if b"R" in entry[:2] or b"C" in entry[:2]:
            _check(index < len(status) and status[index], "truncated rename status")
            affected.append(status[index].decode("utf-8", errors="strict"))
            index += 1
        if any(
            name in selected or name in mandatory or inputs_policy.selects(name)
            for name in affected
        ):
            dirty = True
    input_file = reader.root / policy["verified_inputs"]
    policy_hash = (
        H(reader.read(policy["verified_inputs"], False))
        if input_file.exists()
        else D(
            "verified-inputs-default",
            {
                "mode": "exclude",
                "prefixes": [],
                "structural": list(fv_project.DEFAULT_EXCLUSIONS),
            },
        )
    )
    state = {
        "verified_inputs_policy_hash": policy_hash,
        "inventory_hash": D(
            "inventory",
            [
                {"path": entry["path"], "executable": entry["executable"]}
                for entry in files
            ],
        ),
        "source_snapshot": H(
            b"".join(
                entry["path"].encode("utf-8")
                + b"\0"
                + entry["hash"][7:].encode("ascii")
                + b"\n"
                for entry in files
            )
        ),
        "clean": not dirty,
        "files": files,
    }
    _input_state(state)
    for recipe in policy["recipes"]:
        for prefix in recipe["source_closure"]["prefixes"]:
            _check(
                any(
                    fv_project.matches_prefixes(entry["path"], [prefix])
                    for entry in files
                ),
                "required closure prefix has no covered source",
            )
    return state


def _effective_closure(recipe, state, common):
    closure = recipe["source_closure"]
    mode = closure["mode"] if closure["basis"] else "verified-inputs"
    prefixes = closure["prefixes"] if mode == "prefixes" else []
    mandatory = {
        common["policy_path"],
        common["intent_path"],
        common["manifest_path"],
        *(entry["path"] for entry in common["definition_files"]),
        *closure["basis"],
    }
    if common["dispatch_hash"] is not None:
        mandatory.add(fv_project.DISPATCH_RELATIVE)
    if recipe["build_cache"] is not None:
        mandatory.update(recipe["build_cache"]["configuration"])
    files = (
        state["files"]
        if mode == "verified-inputs"
        else [
            entry
            for entry in state["files"]
            if entry["path"] in mandatory
            or fv_project.matches_prefixes(entry["path"], prefixes)
        ]
    )
    _check(
        mandatory <= {entry["path"] for entry in files},
        "missing original closure binding input",
    )
    body = {
        "mode": mode,
        "prefixes": prefixes,
        "basis": closure["basis"],
        "files": files,
    }
    return {**body, "hash": D("source-closure", body)}


def _current_descriptor(
    reader, artifact, common, policy, recipes, members, declarations, state
):
    descriptor = artifact["descriptor"]
    recipe = recipes.get(descriptor["recipe"]["recipe_id"])
    _check(
        recipe is not None and descriptor["recipe"] == recipe,
        "stale or rebound recipe definition",
    )
    _check(
        descriptor["common"] == common,
        "stale common policy/intent/manifest/definition/dispatch binding",
    )
    expected = members[recipe["recipe_id"]]
    if recipe["determinism"]["mode"] == "distinct":
        distinct = descriptor["distinct_slot"]
        expected = [
            entry
            for entry in expected
            if entry["claim_id"] == distinct["claim_id"]
            and entry["slot_id"] == distinct["slot_id"]
        ]
    _check(
        descriptor["members"] == expected, "descriptor omits or adds reviewed members"
    )
    _environment(descriptor["environment"], policy)
    _tools(
        descriptor["toolchain"],
        declarations,
        recipe["toolchain"],
        descriptor["environment"],
    )
    if state is not None:
        _check(state["clean"], "current selected source state is dirty")
        _check(
            descriptor["verified_inputs_policy_hash"]
            == state["verified_inputs_policy_hash"]
            and descriptor["inventory_hash"] == state["inventory_hash"],
            "stale global inventory or verified-input policy",
        )
        _check(
            descriptor["closure"] == _effective_closure(recipe, state, common),
            "stale source dependency closure",
        )
        _cache(descriptor["build_cache"], recipe, state)
        _package_policy(reader, descriptor["toolchain"], state)


def _observation(reader, ref):
    if ref["path"] in reader.checks:
        saved_ref, check, request, response, usable = reader.checks[ref["path"]]
        _check(saved_ref == ref, "conflicting observation receipt reference")
        return check, request, response, usable
    check = reader.json_ref(ref, "ObservationCheck")
    request = reader.json_ref(check["request"], "ObservationRequest")
    match = re.fullmatch(
        re.escape(BASE) + r"/runs/([0-9a-f-]+)/observations/([^/]+)/([^/]+)/check.json",
        ref["path"],
    )
    _check(match is not None, "observation check owner path mismatch")
    validate({"run_id": "uuid"}, {"run_id": match[1]})
    directory = ref["path"].rsplit("/", 1)[0]
    _check(
        match[2] == request["claim_id"] and match[3] == request["request_id"],
        "observation request owner mismatch",
    )
    _check(
        check["request"]["path"] == directory + "/request.json",
        "observation request path mismatch",
    )
    _check(
        request["policy_path"] == request["common"]["policy_path"]
        and request["policy_hash"] == request["common"]["policy_hash"],
        "observation common policy mismatch",
    )
    _check(
        len({item["slot_id"] for item in request["slots"]}) == len(request["slots"]),
        "duplicate observation request slot",
    )
    _check(
        request["created_at"] <= check["started_at"] <= check["finished_at"],
        "observation checker interval contradiction",
    )
    _input_state(check["source_before"])
    if check["source_after"] is not None:
        _input_state(check["source_after"])
    _tools(check["toolchain"])
    valid_streams = True
    for field in ("stdout", "stderr"):
        _check(
            check[field]["path"] == directory + "/" + field + ".bin",
            "checker output has foreign owner/name",
        )
        data = reader.ref(check[field])
        try:
            data.decode("utf-8", errors="strict")
        except UnicodeError:
            valid_streams = False
    for slot in request["slots"]:
        artifact = _execution(reader, slot["execution"])
        _check(
            artifact["result"] == "PASS",
            "observation requested nonpassing physical execution",
        )
        _check(
            artifact["descriptor"]["common"] == request["common"]
            and artifact["descriptor"]["recipe"]["recipe_id"] == slot["recipe_id"],
            "observation request execution definition mismatch",
        )
        _check(
            {
                "claim_id": request["claim_id"],
                "slot_id": slot["slot_id"],
                "tool": slot["tool"],
            }
            in artifact["descriptor"]["members"],
            "observation request member outside original descriptor",
        )
    response = None
    if check["response"] is not None:
        _check(
            check["response"]["path"] == directory + "/response.json",
            "observation response owner mismatch",
        )
        response_bytes = reader.ref(check["response"])
        try:
            response = parse_json(response_bytes)
            _response(request, check["request"]["hash"], response)
            _check(
                check["started_at"]
                <= response["started_at"]
                <= response["finished_at"]
                <= check["finished_at"],
                "response/check interval contradiction",
            )
        except V4Error:
            if check["result"] not in ("ERROR", "CANCELLED"):
                raise
            response = None
    aggregate = (
        None
        if response is None
        else "FAIL"
        if any(slot["result"] == "FAIL" for slot in response["slots"])
        else "ERROR"
        if any(slot["result"] == "ERROR" for slot in response["slots"])
        else "PASS"
    )
    usable = (
        valid_streams
        and response is not None
        and check["result"] == aggregate
        and check["termination"]
        == {"exit_code": 0, "signal": None, "timed_out": False, "cancelled": False}
        and check["source_before"]["clean"]
        and check["source_after"] is not None
        and check["source_after"]["clean"]
        and check["source_before"] == check["source_after"]
    )
    if check["result"] in ("PASS", "FAIL"):
        _check(
            usable,
            "assessed observation has invalid transport, endpoints or response aggregate",
        )
    reader.checks[ref["path"]] = (ref, check, request, response, usable)
    return check, request, response, usable


def _observation_outcome(check, response, slot_id, usable, artifact):
    slot = next(
        (
            value
            for value in (response or {}).get("slots", [])
            if value["slot_id"] == slot_id
        ),
        None,
    )
    if usable and slot is not None:
        if slot["result"] in ("PASS", "FAIL"):
            descriptor = artifact["descriptor"]
            source = check["source_before"]
            _check(
                source["inventory_hash"] == descriptor["inventory_hash"]
                and source["verified_inputs_policy_hash"]
                == descriptor["verified_inputs_policy_hash"],
                "observation source inventory differs from actual execution",
            )
            files = {value["path"]: value for value in source["files"]}
            _check(
                all(
                    files.get(value["path"]) == value
                    for value in descriptor["closure"]["files"]
                ),
                "observation source closure differs from actual execution",
            )
            producer = next(
                (
                    tool
                    for tool in descriptor["toolchain"]
                    if tool["id"] == "fv-producer"
                ),
                None,
            )
            checker_producer = next(
                (tool for tool in check["toolchain"] if tool["id"] == "fv-producer"),
                None,
            )
            _check(
                producer is not None and producer == checker_producer,
                "observation producer differs from actual execution",
            )
        return slot["result"], slot
    _check(
        check["result"] in ("ERROR", "CANCELLED"),
        "observation receipt has no valid member assessment",
    )
    return check["result"], slot


def _response(request, request_hash, response):
    validate("ObservationResponse", response)
    _check(
        response["request_id"] == request["request_id"]
        and response["request_hash"] == request_hash
        and response["claim_id"] == request["claim_id"],
        "observation response request identity mismatch",
    )
    _check(
        [slot["slot_id"] for slot in response["slots"]]
        == [slot["slot_id"] for slot in request["slots"]],
        "observation response missing/extra/reordered slots",
    )
    _check(
        request["created_at"] <= response["started_at"] <= response["finished_at"],
        "observation response interval invalid",
    )


def _history_event(reader, event):
    execution = event["execution"]
    artifact = None
    if execution is not None:
        artifact = _execution(reader, execution)
        _check(
            artifact["execution_key"] == event["execution_key"]
            and artifact["attempt_id"] == event["attempt_id"]
            and artifact["descriptor"]["members"] == event["members"],
            "history execution original membership mismatch",
        )
    if event["kind"] == "execution":
        _check(
            event["claim_id"] is None
            and event["slot_id"] is None
            and event["observation"] is None
            and event["indeterminate_owner"] is None,
            "execution event carries observation/owner fields",
        )
        _check(
            execution is not None or event["result"] != "PASS",
            "PASS history has no physical receipt",
        )
        if artifact is not None:
            _check(
                artifact["result"] == event["result"],
                "history physical result contradiction",
            )
    elif event["kind"] == "observation":
        selected = [
            item
            for item in event["members"]
            if item["claim_id"] == event["claim_id"]
            and item["slot_id"] == event["slot_id"]
        ]
        _check(
            len(selected) == 1 and event["indeterminate_owner"] is None,
            "observation history selected member mismatch",
        )
        _check(
            event["observation"] is not None or event["result"] != "PASS",
            "PASS history has no observation receipt",
        )
        if event["observation"] is not None:
            check, request, response, usable = _observation(
                reader, event["observation"]
            )
            slots = [
                slot for slot in request["slots"] if slot["slot_id"] == event["slot_id"]
            ]
            _check(
                request["claim_id"] == event["claim_id"]
                and len(slots) == 1
                and slots[0]["execution"] == execution
                and slots[0]["tool"] == selected[0]["tool"],
                "history observation original request mismatch",
            )
            result, _ = _observation_outcome(
                check, response, event["slot_id"], usable, artifact
            )
            _check(
                result == event["result"],
                "history observation member result contradiction",
            )
    else:
        _check(
            event["result"] in ("ERROR", "CANCELLED")
            and event["indeterminate_owner"] is not None
            and event["observation"] is None,
            "indeterminate history shape contradiction",
        )
        owner_ref = event["indeterminate_owner"]
        owner = reader.json_ref(owner_ref, "Owner")
        _check(
            owner_ref["path"]
            == BASE + "/recovered-owners/" + owner["owner_id"] + ".json",
            "recovered owner immutable path mismatch",
        )
        pending = [
            item
            for item in owner["pending_results"]
            if item["execution_key"] == event["execution_key"]
            and item["attempt_id"] == event["attempt_id"]
            and item["members"] == event["members"]
            and item["claim_id"] == event["claim_id"]
            and item["slot_id"] == event["slot_id"]
        ]
        _check(len(pending) == 1, "indeterminate history lacks original PendingResult")


def _history(reader, captured):
    validate("HistoryView", captured)
    directory = reader.root / BASE / "history"
    refs, events, errors = [], [], []
    if directory.exists():
        _check(
            not directory.is_symlink() and directory.is_dir(),
            "history directory unsafe",
        )
        names = sorted(entry.name for entry in directory.iterdir())
        for index, name in enumerate(names, 1):
            _check(
                name == f"{index:020d}.json",
                "unknown entry or noncontiguous retained history",
            )
            relative = BASE + "/history/" + name
            data = reader.read(relative)
            event = parse_json(data)
            validate("HistoryEvent", event)
            _identity(event, "event_id", "history-event")
            _members(event["members"])
            _check(
                event["sequence"] == index
                and event["previous"] == (refs[-1] if refs else None),
                "history chain sequence/previous contradiction",
            )
            ref = {
                "sequence": index,
                "event_id": event["event_id"],
                "path": relative,
                "hash": H(data),
            }
            try:
                _history_event(reader, event)
                if event["kind"] == "observation":
                    prior = [
                        item
                        for item in events
                        if item["kind"] == "execution"
                        and item["execution"] == event["execution"]
                        and item["execution_key"] == event["execution_key"]
                        and item["attempt_id"] == event["attempt_id"]
                    ]
                    _check(
                        prior and prior[-1]["result"] == "PASS",
                        "observation history precedes actual physical PASS",
                    )
                events.append(event)
            except (V4Error, OSError, UnicodeError, KeyError, TypeError) as error:
                errors.append(f"history {index}: {error}")
            refs.append(ref)
    _check(
        captured["events"] == refs[: len(captured["events"])]
        and captured["head"]
        == (captured["events"][-1] if captured["events"] else None),
        "captured history is not consistent prefix of supplied full store",
    )
    accounted = {
        (event["execution_key"][7:], event["attempt_id"])
        for event in events
        if event["execution"] is not None or event["kind"] == "indeterminate"
    }
    attempts = reader.root / BASE / "executions"
    if attempts.exists():
        _check(not attempts.is_symlink(), "execution index is symlink")
        for key in attempts.iterdir():
            _check(
                key.is_dir()
                and not key.is_symlink()
                and re.fullmatch(r"[0-9a-f]{64}", key.name),
                "unknown execution-key entry",
            )
            for attempt in key.iterdir():
                _check(
                    attempt.is_dir() and not attempt.is_symlink(),
                    "unsafe committed attempt directory",
                )
                if (attempt / "execution.json").exists() and (
                    key.name,
                    attempt.name,
                ) not in accounted:
                    errors.append(
                        "unaccounted committed execution attempt: "
                        + str(attempt.relative_to(reader.root))
                    )
    return {"head": refs[-1] if refs else None, "events": refs}, events, errors


def _applicable(event, claim_id, tool):
    if event["kind"] == "observation" or (
        event["kind"] == "indeterminate" and event["claim_id"] is not None
    ):
        return event["claim_id"] == claim_id and any(
            member["claim_id"] == claim_id
            and member["slot_id"] == event["slot_id"]
            and member["tool"] == tool
            for member in event["members"]
        )
    return any(
        member["claim_id"] == claim_id and member["tool"] == tool
        for member in event["members"]
    )


def _barrier_applies(event, claim_id, tool):
    return (
        event["result"] == "FAIL" or event["kind"] == "indeterminate"
    ) and _applicable(event, claim_id, tool)


def _outside_policy_history(row, events, refs, canonical_tools):
    identifier = row["claim_id"]
    tools = (
        set(canonical_tools)
        if canonical_tools
        else {
            member["tool"]
            for event in events
            for member in event["members"]
            if member["claim_id"] == identifier
        }
    )
    associations = []
    blockers = {}
    for tool in sorted(tools, key=lambda value: value.encode("utf-8")):
        applicable = [
            event for event in events if _barrier_applies(event, identifier, tool)
        ]
        history_refs = [refs[event["sequence"] - 1] for event in applicable]
        state = (
            "FAIL"
            if any(event["result"] == "FAIL" for event in applicable)
            else "ERROR"
            if applicable
            else "MISSING"
        )
        associations.append(
            {
                "tool": tool,
                "state": state,
                "blocking_events": history_refs,
                "failure_cutoff": max(
                    (event["sequence"] for event in applicable), default=0
                ),
            }
        )
        blockers.update(
            {reference["sequence"]: reference for reference in history_refs}
        )
    row["history_associations"] = associations
    row["blocking_events"] = [blockers[sequence] for sequence in sorted(blockers)]
    # History cannot supply a current descriptor for an association excluded by policy.
    if any(association["state"] == "FAIL" for association in associations):
        row["result"], row["status"] = "FAIL", "FAIL"
    else:
        row["result"], row["status"] = "INCOMPLETE", "missing-record"


def _eligibility(events, refs, execution, claim_id, tool):
    blockers = [event for event in events if _barrier_applies(event, claim_id, tool)]
    cutoff = max((event["sequence"] for event in blockers), default=0)
    successes = [
        event
        for event in events
        if event["kind"] == "execution"
        and event["result"] == "PASS"
        and event["execution"] == execution
    ]
    _check(
        len(successes) <= 1, "duplicate execution PASS event for same physical attempt"
    )
    sequence = successes[0]["sequence"] if successes else 0
    observed = [
        event
        for event in events
        if event["kind"] == "observation"
        and event["result"] == "PASS"
        and event["execution"] == execution
        and _applicable(event, claim_id, tool)
        and event["sequence"] > sequence
    ]
    eligible = sequence > cutoff and bool(observed)
    remaining = [
        event for event in blockers if not eligible or event["sequence"] >= sequence
    ]
    return (
        eligible,
        [refs[event["sequence"] - 1] for event in blockers],
        remaining,
        observed,
    )


def _read_entry(root, records_path):
    candidate = Path(records_path)
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = Path(os.path.normpath(candidate))
    _check(candidate.is_relative_to(root), "records path outside project root")
    relative = candidate.relative_to(root).as_posix()
    if candidate.is_dir():
        _check(not candidate.is_symlink(), "records directory is symlink")
        entries = [
            parse_json(
                _regular(root, (candidate / name).relative_to(root).as_posix(), True)[
                    0
                ].read_bytes()
            )
            for name in sorted(
                entry.name
                for entry in candidate.iterdir()
                if entry.name.endswith(".json")
            )
        ]
        _check(entries, "empty records directory")
        return entries, relative
    return parse_json(_regular(root, relative, True)[0].read_bytes()), relative


def _discriminators(value):
    found = set()
    if isinstance(value, list):
        for entry in value:
            found.update(_discriminators(entry))
    elif isinstance(value, dict):
        schema = value.get("schema_version")
        if schema is not None:
            _check(
                schema in DISCRIMINATORS or schema == "fv-evidence-run/v3",
                "unknown evidence schema discriminator",
            )
            found.add(schema)
        elif "records" in value:
            found.update(_discriminators(value["records"]))
        if "bindings" in value:
            found.add("legacy")
            parser = (
                value["bindings"].get("parser_schema_version")
                if isinstance(value["bindings"], dict)
                else None
            )
            _check(
                parser != "fv-evidence-run/v4",
                "v4 record projected into legacy bindings",
            )
        if schema in DISCRIMINATORS:
            _check(
                "bindings" not in value and "records" not in value,
                "mixed v4/legacy record envelope",
            )
    return found


def detect_v4(root, records_path):
    root = fv_project.resolve_project_root(root)
    candidate = Path(records_path)
    if not candidate.is_absolute():
        candidate = root / candidate
    discovered = set()

    def pairs(entries):
        for key, value in entries:
            if key in ("schema_version", "parser_schema_version") and isinstance(
                value, str
            ):
                discovered.add(value)
        return dict(entries)

    paths = sorted(candidate.glob("*.json")) if candidate.is_dir() else [candidate]
    values = []
    for entry in paths:
        try:
            data = entry.read_bytes()
        except FileNotFoundError:
            if entry.is_relative_to(root) and entry.relative_to(
                root
            ).as_posix().startswith(BASE + "/"):
                return True
            raise
        try:
            values.append(json.loads(data, object_pairs_hook=pairs))
        except (json.JSONDecodeError, UnicodeError) as error:
            if re.search(
                rb'"(?:schema_version|parser_schema_version)"\s*:\s*"fv-(?:evidence|execution|claim|observation)[^"]*(?:/v4|current/v1|batch/v1|result/v1)',
                data,
            ):
                raise V4Error("malformed v4 evidence JSON") from error
            raise
    found = _discriminators(values)
    v4 = (found | discovered) & set(DISCRIMINATORS)
    _check(
        not v4 or not (found - set(DISCRIMINATORS)),
        "mixed v4 and legacy evidence schemas",
    )
    if v4:
        _read_entry(root, records_path)
    return bool(v4)


def _load_run(reader, records_path):
    value, relative = _read_entry(reader.root, records_path)
    if isinstance(value, list):
        _check(
            value
            and all(
                isinstance(entry, dict)
                and entry.get("schema_version") == "fv-evidence-run/v4"
                for entry in value
            ),
            "v4 array contains mixed or unknown records",
        )
        for entry in value:
            validate(
                {"run_id": "uuid", "claim_id": "id"},
                {"run_id": entry.get("run_id"), "claim_id": entry.get("claim_id")},
            )
        _check(
            len({entry["run_id"] for entry in value}) == 1
            and len({entry["claim_id"] for entry in value}) == len(value),
            "ambiguous v4 claim array",
        )
        run_id = value[0]["run_id"]
        run_relative = f"{BASE}/runs/{run_id}/run.json"
        run = parse_json(reader.read(run_relative))
    else:
        _check(
            isinstance(value, dict) and value.get("schema_version") in DISCRIMINATORS,
            "expected exact v4 current/run/claim schema",
        )
        shape = DISCRIMINATORS[value["schema_version"]]
        if shape == "ClaimRecord":
            validate(
                {"run_id": "uuid", "claim_id": "id"},
                {"run_id": value.get("run_id"), "claim_id": value.get("claim_id")},
            )
        else:
            validate(shape, value)
        if shape == "CurrentPointer":
            run = reader.json_ref(value["run"], "RunManifest")
            _check(run["run_id"] == value["run_id"], "current pointer run ID mismatch")
            run_relative = value["run"]["path"]
        elif shape == "RunResult":
            _check(
                value["run"] is not None,
                "run result lacks immutable collection reference",
            )
            run = reader.json_ref(value["run"], "RunManifest")
            _check(
                value["manifest"] == run,
                "run result inline manifest differs from bytes",
            )
            run_relative = value["run"]["path"]
        elif shape == "ClaimRecord":
            run_relative = f"{BASE}/runs/{value['run_id']}/run.json"
            run = parse_json(reader.read(run_relative))
        else:
            run = value
            run_relative = relative
    validate("RunManifest", run)
    _check(
        run_relative == f"{BASE}/runs/{run['run_id']}/run.json",
        "run manifest immutable owner path mismatch",
    )
    if isinstance(value, list):
        supplied = {entry["claim_id"]: entry for entry in value}
    elif value.get("schema_version") == "fv-evidence-run/v4":
        supplied = {value["claim_id"]: value}
    else:
        supplied = {}
    for entry in run["claims"]:
        if entry["claim_id"] in supplied:
            _check(
                parse_json(reader.ref(entry["record"]))
                == supplied.pop(entry["claim_id"]),
                "supplied claim differs from immutable run reference",
            )
    _check(not supplied, "supplied claim absent from full run")
    return run


def _now():
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _stop_group(process):
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.05)
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def _recheck(reader, policy, request, original_response, mandatory, baseline):
    # This disposable protocol call creates no execution, claim or history evidence.
    run_id = str(uuid.uuid4())
    request_id = str(uuid.uuid4())
    runs = reader.root / BASE / "runs"
    _check(
        runs.is_dir() and not runs.is_symlink(), "unsafe verification request parent"
    )
    owned = runs / run_id
    owned.mkdir(mode=0o700)
    owned_identity = owned.lstat()
    directory = owned / "observations" / request["claim_id"] / request_id
    try:
        directory.mkdir(parents=True, mode=0o700)
        temporary_request = {**request, "request_id": request_id, "created_at": _now()}
        data = C(temporary_request)
        request_path = directory / "request.json"
        response_path = directory / "response.json"
        with request_path.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        environment = {
            name: os.environ[name]
            for name in policy["environment"]["inherit"]
            if name in os.environ
        }
        environment.update(policy["environment"]["set"])
        check = policy["claim_checker"]
        cwd = reader.root if check["cwd"] == "." else reader.root / check["cwd"]
        _check(cwd.is_dir() and not cwd.is_symlink(), "checker cwd is unsafe")
        before = _current_inputs(Reader(reader.root), policy, mandatory)
        _check(before == baseline, "source drift before portable observation recheck")
        process = subprocess.Popen(
            [
                *check["command"],
                "--request",
                str(request_path),
                "--response",
                str(response_path),
            ],
            cwd=cwd,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        try:
            stdout, stderr = process.communicate(timeout=check["timeout_seconds"])
        except subprocess.TimeoutExpired as error:
            _stop_group(process)
            process.communicate()
            raise V4Error("portable observation checker timed out") from error
        finally:
            _stop_group(process)
        _check(process.returncode == 0, "portable observation checker transport failed")
        stdout.decode("utf-8", errors="strict")
        stderr.decode("utf-8", errors="strict")
        response_relative = response_path.relative_to(reader.root).as_posix()
        response_target, _ = _regular(reader.root, response_relative, True)
        request_target, _ = _regular(
            reader.root, request_path.relative_to(reader.root).as_posix(), True
        )
        _check(
            request_target.read_bytes() == data,
            "portable checker replaced request bytes",
        )
        response = parse_json(response_target.read_bytes())
        _response(temporary_request, H(data), response)
        _check(
            _current_inputs(Reader(reader.root), policy, mandatory) == baseline,
            "source drift during portable observation recheck",
        )
        _check(
            {entry.name for entry in directory.iterdir()}
            <= {"request.json", "response.json"},
            "unexpected disposable checker response files",
        )
        for slot, original in zip(
            response["slots"], original_response["slots"], strict=True
        ):
            if slot["result"] == "PASS":
                _check(
                    slot["observations"] == original["observations"],
                    "portable observation summary differs from retained contract assessment",
                )
        return response
    finally:
        # The exclusive UUID directory is the only path owned by this checker.
        remaining = owned.lstat()
        _check(
            stat.S_ISDIR(remaining.st_mode)
            and (remaining.st_dev, remaining.st_ino)
            == (owned_identity.st_dev, owned_identity.st_ino),
            "owned verification directory replaced; cleanup refused",
        )
        shutil.rmtree(owned)


def _physical_expansion(policy):
    result = []
    for recipe in policy["recipes"]:
        if recipe["determinism"]["mode"] == "fixed":
            result.append((recipe["recipe_id"], None))
        else:
            for record in policy["records"]:
                for slot in record["executions"]:
                    if slot["recipe_id"] == recipe["recipe_id"]:
                        result.append(
                            (
                                recipe["recipe_id"],
                                {
                                    "claim_id": record["claim_id"],
                                    "slot_id": slot["slot_id"],
                                },
                            )
                        )
    return result


def _report(root, records_path, recompute):
    return {
        "gate": "semantic-evidence",
        "schema_version": "fv-evidence-run/v4",
        "records": str(records_path),
        "repo_root": str(root),
        "expected_snapshot": None,
        "intent_path": None,
        "binding": "recomputed" if recompute else "not-recomputed",
        "validation": "portable-checker",
        "history_binding": "retained-store-completeness-assumed",
        "dependency_expansion": {},
        "required_claims": [],
        "obligation_kinds": {},
        "required_evidence": {},
        "dependencies": {},
        "per_claim": [],
        "failed": [],
        "incomplete": [],
        "errors": [],
        "verdict": "ERROR",
        "trust_assumptions": None,
        "counts": {
            "logical_associations": None,
            "unique_physical_executions": None,
            "actual_dispatches": None,
            "cache_hits": None,
            "missing_associations": 0,
            "failed_associations": 0,
            "error_associations": 0,
            "cancelled_associations": 0,
        },
    }


def assess_v4(
    root,
    records_path,
    manifest_path=None,
    require=None,
    *,
    recompute=True,
    recheck_observations=True,
):
    report = _report(root, records_path, recompute)
    try:
        _check(
            type(recompute) is bool and type(recheck_observations) is bool,
            "assessment mode flags must be boolean",
        )
        reader = Reader(root)
        report["repo_root"] = str(reader.root)
        run = _load_run(reader, records_path)
        (
            policy,
            common,
            mandatory,
            recipes,
            records,
            members,
            declarations,
            kinds,
            evidence,
            dependencies,
        ) = _policy(reader, run["policy_path"], manifest_path)
        report["common"] = common
        report["captured_source_snapshot"] = (run["source_before"] or {}).get(
            "source_snapshot"
        )
        report["intent_path"] = common["intent_path"]
        report["coverage_only"] = not (recompute and recheck_observations)
        report["freshness"] = "recomputed" if recompute else "not-recomputed"
        report["reusable"] = False
        report["observations_rechecked"] = False
        report["observation_recheck_count"] = 0
        report["trust_assumptions"] = policy["trust_assumptions"]
        report["provenance"] = {
            "source": "endpoint-recomputation-under-no-concurrent-mutation"
            if recompute
            else "not-recomputed",
            "build_products": "upstream-build-system-integrity-assumed; no-fresh-compilation-claim",
            "system_packages": "producer-os-vendor-package-integrity-assumed",
            "history": "trusted-supplied-store-completeness-and-nondeletion-assumed",
            "observations": "independent-recheck-required"
            if recompute and recheck_observations
            else "retained-receipts-only",
        }
        selected = None
        if require is not None:
            selected = (
                [entry.strip() for entry in require.split(",") if entry.strip()]
                if isinstance(require, str)
                else list(require)
            )
            _check(
                selected
                and len(set(selected)) == len(selected)
                and set(selected) <= set(kinds),
                "invalid required canonical claim selection",
            )
        required = set(common["required_targets"] if selected is None else selected) | {
            identifier for identifier, record in records.items() if record["required"]
        }
        for identifier in list(required):
            added = [
                dep for dep in dependencies.get(identifier, []) if dep not in required
            ]
            if added:
                report["dependency_expansion"][identifier] = added
                required.update(added)
        report["required_claims"] = sorted(
            required, key=lambda identifier: identifier.encode("utf-8")
        )
        report["obligation_kinds"] = {
            identifier: kinds[identifier] for identifier in report["required_claims"]
        }
        report["required_evidence"] = evidence
        report["dependencies"] = dependencies
        report["assessment_scope"] = (
            "canonical-full"
            if selected is None
            else "full-policy-plus-explicit-canonical-selection"
        )
        for identifier in [
            *records,
            *(name for name in report["required_claims"] if name not in records),
        ]:
            policy_record = records.get(identifier)
            row = {
                "claim_id": identifier,
                "status": "missing-record",
                "result": "INCOMPLETE",
                "evidence_class": policy_record["evidence_class"]
                if policy_record
                else None,
                "scope": policy_record["scope"] if policy_record else None,
                "defects": [],
                "executions": [],
                "depends_on": dependencies.get(identifier, []),
            }
            if policy_record is not None:
                for slot in policy_record["executions"]:
                    row["executions"].append(
                        {
                            **slot,
                            "evidence_class": recipes[slot["recipe_id"]][
                                "evidence_class"
                            ],
                            "expected_class": recipes[slot["recipe_id"]][
                                "evidence_class"
                            ],
                            "state": "MISSING",
                            "execution": None,
                            "cache": "not-checked",
                            "observation": None,
                            "observations": None,
                            "blocking_events": [],
                            "defects": [],
                        }
                    )
            report["per_claim"].append(row)
        report["counts"]["logical_associations"] = sum(
            len(row["executions"]) for row in report["per_claim"]
        )
        _check(
            run["common"] == common
            and run["policy_hash"] == common["policy_hash"]
            and run["trust_assumptions"] == policy["trust_assumptions"],
            "run common/policy/trust binding mismatch",
        )
        _check(
            run["started_at"] <= run["finished_at"]
            and run["jobs"] <= policy["jobs"]["max"],
            "invalid run interval or scheduling bound",
        )
        sorted_unique(run["selected_records"])
        sorted_unique(run["required_records"])
        _check(
            set(run["selected_records"]) <= set(records)
            and run["required_records"]
            == sorted(
                [
                    identifier
                    for identifier, record in records.items()
                    if record["required"]
                ],
                key=lambda identifier: identifier.encode("utf-8"),
            ),
            "run selection/required records differs from policy",
        )
        _check(
            [entry["claim_id"] for entry in run["claims"]] == list(records),
            "run claim references omit/add/reorder policy records",
        )
        expansion = _physical_expansion(policy)
        _check(
            [(entry["recipe_id"], entry["distinct_slot"]) for entry in run["work"]]
            == expansion,
            "run physical work expansion differs from policy",
        )
        for entry in run["work"]:
            try:
                if entry["execution"] is not None:
                    _check(
                        entry["execution_key"] == entry["execution"]["execution_key"],
                        "work execution key/ref mismatch",
                    )
                    artifact = _execution(reader, entry["execution"])
                    _check(
                        artifact["descriptor"]["recipe"]["recipe_id"]
                        == entry["recipe_id"]
                        and artifact["descriptor"]["distinct_slot"]
                        == entry["distinct_slot"],
                        "work references foreign physical slot",
                    )
                    _check(
                        entry["state"] == artifact["result"],
                        "work state differs from physical result",
                    )
                else:
                    _check(
                        entry["state"] not in ("PASS", "FAIL"),
                        "work PASS/FAIL has no actual execution",
                    )
                _check(
                    entry["cache"] != "hit" or entry["execution"] is not None,
                    "cache hit has no physical receipt",
                )
            except (V4Error, OSError, UnicodeError, KeyError, TypeError) as error:
                report["errors"].append(entry["recipe_id"] + ": " + str(error))

        report["counts"]["actual_dispatches"] = sum(
            entry["cache"] == "miss" and entry["execution"] is not None
            for entry in run["work"]
        )
        report["counts"]["cache_hits"] = sum(
            entry["cache"] == "hit" for entry in run["work"]
        )
        for state_field in ("source_before", "source_after"):
            if run[state_field] is not None:
                _input_state(run[state_field])
        if run["result"] == "PASS":
            _check(
                run["source_before"] is not None
                and run["source_before"]["clean"]
                and run["source_after"] == run["source_before"]
                and run["preflight"]["result"] == "PASS",
                "PASS run lacks stable clean final scans/preflight",
            )
        _check(
            [entry["id"] for entry in run["preflight"]["checks"]]
            == [entry["id"] for entry in policy["preflight"]],
            "preflight check expansion differs from policy",
        )
        for check in run["preflight"]["checks"]:
            for stream in ("stdout", "stderr"):
                if check[stream] is not None:
                    reader.ref(check[stream])
            if check["result"] == "PASS":
                _check(
                    check["termination"]
                    == {
                        "exit_code": 0,
                        "signal": None,
                        "timed_out": False,
                        "cancelled": False,
                    }
                    and check["stdout"] is not None
                    and check["stderr"] is not None,
                    "preflight PASS without actual successful streams/termination",
                )
            if check["result"] == "MISSING":
                _check(
                    check["stdout"] is None
                    and check["stderr"] is None
                    and check["termination"]
                    == {
                        "exit_code": None,
                        "signal": None,
                        "timed_out": False,
                        "cancelled": False,
                    },
                    "unrun preflight has fabricated outputs/termination",
                )
        if run["preflight"]["result"] == "PASS":
            _check(
                all(check["result"] == "PASS" for check in run["preflight"]["checks"]),
                "preflight aggregate contradicts missing/failed checks",
            )
        history, events, history_errors = _history(reader, run["history"])
        report["errors"].extend(history_errors)
        report["history"] = history
        for row in report["per_claim"]:
            if row["claim_id"] not in records:
                _outside_policy_history(
                    row, events, history["events"], evidence.get(row["claim_id"], ())
                )
        current = None
        if recompute:
            try:
                current = _current_inputs(reader, policy, mandatory)
                report["expected_snapshot"] = current["source_snapshot"]
                if not current["clean"]:
                    report["errors"].append("current selected input set is dirty")
            except (V4Error, OSError, UnicodeError, ValueError) as error:
                report["errors"].append(
                    "current source scan unavailable: " + str(error)
                )

        claim_refs = {entry["claim_id"]: entry["record"] for entry in run["claims"]}
        work_by_slot = {
            (entry["recipe_id"], C(entry["distinct_slot"])): entry
            for entry in run["work"]
        }
        replayed = {}
        unique = {
            entry["execution"]["path"]
            for entry in run["work"]
            if entry["execution"] is not None
            and entry["execution"]["path"] in reader.artifacts
        }
        for row in report["per_claim"]:
            identifier = row["claim_id"]
            if identifier not in records:
                continue
            record = None
            try:
                ref = claim_refs[identifier]
                _check(
                    ref["path"]
                    == f"{BASE}/runs/{run['run_id']}/claims/{identifier}.json",
                    "claim record immutable owner path mismatch",
                )
                record = parse_json(reader.ref(ref))
                if isinstance(record, dict):
                    row["declared_class"] = record.get("evidence_class")
                    raw_slots = record.get("executions")
                    if isinstance(raw_slots, list):
                        for slot_row in row["executions"]:
                            declared = next(
                                (
                                    slot
                                    for slot in raw_slots
                                    if isinstance(slot, dict)
                                    and slot.get("slot_id") == slot_row["slot_id"]
                                ),
                                None,
                            )
                            if declared is not None:
                                slot_row["declared_class"] = declared.get(
                                    "evidence_class"
                                )
                validate("ClaimRecord", record)
                _identity(record, "record_id", "claim-record")
                expected = records[identifier]
                _check(
                    record["run_id"] == run["run_id"]
                    and all(
                        record[key] == expected[key]
                        for key in ("claim_id", "required", "evidence_class", "scope")
                    )
                    and record["common"] == common,
                    "claim identity/class/scope/common differs from policy",
                )
                _check(
                    [slot["slot_id"] for slot in record["executions"]]
                    == [slot["slot_id"] for slot in expected["executions"]],
                    "claim slots missing/extra/reordered",
                )
                row["evidence_class"] = record["evidence_class"]
            except (V4Error, OSError, UnicodeError, KeyError, TypeError) as error:
                row["defects"].append(str(error))
                report["errors"].append(f"{identifier}: {error}")
                record = None
            for slot_row in row["executions"]:
                tool = slot_row["tool"]
                saved = (
                    next(
                        (
                            slot
                            for slot in record["executions"]
                            if slot["slot_id"] == slot_row["slot_id"]
                        ),
                        None,
                    )
                    if record is not None
                    else None
                )
                execution = saved["execution"] if saved is not None else None
                eligible, blocking, barriers, observed = _eligibility(
                    events, history["events"], execution, identifier, tool
                )
                slot_row["blocking_events"] = blocking
                physical_failure = any(event["result"] == "FAIL" for event in barriers)
                if saved is not None:
                    slot_row.update(
                        {
                            key: saved[key]
                            for key in (
                                "state",
                                "execution",
                                "observation",
                                "evidence_class",
                            )
                        }
                    )
                if physical_failure:
                    slot_row["state"] = "FAIL"
                elif barriers:
                    slot_row["state"] = (
                        "CANCELLED"
                        if barriers[-1]["result"] == "CANCELLED"
                        else "ERROR"
                    )
                try:
                    if saved is None:
                        raise V4Error("missing or malformed canonical slot")
                    _check(
                        all(
                            saved[key] == slot_row[key]
                            for key in (
                                "slot_id",
                                "tool",
                                "recipe_id",
                                "observation_binding",
                            )
                        )
                        and saved["evidence_class"] == slot_row["expected_class"],
                        "claim slot tool/recipe/observation/class differs from policy",
                    )
                    captured_blockers = [
                        history["events"][event["sequence"] - 1]
                        for event in events
                        if event["sequence"] <= len(run["history"]["events"])
                        and _barrier_applies(event, identifier, tool)
                    ]
                    _check(
                        saved["blocking_events"] == captured_blockers,
                        "claim captured historical barrier references are incomplete or foreign",
                    )
                    distinct = (
                        None
                        if recipes[saved["recipe_id"]]["determinism"]["mode"] == "fixed"
                        else {"claim_id": identifier, "slot_id": saved["slot_id"]}
                    )
                    work = work_by_slot[(saved["recipe_id"], C(distinct))]
                    slot_row["cache"] = work["cache"]
                    if execution is None:
                        _check(
                            saved["state"] not in ("PASS", "FAIL") or physical_failure,
                            "slot PASS/FAIL has no actual receipt/barrier",
                        )
                        continue
                    artifact = _execution(reader, execution)
                    unique.add(execution["path"])
                    _current_descriptor(
                        reader,
                        artifact,
                        common,
                        policy,
                        recipes,
                        members,
                        declarations,
                        current,
                    )
                    _check(
                        {
                            "claim_id": identifier,
                            "slot_id": saved["slot_id"],
                            "tool": tool,
                        }
                        in artifact["descriptor"]["members"],
                        "claim cites another execution member",
                    )
                    if artifact["result"] != "PASS":
                        _check(
                            saved["state"] == artifact["result"] or physical_failure,
                            "slot result contradicts physical attempt",
                        )
                        continue
                    observation = saved["observation"]
                    _check(
                        observation is not None,
                        "physical PASS lacks own member observation",
                    )
                    check, request, response, usable = _observation(
                        reader, observation["check"]
                    )
                    _check(
                        observation["response"] == check["response"],
                        "claim response reference differs from checker receipt",
                    )
                    requested = next(
                        (
                            slot
                            for slot in request["slots"]
                            if slot["slot_id"] == saved["slot_id"]
                        ),
                        None,
                    )
                    _check(
                        request["claim_id"] == identifier
                        and requested is not None
                        and requested["execution"] == execution
                        and requested["observation_binding"]
                        == saved["observation_binding"],
                        "claim member observation request mismatch",
                    )
                    _tools(
                        check["toolchain"],
                        declarations,
                        policy["claim_checker"]["toolchain"],
                        artifact["descriptor"]["environment"],
                    )
                    outcome, response_slot = _observation_outcome(
                        check, response, saved["slot_id"], usable, artifact
                    )
                    _check(
                        outcome == observation["result"],
                        "claim observation result mismatch",
                    )
                    slot_row["observations"] = (
                        response_slot["observations"]
                        if response_slot is not None
                        else None
                    )
                    if outcome in ("ERROR", "CANCELLED"):
                        _check(
                            saved["state"] == outcome or physical_failure,
                            "claim hides operational observation outcome",
                        )
                        if not physical_failure:
                            slot_row["state"] = outcome
                        continue

                    if not eligible:
                        if not physical_failure:
                            slot_row["state"] = (
                                (
                                    "CANCELLED"
                                    if barriers[-1]["result"] == "CANCELLED"
                                    else "ERROR"
                                )
                                if barriers
                                else "MISSING"
                            )
                        continue
                    _check(
                        any(
                            event["observation"] == observation["check"]
                            for event in observed
                        ),
                        "claim observation lacks subsequent matching PASS history",
                    )
                    _check(
                        response_slot["result"] == "PASS",
                        "eligible slot retains nonpassing observation",
                    )
                    _check(
                        not recompute or current is not None,
                        "current source scan unavailable for coverage",
                    )
                    if recompute and recheck_observations:
                        cache_key = observation["check"]["path"]
                        if cache_key not in replayed:
                            replayed[cache_key] = _recheck(
                                reader, policy, request, response, mandatory, current
                            )
                            report["observations_rechecked"] = True
                            report["observation_recheck_count"] = len(replayed)
                            report["provenance"]["observations"] = (
                                "independently-rechecked-pass-candidates"
                            )
                        checked = next(
                            slot
                            for slot in replayed[cache_key]["slots"]
                            if slot["slot_id"] == saved["slot_id"]
                        )
                        slot_row["observations"] = checked["observations"]
                        if checked["result"] != "PASS":
                            slot_row["state"] = (
                                "FAIL" if checked["result"] == "FAIL" else "ERROR"
                            )
                            slot_row["defects"].append(
                                checked["reason"]
                                or "independent member observation did not pass"
                            )
                            continue
                    slot_row["state"] = "PASS"
                except (
                    V4Error,
                    OSError,
                    UnicodeError,
                    KeyError,
                    TypeError,
                    ValueError,
                ) as error:
                    slot_row["defects"].append(str(error))
                    if not physical_failure:
                        slot_row["state"] = "ERROR"
                    report["errors"].append(f"{identifier}/{tool}: {error}")
            states = [slot["state"] for slot in row["executions"]]
            row["result"] = (
                "FAIL"
                if "FAIL" in states
                else "PASS"
                if states
                and all(state == "PASS" for state in states)
                and not row["defects"]
                else "INCOMPLETE"
            )
            row["status"] = row["result"]
            if record is not None:
                # Later retained history may change a captured aggregate, never its bytes.
                captured_result = (
                    "FAIL"
                    if any(slot["state"] == "FAIL" for slot in record["executions"])
                    else "PASS"
                    if all(slot["state"] == "PASS" for slot in record["executions"])
                    else "INCOMPLETE"
                )
                if record["result"] not in (captured_result, "INCOMPLETE"):
                    row["defects"].append(
                        "stored claim aggregate contradicts slot states"
                    )
                    report["errors"].append(
                        identifier + ": stored claim aggregate contradicts slot states"
                    )
        latest_history, latest_events, latest_errors = _history(reader, run["history"])
        report["errors"].extend(latest_errors)
        if latest_history != history:
            report["history"] = latest_history
            for row in report["per_claim"]:
                if row["claim_id"] not in records:
                    _outside_policy_history(
                        row,
                        latest_events,
                        latest_history["events"],
                        evidence.get(row["claim_id"], ()),
                    )
                    continue
                for slot in row["executions"]:
                    eligible, blocking, barriers, observed = _eligibility(
                        latest_events,
                        latest_history["events"],
                        slot["execution"],
                        row["claim_id"],
                        slot["tool"],
                    )
                    slot["blocking_events"] = blocking
                    if any(event["result"] == "FAIL" for event in barriers):
                        slot["state"] = "FAIL"
                    elif barriers:
                        slot["state"] = (
                            "CANCELLED"
                            if barriers[-1]["result"] == "CANCELLED"
                            else "ERROR"
                        )
                    elif not eligible and slot["state"] == "PASS":
                        slot["state"] = "MISSING"
                states = [slot["state"] for slot in row["executions"]]
                if "FAIL" in states:
                    row["result"], row["status"] = "FAIL", "FAIL"
                elif (
                    any(state != "PASS" for state in states) and row["result"] == "PASS"
                ):
                    row["result"], row["status"] = "INCOMPLETE", "INCOMPLETE"

        report["counts"]["unique_physical_executions"] = len(unique)
        by_claim = {row["claim_id"]: row for row in report["per_claim"]}
        for row in report["per_claim"]:
            if row["result"] == "PASS":
                gaps = [
                    dep
                    for dep in dependencies.get(row["claim_id"], [])
                    if dep not in by_claim or by_claim[dep]["result"] != "PASS"
                ]
                if gaps:
                    row["status"] = "dependency-gap"
                    row["result"] = "INCOMPLETE"
                    row["dependency_gaps"] = gaps
                    row["defects"].append(
                        "canonical dependencies not covered: " + ",".join(gaps)
                    )
        for row in report["per_claim"]:
            if row["claim_id"] in required:
                if row["result"] == "FAIL":
                    report["failed"].append(
                        row["claim_id"] + ": recorded or independently observed FAIL"
                    )
                elif row["result"] != "PASS":
                    report["incomplete"].append(row["claim_id"] + ": " + row["status"])
        if not required:
            report["incomplete"].append("required claim set is empty")
        if recompute and current is not None:
            _check(
                _current_inputs(Reader(reader.root), policy, mandatory) == current,
                "source drift during portable assessment",
            )
        if report["failed"]:
            report["verdict"] = "FAILED"
            return report, 1
        if (
            report["errors"]
            or run["result"] == "ERROR"
            or run["preflight"]["result"] == "ERROR"
        ):
            report["verdict"] = "ERROR"
            return report, 2
        if report["incomplete"] or run["result"] == "CANCELLED":
            report["verdict"] = "INCOMPLETE"
            return report, 3
        qualification = (
            ""
            if recompute and recheck_observations
            else "; binding="
            + ("not-recomputed" if not recompute else "observations-not-rechecked")
        )
        if selected is not None:
            qualification += "; scope=full-policy-selection"
        report["verdict"] = (
            ("VERIFIED" if recompute and recheck_observations else "COVERED")
            + "[profile=producer-trusted-execution-v4"
            + qualification
            + "]"
        )
        return report, 0
    except (V4Error, OSError, UnicodeError, ValueError, KeyError, TypeError) as error:
        report["errors"].append(str(error))
        # Retain independently validated failures even when another member is corrupt.
        for row in report["per_claim"]:
            if row["claim_id"] in report["required_claims"] and (
                row["result"] == "FAIL"
                or any(slot["state"] == "FAIL" for slot in row["executions"])
            ):
                row["result"] = "FAIL"
                row["status"] = "FAIL"
                message = row["claim_id"] + ": recorded FAIL"
                if message not in report["failed"]:
                    report["failed"].append(message)
        report["verdict"] = "FAILED" if report["failed"] else "ERROR"
        return report, 1 if report["failed"] else 2
    finally:
        association_counts = {
            "MISSING": "missing_associations",
            "FAIL": "failed_associations",
            "ERROR": "error_associations",
            "CANCELLED": "cancelled_associations",
        }
        for count in association_counts.values():
            report["counts"][count] = 0
        for row in report["per_claim"]:
            for slot in row["executions"]:
                count = association_counts.get(slot["state"])
                if count:
                    report["counts"][count] += 1
