import logging
from datetime import datetime, timedelta
from typing import Any

from src.config import Settings
from src.models import NewsItem, StockSnapshot
from src.utils.http import HttpClient

logger = logging.getLogger(__name__)


class PolygonClient:
    """Polygon REST client — no websockets."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.http = HttpClient(settings.polygon_base_url)

    def _params(self, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        params = {"apiKey": self.settings.polygon_api_key}
        if extra:
            params.update(extra)
        return params

    def get_gainers(self) -> list[StockSnapshot]:
        data = self.http.get(
            "/v2/snapshot/locale/us/markets/stocks/gainers",
            params=self._params(),
        )
        return self._parse_snapshot_tickers(data.get("tickers", []), "polygon_gainers")

    def get_losers(self) -> list[StockSnapshot]:
        data = self.http.get(
            "/v2/snapshot/locale/us/markets/stocks/losers",
            params=self._params(),
        )
        return self._parse_snapshot_tickers(data.get("tickers", []), "polygon_losers")

    def get_ticker_snapshot(self, symbol: str) -> StockSnapshot | None:
        data = self.http.get(
            f"/v2/snapshot/locale/us/markets/stocks/tickers/{symbol.upper()}",
            params=self._params(),
        )
        ticker = data.get("ticker")
        if not ticker:
            return None
        parsed = self._parse_snapshot_tickers([ticker], "polygon_snapshot")
        return parsed[0] if parsed else None

    def get_aggregates(self, symbol: str, days: int = 20) -> list[dict[str, Any]]:
        end = datetime.utcnow().date()
        start = end - timedelta(days=days + 10)
        data = self.http.get(
            f"/v2/aggs/ticker/{symbol.upper()}/range/1/day/{start}/{end}",
            params=self._params({"adjusted": "true", "sort": "asc", "limit": 50000}),
        )
        return data.get("results", [])

    def get_news(self, symbol: str | None = None, limit: int = 20) -> list[NewsItem]:
        params: dict[str, Any] = {"limit": limit, "order": "desc", "sort": "published_utc"}
        if symbol:
            params["ticker"] = symbol.upper()
        data = self.http.get("/v2/reference/news", params=self._params(params))
        items: list[NewsItem] = []
        for article in data.get("results", []):
            tickers = article.get("tickers") or []
            sym = tickers[0] if tickers else (symbol or "MARKET")
            published = article.get("published_utc")
            items.append(
                NewsItem(
                    symbol=sym,
                    title=article.get("title", ""),
                    summary=article.get("description", "") or article.get("insights", [{}])[0].get("sentiment_reasoning", "") if article.get("insights") else "",
                    url=article.get("article_url", ""),
                    published_at=datetime.fromisoformat(published.replace("Z", "+00:00")) if published else None,
                    source="polygon",
                    tickers=tickers,
                    queried_symbol=symbol.upper() if symbol else "",
                )
            )
        return items

    def _parse_snapshot_tickers(self, tickers: list[dict], source: str) -> list[StockSnapshot]:
        results: list[StockSnapshot] = []
        for t in tickers:
            sym = t.get("ticker") or t.get("T")
            if not sym:
                continue
            day = t.get("day") or {}
            prev = t.get("prevDay") or {}
            last_trade = t.get("lastTrade") or {}
            price = last_trade.get("p") or day.get("c") or prev.get("c") or 0
            prev_close = prev.get("c") or 0
            change_pct = ((price - prev_close) / prev_close * 100) if prev_close else t.get("todaysChangePerc", 0)
            results.append(
                StockSnapshot(
                    symbol=sym,
                    price=float(price),
                    change_pct=float(change_pct or 0),
                    volume=int(day.get("v") or 0),
                    prev_close=float(prev_close) if prev_close else None,
                    day_high=float(day.get("h")) if day.get("h") else None,
                    day_low=float(day.get("l")) if day.get("l") else None,
                    vwap=float(day.get("vw")) if day.get("vw") else None,
                    source=source,
                )
            )
        return results

    def close(self) -> None:
        self.http.close()