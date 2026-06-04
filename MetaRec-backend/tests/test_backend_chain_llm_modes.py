import asyncio
import types

import pytest

from service import RecommendationResult, Restaurant, ThinkingStep

from conftest import confirm_yes_json, make_service, query_intent_json


def _attach_fast_task_processor(service):
    async def _fast_process(
        self,
        task_id,
        query,
        preferences,
        user_id="default",
        session_id=None,
        use_online_agent=False,
        tool_tags=None,
    ):
        session_ctx = self._get_session_context(user_id, session_id)
        session_ctx["tasks"][task_id].update(
            {
                "status": "completed",
                "progress": 100,
                "message": "Recommendations ready!",
                "result": RecommendationResult(
                    restaurants=[
                        Restaurant(
                            id="mock-1",
                            name="Mock Bistro",
                            area="Chinatown",
                            cuisine="Sichuan",
                            price_per_person_sgd="20-30",
                            flavor_match=["Spicy"],
                            purpose_match=["Friends"],
                            why="Mocked result for chain testing",
                        )
                    ],
                    thinking_steps=[
                        ThinkingStep(step="done", description="done", status="completed", details="mocked")
                    ],
                ),
            }
        )

    service.run_recommendation_task_graph = types.MethodType(_fast_process, service)


async def _run_full_chain(service):
    user_id = "chain-user"
    session_id = "chain-session"

    first = await service.handle_user_request_async(
        "Please recommend a spicy casual restaurant in Chinatown.",
        user_id=user_id,
        session_id=session_id,
        conversation_history=[],
    )
    assert first["type"] == "confirmation"
    assert first["confirmation_request"].needs_confirmation

    second = await service.handle_user_request_async(
        "Yes, that's correct.",
        user_id=user_id,
        session_id=session_id,
        conversation_history=[{"role": "assistant", "content": first["confirmation_request"].message}],
    )
    assert second["type"] == "task_created"
    task_id = second["task_id"]

    await asyncio.sleep(0)
    status = service.get_task_status(task_id, user_id=user_id, session_id=session_id)
    assert status is not None
    assert status["status"] == "completed"
    assert status["result"].restaurants[0].name == "Mock Bistro"
    return first, second, status


@pytest.mark.chain_standard
@pytest.mark.asyncio
async def test_backend_chain_standard_mock_llm():
    service, fake_client = make_service(
        [
            query_intent_json(),
            "Great, I understood your preferences. Is this correct?",
            confirm_yes_json(),
        ],
        max_retries=2,
    )
    _attach_fast_task_processor(service)

    first, _, status = await _run_full_chain(service)

    assert "Is this correct" in first["confirmation_request"].message
    assert fake_client.chat.completions.calls == 3
    assert status["progress"] == 100


@pytest.mark.chain_retrial
@pytest.mark.asyncio
async def test_backend_chain_retrial_mock_llm():
    service, fake_client = make_service(
        [
            "not-a-json-response",
            query_intent_json(),
            "",
            "Got it. You prefer spicy casual options in Chinatown. Is this correct?",
            "still-not-json",
            confirm_yes_json(),
        ],
        max_retries=1,
    )
    _attach_fast_task_processor(service)

    first, _, status = await _run_full_chain(service)

    assert "Is this correct" in first["confirmation_request"].message
    # 3 logical LLM步骤，每步都先失败一次再成功 => 6 次调用
    assert fake_client.chat.completions.calls == 6
    assert status["status"] == "completed"


@pytest.mark.chain_fallback
@pytest.mark.asyncio
async def test_backend_chain_fallback_mock_llm_with_high_retry_cap():
    # 三个 LLM 步骤：analyze(query), confirmation message, analyze(confirm yes)
    # 每个步骤都持续无效，依赖重试上限+回退逻辑确保流程可终止。
    per_step_attempts = 7  # max_retries=6 => 7 attempts
    scripted = (
        ["INVALID"] * per_step_attempts
        + [""] * per_step_attempts
        + ["INVALID"] * per_step_attempts
    )
    service, fake_client = make_service(scripted, max_retries=6)
    _attach_fast_task_processor(service)

    first, _, status = await asyncio.wait_for(_run_full_chain(service), timeout=5)

    assert "Based on your request" in first["confirmation_request"].message
    assert fake_client.chat.completions.calls == per_step_attempts * 3
    assert status["status"] == "completed"
