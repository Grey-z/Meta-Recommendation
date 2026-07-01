"""Regression tests for three confirmation/dynamic-form fixes:

1. product detection no longer reads "phone" inside "headphones";
2. a model/version number (e.g. "iPhone 14") is never misread as a budget;
3. the in-flow new-query guard recognizes a domain switch evidenced only by
   entity keys (artist/director/author), matching the routing-graph hint.
"""

import pytest

from langgraph_metarec.graphs.request_orchestrator import (
    _extract_product_budget_text,
    _normalize_product_preferences,
    _refine_preferences,
    _starts_new_query_flow,
)


# --------------------------------------------------------------------------- #
# Fix #1 — "headphones" must not be classified as a smartphone
# --------------------------------------------------------------------------- #
@pytest.mark.backend_unit
def test_headphones_not_classified_as_smartphone():
    out = _normalize_product_preferences({}, "cheap headphones")
    assert out["product"] == "headphones"
    assert out["category"] == "headphones"

    # Standalone "phone(s)" still maps to smartphone.
    assert _normalize_product_preferences({}, "a new phone")["product"] == "smartphone"
    assert _normalize_product_preferences({}, "looking for phones")["product"] == "smartphone"


# --------------------------------------------------------------------------- #
# Fix #2 — model/version numbers must not be read as a budget
# --------------------------------------------------------------------------- #
@pytest.mark.backend_unit
def test_model_number_is_not_treated_as_budget():
    # No currency and no budget keyword -> the model number is not a budget.
    assert _extract_product_budget_text("iphone 15", {}) == ""
    assert "budget" not in _normalize_product_preferences({}, "iphone 15")

    # A real budget with a keyword + currency wins over the model number.
    assert (
        _extract_product_budget_text("iPhone 14-16 for iOS testing under 1600 SGD", {})
        == "<= 1600 SGD"
    )
    out = _normalize_product_preferences({}, "iPhone 14-16 under 1600 SGD")
    assert out["budget"] == "<= 1600 SGD"
    assert out["model"] == "Iphone 14-16"  # model preserved, not consumed as budget


@pytest.mark.backend_unit
def test_budget_extracted_from_currency_or_keyword():
    assert _extract_product_budget_text("a laptop below 2000 SGD", {}) == "<= 2000 SGD"
    assert _extract_product_budget_text("headphones $300", {}) == "300 SGD"  # $ -> SGD default
    assert _extract_product_budget_text("budget 800 USD", {}) == "800 USD"
    assert _extract_product_budget_text("cheap headphones", {}) == "affordable"
    # An explicit preference budget always wins.
    assert _extract_product_budget_text("anything", {"budget": "1000 SGD"}) == "1000 SGD"


# --------------------------------------------------------------------------- #
# Fix #3 — in-flow guard recognizes an entity-only domain switch
# --------------------------------------------------------------------------- #
@pytest.mark.backend_unit
def test_in_flow_guard_detects_entity_only_domain_switch():
    music_pending = {
        "query": "music by Daft Punk",
        "routing": {"execution_domain": "music", "domain": "music"},
    }

    # A movie request evidenced only by the `directors` entity key (no "movie"
    # keyword, no explicit domain) is now recognized as a new flow.
    assert _starts_new_query_flow(music_pending, "something by Nolan", {"directors": ["Nolan"]}) is True

    # An explicit domain key is still honored.
    assert _starts_new_query_flow(music_pending, "by Nolan", {"domain": "movie"}) is True

    # Same-domain entities (artist while music is pending) stay a refinement.
    assert _starts_new_query_flow(music_pending, "by Adele", {"artist": "Adele"}) is False


# --------------------------------------------------------------------------- #
# Unified, domain-aware refine merge (reject + text-rejection share this)
# --------------------------------------------------------------------------- #
@pytest.mark.backend_unit
def test_refine_preferences_is_domain_aware_for_generic_domains():
    restaurant_baseline = {"restaurant_types": ["casual"], "location": "any", "budget_range": {"min": 20, "max": 60}}

    # A movie refine keeps its structured prefs and never inherits the restaurant
    # baseline (the bug: the old reject path used the restaurant-only merge).
    movie = _refine_preferences(
        routing={"execution_domain": "movie", "domain": "movie"},
        previous={"genres": ["drama"], "actors": "Cillian Murphy"},
        new={"genres": ["comedy"]},
        restaurant_baseline=restaurant_baseline,
    )
    assert movie["genres"] == ["comedy"]  # new overlays previous
    assert movie["actors"] == "Cillian Murphy"  # existing structured pref preserved
    assert "restaurant_types" not in movie  # baseline never leaks into a non-restaurant refine


@pytest.mark.backend_unit
def test_refine_preferences_uses_baseline_for_restaurant():
    restaurant_baseline = {"restaurant_types": ["casual"], "location": "any", "flavor_profiles": ["any"]}
    out = _refine_preferences(
        routing={"execution_domain": "restaurant", "domain": "restaurant"},
        previous=None,  # falls back to the restaurant baseline
        new={"location": "Chinatown", "flavor_profiles": ["spicy"]},
        restaurant_baseline=restaurant_baseline,
    )
    assert out["location"] == "Chinatown"  # new value overrides the "any" baseline
    assert out["flavor_profiles"] == ["spicy"]
    assert out["restaurant_types"] == ["casual"]  # baseline preserved where not overridden
