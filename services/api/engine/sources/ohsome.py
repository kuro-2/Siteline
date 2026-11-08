"""ohsome API (HeiGIT): what OSM looked like on a past date. Free; cached on disk."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import httpx
from shapely.geometry import mapping
from shapely.geometry.base import BaseGeometry

from engine.sources.categories import COMMERCIAL_AMENITIES
from engine.sources.osm import OsmPlace

FILTER = (
    "(shop=* or office=* or craft=* or healthcare=* or amenity in ("
    + ", ".join(sorted(COMMERCIAL_AMENITIES))
    + ")) and (geometry:point or geometry:polygon)"
)


def parse_features(payload: dict[str, Any]) -> list[OsmPlace]:
    out: list[OsmPlace] = []
    for f in payload.get("features", []):
        props = dict(f.get("properties") or {})
        geom = f.get("geometry") or {}
        if geom.get("type") != "Point":
            continue
        lng, lat = geom["coordinates"][:2]
        osm_id = str(props.pop("@osmId", ""))
        tags = {k: str(v) for k, v in props.items() if not k.startswith("@")}
        out.append(OsmPlace(osm_id, tags.get("name"), tags, float(lat), float(lng)))
    return out


class OhsomeClient:
    def __init__(
        self, base_url: str, user_agent: str, cache_dir: Path, http: httpx.Client | None = None
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.cache_dir = cache_dir
        self.http = http or httpx.Client(timeout=300, headers={"User-Agent": user_agent})

    def centroids(self, region: BaseGeometry, when: str) -> list[OsmPlace]:
        bpolys = json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {"type": "Feature", "properties": {"id": "area"}, "geometry": mapping(region)}
                ],
            }
        )
        body = {"bpolys": bpolys, "time": when, "filter": FILTER, "properties": "tags"}
        key = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:16]
        path = self.cache_dir / f"{key}.json"
        if path.exists():
            return parse_features(json.loads(path.read_text(encoding="utf-8")))
        r = self.http.post(f"{self.base_url}/elements/centroid", data=body)
        r.raise_for_status()
        payload = r.json()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
        return parse_features(payload)
