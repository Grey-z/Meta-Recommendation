from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from passlib.context import CryptContext
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from business_db import session_scope
from business_models import (
    AuthSessionPayload,
    FeedbackRecord,
    RecommendationResultRecord,
    TaskProjectionRecord,
    UserRecord,
    UserSessionRecord,
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
        email=row.email,
        display_name=row.display_name,
        status=row.status,
        metadata=row.metadata_json or {},
        created_at=row.created_at,
        updated_at=row.updated_at,
        last_seen_at=row.last_seen_at,
    )


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
        ttl_days: int = 30,
    ) -> AuthSessionPayload:
        normalized_email = email.strip().lower()
        if "@" not in normalized_email or len(normalized_email) > 320:
            raise ValueError("valid email is required")
        if len(password) < 8:
            raise ValueError("password must be at least 8 characters")
        now = utc_now()
        async with session_scope() as session:
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


class PostgresProfileRepository:
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
            if row is None:
                row = UserProfileORM(
                    user_id=user_id,
                    demographics=profile.get("demographics") or {},
                    dining_habits=profile.get("dining_habits") or {},
                    metadata_json=profile.get("metadata") or {},
                    created_at=now,
                    updated_at=now,
                )
                session.add(row)
            else:
                row.demographics = profile.get("demographics") or {}
                row.dining_habits = profile.get("dining_habits") or {}
                row.metadata_json = profile.get("metadata") or {}
                row.version = (row.version or 1) + 1
                row.updated_at = now
            return True


class PostgresConversationRepository:
    MAIN_BRANCH_ID = ConversationStorage.MAIN_BRANCH_ID

    def __init__(self):
        self._tree = ConversationStorage(storage_dir="conversations")

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
            }
            return self._tree._ensure_tree_metadata(payload)

    async def _save_conversation(self, user_id: str, conversation: dict[str, Any]) -> bool:
        ensure_uuid(user_id)
        conversation_id = ensure_uuid(conversation.get("id"))
        now = utc_now()
        async with session_scope() as session:
            conv = await session.get(ConversationORM, conversation_id)
            created_at = conversation.get("timestamp") or conversation.get("created_at")
            if conv is None:
                conv = ConversationORM(
                    id=conversation_id,
                    user_id=user_id,
                    created_at=datetime.fromisoformat(created_at) if created_at else now,
                )
                session.add(conv)
            conv.user_id = user_id
            conv.title = conversation.get("title") or "New Chat"
            conv.model = conversation.get("model") or "Auto"
            conv.last_message = conversation.get("last_message") or ""
            conv.active_branch_id = conversation.get("active_branch_id") or self.MAIN_BRANCH_ID
            conv.branch_selection_state = conversation.get("branch_selection_state") or {}
            conv.preferences = conversation.get("preferences") or {}
            conv.metadata_json = conversation.get("metadata") or {}
            conv.updated_at = now

            await session.execute(delete(ConversationBranchORM).where(ConversationBranchORM.conversation_id == conversation_id))
            await session.execute(delete(ConversationNodeORM).where(ConversationNodeORM.conversation_id == conversation_id))
            await session.flush()

            for branch in (conversation.get("branches") or {}).values():
                branch_id = ensure_node_id(branch.get("id"))
                session.add(
                    ConversationBranchORM(
                        id=branch_id,
                        conversation_id=conversation_id,
                        parent_branch_id=branch.get("parent_branch_id"),
                        fork_from_message_id=branch.get("fork_from_message_id"),
                        root_message_id=branch.get("root_message_id"),
                        head_message_id=branch.get("head_message_id"),
                        title=branch.get("title"),
                        created_at=datetime.fromisoformat(branch["created_at"]) if branch.get("created_at") else now,
                        updated_at=datetime.fromisoformat(branch["updated_at"]) if branch.get("updated_at") else now,
                        metadata_json=branch.get("metadata") or {},
                    )
                )
            for message in conversation.get("messages") or []:
                metadata = message.get("metadata") or {}
                stats = metadata.get("stats") if isinstance(metadata.get("stats"), dict) else {}
                session.add(
                    ConversationNodeORM(
                        id=ensure_node_id(message.get("id") or metadata.get("message_id")),
                        conversation_id=conversation_id,
                        branch_id=ensure_node_id(message.get("branch_id") or metadata.get("branch_id") or self.MAIN_BRANCH_ID),
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
                        created_at=datetime.fromisoformat(message["timestamp"]) if message.get("timestamp") else now,
                    )
                )
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
        await self._save_conversation(user_id, conversation)
        return conversation

    async def get_full_conversation(self, user_id: str, conversation_id: str) -> Optional[dict[str, Any]]:
        return await self._load_conversation(user_id, conversation_id)

    async def get_all_conversations(self, user_id: str) -> list[dict[str, Any]]:
        ensure_uuid(user_id)
        async with session_scope() as session:
            rows = (
                await session.scalars(
                    select(ConversationORM)
                    .where(ConversationORM.user_id == user_id, ConversationORM.deleted_at.is_(None))
                    .order_by(ConversationORM.updated_at.desc())
                )
            ).all()
            return [
                {
                    "id": row.id,
                    "title": row.title,
                    "model": row.model,
                    "last_message": row.last_message,
                    "timestamp": row.created_at.isoformat(),
                    "updated_at": row.updated_at.isoformat(),
                    "message_count": await self._message_count(session, row.id),
                }
                for row in rows
            ]

    async def _message_count(self, session, conversation_id: str) -> int:
        rows = (await session.scalars(select(ConversationNodeORM.id).where(ConversationNodeORM.conversation_id == conversation_id))).all()
        return len(rows)

    async def add_message(
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
        return await self._save_conversation(user_id, conversation)

    async def mark_messages_superseded_after(
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
        for message in messages[target_index + 1:]:
            metadata = message.setdefault("metadata", {})
            if branch_id and metadata.get("time_travel", {}).get("branch_id") == branch_id:
                continue
            metadata["superseded"] = True
            metadata["superseded_at"] = now
            metadata["superseded_by_message_id"] = message_id
            if branch_id:
                metadata["superseded_by_branch_id"] = branch_id

        active_messages = [
            message for message in messages
            if not message.get("metadata", {}).get("superseded")
        ]
        if active_messages:
            conversation["last_message"] = active_messages[-1].get("content", "")[:100]
        conversation["updated_at"] = now
        return await self._save_conversation(user_id, conversation)

    async def set_active_branch(
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
        return await self._save_conversation(user_id, conversation)

    async def update_conversation(self, user_id: str, conversation_id: str, updates: dict[str, Any]) -> bool:
        conversation = await self._load_conversation(user_id, conversation_id)
        if not conversation:
            return False
        for key, value in updates.items():
            if key not in {"id", "user_id"}:
                conversation[key] = value
        conversation["updated_at"] = utc_now().isoformat()
        return await self._save_conversation(user_id, conversation)

    async def delete_conversation(self, user_id: str, conversation_id: str) -> bool:
        ensure_uuid(user_id)
        ensure_uuid(conversation_id)
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
        return await self._save_conversation(user_id, conversation)

    async def get_conversation_preferences(self, user_id: str, conversation_id: str) -> Optional[dict[str, Any]]:
        conversation = await self._load_conversation(user_id, conversation_id)
        if not conversation:
            return None
        return conversation.get("preferences", {})


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
            row = await session.get(RecommendationResultORM, record.result_id)
            if row is None:
                row = RecommendationResultORM(result_id=record.result_id, user_id=record.user_id, created_at=now)
                session.add(row)
            row.conversation_id = record.conversation_id
            row.branch_id = record.branch_id
            row.message_id = record.message_id
            row.task_id = record.task_id
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


class PostgresFeedbackRepository:
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


auth_repository = PostgresAuthRepository()
profile_repository = PostgresProfileRepository()
conversation_repository = PostgresConversationRepository()
task_repository = PostgresTaskRepository()
result_repository = PostgresResultRepository()
feedback_repository = PostgresFeedbackRepository()
