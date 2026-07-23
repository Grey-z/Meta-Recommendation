import pytest

from langgraph_metarec.itinerary_metrics import compute_route_quality_metrics

pytestmark = pytest.mark.backend_unit


MEAL_WINDOWS = {
    "breakfast": (420, 630),
    "lunch": (690, 870),
    "dinner": (1050, 1260),
}


def test_route_metrics_compare_same_stops_with_fixed_anchors():
    metrics = compute_route_quality_metrics(
        travel_minutes={
            "anchor:start": {"a": 10, "b": 5},
            "a": {"b": 30, "anchor:end": 10},
            "b": {"a": 5, "anchor:end": 10},
        },
        day_routes=[{
            "day_index": 0,
            "activity_ids": ["a", "b"],
            "start_id": "anchor:start",
            "end_id": "anchor:end",
            "window_min": 600,
        }],
        activities=[
            {"day_index": 0, "candidate_id": "a", "start_min": 540, "end_min": 600},
            {
                "day_index": 0,
                "candidate_id": "b",
                "start_min": 690,
                "end_min": 765,
                "satisfied_meals": ["lunch"],
            },
        ],
        meal_windows=MEAL_WINDOWS,
    )

    assert metrics["estimated_route_travel_min"] == 50
    assert metrics["best_same_stops_travel_min"] == 20
    assert metrics["route_order_excess_min"] == 30
    assert metrics["route_order_detour_ratio"] == 2.5
    assert metrics["estimated_travel_window_share"] == pytest.approx(50 / 600, abs=1e-6)
    assert metrics["estimated_travel_minutes_per_activity"] == 25
    assert metrics["meal_time_naturalness"] == pytest.approx(5 / 6, abs=1e-6)
    assert metrics["measured_meal_count"] == 1


def test_multi_day_metrics_keep_days_and_lodging_boundaries_separate():
    metrics = compute_route_quality_metrics(
        travel_minutes={
            "lodging:h": {"a": 10, "b": 30, "c": 20},
            "a": {"lodging:h": 10},
            "b": {"c": 25, "lodging:h": 10},
            "c": {"b": 5, "lodging:h": 10},
        },
        day_routes=[
            {
                "day_index": 0,
                "activity_ids": ["a"],
                "start_id": "lodging:h",
                "end_id": "lodging:h",
                "window_min": 480,
            },
            {
                "day_index": 1,
                "activity_ids": ["b", "c"],
                "start_id": "lodging:h",
                "end_id": "lodging:h",
                "window_min": 480,
            },
        ],
        activities=[],
        meal_windows=MEAL_WINDOWS,
    )

    assert metrics["route_metric_day_count"] == 2
    assert metrics["estimated_route_travel_min"] == 85
    assert metrics["best_same_stops_travel_min"] == 55
    assert metrics["route_order_excess_min"] == 30
    assert [row["day_index"] for row in metrics["route_metrics_by_day"]] == [0, 1]
    assert metrics["route_metrics_by_day"][0]["route_order_detour_ratio"] == 1.0
    assert metrics["route_metrics_by_day"][1]["route_order_detour_ratio"] == pytest.approx(
        65 / 35, abs=1e-6
    )


def test_detour_ratio_does_not_hide_absolute_travel_burden():
    metrics = compute_route_quality_metrics(
        travel_minutes={"a": {"b": 240}, "b": {"a": 240}},
        day_routes=[{
            "day_index": 0,
            "activity_ids": ["a", "b"],
            "window_min": 480,
        }],
        activities=[],
        meal_windows=MEAL_WINDOWS,
    )

    assert metrics["route_order_detour_ratio"] == 1.0
    assert metrics["estimated_travel_window_share"] == 0.5
    assert metrics["estimated_travel_minutes_per_activity"] == 120


def test_missing_matrix_edges_are_reported_without_zero_fallback():
    metrics = compute_route_quality_metrics(
        travel_minutes={"a": {}},
        day_routes=[{
            "day_index": 0,
            "activity_ids": ["a", "b"],
            "window_min": 480,
        }],
        activities=[],
        meal_windows=MEAL_WINDOWS,
    )

    assert metrics["route_metric_day_count"] == 0
    assert metrics["route_order_detour_ratio"] is None
    assert metrics["route_metrics_by_day"][0]["measurement_status"] == "missing_matrix_edges"
