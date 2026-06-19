import json
import logging
import re

from src.config import Settings
from src.models import Alert, AlertType, CatalystInsight
from src.utils.http import HttpClient

logger = logging.getLogger(__name__)

CATALYST_PROMPT = """You are a stock market catalyst analyst with access to real-time social chatter and news.

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
  "summary": "2-3 sentence actionable summary"
}}

If no meaningful catalysts found, return confidence below 0.4 and explain why."""


class XAIClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.http = HttpClient(settings.xai_base_url)

    def analyze_catalysts(self, symbol: str, context: str = "") -> CatalystInsight | None:
        if not self.settings.xai_api_key or not self.settings.enable_xai_catalyst_search:
            return None

        prompt = CATALYST_PROMPT.format(symbol=symbol)
        if context:
            prompt += f"\n\nAdditional context:\n{context}"

        try:
            response = self.http.post(
                "/chat/completions",
                json={
                    "model": self.settings.xai_model,
                    "messages": [
                        {"role": "system", "content": "You are a financial catalyst research agent. Use live search when available."},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.3,
                    "search_parameters": {"mode": "auto"},
                },
                headers={
                    "Authorization": f"Bearer {self.settings.xai_api_key}",
                    "Content-Type": "application/json",
                },
            )
            content = response["choices"][0]["message"]["content"]
            parsed = self._parse_json(content)
            if not parsed:
                return None
            return CatalystInsight(
                symbol=symbol,
                catalysts=parsed.get("catalysts", []),
                social_chatter=parsed.get("social_chatter", []),
                sentiment=parsed.get("sentiment", "neutral"),
                confidence=float(parsed.get("confidence", 0.5)),
                summary=parsed.get("summary", ""),
                source="xai",
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

        return [
            Alert(
                alert_type=AlertType.CATALYST,
                symbol=insight.symbol,
                title=f"xAI catalyst scan — {insight.sentiment} sentiment",
                message=message,
                confidence=insight.confidence,
                metadata={"source": "xai", "sentiment": insight.sentiment},
            )
        ]

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