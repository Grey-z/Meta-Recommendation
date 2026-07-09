"""Usage-scope wiring for fire-and-forget service work.

Regression for a token-accounting race: the rolling-summary task inherits the
spawning request's contextvars, so it used to record its LLM usage into the
request's ledger — which is flushed the moment the request returns. Any summary
finishing after that appended to a dead ledger and its tokens were silently
dropped. The summary must open its OWN scope and flush on its own completion.
"""
from __future__ import annotations

import asyncio

import pytest

import business_repositories
import llm_service
import llm_usage
from conftest import make_service
from conversation_context import SummaryUpdate


class _Usage:
    prompt_tokens = 11
    completion_tokens = 4
    total_tokens = 15


class _Response:
    usage = _Usage()
    model = "fast-model"


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_summary_usage_flushes_even_after_request_scope_closed(monkeypatch):
    service, _ = make_service([])

    flushed: list = []

    class FakeUsageRepository:
        async def record_events(self, *, user_id, conversation_id, task_id, events):
            flushed.append({"user_id": user_id, "conversation_id": conversation_id, "events": list(events)})
            return len(events)

    monkeypatch.setattr(business_repositories, "usage_repository", FakeUsageRepository())

    async def fake_summarize(client, prior_summary, new_turns, model=None):
        # What the real summarize_conversation does with the provider response.
        llm_usage.record_response_usage(_Response())
        return "updated summary"

    monkeypatch.setattr(llm_service, "summarize_conversation", fake_summarize)

    persisted_summaries: list = []

    async def fake_update(user_id, conversation_id, summary, watermark_id):
        persisted_summaries.append((user_id, conversation_id, summary, watermark_id))
        return True

    monkeypatch.setattr(
        business_repositories.conversation_repository,
        "update_conversation_context_summary",
        fake_update,
    )

    update = SummaryUpdate(prior_summary="", new_turns_text="User: hi", new_watermark_id="m-1")

    # Reproduce the production timing: the request's scope opens, spawns the
    # summary task (which snapshots the context), then closes BEFORE the summary
    # runs. The summary's usage must not land in the request's dead ledger.
    request_ledger = llm_usage.UsageLedger()
    token = llm_usage.push_ledger(request_ledger)
    try:
        summary_task = asyncio.create_task(service._apply_conversation_summary("u-1", "c-1", update))
    finally:
        llm_usage.reset_ledger(token)  # request scope exits (and would flush) here
    await summary_task

    assert persisted_summaries == [("u-1", "c-1", "updated summary", "m-1")]
    assert request_ledger.events == []  # nothing leaked into the closed request scope
    assert len(flushed) == 1
    assert flushed[0]["user_id"] == "u-1"
    assert flushed[0]["conversation_id"] == "c-1"
    assert [event.total_tokens for event in flushed[0]["events"]] == [15]


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_summary_spawn_keeps_a_task_reference(monkeypatch):
    """The spawned summary task must be strongly referenced until it completes
    (an unreferenced asyncio task may be garbage-collected mid-flight)."""
    service, _ = make_service([])

    release = asyncio.Event()

    async def fake_summarize(client, prior_summary, new_turns, model=None):
        await release.wait()
        return ""

    monkeypatch.setattr(llm_service, "summarize_conversation", fake_summarize)

    update = SummaryUpdate(prior_summary="", new_turns_text="User: hi", new_watermark_id="m-1")
    task = asyncio.create_task(service._apply_conversation_summary("u-1", "c-1", update))
    service._background_tasks.add(task)
    task.add_done_callback(service._background_tasks.discard)

    assert task in service._background_tasks
    release.set()
    await task
    await asyncio.sleep(0)  # let the call_soon-scheduled done-callback run
    assert task not in service._background_tasks  # discarded once done
