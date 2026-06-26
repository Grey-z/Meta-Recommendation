from __future__ import annotations

import datetime as _dt
import os
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from langgraph_metarec.checkpointing import RuntimeCheckpointer, conversation_thread_id
from langgraph_metarec.graphs.routing_graph import DomainRoute, run_routing_graph, supported_domains_phrase
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
PreferenceUpdater = Callable[[Dict[str, Any]], None]


@dataclass
class RequestOrchestratorAdapters:
    analyze_message: AnalyzeMessage
    make_confirmation: ConfirmationFactory
    create_task: TaskFactory
    extract_preferences: PreferenceExtractor
    update_preferences: PreferenceUpdater


class RequestOrchestratorState(TypedDict, total=False):
    runtime: Dict[str, Any]
    conversation_history: List[Dict[str, Any]]
    user_profile: Optional[Dict[str, Any]]
    current_preferences: Optional[Dict[str, Any]]
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


_RESTAURANT_PREFERENCE_KEYS = {
    "restaurant_types",
    "flavor_profiles",
    "dining_purpose",
    "budget_range",
    "location",
    "food_intent",
}


def _generic_preference_subset(preferences: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(preferences, dict):
        return {}
    return {
        key: value
        for key, value in preferences.items()
        if key not in _RESTAURANT_PREFERENCE_KEYS and value not in (None, "", [], {})
    }


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
            # Overlay any newly stated preferences onto the set already under
            # review (falling back to the loaded baseline) so a rejection keeps
            # the user's existing choices instead of resetting to a blank set.
            base = previous or state.get("current_preferences") or {}
            resolved_preferences = merge_preferences(base, preferences)
            confirmation = _modification_confirmation(resolved_preferences)
            runtime.intent_result = IntentResult(
                intent="confirmation_no",
                confidence=runtime.intent_result.confidence if runtime.intent_result else None,
                reply=runtime.intent_result.reply if runtime.intent_result else None,
                preferences=resolved_preferences,
                profile_updates=runtime.intent_result.profile_updates if runtime.intent_result else None,
            )
            runtime.collect_confirm_state = build_collect_confirm_state_payload(
                query=collect_state.get("query") or runtime.query,
                intent="confirmation_no",
                preferences=resolved_preferences,
                pending_preferences=resolved_preferences,
                current_preferences=state.get("current_preferences"),
                needs_confirmation=True,
                confirmation_request=confirmation,
                routing=collect_state.get("routing"),
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
            # Refine the set under review: overlay new choices, keep the rest.
            base = previous or state.get("current_preferences") or {}
            preferences = merge_preferences(base, preferences)
            adapters.update_preferences(preferences or {})
            original_query = collect_state.get("query") or runtime.query

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
                    current_preferences=state.get("current_preferences"),
                    needs_confirmation=True,
                    routing=collect_state.get("routing"),
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
            domain_for_confirm = _route_domain(collect_state.get("routing"))
            confirmation = await adapters.make_confirmation(original_query, preferences or {}, domain_for_confirm)
            if (collect_state.get("routing") or {}).get("mode") != "multi_domain":
                _attach_preference_form(confirmation, domain_for_confirm, preferences or {})
            runtime.collect_confirm_state = build_collect_confirm_state_payload(
                query=original_query,
                intent=intent,
                preferences=preferences or {},
                pending_preferences=preferences or {},
                current_preferences=state.get("current_preferences"),
                needs_confirmation=True,
                confirmation_request=confirmation,
                routing=collect_state.get("routing"),
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
            adapters.update_preferences(preferences or {})
            runtime.collect_confirm_state = build_collect_confirm_state_payload(
                query=runtime.query,
                intent=intent,
                preferences=preferences or {},
                pending_preferences=preferences or {},
                current_preferences=state.get("current_preferences"),
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
                base_preferences = state.get("current_preferences") or {}
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

            if is_multi:
                confirmation = _multi_domain_confirmation(original_query, route, preferences)
            else:
                confirmation = await adapters.make_confirmation(original_query, preferences, exec_domain)
                _attach_preference_form(confirmation, exec_domain, preferences)

            runtime.collect_confirm_state = build_collect_confirm_state_payload(
                query=original_query,
                intent=intent,
                preferences=preferences,
                pending_preferences=preferences,
                current_preferences=state.get("current_preferences"),
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
    current_preferences: Optional[Dict[str, Any]],
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
            incoming_prefs = hitl_state.get("preferences")
            if isinstance(incoming_prefs, dict) and incoming_prefs:
                merged_prefs = {
                    **(runtime.collect_confirm_state.get("preferences") or {}),
                    **incoming_prefs,
                }
                runtime.collect_confirm_state = {
                    **runtime.collect_confirm_state,
                    "preferences": merged_prefs,
                }
                runtime.metadata["merged_hitl_preferences"] = True

        final_state = await graph.ainvoke(
            {
                "runtime": runtime.to_checkpoint(),
                "conversation_history": conversation_history or [],
                "user_profile": user_profile,
                "current_preferences": current_preferences,
                "use_online_agent": use_online_agent,
                "domain_lock": domain_lock,
            },
            config,
        )
        return GraphRuntimeState.from_checkpoint(final_state["runtime"])
    finally:
        if owner is not None:
            await owner.aclose()
