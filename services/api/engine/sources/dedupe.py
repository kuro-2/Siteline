"""Merge the same shop seen by several sources (OSM, Google, ground). Pure functions.

Rule (docs/04 §2): distance < 40 m AND (name similarity ≥ 0.8 OR same category with no
other candidate within 40 m). One canonical row is kept; the others point to it.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from rapidfuzz import fuzz

from engine.geo.grid import haversine_m

MATCH_DISTANCE_M = 40.0
NAME_SIMILARITY = 0.8

# Words that carry no identity in Indian shop names, plus transliteration variants.
_STOPWORDS = {
    "medical",
    "medicals",
    "medicos",
    "medico",
    "medicine",
    "medicines",
    "store",
    "stores",
    "shop",
    "and",
    "sons",
    "son",
    "the",
    "pvt",
    "ltd",
    "enterprise",
    "enterprises",
    "pharmacy",
    "pharma",
    "chemist",
    "chemists",
    "drug",
    "drugs",
    "hall",
    "centre",
    "center",
    "co",
    "company",
    "traders",
    "agency",
    "agencies",
}
_VARIANTS = {
    "medicals": "medical",
    "medicos": "medical",
    "medico": "medical",
    "saloon": "salon",
    "parlour": "parlor",
    "beauty": "beauty",
    "tea": "tea",
    "chai": "tea",
    "cha": "tea",
    "hardwares": "hardware",
    "coaching": "coaching",
    "tutorial": "tuition",
    "tutorials": "tuition",
}


def normalise_name(name: str | None) -> str:
    if not name:
        return ""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = s.replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    tokens = [_VARIANTS.get(t, t) for t in s.split()]
    kept = [t for t in tokens if t not in _STOPWORDS]
    return " ".join(kept or tokens)


def name_similarity(a: str | None, b: str | None) -> float:
    na, nb = normalise_name(a), normalise_name(b)
    if not na or not nb:
        return 0.0
    return fuzz.token_set_ratio(na, nb) / 100.0


@dataclass(frozen=True)
class PlaceRef:
    id: str
    source: str  # osm | google | ground
    name: str | None
    category_id: str | None
    lat: float
    lng: float


SOURCE_PRIORITY = {"ground": 0, "osm": 1, "google": 2}  # canonical row preference


def find_merges(places: list[PlaceRef]) -> dict[str, str]:
    """Return {duplicate_id: canonical_id}. Only cross-source pairs are merged."""
    by_priority = sorted(places, key=lambda p: (SOURCE_PRIORITY.get(p.source, 9), p.id))
    canon: list[PlaceRef] = []
    merges: dict[str, str] = {}
    for p in by_priority:
        near = [
            c
            for c in canon
            if c.source != p.source and haversine_m(c.lat, c.lng, p.lat, p.lng) < MATCH_DISTANCE_M
        ]
        target: PlaceRef | None = None
        named = [c for c in near if name_similarity(c.name, p.name) >= NAME_SIMILARITY]
        if named:
            target = max(named, key=lambda c: name_similarity(c.name, p.name))
        else:
            same_cat = [c for c in near if c.category_id and c.category_id == p.category_id]
            if len(same_cat) == 1 and len(near) == 1:
                target = same_cat[0]
        if target is not None:
            merges[p.id] = target.id
        else:
            canon.append(p)
    return merges
