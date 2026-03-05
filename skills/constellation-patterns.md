# Constellation Patterns

Domain expertise for interpreting the 8 structural archetypes detected by ReNoUn.

## When This Applies

When analysis results contain constellation detections, or when a user asks about structural patterns, loops, breakthroughs, convergence, or stuck states.

## The 8 Constellations

**CLOSED_LOOP** — Same patterns cycling without disruption. Re↑↑ No↓↓ Un↑↑.
Agent action: `explore_new_angle`. Try different framing or topic.

**HIGH_SYMMETRY** — Highly structured interaction with minimal variation. Re₄↑ Un₄↑ Un₆↑ No₃↓.
Agent action: `introduce_variation`. Consider open-ended prompts.

**PATTERN_BREAK** — Established pattern suddenly disrupted. Re↓ No₂+No₃↑↑ Un↓→↑.
Agent action: `support_integration`. Help process before moving on. What follows the break matters more than the break itself.

**CONVERGENCE** — Speakers moving toward shared structure. Un₁-₆ rising steadily.
Agent action: `maintain_trajectory`. Productive movement occurring — don't disrupt.

**SCATTERING** — Structure fragmenting, low coherence. Re₁+₂↓↓ No₅↑ Un↓↓.
Agent action: `provide_structure`. Offer grounding, summarize, simplify. HIGH alert if DHS < 0.35.

**REPEATED_DISRUPTION** — Multiple pattern breaks without stabilization. Re↓ No₁+₂ spikes Un↓.
Agent action: `slow_down`. Reduce pace. Different from SCATTERING — this is repeated failed attempts to change.

**DIP_AND_RECOVERY** — Temporary disruption followed by new stability. Re₄↓→↑ No₄ spike Un₄↑.
Agent action: `acknowledge_shift`. Note resilience. Check if recovery established a new pattern or returned to the old one.

**SURFACE_VARIATION** — New words and syntax, unchanged rhythm and dynamics. No₁+₂↑ No₃+₄↓ Un₆↑.
Agent action: `go_deeper`. The conversation sounds different but works the same way.

## Common Sequences

| Sequence | Meaning |
|----------|---------|
| CLOSED_LOOP → PATTERN_BREAK → CONVERGENCE | Healthy disruption-integration cycle |
| CLOSED_LOOP → PATTERN_BREAK → SCATTERING | Disruption without containment |
| PATTERN_BREAK → DIP_AND_RECOVERY | Productive disruption with resilient recovery |
| REPEATED_DISRUPTION → SCATTERING | Escalating structural instability |
| SURFACE_VARIATION → CLOSED_LOOP | Cosmetic change masking persistent loop |

## Compound Signals

- **Stuck:** CLOSED_LOOP > 20 turns + DHS < 0.45 → structurally stuck, recommend change
- **False progress:** SURFACE_VARIATION repeated + no PATTERN_BREAK → things sound different but nothing shifted
- **Resilient:** Multiple DIP_AND_RECOVERY + rising DHS → system handles disruption well
- **Escalating:** PATTERN_BREAK → REPEATED_DISRUPTION → SCATTERING → destabilizing, intervene
