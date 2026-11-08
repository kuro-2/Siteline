"""Deterministic scoring. Pure functions only: no I/O, no randomness, no LLM.

score = 50 + gap effect + adjustments, clamped to [0, 100], then capped for tiny
populations. Every effect is recorded as a Component with a plain-language reason, so
the explanation shown to people is built from the same numbers that made the score.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

from engine.scoring.config import CategoryCfg, ScoringConfig


@dataclass(frozen=True)
class Component:
    name: str
    effect: float  # points added to (or removed from) the score
    value: float | None  # the main input number
    why: str  # plain sentence; every number in it is also in this JSON

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class CellInputs:
    """Everything the score needs for one (cell, category). Built by engine/features."""

    category_slug: str
    category_name: str
    pop_catchment: float | None
    supply_quality_adj: float  # distance- and status-weighted mapped competitors
    mapped_count: int  # unweighted mapped competitors in catchment
    ground_correction: float  # ground / mapped ratio (or area median)
    informal_supply: float
    benchmark_ppo: float | None
    survey_share: float | None = None  # share travelling far / leaving the area
    survey_n: int = 0
    rent_median: float | None = None  # ₹ per sqft per month
    rent_n: int = 0
    area_rent_q75: float | None = None
    activity_count: float = 0.0
    review_pain_share: float | None = None
    ground_age_days: int | None = None  # age of the newest ground count in catchment
    ground_correction_sd: float = 0.3  # log-scale spread of the correction
    hidden_supply_mean: float = 1.0  # outlets the map may miss (bootstrap only)
    extra: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class ScoreResult:
    score: float
    components: list[Component]
    supply_est: float
    people_per_outlet: float | None
    gap_ratio: float | None


# ----------------------------------------------------------------- building blocks
def distance_weight(distance_m: float, decay_lambda_m: float) -> float:
    if distance_m < 0:
        raise ValueError("distance cannot be negative")
    if decay_lambda_m <= 0:
        raise ValueError("decay lambda must be positive")
    return math.exp(-distance_m / decay_lambda_m)


def status_factor(status: str | None, factors: dict[str, float]) -> float:
    if not status:
        return factors.get("unknown", 1.0)
    return factors.get(status, factors.get("unknown", 1.0))


def quality_weight(rating: float | None, rating_count: int | None, cfg: ScoringConfig) -> float:
    q = cfg.quality
    if not q.enabled or rating is None or (rating_count or 0) < q.min_rating_count:
        return 1.0
    w = 1.0 + (rating - q.neutral_rating) * q.per_star
    return min(q.max_weight, max(q.min_weight, w))


def ground_correction(ground: float | None, mapped: float, cfg: ScoringConfig) -> float:
    """Ratio of outlets counted on foot to outlets on the map (add-one smoothed)."""
    if ground is None:
        return 1.0
    if ground < 0 or mapped < 0:
        raise ValueError("counts cannot be negative")
    ratio = (ground + 1.0) / (mapped + 1.0)
    g = cfg.ground_correction
    return min(g.max, max(g.min, ratio))


def supply_estimate(
    supply_quality_adj: float, correction: float, informal: float, informal_weight: float
) -> float:
    return max(0.0, supply_quality_adj * correction + informal * informal_weight)


def people_per_outlet(pop: float, supply: float, min_supply: float) -> float:
    return max(0.0, pop) / max(supply, min_supply)


def gap_ratio(ppo: float, benchmark: float, cfg: ScoringConfig) -> float:
    if benchmark <= 0:
        raise ValueError("benchmark must be positive")
    return min(cfg.score.g_cap, max(0.0, ppo / benchmark))


def base_score(g: float, cfg: ScoringConfig) -> float:
    """100 × logistic(α · log g); g = 1 → 50."""
    g = max(g, cfg.score.g_floor)
    return 100.0 / (1.0 + math.exp(-cfg.score.alpha * math.log(g)))


def survey_adjustment(share: float | None, n: int, cfg: ScoringConfig) -> float:
    a = cfg.adjustments.survey_need
    if share is None or n < a.min_n:
        return 0.0
    # scale by evidence: grows linearly from min_n to full_effect_n
    evidence = min(1.0, (n - a.min_n) / max(1, a.full_effect_n - a.min_n) * 0.75 + 0.25)
    # share above neutral pushes up, below pulls down; ±(1 - neutral) maps to ±max
    span = 1.0 - a.neutral_share if share >= a.neutral_share else a.neutral_share
    raw = (share - a.neutral_share) / span
    return round(max(-1.0, min(1.0, raw)) * a.max_points * evidence, 1)


def activity_adjustment(activity: float, weight: float, cfg: ScoringConfig) -> float:
    a = cfg.adjustments.activity_proxy
    if activity <= 0 or weight <= 0:
        return 0.0
    return round(min(1.0, activity / a.saturation) * a.max_points * min(1.0, weight), 1)


def review_pain_adjustment(share: float | None, cfg: ScoringConfig) -> float:
    if share is None:
        return 0.0
    return round(max(0.0, min(1.0, share)) * cfg.adjustments.review_pain.max_points, 1)


def rent_adjustment(
    median: float | None, area_q75: float | None, n: int, cfg: ScoringConfig
) -> float:
    a = cfg.adjustments.rent_band
    if median is None or area_q75 is None or n < a.min_n or area_q75 <= 0:
        return 0.0
    if median <= area_q75:
        return 0.0
    # 0 at the 75th percentile, full penalty at 1.5× it
    over = min(1.0, (median - area_q75) / (0.5 * area_q75))
    return round(-a.max_points * max(over, 0.3), 1)


# ----------------------------------------------------------------- formatting helpers
def fmt_int(x: float) -> str:
    """Indian digit grouping: 1,23,456."""
    n = round(x)
    s = str(abs(n))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        s = ",".join([*groups, tail])
    return ("-" if n < 0 else "") + s


def _plural(word: str, n: float) -> str:
    return word if round(n) == 1 else word + "s"


# ----------------------------------------------------------------- assembly
def score_cell(inp: CellInputs, cfg: ScoringConfig, cat: CategoryCfg) -> ScoreResult:
    """Score one (cell, category). Raises ValueError if population or benchmark is missing."""
    if inp.pop_catchment is None:
        raise ValueError("population is missing for this cell")
    if inp.benchmark_ppo is None or inp.benchmark_ppo <= 0:
        raise ValueError("benchmark people-per-outlet is missing")

    supply = supply_estimate(
        inp.supply_quality_adj, inp.ground_correction, inp.informal_supply, cat.informal_weight
    )
    ppo = people_per_outlet(inp.pop_catchment, supply, cfg.score.min_supply)
    g = gap_ratio(ppo, inp.benchmark_ppo, cfg)
    base = base_score(g, cfg)
    gap_effect = round(base - 50.0, 1)

    noun = inp.category_name.lower()
    comps: list[Component] = []
    if supply < cfg.score.min_supply:
        why = (
            f"No {noun} found within walking distance for about "
            f"{fmt_int(inp.pop_catchment)} people, vs 1 for every "
            f"{fmt_int(inp.benchmark_ppo)} people across the area."
        )
    else:
        why = (
            f"1 {noun} for every {fmt_int(ppo)} people here, vs 1 for every "
            f"{fmt_int(inp.benchmark_ppo)} across the area."
        )
    comps.append(Component("gap", gap_effect, round(g, 2), why))

    s_adj = survey_adjustment(inp.survey_share, inp.survey_n, cfg)
    if s_adj != 0.0 and inp.survey_share is not None:
        pct = round(inp.survey_share * 100)
        comps.append(
            Component(
                "survey_need",
                s_adj,
                pct,
                f"{pct}% of {inp.survey_n} neighbours who answered travel more than "
                f"{cat.travel_minutes} minutes or leave the area for this.",
            )
        )

    a_adj = activity_adjustment(inp.activity_count, cat.activity_weight, cfg)
    if a_adj != 0.0:
        comps.append(
            Component(
                "activity_proxy",
                a_adj,
                round(inp.activity_count),
                f"A busy stretch: {fmt_int(inp.activity_count)} businesses of all kinds nearby "
                "bring walk-in customers.",
            )
        )

    r_adj = review_pain_adjustment(inp.review_pain_share, cfg)
    if r_adj != 0.0 and inp.review_pain_share is not None:
        pct = round(inp.review_pain_share * 100)
        comps.append(
            Component(
                "review_pain",
                r_adj,
                pct,
                f"{pct}% of review themes for nearby competitors are complaints.",
            )
        )

    rent_adj = rent_adjustment(inp.rent_median, inp.area_rent_q75, inp.rent_n, cfg)
    if rent_adj != 0.0 and inp.rent_median is not None:
        comps.append(
            Component(
                "rent_band",
                rent_adj,
                round(inp.rent_median),
                f"Rents here are high for the area: about ₹{fmt_int(inp.rent_median)} per sq ft "
                f"a month, from {inp.rent_n} {_plural('observation', inp.rent_n)}.",
            )
        )

    total = 50.0 + sum(c.effect for c in comps)
    total = max(0.0, min(100.0, total))

    cap = cfg.adjustments.low_population.cap
    if inp.pop_catchment < cat.min_population and total > cap:
        comps.append(
            Component(
                "low_population",
                round(cap - total, 1),
                round(inp.pop_catchment),
                f"Only about {fmt_int(inp.pop_catchment)} people live within walking distance, "
                f"fewer than the {fmt_int(cat.min_population)} a {noun} usually needs.",
            )
        )
        total = cap

    return ScoreResult(
        score=round(total, 1),
        components=comps,
        supply_est=round(supply, 2),
        people_per_outlet=round(ppo, 1),
        gap_ratio=round(g, 3),
    )
