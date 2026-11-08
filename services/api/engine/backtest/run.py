"""`engine backtest run`: score the area as it looked on --as-of, then check which cells
got new outlets that still existed on --evaluate-on.

Limits (always printed in the report): no surveys or ground counts existed for the past,
so only the mapped-data model is tested; OSM "new" can mean "newly mapped".
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

import h3
from shapely.ops import unary_union

from engine.backtest.metrics import (
    calibration_by_decile,
    precision_recall_at_k,
    random_precision,
    rank,
    roc_auc,
)
from engine.features.build import CellRow, Inputs, PlaceRow, build_category
from engine.geo.grid import cell_polygon
from engine.scoring.config import ScoringConfig, get_config
from engine.scoring.core import score_cell
from engine.sources.categories import CategoryDef, is_business, match_osm
from engine.sources.osm import OsmPlace

KS = (3, 5, 10)


@dataclass
class CategoryResult:
    slug: str
    name: str
    cells: int
    positives: int
    metrics: dict[str, Any]
    beats_baselines: bool


def places_to_rows(
    places: list[OsmPlace], cats: list[CategoryDef], cells: set[str], resolution: int
) -> tuple[list[PlaceRow], dict[str, tuple[str, str | None]]]:
    rows: list[PlaceRow] = []
    index: dict[str, tuple[str, str | None]] = {}
    for p in places:
        if not is_business(p.tags):
            continue
        cell = h3.latlng_to_cell(p.lat, p.lng, resolution)
        if cell not in cells:
            continue
        cat = match_osm(p.tags, cats)
        rows.append(
            PlaceRow(cell, cat.slug if cat else None, None, source="osm", place_id=p.source_id)
        )
        index[p.source_id] = (cell, cat.slug if cat else None)
    return rows, index


def evaluate_category(
    scores: dict[str, float], population: dict[str, float], positives: set[str]
) -> tuple[dict[str, Any], bool]:
    ranked = rank(scores)
    pop_ranked = rank(population)
    n, n_pos = len(scores), len(positives)
    m: dict[str, Any] = {
        "cells": n,
        "positive_cells": n_pos,
        "random_precision": round(random_precision(n, n_pos), 3),
    }
    wins = 0
    for k in KS:
        if k > n:
            continue
        p, r = precision_recall_at_k(ranked, positives, k)
        pp, _ = precision_recall_at_k(pop_ranked, positives, k)
        m[f"precision@{k}"] = round(p, 3)
        m[f"recall@{k}"] = round(r, 3)
        m[f"population_only_precision@{k}"] = round(pp, 3)
        if k == 5 and p > pp and p > m["random_precision"]:
            wins += 1
    auc = roc_auc(scores, positives)
    m["roc_auc"] = round(auc, 3) if auc is not None else None
    pop_auc = roc_auc(population, positives)
    m["population_only_roc_auc"] = round(pop_auc, 3) if pop_auc is not None else None
    m["calibration"] = calibration_by_decile(scores, positives)
    return m, wins > 0


def run_backtest_pure(
    *,
    cells: dict[str, CellRow],
    cats: list[CategoryDef],
    past: list[OsmPlace],
    future: list[OsmPlace],
    as_of: date,
    cfg: ScoringConfig,
    population_year: int | None,
) -> list[CategoryResult]:
    grid = set(cells)
    past_rows, past_idx = places_to_rows(past, cats, grid, cfg.grid.resolution)
    _, future_idx = places_to_rows(future, cats, grid, cfg.grid.resolution)
    data = Inputs(cells=cells, places=past_rows, population_year=population_year, osm_as_of=as_of)
    out: list[CategoryResult] = []
    for cat in cats:
        if cat.slug not in cfg.categories:
            continue
        ccfg = cfg.category(cat.slug)
        feats = build_category(data, cat.slug, cat.name, ccfg, cfg, as_of)
        scores: dict[str, float] = {}
        pops: dict[str, float] = {}
        for cell, (inp, _) in feats.items():
            if inp.pop_catchment is None or not inp.benchmark_ppo:
                continue
            scores[cell] = score_cell(inp, cfg, ccfg).score
            pops[cell] = inp.pop_catchment
        # a cell is positive if a new outlet of this category appeared in it and survived
        positives = {
            c
            for oid, (c, slug) in future_idx.items()
            if slug == cat.slug and oid not in past_idx and c in scores
        }
        if not scores:
            continue
        m, beats = evaluate_category(scores, pops, positives)
        out.append(CategoryResult(cat.slug, cat.name, len(scores), len(positives), m, beats))
    return out


def report_markdown(
    area_name: str,
    as_of: date,
    evaluate_on: date,
    results: list[CategoryResult],
    engine_version: str,
) -> str:
    wins = sum(1 for r in results if r.beats_baselines)
    lines = [
        f"# Backtest: {area_name}, {as_of.isoformat()} → {evaluate_on.isoformat()}",
        "",
        f"Engine version `{engine_version}`. Generated {datetime.now(UTC).date().isoformat()}.",
        "",
        "We scored every cell using only what OpenStreetMap showed on "
        f"{as_of.isoformat()}, then checked which cells got a new outlet of that kind that was "
        f"still mapped on {evaluate_on.isoformat()}.",
        "",
        f"**Result: the model beat both baselines (random and population-only) on "
        f"precision@5 for {wins} of {len(results)} categories.** "
        + (
            "That clears the bar for showing it publicly (3 of 5)."
            if wins >= 3
            else "That does not clear the 3-of-5 bar. Publish fewer categories, "
            "or gather ground counts first."
        ),
        "",
        "| Category | Cells | Cells with a new outlet | Precision@5 | Population-only P@5 | Random | AUC | Pop-only AUC | Beats both |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for r in results:
        m = r.metrics
        lines.append(
            f"| {r.name} | {r.cells} | {r.positives} | {m.get('precision@5', '–')} | "
            f"{m.get('population_only_precision@5', '–')} | {m['random_precision']} | "
            f"{m.get('roc_auc') if m.get('roc_auc') is not None else '–'} | "
            f"{m.get('population_only_roc_auc') if m.get('population_only_roc_auc') is not None else '–'} | "
            f"{'yes' if r.beats_baselines else 'no'} |"
        )
    lines += [
        "",
        "## What this test can't tell us",
        "",
        "- There were no resident surveys or ground counts in the past, so this only tests the "
        "map-data part of the model. Those inputs may help or hurt.",
        '- In OpenStreetMap, a "new" shop may simply be an old shop someone mapped late. '
        "Guwahati's map coverage is uneven, so busy, well-mapped streets look like they "
        '"grew" more.',
        "- Population comes from the nearest WorldPop year, not the as-of date.",
        "- With few new outlets per category, a single shop changes precision a lot. Treat small "
        "differences as noise.",
        "",
        "## Calibration (share of cells that got a new outlet, by score band)",
        "",
    ]
    for r in results:
        cal = ", ".join(
            f"{b['from']}–{b['to']}: {b['positives']}/{b['cells']}"
            for b in r.metrics["calibration"]
        )
        lines.append(f"- **{r.name}**: {cal or 'no data'}")
    lines.append("")
    return "\n".join(lines)


def region_for(cells: dict[str, CellRow]) -> Any:
    return unary_union([cell_polygon(c) for c in cells])


def results_json(results: list[CategoryResult]) -> dict[str, Any]:
    return {
        "categories": {
            r.slug: {
                "name": r.name,
                "positives": r.positives,
                **r.metrics,
                "beats_baselines": r.beats_baselines,
            }
            for r in results
        },
        "categories_beating_baselines": sum(1 for r in results if r.beats_baselines),
        "good_enough_to_publish": sum(1 for r in results if r.beats_baselines) >= 3,
    }


def dumps(results: list[CategoryResult]) -> str:
    return json.dumps(results_json(results))


__all__ = ["CategoryResult", "get_config", "report_markdown", "run_backtest_pure"]
