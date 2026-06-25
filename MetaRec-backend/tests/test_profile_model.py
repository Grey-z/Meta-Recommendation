import pytest

from profile_model import (
    assemble_domains,
    build_recommender_profile_block,
    normalize_profile,
    taste_persona_of,
)


def _profile() -> dict:
    return {
        "user_id": "u-1",
        "demographics": {"age_range": "26-35", "occupation": "engineer", "gender": ""},
        "dining_habits": {
            "typical_budget": "20-60 SGD",
            "dietary_restrictions": "vegetarian",
            "spice_tolerance": "high",
            "description": "loves quiet cafes and spicy food",
        },
        "metadata": {
            "taste_persona": "into hard sci-fi and slow cafes",
            "constraints": {"language": "en", "content_rating_max": ""},
            "domains": {"movie": {"genres": ["science fiction", "drama"]}},
        },
    }


@pytest.mark.backend_unit
def test_assemble_domains_merges_restaurant_from_dining_habits():
    domains = assemble_domains(_profile())
    assert domains["movie"]["genres"] == ["science fiction", "drama"]
    # restaurant slice comes from dining_habits, structured fields only (no prose).
    assert domains["restaurant"] == {
        "typical_budget": "20-60 SGD",
        "dietary_restrictions": "vegetarian",
        "spice_tolerance": "high",
    }


@pytest.mark.backend_unit
def test_taste_persona_falls_back_to_legacy_description():
    assert taste_persona_of(_profile()) == "into hard sci-fi and slow cafes"
    legacy = {"dining_habits": {"description": "old dining notes"}}
    assert taste_persona_of(legacy) == "old dining notes"


@pytest.mark.backend_unit
def test_fusion_includes_only_the_dispatched_domain_slice():
    block_movie = build_recommender_profile_block(_profile(), "movie")
    # demographics + persona + constraints + movie slice present...
    assert "Demographics: age_range=26-35" in block_movie
    assert "Taste: into hard sci-fi and slow cafes" in block_movie
    assert "Constraints: language=en" in block_movie
    assert "Movie preferences: genres=science fiction, drama" in block_movie
    # ...but the restaurant slice must NOT bleed into a movie request.
    assert "vegetarian" not in block_movie
    assert "Restaurant preferences" not in block_movie

    block_restaurant = build_recommender_profile_block(_profile(), "restaurant")
    assert "Restaurant preferences: typical_budget=20-60 SGD" in block_restaurant
    assert "dietary_restrictions=vegetarian" in block_restaurant
    assert "genres=science fiction" not in block_restaurant


@pytest.mark.backend_unit
def test_fusion_empty_profile_returns_empty_string():
    assert build_recommender_profile_block({}, "movie") == ""
    assert build_recommender_profile_block({"demographics": {}}, "movie") == ""


@pytest.mark.backend_unit
def test_normalize_profile_exposes_three_layers():
    normalized = normalize_profile(_profile())
    assert set(["demographics", "constraints", "taste_persona", "domains"]).issubset(normalized)
    assert normalized["constraints"] == {"language": "en"}  # empty content_rating_max dropped
    assert "restaurant" in normalized["domains"] and "movie" in normalized["domains"]
