import pytest

from langgraph_metarec.itinerary_contracts import (
    BudgetConstraint,
    DayConstraint,
    ItineraryPlanningRequest,
    LocationConstraint,
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
    assert request.to_dict()["schema_version"] == "itinerary-ir/v1"


@pytest.mark.backend_unit
def test_planning_request_rejects_multi_day_and_incomplete_budget():
    request = ItineraryPlanningRequest(
        location=LocationConstraint(query="Singapore"),
        days=(
            DayConstraint(day_index=0, date="2026-08-01", start_min=540, end_min=1080),
            DayConstraint(day_index=1, date="2026-08-02", start_min=540, end_min=1080),
        ),
        budget=BudgetConstraint(mode="limited"),
    )
    codes = {item["code"] for item in validate_planning_request(request)}
    assert {"unsupported_horizon", "missing_budget_amount", "missing_budget_currency"} <= codes
