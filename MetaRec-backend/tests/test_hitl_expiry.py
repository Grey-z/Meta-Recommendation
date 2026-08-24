"""HITL collect/confirm expiry: created_at must be timezone-aware UTC.

A naive local created_at compared against UTC now reads hours off on any
non-UTC host: east of UTC the expiry never fires, west of UTC+1 every fresh
confirmation is instantly expired and Confirm clicks stop resolving.
"""
from datetime import datetime, timedelta, timezone

import pytest

from langgraph_metarec.graphs.request_orchestrator import HITL_EXPIRY_SECONDS, _is_collecting
from langgraph_metarec.nodes.preferences import build_collect_confirm_state_payload
from langgraph_metarec.state import GraphRuntimeState

pytestmark = pytest.mark.backend_unit


def _runtime_with_state(state):
    runtime = GraphRuntimeState()
    runtime.collect_confirm_state = state
    return runtime


def _awaiting_state(**overrides):
    state = build_collect_confirm_state_payload(
        query="spicy sichuan dinner",
        intent="query",
        preferences={},
        needs_confirmation=True,
        status="awaiting_confirmation",
    )
    state.update(overrides)
    return state


def test_created_at_is_timezone_aware_utc():
    state = _awaiting_state()
    created_at = datetime.fromisoformat(state["created_at"])
    assert created_at.tzinfo is not None
    assert abs((datetime.now(timezone.utc) - created_at).total_seconds()) < 60


def test_fresh_confirmation_is_collecting():
    assert _is_collecting(_runtime_with_state(_awaiting_state())) is True


def test_expired_confirmation_is_not_collecting():
    expired = (
        datetime.now(timezone.utc) - timedelta(seconds=HITL_EXPIRY_SECONDS + 60)
    ).isoformat()
    state = _awaiting_state(created_at=expired)
    assert _is_collecting(_runtime_with_state(state)) is False


def test_malformed_timestamp_treated_as_non_expired():
    state = _awaiting_state(created_at="not-a-timestamp")
    assert _is_collecting(_runtime_with_state(state)) is True


def test_inactive_status_is_not_collecting():
    state = _awaiting_state(status="confirmed")
    assert _is_collecting(_runtime_with_state(state)) is False
