"""Client-safe, bounded live projections for itinerary task progress."""
from __future__ import annotations

from typing import Any, Dict, Optional, Sequence

from langgraph_metarec.itinerary_contracts import ItineraryPlanningRequest, PlanningCandidate

SNAPSHOT_SCHEMA_VERSION = "itinerary-planning-snapshot/v1"
MAX_CONFIRMED_NODES = 24
MAX_FRONTIER_NODES = 24
MAX_EDGES = 48
MAX_RETIRED_IDS = 24


def _text(value: Any, limit: int = 120) -> str:
    return str(value or "")[:limit]


def _node_from_candidate(candidate: PlanningCandidate, status: str) -> Dict[str, Any]:
    return {
        "id": _text(candidate.id, 160),
        "title": _text(candidate.title),
        "domain": _text(candidate.domain, 32),
        "role": _text(candidate.role, 32),
        "status": status,
        "lat": round(float(candidate.latitude), 6),
        "lng": round(float(candidate.longitude), 6),
    }


def build_planning_snapshot(
    *,
    revision: int,
    phase: str,
    request: ItineraryPlanningRequest,
    candidates: Sequence[PlanningCandidate] = (),
    block: Optional[Dict[str, Any]] = None,
    round_index: Optional[int] = None,
    retired_ids: Sequence[str] = (),
    provider_calls: int = 0,
    provider_call_limit: int = 0,
) -> Dict[str, Any]:
    block = block if isinstance(block, dict) else {}
    selected_slots = block.get("slots") or []
    selected_ids = {
        str((slot.get("chosen") or {}).get("id") or "") for slot in selected_slots
        if isinstance(slot, dict)
    }
    confirmed = []
    for slot in selected_slots[:MAX_CONFIRMED_NODES]:
        chosen = slot.get("chosen") if isinstance(slot.get("chosen"), dict) else {}
        try:
            latitude, longitude = round(float(chosen["lat"]), 6), round(float(chosen["lng"]), 6)
        except (KeyError, TypeError, ValueError):
            latitude = longitude = None
        confirmed.append({
            "id": _text(chosen.get("id"), 160),
            "title": _text(chosen.get("title") or slot.get("label")),
            "domain": _text(chosen.get("domain") or slot.get("domain"), 32),
            "role": _text(chosen.get("role"), 32),
            "status": "confirmed",
            "day_index": int(slot.get("day_index") or 0),
            "time": _text(slot.get("time"), 8),
            "end_time": _text(slot.get("end_time"), 8),
            "lat": latitude,
            "lng": longitude,
        })
    frontier = [
        _node_from_candidate(candidate, "candidate")
        for candidate in candidates
        if candidate.id not in selected_ids and candidate.role != "lodging"
    ][:MAX_FRONTIER_NODES]
    lodging = block.get("lodging") if isinstance(block.get("lodging"), dict) else None
    if lodging:
        try:
            confirmed.insert(0, {
                "id": _text(lodging.get("candidate_id"), 160),
                "title": _text(lodging.get("title") or "Shared hotel"),
                "domain": "hotel",
                "role": "lodging",
                "status": "confirmed",
                "day_index": None,
                "lat": round(float(lodging["latitude"]), 6),
                "lng": round(float(lodging["longitude"]), 6),
            })
        except (KeyError, TypeError, ValueError):
            pass
    edges = [
        {
            "day_index": int(edge.get("day_index") or 0),
            "from_id": _text(edge.get("from_id"), 160),
            "to_id": _text(edge.get("to_id"), 160),
            "status": "estimated" if edge.get("source") == "estimate" else "provider",
            "mode": _text(edge.get("mode"), 24),
            "duration_min": max(0, int(edge.get("duration_min") or 0)),
            "coords": [
                [round(float(point[0]), 6), round(float(point[1]), 6)]
                for point in (edge.get("coords") or [])[:32]
                if isinstance(point, (list, tuple))
                and len(point) >= 2
                and isinstance(point[0], (int, float))
                and isinstance(point[1], (int, float))
                and -180 <= float(point[0]) <= 180
                and -90 <= float(point[1]) <= 90
            ],
        }
        for edge in (block.get("legs") or [])[:MAX_EDGES]
        if isinstance(edge, dict)
    ]
    day_rows = block.get("days") or [
        {
            "day_index": day.day_index,
            "date": day.date,
            "start_time": f"{day.start_min // 60:02d}:{day.start_min % 60:02d}",
            "end_time_constraint": f"{day.end_min // 60:02d}:{day.end_min % 60:02d}",
            "totals": {},
        }
        for day in request.days
    ]
    days = [
        {
            "day_index": int(day.get("day_index") or 0),
            "date": _text(day.get("date"), 16),
            "start_time": _text(day.get("start_time"), 8),
            "end_time_constraint": _text(day.get("end_time_constraint"), 8),
            "current_end_time": _text((day.get("totals") or {}).get("end_time"), 8),
            "activity_min": int((day.get("totals") or {}).get("total_activity_min") or 0),
            "travel_min": int((day.get("totals") or {}).get("total_travel_min") or 0),
            "wait_min": int((day.get("totals") or {}).get("total_wait_min") or 0),
        }
        for day in day_rows[:3]
        if isinstance(day, dict)
    ]
    cost = block.get("cost_summary") if isinstance(block.get("cost_summary"), dict) else {}
    budget_limit = request.budget.amount if request.budget.mode == "limited" else None
    maximum = cost.get("max")
    minimum = cost.get("min")
    remaining = {
        "min": round(float(budget_limit) - float(maximum), 2)
        if budget_limit is not None and maximum is not None else None,
        "max": round(float(budget_limit) - float(minimum), 2)
        if budget_limit is not None and minimum is not None else None,
    }
    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "revision": max(1, int(revision)),
        "phase": _text(phase, 48),
        "round": int(round_index) if round_index is not None else None,
        "planning_status": _text(block.get("planning_status"), 32) or "processing",
        "confirmed_nodes": confirmed[:MAX_CONFIRMED_NODES],
        "frontier_nodes": frontier,
        "retired_ids": [_text(value, 160) for value in retired_ids[:MAX_RETIRED_IDS]],
        "edges": edges,
        "days": days,
        "cost": {
            "min": minimum,
            "max": maximum,
            "currency": cost.get("currency") or request.budget.currency,
            "budget_limit": budget_limit,
            "remaining": remaining,
            "budget_status": _text(cost.get("budget_status"), 24),
        },
        "uncertainty_count": len(block.get("uncertainties") or []),
        "provider_calls": max(0, int(provider_calls)),
        "provider_call_limit": max(0, int(provider_call_limit)),
    }


def sanitize_planning_snapshot(
    value: Any,
    *,
    previous_revision: int = 0,
) -> Optional[Dict[str, Any]]:
    """Allowlist an emitted snapshot and reject stale/non-versioned updates."""
    if not isinstance(value, dict) or value.get("schema_version") != SNAPSHOT_SCHEMA_VERSION:
        return None
    try:
        revision = int(value.get("revision"))
    except (TypeError, ValueError):
        return None
    if revision <= previous_revision:
        return None

    def rows(name: str, limit: int, allowed: Sequence[str]) -> list[Dict[str, Any]]:
        output = []
        for row in value.get(name) or []:
            if not isinstance(row, dict):
                continue
            output.append({
                key: row.get(key)
                for key in allowed
                if key in row and isinstance(row.get(key), (str, int, float, bool, type(None)))
            })
            if len(output) >= limit:
                break
        return output

    def nonnegative_int(item: Any) -> int:
        try:
            return max(0, int(item or 0))
        except (TypeError, ValueError):
            return 0

    cost_value = value.get("cost") if isinstance(value.get("cost"), dict) else {}
    remaining_value = (
        cost_value.get("remaining") if isinstance(cost_value.get("remaining"), dict) else {}
    )
    cleaned_edges = rows(
        "edges", MAX_EDGES,
        ("day_index", "from_id", "to_id", "status", "mode", "duration_min"),
    )
    source_edges = [row for row in value.get("edges") or [] if isinstance(row, dict)][:MAX_EDGES]
    for cleaned, source in zip(cleaned_edges, source_edges):
        cleaned["coords"] = [
            [round(float(point[0]), 6), round(float(point[1]), 6)]
            for point in (source.get("coords") or [])[:32]
            if isinstance(point, (list, tuple))
            and len(point) >= 2
            and isinstance(point[0], (int, float))
            and isinstance(point[1], (int, float))
            and -180 <= float(point[0]) <= 180
            and -90 <= float(point[1]) <= 90
        ]
    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "revision": revision,
        "phase": _text(value.get("phase"), 48),
        "round": nonnegative_int(value.get("round")) if value.get("round") is not None else None,
        "planning_status": _text(value.get("planning_status"), 32),
        "confirmed_nodes": rows(
            "confirmed_nodes", MAX_CONFIRMED_NODES,
            ("id", "title", "domain", "role", "status", "day_index", "time", "end_time", "lat", "lng"),
        ),
        "frontier_nodes": rows(
            "frontier_nodes", MAX_FRONTIER_NODES,
            ("id", "title", "domain", "role", "status", "day_index", "lat", "lng"),
        ),
        "retired_ids": [_text(item, 160) for item in (value.get("retired_ids") or [])[:MAX_RETIRED_IDS]],
        "edges": cleaned_edges,
        "days": rows(
            "days", 3,
            ("day_index", "date", "start_time", "end_time_constraint", "current_end_time", "activity_min", "travel_min", "wait_min"),
        ),
        "cost": {
            "min": cost_value.get("min"),
            "max": cost_value.get("max"),
            "currency": _text(cost_value.get("currency"), 12),
            "budget_limit": cost_value.get("budget_limit"),
            "remaining": {
                "min": remaining_value.get("min"),
                "max": remaining_value.get("max"),
            },
            "budget_status": _text(cost_value.get("budget_status"), 24),
        },
        "uncertainty_count": nonnegative_int(value.get("uncertainty_count")),
        "provider_calls": nonnegative_int(value.get("provider_calls")),
        "provider_call_limit": nonnegative_int(value.get("provider_call_limit")),
    }
