import pytest

from preference_specs import build_domain_form, supported_domains


@pytest.mark.backend_unit
def test_movie_form_lists_genres_and_flags_missing_required():
    form = build_domain_form("movie", {})
    assert form["domain"] == "movie"
    genres = next(field for field in form["fields"] if field["key"] == "genres")
    assert genres["type"] == "multiselect"
    assert "science fiction" in genres["options"]
    assert genres["required"] is True
    assert "genres" in form["missing_required"]
    assert form["complete"] is False


@pytest.mark.backend_unit
def test_form_marks_complete_when_required_present():
    form = build_domain_form("movie", {"genres": ["science fiction"]})
    assert form["missing_required"] == []
    assert form["complete"] is True


@pytest.mark.backend_unit
def test_any_value_counts_as_missing_for_required():
    form = build_domain_form("restaurant", {"location": "any"})
    assert "location" in form["missing_required"]


@pytest.mark.backend_unit
def test_unknown_domain_returns_empty_complete_form():
    form = build_domain_form("travel", {})
    assert form["fields"] == []
    assert form["complete"] is True


@pytest.mark.backend_unit
def test_supported_domains_cover_executable_domains():
    domains = supported_domains()
    assert {"restaurant", "hotel", "attraction", "movie", "book", "music", "product"}.issubset(set(domains))


@pytest.mark.backend_unit
def test_hotel_form_requires_destination_and_offers_stay_fields():
    form = build_domain_form("hotel", {"stars": "4"})
    fields = {field["key"]: field for field in form["fields"]}
    assert {"location", "stars", "amenities", "budget"} <= set(fields)
    assert fields["location"]["required"] is True
    assert fields["stars"]["label"] == "Exact star class"
    assert fields["stars"]["value"] == "4"
    assert "4" in fields["stars"]["options"]
    assert "location" in form["missing_required"]
    assert form["complete"] is False


@pytest.mark.backend_unit
def test_attraction_form_requires_destination_and_offers_type_fields():
    form = build_domain_form("attraction", {"attraction_types": ["museum"]})
    fields = {field["key"]: field for field in form["fields"]}
    assert {"location", "attraction_types", "budget"} <= set(fields)
    assert fields["location"]["required"] is True
    assert fields["attraction_types"]["type"] == "multiselect"
    assert fields["attraction_types"]["value"] == ["museum"]
    assert "location" in form["missing_required"]
    assert form["complete"] is False


@pytest.mark.backend_unit
def test_attraction_form_options_match_the_osm_type_map():
    # The multiselect options and the Overpass type map must not drift apart:
    # every selectable value must resolve to OSM tourism types, or the discover
    # tool would silently ignore it.
    from langgraph_metarec.tool_registry import _ATTRACTION_TYPE_OSM

    form = build_domain_form("attraction", {})
    options = next(field for field in form["fields"] if field["key"] == "attraction_types")["options"]
    assert set(options) == set(_ATTRACTION_TYPE_OSM)


@pytest.mark.backend_unit
def test_itinerary_form_requires_structured_day_constraints():
    form = build_domain_form("itinerary", {"budget_mode": "limited"})
    fields = {field["key"]: field for field in form["fields"]}
    assert {
        "location", "date", "horizon_days", "daily_start_time", "daily_end_time",
        "budget_mode", "budget_amount", "budget_currency", "travelers", "rooms", "pace",
        "attraction_types",
    } <= set(fields)
    assert fields["location"]["required"] is True
    assert fields["date"]["type"] == "date"
    assert fields["daily_start_time"]["type"] == "time"
    assert fields["horizon_days"]["max"] == 3
    assert "university-campus" in fields["attraction_types"]["options"]
    assert fields["budget_amount"]["min"] > 0
    assert fields["budget_amount"]["required_when"] == {"key": "budget_mode", "equals": "limited"}
    assert fields["travelers"]["required_when"] == {"key": "horizon_days", "operator": "gt", "value": 1}
    assert {
        "location", "date", "horizon_days", "daily_start_time", "daily_end_time",
        "budget_amount", "budget_currency",
    } <= set(form["missing_required"])
    assert form["complete"] is False


@pytest.mark.backend_unit
def test_itinerary_unlimited_budget_does_not_require_amount_or_currency():
    form = build_domain_form(
        "itinerary",
        {
            "location": "Sentosa",
            "date": "2026-08-01",
            "horizon_days": 1,
            "daily_start_time": "09:00",
            "daily_end_time": "18:00",
            "budget_mode": "unlimited",
            "timezone": "Asia/Singapore",
            "style": "sightseeing",
            "pace": "balanced",
        },
    )
    assert form["missing_required"] == []
    assert form["complete"] is True


@pytest.mark.backend_unit
def test_itinerary_form_exposes_style_pace_and_route_end_policy():
    form = build_domain_form("itinerary", {"hotel_anchor": "Siloso Beach Resort", "anchor_policy": "distinct_end"})
    fields = {field["key"]: field for field in form["fields"]}
    assert fields["style"]["options"] == ["sightseeing", "food_tour", "shopping", "theme_park", "mixed"]
    assert fields["style"]["required"] is True
    assert fields["pace"]["required"] is True
    assert fields["anchor_policy"]["options"] == ["round_trip", "start_only", "distinct_end"]
    assert fields["end_anchor"]["required_when"] == {"key": "anchor_policy", "equals": "distinct_end"}
    assert "end_anchor" in form["missing_required"]


@pytest.mark.backend_unit
def test_product_form_exposes_structured_shopping_fields():
    form = build_domain_form(
        "product",
        {"product": "iPhone", "model": "iPhone 14-16", "budget": "<= 1600 SGD", "use_case": "iOS testing"},
    )
    fields = {field["key"]: field for field in form["fields"]}
    assert {"product", "model", "budget", "use_case", "brand", "category"} <= set(fields)
    assert fields["product"]["value"] == "iPhone"
    assert fields["model"]["value"] == "iPhone 14-16"
    assert fields["budget"]["value"] == "<= 1600 SGD"
    assert fields["use_case"]["value"] == "iOS testing"
    assert form["missing_required"] == []
