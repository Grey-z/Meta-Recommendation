"""Genre vocabulary for entertainment domains.

The TMDB *discover* endpoints filter by numeric genre ids, but users (and the
upstream LLM/preference flow) speak in genre *names*. This module owns the
name<->id mapping, a small set of aliases, and lightweight text detection so the
discover tools can actually fire from natural queries or stored preferences.

It also exposes declarative entertainment preference specs — the canonical
vocabulary a future preference form can render — so the option list lives in one
place rather than being hard-coded across the UI and the graph.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List

# Canonical TMDB genre ids. Movies and TV use different taxonomies.
MOVIE_GENRE_IDS: Dict[str, int] = {
    "action": 28,
    "adventure": 12,
    "animation": 16,
    "comedy": 35,
    "crime": 80,
    "documentary": 99,
    "drama": 18,
    "family": 10751,
    "fantasy": 14,
    "history": 36,
    "horror": 27,
    "music": 10402,
    "mystery": 9648,
    "romance": 10749,
    "science fiction": 878,
    "tv movie": 10770,
    "thriller": 53,
    "war": 10752,
    "western": 37,
}

TV_GENRE_IDS: Dict[str, int] = {
    "action & adventure": 10759,
    "animation": 16,
    "comedy": 35,
    "crime": 80,
    "documentary": 99,
    "drama": 18,
    "family": 10751,
    "kids": 10762,
    "mystery": 9648,
    "news": 10763,
    "reality": 10764,
    "sci-fi & fantasy": 10765,
    "soap": 10766,
    "talk": 10767,
    "war & politics": 10768,
    "western": 37,
}

# Free-text surface forms -> canonical movie-genre name.
_ALIASES: Dict[str, str] = {
    "sci-fi": "science fiction",
    "scifi": "science fiction",
    "sci fi": "science fiction",
    "science-fiction": "science fiction",
    "rom-com": "romance",
    "romcom": "romance",
    "rom com": "romance",
    "romantic": "romance",
    "docu": "documentary",
    "documentaries": "documentary",
    "animated": "animation",
    "anime": "animation",
    "kid": "kids",
    "children": "kids",
    "thrillers": "thriller",
    "comedies": "comedy",
    "dramas": "drama",
}

# When a movie-canonical name has no direct TV equivalent, fold it into the
# coarser TV taxonomy (e.g. movie "fantasy" -> TV "sci-fi & fantasy").
_TV_FALLBACKS: Dict[str, str] = {
    "science fiction": "sci-fi & fantasy",
    "fantasy": "sci-fi & fantasy",
    "action": "action & adventure",
    "adventure": "action & adventure",
    "war": "war & politics",
}


def _genre_map(media_type: str) -> Dict[str, int]:
    return TV_GENRE_IDS if str(media_type).lower() == "tv" else MOVIE_GENRE_IDS


def _canonical(surface: str, media_type: str) -> str | None:
    """Resolve a surface form to a genre name valid for ``media_type``."""
    token = _ALIASES.get(surface, surface)
    gmap = _genre_map(media_type)
    if token in gmap:
        return token
    if str(media_type).lower() == "tv":
        folded = _TV_FALLBACKS.get(token)
        if folded in gmap:
            return folded
    return None


def split_genres(value: Any) -> List[str]:
    """Normalize a list or comma-separated string of genre tokens to a list."""
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        tokens: Iterable[Any] = value
    else:
        tokens = str(value).split(",")
    return [str(token).strip().lower() for token in tokens if str(token).strip()]


def resolve_genre_ids(values: Any, media_type: str) -> List[int]:
    """Map genre names (or already-numeric ids) to TMDB ids, order-preserving."""
    gmap = _genre_map(media_type)
    ids: List[int] = []
    for token in split_genres(values):
        if token.isdigit():
            ids.append(int(token))
            continue
        canon = _canonical(token, media_type)
        if canon is not None:
            ids.append(gmap[canon])
    return list(dict.fromkeys(ids))


def detect_genres_in_text(text: str, media_type: str) -> List[str]:
    """Return canonical genre names mentioned in free text for ``media_type``."""
    if not text:
        return []
    lowered = str(text).lower()
    found: List[str] = []
    surfaces = set(_genre_map(media_type)) | set(MOVIE_GENRE_IDS) | set(_ALIASES)
    for surface in surfaces:
        pattern = r"(?<![a-z0-9])" + re.escape(surface) + r"(?![a-z0-9])"
        if re.search(pattern, lowered):
            canon = _canonical(surface, media_type)
            if canon is not None and canon not in found:
                found.append(canon)
    return found


# Curated music-genre vocabulary. Unlike TMDB genres these need no id resolution:
# MusicBrainz and Last.fm both filter by *tag* names, so the canonical token is
# the tag itself (e.g. "rock", "edm"). This is the single source the music
# preference form renders and the discover tools query against.
MUSIC_GENRES: List[str] = [
    "classical",
    "rock",
    "pop",
    "jazz",
    "hip hop",
    "rap",
    "electronic",
    "edm",
    "house",
    "techno",
    "dance",
    "ambient",
    "country",
    "metal",
    "folk",
    "blues",
    "r&b",
    "soul",
    "funk",
    "punk",
    "reggae",
    "indie",
    "k-pop",
    "latin",
]

# Free-text surface forms -> canonical music-genre tag.
_MUSIC_GENRE_ALIASES: Dict[str, str] = {
    "hiphop": "hip hop",
    "hip-hop": "hip hop",
    "rnb": "r&b",
    "r and b": "r&b",
    "electronica": "electronic",
    "electronic dance music": "edm",
    "kpop": "k-pop",
    "k pop": "k-pop",
    "classic": "classical",
    "classical music": "classical",
}


def music_genre_tags(values: Any) -> List[str]:
    """Map genre names/aliases to MusicBrainz/Last.fm tag tokens, lowercased,
    deduped and order-preserving. Unknown tokens pass through unchanged so niche
    tags (e.g. "shoegaze") still work."""
    tags: List[str] = []
    for token in split_genres(values):
        tags.append(_MUSIC_GENRE_ALIASES.get(token, token))
    return list(dict.fromkeys(tags))
