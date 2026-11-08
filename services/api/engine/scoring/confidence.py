"""Confidence band from data coverage, never from the score itself."""

from __future__ import annotations

from enum import StrEnum

from engine.scoring.config import ScoringConfig


class Band(StrEnum):
    NOT_ENOUGH_DATA = "not_enough_data"
    EARLY_SIGNAL = "early_signal"
    FAIRLY_SURE = "fairly_sure"
    CONFIDENT = "confident"

    @property
    def rank(self) -> int:
        return ORDER.index(self)


ORDER = [Band.NOT_ENOUGH_DATA, Band.EARLY_SIGNAL, Band.FAIRLY_SURE, Band.CONFIDENT]


def confidence_band(
    *,
    interval_width: float | None,
    ground_age_days: int | None,
    survey_n: int,
    has_population: bool,
    cfg: ScoringConfig,
) -> Band:
    """Evaluated top-down; the first band whose rules all hold wins."""
    if not has_population or interval_width is None:
        return Band.NOT_ENOUGH_DATA
    c = cfg.confidence
    g = cfg.ground_correction
    fresh_ground = ground_age_days is not None and ground_age_days <= g.fresh_days
    usable_ground = ground_age_days is not None and ground_age_days <= g.usable_days

    if (
        fresh_ground
        and survey_n >= c.confident.survey_n
        and interval_width <= c.confident.max_width
    ):
        return Band.CONFIDENT
    if (usable_ground or survey_n >= c.fairly_sure.survey_n) and (
        interval_width <= c.fairly_sure.max_width
    ):
        return Band.FAIRLY_SURE
    if interval_width <= c.early_signal.max_width:
        return Band.EARLY_SIGNAL
    return Band.NOT_ENOUGH_DATA
