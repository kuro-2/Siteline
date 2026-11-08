"""Per-(cell, category) features. Pure: takes loaded rows, returns CellInputs + feature JSON.

Every feature is stored as {"value", "source", "as_of", "n"} so each number shown to people
can be traced back to its source rows and date (CLAUDE.md rule 5).
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import h3

from engine.geo.grid import cell_distance_m
from engine.scoring.config import CategoryCfg, ScoringConfig
from engine.scoring.core import (
    CellInputs,
    distance_weight,
    people_per_outlet,
    quality_weight,
    status_factor,
    supply_estimate,
)
from engine.survey import need_indicator


@dataclass(frozen=True)
class CellRow:
    h3: str
    in_area: bool
    population: float | None


@dataclass(frozen=True)
class PlaceRow:
    h3: str
    category_slug: str | None
    business_status: str | None
    rating: float | None = None
    rating_count: int | None = None
    source: str = "osm"
    place_id: str = ""


@dataclass(frozen=True)
class GroundRow:
    h3: str
    category_slug: str
    count: int
    informal_count: int
    counted_on: date


@dataclass(frozen=True)
class ResponseRow:
    h3: str
    answers: dict[str, Any]
    weight: float  # 0 for flagged-and-not-cleared or excluded
    submitted_on: date


@dataclass(frozen=True)
class RentRow:
    h3: str
    inr_per_sqft: float
    observed_on: date


@dataclass
class Inputs:
    cells: dict[str, CellRow]
    places: list[PlaceRow]
    ground: list[GroundRow] = field(default_factory=list)
    responses: list[ResponseRow] = field(default_factory=list)
    rents: list[RentRow] = field(default_factory=list)
    review_pain: dict[str, float] = field(default_factory=dict)  # place_id -> negative share
    population_year: int | None = None
    osm_as_of: date | None = None
    google_as_of: date | None = None


def _feature(
    value: Any, source: str, as_of: date | str | None, n: int | None = None
) -> dict[str, Any]:
    return {
        "value": value,
        "source": source,
        "as_of": as_of.isoformat() if isinstance(as_of, date) else as_of,
        "n": n,
    }


def _latest_ground(
    rows: list[GroundRow], slug: str, today: date, usable_days: int
) -> dict[str, GroundRow]:
    latest: dict[str, GroundRow] = {}
    for g in rows:
        if g.category_slug != slug or (today - g.counted_on).days > usable_days:
            continue
        cur = latest.get(g.h3)
        if cur is None or g.counted_on > cur.counted_on:
            latest[g.h3] = g
    return latest


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    idx = (len(s) - 1) * q
    lo, hi = int(idx), min(int(idx) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (idx - lo)


def build_category(
    data: Inputs,
    slug: str,
    name: str,
    cat: CategoryCfg,
    cfg: ScoringConfig,
    today: date,
    benchmark_override: float | None = None,
) -> dict[str, tuple[CellInputs, dict[str, Any]]]:
    """Return {h3: (CellInputs, features_json)} for every in-area cell."""
    k = cat.catchment_k
    lam = cat.decay_lambda_m
    grid = data.cells
    places_by_cell: dict[str, list[PlaceRow]] = defaultdict(list)
    all_by_cell: dict[str, int] = defaultdict(int)
    for p in data.places:
        all_by_cell[p.h3] += 1
        if p.category_slug == slug:
            places_by_cell[p.h3].append(p)

    ground = _latest_ground(data.ground, slug, today, cfg.ground_correction.usable_days)
    ratios = [(g.count + 1.0) / (len(places_by_cell.get(c, [])) + 1.0) for c, g in ground.items()]
    area_ratio = statistics.median(ratios) if ratios else None
    # spread on the log scale, like the bootstrap that uses it
    area_ratio_sd = (
        max(0.15, statistics.pstdev([math.log(r) for r in ratios])) if len(ratios) >= 2 else 0.3
    )

    # responses per cell for post-stratification
    resp_by_cell: dict[str, list[ResponseRow]] = defaultdict(list)
    for r in data.responses:
        resp_by_cell[r.h3].append(r)

    rents_by_cell: dict[str, list[float]] = defaultdict(list)
    for rr in data.rents:
        rents_by_cell[rr.h3].append(rr.inr_per_sqft)
    area_rents = [v for c, vs in rents_by_cell.items() if c in grid and grid[c].in_area for v in vs]
    area_q75 = _percentile(area_rents, 0.75)

    interim: dict[str, dict[str, Any]] = {}
    for cell_id, cell in grid.items():
        if not cell.in_area:
            continue
        catch = [c for c in h3.grid_disk(cell_id, k) if c in grid]
        weights = {
            c: distance_weight(cell_distance_m(cell_id, c) if c != cell_id else 0.0, lam)
            for c in catch
        }
        pops = [grid[c].population for c in catch]
        has_pop = all(p is not None for p in pops) and cell.population is not None
        pop_c = sum((grid[c].population or 0.0) * weights[c] for c in catch) if has_pop else None

        supply_mapped = 0.0
        supply_q = 0.0
        mapped_count = 0
        pain_vals: list[float] = []
        for c in catch:
            for p in places_by_cell.get(c, []):
                sf = status_factor(p.business_status, cfg.status_factor)
                if sf == 0:
                    continue
                mapped_count += 1
                supply_mapped += weights[c] * sf
                supply_q += weights[c] * sf * quality_weight(p.rating, p.rating_count, cfg)
                if p.place_id in data.review_pain:
                    pain_vals.append(data.review_pain[p.place_id])

        local_ground = [ground[c] for c in catch if c in ground]
        if local_ground:
            g_total = sum(g.count for g in local_ground)
            m_total = sum(len(places_by_cell.get(g.h3, [])) for g in local_ground)
            correction = min(
                cfg.ground_correction.max,
                max(cfg.ground_correction.min, (g_total + 1.0) / (m_total + 1.0)),
            )
            corr_sd = 0.1
            corr_source = "ground count in catchment"
            hidden_key = "local"
            newest = max(g.counted_on for g in local_ground)
            ground_age: int | None = (today - newest).days
        elif area_ratio is not None:
            correction = min(cfg.ground_correction.max, max(cfg.ground_correction.min, area_ratio))
            corr_sd = area_ratio_sd
            corr_source = "area median of ground counts"
            hidden_key = "area"
            newest = None
            ground_age = None
        else:
            correction, corr_sd, corr_source = 1.0, 0.25, "none yet"
            hidden_key, newest, ground_age = "none", None, None

        informal = sum(g.informal_count * weights[g.h3] for g in local_ground)

        # survey: post-stratified by cell population
        num = den = 0.0
        n_resp = 0
        last_resp: date | None = None
        for c in catch:
            rs = resp_by_cell.get(c, [])
            usable = [(r, need_indicator(r.answers, slug, cat.travel_minutes)) for r in rs]
            usable = [(r, v) for r, v in usable if v is not None and r.weight > 0]
            if not usable:
                continue
            cell_pop = grid[c].population or 1.0
            per_resp = cell_pop / len(usable) * weights[c]
            for r, v in usable:
                assert v is not None
                w = per_resp * r.weight
                num += w * v
                den += w
                n_resp += 1
                last_resp = r.submitted_on if last_resp is None else max(last_resp, r.submitted_on)
        share = num / den if den > 0 else None

        rent_vals = [v for c in catch for v in rents_by_cell.get(c, [])]
        rent_med = statistics.median(rent_vals) if rent_vals else None
        activity = sum(all_by_cell.get(c, 0) * weights[c] for c in catch)
        pain = statistics.mean(pain_vals) if pain_vals else None

        interim[cell_id] = {
            "pop": pop_c,
            "supply_mapped": supply_mapped,
            "supply_q": supply_q,
            "mapped_count": mapped_count,
            "correction": correction,
            "corr_sd": corr_sd,
            "corr_source": corr_source,
            "hidden": cfg.uncertainty.hidden_supply_mean.get(hidden_key, 1.0),
            "ground_newest": newest,
            "ground_age": ground_age,
            "ground_n": len(local_ground),
            "informal": informal,
            "share": share,
            "n_resp": n_resp,
            "last_resp": last_resp,
            "rent_med": rent_med,
            "rent_n": len(rent_vals),
            "activity": activity,
            "pain": pain,
            "pain_n": len(pain_vals),
        }

    # benchmark: people per outlet across the whole area (total population of in-area cells
    # / estimated outlets located in them). "1 for every 3,900 people across the area."
    area_pop = 0.0
    area_supply = 0.0
    pop_known = True
    for cell_id, cell in grid.items():
        if not cell.in_area:
            continue
        if cell.population is None:
            pop_known = False
            continue
        area_pop += cell.population
        for p in places_by_cell.get(cell_id, []):
            area_supply += status_factor(p.business_status, cfg.status_factor) * quality_weight(
                p.rating, p.rating_count, cfg
            )
        g_here = ground.get(cell_id)
        if g_here:
            area_supply += g_here.informal_count * cat.informal_weight
    area_correction = area_ratio if area_ratio is not None else 1.0
    area_supply *= max(cfg.ground_correction.min, min(cfg.ground_correction.max, area_correction))
    benchmark_n = round(area_supply)  # outlets behind the benchmark, for the feature record
    if benchmark_override:
        benchmark: float | None = float(benchmark_override)
    elif pop_known and area_pop > 0 and area_supply >= cfg.score.min_supply:
        benchmark = area_pop / area_supply
    else:
        benchmark = None  # no outlets of this kind anywhere in the area: nothing to compare to

    sources = f"OpenStreetMap{' + Google' if data.google_as_of else ''}"
    places_as_of = (
        max(d for d in (data.osm_as_of, data.google_as_of) if d)
        if (data.osm_as_of or data.google_as_of)
        else None
    )
    out: dict[str, tuple[CellInputs, dict[str, Any]]] = {}
    for cell_id, v in interim.items():
        supply_est = supply_estimate(
            v["supply_q"], v["correction"], v["informal"], cat.informal_weight
        )
        ppo = (
            people_per_outlet(v["pop"], supply_est, cfg.score.min_supply)
            if v["pop"] is not None
            else None
        )
        inputs = CellInputs(
            category_slug=slug,
            category_name=name,
            pop_catchment=v["pop"],
            supply_quality_adj=v["supply_q"],
            mapped_count=v["mapped_count"],
            ground_correction=v["correction"],
            informal_supply=v["informal"],
            benchmark_ppo=benchmark,
            survey_share=v["share"],
            survey_n=v["n_resp"],
            rent_median=v["rent_med"],
            rent_n=v["rent_n"],
            area_rent_q75=area_q75,
            activity_count=v["activity"],
            review_pain_share=v["pain"],
            ground_age_days=v["ground_age"],
            ground_correction_sd=v["corr_sd"],
            hidden_supply_mean=v["hidden"],
        )
        feats = {
            "pop_catchment": _feature(
                round(v["pop"]) if v["pop"] is not None else None,
                "WorldPop",
                str(data.population_year) if data.population_year else None,
            ),
            "supply_mapped": _feature(
                round(v["supply_mapped"], 2), sources, places_as_of, v["mapped_count"]
            ),
            "supply_quality_adj": _feature(
                round(v["supply_q"], 2), sources, places_as_of, v["mapped_count"]
            ),
            "ground_correction": _feature(
                round(v["correction"], 3), v["corr_source"], v["ground_newest"], v["ground_n"]
            ),
            "informal_supply": _feature(
                round(v["informal"], 2), "Field ground counts", v["ground_newest"], v["ground_n"]
            ),
            "supply_est": _feature(round(supply_est, 2), "derived", places_as_of),
            "people_per_outlet": _feature(
                round(ppo, 1) if ppo is not None else None, "derived", places_as_of
            ),
            "benchmark_ppo": _feature(
                round(benchmark, 1) if benchmark else None,
                "whole area" if not benchmark_override else "category setting",
                places_as_of,
                benchmark_n,
            ),
            "survey_need": _feature(
                round(v["share"], 3) if v["share"] is not None else None,
                "Resident survey",
                v["last_resp"],
                v["n_resp"],
            ),
            "rent_band": _feature(
                round(v["rent_med"], 1) if v["rent_med"] is not None else None,
                "Rent observations",
                None,
                v["rent_n"],
            ),
            "activity_proxy": _feature(round(v["activity"], 1), sources, places_as_of),
            "review_pain": _feature(
                round(v["pain"], 3) if v["pain"] is not None else None,
                "Review themes",
                None,
                v["pain_n"],
            ),
            "ground_age_days": _feature(v["ground_age"], "Field ground counts", v["ground_newest"]),
        }
        out[cell_id] = (inputs, feats)
    return out
