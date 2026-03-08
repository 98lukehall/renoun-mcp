# MCP Market Listing — renoun-mcp

## Server Name

renoun-mcp

## Description

Structural observability for AI conversations and financial risk management. 17-channel pattern detection engine that measures Recurrence, Novelty, and Unity without analyzing semantic content. Detects loops, stuck states, breakthroughs, convergence, and scattering. Also applies structural analysis to OHLCV financial data for risk overlay with validated drawdown reduction.

Patent Pending #63/923,592.

## Install Command

```bash
pip install renoun-mcp
```

## Quick Start

```json
{
  "mcpServers": {
    "renoun": {
      "command": "python3",
      "args": ["-m", "renoun_mcp"],
      "env": {
        "RENOUN_API_KEY": "rn_live_your_key_here"
      }
    }
  }
}
```

## Tool List

| Tool | Description |
|------|-------------|
| `renoun_analyze` | Full 17-channel structural analysis. Returns DHS, 8 constellation patterns, breakthrough moments, recommendations. |
| `renoun_health_check` | Sub-50ms structural triage. One score, one pattern, one summary. |
| `renoun_compare` | Structural A/B test between two conversations. DHS delta, constellation transitions, channel shifts. |
| `renoun_pattern_query` | Longitudinal history. Save, query, filter, and trend analysis results over time. |
| `renoun_steer` | Real-time monitoring. Rolling window analysis with automatic steering signals. |
| `renoun_finance_analyze` | OHLCV structural analysis. Exposure recommendations validated 31/31 for drawdown reduction. |

## Features

- **17-channel engine**: 5 Recurrence channels (lexical, syntactic, rhythmic, turn-taking, self-interruption), 6 Novelty channels, 6 Unity channels
- **8 constellation patterns**: CLOSED_LOOP, HIGH_SYMMETRY, PATTERN_BREAK, CONVERGENCE, SCATTERING, REPEATED_DISRUPTION, DIP_AND_RECOVERY, SURFACE_VARIATION
- **Agent action mappings**: Each constellation maps to a recommended agent behavior (explore_new_angle, slow_down, maintain_trajectory, etc.)
- **Real-time steering**: `renoun_steer` maintains rolling window buffers and emits signals when thresholds are crossed
- **Longitudinal tracking**: Save and query analysis results over time, compute DHS trends
- **Financial risk overlay**: Apply the same structural engine to OHLCV data for position sizing
- **Validated performance**: 31/31 drawdown reduction, 21.3pp avg DD improvement on black swan events, 0.1 median Sharpe cost
- **Privacy-preserving**: Measures structure, not content. No semantic analysis.
- **Content-free**: Works on any turn-based interaction regardless of language or domain

## Use Cases

### Agent Observability
Monitor AI agent conversations for structural problems. Detect when agents loop, scatter, or produce cosmetic variation without meaningful progress. Trigger automatic interventions via steering signals.

### Conversation Quality Analysis
Analyze any dialogue for structural health: therapy sessions, coaching calls, sales conversations, support tickets. Identify breakthrough moments, stuck states, and convergence patterns.

### Prompt Engineering
A/B test prompt strategies structurally. Compare sessions to see whether revised prompts produce healthier dynamics, less looping, or better convergence.

### Financial Risk Management
Structural risk overlay for crypto markets. Reduce exposure during structural disorder. Validated across 9 assets (BTC, ETH, SOL, DOGE, AVAX, LINK, ADA, DOT, MATIC) on 5 timeframes (1m, 5m, 15m, 1h, 4h).

### Real-Time Monitoring
Feed live conversation turns to `renoun_steer` for continuous structural monitoring. Receive HIGH/MEDIUM/INFO alerts when DHS drops, loops persist, or scattering is detected.

## Pricing

- **Free**: 50 calls/day, all 6 tools
- **Pro**: $4.99/mo (Stripe), unlimited calls

## Links

- **GitHub**: https://github.com/98lukehall/renoun-mcp
- **PyPI**: https://pypi.org/project/renoun-mcp/
- **API Key**: https://harrisoncollab.com
