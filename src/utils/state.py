import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class AgentState:
    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data: dict[str, Any] = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {
                "sent_alerts": {},
                "daily_alerts": {},
                "trending_watchlist": [],
                "symbol_baselines": {},
                "last_scan": None,
            }
        try:
            return json.loads(self.path.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load state: %s", exc)
            return {"sent_alerts": {}, "trending_watchlist": [], "symbol_baselines": {}, "last_scan": None}

    def save(self) -> None:
        self.path.write_text(json.dumps(self._data, indent=2, default=str))

    def should_send_alert(self, key: str, cooldown_minutes: int = 60) -> bool:
        sent = self._data.setdefault("sent_alerts", {})
        last = sent.get(key)
        if not last:
            return True
        try:
            last_dt = datetime.fromisoformat(last)
            elapsed = (datetime.utcnow() - last_dt).total_seconds() / 60
            return elapsed >= cooldown_minutes
        except ValueError:
            return True

    def mark_alert_sent(self, key: str) -> None:
        self._data.setdefault("sent_alerts", {})[key] = datetime.utcnow().isoformat()
        self.save()

    def update_watchlist(self, symbols: list[str]) -> None:
        self._data["trending_watchlist"] = symbols
        self.save()

    def get_watchlist(self) -> list[str]:
        return self._data.get("trending_watchlist", [])

    def set_baseline(self, symbol: str, data: dict[str, Any]) -> None:
        self._data.setdefault("symbol_baselines", {})[symbol] = data
        self.save()

    def get_baseline(self, symbol: str) -> dict[str, Any] | None:
        return self._data.get("symbol_baselines", {}).get(symbol)

    def set_last_scan(self) -> None:
        self._data["last_scan"] = datetime.utcnow().isoformat()
        self.save()

    def get_daily_alert_count(self, trading_date: str) -> int:
        daily = self._data.setdefault("daily_alerts", {})
        return len(daily.get(trading_date, []))

    def get_daily_alerted_symbols(self, trading_date: str) -> list[str]:
        daily = self._data.setdefault("daily_alerts", {})
        return list(daily.get(trading_date, []))

    def remaining_daily_slots(self, trading_date: str, max_daily: int) -> int:
        return max(0, max_daily - self.get_daily_alert_count(trading_date))

    def mark_daily_alert(self, symbol: str, trading_date: str) -> None:
        daily = self._data.setdefault("daily_alerts", {})
        entries = daily.setdefault(trading_date, [])
        if symbol not in entries:
            entries.append(symbol)
        self.save()

    def already_alerted_today(self, symbol: str, trading_date: str) -> bool:
        return symbol in self.get_daily_alerted_symbols(trading_date)