import pytest

from langgraph_metarec.itinerary_contracts import (
    BudgetConstraint,
    DayConstraint,
    ItineraryPlanningRequest,
    LocationConstraint,
    planning_request_from_preferences,
    validate_planning_request,
)


@pytest.mark.backend_unit
def test_planning_request_is_serializable_and_valid():
    request = ItineraryPlanningRequest(
        location=LocationConstraint(query="Sentosa", timezone="Asia/Singapore"),
        days=(DayConstraint(day_index=0, date="2026-08-01", start_min=540, end_min=1080),),
        budget=BudgetConstraint(mode="limited", amount=150, currency="SGD"),
        explicit_fields=("location", "date", "start_time", "end_time", "budget"),
    )
    assert validate_planning_request(request) == []
    assert request.to_dict()["days"][0]["start_min"] == 540
    assert request.to_dict()["schema_version"] == "itinerary-ir/v2"


@pytest.mark.backend_unit
def test_planning_request_accepts_contiguous_multi_day_but_requires_occupancy_and_budget():
    request = ItineraryPlanningRequest(
        location=LocationConstraint(query="Singapore"),
        days=(
            DayConstraint(day_index=0, date="2026-08-01", start_min=540, end_min=1080),
            DayConstraint(day_index=1, date="2026-08-02", start_min=540, end_min=1080),
        ),
        budget=BudgetConstraint(mode="limited"),
    )
    codes = {item["code"] for item in validate_planning_request(request)}
    assert "unsupported_horizon" not in codes
    assert {
        "missing_budget_amount", "missing_budget_currency", "missing_travelers", "missing_rooms",
    } <= codes


@pytest.mark.backend_unit
def test_preferences_build_single_day_request_with_soft_meal_suggestions():
    request, errors = planning_request_from_preferences({
        "location": "Sentosa",
        "date": "2026-08-01",
        "start_time": "09:00",
        "end_time": "20:00",
        "timezone": "Asia/Singapore",
        "budget_mode": "unlimited",
        "pace": "balanced",
        "_itinerary_field_sources": {"location": "user"},
    })
    assert errors == [] and request is not None
    assert request.hard_constraints["meal_obligations"] == []
    assert request.soft_preferences["suggested_meals"] == [
        {"day_index": 0, "meal": "lunch"},
        {"day_index": 0, "meal": "dinner"},
    ]
    assert request.days[0].end_min == 1200


@pytest.mark.backend_unit
def test_only_explicit_meals_become_hard_obligations():
    request, errors = planning_request_from_preferences({
        "location": "Sentosa",
        "date": "2026-08-01",
        "start_time": "09:00",
        "end_time": "20:00",
        "timezone": "Asia/Singapore",
        "budget_mode": "unlimited",
        "meal_obligations": ["lunch"],
        "_itinerary_field_sources": {"meal_obligations": "user"},
    })

    assert errors == [] and request is not None
    assert request.hard_constraints["meal_obligations"] == [
        {"day_index": 0, "meal": "lunch"},
    ]
    assert request.soft_preferences["suggested_meals"] == [
        {"day_index": 0, "meal": "dinner"},
    ]


@pytest.mark.backend_unit
def test_absent_date_and_window_default_to_tomorrow_nine_to_ten():
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    request, errors = planning_request_from_preferences({
        "location": "Sentosa",
        "timezone": "Asia/Singapore",
        "budget_mode": "unlimited",
        "style": "sightseeing",
        "pace": "balanced",
    })
    assert errors == [] and request is not None
    tomorrow = (datetime.now(ZoneInfo("Asia/Singapore")).date() + timedelta(days=1)).isoformat()
    assert request.days[0].date == tomorrow
    assert request.days[0].start_min == 9 * 60      # 09:00
    assert request.days[0].end_min == 22 * 60       # 22:00


@pytest.mark.backend_unit
def test_query_supplied_date_and_window_override_defaults():
    request, errors = planning_request_from_preferences({
        "location": "Sentosa",
        "date": "2026-08-05",
        "daily_start_time": "08:30",
        "daily_end_time": "20:15",
        "timezone": "Asia/Singapore",
        "budget_mode": "unlimited",
        "style": "sightseeing",
        "pace": "balanced",
    })
    assert errors == [] and request is not None
    assert request.days[0].date == "2026-08-05"
    assert request.days[0].start_min == 8 * 60 + 30
    assert request.days[0].end_min == 20 * 60 + 15


@pytest.mark.backend_unit
@pytest.mark.parametrize(
    "field,value",
    [("daily_start_time", "25:00"), ("daily_end_time", "not-a-time")],
)
def test_explicit_invalid_time_is_not_replaced_by_default(field, value):
    request, errors = planning_request_from_preferences({
        "location": "Sentosa",
        "date": "2026-08-05",
        field: value,
        "timezone": "Asia/Singapore",
        "budget_mode": "unlimited",
    })

    assert request is None
    assert errors == [{"code": "invalid_time_window", "day_index": 0}]


@pytest.mark.backend_unit
def test_malformed_explicit_date_still_errors_rather_than_defaulting():
    request, errors = planning_request_from_preferences({
        "location": "Sentosa",
        "date": "not-a-date",
        "timezone": "Asia/Singapore",
        "budget_mode": "unlimited",
    })
    assert request is None
    assert errors == [{"code": "invalid_date", "day_index": 0}]


@pytest.mark.backend_unit
def test_multi_day_defaults_keep_contiguous_dates_from_tomorrow():
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    request, errors = planning_request_from_preferences({
        "location": "Singapore",
        "horizon_days": 3,
        "timezone": "Asia/Singapore",
        "budget_mode": "unlimited",
        "travelers": 2,
        "rooms": 1,
        "style": "mixed",
        "pace": "balanced",
        "lodging_mode": "recommend",
    })
    assert errors == [] and request is not None
    first = datetime.now(ZoneInfo("Asia/Singapore")).date() + timedelta(days=1)
    assert [day.date for day in request.days] == [
        (first + timedelta(days=offset)).isoformat() for offset in range(3)
    ]
    assert all(day.start_min == 9 * 60 and day.end_min == 22 * 60 for day in request.days)


@pytest.mark.backend_unit
def test_lodging_mode_none_ignores_stale_resolved_hotel_anchor():
    request, errors = planning_request_from_preferences({
        "location": "Sentosa",
        "date": "2026-08-01",
        "start_time": "09:00",
        "end_time": "18:00",
        "timezone": "Asia/Singapore",
        "budget_mode": "unlimited",
        "style": "sightseeing",
        "pace": "balanced",
        "lodging_mode": "none",
        "hotel_anchor": "Stale Hotel",
        "resolved_anchors": {
            "start": {
                "query": "Stale Hotel",
                "resolved_name": "Stale Hotel",
                "latitude": 1.25,
                "longitude": 103.82,
            },
        },
    })

    assert errors == []
    assert request is not None
    assert "start" not in request.anchors


@pytest.mark.backend_unit
def test_preferences_build_three_contiguous_days_with_trip_total_budget():
    request, errors = planning_request_from_preferences({
        "location": "Singapore",
        "date": "2026-08-01",
        "horizon_days": 3,
        "daily_start_time": "09:00",
        "daily_end_time": "19:00",
        "timezone": "Asia/Singapore",
        "budget_mode": "limited",
        "budget_amount": 900,
        "budget_currency": "SGD",
        "travelers": 2,
        "rooms": 1,
        "lodging_mode": "recommend",
    })

    assert errors == [] and request is not None
    assert [day.date for day in request.days] == ["2026-08-01", "2026-08-02", "2026-08-03"]
    assert request.budget.scope == "trip_total"
    assert request.budget.include_lodging is True
    assert request.hard_constraints["night_count"] == 2
    assert request.hard_constraints["travelers"] == 2
    assert request.hard_constraints["rooms"] == 1


@pytest.mark.backend_unit
def test_preferences_reject_more_than_three_days():
    request, errors = planning_request_from_preferences({
        "location": "Singapore",
        "date": "2026-08-01",
        "horizon_days": 4,
        "daily_start_time": "09:00",
        "daily_end_time": "19:00",
        "timezone": "Asia/Singapore",
        "budget_mode": "unlimited",
        "travelers": 2,
        "rooms": 1,
    })
    assert request is not None
    assert "unsupported_horizon" in {item["code"] for item in errors}


@pytest.mark.backend_unit
def test_preferences_build_resolved_round_trip_and_distinct_end_anchors():
    base = {
        "location": "Sentosa", "date": "2026-08-01",
        "start_time": "09:00", "end_time": "20:00",
        "timezone": "Asia/Singapore", "budget_mode": "unlimited",
        "style": "sightseeing", "pace": "balanced",
        "hotel_anchor": "Start Hotel",
        "resolved_anchors": {
            "start": {
                "query": "Start Hotel", "resolved_name": "Start Hotel Singapore",
                "latitude": 1.25, "longitude": 103.82, "provider_id": "start-1",
            }
        },
    }
    request, errors = planning_request_from_preferences({**base, "anchor_policy": "round_trip"})
    assert errors == [] and request is not None
    assert request.anchors["start"] == request.anchors["end"]
    assert request.soft_preferences["style"] == "sightseeing"

    distinct, errors = planning_request_from_preferences({
        **base,
        "anchor_policy": "distinct_end",
        "end_anchor": "End Hotel",
        "resolved_anchors": {
            **base["resolved_anchors"],
            "end": {
                "query": "End Hotel", "resolved_name": "End Hotel Singapore",
                "latitude": 1.31, "longitude": 103.86, "provider_id": "end-1",
            },
        },
    })
    assert errors == [] and distinct is not None
    assert distinct.anchors["start"].provider_id == "start-1"
    assert distinct.anchors["end"].provider_id == "end-1"
