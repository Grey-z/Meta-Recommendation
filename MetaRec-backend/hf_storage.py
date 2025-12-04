"""
基于 HuggingFace Datasets Hub 的存储模块
使用 HuggingFace Datasets Hub 进行持久化存储
"""
import json
import os
from typing import List, Dict, Any, Optional
from datetime import datetime
import uuid
from datasets import Dataset, load_dataset
from huggingface_hub import login, HfApi
from dotenv import load_dotenv

load_dotenv()

# HuggingFace 配置
HF_REPO_ID = os.getenv("HF_DATASET_REPO", "jnsecret/MetaRecStorage")
HF_TOKEN = os.getenv("HF_TOKEN", os.getenv("HUGGINGFACE_HUB_TOKEN", ""))

# 如果提供了 token，登录
if HF_TOKEN:
    try:
        login(token=HF_TOKEN)
    except Exception as e:
        print(f"Warning: Failed to login to HuggingFace Hub: {e}")


class HFConversationStorage:
    """基于 HuggingFace Datasets Hub 的对话存储管理器"""
    
    def __init__(self, repo_id: str = HF_REPO_ID):
        """
        初始化存储管理器
        
        Args:
            repo_id: HuggingFace 数据集仓库 ID
        """
        self.repo_id = repo_id
        self.api = HfApi(token=HF_TOKEN if HF_TOKEN else None)
        self._cache = {}  # 内存缓存
        self._cache_loaded = False
    
    def _load_dataset(self) -> Dict[str, Any]:
        """从 Hub 加载数据集或使用缓存"""
        if not self._cache_loaded:
            try:
                # 尝试加载数据集
                dataset = load_dataset(self.repo_id, "conversations", token=HF_TOKEN if HF_TOKEN else None)
                
                # 处理不同的数据集格式
                if isinstance(dataset, dict):
                    train_data = dataset.get("train")
                    if train_data and len(train_data) > 0:
                        # 转换为列表格式
                        conversations = [dict(row) for row in train_data]
                        self._cache = {"conversations": conversations}
                    else:
                        self._cache = {"conversations": []}
                else:
                    # 单个数据集对象
                    if len(dataset) > 0:
                        conversations = [dict(row) for row in dataset]
                        self._cache = {"conversations": conversations}
                    else:
                        self._cache = {"conversations": []}
                
                self._cache_loaded = True
            except Exception as e:
                print(f"Warning: Failed to load dataset from Hub, using empty dataset: {e}")
                self._cache = {"conversations": []}
                self._cache_loaded = True
        
        return self._cache
    
    def _save_dataset(self) -> bool:
        """保存数据集到 Hub"""
        try:
            conversations = self._cache.get("conversations", [])
            if not conversations:
                # 如果为空，创建一个空的数据集结构
                conversations = []
            
            # 创建数据集，将每个 conversation 作为一行
            # 使用 from_list 确保每个 conversation 对象作为一行数据
            dataset = Dataset.from_list(conversations)
            
            # 推送到 Hub，如果数据集不存在会自动创建
            dataset.push_to_hub(
                self.repo_id,
                config_name="conversations",
                token=HF_TOKEN if HF_TOKEN else None,
                private=True,
                commit_message=f"Update conversations at {datetime.now().isoformat()}"
            )
            return True
        except Exception as e:
            print(f"Error saving dataset to Hub: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _find_conversation(self, user_id: str, conversation_id: str) -> Optional[int]:
        """查找对话在列表中的索引"""
        conversations = self._load_dataset().get("conversations", [])
        for idx, conv in enumerate(conversations):
            if conv.get("user_id") == user_id and conv.get("id") == conversation_id:
                return idx
        return None
    
    def create_conversation(
        self, 
        user_id: str, 
        title: Optional[str] = None,
        model: str = "RestRec"
    ) -> Dict[str, Any]:
        """创建新对话"""
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
            "messages": [],
            "preferences": {}
        }
        
        # 添加到缓存
        if "conversations" not in self._cache:
            self._cache["conversations"] = []
        self._cache["conversations"].append(conversation)
        
        # 保存到 Hub
        if self._save_dataset():
            return conversation
        else:
            raise Exception("Failed to create conversation")
    
    def get_conversation(self, user_id: str, conversation_id: str) -> Optional[Dict[str, Any]]:
        """获取单个对话"""
        idx = self._find_conversation(user_id, conversation_id)
        if idx is not None:
            conversations = self._load_dataset().get("conversations", [])
            return conversations[idx]
        return None
    
    def get_all_conversations(self, user_id: str) -> List[Dict[str, Any]]:
        """获取用户的所有对话列表"""
        conversations = self._load_dataset().get("conversations", [])
        user_conversations = [
            {
                "id": conv.get("id"),
                "title": conv.get("title", "Untitled"),
                "model": conv.get("model", "RestRec"),
                "last_message": conv.get("last_message", ""),
                "timestamp": conv.get("timestamp"),
                "updated_at": conv.get("updated_at", conv.get("timestamp")),
                "message_count": len(conv.get("messages", []))
            }
            for conv in conversations
            if conv.get("user_id") == user_id
        ]
        
        # 按更新时间倒序排序
        user_conversations.sort(
            key=lambda x: x.get("updated_at", x.get("timestamp", "")),
            reverse=True
        )
        
        return user_conversations
    
    def add_message(
        self,
        user_id: str,
        conversation_id: str,
        role: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """向对话添加消息"""
        idx = self._find_conversation(user_id, conversation_id)
        if idx is None:
            return False
        
        conversations = self._load_dataset().get("conversations", [])
        conversation = conversations[idx]
        
        message = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat()
        }
        
        if metadata:
            message["metadata"] = metadata
        
        conversation["messages"].append(message)
        conversation["last_message"] = content[:100]
        conversation["updated_at"] = datetime.now().isoformat()
        
        if role == "user" and conversation.get("title") in ["New Chat", "Untitled"]:
            conversation["title"] = content[:30].strip() or "New Chat"
        
        conversations[idx] = conversation
        self._cache["conversations"] = conversations
        
        return self._save_dataset()
    
    def update_conversation(
        self,
        user_id: str,
        conversation_id: str,
        updates: Dict[str, Any]
    ) -> bool:
        """更新对话信息"""
        idx = self._find_conversation(user_id, conversation_id)
        if idx is None:
            return False
        
        conversations = self._load_dataset().get("conversations", [])
        conversation = conversations[idx]
        
        for key, value in updates.items():
            if key not in ["id", "user_id"]:
                conversation[key] = value
        
        conversation["updated_at"] = datetime.now().isoformat()
        conversations[idx] = conversation
        self._cache["conversations"] = conversations
        
        return self._save_dataset()
    
    def delete_conversation(self, user_id: str, conversation_id: str) -> bool:
        """删除对话"""
        idx = self._find_conversation(user_id, conversation_id)
        if idx is None:
            return False
        
        conversations = self._load_dataset().get("conversations", [])
        conversations.pop(idx)
        self._cache["conversations"] = conversations
        
        return self._save_dataset()
    
    def get_full_conversation(self, user_id: str, conversation_id: str) -> Optional[Dict[str, Any]]:
        """获取完整的对话"""
        return self.get_conversation(user_id, conversation_id)
    
    def update_conversation_preferences(
        self,
        user_id: str,
        conversation_id: str,
        new_preferences: Dict[str, Any]
    ) -> bool:
        """更新对话的偏好设置"""
        idx = self._find_conversation(user_id, conversation_id)
        if idx is None:
            return False
        
        conversations = self._load_dataset().get("conversations", [])
        conversation = conversations[idx]
        
        if "preferences" not in conversation:
            conversation["preferences"] = {}
        
        for key, value in new_preferences.items():
            if value is not None:
                if isinstance(value, dict):
                    if key not in conversation["preferences"]:
                        conversation["preferences"][key] = {}
                    conversation["preferences"][key].update(value)
                elif isinstance(value, list) and len(value) > 0:
                    conversation["preferences"][key] = value
                elif not isinstance(value, (list, dict)):
                    conversation["preferences"][key] = value
        
        conversation["updated_at"] = datetime.now().isoformat()
        conversations[idx] = conversation
        self._cache["conversations"] = conversations
        
        return self._save_dataset()
    
    def get_conversation_preferences(
        self,
        user_id: str,
        conversation_id: str
    ) -> Optional[Dict[str, Any]]:
        """获取对话的偏好设置"""
        conversation = self.get_conversation(user_id, conversation_id)
        if not conversation:
            return None
        return conversation.get("preferences", {})


class HFUserProfileStorage:
    """基于 HuggingFace Datasets Hub 的用户画像存储类"""
    
    def __init__(self, repo_id: str = HF_REPO_ID):
        """
        初始化用户画像存储
        
        Args:
            repo_id: HuggingFace 数据集仓库 ID
        """
        self.repo_id = repo_id
        self.api = HfApi(token=HF_TOKEN if HF_TOKEN else None)
        self._cache = {}
        self._cache_loaded = False
    
    def _load_dataset(self) -> Dict[str, Any]:
        """从 Hub 加载数据集或使用缓存"""
        if not self._cache_loaded:
            try:
                dataset = load_dataset(self.repo_id, "user_profiles", token=HF_TOKEN if HF_TOKEN else None)
                
                # 处理不同的数据集格式
                if isinstance(dataset, dict):
                    train_data = dataset.get("train")
                    if train_data and len(train_data) > 0:
                        profiles = [dict(row) for row in train_data]
                    else:
                        profiles = []
                else:
                    if len(dataset) > 0:
                        profiles = [dict(row) for row in dataset]
                    else:
                        profiles = []
                
                # 转换为 user_id -> profile 的字典
                self._cache = {p.get("user_id", ""): p for p in profiles if p.get("user_id")}
                self._cache_loaded = True
            except Exception as e:
                print(f"Warning: Failed to load user profiles from Hub, using empty cache: {e}")
                self._cache = {}
                self._cache_loaded = True
        
        return self._cache
    
    def _save_dataset(self) -> bool:
        """保存数据集到 Hub"""
        try:
            profiles = list(self._cache.values())
            if not profiles:
                profiles = []
            
            # 创建数据集，将每个 profile 作为一行
            dataset = Dataset.from_list(profiles)
            dataset.push_to_hub(
                self.repo_id,
                config_name="user_profiles",
                token=HF_TOKEN if HF_TOKEN else None,
                private=True,
                commit_message=f"Update user profiles at {datetime.now().isoformat()}"
            )
            return True
        except Exception as e:
            print(f"Error saving user profiles to Hub: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def get_default_profile(self) -> Dict[str, Any]:
        """获取默认用户画像"""
        return {
            "user_id": "",
            "demographics": {
                "age_range": "",
                "gender": "",
                "occupation": "",
                "location": "",
                "nationality": ""
            },
            "dining_habits": {
                "typical_budget": "",
                "dietary_restrictions": "",
                "spice_tolerance": "",
                "description": ""
            },
            "metadata": {
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
            }
        }
    
    def get_user_profile(self, user_id: str) -> Dict[str, Any]:
        """获取用户画像"""
        profiles = self._load_dataset()
        
        if user_id in profiles:
            profile = profiles[user_id]
            default_profile = self.get_default_profile()
            
            # 确保所有字段都存在
            for key in default_profile:
                if key not in profile:
                    profile[key] = default_profile[key]
                elif isinstance(profile[key], dict):
                    for sub_key, sub_value in profile[key].items():
                        if sub_value is None:
                            profile[key][sub_key] = ""
                        elif isinstance(sub_value, list):
                            profile[key][sub_key] = ", ".join(str(item) for item in sub_value if item) if sub_value else ""
            
            return profile
        else:
            profile = self.get_default_profile()
            profile["user_id"] = user_id
            return profile
    
    def save_user_profile(self, user_id: str, profile: Dict[str, Any]) -> bool:
        """保存用户画像"""
        try:
            profiles = self._load_dataset()
            profile["user_id"] = user_id
            profile["metadata"]["updated_at"] = datetime.now().isoformat()
            if "created_at" not in profile["metadata"]:
                profile["metadata"]["created_at"] = datetime.now().isoformat()
            
            profiles[user_id] = profile
            self._cache = profiles
            
            return self._save_dataset()
        except Exception as e:
            print(f"Error saving user profile for {user_id}: {e}")
            return False
    
    def update_user_profile(
        self, 
        user_id: str, 
        updates: Dict[str, Any],
        merge: bool = True
    ) -> Dict[str, Any]:
        """更新用户画像"""
        profile = self.get_user_profile(user_id)
        
        if merge:
            self._deep_merge(profile, updates)
        else:
            profile.update(updates)
        
        profile["metadata"]["interaction_count"] = profile["metadata"].get("interaction_count", 0) + 1
        profile["metadata"]["last_interaction"] = datetime.now().isoformat()
        
        self.save_user_profile(user_id, profile)
        return profile
    
    def _deep_merge(self, base: Dict[str, Any], updates: Dict[str, Any]) -> None:
        """深度合并两个字典"""
        for key, value in updates.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._deep_merge(base[key], value)
            else:
                base[key] = value


# 全局存储实例
_conversation_storage_instance: Optional[HFConversationStorage] = None
_profile_storage_instance: Optional[HFUserProfileStorage] = None


def get_storage() -> HFConversationStorage:
    """获取全局对话存储实例（单例模式）"""
    global _conversation_storage_instance
    if _conversation_storage_instance is None:
        _conversation_storage_instance = HFConversationStorage()
    return _conversation_storage_instance


def get_profile_storage() -> HFUserProfileStorage:
    """获取全局用户画像存储实例（单例模式）"""
    global _profile_storage_instance
    if _profile_storage_instance is None:
        _profile_storage_instance = HFUserProfileStorage()
    return _profile_storage_instance

