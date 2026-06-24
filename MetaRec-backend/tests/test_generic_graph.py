import pytest

from langgraph_metarec.graphs.generic_graph import (
    GenericGraphAdapters,
    _parameters_for_tool,
    run_generic_domain_graph,
)
from langgraph_metarec.tool_registry import ToolRegistry, ToolSpec


@pytest.mark.backend_unit
def test_parameters_for_tool_derives_discover_genres():
    # Genres inferred from the query when no explicit preference is set.
    params = _parameters_for_tool("tmdb.movie.discover", "a quiet sci-fi movie", {})
    assert params["with_genres"] == "science fiction"

    # Explicit preference genres take priority over inference.
    params = _parameters_for_tool("tmdb.tv.discover", "anything", {"genres": ["comedy", "drama"]})
    assert params["with_genres"] == "comedy,drama"

    # Search tools just carry the query through.
    assert _parameters_for_tool("tmdb.movie.search", "jaws", {}) == {"max_results": 10, "query": "jaws"}


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_generic_graph_dispatches_active_scoped_tools_and_normalizes_items():
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="amazon.product.search",
            domain="product",
            tags={"#thing", "#product", "#shopping"},
            input_schema={"type": "object"},
            output_schema={"type": "array"},
            adapter=lambda params: [
                {
                    "product_id": "asin-1",
                    "title": f"{params['query']} headphones",
                    "brand": "Acme",
                    "rating": 4.7,
                    "reviews": 1200,
                    "thumbnail": "https://example.test/headphones.jpg",
                    "link": "https://example.test/headphones",
                    "tags": ["audio"],
                }
            ],
        )
    )

    result = await run_generic_domain_graph(
        query="noise cancelling",
        domain="product",
        tool_tags=["#thing", "#product"],
        adapters=GenericGraphAdapters(tool_registry=registry),
    )

    assert result.metadata["domain"] == "product"
    assert result.items[0]["id"] == "asin-1"
    assert result.items[0]["title"] == "noise cancelling headphones"
    assert result.items[0]["subtitle"] == "Acme"
    assert result.items[0]["rating"] == 4.7
    assert result.items[0]["reviews_count"] == 1200
    assert result.items[0]["source"] == "Amazon"
    assert result.metadata["selected_tools"] == ["amazon.product.search"]
    assert result.metadata["skipped_tools"] == []
    assert result.metadata["items_count"] == 1


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_generic_graph_reports_inactive_scoped_tools_without_dispatching():
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="tmdb.movie.search",
            domain="movie",
            tags={"#thing", "#movie"},
            input_schema={"type": "object"},
            output_schema={"type": "array"},
            adapter=lambda params: pytest.fail("inactive adapter should not be dispatched"),
            status="missing_credentials:TMDB_API_ACCESS_TOKEN",
        )
    )

    result = await run_generic_domain_graph(
        query="quiet sci-fi movie",
        domain="movie",
        tool_tags=["#thing", "#movie"],
        adapters=GenericGraphAdapters(tool_registry=registry),
    )

    assert result.items == []
    assert result.metadata["selected_tools"] == []
    assert result.metadata["skipped_tools"] == [
        {"name": "tmdb.movie.search", "status": "missing_credentials:TMDB_API_ACCESS_TOKEN"}
    ]
    assert result.metadata["items_count"] == 0
