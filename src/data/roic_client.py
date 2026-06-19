import logging
from datetime import datetime
from typing import Any

import httpx

from src.config import Settings
from src.models import NewsItem, StockSnapshot
from src.utils.http import HttpClient

logger = logging.getLogger(__name__)

# High-liquidity seed universe used when no symbols are available yet.
LIQUID_SEED_SYMBOLS = [
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA", "AMD", "AVGO", "NFLX",
    "CRM", "ORCL", "QCOM", "INTC", "AMAT", "MU", "COIN", "PLTR", "SOFI", "MARA",
    "RIOT", "SMCI", "ARM", "DELL", "UBER", "ABNB", "SNOW", "NET", "CRWD", "PANW",
]


class ROICClient:
    """ROIC.ai v2 financial data client."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.http = HttpClient(settings.roic_base_url)
        self._direct = httpx.Client(timeout=20.0, follow_redirects=True)

    def _params(self, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        params = {"apikey": self.settings.roic_api_key}
        if extra:
            params.update(extra)
        return params

    def _get_optional(self, path: str, params: dict[str, Any] | None = None) -> Any | None:
        url = f"{self.settings.roic_base_url.rstrip('/')}{path}"
        try:
            response = self._direct.get(url, params=params or self._params())
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as exc:
            logger.debug("ROIC optional fetch failed for %s: %s", path, exc)
            return None

    def get_latest_quote(self, symbol: str) -> StockSnapshot | None:
        data = self._get_optional(
            f"/v2/stock-prices/latest/{symbol.upper()}",
            params=self._params(),
        )
        if not data:
            return None

        row = data[0] if isinstance(data, list) else data
        if not isinstance(row, dict):
            return None

        return StockSnapshot(
            symbol=symbol.upper(),
            price=float(row.get("close", row.get("adj_close", 0))),
            change_pct=float(row.get("change_percent", 0)),
            volume=int(row.get("volume", 0)),
            day_high=float(row.get("high")) if row.get("high") else None,
            day_low=float(row.get("low")) if row.get("low") else None,
            source="roic_latest",
            extra=row,
        )

    def get_trending(self, limit: int = 30, seed_symbols: list[str] | None = None) -> list[StockSnapshot]:
        symbols = list(dict.fromkeys((seed_symbols or []) + LIQUID_SEED_SYMBOLS))[:40]
        movers: list[StockSnapshot] = []
        for symbol in symbols:
            quote = self.get_latest_quote(symbol)
            if quote and quote.price > 0:
                movers.append(quote)
        movers.sort(key=lambda s: abs(s.change_pct), reverse=True)
        return movers[:limit]

    def get_symbol_metrics(self, symbol: str) -> dict[str, Any]:
        metrics: dict[str, Any] = {"symbol": symbol.upper()}
        endpoints = {
            "profile": f"/v2/company/profile/{symbol.upper()}",
            "profitability": f"/v2/fundamental/ratios/profitability/{symbol.upper()}",
            "multiples": f"/v2/fundamental/multiples/{symbol.upper()}",
            "yield_analysis": f"/v2/fundamental/ratios/yield-analysis/{symbol.upper()}",
        }
        for key, path in endpoints.items():
            try:
                data = self.http.get(path, params=self._params())
                metrics[key] = data[0] if isinstance(data, list) and data else data
            except Exception as exc:
                logger.warning("ROIC %s for %s unavailable: %s", key, symbol, exc)
        return metrics

    def get_upside_candidates(
        self,
        symbols: list[str] | None = None,
        limit: int = 25,
    ) -> list[dict[str, Any]]:
        universe = list(dict.fromkeys(symbols or LIQUID_SEED_SYMBOLS))[:25]
        candidates: list[dict[str, Any]] = []

        for symbol in universe:
            try:
                score_row = self._score_upside(symbol)
                if score_row:
                    candidates.append(score_row)
            except Exception as exc:
                logger.warning("ROIC upside scoring failed for %s: %s", symbol, exc)

        candidates.sort(key=lambda row: row.get("score", 0), reverse=True)
        return candidates[:limit]

    def get_catalysts(self, symbol: str, limit: int = 5) -> list[dict[str, Any]]:
        news = self.get_news(symbol, limit=limit)
        catalysts: list[dict[str, Any]] = []
        for item in news:
            catalysts.append({
                "title": item.title,
                "description": item.summary,
                "summary": item.summary,
                "url": item.url,
                "published_at": item.published_at.isoformat() if item.published_at else None,
                "source": "roic",
                "confidence": 0.65,
            })
        return catalysts

    def get_news(self, symbol: str, limit: int = 10) -> list[NewsItem]:
        try:
            data = self.http.get(
                f"/v2/company/news/{symbol.upper()}",
                params=self._params({"limit": limit}),
            )
        except Exception as exc:
            logger.warning("ROIC news for %s unavailable: %s", symbol, exc)
            return []

        items: list[NewsItem] = []
        for article in data or []:
            published = article.get("published_date") or article.get("publishedDate")
            published_at = None
            if published:
                try:
                    published_at = datetime.fromisoformat(published.replace("Z", "+00:00"))
                except ValueError:
                    published_at = None
            sym = article.get("symbol", symbol.upper())
            items.append(
                NewsItem(
                    symbol=sym,
                    title=article.get("title", ""),
                    summary=(article.get("article_text") or article.get("text", ""))[:500],
                    url=article.get("article_url") or article.get("url", ""),
                    published_at=published_at,
                    source="roic",
                    tickers=[sym],
                    queried_symbol=symbol.upper(),
                )
            )
        return items

    def _score_upside(self, symbol: str) -> dict[str, Any] | None:
        quote = self.get_latest_quote(symbol)
        metrics = self.get_symbol_metrics(symbol)
        profitability = metrics.get("profitability") or {}
        multiples = metrics.get("multiples") or {}
        profile = metrics.get("profile") or {}
        if isinstance(profile, list):
            profile = profile[0] if profile else {}

        roic = float(profitability.get("return_on_inv_capital") or 0)
        margin = float(profitability.get("oper_margin") or 0)
        pe = float(multiples.get("pe_ratio") or 0)
        change_pct = quote.change_pct if quote else 0.0

        if roic <= 0 and margin <= 0:
            return None

        score = 0.0
        reasons: list[str] = []

        if roic >= 15:
            score += 0.35
            reasons.append(f"Strong ROIC at {roic:.1f}%")
        elif roic >= 10:
            score += 0.2
            reasons.append(f"Healthy ROIC at {roic:.1f}%")

        if margin >= 20:
            score += 0.2
            reasons.append(f"Operating margin {margin:.1f}%")
        elif margin >= 10:
            score += 0.1
            reasons.append(f"Positive operating margin {margin:.1f}%")

        if 0 < pe <= 25:
            score += 0.15
            reasons.append(f"Reasonable P/E at {pe:.1f}")
        elif pe > 0:
            score += 0.05

        if change_pct >= 2:
            score += 0.15
            reasons.append(f"Recent momentum {change_pct:+.1f}%")
        elif change_pct >= 0:
            score += 0.05

        if score < 0.45:
            return None

        company = profile.get("company_name") or profile.get("name") or symbol.upper()
        return {
            "symbol": symbol.upper(),
            "ticker": symbol.upper(),
            "score": min(score, 0.95),
            "reason": f"{company}: " + "; ".join(reasons),
            "summary": "; ".join(reasons),
            "roic": roic,
            "pe_ratio": pe,
            "change_pct": change_pct,
        }

    def close(self) -> None:
        self.http.close()
        self._direct.close()