import logging
from datetime import datetime
from typing import Any

from src.config import Settings
from src.models import NewsItem, StockSnapshot
from src.utils.http import HttpClient

logger = logging.getLogger(__name__)


class FMPClient:
    """FMP stable REST client (paid tier)."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.http = HttpClient(settings.fmp_base_url)

    def _params(self, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        params = {"apikey": self.settings.fmp_api_key}
        if extra:
            params.update(extra)
        return params

    def get_gainers(self) -> list[StockSnapshot]:
        data = self.http.get("/biggest-gainers", params=self._params())
        return self._parse_movers(data, "fmp_gainers")

    def get_losers(self) -> list[StockSnapshot]:
        data = self.http.get("/biggest-losers", params=self._params())
        return self._parse_movers(data, "fmp_losers")

    def get_actives(self) -> list[StockSnapshot]:
        data = self.http.get("/most-actives", params=self._params())
        return self._parse_movers(data, "fmp_actives")

    def get_quote(self, symbol: str) -> StockSnapshot | None:
        data = self.http.get("/quote", params=self._params({"symbol": symbol.upper()}))
        if not data:
            return None
        q = data[0] if isinstance(data, list) else data
        return StockSnapshot(
            symbol=q.get("symbol", symbol.upper()),
            price=float(q.get("price", 0)),
            change_pct=float(q.get("changePercentage", q.get("changesPercentage", 0))),
            volume=int(q.get("volume", 0)),
            prev_close=float(q.get("previousClose", 0)) if q.get("previousClose") else None,
            day_high=float(q.get("dayHigh", 0)) if q.get("dayHigh") else None,
            day_low=float(q.get("dayLow", 0)) if q.get("dayLow") else None,
            source="fmp_quote",
        )

    def get_news(self, symbol: str | None = None, limit: int = 20) -> list[NewsItem]:
        if symbol:
            data = self.http.get(
                "/news/stock",
                params=self._params({"symbols": symbol.upper(), "limit": limit}),
            )
        else:
            data = self.http.get(
                "/news/stock-latest",
                params=self._params({"limit": limit, "page": 0}),
            )
        items: list[NewsItem] = []
        for article in data or []:
            published = article.get("publishedDate")
            sym = article.get("symbol", symbol or "MARKET")
            items.append(
                NewsItem(
                    symbol=sym,
                    title=article.get("title", ""),
                    summary=article.get("text", "")[:500],
                    url=article.get("url", ""),
                    published_at=(
                        datetime.strptime(published, "%Y-%m-%d %H:%M:%S") if published else None
                    ),
                    source="fmp",
                    tickers=[sym] if sym else [],
                    queried_symbol=symbol.upper() if symbol else "",
                )
            )
        return items

    def get_stock_screener(
        self,
        market_cap_more_than: int = 300_000_000,
        volume_more_than: int = 500_000,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        return self.http.get(
            "/company-screener",
            params=self._params({
                "marketCapMoreThan": market_cap_more_than,
                "volumeMoreThan": volume_more_than,
                "isActivelyTrading": True,
                "limit": limit,
            }),
        )

    def _parse_movers(self, data: list[dict], source: str) -> list[StockSnapshot]:
        results: list[StockSnapshot] = []
        for row in data or []:
            symbol = row.get("symbol", "")
            if not symbol:
                continue
            results.append(
                StockSnapshot(
                    symbol=symbol,
                    price=float(row.get("price", 0)),
                    change_pct=float(row.get("changesPercentage", row.get("changePercentage", 0))),
                    volume=int(row.get("volume", 0)),
                    source=source,
                )
            )
        return results

    def close(self) -> None:
        self.http.close()