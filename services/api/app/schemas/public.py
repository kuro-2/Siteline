"""Response models for public endpoints. The web app's TypeScript types are generated
from these (pnpm gen:api), so keep them accurate."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

Confidence = Literal["not_enough_data", "early_signal", "fairly_sure", "confident"]


class Health(BaseModel):
    status: str
    db: str


class AreaSummary(BaseModel):
    id: str
    slug: str
    name: str
    city: str
    bbox: list[float]


class Freshness(BaseModel):
    source: str
    last_updated: str | None


class AreaDetail(AreaSummary):
    boundary: dict[str, Any]
    centre: list[float]
    cells: int
    survey_slug: str | None
    freshness: list[Freshness]


class Category(BaseModel):
    slug: str
    name: str
    description: str | None
    catchment_k: int
    walk_minutes: int | None


class MapResponse(BaseModel):
    run_at: str | None
    # [h3, score | null, confidence, is_recommended]
    cells: list[tuple[str, int | None, Confidence, bool]]


class TopPick(BaseModel):
    id: str
    h3: str
    score: int
    confidence: Confidence
    published_at: str | None
    reviewed_by_name: str | None
    category: str
    category_name: str


class Competitor(BaseModel):
    name: str
    distance_m: int
    rating: float | None
    rating_count: int | None
    source: str
    source_label: str
    status: str | None


class PopulationEvidence(BaseModel):
    value: float | None
    source: str
    as_of: str | None
    walk_minutes: int


class GroundEvidence(BaseModel):
    value: int
    informal: int
    counted_on: str
    by: str


class SurveyEvidence(BaseModel):
    n: int
    share_travel_far: float | None
    travel_minutes: int
    as_of: str | None


class RentEvidence(BaseModel):
    median_inr_per_sqft: float | None
    n: int


class Evidence(BaseModel):
    population: PopulationEvidence
    competitors: list[Competitor]
    ground_count: GroundEvidence | None
    survey: SurveyEvidence | None
    rent_band: RentEvidence | None
    places_as_of: str | None


class ComponentOut(BaseModel):
    name: str
    effect: float
    why: str


class ReviewedBy(BaseModel):
    name: str
    on: str


class Neighbour(BaseModel):
    h3: str
    score: int
    confidence: Confidence
    direction: str
    distance_m: int


class Named(BaseModel):
    slug: str
    name: str


class CellReport(BaseModel):
    h3: str
    area: Named
    category: Named
    score: int | None
    score_low: int | None
    score_high: int | None
    confidence: Confidence
    status: Literal["published", "engine_only"]
    headline: str
    explanation: str
    evidence: Evidence
    components: list[ComponentOut]
    reviewed_by: ReviewedBy | None
    limits: list[str]
    neighbours: list[Neighbour]
    data_snapshot_at: str


class CheckResponse(BaseModel):
    report: CellReport
    advice: str | None


class GeocodeResult(BaseModel):
    name: str
    lat: float
    lng: float


class ErrorBody(BaseModel):
    code: str
    message: str
    hint: str | None


class ErrorResponse(BaseModel):
    error: ErrorBody
