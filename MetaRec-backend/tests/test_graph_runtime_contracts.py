import json
from tempfile import TemporaryDirectory

import pytest

from conftest import FakeAsyncClient, confirm_yes_json, make_service, query_intent_json
from langgraph_metarec.graphs.intention_graph import run_intention_graph
from task_storage import TaskStorage


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
