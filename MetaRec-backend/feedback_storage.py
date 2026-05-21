from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from langgraph_metarec.storage_ids import safe_id


class FeedbackStorage:
    """File-backed feedback storage scoped by conversation branch."""

    def __init__(self, storage_dir: str = "feedback"):
        base_dir = Path(__file__).parent
        self.storage_dir = base_dir / storage_dir
        self.storage_dir.mkdir(exist_ok=True)

    def _feedback_path(
        self,
        user_id: str,
        conversation_id: Optional[str],
        branch_id: Optional[str],
        feedback_id: str,
    ) -> Path:
        feedback_dir = self.storage_dir / safe_id(user_id) / safe_id(conversation_id) / safe_id(branch_id)
        feedback_dir.mkdir(parents=True, exist_ok=True)
        return feedback_dir / f"{safe_id(feedback_id)}.json"

    def save(
        self,
        user_id: str,
        conversation_id: Optional[str],
        branch_id: Optional[str],
        feedback_id: str,
        payload: Dict[str, Any],
    ) -> bool:
        data = dict(payload)
        data.setdefault("feedback_id", feedback_id)
        data.setdefault("user_id", user_id)
        data.setdefault("conversation_id", conversation_id or "default")
        data.setdefault("branch_id", branch_id or "default")
        data["updated_at"] = datetime.now().isoformat()
        try:
            with open(self._feedback_path(user_id, conversation_id, branch_id, feedback_id), "w", encoding="utf-8") as file:
                json.dump(data, file, ensure_ascii=False, indent=2)
            return True
        except Exception as exc:
            print(f"Error saving feedback {feedback_id}: {exc}")
            return False

    def load(
        self,
        user_id: str,
        conversation_id: Optional[str],
        branch_id: Optional[str],
        feedback_id: str,
    ) -> Optional[Dict[str, Any]]:
        path = self._feedback_path(user_id, conversation_id, branch_id, feedback_id)
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as file:
                payload = json.load(file)
            return payload if isinstance(payload, dict) else None
        except Exception as exc:
            print(f"Error loading feedback {feedback_id}: {exc}")
            return None
