from __future__ import annotations

import re
from typing import Dict, Iterable, Tuple


DOMAIN_KEYWORDS: Dict[str, Iterable[str]] = {
    "restaurant": [
        "restaurant", "restaurants", "food", "dining", "eat", "cuisine",
        "dinner", "lunch", "breakfast", "brunch", "餐厅", "美食", "吃",
        "吃饭", "晚餐", "午餐", "早餐", "菜", "口味",
    ],
    "hotel": ["hotel", "stay", "住宿", "酒店", "旅馆"],
    "music": ["music", "song", "playlist", "artist", "album", "音乐", "歌曲", "歌单"],
    "movie": ["movie", "film", "cinema", "showtime", "tv show", "电影", "影片", "影院"],
    "book": [
        "book recommendation", "recommend a book", "suggest a book",
        "books", "novel", "read", "author", "书", "小说", "阅读",
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
    scores = {
        domain: _keyword_score(query, keywords)
        for domain, keywords in DOMAIN_KEYWORDS.items()
    }
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
