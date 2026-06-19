import logging
import signal
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from src.agent import StockAlertAgent
from src.config import get_settings
from src.market import MarketCalendar

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)


def setup_logging() -> None:
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    root.addHandler(console)

    file_handler = RotatingFileHandler(LOG_DIR / "agent.log", maxBytes=5_000_000, backupCount=3)
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)


def wait_for_agent_window(calendar: MarketCalendar) -> None:
    while not calendar.is_agent_active():
        wait_secs = calendar.seconds_until_agent_start()
        if wait_secs > 0:
            logging.info("Waiting %.0f seconds until agent window opens", wait_secs)
            time.sleep(min(wait_secs, 300))
        else:
            break


def main() -> None:
    setup_logging()
    settings = get_settings()
    calendar = MarketCalendar(settings)
    agent = StockAlertAgent(settings)

    def shutdown(signum, frame):
        logging.info("Shutting down (signal %s)", signum)
        agent.close()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    logging.info("grok-stock-alerts-agent starting")
    wait_for_agent_window(calendar)
    agent.send_startup_message()
    agent.run_scan()

    scheduler = BlockingScheduler(timezone=settings.market_timezone)

    scheduler.add_job(
        agent.run_scan,
        IntervalTrigger(minutes=settings.scan_interval_minutes),
        id="intraday_scan",
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
        id="premarket_scan",
        max_instances=1,
    )

    logging.info(
        "Scheduler active — scans every %d min during market hours",
        settings.scan_interval_minutes,
    )

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        agent.close()


if __name__ == "__main__":
    main()