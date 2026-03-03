# ReNoUn MCP Server

Structural observability for AI conversations. Detects when conversations are stuck in loops, producing cosmetic variation instead of real change, or failing to converge. Measures structural health across 17 channels without analyzing content — works on any turn-based interaction.

**Your agent doesn't know when it's going in circles. ReNoUn does.**

## Tools

| Tool | Purpose | Speed |
|------|---------|-------|
| `renoun_analyze` | Full 17-channel structural analysis with breakthrough detection | ~200ms |
| `renoun_health_check` | Quick triage — one score, one pattern, one action | ~50ms |
| `renoun_compare` | Structural A/B test between two conversations | ~400ms |
| `renoun_pattern_query` | Save, query, and trend longitudinal session history | ~10ms |

## Quick Start

```bash
# Install dependencies
pip install numpy

# Optional: enables full MCP protocol (falls back to JSON-RPC stdio without it)
pip install mcp

# Place core.py in one of these locations:
#   1. Same directory as server.py
#   2. Parent directory
#   3. ~/.renoun/core.py
#   4. Set RENOUN_CORE_PATH=/path/to/core.py

# Run
python3 server.py
```

## Integration

### Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
    "mcpServers": {
        "renoun": {
            "command": "python3",
            "args": ["/absolute/path/to/renoun-mcp/server.py"]
        }
    }
}
```

### Claude Code

```bash
claude mcp add renoun python3 /absolute/path/to/renoun-mcp/server.py
```

### Generic MCP Client

```json
{
    "transport": "stdio",
    "command": "python3",
    "args": ["server.py"],
    "cwd": "/absolute/path/to/renoun-mcp/"
}
```

### Environment Variable Configuration

```bash
# Point to core engine if not co-located
export RENOUN_CORE_PATH=/path/to/core.py

# Or use config file: ~/.renoun/config.json
# { "core_path": "/path/to/core.py" }
```

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

## What You Get Back

### Health Score (DHS)
A 0.0–1.0 structural health metric. Below 0.45 = stuck or fragmenting. 0.55–0.75 = healthy movement. Above 0.75 = strong convergence.

### 8 Constellation Patterns
Each detected pattern includes an `agent_action` telling your agent what to do:

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

### 17 Channels
Five recurrence channels (stability), six novelty channels (disruption), six unity channels (coherence). Full breakdown available in `references/CHANNELS.md`.

## Longitudinal Storage

Results persist to `~/.renoun/history/`. Use `renoun_pattern_query` to:
- **save**: Store an analysis result with domain/tags
- **list**: See all stored sessions
- **query**: Filter by date, domain, constellation, DHS threshold
- **trend**: Compute health trajectory over time

## Version

- Server: 1.1.0
- Engine: 4.1
- Schema: 1.1
- Protocol: MCP 2024-11-05 (or JSON-RPC stdio fallback)

## Related

The **[ReNoUn Cowork Plugin](../renoun-plugin/)** provides skill files, slash commands, and reference documentation for agents using the Cowork plugin system. The MCP server and plugin share the same engine and can be used independently or together.

## Patent Notice

The core computation engine is proprietary and patent-pending (#63/923,592). This MCP server wraps it as a black box. Agents call `engine.score()` and receive structured results — they never access internal algorithms.

## License

Plugin wrapper and MCP server: MIT. Core engine: Proprietary.
