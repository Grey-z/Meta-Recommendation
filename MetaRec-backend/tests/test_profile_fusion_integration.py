"""Cross-cutting guards for the profile -> dispatch -> tool-param contract.

These tie together the pure pieces that the dispatcher (service.run_domain ->
execute_domain_task) composes, so a regression in any link is caught without
needing a live task graph or Postgres.
"""

import pytest

from profile_model import assemble_domains, build_recommender_profile_block
from preference_specs import build_domain_form
from langgraph_metarec.graphs.generic_graph import _parameters_for_tool
from langgraph_metarec.genres import resolve_genre_ids


def _profile() -> dict:
    return {
        "demographics": {"occupation": "engineer"},
        "dining_habits": {"dietary_restrictions": "vegetarian", "typical_budget": "20-60 SGD"},
        "metadata": {
            "taste_persona": "into hard sci-fi",
            "domains": {"movie": {"genres": ["science fiction", "drama"]}},
        },
    }


@pytest.mark.backend_unit
def test_movie_profile_slice_drives_discover_params():
    # The same fusion the generic dispatch does: slice -> preferences -> params.
    domain_slice = assemble_domains(_profile())["movie"]
    params = _parameters_for_tool("tmdb.movie.discover", "find me something good", domain_slice)
    assert "with_genres" in params
    assert resolve_genre_ids(params["with_genres"], "movie") == [878, 18]  # sci-fi, drama


@pytest.mark.backend_unit
def test_request_preferences_override_profile_slice():
    profile = {"metadata": {"domains": {"movie": {"genres": ["drama"]}}}}
    domain_slice = assemble_domains(profile)["movie"]
    # execute_domain_task merges as {**slice, **request} so the request wins.
    fused = {**domain_slice, **{"genres": ["comedy"]}}
    params = _parameters_for_tool("tmdb.movie.discover", "x", fused)
    assert resolve_genre_ids(params["with_genres"], "movie") == [35]  # comedy, not drama


@pytest.mark.backend_unit
def test_restaurant_slice_never_leaks_into_a_movie_task():
    profile = _profile()
    block = build_recommender_profile_block(profile, "movie")
    assert "into hard sci-fi" in block  # persona carries across
    assert "vegetarian" not in block  # restaurant slice does not
    movie_slice = assemble_domains(profile)["movie"]
    assert "dietary_restrictions" not in movie_slice and "typical_budget" not in movie_slice


@pytest.mark.backend_unit
def test_form_completeness_reflects_the_profile_slice():
    movie_slice = assemble_domains(_profile())["movie"]
    assert build_domain_form("movie", movie_slice)["complete"] is True
    assert "genres" in build_domain_form("movie", {})["missing_required"]
