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
