"""Leg ETA resolution for itinerary mode.

Discipline: itinerary composition scores candidates with the deterministic
haversine estimates ONLY — no network. The real routing providers (OneMap for
Singapore walk/public-transport, Mapbox Directions elsewhere) are called for
exactly the chosen legs of a composed trajectory, never during candidate
scoring, and every provider failure degrades back to the deterministic
estimate. Provider results are cached for the process lifetime keyed on
rounded coordinates (~11 m), so slot refinements usually re-resolve their two
affected legs from cache.
"""
from __future__ import annotations

import asyncio
import datetime as _dt
import math
import os
import time
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple
from weakref import WeakKeyDictionary
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

from langgraph_metarec.tool_registry import PROVIDER_HTTP_TIMEOUT

# (lat, lng) everywhere in this module; leg ``coords`` are GeoJSON-ordered
# [[lng, lat], ...] because they feed straight into map line layers.
Point = Tuple[float, float]

# Deterministic estimate parameters: mode threshold and urban speed heuristics.
WALK_MAX_KM = 1.2
_WALK_KMH = 5.0
_PT_KMH = 20.0
_PT_OVERHEAD_MIN = 10
_DRIVE_KMH = 30.0
_DRIVE_OVERHEAD_MIN = 5

_SG_BBOX = (1.13, 1.47, 103.59, 104.10)  # lat_min, lat_max, lng_min, lng_max

_ONEMAP_TOKEN_URL = "https://www.onemap.gov.sg/api/auth/post/getToken"
_ONEMAP_ROUTE_URL = "https://www.onemap.gov.sg/api/public/routingsvc/route"
_MAPBOX_DIRECTIONS_URL = "https://api.mapbox.com/directions/v5/mapbox"

# Refresh the OneMap JWT an hour before its ~3-day expiry.
_ONEMAP_TOKEN_REFRESH_MARGIN_SECONDS = 3600

# Process-lifetime caches (TMDB-cache style: check-then-fill, failures never
# cached). The leg cache is bounded defensively; itineraries produce few legs.
_ONEMAP_TOKEN_CACHE: Dict[str, Any] = {}
# One token lock per running event loop: asyncio primitives bind to the loop
# that first awaits them, so a single module-level lock breaks as soon as a
# second loop (tests, dev reloads) contends for it.
_ONEMAP_TOKEN_LOCKS: "WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock]" = WeakKeyDictionary()
_LEG_CACHE: "OrderedDict[tuple, tuple[float, Dict[str, Any]]]" = OrderedDict()
_LEG_CACHE_MAX = 512
_LEG_CACHE_TTL_SECONDS = 30 * 60
_PT_CACHE_BUCKET_MINUTES = 15

MAX_LEG_COORDS = 60


def haversine_km(a: Point, b: Point) -> float:
    lat1, lng1 = float(a[0]), float(a[1])
    lat2, lng2 = float(b[0]), float(b[1])
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    h = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def estimate_leg(a: Point, b: Point, *, prefer: str = "auto") -> Dict[str, Any]:
    """Deterministic leg estimate — the only thing composition may use."""
    distance_km = haversine_km(a, b)
    if prefer == "drive":
        mode = "drive"
        duration = distance_km / _DRIVE_KMH * 60 + _DRIVE_OVERHEAD_MIN
    elif distance_km < WALK_MAX_KM:
        mode = "walk"
        duration = distance_km / _WALK_KMH * 60
    else:
        mode = "pt"
        duration = distance_km / _PT_KMH * 60 + _PT_OVERHEAD_MIN
    return {
        "mode": mode,
        "duration_min": max(1, int(round(duration))),
        "distance_km": round(distance_km, 2),
        "source": "estimate",
    }


def _in_singapore(p: Point) -> bool:
    lat_min, lat_max, lng_min, lng_max = _SG_BBOX
    return lat_min <= float(p[0]) <= lat_max and lng_min <= float(p[1]) <= lng_max


def decode_polyline(encoded: str, precision: int = 5) -> List[List[float]]:
    """Decode a Google-format encoded polyline into [[lng, lat], ...]."""
    coords: List[List[float]] = []
    index = lat = lng = 0
    factor = 10 ** precision
    while index < len(encoded):
        for is_lng in (False, True):
            shift = result = 0
            while True:
                byte = ord(encoded[index]) - 63
                index += 1
                result |= (byte & 0x1F) << shift
                shift += 5
                if byte < 0x20:
                    break
            delta = ~(result >> 1) if result & 1 else result >> 1
            if is_lng:
                lng += delta
            else:
                lat += delta
        coords.append([lng / factor, lat / factor])
    return coords


def _downsample(coords: List[List[float]], max_points: int = MAX_LEG_COORDS) -> List[List[float]]:
    if len(coords) <= max_points:
        return coords
    step = (len(coords) - 1) / (max_points - 1)
    sampled = [coords[int(round(i * step))] for i in range(max_points)]
    sampled[-1] = coords[-1]
    return sampled


async def _post_json(url: str, payload: Dict[str, Any]) -> Any:
    async with httpx.AsyncClient(timeout=PROVIDER_HTTP_TIMEOUT) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        return response.json()


async def _get_json(url: str, *, params: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None) -> Any:
    async with httpx.AsyncClient(timeout=PROVIDER_HTTP_TIMEOUT) as client:
        response = await client.get(url, params=params, headers=headers)
        response.raise_for_status()
        return response.json()


def _onemap_token_lock() -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    lock = _ONEMAP_TOKEN_LOCKS.get(loop)
    if lock is None:
        lock = asyncio.Lock()
        _ONEMAP_TOKEN_LOCKS[loop] = lock
    return lock


def _onemap_credentials() -> Optional[Dict[str, str]]:
    email = os.getenv("ONEMAP_EMAIL")
    password = os.getenv("ONEMAP_PASSWORD")
    if not email or not password:
        return None
    return {"email": email, "password": password}


async def _onemap_token(*, force_refresh: bool = False) -> Optional[str]:
    credentials = _onemap_credentials()
    if credentials is None:
        return None
    now = _dt.datetime.now(_dt.timezone.utc).timestamp()
    async with _onemap_token_lock():
        cached = _ONEMAP_TOKEN_CACHE.get("token")
        expiry = _ONEMAP_TOKEN_CACHE.get("expiry", 0)
        if not force_refresh and cached and now < float(expiry) - _ONEMAP_TOKEN_REFRESH_MARGIN_SECONDS:
            return cached
        try:
            data = await _post_json(_ONEMAP_TOKEN_URL, credentials)
            token = str(data["access_token"])
            _ONEMAP_TOKEN_CACHE["token"] = token
            _ONEMAP_TOKEN_CACHE["expiry"] = float(data.get("expiry_timestamp") or now + 2 * 24 * 3600)
            return token
        except Exception:
            return None  # failure never cached


def _pt_departure(
    depart_hhmm: Optional[str],
    *,
    service_date: Optional[str] = None,
    timezone: str = "Asia/Singapore",
) -> Tuple[str, str]:
    """Return the requested local service date/time without consulting server
    wall-clock time for the itinerary time itself."""
    try:
        zone = ZoneInfo(timezone)
    except ZoneInfoNotFoundError:
        zone = ZoneInfo("Asia/Singapore")
    today = _dt.datetime.now(zone).date()
    try:
        day = _dt.date.fromisoformat(str(service_date)) if service_date else today
    except ValueError:
        day = today
    hour, minute = 10, 0
    if depart_hhmm:
        try:
            hour, minute = (int(part) for part in depart_hhmm.split(":", 1))
            if not (0 <= hour and 0 <= minute < 60):
                raise ValueError
        except (ValueError, TypeError):
            hour, minute = 10, 0
    # Schedules pushed past midnight arrive as "24:30"-style times; roll them
    # into the next service day instead of discarding them for the default.
    day += _dt.timedelta(days=hour // 24)
    hour %= 24
    when = _dt.datetime.combine(day, _dt.time(hour, minute), tzinfo=zone)
    return when.strftime("%m-%d-%Y"), when.strftime("%H:%M:%S")


def _pt_steps(legs: Any) -> List[Dict[str, Any]]:
    """Summarise each OneMap public-transport sub-leg into a compact, UI-ready
    step: the MRT line / bus service, boarding & alighting stops, stop count,
    and the sub-leg's own geometry. This lets the itinerary show *which*
    transport is used and colour each segment on the map, instead of one opaque
    "transit" line."""
    steps: List[Dict[str, Any]] = []
    for leg in legs or []:
        if not isinstance(leg, dict):
            continue
        raw_mode = str(leg.get("mode") or "").strip().upper()
        if not raw_mode:
            continue
        step: Dict[str, Any] = {"mode": raw_mode.lower()}
        if raw_mode == "WALK":
            distance = leg.get("distance")
            try:
                if distance is not None:
                    step["distance_m"] = max(0, int(round(float(distance))))
            except (TypeError, ValueError):
                pass
        else:
            service = leg.get("routeShortName") or leg.get("route")
            if service not in (None, ""):
                step["service"] = str(service).strip()
            line_name = leg.get("routeLongName")
            if line_name:
                step["line_name"] = str(line_name).strip()
            board = leg.get("from").get("name") if isinstance(leg.get("from"), dict) else None
            if board:
                step["from"] = str(board).strip()
            alight = leg.get("to").get("name") if isinstance(leg.get("to"), dict) else None
            if alight:
                step["to"] = str(alight).strip()
            num_stops = leg.get("numStops")
            if isinstance(num_stops, (int, float)) and not isinstance(num_stops, bool):
                step["num_stops"] = int(num_stops)
        points = leg.get("legGeometry").get("points") if isinstance(leg.get("legGeometry"), dict) else None
        if points:
            coords = _downsample(decode_polyline(str(points)))
            if coords:
                step["coords"] = coords
        steps.append(step)
    return steps


async def _onemap_route(
    a: Point,
    b: Point,
    route_type: str,
    depart_hhmm: Optional[str],
    *,
    service_date: Optional[str],
    timezone: str,
) -> Optional[Dict[str, Any]]:
    params: Dict[str, Any] = {
        "start": f"{a[0]},{a[1]}",
        "end": f"{b[0]},{b[1]}",
        "routeType": route_type,
    }
    if route_type == "pt":
        date, route_time = _pt_departure(depart_hhmm, service_date=service_date, timezone=timezone)
        params.update({"date": date, "time": route_time, "mode": "TRANSIT", "maxWalkDistance": 1000, "numItineraries": 1})
    data: Any = None
    for attempt in range(2):
        token = await _onemap_token(force_refresh=attempt > 0)
        if not token:
            return None
        try:
            data = await _get_json(_ONEMAP_ROUTE_URL, params=params, headers={"Authorization": token})
            break
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 401 and attempt == 0:
                _ONEMAP_TOKEN_CACHE.clear()
                continue
            return None
        except Exception:
            return None
    try:
        if route_type == "pt":
            itinerary = data["plan"]["itineraries"][0]
            legs = itinerary.get("legs") or []
            coords: List[List[float]] = []
            for leg in legs:
                points = ((leg.get("legGeometry") or {}).get("points")) or ""
                if points:
                    coords.extend(decode_polyline(points))
            result: Dict[str, Any] = {
                "mode": "pt",
                "duration_min": max(1, int(round(float(itinerary["duration"]) / 60))),
            }
            fare = itinerary.get("fare")
            if fare not in (None, ""):
                result["fare"] = f"{fare} SGD"
            steps = _pt_steps(legs)
            if steps:
                result["steps"] = steps
            if coords:
                result["coords"] = _downsample(coords)
            return result
        summary = data["route_summary"]
        result = {
            "mode": "walk" if route_type == "walk" else "drive",
            "duration_min": max(1, int(round(float(summary["total_time"]) / 60))),
            "distance_km": round(float(summary["total_distance"]) / 1000, 2),
        }
        geometry = data.get("route_geometry")
        if geometry:
            result["coords"] = _downsample(decode_polyline(str(geometry)))
        return result
    except (KeyError, IndexError, TypeError, ValueError):
        return None


async def _mapbox_route(a: Point, b: Point, profile: str) -> Optional[Dict[str, Any]]:
    token = os.getenv("MAPBOX_ACCESS_TOKEN") or os.getenv("VITE_MAPBOX_TOKEN")
    if not token:
        return None
    url = f"{_MAPBOX_DIRECTIONS_URL}/{profile}/{a[1]},{a[0]};{b[1]},{b[0]}"
    try:
        data = await _get_json(url, params={"geometries": "geojson", "overview": "simplified", "access_token": token})
        route = data["routes"][0]
        result: Dict[str, Any] = {
            "mode": "walk" if profile == "walking" else "drive",
            "duration_min": max(1, int(round(float(route["duration"]) / 60))),
            "distance_km": round(float(route["distance"]) / 1000, 2),
        }
        coords = (route.get("geometry") or {}).get("coordinates")
        if coords:
            result["coords"] = _downsample([[float(lng), float(lat)] for lng, lat in coords])
        return result
    except Exception:
        return None


def _time_bucket(depart_hhmm: Optional[str]) -> Optional[int]:
    if not depart_hhmm:
        return None
    try:
        hour, minute = (int(part) for part in depart_hhmm.split(":", 1))
        return (hour * 60 + minute) // _PT_CACHE_BUCKET_MINUTES
    except (TypeError, ValueError):
        return None


def _cache_get(key: tuple) -> Optional[Dict[str, Any]]:
    entry = _LEG_CACHE.get(key)
    if entry is None:
        return None
    created_at, value = entry
    if time.monotonic() - created_at > _LEG_CACHE_TTL_SECONDS:
        _LEG_CACHE.pop(key, None)
        return None
    if hasattr(_LEG_CACHE, "move_to_end"):
        _LEG_CACHE.move_to_end(key)
    return {**value, "cache": "hit"}


def _cache_put(key: tuple, value: Dict[str, Any]) -> None:
    if len(_LEG_CACHE) >= _LEG_CACHE_MAX:
        _LEG_CACHE.pop(next(iter(_LEG_CACHE)))
    _LEG_CACHE[key] = (time.monotonic(), dict(value))


async def resolve_leg(
    a: Point,
    b: Point,
    *,
    depart_hhmm: Optional[str] = None,
    service_date: Optional[str] = None,
    timezone: str = "Asia/Singapore",
) -> Dict[str, Any]:
    """Resolve one chosen leg: deterministic estimate first, then the best
    available provider (OneMap inside Singapore, Mapbox otherwise), falling
    back to the estimate on any failure. Cached per rounded endpoints+mode."""
    estimate = estimate_leg(a, b)
    both_in_sg = _in_singapore(a) and _in_singapore(b)
    desired_provider = "onemap" if both_in_sg and _onemap_credentials() else "mapbox"
    temporal = (service_date, _time_bucket(depart_hhmm)) if estimate["mode"] == "pt" else (None, None)
    key = (
        desired_provider, round(float(a[0]), 4), round(float(a[1]), 4),
        round(float(b[0]), 4), round(float(b[1]), 4), estimate["mode"], *temporal,
    )
    cached = _cache_get(key)
    if cached is not None:
        return dict(cached)

    resolved: Optional[Dict[str, Any]] = None
    if both_in_sg and _onemap_credentials() is not None:
        route_type = "walk" if estimate["mode"] == "walk" else "pt"
        resolved = await _onemap_route(
            a, b, route_type, depart_hhmm, service_date=service_date, timezone=timezone
        )
        if resolved is not None:
            resolved["source"] = "onemap"
    if resolved is None:
        # Mapbox Directions has no public-transport profile anywhere, and OneMap
        # (Singapore-only) is the sole transit provider. A "pt" leg no provider
        # resolved must stay public transport as a deterministic estimate —
        # routing it through Mapbox would silently switch the traveller to a
        # car, inside or outside Singapore alike.
        if estimate["mode"] == "pt":
            return estimate  # no transit provider: keep PT, never cached
        profile = "walking" if estimate["mode"] == "walk" else "driving"
        resolved = await _mapbox_route(a, b, profile)
        if resolved is not None:
            resolved["source"] = "mapbox"
    if resolved is None:
        return estimate  # failures / no providers: never cached

    leg = {**estimate, **resolved}
    leg["cache"] = "miss"
    _cache_put(key, leg)
    return leg
