import re


def normalize_headline(text: str) -> str:
    """Collapse a headline into a stable dedup token."""
    lowered = text.lower()
    lowered = re.sub(r"https?://\S+", "", lowered)
    lowered = re.sub(r"[^a-z0-9]+", " ", lowered)
    return " ".join(lowered.split())[:100]


def catalyst_dedup_key(symbol: str, title: str, source: str = "") -> str:
    headline = normalize_headline(title)
    source_tag = source.lower()[:12] if source else "any"
    return f"catalyst:{symbol}:{source_tag}:{headline}"