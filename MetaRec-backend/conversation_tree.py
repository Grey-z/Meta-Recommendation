from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional


class ConversationTree:
    """Pure branch-tree normalization helpers shared by DB and file storage."""

    MAIN_BRANCH_ID = "branch-main"

    def _new_branch(
        self,
        branch_id: str,
        *,
        parent_branch_id: Optional[str] = None,
        fork_from_message_id: Optional[str] = None,
        root_message_id: Optional[str] = None,
        head_message_id: Optional[str] = None,
        title: Optional[str] = None,
        created_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        now = created_at or datetime.now().isoformat()
        return {
            "id": branch_id,
            "parent_branch_id": parent_branch_id,
            "fork_from_message_id": fork_from_message_id,
            "root_message_id": root_message_id,
            "head_message_id": head_message_id,
            "title": title or ("Main" if branch_id == self.MAIN_BRANCH_ID else "Branch"),
            "created_at": now,
            "updated_at": now,
        }

    def _message_id(self, message: Dict[str, Any]) -> str:
        metadata = message.setdefault("metadata", {})
        message_id = message.get("id") or metadata.get("message_id") or str(uuid.uuid4())
        message["id"] = message_id
        metadata.setdefault("message_id", message_id)
        return message_id

    def _extract_branch_id(self, message: Dict[str, Any], fallback: str) -> str:
        metadata = message.setdefault("metadata", {})
        time_travel = metadata.get("time_travel") if isinstance(metadata.get("time_travel"), dict) else {}
        return (
            message.get("branch_id")
            or metadata.get("branch_id")
            or time_travel.get("branch_id")
            or fallback
            or self.MAIN_BRANCH_ID
        )

    def _message_lookup(self, messages: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        return {
            message_id: message
            for message in messages
            if (message_id := (message.get("id") or message.get("metadata", {}).get("message_id")))
        }

    def _revision_source_id(self, message: Dict[str, Any]) -> Optional[str]:
        metadata = message.get("metadata", {}) if isinstance(message.get("metadata"), dict) else {}
        time_travel = metadata.get("time_travel") if isinstance(metadata.get("time_travel"), dict) else {}
        return (
            message.get("revision_of_message_id")
            or message.get("fork_from_message_id")
            or metadata.get("revision_of_message_id")
            or metadata.get("fork_from_message_id")
            or time_travel.get("replay_from_message_id")
        )

    def _canonical_revision_root_id(
        self,
        message_id: Optional[str],
        message_by_id: Dict[str, Dict[str, Any]],
    ) -> Optional[str]:
        if not message_id:
            return None
        current_id = message_id
        seen = set()
        while current_id and current_id not in seen:
            seen.add(current_id)
            message = message_by_id.get(current_id)
            if not message:
                return current_id
            source_id = self._revision_source_id(message)
            if not source_id:
                return message.get("id") or message.get("metadata", {}).get("message_id") or current_id
            current_id = source_id
        return current_id

    def _branch_revision_root_id(
        self,
        branch: Dict[str, Any],
        message_by_id: Dict[str, Dict[str, Any]],
    ) -> Optional[str]:
        return self._canonical_revision_root_id(
            branch.get("fork_from_message_id") or branch.get("root_message_id"),
            message_by_id,
        )

    def _normalize_branch_selection_state(
        self,
        conversation: Dict[str, Any],
        message_by_id: Dict[str, Dict[str, Any]],
    ) -> Dict[str, str]:
        branches = conversation.get("branches", {})
        raw_state = conversation.get("branch_selection_state")
        if not isinstance(raw_state, dict):
            raw_state = {}

        normalized: Dict[str, str] = {}
        for source_message_id, selected_branch_id in raw_state.items():
            if not isinstance(source_message_id, str) or not isinstance(selected_branch_id, str):
                continue
            if selected_branch_id not in branches:
                continue
            root_id = self._canonical_revision_root_id(source_message_id, message_by_id)
            if root_id:
                normalized[root_id] = selected_branch_id
        conversation["branch_selection_state"] = normalized
        return normalized

    def _ensure_tree_metadata(self, conversation: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize legacy linear conversations into a branch-tree shape."""
        now = datetime.now().isoformat()
        messages = conversation.setdefault("messages", [])
        branches = conversation.get("branches")
        if not isinstance(branches, dict):
            branches = {}
            conversation["branches"] = branches

        branches.setdefault(
            self.MAIN_BRANCH_ID,
            self._new_branch(
                self.MAIN_BRANCH_ID,
                created_at=conversation.get("timestamp") or now,
            ),
        )

        message_by_id: Dict[str, Dict[str, Any]] = {}
        previous_by_branch: Dict[str, Optional[str]] = {}

        for message in messages:
            message_id = self._message_id(message)
            message_by_id[message_id] = message

            branch_id = self._extract_branch_id(
                message,
                self.MAIN_BRANCH_ID,
            )
            metadata = message.setdefault("metadata", {})
            time_travel = metadata.get("time_travel") if isinstance(metadata.get("time_travel"), dict) else {}
            replay_from = (
                message.get("fork_from_message_id")
                or metadata.get("fork_from_message_id")
                or time_travel.get("replay_from_message_id")
            )

            if branch_id not in branches:
                parent_branch_id = None
                if replay_from and replay_from in message_by_id:
                    parent_branch_id = message_by_id[replay_from].get("branch_id")
                branches[branch_id] = self._new_branch(
                    branch_id,
                    parent_branch_id=parent_branch_id or self.MAIN_BRANCH_ID,
                    fork_from_message_id=replay_from,
                    created_at=message.get("timestamp") or now,
                )

            parent_message_id = (
                message.get("parent_message_id")
                or metadata.get("parent_message_id")
            )
            if not parent_message_id:
                if replay_from and replay_from in message_by_id:
                    parent_message_id = message_by_id[replay_from].get("parent_message_id")
                else:
                    parent_message_id = previous_by_branch.get(branch_id)
            if parent_message_id and (parent_message_id == message_id or parent_message_id not in message_by_id):
                parent_message_id = previous_by_branch.get(branch_id)

            message["branch_id"] = branch_id
            message["parent_message_id"] = parent_message_id
            if replay_from:
                message["fork_from_message_id"] = replay_from
                message.setdefault("revision_of_message_id", replay_from)
                branches[branch_id]["fork_from_message_id"] = replay_from
            metadata["branch_id"] = branch_id
            if parent_message_id:
                metadata["parent_message_id"] = parent_message_id

            branch = branches[branch_id]
            branch.setdefault("root_message_id", message_id)
            if not branch.get("root_message_id"):
                branch["root_message_id"] = message_id
            if not metadata.get("superseded"):
                branch["head_message_id"] = message_id
                branch["updated_at"] = message.get("timestamp") or now
            previous_by_branch[branch_id] = message_id

        active_branch_id = conversation.get("active_branch_id")
        if (
            not active_branch_id
            or active_branch_id not in branches
            or not branches.get(active_branch_id, {}).get("head_message_id")
        ):
            active_branch_id = self.MAIN_BRANCH_ID
            for message in reversed(messages):
                if not message.get("metadata", {}).get("superseded"):
                    active_branch_id = message.get("branch_id") or self.MAIN_BRANCH_ID
                    break
        conversation["active_branch_id"] = active_branch_id
        self._normalize_branch_selection_state(conversation, message_by_id)

        active_head = branches.get(active_branch_id, {}).get("head_message_id")
        if active_head:
            conversation["last_message"] = message_by_id.get(active_head, {}).get(
                "content", conversation.get("last_message", "")
            )[:100]
        return conversation
