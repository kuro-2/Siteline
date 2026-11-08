"""Small data-access helpers shared by engine commands and the API."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import psycopg
from shapely import wkb
from shapely.geometry import MultiPolygon

from engine.sources.categories import CategoryDef

Conn = psycopg.Connection[dict[str, Any]]


class NotFound(LookupError):
    pass


@dataclass(frozen=True)
class Area:
    id: str
    slug: str
    name: str
    boundary: MultiPolygon
    is_published: bool


def get_area(conn: Conn, slug: str) -> Area:
    row = conn.execute(
        """select id, slug, name, is_published, extensions.st_asbinary(boundary) as b
           from areas where slug = %s""",
        (slug,),
    ).fetchone()
    if not row:
        raise NotFound(
            f"No area with slug '{slug}'. Load it first: "
            f'uv run engine area load --slug {slug} --name "…" --geojson <file>'
        )
    geom = wkb.loads(bytes(row["b"]))
    return Area(str(row["id"]), row["slug"], row["name"], geom, row["is_published"])


def load_categories(conn: Conn, active_only: bool = True) -> list[CategoryDef]:
    rows = conn.execute(
        f"""select id, slug, name, osm_tags, google_types, google_text_query, catchment_k,
                  sort_order from categories {"where active" if active_only else ""}
           order by sort_order, slug"""
    ).fetchall()
    return [
        CategoryDef(
            id=str(r["id"]),
            slug=r["slug"],
            name=r["name"],
            osm_tags=r["osm_tags"]
            if isinstance(r["osm_tags"], list)
            else json.loads(r["osm_tags"]),
            google_types=list(r["google_types"] or []),
            google_text_query=r["google_text_query"],
            catchment_k=r["catchment_k"],
            sort_order=r["sort_order"],
        )
        for r in rows
    ]


def grid_cells(conn: Conn, area_id: str) -> list[dict[str, Any]]:
    return conn.execute(
        """select h3, in_area, population, population_source_year,
                  extensions.st_y(centroid) as lat, extensions.st_x(centroid) as lng
           from h3_cells where area_id = %s order by h3""",
        (area_id,),
    ).fetchall()


def audit(
    conn: Conn,
    actor: str | None,
    action: str,
    entity: str,
    entity_id: str,
    diff: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        "insert into audit_log (actor, action, entity, entity_id, diff) values (%s,%s,%s,%s,%s)",
        (actor, action, entity, entity_id, json.dumps(diff or {}, default=str)),
    )
