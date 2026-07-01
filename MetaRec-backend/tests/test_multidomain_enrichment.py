"""Tests for the richer movie/music/book candidate gathering: structured provider
filters (TMDB cast/crew, MusicBrainz Lucene, OpenLibrary, Last.fm), the per-tool
param mapping, normalization, the ReAct gather loop, profile-favorite fusion and
the request-time form fields."""

import asyncio

import pytest

from langgraph_metarec import tool_registry as tr
from langgraph_metarec.graphs.generic_graph import (
    GenericGraphAdapters,
    _parameters_for_tool,
    normalize_tool_items,
    run_generic_domain_graph,
)
from langgraph_metarec.tool_registry import ToolRegistry, ToolSpec, build_default_tool_registry, validate_json_schema


# --------------------------------------------------------------------------- #
# Provider adapters
# --------------------------------------------------------------------------- #
@pytest.mark.backend_unit
def test_name_list_splits_and_dedupes():
    assert tr._name_list("Nolan, Villeneuve & Kubrick") == ["Nolan", "Villeneuve", "Kubrick"]
    assert tr._name_list(["Nolan", "Nolan"]) == ["Nolan"]
    assert tr._name_list(None) == []
    assert tr._name_list("") == []


@pytest.mark.backend_unit
def test_tmdb_resolve_person_prefers_role_department_and_caches(monkeypatch):
    calls = []

    def fake_get(path, params=None):
        calls.append((path, params))
        return {
            "results": [
                {"id": 1, "known_for_department": "Acting", "popularity": 50},
                {"id": 525, "known_for_department": "Directing", "popularity": 9},
            ]
        }

    monkeypatch.setattr(tr, "_TMDB_PERSON_CACHE", {})
    monkeypatch.setattr(tr, "_tmdb_get", fake_get)

    # Director resolution prefers the Directing department even if less popular.
    assert tr._tmdb_resolve_person("Christopher Nolan", "director") == 525
    # Actor resolution prefers Acting.
    assert tr._tmdb_resolve_person("Christopher Nolan", "actor") == 1
    # A repeated lookup is served from cache (no extra HTTP call).
    before = len(calls)
    tr._tmdb_resolve_person("Christopher Nolan", "director")
    assert len(calls) == before


@pytest.mark.backend_unit
def test_tmdb_discover_fires_on_crew_without_genre_and_gates_empty(monkeypatch):
    discover_params = {}

    def fake_get(path, params=None):
        if path == "/3/search/person":
            return {"results": [{"id": 525, "known_for_department": "Directing", "popularity": 9}]}
        if path.startswith("/3/discover"):
            discover_params.update(params or {})
            return {"results": [{"id": 1, "title": "Inception", "genre_ids": []}]}
        return {}

    monkeypatch.setattr(tr, "_TMDB_PERSON_CACHE", {})
    monkeypatch.setattr(
        tr, "_TMDB_STATIC_CACHE", {"config": {}, "genres:movie": {}, "genres:tv": {}, "languages": {}}
    )
    monkeypatch.setattr(tr, "_tmdb_get", fake_get)

    # Director-only discover (no genre) still fires, resolving the crew id.
    out = tr._tmdb_discover({"with_crew": "Christopher Nolan"}, media_type="movie")
    assert discover_params.get("with_crew") == "525"
    assert discover_params.get("vote_count.gte") == 50
    assert out and out[0]["title"] == "Inception"

    # No structured filter at all -> contributes nothing (no discover call).
    discover_params.clear()
    assert tr._tmdb_discover({}, media_type="movie") == []
    assert discover_params == {}


@pytest.mark.backend_unit
def test_musicbrainz_lucene_query_builds_artist_and_tag_clauses():
    q = tr._musicbrainz_lucene_query({"artist": "Daft Punk", "genres": ["rock", "EDM"]})
    assert q == 'artist:"Daft Punk" AND (tag:"rock" OR tag:"edm")'
    assert tr._musicbrainz_lucene_query({"artist": "Daft Punk"}) == 'artist:"Daft Punk"'
    assert tr._musicbrainz_lucene_query({}) == ""


@pytest.mark.backend_unit
def test_openlibrary_discover_builds_field_params_and_normalizes(monkeypatch):
    captured = {}

    def fake_http_get_json(url, params=None, headers=None, **kwargs):
        captured["url"] = url
        captured["params"] = params
        return {
            "docs": [
                {
                    "key": "/works/OL1W",
                    "title": "Mistborn",
                    "author_name": ["Brandon Sanderson"],
                    "publisher": ["Tor"],
                    "first_publish_year": 2006,
                    "cover_i": 123,
                    "subject": ["fantasy"] * 20,
                    "ratings_average": 4.5,
                    "ratings_count": 900,
                }
            ]
        }

    monkeypatch.setattr(tr, "_http_get_json", fake_http_get_json)

    out = tr._openlibrary_book_discover_adapter(
        {"author": "Brandon Sanderson", "publisher": "Tor", "genres": "fantasy"}
    )
    assert captured["params"]["author"] == "Brandon Sanderson"
    assert captured["params"]["publisher"] == "Tor"
    assert captured["params"]["subject"] == "fantasy"
    assert out[0]["title"] == "Mistborn"
    assert out[0]["image"] == "https://covers.openlibrary.org/b/id/123-M.jpg"
    assert len(out[0]["subjects"]) == 8  # capped


@pytest.mark.backend_unit
def test_openlibrary_discover_gates_when_no_structured_filter(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("should not hit HTTP when no structured filter is present")

    monkeypatch.setattr(tr, "_http_get_json", boom)
    assert tr._openlibrary_book_discover_adapter({"max_results": 10}) == []


@pytest.mark.backend_unit
def test_lastfm_discover_is_credential_gated(monkeypatch):
    monkeypatch.delenv("LASTFM_API_KEY", raising=False)
    assert tr._lastfm_discover_adapter({"artist": "Daft Punk"}) is None


@pytest.mark.backend_unit
def test_lastfm_discover_queries_artist_top_tracks(monkeypatch):
    captured = {}

    def fake_http_get_json(url, params=None, headers=None, **kwargs):
        captured["params"] = params
        return {
            "toptracks": {
                "track": [
                    {
                        "name": "Get Lucky",
                        "artist": {"name": "Daft Punk"},
                        "url": "https://last.fm/x",
                        "playcount": "1000",
                        "image": [{"#text": "small"}, {"#text": "big"}],
                    }
                ]
            }
        }

    monkeypatch.setenv("LASTFM_API_KEY", "k")
    monkeypatch.setattr(tr, "_http_get_json", fake_http_get_json)

    out = tr._lastfm_discover_adapter({"artist": "Daft Punk"})
    assert captured["params"]["method"] == "artist.gettoptracks"
    assert captured["params"]["artist"] == "Daft Punk"
    assert out[0]["title"] == "Get Lucky"
    assert out[0]["artists"] == ["Daft Punk"]
    assert out[0]["image"] == "big"  # largest image chosen


@pytest.mark.backend_unit
def test_default_registry_exposes_new_discover_tools():
    registry = tr.build_default_tool_registry()
    music = {s.name for s in registry.resolve(domain="music", active_only=False)}
    book = {s.name for s in registry.resolve(domain="book", active_only=False)}
    assert {"musicbrainz.recording.discover", "lastfm.track.discover"} <= music
    assert "openlibrary.book.discover" in book


# --------------------------------------------------------------------------- #
# Param mapping + normalization
# --------------------------------------------------------------------------- #
@pytest.mark.backend_unit
def test_parameters_for_tool_maps_structured_filters():
    movie = _parameters_for_tool(
        "tmdb.movie.discover",
        "x",
        {"genres": ["comedy"], "actors": "Cillian Murphy", "directors": ["Christopher Nolan"], "min_rating": "7.5", "year": 2010},
    )
    assert movie["with_genres"] == "comedy"
    assert movie["with_cast"] == "Cillian Murphy"
    assert movie["with_crew"] == "Christopher Nolan"
    assert movie["min_rating"] == "7.5" and movie["year"] == 2010

    assert _parameters_for_tool("musicbrainz.recording.discover", "x", {"artist": "Daft Punk", "genres": ["rock"]}) == {
        "max_results": 10,
        "artist": "Daft Punk",
        "genres": "rock",
    }
    assert _parameters_for_tool("openlibrary.book.discover", "x", {"author": ["Sanderson"], "publisher": "Tor", "genres": ["fantasy"]}) == {
        "max_results": 10,
        "author": "Sanderson",
        "publisher": "Tor",
        "subject": "fantasy",
    }
    # Search tools keep the minimal {max_results, query} shape.
    assert _parameters_for_tool("hardcover.book.search", "dune", {}) == {"max_results": 10, "query": "dune"}


@pytest.mark.backend_unit
def test_structured_param_mapping_satisfies_tool_schemas_for_list_preferences():
    registry = build_default_tool_registry()

    music_params = _parameters_for_tool(
        "musicbrainz.recording.discover",
        "recommend rock music",
        {"artist": ["Daft Punk"], "genres": ["rock", "edm"]},
    )
    assert music_params["artist"] == "Daft Punk"
    assert music_params["genres"] == "rock,edm"
    assert validate_json_schema(
        registry.get("musicbrainz.recording.discover").input_schema,
        music_params,
        "input",
    ) == []

    book_params = _parameters_for_tool(
        "openlibrary.book.discover",
        "recommend a science fiction book",
        {"author": ["Ursula K. Le Guin"], "genres": ["science fiction"]},
    )
    assert book_params["author"] == "Ursula K. Le Guin"
    assert book_params["subject"] == "science fiction"
    assert validate_json_schema(
        registry.get("openlibrary.book.discover").input_schema,
        book_params,
        "input",
    ) == []


@pytest.mark.backend_unit
def test_normalize_tool_items_new_branches():
    lastfm = normalize_tool_items(
        "lastfm.track.discover",
        [{"title": "Get Lucky", "artists": ["Daft Punk"], "link": "u", "playcount": 1000, "image": "img"}],
        "music",
    )
    assert lastfm[0]["title"] == "Get Lucky"
    assert lastfm[0]["subtitle"] == "Daft Punk"
    assert lastfm[0]["source"] == "Last.fm"

    ol = normalize_tool_items(
        "openlibrary.book.discover",
        [{"title": "Mistborn", "authors": ["Brandon Sanderson"], "link": "u", "rating": 4.5, "ratings_count": 900, "subjects": ["fantasy"]}],
        "book",
    )
    assert ol[0]["subtitle"] == "Brandon Sanderson"
    assert ol[0]["rating"] == 4.5
    assert ol[0]["source"] == "OpenLibrary"

    mb = normalize_tool_items(
        "musicbrainz.recording.discover",
        [{"title": "One More Time", "artists": ["Daft Punk"], "tags": ["house"], "link": "u"}],
        "music",
    )
    assert mb[0]["title"] == "One More Time"
    assert mb[0]["source"] == "MusicBrainz"


# --------------------------------------------------------------------------- #
# ReAct gather loop
# --------------------------------------------------------------------------- #
def _discover_registry():
    """A registry whose movie discover returns nothing while over-constrained
    (with_cast present) and ten items once relaxed."""
    registry = ToolRegistry()

    def adapter(params):
        if params.get("with_cast"):
            return []
        return [{"title": f"M{i}"} for i in range(10)]

    registry.register(
        ToolSpec(
            name="tmdb.movie.discover",
            domain="movie",
            tags={"#thing", "#movie"},
            input_schema={"type": "object"},
            output_schema={"type": "array"},
            adapter=adapter,
        )
    )
    return registry


async def _run_movie(preferences, reasoner=None):
    return await run_generic_domain_graph(
        query="recommend a movie",
        domain="movie",
        tool_tags=["#thing", "#movie"],
        preferences=preferences,
        adapters=GenericGraphAdapters(tool_registry=_discover_registry(), reasoner=reasoner),
    )


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_react_deterministic_ladder_relaxes_over_constraint():
    # Seed pass is over-constrained (actor filter -> 0); the deterministic ladder
    # drops with_cast and the relaxed call fills the result set.
    result = await _run_movie({"genres": ["comedy"], "actors": "Nobody"})
    assert len(result.items) == 10
    assert result.metadata["gather_iterations"] == 1


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_react_seed_pass_enough_does_not_refine():
    result = await _run_movie({"genres": ["comedy"]})
    assert len(result.items) == 10
    assert result.metadata["gather_iterations"] == 0


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_react_reasoner_action_is_used_when_ladder_empty():
    # With only an actor (no genre) the relaxed call carries no filter, so the
    # deterministic ladder is empty — only the reasoner can recover candidates.
    calls = []

    async def reasoner(context):
        calls.append(context)
        return {"tool": "tmdb.movie.discover", "parameters": {"with_genres": "comedy"}}

    result = await _run_movie({"actors": "Nobody"}, reasoner=reasoner)
    assert len(result.items) == 10
    assert calls and result.metadata["gather_iterations"] >= 1


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_react_reasoner_error_falls_back_gracefully():
    async def reasoner(context):
        raise RuntimeError("LLM down")

    # No genre -> empty ladder; reasoner errors -> loop ends gracefully (no crash).
    result = await _run_movie({"actors": "Nobody"}, reasoner=reasoner)
    assert result.items == []


# --------------------------------------------------------------------------- #
# Profile-favorite fusion + request-time form
# --------------------------------------------------------------------------- #
@pytest.mark.backend_unit
def test_profile_movie_favorites_seed_discover_and_request_wins():
    from profile_model import assemble_domains

    profile = {"metadata": {"domains": {"movie": {"genres": ["drama"], "directors": "Christopher Nolan", "actors": "Cillian Murphy"}}}}
    slice_ = assemble_domains(profile).get("movie", {})

    # Bare request: favorites seed the discover filters.
    bare = _parameters_for_tool("tmdb.movie.discover", "recommend a movie", {**slice_})
    assert bare["with_crew"] == "Christopher Nolan"
    assert bare["with_cast"] == "Cillian Murphy"

    # Explicit request overrides the matching favorite, keeps the rest.
    fused = {**slice_, **{"directors": "Greta Gerwig", "genres": ["comedy"]}}
    got = _parameters_for_tool("tmdb.movie.discover", "x", fused)
    assert got["with_crew"] == "Greta Gerwig"
    assert got["with_genres"] == "comedy"
    assert got["with_cast"] == "Cillian Murphy"


@pytest.mark.backend_unit
def test_request_time_form_exposes_new_entity_fields():
    from preference_specs import build_domain_form

    movie = {f["key"]: f for f in build_domain_form("movie")["fields"]}
    assert {"actors", "directors", "min_rating"} <= set(movie)
    assert build_domain_form("movie")["missing_required"] == ["genres"]  # genres still required

    music = {f["key"]: f for f in build_domain_form("music")["fields"]}
    assert {"artist", "genres"} <= set(music)
    assert music["genres"]["type"] == "multiselect"
    assert build_domain_form("music")["missing_required"] == []  # nothing required for music

    book = {f["key"]: f for f in build_domain_form("book")["fields"]}
    assert {"author", "publisher"} <= set(book)
