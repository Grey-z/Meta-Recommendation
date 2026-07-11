import pytest

from langgraph_metarec.itinerary_evaluation import evaluate_itinerary

pytestmark = pytest.mark.backend_unit


def _block():
    return {
        "slots": [
            {"slot_index": 0, "chosen": {"id": "a", "rating": 4.5}},
            {"slot_index": 1, "chosen": {"id": "b", "rating": 4.0}},
        ],
        "legs": [
            {"source": "onemap", "cache": "miss"},
            {"source": "estimate"},
        ],
        "totals": {"total_travel_min": 30},
        "validation": {
            "violations": [],
            "checks": {"estimated_food_spend_sgd": 60, "budget_limit_sgd": 50},
        },
    }


def test_offline_metrics_are_deterministic_and_provider_free():
    metrics = evaluate_itinerary(_block())
    assert metrics == {
        "delivery_rate": 1.0,
        "hard_constraint_pass_rate": 1.0,
        "commonsense_pass_rate": 1.0,
        "duplicate_rate": 0.0,
        "schedule_conflict_rate": 0.0,
        "route_travel_min": 30,
        "budget_deviation_sgd": 10.0,
        "preference_match": 0.85,
        "provider_call_count": 1,
        "fallback_rate": 0.5,
    }


def test_refinement_stability_compares_slot_choices():
    current = _block()
    previous = _block()
    current["slots"][1]["chosen"]["id"] = "c"
    assert evaluate_itinerary(current, previous)["refinement_stability"] == 0.5

