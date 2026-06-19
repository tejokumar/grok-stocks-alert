import logging
from typing import Any

from src.config import Settings
from src.models import StockSnapshot
from src.utils.http import HttpClient

logger = logging.getLogger(__name__)


class ROICClient:
    """ROIC.ai financial metrics and screening client."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.http = HttpClient(settings.roic_base_url)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.settings.roic_api_key}"}

    def get_trending(self, limit: int = 30) -> list[StockSnapshot]:
        try:
            data = self.http.get(
                "/v1/market/trending",
                params={"limit": limit},
                headers=self._headers(),
            )
        except Exception as exc:
            logger.warning("ROIC trending unavailable: %s", exc)
            return []
        return self._parse_symbols(data.get("data", data) if isinstance(data, dict) else data)

    def get_symbol_metrics(self, symbol: str) -> dict[str, Any]:
        try:
            return self.http.get(
                f"/v1/symbols/{symbol.upper()}/metrics",
                headers=self._headers(),
            )
        except Exception as exc:
            logger.warning("ROIC metrics for %s unavailable: %s", symbol, exc)
            return {}

    def get_upside_candidates(self, limit: int = 25) -> list[dict[str, Any]]:
        try:
            data = self.http.get(
                "/v1/screen/upside",
                params={"limit": limit},
                headers=self._headers(),
            )
            return data.get("data", data) if isinstance(data, dict) else data or []
        except Exception as exc:
            logger.warning("ROIC upside screen unavailable: %s", exc)
            return []

    def get_catalysts(self, symbol: str) -> list[dict[str, Any]]:
        try:
            data = self.http.get(
                f"/v1/symbols/{symbol.upper()}/catalysts",
                headers=self._headers(),
            )
            return data.get("data", data) if isinstance(data, dict) else data or []
        except Exception as exc:
            logger.warning("ROIC catalysts for %s unavailable: %s", symbol, exc)
            return []

    def _parse_symbols(self, rows: list[Any]) -> list[StockSnapshot]:
        results: list[StockSnapshot] = []
        for row in rows or []:
            if isinstance(row, str):
                results.append(StockSnapshot(symbol=row, price=0, change_pct=0, volume=0, source="roic"))
                continue
            if not isinstance(row, dict):
                continue
            sym = row.get("symbol") or row.get("ticker", "")
            if not sym:
                continue
            results.append(
                StockSnapshot(
                    symbol=sym,
                    price=float(row.get("price", row.get("last_price", 0))),
                    change_pct=float(row.get("change_pct", row.get("change_percent", 0))),
                    volume=int(row.get("volume", 0)),
                    source="roic",
                    extra=row,
                )
            )
        return results

    def close(self) -> None:
        self.http.close()