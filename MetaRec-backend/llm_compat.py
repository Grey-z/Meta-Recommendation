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
    for _ in range(3):
        try:
            return await client.chat.completions.create(**request)
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
    for _ in range(3):
        try:
            return client.chat.completions.create(**request)
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
