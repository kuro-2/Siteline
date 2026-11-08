from __future__ import annotations

import math

import pytest

from engine.scoring import core
from engine.scoring.config import ScoringConfig, config_hash, load_config
from tests.conftest import make_inputs


def test_config_loads_and_has_all_categories(cfg: ScoringConfig) -> None:
    assert set(cfg.categories) == {"pharmacy", "cafe", "salon", "coaching", "hardware"}
    assert cfg.max_catchment_k == 6
    assert len(config_hash()) == 12
    with pytest.raises(KeyError):
        cfg.category("bakery")
    assert load_config().score.alpha == cfg.score.alpha


def test_distance_weight() -> None:
    assert core.distance_weight(0, 600) == 1.0
    assert core.distance_weight(600, 600) == pytest.approx(math.exp(-1))
    with pytest.raises(ValueError):
        core.distance_weight(-1, 600)
    with pytest.raises(ValueError):
        core.distance_weight(10, 0)


def test_status_factor(cfg: ScoringConfig) -> None:
    f = cfg.status_factor
    assert core.status_factor("OPERATIONAL", f) == 1.0
    assert core.status_factor("CLOSED_TEMPORARILY", f) == 0.3
    assert core.status_factor("CLOSED_PERMANENTLY", f) == 0.0
    assert core.status_factor(None, f) == f["unknown"]
    assert core.status_factor("WEIRD", f) == f["unknown"]


def test_quality_weight(cfg: ScoringConfig) -> None:
    assert core.quality_weight(None, None, cfg) == 1.0
    assert core.quality_weight(2.0, 5, cfg) == 1.0  # too few reviews
    assert core.quality_weight(4.0, 100, cfg) == 1.0
    assert core.quality_weight(2.0, 100, cfg) == pytest.approx(0.7)
    assert core.quality_weight(1.0, 100, cfg) == cfg.quality.min_weight
    assert core.quality_weight(5.0, 100, cfg) == pytest.approx(1.15)
    disabled = cfg.model_copy(deep=True)
    disabled.quality.enabled = False
    assert core.quality_weight(1.0, 1000, disabled) == 1.0


def test_ground_correction(cfg: ScoringConfig) -> None:
    assert core.ground_correction(None, 3, cfg) == 1.0
    assert core.ground_correction(3, 3, cfg) == 1.0
    # zero mapped: smoothed, not infinite
    assert core.ground_correction(3, 0, cfg) == 4.0
    assert core.ground_correction(1, 0, cfg) == 2.0
    assert core.ground_correction(0, 9, cfg) == cfg.ground_correction.min
    with pytest.raises(ValueError):
        core.ground_correction(-1, 0, cfg)


def test_supply_and_ppo() -> None:
    assert core.supply_estimate(2.0, 1.5, 2.0, 0.5) == 4.0
    assert core.supply_estimate(0.0, 1.0, 0.0, 0.5) == 0.0
    assert core.people_per_outlet(1000, 0, 0.5) == 2000
    assert core.people_per_outlet(-5, 1, 0.5) == 0


def test_gap_ratio_and_base_score(cfg: ScoringConfig) -> None:
    assert core.gap_ratio(3900, 3900, cfg) == 1.0
    assert core.gap_ratio(100000, 3900, cfg) == cfg.score.g_cap
    assert core.gap_ratio(0, 3900, cfg) == 0.0
    with pytest.raises(ValueError):
        core.gap_ratio(10, 0, cfg)
    assert core.base_score(1.0, cfg) == pytest.approx(50.0)
    assert core.base_score(2.0, cfg) > 75
    assert core.base_score(0.5, cfg) < 25
    # zero gap is floored, not -inf
    assert 0 < core.base_score(0.0, cfg) < 1
    # symmetric in log space
    assert core.base_score(2.0, cfg) + core.base_score(0.5, cfg) == pytest.approx(100.0)


def test_survey_adjustment(cfg: ScoringConfig) -> None:
    a = cfg.adjustments.survey_need
    assert core.survey_adjustment(None, 100, cfg) == 0.0
    assert core.survey_adjustment(0.9, a.min_n - 1, cfg) == 0.0  # too few answers
    full = core.survey_adjustment(1.0, a.full_effect_n, cfg)
    assert full == a.max_points
    assert core.survey_adjustment(0.0, a.full_effect_n, cfg) == -a.max_points
    assert core.survey_adjustment(a.neutral_share, 100, cfg) == 0.0
    small = core.survey_adjustment(1.0, a.min_n, cfg)
    assert 0 < small < full


def test_activity_review_rent(cfg: ScoringConfig) -> None:
    assert core.activity_adjustment(0, 1, cfg) == 0.0
    assert core.activity_adjustment(1000, 1.0, cfg) == cfg.adjustments.activity_proxy.max_points
    assert core.activity_adjustment(75, 1.0, cfg) == pytest.approx(4.0)
    assert core.activity_adjustment(75, 0.0, cfg) == 0.0
    assert core.review_pain_adjustment(None, cfg) == 0.0
    assert core.review_pain_adjustment(0.5, cfg) == 3.0
    assert core.review_pain_adjustment(2.0, cfg) == 6.0
    assert core.rent_adjustment(None, 50, 10, cfg) == 0.0
    assert core.rent_adjustment(60, 50, 1, cfg) == 0.0  # too few observations
    assert core.rent_adjustment(40, 50, 10, cfg) == 0.0
    assert core.rent_adjustment(80, 50, 10, cfg) == -10.0
    assert core.rent_adjustment(51, 50, 10, cfg) == -3.0  # minimum 30% of penalty
    assert core.rent_adjustment(60, 0, 10, cfg) == 0.0


def test_fmt_int_indian_grouping() -> None:
    assert core.fmt_int(7100) == "7,100"
    assert core.fmt_int(123456) == "1,23,456"
    assert core.fmt_int(12345678) == "1,23,45,678"
    assert core.fmt_int(999) == "999"
    assert core.fmt_int(-1500) == "-1,500"


def test_score_cell_undersupplied(cfg: ScoringConfig) -> None:
    inp = make_inputs(pop_catchment=14200, supply_quality_adj=2.0)
    res = core.score_cell(inp, cfg, cfg.category("pharmacy"))
    assert res.people_per_outlet == pytest.approx(7100)
    assert res.score > 70
    gap = res.components[0]
    assert gap.name == "gap"
    assert "7,100" in gap.why and "3,900" in gap.why
    assert res.score == pytest.approx(50 + sum(c.effect for c in res.components), abs=0.11)


def test_score_cell_oversupplied(cfg: ScoringConfig) -> None:
    inp = make_inputs(pop_catchment=8000, supply_quality_adj=6.0)
    assert core.score_cell(inp, cfg, cfg.category("pharmacy")).score < 35


def test_score_cell_zero_supply(cfg: ScoringConfig) -> None:
    inp = make_inputs(supply_quality_adj=0.0, mapped_count=0)
    res = core.score_cell(inp, cfg, cfg.category("pharmacy"))
    assert res.gap_ratio == cfg.score.g_cap
    assert "No pharmacy found" in res.components[0].why
    assert res.score <= 100


def test_score_cell_tiny_population_is_capped(cfg: ScoringConfig) -> None:
    inp = make_inputs(pop_catchment=900, supply_quality_adj=0.0, benchmark_ppo=300)
    res = core.score_cell(inp, cfg, cfg.category("pharmacy"))
    assert res.score == cfg.adjustments.low_population.cap
    assert res.components[-1].name == "low_population"
    assert res.components[-1].effect < 0


def test_score_cell_zero_population(cfg: ScoringConfig) -> None:
    inp = make_inputs(pop_catchment=0.0, supply_quality_adj=1.0)
    res = core.score_cell(inp, cfg, cfg.category("pharmacy"))
    assert res.score < 5


def test_score_cell_missing_data_raises(cfg: ScoringConfig) -> None:
    with pytest.raises(ValueError):
        core.score_cell(make_inputs(pop_catchment=None), cfg, cfg.category("pharmacy"))
    with pytest.raises(ValueError):
        core.score_cell(make_inputs(benchmark_ppo=None), cfg, cfg.category("pharmacy"))
    with pytest.raises(ValueError):
        core.score_cell(make_inputs(benchmark_ppo=0), cfg, cfg.category("pharmacy"))


def test_score_cell_all_adjustments(cfg: ScoringConfig) -> None:
    inp = make_inputs(
        survey_share=0.41,
        survey_n=64,
        activity_count=200,
        review_pain_share=0.5,
        rent_median=80,
        rent_n=6,
        area_rent_q75=50,
    )
    res = core.score_cell(inp, cfg, cfg.category("pharmacy"))
    names = [c.name for c in res.components]
    assert names == ["gap", "survey_need", "activity_proxy", "review_pain", "rent_band"]
    assert "41%" in res.components[1].why and "64" in res.components[1].why
    assert "₹80" in res.components[4].why and "6 observations" in res.components[4].why
    assert 0 <= res.score <= 100
    d = res.components[0].to_dict()
    assert set(d) == {"name", "effect", "value", "why"}


def test_score_never_leaves_bounds(cfg: ScoringConfig) -> None:
    for pop in (0, 10, 1e3, 1e5, 1e7):
        for supply in (0, 0.1, 1, 50):
            for share in (None, 0.0, 1.0):
                inp = make_inputs(
                    pop_catchment=pop,
                    supply_quality_adj=supply,
                    survey_share=share,
                    survey_n=100,
                    activity_count=500,
                )
                s = core.score_cell(inp, cfg, cfg.category("cafe")).score
                assert 0 <= s <= 100
