"""Router + model tests for /api/item-interactions (network- and DB-free).

The repository is faked with the same semantics the Postgres one documents:
event_id idempotency, save/hide as mutually-exclusive toggles, everything else
append-only. The DB-backed contract lives in test_item_interactions_pg.py.
"""
from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from business_models import (
    ITEM_INTERACTION_ACTIONS,
    ITEM_INTERACTION_TOGGLE_ACTIONS,
    AuthSessionPayload,
    ItemInteractionRecord,
    UserRecord,
    UserRole,
    UserSessionRecord,
    item_interaction_options_for_domain,
    to_interaction_v1,
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


class FakeItemInteractionRepository:
    """In-memory twin of PostgresItemInteractionRepository's contract."""

    def __init__(self):
        self.rows: dict[str, ItemInteractionRecord] = {}

    def _active_toggles(self, user_id: str, domain: str, item_id: str) -> list[ItemInteractionRecord]:
        return [
            r
            for r in self.rows.values()
            if r.user_id == user_id
            and r.domain == domain
            and r.item_id == item_id
            and r.action in ITEM_INTERACTION_TOGGLE_ACTIONS
            and r.revoked_at is None
        ]

    async def record(self, *, user_id, domain, item_id, action, event_id=None, result_id=None,
                     task_id=None, conversation_id=None, item=None, occurred_at=None):
        if action not in ITEM_INTERACTION_ACTIONS:
            raise ValueError("bad action")
        now = utc_now()
        candidate = ItemInteractionRecord(
            event_id=event_id or str(uuid.uuid4()),
            user_id=user_id,
            domain=domain,
            item_id=item_id,
            action=action,
            result_id=result_id,
            task_id=task_id,
            conversation_id=conversation_id,
            payload={"item": item} if item else {},
            occurred_at=occurred_at or now,
            created_at=now,
        )
        existing = self.rows.get(candidate.event_id)
        if existing is not None:
            if existing.user_id != candidate.user_id:
                raise ValueError("event_id already exists outside the requested user scope")
            return existing, False
        if action in ITEM_INTERACTION_TOGGLE_ACTIONS:
            active = self._active_toggles(candidate.user_id, candidate.domain, candidate.item_id)
            same = next((r for r in active if r.action == action), None)
            if same is not None:
                return same, False
            for r in active:
                self.rows[r.event_id] = r.model_copy(update={"revoked_at": now})
        self.rows[candidate.event_id] = candidate
        return candidate, True

    async def revoke(self, *, user_id, event_id):
        row = self.rows.get(event_id)
        if row is None or row.user_id != user_id:
            return None
        if row.revoked_at is None:
            row = row.model_copy(update={"revoked_at": utc_now()})
            self.rows[event_id] = row
        return row

    async def list_for_user(self, user_id, *, domain=None, item_ids=None, since=None,
                            include_revoked=False, limit=500):
        out = [r for r in self.rows.values() if r.user_id == user_id]
        if domain:
            out = [r for r in out if r.domain == domain]
        if item_ids:
            out = [r for r in out if r.item_id in set(item_ids)]
        if not include_revoked:
            out = [r for r in out if r.revoked_at is None]
        out.sort(key=lambda r: (r.occurred_at, r.created_at))
        return out[:limit]


@pytest.fixture
def interaction_setup(monkeypatch):
    import main
    import internal.item_interactions.router as router_mod

    registered = _auth_payload(token=REGISTERED_TOKEN)
    guest = _auth_payload(token=GUEST_TOKEN, kind="guest")
    fake_auth = FakeAuthRepository(registered, guest)
    fake_repo = FakeItemInteractionRepository()
    monkeypatch.setattr(main, "auth_repository", fake_auth)
    monkeypatch.setattr(router_mod, "item_interaction_repository", fake_repo)
    return main, fake_repo, registered, guest


def _client_as(main, token):
    client = TestClient(main.app)
    if token:
        client.cookies.set(main.AUTH_COOKIE_NAME, token)
    return client


# ---------------------------------------------------------------------------
# Pure model behaviour
# ---------------------------------------------------------------------------


@pytest.mark.backend_unit
def test_record_model_normalises_and_rejects():
    rec = ItemInteractionRecord(
        event_id=str(uuid.uuid4()),
        user_id=str(uuid.uuid4()),
        domain=" Movie ",
        item_id="  tmdb_movie_42 ",
        action="save",
    )
    assert rec.domain == "movie"
    assert rec.item_id == "tmdb_movie_42"
    assert rec.is_active

    with pytest.raises(ValueError):
        ItemInteractionRecord(event_id=str(uuid.uuid4()), user_id=str(uuid.uuid4()),
                              domain="podcast", item_id="x", action="save")
    with pytest.raises(ValueError):
        ItemInteractionRecord(event_id=str(uuid.uuid4()), user_id=str(uuid.uuid4()),
                              domain="music", item_id="x" * 513, action="save")
    with pytest.raises(ValueError):
        ItemInteractionRecord(event_id=str(uuid.uuid4()), user_id=str(uuid.uuid4()),
                              domain="music", item_id="x", action="love")


@pytest.mark.backend_unit
def test_interaction_v1_projection_is_minimal_and_stable():
    now = utc_now()
    rec = ItemInteractionRecord(
        event_id=str(uuid.uuid4()), user_id=str(uuid.uuid4()), domain="music",
        item_id="mbid-1", action="consumed", result_id=str(uuid.uuid4()),
        payload={"item": {"title": "secret"}}, occurred_at=now,
    )
    wire = to_interaction_v1(rec)
    # Exactly the six ItemInteractionV1 fields plus schema_version — no payload,
    # no user_id, so the projection is safe to hand to an offline evaluator.
    assert set(wire) == {"schema_version", "event_id", "domain", "item_id", "action", "result_id", "occurred_at"}
    assert wire["schema_version"] == "item-interaction.v1"
    assert wire["occurred_at"] == now.isoformat()


@pytest.mark.backend_unit
def test_options_wording_is_domain_aware():
    codes = [o["code"] for o in item_interaction_options_for_domain("music")]
    assert codes == ["save", "hide", "consumed"]
    assert item_interaction_options_for_domain("music")[2]["label"] == "Played"
    assert item_interaction_options_for_domain("movie")[2]["label"] == "Watched"
    assert item_interaction_options_for_domain("book")[2]["label"] == "Read"
    assert item_interaction_options_for_domain("product")[2]["label"] == "Purchased"
    assert item_interaction_options_for_domain(None)[2]["label"] == "Used"


# ---------------------------------------------------------------------------
# Router behaviour
# ---------------------------------------------------------------------------


@pytest.mark.backend_unit
def test_auth_gating(interaction_setup):
    main, _repo, _reg, _guest = interaction_setup
    body = {"domain": "music", "item_id": "mbid-1", "action": "save"}

    with TestClient(main.app) as client:
        assert client.post("/api/item-interactions", json=body).status_code == 401
        assert client.get("/api/item-interactions").status_code == 401

    with _client_as(main, GUEST_TOKEN) as client:
        # Guests may read options but not write.
        assert client.get("/api/item-interactions/options?domain=music").status_code == 200
        assert client.post("/api/item-interactions", json=body).status_code == 403
        assert client.delete(f"/api/item-interactions/{uuid.uuid4()}").status_code == 403


@pytest.mark.backend_unit
def test_record_list_revoke_roundtrip(interaction_setup):
    main, repo, registered, _guest = interaction_setup
    with _client_as(main, REGISTERED_TOKEN) as client:
        res = client.post("/api/item-interactions", json={
            "domain": "Movie",
            "item_id": "tmdb_movie_42",
            "action": "save",
            "item": {"title": "Arrival", "source": "tmdb.movie.search", "url": "https://example.invalid/42"},
        })
        assert res.status_code == 200, res.text
        data = res.json()
        assert data["ok"] is True and data["created"] is True
        saved = data["interaction"]
        assert saved["domain"] == "movie"
        assert saved["action"] == "save"
        assert saved["item"]["title"] == "Arrival"
        assert saved["revoked_at"] is None
        event_id = saved["event_id"]

        # user_id is never in the response.
        assert "user_id" not in saved

        listed = client.get("/api/item-interactions?domain=movie&item_ids=tmdb_movie_42,other").json()
        assert [r["event_id"] for r in listed["interactions"]] == [event_id]

        gone = client.delete(f"/api/item-interactions/{event_id}")
        assert gone.status_code == 200
        assert gone.json()["interaction"]["revoked_at"] is not None

        assert client.get("/api/item-interactions?domain=movie").json()["interactions"] == []
        with_revoked = client.get("/api/item-interactions?domain=movie&include_revoked=true").json()
        assert len(with_revoked["interactions"]) == 1

        # Revoking again is idempotent; a foreign/unknown id is 404.
        assert client.delete(f"/api/item-interactions/{event_id}").status_code == 200
        assert client.delete(f"/api/item-interactions/{uuid.uuid4()}").status_code == 404


@pytest.mark.backend_unit
def test_event_id_idempotency_and_toggle_semantics(interaction_setup):
    main, repo, registered, _guest = interaction_setup
    with _client_as(main, REGISTERED_TOKEN) as client:
        event_id = str(uuid.uuid4())
        first = client.post("/api/item-interactions", json={
            "domain": "music", "item_id": "mbid-1", "action": "save", "event_id": event_id,
        }).json()
        again = client.post("/api/item-interactions", json={
            "domain": "music", "item_id": "mbid-1", "action": "save", "event_id": event_id,
        }).json()
        assert first["created"] is True and again["created"] is False
        assert again["interaction"]["event_id"] == event_id

        # A fresh save on an already-saved item is a no-op, not a duplicate.
        dup = client.post("/api/item-interactions", json={"domain": "music", "item_id": "mbid-1", "action": "save"}).json()
        assert dup["created"] is False and dup["interaction"]["event_id"] == event_id

        # hide supersedes save on the same item.
        hidden = client.post("/api/item-interactions", json={"domain": "music", "item_id": "mbid-1", "action": "hide"}).json()
        assert hidden["created"] is True
        active = client.get("/api/item-interactions?domain=music&item_ids=mbid-1").json()["interactions"]
        assert [r["action"] for r in active] == ["hide"]

        # consumed is append-only: two plays are two rows.
        for _ in range(2):
            assert client.post("/api/item-interactions", json={"domain": "music", "item_id": "mbid-1", "action": "consumed"}).json()["created"] is True
        plays = [r for r in client.get("/api/item-interactions?domain=music").json()["interactions"] if r["action"] == "consumed"]
        assert len(plays) == 2


@pytest.mark.backend_unit
def test_validation_errors(interaction_setup):
    main, _repo, _reg, _guest = interaction_setup
    with _client_as(main, REGISTERED_TOKEN) as client:
        assert client.post("/api/item-interactions", json={"domain": "podcast", "item_id": "x", "action": "save"}).status_code == 422
        assert client.post("/api/item-interactions", json={"domain": "music", "item_id": "x", "action": "love"}).status_code == 422
        assert client.post("/api/item-interactions", json={"domain": "music", "item_id": "", "action": "save"}).status_code == 422
        assert client.post("/api/item-interactions", json={"domain": "music", "item_id": "x", "action": "save", "result_id": "not-a-uuid"}).status_code == 422
        # Unknown fields are rejected (extra="forbid").
        assert client.post("/api/item-interactions", json={"domain": "music", "item_id": "x", "action": "save", "raw": {}}).status_code == 422
        assert client.get("/api/item-interactions?domain=podcast").status_code == 400
        too_many = ",".join(f"i{n}" for n in range(51))
        assert client.get(f"/api/item-interactions?item_ids={too_many}").status_code == 400
