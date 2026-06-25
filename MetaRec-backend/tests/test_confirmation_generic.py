import pytest

from llm_service import _summarize_preferences_for_confirmation, _humanize_domain_label


@pytest.mark.backend_unit
def test_summarize_preferences_is_domain_agnostic():
    # Restaurant: structured food_intent + a generic key.
    restaurant = _summarize_preferences_for_confirmation(
        {"location": "Chinatown", "food_intent": {"cuisines": ["vietnamese"], "dishes": ["pho"], "confidence": 0.9}}
    )
    assert "cuisine: vietnamese" in restaurant
    assert "dish: pho" in restaurant
    assert "location: Chinatown" in restaurant

    # Movie: generic keys render the same way; control keys are skipped.
    movie = _summarize_preferences_for_confirmation({"genres": ["comedy", "drama"], "domain": "movie", "query": "x"})
    assert "genres: comedy, drama" in movie
    assert "domain" not in movie and "query" not in movie


@pytest.mark.backend_unit
def test_summarize_preferences_drops_any_and_empty():
    assert _summarize_preferences_for_confirmation({"restaurant_types": ["any"], "location": ""}) == ""
    assert _summarize_preferences_for_confirmation({}) == ""


@pytest.mark.backend_unit
def test_humanize_domain_label():
    assert _humanize_domain_label("movie") == "movie"
    assert _humanize_domain_label("multi_domain") == "recommendation"
    assert _humanize_domain_label(None) == "recommendation"


@pytest.mark.backend_unit
def test_generate_confirmation_prompt_is_keyerror_safe_for_non_restaurant():
    from conftest import make_service

    service, _ = make_service([])
    # Non-restaurant preferences lack restaurant_types/flavor_profiles/etc. The
    # template fallback must not KeyError and must describe the right domain.
    message = service.generate_confirmation_prompt(
        "recommend a movie", {"genres": ["comedy"], "domain": "movie"}, "movie"
    )
    assert "movie" in message.lower()
    assert "comedy" in message.lower()
