from __future__ import annotations

import asyncio
from inspect import isawaitable
import os
import sys
from typing import Any, Optional

from langgraph.checkpoint.memory import MemorySaver

from langgraph_metarec.storage_ids import safe_id


DEFAULT_BRANCH_ID = "branch-main"


def _configure_windows_event_loop_policy_for_psycopg() -> None:
    if sys.platform != "win32":
        return
    selector_policy = getattr(asyncio, "WindowsSelectorEventLoopPolicy", None)
    proactor_policy = getattr(asyncio, "WindowsProactorEventLoopPolicy", None)
    if selector_policy is None:
        return
    current_policy = asyncio.get_event_loop_policy()
    if proactor_policy is None or isinstance(current_policy, proactor_policy):
        asyncio.set_event_loop_policy(selector_policy())


_configure_windows_event_loop_policy_for_psycopg()


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

    def __init__(self, conn_string: Optional[str] = None, backend: Optional[str] = None):
        self.backend = (backend or os.getenv("METAREC_CHECKPOINTER_BACKEND", "postgres")).strip().lower()
        self.conn_string = conn_string or os.getenv("DATABASE_URL")
        self._context_manager: Optional[Any] = None
        self._saver: Optional[Any] = None
        self._async_context_manager: Optional[Any] = None
        self._async_saver: Optional[Any] = None
        self._memory_saver: Optional[MemorySaver] = None

    def _require_postgres_conn_string(self) -> str:
        if not self.conn_string:
            raise RuntimeError(
                "DATABASE_URL is required for the Postgres LangGraph checkpointer. "
                "Set METAREC_CHECKPOINTER_BACKEND=memory only for tests."
            )
        return self.conn_string

    def _get_memory_saver(self) -> MemorySaver:
        if self._memory_saver is None:
            self._memory_saver = MemorySaver()
        return self._memory_saver

    def get(self) -> Any:
        if self._saver is not None:
            return self._saver
        if self.backend == "memory":
            self._saver = self._get_memory_saver()
            return self._saver
        if self.backend != "postgres":
            raise RuntimeError(f"Unsupported METAREC_CHECKPOINTER_BACKEND: {self.backend}")
        conn_string = self._require_postgres_conn_string()

        from langgraph.checkpoint.postgres import PostgresSaver

        self._context_manager = PostgresSaver.from_conn_string(conn_string)
        self._saver = self._context_manager.__enter__()
        setup = getattr(self._saver, "setup", None)
        if callable(setup):
            setup()
        return self._saver

    async def aget(self) -> Any:
        if self._async_saver is not None:
            return self._async_saver
        if self.backend == "memory":
            self._async_saver = self._get_memory_saver()
            return self._async_saver
        if self.backend != "postgres":
            raise RuntimeError(f"Unsupported METAREC_CHECKPOINTER_BACKEND: {self.backend}")
        conn_string = self._require_postgres_conn_string()

        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        self._async_context_manager = AsyncPostgresSaver.from_conn_string(conn_string)
        self._async_saver = await self._async_context_manager.__aenter__()
        setup = getattr(self._async_saver, "setup", None)
        if callable(setup):
            result = setup()
            if isawaitable(result):
                await result
        return self._async_saver

    def close(self) -> None:
        if self._context_manager is not None:
            self._context_manager.__exit__(None, None, None)
        self._context_manager = None
        self._saver = None

    async def aclose(self) -> None:
        if self._async_context_manager is not None:
            await self._async_context_manager.__aexit__(None, None, None)
        self._async_context_manager = None
        self._async_saver = None
