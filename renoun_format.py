#!/usr/bin/env python3
"""
ReNoUn Output Formatting Utilities.

Converts raw engine JSON output to human-readable formats:
- Markdown report
- Summary-only mode
- Compact one-liner

Usage:
    python3 renoun_format.py --input result.json --mode report
    python3 renoun_format.py --input result.json --mode summary
    python3 renoun_format.py --input result.json --mode compact
    cat result.json | python3 renoun_format.py --mode report

Patent Pending #63/923,592 — core engine is proprietary.
"""

import sys
import json
import argparse
from pathlib import Path
from typing import Dict, Any, List, Optional


# ---------------------------------------------------------------------------
# DHS Assessment
# ---------------------------------------------------------------------------

def dhs_assessment(dhs: float) -> str:
    if dhs >= 0.75:
        return "Structurally excellent"
    elif dhs >= 0.55:
        return "Healthy"
    elif dhs >= 0.35:
        return "Below baseline"
    else:
        return "Structurally distressed"


def dhs_emoji(dhs: float) -> str:
    if dhs >= 0.75:
        return "+++"
    elif dhs >= 0.55:
        return "+"
    elif dhs >= 0.35:
        return "-"
    else:
        return "---"


def loop_reading(loop: float) -> str:
    if loop >= 0.7:
        return "High (heavily recycling)"
    elif loop >= 0.4:
        return "Moderate"
    elif loop >= 0.2:
        return "Low (dynamic)"
    else:
        return "Minimal"


# ---------------------------------------------------------------------------
# Compact (one-liner)
# ---------------------------------------------------------------------------

def format_compact(result: Dict[str, Any]) -> str:
    dhs = result.get("dialectical_health", 0.0)
    loop = result.get("loop_strength", 0.0)
    constellations = result.get("constellations", [])
    dominant = max(constellations, key=lambda c: c.get("confidence", 0)) if constellations else None

    pattern_str = dominant["detected"] if dominant else "NONE"
    meta = result.get("_meta", {})
    turns = meta.get("turn_count", "?")

    return (
        f"DHS: {dhs:.2f} ({dhs_assessment(dhs)}) | "
        f"Pattern: {pattern_str} | "
        f"Loop: {loop:.2f} ({loop_reading(loop)}) | "
        f"Turns: {turns}"
    )


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def format_summary(result: Dict[str, Any]) -> str:
    dhs = result.get("dialectical_health", 0.0)
    loop = result.get("loop_strength", 0.0)
    constellations = result.get("constellations", [])
    summary_text = result.get("summary", "")
    meta = result.get("_meta", {})
    turns = meta.get("turn_count", "?")

    dominant = max(constellations, key=lambda c: c.get("confidence", 0)) if constellations else None

    lines = []
    lines.append(f"DHS: {dhs:.2f} / 1.0 ({dhs_assessment(dhs)})")
    if dominant:
        lines.append(f"Pattern: {dominant['detected']} — {dominant.get('plain_description', '')}")
        lines.append(f"  Confidence: {dominant.get('confidence', 0):.2f}")
    lines.append(f"Loop Strength: {loop:.2f} ({loop_reading(loop)})")
    lines.append(f"Turns Analyzed: {turns}")

    if summary_text:
        lines.append("")
        lines.append(summary_text)

    min_warning = meta.get("min_turns_warning", False)
    if min_warning:
        lines.append("")
        lines.append(
            f"Note: Analysis based on {turns} turns. ReNoUn produces more reliable "
            "results with 20+ turns. Treat these values as indicative."
        )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Full Report (Markdown)
# ---------------------------------------------------------------------------

def format_report(result: Dict[str, Any]) -> str:
    dhs = result.get("dialectical_health", 0.0)
    loop = result.get("loop_strength", 0.0)
    channels = result.get("channels", {})
    constellations = result.get("constellations", [])
    summary_text = result.get("summary", "")
    recommendations = result.get("recommendations", [])
    novelty_items = result.get("novelty_items", [])
    meta = result.get("_meta", {})
    turns = meta.get("turn_count", "?")
    speakers = meta.get("speakers", [])

    lines = []
    lines.append("## ReNoUn Structural Analysis Report")
    lines.append("")
    lines.append(f"**Dialectical Health Score:** {dhs:.3f} / 1.0 ({dhs_assessment(dhs)})")
    lines.append(f"**Loop Strength:** {loop:.3f} ({loop_reading(loop)})")
    lines.append(f"**Turns Analyzed:** {turns}")
    if speakers:
        lines.append(f"**Speakers:** {', '.join(speakers)}")
    lines.append(f"**Timestamp:** {meta.get('timestamp', 'N/A')}")

    # Constellation Patterns
    if constellations:
        lines.append("")
        lines.append("### Constellation Patterns Detected")
        sorted_const = sorted(constellations, key=lambda c: c.get("confidence", 0), reverse=True)
        for i, c in enumerate(sorted_const, 1):
            lines.append(
                f"{i}. **{c['detected']}** (confidence: {c.get('confidence', 0):.2f}) — "
                f"{c.get('plain_description', '')}"
            )
            lines.append(f"   Channel legend: `{c.get('channel_legend', '')}`")
            interps = c.get("possible_interpretations", [])
            if interps:
                for interp in interps:
                    lines.append(f"   - {interp}")

    # Dimension Aggregates
    lines.append("")
    lines.append("### Dimension Aggregates")
    lines.append("")
    lines.append("| Dimension | Aggregate | Reading |")
    lines.append("|-----------|-----------|---------|")

    re_agg = channels.get("recurrence", {}).get("aggregate", 0.0)
    no_agg = channels.get("novelty", {}).get("aggregate", 0.0)
    un_agg = channels.get("unity", {}).get("aggregate", 0.0)

    lines.append(f"| Recurrence | {re_agg:.3f} | {loop_reading(re_agg)} |")
    lines.append(f"| Novelty | {no_agg:.3f} | {'High' if no_agg > 0.5 else 'Moderate' if no_agg > 0.25 else 'Low'} |")
    lines.append(f"| Unity | {un_agg:.3f} | {'Strong' if un_agg > 0.6 else 'Moderate' if un_agg > 0.35 else 'Weak'} |")

    # Full Channel Breakdown
    lines.append("")
    lines.append("### Full 17-Channel Breakdown")

    for dimension in ["recurrence", "novelty", "unity"]:
        dim_data = channels.get(dimension, {})
        lines.append("")
        lines.append(f"**{dimension.title()}:**")
        lines.append("")
        lines.append("| Channel | Value |")
        lines.append("|---------|-------|")
        for key, value in dim_data.items():
            if key == "aggregate":
                continue
            lines.append(f"| {key} | {value:.3f} |")
        lines.append(f"| **Aggregate** | **{dim_data.get('aggregate', 0.0):.3f}** |")

    # Novelty Peaks
    if novelty_items:
        lines.append("")
        lines.append("### Key Novelty Peaks")
        display_items = novelty_items[:5] if isinstance(novelty_items, list) else []
        for item in display_items:
            if isinstance(item, dict):
                idx = item.get("index", "?")
                speaker = item.get("speaker", "?")
                text_preview = item.get("text", "")[:80]
                score = item.get("total_score", item.get("score", 0))
                lines.append(f"- **Turn {idx}** ({speaker}): score {score:.2f} — \"{text_preview}...\"")

    # Summary
    if summary_text:
        lines.append("")
        lines.append("### Summary")
        lines.append(summary_text)

    # Recommendations
    if recommendations:
        lines.append("")
        lines.append("### Structural Observations")
        for rec in recommendations:
            lines.append(f"- {rec}")

    # Min turns warning
    if meta.get("min_turns_warning"):
        lines.append("")
        lines.append(
            f"> **Note:** This analysis is based on {turns} turns. ReNoUn produces "
            "more reliable results with 20+ turns. Channel values should be treated as indicative."
        )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Comparison Report
# ---------------------------------------------------------------------------

def format_comparison(comparison: Dict[str, Any]) -> str:
    lines = []
    label_a = comparison.get("label_a", "Session A")
    label_b = comparison.get("label_b", "Session B")

    lines.append(f"## Structural Comparison: {label_a} → {label_b}")

    health = comparison.get("health", {})
    loop = comparison.get("loop", {})
    aggs = comparison.get("aggregates", {})

    lines.append("")
    lines.append("### Health Trajectory")
    lines.append("")
    lines.append(f"| Metric | {label_a} | {label_b} | Delta | Trend |")
    lines.append("|--------|-----------|-----------|-------|-------|")

    dhs_dir = "↑" if health.get("dhs_delta", 0) > 0 else ("↓" if health.get("dhs_delta", 0) < 0 else "→")
    lines.append(
        f"| DHS | {health.get('dhs_a', 0):.3f} | {health.get('dhs_b', 0):.3f} | "
        f"{health.get('dhs_delta', 0):+.3f} | {dhs_dir} {health.get('trend', '')} |"
    )

    loop_dir = "↑" if loop.get("loop_delta", 0) > 0 else ("↓" if loop.get("loop_delta", 0) < 0 else "→")
    lines.append(
        f"| Loop | {loop.get('loop_a', 0):.3f} | {loop.get('loop_b', 0):.3f} | "
        f"{loop.get('loop_delta', 0):+.3f} | {loop_dir} |"
    )

    for dim in ["recurrence", "novelty", "unity"]:
        d = aggs.get(dim, {})
        delta = d.get("delta", 0)
        direction = "↑" if delta > 0.02 else ("↓" if delta < -0.02 else "→")
        lines.append(
            f"| {dim.title()} Agg | {d.get('a', 0):.3f} | {d.get('b', 0):.3f} | "
            f"{delta:+.3f} | {direction} |"
        )

    # Constellation transition
    ct = comparison.get("constellation_transition", {})
    if ct.get("from") or ct.get("to"):
        lines.append("")
        lines.append("### Constellation Transition")
        lines.append(f"- **{label_a}:** {ct.get('from', 'None')} (conf: {ct.get('from_confidence', 0):.2f})")
        lines.append(f"- **{label_b}:** {ct.get('to', 'None')} (conf: {ct.get('to_confidence', 0):.2f})")

    # Top channel shifts
    top_shifts = comparison.get("top_shifts", [])
    if top_shifts:
        lines.append("")
        lines.append("### Biggest Channel Shifts")
        for shift in top_shifts:
            lines.append(
                f"- **{shift['name']}:** {shift['value_a']:.3f} → {shift['value_b']:.3f} "
                f"({shift['delta']:+.3f}) {shift['direction']}"
            )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="ReNoUn Output Formatter")
    parser.add_argument("--input", "-i", help="Input JSON file (or stdin)")
    parser.add_argument("--mode", "-m", choices=["report", "summary", "compact", "comparison"],
                        default="report", help="Output mode")
    parser.add_argument("--output", "-o", help="Output file path")

    args = parser.parse_args()

    if args.input:
        data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    else:
        data = json.loads(sys.stdin.read())

    if args.mode == "compact":
        output = format_compact(data)
    elif args.mode == "summary":
        output = format_summary(data)
    elif args.mode == "comparison":
        output = format_comparison(data)
    else:
        output = format_report(data)

    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
    else:
        print(output)


if __name__ == "__main__":
    main()
