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
        "feasibility_rate": 1.0,
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
        "eta_provider_call_count": 1,
        "retrieval_provider_call_count": 0,
        "cache_hit_count": 0,
        "retrieval_round_count": 0,
        "fallback_rate": 0.5,
        "candidate_count": 2,
        "expanded_states": 0,
        "repair_count": 0,
        "anchor_continuity": True,
        "hotel_continuity": True,
        "per_day_utilization": [],
        "mean_day_utilization": None,
        "idle_gap_min": 0,
        "budget_status_accuracy": None,
        "primary_experience_share": None,
        "semantic_rejection_rate": 0.0,
        "lodging_activity_count": 0,
        "zero_dwell_activity_count": 0,
        "soft_warning_count": 0,
        "meal_overallocation_count": 0,
        "parent_access_violation_count": 0,
        "automatic_repair_attempted": False,
        "automatic_repair_success": None,
        "automatic_repair_added_provider_calls": 0,
        "automatic_repair_latency_ms": None,
        "solver_runtime_ms": None,
        "runtime_ms": None,
    }


def test_refinement_stability_compares_slot_choices():
    current = _block()
    previous = _block()
    current["slots"][1]["chosen"]["id"] = "c"
    assert evaluate_itinerary(current, previous)["refinement_stability"] == 0.5


def test_soft_policy_warnings_do_not_reduce_hard_feasibility():
    block = _block()
    block["validation"]["warnings"] = [
        {"code": "missing_primary_experience"},
        {"code": "meal_overallocation"},
    ]

    metrics = evaluate_itinerary(block)

    assert metrics["feasibility_rate"] == 1.0
    assert metrics["hard_constraint_pass_rate"] == 1.0
    assert metrics["soft_warning_count"] == 2
    assert metrics["meal_overallocation_count"] == 1


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


def test_multi_day_metrics_include_utilization_retrieval_and_budget_accuracy():
    block = _block()
    block["planning_status"] = "feasible"
    block["days"] = [
        {"start_time": "09:00", "end_time_constraint": "17:00", "totals": {"total_activity_min": 300, "total_travel_min": 60, "total_wait_min": 30}},
        {"start_time": "09:00", "end_time_constraint": "15:00", "totals": {"total_activity_min": 240, "total_travel_min": 30, "total_wait_min": 0}},
    ]
    block["cost_summary"] = {
        "min": 80, "max": 90, "currency": "SGD",
        "budget_limit": 100, "budget_status": "feasible",
    }
    block["retrieval"] = {
        "provider_calls": 3,
        "rounds": [
            {"retrievals": [{"cache_status": "miss"}, {"cache_status": "hit"}]},
            {"retrievals": [{"cache_status": "negative_hit"}]},
        ],
    }
    metrics = evaluate_itinerary(block)
    assert metrics["per_day_utilization"] == [0.812, 0.75]
    assert metrics["mean_day_utilization"] == 0.781
    assert metrics["idle_gap_min"] == 180
    assert metrics["retrieval_provider_call_count"] == 3
    assert metrics["provider_call_count"] == 4
    assert metrics["cache_hit_count"] == 2
    assert metrics["retrieval_round_count"] == 2
    assert metrics["budget_status_accuracy"] == 1.0
