# Product Hunt Launch Draft — ReNoUn

## Tagline (under 60 chars)

Structural pattern detection for conversations & crypto risk

## Short Description

ReNoUn is a 17-channel structural analysis engine that measures Recurrence, Novelty, and Unity in conversations and financial data — without reading content. It tells you when your AI agent is going in circles, and when to reduce crypto exposure.

## Long Description

Your AI agent doesn't know when it's going in circles. ReNoUn does.

ReNoUn applies a 17-channel structural analysis engine to any turn-based interaction. It measures three dimensions — Recurrence (what repeats), Novelty (what disrupts), and Unity (what holds together) — across lexical, syntactic, rhythmic, turn-taking, and self-interruption channels. The result is a Dialectical Health Score (DHS) and one of 8 constellation patterns that describe what's happening structurally: CLOSED_LOOP, CONVERGENCE, SCATTERING, PATTERN_BREAK, and others.

The same engine applies to financial markets. Feed it OHLCV candles and it returns structural health scores and exposure recommendations. It's not a price prediction model. It's a structural risk overlay — think "structural VIX for crypto." In backtesting, it reduced drawdowns on 31 out of 31 datasets across 9 crypto assets and 5 timeframes, with a 21.3 percentage point average improvement on black swan events and only 0.1 median Sharpe cost.

ReNoUn ships as an MCP server with 6 tools: full analysis, fast triage, A/B comparison, longitudinal tracking, real-time steering, and financial risk analysis. Install with pip, connect to Claude Desktop or any MCP client, and start measuring structure. Free tier: 50 calls/day. Pro: $4.99/mo. Patent Pending #63/923,592.

## Key Features

- 17-channel structural analysis engine (5 Recurrence, 6 Novelty, 6 Unity channels)
- 8 constellation patterns with agent action mappings (CLOSED_LOOP, CONVERGENCE, SCATTERING, PATTERN_BREAK, etc.)
- Sub-50ms health check for real-time triage
- Real-time inference steering with automatic signals when structural thresholds are crossed
- Structural A/B testing between conversation sessions
- Longitudinal pattern tracking with save/query/trend
- Financial OHLCV analysis with exposure recommendations
- 31/31 drawdown reduction across 9 crypto assets, 5 timeframes
- 21.3pp average drawdown improvement on black swan events
- 0.1 median Sharpe cost (minimal return sacrifice)
- Privacy-preserving: measures structure, not content
- Domain-agnostic: therapy, sales, support, agent monitoring, financial markets
- MCP-native: works with Claude Desktop, Cursor, and any MCP client
- Free tier (50 calls/day) + Pro tier ($4.99/mo via Stripe)

## Maker Comment Draft

I built ReNoUn because I kept watching AI agents go in circles and nobody could tell until it was too late. The agent would rephrase the same idea three different ways, the user would keep pushing, and both sides would insist they were making progress. They weren't. The structure was looping.

So I built a measurement system. Not for what conversations say — for how they move. 17 channels measuring recurrence, novelty, and unity. It turned out the same engine worked on financial data too. When price action loses structural coherence, drawdowns follow. The math doesn't care whether it's reading a therapy transcript or a BTC candlestick chart.

The finance results surprised me: 31 out of 31 datasets showed drawdown reduction. Not cherry-picked — every combination of 9 assets and 5 timeframes. The structural VIX metaphor isn't marketing. It's what the data showed.

This is patent-pending, the core engine is proprietary, and the MCP wrapper is MIT. Happy to answer questions about the structural theory, the channel definitions, or the finance validation.

## First Comment Draft (Technical Details)

Technical details for the curious:

**The 17 channels:**
- Recurrence (Re1-Re5): lexical recycling, syntactic repetition, rhythmic consistency, turn-taking predictability, self-correction patterns
- Novelty (No1-No6): lexical novelty, syntactic novelty, pacing changes, interaction shifts, new correction patterns, global vocabulary rarity
- Unity (Un1-Un6): lexical cohesion, syntactic cohesion, rhythmic cohesion, interactional cohesion, anaphoric cohesion, global structural symmetry

**The 8 constellations:**
Each is a specific Re/No/Un channel signature. CLOSED_LOOP = Re up, No down, Un up (recycling without disruption). SCATTERING = Re down, No up, Un down (disrupting without holding together). CONVERGENCE = all Un channels rising (moving toward resolution). And 5 others.

**Finance validation:**
- 9 assets: BTC, ETH, SOL, DOGE, AVAX, LINK, ADA, DOT, MATIC
- 5 timeframes: 1m, 5m, 15m, 1h, 4h
- 31/31 drawdown reduction (100%)
- 21.3pp avg DD improvement on black swan events
- 0.1 median Sharpe cost
- NOT a prediction engine. It scales exposure down when structural health deteriorates.

**Stack:** Python, numpy, MCP protocol. Core engine is proprietary (not in the repo). MCP wrapper is MIT. Hosted on Railway, billing via Stripe.

Repo: https://github.com/98lukehall/renoun-mcp
Patent Pending #63/923,592
