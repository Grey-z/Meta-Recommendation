"""
对话历史存储模块
负责用户对话历史的持久化存储和管理
"""
import json
import os
from typing import List, Dict, Any, Optional
from datetime import datetime
from pathlib import Path
import uuid


class ConversationStorage:
    """对话历史存储管理器"""

    MAIN_BRANCH_ID = "branch-main"
    
    def __init__(self, storage_dir: str = "conversations"):
        """
        初始化存储管理器
        
        Args:
            storage_dir: 存储目录路径（相对于当前文件）
        """
        # 获取存储目录的绝对路径
        base_dir = Path(__file__).parent
        self.storage_dir = base_dir / storage_dir
        self.storage_dir.mkdir(exist_ok=True)
    
    def _get_user_dir(self, user_id: str) -> Path:
        """获取用户的存储目录"""
        user_dir = self.storage_dir / self._safe_part(user_id)
        user_dir.mkdir(exist_ok=True)
        return user_dir
    
    def _get_conversation_file(self, user_id: str, conversation_id: str) -> Path:
        """获取对话文件的路径"""
        return self._get_user_dir(user_id) / f"{self._safe_part(conversation_id)}.json"

    def _safe_part(self, value: Optional[str], fallback: str = "default") -> str:
        raw = str(value or fallback).strip() or fallback
        return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in raw)[:160]
    
    def _load_conversation(self, user_id: str, conversation_id: str) -> Optional[Dict[str, Any]]:
        """加载单个对话"""
        file_path = self._get_conversation_file(user_id, conversation_id)
        if not file_path.exists():
            return None
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                conversation = json.load(f)
            return self._ensure_tree_metadata(conversation)
        except Exception as e:
            print(f"Error loading conversation {conversation_id} for user {user_id}: {e}")
            return None

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

        active_head = branches.get(active_branch_id, {}).get("head_message_id")
        if active_head:
            conversation["last_message"] = message_by_id.get(active_head, {}).get("content", conversation.get("last_message", ""))[:100]
        return conversation
    
    def _save_conversation(self, user_id: str, conversation: Dict[str, Any]) -> bool:
        """保存对话"""
        conversation_id = conversation.get('id')
        if not conversation_id:
            return False
        
        file_path = self._get_conversation_file(user_id, conversation_id)
        
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(conversation, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"Error saving conversation {conversation_id} for user {user_id}: {e}")
            return False
    
    def create_conversation(
        self, 
        user_id: str, 
        title: Optional[str] = None,
        model: str = "Auto"
    ) -> Dict[str, Any]:
        """
        创建新对话
        
        Args:
            user_id: 用户ID
            title: 对话标题（可选）
            model: 使用的模型名称
            
        Returns:
            创建的对话对象
        """
        conversation_id = str(uuid.uuid4())
        now = datetime.now().isoformat()
        
        conversation = {
            "id": conversation_id,
            "user_id": user_id,
            "title": title or "New Chat",
            "model": model,
            "last_message": "Start a new conversation...",
            "timestamp": now,
            "updated_at": now,
            "active_branch_id": self.MAIN_BRANCH_ID,
            "branches": {
                self.MAIN_BRANCH_ID: self._new_branch(
                    self.MAIN_BRANCH_ID,
                    created_at=now,
                )
            },
            "messages": [],
            "preferences": {}  # 初始化空的偏好设置
        }
        
        if self._save_conversation(user_id, conversation):
            return conversation
        else:
            raise Exception("Failed to create conversation")
    
    def get_conversation(self, user_id: str, conversation_id: str) -> Optional[Dict[str, Any]]:
        """
        获取单个对话
        
        Args:
            user_id: 用户ID
            conversation_id: 对话ID
            
        Returns:
            对话对象，如果不存在返回None
        """
        return self._load_conversation(user_id, conversation_id)
    
    def get_all_conversations(self, user_id: str) -> List[Dict[str, Any]]:
        """
        获取用户的所有对话列表（只包含摘要信息）
        
        Args:
            user_id: 用户ID
            
        Returns:
            对话列表（按更新时间倒序）
        """
        user_dir = self._get_user_dir(user_id)
        conversations = []
        
        if not user_dir.exists():
            return conversations
        
        for file_path in user_dir.glob("*.json"):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    conv = json.load(f)
                    # 只返回摘要信息，不包含完整消息列表（为了性能）
                    conversations.append({
                        "id": conv.get("id"),
                        "title": conv.get("title", "Untitled"),
                        "model": conv.get("model", "Auto"),
                        "last_message": conv.get("last_message", ""),
                        "timestamp": conv.get("timestamp"),
                        "updated_at": conv.get("updated_at", conv.get("timestamp")),
                        "message_count": len(conv.get("messages", []))
                    })
            except Exception as e:
                print(f"Error loading conversation from {file_path}: {e}")
                continue
        
        # 按更新时间倒序排序
        conversations.sort(
            key=lambda x: x.get("updated_at", x.get("timestamp", "")),
            reverse=True
        )
        
        return conversations
    
    def add_message(
        self,
        user_id: str,
        conversation_id: str,
        role: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        向对话添加消息
        
        Args:
            user_id: 用户ID
            conversation_id: 对话ID
            role: 消息角色 ('user' 或 'assistant')
            content: 消息内容
            metadata: 可选的元数据
            
        Returns:
            是否成功
        """
        conversation = self._load_conversation(user_id, conversation_id)
        if not conversation:
            return False

        metadata = metadata.copy() if metadata else {}
        message_id = metadata.get("message_id") or str(uuid.uuid4())
        metadata.setdefault("message_id", message_id)
        conversation = self._ensure_tree_metadata(conversation)
        existing_message_ids = {
            existing.get("id") or existing.get("metadata", {}).get("message_id")
            for existing in conversation.get("messages", [])
        }
        branches = conversation.setdefault("branches", {})
        active_branch_id = conversation.get("active_branch_id") or self.MAIN_BRANCH_ID
        time_travel = metadata.get("time_travel") if isinstance(metadata.get("time_travel"), dict) else {}
        branch_id = metadata.get("branch_id") or time_travel.get("branch_id") or active_branch_id
        parent_message_id = metadata.get("parent_message_id")
        fork_from_message_id = metadata.get("fork_from_message_id") or time_travel.get("replay_from_message_id")
        revision_of_message_id = metadata.get("revision_of_message_id") or fork_from_message_id
        fork_source_message = None
        if fork_from_message_id:
            for existing in conversation.get("messages", []):
                if (existing.get("id") or existing.get("metadata", {}).get("message_id")) == fork_from_message_id:
                    fork_source_message = existing
                    break

        if branch_id not in branches:
            parent_branch_id = active_branch_id
            if fork_source_message:
                parent_branch_id = fork_source_message.get("branch_id") or parent_branch_id
            branches[branch_id] = self._new_branch(
                branch_id,
                parent_branch_id=parent_branch_id,
                fork_from_message_id=fork_from_message_id,
                created_at=datetime.now().isoformat(),
            )

        if not parent_message_id and fork_source_message:
            parent_message_id = (
                fork_source_message.get("parent_message_id")
                or fork_source_message.get("metadata", {}).get("parent_message_id")
            )
        if not parent_message_id:
            parent_message_id = branches.get(branch_id, {}).get("head_message_id")
        if parent_message_id and parent_message_id not in existing_message_ids:
            fallback_parent_id = branches.get(branch_id, {}).get("head_message_id")
            parent_message_id = fallback_parent_id if fallback_parent_id in existing_message_ids else None

        metadata["branch_id"] = branch_id
        if parent_message_id:
            metadata["parent_message_id"] = parent_message_id
        if fork_from_message_id:
            metadata["fork_from_message_id"] = fork_from_message_id
        if revision_of_message_id:
            metadata["revision_of_message_id"] = revision_of_message_id
        
        message = {
            "id": message_id,
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
            "branch_id": branch_id,
            "parent_message_id": parent_message_id,
        }
        if fork_from_message_id:
            message["fork_from_message_id"] = fork_from_message_id
        if revision_of_message_id:
            message["revision_of_message_id"] = revision_of_message_id
        
        if metadata:
            message["metadata"] = metadata
        
        conversation["messages"].append(message)
        branch = branches[branch_id]
        if not branch.get("root_message_id"):
            branch["root_message_id"] = message_id
        branch["head_message_id"] = message_id
        branch["updated_at"] = message["timestamp"]
        conversation["active_branch_id"] = branch_id
        conversation["last_message"] = content[:100]  # 保存最后一条消息的前100个字符
        conversation["updated_at"] = datetime.now().isoformat()
        
        # 如果消息是用户发送的，尝试从消息中提取标题
        if role == "user" and conversation.get("title") in ["New Chat", "Untitled"]:
            # 使用前30个字符作为标题
            conversation["title"] = content[:30].strip() or "New Chat"
        
        return self._save_conversation(user_id, conversation)

    def mark_messages_superseded_after(
        self,
        user_id: str,
        conversation_id: str,
        message_id: str,
        branch_id: Optional[str] = None
    ) -> bool:
        """
        Mark messages after a timeline point as superseded for linear
        time-travel regeneration. The original records are retained for
        auditability; clients can hide or de-emphasize superseded messages.
        """
        conversation = self._load_conversation(user_id, conversation_id)
        if not conversation:
            return False
        conversation = self._ensure_tree_metadata(conversation)

        messages = conversation.get("messages", [])
        target_index = -1
        for idx, message in enumerate(messages):
            current_id = message.get("id") or message.get("metadata", {}).get("message_id")
            if current_id == message_id:
                target_index = idx
                break

        if target_index < 0:
            return False

        now = datetime.now().isoformat()
        for message in messages[target_index + 1:]:
            metadata = message.setdefault("metadata", {})
            if branch_id and metadata.get("time_travel", {}).get("branch_id") == branch_id:
                continue
            metadata["superseded"] = True
            metadata["superseded_at"] = now
            metadata["superseded_by_message_id"] = message_id
            if branch_id:
                metadata["superseded_by_branch_id"] = branch_id

        active_messages = [
            m for m in messages
            if not m.get("metadata", {}).get("superseded")
        ]
        if active_messages:
            conversation["last_message"] = active_messages[-1].get("content", "")[:100]
        conversation["updated_at"] = now
        return self._save_conversation(user_id, conversation)

    def set_active_branch(
        self,
        user_id: str,
        conversation_id: str,
        branch_id: str,
    ) -> bool:
        """Switch the visible branch for a conversation without modifying messages."""
        conversation = self._load_conversation(user_id, conversation_id)
        if not conversation:
            return False
        conversation = self._ensure_tree_metadata(conversation)
        branches = conversation.get("branches", {})
        if branch_id not in branches:
            return False

        conversation["active_branch_id"] = branch_id
        head_message_id = branches.get(branch_id, {}).get("head_message_id")
        if head_message_id:
            for message in conversation.get("messages", []):
                current_id = message.get("id") or message.get("metadata", {}).get("message_id")
                if current_id == head_message_id:
                    conversation["last_message"] = message.get("content", "")[:100]
                    break
        conversation["updated_at"] = datetime.now().isoformat()
        return self._save_conversation(user_id, conversation)
    
    def update_conversation(
        self,
        user_id: str,
        conversation_id: str,
        updates: Dict[str, Any]
    ) -> bool:
        """
        更新对话信息
        
        Args:
            user_id: 用户ID
            conversation_id: 对话ID
            updates: 要更新的字段字典
            
        Returns:
            是否成功
        """
        conversation = self._load_conversation(user_id, conversation_id)
        if not conversation:
            return False
        
        # 更新字段
        for key, value in updates.items():
            if key not in ["id", "user_id"]:  # 不允许修改ID
                conversation[key] = value
        
        conversation["updated_at"] = datetime.now().isoformat()
        
        return self._save_conversation(user_id, conversation)
    
    def delete_conversation(self, user_id: str, conversation_id: str) -> bool:
        """
        删除对话
        
        Args:
            user_id: 用户ID
            conversation_id: 对话ID
            
        Returns:
            是否成功
        """
        file_path = self._get_conversation_file(user_id, conversation_id)
        
        if file_path.exists():
            try:
                file_path.unlink()
                return True
            except Exception as e:
                print(f"Error deleting conversation {conversation_id} for user {user_id}: {e}")
                return False
        
        return False
    
    def get_full_conversation(self, user_id: str, conversation_id: str) -> Optional[Dict[str, Any]]:
        """
        获取完整的对话（包含所有消息）
        
        Args:
            user_id: 用户ID
            conversation_id: 对话ID
            
        Returns:
            完整的对话对象
        """
        return self._load_conversation(user_id, conversation_id)
    
    def update_conversation_preferences(
        self,
        user_id: str,
        conversation_id: str,
        new_preferences: Dict[str, Any]
    ) -> bool:
        """
        更新对话的偏好设置（覆盖式更新，只覆盖有内容的字段）
        
        Args:
            user_id: 用户ID
            conversation_id: 对话ID
            new_preferences: 新的偏好设置（只包含要更新的字段）
            
        Returns:
            是否成功
        """
        conversation = self._load_conversation(user_id, conversation_id)
        if not conversation:
            return False
        
        # 初始化 preferences 字段（如果不存在）
        if "preferences" not in conversation:
            conversation["preferences"] = {}
        
        # 覆盖式更新：只更新有内容的字段
        for key, value in new_preferences.items():
            if value is not None:  # 只更新非 None 的字段
                if isinstance(value, dict):
                    # 对于字典类型（如 budget_range），合并更新
                    if key not in conversation["preferences"]:
                        conversation["preferences"][key] = {}
                    conversation["preferences"][key].update(value)
                elif isinstance(value, list) and len(value) > 0:
                    # 对于列表类型，如果非空则更新
                    conversation["preferences"][key] = value
                elif not isinstance(value, (list, dict)):
                    # 对于其他类型，直接更新
                    conversation["preferences"][key] = value
        
        conversation["updated_at"] = datetime.now().isoformat()
        
        return self._save_conversation(user_id, conversation)
    
    def get_conversation_preferences(
        self,
        user_id: str,
        conversation_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        获取对话的偏好设置
        
        Args:
            user_id: 用户ID
            conversation_id: 对话ID
            
        Returns:
            偏好设置字典，如果对话不存在返回 None
        """
        conversation = self._load_conversation(user_id, conversation_id)
        if not conversation:
            return None
        
        return conversation.get("preferences", {})


# 全局存储实例
_storage_instance: Optional[ConversationStorage] = None


def get_storage() -> ConversationStorage:
    """获取全局存储实例（单例模式）"""
    global _storage_instance
    if _storage_instance is None:
        _storage_instance = ConversationStorage()
    return _storage_instance
