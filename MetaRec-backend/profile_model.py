"""Three-layer user profile model + domain-scoped context fusion.

The profile has three layers:

1. **Generic core** — ``demographics`` (age/occupation/location/...) plus a small
   set of cross-domain hard ``constraints`` (language, content rating ceiling).
   Reusable for every domain.
2. **Taste persona** — a single natural-language summary of *soft* preferences
   across all domains. Domain-agnostic; injected into every recommendation.
3. **Per-domain slices** — sparse structured preferences that drive tool params
   (restaurant: budget/dietary/spice; movie: genres). Only the *dispatched*
   domain's slice is fused into a given request.

This module is intentionally pure (no DB / IO) so the fusion rules can be unit
tested. The repository maps these layers onto the existing JSONB columns
(``dining_habits`` continues to back the restaurant slice for backward
compatibility); see ``PostgresProfileRepository``.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

# Layer 1 — generic, reusable across every domain.
DEMOGRAPHIC_KEYS: List[str] = ["age_range", "gender", "occupation", "location", "nationality"]
CONSTRAINT_KEYS: List[str] = ["language", "content_rating_max"]

PROFILE_MEMORY_MAX_ENTRIES = 80
TASTE_PERSONA_MAX_WORDS = 300

_REQUEST_SCOPED_MEMORY_KEYS = {"domain", "query", "food_intent"}
_DOMAIN_MEMORY_KEYS: Dict[str, List[str]] = {
    "restaurant": [
        "restaurant_types",
        "flavor_profiles",
        "dining_purpose",
        "budget_range",
        "location",
        "typical_budget",
        "dietary_restrictions",
        "spice_tolerance",
    ],
    "movie": ["genres", "mood", "tags", "actors", "directors"],
    "music": ["genres", "mood", "tags", "artist"],
    "book": ["genres", "mood", "tags", "author", "publisher", "subject"],
    "product": ["product", "category", "brand", "model", "use_case", "budget", "budget_range"],
}

# Specific named entities are useful evidence, but too easy to overfit from one
# request. Promote them into the visible persona only after repeated evidence.
_REPEAT_BEFORE_PERSONA_KEYS = {
    ("movie", "actors"),
    ("movie", "directors"),
    ("music", "artist"),
    ("book", "author"),
    ("book", "publisher"),
    ("product", "product"),
    ("product", "brand"),
    ("product", "model"),
}

# The restaurant slice is physically stored in the legacy ``dining_habits``
# column; these are its structured (non-prose) fields.
RESTAURANT_SLICE_KEYS: List[str] = [
    "typical_budget",
    "dietary_restrictions",
    "spice_tolerance",
    # Legacy restaurant preference-panel fields. They now live in the
    # restaurant domain slice instead of a separate metadata.preferences system.
    "restaurant_types",
    "flavor_profiles",
    "dining_purpose",
    "budget_range",
    "location",
]


def _clean_str_map(raw: Any, keys: List[str]) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    cleaned: Dict[str, Any] = {}
    for key in keys:
        value = raw.get(key)
        if value not in (None, "", [], {}):
            cleaned[key] = value
    return cleaned


def assemble_domains(profile: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Build the unified per-domain slice map from physical storage.

    ``restaurant`` comes from the legacy ``dining_habits`` column; every other
    domain lives under ``metadata.domains``. Returns a fresh dict (no aliasing).
    """
    metadata = profile.get("metadata") if isinstance(profile.get("metadata"), dict) else {}
    domains: Dict[str, Dict[str, Any]] = {}
    stored = metadata.get("domains")
    if isinstance(stored, dict):
        for domain, slice_ in stored.items():
            if isinstance(slice_, dict) and slice_:
                domains[str(domain)] = dict(slice_)

    legacy_preferences = metadata.get("preferences")
    if isinstance(legacy_preferences, dict) and legacy_preferences:
        domains["restaurant"] = {
            **domains.get("restaurant", {}),
            **dict(legacy_preferences),
        }

    restaurant_slice = _clean_str_map(profile.get("dining_habits"), RESTAURANT_SLICE_KEYS)
    if restaurant_slice:
        domains["restaurant"] = {**domains.get("restaurant", {}), **restaurant_slice}
    return domains


def taste_persona_of(profile: Dict[str, Any]) -> str:
    """Layer 2. Falls back to the legacy ``dining_habits.description`` so existing
    profiles transparently seed a persona instead of losing that text."""
    metadata = profile.get("metadata") if isinstance(profile.get("metadata"), dict) else {}
    persona = profile.get("taste_persona") or metadata.get("taste_persona")
    if persona:
        return str(persona).strip()
    dining = profile.get("dining_habits") if isinstance(profile.get("dining_habits"), dict) else {}
    return str(dining.get("description") or "").strip()


def constraints_of(profile: Dict[str, Any]) -> Dict[str, Any]:
    metadata = profile.get("metadata") if isinstance(profile.get("metadata"), dict) else {}
    raw = profile.get("constraints")
    if not isinstance(raw, dict):
        raw = metadata.get("constraints")
    return _clean_str_map(raw, CONSTRAINT_KEYS)


def normalize_profile(profile: Dict[str, Any]) -> Dict[str, Any]:
    """Return a logical three-layer view, leaving physical fields intact so the
    repository/back-compat readers keep working."""
    base = dict(profile or {})
    base["demographics"] = _clean_str_map(base.get("demographics"), DEMOGRAPHIC_KEYS)
    base["constraints"] = constraints_of(base)
    base["taste_persona"] = taste_persona_of(base)
    base["domains"] = assemble_domains(base)
    return base


def _format_slice(slice_: Dict[str, Any]) -> str:
    parts: List[str] = []
    for key, value in slice_.items():
        if isinstance(value, (list, tuple, set)):
            rendered = ", ".join(str(item) for item in value if item not in (None, ""))
        else:
            rendered = str(value)
        if rendered:
            parts.append(f"{key}={rendered}")
    return "; ".join(parts)


def build_recommender_profile_block(profile: Dict[str, Any], domain: str) -> str:
    """Fuse the profile into a compact NL block for *one* dispatched domain.

    Always includes demographics, the taste persona, and cross-domain
    constraints. Includes **only** the given domain's structured slice — never
    another domain's — so a movie request is never biased by restaurant prefs.
    Returns ``""`` when there is nothing meaningful to inject.
    """
    if not isinstance(profile, dict) or not profile:
        return ""
    domain_key = str(domain or "").lower()
    demographics = _clean_str_map(profile.get("demographics"), DEMOGRAPHIC_KEYS)
    persona = taste_persona_of(profile)
    constraints = constraints_of(profile)
    domain_slice = assemble_domains(profile).get(domain_key, {})

    lines: List[str] = []
    if demographics:
        lines.append(f"Demographics: {_format_slice(demographics)}")
    if persona:
        lines.append(f"Taste: {persona}")
    if constraints:
        lines.append(f"Constraints: {_format_slice(constraints)}")
    if domain_slice:
        lines.append(f"{domain_key.title()} preferences: {_format_slice(domain_slice)}")

    if not lines:
        return ""
    return "[User profile]\n" + "\n".join(lines)


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_memory_text(value: Any) -> str:
    if value in (None, "", [], {}, "any", ["any"]):
        return ""
    if isinstance(value, dict):
        meaningful = {k: v for k, v in value.items() if v not in (None, "", [], {}, "any")}
        if not meaningful:
            return ""
        if {"min", "max", "currency"} & set(meaningful):
            currency = str(meaningful.get("currency") or "SGD")
            min_value = meaningful.get("min")
            max_value = meaningful.get("max")
            if min_value not in (None, "") and max_value not in (None, ""):
                return f"{min_value}-{max_value} {currency}"
            if max_value not in (None, ""):
                return f"up to {max_value} {currency}"
            if min_value not in (None, ""):
                return f"from {min_value} {currency}"
        return ", ".join(f"{k}={v}" for k, v in meaningful.items())
    if isinstance(value, (list, tuple, set)):
        parts = [_clean_memory_text(item) for item in value]
        return ", ".join(part for part in parts if part)
    return str(value).strip()


def _split_memory_values(value: Any) -> List[str]:
    if value in (None, "", [], {}, "any", ["any"]):
        return []
    if isinstance(value, (list, tuple, set)):
        values: List[str] = []
        for item in value:
            cleaned = _clean_memory_text(item)
            if cleaned:
                values.append(cleaned)
        return values
    cleaned = _clean_memory_text(value)
    return [cleaned] if cleaned else []


def _memory_identity(domain: str, key: str, value: str) -> str:
    return f"{domain}:{key}:{value.casefold()}"


def _entry_sort_key(entry: Dict[str, Any]) -> Tuple[str, str, str]:
    return (
        str(entry.get("domain") or ""),
        str(entry.get("key") or ""),
        str(entry.get("value") or "").casefold(),
    )


def _clamp_words(text: str, max_words: int = TASTE_PERSONA_MAX_WORDS) -> str:
    words = str(text or "").split()
    if len(words) <= max_words:
        return " ".join(words).strip()
    trimmed = " ".join(words[:max_words]).rstrip(" ,;:")
    return f"{trimmed}."


def profile_memory_entries_from_preferences(
    preferences: Optional[Dict[str, Any]],
    *,
    source: str = "confirmed_recommendation",
    evidence: Optional[str] = None,
    timestamp: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Extract bounded, provenance-backed profile memory signals.

    This intentionally uses only explicit, structured recommendation preferences
    rather than free-form chat text. The caller decides whether the request was
    confirmed enough to persist.
    """
    if not isinstance(preferences, dict) or not preferences:
        return []
    domain = str(preferences.get("domain") or "").strip().lower()
    if not domain:
        domain = "restaurant" if any(key in preferences for key in _DOMAIN_MEMORY_KEYS["restaurant"]) else ""
    if domain not in _DOMAIN_MEMORY_KEYS:
        return []
    now = timestamp or _utc_timestamp()
    entries: List[Dict[str, Any]] = []
    for key in _DOMAIN_MEMORY_KEYS[domain]:
        if key in _REQUEST_SCOPED_MEMORY_KEYS or key not in preferences:
            continue
        for value in _split_memory_values(preferences.get(key)):
            entries.append(
                {
                    "domain": domain,
                    "key": key,
                    "value": value,
                    "source": source,
                    "confidence": 0.85,
                    "count": 1,
                    "first_seen": now,
                    "last_seen": now,
                    "evidence": str(evidence or preferences.get("query") or "")[:240],
                }
            )
    return entries


def merge_profile_memory_entries(
    existing: Any,
    incoming: List[Dict[str, Any]],
    *,
    max_entries: int = PROFILE_MEMORY_MAX_ENTRIES,
) -> List[Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {}

    def ingest(entry: Dict[str, Any], *, is_incoming: bool) -> None:
        domain = str(entry.get("domain") or "").strip().lower()
        key = str(entry.get("key") or "").strip()
        value = _clean_memory_text(entry.get("value"))
        if domain not in _DOMAIN_MEMORY_KEYS or key not in _DOMAIN_MEMORY_KEYS[domain] or not value:
            return
        identity = _memory_identity(domain, key, value)
        current = merged.get(identity)
        if current is None:
            count = entry.get("count", 1)
            try:
                count_int = max(1, int(count))
            except (TypeError, ValueError):
                count_int = 1
            confidence = entry.get("confidence", 0.85)
            try:
                confidence_float = max(0.0, min(1.0, float(confidence)))
            except (TypeError, ValueError):
                confidence_float = 0.85
            merged[identity] = {
                "domain": domain,
                "key": key,
                "value": value,
                "source": str(entry.get("source") or "confirmed_recommendation"),
                "confidence": confidence_float,
                "count": count_int,
                "first_seen": str(entry.get("first_seen") or entry.get("last_seen") or _utc_timestamp()),
                "last_seen": str(entry.get("last_seen") or entry.get("first_seen") or _utc_timestamp()),
                "evidence": str(entry.get("evidence") or "")[:240],
            }
            return
        if is_incoming:
            current["count"] = int(current.get("count") or 1) + 1
        current["confidence"] = max(float(current.get("confidence") or 0.0), float(entry.get("confidence") or 0.85))
        if entry.get("last_seen"):
            current["last_seen"] = str(entry["last_seen"])
        if entry.get("evidence"):
            current["evidence"] = str(entry["evidence"])[:240]

    if isinstance(existing, list):
        for item in existing:
            if isinstance(item, dict):
                ingest(item, is_incoming=False)
    for item in incoming:
        if isinstance(item, dict):
            ingest(item, is_incoming=True)

    entries = sorted(merged.values(), key=lambda item: (str(item.get("last_seen") or ""), int(item.get("count") or 1)), reverse=True)
    entries = entries[:max_entries]
    return sorted(entries, key=_entry_sort_key)


def _promoted_memory_entries(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    promoted: List[Dict[str, Any]] = []
    for entry in entries:
        domain = str(entry.get("domain") or "")
        key = str(entry.get("key") or "")
        count = int(entry.get("count") or 1)
        confidence = float(entry.get("confidence") or 0.0)
        if confidence < 0.75:
            continue
        if (domain, key) in _REPEAT_BEFORE_PERSONA_KEYS and count < 2:
            continue
        promoted.append(entry)
    return promoted


def _values_for(entries: List[Dict[str, Any]], domain: str, key: str, limit: int = 4) -> List[str]:
    values: List[str] = []
    for entry in entries:
        if entry.get("domain") != domain or entry.get("key") != key:
            continue
        value = str(entry.get("value") or "").strip()
        if value and value not in values:
            values.append(value)
        if len(values) >= limit:
            break
    return values


def _join_values(values: List[str]) -> str:
    return ", ".join(values)


def summarize_profile_memory(entries: List[Dict[str, Any]], *, max_words: int = TASTE_PERSONA_MAX_WORDS) -> str:
    promoted = _promoted_memory_entries(entries)
    if not promoted:
        return ""

    fragments: List[str] = []
    movie_bits = []
    if genres := _values_for(promoted, "movie", "genres"):
        movie_bits.append(f"genres: {_join_values(genres)}")
    if mood := _values_for(promoted, "movie", "mood"):
        movie_bits.append(f"mood: {_join_values(mood)}")
    if directors := _values_for(promoted, "movie", "directors"):
        movie_bits.append(f"recurring directors: {_join_values(directors)}")
    if actors := _values_for(promoted, "movie", "actors"):
        movie_bits.append(f"recurring actors: {_join_values(actors)}")
    if movie_bits:
        fragments.append("Movies - " + "; ".join(movie_bits))

    music_bits = []
    if genres := _values_for(promoted, "music", "genres"):
        music_bits.append(f"genres: {_join_values(genres)}")
    if mood := _values_for(promoted, "music", "mood"):
        music_bits.append(f"mood: {_join_values(mood)}")
    if artists := _values_for(promoted, "music", "artist"):
        music_bits.append(f"recurring artists: {_join_values(artists)}")
    if music_bits:
        fragments.append("Music - " + "; ".join(music_bits))

    book_bits = []
    if genres := (_values_for(promoted, "book", "genres") or _values_for(promoted, "book", "subject")):
        book_bits.append(f"topics/genres: {_join_values(genres)}")
    if mood := _values_for(promoted, "book", "mood"):
        book_bits.append(f"mood: {_join_values(mood)}")
    if authors := _values_for(promoted, "book", "author"):
        book_bits.append(f"recurring authors: {_join_values(authors)}")
    if book_bits:
        fragments.append("Books - " + "; ".join(book_bits))

    product_bits = []
    if categories := _values_for(promoted, "product", "category"):
        product_bits.append(f"categories: {_join_values(categories)}")
    if use_cases := _values_for(promoted, "product", "use_case"):
        product_bits.append(f"use cases: {_join_values(use_cases)}")
    if budgets := (_values_for(promoted, "product", "budget") or _values_for(promoted, "product", "budget_range")):
        product_bits.append(f"budget: {_join_values(budgets)}")
    if brands := _values_for(promoted, "product", "brand"):
        product_bits.append(f"recurring brands: {_join_values(brands)}")
    if product_bits:
        fragments.append("Products - " + "; ".join(product_bits))

    restaurant_bits = []
    if types := _values_for(promoted, "restaurant", "restaurant_types"):
        restaurant_bits.append(f"styles: {_join_values(types)}")
    if flavors := _values_for(promoted, "restaurant", "flavor_profiles"):
        restaurant_bits.append(f"flavors: {_join_values(flavors)}")
    if dietary := _values_for(promoted, "restaurant", "dietary_restrictions"):
        restaurant_bits.append(f"dietary needs: {_join_values(dietary)}")
    if location := _values_for(promoted, "restaurant", "location"):
        restaurant_bits.append(f"areas: {_join_values(location)}")
    if restaurant_bits:
        fragments.append("Restaurants - " + "; ".join(restaurant_bits))

    return _clamp_words(". ".join(fragments), max_words=max_words)


def _remove_previous_auto_persona(current: str, previous_auto: str) -> Optional[str]:
    if not previous_auto:
        return current.strip()
    if previous_auto not in current:
        return None
    manual = current.replace(previous_auto, " ")
    return " ".join(manual.split()).strip(" ;.\n\t")


def apply_profile_memory_from_preferences(
    profile: Dict[str, Any],
    preferences: Optional[Dict[str, Any]],
    *,
    source: str = "confirmed_recommendation",
    evidence: Optional[str] = None,
    timestamp: Optional[str] = None,
    max_words: int = TASTE_PERSONA_MAX_WORDS,
) -> Dict[str, Any]:
    """Persist confirmed preference evidence and refresh the General persona.

    The visible free-text is bounded and deterministic. Existing user-authored
    text wins: if the user edited away the previous auto-generated fragment, this
    function keeps their text intact while still updating structured memory.
    """
    incoming = profile_memory_entries_from_preferences(
        preferences,
        source=source,
        evidence=evidence,
        timestamp=timestamp,
    )
    if not incoming:
        return deepcopy(profile or {})

    updated = deepcopy(profile or {})
    metadata = updated.setdefault("metadata", {})
    existing_memory = metadata.get("profile_memory")
    memory = merge_profile_memory_entries(existing_memory, incoming)
    auto_persona = summarize_profile_memory(memory, max_words=max_words)
    metadata["profile_memory"] = memory
    metadata["profile_memory_updated_at"] = timestamp or _utc_timestamp()

    if not auto_persona:
        return updated

    current_persona = taste_persona_of(updated)
    previous_auto = str(metadata.get("taste_persona_auto") or "").strip()
    manual_persona = _remove_previous_auto_persona(current_persona, previous_auto)
    metadata["taste_persona_auto"] = auto_persona
    if manual_persona is None:
        # The user changed the generated fragment. Keep the visible field stable
        # and let future explicit profile edits decide what belongs there.
        return updated

    combined = " ".join(part for part in (manual_persona, auto_persona) if part).strip()
    metadata["taste_persona"] = _clamp_words(combined, max_words=max_words)
    return updated
