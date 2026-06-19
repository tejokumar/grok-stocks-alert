import logging
from collections import defaultdict

from src.config import Settings
from src.data import FMPClient, PolygonClient, ROICClient
from src.models import StockSnapshot

logger = logging.getLogger(__name__)


class TrendingAnalyzer:
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

    def discover_trending(self) -> list[StockSnapshot]:
        buckets: dict[str, list[StockSnapshot]] = defaultdict(list)
        seed_symbols: list[str] = []

        for source_name, fetch in [
            ("polygon_gainers", self.polygon.get_gainers),
            ("fmp_gainers", self.fmp.get_gainers),
            ("fmp_actives", self.fmp.get_actives),
        ]:
            try:
                for snap in fetch():
                    if self._passes_filters(snap):
                        buckets[snap.symbol].append(snap)
                        seed_symbols.append(snap.symbol)
            except Exception as exc:
                logger.warning("Trending fetch failed for %s: %s", source_name, exc)

        try:
            for snap in self.roic.get_trending(seed_symbols=seed_symbols[:20]):
                if self._passes_filters(snap):
                    buckets[snap.symbol].append(snap)
        except Exception as exc:
            logger.warning("Trending fetch failed for roic_prices: %s", exc)

        scored: list[tuple[float, StockSnapshot]] = []
        for symbol, snaps in buckets.items():
            best = max(snaps, key=lambda s: abs(s.change_pct))
            score = self._score_symbol(snaps)
            scored.append((score, best))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [snap for _, snap in scored[: self.settings.max_watchlist_size]]

    def _passes_filters(self, snap: StockSnapshot) -> bool:
        if not snap.symbol or len(snap.symbol) > 5:
            return False
        if snap.price and snap.price < self.settings.min_price:
            return False
        if snap.volume and snap.volume < self.settings.min_volume:
            return False
        return True

    def _score_symbol(self, snaps: list[StockSnapshot]) -> float:
        source_weight = len(snaps) * 2
        max_change = max(abs(s.change_pct) for s in snaps)
        volumes = [s.volume for s in snaps if s.volume]
        volume_score = (max(volumes) / 1_000_000) if volumes else 0
        return source_weight + max_change + volume_score