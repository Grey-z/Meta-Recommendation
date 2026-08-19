import asyncio

import pytest

import langgraph_metarec.eta as eta

pytestmark = pytest.mark.backend_unit

MBS = (1.2834, 103.8607)      # Marina Bay Sands
MERLION = (1.2868, 103.8545)  # ~0.8 km away
SENTOSA = (1.2494, 103.8303)  # ~5 km away
PARIS = (48.8584, 2.2945)     # outside Singapore


@pytest.fixture(autouse=True)
def _fresh_caches(monkeypatch):
    monkeypatch.setattr(eta, "_LEG_CACHE", {})
    monkeypatch.setattr(eta, "_ONEMAP_TOKEN_CACHE", {})
    monkeypatch.delenv("MAPBOX_ACCESS_TOKEN", raising=False)


@pytest.fixture()
def _no_credentials(monkeypatch):
    monkeypatch.delenv("ONEMAP_EMAIL", raising=False)
    monkeypatch.delenv("ONEMAP_PASSWORD", raising=False)
    monkeypatch.delenv("VITE_MAPBOX_TOKEN", raising=False)
    monkeypatch.delenv("MAPBOX_ACCESS_TOKEN", raising=False)


@pytest.fixture()
def _onemap_credentials(monkeypatch):
    monkeypatch.setenv("ONEMAP_EMAIL", "user@example.com")
    monkeypatch.setenv("ONEMAP_PASSWORD", "secret")
    monkeypatch.delenv("VITE_MAPBOX_TOKEN", raising=False)
    monkeypatch.delenv("MAPBOX_ACCESS_TOKEN", raising=False)


def test_haversine_known_singapore_pair():
    distance = eta.haversine_km(MBS, MERLION)
    assert 0.7 <= distance <= 0.9


def test_estimate_leg_mode_thresholds():
    walk = eta.estimate_leg(MBS, MERLION)
    assert walk["mode"] == "walk"
    assert walk["source"] == "estimate"
    assert 5 <= walk["duration_min"] <= 15

    transit = eta.estimate_leg(MBS, SENTOSA)
    assert transit["mode"] == "pt"
    # Overhead keeps even mid-range hops from looking instant.
    assert transit["duration_min"] >= eta._PT_OVERHEAD_MIN

    drive = eta.estimate_leg(MBS, SENTOSA, prefer="drive")
    assert drive["mode"] == "drive"


def test_pt_departure_rolls_past_midnight_times_into_the_next_day():
    # Past-midnight schedule times arrive as "24:30"; they must roll into the
    # next service day rather than being discarded for the 10:00 default.
    date, time = eta._pt_departure("24:30", service_date="2026-08-03")
    assert (date, time) == ("08-04-2026", "00:30:00")
    date, time = eta._pt_departure("23:59", service_date="2026-08-03")
    assert (date, time) == ("08-03-2026", "23:59:00")
    date, time = eta._pt_departure("nonsense", service_date="2026-08-03")
    assert (date, time) == ("08-03-2026", "10:00:00")


def test_decode_polyline_reference_fixture():
    # Canonical Google polyline example: (38.5,-120.2) (40.7,-120.95) (43.252,-126.453)
    coords = eta.decode_polyline("_p~iF~ps|U_ulLnnqC_mqNvxq`@")
    assert coords == [[-120.2, 38.5], [-120.95, 40.7], [-126.453, 43.252]]


def test_downsample_preserves_endpoints():
    coords = [[float(i), float(i)] for i in range(200)]
    sampled = eta._downsample(coords, max_points=60)
    assert len(sampled) == 60
    assert sampled[0] == [0.0, 0.0]
    assert sampled[-1] == [199.0, 199.0]

    short = [[0.0, 0.0], [1.0, 1.0]]
    assert eta._downsample(short) == short


@pytest.mark.asyncio
async def test_resolve_leg_without_credentials_is_pure_estimate(monkeypatch, _no_credentials):
    def boom(*args, **kwargs):
        raise AssertionError("no provider may be called without credentials")

    monkeypatch.setattr(eta, "_get_json", boom)
    monkeypatch.setattr(eta, "_post_json", boom)

    leg = await eta.resolve_leg(MBS, SENTOSA)
    assert leg["source"] == "estimate"
    # Estimates are never cached as provider results.
    assert eta._LEG_CACHE == {}


def test_onemap_token_lock_survives_multiple_event_loops(monkeypatch, _onemap_credentials):
    async def fake_post(url, payload):
        await asyncio.sleep(0)  # hold the lock across an await -> real contention
        return {"access_token": "jwt-loop", "expiry_timestamp": 4102444800}

    monkeypatch.setattr(eta, "_post_json", fake_post)

    async def contended_fetch():
        eta._ONEMAP_TOKEN_CACHE.clear()
        tokens = await asyncio.gather(eta._onemap_token(), eta._onemap_token())
        assert tokens == ["jwt-loop", "jwt-loop"]

    # Contended acquire binds an asyncio.Lock to the running loop. A single
    # module-level lock would raise "bound to a different event loop" on the
    # second run; the per-loop lock registry must survive both.
    asyncio.run(contended_fetch())
    asyncio.run(contended_fetch())


@pytest.mark.asyncio
async def test_onemap_token_is_cached(monkeypatch, _onemap_credentials):
    calls = {"n": 0}

    async def fake_post(url, payload):
        calls["n"] += 1
        assert payload == {"email": "user@example.com", "password": "secret"}
        return {"access_token": "jwt-123", "expiry_timestamp": 4102444800}

    monkeypatch.setattr(eta, "_post_json", fake_post)
    assert await eta._onemap_token() == "jwt-123"
    assert await eta._onemap_token() == "jwt-123"
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_resolve_leg_uses_onemap_pt_within_singapore(monkeypatch, _onemap_credentials):
    async def fake_post(url, payload):
        return {"access_token": "jwt", "expiry_timestamp": 4102444800}
    monkeypatch.setattr(eta, "_post_json", fake_post)

    async def fake_get(url, *, params=None, headers=None):
        assert headers == {"Authorization": "jwt"}
        assert params["routeType"] == "pt"
        assert params["mode"] == "TRANSIT"
        return {
            "plan": {
                "itineraries": [
                    {
                        "duration": 1500,
                        "fare": "1.90",
                        "legs": [{"legGeometry": {"points": "_p~iF~ps|U_ulLnnqC"}}],
                    }
                ]
            }
        }

    monkeypatch.setattr(eta, "_get_json", fake_get)

    leg = await eta.resolve_leg(MBS, SENTOSA, depart_hhmm="10:00")
    assert leg["source"] == "onemap"
    assert leg["mode"] == "pt"
    assert leg["duration_min"] == 25
    assert leg["fare"] == "1.90 SGD"
    assert leg["coords"][0] == [-120.2, 38.5]
    # The haversine distance estimate survives when pt reports no distance.
    assert leg["distance_km"] > 3


@pytest.mark.asyncio
async def test_resolve_leg_onemap_pt_reports_transit_steps(monkeypatch, _onemap_credentials):
    async def fake_post(url, payload):
        return {"access_token": "jwt", "expiry_timestamp": 4102444800}

    async def fake_get(url, *, params=None, headers=None):
        return {
            "plan": {"itineraries": [{
                "duration": 1800,
                "fare": "1.99",
                "legs": [
                    {"mode": "WALK", "distance": 240.4,
                     "legGeometry": {"points": "_p~iF~ps|U"}},
                    {"mode": "BUS", "route": "199", "routeShortName": "199",
                     "routeLongName": "SBS 199", "numStops": 5,
                     "from": {"name": "Marina Bay Stn"}, "to": {"name": "Buona Vista Stn"},
                     "legGeometry": {"points": "_p~iF~ps|U_ulLnnqC"}},
                    {"mode": "SUBWAY", "routeShortName": "EW", "routeLongName": "East West Line",
                     "numStops": 4, "from": {"name": "Buona Vista"}, "to": {"name": "Outram Park"},
                     "legGeometry": {"points": "_p~iF~ps|U"}},
                    {"mode": "WALK", "distance": 130.0},
                ],
            }]}
        }

    monkeypatch.setattr(eta, "_post_json", fake_post)
    monkeypatch.setattr(eta, "_get_json", fake_get)

    leg = await eta.resolve_leg(MBS, SENTOSA, depart_hhmm="10:00")
    assert leg["mode"] == "pt"
    steps = leg["steps"]
    assert [step["mode"] for step in steps] == ["walk", "bus", "subway", "walk"]
    assert steps[0]["distance_m"] == 240
    assert steps[1]["service"] == "199"
    assert steps[1]["from"] == "Marina Bay Stn" and steps[1]["to"] == "Buona Vista Stn"
    assert steps[1]["num_stops"] == 5
    assert steps[2]["service"] == "EW" and steps[2]["line_name"] == "East West Line"
    # Transit sub-legs with geometry carry their own coords for map colouring.
    assert steps[1]["coords"] == [[-120.2, 38.5], [-120.95, 40.7]]
    # A sub-leg without geometry (final walk) omits coords rather than erroring.
    assert "coords" not in steps[3]


@pytest.mark.asyncio
async def test_resolve_leg_uses_onemap_walk_for_short_hops(monkeypatch, _onemap_credentials):
    async def fake_post(url, payload):
        return {"access_token": "jwt", "expiry_timestamp": 4102444800}
    monkeypatch.setattr(eta, "_post_json", fake_post)

    async def fake_get(url, *, params=None, headers=None):
        assert params["routeType"] == "walk"
        return {"route_summary": {"total_time": 660, "total_distance": 850}, "route_geometry": "_p~iF~ps|U"}

    monkeypatch.setattr(eta, "_get_json", fake_get)

    leg = await eta.resolve_leg(MBS, MERLION)
    assert leg["source"] == "onemap"
    assert leg["mode"] == "walk"
    assert leg["duration_min"] == 11
    assert leg["distance_km"] == 0.85


@pytest.mark.asyncio
async def test_resolve_leg_falls_back_to_mapbox_outside_singapore(monkeypatch):
    monkeypatch.delenv("ONEMAP_EMAIL", raising=False)
    monkeypatch.delenv("ONEMAP_PASSWORD", raising=False)
    monkeypatch.setenv("VITE_MAPBOX_TOKEN", "pk.test")

    async def fake_get(url, *, params=None, headers=None):
        assert "directions/v5/mapbox/driving" in url
        assert params["access_token"] == "pk.test"
        return {"routes": [{"duration": 900, "distance": 7200, "geometry": {"coordinates": [[2.29, 48.85], [2.35, 48.86]]}}]}

    monkeypatch.setattr(eta, "_get_json", fake_get)

    leg = await eta.resolve_leg(PARIS, (48.8606, 2.3376))
    assert leg["source"] == "mapbox"
    assert leg["mode"] == "drive"
    assert leg["duration_min"] == 15
    assert leg["distance_km"] == 7.2
    assert leg["coords"] == [[2.29, 48.85], [2.35, 48.86]]


@pytest.mark.asyncio
async def test_resolve_leg_pt_in_singapore_never_falls_back_to_mapbox_driving(monkeypatch):
    # Production scenario: a Mapbox token is configured but OneMap credentials
    # are not. A long ("pt") Singapore leg must stay public transport as a
    # deterministic estimate rather than being rerouted by car via Mapbox.
    monkeypatch.delenv("ONEMAP_EMAIL", raising=False)
    monkeypatch.delenv("ONEMAP_PASSWORD", raising=False)
    monkeypatch.setenv("MAPBOX_ACCESS_TOKEN", "pk.test")

    def boom(*args, **kwargs):
        raise AssertionError("Mapbox must not be called for an SG public-transport leg")

    monkeypatch.setattr(eta, "_get_json", boom)

    leg = await eta.resolve_leg(MBS, SENTOSA)
    assert leg["mode"] == "pt"
    assert leg["source"] == "estimate"
    assert eta._LEG_CACHE == {}  # estimates are never cached as provider results


@pytest.mark.asyncio
async def test_resolve_leg_provider_failure_degrades_to_estimate(monkeypatch, _onemap_credentials):
    async def fake_post(url, payload):
        return {"access_token": "jwt", "expiry_timestamp": 4102444800}
    async def fake_get(*args, **kwargs):
        return {"unexpected": "shape"}
    monkeypatch.setattr(eta, "_post_json", fake_post)
    monkeypatch.setattr(eta, "_get_json", fake_get)

    leg = await eta.resolve_leg(MBS, SENTOSA)
    assert leg["source"] == "estimate"
    assert eta._LEG_CACHE == {}  # failures never cached


@pytest.mark.asyncio
async def test_resolve_leg_cache_hit_skips_second_provider_call(monkeypatch, _onemap_credentials):
    async def fake_post(url, payload):
        return {"access_token": "jwt", "expiry_timestamp": 4102444800}
    monkeypatch.setattr(eta, "_post_json", fake_post)
    calls = {"n": 0}

    async def fake_get(url, *, params=None, headers=None):
        calls["n"] += 1
        return {"route_summary": {"total_time": 600, "total_distance": 800}, "route_geometry": ""}

    monkeypatch.setattr(eta, "_get_json", fake_get)

    first = await eta.resolve_leg(MBS, MERLION)
    second = await eta.resolve_leg(MBS, MERLION)
    assert calls["n"] == 1
    assert {key: value for key, value in first.items() if key != "cache"} == {
        key: value for key, value in second.items() if key != "cache"
    }
    assert first["cache"] == "miss"
    assert second["cache"] == "hit"
    assert second["source"] == "onemap"


@pytest.mark.asyncio
async def test_pt_cache_is_scoped_by_service_time(monkeypatch, _onemap_credentials):
    async def fake_post(url, payload):
        return {"access_token": "jwt", "expiry_timestamp": 4102444800}

    calls = []

    async def fake_get(url, *, params=None, headers=None):
        calls.append((params["date"], params["time"]))
        return {"plan": {"itineraries": [{"duration": 1200, "legs": []}]}}

    monkeypatch.setattr(eta, "_post_json", fake_post)
    monkeypatch.setattr(eta, "_get_json", fake_get)
    await eta.resolve_leg(MBS, SENTOSA, depart_hhmm="10:02", service_date="2026-08-01")
    await eta.resolve_leg(MBS, SENTOSA, depart_hhmm="10:10", service_date="2026-08-01")
    await eta.resolve_leg(MBS, SENTOSA, depart_hhmm="10:20", service_date="2026-08-01")
    await eta.resolve_leg(MBS, SENTOSA, depart_hhmm="10:02", service_date="2026-08-02")

    assert len(calls) == 3  # first two share a 15-minute bucket
    assert calls[0] == ("08-01-2026", "10:02:00")
    assert calls[-1][0] == "08-02-2026"


@pytest.mark.asyncio
async def test_async_provider_wait_does_not_block_event_loop(monkeypatch):
    monkeypatch.delenv("ONEMAP_EMAIL", raising=False)
    monkeypatch.delenv("ONEMAP_PASSWORD", raising=False)
    monkeypatch.setenv("MAPBOX_ACCESS_TOKEN", "pk.test")
    provider_started = asyncio.Event()

    async def slow_get(url, *, params=None, headers=None):
        provider_started.set()
        await asyncio.sleep(0.02)
        return {"routes": [{"duration": 600, "distance": 1000, "geometry": {"coordinates": []}}]}

    monkeypatch.setattr(eta, "_get_json", slow_get)
    task = asyncio.create_task(eta.resolve_leg(PARIS, (48.8606, 2.3376)))
    await provider_started.wait()
    await asyncio.sleep(0)
    assert not task.done()
    await task
