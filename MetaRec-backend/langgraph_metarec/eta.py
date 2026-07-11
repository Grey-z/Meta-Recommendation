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

import datetime as _dt
import math
import os
from typing import Any, Dict, List, Optional, Tuple

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
_LEG_CACHE: Dict[tuple, Dict[str, Any]] = {}
_LEG_CACHE_MAX = 512

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


def _post_json(url: str, payload: Dict[str, Any]) -> Any:
    with httpx.Client(timeout=PROVIDER_HTTP_TIMEOUT) as client:
        response = client.post(url, json=payload)
        response.raise_for_status()
        return response.json()


def _get_json(url: str, *, params: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None) -> Any:
    with httpx.Client(timeout=PROVIDER_HTTP_TIMEOUT) as client:
        response = client.get(url, params=params, headers=headers)
        response.raise_for_status()
        return response.json()


def _onemap_credentials() -> Optional[Dict[str, str]]:
    email = os.getenv("ONEMAP_EMAIL")
    password = os.getenv("ONEMAP_PASSWORD")
    if not email or not password:
        return None
    return {"email": email, "password": password}


def _onemap_token() -> Optional[str]:
    credentials = _onemap_credentials()
    if credentials is None:
        return None
    now = _dt.datetime.now(_dt.timezone.utc).timestamp()
    cached = _ONEMAP_TOKEN_CACHE.get("token")
    expiry = _ONEMAP_TOKEN_CACHE.get("expiry", 0)
    if cached and now < float(expiry) - _ONEMAP_TOKEN_REFRESH_MARGIN_SECONDS:
        return cached
    try:
        data = _post_json(_ONEMAP_TOKEN_URL, credentials)
        token = str(data["access_token"])
        _ONEMAP_TOKEN_CACHE["token"] = token
        _ONEMAP_TOKEN_CACHE["expiry"] = float(data.get("expiry_timestamp") or now + 2 * 24 * 3600)
        return token
    except Exception:
        return None  # failure never cached


def _pt_departure(depart_hhmm: Optional[str]) -> Tuple[str, str]:
    """OneMap pt routing wants an explicit date/time; past times are replaced
    with the current time so a morning slot planned at night still routes."""
    now = _dt.datetime.now()
    when = now
    if depart_hhmm:
        try:
            hour, minute = (int(part) for part in depart_hhmm.split(":", 1))
            candidate = now.replace(hour=hour, minute=minute, second=0)
            if candidate > now:
                when = candidate
        except (ValueError, TypeError):
            pass
    return when.strftime("%m-%d-%Y"), when.strftime("%H:%M:%S")


def _onemap_route(a: Point, b: Point, route_type: str, depart_hhmm: Optional[str]) -> Optional[Dict[str, Any]]:
    token = _onemap_token()
    if not token:
        return None
    params: Dict[str, Any] = {
        "start": f"{a[0]},{a[1]}",
        "end": f"{b[0]},{b[1]}",
        "routeType": route_type,
    }
    if route_type == "pt":
        date, time = _pt_departure(depart_hhmm)
        params.update({"date": date, "time": time, "mode": "TRANSIT", "maxWalkDistance": 1000, "numItineraries": 1})
    try:
        data = _get_json(_ONEMAP_ROUTE_URL, params=params, headers={"Authorization": token})
        if route_type == "pt":
            itinerary = data["plan"]["itineraries"][0]
            coords: List[List[float]] = []
            for leg in itinerary.get("legs") or []:
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
    except Exception:
        return None


def _mapbox_route(a: Point, b: Point, profile: str) -> Optional[Dict[str, Any]]:
    token = os.getenv("VITE_MAPBOX_TOKEN")
    if not token:
        return None
    url = f"{_MAPBOX_DIRECTIONS_URL}/{profile}/{a[1]},{a[0]};{b[1]},{b[0]}"
    try:
        data = _get_json(url, params={"geometries": "geojson", "overview": "simplified", "access_token": token})
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


def resolve_leg(a: Point, b: Point, *, depart_hhmm: Optional[str] = None) -> Dict[str, Any]:
    """Resolve one chosen leg: deterministic estimate first, then the best
    available provider (OneMap inside Singapore, Mapbox otherwise), falling
    back to the estimate on any failure. Cached per rounded endpoints+mode."""
    estimate = estimate_leg(a, b)
    key = (round(float(a[0]), 4), round(float(a[1]), 4), round(float(b[0]), 4), round(float(b[1]), 4), estimate["mode"])
    cached = _LEG_CACHE.get(key)
    if cached is not None:
        return dict(cached)

    resolved: Optional[Dict[str, Any]] = None
    if _in_singapore(a) and _in_singapore(b) and _onemap_credentials() is not None:
        route_type = "walk" if estimate["mode"] == "walk" else "pt"
        resolved = _onemap_route(a, b, route_type, depart_hhmm)
        if resolved is not None:
            resolved["source"] = "onemap"
    if resolved is None:
        profile = "walking" if estimate["mode"] == "walk" else "driving"
        resolved = _mapbox_route(a, b, profile)
        if resolved is not None:
            resolved["source"] = "mapbox"
    if resolved is None:
        return estimate  # failures / no providers: never cached

    leg = {**estimate, **resolved}
    if len(_LEG_CACHE) >= _LEG_CACHE_MAX:
        _LEG_CACHE.clear()
    _LEG_CACHE[key] = dict(leg)
    return leg
