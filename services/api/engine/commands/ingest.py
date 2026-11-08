"""Ingestion commands: OSM, WorldPop, Google, Google expiry, dedupe."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import h3
from shapely.ops import unary_union

from engine.db import connect
from engine.geo.grid import cell_polygon
from engine.jobs import job_run
from engine.log import get_logger
from engine.quota import DbUsageStore, QuotaGuard, estimate_cost_usd, pricing
from engine.repo import Conn, get_area, grid_cells, load_categories
from engine.scoring.config import get_config
from engine.settings import REPO_ROOT, get_settings
from engine.sources import google_places as gp
from engine.sources.categories import is_business, match_google, match_osm, raw_category
from engine.sources.dedupe import PlaceRef, find_merges
from engine.sources.osm import OverpassClient, build_query, parse_elements
from engine.sources.worldpop import population_by_cell

log = get_logger("engine.ingest")
CACHE_DIR = REPO_ROOT / "data" / "cache"


def _upsert_place(
    conn: Conn,
    *,
    source: str,
    source_id: str,
    name: str | None,
    category_id: str | None,
    raw: str | None,
    lat: float,
    lng: float,
    cell: str | None,
    status: str | None,
    rating: float | None = None,
    rating_count: int | None = None,
) -> None:
    conn.execute(
        """insert into places (source, source_id, name, category_id, raw_category, geom, h3,
                               business_status, rating, rating_count, content_expired)
           values (%s,%s,%s,%s,%s, extensions.st_setsrid(extensions.st_makepoint(%s,%s),4326),
                   %s,%s,%s,%s,false)
           on conflict (source, source_id) do update set
             name = excluded.name, category_id = excluded.category_id,
             raw_category = excluded.raw_category, geom = excluded.geom, h3 = excluded.h3,
             business_status = excluded.business_status, rating = excluded.rating,
             rating_count = excluded.rating_count, last_seen_at = now(), fetched_at = now(),
             content_expired = false""",
        (source, source_id, name, category_id, raw, lng, lat, cell, status, rating, rating_count),
    )


def _snapshot(conn: Conn, source: str) -> int:
    cur = conn.execute(
        """insert into place_snapshots (snapshot_on, place_id, category_id, h3, business_status)
           select current_date, id, category_id, h3, business_status from places
           where source = %s and last_seen_at::date = current_date
           on conflict do nothing""",
        (source,),
    )
    return cur.rowcount


# ------------------------------------------------------------------------------ OSM
def ingest_osm(area_slug: str, dry_run: bool, use_cache: bool = True) -> dict[str, Any]:
    s = get_settings()
    cfg = get_config()
    with connect() as conn:
        area = get_area(conn, area_slug)
        cats = load_categories(conn)
        cells = {c["h3"] for c in grid_cells(conn, area.id)}
    if not cells:
        raise RuntimeError(
            f"No grid for '{area_slug}'. Run: uv run engine geo build-grid --area {area_slug}"
        )
    region = unary_union([cell_polygon(c) for c in cells])
    query = build_query(region)
    client = OverpassClient(s.overpass_url, s.user_agent, CACHE_DIR / "overpass")

    with job_run("ingest.osm", {"area": area_slug}, dry_run=dry_run) as run:
        if dry_run:
            cached = client.cached(query) is not None
            run.set("would_call_overpass", 0 if cached else 1)
            return {"calls": 0 if cached else 1, "cost_usd": 0, "cached": cached}
        if not s.contact_email:
            raise RuntimeError(
                "CONTACT_EMAIL is not set. OpenStreetMap's Overpass service asks every client "
                "to identify itself; add CONTACT_EMAIL to .env."
            )
        payload, from_cache = client.fetch(query, use_cache=use_cache)
        run.set("from_cache", from_cache)
        places = parse_elements(payload)
        by_cat: Counter[str] = Counter()
        unmapped: Counter[str] = Counter()
        with connect() as conn:
            for p in places:
                if not is_business(p.tags):
                    continue
                cat = match_osm(p.tags, cats)
                raw = raw_category(p.tags)
                cell = h3.latlng_to_cell(p.lat, p.lng, cfg.grid.resolution)
                if cell not in cells:
                    continue
                if cat:
                    by_cat[cat.slug] += 1
                elif raw:
                    unmapped[raw] += 1
                _upsert_place(
                    conn,
                    source="osm",
                    source_id=p.source_id,
                    name=p.name,
                    category_id=cat.id if cat else None,
                    raw=raw,
                    lat=p.lat,
                    lng=p.lng,
                    cell=cell,
                    status=None,
                )
                run.count("places")
            run.set("snapshot_rows", _snapshot(conn, "osm"))
        run.set("by_category", dict(by_cat))
        run.set("unmapped", dict(unmapped.most_common(40)))
        return dict(run.counts)


# ------------------------------------------------------------------------------ WorldPop
def ingest_worldpop(area_slug: str, dry_run: bool, raster: str | None = None) -> dict[str, Any]:
    s = get_settings()
    cfg = get_config()
    path_str = raster or s.worldpop_raster_path
    if not path_str:
        raise RuntimeError(
            "WORLDPOP_RASTER_PATH is not set. Download the India constrained 100 m GeoTIFF from "
            "worldpop.org and point WORLDPOP_RASTER_PATH at the .tif file."
        )
    path = s.repo_path(path_str)
    if path.is_dir():
        tifs = sorted(path.glob("*.tif"))
        if not tifs:
            raise RuntimeError(f"No .tif file in {path}.")
        path = tifs[-1]
    if not path.exists():
        raise RuntimeError(f"WorldPop raster not found at {path}.")
    with connect() as conn:
        area = get_area(conn, area_slug)
        cells = {c["h3"] for c in grid_cells(conn, area.id)}
    with job_run("ingest.worldpop", {"area": area_slug, "file": path.name}, dry_run=dry_run) as run:
        pops, pixels = population_by_cell(path, cells, cfg.grid.resolution)
        run.set("cells", len(pops))
        run.set("pixels", pixels)
        run.set("total_population", round(sum(pops.values())))
        if dry_run:
            return dict(run.counts)
        with connect() as conn, conn.cursor() as cur:
            cur.executemany(
                "update h3_cells set population = %s, population_source_year = %s where h3 = %s",
                [(v, s.worldpop_year, c) for c, v in pops.items()],
            )
        return dict(run.counts)


# ------------------------------------------------------------------------------ Google
def google_plan(area_slug: str) -> dict[str, Any]:
    s = get_settings()
    with connect() as conn:
        area = get_area(conn, area_slug)
        cats = load_categories(conn)
    # The boundary plus ~600 m, so competitors just outside the edge are counted.
    region = area.boundary.buffer(0.0055)
    circles = gp.plan_circles(region)
    nearby_cats = [c for c in cats if c.google_types]
    text_cats = [c for c in cats if not c.google_types and c.google_text_query]
    nearby_calls = len(circles) * len(nearby_cats)
    # Text search: one search per ~1.5 km tile, up to 3 pages each
    text_tiles = gp.plan_circles(region, radius_m=1500)
    text_calls = len(text_tiles) * len(text_cats) * 3
    plan = {
        "circles": len(circles),
        "nearby_categories": [c.slug for c in nearby_cats],
        "text_categories": [c.slug for c in text_cats],
        "planned_nearby_calls": nearby_calls,
        "planned_text_calls_max": text_calls,
        # splits happen only where a circle returns 20 results; budget 50% extra
        "nearby_calls_with_splits_estimate": round(nearby_calls * 1.5),
        "ratings_enabled": s.google_ratings_enabled,
        "field_mask": gp.field_mask(s.google_ratings_enabled),
    }
    return {"plan": plan, "circles": circles, "text_tiles": text_tiles, "cats": cats, "area": area}


def ingest_google(area_slug: str, dry_run: bool) -> dict[str, Any]:
    s = get_settings()
    cfg = get_config()
    p = google_plan(area_slug)
    plan = p["plan"]
    ratings = s.google_ratings_enabled
    nearby_sku = gp.sku_for("nearby", ratings)
    text_sku = gp.sku_for("text", ratings)
    store = DbUsageStore()
    from engine.quota import month_start

    used_nearby = store.get("google", nearby_sku, month_start())
    used_text = store.get("google", text_sku, month_start())
    est = estimate_cost_usd(nearby_sku, used_nearby, plan["nearby_calls_with_splits_estimate"])
    est += estimate_cost_usd(text_sku, used_text, plan["planned_text_calls_max"])
    usd_inr = float(pricing()["google"]["usd_to_inr"])  # type: ignore[index]
    plan.update(
        {
            "sku_nearby": nearby_sku,
            "sku_text": text_sku,
            "used_this_month": {nearby_sku: used_nearby, text_sku: used_text},
            "estimated_cost_usd": round(est, 2),
            "estimated_cost_inr": round(est * usd_inr),
            "monthly_cap_per_sku": s.google_monthly_call_cap,
        }
    )
    really = not dry_run and s.google_ingest_confirmed
    with job_run("ingest.google", {"area": area_slug}, dry_run=not really) as run:
        run.counts.update({k: v for k, v in plan.items() if k != "field_mask"})
        if not really:
            plan["note"] = (
                "Dry run: nothing was called. To make real (possibly billed) calls set "
                "GOOGLE_INGEST_CONFIRMED=true in .env and run without --dry-run."
            )
            return plan
        key = s.require("google_places_api_key", "Needed for real Google Places calls.")
        guard = QuotaGuard(store, s.google_monthly_call_cap)
        guard.check(nearby_sku, plan["planned_nearby_calls"])
        client = gp.GooglePlacesClient(key, guard, ratings)
        found: list[gp.GooglePlace] = []
        cats = p["cats"]
        try:
            for cat in cats:
                if cat.google_types:
                    for c in p["circles"]:
                        found.extend(client.nearby_recursive(c, cat.google_types))
                elif cat.google_text_query:
                    for c in p["text_tiles"]:
                        found.extend(client.text(cat.google_text_query, c))
        finally:
            run.est_cost_usd = guard.spent_usd
            run.set("calls_made", guard.calls)
        places = gp.dedupe_by_id(found)
        with connect() as conn:
            cells = {c["h3"] for c in grid_cells(conn, p["area"].id)}
            text_cat = {c.google_text_query: c for c in cats if c.google_text_query}
            for pl in places:
                cat = match_google(pl.types, cats)
                if cat is None and len(text_cat) == 1:
                    cat = next(iter(text_cat.values()))
                cell = h3.latlng_to_cell(pl.lat, pl.lng, cfg.grid.resolution)
                _upsert_place(
                    conn,
                    source="google",
                    source_id=pl.place_id,
                    name=pl.name,
                    category_id=cat.id if cat else None,
                    raw=",".join(pl.types[:4]) or None,
                    lat=pl.lat,
                    lng=pl.lng,
                    cell=cell if cell in cells else None,
                    status=pl.business_status,
                    rating=pl.rating if ratings else None,
                    rating_count=pl.rating_count if ratings else None,
                )
                run.count("places")
            run.set("snapshot_rows", _snapshot(conn, "google"))
        return dict(run.counts)


def google_expire(dry_run: bool) -> dict[str, Any]:
    """Clear Google content older than GOOGLE_CACHE_DAYS. place_id is kept; the exact
    location is replaced by the H3 cell centre (our own derived index)."""
    s = get_settings()
    cutoff = datetime.now(UTC) - timedelta(days=s.google_cache_days)
    with (
        job_run("google.expire", {"cache_days": s.google_cache_days}, dry_run=dry_run) as run,
        connect() as conn,
    ):
        n = conn.execute(
            """select count(*) as n from places where source='google' and not content_expired
               and fetched_at < %s""",
            (cutoff,),
        ).fetchone()
        run.set("to_expire", int(n["n"]) if n else 0)
        if not dry_run:
            cur = conn.execute(
                """update places p set name = null, rating = null, rating_count = null,
                       business_status = null, content_expired = true,
                       geom = coalesce((select c.centroid from h3_cells c where c.h3 = p.h3), p.geom)
                   where source = 'google' and not content_expired and fetched_at < %s""",
                (cutoff,),
            )
            run.set("expired", cur.rowcount)
        return dict(run.counts)


# ------------------------------------------------------------------------------ dedupe
def dedupe(area_slug: str, dry_run: bool) -> dict[str, Any]:
    with connect() as conn:
        area = get_area(conn, area_slug)
        rows = conn.execute(
            """select p.id::text as id, p.source::text as source, p.name,
                      p.category_id::text as category_id,
                      extensions.st_y(p.geom) as lat, extensions.st_x(p.geom) as lng
               from places p join h3_cells c on c.h3 = p.h3
               where c.area_id = %s and p.category_id is not null""",
            (area.id,),
        ).fetchall()
    refs = [
        PlaceRef(r["id"], r["source"], r["name"], r["category_id"], r["lat"], r["lng"])
        for r in rows
    ]
    merges = find_merges(refs)
    with job_run("dedupe", {"area": area_slug}, dry_run=dry_run) as run:
        run.set("places", len(refs))
        run.set("merged", len(merges))
        if not dry_run:
            with connect() as conn, conn.cursor() as cur:
                cur.execute(
                    """update places set merged_into = null
                       where h3 in (select h3 from h3_cells where area_id = %s)""",
                    (area.id,),
                )
                cur.executemany(
                    "update places set merged_into = %s where id = %s",
                    [(canon, dup) for dup, canon in merges.items()],
                )
        return dict(run.counts)


def category_report(area_slug: str) -> list[dict[str, Any]]:
    with connect() as conn:
        area = get_area(conn, area_slug)
        return conn.execute(
            """select coalesce(cat.slug, '(unmapped)') as category, p.source::text as source,
                      count(*) filter (where p.merged_into is null) as canonical,
                      count(*) as total
               from places p join h3_cells c on c.h3 = p.h3
               left join categories cat on cat.id = p.category_id
               where c.area_id = %s
               group by 1, 2 order by 1, 2""",
            (area.id,),
        ).fetchall()


def path_or_none(v: str) -> Path | None:
    return Path(v) if v else None
