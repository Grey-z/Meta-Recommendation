from dataclasses import replace

import pytest

from langgraph_metarec.itinerary_candidates import normalize_candidates
from langgraph_metarec.itinerary_contracts import (
    AvailabilityWindow,
    BudgetConstraint,
    CostEstimate,
    DayConstraint,
    DurationEstimate,
    ItineraryPlanningRequest,
    LocationConstraint,
    LodgingRequirement,
    PlanningCandidate,
    PlanningProblem,
    planning_request_from_preferences,
)
from langgraph_metarec.itinerary_lodging import build_lodging_scenarios
from langgraph_metarec.itinerary_solver import BeamItinerarySolver

pytestmark = pytest.mark.backend_unit


def _request(*, budget=1000):
    return ItineraryPlanningRequest(
        location=LocationConstraint("Singapore", timezone="Asia/Singapore"),
        days=(
            DayConstraint(0, "2026-08-01", 540, 1080),
            DayConstraint(1, "2026-08-02", 540, 1080),
            DayConstraint(2, "2026-08-03", 540, 1080),
        ),
        budget=BudgetConstraint("limited", budget, "SGD", scope="trip_total", include_lodging=True),
        lodging=LodgingRequirement("recommend", "2026-08-01", "2026-08-03", 2, 2, 1),
        hard_constraints={"travelers": 2, "rooms": 1, "meal_obligations": []},
    )


def _activity(day_index=0):
    identifier = f"museum-{day_index}"
    return PlanningCandidate(
        identifier, "attraction", f"Museum {day_index}", 1.30, 103.80,
        DurationEstimate(60, 60, 60, "provider", 1.0),
        CostEstimate(10, 10, "SGD", ("admission",), "provider", 1.0),
        availability_windows=(AvailabilityWindow(day_index, 0, 1440),),
        availability_known=True,
        role="experience",
        item={"id": identifier, "domain": "attraction", "title": f"Museum {day_index}", "lat": 1.30, "lng": 103.80},
    )


def test_provider_nightly_price_becomes_per_person_trip_cost_and_stable_scenarios():
    request = _request()
    hotels = normalize_candidates([
        {
            "id": "hotel-b", "domain": "hotel", "title": "Hotel B", "rating": 4.2,
            "tags": ["hotel"], "gps_coordinates": {"latitude": 1.31, "longitude": 103.81},
            "raw": {"price": "SGD 300-360"},
        },
        {
            "id": "hotel-a", "domain": "hotel", "title": "Hotel A", "rating": 4.8,
            "tags": ["hotel"], "gps_coordinates": {"latitude": 1.32, "longitude": 103.82},
            "raw": {"price": "SGD 300-360"},
        },
        {
            "id": "hotel-unknown", "domain": "hotel", "title": "Hotel Unknown", "rating": 5,
            "tags": ["hotel"], "gps_coordinates": {"latitude": 1.33, "longitude": 103.83},
        },
    ], request)

    scenarios = build_lodging_scenarios(hotels, request)
    assert [scenario.candidate_id for scenario in scenarios] == ["hotel-a", "hotel-b", "hotel-unknown"]
    assert scenarios[0].nightly_cost.components == ("lodging_nightly_per_room",)
    assert scenarios[0].trip_cost_per_person.min == 300
    assert scenarios[0].trip_cost_per_person.max == 360
    assert scenarios[-1].trip_cost_per_person.max is None


def test_solver_charges_lodging_and_rejects_certain_over_budget_scenario():
    request = _request(budget=350)
    hotels = normalize_candidates([{
        "id": "hotel", "domain": "hotel", "title": "Shared Hotel", "rating": 4.5,
        "tags": ["hotel"], "gps_coordinates": {"latitude": 1.31, "longitude": 103.81},
        "raw": {"price": "SGD 300-360"},
    }], request)
    scenarios = tuple(build_lodging_scenarios(hotels, request))
    activities = tuple(_activity(day_index) for day_index in range(3))
    result = BeamItinerarySolver().solve(PlanningProblem(request, activities, {}, scenarios))

    assert result.lodging["candidate_id"] == "hotel"
    assert result.cost_summary["min"] == 330
    assert result.cost_summary["budget_status"] == "indeterminate"

    over_budget = replace(request, budget=replace(request.budget, amount=250))
    rejected = BeamItinerarySolver().solve(PlanningProblem(over_budget, activities, {}, scenarios))
    assert rejected.status == "infeasible"
    assert rejected.unsatisfied_constraints[0]["code"] == "lodging_unavailable_or_over_budget"


def test_supplied_multi_day_hotel_is_a_lodging_boundary_not_final_anchor():
    request, errors = planning_request_from_preferences({
        "location": "Sentosa",
        "date": "2026-08-01",
        "horizon_days": 2,
        "daily_start_time": "09:00",
        "daily_end_time": "19:00",
        "timezone": "Asia/Singapore",
        "budget_mode": "unlimited",
        "travelers": 2,
        "rooms": 1,
        "lodging_mode": "supplied",
        "hotel_anchor": "Beach Hotel",
        "anchor_policy": "start_only",
        "resolved_anchors": {
            "start": {
                "query": "Beach Hotel", "resolved_name": "Beach Hotel",
                "latitude": 1.25, "longitude": 103.82, "provider_id": "hotel-1",
            },
        },
    })

    assert errors == [] and request is not None
    assert request.anchors["start"] == request.anchors["lodging"]
    assert "end" not in request.anchors
    scenario = build_lodging_scenarios([], request)[0]
    assert scenario.candidate_id == "hotel-1"
    assert scenario.trip_cost_per_person.max is None
