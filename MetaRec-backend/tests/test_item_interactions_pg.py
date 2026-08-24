"""Postgres contract for PostgresItemInteractionRepository.

Skips without DATABASE_URL (CI runs it against a real Postgres 16 service).
Asserts the semantics the API, the UI and the domain rankers all rely on:
event_id idempotency, save/hide exclusivity under the partial unique index,
append-only events, soft revoke, and chronological reads.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import timedelta

import pytest


@pytest.mark.runtime_contract
@pytest.mark.asyncio
async def test_item_interaction_repository_contract():
    if not os.getenv("DATABASE_URL"):
        pytest.skip("DATABASE_URL is required for the Postgres item-interaction contract test")

    from business_db import dispose_async_engine
    from business_models import to_interaction_v1, utc_now
    from business_repositories import auth_repository, item_interaction_repository as repo

    suffix = uuid.uuid4().hex
    try:
        auth = await auth_repository.get_or_create_guest(device_id=f"pytest-ii-{suffix}")
        user_id = auth.user.id
        other = await auth_repository.get_or_create_guest(device_id=f"pytest-ii-other-{suffix}")
        item = f"tmdb_movie_{suffix[:8]}"

        # 1. event_id idempotency — second call returns the stored row unchanged.
        event_id = str(uuid.uuid4())
        first, created = await repo.record(
            user_id=user_id, domain="movie", item_id=item, action="save", event_id=event_id,
            item={"title": "Arrival", "raw": {"must": "not be stored"}},
        )
        assert created is True
        assert first.payload == {"item": {"title": "Arrival"}}  # raw is dropped
        again, created = await repo.record(user_id=user_id, domain="movie", item_id=item, action="hide", event_id=event_id)
        assert created is False and again.action == "save"  # body differences are ignored

        # Same event_id from another user is refused, never silently re-owned.
        with pytest.raises(ValueError):
            await repo.record(user_id=other.user.id, domain="movie", item_id=item, action="save", event_id=event_id)

        # 2. save is a toggle: a fresh save on the same item is a no-op.
        dup, created = await repo.record(user_id=user_id, domain="movie", item_id=item, action="save")
        assert created is False and dup.event_id == event_id

        # 3. hide supersedes save (mutual exclusion), leaving one active toggle.
        hidden, created = await repo.record(user_id=user_id, domain="movie", item_id=item, action="hide")
        assert created is True
        active = await repo.list_for_user(user_id, domain="movie", item_ids=[item])
        assert [r.action for r in active] == ["hide"]
        history = await repo.list_for_user(user_id, domain="movie", item_ids=[item], include_revoked=True)
        assert sorted(r.action for r in history) == ["hide", "save"]
        assert next(r for r in history if r.action == "save").revoked_at is not None

        # 4. Concurrent saves on the same item converge on one active row
        #    (partial unique index + IntegrityError fallback).
        fresh_item = f"{item}-race"
        results = await asyncio.gather(*[
            repo.record(user_id=user_id, domain="movie", item_id=fresh_item, action="save") for _ in range(5)
        ])
        assert sum(1 for _, c in results if c) == 1
        assert len({r.event_id for r, _ in results}) == 1
        assert len(await repo.list_for_user(user_id, domain="movie", item_ids=[fresh_item])) == 1

        # 5. consumed is append-only and reads back in chronological order.
        t0 = utc_now() - timedelta(minutes=10)
        for minute in (3, 1, 2):
            await repo.record(
                user_id=user_id, domain="movie", item_id=item, action="consumed",
                occurred_at=t0 + timedelta(minutes=minute),
            )
        plays = [r for r in await repo.list_for_user(user_id, domain="movie") if r.action == "consumed"]
        assert [r.occurred_at.minute for r in plays] == [(t0 + timedelta(minutes=m)).minute for m in (1, 2, 3)]
        assert len(plays) == 3

        # 6. Domain filter and the ranker projection.
        assert await repo.list_for_user(user_id, domain="music") == []
        wire = [to_interaction_v1(r) for r in await repo.list_for_user(user_id, domain="movie")]
        assert all(set(w) == {"schema_version", "event_id", "domain", "item_id", "action", "result_id", "occurred_at"} for w in wire)

        # 7. Revoke is owner-scoped and idempotent.
        assert await repo.revoke(user_id=other.user.id, event_id=hidden.event_id) is None
        revoked = await repo.revoke(user_id=user_id, event_id=hidden.event_id)
        assert revoked is not None and revoked.revoked_at is not None
        again_revoked = await repo.revoke(user_id=user_id, event_id=hidden.event_id)
        assert again_revoked.revoked_at == revoked.revoked_at
        assert await repo.list_for_user(user_id, domain="movie", item_ids=[item]) != []  # consumed rows remain
        assert all(r.action == "consumed" for r in await repo.list_for_user(user_id, domain="movie", item_ids=[item]))

        # 8. Other user sees nothing.
        assert await repo.list_for_user(other.user.id, domain="movie") == []
    finally:
        await dispose_async_engine()
