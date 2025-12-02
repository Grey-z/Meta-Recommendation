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
        user_dir = self.storage_dir / user_id
        user_dir.mkdir(exist_ok=True)
        return user_dir
    
    def _get_conversation_file(self, user_id: str, conversation_id: str) -> Path:
        """获取对话文件的路径"""
        return self._get_user_dir(user_id) / f"{conversation_id}.json"
    
    def _load_conversation(self, user_id: str, conversation_id: str) -> Optional[Dict[str, Any]]:
        """加载单个对话"""
        file_path = self._get_conversation_file(user_id, conversation_id)
        if not file_path.exists():
            return None
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading conversation {conversation_id} for user {user_id}: {e}")
            return None
    
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
        model: str = "RestRec"
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
            "messages": []
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
                        "model": conv.get("model", "RestRec"),
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
        
        message = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat()
        }
        
        if metadata:
            message["metadata"] = metadata
        
        conversation["messages"].append(message)
        conversation["last_message"] = content[:100]  # 保存最后一条消息的前100个字符
        conversation["updated_at"] = datetime.now().isoformat()
        
        # 如果消息是用户发送的，尝试从消息中提取标题
        if role == "user" and conversation.get("title") in ["New Chat", "Untitled"]:
            # 使用前30个字符作为标题
            conversation["title"] = content[:30].strip() or "New Chat"
        
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


# 全局存储实例
_storage_instance: Optional[ConversationStorage] = None


def get_storage() -> ConversationStorage:
    """获取全局存储实例（单例模式）"""
    global _storage_instance
    if _storage_instance is None:
        _storage_instance = ConversationStorage()
    return _storage_instance

