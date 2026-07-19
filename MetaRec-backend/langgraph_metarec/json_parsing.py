"""Small helpers for extracting schema-typed JSON from LLM text responses."""
from __future__ import annotations

import json
import re
from typing import Any, Type

_FENCED_JSON_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.IGNORECASE | re.DOTALL)


def loads_first_json_value(text: str, expected_type: Type[Any]) -> Any:
    """Return the first complete JSON value of ``expected_type`` in ``text``.

    Bare JSON is preferred, followed by fenced blocks and then values embedded
    in prose. ``JSONDecoder.raw_decode`` avoids greedy spans across two values.
    """
    if not isinstance(text, str):
        raise TypeError("LLM JSON content must be a string")
    stripped = text.strip()
    candidates = [stripped, *[match.group(1).strip() for match in _FENCED_JSON_RE.finditer(stripped)]]
    decoder = json.JSONDecoder()
    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except (TypeError, ValueError):
            value = None
        if isinstance(value, expected_type):
            return value
        for index, character in enumerate(candidate):
            if character not in "[{":
                continue
            try:
                value, _end = decoder.raw_decode(candidate, index)
            except ValueError:
                continue
            if isinstance(value, expected_type):
                return value
    raise ValueError(f"No complete JSON {expected_type.__name__} found")


def loads_first_json_object(text: str) -> dict[str, Any]:
    return loads_first_json_value(text, dict)


def loads_first_json_array(text: str) -> list[Any]:
    return loads_first_json_value(text, list)
