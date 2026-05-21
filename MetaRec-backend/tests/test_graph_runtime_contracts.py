import json
from tempfile import TemporaryDirectory
from typing import TypedDict

import pytest
from langgraph.graph import END, START, StateGraph

from conftest import FakeAsyncClient, confirm_yes_json, make_service, query_intent_json
from langgraph_metarec.checkpointing import RuntimeCheckpointer, conversation_thread_id, task_thread_id
from langgraph_metarec.graphs.intention_graph import run_intention_graph
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
def test_sqlite_checkpointer_recovers_state_by_thread_id_after_restart():
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

    with TemporaryDirectory(prefix="metarec_checkpoint_") as tmpdir:
        thread_id = conversation_thread_id("u-check", "c-check", "branch-main")
        config = {"configurable": {"thread_id": thread_id}}

        first_owner = RuntimeCheckpointer(storage_dir=tmpdir)
        first_graph = build_counter_graph(first_owner.get())
        first_graph.invoke({"value": 1}, config)
        first_owner.close()

        second_owner = RuntimeCheckpointer(storage_dir=tmpdir)
        second_graph = build_counter_graph(second_owner.get())
        restored = second_graph.get_state(config)
        second_owner.close()

        assert restored.values["value"] == 2


@pytest.mark.runtime_contract
@pytest.mark.asyncio
async def test_collect_confirm_hitl_snapshot_is_json_serializable():
    result = await run_intention_graph(
        async_client=FakeAsyncClient([query_intent_json()]),
        query="Please recommend spicy restaurants in Chinatown",
        user_id="u-state",
        conversation_history=[],
        user_profile=None,
        is_in_query_flow=False,
        pending_preferences=None,
        current_preferences=None,
        conversation_id="c-state",
        message_id="m-state",
        branch_id="branch-main",
        timeline_cursor=None,
        model="fake-model",
        max_format_retries=0,
    )

    hitl_state = result.state.response_payload["hitl_state"]
    encoded = json.dumps(hitl_state, ensure_ascii=False)
    decoded = json.loads(encoded)

    assert decoded["node"] == "collect_confirm_preferences"
    assert decoded["status"] == "awaiting_confirmation"
    assert decoded["query"] == "Please recommend spicy restaurants in Chinatown"
    assert decoded["preferences"]["location"] == "Chinatown"
    assert result.state.conversation_id == "c-state"
    assert result.state.message_id == "m-state"
    assert result.state.branch_id == "branch-main"


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
    restarted_service.create_task = lambda *args, **kwargs: "task-after-resume"

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
