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
async def test_routing_graph_keeps_unknown_compatible_with_restaurant():
    route = await run_routing_graph(query="Recommend something nice tonight", intent="query")

    assert route.domain == "unknown"
    assert route.execution_domain == "restaurant"
    assert route.status == "ready"
    assert route.tool_tags == ["#place", "#restaurant"]


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_routing_graph_future_single_domain_does_not_execute_restaurant():
    route = await run_routing_graph(query="Recommend a relaxing music playlist", intent="query")

    assert route.domain == "music"
    assert route.execution_domain is None
    assert route.status == "future_domain"
    assert route.tool_tags == ["#thing", "#music"]
    assert not route.can_execute


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_routing_graph_multi_domain_is_structured_future_route():
    route = await run_routing_graph(query="Recommend a movie and restaurant for tonight", intent="query")

    assert route.domain == "multi_domain"
    assert route.mode == "multi_domain"
    assert route.status == "future_multi_domain"
    assert route.execution_domain is None


@pytest.mark.backend_unit
def test_tool_tags_for_domain_normalizes_tags():
    assert tool_tags_for_domain("hotel") == ["#place", "#hotel"]


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_service_uses_routing_graph_for_future_domain_response():
    service, fake_client = make_service([query_intent_json()])

    result = await service.handle_user_request_async(
        "Recommend a relaxing music playlist",
        user_id="u-routing",
        session_id="c-routing",
        conversation_history=[],
    )

    assert result["type"] == "llm_reply"
    assert result["intent"] == "future_domain"
    assert result["domain"] == "music"
    assert result["routing"]["status"] == "future_domain"
    assert result["routing"]["tool_tags"] == ["#thing", "#music"]
    assert fake_client.chat.completions.calls == 1


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
    context = service._get_session_context("u-routing", "c-routing")["context"]

    assert result["type"] == "confirmation"
    assert context["routing"]["execution_domain"] == "restaurant"
    assert context["routing"]["tool_tags"] == ["#place", "#restaurant"]
