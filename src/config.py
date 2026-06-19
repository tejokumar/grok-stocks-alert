from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    polygon_api_key: str = ""
    fmp_api_key: str = ""
    roic_api_key: str = ""
    xai_api_key: str = ""
    anthropic_api_key: str = ""

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    alert_prefix: str = "grok-stock-alerts-agent"
    scan_interval_minutes: int = 10
    premarket_start_minutes_before_open: int = 15
    min_price: float = 2.0
    min_volume: int = 100_000
    breakout_volume_multiplier: float = 2.0
    breakout_price_pct: float = 3.0
    max_watchlist_size: int = 50
    max_daily_alerts: int = 3
    min_conviction_score: float = 0.58
    min_alert_confidence: float = 0.68
    min_conviction_price: float = 5.0
    max_analysis_symbols: int = 20
    enable_xai_catalyst_search: bool = True
    enable_claude_validation: bool = True
    xai_model: str = "grok-3-fast"
    claude_model: str = "claude-sonnet-4-20250514"

    market_timezone: str = "America/New_York"
    market_open_hour: int = 9
    market_open_minute: int = 30
    market_close_hour: int = 16
    market_close_minute: int = 0

    polygon_base_url: str = "https://api.polygon.io"
    fmp_base_url: str = "https://financialmodelingprep.com/stable"
    roic_base_url: str = "https://api.roic.ai"
    xai_base_url: str = "https://api.x.ai/v1"

    state_file: str = Field(default="data/state.json")
    cache_dir: str = Field(default="data/cache")


@lru_cache
def get_settings() -> Settings:
    return Settings()