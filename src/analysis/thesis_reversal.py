import logging
from datetime import datetime, timedelta, timezone

from src.analysis.relevance import is_relevant_to_symbol
from src.config import Settings
from src.data import FMPClient, PolygonClient
from src.models import Alert, AlertType, StockSnapshot
from src.utils.dedup import catalyst_dedup_key
from src.utils.state import AgentState

logger = logging.getLogger(__name__)

BEARISH_THESIS_KEYWORDS = [
    "downgrade", "downgraded", "cut to", "lowered to", "price target cut",
    "guidance cut", "lowered guidance", "missed estimates", "earnings miss",
    "revenue miss", "warning", "profit warning", "lawsuit", "investigation",
    "recall", "layoffs", "bankruptcy", "offering", "dilution", "sec probe",
    "fraud", "weak demand", "demand slowdown", "inventory glut", "overcapacity",
]

BEARISH_HIGH_IMPACT = [
    "downgrade", "guidance cut", "earnings miss", "revenue miss",
    "price target cut", "profit warning", "sec investigation",
]


class ThesisReversalAnalyzer:
    """Alert when a prior bullish thesis is contradicted by new signals."""

    def __init__(
        self,
        settings: Settings,
        state: AgentState,
        polygon: PolygonClient,
        fmp: FMPClient,
    ):
        self.settings = settings
        self.state = state
        self.polygon = polygon
        self.fmp = fmp

    def find_reversals(
        self,
        downgrade_alerts: list[Alert],
        watchlist_by_symbol: dict[str, StockSnapshot],
    ) -> list[Alert]:
        alerts: list[Alert] = []
        theses = self.state.list_bullish_theses()
        if not theses:
            return alerts

        downgrade_by_symbol = {a.symbol: a for a in downgrade_alerts}
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.settings.thesis_reversal_lookback_days)

        for symbol, thesis in theses.items():
            reversal_alert = None

            if symbol in downgrade_by_symbol:
                reversal_alert = self._build_reversal_alert(
                    symbol, thesis, downgrade_by_symbol[symbol], watchlist_by_symbol,
                    trigger="analyst_downgrade",
                )
            else:
                bearish_news = self._find_bearish_news(symbol, cutoff)
                if bearish_news:
                    reversal_alert = self._build_reversal_alert(
                        symbol, thesis, bearish_news, watchlist_by_symbol,
                        trigger="bearish_news",
                    )

            if reversal_alert:
                alerts.append(reversal_alert)

        return alerts

    def _find_bearish_news(self, symbol: str, cutoff: datetime) -> Alert | None:
        items = []
        for fetch in (self.polygon.get_news, self.fmp.get_news):
            try:
                items.extend(fetch(symbol, limit=5))
            except Exception:
                pass

        for item in items:
            if not is_relevant_to_symbol(symbol, item):
                continue
            if item.published_at and item.published_at.astimezone(timezone.utc) < cutoff:
                continue
            text = f"{item.title} {item.summary}".lower()
            if not any(kw in text for kw in BEARISH_HIGH_IMPACT):
                continue
            if not any(kw in text for kw in BEARISH_THESIS_KEYWORDS):
                continue
            refs = (
                [{"title": item.title[:80], "url": item.url, "source": item.source}]
                if item.url
                else []
            )
            return Alert(
                alert_type=AlertType.ANALYST_DOWNGRADE,
                symbol=symbol,
                title=f"Bearish catalyst: {item.title[:80]}",
                message=item.summary[:350] or item.title,
                confidence=0.82,
                metadata={
                    "source": item.source,
                    "url": item.url,
                    "references": refs,
                    "thesis_direction": "bearish",
                    "trigger": "bearish_news",
                },
            )
        return None

    def _build_reversal_alert(
        self,
        symbol: str,
        thesis: dict,
        trigger_alert: Alert,
        watchlist_by_symbol: dict[str, StockSnapshot],
        trigger: str,
    ) -> Alert:
        snap = watchlist_by_symbol.get(symbol)
        price_note = ""
        if snap and snap.price > 0:
            price_note = f"\nCurrent: ${snap.price:.2f} ({snap.change_pct:+.1f}%)"

        original_title = thesis.get("title", "Bullish thesis")
        original_summary = thesis.get("summary", "")[:200]
        original_price = thesis.get("price_at_alert")
        original_target = thesis.get("target_at_alert")
        alerted_at = thesis.get("alerted_at", "unknown")

        thesis_block = (
            f"<b>Original bullish thesis</b> ({alerted_at[:10] if alerted_at else 'prior'}):\n"
            f"• {original_title}\n"
        )
        if original_summary:
            thesis_block += f"• {original_summary[:180]}\n"
        if original_price and original_target:
            thesis_block += f"• Entry ${original_price:.2f} → Target ${original_target:.2f}\n"

        change_block = (
            f"\n<b>Thesis change</b>:\n"
            f"• {trigger_alert.title}\n"
            f"• {trigger_alert.message[:250]}"
            f"{price_note}"
        )

        refs = list(thesis.get("references") or [])
        refs.extend(trigger_alert.metadata.get("references") or [])
        if trigger_alert.metadata.get("url") and not refs:
            refs.append({
                "title": trigger_alert.title[:80],
                "url": trigger_alert.metadata["url"],
                "source": trigger_alert.metadata.get("source", ""),
            })

        dedup_seed = f"{trigger}:{trigger_alert.title}:{trigger_alert.metadata.get('grade_date', '')}"
        return Alert(
            alert_type=AlertType.THESIS_REVERSAL,
            symbol=symbol,
            title=f"Bullish thesis reversed — {trigger_alert.title[:60]}",
            message=thesis_block + change_block,
            confidence=max(0.8, trigger_alert.confidence),
            metadata={
                "source": "thesis_reversal",
                "trigger": trigger,
                "original_thesis": thesis,
                "references": refs[:6],
                "thesis_direction": "bearish",
                "catalyst_key": catalyst_dedup_key(symbol, dedup_seed, "thesis_reversal"),
            },
        )