import re

from src.models import NewsItem

COMPANY_ALIASES: dict[str, list[str]] = {
    "AAPL": ["apple", "aapl"],
    "AMZN": ["amazon", "amzn"],
    "GOOGL": ["google", "alphabet", "googl", "goog"],
    "META": ["meta", "facebook"],
    "MSFT": ["microsoft", "msft"],
    "NVDA": ["nvidia", "nvda"],
    "TSLA": ["tesla", "tsla"],
    "INTC": ["intel", "intc"],
    "AMD": ["amd", "advanced micro"],
    "MU": ["micron", "mu"],
    "NFLX": ["netflix", "nflx"],
    "PLTR": ["palantir", "pltr"],
    "SPCX": ["spacex", "spcx"],
}

OTHER_COMPANY_MARKERS = [
    "spacex", "tesla", "nvidia", "apple", "amazon", "microsoft",
    "netflix", "palantir", "amd", "micron", "qualcomm",
]


def _aliases(symbol: str) -> list[str]:
    sym = symbol.upper()
    return COMPANY_ALIASES.get(sym, [sym.lower()])


def _text_mentions_symbol(symbol: str, text: str) -> bool:
    text = text.lower()
    for alias in _aliases(symbol):
        if re.search(rf"\b{re.escape(alias)}\b", text):
            return True
    return False


def is_relevant_to_symbol(symbol: str, item: NewsItem) -> bool:
    """Ensure a news item is actually about the target ticker, not a cross-tag."""
    sym = symbol.upper()
    title = item.title or ""
    summary = item.summary or ""
    headline = title.lower()

    if not _text_mentions_symbol(sym, title):
        if not _text_mentions_symbol(sym, summary[:300]):
            return False

    if item.tickers and sym not in [t.upper() for t in item.tickers]:
        return False

    if item.symbol.upper() != sym:
        for marker in OTHER_COMPANY_MARKERS:
            if marker in headline and not any(a in headline for a in _aliases(sym)):
                return False

    return True