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
