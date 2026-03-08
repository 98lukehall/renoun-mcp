# PulseMCP Submission — renoun-mcp

## Server Details

- **Server Name**: renoun-mcp
- **Repo URL**: https://github.com/98lukehall/renoun-mcp
- **PyPI**: https://pypi.org/project/renoun-mcp/
- **Language**: Python
- **License**: Plugin wrapper: MIT | Core engine: Proprietary
- **Patent**: Pending #63/923,592

## Description

Patent-pending structural pattern detection for AI conversations and financial risk management. Measures structure across 17 channels (Recurrence, Novelty, Unity) without analyzing semantic content. Detects when conversations are stuck in loops, scattering apart, or converging toward resolution. Also applies the same structural engine to OHLCV financial data for risk overlay with validated drawdown reduction.

## Tool List (6 tools)

| Tool | Description |
|------|-------------|
| `renoun_analyze` | Full 17-channel structural analysis of conversations. Returns DHS (0-1), 8 constellation patterns, breakthrough moments, and actionable agent recommendations. Min 10 turns. |
| `renoun_health_check` | Sub-50ms structural triage. Returns one health score, one dominant pattern, one summary. Use for quick checks before deciding on full analysis. |
| `renoun_compare` | Structural A/B test between two conversations. Shows DHS delta, constellation transitions, and top channel shifts. Use for prompt iteration or session-over-session tracking. |
| `renoun_pattern_query` | Longitudinal pattern history. Save analysis results, query by date/domain/pattern/health, compute DHS trends over time. |
| `renoun_steer` | Real-time inference steering. Rolling window monitoring with automatic signals when structural thresholds are crossed (DHS drops, loop persistence, scattering). |
| `renoun_finance_analyze` | Structural analysis of OHLCV financial data. Returns DHS, constellation patterns, stress indicators, and exposure recommendations. Validated 31/31 drawdown reduction across 9 crypto assets and 5 timeframes. |

## Use Cases

### Conversation Quality Monitoring
Monitor AI agent conversations in real time. Detect when agents are stuck in loops (CLOSED_LOOP), producing cosmetic variation without real change (SURFACE_VARIATION), or losing coherence (SCATTERING). Trigger interventions automatically via `renoun_steer`.

### Therapy / Coaching Session Analysis
Analyze the structural dynamics of therapeutic or coaching sessions without reading content. Identify breakthrough moments (PATTERN_BREAK), healthy disruption-recovery cycles (DIP_AND_RECOVERY), and sessions that are productively converging.

### Prompt Iteration Testing
A/B test prompt strategies structurally. Run `renoun_compare` to see whether a revised prompt produces healthier structural dynamics, less looping, or better convergence than the original.

### Financial Risk Overlay
Apply the 17-channel engine to OHLCV candle data as a structural risk overlay. Reduce exposure during periods of structural disorder. Not a prediction engine — think of it as a "structural VIX for crypto."

### Crypto Position Sizing
Use `renoun_finance_analyze` exposure recommendations to scale position sizes based on structural health. Validated across BTC, ETH, SOL, DOGE, AVAX, LINK, ADA, DOT, and MATIC on 1m/5m/15m/1h/4h timeframes.

## Key Differentiator

ReNoUn measures STRUCTURE, not CONTENT. It has no access to semantic meaning — it operates entirely on formal patterns of recurrence, novelty, and unity. This makes it:
- **Privacy-preserving**: no content leaves the analysis layer
- **Domain-agnostic**: works on therapy sessions, sales calls, agent loops, or financial candles
- **Complementary**: pairs with any content-aware tool since it operates on a different axis entirely

## Pricing

- **Free tier**: 50 API calls/day, all 6 tools
- **Pro tier**: $4.99/mo via Stripe, unlimited calls
