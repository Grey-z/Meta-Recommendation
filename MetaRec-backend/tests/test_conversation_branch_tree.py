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
        assert restored["branch_selection_state"]["u-main"] == "branch-edit"


@pytest.mark.backend_unit
def test_active_branch_switch_persists_node_branch_selection_state():
    with TemporaryDirectory(prefix="metarec_branch_tree_") as tmpdir:
        storage = ConversationStorage(storage_dir=tmpdir)
        user_id = "u-selection"
        conversation = storage.create_conversation(user_id, title="Selection")
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
        assert storage.set_active_branch(user_id, conversation_id, "branch-main", "u-edit")

        restored = storage.get_full_conversation(user_id, conversation_id)

        assert restored["active_branch_id"] == "branch-main"
        assert restored["branch_selection_state"]["u-main"] == "branch-main"


@pytest.mark.backend_unit
def test_add_message_falls_back_when_parent_id_is_not_persisted():
    with TemporaryDirectory(prefix="metarec_branch_tree_") as tmpdir:
        storage = ConversationStorage(storage_dir=tmpdir)
        user_id = "u-missing-parent"
        conversation = storage.create_conversation(user_id, title="Missing Parent")
        conversation_id = conversation["id"]

        assert storage.add_message(
            user_id,
            conversation_id,
            "user",
            "request",
            {"message_id": "u-client", "branch_id": "branch-main"},
        )
        assert storage.add_message(
            user_id,
            conversation_id,
            "assistant",
            "answer",
            {
                "message_id": "a-result",
                "branch_id": "branch-main",
                "parent_message_id": "client-only-processing-id",
            },
        )

        restored = storage.get_full_conversation(user_id, conversation_id)
        by_id = {message["id"]: message for message in restored["messages"]}

        assert by_id["a-result"]["parent_message_id"] == "u-client"
        assert by_id["a-result"]["metadata"]["parent_message_id"] == "u-client"
        assert restored["branches"]["branch-main"]["head_message_id"] == "a-result"


@pytest.mark.backend_unit
def test_loading_existing_conversation_repairs_unpersisted_parent_id():
    with TemporaryDirectory(prefix="metarec_branch_tree_") as tmpdir:
        storage = ConversationStorage(storage_dir=tmpdir)
        user_id = "u-repair-parent"
        conversation = storage.create_conversation(user_id, title="Repair Parent")
        conversation_id = conversation["id"]
        timestamp = conversation["timestamp"]
        conversation["messages"] = [
            {
                "id": "u-client",
                "role": "user",
                "content": "request",
                "timestamp": timestamp,
                "branch_id": "branch-main",
                "parent_message_id": None,
                "metadata": {"message_id": "u-client", "branch_id": "branch-main"},
            },
            {
                "id": "a-result",
                "role": "assistant",
                "content": "answer",
                "timestamp": timestamp,
                "branch_id": "branch-main",
                "parent_message_id": "client-only-processing-id",
                "metadata": {
                    "message_id": "a-result",
                    "branch_id": "branch-main",
                    "parent_message_id": "client-only-processing-id",
                    "type": "recommendation",
                    "recommendation_data": {"restaurants": []},
                },
            },
        ]
        conversation["branches"]["branch-main"]["head_message_id"] = "a-result"
        assert storage._save_conversation(user_id, conversation)

        restored = storage.get_full_conversation(user_id, conversation_id)
        by_id = {message["id"]: message for message in restored["messages"]}

        assert by_id["a-result"]["parent_message_id"] == "u-client"
        assert by_id["a-result"]["metadata"]["parent_message_id"] == "u-client"
