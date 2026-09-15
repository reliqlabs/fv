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
const stub: any = {};
for (const key of ["min", "max", "optional", "describe", "default", "nullable", "array"]) stub[key] = () => stub;
stub.parse = (value: any) => value;
const zod: any = new Proxy(stub, { get: (target, key) => key in target ? target[key] : () => stub });
const panelSettings = await Bun.file(settingsPath).json();
const MODELS = [
  { id: "m1", provider: "pa", identity: { class: "pa", family: "one" } },
  { id: "m1", provider: "pb", identity: { class: "pb", family: "two" } },
  { id: "m2", provider: "pb", identity: { class: "pb", family: "two" } },
  { id: "m3", provider: "pa", identity: { class: "pa", family: "one" } },
];
const api: any = { cwd: process.cwd(), zod, pi: panel };
const settings = settingsModule.Settings.isolated({ panel: panelSettings, modelRoles: { plan: "pa/m1" } });
const tool = await mod.default(api);
try {
  const result = await tool.execute(
    "tc",
    { role, mode: "project-plan", synthesizer: "pa/m1" },
    undefined,
    { settings, modelRegistry: { getAvailable: () => MODELS, hasConfiguredAuth: () => true } },
  );
  console.log(JSON.stringify({ ok: true, roster: result.details, tool_name: tool.name }));
} catch (error: any) {
  console.log(JSON.stringify({ ok: false, error: String(error?.message ?? error), tool_name: tool.name }));
}
"""

PANEL_SETTINGS = {
    "roles": {
        "dup": {
            "strategy": "independent", "minFamilies": 2,
            "members": [{"model": "pa/m1"}, {"model": "pb/m1"}],
        },
        "hidden": {
            "strategy": "independent", "minFamilies": 2,
            "members": [
                {"model": "pz/m3", "fallbacks": ["pa/m3"]},
                {"model": "pb/m2"},
            ],
        },
        "bare": {
            "strategy": "independent", "minFamilies": 2,
            "members": [{"model": "m2"}, {"model": "m3"}],
        },
        "collide": {
            "strategy": "independent", "minFamilies": 2,
            "members": [{"model": "pb/m1"}, {"model": "pb/m2"}],
        },
        "none": {
            "strategy": "independent", "minFamilies": 2,
            "members": [{"model": "pa/m1"}, {"model": "nope/nothing"}],
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
            check("duplicate bare ids stay provider-qualified",
                  [seat["resolved_model"] for seat in seats] == ["pa/m1", "pb/m1"], seats)
            check("declared quorum labels come from OMP resolved families",
                  [seat["declared_family"] for seat in seats] == ["pa", "pb"], seats)
            check("OMP family floor is carried into FV orchestration",
                  dup["roster"]["min_families"] == 2, dup["roster"])
            check("OMP lineup hash names the frozen FV panel",
                  isinstance(dup["roster"].get("lineup_hash"), str)
                  and len(dup["roster"]["lineup_hash"]) == 71, dup["roster"])
            check("synthesizer resolves through the OMP model selector",
                  dup["roster"]["synthesizer"]["resolved_model"] == "pa/m1",
                  dup["roster"]["synthesizer"])

        hidden = run("hidden")
        check("OMP role candidates fall through in priority order",
              hidden.get("ok")
              and hidden["roster"]["seats"][0]["requested_selector"] == "pa/m3",
              hidden)

        bare = run("bare")
        check("bare OMP model ids resolve to provider-qualified selectors",
              bare.get("ok")
              and [seat["resolved_model"] for seat in bare["roster"]["seats"]] == ["pb/m2", "pa/m3"],
              bare)

        collide = run("collide")
        check("OMP rejects a panel role whose served families collide",
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
