"""Deterministic, provider-free itinerary quality metrics for CI and metadata."""
from __future__ import annotations

from typing import Any, Dict, Iterable, Optional


def _minute(value: Any) -> Optional[int]:
    try:
        hour, minute = (int(part) for part in str(value).split(":", 1))
    except (TypeError, ValueError, AttributeError):
        return None
    return hour * 60 + minute if 0 <= hour < 24 and 0 <= minute < 60 else None


def evaluate_itinerary(block: Dict[str, Any], previous: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    slots = [slot for slot in block.get("slots") or [] if isinstance(slot, dict)]
    chosen = [slot for slot in slots if isinstance(slot.get("chosen"), dict)]
    validation = block.get("validation") if isinstance(block.get("validation"), dict) else {}
    violations = validation.get("violations") if isinstance(validation.get("violations"), list) else []
    warnings = validation.get("warnings") if isinstance(validation.get("warnings"), list) else []
    codes = [str(item.get("code")) for item in violations if isinstance(item, dict)]
    warning_codes = [str(item.get("code")) for item in warnings if isinstance(item, dict)]
    ids = [str(slot["chosen"].get("id")) for slot in chosen if slot["chosen"].get("id")]
    duplicate_count = max(0, len(ids) - len(set(ids)))
    schedule_codes = {"meal_window", "day_too_long", "known_closed", "time_window_exceeded"}
    schedule_conflicts = sum(code in schedule_codes for code in codes)
    checks = validation.get("checks") if isinstance(validation.get("checks"), dict) else {}
    cost_summary = block.get("cost_summary") if isinstance(block.get("cost_summary"), dict) else {}
    budget_limit = cost_summary.get("budget_limit", checks.get("budget_limit_sgd"))
    spend_max = cost_summary.get("max")
    if cost_summary:
        spend = float(spend_max or 0)
        budget_deviation = max(0.0, spend - float(budget_limit)) if budget_limit is not None and spend_max is not None else None
    else:
        spend = float(checks.get("estimated_food_spend_sgd") or 0)
        budget_deviation = max(0.0, spend - float(budget_limit)) if budget_limit is not None else None
    ratings = [float(slot["chosen"].get("rating")) / 5 for slot in chosen if slot["chosen"].get("rating") is not None]
    legs = [leg for leg in block.get("legs") or [] if isinstance(leg, dict)]
    fallback_count = sum(leg.get("source") == "estimate" for leg in legs)
    totals = block.get("totals") if isinstance(block.get("totals"), dict) else {}
    travel_min = int(totals.get("total_travel_min") or 0)
    activity_min = int(totals.get("total_activity_min") or 0)
    uncertainties = block.get("uncertainties") if isinstance(block.get("uncertainties"), list) else []
    solver = block.get("solver") if isinstance(block.get("solver"), dict) else {}
    sanity = block.get("sanity") if isinstance(block.get("sanity"), dict) else {}
    sanity_metrics = sanity.get("metrics") if isinstance(sanity.get("metrics"), dict) else {}
    candidate_diagnostics = solver.get("candidate_diagnostics") if isinstance(solver.get("candidate_diagnostics"), dict) else {}
    rejection_counts = candidate_diagnostics.get("rejection_counts") if isinstance(candidate_diagnostics.get("rejection_counts"), dict) else {}
    semantic_rejections = sum(
        int(count or 0) for code, count in rejection_counts.items()
        if str(code).startswith(("domain_mismatch", "unknown_role", "unknown_access", "unknown_parent", "gated_child"))
    )
    lodging_count = sum(str(slot["chosen"].get("role") or "") == "lodging" for slot in chosen)
    zero_dwell_count = sum(
        slot.get("dwell_min") is not None and int(slot.get("dwell_min") or 0) <= 0
        for slot in chosen
    )
    repair = block.get("repair") if isinstance(block.get("repair"), dict) else {}
    retrieval = block.get("retrieval") if isinstance(block.get("retrieval"), dict) else {}
    retrieval_rounds = [row for row in retrieval.get("rounds") or [] if isinstance(row, dict)]
    retrieval_rows = [
        item
        for round_row in retrieval_rounds
        for item in round_row.get("retrievals") or []
        if isinstance(item, dict)
    ]
    retrieval_cache_hits = sum(
        row.get("cache_status") in {"hit", "negative_hit"} for row in retrieval_rows
    )
    eta_provider_calls = sum(
        leg.get("source") != "estimate" and leg.get("cache") != "hit" for leg in legs
    )
    retrieval_provider_calls = int(retrieval.get("provider_calls") or 0)
    days = [row for row in block.get("days") or [] if isinstance(row, dict)]
    day_utilization = []
    idle_gap_min = 0
    for day in days:
        start = _minute(day.get("start_time"))
        end = _minute(day.get("end_time_constraint"))
        if start is None or end is None or end <= start:
            continue
        day_totals = day.get("totals") if isinstance(day.get("totals"), dict) else {}
        allocated = sum(
            int(day_totals.get(key) or 0)
            for key in ("total_activity_min", "total_travel_min", "total_wait_min")
        )
        window = end - start
        day_utilization.append(round(min(1.0, allocated / window), 3))
        idle_gap_min += max(0, window - allocated)
    reported_budget_status = cost_summary.get("budget_status")
    expected_budget_status = None
    if budget_limit is not None and cost_summary:
        spend_min = cost_summary.get("min")
        if spend_min is not None and float(spend_min) > float(budget_limit):
            expected_budget_status = "infeasible"
        elif spend_max is not None and float(spend_max) <= float(budget_limit):
            expected_budget_status = "feasible"
        else:
            expected_budget_status = "indeterminate"
    budget_status_accuracy = (
        float(reported_budget_status == expected_budget_status)
        if reported_budget_status and expected_budget_status else None
    )
    anchors = block.get("anchors") if isinstance(block.get("anchors"), dict) else {}
    if "anchor_continuity" in sanity_metrics:
        anchor_continuity = bool(sanity_metrics["anchor_continuity"])
    else:
        has_lodging = isinstance(block.get("lodging"), dict) or isinstance(anchors.get("lodging"), dict)
        anchor_continuity = True
        if has_lodging:
            anchor_continuity = bool(days) and all(
                bool(day.get("legs"))
                and day["legs"][0].get("from_anchor") == "lodging"
                and day["legs"][-1].get("to_anchor") == "lodging"
                for day in days
            )
        elif isinstance(anchors.get("start"), dict) and days:
            anchor_continuity = bool(days[0].get("legs")) and days[0]["legs"][0].get("from_anchor") == "start"
        if anchor_continuity and isinstance(anchors.get("end"), dict) and days:
            anchor_continuity = bool(days[-1].get("legs")) and days[-1]["legs"][-1].get("to_anchor") == "end"
    metrics: Dict[str, Any] = {
        "delivery_rate": round(len(chosen) / len(slots), 3) if slots else 0.0,
        "feasibility_rate": 1.0 if not violations and block.get("planning_status") != "needs_refinement" else 0.0,
        "hard_constraint_pass_rate": 1.0 if not violations else 0.0,
        "commonsense_pass_rate": 1.0 if not any(code in schedule_codes | {"duplicate_poi", "missing_required_stop"} for code in codes) else 0.0,
        "duplicate_rate": round(duplicate_count / max(1, len(chosen)), 3),
        "schedule_conflict_rate": round(schedule_conflicts / max(1, len(slots)), 3),
        "route_travel_min": travel_min,
        "travel_ratio": round(travel_min / max(1, travel_min + activity_min), 3),
        "budget_deviation": round(budget_deviation, 2) if budget_deviation is not None else None,
        "budget_currency": cost_summary.get("currency") or ("SGD" if budget_limit is not None else None),
        "budget_status": cost_summary.get("budget_status"),
        "uncertainty_rate": round(len(uncertainties) / max(1, len(chosen)), 3),
        "planning_status": block.get("planning_status"),
        "preference_match": round(sum(ratings) / len(ratings), 3) if ratings else None,
        "provider_call_count": eta_provider_calls + retrieval_provider_calls,
        "eta_provider_call_count": eta_provider_calls,
        "retrieval_provider_call_count": retrieval_provider_calls,
        "cache_hit_count": sum(leg.get("cache") == "hit" for leg in legs) + retrieval_cache_hits,
        "retrieval_round_count": len(retrieval_rounds),
        "fallback_rate": round(fallback_count / len(legs), 3) if legs else 0.0,
        "candidate_count": int(solver.get("candidate_count") or len(chosen)),
        "expanded_states": int(solver.get("expanded_states") or 0),
        "repair_count": int(solver.get("repair_count") or 0),
        "anchor_continuity": anchor_continuity,
        "hotel_continuity": anchor_continuity,
        "per_day_utilization": day_utilization,
        "mean_day_utilization": round(sum(day_utilization) / len(day_utilization), 3) if day_utilization else None,
        "idle_gap_min": idle_gap_min,
        "budget_status_accuracy": budget_status_accuracy,
        "primary_experience_share": sanity_metrics.get("primary_experience_share"),
        "semantic_rejection_rate": round(
            semantic_rejections / max(1, semantic_rejections + int(solver.get("candidate_count") or len(chosen))), 3
        ),
        "lodging_activity_count": lodging_count,
        "zero_dwell_activity_count": zero_dwell_count,
        "soft_warning_count": len(warning_codes),
        "meal_overallocation_count": warning_codes.count("meal_overallocation"),
        "parent_access_violation_count": codes.count("gated_child_without_parent"),
        "automatic_repair_attempted": bool(repair.get("attempt_count")),
        "automatic_repair_success": repair.get("success"),
        "automatic_repair_added_provider_calls": int(repair.get("added_provider_calls") or 0),
        "automatic_repair_latency_ms": repair.get("latency_ms"),
        "solver_runtime_ms": solver.get("runtime_ms"),
        "runtime_ms": block.get("runtime_ms"),
    }
    if previous is not None:
        prior = {
            int(slot.get("slot_index", -1)): str((slot.get("chosen") or {}).get("id") or "")
            for slot in previous.get("slots") or [] if isinstance(slot, dict)
        }
        unchanged = sum(prior.get(int(slot.get("slot_index", -1))) == str((slot.get("chosen") or {}).get("id") or "") for slot in slots)
        metrics["refinement_stability"] = round(unchanged / max(1, len(slots)), 3)
    return metrics


def summarize_itinerary_evaluations(blocks: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate deterministic offline metrics without provider or LLM calls."""
    rows = [evaluate_itinerary(block) for block in blocks]

    def mean(key: str) -> Optional[float]:
        values = [float(row[key]) for row in rows if row.get(key) is not None]
        return round(sum(values) / len(values), 3) if values else None

    return {
        "case_count": len(rows),
        "delivery_rate": mean("delivery_rate"),
        "feasibility_rate": mean("feasibility_rate"),
        "uncertainty_rate": mean("uncertainty_rate"),
        "mean_day_utilization": mean("mean_day_utilization"),
        "hotel_continuity_rate": mean("hotel_continuity"),
        "idle_gap_min": mean("idle_gap_min"),
        "duplicate_rate": mean("duplicate_rate"),
        "travel_ratio": mean("travel_ratio"),
        "budget_status_accuracy": mean("budget_status_accuracy"),
        "provider_call_count": mean("provider_call_count"),
        "cache_hit_count": mean("cache_hit_count"),
        "retrieval_round_count": mean("retrieval_round_count"),
        "expanded_states": mean("expanded_states"),
        "repair_count": mean("repair_count"),
        "runtime_ms": mean("runtime_ms"),
    }
