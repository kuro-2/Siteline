"""`engine features build` and `engine score run`."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, date, datetime
from typing import Any

from engine.db import connect
from engine.features.build import (
    CellRow,
    GroundRow,
    Inputs,
    PlaceRow,
    RentRow,
    ResponseRow,
    build_category,
)
from engine.jobs import job_run
from engine.repo import Conn, get_area, load_categories
from engine.scoring.confidence import Band, confidence_band
from engine.scoring.config import config_hash, get_config
from engine.scoring.core import CellInputs, score_cell
from engine.scoring.recommend import Candidate, select_drafts
from engine.scoring.uncertainty import score_interval
from engine.settings import REPO_ROOT


def engine_version() -> str:
    try:
        sha = (
            subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            ).stdout.strip()
            or "nogit"
        )
    except OSError:
        sha = "nogit"
    return f"{sha}+cfg.{config_hash()}"


def load_inputs(conn: Conn, area_id: str, today: date) -> Inputs:
    cells = {
        r["h3"]: CellRow(
            r["h3"], r["in_area"], float(r["population"]) if r["population"] is not None else None
        )
        for r in conn.execute(
            "select h3, in_area, population from h3_cells where area_id = %s", (area_id,)
        ).fetchall()
    }
    year_row = conn.execute(
        "select max(population_source_year) as y from h3_cells where area_id = %s", (area_id,)
    ).fetchone()
    places = [
        PlaceRow(
            r["h3"],
            r["slug"],
            r["business_status"],
            float(r["rating"]) if r["rating"] is not None else None,
            r["rating_count"],
            r["source"],
            str(r["id"]),
        )
        for r in conn.execute(
            """select p.id, p.h3, cat.slug, p.business_status, p.rating, p.rating_count,
                      p.source::text as source
               from places p join h3_cells c on c.h3 = p.h3
               left join categories cat on cat.id = p.category_id
               where c.area_id = %s and p.merged_into is null""",
            (area_id,),
        ).fetchall()
    ]
    as_of = {
        r["source"]: r["d"]
        for r in conn.execute(
            """select p.source::text as source, max(p.last_seen_at)::date as d from places p
               join h3_cells c on c.h3 = p.h3 where c.area_id = %s group by 1""",
            (area_id,),
        ).fetchall()
    }
    ground = [
        GroundRow(r["h3"], r["slug"], r["count"], r["informal_count"], r["counted_at"].date())
        for r in conn.execute(
            """select g.h3, cat.slug, g.count, g.informal_count, g.counted_at
               from ground_counts g join categories cat on cat.id = g.category_id
               join h3_cells c on c.h3 = g.h3 where c.area_id = %s""",
            (area_id,),
        ).fetchall()
    ]
    responses = [
        ResponseRow(
            r["h3"],
            r["answers"],
            0.0
            if r["excluded"] or (r["fraud_flags"] and r["cleared_by"] is None)
            else float(r["weight"]),
            r["submitted_at"].date(),
        )
        for r in conn.execute(
            """select sr.h3, sr.answers, sr.weight, sr.excluded, sr.fraud_flags, sr.cleared_by,
                      sr.submitted_at
               from survey_responses sr join surveys s on s.id = sr.survey_id
               where s.area_id = %s""",
            (area_id,),
        ).fetchall()
    ]
    rents = [
        RentRow(r["h3"], r["monthly_rent_inr"] / r["area_sqft"], r["observed_on"])
        for r in conn.execute(
            """select ro.h3, ro.monthly_rent_inr, ro.area_sqft, ro.observed_on
               from rent_observations ro join h3_cells c on c.h3 = ro.h3
               where c.area_id = %s and ro.area_sqft is not null""",
            (area_id,),
        ).fetchall()
    ]
    pain = {}
    for r in conn.execute(
        """select t.place_id, t.themes from place_review_themes t
           join places p on p.id = t.place_id join h3_cells c on c.h3 = p.h3
           where c.area_id = %s""",
        (area_id,),
    ).fetchall():
        themes = r["themes"] or []
        total = sum(int(t.get("mentions", 0)) for t in themes)
        neg = sum(int(t.get("mentions", 0)) for t in themes if float(t.get("sentiment", 0)) < 0)
        if total:
            pain[str(r["place_id"])] = neg / total
    _ = today
    return Inputs(
        cells=cells,
        places=places,
        ground=ground,
        responses=responses,
        rents=rents,
        review_pain=pain,
        population_year=year_row["y"] if year_row else None,
        osm_as_of=as_of.get("osm"),
        google_as_of=as_of.get("google"),
    )


def score_inputs(
    inp: CellInputs, slug: str
) -> tuple[float, float | None, float | None, Band, list[dict[str, Any]], dict[str, Any]]:
    cfg = get_config()
    cat = cfg.category(slug)
    if inp.pop_catchment is None or not inp.benchmark_ppo:
        return 0.0, None, None, Band.NOT_ENOUGH_DATA, [], {}
    res = score_cell(inp, cfg, cat)
    lo, hi = score_interval(inp, cfg, cat)
    band = confidence_band(
        interval_width=hi - lo,
        ground_age_days=inp.ground_age_days,
        survey_n=inp.survey_n,
        has_population=True,
        cfg=cfg,
    )
    extra = {
        "supply_est": res.supply_est,
        "people_per_outlet": res.people_per_outlet,
        "gap_ratio": res.gap_ratio,
    }
    return res.score, lo, hi, band, [c.to_dict() for c in res.components], extra


def run_scoring(
    area_slug: str,
    dry_run: bool,
    *,
    kind: str = "live",
    today: date | None = None,
    inputs: Inputs | None = None,
    create_drafts: bool = True,
) -> dict[str, Any]:
    cfg = get_config()
    today = today or datetime.now(UTC).date()
    with connect() as conn:
        area = get_area(conn, area_slug)
        cats = load_categories(conn)
        data = inputs or load_inputs(conn, area.id, today)
        benchmarks = {
            r["slug"]: r["people_per_outlet_benchmark"]
            for r in conn.execute(
                "select slug, people_per_outlet_benchmark from categories"
            ).fetchall()
        }

    results: dict[str, dict[str, Any]] = {}
    with job_run("score.run", {"area": area_slug, "kind": kind}, dry_run=dry_run) as run:
        for c in cats:
            if c.slug not in cfg.categories:
                run.count("skipped_categories")
                continue
            feats = build_category(
                data,
                c.slug,
                c.name,
                cfg.category(c.slug),
                cfg,
                today,
                benchmark_override=benchmarks.get(c.slug),
            )
            rows = {}
            for cell, (inp, fjson) in feats.items():
                s, lo, hi, band, comps, extra = score_inputs(inp, c.slug)
                rows[cell] = {
                    "score": s,
                    "low": lo,
                    "high": hi,
                    "band": band,
                    "components": comps,
                    "features": fjson,
                    "extra": extra,
                }
                run.count(f"band.{band.value}")
            results[c.slug] = {"cat": c, "rows": rows}
            run.count("cells_scored", len(rows))

        drafts: dict[str, list[Candidate]] = {}
        for slug, r in results.items():
            cands = [Candidate(h, v["score"], v["band"]) for h, v in r["rows"].items()]
            drafts[slug] = (
                select_drafts(
                    cands,
                    threshold=cfg.score.draft_threshold,
                    k=r["cat"].catchment_k,
                    limit=cfg.score.max_drafts_per_category,
                )
                if create_drafts
                else []
            )
            run.set(f"drafts.{slug}", len(drafts[slug]))

        if dry_run:
            return {"counts": dict(run.counts), "results": results, "drafts": drafts}

        with connect() as conn, conn.cursor() as cur:
            mr = conn.execute(
                """insert into model_runs (engine_version, params, area_id, data_snapshot_at, kind)
                   values (%s, %s, %s, %s, %s) returning id""",
                (
                    engine_version(),
                    json.dumps(cfg.model_dump()),
                    area.id,
                    datetime.combine(today, datetime.min.time(), UTC),
                    kind,
                ),
            ).fetchone()
            assert mr is not None
            run_id = str(mr["id"])
            for slug, r in results.items():
                cat_id = r["cat"].id
                cur.executemany(
                    "insert into cell_features (run_id, h3, category_id, features) values (%s,%s,%s,%s)",
                    [
                        (run_id, h, cat_id, json.dumps(v["features"], default=str))
                        for h, v in r["rows"].items()
                    ],
                )
                cur.executemany(
                    """insert into scores (run_id, h3, category_id, score, score_low, score_high,
                                           confidence, components)
                       values (%s,%s,%s,%s,%s,%s,%s,%s)""",
                    [
                        (
                            run_id,
                            h,
                            cat_id,
                            v["score"],
                            v["low"],
                            v["high"],
                            v["band"].value,
                            json.dumps({"items": v["components"], **v["extra"]}),
                        )
                        for h, v in r["rows"].items()
                    ],
                )
                if kind == "live":
                    # older drafts for this category that nobody touched are superseded
                    cur.execute(
                        """delete from recommendations where area_id = %s and category_id = %s
                           and status = 'draft'
                           and not exists (select 1 from analyst_reviews ar
                                           where ar.recommendation_id = recommendations.id)""",
                        (area.id, cat_id),
                    )
                    for d in drafts[slug]:
                        cur.execute(
                            """insert into recommendations (run_id, area_id, category_id, h3,
                                   engine_score, confidence, status)
                               values (%s,%s,%s,%s,%s,%s,'draft')""",
                            (run_id, area.id, cat_id, d.h3, d.score, d.band.value),
                        )
            run.set("run_id", run_id)
        return {"counts": dict(run.counts), "run_id": run_id, "results": results, "drafts": drafts}
