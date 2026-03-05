# Pattern History

Domain expertise for longitudinal structural tracking across sessions.

## When This Applies

When a user asks about trends over time, wants to save an analysis result, queries historical patterns, mentions "track," "history," "trend," or "over time."

## Operations

**Save** — After any analysis, offer to save to history using `renoun_pattern_query` with `action: "save"`. Requires a `session_name` and the analysis `result`. Optionally tag with `domain` and `tags`.

**List** — Show all stored sessions using `action: "list"`.

**Query** — Filter stored sessions by date range, domain, tag, constellation type, or DHS thresholds using `action: "query"`.

**Trend** — Compute metric trajectory over time using `action: "trend"`. Tracks DHS or loop strength across filtered sessions.

## Presentation

DHS trend summaries should include: session count, DHS range, trajectory direction, and a table of sessions with date, name, DHS, dominant pattern, and loop strength.

Constellation distribution shows frequency of each pattern across sessions as a ranked list.

## Storage

All history is stored locally at `~/.renoun/history/` as individual JSON files. Plain JSON format — portable, user-owned, never transmitted externally.

## Workflow Integration

After presenting analysis results, offer:
- "Want me to save this for longitudinal tracking?"
- Pre-fill domain tag if detectable from context
- After saving, mention that trends become available as more sessions accumulate
