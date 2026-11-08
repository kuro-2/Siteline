"""`engine` command line. Every command takes --area and --dry-run where it makes sense.

uv run engine --help
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Annotated, Any

import httpx
import typer

from engine.log import configure
from engine.settings import MissingSetting, get_settings

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Nukkad data engine.")
area_app = typer.Typer(no_args_is_help=True, help="Areas (pilot boundary).")
geo_app = typer.Typer(no_args_is_help=True, help="H3 grid.")
ingest_app = typer.Typer(no_args_is_help=True, help="Pull data from sources.")
google_app = typer.Typer(no_args_is_help=True, help="Google Places maintenance.")
features_app = typer.Typer(no_args_is_help=True, help="Per-cell features.")
score_app = typer.Typer(no_args_is_help=True, help="Scores and draft recommendations.")
backtest_app = typer.Typer(no_args_is_help=True, help="Backtests.")
explain_app = typer.Typer(no_args_is_help=True, help="Plain-language explanations.")
outcomes_app = typer.Typer(no_args_is_help=True, help="Outcome tracking.")
survey_app = typer.Typer(no_args_is_help=True, help="Resident surveys.")
for name, sub in [
    ("area", area_app),
    ("geo", geo_app),
    ("ingest", ingest_app),
    ("google", google_app),
    ("features", features_app),
    ("score", score_app),
    ("backtest", backtest_app),
    ("explain", explain_app),
    ("outcomes", outcomes_app),
    ("survey", survey_app),
]:
    app.add_typer(sub, name=name)

AreaOpt = Annotated[str, typer.Option("--area", help="Area slug")]
DryOpt = Annotated[bool, typer.Option("--dry-run", help="Print what would happen; call nothing")]


def _default_area() -> str:
    return get_settings().pilot_area_slug


def _print(obj: Any) -> None:
    typer.echo(json.dumps(obj, indent=2, default=str, ensure_ascii=False))


@app.callback()
def main(verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False) -> None:
    import logging

    configure(json=False, level=logging.DEBUG if verbose else logging.INFO)


def _run(fn: Any, *args: Any, **kwargs: Any) -> None:
    try:
        _print(fn(*args, **kwargs))
    except MissingSetting as e:
        typer.secho(str(e), fg="red", err=True)
        raise typer.Exit(2) from e
    except (RuntimeError, ValueError, LookupError) as e:
        typer.secho(str(e), fg="red", err=True)
        raise typer.Exit(1) from e
    except httpx.HTTPError as e:
        typer.secho(
            f"A data source didn't answer properly: {e}. Try again later.", fg="red", err=True
        )
        raise typer.Exit(3) from e
    finally:
        from engine.db import close_pool

        close_pool()


# ----------------------------------------------------------------- area / geo
@area_app.command("load")
def area_load(
    slug: Annotated[str, typer.Option(help="Short id, e.g. pilot")] = "",
    name: Annotated[str, typer.Option(help="Locality name shown to people")] = "",
    geojson: Annotated[Path | None, typer.Option(help="Boundary GeoJSON file")] = None,
    publish: Annotated[bool, typer.Option(help="Make the area public")] = True,
    dry_run: DryOpt = False,
) -> None:
    """Load (or update) an area from a GeoJSON boundary."""
    from engine.commands.area import load_area

    s = get_settings()
    path = geojson or s.repo_path(s.pilot_boundary_path)
    if not name and not s.pilot_area_name:
        typer.secho("Give --name or set PILOT_AREA_NAME in .env", fg="red", err=True)
        raise typer.Exit(2)
    _run(load_area, slug or s.pilot_area_slug, name or s.pilot_area_name, path, publish, dry_run)


@geo_app.command("build-grid")
def build_grid(area: AreaOpt = "", dry_run: DryOpt = False) -> None:
    """Fill h3_cells for the area (cells inside + a buffer ring for full catchments)."""
    from engine.commands.area import build_area_grid

    _run(build_area_grid, area or _default_area(), dry_run)


# ----------------------------------------------------------------- ingest
@ingest_app.command("osm")
def ingest_osm(
    area: AreaOpt = "",
    dry_run: DryOpt = False,
    no_cache: Annotated[bool, typer.Option("--no-cache")] = False,
) -> None:
    """Shops and amenities from OpenStreetMap (free, cached)."""
    from engine.commands.ingest import ingest_osm as fn

    _run(fn, area or _default_area(), dry_run, use_cache=not no_cache)


@ingest_app.command("worldpop")
def ingest_worldpop(
    area: AreaOpt = "",
    dry_run: DryOpt = False,
    raster: Annotated[str, typer.Option(help="Override WORLDPOP_RASTER_PATH")] = "",
) -> None:
    """Population per cell from the WorldPop raster."""
    from engine.commands.ingest import ingest_worldpop as fn

    _run(fn, area or _default_area(), dry_run, raster or None)


@ingest_app.command("google")
def ingest_google(area: AreaOpt = "", dry_run: DryOpt = False) -> None:
    """Google Places (PAID beyond free tier). Dry run unless GOOGLE_INGEST_CONFIRMED=true."""
    from engine.commands.ingest import ingest_google as fn

    _run(fn, area or _default_area(), dry_run)


@ingest_app.command("ohsome")
def ingest_ohsome(
    area: AreaOpt = "",
    on: Annotated[str, typer.Option(help="Date, YYYY-MM-DD")] = "2023-06-01",
    dry_run: DryOpt = False,
) -> None:
    """Fetch (and cache) per-cell OSM counts as they were on a date. Used by backtests."""
    from engine.db import connect
    from engine.repo import get_area, grid_cells, load_categories
    from engine.settings import REPO_ROOT
    from engine.sources.ohsome import OhsomeClient, category_filter

    def fn() -> dict[str, Any]:
        s = get_settings()
        with connect() as conn:
            a = get_area(conn, area or _default_area())
            cells = [c["h3"] for c in grid_cells(conn, a.id)]
            cats = load_categories(conn)
        if dry_run:
            return {"calls": len(cats), "cost_usd": 0}
        client = OhsomeClient(s.ohsome_url, s.user_agent, REPO_ROOT / "data" / "cache" / "ohsome")
        out = {}
        for cat in cats:
            counts = client.counts_by_cell(cells, category_filter(cat), [on])
            out[cat.slug] = sum(v.get(on, 0) for v in counts.values())
        return {"date": on, "outlets": out}

    _run(fn)


@ingest_app.command("kobo")
def ingest_kobo(
    dry_run: DryOpt = False,
    no_photos: Annotated[bool, typer.Option("--no-photos")] = False,
) -> None:
    """Ground counts from KoboToolbox."""
    from engine.commands.kobo import ingest_kobo as fn

    _run(fn, dry_run, with_photos=not no_photos)


@ingest_app.command("dedupe")
def ingest_dedupe(area: AreaOpt = "", dry_run: DryOpt = False) -> None:
    """Merge the same shop seen in several sources."""
    from engine.commands.ingest import dedupe

    _run(dedupe, area or _default_area(), dry_run)


@ingest_app.command("report")
def ingest_report(area: AreaOpt = "") -> None:
    """Places per category and source (the category mapping report)."""
    from engine.commands.ingest import category_report

    _run(category_report, area or _default_area())


@google_app.command("expire")
def google_expire(dry_run: DryOpt = False) -> None:
    """Clear Google content older than GOOGLE_CACHE_DAYS (run daily)."""
    from engine.commands.ingest import google_expire as fn

    _run(fn, dry_run)


# ----------------------------------------------------------------- features / score
@features_app.command("build")
def features_build(area: AreaOpt = "") -> None:
    """Compute features for every cell and category and print a summary (stores nothing;
    `engine score run` stores features and scores together in one model run)."""
    from engine.commands.score import run_scoring

    def fn() -> dict[str, Any]:
        out = run_scoring(area or _default_area(), dry_run=True, create_drafts=False)
        return out["counts"]

    _run(fn)


@score_app.command("run")
def score_run(area: AreaOpt = "", dry_run: DryOpt = False) -> None:
    """Features → scores → draft recommendations, in a new model run."""
    from engine.commands.score import run_scoring

    def fn() -> dict[str, Any]:
        out = run_scoring(area or _default_area(), dry_run)
        drafts = {k: [(d.h3, d.score, d.band.value) for d in v] for k, v in out["drafts"].items()}
        return {"counts": out["counts"], "run_id": out.get("run_id"), "drafts": drafts}

    _run(fn)


@backtest_app.command("run")
def backtest_run(
    area: AreaOpt = "",
    as_of: Annotated[str, typer.Option("--as-of")] = "2023-06-01",
    evaluate_on: Annotated[str, typer.Option("--evaluate-on")] = "2025-06-01",
    dry_run: DryOpt = False,
) -> None:
    """Score the past, check against what opened since. Writes docs/backtests/<date>.md."""
    from engine.commands.analysis import backtest

    _run(
        backtest,
        area or _default_area(),
        date.fromisoformat(as_of),
        date.fromisoformat(evaluate_on),
        dry_run,
    )


@explain_app.command("draft")
def explain_draft(
    area: AreaOpt = "",
    dry_run: DryOpt = False,
    all_: Annotated[bool, typer.Option("--all", help="Redo existing drafts too")] = False,
) -> None:
    """Draft plain-language explanations for recommendations (LLM_PROVIDER)."""
    from engine.commands.analysis import explain_drafts

    _run(explain_drafts, area or _default_area(), dry_run, only_missing=not all_)


@outcomes_app.command("scan")
def outcomes_scan(area: AreaOpt = "", dry_run: DryOpt = False) -> None:
    """Detect opened/closed places in published cells (monthly)."""
    from engine.commands.analysis import outcomes_scan as fn

    _run(fn, area or _default_area(), dry_run)


@survey_app.command("create")
def survey_create(
    area: AreaOpt = "",
    slug: Annotated[str, typer.Option(help="Survey slug (default <area>-2026)")] = "",
    title: Annotated[str, typer.Option()] = "What's missing near you?",
) -> None:
    """Create or update the resident survey for an area."""
    from engine.commands.analysis import create_survey

    _run(create_survey, area or _default_area(), slug or None, title)


@app.command("privacy-purge")
def privacy_purge(
    days: Annotated[int, typer.Option(help="Keep hashes this many days")] = 365,
    dry_run: DryOpt = False,
) -> None:
    """Remove device and network hashes from survey answers older than --days."""
    from engine.db import connect
    from engine.jobs import job_run

    def fn() -> dict[str, Any]:
        with job_run("privacy.purge", {"days": days}, dry_run=dry_run) as run, connect() as conn:
            where = "submitted_at < now() - make_interval(days => %s) and (device_hash is not null or ip_hash is not null)"
            n = conn.execute(
                f"select count(*) as n from survey_responses where {where}", (days,)
            ).fetchone()
            run.set("rows", n["n"] if n else 0)
            if not dry_run:
                conn.execute(
                    f"update survey_responses set device_hash = null, ip_hash = null where {where}",
                    (days,),
                )
            return dict(run.counts)

    _run(fn)


@app.command("keepalive")
def keepalive() -> None:
    """Tiny query so the free Supabase project doesn't pause."""
    from engine.db import connect

    def fn() -> dict[str, Any]:
        with connect() as conn:
            row = conn.execute("select now() as now").fetchone()
        return {"ok": True, "db_time": row["now"] if row else None}

    _run(fn)


if __name__ == "__main__":
    app()
