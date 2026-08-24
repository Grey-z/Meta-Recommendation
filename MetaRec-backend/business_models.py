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


# Single-select reason taxonomy for a thumb-down on a recommendation result.
# `FEEDBACK_REASON_CODES` is the *union* of every code across domains — the POST
# endpoint validates submitted reasons against it and the dashboard aggregates on
# it, so it is append-only (keep old codes when evolving so historical label
# distributions stay valid; bump `FEEDBACK_REASON_SCHEMA`). Which subset of chips
# the FE *offers* is domain-aware (see `FEEDBACK_REASONS_BY_DOMAIN`) so users are
# not shown irrelevant reasons (e.g. "Too far" for a song). The label map is the
# single source of truth for chip text.
FEEDBACK_REASON_SCHEMA = "v2"
FeedbackReason = Literal[
    "too_far",
    "not_related",
    "inaccurate",
    "lack_options",
    "already_known",
    "others",
]
FEEDBACK_REASON_CODES: tuple[str, ...] = (
    "too_far",
    "not_related",
    "inaccurate",
    "lack_options",
    "already_known",
    "others",
)
FEEDBACK_REASON_LABELS: dict[str, str] = {
    "too_far": "Too far",
    "not_related": "Not related",
    "inaccurate": "Inaccurate info",
    "lack_options": "Not enough options",
    "already_known": "Already know these",
    "others": "Others",
}
FeedbackSentiment = Literal["up", "down"]

# Ordered reason chips offered per domain ("others" always last). The POST endpoint
# still accepts any code in `FEEDBACK_REASON_CODES` regardless of domain — this only
# tailors the FE prompt. `too_far` suits location-anchored domains (restaurant,
# hotel); `already_known` ("already seen/heard/read it") suits discovery domains.
_FEEDBACK_REASONS_DEFAULT: tuple[str, ...] = (
    "not_related",
    "inaccurate",
    "lack_options",
    "others",
)
_FEEDBACK_REASONS_ENTERTAINMENT: tuple[str, ...] = (
    "not_related",
    "inaccurate",
    "lack_options",
    "already_known",
    "others",
)
_FEEDBACK_REASONS_PLACE: tuple[str, ...] = (
    "too_far",
    "not_related",
    "inaccurate",
    "lack_options",
    "others",
)
FEEDBACK_REASONS_BY_DOMAIN: dict[str, tuple[str, ...]] = {
    "restaurant": _FEEDBACK_REASONS_PLACE,
    "hotel": _FEEDBACK_REASONS_PLACE,
    "attraction": _FEEDBACK_REASONS_PLACE,
    "movie": _FEEDBACK_REASONS_ENTERTAINMENT,
    "music": _FEEDBACK_REASONS_ENTERTAINMENT,
    "book": _FEEDBACK_REASONS_ENTERTAINMENT,
}


def feedback_reasons_for_domain(domain: Optional[str]) -> tuple[str, ...]:
    """Ordered reason codes to offer for ``domain``; a generic default for any
    domain without a bespoke set (and for a missing/unknown domain)."""
    key = (domain or "").strip().lower()
    return FEEDBACK_REASONS_BY_DOMAIN.get(key, _FEEDBACK_REASONS_DEFAULT)


# ---------------------------------------------------------------------------
# Item-level interactions (user × item), distinct from result-level feedback.
#
# `ITEM_INTERACTION_SCHEMA` names the wire shape returned by `to_interaction_v1`;
# bump it if a field is added/renamed so offline datasets stay comparable.
# The action vocabulary is append-only for the same reason as feedback reasons.
# ---------------------------------------------------------------------------
ITEM_INTERACTION_SCHEMA = "item-interaction.v1"
ItemInteractionAction = Literal["save", "hide", "positive", "negative", "consumed"]
ITEM_INTERACTION_ACTIONS: tuple[str, ...] = ("save", "hide", "positive", "negative", "consumed")
# Stateful toggles: at most one active row per (user, domain, item, action);
# saving un-hides and hiding un-saves. Everything else is an append-only event.
ITEM_INTERACTION_TOGGLE_ACTIONS: frozenset[str] = frozenset({"save", "hide"})
ITEM_INTERACTION_MAX_ITEM_ID = 512
ITEM_INTERACTION_DOMAINS: tuple[str, ...] = (
    "restaurant", "hotel", "attraction", "movie", "music", "book", "product",
)

# Per-domain wording for the `consumed` action; the FE offers exactly these
# three chips, in this order. `positive`/`negative` are accepted by the API but
# deliberately have no chip yet (reserved for a future item-level thumb).
_CONSUMED_LABEL_BY_DOMAIN: dict[str, str] = {
    "music": "Played",
    "movie": "Watched",
    "book": "Read",
    "product": "Purchased",
    "restaurant": "Visited",
    "hotel": "Stayed",
    "attraction": "Visited",
}


def item_interaction_options_for_domain(domain: Optional[str]) -> list[dict[str, str]]:
    """Ordered `{code, label}` chips the FE should offer for ``domain``."""
    key = (domain or "").strip().lower()
    consumed = _CONSUMED_LABEL_BY_DOMAIN.get(key, "Used")
    return [
        {"code": "save", "label": "Save"},
        {"code": "hide", "label": "Not interested"},
        {"code": "consumed", "label": consumed},
    ]


class ItemInteractionRecord(BusinessModel):
    event_id: str
    user_id: str
    domain: str
    item_id: str
    action: ItemInteractionAction
    result_id: Optional[str] = None
    task_id: Optional[str] = None
    conversation_id: Optional[str] = None
    payload: dict[str, Any] = Field(default_factory=dict)
    occurred_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None
    created_at: Optional[datetime] = None

    @field_validator("event_id", "user_id", "result_id", "conversation_id")
    @classmethod
    def _uuid_fields(cls, value: Optional[str]) -> Optional[str]:
        return ensure_uuid(value) if value else value

    @field_validator("domain")
    @classmethod
    def _domain(cls, value: str) -> str:
        key = (value or "").strip().lower()
        if key not in ITEM_INTERACTION_DOMAINS:
            raise ValueError(f"domain must be one of {', '.join(ITEM_INTERACTION_DOMAINS)}")
        return key

    @field_validator("item_id")
    @classmethod
    def _item_id(cls, value: str) -> str:
        text = (value or "").strip()
        if not text:
            raise ValueError("item_id is required")
        if len(text) > ITEM_INTERACTION_MAX_ITEM_ID:
            raise ValueError(f"item_id must be <= {ITEM_INTERACTION_MAX_ITEM_ID} characters")
        return text

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None


def to_interaction_v1(record: ItemInteractionRecord) -> dict[str, Any]:
    """Project a record to the `ItemInteractionV1` wire shape consumed by the
    domain rankers and the offline evaluators. Deliberately minimal and stable:
    add fields here only together with a schema bump."""
    return {
        "schema_version": ITEM_INTERACTION_SCHEMA,
        "event_id": record.event_id,
        "domain": record.domain,
        "item_id": record.item_id,
        "action": record.action,
        "result_id": record.result_id,
        "occurred_at": record.occurred_at.isoformat() if record.occurred_at else None,
    }


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
