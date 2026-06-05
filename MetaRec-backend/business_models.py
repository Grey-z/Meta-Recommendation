from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


SAFE_NODE_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


class UserRole(str, Enum):
    """Authorization role for a user. Stored lowercase to match the existing
    `kind`/`status` VARCHAR convention. Extend here (and the migration's CHECK
    constraint) when adding new roles."""

    ADMIN = "admin"
    USER = "user"


def new_uuid() -> str:
    return str(uuid.uuid4())


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_uuid(value: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except Exception as exc:
        raise ValueError("must be a UUID string") from exc


def ensure_node_id(value: str) -> str:
    if not SAFE_NODE_ID_RE.fullmatch(str(value)):
        raise ValueError("must contain only letters, numbers, '.', '_', ':', '-' and be <= 128 chars")
    return str(value)


def derive_result_id(task_id: str, branch_id: Optional[str]) -> str:
    """Deterministic, stable result_id for a (task, branch). Canonical definition
    reused by the recommendation result persistence (so re-emitting a completed
    projection updates the same row) and by the feedback pipeline (so a vote can
    be attached to the result without the client knowing the derived id)."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"metarec-result:{task_id}:{branch_id or ''}"))


class BusinessModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class UserRecord(BusinessModel):
    id: str
    kind: Literal["registered", "guest"] = "guest"
    role: UserRole = UserRole.USER
    email: Optional[str] = None
    display_name: Optional[str] = None
    status: str = "active"
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    last_seen_at: Optional[datetime] = None

    @field_validator("id")
    @classmethod
    def _id_is_uuid(cls, value: str) -> str:
        return ensure_uuid(value)

    @field_validator("email")
    @classmethod
    def _email_shape(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        normalized = value.strip().lower()
        if "@" not in normalized or len(normalized) > 320:
            raise ValueError("must be an email-like address")
        return normalized


class AnonymousDeviceRecord(BusinessModel):
    id: str
    user_id: str
    device_hash: str
    user_agent: Optional[str] = None
    session_count: int = 0
    first_seen_at: Optional[datetime] = None
    last_seen_at: Optional[datetime] = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("id", "user_id")
    @classmethod
    def _uuid_fields(cls, value: str) -> str:
        return ensure_uuid(value)


class UserSessionRecord(BusinessModel):
    id: str
    user_id: str
    anonymous_device_id: Optional[str] = None
    status: str = "active"
    expires_at: datetime
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    last_seen_at: Optional[datetime] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    user: Optional[UserRecord] = None

    @field_validator("id", "user_id", "anonymous_device_id")
    @classmethod
    def _uuid_fields(cls, value: Optional[str]) -> Optional[str]:
        return ensure_uuid(value) if value else value


class AuthSessionPayload(BusinessModel):
    token: str
    session: UserSessionRecord
    user: UserRecord


class UserProfileRecord(BusinessModel):
    user_id: str
    demographics: dict[str, Any] = Field(default_factory=dict)
    dining_habits: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    version: int = 1
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @field_validator("user_id")
    @classmethod
    def _user_id_is_uuid(cls, value: str) -> str:
        return ensure_uuid(value)


class ConversationBranchRecord(BusinessModel):
    id: str
    conversation_id: str
    parent_branch_id: Optional[str] = None
    fork_from_message_id: Optional[str] = None
    root_message_id: Optional[str] = None
    head_message_id: Optional[str] = None
    title: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("id", "parent_branch_id", "fork_from_message_id", "root_message_id", "head_message_id")
    @classmethod
    def _node_id_fields(cls, value: Optional[str]) -> Optional[str]:
        return ensure_node_id(value) if value else value

    @field_validator("conversation_id")
    @classmethod
    def _conversation_id_is_uuid(cls, value: str) -> str:
        return ensure_uuid(value)


class ConversationNodeRecord(BusinessModel):
    id: str
    conversation_id: str
    branch_id: str
    role: Literal["user", "assistant"]
    content: str
    parent_message_id: Optional[str] = None
    fork_from_message_id: Optional[str] = None
    revision_of_message_id: Optional[str] = None
    state: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    model: Optional[str] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    cost_usd: Optional[float] = None
    latency_ms: Optional[int] = None
    created_at: Optional[datetime] = None

    @field_validator("id", "branch_id", "parent_message_id", "fork_from_message_id", "revision_of_message_id")
    @classmethod
    def _node_id_fields(cls, value: Optional[str]) -> Optional[str]:
        return ensure_node_id(value) if value else value

    @field_validator("conversation_id")
    @classmethod
    def _conversation_id_is_uuid(cls, value: str) -> str:
        return ensure_uuid(value)


class ConversationRecord(BusinessModel):
    id: str
    user_id: str
    title: str = "New Chat"
    model: str = "Auto"
    last_message: str = ""
    active_branch_id: str = "branch-main"
    branch_selection_state: dict[str, str] = Field(default_factory=dict)
    preferences: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None
    branches: dict[str, ConversationBranchRecord] = Field(default_factory=dict)
    messages: list[ConversationNodeRecord] = Field(default_factory=list)

    @field_validator("id", "user_id")
    @classmethod
    def _uuid_fields(cls, value: str) -> str:
        return ensure_uuid(value)

    @field_validator("active_branch_id")
    @classmethod
    def _active_branch_id_is_safe(cls, value: str) -> str:
        return ensure_node_id(value)


class TaskProjectionRecord(BusinessModel):
    task_id: str
    user_id: str
    conversation_id: Optional[str] = None
    branch_id: Optional[str] = None
    status: str = "pending"
    progress: int = 0
    message: str = ""
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @field_validator("task_id", "user_id", "conversation_id")
    @classmethod
    def _uuid_fields(cls, value: Optional[str]) -> Optional[str]:
        return ensure_uuid(value) if value else value

    @field_validator("branch_id")
    @classmethod
    def _branch_id_is_safe(cls, value: Optional[str]) -> Optional[str]:
        return ensure_node_id(value) if value else value


class RecommendationResultRecord(BusinessModel):
    result_id: str
    user_id: str
    conversation_id: Optional[str] = None
    branch_id: Optional[str] = None
    message_id: Optional[str] = None
    task_id: Optional[str] = None
    domain: Optional[str] = None
    restaurants: list[dict[str, Any]] = Field(default_factory=list)
    thinking_steps: list[dict[str, Any]] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @field_validator("result_id", "user_id", "conversation_id", "task_id")
    @classmethod
    def _uuid_fields(cls, value: Optional[str]) -> Optional[str]:
        return ensure_uuid(value) if value else value

    @field_validator("branch_id", "message_id")
    @classmethod
    def _node_id_fields(cls, value: Optional[str]) -> Optional[str]:
        return ensure_node_id(value) if value else value


# Fixed, single-select reason taxonomy for a thumb-down on a recommendation result.
# The API gates submitted reasons against this set; the FE renders chips from the
# label map (single source of truth). Bump `FEEDBACK_REASON_SCHEMA` and keep old
# codes here when evolving the taxonomy so historical label distributions stay valid.
FEEDBACK_REASON_SCHEMA = "v1"
FeedbackReason = Literal["too_far", "not_related", "inaccurate", "lack_options", "others"]
FEEDBACK_REASON_CODES: tuple[str, ...] = (
    "too_far",
    "not_related",
    "inaccurate",
    "lack_options",
    "others",
)
FEEDBACK_REASON_LABELS: dict[str, str] = {
    "too_far": "Too far",
    "not_related": "Not related",
    "inaccurate": "Inaccurate info",
    "lack_options": "Not enough options",
    "others": "Others",
}
FeedbackSentiment = Literal["up", "down"]


class FeedbackRecord(BusinessModel):
    feedback_id: str
    user_id: str
    conversation_id: Optional[str] = None
    branch_id: Optional[str] = None
    message_id: Optional[str] = None
    result_id: Optional[str] = None
    label: Optional[str] = None
    rating: Optional[int] = None
    comment: Optional[str] = None
    payload: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @field_validator("feedback_id", "user_id", "conversation_id", "result_id")
    @classmethod
    def _uuid_fields(cls, value: Optional[str]) -> Optional[str]:
        return ensure_uuid(value) if value else value

    @field_validator("branch_id", "message_id")
    @classmethod
    def _node_id_fields(cls, value: Optional[str]) -> Optional[str]:
        return ensure_node_id(value) if value else value
