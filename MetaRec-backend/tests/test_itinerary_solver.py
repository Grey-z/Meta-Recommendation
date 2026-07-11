from dataclasses import replace

import pytest

from langgraph_metarec.itinerary_contracts import (
    AvailabilityWindow,
    BudgetConstraint,
    CostEstimate,
    DayConstraint,
    DurationEstimate,
    ItineraryPlanningRequest,
    LocationConstraint,
    PlanningCandidate,
    PlanningProblem,
)
from langgraph_metarec.itinerary_solver import BeamItinerarySolver, build_solver

pytestmark = pytest.mark.backend_unit


def _request(*, end=1080, budget=150, meals=(), must=(), pace="balanced"):
    return ItineraryPlanningRequest(
        location=LocationConstraint("Singapore", timezone="Asia/Singapore"),
        days=(DayConstraint(0, "2026-08-03", 540, end),),
        budget=BudgetConstraint("limited", budget, "SGD") if budget is not None else BudgetConstraint("unlimited"),
        hard_constraints={"meal_obligations": list(meals), "must_visit": list(must)},
        soft_preferences={"pace": pace},
    )


def _candidate(identifier, *, domain="attraction", duration=60, cost=10, known=True, meals=(), relevance=0.8):
    return PlanningCandidate(
        id=identifier, domain=domain, title=identifier, latitude=1.3, longitude=103.8,
        duration=DurationEstimate(duration, duration, duration, "provider", 0.95),
        cost=CostEstimate(cost, cost, "SGD", ("admission",), "provider", 0.9),
        availability_windows=(AvailabilityWindow(0, 0, 1440),) if known else (),
        availability_known=known, meal_coverage=tuple(meals), provider_relevance=relevance,
        item={"id": identifier, "title": identifier, "domain": domain, "lat": 1.3, "lng": 103.8},
    )


def test_dynamic_solver_chooses_multiple_short_stops_without_fixed_slots():
    candidates = tuple(_candidate(f"p{i}", duration=60, relevance=1 - i * 0.05) for i in range(4))
    matrix = {a.id: {b.id: 15 for b in candidates if b.id != a.id} for a in candidates}
    result = BeamItinerarySolver().solve(PlanningProblem(_request(end=900, budget=None), candidates, matrix))
    assert result.status == "feasible"
    assert len(result.activities) >= 3
    assert [item["candidate_id"] for item in result.activities] == sorted(
        [item["candidate_id"] for item in result.activities]
    )


def test_compound_full_day_poi_satisfies_lunch_without_restaurant():
    universal = _candidate("uss", duration=510, cost=None, meals=("lunch",), known=True)
    universal = replace(universal, cost=CostEstimate(None, None, None))
    result = BeamItinerarySolver().solve(PlanningProblem(
        _request(end=1080, budget=200, meals=("lunch",), must=("uss",)),
        (universal,),
    ))
    assert result.status == "indeterminate"
    assert [item["candidate_id"] for item in result.activities] == ["uss"]
    assert result.cost_summary["budget_status"] == "indeterminate"


def test_budget_feasible_infeasible_and_unknown_are_distinct():
    known = _candidate("known", cost=30)
    feasible = BeamItinerarySolver().solve(PlanningProblem(_request(budget=50), (known,)))
    assert feasible.cost_summary["budget_status"] == "feasible"
    too_expensive = BeamItinerarySolver().solve(PlanningProblem(_request(budget=20, must=("known",)), (known,)))
    assert too_expensive.status == "infeasible"
    unknown = replace(known, id="unknown", title="unknown", cost=CostEstimate(None, None, None))
    uncertain = BeamItinerarySolver().solve(PlanningProblem(_request(budget=50), (unknown,)))
    assert uncertain.status == "indeterminate"


def test_opening_window_adds_wait_and_stable_tie_breaking():
    later = replace(_candidate("a"), availability_windows=(AvailabilityWindow(0, 600, 800),))
    peer = replace(_candidate("b"), availability_windows=(AvailabilityWindow(0, 600, 800),))
    problem = PlanningProblem(_request(end=800, budget=None), (peer, later), {"a": {"b": 10}, "b": {"a": 10}})
    first = BeamItinerarySolver().solve(problem)
    second = BeamItinerarySolver().solve(problem)
    assert first.activities == second.activities
    assert first.activities[0]["start_min"] == 600
    assert first.diagnostics["wait_min"] == 60


def test_solver_factory_keeps_future_adapter_boundary_explicit():
    assert isinstance(build_solver("beam"), BeamItinerarySolver)
    with pytest.raises(ValueError):
        build_solver("milp")
