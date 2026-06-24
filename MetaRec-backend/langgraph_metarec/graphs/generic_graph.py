from __future__ import annotations

import asyncio
import hashlib
import inspect
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from langgraph_metarec.genres import detect_genres_in_text
from langgraph_metarec.tool_registry import DEFAULT_TOOL_REGISTRY, ToolRegistry


ProgressCallback = Callable[[Dict[str, Any]], Awaitable[None] | None]


class GenericRuntimeState(TypedDict, total=False):
    query: str
    domain: str
    preferences: Dict[str, Any]
    use_online_agent: bool
    tool_tags: List[str]
    selected_tools: List[str]
    skipped_tools: List[Dict[str, str]]
    executions: List[Dict[str, Any]]
    items: List[Dict[str, Any]]
    progress_events: List[Dict[str, Any]]
    metadata: Dict[str, Any]
    errors: List[str]


@dataclass
class GenericGraphResult:
    executions: List[Dict[str, Any]]
    items: List[Dict[str, Any]]
    progress_events: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)


@dataclass
class GenericGraphAdapters:
    tool_registry: ToolRegistry = field(default_factory=lambda: DEFAULT_TOOL_REGISTRY)


async def _emit(
    state: GenericRuntimeState,
    progress_callback: Optional[ProgressCallback],
    event: Dict[str, Any],
) -> None:
    events = list(state.get("progress_events", []))
    events.append(event)
    state["progress_events"] = events
    if progress_callback:
        result = progress_callback(event)
        if inspect.isawaitable(result):
            await result  # type: ignore[misc]


def _stable_id(*parts: Any) -> str:
    text = "|".join(str(part or "") for part in parts)
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def _float_or_none(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> Optional[int]:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str):
        value = value.replace(",", "").strip()
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _string_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    result: List[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            result.append(item.strip())
        elif isinstance(item, dict):
            title = item.get("title") or item.get("name")
            if title:
                result.append(str(title))
    return result


def _item(
    *,
    domain: str,
    tool: str,
    raw: Dict[str, Any],
    title: Any,
    subtitle: Any = None,
    description: Any = None,
    image_url: Any = None,
    url: Any = None,
    rating: Any = None,
    reviews_count: Any = None,
    source: Any = None,
    tags: Optional[List[str]] = None,
    why: Any = None,
    item_id: Any = None,
) -> Dict[str, Any]:
    title_text = str(title or "").strip()
    url_text = str(url or "").strip() or None
    item_id_text = str(item_id).strip() if item_id else ""
    return {
        "id": item_id_text or f"{domain}_{_stable_id(tool, title_text, url_text)}",
        "domain": domain,
        "title": title_text or "Untitled",
        "subtitle": str(subtitle).strip() if subtitle else None,
        "description": str(description).strip() if description else None,
        "image_url": str(image_url).strip() if image_url else None,
        "url": url_text,
        "rating": _float_or_none(rating),
        "reviews_count": _int_or_none(reviews_count),
        "source": str(source or tool),
        "tags": tags or [],
        "why": str(why).strip() if why else None,
        "raw": raw,
    }


def normalize_tool_items(tool: str, output: Any, domain: str) -> List[Dict[str, Any]]:
    if not isinstance(output, list):
        return []
    items: List[Dict[str, Any]] = []
    for raw_item in output:
        if not isinstance(raw_item, dict):
            continue
        if tool == "amazon.product.search":
            items.append(
                _item(
                    domain=domain,
                    tool=tool,
                    raw=raw_item,
                    title=raw_item.get("title"),
                    subtitle=raw_item.get("brand") or raw_item.get("price"),
                    image_url=raw_item.get("thumbnail"),
                    url=raw_item.get("link"),
                    rating=raw_item.get("rating"),
                    reviews_count=raw_item.get("reviews"),
                    source="Amazon",
                    tags=[tag for tag in [raw_item.get("brand"), raw_item.get("price")] if tag],
                    why="Matched the product search query.",
                    item_id=raw_item.get("product_id") or raw_item.get("asin"),
                )
            )
        elif tool == "hardcover.book.search":
            authors = _string_list(raw_item.get("authors"))
            tags = _string_list(raw_item.get("genres")) + _string_list(raw_item.get("moods"))
            items.append(
                _item(
                    domain=domain,
                    tool=tool,
                    raw=raw_item,
                    title=raw_item.get("title"),
                    subtitle=", ".join(authors) if authors else raw_item.get("release_date"),
                    description=raw_item.get("description"),
                    image_url=raw_item.get("image"),
                    url=raw_item.get("hardcover_link"),
                    reviews_count=raw_item.get("reviews_count") or raw_item.get("ratings_count"),
                    source="Hardcover",
                    tags=tags,
                    why="Matched the requested book theme or genre.",
                    item_id=raw_item.get("id") or raw_item.get("hardcover_id"),
                )
            )
        elif tool == "musicbrainz.recording.search":
            artists = _string_list(raw_item.get("artists"))
            items.append(
                _item(
                    domain=domain,
                    tool=tool,
                    raw=raw_item,
                    title=raw_item.get("title"),
                    subtitle=", ".join(artists) if artists else raw_item.get("date"),
                    image_url=raw_item.get("cover_art_url"),
                    url=raw_item.get("link"),
                    source="MusicBrainz",
                    tags=_string_list(raw_item.get("tags")),
                    why="Matched the music search query.",
                    item_id=raw_item.get("id") or raw_item.get("mbid"),
                )
            )
        elif tool.startswith("tmdb."):
            media_type = raw_item.get("media_type") or ("tv" if ".tv." in tool else "movie")
            tmdb_id = raw_item.get("tmdb_id")
            items.append(
                _item(
                    domain=domain,
                    tool=tool,
                    raw=raw_item,
                    title=raw_item.get("title") or raw_item.get("name"),
                    subtitle=raw_item.get("release_date") or raw_item.get("original_language"),
                    description=raw_item.get("overview"),
                    image_url=raw_item.get("poster_url"),
                    url=f"https://www.themoviedb.org/{media_type}/{tmdb_id}" if tmdb_id else None,
                    rating=raw_item.get("vote_average"),
                    reviews_count=raw_item.get("vote_count"),
                    source="TMDB",
                    tags=_string_list(raw_item.get("genres")) + [str(media_type)],
                    why="Matched the entertainment search query.",
                    item_id=f"tmdb_{media_type}_{tmdb_id}" if tmdb_id else None,
                )
            )
    return items


def _rank_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    def score(item: Dict[str, Any]) -> tuple:
        raw = item.get("raw") if isinstance(item.get("raw"), dict) else {}
        return (
            item.get("rating") or 0,
            item.get("reviews_count") or 0,
            _float_or_none(raw.get("popularity")) or 0,
            item.get("title") or "",
        )

    deduped: Dict[str, Dict[str, Any]] = {}
    for item in items:
        key = f"{item.get('domain')}|{str(item.get('title')).lower()}|{item.get('url') or ''}"
        current = deduped.get(key)
        if current is None or score(item) > score(current):
            deduped[key] = item
    return sorted(deduped.values(), key=score, reverse=True)


def _genre_tokens(*values: Any) -> List[str]:
    tokens: List[str] = []
    for value in values:
        if not value:
            continue
        if isinstance(value, (list, tuple, set)):
            tokens.extend(str(token).strip() for token in value if str(token).strip())
        else:
            tokens.extend(part.strip() for part in str(value).split(",") if part.strip())
    return list(dict.fromkeys(tokens))


def _parameters_for_tool(tool: str, query: str, preferences: Dict[str, Any]) -> Dict[str, Any]:
    params: Dict[str, Any] = {"max_results": 10}
    if tool.endswith(".search"):
        params["query"] = query
    if tool.endswith(".discover"):
        media_type = "tv" if ".tv." in tool else "movie"
        # Explicit preference genres win; otherwise infer them from the query so
        # discover fires for natural prompts like "a quiet sci-fi movie". Genre
        # *names* are passed through — the TMDB adapter maps them to ids.
        include = _genre_tokens(preferences.get("with_genres"), preferences.get("genres")) or [
            str(name) for name in detect_genres_in_text(query, media_type)
        ]
        exclude = _genre_tokens(preferences.get("without_genres"), preferences.get("exclude_genres"))
        if include:
            params["with_genres"] = ",".join(include)
        if exclude:
            params["without_genres"] = ",".join(exclude)
    return params


def build_generic_domain_graph(
    *,
    adapters: Optional[GenericGraphAdapters] = None,
    progress_callback: Optional[ProgressCallback] = None,
):
    adapters = adapters or GenericGraphAdapters()
    registry = adapters.tool_registry

    async def candidate_gather(state: GenericRuntimeState) -> GenericRuntimeState:
        await _emit(
            state,
            progress_callback,
            {
                "stage": "candidate_gather",
                "stage_number": 1,
                "status": "started",
                "progress": 15,
                "message": f"Gathering {state.get('domain')} candidates...",
            },
        )
        domain = state.get("domain", "unknown")
        tags = state.get("tool_tags") or []
        all_specs = registry.resolve(domain=domain, tags=tags, active_only=False)
        active_specs = registry.resolve(domain=domain, tags=tags, active_only=True)
        active_names = [spec.name for spec in active_specs]
        state["selected_tools"] = active_names
        state["skipped_tools"] = [
            {"name": spec.name, "status": spec.status}
            for spec in all_specs
            if spec.name not in active_names
        ]
        executions: List[Dict[str, Any]] = []
        quota_tracker: Dict[str, int] = {}
        total = max(len(active_specs), 1)
        for idx, spec in enumerate(active_specs, start=1):
            params = _parameters_for_tool(spec.name, state.get("query", ""), state.get("preferences", {}))
            await _emit(
                state,
                progress_callback,
                {
                    "stage": "candidate_gather",
                    "stage_number": 1,
                    "status": "in_progress",
                    "progress": 20 + int((idx / total) * 45),
                    "message": f"Executing: {spec.name}",
                    "tool": spec.name,
                    "query": params.get("query", ""),
                },
            )
            executions.append(await asyncio.to_thread(registry.dispatch, spec.name, params, quota_tracker=quota_tracker))
        state["executions"] = executions
        await _emit(
            state,
            progress_callback,
            {
                "stage": "candidate_gather",
                "stage_number": 1,
                "status": "completed",
                "progress": 70,
                "message": f"{domain.title()} candidate gathering completed",
                "tools": active_names,
                "skipped_tools": state.get("skipped_tools", []),
            },
        )
        return state

    async def normalize_and_rank(state: GenericRuntimeState) -> GenericRuntimeState:
        await _emit(
            state,
            progress_callback,
            {
                "stage": "normalize_and_rank",
                "stage_number": 2,
                "status": "started",
                "progress": 80,
                "message": "Normalizing and ranking candidates...",
            },
        )
        domain = state.get("domain", "unknown")
        items: List[Dict[str, Any]] = []
        errors = list(state.get("errors", []))
        for execution in state.get("executions", []):
            if not execution.get("success"):
                if execution.get("error"):
                    errors.append(str(execution["error"]))
                continue
            items.extend(normalize_tool_items(str(execution.get("tool")), execution.get("output"), domain))
        state["items"] = _rank_items(items)[:10]
        state["errors"] = errors
        await _emit(
            state,
            progress_callback,
            {
                "stage": "normalize_and_rank",
                "stage_number": 2,
                "status": "completed",
                "progress": 92,
                "message": "Candidate ranking completed",
                "item_count": len(state["items"]),
            },
        )
        return state

    async def recommendation_result(state: GenericRuntimeState) -> GenericRuntimeState:
        state["metadata"] = {
            "domain": state.get("domain"),
            "graph": "generic_domain_graph",
            "tool_tags": state.get("tool_tags", []),
            "selected_tools": state.get("selected_tools", []),
            "skipped_tools": state.get("skipped_tools", []),
            "executions": state.get("executions", []),
            "items_count": len(state.get("items", [])),
        }
        await _emit(
            state,
            progress_callback,
            {
                "stage": "recommendation_result",
                "stage_number": 3,
                "status": "completed",
                "progress": 100,
                "message": "Recommendations ready!",
            },
        )
        return state

    graph = StateGraph(GenericRuntimeState)
    graph.add_node("candidate_gather", candidate_gather)
    graph.add_node("normalize_and_rank", normalize_and_rank)
    graph.add_node("recommendation_result", recommendation_result)
    graph.add_edge(START, "candidate_gather")
    graph.add_edge("candidate_gather", "normalize_and_rank")
    graph.add_edge("normalize_and_rank", "recommendation_result")
    graph.add_edge("recommendation_result", END)
    return graph.compile()


async def run_generic_domain_graph(
    *,
    query: str,
    domain: str,
    preferences: Optional[Dict[str, Any]] = None,
    use_online_agent: bool = False,
    tool_tags: Optional[List[str]] = None,
    adapters: Optional[GenericGraphAdapters] = None,
    progress_callback: Optional[ProgressCallback] = None,
) -> GenericGraphResult:
    graph = build_generic_domain_graph(adapters=adapters, progress_callback=progress_callback)
    final_state = await graph.ainvoke(
        {
            "query": query,
            "domain": domain,
            "preferences": preferences or {},
            "use_online_agent": use_online_agent,
            "tool_tags": tool_tags or [],
            "selected_tools": [],
            "skipped_tools": [],
            "executions": [],
            "items": [],
            "progress_events": [],
            "metadata": {},
            "errors": [],
        }
    )
    return GenericGraphResult(
        executions=final_state.get("executions", []),
        items=final_state.get("items", []),
        progress_events=final_state.get("progress_events", []),
        metadata=final_state.get("metadata", {}),
        errors=final_state.get("errors", []),
    )
