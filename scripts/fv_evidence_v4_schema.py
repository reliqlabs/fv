"""Strict wire grammar and canonical identities for execution evidence v4."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime

MAX_INTEGER = 9007199254740991
CLASSES = (
    "code-enforced",
    "proof-discharged",
    "bounded-checked",
    "test-witnessed",
    "conformance-tested",
)
ADAPTERS = (
    "python-runtime",
    "quint-backends",
    "cargo-toolchain",
    "kani-toolchain",
    "lean-toolchain",
    "darwin-native",
    "node-toolchain",
)


class V4Error(ValueError):
    pass


def scalar(value):
    if not isinstance(value, str) or any(0xD800 <= ord(c) <= 0xDFFF for c in value):
        raise V4Error("string contains a non-scalar value")
    return value


def _grammar(value, field=None):
    if value is None or type(value) is bool:
        return
    if type(value) is int:
        if abs(value) > MAX_INTEGER or (value < 0 and field != "exit_code"):
            raise V4Error("integer out of range or negative outside exit_code")
    elif isinstance(value, str):
        scalar(value)
    elif isinstance(value, list):
        for entry in value:
            _grammar(entry)
    elif isinstance(value, dict):
        for key, entry in value.items():
            scalar(key)
            _grammar(entry, key)
    else:
        raise V4Error("unsupported JSON value")


def parse_json(data: bytes):
    def integer(token):
        if token == "-0" or not re.fullmatch(r"-?(?:0|[1-9][0-9]*)", token):
            raise V4Error("noncanonical integer token")
        if len(token.lstrip("-")) > 16:
            raise V4Error("integer exceeds safe range")
        value = int(token)
        if abs(value) > MAX_INTEGER:
            raise V4Error("integer exceeds safe range")
        return value

    def reject(token):
        raise V4Error(f"noninteger JSON token: {token}")

    def pairs(entries):
        result = {}
        for key, value in entries:
            if key in result:
                raise V4Error(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(
            data.decode("utf-8", errors="strict"),
            parse_int=integer,
            parse_float=reject,
            parse_constant=reject,
            object_pairs_hook=pairs,
        )
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise V4Error(f"invalid v4 JSON: {error}") from error
    try:
        _grammar(value)
    except RecursionError as error:
        raise V4Error("JSON nesting exceeds parser capacity") from error
    return value


def C(value) -> bytes:
    _grammar(value)

    def encode(entry):
        if entry is None:
            return "null"
        if type(entry) is bool:
            return "true" if entry else "false"
        if type(entry) is int:
            if abs(entry) > MAX_INTEGER:
                raise V4Error("canonical integer exceeds safe range")
            return str(entry)
        if isinstance(entry, str):
            scalar(entry)
            return (
                '"'
                + "".join(
                    '\\"'
                    if c == '"'
                    else "\\\\"
                    if c == "\\"
                    else f"\\u{ord(c):04x}"
                    if ord(c) < 32
                    else c
                    for c in entry
                )
                + '"'
            )
        if isinstance(entry, list):
            return "[" + ",".join(encode(item) for item in entry) + "]"
        if isinstance(entry, dict):
            for key in entry:
                scalar(key)
            return (
                "{"
                + ",".join(
                    encode(key) + ":" + encode(entry[key])
                    for key in sorted(entry, key=lambda key: key.encode("utf-8"))
                )
                + "}"
            )
        raise V4Error("unsupported canonical JSON value")

    return encode(value).encode("utf-8")


def H(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def D(label: str, value) -> str:
    return H(("fv-evidence-v4/" + label).encode("utf-8") + b"\0" + C(value))


def path(value, cwd=False, prefix=False):
    scalar(value)
    if cwd and value == ".":
        return value
    name = value[:-1] if prefix and value.endswith("/") else value
    if (
        not name
        or name.startswith(("/", "~"))
        or "\\" in name
        or any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in name)
        or any(part in ("", ".", "..") for part in name.split("/"))
    ):
        raise V4Error(f"unsafe path: {value!r}")
    return value


def sorted_unique(values, key=lambda value: value):
    keys = [key(value) for value in values]
    encoded = [
        tuple(part.encode("utf-8") for part in item)
        if isinstance(item, tuple)
        else item.encode("utf-8")
        for item in keys
    ]
    if encoded != sorted(encoded) or len(set(keys)) != len(keys):
        raise V4Error("set array is not unique UTF-8 sorted")


def utc(value):
    if not isinstance(value, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", value
    ):
        raise V4Error("invalid UTC timestamp")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError as error:
        raise V4Error("invalid UTC timestamp") from error


def enum(*values):
    return ("enum", values)


def array(shape, minimum=0):
    return ("array", shape, minimum)


def nullable(shape):
    return ("nullable", shape)


def union(*shapes):
    return ("union", shapes)


S = {}
ID = "id"
HASH = "hash"
PATH = "path"
CWD = "cwd"
CMD = "command"
UINT = "uint"
POS = "positive"
TEXT = "text"
NONEMPTY = "nonempty"
STR = "string"
BOOL = "boolean"
REF = "FileRef"
MEMBER = {"claim_id": ID, "slot_id": ID, "tool": "tool"}
SLOT = {"claim_id": ID, "slot_id": ID}
BINDING = {"path": PATH, "pointer": "pointer"}
STATE = enum("PASS", "FAIL", "ERROR", "CANCELLED", "MISSING")
RESULT = enum("PASS", "FAIL", "ERROR", "CANCELLED")
TERMINATION = {
    "exit_code": nullable("exit"),
    "signal": nullable(TEXT),
    "timed_out": BOOL,
    "cancelled": BOOL,
}
S["Locator"] = union(
    {"mode": enum("command", "path"), "value": TEXT},
    {
        "mode": enum("command-relative"),
        "value": TEXT,
        "parent_levels": UINT,
        "subpath": CWD,
    },
    {"mode": enum("adapter"), "value": enum(*ADAPTERS), "cwd": CWD, "subject": CMD},
)
S["ProducerLocator"] = {
    "mode": enum("adapter"),
    "value": enum("producer-runtime"),
    "cwd": enum("."),
    "subject": enum(["fv_evidence_run"]),
}
S["TrustAssumptions"] = {
    "no_concurrent_mutation": enum(True),
    "build_cache_integrity": enum("upstream-build-system"),
    "retained_history_integrity": enum("trusted-producer-store"),
}
S["Check"] = {
    "id": ID,
    "command": CMD,
    "cwd": CWD,
    "resources": array("resource"),
    "toolchain": array(ID),
    "timeout_seconds": nullable(POS),
}
S["ToolDeclaration"] = {
    "id": ID,
    "kind": enum("executable", "file", "tree"),
    "locator": "Locator",
    "version_command": nullable(CMD),
    "version_cwd": nullable(CWD),
    "requires": array(ID),
    "accept": {"sha256": array(HASH), "version_contains": array(NONEMPTY)},
}
S["Recipe"] = {
    "recipe_id": ID,
    "command": CMD,
    "cwd": CWD,
    "evidence_class": enum(*CLASSES),
    "pass_marker": nullable(NONEMPTY),
    "timeout_seconds": nullable(POS),
    "determinism": {"mode": enum("fixed", "distinct"), "rationale": NONEMPTY},
    "source_closure": {
        "mode": enum("prefixes", "verified-inputs"),
        "prefixes": array("prefix"),
        "basis": array(PATH),
    },
    "toolchain": array(ID),
    "resources": array("resource"),
    "exclusive": BOOL,
    "bounds": {
        "samples": nullable(POS),
        "max_steps": nullable(POS),
        "seed": nullable(STR),
    },
    "attestation": nullable(
        {"path": PATH, "pointer": "pointer", "validation": enum("collector-transitive")}
    ),
    "build_cache": nullable(
        {
            "mode": enum("upstream-integrity"),
            "system": enum("cargo", "lake", "node", "replay"),
            "configuration": array(PATH),
            "resources": array("resource"),
        }
    ),
    "ownership_protocol": nullable(enum("dossier-quint-private-pipes/v1")),
    "retained_environment": array("envname"),
}
S["PolicyRecord"] = {
    "claim_id": ID,
    "required": BOOL,
    "evidence_class": enum(*CLASSES),
    "scope": NONEMPTY,
    "executions": array(
        {
            "slot_id": ID,
            "recipe_id": ID,
            "tool": "tool",
            "observation_binding": BINDING,
        },
        1,
    ),
}
S["Policy"] = {
    "schema_version": enum("fv-execution-policy/v1"),
    "policy_id": ID,
    "verified_inputs": enum(".fv/verified-inputs.txt"),
    "intent_path": PATH,
    "manifest_path": enum(".fv/obligations.json"),
    "definition_files": array(PATH),
    "environment": {
        "mode": enum("sanitized"),
        "platforms": array({"os": TEXT, "arch": TEXT}, 1),
        "inherit": array("envname"),
        "set": "envmap",
        "identity": array("envname"),
    },
    "toolchains": array("ToolDeclaration"),
    "preflight": array("Check"),
    "claim_checker": "Check",
    "recipes": array("Recipe", 1),
    "records": array("PolicyRecord", 1),
    "jobs": {"default": enum(2), "max": POS},
    "trust_assumptions": "TrustAssumptions",
}
S["SourceFile"] = {"path": PATH, "hash": HASH, "size": UINT, "executable": BOOL}
S["InputState"] = {
    "verified_inputs_policy_hash": HASH,
    "inventory_hash": HASH,
    "source_snapshot": HASH,
    "clean": BOOL,
    "files": array("SourceFile"),
}
S["Closure"] = {
    "mode": enum("prefixes", "verified-inputs"),
    "prefixes": array("prefix"),
    "basis": array(PATH),
    "files": array("SourceFile"),
    "hash": HASH,
}
S["EnvironmentIdentity"] = {
    "os": TEXT,
    "arch": TEXT,
    "release": TEXT,
    "variables": array(
        {"name": "envname", "present": BOOL, "value_hash": nullable(HASH)}
    ),
}
S["ToolFile"] = union(
    {"path": CWD, "kind": enum("file"), "hash": HASH, "size": UINT, "executable": BOOL},
    {"path": CWD, "kind": enum("directory")},
    {
        "path": CWD,
        "kind": enum("symlink-file"),
        "target": TEXT,
        "resolved_path": CWD,
        "resolved_hash": HASH,
        "resolved_size": UINT,
        "executable": BOOL,
    },
    {
        "path": CWD,
        "kind": enum("symlink-directory"),
        "target": TEXT,
        "resolved_path": CWD,
        "resolved_hash": HASH,
    },
)
S["PackageIdentity"] = {
    "name": NONEMPTY,
    "version": NONEMPTY,
    "source": union(
        {"kind": enum("registry"), "id": NONEMPTY, "checksum": "hex64"},
        {"kind": enum("git"), "id": NONEMPTY, "revision": "revision"},
        {"kind": enum("path"), "path": CWD},
    ),
}
PROBE = {
    "command": CMD,
    "cwd": CWD,
    "stdout_hash": HASH,
    "stderr_hash": HASH,
    "exit_code": "exit",
}
S["ToolIdentity"] = {
    "id": ID,
    "kind": enum("executable", "file", "tree"),
    "locator": union("Locator", "ProducerLocator"),
    "digest": HASH,
    "files": array("ToolFile", 1),
    "packages": array("PackageIdentity"),
    "version": nullable({**PROBE, "text": STR}),
    "discovery": array(PROBE),
    "system_dependencies": {
        "os": TEXT,
        "arch": TEXT,
        "release": TEXT,
        "sdk": nullable({"version": TEXT, "settings_hash": HASH}),
    },
    "requires": array(ID),
}
S["BuildCacheIdentity"] = nullable(
    {
        "system": enum("cargo", "lake", "node", "replay"),
        "configuration": array({"path": PATH, "hash": HASH}),
        "namespaces": array(
            {
                "role": ID,
                "kind": enum("selected-path", "producer-fresh"),
                "identity_hash": HASH,
            },
            1,
        ),
        "integrity": enum("upstream-build-system"),
    }
)
S["CommonBindings"] = {
    "policy_path": PATH,
    "policy_hash": HASH,
    "intent_path": PATH,
    "intent_hash": HASH,
    "manifest_path": PATH,
    "manifest_hash": HASH,
    "definition_files": array({"path": PATH, "hash": HASH}),
    "dispatch_hash": nullable(HASH),
    "required_targets": array(ID),
}
S["ExecutionDescriptor"] = {
    "schema_version": enum("fv-execution-descriptor/v1"),
    "common": "CommonBindings",
    "recipe": "Recipe",
    "members": array(MEMBER, 1),
    "distinct_slot": nullable(SLOT),
    "verified_inputs_policy_hash": HASH,
    "inventory_hash": HASH,
    "closure": "Closure",
    "environment": "EnvironmentIdentity",
    "toolchain": array("ToolIdentity", 1),
    "build_cache": "BuildCacheIdentity",
}
S[REF] = {"path": PATH, "hash": HASH, "size": UINT}
S["Producer"] = {
    "name": enum("fv_evidence_run"),
    "schema_version": enum("fv-evidence-run/v4"),
    "implementation_hash": HASH,
    "host_contract": enum("fv-producer-host/v1"),
}
S["OwnedProcess"] = {
    "pid": POS,
    "process_start_id": TEXT,
    "process_group": POS,
    "session_id": POS,
    "parent_pid": POS,
}
S["SpawnWindow"] = {
    "window_id": "uuid",
    "protocol": enum("native-direct/v1", "dossier-quint-private-pipes/v1"),
    "execution_key": nullable(HASH),
    "attempt_id": nullable("uuid"),
    "parent": nullable("OwnedProcess"),
    "state": enum("pending", "active", "closed", "indeterminate"),
}
S["PendingResult"] = {
    "kind": enum("execution", "observation"),
    "execution_key": HASH,
    "attempt_id": "uuid",
    "members": array(MEMBER, 1),
    "claim_id": nullable(ID),
    "slot_id": nullable(ID),
}
S["Owner"] = {
    "schema_version": enum("fv-evidence-owner/v1"),
    "owner_id": "uuid",
    "host_id": HASH,
    "boot_id": HASH,
    "pid": POS,
    "process_start_id": TEXT,
    "run_id": "uuid",
    "created_at": "utc",
    "children": array("OwnedProcess"),
    "spawn_windows": array("SpawnWindow"),
    "pending_results": array("PendingResult"),
}
S["OwnershipReceipt"] = {
    "schema_version": enum("fv-execution-ownership/v1"),
    "owner_id": "uuid",
    "children": array(
        {
            "process": "OwnedProcess",
            "window_id": "uuid",
            "registered_at": "utc",
            "terminated_at": nullable("utc"),
        }
    ),
    "spawn_windows": array("SpawnWindow"),
    "protocol_log": nullable(REF),
}
S["ExecutionArtifact"] = {
    "schema_version": enum("fv-execution-artifact/v1"),
    "artifact_id": HASH,
    "execution_key": HASH,
    "attempt_id": "uuid",
    "producer": "Producer",
    "descriptor": "ExecutionDescriptor",
    "started_at": "utc",
    "finished_at": "utc",
    "source_before": "InputState",
    "source_after": nullable("InputState"),
    "toolchain_after": nullable(array("ToolIdentity", 1)),
    "environment_after": nullable("EnvironmentIdentity"),
    "stdout": REF,
    "stderr": REF,
    "raw_output": REF,
    "attachments": array(REF),
    "ownership": "OwnershipReceipt",
    "build_cache_after": "BuildCacheIdentity",
    "termination": TERMINATION,
    "marker_matched": BOOL,
    "result": RESULT,
    "reason": nullable(STR),
}
S["ExecutionRef"] = {
    "execution_key": HASH,
    "artifact_id": HASH,
    "path": PATH,
    "hash": HASH,
}
S["HistoryRef"] = {"sequence": POS, "event_id": HASH, "path": PATH, "hash": HASH}
S["HistoryView"] = {"head": nullable("HistoryRef"), "events": array("HistoryRef")}
S["HistoryEvent"] = {
    "schema_version": enum("fv-evidence-history/v1"),
    "event_id": HASH,
    "sequence": POS,
    "previous": nullable("HistoryRef"),
    "kind": enum("execution", "observation", "indeterminate"),
    "execution_key": HASH,
    "attempt_id": "uuid",
    "members": array(MEMBER, 1),
    "execution": nullable("ExecutionRef"),
    "claim_id": nullable(ID),
    "slot_id": nullable(ID),
    "observation": nullable(REF),
    "indeterminate_owner": nullable(REF),
    "result": RESULT,
}
OBSERVATION = {"check": REF, "response": nullable(REF), "result": RESULT}
S["ClaimRecord"] = {
    "schema_version": enum("fv-evidence-run/v4"),
    "record_id": HASH,
    "run_id": "uuid",
    "claim_id": ID,
    "required": BOOL,
    "evidence_class": enum(*CLASSES),
    "scope": NONEMPTY,
    "common": "CommonBindings",
    "executions": array(
        {
            "slot_id": ID,
            "tool": "tool",
            "recipe_id": ID,
            "evidence_class": enum(*CLASSES),
            "execution": nullable("ExecutionRef"),
            "state": STATE,
            "reason": nullable(STR),
            "observation_binding": BINDING,
            "blocking_events": array("HistoryRef"),
            "observation": nullable(OBSERVATION),
        },
        1,
    ),
    "result": enum("PASS", "FAIL", "INCOMPLETE"),
    "waiver": enum(None),
}
S["ObservationRequest"] = {
    "schema_version": enum("fv-claim-observation-request/v1"),
    "request_id": "uuid",
    "policy_path": PATH,
    "policy_hash": HASH,
    "common": "CommonBindings",
    "claim_id": ID,
    "created_at": "utc",
    "slots": array(
        {
            "slot_id": ID,
            "tool": "tool",
            "recipe_id": ID,
            "execution": "ExecutionRef",
            "observation_binding": BINDING,
        },
        1,
    ),
}
S["ObservationResponse"] = {
    "schema_version": enum("fv-claim-observations/v1"),
    "request_id": "uuid",
    "request_hash": HASH,
    "claim_id": ID,
    "started_at": "utc",
    "finished_at": "utc",
    "slots": array(
        {
            "slot_id": ID,
            "result": enum("PASS", "FAIL", "ERROR"),
            "reason": nullable(STR),
            "observations": "object",
        },
        1,
    ),
}
S["ObservationCheck"] = {
    "schema_version": enum("fv-observation-check/v1"),
    "request": REF,
    "response": nullable(REF),
    "started_at": "utc",
    "finished_at": "utc",
    "termination": TERMINATION,
    "stdout": REF,
    "stderr": REF,
    "source_before": "InputState",
    "source_after": nullable("InputState"),
    "toolchain": array("ToolIdentity", 1),
    "result": RESULT,
    "reason": nullable(STR),
}
S["RunManifest"] = {
    "schema_version": enum("fv-evidence-batch/v1"),
    "run_id": "uuid",
    "policy_path": PATH,
    "policy_hash": HASH,
    "common": "CommonBindings",
    "producer": "Producer",
    "trust_assumptions": "TrustAssumptions",
    "history": "HistoryView",
    "started_at": "utc",
    "finished_at": "utc",
    "jobs": POS,
    "selected_records": array(ID, 1),
    "required_records": array(ID),
    "source_before": nullable("InputState"),
    "source_after": nullable("InputState"),
    "preflight": {
        "result": enum("PASS", "ERROR", "CANCELLED"),
        "reason": nullable(STR),
        "checks": array(
            {
                "id": ID,
                "result": enum("PASS", "ERROR", "CANCELLED", "MISSING"),
                "termination": TERMINATION,
                "stdout": nullable(REF),
                "stderr": nullable(REF),
                "reason": nullable(STR),
            }
        ),
    },
    "work": array(
        {
            "recipe_id": ID,
            "distinct_slot": nullable(SLOT),
            "execution_key": nullable(HASH),
            "execution": nullable("ExecutionRef"),
            "state": STATE,
            "cache": enum("hit", "miss", "not-checked"),
            "reason": nullable(STR),
        }
    ),
    "claims": array({"claim_id": ID, "record": REF}),
    "result": enum("PASS", "FAIL", "INCOMPLETE", "ERROR", "CANCELLED"),
    "reason": nullable(STR),
}
S["CurrentPointer"] = {
    "schema_version": enum("fv-evidence-current/v1"),
    "run_id": "uuid",
    "run": REF,
}
S["V4Call"] = {
    "schema_version": enum("fv-evidence-run/v4"),
    "policy": PATH,
    "mode": enum("plan", "run"),
    "records?": array(ID, 1),
    "jobs?": POS,
    "resume?": BOOL,
}
S["RunResult"] = {
    "schema_version": enum("fv-evidence-run-result/v1"),
    "result": enum("PASS", "FAIL", "INCOMPLETE", "ERROR", "CANCELLED"),
    "run": nullable(REF),
    "manifest": nullable("RunManifest"),
    "publication": {
        "state": enum(
            "not-attempted", "pre-replace-error", "post-replace-error", "durable"
        ),
        "candidate": nullable(REF),
    },
    "reason": nullable(STR),
}
S["PlanResult"] = {
    "schema_version": enum("fv-evidence-plan/v1"),
    "policy_path": PATH,
    "policy_hash": HASH,
    "result": enum("READY", "ERROR"),
    "reason": nullable(STR),
    "required_records": array(ID),
    "selected_records": array(ID),
    "canonical_required_targets": array(ID),
    "jobs": POS,
    "physical_slots": array(
        {
            "recipe_id": ID,
            "distinct_slot": nullable(SLOT),
            "members": array(MEMBER, 1),
            "execution_key": nullable(HASH),
            "resources": array("resource"),
            "exclusive": BOOL,
            "cache": enum("eligible", "miss", "corrupt", "not-checked"),
        }
    ),
}


def _validate(shape, value, label):
    if isinstance(shape, str) and shape in S:
        return _validate(S[shape], value, label)
    if isinstance(shape, dict):
        if not isinstance(value, dict):
            raise V4Error(f"{label}: expected object")
        required = {key for key in shape if not key.endswith("?")}
        allowed = {key.rstrip("?") for key in shape}
        if required - value.keys() or value.keys() - allowed:
            raise V4Error(
                f"{label}: missing {sorted(required - value.keys())}, unknown {sorted(value.keys() - allowed)}"
            )
        for key, subshape in shape.items():
            name = key.rstrip("?")
            if name in value:
                _validate(subshape, value[name], label + "." + name)
        return
    if isinstance(shape, tuple):
        kind = shape[0]
        if kind == "nullable":
            if value is not None:
                _validate(shape[1], value, label)
        elif kind == "enum":
            if not any(
                type(value) is type(entry) and value == entry for entry in shape[1]
            ):
                raise V4Error(f"{label}: invalid enum value")
        elif kind == "array":
            if not isinstance(value, list) or len(value) < shape[2]:
                raise V4Error(f"{label}: invalid array")
            for i, entry in enumerate(value):
                _validate(shape[1], entry, f"{label}[{i}]")
        elif kind == "union":
            for option in shape[1]:
                try:
                    _validate(option, value, label)
                    return
                except V4Error:
                    pass
            raise V4Error(f"{label}: no matching exact shape")
        return
    valid = True
    if shape in (
        STR,
        TEXT,
        NONEMPTY,
        "resource",
        ID,
        HASH,
        PATH,
        CWD,
        "prefix",
        "tool",
        "uuid",
        "utc",
        "envname",
        "hex64",
        "revision",
        "pointer",
    ):
        scalar(value)
        if shape == TEXT:
            valid = bool(value) and "\0" not in value
        elif shape == NONEMPTY:
            valid = bool(value)
        elif shape == "resource":
            valid = bool(value) and re.search(r"[\x00-\x1f\x7f-\x9f]", value) is None
        elif shape in (ID, "tool", HASH, "uuid", "envname", "hex64", "revision"):
            patterns = {
                ID: r"[A-Za-z0-9][A-Za-z0-9._-]*",
                "tool": r"[A-Za-z0-9][A-Za-z0-9._:+/-]*",
                HASH: r"sha256:[0-9a-f]{64}",
                "uuid": r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
                "envname": r"[A-Za-z_][A-Za-z0-9_]*",
                "hex64": r"[0-9a-f]{64}",
                "revision": r"(?:[0-9a-f]{40}|[0-9a-f]{64})",
            }
            valid = re.fullmatch(patterns[shape], value) is not None
        elif shape in (PATH, CWD, "prefix"):
            path(value, cwd=shape == CWD, prefix=shape == "prefix")
        elif shape == "utc":
            utc(value)
        elif shape == "pointer":
            valid = value == "" or (
                value.startswith("/") and re.search(r"~(?![01])", value) is None
            )
    elif shape in (UINT, POS, "exit"):
        valid = (
            type(value) is int
            and (-MAX_INTEGER if shape == "exit" else 1 if shape == POS else 0)
            <= value
            <= MAX_INTEGER
        )
    elif shape == BOOL:
        valid = type(value) is bool
    elif shape == CMD:
        valid = isinstance(value, list) and bool(value)
        if valid:
            for entry in value:
                _validate(TEXT, entry, label)
    elif shape == "object":
        valid = isinstance(value, dict)
    elif shape == "envmap":
        valid = isinstance(value, dict)
        if valid:
            for key, entry in value.items():
                _validate("envname", key, label)
                _validate(STR, entry, label)
                valid = valid and "\0" not in entry
    else:
        raise V4Error(f"unknown validator shape: {shape}")
    if not valid:
        raise V4Error(f"{label}: invalid {shape}")


def _require(condition, message):
    if not condition:
        raise V4Error(message)


def _package_intrinsics(value):
    source = value["source"]
    if source["kind"] == "git":
        _require(
            "#" in source["id"]
            and source["id"].rsplit("#", 1)[-1] == source["revision"],
            "PackageIdentity git revision mismatch",
        )


def _tool_intrinsics(value):
    files = value["files"]
    by_path = {entry["path"]: entry for entry in files}
    if value["kind"] != "tree":
        _require(
            len(files) == 1 and files[0]["path"] == "." and files[0]["kind"] == "file",
            "non-tree tool must have one regular root file",
        )
    if value["kind"] == "executable":
        _require(files[0]["executable"], "tool executable bit absent")
    for entry in files:
        parent = entry["path"].rsplit("/", 1)[0] if "/" in entry["path"] else None
        while parent is not None:
            _require(
                by_path.get(parent, {}).get("kind") == "directory",
                "tool path has missing/non-directory parent: " + entry["path"],
            )
            parent = parent.rsplit("/", 1)[0] if "/" in parent else None
    visiting, done = set(), set()

    def check_link(entry):
        if (
            entry["kind"] not in ("symlink-file", "symlink-directory")
            or entry["path"] in done
        ):
            return
        name = entry["path"]
        _require(name not in visiting, "cyclic tool target-hash graph")
        visiting.add(name)
        target = by_path.get(entry["resolved_path"])
        if entry["kind"] == "symlink-file":
            _require(
                target is not None
                and target["kind"] == "file"
                and (
                    entry["resolved_hash"],
                    entry["resolved_size"],
                    entry["executable"],
                )
                == (target["hash"], target["size"], target["executable"]),
                "tool symlink-file target mismatch",
            )
        else:
            _require(
                target is not None and target["kind"] == "directory",
                "tool symlink-directory target missing",
            )
            prefix = (
                "" if entry["resolved_path"] == "." else entry["resolved_path"] + "/"
            )
            descendants = [
                child
                for child in files
                if child["path"] != entry["resolved_path"]
                and child["path"].startswith(prefix)
            ]
            for child in descendants:
                check_link(child)
            relative = [
                {**child, "path": child["path"][len(prefix) :]} for child in descendants
            ]
            relative.sort(key=lambda child: child["path"].encode("utf-8"))
            _require(
                entry["resolved_hash"] == D("tool-directory", {"entries": relative}),
                "tool symlink-directory hash mismatch",
            )
        visiting.remove(name)
        done.add(name)

    for entry in files:
        check_link(entry)
    for package in value["packages"]:
        label = "packages/" + D("cargo-package", package)[7:]
        _require(
            by_path.get(label, {}).get("kind") == "directory",
            "source-qualified package root missing",
        )
    content = {
        key: value[key] for key in ("kind", "files", "packages", "system_dependencies")
    }
    _require(
        value["digest"] == D("tool-content", content), "tool content digest mismatch"
    )
    _require(
        value["version"] is None or value["version"]["exit_code"] == 0,
        "tool version probe did not complete successfully",
    )
    _require(
        all(probe["exit_code"] == 0 for probe in value["discovery"]),
        "tool discovery probe did not complete successfully",
    )


def _sets(shape, value):
    if isinstance(shape, str) and shape in S:
        _sets(S[shape], value)
        if shape == "Policy":
            if (
                value["jobs"]["max"] < 2
                or value["claim_checker"]["timeout_seconds"] is None
            ):
                raise V4Error("invalid policy job maximum/checker deadline")
        elif shape == "ToolDeclaration":
            if (value["version_command"] is None) != (value["version_cwd"] is None):
                raise V4Error("version command/cwd presence mismatch")
            if value["version_command"] is None and value["accept"]["version_contains"]:
                raise V4Error("version pin without declared probe")
        elif shape == "ToolIdentity":
            sorted_unique(value["packages"], lambda item: D("cargo-package", item))
            _tool_intrinsics(value)
        elif shape == "PackageIdentity":
            _package_intrinsics(value)
        elif shape == "HistoryView":
            if [entry["sequence"] for entry in value["events"]] != list(
                range(1, len(value["events"]) + 1)
            ) or value["head"] != (value["events"][-1] if value["events"] else None):
                raise V4Error("history view is not a complete contiguous prefix")
        return
    if isinstance(shape, tuple):
        if shape[0] == "nullable" and value is not None:
            _sets(shape[1], value)
        elif shape[0] == "array":
            for entry in value:
                _sets(shape[1], entry)
        elif shape[0] == "union":
            for option in shape[1]:
                try:
                    _validate(option, value, "union")
                except V4Error:
                    continue
                _sets(option, value)
                break
        return
    if not isinstance(shape, dict):
        return
    for raw_key, entry_shape in shape.items():
        key = raw_key.rstrip("?")
        if key not in value:
            continue
        entry = value[key]
        _sets(entry_shape, entry)
        if not isinstance(entry, list):
            continue
        if key in (
            "resources",
            "requires",
            "inherit",
            "identity",
            "prefixes",
            "basis",
            "sha256",
            "retained_environment",
            "configuration",
            "required_targets",
            "required_records",
            "selected_records",
            "canonical_required_targets",
        ):
            sorted_unique(
                entry, lambda item: item["path"] if isinstance(item, dict) else item
            )
        elif key == "toolchain":
            sorted_unique(
                entry, lambda item: item["id"] if isinstance(item, dict) else item
            )
        elif key in ("files", "attachments", "definition_files"):
            sorted_unique(
                entry, lambda item: item["path"] if isinstance(item, dict) else item
            )
        elif key == "members":
            sorted_unique(entry, lambda item: (item["claim_id"], item["slot_id"]))
        elif key == "platforms":
            sorted_unique(entry, lambda item: (item["os"], item["arch"]))
        elif key == "variables":
            sorted_unique(entry, lambda item: item["name"])
        elif key == "namespaces":
            sorted_unique(entry, lambda item: item["role"])
        elif key == "blocking_events":
            sequences = [item["sequence"] for item in entry]
            if sequences != sorted(set(sequences)):
                raise V4Error("blocking history references are not unique ordered")
        elif key in (
            "toolchains",
            "recipes",
            "records",
            "preflight",
            "checks",
            "executions",
            "slots",
            "claims",
        ):
            if entry and isinstance(entry[0], dict):
                identity = {
                    "toolchains": "id",
                    "recipes": "recipe_id",
                    "records": "claim_id",
                    "preflight": "id",
                    "checks": "id",
                    "executions": "slot_id",
                    "slots": "slot_id",
                    "claims": "claim_id",
                }[key]
                identifiers = [item[identity] for item in entry]
                if len(set(identifiers)) != len(identifiers):
                    raise V4Error("duplicate ordered entry ID")
                if key == "executions" and len({item["tool"] for item in entry}) != len(
                    entry
                ):
                    raise V4Error("duplicate claim tool")
            elif key == "records":
                sorted_unique(entry)


def validate(shape, value):
    _grammar(value)
    _validate(shape, value, shape if isinstance(shape, str) else "value")
    _sets(shape, value)
    return value


def validate_call(value):
    validate("V4Call", value)
    if "records" in value:
        sorted_unique(value["records"])
    return value
