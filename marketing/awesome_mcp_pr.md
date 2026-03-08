# awesome-mcp-servers PR Content

## PR Title

Add renoun-mcp: structural observability for AI conversations + financial risk overlay

## README.md Addition (Monitoring section, alphabetical)

```markdown
- [renoun-mcp](https://github.com/98lukehall/renoun-mcp) 🐍 - Structural observability for AI conversations and financial risk management. 17-channel pattern detection, loop/convergence/scattering detection, and OHLCV risk overlay with 31/31 validated drawdown reduction.
```

## PR Description

```markdown
Adds ReNoUn MCP Server — structural pattern detection for conversations and financial markets.

ReNoUn (Recurrence, Novelty, Unity) is a patent-pending 17-channel structural analysis engine.
It measures conversation and market structure without analyzing semantic content.

**Conversation tools (5):**
- `renoun_analyze` — full 17-channel structural analysis with 8 constellation patterns
- `renoun_health_check` — fast structural triage (sub-50ms), returns DHS + dominant pattern
- `renoun_compare` — structural A/B testing between two sessions
- `renoun_pattern_query` — longitudinal pattern history (save/query/trend)
- `renoun_steer` — real-time inference steering with rolling window monitoring

**Finance tool (1):**
- `renoun_finance_analyze` — OHLCV structural analysis with exposure recommendations

Key stats:
- 31/31 drawdown reduction across 9 crypto assets, 5 timeframes
- 21.3pp average DD improvement on black swan events
- 0.1 median Sharpe cost
- 8 constellation patterns (CONVERGENCE, SCATTERING, PATTERN_BREAK, CLOSED_LOOP, etc.)
- Real-time monitoring via `renoun_steer`
- Stripe-billed Pro tier at $4.99/mo
- Patent Pending #63/923,592

Repo: https://github.com/98lukehall/renoun-mcp
PyPI: https://pypi.org/project/renoun-mcp/
```

## Submission Checklist

- [ ] Fork `github.com/punkpeye/awesome-mcp-servers`
- [ ] Add entry under **Monitoring** section in alphabetical order
- [ ] Submit PR with title and description above
- [ ] Respond to any reviewer feedback
