"""Public endpoints (no login)."""

from __future__ import annotations

import json
from typing import Any

import h3
from fastapi import APIRouter, Query, Request, Response
from pydantic import BaseModel, Field

from app.errors import ApiError, not_found
from app.limits import limiter
from app.schemas.public import (
    AreaDetail,
    AreaSummary,
    Category,
    CellReport,
    CheckResponse,
    ErrorResponse,
    GeocodeResult,
    Health,
    MapResponse,
    TopPick,
)
from app.services.report import build_report, category_by_slug, latest_run, neighbour_advice
from engine.db import connect
from engine.scoring.config import get_config

router = APIRouter(
    tags=["public"], responses={404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}}
)

FRESHNESS_JOBS = {
    "OpenStreetMap": "ingest.osm",
    "WorldPop": "ingest.worldpop",
    "Google Maps": "ingest.google",
    "Ground counts": "ingest.kobo",
    "Scores": "score.run",
}


@router.get("/health", response_model=Health)
def health() -> dict[str, Any]:
    try:
        with connect() as conn:
            conn.execute("select 1")
        db = "ok"
    except Exception as e:  # the health check must never raise
        db = f"unavailable: {type(e).__name__}"
    return {"status": "ok", "db": db}


@router.get("/areas", response_model=list[AreaSummary])
def areas() -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """select id, slug, name, city,
                      extensions.st_xmin(boundary) as w, extensions.st_ymin(boundary) as s,
                      extensions.st_xmax(boundary) as e, extensions.st_ymax(boundary) as n
               from areas where is_published order by name"""
        ).fetchall()
    return [
        {
            "id": str(r["id"]),
            "slug": r["slug"],
            "name": r["name"],
            "city": r["city"],
            "bbox": [r["w"], r["s"], r["e"], r["n"]],
        }
        for r in rows
    ]


@router.get("/areas/{slug}", response_model=AreaDetail)
def area(slug: str) -> dict[str, Any]:
    with connect() as conn:
        r = conn.execute(
            """select id, slug, name, city, extensions.st_asgeojson(boundary) as gj,
                      extensions.st_xmin(boundary) as w, extensions.st_ymin(boundary) as s,
                      extensions.st_xmax(boundary) as e, extensions.st_ymax(boundary) as n,
                      extensions.st_y(extensions.st_centroid(boundary)) as clat,
                      extensions.st_x(extensions.st_centroid(boundary)) as clng
               from areas where slug = %s and is_published""",
            (slug,),
        ).fetchone()
        if not r:
            raise not_found("area", "Pick an area from the list.")
        fresh = []
        for label, job in FRESHNESS_JOBS.items():
            j = conn.execute(
                """select finished_at, counts from job_runs where job = %s and status = 'succeeded'
                   order by finished_at desc limit 1""",
                (job,),
            ).fetchone()
            fresh.append(
                {"source": label, "last_updated": j["finished_at"].isoformat() if j else None}
            )
        cells = conn.execute(
            "select count(*) as n from h3_cells where area_id = %s and in_area", (r["id"],)
        ).fetchone()
        survey = conn.execute(
            """select slug from surveys where area_id = %s and is_active
               and (closes_at is null or closes_at > now()) order by version desc limit 1""",
            (r["id"],),
        ).fetchone()
    return {
        "id": str(r["id"]),
        "slug": r["slug"],
        "name": r["name"],
        "city": r["city"],
        "boundary": json.loads(r["gj"]),
        "bbox": [r["w"], r["s"], r["e"], r["n"]],
        "centre": [r["clng"], r["clat"]],
        "cells": cells["n"] if cells else 0,
        "survey_slug": survey["slug"] if survey else None,
        "freshness": fresh,
    }


@router.get("/categories", response_model=list[Category])
def categories() -> list[dict[str, Any]]:
    cfg = get_config()
    with connect() as conn:
        rows = conn.execute(
            "select slug, name, description, catchment_k from categories where active order by sort_order"
        ).fetchall()
    return [
        {
            **r,
            "walk_minutes": cfg.categories[r["slug"]].travel_minutes
            if r["slug"] in cfg.categories
            else None,
        }
        for r in rows
    ]


def _area_id(conn: Any, slug: str) -> str:
    r = conn.execute("select id from areas where slug = %s and is_published", (slug,)).fetchone()
    if not r:
        raise not_found("area", "Pick an area from the list.")
    return str(r["id"])


@router.get("/areas/{slug}/map", response_model=MapResponse)
def area_map(slug: str, response: Response, category: str = Query(...)) -> dict[str, Any]:
    with connect() as conn:
        area_id = _area_id(conn, slug)
        cat = category_by_slug(conn, category)
        run = latest_run(conn, area_id)
        if not run:
            return {"run_at": None, "cells": []}
        rows = conn.execute(
            """select s.h3, s.score, s.confidence::text as confidence,
                      exists (select 1 from recommendations r where r.h3 = s.h3
                              and r.category_id = s.category_id and r.status = 'published') as rec
               from scores s join h3_cells c on c.h3 = s.h3
               where s.run_id = %s and s.category_id = %s and c.in_area""",
            (run["id"], cat["id"]),
        ).fetchall()
    response.headers["Cache-Control"] = "public, max-age=300, s-maxage=3600"
    return {
        "run_at": run["created_at"].isoformat(),
        # compact rows for deck.gl: [h3, score|null, confidence, is_recommended]
        "cells": [
            [
                r["h3"],
                None if r["confidence"] == "not_enough_data" else round(float(r["score"])),
                r["confidence"],
                r["rec"],
            ]
            for r in rows
        ],
    }


@router.get("/areas/{slug}/top", response_model=list[TopPick])
def area_top(
    slug: str, category: str | None = None, limit: int = Query(3, ge=1, le=20)
) -> list[dict[str, Any]]:
    with connect() as conn:
        area_id = _area_id(conn, slug)
        params: list[Any] = [area_id]
        where = "pr.area_id = %s"
        if category:
            cat = category_by_slug(conn, category)
            where += " and pr.category_id = %s"
            params.append(cat["id"])
        params.append(limit)
        rows = conn.execute(
            f"""select pr.id, pr.h3, round(pr.score) as score, pr.confidence::text as confidence,
                       pr.published_at, pr.reviewed_by_name, c.slug as category, c.name as category_name
                from public_recommendations pr join categories c on c.id = pr.category_id
                where {where} order by pr.score desc limit %s""",
            params,
        ).fetchall()
    return [
        {
            **r,
            "id": str(r["id"]),
            "score": int(r["score"]),
            "published_at": r["published_at"].isoformat() if r["published_at"] else None,
        }
        for r in rows
    ]


@router.get("/cells/{cell}/report", response_model=CellReport)
def cell_report(cell: str, category: str = Query(...)) -> dict[str, Any]:
    with connect() as conn:
        return build_report(conn, cell, category)


class CheckBody(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    category: str


@router.post("/check", response_model=CheckResponse)
@limiter.limit("30/minute")
def check(request: Request, body: CheckBody) -> dict[str, Any]:
    _ = request
    cfg = get_config()
    cell = h3.latlng_to_cell(body.lat, body.lng, cfg.grid.resolution)
    with connect() as conn:
        found = conn.execute(
            """select a.name, c.in_area from h3_cells c join areas a on a.id = c.area_id
               where c.h3 = %s and a.is_published""",
            (cell,),
        ).fetchone()
        if not found or not found["in_area"]:
            names = [
                r["name"]
                for r in conn.execute(
                    "select name from areas where is_published order by name"
                ).fetchall()
            ]
            area_txt = names[0] if len(names) == 1 else "one of our areas"
            raise ApiError(
                422,
                "outside_area",
                f"That pin is outside {area_txt}. Move it inside the outlined area, "
                "or pick another area.",
            )
        report = build_report(conn, cell, body.category)
    return {"report": report, "advice": neighbour_advice(report)}


_geocode_cache: dict[str, list[dict[str, Any]]] = {}
_last_geocode = [0.0]


@router.get("/areas/{slug}/geocode", response_model=list[GeocodeResult])
@limiter.limit("20/minute")
def geocode(
    request: Request, slug: str, q: str = Query(min_length=2, max_length=120)
) -> list[dict[str, Any]]:
    """Street / landmark search inside one area (OpenStreetMap Nominatim, cached,
    at most one upstream request per second as its usage policy asks)."""
    import time

    import httpx

    from engine.settings import get_settings

    _ = request
    key = f"{slug}:{q.strip().lower()}"
    if key in _geocode_cache:
        return _geocode_cache[key]
    with connect() as conn:
        a = conn.execute(
            """select extensions.st_xmin(boundary) as w, extensions.st_ymin(boundary) as s,
                      extensions.st_xmax(boundary) as e, extensions.st_ymax(boundary) as n
               from areas where slug = %s and is_published""",
            (slug,),
        ).fetchone()
    if not a:
        raise not_found("area")
    wait = 1.0 - (time.monotonic() - _last_geocode[0])
    if wait > 0:
        time.sleep(wait)
    _last_geocode[0] = time.monotonic()
    s = get_settings()
    pad = 0.01
    try:
        r = httpx.get(
            "https://nominatim.openstreetmap.org/search",
            params={
                "q": f"{q}, Guwahati",
                "format": "jsonv2",
                "limit": 6,
                "bounded": 1,
                "viewbox": f"{a['w'] - pad},{a['n'] + pad},{a['e'] + pad},{a['s'] - pad}",
            },
            headers={"User-Agent": s.user_agent},
            timeout=10,
        )
        r.raise_for_status()
    except httpx.HTTPError as e:
        raise ApiError(
            503,
            "search_unavailable",
            "Street search isn't answering right now.",
            "Drop a pin on the map instead.",
        ) from e
    out = [
        {
            "name": x.get("display_name", "").split(",")[0]
            + ", "
            + ", ".join(x.get("display_name", "").split(",")[1:3]).strip(),
            "lat": float(x["lat"]),
            "lng": float(x["lon"]),
        }
        for x in r.json()
    ]
    _geocode_cache[key] = out
    return out
