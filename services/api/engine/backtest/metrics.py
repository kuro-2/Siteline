"""Backtest metrics. Pure functions, no dependencies beyond the stdlib."""

from __future__ import annotations

from collections.abc import Sequence


def precision_recall_at_k(
    ranked: Sequence[str], positives: set[str], k: int
) -> tuple[float, float]:
    if k <= 0:
        raise ValueError("k must be positive")
    top = list(ranked[:k])
    hits = sum(1 for c in top if c in positives)
    precision = hits / len(top) if top else 0.0
    recall = hits / len(positives) if positives else 0.0
    return precision, recall


def roc_auc(scores: dict[str, float], positives: set[str]) -> float | None:
    """Mann–Whitney U formulation; ties count half. None when only one class exists."""
    pos = [s for c, s in scores.items() if c in positives]
    neg = [s for c, s in scores.items() if c not in positives]
    if not pos or not neg:
        return None
    wins = 0.0
    for p in pos:
        for n in neg:
            if p > n:
                wins += 1
            elif p == n:
                wins += 0.5
    return wins / (len(pos) * len(neg))


def random_precision(n_cells: int, n_pos: int) -> float:
    """Expected precision@k of a random ranking (independent of k)."""
    return n_pos / n_cells if n_cells else 0.0


def rank(scores: dict[str, float]) -> list[str]:
    return [c for c, _ in sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))]


def calibration_by_decile(scores: dict[str, float], positives: set[str]) -> list[dict[str, float]]:
    """Share of positive cells in each score decile (0–10, 10–20, …)."""
    bins: list[dict[str, float]] = []
    for lo in range(0, 100, 10):
        hi = lo + 10
        cells = [c for c, s in scores.items() if lo <= s < hi or (hi == 100 and s == 100)]
        if not cells:
            continue
        hit = sum(1 for c in cells if c in positives)
        bins.append(
            {
                "from": lo,
                "to": hi,
                "cells": len(cells),
                "positives": hit,
                "rate": round(hit / len(cells), 3),
            }
        )
    return bins
