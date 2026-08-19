"""Instrumented copy of langgraph_metarec/itinerary_solver.py for objective sweeps.

Calibration harness only -- never import from the app. It records beam-trim
sizes, tie depths in the objective key, and final-ranking decisions into the
module-level PROBE dict (see the ROLE_REPEAT_DISCOUNT / TRANSITION_COST_MIN
sweep notes in the real solver). Re-sync this file from itinerary_solver.py
before each sweep; it drifts otherwise. Run from MetaRec-backend/ so the
langgraph_metarec imports resolve.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, List, Optional, Sequence, Tuple

from langgraph_metarec.itinerary_contracts import (
    ItinerarySolver,
    PlanningCandidate,
    PlanningProblem,
    SolverResult,
)
from langgraph_metarec.itinerary_policy import (
    PACE_MAX_IDLE_GAP,
    attraction_type_match_tokens,
    style_policy,
)
from langgraph_metarec.itinerary_metrics import compute_route_quality_metrics
from langgraph_metarec.itinerary_sanity import validate_activity_policy

MEAL_WINDOWS = {
    "breakfast": (7 * 60, 10 * 60 + 30),
    "lunch": (11 * 60 + 30, 14 * 60 + 30),
    "dinner": (17 * 60 + 30, 21 * 60),
}
PACE_MAX_STOPS = {"relaxed": 4, "balanced": 6, "packed": 8}

# Weight on the share of the planning window spent travelling, folded into
# schedule_quality (objective key 3). Before this, travel only appeared at key
# 10 -- behind three continuous floats that practically never tie -- so the
# objective scored a 25-minute-travel day and a 120-minute-travel day
# identically and spatial continuity was decided by chance.
#
# Paired against the 2.0 weight on planning_window_utilization, this sets the
# break-even for adding a stop at `travel <= (2.0 / weight) * dwell`: at 1.0 a
# detour is worth it as long as you stay at least half as long as the trip out.
# Keep it below 6.0 -- past that a marginal stop can never pay for its own
# travel and the solver starts preferring shorter days over closer ones.
TRAVEL_SHARE_WEIGHT = 1.0

# Decay exponent for the repeated-role discount within a day (see
# _role_repeat_discount). The n-th stop of a role is worth 1/n**exponent.
#
# This was 1.0 -- harmonic decay, and far too steep. The quality term went
# *negative* by the sixth same-role stop (+0.898 at one stop, -0.033 at six once
# transition_friction applies), so only planning_window_utilization at weight
# 2.0 kept multi-stop days alive. Setting those two equal puts the break-even at
# ~74 minutes of dwell, and because it is a threshold rather than a gradient it
# behaved as a cliff: measured over eight realistic short-dwell Singapore pools
# (museums, temples, viewpoints, hawker centres -- all 45-90 minute stops), 1.0
# returned a ONE-stop day in 8 of 8, averaging 14.4% of the planning window.
# The same pools at 90-minute dwells returned six stops each.
#
# 0.25 clears the pathology outright (0 of 8 one-stop days, 45.0% mean window
# use) while keeping real damping -- a sixth repeat is still worth 0.64x the
# first. Values are near-linear in effect, so tune by measurement:
#   1.0 -> 8/8 one-stop, 14.4%   0.5 -> 6/8, 22.1%   0.35 -> 2/8, 37.1%
#   0.25 -> 0/8, 45.0%           0.0 -> 0/8, 47.2%
# Do not raise it past ~0.3 without re-running that sweep; the cliff returns
# quickly. Route quality is unaffected across the whole range (detour ratio
# 1.000-1.010), and so is composition -- see _role_repeat_discount.
ROLE_REPEAT_DISCOUNT_EXPONENT = 0.25

# Weight on planning_window_utilization inside schedule_quality. Named because
# transition friction is denominated against it -- see TRANSITION_COST_MIN.
WINDOW_UTILIZATION_WEIGHT = 2.0

# Minutes of dwell a stop must be worth to justify its own transition.
#
# Friction used to be a flat 0.08 per extra stop while everything else in
# schedule_quality is a normalised ratio. Mixing absolute and relative units made
# the trade silently depend on window length and trip length: the reward for a
# stop is WINDOW_UTILIZATION_WEIGHT * dwell / window, which shrinks as the window
# grows, while the flat cost did not. Break-even was `dwell > 0.04 * window`, and
# for multi-day `window` is the WHOLE-TRIP sum, so the bar rose with every extra
# day -- 28.8 minutes on a one-day trip, 115 minutes on a four-day one. Measured
# against a 12-candidate pool of 45-minute POIs, a 4-day request returned 4 total
# stops (one per day) where the same pool over 1 day returned 8. A longer trip
# produced a thinner itinerary.
#
# Expressing friction in the same units removes both effects: break-even is now
# this many minutes of dwell regardless of day length or trip length. 20 was
# chosen by sweep -- it clears the small-pool knife edge that 28.8 (the value
# equivalent to the old 0.08 on a 12-hour day) still left behind, without
# admitting stops too short to be worth the trip.
TRANSITION_COST_MIN = 20.0



PROBE = {"trim": [], "final": [], "beamtie": []}

def _tie_depth(a, b):
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return i
    return -1

def _record_final(rows, tag):
    keys = sorted(row[0] for row in rows)
    depth = _tie_depth(keys[0], keys[1]) if len(keys) > 1 else None
    PROBE["final"].append({"tag": tag, "n": len(keys), "decided_at": depth})


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


@dataclass(frozen=True)
class _TripState:
    day_index: int
    current_min: int
    last_id: Optional[str]
    used: FrozenSet[str] = frozenset()
    satisfied_meals: FrozenSet[str] = frozenset()
    activities: Tuple[Dict[str, Any], ...] = ()
    spend_min: float = 0.0
    spend_max: Optional[float] = 0.0
    utility: float = 0.0
    travel_min: int = 0
    wait_min: int = 0
    tail_slack_min: int = 0
    day_stop_count: int = 0
    day_primary_count: int = 0
    completed_day_travel: Tuple[int, ...] = ()
    completed_day_wait: Tuple[int, ...] = ()
    current_day_travel: int = 0
    current_day_wait: int = 0
    uncertainties: Tuple[Dict[str, Any], ...] = ()


def _travel(problem: PlanningProblem, from_id: Optional[str], to_id: str) -> int:
    if from_id is None:
        return 0
    try:
        return max(0, int(problem.travel_minutes.get(from_id, {}).get(to_id, 0)))
    except (TypeError, ValueError):
        return 0


def _availability_start(
    candidate: PlanningCandidate,
    earliest: int,
    duration: int,
    day_index: int = 0,
) -> Optional[int]:
    if not candidate.availability_known:
        return earliest
    for window in candidate.availability_windows:
        if window.day_index != day_index:
            continue
        start = max(earliest, window.start_min)
        if start + duration <= window.end_min:
            return start
    return None


def _candidate_utility(candidate: PlanningCandidate, state: _State) -> float:
    quality = max(0.0, min(1.0, float(candidate.rating or 0) / 5.0))
    domain_weight = 1.2 if candidate.domain == "attraction" else (0.75 if candidate.domain == "restaurant" else 0.2)
    repeats = sum(1 for activity in state.activities if activity.get("role") == candidate.role)
    return (domain_weight + candidate.provider_relevance + quality) / (1 + 0.6 * repeats) - 0.25


def _calibrated_quality(candidate: PlanningCandidate) -> float:
    rating = float(candidate.rating or 0)
    if rating <= 0:
        return 0.5 * candidate.provider_relevance
    try:
        reviews = max(0, int(candidate.item.get("reviews_count") or 0))
    except (TypeError, ValueError):
        reviews = 0
    confidence = min(1.0, math.log1p(reviews) / math.log1p(500)) if reviews else 0.25
    rating_quality = 0.5 + (max(0.0, min(5.0, rating)) / 5.0 - 0.5) * confidence
    return 0.7 * rating_quality + 0.3 * candidate.provider_relevance


def _transition_friction(extra_stops: int, window_min: int) -> float:
    """Cost of each extra stop, in the same units as planning_window_utilization.

    Both paths charge this per stop beyond the first *within a day*, so a stop
    pays for itself once its dwell exceeds TRANSITION_COST_MIN -- independent of
    how long the day is or how many days the trip spans. ``window_min`` must be
    the same denominator the utilization term uses (the whole-trip sum on the
    multi-day path), or the two stop cancelling and the scale dependence returns.
    """
    return (
        WINDOW_UTILIZATION_WEIGHT
        * TRANSITION_COST_MIN
        * max(0, extra_stops)
        / max(1, window_min)
    )


def _role_repeat_discount(repeat_index: int) -> float:
    """Discount applied to the ``repeat_index``-th stop of a role within a day.

    Despite the name this damps stop *count*, not monotony: the discount keys off
    position in the selection order, so it falls on the sixth stop whether that
    stop is excellent or filler. Measured directly -- a pool of two strong stops
    plus five rating-2.4 fillers yields the same 7 stops, the same 5 fillers taken
    and the same 3.06 mean rating at every exponent from 1.0 down to 0.0. Actual
    composition pressure comes from ``_candidate_utility`` (which divides by
    ``1 + 0.6 * repeats`` during expansion) and the ``diversity`` component; do
    not reach for this knob to fix a monotonous day.
    """
    return 1.0 / (max(1, repeat_index) ** ROLE_REPEAT_DISCOUNT_EXPONENT)


def _idle_gap_metrics(
    problem: PlanningProblem,
    activities: Sequence[Dict[str, Any]],
    *,
    day_index: int,
    start_node: Optional[str],
) -> Tuple[int, int]:
    day = problem.request.days[day_index]
    previous_end = day.start_min
    previous_id = start_node
    gaps: List[int] = []
    for activity in sorted(
        (item for item in activities if int(item.get("day_index") or 0) == day_index),
        key=lambda item: (int(item.get("start_min") or 0), str(item.get("candidate_id") or "")),
    ):
        candidate_id = str(activity.get("candidate_id") or "")
        travel = _travel(problem, previous_id, candidate_id)
        gaps.append(max(0, int(activity.get("start_min") or 0) - previous_end - travel))
        previous_end = int(activity.get("end_min") or previous_end)
        previous_id = candidate_id
    return (max(gaps, default=0), sum(gaps))


def _attraction_preference_match(
    candidates: Sequence[PlanningCandidate],
    requested_values: Sequence[Any],
) -> Tuple[float, FrozenSet[str]]:
    requested = {
        str(value).strip().casefold().replace("-", " ")
        for value in requested_values if str(value).strip()
    }
    matched = set()
    for value in requested:
        aliases = attraction_type_match_tokens(value)
        for candidate in candidates:
            tags = {str(tag).casefold().replace("-", " ") for tag in candidate.tags}
            title = candidate.title.casefold().replace("-", " ")
            if any(alias in tags or alias in title for alias in aliases):
                matched.add(value)
                break
    return (len(matched) / len(requested) if requested else 0.0, frozenset(matched))


def _route_objective(
    state: _State,
    problem: PlanningProblem,
    report: Any,
    by_id: Optional[Dict[str, PlanningCandidate]] = None,
) -> Tuple[Tuple[Any, ...], Dict[str, Any]]:
    if by_id is None:
        by_id = {candidate.id: candidate for candidate in problem.candidates}
    selected = [by_id[str(activity["candidate_id"])] for activity in state.activities]
    requested = problem.request.soft_preferences.get("attraction_types") or []
    preference_match, matched = _attraction_preference_match(selected, requested)
    preferred_meals = _meal_names_for_day(
        problem.request.soft_preferences.get("suggested_meals"),
        problem.request.days[0].day_index,
    )
    meal_preference_coverage = (
        len(preferred_meals & state.satisfied_meals) / len(preferred_meals)
        if preferred_meals else 1.0
    )
    role_families = {candidate.role for candidate in selected}
    category_families = {
        value for value in matched
    }
    diversity = len(role_families) + 0.25 * len(category_families)
    role_counts: Dict[str, int] = {}
    quality_parts = []
    for candidate in selected:
        role_counts[candidate.role] = role_counts.get(candidate.role, 0) + 1
        quality_parts.append(
            _calibrated_quality(candidate) * _role_repeat_discount(role_counts[candidate.role])
        )
    quality = (sum(quality_parts) / len(quality_parts) if quality_parts else 0.0)
    budget_limit = problem.request.budget.amount if problem.request.budget.mode == "limited" else None
    budget_margin = (
        float(budget_limit) - float(state.spend_max)
        if budget_limit is not None and state.spend_max is not None else 0.0
    )
    day = problem.request.days[0]
    window_min = max(1, day.end_min - day.start_min)
    # Friction is denominated against window_min, so it has to be computed after it.
    transition_friction = _transition_friction(len(selected) - 1, window_min)
    quality_score = quality - transition_friction
    activity_min = sum(
        max(0, int(activity["end_min"]) - int(activity["start_min"]))
        for activity in state.activities
    )
    end_node = "anchor:end" if problem.request.anchors.get("end") else None
    return_travel = _travel(problem, state.last_id, end_node) if end_node else 0
    total_travel = state.travel_min + return_travel
    tail_slack_min = max(0, day.end_min - state.current_min - return_travel)
    unallocated_min = max(0, window_min - activity_min - total_travel)
    active_time_min = activity_min + state.wait_min
    time_utilization = activity_min / active_time_min if active_time_min else 0.0
    window_utilization = activity_min / window_min
    max_idle_gap_min, idle_gap_min = _idle_gap_metrics(
        problem,
        state.activities,
        day_index=day.day_index,
        start_node="anchor:start" if problem.request.anchors.get("start") else None,
    )
    pace = str(problem.request.soft_preferences.get("pace") or "balanced")
    allowed_idle_gap_min = PACE_MAX_IDLE_GAP.get(pace, PACE_MAX_IDLE_GAP["balanced"])
    avoidable_idle_min = max(0, max_idle_gap_min - allowed_idle_gap_min)
    signature = tuple(candidate.id for candidate in selected)
    components = {
        "primary_experience_share": report.metrics["primary_experience_share"],
        "preference_match": round(preference_match, 4),
        "meal_preference_coverage": round(meal_preference_coverage, 4),
        "diversity": round(diversity, 4),
        "time_utilization": round(time_utilization, 6),
        "planning_window_utilization": round(window_utilization, 6),
        "planning_window_min": window_min,
        "scheduled_activity_min": activity_min,
        "unallocated_min": unallocated_min,
        "tail_slack_min": tail_slack_min,
        "idle_gap_min": idle_gap_min,
        "max_idle_gap_min": max_idle_gap_min,
        "allowed_idle_gap_min": allowed_idle_gap_min,
        "avoidable_idle_min": avoidable_idle_min,
        "calibrated_quality": round(quality_score, 6),
        "uncertainty_count": len(state.uncertainties),
        "travel_wait_min": total_travel + state.wait_min,
        "travel_share": round(total_travel / window_min, 6),
        "budget_margin": round(budget_margin, 2),
        "transition_friction": round(transition_friction, 4),
    }
    components["schedule_quality"] = round(
        components["calibrated_quality"]
        + WINDOW_UTILIZATION_WEIGHT * components["planning_window_utilization"]
        + 0.4 * components["time_utilization"]
        + 0.25 * components["meal_preference_coverage"]
        - 2.0 * (avoidable_idle_min / window_min)
        - TRAVEL_SHARE_WEIGHT * components["travel_share"],
        6,
    )
    key = (
        -components["primary_experience_share"],
        -components["preference_match"],
        -components["schedule_quality"],
        components["max_idle_gap_min"],
        -components["planning_window_utilization"],
        -components["calibrated_quality"],
        -components["meal_preference_coverage"],
        -components["diversity"],
        components["uncertainty_count"],
        components["travel_wait_min"],
        -components["budget_margin"],
        signature,
    )
    return key, components


def _must_visit_requirements(problem: PlanningProblem) -> Tuple[FrozenSet[str], Tuple[str, ...]]:
    values = problem.request.hard_constraints.get("must_visit") or ()
    normalized = {
        str(value).strip().casefold(): str(value).strip()
        for value in values if str(value).strip()
    }
    ids = {
        candidate.id
        for candidate in problem.candidates
        if candidate.id.casefold() in normalized or candidate.title.strip().casefold() in normalized
    }
    matched_names = {
        token for candidate in problem.candidates for token in normalized
        if candidate.id.casefold() == token or candidate.title.strip().casefold() == token
    }
    unresolved = tuple(sorted(normalized[token] for token in normalized.keys() - matched_names))
    return frozenset(ids), unresolved


def _must_visit_ids(problem: PlanningProblem) -> FrozenSet[str]:
    return _must_visit_requirements(problem)[0]


def _excluded_candidate_ids(problem: PlanningProblem) -> FrozenSet[str]:
    values = {
        str(value).strip().casefold().replace("-", " ")
        for value in problem.request.hard_constraints.get("exclude") or ()
        if str(value).strip()
    }
    return frozenset(
        candidate.id for candidate in problem.candidates
        if candidate.id.casefold().replace("-", " ") in values
        or candidate.title.strip().casefold().replace("-", " ") in values
        or bool(values & {tag.casefold().replace("-", " ") for tag in candidate.tags})
    )


def _state_key(
    state: _State,
    required_meals: FrozenSet[str],
    must_ids: FrozenSet[str],
    preferred_meals: FrozenSet[str] = frozenset(),
) -> Tuple[Any, ...]:
    missing = len(required_meals - state.satisfied_meals) + len(must_ids - state.used)
    missing_preferences = len(preferred_meals - state.satisfied_meals)
    signature = tuple(activity["candidate_id"] for activity in state.activities)
    return (
        missing,
        -round(state.utility, 6),
        state.travel_min + state.wait_min,
        missing_preferences,
        len(state.uncertainties),
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


def _internal_meal_children(problem: PlanningProblem, parent_id: str) -> List[PlanningCandidate]:
    return sorted(
        (
            candidate for candidate in problem.candidates
            if candidate.parent_id == parent_id
            and candidate.access == "gated"
            and candidate.role == "food"
        ),
        key=lambda candidate: (-candidate.provider_relevance, candidate.id),
    )


def _meal_names_for_day(values: Any, day_index: int) -> FrozenSet[str]:
    names = set()
    for value in values or ():
        if isinstance(value, dict):
            try:
                applies = int(value.get("day_index", 0)) == day_index
            except (TypeError, ValueError):
                applies = False
            name = str(value.get("meal") or "").strip()
            if applies and name:
                names.add(name)
        else:
            name = str(value or "").strip()
            if day_index == 0 and name:
                names.add(name)
    return frozenset(names)


class BeamItinerarySolver(ItinerarySolver):
    def __init__(self, *, beam_width: int = 48) -> None:
        self.beam_width = max(1, beam_width)

    def _solve_multi_day(self, problem: PlanningProblem) -> SolverResult:
        request = problem.request
        pace = str(request.soft_preferences.get("pace") or "balanced")
        style = str(request.soft_preferences.get("style") or "sightseeing")
        policy = style_policy(style)
        per_day_cap = PACE_MAX_STOPS.get(pace, PACE_MAX_STOPS["balanced"])
        budget_limit = request.budget.amount if request.budget.mode == "limited" else None
        budget_currency = request.budget.currency if request.budget.mode == "limited" else None
        must_ids, unresolved_must = _must_visit_requirements(problem)
        excluded_ids = _excluded_candidate_ids(problem)
        if unresolved_must:
            return SolverResult(
                status="infeasible",
                activities=(),
                cost_summary={
                    "min": 0.0, "max": 0.0, "currency": budget_currency,
                    "budget_limit": budget_limit, "budget_status": "infeasible",
                },
                unsatisfied_constraints=tuple(
                    {"code": "must_visit_unavailable", "value": value}
                    for value in unresolved_must
                ),
                diagnostics={
                    "strategy": "bounded_multi_day_beam_search",
                    "expanded_states": 0,
                    "beam_width": self.beam_width,
                    "day_count": len(request.days),
                },
            )
        fixed_day_candidates = {
            str(candidate_id): int(day_index)
            for candidate_id, day_index in (
                request.hard_constraints.get("fixed_day_candidates") or {}
            ).items()
            if str(candidate_id).strip()
        }
        must_ids = frozenset(set(must_ids) | set(fixed_day_candidates))
        conflicting_ids = must_ids & excluded_ids
        if conflicting_ids:
            return SolverResult(
                status="infeasible",
                activities=(),
                cost_summary={
                    "min": 0.0, "max": 0.0, "currency": budget_currency,
                    "budget_limit": budget_limit, "budget_status": "infeasible",
                },
                unsatisfied_constraints=tuple(
                    {"code": "conflicting_explicit_constraints", "candidate_id": candidate_id}
                    for candidate_id in sorted(conflicting_ids)
                ),
                diagnostics={
                    "strategy": "bounded_multi_day_beam_search",
                    "expanded_states": 0,
                    "beam_width": self.beam_width,
                    "day_count": len(request.days),
                },
            )
        day_candidate_options = {
            int(day_index): frozenset(str(candidate_id) for candidate_id in candidate_ids)
            for day_index, candidate_ids in (
                request.hard_constraints.get("day_candidate_options") or {}
            ).items()
        }
        option_day_by_id = {
            candidate_id: day_index
            for day_index, candidate_ids in day_candidate_options.items()
            for candidate_id in candidate_ids
        }

        available_lodging = []
        for scenario in problem.lodging_scenarios:
            cost = scenario.trip_cost_per_person
            same_currency = (
                not budget_currency
                or not cost.currency
                or str(cost.currency).upper() == str(budget_currency).upper()
            )
            if (
                budget_limit is not None
                and same_currency
                and cost.min is not None
                and float(cost.min) > float(budget_limit)
            ):
                continue
            available_lodging.append(scenario)
        if not available_lodging:
            return SolverResult(
                status="infeasible",
                activities=(),
                cost_summary={
                    "min": 0.0,
                    "max": 0.0,
                    "currency": budget_currency,
                    "budget_limit": budget_limit,
                    "budget_status": "infeasible",
                },
                unsatisfied_constraints=({"code": "lodging_unavailable_or_over_budget"},),
                diagnostics={
                    "strategy": "bounded_multi_day_beam_search",
                    "expanded_states": 0,
                    "beam_width": self.beam_width,
                    "day_count": len(request.days),
                },
            )
        selected_lodging = available_lodging[0]
        lodging = selected_lodging.to_dict()
        lodging_node = f"lodging:{selected_lodging.candidate_id}"
        lodging_cost = selected_lodging.trip_cost_per_person
        base_uncertainties: Tuple[Dict[str, Any], ...] = ()
        if (
            lodging_cost.min is None
            or lodging_cost.max is None
            or (
                budget_currency
                and str(lodging_cost.currency or "").upper() != str(budget_currency).upper()
            )
        ):
            base_spend_min = 0.0
            base_spend_max: Optional[float] = None
            base_uncertainties = ({
                "code": "lodging_cost_unknown",
                "candidate_id": selected_lodging.candidate_id,
            },)
        else:
            base_spend_min = float(lodging_cost.min)
            base_spend_max = float(lodging_cost.max)

        first_day = request.days[0]
        beam: List[_TripState] = [_TripState(
            day_index=0,
            current_min=first_day.start_min,
            last_id=lodging_node,
            spend_min=base_spend_min,
            spend_max=base_spend_max,
            uncertainties=base_uncertainties,
        )]
        finals: List[_TripState] = []
        expanded = 0
        total_depth = per_day_cap * len(request.days) + len(request.days) - 1

        def state_key(state: _TripState) -> Tuple[Any, ...]:
            required = _meal_names_for_day(
                request.hard_constraints.get("meal_obligations"), state.day_index
            )
            preferred = _meal_names_for_day(
                request.soft_preferences.get("suggested_meals"), state.day_index
            )
            missing = len(required - state.satisfied_meals)
            missing_preferences = len(preferred - state.satisfied_meals)
            signature = tuple(
                (int(activity.get("day_index") or 0), str(activity.get("candidate_id") or ""))
                for activity in state.activities
            )
            return (
                -state.day_index,
                missing,
                -state.day_primary_count,
                -round(state.utility, 6),
                state.travel_min + state.wait_min,
                missing_preferences,
                len(state.uncertainties),
                state.current_min,
                signature,
            )

        for _depth in range(total_depth):
            next_states: List[_TripState] = []
            for state in beam:
                day = request.days[state.day_index]
                required_meals = _meal_names_for_day(
                    request.hard_constraints.get("meal_obligations"), state.day_index
                )
                preferred_meals = _meal_names_for_day(
                    request.soft_preferences.get("suggested_meals"), state.day_index
                )
                target_meals = required_meals | preferred_meals
                day_ready = (
                    state.day_stop_count > 0
                    and required_meals <= state.satisfied_meals
                    and (
                        not day_candidate_options.get(state.day_index)
                        or bool(day_candidate_options[state.day_index] & state.used)
                    )
                )
                if state.day_index == len(request.days) - 1 and day_ready and must_ids <= state.used:
                    return_to_hotel = _travel(problem, state.last_id, lodging_node)
                    if state.current_min + return_to_hotel <= day.end_min:
                        finals.append(state)
                elif state.day_index < len(request.days) - 1 and day_ready:
                    return_to_hotel = _travel(problem, state.last_id, lodging_node)
                    hotel_arrival = state.current_min + return_to_hotel
                    if hotel_arrival <= day.end_min:
                        next_day = request.days[state.day_index + 1]
                        next_states.append(_TripState(
                            day_index=state.day_index + 1,
                            current_min=next_day.start_min,
                            last_id=lodging_node,
                            used=state.used,
                            activities=state.activities,
                            spend_min=state.spend_min,
                            spend_max=state.spend_max,
                            utility=state.utility,
                            travel_min=state.travel_min + return_to_hotel,
                            wait_min=state.wait_min,
                            tail_slack_min=state.tail_slack_min + max(0, day.end_min - hotel_arrival),
                            completed_day_travel=state.completed_day_travel + (
                                state.current_day_travel + return_to_hotel,
                            ),
                            completed_day_wait=state.completed_day_wait + (state.current_day_wait,),
                            uncertainties=state.uncertainties,
                        ))

                if state.day_stop_count >= per_day_cap:
                    continue
                for candidate in problem.candidates:
                    if candidate.id in state.used or candidate.id in excluded_ids or candidate.access == "gated":
                        continue
                    assigned_day = fixed_day_candidates.get(
                        candidate.id, option_day_by_id.get(candidate.id)
                    )
                    if assigned_day is not None and assigned_day != state.day_index:
                        continue
                    if candidate.duration.preferred <= 0:
                        continue
                    travel = _travel(problem, state.last_id, candidate.id)
                    arrival = state.current_min + travel
                    earliest = arrival
                    unsatisfied_meals = sorted(target_meals - state.satisfied_meals)
                    if candidate.role == "food" and policy.meals_only_food and not unsatisfied_meals:
                        continue
                    if candidate.domain == "restaurant" and unsatisfied_meals:
                        meal = min(unsatisfied_meals, key=lambda name: MEAL_WINDOWS.get(name, (0, 0))[0])
                        earliest = max(earliest, MEAL_WINDOWS.get(meal, (earliest, earliest))[0])
                    start = _availability_start(
                        candidate,
                        earliest,
                        candidate.duration.preferred,
                        state.day_index,
                    )
                    return_travel = _travel(problem, candidate.id, lodging_node)
                    if start is None or start + candidate.duration.preferred + return_travel > day.end_min:
                        continue
                    spend_min, spend_max, cost_uncertainty = _budget_add(
                        state, candidate, budget_currency
                    )
                    end = start + candidate.duration.preferred
                    meals_before = set(state.satisfied_meals)
                    meals = set(state.satisfied_meals)
                    meals.update(candidate.meal_coverage)
                    sub_activities: List[Dict[str, Any]] = []
                    used_children: set[str] = set()
                    for meal in sorted(target_meals - meals):
                        window_start, window_end = MEAL_WINDOWS.get(meal, (0, 0))
                        if not (start < window_end and end > window_start):
                            continue
                        child = next(
                            (
                                item for item in _internal_meal_children(problem, candidate.id)
                                if item.id not in state.used and item.id not in used_children
                            ),
                            None,
                        )
                        if child is None:
                            continue
                        child_state = _TripState(
                            day_index=state.day_index,
                            current_min=end,
                            last_id=candidate.id,
                            spend_min=spend_min,
                            spend_max=spend_max,
                        )
                        spend_min, spend_max, child_uncertainty = _budget_add(
                            child_state, child, budget_currency
                        )
                        if child_uncertainty is not None:
                            cost_uncertainty = child_uncertainty
                        meals.add(meal)
                        used_children.add(child.id)
                        sub_activities.append({
                            "candidate_id": child.id,
                            "title": child.title,
                            "role": child.role,
                            "parent_id": candidate.id,
                            "meal": meal,
                            "cost": {
                                "min": child.cost.min,
                                "max": child.cost.max,
                                "currency": child.cost.currency,
                                "source": child.cost.source,
                            },
                        })
                    if budget_limit is not None and spend_min > budget_limit:
                        continue
                    if candidate.domain == "restaurant":
                        for meal, (window_start, window_end) in MEAL_WINDOWS.items():
                            if meal in target_meals and window_start <= start <= window_end:
                                meals.add(meal)
                    uncertainties = list(state.uncertainties)
                    if not candidate.availability_known:
                        uncertainties.append({
                            "code": "opening_hours_unknown",
                            "candidate_id": candidate.id,
                            "day_index": state.day_index,
                        })
                    if candidate.duration.confidence < 0.6:
                        uncertainties.append({
                            "code": "duration_uncertain",
                            "candidate_id": candidate.id,
                        })
                    if budget_limit is not None and cost_uncertainty is not None:
                        uncertainties.append(cost_uncertainty)
                    wait = max(0, start - arrival)
                    activity = {
                        "day_index": state.day_index,
                        "candidate_id": candidate.id,
                        "domain": candidate.domain,
                        "role": candidate.role,
                        "is_compound": candidate.is_compound,
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
                        "satisfied_meals": sorted(meals - meals_before),
                        "sub_activities": sub_activities,
                        "item": dict(candidate.item),
                    }
                    next_states.append(_TripState(
                        day_index=state.day_index,
                        current_min=end,
                        last_id=candidate.id,
                        used=state.used | {candidate.id} | used_children,
                        satisfied_meals=frozenset(meals),
                        activities=state.activities + (activity,),
                        spend_min=spend_min,
                        spend_max=spend_max,
                        utility=state.utility + _candidate_utility(candidate, state) - 0.012 * travel - 0.004 * wait,
                        travel_min=state.travel_min + travel,
                        wait_min=state.wait_min + wait,
                        tail_slack_min=state.tail_slack_min,
                        day_stop_count=state.day_stop_count + 1,
                        day_primary_count=state.day_primary_count + int(candidate.role in policy.primary_roles),
                        completed_day_travel=state.completed_day_travel,
                        completed_day_wait=state.completed_day_wait,
                        current_day_travel=state.current_day_travel + travel,
                        current_day_wait=state.current_day_wait + wait,
                        uncertainties=tuple(uncertainties),
                    ))
                    expanded += 1
            if not next_states:
                break
            dominant: Dict[Tuple[Any, ...], _TripState] = {}
            for state in next_states:
                key = (
                    state.day_index,
                    state.last_id,
                    state.current_min // 15,
                    state.satisfied_meals,
                    frozenset(must_ids & state.used),
                    state.day_stop_count,
                    len(state.activities),
                )
                previous = dominant.get(key)
                if previous is None or state_key(state) < state_key(previous):
                    dominant[key] = state
            _ranked = sorted(dominant.values(), key=state_key)
            PROBE["trim"].append({"tag": "multi", "generated": len(next_states), "after_agg": len(dominant), "kept": min(len(dominant), self.beam_width), "width": self.beam_width})
            if len(_ranked) > 1:
                PROBE["beamtie"].append({"tag": "multi", "decided_at": _tie_depth(state_key(_ranked[0]), state_key(_ranked[1]))})
            beam = _ranked[:self.beam_width]

        by_id = {candidate.id: candidate for candidate in problem.candidates}
        final_rows: List[Tuple[Tuple[Any, ...], _TripState, Dict[str, Any]]] = []
        policy_failures: List[Dict[str, Any]] = []
        for state in finals:
            report = validate_activity_policy(request, state.activities, problem.candidates)
            if report.status != "valid":
                policy_failures.extend(report.violations)
                continue
            final_day = request.days[-1]
            return_travel = _travel(problem, state.last_id, lodging_node)
            activity_minutes = sum(
                max(0, int(item["end_min"]) - int(item["start_min"]))
                for item in state.activities
            )
            window_minutes = sum(day.end_min - day.start_min for day in request.days)
            total_travel = state.travel_min + return_travel
            day_activity = [
                sum(
                    max(0, int(item["end_min"]) - int(item["start_min"]))
                    for item in state.activities if int(item.get("day_index") or 0) == day.day_index
                )
                for day in request.days
            ]
            daily_utilization = [
                minutes / max(1, day.end_min - day.start_min)
                for minutes, day in zip(day_activity, request.days)
            ]
            selected = [by_id[item["candidate_id"]] for item in state.activities]
            quality_parts = [_calibrated_quality(candidate) for candidate in selected]
            quality = sum(quality_parts) / len(quality_parts) if quality_parts else 0.0
            # window_minutes is the whole-trip sum, which is also the denominator
            # planning_window_utilization uses; charging a flat cost against it
            # made the bar for an extra stop rise with every added day.
            transition_friction = _transition_friction(
                sum(
                    max(0, sum(1 for item in state.activities if item.get("day_index") == day.day_index) - 1)
                    for day in request.days
                ),
                window_minutes,
            )
            preference_match, _matched = _attraction_preference_match(
                selected,
                request.soft_preferences.get("attraction_types") or [],
            )
            preferred_meals = {
                (day.day_index, meal)
                for day in request.days
                for meal in _meal_names_for_day(
                    request.soft_preferences.get("suggested_meals"), day.day_index
                )
            }
            covered_meals = {
                (int(activity.get("day_index") or 0), meal)
                for activity in state.activities
                for meal in (
                    set(activity.get("satisfied_meals") or ())
                    | set(activity.get("meal_coverage") or ())
                )
            }
            meal_preference_coverage = (
                len(preferred_meals & covered_meals) / len(preferred_meals)
                if preferred_meals else 1.0
            )
            diversity = len({candidate.role for candidate in selected})
            tail_slack = state.tail_slack_min + max(
                0, final_day.end_min - state.current_min - return_travel
            )
            daily_idle = [
                _idle_gap_metrics(
                    problem,
                    state.activities,
                    day_index=day.day_index,
                    start_node=lodging_node,
                )
                for day in request.days
            ]
            allowed_idle_gap_min = PACE_MAX_IDLE_GAP.get(
                pace, PACE_MAX_IDLE_GAP["balanced"]
            )
            max_idle_gap_min = max((row[0] for row in daily_idle), default=0)
            avoidable_idle_min = sum(
                max(0, row[0] - allowed_idle_gap_min) for row in daily_idle
            )
            components = {
                "primary_experience_share": report.metrics["primary_experience_share"],
                "preference_match": round(preference_match, 4),
                "meal_preference_coverage": round(meal_preference_coverage, 4),
                "diversity": diversity,
                "daily_utilization": [round(value, 6) for value in daily_utilization],
                "minimum_daily_utilization": round(min(daily_utilization), 6),
                "planning_window_utilization": round(activity_minutes / max(1, window_minutes), 6),
                "planning_window_min": window_minutes,
                "scheduled_activity_min": activity_minutes,
                "unallocated_min": max(0, window_minutes - activity_minutes - total_travel),
                "tail_slack_min": tail_slack,
                "idle_gap_min": sum(row[1] for row in daily_idle),
                "max_idle_gap_min": max_idle_gap_min,
                "allowed_idle_gap_min": allowed_idle_gap_min,
                "avoidable_idle_min": avoidable_idle_min,
                "calibrated_quality": round(quality - transition_friction, 6),
                "uncertainty_count": len(state.uncertainties),
                "travel_wait_min": total_travel + state.wait_min,
                "travel_share": round(total_travel / max(1, window_minutes), 6),
                "transition_friction": round(transition_friction, 4),
            }
            components["schedule_quality"] = round(
                components["calibrated_quality"]
                + WINDOW_UTILIZATION_WEIGHT * components["planning_window_utilization"]
                + 0.4 * (
                    components["scheduled_activity_min"]
                    / max(1, components["scheduled_activity_min"] + state.wait_min)
                )
                + 0.25 * components["meal_preference_coverage"]
                - 2.0 * (avoidable_idle_min / max(1, window_minutes))
                - TRAVEL_SHARE_WEIGHT * components["travel_share"],
                6,
            )
            signature = tuple(
                (int(item.get("day_index") or 0), str(item.get("candidate_id") or ""))
                for item in state.activities
            )
            key = (
                -components["primary_experience_share"],
                -components["preference_match"],
                -components["schedule_quality"],
                components["max_idle_gap_min"],
                -components["minimum_daily_utilization"],
                -components["calibrated_quality"],
                -components["meal_preference_coverage"],
                -components["diversity"],
                components["uncertainty_count"],
                components["travel_wait_min"],
                signature,
            )
            final_rows.append((key, state, components))

        if not final_rows:
            unsatisfied = list(policy_failures[:8])
            if beam:
                closest = min(beam, key=state_key)
                required = _meal_names_for_day(
                    request.hard_constraints.get("meal_obligations"), closest.day_index
                )
                unsatisfied.extend(
                    {"code": "meal_obligation", "day_index": closest.day_index, "meal": meal}
                    for meal in sorted(required - closest.satisfied_meals)
                )
                unsatisfied.extend(
                    {"code": "must_visit", "candidate_id": candidate_id}
                    for candidate_id in sorted(must_ids - closest.used)
                )
                options = day_candidate_options.get(closest.day_index, frozenset())
                if options and not options & closest.used:
                    unsatisfied.append({
                        "code": "day_candidate_option",
                        "day_index": closest.day_index,
                    })
            if not unsatisfied:
                unsatisfied.append({"code": "no_feasible_multi_day_route"})
            return SolverResult(
                status="infeasible",
                activities=(),
                cost_summary={
                    "min": base_spend_min,
                    "max": base_spend_max,
                    "currency": budget_currency,
                    "budget_limit": budget_limit,
                    "budget_status": "infeasible",
                },
                unsatisfied_constraints=tuple(unsatisfied),
                diagnostics={
                    "strategy": "bounded_multi_day_beam_search",
                    "expanded_states": expanded,
                    "beam_width": self.beam_width,
                    "day_count": len(request.days),
                },
                lodging=lodging,
            )
        _record_final(final_rows, "multi")
        _key, winner, components = min(final_rows, key=lambda row: row[0])
        return_travel = _travel(problem, winner.last_id, lodging_node)
        components.update(compute_route_quality_metrics(
            travel_minutes=problem.travel_minutes,
            day_routes=[{
                "day_index": day.day_index,
                "activity_ids": [
                    str(activity.get("candidate_id") or "")
                    for activity in winner.activities
                    if int(activity.get("day_index") or 0) == day.day_index
                ],
                "start_id": lodging_node,
                "end_id": lodging_node,
                "window_min": day.end_min - day.start_min,
            } for day in request.days],
            activities=winner.activities,
            meal_windows=MEAL_WINDOWS,
        ))
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
                "strategy": "bounded_multi_day_beam_search",
                "beam_width": self.beam_width,
                "expanded_states": expanded,
                "selected_stops": len(winner.activities),
                "day_count": len(request.days),
                "travel_min": winner.travel_min + return_travel,
                "wait_min": winner.wait_min,
                "utility": round(winner.utility, 6),
                "daily_travel_min": list(winner.completed_day_travel) + [
                    winner.current_day_travel + return_travel
                ],
                "daily_wait_min": list(winner.completed_day_wait) + [winner.current_day_wait],
                "objective_order": [
                    "hard_constraints", "must_visit", "primary_experience_share",
                    "preference_match", "schedule_quality", "max_idle_gap",
                    "daily_time_utilization", "calibrated_quality",
                    "meal_preference_coverage", "diversity", "uncertainty",
                    "travel_wait", "budget_margin", "stable_id",
                ],
                "objective_components": components,
            },
            lodging=lodging,
        )

    def solve(self, problem: PlanningProblem) -> SolverResult:
        request = problem.request
        if len(request.days) > 1:
            return self._solve_multi_day(problem)
        day = request.days[0]
        required_meals = _meal_names_for_day(
            request.hard_constraints.get("meal_obligations"),
            day.day_index,
        )
        preferred_meals = _meal_names_for_day(
            request.soft_preferences.get("suggested_meals"),
            day.day_index,
        )
        target_meals = required_meals | preferred_meals
        must_ids, unresolved_must = _must_visit_requirements(problem)
        excluded_ids = _excluded_candidate_ids(problem)
        day_options = request.hard_constraints.get("day_candidate_options") or {}
        required_day_options = frozenset(
            str(candidate_id)
            for candidate_id in day_options.get(str(day.day_index), day_options.get(day.day_index, ()))
        )

        def single_day_state_key(state: _State) -> tuple:
            missing_day_option = int(bool(required_day_options) and not bool(required_day_options & state.used))
            return (
                missing_day_option,
                *_state_key(state, required_meals, must_ids, preferred_meals),
            )

        pace = str(request.soft_preferences.get("pace") or "balanced")
        style = str(request.soft_preferences.get("style") or "sightseeing")
        policy = style_policy(style)
        max_stops = PACE_MAX_STOPS.get(pace, PACE_MAX_STOPS["balanced"])
        budget_limit = request.budget.amount if request.budget.mode == "limited" else None
        budget_currency = request.budget.currency if request.budget.mode == "limited" else None
        if unresolved_must:
            return SolverResult(
                status="infeasible",
                activities=(),
                cost_summary={
                    "min": 0.0, "max": 0.0, "currency": budget_currency,
                    "budget_limit": budget_limit, "budget_status": "infeasible",
                },
                unsatisfied_constraints=tuple(
                    {"code": "must_visit_unavailable", "value": value}
                    for value in unresolved_must
                ),
                diagnostics={
                    "strategy": "bounded_beam_search",
                    "expanded_states": 0,
                    "beam_width": self.beam_width,
                },
            )
        conflicting_ids = must_ids & excluded_ids
        if conflicting_ids:
            return SolverResult(
                status="infeasible",
                activities=(),
                cost_summary={
                    "min": 0.0, "max": 0.0, "currency": budget_currency,
                    "budget_limit": budget_limit, "budget_status": "infeasible",
                },
                unsatisfied_constraints=tuple(
                    {"code": "conflicting_explicit_constraints", "candidate_id": candidate_id}
                    for candidate_id in sorted(conflicting_ids)
                ),
                diagnostics={
                    "strategy": "bounded_beam_search",
                    "expanded_states": 0,
                    "beam_width": self.beam_width,
                },
            )
        lodging = None
        base_spend_min = 0.0
        base_spend_max: Optional[float] = 0.0
        base_uncertainties: Tuple[Dict[str, Any], ...] = ()
        if request.lodging is not None and request.lodging.nights > 0:
            available_lodging = []
            for scenario in problem.lodging_scenarios:
                cost = scenario.trip_cost_per_person
                same_currency = (
                    not budget_currency
                    or not cost.currency
                    or str(cost.currency).upper() == str(budget_currency).upper()
                )
                if (
                    budget_limit is not None
                    and same_currency
                    and cost.min is not None
                    and float(cost.min) > float(budget_limit)
                ):
                    continue
                available_lodging.append(scenario)
            if not available_lodging:
                return SolverResult(
                    status="infeasible",
                    activities=(),
                    cost_summary={
                        "min": 0.0, "max": 0.0, "currency": budget_currency,
                        "budget_limit": budget_limit, "budget_status": "infeasible",
                    },
                    unsatisfied_constraints=({"code": "lodging_unavailable_or_over_budget"},),
                    diagnostics={
                        "strategy": "bounded_beam_search", "expanded_states": 0,
                        "beam_width": self.beam_width,
                    },
                )
            selected_lodging = available_lodging[0]
            lodging = selected_lodging.to_dict()
            lodging_cost = selected_lodging.trip_cost_per_person
            if (
                lodging_cost.min is None
                or lodging_cost.max is None
                or (
                    budget_currency
                    and str(lodging_cost.currency or "").upper() != str(budget_currency).upper()
                )
            ):
                base_spend_max = None
                base_uncertainties = ({
                    "code": "lodging_cost_unknown",
                    "candidate_id": selected_lodging.candidate_id,
                },)
            else:
                base_spend_min = float(lodging_cost.min)
                base_spend_max = float(lodging_cost.max)
        start_node = "anchor:start" if request.anchors.get("start") else None
        end_node = "anchor:end" if request.anchors.get("end") else None
        beam: List[_State] = [_State(
            current_min=day.start_min,
            last_id=start_node,
            spend_min=base_spend_min,
            spend_max=base_spend_max,
            uncertainties=base_uncertainties,
        )]
        finals: List[_State] = []
        expanded = 0

        for _depth in range(max_stops):
            next_states: List[_State] = []
            for state in beam:
                if (
                    state.activities
                    and required_meals <= state.satisfied_meals
                    and must_ids <= state.used
                    and (not required_day_options or bool(required_day_options & state.used))
                ):
                    finals.append(state)
                for candidate in problem.candidates:
                    if candidate.id in state.used or candidate.id in excluded_ids:
                        continue
                    if candidate.access == "gated":
                        continue
                    if candidate.duration.preferred <= 0:
                        continue
                    travel = _travel(problem, state.last_id, candidate.id)
                    arrival = state.current_min + travel
                    earliest = arrival
                    unsatisfied_meals = [meal for meal in target_meals - state.satisfied_meals]
                    if candidate.role == "food" and policy.meals_only_food and not unsatisfied_meals:
                        continue
                    if candidate.domain == "restaurant" and unsatisfied_meals:
                        meal = min(unsatisfied_meals, key=lambda name: MEAL_WINDOWS.get(name, (0, 0))[0])
                        earliest = max(earliest, MEAL_WINDOWS.get(meal, (earliest, earliest))[0])
                    start = _availability_start(candidate, earliest, candidate.duration.preferred)
                    return_travel = _travel(problem, candidate.id, end_node) if end_node else 0
                    if start is None or start + candidate.duration.preferred + return_travel > day.end_min:
                        continue
                    spend_min, spend_max, cost_uncertainty = _budget_add(state, candidate, budget_currency)
                    end = start + candidate.duration.preferred
                    meals_before = set(state.satisfied_meals)
                    meals = set(state.satisfied_meals)
                    meals.update(candidate.meal_coverage)
                    sub_activities: List[Dict[str, Any]] = []
                    used_children: set[str] = set()
                    internal_children = _internal_meal_children(problem, candidate.id)
                    for meal in sorted(target_meals - meals):
                        window_start, window_end = MEAL_WINDOWS.get(meal, (0, 0))
                        if not (start < window_end and end > window_start):
                            continue
                        child = next((item for item in internal_children if item.id not in used_children), None)
                        if child is None:
                            continue
                        child_state = _State(
                            current_min=end,
                            spend_min=spend_min,
                            spend_max=spend_max,
                        )
                        spend_min, spend_max, child_uncertainty = _budget_add(
                            child_state, child, budget_currency
                        )
                        if child_uncertainty is not None:
                            cost_uncertainty = child_uncertainty
                        meals.add(meal)
                        used_children.add(child.id)
                        sub_activities.append({
                            "candidate_id": child.id,
                            "title": child.title,
                            "role": child.role,
                            "parent_id": candidate.id,
                            "meal": meal,
                            "cost": {
                                "min": child.cost.min,
                                "max": child.cost.max,
                                "currency": child.cost.currency,
                                "source": child.cost.source,
                            },
                        })
                    if budget_limit is not None and spend_min > budget_limit:
                        continue
                    if candidate.domain == "restaurant":
                        for meal, (window_start, window_end) in MEAL_WINDOWS.items():
                            if meal in target_meals and window_start <= start <= window_end:
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
                    wait = max(0, start - arrival)
                    activity = {
                        "day_index": 0,
                        "candidate_id": candidate.id,
                        "domain": candidate.domain,
                        "role": candidate.role,
                        "is_compound": candidate.is_compound,
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
                        "satisfied_meals": sorted(meals - meals_before),
                        "sub_activities": sub_activities,
                        "item": dict(candidate.item),
                    }
                    next_states.append(_State(
                        current_min=end,
                        last_id=candidate.id,
                        used=state.used | {candidate.id} | used_children,
                        satisfied_meals=frozenset(meals),
                        activities=state.activities + (activity,),
                        spend_min=spend_min,
                        spend_max=spend_max,
                        utility=state.utility + _candidate_utility(candidate, state) - 0.012 * travel - 0.004 * wait,
                        travel_min=state.travel_min + travel,
                        wait_min=state.wait_min + wait,
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
                if previous is None or single_day_state_key(state) < single_day_state_key(previous):
                    dominant[key] = state
            _ranked = sorted(dominant.values(), key=single_day_state_key)
            PROBE["trim"].append({"tag": "single", "generated": len(next_states), "after_agg": len(dominant), "kept": min(len(dominant), self.beam_width), "width": self.beam_width})
            if len(_ranked) > 1:
                PROBE["beamtie"].append({"tag": "single", "decided_at": _tie_depth(single_day_state_key(_ranked[0]), single_day_state_key(_ranked[1]))})
            beam = _ranked[:self.beam_width]

        finals.extend(
            state for state in beam
            if state.activities
            and required_meals <= state.satisfied_meals
            and must_ids <= state.used
            and (not required_day_options or bool(required_day_options & state.used))
        )
        by_id = {candidate.id: candidate for candidate in problem.candidates}
        policy_failures = []
        policy_valid = []
        for state in finals:
            report = validate_activity_policy(request, state.activities, problem.candidates)
            if report.status == "valid":
                policy_valid.append((state, report))
            else:
                policy_failures.append((state, report))
        if not policy_valid:
            policy_violations = (
                list(min(policy_failures, key=lambda row: single_day_state_key(row[0]))[1].violations)
                if policy_failures else []
            )
            closest = min(beam, key=single_day_state_key) if beam else None
            missing_meals = required_meals - (
                closest.satisfied_meals if closest is not None else frozenset()
            )
            missing_must = must_ids - (closest.used if closest is not None else frozenset())
            missing_day_option = bool(
                required_day_options
                and (closest is None or not required_day_options & closest.used)
            )
            return SolverResult(
                status="infeasible",
                activities=(),
                cost_summary={
                    "min": 0.0, "max": 0.0, "currency": budget_currency,
                    "budget_limit": budget_limit, "budget_status": "infeasible",
                },
                unsatisfied_constraints=tuple(
                    policy_violations
                    + [{"code": "meal_obligation", "value": meal} for meal in sorted(missing_meals)]
                    + [{"code": "must_visit", "candidate_id": item_id} for item_id in sorted(missing_must)]
                    + ([{"code": "day_candidate_option", "day_index": day.day_index}]
                       if missing_day_option else [])
                    + ([{"code": "no_feasible_route"}]
                       if not policy_violations and not missing_meals and not missing_must
                       and not missing_day_option else [])
                ),
                diagnostics={"strategy": "bounded_beam_search", "expanded_states": expanded, "beam_width": self.beam_width},
                lodging=lodging,
            )
        scored_finals = []
        for state, report in policy_valid:
            key, components = _route_objective(state, problem, report, by_id)
            scored_finals.append((key, state, components))
        _record_final(scored_finals, "single")
        _, winner, objective_components = min(scored_finals, key=lambda row: row[0])
        return_travel = _travel(problem, winner.last_id, end_node) if end_node else 0
        objective_components.update(compute_route_quality_metrics(
            travel_minutes=problem.travel_minutes,
            day_routes=[{
                "day_index": day.day_index,
                "activity_ids": [
                    str(activity.get("candidate_id") or "")
                    for activity in winner.activities
                ],
                "start_id": start_node,
                "end_id": end_node,
                "window_min": day.end_min - day.start_min,
            }],
            activities=winner.activities,
            meal_windows=MEAL_WINDOWS,
        ))
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
                "travel_min": winner.travel_min + return_travel,
                "outbound_anchor": bool(start_node),
                "return_anchor": bool(end_node),
                "wait_min": winner.wait_min,
                "utility": round(winner.utility, 6),
                "objective_order": [
                    "hard_constraints", "primary_experience_share", "preference_match",
                    "schedule_quality", "max_idle_gap", "planning_window_utilization",
                    "calibrated_quality", "meal_preference_coverage", "diversity",
                    "uncertainty", "travel_wait",
                    "budget_margin", "stable_id",
                ],
                "objective_components": objective_components,
            },
            lodging=lodging,
        )


def build_solver(name: str = "beam") -> ItinerarySolver:
    if str(name or "beam").strip().lower() != "beam":
        raise ValueError(f"Unsupported itinerary solver: {name}")
    return BeamItinerarySolver()
