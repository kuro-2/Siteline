"""Map source tags/types to Siteline categories. Pure functions."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class CategoryDef:
    id: str
    slug: str
    name: str
    osm_tags: list[dict[str, str]]
    google_types: list[str]
    catchment_k: int
    google_text_query: str | None = None
    sort_order: int = 100
    extra: dict[str, Any] = field(default_factory=dict)


# Keys whose values describe a business; used for "unmapped" reporting and activity counts.
BUSINESS_KEYS = ("shop", "amenity", "office", "craft", "healthcare")
COMMERCIAL_AMENITIES = {
    "pharmacy",
    "cafe",
    "restaurant",
    "fast_food",
    "bank",
    "clinic",
    "doctors",
    "dentist",
    "prep_school",
    "tutoring",
    "training",
    "marketplace",
    "fuel",
    "bar",
    "pub",
    "ice_cream",
    "food_court",
    "veterinary",
    "internet_cafe",
    "car_wash",
    "driving_school",
    "money_transfer",
    "bureau_de_change",
    "studio",
    "cinema",
    "hospital",
}


def match_osm(tags: Mapping[str, str], categories: Iterable[CategoryDef]) -> CategoryDef | None:
    """First category (by sort order) with a tag rule whose every key=value matches."""
    for cat in sorted(categories, key=lambda c: c.sort_order):
        for rule in cat.osm_tags:
            if all(tags.get(k) == v for k, v in rule.items()):
                return cat
    return None


def is_business(tags: Mapping[str, str]) -> bool:
    if any(k in tags for k in ("shop", "office", "craft")):
        return True
    if tags.get("amenity") in COMMERCIAL_AMENITIES:
        return True
    return "healthcare" in tags


def raw_category(tags: Mapping[str, str]) -> str | None:
    for k in BUSINESS_KEYS:
        if k in tags:
            return f"{k}={tags[k]}"
    return None


def match_google(types: Iterable[str], categories: Iterable[CategoryDef]) -> CategoryDef | None:
    tset = set(types)
    for cat in sorted(categories, key=lambda c: c.sort_order):
        if tset.intersection(cat.google_types):
            return cat
    return None
