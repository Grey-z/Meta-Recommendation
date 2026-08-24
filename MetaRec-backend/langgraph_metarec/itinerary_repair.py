"""Strict validation for the itinerary Agent's bounded repair directive."""
from __future__ import annotations

from typing import Any, Dict, Optional

from langgraph_metarec.itinerary_contracts import RepairDirective

_ALLOWED_KEYS = {"domain_queries", "required_roles", "excluded_types", "provider_hints"}
_HARD_KEYS = {
    "location", "date", "start_time", "end_time", "timezone", "budget",
    "budget_amount", "budget_currency", "anchors", "anchor_policy", "must_visit",
    "style", "pace",
}
_DOMAINS = {"attraction", "restaurant"}
_ROLES = {"experience", "food", "shopping"}
_EXCLUDED = {"lodging", "food", "shopping", "region", "unknown"}


def parse_repair_directive(payload: Any) -> Optional[RepairDirective]:
    if not isinstance(payload, dict) or set(payload) - _ALLOWED_KEYS:
        return None
    # Defense-in-depth only: the allowlist above already rejects every hard key.
    # Kept so a future _ALLOWED_KEYS edit cannot silently open them up.
    if set(payload) & _HARD_KEYS:
        return None
    raw_queries = payload.get("domain_queries")
    if not isinstance(raw_queries, dict):
        return None
    queries: Dict[str, str] = {}
    for domain, query in raw_queries.items():
        domain = str(domain).lower()
        query = str(query or "").strip()
        if domain not in _DOMAINS or not query or len(query) > 240:
            return None
        queries[domain] = query
    if not queries:
        return None
    roles = tuple(dict.fromkeys(str(value).lower() for value in payload.get("required_roles") or ()))
    excluded = tuple(dict.fromkeys(str(value).lower() for value in payload.get("excluded_types") or ()))
    if any(role not in _ROLES for role in roles) or any(value not in _EXCLUDED for value in excluded):
        return None
    raw_hints = payload.get("provider_hints") or {}
    if not isinstance(raw_hints, dict) or any(str(domain).lower() not in _DOMAINS for domain in raw_hints):
        return None
    hints: Dict[str, tuple[str, ...]] = {}
    for domain, values in raw_hints.items():
        if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
            return None
        hints[str(domain).lower()] = tuple(value.strip()[:80] for value in values[:6] if value.strip())
    return RepairDirective(queries, roles, excluded, hints)
