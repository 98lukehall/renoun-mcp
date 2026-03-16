<p align="center">
  <h1 align="center">ReNoUn</h1>
  <p align="center"><strong>Structural observability for AI conversations and financial markets</strong></p>
  <p align="center">
    <a href="https://codecov.io/gh/98lukehall/renoun-mcp"><img src="https://codecov.io/gh/98lukehall/renoun-mcp/branch/main/graph/badge.svg" alt="codecov"></a>
    <a href="https://github.com/98lukehall/renoun-mcp/actions/workflows/ci.yml"><img src="https://github.com/98lukehall/renoun-mcp/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
    <a href="https://pypi.org/project/renoun-mcp/"><img src="https://img.shields.io/pypi/v/renoun-mcp?color=7C9A6E&label=PyPI" alt="PyPI"></a>
    <a href="https://pypi.org/project/renoun-mcp/"><img src="https://img.shields.io/pypi/pyversions/renoun-mcp?color=5B7B9E" alt="Python"></a>
    <a href="https://github.com/98lukehall/renoun-mcp/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="License"></a>
    <a href="https://web-production-817e2.up.railway.app/docs"><img src="https://img.shields.io/badge/API-docs-orange" alt="API Docs"></a>
    <a href="#financial-risk-overlay"><img src="https://img.shields.io/badge/finance-98%25_accuracy-7C9A6E" alt="Finance: 98% accuracy"></a>
    <img src="https://img.shields.io/badge/patent_pending-%2363%2F923%2C592-lightgrey" alt="Patent Pending #63/923,592">
  </p>
</p>

Your agent doesn't know when it's going in circles. **ReNoUn does.**

Detects when conversations are stuck in loops, producing cosmetic variation instead of real change, or failing to converge. Measures structural health across 17 channels without analyzing content — works on any turn-based interaction.

## Why?

LLMs get stuck. They produce responses that *sound* different but are structurally identical — what we call **surface variation**. A human might notice after 5 turns. An agent never will.

ReNoUn catches this in ~200ms by measuring structure, not content. It works on any language, any topic, any model.

## Install

```bash
pip install renoun-mcp
```

For financial market analysis with streaming support:

```bash
pip install renoun-mcp[finance]
```

## Quick Start

### As an MCP Server (Claude Desktop)

Add to your Claude Desktop config (`~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
    "mcpServers": {
        "renoun": {
            "command": "python3",
            "args": ["-m", "server"],
            "env": {
                "RENOUN_API_KEY": "rn_live_your_key_here"
            }
        }
    }
}
```

### As a REST API

```bash
curl -X POST https://web-production-817e2.up.railway.app/v1/analyze \
  -H "Authorization: Bearer rn_live_your_key_here" \
  -H "Content-Type: application/json" \
  -d '{"utterances": [
    {"speaker": "user", "text": "I feel stuck"},
    {"speaker": "assistant", "text": "Tell me more about that"},
    {"speaker": "user", "text": "I keep going in circles"},
    {"speaker": "assistant", "text": "What patterns do you notice?"},
    {"speaker": "user", "text": "The same thoughts repeat"}
  ]}'
```

### As a Claude Code MCP

```bash
claude mcp add renoun python3 -m server
```

## Demo Output

```json
{
  "dialectical_health": 0.491,
  "loop_strength": 0.36,
  "channels": {
    "recurrence": { "Re1_lexical": 0.0, "Re2_syntactic": 0.3, "Re3_rhythmic": 0.5, "Re4_turn_taking": 1.0, "Re5_self_interruption": 0.0, "aggregate": 0.36 },
    "novelty":    { "No1_lexical": 1.0, "No2_syntactic": 1.0, "No3_rhythmic": 0.5, "No4_turn_taking": 0.5, "No5_self_interruption": 0.0, "No6_vocabulary_rarity": 0.833, "aggregate": 0.639 },
    "unity":      { "Un1_lexical": 0.5, "Un2_syntactic": 0.135, "Un3_rhythmic": 0.898, "Un4_interactional": 0.7, "Un5_anaphoric": 0.705, "Un6_structural_symmetry": 0.5, "aggregate": 0.573 }
  },
  "constellations": [],
  "novelty_items": [
    { "index": 4, "text": "The same thoughts repeat", "score": 0.457, "reason": "shifts conversational direction" }
  ],
  "summary": "Moderate dialectical health (DHS: 0.491). Diverse exploration (loop strength: 0.36). Key moment at turn 4.",
  "recommendations": ["■ Key novelty at turn 4. Consider returning to this moment."]
}
```

## Tools

| Tool | Purpose | Speed | Tier |
|------|---------|-------|------|
| `renoun_analyze` | Full 17-channel structural analysis with breakthrough detection | ~200ms | Pro |
| `renoun_health_check` | Quick triage — one score, one pattern, one action | ~50ms | Free |
| `renoun_compare` | Structural A/B test between two conversations | ~400ms | Pro |
| `renoun_pattern_query` | Save, query, and trend longitudinal session history | ~10ms | Pro |
| `renoun_finance_analyze` | Structural analysis of OHLCV data with exposure recommendations | ~200ms | Pro |

## How It Works

ReNoUn measures 17 structural channels across three dimensions:

**Recurrence** (5 channels) — Is structure repeating? Lexical, syntactic, rhythmic, turn-taking, and self-interruption patterns.

**Novelty** (6 channels) — Is anything genuinely new emerging? Lexical novelty, syntactic novelty, rhythmic shifts, turn-taking changes, self-interruption breaks, and vocabulary rarity.

**Unity** (6 channels) — Is the conversation holding together? Lexical coherence, syntactic coherence, rhythmic coherence, interactional alignment, anaphoric reference, and structural symmetry.

From these 17 signals, ReNoUn computes a **Dialectical Health Score** (DHS: 0.0–1.0) and detects **8 constellation patterns**, each with a recommended agent action:

| Pattern | What It Means | Agent Action |
|---------|---------------|--------------|
| CLOSED_LOOP | Stuck recycling the same structure | `explore_new_angle` |
| HIGH_SYMMETRY | Rigid, overly balanced exchange | `introduce_variation` |
| CONVERGENCE | Moving toward resolution | `maintain_trajectory` |
| PATTERN_BREAK | Something just shifted | `support_integration` |
| SURFACE_VARIATION | Sounds different but structurally identical | `go_deeper` |
| SCATTERING | Falling apart, losing coherence | `provide_structure` |
| REPEATED_DISRUPTION | Keeps breaking without stabilizing | `slow_down` |
| DIP_AND_RECOVERY | Disrupted then recovered | `acknowledge_shift` |

## Pricing

| | Free | Pro ($4.99/mo) |
|---|------|---------------|
| `renoun_health_check` | ✓ | ✓ |
| `renoun_analyze` | — | ✓ |
| `renoun_compare` | — | ✓ |
| `renoun_pattern_query` | — | ✓ |
| `renoun_finance_analyze` | — | ✓ |
| Daily requests | 20 | 1,000 |
| Max turns per analysis | 200 | 500 |

**Get your API key:** [Subscribe via Stripe](https://web-production-817e2.up.railway.app/v1/billing/checkout) or visit [harrisoncollab.com](https://harrisoncollab.com).

## REST API

Base URL: `https://web-production-817e2.up.railway.app`

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/v1/analyze` | POST | Bearer | Full 17-channel analysis |
| `/v1/health-check` | POST | Bearer | Fast structural triage |
| `/v1/compare` | POST | Bearer | A/B test two conversations |
| `/v1/patterns/{action}` | POST | Bearer | Longitudinal pattern history |
| `/v1/finance/analyze` | POST | Bearer | OHLCV structural analysis with exposure recs |
| `/v1/status` | GET | None | Liveness + version info |
| `/v1/billing/checkout` | POST | None | Create Stripe checkout session |
| `/docs` | GET | None | Interactive API explorer |

All authenticated endpoints require: `Authorization: Bearer rn_live_...`

## Input Format

All analysis tools accept conversation turns as speaker/text pairs:

```json
{
    "utterances": [
        {"speaker": "user", "text": "I keep going back and forth on this decision."},
        {"speaker": "assistant", "text": "What makes it feel difficult to commit?"},
        {"speaker": "user", "text": "I think I'm afraid of making the wrong choice."}
    ]
}
```

Minimum 3 turns required. 10+ recommended for reliable results. 20+ for stable constellation detection.

## Integration

### Claude Desktop

```json
{
    "mcpServers": {
        "renoun": {
            "command": "python3",
            "args": ["-m", "server"],
            "env": { "RENOUN_API_KEY": "rn_live_your_key_here" }
        }
    }
}
```

### Claude Code

```bash
RENOUN_API_KEY=rn_live_your_key_here claude mcp add renoun python3 -m server
```

### Generic MCP Client

```json
{
    "transport": "stdio",
    "command": "python3",
    "args": ["-m", "server"],
    "env": { "RENOUN_API_KEY": "rn_live_your_key_here" }
}
```

### Environment Variable

```bash
export RENOUN_API_KEY=rn_live_your_key_here
```

## Longitudinal Storage

Results persist to `~/.renoun/history/`. Use `renoun_pattern_query` to save, list, query, and trend session history over time. Filter by date, domain, constellation pattern, or DHS threshold.

---

## Financial Risk Overlay

The same 17-channel engine that detects stuck conversations also detects structural disorder in financial markets. When market structure breaks down, reduce exposure. When it's coherent, stay the course.

- **98% accuracy** across 240+ live graded predictions
- **21.3pp** average DD improvement on black swan events (COVID, LUNA, FTX)
- **0.1 Sharpe** median cost — cheap insurance
- Works on any OHLCV data — crypto, equities, forex, commodities
- **Not a prediction engine** — a structural risk overlay

### How It Works (Finance)

ReNoUn maps OHLCV candle data onto the same 17 structural channels used for conversation analysis:

**Recurrence (Re1-Re5)** — Is the market repeating known patterns? Price action rhythms, volume profiles, volatility persistence, session structure, and mean-reversion signatures.

**Novelty (No1-No6)** — Is something genuinely new happening? Regime breaks, flow reversals, volatility spikes, session disruptions, behavioral shifts, and cross-signal rarity.

**Unity (Un1-Un6)** — Is the market holding together? Trend cohesion across price and volume, volatility-price alignment, session continuity, reference-frame stability, and structural symmetry between first-half and second-half of the analysis window.

From these 17 signals, the engine produces:

- **DHS (0.0-1.0)** — Dialectical Health Score. High = coherent structure, low = disorder.
- **Constellation patterns** — The same 8 patterns (CONVERGENCE, SCATTERING, CLOSED_LOOP, etc.) applied to market structure.
- **Stress metrics** — Drawdown depth, volatility expansion, and structural fragility indicators.
- **Exposure scalar** — A smoothed, persistence-weighted recommendation mapping structural health to position sizing. High DHS = full exposure, low DHS = reduce.

### Quick Start (Finance)

#### Python API

```python
from renoun_finance import analyze_financial

klines = [
    {"open": 100, "high": 105, "low": 98, "close": 103, "volume": 1000},
    {"open": 103, "high": 107, "low": 101, "close": 106, "volume": 1200},
    # ... 50+ candles recommended for reliable signals
]

result = analyze_financial(klines, symbol="BTCUSDT", timeframe="1h")

print(result["dialectical_health"])  # 0.72
print(result["constellations"])      # [{"detected": "CONVERGENCE", ...}]
print(result["stress"])              # {"drawdown": 0.15, "vol_expansion": 0.08}
print(result["exposure"])            # {"scalar": 0.85, "regime": "healthy"}
```

#### MCP Tool

```json
{
    "tool": "renoun_finance_analyze",
    "arguments": {
        "klines": [
            {"open": 100, "high": 105, "low": 98, "close": 103, "volume": 1000},
            {"open": 103, "high": 107, "low": 101, "close": 106, "volume": 1200}
        ],
        "symbol": "BTCUSDT",
        "timeframe": "1h",
        "include_exposure": true
    }
}
```

#### REST API

```bash
curl -X POST https://web-production-817e2.up.railway.app/v1/finance/analyze \
  -H "Authorization: Bearer rn_live_your_key_here" \
  -H "Content-Type: application/json" \
  -d '{
    "klines": [{"open": 100, "high": 105, "low": 98, "close": 103, "volume": 1000}],
    "symbol": "BTCUSDT",
    "timeframe": "1h",
    "include_exposure": true
  }'
```

### Live Streaming

For real-time monitoring with continuous exposure updates:

```bash
python renoun_stream.py --symbol BTCUSDT --tf 5m
python renoun_stream.py --symbols BTCUSDT,ETHUSDT,SOLUSDT  # multi-asset
```

The streamer connects to exchange websocket feeds, buffers candles, and runs `renoun_finance_analyze` on a rolling window. Output includes live DHS, constellation detection, and exposure scalar updates.

Supported timeframes: `1m`, `5m`, `15m`, `1h`, `4h`, `1d`.

Requires the finance extras: `pip install renoun-mcp[finance]`.

### Backtest Results

Validated across 31 datasets (9 crypto assets, 5 timeframes per asset):

| Metric | Result |
|--------|--------|
| Datasets tested | 31 (9 assets x 5 timeframes) |
| Live prediction accuracy | 98% (240+ graded) |
| Avg DD improvement | 5.7pp |
| Black swan DD improvement | 21.3pp avg (4 events) |
| Sharpe improved | 14/31 (45%) |
| Sharpe degraded | 17/31 (55%) |
| Median Sharpe cost | 0.1 |
| Negative impact (DD worse) | 0/31 (0%) |

The pattern is consistent: ReNoUn reduces drawdowns in every tested configuration. Sharpe impact is mixed because the overlay occasionally reduces exposure during recoveries, trimming upside along with downside. The median Sharpe cost of 0.1 is the price of insurance — you give up a small amount of return for significantly better tail-risk protection.

Best on high-volatility assets (DOGE, SHIB, ETH) where structural disorder is most frequent and drawdown events are deepest.

### The Honest Take

ReNoUn is **not** a prediction engine. It does **not** generate alpha. It does not tell you what to buy or when to enter.

What it does: measures structural market disorder and reduces exposure when structure breaks down. When price, volume, and volatility signals lose coherence — when the 17 channels show SCATTERING or REPEATED_DISRUPTION — the exposure scalar pulls you back. When structure is healthy and converging, you stay fully allocated.

Think of it as a VIX-based position sizer for markets where there is no options-implied volatility. Crypto has no VIX. Most small-cap equities have no liquid options chain. ReNoUn fills that gap by deriving structural disorder directly from OHLCV data.

**Best used as a risk overlay** — pair it with your own signal, your own strategy, your own edge. ReNoUn handles the "when to reduce" question so your signal can focus on the "what to trade" question.

---

## For AI Trading Agents

ReNoUn serves as a pre-trade structural risk check for autonomous trading agents. Call the regime endpoint before any crypto position to classify the current market structure.

### Quick Integration (3 lines)

```python
import requests

def check_regime(symbol="BTCUSDT", key="rn_agent_YOUR_KEY"):
    r = requests.get(f"https://web-production-817e2.up.railway.app/v1/regime/live/{symbol}",
                     headers={"Authorization": f"Bearer {key}"})
    return r.json()

# In your trading logic:
regime = check_regime("BTCUSDT")
if regime["action"] == "avoid":
    pass  # skip trade — structure fragmenting
elif regime["action"] == "reduce":
    execute(size=intended * regime["exposure"])  # scale down
else:
    execute(size=intended)  # full size — structure healthy
```

### Regime Types

| Regime | Action | What It Means |
|--------|--------|---------------|
| `bounded` | `proceed` | Price expected within envelope. Trade at full size. |
| `active` | `reduce` | Dynamic conditions. Multiply position by `exposure` scalar. |
| `unstable` | `avoid` | Structure fragmenting. Skip this trade. |

### Get a Key (Free)

```bash
curl -X POST https://web-production-817e2.up.railway.app/v1/keys/provision \
  -H "Content-Type: application/json" \
  -d '{"email": "you@example.com", "agent_name": "my-bot"}'
```

50 free calls/day. $0.02/call after that. No credit card to start.

### MCP Integration

```json
{
  "mcpServers": {
    "renoun": {
      "command": "python",
      "args": ["-m", "renoun_mcp"],
      "env": { "RENOUN_API_KEY": "rn_agent_YOUR_KEY" }
    }
  }
}
```

### System Prompt for Your Agent

```
Before any crypto trade, check the structural regime:
  GET /v1/regime/live/{SYMBOL}
If action is "avoid" — skip the trade (structure unstable).
If action is "reduce" — multiply position by the exposure scalar.
If action is "proceed" — execute at intended size.
ReNoUn classifies structural regimes with 98% accuracy across 240+ live predictions.
It does not predict price direction.
```

### Accuracy

98% regime classification accuracy across 240+ live, timestamped, graded predictions. Every prediction is public: [@98lukehall on X](https://x.com/98lukehall).

---

## Version

- Server: 1.2.0
- Engine: 4.1
- Schema: 1.1
- Protocol: MCP 2024-11-05

## Related

The **[ReNoUn Cowork Plugin](../renoun-plugin/)** provides skill files, slash commands, and reference documentation for agents using the Cowork plugin system. The MCP server and plugin share the same engine and can be used independently or together.

## Patent Notice

The core computation engine is proprietary and patent-pending (#63/923,592). This MCP server wraps it as a black box. Agents call `engine.score()` and receive structured results — they never access internal algorithms.

## License

MCP server and API wrapper: MIT. Core engine: Proprietary.

---

<p align="center">
  <a href="https://harrisoncollab.com">Harrison Collab</a> · <a href="https://web-production-817e2.up.railway.app/docs">API Docs</a> · <a href="https://pypi.org/project/renoun-mcp/">PyPI</a>
</p>
