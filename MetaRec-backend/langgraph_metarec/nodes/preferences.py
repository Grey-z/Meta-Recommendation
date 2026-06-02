from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional


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


