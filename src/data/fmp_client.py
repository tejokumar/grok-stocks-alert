import logging
from datetime import datetime
from typing import Any

from src.config import Settings
from src.models import NewsItem, StockSnapshot
from src.utils.http import HttpClient

logger = logging.getLogger(__name__)


class FMPClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.http = HttpClient(settings.fmp_base_url)

    def _params(self, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        params = {"apikey": self.settings.fmp_api_key}
        if extra:
            params.update(extra)
        return params

    def get_gainers(self) -> list[StockSnapshot]:
        data = self.http.get("/stock_market/gainers", params=self._params())
        return self._parse_movers(data, "fmp_gainers")

    def get_losers(self) -> list[StockSnapshot]:
        data = self.http.get("/stock_market/losers", params=self._params())
        return self._parse_movers(data, "fmp_losers")

    def get_actives(self) -> list[StockSnapshot]:
        data = self.http.get("/stock_market/actives", params=self._params())
        return self._parse_movers(data, "fmp_actives")

    def get_quote(self, symbol: str) -> StockSnapshot | None:
        data = self.http.get(f"/quote/{symbol.upper()}", params=self._params())
        if not data:
            return None
        q = data[0] if isinstance(data, list) else data
        return StockSnapshot(
            symbol=q.get("symbol", symbol.upper()),
            price=float(q.get("price", 0)),
            change_pct=float(q.get("changesPercentage", 0)),
            volume=int(q.get("volume", 0)),
            prev_close=float(q.get("previousClose", 0)) if q.get("previousClose") else None,
            day_high=float(q.get("dayHigh", 0)) if q.get("dayHigh") else None,
            day_low=float(q.get("dayLow", 0)) if q.get("dayLow") else None,
            source="fmp_quote",
        )

    def get_news(self, symbol: str | None = None, limit: int = 20) -> list[NewsItem]:
        if symbol:
            path = f"/stock_news"
            params = self._params({"tickers": symbol.upper(), "limit": limit})
        else:
            path = "/stock_news"
            params = self._params({"limit": limit})
        data = self.http.get(path, params=params)
        items: list[NewsItem] = []
        for article in data or []:
            published = article.get("publishedDate")
            items.append(
                NewsItem(
                    symbol=article.get("symbol", symbol or "MARKET"),
                    title=article.get("title", ""),
                    summary=article.get("text", "")[:500],
                    url=article.get("url", ""),
                    published_at=datetime.strptime(published, "%Y-%m-%d %H:%M:%S") if published else None,
                    source="fmp",
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
            "/stock-screener",
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
            results.append(
                StockSnapshot(
                    symbol=row.get("symbol", ""),
                    price=float(row.get("price", 0)),
                    change_pct=float(row.get("changesPercentage", 0)),
                    volume=int(row.get("volume", 0)),
                    source=source,
                )
            )
        return [r for r in results if r.symbol]

    def close(self) -> None:
        self.http.close()