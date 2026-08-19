"""Compatibility operations for itinerary payloads created before Planning IR.

New itinerary tasks must use ``itinerary_runtime`` and ``itinerary_solver``.
These helpers exist only so already-persisted fixed-slot results can still be
swapped or prompt-refined without a data migration.
"""
from __future__ import annotations

import copy
import inspect
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple, Union

from langgraph_metarec.eta import estimate_leg


_DWELL_MIN = {"attraction": 120, "restaurant": 90, "hotel": 0}
_DEFAULT_DWELL_MIN = 90
_MAX_ALTERNATES = 4

Estimator = Callable[..., Dict[str, Any]]
Resolver = Callable[..., Union[Dict[str, Any], Awaitable[Dict[str, Any]]]]


def _candidate_geo(candidate: Dict[str, Any]) -> Optional[Tuple[float, float]]:
    gps = candidate.get("gps_coordinates")
    if not isinstance(gps, dict):
        raw = candidate.get("raw")
        gps = raw.get("gps_coordinates") if isinstance(raw, dict) else None
    if not isinstance(gps, dict):
        return None
    try:
        return float(gps["latitude"]), float(gps["longitude"])
    except (KeyError, TypeError, ValueError):
        return None


def _lite_item(candidate: Dict[str, Any]) -> Dict[str, Any]:
    geo = _candidate_geo(candidate)
    item: Dict[str, Any] = {
        "id": candidate.get("id"),
        "title": candidate.get("title") or candidate.get("name") or "Untitled",
        "subtitle": candidate.get("subtitle") or candidate.get("address"),
        "rating": candidate.get("rating"),
        "price": candidate.get("price"),
        "image_url": candidate.get("image_url"),
        "url": candidate.get("url") or candidate.get("reference"),
        "domain": candidate.get("domain"),
        "source": candidate.get("source"),
        "lat": geo[0] if geo else None,
        "lng": geo[1] if geo else None,
    }
    raw = candidate.get("raw") if isinstance(candidate.get("raw"), dict) else {}
    tags = raw.get("tags") if isinstance(raw.get("tags"), dict) else {}
    opening_hours = candidate.get("opening_hours") or raw.get("opening_hours") or tags.get("opening_hours")
    if opening_hours:
        item["opening_hours"] = str(opening_hours)[:160]
    if isinstance(candidate.get("open_now"), bool):
        item["open_now"] = candidate["open_now"]
    try:
        price = float(candidate.get("price_per_person_sgd"))
    except (TypeError, ValueError):
        price = 0
    if price > 0:
        item["price_per_person_sgd"] = price
    return item


def _parse_hhmm(value: Any) -> Optional[int]:
    try:
        hour, minute = (int(part) for part in str(value).strip().split(":", 1))
    except (TypeError, ValueError, AttributeError):
        return None
    return hour * 60 + minute if 0 <= hour < 24 and 0 <= minute < 60 else None


def _format_hhmm(minutes: int) -> str:
    # No % 24: keep past-midnight minutes intact (see itinerary_runtime.fmt_hhmm).
    total = max(0, int(minutes))
    return f"{total // 60:02d}:{total % 60:02d}"


def _dwell(slot: Dict[str, Any]) -> int:
    try:
        explicit = int(slot.get("dwell_min"))
        if 0 <= explicit <= 12 * 60:
            return explicit
    except (TypeError, ValueError):
        pass
    return _DWELL_MIN.get(str(slot.get("domain") or "").lower(), _DEFAULT_DWELL_MIN)


def _stop_geo(slot: Dict[str, Any]) -> Optional[Tuple[float, float]]:
    chosen = slot.get("chosen")
    if not isinstance(chosen, dict):
        return None
    try:
        return float(chosen["lat"]), float(chosen["lng"])
    except (KeyError, TypeError, ValueError):
        return None


def _build_legs(
    slots: List[Dict[str, Any]],
    estimator: Estimator,
    previous_legs: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    prior = {(leg.get("from_index"), leg.get("to_index")): leg for leg in previous_legs or []}
    located = [
        (slot.get("slot_index"), _stop_geo(slot), slot)
        for slot in slots
        if _stop_geo(slot) is not None
    ]
    legs: List[Dict[str, Any]] = []
    for (from_index, from_geo, from_slot), (to_index, to_geo, to_slot) in zip(located, located[1:]):
        from_id = (from_slot.get("chosen") or {}).get("id")
        to_id = (to_slot.get("chosen") or {}).get("id")
        previous = prior.get((from_index, to_index))
        if previous and previous.get("from_id") == from_id and previous.get("to_id") == to_id:
            legs.append(dict(previous))
            continue
        legs.append({
            "from_index": from_index,
            "to_index": to_index,
            "from_id": from_id,
            "to_id": to_id,
            **estimator(from_geo, to_geo),
        })
    return legs


def _reschedule(block: Dict[str, Any]) -> None:
    """Recompute slot times and totals in place (no evaluation).

    Cheap enough to run per resolved leg so a later leg's departure time sees
    the updated schedule; the expensive evaluation is deferred to ``_finalize``.
    """
    slots = block.get("slots") or []
    legs_by_arrival = {leg.get("to_index"): leg for leg in block.get("legs") or []}
    current = _parse_hhmm(block.get("start_time")) or 10 * 60
    for slot in slots:
        if slot.get("chosen") is None:
            slot["time"] = slot.get("preferred_time")
            continue
        leg = legs_by_arrival.get(slot.get("slot_index"))
        if leg:
            current += int(leg.get("duration_min") or 0)
        preferred = _parse_hhmm(slot.get("preferred_time"))
        if preferred is not None:
            current = max(current, preferred)
        slot["time"] = _format_hhmm(current)
        current += _dwell(slot)
    terminal = next((leg for leg in block.get("legs") or [] if leg.get("to_anchor") == "end"), None)
    if terminal:
        current += int(terminal.get("duration_min") or 0)
    previous_totals = block.get("totals") if isinstance(block.get("totals"), dict) else {}
    block["totals"] = {
        "end_time": _format_hhmm(current),
        "total_travel_min": sum(int(leg.get("duration_min") or 0) for leg in block.get("legs") or []),
        **({"budget_note": previous_totals["budget_note"]} if previous_totals.get("budget_note") else {}),
    }


def _finalize(block: Dict[str, Any]) -> None:
    _reschedule(block)
    from langgraph_metarec.itinerary_evaluation import evaluate_itinerary

    block["evaluation"] = evaluate_itinerary(block)


def swap_legacy_choice(
    block: Dict[str, Any],
    slot_index: int,
    item_id: str,
    *,
    estimator: Estimator = estimate_leg,
) -> Dict[str, Any]:
    """Promote an alternate in a persisted pre-Planning-IR itinerary."""
    updated = copy.deepcopy(block)
    slot = next((row for row in updated.get("slots") or [] if row.get("slot_index") == slot_index), None)
    if slot is None:
        raise ValueError(f"unknown slot_index {slot_index}")
    chosen = slot.get("chosen")
    if isinstance(chosen, dict) and chosen.get("id") == item_id:
        return updated
    replacement = next((row for row in slot.get("alternates") or [] if row.get("id") == item_id), None)
    if replacement is None:
        raise ValueError(f"item {item_id} is not an alternate of slot {slot_index}")
    if any(
        other is not slot
        and isinstance(other.get("chosen"), dict)
        and str(other["chosen"].get("id") or "") == str(item_id)
        for other in updated.get("slots") or []
    ):
        raise ValueError(f"item {item_id} is already used by another slot")
    slot["alternates"] = [row for row in slot.get("alternates") or [] if row.get("id") != item_id]
    if isinstance(chosen, dict):
        slot["alternates"] = [chosen, *slot["alternates"]][:_MAX_ALTERNATES]
    slot["chosen"] = replacement
    updated["legs"] = _build_legs(updated["slots"], estimator, updated.get("legs"))
    updated["revision"] = int(updated.get("revision") or 1) + 1
    _finalize(updated)
    return updated


def replace_legacy_slot_candidates(
    block: Dict[str, Any],
    slot_index: int,
    candidates: List[Dict[str, Any]],
    *,
    estimator: Estimator = estimate_leg,
) -> Dict[str, Any]:
    """Replace one candidate pool in a persisted pre-Planning-IR itinerary."""
    updated = copy.deepcopy(block)
    slots = updated.get("slots") or []
    slot = next((row for row in slots if row.get("slot_index") == slot_index), None)
    if slot is None:
        raise ValueError(f"unknown slot_index {slot_index}")
    used_ids = {
        str((other.get("chosen") or {}).get("id"))
        for other in slots
        if other is not slot and isinstance(other.get("chosen"), dict)
    }
    options = [item for item in map(_lite_item, candidates) if not item.get("id") or str(item["id"]) not in used_ids]
    located = [item for item in options if item.get("lat") is not None and item.get("lng") is not None]
    prior = next((_stop_geo(row) for row in reversed(slots) if row.get("slot_index", -1) < slot_index and _stop_geo(row)), None)
    following = next((_stop_geo(row) for row in slots if row.get("slot_index", -1) > slot_index and _stop_geo(row)), None)
    chosen = None
    if located:
        chosen = min(located, key=lambda item: (
            (estimator(prior, (item["lat"], item["lng"]))["distance_km"] if prior else 0)
            + (estimator((item["lat"], item["lng"]), following)["distance_km"] if following else 0)
            - 0.3 * float(item.get("rating") or 0)
        ))
    slot["chosen"] = chosen
    slot["alternates"] = [item for item in options if chosen is None or item.get("id") != chosen.get("id")][:_MAX_ALTERNATES]
    updated["legs"] = _build_legs(slots, estimator, updated.get("legs"))
    updated["revision"] = int(updated.get("revision") or 1) + 1
    _finalize(updated)
    return updated


async def resolve_legacy_legs(block: Dict[str, Any], resolver: Resolver) -> Dict[str, Any]:
    """Resolve only newly estimated legs in a pre-Planning-IR payload."""
    updated = copy.deepcopy(block)
    geo_by_index = {slot.get("slot_index"): _stop_geo(slot) for slot in updated.get("slots") or []}
    anchors = updated.get("anchors") if isinstance(updated.get("anchors"), dict) else {}

    def anchor_geo(key: str) -> Optional[Tuple[float, float]]:
        anchor = anchors.get(key)
        if not isinstance(anchor, dict):
            return None
        try:
            return float(anchor["lat"]), float(anchor["lng"])
        except (KeyError, TypeError, ValueError):
            return None

    for position, leg in enumerate(updated.get("legs") or []):
        if leg.get("source") != "estimate":
            continue
        from_geo = anchor_geo(str(leg.get("from_anchor"))) if leg.get("from_anchor") else geo_by_index.get(leg.get("from_index"))
        to_geo = anchor_geo(str(leg.get("to_anchor"))) if leg.get("to_anchor") else geo_by_index.get(leg.get("to_index"))
        if from_geo is None or to_geo is None:
            continue
        from_slot = next((slot for slot in updated.get("slots") or [] if slot.get("slot_index") == leg.get("from_index")), {})
        arrival = _parse_hhmm(from_slot.get("time"))
        depart_hhmm = str(updated.get("start_time")) if leg.get("from_anchor") == "start" else (
            _format_hhmm(arrival + _dwell(from_slot)) if arrival is not None else None
        )
        kwargs = {
            "depart_hhmm": depart_hhmm,
            "service_date": updated.get("service_date"),
            "timezone": str(updated.get("timezone") or "Asia/Singapore"),
        }
        try:
            parameters = inspect.signature(resolver).parameters.values()
            if not any(parameter.kind == parameter.VAR_KEYWORD for parameter in parameters):
                accepted = {parameter.name for parameter in parameters}
                kwargs = {key: value for key, value in kwargs.items() if key in accepted}
        except (TypeError, ValueError):
            pass
        resolved = resolver(from_geo, to_geo, **kwargs)
        if inspect.isawaitable(resolved):
            resolved = await resolved
        updated["legs"][position] = {
            "from_index": leg.get("from_index"),
            "to_index": leg.get("to_index"),
            **({"from_anchor": leg["from_anchor"]} if leg.get("from_anchor") else {}),
            **({"to_anchor": leg["to_anchor"]} if leg.get("to_anchor") else {}),
            "from_id": leg.get("from_id"),
            "to_id": leg.get("to_id"),
            **resolved,
        }
        # Propagate the new schedule so the next leg departs at the right time;
        # the one-time evaluation happens in the final _finalize below.
        _reschedule(updated)
    _finalize(updated)
    return updated
