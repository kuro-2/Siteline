"""Paid-API guard. Every Google call goes through `QuotaGuard.spend()`.

- Counts calls per (provider, sku, month) in `api_usage`.
- Refuses when the monthly cap for that SKU would be exceeded.
- Estimates cost from engine/config/pricing.yaml (free allowance first, then per-1k price).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from functools import lru_cache
from typing import Protocol

import yaml

from engine.scoring.config import CONFIG_DIR

ENTERPRISE_SAFE_CAP = 900  # stays under the 1,000 free Enterprise calls


class QuotaExceeded(RuntimeError):
    pass


@dataclass(frozen=True)
class SkuPrice:
    free_calls_per_month: int
    usd_per_1000: float


@lru_cache
def pricing() -> dict[str, object]:
    with (CONFIG_DIR / "pricing.yaml").open(encoding="utf-8") as f:
        data: dict[str, object] = yaml.safe_load(f)
    return data


def sku_price(sku: str) -> SkuPrice:
    skus = pricing()["google"]["skus"]  # type: ignore[index]
    raw = skus[sku]
    return SkuPrice(int(raw["free_calls_per_month"]), float(raw["usd_per_1000"]))


def estimate_cost_usd(sku: str, already_used: int, new_calls: int) -> float:
    """Cost of `new_calls` more calls this month, after `already_used` calls."""
    p = sku_price(sku)
    free_left = max(0, p.free_calls_per_month - already_used)
    billable = max(0, new_calls - free_left)
    return round(billable * p.usd_per_1000 / 1000, 4)


def month_start(today: date | None = None) -> date:
    d = today or datetime.now(UTC).date()
    return d.replace(day=1)


def effective_cap(sku: str, configured_cap: int) -> int:
    if sku.endswith("_enterprise"):
        return min(configured_cap, ENTERPRISE_SAFE_CAP)
    return configured_cap


class UsageStore(Protocol):
    def get(self, provider: str, sku: str, month: date) -> int: ...
    def add(self, provider: str, sku: str, month: date, calls: int, cost: float) -> None: ...


class MemoryUsageStore:
    """For tests and dry runs without a database."""

    def __init__(self) -> None:
        self.calls: dict[tuple[str, str, date], int] = {}
        self.cost: dict[tuple[str, str, date], float] = {}

    def get(self, provider: str, sku: str, month: date) -> int:
        return self.calls.get((provider, sku, month), 0)

    def add(self, provider: str, sku: str, month: date, calls: int, cost: float) -> None:
        key = (provider, sku, month)
        self.calls[key] = self.calls.get(key, 0) + calls
        self.cost[key] = self.cost.get(key, 0.0) + cost


class DbUsageStore:
    def get(self, provider: str, sku: str, month: date) -> int:
        from engine.db import connect

        with connect() as conn:
            row = conn.execute(
                "select calls from api_usage where provider=%s and sku=%s and month=%s",
                (provider, sku, month),
            ).fetchone()
        return int(row["calls"]) if row else 0

    def add(self, provider: str, sku: str, month: date, calls: int, cost: float) -> None:
        from engine.db import connect

        with connect() as conn:
            conn.execute(
                """insert into api_usage (provider, sku, month, calls, est_cost_usd)
                   values (%s, %s, %s, %s, %s)
                   on conflict (provider, sku, month) do update
                   set calls = api_usage.calls + excluded.calls,
                       est_cost_usd = api_usage.est_cost_usd + excluded.est_cost_usd""",
                (provider, sku, month, calls, cost),
            )


class QuotaGuard:
    def __init__(self, store: UsageStore, cap: int, provider: str = "google") -> None:
        self.store = store
        self.cap = cap
        self.provider = provider
        self.spent_usd = 0.0
        self.calls = 0

    def remaining(self, sku: str, today: date | None = None) -> int:
        used = self.store.get(self.provider, sku, month_start(today))
        return max(0, effective_cap(sku, self.cap) - used)

    def check(self, sku: str, planned_calls: int, today: date | None = None) -> None:
        left = self.remaining(sku, today)
        if planned_calls > left:
            raise QuotaExceeded(
                f"This run needs about {planned_calls} {sku} calls but only {left} are left "
                f"under the monthly cap ({effective_cap(sku, self.cap)}). Nothing was called."
            )

    def spend(self, sku: str, today: date | None = None) -> None:
        """Record one call. Call this *before* making the request."""
        m = month_start(today)
        used = self.store.get(self.provider, sku, m)
        if used >= effective_cap(sku, self.cap):
            raise QuotaExceeded(
                f"Monthly cap reached for {sku} ({used} calls). Stopping before the next call."
            )
        cost = estimate_cost_usd(sku, used, 1)
        self.store.add(self.provider, sku, m, 1, cost)
        self.spent_usd += cost
        self.calls += 1
