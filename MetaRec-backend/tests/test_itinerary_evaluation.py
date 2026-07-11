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
        "travel_ratio": 1.0,
        "budget_deviation": 10.0,
        "budget_currency": "SGD",
        "budget_status": None,
        "uncertainty_rate": 0.0,
        "planning_status": None,
        "preference_match": 0.85,
        "provider_call_count": 1,
        "fallback_rate": 0.5,
        "candidate_count": 2,
        "expanded_states": 0,
        "repair_count": 0,
    }


def test_refinement_stability_compares_slot_choices():
    current = _block()
    previous = _block()
    current["slots"][1]["chosen"]["id"] = "c"
    assert evaluate_itinerary(current, previous)["refinement_stability"] == 0.5


def test_dynamic_metrics_report_budget_uncertainty_and_solver_work():
    block = _block()
    block["planning_status"] = "needs_refinement"
    block["uncertainties"] = [{"code": "cost_unknown"}]
    block["cost_summary"] = {
        "min": 40, "max": None, "currency": "SGD",
        "budget_limit": 50, "budget_status": "indeterminate",
    }
    block["totals"]["total_activity_min"] = 180
    block["solver"] = {"candidate_count": 12, "expanded_states": 48, "repair_count": 1}
    metrics = evaluate_itinerary(block)
    assert metrics["uncertainty_rate"] == 0.5
    assert metrics["budget_status"] == "indeterminate"
    assert metrics["budget_deviation"] is None
    assert metrics["travel_ratio"] == 0.143
    assert metrics["candidate_count"] == 12
    assert metrics["repair_count"] == 1
