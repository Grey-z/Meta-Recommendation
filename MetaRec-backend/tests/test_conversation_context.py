from __future__ import annotations

import pytest

from conversation_context import (
    ConversationContext,
    build_conversation_context,
    compute_summary_update,
    render_message,
)


def _turn(i, role="user", branch="main"):
    return {
        "id": f"m{i}",
        "role": role,
        "content": f"turn {i}",
        "branch_id": branch,
        "metadata": {"message_id": f"m{i}"},
    }


def _rec_message(names, *, branch_id="main", feedback=None, restaurants=None):
    data_restaurants = restaurants or [{"name": n} for n in names]
    metadata = {"type": "recommendation", "recommendation_data": {"restaurants": data_restaurants}}
    if feedback is not None:
        metadata["feedback"] = feedback
    return {"role": "assistant", "content": "Found restaurants", "branch_id": branch_id, "metadata": metadata}


@pytest.mark.backend_unit
def test_render_message_variants():
    assert render_message({"role": "user", "content": "spicy dinner"}) == "User: spicy dinner"
    assert render_message({"role": "assistant", "content": "Sure!"}) == "Assistant: Sure!"
    # Processing placeholders are skipped.
    assert render_message({"role": "assistant", "content": "...", "metadata": {"type": "processing"}}) is None
    # Empty user content is skipped.
    assert render_message({"role": "user", "content": "   "}) is None


@pytest.mark.backend_unit
def test_render_recommendation_includes_names_and_feedback():
    line = render_message(
        _rec_message(
            [],
            restaurants=[
                {"name": "Xi'an Famous Foods", "cuisine": "Sichuan", "area": "Chinatown", "price_per_person_sgd": "20-30"},
                {"name": "Pho Street", "cuisine": "Vietnamese"},
            ],
            feedback={"sentiment": "down", "reason": "too_far"},
        )
    )
    assert "Assistant recommended:" in line
    assert "Xi'an Famous Foods (Sichuan, Chinatown, $20-30)" in line
    assert "2. Pho Street (Vietnamese)" in line
    assert "👎 not helpful — too_far" in line


@pytest.mark.backend_unit
def test_build_context_window_scopes_to_branch_and_drops_query_echo():
    conversation = {
        "active_branch_id": "main",
        "preferences": {"location": "Chinatown"},
        "messages": [
            {"role": "user", "content": "spicy dinner in Chinatown", "branch_id": "main"},
            _rec_message(["Place A", "Place B"], branch_id="main"),
            {"role": "user", "content": "off-branch turn", "branch_id": "other"},  # excluded
            {"role": "user", "content": "make it cheaper", "branch_id": "main"},  # current-query echo
        ],
    }
    context = build_conversation_context(conversation, active_branch_id="main", current_query="make it cheaper")

    assert "User: spicy dinner in Chinatown" in context.window
    assert any("Assistant recommended:" in line for line in context.window)
    # Off-branch message excluded; trailing echo of the live query dropped.
    assert all("off-branch turn" not in line for line in context.window)
    assert all("make it cheaper" not in line for line in context.window)


@pytest.mark.backend_unit
def test_facts_track_shown_and_disliked():
    conversation = {
        "active_branch_id": "main",
        "preferences": {"budget_range": {"min": 20, "max": 40, "currency": "SGD"}},
        "messages": [
            _rec_message(["Place A", "Place B"], branch_id="main"),
            _rec_message(["Place C"], branch_id="main", feedback={"sentiment": "down", "reason": "not_related"}),
        ],
    }
    context = build_conversation_context(conversation, active_branch_id="main")
    assert context.facts["shown"] == ["Place A", "Place B", "Place C"]
    assert context.facts["disliked"] == ["Place C"]


@pytest.mark.backend_unit
def test_analysis_block_carries_preferences_shown_and_guidance():
    conversation = {
        "active_branch_id": "main",
        "preferences": {
            "budget_range": {"min": 30, "max": 60, "currency": "SGD"},
            "location": "Bugis",
        },
        "messages": [_rec_message(["Place A"], branch_id="main")],
    }
    block = build_conversation_context(conversation, active_branch_id="main").to_analysis_block()
    assert "[User's current preferences]" in block
    assert "budget (per person): 30–60 SGD" in block
    assert "location: Bugis" in block
    assert "[Already recommended] Place A" in block
    assert "relative to the current preferences" in block  # the refine guidance


@pytest.mark.backend_unit
def test_summary_read_from_conversation_metadata():
    conversation = {
        "active_branch_id": "main",
        "metadata": {"context_summary": {"summary": "User wants cheap spicy food near Bugis."}},
        "messages": [{"role": "user", "content": "hi", "branch_id": "main"}],
    }
    context = build_conversation_context(conversation, active_branch_id="main")
    assert context.summary == "User wants cheap spicy food near Bugis."
    assert "User wants cheap spicy food near Bugis." in context.to_analysis_block()


@pytest.mark.backend_unit
def test_empty_conversation_yields_empty_block():
    assert build_conversation_context(None).to_analysis_block() == ""
    assert ConversationContext().is_empty()


@pytest.mark.backend_unit
def test_summary_update_none_when_within_window():
    conv = {"active_branch_id": "main", "messages": [_turn(i) for i in range(2)]}
    assert compute_summary_update(conv, active_branch_id="main", window_turns=8) is None


@pytest.mark.backend_unit
def test_summary_update_triggers_for_rolled_out_turns():
    conv = {"active_branch_id": "main", "messages": [_turn(i) for i in range(6)]}
    update = compute_summary_update(conv, active_branch_id="main", window_turns=2, trigger_min=2)
    assert update is not None
    assert update.prior_summary == ""
    # older = m0..m3 (last 2 stay in the window); watermark is the last rolled-out turn.
    assert update.new_watermark_id == "m3"
    assert "turn 0" in update.new_turns_text and "turn 3" in update.new_turns_text
    assert "turn 4" not in update.new_turns_text


@pytest.mark.backend_unit
def test_summary_update_respects_existing_watermark():
    conv = {
        "active_branch_id": "main",
        "messages": [_turn(i) for i in range(6)],
        "metadata": {"context_summary": {"summary": "prev", "summarized_through_message_id": "m3"}},
    }
    # Everything older than the window is already summarized → nothing to do.
    assert compute_summary_update(conv, active_branch_id="main", window_turns=2, trigger_min=1) is None


@pytest.mark.backend_unit
def test_summary_update_folds_only_turns_past_watermark():
    conv = {
        "active_branch_id": "main",
        "messages": [_turn(i) for i in range(8)],
        "metadata": {"context_summary": {"summary": "prev", "summarized_through_message_id": "m1"}},
    }
    update = compute_summary_update(conv, active_branch_id="main", window_turns=2, trigger_min=2)
    assert update is not None
    assert update.prior_summary == "prev"
    assert update.new_watermark_id == "m5"
    assert "turn 2" in update.new_turns_text
    assert "turn 1" not in update.new_turns_text


class _FakeCompletions:
    def __init__(self, content):
        self._content = content
        self.kwargs = None

    async def create(self, **kwargs):
        self.kwargs = kwargs
        message = type("_M", (), {"content": self._content})()
        choice = type("_C", (), {"message": message})()
        return type("_R", (), {"choices": [choice]})()


class _FakeClient:
    def __init__(self, content):
        self.chat = type("_Chat", (), {"completions": _FakeCompletions(content)})()


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_summarize_conversation_returns_model_summary():
    from llm_service import summarize_conversation

    client = _FakeClient("User wants cheap ramen near Bugis.")
    out = await summarize_conversation(client, "prev summary", "User: cheaper please", model="test-model")
    assert out == "User wants cheap ramen near Bugis."
    # Summarization runs on the provided (fast) model.
    assert client.chat.completions.kwargs["model"] == "test-model"


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_summarize_conversation_falls_back_to_prior_on_error():
    from llm_service import summarize_conversation

    class _Boom:
        class chat:
            class completions:
                @staticmethod
                async def create(**_kwargs):
                    raise RuntimeError("model down")

    out = await summarize_conversation(_Boom(), "prev summary", "new turns", model="test-model")
    assert out == "prev summary"
