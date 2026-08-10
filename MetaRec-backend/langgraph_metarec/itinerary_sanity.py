"""Deterministic commonsense validation for solved itinerary routes."""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence

from langgraph_metarec.itinerary_contracts import (
    ItineraryPlanningRequest,
    PlanningCandidate,
    SanityReport,
)
from langgraph_metarec.itinerary_policy import (
    PACE_MAX_IDLE_GAP,
    PACE_MIN_PRIMARY_SHARE,
    role_allowed,
    style_policy,
)

REPAIRABLE_CODES = {
    # A named venue the pool never contained is repairable by searching for it:
    # the directive carries the unresolved names so the retry can look them up by
    # name. Without this the solver hard-failed and no repair was ever attempted.
    "must_visit_unavailable",
    "missing_primary_experience",
    "experience_share_low",
    "meal_overallocation",
    "domain_mismatch",
    "mixed_role_diversity_low",
    "lodging_as_activity",
    "zero_dwell_activity",
    "gated_child_without_parent",
    "role_unverified",
    "meal_preference_unmet",
    "excessive_idle_gap",
}

CONTINUOUS_ROUTE_METRICS = (
    "estimated_route_travel_min",
    "best_same_stops_travel_min",
    "route_order_excess_min",
    "route_order_detour_ratio",
    "estimated_travel_window_share",
    "estimated_travel_minutes_per_activity",
    "meal_time_naturalness",
    "measured_meal_count",
    "route_metric_day_count",
    "route_metrics_by_day",
)


def _activity_metrics(
    request: ItineraryPlanningRequest,
    activities: Iterable[Dict[str, Any]],
) -> Dict[str, Any]:
    style = str(request.soft_preferences.get("style") or "sightseeing")
    pace = str(request.soft_preferences.get("pace") or "balanced")
    policy = style_policy(style)
    primary_minutes = 0
    eligible_minutes = 0
    primary_roles = set()
    standalone_food = 0
    for activity in activities:
        role = str(activity.get("role") or (activity.get("item") or {}).get("role") or "unknown")
        duration = max(0, int((activity.get("duration") or {}).get("preferred") or activity.get("dwell_min") or 0))
        meal_only = role == "food" and policy.meals_only_food
        if not meal_only:
            eligible_minutes += duration
        if role in policy.primary_roles and not meal_only:
            primary_minutes += duration
            primary_roles.add(role)
        if role == "food" and not activity.get("parent_id"):
            standalone_food += 1
    share = primary_minutes / eligible_minutes if eligible_minutes else 0.0
    return {
        "style": style,
        "pace": pace,
        "primary_minutes": primary_minutes,
        "eligible_activity_minutes": eligible_minutes,
        "primary_experience_share": round(share, 4),
        "required_primary_share": PACE_MIN_PRIMARY_SHARE.get(pace, 0.50),
        "primary_role_families": sorted(primary_roles),
        "standalone_food_count": standalone_food,
    }


def validate_activity_policy(
    request: ItineraryPlanningRequest,
    activities: Sequence[Dict[str, Any]],
    candidates: Sequence[PlanningCandidate] = (),
) -> SanityReport:
    metrics = _activity_metrics(request, activities)
    policy = style_policy(metrics["style"])
    violations: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []
    seen = set()
    for activity in activities:
        item_id = str(activity.get("candidate_id") or (activity.get("item") or {}).get("id") or "")
        role = str(activity.get("role") or (activity.get("item") or {}).get("role") or "unknown")
        domain = str(activity.get("domain") or (activity.get("item") or {}).get("domain") or "")
        duration = int((activity.get("duration") or {}).get("preferred") or activity.get("dwell_min") or 0)
        if item_id and item_id in seen:
            violations.append({"code": "duplicate_poi", "candidate_id": item_id})
        seen.add(item_id)
        if duration <= 0:
            violations.append({"code": "zero_dwell_activity", "candidate_id": item_id})
        if role == "lodging":
            violations.append({"code": "lodging_as_activity", "candidate_id": item_id})
        if role == "unknown":
            warnings.append({"code": "role_unverified", "candidate_id": item_id, "domain": domain})
        elif not role_allowed(domain, role):
            violations.append({"code": "domain_mismatch", "candidate_id": item_id, "role": role})
        access = str((activity.get("item") or {}).get("access") or activity.get("access") or "independent")
        if access == "gated":
            violations.append({"code": "gated_child_without_parent", "candidate_id": item_id})
    if metrics["primary_minutes"] <= 0:
        warnings.append({"code": "missing_primary_experience", "style": metrics["style"]})
    elif metrics["primary_experience_share"] < metrics["required_primary_share"]:
        warnings.append({
            "code": "experience_share_low",
            "actual": metrics["primary_experience_share"],
            "required": metrics["required_primary_share"],
        })
    if policy.meals_only_food:
        obligations = len(request.hard_constraints.get("meal_obligations") or []) + len(
            request.soft_preferences.get("suggested_meals") or []
        )
        if metrics["standalone_food_count"] > obligations:
            warnings.append({"code": "meal_overallocation"})
    if policy.minimum_role_families > 1:
        available_roles = {
            candidate.role for candidate in candidates
            if candidate.role in policy.primary_roles and candidate.access != "gated"
        }
        window = request.days[0].end_min - request.days[0].start_min
        can_diversify = len(available_roles) >= policy.minimum_role_families and window >= 180
        if can_diversify and len(metrics["primary_role_families"]) < policy.minimum_role_families:
            warnings.append({"code": "mixed_role_diversity_low"})
    codes = tuple(sorted({item["code"] for item in (*violations, *warnings)}))
    return SanityReport(
        status="valid" if not violations else "invalid",
        violations=tuple(violations),
        metrics=metrics,
        repairable_codes=tuple(code for code in codes if code in REPAIRABLE_CODES),
        warnings=tuple(warnings),
    )


def validate_itinerary_block(
    block: Dict[str, Any],
    request: ItineraryPlanningRequest,
) -> SanityReport:
    activities = []
    for slot in block.get("slots") or []:
        chosen = slot.get("chosen") if isinstance(slot.get("chosen"), dict) else {}
        activities.append({
            "day_index": int(slot.get("day_index") or 0),
            "candidate_id": chosen.get("id"),
            "domain": slot.get("domain") or chosen.get("domain"),
            "role": chosen.get("role"),
            "duration": {"preferred": slot.get("dwell_min")},
            "item": chosen,
        })
    report = validate_activity_policy(request, activities)
    solver = block.get("solver") if isinstance(block.get("solver"), dict) else {}
    components = (
        solver.get("objective_components")
        if isinstance(solver.get("objective_components"), dict) else {}
    )
    continuous_metrics = {
        key: components[key]
        for key in CONTINUOUS_ROUTE_METRICS
        if key in components
    }
    if continuous_metrics:
        report = SanityReport(
            report.status,
            report.violations,
            {**report.metrics, **continuous_metrics},
            report.repairable_codes,
            report.warnings,
        )
    extra_violations: List[Dict[str, Any]] = []
    extra_warnings: List[Dict[str, Any]] = []
    constraints = {day.day_index: day for day in request.days}

    def minute(value: Any) -> Optional[int]:
        try:
            hour, minute_value = (int(part) for part in str(value).split(":", 1))
            return hour * 60 + minute_value
        except (TypeError, ValueError):
            return None

    for day in block.get("days") or []:
        day_index = int(day.get("day_index") or 0)
        constraint = constraints.get(day_index)
        previous_end = constraint.start_min if constraint else 0
        day_max_idle = 0
        legs_by_destination = {
            int(leg.get("to_index")): leg
            for leg in day.get("legs") or []
            if isinstance(leg, dict) and leg.get("to_index") is not None
        }
        for slot in day.get("slots") or []:
            start_min = minute(slot.get("time"))
            end_min = minute(slot.get("end_time"))
            if start_min is None or end_min is None or start_min < previous_end:
                extra_violations.append({"code": "chronology_conflict", "day_index": day_index})
                continue
            try:
                slot_index = int(slot.get("slot_index"))
            except (TypeError, ValueError):
                slot_index = -1
            try:
                travel_min = int((legs_by_destination.get(slot_index) or {}).get("duration_min") or 0)
            except (TypeError, ValueError):
                travel_min = 0
            day_max_idle = max(day_max_idle, max(0, start_min - previous_end - travel_min))
            if constraint and end_min > constraint.end_min:
                extra_violations.append({
                    "code": "time_window_exceeded",
                    "day_index": day_index,
                    "slot_index": slot.get("slot_index"),
                })
            previous_end = end_min
            availability = slot.get("availability") if isinstance(slot.get("availability"), dict) else {}
            if availability.get("known"):
                windows = [
                    window for window in availability.get("windows") or []
                    if isinstance(window, dict) and int(window.get("day_index") or 0) == day_index
                ]
                if not any(
                    int(window.get("start_min") or 0) <= start_min
                    and end_min <= int(window.get("end_min") or 0)
                    for window in windows
                ):
                    extra_violations.append({
                        "code": "known_closed",
                        "day_index": day_index,
                        "slot_index": slot.get("slot_index"),
                    })
        pace = str(request.soft_preferences.get("pace") or "balanced")
        allowed_idle = PACE_MAX_IDLE_GAP.get(pace, PACE_MAX_IDLE_GAP["balanced"])
        if day_max_idle > allowed_idle:
            extra_warnings.append({
                "code": "excessive_idle_gap",
                "day_index": day_index,
                "actual_min": day_max_idle,
                "allowed_min": allowed_idle,
            })
    for obligation in request.hard_constraints.get("meal_obligations") or []:
        if not isinstance(obligation, dict):
            continue
        day_index = int(obligation.get("day_index") or 0)
        meal = str(obligation.get("meal") or "")
        day = next(
            (value for value in block.get("days") or [] if int(value.get("day_index") or 0) == day_index),
            {},
        )
        covered = any(
            meal in set(slot.get("satisfied_meals") or ()) | set(slot.get("meal_coverage") or ())
            for slot in day.get("slots") or []
        )
        if meal and not covered:
            extra_violations.append({"code": "meal_obligation", "day_index": day_index, "meal": meal})
    for preference in request.soft_preferences.get("suggested_meals") or []:
        if not isinstance(preference, dict):
            continue
        try:
            day_index = int(preference.get("day_index") or 0)
        except (TypeError, ValueError):
            continue
        meal = str(preference.get("meal") or "")
        day = next(
            (value for value in block.get("days") or [] if int(value.get("day_index") or 0) == day_index),
            {},
        )
        covered = any(
            meal in set(slot.get("satisfied_meals") or ()) | set(slot.get("meal_coverage") or ())
            for slot in day.get("slots") or []
        )
        if meal and not covered:
            extra_warnings.append({
                "code": "meal_preference_unmet",
                "day_index": day_index,
                "meal": meal,
            })
    if len(request.days) > 1:
        if not block.get("lodging"):
            extra_violations.append({"code": "lodging_continuity_missing"})
        if request.lodging and request.lodging.nights != len(request.days) - 1:
            extra_violations.append({"code": "night_count_mismatch"})
    if extra_violations or extra_warnings:
        combined = tuple((*report.violations, *extra_violations))
        combined_warnings = tuple((*report.warnings, *extra_warnings))
        codes = tuple(sorted({
            str(item.get("code") or "") for item in (*combined, *combined_warnings)
        }))
        report = SanityReport(
            "invalid" if combined else "valid",
            combined,
            report.metrics,
            tuple(code for code in codes if code in REPAIRABLE_CODES),
            combined_warnings,
        )
    anchors = block.get("anchors") if isinstance(block.get("anchors"), dict) else {}
    legs = block.get("legs") or []
    continuity = True
    if len(request.days) > 1:
        for day in block.get("days") or []:
            day_slots = day.get("slots") or []
            day_legs = day.get("legs") or []
            if day_slots:
                continuity = continuity and bool(
                    day_legs
                    and day_legs[0].get("from_anchor") == "lodging"
                    and day_legs[-1].get("to_anchor") == "lodging"
                )
    else:
        if anchors.get("start") and activities:
            continuity = continuity and bool(legs and legs[0].get("from_anchor") == "start")
        if anchors.get("end") and activities:
            continuity = continuity and bool(legs and legs[-1].get("to_anchor") == "end")
    if not continuity:
        violations = (*report.violations, {"code": "anchor_continuity_broken"})
        report = SanityReport(
            "invalid",
            violations,
            {**report.metrics, "anchor_continuity": False},
            report.repairable_codes,
            report.warnings,
        )
    else:
        report = SanityReport(
            report.status,
            report.violations,
            {**report.metrics, "anchor_continuity": True},
            report.repairable_codes,
            report.warnings,
        )
    return report


def apply_sanity_report(block: Dict[str, Any], report: SanityReport) -> None:
    block["sanity"] = report.to_dict()
    block.setdefault("problem_summary", {}).update(report.metrics)
    if report.warnings:
        validation = block.setdefault("validation", {})
        existing_warnings = list(validation.get("warnings") or [])
        known_warnings = {
            (str(item.get("code")), item.get("day_index"), item.get("candidate_id"))
            for item in existing_warnings if isinstance(item, dict)
        }
        existing_warnings.extend(
            item for item in report.warnings
            if (str(item.get("code")), item.get("day_index"), item.get("candidate_id"))
            not in known_warnings
        )
        validation["warnings"] = existing_warnings
    if report.status == "valid":
        return
    validation = block.setdefault("validation", {})
    existing = list(validation.get("violations") or [])
    known = {str(item.get("code")) for item in existing if isinstance(item, dict)}
    existing.extend(item for item in report.violations if item.get("code") not in known)
    validation["violations"] = existing
    validation["status"] = "partial" if block.get("slots") else "invalid"
    block["planning_status"] = "needs_refinement"
