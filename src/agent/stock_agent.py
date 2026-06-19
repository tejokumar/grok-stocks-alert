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
from src.models import Alert, AlertType, StockSnapshot
from src.utils.dedup import catalyst_dedup_key, normalize_headline
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

        if force:
            phase = "regular"
            logger.info("Force mode — ignoring market hours")
        else:
            phase = "premarket" if self.calendar.is_premarket_window(now) else "regular"
        logger.info("Starting %s scan at %s", phase, now.isoformat())

        watchlist = self.trending.discover_trending()
        focus = watchlist[: self.settings.max_analysis_symbols]
        symbols = [s.symbol for s in watchlist]
        watchlist_by_symbol = {s.symbol: s for s in watchlist}
        self.state.update_watchlist(symbols)
        logger.info("Watchlist: %d symbols — %s", len(symbols), ", ".join(symbols[:8]))

        catalyst_alerts = self.catalyst.find_strong_catalyst_alerts(
            symbols, watchlist_by_symbol, phase=phase,
        )
        catalyst_alerts.extend(self._xai_catalyst_alerts(symbols[:12], phase))
        merged = self._merge_catalyst_alerts(catalyst_alerts)
        logger.info("Strong catalyst alerts: %d (merged from %d)", len(merged), len(catalyst_alerts))
        self._dispatch_catalyst_alerts(merged, watchlist_by_symbol)

        conviction_candidates: list[Alert] = []
        conviction_candidates.extend(self.breakout.detect_breakouts(focus))
        conviction_candidates.extend(self.direction.detect_direction_changes(focus))
        conviction_candidates.extend(self.catalyst.find_upside_candidates(symbols[:20]))

        if self.settings.max_daily_alerts > 0:
            trading_date = now.strftime("%Y-%m-%d")
            slots = self.state.remaining_daily_slots(trading_date, self.settings.max_daily_alerts)
        else:
            slots = self.settings.max_conviction_per_scan

        if slots > 0:
            top_picks = self.conviction.select_top_picks(
                conviction_candidates, focus, slots_available=slots,
            )
            logger.info("High conviction picks: %d", len(top_picks))
            self._dispatch_conviction_alerts(top_picks)

        self.state.set_last_scan()

    def _merge_catalyst_alerts(self, alerts: list[Alert]) -> list[Alert]:
        """Keep only the single best alert per symbol."""
        by_symbol: dict[str, Alert] = {}
        for alert in alerts:
            existing = by_symbol.get(alert.symbol)
            if not existing or alert.confidence > existing.confidence:
                by_symbol[alert.symbol] = alert
        return sorted(by_symbol.values(), key=lambda a: a.confidence, reverse=True)

    def _xai_catalyst_alerts(self, symbols: list[str], phase: str) -> list[Alert]:
        if not self.settings.enable_xai_catalyst_search:
            return []

        alerts: list[Alert] = []
        for symbol in symbols:
            context_parts = []
            try:
                news = self.polygon.get_news(symbol, limit=3)
                context_parts.extend(f"- {n.title}" for n in news)
            except Exception:
                pass
            insight = self.xai.analyze_catalysts(symbol, "\n".join(context_parts))
            if not insight:
                continue
            xai_alerts = self.xai.to_alerts(insight)
            for alert in xai_alerts:
                if phase == "premarket":
                    alert.alert_type = AlertType.PREMARKET
                alert.metadata["catalyst_key"] = catalyst_dedup_key(
                    symbol, insight.summary or alert.title, "xai",
                )
                if alert.confidence >= self.settings.min_catalyst_confidence:
                    alerts.append(alert)
        return alerts

    def _enrich_with_price(
        self,
        alert: Alert,
        watchlist_by_symbol: dict[str, StockSnapshot],
    ) -> Alert:
        snap = watchlist_by_symbol.get(alert.symbol)
        price = self.conviction._resolve_price(alert.symbol, snap)

        if price <= 0:
            alert.metadata["current_price"] = 0.0
            alert.metadata["price_target"] = 0.0
            alert.metadata["target_pct"] = 0.0
            return alert

        target, target_pct = self.conviction.estimate_target(alert.symbol, price, snap)
        alert.metadata["current_price"] = price
        alert.metadata["price_target"] = target
        alert.metadata["target_pct"] = target_pct

        price_block = (
            f"Current Price: ${price:.2f}\n"
            f"2-4 Week Target: ${target:.2f} ({target_pct:+.1f}%)\n\n"
        )
        if "Current Price:" not in alert.message:
            alert.message = price_block + alert.message
        else:
            alert.message = price_block + alert.message.split("\n\n", 1)[-1]

        return alert

    def _dispatch_catalyst_alerts(
        self,
        alerts: list[Alert],
        watchlist_by_symbol: dict[str, StockSnapshot],
    ) -> None:
        seen_headlines: set[str] = set()

        for alert in alerts:
            headline_key = normalize_headline(alert.title)
            if headline_key in seen_headlines:
                continue
            seen_headlines.add(headline_key)

            dedup_key = alert.metadata.get(
                "catalyst_key",
                catalyst_dedup_key(alert.symbol, alert.title),
            )
            symbol_key = f"symbol:{alert.symbol}"

            if not self.state.should_send_alert(dedup_key, cooldown_minutes=self.settings.catalyst_cooldown_minutes):
                logger.debug("Cooldown active for dedup key: %s", dedup_key[:60])
                continue
            if not self.state.should_send_alert(symbol_key, cooldown_minutes=self.settings.catalyst_cooldown_minutes):
                logger.debug("Cooldown active for symbol: %s", alert.symbol)
                continue

            alert = self._enrich_with_price(alert, watchlist_by_symbol)
            if alert.metadata.get("price_target", 0) <= 0:
                logger.warning("Skipping %s — could not compute price target", alert.symbol)
                continue

            if self.telegram.send(alert):
                self.state.mark_alert_sent(dedup_key)
                self.state.mark_alert_sent(symbol_key)
                logger.info(
                    "Sent catalyst alert: %s @ $%.2f → $%.2f",
                    alert.symbol,
                    alert.metadata.get("current_price", 0),
                    alert.metadata.get("price_target", 0),
                )

    def _dispatch_conviction_alerts(self, alerts: list[Alert]) -> None:
        for alert in alerts:
            if alert.confidence < self.settings.min_alert_confidence:
                continue

            key = f"conviction:{alert.symbol}:{normalize_headline(alert.title)}"
            if not self.state.should_send_alert(key, cooldown_minutes=240):
                continue

            validated = self.claude.validate_alert(alert)
            if not validated:
                continue

            if validated.metadata.get("price_target", 0) <= 0:
                continue

            if self.telegram.send(validated):
                self.state.mark_alert_sent(key)
                if self.settings.max_daily_alerts > 0:
                    self.state.mark_daily_alert(
                        alert.symbol, self.calendar.now().strftime("%Y-%m-%d"),
                    )
                logger.info(
                    "Sent conviction alert: %s @ $%.2f → $%.2f",
                    alert.symbol,
                    validated.metadata.get("current_price", 0),
                    validated.metadata.get("price_target", 0),
                )

    def send_startup_message(self) -> None:
        now = self.calendar.now()
        self.telegram.send_text(
            f"Agent started at {now.strftime('%Y-%m-%d %H:%M %Z')}. "
            f"Strong catalyst alerts fire immediately during pre-market and intraday. "
            f"Each alert includes current price and 2-4 week target."
        )

    def close(self) -> None:
        self.polygon.close()
        self.fmp.close()
        self.roic.close()
        self.xai.close()
        self.telegram.close()