"""Provider-free contracts for itinerary planning and solver adapters.

The structures in this module intentionally contain only serializable values.
Provider clients and LLM responses must be normalized before they cross this
boundary, allowing another solver implementation to consume the same problem.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date as date_type
from typing import Any, Dict, List, Optional, Protocol, Tuple

PLANNING_SCHEMA_VERSION = "itinerary-ir/v1"
PLANNING_STATUSES = {"feasible", "indeterminate", "infeasible"}
EVIDENCE_SOURCES = {"user", "profile", "system", "provider", "registry", "rule", "llm", "unknown"}


@dataclass(frozen=True)
class LocationConstraint:
    query: str
    resolved_name: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    timezone: Optional[str] = None
    source: str = "user"


@dataclass(frozen=True)
class DayConstraint:
    day_index: int
    date: str
    start_min: int
    end_min: int


@dataclass(frozen=True)
class BudgetConstraint:
    mode: str
    amount: Optional[float] = None
    currency: Optional[str] = None
    basis: str = "per_person"
    include_lodging: bool = False


@dataclass(frozen=True)
class AnchorConstraint:
    query: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    provider_id: Optional[str] = None


@dataclass(frozen=True)
class ItineraryPlanningRequest:
    location: LocationConstraint
    days: Tuple[DayConstraint, ...]
    budget: BudgetConstraint
    anchors: Dict[str, AnchorConstraint] = field(default_factory=dict)
    hard_constraints: Dict[str, Any] = field(default_factory=dict)
    soft_preferences: Dict[str, Any] = field(default_factory=dict)
    explicit_fields: Tuple[str, ...] = ()
    schema_version: str = PLANNING_SCHEMA_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AvailabilityWindow:
    day_index: int
    start_min: int
    end_min: int


@dataclass(frozen=True)
class DurationEstimate:
    min: int
    preferred: int
    max: int
    source: str
    confidence: float


@dataclass(frozen=True)
class CostEstimate:
    min: Optional[float]
    max: Optional[float]
    currency: Optional[str]
    components: Tuple[str, ...] = ()
    source: str = "unknown"
    confidence: float = 0.0


@dataclass(frozen=True)
class PlanningCandidate:
    id: str
    domain: str
    title: str
    latitude: float
    longitude: float
    duration: DurationEstimate
    cost: CostEstimate
    availability_windows: Tuple[AvailabilityWindow, ...] = ()
    availability_known: bool = False
    meal_coverage: Tuple[str, ...] = ()
    tags: Tuple[str, ...] = ()
    provider_relevance: float = 0.0
    rating: Optional[float] = None
    source: Optional[str] = None
    item: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PlanningProblem:
    request: ItineraryPlanningRequest
    candidates: Tuple[PlanningCandidate, ...]
    travel_minutes: Dict[str, Dict[str, int]] = field(default_factory=dict)


@dataclass(frozen=True)
class SolverResult:
    status: str
    activities: Tuple[Dict[str, Any], ...]
    cost_summary: Dict[str, Any]
    uncertainties: Tuple[Dict[str, Any], ...] = ()
    unsatisfied_constraints: Tuple[Dict[str, Any], ...] = ()
    diagnostics: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ItinerarySolver(Protocol):
    def solve(self, problem: PlanningProblem) -> SolverResult: ...


def validate_planning_request(request: ItineraryPlanningRequest) -> List[Dict[str, Any]]:
    """Return deterministic contract violations without raising exceptions."""
    violations: List[Dict[str, Any]] = []
    if request.schema_version != PLANNING_SCHEMA_VERSION:
        violations.append({"code": "unsupported_schema_version"})
    if not (request.location.query.strip() or str(request.location.resolved_name or "").strip()):
        violations.append({"code": "missing_location"})
    if request.location.source not in EVIDENCE_SOURCES:
        violations.append({"code": "invalid_location_source"})
    if len(request.days) != 1 or request.days[0].day_index != 0:
        violations.append({"code": "unsupported_horizon", "max_days": 1})
    for day in request.days:
        try:
            date_type.fromisoformat(day.date)
        except (TypeError, ValueError):
            violations.append({"code": "invalid_date", "day_index": day.day_index})
        if not (0 <= day.start_min < day.end_min <= 24 * 60):
            violations.append({"code": "invalid_time_window", "day_index": day.day_index})
    if request.budget.basis != "per_person":
        violations.append({"code": "unsupported_budget_basis"})
    if request.budget.mode not in {"limited", "unlimited"}:
        violations.append({"code": "invalid_budget_mode"})
    elif request.budget.mode == "limited":
        if request.budget.amount is None or request.budget.amount <= 0:
            violations.append({"code": "missing_budget_amount"})
        if not str(request.budget.currency or "").strip():
            violations.append({"code": "missing_budget_currency"})
    return violations
