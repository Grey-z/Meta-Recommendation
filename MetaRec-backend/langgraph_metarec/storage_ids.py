from __future__ import annotations

from typing import Any


SAFE_ID_MAX_LENGTH = 160


def safe_id(value: Any, fallback: str = "default", max_length: int = SAFE_ID_MAX_LENGTH) -> str:
    """Return a filesystem-safe identifier component.

    This helper intentionally allows only alphanumeric characters, dash,
    and underscore so IDs can be used as single path components without
    carrying path traversal semantics.
    """
    raw = str(value or fallback).strip() or fallback
    sanitized = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in raw)
    sanitized = sanitized[:max(1, max_length)]
    return sanitized or fallback
