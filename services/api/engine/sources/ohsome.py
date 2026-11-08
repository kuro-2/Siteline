"""ohsome API (HeiGIT): how many OSM features of a kind existed in each cell on past dates.

The public instance allows aggregate endpoints (counts) but not raw extraction, so the
backtest works on per-cell counts. Responses are cached on disk.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence
from pathlib import Path

import h3
import httpx

from engine.sources.categories import COMMERCIAL_AMENITIES, CategoryDef

ALL_BUSINESSES = (
    "shop=* or office=* or craft=* or healthcare=* or amenity in ("
    + ", ".join(sorted(COMMERCIAL_AMENITIES))
    + ")"
)


def category_filter(cat: CategoryDef) -> str:
    """OSM tag rules → ohsome filter, e.g. (amenity=pharmacy or shop=chemist)."""
    rules = []
    for rule in cat.osm_tags:
        parts = [f"{k}={v}" for k, v in rule.items()]
        rules.append(parts[0] if len(parts) == 1 else "(" + " and ".join(parts) + ")")
    return "(" + " or ".join(rules) + ")"


def cells_geojson(cells: Iterable[str]) -> str:
    feats = []
    for c in sorted(cells):
        ring = [[lng, lat] for lat, lng in h3.cell_to_boundary(c)]
        ring.append(ring[0])
        feats.append(
            {
                "type": "Feature",
                "id": c,
                "properties": {"id": c},
                "geometry": {"type": "Polygon", "coordinates": [ring]},
            }
        )
    return json.dumps({"type": "FeatureCollection", "features": feats})


def parse_counts(payload: dict[str, object]) -> dict[str, dict[str, int]]:
    """{cell: {"YYYY-MM-DD": count}}"""
    out: dict[str, dict[str, int]] = {}
    for g in payload.get("groupByResult", []):  # type: ignore[union-attr]
        cell = str(g["groupByObject"])  # type: ignore[index]
        out[cell] = {
            str(r["timestamp"])[:10]: round(float(r["value"]))  # type: ignore[index]
            for r in g["result"]  # type: ignore[index]
        }
    return out


class OhsomeClient:
    def __init__(
        self, base_url: str, user_agent: str, cache_dir: Path, http: httpx.Client | None = None
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.cache_dir = cache_dir
        self.http = http or httpx.Client(timeout=300, headers={"User-Agent": user_agent})

    def counts_by_cell(
        self, cells: Iterable[str], osm_filter: str, times: Sequence[str]
    ) -> dict[str, dict[str, int]]:
        body = {"bpolys": cells_geojson(cells), "time": ",".join(times), "filter": osm_filter}
        key = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:16]
        path = self.cache_dir / f"counts-{key}.json"
        if path.exists():
            return parse_counts(json.loads(path.read_text(encoding="utf-8")))
        r = self.http.post(f"{self.base_url}/elements/count/groupBy/boundary", data=body)
        r.raise_for_status()
        payload = r.json()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
        return parse_counts(payload)
