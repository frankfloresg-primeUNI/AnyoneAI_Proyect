"""Map latitude/longitude coordinates to NYC TLC taxi zones (LocationID).

Load the zones once at API startup and reuse the locator for every request:

    from src.features.zones import ZoneLocator, OutOfServiceAreaError

    locator = ZoneLocator("data/reference/taxi_zones.geojson")   # once, at startup
    match = locator.coords_to_zone(40.7580, -73.9855)            # per request
    match.location_id  # 230 (Times Sq/Theatre District)

Only depends on shapely, so the API image does not need geopandas.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import shapely
from shapely.geometry import Point, shape

# Rough bounding box of the TLC zones (with a small margin). Anything outside is rejected early.
NYC_LAT_RANGE = (40.45, 40.95)
NYC_LON_RANGE = (-74.30, -73.65)

# A point that falls in no polygon (a pier, a bridge, GPS noise) is assigned to the nearest
# zone only if that zone is closer than this. Farther away means outside the service area.
DEFAULT_MAX_SNAP_METERS = 200.0

# Local flat projection around NYC: degrees -> meters. Error is well below 1% at city scale,
# which is plenty for a 200 m snapping threshold, and avoids a pyproj dependency.
_REF_LAT = 40.7
_M_PER_DEG_LAT = 110_540.0
_M_PER_DEG_LON = 111_320.0 * math.cos(math.radians(_REF_LAT))


class InvalidCoordinatesError(ValueError):
    """The input is not a valid coordinate (wrong type, NaN, out of range, or swapped)."""


class OutOfServiceAreaError(ValueError):
    """The coordinate is valid but not inside (or near) any NYC taxi zone."""


@dataclass(frozen=True)
class ZoneMatch:
    location_id: int
    zone: str
    borough: str
    matched_by: str          # "inside" or "nearest"
    distance_m: float        # 0.0 when the point is inside the zone


def _to_meters(geom):
    return shapely.transform(geom, lambda xy: xy * [_M_PER_DEG_LON, _M_PER_DEG_LAT])


class ZoneLocator:
    def __init__(self, geojson_path: str | Path, max_snap_meters: float = DEFAULT_MAX_SNAP_METERS):
        with open(geojson_path, encoding="utf-8") as f:
            features = json.load(f)["features"]
        if len(features) != 263:
            raise ValueError(f"Expected 263 taxi zones, found {len(features)}. Wrong file?")

        self._props = [f["properties"] for f in features]
        # Geometries in a local metric plane, so distances come out in meters
        self._geoms = [_to_meters(shape(f["geometry"])) for f in features]
        shapely.prepare(self._geoms)
        self._tree = shapely.STRtree(self._geoms)
        self.max_snap_meters = max_snap_meters

    @staticmethod
    def _validate(lat, lon) -> tuple[float, float]:
        try:
            lat, lon = float(lat), float(lon)
        except (TypeError, ValueError):
            raise InvalidCoordinatesError(f"Coordinates must be numbers, got lat={lat!r}, lon={lon!r}")
        if math.isnan(lat) or math.isnan(lon) or math.isinf(lat) or math.isinf(lon):
            raise InvalidCoordinatesError("Coordinates must be finite numbers")
        # Most common bug: latitude and longitude swapped (NYC is lat ~40.7, lon ~-74.0)
        if NYC_LAT_RANGE[0] <= lon <= NYC_LAT_RANGE[1] and NYC_LON_RANGE[0] <= lat <= NYC_LON_RANGE[1]:
            raise InvalidCoordinatesError(
                f"lat={lat}, lon={lon} looks swapped: NYC is around lat 40.7, lon -74.0")
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise InvalidCoordinatesError(f"Coordinates out of range: lat={lat}, lon={lon}")
        return lat, lon

    def coords_to_zone(self, lat: float, lon: float) -> ZoneMatch:
        """Return the taxi zone for a (latitude, longitude) pair.

        Raises InvalidCoordinatesError for bad input and OutOfServiceAreaError when the point is
        not in NYC. In the API, map both to HTTP 422 with the error message.
        """
        lat, lon = self._validate(lat, lon)
        if not (NYC_LAT_RANGE[0] <= lat <= NYC_LAT_RANGE[1] and NYC_LON_RANGE[0] <= lon <= NYC_LON_RANGE[1]):
            raise OutOfServiceAreaError(f"({lat}, {lon}) is outside the NYC taxi service area")

        # Note the order: shapely points are (x=longitude, y=latitude)
        point = _to_meters(Point(lon, lat))

        # 1. Inside a polygon ("intersects" also catches points exactly on a border)
        hits = self._tree.query(point, predicate="intersects")
        if len(hits):
            # On a shared border two zones match: pick the lowest LocationID so results are stable
            idx = min(hits, key=lambda i: self._props[i]["LocationID"])
            return self._match(idx, "inside", 0.0)

        # 2. Not inside any zone: snap to the nearest one if it is close enough
        nearest = self._tree.query_nearest(point, max_distance=self.max_snap_meters, return_distance=True)
        indices, distances = nearest
        if len(indices):
            j = min(range(len(indices)), key=lambda k: (distances[k], self._props[indices[k]]["LocationID"]))
            return self._match(indices[j], "nearest", round(float(distances[j]), 1))

        raise OutOfServiceAreaError(
            f"({lat}, {lon}) is more than {self.max_snap_meters:.0f} m from any NYC taxi zone")

    def _match(self, idx, how, dist) -> ZoneMatch:
        p = self._props[idx]
        return ZoneMatch(int(p["LocationID"]), p["zone"], p["borough"], how, dist)


# Convenience function for scripts and notebooks. The API should create one ZoneLocator at startup.
_default_locator: ZoneLocator | None = None


def coords_to_zone(lat: float, lon: float,
                   geojson_path: str | Path = "data/reference/taxi_zones.geojson") -> int:
    """Return only the LocationID. Loads the zones on the first call and reuses them afterwards."""
    global _default_locator
    if _default_locator is None:
        _default_locator = ZoneLocator(geojson_path)
    return _default_locator.coords_to_zone(lat, lon).location_id
