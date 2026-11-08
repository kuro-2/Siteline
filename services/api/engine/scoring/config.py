"""Typed view of engine/config/scoring.yaml."""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"
SCORING_PATH = CONFIG_DIR / "scoring.yaml"


class ScoreCfg(BaseModel):
    alpha: float
    g_floor: float
    g_cap: float
    min_supply: float
    draft_threshold: float
    max_drafts_per_category: int


class QualityCfg(BaseModel):
    enabled: bool
    neutral_rating: float
    per_star: float
    min_weight: float
    max_weight: float
    min_rating_count: int


class GroundCfg(BaseModel):
    min: float
    max: float
    fresh_days: int
    usable_days: int


class SurveyAdjCfg(BaseModel):
    max_points: float
    min_n: int
    full_effect_n: int
    neutral_share: float


class ActivityAdjCfg(BaseModel):
    max_points: float
    saturation: float


class ReviewAdjCfg(BaseModel):
    max_points: float


class RentAdjCfg(BaseModel):
    max_points: float
    min_n: int


class LowPopCfg(BaseModel):
    cap: float


class AdjustmentsCfg(BaseModel):
    survey_need: SurveyAdjCfg
    activity_proxy: ActivityAdjCfg
    review_pain: ReviewAdjCfg
    rent_band: RentAdjCfg
    low_population: LowPopCfg


class UncertaintyCfg(BaseModel):
    samples: int
    seed: int
    population_rel_sd: float
    survey_min_sd: float
    hidden_supply_mean: dict[str, float]


class BandCfg(BaseModel):
    max_width: float
    survey_n: int = 0


class ConfidenceCfg(BaseModel):
    confident: BandCfg
    fairly_sure: BandCfg
    early_signal: BandCfg


class CategoryCfg(BaseModel):
    catchment_k: int
    decay_lambda_m: float
    min_population: float
    informal_weight: float
    activity_weight: float
    travel_minutes: int


class GridCfg(BaseModel):
    resolution: int


class ScoringConfig(BaseModel):
    version: int
    grid: GridCfg
    score: ScoreCfg
    status_factor: dict[str, float]
    quality: QualityCfg
    ground_correction: GroundCfg
    adjustments: AdjustmentsCfg
    uncertainty: UncertaintyCfg
    confidence: ConfidenceCfg
    categories: dict[str, CategoryCfg]

    def category(self, slug: str) -> CategoryCfg:
        try:
            return self.categories[slug]
        except KeyError as e:
            raise KeyError(f"Category '{slug}' has no entry in scoring.yaml") from e

    @property
    def max_catchment_k(self) -> int:
        return max(c.catchment_k for c in self.categories.values())


def load_config(path: Path = SCORING_PATH) -> ScoringConfig:
    with path.open(encoding="utf-8") as f:
        return ScoringConfig.model_validate(yaml.safe_load(f))


@lru_cache
def get_config() -> ScoringConfig:
    return load_config()


def config_hash(path: Path = SCORING_PATH) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]
