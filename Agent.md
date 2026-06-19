# Agent.md — grok-stocks-alert system reference

> **Audience:** Future coding agents, LLM assistants, and maintainers.  
> **Repo:** https://github.com/tejokumar/grok-stocks-alert  
> **Language:** Python 3.11+  
> **Last updated:** 2026-06-19

This document describes the full architecture, behavior, and extension points of the stock alerting system. Read this before modifying agents, adding features, or debugging production runs.

---

## 1. System overview

`grok-stocks-alert` is a **dual-agent** US equities alerting system that:

1. Discovers trending symbols during market hours
2. Scores catalysts, analyst actions, breakouts, and thesis changes
3. Enriches alerts with price targets and reference links
4. Delivers HTML-formatted messages to **Telegram**

Both agents share the same codebase, API clients, and orchestration logic. They differ in **universe scope**, **state file**, and **Telegram prefix**.

| Property | General agent | Semiconductor agent |
|----------|---------------|---------------------|
| Entry point | `run.py` | `run_semi.py` |
| Main module | `src/main.py` | `src/semiconductor_main.py` |
| Agent class | `StockAlertAgent` | `SemiconductorAlertAgent` |
| Telegram prefix | `grok-stock-alerts-agent` | `grok-semi-alerts-agent` |
| State file | `data/state.json` | `data/semi_state.json` |
| Log file | `logs/agent.log` | `logs/semi_agent.log` |
| Trending analyzer | `TrendingAnalyzer` | `SemiconductorTrendingAnalyzer` |
| Catalyst analyzer | `CatalystAnalyzer` | `SemiconductorCatalystAnalyzer` |

**Inheritance:** `SemiconductorAlertAgent` extends `StockAlertAgent` and overrides trending, catalyst, xAI context, and startup message. All thesis tracking, analyst grades, dispatch, and price enrichment live in the base class.

---

## 2. Runtime schedule

### Market window

- **Timezone:** `America/New_York` (configurable)
- **Active:** Weekdays, 9:15 AM – 4:00 PM ET
  - 9:15 AM = market open (9:30) minus `PREMARKET_START_MINUTES_BEFORE_OPEN` (default 15)
- **Phases:**
  - `premarket` — before 9:30 AM ET
  - `regular` — 9:30 AM – 4:00 PM ET

### Scheduler (APScheduler `BlockingScheduler`)

Each agent runs:

1. **Initial scan** after waiting for agent window (or immediately with `--force`)
2. **Interval job** — every `SCAN_INTERVAL_MINUTES` (default 10)
3. **Cron premarket job** — weekdays at 9:15 AM ET

### Force mode

```bash
python run.py --force        # general: one scan, exit
python run_semi.py --force   # semi: one scan, exit
```

Bypasses `MarketCalendar.is_agent_active()` and sets phase to `regular`.

### Scans per trading day

~**41 scans/agent/day** (405 minutes ÷ 10 min + initial). Both agents = ~**82 scans/day**.

---

## 3. Scan pipeline (`StockAlertAgent.run_scan`)

Execute order on every scan:

```
1. trending.discover_trending()           → watchlist (max 50 symbols)
2. catalyst.find_strong_catalyst_alerts() → news/ROIC catalysts
3. _xai_catalyst_alerts()                 → Grok catalyst search (12 symbols)
4. analyst_grades.scan_symbols()        → FMP top-firm upgrades/downgrades
5. _merge_catalyst_alerts()               → 1 best alert per symbol (by confidence)
6. _dispatch_catalyst_alerts()            → Telegram + thesis recording
7. thesis_reversal.find_reversals()       → bearish change on prior bullish thesis
8. _dispatch_thesis_reversals()           → Telegram
9. breakout + direction + upside          → conviction candidates
10. conviction.select_top_picks()         → top N picks
11. _dispatch_conviction_alerts()        → Claude validation → Telegram
12. state.set_last_scan()
```

### Semiconductor overrides

- Step 1 uses `SemiconductorTrendingAnalyzer` — filters movers to semi universe only; polls all curated symbols via FMP quotes
- Step 2 uses `SemiconductorCatalystAnalyzer` — semi-specific keywords; tags alerts `[CATEGORY]`
- Step 3 `_xai_catalyst_alerts()` — adds `SEMI_XAI_CONTEXT` and category label; only scans symbols in semi universe

---

## 4. Alert types

Defined in `src/models.py` as `AlertType` enum:

| Enum value | Telegram label | When fired |
|------------|----------------|------------|
| `catalyst` | CATALYST | Strong news/ROIC catalyst |
| `premarket` | PRE-MARKET CATALYST | Catalyst during pre-market phase |
| `analyst_upgrade` | ANALYST UPGRADE | Top-firm upgrade (usually merged into catalyst) |
| `analyst_downgrade` | ANALYST DOWNGRADE | Internal signal for thesis reversal (not standalone first alert) |
| `thesis_reversal` | THESIS REVERSAL | Prior bullish thesis contradicted |
| `breakout` | BREAKOUT | Price + volume breakout |
| `upside_potential` | HIGH CONVICTION | Multi-signal conviction pick |
| `direction_change` | DIRECTION CHANGE | Momentum reversal/fade |
| `trending` | TRENDING | Watchlist summary (rarely dispatched) |

**Combined label:** If `metadata.analyst_upgrade` is set on a catalyst alert → `CATALYST + ANALYST UPGRADE`.

---

## 5. Catalyst dispatch rules

Location: `src/agent/stock_agent.py` → `_dispatch_catalyst_alerts()`

### Bullish-first policy

`_is_bullish_alert()` rejects:

- `ANALYST_DOWNGRADE`, `THESIS_REVERSAL` types
- `metadata.thesis_direction == "bearish"`
- xAI `sentiment` in `bearish`, `neutral`, `mixed`
- Title/message containing: downgrade, earnings miss, guidance cut, etc.

**First alert for a symbol must pass bullish check.**

### Merge logic

`_merge_catalyst_alerts()` keeps **one alert per symbol** — highest `confidence` wins.

**Important:** Analyst upgrade alerts (confidence ~0.88) often lose to news catalysts (~0.90+). Fix: `_enrich_with_analyst_grade()` merges upgrade details into the winning alert's message and references.

### Deduplication & cooldown

Two keys checked before send:

1. `catalyst_key` — headline/source hash (`src/utils/dedup.py`)
2. `symbol:{SYMBOL}` — per-symbol cooldown

Default cooldown: `CATALYST_COOLDOWN_MINUTES=360` (6 hours).

Also dedupes normalized headlines within a single scan (`normalize_headline()`).

### Price enrichment

`_enrich_with_price()` via `ConvictionSelector.estimate_target()`:

- Adds `Current Price` and `2-4 Week Target` to message
- Sets `metadata.current_price`, `metadata.price_target`, `metadata.target_pct`
- **Skips alert** if `price_target <= 0`

### Thesis recording

On successful catalyst send → `state.set_bullish_thesis()` stores:

```json
{
  "direction": "bullish",
  "title": "...",
  "summary": "...",
  "alerted_at": "ISO timestamp",
  "price_at_alert": 133.99,
  "target_at_alert": 155.51,
  "references": [{"title": "...", "url": "...", "source": "polygon"}],
  "analyst_upgrade": {"grading_company": "...", "previous_grade": "...", "new_grade": "...", "grade_date": "..."},
  "catalyst_key": "...",
  "alert_type": "catalyst"
}
```

---

## 6. Thesis reversal

Location: `src/analysis/thesis_reversal.py`

### Triggers (symbol must have `direction: bullish` in state)

1. **Analyst downgrade** — top firm, within `ANALYST_GRADE_LOOKBACK_DAYS` (14d)
2. **Bearish news** — within `THESIS_REVERSAL_LOOKBACK_DAYS` (7d), matching `BEARISH_HIGH_IMPACT` keywords

### Dispatch

- Separate from catalyst cooldown on `symbol:` key — uses `thesis_reversal` dedup key only
- Sets revised bearish target: `price * 0.92` (-8%)
- Calls `state.mark_thesis_reversed()` → sets `direction: bearish`

### Alert format

Shows **original bullish thesis** block + **thesis change** block + references from both.

---

## 7. Analyst grades

Location: `src/analysis/analyst_grades.py`, `src/data/fmp_client.py`

### API

```
GET https://financialmodelingprep.com/stable/grades?symbol={SYMBOL}&apikey=...
```

Returns: `gradingCompany`, `previousGrade`, `newGrade`, `action` (upgrade/downgrade/maintain), `date`

### Top firms filter

`TOP_ANALYST_FIRMS` in `fmp_client.py` — Goldman, Morgan Stanley, Citi, BofA, Barclays, Bernstein, Needham, etc.

### Behavior

- **Upgrades** → added to catalyst pool; enriched into winning alert
- **Downgrades** → fed to `ThesisReversalAnalyzer` only (not sent as standalone bullish alerts)

---

## 8. Reference links

Location: `src/models.py` → `Alert._format_references()`, `Alert.format_telegram()`

### Metadata shape

```python
metadata["references"] = [
    {"title": "Headline", "url": "https://...", "source": "polygon|fmp|roic|fmp_grades|xai"}
]
metadata["url"] = "https://..."  # fallback single URL
```

### Sources

| Source | How populated |
|--------|-----------------|
| News catalysts | `CatalystAnalyzer._news_to_alert()` from `NewsItem.url` |
| ROIC catalysts | `cat["url"]` from ROIC news |
| xAI | Prompt requests `references` array; fallback from Polygon/FMP news URLs |
| Analyst grades | FMP grades page URL |

Rendered as HTML `<a href="...">` links under **References:** in Telegram (parse_mode HTML).

---

## 9. News relevance filter

Location: `src/analysis/relevance.py`

**Problem solved:** Polygon cross-tags news (e.g., SpaceX story tagged to INTC).

`is_relevant_to_symbol(symbol, news_item)` requires:

1. Company name/alias appears in title or summary
2. If `tickers` present, target symbol must be listed
3. Headline mentioning another major company without target alias → rejected

Extend `COMPANY_ALIASES` when adding new universe symbols.

---

## 10. Semiconductor universe

Location: `src/semiconductor/universe.py`

### Curated symbols (59)

| Category | Count | Examples |
|----------|-------|----------|
| `cpu` | 3 | INTC, AMD, ARM |
| `gpu` | 1 | NVDA |
| `memory` | 3 | MU, WDC, SNDK |
| `networking` | 5 | MRVL, QCOM, CRDO, ALAB, AVGO |
| `fiber_optics` | 9 | LITE, COHR, CIEN, GLW, FN, AAOI, VIAV, POET, COMM |
| `foundry` | 3 | TSM, GFS, AMKR |
| `equipment` | 9 | AMAT, LRCX, KLAC, ASML, ONTO, TER, ACMR, FORM, UCTT |
| `analog` | 6 | TXN, ADI, NXPI, MCHP, SWKS, ALGM |
| `power` | 11 | ON, MPWR, AEIS, POWI, QRVO, WOLF, DIOD, STM, ENPH, SEDG, VRT |
| `eda` | 2 | SNPS, CDNS |
| `etf` | 2 | SMH, SOXX |
| Other | 5 | ip, audio, fpga, materials, systems |

### Dynamic enrichment

`SemiconductorUniverse.enrich_from_screener()` adds symbols from FMP:

```
GET /company-screener?sector=Technology&industry=Semiconductors
```

### Category tags in alerts

`SemiconductorCatalystAnalyzer._news_to_alert()` prefixes title with `[{CATEGORY.upper()}]`.

---

## 11. External APIs

### Polygon (REST only — no websockets)

Base: `https://api.polygon.io`

| Endpoint | Used for |
|----------|----------|
| `/v2/snapshot/locale/us/markets/stocks/gainers` | Trending |
| `/v2/reference/news` | News catalysts |
| `/v2/aggs/ticker/{sym}/range/1/day/{from}/{to}` | Breakouts, price targets |

### FMP stable API

Base: `https://financialmodelingprep.com/stable`

| Endpoint | Used for |
|----------|----------|
| `/biggest-gainers`, `/most-actives` | Trending |
| `/quote` | Prices (semi universe polling) |
| `/news/stock`, `/news/stock-latest` | News |
| `/grades` | Analyst upgrades/downgrades |
| `/company-screener` | Semi universe enrichment |

**Note:** FMP occasionally returns bad quotes (e.g., MU at $1133). No sanity filter yet — consider Polygon fallback.

### ROIC v2

Base: `https://api.roic.ai`

Auth: `?apikey=` query param

| Endpoint | Used for |
|----------|----------|
| `/v2/stock-prices/latest/{sym}` | Quotes, trending |
| `/v2/company/news/{sym}` | News, catalysts |
| `/v2/company/profile/{sym}` | Fundamentals |
| `/v2/fundamental/ratios/*` | Upside scoring |

### xAI

Base: `https://api.x.ai/v1`

```
POST /chat/completions
model: grok-3-fast (configurable)
search_parameters: { mode: "auto" }  # live web search
```

Returns JSON: `catalysts`, `social_chatter`, `sentiment`, `confidence`, `summary`, `references`

**Rate limits:** May hit HTTP errors under heavy dual-agent load. Retries: 3 attempts via `tenacity`.

### Claude (Anthropic)

Used only in `_dispatch_conviction_alerts()` for HIGH CONVICTION validation.

```
model: claude-sonnet-4-20250514
max_tokens: 300
```

Returns `{ should_send, adjusted_confidence, reason }`.

### Telegram

```
POST https://api.telegram.org/bot{token}/sendMessage
parse_mode: HTML
disable_web_page_preview: true
```

---

## 12. Configuration

All settings in `src/config.py` (`Settings` class), loaded from `.env`.

### Required secrets

```
POLYGON_API_KEY
FMP_API_KEY
ROIC_API_KEY
XAI_API_KEY
ANTHROPIC_API_KEY
TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID
```

### Key behavioral settings

| Variable | Default | Effect |
|----------|---------|--------|
| `SCAN_INTERVAL_MINUTES` | 10 | Intraday scan frequency |
| `MAX_WATCHLIST_SIZE` | 50 | Max symbols per scan |
| `MAX_ANALYSIS_SYMBOLS` | 20 | Breakout/direction focus count |
| `MIN_CATALYST_CONFIDENCE` | 0.75 | Min confidence to send catalyst |
| `CATALYST_COOLDOWN_MINUTES` | 360 | Dedup cooldown |
| `MAX_DAILY_ALERTS` | 0 | 0 = unlimited catalysts; >0 caps conviction |
| `ENABLE_XAI_CATALYST_SEARCH` | true | Grok catalyst scan |
| `ENABLE_CLAUDE_VALIDATION` | true | Claude conviction filter |
| `ENABLE_ANALYST_GRADES` | true | FMP grades integration |
| `ANALYST_GRADE_LOOKBACK_DAYS` | 14 | Recent upgrade/downgrade window |
| `THESIS_REVERSAL_LOOKBACK_DAYS` | 7 | Bearish news window for reversals |
| `SEMI_ALERT_PREFIX` | grok-semi-alerts-agent | Semi Telegram prefix |
| `SEMI_STATE_FILE` | data/semi_state.json | Semi state path |

---

## 13. State files

### `data/state.json` / `data/semi_state.json`

```json
{
  "sent_alerts": { "catalyst:INTC:...": "2026-06-19T20:20:55", "symbol:INTC": "..." },
  "daily_alerts": { "2026-06-19": ["NVDA"] },
  "trending_watchlist": ["INTC", "AMD", ...],
  "symbol_baselines": { "INTC": { "price": 133.99, "change_pct": 10.6, "volume": 5000000 } },
  "symbol_theses": { "INTC": { "direction": "bullish", "title": "...", ... } },
  "last_scan": "2026-06-19T20:30:00"
}
```

**Agents must never share state files.** Cooldowns and theses are per-agent.

### Clearing state (testing)

```bash
# Reset semi agent state
cat > data/semi_state.json << 'EOF'
{"sent_alerts":{},"daily_alerts":{},"trending_watchlist":[],"symbol_baselines":{},"symbol_theses":{},"last_scan":null}
EOF
```

---

## 14. File map

```
run.py                          # General entry
run_semi.py                     # Semi entry
install-semi-agent.sh           # Mac mini installer
Agent.md                        # This file
README.md                       # User-facing docs

src/
├── main.py                     # General scheduler + --force
├── semiconductor_main.py       # Semi scheduler + --force
├── config.py                   # Pydantic Settings from .env
├── models.py                   # Alert, NewsItem, AnalystGrade, AlertType
│
├── agent/
│   ├── stock_agent.py          # ★ Core orchestrator — scan pipeline, dispatch
│   └── semiconductor_agent.py  # Semi overrides (trending, catalyst, xAI)
│
├── semiconductor/
│   ├── universe.py             # ★ SEMI_UNIVERSE dict (59 symbols)
│   └── catalyst.py             # Semi catalyst keywords + category tags
│
├── analysis/
│   ├── trending.py             # General trending
│   ├── semiconductor_trending.py
│   ├── catalyst.py             # News scoring, ROIC catalysts
│   ├── analyst_grades.py       # FMP grades → upgrade/downgrade alerts
│   ├── thesis_reversal.py      # Bullish thesis → reversal detection
│   ├── relevance.py            # News-to-symbol relevance filter
│   ├── breakout.py             # 20-day resistance breakouts
│   ├── direction.py            # Momentum reversal/fade
│   └── conviction.py           # Price targets, high-conviction picks
│
├── data/
│   ├── polygon_client.py       # Polygon REST
│   ├── fmp_client.py           # FMP stable + grades + TOP_ANALYST_FIRMS
│   └── roic_client.py          # ROIC v2
│
├── ai/
│   ├── xai_client.py           # Grok catalyst search + to_alerts()
│   └── claude_client.py        # Conviction validation
│
├── alerts/
│   └── telegram.py             # TelegramAlerter.send()
│
├── market/
│   └── calendar.py             # US market hours, premarket window
│
└── utils/
    ├── state.py                # AgentState persistence
    ├── dedup.py                # catalyst_dedup_key, normalize_headline
    └── http.py                 # HttpClient with tenacity retries
```

---

## 15. Telegram message format

```
<b>{prefix}</b> | {LABEL}

<b>{SYMBOL}</b> — {title}

Current Price: $133.99
2-4 Week Target: $155.51 (+16.1%)

{catalyst summary}

<b>Top analyst upgrade:</b>
• B of A Securities (2026-06-11): Underperform → Buy

<b>References:</b>
• <a href="...">Headline (polygon)</a>
• <a href="...">B of A Securities upgrade (fmp_grades)</a>

Confidence: 85%
```

---

## 16. Deployment — Mac mini (semi agent)

### Install

```bash
curl -fsSL https://raw.githubusercontent.com/tejokumar/grok-stocks-alert/main/install-semi-agent.sh | bash
```

Installs to: `~/projects/grok-stocks-alert`

### Scripts created by installer

| Script | Purpose |
|--------|---------|
| `start-semi-agent.sh` | Production run (market hours) |
| `test-semi-agent.sh` | `run_semi.py --force` |

### LaunchAgent

- Label: `com.tejokumar.grok-semi-alerts`
- Path: `~/Library/LaunchAgents/com.tejokumar.grok-semi-alerts.plist`
- `RunAtLoad` + `KeepAlive` = auto-start on login, restart on crash

---

## 17. API call volume (per scan)

Measured semi agent scan (~518 HTTP calls):

| Provider | Calls/scan |
|----------|------------|
| FMP | ~186 |
| ROIC | ~182 |
| Polygon | ~98 |
| xAI | ~12–36 (with retries) |
| Telegram | ~0–16 |

**Daily (both agents, 41 scans each):** ~34,000 REST calls + ~984 xAI calls.

---

## 18. Known issues & pitfalls

| Issue | Detail | Fix direction |
|-------|--------|---------------|
| FMP bad quotes | MU returned $1133.99 | Add price sanity check vs 20-day avg; Polygon fallback |
| xAI rate limits | HTTPStatusError under dual-agent load | Reduce symbols, disable on one agent, increase interval |
| Analyst upgrade dropped | Lost in per-symbol merge | Already fixed via `_enrich_with_analyst_grade()` |
| Cross-tagged news | Wrong ticker on catalyst | `is_relevant_to_symbol()` — extend aliases as needed |
| State not cleared on reinstall | Old cooldowns persist | Delete `data/semi_state.json` before testing |
| `symbol:` cooldown | Blocks new catalyst for 6h even if different news | By design — prevents spam |

---

## 19. Testing commands

```bash
# Activate venv
source .venv/bin/activate

# Force scan (either agent)
python run_semi.py --force
python run.py --force

# Verify imports
python -c "from src.agent.semiconductor_agent import SemiconductorAlertAgent; print('OK')"

# Check universe size
python -c "from src.semiconductor.universe import SEMI_UNIVERSE; print(len(SEMI_UNIVERSE))"

# Clear semi state and test
echo '{"sent_alerts":{},"daily_alerts":{},"trending_watchlist":[],"symbol_baselines":{},"symbol_theses":{},"last_scan":null}' > data/semi_state.json
python run_semi.py --force
```

---

## 20. Extension guide for new coding agents

### Add a new symbol to semi universe

Edit `src/semiconductor/universe.py` → `SEMI_UNIVERSE` dict. Add alias to `src/analysis/relevance.py` → `COMPANY_ALIASES` if needed.

### Add a third themed agent

1. Create `src/{theme}/universe.py` and `src/{theme}/catalyst.py`
2. Create `src/analysis/{theme}_trending.py`
3. Subclass `StockAlertAgent` (see `SemiconductorAlertAgent`)
4. Create `src/{theme}_main.py` and `run_{theme}.py`
5. Add `{theme}_state_file` and `{theme}_alert_prefix` to `src/config.py`
6. Use separate state file — **never share state between agents**

### Modify catalyst behavior

- General keywords: `src/analysis/catalyst.py` → `CATALYST_KEYWORDS`, `HIGH_IMPACT_KEYWORDS`
- Semi keywords: `src/semiconductor/catalyst.py` → `SEMI_CATALYST_KEYWORDS`
- Strong threshold: `settings.strong_catalyst_keyword_hits`, `settings.min_catalyst_confidence`

### Modify alert dispatch

All dispatch logic is in `src/agent/stock_agent.py`:

- `_dispatch_catalyst_alerts()` — main catalyst path
- `_dispatch_thesis_reversals()` — reversal path
- `_dispatch_conviction_alerts()` — Claude-validated picks

### Add a new data source

1. Create client in `src/data/`
2. Wire into relevant analyzer in `src/analysis/`
3. Export from `src/data/__init__.py`
4. Add API key to `src/config.py` and `.env.example`

### Safe change checklist

- [ ] Both agents tested with `--force` if touching `stock_agent.py`
- [ ] State file format backward-compatible if touching `state.py`
- [ ] `is_relevant_to_symbol()` updated for new tickers
- [ ] Reference links populated in `metadata.references`
- [ ] Bullish-first policy preserved for catalyst dispatch
- [ ] Semi agent still filters to universe in trending + catalyst

---

## 21. Cost estimate (both agents, per trading day)

| Category | Daily | Monthly (~22 days) |
|----------|-------|-------------------|
| Subscriptions (Polygon, FMP, ROIC) | ~$6–10 | ~$120–240 |
| xAI (grok-3-fast + search) | ~$3–15 | ~$65–330 |
| Claude (conviction, usually 0) | ~$0–2 | ~$0–40 |
| **Total** | **~$10–20** | **~$250–400** |

Cost reduction: `ENABLE_XAI_CATALYST_SEARCH=false`, `SCAN_INTERVAL_MINUTES=15`, run semi agent part-time only.

---

## 22. Do not

- Share state files between agents
- Remove `is_relevant_to_symbol()` checks — causes cross-ticker false alerts
- Send analyst downgrades as first bullish alerts — use thesis reversal path
- Use Polygon websockets — architecture is REST-only by design
- Commit `.env` — secrets only in local `.env`
- Assume FMP quotes are always correct — validate outliers

---

## 23. Quick reference

```bash
# General agent
python run.py
python run.py --force

# Semi agent
python run_semi.py
python run_semi.py --force

# Mac mini install
curl -fsSL https://raw.githubusercontent.com/tejokumar/grok-stocks-alert/main/install-semi-agent.sh | bash

# After install
nano ~/projects/grok-stocks-alert/.env
~/projects/grok-stocks-alert/test-semi-agent.sh
~/projects/grok-stocks-alert/start-semi-agent.sh
```

**Repo:** https://github.com/tejokumar/grok-stocks-alert  
**Default install path:** `~/projects/grok-stocks-alert`