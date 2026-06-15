from __future__ import annotations

import hashlib
import secrets
import uuid
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from passlib.context import CryptContext
from sqlalchemy import func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from business_db import session_scope
from business_models import (
    AuthSessionPayload,
    FEEDBACK_REASON_SCHEMA,
    FeedbackRecord,
    RecommendationResultRecord,
    TaskProjectionRecord,
    UserRecord,
    UserRole,
    UserSessionRecord,
    derive_result_id,
    ensure_node_id,
    ensure_uuid,
    new_uuid,
)
from business_orm import (
    AnonymousDeviceORM,
    ConversationBranchORM,
    ConversationNodeORM,
    ConversationORM,
    FeedbackORM,
    RecommendationResultORM,
    RecommendationTaskORM,
    UserORM,
    UserProfileORM,
    UserSessionORM,
    utc_now,
)
from conversation_storage import ConversationStorage


pwd_context = CryptContext(schemes=["pbkdf2_sha256", "bcrypt"], deprecated="auto")


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _device_hash(device_id: str) -> str:
    return hashlib.sha256(device_id.encode("utf-8")).hexdigest()


def _truncate(value: Optional[str], length: int) -> Optional[str]:
    if value is None:
        return None
    return value[:length]


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "dict"):
        return value.dict()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


def _user_record(row: UserORM) -> UserRecord:
    return UserRecord(
        id=row.id,
        kind=row.kind,
        role=row.role or UserRole.USER.value,
        email=row.email,
        display_name=row.display_name,
        status=row.status,
        metadata=row.metadata_json or {},
        created_at=row.created_at,
        updated_at=row.updated_at,
        last_seen_at=row.last_seen_at,
    )


class AdminRepositoryError(Exception):
    """Base class for admin user-management errors."""


class UserNotFoundError(AdminRepositoryError):
    """The target user does not exist."""


class ConcurrencyConflictError(AdminRepositoryError):
    """The user was modified since the caller last read it (stale edit)."""


class LastAdminError(AdminRepositoryError):
    """The change would remove the last active admin (lock-out guard)."""


# Positive / negative feedback labels for the dashboard satisfaction stats. Kept
# lowercase; compared via lower(label). Feedback ingestion is not wired yet, so
# these are placeholders that degrade to zeros on an empty table.
_POSITIVE_FEEDBACK_LABELS = {"helpful", "accurate", "satisfied", "thumbs_up", "like", "good", "positive"}
_NEGATIVE_FEEDBACK_LABELS = {"not_helpful", "inaccurate", "unsatisfied", "thumbs_down", "dislike", "bad", "negative"}

# Fixed key for a Postgres transaction-level advisory lock that serializes
# admin role/status mutations across processes, so the last-admin check and the
# write cannot interleave (defense-in-depth on top of the per-row FOR UPDATE).
_ADMIN_MUTATION_LOCK_KEY = 728192


def _user_admin_dict(row: UserORM) -> dict[str, Any]:
    """Admin-facing, JSON-serializable view of a user row."""
    return {
        "id": row.id,
        "kind": row.kind,
        "role": row.role or UserRole.USER.value,
        "email": row.email,
        "display_name": row.display_name,
        "status": row.status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "last_seen_at": row.last_seen_at.isoformat() if row.last_seen_at else None,
    }


def _parse_iso_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _updated_at_matches(current: Optional[datetime], expected: Any) -> bool:
    """Optimistic-concurrency token comparison. Both sides are normalized to
    UTC-aware datetimes so a round-tripped ISO string compares equal."""
    expected_dt = _parse_iso_datetime(expected)
    if expected_dt is None or current is None:
        return False
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    if expected_dt.tzinfo is None:
        expected_dt = expected_dt.replace(tzinfo=timezone.utc)
    return current == expected_dt


def _session_record(row: UserSessionORM, user: Optional[UserORM] = None) -> UserSessionRecord:
    return UserSessionRecord(
        id=row.id,
        user_id=row.user_id,
        anonymous_device_id=row.anonymous_device_id,
        status=row.status,
        expires_at=row.expires_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
        last_seen_at=row.last_seen_at,
        metadata=row.metadata_json or {},
        user=_user_record(user) if user is not None else None,
    )


class PostgresAuthRepository:
    cookie_name = "metarec_session"

    async def get_or_create_guest(
        self,
        *,
        device_id: str,
        user_agent: Optional[str] = None,
        ttl_days: int = 30,
    ) -> AuthSessionPayload:
        if not device_id or len(device_id) > 256:
            raise ValueError("device_id is required and must be <= 256 characters")
        hashed = _device_hash(device_id)
        for attempt in range(2):
            try:
                return await self._get_or_create_guest_once(
                    hashed_device_id=hashed,
                    user_agent=user_agent,
                    ttl_days=ttl_days,
                )
            except IntegrityError:
                if attempt == 0:
                    continue
                raise
        raise RuntimeError("failed to create guest session")

    async def _get_or_create_guest_once(
        self,
        *,
        hashed_device_id: str,
        user_agent: Optional[str],
        ttl_days: int,
    ) -> AuthSessionPayload:
        now = utc_now()
        async with session_scope() as session:
            device = await session.scalar(
                select(AnonymousDeviceORM).where(AnonymousDeviceORM.device_hash == hashed_device_id)
            )
            if device is None:
                user = UserORM(
                    id=new_uuid(),
                    kind="guest",
                    status="active",
                    last_seen_at=now,
                    metadata_json={"source": "guest_login"},
                    created_at=now,
                    updated_at=now,
                )
                session.add(user)
                await session.flush()
                device = AnonymousDeviceORM(
                    id=new_uuid(),
                    user_id=user.id,
                    device_hash=hashed_device_id,
                    user_agent=_truncate(user_agent, 512),
                    session_count=1,
                    first_seen_at=now,
                    last_seen_at=now,
                )
                session.add(device)
            else:
                user = await session.get(UserORM, device.user_id)
                if user is None:
                    raise RuntimeError("anonymous device is orphaned")
                device.session_count = (device.session_count or 0) + 1
                device.last_seen_at = now
                if user_agent:
                    device.user_agent = _truncate(user_agent, 512)
                user.last_seen_at = now
                user.updated_at = now

            token = secrets.token_urlsafe(32)
            session_row = UserSessionORM(
                id=new_uuid(),
                user_id=device.user_id,
                anonymous_device_id=device.id,
                token_hash=_token_hash(token),
                status="active",
                expires_at=now + timedelta(days=ttl_days),
                created_at=now,
                updated_at=now,
                last_seen_at=now,
            )
            session.add(session_row)
            await session.flush()
            user = await session.get(UserORM, device.user_id)
            return AuthSessionPayload(token=token, session=_session_record(session_row, user), user=_user_record(user))

    async def register(
        self,
        *,
        email: str,
        password: str,
        display_name: Optional[str] = None,
        existing_guest_user_id: Optional[str] = None,
        ttl_days: int = 30,
    ) -> AuthSessionPayload:
        normalized_email = email.strip().lower()
        if "@" not in normalized_email or len(normalized_email) > 320:
            raise ValueError("valid email is required")
        if len(password) < 8:
            raise ValueError("password must be at least 8 characters")
        now = utc_now()
        async with session_scope() as session:
            user = None
            if existing_guest_user_id:
                existing = await session.get(UserORM, ensure_uuid(existing_guest_user_id))
                if existing is not None and existing.kind == "guest" and not existing.email:
                    user = existing
                    user.kind = "registered"
                    user.email = normalized_email
                    user.password_hash = pwd_context.hash(password)
                    user.display_name = display_name
                    user.status = "active"
                    user.last_seen_at = now
                    user.updated_at = now
            if user is None:
                user = UserORM(
                    id=new_uuid(),
                    kind="registered",
                    email=normalized_email,
                    password_hash=pwd_context.hash(password),
                    display_name=display_name,
                    status="active",
                    last_seen_at=now,
                    created_at=now,
                    updated_at=now,
                )
                session.add(user)
            try:
                await session.flush()
            except IntegrityError as exc:
                raise ValueError("email is already registered") from exc
            token = secrets.token_urlsafe(32)
            session_row = UserSessionORM(
                id=new_uuid(),
                user_id=user.id,
                token_hash=_token_hash(token),
                status="active",
                expires_at=now + timedelta(days=ttl_days),
                created_at=now,
                updated_at=now,
                last_seen_at=now,
            )
            session.add(session_row)
            await session.flush()
            return AuthSessionPayload(token=token, session=_session_record(session_row, user), user=_user_record(user))

    async def login(self, *, email: str, password: str, ttl_days: int = 30) -> AuthSessionPayload:
        normalized_email = email.strip().lower()
        now = utc_now()
        async with session_scope() as session:
            user = await session.scalar(select(UserORM).where(UserORM.email == normalized_email))
            if user is None or not user.password_hash or not pwd_context.verify(password, user.password_hash):
                raise ValueError("invalid email or password")
            if user.status != "active":
                raise ValueError("user is not active")
            user.last_seen_at = now
            user.updated_at = now
            token = secrets.token_urlsafe(32)
            session_row = UserSessionORM(
                id=new_uuid(),
                user_id=user.id,
                token_hash=_token_hash(token),
                status="active",
                expires_at=now + timedelta(days=ttl_days),
                created_at=now,
                updated_at=now,
                last_seen_at=now,
            )
            session.add(session_row)
            await session.flush()
            return AuthSessionPayload(token=token, session=_session_record(session_row, user), user=_user_record(user))

    async def session_from_token(self, token: Optional[str]) -> Optional[AuthSessionPayload]:
        if not token:
            return None
        now = utc_now()
        async with session_scope() as session:
            row = await session.scalar(select(UserSessionORM).where(UserSessionORM.token_hash == _token_hash(token)))
            if row is None or row.status != "active" or row.revoked_at is not None or row.expires_at <= now:
                return None
            user = await session.get(UserORM, row.user_id)
            if user is None or user.status != "active":
                return None
            row.last_seen_at = now
            row.updated_at = now
            user.last_seen_at = now
            user.updated_at = now
            return AuthSessionPayload(token=token, session=_session_record(row, user), user=_user_record(user))

    async def revoke_token(self, token: Optional[str]) -> bool:
        if not token:
            return False
        now = utc_now()
        async with session_scope() as session:
            row = await session.scalar(select(UserSessionORM).where(UserSessionORM.token_hash == _token_hash(token)))
            if row is None:
                return False
            row.status = "revoked"
            row.revoked_at = now
            row.updated_at = now
            return True

    async def set_role_by_email(self, email: str, role: UserRole) -> bool:
        """Set a registered user's role by email. Returns False if no matching
        registered user exists. Idempotent."""
        normalized_email = email.strip().lower()
        if not normalized_email:
            return False
        async with session_scope() as session:
            user = await session.scalar(select(UserORM).where(UserORM.email == normalized_email))
            if user is None:
                return False
            user.role = role.value
            user.updated_at = utc_now()
            return True

    async def promote_admins(self, emails: list[str]) -> int:
        """Promote each given email to ADMIN. Returns the count promoted.
        Used by the startup allowlist (METAREC_ADMIN_EMAILS) and seed_admin.py."""
        promoted = 0
        for email in emails:
            if await self.set_role_by_email(email, UserRole.ADMIN):
                promoted += 1
        return promoted


class PostgresProfileRepository:
    COMPUTED_METADATA_KEYS = {"created_at", "updated_at", "version"}

    def default_profile(self, user_id: str) -> dict[str, Any]:
        return {
            "user_id": user_id,
            "demographics": {
                "age_range": "",
                "gender": "",
                "occupation": "",
                "location": "",
                "nationality": "",
            },
            "dining_habits": {
                "typical_budget": "",
                "dietary_restrictions": "",
                "spice_tolerance": "",
                "description": "",
            },
            "metadata": {
                "created_at": utc_now().isoformat(),
                "updated_at": utc_now().isoformat(),
            },
        }

    @staticmethod
    def _merge_profile_section(existing: dict[str, Any], incoming: Optional[dict[str, Any]]) -> dict[str, Any]:
        merged = dict(existing or {})
        if not isinstance(incoming, dict):
            return merged
        for key, value in incoming.items():
            if value is None:
                continue
            if isinstance(value, str) and value == "" and merged.get(key):
                continue
            merged[key] = value
        return merged

    def _clean_metadata(self, metadata: Optional[dict[str, Any]]) -> dict[str, Any]:
        if not isinstance(metadata, dict):
            return {}
        return {
            key: value
            for key, value in metadata.items()
            if key not in self.COMPUTED_METADATA_KEYS
        }

    async def get_user_profile(self, user_id: str) -> dict[str, Any]:
        ensure_uuid(user_id)
        async with session_scope() as session:
            row = await session.get(UserProfileORM, user_id)
            if row is None:
                return self.default_profile(user_id)
            return {
                "user_id": row.user_id,
                "demographics": row.demographics or {},
                "dining_habits": row.dining_habits or {},
                "metadata": {
                    **(row.metadata_json or {}),
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                    "updated_at": row.updated_at.isoformat() if row.updated_at else None,
                    "version": row.version,
                },
            }

    async def save_user_profile(self, user_id: str, profile: dict[str, Any]) -> bool:
        ensure_uuid(user_id)
        now = utc_now()
        async with session_scope() as session:
            row = await session.get(UserProfileORM, user_id)
            base = self.default_profile(user_id)
            if row is None:
                demographics = self._merge_profile_section(base["demographics"], profile.get("demographics"))
                dining_habits = self._merge_profile_section(base["dining_habits"], profile.get("dining_habits"))
                metadata = {
                    **self._clean_metadata(base.get("metadata")),
                    **self._clean_metadata(profile.get("metadata")),
                }
                row = UserProfileORM(
                    user_id=user_id,
                    demographics=demographics,
                    dining_habits=dining_habits,
                    metadata_json=metadata,
                    created_at=now,
                    updated_at=now,
                )
                session.add(row)
            else:
                row.demographics = self._merge_profile_section(row.demographics or base["demographics"], profile.get("demographics"))
                row.dining_habits = self._merge_profile_section(row.dining_habits or base["dining_habits"], profile.get("dining_habits"))
                row.metadata_json = {
                    **self._clean_metadata(row.metadata_json),
                    **self._clean_metadata(profile.get("metadata")),
                }
                row.version = (row.version or 1) + 1
                row.updated_at = now
            return True


class PostgresConversationRepository:
    MAIN_BRANCH_ID = ConversationStorage.MAIN_BRANCH_ID

    def __init__(self):
        self._tree = ConversationStorage(storage_dir="conversations")
        self._locks: dict[str, asyncio.Lock] = {}

    def _conversation_lock(self, conversation_id: str) -> asyncio.Lock:
        return self._locks.setdefault(conversation_id, asyncio.Lock())

    async def _load_conversation(self, user_id: str, conversation_id: str) -> Optional[dict[str, Any]]:
        ensure_uuid(user_id)
        ensure_uuid(conversation_id)
        async with session_scope() as session:
            conv = await session.get(ConversationORM, conversation_id)
            if conv is None or conv.user_id != user_id or conv.deleted_at is not None:
                return None
            branches = (
                await session.scalars(
                    select(ConversationBranchORM)
                    .where(ConversationBranchORM.conversation_id == conversation_id)
                    .order_by(ConversationBranchORM.created_at)
                )
            ).all()
            nodes = (
                await session.scalars(
                    select(ConversationNodeORM)
                    .where(ConversationNodeORM.conversation_id == conversation_id)
                    .order_by(ConversationNodeORM.created_at)
                )
            ).all()
            payload = {
                "id": conv.id,
                "user_id": conv.user_id,
                "title": conv.title,
                "model": conv.model,
                "last_message": conv.last_message,
                "timestamp": conv.created_at.isoformat(),
                "updated_at": conv.updated_at.isoformat(),
                "active_branch_id": conv.active_branch_id,
                "branch_selection_state": conv.branch_selection_state or {},
                "branches": {
                    item.id: {
                        "id": item.id,
                        "parent_branch_id": item.parent_branch_id,
                        "fork_from_message_id": item.fork_from_message_id,
                        "root_message_id": item.root_message_id,
                        "head_message_id": item.head_message_id,
                        "title": item.title,
                        "created_at": item.created_at.isoformat(),
                        "updated_at": item.updated_at.isoformat(),
                    }
                    for item in branches
                },
                "messages": [
                    {
                        "id": item.id,
                        "role": item.role,
                        "content": item.content,
                        "timestamp": item.created_at.isoformat(),
                        "branch_id": item.branch_id,
                        "parent_message_id": item.parent_message_id,
                        "fork_from_message_id": item.fork_from_message_id,
                        "revision_of_message_id": item.revision_of_message_id,
                        "metadata": item.metadata_json or {},
                    }
                    for item in nodes
                ],
                "preferences": conv.preferences or {},
                "metadata": conv.metadata_json or {},
            }
            return self._tree._ensure_tree_metadata(payload)

    @staticmethod
    def _apply_conversation_scalars(conv: ConversationORM, conversation: dict[str, Any]) -> None:
        """Write the conversation row's scalar fields from the in-memory dict."""
        conv.title = conversation.get("title") or "New Chat"
        conv.model = conversation.get("model") or "Auto"
        conv.last_message = conversation.get("last_message") or ""
        conv.active_branch_id = conversation.get("active_branch_id") or PostgresConversationRepository.MAIN_BRANCH_ID
        conv.branch_selection_state = conversation.get("branch_selection_state") or {}
        conv.preferences = conversation.get("preferences") or {}
        conv.metadata_json = conversation.get("metadata") or {}
        conv.updated_at = utc_now()

    @staticmethod
    def _node_row_from_message(conversation_id: str, message: dict[str, Any]) -> ConversationNodeORM:
        """Build a node row from an in-memory message dict (same field mapping the
        previous full-rewrite used)."""
        metadata = message.get("metadata") or {}
        stats = metadata.get("stats") if isinstance(metadata.get("stats"), dict) else {}
        node_id = ensure_node_id(message.get("id") or metadata.get("message_id"))
        return ConversationNodeORM(
            id=node_id,
            conversation_id=conversation_id,
            branch_id=ensure_node_id(
                message.get("branch_id") or metadata.get("branch_id") or PostgresConversationRepository.MAIN_BRANCH_ID
            ),
            role=message.get("role"),
            content=message.get("content") or "",
            parent_message_id=message.get("parent_message_id") or metadata.get("parent_message_id"),
            fork_from_message_id=message.get("fork_from_message_id") or metadata.get("fork_from_message_id"),
            revision_of_message_id=message.get("revision_of_message_id") or metadata.get("revision_of_message_id"),
            state=metadata.get("hitl_state") if isinstance(metadata.get("hitl_state"), dict) else {},
            metadata_json=metadata,
            model=metadata.get("model"),
            prompt_tokens=stats.get("prompt_tokens"),
            completion_tokens=stats.get("completion_tokens"),
            total_tokens=stats.get("total_tokens"),
            cost_usd=stats.get("cost_usd"),
            latency_ms=stats.get("latency_ms"),
            created_at=datetime.fromisoformat(message["timestamp"]) if message.get("timestamp") else utc_now(),
        )

    async def _upsert_branch_row(
        self,
        session,
        conversation_id: str,
        branch: dict[str, Any],
        valid_node_ids: Optional[set[str]] = None,
    ) -> None:
        """Insert or update one branch row. head/root pointers are only set when the
        referenced node exists (composite FKs fk_branches_head/root_message), matching
        the guard the previous full-rewrite applied; a dangling pointer is left NULL."""
        branch_id = ensure_node_id(branch.get("id"))
        root_message_id = branch.get("root_message_id")
        head_message_id = branch.get("head_message_id")
        if valid_node_ids is not None:
            root_message_id = root_message_id if root_message_id in valid_node_ids else None
            head_message_id = head_message_id if head_message_id in valid_node_ids else None
        row = await session.get(ConversationBranchORM, (branch_id, conversation_id))
        if row is None:
            row = ConversationBranchORM(
                id=branch_id,
                conversation_id=conversation_id,
                created_at=datetime.fromisoformat(branch["created_at"]) if branch.get("created_at") else utc_now(),
            )
            session.add(row)
        row.parent_branch_id = branch.get("parent_branch_id")
        row.fork_from_message_id = branch.get("fork_from_message_id")
        row.root_message_id = root_message_id
        row.head_message_id = head_message_id
        row.title = branch.get("title")
        row.updated_at = datetime.fromisoformat(branch["updated_at"]) if branch.get("updated_at") else utc_now()
        row.metadata_json = branch.get("metadata") or {}

    @staticmethod
    def _in_memory_node_ids(conversation: dict[str, Any]) -> set[str]:
        return {
            ensure_node_id(message.get("id") or (message.get("metadata") or {}).get("message_id"))
            for message in conversation.get("messages") or []
        }

    async def _insert_conversation(self, user_id: str, conversation: dict[str, Any]) -> bool:
        """Persist a brand-new conversation (row + initial branch, no nodes yet)."""
        conversation_id = ensure_uuid(conversation.get("id"))
        now = utc_now()
        created_at = conversation.get("timestamp") or conversation.get("created_at")
        async with session_scope() as session:
            conv = ConversationORM(
                id=conversation_id,
                user_id=ensure_uuid(user_id),
                created_at=datetime.fromisoformat(created_at) if created_at else now,
            )
            session.add(conv)
            self._apply_conversation_scalars(conv, conversation)
            await session.flush()
            for branch in (conversation.get("branches") or {}).values():
                await self._upsert_branch_row(session, conversation_id, branch, valid_node_ids=set())
            return True

    async def _persist_conversation_scalars(self, user_id: str, conversation: dict[str, Any]) -> bool:
        """Targeted UPDATE of only the conversation row's scalar fields. For mutations
        that touch neither nodes nor branch pointers (preferences, title/model, active
        branch, rolling summary) — no delete+reinsert of the tree."""
        conversation_id = ensure_uuid(conversation.get("id"))
        async with session_scope() as session:
            conv = await session.get(ConversationORM, conversation_id)
            if conv is None or conv.user_id != user_id or conv.deleted_at is not None:
                return False
            self._apply_conversation_scalars(conv, conversation)
            return True

    async def _persist_added_message(
        self,
        user_id: str,
        conversation: dict[str, Any],
        message: dict[str, Any],
        branch: dict[str, Any],
    ) -> bool:
        """Targeted append: INSERT the one new node, upsert its branch (head/root),
        and UPDATE the conversation scalars — no rewrite of the existing tree."""
        conversation_id = ensure_uuid(conversation.get("id"))
        async with session_scope() as session:
            conv = await session.get(ConversationORM, conversation_id)
            if conv is None or conv.user_id != user_id or conv.deleted_at is not None:
                return False
            node_id = ensure_node_id(message.get("id") or (message.get("metadata") or {}).get("message_id"))
            if await session.get(ConversationNodeORM, (node_id, conversation_id)) is None:
                session.add(self._node_row_from_message(conversation_id, message))
                # Node must exist before the branch head/root FK references it.
                await session.flush()
            await self._upsert_branch_row(
                session, conversation_id, branch, valid_node_ids=self._in_memory_node_ids(conversation)
            )
            self._apply_conversation_scalars(conv, conversation)
            return True

    async def _persist_superseded_nodes(
        self,
        user_id: str,
        conversation: dict[str, Any],
        changed_messages: list[dict[str, Any]],
    ) -> bool:
        """Targeted UPDATE of the superseded nodes' metadata + conversation scalars."""
        conversation_id = ensure_uuid(conversation.get("id"))
        async with session_scope() as session:
            conv = await session.get(ConversationORM, conversation_id)
            if conv is None or conv.user_id != user_id or conv.deleted_at is not None:
                return False
            for message in changed_messages:
                node_id = ensure_node_id(message.get("id") or (message.get("metadata") or {}).get("message_id"))
                row = await session.get(ConversationNodeORM, (node_id, conversation_id))
                if row is not None:
                    row.metadata_json = message.get("metadata") or {}
            self._apply_conversation_scalars(conv, conversation)
            return True

    async def create_conversation(self, user_id: str, title: Optional[str] = None, model: str = "Auto") -> dict[str, Any]:
        ensure_uuid(user_id)
        conversation_id = new_uuid()
        now = utc_now().isoformat()
        conversation = {
            "id": conversation_id,
            "user_id": user_id,
            "title": title or "New Chat",
            "model": model,
            "last_message": "Start a new conversation...",
            "timestamp": now,
            "updated_at": now,
            "active_branch_id": self.MAIN_BRANCH_ID,
            "branch_selection_state": {},
            "branches": {
                self.MAIN_BRANCH_ID: self._tree._new_branch(self.MAIN_BRANCH_ID, created_at=now),
            },
            "messages": [],
            "preferences": {},
        }
        await self._insert_conversation(user_id, conversation)
        return conversation

    async def get_full_conversation(self, user_id: str, conversation_id: str) -> Optional[dict[str, Any]]:
        conversation = await self._load_conversation(user_id, conversation_id)
        if conversation:
            await self._annotate_feedback_state(user_id, conversation)
        return conversation

    async def _annotate_feedback_state(self, user_id: str, conversation: dict[str, Any]) -> None:
        """Tag recommendation messages the user has already rated with
        ``metadata['feedback'] = {sentiment, reason}`` so the UI shows the vote as
        submitted and does not re-arm the prompt after a refresh / chat switch.

        The result id is resolved the same way ``feedback_repository.submit`` does:
        an explicit ``result_id`` if present, otherwise derived from
        (task_id, branch_id). Messages without a resolvable result reference are
        left untouched (e.g. legacy foreground saves carrying no task id).
        """
        messages = conversation.get("messages") or []
        pending: list[tuple[dict[str, Any], str]] = []
        for message in messages:
            metadata = message.get("metadata")
            if not isinstance(metadata, dict) or metadata.get("type") != "recommendation":
                continue
            result_id = (metadata.get("result_id") or "").strip() or None
            if result_id is None:
                task_id = metadata.get("task_id")
                if task_id:
                    branch_id = message.get("branch_id") or metadata.get("branch_id")
                    result_id = derive_result_id(task_id, branch_id)
            if not result_id:
                continue
            try:
                canonical = ensure_uuid(result_id)
            except ValueError:
                continue
            pending.append((metadata, canonical))
        if not pending:
            return
        found = await feedback_repository.get_for_results(user_id, [rid for _, rid in pending])
        if not found:
            return
        for metadata, canonical in pending:
            vote = found.get(canonical)
            if vote:
                metadata["feedback"] = vote

    async def get_all_conversations(self, user_id: str, *, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        ensure_uuid(user_id)
        limit = max(1, min(int(limit), 100))
        offset = max(0, int(offset))
        async with session_scope() as session:
            rows = (
                await session.scalars(
                    select(ConversationORM)
                    .where(ConversationORM.user_id == user_id, ConversationORM.deleted_at.is_(None))
                    .order_by(ConversationORM.updated_at.desc())
                    .limit(limit)
                    .offset(offset)
                )
            ).all()
            # One grouped COUNT for the whole page instead of a per-conversation
            # query that materialized every node id (former N+1 + full-row scan).
            conversation_ids = [row.id for row in rows]
            counts: dict[str, int] = {}
            if conversation_ids:
                count_rows = (
                    await session.execute(
                        select(
                            ConversationNodeORM.conversation_id,
                            func.count(ConversationNodeORM.id),
                        )
                        .where(ConversationNodeORM.conversation_id.in_(conversation_ids))
                        .group_by(ConversationNodeORM.conversation_id)
                    )
                ).all()
                counts = {cid: int(count) for cid, count in count_rows}
            return [
                {
                    "id": row.id,
                    "title": row.title,
                    "model": row.model,
                    "last_message": row.last_message,
                    "timestamp": row.created_at.isoformat(),
                    "updated_at": row.updated_at.isoformat(),
                    "message_count": counts.get(row.id, 0),
                }
                for row in rows
            ]

    async def add_message(
        self,
        user_id: str,
        conversation_id: str,
        role: str,
        content: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> bool:
        ensure_uuid(conversation_id)
        async with self._conversation_lock(conversation_id):
            return await self._add_message_locked(user_id, conversation_id, role, content, metadata)

    async def _add_message_locked(
        self,
        user_id: str,
        conversation_id: str,
        role: str,
        content: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> bool:
        conversation = await self._load_conversation(user_id, conversation_id)
        if not conversation:
            return False
        metadata = metadata.copy() if metadata else {}
        message_id = metadata.get("message_id") or new_uuid()
        metadata.setdefault("message_id", message_id)
        conversation = self._tree._ensure_tree_metadata(conversation)
        existing_message_ids = {
            existing.get("id") or existing.get("metadata", {}).get("message_id")
            for existing in conversation.get("messages", [])
        }
        branches = conversation.setdefault("branches", {})
        active_branch_id = conversation.get("active_branch_id") or self.MAIN_BRANCH_ID
        time_travel = metadata.get("time_travel") if isinstance(metadata.get("time_travel"), dict) else {}
        branch_id = metadata.get("branch_id") or time_travel.get("branch_id") or active_branch_id
        parent_message_id = metadata.get("parent_message_id")
        fork_from_message_id = metadata.get("fork_from_message_id") or time_travel.get("replay_from_message_id")
        revision_of_message_id = metadata.get("revision_of_message_id") or fork_from_message_id
        fork_source_message = None
        if fork_from_message_id:
            for existing in conversation.get("messages", []):
                if (existing.get("id") or existing.get("metadata", {}).get("message_id")) == fork_from_message_id:
                    fork_source_message = existing
                    break
        if branch_id not in branches:
            parent_branch_id = active_branch_id
            if fork_source_message:
                parent_branch_id = fork_source_message.get("branch_id") or parent_branch_id
            branches[branch_id] = self._tree._new_branch(
                branch_id,
                parent_branch_id=parent_branch_id,
                fork_from_message_id=fork_from_message_id,
                created_at=utc_now().isoformat(),
            )
        if not parent_message_id and fork_source_message:
            parent_message_id = (
                fork_source_message.get("parent_message_id")
                or fork_source_message.get("metadata", {}).get("parent_message_id")
            )
        if not parent_message_id:
            parent_message_id = branches.get(branch_id, {}).get("head_message_id")
        if parent_message_id and parent_message_id not in existing_message_ids:
            fallback_parent_id = branches.get(branch_id, {}).get("head_message_id")
            parent_message_id = fallback_parent_id if fallback_parent_id in existing_message_ids else None
        metadata["branch_id"] = branch_id
        if parent_message_id:
            metadata["parent_message_id"] = parent_message_id
        if fork_from_message_id:
            metadata["fork_from_message_id"] = fork_from_message_id
        if revision_of_message_id:
            metadata["revision_of_message_id"] = revision_of_message_id
        now = utc_now().isoformat()
        message = {
            "id": message_id,
            "role": role,
            "content": content,
            "timestamp": now,
            "branch_id": branch_id,
            "parent_message_id": parent_message_id,
            "metadata": metadata,
        }
        if fork_from_message_id:
            message["fork_from_message_id"] = fork_from_message_id
        if revision_of_message_id:
            message["revision_of_message_id"] = revision_of_message_id
        conversation["messages"].append(message)
        message_by_id = self._tree._message_lookup(conversation.get("messages", []))
        branch = branches[branch_id]
        if not branch.get("root_message_id"):
            branch["root_message_id"] = message_id
        branch["head_message_id"] = message_id
        branch["updated_at"] = now
        branch_selection_state = self._tree._normalize_branch_selection_state(conversation, message_by_id)
        if fork_from_message_id:
            root_id = self._tree._canonical_revision_root_id(fork_from_message_id, message_by_id)
            if root_id:
                branch_selection_state[root_id] = branch_id
        conversation["active_branch_id"] = branch_id
        conversation["last_message"] = content[:100]
        conversation["updated_at"] = now
        if role == "user" and conversation.get("title") in ["New Chat", "Untitled"]:
            conversation["title"] = content[:30].strip() or "New Chat"
        return await self._persist_added_message(user_id, conversation, message, branches[branch_id])

    async def mark_messages_superseded_after(
        self,
        user_id: str,
        conversation_id: str,
        message_id: str,
        branch_id: Optional[str] = None,
    ) -> bool:
        ensure_uuid(conversation_id)
        async with self._conversation_lock(conversation_id):
            return await self._mark_messages_superseded_after_locked(user_id, conversation_id, message_id, branch_id)

    async def _mark_messages_superseded_after_locked(
        self,
        user_id: str,
        conversation_id: str,
        message_id: str,
        branch_id: Optional[str] = None,
    ) -> bool:
        conversation = await self._load_conversation(user_id, conversation_id)
        if not conversation:
            return False
        conversation = self._tree._ensure_tree_metadata(conversation)
        messages = conversation.get("messages", [])
        target_index = -1
        for index, message in enumerate(messages):
            current_id = message.get("id") or message.get("metadata", {}).get("message_id")
            if current_id == message_id:
                target_index = index
                break
        if target_index < 0:
            return False

        now = utc_now().isoformat()
        changed_messages: list[dict[str, Any]] = []
        for message in messages[target_index + 1:]:
            metadata = message.setdefault("metadata", {})
            if branch_id and metadata.get("time_travel", {}).get("branch_id") == branch_id:
                continue
            metadata["superseded"] = True
            metadata["superseded_at"] = now
            metadata["superseded_by_message_id"] = message_id
            if branch_id:
                metadata["superseded_by_branch_id"] = branch_id
            changed_messages.append(message)

        active_messages = [
            message for message in messages
            if not message.get("metadata", {}).get("superseded")
        ]
        if active_messages:
            conversation["last_message"] = active_messages[-1].get("content", "")[:100]
        conversation["updated_at"] = now
        return await self._persist_superseded_nodes(user_id, conversation, changed_messages)

    async def set_active_branch(
        self,
        user_id: str,
        conversation_id: str,
        branch_id: str,
        source_message_id: Optional[str] = None,
    ) -> bool:
        ensure_uuid(conversation_id)
        async with self._conversation_lock(conversation_id):
            return await self._set_active_branch_locked(user_id, conversation_id, branch_id, source_message_id)

    async def _set_active_branch_locked(
        self,
        user_id: str,
        conversation_id: str,
        branch_id: str,
        source_message_id: Optional[str] = None,
    ) -> bool:
        conversation = await self._load_conversation(user_id, conversation_id)
        if not conversation:
            return False
        conversation = self._tree._ensure_tree_metadata(conversation)
        branches = conversation.get("branches", {})
        if branch_id not in branches:
            return False
        conversation["active_branch_id"] = branch_id
        message_by_id = self._tree._message_lookup(conversation.get("messages", []))
        branch_selection_state = self._tree._normalize_branch_selection_state(conversation, message_by_id)
        selection_source_id = source_message_id or self._tree._branch_revision_root_id(branches.get(branch_id, {}), message_by_id)
        selection_root_id = self._tree._canonical_revision_root_id(selection_source_id, message_by_id)
        if selection_root_id:
            branch_selection_state[selection_root_id] = branch_id
        head_message_id = branches.get(branch_id, {}).get("head_message_id")
        if head_message_id:
            for message in conversation.get("messages", []):
                current_id = message.get("id") or message.get("metadata", {}).get("message_id")
                if current_id == head_message_id:
                    conversation["last_message"] = message.get("content", "")[:100]
                    break
        conversation["updated_at"] = utc_now().isoformat()
        return await self._persist_conversation_scalars(user_id, conversation)

    async def update_conversation(self, user_id: str, conversation_id: str, updates: dict[str, Any]) -> bool:
        ensure_uuid(conversation_id)
        async with self._conversation_lock(conversation_id):
            return await self._update_conversation_locked(user_id, conversation_id, updates)

    async def _update_conversation_locked(self, user_id: str, conversation_id: str, updates: dict[str, Any]) -> bool:
        conversation = await self._load_conversation(user_id, conversation_id)
        if not conversation:
            return False
        for key, value in updates.items():
            if key not in {"id", "user_id"}:
                conversation[key] = value
        conversation["updated_at"] = utc_now().isoformat()
        return await self._persist_conversation_scalars(user_id, conversation)

    async def delete_conversation(self, user_id: str, conversation_id: str) -> bool:
        ensure_uuid(user_id)
        ensure_uuid(conversation_id)
        async with self._conversation_lock(conversation_id):
            return await self._delete_conversation_locked(user_id, conversation_id)

    async def _delete_conversation_locked(self, user_id: str, conversation_id: str) -> bool:
        async with session_scope() as session:
            row = await session.get(ConversationORM, conversation_id)
            if row is None or row.user_id != user_id or row.deleted_at is not None:
                return False
            row.deleted_at = utc_now()
            row.updated_at = row.deleted_at
            return True

    async def update_conversation_preferences(
        self,
        user_id: str,
        conversation_id: str,
        new_preferences: dict[str, Any],
    ) -> bool:
        ensure_uuid(conversation_id)
        async with self._conversation_lock(conversation_id):
            return await self._update_conversation_preferences_locked(user_id, conversation_id, new_preferences)

    async def _update_conversation_preferences_locked(
        self,
        user_id: str,
        conversation_id: str,
        new_preferences: dict[str, Any],
    ) -> bool:
        conversation = await self._load_conversation(user_id, conversation_id)
        if not conversation:
            return False
        preferences = conversation.setdefault("preferences", {})
        for key, value in new_preferences.items():
            if value is not None:
                if isinstance(value, dict):
                    preferences.setdefault(key, {}).update(value)
                elif isinstance(value, list) and len(value) > 0:
                    preferences[key] = value
                elif not isinstance(value, (list, dict)):
                    preferences[key] = value
        conversation["updated_at"] = utc_now().isoformat()
        return await self._persist_conversation_scalars(user_id, conversation)

    async def get_conversation_preferences(self, user_id: str, conversation_id: str) -> Optional[dict[str, Any]]:
        conversation = await self._load_conversation(user_id, conversation_id)
        if not conversation:
            return None
        return conversation.get("preferences", {})

    async def update_conversation_context_summary(
        self,
        user_id: str,
        conversation_id: str,
        summary: str,
        watermark_id: Optional[str],
    ) -> bool:
        """Persist the rolling conversation summary + watermark on the conversation's
        metadata (the slice of older turns it already covers), used by the context
        builder so long chats keep memory without re-summarizing every turn."""
        ensure_uuid(conversation_id)
        async with self._conversation_lock(conversation_id):
            conversation = await self._load_conversation(user_id, conversation_id)
            if not conversation:
                return False
            metadata = conversation.setdefault("metadata", {})
            metadata["context_summary"] = {
                "summary": summary,
                "summarized_through_message_id": watermark_id,
                "updated_at": utc_now().isoformat(),
            }
            conversation["updated_at"] = utc_now().isoformat()
            return await self._persist_conversation_scalars(user_id, conversation)


class PostgresTaskRepository:
    async def save(self, user_id: str, conversation_id: Optional[str], task_id: str, status: dict[str, Any]) -> bool:
        payload = _jsonable(status)
        record = TaskProjectionRecord(
            task_id=task_id,
            user_id=user_id,
            conversation_id=conversation_id,
            branch_id=payload.get("metadata", {}).get("branch_id") or payload.get("branch_id"),
            status=payload.get("status", "pending"),
            progress=payload.get("progress", 0),
            message=payload.get("message", ""),
            result=payload.get("result"),
            error=payload.get("error"),
            metadata=payload.get("metadata") or {},
        )
        now = utc_now()
        async with session_scope() as session:
            row = await session.get(RecommendationTaskORM, record.task_id)
            if row is None:
                row = RecommendationTaskORM(
                    task_id=record.task_id,
                    user_id=record.user_id,
                    conversation_id=record.conversation_id,
                    branch_id=record.branch_id,
                    created_at=now,
                )
                session.add(row)
            elif row.user_id != record.user_id or row.conversation_id != record.conversation_id:
                raise ValueError("task_id already exists outside the requested scope")
            row.status = record.status
            row.progress = record.progress
            row.message = record.message
            row.result = record.result
            row.error = record.error
            row.metadata_json = record.metadata
            row.updated_at = now
            return True

    async def load(self, user_id: str, conversation_id: Optional[str], task_id: str) -> Optional[dict[str, Any]]:
        async with session_scope() as session:
            row = await session.get(RecommendationTaskORM, ensure_uuid(task_id))
            if row is None or row.user_id != ensure_uuid(user_id) or row.conversation_id != conversation_id:
                return None
            return {
                "task_id": row.task_id,
                "user_id": row.user_id,
                "conversation_id": row.conversation_id or "default",
                "status": row.status,
                "progress": row.progress,
                "message": row.message,
                "result": row.result,
                "error": row.error,
                "metadata": row.metadata_json or {},
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            }


class PostgresResultRepository:
    async def save(
        self,
        user_id: str,
        conversation_id: Optional[str],
        branch_id: Optional[str],
        result_id: str,
        payload: dict[str, Any],
    ) -> bool:
        data = _jsonable(payload)
        record = RecommendationResultRecord(
            result_id=result_id,
            user_id=user_id,
            conversation_id=conversation_id,
            branch_id=branch_id,
            message_id=data.get("message_id"),
            task_id=data.get("task_id"),
            domain=data.get("domain") or data.get("metadata", {}).get("domain"),
            restaurants=data.get("restaurants") or [],
            thinking_steps=data.get("thinking_steps") or [],
            payload=data,
            metadata=data.get("metadata") or {},
        )
        now = utc_now()
        async with session_scope() as session:
            # Guard the FK (recommendation_results.task_id -> recommendation_tasks.task_id):
            # only reference a task row that actually exists, otherwise the immediate FK
            # check rolls back the whole save and the result is silently lost.
            task_id = record.task_id
            if task_id is not None and await session.get(RecommendationTaskORM, task_id) is None:
                task_id = None
            row = await session.get(RecommendationResultORM, record.result_id)
            if row is None:
                row = RecommendationResultORM(result_id=record.result_id, user_id=record.user_id, created_at=now)
                session.add(row)
            elif row.user_id != record.user_id:
                raise ValueError("result_id already exists outside the requested user scope")
            row.conversation_id = record.conversation_id
            row.branch_id = record.branch_id
            row.message_id = record.message_id
            row.task_id = task_id
            row.domain = record.domain
            row.restaurants = record.restaurants
            row.thinking_steps = record.thinking_steps
            row.payload = record.payload
            row.metadata_json = record.metadata
            row.updated_at = now
            return True

    async def load(
        self,
        user_id: str,
        conversation_id: Optional[str],
        branch_id: Optional[str],
        result_id: str,
    ) -> Optional[dict[str, Any]]:
        async with session_scope() as session:
            row = await session.get(RecommendationResultORM, ensure_uuid(result_id))
            if row is None or row.user_id != ensure_uuid(user_id):
                return None
            if row.conversation_id != conversation_id or row.branch_id != branch_id:
                return None
            return row.payload

    async def load_by_task(
        self,
        user_id: str,
        conversation_id: Optional[str],
        task_id: str,
    ) -> Optional[dict[str, Any]]:
        """Fetch the recommendation persisted for a task, scoped to the owning
        user (and conversation when provided). Used by the conversation side card
        and the /Debug testing arena to resolve a result from a Task ID."""
        async with session_scope() as session:
            row = (
                await session.scalars(
                    select(RecommendationResultORM)
                    .where(
                        RecommendationResultORM.user_id == ensure_uuid(user_id),
                        RecommendationResultORM.task_id == task_id,
                    )
                    .order_by(RecommendationResultORM.updated_at.desc())
                    .limit(1)
                )
            ).first()
            if row is None:
                return None
            if conversation_id is not None and row.conversation_id != conversation_id:
                return None
            return row.payload


class PostgresFeedbackRepository:
    async def _resolve_feedback_result(
        self,
        session: Any,
        *,
        user_uuid: str,
        result_id: Optional[str],
        task_id: Optional[str],
        branch_id: Optional[str],
        conversation_id: Optional[str],
    ) -> RecommendationResultORM:
        explicit_result_id = (result_id or "").strip() or None
        normalized_task_id = (task_id or "").strip() or None

        if explicit_result_id:
            row = await session.get(RecommendationResultORM, ensure_uuid(explicit_result_id))
            if row is None or row.user_id != user_uuid:
                raise ValueError("feedback target not found")
        elif normalized_task_id:
            task = await session.get(RecommendationTaskORM, normalized_task_id)
            if task is None or task.user_id != user_uuid:
                raise ValueError("feedback target not found")
            if conversation_id is not None and task.conversation_id != conversation_id:
                raise ValueError("feedback target not found")
            if branch_id is not None and task.branch_id is not None and task.branch_id != branch_id:
                raise ValueError("feedback target not found")

            effective_branch_id = branch_id if branch_id is not None else task.branch_id
            derived_result_id = derive_result_id(normalized_task_id, effective_branch_id)
            row = await session.get(RecommendationResultORM, derived_result_id)
            if row is None or row.user_id != user_uuid or row.task_id != normalized_task_id:
                conditions = [
                    RecommendationResultORM.user_id == user_uuid,
                    RecommendationResultORM.task_id == normalized_task_id,
                ]
                if conversation_id is not None:
                    conditions.append(RecommendationResultORM.conversation_id == conversation_id)
                if effective_branch_id is not None:
                    conditions.append(RecommendationResultORM.branch_id == effective_branch_id)
                row = (
                    await session.scalars(
                        select(RecommendationResultORM)
                        .where(*conditions)
                        .order_by(RecommendationResultORM.updated_at.desc())
                        .limit(1)
                    )
                ).first()
            if row is None:
                raise ValueError("feedback target not found")
        else:
            raise ValueError("result_id or task_id is required to attach feedback")

        if conversation_id is not None and row.conversation_id != conversation_id:
            raise ValueError("feedback target not found")
        if branch_id is not None and row.branch_id != branch_id:
            raise ValueError("feedback target not found")
        return row

    async def save(
        self,
        user_id: str,
        conversation_id: Optional[str],
        branch_id: Optional[str],
        feedback_id: str,
        payload: dict[str, Any],
    ) -> bool:
        data = _jsonable(payload)
        record = FeedbackRecord(
            feedback_id=feedback_id,
            user_id=user_id,
            conversation_id=conversation_id,
            branch_id=branch_id,
            message_id=data.get("message_id"),
            result_id=data.get("result_id"),
            label=data.get("label"),
            rating=data.get("rating"),
            comment=data.get("comment"),
            payload=data,
            metadata=data.get("metadata") or {},
        )
        now = utc_now()
        async with session_scope() as session:
            row = await session.get(FeedbackORM, record.feedback_id)
            if row is None:
                row = FeedbackORM(feedback_id=record.feedback_id, user_id=record.user_id, created_at=now)
                session.add(row)
            elif row.user_id != record.user_id:
                raise ValueError("feedback_id already exists outside the requested user scope")
            row.conversation_id = record.conversation_id
            row.branch_id = record.branch_id
            row.message_id = record.message_id
            row.result_id = record.result_id
            row.label = record.label
            row.rating = record.rating
            row.comment = record.comment
            row.payload = record.payload
            row.metadata_json = record.metadata
            row.updated_at = now
            return True

    async def load(
        self,
        user_id: str,
        conversation_id: Optional[str],
        branch_id: Optional[str],
        feedback_id: str,
    ) -> Optional[dict[str, Any]]:
        async with session_scope() as session:
            row = await session.get(FeedbackORM, ensure_uuid(feedback_id))
            if row is None or row.user_id != ensure_uuid(user_id):
                return None
            if row.conversation_id != conversation_id or row.branch_id != branch_id:
                return None
            return row.payload

    async def submit(
        self,
        *,
        user_id: str,
        sentiment: str,
        reason: Optional[str] = None,
        result_id: Optional[str] = None,
        task_id: Optional[str] = None,
        branch_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        ui_message_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Record a user's thumb-up / thumb-down on a recommendation result.

        Sentiment maps to `rating` (the authoritative satisfaction signal read by
        the dashboard) and `label` carries the dislike reason (the "why" histogram):
          up   -> rating=5, label=None
          down -> rating=1, label=<reason or "others">

        The vote is keyed on (user_id, result_id): we store the `message_id` column
        as the resolved result_id so the partial unique index `ix_feedback_uq_with_result`
        collapses to one row per (user, result), making re-votes an idempotent UPSERT
        (no lost updates under concurrent taps) regardless of the UI message id.
        """
        if sentiment == "up":
            rating = 5
            label: Optional[str] = None
        elif sentiment == "down":
            rating = 1
            label = reason or "others"
        else:
            raise ValueError("sentiment must be 'up' or 'down'")

        user_uuid = ensure_uuid(user_id)
        now = utc_now()
        async with session_scope() as session:
            target = await self._resolve_feedback_result(
                session,
                user_uuid=user_uuid,
                result_id=result_id,
                task_id=task_id,
                branch_id=branch_id,
                conversation_id=conversation_id,
            )
            resolved_result_id = ensure_uuid(target.result_id)
            canonical_conversation_id = target.conversation_id
            canonical_branch_id = target.branch_id
            canonical_task_id = target.task_id or ((task_id or "").strip() or None)
            payload = {
                "sentiment": sentiment,
                "reason": label,
                "reason_schema": FEEDBACK_REASON_SCHEMA,
                "ui_message_id": ui_message_id,
                "result_id": resolved_result_id,
                "task_id": canonical_task_id,
                "branch_id": canonical_branch_id,
                "conversation_id": canonical_conversation_id,
            }
            stmt = (
                pg_insert(FeedbackORM)
                .values(
                    feedback_id=new_uuid(),
                    user_id=user_uuid,
                    conversation_id=canonical_conversation_id,
                    branch_id=canonical_branch_id,
                    message_id=resolved_result_id,
                    result_id=resolved_result_id,
                    label=label,
                    rating=rating,
                    comment=None,
                    payload=payload,
                    metadata_json={},
                    created_at=now,
                    updated_at=now,
                )
                .on_conflict_do_update(
                    index_elements=["user_id", "result_id", "message_id"],
                    index_where=text("result_id IS NOT NULL"),
                    set_={
                        "conversation_id": canonical_conversation_id,
                        "branch_id": canonical_branch_id,
                        "label": label,
                        "rating": rating,
                        "payload": payload,
                        "updated_at": now,
                    },
                )
                .returning(FeedbackORM.feedback_id)
            )
            feedback_id = (await session.execute(stmt)).scalar_one()
        return {
            "feedback_id": str(feedback_id),
            "result_id": resolved_result_id,
            "sentiment": sentiment,
            "rating": rating,
            "reason": label,
        }

    async def get_for_results(self, user_id: str, result_ids: list[str]) -> dict[str, dict[str, Any]]:
        """Map ``result_id -> {sentiment, reason}`` for this user's existing votes
        on the given results.

        Powers the "already answered" state so the feedback prompt does not
        re-arm after a refresh or when switching conversations. Ids are matched
        against the same canonical (UUID) form ``submit`` persists; non-UUID
        values are skipped.
        """
        if not result_ids:
            return {}
        user_uuid = ensure_uuid(user_id)
        normalized: list[str] = []
        seen: set[str] = set()
        for rid in result_ids:
            try:
                canonical = ensure_uuid(rid)
            except ValueError:
                continue
            if canonical not in seen:
                seen.add(canonical)
                normalized.append(canonical)
        if not normalized:
            return {}
        async with session_scope() as session:
            rows = (
                await session.scalars(
                    select(FeedbackORM).where(
                        FeedbackORM.user_id == user_uuid,
                        FeedbackORM.result_id.in_(normalized),
                    )
                )
            ).all()
        out: dict[str, dict[str, Any]] = {}
        for row in rows:
            payload = row.payload if isinstance(row.payload, dict) else {}
            sentiment = payload.get("sentiment") or ("up" if (row.rating or 0) >= 4 else "down")
            out[str(row.result_id)] = {
                "sentiment": sentiment,
                "reason": payload.get("reason") if sentiment == "down" else None,
            }
        return out


class PostgresAdminRepository:
    """Admin dashboard analytics + user-table CRUD.

    Read paths use aggregate SQL only (never materialize whole tables); list_users
    is strictly paginated. Mutations take a per-row FOR UPDATE lock and a process-
    crossing advisory lock so the last-admin guard cannot race a concurrent edit.
    """

    ALLOWED_STATUSES = {"active", "suspended", "deleted"}

    # ---- analytics -------------------------------------------------------

    async def get_stats(self) -> dict[str, Any]:
        now = utc_now()
        seven_days_ago = now - timedelta(days=7)
        async with session_scope() as session:
            # Tasks
            total_tasks, completed_tasks, errored_tasks = (
                await session.execute(
                    select(
                        func.count(RecommendationTaskORM.task_id),
                        func.count().filter(RecommendationTaskORM.status == "completed"),
                        func.count().filter(RecommendationTaskORM.status == "error"),
                    )
                )
            ).one()
            finished = completed_tasks + errored_tasks
            success_rate = round(completed_tasks / finished, 4) if finished else 0.0

            # Tokens (cumulative + trailing 7 days)
            total_tokens, prompt_tokens, completion_tokens, cost_usd = (
                await session.execute(
                    select(
                        func.coalesce(func.sum(ConversationNodeORM.total_tokens), 0),
                        func.coalesce(func.sum(ConversationNodeORM.prompt_tokens), 0),
                        func.coalesce(func.sum(ConversationNodeORM.completion_tokens), 0),
                        func.coalesce(func.sum(ConversationNodeORM.cost_usd), 0.0),
                    )
                )
            ).one()
            last_7d_total_tokens = (
                await session.execute(
                    select(func.coalesce(func.sum(ConversationNodeORM.total_tokens), 0)).where(
                        ConversationNodeORM.created_at >= seven_days_ago
                    )
                )
            ).scalar_one()

            # Users
            total_users, registered_users, guest_users, new_registered_7d = (
                await session.execute(
                    select(
                        func.count(UserORM.id),
                        func.count().filter(UserORM.kind == "registered"),
                        func.count().filter(UserORM.kind == "guest"),
                        func.count().filter(
                            (UserORM.kind == "registered") & (UserORM.created_at >= seven_days_ago)
                        ),
                    )
                )
            ).one()

            # Conversations + active sessions
            total_conversations = (
                await session.execute(
                    select(func.count(ConversationORM.id)).where(ConversationORM.deleted_at.is_(None))
                )
            ).scalar_one()
            active_sessions = (
                await session.execute(
                    select(func.count(UserSessionORM.id)).where(
                        UserSessionORM.status == "active",
                        UserSessionORM.expires_at > now,
                    )
                )
            ).scalar_one()

            feedback = await self._feedback_stats(session)

        return {
            "tasks": {
                "total": int(total_tasks),
                "completed": int(completed_tasks),
                "errored": int(errored_tasks),
                "success_rate": success_rate,
            },
            "tokens": {
                "total_tokens": int(total_tokens),
                "prompt_tokens": int(prompt_tokens),
                "completion_tokens": int(completion_tokens),
                "cost_usd": round(float(cost_usd), 6),
                "last_7d_total_tokens": int(last_7d_total_tokens),
            },
            "users": {
                "total": int(total_users),
                "registered": int(registered_users),
                "guests": int(guest_users),
                "new_registered_last_7d": int(new_registered_7d),
            },
            "conversations": {
                "total_created": int(total_conversations),
                "active_sessions": int(active_sessions),
            },
            "feedback": feedback,
            "generated_at": now.isoformat(),
        }

    @staticmethod
    async def _feedback_stats(session) -> dict[str, Any]:
        positive = func.lower(FeedbackORM.label).in_(_POSITIVE_FEEDBACK_LABELS)
        negative = func.lower(FeedbackORM.label).in_(_NEGATIVE_FEEDBACK_LABELS)
        satisfied_cond = (FeedbackORM.rating >= 4) | positive
        unsatisfied_cond = ((FeedbackORM.rating.isnot(None)) & (FeedbackORM.rating <= 2)) | negative

        total, satisfied, unsatisfied = (
            await session.execute(
                select(
                    func.count(FeedbackORM.feedback_id),
                    func.count().filter(satisfied_cond),
                    func.count().filter(unsatisfied_cond),
                )
            )
        ).one()
        rated = satisfied + unsatisfied
        ratio = round(satisfied / rated, 4) if rated else None

        reason_rows = (
            await session.execute(
                select(FeedbackORM.label, func.count())
                .where(unsatisfied_cond)
                .group_by(FeedbackORM.label)
                .order_by(func.count().desc())
                .limit(10)
            )
        ).all()
        reasons = [{"reason": label or "unspecified", "count": int(count)} for label, count in reason_rows]
        return {
            "total": int(total),
            "satisfied": int(satisfied),
            "unsatisfied": int(unsatisfied),
            "satisfaction_ratio": ratio,
            "reasons": reasons,
        }

    # ---- user CRUD -------------------------------------------------------

    async def list_users(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        search: Optional[str] = None,
        role: Optional[str] = None,
        status: Optional[str] = None,
        kind: Optional[str] = None,
    ) -> tuple[list[dict[str, Any]], int]:
        limit = max(1, min(int(limit), 100))
        offset = max(0, int(offset))
        conditions = []
        if search and search.strip():
            like = f"%{search.strip().lower()}%"
            conditions.append(
                or_(
                    func.lower(UserORM.email).like(like),
                    func.lower(UserORM.display_name).like(like),
                )
            )
        if role:
            conditions.append(UserORM.role == role)
        if status:
            conditions.append(UserORM.status == status)
        if kind:
            conditions.append(UserORM.kind == kind)
        async with session_scope() as session:
            count_q = select(func.count(UserORM.id))
            rows_q = select(UserORM).order_by(UserORM.created_at.desc()).limit(limit).offset(offset)
            if conditions:
                count_q = count_q.where(*conditions)
                rows_q = rows_q.where(*conditions)
            total = (await session.execute(count_q)).scalar_one()
            rows = (await session.scalars(rows_q)).all()
            return [_user_admin_dict(r) for r in rows], int(total)

    async def get_user(self, user_id: str) -> Optional[dict[str, Any]]:
        async with session_scope() as session:
            row = await session.get(UserORM, ensure_uuid(user_id))
            return _user_admin_dict(row) if row is not None else None

    async def count_active_admins(self, *, exclude_user_id: Optional[str] = None) -> int:
        async with session_scope() as session:
            return await self._count_active_admins(session, exclude_user_id=exclude_user_id)

    @staticmethod
    async def _count_active_admins(session, *, exclude_user_id: Optional[str] = None) -> int:
        q = select(func.count(UserORM.id)).where(
            UserORM.role == UserRole.ADMIN.value,
            UserORM.status == "active",
        )
        if exclude_user_id is not None:
            q = q.where(UserORM.id != exclude_user_id)
        return int((await session.execute(q)).scalar_one())

    async def create_user(
        self,
        *,
        email: str,
        password: str,
        display_name: Optional[str] = None,
        role: str = UserRole.USER.value,
        status: str = "active",
    ) -> dict[str, Any]:
        normalized_email = (email or "").strip().lower()
        if "@" not in normalized_email or len(normalized_email) > 320:
            raise ValueError("a valid email is required")
        if not password or len(password) < 8:
            raise ValueError("password must be at least 8 characters")
        role_value = UserRole(role).value  # raises ValueError on unknown role
        if status not in self.ALLOWED_STATUSES:
            raise ValueError(f"status must be one of {sorted(self.ALLOWED_STATUSES)}")
        now = utc_now()
        async with session_scope() as session:
            user = UserORM(
                id=new_uuid(),
                kind="registered",
                email=normalized_email,
                password_hash=pwd_context.hash(password),
                display_name=display_name,
                role=role_value,
                status=status,
                metadata_json={"source": "admin_create"},
                created_at=now,
                updated_at=now,
            )
            session.add(user)
            try:
                await session.flush()
            except IntegrityError as exc:
                raise ValueError("email is already registered") from exc
            return _user_admin_dict(user)

    async def update_user(
        self,
        *,
        user_id: str,
        expected_updated_at: Any = None,
        role: Optional[str] = None,
        status: Optional[str] = None,
        display_name: Optional[str] = None,
        display_name_provided: bool = False,
    ) -> dict[str, Any]:
        role_value = UserRole(role).value if role is not None else None
        if status is not None and status not in self.ALLOWED_STATUSES:
            raise ValueError(f"status must be one of {sorted(self.ALLOWED_STATUSES)}")
        async with session_scope() as session:
            await session.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _ADMIN_MUTATION_LOCK_KEY})
            row = await session.scalar(
                select(UserORM).where(UserORM.id == ensure_uuid(user_id)).with_for_update()
            )
            if row is None:
                raise UserNotFoundError("user not found")
            if expected_updated_at is not None and not _updated_at_matches(row.updated_at, expected_updated_at):
                raise ConcurrencyConflictError("user has been modified since it was loaded")

            removes_admin = (
                row.role == UserRole.ADMIN.value
                and row.status == "active"
                and (
                    (role_value is not None and role_value != UserRole.ADMIN.value)
                    or (status is not None and status != "active")
                )
            )
            if removes_admin and await self._count_active_admins(session, exclude_user_id=row.id) == 0:
                raise LastAdminError("cannot remove the last active admin")

            if role_value is not None:
                row.role = role_value
            if status is not None:
                row.status = status
            if display_name_provided:
                row.display_name = display_name
            row.updated_at = utc_now()
            await session.flush()
            return _user_admin_dict(row)

    async def soft_delete_user(self, *, user_id: str) -> dict[str, Any]:
        async with session_scope() as session:
            await session.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _ADMIN_MUTATION_LOCK_KEY})
            uid = ensure_uuid(user_id)
            row = await session.scalar(select(UserORM).where(UserORM.id == uid).with_for_update())
            if row is None:
                raise UserNotFoundError("user not found")
            if (
                row.role == UserRole.ADMIN.value
                and row.status == "active"
                and await self._count_active_admins(session, exclude_user_id=row.id) == 0
            ):
                raise LastAdminError("cannot remove the last active admin")
            now = utc_now()
            row.status = "deleted"
            row.updated_at = now
            await session.execute(
                update(UserSessionORM)
                .where(UserSessionORM.user_id == uid, UserSessionORM.status == "active")
                .values(status="revoked", revoked_at=now, updated_at=now)
            )
            return _user_admin_dict(row)


auth_repository = PostgresAuthRepository()
profile_repository = PostgresProfileRepository()
conversation_repository = PostgresConversationRepository()
task_repository = PostgresTaskRepository()
result_repository = PostgresResultRepository()
feedback_repository = PostgresFeedbackRepository()
admin_repository = PostgresAdminRepository()
