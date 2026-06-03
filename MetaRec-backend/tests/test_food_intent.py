import pytest

from langgraph_metarec.nodes.food_intent import (
    extract_food_intent_keywords,
    is_food_intent_strict,
    is_meaningful_food_intent,
    normalize_food_intent,
    relax_food_intent,
    restaurant_matches_food_intent,
)
from langgraph_metarec.nodes.preferences import merge_preferences
from service import MetaRecService


def _bare_service() -> MetaRecService:
    # The consistency / fallback helpers don't touch __init__ state.
    return MetaRecService.__new__(MetaRecService)


# ---------------------------------------------------------------- extraction

@pytest.mark.backend_unit
@pytest.mark.parametrize(
    "text,cuisine,dish",
    [
        ("Vietnamese Pho near Bugis", "vietnamese", "pho"),
        ("I want a Kopi-C", "kopitiam", "kopi"),
        ("spicy american burger", "american", "burger"),
    ],
)
def test_gazetteer_extracts_cuisine_and_dish(text, cuisine, dish):
    fi = extract_food_intent_keywords(text)
    assert cuisine in fi["cuisines"]
    assert dish in fi["dishes"]
    assert is_food_intent_strict(fi)  # exact gazetteer hit => strict


@pytest.mark.backend_unit
@pytest.mark.parametrize("text", ["somewhere nice for dinner", "some asian noodles", ""])
def test_gazetteer_ignores_no_or_ambiguous_food(text):
    fi = extract_food_intent_keywords(text)
    assert not is_meaningful_food_intent(fi)
    assert not is_food_intent_strict(fi)


@pytest.mark.backend_unit
def test_confidence_gating_soft_vs_strict():
    soft = {"cuisines": ["vietnamese"], "dishes": ["pho"], "confidence": 0.3}
    strict = {"cuisines": ["vietnamese"], "dishes": ["pho"], "confidence": 0.8}
    assert is_meaningful_food_intent(soft)
    assert not is_food_intent_strict(soft)
    assert is_food_intent_strict(strict)


@pytest.mark.backend_unit
def test_normalize_cleans_and_clamps():
    fi = normalize_food_intent({"cuisines": ["Any", "VIETNAMESE"], "dishes": ["Pho", "pho"], "confidence": "1.5"})
    assert fi == {"cuisines": ["vietnamese"], "dishes": ["pho"], "confidence": 1.0}
    assert normalize_food_intent({"cuisines": [], "dishes": []}) == {"cuisines": [], "dishes": [], "confidence": 0.0}


@pytest.mark.backend_unit
def test_relax_drops_dish_keeps_cuisine():
    fi = {"cuisines": ["vietnamese"], "dishes": ["pho"], "confidence": 0.9}
    relaxed = relax_food_intent(fi)
    assert relaxed["dishes"] == []
    assert relaxed["cuisines"] == ["vietnamese"]
    # Nothing to relax to when there is no cuisine fallback.
    assert relax_food_intent({"cuisines": [], "dishes": ["pho"], "confidence": 0.9}) is None


@pytest.mark.backend_unit
def test_restaurant_match():
    fi = {"cuisines": ["vietnamese"], "dishes": ["pho"], "confidence": 0.9}
    assert restaurant_matches_food_intent("Pho 99 - authentic vietnamese", fi)
    assert not restaurant_matches_food_intent("Best sushi bar in town", fi)


# ------------------------------------------------------------------- merge

@pytest.mark.backend_unit
def test_merge_overlays_meaningful_food_intent_and_keeps_base_otherwise():
    base = {"location": "Bugis", "food_intent": {"cuisines": [], "dishes": [], "confidence": 0.0}}
    overlay = {"food_intent": {"cuisines": ["vietnamese"], "dishes": ["pho"], "confidence": 0.9}}
    merged = merge_preferences(base, overlay)
    assert merged["food_intent"]["dishes"] == ["pho"]

    # Empty overlay must not clobber an existing intent under review.
    pending = {"food_intent": {"cuisines": ["vietnamese"], "dishes": ["pho"], "confidence": 0.9}}
    empty_overlay = {"food_intent": {"cuisines": [], "dishes": [], "confidence": 0.0}}
    assert merge_preferences(pending, empty_overlay)["food_intent"]["dishes"] == ["pho"]


@pytest.mark.backend_unit
def test_runtime_baseline_strips_food_intent_no_stickiness():
    defaults = MetaRecService.get_default_preferences(MetaRecService.__new__(MetaRecService))
    profile = {"metadata": {"preferences": {"food_intent": {"cuisines": ["vietnamese"], "dishes": ["pho"], "confidence": 0.9}, "location": "Chinatown"}}}
    conversation = {"food_intent": {"cuisines": ["thai"], "dishes": ["pad thai"], "confidence": 0.9}}

    selected = MetaRecService._select_runtime_preferences(defaults, profile, conversation)

    # A previous query's dish must never seed the next request's baseline.
    assert selected["food_intent"] == {"cuisines": [], "dishes": [], "confidence": 0.0}
    # Non-food prefs still layer through normally.
    assert selected["location"] == "Chinatown"


# ----------------------------------------------------------- consistency check

@pytest.mark.backend_unit
def test_strict_food_intent_hard_rejects_off_cuisine():
    svc = _bare_service()
    prefs = {
        "food_intent": {"cuisines": ["vietnamese"], "dishes": ["pho"], "confidence": 0.9},
        "budget_range": {}, "restaurant_types": ["any"], "flavor_profiles": ["any"],
        "dining_purpose": "any", "location": "any",
    }
    sushi = {"name": "Sushi Place", "cuisine": "Japanese", "why": "great sushi"}
    pho = {"name": "Pho 99", "cuisine": "Vietnamese", "why": "authentic pho", "rating": 4.5}
    kept, stats = svc._apply_preference_consistency_check([sushi, pho], prefs, "Vietnamese Pho")
    assert [r["name"] for r in kept] == ["Pho 99"]
    assert stats.get("food_intent_mismatch") == 1


@pytest.mark.backend_unit
def test_soft_food_intent_does_not_hard_reject():
    svc = _bare_service()
    prefs = {
        "food_intent": {"cuisines": ["vietnamese"], "dishes": ["pho"], "confidence": 0.3},
        "budget_range": {}, "restaurant_types": ["any"], "flavor_profiles": ["any"],
        "dining_purpose": "any", "location": "any",
    }
    sushi = {"name": "Sushi Place", "cuisine": "Japanese", "why": "great sushi"}
    kept, _ = svc._apply_preference_consistency_check([sushi], prefs, "maybe pho")
    assert [r["name"] for r in kept] == ["Sushi Place"]


# --------------------------------------------------------------- empty fallback

@pytest.mark.backend_unit
def test_empty_fallback_relaxes_dish_to_cuisine_then_empties():
    svc = _bare_service()
    prefs = {"food_intent": {"cuisines": ["vietnamese"], "dishes": ["pho"], "confidence": 0.9}}
    sushi = {"name": "Sushi Place", "cuisine": "Japanese"}
    viet = {"name": "Saigon Kitchen", "cuisine": "Vietnamese", "rating": 4.2}

    # Relax dish -> cuisine: a Vietnamese place survives even if not "pho".
    relaxed = svc._select_empty_fallback([sushi, viet], prefs, "pho", {"food_intent_mismatch": 2})
    assert [r["name"] for r in relaxed] == ["Saigon Kitchen"]

    # No cuisine match at all -> empty (never substitute unrelated results).
    assert svc._select_empty_fallback([sushi], prefs, "pho", {"food_intent_mismatch": 1}) == []


@pytest.mark.backend_unit
def test_empty_fallback_non_strict_uses_top_rated():
    svc = _bare_service()
    prefs = {"food_intent": {"cuisines": [], "dishes": [], "confidence": 0.0}}
    a = {"name": "A", "rating": 3.0}
    b = {"name": "B", "rating": 4.8}
    result = svc._select_empty_fallback([a, b], prefs, "dinner", {})
    assert [r["name"] for r in result] == ["B", "A"]
