from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class GraphState:
    query: str
    user_id: str = "default"
    conversation_id: Optional[str] = None
    message_id: Optional[str] = None
    branch_id: Optional[str] = None
    timeline_cursor: Optional[str] = None
    conversation_history: Optional[List[Dict[str, Any]]] = None
    user_profile: Optional[Dict[str, Any]] = None
    current_preferences: Optional[Dict[str, Any]] = None
    preferences: Optional[Dict[str, Any]] = None
    pending_preferences: Optional[Dict[str, Any]] = None
    is_in_query_flow: bool = False
    intent: Optional[str] = None
    intent_confidence: Optional[float] = None
    reply: Optional[str] = None
    domain: str = "unknown"
    domain_confidence: float = 0.0
    domain_reason: Optional[str] = None
    needs_confirmation: bool = False
    response_payload: Optional[Dict[str, Any]] = None
    errors: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_metadata(self) -> Dict[str, Any]:
        return {
            "intent": self.intent,
            "intent_confidence": self.intent_confidence,
            "domain": self.domain,
            "domain_confidence": self.domain_confidence,
            "domain_reason": self.domain_reason,
            "branch_id": self.branch_id,
            "timeline_cursor": self.timeline_cursor,
            "errors": list(self.errors),
        }

