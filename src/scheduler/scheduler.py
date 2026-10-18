"""Repeating runner. The interval comes from config, currently every 2 hours."""

from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers.blocking import BlockingScheduler

from src.utils.logger import get_logger

logger = get_logger("scheduler")
JOB_ID = "naukri_hourly"


def build_scheduler(run_fn, hours: float = 1) -> BackgroundScheduler:
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        run_fn,
        "interval",
        hours=hours,
        id=JOB_ID,
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    return scheduler


def serve(run_fn, hours: float = 1) -> None:
    """Run once now, then block and repeat on the configured interval."""
    logger.info("Running the job cycle once, then every %s hour(s)", hours)
    run_fn()
    scheduler = BlockingScheduler()
    scheduler.add_job(
        run_fn,
        "interval",
        hours=hours,
        id=JOB_ID,
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    scheduler.start()
