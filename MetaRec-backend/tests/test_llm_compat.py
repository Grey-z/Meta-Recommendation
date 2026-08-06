import json
from types import SimpleNamespace

import httpx
import pytest
from openai import OpenAI

from llm_compat import (
    create_chat_completion,
    create_chat_completion_async,
    prepare_chat_completion_request,
)


pytestmark = pytest.mark.backend_unit


def test_reasoning_model_uses_supported_openai_parameters():
    request = prepare_chat_completion_request(
        model="gpt-5.6-luna",
        messages=[],
        temperature=0.7,
        max_tokens=128,
    )

    assert "temperature" not in request
    assert "max_tokens" not in request
    assert request["extra_body"]["max_completion_tokens"] == 128


def test_compatible_provider_model_keeps_existing_parameters():
    request = prepare_chat_completion_request(
        model="glm-5.2",
        messages=[],
        temperature=0.7,
        max_tokens=128,
    )

    assert request["temperature"] == 0.7
    assert request["max_tokens"] == 128
    assert "extra_body" not in request


def test_pinned_sdk_sends_new_completion_token_field():
    captured = {}

    def handle_request(request):
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "created": 0,
                "model": "gpt-5.6-luna",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "ok"},
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    client = OpenAI(
        api_key="test-key",
        base_url="https://example.test/v1",
        http_client=httpx.Client(transport=httpx.MockTransport(handle_request)),
    )
    create_chat_completion(
        client,
        model="gpt-5.6-luna",
        messages=[{"role": "user", "content": "hi"}],
        temperature=0.7,
        max_tokens=16,
    )

    assert "temperature" not in captured
    assert "max_tokens" not in captured
    assert captured["max_completion_tokens"] == 16


@pytest.mark.asyncio
async def test_unknown_model_retries_without_rejected_temperature():
    calls = []

    async def create(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise RuntimeError(
                "Unsupported value: 'temperature' does not support 0.7 with this model. "
                "Only the default (1) value is supported."
            )
        return "ok"

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    result = await create_chat_completion_async(
        client,
        model="deployment-alias",
        messages=[],
        temperature=0.7,
    )

    assert result == "ok"
    assert calls[0]["temperature"] == 0.7
    assert "temperature" not in calls[1]


def test_sync_helper_does_not_retry_unrelated_errors():
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        raise RuntimeError("invalid API key")

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    with pytest.raises(RuntimeError, match="invalid API key"):
        create_chat_completion(
            client,
            model="deployment-alias",
            messages=[],
            temperature=0.2,
        )

    assert len(calls) == 1
