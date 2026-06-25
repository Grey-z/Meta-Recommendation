import pytest

from llm_service import analyze_user_message
from service import MetaRecService

from conftest import FakeAsyncClient, query_intent_json


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_analyze_user_message_parses_structured_json():
    client = FakeAsyncClient([query_intent_json("I'll help you find spicy restaurants.")])
    result = await analyze_user_message(
        client=client,
        message="Find spicy casual places in Chinatown",
        model="fake-model",
        max_format_retries=0,
    )

    assert result.intent == "query"
    assert result.preferences is not None
    assert result.preferences["restaurant_types"] == ["casual"]
    assert result.preferences["location"] == "Chinatown"
    assert "spicy" in result.preferences["flavor_profiles"]


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_analyze_user_message_preserves_generic_preferences():
    client = FakeAsyncClient(
        [
            """
            {
              "intent": "query",
              "reply": "I'll help you find a movie.",
              "confidence": 0.9,
              "preferences": {
                "domain": "movie",
                "genres": ["science fiction"],
                "mood": "quiet"
              }
            }
            """
        ]
    )

    result = await analyze_user_message(
        client=client,
        message="Recommend a quiet science fiction movie",
        model="fake-model",
        max_format_retries=0,
    )

    assert result.intent == "query"
    assert result.preferences == {
        "domain": "movie",
        "genres": ["science fiction"],
        "mood": "quiet",
    }


@pytest.mark.backend_unit
def test_normalize_profile_updates_keeps_supported_fields_and_merges_unknown_to_description():
    raw = {
        "demographics": {"age_range": ["26-35"], "hobby": "hiking"},
        "dining_habits": {"dietary_restrictions": ["vegetarian", "halal"], "unknown_field": "late-night"},
    }
    normalized = MetaRecService._normalize_profile_updates(raw)

    assert normalized["demographics"]["age_range"] == "26-35"
    assert "unknown_field: late-night" in normalized["dining_habits"]["description"]
    assert normalized["dining_habits"]["dietary_restrictions"] == "vegetarian, halal"


@pytest.mark.backend_unit
def test_runtime_preferences_use_profile_when_conversation_preferences_empty():
    defaults = {
        "restaurant_types": ["any"],
        "flavor_profiles": ["any"],
        "dining_purpose": "any",
        "budget_range": {"min": 20, "max": 60, "currency": "SGD", "per": "person"},
        "location": "any",
    }
    profile = {
        "metadata": {
            "preferences": {
                "restaurant_types": ["casual"],
                "flavor_profiles": ["spicy"],
                "dining_purpose": "friends",
                "budget_range": {"min": 45, "max": 90, "currency": "SGD", "per": "person"},
                "location": "Chinatown",
            }
        }
    }

    selected = MetaRecService._select_runtime_preferences(defaults, profile, {})

    assert selected["flavor_profiles"] == ["spicy"]
    assert selected["budget_range"]["min"] == 45


@pytest.mark.backend_unit
def test_runtime_preferences_allow_non_empty_conversation_override():
    defaults = {"location": "any"}
    profile = {"metadata": {"preferences": {"location": "Chinatown"}}}

    selected = MetaRecService._select_runtime_preferences(defaults, profile, {"location": "Bugis"})

    assert selected["location"] == "Bugis"


@pytest.mark.backend_unit
def test_merge_preferences_keeps_base_when_overlay_is_unspecified():
    from langgraph_metarec.nodes.preferences import merge_preferences

    base = {
        "restaurant_types": ["any"],
        "flavor_profiles": ["spicy"],
        "dining_purpose": "friends",
        "budget_range": {"min": 5, "max": 10, "currency": "SGD", "per": "person"},
        "location": "Chinatown",
    }
    # Overlay as the LLM emits it when the prompt only mentioned a cafe: a real
    # restaurant type, but "any"/default everything else (incl. the 20-60 budget).
    overlay = {
        "restaurant_types": ["cafe"],
        "flavor_profiles": ["any"],
        "dining_purpose": "any",
        "budget_range": {"min": 20, "max": 60, "currency": "SGD"},
        "location": "any",
    }
    merged = merge_preferences(base, overlay)

    assert merged["restaurant_types"] == ["cafe"]      # meaningful overlay wins
    assert merged["flavor_profiles"] == ["spicy"]       # 'any' overlay -> keep base
    assert merged["dining_purpose"] == "friends"        # 'any' overlay -> keep base
    assert merged["budget_range"]["min"] == 5           # default budget -> keep base
    assert merged["budget_range"]["max"] == 10
    assert merged["location"] == "Chinatown"            # 'any' overlay -> keep base


@pytest.mark.backend_unit
def test_merge_preferences_meaningful_overlay_overrides_base():
    from langgraph_metarec.nodes.preferences import merge_preferences

    merged = merge_preferences(
        {"budget_range": {"min": 5, "max": 10}, "location": "Chinatown"},
        {"budget_range": {"min": 30, "max": 50}, "location": "Bugis"},
    )
    assert merged["budget_range"] == {"min": 30, "max": 50}
    assert merged["location"] == "Bugis"


@pytest.mark.backend_unit
def test_runtime_preferences_derive_budget_and_location_from_profile_fields():
    defaults = {
        "restaurant_types": ["any"],
        "flavor_profiles": ["any"],
        "dining_purpose": "any",
        "budget_range": {"min": 20, "max": 60, "currency": "SGD", "per": "person"},
        "location": "any",
    }
    # Editable profile fields (no metadata.preferences set) must seed the baseline.
    profile = {
        "dining_habits": {"typical_budget": "5-10 SGD"},
        "demographics": {"location": "Bugis"},
    }

    selected = MetaRecService._select_runtime_preferences(defaults, profile, None)

    assert selected["budget_range"]["min"] == 5
    assert selected["budget_range"]["max"] == 10
    assert selected["location"] == "Bugis"


@pytest.mark.backend_unit
def test_extract_restaurants_from_summary_string():
    data = {
        "summary": (
            '{"recommendations":[{"name":"Mock Bistro","area":"Chinatown","cuisine":"Sichuan",'
            '"price_per_person_sgd":"20-30","flavor_match":["Spicy"],"purpose_match":["Friends"],'
            '"why":"Great fit","sources":{"google_maps":"place-1"}}]}'
        ),
        "executions": [],
    }

    restaurants = MetaRecService._extract_restaurants_from_execution_data(data)

    assert len(restaurants) == 1
    assert restaurants[0]["name"] == "Mock Bistro"
    assert restaurants[0]["sources"] == {"google_maps": "place-1"}
