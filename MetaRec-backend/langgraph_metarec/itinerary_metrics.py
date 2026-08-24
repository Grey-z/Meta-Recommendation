"""Provider-free continuous quality metrics for solved itinerary routes."""
from __future__ import annotations

from itertools import permutations
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple


def _edge_minutes(
    travel_minutes: Mapping[str, Mapping[str, int]],
    start_id: str,
    end_id: str,
) -> Optional[int]:
    if start_id == end_id:
        return 0
    try:
        value = int(travel_minutes[start_id][end_id])
    except (KeyError, TypeError, ValueError):
        return None
    return max(0, value)


def _path_minutes(
    travel_minutes: Mapping[str, Mapping[str, int]],
    activity_ids: Sequence[str],
    *,
    start_id: Optional[str],
    end_id: Optional[str],
) -> Optional[int]:
    nodes = list(activity_ids)
    if start_id:
        nodes.insert(0, str(start_id))
    if end_id:
        nodes.append(str(end_id))
    total = 0
    for left, right in zip(nodes, nodes[1:]):
        edge = _edge_minutes(travel_minutes, left, right)
        if edge is None:
            return None
        total += edge
    return total


def _best_same_stops_minutes(
    travel_minutes: Mapping[str, Mapping[str, int]],
    activity_ids: Sequence[str],
    *,
    start_id: Optional[str],
    end_id: Optional[str],
) -> Optional[int]:
    if len(activity_ids) > 8:
        return None
    best: Optional[int] = None
    for order in permutations(activity_ids):
        total = _path_minutes(
            travel_minutes,
            order,
            start_id=start_id,
            end_id=end_id,
        )
        if total is not None and (best is None or total < best):
            best = total
    return best


def _meal_naturalness(
    activities: Sequence[Mapping[str, Any]],
    meal_windows: Mapping[str, Tuple[int, int]],
) -> Tuple[Optional[float], int]:
    scores: Dict[Tuple[int, str], float] = {}
    for activity in activities:
        try:
            start_min = int(activity.get("start_min"))
            end_min = int(activity.get("end_min"))
            day_index = int(activity.get("day_index") or 0)
        except (TypeError, ValueError):
            continue
        covered = {
            str(value).strip().lower()
            for value in (
                *(activity.get("satisfied_meals") or ()),
                *(activity.get("meal_coverage") or ()),
            )
            if str(value).strip()
        }
        midpoint = (start_min + end_min) / 2
        for meal in covered:
            window = meal_windows.get(meal)
            if not window or window[1] <= window[0]:
                continue
            center = (window[0] + window[1]) / 2
            half_width = (window[1] - window[0]) / 2
            preferred_half_width = half_width / 2
            distance = abs(midpoint - center)
            if distance <= preferred_half_width:
                score = 1.0
            else:
                score = max(
                    0.0,
                    1.0 - (distance - preferred_half_width) / max(1.0, half_width - preferred_half_width),
                )
            key = (day_index, meal)
            scores[key] = max(scores.get(key, 0.0), score)
    if not scores:
        return None, 0
    return round(sum(scores.values()) / len(scores), 6), len(scores)


def compute_route_quality_metrics(
    *,
    travel_minutes: Mapping[str, Mapping[str, int]],
    day_routes: Sequence[Mapping[str, Any]],
    activities: Sequence[Mapping[str, Any]],
    meal_windows: Mapping[str, Tuple[int, int]],
) -> Dict[str, Any]:
    """Measure route ordering and travel burden without changing solver policy.

    Each day route contains ``day_index``, ordered ``activity_ids``, ``window_min``,
    and optional fixed ``start_id``/``end_id``. The numerator and same-stop
    optimum always use the same estimated travel matrix.
    """
    per_day = []
    measured_travel = 0
    measured_optimum = 0
    measured_windows = 0
    measured_activities = 0
    measured_days = 0
    for route in day_routes:
        activity_ids = tuple(str(value) for value in route.get("activity_ids") or ())
        start_id = str(route["start_id"]) if route.get("start_id") else None
        end_id = str(route["end_id"]) if route.get("end_id") else None
        try:
            window_min = max(1, int(route.get("window_min") or 0))
            day_index = int(route.get("day_index") or 0)
        except (TypeError, ValueError):
            continue
        if not activity_ids:
            per_day.append({
                "day_index": day_index,
                "activity_count": 0,
                "estimated_route_travel_min": None,
                "best_same_stops_travel_min": None,
                "route_order_excess_min": None,
                "route_order_detour_ratio": None,
                "estimated_travel_window_share": None,
                "estimated_travel_minutes_per_activity": None,
                "measurement_status": "no_activities",
            })
            continue
        chosen = _path_minutes(
            travel_minutes,
            activity_ids,
            start_id=start_id,
            end_id=end_id,
        )
        optimum = _best_same_stops_minutes(
            travel_minutes,
            activity_ids,
            start_id=start_id,
            end_id=end_id,
        )
        measurable = chosen is not None and optimum is not None
        ratio = (
            round(chosen / optimum, 6)
            if measurable and optimum > 0 else (1.0 if measurable and chosen == 0 else None)
        )
        per_day.append({
            "day_index": day_index,
            "activity_count": len(activity_ids),
            "estimated_route_travel_min": chosen,
            "best_same_stops_travel_min": optimum,
            "route_order_excess_min": max(0, chosen - optimum) if measurable else None,
            "route_order_detour_ratio": ratio,
            "estimated_travel_window_share": round(chosen / window_min, 6) if chosen is not None else None,
            "estimated_travel_minutes_per_activity": (
                round(chosen / len(activity_ids), 6) if chosen is not None and activity_ids else None
            ),
            "measurement_status": "measured" if measurable else "missing_matrix_edges",
        })
        if measurable:
            measured_days += 1
            measured_travel += chosen
            measured_optimum += optimum
            measured_windows += window_min
            measured_activities += len(activity_ids)

    naturalness, meal_count = _meal_naturalness(activities, meal_windows)
    detour_ratio = (
        round(measured_travel / measured_optimum, 6)
        if measured_optimum > 0 else (1.0 if measured_days and measured_travel == 0 else None)
    )
    return {
        "estimated_route_travel_min": measured_travel if measured_days else None,
        "best_same_stops_travel_min": measured_optimum if measured_days else None,
        "route_order_excess_min": max(0, measured_travel - measured_optimum) if measured_days else None,
        "route_order_detour_ratio": detour_ratio,
        "estimated_travel_window_share": (
            round(measured_travel / measured_windows, 6) if measured_windows else None
        ),
        "estimated_travel_minutes_per_activity": (
            round(measured_travel / measured_activities, 6) if measured_activities else None
        ),
        "meal_time_naturalness": naturalness,
        "measured_meal_count": meal_count,
        "route_metric_day_count": measured_days,
        "route_metrics_by_day": per_day,
    }
