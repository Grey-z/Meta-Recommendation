"""
智能存储适配器
根据本地目录是否存在，自动选择使用本地文件系统存储或 HuggingFace Datasets Hub 存储
"""
import os
from pathlib import Path
from typing import Union, Optional, Tuple

# 导入本地存储
from conversation_storage import ConversationStorage
from user_profile_storage import UserProfileStorage

# 导入 HuggingFace 存储
try:
    from hf_storage import HFConversationStorage, HFUserProfileStorage
    HF_STORAGE_AVAILABLE = True
except ImportError:
    HF_STORAGE_AVAILABLE = False
    print("Warning: HuggingFace storage not available. Install datasets and huggingface_hub if needed.")


def _check_local_storage_exists() -> Tuple[bool, bool]:
    """
    检查本地存储目录是否存在（在初始化之前检查，避免自动创建）
    
    Returns:
        (conversations_exists, user_profiles_exists)
    """
    base_dir = Path(__file__).parent
    
    conversations_dir = base_dir / "conversations"
    user_profiles_dir = base_dir / "user_profiles"
    
    # 检查目录是否存在且为目录（即使为空也算存在）
    # 注意：这里只检查是否存在，不创建目录
    conversations_exists = conversations_dir.exists() and conversations_dir.is_dir()
    user_profiles_exists = user_profiles_dir.exists() and user_profiles_dir.is_dir()
    
    return conversations_exists, user_profiles_exists


def get_storage() -> Union[ConversationStorage, HFConversationStorage]:
    """
    获取对话存储实例（自动选择本地或 HuggingFace）
    
    如果本地 conversations 目录存在，使用本地存储
    否则使用 HuggingFace Datasets Hub 存储
    """
    conversations_exists, _ = _check_local_storage_exists()
    
    if conversations_exists:
        print("📁 Using local file system storage for conversations")
        return ConversationStorage()
    else:
        if not HF_STORAGE_AVAILABLE:
            raise ImportError(
                "Local conversations directory not found and HuggingFace storage is not available. "
                "Please either:\n"
                "1. Create a 'conversations' directory in MetaRec-backend, or\n"
                "2. Install datasets and huggingface_hub: pip install datasets huggingface_hub"
            )
        print("☁️  Using HuggingFace Datasets Hub storage for conversations")
        return HFConversationStorage()


def get_profile_storage() -> Union[UserProfileStorage, HFUserProfileStorage]:
    """
    获取用户画像存储实例（自动选择本地或 HuggingFace）
    
    如果本地 user_profiles 目录存在，使用本地存储
    否则使用 HuggingFace Datasets Hub 存储
    """
    _, user_profiles_exists = _check_local_storage_exists()
    
    if user_profiles_exists:
        print("📁 Using local file system storage for user profiles")
        # UserProfileStorage 使用相对路径，需要确保路径正确
        base_dir = Path(__file__).parent
        return UserProfileStorage(storage_dir=str(base_dir / "user_profiles"))
    else:
        if not HF_STORAGE_AVAILABLE:
            raise ImportError(
                "Local user_profiles directory not found and HuggingFace storage is not available. "
                "Please either:\n"
                "1. Create a 'user_profiles' directory in MetaRec-backend, or\n"
                "2. Install datasets and huggingface_hub: pip install datasets huggingface_hub"
            )
        print("☁️  Using HuggingFace Datasets Hub storage for user profiles")
        return HFUserProfileStorage()

