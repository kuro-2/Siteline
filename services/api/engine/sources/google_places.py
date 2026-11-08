"""Google Places API (New). Paid beyond the free tier, so:

- never called from the browser; the key only lives in the API/engine env;
- every request goes through QuotaGuard.spend() first;
- field masks keep calls in the Pro SKU unless GOOGLE_RATINGS_ENABLED=true;
- Nearby Search returns at most 20 places and does not paginate, so a full circle is
  split into 4 smaller ones (up to MAX_DEPTH levels).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import httpx
from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry

from engine.geo.grid import EARTH_RADIUS_M
from engine.quota import QuotaGuard, pricing

NEARBY_URL = "https://places.googleapis.com/v1/places:searchNearby"
TEXT_URL = "https://places.googleapis.com/v1/places:searchText"
MAX_RESULTS = 20
MAX_DEPTH = 3
DEFAULT_RADIUS_M = 300.0


@dataclass(frozen=True)
class Circle:
    lat: float
    lng: float
    radius_m: float


@dataclass(frozen=True)
class GooglePlace:
    place_id: str
    name: str | None
    types: list[str]
    lat: float
    lng: float
    business_status: str | None
    rating: float | None
    rating_count: int | None


def field_mask(ratings: bool, text_search: bool = False) -> str:
    g = pricing()["google"]  # type: ignore[index]
    fields: list[str] = list(g["pro_fields"])
    if ratings:
        fields += list(g["enterprise_fields"])
    if text_search:
        fields.append("nextPageToken")
    return ",".join(fields)


def sku_for(kind: str, ratings: bool) -> str:
    tier = "enterprise" if ratings else "pro"
    return f"{'nearby' if kind == 'nearby' else 'text'}_search_{tier}"


def _offset(lat: float, lng: float, dx_m: float, dy_m: float) -> tuple[float, float]:
    dlat = math.degrees(dy_m / EARTH_RADIUS_M)
    dlng = math.degrees(dx_m / (EARTH_RADIUS_M * math.cos(math.radians(lat))))
    return lat + dlat, lng + dlng


def plan_circles(region: BaseGeometry, radius_m: float = DEFAULT_RADIUS_M) -> list[Circle]:
    """Hexagonal packing of circles that together cover `region` (lng/lat geometry)."""
    minx, miny, maxx, maxy = region.bounds
    lat0 = (miny + maxy) / 2
    step_x = radius_m * math.sqrt(3)
    step_y = radius_m * 1.5
    deg_per_m_lat = math.degrees(1 / EARTH_RADIUS_M)
    deg_per_m_lng = deg_per_m_lat / math.cos(math.radians(lat0))
    circles: list[Circle] = []
    row = 0
    y = miny - radius_m * deg_per_m_lat
    while y <= maxy + radius_m * deg_per_m_lat:
        x = minx - radius_m * deg_per_m_lng + (step_x / 2 * deg_per_m_lng if row % 2 else 0)
        while x <= maxx + radius_m * deg_per_m_lng:
            disc = Point(x, y).buffer(radius_m * deg_per_m_lng)
            if disc.intersects(region):
                circles.append(Circle(round(y, 6), round(x, 6), radius_m))
            x += step_x * deg_per_m_lng
        y += step_y * deg_per_m_lat
        row += 1
    return circles


def split_circle(c: Circle) -> list[Circle]:
    """Four circles (radius × 0.75) whose union covers the parent circle."""
    d = c.radius_m / 2
    r = c.radius_m * 0.75
    out = []
    for dx, dy in ((-d, -d), (d, -d), (-d, d), (d, d)):
        lat, lng = _offset(c.lat, c.lng, dx, dy)
        out.append(Circle(round(lat, 6), round(lng, 6), round(r, 1)))
    return out


def parse_place(p: dict[str, Any]) -> GooglePlace:
    loc = p.get("location") or {}
    name = (p.get("displayName") or {}).get("text")
    return GooglePlace(
        place_id=p["id"],
        name=name,
        types=list(p.get("types") or []),
        lat=float(loc.get("latitude", 0.0)),
        lng=float(loc.get("longitude", 0.0)),
        business_status=p.get("businessStatus"),
        rating=p.get("rating"),
        rating_count=p.get("userRatingCount"),
    )


class GooglePlacesClient:
    def __init__(
        self, api_key: str, guard: QuotaGuard, ratings: bool, http: httpx.Client | None = None
    ) -> None:
        if not api_key:
            raise ValueError("GOOGLE_PLACES_API_KEY is empty")
        self.api_key = api_key
        self.guard = guard
        self.ratings = ratings
        self.http = http or httpx.Client(timeout=30)

    def _post(self, url: str, body: dict[str, Any], sku: str, text: bool) -> dict[str, Any]:
        self.guard.spend(sku)  # records + enforces the cap BEFORE the request
        r = self.http.post(
            url,
            json=body,
            headers={
                "X-Goog-Api-Key": self.api_key,
                "X-Goog-FieldMask": field_mask(self.ratings, text_search=text),
            },
        )
        r.raise_for_status()
        data: dict[str, Any] = r.json()
        return data

    def nearby(self, c: Circle, types: list[str]) -> list[GooglePlace]:
        body = {
            "includedTypes": types,
            "maxResultCount": MAX_RESULTS,
            "locationRestriction": {
                "circle": {"center": {"latitude": c.lat, "longitude": c.lng}, "radius": c.radius_m}
            },
        }
        data = self._post(NEARBY_URL, body, sku_for("nearby", self.ratings), text=False)
        return [parse_place(p) for p in data.get("places", [])]

    def nearby_recursive(self, c: Circle, types: list[str], depth: int = 0) -> list[GooglePlace]:
        found = self.nearby(c, types)
        if len(found) >= MAX_RESULTS and depth < MAX_DEPTH:
            for sub in split_circle(c):
                found.extend(self.nearby_recursive(sub, types, depth + 1))
        return found

    def text(self, query: str, c: Circle, max_pages: int = 3) -> list[GooglePlace]:
        out: list[GooglePlace] = []
        token: str | None = None
        for _ in range(max_pages):
            body: dict[str, Any] = {
                "textQuery": query,
                "pageSize": MAX_RESULTS,
                "locationBias": {
                    "circle": {
                        "center": {"latitude": c.lat, "longitude": c.lng},
                        "radius": c.radius_m,
                    }
                },
            }
            if token:
                body["pageToken"] = token
            data = self._post(TEXT_URL, body, sku_for("text", self.ratings), text=True)
            out.extend(parse_place(p) for p in data.get("places", []))
            token = data.get("nextPageToken")
            if not token:
                break
        return out


def dedupe_by_id(places: list[GooglePlace]) -> list[GooglePlace]:
    seen: dict[str, GooglePlace] = {}
    for p in places:
        seen.setdefault(p.place_id, p)
    return list(seen.values())
