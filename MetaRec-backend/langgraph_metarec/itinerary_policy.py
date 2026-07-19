"""Auditable semantic registries shared by itinerary normalization and solving."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, FrozenSet, Iterable, Tuple

ROLE_TOKENS: Dict[str, FrozenSet[str]] = {
    "lodging": frozenset({
        "hotel", "resort hotel", "hostel", "motel", "guest house", "guest_house",
        "apartment hotel", "lodging", "chalet", "resort",
    }),
    "food": frozenset({
        "restaurant", "cafe", "coffee shop", "food court", "fast food", "bar",
        "pub", "bakery", "ice cream shop", "meal takeaway",
    }),
    "shopping": frozenset({
        "shopping mall", "mall", "market", "department store", "retail", "shop",
        "gift shop", "supermarket", "shopping centre", "shopping center",
    }),
    "experience": frozenset({
        "attraction", "tourist attraction", "museum", "gallery", "theme park",
        "theme_park", "water park", "zoo", "aquarium", "viewpoint", "artwork",
        "landmark", "monument", "memorial", "park", "garden", "nature reserve",
        "nature_reserve", "beach", "place of worship", "historic site", "castle",
        "observation deck", "performing arts theater", "stadium",
        "university", "college", "campus",
    }),
    "region": frozenset({
        "city", "country", "island", "neighbourhood", "neighborhood", "locality",
        "route", "street", "administrative", "postal code", "political",
    }),
}

DOMAIN_ALLOWED_ROLES: Dict[str, FrozenSet[str]] = {
    "attraction": frozenset({"experience", "shopping"}),
    "restaurant": frozenset({"food"}),
    "hotel": frozenset({"lodging"}),
}

STRICT_ROLE_ENUM = frozenset({"experience", "food", "shopping", "lodging", "region", "unknown"})
PACE_MIN_PRIMARY_SHARE = {"relaxed": 0.40, "balanced": 0.50, "packed": 0.60}
PACE_MAX_IDLE_GAP = {"relaxed": 120, "balanced": 90, "packed": 60}

_ITINERARY_THEME_PATTERNS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("university-campus", (r"\buniversit(?:y|ies)\b", r"\bcampus(?:es)?\b", r"\bcollege\b", r"大学", r"校园", r"高校")),
    ("museum", (r"\bmuseums?\b", r"博物馆")),
    ("gallery", (r"\bgaller(?:y|ies)\b", r"\bart exhibitions?\b", r"美术馆", r"画廊")),
    ("theme-park", (r"\btheme parks?\b", r"\bamusement parks?\b", r"主题公园", r"游乐园")),
    ("zoo-aquarium", (r"\bzoos?\b", r"\baquariums?\b", r"动物园", r"水族馆")),
    ("viewpoint", (r"\bviewpoints?\b", r"\bobservation decks?\b", r"观景", r"观景台")),
    ("park-nature", (r"\bparks?\b", r"\bgardens?\b", r"\bnature\b", r"公园", r"花园", r"自然")),
    ("historic-site", (r"\bhistor(?:y|ic|ical)\b", r"\bheritage\b", r"历史", r"古迹", r"文化遗产")),
    ("beach", (r"\bbeaches?\b", r"海滩", r"沙滩")),
    ("landmark", (r"\blandmarks?\b", r"\barchitecture\b", r"地标", r"建筑")),
)
_ATTRACTION_TYPE_MATCH_TOKENS: Dict[str, FrozenSet[str]] = {
    "university campus": frozenset({"university", "college", "campus", "academic"}),
    "theme park": frozenset({"theme park", "theme_park", "amusement park", "water park"}),
    "zoo aquarium": frozenset({"zoo", "aquarium"}),
    "park nature": frozenset({"park", "garden", "nature reserve", "beach", "peak", "waterfall"}),
    "historic site": frozenset({"historic", "heritage", "castle", "fort", "monument", "memorial", "ruins"}),
    "landmark": frozenset({"landmark", "attraction", "artwork", "tower", "lighthouse", "architecture"}),
}


@dataclass(frozen=True)
class StylePolicy:
    primary_roles: FrozenSet[str]
    meals_only_food: bool
    minimum_role_families: int = 1
    compound_preferred: bool = False


STYLE_POLICIES: Dict[str, StylePolicy] = {
    "sightseeing": StylePolicy(frozenset({"experience"}), True),
    "food_tour": StylePolicy(frozenset({"food"}), False),
    "shopping": StylePolicy(frozenset({"shopping"}), True),
    "theme_park": StylePolicy(frozenset({"experience"}), True, compound_preferred=True),
    "mixed": StylePolicy(frozenset({"experience", "food", "shopping"}), False, minimum_role_families=2),
}


def role_from_tokens(tokens: Iterable[str]) -> str:
    normalized = {str(token or "").strip().lower().replace("-", " ") for token in tokens}
    normalized.discard("")
    for role in ("lodging", "food", "shopping", "experience", "region"):
        if normalized & {item.replace("-", " ") for item in ROLE_TOKENS[role]}:
            return role
    return "unknown"


def role_allowed(domain: str, role: str) -> bool:
    return role in DOMAIN_ALLOWED_ROLES.get(str(domain).lower(), frozenset())


def style_policy(style: str) -> StylePolicy:
    return STYLE_POLICIES.get(str(style or "").lower(), STYLE_POLICIES["sightseeing"])


def infer_itinerary_attraction_types(text: str) -> Tuple[str, ...]:
    """Return canonical provider filters explicitly mentioned in user text."""
    value = str(text or "").casefold()
    return tuple(
        attraction_type
        for attraction_type, patterns in _ITINERARY_THEME_PATTERNS
        if any(re.search(pattern, value, re.IGNORECASE) for pattern in patterns)
    )


def attraction_type_match_tokens(value: str) -> FrozenSet[str]:
    normalized = str(value or "").strip().casefold().replace("-", " ")
    return _ATTRACTION_TYPE_MATCH_TOKENS.get(normalized, frozenset({normalized}))
