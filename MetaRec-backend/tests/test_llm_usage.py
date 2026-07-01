from __future__ import annotations

import pytest

import llm_usage
from llm_usage import (
    UsageLedger,
    current_ledger,
    estimate_cost,
    push_ledger,
    record_response_usage,
    reset_ledger,
)


class _Usage:
    def __init__(self, prompt, completion, total=None):
        self.prompt_tokens = prompt
        self.completion_tokens = completion
        self.total_tokens = total if total is not None else prompt + completion


class _Response:
    def __init__(self, usage, model="gpt-4o"):
        self.usage = usage
        self.model = model


class _SyncCompletions:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class _SyncChat:
    def __init__(self, response):
        self.completions = _SyncCompletions(response)


class _SyncClient:
    def __init__(self, response):
        self.chat = _SyncChat(response)


@pytest.fixture(autouse=True)
def _isolate_ledger():
    # Guarantee no ledger leaks across tests via the module-level ContextVar.
    token = push_ledger(None)  # type: ignore[arg-type]
    try:
        yield
    finally:
        reset_ledger(token)


@pytest.fixture(autouse=True)
def _clear_price_env(monkeypatch):
    for name in ("LLM_PRICE_INPUT_PER_1M", "LLM_PRICE_OUTPUT_PER_1M", "LLM_PRICE_TABLE_JSON"):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.backend_unit
def test_record_is_noop_without_active_ledger():
    assert current_ledger() is None
    # Must not raise and must record nothing when there is no scope.
    assert record_response_usage(_Response(_Usage(10, 5))) is None


@pytest.mark.backend_unit
def test_ledger_accumulates_totals_across_calls():
    ledger = UsageLedger()
    token = push_ledger(ledger)
    try:
        record_response_usage(_Response(_Usage(100, 50)))
        record_response_usage(_Response(_Usage(200, 25)))
    finally:
        reset_ledger(token)

    assert [e.prompt_tokens for e in ledger.events] == [100, 200]
    totals = ledger.totals
    assert totals["prompt_tokens"] == 300
    assert totals["completion_tokens"] == 75
    assert totals["total_tokens"] == 375
    # No prices configured -> cost stays zero.
    assert totals["cost_usd"] == 0.0


@pytest.mark.backend_unit
def test_cost_defaults_to_zero():
    assert estimate_cost("gpt-4o", 1_000_000, 1_000_000) == 0.0


@pytest.mark.backend_unit
def test_cost_uses_global_env_prices(monkeypatch):
    monkeypatch.setenv("LLM_PRICE_INPUT_PER_1M", "2")
    monkeypatch.setenv("LLM_PRICE_OUTPUT_PER_1M", "4")
    # 0.5M prompt * $2/1M + 0.25M completion * $4/1M = 1.0 + 1.0 = 2.0
    assert estimate_cost("any-model", 500_000, 250_000) == 2.0


@pytest.mark.backend_unit
def test_cost_uses_per_model_table_over_global(monkeypatch):
    monkeypatch.setenv("LLM_PRICE_INPUT_PER_1M", "1")
    monkeypatch.setenv("LLM_PRICE_OUTPUT_PER_1M", "1")
    monkeypatch.setenv("LLM_PRICE_TABLE_JSON", '{"gpt-4o": {"input": 10, "output": 30}}')
    # gpt-4o uses the table: 1M in * $10 + 1M out * $30 = 40.0
    assert estimate_cost("gpt-4o", 1_000_000, 1_000_000) == 40.0
    # An unlisted model falls back to the globals: 1M + 1M = 2.0
    assert estimate_cost("other", 1_000_000, 1_000_000) == 2.0


@pytest.mark.backend_unit
def test_record_computes_cost_and_prefers_response_model(monkeypatch):
    monkeypatch.setenv("LLM_PRICE_TABLE_JSON", '{"real-model": {"input": 10, "output": 20}}')
    ledger = UsageLedger()
    token = push_ledger(ledger)
    try:
        # response.model wins over the hint, so the table entry is applied.
        event = record_response_usage(_Response(_Usage(1_000_000, 1_000_000), model="real-model"), "hint-model")
    finally:
        reset_ledger(token)

    assert event is not None
    assert event.model == "real-model"
    assert event.cost_usd == 30.0  # 1M*10 + 1M*20 = 30


@pytest.mark.backend_unit
def test_record_accepts_dict_usage_and_derives_total():
    ledger = UsageLedger()
    token = push_ledger(ledger)
    try:
        resp = {"usage": {"prompt_tokens": 7, "completion_tokens": 3}, "model": "m"}
        event = record_response_usage(resp)
    finally:
        reset_ledger(token)

    assert event is not None
    assert event.total_tokens == 10  # derived from prompt + completion
    assert event.model == "m"


@pytest.mark.backend_unit
def test_record_ignores_response_without_usage():
    ledger = UsageLedger()
    token = push_ledger(ledger)
    try:
        assert record_response_usage(_Response(None)) is None
    finally:
        reset_ledger(token)
    assert ledger.events == []


@pytest.mark.backend_unit
def test_restaurant_legacy_agent_calls_record_usage():
    from agent.agent_plan import run_demo
    from agent.agent_summary import summarize_recommendations

    ledger = UsageLedger()
    token = push_ledger(ledger)
    try:
        run_demo(_SyncClient(_Response(_Usage(11, 5), model="planner-model")), "find hotpot", "planner-model")
        summarize_recommendations(
            _SyncClient(_Response(_Usage(17, 9), model="summary-model")),
            {"query": "find hotpot"},
            [],
            [],
            [],
            "summary-model",
        )
    finally:
        reset_ledger(token)

    assert [event.model for event in ledger.events] == ["planner-model", "summary-model"]
    assert [event.total_tokens for event in ledger.events] == [16, 26]
