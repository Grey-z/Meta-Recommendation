"""Path-safety contract for storage identifiers.

``safe_id`` is the single sanitizer every disk-touching id passes through
(LangGraph checkpoint scopes, debug traces). The file-based conversation/task/
profile stores it used to guard were replaced by the Postgres repositories.
"""
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from conversation_tree import ConversationTree
from langgraph_metarec.storage_ids import safe_id


@pytest.mark.runtime_contract
def test_safe_id_normalizes_path_like_values():
    assert safe_id("../escape") == "___escape"
    assert safe_id("user:conversation/branch") == "user_conversation_branch"
    assert safe_id("") == "default"


@pytest.mark.runtime_contract
def test_safe_id_result_never_escapes_a_root_directory():
    with TemporaryDirectory(prefix="metarec_safe_id_") as tmpdir:
        root = Path(tmpdir)
        for hostile in ("../escape-user", "..\\escape-user", "a/../../b", "..", "C:\\evil"):
            resolved = (root / safe_id(hostile)).resolve()
            assert resolved.is_relative_to(root.resolve())
            assert ".." not in resolved.name


@pytest.mark.backend_unit
def test_postgres_conversation_repository_uses_pure_tree_helper():
    from business_repositories import PostgresConversationRepository

    repository = PostgresConversationRepository()
    assert isinstance(repository._tree, ConversationTree)
