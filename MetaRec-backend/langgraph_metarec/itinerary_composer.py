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
import inspect
import re
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple, Union

from langgraph_metarec.eta import estimate_leg

# Default minutes spent at a stop, by domain.
DWELL_MIN: Dict[str, int] = {"attraction": 120, "restaurant": 90, "hotel": 0}
_DEFAULT_DWELL_MIN = 90
MAX_ALTERNATES = 4
BEAM_WIDTH = 12
MAX_CANDIDATES_PER_SLOT = 5

Estimator = Callable[..., Dict[str, Any]]
Resolver = Callable[..., Union[Dict[str, Any], Awaitable[Dict[str, Any]]]]


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
        "source": candidate.get("source"),
        "lat": geo[0] if geo else None,
        "lng": geo[1] if geo else None,
    }
    raw = candidate.get("raw") if isinstance(candidate.get("raw"), dict) else {}
    tags = raw.get("tags") if isinstance(raw.get("tags"), dict) else {}
    opening_hours = candidate.get("opening_hours") or raw.get("opening_hours") or tags.get("opening_hours")
    if opening_hours:
        lite["opening_hours"] = str(opening_hours)[:160]
    if isinstance(candidate.get("open_now"), bool):
        lite["open_now"] = candidate["open_now"]
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


def _dwell(slot_or_domain: Any) -> int:
    if isinstance(slot_or_domain, dict):
        try:
            explicit = int(slot_or_domain.get("dwell_min"))
            if 0 <= explicit <= 12 * 60:
                return explicit
        except (TypeError, ValueError):
            pass
        domain = slot_or_domain.get("domain")
    else:
        domain = slot_or_domain
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
        current += _dwell(slot)
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


def _budget_limit(budget: Any) -> Optional[float]:
    values = [float(value) for value in re.findall(r"\d+(?:\.\d+)?", str(budget or ""))]
    return max(values) if values else None


def validate_itinerary(block: Dict[str, Any]) -> Dict[str, Any]:
    """Deterministic feasibility projection. Unknown provider facts are exposed
    as warnings rather than treated as valid facts."""
    slots = [slot for slot in block.get("slots") or [] if isinstance(slot, dict)]
    violations: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []
    seen: set[str] = set()
    chosen_count = 0
    food_spend = 0.0
    for slot in slots:
        chosen = slot.get("chosen") if isinstance(slot.get("chosen"), dict) else None
        if chosen is None:
            violations.append({"code": "missing_required_stop", "slot_index": slot.get("slot_index")})
            continue
        chosen_count += 1
        item_id = str(chosen.get("id") or "")
        if item_id and item_id in seen:
            violations.append({"code": "duplicate_poi", "slot_index": slot.get("slot_index"), "item_id": item_id})
        seen.add(item_id)
        if chosen.get("open_now") is False:
            violations.append({"code": "known_closed", "slot_index": slot.get("slot_index")})
        elif not chosen.get("opening_hours"):
            warnings.append({"code": "opening_hours_unknown", "slot_index": slot.get("slot_index")})
        try:
            food_spend += float(chosen.get("price_per_person_sgd") or 0)
        except (TypeError, ValueError):
            pass
        if slot.get("domain") == "restaurant":
            minute = _parse_hhmm(slot.get("time"))
            label = str(slot.get("label") or "").lower()
            if minute is not None and "lunch" in label and not (11 * 60 <= minute <= 14 * 60 + 30):
                violations.append({"code": "meal_window", "slot_index": slot.get("slot_index"), "meal": "lunch"})
            if minute is not None and "dinner" in label and not (17 * 60 <= minute <= 21 * 60 + 30):
                violations.append({"code": "meal_window", "slot_index": slot.get("slot_index"), "meal": "dinner"})
    start = _parse_hhmm(block.get("start_time"))
    end = _parse_hhmm((block.get("totals") or {}).get("end_time"))
    if start is not None and end is not None:
        duration = end - start if end >= start else end + 24 * 60 - start
        if duration > 14 * 60:
            violations.append({"code": "day_too_long", "duration_min": duration})
    budget_limit = _budget_limit(block.get("budget"))
    if budget_limit is not None and food_spend > budget_limit:
        violations.append({"code": "budget_exceeded", "estimated": round(food_spend, 2), "limit": budget_limit})
    return {
        "status": "valid" if not violations else ("partial" if chosen_count else "invalid"),
        "violations": violations,
        "warnings": warnings[:12],
        "checks": {
            "chosen_stops": chosen_count,
            "required_stops": len(slots),
            "estimated_food_spend_sgd": round(food_spend, 2),
            "budget_limit_sgd": budget_limit,
        },
    }


def _finalize(block: Dict[str, Any]) -> None:
    _recompute_schedule(block)
    block["validation"] = validate_itinerary(block)
    from langgraph_metarec.itinerary_evaluation import evaluate_itinerary

    block["evaluation"] = evaluate_itinerary(block)


def _beam_route_choices(
    candidates_by_slot: List[List[Dict[str, Any]]],
    *,
    budget: str,
    estimator: Estimator,
    beam_width: int = BEAM_WIDTH,
) -> Tuple[List[Optional[Dict[str, Any]]], Dict[str, Any]]:
    """Bounded route-level search. Hard failures sort before soft utility, so
    rating can never buy back a duplicate, missing stop, known closure, or
    explicit budget overrun."""
    limit = _budget_limit(budget)
    beam: List[Dict[str, Any]] = [{
        "choices": [], "used": frozenset(), "last_geo": None,
        "missing": 0, "closed": 0, "distance": 0.0,
        "rank_cost": 0.0, "rating_total": 0.0, "spend": 0.0,
    }]

    def key(state: Dict[str, Any]) -> tuple:
        excess = max(0.0, state["spend"] - limit) if limit is not None else 0.0
        soft_cost = state["distance"] + state["rank_cost"] - 0.3 * state["rating_total"]
        return (state["missing"], state["closed"], int(excess > 0), round(excess, 3), round(soft_cost, 6))

    expanded_states = 0
    for slot_candidates in candidates_by_slot:
        next_beam: List[Dict[str, Any]] = []
        for state in beam:
            available = [
                (rank, candidate)
                for rank, candidate in enumerate(slot_candidates[:MAX_CANDIDATES_PER_SLOT])
                if candidate.get("lat") is not None
                and (not candidate.get("id") or str(candidate["id"]) not in state["used"])
            ]
            options: List[Tuple[int, Optional[Dict[str, Any]]]] = available or [(0, None)]
            for rank, candidate in options:
                expanded_states += 1
                item_id = str((candidate or {}).get("id") or "")
                geo = (candidate["lat"], candidate["lng"]) if candidate else None
                leg_distance = (
                    float(estimator(state["last_geo"], geo).get("distance_km") or 0)
                    if state["last_geo"] is not None and geo is not None else 0.0
                )
                try:
                    spend = float((candidate or {}).get("price_per_person_sgd") or 0)
                except (TypeError, ValueError):
                    spend = 0.0
                next_beam.append({
                    "choices": [*state["choices"], candidate],
                    "used": state["used"] | ({item_id} if item_id else set()),
                    "last_geo": geo or state["last_geo"],
                    "missing": state["missing"] + int(candidate is None),
                    "closed": state["closed"] + int((candidate or {}).get("open_now") is False),
                    "distance": state["distance"] + leg_distance,
                    "rank_cost": state["rank_cost"] + rank * 0.25,
                    "rating_total": state["rating_total"] + float((candidate or {}).get("rating") or 0),
                    "spend": state["spend"] + spend,
                })
        beam = sorted(next_beam, key=key)[:max(1, beam_width)]

    winner = min(beam, key=key) if beam else {"choices": [None] * len(candidates_by_slot)}
    return winner["choices"], {
        "strategy": "bounded_beam_search",
        "beam_width": beam_width,
        "candidate_limit_per_slot": MAX_CANDIDATES_PER_SLOT,
        "expanded_states": expanded_states,
        "route_distance_km": round(float(winner.get("distance") or 0), 2),
        "estimated_spend_sgd": round(float(winner.get("spend") or 0), 2),
        "objective_order": ["missing", "known_closed", "budget_excess", "distance_rank_quality"],
    }


def compose_itinerary(
    slot_plans: List[Dict[str, Any]],
    *,
    location: str,
    start_time: str = "10:00",
    budget: str = "",
    service_date: Optional[str] = None,
    timezone: str = "Asia/Singapore",
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
    prepared = [[lite_item(candidate) for candidate in plan.get("candidates") or []] for plan in slot_plans]
    choices, optimizer = _beam_route_choices(prepared, budget=budget, estimator=estimator)
    chosen_ids = {str(choice.get("id")) for choice in choices if choice and choice.get("id")}
    slots: List[Dict[str, Any]] = []
    for plan, lites, chosen in zip(slot_plans, prepared, choices):
        alternates = [
            lite for lite in lites
            if (chosen is None or lite.get("id") != chosen.get("id"))
            and (not lite.get("id") or str(lite["id"]) not in chosen_ids)
        ][:MAX_ALTERNATES]
        slots.append(
            {
                "slot_index": int(plan.get("slot_index", len(slots))),
                "label": plan.get("slot_label") or plan.get("label") or str(plan.get("domain") or "stop"),
                "domain": plan.get("domain"),
                "preferred_time": plan.get("slot_time") or plan.get("time"),
                "slot_role": plan.get("slot_role") or "activity",
                "slot_preferences": dict(plan.get("slot_preferences") or {}),
                "dwell_min": plan.get("dwell_min"),
                "time": None,
                "chosen": chosen,
                "alternates": alternates,
            }
        )

    block: Dict[str, Any] = {
        "location": location,
        "start_time": start_time if _parse_hhmm(start_time) is not None else "10:00",
        "service_date": service_date,
        "timezone": timezone or "Asia/Singapore",
        "budget": budget,
        "revision": 1,
        "optimizer": optimizer,
        "slots": slots,
        "legs": _build_legs(slots, estimator),
        "totals": {},
    }
    note = _budget_note(slots, budget)
    if note:
        block["totals"]["budget_note"] = note
    _finalize(block)
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
    if any(
        other is not slot
        and isinstance(other.get("chosen"), dict)
        and str(other["chosen"].get("id") or "") == str(item_id)
        for other in updated.get("slots") or []
    ):
        raise ValueError(f"item {item_id} is already used by another slot")
    slot["alternates"] = [a for a in slot["alternates"] if a.get("id") != item_id]
    if isinstance(chosen, dict):
        slot["alternates"] = ([chosen] + slot["alternates"])[:MAX_ALTERNATES]
    slot["chosen"] = replacement
    updated["legs"] = _build_legs(updated["slots"], estimator, previous_legs=updated.get("legs"))
    updated["revision"] = int(updated.get("revision") or 1) + 1
    _finalize(updated)
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
    used_ids = {
        str((other.get("chosen") or {}).get("id"))
        for other in slots
        if other is not slot and isinstance(other.get("chosen"), dict) and (other.get("chosen") or {}).get("id")
    }
    lites = [lite_item(candidate) for candidate in candidates]
    lites = [lite for lite in lites if not lite.get("id") or str(lite["id"]) not in used_ids]
    geo_lites = [lite for lite in lites if lite["lat"] is not None]
    anchor = next(
        (_stop_geo(s) for s in reversed(slots) if s["slot_index"] < slot_index and _stop_geo(s) is not None),
        None,
    )
    successor = next(
        (_stop_geo(s) for s in slots if s["slot_index"] > slot_index and _stop_geo(s) is not None),
        None,
    )
    chosen: Optional[Dict[str, Any]] = None
    if geo_lites:
        if anchor is None and successor is None:
            chosen = geo_lites[0]
        else:
            chosen = min(
                geo_lites,
                key=lambda lite: (
                    (estimator(anchor, (lite["lat"], lite["lng"]))["distance_km"] if anchor else 0)
                    + (estimator((lite["lat"], lite["lng"]), successor)["distance_km"] if successor else 0)
                    - 0.3 * float(lite.get("rating") or 0)
                ),
            )
    slot["chosen"] = chosen
    slot["alternates"] = [lite for lite in lites if chosen is None or lite["id"] != chosen["id"]][:MAX_ALTERNATES]
    updated["legs"] = _build_legs(slots, estimator, previous_legs=updated.get("legs"))
    updated["revision"] = int(updated.get("revision") or 1) + 1
    _finalize(updated)
    return updated


async def resolve_block_legs(block: Dict[str, Any], resolver: Resolver) -> Dict[str, Any]:
    """Apply the real ETA resolver to every leg that is still a deterministic
    estimate — exactly the composed N-1 legs on first call, and only the
    refreshed adjacent legs after a swap/refine (the rest keep their provider
    data). Returns a new block with the schedule recomputed."""
    updated = copy.deepcopy(block)
    geo_by_index = {slot["slot_index"]: _stop_geo(slot) for slot in updated.get("slots") or []}
    for position, leg in enumerate(updated.get("legs") or []):
        if leg.get("source") != "estimate":
            continue
        from_geo = geo_by_index.get(leg.get("from_index"))
        to_geo = geo_by_index.get(leg.get("to_index"))
        if from_geo is None or to_geo is None:
            continue
        from_slot = next((slot for slot in updated.get("slots") or [] if slot.get("slot_index") == leg.get("from_index")), {})
        arrival = _parse_hhmm(from_slot.get("time"))
        depart_hhmm = _fmt_hhmm(arrival + _dwell(from_slot)) if arrival is not None else None
        resolver_kwargs = {
            "depart_hhmm": depart_hhmm,
            "service_date": updated.get("service_date"),
            "timezone": str(updated.get("timezone") or "Asia/Singapore"),
        }
        try:
            parameters = inspect.signature(resolver).parameters.values()
            accepts_kwargs = any(parameter.kind == parameter.VAR_KEYWORD for parameter in parameters)
            accepted_names = {parameter.name for parameter in parameters}
            if not accepts_kwargs:
                resolver_kwargs = {key: value for key, value in resolver_kwargs.items() if key in accepted_names}
        except (TypeError, ValueError):
            pass
        resolved = resolver(from_geo, to_geo, **resolver_kwargs)
        if inspect.isawaitable(resolved):
            resolved = await resolved
        updated["legs"][position] = {
            "from_index": leg["from_index"],
            "to_index": leg["to_index"],
            "from_id": leg.get("from_id"),
            "to_id": leg.get("to_id"),
            **resolved,
        }
        _recompute_schedule(updated)
    _finalize(updated)
    return updated
