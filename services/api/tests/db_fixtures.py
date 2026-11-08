"""Shared setup for tests that need Postgres (local Supabase). Skipped when no DB."""

from __future__ import annotations

import json
import os
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import h3
import jwt
import psycopg
import pytest
from psycopg.rows import dict_row

from engine.settings import get_settings

TEST_AREA = "ci-test"
CENTRE = (26.3000, 91.6000)  # away from the pilot so H3 cells never collide


def db_url() -> str | None:
    return os.environ.get("TEST_DATABASE_URL") or get_settings().database_url or None


def db_available() -> bool:
    url = db_url()
    if not url:
        return False
    try:
        with psycopg.connect(url, connect_timeout=3) as c:
            c.execute("select 1 from public.areas limit 1")
        return True
    except Exception:
        return False


requires_db = pytest.mark.skipif(not db_available(), reason="no test database")


def raw_conn() -> psycopg.Connection[dict[str, Any]]:
    url = db_url()
    assert url
    return psycopg.connect(url, autocommit=True, row_factory=dict_row)


@dataclass
class TestUser:
    id: str
    email: str
    role: str

    def token(self) -> str:
        secret = get_settings().supabase_jwt_secret
        now = int(time.time())
        claims = {"sub": self.id, "aud": "authenticated", "role": "authenticated",
                  "email": self.email, "iat": now, "exp": now + 3600}
        return jwt.encode(claims, secret, algorithm="HS256")

    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token()}"}


def make_user(conn: psycopg.Connection[dict[str, Any]], role: str, name: str) -> TestUser:
    uid = str(uuid.uuid4())
    email = f"{name}-{uid[:8]}@test.invalid"
    conn.execute(
        """insert into auth.users (id, instance_id, aud, role, email, email_confirmed_at,
                                   created_at, updated_at, raw_app_meta_data, raw_user_meta_data)
           values (%s, '00000000-0000-0000-0000-000000000000', 'authenticated', 'authenticated',
                   %s, now(), now(), now(), '{}', '{}')""",
        (uid, email),
    )
    conn.execute(
        "update profiles set role = %s, display_name = %s, verified_at = now() where id = %s",
        (role, name.title(), uid),
    )
    return TestUser(uid, email, role)


def cleanup(conn: psycopg.Connection[dict[str, Any]]) -> None:
    a = conn.execute("select id from areas where slug = %s", (TEST_AREA,)).fetchone()
    if a:
        aid = a["id"]
        conn.execute("delete from data_tasks where h3 in (select h3 from h3_cells where area_id=%s)", (aid,))
        conn.execute("delete from recommendations where area_id = %s", (aid,))
        conn.execute("delete from backtests where area_id = %s", (aid,))
        conn.execute("delete from model_runs where area_id = %s", (aid,))
        conn.execute("delete from survey_responses where survey_id in (select id from surveys where area_id=%s)", (aid,))
        conn.execute("delete from surveys where area_id = %s", (aid,))
        conn.execute("delete from ground_counts where h3 in (select h3 from h3_cells where area_id=%s)", (aid,))
        conn.execute("delete from rent_observations where h3 in (select h3 from h3_cells where area_id=%s)", (aid,))
        conn.execute("delete from saved_areas where area_id = %s", (aid,))
        conn.execute("update profiles set home_h3 = null where home_h3 in (select h3 from h3_cells where area_id=%s)", (aid,))
        conn.execute("delete from places where source_id like 'test/%%'")
        conn.execute("delete from areas where id = %s", (aid,))
    conn.execute("delete from auth.users where email like '%%@test.invalid'")


@dataclass
class Scenario:
    area_id: str
    cells: list[str]
    centre_cell: str
    users: dict[str, TestUser]
    rec_id: str | None = None


def build_scenario() -> Iterator[Scenario]:
    """A small area with population, shops, a scoring run and one draft recommendation."""
    from engine.commands.area import build_area_grid
    from engine.commands.score import run_scoring
    from engine.db import close_pool

    conn = raw_conn()
    cleanup(conn)
    lat, lng = CENTRE
    d = 0.008
    poly = {"type": "Polygon", "coordinates": [[[lng - d, lat - d], [lng + d, lat - d],
                                                [lng + d, lat + d], [lng - d, lat + d],
                                                [lng - d, lat - d]]]}
    row = conn.execute(
        """insert into areas (slug, name, boundary, is_published)
           values (%s, 'Test Bazaar', extensions.st_multi(extensions.st_setsrid(
                   extensions.st_geomfromgeojson(%s), 4326)), true) returning id""",
        (TEST_AREA, json.dumps(poly)),
    ).fetchone()
    assert row
    area_id = str(row["id"])
    build_area_grid(TEST_AREA, dry_run=False)
    cells = [r["h3"] for r in conn.execute(
        "select h3 from h3_cells where area_id = %s order by h3", (area_id,)).fetchall()]
    centre = h3.latlng_to_cell(lat, lng, 9)
    conn.execute("update h3_cells set population = 2500, population_source_year = 2020 where area_id = %s",
                 (area_id,))
    cats = {r["slug"]: r["id"] for r in conn.execute("select slug, id from categories").fetchall()}
    # pharmacies only on the far edge of the area → the centre should look under-supplied
    inside = set(cells)
    ring4 = [c for c in h3.grid_ring(centre, 2) if c in inside][:6]
    for i, c in enumerate(ring4):
        clat, clng = h3.cell_to_latlng(c)
        conn.execute(
            """insert into places (source, source_id, name, category_id, raw_category, geom, h3)
               values ('osm', %s, %s, %s, 'amenity=pharmacy',
                       extensions.st_setsrid(extensions.st_makepoint(%s, %s), 4326), %s)""",
            (f"test/node/{i}", f"Test Medicos {i}", cats["pharmacy"], clng, clat, c),
        )
    for i, c in enumerate(cells[:40]):
        clat, clng = h3.cell_to_latlng(c)
        conn.execute(
            """insert into places (source, source_id, name, category_id, raw_category, geom, h3)
               values ('osm', %s, %s, %s, 'amenity=cafe',
                       extensions.st_setsrid(extensions.st_makepoint(%s, %s), 4326), %s)""",
            (f"test/cafe/{i}", f"Cha Ghar {i}", cats["cafe"], clng, clat, c),
        )
    users = {
        "resident": make_user(conn, "public", "resident"),
        "analyst": make_user(conn, "analyst", "analyst"),
        "admin": make_user(conn, "admin", "admin"),
        "surveyor": make_user(conn, "surveyor", "surveyor"),
        "other": make_user(conn, "public", "other"),
    }
    run_scoring(TEST_AREA, dry_run=False)
    rec = conn.execute(
        "select id from recommendations where area_id = %s order by engine_score desc limit 1",
        (area_id,),
    ).fetchone()
    scen = Scenario(area_id, cells, centre, users, str(rec["id"]) if rec else None)
    try:
        yield scen
    finally:
        cleanup(conn)
        conn.close()
        close_pool()
