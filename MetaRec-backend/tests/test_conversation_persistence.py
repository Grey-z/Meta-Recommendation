"""DB-free coverage of the incremental conversation-persistence path.

The Postgres round-trip is covered by the DATABASE_URL-gated tests in
test_business_repositories_pg.py; these exercise the targeted-write logic (which
node gets inserted, which branch is upserted, the composite-FK head/root guard,
and the scalar update) without a database, by faking the SQLAlchemy session.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

import business_repositories as br
from business_orm import ConversationBranchORM, ConversationNodeORM, ConversationORM


class _FakeSession:
    def __init__(self, existing):
        self._existing = existing  # {(model_name, pk): obj}
        self.added = []
        self.flushed = 0

    async def get(self, model, pk):
        return self._existing.get((model.__name__, pk))

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        self.flushed += 1


class _FakeSessionScope:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *exc):
        return False


def _patch_session(monkeypatch, session):
    monkeypatch.setattr(br, "session_scope", lambda: _FakeSessionScope(session))


def _added_of(session, model):
    return [obj for obj in session.added if isinstance(obj, model)]


@pytest.mark.backend_unit
def test_node_row_from_message_maps_fields():
    repo = br.PostgresConversationRepository()
    conv_id = str(uuid.uuid4())
    node = repo._node_row_from_message(
        conv_id,
        {
            "id": "m-1",
            "role": "assistant",
            "content": "hi",
            "branch_id": "branch-main",
            "metadata": {"message_id": "m-1", "model": "fast-model"},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )
    assert node.id == "m-1"
    assert node.conversation_id == conv_id
    assert node.role == "assistant"
    assert node.content == "hi"
    assert node.branch_id == "branch-main"
    assert node.model == "fast-model"


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_upsert_branch_row_nulls_dangling_fk_pointers():
    repo = br.PostgresConversationRepository()
    conv_id = str(uuid.uuid4())
    session = _FakeSession(existing={})
    branch = {
        "id": "branch-main",
        "root_message_id": "m-1",
        "head_message_id": "missing",  # not a known node -> must be NULLed
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "metadata": {},
    }
    await repo._upsert_branch_row(session, conv_id, branch, valid_node_ids={"m-1"})
    rows = _added_of(session, ConversationBranchORM)
    assert len(rows) == 1
    assert rows[0].root_message_id == "m-1"
    assert rows[0].head_message_id is None  # dangling pointer guarded to NULL


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_persist_added_message_inserts_node_and_upserts_branch(monkeypatch):
    repo = br.PostgresConversationRepository()
    conv_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    conv_row = ConversationORM(id=conv_id, user_id=user_id, deleted_at=None)
    session = _FakeSession(existing={("ConversationORM", conv_id): conv_row})
    _patch_session(monkeypatch, session)

    now = datetime.now(timezone.utc).isoformat()
    message = {
        "id": "m-1",
        "role": "user",
        "content": "find spicy dinner",
        "branch_id": "branch-main",
        "metadata": {"message_id": "m-1", "branch_id": "branch-main"},
        "timestamp": now,
    }
    branch = {
        "id": "branch-main",
        "root_message_id": "m-1",
        "head_message_id": "m-1",
        "created_at": now,
        "updated_at": now,
        "metadata": {},
    }
    conversation = {
        "id": conv_id,
        "title": "find spicy dinner",
        "model": "Auto",
        "last_message": "find spicy dinner",
        "active_branch_id": "branch-main",
        "branch_selection_state": {},
        "preferences": {},
        "metadata": {},
        "messages": [message],
        "branches": {"branch-main": branch},
    }

    assert await repo._persist_added_message(user_id, conversation, message, branch) is True

    nodes = _added_of(session, ConversationNodeORM)
    branches = _added_of(session, ConversationBranchORM)
    assert [n.id for n in nodes] == ["m-1"]
    assert session.flushed >= 1  # node flushed before the branch FK references it
    assert len(branches) == 1
    assert branches[0].head_message_id == "m-1"
    assert branches[0].root_message_id == "m-1"
    # Conversation scalars updated in place (no tree rewrite).
    assert conv_row.last_message == "find spicy dinner"
    assert conv_row.active_branch_id == "branch-main"


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_persist_added_message_skips_reinsert_of_existing_node(monkeypatch):
    repo = br.PostgresConversationRepository()
    conv_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    conv_row = ConversationORM(id=conv_id, user_id=user_id, deleted_at=None)
    existing_node = ConversationNodeORM(id="m-1", conversation_id=conv_id, role="user", content="x")
    session = _FakeSession(
        existing={
            ("ConversationORM", conv_id): conv_row,
            ("ConversationNodeORM", ("m-1", conv_id)): existing_node,
        }
    )
    _patch_session(monkeypatch, session)

    now = datetime.now(timezone.utc).isoformat()
    message = {"id": "m-1", "role": "user", "content": "x", "branch_id": "branch-main",
               "metadata": {"message_id": "m-1"}, "timestamp": now}
    branch = {"id": "branch-main", "root_message_id": "m-1", "head_message_id": "m-1",
              "created_at": now, "updated_at": now, "metadata": {}}
    conversation = {
        "id": conv_id, "title": "t", "model": "Auto", "last_message": "x",
        "active_branch_id": "branch-main", "branch_selection_state": {}, "preferences": {},
        "metadata": {}, "messages": [message], "branches": {"branch-main": branch},
    }

    assert await repo._persist_added_message(user_id, conversation, message, branch) is True
    # Existing node is not re-inserted (idempotent re-add).
    assert _added_of(session, ConversationNodeORM) == []
