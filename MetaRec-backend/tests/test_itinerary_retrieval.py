import pytest

from langgraph_metarec.itinerary_contracts import (
    CostEstimate,
    DurationEstimate,
    PlanningCandidate,
)
from langgraph_metarec.itinerary_retrieval import (
    AdaptiveEvaluation,
    AdaptiveItineraryPlanner,
    CandidateStore,
    RetrievalBudget,
    RetrievalRequest,
    domains_needing_retrieval,
    evaluation_failure_codes,
)

pytestmark = pytest.mark.backend_unit


def _candidate(identifier: str) -> PlanningCandidate:
    return PlanningCandidate(
        identifier, "attraction", identifier, 1.3, 103.8,
        DurationEstimate(30, 30, 30, "rule", 0.5),
        CostEstimate(None, None, None),
        role="experience",
        item={"id": identifier, "domain": "attraction", "title": identifier, "lat": 1.3, "lng": 103.8},
    )


def _request(task_id="task-1", *, lat=1.3, radius=1000, signature="base"):
    return RetrievalRequest(
        task_id=task_id,
        tool="osm.attraction.discover",
        domain="attraction",
        role="experience",
        anchor_lat=lat,
        anchor_lng=103.8,
        radius_meters=radius,
        constraint_signature=signature,
    )


def test_candidate_store_is_task_isolated_bounded_and_disposable():
    store = CandidateStore("task-1", max_entries=2, max_candidates_per_entry=2, ttl_seconds=10)
    first = store.put(_request(signature="one"), [_candidate("a"), _candidate("a"), _candidate("b"), _candidate("c")], now=1)
    assert [item.id for item in first.candidates] == ["a", "b"]
    assert store.get(_request(signature="one"), now=2) == first

    negative = store.put(_request(signature="none"), [], now=2)
    assert negative.negative is True
    store.put(_request(signature="three"), [_candidate("c")], now=3)
    assert store.get(_request(signature="one"), now=3) is None
    assert [item.id for item in store.candidates()] == ["c"]

    with pytest.raises(ValueError):
        store.get(_request(task_id="other"))
    store.close()
    assert store.closed is True and store.candidates() == ()
    with pytest.raises(RuntimeError):
        store.put(_request(), [_candidate("x")])


def test_candidate_store_keys_anchor_buckets_and_expires_entries():
    store = CandidateStore("task-1", ttl_seconds=5)
    request = _request(lat=1.3001, radius=1100)
    store.put(request, [_candidate("a")], now=10)

    # Same rounded cell and 500 m radius bucket is a cache hit.
    assert store.get(_request(lat=1.3002, radius=1200), now=11) is not None
    assert store.get(request, now=15) is None


def test_retrieval_budget_hard_bounds_calls_and_rounds():
    budget = RetrievalBudget(max_provider_calls=2, max_rounds=1)
    assert budget.begin_round() is True
    assert budget.begin_round() is False
    assert budget.consume_call() is True
    assert budget.consume_call() is True
    assert budget.consume_call() is False


@pytest.mark.asyncio
async def test_adaptive_planner_fetches_cache_misses_and_stops_on_stable_winner():
    calls = []
    solve_inputs = []

    async def fetch(request):
        calls.append(request.constraint_signature)
        return [_candidate("seed" if request.constraint_signature == "seed" else "nearby")]

    def evaluate(candidates):
        solve_inputs.append(tuple(item.id for item in candidates))
        return AdaptiveEvaluation(
            status="feasible",
            selected_ids=tuple(item.id for item in candidates),
            utility=float(len(candidates)),
        )

    def derive(evaluation, _candidates):
        if "nearby" in evaluation.selected_ids:
            return []
        # Duplicate requests in the same round are clustered into one provider call.
        return [_request(signature="nearby"), _request(signature="nearby")]

    planner = AdaptiveItineraryPlanner(
        "task-1", fetch=fetch, evaluate=evaluate, derive_requests=derive,
        budget=RetrievalBudget(max_provider_calls=3, max_rounds=2),
    )
    result = await planner.run([_request(signature="seed"), _request(signature="seed")])

    assert calls == ["seed", "nearby"]
    assert solve_inputs == [("seed",), ("nearby", "seed")]
    assert result.provider_calls == 2
    assert result.stop_reason == "stable_feasible_winner"
    assert result.evaluation and result.evaluation.selected_ids == ("nearby", "seed")
    assert planner.store.closed is True


@pytest.mark.asyncio
async def test_adaptive_planner_fetches_independent_requests_in_one_round():
    calls = []

    async def fetch(request):
        calls.append(request.constraint_signature)
        return [_candidate(request.constraint_signature)]

    planner = AdaptiveItineraryPlanner(
        "task-1",
        fetch=fetch,
        evaluate=lambda candidates: AdaptiveEvaluation(
            "feasible", tuple(item.id for item in candidates), float(len(candidates))
        ),
        derive_requests=lambda _evaluation, _candidates: (),
        budget=RetrievalBudget(max_provider_calls=4, max_rounds=1),
    )
    result = await planner.run([_request(signature="a"), _request(signature="b")])

    assert sorted(calls) == ["a", "b"]
    assert result.provider_calls == 2
    assert result.evaluation and set(result.evaluation.selected_ids) == {"a", "b"}


@pytest.mark.asyncio
async def test_adaptive_planner_negative_cache_bounds_errors_and_preserves_best():
    calls = []

    async def fetch(request):
        calls.append(request.constraint_signature)
        if request.constraint_signature == "error":
            raise TimeoutError("provider timeout")
        return [_candidate("best")] if request.constraint_signature == "seed" else []

    def evaluate(candidates):
        ids = tuple(item.id for item in candidates)
        return AdaptiveEvaluation(
            status="feasible" if ids else "infeasible",
            selected_ids=ids,
            utility=10.0 if ids else 0.0,
        )

    def derive(evaluation, _candidates):
        return [_request(signature="empty"), _request(signature="error")]

    planner = AdaptiveItineraryPlanner(
        "task-1", fetch=fetch, evaluate=evaluate, derive_requests=derive,
        budget=RetrievalBudget(max_provider_calls=2, max_rounds=3),
    )
    result = await planner.run([_request(signature="seed")])

    # The hard provider budget prevents the second follow-up call.
    assert calls == ["seed", "empty"]
    assert result.provider_calls == 2
    assert result.stop_reason == "no_material_candidate_change"
    assert result.evaluation and result.evaluation.selected_ids == ("best",)


@pytest.mark.asyncio
async def test_adaptive_planner_propagates_cancellation_and_disposes_store():
    async def fetch(_request_value):
        raise __import__("asyncio").CancelledError()

    planner = AdaptiveItineraryPlanner(
        "task-1",
        fetch=fetch,
        evaluate=lambda _candidates: AdaptiveEvaluation("infeasible", (), 0.0),
        derive_requests=lambda _evaluation, _candidates: (),
    )
    with pytest.raises(__import__("asyncio").CancelledError):
        await planner.run([_request()])
    assert planner.store.closed is True


# --- Failure-code routing -------------------------------------------------
#
# Regression cover for the NTU run where "Canteen B" (must_visit) was never
# retrieved: the loop routed must_visit_unavailable to attractions only and
# never saw sanity *violations*, so the one trigger that re-queries restaurants
# was unreachable. See itinerary_retrieval.evaluation_failure_codes.


def test_failure_codes_include_sanity_violations_not_just_warnings():
    codes = evaluation_failure_codes({
        "unsatisfied_constraints": [{"code": "must_visit_unavailable", "value": "Canteen B"}],
        "sanity_warnings": [{"code": "missing_primary_experience"}],
        "sanity_violations": [{"code": "meal_obligation", "meal": "lunch"}],
    })

    # meal_obligation is only ever raised as a violation; dropping that channel
    # is what made the restaurant re-fetch trigger dead code.
    assert codes == {"must_visit_unavailable", "missing_primary_experience", "meal_obligation"}


def test_failure_codes_tolerate_missing_and_malformed_channels():
    assert evaluation_failure_codes({}) == frozenset()
    assert evaluation_failure_codes({
        "sanity_violations": [{"code": ""}, "not-a-mapping", {"no_code": 1}],
    }) == frozenset()


def test_unresolved_must_visit_widens_to_every_active_domain():
    active = ("attraction", "restaurant")

    needs = domains_needing_retrieval({"must_visit_unavailable"}, active)

    # The code says a named venue is missing but not what kind of venue it is.
    # Attraction-only routing is why a missing canteen kept re-fetching landmarks.
    assert needs == {"attraction", "restaurant"}


def test_unresolved_must_visit_never_invents_an_inactive_domain():
    needs = domains_needing_retrieval({"must_visit_unavailable"}, ("attraction",))

    assert needs == {"attraction"}


def test_meal_obligation_routes_to_restaurant_and_not_attraction():
    needs = domains_needing_retrieval({"meal_obligation"}, ("attraction", "restaurant"))

    assert needs == {"restaurant"}


def test_experience_gaps_still_route_to_attraction_only():
    needs = domains_needing_retrieval({"missing_primary_experience"}, ("attraction", "restaurant"))

    assert needs == {"attraction"}


def test_infeasible_status_alone_still_pulls_attractions():
    assert domains_needing_retrieval(frozenset(), ("attraction", "restaurant"), infeasible=True) == {
        "attraction"
    }
    assert domains_needing_retrieval(frozenset(), ("attraction", "restaurant")) == frozenset()
