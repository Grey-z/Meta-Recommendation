from dataclasses import replace

import pytest

from langgraph_metarec.itinerary_contracts import (
    BudgetConstraint,
    AnchorConstraint,
    CostEstimate,
    DayConstraint,
    DurationEstimate,
    ItineraryPlanningRequest,
    LodgingRequirement,
    LocationConstraint,
    PlanningCandidate,
    SolverResult,
)
from langgraph_metarec.itinerary_runtime import (
    apply_transport_cost,
    build_itinerary_block,
    exceeds_time_window,
    finalize_dynamic_metadata,
    fmt_hhmm,
    parse_hhmm,
    resolve_itinerary_legs,
)

pytestmark = pytest.mark.backend_unit


def _request():
    return ItineraryPlanningRequest(
        LocationConstraint("Singapore", timezone="Asia/Singapore"),
        (DayConstraint(0, "2026-08-03", 540, 720),),
        BudgetConstraint("limited", 50, "SGD"),
    )


def _candidate(identifier, lat):
    return PlanningCandidate(
        identifier, "attraction", identifier, lat, 103.8,
        DurationEstimate(30, 30, 30, "provider", 1),
        CostEstimate(5, 5, "SGD", ("admission",), "provider", 1),
        item={"id": identifier, "title": identifier, "domain": "attraction", "lat": lat, "lng": 103.8},
    )


def test_fmt_hhmm_carries_past_midnight_instead_of_wrapping():
    # A wrapped "00:30" round-tripped to 30 minutes and hid every past-midnight
    # time_window_exceeded violation from the checks and the ETA repair loop.
    assert fmt_hhmm(1470) == "24:30"
    assert parse_hhmm(fmt_hhmm(1470)) == 1470
    assert fmt_hhmm(1440) == "24:00"
    assert parse_hhmm(fmt_hhmm(1440)) == 1440
    assert fmt_hhmm(-5) == "00:00"


def test_past_midnight_end_time_is_detected_as_window_violation():
    candidate = _candidate("a", 1.30)
    result = SolverResult(
        "feasible",
        ({"candidate_id": "a", "start_min": 690, "end_min": 720, "duration": {}, "cost": {}, "meal_coverage": []},),
        {"min": 5, "max": 5, "currency": "SGD", "budget_limit": 50, "budget_status": "feasible"},
    )
    request = _request()
    block = build_itinerary_block(request, result, (candidate,))
    block["totals"]["end_time"] = fmt_hhmm(1470)
    block["days"][0]["totals"]["end_time"] = fmt_hhmm(1470)
    assert exceeds_time_window(block, request) is True
    finalize_dynamic_metadata(block, request, result)
    codes = [item["code"] for item in block["validation"]["violations"]]
    assert "time_window_exceeded" in codes
    assert block["planning_status"] == "needs_refinement"


def test_public_block_has_no_invented_first_or_last_anchor_leg():
    candidates = (_candidate("a", 1.30), _candidate("b", 1.31))
    result = SolverResult(
        "feasible",
        (
            {"candidate_id": "a", "start_min": 540, "end_min": 570, "duration": {}, "cost": {}, "meal_coverage": []},
            {"candidate_id": "b", "start_min": 600, "end_min": 630, "duration": {}, "cost": {}, "meal_coverage": []},
        ),
        {"min": 10, "max": 10, "currency": "SGD", "budget_limit": 50, "budget_status": "feasible"},
    )
    block = build_itinerary_block(_request(), result, candidates)
    assert len(block["legs"]) == 1
    assert block["legs"][0]["from_id"] == "a" and block["legs"][0]["to_id"] == "b"


def test_transport_cost_and_time_violation_restore_dynamic_projection():
    candidate = _candidate("a", 1.30)
    result = SolverResult(
        "feasible",
        ({"candidate_id": "a", "start_min": 690, "end_min": 720, "duration": {}, "cost": {}, "meal_coverage": []},),
        {"min": 5, "max": 5, "currency": "SGD", "budget_limit": 50, "budget_status": "feasible"},
    )
    block = build_itinerary_block(_request(), result, (candidate,))
    block["totals"]["end_time"] = "12:30"
    block["days"][0]["totals"]["end_time"] = "12:30"
    block["legs"] = [{"mode": "pt", "fare": "1.20 SGD"}, {"mode": "drive"}]
    finalize_dynamic_metadata(block, _request(), result)
    apply_transport_cost(block)
    assert block["validation"]["violations"][0]["code"] == "time_window_exceeded"
    assert block["cost_summary"]["min"] == 6.2
    assert block["cost_summary"]["max"] is None
    assert block["planning_status"] == "needs_refinement"


def test_round_trip_anchor_is_separate_and_adds_outbound_and_return_legs():
    anchor = AnchorConstraint(
        "Beach Hotel", resolved_name="Beach Hotel", address="1 Coast Road",
        latitude=1.25, longitude=103.82, provider_id="hotel-1", source="provider",
    )
    request = replace(_request(), anchors={"start": anchor, "end": anchor})
    candidate = _candidate("a", 1.30)
    result = SolverResult(
        "feasible",
        ({"candidate_id": "a", "start_min": 555, "end_min": 585, "duration": {}, "cost": {}, "meal_coverage": []},),
        {"min": 5, "max": 5, "currency": "SGD", "budget_limit": 50, "budget_status": "feasible"},
    )
    block = build_itinerary_block(request, result, (candidate,))
    assert block["anchors"]["shared"] is True
    assert block["anchors"]["start"]["title"] == "Beach Hotel"
    assert [leg.get("from_anchor") or leg.get("to_anchor") for leg in block["legs"]] == ["start", "end"]
    assert len(block["slots"]) == 1
    assert block["totals"]["total_travel_min"] > 0


def test_multi_day_block_projects_daily_routes_without_overnight_leg():
    request = ItineraryPlanningRequest(
        LocationConstraint("Singapore", timezone="Asia/Singapore"),
        (DayConstraint(0, "2026-08-03", 540, 900), DayConstraint(1, "2026-08-04", 540, 900)),
        BudgetConstraint("limited", 200, "SGD", scope="trip_total", include_lodging=True),
        lodging=LodgingRequirement("recommend", "2026-08-03", "2026-08-05", 2, 1, 1),
    )
    candidates = (_candidate("a", 1.30), _candidate("b", 1.31))
    result = SolverResult(
        "feasible",
        (
            {"day_index": 0, "candidate_id": "a", "start_min": 570, "end_min": 600, "duration": {}, "cost": {}, "meal_coverage": []},
            {"day_index": 1, "candidate_id": "b", "start_min": 570, "end_min": 600, "duration": {}, "cost": {}, "meal_coverage": []},
        ),
        {"min": 60, "max": 60, "currency": "SGD", "budget_limit": 200, "budget_status": "feasible"},
        diagnostics={"daily_wait_min": [0, 0]},
        lodging={
            "candidate_id": "hotel", "title": "Shared Hotel", "latitude": 1.29,
            "longitude": 103.8, "address": "1 Hotel Rd", "source": "provider",
        },
    )
    block = build_itinerary_block(request, result, candidates)

    assert [day["day_index"] for day in block["days"]] == [0, 1]
    assert [[slot["slot_index"] for slot in day["slots"]] for day in block["days"]] == [[0], [1]]
    assert all(
        [leg.get("from_anchor") or leg.get("to_anchor") for leg in day["legs"]]
        == ["lodging", "lodging"]
        for day in block["days"]
    )
    assert len(block["legs"]) == 4
    assert not any(leg.get("from_id") == "a" and leg.get("to_id") == "b" for leg in block["legs"])
    assert block["totals"]["day_count"] == 2


@pytest.mark.asyncio
async def test_real_eta_is_resolved_and_propagated_independently_per_day():
    request = ItineraryPlanningRequest(
        LocationConstraint("Singapore", timezone="Asia/Singapore"),
        (DayConstraint(0, "2026-08-03", 540, 900), DayConstraint(1, "2026-08-04", 540, 900)),
        BudgetConstraint("unlimited"),
        lodging=LodgingRequirement("recommend", "2026-08-03", "2026-08-05", 2, 1, 1),
    )
    candidates = (_candidate("a", 1.30), _candidate("b", 1.31))
    result = SolverResult(
        "feasible",
        (
            {"day_index": 0, "candidate_id": "a", "start_min": 570, "end_min": 600, "duration": {}, "cost": {}, "meal_coverage": []},
            {"day_index": 1, "candidate_id": "b", "start_min": 570, "end_min": 600, "duration": {}, "cost": {}, "meal_coverage": []},
        ),
        {"min": 0, "max": 0, "currency": None, "budget_status": "unlimited"},
        diagnostics={"daily_wait_min": [10, 10]},
        lodging={
            "candidate_id": "hotel", "title": "Shared Hotel", "latitude": 1.29,
            "longitude": 103.8, "address": "1 Hotel Rd", "source": "provider",
        },
    )
    block = build_itinerary_block(request, result, candidates)
    calls = []

    def resolver(_from_geo, _to_geo, *, depart_hhmm, service_date, timezone):
        calls.append((depart_hhmm, service_date, timezone))
        return {"mode": "pt", "duration_min": 20, "distance_km": 1, "source": "fixture"}

    resolved = await resolve_itinerary_legs(block, resolver)

    assert [day["totals"]["end_time"] for day in resolved["days"]] == ["10:20", "10:20"]
    assert [day["slots"][0]["time"] for day in resolved["days"]] == ["09:30", "09:30"]
    assert [call[1] for call in calls] == ["2026-08-03", "2026-08-03", "2026-08-04", "2026-08-04"]
    assert len(resolved["legs"]) == 4


def test_legacy_adapter_parses_the_past_midnight_times_it_formats():
    # The legacy refine adapter formats "24:30"-style times (same convention as
    # fmt_hhmm above) but its parser rejected hour >= 24: a slot arrival came
    # back None and _pt_departure silently fell back to a 10:00 departure.
    from langgraph_metarec.legacy_adapters.itinerary_payload import (
        _format_hhmm,
        _parse_hhmm,
    )

    assert _format_hhmm(1470) == "24:30"
    assert _parse_hhmm(_format_hhmm(1470)) == 1470
    assert _parse_hhmm(_format_hhmm(1440)) == 1440
    assert _parse_hhmm("10:30") == 630
    assert _parse_hhmm("10:75") is None
    assert _parse_hhmm("-1:30") is None
    assert _parse_hhmm("junk") is None
