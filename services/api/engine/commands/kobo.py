"""`engine ingest kobo`: pull ground counts, store photos in Supabase Storage."""

from __future__ import annotations

from typing import Any

import h3
import httpx

from engine.db import connect
from engine.jobs import job_run
from engine.repo import load_categories
from engine.scoring.config import get_config
from engine.settings import get_settings
from engine.sources.kobo import KoboClient, parse_submission

PHOTO_BUCKET = "field-photos"


def _upload_photo(path: str, content: bytes, content_type: str = "image/jpeg") -> None:
    s = get_settings()
    url = f"{s.require('supabase_url')}/storage/v1/object/{PHOTO_BUCKET}/{path}"
    key = s.require("supabase_service_role_key", "Needed to store field photos.")
    r = httpx.post(
        url,
        content=content,
        headers={
            "Authorization": f"Bearer {key}",
            "apikey": key,
            "Content-Type": content_type,
            "x-upsert": "true",
        },
        timeout=60,
    )
    r.raise_for_status()


def ingest_kobo(dry_run: bool, with_photos: bool = True) -> dict[str, Any]:
    s = get_settings()
    token = s.require("kobo_api_token", "Get it from KoboToolbox → Account settings → Security.")
    uid = s.require("kobo_asset_uid", "It's in the form's URL on KoboToolbox.")
    cfg = get_config()
    client = KoboClient(s.kobo_base_url, token)
    with connect() as conn:
        cats = {c.slug: c for c in load_categories(conn)}
        known = {
            r["kobo_submission_id"]
            for r in conn.execute(
                "select kobo_submission_id from ground_counts where kobo_submission_id is not null"
            ).fetchall()
        }
        surveyors = {
            r["kobo_username"]: r
            for r in conn.execute(
                "select kobo_username, user_id, display_name from surveyors"
            ).fetchall()
        }
        grid = {r["h3"] for r in conn.execute("select h3 from h3_cells").fetchall()}
    with job_run("ingest.kobo", {"asset": uid}, dry_run=dry_run) as run:
        subs = client.submissions(uid)
        run.set("submissions", len(subs))
        for raw in subs:
            sub = parse_submission(raw)
            if sub is None:
                run.count("unparseable")
                continue
            if sub.submission_id in known:
                run.count("already_imported")
                continue
            cat = cats.get(sub.category_slug)
            cell = h3.latlng_to_cell(sub.lat, sub.lng, cfg.grid.resolution)
            if cat is None or cell not in grid:
                run.count("outside_grid_or_unknown_category")
                continue
            run.count("new")
            if dry_run:
                continue
            sv = surveyors.get(sub.username or "")
            paths: list[str] = []
            if with_photos:
                for i, ph in enumerate(sub.photos):
                    if not ph["url"]:
                        continue
                    path = f"{cell}/{sub.submission_id}-{i}.jpg"
                    try:
                        _upload_photo(path, client.download(ph["url"]))
                        paths.append(path)
                    except httpx.HTTPError:
                        run.count("photo_failed")
            with connect() as conn:
                conn.execute(
                    """insert into ground_counts (kobo_submission_id, surveyor_id, surveyor_name, h3,
                           category_id, count, informal_count, photo_paths, counted_at, notes)
                       values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       on conflict (kobo_submission_id) do nothing""",
                    (
                        sub.submission_id,
                        sv["user_id"] if sv else None,
                        sv["display_name"] if sv else (sub.username or "Field team"),
                        cell,
                        cat.id,
                        sub.count,
                        sub.informal_count,
                        paths or None,
                        sub.counted_at,
                        sub.notes,
                    ),
                )
        return dict(run.counts)
