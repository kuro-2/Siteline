"""Survey anti-fraud checks (docs/04 §6). Pure functions; flags, never auto-rejects."""

from __future__ import annotations

import hashlib
from typing import Any

import h3

from engine.geo.grid import haversine_m

LOCATION_RADIUS_M = 2000
MIN_SECONDS = 30
VELOCITY_LIMIT = 10


def salted_hash(value: str | None, salt: str) -> str | None:
    if not value:
        return None
    return hashlib.sha256(f"{salt}:{value}".encode()).hexdigest()[:32]


def location_check(
    home_h3: str, geo: dict[str, float] | None, confirmed_on_map: bool
) -> bool | None:
    """True = passed, False = mismatch, None = not checked (no geolocation, no tap)."""
    if geo:
        lat, lng = h3.cell_to_latlng(home_h3)
        return haversine_m(lat, lng, geo["lat"], geo["lng"]) <= LOCATION_RADIUS_M
    if confirmed_on_map:
        return True
    return None


def straight_lined(questions: list[dict[str, Any]], answers: dict[str, Any]) -> bool:
    """Same option position picked for every single-choice question (needs ≥6 of them)."""
    positions = []
    for q in questions:
        if q["type"] != "single" or q["id"] not in answers:
            continue
        opts = q.get("options") or []
        if answers[q["id"]] in opts:
            positions.append(opts.index(answers[q["id"]]))
    return len(positions) >= 6 and len(set(positions)) == 1


def flags_for(
    *,
    questions: list[dict[str, Any]],
    answers: dict[str, Any],
    duration_seconds: int | None,
    location_ok: bool | None,
    recent_same_device: int,
    recent_same_ip: int,
    recent_same_cell: int,
) -> list[str]:
    flags: list[str] = []
    if location_ok is False:
        flags.append("location_mismatch")
    if location_ok is None:
        flags.append("location_unchecked")
    if duration_seconds is not None and duration_seconds < MIN_SECONDS:
        flags.append("too_fast")
    if straight_lined(questions, answers):
        flags.append("straight_lining")
    if max(recent_same_device, recent_same_ip, recent_same_cell) >= VELOCITY_LIMIT:
        flags.append("velocity")
    return flags


# location_unchecked alone does not zero a response's weight; the others do until cleared.
SOFT_FLAGS = {"location_unchecked"}


def weight_for(flags: list[str]) -> float:
    return 0.0 if any(f not in SOFT_FLAGS for f in flags) else 1.0
