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
    assert {"restaurant", "hotel", "movie", "book", "music", "product"}.issubset(set(domains))


@pytest.mark.backend_unit
def test_hotel_form_requires_destination_and_offers_stay_fields():
    form = build_domain_form("hotel", {"stars": "4"})
    fields = {field["key"]: field for field in form["fields"]}
    assert {"location", "stars", "amenities", "budget"} <= set(fields)
    assert fields["location"]["required"] is True
    assert fields["stars"]["value"] == "4"
    assert "4" in fields["stars"]["options"]
    assert "location" in form["missing_required"]
    assert form["complete"] is False


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
