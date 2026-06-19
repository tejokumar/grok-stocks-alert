import logging
from statistics import mean

from src.config import Settings
from src.data.polygon_client import PolygonClient
from src.models import Alert, AlertType, StockSnapshot

logger = logging.getLogger(__name__)


class BreakoutAnalyzer:
    def __init__(self, settings: Settings, polygon: PolygonClient):
        self.settings = settings
        self.polygon = polygon

    def detect_breakouts(self, watchlist: list[StockSnapshot]) -> list[Alert]:
        alerts: list[Alert] = []
        for snap in watchlist:
            try:
                alert = self._check_symbol(snap)
                if alert:
                    alerts.append(alert)
            except Exception as exc:
                logger.warning("Breakout check failed for %s: %s", snap.symbol, exc)
        return alerts

    def _check_symbol(self, snap: StockSnapshot) -> Alert | None:
        bars = self.polygon.get_aggregates(snap.symbol, days=25)
        if len(bars) < 10:
            return None

        closes = [b["c"] for b in bars[:-1]]
        volumes = [b["v"] for b in bars[:-1]]
        avg_close = mean(closes[-20:]) if len(closes) >= 20 else mean(closes)
        avg_volume = mean(volumes[-20:]) if len(volumes) >= 20 else mean(volumes)

        price = snap.price or bars[-1]["c"]
        volume = snap.volume or bars[-1]["v"]
        resistance = max(closes[-20:]) if len(closes) >= 20 else max(closes)

        price_break = price > resistance and ((price - avg_close) / avg_close * 100) >= self.settings.breakout_price_pct
        volume_surge = volume >= avg_volume * self.settings.breakout_volume_multiplier

        if not (price_break and volume_surge):
            return None

        pct_above = (price - resistance) / resistance * 100
        return Alert(
            alert_type=AlertType.BREAKOUT,
            symbol=snap.symbol,
            title="Volume breakout above resistance",
            message=(
                f"Price ${price:.2f} broke 20-day high ${resistance:.2f} (+{pct_above:.1f}%). "
                f"Volume {volume:,} is {volume / avg_volume:.1f}x the 20-day average. "
                f"Day change: {snap.change_pct:+.1f}%."
            ),
            confidence=min(0.95, 0.5 + pct_above / 20 + (volume / avg_volume) / 10),
            metadata={"resistance": resistance, "avg_volume": avg_volume},
        )