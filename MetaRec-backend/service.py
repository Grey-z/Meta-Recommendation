"""
MetaRec 核心服务类
提供餐厅推荐的核心业务逻辑，可以被其他模块直接调用
"""
from typing import List, Dict, Any, Optional, Tuple
import asyncio
import uuid
import random
import re
import json
import os
from datetime import datetime
from pydantic import BaseModel

# 导入 LLM 服务
from llm_service import analyze_user_message, generate_confirmation_message, LLMResponse, detect_language

# 导入用户画像存储
from user_profile_storage import get_profile_storage


# ==================== 数据模型 ====================

class BudgetRange(BaseModel):
    min: Optional[int] = None
    max: Optional[int] = None
    currency: str = "SGD"
    per: str = "person"


class Restaurant(BaseModel):
    id: str
    name: str
    address: Optional[str] = None
    area: Optional[str] = None
    cuisine: Optional[str] = None
    type: Optional[str] = None  # casual, fine-dining, etc.
    location: Optional[str] = None
    rating: Optional[float] = None
    reviews_count: Optional[int] = None
    price: Optional[str] = None  # price range in SGD
    price_per_person_sgd: Optional[str] = None  # e.g., "20-30", "28.80"
    distance_or_walk_time: Optional[str] = None
    open_hours_note: Optional[str] = None
    highlights: Optional[List[str]] = None
    flavor_match: Optional[List[str]] = None
    purpose_match: Optional[List[str]] = None
    why: Optional[str] = None  # reason for recommendation
    reason: Optional[str] = None  # alias for why
    reference: Optional[str] = None
    sources: Optional[Dict[str, str]] = None  # e.g., {"xiaohongshu": "id", "google_maps": "id"}
    phone: Optional[str] = None
    gps_coordinates: Optional[Dict[str, float]] = None  # {"latitude": 1.29, "longitude": 103.85}


class ThinkingStep(BaseModel):
    step: str
    description: str
    status: str  # "thinking", "completed", "error"
    details: Optional[str] = None


class RecommendationResult(BaseModel):
    """推荐结果"""
    restaurants: List[Restaurant]
    thinking_steps: Optional[List[ThinkingStep]] = None
    confidence_score: Optional[float] = None  # 推荐置信度 0-1
    metadata: Optional[Dict[str, Any]] = None  # 额外的元数据


class ConfirmationRequest(BaseModel):
    """确认请求"""
    message: str
    preferences: Dict[str, Any]
    needs_confirmation: bool = True


# ==================== 核心服务类 ====================

class MetaRecService:
    """
    MetaRec 核心推荐服务
    
    这个类封装了所有的推荐逻辑，可以被其他模块直接调用：
    - 用户意图分析
    - 偏好提取
    - 确认流程
    - 思考过程模拟
    - 餐厅推荐
    """
    
    def __init__(self, restaurant_data: Optional[List[Dict]] = None):
        """
        初始化服务
        
        Args:
            restaurant_data: 餐厅数据列表，如果为None则使用默认样例数据
        """
        # 餐厅数据库
        self.restaurant_data = restaurant_data or self._get_default_restaurants()
        
        # 用户偏好存储
        self.user_preferences: Dict[str, Dict[str, Any]] = {}
        
        # 用户上下文存储（用于确认流程）
        self.user_contexts: Dict[str, Dict[str, Any]] = {}
        
        # 任务存储（用于异步任务跟踪）
        self.tasks: Dict[str, Dict[str, Any]] = {}
        
        # 用户画像存储
        self.profile_storage = get_profile_storage() if get_profile_storage else None
    
    @staticmethod
    def _normalize_profile_updates(updates: Dict[str, Any]) -> Dict[str, Any]:
        """
        规范化 profile 更新，确保：
        1. 只更新 profile_example.json 中定义的字段
        2. 所有值都转换为字符串（数组用逗号分隔，null 转为空字符串）
        3. 未定义的字段内容合并到 description 中
        
        Args:
            updates: 原始更新字典
            
        Returns:
            规范化后的更新字典
        """
        normalized = {}
        
        # 定义合法的字段（与 profile_example.json 一致）
        valid_demographics_fields = {
            "age_range", "gender", "occupation", "location", "nationality"
        }
        
        valid_dining_habits_fields = {
            "typical_budget", "dietary_restrictions",
            "spice_tolerance", "description"
        }
        
        def _to_string(value: Any) -> str:
            """将值转换为字符串"""
            if value is None:
                return ""
            if isinstance(value, list):
                # 数组转换为逗号分隔的字符串
                return ", ".join(str(item) for item in value if item)
            if isinstance(value, dict):
                # 字典转换为字符串描述
                return str(value)
            return str(value) if value else ""
        
        for key, value in updates.items():
            if key == "demographics" and isinstance(value, dict):
                # 处理 demographics
                normalized_demographics = {}
                description_parts = []
                
                for field, field_value in value.items():
                    if field in valid_demographics_fields:
                        # 转换为字符串
                        normalized_demographics[field] = _to_string(field_value)
                    else:
                        # 未定义的字段，添加到 description
                        description_parts.append(f"{field}: {field_value}")
                
                if normalized_demographics:
                    normalized["demographics"] = normalized_demographics
                
                # 如果有未定义字段，需要添加到 dining_habits.description
                # 注意：description 应该是一个完整的描述，不是增量追加
                if description_parts:
                    if "dining_habits" not in normalized:
                        normalized["dining_habits"] = {}
                    # 直接设置 description，不追加
                    normalized["dining_habits"]["description"] = "demographics: " + "; ".join(description_parts)
                    
            elif key == "dining_habits" and isinstance(value, dict):
                # 处理 dining_habits
                normalized_dining_habits = {}
                description_parts = []
                has_explicit_description = False
                
                for field, field_value in value.items():
                    if field == "description":
                        # LLM 明确提供了 description，使用它（完整描述，覆盖旧内容）
                        has_explicit_description = True
                        normalized_dining_habits["description"] = _to_string(field_value)
                    elif field in valid_dining_habits_fields:
                        # 合法字段，转换为字符串
                        normalized_dining_habits[field] = _to_string(field_value)
                    else:
                        # 未定义的字段，添加到 description_parts（但只有在没有明确 description 时才使用）
                        description_parts.append(f"{field}: {field_value}")
                
                # 如果有未定义字段且没有明确的 description，才创建 description
                # 注意：如果 LLM 明确提供了 description，我们使用它，不追加未定义字段
                if description_parts and not has_explicit_description:
                    # 直接设置 description，不追加
                    normalized_dining_habits["description"] = "; ".join(description_parts)
                
                if normalized_dining_habits:
                    normalized["dining_habits"] = normalized_dining_habits
            elif key == "inferred_info":
                # inferred_info 不再使用，将其内容添加到 description
                # 注意：description 应该是一个完整的描述，不是增量追加
                if "dining_habits" not in normalized:
                    normalized["dining_habits"] = {}
                normalized["dining_habits"]["description"] = f"inferred_info: {value}"
            else:
                # 其他未定义的顶级字段，忽略或添加到 description
                pass
        
        return normalized
    
    @staticmethod
    def _extract_restaurants_from_execution_data(data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        从真实执行数据中提取餐厅信息
        
        Args:
            data: 包含 executions 和 summary 的数据字典
            
        Returns:
            餐厅列表
        """
        restaurants = []
        
        # 从 summary.recommendations 中提取推荐餐厅
        if "summary" in data and "recommendations" in data["summary"]:
            for idx, rec in enumerate(data["summary"]["recommendations"]):
                restaurant = {
                    "id": f"rec_{idx}_{rec.get('name', '').replace(' ', '_')}",
                    "name": rec.get("name", ""),
                    "address": rec.get("address"),
                    "area": rec.get("area"),
                    "cuisine": rec.get("cuisine"),
                    "type": rec.get("type"),
                    "location": rec.get("area"),  # 使用 area 作为 location
                    "rating": rec.get("rating"),
                    "reviews_count": rec.get("reviews_count"),
                    "price": None,  # 从 price_per_person_sgd 推断
                    "price_per_person_sgd": rec.get("price_per_person_sgd"),
                    "distance_or_walk_time": rec.get("distance_or_walk_time"),
                    "open_hours_note": rec.get("open_hours_note"),
                    "flavor_match": rec.get("flavor_match", []),
                    "purpose_match": rec.get("purpose_match", []),
                    "why": rec.get("why"),
                    "reason": rec.get("why"),  # alias
                    "sources": rec.get("sources", {}),
                    "phone": None,
                    "gps_coordinates": None
                }
                
                # 从 price_per_person_sgd 推断 price 等级
                if restaurant["price_per_person_sgd"]:
                    price_str = restaurant["price_per_person_sgd"]
                    if "-" in price_str:
                        parts = price_str.split("-")
                        try:
                            min_price = float(parts[0].strip())
                            if min_price < 20:
                                restaurant["price"] = "$"
                            elif min_price < 40:
                                restaurant["price"] = "$$"
                            elif min_price < 80:
                                restaurant["price"] = "$$$"
                            else:
                                restaurant["price"] = "$$$$"
                        except:
                            pass
                    else:
                        try:
                            price_val = float(price_str)
                            if price_val < 20:
                                restaurant["price"] = "$"
                            elif price_val < 40:
                                restaurant["price"] = "$$"
                            elif price_val < 80:
                                restaurant["price"] = "$$$"
                            else:
                                restaurant["price"] = "$$$$"
                        except:
                            pass
                
                restaurants.append(restaurant)
        
        # 从 executions 中的 gmap.search 结果中提取额外信息
        if "executions" in data:
            gmap_restaurants = {}
            for execution in data["executions"]:
                if execution.get("tool") == "gmap.search" and execution.get("success") and execution.get("output"):
                    for gmap_item in execution["output"]:
                        # 尝试通过名称匹配
                        name = gmap_item.get("title", "")
                        if name:
                            gmap_restaurants[name] = {
                                "rating": gmap_item.get("rating"),
                                "reviews_count": gmap_item.get("reviews"),
                                "price": gmap_item.get("price"),
                                "phone": gmap_item.get("phone"),
                                "address": gmap_item.get("address"),
                                "gps_coordinates": gmap_item.get("gps_coordinates"),
                                "open_state": gmap_item.get("open_state")
                            }
            
            # 合并 gmap 数据到推荐餐厅
            for restaurant in restaurants:
                name = restaurant["name"]
                # 尝试模糊匹配名称
                for gmap_name, gmap_data in gmap_restaurants.items():
                    if name.lower() in gmap_name.lower() or gmap_name.lower() in name.lower():
                        # 更新餐厅信息
                        if not restaurant.get("rating") and gmap_data.get("rating"):
                            restaurant["rating"] = gmap_data["rating"]
                        if not restaurant.get("reviews_count") and gmap_data.get("reviews_count"):
                            restaurant["reviews_count"] = gmap_data["reviews_count"]
                        if not restaurant.get("price") and gmap_data.get("price"):
                            restaurant["price"] = gmap_data["price"]
                        if not restaurant.get("phone") and gmap_data.get("phone"):
                            restaurant["phone"] = gmap_data["phone"]
                        if not restaurant.get("address") and gmap_data.get("address"):
                            restaurant["address"] = gmap_data["address"]
                        if not restaurant.get("gps_coordinates") and gmap_data.get("gps_coordinates"):
                            restaurant["gps_coordinates"] = gmap_data["gps_coordinates"]
                        if not restaurant.get("open_hours_note") and gmap_data.get("open_state"):
                            restaurant["open_hours_note"] = gmap_data["open_state"]
                        break
        
        return restaurants
    
    @staticmethod
    def _get_default_restaurants() -> List[Dict]:
        """获取默认餐厅数据，优先从 demo_restaurant.json 加载"""
        # 尝试从 demo_restaurant.json 加载真实数据
        demo_file = os.path.join(os.path.dirname(__file__), "demo_restaurant.json")
        if os.path.exists(demo_file):
            try:
                with open(demo_file, 'r', encoding='utf-8') as f:
                    demo_data = json.load(f)
                    restaurants = MetaRecService._extract_restaurants_from_execution_data(demo_data)
                    if restaurants:
                        return restaurants
            except Exception as e:
                print(f"Warning: Failed to load demo_restaurant.json: {e}")
        
        # 如果加载失败，返回默认数据
        return [
            {
                "id": "default_1",
                "name": "四川饭店满庭芳",
                "address": "72 Pagoda St, Singapore 059231",
                "area": "Chinatown",
                "cuisine": "Sichuan",
                "type": "casual",
                "price_per_person_sgd": "20-30",
                "rating": None,
                "reviews_count": None,
                "distance_or_walk_time": "3 min walk from Chinatown MRT",
                "open_hours_note": "11 AM–10 PM daily",
                "flavor_match": ["Spicy"],
                "purpose_match": ["Friends", "Group-friendly"],
                "why": "人均约20新币，招牌辣子鸡与水煮肉片均为重辣口味，地理位置便利，深受川菜控好评。",
                "sources": {"xiaohongshu": "623d9ddf000000000102f1ce"}
            }
        ]
    
    # ==================== 偏好管理 ====================
    
    def get_default_preferences(self) -> Dict[str, Any]:
        """获取默认偏好设置"""
        return {
            "restaurant_types": ["any"],
            "flavor_profiles": ["any"],
            "dining_purpose": "any",
            "budget_range": {
                "min": 20,
                "max": 60,
                "currency": "SGD",
                "per": "person"
            },
            "location": "any"
        }
    
    def get_user_preferences(self, user_id: str = "default") -> Dict[str, Any]:
        """
        获取用户的偏好设置
        
        Args:
            user_id: 用户ID
            
        Returns:
            用户偏好字典
        """
        if user_id not in self.user_preferences:
            self.user_preferences[user_id] = self.get_default_preferences()
        return self.user_preferences[user_id].copy()
    
    def update_user_preferences(self, user_id: str, preferences: Dict[str, Any]) -> Dict[str, Any]:
        """
        更新用户的偏好设置
        
        Args:
            user_id: 用户ID
            preferences: 要更新的偏好
            
        Returns:
            更新后的完整偏好
        """
        if user_id not in self.user_preferences:
            self.user_preferences[user_id] = self.get_default_preferences()
        
        # 合并更新偏好，只更新提供的字段
        if "restaurant_types" in preferences:
            self.user_preferences[user_id]["restaurant_types"] = preferences["restaurant_types"]
        if "flavor_profiles" in preferences:
            self.user_preferences[user_id]["flavor_profiles"] = preferences["flavor_profiles"]
        if "dining_purpose" in preferences:
            self.user_preferences[user_id]["dining_purpose"] = preferences["dining_purpose"]
        if "budget_range" in preferences:
            self.user_preferences[user_id]["budget_range"] = preferences["budget_range"]
        if "location" in preferences:
            self.user_preferences[user_id]["location"] = preferences["location"]
        
        return self.user_preferences[user_id].copy()
    
    # ==================== 意图分析 ====================
    
    def analyze_user_intent(self, query: str) -> Dict[str, Any]:
        """
        分析用户意图，判断是确认、拒绝还是新请求
        
        Args:
            query: 用户输入的查询
            
        Returns:
            意图分析结果，包含type和相关信息
        """
        query_lower = query.lower().strip()
        
        # 检查是否是确认响应
        yes_patterns = [
            r'\b(yes|yeah|yep|yup|correct|right|that\'s right|that\'s correct|sounds good|perfect|ok|okay|sure|exactly|precisely)\b',
            r'\b(是的|对|正确|没错|好的|可以|行|没问题|完全正确|就是这样)\b'
        ]
        
        no_patterns = [
            r'\b(no|nope|not right|incorrect|wrong|not correct|that\'s not right|that\'s wrong|not what I want|not quite|almost|close but|not exactly)\b',
            r'\b(不|不对|错误|不是|不是这样|不是这个|不对的|不是我要的|差不多|接近但不是|不完全对)\b'
        ]
        
        # 检查是否包含确认关键词
        is_yes = any(re.search(pattern, query_lower) for pattern in yes_patterns)
        is_no = any(re.search(pattern, query_lower) for pattern in no_patterns)
        
        # 检查是否包含修改/更新关键词
        modify_patterns = [
            r'\b(change|modify|update|different|instead|rather|actually|but|however|although|though)\b',
            r'\b(改变|修改|更新|不同|而是|实际上|但是|不过|虽然|但是)\b'
        ]
        
        is_modify = any(re.search(pattern, query_lower) for pattern in modify_patterns)
        
        # 检查是否包含新的餐厅查询关键词
        new_query_patterns = [
            r'\b(restaurant|food|dining|eat|meal|dinner|lunch|breakfast|cuisine|taste|flavor|spicy|sweet|sour|savory)\b',
            r'\b(餐厅|食物|用餐|吃饭|餐|晚餐|午餐|早餐|菜系|味道|口味|辣|甜|酸|咸|香)\b'
        ]
        
        is_new_query = any(re.search(pattern, query_lower) for pattern in new_query_patterns)
        
        # 判断意图类型
        if is_yes and not is_no:
            return {
                "type": "confirmation_yes",
                "original_query": query,
                "confidence": 0.9
            }
        elif is_no or is_modify:
            return {
                "type": "confirmation_no",
                "original_query": query,
                "confidence": 0.8
            }
        elif is_new_query:
            return {
                "type": "new_query",
                "original_query": query,
                "confidence": 0.85
            }
        else:
            # 默认认为是新查询
            return {
                "type": "new_query",
                "original_query": query,
                "confidence": 0.6
            }
    
    # ==================== 偏好提取 ====================
    
    def extract_preferences_from_query(self, query: str, user_id: str = "default") -> Dict[str, Any]:
        """
        从用户查询中智能提取偏好设置
        
        Args:
            query: 用户查询
            user_id: 用户ID
            
        Returns:
            提取的偏好设置
        """
        query_lower = query.lower()
        
        # 获取用户存储的偏好作为基础
        stored_prefs = self.get_user_preferences(user_id)
        
        # 初始化为空，用于检测用户是否指定了新值
        preferences = {
            "restaurant_types": [],
            "flavor_profiles": [],
            "dining_purpose": None,
            "budget_range": {"min": None, "max": None, "currency": "SGD", "per": "person"},
            "location": None
        }
        
        # 提取餐厅类型
        type_keywords = {
            "casual": ["casual", "relaxed", "informal", "everyday"],
            "fine-dining": ["fine dining", "fancy", "elegant", "upscale", "romantic", "special occasion"],
            "fast-casual": ["fast casual", "quick", "grab and go"],
            "street-food": ["street food", "hawker", "food court", "local"],
            "buffet": ["buffet", "all you can eat", "unlimited"],
            "cafe": ["cafe", "coffee", "brunch", "light meal"]
        }
        
        for type_key, keywords in type_keywords.items():
            if any(keyword in query_lower for keyword in keywords):
                preferences["restaurant_types"].append(type_key)
        
        # 提取口味偏好
        flavor_keywords = {
            "spicy": ["spicy", "hot", "chili", "sichuan", "thai", "indian", "korean"],
            "savory": ["savory", "umami", "meaty", "rich"],
            "sweet": ["sweet", "dessert", "cake", "chocolate"],
            "sour": ["sour", "tangy", "citrus", "vinegar"],
            "mild": ["mild", "gentle", "subtle", "light"]
        }
        
        for flavor_key, keywords in flavor_keywords.items():
            if any(keyword in query_lower for keyword in keywords):
                preferences["flavor_profiles"].append(flavor_key)
        
        # 提取用餐目的
        purpose_keywords = {
            "date-night": ["date", "romantic", "anniversary", "valentine", "couple"],
            "family": ["family", "kids", "children", "parents"],
            "business": ["business", "meeting", "client", "professional"],
            "solo": ["solo", "alone", "myself", "personal"],
            "friends": ["friends", "group", "party", "celebration"],
            "celebration": ["celebration", "birthday", "graduation", "promotion"]
        }
        
        for purpose_key, keywords in purpose_keywords.items():
            if any(keyword in query_lower for keyword in keywords):
                preferences["dining_purpose"] = purpose_key
                break
        
        # 提取预算信息
        budget_patterns = [
            r'(\$+)\s*(\d+)',  # $50, $$100
            r'(\d+)\s*to\s*(\d+)',  # 50 to 100
            r'under\s*(\d+)',  # under 50
            r'around\s*(\d+)',  # around 50
            r'budget\s*(\d+)',  # budget 50
        ]
        
        for pattern in budget_patterns:
            match = re.search(pattern, query_lower)
            if match:
                if 'to' in pattern:
                    preferences["budget_range"]["min"] = int(match.group(1))
                    preferences["budget_range"]["max"] = int(match.group(2))
                else:
                    amount = int(match.group(1)) if match.group(1).isdigit() else int(match.group(2))
                    if 'under' in pattern:
                        preferences["budget_range"]["max"] = amount
                    else:
                        preferences["budget_range"]["min"] = amount
                        preferences["budget_range"]["max"] = amount + 20
                break
        
        # 提取位置信息
        singapore_areas = [
            "orchard", "marina bay", "chinatown", "bugis", "tanjong pagar",
            "clarke quay", "little india", "holland village", "tiong bahru",
            "katong", "joo chiat", "downtown", "cbd", "central"
        ]
        
        for area in singapore_areas:
            if area in query_lower:
                preferences["location"] = area.title()
                break
        
        # 合并用户存储的偏好：如果query中没有指定，则使用存储的值
        if not preferences["restaurant_types"]:
            preferences["restaurant_types"] = stored_prefs["restaurant_types"]
        
        if not preferences["flavor_profiles"]:
            preferences["flavor_profiles"] = stored_prefs["flavor_profiles"]
        
        if preferences["dining_purpose"] is None:
            preferences["dining_purpose"] = stored_prefs["dining_purpose"]
        
        if not preferences["budget_range"]["min"] and not preferences["budget_range"]["max"]:
            preferences["budget_range"] = stored_prefs["budget_range"]
        
        if preferences["location"] is None:
            preferences["location"] = stored_prefs["location"]
        
        # 更新用户的偏好存储（保存本次提取的偏好）
        self.update_user_preferences(user_id, preferences)
        
        return preferences
    
    # ==================== 确认流程 ====================
    
    def generate_confirmation_prompt(self, query: str, preferences: Dict[str, Any]) -> str:
        """
        生成确认提示
        
        Args:
            query: 原始查询
            preferences: 提取的偏好
            
        Returns:
            确认提示文本
        """
        parts = []
        
        # 餐厅类型
        if preferences["restaurant_types"] and preferences["restaurant_types"] != ["any"]:
            type_names = {
                "casual": "Casual Dining",
                "fine-dining": "Fine Dining", 
                "fast-casual": "Fast Casual",
                "street-food": "Street Food",
                "buffet": "Buffet",
                "cafe": "Cafe"
            }
            types = [type_names.get(t, t) for t in preferences["restaurant_types"]]
            parts.append(f"• Restaurant Type: {', '.join(types)}")
        
        # 口味偏好
        if preferences["flavor_profiles"] and preferences["flavor_profiles"] != ["any"]:
            flavor_names = {
                "spicy": "Spicy",
                "savory": "Savory",
                "sweet": "Sweet",
                "sour": "Sour",
                "mild": "Mild"
            }
            flavors = [flavor_names.get(f, f) for f in preferences["flavor_profiles"]]
            parts.append(f"• Flavor Profile: {', '.join(flavors)}")
        
        # 用餐目的
        purpose_names = {
            "date-night": "Date Night",
            "family": "Family Dining",
            "business": "Business Meeting",
            "solo": "Solo Dining",
            "friends": "Friends Gathering",
            "celebration": "Celebration"
        }
        if preferences["dining_purpose"] != "any":
            parts.append(f"• Dining Purpose: {purpose_names.get(preferences['dining_purpose'], preferences['dining_purpose'])}")
        
        # 预算范围
        budget = preferences["budget_range"]
        if budget.get("min") or budget.get("max"):
            if budget.get("min") and budget.get("max"):
                parts.append(f"• Budget Range: {budget['min']}-{budget['max']} SGD per person")
            elif budget.get("min"):
                parts.append(f"• Minimum Budget: {budget['min']} SGD per person")
            elif budget.get("max"):
                parts.append(f"• Maximum Budget: {budget['max']} SGD per person")
        
        # 位置
        if preferences["location"] and preferences["location"] != "any":
            parts.append(f"• Location: {preferences['location']}")
        
        # 默认值
        if not parts:
            parts = [
                "• Restaurant Type: Any",
                "• Flavor Profile: Any", 
                "• Dining Purpose: Any",
                "• Budget Range: 20-60 SGD per person",
                "• Location: Any"
            ]
        
        prompt = f"Based on your query '{query}', I understand you want:\n\n" + "\n".join(parts) + "\n\nIs this correct?"
        return prompt
    
    async def create_confirmation_request(
        self, 
        query: str, 
        preferences: Dict[str, Any], 
        user_id: str = "default",
        use_llm: bool = True
    ) -> ConfirmationRequest:
        """
        创建确认请求对象
        
        Args:
            query: 原始查询
            preferences: 提取的偏好
            user_id: 用户ID
            use_llm: 是否使用 LLM 生成自然确认消息（默认 True）
            
        Returns:
            ConfirmationRequest对象
        """
        # 使用 LLM 生成自然的确认消息
        if use_llm and generate_confirmation_message:
            try:
                # 检测语言
                language = "en"
                if detect_language:
                    language = detect_language(query)
                
                # 获取用户画像（可选）
                user_profile = None
                if self.profile_storage:
                    user_profile = self.profile_storage.get_user_profile(user_id)
                
                # 生成确认消息
                message = await generate_confirmation_message(query, preferences, language, user_profile)
            except Exception as e:
                print(f"Error generating LLM confirmation message, falling back to template: {e}")
                # 回退到模板格式
                message = self.generate_confirmation_prompt(query, preferences)
        else:
            # 使用模板格式
            message = self.generate_confirmation_prompt(query, preferences)
        
        # 保存到上下文（包括确认消息）
        self.user_contexts[user_id] = {
            "preferences": preferences,
            "original_query": query,
            "confirmation_message": message,  # 保存确认消息，以便后续使用
            "timestamp": datetime.now().isoformat()
        }
        
        return ConfirmationRequest(
            message=message,
            preferences=preferences,
            needs_confirmation=True
        )
    
    # ==================== 思考过程模拟 ====================
    
    async def simulate_thinking_process(self, query: str, preferences: Dict[str, Any]) -> List[ThinkingStep]:
        """
        模拟AI思考过程
        
        Args:
            query: 用户查询
            preferences: 偏好设置
            
        Returns:
            思考步骤列表
        """
        steps = []
        
        # Step 1: 分析用户需求
        steps.append(ThinkingStep(
            step="analyze_query",
            description="Analyzing your requirements...",
            status="thinking"
        ))
        await asyncio.sleep(0.5)
        steps[-1].status = "completed"
        steps[-1].details = f"Identified keywords: {', '.join([k for k in query.split() if len(k) > 3])}"
        
        # Step 2: 提取偏好
        steps.append(ThinkingStep(
            step="extract_preferences",
            description="Extracting your preferences...",
            status="thinking"
        ))
        await asyncio.sleep(0.8)
        steps[-1].status = "completed"
        prefs_text = []
        if preferences["restaurant_types"] != ["any"]:
            prefs_text.append(f"Restaurant Types: {preferences['restaurant_types']}")
        if preferences["flavor_profiles"] != ["any"]:
            prefs_text.append(f"Flavor Profiles: {preferences['flavor_profiles']}")
        if preferences["dining_purpose"] != "any":
            prefs_text.append(f"Dining Purpose: {preferences['dining_purpose']}")
        steps[-1].details = "; ".join(prefs_text) if prefs_text else "Using default preferences"
        
        # Step 3: 搜索餐厅数据库
        steps.append(ThinkingStep(
            step="search_database",
            description="Searching restaurant database...",
            status="thinking"
        ))
        await asyncio.sleep(1.0)
        steps[-1].status = "completed"
        steps[-1].details = f"Screening {len(self.restaurant_data)} restaurants for matches"
        
        # Step 4: 应用过滤条件
        steps.append(ThinkingStep(
            step="apply_filters",
            description="Applying filter conditions...",
            status="thinking"
        ))
        await asyncio.sleep(0.6)
        steps[-1].status = "completed"
        steps[-1].details = "Filtering by location, budget, taste preferences, etc."
        
        # Step 5: 排序和评分
        steps.append(ThinkingStep(
            step="rank_results",
            description="Ranking and scoring recommendations...",
            status="thinking"
        ))
        await asyncio.sleep(0.7)
        steps[-1].status = "completed"
        steps[-1].details = "Sorting by rating and match score, selecting best recommendations"
        
        return steps
    
    # ==================== 餐厅推荐 ====================
    
    def filter_restaurants(self, query: str, preferences: Dict[str, Any]) -> List[Restaurant]:
        """
        根据查询和偏好过滤餐厅
        
        Args:
            query: 用户查询
            preferences: 偏好设置
            
        Returns:
            过滤后的餐厅列表
        """
        restaurants = [Restaurant(**r) for r in self.restaurant_data]
        filtered = restaurants.copy()
        
        # 按位置过滤
        location = preferences.get("location")
        if location and location != "any":
            location_lower = location.lower()
            filtered = [r for r in filtered if 
                       (r.location and location_lower in r.location.lower()) or
                       (r.area and location_lower in r.area.lower()) or
                       (r.address and location_lower in r.address.lower())]
        
        # 按预算过滤
        budget_range = preferences.get("budget_range", {})
        budget_min = budget_range.get("min")
        budget_max = budget_range.get("max")
        
        if budget_min is not None or budget_max is not None:
            def matches_budget(r: Restaurant) -> bool:
                # 优先使用 price_per_person_sgd
                if r.price_per_person_sgd:
                    try:
                        price_str = r.price_per_person_sgd
                        if "-" in price_str:
                            parts = price_str.split("-")
                            min_price = float(parts[0].strip())
                            max_price = float(parts[1].strip()) if len(parts) > 1 else min_price
                            if budget_min is not None and max_price < budget_min:
                                return False
                            if budget_max is not None and min_price > budget_max:
                                return False
                            return True
                        else:
                            price_val = float(price_str)
                            if budget_min is not None and price_val < budget_min:
                                return False
                            if budget_max is not None and price_val > budget_max:
                                return False
                            return True
                    except:
                        pass
                
                # 回退到 price 字段
                if r.price:
                    price_mapping = {"$": 20, "$$": 40, "$$$": 80, "$$$$": 150}
                    price_val = price_mapping.get(r.price, 0)
                    if budget_min is not None and price_val < budget_min:
                        return False
                    if budget_max is not None and price_val > budget_max:
                        return False
                    return True
                
                return True  # 如果没有价格信息，不过滤
            
            filtered = [r for r in filtered if matches_budget(r)]
        
        # 根据查询过滤菜系
        query_lower = query.lower()
        cuisine_keywords = {
            "chinese": ["chinese", "dim sum", "cantonese", "sichuan", "hunan"],
            "japanese": ["japanese", "sushi", "ramen", "tempura", "yakitori"],
            "korean": ["korean", "bbq", "kimchi", "korean"],
            "thai": ["thai", "thailand", "pad thai", "tom yum"],
            "indian": ["indian", "curry", "tandoor", "biryani"],
            "italian": ["italian", "pasta", "pizza", "risotto"],
            "french": ["french", "bistro", "brasserie"],
            "western": ["western", "steak", "burger", "grill"],
            "local": ["local", "singaporean", "hawker", "peranakan", "malay"]
        }
        
        # 辣味过滤
        flavor_profiles = preferences.get("flavor_profiles", [])
        if "spicy" in flavor_profiles or any(keyword in query_lower for keyword in ["spicy", "hot"]):
            # 检查 flavor_match 字段
            filtered = [r for r in filtered if 
                       (r.flavor_match and "Spicy" in r.flavor_match) or
                       (r.cuisine and any(cuisine in r.cuisine.lower() for cuisine in ["sichuan", "korean", "thai", "indian", "peranakan"]))]
        
        # 按用餐目的过滤
        dining_purpose = preferences.get("dining_purpose", "any")
        if dining_purpose == "date-night":
            filtered = [r for r in filtered if r.price in ["$$$", "$$$$"] and 
                       r.highlights and "romantic" in [h.lower() for h in r.highlights]]
        elif dining_purpose == "family":
            filtered = [r for r in filtered if r.highlights and 
                       any("family" in h.lower() for h in r.highlights) or r.price in ["$", "$$"]]
        elif dining_purpose == "business":
            filtered = [r for r in filtered if r.price in ["$$$", "$$$$"] and 
                       r.rating and r.rating >= 4.0]
        
        # 如果没有匹配结果，返回一些通用推荐
        if not filtered:
            filtered = restaurants[:3]
        
        # 按评分排序并限制结果数量
        filtered.sort(key=lambda x: x.rating or 0, reverse=True)
        
        # 增加一些随机性
        if len(filtered) > 6:
            # 保留前3个高评分，其余随机选择
            top_3 = filtered[:3]
            others = filtered[3:]
            random.shuffle(others)
            filtered = top_3 + others[:3]
        else:
            filtered = filtered[:6]
        
        return filtered
    
    async def get_recommendations(
        self, 
        query: str, 
        preferences: Optional[Dict[str, Any]] = None,
        user_id: str = "default",
        include_thinking: bool = True
    ) -> RecommendationResult:
        """
        获取餐厅推荐（主接口）
        
        Args:
            query: 用户查询
            preferences: 偏好设置（如果为None则从query提取）
            user_id: 用户ID
            include_thinking: 是否包含思考过程
            
        Returns:
            RecommendationResult对象
        """
        # 如果没有提供偏好，则从查询中提取
        if preferences is None:
            preferences = self.extract_preferences_from_query(query, user_id)
        
        # 模拟思考过程（如果需要）
        thinking_steps = None
        if include_thinking:
            thinking_steps = await self.simulate_thinking_process(query, preferences)
        
        # 获取推荐餐厅
        restaurants = self.filter_restaurants(query, preferences)
        
        # 计算置信度分数
        confidence_score = self._calculate_confidence(query, preferences, restaurants)
        
        return RecommendationResult(
            restaurants=restaurants,
            thinking_steps=thinking_steps,
            confidence_score=confidence_score,
            metadata={
                "query": query,
                "user_id": user_id,
                "timestamp": datetime.now().isoformat(),
                "preferences": preferences
            }
        )
    
    def _calculate_confidence(self, query: str, preferences: Dict[str, Any], restaurants: List[Restaurant]) -> float:
        """计算推荐置信度"""
        confidence = 0.5  # 基础置信度
        
        # 如果有明确的偏好设置，提高置信度
        if preferences["restaurant_types"] != ["any"]:
            confidence += 0.1
        if preferences["flavor_profiles"] != ["any"]:
            confidence += 0.1
        if preferences["dining_purpose"] != "any":
            confidence += 0.1
        if preferences.get("location") and preferences["location"] != "any":
            confidence += 0.1
        
        # 如果找到了餐厅，提高置信度
        if len(restaurants) > 0:
            confidence += 0.1
        
        return min(confidence, 1.0)
    
    # ==================== 异步任务处理 ====================
    
    async def process_recommendation_task(
        self,
        task_id: str,
        query: str,
        preferences: Dict[str, Any],
        user_id: str = "default"
    ):
        """
        后台处理推荐任务
        
        Args:
            task_id: 任务ID
            query: 用户查询
            preferences: 偏好设置
            user_id: 用户ID
        """
        try:
            # 更新进度
            self.tasks[task_id] = {
                "status": "processing",
                "progress": 10,
                "message": "Analyzing your requirements..."
            }
            await asyncio.sleep(1)
            
            self.tasks[task_id]["progress"] = 30
            self.tasks[task_id]["message"] = "Extracting preferences..."
            await asyncio.sleep(1)
            
            self.tasks[task_id]["progress"] = 50
            self.tasks[task_id]["message"] = "Searching restaurant database..."
            await asyncio.sleep(1)
            
            self.tasks[task_id]["progress"] = 70
            self.tasks[task_id]["message"] = "Applying filters..."
            await asyncio.sleep(1)
            
            self.tasks[task_id]["progress"] = 90
            self.tasks[task_id]["message"] = "Generating recommendations..."
            
            # 获取推荐结果
            result = await self.get_recommendations(query, preferences, user_id, include_thinking=True)
            
            # 完成任务
            self.tasks[task_id]["status"] = "completed"
            self.tasks[task_id]["progress"] = 100
            self.tasks[task_id]["message"] = "Recommendations ready!"
            self.tasks[task_id]["result"] = result
            
        except Exception as e:
            self.tasks[task_id]["status"] = "error"
            self.tasks[task_id]["error"] = str(e)
            self.tasks[task_id]["message"] = f"Error: {str(e)}"
    
    def create_task(self, query: str, preferences: Dict[str, Any], user_id: str = "default") -> str:
        """
        创建一个新的推荐任务
        
        Args:
            query: 用户查询
            preferences: 偏好设置
            user_id: 用户ID
            
        Returns:
            任务ID
        """
        task_id = str(uuid.uuid4())
        
        # 创建任务
        self.tasks[task_id] = {
            "task_id": task_id,
            "status": "pending",
            "progress": 0,
            "message": "Task created",
            "result": None,
            "error": None
        }
        
        # 启动后台任务
        asyncio.create_task(self.process_recommendation_task(task_id, query, preferences, user_id))
        
        return task_id
    
    def get_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        获取任务状态
        
        Args:
            task_id: 任务ID
            
        Returns:
            任务状态字典，如果任务不存在返回None
        """
        return self.tasks.get(task_id)
    
    # ==================== 统一用户请求处理 ====================
    
    async def handle_user_request_async(
        self,
        query: str,
        user_id: str = "default",
        conversation_history: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        异步处理用户请求的统一入口函数（使用 LLM 进行意图识别）
        
        这个函数会自动处理：
        1. 使用 LLM 进行意图识别和生成回复
        2. 根据意图决定后续操作：
           - "query": 触发推荐流程
           - "chat": 返回 LLM 的回复
        
        Args:
            query: 用户查询
            user_id: 用户ID
            conversation_history: 对话历史（可选）
            
        Returns:
            包含以下字段的字典：
            - type: "llm_reply" | "confirmation" | "task_created" | "modify_request"
            - llm_reply: GPT-4 的回复（如果type为llm_reply）
            - task_id: 任务ID（如果type为task_created）
            - confirmation_request: 确认请求对象（如果type为confirmation）
            - message: 消息文本（如果type为modify_request）
        """
        # Step 1: 使用 LLM 进行意图识别
        if analyze_user_message is None:
            # 如果 LLM 服务不可用，回退到原有逻辑
            return self.handle_user_request(query, user_id)
        
        try:
            # Step 1.5: 加载用户画像
            user_profile = None
            if self.profile_storage:
                user_profile = self.profile_storage.get_user_profile(user_id)
            
            # Step 1: 检查当前状态（是否在 query 流程中）
            is_in_query_flow = user_id in self.user_contexts
            pending_preferences = None
            original_query = query
            confirmation_message = None
            if is_in_query_flow:
                context = self.user_contexts[user_id]
                pending_preferences = context.get("preferences")
                original_query = context.get("original_query", query)
                confirmation_message = context.get("confirmation_message")  # 获取保存的确认消息
            
            # Step 1.5: 如果在 query 流程中，确保对话历史包含确认消息
            enhanced_history = list(conversation_history) if conversation_history else []
            if is_in_query_flow and confirmation_message:
                # 检查对话历史中是否已经有确认消息
                # 如果最后一条消息是助手消息且内容匹配确认消息，则认为已有确认消息
                needs_confirmation = True
                if enhanced_history:
                    last_msg = enhanced_history[-1]
                    if (last_msg.get("role") == "assistant" and 
                        last_msg.get("content", "").strip() == confirmation_message.strip()):
                        needs_confirmation = False
                
                # 如果对话历史中没有确认消息，添加它
                if needs_confirmation:
                    enhanced_history.append({
                        "role": "assistant",
                        "content": confirmation_message
                    })
            
            # Step 2: 使用 LLM 进行意图识别（根据当前状态）
            llm_response = await analyze_user_message(
                query, 
                enhanced_history,  # 使用增强后的对话历史
                user_profile,
                is_in_query_flow=is_in_query_flow,
                pending_preferences=pending_preferences
            )
            
            # Step 2.5: 更新用户画像（如果有新的画像信息）
            if self.profile_storage and llm_response.profile_updates:
                # 规范化 profile 更新
                raw_updates = {}
                if "demographics" in llm_response.profile_updates:
                    raw_updates["demographics"] = llm_response.profile_updates["demographics"]
                if "dining_habits" in llm_response.profile_updates:
                    raw_updates["dining_habits"] = llm_response.profile_updates["dining_habits"]
                
                if raw_updates:
                    # 规范化更新
                    profile_updates = self._normalize_profile_updates(raw_updates)
                    
                    # 合并更新到现有画像
                    current_profile = self.profile_storage.get_user_profile(user_id)
                    
                    # 处理 description 的更新（直接覆盖，不追加）
                    if "dining_habits" in profile_updates and "description" in profile_updates["dining_habits"]:
                        # description 直接覆盖，不追加，因为它是完整的描述
                        new_desc = profile_updates["dining_habits"]["description"]
                        if new_desc:  # 只有在新描述不为空时才更新
                            current_profile["dining_habits"]["description"] = new_desc
                        # 移除 profile_updates 中的 description，避免重复更新
                        profile_updates["dining_habits"] = {k: v for k, v in profile_updates["dining_habits"].items() if k != "description"}
                    
                    # 合并其他字段
                    for key, value in profile_updates.items():
                        if key in current_profile and isinstance(current_profile[key], dict) and isinstance(value, dict):
                            current_profile[key].update(value)
                        else:
                            current_profile[key] = value
                    
                    self.profile_storage.save_user_profile(user_id, current_profile)
                    # 重新加载更新后的画像
                    user_profile = self.profile_storage.get_user_profile(user_id)
            
            # Step 3: 根据意图类型和当前状态处理
            if is_in_query_flow:
                # ========== Query 流程状态 ==========
                # 在这个状态中，LLM 可以判断：confirmation_yes, confirmation_no, query, chat
                
                if llm_response.intent == "confirmation_yes":
                    # 用户确认，创建推荐任务
                    result = self._handle_confirmation_yes(query, user_id)
                    # 添加 preferences（从上下文中获取）
                    if user_id in self.user_contexts:
                        result["preferences"] = self.user_contexts[user_id].get("preferences")
                    return result
                
                elif llm_response.intent == "confirmation_no":
                    # 用户拒绝，但没有提供新偏好
                    # 清除上下文，返回 LLM 的自然回复
                    preferences = None
                    if user_id in self.user_contexts:
                        preferences = self.user_contexts[user_id].get("preferences")
                        del self.user_contexts[user_id]
                    
                    return {
                        "type": "llm_reply",
                        "llm_reply": llm_response.reply,
                        "intent": "chat",
                        "confidence": llm_response.confidence,
                        "preferences": preferences
                    }
                
                elif llm_response.intent == "query":
                    # 用户提供了新的偏好信息（拒绝旧偏好并提供新偏好）
                    # 提取新偏好并重新确认
                    if llm_response.preferences:
                        new_preferences = llm_response.preferences
                        
                        # 结合用户画像填充缺失的偏好项
                        if user_profile:
                            if new_preferences.get("budget_range", {}).get("min") == 20 and new_preferences.get("budget_range", {}).get("max") == 60:
                                typical_budget = user_profile.get("dining_habits", {}).get("typical_budget")
                                if typical_budget:
                                    if isinstance(typical_budget, dict):
                                        new_preferences["budget_range"].update(typical_budget)
                                    elif isinstance(typical_budget, (int, float)):
                                        new_preferences["budget_range"]["min"] = int(typical_budget * 0.8)
                                        new_preferences["budget_range"]["max"] = int(typical_budget * 1.2)
                            
                            if new_preferences.get("location") == "any" and user_profile.get("demographics", {}).get("location"):
                                new_preferences["location"] = user_profile["demographics"]["location"]
                        
                        # 更新用户偏好
                        self.update_user_preferences(user_id, new_preferences)
                        
                        # 生成新的确认消息
                        confirmation = await self.create_confirmation_request(
                            original_query, 
                            new_preferences, 
                            user_id, 
                            use_llm=True
                        )
                        
                        return {
                            "type": "confirmation",
                            "confirmation_request": confirmation,
                            "preferences": new_preferences
                        }
                    else:
                        # LLM 说这是 query 但没有返回偏好，回退到规则匹配
                        new_preferences = self.extract_preferences_from_query(query, user_id)
                        confirmation = await self.create_confirmation_request(
                            original_query,
                            new_preferences,
                            user_id,
                            use_llm=True
                        )
                        return {
                            "type": "confirmation",
                            "confirmation_request": confirmation,
                            "preferences": new_preferences
                        }
                
                elif llm_response.intent == "chat":
                    # 用户回到聊天状态，清除 query 上下文，回到起始状态
                    preferences = None
                    if user_id in self.user_contexts:
                        preferences = self.user_contexts[user_id].get("preferences")
                        del self.user_contexts[user_id]
                    
                    return {
                        "type": "llm_reply",
                        "llm_reply": llm_response.reply,
                        "intent": "chat",
                        "confidence": llm_response.confidence,
                        "preferences": preferences
                    }
            
            else:
                # ========== 起始状态 ==========
                # 在这个状态中，LLM 只判断：query 或 chat
                
                if llm_response.intent == "query":
                    # 新查询，进入 query 流程
                    # 使用 LLM 提取的偏好信息
                    if llm_response.preferences:
                        preferences = llm_response.preferences
                        
                        # 结合用户画像填充缺失的偏好项
                        if user_profile:
                            if preferences.get("budget_range", {}).get("min") == 20 and preferences.get("budget_range", {}).get("max") == 60:
                                typical_budget = user_profile.get("dining_habits", {}).get("typical_budget")
                                if typical_budget:
                                    if isinstance(typical_budget, dict):
                                        preferences["budget_range"].update(typical_budget)
                                    elif isinstance(typical_budget, (int, float)):
                                        preferences["budget_range"]["min"] = int(typical_budget * 0.8)
                                        preferences["budget_range"]["max"] = int(typical_budget * 1.2)
                            
                            if preferences.get("location") == "any" and user_profile.get("demographics", {}).get("location"):
                                preferences["location"] = user_profile["demographics"]["location"]
                        
                        # 更新用户偏好（在确认之前）
                        self.update_user_preferences(user_id, preferences)
                    else:
                        # LLM 没有返回偏好，使用规则匹配作为备用
                        preferences = self.extract_preferences_from_query(query, user_id)
                    
                    # 创建确认请求（使用 LLM 生成自然消息）
                    # 这会设置 user_contexts，进入 query 流程状态
                    confirmation = await self.create_confirmation_request(query, preferences, user_id, use_llm=True)
                    
                    return {
                        "type": "confirmation",
                        "confirmation_request": confirmation,
                        "preferences": preferences
                    }
                else:
                    # 普通对话，返回 LLM 的回复（保持在起始状态）
                    return {
                        "type": "llm_reply",
                        "llm_reply": llm_response.reply,
                        "intent": "chat",
                        "confidence": llm_response.confidence,
                        "preferences": llm_response.preferences  # 即使普通对话也可能包含偏好
                    }
        except Exception as e:
            print(f"Error in LLM intent analysis: {e}")
            # 出错时回退到原有逻辑
            return self.handle_user_request(query, user_id)
    
    def handle_user_request(
        self,
        query: str,
        user_id: str = "default"
    ) -> Dict[str, Any]:
        """
        处理用户请求的统一入口函数
        融合了意图识别、偏好提取、确认流程
        
        这个函数会自动处理：
        1. 意图识别（新查询/确认/拒绝）
        2. 偏好提取（如果是新查询）
        3. 确认流程（如果需要）
        4. 任务创建（如果用户确认）
        
        Args:
            query: 用户查询
            user_id: 用户ID
            
        Returns:
            包含以下字段的字典：
            - type: "confirmation" | "task_created" | "modify_request"
            - task_id: 任务ID（如果type为task_created）
            - confirmation_request: 确认请求对象（如果type为confirmation）
            - message: 消息文本（如果type为modify_request）
        """
        # Step 1: 意图识别
        intent = self.analyze_user_intent(query)
        
        # Step 2: 根据意图类型处理
        if intent["type"] == "new_query":
            # 新查询，需要确认
            return self._handle_new_query(query, user_id)
        elif intent["type"] == "confirmation_yes":
            # 用户确认，创建后台任务
            return self._handle_confirmation_yes(query, user_id)
        elif intent["type"] == "confirmation_no":
            # 用户拒绝，返回修改提示
            return self._handle_confirmation_no(query, user_id)
        else:
            # 其他意图，返回修改提示
            return {
                "type": "modify_request",
                "message": "I understand you'd like to modify your preferences. Please tell me what you'd like to change or provide more details about what you're looking for.",
                "preferences": {}
            }
    
    def _handle_confirmation_yes(self, query: str, user_id: str) -> Dict[str, Any]:
        """
        处理用户确认（创建推荐任务并清除 query 流程状态）
        
        Args:
            query: 用户查询
            user_id: 用户ID
            
        Returns:
            包含task_id的字典
        """
        if user_id in self.user_contexts:
            context = self.user_contexts[user_id]
            preferences = context["preferences"]
            original_query = context.get("original_query", query)
            
            # 清除上下文（退出 query 流程状态，回到起始状态）
            del self.user_contexts[user_id]
            
            # 创建后台任务
            task_id = self.create_task(original_query, preferences, user_id)
        else:
            # 没有上下文，当作新查询处理
            preferences = self.extract_preferences_from_query(query, user_id)
            task_id = self.create_task(query, preferences, user_id)
        
        return {
            "type": "task_created",
            "task_id": task_id,
            "message": "Task started successfully",
            "preferences": preferences
        }
    
    async def _handle_confirmation_no_async(
        self, 
        query: str, 
        user_id: str,
        conversation_history: Optional[List[Dict[str, Any]]] = None,
        user_profile: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        处理用户拒绝（异步版本，使用 LLM 判断是否需要更新偏好）
        
        Args:
            query: 用户查询
            user_id: 用户ID
            conversation_history: 对话历史（可选）
            user_profile: 用户画像（可选）
            
        Returns:
            包含修改提示或新确认请求的字典
        """
        # 获取之前的偏好上下文
        previous_preferences = None
        original_query = query
        if user_id in self.user_contexts:
            context = self.user_contexts[user_id]
            previous_preferences = context.get("preferences")
            original_query = context.get("original_query", query)
        
        # 使用 LLM 分析用户的回复，看是否包含新的偏好信息
        if analyze_user_message:
            try:
                # 构建包含上下文的对话历史
                # 如果 conversation_history 存在，使用它；否则创建新的
                enhanced_history = list(conversation_history) if conversation_history else []
                
                # 如果 conversation_history 的最后一条不是助手消息，或者没有 conversation_history，
                # 我们需要添加之前的确认消息作为上下文
                needs_prev_context = True
                if enhanced_history:
                    last_msg = enhanced_history[-1]
                    if last_msg.get("role") == "assistant":
                        needs_prev_context = False
                
                if previous_preferences and needs_prev_context:
                    # 添加之前的确认消息作为上下文，帮助 LLM 理解用户是在拒绝之前的偏好
                    # 使用更自然的确认消息格式
                    from llm_service import detect_language
                    language = detect_language(query) if detect_language else "en"
                    if language == "zh":
                        prev_msg = f"我刚才理解您想要：餐厅类型 {previous_preferences.get('restaurant_types', ['any'])}, 口味 {previous_preferences.get('flavor_profiles', ['any'])}, 用餐目的 {previous_preferences.get('dining_purpose', 'any')}, 预算 {previous_preferences.get('budget_range', {}).get('min', 20)}-{previous_preferences.get('budget_range', {}).get('max', 60)} SGD，位置 {previous_preferences.get('location', 'any')}。这样对吗？"
                    else:
                        prev_msg = f"I understand you want: restaurant type {previous_preferences.get('restaurant_types', ['any'])}, flavor {previous_preferences.get('flavor_profiles', ['any'])}, dining purpose {previous_preferences.get('dining_purpose', 'any')}, budget {previous_preferences.get('budget_range', {}).get('min', 20)}-{previous_preferences.get('budget_range', {}).get('max', 60)} SGD, location {previous_preferences.get('location', 'any')}. Is this correct?"
                    enhanced_history.append({
                        "role": "assistant",
                        "content": prev_msg
                    })
                
                # 使用 LLM 分析用户回复
                # analyze_user_message 会自动将 query 添加到消息列表的最后
                llm_response = await analyze_user_message(query, enhanced_history, user_profile)
                
                # 如果 LLM 检测到新的偏好信息（intent 为 query 且有 preferences）
                if llm_response.intent == "query" and llm_response.preferences:
                    # 用户提供了新的偏好信息，更新并重新确认
                    new_preferences = llm_response.preferences
                    
                    # 结合用户画像填充缺失的偏好项
                    if user_profile:
                        if new_preferences.get("budget_range", {}).get("min") == 20 and new_preferences.get("budget_range", {}).get("max") == 60:
                            typical_budget = user_profile.get("dining_habits", {}).get("typical_budget")
                            if typical_budget:
                                if isinstance(typical_budget, dict):
                                    new_preferences["budget_range"].update(typical_budget)
                                elif isinstance(typical_budget, (int, float)):
                                    new_preferences["budget_range"]["min"] = int(typical_budget * 0.8)
                                    new_preferences["budget_range"]["max"] = int(typical_budget * 1.2)
                        
                        if new_preferences.get("location") == "any" and user_profile.get("demographics", {}).get("location"):
                            new_preferences["location"] = user_profile["demographics"]["location"]
                    
                    # 更新用户偏好
                    self.update_user_preferences(user_id, new_preferences)
                    
                    # 更新用户画像（如果有）
                    if self.profile_storage and llm_response.profile_updates:
                        # 规范化 profile 更新
                        raw_updates = {}
                        if "demographics" in llm_response.profile_updates:
                            raw_updates["demographics"] = llm_response.profile_updates["demographics"]
                        if "dining_habits" in llm_response.profile_updates:
                            raw_updates["dining_habits"] = llm_response.profile_updates["dining_habits"]
                        
                        if raw_updates:
                            # 规范化更新
                            profile_updates = self._normalize_profile_updates(raw_updates)
                            
                            current_profile = self.profile_storage.get_user_profile(user_id)
                            
                            # 处理 description 的更新（直接覆盖，不追加）
                            if "dining_habits" in profile_updates and "description" in profile_updates["dining_habits"]:
                                # description 直接覆盖，不追加，因为它是完整的描述
                                new_desc = profile_updates["dining_habits"]["description"]
                                if new_desc:  # 只有在新描述不为空时才更新
                                    current_profile["dining_habits"]["description"] = new_desc
                                # 移除 profile_updates 中的 description，避免重复更新
                                profile_updates["dining_habits"] = {k: v for k, v in profile_updates["dining_habits"].items() if k != "description"}
                            
                            # 合并其他字段
                            for key, value in profile_updates.items():
                                if key in current_profile and isinstance(current_profile[key], dict) and isinstance(value, dict):
                                    current_profile[key].update(value)
                                else:
                                    current_profile[key] = value
                            self.profile_storage.save_user_profile(user_id, current_profile)
                    
                    # 生成新的确认消息
                    confirmation = await self.create_confirmation_request(
                        original_query, 
                        new_preferences, 
                        user_id, 
                        use_llm=True
                    )
                    
                    return {
                        "type": "confirmation",
                        "confirmation_request": confirmation
                    }
                else:
                    # 用户只是说 no，没有提供新偏好，给出自然的回复
                    # 清除上下文
                    if user_id in self.user_contexts:
                        del self.user_contexts[user_id]
                    
                    # 使用 LLM 的回复（如果可用），否则使用默认回复
                    if llm_response.reply:
                        return {
                            "type": "llm_reply",
                            "llm_reply": llm_response.reply,
                            "intent": "chat",
                            "confidence": llm_response.confidence
                        }
                    else:
                        # 回退到默认回复
                        return {
                            "type": "modify_request",
                            "message": "No problem! What would you like to change or what are you looking for instead?",
                            "preferences": {}
                        }
            except Exception as e:
                print(f"Error in LLM confirmation_no handling: {e}")
                # 出错时回退到简单处理
                if user_id in self.user_contexts:
                    del self.user_contexts[user_id]
                return {
                    "type": "modify_request",
                    "message": "I understand you'd like to modify your preferences. What would you like to change?",
                    "preferences": {}
                }
        else:
            # LLM 不可用，使用简单处理
            if user_id in self.user_contexts:
                del self.user_contexts[user_id]
            return {
                "type": "modify_request",
                "message": "I understand you'd like to modify your preferences. What would you like to change?",
                "preferences": {}
            }
    
    def _handle_confirmation_no(self, query: str, user_id: str) -> Dict[str, Any]:
        """
        处理用户拒绝（同步版本，用于回退逻辑）
        
        Args:
            query: 用户查询
            user_id: 用户ID
            
        Returns:
            包含修改提示的字典
        """
        if user_id in self.user_contexts:
            del self.user_contexts[user_id]
        
        return {
            "type": "modify_request",
            "message": "I understand you'd like to modify your preferences. What would you like to change?",
            "preferences": {}
        }
    
    def _handle_new_query(self, query: str, user_id: str) -> Dict[str, Any]:
        """
        处理新查询（用于回退逻辑）
        
        Args:
            query: 用户查询
            user_id: 用户ID
            
        Returns:
            包含确认请求的字典
        """
        # 提取偏好
        preferences = self.extract_preferences_from_query(query, user_id)
        
        # 创建确认请求（同步版本，使用模板格式）
        confirmation = self._create_confirmation_request_sync(query, preferences, user_id)
        
        return {
            "type": "confirmation",
            "confirmation_request": confirmation
        }
    
    def _create_confirmation_request_sync(
        self, 
        query: str, 
        preferences: Dict[str, Any], 
        user_id: str
    ) -> ConfirmationRequest:
        """
        创建确认请求对象（同步版本，用于回退逻辑）
        
        Args:
            query: 原始查询
            preferences: 提取的偏好
            user_id: 用户ID
            
        Returns:
            ConfirmationRequest对象
        """
        # 保存到上下文
        self.user_contexts[user_id] = {
            "preferences": preferences,
            "original_query": query,
            "timestamp": datetime.now().isoformat()
        }
        
        # 使用模板格式（同步）
        message = self.generate_confirmation_prompt(query, preferences)
        
        return ConfirmationRequest(
            message=message,
            preferences=preferences,
            needs_confirmation=True
        )
    
    



# ==================== 便捷函数 ====================

def create_service(restaurant_data: Optional[List[Dict]] = None) -> MetaRecService:
    """
    创建服务实例的便捷函数
    
    Args:
        restaurant_data: 可选的餐厅数据
        
    Returns:
        MetaRecService实例
    """
    return MetaRecService(restaurant_data)


