import pytest

from langgraph_metarec import itinerary_composer as composer

pytestmark = pytest.mark.backend_unit


def _generic(item_id, title, lat=None, lng=None, rating=None, domain="attraction"):
    raw = {}
    if lat is not None:
        raw["gps_coordinates"] = {"latitude": lat, "longitude": lng}
    return {"id": item_id, "title": title, "rating": rating, "domain": domain, "raw": raw}


def _restaurant(item_id, name, lat, lng, rating=None, price_pp=None):
    rec = {
        "id": item_id,
        "name": name,
        "address": f"{name} street",
        "rating": rating,
        "gps_coordinates": {"latitude": lat, "longitude": lng},
    }
    if price_pp is not None:
        rec["price_per_person_sgd"] = price_pp
    return rec


def _flat_estimator(a, b, **kwargs):
    # Distance-proportional but deterministic: keeps greedy math easy to reason about.
    distance = composer.estimate_leg(a, b)["distance_km"]
    return {"mode": "walk", "duration_min": 10, "distance_km": distance, "source": "estimate"}


def _slot(index, domain, candidates, time=None, label=None):
    return {
        "slot_index": index,
        "domain": domain,
        "slot_label": label or f"{domain} stop",
        "slot_time": time,
        "candidates": candidates,
    }


def test_swap_choice_rejects_item_already_chosen_in_another_slot():
    # "shared" is a candidate of BOTH slots but wins neither at compose time,
    # so it sits in both alternates lists. Once one slot swaps it in, the other
    # slot must not be able to duplicate it.
    shared = _generic("shared", "Shared Spot", 1.3010, 103.8510, rating=4.0)
    slots = [
        _slot(0, "attraction", [_generic("a0", "Museum", 1.300, 103.850, rating=4.8), dict(shared)]),
        _slot(1, "attraction", [_generic("a1", "Gallery", 1.3005, 103.8505, rating=4.8), dict(shared)]),
    ]
    block = composer.compose_itinerary(slots, location="Sentosa")
    assert block["slots"][0]["chosen"]["id"] == "a0"
    assert block["slots"][1]["chosen"]["id"] == "a1"
    assert "shared" in [alt["id"] for alt in block["slots"][0]["alternates"]]
    assert "shared" in [alt["id"] for alt in block["slots"][1]["alternates"]]

    swapped = composer.swap_choice(block, 0, "shared")
    assert swapped["slots"][0]["chosen"]["id"] == "shared"

    with pytest.raises(ValueError, match="already used"):
        composer.swap_choice(swapped, 1, "shared")


def test_candidate_geo_reads_both_shapes():
    assert composer.candidate_geo(_restaurant("r1", "Kopi", 1.30, 103.85)) == (1.30, 103.85)
    assert composer.candidate_geo(_generic("a1", "Museum", 1.29, 103.86)) == (1.29, 103.86)
    assert composer.candidate_geo(_generic("a2", "No geo")) is None
    assert composer.candidate_geo({"raw": {"gps_coordinates": {"latitude": "x"}}}) is None


def test_compose_greedy_prefers_near_good_over_far_best():
    slots = [
        _slot(0, "attraction", [_generic("a0", "Anchor", 1.300, 103.850, rating=4.5)]),
        _slot(
            1,
            "restaurant",
            [
                _restaurant("far-best", "Far Best", 1.400, 103.950, rating=4.9),
                _restaurant("near-good", "Near Good", 1.301, 103.851, rating=4.3),
            ],
        ),
    ]
    block = composer.compose_itinerary(slots, location="Sentosa")

    assert block["slots"][0]["chosen"]["id"] == "a0"
    # ~15 km away cannot be bought back by +0.6 rating.
    assert block["slots"][1]["chosen"]["id"] == "near-good"
    assert [alt["id"] for alt in block["slots"][1]["alternates"]] == ["far-best"]
    assert len(block["legs"]) == 1
    assert block["legs"][0]["source"] == "estimate"


def test_geo_less_candidates_stay_alternates_and_empty_slot_is_null():
    slots = [
        _slot(0, "attraction", [_generic("no-geo", "Mystery"), _generic("geo", "Museum", 1.29, 103.86, rating=4.0)]),
        _slot(1, "restaurant", []),
        _slot(2, "attraction", [_generic("a2", "Viewpoint", 1.295, 103.858)]),
    ]
    block = composer.compose_itinerary(slots, location="Sentosa")

    # Geo-located candidate wins even though the geo-less one ranked first.
    assert block["slots"][0]["chosen"]["id"] == "geo"
    assert [alt["id"] for alt in block["slots"][0]["alternates"]] == ["no-geo"]
    # Empty slot: null chosen, no leg to/from it.
    assert block["slots"][1]["chosen"] is None
    assert len(block["legs"]) == 1
    assert (block["legs"][0]["from_index"], block["legs"][0]["to_index"]) == (0, 2)


def test_compose_never_reuses_the_same_poi_across_slots():
    shared = _generic("same", "Shared", 1.300, 103.850, rating=4.9)
    block = composer.compose_itinerary(
        [
            _slot(0, "attraction", [shared, _generic("morning", "Morning", 1.301, 103.851)]),
            _slot(1, "attraction", [shared, _generic("afternoon", "Afternoon", 1.302, 103.852)]),
        ],
        location="Singapore",
    )
    chosen = [slot["chosen"]["id"] for slot in block["slots"]]
    assert len(chosen) == len(set(chosen)) == 2
    assert block["validation"]["status"] == "valid"


def test_beam_search_optimizes_the_whole_route_not_only_the_first_rank():
    block = composer.compose_itinerary(
        [
            _slot(0, "attraction", [
                _generic("far-top", "Far top", 1.40, 103.95, rating=5.0),
                _generic("near", "Near", 1.300, 103.850, rating=4.4),
            ]),
            _slot(1, "restaurant", [_restaurant("lunch", "Lunch", 1.301, 103.851, rating=4.5)]),
        ],
        location="Singapore",
    )
    assert block["slots"][0]["chosen"]["id"] == "near"
    assert block["optimizer"]["strategy"] == "bounded_beam_search"
    assert block["optimizer"]["expanded_states"] > 0


def test_timeline_respects_preferred_times_and_totals():
    slots = [
        _slot(0, "attraction", [_generic("a0", "Museum", 1.300, 103.850)], time="10:00"),
        _slot(1, "restaurant", [_restaurant("r1", "Lunch", 1.301, 103.851, price_pp=25)], time="12:30"),
        _slot(2, "attraction", [_generic("a2", "Park", 1.302, 103.852)], time="14:30"),
    ]
    block = composer.compose_itinerary(slots, location="Sentosa", start_time="10:00", budget="< 150 SGD", estimator=_flat_estimator)

    times = [slot["time"] for slot in block["slots"]]
    # 10:00 +120 dwell +10 leg = 12:10 -> preferred 12:30 wins; 12:30+90+10 = 14:10 -> 14:30.
    assert times == ["10:00", "12:30", "14:30"]
    assert block["totals"]["end_time"] == "16:30"  # 14:30 + 120 attraction dwell
    assert block["totals"]["total_travel_min"] == 20
    assert block["totals"]["budget_note"] == "Estimated food spend ≈ 25 SGD/person (your budget: < 150 SGD)"


def test_budget_note_absent_without_parseable_prices():
    slots = [_slot(0, "attraction", [_generic("a0", "Museum", 1.30, 103.85)])]
    block = composer.compose_itinerary(slots, location="Sentosa", budget="< 100 SGD")
    assert "budget_note" not in block["totals"]


def test_swap_choice_refreshes_only_adjacent_legs():
    slots = [
        _slot(0, "attraction", [_generic("a0", "Museum", 1.300, 103.850)]),
        _slot(1, "restaurant", [
            _restaurant("r-old", "Old Lunch", 1.301, 103.851, rating=4.5),
            _restaurant("r-new", "New Lunch", 1.305, 103.855, rating=4.0),
        ]),
        _slot(2, "attraction", [_generic("a2", "Park", 1.302, 103.852)]),
        _slot(3, "attraction", [_generic("a3", "Beach", 1.303, 103.853)]),
    ]
    block = composer.compose_itinerary(slots, location="Sentosa")
    # Simulate provider resolution of every leg.
    for leg in block["legs"]:
        leg["source"] = "onemap"

    swapped = composer.swap_choice(block, 1, "r-new")

    assert swapped["slots"][1]["chosen"]["id"] == "r-new"
    assert "r-old" in [alt["id"] for alt in swapped["slots"][1]["alternates"]]
    by_pair = {(leg["from_index"], leg["to_index"]): leg for leg in swapped["legs"]}
    # Adjacent legs re-estimated; the untouched far leg keeps its resolution.
    assert by_pair[(0, 1)]["source"] == "estimate"
    assert by_pair[(1, 2)]["source"] == "estimate"
    assert by_pair[(2, 3)]["source"] == "onemap"
    # Original block untouched (pure function).
    assert all(leg["source"] == "onemap" for leg in block["legs"])


def test_swap_choice_validates_inputs():
    block = composer.compose_itinerary(
        [_slot(0, "attraction", [_generic("a0", "Museum", 1.30, 103.85)])], location="Sentosa"
    )
    with pytest.raises(ValueError):
        composer.swap_choice(block, 9, "a0")
    with pytest.raises(ValueError):
        composer.swap_choice(block, 0, "not-an-alternate")


def test_replace_slot_candidates_rechooses_against_fixed_neighbors():
    slots = [
        _slot(0, "attraction", [_generic("a0", "Museum", 1.300, 103.850)]),
        _slot(1, "restaurant", [_restaurant("r-old", "Old Lunch", 1.301, 103.851)]),
        _slot(2, "attraction", [_generic("a2", "Park", 1.302, 103.852)]),
    ]
    block = composer.compose_itinerary(slots, location="Sentosa")

    refined = composer.replace_slot_candidates(
        block,
        1,
        [
            _restaurant("sea-far", "Sea View Far", 1.340, 103.900, rating=4.8),
            _restaurant("sea-near", "Sea View Near", 1.3015, 103.8515, rating=4.4),
        ],
    )

    assert refined["slots"][1]["chosen"]["id"] == "sea-near"  # anchored to slot 0
    assert [alt["id"] for alt in refined["slots"][1]["alternates"]] == ["sea-far"]
    assert refined["slots"][0]["chosen"]["id"] == "a0"  # neighbors untouched
    assert refined["slots"][2]["chosen"]["id"] == "a2"


@pytest.mark.asyncio
async def test_resolve_block_legs_resolves_estimates_only_and_recomputes():
    slots = [
        _slot(0, "attraction", [_generic("a0", "Museum", 1.300, 103.850)], time="10:00"),
        _slot(1, "restaurant", [_restaurant("r1", "Lunch", 1.301, 103.851)]),
        _slot(2, "attraction", [_generic("a2", "Park", 1.302, 103.852)]),
    ]
    block = composer.compose_itinerary(slots, location="Sentosa", estimator=_flat_estimator)
    calls = []

    def fake_resolver(a, b, depart_hhmm=None):
        calls.append((a, b, depart_hhmm))
        return {"mode": "pt", "duration_min": 30, "distance_km": 2.0, "source": "onemap", "fare": "1.50 SGD"}

    resolved = await composer.resolve_block_legs(block, fake_resolver)

    assert len(calls) == 2  # exactly N-1 legs
    assert all(leg["source"] == "onemap" for leg in resolved["legs"])
    assert resolved["totals"]["total_travel_min"] == 60
    assert [call[2] for call in calls] == ["12:00", "14:00"]
    # Second pass resolves nothing further (idempotent on provider-backed legs).
    await composer.resolve_block_legs(resolved, fake_resolver)
    assert len(calls) == 2
