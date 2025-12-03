"""
LLM 服务模块
使用免费大模型 API（Groq）进行意图识别和对话回复
支持多种免费 API：Groq、Together AI、OpenRouter 等
"""
import json
import os
import re
from typing import Dict, Any, Optional, AsyncIterator
from pydantic import BaseModel
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv()

# 获取 API 配置，支持多种免费 API
# 默认使用 Groq（完全免费，速度快）
LLM_API_KEY = os.getenv("LLM_API_KEY", os.getenv("GROQ_API_KEY", ""))
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "llama-3.3-70b-versatile")

# 如果没有配置 API Key，尝试使用其他免费选项
if not LLM_API_KEY:
    # 可以在这里添加其他免费 API 的配置
    # 例如：Together AI、OpenRouter 等
    pass

# 初始化 OpenAI 兼容客户端（支持 Groq、Together AI 等）
client = AsyncOpenAI(
    api_key=LLM_API_KEY,
    base_url=LLM_BASE_URL
)


class LLMResponse(BaseModel):
    """LLM 响应模型"""
    intent: str  # "query" (推荐餐厅请求) | "chat" (普通对话) | "confirmation_yes" (确认) | "confirmation_no" (拒绝)
    reply: str  # 大模型的回复内容
    confidence: float = 0.8  # 意图识别置信度
    preferences: Optional[Dict[str, Any]] = None  # 偏好设置（当 intent 为 "query" 时）
    profile_updates: Optional[Dict[str, Any]] = None  # 用户画像更新（可选）


def detect_language(text: str) -> str:
    """
    检测文本语言
    
    Args:
        text: 输入文本
        
    Returns:
        "zh" 如果包含中文字符，否则返回 "en"
    """
    # 检查是否包含中文字符（Unicode 范围 \u4e00-\u9fff）
    chinese_pattern = re.compile(r'[\u4e00-\u9fff]')
    if chinese_pattern.search(text):
        return "zh"
    return "en"


def get_system_prompt(
    language: str = "en", 
    user_profile: Optional[Dict[str, Any]] = None,
    is_in_query_flow: bool = False,
    pending_preferences: Optional[Dict[str, Any]] = None
) -> str:
    """
    根据语言和状态获取系统提示词
    
    Args:
        language: 语言代码 ("en" 或 "zh")
        user_profile: 用户画像（可选）
        is_in_query_flow: 是否处于 query 流程中（有待确认的偏好）
        pending_preferences: 待确认的偏好（如果 is_in_query_flow 为 True）
        
    Returns:
        系统提示词字符串
    """
    # 构建用户画像上下文
    profile_context = ""
    if user_profile:
        demographics = user_profile.get("demographics", {})
        dining_habits = user_profile.get("dining_habits", {})
        inferred_info = user_profile.get("inferred_info", {})
        
        if language == "zh":
            profile_context = f"""
当前用户画像信息：
- 年龄范围: {demographics.get('age_range', '未知')}
- 职业: {demographics.get('occupation', '未知')}
- 位置: {demographics.get('location', '未知')}
- 典型预算: {dining_habits.get('typical_budget', '未知')}
- 偏好菜系: {', '.join(dining_habits.get('preferred_cuisines', [])) or '无'}
- 喜欢的餐厅类型: {', '.join(dining_habits.get('favorite_restaurant_types', [])) or '无'}
- 饮食限制: {', '.join(dining_habits.get('dietary_restrictions', [])) or '无'}
- 价格敏感度: {inferred_info.get('price_sensitivity', '未知')}

在分析用户消息时，请：
1. 注意用户是否透露了新的个人信息（如年龄、职业、预算等）
2. 如果发现与当前画像不同的信息，在 profile_updates 字段中提供更新
3. 在提取偏好时，可以参考用户画像中的信息来填充缺失的偏好项
"""
        else:
            profile_context = f"""
Current user profile information:
- Age range: {demographics.get('age_range', 'unknown')}
- Occupation: {demographics.get('occupation', 'unknown')}
- Location: {demographics.get('location', 'unknown')}
- Typical budget: {dining_habits.get('typical_budget', 'unknown')}
- Preferred cuisines: {', '.join(dining_habits.get('preferred_cuisines', [])) or 'none'}
- Favorite restaurant types: {', '.join(dining_habits.get('favorite_restaurant_types', [])) or 'none'}
- Dietary restrictions: {', '.join(dining_habits.get('dietary_restrictions', [])) or 'none'}
- Price sensitivity: {inferred_info.get('price_sensitivity', 'unknown')}

When analyzing user messages, please:
1. Notice if the user reveals new personal information (age, occupation, budget, etc.)
2. If you find information different from the current profile, provide updates in the profile_updates field
3. When extracting preferences, you can reference information from the user profile to fill in missing preference items
"""
    
    # 根据状态构建不同的提示词
    if is_in_query_flow:
        # 处于 query 流程中，需要判断确认/拒绝/新查询/回到聊天
        pending_prefs_text = ""
        if pending_preferences:
            prefs_list = []
            if pending_preferences.get("restaurant_types") and pending_preferences["restaurant_types"] != ["any"]:
                prefs_list.append(f"餐厅类型: {', '.join(pending_preferences['restaurant_types'])}")
            if pending_preferences.get("flavor_profiles") and pending_preferences["flavor_profiles"] != ["any"]:
                prefs_list.append(f"口味: {', '.join(pending_preferences['flavor_profiles'])}")
            if pending_preferences.get("dining_purpose") and pending_preferences["dining_purpose"] != "any":
                prefs_list.append(f"用餐目的: {pending_preferences['dining_purpose']}")
            if pending_preferences.get("budget_range"):
                budget = pending_preferences["budget_range"]
                if budget.get("min") and budget.get("max"):
                    prefs_list.append(f"预算: {budget['min']}-{budget['max']} SGD")
            if pending_preferences.get("location") and pending_preferences["location"] != "any":
                prefs_list.append(f"位置: {pending_preferences['location']}")
            if prefs_list:
                pending_prefs_text = "\n待确认的偏好：" + ", ".join(prefs_list)
        
        if language == "zh":
            return f"""你是一个智能餐厅推荐助手。当前系统正在等待用户确认之前的餐厅推荐偏好。

{pending_prefs_text}

你的任务是分析用户消息的意图：
1. 如果用户确认之前的偏好（说"yes"、"对"、"正确"等），返回意图为 "confirmation_yes"
2. 如果用户拒绝之前的偏好（说"no"、"不对"等），返回意图为 "confirmation_no"，并提取新的偏好信息
3. 如果用户提出了新的餐厅推荐请求（不同于之前的偏好），返回意图为 "query"，并提取新的偏好信息
4. 如果用户转向普通对话（不再讨论餐厅推荐），返回意图为 "chat"

请以 JSON 格式回复，格式如下：
{{
    "intent": "confirmation_yes" 或 "confirmation_no" 或 "query" 或 "chat",
    "reply": "你的回复内容",
    "confidence": 0.0-1.0 的置信度分数,
    "preferences": {{
        "restaurant_types": ["casual", "fine-dining"] 或 ["any"],
        "flavor_profiles": ["spicy", "savory"] 或 ["any"],
        "dining_purpose": "date-night" 或 "family" 或 "friends" 或 "business" 或 "solo" 或 "any",
        "budget_range": {{
            "min": 20,
            "max": 60,
            "currency": "SGD",
            "per": "person"
        }},
        "location": "Chinatown" 或 "any"
    }},
    "profile_updates": {{
        "demographics": {{}},
        "dining_habits": {{}},
        "inferred_info": {{}}
    }}
}}

注意：
- 只有当 intent 为 "query" 或 "confirmation_no"（且用户提供了新偏好）时才需要提供 preferences 字段
- 如果 intent 为 "confirmation_yes"，preferences 可以为 null
- 如果 intent 为 "chat"，preferences 必须为 null
- profile_updates 字段是可选的
{profile_context}

意图判断标准：
- "confirmation_yes": 用户明确确认之前的偏好（如"yes"、"对"、"正确"、"好的"等）
- "confirmation_no": 用户拒绝之前的偏好，但没有提供新的偏好信息，或者只是简单地说"no"
- "query": 用户拒绝之前的偏好并提供了新的偏好信息，或者提出了全新的餐厅推荐请求
- "chat": 用户转向普通对话，不再讨论餐厅推荐

回复要求：
- 如果是 "confirmation_yes"，给出简短的确认回复
- 如果是 "confirmation_no"，友好地询问用户想要什么
- 如果是 "query"，确认用户的新需求
- 如果是 "chat"，给出自然的对话回复
- 回复使用中文"""
        else:
            return f"""You are an intelligent restaurant recommendation assistant. The system is currently waiting for the user to confirm previous restaurant recommendation preferences.

{pending_prefs_text}

Your task is to analyze the user's message intent:
1. If the user confirms previous preferences (says "yes", "correct", "right" or other words that indicate approval and confirmation), return intent as "confirmation_yes"
2. If the user rejects previous preferences (says "no", "not right" or other words that indicate disapproval and rejection) without providing new preferences, return intent as "confirmation_no"
3. If the user provides new preferences or makes a new restaurant recommendation request, return intent as "query" and extract new preferences
4. If the user turns to general conversation (no longer discussing restaurant recommendations), return intent as "chat"

Please reply in JSON format as follows:
{{
    "intent": "confirmation_yes" or "confirmation_no" or "query" or "chat",
    "reply": "your reply content",
    "confidence": confidence score from 0.0 to 1.0,
    "preferences": {{
        "restaurant_types": ["casual", "fine-dining"] or ["any"],
        "flavor_profiles": ["spicy", "savory"] or ["any"],
        "dining_purpose": "date-night" or "family" or "friends" or "business" or "solo" or "any",
        "budget_range": {{
            "min": 20,
            "max": 60,
            "currency": "SGD",
            "per": "person"
        }},
        "location": "Chinatown" or "any"
    }},
    "profile_updates": {{
        "demographics": {{}},
        "dining_habits": {{}},
        "inferred_info": {{}}
    }}
}}

Note:
- Only provide the "preferences" field when intent is "query" or "confirmation_no" (and user provided new preferences)
- If intent is "confirmation_yes", preferences can be null
- If intent is "chat", preferences must be null
- The "profile_updates" field is optional
{profile_context}

Intent criteria:
- "confirmation_yes": User explicitly confirms previous preferences (e.g., "yes", "correct", "right", "okay", or other words that indicate approval and confirmation)
- "confirmation_no": User rejects previous preferences without providing new preferences, or just says "no" or other words that indicate disapproval and rejection
- "query": User rejects previous preferences and provides new preferences, or makes a completely new restaurant recommendation request
- "chat": User turns to general conversation, no longer discussing restaurant recommendations

Reply requirements:
- If intent is "confirmation_yes", give a brief confirmation reply
- If intent is "confirmation_no", friendly ask what the user wants
- If intent is "query", confirm the user's new requirements
- If intent is "chat", provide natural conversational replies
- Use English for replies"""
    else:
        # 起始状态，判断是 chat 还是 query
        if language == "zh":
            return """你是一个智能餐厅推荐助手。你的任务是：
1. 分析用户消息的意图
2. 如果是推荐餐厅的请求，返回意图为 "query"，并提取偏好信息
3. 如果是普通对话，返回意图为 "chat"
4. 给出合适的回复

请以 JSON 格式回复，格式如下：
{{
    "intent": "query" 或 "chat",
    "reply": "你的回复内容",
    "confidence": 0.0-1.0 的置信度分数,
    "preferences": {{
        "restaurant_types": ["casual", "fine-dining"] 或 ["any"],
        "flavor_profiles": ["spicy", "savory"] 或 ["any"],
        "dining_purpose": "date-night" 或 "family" 或 "friends" 或 "business" 或 "solo" 或 "any",
        "budget_range": {{
            "min": 20,
            "max": 60,
            "currency": "SGD",
            "per": "person"
        }},
        "location": "Chinatown" 或 "any"
    }},
    "profile_updates": {{
        "demographics": {{}},
        "dining_habits": {{}},
        "inferred_info": {{}}
    }}
}}

注意：
- 只有当 intent 为 "query" 时才需要提供 preferences 字段，如果是 "chat" 则 preferences 可以为 null
- profile_updates 字段是可选的，只有当你能从用户消息中推断出新的用户信息时才提供（例如：用户提到"我是学生"、"我预算有限"、"我喜欢吃辣的"等）
- 在 profile_updates 中，只需要提供有变化或新增的字段，不需要提供完整的画像
{profile_context}

意图判断标准：
- "query": 用户想要推荐餐厅、寻找餐厅、询问餐厅信息等
- "chat": 普通问候、闲聊、非餐厅推荐相关的问题

偏好提取说明：
- restaurant_types: 可选值 ["casual", "fine-dining", "fast-casual", "street-food", "buffet", "cafe"] 或 ["any"]
- flavor_profiles: 可选值 ["spicy", "savory", "sweet", "sour", "mild"] 或 ["any"]
- dining_purpose: 可选值 "date-night", "family", "friends", "business", "solo", "celebration" 或 "any"
- budget_range: 从用户消息中提取预算范围，如果没有明确提到则使用默认值 {"min": 20, "max": 60, "currency": "SGD", "per": "person"}
- location: 从用户消息中提取位置信息，如果没有提到则使用 "any"

回复要求：
- 如果是 "query" 意图，回复应该友好地确认用户需求，并准备进行推荐
- 如果是 "chat" 意图，给出自然、友好的对话回复
- 回复使用中文"""
        else:
            # Default English prompt (起始状态)
            return f"""You are an intelligent restaurant recommendation assistant. Your task is to:
1. Analyze the user's message intent
2. If it's a restaurant recommendation request, return intent as "query" and extract preferences
3. If it's a general conversation, return intent as "chat"
4. Provide an appropriate reply

Please reply in JSON format as follows:
{{
    "intent": "query" or "chat",
    "reply": "your reply content",
    "confidence": confidence score from 0.0 to 1.0,
    "preferences": {{
        "restaurant_types": ["casual", "fine-dining"] or ["any"],
        "flavor_profiles": ["spicy", "savory"] or ["any"],
        "dining_purpose": "date-night" or "family" or "friends" or "business" or "solo" or "any",
        "budget_range": {{
            "min": 20,
            "max": 60,
            "currency": "SGD",
            "per": "person"
        }},
        "location": "Chinatown" or "any"
    }},
    "profile_updates": {{
        "demographics": {{}},
        "dining_habits": {{}},
        "inferred_info": {{}}
    }}
}}

Note:
- Only provide the "preferences" field when intent is "query". For "chat" intent, preferences can be null
- The "profile_updates" field is optional, only provide it when you can infer new user information from the message (e.g., user mentions "I'm a student", "I'm on a budget", "I like spicy food", etc.)
- In profile_updates, only provide fields that have changed or are new, don't provide the complete profile
{profile_context}

Intent criteria:
- "query": User wants restaurant recommendations, searching for restaurants, asking about restaurant information, etc.
- "chat": General greetings, casual conversation, non-restaurant-related questions

Preference extraction guide:
- restaurant_types: Options ["casual", "fine-dining", "fast-casual", "street-food", "buffet", "cafe"] or ["any"]
- flavor_profiles: Options ["spicy", "savory", "sweet", "sour", "mild"] or ["any"]
- dining_purpose: Options "date-night", "family", "friends", "business", "solo", "celebration" or "any"
- budget_range: Extract budget from user message, use default {{"min": 20, "max": 60, "currency": "SGD", "per": "person"}} if not mentioned
- location: Extract location from user message, use "any" if not mentioned

Reply requirements:
- If intent is "query", reply should friendly confirm the user's needs and prepare for recommendations
- If intent is "chat", provide natural and friendly conversational replies
- Use English for replies"""


def get_stream_system_prompt(language: str = "en") -> str:
    """
    根据语言获取流式响应的系统提示词
    
    Args:
        language: 语言代码 ("en" 或 "zh")
        
    Returns:
        系统提示词字符串
    """
    if language == "zh":
        return """你是一个智能餐厅推荐助手。你的任务是友好地回答用户的问题。

如果用户想要推荐餐厅、寻找餐厅、询问餐厅信息等，你应该友好地确认用户需求，并告诉他们可以开始推荐流程。
如果是普通对话、问候、闲聊等，你应该给出自然、友好的对话回复。

回复要求：
- 使用中文
- 自然、友好、有帮助
- 如果是餐厅推荐相关，可以引导用户提供更多信息"""
    else:
        # Default English prompt
        return """You are an intelligent restaurant recommendation assistant. Your task is to answer user questions in a friendly manner.

If the user wants restaurant recommendations, is searching for restaurants, or asking about restaurant information, you should friendly confirm their needs and let them know the recommendation process can begin.
If it's general conversation, greetings, or casual chat, you should provide natural and friendly conversational replies.

Reply requirements:
- Use English
- Be natural, friendly, and helpful
- If it's restaurant-related, guide users to provide more information"""


async def analyze_user_message(
    message: str,
    conversation_history: Optional[list] = None,
    user_profile: Optional[Dict[str, Any]] = None,
    is_in_query_flow: bool = False,
    pending_preferences: Optional[Dict[str, Any]] = None
) -> LLMResponse:
    """
    使用免费大模型 API（Groq 等）分析用户消息，返回意图和回复
    
    Args:
        message: 用户消息
        conversation_history: 对话历史（可选）
        user_profile: 用户画像（可选）
        is_in_query_flow: 是否处于 query 流程中（有待确认的偏好）
        pending_preferences: 待确认的偏好（如果 is_in_query_flow 为 True）
        
    Returns:
        LLMResponse 对象，包含意图和回复
    """
    # 检测用户消息的语言（默认英文）
    language = detect_language(message)
    
    # 如果对话历史存在，也检查历史消息的语言
    if conversation_history:
        for msg in conversation_history[-3:]:  # 检查最近3条消息
            msg_content = msg.get("content", "")
            if detect_language(msg_content) == "zh":
                language = "zh"
                break
    
    # 根据语言、用户画像和状态获取系统提示词（默认英文）
    system_prompt = get_system_prompt(language, user_profile, is_in_query_flow, pending_preferences)

    # 构建消息列表
    messages = [{"role": "system", "content": system_prompt}]
    
    # 添加对话历史（最近5条）
    if conversation_history:
        recent_history = conversation_history[-5:]
        for msg in recent_history:
            messages.append({
                "role": msg.get("role", "user"),
                "content": msg.get("content", "")
            })
    
    # 添加当前用户消息
    messages.append({"role": "user", "content": message})
    
    try:
        # 调用免费大模型 API（Groq 等）
        # 注意：某些模型可能不支持 response_format，需要处理
        try:
            response = await client.chat.completions.create(
                model=LLM_MODEL,
                messages=messages,
                temperature=0.7,
                response_format={"type": "json_object"}  # 强制 JSON 格式
            )
        except Exception as e:
            # 如果模型不支持 response_format，尝试不使用它
            if "response_format" in str(e).lower():
                print(f"Model doesn't support response_format, retrying without it: {e}")
                response = await client.chat.completions.create(
                    model=LLM_MODEL,
                    messages=messages,
                    temperature=0.7
                )
            else:
                raise
        
        # 解析响应
        content = response.choices[0].message.content
        
        # 尝试解析 JSON
        try:
            result = json.loads(content)
            # 验证并返回
            intent = result.get("intent", "chat")
            # 根据当前状态验证意图
            if is_in_query_flow:
                # 在 query 流程中，允许的意图
                if intent not in ["confirmation_yes", "confirmation_no", "query", "chat"]:
                    intent = "chat"  # 默认值
            else:
                # 起始状态，只允许 query 或 chat
                if intent not in ["query", "chat"]:
                    intent = "chat"  # 默认值
            
            # 提取偏好信息（当 intent 为 "query" 或 "confirmation_no"（且提供了新偏好）时）
            preferences = None
            if (intent == "query" or (intent == "confirmation_no" and "preferences" in result and result.get("preferences"))) and "preferences" in result:
                preferences = result.get("preferences")
                # 验证偏好格式
                if preferences and isinstance(preferences, dict):
                    # 确保所有必需字段存在
                    validated_prefs = {
                        "restaurant_types": preferences.get("restaurant_types", ["any"]),
                        "flavor_profiles": preferences.get("flavor_profiles", ["any"]),
                        "dining_purpose": preferences.get("dining_purpose", "any"),
                        "budget_range": preferences.get("budget_range", {
                            "min": 20,
                            "max": 60,
                            "currency": "SGD",
                            "per": "person"
                        }),
                        "location": preferences.get("location", "any")
                    }
                    preferences = validated_prefs
            
            # 提取用户画像更新信息
            profile_updates = None
            if "profile_updates" in result and result.get("profile_updates"):
                profile_updates = result.get("profile_updates")
                # 验证并清理空字典
                if isinstance(profile_updates, dict):
                    # 移除空字典
                    cleaned_updates = {}
                    for key, value in profile_updates.items():
                        if value and isinstance(value, dict) and len(value) > 0:
                            cleaned_updates[key] = value
                    if cleaned_updates:
                        profile_updates = cleaned_updates
                    else:
                        profile_updates = None
            
            default_reply = "Sorry, I didn't understand your question." if language == "en" else "抱歉，我没有理解您的问题。"
            return LLMResponse(
                intent=intent,
                reply=result.get("reply", default_reply),
                confidence=float(result.get("confidence", 0.8)),
                preferences=preferences,
                profile_updates=profile_updates
            )
        except json.JSONDecodeError:
            # 如果不是 JSON 格式，尝试从文本中提取意图
            content_lower = content.lower()
            # 简单的意图判断（支持中英文关键词）
            if language == "zh":
                query_keywords = ["推荐", "餐厅", "吃饭", "美食", "找", "想吃", "推荐一下"]
            else:
                query_keywords = ["recommend", "restaurant", "food", "dining", "find", "looking for", "want", "eat"]
            is_query = any(keyword in content_lower for keyword in query_keywords)
            
            # 如果不是 query，preferences 为 None
            preferences = None
            
            return LLMResponse(
                intent="query" if is_query else "chat",
                reply=content,  # 直接使用模型返回的内容
                confidence=0.7 if is_query else 0.8,
                preferences=preferences,
                profile_updates=None
            )
        
    except json.JSONDecodeError as e:
        # JSON 解析失败，尝试提取文本
        print(f"JSON decode error: {e}")
        error_msg = "Sorry, I encountered a technical issue. Please try again later." if language == "en" else "抱歉，我遇到了一些技术问题，请稍后再试。"
        return LLMResponse(
            intent="chat",
            reply=error_msg,
            confidence=0.5,
            preferences=None,
            profile_updates=None
        )
    except Exception as e:
        print(f"LLM API error: {e}")
        error_msg = "Sorry, the service is temporarily unavailable. Please try again later." if language == "en" else "抱歉，服务暂时不可用，请稍后再试。"
        return LLMResponse(
            intent="chat",
            reply=error_msg,
            confidence=0.3,
            preferences=None,
            profile_updates=None
        )


async def generate_confirmation_message(
    query: str,
    preferences: Dict[str, Any],
    language: str = "en",
    user_profile: Optional[Dict[str, Any]] = None
) -> str:
    """
    使用 LLM 生成自然的确认消息
    
    Args:
        query: 用户原始查询
        preferences: 提取的偏好设置
        language: 语言代码 ("en" 或 "zh")
        user_profile: 用户画像（可选）
        
    Returns:
        自然的确认消息文本
    """
    # 构建偏好描述
    prefs_description = []
    
    if preferences.get("restaurant_types") and preferences["restaurant_types"] != ["any"]:
        type_names = {
            "casual": "casual dining" if language == "en" else "休闲餐厅",
            "fine-dining": "fine dining" if language == "en" else "高级餐厅",
            "fast-casual": "fast casual" if language == "en" else "快休闲",
            "street-food": "street food" if language == "en" else "街头小吃",
            "buffet": "buffet" if language == "en" else "自助餐",
            "cafe": "cafe" if language == "en" else "咖啡厅"
        }
        types = [type_names.get(t, t) for t in preferences["restaurant_types"]]
        if language == "zh":
            prefs_description.append(f"餐厅类型：{', '.join(types)}")
        else:
            prefs_description.append(f"restaurant type: {', '.join(types)}")
    
    if preferences.get("flavor_profiles") and preferences["flavor_profiles"] != ["any"]:
        flavor_names = {
            "spicy": "spicy" if language == "en" else "辣",
            "savory": "savory" if language == "en" else "咸香",
            "sweet": "sweet" if language == "en" else "甜",
            "sour": "sour" if language == "en" else "酸",
            "mild": "mild" if language == "en" else "清淡"
        }
        flavors = [flavor_names.get(f, f) for f in preferences["flavor_profiles"]]
        if language == "zh":
            prefs_description.append(f"口味：{', '.join(flavors)}")
        else:
            prefs_description.append(f"flavor: {', '.join(flavors)}")
    
    if preferences.get("dining_purpose") and preferences["dining_purpose"] != "any":
        purpose_names = {
            "date-night": "a romantic date" if language == "en" else "浪漫约会",
            "family": "family dining" if language == "en" else "家庭聚餐",
            "friends": "dining with friends" if language == "en" else "朋友聚会",
            "business": "business meeting" if language == "en" else "商务用餐",
            "solo": "solo dining" if language == "en" else "独自用餐",
            "celebration": "celebration" if language == "en" else "庆祝活动"
        }
        purpose = purpose_names.get(preferences["dining_purpose"], preferences["dining_purpose"])
        if language == "zh":
            prefs_description.append(f"用餐目的：{purpose}")
        else:
            prefs_description.append(f"for {purpose}")
    
    budget = preferences.get("budget_range", {})
    if budget.get("min") or budget.get("max"):
        if budget.get("min") and budget.get("max"):
            if language == "zh":
                prefs_description.append(f"预算：{budget['min']}-{budget['max']} 新币每人")
            else:
                prefs_description.append(f"budget around {budget['min']}-{budget['max']} SGD per person")
        elif budget.get("min"):
            if language == "zh":
                prefs_description.append(f"最低预算：{budget['min']} 新币每人")
            else:
                prefs_description.append(f"minimum budget of {budget['min']} SGD per person")
        elif budget.get("max"):
            if language == "zh":
                prefs_description.append(f"最高预算：{budget['max']} 新币每人")
            else:
                prefs_description.append(f"budget up to {budget['max']} SGD per person")
    
    if preferences.get("location") and preferences["location"] != "any":
        if language == "zh":
            prefs_description.append(f"位置：{preferences['location']}")
        else:
            prefs_description.append(f"location: {preferences['location']}")
    
    prefs_text = ", ".join(prefs_description) if prefs_description else ("无特定偏好" if language == "zh" else "no specific preferences")
    
    if language == "zh":
        prompt = f"""用户说："{query}"

根据用户的查询，我提取了以下偏好信息：
{prefs_text}

请生成一个自然、友好、对话式的确认消息，询问用户这些偏好是否正确。要求：
1. 不要使用列表格式（不要用 • 或 -）
2. 用自然语言描述，就像和朋友聊天一样，要流畅自然
3. 语气要友好、轻松、对话式
4. 可以适当引用用户原话中的关键词，让消息更贴合用户的需求
5. 最后询问"这样对吗？"或"对吗？"等自然的问题
6. 如果某些偏好是默认值（如"any"），可以省略不提
7. 消息长度控制在2-3句话，不要太长

只返回确认消息，不要其他内容。"""
    else:
        prompt = f"""User said: "{query}"

Based on the user's query, I extracted the following preferences:
{prefs_text}

Please generate a natural, friendly, conversational confirmation message asking if these preferences are correct. Requirements:
1. Don't use list format (no • or -)
2. Describe in natural language, like chatting with a friend, be fluent and natural
3. Be friendly, casual, and conversational in tone
4. You can reference keywords from the user's original query to make the message more relevant
5. End with "Is this correct?" or "Does this sound right?" or similar natural questions
6. If some preferences are default values (like "any"), you can omit them
7. Keep the message to 2-3 sentences, not too long

Only return the confirmation message, nothing else."""
    
    try:
        messages = [{"role": "user", "content": prompt}]
        response = await client.chat.completions.create(
            model=LLM_MODEL,
            messages=messages,
            temperature=0.8,  # 稍高的温度让回复更自然
            max_tokens=200
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"Error generating confirmation message: {e}")
        # 回退到简单的自然语言格式
        if language == "zh":
            return f"根据您的需求，我理解您想要{prefs_text}。这样对吗？"
        else:
            return f"Based on your request, I understand you're looking for {prefs_text}. Is this correct?"


async def stream_llm_response(
    message: str,
    conversation_history: Optional[list] = None
) -> AsyncIterator[str]:
    """
    流式生成 LLM 回复（用于逐字显示）
    
    注意：流式模式下不使用 JSON 格式，直接返回文本内容
    
    Args:
        message: 用户消息
        conversation_history: 对话历史（可选）
        
    Yields:
        回复文本的字符片段
    """
    # 检测用户消息的语言（默认英文）
    language = detect_language(message)
    
    # 如果对话历史存在，也检查历史消息的语言
    if conversation_history:
        for msg in conversation_history[-3:]:  # 检查最近3条消息
            msg_content = msg.get("content", "")
            if detect_language(msg_content) == "zh":
                language = "zh"
                break
    
    # 根据语言获取系统提示词（默认英文）
    system_prompt = get_stream_system_prompt(language)

    messages = [{"role": "system", "content": system_prompt}]
    
    if conversation_history:
        recent_history = conversation_history[-5:]
        for msg in recent_history:
            messages.append({
                "role": msg.get("role", "user"),
                "content": msg.get("content", "")
            })
    
    messages.append({"role": "user", "content": message})
    
    try:
        # 流式调用免费大模型 API（Groq 等）
        stream = await client.chat.completions.create(
            model=LLM_MODEL,
            messages=messages,
            temperature=0.7,
            stream=True
        )
        
        async for chunk in stream:
            if chunk.choices[0].delta.content:
                content = chunk.choices[0].delta.content
                yield content
            
    except Exception as e:
        print(f"Stream LLM error: {e}")
        error_msg = "Sorry, the service is temporarily unavailable. Please try again later." if language == "en" else "抱歉，服务暂时不可用，请稍后再试。"
        for char in error_msg:
            yield char

