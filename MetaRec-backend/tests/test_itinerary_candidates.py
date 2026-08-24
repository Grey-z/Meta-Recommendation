import json

import pytest

from conftest import FakeAsyncClient
from langgraph_metarec.itinerary_candidates import (
    apply_role_enrichment,
    apply_containment_enrichment,
    build_itinerary_gather_query,
    containment_enrichment_input,
    apply_duration_enrichment,
    duration_enrichment_input,
    normalize_candidates,
    parse_opening_hours,
    role_enrichment_input,
)
from langgraph_metarec.itinerary_contracts import (
    BudgetConstraint,
    DayConstraint,
    ItineraryPlanningRequest,
    LocationConstraint,
    planning_request_from_preferences,
)
from llm_service import enrich_itinerary_durations

pytestmark = pytest.mark.backend_unit


def _request() -> ItineraryPlanningRequest:
    return ItineraryPlanningRequest(
        location=LocationConstraint(query="Singapore", timezone="Asia/Singapore"),
        days=(DayConstraint(0, "2026-08-03", 540, 1200),),  # Monday
        budget=BudgetConstraint("limited", 150, "SGD"),
    )


def test_normalize_compound_poi_and_restaurant_cost_without_inventing_admission():
    candidates = normalize_candidates([
        {
            "id": "uss", "domain": "attraction", "title": "Universal Studios Singapore",
            "gps_coordinates": {"latitude": 1.254, "longitude": 103.823},
            "opening_hours": "Mo-Su 10:00-20:00",
        },
        {
            "id": "meal", "name": "Lunch", "domain": "restaurant",
            "gps_coordinates": {"latitude": 1.255, "longitude": 103.824},
            "price_per_person_sgd": 32,
        },
    ], _request())
    universal, meal = candidates
    assert universal.duration.preferred == 510
    assert universal.meal_coverage == ("lunch",)
    assert universal.cost.min is None and universal.cost.source == "unknown"
    assert universal.availability_known is True
    assert meal.cost.min == meal.cost.max == 32
    assert meal.cost.currency == "SGD"


def test_opening_hours_common_subset_and_candidate_dedupe():
    assert parse_opening_hours("Mo-Fr 09:00-17:00; Sa 10:00-12:00", "2026-08-03")[0].start_min == 540
    raw = {
        "id": "same", "domain": "attraction", "title": "Gallery",
        "gps_coordinates": {"latitude": 1.3, "longitude": 103.8},
        "raw": {"tags": {"tourism": "gallery"}},
    }
    normalized = normalize_candidates([raw, dict(raw)], _request())
    assert len(normalized) == 1
    assert normalized[0].duration.preferred == 90


def test_opening_hours_preserves_requested_day_index():
    windows = parse_opening_hours(
        "Tu 10:00-18:00", "2026-08-04", day_index=1
    )
    assert len(windows) == 1
    assert windows[0].day_index == 1
    assert (windows[0].start_min, windows[0].end_min) == (600, 1080)


def test_duration_enrichment_only_updates_low_confidence_known_ids():
    candidates = normalize_candidates([{
        "id": "unknown", "domain": "attraction", "title": "Interesting Place",
        "gps_coordinates": {"latitude": 1.3, "longitude": 103.8},
    }], _request())
    assert duration_enrichment_input(candidates)[0]["id"] == "unknown"
    updated = apply_duration_enrichment(candidates, {"durations": [
        {"id": "unknown", "min": 30, "preferred": 60, "max": 90, "confidence": 0.8},
        {"id": "invented", "min": 30, "preferred": 60, "max": 90},
    ]})
    assert updated[0].duration.source == "llm"
    assert updated[0].duration.preferred == 60
    invalid = apply_duration_enrichment(candidates, {"durations": [
        {"id": "unknown", "min": 90, "preferred": 60, "max": 30},
    ]})
    assert invalid[0].duration.source == "rule"


@pytest.mark.asyncio
async def test_llm_duration_enrichment_returns_structured_batch_only():
    response = json.dumps({"durations": [{"id": "p1", "min": 30, "preferred": 45, "max": 60}]})
    result = await enrich_itinerary_durations(
        FakeAsyncClient([response]),
        candidates=[{"id": "p1", "title": "Four-language sign", "domain": "attraction", "tags": []}],
    )
    assert result == {"durations": [{"id": "p1", "min": 30, "preferred": 45, "max": 60}]}


def test_provider_roles_filter_lodging_and_food_from_attraction_pool():
    diagnostics = {}
    candidates = normalize_candidates([
        {
            "id": "museum", "domain": "attraction", "title": "City Museum",
            "tags": ["museum"], "gps_coordinates": {"latitude": 1.30, "longitude": 103.80},
        },
        {
            "id": "hotel", "domain": "attraction", "title": "Resort Hotel",
            "tags": ["resort hotel"], "gps_coordinates": {"latitude": 1.31, "longitude": 103.81},
        },
        {
            "id": "cafe", "domain": "attraction", "title": "Cafe",
            "tags": ["cafe"], "gps_coordinates": {"latitude": 1.32, "longitude": 103.82},
        },
    ], _request(), diagnostics=diagnostics)
    assert [item.id for item in candidates] == ["museum"]
    assert candidates[0].role == "experience"
    assert diagnostics["rejection_counts"] == {
        "domain_mismatch:lodging": 1,
        "domain_mismatch:food": 1,
    }


def test_unknown_role_requires_valid_existing_id_and_cross_provider_dedupes():
    diagnostics = {}
    candidates = normalize_candidates([
        {
            "id": "p1", "domain": "attraction", "title": "Mystery Hall",
            "gps_coordinates": {"latitude": 1.30000, "longitude": 103.80000},
        },
        {
            "id": "p2", "domain": "attraction", "title": "Mystery Hall",
            "gps_coordinates": {"latitude": 1.30004, "longitude": 103.80004},
        },
    ], _request(), diagnostics=diagnostics)
    assert [row["id"] for row in role_enrichment_input(candidates)] == ["p1"]
    resolved = apply_role_enrichment(candidates, {"roles": [
        {"id": "invented", "role": "experience"},
        {"id": "p1", "role": "experience"},
    ]}, diagnostics)
    assert [item.id for item in resolved] == ["p1"]
    assert resolved[0].role_source == "llm"
    assert diagnostics["rejection_counts"]["duplicate_physical_poi"] == 1


def test_gather_query_uses_confirmed_constraints_not_full_request_or_anchor():
    request, errors = planning_request_from_preferences({
        "location": "Sentosa", "date": "2026-08-03", "start_time": "09:00",
        "end_time": "18:00", "timezone": "Asia/Singapore", "budget_mode": "unlimited",
        "style": "shopping", "pace": "balanced", "attraction_types": ["market"],
        "must_visit": ["Fort Siloso"], "hotel_anchor": "Beach Hotel",
    })
    assert errors == [] and request is not None
    query = build_itinerary_gather_query(request, "attraction")
    assert query == "shopping attractions market in Sentosa including Fort Siloso"
    assert "Beach Hotel" not in query


def test_gather_query_carries_explicit_interest_terms_to_attraction_search():
    request, errors = planning_request_from_preferences({
        "location": "Singapore", "date": "2026-08-03", "start_time": "09:00",
        "end_time": "18:00", "timezone": "Asia/Singapore", "budget_mode": "unlimited",
        "style": "sightseeing", "pace": "balanced",
        "attraction_types": ["university-campus"],
        "interest_terms": ["university campus", "academic architecture"],
    })

    assert errors == [] and request is not None
    query = build_itinerary_gather_query(request, "attraction")
    assert query == (
        "sightseeing attractions university campus academic architecture in Singapore"
    )


def test_university_amenity_normalizes_as_an_experience():
    candidates = normalize_candidates([{
        "id": "campus", "domain": "attraction", "title": "Example University",
        "amenity": "university",
        "gps_coordinates": {"latitude": 1.34, "longitude": 103.68},
    }], _request())

    assert len(candidates) == 1
    assert candidates[0].role == "experience"


def test_gated_child_requires_exact_parent_and_public_child_stays_independent():
    diagnostics = {}
    candidates = normalize_candidates([
        {
            "id": "park", "domain": "attraction", "title": "Adventure Theme Park",
            "tags": ["theme park"], "subtitle": "1 Fun Road",
            "gps_coordinates": {"latitude": 1.2500, "longitude": 103.8200},
        },
        {
            "id": "inside", "domain": "restaurant", "title": "Inside Cafe",
            "parent_id": "park", "gps_coordinates": {"latitude": 1.2501, "longitude": 103.8201},
        },
        {
            "id": "public", "domain": "restaurant", "title": "Public Cafe",
            "public_access": True, "gps_coordinates": {"latitude": 1.2502, "longitude": 103.8202},
        },
    ], _request(), diagnostics=diagnostics)
    rows = containment_enrichment_input(candidates)
    assert [row["id"] for row in rows] == ["inside"]
    resolved = apply_containment_enrichment(candidates, {"relations": [
        {"id": "inside", "parent_id": "park", "access": "gated"},
        {"id": "invented", "parent_id": "park", "access": "gated"},
    ]}, diagnostics)
    by_id = {item.id: item for item in resolved}
    assert by_id["inside"].access == "gated" and by_id["inside"].parent_id == "park"
    assert by_id["public"].access == "independent" and by_id["public"].parent_id is None


def test_unresolved_likely_child_is_excluded_as_repairable():
    diagnostics = {}
    candidates = normalize_candidates([
        {
            "id": "park", "domain": "attraction", "title": "Adventure Theme Park",
            "tags": ["theme park"], "gps_coordinates": {"latitude": 1.25, "longitude": 103.82},
        },
        {
            "id": "inside", "domain": "restaurant", "title": "Inside Cafe",
            "parent_id": "park", "gps_coordinates": {"latitude": 1.2501, "longitude": 103.8201},
        },
    ], _request(), diagnostics=diagnostics)
    resolved = apply_containment_enrichment(candidates, None, diagnostics)
    assert [item.id for item in resolved] == ["park"]
    assert diagnostics["rejection_counts"]["unknown_access"] == 1


def test_gather_query_names_must_visit_in_the_restaurant_search_too():
    """A must-visit is often a food venue, and only the restaurant search finds those.

    Regression for the NTU run: "Canteen B" was appended to the attraction query
    alone, so no provider was ever asked for it, the solver hard-failed on
    must_visit_unavailable, and the empty plan then reported all three meal
    obligations as unmet.
    """
    request, errors = planning_request_from_preferences({
        "location": "Nanyang Technological University, Singapore", "date": "2026-08-11",
        "start_time": "09:00", "end_time": "22:00", "timezone": "Asia/Singapore",
        "budget_mode": "unlimited", "style": "sightseeing", "pace": "balanced",
        "must_visit": ["Canteen B"],
        "meal_obligations": [
            {"meal": "breakfast", "day_index": 0},
            {"meal": "lunch", "day_index": 0},
            {"meal": "dinner", "day_index": 0},
        ],
    })
    assert errors == [] and request is not None

    restaurant_query = build_itinerary_gather_query(request, "restaurant")
    attraction_query = build_itinerary_gather_query(request, "attraction")

    assert "Canteen B" in restaurant_query
    assert "Canteen B" in attraction_query
    # The meal context the restaurant search already relied on must survive.
    assert "breakfast, lunch, dinner" in restaurant_query


def test_gather_query_omits_must_visit_when_none_requested():
    request, errors = planning_request_from_preferences({
        "location": "Singapore", "date": "2026-08-03", "start_time": "09:00",
        "end_time": "18:00", "timezone": "Asia/Singapore", "budget_mode": "unlimited",
        "style": "sightseeing", "pace": "balanced",
    })
    assert errors == [] and request is not None

    assert "including" not in build_itinerary_gather_query(request, "restaurant")
    assert "including" not in build_itinerary_gather_query(request, "attraction")
