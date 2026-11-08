"""Signed-in user endpoints: profile, consent, home cell, saved areas, delete my data."""

from __future__ import annotations

from typing import Any

import h3
from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.auth import CurrentUser
from app.errors import ApiError
from engine.db import connect
from engine.repo import audit
from engine.scoring.config import get_config
from engine.settings import get_settings

router = APIRouter(tags=["me"])


@router.get("/me")
def me(user: CurrentUser) -> dict[str, Any]:
    s = get_settings()
    with connect() as conn:
        area = None
        if user.home_h3:
            area = conn.execute(
                """select a.slug, a.name from h3_cells c join areas a on a.id = c.area_id
                   where c.h3 = %s""",
                (user.home_h3,),
            ).fetchone()
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "role": user.role,
        "home_h3": user.home_h3,
        "home_area": area,
        "verified": user.verified,
        "consent_version": user.consent_version,
        "current_consent_version": s.consent_version,
        "needs_consent": user.consent_version != s.consent_version,
    }


class ConsentBody(BaseModel):
    version: str


@router.post("/me/consent")
def consent(user: CurrentUser, body: ConsentBody) -> dict[str, Any]:
    s = get_settings()
    if body.version != s.consent_version:
        raise ApiError(
            409, "consent_outdated", "The privacy notice changed. Read the new one first."
        )
    with connect() as conn:
        conn.execute(
            "update profiles set consent_version = %s, consent_at = now() where id = %s",
            (body.version, user.id),
        )
        audit(conn, user.id, "consent", "profile", user.id, {"version": body.version})
    return {"consent_version": body.version}


class HomeCellBody(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


@router.post("/me/home-cell")
def home_cell(user: CurrentUser, body: HomeCellBody) -> dict[str, Any]:
    """Stores only the H3 cell (~0.1 km²), never the point. Becomes `resident` once
    verified and consented."""
    s = get_settings()
    cell = h3.latlng_to_cell(body.lat, body.lng, get_config().grid.resolution)
    with connect() as conn:
        row = conn.execute(
            """select a.name from h3_cells c join areas a on a.id = c.area_id
               where c.h3 = %s and c.in_area and a.is_published""",
            (cell,),
        ).fetchone()
        if not row:
            raise ApiError(
                422,
                "outside_area",
                "That spot is outside the areas we cover. Move the pin inside the outlined area.",
            )
        if user.consent_version != s.consent_version:
            raise ApiError(
                409, "consent_required", "Please read and accept the privacy notice first."
            )
        promote = user.role == "public" and user.verified
        conn.execute(
            f"""update profiles set home_h3 = %s
                {", role = 'resident'" if promote else ""} where id = %s""",
            (cell, user.id),
        )
        audit(conn, user.id, "set_home_cell", "profile", user.id, {"h3": cell})
    return {"home_h3": cell, "area": row["name"], "role": "resident" if promote else user.role}


@router.delete("/me")
def delete_me(user: CurrentUser) -> dict[str, Any]:
    """DPDP right to erasure: removes the auth user, profile, saved areas and survey answers."""
    with connect() as conn:
        n = conn.execute(
            "delete from survey_responses where respondent_id = %s", (user.id,)
        ).rowcount
        conn.execute("delete from saved_areas where user_id = %s", (user.id,))
        audit(conn, None, "delete_account", "profile", user.id, {"survey_responses": n})
        conn.execute("delete from auth.users where id = %s", (user.id,))
    return {"deleted": True, "survey_responses_removed": n}


class SavedAreaBody(BaseModel):
    area: str
    category: str | None = None
    h3: str | None = None


@router.get("/saved-areas")
def saved_list(user: CurrentUser) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """select a.slug as area, a.name as area_name, c.slug as category, s.h3, s.created_at
               from saved_areas s join areas a on a.id = s.area_id
               left join categories c on c.id = s.category_id
               where s.user_id = %s order by s.created_at desc""",
            (user.id,),
        ).fetchall()
    return [{**r, "created_at": r["created_at"].isoformat()} for r in rows]


@router.post("/saved-areas")
def saved_add(user: CurrentUser, body: SavedAreaBody) -> dict[str, Any]:
    with connect() as conn:
        a = conn.execute(
            "select id from areas where slug = %s and is_published", (body.area,)
        ).fetchone()
        if not a:
            raise ApiError(404, "not_found", "We couldn't find that area.")
        cat = None
        if body.category:
            cat = conn.execute(
                "select id from categories where slug=%s", (body.category,)
            ).fetchone()
        cell = (
            body.h3
            if body.h3
            and conn.execute("select 1 from h3_cells where h3 = %s", (body.h3,)).fetchone()
            else None
        )
        conn.execute(
            """insert into saved_areas (user_id, area_id, category_id, h3) values (%s,%s,%s,%s)
               on conflict (user_id, area_id) do update set category_id = excluded.category_id,
                   h3 = excluded.h3, created_at = now()""",
            (user.id, a["id"], cat["id"] if cat else None, cell),
        )
    return {"saved": True}


@router.delete("/saved-areas/{area}")
def saved_delete(user: CurrentUser, area: str) -> dict[str, Any]:
    with connect() as conn:
        n = conn.execute(
            """delete from saved_areas where user_id = %s
               and area_id = (select id from areas where slug = %s)""",
            (user.id, area),
        ).rowcount
    return {"deleted": n > 0}
