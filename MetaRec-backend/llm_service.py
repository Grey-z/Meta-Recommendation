"""
LLM 服务模块
使用免费大模型 API（Groq）进行意图识别和对话回复
支持多种免费 API：Groq、Together AI、OpenRouter 等
"""
import json
import os
import re
from typing import Dict, Any, Optional, AsyncIterator, Union
from pydantic import BaseModel
from openai import AsyncOpenAI, AsyncAzureOpenAI
from dotenv import load_dotenv

from langgraph_metarec.nodes.food_intent import (
    is_meaningful_food_intent,
    normalize_food_intent,
)

load_dotenv()

# 获取 API 配置，支持多种免费 API
# 默认使用 Groq（完全免费，速度快）
LLM_MODEL = os.getenv("LLM_MODEL", "llama-3.3-70b-versatile")


def _resolve_model(model: Optional[str]) -> str:
    return model or LLM_MODEL


def _format_llm_exception(exc: Exception) -> str:
    cause = getattr(exc, "__cause__", None)
    context = getattr(exc, "__context__", None)
    parts = [f"{type(exc).__name__}: {exc!r}"]
    if cause:
        parts.append(f"cause={type(cause).__name__}: {cause!r}")
    if context and context is not cause:
        parts.append(f"context={type(context).__name__}: {context!r}")
    return "; ".join(parts)


def _get_text_max_tokens(default: int = 1024) -> int:
    try:
        return max(1, int(os.getenv("LLM_TEXT_MAX_TOKENS", str(default))))
    except (TypeError, ValueError):
        return default


def _extract_message_content(response: Any) -> str:
    try:
        message = response.choices[0].message
    except (AttributeError, IndexError, TypeError):
        return ""

    content = getattr(message, "content", None)
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if isinstance(text, str):
                    parts.append(text)
            else:
                text = getattr(item, "text", None) or getattr(item, "content", None)
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts).strip()

    text = getattr(response.choices[0], "text", None)
    if isinstance(text, str):
        return text.strip()
    return ""


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


def is_recommendation_request(text: str) -> bool:
    """
    判断用户是否明确在请求推荐或查找。
    规则偏保守：宁可判为 chat，也避免把普通闲聊误判为推荐请求。
    """
    if not text or not isinstance(text, str):
        return False

    t = text.strip()
    if not t:
        return False

    language = detect_language(t)
    t_lower = t.lower()

    if language == "zh":
        # 直接表达推荐/查找诉求
        if re.search(r"(推荐|帮我推荐|帮我找|帮我选|想找|想买|哪里吃|吃什么|想吃)", t):
            return True
        has_domain_topic = re.search(
            r"(餐厅|美食|火锅|川菜|寿司|烤肉|咖啡|晚餐|午餐|早餐|电影|影片|电视剧|音乐|歌曲|歌单|书|小说|商品|产品|礼物|耳机|电脑|手机)",
            t,
        )
        has_request_intent = re.search(r"(想|要|找|推荐|哪里|吃|买|选)", t)
        return bool(has_domain_topic and has_request_intent)

    # English
    if re.search(
        r"\b(recommend|suggest|find|search|looking\s+for|where\s+to\s+eat|what\s+to\s+eat|movie|movies|film|music|song|playlist|book|books|novel|product|products|shopping|buy|restaurant|restaurants|cuisine)\b",
        t_lower,
    ):
        return True

    if re.search(r"\b(i\s+want|i\s+need|i'm\s+craving|help\s+me\s+find)\b", t_lower) and re.search(
        r"\b(food|eat|dinner|lunch|breakfast|brunch|movie|music|book|product|gift|headphones|laptop|phone)\b", t_lower
    ):
        return True

    return False


def has_meaningful_preferences(preferences: Optional[Dict[str, Any]]) -> bool:
    """
    判断 preferences 是否包含可用于推荐的有效信息。
    仅用于 LLM 意图的语义后处理，不做关键词检索。
    """
    if not preferences or not isinstance(preferences, dict):
        return False

    # 显式菜系/菜品意图本身即为可用于推荐的信息
    if is_meaningful_food_intent(preferences.get("food_intent")):
        return True

    restaurant_types = preferences.get("restaurant_types", [])
    if isinstance(restaurant_types, list) and any(t and t != "any" for t in restaurant_types):
        return True

    flavor_profiles = preferences.get("flavor_profiles", [])
    if isinstance(flavor_profiles, list) and any(f and f != "any" for f in flavor_profiles):
        return True

    dining_purpose = preferences.get("dining_purpose", "any")
    if dining_purpose and dining_purpose != "any":
        return True

    location = preferences.get("location", "any")
    if location and location != "any":
        return True

    budget = preferences.get("budget_range", {})
    if isinstance(budget, dict):
        budget_min = budget.get("min")
        budget_max = budget.get("max")
        # 默认预算 20-60 视为信息量较低
        if (budget_min, budget_max) not in [(20, 60), (None, None)]:
            return True

    restaurant_keys = {
        "restaurant_types",
        "flavor_profiles",
        "dining_purpose",
        "budget_range",
        "location",
        "food_intent",
    }
    for key, value in preferences.items():
        if key in restaurant_keys:
            continue
        if isinstance(value, list) and any(item not in (None, "", "any") for item in value):
            return True
        if isinstance(value, dict) and any(item not in (None, "", [], {}, "any") for item in value.values()):
            return True
        if value not in (None, "", [], {}, "any"):
            return True

    return False


def _sanitize_retry_count(value: Optional[int], default: int = 2) -> int:
    """规范化重试次数，避免负数与过大值"""
    if value is None:
        value = default
    try:
        retry_count = int(value)
    except (TypeError, ValueError):
        retry_count = default
    return max(0, min(retry_count, 50))


def _infer_intent_from_text(text: str, is_in_query_flow: bool) -> str:
    """
    使用规则在 LLM 格式失败时推断意图，作为兜底逻辑
    """
    lowered = (text or "").lower().strip()

    yes_patterns = [
        "yes", "yeah", "yep", "yup", "correct", "right", "sure", "ok", "okay",
        "是", "对", "好的", "可以", "没错", "正确"
    ]
    no_patterns = [
        "no", "nope", "wrong", "incorrect", "not right", "not correct",
        "不", "不是", "不对", "错误", "不要"
    ]
    query_patterns = [
        "recommend", "restaurant", "food", "dining", "eat", "find", "looking for",
        "movie", "film", "music", "playlist", "book", "product", "shopping", "buy",
        "推荐", "餐厅", "美食", "吃", "找餐厅", "吃饭", "电影", "音乐", "歌单", "书", "小说", "商品", "产品", "购物", "买"
    ]

    has_yes = any(p in lowered for p in yes_patterns)
    has_no = any(p in lowered for p in no_patterns)
    has_query = any(p in lowered for p in query_patterns)

    if is_in_query_flow:
        if has_yes and not has_no:
            return "confirmation_yes"
        if has_no and not has_yes:
            return "confirmation_no"
        if has_query:
            return "query"
        return "chat"

    return "query" if has_query else "chat"


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
        try:
            from profile_model import normalize_profile

            normalized_profile = normalize_profile(user_profile)
        except Exception:
            normalized_profile = user_profile
        demographics = normalized_profile.get("demographics", {})
        constraints = normalized_profile.get("constraints", {})
        taste_persona = normalized_profile.get("taste_persona", "")
        domains = normalized_profile.get("domains", {})
        dining_habits = user_profile.get("dining_habits", {})

        def compact_map(value: Any, fallback: str) -> str:
            if not isinstance(value, dict) or not value:
                return fallback
            parts = []
            for key, item in value.items():
                if item not in (None, "", [], {}):
                    parts.append(f"{key}={item}")
            return ", ".join(parts) if parts else fallback
        
        if language == "zh":
            profile_context = f"""用户画像: general({compact_map(demographics, '未知')}), constraints({compact_map(constraints, '无')}), taste_persona={taste_persona or dining_habits.get('description', '')[:80] or '无'}, domain_preferences={compact_map(domains, '无')}

Profile更新: demographics仅可更新age_range/gender/occupation/location/nationality(字符串,未知为空); dining_habits仅用于兼容餐厅画像字段typical_budget/dietary_restrictions(逗号分隔)/spice_tolerance/description(字符串,未知为空); description需完整覆盖而非追加; 多领域偏好优先通过preferences/preference_form表达,不要把电影/书/音乐偏好写入dining_habits"""
        else:
            profile_context = f"""User profile: general({compact_map(demographics, 'unknown')}), constraints({compact_map(constraints, 'none')}), taste_persona={taste_persona or dining_habits.get('description', '')[:80] or 'none'}, domain_preferences={compact_map(domains, 'none')}

Profile updates: demographics only age_range/gender/occupation/location/nationality(string, empty if unknown); dining_habits is only the legacy restaurant profile slice for typical_budget/dietary_restrictions(comma-separated)/spice_tolerance/description(string, empty if unknown); description must replace not append; express movie/book/music/product preferences through preferences/preference_form, not dining_habits"""
    
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
            return f"""通用推荐助手。等待用户确认推荐请求: {pending_prefs_text}

分析意图并返回JSON:
- "confirmation_yes": 用户确认(如"yes"/"对"/"正确")
- "confirmation_no": 用户拒绝但未提供新偏好
- "query": 用户拒绝并提供新偏好，或新推荐请求
- "chat": 普通对话

JSON格式:
{{"intent":"confirmation_yes|confirmation_no|query|chat", "reply":"回复", "confidence":0.0-1.0, "preferences":{{"domain":"restaurant|movie|music|book|product", "query":"用户原始请求", "genres":["science fiction"], "mood":"relaxing", "tags":["award-winning"], "restaurant_types":["casual"], "flavor_profiles":["spicy"], "dining_purpose":"friends", "budget_range":{{"min":20,"max":60,"currency":"SGD","per":"person"}}, "location":"Chinatown", "food_intent":{{"cuisines":["vietnamese"]或[], "dishes":["pho"]或[], "confidence":0.0-1.0}}}}, "profile_updates":{{"demographics":{{}}, "dining_habits":{{}}}}}}

规则: 只有在用户明确提出推荐/查找/修改推荐条件时才用"query"; 普通闲聊/问候/感谢一律用"chat"; 只填写用户明确表达或上下文强支持的preferences; 非餐厅请求不要填餐厅默认值; "confirmation_yes"和"chat"时preferences为null; profile_updates可选,仅推断新信息时提供,严格遵循字段规则; 当intent为"chat"时先正常对话,并可轻量询问是否需要推荐; 当用户明确说出菜系或菜品(如越南河粉/美式汉堡/Kopi-C)时填写food_intent(cuisines与dishes,并按明确程度给confidence,明确则≥0.6),未提及则food_intent留空
{profile_context}
回复使用中文"""
        else:
            return f"""General recommendation assistant. Waiting for user confirmation: {pending_prefs_text}

Analyze intent and return JSON:
- "confirmation_yes": user confirms("yes"/"correct"/"right")
- "confirmation_no": user rejects without new preferences
- "query": user rejects with new preferences or new request
- "chat": general conversation

JSON format:
{{"intent":"confirmation_yes|confirmation_no|query|chat", "reply":"reply", "confidence":0.0-1.0, "preferences":{{"domain":"restaurant|movie|music|book|product", "query":"original user request", "genres":["science fiction"], "mood":"relaxing", "tags":["award-winning"], "restaurant_types":["casual"], "flavor_profiles":["spicy"], "dining_purpose":"friends", "budget_range":{{"min":20,"max":60,"currency":"SGD","per":"person"}}, "location":"Chinatown", "food_intent":{{"cuisines":["vietnamese"]or[], "dishes":["pho"]or[], "confidence":0.0-1.0}}}}, "profile_updates":{{"demographics":{{}}, "dining_habits":{{}}}}}}

Rules: use "query" only when user explicitly asks for recommendations/search or changes recommendation criteria; greetings/small talk/thanks should be "chat"; only include preferences clearly stated by the user or strongly supported by context; do not fill restaurant defaults for non-restaurant requests; null for "confirmation_yes" and "chat"; profile_updates optional, only when inferring new info, follow field rules strictly; when intent is "chat", reply naturally and optionally ask whether user wants recommendations; when the user explicitly names a cuisine or dish (e.g. Vietnamese Pho, American Burger, Kopi-C), fill food_intent.cuisines and dishes and set confidence by how explicit it is (>=0.6 when clearly stated), else leave food_intent empty
{profile_context}
Use English for replies"""
    else:
        # 起始状态，判断是 chat 还是 query
        if language == "zh":
            return f"""通用推荐助手。分析意图并返回JSON:
- "query": 推荐/查找餐厅、电影、音乐、书籍、商品等
- "chat": 普通对话/问候/闲聊

JSON格式:
{{"intent":"query|chat", "reply":"回复", "confidence":0.0-1.0, "preferences":{{"domain":"restaurant|movie|music|book|product", "query":"用户原始请求", "genres":["science fiction"], "mood":"relaxing", "tags":["award-winning"], "restaurant_types":["casual","fine-dining","fast-casual","street-food","buffet","cafe"], "flavor_profiles":["spicy","savory","sweet","sour","mild"], "dining_purpose":"date-night|family|friends|business|solo|celebration", "budget_range":{{"min":20,"max":60,"currency":"SGD"}}, "location":"Chinatown", "food_intent":{{"cuisines":["vietnamese"]或[], "dishes":["pho"]或[], "confidence":0.0-1.0}}}}, "profile_updates":{{"demographics":{{}}, "dining_habits":{{}}}}}}

规则: 仅当用户明确提出想要推荐/查找时才标记为"query"; 普通闲聊/问候/感谢默认"chat"; 只填写用户明确表达或上下文强支持的preferences; 非餐厅请求不要填餐厅默认值; profile_updates可选,仅推断新信息时提供,严格遵循字段规则; 当intent为"chat"时可轻量询问是否需要推荐; 当用户明确说出菜系或菜品(如越南河粉/美式汉堡/Kopi-C)时填写food_intent(cuisines与dishes,并按明确程度给confidence,明确则≥0.6),未提及则food_intent留空
{profile_context}
回复使用中文"""
        else:
            return f"""General recommendation assistant. Analyze intent and return JSON:
- "query": wants recommendations/search for restaurants, movies, music, books, products, or similar domains
- "chat": general conversation/greetings/casual chat

JSON format:
{{"intent":"query|chat", "reply":"reply", "confidence":0.0-1.0, "preferences":{{"domain":"restaurant|movie|music|book|product", "query":"original user request", "genres":["science fiction"], "mood":"relaxing", "tags":["award-winning"], "restaurant_types":["casual","fine-dining","fast-casual","street-food","buffet","cafe"], "flavor_profiles":["spicy","savory","sweet","sour","mild"], "dining_purpose":"date-night|family|friends|business|solo|celebration", "budget_range":{{"min":20,"max":60,"currency":"SGD"}}, "location":"Chinatown", "food_intent":{{"cuisines":["vietnamese"]or[], "dishes":["pho"]or[], "confidence":0.0-1.0}}}}, "profile_updates":{{"demographics":{{}}, "dining_habits":{{}}}}}}

Rules: mark as "query" only when user explicitly asks for recommendations/search; greetings/small talk/thanks should be "chat"; only include preferences clearly stated by the user or strongly supported by context; do not fill restaurant defaults for non-restaurant requests; profile_updates optional, only when inferring new info, follow field rules strictly; when intent is "chat", reply naturally and optionally ask whether the user wants recommendations; when the user explicitly names a cuisine or dish (e.g. Vietnamese Pho, American Burger, Kopi-C), fill food_intent.cuisines and dishes and set confidence by how explicit it is (>=0.6 when clearly stated), else leave food_intent empty
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
        return """通用推荐助手。友好回答用户问题。如用户想要推荐/查找餐厅、电影、音乐、书籍、商品等，确认需求并告知可开始推荐。如普通对话/问候/闲聊，给出自然友好回复。使用中文，自然友好有帮助，可引导提供更多偏好信息"""
    else:
        return """General recommendation assistant. Answer questions friendly. If user wants recommendations/search for restaurants, movies, music, books, products, or similar domains, confirm needs and mention the recommendation process. If general conversation/greetings/casual chat, provide natural friendly replies. Use English and guide for more preference details when helpful."""


async def summarize_conversation(
    client: Union[AsyncOpenAI, AsyncAzureOpenAI],
    prior_summary: str,
    new_turns: str,
    model: str = LLM_MODEL,
) -> str:
    """Fold new (rolled-out) turns into a running conversation summary.

    Uses the fast chat model — summarization is cheap and runs off the reply path.
    Returns the prior summary unchanged on any failure so the caller can no-op.
    """
    model = _resolve_model(model)
    system_prompt = (
        "You maintain a running summary of an ongoing multi-domain recommendation chat for MetaRec. "
        "Combine the previous summary with the new turns into ONE updated summary of at most "
        "120 words. Capture: any concise stable personal details the user shares (e.g. their "
        "name, context, or who they are with); what the user wants, the recommendation domain, "
        "constraints/preferences (genre, mood, product need, cuisine/dish, budget, location, occasion, dietary needs), recommendations already shown and the user's "
        "reactions (liked/disliked and why), and any decisions. Keep personal details brief and "
        "never drop ones already in the previous summary. Plain prose, no preamble, no bullet labels."
    )
    user_prompt = (
        f"Previous summary:\n{prior_summary or '(none yet)'}\n\n"
        f"New turns:\n{new_turns}\n\nUpdated summary:"
    )
    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
        )
        return (response.choices[0].message.content or "").strip() or prior_summary
    except Exception as exc:  # noqa: BLE001 - summary is best-effort
        print(f"[llm_service] summarize_conversation failed: {exc}")
        return prior_summary


async def analyze_user_message(
    client: Union[AsyncOpenAI, AsyncAzureOpenAI],
    message: str,
    conversation_history: Optional[list] = None,
    user_profile: Optional[Dict[str, Any]] = None,
    is_in_query_flow: bool = False,
    pending_preferences: Optional[Dict[str, Any]] = None,
    model: str = LLM_MODEL,
    max_format_retries: Optional[int] = None,
    extra_context: Optional[str] = None,
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
    model = _resolve_model(model)
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

    # In-conversation memory: prior turns, current preferences, and shown/disliked
    # places so relative refinements ("cheaper", "the second one") resolve correctly.
    if extra_context:
        system_prompt = f"{system_prompt}\n\n{extra_context}"

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
    
    max_retries = _sanitize_retry_count(
        max_format_retries,
        default=int(os.getenv("LLM_MAX_FORMAT_RETRIES", "2"))
    )
    default_reply = "Sorry, I didn't understand your question." if language == "en" else "抱歉，我没有理解您的问题。"
    strict_retry_prompt = (
        "Your previous output was invalid. Reply with JSON object only and follow the exact schema."
        if language == "en"
        else "你上一条输出格式无效。请只返回 JSON 对象，并严格遵循既定字段格式。"
    )

    last_raw_content = ""
    last_exception: Optional[Exception] = None

    for attempt in range(max_retries + 1):
        attempt_messages = list(messages)
        if attempt > 0:
            attempt_messages.append({"role": "system", "content": strict_retry_prompt})

        try:
            # 调用免费大模型 API（Groq 等）
            # 注意：某些模型可能不支持 response_format，需要处理
            try:
                response = await client.chat.completions.create(
                    model=model,
                    messages=attempt_messages,
                    temperature=0.7,
                    response_format={"type": "json_object"}  # 强制 JSON 格式
                )
            except Exception as e:
                if "response_format" in str(e).lower():
                    print(f"Model doesn't support response_format, retrying without it: {e}")
                    response = await client.chat.completions.create(
                        model=model,
                        messages=attempt_messages,
                        temperature=0.7
                    )
                else:
                    raise

            content = response.choices[0].message.content or ""
            last_raw_content = content

            # 解析并验证 JSON
            result = json.loads(content)
            if not isinstance(result, dict):
                raise ValueError("LLM output JSON is not an object")

            allowed_intents = ["confirmation_yes", "confirmation_no", "query", "chat"] if is_in_query_flow else ["query", "chat"]
            intent = result.get("intent")
            if not isinstance(intent, str) or intent not in allowed_intents:
                raise ValueError(f"Invalid intent: {intent}")

            # 提取偏好信息（当 intent 为 "query" 或 "confirmation_no"(且有新偏好)时）
            preferences = None
            has_update_prefs = intent == "query" or (intent == "confirmation_no" and bool(result.get("preferences")))
            if has_update_prefs and "preferences" in result:
                preferences = result.get("preferences")
                if preferences and isinstance(preferences, dict):
                    cleaned_preferences = {
                        key: value
                        for key, value in preferences.items()
                        if value not in (None, "", [], {})
                    }
                    if "food_intent" in cleaned_preferences:
                        food_intent = normalize_food_intent(cleaned_preferences.get("food_intent"))
                        if is_meaningful_food_intent(food_intent):
                            cleaned_preferences["food_intent"] = food_intent
                        else:
                            cleaned_preferences.pop("food_intent", None)
                    preferences = cleaned_preferences or None
                else:
                    preferences = None

            profile_updates = None
            if "profile_updates" in result and result.get("profile_updates"):
                raw_updates = result.get("profile_updates")
                if isinstance(raw_updates, dict):
                    cleaned_updates = {
                        k: v for k, v in raw_updates.items()
                        if isinstance(v, dict) and len(v) > 0
                    }
                    profile_updates = cleaned_updates or None

            confidence = result.get("confidence", 0.8)
            try:
                confidence = float(confidence)
            except (TypeError, ValueError):
                confidence = 0.8
            confidence = max(0.0, min(1.0, confidence))

            # 起始状态下的语义后处理：
            # 由 LLM 的 intent + confidence + preferences 信息量共同决定是否进入推荐流程。
            if not is_in_query_flow and intent == "query":
                prefs_meaningful = has_meaningful_preferences(preferences) or is_recommendation_request(message)
                if confidence < 0.6 and not prefs_meaningful:
                    intent = "chat"
                    preferences = None
                elif confidence < 0.75 and not prefs_meaningful:
                    intent = "chat"
                    preferences = None

            reply = result.get("reply", default_reply)
            if not isinstance(reply, str) or not reply.strip():
                reply = default_reply

            if intent == "chat":
                if language == "zh":
                    if "推荐" not in reply:
                        reply = f"{reply}\n\n如果你愿意，我也可以按偏好帮你推荐餐厅、电影、音乐、书籍或商品。"
                else:
                    if "recommend" not in reply.lower():
                        reply = f"{reply}\n\nIf you want, I can also recommend restaurants, movies, music, books, or products by your preferences."

            return LLMResponse(
                intent=intent,
                reply=reply,
                confidence=confidence,
                preferences=preferences,
                profile_updates=profile_updates
            )
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            last_exception = e
            if attempt < max_retries:
                continue

            # 最终回退：用规则推断意图，避免流程中断
            fallback_intent = _infer_intent_from_text(message, is_in_query_flow)
            if not is_in_query_flow and fallback_intent == "chat" and is_recommendation_request(message):
                fallback_intent = "query"
            fallback_reply = last_raw_content.strip() if isinstance(last_raw_content, str) and last_raw_content.strip() else default_reply
            if fallback_intent == "chat":
                if language == "zh":
                    if "推荐" not in fallback_reply:
                        fallback_reply = f"{fallback_reply}\n\n如果你愿意，我也可以按偏好帮你推荐餐厅、电影、音乐、书籍或商品。"
                else:
                    if "recommend" not in fallback_reply.lower():
                        fallback_reply = f"{fallback_reply}\n\nIf you want, I can also recommend restaurants, movies, music, books, or products by your preferences."
            return LLMResponse(
                intent=fallback_intent,
                reply=fallback_reply,
                confidence=0.6,
                preferences=None,
                profile_updates=None
            )
        except Exception as e:
            last_exception = e
            print(f"LLM API error: {_format_llm_exception(e)}")
            error_msg = "Sorry, the service is temporarily unavailable. Please try again later." if language == "en" else "抱歉，服务暂时不可用，请稍后再试。"
            return LLMResponse(
                intent="chat",
                reply=error_msg,
                confidence=0.3,
                preferences=None,
                profile_updates=None
            )

    # 理论上不会到这里，作为安全兜底
    if last_exception:
        print(f"Unexpected fallback after retries: {last_exception}")
    error_msg = "Sorry, I encountered a technical issue. Please try again later." if language == "en" else "抱歉，我遇到了一些技术问题，请稍后再试。"
    return LLMResponse(
        intent="chat",
        reply=error_msg,
        confidence=0.3,
        preferences=None,
        profile_updates=None
    )


def _humanize_pref_key(key: str, language: str = "en") -> str:
    labels_zh = {
        "restaurant_types": "餐厅类型", "flavor_profiles": "口味", "dining_purpose": "用餐目的",
        "location": "位置", "genres": "类型", "exclude_genres": "排除类型", "tags": "标签",
        "dietary_restrictions": "饮食限制", "typical_budget": "预算", "spice_tolerance": "辣度",
    }
    labels_en = {
        "restaurant_types": "restaurant type", "flavor_profiles": "flavor", "dining_purpose": "occasion",
        "location": "location", "genres": "genres", "exclude_genres": "exclude genres", "tags": "tags",
        "dietary_restrictions": "dietary restrictions", "typical_budget": "budget", "spice_tolerance": "spice level",
    }
    table = labels_zh if language == "zh" else labels_en
    return table.get(key, key.replace("_", " "))


def _render_pref_value(value: Any) -> str:
    if isinstance(value, (list, tuple, set)):
        items = [str(v).strip() for v in value if v not in (None, "") and str(v).strip().lower() != "any"]
        return ", ".join(items)
    if isinstance(value, dict):
        return ""  # structured values (food_intent / budget_range) are handled explicitly
    text = str(value).strip()
    return "" if text.lower() in {"", "any"} else text


# Keys handled explicitly above or used as control metadata; excluded from the generic sweep.
_CONFIRMATION_SKIP_KEYS = {"food_intent", "budget_range", "domain", "query", "confidence"}


def _summarize_preferences_for_confirmation(preferences: Dict[str, Any], language: str = "en") -> str:
    """Domain-agnostic NL summary of detected preferences. Special-cases the
    well-known structured shapes (food_intent, budget_range) and renders every
    other meaningful preference generically, so movie/book/music/product confirm
    just as cleanly as restaurant — no per-domain field handling."""
    if not isinstance(preferences, dict):
        return ""
    zh = language == "zh"
    sep = "：" if zh else ": "
    parts: List[str] = []

    food_intent = preferences.get("food_intent")
    if is_meaningful_food_intent(food_intent):
        cuisines = [str(c) for c in (food_intent.get("cuisines") or []) if c]
        dishes = [str(d) for d in (food_intent.get("dishes") or []) if d]
        if cuisines:
            parts.append(("菜系" if zh else "cuisine") + sep + ", ".join(cuisines))
        if dishes:
            parts.append(("菜品" if zh else "dish") + sep + ", ".join(dishes))

    budget = preferences.get("budget_range")
    if isinstance(budget, dict) and (budget.get("min") or budget.get("max")):
        lo, hi = budget.get("min"), budget.get("max")
        label = "预算" if zh else "budget"
        if lo and hi:
            parts.append(f"{label}{sep}{lo}-{hi}")
        elif lo:
            parts.append(f"{label}{sep}≥{lo}")
        elif hi:
            parts.append(f"{label}{sep}≤{hi}")

    for key, value in preferences.items():
        if key in _CONFIRMATION_SKIP_KEYS:
            continue
        rendered = _render_pref_value(value)
        if rendered:
            parts.append(f"{_humanize_pref_key(key, language)}{sep}{rendered}")

    return ("，" if zh else ", ").join(parts)


def _humanize_domain_label(domain: Optional[str], language: str = "en") -> str:
    key = str(domain or "").lower()
    if key in {"", "recommendation", "unknown", "multi_domain"}:
        return "推荐" if language == "zh" else "recommendation"
    zh_labels = {"restaurant": "餐厅", "movie": "电影", "music": "音乐", "book": "书籍", "product": "商品", "hotel": "酒店"}
    return zh_labels.get(key, key) if language == "zh" else key


async def generate_confirmation_message(
    client: Union[AsyncOpenAI, AsyncAzureOpenAI],
    query: str,
    preferences: Dict[str, Any],
    domain: str = "recommendation",
    language: str = "en",
    user_profile: Optional[Dict[str, Any]] = None,
    guide_missing_preferences: bool = False,
    model: str = LLM_MODEL,
    max_text_retries: Optional[int] = None,
) -> str:
    """Generate a natural, domain-aware confirmation message for ANY recommendation
    domain. Restaurant/movie/music/book/product all flow through one path: a generic
    preference summary plus a domain-aware prompt. The request-time preference form
    (attached by the orchestrator) covers refining missing fields, so this message
    only confirms intent."""
    model = _resolve_model(model)
    domain_label = _humanize_domain_label(domain, language)
    prefs_text = _summarize_preferences_for_confirmation(preferences, language)

    if language == "zh":
        if prefs_text:
            prompt = f"""用户想要{domain_label}推荐。用户说："{query}"

识别到的偏好：{prefs_text}

生成自然友好的确认消息(1-2句)：自然语言如聊天，复述将要为其查找的{domain_label}与关键偏好，友好不施压，必须以确认问题结尾(如"这样对吗？")。不要说已经开始查找。只返回确认消息。"""
        else:
            prompt = f"""用户想要{domain_label}推荐。用户说："{query}"

生成自然友好的确认消息(1-2句)：自然语言如聊天，确认将为其查找{domain_label}，必须以确认问题结尾(如"这样对吗？")。不要说已经开始查找。只返回确认消息。"""
    else:
        if prefs_text:
            prompt = f"""The user wants a {domain_label} recommendation. They said: "{query}"

Detected preferences: {prefs_text}

Generate a natural, friendly confirmation (1-2 sentences): conversational, restate the {domain_label} and key preferences you'll look for, friendly and not pushy, and end with a confirmation question (e.g. "Is that correct?"). Do not say you've started searching. Return only the confirmation message."""
        else:
            prompt = f"""The user wants a {domain_label} recommendation. They said: "{query}"

Generate a natural, friendly confirmation (1-2 sentences): conversational, confirm you'll look for a {domain_label} for them, and end with a confirmation question (e.g. "Is that correct?"). Do not say you've started searching. Return only the confirmation message."""

    max_retries = _sanitize_retry_count(
        max_text_retries,
        default=int(os.getenv("LLM_MAX_FORMAT_RETRIES", "2"))
    )
    max_tokens = _get_text_max_tokens()
    for attempt in range(max_retries + 1):
        try:
            messages = [{"role": "user", "content": prompt}]
            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.8,
                max_tokens=max_tokens
            )
            content = _extract_message_content(response)
            if content:
                return content
            raise ValueError(
                f"Empty confirmation content from model={model}; "
                f"try increasing LLM_TEXT_MAX_TOKENS or using a non-reasoning chat model"
            )
        except Exception as e:
            if attempt < max_retries and type(e).__name__ in {"JSONDecodeError", "ValueError", "TypeError"}:
                continue
            print(f"Error generating confirmation message: {_format_llm_exception(e)}")
            detail = (("：" if language == "zh" else ": ") + prefs_text) if prefs_text else ""
            if language == "zh":
                return f"我理解您想要{domain_label}推荐{detail}。这样对吗？"
            return f"Got it — you're looking for a {domain_label} recommendation{detail}. Is that correct?"
