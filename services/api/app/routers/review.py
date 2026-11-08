"""Analyst review: queue, review screen, decisions, explanation, data requests, fraud flags."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.auth import Analyst
from app.errors import ApiError, not_found
from app.services.report import build_report
from engine.commands.analysis import explanation_payload
from engine.db import connect
from engine.llm.client import CachedClient, make_client
from engine.llm.explain import check_numbers, draft_explanation
from engine.repo import audit

router = APIRouter(prefix="/review", tags=["review"])

BAND_WEIGHT = {"not_enough_data": 0.0, "early_signal": 0.6, "fairly_sure": 0.85, "confident": 1.0}


@router.get("/queue")
def queue(
    user: Analyst,
    status: Literal["draft", "in_review", "needs_data", "open"] = "open",
    category: str | None = None,
    limit: int = Query(50, ge=1, le=100),
) -> list[dict[str, Any]]:
    _ = user
    statuses = ["draft", "in_review", "needs_data"] if status == "open" else [status]
    params: list[Any] = [statuses]
    where = "r.status::text = any(%s)"
    if category:
        where += " and c.slug = %s"
        params.append(category)
    with connect() as conn:
        rows = conn.execute(
            f"""select r.id, r.h3, r.status::text as status, r.engine_score,
                       r.confidence::text as confidence, r.created_at, c.slug as category,
                       c.name as category_name, a.slug as area, a.name as area_name,
                       extract(epoch from now() - mr.data_snapshot_at) / 86400 as data_age_days
                from recommendations r join categories c on c.id = r.category_id
                join areas a on a.id = r.area_id join model_runs mr on mr.id = r.run_id
                where {where}""",
            params,
        ).fetchall()
    items = []
    for r in rows:
        freshness = max(0.3, 1 - float(r["data_age_days"] or 0) / 120)
        priority = float(r["engine_score"]) * BAND_WEIGHT.get(r["confidence"], 0.5) * freshness
        items.append(
            {
                **r,
                "id": str(r["id"]),
                "engine_score": round(float(r["engine_score"])),
                "created_at": r["created_at"].isoformat(),
                "priority": round(priority, 1),
                "data_age_days": round(float(r["data_age_days"] or 0)),
            }
        )
    items.sort(key=lambda x: -x["priority"])
    return items[:limit]


@router.get("/flagged-responses")
def flagged(user: Analyst, limit: int = Query(50, ge=1, le=100)) -> list[dict[str, Any]]:
    _ = user
    with connect() as conn:
        rows = conn.execute(
            """select sr.id, sr.h3, sr.fraud_flags, sr.submitted_at, sr.duration_seconds,
                      sr.location_check_passed, s.slug as survey
               from survey_responses sr join surveys s on s.id = sr.survey_id
               where cardinality(sr.fraud_flags) > 0 and sr.cleared_by is null and not sr.excluded
               order by sr.submitted_at desc limit %s""",
            (limit,),
        ).fetchall()
    # No answers or identities: analysts judge on the flags and timing only.
    return [{**r, "id": str(r["id"]), "submitted_at": r["submitted_at"].isoformat()} for r in rows]


class FlagDecision(BaseModel):
    action: Literal["clear", "exclude"]


@router.post("/flagged-responses/{resp_id}")
def flag_decide(resp_id: str, body: FlagDecision, user: Analyst) -> dict[str, Any]:
    with connect() as conn:
        if body.action == "clear":
            n = conn.execute(
                "update survey_responses set cleared_by = %s, weight = 1.0 where id = %s",
                (user.id, resp_id),
            ).rowcount
        else:
            n = conn.execute(
                "update survey_responses set excluded = true, weight = 0, cleared_by = %s where id = %s",
                (user.id, resp_id),
            ).rowcount
        if not n:
            raise not_found("response")
        audit(conn, user.id, f"response_{body.action}", "survey_response", resp_id)
    return {"id": resp_id, "action": body.action}


def _rec(conn: Any, rec_id: str) -> dict[str, Any]:
    row = conn.execute(
        """select r.*, r.status::text as status_text, r.confidence::text as confidence_text,
                  c.slug as category, c.name as category_name, a.slug as area_slug,
                  s.components, s.score_low, s.score_high, f.features
           from recommendations r join categories c on c.id = r.category_id
           join areas a on a.id = r.area_id
           left join scores s on s.run_id = r.run_id and s.h3 = r.h3 and s.category_id = r.category_id
           left join cell_features f on f.run_id = r.run_id and f.h3 = r.h3 and f.category_id = r.category_id
           where r.id = %s""",
        (rec_id,),
    ).fetchone()
    if not row:
        raise not_found("recommendation")
    return row


@router.get("/{rec_id}")
def detail(rec_id: str, user: Analyst) -> dict[str, Any]:
    with connect() as conn:
        r = _rec(conn, rec_id)
        if r["status_text"] == "draft":
            conn.execute("update recommendations set status = 'in_review' where id = %s", (rec_id,))
            audit(conn, user.id, "start_review", "recommendation", rec_id)
            r = _rec(conn, rec_id)
        history = conn.execute(
            """select ar.decision::text as decision, ar.score_delta, ar.reason, ar.created_at,
                      p.display_name as analyst
               from analyst_reviews ar left join profiles p on p.id = ar.analyst_id
               where ar.recommendation_id = %s order by ar.created_at""",
            (rec_id,),
        ).fetchall()
        try:
            report = build_report(conn, r["h3"], r["category"])
        except ApiError:
            report = None
    comps = r["components"] or {}
    return {
        "id": str(r["id"]),
        "h3": r["h3"],
        "area": r["area_slug"],
        "category": r["category"],
        "category_name": r["category_name"],
        "status": r["status_text"],
        "engine_score": round(float(r["engine_score"])),
        "final_score": round(float(r["final_score"])) if r["final_score"] is not None else None,
        "score_low": round(float(r["score_low"])) if r["score_low"] is not None else None,
        "score_high": round(float(r["score_high"])) if r["score_high"] is not None else None,
        "confidence": r["confidence_text"],
        "components": comps.get("items", []) if isinstance(comps, dict) else [],
        "features": r["features"] or {},
        "explanation_draft": r["explanation_draft"],
        "explanation_final": r["explanation_final"],
        "history": [
            {
                **h,
                "created_at": h["created_at"].isoformat(),
                "score_delta": float(h["score_delta"]) if h["score_delta"] is not None else None,
            }
            for h in history
        ],
        "evidence": report["evidence"] if report else None,
        "limits": report["limits"] if report else [],
    }


class Decision(BaseModel):
    decision: Literal["approve", "approve_with_edits", "adjust", "reject", "needs_data"]
    score_delta: float | None = Field(default=None, ge=-15, le=15)
    explanation_final: str | None = Field(default=None, max_length=2000)
    reason: str | None = Field(default=None, max_length=2000)


PUBLISHING = {"approve", "approve_with_edits", "adjust"}


@router.post("/{rec_id}")
def decide(rec_id: str, body: Decision, user: Analyst) -> dict[str, Any]:
    reason = (body.reason or "").strip()
    if body.decision in ("adjust", "reject", "needs_data") and len(reason) < 10:
        raise ApiError(
            422,
            "reason_required",
            "Write a reason of at least 10 characters.",
            "Other analysts and the owner will read it.",
        )
    if body.decision == "adjust" and not body.score_delta:
        raise ApiError(422, "delta_required", "Set how much to adjust the score (−15 to +15).")
    if body.decision != "adjust" and body.score_delta:
        raise ApiError(422, "delta_not_allowed", "Only 'Adjust' changes the score.")
    with connect() as conn:
        r = _rec(conn, rec_id)
        if r["status_text"] in ("published", "rejected"):
            raise ApiError(409, "already_decided", f"This was already {r['status_text']}.")
        explanation = (
            (body.explanation_final or "").strip()
            or r["explanation_final"]
            or r["explanation_draft"]
        )
        if body.decision == "approve_with_edits" and not (body.explanation_final or "").strip():
            raise ApiError(422, "explanation_required", "Edit the explanation, or choose Publish.")
        if body.decision in PUBLISHING and not explanation:
            raise ApiError(
                422, "explanation_required", "Write the explanation people will read first."
            )
        warnings: list[str] = []
        if explanation and body.decision in PUBLISHING:
            payload = explanation_payload(
                {**r, "confidence": r["confidence_text"], "category_name": r["category_name"]}
            )
            if body.decision == "adjust" and body.score_delta is not None:
                payload["final_score"] = round(float(r["engine_score"]) + body.score_delta)
            bad = check_numbers(explanation, payload)
            if bad:
                warnings.append(
                    "These numbers aren't in the evidence: " + ", ".join(f"{n:g}" for n in bad[:5])
                )
        final = None
        if body.decision == "adjust" and body.score_delta is not None:
            final = max(0.0, min(100.0, float(r["engine_score"]) + body.score_delta))
        new_status = {"reject": "rejected", "needs_data": "needs_data"}.get(
            body.decision, "published"
        )
        conn.execute(
            """insert into analyst_reviews (recommendation_id, analyst_id, decision, score_delta, reason)
               values (%s,%s,%s,%s,%s)""",
            (rec_id, user.id, body.decision, body.score_delta, reason or None),
        )
        conn.execute(
            """update recommendations set status = %s, reviewed_by = %s,
                   final_score = coalesce(%s, final_score),
                   explanation_final = case when %s then %s else explanation_final end,
                   published_at = case when %s then now() else published_at end
               where id = %s""",
            (
                new_status,
                user.id,
                final,
                body.decision in PUBLISHING,
                explanation,
                new_status == "published",
                rec_id,
            ),
        )
        if body.decision == "needs_data":
            conn.execute(
                """insert into data_tasks (recommendation_id, kind, h3, category_id, notes, created_by)
                   values (%s,'ground_count',%s,%s,%s,%s)""",
                (rec_id, r["h3"], r["category_id"], reason, user.id),
            )
        audit(
            conn,
            user.id,
            f"review_{body.decision}",
            "recommendation",
            rec_id,
            {"from": r["status_text"], "to": new_status, "delta": body.score_delta},
        )
    return {"status": new_status, "final_score": final, "warnings": warnings}


@router.post("/{rec_id}/regenerate-explanation")
def regenerate(rec_id: str, user: Analyst) -> dict[str, Any]:
    with connect() as conn:
        r = _rec(conn, rec_id)
    payload = explanation_payload(
        {**r, "confidence": r["confidence_text"], "category_name": r["category_name"]}
    )
    text, method = draft_explanation(CachedClient(make_client(), use_db=False), payload)
    with connect() as conn:
        conn.execute(
            "update recommendations set explanation_draft = %s where id = %s", (text, rec_id)
        )
        audit(conn, user.id, "regenerate_explanation", "recommendation", rec_id, {"method": method})
    return {"explanation_draft": text, "method": method}


class DataRequest(BaseModel):
    kind: Literal["ground_count", "survey_boost"] = "ground_count"
    notes: str | None = Field(default=None, max_length=1000)


@router.post("/{rec_id}/request-data")
def request_data(rec_id: str, body: DataRequest, user: Analyst) -> dict[str, Any]:
    with connect() as conn:
        r = _rec(conn, rec_id)
        row = conn.execute(
            """insert into data_tasks (recommendation_id, kind, h3, category_id, notes, created_by)
               values (%s,%s,%s,%s,%s,%s) returning id""",
            (rec_id, body.kind, r["h3"], r["category_id"], body.notes, user.id),
        ).fetchone()
        assert row is not None
        audit(conn, user.id, "request_data", "recommendation", rec_id, {"kind": body.kind})
    return {"task_id": str(row["id"]), "kind": body.kind, "h3": r["h3"]}
