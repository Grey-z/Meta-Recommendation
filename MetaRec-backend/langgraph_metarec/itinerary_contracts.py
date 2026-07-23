"""Provider-free contracts for itinerary planning and solver adapters.

The structures in this module intentionally contain only serializable values.
Provider clients and LLM responses must be normalized before they cross this
boundary, allowing another solver implementation to consume the same problem.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date as date_type, datetime as datetime_type, timedelta
from typing import Any, Dict, List, Optional, Protocol, Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

PLANNING_SCHEMA_VERSION = "itinerary-ir/v2"
PLANNING_STATUSES = {"feasible", "indeterminate", "infeasible"}
EVIDENCE_SOURCES = {"user", "profile", "system", "provider", "registry", "rule", "llm", "unknown"}

# Fallback trip framing used only when the user's query named neither a date nor
# a daily time window (the extractor writes those fields when time-framing *is*
# mentioned, so an explicit query always wins over these defaults).
DEFAULT_DAILY_START_MIN = 9 * 60    # 09:00
DEFAULT_DAILY_END_MIN = 22 * 60     # 22:00
DEFAULT_TIMEZONE = "Asia/Singapore"


def _default_first_date(timezone_name: Any) -> date_type:
    """Tomorrow in the trip's timezone — the default trip start when the user
    named no date. Mirrors eta.py's zone resolution (unknown zone falls back to
    Asia/Singapore) so the default lands on the traveller's local tomorrow."""
    try:
        zone = ZoneInfo(str(timezone_name or "").strip() or DEFAULT_TIMEZONE)
    except (ZoneInfoNotFoundError, ValueError):
        zone = ZoneInfo(DEFAULT_TIMEZONE)
    return datetime_type.now(zone).date() + timedelta(days=1)


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
    scope: str = "trip_total"
    include_lodging: bool = False


@dataclass(frozen=True)
class AnchorConstraint:
    query: str
    resolved_name: Optional[str] = None
    address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    provider_id: Optional[str] = None
    source: str = "user"


@dataclass(frozen=True)
class LodgingRequirement:
    mode: str
    check_in_date: str
    check_out_date: str
    nights: int
    travelers: int
    rooms: int


@dataclass(frozen=True)
class LodgingScenario:
    candidate_id: str
    title: str
    latitude: float
    longitude: float
    address: Optional[str]
    source: Optional[str]
    nightly_cost: CostEstimate
    trip_cost_per_person: CostEstimate
    rating: Optional[float] = None
    provider_relevance: float = 0.0
    item: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ItineraryPlanningRequest:
    location: LocationConstraint
    days: Tuple[DayConstraint, ...]
    budget: BudgetConstraint
    lodging: Optional[LodgingRequirement] = None
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
    role: str = "unknown"
    role_source: str = "unknown"
    is_compound: bool = False
    parent_id: Optional[str] = None
    access: str = "independent"
    containment_source: str = "none"
    item: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PlanningProblem:
    request: ItineraryPlanningRequest
    candidates: Tuple[PlanningCandidate, ...]
    travel_minutes: Dict[str, Dict[str, int]] = field(default_factory=dict)
    lodging_scenarios: Tuple[LodgingScenario, ...] = ()


@dataclass(frozen=True)
class SolverResult:
    status: str
    activities: Tuple[Dict[str, Any], ...]
    cost_summary: Dict[str, Any]
    uncertainties: Tuple[Dict[str, Any], ...] = ()
    unsatisfied_constraints: Tuple[Dict[str, Any], ...] = ()
    diagnostics: Dict[str, Any] = field(default_factory=dict)
    lodging: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SanityReport:
    status: str
    violations: Tuple[Dict[str, Any], ...]
    metrics: Dict[str, Any]
    repairable_codes: Tuple[str, ...] = ()
    warnings: Tuple[Dict[str, Any], ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RepairDirective:
    domain_queries: Dict[str, str]
    required_roles: Tuple[str, ...] = ()
    excluded_types: Tuple[str, ...] = ()
    provider_hints: Dict[str, Tuple[str, ...]] = field(default_factory=dict)

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
    if not str(request.location.timezone or "").strip():
        violations.append({"code": "missing_timezone"})
    if not (1 <= len(request.days) <= 3):
        violations.append({"code": "unsupported_horizon", "max_days": 3})
    parsed_dates: List[Optional[date_type]] = []
    for day in request.days:
        try:
            parsed_dates.append(date_type.fromisoformat(day.date))
        except (TypeError, ValueError):
            parsed_dates.append(None)
            violations.append({"code": "invalid_date", "day_index": day.day_index})
        if not (0 <= day.start_min < day.end_min <= 24 * 60):
            violations.append({"code": "invalid_time_window", "day_index": day.day_index})
    if tuple(day.day_index for day in request.days) != tuple(range(len(request.days))):
        violations.append({"code": "invalid_day_indexes"})
    if all(value is not None for value in parsed_dates):
        for previous, current in zip(parsed_dates, parsed_dates[1:]):
            if current != previous + timedelta(days=1):
                violations.append({"code": "non_contiguous_dates"})
                break
    if request.budget.basis != "per_person":
        violations.append({"code": "unsupported_budget_basis"})
    if request.budget.scope != "trip_total":
        violations.append({"code": "unsupported_budget_scope"})
    if request.budget.mode not in {"limited", "unlimited"}:
        violations.append({"code": "invalid_budget_mode"})
    elif request.budget.mode == "limited":
        if request.budget.amount is None or request.budget.amount <= 0:
            violations.append({"code": "missing_budget_amount"})
        if not str(request.budget.currency or "").strip():
            violations.append({"code": "missing_budget_currency"})
    if len(request.days) > 1:
        for key in ("travelers", "rooms"):
            try:
                valid = int(request.hard_constraints.get(key)) > 0
            except (TypeError, ValueError):
                valid = False
            if not valid:
                violations.append({"code": f"missing_{key}"})
        if request.lodging is None:
            violations.append({"code": "missing_lodging_requirement"})
        elif request.lodging.mode not in {"supplied", "recommend"}:
            violations.append({"code": "invalid_lodging_mode"})
    return violations


def parse_hhmm(value: Any) -> Optional[int]:
    try:
        hour, minute = (int(part) for part in str(value).strip().split(":", 1))
    except (TypeError, ValueError, AttributeError):
        return None
    return hour * 60 + minute if 0 <= hour < 24 and 0 <= minute < 60 else None


def planning_request_from_preferences(
    preferences: Dict[str, Any],
) -> Tuple[Optional[ItineraryPlanningRequest], List[Dict[str, Any]]]:
    """Build the solver-neutral request after the HITL form is complete."""
    # Time window and trip date are optional; default a 09:00–22:00 day starting
    # tomorrow when the user named none. An inverted/out-of-range explicit window
    # still surfaces via validate_planning_request below.
    raw_start = preferences.get("daily_start_time") or preferences.get("start_time")
    raw_end = preferences.get("daily_end_time") or preferences.get("end_time")
    start_min = parse_hhmm(raw_start) if str(raw_start or "").strip() else DEFAULT_DAILY_START_MIN
    end_min = parse_hhmm(raw_end) if str(raw_end or "").strip() else DEFAULT_DAILY_END_MIN
    if start_min is None or end_min is None:
        return None, [{"code": "invalid_time_window", "day_index": 0}]
    try:
        horizon_days = int(preferences.get("horizon_days") or 1)
    except (TypeError, ValueError):
        horizon_days = 0
    raw_date = str(preferences.get("date") or "").strip()
    if raw_date:
        try:
            first_date = date_type.fromisoformat(raw_date)
        except ValueError:
            # A date the user *did* supply but that cannot be parsed is a real
            # error to re-ask, not a case for the tomorrow default.
            return None, [{"code": "invalid_date", "day_index": 0}]
    else:
        first_date = _default_first_date(preferences.get("timezone"))
    try:
        amount = (
            float(preferences.get("budget_amount"))
            if preferences.get("budget_mode") == "limited"
            else None
        )
    except (TypeError, ValueError):
        amount = None
    sources = preferences.get("_itinerary_field_sources")
    sources = sources if isinstance(sources, dict) else {}
    location_source = str(sources.get("location") or "user")
    if location_source not in EVIDENCE_SOURCES:
        location_source = "unknown"

    def list_value(key: str) -> List[str]:
        value = preferences.get(key)
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        if isinstance(value, (list, tuple, set)):
            return [str(part).strip() for part in value if str(part).strip()]
        return []
    days = tuple(
        DayConstraint(
            day_index=day_index,
            date=(first_date + timedelta(days=day_index)).isoformat(),
            start_min=start_min,
            end_min=end_min,
        )
        for day_index in range(max(0, horizon_days))
    )
    suggested_meals: List[Dict[str, Any]] = []
    for day_index in range(max(0, horizon_days)):
        if start_min < 14 * 60 + 30 and end_min > 11 * 60 + 30:
            suggested_meals.append({"day_index": day_index, "meal": "lunch"})
        if start_min <= 19 * 60 and end_min >= 18 * 60 + 30:
            suggested_meals.append({"day_index": day_index, "meal": "dinner"})

    explicit_meals: List[Dict[str, Any]] = []
    raw_meals = preferences.get("meal_obligations")
    meal_source = str(sources.get("meal_obligations") or "user")
    if raw_meals not in (None, "", [], {}) and meal_source == "user":
        values = raw_meals if isinstance(raw_meals, (list, tuple, set)) else [raw_meals]
        for value in values:
            if isinstance(value, dict):
                try:
                    indexes = [int(value.get("day_index", 0))]
                except (TypeError, ValueError):
                    continue
                meal = str(value.get("meal") or "").strip().lower()
            else:
                indexes = list(range(max(0, horizon_days)))
                meal = str(value or "").strip().lower()
            if meal not in {"breakfast", "lunch", "dinner"}:
                continue
            for day_index in indexes:
                obligation = {"day_index": day_index, "meal": meal}
                if 0 <= day_index < horizon_days and obligation not in explicit_meals:
                    explicit_meals.append(obligation)
    suggested_meals = [meal for meal in suggested_meals if meal not in explicit_meals]
    anchors: Dict[str, AnchorConstraint] = {}
    anchor_policy = str(preferences.get("anchor_policy") or "round_trip")
    resolved_anchors = preferences.get("resolved_anchors")
    resolved_anchors = resolved_anchors if isinstance(resolved_anchors, dict) else {}

    def build_anchor(key: str, query_key: str) -> Optional[AnchorConstraint]:
        query = str(preferences.get(query_key) or "").strip()
        resolved = resolved_anchors.get(key)
        if not query or not isinstance(resolved, dict):
            return None
        try:
            latitude = float(resolved["latitude"])
            longitude = float(resolved["longitude"])
        except (KeyError, TypeError, ValueError):
            return None
        return AnchorConstraint(
            query=query,
            resolved_name=str(resolved.get("resolved_name") or query),
            address=str(resolved.get("address") or "") or None,
            latitude=latitude,
            longitude=longitude,
            provider_id=str(resolved.get("provider_id") or "") or None,
            source=str(resolved.get("source") or "provider"),
        )

    lodging_mode = str(preferences.get("lodging_mode") or "").strip().lower()
    if lodging_mode not in {"none", "supplied", "recommend"}:
        lodging_mode = "supplied" if str(preferences.get("hotel_anchor") or "").strip() else "none"
    start_anchor = build_anchor("start", "hotel_anchor") if lodging_mode == "supplied" else None
    if start_anchor is not None:
        anchors["start"] = start_anchor
        if horizon_days > 1:
            anchors["lodging"] = start_anchor
        if anchor_policy == "round_trip":
            anchors["end"] = start_anchor
    if anchor_policy == "distinct_end":
        end_anchor = build_anchor("end", "end_anchor")
        if end_anchor is not None:
            anchors["end"] = end_anchor
    lodging = None
    if horizon_days > 1:
        try:
            travelers = int(preferences.get("travelers"))
            rooms = int(preferences.get("rooms"))
        except (TypeError, ValueError):
            travelers = rooms = 0
        lodging = LodgingRequirement(
            mode=lodging_mode,
            check_in_date=first_date.isoformat(),
            check_out_date=(first_date + timedelta(days=max(0, horizon_days - 1))).isoformat(),
            nights=max(0, horizon_days - 1),
            travelers=travelers,
            rooms=rooms,
        )
    request = ItineraryPlanningRequest(
        location=LocationConstraint(
            query=str(preferences.get("location") or "").strip(),
            resolved_name=str(preferences.get("resolved_location") or "").strip() or None,
            timezone=str(preferences.get("timezone") or "").strip() or None,
            source=location_source,
        ),
        days=days,
        budget=BudgetConstraint(
            mode=str(preferences.get("budget_mode") or ""),
            amount=amount,
            currency=str(preferences.get("budget_currency") or "").strip().upper() or None,
            scope="trip_total",
            include_lodging=horizon_days > 1,
        ),
        lodging=lodging,
        anchors=anchors,
        hard_constraints={
            "meal_obligations": explicit_meals,
            "anchor_policy": anchor_policy,
            "must_visit": list_value("must_visit"),
            "exclude": list_value("exclude"),
            "travelers": preferences.get("travelers"),
            "rooms": preferences.get("rooms"),
            "night_count": max(0, horizon_days - 1),
            "lodging_mode": lodging_mode,
        },
        soft_preferences={
            "pace": str(preferences.get("pace") or "balanced"),
            "style": str(preferences.get("style") or "sightseeing"),
            "attraction_types": list_value("attraction_types"),
            "interest_terms": list_value("interest_terms"),
            "suggested_meals": suggested_meals,
        },
        explicit_fields=tuple(sorted(
            key for key, source in sources.items() if source == "user"
        )),
    )
    return request, validate_planning_request(request)


def planning_request_from_dict(payload: Dict[str, Any]) -> ItineraryPlanningRequest:
    location = payload.get("location") or {}
    budget = payload.get("budget") or {}
    days = payload.get("days") or []
    anchors = payload.get("anchors") or {}
    lodging = payload.get("lodging")
    return ItineraryPlanningRequest(
        schema_version=str(payload.get("schema_version") or PLANNING_SCHEMA_VERSION),
        location=LocationConstraint(**location),
        days=tuple(DayConstraint(**day) for day in days),
        budget=BudgetConstraint(**budget),
        lodging=LodgingRequirement(**lodging) if isinstance(lodging, dict) else None,
        anchors={key: AnchorConstraint(**value) for key, value in anchors.items()},
        hard_constraints=dict(payload.get("hard_constraints") or {}),
        soft_preferences=dict(payload.get("soft_preferences") or {}),
        explicit_fields=tuple(payload.get("explicit_fields") or ()),
    )
