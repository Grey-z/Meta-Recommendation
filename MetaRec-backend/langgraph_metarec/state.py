from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


RUNTIME_SCHEMA_VERSION = "2026-05-21.v1"


class IntentResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    intent: Optional[str] = None
    confidence: Optional[float] = None
    reply: Optional[str] = None
    preferences: Optional[Dict[str, Any]] = None
    profile_updates: Optional[Dict[str, Any]] = None


class TaskStatusProjection(BaseModel):
    model_config = ConfigDict(extra="ignore")

    task_id: Optional[str] = None
    status: str = "idle"
    progress: int = 0
    message: str = ""
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class DomainGraphResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    domain: Optional[str] = None
    status: str = "idle"
    result: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ProgressEvent(BaseModel):
    model_config = ConfigDict(extra="ignore")

    stage: Optional[str] = None
    status: str = "processing"
    progress: int = 0
    message: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)


class RuntimeErrorRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    message: str
    code: Optional[str] = None
    node: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class GraphRuntimeState(BaseModel):
    model_config = ConfigDict(extra="ignore")

    schema_version: str = RUNTIME_SCHEMA_VERSION
    user_id: str = "default"
    conversation_id: Optional[str] = None
    branch_id: Optional[str] = None
    message_id: Optional[str] = None
    thread_id: Optional[str] = None
    task_id: Optional[str] = None
    task_thread_id: Optional[str] = None
    query: str = ""
    intent_result: Optional[IntentResult] = None
    collect_confirm_state: Optional[Dict[str, Any]] = None
    routing_route: Optional[Dict[str, Any]] = None
    task_status: Optional[TaskStatusProjection] = None
    domain_graph_result: Optional[DomainGraphResult] = None
    progress_events: List[ProgressEvent] = Field(default_factory=list)
    errors: List[RuntimeErrorRecord] = Field(default_factory=list)
    response_payload: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def to_checkpoint(self) -> Dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)

    @classmethod
    def from_checkpoint(cls, payload: Optional[Dict[str, Any]]) -> "GraphRuntimeState":
        if not payload:
            return cls()
        return cls.model_validate(payload)

    def runtime_metadata(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "thread_id": self.thread_id,
            "task_thread_id": self.task_thread_id,
            "branch_id": self.branch_id,
            "message_id": self.message_id,
            "routing": self.routing_route,
            "collect_confirm_status": (
                self.collect_confirm_state or {}
            ).get("status"),
            "errors": [error.model_dump(mode="json") for error in self.errors],
        }


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
