#!/usr/bin/env python3
"""
Export 6h-delayed public dashboard data from signal_history.json.

Reads the full signal history and prediction scores, strips anything
newer than 6 hours, and writes signals_public.json to the landing/ dir.

Designed to run as a cron job every 15-30 minutes, or called from the
main signal bot after each analysis cycle.

Usage:
    python export_public.py                          # Default paths
    python export_public.py --output /path/to/out    # Custom output dir
    python export_public.py --delay 6                # Delay in hours (default: 6)
"""

import argparse
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path


# Defaults
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_DIR = SCRIPT_DIR.parent
DEFAULT_HISTORY = SCRIPT_DIR / "signal_history.json"
DEFAULT_SCORES = SCRIPT_DIR / "prediction_scores.json"
DEFAULT_OUTPUT = REPO_DIR / "landing" / "signals_public.json"
DEFAULT_DELAY_HOURS = 6

# Regime mapping (mirrors CONSTELLATION_PREDICTIONS in the bot)
REGIME_MAP = {
    "CLOSED_LOOP":          "bounded",
    "HIGH_SYMMETRY":        "bounded",
    "CONVERGENCE":          "active",
    "SURFACE_VARIATION":    "bounded",
    "DIP_AND_RECOVERY":     "active",
    "SCATTERING":           "unstable",
    "REPEATED_DISRUPTION":  "unstable",
    "PATTERN_BREAK":        "active",
    "NOMINAL":              "bounded",
}


def load_json(path: Path):
    """Safely load a JSON file."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception as e:
        print(f"  WARNING: Could not parse {path}: {e}")
        return None


def export_public(history_path: Path, scores_path: Path, output_path: Path,
                  delay_hours: int = 6, verbose: bool = True):
    """
    Export 6h-delayed public data for the dashboard.

    Output format (signals_public.json):
    {
        "generated_at": "ISO timestamp",
        "delayed_until": "ISO timestamp (newest data point)",
        "delay_hours": 6,
        "latest": {
            "BTC": { dhs, constellation, exposure_scalar, price, persistence_count, ... },
            "ETH": { ... },
            ...
        },
        "transitions": [
            { timestamp, asset, from, to, dhs },
            ...
        ],
        "scores": {
            "summary": { total_graded, correct, accuracy, by_asset, by_constellation },
            ...
        }
    }
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=delay_hours)

    # Load history
    history = load_json(history_path)
    if not history:
        if verbose:
            print("  No signal history found. Skipping export.")
        return False

    # Filter to signals older than cutoff
    delayed = []
    for entry in history:
        ts_str = entry.get("timestamp", "")
        try:
            ts = datetime.fromisoformat(ts_str)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts <= cutoff:
                delayed.append(entry)
        except (ValueError, TypeError):
            continue

    if not delayed:
        if verbose:
            print(f"  No signals older than {delay_hours}h. Nothing to export.")
        return False

    # Latest signal per asset (from the most recent delayed entry)
    latest_entry = delayed[-1]
    latest_assets = latest_entry.get("assets", {})

    # Build transition timeline from last 48h of delayed data
    cutoff_48h = cutoff - timedelta(hours=48)
    transitions = []
    prev_constellations = {}

    for entry in delayed:
        ts_str = entry.get("timestamp", "")
        try:
            ts = datetime.fromisoformat(ts_str)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            continue

        if ts < cutoff_48h:
            # Still need to track constellations for transition detection
            for asset_name, asset_data in entry.get("assets", {}).items():
                c = asset_data.get("constellation")
                if c:
                    prev_constellations[asset_name] = c
            continue

        for asset_name, asset_data in entry.get("assets", {}).items():
            current = asset_data.get("constellation")
            if not current:
                continue
            prev = prev_constellations.get(asset_name)
            if prev and prev != current:
                transitions.append({
                    "timestamp": ts_str,
                    "asset": asset_name,
                    "from": prev,
                    "to": current,
                    "dhs": asset_data.get("dhs", 0.5),
                })
            prev_constellations[asset_name] = current

    # Most recent first
    transitions.reverse()

    # Load scores (these are not time-gated — accuracy is public)
    scores_data = load_json(scores_path)
    scores_public = None
    if scores_data:
        summary = scores_data.get("summary", {})
        # Include by_constellation for per-regime accuracy on the dashboard
        by_constellation = summary.get("by_constellation", {})
        # Add regime labels if missing
        for name, data in by_constellation.items():
            if "regime" not in data:
                data["regime"] = REGIME_MAP.get(name, "unknown")
        scores_public = {
            "summary": summary,
            "by_constellation": by_constellation,
        }

    # Assemble output
    delayed_until = latest_entry.get("timestamp", cutoff.isoformat())
    output = {
        "generated_at": now.isoformat(),
        "delayed_until": delayed_until,
        "delay_hours": delay_hours,
        "latest": latest_assets,
        "transitions": transitions[:50],  # Cap at 50 transitions
        "scores": scores_public,
    }

    # Write
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, indent=2))

    if verbose:
        n_assets = len(latest_assets)
        n_trans = len(transitions)
        print(f"  Exported: {n_assets} assets, {n_trans} transitions")
        print(f"  Delayed until: {delayed_until}")
        print(f"  Output: {output_path}")

    return True


def main():
    parser = argparse.ArgumentParser(description="Export 6h-delayed public dashboard data")
    parser.add_argument("--history", default=str(DEFAULT_HISTORY),
                        help=f"Path to signal_history.json (default: {DEFAULT_HISTORY})")
    parser.add_argument("--scores", default=str(DEFAULT_SCORES),
                        help=f"Path to prediction_scores.json (default: {DEFAULT_SCORES})")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT),
                        help=f"Output path for signals_public.json (default: {DEFAULT_OUTPUT})")
    parser.add_argument("--delay", type=int, default=DEFAULT_DELAY_HOURS,
                        help=f"Delay in hours (default: {DEFAULT_DELAY_HOURS})")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    success = export_public(
        history_path=Path(args.history),
        scores_path=Path(args.scores),
        output_path=Path(args.output),
        delay_hours=args.delay,
        verbose=not args.quiet,
    )

    # Also export track record data
    try:
        from export_track_record import export_track_record
        tr_output = Path(args.output).parent / "track_record.json"
        export_track_record(
            scores_path=Path(args.scores),
            output_path=tr_output,
            verbose=not args.quiet,
        )
    except Exception as e:
        if not args.quiet:
            print(f"  WARNING: Track record export failed: {e}")

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
