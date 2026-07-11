"""
LLM 服务模块
使用免费大模型 API（Groq）进行意图识别和对话回复
支持多种免费 API：Groq、Together AI、OpenRouter 等
"""
import json
import os
import re
from typing import Dict, Any, Optional, AsyncIterator, Union, List
from pydantic import BaseModel
from openai import AsyncOpenAI, AsyncAzureOpenAI
from dotenv import load_dotenv

from langgraph_metarec.nodes.food_intent import (
    is_meaningful_food_intent,
    normalize_food_intent,
)
from llm_usage import record_response_usage

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
        if re.search(r"(推荐|帮我推荐|帮我找|帮我选|想找|想买|哪里吃|吃什么|想吃|听什么|看什么|读什么|住哪里|住哪|哪里玩|玩什么)", t):
            return True
        # Natural Chinese recommendation phrasing often asks for "what is good"
        # without saying 推荐/查找 explicitly, e.g. "万能青年旅店有什么歌好听呀".
        if re.search(r"(有什么|有啥|哪些|哪首|哪几首|哪部|哪本).*(好听|好看|好读|值得|推荐)", t):
            return True
        if re.search(r"(歌|歌曲|歌手|乐队|专辑).*(好听|推荐|听)", t):
            return True
        has_domain_topic = re.search(
            r"(餐厅|美食|火锅|川菜|寿司|烤肉|咖啡|晚餐|午餐|早餐|酒店|旅馆|民宿|青旅|住宿|景点|景区|观光|博物馆|美术馆|主题公园|动物园|水族馆|地标|公园|植物园|自然保护区|海滩|瀑布|古迹|纪念碑|灯塔|电影|影片|电视剧|音乐|歌曲|歌单|歌手|乐队|专辑|书|小说|商品|产品|礼物|耳机|电脑|手机)",
            t,
        )
        has_request_intent = re.search(r"(想|要|找|推荐|哪里|哪家|哪些|什么|有啥|有什么|吃|买|选|好听|好看|好读|值得)", t)
        return bool(has_domain_topic and has_request_intent)

    # English
    if re.search(
        r"\b(recommend|suggest|find|search|looking\s+for|where\s+to\s+(eat|stay)|what\s+to\s+(eat|watch|listen|read|do)|which\s+(hotels?|attractions?|museums?|parks?|beaches?)|things\s+to\s+do|good\s+(songs?|movies?|books?|hotels?|attractions?|parks?|beaches?)|best\s+(hotels?|attractions?|museums?|parks?|beaches?)|must-see\s+(attractions?|landmarks?|monuments?)|songs?\s+by|music\s+by|books?\s+by|product|products|shopping|buy|restaurants?|cuisine)\b",
        t_lower,
    ):
        return True

    if re.search(r"\b(i\s+want|i\s+need|i'm\s+craving|help\s+me\s+find)\b", t_lower) and re.search(
        r"\b(food|eat|dinner|lunch|breakfast|brunch|hotel|lodging|accommodation|attraction|sightseeing|museum|movie|music|book|product|gift|headphones|laptop|phone)\b", t_lower
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
        "hotel", "lodging", "accommodation", "attraction", "sightseeing", "things to do", "museum",
        "movie", "film", "music", "playlist", "book", "product", "shopping", "buy",
        "推荐", "餐厅", "美食", "吃", "找餐厅", "吃饭", "酒店", "旅馆", "民宿", "住宿",
        "景点", "景区", "观光", "游玩", "博物馆", "电影", "音乐", "歌单", "歌手", "乐队", "专辑", "书", "小说", "商品", "产品", "购物", "买"
    ]

    has_yes = any(p in lowered for p in yes_patterns)
    has_no = any(p in lowered for p in no_patterns)
    has_query = any(p in lowered for p in query_patterns) or is_recommendation_request(text)

    if is_in_query_flow:
        if has_yes and not has_no:
            return "confirmation_yes"
        if has_no and not has_yes:
            return "confirmation_no"
        if has_query:
            return "query"
        return "chat"

    # Outside HITL, keep the fallback high precision. Bare domain nouns are
    # useful as short refinements while confirming, but ordinary statements
    # such as "I visited a museum yesterday" must remain chat.
    return "query" if is_recommendation_request(text) else "chat"


_PENDING_PREF_LABELS = {
    "zh": {
        "domain": "领域",
        "query": "请求",
        "genres": "类型/曲风",
        "exclude_genres": "排除类型",
        "mood": "氛围",
        "tags": "标签",
        "actors": "演员",
        "directors": "导演",
        "artist": "歌手/艺术家",
        "author": "作者",
        "publisher": "出版社",
        "min_rating": "最低评分",
        "year": "年份",
        "restaurant_types": "餐厅类型",
        "flavor_profiles": "口味",
        "dining_purpose": "用餐目的",
        "budget_range": "预算",
        "location": "位置",
    },
    "en": {
        "domain": "domain",
        "query": "query",
        "genres": "genres",
        "exclude_genres": "excluded genres",
        "mood": "mood",
        "tags": "tags",
        "actors": "actors",
        "directors": "directors",
        "artist": "artist",
        "author": "author",
        "publisher": "publisher",
        "min_rating": "minimum rating",
        "year": "year",
        "restaurant_types": "restaurant types",
        "flavor_profiles": "flavors",
        "dining_purpose": "dining purpose",
        "budget_range": "budget",
        "location": "location",
    },
}


def _pending_pref_value(value: Any) -> str:
    if isinstance(value, (list, tuple, set)):
        return ", ".join(str(item) for item in value if item not in (None, "", "any"))
    if isinstance(value, dict):
        if value.get("min") is not None or value.get("max") is not None:
            currency = value.get("currency") or "SGD"
            low = value.get("min") if value.get("min") is not None else "?"
            high = value.get("max") if value.get("max") is not None else "?"
            return f"{low}-{high} {currency}"
        cuisines = value.get("cuisines") if isinstance(value.get("cuisines"), list) else []
        dishes = value.get("dishes") if isinstance(value.get("dishes"), list) else []
        terms = [str(item) for item in [*cuisines, *dishes] if item]
        return ", ".join(terms) if terms else ""
    text = str(value).strip()
    return "" if text.lower() == "any" else text


def _format_pending_preferences(
    language: str,
    pending_preferences: Optional[Dict[str, Any]],
) -> str:
    if not isinstance(pending_preferences, dict) or not pending_preferences:
        return ""
    labels = _PENDING_PREF_LABELS.get(language, _PENDING_PREF_LABELS["en"])
    ordered_keys = [
        "domain",
        "query",
        "genres",
        "exclude_genres",
        "mood",
        "tags",
        "actors",
        "directors",
        "artist",
        "author",
        "publisher",
        "min_rating",
        "year",
        "restaurant_types",
        "flavor_profiles",
        "dining_purpose",
        "budget_range",
        "location",
        "food_intent",
    ]
    keys = ordered_keys + sorted(set(pending_preferences) - set(ordered_keys))
    parts = []
    for key in keys:
        if key not in pending_preferences:
            continue
        text = _pending_pref_value(pending_preferences.get(key))
        if text:
            parts.append(f"{labels.get(key, key)}: {text}")
    if not parts:
        return ""
    prefix = "待确认的偏好：" if language == "zh" else "Pending preferences: "
    return "\n" + prefix + ", ".join(parts)


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
        pending_prefs_text = _format_pending_preferences(language, pending_preferences)
        
        if language == "zh":
            return f"""通用推荐助手。等待用户确认推荐请求: {pending_prefs_text}

分析意图并返回JSON:
- "confirmation_yes": 用户确认(如"yes"/"对"/"正确")
- "confirmation_no": 用户拒绝但未提供新偏好
- "query": 用户拒绝并提供新偏好，或新推荐请求
- "chat": 普通对话
- 多领域请求必须设置 preferences.domain="multi_domain"，并用 preferences.domains 列出全部领域，例如 ["attraction","hotel"]

JSON格式:
{{"intent":"confirmation_yes|confirmation_no|query|chat", "reply":"回复", "confidence":0.0-1.0, "preferences":{{"domain":"restaurant|hotel|attraction|movie|music|book|product", "query":"用户原始请求", "genres":["science fiction"], "mood":"relaxing", "tags":["award-winning"], "actors":["Cillian Murphy"], "directors":["Christopher Nolan"], "artist":"Daft Punk", "author":"Brandon Sanderson", "publisher":"Tor", "product":"iPhone", "category":"smartphone", "brand":"Apple", "model":"iPhone 14-16", "use_case":"iOS testing", "budget":"<= 1600 SGD", "stars":"4", "amenities":["pool","free wifi"], "attraction_types":["museum","viewpoint"], "restaurant_types":["casual"], "flavor_profiles":["spicy"], "dining_purpose":"friends", "budget_range":{{"min":20,"max":60,"currency":"SGD","per":"person"}}, "location":"Chinatown", "food_intent":{{"cuisines":["vietnamese"]或[], "dishes":["pho"]或[], "confidence":0.0-1.0}}}}, "profile_updates":{{"demographics":{{}}, "dining_habits":{{}}}}}}

规则: 只有在用户明确提出推荐/查找/修改推荐条件时才用"query"; 普通闲聊/问候/感谢一律用"chat"; 只填写用户明确表达或上下文强支持的preferences; 非餐厅请求不要填餐厅默认值; "confirmation_yes"和"chat"时preferences为null; profile_updates可选,仅推断新信息时提供,严格遵循字段规则; 当intent为"chat"时先正常对话,并可轻量询问是否需要推荐; 当用户明确说出菜系或菜品(如越南河粉/美式汉堡/Kopi-C)时填写food_intent(cuisines与dishes,并按明确程度给confidence,明确则≥0.6),未提及则food_intent留空; 仅当用户明确说出时提取命名实体(类似food_intent): 电影提取演员(actors)与导演(directors), 音乐提取歌手(artist)与曲风(genres,如rock/edm/classical), 书籍提取作者(author)与出版社(publisher), 酒店提取目的地(location)、星级(stars)与设施(amenities), 景点提取目的地(location)、景点类型(attraction_types,如museum/theme-park/viewpoint)与预算(budget), 商品提取具体商品(product)、类别(category)、品牌(brand)、型号/版本(model)、用途(use_case)、预算(budget与budget_range), 未提及则留空
{profile_context}
回复使用中文"""
        else:
            return f"""General recommendation assistant. Waiting for user confirmation: {pending_prefs_text}

Analyze intent and return JSON:
- "confirmation_yes": user confirms("yes"/"correct"/"right")
- "confirmation_no": user rejects without new preferences
- "query": user rejects with new preferences or new request
- "chat": general conversation
- For a multi-domain request, set preferences.domain="multi_domain" and list every domain in preferences.domains, e.g. ["attraction","hotel"]

JSON format:
{{"intent":"confirmation_yes|confirmation_no|query|chat", "reply":"reply", "confidence":0.0-1.0, "preferences":{{"domain":"restaurant|hotel|attraction|movie|music|book|product", "query":"original user request", "genres":["science fiction"], "mood":"relaxing", "tags":["award-winning"], "actors":["Cillian Murphy"], "directors":["Christopher Nolan"], "artist":"Daft Punk", "author":"Brandon Sanderson", "publisher":"Tor", "product":"iPhone", "category":"smartphone", "brand":"Apple", "model":"iPhone 14-16", "use_case":"iOS testing", "budget":"<= 1600 SGD", "stars":"4", "amenities":["pool","free wifi"], "attraction_types":["museum","viewpoint"], "restaurant_types":["casual"], "flavor_profiles":["spicy"], "dining_purpose":"friends", "budget_range":{{"min":20,"max":60,"currency":"SGD","per":"person"}}, "location":"Chinatown", "food_intent":{{"cuisines":["vietnamese"]or[], "dishes":["pho"]or[], "confidence":0.0-1.0}}}}, "profile_updates":{{"demographics":{{}}, "dining_habits":{{}}}}}}

Rules: use "query" only when user explicitly asks for recommendations/search or changes recommendation criteria; greetings/small talk/thanks should be "chat"; only include preferences clearly stated by the user or strongly supported by context; do not fill restaurant defaults for non-restaurant requests; null for "confirmation_yes" and "chat"; profile_updates optional, only when inferring new info, follow field rules strictly; when intent is "chat", reply naturally and optionally ask whether user wants recommendations; when the user explicitly names a cuisine or dish (e.g. Vietnamese Pho, American Burger, Kopi-C), fill food_intent.cuisines and dishes and set confidence by how explicit it is (>=0.6 when clearly stated), else leave food_intent empty; extract named entities only when the user explicitly states them (like food_intent) — for movies the actors and directors, for music the artist and genres (e.g. rock, edm, classical), for books the author and publisher, for hotels the destination (location), star class (stars) and amenities, for attractions the destination (location), attraction types (attraction_types, e.g. museum, theme-park, viewpoint) and budget, for products the concrete product, category, brand, model/version, use_case, and budget/budget_range — and leave them out otherwise
{profile_context}
Use English for replies"""
    else:
        # 起始状态，判断是 chat 还是 query
        if language == "zh":
            return f"""通用推荐助手。分析意图并返回JSON:
- "query": 推荐/查找餐厅、酒店、景点、电影、音乐、书籍、商品等
- "chat": 普通对话/问候/闲聊
- 多领域请求必须设置 preferences.domain="multi_domain"，并用 preferences.domains 列出全部领域，例如 ["attraction","hotel"]

JSON格式:
{{"intent":"query|chat", "reply":"回复", "confidence":0.0-1.0, "preferences":{{"domain":"restaurant|hotel|attraction|movie|music|book|product", "query":"用户原始请求", "genres":["science fiction"], "mood":"relaxing", "tags":["award-winning"], "actors":["Cillian Murphy"], "directors":["Christopher Nolan"], "artist":"Daft Punk", "author":"Brandon Sanderson", "publisher":"Tor", "product":"iPhone", "category":"smartphone", "brand":"Apple", "model":"iPhone 14-16", "use_case":"iOS testing", "budget":"<= 1600 SGD", "stars":"4", "amenities":["pool","free wifi"], "attraction_types":["museum","viewpoint"], "restaurant_types":["casual","fine-dining","fast-casual","street-food","buffet","cafe"], "flavor_profiles":["spicy","savory","sweet","sour","mild"], "dining_purpose":"date-night|family|friends|business|solo|celebration", "budget_range":{{"min":20,"max":60,"currency":"SGD"}}, "location":"Chinatown", "food_intent":{{"cuisines":["vietnamese"]或[], "dishes":["pho"]或[], "confidence":0.0-1.0}}}}, "profile_updates":{{"demographics":{{}}, "dining_habits":{{}}}}}}

规则: 仅当用户明确提出想要推荐/查找时才标记为"query"; 普通闲聊/问候/感谢默认"chat"; 只填写用户明确表达或上下文强支持的preferences; 非餐厅请求不要填餐厅默认值; profile_updates可选,仅推断新信息时提供,严格遵循字段规则; 当intent为"chat"时可轻量询问是否需要推荐; 当用户明确说出菜系或菜品(如越南河粉/美式汉堡/Kopi-C)时填写food_intent(cuisines与dishes,并按明确程度给confidence,明确则≥0.6),未提及则food_intent留空; 仅当用户明确说出时提取命名实体(类似food_intent): 电影提取演员(actors)与导演(directors), 音乐提取歌手(artist)与曲风(genres,如rock/edm/classical), 书籍提取作者(author)与出版社(publisher), 酒店提取目的地(location)、星级(stars)与设施(amenities), 景点提取目的地(location)、景点类型(attraction_types,如museum/theme-park/viewpoint)与预算(budget), 商品提取具体商品(product)、类别(category)、品牌(brand)、型号/版本(model)、用途(use_case)、预算(budget与budget_range), 未提及则留空
{profile_context}
回复使用中文"""
        else:
            return f"""General recommendation assistant. Analyze intent and return JSON:
- "query": wants recommendations/search for restaurants, hotels, attractions, movies, music, books, products, or similar domains
- "chat": general conversation/greetings/casual chat
- For a multi-domain request, set preferences.domain="multi_domain" and list every domain in preferences.domains, e.g. ["attraction","hotel"]

JSON format:
{{"intent":"query|chat", "reply":"reply", "confidence":0.0-1.0, "preferences":{{"domain":"restaurant|hotel|attraction|movie|music|book|product", "query":"original user request", "genres":["science fiction"], "mood":"relaxing", "tags":["award-winning"], "actors":["Cillian Murphy"], "directors":["Christopher Nolan"], "artist":"Daft Punk", "author":"Brandon Sanderson", "publisher":"Tor", "product":"iPhone", "category":"smartphone", "brand":"Apple", "model":"iPhone 14-16", "use_case":"iOS testing", "budget":"<= 1600 SGD", "stars":"4", "amenities":["pool","free wifi"], "attraction_types":["museum","viewpoint"], "restaurant_types":["casual","fine-dining","fast-casual","street-food","buffet","cafe"], "flavor_profiles":["spicy","savory","sweet","sour","mild"], "dining_purpose":"date-night|family|friends|business|solo|celebration", "budget_range":{{"min":20,"max":60,"currency":"SGD"}}, "location":"Chinatown", "food_intent":{{"cuisines":["vietnamese"]or[], "dishes":["pho"]or[], "confidence":0.0-1.0}}}}, "profile_updates":{{"demographics":{{}}, "dining_habits":{{}}}}}}

Rules: mark as "query" only when user explicitly asks for recommendations/search; greetings/small talk/thanks should be "chat"; only include preferences clearly stated by the user or strongly supported by context; do not fill restaurant defaults for non-restaurant requests; profile_updates optional, only when inferring new info, follow field rules strictly; when intent is "chat", reply naturally and optionally ask whether the user wants recommendations; when the user explicitly names a cuisine or dish (e.g. Vietnamese Pho, American Burger, Kopi-C), fill food_intent.cuisines and dishes and set confidence by how explicit it is (>=0.6 when clearly stated), else leave food_intent empty; extract named entities only when the user explicitly states them (like food_intent) — for movies the actors and directors, for music the artist and genres (e.g. rock, edm, classical), for books the author and publisher, for hotels the destination (location), star class (stars) and amenities, for attractions the destination (location), attraction types (attraction_types, e.g. museum, theme-park, viewpoint) and budget, for products the concrete product, category, brand, model/version, use_case, and budget/budget_range — and leave them out otherwise
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
        return """通用推荐助手。友好回答用户问题。如用户想要推荐/查找餐厅、酒店、景点、电影、音乐、书籍、商品等，确认需求并告知可开始推荐。如普通对话/问候/闲聊，给出自然友好回复。使用中文，自然友好有帮助，可引导提供更多偏好信息"""
    else:
        return """General recommendation assistant. Answer questions friendly. If user wants recommendations/search for restaurants, hotels, attractions, movies, music, books, products, or similar domains, confirm needs and mention the recommendation process. If general conversation/greetings/casual chat, provide natural friendly replies. Use English and guide for more preference details when helpful."""


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
        record_response_usage(response, model)
        return (response.choices[0].message.content or "").strip() or prior_summary
    except Exception as exc:  # noqa: BLE001 - summary is best-effort
        print(f"[llm_service] summarize_conversation failed: {exc}")
        return prior_summary


# Tunable parameters the gather reasoner is allowed to set per tool. Kept here as
# the prompt's source of truth so the reasoner never invents params the adapters
# don't understand.
_GATHER_TUNABLE_PARAMS: Dict[str, list] = {
    "tmdb.movie.discover": ["with_genres", "without_genres", "with_cast", "with_crew", "min_rating", "year"],
    "tmdb.tv.discover": ["with_genres", "without_genres", "with_cast", "with_crew", "min_rating", "year"],
    "tmdb.movie.search": ["query"],
    "tmdb.tv.search": ["query"],
    "musicbrainz.recording.discover": ["artist", "genres"],
    "gmap.hotel.search": ["query"],
    "osm.hotel.discover": ["location", "stars"],
    "gmap.attraction.search": ["query"],
    "osm.attraction.discover": ["location", "attraction_types"],
    "musicbrainz.recording.search": ["query"],
    "lastfm.track.discover": ["artist", "genres"],
    "openlibrary.book.discover": ["author", "publisher", "subject", "title"],
    "hardcover.book.search": ["query"],
    "amazon.product.search": ["query"],
}


def _safe_parse_action(content: str) -> Optional[Dict[str, Any]]:
    """Parse the reasoner's reply into an action dict, tolerating code fences and
    surrounding prose. Returns None when no usable JSON object is found."""
    if not content:
        return None
    match = re.search(r"\{.*\}", content, re.DOTALL)
    text = match.group(0) if match else content.strip()
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


async def propose_gather_action(
    client: Union[AsyncOpenAI, AsyncAzureOpenAI],
    *,
    query: str,
    domain: str,
    preferences: Dict[str, Any],
    observations: list,
    tools: list,
    found: int,
    target: int,
    model: str = LLM_MODEL,
) -> Optional[Dict[str, Any]]:
    """ReAct reasoner for candidate gathering: given the per-tool candidate counts
    so far, propose the next ``{"tool", "parameters"}`` call that would widen or
    refine the result set — or return ``None`` to stop. Best-effort: any failure
    returns ``None`` so the graph falls back to its deterministic relaxation
    ladder (no tool or LLM is ever assumed to be working)."""
    available = {name: _GATHER_TUNABLE_PARAMS.get(name, ["query"]) for name in tools}
    system_prompt = (
        "You refine a recommendation candidate search for MetaRec. You receive the user "
        f"query, the available {domain} tools with their tunable parameters, and how many "
        "candidates each call returned so far. Propose ONE next tool call that would find "
        "MORE relevant candidates — usually by RELAXING an over-constraining filter (drop "
        "the narrowest one, e.g. release year or a specific actor) or re-running a keyword "
        "search with better terms. Respond with ONLY a JSON object "
        '{"tool": <one of the available tool names>, "parameters": {<tunable params>}}. '
        'If no useful refinement remains, respond {"action": "stop"}. Never invent tool '
        "names or parameters."
    )
    user_prompt = json.dumps(
        {
            "query": query,
            "domain": domain,
            "preferences": preferences,
            "available_tools": available,
            "observations": observations,
            "found": found,
            "target": target,
        },
        ensure_ascii=False,
        default=str,
    )
    try:
        response = await client.chat.completions.create(
            model=_resolve_model(model),
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
        )
        record_response_usage(response, model)
    except Exception as exc:  # noqa: BLE001 - reasoner is best-effort
        print(f"[llm_service] propose_gather_action failed: {_format_llm_exception(exc)}")
        return None
    action = _safe_parse_action(_extract_message_content(response))
    if not isinstance(action, dict) or action.get("tool") not in tools:
        return None  # stop / invalid -> deterministic fallback or break
    params = action.get("parameters")
    return {"tool": action["tool"], "parameters": params if isinstance(params, dict) else {}}


_ITINERARY_SLOTS_MIN = 2
_ITINERARY_SLOTS_MAX = 6
_ITINERARY_TIME_RE = re.compile(r"^([01]?\d|2[0-3]):[0-5]\d$")


async def propose_itinerary_slots(
    client: Union[AsyncOpenAI, AsyncAzureOpenAI],
    *,
    query: str,
    preferences: Optional[Dict[str, Any]] = None,
    model: str = LLM_MODEL,
) -> Optional[list]:
    """Propose an ordered day-plan (slots) for an itinerary request. Returns
    validated slot dicts ready for routing's ``domain_tasks``, or ``None`` on
    ANY failure/invalid plan so the caller keeps the deterministic template
    (no LLM is ever assumed to be working)."""
    from langgraph_metarec.graphs.routing_graph import EXECUTABLE_DOMAINS, tool_tags_for_domain

    domains = sorted(EXECUTABLE_DOMAINS)
    system_prompt = (
        "You plan a one-day itinerary skeleton for MetaRec. Given the user's request "
        "and preferences, respond with ONLY a JSON object "
        '{"slots": [{"domain": <one of: ' + ", ".join(domains) + '>, '
        '"label": <short human label, e.g. "Morning at the museum">, '
        '"time": "HH:MM"}]} '
        f"with {_ITINERARY_SLOTS_MIN}-{_ITINERARY_SLOTS_MAX} slots in chronological order. "
        "Prefer place domains (attraction, restaurant, hotel) unless the user asks "
        "otherwise; include meals at sensible times. Never invent domain names."
    )
    user_prompt = json.dumps(
        {"query": query, "preferences": preferences or {}},
        ensure_ascii=False,
        default=str,
    )
    try:
        response = await client.chat.completions.create(
            model=_resolve_model(model),
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
        )
        record_response_usage(response, model)
    except Exception as exc:  # noqa: BLE001 - proposer is best-effort
        print(f"[llm_service] propose_itinerary_slots failed: {_format_llm_exception(exc)}")
        return None
    action = _safe_parse_action(_extract_message_content(response))
    raw_slots = action.get("slots") if isinstance(action, dict) else None
    if not isinstance(raw_slots, list) or not (_ITINERARY_SLOTS_MIN <= len(raw_slots) <= _ITINERARY_SLOTS_MAX):
        return None
    slots = []
    for index, raw in enumerate(raw_slots):
        if not isinstance(raw, dict):
            return None
        domain = str(raw.get("domain") or "").strip().lower()
        if domain not in EXECUTABLE_DOMAINS:
            return None
        time = str(raw.get("time") or "").strip()
        slots.append(
            {
                "domain": domain,
                "source_domain": domain,
                "status": "ready",
                "tool_tags": tool_tags_for_domain(domain),
                "slot_index": index,
                "slot_label": str(raw.get("label") or domain).strip()[:80] or domain,
                "slot_time": time if _ITINERARY_TIME_RE.match(time) else None,
            }
        )
    return slots


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

            record_response_usage(response, model)
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
            # LLM 的结构化语义判断是主信号；关键词只做兜底/guardrail。
            if not is_in_query_flow and intent == "query":
                prefs_meaningful = has_meaningful_preferences(preferences) or is_recommendation_request(message)
                if confidence < 0.35 and not prefs_meaningful:
                    intent = "chat"
                    preferences = None
            elif not is_in_query_flow and intent == "chat" and is_recommendation_request(message):
                # High-precision keyword fallback: if the LLM missed an explicit
                # recommendation/search phrasing, still enter the recommendation
                # flow. Routing will classify or ask a supported-domain fallback.
                intent = "query"
                confidence = max(confidence, 0.55)
                preferences = preferences or {"query": message}

            reply = result.get("reply", default_reply)
            if not isinstance(reply, str) or not reply.strip():
                reply = default_reply

            if intent == "chat":
                if language == "zh":
                    if "推荐" not in reply:
                        reply = f"{reply}\n\n如果你愿意，我也可以按偏好帮你推荐餐厅、酒店、景点、电影、音乐、书籍或商品。"
                else:
                    if "recommend" not in reply.lower():
                        reply = f"{reply}\n\nIf you want, I can also recommend restaurants, hotels, attractions, movies, music, books, or products by your preferences."

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
                        fallback_reply = f"{fallback_reply}\n\n如果你愿意，我也可以按偏好帮你推荐餐厅、酒店、景点、电影、音乐、书籍或商品。"
                else:
                    if "recommend" not in fallback_reply.lower():
                        fallback_reply = f"{fallback_reply}\n\nIf you want, I can also recommend restaurants, hotels, attractions, movies, music, books, or products by your preferences."
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
        "product": "商品", "category": "类别", "brand": "品牌", "model": "型号", "use_case": "用途", "budget": "预算",
    }
    labels_en = {
        "restaurant_types": "restaurant type", "flavor_profiles": "flavor", "dining_purpose": "occasion",
        "location": "location", "genres": "genres", "exclude_genres": "exclude genres", "tags": "tags",
        "dietary_restrictions": "dietary restrictions", "typical_budget": "budget", "spice_tolerance": "spice level",
        "product": "product", "category": "category", "brand": "brand", "model": "model", "use_case": "use case", "budget": "budget",
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

_CONFIRMATION_QUICK_ACTION_KEYS = {
    "restaurant": {
        "restaurant_types",
        "flavor_profiles",
        "dining_purpose",
        "location",
        "dietary_restrictions",
        "typical_budget",
        "budget_range",
    },
    "movie": {"genres", "exclude_genres", "tags", "mood", "min_rating", "year"},
    "music": {"genres", "tags", "mood"},
    "book": {"genres", "subject", "tags", "mood"},
    "product": {"product", "use_case", "category", "brand", "model", "budget", "tags", "mood", "budget_range"},
    "hotel": {"stars", "amenities", "budget", "tags", "mood"},
    "attraction": {"attraction_types", "budget", "tags", "mood"},
}
_COMMON_QUICK_ACTION_KEYS = {"use_case", "tags", "mood"}


def _slugify_quick_action(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text[:64] or "option"


def _allowed_quick_action_keys(domain: Optional[str]) -> set:
    key = str(domain or "").lower()
    return set(_CONFIRMATION_QUICK_ACTION_KEYS.get(key, set())) | set(_COMMON_QUICK_ACTION_KEYS)


def _meaningful_patch_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip()) and value.strip().lower() != "any"
    if isinstance(value, (list, tuple, set)):
        return any(_meaningful_patch_value(item) for item in value)
    if isinstance(value, dict):
        return any(_meaningful_patch_value(item) for item in value.values())
    return True


def _clean_quick_actions(raw_actions: Any, domain: Optional[str]) -> List[Dict[str, Any]]:
    """Validate LLM-proposed single-choice HITL actions.

    The model may suggest prose, unsupported keys, or multi-dimensional patches.
    Keep only compact actions that patch exactly one allowed preference key, so a
    button click can safely act as confirmation.
    """
    if not isinstance(raw_actions, list):
        return []
    allowed_keys = _allowed_quick_action_keys(domain)
    cleaned: List[Dict[str, Any]] = []
    seen_ids = set()
    seen_labels = set()
    patch_keys = set()
    for index, raw in enumerate(raw_actions[:6]):
        if not isinstance(raw, dict):
            continue
        label = str(raw.get("label") or raw.get("value") or "").strip()
        if not label:
            continue
        patch = raw.get("preference_patch")
        if not isinstance(patch, dict):
            continue
        filtered_patch = {
            str(key): value
            for key, value in patch.items()
            if str(key) in allowed_keys and _meaningful_patch_value(value)
        }
        if len(filtered_patch) != 1:
            continue
        patch_key = next(iter(filtered_patch))
        action_id = _slugify_quick_action(raw.get("id") or f"{patch_key}_{raw.get('value') or label or index}")
        if action_id in seen_ids:
            action_id = f"{action_id}_{index + 1}"
        label_key = label.casefold()
        if label_key in seen_labels:
            continue
        value = raw.get("value")
        if value is None or value == "":
            value = next(iter(filtered_patch.values()))
        action: Dict[str, Any] = {
            "id": action_id,
            "label": label[:40],
            "value": str(value),
            "preference_patch": filtered_patch,
        }
        message = raw.get("message")
        if isinstance(message, str) and message.strip():
            action["message"] = message.strip()[:120]
        cleaned.append(action)
        seen_ids.add(action_id)
        seen_labels.add(label_key)
        patch_keys.add(patch_key)
    if len(cleaned) < 2 or len(cleaned) > 4:
        return []
    if len(patch_keys) != 1:
        return []
    return cleaned


def _fallback_confirmation_message(
    domain_label: str,
    prefs_text: str,
    language: str,
) -> str:
    detail = (("：" if language == "zh" else ": ") + prefs_text) if prefs_text else ""
    if language == "zh":
        return f"我理解您想要{domain_label}推荐{detail}。这样对吗？"
    return f"Got it — you're looking for a {domain_label} recommendation{detail}. Is that correct?"


def _confirmation_generation_prompt(
    *,
    query: str,
    domain: str,
    domain_label: str,
    prefs_text: str,
    language: str,
    guide_missing_preferences: bool,
) -> str:
    allowed_keys = sorted(_allowed_quick_action_keys(domain))
    base_payload = {
        "query": query,
        "domain": domain,
        "detected_preferences": prefs_text or "",
        "allowed_preference_patch_keys": allowed_keys,
        "output_schema": {
            "message": "natural confirmation message ending with a question",
            "quick_actions": [
                {
                    "id": "stable_slug",
                    "label": "short button label",
                    "value": "normalized value",
                    "preference_patch": {"one_allowed_key": "value"},
                    "message": "optional user-facing selected message",
                }
            ],
        },
    }
    if language == "zh":
        instructions = (
            "你为 MetaRec 生成推荐请求的确认消息。只返回一个 JSON object，不要 markdown。\n"
            "message: 1-2 句自然友好的中文确认，复述将查找的推荐对象和关键偏好，必须以确认问题结尾，例如“这样对吗？”。不要说已经开始查找。\n"
            "quick_actions: 仅当用户明显缺少一个适合按钮单选的关键维度时生成 2-4 个互斥选项；否则返回 []。\n"
            "如果返回 quick_actions，message 必须自然地询问这些选项本身，并点名所有按钮 label，例如“主要用于办公、学习还是游戏呢？”，不要只问“这样对吗？”。\n"
            "每个 quick action 只能 patch 一个 allowed_preference_patch_keys 中的 key。不要为开放问题生成按钮，例如导演、作者、艺术家、自由文本地点。\n"
            "商品/电脑类可优先询问 use_case，例如 办公/学习/游戏；电影可询问 genres；音乐可询问 mood/tags；书籍可询问 genres/subject；酒店可询问 stars 或 amenities；景点可询问 attraction_types，但不要用按钮询问自由文本地点。\n"
            "如果无法稳定映射成 preference_patch，quick_actions 必须为 []。"
        )
        if guide_missing_preferences:
            instructions += "\n如果已有动态表单覆盖缺失信息，倾向于 quick_actions=[]。"
    else:
        instructions = (
            "You generate a recommendation confirmation for MetaRec. Return only one JSON object, no markdown.\n"
            "message: 1-2 natural sentences, restate what will be searched and key preferences, and end with a confirmation question such as 'Is that correct?'. Do not say search has started.\n"
            "quick_actions: generate 2-4 mutually exclusive buttons only when one obvious missing dimension is suitable for single-choice buttons; otherwise return [].\n"
            "If quick_actions is non-empty, message must ask about those choices directly and mention every button label, e.g. 'Will this be mainly for work, study, or gaming?' Do not only ask 'Is that correct?'.\n"
            "Each quick action must patch exactly one key from allowed_preference_patch_keys. Do not create buttons for open-ended questions such as director, author, artist, or free-text location.\n"
            "For products/laptops prefer use_case such as work/study/gaming; for movies use genres; for music use mood/tags; for books use genres/subject; for hotels use stars or amenities; for attractions use attraction_types, but never use buttons for free-text destinations.\n"
            "If a choice cannot be mapped reliably into preference_patch, quick_actions must be []."
        )
        if guide_missing_preferences:
            instructions += "\nIf a dynamic form already covers the missing fields, prefer quick_actions=[]."
    return instructions + "\n\nContext:\n" + json.dumps(base_payload, ensure_ascii=False, default=str)


def _parse_confirmation_generation(
    content: str,
    *,
    domain: str,
    fallback_message: str,
    language: str = "en",
) -> Dict[str, Any]:
    content = (content or "").strip()
    parsed = _safe_parse_action(content)
    if not isinstance(parsed, dict):
        # Do not leak malformed structured output into the chat. If the model
        # tried to produce JSON but truncated or wrapped it badly, fall back to a
        # safe natural-language confirmation instead of rendering `{ "message`.
        lowered = content.lower()
        looks_structured = (
            content.startswith(("{", "["))
            or content.startswith("```")
            or '"message"' in lowered
            or "'message'" in lowered
            or ("{" in content and re.search(r"\bmessage\b", lowered))
            or "quick_actions" in lowered
            or "preference_patch" in lowered
        )
        return {"message": fallback_message if looks_structured else (content or fallback_message)}

    message = parsed.get("message")
    if not isinstance(message, str) or not message.strip():
        message = fallback_message
    payload: Dict[str, Any] = {"message": message.strip()}
    quick_actions = _clean_quick_actions(parsed.get("quick_actions"), domain)
    if quick_actions:
        payload["quick_actions"] = quick_actions
        payload["message"] = _ensure_confirmation_mentions_quick_actions(
            payload["message"],
            quick_actions,
            language,
        )
    return payload


def _join_choice_labels(labels: List[str], language: str = "en") -> str:
    clean = [str(label).strip() for label in labels if str(label).strip()]
    if not clean:
        return ""
    if language == "zh":
        if len(clean) == 1:
            return clean[0]
        if len(clean) == 2:
            return f"{clean[0]}还是{clean[1]}"
        return f"{'、'.join(clean[:-1])}还是{clean[-1]}"
    if len(clean) == 1:
        return clean[0]
    if len(clean) == 2:
        return f"{clean[0]} or {clean[1]}"
    return f"{', '.join(clean[:-1])}, or {clean[-1]}"


def _ensure_confirmation_mentions_quick_actions(
    message: str,
    quick_actions: List[Dict[str, Any]],
    language: str = "en",
) -> str:
    labels = [str(action.get("label") or "").strip() for action in quick_actions if action.get("label")]
    if not labels:
        return message
    lowered = message.casefold()
    if any(label.casefold() in lowered for label in labels):
        return message
    choices = _join_choice_labels(labels, language)
    if not choices:
        return message
    suffix = f"您更偏向{choices}呢？" if language == "zh" else f"Would you prefer {choices}?"
    return f"{message.rstrip()} {suffix}".strip()


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
    zh_labels = {"restaurant": "餐厅", "movie": "电影", "music": "音乐", "book": "书籍", "product": "商品", "hotel": "酒店", "attraction": "景点"}
    return zh_labels.get(key, key) if language == "zh" else key


async def generate_confirmation_payload(
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
    only confirms intent.

    The return payload is backward-compatible with the previous text-only
    confirmation: it always includes ``message`` and may include
    ``quick_actions`` when the model can safely map one missing preference
    dimension to structured button choices.
    """
    model = _resolve_model(model)
    domain_label = _humanize_domain_label(domain, language)
    prefs_text = _summarize_preferences_for_confirmation(preferences, language)
    fallback_message = _fallback_confirmation_message(domain_label, prefs_text, language)
    prompt = _confirmation_generation_prompt(
        query=query,
        domain=domain,
        domain_label=domain_label,
        prefs_text=prefs_text,
        language=language,
        guide_missing_preferences=guide_missing_preferences,
    )

    max_retries = _sanitize_retry_count(
        max_text_retries,
        default=int(os.getenv("LLM_MAX_FORMAT_RETRIES", "2"))
    )
    max_tokens = _get_text_max_tokens()
    for attempt in range(max_retries + 1):
        try:
            messages = [{"role": "user", "content": prompt}]
            try:
                response = await client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=0.8,
                    max_tokens=max_tokens,
                    response_format={"type": "json_object"},
                )
            except Exception as format_exc:
                if "response_format" not in str(format_exc).lower():
                    raise
                response = await client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=0.8,
                    max_tokens=max_tokens,
                )
            record_response_usage(response, model)
            content = _extract_message_content(response)
            if content:
                return _parse_confirmation_generation(
                    content,
                    domain=domain,
                    fallback_message=fallback_message,
                    language=language,
                )
            raise ValueError(
                f"Empty confirmation content from model={model}; "
                f"try increasing LLM_TEXT_MAX_TOKENS or using a non-reasoning chat model"
            )
        except Exception as e:
            if attempt < max_retries and type(e).__name__ in {"JSONDecodeError", "ValueError", "TypeError"}:
                continue
            print(f"Error generating confirmation message: {_format_llm_exception(e)}")
            return {"message": fallback_message}


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
    """Backward-compatible text-only confirmation helper."""
    payload = await generate_confirmation_payload(
        client,
        query,
        preferences,
        domain=domain,
        language=language,
        user_profile=user_profile,
        guide_missing_preferences=guide_missing_preferences,
        model=model,
        max_text_retries=max_text_retries,
    )
    return str(payload.get("message") or "")
