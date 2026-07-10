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
def test_default_registry_scopes_hotel_tools(monkeypatch):
    monkeypatch.setenv("SERPAPI_KEY", "test-key")
    registry = build_default_tool_registry()

    hotel_tools = registry.resolve(domain="hotel", tags={"#place", "#hotel"}, active_only=False)
    names = {tool.name for tool in hotel_tools}
    assert names == {"gmap.hotel.search", "osm.hotel.discover"}

    # The keyless OSM tool stays active even without SERPAPI; the gmap search
    # is credential-gated like the other SerpAPI-backed tools.
    monkeypatch.delenv("SERPAPI_KEY", raising=False)
    registry = build_default_tool_registry()
    active = {tool.name for tool in registry.resolve(domain="hotel", tags={"#place", "#hotel"})}
    assert active == {"osm.hotel.discover"}

    # Hotel tools never leak into restaurant resolution (and vice versa).
    restaurant = {tool.name for tool in registry.resolve(domain="restaurant", tags={"#place", "#restaurant"})}
    assert not restaurant & {"gmap.hotel.search", "osm.hotel.discover"}


def _osm_element(name, *, stars=None, element_type="node", element_id=1, **tags):
    payload_tags = {"tourism": "hotel", "name": name, **tags}
    if stars is not None:
        payload_tags["stars"] = stars
    return {"type": element_type, "id": element_id, "lat": 1.28, "lon": 103.85, "tags": payload_tags}


@pytest.mark.backend_unit
def test_osm_hotel_discover_geocodes_then_filters_exact_stars(monkeypatch):
    import langgraph_metarec.tool_registry as tr

    monkeypatch.setattr(tr, "_osm_geocode", lambda location: {"lat": 1.28, "lon": 103.85})
    monkeypatch.setattr(
        tr,
        "_osm_tourism_elements",
        lambda lat, lon, type_regex, fetch_count, radius_meters: [
            _osm_element("Budget Inn", stars="2", element_id=1),
            _osm_element("Park Hotel", stars="4", element_id=2, website="https://park.example"),
            _osm_element("Grand Palace", stars="5", element_id=3, website="https://grand.example"),
            _osm_element("Untagged Lodge", element_id=3),
            {"type": "node", "id": 4, "tags": {"tourism": "hotel"}},  # nameless -> skipped
        ],
    )

    output = tr._osm_hotel_discover_adapter({"location": "Chinatown", "stars": "4"})
    assert [item["title"] for item in output] == ["Park Hotel"]
    assert output[0]["stars"] == 4.0
    assert output[0]["website"] == "https://park.example"
    assert output[0]["link"] == "https://www.openstreetmap.org/node/2"

    unfiltered = tr._osm_hotel_discover_adapter({"location": "Chinatown"})
    assert [item["title"] for item in unfiltered] == ["Budget Inn", "Park Hotel", "Grand Palace", "Untagged Lodge"]


@pytest.mark.backend_unit
def test_osm_dynamic_radius_uses_bounding_box_and_place_type():
    import langgraph_metarec.tool_registry as tr

    city = {
        "lat": 1.35,
        "lon": 103.8,
        "type": "city",
        "boundingbox": ["1.20", "1.50", "103.60", "104.00"],
    }
    assert tr._osm_dynamic_radius(city) > tr._OSM_DEFAULT_SEARCH_RADIUS_METERS

    suburb = {"lat": 1.35, "lon": 103.8, "type": "suburb"}
    assert tr._osm_dynamic_radius(suburb) == 7000


@pytest.mark.backend_unit
def test_osm_hotel_discover_contributes_nothing_without_destination(monkeypatch):
    import langgraph_metarec.tool_registry as tr

    def boom(*args, **kwargs):
        raise AssertionError("must not touch the network without a destination")

    monkeypatch.setattr(tr, "_osm_geocode", boom)
    assert tr._osm_hotel_discover_adapter({}) == []
    assert tr._osm_hotel_discover_adapter({"location": "any"}) == []


@pytest.mark.backend_unit
def test_osm_hotel_discover_handles_unresolvable_destination(monkeypatch):
    import langgraph_metarec.tool_registry as tr

    monkeypatch.setattr(tr, "_osm_geocode", lambda location: None)
    assert tr._osm_hotel_discover_adapter({"location": "Nowhereville-xyz"}) == []


@pytest.mark.backend_unit
def test_default_registry_scopes_attraction_tools(monkeypatch):
    monkeypatch.setenv("SERPAPI_KEY", "test-key")
    registry = build_default_tool_registry()

    attraction_tools = registry.resolve(domain="attraction", tags={"#place", "#attraction"}, active_only=False)
    names = {tool.name for tool in attraction_tools}
    assert names == {"gmap.attraction.search", "osm.attraction.discover"}

    # The keyless OSM tool stays active even without SERPAPI; the gmap search
    # is credential-gated like the other SerpAPI-backed tools.
    monkeypatch.delenv("SERPAPI_KEY", raising=False)
    registry = build_default_tool_registry()
    active = {tool.name for tool in registry.resolve(domain="attraction", tags={"#place", "#attraction"})}
    assert active == {"osm.attraction.discover"}

    # Attraction tools never leak into the other place domains (and vice versa).
    hotel = {tool.name for tool in registry.resolve(domain="hotel", tags={"#place", "#hotel"})}
    assert not hotel & {"gmap.attraction.search", "osm.attraction.discover"}


def _osm_attraction_element(name, tourism, element_id=1, **tags):
    payload_tags = {"tourism": tourism, "name": name, **tags}
    return {"type": "node", "id": element_id, "lat": 1.25, "lon": 103.82, "tags": payload_tags}


@pytest.mark.backend_unit
def test_osm_attraction_discover_geocodes_then_filters_types(monkeypatch):
    import langgraph_metarec.tool_registry as tr

    seen = {}

    def fake_elements(lat, lon, type_regex, fetch_count, radius_meters):
        seen["type_regex"] = type_regex
        return [
            _osm_attraction_element(
                "ArtScience Museum", "museum", element_id=1,
                website="https://asm.example", opening_hours="Mo-Su 10:00-19:00",
            ),
            _osm_attraction_element("S.E.A. Aquarium", "aquarium", element_id=2),
            {"type": "node", "id": 3, "tags": {"tourism": "museum"}},  # nameless -> skipped
        ]

    monkeypatch.setattr(
        tr, "_osm_geocode", lambda location: {"lat": 1.25, "lon": 103.82, "display_name": "Sentosa, Singapore"}
    )
    monkeypatch.setattr(tr, "_osm_tourism_elements", fake_elements)

    output = tr._osm_attraction_discover_adapter(
        {"location": "Sentosa", "attraction_types": ["museum", "zoo-aquarium"]}
    )

    # Selected form values map through the curated dict into the Overpass regex.
    assert set(seen["type_regex"].split("|")) == {"museum", "zoo", "aquarium"}
    assert [item["title"] for item in output] == ["ArtScience Museum", "S.E.A. Aquarium"]
    assert output[0]["website"] == "https://asm.example"
    assert output[0]["opening_hours"] == "Mo-Su 10:00-19:00"
    assert output[0]["gps_coordinates"] == {"latitude": 1.25, "longitude": 103.82}
    assert output[0]["link"] == "https://www.openstreetmap.org/node/1"

    # Unrecognized selections (or none) fall back to the full curated type set —
    # raw user text never reaches the regex.
    tr._osm_attraction_discover_adapter({"location": "Sentosa", "attraction_types": ["nonsense); out;"]})
    assert set(seen["type_regex"].split("|")) == set(tr._OSM_ATTRACTION_TYPES)


@pytest.mark.backend_unit
def test_osm_attraction_discover_contributes_nothing_without_destination(monkeypatch):
    import langgraph_metarec.tool_registry as tr

    def boom(*args, **kwargs):
        raise AssertionError("must not touch the network without a destination")

    monkeypatch.setattr(tr, "_osm_geocode", boom)
    assert tr._osm_attraction_discover_adapter({}) == []
    assert tr._osm_attraction_discover_adapter({"location": "any"}) == []


@pytest.mark.backend_unit
def test_osm_attraction_discover_handles_unresolvable_destination(monkeypatch):
    import langgraph_metarec.tool_registry as tr

    monkeypatch.setattr(tr, "_osm_geocode", lambda location: None)
    assert tr._osm_attraction_discover_adapter({"location": "Nowhereville-xyz"}) == []


@pytest.mark.backend_unit
def test_osm_stars_value_parses_superior_suffix():
    import langgraph_metarec.tool_registry as tr

    assert tr._osm_stars_value({"stars": "4S"}) == 4.0
    assert tr._osm_stars_value({"stars": "3.5"}) == 3.5
    assert tr._osm_stars_value({"stars": "boutique"}) is None
    assert tr._osm_stars_value({}) is None


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
def test_musicbrainz_cover_art_enrichment_is_bounded(monkeypatch):
    import langgraph_metarec.tool_registry as tr

    recordings = [
        {"id": f"rec-{i}", "title": f"Song {i}", "releases": [{"id": f"rel-{i}"}]}
        for i in range(20)
    ]
    monkeypatch.setattr(tr, "_http_get_json", lambda *a, **k: {"recordings": recordings})

    calls = {"n": 0}

    class _FakeResp:
        status_code = 200
        headers: dict = {}

    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        def get(self, url):
            calls["n"] += 1
            return _FakeResp()

        def close(self):
            pass

    monkeypatch.setattr(tr.httpx, "Client", _FakeClient)

    out = tr._musicbrainz_recording_search_adapter({"query": "rock", "max_results": 20})

    # Every recording has a release id, so the budget — not the result count —
    # must cap how many cover-art lookups happen.
    assert calls["n"] == tr.MUSICBRAINZ_COVER_ART_LIMIT
    assert isinstance(out, list) and len(out) >= 1


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


@pytest.mark.backend_unit
def test_dispatch_bounds_wall_clock_for_a_hung_adapter():
    """A provider that never returns (e.g. an unreachable host) must not stall the
    graph: dispatch returns a clean failure within ~timeout_seconds, not the
    adapter's full duration."""
    registry = ToolRegistry()

    def hung_adapter(params):
        time.sleep(30)  # simulate a dead/unreachable provider
        return []

    registry.register(
        ToolSpec(
            name="hang.search",
            domain="restaurant",
            tags={"#place"},
            input_schema={"type": "object"},
            output_schema={"type": "array"},
            adapter=hung_adapter,
            timeout_seconds=0.2,
        )
    )

    start = time.monotonic()
    result = registry.dispatch("hang.search", {})
    elapsed = time.monotonic() - start

    assert result["success"] is False
    assert "timed out" in result["error"]
    # Must return near the timeout, nowhere near the adapter's 30s sleep.
    assert elapsed < 5


@pytest.mark.backend_unit
def test_tmdb_static_config_is_cached(monkeypatch):
    import langgraph_metarec.tool_registry as tr

    tr._TMDB_STATIC_CACHE.clear()
    calls = {"n": 0}

    def fake_get(path, params=None):
        calls["n"] += 1
        return {"images": {"secure_base_url": "https://img.test/"}}

    monkeypatch.setattr(tr, "_tmdb_get", fake_get)
    first = tr._tmdb_configuration()
    second = tr._tmdb_configuration()

    assert first == second
    assert calls["n"] == 1  # second read served from cache, not the network
    tr._TMDB_STATIC_CACHE.clear()
