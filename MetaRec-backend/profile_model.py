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

from typing import Any, Dict, List

# Layer 1 — generic, reusable across every domain.
DEMOGRAPHIC_KEYS: List[str] = ["age_range", "gender", "occupation", "location", "nationality"]
CONSTRAINT_KEYS: List[str] = ["language", "content_rating_max"]

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
