# grok-stocks-alert

Automated stock alerting system with two independent agents that run during US market hours. Each agent scans for catalysts, analyst actions, breakouts, and thesis changes — then delivers Telegram alerts with price targets and reference links.

| Agent | Entry point | Telegram prefix | State file |
|-------|-------------|-----------------|------------|
| **General** | `run.py` | `grok-stock-alerts-agent` | `data/state.json` |
| **Semiconductor** | `run_semi.py` | `grok-semi-alerts-agent` | `data/semi_state.json` |

Both agents can run in parallel on the same machine. They share API keys but maintain separate cooldowns, theses, and alert history.

---

## Agents

### General stock agent

Scans the broad US equity market for trending movers, breakouts, and catalysts across all sectors.

- **Entry:** `python run.py`
- **Universe:** Polygon/FMP gainers, actives, and ROIC trending seeds
- **Focus:** Any liquid stock passing price/volume filters

### Semiconductor agent

Scoped exclusively to the semiconductor ecosystem — CPU, GPU, memory, networking, fiber optics, power, fab equipment, and related ETFs.

- **Entry:** `python run_semi.py`
- **Universe:** ~40+ curated symbols (INTC, AMD, NVDA, MU, AVGO, TSM, AMAT, etc.) plus FMP semiconductor screener enrichment
- **Categories:** Alerts tagged with `[CPU]`, `[GPU]`, `[MEMORY]`, `[NETWORKING]`, `[FIBER_OPTICS]`, `[POWER]`, `[EQUIPMENT]`, etc.
- **Catalyst keywords:** HBM, DRAM, CoWoS, fab expansion, chips act, export controls, and more

---

## Features

| Feature | Details |
|---------|---------|
| **Market hours** | Active 9:15 AM–4:00 PM ET, weekdays only |
| **Pre-market** | Starts 15 minutes before the open |
| **Intraday scans** | Every 10 minutes (configurable) |
| **Data sources** | Polygon REST, FMP stable API, ROIC v2 (no websockets) |
| **Analyst grades** | Top-firm upgrades/downgrades via FMP `/grades` |
| **Thesis tracking** | First alert per stock is bullish; stores thesis for reversal monitoring |
| **Thesis reversals** | Alerts when a prior bullish thesis is contradicted by downgrades or bearish news |
| **Reference links** | Every catalyst alert includes clickable source URLs in Telegram |
| **Price targets** | Current price + 2–4 week target on every catalyst alert |
| **xAI catalyst search** | Grok 4.3 with web + X search tools (Responses API) |
| **Claude validation** | Filters low-quality high-conviction picks |
| **Deduplication** | Headline normalization, per-symbol cooldown, 1 alert/symbol/scan |
| **Force mode** | `--force` flag runs one scan immediately, ignoring market hours |

---

## Alert types

| Type | Label in Telegram | Description |
|------|-------------------|-------------|
| `catalyst` | CATALYST | Strong news or ROIC catalyst |
| `premarket` | PRE-MARKET CATALYST | Pre-market catalyst before the open |
| `analyst_upgrade` | ANALYST UPGRADE | Top-firm rating upgrade (enriched into catalyst alerts) |
| `thesis_reversal` | THESIS REVERSAL | Prior bullish thesis contradicted by new signals |
| `breakout` | BREAKOUT | Price + volume breakout above 20-day resistance |
| `upside_potential` | HIGH CONVICTION | Multi-signal conviction pick (Claude-validated) |
| `direction_change` | DIRECTION CHANGE | Trend reversal or momentum fade |

When a catalyst alert also has a recent analyst upgrade, the label becomes **CATALYST + ANALYST UPGRADE**.

### Analyst upgrades

- Pulled from FMP grades API for top firms (Goldman, Morgan Stanley, Citi, BofA, Barclays, Bernstein, etc.)
- Lookback window: 14 days (configurable)
- Upgrade details are **merged into the winning catalyst alert** for that symbol (not sent as a separate message)

### Thesis tracking and reversals

1. **First alert** for any symbol must be **bullish** (upgrade, positive catalyst, earnings beat, etc.)
2. When sent, the agent stores the thesis: title, summary, entry price, target, references, timestamp
3. On future scans, symbols with an active bullish thesis are monitored for:
   - Top-analyst **downgrades**
   - Bearish news (guidance cut, earnings miss, downgrade headlines, etc.)
4. When detected → **THESIS REVERSAL** alert showing the original thesis vs. the new bearish signal
5. Thesis is then marked bearish (no repeat reversals until a new bullish thesis is recorded)
6. After the per-symbol cooldown expires, the ticker can receive a **new bullish catalyst** — that re-arms reversal tracking

### Price targets (2–4 week)

Targets on catalyst alerts are **not** AI predictions. They use a rules-based formula from Polygon 20-day range + intraday momentum, capped between **+4%** and **+22%**. Thesis reversals use a fixed **−8%** revised target.

---

## Quick start (manual install)

### 1. Clone and install (uv — recommended)

```bash
git clone https://github.com/tejokumar/grok-stocks-alert.git
cd grok-stocks-alert
curl -LsSf https://astral.sh/uv/install.sh | sh   # if uv not installed
uv python install 3.12
uv sync
```

Or with classic pip:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
nano .env   # add your API keys
```

### 3. Run

```bash
# With uv (recommended)
uv run python run.py
uv run python run_semi.py
uv run python run_semi.py --force

# Or activate .venv created by uv sync
source .venv/bin/activate
python run_semi.py
```

### 4. Run both agents in parallel

```bash
python run.py &
python run_semi.py &
```

---

## Mac mini install (semiconductor agent)

Default install path: `~/projects/grok-stocks-alert`

### One-line setup (clone + deps, no launchd)

```bash
curl -fsSL https://raw.githubusercontent.com/tejokumar/grok-stocks-alert/main/mac-mini-setup.sh | bash
```

You should see `4.0.0-uv` in the first line. If you see `Python 3.11+ required`, use `mac-mini-setup.sh` (not a cached old installer URL).

### Full install (clone + deps + LaunchAgent)

```bash
curl -fsSL https://raw.githubusercontent.com/tejokumar/grok-stocks-alert/main/install-semi-agent.sh | bash
```

### Mac mini helper scripts

All scripts live in the repo root. After `git pull`, make them executable once:

```bash
cd ~/projects/grok-stocks-alert
chmod +x start-semi-agent.sh test-semi-agent.sh clear-semi-cache.sh \
  install-semi-launchagent.sh uninstall-semi-launchagent.sh
```

| Script | Purpose |
|--------|---------|
| `start-semi-agent.sh` | Run **live** agent during market hours |
| `test-semi-agent.sh` | One force scan using **isolated test state** |
| `clear-semi-cache.sh` | Reset **test-only** cooldowns/theses (live untouched) |
| `install-semi-launchagent.sh` | Install or reload LaunchAgent (launchd) |
| `uninstall-semi-launchagent.sh` | Fully remove LaunchAgent + stop orphan processes |

### Test vs live state (important)

| | Test (`test-semi-agent.sh`) | Live (`start-semi-agent.sh` / LaunchAgent) |
|--|--|--|
| State file | `data/test/semi_state.json` | `data/semi_state.json` |
| Cache dir | `data/test/cache/` | `data/cache/` |

`clear-semi-cache.sh` only clears the **test** paths. Production cooldowns and theses are never modified.

### Typical Mac mini workflow

```bash
cd ~/projects/grok-stocks-alert
git pull

# 1. Configure API keys (once)
nano .env

# 2. Test without affecting live agent
./clear-semi-cache.sh
./test-semi-agent.sh

# 3. Enable auto-start on login
./install-semi-launchagent.sh
```

### LaunchAgent install / uninstall

```bash
# Install or reload (writes plist + loads launchd)
./install-semi-launchagent.sh

# Full remove: bootout, delete plist, kill orphan processes
./uninstall-semi-launchagent.sh

# Also delete launchd stdout/stderr logs
./uninstall-semi-launchagent.sh --purge-logs
```

Plist location: `~/Library/LaunchAgents/com.tejokumar.grok-semi-alerts.plist`

```bash
# Restart running agent
launchctl kickstart -k gui/$(id -u)/com.tejokumar.grok-semi-alerts

# Check launchd status
launchctl print gui/$(id -u)/com.tejokumar.grok-semi-alerts
```

`uninstall-semi-launchagent.sh` does **not** delete `.env`, `data/semi_state.json`, or the repo.

### git pull conflict (old local scripts)

If `git pull` fails because `test-semi-agent.sh` already exists locally:

```bash
rm -f test-semi-agent.sh clear-semi-cache.sh
git pull
chmod +x *.sh
```

### Install options

```bash
# Custom install path
INSTALL_DIR=~/other/path/grok-stocks-alert ./install-semi-agent.sh

# Skip LaunchAgent during full install (set up later with install-semi-launchagent.sh)
INSTALL_LAUNCH_AGENT=no ./install-semi-agent.sh
```

### Logs on Mac mini

| File | Purpose |
|------|---------|
| `logs/semi_agent.log` | Agent scan logs |
| `logs/launchd.stdout.log` | LaunchAgent stdout |
| `logs/launchd.stderr.log` | LaunchAgent stderr |

Copy your `.env` from another machine before testing — installers do not include API keys.

---

## Environment variables

### Required API keys

| Variable | Source |
|----------|--------|
| `POLYGON_API_KEY` | [polygon.io](https://polygon.io) |
| `FMP_API_KEY` | [financialmodelingprep.com](https://financialmodelingprep.com) |
| `ROIC_API_KEY` | [roic.ai](https://roic.ai) |
| `XAI_API_KEY` | [x.ai](https://x.ai/api) |
| `ANTHROPIC_API_KEY` | [anthropic.com](https://anthropic.com) |
| `TELEGRAM_BOT_TOKEN` | [@BotFather](https://t.me/BotFather) |
| `TELEGRAM_CHAT_ID` | Your chat or group ID |

### Key settings

```env
# Agent identity
ALERT_PREFIX=grok-stock-alerts-agent
SEMI_ALERT_PREFIX=grok-semi-alerts-agent
SEMI_STATE_FILE=data/semi_state.json

# Scanning
SCAN_INTERVAL_MINUTES=10
PREMARKET_START_MINUTES_BEFORE_OPEN=15
MAX_WATCHLIST_SIZE=50
CATALYST_COOLDOWN_MINUTES=360
MIN_CATALYST_CONFIDENCE=0.75

# Filters
MIN_PRICE=2.0
MIN_VOLUME=100000

# AI features
ENABLE_XAI_CATALYST_SEARCH=true
ENABLE_CLAUDE_VALIDATION=true
ENABLE_ANALYST_GRADES=true
XAI_MODEL=grok-4.3
XAI_REASONING_EFFORT=none
XAI_MAX_SYMBOLS=6
XAI_MAX_WORKERS=4
ANALYST_GRADE_LOOKBACK_DAYS=14
THESIS_REVERSAL_LOOKBACK_DAYS=7

# Market hours (US Eastern)
MARKET_TIMEZONE=America/New_York
MARKET_OPEN_HOUR=9
MARKET_OPEN_MINUTE=30
MARKET_CLOSE_HOUR=16
MARKET_CLOSE_MINUTE=0
```

---

## Architecture

```
run.py                          # General agent entry
run_semi.py                     # Semiconductor agent entry

# Mac mini / ops scripts
install-semi-agent.sh           # Full install (clone, uv, LaunchAgent)
mac-mini-setup.sh               # Clone + uv only (no launchd)
start-semi-agent.sh               # Run live semi agent
test-semi-agent.sh               # Force scan (test state only)
clear-semi-cache.sh             # Reset test state/cache
install-semi-launchagent.sh     # Install/reload LaunchAgent
uninstall-semi-launchagent.sh   # Remove LaunchAgent completely

src/
├── main.py                     # General agent scheduler
├── semiconductor_main.py       # Semi agent scheduler
├── config.py                   # Settings from .env
├── models.py                   # Alert, NewsItem, AnalystGrade types
├── agent/
│   ├── stock_agent.py          # Core orchestrator (both agents inherit)
│   └── semiconductor_agent.py  # Semi-scoped overrides
├── semiconductor/
│   ├── universe.py             # Curated semi symbol list + categories
│   └── catalyst.py             # Semi-tuned catalyst keywords
├── analysis/
│   ├── trending.py             # General trending discovery
│   ├── semiconductor_trending.py
│   ├── catalyst.py             # News catalyst scoring
│   ├── analyst_grades.py       # FMP top-firm upgrades/downgrades
│   ├── thesis_reversal.py      # Bullish thesis change detection
│   ├── breakout.py
│   ├── direction.py
│   └── conviction.py           # Price targets + high-conviction picks
├── data/
│   ├── polygon_client.py       # REST only (no websockets)
│   ├── fmp_client.py           # Stable API + grades
│   └── roic_client.py          # v2 endpoints
├── ai/
│   ├── xai_client.py           # Grok 4.3 Responses API + web/X search
│   └── claude_client.py        # Alert validation
├── alerts/telegram.py          # Telegram delivery with reference links
├── market/calendar.py          # US market hours
└── utils/
    ├── state.py                # Cooldowns, watchlist, thesis tracking
    └── dedup.py                # Headline normalization

data/
├── state.json                  # General agent state (live)
├── semi_state.json             # Semi agent state (live)
└── test/
    ├── semi_state.json         # Test-only state (test-semi-agent.sh)
    └── cache/                  # Test-only cache
```

---

## Estimated daily costs (both agents)

Running both agents on a trading day (9:15 AM–4:00 PM ET, 10-min interval):

| Metric | Per agent | Both agents |
|--------|-----------|-------------|
| Scans/day | 41 | 82 |
| REST API calls/day | ~12.7k (main), ~21.2k (semi) | ~34,000 |
| xAI calls/day | ~492 | ~984 |
| Claude validations/day | 0–205 (usually 0) | 0–410 max |

### Cost breakdown

| Category | Est. daily | Est. monthly (22 trading days) |
|----------|------------|-------------------------------|
| Subscriptions (Polygon, FMP, ROIC) | ~$6–10/day amortized | ~$120–240/month |
| xAI (grok-4.3 + web/X search) | ~$3–15/day | ~$65–330/month |
| Claude (conviction validation) | ~$0–2/day | ~$0–40/month |
| Telegram | $0 | $0 |
| **Total** | **~$10–20/day** | **~$250–400/month** |

The semi agent is ~70% heavier per scan (polls the full semi universe). xAI with live search is the main variable cost.

### Cost reduction tips

| Change | Savings |
|--------|---------|
| `ENABLE_XAI_CATALYST_SEARCH=false` on one agent | ~$1.50–7/day |
| `SCAN_INTERVAL_MINUTES=15` | ~35% fewer API + xAI calls |
| Run semi agent only during pre-market + open | Cuts semi daily load ~70% |
| `ENABLE_CLAUDE_VALIDATION=false` | Minimal (usually ~$0 today) |

---

## Telegram alert format

Example catalyst alert with analyst upgrade and references:

```
grok-semi-alerts-agent | CATALYST + ANALYST UPGRADE

INTC — [CPU] Intraday catalyst: Intel Becomes the US Chip Bet...

Current Price: $133.99
2-4 Week Target: $155.51 (+16.1%)

Intel's stock surged following President Trump's announcement...

Top analyst upgrade:
• B of A Securities (2026-06-11): Underperform → Buy

References:
• B of A Securities upgrade (2026-06-11) (fmp_grades)
• Intel Becomes the US Chip Bet... (polygon)

Confidence: 85%
```

---

## Semiconductor universe (curated)

| Category | Symbols |
|----------|---------|
| CPU | INTC, AMD, ARM |
| GPU / AI | NVDA |
| Memory | MU, WDC, SNDK |
| Networking | MRVL, QCOM, CRDO, ALAB, AVGO |
| Fiber optics | LITE, COHR, CIEN, GLW, FN, AAOI, VIAV, POET, COMM |
| Foundry | TSM, GFS, AMKR |
| Equipment | AMAT, LRCX, KLAC, ASML, ONTO, TER, ACMR |
| Analog | TXN, ADI, NXPI, MCHP, SWKS |
| Power | ON, MPWR, AEIS, POWI, QRVO, WOLF, DIOD, STM, ENPH, SEDG, VRT |
| EDA / IP | SNPS, CDNS, RMBS |
| ETFs | SMH, SOXX |

Additional symbols are added dynamically from the FMP semiconductor screener.

---

## Disclaimer

This tool is for informational purposes only. It is not financial advice. Always do your own research before making investment decisions.