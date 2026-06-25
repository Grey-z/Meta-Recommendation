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

from langgraph_metarec.genres import MOVIE_GENRE_IDS

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

# Per-domain form definitions. Keep these minimal — only what actually drives a
# search/tool param or is a hard constraint worth asking for.
DOMAIN_PREFERENCE_SPECS: Dict[str, List[PreferenceSpec]] = {
    "restaurant": [
        PreferenceSpec("location", "Location", "text", required=True, placeholder="e.g. Chinatown"),
        PreferenceSpec("dietary_restrictions", "Dietary restrictions", "text", placeholder="e.g. vegetarian"),
        PreferenceSpec("typical_budget", "Budget per person", "text", placeholder="e.g. 20-60 SGD"),
    ],
    "movie": [
        PreferenceSpec("genres", "Genres", "multiselect", options=_MOVIE_GENRES, required=True),
        PreferenceSpec("exclude_genres", "Exclude genres", "multiselect", options=_MOVIE_GENRES),
    ],
    "book": [
        PreferenceSpec("genres", "Genres / themes", "text", required=True, placeholder="e.g. science fiction"),
    ],
    "music": [
        PreferenceSpec("tags", "Tags / mood", "text", placeholder="e.g. tag:rock, mood:chill"),
    ],
    "product": [
        PreferenceSpec("query", "What are you shopping for?", "text", required=True, placeholder="e.g. noise cancelling headphones"),
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
