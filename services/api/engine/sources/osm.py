"""OpenStreetMap via the Overpass API. Free; be polite.

- One query per area (all business-like POIs inside the grid's outer boundary).
- Responses cached in data/cache/overpass/<hash>.json; reused for 6 days.
- User-Agent carries CONTACT_EMAIL. Backs off on 429/504.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from shapely.geometry import MultiPolygon, Polygon

from engine.log import get_logger

log = get_logger("engine.osm")
CACHE_MAX_AGE_S = 6 * 24 * 3600


@dataclass(frozen=True)
class OsmPlace:
    source_id: str  # "node/123" | "way/456"
    name: str | None
    tags: dict[str, str]
    lat: float
    lng: float


def build_query(region: MultiPolygon | Polygon, timeout_s: int = 90) -> str:
    """One compact bounding-box query; results are clipped to the grid in code."""
    minx, miny, maxx, maxy = region.bounds
    bbox = f"{miny:.5f},{minx:.5f},{maxy:.5f},{maxx:.5f}"
    keys = ("shop", "office", "craft", "healthcare", "amenity")
    body = "\n".join(f'  nwr["{key}"]({bbox});' for key in keys)
    return f"[out:json][timeout:{timeout_s}];\n(\n{body}\n);\nout center tags;"


def parse_elements(payload: dict[str, Any]) -> list[OsmPlace]:
    out: list[OsmPlace] = []
    for el in payload.get("elements", []):
        tags = el.get("tags") or {}
        if el["type"] == "node":
            lat, lng = el.get("lat"), el.get("lon")
        else:
            c = el.get("center") or {}
            lat, lng = c.get("lat"), c.get("lon")
        if lat is None or lng is None:
            continue
        out.append(
            OsmPlace(
                source_id=f"{el['type']}/{el['id']}",
                name=tags.get("name") or tags.get("name:en"),
                tags=tags,
                lat=float(lat),
                lng=float(lng),
            )
        )
    return out


class OverpassClient:
    def __init__(
        self,
        url: str,
        user_agent: str,
        cache_dir: Path,
        http: httpx.Client | None = None,
        max_retries: int = 4,
        sleep: Any = time.sleep,
    ) -> None:
        self.url = url
        self.cache_dir = cache_dir
        self.http = http or httpx.Client(timeout=180, headers={"User-Agent": user_agent})
        self.max_retries = max_retries
        self.sleep = sleep

    def _cache_path(self, query: str) -> Path:
        h = hashlib.sha256(query.encode()).hexdigest()[:16]
        return self.cache_dir / f"{h}.json"

    def cached(self, query: str) -> dict[str, Any] | None:
        p = self._cache_path(query)
        if p.exists() and time.time() - p.stat().st_mtime < CACHE_MAX_AGE_S:
            data: dict[str, Any] = json.loads(p.read_text(encoding="utf-8"))
            return data
        return None

    def fetch(self, query: str, use_cache: bool = True) -> tuple[dict[str, Any], bool]:
        """Return (payload, from_cache)."""
        if use_cache and (hit := self.cached(query)) is not None:
            return hit, True
        delay = 15.0
        for attempt in range(self.max_retries + 1):
            r = self.http.post(self.url, data={"data": query})
            if r.status_code in (429, 502, 503, 504) and attempt < self.max_retries:
                log.warning("overpass.backoff", status=r.status_code, wait_s=delay)
                self.sleep(delay)
                delay *= 2
                continue
            r.raise_for_status()
            payload: dict[str, Any] = r.json()
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            self._cache_path(query).write_text(json.dumps(payload), encoding="utf-8")
            return payload, False
        raise RuntimeError("Overpass kept refusing; try again later.")  # pragma: no cover
