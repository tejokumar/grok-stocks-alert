import logging
from datetime import datetime, timezone

from src.config import Settings
from src.data import FMPClient, PolygonClient, ROICClient
from src.models import Alert, AlertType, NewsItem, StockSnapshot
from src.utils.dedup import catalyst_dedup_key

logger = logging.getLogger(__name__)

CATALYST_KEYWORDS = [
    "fda", "approval", "acquisition", "merger", "partnership", "contract",
    "upgrade", "buyout", "short squeeze", "breakthrough", "launch", "patent",
    "buyback", "earnings beat", "guidance raise", "raised guidance",
    "price target", "takeover", "activist",
]

HIGH_IMPACT_KEYWORDS = [
    "fda approval", "merger", "acquisition", "buyout", "earnings beat",
    "guidance raise", "raised guidance", "price target", "upgrade",
    "breakthrough", "contract award", "partnership", "short squeeze",
    "offering withdrawn", "activist", "takeover",
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

    def find_strong_catalyst_alerts(
        self,
        symbols: list[str],
        watchlist_by_symbol: dict[str, StockSnapshot],
        phase: str = "regular",
    ) -> list[Alert]:
        alerts: list[Alert] = []
        scan_symbols = symbols[:25]

        by_symbol: dict[str, Alert] = {}
        for symbol in scan_symbols:
            snap = watchlist_by_symbol.get(symbol)
            symbol_alerts = self._scan_symbol_catalysts(symbol, snap, phase)
            if symbol_alerts:
                best = max(symbol_alerts, key=lambda a: a.confidence)
                if best.confidence >= self.settings.min_catalyst_confidence:
                    by_symbol[symbol] = best

        if phase == "premarket":
            for alert in self._scan_market_headlines(watchlist_by_symbol):
                existing = by_symbol.get(alert.symbol)
                if not existing or alert.confidence > existing.confidence:
                    by_symbol[alert.symbol] = alert

        return list(by_symbol.values())

    def _scan_symbol_catalysts(
        self,
        symbol: str,
        snapshot: StockSnapshot | None,
        phase: str,
    ) -> list[Alert]:
        alerts: list[Alert] = []
        news = self._gather_news(symbol)

        scored_items = [
            (item, score) for item, score in self._score_news_items(news)
            if self._is_strong(score, item)
        ]
        if scored_items:
            item, score = scored_items[0]
            alerts.append(self._news_to_alert(symbol, item, score, snapshot, phase))

        for cat in self.roic.get_catalysts(symbol)[:1]:
            title = cat.get("title") or cat.get("description", "ROIC catalyst")
            text = f"{title} {cat.get('summary', '')}".lower()
            score = self._keyword_score(text)
            if self._is_strong(score, None, text):
                alerts.append(
                    Alert(
                        alert_type=AlertType.PREMARKET if phase == "premarket" else AlertType.CATALYST,
                        symbol=symbol,
                        title=f"Strong catalyst: {title[:80]}",
                        message=str(cat.get("summary") or cat.get("description", title))[:400],
                        confidence=min(0.92, 0.72 + score * 0.04),
                        metadata={
                            "source": "roic",
                            "catalyst_key": catalyst_dedup_key(symbol, title, "roic"),
                        },
                    )
                )

        return alerts

    def _scan_market_headlines(
        self,
        watchlist_by_symbol: dict[str, StockSnapshot],
    ) -> list[Alert]:
        alerts: list[Alert] = []
        try:
            latest = self.fmp.get_news(limit=30)
        except Exception as exc:
            logger.warning("Market headline scan failed: %s", exc)
            return alerts

        for item, score in self._score_news_items(latest):
            if not self._is_strong(score, item):
                continue
            symbol = item.symbol
            if symbol == "MARKET" or len(symbol) > 5:
                continue
            snap = watchlist_by_symbol.get(symbol)
            alerts.append(self._news_to_alert(symbol, item, score, snap, "premarket"))

        return alerts

    def find_upside_candidates(self, symbols: list[str] | None = None) -> list[Alert]:
        alerts: list[Alert] = []
        candidates = self.roic.get_upside_candidates(symbols=symbols)
        for row in candidates[:8]:
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

    def _news_to_alert(
        self,
        symbol: str,
        item: NewsItem,
        score: int,
        snapshot: StockSnapshot | None,
        phase: str,
    ) -> Alert:
        phase_label = "Pre-market" if phase == "premarket" else "Intraday"
        price_note = ""
        if snapshot and snapshot.price > 0:
            price_note = f"\nPrice: ${snapshot.price:.2f} ({snapshot.change_pct:+.1f}%)"

        freshness = ""
        if item.published_at:
            age_hours = (datetime.now(timezone.utc) - item.published_at.astimezone(timezone.utc)).total_seconds() / 3600
            if age_hours < 6:
                freshness = " [FRESH]"

        return Alert(
            alert_type=AlertType.PREMARKET if phase == "premarket" else AlertType.CATALYST,
            symbol=symbol,
            title=f"{phase_label} catalyst{freshness}: {item.title[:80]}",
            message=(item.summary[:350] or item.title) + price_note,
            confidence=min(0.95, 0.68 + score * 0.05),
            metadata={
                "url": item.url,
                "source": item.source,
                "catalyst_key": catalyst_dedup_key(symbol, item.title, item.source),
                "keyword_score": score,
            },
        )

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
        try:
            items.extend(self.roic.get_news(symbol, limit=5))
        except Exception as exc:
            logger.warning("ROIC news for %s: %s", symbol, exc)
        return items

    def _score_news_items(self, items: list[NewsItem]) -> list[tuple[NewsItem, int]]:
        scored: list[tuple[NewsItem, int]] = []
        for item in items:
            score = self._keyword_score(f"{item.title} {item.summary}")
            if score > 0:
                scored.append((item, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored

    def _keyword_score(self, text: str) -> int:
        text = text.lower()
        hits = sum(1 for kw in CATALYST_KEYWORDS if kw in text)
        for phrase in HIGH_IMPACT_KEYWORDS:
            if phrase in text:
                hits += 2
        return hits

    def _is_strong(self, score: int, item: NewsItem | None, text: str | None = None) -> bool:
        combined = text or (f"{item.title} {item.summary}" if item else "")
        combined = combined.lower()
        has_high_impact = any(phrase in combined for phrase in HIGH_IMPACT_KEYWORDS)

        if has_high_impact and score >= 2:
            return True
        if score >= self.settings.strong_catalyst_keyword_hits + 2:
            return True
        if item and item.published_at and has_high_impact:
            age_hours = (
                datetime.now(timezone.utc) - item.published_at.astimezone(timezone.utc)
            ).total_seconds() / 3600
            if age_hours < 4:
                return True
        return False