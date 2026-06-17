"""Branch-tree contract tests for the live conversation persistence path.

These used to drive the file-based ``ConversationStorage`` facade, which the
application no longer uses for conversation persistence (``main.py`` goes through
``PostgresConversationRepository``). They now exercise the Postgres repository
directly so they validate the branch-tree behavior that actually ships. The
repository reuses the pure ``ConversationTree`` helpers, so the same invariants
are asserted — just against the real storage path.

Requires ``DATABASE_URL`` (skipped otherwise), like the other Postgres contract
tests in ``test_business_repositories_pg.py``.
"""

from __future__ import annotations

import os
import uuid

import pytest


@pytest.mark.runtime_contract
@pytest.mark.asyncio
async def test_postgres_branch_fork_without_parent_uses_revised_message_parent():
    if not os.getenv("DATABASE_URL"):
        pytest.skip("DATABASE_URL is required for the Postgres branch-tree contract test")

    from business_db import dispose_async_engine
    from business_repositories import auth_repository, conversation_repository

    suffix = uuid.uuid4().hex

    try:
        auth = await auth_repository.get_or_create_guest(device_id=f"pytest-fork-{suffix}")
        user_id = auth.user.id

        conversation = await conversation_repository.create_conversation(user_id, title="Fork")
        conversation_id = conversation["id"]

        assert await conversation_repository.add_message(
            user_id, conversation_id, "user", "original request",
            metadata={"message_id": "u-main"},
        )
        assert await conversation_repository.add_message(
            user_id, conversation_id, "assistant", "original answer",
            metadata={"message_id": "a-main"},
        )
        # Edit u-main into a new branch without supplying a parent: the fork must
        # inherit the revised message's parent (None here) rather than dangling.
        assert await conversation_repository.add_message(
            user_id, conversation_id, "user", "edited request",
            metadata={
                "message_id": "u-edit",
                "branch_id": "branch-edit",
                "fork_from_message_id": "u-main",
                "revision_of_message_id": "u-main",
            },
        )
        assert await conversation_repository.add_message(
            user_id, conversation_id, "assistant", "edited answer",
            metadata={"message_id": "a-edit", "branch_id": "branch-edit"},
        )

        restored = await conversation_repository.get_full_conversation(user_id, conversation_id)
        by_id = {message["id"]: message for message in restored["messages"]}

        assert by_id["u-edit"]["parent_message_id"] is None
        assert by_id["a-edit"]["parent_message_id"] == "u-edit"
        assert restored["branches"]["branch-main"]["head_message_id"] == "a-main"
        assert restored["branches"]["branch-edit"]["head_message_id"] == "a-edit"
        assert restored["branch_selection_state"]["u-main"] == "branch-edit"
    finally:
        await dispose_async_engine()


@pytest.mark.runtime_contract
@pytest.mark.asyncio
async def test_postgres_active_branch_switch_persists_branch_selection_state():
    if not os.getenv("DATABASE_URL"):
        pytest.skip("DATABASE_URL is required for the Postgres branch-tree contract test")

    from business_db import dispose_async_engine
    from business_repositories import auth_repository, conversation_repository

    suffix = uuid.uuid4().hex

    try:
        auth = await auth_repository.get_or_create_guest(device_id=f"pytest-switch-{suffix}")
        user_id = auth.user.id

        conversation = await conversation_repository.create_conversation(user_id, title="Selection")
        conversation_id = conversation["id"]

        assert await conversation_repository.add_message(
            user_id, conversation_id, "user", "original request",
            metadata={"message_id": "u-main"},
        )
        assert await conversation_repository.add_message(
            user_id, conversation_id, "assistant", "original answer",
            metadata={"message_id": "a-main"},
        )
        assert await conversation_repository.add_message(
            user_id, conversation_id, "user", "edited request",
            metadata={
                "message_id": "u-edit",
                "branch_id": "branch-edit",
                "fork_from_message_id": "u-main",
                "revision_of_message_id": "u-main",
            },
        )
        assert await conversation_repository.add_message(
            user_id, conversation_id, "assistant", "edited answer",
            metadata={"message_id": "a-edit", "branch_id": "branch-edit"},
        )

        # Switching back to main must record the per-fork selection so a reload
        # reopens the branch the user chose.
        assert await conversation_repository.set_active_branch(
            user_id, conversation_id, "branch-main", "u-edit"
        )

        restored = await conversation_repository.get_full_conversation(user_id, conversation_id)

        assert restored["active_branch_id"] == "branch-main"
        assert restored["branch_selection_state"]["u-main"] == "branch-main"
    finally:
        await dispose_async_engine()


@pytest.mark.runtime_contract
@pytest.mark.asyncio
async def test_postgres_add_message_falls_back_when_parent_id_is_not_persisted():
    if not os.getenv("DATABASE_URL"):
        pytest.skip("DATABASE_URL is required for the Postgres branch-tree contract test")

    from business_db import dispose_async_engine
    from business_repositories import auth_repository, conversation_repository

    suffix = uuid.uuid4().hex

    try:
        auth = await auth_repository.get_or_create_guest(device_id=f"pytest-parent-{suffix}")
        user_id = auth.user.id

        conversation = await conversation_repository.create_conversation(user_id, title="Missing Parent")
        conversation_id = conversation["id"]

        assert await conversation_repository.add_message(
            user_id, conversation_id, "user", "request",
            metadata={"message_id": "u-client", "branch_id": "branch-main"},
        )
        # The client sends a parent id that was never persisted (a transient
        # processing-view id). The repository must fall back to the branch head.
        assert await conversation_repository.add_message(
            user_id, conversation_id, "assistant", "answer",
            metadata={
                "message_id": "a-result",
                "branch_id": "branch-main",
                "parent_message_id": "client-only-processing-id",
            },
        )

        restored = await conversation_repository.get_full_conversation(user_id, conversation_id)
        by_id = {message["id"]: message for message in restored["messages"]}

        assert by_id["a-result"]["parent_message_id"] == "u-client"
        assert by_id["a-result"]["metadata"]["parent_message_id"] == "u-client"
        assert restored["branches"]["branch-main"]["head_message_id"] == "a-result"
    finally:
        await dispose_async_engine()
