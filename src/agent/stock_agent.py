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
        logger.info("Strong catalyst alerts: %d", len(catalyst_alerts))
        self._dispatch_catalyst_alerts(catalyst_alerts)

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
                alert.metadata["catalyst_key"] = f"xai:{symbol}:{insight.summary[:60]}"
                if alert.confidence >= self.settings.min_catalyst_confidence:
                    alerts.append(alert)
        return alerts

    def _enrich_with_price(self, alert: Alert, watchlist_by_symbol: dict[str, StockSnapshot] | None = None) -> Alert:
        snap = (watchlist_by_symbol or {}).get(alert.symbol)
        price = snap.price if snap and snap.price > 0 else 0.0
        if price <= 0:
            try:
                quote = self.fmp.get_quote(alert.symbol)
                if quote:
                    price = quote.price
            except Exception:
                pass

        if price > 0:
            pick = self.conviction._build_pick(alert.symbol, [alert], snap)
            alert.metadata["current_price"] = price
            alert.metadata["price_target"] = pick.price_target
            alert.metadata["target_pct"] = pick.target_pct
            price_block = (
                f"Current Price: ${price:.2f}\n"
                f"2-4 Week Target: ${pick.price_target:.2f} ({pick.target_pct:+.1f}%)\n\n"
            )
            if "Current Price:" not in alert.message:
                alert.message = price_block + alert.message
        return alert

    def _dispatch_catalyst_alerts(self, alerts: list[Alert]) -> None:
        alerts.sort(key=lambda a: a.confidence, reverse=True)
        seen_keys: set[str] = set()
        sent_symbols: set[str] = set()

        for alert in alerts:
            key = alert.metadata.get("catalyst_key", f"{alert.symbol}:{alert.title[:50]}")
            if key in seen_keys:
                continue
            seen_keys.add(key)

            if not self.state.should_send_alert(key, cooldown_minutes=self.settings.catalyst_cooldown_minutes):
                continue

            symbol_key = f"catalyst:{alert.symbol}"
            if not self.state.should_send_alert(symbol_key, cooldown_minutes=self.settings.catalyst_cooldown_minutes):
                continue
            if symbol_key in sent_symbols:
                continue

            alert = self._enrich_with_price(alert)
            if self.telegram.send(alert):
                self.state.mark_alert_sent(key)
                self.state.mark_alert_sent(symbol_key)
                sent_symbols.add(symbol_key)
                logger.info("Sent catalyst alert: %s — %s", alert.symbol, alert.title[:60])

    def _dispatch_conviction_alerts(self, alerts: list[Alert]) -> None:
        for alert in alerts:
            if alert.confidence < self.settings.min_alert_confidence:
                continue

            key = f"conviction:{alert.symbol}:{alert.title[:40]}"
            if not self.state.should_send_alert(key, cooldown_minutes=240):
                continue

            validated = self.claude.validate_alert(alert)
            if not validated:
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
            f"Consolidated high-conviction picks sent when multi-signal setups appear."
        )

    def close(self) -> None:
        self.polygon.close()
        self.fmp.close()
        self.roic.close()
        self.xai.close()
        self.telegram.close()