# grok-stocks-alert

Automated stock alerting agent that runs during US market hours. It scans for breakouts, catalysts, trending movers, and direction changes — then sends Telegram alerts prefixed with `grok-stock-alerts-agent`.

## Features

- **Pre-market analysis** — starts 15 minutes before the market open (9:15 AM ET)
- **Intraday scanning** — configurable interval (default: every 10 minutes)
- **Multi-source data** — Polygon REST (no websockets), FMP, ROIC
- **AI catalyst research** — xAI Grok searches social chatter and news for catalysts
- **Alert validation** — Claude filters low-quality alerts before sending
- **Telegram delivery** — all alerts prefixed with `grok-stock-alerts-agent`

## Alert Types

| Type | Description |
|------|-------------|
| `premarket` | Pre-market momentum leaders before the open |
| `trending` | Daily watchlist summary |
| `breakout` | Price + volume breakout above 20-day resistance |
| `catalyst` | News, ROIC catalysts, or xAI social/news findings |
| `upside_potential` | ROIC multi-session upside candidates |
| `direction_change` | Trend reversal or momentum fade on watched stocks |

## Setup

### 1. Clone and install

```bash
git clone https://github.com/tejokumar/grok-stocks-alert.git
cd grok-stocks-alert
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env with your API keys
```

Required keys:

| Variable | Source |
|----------|--------|
| `POLYGON_API_KEY` | [polygon.io](https://polygon.io) |
| `FMP_API_KEY` | [financialmodelingprep.com](https://financialmodelingprep.com) |
| `ROIC_API_KEY` | [roic.ai](https://roic.ai) |
| `XAI_API_KEY` | [x.ai](https://x.ai/api) |
| `ANTHROPIC_API_KEY` | [anthropic.com](https://anthropic.com) |
| `TELEGRAM_BOT_TOKEN` | [@BotFather](https://t.me/BotFather) |
| `TELEGRAM_CHAT_ID` | Your chat or group ID |

### 3. Run

```bash
python run.py
```

The agent waits until 9:15 AM ET on weekdays, then runs continuously until market close at 4:00 PM ET.

## Configuration

Key settings in `.env`:

```env
ALERT_PREFIX=grok-stock-alerts-agent
SCAN_INTERVAL_MINUTES=10
PREMARKET_START_MINUTES_BEFORE_OPEN=15
MIN_PRICE=2.0
MIN_VOLUME=100000
BREAKOUT_VOLUME_MULTIPLIER=2.0
BREAKOUT_PRICE_PCT=3.0
ENABLE_XAI_CATALYST_SEARCH=true
ENABLE_CLAUDE_VALIDATION=true
```

## Architecture

```
run.py
└── src/
    ├── main.py              # Scheduler and entry loop
    ├── agent/stock_agent.py # Orchestrator
    ├── data/                # Polygon, FMP, ROIC clients (REST only)
    ├── analysis/            # Trending, breakout, direction, catalyst
    ├── ai/                  # xAI (social/news) + Claude (validation)
    ├── alerts/telegram.py   # Telegram delivery
    └── market/calendar.py   # US market hours
```

## Run as a background service (macOS launchd)

```bash
# Create ~/Library/LaunchAgents/com.grok.stocks-alert.plist
# Point ProgramArguments to: /path/to/.venv/bin/python /path/to/run.py
launchctl load ~/Library/LaunchAgents/com.grok.stocks-alert.plist
```

## Disclaimer

This tool is for informational purposes only. It is not financial advice. Always do your own research before making investment decisions.