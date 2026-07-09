"""Compact raw tool-search outputs before they reach the summarizer LLM and the
persisted execution blobs.

The recommendation pipeline feeds the three search tools' raw results into the
summarizer LLM (``rerank_and_summarize``) and *also* stores them in
``metadata.executions``, which is persisted to Postgres and shipped to the
frontend with the result. The dominant cost is a handful of high-volume
free-text fields — above all Google Maps ``user_reviews`` (full review text for
every place). Bounding those collapses the summarizer's input tokens (faster,
cheaper inference) and shrinks the stored/transferred blob, with no loss of
ranking signal (rating, price, category, location, opening hours, a snippet and
recency are all retained).

Design principle: **bound volume, do not drop fields.** Every metadata key the
tools return is preserved (opening hours, coordinates, contact, price,
photo/review links, ...), so current and future features can still rely on it.
Only the size of high-cardinality nested structures and long strings is capped.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple


def _int_env(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


# Max candidates kept per tool. The live adapters already request ~10; this is a
# defensive ceiling so an over-eager provider response cannot blow up the blob.
MAX_ITEMS_PER_TOOL = _int_env("METAREC_TOOL_MAX_ITEMS", 10)
# Default caps for bounded fields: nested list length and string length.
_LIST_CAP = _int_env("METAREC_TOOL_LIST_CAP", 3)
_TEXT_CAP = _int_env("METAREC_TOOL_TEXT_CAP", 240)


# Per-tool ``field -> (max_list, max_chars)`` for the high-volume fields only.
# Anything NOT listed here is preserved verbatim (that is how opening hours,
# coordinates, links, price, etc. survive untouched). ``max_list`` caps nested
# list lengths; ``max_chars`` truncates strings (both apply recursively).
_FIELD_CAPS: Dict[str, Dict[str, Tuple[int, int]]] = {
    "gmap.search": {
        "user_reviews": (_LIST_CAP, _TEXT_CAP),  # full review text — the big one
        "extensions": (12, 160),                 # nested feature/amenity lists
    },
    "gmap.hotel.search": {
        "user_reviews": (_LIST_CAP, _TEXT_CAP),
        "extensions": (12, 160),
    },
    "yelp.search": {
        "snippet": (1, 320),                     # featured review / review summary
        "highlights": (12, 120),
    },
    "xhs.search": {
        "desc": (1, 320),                        # note body
        "title": (1, 200),
    },
    "hardcover.book.search": {
        "description": (1, 480),
    },
    "tmdb.movie.search": {
        "overview": (1, 480),
    },
    "tmdb.movie.discover": {
        "overview": (1, 480),
    },
    "tmdb.tv.search": {
        "overview": (1, 480),
    },
    "tmdb.tv.discover": {
        "overview": (1, 480),
    },
}


def _truncate(text: str, max_chars: int) -> str:
    text = text.strip()
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "…"


def _bound(value: Any, *, max_list: int, max_chars: int) -> Any:
    """Recursively cap list lengths and truncate strings, preserving shape."""
    if isinstance(value, str):
        return _truncate(value, max_chars)
    if isinstance(value, list):
        return [_bound(item, max_list=max_list, max_chars=max_chars) for item in value[:max_list]]
    if isinstance(value, dict):
        return {key: _bound(item, max_list=max_list, max_chars=max_chars) for key, item in value.items()}
    return value


def _compact_item(field_caps: Dict[str, Tuple[int, int]], item: Dict[str, Any]) -> Dict[str, Any]:
    compacted: Dict[str, Any] = {}
    for key, value in item.items():
        cap = field_caps.get(key)
        if cap is None:
            compacted[key] = value  # preserved verbatim (structured metadata)
        else:
            max_list, max_chars = cap
            compacted[key] = _bound(value, max_list=max_list, max_chars=max_chars)
    return compacted


def compact_tool_output(tool: str, output: Any, *, max_items: Optional[int] = None) -> Any:
    """Return a size-bounded copy of a tool's search output.

    Non-list outputs (e.g. ``None`` from an upstream error) are returned
    unchanged so the registry's dispatch success/failure semantics
    (``success = output is not None``) are preserved.
    """
    if not isinstance(output, list):
        return output
    cap = MAX_ITEMS_PER_TOOL if max_items is None else max_items
    field_caps = _FIELD_CAPS.get(tool, {})
    compacted: List[Any] = []
    for item in output[:cap]:
        compacted.append(_compact_item(field_caps, item) if isinstance(item, dict) else item)
    return compacted
