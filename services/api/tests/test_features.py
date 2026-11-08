from __future__ import annotations

from datetime import date

import h3
import pytest

from engine.features.build import (
    CellRow,
    GroundRow,
    Inputs,
    PlaceRow,
    RentRow,
    ResponseRow,
    build_category,
)
from engine.scoring.config import ScoringConfig

TODAY = date(2026, 11, 8)
CENTRE = h3.latlng_to_cell(26.1808, 91.7894, 9)


@pytest.fixture
def grid() -> dict[str, CellRow]:
    cells: dict[str, CellRow] = {}
    for c in h3.grid_disk(CENTRE, 8):
        in_area = h3.grid_distance(CENTRE, c) <= 2
        cells[c] = CellRow(c, in_area, 1500.0)
    return cells


def test_basic_features(grid: dict[str, CellRow], cfg: ScoringConfig) -> None:
    places = [PlaceRow(CENTRE, "pharmacy", None, place_id="a")]
    data = Inputs(cells=grid, places=places, population_year=2020, osm_as_of=TODAY)
    out = build_category(data, "pharmacy", "Pharmacy", cfg.category("pharmacy"), cfg, TODAY)
    assert set(out) == {c for c, r in grid.items() if r.in_area}
    inp, feats = out[CENTRE]
    assert inp.pop_catchment and inp.pop_catchment > 1500
    assert inp.mapped_count == 1
    assert inp.benchmark_ppo and inp.benchmark_ppo > 0
    assert feats["pop_catchment"]["source"] == "WorldPop"
    assert feats["pop_catchment"]["as_of"] == "2020"
    assert feats["supply_mapped"]["as_of"] == TODAY.isoformat()
    assert feats["ground_correction"]["source"] == "none yet"
    assert inp.hidden_supply_mean == cfg.uncertainty.hidden_supply_mean["none"]
    for f in feats.values():
        assert set(f) == {"value", "source", "as_of", "n"}


def test_missing_population_propagates(grid: dict[str, CellRow], cfg: ScoringConfig) -> None:
    grid = {**grid, CENTRE: CellRow(CENTRE, True, None)}
    out = build_category(
        Inputs(cells=grid, places=[]), "pharmacy", "Pharmacy", cfg.category("pharmacy"), cfg, TODAY
    )
    assert out[CENTRE][0].pop_catchment is None


def test_closed_places_do_not_count(grid: dict[str, CellRow], cfg: ScoringConfig) -> None:
    places = [PlaceRow(CENTRE, "pharmacy", "CLOSED_PERMANENTLY", place_id="x")]
    out = build_category(
        Inputs(cells=grid, places=places),
        "pharmacy",
        "Pharmacy",
        cfg.category("pharmacy"),
        cfg,
        TODAY,
    )
    assert out[CENTRE][0].mapped_count == 0


def test_ground_counts_local_and_area(grid: dict[str, CellRow], cfg: ScoringConfig) -> None:
    places = [PlaceRow(CENTRE, "pharmacy", None, place_id="a")]
    ground = [
        GroundRow(CENTRE, "pharmacy", 3, 2, date(2026, 10, 12)),
        GroundRow(CENTRE, "cafe", 9, 0, date(2026, 10, 12)),
        GroundRow(CENTRE, "pharmacy", 1, 0, date(2024, 1, 1)),
    ]  # too old, ignored
    data = Inputs(cells=grid, places=places, ground=ground)
    out = build_category(data, "pharmacy", "Pharmacy", cfg.category("pharmacy"), cfg, TODAY)
    inp, feats = out[CENTRE]
    assert inp.ground_correction == pytest.approx(2.0)  # (3+1)/(1+1)
    assert inp.ground_age_days == 27
    assert inp.informal_supply == pytest.approx(2.0)
    assert feats["ground_correction"]["source"] == "ground count in catchment"
    # a cell far from the count uses the area median instead
    far = next(c for c, r in grid.items() if r.in_area and h3.grid_distance(CENTRE, c) == 2)
    far_cat = cfg.category("cafe")  # k=2 → reaches CENTRE; use pharmacy k=3 instead
    _ = far_cat
    inp_far = out[far][0]
    assert inp_far.ground_age_days is not None  # within k=3 of CENTRE


def test_area_median_when_no_local_count(cfg: ScoringConfig) -> None:
    centre = CENTRE
    cells = {
        c: CellRow(c, h3.grid_distance(centre, c) <= 6, 1000.0) for c in h3.grid_disk(centre, 9)
    }
    corner = next(c for c, r in cells.items() if r.in_area and h3.grid_distance(centre, c) == 6)
    ground = [GroundRow(centre, "cafe", 4, 0, date(2026, 10, 1))]
    out = build_category(
        Inputs(cells=cells, places=[], ground=ground),
        "cafe",
        "Café",
        cfg.category("cafe"),
        cfg,
        TODAY,
    )
    inp, feats = out[corner]
    assert feats["ground_correction"]["source"] == "area median of ground counts"
    assert inp.ground_correction == pytest.approx(4.0)  # (4+1)/(0+1) capped at 4
    assert inp.ground_age_days is None


def test_survey_post_stratified(grid: dict[str, CellRow], cfg: ScoringConfig) -> None:
    far_ans = {"where_pharmacy": "outside"}
    near_ans = {"where_pharmacy": "in_area", "time_pharmacy": "lt5"}
    responses = [ResponseRow(CENTRE, far_ans, 1.0, TODAY) for _ in range(30)]
    neighbour = next(c for c in h3.grid_disk(CENTRE, 1) if c != CENTRE)
    responses.append(ResponseRow(neighbour, near_ans, 1.0, TODAY))
    responses.append(ResponseRow(neighbour, far_ans, 0.0, TODAY))  # flagged → ignored
    data = Inputs(cells=grid, places=[], responses=responses)
    inp, feats = build_category(data, "pharmacy", "Pharmacy", cfg.category("pharmacy"), cfg, TODAY)[
        CENTRE
    ]
    assert inp.survey_n == 31
    # 30 answers from one cell don't outweigh the single answer from an equally
    # populated neighbour by 30:1 (post-stratification); centre has distance weight 1
    assert inp.survey_share is not None and 0.4 < inp.survey_share < 0.7
    assert feats["survey_need"]["n"] == 31


def test_rent_band(grid: dict[str, CellRow], cfg: ScoringConfig) -> None:
    rents = [RentRow(CENTRE, v, TODAY) for v in (40, 50, 60, 120)]
    data = Inputs(cells=grid, places=[], rents=rents)
    inp, _ = build_category(data, "pharmacy", "Pharmacy", cfg.category("pharmacy"), cfg, TODAY)[
        CENTRE
    ]
    assert inp.rent_n == 4
    assert inp.rent_median == 55
    assert inp.area_rent_q75 == pytest.approx(75.0)


def test_benchmark_override_and_review_pain(grid: dict[str, CellRow], cfg: ScoringConfig) -> None:
    places = [PlaceRow(CENTRE, "pharmacy", None, 3.0, 50, "google", "g1")]
    data = Inputs(cells=grid, places=places, review_pain={"g1": 0.6}, google_as_of=TODAY)
    out = build_category(
        data, "pharmacy", "Pharmacy", cfg.category("pharmacy"), cfg, TODAY, benchmark_override=4000
    )
    inp, feats = out[CENTRE]
    assert inp.benchmark_ppo == 4000
    assert feats["benchmark_ppo"]["source"] == "category setting"
    assert inp.review_pain_share == pytest.approx(0.6)
    assert inp.supply_quality_adj < 1.0  # poorly rated competitor counts less
    assert "Google" in feats["supply_mapped"]["source"]
