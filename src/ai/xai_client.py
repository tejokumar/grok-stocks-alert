import json
import logging
import re
import time

from src.config import Settings
from src.models import Alert, AlertType, CatalystInsight
from src.utils.http import HttpClient

logger = logging.getLogger(__name__)

CATALYST_PROMPT = """You are a stock market catalyst analyst with access to real-time web and X/Twitter search.

Analyze {symbol} for potential catalysts that could move the stock significantly UP over the next few trading sessions.

Consider:
- Breaking news and press releases
- Social media chatter on X/Twitter, Reddit (r/wallstreetbets, r/stocks)
- Analyst upgrades, price target raises
- Sector momentum and peer movements
- Upcoming earnings, FDA decisions, product launches
- Unusual options activity mentions
- Short squeeze potential

Respond ONLY with valid JSON:
{{
  "catalysts": ["list of specific catalysts"],
  "social_chatter": ["notable social media themes"],
  "sentiment": "bullish|bearish|neutral|mixed",
  "confidence": 0.0-1.0,
  "summary": "2-3 sentence actionable summary",
  "references": [
    {{"title": "headline or source name", "url": "https://full-article-url", "source": "publisher"}}
  ]
}}

If no meaningful catalysts found, return confidence below 0.4 and explain why."""


class XAIClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.http = HttpClient(settings.xai_base_url, timeout=180.0)

    def analyze_catalysts(self, symbol: str, context: str = "") -> CatalystInsight | None:
        if not self.settings.xai_api_key or not self.settings.enable_xai_catalyst_search:
            return None

        prompt = CATALYST_PROMPT.format(symbol=symbol)
        if context:
            prompt += f"\n\nAdditional context:\n{context}"

        started = time.monotonic()
        try:
            response = self.http.post(
                "/responses",
                json={
                    "model": self.settings.xai_model,
                    "include": ["no_inline_citations"],
                    "reasoning": {"effort": self.settings.xai_reasoning_effort},
                    "input": [
                        {
                            "role": "system",
                            "content": (
                                "You are a financial catalyst research agent. "
                                "Use web_search and x_search tools to find current news and social chatter."
                            ),
                        },
                        {"role": "user", "content": prompt},
                    ],
                    "tools": [
                        {"type": "web_search"},
                        {"type": "x_search"},
                    ],
                },
                headers={
                    "Authorization": f"Bearer {self.settings.xai_api_key}",
                    "Content-Type": "application/json",
                },
            )
            content = self._extract_output_text(response)
            if not content:
                logger.warning("xAI returned empty response for %s", symbol)
                return None

            parsed = self._parse_json(content)
            if not parsed:
                return None

            references = self._build_references(parsed, response.get("citations") or [])
            elapsed = time.monotonic() - started
            logger.info(
                "xAI catalyst scan for %s completed in %.1fs (%d citations)",
                symbol, elapsed, len(references),
            )
            return CatalystInsight(
                symbol=symbol,
                catalysts=parsed.get("catalysts", []),
                social_chatter=parsed.get("social_chatter", []),
                sentiment=parsed.get("sentiment", "neutral"),
                confidence=float(parsed.get("confidence", 0.5)),
                summary=parsed.get("summary", ""),
                source="xai",
                references=references,
            )
        except Exception as exc:
            logger.warning("xAI catalyst analysis failed for %s: %s", symbol, exc)
            return None

    def to_alerts(self, insight: CatalystInsight) -> list[Alert]:
        if insight.confidence < 0.60 or insight.sentiment in ("bearish", "neutral", "mixed"):
            return []

        catalyst_text = "\n".join(f"• {c}" for c in insight.catalysts[:5])
        social_text = "\n".join(f"• {s}" for s in insight.social_chatter[:3])
        message = insight.summary
        if catalyst_text:
            message += f"\n\nCatalysts:\n{catalyst_text}"
        if social_text:
            message += f"\n\nSocial chatter:\n{social_text}"

        references = [
            {
                "title": (ref.get("title") or "Source")[:100],
                "url": ref.get("url", ""),
                "source": ref.get("source") or "xai",
            }
            for ref in insight.references
            if ref.get("url")
        ]
        return [
            Alert(
                alert_type=AlertType.CATALYST,
                symbol=insight.symbol,
                title=f"xAI catalyst scan — {insight.sentiment} sentiment",
                message=message,
                confidence=insight.confidence,
                metadata={
                    "source": "xai",
                    "sentiment": insight.sentiment,
                    "references": references,
                    "url": references[0]["url"] if references else "",
                },
            )
        ]

    def _extract_output_text(self, response: dict) -> str:
        parts: list[str] = []
        for item in response.get("output") or []:
            if item.get("type") != "message":
                continue
            for content in item.get("content") or []:
                if content.get("type") == "output_text":
                    text = (content.get("text") or "").strip()
                    if text:
                        parts.append(text)
        return "\n".join(parts).strip()

    def _build_references(self, parsed: dict, citations: list) -> list[dict[str, str]]:
        references: list[dict[str, str]] = []
        seen_urls: set[str] = set()

        for ref in parsed.get("references") or []:
            if not isinstance(ref, dict):
                continue
            url = (ref.get("url") or "").strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            references.append(
                {
                    "title": (ref.get("title") or "Source")[:100],
                    "url": url,
                    "source": ref.get("source") or "xai",
                }
            )

        for url in citations:
            if not isinstance(url, str):
                continue
            url = url.strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            references.append(
                {
                    "title": self._citation_title(url),
                    "url": url,
                    "source": "xai",
                }
            )

        return references[:8]

    @staticmethod
    def _citation_title(url: str) -> str:
        if "x.com/" in url or "twitter.com/" in url:
            return "X post"
        host = url.split("/")[2] if "://" in url else url
        return host[:100]

    def _parse_json(self, text: str) -> dict | None:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    return None
        return None

    def close(self) -> None:
        self.http.close()