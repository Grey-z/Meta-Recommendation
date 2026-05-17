from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Set


ToolAdapter = Callable[[Dict[str, Any]], Any]


def normalize_tag(tag: str) -> str:
    value = str(tag or "").strip().lower()
    if not value:
        return value
    return value if value.startswith("#") else f"#{value}"


@dataclass(frozen=True)
class ToolSpec:
    name: str
    domain: str
    tags: Set[str]
    input_schema: Dict[str, Any]
    output_schema: Dict[str, Any]
    adapter: ToolAdapter
    online_only: bool = False
    status: str = "active"
    description: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "domain", self.domain.lower())
        object.__setattr__(self, "tags", {normalize_tag(tag) for tag in self.tags})

    def matches(
        self,
        *,
        domain: Optional[str] = None,
        tags: Optional[Iterable[str]] = None,
        include_online_only: bool = True,
        active_only: bool = True,
    ) -> bool:
        if domain and self.domain != domain.lower():
            return False
        if active_only and self.status != "active":
            return False
        if self.online_only and not include_online_only:
            return False
        required_tags = {normalize_tag(tag) for tag in (tags or []) if tag}
        return required_tags.issubset(self.tags)


@dataclass
class ToolRegistry:
    _tools: Dict[str, ToolSpec] = field(default_factory=dict)

    def register(self, spec: ToolSpec) -> None:
        if not spec.name:
            raise ValueError("Tool name is required")
        if spec.name in self._tools:
            raise ValueError(f"Tool already registered: {spec.name}")
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise KeyError(f"Unknown tool: {name}") from exc

    def names(self) -> List[str]:
        return sorted(self._tools)

    def resolve(
        self,
        *,
        domain: Optional[str] = None,
        tags: Optional[Iterable[str]] = None,
        include_online_only: bool = True,
        active_only: bool = True,
    ) -> List[ToolSpec]:
        return sorted(
            [
                spec
                for spec in self._tools.values()
                if spec.matches(
                    domain=domain,
                    tags=tags,
                    include_online_only=include_online_only,
                    active_only=active_only,
                )
            ],
            key=lambda spec: spec.name,
        )

    def dispatch(self, name: str, parameters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        spec = self.get(name)
        if spec.status != "active":
            return {
                "tool": name,
                "input": parameters or {},
                "success": False,
                "error": f"Tool is not active: {spec.status}",
            }
        try:
            output = spec.adapter(parameters or {})
            return {
                "tool": name,
                "input": parameters or {},
                "output": output,
                "success": output is not None,
            }
        except Exception as exc:
            return {
                "tool": name,
                "input": parameters or {},
                "success": False,
                "error": str(exc),
            }


def _gmap_search_adapter(parameters: Dict[str, Any]) -> Any:
    from agent.agent_mcp.agent_google_map import search_google_maps

    return search_google_maps(
        query=parameters.get("query", ""),
        max_results=int(parameters.get("max_results", 10)),
    )


def _xhs_search_adapter(parameters: Dict[str, Any]) -> Any:
    from agent.agent_mcp.agent_xiaohongshu import search_notes_by_keyword

    return search_notes_by_keyword(
        keyword=parameters.get("query", ""),
        max_results=int(parameters.get("max_results", 10)),
    )


def _yelp_search_adapter(parameters: Dict[str, Any]) -> Any:
    from agent.agent_mcp.agent_yelp import search_yelp_organic_results

    return search_yelp_organic_results(
        query=parameters.get("query", ""),
        location=parameters.get("location", "Singapore"),
        max_results=int(parameters.get("max_results", 10)),
    )


def _gmap_source_matcher_adapter(parameters: Dict[str, Any]) -> Any:
    return {
        "candidates": parameters.get("candidates", []),
        "reference_results": parameters.get("reference_results", []),
        "matches": [],
        "status": "passthrough",
    }


def build_default_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()

    registry.register(
        ToolSpec(
            name="gmap.search",
            domain="restaurant",
            tags={"#place", "#restaurant", "#review", "#map"},
            input_schema={
                "type": "object",
                "required": ["query"],
                "properties": {"query": {"type": "string"}, "max_results": {"type": "integer"}},
            },
            output_schema={"type": "array", "items": {"type": "object"}},
            adapter=_gmap_search_adapter,
            description="Search Google Maps for restaurant/place candidates.",
        )
    )
    registry.register(
        ToolSpec(
            name="xhs.search",
            domain="restaurant",
            tags={"#place", "#restaurant", "#review", "#social"},
            input_schema={
                "type": "object",
                "required": ["query"],
                "properties": {"query": {"type": "string"}, "max_results": {"type": "integer"}},
            },
            output_schema={"type": "array", "items": {"type": "object"}},
            adapter=_xhs_search_adapter,
            description="Search Xiaohongshu notes for social/review evidence.",
        )
    )
    registry.register(
        ToolSpec(
            name="yelp.search",
            domain="restaurant",
            tags={"#place", "#restaurant", "#review"},
            input_schema={
                "type": "object",
                "required": ["query", "location"],
                "properties": {
                    "query": {"type": "string"},
                    "location": {"type": "string"},
                    "max_results": {"type": "integer"},
                },
            },
            output_schema={"type": "array", "items": {"type": "object"}},
            adapter=_yelp_search_adapter,
            description="Search Yelp for restaurant review candidates.",
        )
    )
    registry.register(
        ToolSpec(
            name="gmap.source_matcher",
            domain="restaurant",
            tags={"#place", "#restaurant", "#map", "#source_match"},
            input_schema={
                "type": "object",
                "properties": {
                    "candidates": {"type": "array", "items": {"type": "object"}},
                    "reference_results": {"type": "array", "items": {"type": "object"}},
                },
            },
            output_schema={"type": "object"},
            adapter=_gmap_source_matcher_adapter,
            description="Match restaurant candidates against Google Maps source records.",
        )
    )

    return registry


DEFAULT_TOOL_REGISTRY = build_default_tool_registry()
