import pytest

from langgraph_metarec.nodes.domain import classify_domain


@pytest.mark.backend_unit
def test_classify_domain_restaurant():
    domain, confidence, reason = classify_domain("Recommend spicy restaurants in Chinatown")

    assert domain == "restaurant"
    assert confidence > 0.5
    assert "restaurant" in reason


@pytest.mark.backend_unit
def test_classify_domain_multi_domain():
    domain, confidence, reason = classify_domain("Recommend a movie and a restaurant for tonight")

    assert domain == "multi_domain"
    assert confidence > 0.5
    assert "multiple" in reason


@pytest.mark.backend_unit
def test_classify_domain_future_domain_music():
    domain, confidence, _ = classify_domain("Build a relaxing music playlist")

    assert domain == "music"
    assert confidence > 0.5


@pytest.mark.backend_unit
def test_classify_domain_chinese_implicit_music_fallback():
    domain, confidence, _ = classify_domain("万能青年旅店有什么歌好听呀")

    assert domain == "music"
    assert confidence > 0.5


@pytest.mark.backend_unit
def test_classify_domain_does_not_match_book_as_restaurant_booking_verb():
    domain, _, reason = classify_domain("Can you help me book a restaurant in Chinatown?")

    assert domain == "restaurant"
    assert "restaurant" in reason


@pytest.mark.backend_unit
def test_classify_domain_does_not_match_show_as_generic_verb():
    domain, _, reason = classify_domain("Show me restaurants near Orchard")

    assert domain == "restaurant"
    assert "restaurant" in reason


@pytest.mark.backend_unit
def test_classify_domain_future_domain_book_phrase():
    domain, confidence, _ = classify_domain("Can you recommend a book for the weekend?")

    assert domain == "book"
    assert confidence > 0.5


@pytest.mark.backend_unit
@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("Find a guest house near the old town", "hotel"),
        ("帮我找一家青旅或者民宿", "hotel"),
        ("Suggest a documentary series", "movie"),
        ("推荐一部纪录片", "movie"),
        ("Any good earbuds to buy?", "product"),
        ("推荐一个耳机", "product"),
        ("Find a comic to read", "book"),
        ("有什么漫画好看", "book"),
        ("Recommend tracks by this singer", "music"),
        ("What are the must-see attractions in Sentosa?", "attraction"),
        ("Any good sightseeing spots this weekend?", "attraction"),
        ("推荐几个新加坡的景点", "attraction"),
        ("周末去哪里观光比较好", "attraction"),
        ("Which parks and beaches are worth visiting?", "attraction"),
        ("推荐几个有历史古迹的地方", "attraction"),
    ],
)
def test_classify_domain_enriched_keyword_vocab(query, expected):
    domain, confidence, _ = classify_domain(query)

    assert domain == expected
    assert confidence > 0.5
