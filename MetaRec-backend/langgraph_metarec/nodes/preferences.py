from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional

# The historical "unspecified" budget sentinel. The LLM/extractor fill this in
# when the user does not state a budget, so it must NOT override a real stored
# preference during a merge. Kept consistent with
# llm_service.has_meaningful_preferences.
_DEFAULT_BUDGET = (20, 60)


def _is_meaningful_list(value: Any) -> bool:
    return isinstance(value, list) and any(item not in (None, "", "any") for item in value)


def _is_meaningful_scalar(value: Any) -> bool:
    return value not in (None, "", "any")


def _is_meaningful_budget(budget: Any) -> bool:
    if not isinstance(budget, dict):
        return False
    minimum, maximum = budget.get("min"), budget.get("max")
    if minimum is None and maximum is None:
        return False
    if (minimum, maximum) == _DEFAULT_BUDGET:
        return False
    return True


def merge_preferences(
    base: Optional[Dict[str, Any]],
    overlay: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Overlay ``overlay`` onto ``base``, keeping the base value wherever the
    overlay field is unspecified.

    "Unspecified" means an empty/``["any"]`` list, ``None``/``""``/``"any"``
    scalar, or the default ``(20, 60)`` / ``(None, None)`` budget — i.e. the
    values the LLM and the keyword extractor emit when the user said nothing.
    This lets a user's stored preferences (profile / session) survive a new
    request that only mentions, say, a restaurant type, instead of being reset
    to defaults.
    """
    result: Dict[str, Any] = dict(base or {})
    overlay = overlay or {}

    for key in ("restaurant_types", "flavor_profiles"):
        if _is_meaningful_list(overlay.get(key)):
            result[key] = overlay[key]
    for key in ("dining_purpose", "location"):
        if _is_meaningful_scalar(overlay.get(key)):
            result[key] = overlay[key]
    if _is_meaningful_budget(overlay.get("budget_range")):
        result["budget_range"] = overlay["budget_range"]

    return result


@dataclass
class CollectConfirmState:
    """Serializable HITL state for the collect/confirm preference boundary."""

    node: str = "collect_confirm_preferences"
    status: str = "inactive"
    intent: Optional[str] = None
    query: str = ""
    preferences: Optional[Dict[str, Any]] = None
    pending_preferences: Optional[Dict[str, Any]] = None
    current_preferences: Optional[Dict[str, Any]] = None
    needs_confirmation: bool = False
    confirmation_request: Optional[Dict[str, Any]] = None
    routing: Optional[Dict[str, Any]] = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "node": self.node,
            "status": self.status,
            "intent": self.intent,
            "query": self.query,
            "preferences": self.preferences,
            "pending_preferences": self.pending_preferences,
            "current_preferences": self.current_preferences,
            "needs_confirmation": self.needs_confirmation,
            "created_at": self.created_at,
        }
        if self.confirmation_request is not None:
            payload["confirmation_request"] = self.confirmation_request
        if self.routing is not None:
            payload["routing"] = self.routing
        return payload


def build_collect_confirm_state_payload(
    *,
    query: str,
    intent: Optional[str],
    preferences: Optional[Dict[str, Any]],
    pending_preferences: Optional[Dict[str, Any]] = None,
    current_preferences: Optional[Dict[str, Any]] = None,
    needs_confirmation: bool = False,
    confirmation_request: Optional[Dict[str, Any]] = None,
    routing: Optional[Dict[str, Any]] = None,
    status: Optional[str] = None,
) -> Dict[str, Any]:
    if status is None:
        if needs_confirmation:
            status = "awaiting_confirmation"
        elif intent in {"confirmation_yes", "confirmation_no"}:
            status = "resolved"
        else:
            status = "inactive"

    return CollectConfirmState(
        status=status,
        intent=intent,
        query=query,
        preferences=preferences,
        pending_preferences=pending_preferences,
        current_preferences=current_preferences,
        needs_confirmation=needs_confirmation,
        confirmation_request=confirmation_request,
        routing=routing,
    ).to_dict()


