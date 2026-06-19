import argparse
import logging
import signal
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from src.agent.semiconductor_agent import SemiconductorAlertAgent
from src.config import get_settings
from src.market import MarketCalendar

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)


def setup_logging() -> None:
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    root.addHandler(console)

    file_handler = RotatingFileHandler(LOG_DIR / "semi_agent.log", maxBytes=5_000_000, backupCount=3)
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)


def wait_for_agent_window(calendar: MarketCalendar) -> None:
    while not calendar.is_agent_active():
        wait_secs = calendar.seconds_until_agent_start()
        if wait_secs > 0:
            logging.info("Waiting %.0f seconds until semi agent window opens", wait_secs)
            time.sleep(min(wait_secs, 300))
        else:
            break


def main() -> None:
    parser = argparse.ArgumentParser(description="Grok semiconductor alerts agent")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Run immediately, ignoring market hours (single scan, then exit)",
    )
    args = parser.parse_args()

    setup_logging()
    settings = get_settings()
    calendar = MarketCalendar(settings)
    agent = SemiconductorAlertAgent(settings)

    def shutdown(signum, frame):
        logging.info("Shutting down semi agent (signal %s)", signum)
        agent.close()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    if args.force:
        logging.info("%s starting (force/test mode)", settings.semi_alert_prefix)
        agent.send_startup_message()
        agent.run_scan(force=True)
        agent.close()
        logging.info("Semi force scan complete — exiting")
        return

    logging.info("%s starting", settings.semi_alert_prefix)
    wait_for_agent_window(calendar)
    agent.send_startup_message()
    agent.run_scan()

    scheduler = BlockingScheduler(timezone=settings.market_timezone)
    scheduler.add_job(
        agent.run_scan,
        IntervalTrigger(minutes=settings.scan_interval_minutes),
        id="semi_intraday_scan",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        agent.run_scan,
        CronTrigger(
            day_of_week="mon-fri",
            hour=settings.market_open_hour,
            minute=settings.market_open_minute - settings.premarket_start_minutes_before_open,
            timezone=settings.market_timezone,
        ),
        id="semi_premarket_scan",
        max_instances=1,
    )

    logging.info("Semi scheduler active — scans every %d min", settings.scan_interval_minutes)
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        agent.close()


if __name__ == "__main__":
    main()