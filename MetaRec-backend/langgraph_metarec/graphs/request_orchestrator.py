from __future__ import annotations

import datetime as _dt
import os
import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from langgraph_metarec.checkpointing import RuntimeCheckpointer, conversation_thread_id
from langgraph_metarec.graphs.routing_graph import (
    DomainRoute,
    _preference_domain_hint,
    run_routing_graph,
    supported_domains_phrase,
)
from langgraph_metarec.nodes.domain import classify_domain
from langgraph_metarec.nodes.preferences import build_collect_confirm_state_payload, merge_preferences
from langgraph_metarec.state import (
    GraphRuntimeState,
    IntentResult,
    RuntimeErrorRecord,
    TaskStatusProjection,
)


AnalyzeMessage = Callable[..., Awaitable[Any]]
ConfirmationFactory = Callable[..., Awaitable[Dict[str, Any]]]
TaskFactory = Callable[[str, Dict[str, Any], Optional[List[str]], Optional[Dict[str, Any]]], Awaitable[str]]
PreferenceExtractor = Callable[[str], Dict[str, Any]]


@dataclass
class RequestOrchestratorAdapters:
    analyze_message: AnalyzeMessage
    make_confirmation: ConfirmationFactory
    create_task: TaskFactory
    extract_preferences: PreferenceExtractor


class RequestOrchestratorState(TypedDict, total=False):
    runtime: Dict[str, Any]
    conversation_history: List[Dict[str, Any]]
    user_profile: Optional[Dict[str, Any]]
    # Restaurant-only runtime preference baseline (defaults + profile + conversation).
    # Used solely as the merge base for the *restaurant* refine/dispatch paths; other
    # domains never inherit it (see _refine_preferences).
    restaurant_baseline: Optional[Dict[str, Any]]
    use_online_agent: bool
    domain_lock: Optional[str]


def _route_to_dict(route: Optional[DomainRoute], domain_lock: Optional[str] = None) -> Optional[Dict[str, Any]]:
    if route is None:
        return None
    return route.to_payload(domain_lock)


def _confirmation_request_from_hitl(hitl_state: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(hitl_state, dict):
        return None
    confirmation = hitl_state.get("confirmation_request")
    return confirmation if isinstance(confirmation, dict) else None


def _confirmation_message_from_hitl(hitl_state: Optional[Dict[str, Any]]) -> Optional[str]:
    confirmation = _confirmation_request_from_hitl(hitl_state)
    if confirmation:
        message = confirmation.get("message")
        if message:
            return str(message)
    return None


def _modification_confirmation(preferences: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "message": "No problem. Update the preferences below, then confirm to continue.",
        "preferences": preferences,
        "needs_confirmation": True,
    }


# Restaurant-ONLY preference keys, stripped before preferences reach a generic
# domain so restaurant defaults never reshape a movie/music/book/product/hotel
# request. `location` is deliberately NOT in this set: it is a genuinely generic
# key (hotels anchor on it, and the leakage concern was restaurant *defaults*,
# which `_generic_preference_subset`'s fresh-extraction inputs never carry).
_RESTAURANT_PREFERENCE_KEYS = {
    "restaurant_types",
    "flavor_profiles",
    "dining_purpose",
    "food_intent",
}


def _is_meaningful_budget_range(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    budget_min = value.get("min")
    budget_max = value.get("max")
    if budget_min in (None, "") and budget_max in (None, ""):
        return False
    # Common restaurant default emitted by older prompts; do not let it leak
    # into generic domains unless the user actually supplied a different budget.
    return (budget_min, budget_max) not in {(20, 60), ("20", "60")}


def _generic_preference_subset(preferences: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(preferences, dict):
        return {}
    result: Dict[str, Any] = {}
    for key, value in preferences.items():
        if key in _RESTAURANT_PREFERENCE_KEYS or value in (None, "", [], {}):
            continue
        if key == "budget_range" and not _is_meaningful_budget_range(value):
            continue
        result[key] = value
    return result


def _budget_text_from_range(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    currency = str(value.get("currency") or "SGD").upper()
    budget_min = value.get("min")
    budget_max = value.get("max")
    if budget_min not in (None, "") and budget_max not in (None, ""):
        return f"{budget_min}-{budget_max} {currency}"
    if budget_max not in (None, ""):
        return f"<= {budget_max} {currency}"
    if budget_min not in (None, ""):
        return f">= {budget_min} {currency}"
    return ""


_BUDGET_AMOUNT_RE = re.compile(
    r"(?P<prefix><=|<|under|below|以内|以下|不超过|少于|低于)?\s*"
    r"(?P<sym>[$￥¥])?\s*(?P<amount>\d+(?:[,.]\d+)?)\s*"
    r"(?P<currency>SGD|USD|CNY|RMB|EUR|新币|美元|人民币)?",
    re.IGNORECASE,
)
_BUDGET_UPPER_RE = re.compile(r"(以内|以下|不超过|少于|低于|under|below)", re.IGNORECASE)
_CURRENCY_NORMALIZE = {"新币": "SGD", "美元": "USD", "人民币": "CNY", "RMB": "CNY"}


def _extract_product_budget_text(query: str, preferences: Dict[str, Any]) -> str:
    explicit = preferences.get("budget")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    from_range = _budget_text_from_range(preferences.get("budget_range"))
    if from_range:
        return from_range
    text = query or ""
    # A number only counts as a budget when it carries a currency token/symbol or
    # sits next to a budget keyword. Bare numbers (e.g. the "14" in "iPhone 14") are
    # ignored, so a model/version number is never misread as a price.
    for match in _BUDGET_AMOUNT_RE.finditer(text):
        sym = match.group("sym")
        currency_tok = match.group("currency")
        prefix = match.group("prefix")
        trailing = text[match.end():match.end() + 3]
        has_currency = bool(sym or currency_tok)
        has_keyword = bool(prefix) or bool(re.match(r"\s*(以内|以下)", trailing))
        if not (has_currency or has_keyword):
            continue
        amount = match.group("amount").replace(",", "")
        if currency_tok:
            currency = _CURRENCY_NORMALIZE.get(currency_tok, currency_tok.upper())
        elif sym in ("￥", "¥"):
            currency = "CNY"
        else:
            currency = "SGD"  # "$" defaults to SGD to match the app's SGD-centric defaults
        is_upper = bool(prefix) or bool(_BUDGET_UPPER_RE.search(text))
        return f"<= {amount} {currency}" if is_upper else f"{amount} {currency}"
    if re.search(r"(不那么贵|便宜|实惠|预算有限|affordable|cheap|budget)", text, re.IGNORECASE):
        return "affordable"
    return ""


def _normalize_product_preferences(preferences: Dict[str, Any], query: str) -> Dict[str, Any]:
    result = dict(preferences or {})
    text = " ".join(str(part or "") for part in [query, result.get("query")]).strip()
    lower = text.lower()

    product = str(result.get("product") or result.get("item") or "").strip()
    brand = str(result.get("brand") or "").strip()
    category = str(result.get("category") or "").strip()
    use_case = str(result.get("use_case") or "").strip()

    if not product:
        if re.search(r"(iphone|ios|苹果手机|蘋果手機)", lower, re.IGNORECASE):
            product = "iPhone"
        elif re.search(r"(ipad|平板)", lower, re.IGNORECASE):
            product = "iPad"
        elif re.search(r"(laptop|notebook|电脑|筆電|笔记本|筆記本)", lower, re.IGNORECASE):
            product = "laptop"
        elif re.search(r"(headphones?|earbuds?|耳机|耳機)", lower, re.IGNORECASE):
            product = "headphones"
        # \bphones?\b so the substring "phone" in "headphones" is not matched.
        elif re.search(r"(\bphones?\b|smartphone|手机|手機)", lower, re.IGNORECASE):
            product = "smartphone"
    if product:
        result["product"] = product

    if not brand and re.search(r"(iphone|ipad|ios|apple|苹果|蘋果)", lower, re.IGNORECASE):
        result["brand"] = "Apple"
    elif brand:
        result["brand"] = brand

    if not category:
        if re.search(r"(iphone|ios|\bphones?\b|smartphone|手机|手機)", lower, re.IGNORECASE):
            category = "smartphone"
        elif re.search(r"(laptop|notebook|电脑|筆電|笔记本|筆記本)", lower, re.IGNORECASE):
            category = "laptop"
        elif product:
            category = product
    if category:
        result["category"] = category

    if not use_case:
        if re.search(r"(ios|app).*(test|测试|測試)|测试.*ios|測試.*ios", lower, re.IGNORECASE):
            use_case = "iOS testing"
        elif re.search(r"(办公|工作|office|work)", lower, re.IGNORECASE):
            use_case = "work"
        elif re.search(r"(学习|學習|study|school)", lower, re.IGNORECASE):
            use_case = "study"
        elif re.search(r"(游戏|遊戲|gaming|game)", lower, re.IGNORECASE):
            use_case = "gaming"
    if use_case:
        result["use_case"] = use_case

    model = str(result.get("model") or "").strip()
    if not model:
        model_match = re.search(r"(iphone|ipad)\s*(\d{1,2})(?:\s*(?:-|~|到|至)\s*(\d{1,2}))?", text, re.IGNORECASE)
        if model_match:
            start = model_match.group(2)
            end = model_match.group(3)
            model = f"{model_match.group(1).title()} {start}-{end}" if end else f"{model_match.group(1).title()} {start}"
    if model:
        result["model"] = model

    budget = _extract_product_budget_text(text, result)
    if budget:
        result["budget"] = budget
    return result


def _normalize_domain_preferences(domain: str, preferences: Dict[str, Any], query: str) -> Dict[str, Any]:
    if str(domain or "").lower() == "product":
        return _normalize_product_preferences(preferences, query)
    return preferences


def _enrich_hotel_preferences_from_profile(
    preferences: Dict[str, Any],
    user_profile: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    if not isinstance(preferences, dict) or str(preferences.get("domain") or "").lower() != "hotel":
        return preferences
    try:
        from profile_model import enrich_hotel_location_preferences

        return enrich_hotel_location_preferences(preferences, user_profile)
    except Exception:
        return preferences


def _hotel_location_needs_clarification(
    preferences: Dict[str, Any],
    user_profile: Optional[Dict[str, Any]],
) -> bool:
    if not isinstance(preferences, dict) or str(preferences.get("domain") or "").lower() != "hotel":
        return False
    try:
        from profile_model import hotel_location_needs_clarification

        return hotel_location_needs_clarification(preferences, user_profile)
    except Exception:
        return False


def _hotel_location_clarification(preferences: Dict[str, Any]) -> Dict[str, Any]:
    location = str((preferences or {}).get("location") or "").strip()
    if location and location.lower() != "any":
        message = (
            f"I need a more specific hotel destination for '{location}'. "
            "Please add the city or country, then confirm to continue."
        )
    else:
        message = "Please add the hotel destination or area, then confirm to continue."
    return {
        "message": message,
        "preferences": preferences,
        "needs_confirmation": True,
    }


def _merge_generic_preferences(
    base: Optional[Dict[str, Any]],
    overlay: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    result = _generic_preference_subset(base)
    result.update(_generic_preference_subset(overlay))
    return result


def _refine_preferences(
    *,
    routing: Optional[Dict[str, Any]],
    previous: Optional[Dict[str, Any]],
    new: Optional[Dict[str, Any]],
    restaurant_baseline: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Domain-aware merge for refining an open confirmation (shared by the
    reject-button and text-rejection paths).

    Restaurant folds the new preferences onto its rich runtime baseline. Every
    other domain merges only generic keys onto the set already under review and
    **never** inherits the restaurant baseline, so a movie/music/book/product
    refinement keeps its structured prefs instead of being reshaped into a
    restaurant request.
    """
    if _route_domain(routing) == "restaurant":
        base = previous or restaurant_baseline or {}
        return merge_preferences(base, new)
    return _merge_generic_preferences(previous or {}, new)


def _preference_domain(preferences: Optional[Dict[str, Any]]) -> Optional[str]:
    if not isinstance(preferences, dict):
        return None
    value = str(preferences.get("domain") or "").strip().lower()
    return value or None


def _classified_query_domain(query: str) -> Optional[str]:
    domain, _, _ = classify_domain(query or "")
    return None if domain == "unknown" else domain


def _starts_new_query_flow(
    collect_state: Dict[str, Any],
    query: str,
    preferences: Optional[Dict[str, Any]],
) -> bool:
    previous_domain = _route_domain(collect_state.get("routing"))
    query_domain = _classified_query_domain(query)
    if query_domain:
        return True
    # Semantic evidence from the LLM-structured preferences — explicit ``domain`` or
    # entity keys like artist/director/author. Reusing the same hint routing uses
    # lets the in-flow guard recognize a domain switch even when the query carries
    # no domain keyword (e.g. "by Nolan" while a music confirmation is open).
    hint = _preference_domain_hint(preferences)
    pref_domain = (hint[0] if hint else None) or _preference_domain(preferences)
    if not pref_domain:
        return False
    if previous_domain in {"recommendation", "unknown"}:
        return True
    return pref_domain != previous_domain


def _route_domain(route: Optional[Dict[str, Any]]) -> str:
    if not isinstance(route, dict):
        return "recommendation"
    return str(route.get("execution_domain") or route.get("domain") or "recommendation")


def _unsupported_domain_reply(domain: Optional[str]) -> str:
    """Graceful, extendable reply for a query we can't serve — an unknown/ambiguous
    domain or a recognized-but-not-connected one. Always points the user at the
    currently supported domains (single source: routing.supported_domains_phrase)."""
    phrase = supported_domains_phrase()
    domain_key = str(domain or "").lower()
    if domain_key and domain_key not in {"unknown", "multi_domain", "recommendation"}:
        return (
            f"It looks like you're after {domain_key} recommendations, which I don't "
            f"support yet. I can help with {phrase} — feel free to ask about any of those!"
        )
    return (
        "I'm not sure what kind of recommendation you're after. "
        f"I can help with {phrase} — feel free to ask about any of those!"
    )


def _itinerary_confirmation(query: str, route: Dict[str, Any], preferences: Dict[str, Any]) -> Dict[str, Any]:
    """Deterministic day-plan confirmation: lists the ordered slots so the user
    confirms the skeleton before any gathering runs. The attached itinerary form
    collects the required destination (plus budget / start time)."""
    slots = [task for task in route.get("domain_tasks", []) if task.get("status") == "ready"]
    lines = []
    for position, slot in enumerate(slots):
        time = str(slot.get("slot_time") or "").strip()
        label = str(slot.get("slot_label") or slot.get("domain") or "stop").strip()
        lines.append(f"{position + 1}. {f'{time} ' if time else ''}{label}")
    plan_text = "; ".join(lines) or "a day plan"
    location = str((preferences or {}).get("location") or "").strip()
    if location and location.lower() != "any":
        where = f" around {location}"
        ask = "Adjust the details below, then confirm to continue."
    else:
        where = ""
        ask = "Please add the destination below, then confirm to continue."
    return {
        "message": f"Here's the day plan I'll build{where}: {plan_text}. {ask}",
        "preferences": preferences,
        "needs_confirmation": True,
    }


def _multi_domain_confirmation(query: str, route: Dict[str, Any], preferences: Dict[str, Any]) -> Dict[str, Any]:
    """A coordination confirmation listing the ready domains. Multi-domain stays a
    simple yes/no (no single preference form)."""
    ready_domains = [
        task.get("domain")
        for task in route.get("domain_tasks", [])
        if isinstance(task, dict) and task.get("status") == "ready"
    ]
    label = ", ".join([str(item) for item in ready_domains if item]) or "multiple domains"
    return {
        "message": f"I detected this as a multi-domain recommendation request ({label}). I'll search for: {query}. Is that correct?",
        "preferences": preferences,
        "needs_confirmation": True,
    }


def _attach_preference_form(confirmation: Dict[str, Any], domain: str, preferences: Dict[str, Any]) -> None:
    """Attach the request-time preference form for ``domain`` so the client can
    refine structured preferences before the search runs. Single-domain only."""
    try:
        from preference_specs import build_domain_form

        form = build_domain_form(str(domain), preferences)
        if form.get("fields"):
            confirmation["preference_form"] = form
    except Exception:
        pass


HITL_EXPIRY_SECONDS = int(os.getenv("HITL_EXPIRY_SECONDS", "3600"))


def _is_collecting(runtime: GraphRuntimeState) -> bool:
    collect = runtime.collect_confirm_state or {}
    if collect.get("status") not in {"awaiting_confirmation", "awaiting_clarification"}:
        return False
    created_at_str = collect.get("created_at")
    if created_at_str:
        try:
            created_at = _dt.datetime.fromisoformat(created_at_str)
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=_dt.timezone.utc)
            elapsed = (_dt.datetime.now(_dt.timezone.utc) - created_at).total_seconds()
            if elapsed > HITL_EXPIRY_SECONDS:
                return False
        except (ValueError, TypeError):
            pass  # malformed timestamp → treat as non-expired (safe default)
    return True


def build_request_orchestrator_graph(
    adapters: RequestOrchestratorAdapters,
    *,
    checkpointer: Optional[Any] = None,
):
    async def intention_node(state: RequestOrchestratorState) -> RequestOrchestratorState:
        runtime = GraphRuntimeState.from_checkpoint(state.get("runtime"))
        collect_state = runtime.collect_confirm_state
        if (
            isinstance(collect_state, dict)
            and collect_state.get("action") == "confirm"
            and _is_collecting(runtime)
        ):
            runtime.intent_result = IntentResult(
                intent="confirmation_yes",
                confidence=1.0,
                preferences=collect_state.get("preferences"),
            )
            return {**state, "runtime": runtime.to_checkpoint()}

        history = list(state.get("conversation_history") or [])
        confirmation_message = _confirmation_message_from_hitl(collect_state)
        if _is_collecting(runtime) and confirmation_message:
            if not history or history[-1].get("content", "").strip() != confirmation_message.strip():
                history.append({"role": "assistant", "content": confirmation_message})

        pending_preferences = collect_state.get("preferences") if isinstance(collect_state, dict) else None
        try:
            llm_response = await adapters.analyze_message(
                runtime.query,
                history,
                state.get("user_profile"),
                _is_collecting(runtime),
                pending_preferences,
            )
            runtime.intent_result = IntentResult(
                intent=llm_response.intent,
                confidence=llm_response.confidence,
                reply=llm_response.reply,
                preferences=llm_response.preferences,
                profile_updates=getattr(llm_response, "profile_updates", None),
            )
        except Exception as exc:
            runtime.intent_result = IntentResult(intent="chat", confidence=0.0, reply=str(exc))
            runtime.errors.append(RuntimeErrorRecord(message=str(exc), node="intention"))
        return {**state, "runtime": runtime.to_checkpoint()}

    async def collect_confirm_node(state: RequestOrchestratorState) -> RequestOrchestratorState:
        runtime = GraphRuntimeState.from_checkpoint(state.get("runtime"))
        intent = runtime.intent_result.intent if runtime.intent_result else "chat"
        collect_state = runtime.collect_confirm_state or {}
        collecting = _is_collecting(runtime)
        preferences = runtime.intent_result.preferences if runtime.intent_result else None
        hitl_action = collect_state.get("action") if isinstance(collect_state, dict) else None

        if collecting and hitl_action == "reject":
            previous = collect_state.get("preferences") if isinstance(collect_state, dict) else None
            routing = collect_state.get("routing") if isinstance(collect_state, dict) else None
            refine_query = collect_state.get("query") or runtime.query
            domain_for_confirm = _route_domain(routing)
            # Domain-aware overlay of any newly stated preferences onto the set under
            # review — the same path as a text rejection — so a movie/music/book/
            # product rejection keeps its structured prefs and still gets the
            # request-time form (not a restaurant-shaped, form-less message).
            resolved_preferences = _refine_preferences(
                routing=routing,
                previous=previous,
                new=preferences,
                restaurant_baseline=state.get("restaurant_baseline"),
            )
            resolved_preferences = _normalize_domain_preferences(
                domain_for_confirm, resolved_preferences, refine_query
            )
            confirmation = _modification_confirmation(resolved_preferences)
            if (routing or {}).get("mode") != "multi_domain":
                _attach_preference_form(confirmation, domain_for_confirm, resolved_preferences)
            runtime.intent_result = IntentResult(
                intent="confirmation_no",
                confidence=runtime.intent_result.confidence if runtime.intent_result else None,
                reply=runtime.intent_result.reply if runtime.intent_result else None,
                preferences=resolved_preferences,
                profile_updates=runtime.intent_result.profile_updates if runtime.intent_result else None,
            )
            runtime.collect_confirm_state = build_collect_confirm_state_payload(
                query=refine_query,
                intent="confirmation_no",
                preferences=resolved_preferences,
                pending_preferences=resolved_preferences,
                needs_confirmation=True,
                confirmation_request=confirmation,
                routing=routing,
                status="awaiting_clarification",
            )
            runtime.collect_confirm_state["action"] = "reject"
            runtime.response_payload = {
                "type": "confirmation",
                "confirmation_request": confirmation,
                "intent": "confirmation_no",
                "preferences": resolved_preferences,
                "hitl_state": runtime.collect_confirm_state,
            }
            return {**state, "runtime": runtime.to_checkpoint()}

        if intent == "chat":
            runtime.collect_confirm_state = None
            runtime.response_payload = {
                "type": "llm_reply",
                "llm_reply": runtime.intent_result.reply if runtime.intent_result else "",
                "intent": "chat",
                "confidence": runtime.intent_result.confidence if runtime.intent_result else 0.0,
                "preferences": preferences,
            }
            return {**state, "runtime": runtime.to_checkpoint()}

        if intent == "confirmation_yes" and collecting:
            runtime.collect_confirm_state = {
                **collect_state,
                "status": "confirmed",
                "intent": intent,
            }
            runtime.response_payload = {"type": "confirmed"}
            return {**state, "runtime": runtime.to_checkpoint()}

        if collecting and intent in {"confirmation_no", "query"}:
            previous = collect_state.get("preferences") if isinstance(collect_state, dict) else None
            previous_route = collect_state.get("routing") if isinstance(collect_state, dict) else None
            starts_new_flow = intent == "query" and _starts_new_query_flow(
                collect_state,
                runtime.query,
                preferences,
            )
            # Refine the set under review unless the user clearly started a new
            # recommendation request/domain while a prior confirmation was open.
            if starts_new_flow:
                preferences = preferences or {}
                original_query = runtime.query
                routing = None
            else:
                preferences = _refine_preferences(
                    routing=previous_route,
                    previous=previous,
                    new=preferences,
                    restaurant_baseline=state.get("restaurant_baseline"),
                )
                original_query = collect_state.get("query") or runtime.query
                routing = previous_route

            if intent == "query":
                # An in-flow query still flows on to routing -> domain_dispatch,
                # which owns the single make_confirmation call. Only stage the
                # refined preferences here (mirroring the fresh-query path) so the
                # confirmation LLM is not generated twice and then discarded.
                runtime.collect_confirm_state = build_collect_confirm_state_payload(
                    query=original_query,
                    intent=intent,
                    preferences=preferences or {},
                    pending_preferences=preferences or {},
                    needs_confirmation=True,
                    routing=routing,
                    status="awaiting_confirmation",
                )
                runtime.response_payload = {
                    "type": "pending_confirmation",
                    "preferences": preferences or {},
                    "hitl_state": runtime.collect_confirm_state,
                }
                return {**state, "runtime": runtime.to_checkpoint()}

            # confirmation_no terminates at the result node (no dispatch), so it
            # builds its own confirmation here — same natural message + form as the
            # ready-domain path.
            domain_for_confirm = _route_domain(routing)
            preferences = _normalize_domain_preferences(domain_for_confirm, preferences or {}, original_query)
            confirmation = await adapters.make_confirmation(original_query, preferences or {}, domain_for_confirm)
            if (routing or {}).get("mode") != "multi_domain":
                _attach_preference_form(confirmation, domain_for_confirm, preferences or {})
            runtime.collect_confirm_state = build_collect_confirm_state_payload(
                query=original_query,
                intent=intent,
                preferences=preferences or {},
                pending_preferences=preferences or {},
                needs_confirmation=True,
                confirmation_request=confirmation,
                routing=routing,
                status="awaiting_confirmation",
            )
            runtime.response_payload = {
                "type": "confirmation",
                "confirmation_request": confirmation,
                "intent": intent,
                "preferences": preferences or {},
                "hitl_state": runtime.collect_confirm_state,
            }
            return {**state, "runtime": runtime.to_checkpoint()}

        if intent == "query":
            # Do not seed fresh queries with restaurant defaults before routing:
            # a movie/book/music/product request should not carry a restaurant
            # preference baseline into HITL. Restaurant routes fuse/extract their
            # baseline in domain_dispatch once the route is known.
            preferences = preferences or {}
            runtime.collect_confirm_state = build_collect_confirm_state_payload(
                query=runtime.query,
                intent=intent,
                preferences=preferences or {},
                pending_preferences=preferences or {},
                needs_confirmation=True,
                status="awaiting_confirmation",
            )
            runtime.response_payload = {
                "type": "pending_confirmation",
                "preferences": preferences or {},
                "hitl_state": runtime.collect_confirm_state,
            }
        return {**state, "runtime": runtime.to_checkpoint()}

    async def routing_node(state: RequestOrchestratorState) -> RequestOrchestratorState:
        runtime = GraphRuntimeState.from_checkpoint(state.get("runtime"))
        intent = runtime.intent_result.intent if runtime.intent_result else None
        if intent not in {"query", "confirmation_yes"}:
            return state

        collect_state = runtime.collect_confirm_state or {}
        existing_route = collect_state.get("routing") if isinstance(collect_state.get("routing"), dict) else None
        if intent == "confirmation_yes" and existing_route:
            runtime.routing_route = existing_route
            return {**state, "runtime": runtime.to_checkpoint()}

        preferences = collect_state.get("preferences") if isinstance(collect_state, dict) else None
        if not preferences and runtime.intent_result:
            preferences = runtime.intent_result.preferences
        route = await run_routing_graph(
            query=collect_state.get("query") or runtime.query,
            intent=intent,
            preferences=preferences,
            domain_lock=state.get("domain_lock"),
        )
        runtime.routing_route = _route_to_dict(route, state.get("domain_lock"))
        if runtime.collect_confirm_state is not None:
            runtime.collect_confirm_state["routing"] = runtime.routing_route
            if runtime.response_payload.get("hitl_state"):
                runtime.response_payload["hitl_state"] = runtime.collect_confirm_state
        return {**state, "runtime": runtime.to_checkpoint()}

    async def domain_dispatch_node(state: RequestOrchestratorState) -> RequestOrchestratorState:
        runtime = GraphRuntimeState.from_checkpoint(state.get("runtime"))
        route = runtime.routing_route or {}
        intent = runtime.intent_result.intent if runtime.intent_result else None
        collect_state = runtime.collect_confirm_state or {}

        if intent == "query" and route and route.get("status") != "ready":
            # We can't serve this query (ambiguous/unknown, or a recognized domain
            # that isn't connected). Respond as-is with a graceful, extendable reply
            # that points to the supported domains — no clarification HITL loop.
            status = route.get("status")
            runtime.collect_confirm_state = None
            runtime.response_payload = {
                "type": "llm_reply",
                "llm_reply": _unsupported_domain_reply(route.get("domain")),
                "intent": status,
                "confidence": route.get("domain_confidence"),
                "preferences": runtime.intent_result.preferences if runtime.intent_result else None,
                "domain": route.get("domain"),
                "routing": route,
            }
            return {**state, "runtime": runtime.to_checkpoint()}

        if intent == "query" and route.get("status") == "ready":
            # One confirmation path for every ready domain: a natural, domain-aware
            # message (restaurant/movie/music/book/product all flow through the same
            # make_confirmation) plus the request-time preference form. Multi-domain
            # stays a coordination yes/no.
            original_query = collect_state.get("query") or runtime.query
            exec_domain = _route_domain(route)
            is_multi = route.get("mode") == "multi_domain"

            if exec_domain == "restaurant" and not is_multi:
                # Restaurant has a rich preference baseline to fuse/extract.
                raw_preferences = collect_state.get("preferences") or {}
                base_preferences = state.get("restaurant_baseline") or {}
                if raw_preferences:
                    preferences = merge_preferences(base_preferences, raw_preferences)
                else:
                    preferences = adapters.extract_preferences(original_query)
            else:
                preferences = {
                    **_generic_preference_subset(collect_state.get("preferences")),
                    "domain": route.get("domain"),
                    "query": original_query,
                }
                preferences = _normalize_domain_preferences(exec_domain, preferences, original_query)

            if exec_domain == "hotel" and not is_multi:
                preferences = _enrich_hotel_preferences_from_profile(preferences, state.get("user_profile"))
                if _hotel_location_needs_clarification(preferences, state.get("user_profile")):
                    confirmation = _hotel_location_clarification(preferences)
                    _attach_preference_form(confirmation, exec_domain, preferences)
                    runtime.intent_result = IntentResult(
                        intent="confirmation_no",
                        confidence=runtime.intent_result.confidence if runtime.intent_result else None,
                        reply=runtime.intent_result.reply if runtime.intent_result else None,
                        preferences=preferences,
                        profile_updates=runtime.intent_result.profile_updates if runtime.intent_result else None,
                    )
                    runtime.collect_confirm_state = build_collect_confirm_state_payload(
                        query=original_query,
                        intent="confirmation_no",
                        preferences=preferences,
                        pending_preferences=preferences,
                        needs_confirmation=True,
                        confirmation_request=confirmation,
                        routing=route,
                        status="awaiting_clarification",
                    )
                    runtime.response_payload = {
                        "type": "confirmation",
                        "confirmation_request": confirmation,
                        "intent": "confirmation_no",
                        "preferences": preferences,
                        "domain": route.get("domain"),
                        "hitl_state": runtime.collect_confirm_state,
                    }
                    return {**state, "runtime": runtime.to_checkpoint()}

            if route.get("mode") == "itinerary":
                # Deterministic skeleton confirmation; the form is attached in
                # round 1 (unlike single domains) because the destination is the
                # required anchor for every slot's gathering.
                confirmation = _itinerary_confirmation(original_query, route, preferences)
                _attach_preference_form(confirmation, "itinerary", preferences)
            elif is_multi:
                confirmation = _multi_domain_confirmation(original_query, route, preferences)
            else:
                # Round 1 stays light: a natural message plus any quick actions from
                # make_confirmation. The full request-time form is reserved for the
                # refine round (reject / confirmation_no), so we do NOT attach it here.
                confirmation = await adapters.make_confirmation(original_query, preferences, exec_domain)

            runtime.collect_confirm_state = build_collect_confirm_state_payload(
                query=original_query,
                intent=intent,
                preferences=preferences,
                pending_preferences=preferences,
                needs_confirmation=True,
                confirmation_request=confirmation,
                routing=route,
                status="awaiting_confirmation",
            )
            runtime.response_payload = {
                "type": "confirmation",
                "confirmation_request": confirmation,
                "preferences": preferences,
                "domain": route.get("domain"),
                "hitl_state": runtime.collect_confirm_state,
            }
            return {**state, "runtime": runtime.to_checkpoint()}

        if intent == "confirmation_yes":
            preferences = collect_state.get("preferences") or {}
            original_query = collect_state.get("query") or runtime.query
            task_id = await adapters.create_task(original_query, preferences, route.get("tool_tags"), route)
            runtime.task_id = task_id
            runtime.task_status = TaskStatusProjection(
                task_id=task_id,
                status="pending",
                progress=0,
                message="Task created",
                metadata={"routing": route},
            )
            runtime.collect_confirm_state = None
            runtime.response_payload = {
                "type": "task_created",
                "task_id": task_id,
                "message": "Task started successfully",
                "preferences": preferences,
                "domain": route.get("domain"),
            }
        return {**state, "runtime": runtime.to_checkpoint()}

    def result_node(state: RequestOrchestratorState) -> RequestOrchestratorState:
        runtime = GraphRuntimeState.from_checkpoint(state.get("runtime"))
        payload = dict(runtime.response_payload)
        payload.setdefault("metadata", {})
        payload["metadata"] = {
            **payload["metadata"],
            **runtime.runtime_metadata(),
        }
        if runtime.routing_route and "routing" not in payload:
            payload["routing"] = runtime.routing_route
        if runtime.collect_confirm_state and "hitl_state" not in payload:
            payload["hitl_state"] = runtime.collect_confirm_state
        runtime.response_payload = payload
        return {**state, "runtime": runtime.to_checkpoint()}

    def _route_after_collect_confirm(state: RequestOrchestratorState) -> str:
        runtime = GraphRuntimeState.from_checkpoint(state.get("runtime"))
        intent = runtime.intent_result.intent if runtime.intent_result else None
        if intent in {"query", "confirmation_yes"}:
            return "routing"
        return "result"

    graph = StateGraph(RequestOrchestratorState)
    graph.add_node("intention", intention_node)
    graph.add_node("collect_confirm", collect_confirm_node)
    graph.add_node("routing", routing_node)
    graph.add_node("domain_dispatch", domain_dispatch_node)
    graph.add_node("result", result_node)
    graph.add_edge(START, "intention")
    graph.add_edge("intention", "collect_confirm")
    graph.add_conditional_edges(
        "collect_confirm",
        _route_after_collect_confirm,
        {"routing": "routing", "result": "result"},
    )
    graph.add_edge("routing", "domain_dispatch")
    graph.add_edge("domain_dispatch", "result")
    graph.add_edge("result", END)
    return graph.compile(checkpointer=checkpointer)


async def run_request_orchestrator(
    *,
    adapters: RequestOrchestratorAdapters,
    query: str,
    user_id: str,
    conversation_id: Optional[str],
    branch_id: Optional[str],
    message_id: Optional[str],
    conversation_history: Optional[List[Dict[str, Any]]],
    user_profile: Optional[Dict[str, Any]],
    restaurant_baseline: Optional[Dict[str, Any]],
    use_online_agent: bool,
    domain_lock: Optional[str],
    hitl_state: Optional[Dict[str, Any]] = None,
    checkpointer: Optional[Any] = None,
) -> GraphRuntimeState:
    thread_id = conversation_thread_id(user_id, conversation_id, branch_id)
    owner = None
    if checkpointer is None:
        owner = RuntimeCheckpointer()
        active_checkpointer = await owner.aget()
    else:
        active_checkpointer = checkpointer
    graph = build_request_orchestrator_graph(adapters, checkpointer=active_checkpointer)
    config = {"configurable": {"thread_id": thread_id}}
    try:
        stored = await graph.aget_state(config)
        stored_runtime = stored.values.get("runtime") if stored and stored.values else None
        runtime = GraphRuntimeState.from_checkpoint(stored_runtime)
        runtime.user_id = user_id
        runtime.conversation_id = conversation_id
        runtime.branch_id = branch_id
        runtime.message_id = message_id
        runtime.thread_id = thread_id
        runtime.query = query
        if not runtime.collect_confirm_state and isinstance(hitl_state, dict):
            runtime.collect_confirm_state = dict(hitl_state)
            runtime.metadata["imported_hitl_state"] = True
        elif runtime.collect_confirm_state and isinstance(hitl_state, dict):
            # The client may submit refined preferences (e.g. request-time form
            # values picked during confirmation) alongside the confirm. The
            # checkpointed collect state owns the structure, but merge the
            # client's preferences so those choices actually reach the search
            # (explicit form values > checkpoint defaults).
            state_updates: Dict[str, Any] = {}
            incoming_prefs = hitl_state.get("preferences")
            if isinstance(incoming_prefs, dict) and incoming_prefs:
                merged_prefs = {
                    **(runtime.collect_confirm_state.get("preferences") or {}),
                    **incoming_prefs,
                }
                state_updates["preferences"] = merged_prefs
                runtime.metadata["merged_hitl_preferences"] = True
            incoming_action = hitl_state.get("action")
            if incoming_action in {"confirm", "reject"}:
                state_updates["action"] = incoming_action
                runtime.metadata["merged_hitl_action"] = incoming_action
            selected_quick_action = hitl_state.get("selected_quick_action")
            if isinstance(selected_quick_action, dict):
                state_updates["selected_quick_action"] = selected_quick_action
                runtime.metadata["selected_quick_action"] = selected_quick_action
            if state_updates:
                runtime.collect_confirm_state = {
                    **runtime.collect_confirm_state,
                    **state_updates,
                }

        final_state = await graph.ainvoke(
            {
                "runtime": runtime.to_checkpoint(),
                "conversation_history": conversation_history or [],
                "user_profile": user_profile,
                "restaurant_baseline": restaurant_baseline,
                "use_online_agent": use_online_agent,
                "domain_lock": domain_lock,
            },
            config,
        )
        return GraphRuntimeState.from_checkpoint(final_state["runtime"])
    finally:
        if owner is not None:
            await owner.aclose()
