# ReNoUn MCP Server — Registry Submission Playbook

Step-by-step instructions for getting ReNoUn listed in every major MCP registry.
All copy-paste ready. Work through in order.

---

## Pre-Flight Checklist

- [x] GitHub repo at `github.com/98lukehall/renoun-mcp`
- [x] PyPI package published: `pip install renoun-mcp` (v1.2.0)
- [x] README is registry-ready (badges, demo output, pricing, API docs)
- [x] `smithery.yaml` updated (API key config, not core.py)
- [x] Railway API live at `https://web-production-817e2.up.railway.app`
- [x] Stripe checkout working for $4.99/mo Pro tier
- [x] `.gitignore` excludes proprietary engine files

---

## 1. Smithery (smithery.ai)

**Status**: [ ] Submitted  [ ] Listed

1. Go to https://smithery.ai
2. Sign in / create account
3. Click "Publish MCP" or "Add Server"
4. Connect GitHub repo: `github.com/98lukehall/renoun-mcp`
5. Smithery reads `smithery.yaml` automatically
6. Fill in metadata:
   - **Name**: ReNoUn
   - **Description**: Structural observability for AI conversations. Detects loops, stuck states, breakthroughs, and convergence patterns across 17 channels without analyzing content.
   - **Category**: Observability / Analysis
   - **Tags**: conversation-analysis, loop-detection, agent-observability, pattern-detection
   - **Environment Variables**: `RENOUN_API_KEY` (required)
   - **Example Prompts**:
     - "Check if this conversation is stuck in a loop"
     - "Analyze the structural health of our discussion"
     - "Compare these two conversation sessions"

---

## 2. punkpeye/awesome-mcp-servers (→ synced to mcpservers.org)

**Status**: [ ] PR Submitted  [ ] Merged

1. Fork `github.com/punkpeye/awesome-mcp-servers`
2. Edit `README.md` — add under **Monitoring** category (alphabetical order):

```markdown
- [renoun-mcp](https://github.com/98lukehall/renoun-mcp) 🐍 - Structural observability for AI conversations. Detects loops, stuck states, breakthroughs, and convergence across 17 channels without analyzing content.
```

3. Submit PR:
   - **Title**: `Add renoun-mcp: structural observability for AI conversations`
   - **Body**:
```
Adds ReNoUn MCP Server — structural pattern detection for conversations.

- 4 tools: analyze, health_check, compare, pattern_query
- 17-channel measurement without content analysis
- 8 constellation patterns with agent action mappings
- Available on PyPI: `pip install renoun-mcp`
- REST API + MCP server

Repo: https://github.com/98lukehall/renoun-mcp
PyPI: https://pypi.org/project/renoun-mcp/
```

---

## 3. wong2/awesome-mcp-servers (→ mcpservers.org)

**Status**: [ ] Submitted  [ ] Listed

**Note**: This repo does NOT accept pull requests. Submit via their website.

1. Go to https://mcpservers.org/submit
2. Submit server details:
   - **URL**: `https://github.com/98lukehall/renoun-mcp`
   - **Description**: Structural observability for AI conversations. Detects loops, stuck states, and convergence patterns across 17 channels without analyzing content.

---

## 4. MCP.so

**Status**: [ ] Submitted  [ ] Listed

1. Go to https://mcp.so/submit
2. Fill in:
   - **Server Name**: ReNoUn MCP Server
   - **URL**: `https://github.com/98lukehall/renoun-mcp`
   - **Description**: Structural observability for AI conversations. Detects loops, stuck states, breakthroughs, and convergence patterns across 17 channels without analyzing content. 4 tools with agent action mappings.
   - **Category**: Observability / Analysis
   - **Language**: Python

---

## 5. PulseMCP (pulsemcp.com)

**Status**: [ ] Submitted  [ ] Listed

PulseMCP indexes 8,600+ servers. It may auto-discover from GitHub/PyPI, but to be safe:

1. Go to https://pulsemcp.com
2. Look for a submit/suggest form
3. Same description as above

---

## 6. Official MCP Registry (registry.modelcontextprotocol.io)

**Status**: [ ] Submitted  [ ] Listed

The official registry. Check current submission process:

1. Visit https://registry.modelcontextprotocol.io
2. Review docs for submission requirements
3. May require npm publish or specific metadata format
4. Check https://github.com/modelcontextprotocol discussions for guidance

---

## 7. MCP Market (mcpmarket.com)

**Status**: [ ] Submitted  [ ] Listed

1. Go to https://mcpmarket.com/submit
2. Submit GitHub repo link: `https://github.com/98lukehall/renoun-mcp`
3. Same description as above

---

## 8. MCP Server Finder (mcpserverfinder.com)

**Status**: [ ] Submitted  [ ] Listed

1. Go to https://mcpserverfinder.com
2. Look for "Submit" in nav
3. Same description as above

---

## Copy-Paste Descriptions

### One-liner:
```
Structural observability for AI conversations — loop detection, convergence tracking, 17-channel analysis.
```

### Short (registry cards):
```
Detects when conversations are stuck in loops, producing cosmetic variation instead of real change, or failing to converge. Measures structural health across 17 channels without analyzing content. Your agent doesn't know when it's going in circles. ReNoUn does.
```

### Technical (developer directories):
```
MCP server exposing 4 tools: renoun_analyze (full 17-channel structural analysis), renoun_health_check (fast DHS triage), renoun_compare (structural A/B testing), renoun_pattern_query (longitudinal history). Detects 8 constellation patterns with agent action mappings. Content-free — measures structure, not meaning. Patent pending #63/923,592.
```

---

## Tracking

| Registry | URL | Submitted | Listed | Notes |
|----------|-----|-----------|--------|-------|
| Smithery | smithery.ai | [ ] | [ ] | smithery.yaml ready |
| awesome-mcp (punkpeye) | github.com/punkpeye/awesome-mcp-servers | [ ] | [ ] | PR to Monitoring |
| awesome-mcp (wong2) | mcpservers.org/submit | [ ] | [ ] | Web form only |
| MCP.so | mcp.so/submit | [ ] | [ ] | Web form |
| PulseMCP | pulsemcp.com | [ ] | [ ] | May auto-index |
| Official Registry | registry.modelcontextprotocol.io | [ ] | [ ] | Check process |
| MCP Market | mcpmarket.com | [ ] | [ ] | Web form |
| MCP Server Finder | mcpserverfinder.com | [ ] | [ ] | Web form |
