import time

import pytest

from langgraph_metarec.tool_registry import (
    DEFAULT_TOOL_REGISTRY,
    DEFAULT_TOOL_QUOTA_PER_RUN,
    DEFAULT_TOOL_TIMEOUT_SECONDS,
    ToolRegistry,
    ToolSpec,
    build_default_tool_registry,
    normalize_tag,
)


@pytest.mark.backend_unit
def test_normalize_tag_adds_hash_and_lowercases():
    assert normalize_tag("restaurant") == "#restaurant"
    assert normalize_tag("#Place") == "#place"


@pytest.mark.backend_unit
def test_default_registry_scopes_restaurant_place_tools():
    tools = DEFAULT_TOOL_REGISTRY.resolve(domain="restaurant", tags={"#restaurant", "#place"})
    names = {tool.name for tool in tools}

    assert {"gmap.search", "xhs.search", "yelp.search", "gmap.source_matcher"}.issubset(names)


@pytest.mark.backend_unit
def test_default_registry_contains_generic_domain_tools():
    specs = DEFAULT_TOOL_REGISTRY.resolve(
        domain="movie",
        tags={"#thing", "#movie"},
        active_only=False,
    )
    names = {tool.name for tool in specs}

    assert {"tmdb.movie.search", "tmdb.movie.discover", "tmdb.tv.search", "tmdb.tv.discover"}.issubset(names)

    product_tools = DEFAULT_TOOL_REGISTRY.resolve(
        domain="product",
        tags={"#thing", "#product"},
        active_only=False,
    )
    assert "amazon.product.search" in {tool.name for tool in product_tools}


@pytest.mark.backend_unit
def test_default_registry_marks_credentialed_tools_inactive_without_env(monkeypatch):
    monkeypatch.delenv("SERPAPI_KEY", raising=False)
    registry = build_default_tool_registry()

    all_product_tools = registry.resolve(domain="product", tags={"#thing", "#product"}, active_only=False)
    active_product_tools = registry.resolve(domain="product", tags={"#thing", "#product"}, active_only=True)

    amazon_tool = next(tool for tool in all_product_tools if tool.name == "amazon.product.search")
    assert amazon_tool.status == "missing_credentials:SERPAPI_KEY"
    assert "amazon.product.search" not in {tool.name for tool in active_product_tools}


@pytest.mark.backend_unit
def test_tmdb_discover_resolves_genre_names_to_ids(monkeypatch):
    import langgraph_metarec.tool_registry as tr

    calls: list = []

    def fake_get(path, params=None):
        calls.append((path, params or {}))
        return {"results": []}

    monkeypatch.setattr(tr, "_tmdb_get", fake_get)
    tr._tmdb_movie_discover_adapter({"with_genres": "sci-fi, comedy"})

    discover_calls = [call for call in calls if "/discover/" in call[0]]
    assert discover_calls, "discover endpoint was not called"
    path, params = discover_calls[0]
    assert path == "/3/discover/movie"
    assert params["with_genres"] == "878,35"


@pytest.mark.backend_unit
def test_tmdb_discover_without_genre_filter_contributes_nothing(monkeypatch):
    import langgraph_metarec.tool_registry as tr

    def boom(*args, **kwargs):
        raise AssertionError("discover must not call TMDB without a genre filter")

    monkeypatch.setattr(tr, "_tmdb_get", boom)
    assert tr._tmdb_tv_discover_adapter({}) == []


@pytest.mark.backend_unit
def test_registry_excludes_unrelated_domain_tools():
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="gmap.search",
            domain="restaurant",
            tags={"#place", "#restaurant", "#map"},
            input_schema={"type": "object"},
            output_schema={"type": "array"},
            adapter=lambda params: [{"title": params["query"]}],
        )
    )
    registry.register(
        ToolSpec(
            name="amazon.search",
            domain="product",
            tags={"#thing", "#shopping"},
            input_schema={"type": "object"},
            output_schema={"type": "array"},
            adapter=lambda params: [],
        )
    )

    restaurant_tools = registry.resolve(domain="restaurant", tags={"#place"})

    assert [tool.name for tool in restaurant_tools] == ["gmap.search"]
    assert registry.dispatch("gmap.search", {"query": "ramen"})["success"] is True


@pytest.mark.backend_unit
def test_registry_reports_inactive_tool_without_dispatching():
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="disabled.search",
            domain="restaurant",
            tags={"#place", "#restaurant"},
            input_schema={"type": "object"},
            output_schema={"type": "array"},
            adapter=lambda params: pytest.fail("adapter should not be called"),
            status="disabled",
        )
    )

    result = registry.dispatch("disabled.search", {"query": "test"})

    assert result["success"] is False
    assert "not active" in result["error"]


@pytest.mark.backend_unit
def test_tool_spec_has_safe_default_timeout_and_quota():
    spec = ToolSpec(
        name="defaults.search",
        domain="restaurant",
        tags={"#place"},
        input_schema={"type": "object"},
        output_schema={"type": "array"},
        adapter=lambda params: [],
    )

    assert spec.timeout_seconds == DEFAULT_TOOL_TIMEOUT_SECONDS
    assert spec.quota_per_run == DEFAULT_TOOL_QUOTA_PER_RUN


@pytest.mark.backend_unit
def test_registry_validates_tool_input_schema_before_dispatching():
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="validated.search",
            domain="restaurant",
            tags={"#place"},
            input_schema={
                "type": "object",
                "required": ["query"],
                "properties": {"query": {"type": "string"}, "max_results": {"type": "integer"}},
            },
            output_schema={"type": "array"},
            adapter=lambda params: pytest.fail("adapter should not be called"),
        )
    )

    result = registry.dispatch("validated.search", {"max_results": "10"})

    assert result["success"] is False
    assert "input schema validation failed" in result["error"]
    assert "input.query" in result["error"]
    assert "input.max_results" in result["error"]


@pytest.mark.backend_unit
def test_registry_validates_tool_output_schema():
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="bad-output.search",
            domain="restaurant",
            tags={"#place"},
            input_schema={"type": "object"},
            output_schema={"type": "array"},
            adapter=lambda params: {"not": "an array"},
        )
    )

    result = registry.dispatch("bad-output.search", {})

    assert result["success"] is False
    assert "output schema validation failed" in result["error"]
    assert result["output"] == {"not": "an array"}


@pytest.mark.backend_unit
def test_registry_enforces_per_tool_quota_per_run():
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="quota.search",
            domain="restaurant",
            tags={"#place"},
            input_schema={"type": "object"},
            output_schema={"type": "array"},
            adapter=lambda params: [],
            quota_per_run=1,
        )
    )
    quota_tracker = {}

    assert registry.dispatch("quota.search", {}, quota_tracker=quota_tracker)["success"] is True
    result = registry.dispatch("quota.search", {}, quota_tracker=quota_tracker)

    assert result["success"] is False
    assert "quota exceeded" in result["error"]
    assert result["metadata"]["quota_used"] == 1


@pytest.mark.backend_unit
def test_registry_enforces_per_tool_timeout():
    registry = ToolRegistry()

    def slow_adapter(params):
        time.sleep(0.05)
        return []

    registry.register(
        ToolSpec(
            name="slow.search",
            domain="restaurant",
            tags={"#place"},
            input_schema={"type": "object"},
            output_schema={"type": "array"},
            adapter=slow_adapter,
            timeout_seconds=0.01,
        )
    )

    result = registry.dispatch("slow.search", {})

    assert result["success"] is False
    assert "timed out" in result["error"]
    assert result["metadata"]["timeout_seconds"] == 0.01
