"""Resident surveys."""

from __future__ import annotations

import json
from typing import Annotated, Any

import h3
from fastapi import APIRouter, Header, Request
from pydantic import BaseModel, Field

from app.auth import CurrentUser, Resident
from app.errors import ApiError, not_found
from app.limits import limiter, user_or_ip
from app.services.fraud import flags_for, location_check, salted_hash, weight_for
from engine.db import connect
from engine.repo import audit
from engine.settings import get_settings
from engine.survey import need_indicator, validate_answers

router = APIRouter(tags=["surveys"])
MIN_GROUP_N = 20


def _survey(conn: Any, slug: str) -> dict[str, Any]:
    row = conn.execute(
        """select s.id, s.slug, s.title, s.questions, s.version, s.opens_at, s.closes_at,
                  s.is_active, a.slug as area_slug, a.name as area_name, a.id as area_id
           from surveys s join areas a on a.id = s.area_id where s.slug = %s""",
        (slug,),
    ).fetchone()
    if not row or not row["is_active"]:
        raise not_found("survey", "The link may be old. Check the poster or the area page.")
    return row


@router.get("/surveys/{slug}")
def get_survey(slug: str, user: CurrentUser) -> dict[str, Any]:
    with connect() as conn:
        s = _survey(conn, slug)
        done = conn.execute(
            "select 1 from survey_responses where survey_id = %s and respondent_id = %s",
            (s["id"], user.id),
        ).fetchone()
    return {
        "slug": s["slug"],
        "title": s["title"],
        "version": s["version"],
        "questions": s["questions"],
        "area": {"slug": s["area_slug"], "name": s["area_name"]},
        "closes_at": s["closes_at"].isoformat() if s["closes_at"] else None,
        "already_answered": done is not None,
    }


class ResponseBody(BaseModel):
    answers: dict[str, Any]
    survey_version: int
    duration_seconds: int | None = Field(default=None, ge=0, le=86400)
    device_id: str | None = Field(default=None, max_length=100)
    geo: dict[str, float] | None = None
    confirmed_on_map: bool = False


@router.post("/surveys/{slug}/responses", status_code=201)
@limiter.limit("5/minute", key_func=user_or_ip)
def submit(
    request: Request,
    slug: str,
    body: ResponseBody,
    user: Resident,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, Any]:
    if not idempotency_key or len(idempotency_key) > 100:
        raise ApiError(400, "idempotency_key_required", "Your app needs updating. Reload the page.")
    s = get_settings()
    if not user.home_h3:
        raise ApiError(409, "home_cell_required", "Tell us roughly where you live first.")
    salt = s.device_hash_salt or ("" if s.app_env == "production" else "local-dev")
    if not salt:
        raise ApiError(500, "not_configured", "Surveys aren't set up on this server yet.")
    with connect() as conn:
        prior = conn.execute(
            "select id from survey_responses where idempotency_key = %s and respondent_id = %s",
            (idempotency_key, user.id),
        ).fetchone()
        if prior:
            return {"id": str(prior["id"]), "duplicate": True}
        sv = _survey(conn, slug)
        if sv["closes_at"] and sv["closes_at"] < conn.execute("select now() as n").fetchone()["n"]:
            raise ApiError(
                409,
                "survey_closed",
                f"This survey closed on {sv['closes_at']:%d %b}.",
                "Check back for the next round.",
            )
        if body.survey_version != sv["version"]:
            raise ApiError(
                409,
                "survey_changed",
                "The questions changed while you were answering. Reload to see them.",
            )
        problems = validate_answers(sv["questions"], body.answers)
        if problems:
            raise ApiError(
                422, "invalid_answers", "Some answers didn't make sense: " + "; ".join(problems[:3])
            )
        if not body.answers:
            raise ApiError(422, "empty", "Answer at least one question.")
        in_area = conn.execute(
            "select 1 from h3_cells where h3 = %s and area_id = %s", (user.home_h3, sv["area_id"])
        ).fetchone()
        if not in_area:
            raise ApiError(409, "wrong_area", "This survey is for a different area from your home.")
        device_hash = salted_hash(body.device_id, salt)
        client_ip = request.client.host if request.client else None
        ip_hash = salted_hash(client_ip, salt)
        recent = conn.execute(
            """select count(*) filter (where device_hash = %(d)s and %(d)s is not null) as dev,
                      count(*) filter (where ip_hash = %(i)s and %(i)s is not null) as ip,
                      count(*) filter (where h3 = %(c)s) as cell
               from survey_responses where submitted_at > now() - interval '1 hour'""",
            {"d": device_hash, "i": ip_hash, "c": user.home_h3},
        ).fetchone()
        loc = location_check(user.home_h3, body.geo, body.confirmed_on_map)
        flags = flags_for(
            questions=sv["questions"],
            answers=body.answers,
            duration_seconds=body.duration_seconds,
            location_ok=loc,
            recent_same_device=recent["dev"],
            recent_same_ip=recent["ip"],
            recent_same_cell=recent["cell"],
        )
        try:
            row = conn.execute(
                """insert into survey_responses (survey_id, survey_version, respondent_id, h3, answers,
                       device_hash, ip_hash, duration_seconds, idempotency_key, location_check_passed,
                       fraud_flags, weight)
                   values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning id""",
                (
                    sv["id"],
                    sv["version"],
                    user.id,
                    user.home_h3,
                    json.dumps(body.answers),
                    device_hash,
                    ip_hash,
                    body.duration_seconds,
                    idempotency_key,
                    loc,
                    flags,
                    weight_for(flags),
                ),
            ).fetchone()
        except Exception as e:
            if "survey_responses_survey_id_respondent_id_key" in str(e):
                raise ApiError(
                    409, "already_answered", "You've already answered this survey. Thank you."
                ) from e
            raise
        assert row is not None
        audit(conn, user.id, "survey_submit", "survey_response", str(row["id"]), {"flags": flags})
    return {"id": str(row["id"]), "duplicate": False}


@router.get("/surveys/{slug}/summary")
def summary(slug: str, user: Resident) -> dict[str, Any]:
    """Neighbours' answers around the user's home cell (cell + ring), only if n >= 20."""
    cell = user.home_h3
    if not cell:
        raise ApiError(409, "home_cell_required", "Tell us roughly where you live first.")
    group = list(h3.grid_disk(cell, 1))
    with connect() as conn:
        sv = _survey(conn, slug)
        rows = conn.execute(
            """select answers from survey_responses where survey_id = %s and h3 = any(%s)
               and not excluded and weight > 0""",
            (sv["id"], group),
        ).fetchall()
        cats = conn.execute(
            "select slug, name from categories where active order by sort_order"
        ).fetchall()
    n = len(rows)
    if n < MIN_GROUP_N:
        return {"n": n, "min_n": MIN_GROUP_N, "shown": False, "categories": []}
    from engine.scoring.config import get_config

    cfg = get_config()
    out = []
    for c in cats:
        if c["slug"] not in cfg.categories:
            continue
        vals = [
            need_indicator(r["answers"], c["slug"], cfg.categories[c["slug"]].travel_minutes)
            for r in rows
        ]
        vals = [v for v in vals if v is not None]
        if len(vals) >= MIN_GROUP_N:
            out.append(
                {
                    "slug": c["slug"],
                    "name": c["name"],
                    "n": len(vals),
                    "share_travel_far": round(sum(1 for v in vals if v >= 1) / len(vals), 2),
                }
            )
    return {"n": n, "min_n": MIN_GROUP_N, "shown": True, "categories": out}
