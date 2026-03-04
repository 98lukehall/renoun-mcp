# ReNoUn MCP Server — Registry Submission Playbook

Step-by-step instructions for getting ReNoUn listed in every major MCP registry.
Target: zero sales effort, discovery-only distribution.

---

## Pre-Flight Checklist

Before submitting anywhere:

- [ ] GitHub repo created at `github.com/98lukehall/renoun-mcp`
- [ ] `server.py`, `tool_definition.json`, `smithery.yaml`, `pyproject.toml` committed
- [ ] `README.md` is registry-ready (config examples, tool table, constellation table)
- [ ] `tests/test_integration.py` passes (23/23)
- [ ] `core.py` is NOT in the repo (proprietary — referenced by path only)
- [ ] License file added (MIT for wrapper, proprietary note for engine)

---

## Day 0: GitHub + Smithery

### 1. Push to GitHub

```bash
cd renoun-mcp
git init
git add server.py tool_definition.json smithery.yaml pyproject.toml README.md tests/
git commit -m "ReNoUn MCP Server v1.1.0 — structural observability for AI conversations"
git remote add origin git@github.com:98lukehall/renoun-mcp.git
git push -u origin main
```

**Do NOT commit**: `core.py`, `novelty_dual_pass.py`, `__pycache__/`, `.renoun/history/`

Add a `.gitignore`:
```
core.py
novelty_dual_pass.py
__pycache__/
*.pyc
.renoun/
```

### 2. Smithery Submission

The `smithery.yaml` is already in the repo root. Smithery auto-indexes GitHub repos.

To submit manually:
1. Go to https://smithery.ai
2. Click "Add Server" or submit via their GitHub integration
3. Point to `github.com/98lukehall/renoun-mcp`
4. Smithery reads `smithery.yaml` and indexes the server automatically

The `configSchema` exposes one optional field (`corePath`) for users who don't have `core.py` in a standard location.

---

## Day 1: Awesome MCP Servers Lists

### punkpeye/awesome-mcp-servers (Primary — synced to mcpservers.org)

1. Fork `github.com/punkpeye/awesome-mcp-servers`
2. Edit `README.md`, add entry under **Monitoring** category (alphabetical):

```markdown
- [98lukehall/renoun-mcp](https://github.com/98lukehall/renoun-mcp) 🐍 🏠 🍎 🪟 🐧 - Structural observability for AI conversations. Detects loops, stuck states, breakthroughs, and convergence patterns across 17 channels without analyzing content.
```

Emoji key: 🐍 = Python, 🏠 = Local, 🍎🪟🐧 = All OS

3. Submit PR with title: `Add renoun-mcp: structural observability for AI conversations`
4. PR body:
```
Adds ReNoUn MCP Server — structural pattern detection for conversations.

- 4 tools: analyze, health_check, compare, pattern_query
- 17-channel measurement without content analysis
- Agent action mappings (tells agents what to do about detected patterns)
- Patent pending #63/923,592

Repo: https://github.com/98lukehall/renoun-mcp
```

### wong2/awesome-mcp-servers (Secondary)

Same process, different repo. Check their category structure — likely "Analysis" or "Monitoring".

---

## Day 2: MCP.so + PulseMCP

### MCP.so

1. Go to https://mcp.so
2. Click "Submit" in the nav bar (or go to their GitHub issues)
3. Create an issue with:
   - **Server Name**: ReNoUn MCP Server
   - **URL**: `https://github.com/98lukehall/renoun-mcp`
   - **Description**: Structural observability for AI conversations. Detects loops, stuck states, breakthroughs, and convergence patterns across 17 channels without analyzing content. 4 tools with agent action mappings.
   - **Category**: Observability / Analysis
   - **Language**: Python

### PulseMCP

1. Go to https://pulsemcp.com
2. Submit via their form or GitHub integration
3. Same description as above

### Official MCP Registry (registry.modelcontextprotocol.io)

The official registry is designed for programmatic consumption by sub-registries. Check for submission instructions at:
- https://registry.modelcontextprotocol.io
- https://github.com/modelcontextprotocol discussions

---

## Day 3: MCP Market + MCP Server Finder

### MCP Market (mcpmarket.com)

Submit via their directory form. Same description.

### MCP Server Finder (mcpserverfinder.com)

Submit via their form. Same description.

---

## Ongoing: Claude Desktop Testing

After listing, test that the full loop works from Claude Desktop:

1. Add to `claude_desktop_config.json`:
```json
{
    "mcpServers": {
        "renoun": {
            "command": "python3",
            "args": ["/path/to/renoun-mcp/server.py"]
        }
    }
}
```

2. Restart Claude Desktop
3. Ask Claude: "Use renoun to check the health of this conversation"
4. Verify Claude discovers and calls `renoun_health_check`

---

## Registry Description Templates

### One-liner (for badges/listings):
```
Structural observability for AI conversations — loop detection, convergence tracking, 17-channel analysis.
```

### Short (for registry cards):
```
Detects when conversations are stuck in loops, producing cosmetic variation instead of real change, or failing to converge. Measures structural health across 17 channels without analyzing content. Your agent doesn't know when it's going in circles. ReNoUn does.
```

### Technical (for developer directories):
```
MCP server exposing 4 tools: renoun_analyze (full 17-channel structural analysis), renoun_health_check (fast DHS triage), renoun_compare (structural A/B testing), renoun_pattern_query (longitudinal history). Detects 8 constellation patterns with agent action mappings. Content-free — measures structure, not meaning. Patent pending #63/923,592.
```

---

## Tracking

| Registry | URL | Submitted | Listed | Notes |
|----------|-----|-----------|--------|-------|
| Smithery | smithery.ai | [ ] | [ ] | Auto-indexes from smithery.yaml |
| awesome-mcp-servers (punkpeye) | github.com/punkpeye/awesome-mcp-servers | [ ] | [ ] | PR to Monitoring category |
| awesome-mcp-servers (wong2) | github.com/wong2/awesome-mcp-servers | [ ] | [ ] | PR to relevant category |
| MCP.so | mcp.so | [ ] | [ ] | GitHub issue submission |
| PulseMCP | pulsemcp.com | [ ] | [ ] | Form submission |
| Official Registry | registry.modelcontextprotocol.io | [ ] | [ ] | Check submission process |
| MCP Market | mcpmarket.com | [ ] | [ ] | Directory form |
| MCP Server Finder | mcpserverfinder.com | [ ] | [ ] | Directory form |
