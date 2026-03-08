# Smithery Listing — renoun-mcp

## Server Metadata

- **Name**: renoun-mcp
- **Category**: Monitoring / Analytics
- **Tags**: structural-analysis, conversation-analytics, financial-risk, crypto, risk-overlay, loop-detection, agent-observability, pattern-detection

## Short Description

Structural observability for AI conversations and financial risk management. 17-channel pattern detection without content analysis.

## Long Description

ReNoUn (Recurrence, Novelty, Unity) is a patent-pending 17-channel structural analysis engine. It measures conversation and market structure without analyzing semantic content — detecting loops, stuck states, breakthroughs, convergence, and scattering patterns.

6 tools cover two surfaces:

**Conversation Analysis (5 tools)**
- `renoun_analyze` — Full 17-channel structural analysis returning DHS, 8 constellation patterns, breakthrough moments, and actionable recommendations
- `renoun_health_check` — Sub-50ms triage returning one score, one pattern, one summary
- `renoun_compare` — Structural A/B testing between conversation sessions
- `renoun_pattern_query` — Longitudinal pattern history with save/query/trend
- `renoun_steer` — Real-time inference steering with rolling window monitoring and automatic signals

**Financial Risk (1 tool)**
- `renoun_finance_analyze` — OHLCV structural analysis with exposure recommendations, validated 31/31 drawdown reduction across 9 crypto assets and 5 timeframes

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `RENOUN_API_KEY` | Optional | API key for authenticated access (starts with `rn_live_`). Get one at https://harrisoncollab.com. Free tier: 50 calls/day. Pro tier ($4.99/mo): unlimited. |

## Example Prompts

### Conversation Analysis
- "Check if this conversation is stuck in a loop"
- "Analyze the structural health of our discussion"
- "Compare these two conversation sessions"
- "Is this dialogue converging or scattering?"
- "Monitor this live conversation for structural problems"

### Financial Risk
- "Analyze the structural health of BTCUSDT 1h candles"
- "What's the current exposure recommendation for this price data?"
- "Is this market showing signs of structural disorder?"
- "Run a structural risk overlay on these OHLCV candles"

## smithery.yaml Status

The current `smithery.yaml` is functional but does not reflect the finance tool or `renoun_steer`. The description field only mentions conversation analysis. Consider updating:

### Recommended smithery.yaml Updates

```yaml
# Smithery configuration for ReNoUn MCP Server
# https://smithery.ai/docs/config#smitheryyaml

startCommand:
  type: stdio
  configSchema:
    type: object
    required:
      - apiKey
    properties:
      apiKey:
        type: string
        description: "Your ReNoUn API key (starts with rn_live_). Get one at https://harrisoncollab.com"
    description: "Structural observability for AI conversations and financial risk management. 17-channel pattern detection, loop/convergence/scattering detection, real-time steering, and OHLCV risk overlay with validated drawdown reduction."
  commandFunction: |-
    (config) => ({
      command: 'python3',
      args: ['-m', 'server'],
      env: { RENOUN_API_KEY: config.apiKey }
    })
  exampleConfig:
    apiKey: "rn_live_your_key_here"
```

**Changes from current**:
- Updated `description` to include financial risk management, real-time steering, and drawdown reduction
- No structural changes to command or config schema needed
