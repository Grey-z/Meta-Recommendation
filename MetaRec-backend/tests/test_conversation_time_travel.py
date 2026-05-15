import pytest
from tempfile import TemporaryDirectory

from conversation_storage import ConversationStorage


@pytest.mark.backend_unit
def test_mark_messages_superseded_after_preserves_regenerated_branch():
    with TemporaryDirectory(prefix="metarec_time_travel_") as tmpdir:
        storage = ConversationStorage(storage_dir=tmpdir)
        user_id = "u-1"
        conversation = storage.create_conversation(user_id, title="Time Travel")
        conversation_id = conversation["id"]

        assert storage.add_message(
            user_id,
            conversation_id,
            "user",
            "old request",
            {"message_id": "m-old"},
        )
        assert storage.add_message(
            user_id,
            conversation_id,
            "assistant",
            "old confirmation",
            {"message_id": "m-old-assistant"},
        )
        assert storage.add_message(
            user_id,
            conversation_id,
            "user",
            "edited request",
            {
                "message_id": "m-new",
                "time_travel": {
                    "mode": "linear_regenerate",
                    "replay_from_message_id": "m-old",
                    "branch_id": "b-new",
                },
            },
        )

        assert storage.mark_messages_superseded_after(user_id, conversation_id, "m-old", "b-new")

        updated = storage.get_full_conversation(user_id, conversation_id)
        messages = updated["messages"]
        assert messages[1]["metadata"]["superseded"] is True
        assert messages[2]["metadata"].get("superseded") is not True
        assert messages[2]["content"] == "edited request"
