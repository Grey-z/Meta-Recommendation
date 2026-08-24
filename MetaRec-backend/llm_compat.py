"""Compatibility helpers for OpenAI-style Chat Completions providers.

MetaRec can point the same SDK client at OpenAI, GLM, Groq, and other
OpenAI-compatible endpoints. Request parameter support is model-dependent,
so callers should go through the helpers in this module instead of invoking
``client.chat.completions.create`` directly.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict


logger = logging.getLogger(__name__)

# Current OpenAI reasoning-model families use the default sampling temperature
# and the newer completion-token field. The final component also covers model
# names qualified by a provider, for example ``openai/gpt-5-mini``.
_REASONING_MODEL_RE = re.compile(r"^(?:o[1-9](?:-|$)|gpt-5(?:[.-]|$))", re.IGNORECASE)


# Strictest common denominator across OpenAI-compatible providers: several
# reject any function name outside this pattern with a 400 before the model
# ever runs. MetaRec's registry names are dotted ("gmap.search"), so they are
# sanitized on the way out and restored on the way back in.
_TOOL_NAME_ALLOWED_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


def _sanitize_tool_names(request: Dict[str, Any]) -> Dict[str, str]:
    """Rewrite tool names the wire format rejects; return sanitized->original.

    Never mutates the caller's tool definitions (they are typically module-level
    constants); offending entries are replaced with copies.
    """
    tools = request.get("tools")
    if not isinstance(tools, list):
        return {}
    mapping: Dict[str, str] = {}
    taken = {
        str(tool.get("function", {}).get("name") or "")
        for tool in tools
        if isinstance(tool, dict)
    }
    sanitized_tools = []
    for tool in tools:
        function = tool.get("function") if isinstance(tool, dict) else None
        name = str((function or {}).get("name") or "")
        if not name or _TOOL_NAME_ALLOWED_RE.match(name):
            sanitized_tools.append(tool)
            continue
        candidate = re.sub(r"[^a-zA-Z0-9_-]", "_", name)
        while candidate in taken or candidate in mapping:
            candidate += "_"
        mapping[candidate] = name
        sanitized_tools.append({**tool, "function": {**function, "name": candidate}})
    if mapping:
        request["tools"] = sanitized_tools
        choice = request.get("tool_choice")
        if isinstance(choice, dict):
            forced = str((choice.get("function") or {}).get("name") or "")
            reverse = {original: sanitized for sanitized, original in mapping.items()}
            if forced in reverse:
                request["tool_choice"] = {
                    **choice,
                    "function": {**choice["function"], "name": reverse[forced]},
                }
    return mapping


def _restore_tool_names(response: Any, mapping: Dict[str, str]) -> Any:
    """Map sanitized function names in response tool_calls back to originals."""
    if not mapping:
        return response
    for choice in getattr(response, "choices", None) or []:
        message = getattr(choice, "message", None)
        for tool_call in getattr(message, "tool_calls", None) or []:
            function = (
                tool_call.get("function")
                if isinstance(tool_call, dict)
                else getattr(tool_call, "function", None)
            )
            if function is None:
                continue
            name = (
                function.get("name")
                if isinstance(function, dict)
                else getattr(function, "name", None)
            )
            original = mapping.get(str(name or ""))
            if original is None:
                continue
            if isinstance(function, dict):
                function["name"] = original
            else:
                function.name = original
    return response


def _model_name(model: Any) -> str:
    return str(model or "").strip().rsplit("/", 1)[-1].lower()


def _is_reasoning_model(model: Any) -> bool:
    return bool(_REASONING_MODEL_RE.match(_model_name(model)))


def _use_max_completion_tokens(request: Dict[str, Any]) -> None:
    """Move max_tokens into extra_body for the pinned older OpenAI SDK.

    openai==1.12.0 predates the typed ``max_completion_tokens`` argument but
    supports sending newer API fields through ``extra_body``.
    """
    if "max_tokens" not in request:
        return
    max_tokens = request.pop("max_tokens")
    extra_body = dict(request.get("extra_body") or {})
    extra_body.setdefault("max_completion_tokens", max_tokens)
    request["extra_body"] = extra_body


def prepare_chat_completion_request(**kwargs: Any) -> Dict[str, Any]:
    """Return request kwargs normalized for known reasoning model families."""
    request = dict(kwargs)
    if not _is_reasoning_model(request.get("model")):
        return request

    if request.get("temperature") != 1:
        request.pop("temperature", None)
    _use_max_completion_tokens(request)
    return request


def _error_text(exc: Exception) -> str:
    body = getattr(exc, "body", None)
    return f"{exc} {body!r}".lower()


def _adapt_request_from_error(request: Dict[str, Any], exc: Exception) -> str | None:
    """Adapt one unsupported parameter, returning its name when changed."""
    message = _error_text(exc)
    unsupported = any(token in message for token in ("unsupported", "does not support", "only the default"))

    if "temperature" in request and "temperature" in message and unsupported:
        request.pop("temperature", None)
        return "temperature"

    if "max_tokens" in request and "max_tokens" in message and (
        unsupported or "max_completion_tokens" in message
    ):
        _use_max_completion_tokens(request)
        return "max_tokens"

    return None


async def create_chat_completion_async(client: Any, **kwargs: Any) -> Any:
    """Create an async chat completion with narrowly scoped compatibility retries."""
    request = prepare_chat_completion_request(**kwargs)
    tool_names = _sanitize_tool_names(request)
    for _ in range(3):
        try:
            return _restore_tool_names(await client.chat.completions.create(**request), tool_names)
        except Exception as exc:
            adapted = _adapt_request_from_error(request, exc)
            if adapted is None:
                raise
            logger.info(
                "Retrying Chat Completions without unsupported %s for model=%s",
                adapted,
                request.get("model"),
            )
    raise RuntimeError("Chat Completions compatibility retry limit exceeded")


def create_chat_completion(client: Any, **kwargs: Any) -> Any:
    """Create a synchronous chat completion with compatibility retries."""
    request = prepare_chat_completion_request(**kwargs)
    tool_names = _sanitize_tool_names(request)
    for _ in range(3):
        try:
            return _restore_tool_names(client.chat.completions.create(**request), tool_names)
        except Exception as exc:
            adapted = _adapt_request_from_error(request, exc)
            if adapted is None:
                raise
            logger.info(
                "Retrying Chat Completions without unsupported %s for model=%s",
                adapted,
                request.get("model"),
            )
    raise RuntimeError("Chat Completions compatibility retry limit exceeded")
