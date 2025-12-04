"""
用户画像存储模块
维护用户画像信息，支持持久化存储和更新
"""
import json
import os
from typing import Dict, Any, Optional
from datetime import datetime


class UserProfileStorage:
    """用户画像存储类"""
    
    def __init__(self, storage_dir: str = "user_profiles"):
        """
        初始化用户画像存储
        
        Args:
            storage_dir: 存储目录路径
        """
        self.storage_dir = storage_dir
        # 确保存储目录存在
        os.makedirs(self.storage_dir, exist_ok=True)
    
    def _get_profile_path(self, user_id: str) -> str:
        """获取用户画像文件路径"""
        return os.path.join(self.storage_dir, f"{user_id}.json")
    
    def get_default_profile(self) -> Dict[str, Any]:
        """
        获取默认用户画像
        
        Returns:
            默认用户画像字典
        """
        return {
            "user_id": "",
            "demographics": {
                "age_range": "",  # "18-25", "26-35", "36-45", "46-55", "55+"
                "gender": "",  # "male", "female", "other"
                "occupation": "",  # "student", "professional", "retired", etc.
                "location": "",  # "Singapore", "Chinatown", etc.
                "nationality": ""  # "Chinese", "Singaporean", etc.
            },
            "dining_habits": {
                "typical_budget": "",  # String, e.g. "20-60 SGD"
                "dietary_restrictions": "",  # String, e.g. "vegetarian, vegan" or comma-separated
                "spice_tolerance": "",  # "low", "medium", "high"
                "description": ""  # 用户描述文本，用于存储从对话中推断出的其他用餐习惯信息
            },
            "metadata": {
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
            }
        }
    
    def get_user_profile(self, user_id: str) -> Dict[str, Any]:
        """
        获取用户画像
        
        Args:
            user_id: 用户ID
            
        Returns:
            用户画像字典，如果不存在则返回默认画像
        """
        profile_path = self._get_profile_path(user_id)
        
        if os.path.exists(profile_path):
            try:
                with open(profile_path, 'r', encoding='utf-8') as f:
                    profile = json.load(f)
                    # 确保所有字段都存在，并规范化值（数组转字符串，null转空字符串）
                    default_profile = self.get_default_profile()
                    for key in default_profile:
                        if key not in profile:
                            profile[key] = default_profile[key]
                        elif isinstance(profile[key], dict):
                            # 规范化字典中的值
                            for sub_key, sub_value in profile[key].items():
                                if sub_value is None:
                                    profile[key][sub_key] = ""
                                elif isinstance(sub_value, list):
                                    profile[key][sub_key] = ", ".join(str(item) for item in sub_value if item) if sub_value else ""
                    return profile
            except Exception as e:
                print(f"Error loading user profile for {user_id}: {e}")
                return self.get_default_profile()
        else:
            # 返回默认画像
            profile = self.get_default_profile()
            profile["user_id"] = user_id
            return profile
    
    def save_user_profile(self, user_id: str, profile: Dict[str, Any]) -> bool:
        """
        保存用户画像
        
        Args:
            user_id: 用户ID
            profile: 用户画像字典
            
        Returns:
            是否保存成功
        """
        try:
            profile["user_id"] = user_id
            profile["metadata"]["updated_at"] = datetime.now().isoformat()
            if "created_at" not in profile["metadata"]:
                profile["metadata"]["created_at"] = datetime.now().isoformat()
            
            profile_path = self._get_profile_path(user_id)
            with open(profile_path, 'w', encoding='utf-8') as f:
                json.dump(profile, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"Error saving user profile for {user_id}: {e}")
            return False
    
    def update_user_profile(
        self, 
        user_id: str, 
        updates: Dict[str, Any],
        merge: bool = True
    ) -> Dict[str, Any]:
        """
        更新用户画像
        
        Args:
            user_id: 用户ID
            updates: 要更新的字段字典
            merge: 是否合并更新（True）还是替换（False）
            
        Returns:
            更新后的用户画像
        """
        profile = self.get_user_profile(user_id)
        
        if merge:
            # 深度合并更新
            self._deep_merge(profile, updates)
        else:
            # 直接替换
            profile.update(updates)
        
        # 更新元数据
        profile["metadata"]["interaction_count"] = profile["metadata"].get("interaction_count", 0) + 1
        profile["metadata"]["last_interaction"] = datetime.now().isoformat()
        
        # 保存
        self.save_user_profile(user_id, profile)
        return profile
    
    def _deep_merge(self, base: Dict[str, Any], updates: Dict[str, Any]) -> None:
        """
        深度合并两个字典
        
        Args:
            base: 基础字典（会被修改）
            updates: 更新字典
        """
        for key, value in updates.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                # 递归合并字典
                self._deep_merge(base[key], value)
            else:
                # 直接更新
                base[key] = value


# 全局存储实例
_storage_instance: Optional[UserProfileStorage] = None


def get_profile_storage(storage_dir: str = "user_profiles") -> UserProfileStorage:
    """
    获取用户画像存储实例（单例模式）
    
    Args:
        storage_dir: 存储目录路径
        
    Returns:
        UserProfileStorage 实例
    """
    global _storage_instance
    if _storage_instance is None:
        _storage_instance = UserProfileStorage(storage_dir)
    return _storage_instance

