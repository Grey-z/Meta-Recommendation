import json
from pathlib import Path

import pytest

from langgraph_metarec.itinerary_candidates import (
    apply_containment_enrichment,
    apply_role_enrichment,
    normalize_candidates,
)
from langgraph_metarec.itinerary_contracts import (
    BudgetConstraint,
    CostEstimate,
    DayConstraint,
    DurationEstimate,
    ItineraryPlanningRequest,
    LocationConstraint,
    PlanningCandidate,
    PlanningProblem,
    planning_request_from_dict,
)
from langgraph_metarec.itinerary_runtime import build_itinerary_block, build_travel_matrix
from langgraph_metarec.itinerary_sanity import validate_activity_policy
from langgraph_metarec.itinerary_solver import BeamItinerarySolver

pytestmark = pytest.mark.backend_unit

FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures" / "itinerary_reasonableness.json").read_text(encoding="utf-8")
)


def test_sentosa_fixture_filters_hotels_and_keeps_anchor_and_gated_access_sound():
    fixture = FIXTURES["sentosa_round_trip"]
    request = planning_request_from_dict(fixture["request"])
    diagnostics = {}
    candidates = normalize_candidates(fixture["candidates"], request, diagnostics=diagnostics)
    candidates = apply_role_enrichment(candidates, {"roles": []}, diagnostics)
    candidates = apply_containment_enrichment(candidates, {"relations": []}, diagnostics)
    assert {candidate.id for candidate in candidates}.isdisjoint({"unrelated-hotel-a", "unrelated-hotel-b"})
    internal = next(candidate for candidate in candidates if candidate.id == "internal-cafe")
    assert internal.access == "gated" and internal.parent_id == "uss"

    solver = BeamItinerarySolver()
    result = solver.solve(PlanningProblem(request, tuple(candidates), build_travel_matrix(candidates, request)))
    block = build_itinerary_block(request, result, candidates)
    selected = [activity["candidate_id"] for activity in result.activities]
    assert selected
    assert all(candidate_id not in {"unrelated-hotel-a", "unrelated-hotel-b", "internal-cafe"} for candidate_id in selected)
    assert block["anchors"]["shared"] is True
    assert block["anchors"]["start"]["title"] == "Siloso Beach Resort - Sentosa"
    assert block["legs"][0]["from_anchor"] == "start"
    assert block["legs"][-1]["to_anchor"] == "end"
    assert validate_activity_policy(request, result.activities, candidates).status == "valid"


def _policy_candidate(identifier, role):
    domain = "restaurant" if role == "food" else "attraction"
    return PlanningCandidate(
        identifier, domain, identifier, 1.3, 103.8,
        DurationEstimate(60, 60, 60, "provider", 1),
        CostEstimate(0, 0, "SGD"),
        role=role,
        item={"id": identifier, "domain": domain, "role": role},
    )


@pytest.mark.parametrize("fixture_name", ["food_tour", "shopping_day"])
def test_style_reasonableness_fixtures_have_valid_primary_roles(fixture_name):
    fixture = FIXTURES[fixture_name]
    candidates = [_policy_candidate(f"{fixture_name}-{index}", role) for index, role in enumerate(fixture["roles"])]
    request = ItineraryPlanningRequest(
        LocationConstraint("Singapore", timezone="Asia/Singapore"),
        (DayConstraint(0, "2026-08-03", 540, 1080),),
        BudgetConstraint("unlimited"),
        soft_preferences={"style": fixture["style"], "pace": "balanced"},
    )
    result = BeamItinerarySolver().solve(PlanningProblem(request, tuple(candidates)))
    assert validate_activity_policy(request, result.activities, candidates).status == "valid"


def test_sparse_fixture_returns_structured_infeasibility_not_filler():
    fixture = FIXTURES["sparse_candidates"]
    request = ItineraryPlanningRequest(
        LocationConstraint("Singapore", timezone="Asia/Singapore"),
        (DayConstraint(0, "2026-08-03", 540, 1080),),
        BudgetConstraint("unlimited"),
        soft_preferences={"style": fixture["style"], "pace": "balanced"},
    )
    result = BeamItinerarySolver().solve(PlanningProblem(request, ()))
    assert result.status == "infeasible"
    assert result.activities == ()
