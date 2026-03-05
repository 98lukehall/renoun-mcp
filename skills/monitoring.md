# Conversation Monitoring

Domain expertise for rolling real-time structural monitoring of conversations.

## When This Applies

When a user wants to monitor an ongoing conversation, track structural patterns as they unfold, watch for loops or breakthroughs in real time, or detect structural shifts as they happen.

## How Monitoring Works

Monitoring uses a rolling window approach:
1. Maintain a buffer of the last N turns (default: 30)
2. On each new batch of turns, run `renoun_analyze` on the current window
3. Compare to previous window via `renoun_compare`
4. Alert on structural transitions

## Alert Conditions

| Condition | Level | Message |
|-----------|-------|---------|
| DHS drops > 0.15 in one window | HIGH | Structural health dropping |
| SCATTERING detected (new) | HIGH | Structural coherence collapsing |
| CLOSED_LOOP persists > 2 windows | MEDIUM | Same patterns recycling for N turns |
| Any channel spikes > 0.8 | MEDIUM | Channel spike detected |
| Re₁ > 0.85 for > 15 turns | MEDIUM | Heavy vocabulary recycling |
| PATTERN_BREAK detected (new) | INFO | Structural shift detected |
| CONVERGENCE detected (new) | INFO | Integration occurring |
| DIP_AND_RECOVERY detected | INFO | Healthy dip-recovery cycle |

## Output Format

Each monitoring cycle produces a compact status line:
```
[Window 31-60] DHS: 0.68 (+0.05) | Pattern: DIP_AND_RECOVERY | Loop: 0.39
```

When alerts trigger:
```
[Window 45-75] DHS: 0.41 (-0.18) | Pattern: SCATTERING | Loop: 0.22
  ALERT: Structural coherence collapsing. Un aggregate dropped from 0.58 to 0.29.
```

## Configuration

- Window size: 30 turns (default), configurable
- Alert threshold: info/medium/high
- Above 200 turns: always use windowed monitoring rather than single-pass analysis
