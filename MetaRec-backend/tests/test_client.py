import pytest

from client import create_agent_sync_client

_COMPAT_KEY_VARS = (
    "LLM_API_KEY",
    "OPENAI_COMPAT_API_KEY",
    "OPENAI_COMPATIBLE_API_KEY",
    "GROQ_API_KEY",
)


def _clear_compat_keys(monkeypatch):
    for name in _COMPAT_KEY_VARS:
        monkeypatch.delenv(name, raising=False)


@pytest.mark.backend_unit
def test_agent_client_prefers_openai_compatible_over_azure(monkeypatch):
    # Both providers configured: the OpenAI-compatible endpoint must win.
    monkeypatch.setenv("LLM_API_KEY", "compat-key")
    monkeypatch.setenv("OPENAI_API_KEY", "azure-key")
    monkeypatch.setenv("LLM_MODEL", "llama-test")
    monkeypatch.delenv("AGENT_PLANNING_MODEL", raising=False)
    monkeypatch.delenv("AGENT_SUMMARY_MODEL", raising=False)

    client, summary_model, planning_model = create_agent_sync_client()

    # AzureOpenAI subclasses OpenAI, so assert the exact type.
    assert type(client).__name__ == "OpenAI"
    assert summary_model == "llama-test"
    assert planning_model == "llama-test"


@pytest.mark.backend_unit
def test_agent_client_model_overrides_beat_llm_model(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "compat-key")
    monkeypatch.setenv("LLM_MODEL", "llama-test")
    monkeypatch.setenv("AGENT_PLANNING_MODEL", "planner-x")
    monkeypatch.setenv("AGENT_SUMMARY_MODEL", "summary-y")

    _, summary_model, planning_model = create_agent_sync_client()

    assert summary_model == "summary-y"
    assert planning_model == "planner-x"


@pytest.mark.backend_unit
def test_agent_client_falls_back_to_azure_without_compatible_key(monkeypatch):
    _clear_compat_keys(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "azure-key")
    monkeypatch.delenv("AZURE_AGENT_SUMMARY_MODEL", raising=False)
    monkeypatch.delenv("AZURE_AGENT_PLANNING_MODEL", raising=False)

    client, summary_model, planning_model = create_agent_sync_client()

    assert type(client).__name__ == "AzureOpenAI"
    assert summary_model == "o4-mini"
    assert planning_model == "gpt-4.1"


@pytest.mark.backend_unit
def test_agent_client_boots_without_any_credentials(monkeypatch):
    # No credentials at all: still return a compatible client so the app
    # starts; requests fail later with an explicit auth error.
    _clear_compat_keys(monkeypatch)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("LLM_MODEL", "llama-test")

    client, summary_model, planning_model = create_agent_sync_client()

    assert type(client).__name__ == "OpenAI"
    assert summary_model == "llama-test"
    assert planning_model == "llama-test"
