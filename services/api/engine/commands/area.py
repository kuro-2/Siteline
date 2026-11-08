"""`engine area load` and `engine geo build-grid`."""

from __future__ import annotations

import json
from pathlib import Path

from shapely.geometry import mapping

from engine.db import connect
from engine.geo.grid import area_km2, build_grid, load_boundary
from engine.jobs import job_run
from engine.repo import get_area
from engine.scoring.config import get_config


def load_area(
    slug: str, name: str, geojson: Path, publish: bool, dry_run: bool
) -> dict[str, object]:
    boundary = load_boundary(geojson)
    km2 = area_km2(boundary)
    info: dict[str, object] = {"slug": slug, "name": name, "area_km2": round(km2, 2)}
    if km2 > 25:
        raise ValueError(
            f"The boundary covers {km2:.1f} km². The pilot should be 3–6 km²; "
            "check you drew the right area."
        )
    with job_run("area.load", {"slug": slug, "file": str(geojson)}, dry_run=dry_run) as run:
        run.set("area_km2", round(km2, 2))
        if dry_run:
            return info
        with connect() as conn:
            conn.execute(
                """insert into areas (slug, name, boundary, is_published)
                   values (%s, %s, extensions.st_multi(extensions.st_setsrid(
                           extensions.st_geomfromgeojson(%s), 4326)), %s)
                   on conflict (slug) do update set name = excluded.name,
                       boundary = excluded.boundary, is_published = excluded.is_published""",
                (slug, name, json.dumps(mapping(boundary)), publish),
            )
    return info


def build_area_grid(slug: str, dry_run: bool) -> dict[str, int]:
    cfg = get_config()
    with connect() as conn:
        area = get_area(conn, slug)
    cells = build_grid(area.boundary, cfg.grid.resolution, cfg.max_catchment_k)
    inside = sum(1 for c in cells if c.in_area)
    result = {"cells_inside": inside, "cells_buffer": len(cells) - inside}
    with job_run("geo.build-grid", {"area": slug}, dry_run=dry_run) as run:
        run.counts.update(result)
        if dry_run:
            return result
        with connect() as conn, conn.cursor() as cur:
            cur.executemany(
                """insert into h3_cells (h3, area_id, geom, centroid, in_area)
                   values (%s, %s, extensions.st_setsrid(extensions.st_geomfromtext(%s), 4326),
                           extensions.st_setsrid(extensions.st_geomfromtext(%s), 4326), %s)
                   on conflict (h3) do update set area_id = excluded.area_id,
                       in_area = excluded.in_area""",
                [(c.h3, area.id, c.polygon.wkt, c.centroid.wkt, c.in_area) for c in cells],
            )
            # cells no longer in the grid (boundary was redrawn)
            cur.execute(
                "delete from h3_cells where area_id = %s and not (h3 = any(%s))",
                (area.id, [c.h3 for c in cells]),
            )
    return result
