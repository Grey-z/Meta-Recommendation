"""Deterministic resolution of user-supplied itinerary anchors."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional, Tuple


def _normalized(value: Any) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(value or "").lower()))


def _minor_token_variation(left: str, right: str) -> bool:
    if left == right:
        return True
    if min(len(left), len(right)) < 5 or abs(len(left) - len(right)) > 2:
        return False
    previous = list(range(len(right) + 1))
    for left_index, left_char in enumerate(left, start=1):
        current = [left_index]
        for right_index, right_char in enumerate(right, start=1):
            current.append(min(
                current[-1] + 1,
                previous[right_index] + 1,
                previous[right_index - 1] + int(left_char != right_char),
            ))
        previous = current
    return previous[-1] <= 2


def _coordinates(item: Dict[str, Any]) -> Optional[Tuple[float, float]]:
    gps = item.get("gps_coordinates")
    raw = item.get("raw") if isinstance(item.get("raw"), dict) else {}
    if not isinstance(gps, dict):
        gps = raw.get("gps_coordinates")
    try:
        return float(gps["latitude"]), float(gps["longitude"])
    except (KeyError, TypeError, ValueError):
        return None


def _resolved_item(item: Dict[str, Any], query: str) -> Optional[Dict[str, Any]]:
    coordinates = _coordinates(item)
    if coordinates is None:
        return None
    title = str(item.get("title") or item.get("name") or "").strip()
    if not title:
        return None
    return {
        "query": query,
        "resolved_name": title,
        "address": str(item.get("subtitle") or item.get("address") or "").strip() or None,
        "latitude": coordinates[0],
        "longitude": coordinates[1],
        "provider_id": str(item.get("id") or "").strip() or None,
        "source": str(item.get("source") or "provider"),
    }


@dataclass(frozen=True)
class AnchorResolution:
    status: str
    match: Optional[Dict[str, Any]] = None
    options: Tuple[Dict[str, Any], ...] = ()


def resolve_anchor_candidates(
    query: str,
    destination: str,
    candidates: Iterable[Dict[str, Any]],
    *,
    provider_id: Optional[str] = None,
) -> AnchorResolution:
    """Resolve a unique anchor without guessing between similarly named places."""
    query_key = _normalized(query)
    destination_tokens = set(_normalized(destination).split())
    ranked = []
    for rank, item in enumerate(candidate for candidate in candidates if isinstance(candidate, dict)):
        resolved = _resolved_item(item, query)
        if resolved is None:
            continue
        title_key = _normalized(resolved["resolved_name"])
        address_key = _normalized(resolved.get("address"))
        candidate_id = str(resolved.get("provider_id") or "")
        if provider_id and candidate_id == str(provider_id):
            score = 2.0
        elif query_key and title_key == query_key:
            score = 1.0
        else:
            query_tokens = set(query_key.split())
            evidence_tokens = set(f"{title_key} {address_key}".split())
            matched_tokens = sum(
                any(
                    _minor_token_variation(token, evidence)
                    for evidence in evidence_tokens
                )
                for token in query_tokens
            )
            overlap = matched_tokens / max(len(query_tokens), 1)
            score = 0.65 * overlap
            if query_key and (query_key in title_key or title_key in query_key):
                score += 0.2
        if destination_tokens:
            evidence_tokens = set(f"{title_key} {address_key}".split())
            score += min(0.15, 0.05 * len(destination_tokens & evidence_tokens))
        ranked.append((score, rank, resolved))
    ranked.sort(key=lambda row: (-row[0], row[1], str(row[2].get("provider_id") or "")))
    if not ranked:
        return AnchorResolution("unresolved")
    best_score = ranked[0][0]
    plausible = [row for row in ranked if row[0] >= max(0.55, best_score - 0.12)]
    if best_score >= 0.85 and len(plausible) == 1:
        return AnchorResolution("resolved", match=ranked[0][2])
    options = tuple(row[2] for row in plausible[:4])
    if len(options) == 1 and best_score >= 0.7:
        return AnchorResolution("resolved", match=options[0])
    return AnchorResolution("ambiguous" if len(options) > 1 else "unresolved", options=options)
