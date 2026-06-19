import json
import logging
import re

from src.config import Settings
from src.models import Alert

logger = logging.getLogger(__name__)

VALIDATION_PROMPT = """You are a senior equity analyst validating automated stock alerts.

Review this alert for {symbol} and decide if it should be sent to a trader.

Alert type: {alert_type}
Title: {title}
Message: {message}

Respond ONLY with valid JSON:
{{
  "should_send": true|false,
  "adjusted_confidence": 0.0-1.0,
  "reason": "brief justification"
}}

Reject alerts that are vague, duplicate obvious market moves, or lack actionable catalysts."""


class ClaudeClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._client = None

    def _get_client(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic(api_key=self.settings.anthropic_api_key)
        return self._client

    def validate_alert(self, alert: Alert) -> Alert | None:
        if not self.settings.anthropic_api_key or not self.settings.enable_claude_validation:
            return alert

        prompt = VALIDATION_PROMPT.format(
            symbol=alert.symbol,
            alert_type=alert.alert_type.value,
            title=alert.title,
            message=alert.message,
        )

        try:
            client = self._get_client()
            response = client.messages.create(
                model=self.settings.claude_model,
                max_tokens=300,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text
            parsed = self._parse_json(text)
            if not parsed or not parsed.get("should_send", True):
                logger.info("Claude rejected alert for %s: %s", alert.symbol, parsed)
                return None
            alert.confidence = float(parsed.get("adjusted_confidence", alert.confidence))
            return alert
        except Exception as exc:
            logger.warning("Claude validation failed for %s: %s", alert.symbol, exc)
            return alert

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