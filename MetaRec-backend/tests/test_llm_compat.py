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


# --- Tool-name compatibility ------------------------------------------------
#
# Strict OpenAI-compatible providers reject function names outside
# ^[a-zA-Z0-9_-]+$ with a 400 before the model runs. MetaRec's registry names
# are dotted ("gmap.search"), which is exactly the crash seen in the
# restaurant planner. The shim sanitizes names on the wire and restores them
# in the response so downstream registry dispatch still matches.


def _tool(name):
    return {
        "type": "function",
        "function": {"name": name, "parameters": {"type": "object"}},
    }


def _tool_call_response(name):
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 0,
        "model": "glm-5.2",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "type": "function",
                            "function": {"name": name, "arguments": "{}"},
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
    }


def test_dotted_tool_names_are_sanitized_on_the_wire_and_restored_in_response():
    captured = {}

    def handle_request(request):
        captured.update(json.loads(request.content))
        return httpx.Response(200, json=_tool_call_response("gmap_search"))

    client = OpenAI(
        api_key="test-key",
        base_url="https://example.test/v1",
        http_client=httpx.Client(transport=httpx.MockTransport(handle_request)),
    )
    tools = [_tool("gmap.search"), _tool("xhs.search")]
    completion = create_chat_completion(
        client,
        model="glm-5.2",
        messages=[{"role": "user", "content": "plan"}],
        tools=tools,
        tool_choice={"type": "function", "function": {"name": "gmap.search"}},
    )

    wire_names = [tool["function"]["name"] for tool in captured["tools"]]
    assert wire_names == ["gmap_search", "xhs_search"]
    assert captured["tool_choice"]["function"]["name"] == "gmap_search"
    # The caller's tool list (typically a module constant) is never mutated.
    assert tools[0]["function"]["name"] == "gmap.search"
    # Downstream parses the ORIGINAL name, so registry dispatch still matches.
    assert completion.choices[0].message.tool_calls[0].function.name == "gmap.search"


def test_valid_tool_names_go_over_the_wire_untouched():
    captured = {}

    def handle_request(request):
        captured.update(json.loads(request.content))
        return httpx.Response(200, json=_tool_call_response("plain_tool"))

    client = OpenAI(
        api_key="test-key",
        base_url="https://example.test/v1",
        http_client=httpx.Client(transport=httpx.MockTransport(handle_request)),
    )
    completion = create_chat_completion(
        client,
        model="glm-5.2",
        messages=[{"role": "user", "content": "plan"}],
        tools=[_tool("plain_tool")],
    )

    assert [tool["function"]["name"] for tool in captured["tools"]] == ["plain_tool"]
    assert completion.choices[0].message.tool_calls[0].function.name == "plain_tool"


def test_sanitized_tool_name_collisions_stay_distinct():
    captured = {}

    def handle_request(request):
        captured.update(json.loads(request.content))
        return httpx.Response(200, json=_tool_call_response("a_b_"))

    client = OpenAI(
        api_key="test-key",
        base_url="https://example.test/v1",
        http_client=httpx.Client(transport=httpx.MockTransport(handle_request)),
    )
    completion = create_chat_completion(
        client,
        model="glm-5.2",
        messages=[{"role": "user", "content": "plan"}],
        tools=[_tool("a_b"), _tool("a.b")],
    )

    wire_names = [tool["function"]["name"] for tool in captured["tools"]]
    assert len(set(wire_names)) == 2 and "a_b" in wire_names
    # The colliding dotted name restores to its original, not to "a_b".
    assert completion.choices[0].message.tool_calls[0].function.name == "a.b"
