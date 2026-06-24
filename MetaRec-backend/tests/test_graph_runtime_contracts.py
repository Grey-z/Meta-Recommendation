import json
import os
from tempfile import TemporaryDirectory
import uuid
from typing import TypedDict

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from conftest import FakeAsyncClient, confirm_yes_json, make_service, query_intent_json
from langgraph_metarec.checkpointing import RuntimeCheckpointer, conversation_thread_id, task_thread_id
from langgraph_metarec.state import GraphRuntimeState, IntentResult, ProgressEvent, TaskStatusProjection
from task_storage import TaskStorage


@pytest.mark.runtime_contract
def test_graph_runtime_state_is_json_serializable():
    state = GraphRuntimeState(
        user_id="u-runtime",
        conversation_id="c-runtime",
        branch_id="branch-main",
        message_id="m-runtime",
        thread_id=conversation_thread_id("u-runtime", "c-runtime", "branch-main"),
        task_id="task-1",
        task_thread_id=task_thread_id("u-runtime", "c-runtime", "branch-main", "task-1"),
        query="Recommend spicy restaurants",
        intent_result=IntentResult(intent="query", confidence=0.9, preferences={"location": "Chinatown"}),
        collect_confirm_state={"status": "awaiting_confirmation", "preferences": {"location": "Chinatown"}},
        routing_route={"domain": "restaurant", "status": "ready"},
        task_status=TaskStatusProjection(task_id="task-1", status="processing", progress=40),
        progress_events=[ProgressEvent(stage="routing", progress=20, message="Routing")],
        response_payload={"type": "confirmation"},
    )

    encoded = json.dumps(state.to_checkpoint(), ensure_ascii=False)
    decoded = GraphRuntimeState.from_checkpoint(json.loads(encoded))

    assert decoded.schema_version == "2026-05-21.v1"
    assert decoded.thread_id == "u-runtime:c-runtime:branch-main"
    assert decoded.task_thread_id == "u-runtime:c-runtime:branch-main:task-1"
    assert decoded.runtime_metadata()["collect_confirm_status"] == "awaiting_confirmation"


@pytest.mark.runtime_contract
def test_postgres_checkpointer_recovers_state_by_thread_id_after_restart():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL is required for the Postgres checkpointer contract test")

    class CounterState(TypedDict):
        value: int

    def build_counter_graph(checkpointer):
        def increment(state: CounterState) -> CounterState:
            return {"value": state.get("value", 0) + 1}

        graph = StateGraph(CounterState)
        graph.add_node("increment", increment)
        graph.add_edge(START, "increment")
        graph.add_edge("increment", END)
        return graph.compile(checkpointer=checkpointer)

    thread_id = conversation_thread_id("u-check", f"c-check-{uuid.uuid4().hex}", "branch-main")
    config = {"configurable": {"thread_id": thread_id}}

    first_owner = RuntimeCheckpointer(conn_string=database_url)
    first_graph = build_counter_graph(first_owner.get())
    first_graph.invoke({"value": 1}, config)
    first_owner.close()

    second_owner = RuntimeCheckpointer(conn_string=database_url)
    second_graph = build_counter_graph(second_owner.get())
    restored = second_graph.get_state(config)
    second_owner.close()

    assert restored.values["value"] == 2


@pytest.mark.runtime_contract
@pytest.mark.asyncio
async def test_async_postgres_checkpointer_persists_state():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL is required for the async Postgres checkpointer contract test")

    class CounterState(TypedDict):
        value: int

    def increment(state: CounterState) -> CounterState:
        return {"value": state.get("value", 0) + 1}

    graph_builder = StateGraph(CounterState)
    graph_builder.add_node("increment", increment)
    graph_builder.add_edge(START, "increment")
    graph_builder.add_edge("increment", END)

    thread_id = conversation_thread_id("u-async-check", f"c-check-{uuid.uuid4().hex}", "branch-main")
    config = {"configurable": {"thread_id": thread_id}}
    owner = RuntimeCheckpointer(conn_string=database_url)
    try:
        graph = graph_builder.compile(checkpointer=await owner.aget())
        await graph.ainvoke({"value": 1}, config)
        restored = await graph.aget_state(config)
        assert restored.values["value"] == 2
    finally:
        await owner.aclose()


@pytest.mark.runtime_contract
def test_postgres_checkpointer_requires_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("METAREC_CHECKPOINTER_BACKEND", raising=False)

    with pytest.raises(RuntimeError, match="DATABASE_URL is required"):
        RuntimeCheckpointer().get()


@pytest.mark.runtime_contract
def test_memory_checkpointer_backend_must_be_explicit(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("METAREC_CHECKPOINTER_BACKEND", "memory")

    owner = RuntimeCheckpointer()
    try:
        assert isinstance(owner.get(), MemorySaver)
    finally:
        owner.close()


@pytest.mark.runtime_contract
@pytest.mark.asyncio
async def test_hitl_snapshot_can_resume_confirmation_after_service_restart():
    first_service, _ = make_service(
        [
            query_intent_json(),
            "I found your restaurant preferences. Is this correct?",
        ]
    )
    first_result = await first_service.handle_user_request_async(
        "Recommend spicy restaurants in Chinatown",
        user_id="u-resume",
        session_id="c-resume",
        conversation_history=[],
        branch_id="branch-main",
    )
    hitl_state = first_result["hitl_state"]

    restarted_service, _ = make_service([confirm_yes_json()])

    async def fake_create_task_async(*args, **kwargs):
        return "task-after-resume"

    restarted_service.create_task_async = fake_create_task_async

    resumed = await restarted_service.handle_user_request_async(
        "Yes, that's correct",
        user_id="u-resume",
        session_id="c-resume",
        conversation_history=[],
        branch_id="branch-main",
        hitl_state=hitl_state,
    )

    assert resumed["type"] == "task_created"
    assert resumed["task_id"] == "task-after-resume"
    assert resumed["preferences"]["location"] == "Chinatown"


@pytest.mark.runtime_contract
@pytest.mark.asyncio
async def test_hitl_confirm_action_bypasses_llm_intent_classification():
    first_service, _ = make_service(
        [
            query_intent_json(),
            "I found your restaurant preferences. Is this correct?",
        ]
    )
    first_result = await first_service.handle_user_request_async(
        "Recommend spicy restaurants in Chinatown",
        user_id="u-action-confirm",
        session_id="c-action-confirm",
        conversation_history=[],
        branch_id="branch-main",
    )

    # This fake LLM would incorrectly classify the confirm turn as a new query.
    # The UI-level HITL action is authoritative, so the resumed call must not
    # ask the model again or generate a second confirmation.
    restarted_service, fake = make_service([query_intent_json("Wrong path")])

    async def fake_create_task_async(*args, **kwargs):
        return "task-action-confirm"

    restarted_service.create_task_async = fake_create_task_async

    resumed = await restarted_service.handle_user_request_async(
        "Yes, that's correct",
        user_id="u-action-confirm",
        session_id="c-action-confirm",
        conversation_history=[],
        branch_id="branch-main",
        hitl_state={**first_result["hitl_state"], "action": "confirm"},
    )

    assert resumed["type"] == "task_created"
    assert resumed["task_id"] == "task-action-confirm"
    assert fake.chat.completions.calls == 0


@pytest.mark.runtime_contract
@pytest.mark.asyncio
async def test_query_confirmation_preserves_profile_preferences_when_prompt_omits_them():
    """Regression: asking for a cafe (prompt mentions only a restaurant type)
    must confirm against the user's stored profile budget, not reset it to the
    20-60 default. The LLM emits the default budget when the user said nothing;
    the orchestrator must merge the extracted prefs onto the loaded baseline."""
    cafe_intent = json.dumps({
        "intent": "query",
        "reply": "Sure, let me find a cafe.",
        "confidence": 0.9,
        "preferences": {
            "restaurant_types": ["cafe"],
            "flavor_profiles": ["any"],
            "dining_purpose": "any",
            "budget_range": {"min": 20, "max": 60, "currency": "SGD", "per": "person"},
            "location": "any",
        },
    })
    service, _ = make_service([cafe_intent, "Confirm your cafe preferences?"])

    class _ProfileRepo:
        async def get_user_profile(self, _user_id):
            return {
                "metadata": {
                    "preferences": {
                        "restaurant_types": ["any"],
                        "flavor_profiles": ["any"],
                        "dining_purpose": "any",
                        "budget_range": {"min": 5, "max": 10, "currency": "SGD", "per": "person"},
                        "location": "Chinatown",
                    }
                }
            }

    service.profile_repository = _ProfileRepo()

    result = await service.handle_user_request_async(
        "Find me a Kopi C",
        user_id="u-pref",
        session_id="c-pref",
        conversation_history=[],
        branch_id="branch-main",
        domain_lock="restaurant",
    )

    assert result["type"] == "confirmation"
    prefs = result["confirmation_request"].preferences
    assert prefs["restaurant_types"] == ["cafe"]          # extracted from the prompt
    assert prefs["budget_range"]["min"] == 5              # profile budget preserved
    assert prefs["budget_range"]["max"] == 10
    assert prefs["location"] == "Chinatown"               # profile location preserved


@pytest.mark.runtime_contract
@pytest.mark.asyncio
async def test_in_flow_query_refine_generates_confirmation_only_once():
    """An in-flow query refinement must produce exactly one confirmation LLM call
    (owned by domain_dispatch), not generate-then-discard a second one in
    collect_confirm. Two query turns => 2 intent + 2 confirmation = 4 LLM calls;
    the old double-generation made it 5."""
    cheaper = json.dumps({
        "intent": "query",
        "reply": "Cheaper, got it.",
        "confidence": 0.9,
        "preferences": {
            "restaurant_types": ["casual"],
            "flavor_profiles": ["spicy"],
            "dining_purpose": "friends",
            "budget_range": {"min": 10, "max": 25, "currency": "SGD", "per": "person"},
            "location": "Chinatown",
        },
    })
    service, fake = make_service([
        query_intent_json(),                  # turn 1 intent
        "Confirm Chinatown preferences?",     # turn 1 confirmation
        cheaper,                              # turn 2 intent (in-flow refine)
        "Confirm the cheaper preferences?",   # turn 2 confirmation (single)
    ])

    first = await service.handle_user_request_async(
        "Recommend spicy restaurants in Chinatown",
        user_id="u-once", session_id="c-once",
        conversation_history=[], branch_id="branch-main", domain_lock="restaurant",
    )
    assert first["type"] == "confirmation"

    second = await service.handle_user_request_async(
        "Actually make it cheaper",
        user_id="u-once", session_id="c-once",
        conversation_history=[], branch_id="branch-main", domain_lock="restaurant",
    )
    assert second["type"] == "confirmation"
    assert second["confirmation_request"].preferences["budget_range"]["max"] == 25
    assert fake.chat.completions.calls == 4


@pytest.mark.runtime_contract
@pytest.mark.asyncio
async def test_hitl_reject_forces_preference_revision_even_when_llm_returns_query():
    first_service, _ = make_service(
        [
            query_intent_json(),
            "I found your restaurant preferences. Is this correct?",
        ]
    )
    first_result = await first_service.handle_user_request_async(
        "Recommend spicy restaurants in Chinatown",
        user_id="u-reject",
        session_id="c-reject",
        conversation_history=[],
        branch_id="branch-main",
    )
    hitl_state = {**first_result["hitl_state"], "action": "reject"}

    restarted_service, _ = make_service([query_intent_json("I can update that.")])
    rejected = await restarted_service.handle_user_request_async(
        "No, that's not quite right",
        user_id="u-reject",
        session_id="c-reject",
        conversation_history=[],
        branch_id="branch-main",
        hitl_state=hitl_state,
    )

    assert rejected["type"] == "confirmation"
    assert rejected["intent"] == "confirmation_no"
    assert rejected["hitl_state"]["status"] == "awaiting_clarification"
    assert rejected["confirmation_request"].preferences["location"] == "Chinatown"


@pytest.mark.runtime_contract
@pytest.mark.asyncio
async def test_collect_confirm_checkpoint_is_isolated_by_branch_without_hitl_snapshot():
    service, _ = make_service(
        [
            query_intent_json(),
            "Confirm the Chinatown restaurant preferences?",
            query_intent_json(),
            confirm_yes_json(),
        ]
    )

    first = await service.handle_user_request_async(
        "Recommend spicy restaurants in Chinatown",
        user_id="u-branch",
        session_id="c-branch",
        conversation_history=[],
        branch_id="branch-main",
    )
    second = await service.handle_user_request_async(
        "Recommend a relaxing music playlist",
        user_id="u-branch",
        session_id="c-branch",
        conversation_history=[],
        branch_id="branch-edit",
    )
    async def fake_create_task_async(*args, **kwargs):
        return "task-branch-main"

    service.create_task_async = fake_create_task_async
    resumed = await service.handle_user_request_async(
        "Yes, that's correct",
        user_id="u-branch",
        session_id="c-branch",
        conversation_history=[],
        branch_id="branch-main",
    )

    assert first["type"] == "confirmation"
    assert second["type"] == "confirmation"
    assert second["domain"] == "music"
    assert second["routing"]["status"] == "ready"
    assert second["routing"]["execution_domain"] == "music"
    assert resumed["type"] == "task_created"
    assert resumed["task_id"] == "task-branch-main"
    assert resumed["preferences"]["location"] == "Chinatown"


@pytest.mark.runtime_contract
def test_task_status_persists_and_stays_scoped_after_service_restart():
    with TemporaryDirectory(prefix="metarec_task_state_") as tmpdir:
        service, _ = make_service([])
        service.task_storage = TaskStorage(storage_dir=tmpdir)
        service._save_task_status(
            "u-task",
            "c-task",
            "task-1",
            {
                "task_id": "task-1",
                "status": "processing",
                "progress": 40,
                "message": "Running graph",
                "user_id": "u-task",
                "conversation_id": "c-task",
            },
        )

        restarted_service, _ = make_service([])
        restarted_service.task_storage = TaskStorage(storage_dir=tmpdir)

        restored = restarted_service.get_task_status("task-1", user_id="u-task", session_id="c-task")

        assert restored is not None
        assert restored["status"] == "processing"
        assert restored["progress"] == 40
        assert restarted_service.get_task_status("task-1", user_id="u-task", session_id="other") is None
