import pytest

from langgraph_metarec.genres import (
    detect_genres_in_text,
    get_entertainment_preference_specs,
    resolve_genre_ids,
)


@pytest.mark.backend_unit
def test_resolve_genre_ids_maps_names_aliases_and_numbers():
    assert resolve_genre_ids(["science fiction"], "movie") == [878]
    assert resolve_genre_ids(["sci-fi"], "movie") == [878]
    assert resolve_genre_ids("sci-fi, comedy", "movie") == [878, 35]
    # Already-numeric ids pass through untouched.
    assert resolve_genre_ids(["878"], "movie") == [878]
    # TV folds movie-only genres into the coarser TV taxonomy.
    assert resolve_genre_ids(["sci-fi"], "tv") == [10765]
    # Unknown tokens dropped; order preserved; deduped.
    assert resolve_genre_ids(["comedy", "nonsense", "comedy"], "movie") == [35]


@pytest.mark.backend_unit
def test_detect_genres_in_text_respects_word_boundaries():
    found = detect_genres_in_text("looking for a quiet sci-fi movie tonight", "movie")
    assert "science fiction" in found

    result = detect_genres_in_text("a warm family drama", "movie")
    assert "war" not in result  # "warm" must not trigger "war"
    assert "family" in result and "drama" in result

    assert detect_genres_in_text("", "movie") == []


@pytest.mark.backend_unit
def test_entertainment_preference_specs_expose_genre_options():
    specs = get_entertainment_preference_specs("movie")
    assert "genres" in specs
    assert "science fiction" in specs["genres"]["options"]
    assert get_entertainment_preference_specs("unknown") == {}
