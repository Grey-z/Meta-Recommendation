"""Server-side conversation context assembly.

Gives each turn real in-conversation memory by building a compact, model-ready
view of a conversation from its *persisted* messages (which the frontend's
string-only history can't see — recommendation bubbles are React elements there):

  - a verbatim sliding **window** of recent turns, INCLUDING recommendation
    results and the user's feedback on them;
  - a rolling compressed **summary** of older turns (populated by P2; read from
    the conversation's metadata here);
  - a small structured **facts** ledger — the user's accumulated preferences plus
    the restaurants already shown / disliked.

The builder is a pure function over a loaded conversation dict (the shape returned
by `PostgresConversationRepository.get_full_conversation`) so it is trivially
unit-testable without a database.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


def _int_env(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


# Defaults are deliberately small; the window is verbatim and the rest is a digest.
DEFAULT_WINDOW_TURNS = _int_env("METAREC_CONTEXT_WINDOW_TURNS", 5)
# Only roll older turns into the summary once at least this many have accrued past
# the watermark — keeps summarization infrequent (amortized cost).
SUMMARY_TRIGGER_MIN = _int_env("METAREC_CONTEXT_SUMMARY_TRIGGER", 3)
_LINE_CHAR_CAP = 220
_SHOWN_CAP = 18


def _clip(text: str, limit: int = _LINE_CHAR_CAP) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _restaurant_label(restaurant: Dict[str, Any]) -> str:
    """A short, human label for one recommended restaurant."""
    name = str(restaurant.get("name") or restaurant.get("id") or "").strip()
    if not name:
        return ""
    bits: List[str] = []
    cuisine = restaurant.get("cuisine")
    if cuisine:
        bits.append(str(cuisine))
    area = restaurant.get("area") or restaurant.get("location")
    if area:
        bits.append(str(area))
    price = restaurant.get("price_per_person_sgd") or restaurant.get("price")
    if price:
        bits.append(f"${price}")
    return f"{name} ({', '.join(bits)})" if bits else name


def _recommendation_entries(metadata: Dict[str, Any]) -> List[Dict[str, str]]:
    data = metadata.get("recommendation_data")
    if not isinstance(data, dict):
        return []
    entries: List[Dict[str, str]] = []
    restaurants = data.get("restaurants")
    if isinstance(restaurants, list):
        for restaurant in restaurants:
            if isinstance(restaurant, dict):
                name = str(restaurant.get("name") or "").strip()
                if name:
                    entries.append({"name": name, "domain": "restaurant", "label": _restaurant_label(restaurant) or name})
    items = data.get("items")
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict):
                title = str(item.get("title") or "").strip()
                if title:
                    domain = str(item.get("domain") or "item").strip() or "item"
                    subtitle = str(item.get("subtitle") or "").strip()
                    label = f"{title} ({domain}{f', {subtitle}' if subtitle else ''})"
                    entries.append({"name": title, "domain": domain, "label": label})
    return entries


def _recommendation_names(metadata: Dict[str, Any]) -> List[str]:
    return [entry["name"] for entry in _recommendation_entries(metadata)]


def _feedback_suffix(metadata: Dict[str, Any]) -> str:
    feedback = metadata.get("feedback")
    if not isinstance(feedback, dict):
        return ""
    sentiment = feedback.get("sentiment")
    if sentiment == "up":
        return " [user feedback: 👍 helpful]"
    if sentiment == "down":
        reason = feedback.get("reason")
        return f" [user feedback: 👎 not helpful{f' — {reason}' if reason else ''}]"
    return ""


def render_message(message: Dict[str, Any]) -> Optional[str]:
    """Render one persisted message to a single compact line, or None to skip it
    (e.g. transient processing placeholders)."""
    if not isinstance(message, dict):
        return None
    role = message.get("role")
    metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
    msg_type = metadata.get("type")

    if msg_type == "processing":
        return None

    if role == "user":
        content = message.get("content")
        text = content if isinstance(content, str) else ""
        return _clip(f"User: {text}") if text.strip() else None

    # Assistant turns.
    if msg_type == "recommendation":
        entries = _recommendation_entries(metadata)
        if entries:
            shown = "; ".join(
                f"{i}. {entry['label']}"
                for i, entry in enumerate(entries, start=1)
                if entry.get("label")
            )
            line = f"Assistant recommended: {shown}"
        else:
            line = "Assistant: (no matching recommendations found)"
        return _clip(line + _feedback_suffix(metadata), _LINE_CHAR_CAP + 80)

    if msg_type == "confirmation":
        request = metadata.get("confirmation_request")
        text = ""
        if isinstance(request, dict):
            text = str(request.get("message") or "")
        return _clip(f"Assistant asked to confirm preferences: {text}") if text else None

    # Plain assistant text reply.
    content = message.get("content")
    text = content if isinstance(content, str) else ""
    return _clip(f"Assistant: {text}") if text.strip() else None


def _branch_messages(messages: List[Dict[str, Any]], active_branch_id: Optional[str]) -> List[Dict[str, Any]]:
    """Messages along the active branch (superseded / off-branch turns excluded).
    When no branch is known, fall back to all messages."""
    if not active_branch_id:
        return [m for m in messages if isinstance(m, dict) and not (m.get("metadata") or {}).get("superseded")]
    scoped: List[Dict[str, Any]] = []
    for m in messages:
        if not isinstance(m, dict):
            continue
        metadata = m.get("metadata") if isinstance(m.get("metadata"), dict) else {}
        if metadata.get("superseded"):
            continue
        branch = m.get("branch_id") or metadata.get("branch_id")
        # Keep unbranched messages (legacy) and those on the active branch.
        if branch is None or branch == active_branch_id:
            scoped.append(m)
    return scoped


@dataclass
class ConversationContext:
    window: List[str] = field(default_factory=list)
    summary: str = ""
    facts: Dict[str, Any] = field(default_factory=dict)

    def is_empty(self) -> bool:
        return not self.window and not self.summary and not self.facts.get("shown")

    def _preferences_lines(self) -> List[str]:
        prefs = self.facts.get("preferences") or {}
        if not isinstance(prefs, dict):
            return []
        lines: List[str] = []
        food = prefs.get("food_intent")
        if isinstance(food, dict):
            terms = [str(t) for t in (food.get("cuisines") or []) + (food.get("dishes") or []) if t]
            if terms:
                lines.append(f"- cuisine/dish: {', '.join(terms)}")
        budget = prefs.get("budget_range")
        if isinstance(budget, dict) and (budget.get("min") or budget.get("max")):
            lines.append(
                f"- budget (per person): {budget.get('min') or '?'}–{budget.get('max') or '?'} "
                f"{budget.get('currency') or 'SGD'}"
            )
        if prefs.get("location"):
            lines.append(f"- location: {prefs.get('location')}")
        if prefs.get("dining_purpose") and prefs.get("dining_purpose") != "any":
            lines.append(f"- dining purpose: {prefs.get('dining_purpose')}")
        types = [t for t in (prefs.get("restaurant_types") or []) if t and t != "any"]
        if types:
            lines.append(f"- restaurant types: {', '.join(types)}")
        flavors = [f for f in (prefs.get("flavor_profiles") or []) if f and f != "any"]
        if flavors:
            lines.append(f"- flavors: {', '.join(flavors)}")
        domain = prefs.get("domain")
        if domain and domain not in {"restaurant", "multi_domain"}:
            lines.append(f"- recommendation domain: {domain}")
        if prefs.get("query") and domain and domain != "restaurant":
            lines.append(f"- requested item/search: {prefs.get('query')}")
        for key in ("genres", "exclude_genres", "tags", "stars", "amenities", "budget"):
            value = prefs.get(key)
            if isinstance(value, list) and value:
                lines.append(f"- {key.replace('_', ' ')}: {', '.join(str(item) for item in value)}")
            elif isinstance(value, str) and value.strip():
                lines.append(f"- {key.replace('_', ' ')}: {value}")
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                lines.append(f"- {key.replace('_', ' ')}: {value}")
        domains = prefs.get("domains")
        if isinstance(domains, dict):
            for domain_name, slice_ in domains.items():
                if isinstance(slice_, dict) and slice_:
                    rendered = ", ".join(f"{k}={v}" for k, v in slice_.items() if v not in (None, "", [], {}))
                    if rendered:
                        lines.append(f"- {domain_name} preferences: {rendered}")
        return lines

    def to_analysis_block(self) -> str:
        """Block appended to the intent/preference-extraction system prompt."""
        if self.is_empty():
            return ""
        sections: List[str] = ["[Conversation so far]"]
        if self.summary:
            sections.append(self.summary)
        if self.window:
            sections.extend(self.window)

        pref_lines = self._preferences_lines()
        if pref_lines:
            sections.append("")
            sections.append("[User's current preferences]")
            sections.extend(pref_lines)

        shown = self.facts.get("shown") or []
        if shown:
            sections.append("")
            sections.append(f"[Already recommended] {', '.join(shown)}")
        disliked = self.facts.get("disliked") or []
        if disliked:
            sections.append(f"[Disliked] {', '.join(disliked)}")

        sections.append("")
        sections.append(
            "Guidance: treat this as one ongoing conversation. If the user asks to adjust "
            "relative to before (e.g. \"cheaper\", \"closer\", \"more upscale\", \"a different "
            "cuisine\", \"lighter\", \"another movie\", \"a different genre\"), UPDATE the relevant fields relative to the current preferences above "
            "rather than starting from scratch, and keep the unchanged fields. Resolve "
            "references like \"the second one\" against the recommended list."
        )
        return "\n".join(sections)

    def to_recommender_block(self) -> str:
        """Compact context for the recommendation summarizer: what's been shown /
        disliked so it avoids repeats and respects the running thread."""
        if self.is_empty():
            return ""
        sections: List[str] = []
        if self.summary:
            sections.append(f"Conversation summary: {self.summary}")
        shown = self.facts.get("shown") or []
        if shown:
            sections.append(f"Already recommended (avoid repeating unless asked): {', '.join(shown)}")
        disliked = self.facts.get("disliked") or []
        if disliked:
            sections.append(f"User disliked: {', '.join(disliked)}")
        return "\n".join(sections)


def _message_id(message: Dict[str, Any]) -> Optional[str]:
    metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
    return metadata.get("message_id") or message.get("id")


@dataclass
class SummaryUpdate:
    """The slice of rolled-out turns to fold into the rolling summary next."""
    prior_summary: str
    new_turns_text: str
    new_watermark_id: Optional[str]


def compute_summary_update(
    conversation: Optional[Dict[str, Any]],
    *,
    active_branch_id: Optional[str] = None,
    window_turns: int = DEFAULT_WINDOW_TURNS,
    trigger_min: int = SUMMARY_TRIGGER_MIN,
) -> Optional[SummaryUpdate]:
    """Decide whether the rolling summary needs updating and, if so, return the new
    turns (past the live window AND past the last-summarized watermark) to fold in.

    Pure: no LLM, no I/O — the caller runs the actual summarization off the hot path.
    Returns None when everything still fits the verbatim window or too little is new.
    """
    if not conversation:
        return None
    messages = conversation.get("messages")
    if not isinstance(messages, list):
        return None
    branch_id = active_branch_id or conversation.get("active_branch_id")
    scoped = _branch_messages(messages, branch_id)
    if len(scoped) <= window_turns:
        return None
    older = scoped[:-window_turns]

    metadata = conversation.get("metadata") if isinstance(conversation.get("metadata"), dict) else {}
    context_meta = metadata.get("context_summary") if isinstance(metadata.get("context_summary"), dict) else {}
    prior_summary = str(context_meta.get("summary") or "")
    watermark = context_meta.get("summarized_through_message_id")

    new_older = older
    if watermark:
        for idx, message in enumerate(older):
            if _message_id(message) == watermark:
                new_older = older[idx + 1:]
                break

    if len(new_older) < trigger_min:
        return None
    lines = [line for line in (render_message(m) for m in new_older) if line]
    if not lines:
        return None
    return SummaryUpdate(
        prior_summary=prior_summary,
        new_turns_text="\n".join(lines),
        new_watermark_id=_message_id(new_older[-1]),
    )


def build_facts(conversation: Dict[str, Any], scoped_messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    preferences = conversation.get("preferences") if isinstance(conversation.get("preferences"), dict) else {}
    shown: List[str] = []
    disliked: List[str] = []
    seen = set()
    for message in scoped_messages:
        metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
        if metadata.get("type") != "recommendation":
            continue
        names = _recommendation_names(metadata)
        feedback = metadata.get("feedback")
        is_disliked = isinstance(feedback, dict) and feedback.get("sentiment") == "down"
        for name in names:
            if name not in seen:
                seen.add(name)
                shown.append(name)
            if is_disliked and name not in disliked:
                disliked.append(name)
    return {
        "preferences": preferences,
        "shown": shown[-_SHOWN_CAP:],
        "disliked": disliked[-_SHOWN_CAP:],
    }


def build_conversation_context(
    conversation: Optional[Dict[str, Any]],
    *,
    active_branch_id: Optional[str] = None,
    max_window_turns: int = DEFAULT_WINDOW_TURNS,
    current_query: Optional[str] = None,
) -> ConversationContext:
    """Build the context for the next turn from a loaded conversation dict.

    `active_branch_id` scopes the window/facts to the active branch. `current_query`,
    when given, drops a trailing user turn equal to it (the just-sent message that
    may already be persisted) so it isn't duplicated alongside the live query.
    """
    if not conversation:
        return ConversationContext()

    messages = conversation.get("messages")
    if not isinstance(messages, list):
        messages = []

    branch_id = active_branch_id or conversation.get("active_branch_id")
    scoped = _branch_messages(messages, branch_id)

    # Drop the trailing user echo of the in-flight query, if present.
    if current_query and scoped:
        last = scoped[-1]
        if (
            isinstance(last, dict)
            and last.get("role") == "user"
            and isinstance(last.get("content"), str)
            and last["content"].strip() == current_query.strip()
        ):
            scoped = scoped[:-1]

    rendered: List[str] = []
    for message in scoped:
        line = render_message(message)
        if line:
            rendered.append(line)
    window = rendered[-max_window_turns:]

    metadata = conversation.get("metadata") if isinstance(conversation.get("metadata"), dict) else {}
    summary = ""
    context_meta = metadata.get("context_summary")
    if isinstance(context_meta, dict):
        summary = str(context_meta.get("summary") or "")
    elif isinstance(context_meta, str):
        summary = context_meta

    facts = build_facts(conversation, scoped)
    return ConversationContext(window=window, summary=summary, facts=facts)
