<p align="center">
  <h1 align="center">ReNoUn</h1>
  <p align="center"><strong>Structural observability for AI conversations</strong></p>
  <p align="center">
    <a href="https://pypi.org/project/renoun-mcp/"><img src="https://img.shields.io/pypi/v/renoun-mcp?color=7C9A6E&label=PyPI" alt="PyPI"></a>
    <a href="https://pypi.org/project/renoun-mcp/"><img src="https://img.shields.io/pypi/pyversions/renoun-mcp?color=5B7B9E" alt="Python"></a>
    <a href="https://github.com/98lukehall/renoun-mcp/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="License"></a>
    <a href="https://web-production-817e2.up.railway.app/docs"><img src="https://img.shields.io/badge/API-docs-orange" alt="API Docs"></a>
  </p>
</p>

Your agent doesn't know when it's going in circles. **ReNoUn does.**

Detects when conversations are stuck in loops, producing cosmetic variation instead of real change, or failing to converge. Measures structural health across 17 channels without analyzing content — works on any turn-based interaction.

<a href="https://glama.ai/mcp/servers/@98lukehall/renoun-mpc">
  <img width="380" height="200" src="https://glama.ai/mcp/servers/@98lukehall/renoun-mpc/badge" alt="renoun-mpc MCP server" />
</a>

## Why?

LLMs get stuck. They produce responses that *sound* different but are structurally identical — what we call **surface variation**. A human might notice after 5 turns. An agent never will.

ReNoUn catches this in ~200ms by measuring structure, not content. It works on any language, any topic, any model.

## Install

```bash
pip install renoun-mcp
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