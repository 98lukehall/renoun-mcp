# Hacker News — Show HN Post Draft

## Title

Show HN: ReNoUn -- 17-channel structural analysis for conversations and crypto risk (patent pending)

## Post Body

I built a structural analysis engine that measures Recurrence, Novelty, and Unity across 17 channels in any turn-based interaction. It doesn't read content. It measures how conversations move — what repeats, what disrupts, what holds together.

**What it measures:**

The engine tracks 5 recurrence channels (lexical recycling, syntactic repetition, rhythmic consistency, turn-taking predictability, self-correction patterns), 6 novelty channels (new vocabulary, structures, pacing changes, interaction shifts, etc.), and 6 unity channels (cohesion across vocabulary, syntax, rhythm, interaction, reference, and global symmetry).

From these 17 signals, it computes a Dialectical Health Score (DHS, 0-1) and detects 8 constellation patterns: CLOSED_LOOP (stuck recycling), CONVERGENCE (moving toward resolution), SCATTERING (losing coherence), PATTERN_BREAK (structural shift), and 4 others.

**Conversation use case:**

Your AI agent doesn't know when it's going in circles. ReNoUn does. It detects when agents loop, produce cosmetic variation (sounds different but structurally identical), or lose coherence. Each constellation maps to a recommended agent action. There's a real-time steering tool that monitors live conversations and emits signals when structural thresholds are crossed.

**Finance use case:**

The same 17-channel engine applies to OHLCV candle data. It's a structural risk overlay, not a prediction engine. Think structural VIX — it reduces exposure when structural health deteriorates.

Backtest results across 9 crypto assets (BTC, ETH, SOL, DOGE, AVAX, LINK, ADA, DOT, MATIC) and 5 timeframes (1m through 4h):
- 31/31 drawdown reduction (every dataset)
- 21.3pp average DD improvement on black swan events
- 0.1 median Sharpe cost (minimal return sacrifice)

I'm not claiming this predicts prices. It doesn't. It measures structural disorder in price action and reduces exposure during those periods. The drawdown reduction is the primary value.

**Implementation:**

Ships as an MCP server (Model Context Protocol) with 6 tools. Install: `pip install renoun-mcp`. Works with Claude Desktop, Cursor, or any MCP client. Free tier: 50 calls/day. Pro: $4.99/mo.

The core engine is proprietary (patent pending #63/923,592). The MCP wrapper is MIT.

GitHub: https://github.com/98lukehall/renoun-mcp
PyPI: https://pypi.org/project/renoun-mcp/

**Limitations (being honest):**

- Minimum 10 conversation turns for reliable channel values, 20+ for constellation detection
- Finance tool is a risk overlay, not an alpha generator. It reduces drawdowns; it does not pick entries.
- The 0.1 Sharpe cost means you do sacrifice some upside for the drawdown protection.
- Backtest results are in-sample. I'm working on walk-forward validation.
- Patent pending means the structural theory is documented but the legal process is still in progress.

Happy to discuss the structural theory, the channel definitions, or the finance validation methodology.
