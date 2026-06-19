import logging

from src.config import Settings
from src.data import FMPClient, PolygonClient, ROICClient
from src.models import Alert, AlertType, NewsItem

logger = logging.getLogger(__name__)

CATALYST_KEYWORDS = [
    "earnings", "guidance", "fda", "approval", "acquisition", "merger",
    "partnership", "contract", "upgrade", "downgrade", "buyout", "offering",
    "short squeeze", "breakthrough", "launch", "patent", "dividend",
    "buyback", "analyst", "revenue", "beat", "miss", "ceo", "cfo",
]


class CatalystAnalyzer:
    def __init__(
        self,
        settings: Settings,
        polygon: PolygonClient,
        fmp: FMPClient,
        roic: ROICClient,
    ):
        self.settings = settings
        self.polygon = polygon
        self.fmp = fmp
        self.roic = roic

    def find_catalyst_alerts(self, symbols: list[str]) -> list[Alert]:
        alerts: list[Alert] = []
        for symbol in symbols[:15]:
            news = self._gather_news(symbol)
            roic_catalysts = self.roic.get_catalysts(symbol)
            scored = self._score_news(news)
            if scored:
                top = scored[0]
                alerts.append(
                    Alert(
                        alert_type=AlertType.CATALYST,
                        symbol=symbol,
                        title=f"News catalyst: {top.title[:80]}",
                        message=top.summary[:400] or top.title,
                        confidence=0.7,
                        metadata={"url": top.url, "source": top.source},
                    )
                )
            for cat in roic_catalysts[:2]:
                title = cat.get("title") or cat.get("description", "ROIC catalyst")
                alerts.append(
                    Alert(
                        alert_type=AlertType.CATALYST,
                        symbol=symbol,
                        title=f"ROIC catalyst: {title[:80]}",
                        message=str(cat.get("summary") or cat.get("description", title))[:400],
                        confidence=float(cat.get("confidence", 0.6)),
                        metadata={"source": "roic"},
                    )
                )
        return alerts

    def find_upside_candidates(self) -> list[Alert]:
        alerts: list[Alert] = []
        candidates = self.roic.get_upside_candidates()
        for row in candidates[:10]:
            symbol = row.get("symbol") or row.get("ticker")
            if not symbol:
                continue
            reason = row.get("reason") or row.get("summary") or "ROIC upside screen match"
            score = float(row.get("score", row.get("upside_score", 0.6)))
            alerts.append(
                Alert(
                    alert_type=AlertType.UPSIDE_POTENTIAL,
                    symbol=symbol,
                    title="Multi-session upside candidate",
                    message=str(reason)[:400],
                    confidence=min(0.9, score),
                    metadata=row,
                )
            )
        return alerts

    def _gather_news(self, symbol: str) -> list[NewsItem]:
        items: list[NewsItem] = []
        try:
            items.extend(self.polygon.get_news(symbol, limit=5))
        except Exception as exc:
            logger.warning("Polygon news for %s: %s", symbol, exc)
        try:
            items.extend(self.fmp.get_news(symbol, limit=5))
        except Exception as exc:
            logger.warning("FMP news for %s: %s", symbol, exc)
        return items

    def _score_news(self, items: list[NewsItem]) -> list[NewsItem]:
        scored: list[tuple[int, NewsItem]] = []
        for item in items:
            text = f"{item.title} {item.summary}".lower()
            hits = sum(1 for kw in CATALYST_KEYWORDS if kw in text)
            if hits:
                scored.append((hits, item))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in scored]