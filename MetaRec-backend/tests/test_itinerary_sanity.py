from dataclasses import replace

import pytest

from langgraph_metarec.itinerary_contracts import (
    BudgetConstraint,
    CostEstimate,
    DayConstraint,
    DurationEstimate,
    ItineraryPlanningRequest,
    LocationConstraint,
    PlanningCandidate,
)
from langgraph_metarec.itinerary_sanity import (
    apply_sanity_report,
    validate_activity_policy,
    validate_itinerary_block,
)

pytestmark = pytest.mark.backend_unit


def _request(style, pace="balanced", meals=()):
    return ItineraryPlanningRequest(
        LocationConstraint("Singapore", timezone="Asia/Singapore"),
        (DayConstraint(0, "2026-08-03", 540, 1080),),
        BudgetConstraint("unlimited"),
        hard_constraints={"meal_obligations": list(meals)},
        soft_preferences={"style": style, "pace": pace},
    )


def _candidate(identifier, role, duration=60, *, domain="attraction", compound=False):
    return PlanningCandidate(
        identifier, domain, identifier, 1.3, 103.8,
        DurationEstimate(duration, duration, duration, "provider", 1),
        CostEstimate(0, 0, "SGD"),
        role=role, role_source="provider", is_compound=compound,
        item={"id": identifier, "domain": domain, "role": role},
    )


def _activity(candidate):
    return {
        "candidate_id": candidate.id,
        "domain": candidate.domain,
        "role": candidate.role,
        "duration": {"preferred": candidate.duration.preferred},
        "item": candidate.item,
    }


@pytest.mark.parametrize(
    ("style", "candidates"),
    [
        ("sightseeing", [_candidate("museum", "experience")]),
        ("food_tour", [_candidate("cafe-a", "food", domain="restaurant"), _candidate("cafe-b", "food", domain="restaurant")]),
        ("shopping", [_candidate("market", "shopping")]),
        ("theme_park", [_candidate("park", "experience", 480, compound=True)]),
        ("mixed", [_candidate("museum", "experience"), _candidate("market", "shopping")]),
    ],
)
def test_all_style_policies_accept_their_primary_experiences(style, candidates):
    report = validate_activity_policy(_request(style), [_activity(item) for item in candidates], candidates)
    assert report.status == "valid"


@pytest.mark.parametrize(
    ("pace", "warns"),
    [("relaxed", False), ("balanced", True), ("packed", True)],
)
def test_pace_specific_primary_share_thresholds_are_quality_warnings(pace, warns):
    primary = _candidate("museum", "experience", 40)
    optional = _candidate("market", "shopping", 60)
    report = validate_activity_policy(
        _request("sightseeing", pace),
        [_activity(primary), _activity(optional)],
        [primary, optional],
    )
    assert report.status == "valid"
    assert ("experience_share_low" in {item["code"] for item in report.warnings}) is warns
    assert report.metrics["required_primary_share"] == {"relaxed": .4, "balanced": .5, "packed": .6}[pace]


def test_invalid_activities_are_hard_but_extra_meals_are_a_warning():
    lodging = _candidate("hotel", "lodging", 60, domain="hotel")
    zero = _candidate("photo", "experience", 0)
    meal_a = _candidate("meal-a", "food", domain="restaurant")
    meal_b = _candidate("meal-b", "food", domain="restaurant")
    report = validate_activity_policy(
        _request("sightseeing", meals=("lunch",)),
        [_activity(item) for item in (lodging, zero, meal_a, meal_b)],
        [lodging, zero, meal_a, meal_b],
    )
    codes = {item["code"] for item in report.violations}
    warning_codes = {item["code"] for item in report.warnings}
    assert {"lodging_as_activity", "zero_dwell_activity"} <= codes
    assert "meal_overallocation" in warning_codes


def test_unknown_role_is_warning_until_provider_evidence_can_classify_it():
    unknown = _candidate("unclear", "unknown")
    report = validate_activity_policy(
        _request("sightseeing"),
        [_activity(unknown)],
        [unknown],
    )

    assert report.status == "valid"
    assert report.violations == ()
    assert {item["code"] for item in report.warnings} == {
        "role_unverified", "missing_primary_experience",
    }


def test_warning_only_report_remains_deliverable_after_projection():
    meal = _candidate("meal", "food", domain="restaurant")
    report = validate_activity_policy(
        _request("sightseeing", meals=("lunch",)),
        [_activity(meal)],
        [meal],
    )
    block = {"planning_status": "feasible", "slots": [{"chosen": meal.item}]}

    apply_sanity_report(block, report)

    assert report.status == "valid"
    assert block["planning_status"] == "feasible"
    assert "suppress_normal_presentation" not in block
    assert {item["code"] for item in block["validation"]["warnings"]} == {
        "missing_primary_experience",
    }


def test_excessive_idle_gap_is_soft_and_pace_specific():
    request = _request("sightseeing", pace="balanced")
    first = _candidate("first", "experience")
    second = _candidate("second", "experience")

    def slot(index, candidate, start, end):
        return {
            "slot_index": index, "day_index": 0, "domain": "attraction",
            "time": start, "end_time": end, "dwell_min": 60,
            "chosen": {**candidate.item, "id": candidate.id, "role": candidate.role},
        }

    slots = [slot(0, first, "09:00", "10:00"), slot(1, second, "16:00", "17:00")]
    block = {
        "slots": slots,
        "days": [{"day_index": 0, "slots": slots, "legs": [
            {"to_index": 0, "duration_min": 0},
            {"to_index": 1, "duration_min": 15},
        ]}],
        "legs": [],
    }

    report = validate_itinerary_block(block, request)

    assert report.status == "valid"
    warning = next(item for item in report.warnings if item["code"] == "excessive_idle_gap")
    assert warning == {
        "code": "excessive_idle_gap", "day_index": 0,
        "actual_min": 345, "allowed_min": 90,
    }


def test_one_misordered_slot_reports_one_chronology_conflict_not_a_cascade():
    request = _request("sightseeing")
    stops = [_candidate(name, "experience") for name in ("first", "second", "third")]

    def slot(index, candidate, start, end):
        return {
            "slot_index": index, "day_index": 0, "domain": "attraction",
            "time": start, "end_time": end, "dwell_min": 30,
            "chosen": {**candidate.item, "id": candidate.id, "role": candidate.role},
        }

    # Second slot starts before the first ends (violation); the third is fine
    # and must not be dragged into a cascade by a stale chronology cursor.
    slots = [
        slot(0, stops[0], "09:00", "10:00"),
        slot(1, stops[1], "08:00", "08:30"),
        slot(2, stops[2], "10:30", "11:00"),
    ]
    block = {
        "slots": slots,
        "days": [{"day_index": 0, "slots": slots, "legs": []}],
        "legs": [],
    }

    report = validate_itinerary_block(block, request)

    conflicts = [item for item in report.violations if item["code"] == "chronology_conflict"]
    assert len(conflicts) == 1


def test_continuous_solver_metrics_are_preserved_in_sanity_report():
    request = _request("sightseeing")
    museum = _candidate("museum", "experience")
    slot = {
        "slot_index": 0,
        "day_index": 0,
        "domain": "attraction",
        "time": "09:00",
        "end_time": "10:00",
        "dwell_min": 60,
        "chosen": {**museum.item, "id": museum.id, "role": museum.role},
    }
    block = {
        "slots": [slot],
        "days": [{"day_index": 0, "slots": [slot], "legs": []}],
        "legs": [],
        "solver": {"objective_components": {
            "route_order_detour_ratio": 1.1,
            "estimated_travel_window_share": 0.15,
            "route_metrics_by_day": [{"day_index": 0}],
        }},
    }

    report = validate_itinerary_block(block, request)

    assert report.metrics["route_order_detour_ratio"] == 1.1
    assert report.metrics["estimated_travel_window_share"] == 0.15
    assert report.metrics["route_metrics_by_day"] == [{"day_index": 0}]
