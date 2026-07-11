"""Pure itinerary composition — no I/O, no LLM, no network.

Takes the per-slot candidate lists the existing domain graphs produced and
greedily composes a trajectory using ONLY deterministic haversine estimates
(the injected ``estimator``; see eta.estimate_leg). Real routing providers are
applied afterwards via ``resolve_block_legs`` with an injected resolver, so
this module stays unit-testable and the N-1-API-calls discipline is enforced
in exactly one place.

Itinerary block shape (persisted under result ``metadata["itinerary"]`` and
mirrored by the frontend ``Itinerary`` type):

    { "location": str, "start_time": "HH:MM",
      "slots": [{ "slot_index", "label", "domain", "preferred_time",
                  "time",                       # computed arrival
                  "chosen": <lite item | None>, # {id,title,subtitle,rating,
                                                #  price,price_per_person_sgd,
                                                #  image_url,url,domain,lat,lng}
                  "alternates": [<lite item> x<=4] }],
      "legs":  [{ "from_index", "to_index", "from_id", "to_id", "mode",
                  "duration_min", "distance_km", "fare"?, "source", "coords"? }],
      "totals": { "end_time", "total_travel_min", "budget_note"? } }
"""
from __future__ import annotations

import copy
from typing import Any, Callable, Dict, List, Optional, Tuple

from langgraph_metarec.eta import estimate_leg

# Default minutes spent at a stop, by domain.
DWELL_MIN: Dict[str, int] = {"attraction": 120, "restaurant": 90, "hotel": 0}
_DEFAULT_DWELL_MIN = 90
MAX_ALTERNATES = 4

Estimator = Callable[..., Dict[str, Any]]


def candidate_geo(candidate: Dict[str, Any]) -> Optional[Tuple[float, float]]:
    """(lat, lng) from either shape: restaurant dicts carry top-level
    ``gps_coordinates``; generic items keep it in ``raw``."""
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


def _price_per_person(candidate: Dict[str, Any]) -> Optional[float]:
    value = candidate.get("price_per_person_sgd")
    try:
        parsed = float(value)
        return parsed if parsed > 0 else None
    except (TypeError, ValueError):
        return None


def lite_item(candidate: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten a restaurant rec or generic item into the compact stop shape the
    itinerary block ships to the client (no ``raw``, coordinates surfaced)."""
    geo = candidate_geo(candidate)
    lite: Dict[str, Any] = {
        "id": candidate.get("id"),
        "title": candidate.get("title") or candidate.get("name") or "Untitled",
        "subtitle": candidate.get("subtitle") or candidate.get("address"),
        "rating": candidate.get("rating"),
        "price": candidate.get("price"),
        "image_url": candidate.get("image_url"),
        "url": candidate.get("url") or candidate.get("reference"),
        "domain": candidate.get("domain"),
        "lat": geo[0] if geo else None,
        "lng": geo[1] if geo else None,
    }
    price_pp = _price_per_person(candidate)
    if price_pp is not None:
        lite["price_per_person_sgd"] = price_pp
    return lite


def _parse_hhmm(text: Any) -> Optional[int]:
    try:
        hour, minute = (int(part) for part in str(text).strip().split(":", 1))
        if 0 <= hour < 24 and 0 <= minute < 60:
            return hour * 60 + minute
    except (ValueError, TypeError, AttributeError):
        pass
    return None


def _fmt_hhmm(minutes: int) -> str:
    return f"{(minutes // 60) % 24:02d}:{minutes % 60:02d}"


def _dwell(domain: Any) -> int:
    return DWELL_MIN.get(str(domain or "").lower(), _DEFAULT_DWELL_MIN)


def _stop_geo(slot: Dict[str, Any]) -> Optional[Tuple[float, float]]:
    chosen = slot.get("chosen")
    if isinstance(chosen, dict) and chosen.get("lat") is not None and chosen.get("lng") is not None:
        return float(chosen["lat"]), float(chosen["lng"])
    return None


def _build_legs(
    slots: List[Dict[str, Any]],
    estimator: Estimator,
    previous_legs: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Estimate legs between consecutive geo-located stops. When
    ``previous_legs`` is given, legs whose endpoint STOPS are unchanged (same
    chosen item ids) keep their prior — possibly provider-resolved — data, so
    a swap only refreshes the legs adjacent to the swapped stop."""
    prior = {(leg.get("from_index"), leg.get("to_index")): leg for leg in previous_legs or []}
    legs: List[Dict[str, Any]] = []
    located = [(slot["slot_index"], _stop_geo(slot), slot) for slot in slots]
    located = [(index, geo, slot) for index, geo, slot in located if geo is not None]
    for (from_index, from_geo, from_slot), (to_index, to_geo, to_slot) in zip(located, located[1:]):
        from_id = (from_slot.get("chosen") or {}).get("id")
        to_id = (to_slot.get("chosen") or {}).get("id")
        previous = prior.get((from_index, to_index))
        if previous is not None and previous.get("from_id") == from_id and previous.get("to_id") == to_id:
            legs.append(dict(previous))  # same endpoint stops -> keep resolution
            continue
        legs.append(
            {
                "from_index": from_index,
                "to_index": to_index,
                "from_id": from_id,
                "to_id": to_id,
                **estimator(from_geo, to_geo),
            }
        )
    return legs


def _recompute_schedule(block: Dict[str, Any]) -> None:
    """Recompute arrival times and totals in place from legs + dwell defaults.
    A slot's ``preferred_time`` acts as a not-before constraint."""
    slots = block.get("slots") or []
    legs_by_arrival = {leg["to_index"]: leg for leg in block.get("legs") or []}
    current = _parse_hhmm(block.get("start_time")) or 10 * 60
    for slot in slots:
        if slot.get("chosen") is None:
            slot["time"] = slot.get("preferred_time")
            continue
        leg = legs_by_arrival.get(slot["slot_index"])
        if leg is not None:
            current += int(leg.get("duration_min") or 0)
        preferred = _parse_hhmm(slot.get("preferred_time"))
        if preferred is not None and preferred > current:
            current = preferred
        slot["time"] = _fmt_hhmm(current)
        current += _dwell(slot.get("domain"))
    total_travel = sum(int(leg.get("duration_min") or 0) for leg in block.get("legs") or [])
    block["totals"] = {
        "end_time": _fmt_hhmm(current),
        "total_travel_min": total_travel,
        **({"budget_note": block["totals"]["budget_note"]} if (block.get("totals") or {}).get("budget_note") else {}),
    }


def _budget_note(slots: List[Dict[str, Any]], budget: str) -> Optional[str]:
    prices = [
        slot["chosen"]["price_per_person_sgd"]
        for slot in slots
        if isinstance(slot.get("chosen"), dict) and slot["chosen"].get("price_per_person_sgd")
    ]
    if not prices:
        return None
    note = f"Estimated food spend ≈ {int(round(sum(prices)))} SGD/person"
    if str(budget or "").strip():
        note += f" (your budget: {str(budget).strip()})"
    return note


def compose_itinerary(
    slot_plans: List[Dict[str, Any]],
    *,
    location: str,
    start_time: str = "10:00",
    budget: str = "",
    estimator: Estimator = estimate_leg,
) -> Dict[str, Any]:
    """Greedy nearest-neighbor composition over per-slot candidates.

    ``slot_plans``: ordered [{slot_index, slot_label, slot_time, domain,
    candidates: [raw candidate dicts]}]. Candidates are assumed pre-ranked
    (best first). The first geo-located choice anchors the route; each later
    slot picks the candidate minimizing distance-from-previous minus a small
    rating bonus. Geo-less candidates stay available as alternates but are
    never chosen while a geo-located candidate exists.
    """
    slots: List[Dict[str, Any]] = []
    previous_geo: Optional[Tuple[float, float]] = None
    for plan in slot_plans:
        lites = [lite_item(candidate) for candidate in plan.get("candidates") or []]
        geo_lites = [lite for lite in lites if lite["lat"] is not None]
        chosen: Optional[Dict[str, Any]] = None
        if geo_lites:
            if previous_geo is None:
                chosen = geo_lites[0]
            else:
                chosen = min(
                    geo_lites,
                    key=lambda lite: (
                        estimator(previous_geo, (lite["lat"], lite["lng"]))["distance_km"]
                        - 0.3 * float(lite.get("rating") or 0)
                    ),
                )
            previous_geo = (chosen["lat"], chosen["lng"])
        alternates = [lite for lite in lites if chosen is None or lite["id"] != chosen["id"]][:MAX_ALTERNATES]
        slots.append(
            {
                "slot_index": int(plan.get("slot_index", len(slots))),
                "label": plan.get("slot_label") or plan.get("label") or str(plan.get("domain") or "stop"),
                "domain": plan.get("domain"),
                "preferred_time": plan.get("slot_time") or plan.get("time"),
                "time": None,
                "chosen": chosen,
                "alternates": alternates,
            }
        )

    block: Dict[str, Any] = {
        "location": location,
        "start_time": start_time if _parse_hhmm(start_time) is not None else "10:00",
        "slots": slots,
        "legs": _build_legs(slots, estimator),
        "totals": {},
    }
    note = _budget_note(slots, budget)
    if note:
        block["totals"]["budget_note"] = note
    _recompute_schedule(block)
    return block


def swap_choice(
    block: Dict[str, Any],
    slot_index: int,
    item_id: str,
    *,
    estimator: Estimator = estimate_leg,
) -> Dict[str, Any]:
    """Return a new block with ``item_id`` (one of the slot's alternates)
    promoted to chosen. Only the legs adjacent to the swapped stop are
    re-estimated (source resets to "estimate" for re-resolution); every other
    leg keeps its prior provider resolution. Raises ValueError when the slot
    or alternate is unknown."""
    updated = copy.deepcopy(block)
    slot = next((s for s in updated.get("slots") or [] if s.get("slot_index") == slot_index), None)
    if slot is None:
        raise ValueError(f"unknown slot_index {slot_index}")
    chosen = slot.get("chosen")
    if isinstance(chosen, dict) and chosen.get("id") == item_id:
        return updated  # already selected — no-op
    replacement = next((a for a in slot.get("alternates") or [] if a.get("id") == item_id), None)
    if replacement is None:
        raise ValueError(f"item {item_id} is not an alternate of slot {slot_index}")
    slot["alternates"] = [a for a in slot["alternates"] if a.get("id") != item_id]
    if isinstance(chosen, dict):
        slot["alternates"] = ([chosen] + slot["alternates"])[:MAX_ALTERNATES]
    slot["chosen"] = replacement
    updated["legs"] = _build_legs(updated["slots"], estimator, previous_legs=updated.get("legs"))
    _recompute_schedule(updated)
    return updated


def replace_slot_candidates(
    block: Dict[str, Any],
    slot_index: int,
    candidates: List[Dict[str, Any]],
    *,
    estimator: Estimator = estimate_leg,
) -> Dict[str, Any]:
    """Return a new block where one slot's candidate pool is replaced (prompt
    refine): the slot re-chooses greedily against its fixed neighbors and only
    its adjacent legs are re-estimated."""
    updated = copy.deepcopy(block)
    slots = updated.get("slots") or []
    slot = next((s for s in slots if s.get("slot_index") == slot_index), None)
    if slot is None:
        raise ValueError(f"unknown slot_index {slot_index}")
    lites = [lite_item(candidate) for candidate in candidates]
    geo_lites = [lite for lite in lites if lite["lat"] is not None]
    anchor = next(
        (_stop_geo(s) for s in reversed(slots) if s["slot_index"] < slot_index and _stop_geo(s) is not None),
        None,
    )
    chosen: Optional[Dict[str, Any]] = None
    if geo_lites:
        if anchor is None:
            chosen = geo_lites[0]
        else:
            chosen = min(
                geo_lites,
                key=lambda lite: (
                    estimator(anchor, (lite["lat"], lite["lng"]))["distance_km"]
                    - 0.3 * float(lite.get("rating") or 0)
                ),
            )
    slot["chosen"] = chosen
    slot["alternates"] = [lite for lite in lites if chosen is None or lite["id"] != chosen["id"]][:MAX_ALTERNATES]
    updated["legs"] = _build_legs(slots, estimator, previous_legs=updated.get("legs"))
    _recompute_schedule(updated)
    return updated


def resolve_block_legs(block: Dict[str, Any], resolver: Estimator) -> Dict[str, Any]:
    """Apply the real ETA resolver to every leg that is still a deterministic
    estimate — exactly the composed N-1 legs on first call, and only the
    refreshed adjacent legs after a swap/refine (the rest keep their provider
    data). Returns a new block with the schedule recomputed."""
    updated = copy.deepcopy(block)
    geo_by_index = {slot["slot_index"]: _stop_geo(slot) for slot in updated.get("slots") or []}
    time_by_index = {slot["slot_index"]: slot.get("time") for slot in updated.get("slots") or []}
    for position, leg in enumerate(updated.get("legs") or []):
        if leg.get("source") != "estimate":
            continue
        from_geo = geo_by_index.get(leg.get("from_index"))
        to_geo = geo_by_index.get(leg.get("to_index"))
        if from_geo is None or to_geo is None:
            continue
        resolved = resolver(from_geo, to_geo, depart_hhmm=time_by_index.get(leg.get("from_index")))
        updated["legs"][position] = {
            "from_index": leg["from_index"],
            "to_index": leg["to_index"],
            "from_id": leg.get("from_id"),
            "to_id": leg.get("to_id"),
            **resolved,
        }
    _recompute_schedule(updated)
    return updated
