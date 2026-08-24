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
    components = result.diagnostics["objective_components"]
    assert components["route_metric_day_count"] == 1
    assert components["route_order_detour_ratio"] == 1.0
    assert components["estimated_travel_minutes_per_activity"] is not None


def _geo_candidate(identifier, lat, lng, *, duration=90, rating=4.5):
    return replace(
        _candidate(identifier, duration=duration),
        latitude=lat, longitude=lng, rating=rating,
        item={"id": identifier, "title": identifier, "domain": "attraction",
              "lat": lat, "lng": lng, "reviews_count": 900},
    )


def test_schedule_quality_separates_compact_routes_from_sprawling_ones():
    # Identical stop count, durations and ratings -- only the spacing differs.
    # travel_wait_min sits at objective key 10, behind three continuous floats
    # that never tie in practice, so before travel_share was folded into
    # schedule_quality (key 3) these two scored bit-identically and spatial
    # continuity was decided by chance.
    from langgraph_metarec.itinerary_runtime import build_travel_matrix

    def solve(pool):
        request = _request(end=1320, budget=None)
        matrix = build_travel_matrix(pool, request)
        return BeamItinerarySolver().solve(PlanningProblem(request, pool, matrix))

    tight = tuple(
        _geo_candidate(f"tight-{i}", 1.2830 + i * 0.0025, 103.8440 + i * 0.0025)
        for i in range(5)
    )
    far = tuple(
        _geo_candidate(f"far-{i}", 1.2600 + i * 0.0280, 103.7700 + i * 0.0330)
        for i in range(5)
    )
    compact, sprawling = solve(tight), solve(far)
    near = compact.diagnostics["objective_components"]
    wide = sprawling.diagnostics["objective_components"]

    assert len(compact.activities) == len(sprawling.activities)
    assert near["scheduled_activity_min"] == wide["scheduled_activity_min"]
    assert wide["travel_share"] > near["travel_share"]
    assert near["schedule_quality"] > wide["schedule_quality"]


def test_solver_sweeps_an_east_west_pool_instead_of_backtracking():
    # Real Singapore spread, east (Changi) through west (Haw Par Villa), with
    # varied ratings so the orderings do not simply tie. With travel outside
    # schedule_quality this zigzagged for 174 min against a 132 min optimum.
    #
    # Ratings must vary: on a uniform pool every ordering scores alike and the
    # beam's dominance projection collapses them before the objective is
    # consulted, so such a fixture cannot detect this regression at all.
    from langgraph_metarec.itinerary_runtime import build_travel_matrix

    # Dwells are 90 minutes here for realism, not necessity: the role-repeat
    # discount used to force a single stop below ~74 minutes, but
    # ROLE_REPEAT_DISCOUNT_EXPONENT now clears that -- see
    # test_short_dwell_pool_fills_the_day_instead_of_returning_one_stop.
    pool = tuple(
        _geo_candidate(identifier, lat, lng, duration=duration, rating=rating)
        for identifier, lat, lng, duration, rating in (
            ("jewel-changi", 1.3603, 103.9895, 120, 4.7),
            ("east-coast-park", 1.3010, 103.9120, 90, 4.4),
            ("marina-bay-sands", 1.2863, 103.8593, 90, 4.6),
            ("chinatown", 1.2838, 103.8437, 90, 4.3),
            ("orchard-road", 1.3048, 103.8318, 90, 4.4),
            ("haw-par-villa", 1.2830, 103.7820, 90, 4.0),
        )
    )
    request = _request(end=1320, budget=None, pace="packed")
    matrix = build_travel_matrix(pool, request)
    result = BeamItinerarySolver().solve(PlanningProblem(request, pool, matrix))
    components = result.diagnostics["objective_components"]

    assert len(result.activities) >= 5
    assert components["route_order_excess_min"] == 0
    assert components["route_order_detour_ratio"] == 1.0


def test_short_dwell_pool_fills_the_day_instead_of_returning_one_stop():
    # Central Singapore heritage walk: temples, museums and a hawker centre, all
    # 45-60 minute stops, which is entirely ordinary for a city day.
    #
    # The role-repeat discount used to divide by the running repeat count, so the
    # quality term went negative by the sixth same-role stop and only
    # planning_window_utilization (weight 2.0) kept multi-stop days alive. That
    # put the break-even at ~74 minutes of dwell and made it a cliff rather than
    # a gradient: across eight pools like this one the solver returned a ONE-stop
    # day in 8 of 8, using 14.4% of the planning window on average.
    #
    # Ratings vary deliberately -- on a uniform pool the beam's dominance
    # projection collapses equivalent selections before the objective is
    # consulted, so a flat fixture cannot detect this at all.
    from langgraph_metarec.itinerary_runtime import build_travel_matrix

    pool = tuple(
        _geo_candidate(identifier, lat, lng, duration=duration, rating=rating)
        for identifier, lat, lng, duration, rating in (
            ("chinatown", 1.2838, 103.8437, 60, 4.3),
            ("sri-mariamman", 1.2819, 103.8452, 45, 4.5),
            ("maxwell-food", 1.2803, 103.8447, 60, 4.4),
            ("fort-canning", 1.2939, 103.8461, 60, 4.4),
            ("peranakan-museum", 1.2949, 103.8494, 60, 4.4),
            ("national-museum", 1.2966, 103.8485, 90, 4.5),
        )
    )
    request = _request(end=1320, budget=None, pace="packed")
    matrix = build_travel_matrix(pool, request)
    result = BeamItinerarySolver().solve(PlanningProblem(request, pool, matrix))
    components = result.diagnostics["objective_components"]

    # A whole afternoon of walkable 45-60 minute stops must not collapse to one.
    assert len(result.activities) >= 4
    assert components["scheduled_activity_min"] >= 240
    # Route quality must survive the extra stops, not be traded away for them.
    assert components["route_order_detour_ratio"] == 1.0


def test_role_repeat_discount_still_damps_later_repeats():
    # The knob must keep doing its job -- a monotonically decreasing discount --
    # so that lowering the exponent stays a calibration rather than a silent
    # removal of the term.
    from langgraph_metarec.itinerary_solver import _role_repeat_discount

    discounts = [_role_repeat_discount(index) for index in range(1, 7)]
    assert discounts[0] == 1.0
    assert all(later < earlier for earlier, later in zip(discounts, discounts[1:]))
    # Sixth repeat retains most of its value; at the old 1/n it kept only a sixth,
    # which drove the combined quality term negative.
    assert 0.5 < discounts[5] < 0.8


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
    assert first.diagnostics["objective_components"]["route_metric_day_count"] == 2
    assert first.diagnostics["objective_components"]["route_order_detour_ratio"] == 1.0
    assert first.lodging["candidate_id"] == "hotel"


def test_transition_friction_break_even_does_not_move_with_window_or_trip_length():
    # Friction trades directly against planning_window_utilization, so it has to
    # be denominated the same way. When it was a flat 0.08 the break-even was
    # `0.04 * window` -- 28.8 minutes of dwell on a 12-hour day but 115 on a
    # four-day trip, because multi-day divides by the whole-trip window.
    from langgraph_metarec.itinerary_solver import (
        TRANSITION_COST_MIN,
        WINDOW_UTILIZATION_WEIGHT,
        _transition_friction,
    )

    for window_min in (300, 540, 720, 1440, 2880):  # 5-hour day .. 4-day trip
        friction = _transition_friction(1, window_min)
        # Dwell at which the utilization gain exactly pays for one extra stop.
        break_even_dwell = friction * window_min / WINDOW_UTILIZATION_WEIGHT
        assert break_even_dwell == pytest.approx(TRANSITION_COST_MIN)

    assert _transition_friction(0, 720) == 0.0
    assert _transition_friction(3, 720) == pytest.approx(3 * _transition_friction(1, 720))


def test_longer_trips_do_not_starve_each_day_to_a_single_stop():
    # Multi-day divides planning_window_utilization by the WHOLE-TRIP window, so
    # a flat per-stop friction meant the bar for an extra stop rose with every
    # added day. Measured before the fix: this pool gave 8 stops over one day but
    # 1 stop per day over three, so asking for a longer trip returned a thinner
    # itinerary. Dwell is 60 minutes -- comfortably worth a stop, and exactly the
    # range that used to collapse.
    from langgraph_metarec.itinerary_runtime import build_travel_matrix

    pool = tuple(
        _geo_candidate(f"poi-{index}", 1.2860 + index * 0.0030, 103.8440 + index * 0.0030,
                       duration=60, rating=4.2 + (index % 4) * 0.1)
        for index in range(9)
    )
    scenario = LodgingScenario(
        "hotel", "Central Hotel", 1.2900, 103.8500, None, "provider",
        CostEstimate(200, 200, "SGD"), CostEstimate(600, 600, "SGD"),
    )

    def solve(day_count):
        request = ItineraryPlanningRequest(
            location=LocationConstraint("Singapore", timezone="Asia/Singapore"),
            days=tuple(
                DayConstraint(index, f"2026-08-{3 + index:02d}", 540, 1260)
                for index in range(day_count)
            ),
            budget=BudgetConstraint("unlimited"),
            lodging=(
                LodgingRequirement("recommend", "2026-08-03", "2026-08-06", day_count - 1, 1, 1)
                if day_count > 1 else None
            ),
            hard_constraints={"meal_obligations": [], "must_visit": []},
            soft_preferences={"pace": "packed", "style": "sightseeing"},
        )
        lodging = (scenario,) if day_count > 1 else ()
        # Availability has to cover every day or later days are simply unschedulable.
        dated = tuple(
            replace(candidate, availability_windows=tuple(
                AvailabilityWindow(index, 0, 1440) for index in range(day_count)))
            for candidate in pool
        )
        matrix = build_travel_matrix(dated, request, lodging)
        return BeamItinerarySolver().solve(PlanningProblem(request, dated, matrix, lodging))

    single = solve(1)
    counts = {}
    for day_count in (2, 3):
        result = solve(day_count)
        assert result.status == "feasible"
        per_day = {}
        for activity in result.activities:
            index = int(activity.get("day_index") or 0)
            per_day[index] = per_day.get(index, 0) + 1
        assert len(per_day) == day_count, f"{day_count}-day trip left a day empty: {per_day}"
        counts[day_count] = len(result.activities)

    # Asking for more days must never return a thinner itinerary. Before the fix
    # this pool gave 8 stops over one day but 2 over two days and 3 over three,
    # because the per-stop reward was divided by the whole-trip window while the
    # cost per stop stayed flat.
    assert counts[2] >= len(single.activities)
    assert counts[3] >= counts[2]
    # How those stops are spread across days is NOT asserted here: the objective
    # cannot currently express day balance, so the split is decided by the beam's
    # traversal order. See the separate day-balance finding.


def test_small_short_dwell_pool_in_a_long_window_still_plans_more_than_one_stop():
    # The knife edge left over after the role-repeat recalibration: three short
    # stops in a 12-hour window sat within 0.002 of the window-utilization gain,
    # and travel_share tipped it to a single stop. Friction supplied 0.160 of the
    # 0.290 quality drop, so normalising it clears the case.
    from langgraph_metarec.itinerary_runtime import build_travel_matrix

    pool = tuple(
        _geo_candidate(identifier, lat, lng, duration=duration, rating=rating)
        for identifier, lat, lng, duration, rating in (
            ("clarke-quay", 1.2907, 103.8465, 60, 4.2),
            ("merlion-park", 1.2868, 103.8545, 60, 4.5),
            ("singapore-flyer", 1.2893, 103.8631, 45, 4.4),
        )
    )
    request = _request(end=1260, budget=None, pace="packed")
    matrix = build_travel_matrix(pool, request)
    result = BeamItinerarySolver().solve(PlanningProblem(request, pool, matrix))

    assert len(result.activities) == 3


def test_multi_day_solver_harvests_full_cap_finals_from_the_last_beam_depth():
    # A trip using the full per-day stop cap on every day needs exactly
    # total_depth expansions, so its final state is only produced in the last
    # beam iteration. The in-loop finals check never sees that generation; only
    # the post-loop sweep (mirroring the single-day path) can harvest it. Eight
    # must-visits pinned four per day make a relaxed 2-day trip (cap 4/day)
    # feasible ONLY via that maximal plan — before the sweep this reported
    # infeasible with must_visit unsatisfied at ANY beam width. The wide beam
    # below only removes heuristic eviction noise (the beam prefers states that
    # advanced a day early); it does not mask the harvest bug.
    always = (AvailabilityWindow(0, 0, 1440), AvailabilityWindow(1, 0, 1440))
    names = [f"must-{index}" for index in range(8)]
    candidates = tuple(
        replace(_candidate(name, duration=60, cost=0), availability_windows=always)
        for name in names
    )
    request = ItineraryPlanningRequest(
        location=LocationConstraint("Singapore", timezone="Asia/Singapore"),
        days=(DayConstraint(0, "2026-08-03", 540, 1260), DayConstraint(1, "2026-08-04", 540, 1260)),
        budget=BudgetConstraint("unlimited"),
        lodging=LodgingRequirement("recommend", "2026-08-03", "2026-08-05", 2, 1, 1),
        hard_constraints={
            "meal_obligations": [],
            "must_visit": list(names),
            "fixed_day_candidates": {name: (0 if index < 4 else 1) for index, name in enumerate(names)},
        },
        soft_preferences={"pace": "relaxed", "style": "sightseeing"},
    )
    scenario = LodgingScenario(
        "hotel", "Hotel", 1.3, 103.8, None, "provider",
        CostEstimate(0, 0, "SGD"), CostEstimate(0, 0, "SGD"),
    )
    result = BeamItinerarySolver(beam_width=256).solve(
        PlanningProblem(request, candidates, {}, (scenario,))
    )

    assert result.status == "feasible"
    assert sorted(item["candidate_id"] for item in result.activities) == sorted(names)
    per_day = {}
    for activity in result.activities:
        per_day[activity["day_index"]] = per_day.get(activity["day_index"], 0) + 1
    assert per_day == {0: PACE_MAX_STOPS["relaxed"], 1: PACE_MAX_STOPS["relaxed"]}


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


def _two_day_request(*, style="sightseeing"):
    return ItineraryPlanningRequest(
        location=LocationConstraint("Singapore", timezone="Asia/Singapore"),
        days=(DayConstraint(0, "2026-08-03", 540, 1020), DayConstraint(1, "2026-08-04", 540, 1020)),
        budget=BudgetConstraint("unlimited"),
        lodging=LodgingRequirement("recommend", "2026-08-03", "2026-08-05", 2, 1, 1),
        hard_constraints={"meal_obligations": []},
        soft_preferences={"pace": "balanced", "style": style},
    )


def _free_lodging():
    return (LodgingScenario(
        "hotel", "Hotel", 1.3, 103.8, None, "provider",
        CostEstimate(0, 0, "SGD"), CostEstimate(0, 0, "SGD"),
    ),)


def _both_days(candidate):
    return replace(
        candidate,
        availability_windows=(AvailabilityWindow(0, 0, 1440), AvailabilityWindow(1, 0, 1440)),
    )


def test_early_break_does_not_revalidate_finals_a_second_time(monkeypatch):
    # A small pool exhausts expansions long before total_depth, so the loop
    # breaks right after final-checking the current beam. The post-loop
    # harvest must skip that already-checked generation on BOTH solver paths;
    # re-scanning it validated the same final states twice and duplicated
    # their violations in unsatisfied_constraints.
    from langgraph_metarec import itinerary_solver as solver_module

    seen = {}
    real = solver_module.validate_activity_policy

    def counting(request, activities, candidates):
        signature = tuple(
            (activity.get("day_index"), activity.get("candidate_id"))
            for activity in activities
        )
        seen[signature] = seen.get(signature, 0) + 1
        return real(request, activities, candidates)

    monkeypatch.setattr(solver_module, "validate_activity_policy", counting)
    candidates = tuple(
        _both_days(_candidate(f"a{index}", duration=60, cost=0)) for index in range(3)
    )

    multi = BeamItinerarySolver().solve(
        PlanningProblem(_two_day_request(), candidates, {}, _free_lodging())
    )
    assert multi.status == "feasible"
    assert max(seen.values()) == 1

    seen.clear()
    single = BeamItinerarySolver().solve(
        PlanningProblem(_request(budget=None), candidates, {})
    )
    assert single.status == "feasible"
    assert max(seen.values()) == 1


def test_infeasible_trip_reports_each_violation_once():
    # Every final containing candidate X repeats X's policy violation, and the
    # early-break double-scan repeated them again: the NTU-style payload showed
    # 8 entries carrying 3 distinct facts, and the [:8] truncation could push
    # genuinely distinct violations out. Dedupe before truncating.
    candidates = tuple(
        replace(
            _both_days(_candidate(f"a{index}", duration=60, cost=0)),
            role="food",  # domain "attraction" + role "food" -> domain_mismatch
        )
        for index in range(3)
    )

    result = BeamItinerarySolver().solve(
        PlanningProblem(_two_day_request(style="mixed"), candidates, {}, _free_lodging())
    )

    assert result.status == "infeasible"
    markers = [tuple(sorted(item.items())) for item in result.unsatisfied_constraints]
    assert len(markers) == len(set(markers))
    reported = {item.get("candidate_id") for item in result.unsatisfied_constraints}
    assert reported == {"a0", "a1", "a2"}
