"""Decode the FV panel resolver's OMP-owned roster result."""
from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any


def _is_roster(obj: Any) -> bool:
    return (isinstance(obj, Mapping) and isinstance(obj.get("seats"), list)
            and isinstance(obj.get("synthesizer"), Mapping))


def normalize_roster(result: Any) -> dict[str, Any]:
    """Coerce the custom-tool proxy result into the resolved roster dict."""
    if isinstance(result, str):
        result = json.loads(result)
    if _is_roster(result):
        return dict(result)
    if isinstance(result, Mapping):
        details = result.get("details")
        if _is_roster(details):
            return dict(details)
        text = result.get("text")
        if isinstance(text, str):
            try:
                parsed = json.loads(text)
            except (json.JSONDecodeError, ValueError):
                parsed = None
            if _is_roster(parsed):
                return dict(parsed)
        content = result.get("content")
        if isinstance(content, list):
            for item in content:
                if isinstance(item, Mapping) and isinstance(item.get("text"), str):
                    try:
                        parsed = json.loads(item["text"])
                    except (json.JSONDecodeError, ValueError):
                        continue
                    if _is_roster(parsed):
                        return dict(parsed)
    raise ValueError("resolver result does not contain a roster (seats + synthesizer)")
