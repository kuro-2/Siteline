"""Build the cell report (docs/05 "Cell report shape") from stored rows only.

Every number in the report comes from `scores`, `cell_features`, `places`, `ground_counts`,
`survey_responses` or `rent_observations`, each with its source and date.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import h3

from app.errors import ApiError, not_found
from engine.geo.grid import cell_distance_m, direction, haversine_m
from engine.llm.explain import template_explanation
from engine.repo import Conn
from engine.scoring.config import get_config
from engine.scoring.core import fmt_int

PLURALS = {
    "pharmacy": "pharmacies",
    "cafe": "cafés or tea stalls",
    "salon": "salons or barbers",
    "coaching": "coaching centres",
    "hardware": "hardware stores",
}
SINGULAR = {"cafe": "café or tea stall", "salon": "salon or barber"}
SOURCE_LABEL = {"osm": "OpenStreetMap", "google": "Google Maps", "ground": "Counted on foot"}


def plural(slug: str, name: str) -> str:
    return PLURALS.get(slug, name.lower() + "s")


def singular(slug: str, name: str) -> str:
    return SINGULAR.get(slug, name.lower())


def walk_minutes(slug: str) -> int:
    cfg = get_config()
    return cfg.categories[slug].travel_minutes if slug in cfg.categories else 10


def latest_run(conn: Conn, area_id: str) -> dict[str, Any] | None:
    return conn.execute(
        """select id, data_snapshot_at, created_at, engine_version from model_runs
           where area_id = %s and kind = 'live' order by created_at desc limit 1""",
        (area_id,),
    ).fetchone()


def area_for_cell(conn: Conn, cell: str) -> dict[str, Any]:
    row = conn.execute(
        """select a.id, a.slug, a.name, a.is_published, c.in_area
           from h3_cells c join areas a on a.id = c.area_id where c.h3 = %s""",
        (cell,),
    ).fetchone()
    if not row or not row["is_published"]:
        raise not_found("part of the map", "Pick a hexagon inside the outlined area.")
    if not row["in_area"]:
        raise ApiError(
            404,
            "outside_area",
            f"That spot is just outside {row['name']}.",
            "Move inside the outlined area, or pick another area.",
        )
    return row


def category_by_slug(conn: Conn, slug: str) -> dict[str, Any]:
    row = conn.execute(
        "select id, slug, name, catchment_k from categories where slug = %s and active", (slug,)
    ).fetchone()
    if not row:
        raise ApiError(
            404,
            "unknown_category",
            f"We don't cover '{slug}' yet.",
            "Pick one of the categories in the switcher.",
        )
    return row


def headline(
    slug: str,
    name: str,
    score: float | None,
    band: str,
    feats: dict[str, Any],
    comps: list[dict[str, Any]],
) -> str:
    many, one, mins = plural(slug, name), singular(slug, name), walk_minutes(slug)
    if band == "not_enough_data" or score is None:
        return "We need more data here before we say anything."
    pop = (feats.get("pop_catchment") or {}).get("value")
    mapped = (feats.get("supply_mapped") or {}).get("n") or 0
    if score >= 60:
        if mapped == 0 and pop:
            return f"No {one} within a {mins}-minute walk of about {fmt_int(pop)} people."
        return f"Plenty of people, few {many} within a {mins}-minute walk."
    if score >= 40:
        return f"About as many {many} as a street like this usually has."
    if mapped:
        return f"Already well served: {mapped} {many if mapped != 1 else one} within a {mins}-minute walk."
    return f"Few people within a {mins}-minute walk for a {one} to rely on."


def limits_for(
    slug: str,
    feats: dict[str, Any],
    ground: dict[str, Any] | None,
    survey_n: int,
    rent_n: int,
    has_google: bool,
) -> list[str]:
    out: list[str] = []
    if not ground:
        out.append(
            "No one has counted shops on foot here yet, so we may be missing shops "
            "that aren't on any map."
        )
    if slug == "pharmacy":
        out.append("Informal medicine sellers may not be counted.")
    elif slug == "cafe":
        out.append(
            "Roadside tea stalls and carts are rarely on maps; counts on foot help most here."
        )
    elif slug == "coaching":
        out.append("Home tuition is common and almost never mapped.")
    if survey_n == 0:
        out.append("No neighbours have answered our survey here yet.")
    elif survey_n < 20:
        out.append(
            f"Only {survey_n} neighbours have answered so far, so their answers count for little yet."
        )
    if rent_n == 0:
        out.append("We have no rent observations here yet.")
    elif rent_n < 5:
        out.append(
            f"Rent based on only {rent_n} {'observation' if rent_n == 1 else 'observations'}."
        )
    if not has_google:
        out.append("We haven't checked Google Maps listings for this area yet.")
    out.append(
        "We can't measure rent negotiations, owner skill or service quality, and they matter a lot."
    )
    return out


def competitors(conn: Conn, cell: str, category_id: str, k: int) -> list[dict[str, Any]]:
    disk = list(h3.grid_disk(cell, k))
    lat0, lng0 = h3.cell_to_latlng(cell)
    rows = conn.execute(
        """select p.id, p.source::text as source, p.name, p.business_status, p.rating,
                  p.rating_count, p.content_expired,
                  extensions.st_y(p.geom) as lat, extensions.st_x(p.geom) as lng,
                  (select array_agg(distinct d.source::text) from places d where d.merged_into = p.id) as also
           from places p where p.category_id = %s and p.h3 = any(%s) and p.merged_into is null
             and coalesce(p.business_status, '') <> 'CLOSED_PERMANENTLY'""",
        (category_id, disk),
    ).fetchall()
    out = []
    for r in rows:
        sources = [r["source"], *(r["also"] or [])]
        is_google_only = r["source"] == "google"
        name = r["name"]
        if is_google_only and r["content_expired"]:
            name = None
        out.append(
            {
                "name": name or "Unnamed shop",
                "distance_m": round(haversine_m(lat0, lng0, r["lat"], r["lng"]) / 10) * 10,
                "rating": float(r["rating"])
                if r["rating"] is not None and not r["content_expired"]
                else None,
                "rating_count": r["rating_count"] if not r["content_expired"] else None,
                "source": "+".join(sorted({"osm" if s == "osm" else s for s in sources})),
                "source_label": " + ".join(SOURCE_LABEL.get(s, s) for s in sorted(set(sources))),
                "status": r["business_status"],
            }
        )
    out.sort(key=lambda x: x["distance_m"])
    return out[:25]


def build_report(conn: Conn, cell: str, category_slug: str) -> dict[str, Any]:
    if not h3.is_valid_cell(cell):
        raise ApiError(422, "bad_cell", "That isn't a valid map cell.")
    area = area_for_cell(conn, cell)
    cat = category_by_slug(conn, category_slug)
    run = latest_run(conn, area["id"])
    if not run:
        raise ApiError(
            404, "no_scores_yet", f"We haven't scored {area['name']} yet.", "Check back soon."
        )
    s = conn.execute(
        """select s.score, s.score_low, s.score_high, s.confidence::text as confidence,
                  s.components, f.features
           from scores s join cell_features f
             on f.run_id = s.run_id and f.h3 = s.h3 and f.category_id = s.category_id
           where s.run_id = %s and s.h3 = %s and s.category_id = %s""",
        (run["id"], cell, cat["id"]),
    ).fetchone()
    if not s:
        raise not_found("cell report", "Pick a hexagon inside the outlined area.")
    comps_raw = s["components"] or {}
    items: list[dict[str, Any]] = comps_raw.get("items", []) if isinstance(comps_raw, dict) else []
    feats: dict[str, Any] = s["features"] or {}

    rec = conn.execute(
        """select r.id, r.status::text as status, coalesce(r.final_score, r.engine_score) as score,
                  r.explanation_final, r.published_at, p.display_name
           from recommendations r left join profiles p on p.id = r.reviewed_by
           where r.h3 = %s and r.category_id = %s and r.status = 'published'
           order by r.published_at desc limit 1""",
        (cell, cat["id"]),
    ).fetchone()
    published = rec is not None
    score = float(rec["score"]) if published else float(s["score"])
    band = s["confidence"]
    k = int(cat["catchment_k"])
    disk = list(h3.grid_disk(cell, k))

    ground = conn.execute(
        """select g.count, g.informal_count, g.counted_at, g.surveyor_name from ground_counts g
           where g.category_id = %s and g.h3 = any(%s) order by g.counted_at desc limit 1""",
        (cat["id"], disk),
    ).fetchone()
    survey_feat = feats.get("survey_need") or {}
    survey_n = int(survey_feat.get("n") or 0)
    rent_feat = feats.get("rent_band") or {}
    rent_n = int(rent_feat.get("n") or 0)
    comps_list = competitors(conn, cell, cat["id"], k)
    has_google = (
        conn.execute(
            "select 1 from job_runs where job='ingest.google' and status='succeeded' limit 1"
        ).fetchone()
        is not None
    )

    neighbours = []
    for n in h3.grid_ring(cell, 1):
        ns = conn.execute(
            """select score, confidence::text as confidence from scores
               where run_id = %s and h3 = %s and category_id = %s""",
            (run["id"], n, cat["id"]),
        ).fetchone()
        if ns and ns["confidence"] != "not_enough_data":
            neighbours.append(
                {
                    "h3": n,
                    "score": round(float(ns["score"])),
                    "confidence": ns["confidence"],
                    "direction": direction(cell, n),
                    "distance_m": round(cell_distance_m(cell, n) / 10) * 10,
                }
            )
    neighbours.sort(key=lambda x: -x["score"])

    pop = feats.get("pop_catchment") or {}
    explanation = (
        rec["explanation_final"]
        if published and rec["explanation_final"]
        else template_explanation({"components": items, "confidence": band})
    )
    survey_out = None
    if survey_n:
        share = survey_feat.get("value")
        survey_out = {
            "n": survey_n,
            "share_travel_far": share,
            "travel_minutes": walk_minutes(category_slug),
            "as_of": survey_feat.get("as_of"),
        }
    report = {
        "h3": cell,
        "area": {"slug": area["slug"], "name": area["name"]},
        "category": {"slug": cat["slug"], "name": cat["name"]},
        "score": round(score) if band != "not_enough_data" else None,
        "score_low": round(float(s["score_low"])) if s["score_low"] is not None else None,
        "score_high": round(float(s["score_high"])) if s["score_high"] is not None else None,
        "confidence": band,
        "status": "published" if published else "engine_only",
        "headline": headline(category_slug, cat["name"], score, band, feats, items),
        "explanation": explanation,
        "evidence": {
            "population": {
                "value": pop.get("value"),
                "source": "WorldPop",
                "as_of": pop.get("as_of"),
                "walk_minutes": walk_minutes(category_slug),
            },
            "competitors": comps_list,
            "ground_count": (
                {
                    "value": ground["count"],
                    "informal": ground["informal_count"],
                    "counted_on": ground["counted_at"].date().isoformat(),
                    "by": ground["surveyor_name"] or "Field team",
                }
                if ground
                else None
            ),
            "survey": survey_out,
            "rent_band": (
                {"median_inr_per_sqft": rent_feat.get("value"), "n": rent_n} if rent_n else None
            ),
            "places_as_of": (feats.get("supply_mapped") or {}).get("as_of"),
        },
        "components": [{"name": c["name"], "effect": c["effect"], "why": c["why"]} for c in items],
        "reviewed_by": (
            {
                "name": rec["display_name"] or "Siteline analyst",
                "on": rec["published_at"].date().isoformat(),
            }
            if published and rec["published_at"]
            else None
        ),
        "limits": limits_for(category_slug, feats, ground, survey_n, rent_n, has_google),
        "neighbours": neighbours[:6],
        "data_snapshot_at": run["data_snapshot_at"].date().isoformat(),
    }
    return report


def neighbour_advice(report: dict[str, Any]) -> str | None:
    if report["score"] is None:
        return None
    better = [n for n in report["neighbours"] if n["score"] >= report["score"] + 5]
    if not better:
        return None
    b = better[0]
    return (
        f"{b['distance_m']} m {b['direction']} scores {b['score']} against {report['score']} "
        "here. Open it to see why."
    )


def today() -> date:
    from datetime import UTC, datetime

    return datetime.now(UTC).date()
