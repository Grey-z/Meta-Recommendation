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
    
    def create_confirmation_request(self, query: str, preferences: Dict[str, Any], user_id: str = "default") -> ConfirmationRequest:
        """
        创建确认请求对象
        
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
        
        message = self.generate_confirmation_prompt(query, preferences)
        
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
        # Step 1: 意图识别（可独立修改的函数）
        intent = self._identify_user_intent(query)
        
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
            pass # TODO: 其他意图，返回修改提示
    
    def _identify_user_intent(self, query: str) -> Dict[str, Any]:
        """
        识别用户意图（可独立修改的函数）
        
        Args:
            query: 用户查询
            
        Returns:
            意图分析结果
        """
        return self.analyze_user_intent(query)
    
    def _handle_confirmation_yes(self, query: str, user_id: str) -> Dict[str, Any]:
        """
        处理用户确认（可独立修改的函数）
        
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
            
            # 清除上下文
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
            "message": "Task started successfully"
        }
    
    def _handle_confirmation_no(self, query: str, user_id: str) -> Dict[str, Any]:
        """
        处理用户拒绝（可独立修改的函数）
        
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
            "message": "I understand you'd like to modify your preferences. Please tell me what you'd like to change or provide more details about what you're looking for.",
            "preferences": {}
        }
    
    def _handle_new_query(self, query: str, user_id: str) -> Dict[str, Any]:
        """
        处理新查询（可独立修改的函数）
        
        Args:
            query: 用户查询
            user_id: 用户ID
            
        Returns:
            包含确认请求的字典
        """
        # Step 1: 偏好提取（可独立修改的函数）
        preferences = self._extract_user_preferences(query, user_id)
        
        # Step 2: 创建确认请求（可独立修改的函数）
        confirmation = self._create_confirmation_for_preferences(query, preferences, user_id)
        
        return {
            "type": "confirmation",
            "confirmation_request": confirmation
        }
    
    def _extract_user_preferences(self, query: str, user_id: str) -> Dict[str, Any]:
        """
        提取用户偏好（可独立修改的函数）
        
        Args:
            query: 用户查询
            user_id: 用户ID
            
        Returns:
            偏好设置字典
        """
        return self.extract_preferences_from_query(query, user_id)
    
    def _create_confirmation_for_preferences(
        self, 
        query: str, 
        preferences: Dict[str, Any], 
        user_id: str
    ) -> ConfirmationRequest:
        """
        为偏好创建确认请求（可独立修改的函数）
        
        Args:
            query: 原始查询
            preferences: 提取的偏好
            user_id: 用户ID
            
        Returns:
            ConfirmationRequest对象
        """
        return self.create_confirmation_request(query, preferences, user_id)
    
    # ==================== 完整推荐流程（保留用于向后兼容）====================
    
    async def process_user_message(
        self,
        message: str,
        user_id: str = "default"
    ) -> Tuple[Optional[RecommendationResult], Optional[ConfirmationRequest]]:
        """
        处理用户消息的完整流程（保留用于向后兼容）
        
        这是一个高级接口，会自动处理：
        - 意图识别
        - 确认流程
        - 推荐生成
        
        Args:
            message: 用户消息
            user_id: 用户ID
            
        Returns:
            (推荐结果, 确认请求) 元组，两者只有一个不为None
        """
        # 分析用户意图
        intent = self.analyze_user_intent(message)
        
        if intent["type"] == "confirmation_yes":
            # 用户确认，从上下文获取偏好并生成推荐
            if user_id in self.user_contexts:
                context = self.user_contexts[user_id]
                preferences = context["preferences"]
                original_query = context.get("original_query", message)
                
                # 清除上下文
                del self.user_contexts[user_id]
                
                # 生成推荐
                result = await self.get_recommendations(original_query, preferences, user_id)
                return result, None
            else:
                # 没有上下文，当作新查询处理
                preferences = self.extract_preferences_from_query(message, user_id)
                result = await self.get_recommendations(message, preferences, user_id)
                return result, None
        
        elif intent["type"] == "confirmation_no":
            # 用户拒绝，返回修改提示
            if user_id in self.user_contexts:
                del self.user_contexts[user_id]
            
            confirmation = ConfirmationRequest(
                message="I understand you'd like to modify your preferences. Please tell me what you're looking for.",
                preferences={},
                needs_confirmation=True
            )
            return None, confirmation
        
        else:
            # 新查询，需要确认
            preferences = self.extract_preferences_from_query(message, user_id)
            confirmation = self.create_confirmation_request(message, preferences, user_id)
            return None, confirmation


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


