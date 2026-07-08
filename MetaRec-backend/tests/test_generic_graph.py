import pytest

from langgraph_metarec.graphs.generic_graph import (
    GenericGraphAdapters,
    _parameters_for_tool,
    _relaxation_actions,
    normalize_tool_items,
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
    assert _parameters_for_tool("amazon.product.search", "laptop under 2000 SGD", {"use_case": "work"}) == {
        "max_results": 10,
        "query": "laptop under 2000 SGD work",
    }
    assert _parameters_for_tool(
        "amazon.product.search",
        "recommend an iOS testing phone",
        {"product": "iPhone", "model": "iPhone 14-16", "budget": "<= 1600 SGD", "use_case": "iOS testing"},
    ) == {
        "max_results": 10,
        "query": "recommend an iOS testing phone iPhone iPhone 14-16 <= 1600 SGD",
    }


@pytest.mark.backend_unit
def test_parameters_for_tool_composes_hotel_search_query():
    # The stay filters (stars, amenities, budget, destination) enrich the text
    # query the same way the product search does.
    params = _parameters_for_tool(
        "gmap.hotel.search",
        "Find me a place to stay",
        {"location": "Sentosa", "stars": "4", "amenities": "pool, free wifi", "budget": "< 200 SGD"},
    )
    assert params["query"] == "Find me a place to stay hotels 4-star pool free wifi < 200 SGD in Sentosa"

    # Tokens already present in the query are not duplicated; "any" is ignored.
    params = _parameters_for_tool("gmap.hotel.search", "4-star hotels in Kyoto", {"location": "Kyoto", "stars": "any"})
    assert params["query"] == "4-star hotels in Kyoto"


@pytest.mark.backend_unit
def test_parameters_for_tool_hotel_discover_needs_destination():
    params = _parameters_for_tool("osm.hotel.discover", "somewhere nice", {"location": "Chinatown", "stars": "4"})
    assert params == {"max_results": 10, "location": "Chinatown", "stars": "4"}

    # No usable destination -> no structured filter contributed ("any" is noise).
    assert _parameters_for_tool("osm.hotel.discover", "somewhere nice", {"location": "any"}) == {"max_results": 10}
    assert _parameters_for_tool("osm.hotel.discover", "somewhere nice", {}) == {"max_results": 10}


@pytest.mark.backend_unit
def test_normalize_tool_items_maps_hotel_tools():
    gmap_items = normalize_tool_items(
        "gmap.hotel.search",
        [
            {
                "title": "Grand Palace Hotel",
                "address": "1 Beach Rd",
                "rating": 4.5,
                "reviews": 980,
                "type": "Hotel",
                "price": "$$$",
                "gps_coordinates": {"latitude": 1.29, "longitude": 103.85},
            }
        ],
        "hotel",
    )
    assert gmap_items[0]["title"] == "Grand Palace Hotel"
    assert gmap_items[0]["subtitle"] == "1 Beach Rd"
    assert gmap_items[0]["rating"] == 4.5
    assert gmap_items[0]["reviews_count"] == 980
    assert gmap_items[0]["source"] == "Google Maps"
    assert gmap_items[0]["tags"] == ["Hotel", "$$$"]

    osm_items = normalize_tool_items(
        "osm.hotel.discover",
        [
            {
                "title": "Riverside Guest House",
                "tourism": "guest_house",
                "stars": 3.0,
                "address": "12 River St",
                "website": "https://riverside.example",
                "link": "https://www.openstreetmap.org/node/42",
                "searched_location": "Clarke Quay",
            }
        ],
        "hotel",
    )
    assert osm_items[0]["title"] == "Riverside Guest House"
    assert osm_items[0]["subtitle"] == "12 River St"
    assert osm_items[0]["url"] == "https://riverside.example"
    assert osm_items[0]["source"] == "OpenStreetMap"
    assert osm_items[0]["tags"] == ["guest_house", "3-star"]


@pytest.mark.backend_unit
def test_relaxation_ladder_drops_hotel_stars_but_keeps_destination():
    actions = _relaxation_actions(
        [
            {
                "tool": "osm.hotel.discover",
                "parameters": {"max_results": 10, "location": "Chinatown", "stars": "5"},
                "count": 0,
            }
        ]
    )
    # Stars is droppable; the destination is the keep-last filter, so exactly
    # one relaxation step exists and it still carries the location.
    assert actions == [{"tool": "osm.hotel.discover", "parameters": {"max_results": 10, "location": "Chinatown"}}]


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_generic_graph_runs_hotel_domain_end_to_end():
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="gmap.hotel.search",
            domain="hotel",
            tags={"#place", "#hotel"},
            input_schema={"type": "object"},
            output_schema={"type": "array"},
            adapter=lambda params: [
                {"title": "Palm View Hotel", "address": "7 Palm Ave", "rating": 4.6, "reviews": 512, "type": "Hotel"}
            ],
        )
    )
    registry.register(
        ToolSpec(
            name="osm.hotel.discover",
            domain="hotel",
            tags={"#place", "#hotel"},
            input_schema={"type": "object"},
            output_schema={"type": "array"},
            adapter=lambda params: [
                {"title": "Palm Hostel", "tourism": "hostel", "address": "9 Palm Ave", "searched_location": params.get("location")}
            ],
        )
    )

    result = await run_generic_domain_graph(
        query="a hotel near Palm Avenue",
        domain="hotel",
        preferences={"location": "Palm Avenue"},
        tool_tags=["#place", "#hotel"],
        adapters=GenericGraphAdapters(tool_registry=registry),
    )

    assert result.metadata["domain"] == "hotel"
    assert result.metadata["selected_tools"] == ["gmap.hotel.search", "osm.hotel.discover"]
    titles = [item["title"] for item in result.items]
    # Rated gmap candidates rank above unrated OSM ones.
    assert titles[0] == "Palm View Hotel"
    assert "Palm Hostel" in titles
    assert all(item["domain"] == "hotel" for item in result.items)


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
