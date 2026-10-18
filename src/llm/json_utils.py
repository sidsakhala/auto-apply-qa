"""Extract a JSON object from a model response."""

from __future__ import annotations

import json
import re


def parse_json_object(text: str) -> dict:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("Model response did not contain a JSON object") from None
        data = json.loads(raw[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("Model response JSON must be an object")
    return data
