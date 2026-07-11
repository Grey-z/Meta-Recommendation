"""Deterministic dynamic itinerary solver over the provider-free planning IR."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, List, Optional, Sequence, Tuple

from langgraph_metarec.itinerary_contracts import (
    ItinerarySolver,
    PlanningCandidate,
    PlanningProblem,
    SolverResult,
)

MEAL_WINDOWS = {"lunch": (11 * 60 + 30, 14 * 60 + 30), "dinner": (17 * 60 + 30, 21 * 60)}
PACE_MAX_STOPS = {"relaxed": 4, "balanced": 6, "packed": 8}


@dataclass(frozen=True)
class _State:
    current_min: int
    last_id: Optional[str] = None
    used: FrozenSet[str] = frozenset()
    satisfied_meals: FrozenSet[str] = frozenset()
    activities: Tuple[Dict[str, Any], ...] = ()
    spend_min: float = 0.0
    spend_max: Optional[float] = 0.0
    utility: float = 0.0
    travel_min: int = 0
    wait_min: int = 0
    uncertainties: Tuple[Dict[str, Any], ...] = ()


def _travel(problem: PlanningProblem, from_id: Optional[str], to_id: str) -> int:
    if from_id is None:
        return 0
    try:
        return max(0, int(problem.travel_minutes.get(from_id, {}).get(to_id, 0)))
    except (TypeError, ValueError):
        return 0


def _availability_start(candidate: PlanningCandidate, earliest: int, duration: int) -> Optional[int]:
    if not candidate.availability_known:
        return earliest
    for window in candidate.availability_windows:
        start = max(earliest, window.start_min)
        if start + duration <= window.end_min:
            return start
    return None


def _candidate_utility(candidate: PlanningCandidate) -> float:
    quality = max(0.0, min(1.0, float(candidate.rating or 0) / 5.0))
    domain_weight = 1.2 if candidate.domain == "attraction" else (0.75 if candidate.domain == "restaurant" else 0.2)
    return domain_weight + candidate.provider_relevance + quality


def _must_visit_ids(problem: PlanningProblem) -> FrozenSet[str]:
    values = problem.request.hard_constraints.get("must_visit") or ()
    normalized = {str(value).strip().lower() for value in values if str(value).strip()}
    ids = {
        candidate.id
        for candidate in problem.candidates
        if candidate.id.lower() in normalized or candidate.title.strip().lower() in normalized
    }
    return frozenset(ids)


def _state_key(state: _State, required_meals: FrozenSet[str], must_ids: FrozenSet[str]) -> Tuple[Any, ...]:
    missing = len(required_meals - state.satisfied_meals) + len(must_ids - state.used)
    signature = tuple(activity["candidate_id"] for activity in state.activities)
    return (
        missing,
        len(state.uncertainties),
        -round(state.utility, 6),
        state.travel_min + state.wait_min,
        state.current_min,
        signature,
    )


def _budget_add(
    state: _State,
    candidate: PlanningCandidate,
    budget_currency: Optional[str],
) -> Tuple[float, Optional[float], Optional[Dict[str, Any]]]:
    cost = candidate.cost
    if cost.min is None or cost.max is None:
        return state.spend_min, None, {"code": "cost_unknown", "candidate_id": candidate.id}
    if budget_currency and str(cost.currency or "").upper() != budget_currency.upper():
        return state.spend_min, None, {
            "code": "currency_mismatch", "candidate_id": candidate.id,
            "currency": cost.currency,
        }
    return (
        state.spend_min + float(cost.min),
        None if state.spend_max is None else state.spend_max + float(cost.max),
        None,
    )


class BeamItinerarySolver(ItinerarySolver):
    def __init__(self, *, beam_width: int = 48) -> None:
        self.beam_width = max(1, beam_width)

    def solve(self, problem: PlanningProblem) -> SolverResult:
        request = problem.request
        day = request.days[0]
        required_meals = frozenset(request.hard_constraints.get("meal_obligations") or ())
        must_ids = _must_visit_ids(problem)
        pace = str(request.soft_preferences.get("pace") or "balanced")
        max_stops = PACE_MAX_STOPS.get(pace, PACE_MAX_STOPS["balanced"])
        budget_limit = request.budget.amount if request.budget.mode == "limited" else None
        budget_currency = request.budget.currency if request.budget.mode == "limited" else None
        beam: List[_State] = [_State(current_min=day.start_min)]
        finals: List[_State] = []
        expanded = 0

        for _depth in range(max_stops):
            next_states: List[_State] = []
            for state in beam:
                if state.activities and required_meals <= state.satisfied_meals and must_ids <= state.used:
                    finals.append(state)
                for candidate in problem.candidates:
                    if candidate.id in state.used:
                        continue
                    travel = _travel(problem, state.last_id, candidate.id)
                    earliest = state.current_min + travel
                    unsatisfied_meals = [meal for meal in required_meals - state.satisfied_meals]
                    if candidate.domain == "restaurant" and unsatisfied_meals:
                        meal = min(unsatisfied_meals, key=lambda name: MEAL_WINDOWS.get(name, (0, 0))[0])
                        earliest = max(earliest, MEAL_WINDOWS.get(meal, (earliest, earliest))[0])
                    start = _availability_start(candidate, earliest, candidate.duration.preferred)
                    if start is None or start + candidate.duration.preferred > day.end_min:
                        continue
                    spend_min, spend_max, cost_uncertainty = _budget_add(state, candidate, budget_currency)
                    if budget_limit is not None and spend_min > budget_limit:
                        continue
                    end = start + candidate.duration.preferred
                    meals = set(state.satisfied_meals)
                    meals.update(candidate.meal_coverage)
                    if candidate.domain == "restaurant":
                        for meal, (window_start, window_end) in MEAL_WINDOWS.items():
                            if meal in required_meals and window_start <= start <= window_end:
                                meals.add(meal)
                    uncertainties = list(state.uncertainties)
                    if not candidate.availability_known:
                        uncertainties.append({"code": "opening_hours_unknown", "candidate_id": candidate.id})
                    if candidate.duration.confidence < 0.6:
                        uncertainties.append({"code": "duration_uncertain", "candidate_id": candidate.id})
                    if budget_limit is not None and cost_uncertainty is not None:
                        uncertainties.append(cost_uncertainty)
                    if candidate.duration.max > candidate.duration.preferred and start + candidate.duration.max > day.end_min:
                        uncertainties.append({"code": "duration_may_exceed_window", "candidate_id": candidate.id})
                    activity = {
                        "day_index": 0,
                        "candidate_id": candidate.id,
                        "domain": candidate.domain,
                        "start_min": start,
                        "end_min": end,
                        "duration": {
                            "min": candidate.duration.min,
                            "preferred": candidate.duration.preferred,
                            "max": candidate.duration.max,
                            "source": candidate.duration.source,
                            "confidence": candidate.duration.confidence,
                        },
                        "cost": {
                            "min": candidate.cost.min,
                            "max": candidate.cost.max,
                            "currency": candidate.cost.currency,
                            "source": candidate.cost.source,
                        },
                        "meal_coverage": sorted(candidate.meal_coverage),
                        "item": dict(candidate.item),
                    }
                    next_states.append(_State(
                        current_min=end,
                        last_id=candidate.id,
                        used=state.used | {candidate.id},
                        satisfied_meals=frozenset(meals),
                        activities=state.activities + (activity,),
                        spend_min=spend_min,
                        spend_max=spend_max,
                        utility=state.utility + _candidate_utility(candidate) - 0.012 * travel - 0.004 * (start - earliest),
                        travel_min=state.travel_min + travel,
                        wait_min=state.wait_min + (start - earliest),
                        uncertainties=tuple(uncertainties),
                    ))
                    expanded += 1
            if not next_states:
                break
            # Dominance projection keeps the best state for an equivalent
            # position/time/obligation signature before applying beam width.
            dominant: Dict[Tuple[Any, ...], _State] = {}
            for state in next_states:
                key = (
                    state.last_id,
                    state.current_min // 15,
                    state.satisfied_meals,
                    frozenset(must_ids & state.used),
                    len(state.activities),
                )
                previous = dominant.get(key)
                if previous is None or _state_key(state, required_meals, must_ids) < _state_key(previous, required_meals, must_ids):
                    dominant[key] = state
            beam = sorted(dominant.values(), key=lambda state: _state_key(state, required_meals, must_ids))[:self.beam_width]

        finals.extend(
            state for state in beam
            if state.activities and required_meals <= state.satisfied_meals and must_ids <= state.used
        )
        if not finals:
            return SolverResult(
                status="infeasible",
                activities=(),
                cost_summary={
                    "min": 0.0, "max": 0.0, "currency": budget_currency,
                    "budget_limit": budget_limit, "budget_status": "infeasible",
                },
                unsatisfied_constraints=tuple(
                    [{"code": "meal_obligation", "value": meal} for meal in sorted(required_meals)]
                    + [{"code": "must_visit", "candidate_id": item_id} for item_id in sorted(must_ids)]
                    + ([{"code": "no_feasible_route"}] if not required_meals and not must_ids else [])
                ),
                diagnostics={"strategy": "bounded_beam_search", "expanded_states": expanded, "beam_width": self.beam_width},
            )
        winner = min(finals, key=lambda state: _state_key(state, required_meals, must_ids))
        if budget_limit is None:
            budget_status = "unlimited"
        elif winner.spend_max is None or winner.spend_max > budget_limit:
            budget_status = "indeterminate"
        else:
            budget_status = "feasible"
        status = "indeterminate" if winner.uncertainties or budget_status == "indeterminate" else "feasible"
        return SolverResult(
            status=status,
            activities=winner.activities,
            cost_summary={
                "min": round(winner.spend_min, 2),
                "max": round(winner.spend_max, 2) if winner.spend_max is not None else None,
                "currency": budget_currency,
                "budget_limit": budget_limit,
                "budget_status": budget_status,
            },
            uncertainties=winner.uncertainties,
            diagnostics={
                "strategy": "bounded_beam_search",
                "beam_width": self.beam_width,
                "expanded_states": expanded,
                "selected_stops": len(winner.activities),
                "travel_min": winner.travel_min,
                "wait_min": winner.wait_min,
                "utility": round(winner.utility, 6),
            },
        )


def build_solver(name: str = "beam") -> ItinerarySolver:
    if str(name or "beam").strip().lower() != "beam":
        raise ValueError(f"Unsupported itinerary solver: {name}")
    return BeamItinerarySolver()
