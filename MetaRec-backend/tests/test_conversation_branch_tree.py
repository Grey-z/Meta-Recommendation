import pytest
from tempfile import TemporaryDirectory

from conversation_storage import ConversationStorage


@pytest.mark.backend_unit
def test_legacy_messages_stay_on_main_branch_when_active_branch_changes():
    with TemporaryDirectory(prefix="metarec_branch_tree_") as tmpdir:
        storage = ConversationStorage(storage_dir=tmpdir)
        user_id = "u-legacy"
        conversation = storage.create_conversation(user_id, title="Legacy")
        conversation_id = conversation["id"]

        conversation["active_branch_id"] = "branch-edit"
        conversation["branches"]["branch-edit"] = {
            "id": "branch-edit",
            "parent_branch_id": "branch-main",
            "fork_from_message_id": "u-1",
            "root_message_id": None,
            "head_message_id": None,
            "title": "Edit",
            "created_at": conversation["timestamp"],
            "updated_at": conversation["timestamp"],
        }
        conversation["messages"] = [
            {
                "id": "u-1",
                "role": "user",
                "content": "legacy request",
                "timestamp": conversation["timestamp"],
                "metadata": {"message_id": "u-1"},
            },
            {
                "id": "a-1",
                "role": "assistant",
                "content": "legacy answer",
                "timestamp": conversation["timestamp"],
                "metadata": {"message_id": "a-1"},
            },
        ]
        assert storage._save_conversation(user_id, conversation)

        restored = storage.get_full_conversation(user_id, conversation_id)

        assert [message["branch_id"] for message in restored["messages"]] == [
            "branch-main",
            "branch-main",
        ]
        assert restored["branches"]["branch-main"]["head_message_id"] == "a-1"
        assert restored["active_branch_id"] == "branch-main"


@pytest.mark.backend_unit
def test_branch_fork_without_parent_uses_revised_message_parent():
    with TemporaryDirectory(prefix="metarec_branch_tree_") as tmpdir:
        storage = ConversationStorage(storage_dir=tmpdir)
        user_id = "u-fork"
        conversation = storage.create_conversation(user_id, title="Fork")
        conversation_id = conversation["id"]

        assert storage.add_message(
            user_id,
            conversation_id,
            "user",
            "original request",
            {"message_id": "u-main"},
        )
        assert storage.add_message(
            user_id,
            conversation_id,
            "assistant",
            "original answer",
            {"message_id": "a-main"},
        )
        assert storage.add_message(
            user_id,
            conversation_id,
            "user",
            "edited request",
            {
                "message_id": "u-edit",
                "branch_id": "branch-edit",
                "fork_from_message_id": "u-main",
                "revision_of_message_id": "u-main",
            },
        )
        assert storage.add_message(
            user_id,
            conversation_id,
            "assistant",
            "edited answer",
            {"message_id": "a-edit", "branch_id": "branch-edit"},
        )

        restored = storage.get_full_conversation(user_id, conversation_id)
        by_id = {message["id"]: message for message in restored["messages"]}

        assert by_id["u-edit"]["parent_message_id"] is None
        assert by_id["a-edit"]["parent_message_id"] == "u-edit"
        assert restored["branches"]["branch-main"]["head_message_id"] == "a-main"
        assert restored["branches"]["branch-edit"]["head_message_id"] == "a-edit"
