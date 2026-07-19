from dataclasses import replace

import pytest

from langgraph_metarec.itinerary_contracts import (
    AvailabilityWindow,
    AnchorConstraint,
    BudgetConstraint,
    CostEstimate,
    DayConstraint,
    DurationEstimate,
    ItineraryPlanningRequest,
    LodgingRequirement,
    LodgingScenario,
    LocationConstraint,
    PlanningCandidate,
    PlanningProblem,
)
from langgraph_metarec.itinerary_solver import BeamItinerarySolver, PACE_MAX_STOPS, build_solver

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
        role="food" if domain == "restaurant" else "experience",
        item={"id": identifier, "title": identifier, "domain": domain, "lat": 1.3, "lng": 103.8},
    )


def test_dynamic_solver_determines_stop_count_without_fixed_slots():
    candidates = tuple(_candidate(f"p{i}", duration=60, relevance=1 - i * 0.05) for i in range(4))
    matrix = {a.id: {b.id: 15 for b in candidates if b.id != a.id} for a in candidates}
    result = BeamItinerarySolver().solve(PlanningProblem(_request(end=900, budget=None), candidates, matrix))
    assert result.status == "feasible"
    assert 1 <= len(result.activities) <= len(candidates)
    assert result.diagnostics["selected_stops"] == len(result.activities)
    assert result.diagnostics["objective_order"][0] == "hard_constraints"


def test_schedule_quality_uses_more_of_window_for_comparable_short_stops():
    candidates = tuple(_candidate(f"short-{index}", duration=90, relevance=0.8) for index in range(3))
    matrix = {left.id: {right.id: 10 for right in candidates if right.id != left.id} for left in candidates}

    result = BeamItinerarySolver().solve(PlanningProblem(
        _request(end=900, budget=None), candidates, matrix,
    ))

    assert len(result.activities) >= 2
    assert result.diagnostics["objective_components"]["planning_window_utilization"] >= 0.5
    assert "schedule_quality" in result.diagnostics["objective_order"]


def test_single_day_solver_honors_refine_candidate_options():
    request = replace(
        _request(end=780, budget=None),
        hard_constraints={"meal_obligations": [], "day_candidate_options": {"0": ["requested"]}},
    )
    requested = _candidate("requested", relevance=0.2)
    old_alternate = _candidate("old-alternate", relevance=1.0)

    result = BeamItinerarySolver().solve(PlanningProblem(request, (old_alternate, requested)))

    assert result.status == "feasible"
    assert "requested" in {activity["candidate_id"] for activity in result.activities}


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


def test_missing_primary_experience_is_not_a_hard_solver_failure():
    lunch = _candidate("lunch", domain="restaurant", duration=60)
    result = BeamItinerarySolver().solve(PlanningProblem(
        _request(end=900, budget=None, meals=("lunch",)),
        (lunch,),
    ))

    assert result.status == "feasible"
    assert [item["candidate_id"] for item in result.activities] == ["lunch"]


def test_unavailable_explicit_must_visit_is_reported_as_hard_failure():
    result = BeamItinerarySolver().solve(PlanningProblem(
        _request(end=900, budget=None, must=("Missing Museum",)),
        (_candidate("other"),),
    ))

    assert result.status == "infeasible"
    assert result.unsatisfied_constraints == ({
        "code": "must_visit_unavailable",
        "value": "Missing Museum",
    },)


def test_explicit_exclusion_is_never_selected():
    request = replace(
        _request(end=900, budget=None),
        hard_constraints={"meal_obligations": [], "exclude": ["skip-me"]},
    )
    result = BeamItinerarySolver().solve(PlanningProblem(
        request,
        (_candidate("skip-me", relevance=1.0), _candidate("keep-me", relevance=0.5)),
    ))

    assert result.status == "feasible"
    assert "skip-me" not in {item["candidate_id"] for item in result.activities}


def test_explicit_attraction_theme_outranks_generic_provider_quality():
    request = replace(
        _request(end=720, budget=None),
        soft_preferences={
            "pace": "balanced", "style": "sightseeing",
            "attraction_types": ["university-campus"],
        },
    )
    campus = replace(
        _candidate("campus", relevance=0.4),
        title="University Campus", tags=("amenity", "university"),
    )
    generic = replace(
        _candidate("popular", relevance=1.0),
        title="Popular Museum", tags=("museum",),
    )

    result = BeamItinerarySolver().solve(PlanningProblem(request, (generic, campus)))

    assert "campus" in {activity["candidate_id"] for activity in result.activities}
    assert result.diagnostics["objective_components"]["preference_match"] == 1.0


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


def test_solver_reserves_time_for_round_trip_anchor():
    request = replace(
        _request(end=660, budget=None),
        anchors={
            "start": AnchorConstraint("Hotel", latitude=1.2, longitude=103.8),
            "end": AnchorConstraint("Hotel", latitude=1.2, longitude=103.8),
        },
    )
    candidate = _candidate("far", duration=60)
    matrix = {
        "anchor:start": {"far": 30},
        "far": {"anchor:end": 40},
        "anchor:end": {},
    }
    result = BeamItinerarySolver().solve(PlanningProblem(request, (candidate,), matrix))
    assert result.status == "infeasible"

    feasible = BeamItinerarySolver().solve(PlanningProblem(replace(request, days=(replace(request.days[0], end_min=690),)), (candidate,), matrix))
    assert [activity["candidate_id"] for activity in feasible.activities] == ["far"]
    assert feasible.diagnostics["travel_min"] == 70


def test_gated_internal_restaurant_is_subactivity_without_route_stop():
    parent = replace(
        _candidate("park", duration=300, cost=50),
        role="experience",
        is_compound=True,
    )
    child = replace(
        _candidate("inside-food", domain="restaurant", duration=60, cost=20),
        role="food",
        parent_id="park",
        access="gated",
    )
    result = BeamItinerarySolver().solve(PlanningProblem(
        _request(end=900, budget=100, meals=("lunch",)),
        (parent, child),
    ))
    assert [activity["candidate_id"] for activity in result.activities] == ["park"]
    assert result.activities[0]["sub_activities"][0]["candidate_id"] == "inside-food"
    assert result.activities[0]["sub_activities"][0]["meal"] == "lunch"
    assert result.cost_summary["min"] == 70


def test_route_objective_prefers_one_strong_stop_over_repeated_fillers():
    strong = replace(
        _candidate("strong", relevance=1.0),
        rating=5.0,
        item={"id": "strong", "domain": "attraction", "role": "experience", "reviews_count": 1000},
    )
    fillers = tuple(
        replace(
            _candidate(f"filler-{index}", relevance=0.1),
            rating=2.0,
            item={"id": f"filler-{index}", "domain": "attraction", "role": "experience", "reviews_count": 1000},
        )
        for index in range(3)
    )
    candidates = (strong, *fillers)
    matrix = {left.id: {right.id: 5 for right in candidates if right.id != left.id} for left in candidates}
    result = BeamItinerarySolver().solve(PlanningProblem(
        _request(end=1080, budget=None), candidates, matrix
    ))
    assert [activity["candidate_id"] for activity in result.activities] == ["strong"]
    assert result.diagnostics["selected_stops"] < PACE_MAX_STOPS["balanced"]
    assert result.diagnostics["objective_components"]["transition_friction"] == 0


def test_route_objective_fills_avoidable_meal_gap_with_feasible_activity():
    morning = replace(
        _candidate("morning", duration=120, relevance=0.9),
        availability_windows=(AvailabilityWindow(0, 540, 720),),
    )
    afternoon = replace(
        _candidate("afternoon", duration=180, relevance=0.8),
        availability_windows=(AvailabilityWindow(0, 765, 1020),),
    )
    lunch = _candidate("lunch", domain="restaurant", duration=75, relevance=0.8)
    dinner = _candidate("dinner", domain="restaurant", duration=75, relevance=0.8)
    result = BeamItinerarySolver().solve(PlanningProblem(
        _request(end=1140, budget=None, meals=("lunch", "dinner")),
        (morning, afternoon, lunch, dinner),
    ))

    selected = [activity["candidate_id"] for activity in result.activities]
    assert "morning" in selected
    assert "afternoon" in selected
    components = result.diagnostics["objective_components"]
    assert components["time_utilization"] > 0.75
    assert components["planning_window_min"] == 600
    assert components["scheduled_activity_min"] == 450
    assert components["unallocated_min"] == 150
    assert components["tail_slack_min"] == 15
    assert "planning_window_utilization" in result.diagnostics["objective_order"]


def test_soft_dinner_does_not_create_a_long_empty_afternoon():
    request = replace(
        _request(end=1140, budget=None),
        soft_preferences={
            "pace": "balanced", "style": "sightseeing",
            "suggested_meals": [
                {"day_index": 0, "meal": "lunch"},
                {"day_index": 0, "meal": "dinner"},
            ],
        },
    )
    morning = replace(
        _candidate("morning", duration=120),
        availability_windows=(AvailabilityWindow(0, 540, 720),),
    )
    lunch = replace(
        _candidate("lunch", domain="restaurant", duration=75),
        availability_windows=(AvailabilityWindow(0, 690, 870),),
    )
    dinner = replace(
        _candidate("dinner", domain="restaurant", duration=75),
        availability_windows=(AvailabilityWindow(0, 1050, 1140),),
    )

    result = BeamItinerarySolver().solve(PlanningProblem(request, (morning, lunch, dinner)))

    selected = {item["candidate_id"] for item in result.activities}
    assert "morning" in selected and "lunch" in selected
    assert "dinner" not in selected
    assert result.diagnostics["objective_components"]["max_idle_gap_min"] <= 90


def test_continuous_afternoon_activity_beats_lower_uncertainty_short_route():
    request = replace(
        _request(end=1140, budget=None),
        soft_preferences={
            "pace": "balanced", "style": "sightseeing",
            "suggested_meals": [
                {"day_index": 0, "meal": "lunch"},
                {"day_index": 0, "meal": "dinner"},
            ],
        },
    )
    morning = replace(
        _candidate("morning", duration=120),
        availability_windows=(AvailabilityWindow(0, 540, 720),),
    )
    lunch = replace(
        _candidate("lunch", domain="restaurant", duration=75),
        availability_windows=(AvailabilityWindow(0, 690, 870),),
    )
    afternoon = _candidate("afternoon", duration=210, known=False, relevance=0.7)
    dinner = replace(
        _candidate("dinner", domain="restaurant", duration=75),
        availability_windows=(AvailabilityWindow(0, 1050, 1140),),
    )

    result = BeamItinerarySolver().solve(PlanningProblem(
        request, (morning, lunch, afternoon, dinner),
    ))

    assert "afternoon" in {item["candidate_id"] for item in result.activities}
    assert result.diagnostics["objective_components"]["max_idle_gap_min"] <= 90
    assert result.diagnostics["objective_order"].index("schedule_quality") < (
        result.diagnostics["objective_order"].index("uncertainty")
    )


def test_explicit_dinner_remains_hard_even_when_it_requires_waiting():
    request = replace(
        _request(end=1140, budget=None, meals=("lunch", "dinner")),
        soft_preferences={"pace": "balanced", "style": "sightseeing"},
    )
    morning = replace(
        _candidate("morning", duration=120),
        availability_windows=(AvailabilityWindow(0, 540, 720),),
    )
    lunch = replace(
        _candidate("lunch", domain="restaurant", duration=75),
        availability_windows=(AvailabilityWindow(0, 690, 870),),
    )
    dinner = replace(
        _candidate("dinner", domain="restaurant", duration=75),
        availability_windows=(AvailabilityWindow(0, 1050, 1140),),
    )

    result = BeamItinerarySolver().solve(PlanningProblem(request, (morning, lunch, dinner)))

    assert result.status == "feasible"
    assert "dinner" in {item["candidate_id"] for item in result.activities}
    assert result.diagnostics["objective_components"]["max_idle_gap_min"] > 90


def test_route_objective_does_not_treat_travel_as_productive_time():
    request = replace(
        _request(end=690, budget=None),
        anchors={"start": AnchorConstraint("Hotel", latitude=1.2, longitude=103.8)},
    )
    near = _candidate("near", duration=120, relevance=0.8)
    far = _candidate("far", duration=120, relevance=0.8)
    result = BeamItinerarySolver().solve(PlanningProblem(
        request,
        (far, near),
        {"anchor:start": {"far": 120, "near": 10}},
    ))

    assert [activity["candidate_id"] for activity in result.activities] == ["near"]
    assert result.diagnostics["objective_components"]["time_utilization"] == 1.0
    assert result.diagnostics["travel_min"] == 10


def test_multi_day_solver_enforces_daily_windows_meals_dedupe_and_trip_budget():
    request = ItineraryPlanningRequest(
        location=LocationConstraint("Singapore", timezone="Asia/Singapore"),
        days=(
            DayConstraint(0, "2026-08-03", 540, 1020),
            DayConstraint(1, "2026-08-04", 540, 1020),
        ),
        budget=BudgetConstraint("limited", 120, "SGD", scope="trip_total", include_lodging=True),
        lodging=LodgingRequirement("recommend", "2026-08-03", "2026-08-05", 2, 1, 1),
        hard_constraints={
            "meal_obligations": [
                {"day_index": 0, "meal": "lunch"},
                {"day_index": 1, "meal": "lunch"},
            ],
            "must_visit": ["day-one-museum", "day-two-park"],
        },
        soft_preferences={"pace": "balanced", "style": "sightseeing"},
    )
    day_one = replace(
        _candidate("day-one-museum", duration=150, cost=10),
        availability_windows=(AvailabilityWindow(0, 540, 1020),),
    )
    day_two = replace(
        _candidate("day-two-park", duration=150, cost=10),
        availability_windows=(AvailabilityWindow(1, 540, 1020),),
    )
    lunch_one = replace(
        _candidate("lunch-one", domain="restaurant", duration=75, cost=10),
        availability_windows=(AvailabilityWindow(0, 690, 870),),
    )
    lunch_two = replace(
        _candidate("lunch-two", domain="restaurant", duration=75, cost=10),
        availability_windows=(AvailabilityWindow(1, 690, 870),),
    )
    lodging_cost = CostEstimate(50, 50, "SGD", ("lodging",), "provider", 0.9)
    scenario = LodgingScenario(
        "hotel", "Shared Hotel", 1.3, 103.8, "1 Hotel Rd", "provider",
        CostEstimate(25, 25, "SGD", ("nightly",), "provider", 0.9),
        lodging_cost,
    )
    candidates = (day_one, day_two, lunch_one, lunch_two)
    nodes = [candidate.id for candidate in candidates] + ["lodging:hotel"]
    matrix = {left: {right: 10 for right in nodes if right != left} for left in nodes}

    first = BeamItinerarySolver(beam_width=96).solve(
        PlanningProblem(request, candidates, matrix, (scenario,))
    )
    second = BeamItinerarySolver(beam_width=96).solve(
        PlanningProblem(request, candidates, matrix, (scenario,))
    )

    assert first.status == "feasible"
    assert first.activities == second.activities
    assert {item["day_index"] for item in first.activities} == {0, 1}
    assert [item["candidate_id"] for item in first.activities].count("day-one-museum") == 1
    assert first.cost_summary["min"] == 90
    assert first.cost_summary["budget_status"] == "feasible"
    assert first.diagnostics["day_count"] == 2
    assert len(first.diagnostics["daily_travel_min"]) == 2
    assert first.lodging["candidate_id"] == "hotel"


def test_multi_day_solver_rejects_trip_when_lodging_and_activity_exceed_total_budget():
    request = ItineraryPlanningRequest(
        location=LocationConstraint("Singapore", timezone="Asia/Singapore"),
        days=(DayConstraint(0, "2026-08-03", 540, 900), DayConstraint(1, "2026-08-04", 540, 900)),
        budget=BudgetConstraint("limited", 60, "SGD", scope="trip_total", include_lodging=True),
        lodging=LodgingRequirement("recommend", "2026-08-03", "2026-08-05", 2, 1, 1),
        hard_constraints={"meal_obligations": []},
        soft_preferences={"pace": "balanced", "style": "sightseeing"},
    )
    candidates = (
        replace(_candidate("a", cost=20), availability_windows=(AvailabilityWindow(0, 0, 1440),)),
        replace(_candidate("b", cost=20), availability_windows=(AvailabilityWindow(1, 0, 1440),)),
    )
    scenario = LodgingScenario(
        "hotel", "Hotel", 1.3, 103.8, None, "provider",
        CostEstimate(25, 25, "SGD"), CostEstimate(50, 50, "SGD"),
    )
    result = BeamItinerarySolver().solve(PlanningProblem(request, candidates, {}, (scenario,)))
    assert result.status == "infeasible"
    assert result.cost_summary["budget_status"] == "infeasible"


def test_multi_day_solver_pins_refined_candidate_to_requested_day():
    request = ItineraryPlanningRequest(
        location=LocationConstraint("Singapore", timezone="Asia/Singapore"),
        days=(DayConstraint(0, "2026-08-03", 540, 900), DayConstraint(1, "2026-08-04", 540, 900)),
        budget=BudgetConstraint("unlimited"),
        lodging=LodgingRequirement("recommend", "2026-08-03", "2026-08-05", 2, 1, 1),
        hard_constraints={"meal_obligations": [], "fixed_day_candidates": {"fixed": 1}},
        soft_preferences={"pace": "balanced", "style": "sightseeing"},
    )
    always = (AvailabilityWindow(0, 0, 1440), AvailabilityWindow(1, 0, 1440))
    fixed = replace(_candidate("fixed", relevance=1.0), availability_windows=always)
    other = replace(_candidate("other", relevance=0.8), availability_windows=always)
    scenario = LodgingScenario(
        "hotel", "Hotel", 1.3, 103.8, None, "provider",
        CostEstimate(0, 0, "SGD"), CostEstimate(0, 0, "SGD"),
    )
    result = BeamItinerarySolver().solve(PlanningProblem(request, (fixed, other), {}, (scenario,)))
    days_by_id = {item["candidate_id"]: item["day_index"] for item in result.activities}
    assert result.status == "feasible"
    assert days_by_id == {"other": 0, "fixed": 1}
