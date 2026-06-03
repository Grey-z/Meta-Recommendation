"""Time-travel (supersede) contract test for the live conversation path.

Retargeted from the file-based ``ConversationStorage`` facade onto the Postgres
repository that the application actually uses. Requires ``DATABASE_URL``.
"""

from __future__ import annotations

import os
import uuid

import pytest


@pytest.mark.runtime_contract
@pytest.mark.asyncio
async def test_postgres_mark_messages_superseded_after_preserves_regenerated_branch():
    if not os.getenv("DATABASE_URL"):
        pytest.skip("DATABASE_URL is required for the Postgres time-travel contract test")

    from business_db import dispose_async_engine
    from business_repositories import auth_repository, conversation_repository

    suffix = uuid.uuid4().hex

    try:
        auth = await auth_repository.get_or_create_guest(device_id=f"pytest-timetravel-{suffix}")
        user_id = auth.user.id

        conversation = await conversation_repository.create_conversation(user_id, title="Time Travel")
        conversation_id = conversation["id"]

        assert await conversation_repository.add_message(
            user_id, conversation_id, "user", "old request",
            metadata={"message_id": "m-old"},
        )
        assert await conversation_repository.add_message(
            user_id, conversation_id, "assistant", "old confirmation",
            metadata={"message_id": "m-old-assistant"},
        )
        assert await conversation_repository.add_message(
            user_id, conversation_id, "user", "edited request",
            metadata={
                "message_id": "m-new",
                "time_travel": {
                    "mode": "linear_regenerate",
                    "replay_from_message_id": "m-old",
                    "branch_id": "b-new",
                },
            },
        )

        # Supersede everything after m-old except the freshly regenerated branch.
        assert await conversation_repository.mark_messages_superseded_after(
            user_id, conversation_id, "m-old", "b-new"
        )

        restored = await conversation_repository.get_full_conversation(user_id, conversation_id)
        by_id = {message["id"]: message for message in restored["messages"]}

        assert by_id["m-old-assistant"]["metadata"]["superseded"] is True
        assert by_id["m-new"]["metadata"].get("superseded") is not True
        assert by_id["m-new"]["content"] == "edited request"
    finally:
        await dispose_async_engine()
