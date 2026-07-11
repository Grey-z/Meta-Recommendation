"""Normalize place-provider results into solver-neutral planning candidates."""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import replace
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from langgraph_metarec.itinerary_contracts import (
    AvailabilityWindow,
    CostEstimate,
    DurationEstimate,
    ItineraryPlanningRequest,
    PlanningCandidate,
)

_DAY_INDEX = {"Mo": 0, "Tu": 1, "We": 2, "Th": 3, "Fr": 4, "Sa": 5, "Su": 6}
_TIME_RANGE_RE = re.compile(r"^(\d{1,2}):(\d{2})-(\d{1,2}):(\d{2})$")
_PRICE_RE = re.compile(r"(?:(SGD|USD|EUR|GBP|AUD|CAD|CNY|JPY)\s*)?([0-9]+(?:\.[0-9]+)?)", re.IGNORECASE)

# Small, auditable overrides for compound POIs where category defaults are
# materially wrong. Detailed provider APIs can replace these facts later.
_CANONICAL_POIS: Dict[str, Dict[str, Any]] = {
    "universal studios singapore": {
        "duration": (420, 510, 600),
        "meal_coverage": ("lunch",),
    },
}

_DURATION_RULES: Dict[str, Tuple[int, int, int, float]] = {
    "photo_stop": (30, 45, 60, 0.65),
    "museum": (90, 120, 180, 0.7),
    "gallery": (60, 90, 150, 0.65),
    "park": (90, 150, 240, 0.55),
    "zoo": (240, 360, 480, 0.7),
    "aquarium": (120, 180, 240, 0.7),
    "theme_park": (300, 420, 600, 0.7),
    "restaurant": (60, 75, 90, 0.75),
    "hotel": (0, 0, 0, 0.9),
    "generic": (45, 90, 150, 0.35),
}


def _minutes(hour: str, minute: str) -> Optional[int]:
    value = int(hour) * 60 + int(minute)
    return value if 0 <= value <= 24 * 60 else None


def parse_opening_hours(value: Any, service_date: str) -> Tuple[AvailabilityWindow, ...]:
    """Parse a deliberately small, explicit subset of OSM opening_hours."""
    text = str(value or "").strip()
    if not text:
        return ()
    if text == "24/7":
        return (AvailabilityWindow(day_index=0, start_min=0, end_min=24 * 60),)
    try:
        weekday = dt.date.fromisoformat(service_date).weekday()
    except ValueError:
        return ()
    windows: List[AvailabilityWindow] = []
    for clause in text.split(";"):
        parts = clause.strip().split()
        if len(parts) != 2:
            continue
        day_text, time_text = parts
        days: set[int] = set()
        for token in day_text.split(","):
            if "-" in token:
                start_day, end_day = token.split("-", 1)
                if start_day not in _DAY_INDEX or end_day not in _DAY_INDEX:
                    continue
                current = _DAY_INDEX[start_day]
                while True:
                    days.add(current)
                    if current == _DAY_INDEX[end_day]:
                        break
                    current = (current + 1) % 7
            elif token in _DAY_INDEX:
                days.add(_DAY_INDEX[token])
        if weekday not in days:
            continue
        for time_range in time_text.split(","):
            match = _TIME_RANGE_RE.match(time_range)
            if not match:
                continue
            start = _minutes(match.group(1), match.group(2))
            end = _minutes(match.group(3), match.group(4))
            if start is not None and end is not None and start < end:
                windows.append(AvailabilityWindow(day_index=0, start_min=start, end_min=end))
    return tuple(sorted(windows, key=lambda item: (item.start_min, item.end_min)))


def _geo(candidate: Dict[str, Any]) -> Optional[Tuple[float, float]]:
    gps = candidate.get("gps_coordinates")
    raw = candidate.get("raw") if isinstance(candidate.get("raw"), dict) else {}
    if not isinstance(gps, dict):
        gps = raw.get("gps_coordinates")
    try:
        return float(gps["latitude"]), float(gps["longitude"])
    except (TypeError, KeyError, ValueError):
        return None


def _tags(candidate: Dict[str, Any]) -> Tuple[str, ...]:
    raw = candidate.get("raw") if isinstance(candidate.get("raw"), dict) else {}
    raw_tags = raw.get("tags") if isinstance(raw.get("tags"), dict) else {}
    values: List[str] = []
    for value in candidate.get("tags") or []:
        values.append(str(value).strip().lower())
    for key, value in raw_tags.items():
        values.extend((str(key).strip().lower(), str(value).strip().lower()))
    return tuple(sorted({value for value in values if value}))


def _duration(candidate: Dict[str, Any], domain: str, tags: Sequence[str]) -> Tuple[DurationEstimate, Tuple[str, ...]]:
    title_key = re.sub(r"\s+", " ", str(candidate.get("title") or candidate.get("name") or "").strip().lower())
    canonical = _CANONICAL_POIS.get(title_key)
    if canonical:
        low, preferred, high = canonical["duration"]
        return DurationEstimate(low, preferred, high, "registry", 0.95), tuple(canonical.get("meal_coverage") or ())
    for key in ("duration_min", "recommended_duration_min"):
        try:
            explicit = int(candidate.get(key))
        except (TypeError, ValueError):
            continue
        if 0 <= explicit <= 12 * 60:
            return DurationEstimate(explicit, explicit, explicit, "provider", 0.95), ()
    joined = " ".join(tags)
    if domain == "restaurant":
        rule = "restaurant"
    elif domain == "hotel":
        rule = "hotel"
    elif "theme_park" in joined or "theme-park" in joined:
        rule = "theme_park"
    elif "aquarium" in joined:
        rule = "aquarium"
    elif "zoo" in joined:
        rule = "zoo"
    elif "museum" in joined:
        rule = "museum"
    elif "gallery" in joined:
        rule = "gallery"
    elif any(token in joined for token in ("park", "nature", "garden")):
        rule = "park"
    elif any(token in joined for token in ("landmark", "viewpoint", "artwork", "memorial")):
        rule = "photo_stop"
    else:
        rule = "generic"
    low, preferred, high, confidence = _DURATION_RULES[rule]
    return DurationEstimate(low, preferred, high, "rule", confidence), ()


def _cost(candidate: Dict[str, Any], domain: str) -> CostEstimate:
    currency = str(candidate.get("price_currency") or "").strip().upper() or None
    for key in ("price_per_person_sgd", "admission_price", "price_amount"):
        try:
            amount = float(candidate.get(key))
        except (TypeError, ValueError):
            continue
        if amount >= 0:
            if key == "price_per_person_sgd":
                currency = "SGD"
            component = "meal" if domain == "restaurant" else "admission"
            return CostEstimate(amount, amount, currency, (component,), "provider", 0.9)
    price_text = str(candidate.get("price") or "").strip()
    match = _PRICE_RE.search(price_text)
    if match:
        amount = float(match.group(2))
        currency = (match.group(1) or currency or "").upper() or None
        component = "meal" if domain == "restaurant" else "admission"
        return CostEstimate(amount, amount, currency, (component,), "provider", 0.75)
    return CostEstimate(None, None, None, (), "unknown", 0.0)


def _client_item(candidate: Dict[str, Any], domain: str, geo: Tuple[float, float]) -> Dict[str, Any]:
    return {
        "id": str(candidate.get("id") or ""),
        "domain": domain,
        "title": candidate.get("title") or candidate.get("name") or "Untitled",
        "subtitle": candidate.get("subtitle") or candidate.get("address"),
        "rating": candidate.get("rating"),
        "price": candidate.get("price"),
        "price_per_person_sgd": candidate.get("price_per_person_sgd"),
        "image_url": candidate.get("image_url"),
        "url": candidate.get("url") or candidate.get("reference"),
        "source": candidate.get("source"),
        "lat": geo[0],
        "lng": geo[1],
    }


def normalize_candidates(
    candidates: Iterable[Dict[str, Any]],
    request: ItineraryPlanningRequest,
) -> List[PlanningCandidate]:
    normalized: List[PlanningCandidate] = []
    seen: set[Tuple[Any, ...]] = set()
    raw_candidates = [candidate for candidate in candidates if isinstance(candidate, dict)]
    for rank, candidate in enumerate(raw_candidates):
        geo = _geo(candidate)
        if geo is None:
            continue
        domain = str(candidate.get("domain") or ("restaurant" if candidate.get("name") else "attraction")).lower()
        if domain not in {"attraction", "restaurant", "hotel"}:
            continue
        candidate_id = str(candidate.get("id") or "").strip()
        title = str(candidate.get("title") or candidate.get("name") or "Untitled").strip()
        dedupe_key = (candidate_id,) if candidate_id else (title.lower(), round(geo[0], 5), round(geo[1], 5))
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        tags = _tags(candidate)
        duration, meal_coverage = _duration(candidate, domain, tags)
        raw = candidate.get("raw") if isinstance(candidate.get("raw"), dict) else {}
        raw_tags = raw.get("tags") if isinstance(raw.get("tags"), dict) else {}
        opening_hours = candidate.get("opening_hours") or raw.get("opening_hours") or raw_tags.get("opening_hours")
        windows = parse_opening_hours(opening_hours, request.days[0].date)
        normalized.append(PlanningCandidate(
            id=candidate_id or f"geo:{geo[0]:.5f},{geo[1]:.5f}:{title.lower()}",
            domain=domain,
            title=title,
            latitude=geo[0],
            longitude=geo[1],
            duration=duration,
            cost=_cost(candidate, domain),
            availability_windows=windows,
            availability_known=bool(opening_hours and windows),
            meal_coverage=meal_coverage,
            tags=tags,
            provider_relevance=max(0.0, 1.0 - rank / max(len(raw_candidates), 1)),
            rating=float(candidate["rating"]) if candidate.get("rating") is not None else None,
            source=str(candidate.get("source") or "") or None,
            item=_client_item(candidate, domain, geo),
        ))
    return normalized


def duration_enrichment_input(candidates: Sequence[PlanningCandidate]) -> List[Dict[str, Any]]:
    return [
        {"id": item.id, "title": item.title, "domain": item.domain, "tags": list(item.tags)}
        for item in candidates
        if item.duration.confidence < 0.6
    ]


def apply_duration_enrichment(
    candidates: Sequence[PlanningCandidate],
    payload: Any,
) -> List[PlanningCandidate]:
    rows = payload.get("durations") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return list(candidates)
    allowed = {candidate.id for candidate in candidates if candidate.duration.confidence < 0.6}
    replacements: Dict[str, DurationEstimate] = {}
    for row in rows:
        if not isinstance(row, dict) or str(row.get("id") or "") not in allowed:
            continue
        try:
            low = int(row["min"])
            preferred = int(row["preferred"])
            high = int(row["max"])
            confidence = max(0.0, min(1.0, float(row.get("confidence", 0.5))))
        except (KeyError, TypeError, ValueError):
            continue
        if 15 <= low <= preferred <= high <= 12 * 60:
            replacements[str(row["id"])] = DurationEstimate(low, preferred, high, "llm", confidence)
    return [replace(candidate, duration=replacements.get(candidate.id, candidate.duration)) for candidate in candidates]
