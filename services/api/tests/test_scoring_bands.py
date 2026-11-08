from __future__ import annotations

import h3
import pytest

from engine.scoring.confidence import Band, confidence_band
from engine.scoring.config import ScoringConfig
from engine.scoring.recommend import Candidate, select_drafts
from engine.scoring.uncertainty import score_interval
from tests.conftest import make_inputs


def band(cfg: ScoringConfig, **kw: object) -> Band:
    args: dict[str, object] = {
        "interval_width": 10.0,
        "ground_age_days": None,
        "survey_n": 0,
        "has_population": True,
    }
    args.update(kw)
    return confidence_band(cfg=cfg, **args)  # type: ignore[arg-type]


def test_confident_needs_everything(cfg: ScoringConfig) -> None:
    assert band(cfg, ground_age_days=30, survey_n=40, interval_width=20) == Band.CONFIDENT
    # stale ground count → only fairly sure
    assert band(cfg, ground_age_days=200, survey_n=40, interval_width=20) == Band.FAIRLY_SURE
    # too few answers
    assert band(cfg, ground_age_days=30, survey_n=39, interval_width=20) == Band.FAIRLY_SURE
    # too wide
    assert band(cfg, ground_age_days=30, survey_n=60, interval_width=25) == Band.FAIRLY_SURE


def test_fairly_sure_and_below(cfg: ScoringConfig) -> None:
    assert band(cfg, survey_n=20, interval_width=30) == Band.FAIRLY_SURE
    assert band(cfg, ground_age_days=300, interval_width=30) == Band.FAIRLY_SURE
    assert band(cfg, ground_age_days=400, interval_width=30) == Band.EARLY_SIGNAL
    assert band(cfg, survey_n=19, interval_width=30) == Band.EARLY_SIGNAL
    assert band(cfg, interval_width=45) == Band.EARLY_SIGNAL
    assert band(cfg, interval_width=46) == Band.NOT_ENOUGH_DATA
    assert band(cfg, has_population=False) == Band.NOT_ENOUGH_DATA
    assert band(cfg, interval_width=None) == Band.NOT_ENOUGH_DATA


def test_band_order() -> None:
    assert Band.CONFIDENT.rank > Band.FAIRLY_SURE.rank > Band.EARLY_SIGNAL.rank
    assert Band.NOT_ENOUGH_DATA.rank == 0


def test_interval_is_deterministic_and_contains_score(cfg: ScoringConfig) -> None:
    from engine.scoring.core import score_cell

    inp = make_inputs(survey_share=0.4, survey_n=50)
    cat = cfg.category("pharmacy")
    lo, hi = score_interval(inp, cfg, cat)
    assert (lo, hi) == score_interval(inp, cfg, cat)
    s = score_cell(inp, cfg, cat).score
    assert lo <= s <= hi
    assert hi - lo > 0


def test_interval_narrows_with_ground_truth(cfg: ScoringConfig) -> None:
    cat = cfg.category("pharmacy")
    wide = score_interval(make_inputs(ground_correction_sd=0.35), cfg, cat)
    narrow = score_interval(make_inputs(ground_correction_sd=0.05), cfg, cat)
    assert (narrow[1] - narrow[0]) < (wide[1] - wide[0])


def test_mapped_only_cell_can_be_early_signal(cfg: ScoringConfig) -> None:
    lo, hi = score_interval(make_inputs(), cfg, cfg.category("pharmacy"))
    assert band(cfg, interval_width=hi - lo) in (Band.EARLY_SIGNAL, Band.NOT_ENOUGH_DATA)


@pytest.fixture
def cells() -> list[str]:
    origin = h3.latlng_to_cell(26.17, 91.77, 9)
    return sorted(h3.grid_disk(origin, 4))


def test_select_drafts_nms(cells: list[str]) -> None:
    best = cells[0]
    neighbour = next(c for c in h3.grid_disk(best, 1) if c != best)
    far = next(c for c in cells if h3.grid_distance(best, c) >= 4)
    cands = [
        Candidate(best, 90, Band.EARLY_SIGNAL),
        Candidate(neighbour, 88, Band.FAIRLY_SURE),
        Candidate(far, 70, Band.EARLY_SIGNAL),
        Candidate(cells[1], 55, Band.CONFIDENT),  # below threshold
        Candidate(cells[2], 95, Band.NOT_ENOUGH_DATA),  # never recommended
    ]
    picks = select_drafts(cands, threshold=60, k=2, limit=5)
    assert [p.h3 for p in picks] == [best, far]


def test_select_drafts_limit(cells: list[str]) -> None:
    cands = [Candidate(c, 80 - i * 0.1, Band.EARLY_SIGNAL) for i, c in enumerate(cells)]
    assert len(select_drafts(cands, threshold=60, k=0, limit=3)) == 3
    assert select_drafts([], threshold=60, k=1, limit=3) == []
