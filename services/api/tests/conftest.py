from __future__ import annotations

import pytest

from engine.scoring.config import CategoryCfg, ScoringConfig, get_config
from engine.scoring.core import CellInputs


@pytest.fixture
def cfg() -> ScoringConfig:
    return get_config()


@pytest.fixture
def pharmacy(cfg: ScoringConfig) -> CategoryCfg:
    return cfg.category("pharmacy")


def make_inputs(**kw: object) -> CellInputs:
    base: dict[str, object] = {
        "category_slug": "pharmacy",
        "category_name": "Pharmacy",
        "pop_catchment": 14000.0,
        "supply_quality_adj": 2.0,
        "mapped_count": 2,
        "ground_correction": 1.0,
        "informal_supply": 0.0,
        "benchmark_ppo": 3900.0,
    }
    base.update(kw)
    return CellInputs(**base)  # type: ignore[arg-type]
