"""Semiconductor sector stock universe — CPU, GPU, memory, networking, equipment, power."""

from dataclasses import dataclass

from src.data.fmp_client import FMPClient


@dataclass(frozen=True)
class SemiStock:
    symbol: str
    category: str
    name: str = ""


# Curated US-listed semiconductor ecosystem
SEMI_UNIVERSE: dict[str, SemiStock] = {
    # CPU / compute
    "INTC": SemiStock("INTC", "cpu", "Intel"),
    "AMD": SemiStock("AMD", "cpu", "AMD"),
    "ARM": SemiStock("ARM", "cpu", "Arm Holdings"),
    # GPU / AI accelerators
    "NVDA": SemiStock("NVDA", "gpu", "NVIDIA"),
    "AVGO": SemiStock("AVGO", "networking", "Broadcom"),
    # Memory
    "MU": SemiStock("MU", "memory", "Micron"),
    "WDC": SemiStock("WDC", "memory", "Western Digital"),
    "SNDK": SemiStock("SNDK", "memory", "Sandisk"),
    # Networking / connectivity
    "MRVL": SemiStock("MRVL", "networking", "Marvell"),
    "QCOM": SemiStock("QCOM", "networking", "Qualcomm"),
    "CRDO": SemiStock("CRDO", "networking", "Credo Technology"),
    "ALAB": SemiStock("ALAB", "networking", "Astera Labs"),
    # Foundry / manufacturing
    "GFS": SemiStock("GFS", "foundry", "GlobalFoundries"),
    "AMKR": SemiStock("AMKR", "foundry", "Amkor Technology"),
    "TSM": SemiStock("TSM", "foundry", "TSMC"),
    # Equipment
    "AMAT": SemiStock("AMAT", "equipment", "Applied Materials"),
    "LRCX": SemiStock("LRCX", "equipment", "Lam Research"),
    "KLAC": SemiStock("KLAC", "equipment", "KLA Corp"),
    "ASML": SemiStock("ASML", "equipment", "ASML"),
    "ONTO": SemiStock("ONTO", "equipment", "Onto Innovation"),
    "TER": SemiStock("TER", "equipment", "Teradyne"),
    "ACMR": SemiStock("ACMR", "equipment", "ACM Research"),
    # Analog / power / mixed-signal
    "TXN": SemiStock("TXN", "analog", "Texas Instruments"),
    "ADI": SemiStock("ADI", "analog", "Analog Devices"),
    "NXPI": SemiStock("NXPI", "analog", "NXP Semiconductors"),
    "ON": SemiStock("ON", "power", "ON Semiconductor"),
    "MPWR": SemiStock("MPWR", "power", "Monolithic Power"),
    "MCHP": SemiStock("MCHP", "analog", "Microchip"),
    "SWKS": SemiStock("SWKS", "analog", "Skyworks"),
    # EDA / IP
    "SNPS": SemiStock("SNPS", "eda", "Synopsys"),
    "CDNS": SemiStock("CDNS", "eda", "Cadence"),
    "RMBS": SemiStock("RMBS", "ip", "Rambus"),
    # Specialty
    "CRUS": SemiStock("CRUS", "audio", "Cirrus Logic"),
    "LSCC": SemiStock("LSCC", "fpga", "Lattice Semiconductor"),
    "ALGM": SemiStock("ALGM", "analog", "Allegro MicroSystems"),
    "ENTG": SemiStock("ENTG", "materials", "Entegris"),
    "FORM": SemiStock("FORM", "equipment", "FormFactor"),
    "UCTT": SemiStock("UCTT", "equipment", "Ultra Clean"),
    "SMCI": SemiStock("SMCI", "systems", "Super Micro"),
    "VRT": SemiStock("VRT", "power", "Vertiv"),
    # Semi-adjacent AI infra
    "SMH": SemiStock("SMH", "etf", "VanEck Semiconductor ETF"),
    "SOXX": SemiStock("SOXX", "etf", "iShares Semiconductor ETF"),
}

SEMI_SECTOR_KEYWORDS = {
    "semiconductor", "semiconductors", "chip", "chips", "wafer", "foundry",
    "gpu", "cpu", "memory", "dram", "nand", "hbm", "fab", "asic", "fpga",
    "analog", "networking", "silicon", "microprocessor", "accelerator",
}


class SemiconductorUniverse:
    def __init__(self, fmp: FMPClient | None = None):
        self.fmp = fmp
        self._symbols = set(SEMI_UNIVERSE.keys())

    @property
    def symbols(self) -> set[str]:
        return self._symbols

    def is_semiconductor(self, symbol: str) -> bool:
        return symbol.upper() in self._symbols

    def get_category(self, symbol: str) -> str:
        entry = SEMI_UNIVERSE.get(symbol.upper())
        return entry.category if entry else "other"

    def get_name(self, symbol: str) -> str:
        entry = SEMI_UNIVERSE.get(symbol.upper())
        return entry.name if entry else symbol.upper()

    def enrich_from_screener(self) -> None:
        """Add semiconductor industry names from FMP screener."""
        if not self.fmp:
            return
        try:
            rows = self.fmp.get_stock_screener(
                market_cap_more_than=500_000_000,
                volume_more_than=200_000,
                limit=100,
                sector="Technology",
                industry="Semiconductors",
            )
            for row in rows or []:
                industry = (row.get("industry") or "").lower()
                sector = (row.get("sector") or "").lower()
                sym = row.get("symbol", "")
                if not sym or len(sym) > 5:
                    continue
                if "semiconductor" in industry or "semiconductor" in sector:
                    self._symbols.add(sym.upper())
        except Exception:
            pass

    def categories_summary(self) -> str:
        cats: dict[str, list[str]] = {}
        for sym in sorted(self._symbols):
            cat = self.get_category(sym)
            cats.setdefault(cat, []).append(sym)
        parts = [f"{cat}: {', '.join(syms[:6])}" for cat, syms in sorted(cats.items())]
        return "; ".join(parts[:8])