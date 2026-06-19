import logging
from dataclasses import dataclass, field

from src.config import Settings
from src.data.fmp_client import FMPClient
from src.data.polygon_client import PolygonClient
from src.models import Alert, AlertType, StockSnapshot

logger = logging.getLogger(__name__)

SIGNAL_WEIGHTS = {
    AlertType.BREAKOUT: 0.30,
    AlertType.CATALYST: 0.22,
    AlertType.UPSIDE_POTENTIAL: 0.28,
    AlertType.PREMARKET: 0.15,
    AlertType.DIRECTION_CHANGE: 0.10,
}


@dataclass
class ConsolidatedPick:
    symbol: str
    alerts: list[Alert] = field(default_factory=list)
    snapshot: StockSnapshot | None = None
    conviction_score: float = 0.0
    current_price: float = 0.0
    price_target: float = 0.0
    signal_types: list[str] = field(default_factory=list)

    @property
    def target_pct(self) -> float:
        if not self.current_price:
            return 0.0
        return (self.price_target - self.current_price) / self.current_price * 100


class ConvictionSelector:
    def __init__(
        self,
        settings: Settings,
        polygon: PolygonClient,
        fmp: FMPClient,
    ):
        self.settings = settings
        self.polygon = polygon
        self.fmp = fmp

    def select_top_picks(
        self,
        alerts: list[Alert],
        watchlist: list[StockSnapshot],
        slots_available: int,
    ) -> list[Alert]:
        if slots_available <= 0:
            return []

        watchlist_by_symbol = {s.symbol: s for s in watchlist}
        grouped = self._group_by_symbol(alerts)
        picks: list[ConsolidatedPick] = []

        for symbol, symbol_alerts in grouped.items():
            if symbol == "MARKET" or len(symbol) > 5:
                continue
            pick = self._build_pick(symbol, symbol_alerts, watchlist_by_symbol.get(symbol))
            if pick.conviction_score >= self.settings.min_conviction_score:
                picks.append(pick)

        picks = [p for p in picks if p.current_price >= self.settings.min_conviction_price]
        picks.sort(key=lambda p: p.conviction_score, reverse=True)
        top = picks[:slots_available]

        final_alerts: list[Alert] = []
        for pick in top:
            alert = self._to_high_conviction_alert(pick)
            if alert.confidence >= self.settings.min_alert_confidence:
                final_alerts.append(alert)

        return final_alerts

    def _group_by_symbol(self, alerts: list[Alert]) -> dict[str, list[Alert]]:
        grouped: dict[str, list[Alert]] = {}
        skip_types = {AlertType.TRENDING}
        for alert in alerts:
            if alert.alert_type in skip_types:
                continue
            grouped.setdefault(alert.symbol, []).append(alert)
        return grouped

    def _build_pick(
        self,
        symbol: str,
        alerts: list[Alert],
        snapshot: StockSnapshot | None,
    ) -> ConsolidatedPick:
        pick = ConsolidatedPick(symbol=symbol, alerts=alerts, snapshot=snapshot)

        type_confidence: dict[AlertType, float] = {}
        for alert in alerts:
            existing = type_confidence.get(alert.alert_type, 0.0)
            type_confidence[alert.alert_type] = max(existing, alert.confidence)

        signal_types = [t.value for t in type_confidence]
        pick.signal_types = signal_types
        unique_signals = len(type_confidence)
        peak_confidence = max(type_confidence.values()) if type_confidence else 0.0

        has_breakout = AlertType.BREAKOUT in type_confidence
        has_catalyst = AlertType.CATALYST in type_confidence
        has_upside = AlertType.UPSIDE_POTENTIAL in type_confidence
        has_actionable = has_breakout or has_upside

        if not has_actionable and peak_confidence < 0.88:
            pick.conviction_score = 0.0
            pick.current_price = self._resolve_price(symbol, snapshot)
            return pick

        base_score = sum(
            SIGNAL_WEIGHTS.get(alert_type, 0.10) * confidence
            for alert_type, confidence in type_confidence.items()
        )

        if unique_signals >= 3:
            base_score += 0.10
        elif unique_signals >= 2:
            base_score += 0.08

        if has_breakout and has_catalyst:
            base_score += 0.12
        if has_upside and (has_breakout or has_catalyst):
            base_score += 0.08
        if peak_confidence >= 0.90:
            base_score += 0.05

        pick.conviction_score = min(0.98, base_score)
        pick.current_price = self._resolve_price(symbol, snapshot)
        pick.price_target = self._compute_price_target(pick)
        return pick

    def _resolve_price(self, symbol: str, snapshot: StockSnapshot | None) -> float:
        if snapshot and snapshot.price > 0:
            return snapshot.price
        try:
            quote = self.fmp.get_quote(symbol)
            if quote and quote.price > 0:
                return quote.price
        except Exception as exc:
            logger.warning("Quote fetch failed for %s: %s", symbol, exc)
        return 0.0

    def _compute_price_target(self, pick: ConsolidatedPick) -> float:
        price = pick.current_price
        if price <= 0:
            return 0.0

        resistance = price
        support = price * 0.92
        momentum_pct = 0.0

        try:
            bars = self.polygon.get_aggregates(pick.symbol, days=25)
            if len(bars) >= 10:
                closes = [b["c"] for b in bars[:-1]]
                resistance = max(closes[-20:]) if len(closes) >= 20 else max(closes)
                support = min(closes[-20:]) if len(closes) >= 20 else min(closes)
        except Exception as exc:
            logger.warning("Target bars failed for %s: %s", pick.symbol, exc)

        if pick.snapshot:
            momentum_pct = max(0.0, pick.snapshot.change_pct)

        range_height = max(resistance - support, price * 0.05)
        measured_move = price + range_height * 0.75
        momentum_target = price * (1 + min(0.18, max(0.06, momentum_pct / 100 * 1.5)))

        for alert in pick.alerts:
            if alert.alert_type == AlertType.BREAKOUT:
                res = alert.metadata.get("resistance")
                if res and res > 0:
                    measured_move = max(measured_move, price + (price - res) * 0.5 + range_height * 0.5)

        target = max(measured_move, momentum_target)
        target = min(target, price * 1.22)
        target = max(target, price * 1.04)
        return round(target, 2)

    def _to_high_conviction_alert(self, pick: ConsolidatedPick) -> Alert:
        primary = max(pick.alerts, key=lambda a: a.confidence)
        thesis_lines = []
        for alert in sorted(pick.alerts, key=lambda a: a.confidence, reverse=True)[:3]:
            thesis_lines.append(f"• [{alert.alert_type.value}] {alert.title}")

        signal_summary = ", ".join(pick.signal_types)
        price_line = f"Current Price: ${pick.current_price:.2f}" if pick.current_price else "Current Price: N/A"
        target_line = (
            f"2-4 Week Target: ${pick.price_target:.2f} ({pick.target_pct:+.1f}%)"
            if pick.price_target
            else "2-4 Week Target: N/A"
        )

        message = (
            f"{price_line}\n"
            f"{target_line}\n\n"
            f"Thesis ({len(pick.signal_types)} converging signals):\n"
            + "\n".join(thesis_lines)
            + f"\n\n{primary.message[:300]}"
        )

        return Alert(
            alert_type=AlertType.UPSIDE_POTENTIAL,
            symbol=pick.symbol,
            title=f"High conviction — {signal_summary}",
            message=message,
            confidence=min(0.98, pick.conviction_score),
            metadata={
                "current_price": pick.current_price,
                "price_target": pick.price_target,
                "target_pct": pick.target_pct,
                "signal_types": pick.signal_types,
                "conviction_score": pick.conviction_score,
            },
        )