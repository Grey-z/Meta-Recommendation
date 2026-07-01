from __future__ import annotations

import os
import uuid
import asyncio

import pytest


@pytest.mark.runtime_contract
@pytest.mark.asyncio
async def test_postgres_business_repositories_round_trip():
    if not os.getenv("DATABASE_URL"):
        pytest.skip("DATABASE_URL is required for the Postgres business repository contract test")

    from business_db import dispose_async_engine
    from business_repositories import (
        auth_repository,
        conversation_repository,
        feedback_repository,
        profile_repository,
        result_repository,
        task_repository,
    )

    suffix = uuid.uuid4().hex

    try:
        auth = await auth_repository.get_or_create_guest(device_id=f"pytest-device-{suffix}")
        user_id = auth.user.id

        profile = {
            "demographics": {"age_group": "adult"},
            "dining_habits": {"favorite_cuisine": "sichuan"},
            "metadata": {"source": "pytest"},
        }
        assert await profile_repository.save_user_profile(user_id, profile)
        loaded_profile = await profile_repository.get_user_profile(user_id)
        assert loaded_profile["dining_habits"]["favorite_cuisine"] == "sichuan"
        assert await profile_repository.save_user_profile(
            user_id,
            {
                "demographics": {"age_group": ""},
                "dining_habits": {"favorite_cuisine": "", "spice_tolerance": "high"},
                "metadata": {"preferences": {"location": "Chinatown"}},
            },
        )
        loaded_profile = await profile_repository.get_user_profile(user_id)
        assert loaded_profile["demographics"]["age_group"] == "adult"
        assert loaded_profile["dining_habits"]["favorite_cuisine"] == "sichuan"
        assert loaded_profile["dining_habits"]["spice_tolerance"] == "high"
        assert loaded_profile["metadata"]["preferences"]["location"] == "Chinatown"

        conversation = await conversation_repository.create_conversation(
            user_id,
            title=f"PG repository smoke {suffix}",
        )
        conversation_id = conversation["id"]
        message_id = f"m-{suffix[:20]}"
        assert await conversation_repository.add_message(
            user_id,
            conversation_id,
            "user",
            "Find spicy dinner nearby",
            metadata={
                "message_id": message_id,
                "branch_id": "branch-main",
                "token_usage": {"total_tokens": 7},
            },
        )
        loaded_conversation = await conversation_repository.get_full_conversation(user_id, conversation_id)
        assert loaded_conversation is not None
        assert loaded_conversation["messages"][0]["id"] == message_id
        assert loaded_conversation["branches"]["branch-main"]["head_message_id"] == message_id

        task_id = str(uuid.uuid4())
        assert await task_repository.save(
            user_id,
            conversation_id,
            task_id,
            {
                "task_id": task_id,
                "status": "completed",
                "progress": 100,
                "message": "done",
                "metadata": {"branch_id": "branch-main"},
                "result": {"restaurants": []},
            },
        )
        loaded_task = await task_repository.load(user_id, conversation_id, task_id)
        assert loaded_task is not None
        assert loaded_task["metadata"]["branch_id"] == "branch-main"

        result_id = str(uuid.uuid4())
        assert await result_repository.save(
            user_id,
            conversation_id,
            "branch-main",
            result_id,
            {"message_id": message_id, "task_id": task_id, "restaurants": []},
        )
        assert await result_repository.load(user_id, conversation_id, "branch-main", result_id) == {
            "message_id": message_id,
            "task_id": task_id,
            "restaurants": [],
        }

        feedback_id = str(uuid.uuid4())
        assert await feedback_repository.save(
            user_id,
            conversation_id,
            "branch-main",
            feedback_id,
            {"message_id": message_id, "result_id": result_id, "label": "up", "rating": 1},
        )
        loaded_feedback = await feedback_repository.load(user_id, conversation_id, "branch-main", feedback_id)
        assert loaded_feedback is not None
        assert loaded_feedback["label"] == "up"
        assert loaded_feedback["rating"] == 1
    finally:
        await dispose_async_engine()


@pytest.mark.runtime_contract
@pytest.mark.asyncio
async def test_postgres_branch_fork_round_trip_persists_all_messages():
    """Regression: conversation_branches has composite FKs to conversation_nodes
    (head_message_id / root_message_id). _save_conversation must insert nodes before
    branches and never reference a missing node, otherwise the save transaction is
    rolled back and the message is silently lost (history disappears on reload)."""
    if not os.getenv("DATABASE_URL"):
        pytest.skip("DATABASE_URL is required for the Postgres branch fork contract test")

    from business_db import dispose_async_engine
    from business_repositories import auth_repository, conversation_repository

    suffix = uuid.uuid4().hex

    try:
        auth = await auth_repository.get_or_create_guest(device_id=f"pytest-branch-{suffix}")
        user_id = auth.user.id

        conversation = await conversation_repository.create_conversation(user_id, title="branch fork")
        conversation_id = conversation["id"]

        # First exchange on the main branch.
        assert await conversation_repository.add_message(
            user_id, conversation_id, "user", "find sushi",
            metadata={"message_id": "n-u1", "branch_id": "branch-main"},
        )
        assert await conversation_repository.add_message(
            user_id, conversation_id, "assistant", "Found 3",
            metadata={"message_id": "n-a1", "branch_id": "branch-main", "parent_message_id": "n-u1"},
        )

        # Edit the first user message -> fork a new branch (time travel).
        fork_branch = "branch-n-edit1"
        assert await conversation_repository.add_message(
            user_id, conversation_id, "user", "find ramen instead",
            metadata={
                "message_id": "n-u2",
                "branch_id": fork_branch,
                "fork_from_message_id": "n-u1",
                "revision_of_message_id": "n-u1",
                "time_travel": {"mode": "branch_fork", "replay_from_message_id": "n-u1", "branch_id": fork_branch},
            },
        )
        assert await conversation_repository.add_message(
            user_id, conversation_id, "assistant", "Found ramen",
            metadata={"message_id": "n-a2", "branch_id": fork_branch, "parent_message_id": "n-u2"},
        )

        loaded = await conversation_repository.get_full_conversation(user_id, conversation_id)
        assert loaded is not None
        # All four messages survive the delete+reinsert save cycle.
        assert {m["id"] for m in loaded["messages"]} == {"n-u1", "n-a1", "n-u2", "n-a2"}
        assert set(loaded["branches"]) == {"branch-main", fork_branch}
        assert loaded["branches"]["branch-main"]["head_message_id"] == "n-a1"
        assert loaded["branches"][fork_branch]["head_message_id"] == "n-a2"
        assert loaded["active_branch_id"] == fork_branch

        # Switching the active branch must not drop any messages either.
        assert await conversation_repository.set_active_branch(user_id, conversation_id, "branch-main", "n-u1")
        switched = await conversation_repository.get_full_conversation(user_id, conversation_id)
        assert switched["active_branch_id"] == "branch-main"
        assert len(switched["messages"]) == 4
    finally:
        await dispose_async_engine()


@pytest.mark.runtime_contract
@pytest.mark.asyncio
async def test_postgres_recommendation_result_persistence_and_fk_guard():
    """recommendation_results is the durable source of truth for task output.
    Saving must (a) survive a missing task_id without rolling back (FK guard) and
    (b) be retrievable by task_id, scoped to the owning user/conversation."""
    if not os.getenv("DATABASE_URL"):
        pytest.skip("DATABASE_URL is required for the Postgres result repository contract test")

    from business_db import dispose_async_engine
    from business_repositories import auth_repository, task_repository, result_repository

    suffix = uuid.uuid4().hex

    try:
        auth = await auth_repository.get_or_create_guest(device_id=f"pytest-result-{suffix}")
        user_id = auth.user.id
        conversation_id = str(uuid.uuid4())
        branch_id = "branch-main"

        # (a) FK guard: a result referencing a non-existent task must still save.
        orphan_task = str(uuid.uuid4())
        orphan_result_id = str(uuid.uuid4())
        assert await result_repository.save(
            user_id, conversation_id, branch_id, orphan_result_id,
            {"result_id": orphan_result_id, "task_id": orphan_task, "restaurants": []},
        )

        # (b) With a real task row, the result links and is retrievable by task_id.
        task_id = str(uuid.uuid4())
        assert await task_repository.save(
            user_id, conversation_id, task_id,
            {"task_id": task_id, "status": "completed", "progress": 100, "message": "done",
             "result": {"restaurants": [{"name": "Sushi Go"}]}, "metadata": {"branch_id": branch_id}},
        )
        result_id = str(uuid.uuid4())
        assert await result_repository.save(
            user_id, conversation_id, branch_id, result_id,
            {"result_id": result_id, "task_id": task_id, "branch_id": branch_id,
             "restaurants": [{"name": "Sushi Go"}]},
        )

        by_task = await result_repository.load_by_task(user_id, conversation_id, task_id)
        assert by_task is not None
        assert by_task["restaurants"][0]["name"] == "Sushi Go"
        # Scope isolation: a different conversation cannot read it.
        assert await result_repository.load_by_task(user_id, str(uuid.uuid4()), task_id) is None
    finally:
        await dispose_async_engine()


@pytest.mark.runtime_contract
@pytest.mark.asyncio
async def test_postgres_feedback_submit_requires_owned_result_target():
    if not os.getenv("DATABASE_URL"):
        pytest.skip("DATABASE_URL is required for the Postgres feedback repository contract test")

    from business_db import dispose_async_engine
    from business_models import derive_result_id
    from business_repositories import auth_repository, feedback_repository, result_repository, task_repository

    suffix = uuid.uuid4().hex

    try:
        auth = await auth_repository.get_or_create_guest(device_id=f"pytest-feedback-{suffix}")
        other = await auth_repository.get_or_create_guest(device_id=f"pytest-feedback-other-{suffix}")
        user_id = auth.user.id
        conversation_id = str(uuid.uuid4())
        branch_id = "branch-main"
        task_id = str(uuid.uuid4())
        result_id = derive_result_id(task_id, branch_id)

        assert await task_repository.save(
            user_id,
            conversation_id,
            task_id,
            {
                "task_id": task_id,
                "status": "completed",
                "progress": 100,
                "message": "done",
                "metadata": {"branch_id": branch_id},
                "result": {"restaurants": [{"name": "Feedback Sushi"}]},
            },
        )
        assert await result_repository.save(
            user_id,
            conversation_id,
            branch_id,
            result_id,
            {
                "result_id": result_id,
                "task_id": task_id,
                "branch_id": branch_id,
                "restaurants": [{"name": "Feedback Sushi"}],
            },
        )

        by_result = await feedback_repository.submit(
            user_id=user_id,
            sentiment="up",
            result_id=result_id,
            conversation_id=conversation_id,
            branch_id=branch_id,
        )
        assert by_result["result_id"] == result_id
        assert by_result["rating"] == 5

        by_task = await feedback_repository.submit(
            user_id=user_id,
            sentiment="down",
            reason="too_far",
            task_id=task_id,
            conversation_id=conversation_id,
            branch_id=branch_id,
        )
        assert by_task["feedback_id"] == by_result["feedback_id"]
        assert by_task["result_id"] == result_id
        assert by_task["reason"] == "too_far"

        with pytest.raises(ValueError, match="feedback target not found"):
            await feedback_repository.submit(user_id=user_id, sentiment="up", result_id=str(uuid.uuid4()))
        with pytest.raises(ValueError, match="feedback target not found"):
            await feedback_repository.submit(user_id=other.user.id, sentiment="up", result_id=result_id)
        with pytest.raises(ValueError, match="feedback target not found"):
            await feedback_repository.submit(
                user_id=user_id,
                sentiment="up",
                result_id=result_id,
                conversation_id=str(uuid.uuid4()),
            )
        with pytest.raises(ValueError, match="feedback target not found"):
            await feedback_repository.submit(
                user_id=user_id,
                sentiment="up",
                result_id=result_id,
                branch_id="branch-other",
            )
    finally:
        await dispose_async_engine()


@pytest.mark.runtime_contract
@pytest.mark.asyncio
async def test_postgres_user_role_defaults_and_promotion():
    """New users default to the USER role; promote_admins flips registered users
    to ADMIN (idempotent) and skips unknown / guest-only emails."""
    if not os.getenv("DATABASE_URL"):
        pytest.skip("DATABASE_URL is required for the Postgres role contract test")

    from business_db import dispose_async_engine
    from business_repositories import auth_repository
    from business_models import UserRole

    suffix = uuid.uuid4().hex
    email = f"role-{suffix}@example.com"

    try:
        registered = await auth_repository.register(email=email, password="password123")
        assert registered.user.role == UserRole.USER

        guest = await auth_repository.get_or_create_guest(device_id=f"role-guest-{suffix}")
        assert guest.user.role == UserRole.USER

        assert await auth_repository.promote_admins([email]) == 1
        # Idempotent + unknown emails skipped.
        assert await auth_repository.promote_admins([f"missing-{suffix}@example.com"]) == 0

        relogged = await auth_repository.login(email=email, password="password123")
        assert relogged.user.role == UserRole.ADMIN
    finally:
        await dispose_async_engine()


@pytest.mark.runtime_contract
@pytest.mark.asyncio
async def test_postgres_guest_login_is_idempotent_for_concurrent_same_device():
    if not os.getenv("DATABASE_URL"):
        pytest.skip("DATABASE_URL is required for the Postgres guest login contract test")

    from business_db import dispose_async_engine
    from business_repositories import auth_repository

    device_id = f"pytest-race-device-{uuid.uuid4().hex}"

    try:
        sessions = await asyncio.gather(
            *[
                auth_repository.get_or_create_guest(device_id=device_id, user_agent="pytest")
                for _ in range(4)
            ]
        )
        assert len({payload.user.id for payload in sessions}) == 1
        assert len({payload.session.id for payload in sessions}) == 4
    finally:
        await dispose_async_engine()


@pytest.mark.runtime_contract
@pytest.mark.asyncio
async def test_postgres_llm_usage_feeds_dashboard_token_stats():
    """Usage events written by the ledger flush are summed by the admin token card,
    end-to-end through PostgresUsageRepository -> get_stats."""
    if not os.getenv("DATABASE_URL"):
        pytest.skip("DATABASE_URL is required for the Postgres LLM usage contract test")

    from business_db import dispose_async_engine
    from business_repositories import admin_repository, usage_repository
    from llm_usage import UsageEvent

    try:
        before = (await admin_repository.get_stats())["tokens"]

        written = await usage_repository.record_events(
            user_id=str(uuid.uuid4()),
            conversation_id=None,
            task_id=str(uuid.uuid4()),
            events=[
                UsageEvent(model="gpt-4o", prompt_tokens=100, completion_tokens=40, total_tokens=140, cost_usd=0.5),
                UsageEvent(model="gpt-4o", prompt_tokens=10, completion_tokens=5, total_tokens=15, cost_usd=0.05),
            ],
        )
        assert written == 2

        after = (await admin_repository.get_stats())["tokens"]
        assert after["total_tokens"] == before["total_tokens"] + 155
        assert after["prompt_tokens"] == before["prompt_tokens"] + 110
        assert after["completion_tokens"] == before["completion_tokens"] + 45
        assert round(after["cost_usd"] - before["cost_usd"], 6) == 0.55
        assert after["last_7d_total_tokens"] >= 155

        # Empty flush is a no-op and writes nothing.
        assert await usage_repository.record_events(
            user_id=None, conversation_id=None, task_id=None, events=[]
        ) == 0
    finally:
        await dispose_async_engine()
