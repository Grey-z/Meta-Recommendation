from __future__ import annotations

import asyncio
import glob
import inspect
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, Tuple, TypedDict

from langgraph.graph import END, START, StateGraph

from langgraph_metarec.tool_registry import DEFAULT_TOOL_REGISTRY, ToolRegistry


ProgressCallback = Callable[[Dict[str, Any]], Awaitable[None] | None]


class RestaurantRuntimeState(TypedDict, total=False):
    query: str
    preferences: Dict[str, Any]
    user_input: str
    use_online_agent: bool
    tool_tags: List[str]
    plan_calls: List[Dict[str, Any]]
    selected_tools: List[str]
    skipped_tools: List[str]
    executions: List[Dict[str, Any]]
    summary_content: Any
    execution_data: Dict[str, Any]
    restaurants: List[Dict[str, Any]]
    checked_restaurants: List[Dict[str, Any]]
    rejection_stats: Dict[str, int]
    refine_used: bool
    progress_events: List[Dict[str, Any]]
    metadata: Dict[str, Any]
    errors: List[str]


@dataclass
class RestaurantGraphResult:
    plan_calls: List[Dict[str, Any]]
    executions: List[Dict[str, Any]]
    summary_content: Any
    execution_data: Dict[str, Any]
    restaurants: List[Dict[str, Any]]
    checked_restaurants: List[Dict[str, Any]]
    rejection_stats: Dict[str, int]
    refine_used: bool
    progress_events: List[Dict[str, Any]]
    metadata: Dict[str, Any]
    errors: List[str] = field(default_factory=list)


@dataclass
class RestaurantGraphAdapters:
    tool_registry: ToolRegistry = field(default_factory=lambda: DEFAULT_TOOL_REGISTRY)
    planner: Optional[Callable[[Any, str, str], Any]] = None
    plan_parser: Optional[Callable[[Any], List[Dict[str, Any]]]] = None
    summarizer: Optional[Callable[[Any, str, Any, Any, Any, str], Any]] = None
    summary_parser: Optional[Callable[[Any], Dict[str, Any]]] = None
    restaurant_extractor: Optional[Callable[[Dict[str, Any]], List[Dict[str, Any]]]] = None
    consistency_checker: Optional[
        Callable[[List[Dict[str, Any]], Dict[str, Any], str], Tuple[List[Dict[str, Any]], Dict[str, int]]]
    ] = None
    refine_once: Optional[
        Callable[[str, Dict[str, Any], List[Dict[str, Any]], Any, Dict[str, int]], Awaitable[Tuple[List[Dict[str, Any]], Any]]]
    ] = None
    offline_loader: Optional[Callable[[], Dict[str, Any]]] = None
    offline_summary_loader: Optional[Callable[[], Any]] = None


def _default_planner(client: Any, user_input: str, planning_model: str) -> Any:
    from agent.agent_plan import run_demo

    return run_demo(client, user_input, planning_model)


def _default_plan_parser(response: Any) -> List[Dict[str, Any]]:
    if isinstance(response, list):
        return response
    from langgraph_metarec.legacy_adapters.agent import parse_planner_output

    return parse_planner_output(response)


def _default_summarizer(
    client: Any,
    user_input: str,
    gmap_results: Any,
    xhs_results: Any,
    yelp_results: Any,
    summary_model: str,
) -> Any:
    from agent.agent_summary import summarize_recommendations

    response = summarize_recommendations(
        client,
        user_input,
        gmap_results,
        xhs_results,
        yelp_results,
        summary_model,
    )
    return response.choices[0].message.content if response and response.choices else None


def _default_summary_parser(summary_content: Any) -> Dict[str, Any]:
    if not summary_content:
        return {"summary": None}
    if isinstance(summary_content, dict):
        return {"summary": summary_content}
    try:
        return {"summary": json.loads(summary_content)}
    except Exception:
        return {"summary": {"raw": summary_content}}


def _default_restaurant_extractor(execution_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    summary = execution_data.get("summary")
    recommendations = summary.get("recommendations") if isinstance(summary, dict) else None
    if not recommendations:
        return []
    restaurants: List[Dict[str, Any]] = []
    for idx, rec in enumerate(recommendations):
        restaurants.append(
            {
                "id": f"rec_{idx}_{str(rec.get('name', '')).replace(' ', '_')}",
                "name": rec.get("name", ""),
                "address": rec.get("address"),
                "area": rec.get("area"),
                "cuisine": rec.get("cuisine"),
                "type": rec.get("type"),
                "location": rec.get("area"),
                "rating": rec.get("rating"),
                "reviews_count": rec.get("reviews_count"),
                "price": rec.get("price"),
                "price_per_person_sgd": rec.get("price_per_person_sgd"),
                "distance_or_walk_time": rec.get("distance_or_walk_time"),
                "open_hours_note": rec.get("open_hours_note"),
                "flavor_match": rec.get("flavor_match", []),
                "purpose_match": rec.get("purpose_match", []),
                "why": rec.get("why"),
                "reason": rec.get("why"),
                "sources": rec.get("sources"),
                "phone": rec.get("phone"),
                "gps_coordinates": rec.get("gps_coordinates"),
            }
        )
    return restaurants


def _default_consistency_checker(
    restaurants: List[Dict[str, Any]],
    preferences: Dict[str, Any],
    query: str,
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    return restaurants, {}


def _default_offline_loader() -> Dict[str, Any]:
    from langgraph_metarec.legacy_adapters.agent import load_latest_results

    return load_latest_results()


def _default_offline_summary_loader() -> Any:
    base_dir = Path(__file__).resolve().parents[2] / "agent"
    summary_log_dir = base_dir / "agent_log" / "agent_summary"
    summary_files = sorted(glob.glob(str(summary_log_dir / "agent_summary_result_*.json")), reverse=True)
    for file_name in summary_files:
        try:
            with open(file_name, "r", encoding="utf-8") as file:
                payload = json.load(file)
            summary = payload.get("summary")
            if isinstance(summary, dict):
                return json.dumps(summary, ensure_ascii=False)
            if isinstance(summary, str):
                return summary
        except Exception:
            continue

    demo_files = sorted(glob.glob(str(base_dir / "demo_res_log" / "demo_res_*.json")), reverse=True)
    for file_name in demo_files:
        try:
            with open(file_name, "r", encoding="utf-8") as file:
                payload = json.load(file)
            summary = payload.get("summary")
            if isinstance(summary, dict):
                return json.dumps(summary, ensure_ascii=False)
            if isinstance(summary, str):
                return summary
        except Exception:
            continue
    return None


async def _emit(
    state: RestaurantRuntimeState,
    progress_callback: Optional[ProgressCallback],
    event: Dict[str, Any],
) -> None:
    events = list(state.get("progress_events", []))
    events.append(event)
    state["progress_events"] = events
    if progress_callback:
        result = progress_callback(event)
        if inspect.isawaitable(result):
            await result  # type: ignore[misc]


def _extract_tool_outputs(executions: Iterable[Dict[str, Any]]) -> Tuple[Any, Any, Any]:
    gmap_results = None
    xhs_results = None
    yelp_results = None
    for item in executions or []:
        if item.get("tool") == "gmap.search":
            gmap_results = item.get("output")
        elif item.get("tool") == "xhs.search":
            xhs_results = item.get("output")
        elif item.get("tool") == "yelp.search":
            yelp_results = item.get("output")
    return gmap_results, xhs_results, yelp_results


def _sort_top_rated(restaurants: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(
        restaurants,
        key=lambda item: ((item.get("rating") or 0), (item.get("reviews_count") or 0)),
        reverse=True,
    )


def build_restaurant_graph(
    *,
    client: Any,
    summary_model: str,
    planning_model: str,
    adapters: Optional[RestaurantGraphAdapters] = None,
    progress_callback: Optional[ProgressCallback] = None,
):
    adapters = adapters or RestaurantGraphAdapters()
    registry = adapters.tool_registry
    planner = adapters.planner or _default_planner
    plan_parser = adapters.plan_parser or _default_plan_parser
    summarizer = adapters.summarizer or _default_summarizer
    summary_parser = adapters.summary_parser or _default_summary_parser
    restaurant_extractor = adapters.restaurant_extractor or _default_restaurant_extractor
    consistency_checker = adapters.consistency_checker or _default_consistency_checker
    offline_loader = adapters.offline_loader or _default_offline_loader
    offline_summary_loader = adapters.offline_summary_loader or _default_offline_summary_loader

    def _allowed_tools(use_online_agent: bool, tool_tags: List[str]) -> List[str]:
        specs = registry.resolve(
            domain="restaurant",
            tags=tool_tags,
            include_online_only=use_online_agent,
        )
        return [spec.name for spec in specs if spec.name != "gmap.source_matcher"]

    async def candidate_gather(state: RestaurantRuntimeState) -> RestaurantRuntimeState:
        await _emit(
            state,
            progress_callback,
            {"stage": "candidate_gather", "stage_number": 1, "status": "started", "progress": 10, "message": "Gathering restaurant candidates..."},
        )
        tool_tags = state.get("tool_tags") or ["#place", "#restaurant"]
        allowed_names = set(_allowed_tools(bool(state.get("use_online_agent")), tool_tags))
        state["selected_tools"] = sorted(allowed_names)
        state["skipped_tools"] = []

        if state.get("use_online_agent"):
            planning_response = await asyncio.to_thread(planner, client, state["user_input"], planning_model)
            raw_plan_calls = plan_parser(planning_response)
            plan_calls = [
                call for call in raw_plan_calls
                if call.get("name") in allowed_names
            ]
            state["skipped_tools"] = [
                str(call.get("name"))
                for call in raw_plan_calls
                if call.get("name") not in allowed_names
            ]
            executions: List[Dict[str, Any]] = []
            quota_tracker: Dict[str, int] = {}
            total = max(len(plan_calls), 1)
            for idx, call in enumerate(plan_calls, start=1):
                name = str(call.get("name", ""))
                params = call.get("parameters") or {}
                await _emit(
                    state,
                    progress_callback,
                    {
                        "stage": "candidate_gather",
                        "stage_number": 1,
                        "status": "in_progress",
                        "progress": 20 + int((idx / total) * 40),
                        "message": f"Executing: {name}",
                        "tool": name,
                        "query": params.get("query", ""),
                    },
                )
                executions.append(await asyncio.to_thread(registry.dispatch, name, params, quota_tracker=quota_tracker))
        else:
            cached = await asyncio.to_thread(offline_loader)
            raw_plan_calls = cached.get("plan_calls", []) if cached else []
            raw_executions = cached.get("executions", []) if cached else []
            plan_calls = [call for call in raw_plan_calls if call.get("name") in allowed_names]
            executions = [item for item in raw_executions if item.get("tool") in allowed_names]
            state["skipped_tools"] = [
                str(call.get("name"))
                for call in raw_plan_calls
                if call.get("name") not in allowed_names
            ]

        state["plan_calls"] = plan_calls
        state["executions"] = executions
        await _emit(
            state,
            progress_callback,
            {
                "stage": "candidate_gather",
                "stage_number": 1,
                "status": "completed",
                "progress": 65,
                "message": "Restaurant candidate gathering completed",
                "tools": [call.get("name") for call in plan_calls],
            },
        )
        return state

    async def rerank_and_summarize(state: RestaurantRuntimeState) -> RestaurantRuntimeState:
        await _emit(
            state,
            progress_callback,
            {"stage": "rerank_and_summarize", "stage_number": 2, "status": "started", "progress": 70, "message": "Ranking and summarizing restaurants..."},
        )
        summary_content = None
        if not state.get("use_online_agent"):
            summary_content = await asyncio.to_thread(offline_summary_loader)

        if not summary_content:
            gmap_results, xhs_results, yelp_results = _extract_tool_outputs(state.get("executions", []))
            summary_content = await asyncio.to_thread(
                summarizer,
                client,
                state["user_input"],
                gmap_results,
                xhs_results,
                yelp_results,
                summary_model,
            )

        state["summary_content"] = summary_content
        await _emit(
            state,
            progress_callback,
            {
                "stage": "rerank_and_summarize",
                "stage_number": 2,
                "status": "completed",
                "progress": 85,
                "message": "Restaurant ranking summary completed",
                "summary_length": len(summary_content) if summary_content else 0,
            },
        )
        return state

    async def validation_and_calibration(state: RestaurantRuntimeState) -> RestaurantRuntimeState:
        await _emit(
            state,
            progress_callback,
            {"stage": "validation_and_calibration", "stage_number": 3, "status": "started", "progress": 90, "message": "Validating recommendation quality..."},
        )
        execution_data = {
            "executions": state.get("executions", []),
            **summary_parser(state.get("summary_content")),
        }
        restaurants = restaurant_extractor(execution_data)
        checked_restaurants, rejection_stats = consistency_checker(
            restaurants,
            state.get("preferences", {}),
            state.get("query", ""),
        )

        refine_used = False
        if restaurants and not checked_restaurants and state.get("use_online_agent") and adapters.refine_once:
            refine_used = True
            refined_restaurants, refined_summary = await adapters.refine_once(
                state.get("query", ""),
                state.get("preferences", {}),
                state.get("executions", []),
                execution_data.get("summary"),
                rejection_stats,
            )
            if refined_summary:
                state["summary_content"] = refined_summary
                execution_data = {
                    "executions": state.get("executions", []),
                    **summary_parser(refined_summary),
                }
            if refined_restaurants:
                checked_restaurants, refined_rejection_stats = consistency_checker(
                    refined_restaurants,
                    state.get("preferences", {}),
                    state.get("query", ""),
                )
                restaurants = refined_restaurants
                if refined_rejection_stats:
                    rejection_stats = refined_rejection_stats

        if not checked_restaurants and restaurants:
            checked_restaurants = _sort_top_rated(restaurants)[:5]
            if not rejection_stats:
                rejection_stats = {"all_removed_without_explicit_reason": len(restaurants)}

        state["execution_data"] = execution_data
        state["restaurants"] = restaurants
        state["checked_restaurants"] = checked_restaurants
        state["rejection_stats"] = rejection_stats
        state["refine_used"] = refine_used
        await _emit(
            state,
            progress_callback,
            {
                "stage": "validation_and_calibration",
                "stage_number": 3,
                "status": "completed",
                "progress": 95,
                "message": "Restaurant validation completed",
                "raw_count": len(restaurants),
                "final_count": len(checked_restaurants),
            },
        )
        return state

    async def recommendation_result(state: RestaurantRuntimeState) -> RestaurantRuntimeState:
        state["metadata"] = {
            "domain": "restaurant",
            "graph": "restaurant_graph",
            "tool_tags": state.get("tool_tags", []),
            "selected_tools": state.get("selected_tools", []),
            "skipped_tools": state.get("skipped_tools", []),
            "plan_calls": state.get("plan_calls", []),
            "executions": state.get("executions", []),
            "consistency_check": {
                "raw_count": len(state.get("restaurants", [])),
                "final_count": len(state.get("checked_restaurants", [])),
                "rejection_stats": state.get("rejection_stats", {}),
                "refine_used": state.get("refine_used", False),
            },
        }
        await _emit(
            state,
            progress_callback,
            {"stage": "recommendation_result", "stage_number": 4, "status": "completed", "progress": 100, "message": "Recommendations ready!"},
        )
        return state

    graph = StateGraph(RestaurantRuntimeState)
    graph.add_node("candidate_gather", candidate_gather)
    graph.add_node("rerank_and_summarize", rerank_and_summarize)
    graph.add_node("validation_and_calibration", validation_and_calibration)
    graph.add_node("recommendation_result", recommendation_result)
    graph.add_edge(START, "candidate_gather")
    graph.add_edge("candidate_gather", "rerank_and_summarize")
    graph.add_edge("rerank_and_summarize", "validation_and_calibration")
    graph.add_edge("validation_and_calibration", "recommendation_result")
    graph.add_edge("recommendation_result", END)
    return graph.compile()


async def run_restaurant_graph(
    *,
    client: Any,
    summary_model: str,
    planning_model: str,
    query: str,
    preferences: Dict[str, Any],
    user_input: str,
    use_online_agent: bool,
    tool_tags: Optional[List[str]] = None,
    adapters: Optional[RestaurantGraphAdapters] = None,
    progress_callback: Optional[ProgressCallback] = None,
) -> RestaurantGraphResult:
    graph = build_restaurant_graph(
        client=client,
        summary_model=summary_model,
        planning_model=planning_model,
        adapters=adapters,
        progress_callback=progress_callback,
    )
    final_state = await graph.ainvoke(
        {
            "query": query,
            "preferences": preferences,
            "user_input": user_input,
            "use_online_agent": use_online_agent,
            "tool_tags": tool_tags or ["#place", "#restaurant"],
            "plan_calls": [],
            "selected_tools": [],
            "skipped_tools": [],
            "executions": [],
            "restaurants": [],
            "checked_restaurants": [],
            "rejection_stats": {},
            "refine_used": False,
            "progress_events": [],
            "metadata": {},
            "errors": [],
        }
    )
    return RestaurantGraphResult(
        plan_calls=final_state.get("plan_calls", []),
        executions=final_state.get("executions", []),
        summary_content=final_state.get("summary_content"),
        execution_data=final_state.get("execution_data", {}),
        restaurants=final_state.get("restaurants", []),
        checked_restaurants=final_state.get("checked_restaurants", []),
        rejection_stats=final_state.get("rejection_stats", {}),
        refine_used=final_state.get("refine_used", False),
        progress_events=final_state.get("progress_events", []),
        metadata=final_state.get("metadata", {}),
        errors=final_state.get("errors", []),
    )
