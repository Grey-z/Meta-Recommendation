from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from langgraph_metarec.nodes.domain import classify_domain
from langgraph_metarec.tool_registry import normalize_tag


DOMAIN_TOOL_TAGS: Dict[str, List[str]] = {
    "restaurant": ["#place", "#restaurant"],
    "unknown": ["#place", "#restaurant"],
    "hotel": ["#place", "#hotel"],
    "music": ["#thing", "#music"],
    "movie": ["#thing", "#movie"],
    "book": ["#thing", "#book"],
}


@dataclass
class DomainRoute:
    domain: str
    mode: str
    status: str
    tool_tags: List[str]
    domain_confidence: float = 0.0
    reason: Optional[str] = None
    execution_domain: Optional[str] = None
    domain_tasks: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def can_execute(self) -> bool:
        return self.status == "ready" and bool(self.execution_domain)

    @property
    def is_restaurant_execution(self) -> bool:
        return self.can_execute and self.execution_domain == "restaurant"


class RoutingRuntimeState(TypedDict, total=False):
    query: str
    intent: Optional[str]
    preferences: Optional[Dict[str, Any]]
    domain: str
    domain_confidence: float
    domain_reason: Optional[str]
    mode: str
    route: DomainRoute
    errors: List[str]


def tool_tags_for_domain(domain: str) -> List[str]:
    return [normalize_tag(tag) for tag in DOMAIN_TOOL_TAGS.get(domain, [])]


def _future_domain_route(domain: str, confidence: float, reason: str) -> DomainRoute:
    return DomainRoute(
        domain=domain,
        execution_domain=None,
        mode="single_domain",
        status="future_domain",
        tool_tags=tool_tags_for_domain(domain),
        domain_confidence=confidence,
        reason=reason,
        domain_tasks=[
            {
                "domain": domain,
                "status": "future_domain",
                "tool_tags": tool_tags_for_domain(domain),
            }
        ],
    )


def build_routing_graph():
    def domain_classification(runtime_state: RoutingRuntimeState) -> RoutingRuntimeState:
        domain, confidence, reason = classify_domain(runtime_state.get("query", ""))
        return {
            **runtime_state,
            "domain": domain,
            "domain_confidence": confidence,
            "domain_reason": reason,
            "mode": "multi_domain" if domain == "multi_domain" else "single_domain",
        }

    def route_after_classification(runtime_state: RoutingRuntimeState) -> str:
        return "multi_domain" if runtime_state.get("mode") == "multi_domain" else "single_domain"

    def single_domain(runtime_state: RoutingRuntimeState) -> RoutingRuntimeState:
        domain = runtime_state.get("domain", "unknown")
        confidence = float(runtime_state.get("domain_confidence", 0.0))
        reason = runtime_state.get("domain_reason")

        if domain in {"restaurant", "unknown"}:
            execution_domain = "restaurant"
            route = DomainRoute(
                domain=domain,
                execution_domain=execution_domain,
                mode="single_domain",
                status="ready",
                tool_tags=tool_tags_for_domain(execution_domain),
                domain_confidence=confidence,
                reason=reason or "restaurant-compatible route",
                domain_tasks=[
                    {
                        "domain": execution_domain,
                        "source_domain": domain,
                        "status": "ready",
                        "tool_tags": tool_tags_for_domain(execution_domain),
                    }
                ],
            )
        else:
            route = _future_domain_route(domain, confidence, reason or f"{domain} domain is not connected")

        return {**runtime_state, "route": route}

    def multi_domain(runtime_state: RoutingRuntimeState) -> RoutingRuntimeState:
        confidence = float(runtime_state.get("domain_confidence", 0.0))
        reason = runtime_state.get("domain_reason") or "multi-domain request detected"
        route = DomainRoute(
            domain="multi_domain",
            execution_domain=None,
            mode="multi_domain",
            status="future_multi_domain",
            tool_tags=[],
            domain_confidence=confidence,
            reason=reason,
            domain_tasks=[],
            metadata={"decomposition_status": "phase_3"},
        )
        return {**runtime_state, "route": route}

    graph = StateGraph(RoutingRuntimeState)
    graph.add_node("domain_classification", domain_classification)
    graph.add_node("single_domain", single_domain)
    graph.add_node("multi_domain", multi_domain)
    graph.add_edge(START, "domain_classification")
    graph.add_conditional_edges(
        "domain_classification",
        route_after_classification,
        {"single_domain": "single_domain", "multi_domain": "multi_domain"},
    )
    graph.add_edge("single_domain", END)
    graph.add_edge("multi_domain", END)
    return graph.compile()


async def run_routing_graph(
    *,
    query: str,
    intent: Optional[str] = None,
    preferences: Optional[Dict[str, Any]] = None,
) -> DomainRoute:
    graph = build_routing_graph()
    final_state = await graph.ainvoke(
        {
            "query": query,
            "intent": intent,
            "preferences": preferences,
            "errors": [],
        }
    )
    route = final_state.get("route")
    if route is None:
        raise RuntimeError("Routing graph finished without a route")
    return route
