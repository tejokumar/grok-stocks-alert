import logging

from src.models import Alert, AlertType, StockSnapshot
from src.utils.state import AgentState

logger = logging.getLogger(__name__)


class DirectionAnalyzer:
    def __init__(self, state: AgentState):
        self.state = state

    def detect_direction_changes(self, watchlist: list[StockSnapshot]) -> list[Alert]:
        alerts: list[Alert] = []
        for snap in watchlist:
            alert = self._check_symbol(snap)
            if alert:
                alerts.append(alert)
        return alerts

    def _check_symbol(self, snap: StockSnapshot) -> Alert | None:
        baseline = self.state.get_baseline(snap.symbol)
        current = {
            "price": snap.price,
            "change_pct": snap.change_pct,
            "volume": snap.volume,
        }

        if not baseline:
            self.state.set_baseline(snap.symbol, current)
            return None

        prev_trend = baseline.get("change_pct", 0)
        curr_trend = snap.change_pct

        was_bullish = prev_trend >= 2.0
        was_bearish = prev_trend <= -2.0
        now_bullish = curr_trend >= 2.0
        now_bearish = curr_trend <= -2.0

        reversal = (was_bullish and now_bearish) or (was_bearish and now_bullish)
        momentum_fade = was_bullish and 0 <= curr_trend < prev_trend - 3

        self.state.set_baseline(snap.symbol, current)

        if reversal:
            direction = "bearish" if was_bullish else "bullish"
            return Alert(
                alert_type=AlertType.DIRECTION_CHANGE,
                symbol=snap.symbol,
                title=f"Trend reversal — shifting {direction}",
                message=(
                    f"Prior session momentum was {prev_trend:+.1f}%, now {curr_trend:+.1f}%. "
                    f"Price ${snap.price:.2f}, volume {snap.volume:,}. "
                    "Consider tightening stops or reducing exposure."
                ),
                confidence=0.75,
                metadata={"prev_change": prev_trend, "curr_change": curr_trend},
            )

        if momentum_fade:
            return Alert(
                alert_type=AlertType.DIRECTION_CHANGE,
                symbol=snap.symbol,
                title="Bullish momentum fading",
                message=(
                    f"Was up {prev_trend:+.1f}%, now only {curr_trend:+.1f}%. "
                    f"Price ${snap.price:.2f}. Trending stock may be losing steam."
                ),
                confidence=0.65,
                metadata={"prev_change": prev_trend, "curr_change": curr_trend},
            )

        return None