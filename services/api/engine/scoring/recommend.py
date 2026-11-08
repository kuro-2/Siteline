"""Pick draft recommendations: high score, enough confidence, not crowded together."""

from __future__ import annotations

from dataclasses import dataclass

import h3

from engine.scoring.confidence import Band


@dataclass(frozen=True)
class Candidate:
    h3: str
    score: float
    band: Band


def select_drafts(
    candidates: list[Candidate], *, threshold: float, k: int, limit: int
) -> list[Candidate]:
    """Non-maximum suppression: best first; skip any cell within k rings of a pick."""
    eligible = [
        c for c in candidates if c.score >= threshold and c.band.rank >= Band.EARLY_SIGNAL.rank
    ]
    # Higher score first; ties broken by confidence then by h3 for stable output.
    eligible.sort(key=lambda c: (-c.score, -c.band.rank, c.h3))
    picks: list[Candidate] = []
    blocked: set[str] = set()
    for c in eligible:
        if c.h3 in blocked:
            continue
        picks.append(c)
        blocked.update(h3.grid_disk(c.h3, k))
        if len(picks) >= limit:
            break
    return picks
