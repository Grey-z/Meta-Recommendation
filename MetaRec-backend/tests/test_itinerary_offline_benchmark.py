import asyncio
import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from langgraph_metarec.itinerary_contracts import (
    AnchorConstraint,
    AvailabilityWindow,
    BudgetConstraint,
    CostEstimate,
    DayConstraint,
    DurationEstimate,
    ItineraryPlanningRequest,
    LocationConstraint,
    LodgingRequirement,
    LodgingScenario,
    PlanningCandidate,
    PlanningProblem,
)
from langgraph_metarec.itinerary_evaluation import (
    evaluate_itinerary,
    summarize_itinerary_evaluations,
)
from langgraph_metarec.itinerary_retrieval import (
    AdaptiveEvaluation,
    AdaptiveItineraryPlanner,
    RetrievalBudget,
    RetrievalRequest,
)
from langgraph_metarec.itinerary_runtime import build_itinerary_block, build_travel_matrix
from langgraph_metarec.itinerary_solver import BeamItinerarySolver

pytestmark = pytest.mark.backend_unit

FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures" / "itinerary_offline_benchmark.json").read_text(encoding="utf-8")
)


def _request(spec):
    first = date(2026, 8, 3)
    day_count = int(spec["days"])
    days = tuple(
        DayConstraint(index, str(first + timedelta(days=index)), 540, 1020)
        for index in range(day_count)
    )
    budget = (
        BudgetConstraint("limited", float(spec["budget"]), "SGD", scope="trip_total", include_lodging=day_count > 1)
        if spec.get("budget") is not None else BudgetConstraint("unlimited", scope="trip_total")
    )
    anchors = {}
    if spec.get("anchor") == "supplied":
        hotel = AnchorConstraint(
            "Fixture Hotel", resolved_name="Fixture Hotel", latitude=1.29,
            longitude=103.84, provider_id="hotel-anchor", source="fixture",
        )
        anchors = {"start": hotel, "end": hotel}
    lodging = None
    if day_count > 1:
        lodging = LodgingRequirement(
            "recommend", str(first), str(first + timedelta(days=day_count)),
            day_count - 1, 1, 1,
        )
    return ItineraryPlanningRequest(
        LocationConstraint("Singapore", timezone="Asia/Singapore"),
        days,
        budget,
        lodging=lodging,
        anchors=anchors,
        hard_constraints={"meal_obligations": []},
        soft_preferences={"pace": "balanced", "style": spec.get("style", "sightseeing")},
        explicit_fields=("location", "date", "start_time", "end_time", "budget_mode"),
    )


def _candidates(rows):
    output = []
    for index, row in enumerate(rows or []):
        role = row["role"]
        domain = "restaurant" if role == "food" else "attraction"
        cost = row.get("cost")
        output.append(PlanningCandidate(
            row["id"], domain, row["id"], 1.29 + index * 0.002, 103.84 + index * 0.002,
            DurationEstimate(row["duration"], row["duration"], row["duration"], "fixture", 1.0),
            CostEstimate(cost, cost, "SGD" if cost is not None else None, ("fixture",), "fixture", 1.0),
            availability_windows=tuple(AvailabilityWindow(day, 540, 1020) for day in row.get("days", [0])),
            availability_known=True,
            provider_relevance=float(row.get("relevance", 0.8)),
            role=role,
            role_source="fixture",
            item={"id": row["id"], "title": row["id"], "domain": domain, "role": role, "lat": 1.29 + index * 0.002, "lng": 103.84 + index * 0.002},
        ))
    return tuple(output)


def _lodging(spec, request):
    lodging_spec = spec.get("lodging")
    if not lodging_spec:
        return ()
    nightly = lodging_spec.get("nightly")
    nightly_cost = CostEstimate(nightly, nightly, "SGD" if nightly is not None else None, ("lodging",), "fixture", 1.0)
    trip = None if nightly is None else float(nightly) * (request.lodging.nights if request.lodging else 0)
    trip_cost = CostEstimate(trip, trip, "SGD" if trip is not None else None, ("lodging",), "fixture", 1.0)
    return (LodgingScenario("hotel", "Shared Fixture Hotel", 1.285, 103.835, "1 Fixture Road", "fixture", nightly_cost, trip_cost),)


def _solve(spec, rows=None):
    request = _request(spec)
    candidates = _candidates(spec.get("candidates") if rows is None else rows)
    lodging = _lodging(spec, request)
    matrix = build_travel_matrix(candidates, request, lodging)
    result = BeamItinerarySolver().solve(PlanningProblem(request, candidates, matrix, lodging))
    block = build_itinerary_block(request, result, candidates)
    return result, block, candidates


@pytest.mark.parametrize(
    "name",
    [
        "unanchored_single_day", "supplied_hotel", "failed_anchor_cleared",
        "two_day_city", "three_day_mixed", "unknown_hotel_price",
    ],
)
def test_offline_planning_scenarios(name):
    spec = FIXTURES[name]
    result, block, _ = _solve(spec)
    assert result.status == spec["expected"]
    assert len(block["days"]) == spec["days"]
    assert evaluate_itinerary(block)["duplicate_rate"] == 0
    if name == "failed_anchor_cleared":
        assert block["anchors"]["start"] is None and block["anchors"]["end"] is None
    if spec["days"] > 1:
        assert block["lodging"]["candidate_id"] == "hotel"
        assert all(day["legs"][0].get("from_anchor") == "lodging" for day in block["days"])


@pytest.mark.asyncio
async def test_adaptive_frontier_improves_same_seed_without_unbounded_calls():
    spec = FIXTURES["sparse_frontier_recovery"]
    baseline_result, baseline_block, _ = _solve(spec, spec["seed"])
    request = _request(spec)

    async def fetch(retrieval):
        return _candidates(spec["seed"] if retrieval.constraint_signature == "seed" else spec["frontier"])

    def evaluate(candidates):
        lodging = _lodging(spec, request)
        result = BeamItinerarySolver().solve(PlanningProblem(
            request, tuple(candidates), build_travel_matrix(candidates, request, lodging), lodging,
        ))
        return AdaptiveEvaluation(
            result.status,
            tuple(item["candidate_id"] for item in result.activities),
            float(sum(int(item["end_min"]) - int(item["start_min"]) for item in result.activities)),
            diagnostics={"uncertainty_count": len(result.uncertainties)},
            payload=build_itinerary_block(request, result, candidates),
        )

    def derive(evaluation, _candidates_value):
        if len(evaluation.selected_ids) >= 2:
            return ()
        return (_retrieval("frontier"),)

    planner = AdaptiveItineraryPlanner(
        "benchmark", fetch=fetch, evaluate=evaluate, derive_requests=derive,
        budget=RetrievalBudget(max_provider_calls=3, max_rounds=2),
    )
    adaptive = await planner.run((_retrieval("seed"),))
    assert adaptive.evaluation is not None
    assert len(adaptive.evaluation.selected_ids) >= len(baseline_result.activities)
    assert adaptive.provider_calls == 2
    assert adaptive.provider_calls <= 3
    assert adaptive.evaluation.payload["planning_status"] == "feasible"
    assert evaluate_itinerary(adaptive.evaluation.payload)["mean_day_utilization"] > evaluate_itinerary(baseline_block)["mean_day_utilization"]


def _retrieval(signature):
    return RetrievalRequest(
        "benchmark", "fixture.search", "attraction", "experience",
        1.29, 103.84, 3000, signature,
    )


@pytest.mark.asyncio
async def test_provider_exhaustion_is_bounded_and_returns_structured_infeasibility():
    spec = FIXTURES["provider_exhaustion"]

    async def fetch(_request_value):
        return ()

    planner = AdaptiveItineraryPlanner(
        "benchmark", fetch=fetch,
        evaluate=lambda candidates: AdaptiveEvaluation("infeasible", (), 0.0),
        derive_requests=lambda _evaluation, _candidates_value: (_retrieval("frontier"),),
        budget=RetrievalBudget(max_provider_calls=spec["provider_call_limit"], max_rounds=2),
    )
    result = await planner.run((_retrieval("seed"),))
    assert result.provider_calls == 1
    assert result.evaluation and result.evaluation.status == spec["expected"]
    assert planner.store.closed is True


@pytest.mark.asyncio
async def test_offline_cancellation_disposes_task_cache():
    async def fetch(_request_value):
        raise asyncio.CancelledError()

    planner = AdaptiveItineraryPlanner(
        "benchmark", fetch=fetch,
        evaluate=lambda _candidates_value: AdaptiveEvaluation("infeasible", (), 0.0),
        derive_requests=lambda _evaluation, _candidates_value: (),
    )
    with pytest.raises(asyncio.CancelledError):
        await planner.run((_retrieval("seed"),))
    assert planner.store.closed is True


def test_offline_summary_reports_release_metrics():
    blocks = [_solve(FIXTURES[name])[1] for name in (
        "unanchored_single_day", "supplied_hotel", "failed_anchor_cleared",
        "two_day_city", "three_day_mixed", "unknown_hotel_price",
    )]
    summary = summarize_itinerary_evaluations(blocks)
    assert summary["case_count"] == 6
    assert summary["delivery_rate"] == 1.0
    assert summary["duplicate_rate"] == 0.0
    assert summary["hotel_continuity_rate"] == 1.0
    assert summary["expanded_states"] > 0
