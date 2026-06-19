import logging

import httpx

from src.config import Settings
from src.models import Alert

logger = logging.getLogger(__name__)


class TelegramAlerter:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.prefix = settings.alert_prefix
        self._client = httpx.Client(timeout=15.0)

    def send(self, alert: Alert) -> bool:
        if not self.settings.telegram_bot_token or not self.settings.telegram_chat_id:
            logger.warning("Telegram not configured — alert skipped: %s %s", alert.symbol, alert.title)
            return False

        url = f"https://api.telegram.org/bot{self.settings.telegram_bot_token}/sendMessage"
        payload = {
            "chat_id": self.settings.telegram_chat_id,
            "text": alert.format_telegram(self.prefix),
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        try:
            response = self._client.post(url, json=payload)
            response.raise_for_status()
            logger.info("Telegram alert sent: %s — %s", alert.symbol, alert.alert_type.value)
            return True
        except Exception as exc:
            logger.error("Telegram send failed: %s", exc)
            return False

    def send_text(self, message: str) -> bool:
        if not self.settings.telegram_bot_token or not self.settings.telegram_chat_id:
            return False
        url = f"https://api.telegram.org/bot{self.settings.telegram_bot_token}/sendMessage"
        text = f"<b>{self.prefix}</b>\n\n{message}"
        try:
            response = self._client.post(url, json={
                "chat_id": self.settings.telegram_chat_id,
                "text": text,
                "parse_mode": "HTML",
            })
            response.raise_for_status()
            return True
        except Exception as exc:
            logger.error("Telegram text send failed: %s", exc)
            return False

    def close(self) -> None:
        self._client.close()