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
    form = build_domain_form("hotel", {})
    assert form["fields"] == []
    assert form["complete"] is True


@pytest.mark.backend_unit
def test_supported_domains_cover_executable_domains():
    domains = supported_domains()
    assert {"restaurant", "movie", "book", "music", "product"}.issubset(set(domains))
