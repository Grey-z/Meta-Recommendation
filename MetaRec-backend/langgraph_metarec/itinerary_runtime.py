"""Conversion helpers between dynamic solver output and the public itinerary block."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Sequence

from langgraph_metarec.eta import estimate_leg
from langgraph_metarec.itinerary_contracts import (
    AvailabilityWindow,
    CostEstimate,
    DurationEstimate,
    ItineraryPlanningRequest,
    PlanningCandidate,
    SolverResult,
)


def fmt_hhmm(minutes: int) -> str:
    return f"{(int(minutes) // 60) % 24:02d}:{int(minutes) % 60:02d}"


def build_travel_matrix(candidates: Sequence[PlanningCandidate]) -> Dict[str, Dict[str, int]]:
    matrix: Dict[str, Dict[str, int]] = {}
    for source in candidates:
        matrix[source.id] = {}
        for target in candidates:
            if source.id == target.id:
                continue
            leg = estimate_leg((source.latitude, source.longitude), (target.latitude, target.longitude))
            matrix[source.id][target.id] = max(0, int(leg.get("duration_min") or 0))
    return matrix


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
            if other.domain == candidate.domain and other.id not in selected_ids
        ][:4]
        slots.append({
            "slot_index": index,
            "day_index": 0,
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
            "availability": {
                "known": candidate.availability_known,
                "windows": [window.__dict__ for window in candidate.availability_windows],
            },
            "chosen": dict(candidate.item),
            "alternates": alternates,
        })
    legs: List[Dict[str, Any]] = []
    for previous, current in zip(slots, slots[1:]):
        from_item = previous["chosen"]
        to_item = current["chosen"]
        legs.append({
            "from_index": previous["slot_index"],
            "to_index": current["slot_index"],
            "from_id": from_item.get("id"),
            "to_id": to_item.get("id"),
            **estimate_leg((float(from_item["lat"]), float(from_item["lng"])), (float(to_item["lat"]), float(to_item["lng"]))),
        })
    day = request.days[0]
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
            "meal_obligations": list(request.hard_constraints.get("meal_obligations") or []),
        },
        "planning_request": request.to_dict(),
        "cost_summary": dict(result.cost_summary),
        "uncertainties": list(result.uncertainties),
        "solver": dict(result.diagnostics),
        "optimizer": dict(result.diagnostics),
        "slots": slots,
        "legs": legs,
        "totals": {
            "end_time": fmt_hhmm(int(result.activities[-1]["end_min"])) if result.activities else fmt_hhmm(day.start_min),
            "total_travel_min": sum(int(leg.get("duration_min") or 0) for leg in legs),
            "total_activity_min": sum(int(slot.get("dwell_min") or 0) for slot in slots),
            "total_wait_min": int(result.diagnostics.get("wait_min") or 0),
        },
        "validation": {
            "status": validation_status,
            "violations": list(result.unsatisfied_constraints),
            "warnings": list(result.uncertainties)[:12],
            "checks": {"chosen_stops": len(slots), "required_stops": len(slots)},
        },
    }


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
            candidates.append(PlanningCandidate(
                id=candidate_id,
                domain=str(item.get("domain") or slot.get("domain") or "attraction"),
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
    end_text = str((block.get("totals") or {}).get("end_time") or "")
    try:
        hour, minute = (int(part) for part in end_text.split(":", 1))
    except (TypeError, ValueError):
        return True
    return hour * 60 + minute > request.days[0].end_min


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
    totals = block.setdefault("totals", {})
    totals["total_activity_min"] = sum(int(slot.get("dwell_min") or 0) for slot in block.get("slots") or [])
    totals["total_wait_min"] = int(result.diagnostics.get("wait_min") or 0)
    violations = list(result.unsatisfied_constraints)
    if exceeds_time_window(block, request):
        violations.append({
            "code": "time_window_exceeded",
            "end_time": totals.get("end_time"),
            "limit": fmt_hhmm(request.days[0].end_min),
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
            "time_window_end": fmt_hhmm(request.days[0].end_min),
        },
    }
