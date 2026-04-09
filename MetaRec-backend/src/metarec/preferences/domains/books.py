from ..registry import PreferenceSpec
from typing import List

BOOKS_GENRE_SPECS = PreferenceSpec(
    key="books.genres",
    data_type="choice",
    localizations={
        "en": {
            "label": "Genre",
        }
    },
    options={
        "en": {
            "sci-fi": "Science Fiction",
            "non-fiction": "Non-Fiction",
        }
    }
)

def get_books_preference_specs() -> List[PreferenceSpec]:
    return [
        BOOKS_GENRE_SPECS,
    ]
