"""Admin: freshness, costs, jobs, backtests, categories, areas, users."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
from typing import Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.auth import Admin
from app.errors import ApiError, not_found
from engine.db import connect
from engine.quota import pricing
from engine.repo import audit
from engine.settings import API_DIR

router = APIRouter(prefix="/admin", tags=["admin"])

SOURCES = {
    "OpenStreetMap": "ingest.osm",
    "WorldPop": "ingest.worldpop",
    "Google Places": "ingest.google",
    "KoboToolbox": "ingest.kobo",
    "Dedupe": "dedupe",
    "Scores": "score.run",
    "Explanations": "explain.draft",
    "Backtest": "backtest.run",
    "Outcomes": "outcomes.scan",
    "Google expiry": "google.expire",
}

# Jobs the admin page may start, mapped to engine CLI arguments.
JOBS: dict[str, list[str]] = {
    "ingest-osm": ["ingest", "osm"],
    "ingest-worldpop": ["ingest", "worldpop"],
    "ingest-google": ["ingest", "google"],
    "ingest-kobo": ["ingest", "kobo"],
    "dedupe": ["ingest", "dedupe"],
    "score": ["score", "run"],
    "explain": ["explain", "draft"],
    "backtest": ["backtest", "run"],
    "outcomes": ["outcomes", "scan"],
    "google-expire": ["google", "expire"],
}
AREA_JOBS = {
    "ingest-osm",
    "ingest-worldpop",
    "ingest-google",
    "dedupe",
    "score",
    "explain",
    "backtest",
    "outcomes",
}


def _iso(v: Any) -> Any:
    return v.isoformat() if hasattr(v, "isoformat") else v


@router.get("/freshness")
def freshness(user: Admin) -> list[dict[str, Any]]:
    _ = user
    out = []
    with connect() as conn:
        for label, job in SOURCES.items():
            r = conn.execute(
                """select finished_at, counts, extract(epoch from now() - finished_at)/86400 as age
                   from job_runs where job = %s and status = 'succeeded'
                   order by finished_at desc limit 1""",
                (job,),
            ).fetchone()
            last_fail = conn.execute(
                """select started_at, error from job_runs where job = %s and status = 'failed'
                   order by started_at desc limit 1""",
                (job,),
            ).fetchone()
            out.append(
                {
                    "source": label,
                    "job": job,
                    "last_success": _iso(r["finished_at"]) if r else None,
                    "age_days": round(float(r["age"]), 1) if r else None,
                    "counts": r["counts"] if r else None,
                    "last_failure": {
                        "at": _iso(last_fail["started_at"]),
                        "error": last_fail["error"],
                    }
                    if last_fail
                    else None,
                }
            )
    return out


@router.get("/costs")
def costs(user: Admin) -> dict[str, Any]:
    _ = user
    rate = float(pricing()["google"]["usd_to_inr"])  # type: ignore[index]
    with connect() as conn:
        rows = conn.execute(
            "select provider, sku, month, calls, est_cost_usd from api_usage order by month desc, sku"
        ).fetchall()
    return {
        "usd_to_inr": rate,
        "rows": [
            {
                **r,
                "month": r["month"].isoformat(),
                "est_cost_usd": float(r["est_cost_usd"]),
                "est_cost_inr": round(float(r["est_cost_usd"]) * rate),
            }
            for r in rows
        ],
    }


class JobBody(BaseModel):
    dry_run: bool = True
    area: str | None = None
    args: dict[str, str] = Field(default_factory=dict)


def _spawn(cmd: list[str]) -> None:
    def run() -> None:
        subprocess.run(cmd, cwd=API_DIR, capture_output=True, text=True, timeout=3600, check=False)

    threading.Thread(target=run, daemon=True).start()


@router.post("/jobs/{job}", status_code=202)
def start_job(job: str, body: JobBody, user: Admin) -> dict[str, Any]:
    if job not in JOBS:
        raise ApiError(
            404,
            "unknown_job",
            f"There's no job called '{job}'.",
            "Pick one from the list on the admin page.",
        )
    cmd = [sys.executable, "-m", "engine.cli", *JOBS[job]]
    if job in AREA_JOBS and body.area:
        cmd += ["--area", body.area]
    if body.dry_run:
        cmd.append("--dry-run")
    if job == "backtest":
        for k in ("as_of", "evaluate_on"):
            if k in body.args:
                cmd += [f"--{k.replace('_', '-')}", body.args[k]]
    with connect() as conn:
        audit(conn, user.id, "start_job", "job", job, {"dry_run": body.dry_run, "area": body.area})
    _spawn(cmd)
    return {
        "started": job,
        "dry_run": body.dry_run,
        "note": "Running in the background. Refresh the jobs list in a minute.",
    }


@router.get("/jobs")
def jobs(
    user: Admin, limit: int = Query(50, ge=1, le=100), job: str | None = None
) -> list[dict[str, Any]]:
    _ = user
    with connect() as conn:
        rows = conn.execute(
            f"""select id, job, args, status::text as status, started_at, finished_at, counts, error,
                       est_cost_usd from job_runs {"where job = %s" if job else ""}
                order by started_at desc limit %s""",
            ([job, limit] if job else [limit]),
        ).fetchall()
    return [
        {
            **r,
            "id": str(r["id"]),
            "started_at": _iso(r["started_at"]),
            "finished_at": _iso(r["finished_at"]),
            "est_cost_usd": float(r["est_cost_usd"] or 0),
        }
        for r in rows
    ]


@router.get("/backtests")
def backtests(user: Admin) -> list[dict[str, Any]]:
    _ = user
    with connect() as conn:
        rows = conn.execute(
            """select b.id, b.as_of, b.evaluated_on, b.metrics, b.created_at, a.slug as area
               from backtests b left join areas a on a.id = b.area_id order by b.created_at desc"""
        ).fetchall()
    return [
        {
            **r,
            "id": str(r["id"]),
            "as_of": _iso(r["as_of"]),
            "evaluated_on": _iso(r["evaluated_on"]),
            "created_at": _iso(r["created_at"]),
        }
        for r in rows
    ]


@router.get("/backtests/{bt_id}")
def backtest(bt_id: str, user: Admin) -> dict[str, Any]:
    _ = user
    with connect() as conn:
        r = conn.execute("select * from backtests where id = %s", (bt_id,)).fetchone()
    if not r:
        raise not_found("backtest")
    return {
        **r,
        "id": str(r["id"]),
        "run_id": str(r["run_id"]) if r["run_id"] else None,
        "area_id": str(r["area_id"]) if r["area_id"] else None,
        "as_of": _iso(r["as_of"]),
        "evaluated_on": _iso(r["evaluated_on"]),
        "created_at": _iso(r["created_at"]),
    }


@router.get("/calibration")
def calibration(user: Admin) -> dict[str, Any]:
    """Published picks by confidence band vs what happened afterwards (outcomes)."""
    _ = user
    with connect() as conn:
        rows = conn.execute(
            """select r.confidence::text as band, count(distinct r.id) as published,
                      count(o.id) filter (where o.event = 'opened') as opened,
                      count(o.id) filter (where o.event = 'closed') as closed
               from recommendations r left join outcomes o on o.recommendation_id = r.id
               where r.status = 'published' group by 1 order by 1"""
        ).fetchall()
    return {"bands": rows}


# ------------------------------------------------------------------ categories
class CategoryBody(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9-]+$")
    name: str
    description: str | None = None
    osm_tags: list[dict[str, str]]
    google_types: list[str] = Field(default_factory=list)
    google_text_query: str | None = None
    catchment_k: int = Field(ge=1, le=10)
    people_per_outlet_benchmark: int | None = None
    sort_order: int = 100
    active: bool = True


@router.get("/categories")
def list_categories(user: Admin) -> list[dict[str, Any]]:
    _ = user
    with connect() as conn:
        rows = conn.execute("select * from categories order by sort_order").fetchall()
    return [{**r, "id": str(r["id"])} for r in rows]


@router.put("/categories/{slug}")
def upsert_category(slug: str, body: CategoryBody, user: Admin) -> dict[str, Any]:
    if slug != body.slug:
        raise ApiError(422, "slug_mismatch", "The slug in the address and the form must match.")
    with connect() as conn:
        conn.execute(
            """insert into categories (slug, name, description, osm_tags, google_types,
                   google_text_query, catchment_k, people_per_outlet_benchmark, sort_order, active)
               values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               on conflict (slug) do update set name=excluded.name, description=excluded.description,
                 osm_tags=excluded.osm_tags, google_types=excluded.google_types,
                 google_text_query=excluded.google_text_query, catchment_k=excluded.catchment_k,
                 people_per_outlet_benchmark=excluded.people_per_outlet_benchmark,
                 sort_order=excluded.sort_order, active=excluded.active""",
            (
                body.slug,
                body.name,
                body.description,
                json.dumps(body.osm_tags),
                body.google_types,
                body.google_text_query,
                body.catchment_k,
                body.people_per_outlet_benchmark,
                body.sort_order,
                body.active,
            ),
        )
        audit(conn, user.id, "upsert_category", "category", slug, body.model_dump())
    return {"saved": slug}


# ------------------------------------------------------------------ areas
class AreaPatch(BaseModel):
    name: str | None = None
    is_published: bool | None = None


@router.get("/areas")
def list_areas(user: Admin) -> list[dict[str, Any]]:
    _ = user
    with connect() as conn:
        rows = conn.execute(
            """select a.id, a.slug, a.name, a.is_published, a.created_at,
                      (select count(*) from h3_cells c where c.area_id = a.id and c.in_area) as cells
               from areas a order by a.name"""
        ).fetchall()
    return [{**r, "id": str(r["id"]), "created_at": _iso(r["created_at"])} for r in rows]


@router.patch("/areas/{slug}")
def patch_area(slug: str, body: AreaPatch, user: Admin) -> dict[str, Any]:
    with connect() as conn:
        n = conn.execute(
            """update areas set name = coalesce(%s, name), is_published = coalesce(%s, is_published)
               where slug = %s""",
            (body.name, body.is_published, slug),
        ).rowcount
        if not n:
            raise not_found("area")
        audit(conn, user.id, "patch_area", "area", slug, body.model_dump(exclude_none=True))
    return {"saved": slug}


# ------------------------------------------------------------------ users
@router.get("/users")
def users(
    user: Admin, q: str | None = None, limit: int = Query(50, ge=1, le=100)
) -> list[dict[str, Any]]:
    _ = user
    with connect() as conn:
        rows = conn.execute(
            """select p.id, u.email, p.display_name, p.role::text as role, p.home_h3, p.created_at
               from profiles p join auth.users u on u.id = p.id
               where (%s::text is null or u.email ilike '%%' || %s || '%%' or p.display_name ilike '%%' || %s || '%%')
               order by p.created_at desc limit %s""",
            (q, q, q, limit),
        ).fetchall()
    return [{**r, "id": str(r["id"]), "created_at": _iso(r["created_at"])} for r in rows]


class RoleBody(BaseModel):
    role: Literal["public", "resident", "surveyor", "analyst", "admin"]
    display_name: str | None = Field(default=None, max_length=80)


@router.post("/users/{user_id}/role")
def set_role(user_id: str, body: RoleBody, user: Admin) -> dict[str, Any]:
    if user_id == user.id and body.role != "admin":
        raise ApiError(
            409,
            "self_demote",
            "You can't remove your own admin role here.",
            "Ask another admin to do it.",
        )
    with connect() as conn:
        n = conn.execute(
            "update profiles set role = %s, display_name = coalesce(%s, display_name) where id = %s",
            (body.role, body.display_name, user_id),
        ).rowcount
        if not n:
            raise not_found("user")
        audit(conn, user.id, "set_role", "profile", user_id, {"role": body.role})
    return {"id": user_id, "role": body.role}


@router.get("/data-tasks")
def data_tasks(user: Admin, status: str = "open") -> list[dict[str, Any]]:
    _ = user
    with connect() as conn:
        rows = conn.execute(
            """select t.id, t.kind, t.h3, t.status, t.notes, t.created_at, c.slug as category
               from data_tasks t left join categories c on c.id = t.category_id
               where t.status = %s order by t.created_at desc""",
            (status,),
        ).fetchall()
    return [{**r, "id": str(r["id"]), "created_at": _iso(r["created_at"])} for r in rows]
