import pytest

from conftest import make_service
from langgraph_metarec.itinerary_composer import compose_itinerary
from service import ItineraryConflictError

pytestmark = pytest.mark.backend_unit


class FakeResultRepository:
    def __init__(self, payload=None):
        self.payload = payload
        self.saved = []

    async def load_by_task(self, user_id, conversation_id, task_id):
        return self.payload

    async def save(self, user_id, session_id, branch_id, result_id, payload):
        self.saved.append({"result_id": result_id, "branch_id": branch_id, "payload": payload})
        self.payload = payload


def _generic(item_id, title, lat, lng, rating=4.0, domain="attraction"):
    return {
        "id": item_id,
        "title": title,
        "rating": rating,
        "domain": domain,
        "raw": {"gps_coordinates": {"latitude": lat, "longitude": lng}},
    }


def _stored_payload():
    block = compose_itinerary(
        [
            {
                "slot_index": 0,
                "domain": "attraction",
                "slot_label": "Morning activity",
                "slot_time": "10:00",
                "candidates": [_generic("a0", "Museum", 1.300, 103.850)],
            },
            {
                "slot_index": 1,
                "domain": "attraction",
                "slot_label": "Afternoon activity",
                "slot_time": "14:30",
                "candidates": [
                    _generic("a1", "Park", 1.301, 103.851, rating=4.5),
                    _generic("a1-alt", "Gallery", 1.303, 103.853, rating=4.2),
                ],
            },
            {
                "slot_index": 2,
                "domain": "attraction",
                "slot_label": "Evening viewpoint",
                "slot_time": "18:00",
                "candidates": [_generic("a2", "Viewpoint", 1.302, 103.852)],
            },
        ],
        location="Sentosa",
    )
    for leg in block["legs"]:
        leg["source"] = "onemap"  # simulate the original provider resolution
    return {
        "result_id": "res-1",
        "task_id": "t-1",
        "branch_id": None,
        "domain": "itinerary",
        "restaurants": [],
        "items": [],
        "thinking_steps": [],
        "metadata": {"domain": "itinerary", "itinerary": block},
    }


@pytest.fixture()
def _leg_counter(monkeypatch):
    import langgraph_metarec.eta as eta_module

    calls = []

    def fake_resolve_leg(a, b, depart_hhmm=None):
        calls.append((a, b))
        return {"mode": "walk", "duration_min": 8, "distance_km": 0.4, "source": "onemap"}

    monkeypatch.setattr(eta_module, "resolve_leg", fake_resolve_leg)
    return calls


@pytest.mark.asyncio
async def test_refine_swap_promotes_alternate_and_resolves_two_legs(_leg_counter):
    service, _ = make_service([])
    repo = FakeResultRepository(_stored_payload())
    service.result_repository = repo

    updated = await service.refine_itinerary_slot(
        task_id="t-1",
        user_id="u-1",
        conversation_id="c-1",
        slot_index=1,
        selected_item_id="a1-alt",
    )

    block = updated["metadata"]["itinerary"]
    assert block["slots"][1]["chosen"]["id"] == "a1-alt"
    assert "a1" in [alt["id"] for alt in block["slots"][1]["alternates"]]
    # Only the two adjacent legs were re-resolved; persisted under the SAME id.
    assert len(_leg_counter) == 2
    assert repo.saved[0]["result_id"] == "res-1"
    assert repo.saved[0]["payload"]["metadata"]["itinerary"]["slots"][1]["chosen"]["id"] == "a1-alt"


@pytest.mark.asyncio
async def test_refine_prompt_regathers_one_slot_with_anchor(monkeypatch, _leg_counter):
    service, _ = make_service([])
    repo = FakeResultRepository(_stored_payload())
    service.result_repository = repo

    gather_calls = []

    async def fake_generic_task(**kwargs):
        gather_calls.append(kwargs)
        from service import RecommendationItem, RecommendationResult

        return RecommendationResult(
            restaurants=[],
            items=[
                RecommendationItem(
                    id="sea-view",
                    domain="attraction",
                    title="Sea View Deck",
                    rating=4.7,
                    raw={"gps_coordinates": {"latitude": 1.3012, "longitude": 103.8512}},
                )
            ],
            thinking_steps=[],
            confidence_score=0.9,
            metadata={},
        )

    service._execute_generic_domain_task = fake_generic_task

    updated = await service.refine_itinerary_slot(
        task_id="t-1",
        user_id="u-1",
        conversation_id="c-1",
        slot_index=1,
        prompt="somewhere with a sea view",
    )

    # One gather run for that slot only, anchored to the itinerary location.
    assert len(gather_calls) == 1
    assert gather_calls[0]["query"] == "somewhere with a sea view"
    assert gather_calls[0]["domain"] == "attraction"
    assert gather_calls[0]["preferences"]["location"] == "Sentosa"

    block = updated["metadata"]["itinerary"]
    assert block["slots"][1]["chosen"]["id"] == "sea-view"
    assert updated["items"][0]["id"] == "sea-view"
    assert updated["metadata"]["itinerary_revision"] == 2
    # Neighbors untouched; only the two adjacent legs re-resolved.
    assert block["slots"][0]["chosen"]["id"] == "a0"
    assert block["slots"][2]["chosen"]["id"] == "a2"
    assert len(_leg_counter) == 2


@pytest.mark.asyncio
async def test_refine_rejects_stale_revision():
    service, _ = make_service([])
    repo = FakeResultRepository(_stored_payload())
    service.result_repository = repo

    with pytest.raises(ItineraryConflictError):
        await service.refine_itinerary_slot(
            task_id="t-1",
            user_id="u-1",
            conversation_id="c-1",
            slot_index=1,
            selected_item_id="a1-alt",
            expected_revision=0,
        )
    assert repo.saved == []


@pytest.mark.asyncio
async def test_refine_validation_and_missing_result_errors():
    service, _ = make_service([])

    # No result store wired (unit-test mode) -> RuntimeError (503 at the API).
    with pytest.raises(RuntimeError):
        await service.refine_itinerary_slot(
            task_id="t-1", user_id="u", conversation_id="c", slot_index=0, selected_item_id="x"
        )

    repo = FakeResultRepository(None)
    service.result_repository = repo

    # Exactly one of selected_item_id / prompt.
    with pytest.raises(ValueError):
        await service.refine_itinerary_slot(task_id="t-1", user_id="u", conversation_id="c", slot_index=0)
    with pytest.raises(ValueError):
        await service.refine_itinerary_slot(
            task_id="t-1", user_id="u", conversation_id="c", slot_index=0, selected_item_id="x", prompt="y"
        )

    # No stored result -> LookupError (404 at the API).
    with pytest.raises(LookupError):
        await service.refine_itinerary_slot(
            task_id="t-1", user_id="u", conversation_id="c", slot_index=0, selected_item_id="x"
        )

    # Stored result that is not an itinerary -> ValueError (400 at the API).
    repo.payload = {"result_id": "res-2", "metadata": {"domain": "restaurant"}}
    with pytest.raises(ValueError):
        await service.refine_itinerary_slot(
            task_id="t-1", user_id="u", conversation_id="c", slot_index=0, selected_item_id="x"
        )


@pytest.mark.asyncio
async def test_refine_prompt_with_no_candidates_keeps_stored_result(monkeypatch):
    service, _ = make_service([])
    repo = FakeResultRepository(_stored_payload())
    service.result_repository = repo

    async def empty_generic_task(**kwargs):
        from service import RecommendationResult

        return RecommendationResult(
            restaurants=[], items=[], thinking_steps=[], confidence_score=0.4, metadata={}
        )

    service._execute_generic_domain_task = empty_generic_task

    with pytest.raises(ValueError, match="No candidates"):
        await service.refine_itinerary_slot(
            task_id="t-1", user_id="u-1", conversation_id="c-1", slot_index=1, prompt="something impossible"
        )
    assert repo.saved == []  # nothing persisted on failure
