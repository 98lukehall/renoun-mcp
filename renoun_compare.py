#!/usr/bin/env python3
"""
ReNoUn Comparison Script — Structural diff between two or more analysis results.

Usage:
    python3 renoun_compare.py --results result1.json result2.json
    python3 renoun_compare.py --sessions session_name_1 session_name_2
    python3 renoun_compare.py --results r1.json r2.json r3.json --trend

Patent Pending #63/923,592 — core engine is proprietary.
"""

import sys
import json
import argparse
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime

HISTORY_DIR = Path.home() / ".renoun" / "history"

# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_result(path: str) -> Dict[str, Any]:
    """Load an analysis result JSON file."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Result file not found: {path}")
    return json.loads(p.read_text(encoding="utf-8"))


def load_session(name: str) -> Dict[str, Any]:
    """Load a session from the history store."""
    # Try exact filename match
    for f in HISTORY_DIR.glob("*.json"):
        if f.stem == name or name in f.stem:
            data = json.loads(f.read_text(encoding="utf-8"))
            if "result" in data:
                return data["result"]
            return data

    # Try index lookup
    index_path = HISTORY_DIR / "index.json"
    if index_path.exists():
        index = json.loads(index_path.read_text(encoding="utf-8"))
        for entry in index.get("sessions", []):
            if entry.get("session_name") == name:
                result_path = HISTORY_DIR / entry["filename"]
                if result_path.exists():
                    data = json.loads(result_path.read_text(encoding="utf-8"))
                    if "result" in data:
                        return data["result"]
                    return data

    raise FileNotFoundError(f"Session '{name}' not found in history at {HISTORY_DIR}")


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------

CHANNEL_KEYS = {
    "recurrence": [
        "Re1_lexical", "Re2_syntactic", "Re3_rhythmic",
        "Re4_turn_taking", "Re5_self_interruption", "aggregate"
    ],
    "novelty": [
        "No1_lexical", "No2_syntactic", "No3_rhythmic",
        "No4_turn_taking", "No5_self_interruption", "No6_vocabulary_rarity", "aggregate"
    ],
    "unity": [
        "Un1_lexical", "Un2_syntactic", "Un3_rhythmic",
        "Un4_interactional", "Un5_anaphoric", "Un6_structural_symmetry", "aggregate"
    ],
}

CHANNEL_NAMES = {
    "Re1_lexical": "Re₁ Lexical Recurrence",
    "Re2_syntactic": "Re₂ Syntactic Recurrence",
    "Re3_rhythmic": "Re₃ Rhythmic Recurrence",
    "Re4_turn_taking": "Re₄ Turn-Taking Recurrence",
    "Re5_self_interruption": "Re₅ Self-Interruption Recurrence",
    "No1_lexical": "No₁ Lexical Novelty",
    "No2_syntactic": "No₂ Syntactic Novelty",
    "No3_rhythmic": "No₃ Rhythmic Novelty",
    "No4_turn_taking": "No₄ Turn-Taking Novelty",
    "No5_self_interruption": "No₅ Self-Interruption Novelty",
    "No6_vocabulary_rarity": "No₆ Vocabulary Rarity",
    "Un1_lexical": "Un₁ Lexical Cohesion",
    "Un2_syntactic": "Un₂ Syntactic Cohesion",
    "Un3_rhythmic": "Un₃ Rhythmic Cohesion",
    "Un4_interactional": "Un₄ Interactional Cohesion",
    "Un5_anaphoric": "Un₅ Anaphoric Cohesion",
    "Un6_structural_symmetry": "Un₆ Structural Symmetry",
}


def get_dominant_constellation(result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Get the highest-confidence constellation from a result."""
    constellations = result.get("constellations", [])
    if not constellations:
        return None
    return max(constellations, key=lambda c: c.get("confidence", 0))


def compute_channel_deltas(a: Dict[str, Any], b: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Compute per-channel deltas between two results."""
    deltas = []
    channels_a = a.get("channels", {})
    channels_b = b.get("channels", {})

    for dimension, keys in CHANNEL_KEYS.items():
        dim_a = channels_a.get(dimension, {})
        dim_b = channels_b.get(dimension, {})
        for key in keys:
            if key == "aggregate":
                continue
            val_a = dim_a.get(key, 0.0)
            val_b = dim_b.get(key, 0.0)
            delta = val_b - val_a
            deltas.append({
                "channel": key,
                "name": CHANNEL_NAMES.get(key, key),
                "dimension": dimension,
                "value_a": round(val_a, 3),
                "value_b": round(val_b, 3),
                "delta": round(delta, 3),
                "abs_delta": round(abs(delta), 3),
                "direction": "↑" if delta > 0.02 else ("↓" if delta < -0.02 else "→"),
            })

    # Sort by absolute delta descending
    deltas.sort(key=lambda d: d["abs_delta"], reverse=True)
    return deltas


def compare_pair(a: Dict[str, Any], b: Dict[str, Any],
                 label_a: str = "Session A", label_b: str = "Session B") -> Dict[str, Any]:
    """Full comparison between two analysis results."""
    dhs_a = a.get("dialectical_health", 0.0)
    dhs_b = b.get("dialectical_health", 0.0)
    loop_a = a.get("loop_strength", 0.0)
    loop_b = b.get("loop_strength", 0.0)

    channels_a = a.get("channels", {})
    channels_b = b.get("channels", {})

    re_agg_a = channels_a.get("recurrence", {}).get("aggregate", 0.0)
    re_agg_b = channels_b.get("recurrence", {}).get("aggregate", 0.0)
    no_agg_a = channels_a.get("novelty", {}).get("aggregate", 0.0)
    no_agg_b = channels_b.get("novelty", {}).get("aggregate", 0.0)
    un_agg_a = channels_a.get("unity", {}).get("aggregate", 0.0)
    un_agg_b = channels_b.get("unity", {}).get("aggregate", 0.0)

    const_a = get_dominant_constellation(a)
    const_b = get_dominant_constellation(b)

    channel_deltas = compute_channel_deltas(a, b)

    dhs_delta = dhs_b - dhs_a
    trend = "improving" if dhs_delta > 0.05 else ("declining" if dhs_delta < -0.05 else "stable")

    return {
        "label_a": label_a,
        "label_b": label_b,
        "health": {
            "dhs_a": round(dhs_a, 3),
            "dhs_b": round(dhs_b, 3),
            "dhs_delta": round(dhs_delta, 3),
            "trend": trend,
        },
        "loop": {
            "loop_a": round(loop_a, 3),
            "loop_b": round(loop_b, 3),
            "loop_delta": round(loop_b - loop_a, 3),
        },
        "aggregates": {
            "recurrence": {"a": round(re_agg_a, 3), "b": round(re_agg_b, 3), "delta": round(re_agg_b - re_agg_a, 3)},
            "novelty": {"a": round(no_agg_a, 3), "b": round(no_agg_b, 3), "delta": round(no_agg_b - no_agg_a, 3)},
            "unity": {"a": round(un_agg_a, 3), "b": round(un_agg_b, 3), "delta": round(un_agg_b - un_agg_a, 3)},
        },
        "constellation_transition": {
            "from": const_a["detected"] if const_a else None,
            "from_confidence": round(const_a["confidence"], 3) if const_a else None,
            "to": const_b["detected"] if const_b else None,
            "to_confidence": round(const_b["confidence"], 3) if const_b else None,
        },
        "channel_deltas": channel_deltas,
        "top_shifts": channel_deltas[:5],  # Top 5 biggest shifts
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


def compute_trend(results: List[Dict[str, Any]], labels: List[str]) -> Dict[str, Any]:
    """Compute trend across multiple ordered results."""
    comparisons = []
    for i in range(len(results) - 1):
        comp = compare_pair(results[i], results[i + 1], labels[i], labels[i + 1])
        comparisons.append(comp)

    # Overall trajectory
    dhs_values = [r.get("dialectical_health", 0.0) for r in results]
    loop_values = [r.get("loop_strength", 0.0) for r in results]

    dhs_slope = (dhs_values[-1] - dhs_values[0]) / max(len(dhs_values) - 1, 1)
    loop_slope = (loop_values[-1] - loop_values[0]) / max(len(loop_values) - 1, 1)

    # Constellation frequency
    const_freq: Dict[str, int] = {}
    for r in results:
        for c in r.get("constellations", []):
            name = c.get("detected", "unknown")
            const_freq[name] = const_freq.get(name, 0) + 1

    return {
        "session_count": len(results),
        "labels": labels,
        "dhs_trajectory": {
            "values": [round(v, 3) for v in dhs_values],
            "slope": round(dhs_slope, 4),
            "trend": "improving" if dhs_slope > 0.02 else ("declining" if dhs_slope < -0.02 else "stable"),
            "min": round(min(dhs_values), 3),
            "max": round(max(dhs_values), 3),
        },
        "loop_trajectory": {
            "values": [round(v, 3) for v in loop_values],
            "slope": round(loop_slope, 4),
            "trend": "decreasing" if loop_slope < -0.02 else ("increasing" if loop_slope > 0.02 else "stable"),
        },
        "constellation_frequency": const_freq,
        "pairwise_comparisons": comparisons,
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="ReNoUn Structural Comparison")
    parser.add_argument("--results", "-r", nargs="+", help="Result JSON file paths")
    parser.add_argument("--sessions", "-s", nargs="+", help="Session names from history")
    parser.add_argument("--trend", action="store_true", help="Compute trend across all results")
    parser.add_argument("--output", "-o", help="Output file path (default: stdout)")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON")

    args = parser.parse_args()

    # Load results
    results = []
    labels = []

    try:
        if args.results:
            for path in args.results:
                results.append(load_result(path))
                labels.append(Path(path).stem)
        elif args.sessions:
            for name in args.sessions:
                results.append(load_session(name))
                labels.append(name)
        else:
            print(json.dumps({"error": "Provide --results or --sessions"}), file=sys.stderr)
            sys.exit(1)

        if len(results) < 2:
            print(json.dumps({"error": "Need at least 2 results to compare"}), file=sys.stderr)
            sys.exit(1)

        if args.trend or len(results) > 2:
            output = compute_trend(results, labels)
        else:
            output = compare_pair(results[0], results[1], labels[0], labels[1])

    except Exception as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)

    indent = 2 if args.pretty else None
    result_json = json.dumps(output, indent=indent, default=str)

    if args.output:
        Path(args.output).write_text(result_json, encoding="utf-8")
    else:
        print(result_json)


if __name__ == "__main__":
    main()
