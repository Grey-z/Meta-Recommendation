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
        
        if language == "zh":
            profile_context = f"""用户画像: demographics(age_range={demographics.get('age_range', '') or '未知'}, gender={demographics.get('gender', '') or '未知'}, occupation={demographics.get('occupation', '') or '未知'}, location={demographics.get('location', '') or '未知'}, nationality={demographics.get('nationality', '') or '未知'}), dining_habits(typical_budget={dining_habits.get('typical_budget', '') or '未知'}, dietary_restrictions={dining_habits.get('dietary_restrictions', '') or '无'}, spice_tolerance={dining_habits.get('spice_tolerance', '') or '未知'}, description={dining_habits.get('description', '')[:50] if dining_habits.get('description') else '无'})

Profile更新: demographics仅可更新age_range/gender/occupation/location/nationality(字符串,未知为空); dining_habits仅可更新typical_budget/dietary_restrictions(逗号分隔)/spice_tolerance/description(字符串,未知为空); description需完整覆盖而非追加; preferred_cuisines和favorite_restaurant_types在preferences中管理"""
        else:
            profile_context = f"""User profile: demographics(age_range={demographics.get('age_range', '') or 'unknown'}, gender={demographics.get('gender', '') or 'unknown'}, occupation={demographics.get('occupation', '') or 'unknown'}, location={demographics.get('location', '') or 'unknown'}, nationality={demographics.get('nationality', '') or 'unknown'}), dining_habits(typical_budget={dining_habits.get('typical_budget', '') or 'unknown'}, dietary_restrictions={dining_habits.get('dietary_restrictions', '') or 'none'}, spice_tolerance={dining_habits.get('spice_tolerance', '') or 'unknown'}, description={dining_habits.get('description', '')[:50] if dining_habits.get('description') else 'none'})

Profile updates: demographics only age_range/gender/occupation/location/nationality(string, empty if unknown); dining_habits only typical_budget/dietary_restrictions(comma-separated)/spice_tolerance/description(string, empty if unknown); description must replace not append; preferred_cuisines/favorite_restaurant_types in preferences"""
    
    # 根据状态构建不同的提示词
    if is_in_query_flow:
        # 处于 query 流程中，需要判断确认/拒绝/新查询/回到聊天
        pending_prefs_text = ""
        if pending_preferences:
            # 过滤掉 "any" 值的辅助函数
            def filter_any_values(arr):
                """过滤掉数组中的 'any' 值"""
                if not arr or not isinstance(arr, list):
                    return []
                return [item for item in arr if item and item != "any" and str(item).strip() != ""]
            
            prefs_list = []
            # 处理 restaurant_types
            restaurant_types = pending_preferences.get("restaurant_types", [])
            filtered_types = filter_any_values(restaurant_types) if isinstance(restaurant_types, list) else []
            if filtered_types:
                prefs_list.append(f"餐厅类型: {', '.join(filtered_types)}")
            
            # 处理 flavor_profiles
            flavor_profiles = pending_preferences.get("flavor_profiles", [])
            filtered_flavors = filter_any_values(flavor_profiles) if isinstance(flavor_profiles, list) else []
            if filtered_flavors:
                prefs_list.append(f"口味: {', '.join(filtered_flavors)}")
            
            # 处理 dining_purpose
            dining_purpose = pending_preferences.get("dining_purpose", "")
            if dining_purpose and dining_purpose != "any" and str(dining_purpose).strip() != "":
                prefs_list.append(f"用餐目的: {dining_purpose}")
            
            # 处理 budget_range
            if pending_preferences.get("budget_range"):
                budget = pending_preferences["budget_range"]
                if budget.get("min") and budget.get("max"):
                    prefs_list.append(f"预算: {budget['min']}-{budget['max']} SGD")
            
            # 处理 location
            location = pending_preferences.get("location", "")
            if location and location != "any" and str(location).strip() != "":
                prefs_list.append(f"位置: {location}")
            
            if prefs_list:
                pending_prefs_text = "\n待确认的偏好：" + ", ".join(prefs_list)
        
        if language == "zh":
            return f"""餐厅推荐助手。等待用户确认偏好: {pending_prefs_text}

分析意图并返回JSON:
- "confirmation_yes": 用户确认(如"yes"/"对"/"正确")
- "confirmation_no": 用户拒绝但未提供新偏好
- "query": 用户拒绝并提供新偏好，或新推荐请求
- "chat": 普通对话

JSON格式:
{{"intent":"confirmation_yes|confirmation_no|query|chat", "reply":"回复", "confidence":0.0-1.0, "preferences":{{"restaurant_types":["casual"]或["any"], "flavor_profiles":["spicy"]或["any"], "dining_purpose":"date-night|family|friends|business|solo|any", "budget_range":{{"min":20,"max":60,"currency":"SGD","per":"person"}}, "location":"Chinatown"或"any"}}, "profile_updates":{{"demographics":{{}}, "dining_habits":{{}}}}}}

规则: preferences仅在intent为"query"或"confirmation_no"(有新偏好)时提供; "confirmation_yes"和"chat"时preferences为null; profile_updates可选,仅推断新信息时提供,严格遵循字段规则
{profile_context}
回复使用中文"""
        else:
            return f"""Restaurant recommendation assistant. Waiting for user confirmation: {pending_prefs_text}

Analyze intent and return JSON:
- "confirmation_yes": user confirms("yes"/"correct"/"right")
- "confirmation_no": user rejects without new preferences
- "query": user rejects with new preferences or new request
- "chat": general conversation

JSON format:
{{"intent":"confirmation_yes|confirmation_no|query|chat", "reply":"reply", "confidence":0.0-1.0, "preferences":{{"restaurant_types":["casual"]or["any"], "flavor_profiles":["spicy"]or["any"], "dining_purpose":"date-night|family|friends|business|solo|any", "budget_range":{{"min":20,"max":60,"currency":"SGD","per":"person"}}, "location":"Chinatown"or"any"}}, "profile_updates":{{"demographics":{{}}, "dining_habits":{{}}}}}}

Rules: preferences only when intent is "query" or "confirmation_no"(with new prefs); null for "confirmation_yes" and "chat"; profile_updates optional, only when inferring new info, follow field rules strictly
{profile_context}
Use English for replies"""
    else:
        # 起始状态，判断是 chat 还是 query
        if language == "zh":
            return f"""餐厅推荐助手。分析意图并返回JSON:
- "query": 推荐餐厅/寻找餐厅/询问餐厅信息
- "chat": 普通对话/问候/闲聊

JSON格式:
{{"intent":"query|chat", "reply":"回复", "confidence":0.0-1.0, "preferences":{{"restaurant_types":["casual","fine-dining","fast-casual","street-food","buffet","cafe"]或["any"], "flavor_profiles":["spicy","savory","sweet","sour","mild"]或["any"], "dining_purpose":"date-night|family|friends|business|solo|celebration|any", "budget_range":{{"min":20,"max":60,"currency":"SGD"}}, "location":"Chinatown"或"any"}}, "profile_updates":{{"demographics":{{}}, "dining_habits":{{}}}}}}

规则: preferences仅在"query"时提供,"chat"时为null; profile_updates可选,仅推断新信息时提供,严格遵循字段规则; budget_range未提及则默认20-60 SGD; location未提及则"any"
{profile_context}
回复使用中文"""
        else:
            return f"""Restaurant recommendation assistant. Analyze intent and return JSON:
- "query": wants recommendations/searches restaurants/asks about restaurants
- "chat": general conversation/greetings/casual chat

JSON format:
{{"intent":"query|chat", "reply":"reply", "confidence":0.0-1.0, "preferences":{{"restaurant_types":["casual","fine-dining","fast-casual","street-food","buffet","cafe"]or["any"], "flavor_profiles":["spicy","savory","sweet","sour","mild"]or["any"], "dining_purpose":"date-night|family|friends|business|solo|celebration|any", "budget_range":{{"min":20,"max":60,"currency":"SGD"}}, "location":"Chinatown"or"any"}}, "profile_updates":{{"demographics":{{}}, "dining_habits":{{}}}}}}

Rules: preferences only when "query", null for "chat"; profile_updates optional, only when inferring new info, follow field rules strictly; budget_range default 20-60 SGD if not mentioned; location default "any" if not mentioned
{profile_context}
Use English for replies"""


def get_stream_system_prompt(language: str = "en") -> str:
    """
    根据语言获取流式响应的系统提示词
    
    Args:
        language: 语言代码 ("en" 或 "zh")
        
    Returns:
        系统提示词字符串
    """
    if language == "zh":
        return """餐厅推荐助手。友好回答用户问题。如用户想要推荐餐厅/寻找餐厅/询问餐厅信息，确认需求并告知可开始推荐。如普通对话/问候/闲聊，给出自然友好回复。使用中文，自然友好有帮助，餐厅相关可引导提供更多信息"""
    else:
        return """Restaurant recommendation assistant. Answer questions friendly. If user wants recommendations/searches/asks about restaurants, confirm needs and mention recommendation process. If general conversation/greetings/casual chat, provide natural friendly replies. Use English, be natural friendly helpful, restaurant-related can guide for more info"""


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
                print(f"preferences: {preferences}")
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
                            "currency": "SGD"
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
    user_profile: Optional[Dict[str, Any]] = None,
    guide_missing_preferences: bool = False
) -> str:
    """
    使用 LLM 生成自然的确认消息
    
    Args:
        query: 用户原始查询
        preferences: 提取的偏好设置
        language: 语言代码 ("en" 或 "zh")
        user_profile: 用户画像（可选）
        guide_missing_preferences: 是否引导用户添加缺失的偏好（默认 False，只确认已有偏好）
        
    Returns:
        自然的确认消息文本
    """
    # 构建偏好描述
    prefs_description = []
    
    # 过滤掉 "any" 值的辅助函数
    def filter_any_values(arr):
        """过滤掉数组中的 'any' 值"""
        if not arr or not isinstance(arr, list):
            return []
        return [item for item in arr if item and item != "any" and str(item).strip() != ""]
    
    # 处理 restaurant_types
    restaurant_types = preferences.get("restaurant_types", [])
    filtered_types = filter_any_values(restaurant_types) if isinstance(restaurant_types, list) else []
    if filtered_types:
        type_names = {
            "casual": "casual dining" if language == "en" else "休闲餐厅",
            "fine-dining": "fine dining" if language == "en" else "高级餐厅",
            "fast-casual": "fast casual" if language == "en" else "快休闲",
            "street-food": "street food" if language == "en" else "街头小吃",
            "buffet": "buffet" if language == "en" else "自助餐",
            "cafe": "cafe" if language == "en" else "咖啡厅"
        }
        types = [type_names.get(t, t) for t in filtered_types]
        if language == "zh":
            prefs_description.append(f"餐厅类型：{', '.join(types)}")
        else:
            prefs_description.append(f"restaurant type: {', '.join(types)}")
    
    # 处理 flavor_profiles
    flavor_profiles = preferences.get("flavor_profiles", [])
    filtered_flavors = filter_any_values(flavor_profiles) if isinstance(flavor_profiles, list) else []
    if filtered_flavors:
        flavor_names = {
            "spicy": "spicy" if language == "en" else "辣",
            "savory": "savory" if language == "en" else "咸香",
            "sweet": "sweet" if language == "en" else "甜",
            "sour": "sour" if language == "en" else "酸",
            "mild": "mild" if language == "en" else "清淡"
        }
        flavors = [flavor_names.get(f, f) for f in filtered_flavors]
        if language == "zh":
            prefs_description.append(f"口味：{', '.join(flavors)}")
        else:
            prefs_description.append(f"flavor: {', '.join(flavors)}")
    
    # 处理 dining_purpose
    dining_purpose = preferences.get("dining_purpose", "")
    if dining_purpose and dining_purpose != "any" and str(dining_purpose).strip() != "":
        purpose_names = {
            "date-night": "a romantic date" if language == "en" else "浪漫约会",
            "family": "family dining" if language == "en" else "家庭聚餐",
            "friends": "dining with friends" if language == "en" else "朋友聚会",
            "business": "business meeting" if language == "en" else "商务用餐",
            "solo": "solo dining" if language == "en" else "独自用餐",
            "celebration": "celebration" if language == "en" else "庆祝活动"
        }
        purpose = purpose_names.get(dining_purpose, dining_purpose)
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
    
    # 处理 location
    location = preferences.get("location", "")
    if location and location != "any" and str(location).strip() != "":
        if language == "zh":
            prefs_description.append(f"位置：{location}")
        else:
            prefs_description.append(f"location: {location}")
    
    prefs_text = ", ".join(prefs_description) if prefs_description else ("无特定偏好" if language == "zh" else "no specific preferences")
    
    # 检查缺失的偏好信息
    missing_info = []
    
    if not preferences.get("restaurant_types") or preferences["restaurant_types"] == ["any"]:
        missing_info.append("餐厅类型" if language == "zh" else "restaurant type")
    
    if not preferences.get("flavor_profiles") or preferences["flavor_profiles"] == ["any"]:
        missing_info.append("口味偏好" if language == "zh" else "flavor preference")
    
    if not preferences.get("dining_purpose") or preferences["dining_purpose"] == "any":
        missing_info.append("用餐目的" if language == "zh" else "dining purpose")
    
    budget = preferences.get("budget_range", {})
    is_default_budget = (budget.get("min") == 20 and budget.get("max") == 60) or (not budget.get("min") and not budget.get("max"))
    if is_default_budget:
        missing_info.append("预算范围" if language == "zh" else "budget range")
    
    if not preferences.get("location") or preferences["location"] == "any":
        missing_info.append("位置偏好" if language == "zh" else "location preference")
    
    missing_info_text = ""
    if missing_info and guide_missing_preferences:
        # 只有在需要引导缺失偏好时才添加缺失信息提示
        if language == "zh":
            missing_info_text = f"\n\n未明确信息：{', '.join(missing_info)}。轻松友好询问是否补充，语气可选轻松，如\"这样可以吗？还是你想指定位置/预算？\""
        else:
            missing_info_text = f"\n\nUnclear info: {', '.join(missing_info)}. Casually ask if user wants to specify, optional relaxed tone, e.g. 'Is this ok, or specify location/budget?'"
    
    if language == "zh":
        if guide_missing_preferences:
            # 引导缺失偏好的模式
            prompt = f"""用户说："{query}"

提取的偏好：{prefs_text}{missing_info_text}

生成自然友好的确认消息(2-3句): 不用列表格式,自然语言如聊天,友好轻松不施压,可引用用户关键词,先确认已提取偏好,缺失信息轻松可选询问(如"这样可以吗？还是你想指定位置？"),不强调"需要信息才能推荐",语气:即使无补充信息也可推荐,补充信息仅可选优化。只返回确认消息。"""
        else:
            # 只确认已有偏好的模式（不引导缺失偏好）
            prompt = f"""用户说："{query}"

提取的偏好：{prefs_text}

生成自然友好的确认消息(2-3句): 不用列表格式,自然语言如聊天,友好轻松不施压,可引用用户关键词,只确认已提取的偏好,不要询问或引导用户补充缺失信息,不要提及缺失的偏好项。只返回确认消息。"""
    else:
        if guide_missing_preferences:
            # 引导缺失偏好的模式
            prompt = f"""User said: "{query}"

Extracted preferences: {prefs_text}{missing_info_text}

Generate natural friendly confirmation message(2-3 sentences): no list format, natural language like chatting, friendly casual not pressuring, can reference user keywords, confirm extracted preferences first, missing info casually optionally ask(e.g. "Is this ok, or specify location?"), don't emphasize needing info for good recommendations, tone: can recommend without additional info, more details just optional. Return only confirmation message."""
        else:
            # 只确认已有偏好的模式（不引导缺失偏好）
            prompt = f"""User said: "{query}"

Extracted preferences: {prefs_text}

Generate natural friendly confirmation message(2-3 sentences): no list format, natural language like chatting, friendly casual not pressuring, can reference user keywords, only confirm the extracted preferences, do NOT ask or guide user to fill missing preferences, do NOT mention missing preference items. Return only confirmation message."""
    
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


async def generate_missing_preferences_guidance(
    preferences: Dict[str, Any],
    language: str = "en",
    user_profile: Optional[Dict[str, Any]] = None
) -> str:
    """
    生成引导用户填写缺失偏好的消息
    
    Args:
        preferences: 当前的偏好设置
        language: 语言代码 ("en" 或 "zh")
        user_profile: 用户画像（可选）
        
    Returns:
        引导用户填写缺失偏好的消息文本
    """
    # 检查缺失的偏好信息
    missing_info = []
    
    if not preferences.get("restaurant_types") or preferences["restaurant_types"] == ["any"]:
        missing_info.append("餐厅类型" if language == "zh" else "restaurant type")
    
    if not preferences.get("flavor_profiles") or preferences["flavor_profiles"] == ["any"]:
        missing_info.append("口味偏好" if language == "zh" else "flavor preference")
    
    if not preferences.get("dining_purpose") or preferences["dining_purpose"] == "any":
        missing_info.append("用餐目的" if language == "zh" else "dining purpose")
    
    budget = preferences.get("budget_range", {})
    is_default_budget = (budget.get("min") == 20 and budget.get("max") == 60) or (not budget.get("min") and not budget.get("max"))
    if is_default_budget:
        missing_info.append("预算范围" if language == "zh" else "budget range")
    
    if not preferences.get("location") or preferences["location"] == "any":
        missing_info.append("位置偏好" if language == "zh" else "location preference")
    
    if not missing_info:
        # 如果没有缺失信息，返回一个友好的消息
        if language == "zh":
            return "好的，我已经了解了您的偏好。让我为您推荐一些餐厅吧！"
        else:
            return "Great! I've got your preferences. Let me recommend some restaurants for you!"
    
    missing_info_text = ", ".join(missing_info)
    
    if language == "zh":
        prompt = f"""用户当前的偏好设置中，以下信息还未明确：{missing_info_text}

生成自然友好的引导消息(2-3句): 不用列表格式,自然语言如聊天,友好轻松不施压,引导用户提供这些缺失的偏好信息,可以举例说明,语气友好鼓励,如"为了更好地为您推荐,可以告诉我您偏好的餐厅类型吗？比如休闲餐厅、高级餐厅等"。只返回引导消息。"""
    else:
        prompt = f"""The following information is missing from user's current preferences: {missing_info_text}

Generate natural friendly guidance message(2-3 sentences): no list format, natural language like chatting, friendly casual not pressuring, guide user to provide these missing preference information, can give examples, friendly encouraging tone, e.g. "To better recommend restaurants for you, could you tell me your preferred restaurant type? For example, casual dining, fine dining, etc.". Return only guidance message."""
    
    try:
        messages = [{"role": "user", "content": prompt}]
        response = await client.chat.completions.create(
            model=LLM_MODEL,
            messages=messages,
            temperature=0.8,
            max_tokens=200
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"Error generating missing preferences guidance: {e}")
        # 回退到简单的引导格式
        if language == "zh":
            return f"为了更好地为您推荐餐厅，可以告诉我您的{missing_info_text}偏好吗？"
        else:
            return f"To better recommend restaurants for you, could you tell me your preferences for {missing_info_text}?"


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

