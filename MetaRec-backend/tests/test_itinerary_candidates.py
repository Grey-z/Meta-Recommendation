import json

import pytest

from conftest import FakeAsyncClient
from langgraph_metarec.itinerary_candidates import (
    apply_duration_enrichment,
    duration_enrichment_input,
    normalize_candidates,
    parse_opening_hours,
)
from langgraph_metarec.itinerary_contracts import (
    BudgetConstraint,
    DayConstraint,
    ItineraryPlanningRequest,
    LocationConstraint,
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
