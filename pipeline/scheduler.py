"""
scheduler.py
------------
In-process scheduler fallback for local testing.

IMPORTANT (carried over from the CLFS project's architecture lesson):
An in-process scheduler (this file) only runs while the Python process
stays alive - if the machine reboots or the script crashes, the schedule
silently stops. For production reliability, prefer a system cron job
(or Windows Task Scheduler) that calls `python main.py --run-once`
on a fixed schedule instead of relying on this loop.

Example cron entry (daily at 3 AM):
    0 3 * * * /usr/bin/python3 /path/to/main.py --run-once >> /path/to/logs/cron.log 2>&1
"""

import time
import logging

from config import settings
from pipeline.pipeline import run_pipeline

logger = logging.getLogger(__name__)


def run_forever(interval_hours: float = settings.RUN_INTERVAL_HOURS) -> None:
    """Simple blocking loop - fine for local testing, not for production."""
    interval_seconds = interval_hours * 3600
    logger.info("Starting in-process scheduler (every %s hours). Prefer cron in production.", interval_hours)
    while True:
        run_pipeline()
        logger.info("Sleeping for %s hours...", interval_hours)
        time.sleep(interval_seconds)
