import pytest

from langgraph_metarec.tool_compaction import (
    MAX_ITEMS_PER_TOOL,
    _LIST_CAP,
    _TEXT_CAP,
    compact_tool_output,
)


@pytest.mark.backend_unit
def test_gmap_caps_reviews_but_preserves_structured_metadata():
    long_review = "x" * (_TEXT_CAP + 50)
    item = {
        "title": "Sichuan House",
        "rating": 4.6,
        "reviews": 1234,
        "price": "$$",
        "type": "Sichuan restaurant",
        "address": "1 Food St",
        "phone": "+65 1234 5678",
        "gps_coordinates": {"latitude": 1.23, "longitude": 103.8},
        "hours": "11am-10pm",
        "operating_hours": {"monday": "11am-10pm", "tuesday": "11am-10pm"},
        "open_state": "Open now",
        "reviews_link": "https://maps.google.com/reviews/abc",
        "photos_link": "https://maps.google.com/photos/abc",
        "user_reviews": [{"text": long_review, "rating": 5} for _ in range(6)],
    }

    [compacted] = compact_tool_output("gmap.search", [item])

    # High-volume free text is bounded.
    assert len(compacted["user_reviews"]) == _LIST_CAP
    bounded_text = compacted["user_reviews"][0]["text"]
    assert bounded_text.endswith("…")
    assert len(bounded_text) <= _TEXT_CAP + 1

    # Structured metadata (incl. opening hours) is preserved verbatim.
    for key in (
        "title", "rating", "reviews", "price", "type", "address", "phone",
        "gps_coordinates", "hours", "operating_hours", "open_state",
        "reviews_link", "photos_link",
    ):
        assert compacted[key] == item[key], key


@pytest.mark.backend_unit
def test_gmap_review_count_preserved_when_under_cap():
    item = {"title": "A", "user_reviews": [{"text": "short", "rating": 5}]}
    [compacted] = compact_tool_output("gmap.search", [item])
    assert compacted["user_reviews"] == [{"text": "short", "rating": 5}]


@pytest.mark.backend_unit
def test_yelp_truncates_snippet_keeps_categories():
    item = {
        "title": "Pho 99",
        "categories": ["Vietnamese", "Noodles", "Casual"],
        "price": "$$",
        "rating": 4.5,
        "reviews": 320,
        "snippet": "y" * 400,
        "link": "https://yelp.com/biz/pho-99",
        "neighborhoods": "Chinatown",
    }

    [compacted] = compact_tool_output("yelp.search", [item])

    assert compacted["snippet"].endswith("…")
    assert len(compacted["snippet"]) <= 321
    assert compacted["categories"] == item["categories"]
    assert compacted["link"] == item["link"]
    assert compacted["neighborhoods"] == "Chinatown"


@pytest.mark.backend_unit
def test_xhs_truncates_desc_keeps_engagement_metadata():
    item = {
        "id": "note-1",
        "title": "best pho",
        "desc": "z" * 400,
        "liked_count": 999,
        "collected_count": 42,
        "comments_count": 7,
        "publish_time": "2026-01-01",
    }

    [compacted] = compact_tool_output("xhs.search", [item])

    assert compacted["desc"].endswith("…")
    assert len(compacted["desc"]) <= 321
    for key in ("id", "title", "liked_count", "collected_count", "comments_count", "publish_time"):
        assert compacted[key] == item[key], key


@pytest.mark.backend_unit
def test_caps_number_of_candidates_keeping_order():
    items = [{"title": f"R{i}", "rating": 4.0} for i in range(MAX_ITEMS_PER_TOOL + 5)]
    compacted = compact_tool_output("gmap.search", items)
    assert len(compacted) == MAX_ITEMS_PER_TOOL
    assert [c["title"] for c in compacted] == [f"R{i}" for i in range(MAX_ITEMS_PER_TOOL)]


@pytest.mark.backend_unit
def test_none_and_non_list_passthrough_preserves_dispatch_semantics():
    assert compact_tool_output("gmap.search", None) is None
    assert compact_tool_output("gmap.search", {"error": "boom"}) == {"error": "boom"}
    assert compact_tool_output("gmap.search", []) == []


@pytest.mark.backend_unit
def test_unknown_tool_keeps_fields_verbatim_but_caps_count():
    items = [{"title": f"R{i}", "blob": "k" * 1000} for i in range(MAX_ITEMS_PER_TOOL + 2)]
    compacted = compact_tool_output("unknown.search", items)
    assert len(compacted) == MAX_ITEMS_PER_TOOL
    # No field caps for unknown tools -> values preserved verbatim.
    assert compacted[0]["blob"] == "k" * 1000


@pytest.mark.backend_unit
def test_non_dict_items_passthrough():
    assert compact_tool_output("gmap.search", ["a", 1, None]) == ["a", 1, None]
