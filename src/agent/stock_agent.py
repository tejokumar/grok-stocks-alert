import logging

from src.ai import ClaudeClient, XAIClient
from src.alerts import TelegramAlerter
from src.analysis import (
    BreakoutAnalyzer,
    CatalystAnalyzer,
    ConvictionSelector,
    DirectionAnalyzer,
    TrendingAnalyzer,
)
from src.config import Settings
from src.data import FMPClient, PolygonClient, ROICClient
from src.market import MarketCalendar
from src.models import Alert, AlertType
from src.utils.state import AgentState

logger = logging.getLogger(__name__)


class StockAlertAgent:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings()
        self.calendar = MarketCalendar(self.settings)
        self.state = AgentState(self.settings.state_file)

        self.polygon = PolygonClient(self.settings)
        self.fmp = FMPClient(self.settings)
        self.roic = ROICClient(self.settings)
        self.xai = XAIClient(self.settings)
        self.claude = ClaudeClient(self.settings)
        self.telegram = TelegramAlerter(self.settings)

        self.trending = TrendingAnalyzer(self.settings, self.polygon, self.fmp, self.roic)
        self.breakout = BreakoutAnalyzer(self.settings, self.polygon)
        self.direction = DirectionAnalyzer(self.state)
        self.catalyst = CatalystAnalyzer(self.settings, self.polygon, self.fmp, self.roic)
        self.conviction = ConvictionSelector(self.settings, self.polygon, self.fmp)

    def run_scan(self, force: bool = False) -> None:
        now = self.calendar.now()
        if not force and not self.calendar.is_agent_active(now):
            logger.info("Outside agent window — skipping scan")
            return

        trading_date = now.strftime("%Y-%m-%d")
        slots = self.state.remaining_daily_slots(trading_date, self.settings.max_daily_alerts)
        if slots <= 0:
            logger.info("Daily alert limit reached (%d) — skipping scan", self.settings.max_daily_alerts)
            return

        if force:
            phase = "regular"
            logger.info("Force mode — ignoring market hours")
        else:
            phase = "premarket" if self.calendar.is_premarket_window(now) else "regular"
        logger.info("Starting %s scan at %s (%d daily slots left)", phase, now.isoformat(), slots)

        watchlist = self.trending.discover_trending()
        focus = watchlist[: self.settings.max_analysis_symbols]
        symbols = [s.symbol for s in focus]
        self.state.update_watchlist(symbols)
        logger.info("Focus list: %d symbols — %s", len(symbols), ", ".join(symbols[:8]))

        candidates: list[Alert] = []
        candidates.extend(self.breakout.detect_breakouts(focus))
        candidates.extend(self.direction.detect_direction_changes(focus))
        candidates.extend(self.catalyst.find_catalyst_alerts(symbols))
        candidates.extend(self.catalyst.find_upside_candidates(symbols))
        candidates.extend(self._xai_catalyst_alerts(symbols[:6]))

        logger.info("Raw candidate signals: %d", len(candidates))

        top_picks = self.conviction.select_top_picks(candidates, focus, slots_available=slots)
        logger.info("High conviction picks: %d", len(top_picks))

        self._dispatch_alerts(top_picks, trading_date)
        self.state.set_last_scan()

    def _xai_catalyst_alerts(self, symbols: list[str]) -> list[Alert]:
        if not self.settings.enable_xai_catalyst_search:
            return []

        alerts: list[Alert] = []
        for symbol in symbols:
            if self.state.already_alerted_today(symbol, self.calendar.now().strftime("%Y-%m-%d")):
                continue
            context_parts = []
            try:
                news = self.polygon.get_news(symbol, limit=3)
                context_parts.extend(f"- {n.title}" for n in news)
            except Exception:
                pass
            insight = self.xai.analyze_catalysts(symbol, "\n".join(context_parts))
            if insight:
                alerts.extend(self.xai.to_alerts(insight))
        return alerts

    def _dispatch_alerts(self, alerts: list[Alert], trading_date: str) -> None:
        for alert in alerts:
            if self.state.already_alerted_today(alert.symbol, trading_date):
                logger.info("Already alerted on %s today — skipping", alert.symbol)
                continue

            if alert.confidence < self.settings.min_alert_confidence:
                logger.info("Below confidence threshold: %s (%.0f%%)", alert.symbol, alert.confidence * 100)
                continue

            validated = self.claude.validate_alert(alert)
            if not validated:
                continue

            if self.telegram.send(validated):
                self.state.mark_daily_alert(alert.symbol, trading_date)
                self.state.mark_alert_sent(f"conviction:{alert.symbol}")
                logger.info(
                    "Sent high conviction alert: %s @ $%.2f → $%.2f",
                    alert.symbol,
                    validated.metadata.get("current_price", 0),
                    validated.metadata.get("price_target", 0),
                )

    def send_startup_message(self) -> None:
        now = self.calendar.now()
        self.telegram.send_text(
            f"Agent started at {now.strftime('%Y-%m-%d %H:%M %Z')}. "
            f"Max {self.settings.max_daily_alerts} high-conviction alerts per day. "
            f"Each alert includes current price and 2-4 week target."
        )

    def close(self) -> None:
        self.polygon.close()
        self.fmp.close()
        self.roic.close()
        self.xai.close()
        self.telegram.close()