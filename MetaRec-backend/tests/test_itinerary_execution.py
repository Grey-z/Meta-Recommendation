import pytest

from conftest import make_service
from service import RecommendationResult, Restaurant

pytestmark = pytest.mark.backend_unit


def _itinerary_route(slots):
    return {
        "domain": "itinerary",
        "execution_domain": "itinerary",
        "mode": "itinerary",
        "status": "ready",
        "tool_tags": [],
        "domain_tasks": slots,
    }


def _slot(index, domain, label, time):
    return {
        "domain": domain,
        "source_domain": domain,
        "status": "ready",
        "tool_tags": ["#place", f"#{domain}"],
        "slot_index": index,
        "slot_label": label,
        "slot_time": time,
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
async def test_itinerary_mode_executes_slots_in_order_and_composes(_itinerary_harness):
    service, generic_calls, restaurant_calls, leg_calls = _itinerary_harness
    slots = [
        _slot(0, "attraction", "Morning activity", "10:00"),
        _slot(1, "restaurant", "Lunch", "12:30"),
        _slot(2, "attraction", "Afternoon activity", "14:30"),
    ]
    preferences = {"domain": "itinerary", "location": "Sentosa", "budget": "< 150 SGD", "start_time": "10:00"}

    await service.process_recommendation_task(
        "task-itin-1",
        "Plan my day in Sentosa",
        preferences,
        user_id="u-itin",
        session_id="c-itin",
        use_online_agent=False,
        tool_tags=[],
        route=_itinerary_route(slots),
    )

    # Both attraction slots hit the generic graph; the lunch slot the restaurant path.
    assert [call["domain"] for call in generic_calls] == ["attraction", "attraction"]
    assert len(restaurant_calls) == 1
    # Location anchor threaded into slot gathering.
    assert generic_calls[0]["preferences"]["location"] == "Sentosa"

    status = service.get_task_status("task-itin-1", user_id="u-itin", session_id="c-itin")
    assert status["status"] == "completed"
    block = status["result"].metadata["itinerary"]

    assert [slot["domain"] for slot in block["slots"]] == ["attraction", "restaurant", "attraction"]
    assert block["slots"][0]["chosen"]["id"] == "a-1-1"
    assert block["slots"][1]["chosen"]["id"] == "r-1"
    assert block["slots"][0]["chosen"]["lat"] is not None
    assert all(len(slot["alternates"]) >= 1 for slot in (block["slots"][0], block["slots"][2]))

    # Exactly N-1 legs, each resolved through the (fake) provider once.
    assert len(block["legs"]) == 2
    assert len(leg_calls) == 2
    assert all(leg["source"] == "onemap" and leg["fare"] == "1.20 SGD" for leg in block["legs"])
    assert block["totals"]["total_travel_min"] == 30
    assert block["totals"]["budget_note"].startswith("Estimated food spend ≈ 18 SGD/person")
    assert status["result"].metadata["graph"] == "itinerary_graph"
    assert status["result"].metadata["domain"] == "itinerary"

    # Flattened compatibility lists carry the per-slot candidates.
    assert len(status["result"].restaurants) == 1
    assert len(status["result"].items) == 4


@pytest.mark.asyncio
async def test_itinerary_mode_emits_per_slot_progress(_itinerary_harness):
    service, _generic_calls, _restaurant_calls, _leg_calls = _itinerary_harness
    slots = [
        _slot(0, "attraction", "Morning activity", "10:00"),
        _slot(1, "restaurant", "Lunch", "12:30"),
    ]

    await service.process_recommendation_task(
        "task-itin-2",
        "Plan my day in Sentosa",
        {"domain": "itinerary", "location": "Sentosa"},
        user_id="u-itin2",
        session_id="c-itin2",
        use_online_agent=False,
        tool_tags=[],
        route=_itinerary_route(slots),
    )

    status = service.get_task_status("task-itin-2", user_id="u-itin2", session_id="c-itin2")
    stages = [event.get("stage") for event in (status.get("metadata") or {}).get("progress_events", [])]
    assert "slot_0_attraction" in stages
    assert "slot_1_restaurant" in stages
    assert "compose_itinerary" in stages


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
        {"domain": "itinerary", "location": "Sentosa"},
        user_id="u-itin3",
        session_id="c-itin3",
        use_online_agent=False,
        tool_tags=[],
        route=_itinerary_route([_slot(0, "attraction", "Morning activity", "10:00")]),
    )

    status = service.get_task_status("task-itin-3", user_id="u-itin3", session_id="c-itin3")
    assert status["status"] == "completed"
    block = status["result"].metadata["itinerary"]
    assert block["slots"][0]["chosen"] is None
    assert block["legs"] == []
    assert status["result"].confidence_score == 0.35
