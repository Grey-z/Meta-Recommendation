import pytest

from langgraph_metarec.tool_registry import (
    DEFAULT_TOOL_REGISTRY,
    ToolRegistry,
    ToolSpec,
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
