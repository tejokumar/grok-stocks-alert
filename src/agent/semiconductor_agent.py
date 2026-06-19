import logging

from src.agent.stock_agent import StockAlertAgent
from src.analysis import BreakoutAnalyzer, ConvictionSelector, DirectionAnalyzer
from src.analysis.semiconductor_trending import SemiconductorTrendingAnalyzer
from src.config import Settings, get_settings
from src.data import FMPClient, PolygonClient, ROICClient
from src.models import Alert, AlertType
from src.semiconductor.catalyst import SemiconductorCatalystAnalyzer
from src.semiconductor.universe import SemiconductorUniverse
logger = logging.getLogger(__name__)

SEMI_XAI_CONTEXT = (
    "Focus exclusively on semiconductor industry catalysts: CPU, GPU, memory (DRAM/HBM/NAND), "
    "networking chips, fiber optics/photonics, analog/power ICs, power electronics, "
    "fab equipment, foundry capacity, advanced packaging, AI accelerator demand, "
    "export controls, and chip supply chain."
)


class SemiconductorAlertAgent(StockAlertAgent):
    """Stock alerting agent scoped to semiconductor-themed equities."""

    def __init__(self, settings: Settings | None = None):
        base = settings or get_settings()
        semi_settings = base.model_copy(update={
            "alert_prefix": base.semi_alert_prefix,
            "state_file": base.semi_state_file,
        })
        super().__init__(semi_settings)

        self.universe = SemiconductorUniverse(self.fmp)
        self.trending = SemiconductorTrendingAnalyzer(
            self.settings, self.polygon, self.fmp, self.roic, self.universe,
        )
        self.catalyst = SemiconductorCatalystAnalyzer(
            self.settings, self.polygon, self.fmp, self.roic, self.universe,
        )

    def run_scan(self, force: bool = False) -> None:
        logger.info("Semiconductor agent — categories: %s", self.universe.categories_summary())
        super().run_scan(force=force)

    def _xai_catalyst_alerts(self, symbols: list[str], phase: str) -> list[Alert]:
        if not self.settings.enable_xai_catalyst_search:
            return []

        semi_symbols = [s for s in symbols if self.universe.is_semiconductor(s)]
        return super()._xai_catalyst_alerts(semi_symbols, phase)

    def _xai_scan_symbol(self, symbol: str, phase: str) -> list[Alert]:
        context_parts = [SEMI_XAI_CONTEXT]
        news_lines, news_refs = self._collect_news_references(symbol)
        context_parts.extend(news_lines)
        cat = self.universe.get_category(symbol)
        context_parts.append(f"Category: {cat} ({self.universe.get_name(symbol)})")
        return self._xai_alerts_from_context(
            symbol,
            phase,
            context_parts,
            news_refs,
            catalyst_key_prefix="semi:",
            alert_title_prefix=f"[{cat.upper()}] ",
            extra_metadata={"semi_category": cat},
        )

    def send_startup_message(self) -> None:
        now = self.calendar.now()
        self.telegram.send_text(
            f"Semiconductor agent started at {now.strftime('%Y-%m-%d %H:%M %Z')}.\n"
            f"Tracking CPU, GPU, memory, networking, fiber optics, power & equipment.\n"
            f"Universe: {len(self.universe.symbols)} symbols.\n"
            f"Includes top-analyst upgrades and thesis reversal alerts. "
            f"First alert per stock is bullish; reversals fire when thesis changes."
        )