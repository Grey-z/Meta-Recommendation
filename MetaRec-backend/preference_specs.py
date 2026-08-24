"""Request-time preference form generation.

A small per-domain ``PreferenceSpec`` registry that the backend turns into a
machine-readable form *at request time* (reflecting which preferences are still
missing). The frontend renders the form generically, so adding a domain's form
is a data change here — no new UI per domain.

One schema, three consumers: this same registry can drive the LLM extraction
hints, the request-time form, and the per-domain profile slice editor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from langgraph_metarec.genres import MOVIE_GENRE_IDS, MUSIC_GENRES

# Supported field renderings; the frontend PreferenceForm maps these to widgets.
FIELD_TYPES = {"select", "multiselect", "text", "range", "date", "time", "number"}


@dataclass(frozen=True)
class PreferenceSpec:
    key: str
    label: str
    field_type: str
    options: List[str] = field(default_factory=list)
    required: bool = False
    placeholder: str = ""
    required_when: Optional[Tuple[Any, ...]] = None
    min_value: Optional[float] = None
    max_value: Optional[float] = None

    def __post_init__(self) -> None:
        if self.field_type not in FIELD_TYPES:
            raise ValueError(f"Unsupported field_type: {self.field_type}")


_MOVIE_GENRES = sorted(MOVIE_GENRE_IDS)
_MUSIC_GENRES = sorted(MUSIC_GENRES)
# Canonical restaurant option keys the backend recognizes (service mappings + LLM
# schema). Order is display order, not sorted.
_FLAVOR_PROFILES = ["spicy", "savory", "sweet", "sour", "mild"]
_RESTAURANT_TYPES = ["casual", "fine-dining", "fast-casual", "street-food", "buffet", "cafe"]
_DINING_PURPOSES = ["date-night", "family", "friends", "business", "solo", "celebration"]
_ATTRACTION_TYPES = [
    "museum", "gallery", "theme-park", "zoo-aquarium", "landmark", "viewpoint",
    "park-nature", "historic-site", "beach", "university-campus",
]

# Per-domain form definitions. Keep these minimal — only what actually drives a
# search/tool param or is a hard constraint worth asking for. Field keys are kept
# identical to the keys the LLM extractor emits, the generic-graph param mapper
# reads, and the per-domain profile slice stores — so one field flows end to end.
DOMAIN_PREFERENCE_SPECS: Dict[str, List[PreferenceSpec]] = {
    "restaurant": [
        PreferenceSpec("location", "Location", "text", required=True, placeholder="e.g. Chinatown"),
        PreferenceSpec("restaurant_types", "Restaurant types", "multiselect", options=_RESTAURANT_TYPES),
        PreferenceSpec("flavor_profiles", "Flavor profiles", "multiselect", options=_FLAVOR_PROFILES),
        PreferenceSpec("dining_purpose", "Dining purpose", "select", options=_DINING_PURPOSES),
        PreferenceSpec("dietary_restrictions", "Dietary restrictions", "text", placeholder="e.g. vegetarian"),
        PreferenceSpec("typical_budget", "Budget per person", "text", placeholder="e.g. 20-60 SGD"),
    ],
    "hotel": [
        PreferenceSpec("location", "Destination / area", "text", required=True, placeholder="e.g. Sentosa"),
        PreferenceSpec("stars", "Exact star class", "select", options=["2", "3", "4", "5"]),
        PreferenceSpec("amenities", "Amenities", "text", placeholder="e.g. pool, free wifi"),
        PreferenceSpec("budget", "Budget per night", "text", placeholder="e.g. < 200 SGD"),
    ],
    # Itinerary is a routing *mode*: this form gates the day-plan confirmation
    # (destination anchor + display-only budget + start time). It deliberately
    # has no profile tab — the frontend's DOMAIN_ORDER does not include it.
    "itinerary": [
        PreferenceSpec("location", "Destination / area", "text", required=True, placeholder="e.g. Sentosa"),
        PreferenceSpec("date", "First travel date", "date", placeholder="Defaults to tomorrow"),
        PreferenceSpec("horizon_days", "Number of days", "number", required=True, min_value=1, max_value=3),
        PreferenceSpec("daily_start_time", "Daily start time", "time", placeholder="Defaults to 09:00"),
        PreferenceSpec("daily_end_time", "Daily end time", "time", placeholder="Defaults to 22:00"),
        PreferenceSpec("budget_mode", "Budget", "select", options=["limited", "unlimited"], required=True),
        PreferenceSpec("budget_amount", "Total trip budget per person", "number", placeholder="e.g. 450", required_when=("budget_mode", "limited"), min_value=0.01),
        PreferenceSpec("budget_currency", "Currency", "text", placeholder="e.g. SGD", required_when=("budget_mode", "limited")),
        PreferenceSpec("travelers", "Travelers", "number", required_when=("horizon_days", "gt", 1), min_value=1),
        PreferenceSpec("rooms", "Rooms", "number", required_when=("horizon_days", "gt", 1), min_value=1),
        PreferenceSpec("timezone", "Timezone", "text", required=True, placeholder="e.g. Asia/Singapore"),
        PreferenceSpec("hotel_anchor", "Starting hotel", "text", placeholder="Hotel name or address"),
        PreferenceSpec("anchor_policy", "Route end", "select", options=["round_trip", "start_only", "distinct_end"]),
        PreferenceSpec("end_anchor", "Ending place", "text", placeholder="Hotel, address, or POI", required_when=("anchor_policy", "distinct_end")),
        PreferenceSpec("style", "Itinerary style", "select", options=["sightseeing", "food_tour", "shopping", "theme_park", "mixed"], required=True),
        PreferenceSpec("pace", "Pace", "select", options=["relaxed", "balanced", "packed"], required=True),
        PreferenceSpec("attraction_types", "Trip interests", "multiselect", options=_ATTRACTION_TYPES),
    ],
    "attraction": [
        PreferenceSpec("location", "Destination / area", "text", required=True, placeholder="e.g. Sentosa"),
        PreferenceSpec(
            "attraction_types",
            "Attraction types",
            "multiselect",
            options=_ATTRACTION_TYPES,
        ),
        PreferenceSpec("budget", "Budget", "text", placeholder="e.g. free, < 50 SGD"),
    ],
    "movie": [
        PreferenceSpec("genres", "Genres", "multiselect", options=_MOVIE_GENRES, required=True),
        PreferenceSpec("exclude_genres", "Exclude genres", "multiselect", options=_MOVIE_GENRES),
        PreferenceSpec("actors", "Actors", "text", placeholder="e.g. Cillian Murphy"),
        PreferenceSpec("directors", "Directors", "text", placeholder="e.g. Christopher Nolan"),
        PreferenceSpec("min_rating", "Minimum rating", "text", placeholder="e.g. 7.5"),
    ],
    "book": [
        PreferenceSpec("genres", "Genres / themes", "text", required=True, placeholder="e.g. science fiction"),
        PreferenceSpec("author", "Author", "text", placeholder="e.g. Brandon Sanderson"),
        PreferenceSpec("publisher", "Publisher", "text", placeholder="e.g. Tor"),
    ],
    "music": [
        PreferenceSpec("genres", "Genres", "multiselect", options=_MUSIC_GENRES),
        PreferenceSpec("artist", "Artist", "text", placeholder="e.g. Daft Punk"),
        PreferenceSpec("tags", "Tags / mood", "text", placeholder="e.g. tag:shoegaze, mood:chill"),
    ],
    "product": [
        PreferenceSpec("product", "Product", "text", required=True, placeholder="e.g. iPhone"),
        PreferenceSpec("model", "Model / version", "text", placeholder="e.g. iPhone 14-16"),
        PreferenceSpec("budget", "Budget", "text", placeholder="e.g. < 1600 SGD"),
        PreferenceSpec("use_case", "Use case", "text", placeholder="e.g. iOS testing, work, gaming"),
        PreferenceSpec("brand", "Brand", "text", placeholder="e.g. Apple"),
        PreferenceSpec("category", "Category", "text", placeholder="e.g. smartphone"),
    ],
}


def supported_domains() -> List[str]:
    return sorted(DOMAIN_PREFERENCE_SPECS)


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != "" and value.strip().lower() != "any"
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) > 0
    return True


def build_domain_form(domain: str, current: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Generate the form for ``domain``, pre-filled from ``current`` values and
    flagging which *required* fields are still missing."""
    current = current or {}
    specs = DOMAIN_PREFERENCE_SPECS.get(str(domain).lower(), [])
    fields: List[Dict[str, Any]] = []
    missing_required: List[str] = []
    for spec in specs:
        value = current.get(spec.key)
        condition = spec.required_when
        condition_payload = None
        condition_met = False
        if condition is not None and len(condition) == 2:
            condition_payload = {"key": condition[0], "equals": condition[1]}
            condition_met = current.get(condition[0]) == condition[1]
        elif condition is not None and len(condition) == 3:
            key, operator, expected = condition
            condition_payload = {"key": key, "operator": operator, "value": expected}
            try:
                if operator == "gt":
                    condition_met = float(current.get(key)) > float(expected)
                elif operator == "equals":
                    condition_met = current.get(key) == expected
            except (TypeError, ValueError):
                condition_met = False
        fields.append(
            {
                "key": spec.key,
                "label": spec.label,
                "type": spec.field_type,
                "options": list(spec.options),
                "required": spec.required,
                "required_when": condition_payload,
                "placeholder": spec.placeholder,
                "value": value,
                "min": spec.min_value,
                "max": spec.max_value,
            }
        )
        if (spec.required or condition_met) and not _has_value(value):
            missing_required.append(spec.key)
    return {
        "domain": str(domain).lower(),
        "fields": fields,
        "missing_required": missing_required,
        "complete": not missing_required,
    }
