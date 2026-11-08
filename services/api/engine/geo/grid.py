"""H3 grid helpers. Pure functions over shapely geometries and h3 strings."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import h3
from shapely.geometry import MultiPolygon, Point, Polygon, mapping, shape
from shapely.geometry.base import BaseGeometry

EARTH_RADIUS_M = 6_371_008.8


@dataclass(frozen=True)
class GridCell:
    h3: str
    polygon: Polygon  # lng/lat
    centroid: Point
    in_area: bool


def load_boundary(path: Path) -> MultiPolygon:
    """Read a GeoJSON file (FeatureCollection, Feature or bare geometry) into a MultiPolygon."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return boundary_from_geojson(data)


def boundary_from_geojson(data: dict[str, Any]) -> MultiPolygon:
    geoms: list[BaseGeometry] = []
    if data.get("type") == "FeatureCollection":
        geoms = [shape(f["geometry"]) for f in data["features"] if f.get("geometry")]
    elif data.get("type") == "Feature":
        geoms = [shape(data["geometry"])]
    else:
        geoms = [shape(data)]
    polys: list[Polygon] = []
    for g in geoms:
        if isinstance(g, Polygon):
            polys.append(g)
        elif isinstance(g, MultiPolygon):
            polys.extend(g.geoms)
    if not polys:
        raise ValueError("The boundary file has no polygons. Draw an area (not a line or point).")
    mp = MultiPolygon(polys)
    if not mp.is_valid:
        mp_fixed = mp.buffer(0)
        mp = mp_fixed if isinstance(mp_fixed, MultiPolygon) else MultiPolygon([mp_fixed])
    return mp


def area_km2(geom: BaseGeometry) -> float:
    """Approximate area using a local equirectangular projection (fine at city scale)."""
    lat0 = math.radians(geom.centroid.y)
    kx = math.cos(lat0) * math.pi / 180 * EARTH_RADIUS_M
    ky = math.pi / 180 * EARTH_RADIUS_M
    from shapely.affinity import scale

    return float(scale(geom, xfact=kx, yfact=ky, origin=(0, 0)).area) / 1e6


def cell_polygon(cell: str) -> Polygon:
    # h3 returns (lat, lng); shapely wants (lng, lat)
    ring = [(lng, lat) for lat, lng in h3.cell_to_boundary(cell)]
    return Polygon(ring)


def cell_centroid(cell: str) -> Point:
    lat, lng = h3.cell_to_latlng(cell)
    return Point(lng, lat)


def build_grid(boundary: MultiPolygon, resolution: int, buffer_k: int) -> list[GridCell]:
    """Cells whose centroid is inside the boundary, plus `buffer_k` rings around them."""
    inside: set[str] = set()
    for poly in boundary.geoms:
        shell = [(lat, lng) for lng, lat in poly.exterior.coords]
        holes = [[(lat, lng) for lng, lat in r.coords] for r in poly.interiors]
        inside.update(h3.polygon_to_cells(h3.LatLngPoly(shell, *holes), resolution))
    # polygon_to_cells already uses centroid containment; keep an explicit check anyway
    inside = {c for c in inside if boundary.contains(cell_centroid(c))}
    if not inside:
        raise ValueError("The boundary is smaller than one H3 cell (~0.1 km²). Draw a larger area.")
    ring: set[str] = set()
    for c in inside:
        ring.update(h3.grid_disk(c, buffer_k))
    ring -= inside
    cells = [GridCell(c, cell_polygon(c), cell_centroid(c), True) for c in sorted(inside)]
    cells += [GridCell(c, cell_polygon(c), cell_centroid(c), False) for c in sorted(ring)]
    return cells


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def cell_distance_m(a: str, b: str) -> float:
    la, ga = h3.cell_to_latlng(a)
    lb, gb = h3.cell_to_latlng(b)
    return haversine_m(la, ga, lb, gb)


def catchment(cell: str, k: int) -> list[str]:
    return sorted(h3.grid_disk(cell, k))


def to_wkt(geom: BaseGeometry) -> str:
    return geom.wkt


def to_geojson(geom: BaseGeometry) -> dict[str, Any]:
    return dict(mapping(geom))


DIRECTIONS = [
    "north",
    "north-east",
    "east",
    "south-east",
    "south",
    "south-west",
    "west",
    "north-west",
]


def direction(from_cell: str, to_cell: str) -> str:
    la, ga = h3.cell_to_latlng(from_cell)
    lb, gb = h3.cell_to_latlng(to_cell)
    y = math.sin(math.radians(gb - ga)) * math.cos(math.radians(lb))
    x = math.cos(math.radians(la)) * math.sin(math.radians(lb)) - math.sin(
        math.radians(la)
    ) * math.cos(math.radians(lb)) * math.cos(math.radians(gb - ga))
    bearing = (math.degrees(math.atan2(y, x)) + 360) % 360
    return DIRECTIONS[round(bearing / 45) % 8]
