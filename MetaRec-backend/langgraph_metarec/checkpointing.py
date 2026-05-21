from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from langgraph.checkpoint.memory import MemorySaver

from langgraph_metarec.storage_ids import safe_id


DEFAULT_BRANCH_ID = "branch-main"


def conversation_thread_id(user_id: str, conversation_id: Optional[str], branch_id: Optional[str]) -> str:
    return ":".join(
        [
            safe_id(user_id),
            safe_id(conversation_id),
            safe_id(branch_id or DEFAULT_BRANCH_ID),
        ]
    )


def task_thread_id(
    user_id: str,
    conversation_id: Optional[str],
    branch_id: Optional[str],
    task_id: str,
) -> str:
    return ":".join(
        [
            safe_id(user_id),
            safe_id(conversation_id),
            safe_id(branch_id or DEFAULT_BRANCH_ID),
            safe_id(task_id),
        ]
    )


class RuntimeCheckpointer:
    """Owns a LangGraph checkpointer instance and its backing connection."""

    def __init__(self, storage_dir: str = "graph_checkpoints", filename: str = "runtime.sqlite"):
        base_dir = Path(__file__).resolve().parents[1]
        self.storage_dir = base_dir / storage_dir
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.storage_dir / filename
        self._context_manager: Optional[Any] = None
        self._saver: Optional[Any] = None

    def get(self) -> Any:
        if self._saver is not None:
            return self._saver
        try:
            from langgraph.checkpoint.sqlite import SqliteSaver
        except Exception:
            self._saver = MemorySaver()
            return self._saver

        self._context_manager = SqliteSaver.from_conn_string(str(self.db_path))
        self._saver = self._context_manager.__enter__()
        setup = getattr(self._saver, "setup", None)
        if callable(setup):
            setup()
        return self._saver

    def close(self) -> None:
        if self._context_manager is not None:
            self._context_manager.__exit__(None, None, None)
        self._context_manager = None
        self._saver = None


_runtime_checkpointer: Optional[RuntimeCheckpointer] = None


def get_runtime_checkpointer() -> Any:
    global _runtime_checkpointer
    if _runtime_checkpointer is None:
        _runtime_checkpointer = RuntimeCheckpointer()
    return _runtime_checkpointer.get()


def reset_runtime_checkpointer() -> None:
    global _runtime_checkpointer
    if _runtime_checkpointer is not None:
        _runtime_checkpointer.close()
    _runtime_checkpointer = None
