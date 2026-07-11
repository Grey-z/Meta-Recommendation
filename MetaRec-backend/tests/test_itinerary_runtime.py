import pytest

from langgraph_metarec.itinerary_contracts import (
    BudgetConstraint,
    CostEstimate,
    DayConstraint,
    DurationEstimate,
    ItineraryPlanningRequest,
    LocationConstraint,
    PlanningCandidate,
    SolverResult,
)
from langgraph_metarec.itinerary_runtime import (
    apply_transport_cost,
    build_itinerary_block,
    finalize_dynamic_metadata,
)

pytestmark = pytest.mark.backend_unit


def _request():
    return ItineraryPlanningRequest(
        LocationConstraint("Singapore", timezone="Asia/Singapore"),
        (DayConstraint(0, "2026-08-03", 540, 720),),
        BudgetConstraint("limited", 50, "SGD"),
    )


def _candidate(identifier, lat):
    return PlanningCandidate(
        identifier, "attraction", identifier, lat, 103.8,
        DurationEstimate(30, 30, 30, "provider", 1),
        CostEstimate(5, 5, "SGD", ("admission",), "provider", 1),
        item={"id": identifier, "title": identifier, "domain": "attraction", "lat": lat, "lng": 103.8},
    )


def test_public_block_has_no_invented_first_or_last_anchor_leg():
    candidates = (_candidate("a", 1.30), _candidate("b", 1.31))
    result = SolverResult(
        "feasible",
        (
            {"candidate_id": "a", "start_min": 540, "end_min": 570, "duration": {}, "cost": {}, "meal_coverage": []},
            {"candidate_id": "b", "start_min": 600, "end_min": 630, "duration": {}, "cost": {}, "meal_coverage": []},
        ),
        {"min": 10, "max": 10, "currency": "SGD", "budget_limit": 50, "budget_status": "feasible"},
    )
    block = build_itinerary_block(_request(), result, candidates)
    assert len(block["legs"]) == 1
    assert block["legs"][0]["from_id"] == "a" and block["legs"][0]["to_id"] == "b"


def test_transport_cost_and_time_violation_restore_dynamic_projection():
    candidate = _candidate("a", 1.30)
    result = SolverResult(
        "feasible",
        ({"candidate_id": "a", "start_min": 690, "end_min": 720, "duration": {}, "cost": {}, "meal_coverage": []},),
        {"min": 5, "max": 5, "currency": "SGD", "budget_limit": 50, "budget_status": "feasible"},
    )
    block = build_itinerary_block(_request(), result, (candidate,))
    block["totals"]["end_time"] = "12:30"
    block["legs"] = [{"mode": "pt", "fare": "1.20 SGD"}, {"mode": "drive"}]
    finalize_dynamic_metadata(block, _request(), result)
    apply_transport_cost(block)
    assert block["validation"]["violations"][0]["code"] == "time_window_exceeded"
    assert block["cost_summary"]["min"] == 6.2
    assert block["cost_summary"]["max"] is None
    assert block["planning_status"] == "needs_refinement"
