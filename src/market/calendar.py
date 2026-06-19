from datetime import datetime, time, timedelta

import pytz

from src.config import Settings


class MarketCalendar:
    def __init__(self, settings: Settings):
        self.tz = pytz.timezone(settings.market_timezone)
        self.open_time = time(settings.market_open_hour, settings.market_open_minute)
        self.close_time = time(settings.market_close_hour, settings.market_close_minute)
        self.premarket_offset = timedelta(minutes=settings.premarket_start_minutes_before_open)

    def now(self) -> datetime:
        return datetime.now(self.tz)

    def is_weekday(self, dt: datetime | None = None) -> bool:
        dt = dt or self.now()
        return dt.weekday() < 5

    def market_open_today(self, dt: datetime | None = None) -> datetime:
        dt = dt or self.now()
        return self.tz.localize(datetime.combine(dt.date(), self.open_time))

    def market_close_today(self, dt: datetime | None = None) -> datetime:
        dt = dt or self.now()
        return self.tz.localize(datetime.combine(dt.date(), self.close_time))

    def agent_start_today(self, dt: datetime | None = None) -> datetime:
        return self.market_open_today(dt) - self.premarket_offset

    def is_agent_active(self, dt: datetime | None = None) -> bool:
        dt = dt or self.now()
        if not self.is_weekday(dt):
            return False
        start = self.agent_start_today(dt)
        end = self.market_close_today(dt)
        return start <= dt <= end

    def is_premarket_window(self, dt: datetime | None = None) -> bool:
        dt = dt or self.now()
        if not self.is_weekday(dt):
            return False
        start = self.agent_start_today(dt)
        open_time = self.market_open_today(dt)
        return start <= dt < open_time

    def is_regular_session(self, dt: datetime | None = None) -> bool:
        dt = dt or self.now()
        if not self.is_weekday(dt):
            return False
        return self.market_open_today(dt) <= dt <= self.market_close_today(dt)

    def seconds_until_agent_start(self, dt: datetime | None = None) -> float:
        dt = dt or self.now()
        start = self.agent_start_today(dt)
        if dt >= start:
            if self.is_agent_active(dt):
                return 0
            next_day = dt + timedelta(days=1)
            while not self.is_weekday(next_day):
                next_day += timedelta(days=1)
            start = self.agent_start_today(next_day)
            return (start - dt).total_seconds()
        return (start - dt).total_seconds()