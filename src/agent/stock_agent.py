import logging
from datetime import datetime

from src.ai import ClaudeClient, XAIClient
from src.alerts import TelegramAlerter
from src.analysis import BreakoutAnalyzer, CatalystAnalyzer, DirectionAnalyzer, TrendingAnalyzer
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

    def run_scan(self) -> None:
        now = self.calendar.now()
        if not self.calendar.is_agent_active(now):
            logger.info("Outside agent window — skipping scan")
            return

        phase = "premarket" if self.calendar.is_premarket_window(now) else "regular"
        logger.info("Starting %s scan at %s", phase, now.isoformat())

        watchlist = self.trending.discover_trending()
        symbols = [s.symbol for s in watchlist]
        self.state.update_watchlist(symbols)
        logger.info("Watchlist: %d symbols — %s", len(symbols), ", ".join(symbols[:10]))

        alerts: list[Alert] = []

        if phase == "premarket":
            alerts.extend(self._premarket_alerts(watchlist))

        alerts.extend(self.breakout.detect_breakouts(watchlist))
        alerts.extend(self.direction.detect_direction_changes(watchlist))
        alerts.extend(self.catalyst.find_catalyst_alerts(symbols))

        if phase == "premarket" or len(alerts) < 3:
            alerts.extend(self.catalyst.find_upside_candidates())

        alerts.extend(self._xai_catalyst_alerts(symbols[:8]))

        self._dispatch_alerts(alerts)
        self.state.set_last_scan()

    def _premarket_alerts(self, watchlist: list) -> list[Alert]:
        alerts: list[Alert] = []
        for snap in watchlist[:15]:
            if snap.change_pct >= 3.0:
                alerts.append(
                    Alert(
                        alert_type=AlertType.PREMARKET,
                        symbol=snap.symbol,
                        title="Pre-market momentum leader",
                        message=(
                            f"{snap.symbol} is up {snap.change_pct:+.1f}% pre-market "
                            f"at ${snap.price:.2f}. Volume: {snap.volume:,}. "
                            "Watch for continuation or fade at the open."
                        ),
                        confidence=min(0.85, 0.5 + snap.change_pct / 20),
                    )
                )
        if watchlist:
            top = watchlist[0]
            alerts.append(
                Alert(
                    alert_type=AlertType.TRENDING,
                    symbol="MARKET",
                    title="Pre-market trending scan complete",
                    message=(
                        f"Top mover: {top.symbol} ({top.change_pct:+.1f}%). "
                        f"Tracking {len(watchlist)} symbols today: "
                        f"{', '.join(s.symbol for s in watchlist[:8])}."
                    ),
                    confidence=0.8,
                )
            )
        return alerts

    def _xai_catalyst_alerts(self, symbols: list[str]) -> list[Alert]:
        alerts: list[Alert] = []
        for symbol in symbols:
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

    def _dispatch_alerts(self, alerts: list[Alert]) -> None:
        seen: set[str] = set()
        for alert in alerts:
            dedupe_key = f"{alert.alert_type.value}:{alert.symbol}:{alert.title[:40]}"
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)

            state_key = f"{alert.alert_type.value}:{alert.symbol}"
            if not self.state.should_send_alert(state_key, cooldown_minutes=45):
                continue

            validated = self.claude.validate_alert(alert)
            if not validated:
                continue

            if self.telegram.send(validated):
                self.state.mark_alert_sent(state_key)

    def send_startup_message(self) -> None:
        now = self.calendar.now()
        self.telegram.send_text(
            f"Agent started at {now.strftime('%Y-%m-%d %H:%M %Z')}. "
            f"Pre-market analysis begins {self.settings.premarket_start_minutes_before_open} min before open. "
            f"Scan interval: {self.settings.scan_interval_minutes} min."
        )

    def close(self) -> None:
        self.polygon.close()
        self.fmp.close()
        self.roic.close()
        self.xai.close()
        self.telegram.close()