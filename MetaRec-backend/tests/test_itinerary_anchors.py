import pytest

from langgraph_metarec.itinerary_anchors import resolve_anchor_candidates

pytestmark = pytest.mark.backend_unit


def _hotel(identifier, title, address, lat=1.25):
    return {
        "id": identifier,
        "domain": "hotel",
        "title": title,
        "subtitle": address,
        "source": "gmap",
        "raw": {"gps_coordinates": {"latitude": lat, "longitude": 103.82}},
    }


def test_exact_anchor_name_resolves_uniquely_with_destination_bias():
    result = resolve_anchor_candidates(
        "Siloso Beach Resort",
        "Sentosa, Singapore",
        [
            _hotel("h1", "Siloso Beach Resort", "51 Imbiah Walk, Sentosa, Singapore"),
            _hotel("h2", "Siloso Beach Hotel", "Another country", 2.0),
        ],
    )
    assert result.status == "resolved"
    assert result.match["provider_id"] == "h1"
    assert result.match["latitude"] == 1.25


def test_similarly_named_anchor_candidates_require_user_choice():
    result = resolve_anchor_candidates(
        "Grand Hotel",
        "Singapore",
        [
            _hotel("h1", "Grand Hotel", "Orchard, Singapore"),
            _hotel("h2", "Grand Hotel", "Marina, Singapore", 1.29),
        ],
    )
    assert result.status == "ambiguous"
    assert [item["provider_id"] for item in result.options] == ["h1", "h2"]


def test_anchor_without_coordinates_is_not_guessed():
    result = resolve_anchor_candidates(
        "Unknown Hotel", "Singapore", [{"id": "h1", "title": "Unknown Hotel"}]
    )
    assert result.status == "unresolved"


def test_anchor_matching_uses_address_and_tolerates_minor_name_typo():
    candidate = _hotel(
        "h1",
        "Siloso Beach Resort - Sentosa",
        "51 Imbiah Walk, Sentosa, Singapore 099538",
    )
    typo = resolve_anchor_candidates("Soliso Beach Resort", "Sentosa", [candidate])
    assert typo.status == "resolved"
    full_address = resolve_anchor_candidates(
        "Siloso Beach Resort, 51 Imbiah Walk, Singapore 099538",
        "Sentosa",
        [candidate],
    )
    assert full_address.status == "resolved"
