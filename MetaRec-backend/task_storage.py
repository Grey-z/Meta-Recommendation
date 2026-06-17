from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from langgraph_metarec.storage_ids import safe_id


class TaskStorage:
    """File-backed task status storage scoped by user and conversation."""

    def __init__(self, storage_dir: str = "tasks"):
        base_dir = Path(__file__).parent
        self.storage_dir = base_dir / storage_dir
        self.storage_dir.mkdir(exist_ok=True)

    def _task_path(
        self,
        user_id: str,
        conversation_id: Optional[str],
        task_id: str,
        *,
        create_dirs: bool = False,
    ) -> Path:
        user_part = safe_id(user_id)
        conversation_part = safe_id(conversation_id)
        task_part = safe_id(task_id)
        task_dir = self.storage_dir / user_part / conversation_part
        if create_dirs:
            task_dir.mkdir(parents=True, exist_ok=True)
        return task_dir / f"{task_part}.json"

    def _to_jsonable(self, value: Any) -> Any:
        if hasattr(value, "model_dump"):
            return value.model_dump()
        if hasattr(value, "dict"):
            return value.dict()
        if isinstance(value, dict):
            return {key: self._to_jsonable(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._to_jsonable(item) for item in value]
        return value

    def save(
        self,
        user_id: str,
        conversation_id: Optional[str],
        task_id: str,
        status: Dict[str, Any],
    ) -> bool:
        payload = self._to_jsonable(status)
        payload.setdefault("task_id", task_id)
        payload.setdefault("user_id", user_id)
        payload.setdefault("conversation_id", conversation_id or "default")
        payload["updated_at"] = datetime.now().isoformat()
        path = self._task_path(user_id, conversation_id, task_id, create_dirs=True)
        try:
            with open(path, "w", encoding="utf-8") as file:
                json.dump(payload, file, ensure_ascii=False, indent=2)
            return True
        except Exception as exc:
            print(f"Error saving task {task_id}: {exc}")
            return False

    def load(
        self,
        user_id: str,
        conversation_id: Optional[str],
        task_id: str,
    ) -> Optional[Dict[str, Any]]:
        path = self._task_path(user_id, conversation_id, task_id)
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as file:
                payload = json.load(file)
            return payload if isinstance(payload, dict) else None
        except Exception as exc:
            print(f"Error loading task {task_id}: {exc}")
            return None


_task_storage_instance: Optional[TaskStorage] = None


def get_task_storage() -> TaskStorage:
    global _task_storage_instance
    if _task_storage_instance is None:
        _task_storage_instance = TaskStorage()
    return _task_storage_instance
