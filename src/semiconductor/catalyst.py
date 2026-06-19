from src.analysis.catalyst import CatalystAnalyzer, HIGH_IMPACT_KEYWORDS
from src.config import Settings
from src.data import FMPClient, PolygonClient, ROICClient
from src.models import Alert, NewsItem, StockSnapshot
from src.semiconductor.universe import SemiconductorUniverse

SEMI_CATALYST_KEYWORDS = [
    "hbm", "dram", "nand", "memory", "gpu", "cpu", "asic", "fpga",
    "wafer", "fab", "foundry", "capex", "node", "3nm", "2nm", "euv",
    "advanced packaging", "cowos", "chiplet", "ai accelerator",
    "data center", "export control", "chips act", "tariff",
    "capacity expansion", "yield", "utilization", "design win",
    "hyperscaler", "inference", "training chip", "networking chip",
    "ethernet", "pcie", "optical", "power management", "analog",
]

SEMI_HIGH_IMPACT = [
    "hbm shortage", "memory shortage", "gpu shortage", "design win",
    "capacity expansion", "fab expansion", "chips act", "export ban",
    "earnings beat", "guidance raise", "price target", "upgrade",
    "acquisition", "partnership", "contract award",
    "advanced packaging", "node migration", "capex increase",
]


class SemiconductorCatalystAnalyzer(CatalystAnalyzer):
    """Catalyst analyzer tuned for semiconductor supply chain news."""

    def __init__(
        self,
        settings: Settings,
        polygon: PolygonClient,
        fmp: FMPClient,
        roic: ROICClient,
        universe: SemiconductorUniverse | None = None,
    ):
        super().__init__(settings, polygon, fmp, roic)
        self.universe = universe or SemiconductorUniverse(fmp)
        self._semi_keywords = SEMI_CATALYST_KEYWORDS
        self._semi_high_impact = SEMI_HIGH_IMPACT + HIGH_IMPACT_KEYWORDS

    def _news_to_alert(
        self,
        symbol: str,
        item: NewsItem,
        score: int,
        snapshot: StockSnapshot | None,
        phase: str,
    ) -> Alert:
        alert = super()._news_to_alert(symbol, item, score, snapshot, phase)
        cat = self.universe.get_category(symbol)
        alert.title = f"[{cat.upper()}] {alert.title}"
        alert.metadata["semi_category"] = cat
        return alert

    def _keyword_score(self, text: str) -> int:
        text = text.lower()
        hits = sum(1 for kw in self._semi_keywords if kw in text)
        for phrase in self._semi_high_impact:
            if phrase in text:
                hits += 2
        return hits

    def _is_strong(self, score: int, item, text: str | None = None):
        combined = text or (f"{item.title} {item.summary}" if item else "")
        combined = combined.lower()
        has_semi_context = any(kw in combined for kw in SEMI_CATALYST_KEYWORDS[:12])
        has_high_impact = any(phrase in combined for phrase in self._semi_high_impact)

        if has_high_impact and has_semi_context and score >= 2:
            return True
        return super()._is_strong(score, item, text)