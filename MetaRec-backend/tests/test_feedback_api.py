from __future__ import annotations

import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from business_models import (
    AuthSessionPayload,
    UserRecord,
    UserRole,
    UserSessionRecord,
    derive_result_id,
    ensure_uuid,
    utc_now,
)

REGISTERED_TOKEN = "registered-token"
GUEST_TOKEN = "guest-token"


def _auth_payload(*, token: str, kind: str = "registered") -> AuthSessionPayload:
    uid = str(uuid.uuid4())
    user = UserRecord(
        id=uid,
        kind=kind,
        role=UserRole.USER,
        email="user@example.com" if kind == "registered" else None,
        display_name="Registered" if kind == "registered" else "Guest",
        status="active",
    )
    session = UserSessionRecord(
        id=str(uuid.uuid4()),
        user_id=uid,
        status="active",
        expires_at=utc_now() + timedelta(days=30),
        user=user,
    )
    return AuthSessionPayload(token=token, session=session, user=user)


class FakeAuthRepository:
    def __init__(self, *payloads: AuthSessionPayload):
        self._by_token = {p.token: p for p in payloads}

    async def session_from_token(self, token: str | None):
        return self._by_token.get(token)


class FakeFeedbackRepository:
    """Mirrors the real ``submit`` contract closely enough for router tests:
    only known recommendation results can receive feedback."""

    def __init__(self):
        self.rows: dict[tuple[str, str], dict] = {}
        self.targets: dict[str, dict] = {}

    def allow_result(
        self,
        *,
        user_id: str,
        result_id: str | None = None,
        task_id: str | None = None,
        branch_id: str | None = None,
        conversation_id: str | None = None,
    ) -> str:
        resolved = ensure_uuid(result_id or derive_result_id(task_id or str(uuid.uuid4()), branch_id))
        self.targets[resolved] = {
            "user_id": user_id,
            "result_id": resolved,
            "task_id": task_id,
            "branch_id": branch_id,
            "conversation_id": conversation_id,
        }
        return resolved

    async def submit(
        self,
        *,
        user_id,
        sentiment,
        reason=None,
        result_id=None,
        task_id=None,
        branch_id=None,
        conversation_id=None,
        ui_message_id=None,
    ):
        resolved = ensure_uuid(result_id) if (result_id or "").strip() else None
        if resolved is None and task_id:
            for target in self.targets.values():
                if target["user_id"] != user_id or target["task_id"] != task_id:
                    continue
                if branch_id is not None and target["branch_id"] != branch_id:
                    continue
                if conversation_id is not None and target["conversation_id"] != conversation_id:
                    continue
                resolved = target["result_id"]
                break
        if not resolved:
            raise ValueError("result_id or task_id is required to attach feedback")
        target = self.targets.get(resolved)
        if target is None or target["user_id"] != user_id:
            raise ValueError("feedback target not found")
        if conversation_id is not None and target["conversation_id"] != conversation_id:
            raise ValueError("feedback target not found")
        if branch_id is not None and target["branch_id"] != branch_id:
            raise ValueError("feedback target not found")

        if sentiment == "up":
            rating, label = 5, None
        elif sentiment == "down":
            rating, label = 1, reason or "others"
        else:
            raise ValueError("sentiment must be 'up' or 'down'")

        key = (user_id, resolved)
        existing = self.rows.get(key)
        feedback_id = existing["feedback_id"] if existing else str(uuid.uuid4())
        row = {
            "feedback_id": feedback_id,
            "result_id": resolved,
            "sentiment": sentiment,
            "rating": rating,
            "reason": label,
        }
        self.rows[key] = row
        return row


@pytest.fixture
def feedback_setup(monkeypatch):
    import main
    import internal.feedback.router as feedback_router_mod

    registered = _auth_payload(token=REGISTERED_TOKEN, kind="registered")
    guest = _auth_payload(token=GUEST_TOKEN, kind="guest")
    fake_auth = FakeAuthRepository(registered, guest)
    fake_feedback = FakeFeedbackRepository()

    monkeypatch.setattr(main, "auth_repository", fake_auth)
    monkeypatch.setattr(feedback_router_mod, "feedback_repository", fake_feedback)
    return main, fake_feedback, registered, guest


def _client_as(main, token):
    client = TestClient(main.app)
    if token:
        client.cookies.set(main.AUTH_COOKIE_NAME, token)
    return client


@pytest.mark.backend_unit
def test_feedback_requires_authentication(feedback_setup):
    main, _repo, _reg, _guest = feedback_setup
    with TestClient(main.app) as client:
        resp = client.post("/api/feedback", json={"sentiment": "up", "result_id": str(uuid.uuid4())})
    assert resp.status_code == 401


@pytest.mark.backend_unit
def test_guest_feedback_blocked(feedback_setup):
    main, repo, _reg, _guest = feedback_setup
    with _client_as(main, GUEST_TOKEN) as client:
        resp = client.post("/api/feedback", json={"sentiment": "up", "result_id": str(uuid.uuid4())})
    assert resp.status_code == 403
    assert repo.rows == {}  # never reached the repository


@pytest.mark.backend_unit
def test_thumb_up_persists_positive_rating(feedback_setup):
    main, repo, reg, _guest = feedback_setup
    result_id = repo.allow_result(user_id=reg.user.id)
    with _client_as(main, REGISTERED_TOKEN) as client:
        resp = client.post("/api/feedback", json={"sentiment": "up", "result_id": result_id})
    assert resp.status_code == 200
    feedback = resp.json()["feedback"]
    assert feedback["rating"] == 5
    assert feedback["reason"] is None


@pytest.mark.backend_unit
def test_thumb_down_with_reason(feedback_setup):
    main, repo, reg, _guest = feedback_setup
    result_id = repo.allow_result(user_id=reg.user.id)
    with _client_as(main, REGISTERED_TOKEN) as client:
        resp = client.post(
            "/api/feedback",
            json={"sentiment": "down", "reason": "too_far", "result_id": result_id},
        )
    assert resp.status_code == 200
    feedback = resp.json()["feedback"]
    assert feedback["rating"] == 1
    assert feedback["reason"] == "too_far"


@pytest.mark.backend_unit
def test_invalid_reason_rejected(feedback_setup):
    main, _repo, _reg, _guest = feedback_setup
    with _client_as(main, REGISTERED_TOKEN) as client:
        resp = client.post(
            "/api/feedback",
            json={"sentiment": "down", "reason": "made_up", "result_id": str(uuid.uuid4())},
        )
    assert resp.status_code == 422


@pytest.mark.backend_unit
def test_thumb_down_without_reason_defaults_to_others(feedback_setup):
    main, repo, reg, _guest = feedback_setup
    result_id = repo.allow_result(user_id=reg.user.id)
    with _client_as(main, REGISTERED_TOKEN) as client:
        resp = client.post("/api/feedback", json={"sentiment": "down", "result_id": result_id})
    assert resp.status_code == 200
    assert resp.json()["feedback"]["reason"] == "others"


@pytest.mark.backend_unit
def test_missing_result_reference_returns_400(feedback_setup):
    main, _repo, _reg, _guest = feedback_setup
    with _client_as(main, REGISTERED_TOKEN) as client:
        resp = client.post("/api/feedback", json={"sentiment": "up"})
    assert resp.status_code == 400


@pytest.mark.backend_unit
def test_unknown_result_reference_returns_400(feedback_setup):
    main, repo, _reg, _guest = feedback_setup
    with _client_as(main, REGISTERED_TOKEN) as client:
        resp = client.post("/api/feedback", json={"sentiment": "up", "result_id": str(uuid.uuid4())})
    assert resp.status_code == 400
    assert resp.json()["detail"] == "feedback target not found"
    assert repo.rows == {}


@pytest.mark.backend_unit
def test_conversation_mismatch_returns_400(feedback_setup):
    main, repo, reg, _guest = feedback_setup
    result_id = repo.allow_result(user_id=reg.user.id, conversation_id=str(uuid.uuid4()))
    with _client_as(main, REGISTERED_TOKEN) as client:
        resp = client.post(
            "/api/feedback",
            json={"sentiment": "up", "result_id": result_id, "conversation_id": str(uuid.uuid4())},
        )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "feedback target not found"


@pytest.mark.backend_unit
def test_revote_updates_same_row(feedback_setup):
    main, repo, reg, _guest = feedback_setup
    result_id = repo.allow_result(user_id=reg.user.id)
    with _client_as(main, REGISTERED_TOKEN) as client:
        up = client.post("/api/feedback", json={"sentiment": "up", "result_id": result_id})
        down = client.post(
            "/api/feedback",
            json={"sentiment": "down", "reason": "not_related", "result_id": result_id},
        )
    assert up.status_code == 200 and down.status_code == 200
    # One row per (user, result); the second vote overwrote the first.
    assert len(repo.rows) == 1
    assert up.json()["feedback"]["feedback_id"] == down.json()["feedback"]["feedback_id"]
    assert down.json()["feedback"]["rating"] == 1


@pytest.mark.backend_unit
def test_options_endpoint_shape(feedback_setup):
    main, _repo, _reg, _guest = feedback_setup
    with _client_as(main, REGISTERED_TOKEN) as client:
        resp = client.get("/api/feedback/options")
    assert resp.status_code == 200
    reasons = resp.json()["reasons"]
    codes = {r["code"] for r in reasons}
    # No domain -> generic set: no location-specific "too_far".
    assert {"not_related", "inaccurate", "lack_options", "others"}.issubset(codes)
    assert "too_far" not in codes
    assert all(r["label"] for r in reasons)


@pytest.mark.backend_unit
@pytest.mark.parametrize("domain", ["restaurant", "hotel"])
def test_options_endpoint_place_domains_include_too_far(feedback_setup, domain):
    # Location-anchored domains (restaurant, hotel) offer the distance reason.
    main, _repo, _reg, _guest = feedback_setup
    with _client_as(main, REGISTERED_TOKEN) as client:
        resp = client.get("/api/feedback/options", params={"domain": domain})
    assert resp.status_code == 200
    codes = [r["code"] for r in resp.json()["reasons"]]
    assert "too_far" in codes
    assert "already_known" not in codes
    assert codes[-1] == "others"  # "others" is always the trailing chip


@pytest.mark.backend_unit
@pytest.mark.parametrize("domain", ["movie", "music", "book"])
def test_options_endpoint_entertainment_swaps_too_far_for_already_known(feedback_setup, domain):
    main, _repo, _reg, _guest = feedback_setup
    with _client_as(main, REGISTERED_TOKEN) as client:
        resp = client.get("/api/feedback/options", params={"domain": domain})
    assert resp.status_code == 200
    codes = {r["code"] for r in resp.json()["reasons"]}
    assert "already_known" in codes
    assert "too_far" not in codes


@pytest.mark.backend_unit
def test_options_endpoint_unknown_domain_falls_back_to_default(feedback_setup):
    main, _repo, _reg, _guest = feedback_setup
    with _client_as(main, REGISTERED_TOKEN) as client:
        resp = client.get("/api/feedback/options", params={"domain": "product"})
    assert resp.status_code == 200
    codes = {r["code"] for r in resp.json()["reasons"]}
    assert codes == {"not_related", "inaccurate", "lack_options", "others"}


@pytest.mark.backend_unit
def test_submit_accepts_any_union_reason_regardless_of_domain(feedback_setup):
    # The POST endpoint validates against the union, not the domain-scoped chip set,
    # so e.g. "already_known" is accepted even though the FE would only offer it for
    # entertainment domains.
    main, repo, reg, _guest = feedback_setup
    result_id = repo.allow_result(user_id=reg.user.id)
    with _client_as(main, REGISTERED_TOKEN) as client:
        resp = client.post(
            "/api/feedback",
            json={"sentiment": "down", "reason": "already_known", "result_id": result_id},
        )
    assert resp.status_code == 200
    assert resp.json()["feedback"]["reason"] == "already_known"


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_feedback_resolution_accepts_legacy_unscoped_result_branch():
    from business_repositories import PostgresFeedbackRepository
    from business_orm import RecommendationResultORM

    user_id = str(uuid.uuid4())
    conversation_id = str(uuid.uuid4())
    result_id = str(uuid.uuid4())
    result_row = SimpleNamespace(
        result_id=result_id,
        user_id=user_id,
        conversation_id=conversation_id,
        branch_id=None,
        task_id=None,
    )

    class FakeSession:
        async def get(self, model, key):
            if model is RecommendationResultORM and key == result_id:
                return result_row
            return None

    target = await PostgresFeedbackRepository()._resolve_feedback_result(
        FakeSession(),
        user_uuid=user_id,
        result_id=result_id,
        task_id=None,
        branch_id="branch-main",
        conversation_id=conversation_id,
    )

    assert target is result_row


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_feedback_stats_builds_per_domain_breakdown():
    """The aggregation returns an all-domains rollup plus a per-domain breakdown
    (sorted by volume) with each slice's own satisfaction ratio and reasons."""
    from business_repositories import PostgresAdminRepository

    class _FakeResult:
        def __init__(self, rows):
            self._rows = rows

        def one(self):
            return self._rows[0]

        def all(self):
            return self._rows

    class _FakeSession:
        # Queries run in a fixed order: overall counts, overall reasons,
        # per-domain counts, per-domain reasons.
        def __init__(self, queued):
            self._queued = list(queued)
            self.calls = 0

        async def execute(self, _statement):
            result = self._queued[self.calls]
            self.calls += 1
            return result

    session = _FakeSession(
        [
            _FakeResult([(5, 3, 2)]),  # overall: total, satisfied, unsatisfied
            _FakeResult([("too_far", 1), ("already_known", 1)]),  # overall reasons
            _FakeResult([("movie", 2, 1, 1), ("restaurant", 3, 2, 1)]),  # per-domain counts
            _FakeResult([("restaurant", "too_far", 1), ("movie", "already_known", 1)]),  # per-domain reasons
        ]
    )

    stats = await PostgresAdminRepository._feedback_stats(session)

    assert stats["total"] == 5
    assert stats["satisfaction_ratio"] == 0.6
    # Each reason carries the stable code plus a humanized label for display.
    assert stats["reasons"] == [
        {"reason": "too_far", "label": "Too far", "count": 1},
        {"reason": "already_known", "label": "Already know these", "count": 1},
    ]

    # Sorted most-feedback-first regardless of query order (restaurant before movie).
    domains = stats["domains"]
    assert [d["domain"] for d in domains] == ["restaurant", "movie"]
    restaurant = domains[0]
    assert restaurant["total"] == 3 and restaurant["satisfaction_ratio"] == round(2 / 3, 4)
    assert restaurant["reasons"] == [{"reason": "too_far", "label": "Too far", "count": 1}]
    movie = domains[1]
    assert movie["satisfaction_ratio"] == 0.5
    assert movie["reasons"] == [{"reason": "already_known", "label": "Already know these", "count": 1}]


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_feedback_stats_humanizes_unknown_and_missing_reason_codes():
    """A null label maps to "Unspecified"; a legacy/unknown code is title-cased."""
    from business_repositories import PostgresAdminRepository

    class _FakeResult:
        def __init__(self, rows):
            self._rows = rows

        def one(self):
            return self._rows[0]

        def all(self):
            return self._rows

    class _FakeSession:
        def __init__(self, queued):
            self._queued = list(queued)
            self.calls = 0

        async def execute(self, _statement):
            result = self._queued[self.calls]
            self.calls += 1
            return result

    session = _FakeSession(
        [
            _FakeResult([(2, 0, 2)]),  # overall counts
            _FakeResult([(None, 1), ("legacy_reason", 1)]),  # overall reasons
            _FakeResult([]),  # per-domain counts (irrelevant here)
            _FakeResult([]),  # per-domain reasons
        ]
    )

    stats = await PostgresAdminRepository._feedback_stats(session)

    assert stats["reasons"] == [
        {"reason": "unspecified", "label": "Unspecified", "count": 1},
        {"reason": "legacy_reason", "label": "Legacy reason", "count": 1},
    ]


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_feedback_resolution_falls_back_to_unscoped_result_for_task_branch():
    from business_repositories import PostgresFeedbackRepository
    from business_orm import RecommendationResultORM, RecommendationTaskORM

    user_id = str(uuid.uuid4())
    conversation_id = str(uuid.uuid4())
    task_id = str(uuid.uuid4())
    task_row = SimpleNamespace(
        task_id=task_id,
        user_id=user_id,
        conversation_id=conversation_id,
        branch_id=None,
    )
    result_row = SimpleNamespace(
        result_id=str(uuid.uuid4()),
        user_id=user_id,
        conversation_id=conversation_id,
        branch_id=None,
        task_id=task_id,
    )

    class FakeScalars:
        def __init__(self, row):
            self.row = row

        def first(self):
            return self.row

    class FakeSession:
        def __init__(self):
            self.scalar_calls = 0

        async def get(self, model, key):
            if model is RecommendationTaskORM and key == task_id:
                return task_row
            if model is RecommendationResultORM:
                return None
            return None

        async def scalars(self, _statement):
            self.scalar_calls += 1
            return FakeScalars(result_row if self.scalar_calls == 2 else None)

    session = FakeSession()
    target = await PostgresFeedbackRepository()._resolve_feedback_result(
        session,
        user_uuid=user_id,
        result_id=None,
        task_id=task_id,
        branch_id="branch-main",
        conversation_id=conversation_id,
    )

    assert target is result_row
    assert session.scalar_calls == 2
