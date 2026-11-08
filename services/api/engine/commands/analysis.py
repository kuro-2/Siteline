"""`engine backtest run`, `engine explain draft`, `engine outcomes scan`, `engine survey create`."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from typing import Any

from engine.backtest.run import region_for, report_markdown, results_json, run_backtest_pure
from engine.commands.score import engine_version
from engine.db import connect
from engine.features.build import CellRow
from engine.jobs import job_run
from engine.llm.client import CachedClient, make_client
from engine.llm.explain import draft_explanation
from engine.repo import get_area, load_categories
from engine.scoring.config import get_config
from engine.settings import REPO_ROOT, get_settings
from engine.sources.ohsome import OhsomeClient
from engine.survey import default_questions


# ------------------------------------------------------------------------------ backtest
def backtest(area_slug: str, as_of: date, evaluate_on: date, dry_run: bool) -> dict[str, Any]:
    s = get_settings()
    cfg = get_config()
    with connect() as conn:
        area = get_area(conn, area_slug)
        cats = load_categories(conn)
        cell_rows = conn.execute(
            "select h3, in_area, population, population_source_year from h3_cells where area_id=%s",
            (area.id,),
        ).fetchall()
    cells = {
        r["h3"]: CellRow(
            r["h3"], r["in_area"], float(r["population"]) if r["population"] is not None else None
        )
        for r in cell_rows
    }
    if not any(c.population for c in cells.values()):
        raise RuntimeError(
            "No population yet. Run: uv run engine ingest worldpop --area " + area_slug
        )
    pop_year = max((r["population_source_year"] or 0) for r in cell_rows) or None
    client = OhsomeClient(s.ohsome_url, s.user_agent, REPO_ROOT / "data" / "cache" / "ohsome")
    region = region_for(cells)
    args = {"area": area_slug, "as_of": as_of.isoformat(), "evaluate_on": evaluate_on.isoformat()}
    with job_run("backtest.run", args, dry_run=dry_run) as run:
        if dry_run:
            run.set("would_call_ohsome", 2)
            return {"calls": 2, "cost_usd": 0}
        past = client.centroids(region, as_of.isoformat())
        future = client.centroids(region, evaluate_on.isoformat())
        run.set("osm_past", len(past))
        run.set("osm_future", len(future))
        results = run_backtest_pure(
            cells=cells,
            cats=cats,
            past=past,
            future=future,
            as_of=as_of,
            cfg=cfg,
            population_year=pop_year,
        )
        version = engine_version()
        md = report_markdown(area.name, as_of, evaluate_on, results, version)
        metrics = results_json(results)
        out_dir = REPO_ROOT / "docs" / "backtests"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{datetime.now(UTC).date().isoformat()}-{area_slug}.md"
        path.write_text(md, encoding="utf-8")
        with connect() as conn:
            mr = conn.execute(
                """insert into model_runs (engine_version, params, area_id, data_snapshot_at, kind)
                   values (%s,%s,%s,%s,'backtest') returning id""",
                (
                    version,
                    json.dumps(cfg.model_dump()),
                    area.id,
                    datetime.combine(as_of, datetime.min.time(), UTC),
                ),
            ).fetchone()
            assert mr is not None
            conn.execute(
                """insert into backtests (run_id, area_id, as_of, evaluated_on, metrics, report_md)
                   values (%s,%s,%s,%s,%s,%s)""",
                (mr["id"], area.id, as_of, evaluate_on, json.dumps(metrics), md),
            )
        run.set("categories_beating_baselines", metrics["categories_beating_baselines"])
        return {"report": str(path), **metrics}


# ------------------------------------------------------------------------------ explain
def explanation_payload(row: dict[str, Any]) -> dict[str, Any]:
    comps = row["components"] or {}
    items = comps.get("items", []) if isinstance(comps, dict) else comps
    return {
        "category": row["category_name"],
        "score": round(float(row["engine_score"])),
        "likely_between": [
            round(float(row["score_low"] or 0)),
            round(float(row["score_high"] or 0)),
        ],
        "confidence": row["confidence"],
        "components": [{"name": c["name"], "effect": c["effect"], "why": c["why"]} for c in items],
    }


def explain_drafts(
    area_slug: str, dry_run: bool, only_missing: bool = True, rec_id: str | None = None
) -> dict[str, Any]:
    client = CachedClient(make_client(), use_db=True)
    with connect() as conn:
        area = get_area(conn, area_slug)
        where = "r.area_id = %s and r.status in ('draft','in_review','needs_data')"
        params: list[Any] = [area.id]
        if only_missing and rec_id is None:
            where += " and r.explanation_draft is null"
        if rec_id:
            where += " and r.id = %s"
            params.append(rec_id)
        rows = conn.execute(
            f"""select r.id, r.engine_score, r.confidence::text as confidence, cat.name as category_name,
                       s.components, s.score_low, s.score_high
                from recommendations r join categories cat on cat.id = r.category_id
                join scores s on s.run_id = r.run_id and s.h3 = r.h3 and s.category_id = r.category_id
                where {where}""",
            params,
        ).fetchall()
    with job_run(
        "explain.draft", {"area": area_slug, "provider": client.provider}, dry_run=dry_run
    ) as run:
        for row in rows:
            text, method = draft_explanation(client, explanation_payload(row))
            run.count(f"method.{method}")
            if not dry_run:
                with connect() as conn:
                    conn.execute(
                        "update recommendations set explanation_draft=%s where id=%s",
                        (text, row["id"]),
                    )
        run.set("recommendations", len(rows))
        return dict(run.counts)


# ------------------------------------------------------------------------------ outcomes
def outcomes_scan(area_slug: str, dry_run: bool) -> dict[str, Any]:
    """Compare the two most recent OSM snapshots inside published cells."""
    with connect() as conn:
        area = get_area(conn, area_slug)
        dates = [
            r["d"]
            for r in conn.execute(
                """select distinct snapshot_on as d from place_snapshots ps
               join h3_cells c on c.h3 = ps.h3 where c.area_id = %s order by d desc limit 2""",
                (area.id,),
            ).fetchall()
        ]
        if len(dates) < 2:
            with job_run("outcomes.scan", {"area": area_slug}, dry_run=dry_run) as run:
                run.set("note", "need two snapshots; run ingest again next week")
            return {"note": "Need at least two weekly snapshots to compare."}
        new, old = dates
        rows = conn.execute(
            """with pub as (select id, h3, category_id from recommendations
                            where area_id = %(a)s and status = 'published'),
                    cur as (select place_id, h3, category_id from place_snapshots where snapshot_on = %(n)s),
                    prev as (select place_id, h3, category_id from place_snapshots where snapshot_on = %(o)s)
               select 'opened' as event, cur.place_id, pub.id as rec_id from cur
                 join pub on pub.h3 = cur.h3 and pub.category_id = cur.category_id
                 where cur.place_id not in (select place_id from prev)
               union all
               select 'closed', prev.place_id, pub.id from prev
                 join pub on pub.h3 = prev.h3 and pub.category_id = prev.category_id
                 where prev.place_id not in (select place_id from cur)""",
            {"a": area.id, "n": new, "o": old},
        ).fetchall()
    with job_run(
        "outcomes.scan", {"area": area_slug, "new": str(new), "old": str(old)}, dry_run=dry_run
    ) as run:
        for r in rows:
            run.count(r["event"])
        if not dry_run and rows:
            with connect() as conn, conn.cursor() as cur:
                cur.executemany(
                    """insert into outcomes (place_id, recommendation_id, event, observed_on, source)
                       values (%s,%s,%s,%s,'snapshot diff')""",
                    [(r["place_id"], r["rec_id"], r["event"], new) for r in rows],
                )
        return dict(run.counts)


# ------------------------------------------------------------------------------ survey
def create_survey(area_slug: str, slug: str | None, title: str) -> dict[str, Any]:
    with connect() as conn:
        area = get_area(conn, area_slug)
        cats = [c.slug for c in load_categories(conn)]
        qs = default_questions(cats)
        survey_slug = slug or f"{area_slug}-2026"
        row = conn.execute(
            """insert into surveys (slug, area_id, title, questions, version, is_active)
               values (%s,%s,%s,%s,1,true)
               on conflict (slug) do update set questions = excluded.questions,
                   version = surveys.version + case when surveys.questions = excluded.questions
                                                    then 0 else 1 end
               returning slug, version""",
            (survey_slug, area.id, title, json.dumps(qs)),
        ).fetchone()
    assert row is not None
    return {"slug": row["slug"], "version": row["version"], "questions": len(qs)}


def today_utc() -> date:
    return datetime.now(UTC).date()
