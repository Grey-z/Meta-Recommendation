from __future__ import annotations

import re
from typing import Dict, Iterable, List, Tuple


DOMAIN_KEYWORDS: Dict[str, Iterable[str]] = {
    "restaurant": [
        "restaurant", "restaurants", "food", "dining", "eat", "cuisine",
        "dinner", "lunch", "breakfast", "brunch", "cafe", "cafes",
        "bistro", "hawker", "coffee shop", "餐厅", "餐馆", "饭店", "美食", "吃",
        "吃饭", "晚餐", "午餐", "早餐", "菜", "口味", "咖啡馆", "小吃",
    ],
    "hotel": [
        "hotel", "hotels", "stay", "stays", "lodging", "accommodation",
        "hostel", "hostels", "guest house", "guesthouse", "motel", "resort",
        "inn", "bnb", "bed and breakfast", "住宿", "酒店", "旅馆",
        "宾馆", "賓館", "民宿", "青旅", "客栈", "客棧", "度假村",
    ],
    "attraction": [
        "attraction", "attractions", "sightseeing", "things to do", "tourist spot",
        "tourist spots", "landmark", "landmarks", "museum", "museums", "gallery",
        "theme park", "theme parks", "zoo", "aquarium", "viewpoint", "observation deck",
        "park", "parks", "botanical garden", "nature reserve", "beach", "beaches",
        "waterfall", "monument", "memorial", "historic site", "heritage site", "lighthouse",
        "景点", "景區", "景区", "观光", "觀光", "游玩", "遊玩", "打卡",
        "博物馆", "博物館", "美术馆", "美術館", "主题公园", "主題公園",
        "动物园", "動物園", "水族馆", "水族館", "地标", "地標", "名胜",
        "公园", "公園", "植物园", "植物園", "自然保护区", "自然保護區",
        "海滩", "海灘", "瀑布", "古迹", "古蹟", "纪念碑", "紀念碑", "灯塔", "燈塔",
    ],
    "music": [
        "music", "song", "songs", "playlist", "artist", "album", "band",
        "track", "tracks", "single", "singer", "musician", "音乐", "歌曲",
        "歌单", "歌", "歌手", "乐队", "樂隊", "专辑", "專輯", "听歌", "好听",
    ],
    "movie": [
        "movie", "movies", "film", "films", "cinema", "showtime", "tv show",
        "tv series", "series", "drama", "documentary", "电影", "影片", "影院",
        "电视剧", "劇集", "剧集", "纪录片", "影集",
    ],
    "book": [
        "book recommendation", "recommend a book", "suggest a book",
        "books", "novel", "novels", "read", "reading", "author", "writer",
        "publisher", "manga", "comic", "书", "書", "小说", "小說", "阅读",
        "閱讀", "作者", "出版社", "漫画", "漫畫",
    ],
    "product": [
        "product", "products", "buy", "shopping", "shop", "amazon",
        "laptop", "notebook", "headphones", "earbuds", "phone", "smartphone",
        "camera", "monitor", "gift", "deal", "商品", "产品", "產品", "购物",
        "購物", "购买", "購買", "买", "買", "礼物", "禮物", "电脑", "筆電",
        "笔记本", "手機", "手机", "耳机", "耳機",
    ],
}


def _contains_cjk(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text)


def _keyword_score(text: str, keywords: Iterable[str]) -> int:
    score = 0
    lowered = text.lower()
    for keyword in keywords:
        normalized_keyword = keyword.lower()
        if _contains_cjk(normalized_keyword):
            matched = normalized_keyword in lowered
        else:
            # English keywords should match as full words/phrases so verbs
            # like "book a restaurant" do not accidentally route to books.
            pattern = r"(?<![a-z0-9_])" + re.escape(normalized_keyword) + r"(?![a-z0-9_])"
            matched = bool(re.search(pattern, lowered))
        if matched:
            score += 1
    return score


def classify_domain(query: str) -> Tuple[str, float, str]:
    scores = domain_scores(query)
    matched = {domain: score for domain, score in scores.items() if score > 0}
    if not matched:
        return "unknown", 0.0, "no domain keywords matched"

    sorted_matches = sorted(matched.items(), key=lambda item: item[1], reverse=True)
    top_domain, top_score = sorted_matches[0]
    if len(sorted_matches) > 1 and sorted_matches[1][1] > 0:
        confidence = min(0.95, 0.45 + 0.15 * len(sorted_matches))
        return "multi_domain", confidence, f"matched multiple domains: {matched}"

    confidence = min(0.95, 0.55 + 0.15 * top_score)
    return top_domain, confidence, f"matched {top_domain} keywords"


def domain_scores(query: str) -> Dict[str, int]:
    return {
        domain: _keyword_score(query, keywords)
        for domain, keywords in DOMAIN_KEYWORDS.items()
    }


def detect_domains(query: str) -> List[str]:
    scores = domain_scores(query)
    return [
        domain
        for domain, score in sorted(scores.items(), key=lambda item: (-item[1], item[0]))
        if score > 0
    ]
