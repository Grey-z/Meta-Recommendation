"""Item-level interaction API — "Save", "Not interested", "Played/Watched/Read/…"
on one recommended item.

Mounted at ``/api/item-interactions`` and gated on an authenticated **registered**
session, like ``/api/feedback``. The difference from feedback is the unit: feedback
is a thumb on a *result* (no item id), this is an action on an *item*, which is
what a per-domain recommender can learn from.

Semantics live in ``PostgresItemInteractionRepository``; this module only shapes
requests/responses and never reaches into the ORM.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator

from business_models import (
    ITEM_INTERACTION_ACTIONS,
    ITEM_INTERACTION_DOMAINS,
    ITEM_INTERACTION_MAX_ITEM_ID,
    ITEM_INTERACTION_SCHEMA,
    AuthSessionPayload,
    ItemInteractionAction,
    ItemInteractionRecord,
    ensure_uuid,
    item_interaction_options_for_domain,
)
from business_repositories import item_interaction_repository


class StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ItemSnapshotAPI(StrictBaseModel):
    """Client-safe subset of the item, stored with the event for offline use."""

    title: Optional[str] = Field(default=None, max_length=300)
    subtitle: Optional[str] = Field(default=None, max_length=300)
    source: Optional[str] = Field(default=None, max_length=300)
    url: Optional[str] = Field(default=None, max_length=300)


class ItemInteractionCreateAPI(StrictBaseModel):
    domain: str = Field(min_length=1, max_length=40)
    item_id: str = Field(min_length=1, max_length=ITEM_INTERACTION_MAX_ITEM_ID)
    action: ItemInteractionAction
    # Client-generated idempotency key; omit to let the server mint one.
    event_id: Optional[str] = None
    # Where the item was shown. All optional — the interaction is valid on its own.
    result_id: Optional[str] = None
    task_id: Optional[str] = None
    conversation_id: Optional[str] = None
    item: Optional[ItemSnapshotAPI] = None

    @field_validator("domain")
    @classmethod
    def _domain(cls, value: str) -> str:
        key = value.strip().lower()
        if key not in ITEM_INTERACTION_DOMAINS:
            raise ValueError(f"domain must be one of {', '.join(ITEM_INTERACTION_DOMAINS)}")
        return key

    @field_validator("event_id", "result_id", "conversation_id")
    @classmethod
    def _uuid_or_none(cls, value: Optional[str]) -> Optional[str]:
        text = (value or "").strip()
        return ensure_uuid(text) if text else None


class ItemInteractionAPI(StrictBaseModel):
    schema_version: str
    event_id: str
    domain: str
    item_id: str
    action: ItemInteractionAction
    result_id: Optional[str] = None
    task_id: Optional[str] = None
    conversation_id: Optional[str] = None
    occurred_at: datetime
    revoked_at: Optional[datetime] = None
    item: Optional[ItemSnapshotAPI] = None


class ItemInteractionCreateResponseAPI(StrictBaseModel):
    ok: bool
    created: bool
    interaction: ItemInteractionAPI


class ItemInteractionListAPI(StrictBaseModel):
    interactions: List[ItemInteractionAPI]


class ItemInteractionRevokeResponseAPI(StrictBaseModel):
    ok: bool
    interaction: ItemInteractionAPI


class ItemInteractionOptionAPI(StrictBaseModel):
    code: str
    label: str


class ItemInteractionOptionsAPI(StrictBaseModel):
    actions: List[ItemInteractionOptionAPI]


def _to_api(record: ItemInteractionRecord) -> ItemInteractionAPI:
    snapshot = record.payload.get("item") if isinstance(record.payload, dict) else None
    return ItemInteractionAPI(
        schema_version=ITEM_INTERACTION_SCHEMA,
        event_id=record.event_id,
        domain=record.domain,
        item_id=record.item_id,
        action=record.action,
        result_id=record.result_id,
        task_id=record.task_id,
        conversation_id=record.conversation_id,
        occurred_at=record.occurred_at,
        revoked_at=record.revoked_at,
        item=ItemSnapshotAPI(**snapshot) if isinstance(snapshot, dict) and snapshot else None,
    )


def _require_registered(session: AuthSessionPayload) -> None:
    # Guests cannot leave interactions (the UI also hides the control for them).
    if session.user.kind != "registered":
        raise HTTPException(status_code=403, detail="Only registered users can record item interactions")


def create_item_interaction_router(require_session: Callable[..., Any]) -> APIRouter:
    router = APIRouter(prefix="/api/item-interactions", tags=["item-interactions"])

    @router.get("/options", response_model=ItemInteractionOptionsAPI)
    async def interaction_options(
        domain: Optional[str] = None,
        _: AuthSessionPayload = Depends(require_session),
    ):
        # Single source of truth for the FE chips and their per-domain wording.
        return ItemInteractionOptionsAPI(
            actions=[ItemInteractionOptionAPI(**option) for option in item_interaction_options_for_domain(domain)]
        )

    @router.get("", response_model=ItemInteractionListAPI)
    async def list_interactions(
        domain: Optional[str] = Query(default=None, max_length=40),
        item_ids: Optional[str] = Query(
            default=None,
            description="Comma-separated item ids to narrow to (max 50); used for on-screen toggle state.",
        ),
        include_revoked: bool = False,
        limit: int = Query(default=200, ge=1, le=2000),
        session: AuthSessionPayload = Depends(require_session),
    ):
        # Own history only — user_id always comes from the session.
        ids: Optional[List[str]] = None
        if item_ids:
            ids = [part.strip() for part in item_ids.split(",") if part.strip()]
            if len(ids) > 50:
                raise HTTPException(status_code=400, detail="item_ids accepts at most 50 ids")
            if any(len(part) > ITEM_INTERACTION_MAX_ITEM_ID for part in ids):
                raise HTTPException(status_code=400, detail="item id too long")
            if not ids:
                ids = None
        domain_key = (domain or "").strip().lower() or None
        if domain_key and domain_key not in ITEM_INTERACTION_DOMAINS:
            raise HTTPException(status_code=400, detail=f"domain must be one of {', '.join(ITEM_INTERACTION_DOMAINS)}")
        records = await item_interaction_repository.list_for_user(
            session.user.id,
            domain=domain_key,
            item_ids=ids,
            include_revoked=include_revoked,
            limit=limit,
        )
        return ItemInteractionListAPI(interactions=[_to_api(record) for record in records])

    @router.post("", response_model=ItemInteractionCreateResponseAPI)
    async def record_interaction(
        payload: ItemInteractionCreateAPI,
        session: AuthSessionPayload = Depends(require_session),
    ):
        _require_registered(session)
        try:
            record, created = await item_interaction_repository.record(
                user_id=session.user.id,
                domain=payload.domain,
                item_id=payload.item_id,
                action=payload.action,
                event_id=payload.event_id,
                result_id=payload.result_id,
                task_id=payload.task_id,
                conversation_id=payload.conversation_id,
                item=payload.item.model_dump(exclude_none=True) if payload.item else None,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return ItemInteractionCreateResponseAPI(ok=True, created=created, interaction=_to_api(record))

    @router.delete("/{event_id}", response_model=ItemInteractionRevokeResponseAPI)
    async def revoke_interaction(
        event_id: str,
        session: AuthSessionPayload = Depends(require_session),
    ):
        _require_registered(session)
        try:
            record = await item_interaction_repository.revoke(user_id=session.user.id, event_id=event_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        if record is None:
            raise HTTPException(status_code=404, detail="interaction not found")
        return ItemInteractionRevokeResponseAPI(ok=True, interaction=_to_api(record))

    return router


__all__ = [
    "ITEM_INTERACTION_ACTIONS",
    "ItemInteractionCreateAPI",
    "ItemInteractionAPI",
    "create_item_interaction_router",
]
