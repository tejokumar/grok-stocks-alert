import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.ai import ClaudeClient, XAIClient
from src.alerts import TelegramAlerter
from src.analysis import (
    AnalystGradesAnalyzer,
    BreakoutAnalyzer,
    CatalystAnalyzer,
    ConvictionSelector,
    DirectionAnalyzer,
    ThesisReversalAnalyzer,
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
        self.analyst_grades = AnalystGradesAnalyzer(self.settings, self.fmp)
        self.thesis_reversal = ThesisReversalAnalyzer(
            self.settings, self.state, self.polygon, self.fmp,
        )
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
        catalyst_alerts.extend(self._xai_catalyst_alerts(symbols, phase))

        grade_upgrades, grade_downgrades = self.analyst_grades.scan_symbols(
            symbols, watchlist_by_symbol,
        )
        catalyst_alerts.extend(grade_upgrades)
        logger.info(
            "Analyst grades: %d upgrades, %d downgrades",
            len(grade_upgrades), len(grade_downgrades),
        )

        grade_upgrades_by_symbol = {a.symbol: a for a in grade_upgrades}
        merged = self._merge_catalyst_alerts(catalyst_alerts)
        logger.info("Strong catalyst alerts: %d (merged from %d)", len(merged), len(catalyst_alerts))
        self._dispatch_catalyst_alerts(merged, watchlist_by_symbol, grade_upgrades_by_symbol)

        reversal_alerts = self.thesis_reversal.find_reversals(
            grade_downgrades, watchlist_by_symbol,
        )
        logger.info("Thesis reversal alerts: %d", len(reversal_alerts))
        self._dispatch_thesis_reversals(reversal_alerts, watchlist_by_symbol)

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

    def _collect_news_references(self, symbol: str, limit: int = 3) -> tuple[list[str], list[dict[str, str]]]:
        context_lines: list[str] = []
        references: list[dict[str, str]] = []
        seen_urls: set[str] = set()

        for fetch in (self.polygon.get_news, self.fmp.get_news):
            try:
                for item in fetch(symbol, limit=limit):
                    context_lines.append(f"- {item.title}")
                    if item.url and item.url not in seen_urls:
                        seen_urls.add(item.url)
                        references.append({
                            "title": item.title[:80],
                            "url": item.url,
                            "source": item.source,
                        })
            except Exception:
                pass

        return context_lines, references

    def _merge_alert_references(
        self,
        alert: Alert,
        news_refs: list[dict[str, str]],
        insight_refs: list[dict[str, str]] | None = None,
    ) -> None:
        merged: list[dict[str, str]] = []
        seen_urls: set[str] = set()
        for ref in (insight_refs or []) + news_refs + list(alert.metadata.get("references") or []):
            url = (ref.get("url") or "").strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            merged.append(ref)
        if merged:
            alert.metadata["references"] = merged[:5]
            alert.metadata.setdefault("url", merged[0]["url"])

    def _xai_catalyst_alerts(self, symbols: list[str], phase: str) -> list[Alert]:
        if not self.settings.enable_xai_catalyst_search:
            return []

        scan_symbols = symbols[: self.settings.xai_max_symbols]
        if not scan_symbols:
            return []

        workers = min(self.settings.xai_max_workers, len(scan_symbols))
        logger.info(
            "xAI catalyst scan: %d symbols (%s), %d workers",
            len(scan_symbols), ", ".join(scan_symbols), workers,
        )

        alerts: list[Alert] = []
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(self._xai_scan_symbol, symbol, phase): symbol
                for symbol in scan_symbols
            }
            for future in as_completed(futures):
                symbol = futures[future]
                try:
                    alerts.extend(future.result())
                except Exception as exc:
                    logger.warning("xAI scan failed for %s: %s", symbol, exc)
        return alerts

    def _xai_scan_symbol(self, symbol: str, phase: str) -> list[Alert]:
        context_lines, news_refs = self._collect_news_references(symbol)
        return self._xai_alerts_from_context(symbol, phase, context_lines, news_refs)

    def _xai_alerts_from_context(
        self,
        symbol: str,
        phase: str,
        context_lines: list[str],
        news_refs: list[dict[str, str]],
        *,
        catalyst_key_prefix: str = "",
        alert_title_prefix: str = "",
        extra_metadata: dict | None = None,
    ) -> list[Alert]:
        insight = self.xai.analyze_catalysts(symbol, "\n".join(context_lines))
        if not insight:
            return []

        alerts: list[Alert] = []
        for alert in self.xai.to_alerts(insight):
            if phase == "premarket":
                alert.alert_type = AlertType.PREMARKET
            if alert_title_prefix:
                alert.title = f"{alert_title_prefix}{alert.title}"
            if extra_metadata:
                alert.metadata.update(extra_metadata)
            self._merge_alert_references(alert, news_refs, insight.references)
            alert.metadata["catalyst_key"] = catalyst_dedup_key(
                f"{catalyst_key_prefix}{symbol}",
                insight.summary or alert.title,
                "xai",
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

    def _enrich_with_analyst_grade(
        self,
        alert: Alert,
        grade_alert: Alert | None,
    ) -> Alert:
        if not grade_alert:
            return alert

        company = grade_alert.metadata.get("grading_company", "")
        prev = grade_alert.metadata.get("previous_grade", "")
        new = grade_alert.metadata.get("new_grade", "")
        date = grade_alert.metadata.get("grade_date", "")
        analyst_block = (
            f"\n\n<b>Top analyst upgrade:</b>\n"
            f"• {company} ({date}): {prev} → {new}"
        )
        if "Top analyst upgrade:" not in alert.message:
            alert.message += analyst_block

        self._merge_alert_references(
            alert,
            list(grade_alert.metadata.get("references") or []),
        )
        alert.metadata["analyst_upgrade"] = {
            "grading_company": company,
            "previous_grade": prev,
            "new_grade": new,
            "grade_date": date,
        }
        return alert

    def _is_bullish_alert(self, alert: Alert) -> bool:
        if alert.alert_type in (AlertType.ANALYST_DOWNGRADE, AlertType.THESIS_REVERSAL):
            return False
        if alert.metadata.get("thesis_direction") == "bearish":
            return False
        if alert.metadata.get("sentiment") in ("bearish", "neutral", "mixed"):
            return False
        text = f"{alert.title} {alert.message}".lower()
        bearish_hits = (
            "downgrade", "downgraded", "bearish", "earnings miss", "revenue miss",
            "guidance cut", "lowered guidance", "profit warning", "price target cut",
        )
        return not any(kw in text for kw in bearish_hits)

    def _record_bullish_thesis(self, alert: Alert, dedup_key: str) -> None:
        thesis = {
            "title": alert.title,
            "summary": alert.message[:300],
            "alerted_at": self.calendar.now().isoformat(),
            "price_at_alert": alert.metadata.get("current_price"),
            "target_at_alert": alert.metadata.get("price_target"),
            "references": alert.metadata.get("references", []),
            "catalyst_key": dedup_key,
            "alert_type": alert.alert_type.value,
        }
        if alert.metadata.get("analyst_upgrade"):
            thesis["analyst_upgrade"] = alert.metadata["analyst_upgrade"]
        self.state.set_bullish_thesis(alert.symbol, thesis)

    def _dispatch_catalyst_alerts(
        self,
        alerts: list[Alert],
        watchlist_by_symbol: dict[str, StockSnapshot],
        grade_upgrades_by_symbol: dict[str, Alert] | None = None,
    ) -> None:
        seen_headlines: set[str] = set()
        upgrades = grade_upgrades_by_symbol or {}

        for alert in alerts:
            if not self._is_bullish_alert(alert):
                logger.debug("Skipping non-bullish alert for %s", alert.symbol)
                continue

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

            alert = self._enrich_with_analyst_grade(alert, upgrades.get(alert.symbol))
            alert = self._enrich_with_price(alert, watchlist_by_symbol)
            if alert.metadata.get("price_target", 0) <= 0:
                logger.warning("Skipping %s — could not compute price target", alert.symbol)
                continue

            if self.telegram.send(alert):
                self.state.mark_alert_sent(dedup_key)
                self.state.mark_alert_sent(symbol_key)
                self._record_bullish_thesis(alert, dedup_key)
                logger.info(
                    "Sent catalyst alert: %s @ $%.2f → $%.2f",
                    alert.symbol,
                    alert.metadata.get("current_price", 0),
                    alert.metadata.get("price_target", 0),
                )

    def _dispatch_thesis_reversals(
        self,
        alerts: list[Alert],
        watchlist_by_symbol: dict[str, StockSnapshot],
    ) -> None:
        for alert in alerts:
            dedup_key = alert.metadata.get(
                "catalyst_key",
                catalyst_dedup_key(alert.symbol, alert.title, "thesis_reversal"),
            )
            if not self.state.should_send_alert(dedup_key, cooldown_minutes=self.settings.catalyst_cooldown_minutes):
                logger.debug("Thesis reversal cooldown: %s", alert.symbol)
                continue

            snap = watchlist_by_symbol.get(alert.symbol)
            price = self.conviction._resolve_price(alert.symbol, snap)
            if price > 0:
                alert.metadata["current_price"] = price
                alert.metadata["price_target"] = price * 0.92
                alert.metadata["target_pct"] = -8.0
                if "Current Price:" not in alert.message:
                    alert.message = (
                        f"Current Price: ${price:.2f}\n"
                        f"Revised 2-4 Week Target: ${price * 0.92:.2f} (-8.0%)\n\n"
                        + alert.message
                    )

            if self.telegram.send(alert):
                self.state.mark_alert_sent(dedup_key)
                self.state.mark_thesis_reversed(alert.symbol, {
                    "title": alert.title,
                    "trigger": alert.metadata.get("trigger"),
                    "reversed_at": self.calendar.now().isoformat(),
                })
                logger.info("Sent thesis reversal: %s — %s", alert.symbol, alert.title[:60])

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
            f"Includes top-analyst upgrades/downgrades and thesis reversal alerts. "
            f"First alert per stock is bullish; reversals fire when thesis changes."
        )

    def close(self) -> None:
        self.polygon.close()
        self.fmp.close()
        self.roic.close()
        self.xai.close()
        self.telegram.close()