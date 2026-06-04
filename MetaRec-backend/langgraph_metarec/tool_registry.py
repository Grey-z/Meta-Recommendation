from __future__ import annotations

import concurrent.futures
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Set

from pydantic import BaseModel, ConfigDict, Field, ValidationError


ToolAdapter = Callable[[Dict[str, Any]], Any]
DEFAULT_TOOL_TIMEOUT_SECONDS = 12.0
DEFAULT_TOOL_QUOTA_PER_RUN = 5


class ToolDispatchEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: str
    parameters: Dict[str, Any] = Field(default_factory=dict)


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
    timeout_seconds: float = DEFAULT_TOOL_TIMEOUT_SECONDS
    quota_per_run: int = DEFAULT_TOOL_QUOTA_PER_RUN

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError("Tool timeout_seconds must be greater than 0")
        if self.quota_per_run <= 0:
            raise ValueError("Tool quota_per_run must be greater than 0")
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

    def dispatch(
        self,
        name: str,
        parameters: Optional[Dict[str, Any]] = None,
        *,
        quota_tracker: Optional[Dict[str, int]] = None,
    ) -> Dict[str, Any]:
        spec = self.get(name)
        try:
            envelope = ToolDispatchEnvelope(tool=name, parameters=parameters or {})
        except ValidationError as exc:
            return {
                "tool": name,
                "input": parameters or {},
                "success": False,
                "error": f"Tool dispatch envelope validation failed: {exc.errors()}",
            }
        if spec.status != "active":
            return {
                "tool": name,
                "input": envelope.parameters,
                "success": False,
                "error": f"Tool is not active: {spec.status}",
            }

        input_errors = validate_json_schema(spec.input_schema, envelope.parameters, "input")
        if input_errors:
            return {
                "tool": name,
                "input": envelope.parameters,
                "success": False,
                "error": "Tool input schema validation failed: " + "; ".join(input_errors),
            }

        quota_used = None
        if quota_tracker is not None:
            quota_used = int(quota_tracker.get(name, 0))
            if quota_used >= spec.quota_per_run:
                return {
                    "tool": name,
                    "input": envelope.parameters,
                    "success": False,
                    "error": f"Tool quota exceeded: {quota_used}/{spec.quota_per_run} calls used",
                    "metadata": {
                        "quota_per_run": spec.quota_per_run,
                        "quota_used": quota_used,
                        "timeout_seconds": spec.timeout_seconds,
                    },
                }
            quota_used += 1
            quota_tracker[name] = quota_used

        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"tool-{name}")
        try:
            future = executor.submit(spec.adapter, envelope.parameters)
            output = future.result(timeout=spec.timeout_seconds)
            output_errors = validate_json_schema(spec.output_schema, output, "output")
            if output_errors:
                return {
                    "tool": name,
                    "input": envelope.parameters,
                    "output": output,
                    "success": False,
                    "error": "Tool output schema validation failed: " + "; ".join(output_errors),
                    "metadata": {
                        "quota_per_run": spec.quota_per_run,
                        "quota_used": quota_used,
                        "timeout_seconds": spec.timeout_seconds,
                    },
                }
            return {
                "tool": name,
                "input": envelope.parameters,
                "output": output,
                "success": output is not None,
                "metadata": {
                    "quota_per_run": spec.quota_per_run,
                    "quota_used": quota_used,
                    "timeout_seconds": spec.timeout_seconds,
                },
            }
        except concurrent.futures.TimeoutError:
            future.cancel()
            return {
                "tool": name,
                "input": envelope.parameters,
                "success": False,
                "error": f"Tool timed out after {spec.timeout_seconds:.2f}s",
                "metadata": {
                    "quota_per_run": spec.quota_per_run,
                    "quota_used": quota_used,
                    "timeout_seconds": spec.timeout_seconds,
                },
            }
        except Exception as exc:
            return {
                "tool": name,
                "input": envelope.parameters,
                "success": False,
                "error": str(exc),
                "metadata": {
                    "quota_per_run": spec.quota_per_run,
                    "quota_used": quota_used,
                    "timeout_seconds": spec.timeout_seconds,
                },
            }
        finally:
            executor.shutdown(wait=False, cancel_futures=True)


def validate_json_schema(schema: Dict[str, Any], value: Any, path: str = "value") -> List[str]:
    if not schema:
        return []

    errors: List[str] = []
    expected_type = schema.get("type")
    if expected_type is not None and not _matches_json_type(value, expected_type):
        errors.append(f"{path}: expected {_type_name(expected_type)}, got {type(value).__name__}")
        return errors

    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: expected one of {schema['enum']!r}")

    if isinstance(value, dict):
        required = schema.get("required") or []
        for field_name in required:
            if field_name not in value:
                errors.append(f"{path}.{field_name}: missing required field")

        properties = schema.get("properties") or {}
        for field_name, field_schema in properties.items():
            if field_name in value:
                errors.extend(validate_json_schema(field_schema, value[field_name], f"{path}.{field_name}"))

        additional = schema.get("additionalProperties", True)
        if additional is False:
            extra_fields = sorted(set(value) - set(properties))
            for field_name in extra_fields:
                errors.append(f"{path}.{field_name}: additional property is not allowed")
        elif isinstance(additional, dict):
            for field_name in sorted(set(value) - set(properties)):
                errors.extend(validate_json_schema(additional, value[field_name], f"{path}.{field_name}"))

    if isinstance(value, list):
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for idx, item in enumerate(value):
                errors.extend(validate_json_schema(item_schema, item, f"{path}[{idx}]"))

    return errors


def _matches_json_type(value: Any, expected_type: Any) -> bool:
    if isinstance(expected_type, list):
        return any(_matches_json_type(value, item) for item in expected_type)
    if expected_type == "object":
        return isinstance(value, dict)
    if expected_type == "array":
        return isinstance(value, list)
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "null":
        return value is None
    return True


def _type_name(expected_type: Any) -> str:
    if isinstance(expected_type, list):
        return " or ".join(str(item) for item in expected_type)
    return str(expected_type)


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
