<p align="center">
  <h1 align="center">ReNoUn</h1>
  <p align="center"><strong>Structural Risk Telemetry for Crypto Markets</strong></p>
  <p align="center">
    <a href="https://web-production-817e2.up.railway.app/v1/status"><img src="https://img.shields.io/badge/API-live-brightgreen" alt="API Live"></a>
    <a href="#accuracy"><img src="https://img.shields.io/badge/bounded_accuracy-100%25-7C9A6E" alt="100% bounded accuracy"></a>
    <a href="https://web-production-817e2.up.railway.app/docs"><img src="https://img.shields.io/badge/docs-OpenAPI-orange" alt="API Docs"></a>
    <a href="https://github.com/98lukehall/renoun-mcp/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="License"></a>
    <img src="https://img.shields.io/badge/patent_pending-%2363%2F923%2C592-lightgrey" alt="Patent Pending #63/923,592">
  </p>
</p>

Classifies crypto market structural regimes — **bounded**, **active**, or **unstable** — with **100% bounded regime accuracy** (128+ graded predictions, zero false positives). Estimates **regime stability half-life**: how many minutes until the current structure is likely to transition. Every prediction is public, timestamped, and graded — no other crypto signal service does this.

One GET request. One action field. Pre-trade risk gate for trading bots, autonomous agents, and quant systems.

## Quick Start

### 1. Get a Key (Free, No Credit Card)

```bash
curl -X POST https://web-production-817e2.up.railway.app/v1/keys/provision \
  -H "Content-Type: application/json" \
  -d '{"email": "you@example.com", "agent_name": "my-bot"}'
```

Returns an `rn_agent_` key. 50 free calls/day. $0.02/call after that.

### 2. Check a Regime

```bash
curl https://web-production-817e2.up.railway.app/v1/regime/live/BTCUSDT \
  -H "Authorization: Bearer rn_agent_YOUR_KEY"
```

### 3. Read the Response

```json
{
  "regime": "bounded",
  "action": "proceed",
  "dhs": 0.83,
  "exposure": 0.95,
  "constellation": "HIGH_SYMMETRY",
  "envelope_pct": 1.5,
  "description": "Tight equilibrium, <1.5% move expected",
  "action_detail": "Structure healthy. Position size: 95% of intended.",
  "stability": {
    "halflife_minutes": 240,
    "stability_score": 0.82,
    "instability_risk": "low",
    "time_horizon": "2-4 hours",
    "urgency": "none"
  },
  "_meta": {
    "provider": "renoun",
    "version": "1.4.0",
    "accuracy": "100% bounded regime accuracy, 128+ graded",
    "provision_url": "https://web-production-817e2.up.railway.app/v1/keys/provision",
    "docs": "https://harrisoncollab.com"
  }
}
```

### 4. Use It

```python
import requests

def check_regime(symbol="BTCUSDT", key="rn_agent_YOUR_KEY"):
    r = requests.get(
        f"https://web-production-817e2.up.railway.app/v1/regime/live/{symbol}",
        headers={"Authorization": f"Bearer {key}"}
    )
    return r.json()

regime = check_regime("BTCUSDT")

if regime["action"] == "avoid":
    pass  # structure fragmenting — skip trade
elif regime["stability"]["urgency"] == "exit_now":
    close_position()  # regime degrading fast
elif regime["stability"]["urgency"] == "prepare_exit":
    set_tight_stop()  # regime softening
elif regime["action"] == "reduce":
    execute(size=intended * regime["exposure"])
else:
    execute(size=intended)  # structure healthy, full size
```

## Regime Types

| Regime | Action | What It Means |
|--------|--------|---------------|
| `bounded` | `proceed` | Price expected within envelope. Trade at full size. |
| `active` | `reduce` | Dynamic conditions. Scale position by `exposure` scalar. |
| `unstable` | `avoid` | Structure fragmenting. Skip this trade. |

## Stability Half-Life

Every response includes a `stability` block estimating how long the current regime will persist.

| Field | Meaning |
|-------|---------|
| `halflife_minutes` | Minutes until 50% probability of regime transition |
| `stability_score` | 0.0–1.0 composite stability (1.0 = maximally stable) |
| `instability_risk` | `low` / `moderate` / `elevated` / `high` |
| `time_horizon` | Human-readable: "2-4 hours", "15-30 minutes", etc. |
| `urgency` | `none` / `watch` / `prepare_exit` / `exit_now` |
| `exit_window_minutes` | Safe exit window (only when urgency is `prepare_exit` or `exit_now`) |

Without half-life, an agent knows "the regime is bounded, proceed." With half-life, the same agent knows "the regime is bounded, proceed, AND this structure is likely stable for 4 hours." Or: "the regime is active, reduce, AND exit within 15 minutes."

## API Endpoints

Base URL: `https://web-production-817e2.up.railway.app`

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/v1/regime/live/{symbol}` | GET | Bearer | Live regime + stability for a Binance symbol |
| `/v1/regime` | POST | Bearer | Regime from your own OHLCV klines |
| `/v1/regime/batch` | POST | Bearer | Multi-asset regime + portfolio aggregate (max 10) |
| `/v1/keys/provision` | POST | None | Self-provision an API key |
| `/v1/usage` | GET | Bearer | Today's call count, free vs billable |
| `/v1/webhooks/register` | POST | Bearer | Register for regime change notifications |
| `/v1/webhooks` | GET | Bearer | List registered webhooks |
| `/v1/agents/leaderboard` | GET | None | Agent usage leaderboard |
| `/v1/status` | GET | None | Liveness + version info |
| `/docs` | GET | None | Interactive OpenAPI explorer |

### Response Headers

Every regime response includes machine-readable headers:

```
X-ReNoUn-Regime: bounded
X-ReNoUn-Action: proceed
X-ReNoUn-Stability: 0.82
X-ReNoUn-Halflife: 240
X-ReNoUn-Urgency: none
X-ReNoUn-Cache: HIT
X-RateLimit-Remaining: 47
```

## Pricing

| | Agent Tier (default) | Pro Tier |
|---|------|------|
| Daily free calls | 50 | 1,000 |
| Price per call (beyond free) | $0.02 | Included |
| Rate limit | 1,000/hr, 10,000/day | 1,000/hr |
| Key prefix | `rn_agent_` | `rn_live_` |
| Provisioning | Self-serve (POST) | [Subscribe via Stripe](https://harrisoncollab.com) |

No credit card required for the agent tier. Agents provision their own keys.

## Accuracy

**100% bounded regime accuracy** across 128+ graded predictions. When ReNoUn classifies a regime as bounded (proceed), price stays within the predicted envelope every time. Zero false positives. Every prediction is public, timestamped, and graded: [@98lukehall on X](https://x.com/98lukehall). No other crypto signal service publishes every call with a pass/fail grade.

Active regimes (CONVERGENCE, PATTERN_BREAK) are graded against tighter thresholds and have lower accuracy — they recommend position scaling via the exposure scalar, not full-size trades.

**What this means:** when ReNoUn says "bounded," you can trade at full size with confidence. When it says "active," scale your position by the exposure scalar. When it says "unstable," stay out.

**What this does NOT mean:** ReNoUn does not predict whether price goes up or down. It measures structural stability. Use it as a risk gate, not a signal.

## How It Works

ReNoUn is a 17-channel structural analysis engine. It maps OHLCV candle data onto three measurement dimensions:

**Recurrence (Re₁–Re₅)** — Is the market repeating known patterns? Price rhythms, volume profiles, volatility persistence, session structure, mean-reversion signatures.

**Novelty (No₁–No₆)** — Is something genuinely new happening? Regime breaks, flow reversals, volatility spikes, session disruptions, behavioral shifts, cross-signal rarity.

**Unity (Un₁–Un₆)** — Is the market holding together? Trend cohesion, volatility-price alignment, session continuity, reference-frame stability, structural symmetry.

From these 17 signals the engine computes a **Dialectical Health Score** (DHS: 0.0–1.0) and detects **8 constellation patterns**:

| Constellation | Regime | Description |
|---------------|--------|-------------|
| `CLOSED_LOOP` | bounded | Range-bound, <2% move expected |
| `HIGH_SYMMETRY` | bounded | Tight equilibrium, <1.5% move expected |
| `CONVERGENCE` | active | Trend-active, moves up to 2.5% |
| `SURFACE_VARIATION` | bounded | Choppy but bounded, <2.5% net move |
| `DIP_AND_RECOVERY` | active | Recovery regime, moves up to 2.5% |
| `PATTERN_BREAK` | active | Regime shift underway, elevated range |
| `SCATTERING` | unstable | Structure fragmenting, risk elevated |
| `REPEATED_DISRUPTION` | unstable | Unstable regime, risk elevated |

The stability half-life is computed from DHS momentum, unity channel trends, novelty pressure, constellation persistence, and known destabilizing/stabilizing sequences.

## Agent Discovery

ReNoUn is discoverable by AI agents through standard protocols:

- **`llms.txt`** at [harrisoncollab.com/llms.txt](https://harrisoncollab.com/llms.txt)
- **`.well-known/mcp.json`** at [harrisoncollab.com/.well-known/mcp.json](https://harrisoncollab.com/.well-known/mcp.json)
- **`_meta` block** in every API response with provisioning URL and docs
- **`X-Agent-Compatible: true`** header on every response

### MCP Server (Claude Desktop / Claude Code)

```json
{
  "mcpServers": {
    "renoun": {
      "command": "python3",
      "args": ["-m", "server"],
      "env": { "RENOUN_API_KEY": "rn_agent_YOUR_KEY" }
    }
  }
}
```

```bash
claude mcp add renoun python3 -m server
```

### System Prompt for Your Agent

```
Before any crypto trade, check the structural regime:
  GET /v1/regime/live/{SYMBOL}
If action is "avoid" — skip the trade (structure unstable).
If action is "reduce" — multiply position by the exposure scalar.
If urgency is "exit_now" — close position immediately.
If urgency is "prepare_exit" — set tight stop loss.
If action is "proceed" — execute at intended size.
ReNoUn classifies structural regimes with 100% bounded accuracy.
It does not predict price direction.
```

## Batch / Portfolio

Check multiple assets in one call with portfolio-level risk aggregation:

```bash
curl -X POST https://web-production-817e2.up.railway.app/v1/regime/batch \
  -H "Authorization: Bearer rn_agent_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT"], "timeframe": "1h"}'
```

Returns per-asset regimes plus `portfolio_action`, `portfolio_exposure`, and `unstable_count`.

## Webhooks

Get notified when regimes change:

```bash
curl -X POST https://web-production-817e2.up.railway.app/v1/webhooks/register \
  -H "Authorization: Bearer rn_agent_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://your-bot.com/webhook",
    "symbols": ["BTCUSDT"],
    "events": ["regime_change"],
    "secret": "your_hmac_secret"
  }'
```

Webhook payloads are HMAC-signed. Max 5 webhooks per key.

## Conversation Analysis

ReNoUn also analyzes turn-based conversations — detecting stuck loops, surface variation, convergence, and structural health. The conversation tools use the same 17-channel engine applied to speaker/text turns instead of OHLCV candles.

| Tool | Purpose |
|------|---------|
| `renoun_analyze` | Full 17-channel structural analysis |
| `renoun_health_check` | Quick triage — one score, one pattern |
| `renoun_compare` | Structural A/B test between conversations |
| `renoun_pattern_query` | Longitudinal session history |

See the [API docs](https://web-production-817e2.up.railway.app/docs) for conversation analysis endpoints.

## Version

- Server: 1.3.1
- Engine: 4.1
- Schema: 1.1
- Protocol: MCP 2024-11-05

## Patent Notice

The core computation engine is proprietary and patent-pending (#63/923,592). The MCP server wraps it as a black box — agents call the API and receive structured results.

## License

MCP server and API wrapper: MIT. Core engine: Proprietary.

---

<p align="center">
  <a href="https://harrisoncollab.com">Harrison Collab</a> · <a href="https://web-production-817e2.up.railway.app/docs">API Docs</a> · <a href="https://x.com/98lukehall">Live Predictions on X</a>
</p>
