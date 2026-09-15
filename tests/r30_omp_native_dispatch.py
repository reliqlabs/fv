#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""R30: OMP-native model fan-out is routed, isolated, and auditable."""
from __future__ import annotations

import importlib.util
import functools
import os
import json
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
HELPER = REPO / "skills" / "fv-adversarial" / "omp_fanout.py"
CONFIG = REPO / "scripts" / "dispatch.config.example.json"
CHECKER = REPO / "scripts" / "check_dispatch_config.py"
FAILURES: list[str] = []


def pem_begin(kind: str) -> str:
    """Assemble a PEM armor opening line at RUNTIME.

    Written literally, this line would make the preflight scanner flag its own
    test suite, and dispatching a fan-out with `project_root` set to this repo
    would fail closed on two false positives. The scanner's regex needs
    `-----BEGIN ...PRIVATE KEY-----` contiguous, so concatenation keeps the
    fixture value identical while leaving no armor in the source.
    """
    return "-----BEGIN " + kind + "-----"


def check(label: str, ok: bool, detail: object = "") -> None:
    if ok:
        print(f"[ok] {label}")
    else:
        print(f"[FAIL] {label}: {detail}")
        FAILURES.append(label)


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_helper():
    return load_module("omp_fanout", HELPER)


def raises(fn, text: str) -> bool:
    try:
        fn()
    except Exception as exc:
        return text in str(exc)
    return False


def serial_parallel(thunks):
    # The production bridge runs these concurrently. Serial execution keeps the
    # fixture deterministic while exercising the same failure-isolated thunks.
    return [thunk() for thunk in thunks]


def main() -> int:
    mod = load_helper()
    # Every run_omp_fanout call needs the isolation opt-in; inject it once so
    # the individual call sites stay readable. Refusal tests override it.
    mod.run_omp_fanout = functools.partial(
        mod.run_omp_fanout, allow_unverified_isolation=True)
    route = mod.load_omp_native_config(CONFIG)
    check("canonical OMP route resolves all four voices",
          [voice["id"] for voice in route["voices"]]
          == ["claude-agent", "gpt-5.6-sol", "glm-5.2", "kimi-k3"])
    check("canonical OMP route is explicitly uncalibrated",
          route["calibration"] == "pending")

    # Raw evidence must be the VOICE's text, not a transport envelope. A subagent
    # yielding structured output used to land on disk as escaped JSON, which made
    # three of four r3 voices read as unparseable despite compliant output.
    check("a lone-string structured payload is unwrapped",
          mod._result_text({"data": {"findings": "```json\n[]\n```"}})[0]
          == "```json\n[]\n```")
    check("a plain string result is untouched",
          mod._result_text("verbatim")[0] == "verbatim")
    check("text field still wins over data",
          mod._result_text({"text": "chosen", "data": {"x": "ignored"}})[0] == "chosen")
    # Two fields give no basis for choosing; guessing would drop evidence.
    multi = mod._result_text({"data": {"a": "one", "b": "two"}})[0]
    check("a multi-field payload is preserved whole, not guessed at",
          json.loads(multi) == {"a": "one", "b": "two"}, multi)
    check("a non-string lone value is preserved as JSON",
          json.loads(mod._result_text({"data": {"findings": [1, 2]}})[0])
          == {"findings": [1, 2]})
    # The generated config must carry exactly the registry's levels. The policy
    # itself is checked against each voice's recorded ladder in r0; duplicating
    # a hardcoded level table here would just be a second thing to update, and
    # it is what broke when GLM's provider changed its top rung's name.
    registry = json.loads((REPO / "registry" / "voices.json").read_text())
    canonical = {v["id"]: v for v in registry["voices"]}
    check("config levels match the registry, voice for voice",
          {v["id"]: v["thinking_level"] for v in route["voices"]}
          == {v["id"]: canonical[v["id"]]["omp_thinking_level"]
              for v in route["voices"]},
          {v["id"]: v.get("thinking_level") for v in route["voices"]})
    check("dispatch selector carries the per-voice level",
          all(v["dispatch_selector"] == f"{v['model']}:{v['thinking_level']}"
              for v in route["voices"]),
          [v["dispatch_selector"] for v in route["voices"]])
    check("route records the effort policy", route["thinking_policy"] == "one-below-max")
    check("a voice with no thinking level fails closed",
          raises(lambda: mod._validate_voice(
              {"id": "v", "model": "p/m", "family": "F", "calibration": "pending"}),
                 "thinking_level"))
    check("a null thinking level dispatches the bare model",
          mod._validate_voice({"id": "v", "model": "p/m", "family": "F",
                               "calibration": "pending",
                               "thinking_level": None})["dispatch_selector"] == "p/m")
    check("route hash covers the thinking level",
          mod._route_hash({"agent": "a", "thinking_policy": "one-below-max",
                           "voices": [{"id": "v", "model": "p/m",
                                       "thinking_level": "high"}]})
          != mod._route_hash({"agent": "a", "thinking_policy": "one-below-max",
                              "voices": [{"id": "v", "model": "p/m",
                                          "thinking_level": "max"}]}))
    check("base selector strips only a real thinking level",
          mod._base_selector("synthetic/hf:zai-org/GLM-5.2:xhigh")
          == "synthetic/hf:zai-org/GLM-5.2"
          and mod._base_selector("synthetic/hf:moonshotai/Kimi-K3")
          == "synthetic/hf:moonshotai/Kimi-K3"
          and mod._base_selector("burnt/cloudflare-100/@cf/moonshotai/kimi-k2.6")
          == "burnt/cloudflare-100/@cf/moonshotai/kimi-k2.6")
    # OMP rewrites resolvedModel to the fallback target, so a differing served
    # model is positive evidence a retry chain answered. Equality is NOT clean:
    # the bridge reports `resolvedModel ?? modelOverride`.
    fired = mod.classify_served_route(
        "synthetic/hf:zai-org/GLM-5.2:xhigh",
        {"text": "r", "details": {"model": "fireworks/glm-5.2:high"}})
    check("a differing served model is recorded as a fallback",
          fired["served_is_fallback"] is True
          and fired["served_model"] == "fireworks/glm-5.2:high"
          and fired["fallback_basis"].startswith("inferred:"))
    same = mod.classify_served_route(
        "fireworks/kimi-k3:high",
        {"text": "r", "details": {"model": "fireworks/kimi-k3:high"}})
    check("an equal served model is recorded as ambiguous, not clean",
          same["served_is_fallback"] is False
          and "ambiguous" in same["fallback_basis"])
    authoritative = mod.classify_served_route(
        "fireworks/kimi-k3:high",
        {"text": "r", "details": {"model": "fireworks/kimi-k3:high",
                                  "resolvedModelIsFallback": True}})
    check("OMP's own flag outranks selector comparison when present",
          authoritative["served_is_fallback"] is True
          and authoritative["fallback_basis"] == "omp-reported")
    check("a missing served model is unknown, never a clean False",
          mod.classify_served_route("p/m:high", {"text": "r"})["served_is_fallback"]
          is None)
    overlay = mod.fallback_suppression_overlay(route["voices"])
    expected_suppressed = sorted(
        mod._base_selector(voice["dispatch_selector"]) for voice in route["voices"]
    )
    check("suppression overlay disables exactly every selected base selector",
          overlay == {"retry": {"fallbackChains": {
              selector: [] for selector in expected_suppressed
          }}}, overlay)
    duplicate = dict(route["voices"][0])
    duplicate["id"] = "duplicate"
    check("suppression refuses two voices sharing one base selector",
          raises(lambda: mod.fallback_suppression_overlay([route["voices"][0], duplicate]),
                 "share a base selector"))
    suppressed_same = mod.classify_served_route(
        "fireworks/kimi-k3:high",
        {"text": "r", "details": {"model": "fireworks/kimi-k3:high"}},
        suppressed_selectors=frozenset({"fireworks/kimi-k3"}))
    check("a prechecked suppressed route establishes an equal selector",
          suppressed_same["served_is_fallback"] is False
          and suppressed_same["fallback_basis"].startswith("configured-suppression:")
          and mod._route_established(suppressed_same))
    selected = mod.load_omp_native_config(
        CONFIG, selected_ids=["glm-5.2", "claude-agent"])
    check("explicit OMP voice order is preserved",
          [voice["id"] for voice in selected["voices"]]
          == ["glm-5.2", "claude-agent"])
    check("unknown OMP voice fails closed",
          raises(lambda: mod.load_omp_native_config(
              CONFIG, selected_ids=["not-registered"]), "not registered"))

    drifted = json.loads(CONFIG.read_text())
    drifted["omp_native"]["voices"][0]["model"] = "wrong/model"
    with tempfile.TemporaryDirectory(prefix="r30-config-") as td:
        bad_config = Path(td) / "dispatch.json"
        bad_config.write_text(json.dumps(drifted))
        check("OMP route hash catches model drift",
              raises(lambda: mod.load_omp_native_config(bad_config), "hash drift"))

    calls: list[tuple[str, str]] = []

    def fake_agent(prompt: str, **options):
        model = options["model"]
        calls.append((model, prompt))
        if model == selected["voices"][0]["dispatch_selector"]:
            raise RuntimeError("provider unavailable")
        voice_id = options["label"].removeprefix("omp-")
        return {
            "text": f"report from {model}",
            "output": f"report from {model}",
            "handle": f"agent://{voice_id}",
            "id": voice_id,
            "agent": options["agent"],
            "details": {"model": model},
        }

    with tempfile.TemporaryDirectory(prefix="r30-run-") as td:
        root = Path(td)
        # A session whose documented header cwd == project_root: the gate's
        # trusted signal (PI_SESSION_FILE) for every run in this block.
        sess = root / "session.jsonl"
        sess.write_text('{"type":"title","v":1}\n'
                        + json.dumps({"type": "session", "id": "r30sess",
                                      "cwd": str(root)}) + "\n")
        os.environ["PI_SESSION_FILE"] = str(sess)
        target = root / "intent.md"
        target.write_text("# Intent\n")
        evidence_dir = root / "calibration"
        evidence_dir.mkdir()
        certificate_overlay = evidence_dir / "fallback-suppression.json"
        certificate_overlay.write_text(json.dumps(
            mod.fallback_suppression_overlay(selected["voices"]), indent=2) + "\n")
        certificate_precheck = evidence_dir / "fallback-precheck.json"
        certificate_precheck.write_text(json.dumps({
            "command": ["omp", "config", "get", "retry.fallbackChains"],
            "cwd": str(root),
            "environment": {"PI_CONFIG_FILES": str(certificate_overlay)},
            "overlay_sha256": mod._sha256_file(certificate_overlay),
            "effective_fallback_chains": (
                mod.fallback_suppression_overlay(selected["voices"])
                ["retry"]["fallbackChains"]
            ),
        }, indent=2) + "\n")
        certificate = mod.load_fallback_suppression(
            selected["voices"], certificate_overlay, certificate_precheck)
        check("suppression certificate binds the selected overlay and precheck",
              certificate["status"] == "prechecked-suppression"
              and certificate["suppressed_selectors"] == sorted(
                  mod.fallback_suppression_overlay(selected["voices"])
                  ["retry"]["fallbackChains"])
              and certificate["overlay_sha256"] == mod._sha256_file(certificate_overlay))
        invalid_precheck = evidence_dir / "invalid-precheck.json"
        invalid_effective = dict(json.loads(
            certificate_precheck.read_text())["effective_fallback_chains"])
        invalid_effective[mod._base_selector(selected["voices"][0]["dispatch_selector"])] = [
            "fallback/model"
        ]
        invalid_precheck.write_text(json.dumps({
            "command": ["omp", "config", "get", "retry.fallbackChains"],
            "cwd": str(root),
            "environment": {"PI_CONFIG_FILES": str(certificate_overlay)},
            "overlay_sha256": mod._sha256_file(certificate_overlay),
            "effective_fallback_chains": invalid_effective,
        }) + "\n")
        check("suppression precheck fails closed on an eligible fallback",
              raises(lambda: mod.load_fallback_suppression(
                  selected["voices"], certificate_overlay, invalid_precheck),
                  "leaves a tested route eligible"))
        run_dir = root / ".fv" / "attacks" / "partial"
        summary = mod.run_omp_fanout(
            agent_fn=fake_agent,
            parallel_fn=serial_parallel,
            voices=selected["voices"],
            project_root=root,
            target_spec=target,
            prompt="TARGET_SPEC: intent.md",
            run_dir=run_dir,
            metadata={
                "profile": route["profile"],
                "route_hash": route["route_hash"],
                "calibration": route["calibration"],
                "phase": "attack",
            },
            fallback_suppression=certificate,
        )
        check("one failed voice does not sink surviving reports",
              summary["verdict"] == "PARTIAL" and summary["voices_ok"] == 1,
              summary)
        check("every requested OMP voice was invoked", len(calls) == 2, calls)
        statuses = {voice["id"]: voice["status"] for voice in summary["voices"]}
        check("failed provider is recorded as error",
              statuses == {"glm-5.2": "error", "claude-agent": "ok"}, statuses)
        check("successful report persists verbatim",
              (run_dir / "raw" / "omp-claude-agent.md").read_text()
              == f"report from {selected['voices'][1]['dispatch_selector']}")
        check("provider error persists independently",
              "provider unavailable" in
              (run_dir / "raw" / "omp-glm-5.2.error.txt").read_text())
        check("native bridge never invents finish reasons",
              all(voice["finish_reason"] is None for voice in summary["voices"]))
        # The fake echoes the requested selector. Without a bridge provenance
        # field this is normally ambiguous, but the validated empty-chain
        # certificate makes the surviving route established.
        check("suppression certificate closes only the certified route ambiguity",
              summary["served_by_fallback"] == []
              and summary["route_unverified"] == [],
              {"fallback": summary["served_by_fallback"],
               "unverified": summary["route_unverified"]})
        check("an errored voice is not counted as an unverified route",
              "glm-5.2" not in summary["route_unverified"])
        check("requested selector is recorded per voice",
              all(voice["requested_selector"] == voice["dispatch_selector"]
                  for voice in summary["voices"]))
        check("summary is written last as parseable JSON",
              json.loads((run_dir / "summary.json").read_text())["verdict"]
              == "PARTIAL")
        check("preflight binds the target specification hash",
              summary["preflight"]["status"] == "ok"
              and summary["preflight"]["target_spec"] == "intent.md"
              and summary["preflight"]["target_spec_sha256"].startswith("sha256:"))
        meta = json.loads((run_dir / "meta.json").read_text())
        check("run metadata binds route, calibration, and suppression certificate",
              meta["metadata"]["route_hash"] == route["route_hash"]
              and meta["metadata"]["calibration"] == "pending"
              and meta["fallback_suppression"] == certificate
              and summary["fallback_suppression"] == certificate)
        check("run directory cannot be overwritten",
              raises(lambda: mod.run_omp_fanout(
                  agent_fn=fake_agent,
                  parallel_fn=serial_parallel,
                  voices=selected["voices"],
                  project_root=root,
                  target_spec=target,
                  prompt="again",
                  run_dir=run_dir,
              ), "File exists"))

        def all_fail(_prompt: str, **_options):
            raise RuntimeError("offline")

        failed = mod.run_omp_fanout(
            agent_fn=all_fail,
            parallel_fn=serial_parallel,
            voices=selected["voices"],
            project_root=root,
            target_spec=target,
            prompt_by_voice={
                "glm-5.2": "critique A",
                "claude-agent": "critique B",
            },
            run_dir=root / ".fv" / "attacks" / "all-fail",
            metadata={"phase": "critique"},
        )
        check("all-failed native wave is INCOMPLETE",
              failed["verdict"] == "INCOMPLETE" and failed["voices_ok"] == 0)
        check("per-voice critique prompts persist verbatim",
              (root / ".fv" / "attacks" / "all-fail"
               / "prompts" / "glm-5.2.md").read_text()
              == "critique A")

        def mutate_target(_prompt: str, **_options):
            target.write_text("# Changed during dispatch\n")
            return "report against unstable target"

        unstable = mod.run_omp_fanout(
            agent_fn=mutate_target,
            parallel_fn=serial_parallel,
            voices=[selected["voices"][1]],
            project_root=root,
            target_spec=target,
            prompt="attack",
            run_dir=root / ".fv" / "attacks" / "target-drift",
        )
        check("target drift makes an otherwise successful wave INCOMPLETE",
              unstable["voices_ok"] == 1
              and unstable["verdict"] == "INCOMPLETE"
              and unstable["target_spec_stable"] is False)
        def exploding_parallel(_thunks):
            raise RuntimeError("wave crashed")

        crash_dir = root / ".fv" / "attacks" / "wave-crash"
        check("orchestration crash re-raises",
              raises(lambda: mod.run_omp_fanout(
                  agent_fn=fake_agent,
                  parallel_fn=exploding_parallel,
                  voices=selected["voices"],
                  project_root=root,
                  target_spec=target,
                  prompt="attack",
                  run_dir=crash_dir,
              ), "wave crashed"))
        crash = json.loads((crash_dir / "summary.json").read_text())
        check("orchestration crash still persists an INCOMPLETE summary",
              crash["verdict"] == "INCOMPLETE" and crash["voices_ok"] == 0
              and "wave crashed" in crash.get("orchestration_error", ""))

        def dropping_parallel(thunks):
            return [thunk() for thunk in thunks][:-1]

        drop_dir = root / ".fv" / "attacks" / "wave-mismatch"
        check("wave result-count mismatch re-raises",
              raises(lambda: mod.run_omp_fanout(
                  agent_fn=fake_agent,
                  parallel_fn=dropping_parallel,
                  voices=selected["voices"],
                  project_root=root,
                  target_spec=target,
                  prompt="attack",
                  run_dir=drop_dir,
              ), "results for"))
        drop = json.loads((drop_dir / "summary.json").read_text())
        check("wave mismatch still persists an INCOMPLETE summary",
              drop["verdict"] == "INCOMPLETE" and "orchestration_error" in drop)

        check("run stamps isolation unverified with session-root source",
              summary["isolation"]["status"] == "unverified"
              and summary["isolation"]["session_root_source"]
                  == "PI_SESSION_FILE session-header cwd"
              and Path(summary["isolation"]["session_root"]).resolve()
                  == root.resolve())
        check("meta stamps isolation unverified",
              meta["isolation"]["status"] == "unverified")
        acks = len(calls)
        check("missing isolation opt-in refuses before dispatch",
              raises(lambda: mod.run_omp_fanout(
                  agent_fn=fake_agent, parallel_fn=serial_parallel,
                  voices=selected["voices"], project_root=root, target_spec=target,
                  prompt="x", run_dir=root / ".fv" / "attacks" / "no-ack",
                  allow_unverified_isolation=False), "isolation is unverified")
              and len(calls) == acks)
        with tempfile.TemporaryDirectory(prefix="r30-otherroot-") as other:
            wrong = Path(other) / "s.jsonl"
            wrong.write_text(json.dumps(
                {"type": "session", "id": "w", "cwd": other}) + "\n")
            os.environ["PI_SESSION_FILE"] = str(wrong)
            m0 = len(calls)
            check("session root mismatch refuses before dispatch",
                  raises(lambda: mod.run_omp_fanout(
                      agent_fn=fake_agent, parallel_fn=serial_parallel,
                      voices=selected["voices"], project_root=root,
                      target_spec=target, prompt="x",
                      run_dir=root / ".fv" / "attacks" / "mismatch"),
                      "not project_root")
                  and len(calls) == m0)
        os.environ["PI_SESSION_FILE"] = str(sess)
        saved = os.environ.pop("PI_SESSION_FILE", None)
        m1 = len(calls)
        check("absent session metadata refuses before dispatch",
              raises(lambda: mod.run_omp_fanout(
                  agent_fn=fake_agent, parallel_fn=serial_parallel,
                  voices=selected["voices"], project_root=root, target_spec=target,
                  prompt="x", run_dir=root / ".fv" / "attacks" / "no-sess"),
                  "cannot confirm the OMP session root")
              and len(calls) == m1)
        if saved is not None:
            os.environ["PI_SESSION_FILE"] = saved
        (root / ".env").write_text("SECRET=value\n")
        blocked_dir = root / ".fv" / "attacks" / "blocked"
        calls_before = len(calls)
        blocked = raises(lambda: mod.run_omp_fanout(
            agent_fn=fake_agent,
            parallel_fn=serial_parallel,
            voices=selected["voices"],
            project_root=root,
            target_spec=target,
            prompt="attack",
            run_dir=blocked_dir,
        ), "preflight blocked")
        check("secret-bearing project fails before any model call",
              blocked and len(calls) == calls_before)
        check("blocked preflight remains auditable",
              json.loads((blocked_dir / "preflight.json").read_text())["status"]
              == "blocked")

    with tempfile.TemporaryDirectory(prefix="r30-scan-") as td:
        sroot = Path(td)
        (sroot / "clean.rs").write_text("fn main() {}\n")
        check("clean tree scans clean",
              mod.preflight_scan(sroot) == [], mod.preflight_scan(sroot))
        (sroot / "notes.txt").write_text(
            "context\n" + pem_begin("OPENSSH PRIVATE KEY") + "\nAAAA\n")
        v = mod.preflight_scan(sroot)
        check("openssh key in a non-secret-named file is caught",
              any("private-key material" in x and "notes.txt" in x for x in v), v)
        (sroot / "backup.asc").write_text(
            pem_begin("PGP PRIVATE KEY BLOCK") + "\nlQ...\n")
        v = mod.preflight_scan(sroot)
        check("pgp private-key block is caught",
              any("private-key material" in x and "backup.asc" in x for x in v), v)
        (sroot / "scanner_src.py").write_text(
            'M1 = b"PRIVATE KEY-----"\nM2 = b"PRIVATE KEY BLOCK"\n')
        v = mod.preflight_scan(sroot)
        check("marker constants without BEGIN armor are not flagged",
              not any("scanner_src.py" in x for x in v), v)
        if hasattr(os, "geteuid") and os.geteuid() != 0:
            opaque = sroot / "opaque.bin"
            opaque.write_bytes(b"\x00" * 32)
            os.chmod(opaque, 0)
            try:
                v = mod.preflight_scan(sroot)
                check("unreadable file fails closed (recorded, not skipped)",
                      any("unreadable file" in x and "opaque.bin" in x for x in v), v)
            finally:
                os.chmod(opaque, 0o644)

        # Derived trees are out of scope, but the narrowing must be signature-
        # based and recorded -- never "a directory named target is probably
        # build output". A real Cargo target carries CACHEDIR.TAG; a REVIEW
        # target sharing the name does not and stays in scope.
        cargo_target = sroot / "target"
        (cargo_target / "deps").mkdir(parents=True)
        (cargo_target / "CACHEDIR.TAG").write_text(
            "Signature: 8a477f597d28d172789f06886806bc55\n")
        (cargo_target / "deps" / "lib.rmeta").write_text(
            "docs\n" + pem_begin("PRIVATE KEY") + "\nPKCS#8 example\n")
        modules = sroot / "node_modules" / "pkg"
        modules.mkdir(parents=True)
        (modules / "fixture.pem").write_text(pem_begin("PRIVATE KEY") + "\n")
        skipped: list[str] = []
        v = mod.preflight_scan(sroot, skipped)
        check("a CACHEDIR.TAG tree is out of scope, not a violation",
              not any("target/" in x for x in v)
              and not any("node_modules" in x for x in v), v)
        check("every skipped root is recorded for audit",
              {"target", "node_modules"} <= set(skipped), skipped)

        review = sroot / "review" / "target"
        (review / "src").mkdir(parents=True)
        (review / "Cargo.toml").write_text("[package]\nname='x'\n")
        (review / "src" / "planted.rs").write_text(
            "// " + pem_begin("PRIVATE KEY") + "\n")
        skipped2: list[str] = []
        v2 = mod.preflight_scan(sroot, skipped2)
        check("a review target without the tag stays in scope",
              any("planted.rs" in x for x in v2)
              and "review/target" not in skipped2,
              {"violations": v2, "skipped": skipped2})

    # --require-paths must measure a project config from the project root, not
    # from the .fv directory that holds it. Resolving "." against .fv looked
    # for <project>/.fv/.fv/intent.md, so every canonical project config failed
    # path validation, and a moved project failed for the same reason.
    checker = load_module("check_dispatch_config", CHECKER)
    with tempfile.TemporaryDirectory(prefix="r30-paths-") as td:
        tmp = Path(td)
        canonical = json.loads(CONFIG.read_text())

        def config_at(path: Path, project_root: str, target_spec: str) -> Path:
            route = json.loads(json.dumps(canonical))
            route["omp_native"]["project_root"] = project_root
            route["omp_native"]["target_spec"] = target_spec
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(route))
            return path

        alpha = tmp / "alpha"
        (alpha / ".fv").mkdir(parents=True)
        (alpha / ".fv" / "intent.md").write_text("# intent\n")
        dispatch = config_at(alpha / ".fv" / "dispatch.json", ".", ".fv/intent.md")
        check("a project config's '.' is the project root, not its .fv dir",
              checker.project_base(dispatch) == alpha,
              checker.project_base(dispatch))
        errors = checker.check_file(dispatch, True)
        check("canonical repo-relative project config passes --require-paths",
              errors == [], errors)

        # The regression: the bytes on disk never change, only the project's
        # location. A repo-relative config is portable by construction.
        beta = tmp / "moved" / "beta"
        beta.parent.mkdir(parents=True)
        alpha.rename(beta)
        moved = beta / ".fv" / "dispatch.json"
        errors = checker.check_file(moved, True)
        check("the identical config still passes after the project moves",
              errors == [], errors)

        # Arbitrary config locations keep resolving against their own directory.
        outside = config_at(tmp / "elsewhere" / "dispatch.json",
                            "../moved/beta", ".fv/intent.md")
        errors = checker.check_file(outside, True)
        check("a config kept outside .fv resolves from its own directory",
              errors == [], errors)
        stale = config_at(tmp / "elsewhere" / "stale.json", "no-such-project",
                          ".fv/intent.md")
        errors = checker.check_file(stale, True)
        check("a bad project_root is still reported",
              any("project_root does not exist" in item for item in errors),
              errors)

        # Legacy absolute values inside the project remain acceptable.
        legacy = config_at(beta / ".fv" / "legacy.json", str(beta),
                           str(beta / ".fv" / "intent.md"))
        errors = checker.check_file(legacy, True)
        check("legacy absolute inside-project values still validate",
              errors == [], errors)
        (tmp / "outsider.md").write_text("# not ours\n")
        escaping = config_at(beta / ".fv" / "escape.json", ".",
                             "../../outsider.md")
        errors = checker.check_file(escaping, True)
        check("a target escaping the project root is rejected",
              any("escapes project_root" in item for item in errors), errors)
        absent = config_at(beta / ".fv" / "absent.json", ".", ".fv/missing.md")
        errors = checker.check_file(absent, True)
        check("a missing target_spec is rejected",
              any("target_spec does not exist" in item for item in errors),
              errors)

    print()
    if FAILURES:
        print(f"R30: {len(FAILURES)} failure(s)")
        return 1
    print("R30: all assertions passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
