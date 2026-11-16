"""Geodesy helpers (great-circle distance, bearings, circles, interpolation)."""
from __future__ import annotations

import math

import numpy as np

EARTH_RADIUS_KM = 6371.0088
CARDINALS_16 = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
                "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


def haversine_km(lat1, lon1, lat2, lon2):
    """Great-circle distance in km. Works with scalars, arrays and Series."""
    lat1, lon1, lat2, lon2 = (np.radians(np.asarray(v, dtype=float)) for v in (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(a))


def bearing_deg(lat1, lon1, lat2, lon2):
    """Initial bearing (0-360, clockwise from north) from point 1 to point 2."""
    lat1, lon1, lat2, lon2 = (np.radians(np.asarray(v, dtype=float)) for v in (lat1, lon1, lat2, lon2))
    dlon = lon2 - lon1
    x = np.sin(dlon) * np.cos(lat2)
    y = np.cos(lat1) * np.sin(lat2) - np.sin(lat1) * np.cos(lat2) * np.cos(dlon)
    return (np.degrees(np.arctan2(x, y)) + 360.0) % 360.0


def deg_to_cardinal(deg) -> str:
    """16-point compass label; '—' if the angle is missing."""
    if deg is None or (isinstance(deg, float) and math.isnan(deg)):
        return "—"
    return CARDINALS_16[int((float(deg) % 360) / 22.5 + 0.5) % 16]


def destination_point(lat: float, lon: float, bearing: float, distance_km: float) -> tuple[float, float]:
    """Point reached travelling `distance_km` from (lat, lon) along `bearing`."""
    d = distance_km / EARTH_RADIUS_KM
    b, p1, l1 = math.radians(bearing), math.radians(lat), math.radians(lon)
    p2 = math.asin(math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(b))
    l2 = l1 + math.atan2(math.sin(b) * math.sin(d) * math.cos(p1), math.cos(d) - math.sin(p1) * math.sin(p2))
    return math.degrees(p2), (math.degrees(l2) + 540) % 360 - 180


def circle_coords(lat: float, lon: float, radius_km: float, n: int = 120) -> list[list[float]]:
    """Closed ring of [lon, lat] vertices (for map polygons)."""
    pts = [destination_point(lat, lon, 360.0 * i / n, radius_km) for i in range(n + 1)]
    return [[lo, la] for la, lo in pts]


def km_to_nm(km):
    return km / 1.852
