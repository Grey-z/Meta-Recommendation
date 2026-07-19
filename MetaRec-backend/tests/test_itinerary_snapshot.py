import json

import pytest
from langgraph.checkpoint.memory import MemorySaver

from langgraph_metarec.graphs.task_graph import TaskGraphAdapters, run_task_graph
from langgraph_metarec.itinerary_contracts import (
    BudgetConstraint,
    CostEstimate,
    DayConstraint,
    DurationEstimate,
    ItineraryPlanningRequest,
    LocationConstraint,
    PlanningCandidate,
)
from langgraph_metarec.itinerary_snapshot import (
    MAX_EDGES,
    MAX_FRONTIER_NODES,
    SNAPSHOT_SCHEMA_VERSION,
    build_planning_snapshot,
    sanitize_planning_snapshot,
)
from langgraph_metarec.state import DomainGraphResult

pytestmark = pytest.mark.backend_unit


def _request():
    return ItineraryPlanningRequest(
        LocationConstraint("Singapore", timezone="Asia/Singapore"),
        (DayConstraint(0, "2026-08-03", 540, 1020),),
        BudgetConstraint("limited", 100, "SGD"),
    )


def _candidate(index):
    return PlanningCandidate(
        f"p-{index}", "attraction", f"Place {index}", 1.3 + index / 10000, 103.8,
        DurationEstimate(60, 60, 60, "provider", 1),
        CostEstimate(5, 5, "SGD"), role="experience",
        item={"id": f"p-{index}", "raw": {"secret": "must not leak"}},
    )


def test_snapshot_is_bounded_and_contains_no_provider_raw_or_hidden_utility():
    candidates = tuple(_candidate(index) for index in range(60))
    block = {
        "planning_status": "needs_refinement",
        "slots": [],
        "legs": [
            {"day_index": 0, "from_id": f"p-{index}", "to_id": f"p-{index + 1}",
             "source": "estimate", "mode": "pt", "duration_min": 10, "raw": {"secret": 1}}
            for index in range(80)
        ],
        "days": [{
            "day_index": 0, "date": "2026-08-03", "start_time": "09:00",
            "end_time_constraint": "17:00", "totals": {"end_time": "15:00"},
        }],
        "cost_summary": {"min": 20, "max": 30, "currency": "SGD", "budget_status": "feasible"},
        "uncertainties": [{"code": "hours_unknown"}],
        "solver": {"utility": 999},
    }
    snapshot = build_planning_snapshot(
        revision=2, phase="provisional_solve", request=_request(),
        candidates=candidates, block=block, retired_ids=[f"old-{index}" for index in range(50)],
        provider_calls=3, provider_call_limit=8,
    )
    encoded = json.dumps(snapshot)

    assert len(snapshot["frontier_nodes"]) == MAX_FRONTIER_NODES
    assert len(snapshot["edges"]) == MAX_EDGES
    assert '"raw"' not in encoded
    assert "secret" not in encoded
    assert "utility" not in encoded
    assert snapshot["cost"]["remaining"] == {"min": 70.0, "max": 80.0}


def test_snapshot_sanitizer_rejects_stale_and_strips_nested_values():
    value = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "revision": 3,
        "phase": "seed_retrieval",
        "confirmed_nodes": [{"id": "a", "title": {"raw": "secret"}, "raw": "secret"}],
        "frontier_nodes": [], "edges": [], "days": [],
        "cost": {"remaining": {"min": 10, "max": 20, "raw": "secret"}, "raw": "secret"},
    }
    cleaned = sanitize_planning_snapshot(value, previous_revision=2)
    assert cleaned is not None
    assert cleaned["confirmed_nodes"] == [{"id": "a"}]
    assert cleaned["cost"]["remaining"] == {"min": 10, "max": 20}
    assert sanitize_planning_snapshot(value, previous_revision=3) is None


@pytest.mark.asyncio
async def test_task_projection_keeps_only_latest_snapshot_and_not_event_copies():
    projections = []
    first = build_planning_snapshot(revision=1, phase="seed_retrieval", request=_request())
    second = build_planning_snapshot(revision=2, phase="provisional_solve", request=_request())

    async def run_domain(progress):
        await progress({"stage": "itinerary_planning", "progress": 20, "message": "seed", "planning_snapshot": first})
        await progress({"stage": "itinerary_planning", "progress": 30, "message": "stale", "planning_snapshot": first})
        await progress({"stage": "itinerary_planning", "progress": 40, "message": "solve", "planning_snapshot": second})
        result = {"restaurants": [], "items": [], "metadata": {"planning_snapshot": second}}
        return {
            "result_object": result,
            "result_payload": result,
            "domain_graph_result": DomainGraphResult(
                domain="itinerary", status="completed", result=result,
                metadata={"planning_snapshot": second},
            ),
            "metadata": {"planning_snapshot": second},
        }

    async def write_projection(value):
        projections.append(value)

    await run_task_graph(
        adapters=TaskGraphAdapters(run_domain_graph=run_domain, write_projection=write_projection),
        user_id="u", conversation_id="c", branch_id=None, task_id="task", query="plan",
        checkpointer=MemorySaver(),
    )

    processing = [value for value in projections if value["status"] == "processing"]
    assert processing[-1]["metadata"]["planning_snapshot"]["revision"] == 2
    assert all(
        "planning_snapshot" not in event.get("metadata", {})
        for value in projections for event in value["metadata"].get("progress_events", [])
    )
    assert projections[-1]["metadata"]["planning_snapshot"]["revision"] == 2
    assert projections[-1]["message"] == "Itinerary information gathered."
