import logging
from collections import defaultdict

from src.config import Settings
from src.data import FMPClient, PolygonClient, ROICClient
from src.models import StockSnapshot
from src.semiconductor.universe import SemiconductorUniverse

logger = logging.getLogger(__name__)


class SemiconductorTrendingAnalyzer:
    """Discover trending movers within the semiconductor universe only."""

    def __init__(
        self,
        settings: Settings,
        polygon: PolygonClient,
        fmp: FMPClient,
        roic: ROICClient,
        universe: SemiconductorUniverse,
    ):
        self.settings = settings
        self.polygon = polygon
        self.fmp = fmp
        self.roic = roic
        self.universe = universe

    def discover_trending(self) -> list[StockSnapshot]:
        self.universe.enrich_from_screener()
        buckets: dict[str, list[StockSnapshot]] = defaultdict(list)
        seed_symbols: list[str] = []

        for source_name, fetch in [
            ("polygon_gainers", self.polygon.get_gainers),
            ("fmp_gainers", self.fmp.get_gainers),
            ("fmp_actives", self.fmp.get_actives),
        ]:
            try:
                for snap in fetch():
                    if not self.universe.is_semiconductor(snap.symbol):
                        continue
                    if self._passes_filters(snap):
                        snap.extra["semi_category"] = self.universe.get_category(snap.symbol)
                        buckets[snap.symbol].append(snap)
                        seed_symbols.append(snap.symbol)
            except Exception as exc:
                logger.warning("Semi trending fetch failed for %s: %s", source_name, exc)

        # Always poll core semi universe for price momentum
        for symbol in sorted(self.universe.symbols):
            if symbol in buckets:
                continue
            try:
                quote = self.fmp.get_quote(symbol)
                if quote and self._passes_filters(quote):
                    quote.extra["semi_category"] = self.universe.get_category(symbol)
                    buckets[symbol].append(quote)
            except Exception:
                pass

        try:
            semi_seeds = [s for s in seed_symbols if self.universe.is_semiconductor(s)]
            for snap in self.roic.get_trending(seed_symbols=semi_seeds[:20]):
                if self.universe.is_semiconductor(snap.symbol) and self._passes_filters(snap):
                    snap.extra["semi_category"] = self.universe.get_category(snap.symbol)
                    buckets[snap.symbol].append(snap)
        except Exception as exc:
            logger.warning("Semi ROIC prices failed: %s", exc)

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
        category = snaps[0].extra.get("semi_category", "")
        category_bonus = {"gpu": 3, "memory": 2.5, "cpu": 2, "networking": 2, "equipment": 1.5}.get(category, 0)
        return source_weight + max_change + volume_score + category_bonus