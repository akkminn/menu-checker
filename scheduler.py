import atexit

from apscheduler.schedulers.background import BackgroundScheduler

from config import SCHEDULE_HOUR, SCHEDULE_MINUTE, TIMEZONE
from pipeline import run_pipeline
from utils.logger import log

_scheduler = BackgroundScheduler(timezone=TIMEZONE)


@_scheduler.scheduled_job(
    "cron",
    hour=SCHEDULE_HOUR,
    minute=SCHEDULE_MINUTE,
    id="daily_menu",
    # A missed run (process restart, machine asleep) should still fire if we
    # come back within the hour, and never pile up two runs at once.
    misfire_grace_time=3600,
    coalesce=True,
    max_instances=1,
)
def job():
    log.info("Scheduler triggered — running Facebook pipeline")
    run_pipeline()


def start_background():
    log.info(
        "Scheduler started — Facebook pipeline runs daily at %02d:%02d %s",
        SCHEDULE_HOUR,
        SCHEDULE_MINUTE,
        TIMEZONE,
    )
    _scheduler.start()
    atexit.register(stop_background)


def stop_background(wait: bool = False) -> None:
    if _scheduler.running:
        log.info("Scheduler shutting down")
        _scheduler.shutdown(wait=wait)
