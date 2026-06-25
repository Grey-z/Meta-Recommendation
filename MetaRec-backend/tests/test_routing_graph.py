import json

import pytest

from conftest import make_service, query_intent_json
from langgraph_metarec.graphs.routing_graph import (
    build_routing_graph,
    run_routing_graph,
    tool_tags_for_domain,
)


@pytest.mark.backend_unit
def test_routing_graph_uses_langgraph_compiled_executor():
    graph = build_routing_graph()

    assert type(graph).__name__ == "CompiledStateGraph"
    assert hasattr(graph, "ainvoke")


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_routing_graph_routes_restaurant_to_place_restaurant_tags():
    route = await run_routing_graph(
        query="Recommend spicy restaurants in Chinatown",
        intent="query",
        preferences={"location": "Chinatown"},
    )

    assert route.domain == "restaurant"
    assert route.execution_domain == "restaurant"
    assert route.status == "ready"
    assert route.mode == "single_domain"
    assert route.tool_tags == ["#place", "#restaurant"]
    assert route.is_restaurant_execution


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_routing_graph_domain_lock_overrides_query_classification():
    route = await run_routing_graph(
        query="Recommend a restaurant for tonight",
        intent="query",
        domain_lock="movie",
    )

    assert route.domain == "movie"
    assert route.execution_domain == "movie"
    assert route.status == "ready"
    assert route.tool_tags == ["#thing", "#movie"]
    assert route.reason == "domain locked by service type: movie"


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_routing_graph_restaurant_domain_lock_sets_restaurant_scope():
    route = await run_routing_graph(
        query="Recommend a film for tonight",
        intent="query",
        domain_lock="restaurant",
    )

    assert route.domain == "restaurant"
    assert route.execution_domain == "restaurant"
    assert route.status == "ready"
    assert route.tool_tags == ["#place", "#restaurant"]


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_routing_graph_retries_unknown_then_returns_domain_error():
    route = await run_routing_graph(query="Recommend something nice tonight", intent="query")

    assert route.domain == "unknown"
    assert route.execution_domain is None
    assert route.status == "domain_error"
    assert route.mode == "domain_error"
    assert route.tool_tags == []
    assert route.metadata["clarification_required"] is True


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_routing_graph_future_single_domain_does_not_execute_restaurant():
    route = await run_routing_graph(query="Recommend a hotel for tonight", intent="query")

    assert route.domain == "hotel"
    assert route.execution_domain is None
    assert route.status == "future_domain"
    assert route.tool_tags == ["#place", "#hotel"]
    assert not route.can_execute


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_routing_graph_unknown_retry_uses_preference_terms():
    route = await run_routing_graph(
        query="Recommend something nice tonight",
        intent="query",
        preferences={"restaurant_types": ["casual"], "location": "Chinatown"},
    )

    assert route.domain == "restaurant"
    assert route.execution_domain == "restaurant"
    assert route.status == "ready"
    assert route.metadata == {}


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_routing_graph_multi_domain_is_structured_future_route():
    route = await run_routing_graph(query="Recommend a movie and restaurant for tonight", intent="query")

    assert route.domain == "multi_domain"
    assert route.mode == "multi_domain"
    assert route.status == "ready"
    assert route.execution_domain == "multi_domain"
    assert {task["domain"] for task in route.domain_tasks if task["status"] == "ready"} == {"movie", "restaurant"}


@pytest.mark.backend_unit
def test_tool_tags_for_domain_normalizes_tags():
    assert tool_tags_for_domain("hotel") == ["#place", "#hotel"]


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_service_uses_routing_graph_for_generic_domain_confirmation():
    service, fake_client = make_service([query_intent_json()])

    result = await service.handle_user_request_async(
        "Recommend a relaxing music playlist",
        user_id="u-routing",
        session_id="c-routing",
        conversation_history=[],
    )

    assert result["type"] == "confirmation"
    assert result["domain"] == "music"
    assert result["routing"]["status"] == "ready"
    assert result["routing"]["execution_domain"] == "music"
    assert result["routing"]["tool_tags"] == ["#thing", "#music"]
    assert result["preferences"] == {
        "domain": "music",
        "query": "Recommend a relaxing music playlist",
    }
    assert "restaurant" not in result["confirmation_request"].message.lower()
    assert result["hitl_state"]["routing"]["execution_domain"] == "music"
    assert fake_client.chat.completions.calls == 1


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_generic_confirmation_keeps_generic_preferences_without_restaurant_leakage():
    intent_payload = json.dumps(
        {
            "intent": "query",
            "reply": "Sure, I can help with that.",
            "confidence": 0.9,
            "preferences": {
                "genres": ["science fiction"],
                "restaurant_types": ["casual"],
                "location": "Chinatown",
            },
        },
        ensure_ascii=False,
    )
    service, _ = make_service([intent_payload])

    result = await service.handle_user_request_async(
        "Recommend a science fiction movie",
        user_id="u-routing",
        session_id="c-routing-movie",
        conversation_history=[],
    )

    assert result["type"] == "confirmation"
    assert result["domain"] == "movie"
    assert result["preferences"] == {
        "genres": ["science fiction"],
        "domain": "movie",
        "query": "Recommend a science fiction movie",
    }
    assert "restaurant_types" not in result["confirmation_request"].preferences
    assert "location" not in result["confirmation_request"].preferences
    assert result["confirmation_request"].preference_form["missing_required"] == []


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_service_stores_restaurant_route_scope_for_confirmed_task():
    service, _ = make_service(
        [
            query_intent_json(),
            "I found your restaurant preferences. Is this correct?",
        ]
    )

    result = await service.handle_user_request_async(
        "Recommend spicy restaurants in Chinatown",
        user_id="u-routing",
        session_id="c-routing",
        conversation_history=[],
    )

    assert result["type"] == "confirmation"
    assert service._get_session_context("u-routing", "c-routing")["context"] == {}
    assert result["hitl_state"]["routing"]["execution_domain"] == "restaurant"
    assert result["hitl_state"]["routing"]["tool_tags"] == ["#place", "#restaurant"]
    assert result["metadata"]["thread_id"] == "u-routing:c-routing:branch-main"


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_service_returns_domain_error_clarification_for_unknown_route():
    neutral_query_intent = json.dumps(
        {
            "intent": "query",
            "reply": "Sure, I can help with that.",
            "confidence": 0.9,
            "preferences": {
                "restaurant_types": ["any"],
                "flavor_profiles": ["any"],
                "dining_purpose": "any",
                "budget_range": {"min": 20, "max": 60, "currency": "SGD", "per": "person"},
                "location": "any",
            },
        },
        ensure_ascii=False,
    )
    service, fake_client = make_service([neutral_query_intent])

    result = await service.handle_user_request_async(
        "Recommend something nice tonight",
        user_id="u-routing",
        session_id="c-routing-unknown",
        conversation_history=[],
    )

    assert result["type"] == "llm_reply"
    assert result["intent"] == "domain_error"
    assert result["routing"]["status"] == "domain_error"
    assert result["hitl_state"]["status"] == "awaiting_clarification"
    assert result["hitl_state"]["routing"]["metadata"]["clarification_required"] is True
    assert fake_client.chat.completions.calls == 1
