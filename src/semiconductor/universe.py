"""Semiconductor sector stock universe — CPU, GPU, memory, networking, fiber optics, power, equipment."""

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
    # Fiber optics / photonics
    "LITE": SemiStock("LITE", "fiber_optics", "Lumentum"),
    "COHR": SemiStock("COHR", "fiber_optics", "Coherent"),
    "CIEN": SemiStock("CIEN", "fiber_optics", "Ciena"),
    "GLW": SemiStock("GLW", "fiber_optics", "Corning"),
    "FN": SemiStock("FN", "fiber_optics", "Fabrinet"),
    "AAOI": SemiStock("AAOI", "fiber_optics", "Applied Optoelectronics"),
    "VIAV": SemiStock("VIAV", "fiber_optics", "Viavi Solutions"),
    "POET": SemiStock("POET", "fiber_optics", "POET Technologies"),
    "COMM": SemiStock("COMM", "fiber_optics", "CommScope"),
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
    # Analog / mixed-signal
    "TXN": SemiStock("TXN", "analog", "Texas Instruments"),
    "ADI": SemiStock("ADI", "analog", "Analog Devices"),
    "NXPI": SemiStock("NXPI", "analog", "NXP Semiconductors"),
    "MCHP": SemiStock("MCHP", "analog", "Microchip"),
    "SWKS": SemiStock("SWKS", "analog", "Skyworks"),
    # Power semis / power electronics / data-center power
    "ON": SemiStock("ON", "power", "ON Semiconductor"),
    "MPWR": SemiStock("MPWR", "power", "Monolithic Power"),
    "AEIS": SemiStock("AEIS", "power", "Advanced Energy"),
    "POWI": SemiStock("POWI", "power", "Power Integrations"),
    "QRVO": SemiStock("QRVO", "power", "Qorvo"),
    "WOLF": SemiStock("WOLF", "power", "Wolfspeed"),
    "DIOD": SemiStock("DIOD", "power", "Diodes Inc"),
    "STM": SemiStock("STM", "power", "STMicroelectronics"),
    "ENPH": SemiStock("ENPH", "power", "Enphase Energy"),
    "SEDG": SemiStock("SEDG", "power", "SolarEdge"),
    "VRT": SemiStock("VRT", "power", "Vertiv"),
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
    # Semi-adjacent AI infra
    "SMH": SemiStock("SMH", "etf", "VanEck Semiconductor ETF"),
    "SOXX": SemiStock("SOXX", "etf", "iShares Semiconductor ETF"),
}

SEMI_SECTOR_KEYWORDS = {
    "semiconductor", "semiconductors", "chip", "chips", "wafer", "foundry",
    "gpu", "cpu", "memory", "dram", "nand", "hbm", "fab", "asic", "fpga",
    "analog", "networking", "silicon", "microprocessor", "accelerator",
    "fiber optic", "fiber optics", "photonics", "optical", "power management",
    "power semiconductor", "sic", "gallium nitride", "gan",
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