from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class AlertType(str, Enum):
    BREAKOUT = "breakout"
    CATALYST = "catalyst"
    UPSIDE_POTENTIAL = "upside_potential"
    DIRECTION_CHANGE = "direction_change"
    TRENDING = "trending"
    PREMARKET = "premarket"


@dataclass
class StockSnapshot:
    symbol: str
    price: float
    change_pct: float
    volume: int
    prev_close: float | None = None
    day_high: float | None = None
    day_low: float | None = None
    vwap: float | None = None
    source: str = "unknown"
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class NewsItem:
    symbol: str
    title: str
    summary: str
    url: str
    published_at: datetime | None
    source: str


@dataclass
class CatalystInsight:
    symbol: str
    catalysts: list[str]
    social_chatter: list[str]
    sentiment: str
    confidence: float
    summary: str
    source: str = "xai"


@dataclass
class Alert:
    alert_type: AlertType
    symbol: str
    title: str
    message: str
    confidence: float = 0.5
    metadata: dict[str, Any] = field(default_factory=dict)

    def format_telegram(self, prefix: str) -> str:
        label = {
            AlertType.CATALYST: "CATALYST",
            AlertType.PREMARKET: "PRE-MARKET CATALYST",
            AlertType.BREAKOUT: "BREAKOUT",
            AlertType.UPSIDE_POTENTIAL: "HIGH CONVICTION",
            AlertType.DIRECTION_CHANGE: "DIRECTION CHANGE",
            AlertType.TRENDING: "TRENDING",
        }.get(self.alert_type, self.alert_type.value.upper())
        header = f"<b>{prefix}</b> | {label}"
        body = f"<b>{self.symbol}</b> — {self.title}\n\n{self.message}"
        if self.confidence:
            body += f"\n\nConfidence: {self.confidence:.0%}"
        return f"{header}\n\n{body}"