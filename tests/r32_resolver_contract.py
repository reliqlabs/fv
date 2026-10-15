#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""R32: FV resolves named panel roles from OMP settings through OMP's real resolver."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RESOLVER = REPO / "tools" / "panel-resolver.ts"
FAILURES: list[str] = []


def omp_panel_module() -> Path | None:
    candidates: list[Path] = []
    source = os.environ.get("OMP_SOURCE")
    if source:
        candidates.append(Path(source))
    omp = shutil.which("omp")
    if omp:
        candidates.extend(Path(omp).resolve().parents)
    for candidate in candidates:
        module = candidate / "packages" / "coding-agent" / "src" / "panel" / "index.ts"
        if module.is_file():
            return module
    return None


HARNESS_TS = r"""
const [, , resolverPath, settingsPath, role, panelModule, injectPanel] = process.argv;
const mod = await import(resolverPath);
const panel = injectPanel === "yes" ? await import(panelModule) : {};
const settingsModule = await import((await import("node:path")).resolve(panelModule, "..", "..", "config", "settings.ts"));
const { z: zod } = await import((await import("node:path")).resolve(panelModule, "..", "..", "..", "..", "omptype", "src", "zod.ts"));
const panelSettings = await Bun.file(settingsPath).json();
const MODELS = [
  { id: "gpt-5", provider: "openai" },
  { id: "claude-opus-4-1", provider: "anthropic" },
  { id: "claude-sonnet-4-5", provider: "anthropic" },
  { id: "gpt-5-mini", provider: "openai" },
  { id: "kimi-k3", provider: "fireworks" },
  { id: "gpt-5", provider: "openai-codex" },
];
const api = { cwd: process.cwd(), zod, pi: panel };
const settings = settingsModule.Settings.isolated({ panel: panelSettings, modelRoles: { plan: "openai/gpt-5" } });
const tool = await mod.default(api);
try {
  const result = await tool.execute(
    "tc",
    { role, mode: "project-plan", synthesizer: "openai/gpt-5" },
    undefined,
    { settings, modelRegistry: { getAvailable: () => MODELS, hasConfiguredAuth: () => true } },
  );
  console.log(JSON.stringify({ ok: true, roster: result.details, tool_name: tool.name }));
} catch (error: unknown) {
  console.log(JSON.stringify({ ok: false, error: error instanceof Error ? error.message : String(error), tool_name: tool.name }));
}
"""

PANEL_SETTINGS = {
    "roles": {
        "dup": {
            "strategy": "independent", "minFamilies": 2,
            "members": [{"model": "openai/gpt-5"}, {"model": "anthropic/claude-opus-4-1"}],
        },
        "hidden": {
            "strategy": "independent", "minFamilies": 2,
            "members": [
                {"model": "unavailable/gpt-5-mini", "fallbacks": ["openai/gpt-5-mini"]},
                {"model": "anthropic/claude-sonnet-4-5"},
            ],
        },
        "bare": {
            "strategy": "independent", "minFamilies": 2,
            "members": [{"model": "claude-sonnet-4-5"}, {"model": "gpt-5-mini"}],
        },
        "collide": {
            "strategy": "independent", "minFamilies": 2,
            "members": [{"model": "openai/gpt-5"}, {"model": "openai-codex/gpt-5"}],
        },
        "none": {
            "strategy": "independent", "minFamilies": 2,
            "members": [{"model": "openai/gpt-5"}, {"model": "nope/nothing"}],
        },
        "calibration-fallback": {
            "strategy": "independent", "minFamilies": 2,
            "members": [
                {"model": "openai/gpt-5"},
                {"model": "synthetic/hf:moonshotai/Kimi-K3", "fallbacks": ["fireworks/kimi-k3"]},
            ],
        },
    },
    "personas": {},
}


def check(label: str, ok: bool, detail: object = "") -> None:
    if ok:
        print(f"[ok] {label}")
    else:
        print(f"[FAIL] {label}: {detail}")
        FAILURES.append(label)


def main() -> int:
    if shutil.which("bun") is None:
        print("SKIP: bun not on PATH; cannot execute the resolver extension")
        return 2
    if not RESOLVER.is_file():
        print(f"[FAIL] resolver missing: {RESOLVER}")
        return 1
    panel_module = omp_panel_module()
    if panel_module is None:
        print("SKIP: OMP panel module not found; set OMP_SOURCE to the oh-my-pi checkout")
        return 2

    with tempfile.TemporaryDirectory(prefix="r32-") as td:
        root = Path(td)
        harness = root / "harness.ts"
        settings = root / "panel-settings.json"
        harness.write_text(HARNESS_TS)
        settings.write_text(json.dumps(PANEL_SETTINGS))

        def run(role: str, inject_panel: bool = True) -> dict:
            proc = subprocess.run(
                ["bun", "run", str(harness), str(RESOLVER), str(settings), role,
                 str(panel_module), "yes" if inject_panel else "no"],
                cwd=REPO, capture_output=True, text=True, timeout=120,
            )
            lines = (proc.stdout or "").strip().splitlines()
            if not lines:
                return {"ok": False, "error": f"no output (rc={proc.returncode}): {proc.stderr[-400:]}"}
            try:
                return json.loads(lines[-1])
            except json.JSONDecodeError:
                return {"ok": False, "error": f"unparseable: {lines[-1][:300]}"}

        dup = run("dup")
        check("resolver loads and reads a named OMP panel role",
              dup.get("ok") and dup.get("tool_name") == "fv_panel_resolve"
              and dup["roster"]["role"] == "dup", dup)
        if dup.get("ok"):
            seats = dup["roster"]["seats"]
            check("resolved model selectors stay provider-qualified",
                  [seat["resolved_model"] for seat in seats] == ["openai/gpt-5", "anthropic/claude-opus-4-1"], seats)
            check("declared quorum labels come from OMP resolved families",
                  [seat["declared_family"] for seat in seats] == ["openai", "anthropic"], seats)
            check("synthesizer resolves through the OMP model selector",
                  dup["roster"]["synthesizer"]["resolved_model"] == "openai/gpt-5",
                  dup["roster"]["synthesizer"])

        hidden = run("hidden")
        check("OMP role candidates fall through in priority order",
              hidden.get("ok")
              and hidden["roster"]["seats"][0]["requested_selector"] == "openai/gpt-5-mini",
              hidden)

        calibration_fallback = run("calibration-fallback")
        check("fallback routes never inherit primary-route calibration",
              calibration_fallback.get("ok")
              and calibration_fallback["roster"]["seats"][1]["requested_selector"] == "fireworks/kimi-k3"
              and calibration_fallback["roster"]["seats"][1]["calibration"] == "pending",
              calibration_fallback)

        bare = run("bare")
        check("bare OMP model ids resolve to provider-qualified selectors",
              bare.get("ok")
              and [seat["resolved_model"] for seat in bare["roster"]["seats"]] == ["anthropic/claude-sonnet-4-5", "openai/gpt-5-mini"],
              bare)

        collide = run("collide")
        check("OMP rejects the same model family served through different providers",
              not collide.get("ok") and "duplicate resolved model family" in collide.get("error", ""), collide)

        none = run("none")
        check("OMP rejects a panel role with no available candidate",
              not none.get("ok") and "nope/nothing" in none.get("error", ""), none)

        missing = run("dup", inject_panel=False)
        check("missing OMP panel API fails closed",
              not missing.get("ok") and "panelLineupFreeze" in missing.get("error", ""), missing)

    if FAILURES:
        print(f"\nR32: {len(FAILURES)} failure(s)")
        return 1
    print("\nR32: all assertions passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
