"""Conversion helpers between dynamic solver output and the public itinerary block."""
from __future__ import annotations

import copy
import inspect
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from langgraph_metarec.eta import estimate_leg
from langgraph_metarec.itinerary_contracts import (
    AvailabilityWindow,
    CostEstimate,
    DurationEstimate,
    ItineraryPlanningRequest,
    LodgingScenario,
    PlanningCandidate,
    SolverResult,
)


def fmt_hhmm(minutes: int) -> str:
    return f"{(int(minutes) // 60) % 24:02d}:{int(minutes) % 60:02d}"


def parse_hhmm(value: str) -> int:
    hour, minute = (int(part) for part in str(value).split(":", 1))
    return hour * 60 + minute


# Single owner for the two totals formulas. `build_itinerary_block` (provisional,
# pre-ETA), `resolve_itinerary_legs` (post-ETA schedule) and
# `finalize_dynamic_metadata` (authoritative) all derive these the same way; the
# stage-specific pieces (end_time, wait) stay with each caller.
def sum_travel_min(legs: Sequence[Dict[str, Any]]) -> int:
    return sum(int(leg.get("duration_min") or 0) for leg in legs or [])


def sum_activity_min(slots: Sequence[Dict[str, Any]]) -> int:
    return sum(int(slot.get("dwell_min") or 0) for slot in slots or [])


def _anchor_geo(anchor: Any) -> Optional[Tuple[float, float]]:
    try:
        return float(anchor.latitude), float(anchor.longitude)
    except (AttributeError, TypeError, ValueError):
        return None


def build_travel_matrix(
    candidates: Sequence[PlanningCandidate],
    request: Optional[ItineraryPlanningRequest] = None,
    lodging_scenarios: Sequence[LodgingScenario] = (),
) -> Dict[str, Dict[str, int]]:
    nodes: List[Tuple[str, Tuple[float, float]]] = [
        (candidate.id, (candidate.latitude, candidate.longitude)) for candidate in candidates
    ]
    if request is not None:
        for key in ("start", "end"):
            geo = _anchor_geo(request.anchors.get(key))
            if geo is not None:
                nodes.append((f"anchor:{key}", geo))
    nodes.extend(
        (
            f"lodging:{scenario.candidate_id}",
            (float(scenario.latitude), float(scenario.longitude)),
        )
        for scenario in lodging_scenarios
    )
    matrix: Dict[str, Dict[str, int]] = {}
    for source_id, source_geo in nodes:
        matrix[source_id] = {}
        for target_id, target_geo in nodes:
            if source_id == target_id:
                continue
            leg = estimate_leg(source_geo, target_geo)
            matrix[source_id][target_id] = max(0, int(leg.get("duration_min") or 0))
    return matrix


def _anchor_item(key: str, anchor: Any) -> Optional[Dict[str, Any]]:
    geo = _anchor_geo(anchor)
    if geo is None:
        return None
    return {
        "id": f"anchor:{key}",
        "title": anchor.resolved_name or anchor.query,
        "address": anchor.address,
        "lat": geo[0],
        "lng": geo[1],
        "provider_id": anchor.provider_id,
        "source": anchor.source,
    }


def build_itinerary_block(
    request: ItineraryPlanningRequest,
    result: SolverResult,
    candidates: Sequence[PlanningCandidate],
    *,
    revision: int = 1,
) -> Dict[str, Any]:
    by_id = {candidate.id: candidate for candidate in candidates}
    selected_ids = {str(activity.get("candidate_id")) for activity in result.activities}
    slots: List[Dict[str, Any]] = []
    for index, activity in enumerate(result.activities):
        candidate = by_id[str(activity["candidate_id"])]
        alternates = [
            {
                **dict(other.item),
                "duration": {
                    "min": other.duration.min, "preferred": other.duration.preferred,
                    "max": other.duration.max, "source": other.duration.source,
                },
                "cost": {
                    "min": other.cost.min, "max": other.cost.max,
                    "currency": other.cost.currency, "source": other.cost.source,
                },
                "availability": {
                    "known": other.availability_known,
                    "windows": [window.__dict__ for window in other.availability_windows],
                },
            }
            for other in candidates
            if other.domain == candidate.domain
            and other.id not in selected_ids
            and other.access != "gated"
        ][:4]
        slots.append({
            "slot_index": index,
            "day_index": int(activity.get("day_index") or 0),
            "label": candidate.title,
            "domain": candidate.domain,
            "slot_role": "activity",
            "preferred_time": fmt_hhmm(int(activity["start_min"])),
            "time": fmt_hhmm(int(activity["start_min"])),
            "end_time": fmt_hhmm(int(activity["end_min"])),
            "dwell_min": candidate.duration.preferred,
            "duration": dict(activity["duration"]),
            "cost": dict(activity["cost"]),
            "meal_coverage": list(activity.get("meal_coverage") or []),
            "satisfied_meals": list(activity.get("satisfied_meals") or []),
            "sub_activities": list(activity.get("sub_activities") or []),
            "availability": {
                "known": candidate.availability_known,
                "windows": [window.__dict__ for window in candidate.availability_windows],
            },
            "chosen": dict(candidate.item),
            "alternates": alternates,
        })
    legs: List[Dict[str, Any]] = []
    start_anchor = _anchor_item("start", request.anchors.get("start"))
    end_anchor = _anchor_item("end", request.anchors.get("end"))
    lodging_anchor = _anchor_item("lodging", request.anchors.get("lodging"))
    selected_lodging = dict(result.lodging) if isinstance(result.lodging, dict) else None
    if selected_lodging and lodging_anchor is None:
        lodging_anchor = {
            "id": selected_lodging.get("candidate_id") or "anchor:lodging",
            "title": selected_lodging.get("title") or "Shared hotel",
            "address": selected_lodging.get("address"),
            "lat": selected_lodging.get("latitude"),
            "lng": selected_lodging.get("longitude"),
            "provider_id": selected_lodging.get("candidate_id"),
            "source": selected_lodging.get("source"),
        }
    multi_day = len(request.days) > 1
    day_blocks: List[Dict[str, Any]] = []
    for day in request.days:
        day_slots = [slot for slot in slots if slot["day_index"] == day.day_index]
        day_legs: List[Dict[str, Any]] = []
        boundary = lodging_anchor if multi_day else (
            start_anchor if day.day_index == 0 else None
        )
        boundary_name = "lodging" if multi_day else "start"
        if boundary and day_slots:
            first_item = day_slots[0]["chosen"]
            day_legs.append({
                "day_index": day.day_index,
                "from_index": None,
                "to_index": day_slots[0]["slot_index"],
                "from_anchor": boundary_name,
                "from_id": boundary["id"],
                "to_id": first_item.get("id"),
                **estimate_leg(
                    (float(boundary["lat"]), float(boundary["lng"])),
                    (float(first_item["lat"]), float(first_item["lng"])),
                ),
            })
        for previous, current in zip(day_slots, day_slots[1:]):
            from_item = previous["chosen"]
            to_item = current["chosen"]
            day_legs.append({
                "day_index": day.day_index,
                "from_index": previous["slot_index"],
                "to_index": current["slot_index"],
                "from_id": from_item.get("id"),
                "to_id": to_item.get("id"),
                **estimate_leg(
                    (float(from_item["lat"]), float(from_item["lng"])),
                    (float(to_item["lat"]), float(to_item["lng"])),
                ),
            })
        return_boundary = lodging_anchor if multi_day else (
            end_anchor if day.day_index == len(request.days) - 1 else None
        )
        return_name = "lodging" if multi_day else "end"
        if return_boundary and day_slots:
            last_item = day_slots[-1]["chosen"]
            day_legs.append({
                "day_index": day.day_index,
                "from_index": day_slots[-1]["slot_index"],
                "to_index": None,
                "to_anchor": return_name,
                "from_id": last_item.get("id"),
                "to_id": return_boundary["id"],
                **estimate_leg(
                    (float(last_item["lat"]), float(last_item["lng"])),
                    (float(return_boundary["lat"]), float(return_boundary["lng"])),
                ),
            })
        return_minutes = (
            int(day_legs[-1].get("duration_min") or 0)
            if day_legs and day_legs[-1].get("to_anchor") else 0
        )
        finish_min = (
            parse_hhmm(day_slots[-1]["end_time"]) + return_minutes
            if day_slots else day.start_min
        )
        day_total = {
            "end_time": fmt_hhmm(finish_min),
            "total_travel_min": sum_travel_min(day_legs),
            "total_activity_min": sum_activity_min(day_slots),
            "total_wait_min": int(
                (result.diagnostics.get("daily_wait_min") or [result.diagnostics.get("wait_min") or 0])[day.day_index]
            ) if day.day_index < len(result.diagnostics.get("daily_wait_min") or [0]) else 0,
        }
        day_blocks.append({
            "day_index": day.day_index,
            "date": day.date,
            "start_time": fmt_hhmm(day.start_min),
            "end_time_constraint": fmt_hhmm(day.end_min),
            "slots": day_slots,
            "legs": day_legs,
            "totals": day_total,
        })
        legs.extend(day_legs)
    day = request.days[0]
    finish_min = (
        parse_hhmm(day_blocks[-1]["totals"]["end_time"])
        if day_blocks else day.start_min
    )
    validation_status = "valid" if result.status == "feasible" else ("partial" if slots else "invalid")
    return {
        "location": request.location.resolved_name or request.location.query,
        "start_time": fmt_hhmm(day.start_min),
        "end_time_constraint": fmt_hhmm(day.end_min),
        "service_date": day.date,
        "timezone": request.location.timezone,
        "budget": request.budget.__dict__,
        "revision": revision,
        "planning_status": "feasible" if result.status == "feasible" else "needs_refinement",
        "problem_summary": {
            "schema_version": request.schema_version,
            "day_index": day.day_index,
            "date": day.date,
            "start_min": day.start_min,
            "end_min": day.end_min,
            "pace": request.soft_preferences.get("pace", "balanced"),
            "style": request.soft_preferences.get("style", "sightseeing"),
            "meal_obligations": list(request.hard_constraints.get("meal_obligations") or []),
            "horizon_days": len(request.days),
            "night_count": request.lodging.nights if request.lodging else 0,
            "budget_scope": request.budget.scope,
        },
        "planning_request": request.to_dict(),
        "anchors": {
            "start": start_anchor,
            "end": end_anchor,
            "lodging": lodging_anchor,
            "shared": bool(
                start_anchor and end_anchor
                and request.anchors.get("start") == request.anchors.get("end")
            ),
            "policy": request.hard_constraints.get("anchor_policy", "round_trip"),
        },
        "lodging": selected_lodging,
        "cost_summary": dict(result.cost_summary),
        "uncertainties": list(result.uncertainties),
        "solver": dict(result.diagnostics),
        "optimizer": dict(result.diagnostics),
        "days": day_blocks,
        "slots": slots,
        "legs": legs,
        "totals": {
            "end_time": fmt_hhmm(finish_min),
            "total_travel_min": sum_travel_min(legs),
            "total_activity_min": sum_activity_min(slots),
            "total_wait_min": int(result.diagnostics.get("wait_min") or 0),
            "day_count": len(request.days),
        },
        "validation": {
            "status": validation_status,
            "violations": list(result.unsatisfied_constraints),
            "warnings": list(result.uncertainties)[:12],
            "checks": {"chosen_stops": len(slots), "required_stops": len(slots)},
        },
    }


async def resolve_itinerary_legs(block: Dict[str, Any], resolver: Any) -> Dict[str, Any]:
    """Resolve and propagate transport independently inside each service day."""
    updated = copy.deepcopy(block)
    anchors = updated.get("anchors") if isinstance(updated.get("anchors"), dict) else {}

    def geo(item: Any) -> Optional[Tuple[float, float]]:
        if not isinstance(item, dict):
            return None
        try:
            return float(item["lat"]), float(item["lng"])
        except (KeyError, TypeError, ValueError):
            return None

    async def resolve_one(
        leg: Dict[str, Any],
        day: Dict[str, Any],
        slots_by_index: Dict[int, Dict[str, Any]],
        depart_min: int,
    ) -> Dict[str, Any]:
        if leg.get("source") != "estimate":
            return dict(leg)
        from_item = (
            anchors.get(str(leg.get("from_anchor")))
            if leg.get("from_anchor") else (slots_by_index.get(leg.get("from_index"), {}).get("chosen"))
        )
        to_item = (
            anchors.get(str(leg.get("to_anchor")))
            if leg.get("to_anchor") else (slots_by_index.get(leg.get("to_index"), {}).get("chosen"))
        )
        from_geo, to_geo = geo(from_item), geo(to_item)
        if from_geo is None or to_geo is None:
            return dict(leg)
        kwargs = {
            "depart_hhmm": fmt_hhmm(depart_min),
            "service_date": day.get("date"),
            "timezone": str(updated.get("timezone") or "Asia/Singapore"),
        }
        try:
            parameters = inspect.signature(resolver).parameters.values()
            accepts_kwargs = any(parameter.kind == parameter.VAR_KEYWORD for parameter in parameters)
            accepted = {parameter.name for parameter in parameters}
            if not accepts_kwargs:
                kwargs = {key: value for key, value in kwargs.items() if key in accepted}
        except (TypeError, ValueError):
            pass
        resolved = resolver(from_geo, to_geo, **kwargs)
        if inspect.isawaitable(resolved):
            resolved = await resolved
        return {
            "day_index": day.get("day_index"),
            "from_index": leg.get("from_index"),
            "to_index": leg.get("to_index"),
            **({"from_anchor": leg["from_anchor"]} if leg.get("from_anchor") else {}),
            **({"to_anchor": leg["to_anchor"]} if leg.get("to_anchor") else {}),
            "from_id": leg.get("from_id"),
            "to_id": leg.get("to_id"),
            **dict(resolved or {}),
        }

    flattened_legs: List[Dict[str, Any]] = []
    days = updated.get("days") or []
    for day in days:
        day_slots = day.get("slots") or []
        slots_by_index = {int(slot["slot_index"]): slot for slot in day_slots}
        incoming = {leg.get("to_index"): leg for leg in day.get("legs") or [] if leg.get("to_index") is not None}
        terminal = next((leg for leg in day.get("legs") or [] if leg.get("to_anchor")), None)
        current = parse_hhmm(day.get("start_time") or updated.get("start_time"))
        resolved_legs: List[Dict[str, Any]] = []
        for slot in day_slots:
            leg = incoming.get(slot.get("slot_index"))
            if leg is not None:
                resolved = await resolve_one(leg, day, slots_by_index, current)
                resolved_legs.append(resolved)
                current += int(resolved.get("duration_min") or 0)
            preferred = parse_hhmm(slot.get("preferred_time") or slot.get("time"))
            current = max(current, preferred)
            slot["time"] = fmt_hhmm(current)
            current += int(slot.get("dwell_min") or 0)
            slot["end_time"] = fmt_hhmm(current)
        if terminal is not None:
            resolved = await resolve_one(terminal, day, slots_by_index, current)
            resolved_legs.append(resolved)
            current += int(resolved.get("duration_min") or 0)
        day["legs"] = resolved_legs
        day["totals"] = {
            "end_time": fmt_hhmm(current),
            "total_travel_min": sum_travel_min(resolved_legs),
            "total_activity_min": sum_activity_min(day_slots),
            "total_wait_min": int((day.get("totals") or {}).get("total_wait_min") or 0),
        }
        flattened_legs.extend(resolved_legs)
    updated["legs"] = flattened_legs
    if days:
        updated["totals"] = {
            "end_time": days[-1]["totals"]["end_time"],
            "total_travel_min": sum(day["totals"]["total_travel_min"] for day in days),
            "total_activity_min": sum(day["totals"]["total_activity_min"] for day in days),
            "total_wait_min": sum(day["totals"]["total_wait_min"] for day in days),
            "day_count": len(days),
        }
    return updated


def candidates_from_block(block: Dict[str, Any]) -> List[PlanningCandidate]:
    """Rebuild the bounded persisted candidate pool for solver-aware refine."""
    candidates: List[PlanningCandidate] = []
    seen: set[str] = set()
    for slot in block.get("slots") or []:
        entries = [(slot.get("chosen"), slot)] + [(item, item) for item in slot.get("alternates") or []]
        for item, evidence in entries:
            if not isinstance(item, dict):
                continue
            candidate_id = str(item.get("id") or "").strip()
            if not candidate_id or candidate_id in seen:
                continue
            try:
                latitude, longitude = float(item["lat"]), float(item["lng"])
            except (KeyError, TypeError, ValueError):
                continue
            duration = evidence.get("duration") if isinstance(evidence.get("duration"), dict) else {}
            cost = evidence.get("cost") if isinstance(evidence.get("cost"), dict) else {}
            availability = evidence.get("availability") if isinstance(evidence.get("availability"), dict) else {}
            windows = []
            for window in availability.get("windows") or []:
                if isinstance(window, dict):
                    try:
                        windows.append(AvailabilityWindow(**window))
                    except TypeError:
                        pass
            preferred = int(duration.get("preferred") or evidence.get("dwell_min") or 90)
            domain = str(item.get("domain") or slot.get("domain") or "attraction")
            legacy_role = {"attraction": "experience", "restaurant": "food", "hotel": "lodging"}.get(domain, "unknown")
            candidates.append(PlanningCandidate(
                id=candidate_id,
                domain=domain,
                title=str(item.get("title") or slot.get("label") or "Untitled"),
                latitude=latitude,
                longitude=longitude,
                duration=DurationEstimate(
                    int(duration.get("min") or preferred), preferred,
                    int(duration.get("max") or preferred),
                    str(duration.get("source") or "rule"),
                    float(duration.get("confidence") or 0.5),
                ),
                cost=CostEstimate(
                    float(cost["min"]) if cost.get("min") is not None else None,
                    float(cost["max"]) if cost.get("max") is not None else None,
                    str(cost.get("currency") or "") or None,
                    source=str(cost.get("source") or "unknown"),
                ),
                availability_windows=tuple(windows),
                availability_known=bool(availability.get("known")),
                meal_coverage=tuple(evidence.get("meal_coverage") or ()),
                provider_relevance=max(0.0, 1.0 - len(candidates) * 0.03),
                rating=float(item["rating"]) if item.get("rating") is not None else None,
                source=str(item.get("source") or "") or None,
                role=str(item.get("role") or legacy_role),
                role_source=str(item.get("role_source") or "persisted_compat"),
                is_compound=bool(item.get("is_compound")),
                parent_id=str(item.get("parent_id") or "") or None,
                access=str(item.get("access") or "independent"),
                containment_source=str(item.get("containment_source") or "persisted_compat"),
                item=dict(item),
            ))
            seen.add(candidate_id)
    return candidates


def apply_transport_cost(block: Dict[str, Any]) -> None:
    """Merge known leg fares into the per-person cost interval in place."""
    summary = block.get("cost_summary") or {}
    currency = str(summary.get("currency") or "").upper()
    transport = 0.0
    unknown = False
    for leg in block.get("legs") or []:
        if leg.get("mode") == "walk":
            continue
        fare = str(leg.get("fare") or "")
        match = re.search(r"([0-9]+(?:\.[0-9]+)?)", fare)
        if not match:
            unknown = True
            continue
        if currency and fare and currency not in fare.upper():
            unknown = True
            continue
        transport += float(match.group(1))
    summary["transport"] = round(transport, 2)
    summary["min"] = round(float(summary.get("min") or 0) + transport, 2)
    if summary.get("max") is not None and not unknown:
        summary["max"] = round(float(summary["max"]) + transport, 2)
    elif unknown:
        summary["max"] = None
        summary["budget_status"] = "indeterminate" if summary.get("budget_limit") is not None else summary.get("budget_status")
        uncertainty = {"code": "transport_cost_unknown"}
        if uncertainty not in block.setdefault("uncertainties", []):
            block["uncertainties"].append(uncertainty)
    block["cost_summary"] = summary
    if summary.get("budget_status") == "indeterminate":
        block["planning_status"] = "needs_refinement"
        block["validation"]["status"] = "partial"


def exceeds_time_window(block: Dict[str, Any], request: ItineraryPlanningRequest) -> bool:
    days = block.get("days") or []
    if days:
        constraints = {day.day_index: day for day in request.days}
        for day in days:
            constraint = constraints.get(int(day.get("day_index") or 0))
            if constraint is None:
                return True
            try:
                end_min = parse_hhmm((day.get("totals") or {}).get("end_time"))
            except (TypeError, ValueError):
                return True
            if end_min > constraint.end_min:
                return True
        return False
    try:
        return parse_hhmm((block.get("totals") or {}).get("end_time")) > request.days[0].end_min
    except (TypeError, ValueError):
        return True


def finalize_dynamic_metadata(
    block: Dict[str, Any],
    request: ItineraryPlanningRequest,
    result: SolverResult,
) -> None:
    """Restore dynamic semantics after legacy ETA schedule propagation."""
    for slot in block.get("slots") or []:
        start_text = str(slot.get("time") or "")
        try:
            hour, minute = (int(part) for part in start_text.split(":", 1))
            slot["end_time"] = fmt_hhmm(hour * 60 + minute + int(slot.get("dwell_min") or 0))
        except (TypeError, ValueError):
            slot["end_time"] = None
    daily_wait = list(result.diagnostics.get("daily_wait_min") or [])
    for day in block.get("days") or []:
        day_index = int(day.get("day_index") or 0)
        day_totals = day.setdefault("totals", {})
        day_totals["total_activity_min"] = sum_activity_min(day.get("slots") or [])
        day_totals["total_travel_min"] = sum_travel_min(day.get("legs") or [])
        day_totals["total_wait_min"] = (
            int(daily_wait[day_index]) if day_index < len(daily_wait) else 0
        )
    totals = block.setdefault("totals", {})
    totals["total_activity_min"] = sum_activity_min(block.get("slots") or [])
    totals["total_travel_min"] = sum_travel_min(block.get("legs") or [])
    totals["total_wait_min"] = int(result.diagnostics.get("wait_min") or 0)
    totals["day_count"] = len(request.days)
    violations = list(result.unsatisfied_constraints)
    constraints = {day.day_index: day for day in request.days}
    for day in block.get("days") or [{"day_index": 0, "totals": totals}]:
        day_index = int(day.get("day_index") or 0)
        constraint = constraints.get(day_index)
        try:
            end_min = parse_hhmm((day.get("totals") or {}).get("end_time"))
        except (TypeError, ValueError):
            end_min = 24 * 60
        if constraint is not None and end_min > constraint.end_min:
            violations.append({
                "code": "time_window_exceeded",
                "day_index": day_index,
                "end_time": (day.get("totals") or {}).get("end_time"),
                "limit": fmt_hhmm(constraint.end_min),
            })
    block["uncertainties"] = list(result.uncertainties)
    block["planning_status"] = "feasible" if result.status == "feasible" and not violations else "needs_refinement"
    block["validation"] = {
        "status": "valid" if block["planning_status"] == "feasible" else ("partial" if block.get("slots") else "invalid"),
        "violations": violations,
        "warnings": list(result.uncertainties)[:12],
        "checks": {
            "chosen_stops": len(block.get("slots") or []),
            "required_stops": len(block.get("slots") or []),
            "time_window_end": fmt_hhmm(request.days[-1].end_min),
        },
    }
