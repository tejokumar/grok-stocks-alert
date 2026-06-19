import html
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
    ANALYST_UPGRADE = "analyst_upgrade"
    ANALYST_DOWNGRADE = "analyst_downgrade"
    THESIS_REVERSAL = "thesis_reversal"


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
    tickers: list[str] = field(default_factory=list)
    queried_symbol: str = ""


@dataclass
class AnalystGrade:
    symbol: str
    grading_company: str
    previous_grade: str
    new_grade: str
    action: str
    date: str
    is_top_firm: bool = False


@dataclass
class CatalystInsight:
    symbol: str
    catalysts: list[str]
    social_chatter: list[str]
    sentiment: str
    confidence: float
    summary: str
    source: str = "xai"
    references: list[dict[str, str]] = field(default_factory=list)


@dataclass
class Alert:
    alert_type: AlertType
    symbol: str
    title: str
    message: str
    confidence: float = 0.5
    metadata: dict[str, Any] = field(default_factory=dict)

    def _format_references(self) -> str:
        refs: list[dict[str, str]] = list(self.metadata.get("references") or [])
        if not refs and self.metadata.get("url"):
            refs = [{
                "title": self.title[:80],
                "url": self.metadata["url"],
                "source": self.metadata.get("source", ""),
            }]

        lines: list[str] = []
        seen_urls: set[str] = set()
        for ref in refs:
            url = (ref.get("url") or "").strip()
            if not url or not url.startswith("http") or url in seen_urls:
                continue
            seen_urls.add(url)
            title = (ref.get("title") or "Source").strip()[:100]
            source = (ref.get("source") or "").strip()
            label = f"{title} ({source})" if source else title
            lines.append(
                f'• <a href="{html.escape(url, quote=True)}">{html.escape(label)}</a>'
            )

        if not lines:
            return ""
        return "\n\n<b>References:</b>\n" + "\n".join(lines)

    def format_telegram(self, prefix: str) -> str:
        label = {
            AlertType.CATALYST: "CATALYST",
            AlertType.PREMARKET: "PRE-MARKET CATALYST",
            AlertType.BREAKOUT: "BREAKOUT",
            AlertType.UPSIDE_POTENTIAL: "HIGH CONVICTION",
            AlertType.DIRECTION_CHANGE: "DIRECTION CHANGE",
            AlertType.TRENDING: "TRENDING",
            AlertType.ANALYST_UPGRADE: "ANALYST UPGRADE",
            AlertType.ANALYST_DOWNGRADE: "ANALYST DOWNGRADE",
            AlertType.THESIS_REVERSAL: "THESIS REVERSAL",
        }.get(self.alert_type, self.alert_type.value.upper())
        if self.metadata.get("analyst_upgrade") and self.alert_type in (
            AlertType.CATALYST, AlertType.PREMARKET,
        ):
            label = f"{label} + ANALYST UPGRADE"
        header = f"<b>{prefix}</b> | {label}"
        body = f"<b>{self.symbol}</b> — {self.title}\n\n{self.message}"
        ref_types = (
            AlertType.CATALYST,
            AlertType.PREMARKET,
            AlertType.ANALYST_UPGRADE,
            AlertType.ANALYST_DOWNGRADE,
            AlertType.THESIS_REVERSAL,
        )
        if self.alert_type in ref_types:
            body += self._format_references()
        if self.confidence:
            body += f"\n\nConfidence: {self.confidence:.0%}"
        return f"{header}\n\n{body}"