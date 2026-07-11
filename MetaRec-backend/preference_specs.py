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
from typing import Any, Dict, List, Optional

from langgraph_metarec.genres import MOVIE_GENRE_IDS, MUSIC_GENRES

# Supported field renderings; the frontend PreferenceForm maps these to widgets.
FIELD_TYPES = {"select", "multiselect", "text", "range"}


@dataclass(frozen=True)
class PreferenceSpec:
    key: str
    label: str
    field_type: str
    options: List[str] = field(default_factory=list)
    required: bool = False
    placeholder: str = ""

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
        PreferenceSpec("budget", "Budget for the day", "text", placeholder="e.g. < 150 SGD"),
        PreferenceSpec("date", "Travel date", "text", placeholder="YYYY-MM-DD"),
        PreferenceSpec("start_time", "Start time", "text", placeholder="e.g. 10:00"),
        PreferenceSpec("timezone", "Timezone", "text", placeholder="e.g. Asia/Singapore"),
        PreferenceSpec("hotel_anchor", "Starting hotel", "text", placeholder="Hotel name or address"),
    ],
    "attraction": [
        PreferenceSpec("location", "Destination / area", "text", required=True, placeholder="e.g. Sentosa"),
        PreferenceSpec(
            "attraction_types",
            "Attraction types",
            "multiselect",
            options=[
                "museum", "gallery", "theme-park", "zoo-aquarium", "landmark", "viewpoint",
                "park-nature", "historic-site", "beach",
            ],
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
        fields.append(
            {
                "key": spec.key,
                "label": spec.label,
                "type": spec.field_type,
                "options": list(spec.options),
                "required": spec.required,
                "placeholder": spec.placeholder,
                "value": value,
            }
        )
        if spec.required and not _has_value(value):
            missing_required.append(spec.key)
    return {
        "domain": str(domain).lower(),
        "fields": fields,
        "missing_required": missing_required,
        "complete": not missing_required,
    }
