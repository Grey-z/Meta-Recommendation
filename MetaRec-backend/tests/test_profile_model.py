import pytest

from profile_model import (
    apply_profile_memory_from_preferences,
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
def test_assemble_domains_migrates_legacy_metadata_preferences_to_restaurant_slice():
    profile = {
        "metadata": {
            "preferences": {
                "restaurant_types": ["casual"],
                "location": "Chinatown",
            }
        },
        "dining_habits": {"typical_budget": "20-60 SGD"},
    }

    restaurant = assemble_domains(profile)["restaurant"]

    assert restaurant["restaurant_types"] == ["casual"]
    assert restaurant["location"] == "Chinatown"
    assert restaurant["typical_budget"] == "20-60 SGD"


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


@pytest.mark.backend_unit
def test_profile_memory_updates_bounded_general_persona_from_confirmed_preferences():
    profile = {
        "metadata": {
            "taste_persona": "Prefers practical recommendations.",
        }
    }
    updated = apply_profile_memory_from_preferences(
        profile,
        {
            "domain": "product",
            "query": "Recommend a laptop under 2000 SGD for office work",
            "category": "laptop",
            "use_case": "office work",
            "budget": "under 2000 SGD",
        },
        timestamp="2026-07-01T00:00:00+00:00",
    )

    persona = updated["metadata"]["taste_persona"]
    assert "Prefers practical recommendations." in persona
    assert "This user tends to look for laptop recommendations" in persona
    assert "for office work" in persona
    assert "within a budget of under 2000 SGD" in persona
    assert len(persona.split()) <= 300
    assert updated["metadata"]["profile_memory"][0]["evidence"] == "Recommend a laptop under 2000 SGD for office work"


@pytest.mark.backend_unit
def test_profile_memory_requires_repeated_named_entities_before_persona_promotion():
    profile = {"metadata": {"taste_persona": ""}}
    first = apply_profile_memory_from_preferences(
        profile,
        {
            "domain": "music",
            "query": "What songs by Omnipotent Youth Society are good?",
            "artist": "Omnipotent Youth Society",
        },
        timestamp="2026-07-01T00:00:00+00:00",
    )

    assert first["metadata"].get("taste_persona", "") == ""
    assert first["metadata"]["profile_memory"][0]["count"] == 1

    second = apply_profile_memory_from_preferences(
        first,
        {
            "domain": "music",
            "query": "Recommend more music by Omnipotent Youth Society",
            "artist": "Omnipotent Youth Society",
        },
        timestamp="2026-07-02T00:00:00+00:00",
    )

    assert second["metadata"]["profile_memory"][0]["count"] == 2
    assert "artists like Omnipotent Youth Society" in second["metadata"]["taste_persona"]


@pytest.mark.backend_unit
def test_profile_memory_hotel_persona_reads_as_natural_prose():
    updated = apply_profile_memory_from_preferences(
        {"metadata": {"taste_persona": ""}},
        {
            "domain": "hotel",
            "query": "Find a 4-star hotel with a pool near Sentosa",
            "location": "Sentosa",
            "stars": "4",
            "amenities": ["pool"],
        },
        timestamp="2026-07-01T00:00:00+00:00",
    )

    persona = updated["metadata"]["taste_persona"]
    # Pin the facts and the prose shape, not the exact wording — the sentence
    # template may be tweaked without invalidating this test.
    assert persona.startswith("This user")
    assert persona.endswith(".")
    assert "4 star" in persona
    assert "Sentosa" in persona
    assert "pool" in persona
    assert "hotel" in persona.lower()
    stored = {(entry["key"], entry["value"]) for entry in updated["metadata"]["profile_memory"]}
    assert ("location", "Sentosa") in stored
    assert ("stars", "4") in stored
    assert ("amenities", "pool") in stored


@pytest.mark.backend_unit
def test_profile_memory_attraction_persona_reads_as_natural_prose():
    updated = apply_profile_memory_from_preferences(
        {"metadata": {"taste_persona": ""}},
        {
            "domain": "attraction",
            "query": "Museums and viewpoints around Sentosa",
            "location": "Sentosa",
            "attraction_types": ["museum", "theme-park"],
        },
        timestamp="2026-07-01T00:00:00+00:00",
    )

    persona = updated["metadata"]["taste_persona"]
    # Facts + prose shape, not exact wording (see the hotel persona test above).
    assert persona.startswith("This user")
    assert persona.endswith(".")
    assert "museum" in persona
    assert "theme park" in persona  # hyphens humanized, not raw "theme-park"
    assert "Sentosa" in persona
    assert "attraction" in persona.lower()
    stored = {(entry["key"], entry["value"]) for entry in updated["metadata"]["profile_memory"]}
    assert ("location", "Sentosa") in stored
    assert ("attraction_types", "museum") in stored
    assert ("attraction_types", "theme-park") in stored


@pytest.mark.backend_unit
def test_hotel_location_enrichment_uses_profile_context_for_ambiguous_area():
    from profile_model import enrich_hotel_location_preferences, hotel_location_needs_clarification

    profile = {"demographics": {"location": "Singapore"}, "metadata": {"domains": {"hotel": {}}}}
    prefs = {"domain": "hotel", "location": "Chinatown"}

    enriched = enrich_hotel_location_preferences(prefs, profile)

    assert enriched["location"] == "Chinatown, Singapore"
    assert hotel_location_needs_clarification(enriched, profile) is False


@pytest.mark.backend_unit
def test_hotel_location_clarification_when_no_profile_context():
    from profile_model import hotel_location_needs_clarification

    assert hotel_location_needs_clarification({"domain": "hotel", "location": "Chinatown"}, {}) is True
    assert hotel_location_needs_clarification({"domain": "hotel"}, {}) is True


@pytest.mark.backend_unit
def test_profile_memory_restaurant_persona_reads_as_natural_prose():
    updated = apply_profile_memory_from_preferences(
        {"metadata": {"taste_persona": ""}},
        {
            "domain": "restaurant",
            "query": "Find casual spicy food near NTU",
            "restaurant_types": ["casual", "fast_casual"],
            "flavor_profiles": ["savory", "spicy"],
            "location": "NTU",
        },
        timestamp="2026-07-01T00:00:00+00:00",
    )

    persona = updated["metadata"]["taste_persona"]
    # Facts + prose shape, not exact wording (see the hotel persona test above).
    assert persona.startswith("This user")
    assert persona.endswith(".")
    assert "casual" in persona
    assert "fast casual" in persona  # underscores humanized, not raw "fast_casual"
    assert "savory" in persona and "spicy" in persona
    assert "NTU" in persona
    assert "Restaurants -" not in persona
    assert "styles:" not in persona

    combined = apply_profile_memory_from_preferences(
        updated,
        {
            "domain": "product",
            "query": "Find a laptop for office work",
            "category": "laptop",
            "use_case": "office work",
        },
        timestamp="2026-07-02T00:00:00+00:00",
    )
    assert ".." not in combined["metadata"]["taste_persona"]
    assert "Products -" not in combined["metadata"]["taste_persona"]


@pytest.mark.backend_unit
def test_profile_memory_does_not_overwrite_user_edited_persona():
    profile = {
        "metadata": {
            "taste_persona": "User-written profile that intentionally removed the generated text.",
            "taste_persona_auto": "Products - use cases: office work.",
            "profile_memory": [
                {
                    "domain": "product",
                    "key": "use_case",
                    "value": "office work",
                    "source": "confirmed_recommendation",
                    "confidence": 0.85,
                    "count": 1,
                    "first_seen": "2026-07-01T00:00:00+00:00",
                    "last_seen": "2026-07-01T00:00:00+00:00",
                    "evidence": "old",
                }
            ],
        }
    }

    updated = apply_profile_memory_from_preferences(
        profile,
        {
            "domain": "product",
            "query": "Find a laptop for study",
            "use_case": "study",
        },
        timestamp="2026-07-02T00:00:00+00:00",
    )

    assert updated["metadata"]["taste_persona"] == profile["metadata"]["taste_persona"]
    assert updated["metadata"]["taste_persona_auto"]
    assert len(updated["metadata"]["profile_memory"]) == 2
