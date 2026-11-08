"""Every engine command records itself in `job_runs`."""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from engine.log import get_logger

log = get_logger("engine.jobs")


@dataclass
class JobRun:
    job: str
    args: dict[str, Any]
    dry_run: bool
    counts: dict[str, Any] = field(default_factory=dict)
    est_cost_usd: float = 0.0
    id: str | None = None

    def count(self, key: str, n: int = 1) -> None:
        self.counts[key] = int(self.counts.get(key, 0)) + n

    def set(self, key: str, value: Any) -> None:
        self.counts[key] = value


def _db_available() -> bool:
    from engine.settings import get_settings

    return bool(get_settings().database_url)


@contextmanager
def job_run(job: str, args: dict[str, Any], *, dry_run: bool = False) -> Iterator[JobRun]:
    """Insert a `running` row, then mark it succeeded / failed / dry_run.

    If DATABASE_URL is not set (e.g. a Google dry-run on a fresh machine), the run is
    only logged, not stored.
    """
    run = JobRun(job=job, args=args, dry_run=dry_run)
    started = time.monotonic()
    use_db = _db_available()
    if use_db:
        from engine.db import connect

        with connect() as conn:
            row = conn.execute(
                "insert into job_runs (job, args, status) values (%s, %s, 'running') returning id",
                (job, json.dumps(args, default=str)),
            ).fetchone()
            run.id = str(row["id"]) if row else None
    log.info("job.start", job=job, args=args, dry_run=dry_run)
    try:
        yield run
    except Exception as e:
        _finish(run, "failed", str(e)[:2000], use_db)
        log.error("job.failed", job=job, error=str(e))
        raise
    status = "dry_run" if dry_run else "succeeded"
    _finish(run, status, None, use_db)
    log.info(
        "job.done",
        job=job,
        status=status,
        counts=run.counts,
        seconds=round(time.monotonic() - started, 2),
        est_cost_usd=run.est_cost_usd,
    )


def _finish(run: JobRun, status: str, error: str | None, use_db: bool) -> None:
    if not use_db or run.id is None:
        return
    from engine.db import connect

    with connect() as conn:
        conn.execute(
            """update job_runs set status = %s, finished_at = %s, counts = %s, error = %s,
                   est_cost_usd = %s where id = %s""",
            (
                status,
                datetime.now(UTC),
                json.dumps(run.counts, default=str),
                error,
                run.est_cost_usd,
                run.id,
            ),
        )
