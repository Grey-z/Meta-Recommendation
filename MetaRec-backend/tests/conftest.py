import json
import asyncio
import sys
from pathlib import Path
from typing import Any, Iterable, List, Sequence, Tuple

import pytest
from langgraph.checkpoint.memory import MemorySaver


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


@pytest.fixture(scope="session")
def event_loop_policy():
    if sys.platform == "win32":
        policy_cls = getattr(asyncio, "WindowsSelectorEventLoopPolicy", None)
        if policy_cls is not None:
            return policy_cls()
    return asyncio.get_event_loop_policy()


class _FakeMessage:
    def __init__(self, content: str):
        self.content = content


class _FakeChoice:
    def __init__(self, content: str):
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content: str):
        self.choices = [_FakeChoice(content)]


class FakeCompletions:
    def __init__(self, scripted_outputs: Sequence[Any]):
        self._outputs: List[Any] = list(scripted_outputs)
        self.calls = 0

    async def create(self, **kwargs: Any) -> _FakeResponse:
        self.calls += 1
        if not self._outputs:
            raise RuntimeError("No scripted fake LLM outputs left")
        item = self._outputs.pop(0)
        if isinstance(item, Exception):
            raise item
        return _FakeResponse(str(item))


class FakeChat:
    def __init__(self, scripted_outputs: Sequence[Any]):
        self.completions = FakeCompletions(scripted_outputs)


class FakeAsyncClient:
    def __init__(self, scripted_outputs: Sequence[Any]):
        self.chat = FakeChat(scripted_outputs)


class TestRuntimeCheckpointer:
    def __init__(self):
        self.saver = MemorySaver()

    def get(self):
        return self.saver

    async def aget(self):
        return self.saver


def make_service(scripted_outputs: Sequence[Any], max_retries: int = 2):
    from service import MetaRecService

    fake_async_client = FakeAsyncClient(scripted_outputs)
    fake_sync_client = object()
    service = MetaRecService(
        async_client=fake_async_client,
        sync_client=fake_sync_client,
        summary_model="summary-model",
        planning_model="planning-model",
        llm_model="llm-model",
    )
    service.profile_storage = None
    service.profile_repository = None
    service.task_repository = None
    service.runtime_checkpointer = TestRuntimeCheckpointer()
    service.llm_max_format_retries = max_retries
    return service, fake_async_client


def query_intent_json(reply: str = "Sure, I can help with that.") -> str:
    payload = {
        "intent": "query",
        "reply": reply,
        "confidence": 0.9,
        "preferences": {
            "restaurant_types": ["casual"],
            "flavor_profiles": ["spicy"],
            "dining_purpose": "friends",
            "budget_range": {"min": 20, "max": 60, "currency": "SGD", "per": "person"},
            "location": "Chinatown",
        },
    }
    return json.dumps(payload, ensure_ascii=False)


def confirm_yes_json(reply: str = "Confirmed.") -> str:
    payload = {
        "intent": "confirmation_yes",
        "reply": reply,
        "confidence": 0.95,
        "preferences": None,
    }
    return json.dumps(payload, ensure_ascii=False)
