import pytest

from langgraph_metarec.genres import (
    MUSIC_GENRES,
    detect_genres_in_text,
    music_genre_tags,
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
def test_music_genre_tags_canonicalizes_to_tag_tokens():
    # Names/aliases fold to canonical tag tokens; case-insensitive; deduped.
    assert music_genre_tags(["Rock", "EDM"]) == ["rock", "edm"]
    assert music_genre_tags("hip-hop, RnB") == ["hip hop", "r&b"]
    assert music_genre_tags(["rock", "rock"]) == ["rock"]
    # Unknown/niche tags pass through unchanged so they still work as tags.
    assert music_genre_tags(["shoegaze"]) == ["shoegaze"]
    # Canonical genres are present in the curated vocabulary the form renders.
    assert "classical" in MUSIC_GENRES and "edm" in MUSIC_GENRES
