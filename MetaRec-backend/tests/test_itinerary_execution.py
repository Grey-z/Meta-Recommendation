import pytest

from conftest import make_service
from langgraph_metarec.itinerary_contracts import (
    BudgetConstraint,
    DayConstraint,
    ItineraryPlanningRequest,
    LocationConstraint,
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
                    "raw": {"gps_coordinates": {"latitude": base_lat, "longitude": 103.85}},
                },
                {
                    "id": f"a-{len(generic_calls)}-2",
                    "domain": kwargs.get("domain") or "attraction",
                    "title": f"Attraction {len(generic_calls)} alt",
                    "subtitle": "Also scenic",
                    "rating": 4.1,
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
async def test_itinerary_mode_gathers_once_per_domain_and_solves_dynamically(_itinerary_harness):
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

    assert [call["domain"] for call in generic_calls] == ["attraction"]
    assert len(restaurant_calls) == 1
    # Location anchor threaded into slot gathering.
    assert generic_calls[0]["preferences"]["location"] == "Sentosa"

    status = service.get_task_status("task-itin-1", user_id="u-itin", session_id="c-itin")
    assert status["status"] == "completed"
    block = status["result"].metadata["itinerary"]

    assert len(block["slots"]) == 3
    assert {slot["chosen"]["id"] for slot in block["slots"]} == {"a-1-1", "a-1-2", "r-1"}
    assert block["slots"][0]["chosen"]["lat"] is not None
    assert block["problem_summary"]["start_min"] == 600
    assert block["planning_status"] == "needs_refinement"  # attraction hours/prices are unknown

    # Exactly N-1 legs, each resolved through the (fake) provider once.
    assert len(block["legs"]) == 2
    assert len(leg_calls) == 2
    assert all(leg["source"] == "onemap" and leg["fare"] == "1.20 SGD" for leg in block["legs"])
    assert block["totals"]["total_travel_min"] == 30
    assert block["cost_summary"]["min"] >= 20.4
    assert block["cost_summary"]["budget_status"] == "indeterminate"
    assert status["result"].metadata["graph"] == "itinerary_graph"
    assert status["result"].metadata["domain"] == "itinerary"

    # Flattened compatibility lists carry the per-slot candidates.
    assert len(status["result"].restaurants) == 1
    assert len(status["result"].items) == 2


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
