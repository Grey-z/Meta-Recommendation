"""Normalize place-provider results into solver-neutral planning candidates."""
from __future__ import annotations

import datetime as dt
import math
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
from langgraph_metarec.itinerary_policy import STRICT_ROLE_ENUM, role_allowed, role_from_tokens

_DAY_INDEX = {"Mo": 0, "Tu": 1, "We": 2, "Th": 3, "Fr": 4, "Sa": 5, "Su": 6}
_TIME_RANGE_RE = re.compile(r"^(\d{1,2}):(\d{2})-(\d{1,2}):(\d{2})$")
_PRICE_RE = re.compile(r"(?:(SGD|USD|EUR|GBP|AUD|CAD|CNY|JPY)\s*)?([0-9]+(?:\.[0-9]+)?)", re.IGNORECASE)

# Small, auditable overrides for compound POIs where category defaults are
# materially wrong. Detailed provider APIs can replace these facts later.
_CANONICAL_POIS: Dict[str, Dict[str, Any]] = {
    "universal studios singapore": {
        "duration": (420, 510, 600),
        "meal_coverage": ("lunch",),
        "compound": True,
    },
}

_COMPOUND_TAGS = {"theme park", "theme_park", "zoo", "aquarium", "water park", "resort"}
_PARENT_KEYS = ("parent_id", "parent_place_id", "located_in_id", "contained_in_id")


def _raw(candidate: Dict[str, Any]) -> Dict[str, Any]:
    return candidate.get("raw") if isinstance(candidate.get("raw"), dict) else {}


def _explicit_access(candidate: Dict[str, Any]) -> str:
    raw = _raw(candidate)
    value = str(candidate.get("access") or raw.get("access") or "").strip().lower()
    if candidate.get("public_access") is True or raw.get("public_access") is True:
        return "independent"
    if value in {"public", "yes", "independent"}:
        return "independent"
    if value in {"gated", "ticketed", "customers", "private"}:
        return "gated"
    return "unknown"


def _provider_parent_id(candidate: Dict[str, Any]) -> Optional[str]:
    raw = _raw(candidate)
    for key in _PARENT_KEYS:
        value = candidate.get(key, raw.get(key))
        if str(value or "").strip():
            return str(value).strip()
    return None

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


def parse_opening_hours(
    value: Any,
    service_date: str,
    *,
    day_index: int = 0,
) -> Tuple[AvailabilityWindow, ...]:
    """Parse a deliberately small, explicit subset of OSM opening_hours."""
    text = str(value or "").strip()
    if not text:
        return ()
    if text == "24/7":
        return (AvailabilityWindow(day_index=day_index, start_min=0, end_min=24 * 60),)
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
                windows.append(AvailabilityWindow(day_index=day_index, start_min=start, end_min=end))
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
    for key in ("type", "tourism", "osm_category", "osm_tag", "amenity", "shop", "leisure"):
        value = candidate.get(key, raw.get(key))
        if value not in (None, ""):
            values.append(str(value).strip().lower())
    place_types = candidate.get("types", raw.get("types"))
    if isinstance(place_types, list):
        values.extend(str(value).strip().lower() for value in place_types)
    return tuple(sorted({value for value in values if value}))


def _record_rejection(diagnostics: Optional[Dict[str, Any]], code: str) -> None:
    if diagnostics is None:
        return
    counts = diagnostics.setdefault("rejection_counts", {})
    counts[code] = int(counts.get(code) or 0) + 1


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
    raw = _raw(candidate)
    currency = str(candidate.get("price_currency") or raw.get("price_currency") or raw.get("currency") or "").strip().upper() or None
    if domain == "hotel":
        for key in ("nightly_price", "price_per_night", "price_amount"):
            try:
                amount = float(candidate.get(key, raw.get(key)))
            except (TypeError, ValueError):
                continue
            if amount >= 0:
                return CostEstimate(
                    amount, amount, currency, ("lodging_nightly_per_room",), "provider", 0.9
                )
        price_text = str(candidate.get("price") or raw.get("price") or "").strip()
        if price_text:
            if "S$" in price_text.upper():
                currency = "SGD"
            elif "US$" in price_text.upper():
                currency = "USD"
            amounts = [float(match.group(2)) for match in _PRICE_RE.finditer(price_text)]
            if amounts:
                explicit_currency = next(
                    (match.group(1) for match in _PRICE_RE.finditer(price_text) if match.group(1)),
                    None,
                )
                currency = str(explicit_currency or currency or "").upper() or None
                return CostEstimate(
                    min(amounts), max(amounts), currency,
                    ("lodging_nightly_per_room",), "provider", 0.75,
                )
        return CostEstimate(None, None, currency, ("lodging_nightly_per_room",), "unknown", 0.0)
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
    price_text = str(candidate.get("price") or raw.get("price") or "").strip()
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
        "reviews_count": candidate.get("reviews_count") or candidate.get("reviews"),
        "price": candidate.get("price") or _raw(candidate).get("price"),
        "price_per_person_sgd": candidate.get("price_per_person_sgd"),
        "image_url": candidate.get("image_url"),
        "url": candidate.get("url") or candidate.get("reference"),
        "source": candidate.get("source"),
        "lat": geo[0],
        "lng": geo[1],
    }


def _distance_m(left: PlanningCandidate, right: PlanningCandidate) -> float:
    lat_scale = 111_320.0
    lng_scale = lat_scale * math.cos(math.radians((left.latitude + right.latitude) / 2))
    return math.hypot(
        (left.latitude - right.latitude) * lat_scale,
        (left.longitude - right.longitude) * lng_scale,
    )


def _likely_containment_candidates(
    candidates: Sequence[PlanningCandidate],
) -> Dict[str, Tuple[str, ...]]:
    compounds = [candidate for candidate in candidates if candidate.is_compound]
    likely: Dict[str, Tuple[str, ...]] = {}
    for candidate in candidates:
        if candidate.is_compound:
            continue
        if candidate.parent_id:
            likely[candidate.id] = (candidate.parent_id,)
            continue
        possible = []
        child_address = str(candidate.item.get("subtitle") or "").strip().lower()
        for parent in compounds:
            parent_address = str(parent.item.get("subtitle") or "").strip().lower()
            same_address = bool(child_address and parent_address and (
                child_address in parent_address or parent_address in child_address
            ))
            if same_address or _distance_m(candidate, parent) <= 120:
                possible.append(parent.id)
        if possible:
            likely[candidate.id] = tuple(sorted(possible))
    return likely


def normalize_candidates(
    candidates: Iterable[Dict[str, Any]],
    request: ItineraryPlanningRequest,
    diagnostics: Optional[Dict[str, Any]] = None,
) -> List[PlanningCandidate]:
    normalized: List[PlanningCandidate] = []
    seen: set[Tuple[Any, ...]] = set()
    raw_candidates = [candidate for candidate in candidates if isinstance(candidate, dict)]
    for rank, candidate in enumerate(raw_candidates):
        geo = _geo(candidate)
        if geo is None:
            _record_rejection(diagnostics, "missing_coordinates")
            continue
        domain = str(candidate.get("domain") or ("restaurant" if candidate.get("name") else "attraction")).lower()
        if domain not in {"attraction", "restaurant", "hotel"}:
            _record_rejection(diagnostics, "unsupported_domain")
            continue
        candidate_id = str(candidate.get("id") or "").strip()
        title = str(candidate.get("title") or candidate.get("name") or "Untitled").strip()
        title_key = re.sub(r"\W+", " ", title.lower()).strip()
        dedupe_key = (candidate_id,) if candidate_id else (title_key, round(geo[0], 5), round(geo[1], 5))
        physical_duplicate = any(
            key[0] == title_key
            and abs(float(key[1]) - geo[0]) <= 0.00075
            and abs(float(key[2]) - geo[1]) <= 0.00075
            for key in seen if len(key) == 3
        )
        if dedupe_key in seen or physical_duplicate:
            _record_rejection(diagnostics, "duplicate_physical_poi")
            continue
        seen.add(dedupe_key)
        seen.add((title_key, geo[0], geo[1]))
        tags = _tags(candidate)
        role = role_from_tokens(tags)
        if role == "unknown" and domain == "restaurant":
            role = "food"
        elif role == "unknown" and domain == "hotel":
            role = "lodging"
        if role != "unknown" and not role_allowed(domain, role):
            _record_rejection(diagnostics, f"domain_mismatch:{role}")
            continue
        duration, meal_coverage = _duration(candidate, domain, tags)
        raw = _raw(candidate)
        title_key = re.sub(r"\s+", " ", title.lower())
        canonical = _CANONICAL_POIS.get(title_key) or {}
        is_compound = bool(canonical.get("compound")) or bool(
            {tag.replace("-", " ") for tag in tags} & {tag.replace("-", " ") for tag in _COMPOUND_TAGS}
        )
        parent_id = _provider_parent_id(candidate)
        explicit_access = _explicit_access(candidate)
        access = explicit_access if parent_id else "independent"
        containment_source = (
            "provider_access" if explicit_access != "unknown"
            else ("provider_parent" if parent_id else "none")
        )
        raw_tags = raw.get("tags") if isinstance(raw.get("tags"), dict) else {}
        opening_hours = candidate.get("opening_hours") or raw.get("opening_hours") or raw_tags.get("opening_hours")
        windows = tuple(
            window
            for day in request.days
            for window in parse_opening_hours(
                opening_hours,
                day.date,
                day_index=day.day_index,
            )
        )
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
            role=role,
            role_source="provider" if role != "unknown" else "unknown",
            is_compound=is_compound,
            parent_id=parent_id,
            access=access,
            containment_source=containment_source,
            item={
                **_client_item(candidate, domain, geo),
                "role": role,
                "is_compound": is_compound,
                "parent_id": parent_id,
                "access": access,
            },
        ))
    return normalized


def role_enrichment_input(candidates: Sequence[PlanningCandidate]) -> List[Dict[str, Any]]:
    return [
        {"id": item.id, "title": item.title, "domain": item.domain, "tags": list(item.tags)}
        for item in candidates if item.role == "unknown"
    ]


def apply_role_enrichment(
    candidates: Sequence[PlanningCandidate],
    payload: Any,
    diagnostics: Optional[Dict[str, Any]] = None,
) -> List[PlanningCandidate]:
    rows = payload.get("roles") if isinstance(payload, dict) else None
    rows = rows if isinstance(rows, list) else []
    allowed_ids = {item.id for item in candidates if item.role == "unknown"}
    replacements: Dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        item_id = str(row.get("id") or "")
        role = str(row.get("role") or "").lower()
        if item_id in allowed_ids and role in STRICT_ROLE_ENUM and role != "unknown":
            replacements[item_id] = role
    resolved: List[PlanningCandidate] = []
    for candidate in candidates:
        role = replacements.get(candidate.id, candidate.role)
        if role == "unknown":
            _record_rejection(diagnostics, "unknown_role")
            continue
        if not role_allowed(candidate.domain, role):
            _record_rejection(diagnostics, f"domain_mismatch:{role}")
            continue
        resolved.append(replace(
            candidate,
            role=role,
            role_source="llm" if candidate.id in replacements else candidate.role_source,
            item={**candidate.item, "role": role},
        ))
    return resolved


def containment_enrichment_input(candidates: Sequence[PlanningCandidate]) -> List[Dict[str, Any]]:
    likely = _likely_containment_candidates(candidates)
    return [
        {
            "id": candidate.id,
            "title": candidate.title,
            "role": candidate.role,
            "possible_parent_ids": list(likely[candidate.id]),
        }
        for candidate in candidates
        if candidate.id in likely and candidate.containment_source != "provider_access"
    ]


def apply_containment_enrichment(
    candidates: Sequence[PlanningCandidate],
    payload: Any,
    diagnostics: Optional[Dict[str, Any]] = None,
) -> List[PlanningCandidate]:
    likely = _likely_containment_candidates(candidates)
    rows = payload.get("relations") if isinstance(payload, dict) else None
    rows = rows if isinstance(rows, list) else []
    decisions: Dict[str, Tuple[Optional[str], str]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        item_id = str(row.get("id") or "")
        parent_id = str(row.get("parent_id") or "") or None
        access = str(row.get("access") or "").lower()
        if item_id not in likely or access not in {"gated", "independent", "unknown"}:
            continue
        if access == "gated" and parent_id not in likely[item_id]:
            continue
        decisions[item_id] = (parent_id, access)
    candidate_ids = {candidate.id for candidate in candidates}
    resolved: List[PlanningCandidate] = []
    for candidate in candidates:
        if candidate.parent_id and candidate.parent_id not in candidate_ids:
            _record_rejection(diagnostics, "unknown_parent")
            continue
        if candidate.id not in likely:
            resolved.append(candidate)
            continue
        default_access = candidate.access if candidate.containment_source == "provider_access" else "unknown"
        parent_id, access = decisions.get(candidate.id, (candidate.parent_id, default_access))
        if access == "unknown":
            _record_rejection(diagnostics, "unknown_access")
            continue
        if access == "gated" and parent_id not in candidate_ids:
            _record_rejection(diagnostics, "gated_child_without_parent")
            continue
        resolved.append(replace(
            candidate,
            parent_id=parent_id if access == "gated" else None,
            access=access,
            containment_source="llm" if candidate.id in decisions else candidate.containment_source,
            item={
                **candidate.item,
                "parent_id": parent_id if access == "gated" else None,
                "access": access,
            },
        ))
    return resolved


def build_itinerary_gather_query(request: ItineraryPlanningRequest, domain: str) -> str:
    location = request.location.resolved_name or request.location.query
    must_visit = [str(value).strip() for value in request.hard_constraints.get("must_visit") or [] if str(value).strip()]
    if domain == "restaurant":
        meal_preferences = [
            *(request.hard_constraints.get("meal_obligations") or []),
            *(request.soft_preferences.get("suggested_meals") or []),
        ]
        meals = ", ".join(
            str(value.get("meal") if isinstance(value, dict) else value)
            for value in meal_preferences
        )
        return f"Restaurants for {meals or 'a meal'} in {location}".strip()
    if domain == "hotel" and request.lodging is not None:
        lodging = request.lodging
        return (
            f"Hotels in {location} for {lodging.travelers} travelers, {lodging.rooms} rooms, "
            f"check-in {lodging.check_in_date}, check-out {lodging.check_out_date}"
        )
    style = str(request.soft_preferences.get("style") or "sightseeing").replace("_", " ")
    requested = [str(value).replace("-", " ") for value in request.soft_preferences.get("attraction_types") or []]
    interests = [str(value).strip() for value in request.soft_preferences.get("interest_terms") or [] if str(value).strip()]
    themes = list(dict.fromkeys([*requested, *interests]))
    parts = [f"{style} attractions", *themes, f"in {location}"]
    if must_visit:
        parts.append("including " + ", ".join(must_visit))
    return " ".join(part for part in parts if part).strip()


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
