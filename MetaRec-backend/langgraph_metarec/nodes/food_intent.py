"""Explicit food-intent (cuisine / dish) extraction and matching.

The recommender is primarily flavor/preference driven. When a user explicitly
names a cuisine or dish ("Vietnamese Pho", "American Burger", "Kopi-C"), that
declaration should *narrow* the recommendation rather than be flattened into an
abstract flavour. This module is the single, pure (no service deps) home for the
``food_intent`` dimension so it can be reused by the LLM normaliser, the
preference merge, the consistency check, and the restaurant graph without import
cycles.

``food_intent`` shape::

    {"cuisines": ["vietnamese"], "dishes": ["pho"], "confidence": 0.9}

Narrowing is *confidence-gated*: it only becomes a hard constraint when the intent
is meaningful AND ``confidence >= FOOD_INTENT_STRICT_CONFIDENCE``. Below that it is
treated as a soft search hint only.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

# Hard narrowing only kicks in at/above this confidence. The LLM supplies its own
# confidence; the keyword fallback uses HIGH_CONFIDENCE for exact gazetteer hits.
FOOD_INTENT_STRICT_CONFIDENCE = 0.6
_HIGH_CONFIDENCE = 0.9

# Surface form -> normalized {cuisine, dish}. Multi-word keys are matched as whole
# phrases; single tokens are matched on word boundaries. Extend freely.
FOOD_GAZETTEER: Dict[str, Dict[str, str]] = {
    # Vietnamese
    "pho": {"cuisine": "vietnamese", "dish": "pho"},
    "banh mi": {"cuisine": "vietnamese", "dish": "banh mi"},
    "vietnamese": {"cuisine": "vietnamese"},
    # Singaporean / kopitiam
    "kopi-c": {"cuisine": "kopitiam", "dish": "kopi"},
    "kopi c": {"cuisine": "kopitiam", "dish": "kopi"},
    "kopi o": {"cuisine": "kopitiam", "dish": "kopi"},
    "kopi": {"cuisine": "kopitiam", "dish": "kopi"},
    "teh tarik": {"cuisine": "kopitiam", "dish": "teh"},
    "laksa": {"cuisine": "singaporean", "dish": "laksa"},
    "char kway teow": {"cuisine": "singaporean", "dish": "char kway teow"},
    "chicken rice": {"cuisine": "singaporean", "dish": "chicken rice"},
    "nasi lemak": {"cuisine": "singaporean", "dish": "nasi lemak"},
    "bak kut teh": {"cuisine": "singaporean", "dish": "bak kut teh"},
    "hokkien mee": {"cuisine": "singaporean", "dish": "hokkien mee"},
    "singaporean": {"cuisine": "singaporean"},
    "peranakan": {"cuisine": "peranakan"},
    # American / Western
    "burger": {"cuisine": "american", "dish": "burger"},
    "cheeseburger": {"cuisine": "american", "dish": "burger"},
    "hot dog": {"cuisine": "american", "dish": "hot dog"},
    "bbq": {"cuisine": "american", "dish": "bbq"},
    "steak": {"cuisine": "western", "dish": "steak"},
    "american": {"cuisine": "american"},
    "western": {"cuisine": "western"},
    # Japanese
    "ramen": {"cuisine": "japanese", "dish": "ramen"},
    "sushi": {"cuisine": "japanese", "dish": "sushi"},
    "udon": {"cuisine": "japanese", "dish": "udon"},
    "tempura": {"cuisine": "japanese", "dish": "tempura"},
    "yakitori": {"cuisine": "japanese", "dish": "yakitori"},
    "japanese": {"cuisine": "japanese"},
    # Korean
    "kimchi": {"cuisine": "korean", "dish": "kimchi"},
    "bibimbap": {"cuisine": "korean", "dish": "bibimbap"},
    "korean bbq": {"cuisine": "korean", "dish": "korean bbq"},
    "korean": {"cuisine": "korean"},
    # Thai
    "pad thai": {"cuisine": "thai", "dish": "pad thai"},
    "tom yum": {"cuisine": "thai", "dish": "tom yum"},
    "green curry": {"cuisine": "thai", "dish": "green curry"},
    "thai": {"cuisine": "thai"},
    # Indian
    "biryani": {"cuisine": "indian", "dish": "biryani"},
    "tandoori": {"cuisine": "indian", "dish": "tandoori"},
    "naan": {"cuisine": "indian", "dish": "naan"},
    "curry": {"cuisine": "indian", "dish": "curry"},
    "indian": {"cuisine": "indian"},
    # Chinese / Sichuan
    "sichuan": {"cuisine": "sichuan"},
    "dim sum": {"cuisine": "chinese", "dish": "dim sum"},
    "mapo tofu": {"cuisine": "sichuan", "dish": "mapo tofu"},
    "hotpot": {"cuisine": "chinese", "dish": "hotpot"},
    "chinese": {"cuisine": "chinese"},
    "cantonese": {"cuisine": "cantonese"},
    # Italian
    "pizza": {"cuisine": "italian", "dish": "pizza"},
    "pasta": {"cuisine": "italian", "dish": "pasta"},
    "risotto": {"cuisine": "italian", "dish": "risotto"},
    "italian": {"cuisine": "italian"},
}

# Bare tokens too ambiguous to narrow on their own (need richer signal).
_AMBIGUOUS_TERMS = {"asian", "noodles", "rice", "food", "any", "soup", "drink"}


def empty_food_intent() -> Dict[str, Any]:
    return {"cuisines": [], "dishes": [], "confidence": 0.0}


def _clean_terms(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    seen: List[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        term = item.strip().lower()
        if not term or term == "any" or term in _AMBIGUOUS_TERMS:
            continue
        if term not in seen:
            seen.append(term)
    return seen


def normalize_food_intent(raw: Any) -> Dict[str, Any]:
    """Coerce arbitrary (LLM/stored) input into the canonical food_intent dict."""
    if not isinstance(raw, dict):
        return empty_food_intent()
    cuisines = _clean_terms(raw.get("cuisines"))
    dishes = _clean_terms(raw.get("dishes"))
    try:
        confidence = float(raw.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))
    if not cuisines and not dishes:
        # No usable terms => not meaningful, regardless of any stray confidence.
        return empty_food_intent()
    return {"cuisines": cuisines, "dishes": dishes, "confidence": confidence}


def extract_food_intent_keywords(text: Optional[str]) -> Dict[str, Any]:
    """Gazetteer fallback used when the LLM is unavailable (and offline path).

    Exact phrase / word-boundary hits yield HIGH confidence so they narrow hard;
    ambiguous bare tokens are ignored.
    """
    if not text or not isinstance(text, str):
        return empty_food_intent()
    lowered = text.lower()
    cuisines: List[str] = []
    dishes: List[str] = []
    for surface, mapped in FOOD_GAZETTEER.items():
        if " " in surface:
            hit = surface in lowered
        else:
            hit = re.search(rf"\b{re.escape(surface)}\b", lowered) is not None
        if not hit:
            continue
        cuisine = mapped.get("cuisine")
        dish = mapped.get("dish")
        if cuisine and cuisine not in cuisines:
            cuisines.append(cuisine)
        if dish and dish not in dishes:
            dishes.append(dish)
    if not cuisines and not dishes:
        return empty_food_intent()
    return {"cuisines": cuisines, "dishes": dishes, "confidence": _HIGH_CONFIDENCE}


def is_meaningful_food_intent(food_intent: Any) -> bool:
    if not isinstance(food_intent, dict):
        return False
    return bool(_clean_terms(food_intent.get("cuisines")) or _clean_terms(food_intent.get("dishes")))


def is_food_intent_strict(food_intent: Any) -> bool:
    """True when the intent should narrow hard (meaningful AND confident enough)."""
    if not is_meaningful_food_intent(food_intent):
        return False
    try:
        confidence = float(food_intent.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    return confidence >= FOOD_INTENT_STRICT_CONFIDENCE


def food_intent_terms(food_intent: Any) -> List[str]:
    """All cuisine + dish surface terms, for search query building and matching."""
    if not isinstance(food_intent, dict):
        return []
    terms: List[str] = []
    for term in _clean_terms(food_intent.get("dishes")) + _clean_terms(food_intent.get("cuisines")):
        if term not in terms:
            terms.append(term)
    return terms


def restaurant_matches_food_intent(text_blob: str, food_intent: Any) -> bool:
    """Whether a restaurant's text mentions any cuisine/dish term."""
    terms = food_intent_terms(food_intent)
    if not terms:
        return True  # nothing to match against -> not a mismatch
    blob = (text_blob or "").lower()
    return any(term in blob for term in terms)


def relax_food_intent(food_intent: Any) -> Optional[Dict[str, Any]]:
    """Relax a strict intent by one tier: drop dishes, keep cuisines.

    Returns the relaxed intent, or None when there is nothing left to relax to
    (no cuisines to fall back on). Used for the controlled "no exact match"
    fallback so we widen to the cuisine rather than substitute unrelated results.
    """
    if not isinstance(food_intent, dict):
        return None
    cuisines = _clean_terms(food_intent.get("cuisines"))
    dishes = _clean_terms(food_intent.get("dishes"))
    if dishes and cuisines:
        return {"cuisines": cuisines, "dishes": [], "confidence": float(food_intent.get("confidence", 0.0) or 0.0)}
    return None
