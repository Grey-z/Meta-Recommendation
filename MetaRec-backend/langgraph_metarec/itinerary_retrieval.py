"""Task-scoped candidate retrieval and bounded adaptive planning control."""
from __future__ import annotations

import asyncio
import inspect
import time
from dataclasses import dataclass, field
from typing import (
    Any, Awaitable, Callable, Dict, FrozenSet, Iterable, List, Mapping, Optional,
    Sequence, Tuple,
)

from langgraph_metarec.itinerary_contracts import PlanningCandidate

RETRIEVAL_SCHEMA_VERSION = "itinerary-retrieval/v1"

# Failure codes that a domain re-fetch can plausibly resolve, grouped by the
# domain that would have to supply the missing candidates.
RESTAURANT_GAP_CODES = frozenset({"meal_obligation", "meal_preference_unmet"})
ATTRACTION_GAP_CODES = frozenset({
    "no_feasible_route",
    "missing_primary_experience",
    "experience_share_low",
    "mixed_role_diversity_low",
    "role_unverified",
    "excessive_idle_gap",
})
# An unresolved must-visit carries no domain information: the named venue is as
# likely to be a canteen as a landmark, and the code alone cannot tell us which.
# These widen to every active domain rather than guessing.
UNTARGETED_GAP_CODES = frozenset({"must_visit_unavailable"})


def evaluation_failure_codes(diagnostics: Mapping[str, Any]) -> FrozenSet[str]:
    """Every failure code the retrieval loop should react to.

    Findings arrive on three channels: the solver's ``unsatisfied_constraints``
    carry hard-constraint failures, while the sanity pass splits its own findings
    across ``warnings`` and ``violations``. Reading only two of the three left
    ``meal_obligation`` -- a violation, and the sole restaurant re-fetch trigger --
    permanently unreachable, so a plan short of meals never re-queried restaurants.
    """
    codes = set()
    for channel in ("unsatisfied_constraints", "sanity_warnings", "sanity_violations"):
        for value in diagnostics.get(channel) or ():
            if isinstance(value, Mapping):
                code = str(value.get("code") or "")
                if code:
                    codes.add(code)
    return frozenset(codes)


def domains_needing_retrieval(
    codes: Iterable[str],
    active_domains: Iterable[str],
    *,
    infeasible: bool = False,
) -> FrozenSet[str]:
    """Domains to re-fetch for a failure signature, limited to the active ones."""
    codes = frozenset(codes)
    active = frozenset(active_domains)
    needs: set[str] = set()
    if codes & RESTAURANT_GAP_CODES:
        needs |= active & {"restaurant"}
    if codes & UNTARGETED_GAP_CODES:
        needs |= active
    if infeasible or codes & ATTRACTION_GAP_CODES:
        needs |= active & {"attraction"}
    return frozenset(needs)


@dataclass(frozen=True)
class RetrievalRequest:
    task_id: str
    tool: str
    domain: str
    role: str
    anchor_lat: Optional[float]
    anchor_lng: Optional[float]
    radius_meters: int
    constraint_signature: str
    day_index: int = 0
    start_min: Optional[int] = None
    end_min: Optional[int] = None
    exclusions: Tuple[str, ...] = ()
    schema_version: str = RETRIEVAL_SCHEMA_VERSION

    def cache_key(self) -> Tuple[Any, ...]:
        anchor_lat = None if self.anchor_lat is None else round(float(self.anchor_lat), 3)
        anchor_lng = None if self.anchor_lng is None else round(float(self.anchor_lng), 3)
        return (
            self.task_id,
            self.tool,
            self.domain,
            self.role,
            anchor_lat,
            anchor_lng,
            max(100, int(round(self.radius_meters / 500.0) * 500)),
            self.constraint_signature,
            self.day_index,
            self.schema_version,
        )


@dataclass(frozen=True)
class RetrievalRoundResult:
    request: RetrievalRequest
    candidates: Tuple[PlanningCandidate, ...]
    cache_status: str
    diagnostics: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CandidateStoreEntry:
    key: Tuple[Any, ...]
    candidates: Tuple[PlanningCandidate, ...]
    fetched_at: float
    expires_at: float
    negative: bool = False


@dataclass
class RetrievalBudget:
    max_provider_calls: int = 8
    max_rounds: int = 2
    provider_calls: int = 0
    rounds: int = 0

    def consume_call(self) -> bool:
        if self.provider_calls >= self.max_provider_calls:
            return False
        self.provider_calls += 1
        return True

    def begin_round(self) -> bool:
        if self.rounds >= self.max_rounds:
            return False
        self.rounds += 1
        return True


class CandidateStore:
    """Bounded cache owned by exactly one running itinerary task."""

    def __init__(
        self,
        task_id: str,
        *,
        max_entries: int = 24,
        max_candidates_per_entry: int = 12,
        ttl_seconds: float = 15 * 60,
    ) -> None:
        if not str(task_id).strip():
            raise ValueError("CandidateStore requires a task_id")
        self.task_id = str(task_id)
        self.max_entries = max(1, int(max_entries))
        self.max_candidates_per_entry = max(1, int(max_candidates_per_entry))
        self.ttl_seconds = max(1.0, float(ttl_seconds))
        self._entries: Dict[Tuple[Any, ...], CandidateStoreEntry] = {}
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    def _check(self, request: RetrievalRequest) -> Tuple[Any, ...]:
        if self._closed:
            raise RuntimeError("CandidateStore is closed")
        if request.task_id != self.task_id:
            raise ValueError("retrieval request belongs to another task")
        return request.cache_key()

    def get(self, request: RetrievalRequest, *, now: Optional[float] = None) -> Optional[CandidateStoreEntry]:
        key = self._check(request)
        current = time.monotonic() if now is None else float(now)
        entry = self._entries.get(key)
        if entry is not None and entry.expires_at <= current:
            self._entries.pop(key, None)
            return None
        return entry

    def put(
        self,
        request: RetrievalRequest,
        candidates: Sequence[PlanningCandidate],
        *,
        now: Optional[float] = None,
    ) -> CandidateStoreEntry:
        key = self._check(request)
        current = time.monotonic() if now is None else float(now)
        unique: List[PlanningCandidate] = []
        seen = set()
        for candidate in candidates:
            identity = candidate.id or (
                candidate.title.lower(), round(candidate.latitude, 5), round(candidate.longitude, 5)
            )
            if identity in seen:
                continue
            seen.add(identity)
            unique.append(candidate)
            if len(unique) >= self.max_candidates_per_entry:
                break
        entry = CandidateStoreEntry(
            key=key,
            candidates=tuple(unique),
            fetched_at=current,
            expires_at=current + self.ttl_seconds,
            negative=not unique,
        )
        self._entries[key] = entry
        if len(self._entries) > self.max_entries:
            oldest = min(self._entries.values(), key=lambda item: (item.fetched_at, item.key))
            self._entries.pop(oldest.key, None)
        return entry

    def candidates(self) -> Tuple[PlanningCandidate, ...]:
        if self._closed:
            return ()
        merged: Dict[Tuple[Any, ...], Tuple[PlanningCandidate, Tuple[Any, ...]]] = {}
        for entry in sorted(self._entries.values(), key=lambda item: (item.fetched_at, item.key)):
            for candidate in entry.candidates:
                physical_key = (
                    candidate.title.strip().casefold(),
                    round(float(candidate.latitude), 4),
                    round(float(candidate.longitude), 4),
                )
                strength = (
                    int(candidate.availability_known),
                    round(float(candidate.duration.confidence), 4),
                    int(candidate.cost.min is not None and candidate.cost.max is not None),
                    round(float(candidate.rating or 0.0), 4),
                    round(float(candidate.provider_relevance), 4),
                    entry.fetched_at,
                    candidate.id,
                )
                previous = merged.get(physical_key)
                if previous is None or strength > previous[1]:
                    merged[physical_key] = (candidate, strength)
        return tuple(
            row[0]
            for _key, row in sorted(merged.items(), key=lambda item: (item[1][0].id, item[0]))
        )

    def close(self) -> None:
        self._entries.clear()
        self._closed = True


@dataclass(frozen=True)
class AdaptiveEvaluation:
    """One deterministic solve over the complete candidate store."""

    status: str
    selected_ids: Tuple[str, ...]
    utility: float
    diagnostics: Dict[str, Any] = field(default_factory=dict)
    payload: Any = None

    def quality_key(self) -> Tuple[Any, ...]:
        status_rank = {"feasible": 0, "indeterminate": 1, "infeasible": 2}
        uncertainty_count = int(self.diagnostics.get("uncertainty_count") or 0)
        return (
            status_rank.get(self.status, 3),
            -len(self.selected_ids),
            -round(float(self.utility), 6),
            uncertainty_count,
            self.selected_ids,
        )


@dataclass(frozen=True)
class AdaptivePlannerResult:
    evaluation: Optional[AdaptiveEvaluation]
    candidates: Tuple[PlanningCandidate, ...]
    rounds: Tuple[Dict[str, Any], ...]
    provider_calls: int
    stop_reason: str


FetchCandidates = Callable[[RetrievalRequest], Awaitable[Sequence[PlanningCandidate]]]
EvaluateCandidates = Callable[[Sequence[PlanningCandidate]], Any]
DeriveRequests = Callable[[AdaptiveEvaluation, Sequence[PlanningCandidate]], Any]


class AdaptiveItineraryPlanner:
    """Bounded outer loop; provider I/O never crosses into the solver callback."""

    def __init__(
        self,
        task_id: str,
        *,
        fetch: FetchCandidates,
        evaluate: EvaluateCandidates,
        derive_requests: DeriveRequests,
        budget: Optional[RetrievalBudget] = None,
        store: Optional[CandidateStore] = None,
    ) -> None:
        self.store = store or CandidateStore(task_id)
        if self.store.task_id != str(task_id):
            raise ValueError("candidate store belongs to another task")
        self.fetch = fetch
        self.evaluate = evaluate
        self.derive_requests = derive_requests
        self.budget = budget or RetrievalBudget()

    @staticmethod
    async def _resolve(value: Any) -> Any:
        return await value if inspect.isawaitable(value) else value

    async def _safe_fetch(
        self, request: RetrievalRequest
    ) -> Tuple[Tuple[PlanningCandidate, ...], Optional[str]]:
        """Fetch one request, isolating provider failures from the gather."""
        try:
            return tuple(await self.fetch(request)), None
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return (), type(exc).__name__

    @staticmethod
    def _cluster(requests: Sequence[RetrievalRequest]) -> List[RetrievalRequest]:
        unique = {request.cache_key(): request for request in requests}
        return [unique[key] for key in sorted(unique, key=repr)]

    async def run(self, seed_requests: Sequence[RetrievalRequest]) -> AdaptivePlannerResult:
        pending = self._cluster(seed_requests)
        best: Optional[AdaptiveEvaluation] = None
        best_candidates: Tuple[PlanningCandidate, ...] = ()
        rounds: List[Dict[str, Any]] = []
        previous_fingerprint: Optional[Tuple[str, ...]] = None
        stop_reason = "no_seed_requests"
        try:
            while pending and self.budget.begin_round():
                retrievals: List[Dict[str, Any]] = []
                exhausted = False
                # Reserve budget for cache-misses up front, then fetch the
                # round's independent domain requests concurrently. Clustering
                # guarantees unique cache keys, so store writes stay deterministic
                # when applied in pending order after the gather completes.
                planned: List[Tuple[RetrievalRequest, Optional[CandidateStoreEntry]]] = []
                to_fetch: List[RetrievalRequest] = []
                for request in pending:
                    cached = self.store.get(request)
                    if cached is not None:
                        planned.append((request, cached))
                        continue
                    if not self.budget.consume_call():
                        exhausted = True
                        break
                    planned.append((request, None))
                    to_fetch.append(request)
                fetched_by_key: Dict[Tuple[Any, ...], Tuple[Tuple[PlanningCandidate, ...], Optional[str]]] = {}
                if to_fetch:
                    results = await asyncio.gather(
                        *(self._safe_fetch(request) for request in to_fetch)
                    )
                    fetched_by_key = {
                        request.cache_key(): result
                        for request, result in zip(to_fetch, results)
                    }
                for request, cached in planned:
                    if cached is not None:
                        retrievals.append({
                            "domain": request.domain,
                            "role": request.role,
                            "cache_status": "negative_hit" if cached.negative else "hit",
                            "candidate_count": len(cached.candidates),
                        })
                        continue
                    fetched, error = fetched_by_key.get(request.cache_key(), ((), "no_result"))
                    entry = self.store.put(request, () if error else fetched)
                    if error is not None:
                        cache_status = "error"
                    else:
                        cache_status = "negative_miss" if entry.negative else "miss"
                    retrievals.append({
                        "domain": request.domain,
                        "role": request.role,
                        "cache_status": cache_status,
                        "candidate_count": len(entry.candidates),
                        **({"error": error} if error else {}),
                    })
                candidates = self.store.candidates()
                fingerprint = tuple(candidate.id for candidate in candidates)
                if previous_fingerprint == fingerprint and best is not None:
                    stop_reason = "no_material_candidate_change"
                    rounds.append({
                        "round": self.budget.rounds,
                        "candidate_count": len(candidates),
                        "retrievals": retrievals,
                        "evaluated": False,
                    })
                    break
                evaluation = await self._resolve(self.evaluate(candidates))
                if not isinstance(evaluation, AdaptiveEvaluation):
                    raise TypeError("evaluate must return AdaptiveEvaluation")
                rounds.append({
                    "round": self.budget.rounds,
                    "candidate_count": len(candidates),
                    "retrievals": retrievals,
                    "evaluated": True,
                    "status": evaluation.status,
                    "selected_ids": list(evaluation.selected_ids),
                })
                if best is None or evaluation.quality_key() < best.quality_key():
                    best = evaluation
                    best_candidates = candidates
                previous_fingerprint = fingerprint
                if exhausted:
                    stop_reason = "provider_budget_exhausted"
                    break
                derived = await self._resolve(self.derive_requests(evaluation, candidates))
                pending = self._cluster(tuple(derived or ()))
                if not pending:
                    stop_reason = "stable_feasible_winner" if evaluation.status == "feasible" else "no_followup_request"
                    break
                stop_reason = "round_budget_exhausted"
            return AdaptivePlannerResult(
                evaluation=best,
                candidates=best_candidates,
                rounds=tuple(rounds),
                provider_calls=self.budget.provider_calls,
                stop_reason=stop_reason,
            )
        finally:
            self.store.close()
