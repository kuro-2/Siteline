"""KoboToolbox API v2: field surveyors' ground counts (and photos)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx


@dataclass(frozen=True)
class KoboCount:
    submission_id: str
    username: str | None
    category_slug: str
    count: int
    informal_count: int
    lat: float
    lng: float
    counted_at: datetime
    notes: str | None
    photos: list[dict[str, str]]  # [{"filename":…, "url":…}]


def parse_geopoint(v: Any) -> tuple[float, float] | None:
    if isinstance(v, str):
        parts = v.split()
        if len(parts) >= 2:
            return float(parts[0]), float(parts[1])
    if isinstance(v, list) and len(v) >= 2:
        return float(v[0]), float(v[1])
    return None


def _get(sub: dict[str, Any], key: str) -> Any:
    """Kobo prefixes fields with their group path (e.g. 'count/shops'); match by suffix."""
    if key in sub:
        return sub[key]
    for k, v in sub.items():
        if k.split("/")[-1] == key:
            return v
    return None


def parse_submission(sub: dict[str, Any]) -> KoboCount | None:
    loc = parse_geopoint(_get(sub, "location") or sub.get("_geolocation"))
    cat = _get(sub, "category")
    count = _get(sub, "shop_count")
    if loc is None or not cat or count in (None, ""):
        return None
    when_raw = _get(sub, "counted_on") or sub.get("_submission_time")
    try:
        when = datetime.fromisoformat(str(when_raw).replace("Z", "+00:00"))
    except ValueError:
        when = datetime.now(UTC)
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    photos = [
        {
            "filename": a.get("filename", ""),
            "url": a.get("download_url") or a.get("download_large_url", ""),
        }
        for a in sub.get("_attachments", []) or []
        if (a.get("mimetype") or "").startswith("image/")
    ]
    return KoboCount(
        submission_id=str(sub.get("_uuid") or sub.get("_id")),
        username=sub.get("_submitted_by"),
        category_slug=str(cat),
        count=max(0, int(count)),
        informal_count=max(0, int(_get(sub, "informal_count") or 0)),
        lat=loc[0],
        lng=loc[1],
        counted_at=when,
        notes=_get(sub, "notes"),
        photos=photos,
    )


class KoboClient:
    def __init__(self, base_url: str, token: str, http: httpx.Client | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.http = http or httpx.Client(timeout=60, headers={"Authorization": f"Token {token}"})

    def submissions(self, asset_uid: str, since: datetime | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"format": "json", "limit": 1000}
        if since:
            params["query"] = (
                '{"_submission_time": {"$gt": "' + since.strftime("%Y-%m-%dT%H:%M:%S") + '"}}'
            )
        url: str | None = f"{self.base_url}/api/v2/assets/{asset_uid}/data/"
        out: list[dict[str, Any]] = []
        while url:
            r = self.http.get(url, params=params if not out else None)
            r.raise_for_status()
            data = r.json()
            out.extend(data.get("results", []))
            url = data.get("next")
        return out

    def download(self, url: str) -> bytes:
        r = self.http.get(url, follow_redirects=True)
        r.raise_for_status()
        return r.content
