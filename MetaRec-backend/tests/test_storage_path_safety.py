from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from conversation_storage import ConversationStorage
from feedback_storage import FeedbackStorage
from langgraph_metarec.storage_ids import safe_id
from result_storage import ResultStorage
from task_storage import TaskStorage
from user_profile_storage import UserProfileStorage


def _assert_inside(path: str | Path, root: Path) -> None:
    assert Path(path).resolve().is_relative_to(root.resolve())


@pytest.mark.runtime_contract
def test_safe_id_normalizes_path_like_values():
    assert safe_id("../escape") == "___escape"
    assert safe_id("user:conversation/branch") == "user_conversation_branch"
    assert safe_id("") == "default"


@pytest.mark.runtime_contract
def test_conversation_storage_sanitizes_user_and_conversation_ids():
    with TemporaryDirectory(prefix="metarec_conversation_safety_") as tmpdir:
        root = Path(tmpdir)
        storage = ConversationStorage(storage_dir=tmpdir)
        user_id = "../escape-user"
        conversation_id = "../escape-conversation"

        user_dir = storage._get_user_dir(user_id)
        conversation_file = storage._get_conversation_file(user_id, conversation_id)

        _assert_inside(user_dir, root)
        _assert_inside(conversation_file, root)
        assert ".." not in user_dir.name
        assert ".." not in conversation_file.name


@pytest.mark.runtime_contract
def test_user_profile_storage_sanitizes_user_id():
    with TemporaryDirectory(prefix="metarec_profile_safety_") as tmpdir:
        root = Path(tmpdir)
        storage = UserProfileStorage(storage_dir=tmpdir)
        user_id = "../escape-profile"

        profile_path = storage._get_profile_path(user_id)
        profile = storage.get_default_profile()

        assert storage.save_user_profile(user_id, profile) is True
        _assert_inside(profile_path, root)
        assert Path(profile_path).exists()
        assert not (root.parent / "escape-profile.json").exists()


@pytest.mark.runtime_contract
def test_task_storage_sanitizes_scope_parts():
    with TemporaryDirectory(prefix="metarec_task_safety_") as tmpdir:
        root = Path(tmpdir)
        storage = TaskStorage(storage_dir=tmpdir)
        path = storage._task_path("../escape-user", "../escape-conversation", "../escape-task")

        _assert_inside(path, root)
        assert path.name.endswith(".json")
        assert ".." not in str(path.relative_to(root))


@pytest.mark.runtime_contract
def test_result_storage_sanitizes_scope_parts():
    with TemporaryDirectory(prefix="metarec_result_safety_") as tmpdir:
        root = Path(tmpdir)
        storage = ResultStorage(storage_dir=tmpdir)
        path = storage._result_path("../escape-user", "../escape-conversation", "../escape-branch", "../escape-result")

        assert storage.save("../escape-user", "../escape-conversation", "../escape-branch", "../escape-result", {"ok": True})
        _assert_inside(path, root)
        assert path.name.endswith(".json")
        assert ".." not in str(path.relative_to(root))


@pytest.mark.runtime_contract
def test_feedback_storage_sanitizes_scope_parts():
    with TemporaryDirectory(prefix="metarec_feedback_safety_") as tmpdir:
        root = Path(tmpdir)
        storage = FeedbackStorage(storage_dir=tmpdir)
        path = storage._feedback_path("../escape-user", "../escape-conversation", "../escape-branch", "../escape-feedback")

        assert storage.save("../escape-user", "../escape-conversation", "../escape-branch", "../escape-feedback", {"label": "good"})
        _assert_inside(path, root)
        assert path.name.endswith(".json")
        assert ".." not in str(path.relative_to(root))
