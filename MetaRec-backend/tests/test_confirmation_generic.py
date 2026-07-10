import json

import pytest

from conftest import FakeAsyncClient
from llm_service import (
    _summarize_preferences_for_confirmation,
    _humanize_domain_label,
    generate_confirmation_payload,
)


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


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_generate_confirmation_payload_accepts_structured_quick_actions():
    content = json.dumps(
        {
            "message": "好的，我会按 2000 SGD 以内找电脑。主要用途是哪类？",
            "quick_actions": [
                {
                    "id": "use_case_work",
                    "label": "办公",
                    "value": "work",
                    "preference_patch": {"use_case": "work"},
                },
                {
                    "id": "use_case_study",
                    "label": "学习",
                    "value": "study",
                    "preference_patch": {"use_case": "study"},
                },
                {
                    "id": "use_case_gaming",
                    "label": "游戏",
                    "value": "gaming",
                    "preference_patch": {"use_case": "gaming"},
                },
            ],
        },
        ensure_ascii=False,
    )
    payload = await generate_confirmation_payload(
        FakeAsyncClient([content]),
        "推荐 2000 SGD 以内的电脑",
        {"domain": "product", "query": "推荐 2000 SGD 以内的电脑"},
        domain="product",
        language="zh",
        max_text_retries=0,
    )

    assert payload["message"].startswith("好的")
    assert "办公" in payload["message"]
    assert "学习" in payload["message"]
    assert "游戏" in payload["message"]
    assert [action["label"] for action in payload["quick_actions"]] == ["办公", "学习", "游戏"]
    assert payload["quick_actions"][0]["preference_patch"] == {"use_case": "work"}


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_generate_confirmation_payload_drops_invalid_quick_actions():
    content = json.dumps(
        {
            "message": "Confirm this movie request?",
            "quick_actions": [
                {"id": "bad", "label": "Nolan", "value": "Nolan", "preference_patch": {"director": "Nolan"}},
                {"id": "also_bad", "label": "Open text", "value": "x", "preference_patch": {"unknown": "x"}},
            ],
        }
    )
    payload = await generate_confirmation_payload(
        FakeAsyncClient([content]),
        "recommend a movie",
        {"domain": "movie", "query": "recommend a movie"},
        domain="movie",
        language="en",
        max_text_retries=0,
    )

    assert payload == {"message": "Confirm this movie request?"}


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_generate_confirmation_payload_allows_hotel_star_quick_actions():
    content = json.dumps(
        {
            "message": "Which hotel class should I target: 3-star, 4-star, or 5-star?",
            "quick_actions": [
                {"id": "stars_3", "label": "3-star", "value": "3", "preference_patch": {"stars": "3"}},
                {"id": "stars_4", "label": "4-star", "value": "4", "preference_patch": {"stars": "4"}},
                {"id": "stars_5", "label": "5-star", "value": "5", "preference_patch": {"stars": "5"}},
                {"id": "bad_location", "label": "Chinatown", "value": "Chinatown", "preference_patch": {"location": "Chinatown"}},
            ],
        }
    )

    payload = await generate_confirmation_payload(
        FakeAsyncClient([content]),
        "recommend a hotel in Singapore",
        {"domain": "hotel", "query": "recommend a hotel in Singapore"},
        domain="hotel",
        language="en",
        max_text_retries=0,
    )

    assert [action["label"] for action in payload["quick_actions"]] == ["3-star", "4-star", "5-star"]
    assert payload["quick_actions"][1]["preference_patch"] == {"stars": "4"}


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_generate_confirmation_payload_allows_attraction_type_quick_actions():
    content = json.dumps(
        {
            "message": "What kind of attraction are you after: museums, theme parks, or viewpoints?",
            "quick_actions": [
                {"id": "type_museum", "label": "Museums", "value": "museum", "preference_patch": {"attraction_types": ["museum"]}},
                {"id": "type_theme_park", "label": "Theme parks", "value": "theme-park", "preference_patch": {"attraction_types": ["theme-park"]}},
                {"id": "bad_location", "label": "Sentosa", "value": "Sentosa", "preference_patch": {"location": "Sentosa"}},
            ],
        }
    )

    payload = await generate_confirmation_payload(
        FakeAsyncClient([content]),
        "things to do in Singapore",
        {"domain": "attraction", "query": "things to do in Singapore"},
        domain="attraction",
        language="en",
        max_text_retries=0,
    )

    # Attraction-type patches survive; the free-text location button is dropped.
    assert [action["label"] for action in payload["quick_actions"]] == ["Museums", "Theme parks"]
    assert payload["quick_actions"][0]["preference_patch"] == {"attraction_types": ["museum"]}


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_generate_confirmation_payload_does_not_leak_malformed_json():
    payload = await generate_confirmation_payload(
        FakeAsyncClient(['{ "message']),
        "帮我推荐一台好用的电脑呗？预算在2000 SGD以内",
        {
            "domain": "product",
            "query": "帮我推荐一台好用的电脑呗？预算在2000 SGD以内",
            "budget_range": {"max": 2000, "currency": "SGD"},
        },
        domain="product",
        language="zh",
        max_text_retries=0,
    )

    assert payload["message"].startswith("我理解您想要商品推荐")
    assert "{ \"message" not in payload["message"]
    assert "quick_actions" not in payload
