import json

import pytest

from conftest import make_service
from langgraph_metarec.graphs.restaurant_graph import (
    RestaurantGraphAdapters,
    RestaurantGraphResult,
    build_restaurant_graph,
    run_restaurant_graph,
)
from langgraph_metarec.tool_registry import ToolRegistry, ToolSpec


def _fake_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="gmap.search",
            domain="restaurant",
            tags={"#place", "#restaurant", "#map", "#review"},
            input_schema={"type": "object"},
            output_schema={"type": "array"},
            adapter=lambda params: [{"title": "Graph Bistro", "rating": 4.7, "reviews": 100}],
        )
    )
    registry.register(
        ToolSpec(
            name="amazon.search",
            domain="product",
            tags={"#thing", "#shopping"},
            input_schema={"type": "object"},
            output_schema={"type": "array"},
            adapter=lambda params: [{"title": "Not a restaurant"}],
        )
    )
    return registry


@pytest.mark.backend_unit
def test_restaurant_graph_uses_langgraph_compiled_executor():
    graph = build_restaurant_graph(
        client=object(),
        summary_model="summary-model",
        planning_model="planning-model",
        adapters=RestaurantGraphAdapters(
            tool_registry=_fake_registry(),
            planner=lambda client, user_input, model: [],
            summarizer=lambda client, user_input, gmap, xhs, yelp, model: "{}",
        ),
    )

    assert type(graph).__name__ == "CompiledStateGraph"
    assert hasattr(graph, "ainvoke")


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_restaurant_graph_scopes_tools_and_returns_compatible_candidates():
    progress_events = []

    def fake_planner(client, user_input, model):
        return [
            {"name": "gmap.search", "parameters": {"query": "Singapore ramen"}},
            {"name": "amazon.search", "parameters": {"query": "ramen bowl"}},
        ]

    def fake_summarizer(client, user_input, gmap_results, xhs_results, yelp_results, model):
        assert gmap_results == [{"title": "Graph Bistro", "rating": 4.7, "reviews": 100}]
        assert xhs_results is None
        assert yelp_results is None
        return json.dumps(
            {
                "recommendations": [
                    {
                        "name": "Graph Bistro",
                        "area": "Chinatown",
                        "cuisine": "Japanese",
                        "type": "casual",
                        "price_per_person_sgd": "20-30",
                        "rating": 4.7,
                        "reviews_count": 100,
                        "flavor_match": ["Umami"],
                        "purpose_match": ["Friends"],
                        "why": "Good fit from graph test.",
                    }
                ]
            }
        )

    result = await run_restaurant_graph(
        client=object(),
        summary_model="summary-model",
        planning_model="planning-model",
        query="Recommend ramen in Chinatown",
        preferences={"location": "Chinatown"},
        user_input='{"Location (Singapore)": "Chinatown"}',
        use_online_agent=True,
        tool_tags=["#place", "#restaurant"],
        adapters=RestaurantGraphAdapters(
            tool_registry=_fake_registry(),
            planner=fake_planner,
            plan_parser=lambda response: response,
            summarizer=fake_summarizer,
        ),
        progress_callback=lambda event: progress_events.append(event),
    )

    assert [call["name"] for call in result.plan_calls] == ["gmap.search"]
    assert result.metadata["skipped_tools"] == ["amazon.search"]
    assert result.metadata["tool_tags"] == ["#place", "#restaurant"]
    assert result.checked_restaurants[0]["name"] == "Graph Bistro"
    assert result.metadata["graph"] == "restaurant_graph"
    assert progress_events[-1]["stage"] == "recommendation_result"


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_restaurant_graph_falls_back_to_top_rated_when_validation_removes_all():
    def fake_summarizer(client, user_input, gmap_results, xhs_results, yelp_results, model):
        return {
            "recommendations": [
                {"name": "Low Rated", "rating": 3.8, "reviews_count": 200},
                {"name": "High Rated", "rating": 4.9, "reviews_count": 20},
            ]
        }

    result = await run_restaurant_graph(
        client=object(),
        summary_model="summary-model",
        planning_model="planning-model",
        query="Recommend a restaurant",
        preferences={},
        user_input="{}",
        use_online_agent=True,
        adapters=RestaurantGraphAdapters(
            tool_registry=_fake_registry(),
            planner=lambda client, user_input, model: [],
            plan_parser=lambda response: response,
            summarizer=fake_summarizer,
            consistency_checker=lambda restaurants, preferences, query: ([], {"forced_reject": len(restaurants)}),
        ),
    )

    assert result.checked_restaurants[0]["name"] == "High Rated"
    assert result.rejection_stats == {"forced_reject": 2}


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_service_process_recommendation_task_uses_restaurant_graph(monkeypatch):
    service, _ = make_service([])
    task_id = "task-graph"
    session_ctx = service._get_session_context("u-1", "c-1")
    session_ctx["tasks"][task_id] = {
        "task_id": task_id,
        "status": "pending",
        "progress": 0,
        "message": "Task created",
        "result": None,
        "error": None,
    }

    async def fake_run_restaurant_graph(**kwargs):
        assert kwargs["tool_tags"] == ["#place", "#restaurant"]
        await kwargs["progress_callback"](
            {
                "stage": "candidate_gather",
                "stage_number": 1,
                "status": "completed",
                "progress": 65,
                "message": "fake gather done",
            }
        )
        return RestaurantGraphResult(
            plan_calls=[{"name": "gmap.search", "parameters": {"query": "test"}}],
            executions=[{"tool": "gmap.search", "success": True, "output": []}],
            summary_content={},
            execution_data={},
            restaurants=[{"name": "Graph Service Bistro", "rating": 4.8}],
            checked_restaurants=[
                {
                    "id": "graph-service-bistro",
                    "name": "Graph Service Bistro",
                    "area": "Chinatown",
                    "rating": 4.8,
                    "reviews_count": 10,
                    "why": "Generated by fake graph.",
                }
            ],
            rejection_stats={},
            refine_used=False,
            progress_events=[],
            metadata={
                "graph": "restaurant_graph",
                "domain": "restaurant",
                "selected_tools": ["gmap.search"],
                "skipped_tools": [],
            },
        )

    import langgraph_metarec.graphs.restaurant_graph as restaurant_graph_module

    monkeypatch.setattr(restaurant_graph_module, "run_restaurant_graph", fake_run_restaurant_graph)

    await service.process_recommendation_task(
        task_id,
        "Recommend a restaurant",
        {"location": "Chinatown"},
        user_id="u-1",
        session_id="c-1",
        use_online_agent=True,
        tool_tags=["#place", "#restaurant"],
    )

    status = service.get_task_status(task_id, user_id="u-1", session_id="c-1")

    assert status["status"] == "completed"
    assert status["result"].restaurants[0].name == "Graph Service Bistro"
    assert status["result"].metadata["graph"] == "restaurant_graph"
    assert status["metadata"]["task_thread_id"] == "u-1:c-1:branch-main:task-graph"
    assert status["metadata"]["result_metadata"]["domain"] == "restaurant"
