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

from engine.backtest.metrics import (
    calibration_by_decile,
    precision_recall_at_k,
    random_precision,
    rank,
    roc_auc,
)
from engine.features.build import CellRow, Inputs, PlaceRow, build_category
from engine.scoring.config import ScoringConfig, get_config
from engine.scoring.core import score_cell
from engine.sources.categories import CategoryDef

KS = (3, 5, 10)


@dataclass
class CategoryResult:
    slug: str
    name: str
    cells: int
    positives: int
    metrics: dict[str, Any]
    beats_baselines: bool


def counts_to_rows(
    by_category: dict[str, dict[str, int]], all_businesses: dict[str, int]
) -> list[PlaceRow]:
    """Turn per-cell counts into PlaceRows (one per outlet). Businesses not in any of our
    categories still count for the activity proxy."""
    rows: list[PlaceRow] = []
    in_cats: dict[str, int] = {}
    for slug, cells in by_category.items():
        for cell, n in cells.items():
            rows.extend(PlaceRow(cell, slug, None, source="osm") for _ in range(max(0, n)))
            in_cats[cell] = in_cats.get(cell, 0) + max(0, n)
    for cell, n in all_businesses.items():
        rows.extend(
            PlaceRow(cell, None, None, source="osm")
            for _ in range(max(0, n - in_cats.get(cell, 0)))
        )
    return rows


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
    past: dict[str, dict[str, int]],  # {category slug: {cell: count at as_of}}
    future: dict[str, dict[str, int]],  # {category slug: {cell: count at evaluate_on}}
    past_activity: dict[str, int],  # {cell: all businesses at as_of}
    as_of: date,
    cfg: ScoringConfig,
    population_year: int | None,
) -> list[CategoryResult]:
    data = Inputs(
        cells=cells,
        places=counts_to_rows(past, past_activity),
        population_year=population_year,
        osm_as_of=as_of,
    )
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
        before, after = past.get(cat.slug, {}), future.get(cat.slug, {})
        if not scores:
            out.append(
                CategoryResult(
                    cat.slug,
                    cat.name,
                    0,
                    0,
                    {
                        "not_testable": "none were mapped inside the area on the as-of date",
                        "random_precision": 0.0,
                        "calibration": [],
                        "outlets_as_of": sum(before.values()),
                        "outlets_evaluate_on": sum(after.values()),
                    },
                    False,
                )
            )
            continue
        # A cell is positive if it had more outlets of this kind on evaluate_on than on as_of
        # (net new, still mapped). Counts can't tell an opening from a late mapping.
        positives = {c for c in scores if after.get(c, 0) > before.get(c, 0)}
        m, beats = evaluate_category(scores, pops, positives)
        m["outlets_as_of"] = sum(v for c, v in before.items() if c in scores)
        m["outlets_evaluate_on"] = sum(v for c, v in after.items() if c in scores)
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
        if "not_testable" in m:
            lines.append(
                f"| {r.name} | – | – | – | – | – | – | – | not testable: {m['not_testable']} |"
            )
            continue
        lines.append(
            f"| {r.name} | {r.cells} | {r.positives} | {m.get('precision@5', '–')} | "
            f"{m.get('population_only_precision@5', '–')} | {m['random_precision']} | "
            f"{m.get('roc_auc') if m.get('roc_auc') is not None else '–'} | "
            f"{m.get('population_only_roc_auc') if m.get('population_only_roc_auc') is not None else '–'} | "
            f"{'yes' if r.beats_baselines else 'no'} |"
        )
    growth = [
        (r.name, r.metrics.get("outlets_as_of", 0), r.metrics.get("outlets_evaluate_on", 0))
        for r in results
    ]
    lines += ["", "## How much the map itself changed", ""]
    for name, a, b in growth:
        lines.append(
            f"- {name}: {a} mapped on {as_of.isoformat()}, {b} on {evaluate_on.isoformat()}."
        )
    if any(a == 0 or b >= 2 * max(a, 1) for _, a, b in growth):
        lines += [
            "",
            '**Warning: the map grew a lot over this period.** Most "new outlets" are probably '
            "shops that already existed and were mapped late, not shops that opened. Treat these "
            "results as a test of the pipeline, not of the model. A fair test needs either a "
            "stable map period or ground counts repeated over time.",
        ]
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
