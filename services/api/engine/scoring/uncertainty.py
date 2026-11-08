"""Bootstrap interval around a score by perturbing its uncertain inputs.

Seeded, so the same inputs always give the same interval (deterministic and testable).
"""

from __future__ import annotations

import math
from dataclasses import replace

import numpy as np

from engine.scoring.config import CategoryCfg, ScoringConfig
from engine.scoring.core import CellInputs, score_cell

INTERVAL = (10.0, 90.0)  # 80% interval: "likely between low and high"


def score_interval(inp: CellInputs, cfg: ScoringConfig, cat: CategoryCfg) -> tuple[float, float]:
    u = cfg.uncertainty
    rng = np.random.default_rng(u.seed)
    n = u.samples

    pop_mult = rng.normal(1.0, u.population_rel_sd, n).clip(0.3, 2.0)
    corr_mult = np.exp(rng.normal(0.0, inp.ground_correction_sd, n))
    hidden = (
        rng.exponential(inp.hidden_supply_mean, n) if inp.hidden_supply_mean > 0 else np.zeros(n)
    )
    if inp.survey_share is not None and inp.survey_n > 0:
        p = inp.survey_share
        sd = max(u.survey_min_sd, math.sqrt(p * (1 - p) / inp.survey_n))
        shares = rng.normal(p, sd, n).clip(0.0, 1.0)
    else:
        shares = np.full(n, np.nan)

    g = cfg.ground_correction
    out = np.empty(n)
    for i in range(n):
        assert inp.pop_catchment is not None
        sample = replace(
            inp,
            pop_catchment=inp.pop_catchment * float(pop_mult[i]),
            supply_quality_adj=inp.supply_quality_adj + float(hidden[i]),
            ground_correction=min(g.max, max(g.min, inp.ground_correction * float(corr_mult[i]))),
            survey_share=None if math.isnan(shares[i]) else float(shares[i]),
        )
        out[i] = score_cell(sample, cfg, cat).score
    lo, hi = np.percentile(out, INTERVAL)
    return round(float(lo), 1), round(float(hi), 1)
