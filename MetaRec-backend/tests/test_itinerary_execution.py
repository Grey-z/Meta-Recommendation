import pytest

from conftest import make_service
from langgraph_metarec.itinerary_contracts import (
    AnchorConstraint,
    BudgetConstraint,
    DayConstraint,
    ItineraryPlanningRequest,
    LocationConstraint,
    LodgingRequirement,
)
from service import RecommendationResult, Restaurant

pytestmark = pytest.mark.backend_unit


def _planning_request(*, meals=("lunch",)):
    return ItineraryPlanningRequest(
        location=LocationConstraint("Sentosa", timezone="Asia/Singapore"),
        days=(DayConstraint(0, "2026-08-03", 600, 1020),),
        budget=BudgetConstraint("limited", 150, "SGD"),
        hard_constraints={"meal_obligations": list(meals)},
        soft_preferences={"pace": "balanced"},
    )


def _itinerary_route(domains, *, meals=("lunch",)):
    return {
        "domain": "itinerary",
        "execution_domain": "itinerary",
        "mode": "itinerary",
        "status": "ready",
        "tool_tags": [],
        "domain_tasks": [_slot(index, domain) for index, domain in enumerate(domains)],
        "metadata": {"planning_request": _planning_request(meals=meals).to_dict()},
    }


def _slot(index, domain):
    return {
        "domain": domain,
        "source_domain": domain,
        "status": "ready",
        "tool_tags": ["#place", f"#{domain}"],
        "slot_index": index,
    }


@pytest.fixture()
def _itinerary_harness(monkeypatch):
    """Fakes both domain executors with geo candidates and counts resolve_leg calls."""
    import langgraph_metarec.eta as eta_module
    import langgraph_metarec.graphs.generic_graph as generic_graph_module
    from langgraph_metarec.graphs.generic_graph import GenericGraphResult

    generic_calls = []

    async def fake_generic(**kwargs):
        generic_calls.append(kwargs)
        base_lat = 1.30 + 0.001 * len(generic_calls)
        return GenericGraphResult(
            executions=[],
            items=[
                {
                    "id": f"a-{len(generic_calls)}-1",
                    "domain": kwargs.get("domain") or "attraction",
                    "title": f"Attraction {len(generic_calls)} best",
                    "subtitle": "Somewhere scenic",
                    "rating": 4.6,
                    "tags": ["tourist attraction"],
                    "raw": {"gps_coordinates": {"latitude": base_lat, "longitude": 103.85}},
                },
                {
                    "id": f"a-{len(generic_calls)}-2",
                    "domain": kwargs.get("domain") or "attraction",
                    "title": f"Attraction {len(generic_calls)} alt",
                    "subtitle": "Also scenic",
                    "rating": 4.1,
                    "tags": ["tourist attraction"],
                    "raw": {"gps_coordinates": {"latitude": base_lat + 0.002, "longitude": 103.852}},
                },
            ],
            metadata={"graph": "generic_domain_graph", "domain": kwargs.get("domain")},
        )

    monkeypatch.setattr(generic_graph_module, "run_generic_domain_graph", fake_generic)

    service, _ = make_service([])
    restaurant_calls = []

    async def fake_restaurant(**kwargs):
        restaurant_calls.append(kwargs)
        return RecommendationResult(
            restaurants=[
                Restaurant(
                    id="r-1",
                    name="Lunch Kopitiam",
                    address="1 Food Street",
                    rating=4.4,
                    price_per_person_sgd="18",
                    gps_coordinates={"latitude": 1.3005, "longitude": 103.8505},
                )
            ],
            items=[],
            thinking_steps=[],
            confidence_score=0.9,
            metadata={"domain": "restaurant"},
        )

    service._execute_restaurant_domain_task = fake_restaurant

    leg_calls = []

    def fake_resolve_leg(a, b, depart_hhmm=None):
        leg_calls.append((a, b, depart_hhmm))
        return {"mode": "pt", "duration_min": 15, "distance_km": 1.5, "source": "onemap", "fare": "1.20 SGD"}

    monkeypatch.setattr(eta_module, "resolve_leg", fake_resolve_leg)
    return service, generic_calls, restaurant_calls, leg_calls


@pytest.mark.asyncio
async def test_itinerary_mode_uses_bounded_adaptive_gather_and_solves_dynamically(_itinerary_harness):
    service, generic_calls, restaurant_calls, leg_calls = _itinerary_harness
    preferences = {
        "domain": "itinerary", "location": "Sentosa", "date": "2026-08-03",
        "start_time": "10:00", "end_time": "17:00", "timezone": "Asia/Singapore",
        "budget_mode": "limited", "budget_amount": 150, "budget_currency": "SGD",
    }

    await service.process_recommendation_task(
        "task-itin-1",
        "Plan my day in Sentosa",
        preferences,
        user_id="u-itin",
        session_id="c-itin",
        use_online_agent=False,
        tool_tags=[],
        route=_itinerary_route(["attraction", "restaurant"]),
    )

    assert [call["domain"] for call in generic_calls] == ["attraction", "attraction"]
    assert len(restaurant_calls) == 1
    # The seed uses destination text; the adaptive round is re-anchored on the
    # current frontier candidate with a bounded radius.
    assert generic_calls[0]["preferences"]["location"] == "Sentosa"
    assert generic_calls[1]["preferences"]["anchor_lat"] is not None
    assert generic_calls[1]["preferences"]["radius_meters"] > generic_calls[0]["preferences"]["radius_meters"]

    status = service.get_task_status("task-itin-1", user_id="u-itin", session_id="c-itin")
    assert status["status"] == "completed"
    block = status["result"].metadata["itinerary"]
    assert len(block["retrieval"]["rounds"]) == 2
    assert block["retrieval"]["provider_calls"] == 3
    assert block["retrieval"]["provider_call_limit"] == 8
    assert block["retrieval"]["round_limit"] == 2
    assert block["retrieval"]["task_scoped"] is True
    snapshot = status["metadata"]["planning_snapshot"]
    assert snapshot["phase"] == "finalization"
    assert snapshot["revision"] >= 5
    assert snapshot["provider_calls"] == 3
    assert all(
        "planning_snapshot" not in event.get("metadata", {})
        for event in status["metadata"].get("progress_events", [])
    )

    assert 2 <= len(block["slots"]) <= 4
    chosen_ids = {slot["chosen"]["id"] for slot in block["slots"]}
    assert "r-1" in chosen_ids
    assert chosen_ids & {"a-1-1", "a-1-2"}
    assert block["slots"][0]["chosen"]["lat"] is not None
    assert block["problem_summary"]["start_min"] == 600
    assert block["planning_status"] == "needs_refinement"  # attraction hours/prices are unknown
    assert block["solver"]["runtime_ms"] >= 0
    assert block["runtime_ms"] >= block["solver"]["runtime_ms"]

    # Exactly N-1 legs, each resolved through the (fake) provider once.
    assert len(block["legs"]) == len(block["slots"]) - 1
    assert len(leg_calls) == len(block["legs"])
    assert all(leg["source"] == "onemap" and leg["fare"] == "1.20 SGD" for leg in block["legs"])
    assert block["totals"]["total_travel_min"] == 15 * len(block["legs"])
    assert block["cost_summary"]["min"] >= 19.2
    assert block["cost_summary"]["budget_status"] == "indeterminate"
    assert status["result"].metadata["graph"] == "itinerary_graph"
    assert status["result"].metadata["domain"] == "itinerary"

    # Flattened compatibility lists carry the per-slot candidates.
    assert len(status["result"].restaurants) == 1
    assert len(status["result"].items) == 4


@pytest.mark.asyncio
async def test_restaurant_retrieval_reanchors_to_attractions_when_seed_is_far(monkeypatch):
    """The seed pulls a top-rated restaurant far from the day's attractions; a
    tight meal-adjacent restaurant round then re-fetches next to the attraction
    the traveller is at during the meal, and the solver keeps the near option."""
    import langgraph_metarec.eta as eta_module
    import langgraph_metarec.graphs.generic_graph as generic_graph_module
    from langgraph_metarec.graphs.generic_graph import GenericGraphResult

    async def fake_generic(**kwargs):
        return GenericGraphResult(
            executions=[],
            items=[
                {"id": "att-1", "domain": "attraction", "title": "Cluster Museum",
                 "rating": 4.6, "tags": ["museum"],
                 "raw": {"gps_coordinates": {"latitude": 1.300, "longitude": 103.900}}},
                {"id": "att-2", "domain": "attraction", "title": "Cluster Garden",
                 "rating": 4.5, "tags": ["park"],
                 "raw": {"gps_coordinates": {"latitude": 1.302, "longitude": 103.902}}},
            ],
            metadata={"domain": kwargs.get("domain")},
        )

    monkeypatch.setattr(generic_graph_module, "run_generic_domain_graph", fake_generic)
    service, _ = make_service([])

    restaurant_prefs = []

    async def fake_restaurant(**kwargs):
        prefs = kwargs.get("preferences") or {}
        restaurant_prefs.append(prefs)
        if (prefs.get("radius_meters") or 99999) <= 1500:
            # Tight meal-adjacent round: a restaurant beside the attraction cluster.
            row = Restaurant(id="r-near", name="Near Eatery", address="Beside the sights",
                             rating=4.5, price_per_person_sgd="20",
                             gps_coordinates={"latitude": 1.3009, "longitude": 103.9008})
        else:
            # Seed sweep: a top-rated restaurant clear across town.
            row = Restaurant(id="r-far", name="Far Fine Dining", address="Across town",
                             rating=4.9, price_per_person_sgd="30",
                             gps_coordinates={"latitude": 1.400, "longitude": 103.700})
        return RecommendationResult(restaurants=[row], items=[], thinking_steps=[],
                                    confidence_score=0.9, metadata={"domain": "restaurant"})

    service._execute_restaurant_domain_task = fake_restaurant

    def fake_resolve_leg(a, b, depart_hhmm=None):
        return {"mode": "pt", "duration_min": 12, "distance_km": 1.2, "source": "onemap"}

    monkeypatch.setattr(eta_module, "resolve_leg", fake_resolve_leg)

    await service.process_recommendation_task(
        "task-reanchor", "Plan my day",
        {"domain": "itinerary", "location": "Sentosa", "date": "2026-08-03",
         "start_time": "10:00", "end_time": "17:00", "timezone": "Asia/Singapore",
         "budget_mode": "unlimited"},
        user_id="u-re", session_id="c-re", use_online_agent=False, tool_tags=[],
        route=_itinerary_route(["attraction", "restaurant"], meals=("lunch",)),
    )

    status = service.get_task_status("task-reanchor", user_id="u-re", session_id="c-re")
    assert status["status"] == "completed"
    block = status["result"].metadata["itinerary"]
    # A wide seed sweep, then a tight meal-adjacent re-fetch.
    assert len(restaurant_prefs) == 2
    assert (restaurant_prefs[0].get("radius_meters") or 0) > 1500
    assert restaurant_prefs[1]["radius_meters"] == 1200
    # The re-fetch is anchored on the attraction cluster, not the far seed.
    assert abs(restaurant_prefs[1]["anchor_lat"] - 1.301) < 0.01
    assert abs(restaurant_prefs[1]["anchor_lng"] - 103.901) < 0.01
    # The solver keeps the near restaurant over the far top-rated one.
    chosen_ids = {slot["chosen"]["id"] for slot in block["slots"]}
    assert "r-near" in chosen_ids
    assert "r-far" not in chosen_ids


def test_spatially_scope_candidates_drops_far_keeps_near():
    """The gate that scopes an anchored restaurant fetch: candidates inside the
    radius win outright (a far, higher-rated option is dropped before it can reach
    the solver); with nothing inside, the nearest is kept so a meal isn't starved;
    and with no anchor the batch passes through untouched."""
    from service import MetaRecService

    anchor = (1.300, 103.900)
    near = {"id": "r-near", "rating": 4.4, "gps_coordinates": {"latitude": 1.3009, "longitude": 103.9008}}
    far = {"id": "r-far", "rating": 4.9, "gps_coordinates": {"latitude": 1.400, "longitude": 103.700}}

    scoped = MetaRecService._spatially_scope_candidates([far, near], anchor, 1200)
    assert [c["id"] for c in scoped] == ["r-near"]  # far dropped despite higher rating

    # Nothing inside the radius: keep the nearest so the meal window can still fill.
    floor = MetaRecService._spatially_scope_candidates([far], anchor, 1200)
    assert [c["id"] for c in floor] == ["r-far"]

    # No anchor / no coordinates: never over-prune.
    assert MetaRecService._spatially_scope_candidates([far, near], (None, None), 1200) == [far, near]
    blank = {"id": "r-blank", "rating": 5.0}
    assert MetaRecService._spatially_scope_candidates([blank], anchor, 1200) == [blank]


@pytest.mark.asyncio
async def test_itinerary_mode_emits_per_slot_progress(_itinerary_harness):
    service, _generic_calls, _restaurant_calls, _leg_calls = _itinerary_harness
    await service.process_recommendation_task(
        "task-itin-2",
        "Plan my day in Sentosa",
        {
            "domain": "itinerary", "location": "Sentosa", "date": "2026-08-03",
            "start_time": "10:00", "end_time": "17:00", "timezone": "Asia/Singapore",
            "budget_mode": "limited", "budget_amount": 150, "budget_currency": "SGD",
        },
        user_id="u-itin2",
        session_id="c-itin2",
        use_online_agent=False,
        tool_tags=[],
        route=_itinerary_route(["attraction", "restaurant"]),
    )

    status = service.get_task_status("task-itin-2", user_id="u-itin2", session_id="c-itin2")
    stages = [event.get("stage") for event in (status.get("metadata") or {}).get("progress_events", [])]
    assert "gather_attraction" in stages
    assert "gather_restaurant" in stages
    assert "solve_itinerary" in stages


@pytest.mark.asyncio
async def test_two_day_task_uses_same_supplied_hotel_as_each_day_boundary(_itinerary_harness):
    service, generic_calls, _restaurant_calls, leg_calls = _itinerary_harness
    hotel = AnchorConstraint(
        "Beach Hotel", resolved_name="Beach Hotel", address="1 Coast Rd",
        latitude=1.29, longitude=103.84, provider_id="hotel-1", source="provider",
    )
    planning_request = ItineraryPlanningRequest(
        location=LocationConstraint("Sentosa", timezone="Asia/Singapore"),
        days=(DayConstraint(0, "2026-08-03", 600, 1020), DayConstraint(1, "2026-08-04", 600, 1020)),
        budget=BudgetConstraint("unlimited", scope="trip_total", include_lodging=True),
        lodging=LodgingRequirement("supplied", "2026-08-03", "2026-08-05", 2, 1, 1),
        anchors={"start": hotel, "lodging": hotel},
        hard_constraints={"meal_obligations": [], "travelers": 1, "rooms": 1},
        soft_preferences={"pace": "balanced", "style": "sightseeing"},
    )
    route = {
        "domain": "itinerary", "execution_domain": "itinerary", "mode": "itinerary",
        "status": "ready", "tool_tags": [], "domain_tasks": [_slot(0, "attraction")],
        "metadata": {"planning_request": planning_request.to_dict()},
    }
    await service.process_recommendation_task(
        "task-itin-two-days", "Plan two days in Sentosa", {},
        user_id="u-two", session_id="c-two", use_online_agent=False,
        tool_tags=[], route=route,
    )

    status = service.get_task_status("task-itin-two-days", user_id="u-two", session_id="c-two")
    assert status["status"] == "completed"
    block = status["result"].metadata["itinerary"]
    assert len(block["days"]) == 2
    assert all(day["slots"] for day in block["days"])
    assert all(
        day["legs"][0].get("from_anchor") == "lodging"
        and day["legs"][-1].get("to_anchor") == "lodging"
        for day in block["days"]
    )
    assert all(leg.get("day_index") in {0, 1} for leg in block["legs"])
    assert len(generic_calls) == 2
    assert len(leg_calls) == len(block["legs"])


@pytest.mark.asyncio
async def test_itinerary_mode_with_empty_slots_degrades_gracefully(monkeypatch):
    import langgraph_metarec.graphs.generic_graph as generic_graph_module
    from langgraph_metarec.graphs.generic_graph import GenericGraphResult

    async def empty_generic(**kwargs):
        return GenericGraphResult(executions=[], items=[], metadata={})

    monkeypatch.setattr(generic_graph_module, "run_generic_domain_graph", empty_generic)
    service, _ = make_service([])

    await service.process_recommendation_task(
        "task-itin-3",
        "Plan my day somewhere",
        {
            "domain": "itinerary", "location": "Sentosa", "date": "2026-08-03",
            "start_time": "10:00", "end_time": "17:00", "timezone": "Asia/Singapore",
            "budget_mode": "limited", "budget_amount": 150, "budget_currency": "SGD",
        },
        user_id="u-itin3",
        session_id="c-itin3",
        use_online_agent=False,
        tool_tags=[],
        route=_itinerary_route(["attraction"], meals=()),
    )

    status = service.get_task_status("task-itin-3", user_id="u-itin3", session_id="c-itin3")
    assert status["status"] == "completed"
    block = status["result"].metadata["itinerary"]
    assert block["slots"] == []
    assert block["legs"] == []
    assert block["planning_status"] == "needs_refinement"
    assert status["result"].confidence_score == 0.35


@pytest.mark.asyncio
async def test_itinerary_runs_one_affected_domain_repair_pass(monkeypatch):
    import langgraph_metarec.graphs.generic_graph as generic_graph_module
    import llm_service
    from langgraph_metarec.graphs.generic_graph import GenericGraphResult

    calls = []

    async def fake_generic(**kwargs):
        calls.append((kwargs["domain"], kwargs["query"]))
        if len(calls) <= 2:
            item = {
                "id": "polluted-hotel", "domain": "attraction", "title": "Unrelated Hotel",
                "tags": ["hotel"],
                "raw": {"gps_coordinates": {"latitude": 1.25, "longitude": 103.82}},
            }
        else:
            item = {
                "id": "museum", "domain": "attraction", "title": "Sentosa Museum",
                "tags": ["museum"], "rating": 4.7,
                "raw": {"gps_coordinates": {"latitude": 1.26, "longitude": 103.83}},
            }
        return GenericGraphResult(executions=[], items=[item], metadata={})

    async def fake_repair(*args, **kwargs):
        return {
            "domain_queries": {"attraction": "museums and landmarks in Sentosa"},
            "required_roles": ["experience"],
            "excluded_types": ["lodging", "food"],
        }

    monkeypatch.setattr(generic_graph_module, "run_generic_domain_graph", fake_generic)
    monkeypatch.setattr(llm_service, "propose_itinerary_repair", fake_repair)
    service, _ = make_service([])
    await service.process_recommendation_task(
        "task-itin-repair", "Plan a sightseeing day",
        {
            "domain": "itinerary", "location": "Sentosa", "date": "2026-08-03",
            "start_time": "10:00", "end_time": "17:00", "timezone": "Asia/Singapore",
            "budget_mode": "unlimited", "style": "sightseeing", "pace": "balanced",
        },
        user_id="u-repair", session_id="c-repair", use_online_agent=False,
        tool_tags=[], route=_itinerary_route(["attraction"], meals=()),
    )
    status = service.get_task_status("task-itin-repair", user_id="u-repair", session_id="c-repair")
    block = status["result"].metadata["itinerary"]
    assert [domain for domain, _query in calls] == ["attraction", "attraction", "attraction"]
    assert calls[2][1] == "museums and landmarks in Sentosa"
    assert block["repair"]["attempt_count"] == 1
    assert block["repair"]["success"] is True
    assert block["repair"]["provider_calls"] == 3
    assert block["slots"][0]["chosen"]["id"] == "museum"


@pytest.mark.asyncio
async def test_invalid_repair_finishes_with_structured_refinement(monkeypatch):
    import langgraph_metarec.graphs.generic_graph as generic_graph_module
    import llm_service
    from langgraph_metarec.graphs.generic_graph import GenericGraphResult

    calls = []

    async def empty_generic(**kwargs):
        calls.append(kwargs["domain"])
        return GenericGraphResult(executions=[], items=[], metadata={})

    async def injected_repair(*args, **kwargs):
        return {
            "domain_queries": {"attraction": "museums"},
            "location": "somewhere else",
        }

    monkeypatch.setattr(generic_graph_module, "run_generic_domain_graph", empty_generic)
    monkeypatch.setattr(llm_service, "propose_itinerary_repair", injected_repair)
    service, _ = make_service([])
    await service.process_recommendation_task(
        "task-itin-refine", "Plan a sightseeing day",
        {
            "domain": "itinerary", "location": "Sentosa", "date": "2026-08-03",
            "start_time": "10:00", "end_time": "17:00", "timezone": "Asia/Singapore",
            "budget_mode": "unlimited", "style": "sightseeing", "pace": "balanced",
        },
        user_id="u-refine", session_id="c-refine", use_online_agent=False,
        tool_tags=[], route=_itinerary_route(["attraction"], meals=()),
    )
    status = service.get_task_status("task-itin-refine", user_id="u-refine", session_id="c-refine")
    block = status["result"].metadata["itinerary"]
    assert calls == ["attraction", "attraction"]
    assert block["repair"]["attempt_count"] == 1
    assert block["repair"]["directive_accepted"] is False
    assert block["suppress_normal_presentation"] is True
    assert block["planning_status"] == "needs_refinement"
    assert block["refinement"]["suggested_fields"] == ["style", "pace", "attraction_types"]
