"""Deterministic lodging scenario construction for multi-day planning."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from langgraph_metarec.itinerary_contracts import (
    CostEstimate,
    ItineraryPlanningRequest,
    LodgingScenario,
    PlanningCandidate,
)


def build_lodging_scenarios(
    candidates: Sequence[PlanningCandidate],
    request: ItineraryPlanningRequest,
    *,
    limit: int = 3,
) -> List[LodgingScenario]:
    requirement = request.lodging
    if requirement is None or requirement.nights <= 0:
        return []
    scenarios: List[LodgingScenario] = []
    supplied = request.anchors.get("lodging")
    if requirement.mode == "supplied" and supplied is not None:
        try:
            supplied_lat = float(supplied.latitude)
            supplied_lng = float(supplied.longitude)
        except (TypeError, ValueError):
            supplied = None
        if supplied is not None:
            unknown = CostEstimate(
                None, None, request.budget.currency, ("lodging",), "unknown", 0.0
            )
            scenarios.append(LodgingScenario(
                candidate_id=str(supplied.provider_id or "anchor:lodging"),
                title=str(supplied.resolved_name or supplied.query),
                latitude=supplied_lat,
                longitude=supplied_lng,
                address=supplied.address,
                source=supplied.source,
                nightly_cost=unknown,
                trip_cost_per_person=unknown,
                provider_relevance=1.0,
                item={
                    "id": str(supplied.provider_id or "anchor:lodging"),
                    "domain": "hotel",
                    "title": str(supplied.resolved_name or supplied.query),
                    "subtitle": supplied.address,
                    "lat": supplied_lat,
                    "lng": supplied_lng,
                    "source": supplied.source,
                    "role": "lodging",
                },
            ))
    for candidate in candidates:
        if candidate.domain != "hotel" or candidate.role != "lodging":
            continue
        nightly = candidate.cost
        if nightly.min is None or nightly.max is None:
            trip_cost = CostEstimate(
                None, None, nightly.currency, ("lodging",), nightly.source, nightly.confidence
            )
        else:
            divisor = max(1, requirement.travelers)
            multiplier = requirement.rooms * requirement.nights / divisor
            trip_cost = CostEstimate(
                round(float(nightly.min) * multiplier, 2),
                round(float(nightly.max) * multiplier, 2),
                nightly.currency,
                ("lodging",),
                nightly.source,
                nightly.confidence,
            )
        scenarios.append(LodgingScenario(
            candidate_id=candidate.id,
            title=candidate.title,
            latitude=candidate.latitude,
            longitude=candidate.longitude,
            address=str(candidate.item.get("subtitle") or "") or None,
            source=candidate.source,
            nightly_cost=nightly,
            trip_cost_per_person=trip_cost,
            rating=candidate.rating,
            provider_relevance=candidate.provider_relevance,
            item=dict(candidate.item),
        ))

    budget = request.budget.amount if request.budget.mode == "limited" else None
    currency = str(request.budget.currency or "").upper()

    def key(scenario: LodgingScenario):
        cost = scenario.trip_cost_per_person
        if cost.min is None or cost.max is None or (currency and str(cost.currency or "").upper() != currency):
            budget_rank = 1
        elif budget is not None and float(cost.min) > float(budget):
            budget_rank = 2
        else:
            budget_rank = 0
        quality = max(0.0, min(5.0, float(scenario.rating or 0.0))) / 5.0
        return (
            budget_rank,
            -round(0.85 * quality + 0.15 * scenario.provider_relevance, 6),
            scenario.candidate_id,
        )

    return sorted(scenarios, key=key)[:max(1, min(int(limit), 3))]


def lodging_scenario_from_block(block: Dict[str, Any]) -> Optional[LodgingScenario]:
    """Restore the selected scenario needed by solver-aware persisted refine."""
    value = block.get("lodging")
    if not isinstance(value, dict):
        return None

    def cost(name: str) -> CostEstimate:
        row = value.get(name) if isinstance(value.get(name), dict) else {}
        return CostEstimate(
            float(row["min"]) if row.get("min") is not None else None,
            float(row["max"]) if row.get("max") is not None else None,
            str(row.get("currency") or "") or None,
            tuple(row.get("components") or ()),
            str(row.get("source") or "unknown"),
            float(row.get("confidence") or 0.0),
        )

    try:
        return LodgingScenario(
            candidate_id=str(value["candidate_id"]),
            title=str(value.get("title") or "Shared hotel"),
            latitude=float(value["latitude"]),
            longitude=float(value["longitude"]),
            address=str(value.get("address") or "") or None,
            source=str(value.get("source") or "") or None,
            nightly_cost=cost("nightly_cost"),
            trip_cost_per_person=cost("trip_cost_per_person"),
            rating=float(value["rating"]) if value.get("rating") is not None else None,
            provider_relevance=float(value.get("provider_relevance") or 0.0),
            item=dict(value.get("item") or {}),
        )
    except (KeyError, TypeError, ValueError):
        return None
