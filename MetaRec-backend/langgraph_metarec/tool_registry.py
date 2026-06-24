from __future__ import annotations

import concurrent.futures
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Set

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from langgraph_metarec.tool_compaction import compact_tool_output


ToolAdapter = Callable[[Dict[str, Any]], Any]
DEFAULT_TOOL_TIMEOUT_SECONDS = 12.0
DEFAULT_TOOL_QUOTA_PER_RUN = 5


class ToolDispatchEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: str
    parameters: Dict[str, Any] = Field(default_factory=dict)


def normalize_tag(tag: str) -> str:
    value = str(tag or "").strip().lower()
    if not value:
        return value
    return value if value.startswith("#") else f"#{value}"


@dataclass(frozen=True)
class ToolSpec:
    name: str
    domain: str
    tags: Set[str]
    input_schema: Dict[str, Any]
    output_schema: Dict[str, Any]
    adapter: ToolAdapter
    online_only: bool = False
    status: str = "active"
    description: Optional[str] = None
    timeout_seconds: float = DEFAULT_TOOL_TIMEOUT_SECONDS
    quota_per_run: int = DEFAULT_TOOL_QUOTA_PER_RUN

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError("Tool timeout_seconds must be greater than 0")
        if self.quota_per_run <= 0:
            raise ValueError("Tool quota_per_run must be greater than 0")
        object.__setattr__(self, "domain", self.domain.lower())
        object.__setattr__(self, "tags", {normalize_tag(tag) for tag in self.tags})

    def matches(
        self,
        *,
        domain: Optional[str] = None,
        tags: Optional[Iterable[str]] = None,
        include_online_only: bool = True,
        active_only: bool = True,
    ) -> bool:
        if domain and self.domain != domain.lower():
            return False
        if active_only and self.status != "active":
            return False
        if self.online_only and not include_online_only:
            return False
        required_tags = {normalize_tag(tag) for tag in (tags or []) if tag}
        return required_tags.issubset(self.tags)


@dataclass
class ToolRegistry:
    _tools: Dict[str, ToolSpec] = field(default_factory=dict)

    def register(self, spec: ToolSpec) -> None:
        if not spec.name:
            raise ValueError("Tool name is required")
        if spec.name in self._tools:
            raise ValueError(f"Tool already registered: {spec.name}")
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise KeyError(f"Unknown tool: {name}") from exc

    def names(self) -> List[str]:
        return sorted(self._tools)

    def resolve(
        self,
        *,
        domain: Optional[str] = None,
        tags: Optional[Iterable[str]] = None,
        include_online_only: bool = True,
        active_only: bool = True,
    ) -> List[ToolSpec]:
        return sorted(
            [
                spec
                for spec in self._tools.values()
                if spec.matches(
                    domain=domain,
                    tags=tags,
                    include_online_only=include_online_only,
                    active_only=active_only,
                )
            ],
            key=lambda spec: spec.name,
        )

    def dispatch(
        self,
        name: str,
        parameters: Optional[Dict[str, Any]] = None,
        *,
        quota_tracker: Optional[Dict[str, int]] = None,
    ) -> Dict[str, Any]:
        spec = self.get(name)
        try:
            envelope = ToolDispatchEnvelope(tool=name, parameters=parameters or {})
        except ValidationError as exc:
            return {
                "tool": name,
                "input": parameters or {},
                "success": False,
                "error": f"Tool dispatch envelope validation failed: {exc.errors()}",
            }
        if spec.status != "active":
            return {
                "tool": name,
                "input": envelope.parameters,
                "success": False,
                "error": f"Tool is not active: {spec.status}",
            }

        input_errors = validate_json_schema(spec.input_schema, envelope.parameters, "input")
        if input_errors:
            return {
                "tool": name,
                "input": envelope.parameters,
                "success": False,
                "error": "Tool input schema validation failed: " + "; ".join(input_errors),
            }

        quota_used = None
        if quota_tracker is not None:
            quota_used = int(quota_tracker.get(name, 0))
            if quota_used >= spec.quota_per_run:
                return {
                    "tool": name,
                    "input": envelope.parameters,
                    "success": False,
                    "error": f"Tool quota exceeded: {quota_used}/{spec.quota_per_run} calls used",
                    "metadata": {
                        "quota_per_run": spec.quota_per_run,
                        "quota_used": quota_used,
                        "timeout_seconds": spec.timeout_seconds,
                    },
                }
            quota_used += 1
            quota_tracker[name] = quota_used

        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"tool-{name}")
        try:
            future = executor.submit(spec.adapter, envelope.parameters)
            output = future.result(timeout=spec.timeout_seconds)
            output_errors = validate_json_schema(spec.output_schema, output, "output")
            if output_errors:
                return {
                    "tool": name,
                    "input": envelope.parameters,
                    "output": output,
                    "success": False,
                    "error": "Tool output schema validation failed: " + "; ".join(output_errors),
                    "metadata": {
                        "quota_per_run": spec.quota_per_run,
                        "quota_used": quota_used,
                        "timeout_seconds": spec.timeout_seconds,
                    },
                }
            return {
                "tool": name,
                "input": envelope.parameters,
                "output": output,
                "success": output is not None,
                "metadata": {
                    "quota_per_run": spec.quota_per_run,
                    "quota_used": quota_used,
                    "timeout_seconds": spec.timeout_seconds,
                },
            }
        except concurrent.futures.TimeoutError:
            future.cancel()
            return {
                "tool": name,
                "input": envelope.parameters,
                "success": False,
                "error": f"Tool timed out after {spec.timeout_seconds:.2f}s",
                "metadata": {
                    "quota_per_run": spec.quota_per_run,
                    "quota_used": quota_used,
                    "timeout_seconds": spec.timeout_seconds,
                },
            }
        except Exception as exc:
            return {
                "tool": name,
                "input": envelope.parameters,
                "success": False,
                "error": str(exc),
                "metadata": {
                    "quota_per_run": spec.quota_per_run,
                    "quota_used": quota_used,
                    "timeout_seconds": spec.timeout_seconds,
                },
            }
        finally:
            executor.shutdown(wait=False, cancel_futures=True)


def validate_json_schema(schema: Dict[str, Any], value: Any, path: str = "value") -> List[str]:
    if not schema:
        return []

    errors: List[str] = []
    expected_type = schema.get("type")
    if expected_type is not None and not _matches_json_type(value, expected_type):
        errors.append(f"{path}: expected {_type_name(expected_type)}, got {type(value).__name__}")
        return errors

    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: expected one of {schema['enum']!r}")

    if isinstance(value, dict):
        required = schema.get("required") or []
        for field_name in required:
            if field_name not in value:
                errors.append(f"{path}.{field_name}: missing required field")

        properties = schema.get("properties") or {}
        for field_name, field_schema in properties.items():
            if field_name in value:
                errors.extend(validate_json_schema(field_schema, value[field_name], f"{path}.{field_name}"))

        additional = schema.get("additionalProperties", True)
        if additional is False:
            extra_fields = sorted(set(value) - set(properties))
            for field_name in extra_fields:
                errors.append(f"{path}.{field_name}: additional property is not allowed")
        elif isinstance(additional, dict):
            for field_name in sorted(set(value) - set(properties)):
                errors.extend(validate_json_schema(additional, value[field_name], f"{path}.{field_name}"))

    if isinstance(value, list):
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for idx, item in enumerate(value):
                errors.extend(validate_json_schema(item_schema, item, f"{path}[{idx}]"))

    return errors


def _matches_json_type(value: Any, expected_type: Any) -> bool:
    if isinstance(expected_type, list):
        return any(_matches_json_type(value, item) for item in expected_type)
    if expected_type == "object":
        return isinstance(value, dict)
    if expected_type == "array":
        return isinstance(value, list)
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "null":
        return value is None
    return True


def _type_name(expected_type: Any) -> str:
    if isinstance(expected_type, list):
        return " or ".join(str(item) for item in expected_type)
    return str(expected_type)


def _gmap_search_adapter(parameters: Dict[str, Any]) -> Any:
    from agent.agent_mcp.agent_google_map import search_google_maps

    return compact_tool_output(
        "gmap.search",
        search_google_maps(
            query=parameters.get("query", ""),
            max_results=int(parameters.get("max_results", 10)),
        ),
    )


def _xhs_search_adapter(parameters: Dict[str, Any]) -> Any:
    from agent.agent_mcp.agent_xiaohongshu import search_notes_by_keyword

    return compact_tool_output(
        "xhs.search",
        search_notes_by_keyword(
            keyword=parameters.get("query", ""),
            max_results=int(parameters.get("max_results", 10)),
        ),
    )


def _yelp_search_adapter(parameters: Dict[str, Any]) -> Any:
    from agent.agent_mcp.agent_yelp import search_yelp_organic_results

    return compact_tool_output(
        "yelp.search",
        search_yelp_organic_results(
            query=parameters.get("query", ""),
            location=parameters.get("location", "Singapore"),
            max_results=int(parameters.get("max_results", 10)),
        ),
    )


def _gmap_source_matcher_adapter(parameters: Dict[str, Any]) -> Any:
    return {
        "candidates": parameters.get("candidates", []),
        "reference_results": parameters.get("reference_results", []),
        "matches": [],
        "status": "passthrough",
    }


def _credential_status(*env_names: str) -> str:
    missing = [name for name in env_names if not os.getenv(name)]
    return "missing_credentials:" + ",".join(missing) if missing else "active"


def _max_results(parameters: Dict[str, Any], default: int = 10, ceiling: int = 25) -> int:
    try:
        value = int(parameters.get("max_results", default))
    except (TypeError, ValueError):
        value = default
    return max(1, min(value, ceiling))


def _http_get_json(
    url: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: float = 10.0,
    follow_redirects: bool = True,
) -> Dict[str, Any]:
    with httpx.Client(timeout=timeout, follow_redirects=follow_redirects) as client:
        response = client.get(url, params=params, headers=headers)
        response.raise_for_status()
        return response.json()


def _amazon_product_search_adapter(parameters: Dict[str, Any]) -> Any:
    api_key = os.getenv("SERPAPI_KEY")
    if not api_key:
        return None
    params = {
        "api_key": api_key,
        "engine": "amazon",
        "k": parameters.get("query", ""),
    }
    data = _http_get_json(os.getenv("SERPAPI_URL", "https://serpapi.com/search.json"), params=params)
    items = []
    for item in (data.get("organic_results") or [])[:_max_results(parameters)]:
        items.append(
            {
                "title": item.get("title"),
                "brand": item.get("brand"),
                "link": item.get("link_clean") or item.get("link"),
                "rating": item.get("rating"),
                "reviews": item.get("reviews"),
                "price": item.get("price"),
                "thumbnail": item.get("thumbnail"),
                "source": "amazon",
            }
        )
    return compact_tool_output("amazon.product.search", items)


def _hardcover_book_search_adapter(parameters: Dict[str, Any]) -> Any:
    api_key = os.getenv("HARDCOVER_API_KEY")
    if not api_key:
        return None
    query = str(parameters.get("query") or "")
    max_results = _max_results(parameters, ceiling=20)
    graphql_query = """
        query Query {
            search(
                query: "%s",
                query_type: "Book",
                per_page: %d,
                fields: "genres",
                weights: "1",
                sort: "users_read_count:desc",
                typos: "2",
                page: 1
            ) {
                results
            }
        }
    """ % (query.replace('"', '\\"'), max_results)
    with httpx.Client(
        base_url="https://api.hardcover.app/v1/graphql",
        timeout=12.0,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    ) as client:
        response = client.post("/", json={"query": graphql_query})
        response.raise_for_status()
        data = response.json()
    hits = (((data.get("data") or {}).get("search") or {}).get("results") or {}).get("hits") or []
    items = []
    for hit in hits[:max_results]:
        doc = hit.get("document") or {}
        image = doc.get("image") if isinstance(doc.get("image"), dict) else {}
        authors = []
        for contribution in doc.get("contributions") or []:
            author = contribution.get("author") if isinstance(contribution, dict) else None
            if isinstance(author, dict) and author.get("name"):
                authors.append(author["name"])
        slug = doc.get("slug")
        items.append(
            {
                "title": doc.get("title"),
                "release_date": doc.get("release_date"),
                "ratings_count": doc.get("ratings_count"),
                "reviews_count": doc.get("reviews_count"),
                "description": doc.get("description"),
                "image": image.get("url"),
                "genres": doc.get("genres") or [],
                "moods": doc.get("moods") or [],
                "tags": doc.get("tags") or [],
                "authors": authors,
                "hardcover_link": f"https://hardcover.app/books/{slug}" if slug else None,
                "source": "hardcover",
            }
        )
    return compact_tool_output("hardcover.book.search", items)


def _musicbrainz_recording_search_adapter(parameters: Dict[str, Any]) -> Any:
    query = str(parameters.get("query") or "")
    max_results = _max_results(parameters, default=10, ceiling=25)
    data = _http_get_json(
        "https://musicbrainz.org/ws/2/recording",
        params={"query": query, "limit": max_results},
        headers={
            "Accept": "application/json",
            "User-Agent": "MetaRec/0.1 (multi-source recommendation research)",
        },
        timeout=12.0,
    )
    items = []
    for item in (data.get("recordings") or [])[:max_results]:
        artists = [
            artist.get("name")
            for artist in (item.get("artist-credit") or [])
            if isinstance(artist, dict) and artist.get("name")
        ]
        tags = [
            tag.get("name")
            for tag in (item.get("tags") or [])
            if isinstance(tag, dict) and tag.get("name")
        ]
        release = (item.get("releases") or [{}])[0] or {}
        cover_art_url = None
        release_id = release.get("id")
        if release_id:
            try:
                with httpx.Client(timeout=5.0, follow_redirects=False) as client:
                    response = client.get(f"https://coverartarchive.org/release/{release_id}/front")
                    if response.status_code in {301, 302, 307, 308}:
                        cover_art_url = response.headers.get("Location")
            except Exception:
                cover_art_url = None
        mbid = item.get("id")
        items.append(
            {
                "title": item.get("title"),
                "date": item.get("first-release-date"),
                "link": f"https://musicbrainz.org/recording/{mbid}" if mbid else None,
                "artists": artists,
                "tags": tags,
                "cover_art_url": cover_art_url,
                "source": "musicbrainz",
            }
        )
    return compact_tool_output("musicbrainz.recording.search", items)


def _tmdb_headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {os.getenv('TMDB_API_ACCESS_TOKEN')}",
        "accept": "application/json",
    }


def _tmdb_get(path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    with httpx.Client(base_url="https://api.themoviedb.org", timeout=12.0, headers=_tmdb_headers()) as client:
        response = client.get(path, params=params)
        response.raise_for_status()
        return response.json()


def _tmdb_configuration() -> Dict[str, Any]:
    try:
        return _tmdb_get("/3/configuration")
    except Exception:
        return {}


def _tmdb_genres(media_type: str) -> Dict[int, str]:
    try:
        data = _tmdb_get(f"/3/genre/{media_type}/list", {"language": "en"})
        return {
            int(item["id"]): item["name"]
            for item in data.get("genres") or []
            if isinstance(item, dict) and item.get("id") is not None and item.get("name")
        }
    except Exception:
        return {}


def _tmdb_languages() -> Dict[str, str]:
    try:
        data = _tmdb_get("/3/configuration/languages")
        return {
            item.get("iso_639_1"): item.get("english_name")
            for item in data
            if isinstance(item, dict) and item.get("iso_639_1")
        }
    except Exception:
        return {}


def _tmdb_normalize_results(results: List[Dict[str, Any]], *, media_type: str) -> List[Dict[str, Any]]:
    config = _tmdb_configuration()
    image_base = ((config.get("images") or {}).get("secure_base_url") or "https://image.tmdb.org/t/p/")
    genres = _tmdb_genres("tv" if media_type == "tv" else "movie")
    languages = _tmdb_languages()
    normalized = []
    for item in results:
        poster_path = item.get("poster_path")
        normalized.append(
            {
                "title": item.get("title") or item.get("name"),
                "name": item.get("name"),
                "release_date": item.get("release_date") or item.get("first_air_date"),
                "overview": item.get("overview"),
                "vote_count": item.get("vote_count"),
                "popularity": item.get("popularity"),
                "vote_average": item.get("vote_average"),
                "original_language": languages.get(item.get("original_language"), item.get("original_language")),
                "poster_url": f"{image_base}original{poster_path}" if poster_path else None,
                "genres": [genres[genre_id] for genre_id in item.get("genre_ids") or [] if genre_id in genres],
                "tmdb_id": item.get("id"),
                "media_type": media_type,
                "source": "tmdb",
            }
        )
    return normalized


def _tmdb_movie_search_adapter(parameters: Dict[str, Any]) -> Any:
    data = _tmdb_get("/3/search/movie", {"query": parameters.get("query", ""), "language": "en"})
    return compact_tool_output(
        "tmdb.movie.search",
        _tmdb_normalize_results((data.get("results") or [])[:_max_results(parameters)], media_type="movie"),
    )


def _tmdb_movie_discover_adapter(parameters: Dict[str, Any]) -> Any:
    params = {"language": "en", "sort_by": "popularity.desc"}
    if parameters.get("with_genres"):
        params["with_genres"] = parameters["with_genres"]
    if parameters.get("without_genres"):
        params["without_genres"] = parameters["without_genres"]
    data = _tmdb_get("/3/discover/movie", params)
    return compact_tool_output(
        "tmdb.movie.discover",
        _tmdb_normalize_results((data.get("results") or [])[:_max_results(parameters)], media_type="movie"),
    )


def _tmdb_tv_search_adapter(parameters: Dict[str, Any]) -> Any:
    data = _tmdb_get("/3/search/tv", {"query": parameters.get("query", ""), "language": "en"})
    return compact_tool_output(
        "tmdb.tv.search",
        _tmdb_normalize_results((data.get("results") or [])[:_max_results(parameters)], media_type="tv"),
    )


def _tmdb_tv_discover_adapter(parameters: Dict[str, Any]) -> Any:
    params = {"language": "en", "sort_by": "popularity.desc"}
    if parameters.get("with_genres"):
        params["with_genres"] = parameters["with_genres"]
    if parameters.get("without_genres"):
        params["without_genres"] = parameters["without_genres"]
    data = _tmdb_get("/3/discover/tv", params)
    return compact_tool_output(
        "tmdb.tv.discover",
        _tmdb_normalize_results((data.get("results") or [])[:_max_results(parameters)], media_type="tv"),
    )


def build_default_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()

    registry.register(
        ToolSpec(
            name="gmap.search",
            domain="restaurant",
            tags={"#place", "#restaurant", "#review", "#map"},
            input_schema={
                "type": "object",
                "required": ["query"],
                "properties": {"query": {"type": "string"}, "max_results": {"type": "integer"}},
            },
            output_schema={"type": "array", "items": {"type": "object"}},
            adapter=_gmap_search_adapter,
            description="Search Google Maps for restaurant/place candidates.",
        )
    )
    registry.register(
        ToolSpec(
            name="xhs.search",
            domain="restaurant",
            tags={"#place", "#restaurant", "#review", "#social"},
            input_schema={
                "type": "object",
                "required": ["query"],
                "properties": {"query": {"type": "string"}, "max_results": {"type": "integer"}},
            },
            output_schema={"type": "array", "items": {"type": "object"}},
            adapter=_xhs_search_adapter,
            description="Search Xiaohongshu notes for social/review evidence.",
        )
    )
    registry.register(
        ToolSpec(
            name="yelp.search",
            domain="restaurant",
            tags={"#place", "#restaurant", "#review"},
            input_schema={
                "type": "object",
                "required": ["query", "location"],
                "properties": {
                    "query": {"type": "string"},
                    "location": {"type": "string"},
                    "max_results": {"type": "integer"},
                },
            },
            output_schema={"type": "array", "items": {"type": "object"}},
            adapter=_yelp_search_adapter,
            description="Search Yelp for restaurant review candidates.",
        )
    )
    registry.register(
        ToolSpec(
            name="gmap.source_matcher",
            domain="restaurant",
            tags={"#place", "#restaurant", "#map", "#source_match"},
            input_schema={
                "type": "object",
                "properties": {
                    "candidates": {"type": "array", "items": {"type": "object"}},
                    "reference_results": {"type": "array", "items": {"type": "object"}},
                },
            },
            output_schema={"type": "object"},
            adapter=_gmap_source_matcher_adapter,
            description="Match restaurant candidates against Google Maps source records.",
        )
    )
    registry.register(
        ToolSpec(
            name="amazon.product.search",
            domain="product",
            tags={"#thing", "#shopping", "#product"},
            input_schema={
                "type": "object",
                "required": ["query"],
                "properties": {"query": {"type": "string"}, "max_results": {"type": "integer"}},
            },
            output_schema={"type": "array", "items": {"type": "object"}},
            adapter=_amazon_product_search_adapter,
            status=_credential_status("SERPAPI_KEY"),
            description="Search Amazon products via SerpAPI.",
        )
    )
    registry.register(
        ToolSpec(
            name="hardcover.book.search",
            domain="book",
            tags={"#thing", "#book"},
            input_schema={
                "type": "object",
                "required": ["query"],
                "properties": {"query": {"type": "string"}, "max_results": {"type": "integer"}},
            },
            output_schema={"type": "array", "items": {"type": "object"}},
            adapter=_hardcover_book_search_adapter,
            status=_credential_status("HARDCOVER_API_KEY"),
            description="Search books by genre or keyword via Hardcover.",
        )
    )
    registry.register(
        ToolSpec(
            name="musicbrainz.recording.search",
            domain="music",
            tags={"#thing", "#music"},
            input_schema={
                "type": "object",
                "required": ["query"],
                "properties": {"query": {"type": "string"}, "max_results": {"type": "integer"}},
            },
            output_schema={"type": "array", "items": {"type": "object"}},
            adapter=_musicbrainz_recording_search_adapter,
            description="Search recordings via MusicBrainz with optional cover-art enrichment.",
        )
    )
    registry.register(
        ToolSpec(
            name="tmdb.movie.search",
            domain="movie",
            tags={"#thing", "#movie"},
            input_schema={
                "type": "object",
                "required": ["query"],
                "properties": {"query": {"type": "string"}, "max_results": {"type": "integer"}},
            },
            output_schema={"type": "array", "items": {"type": "object"}},
            adapter=_tmdb_movie_search_adapter,
            status=_credential_status("TMDB_API_ACCESS_TOKEN"),
            description="Search movies by title via TMDB.",
        )
    )
    registry.register(
        ToolSpec(
            name="tmdb.movie.discover",
            domain="movie",
            tags={"#thing", "#movie"},
            input_schema={
                "type": "object",
                "properties": {
                    "with_genres": {"type": "string"},
                    "without_genres": {"type": "string"},
                    "max_results": {"type": "integer"},
                },
            },
            output_schema={"type": "array", "items": {"type": "object"}},
            adapter=_tmdb_movie_discover_adapter,
            status=_credential_status("TMDB_API_ACCESS_TOKEN"),
            description="Discover popular movies by TMDB genre filters.",
        )
    )
    registry.register(
        ToolSpec(
            name="tmdb.tv.search",
            domain="movie",
            tags={"#thing", "#movie", "#tv"},
            input_schema={
                "type": "object",
                "required": ["query"],
                "properties": {"query": {"type": "string"}, "max_results": {"type": "integer"}},
            },
            output_schema={"type": "array", "items": {"type": "object"}},
            adapter=_tmdb_tv_search_adapter,
            status=_credential_status("TMDB_API_ACCESS_TOKEN"),
            description="Search TV series by title via TMDB.",
        )
    )
    registry.register(
        ToolSpec(
            name="tmdb.tv.discover",
            domain="movie",
            tags={"#thing", "#movie", "#tv"},
            input_schema={
                "type": "object",
                "properties": {
                    "with_genres": {"type": "string"},
                    "without_genres": {"type": "string"},
                    "max_results": {"type": "integer"},
                },
            },
            output_schema={"type": "array", "items": {"type": "object"}},
            adapter=_tmdb_tv_discover_adapter,
            status=_credential_status("TMDB_API_ACCESS_TOKEN"),
            description="Discover popular TV series by TMDB genre filters.",
        )
    )

    return registry


DEFAULT_TOOL_REGISTRY = build_default_tool_registry()
