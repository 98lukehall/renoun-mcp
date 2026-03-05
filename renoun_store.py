#!/usr/bin/env python3
"""
ReNoUn Longitudinal Storage Manager.

Manages ~/.renoun/history/ directory for storing, querying, and exporting
analysis results over time.

Usage:
    python3 renoun_store.py save --result result.json --name "session_12" --domain therapy --tags weekly,client_a
    python3 renoun_store.py query --from 2026-01-01 --to 2026-03-01
    python3 renoun_store.py query --constellation CLOSED_LOOP
    python3 renoun_store.py query --dhs-below 0.45
    python3 renoun_store.py query --domain therapy --tag client_a
    python3 renoun_store.py trend --domain therapy --metric dhs
    python3 renoun_store.py export --domain therapy --format csv --output trend.csv
    python3 renoun_store.py list

Patent Pending #63/923,592 — core engine is proprietary.
"""

import sys
import json
import csv as csv_module
import argparse
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime, date

HISTORY_DIR = Path.home() / ".renoun" / "history"
INDEX_FILE = HISTORY_DIR / "index.json"


# ---------------------------------------------------------------------------
# Index Management
# ---------------------------------------------------------------------------

def ensure_history_dir():
    """Create the history directory if it doesn't exist."""
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)


def load_index() -> Dict[str, Any]:
    """Load the session index."""
    if INDEX_FILE.exists():
        return json.loads(INDEX_FILE.read_text(encoding="utf-8"))
    return {"sessions": [], "created": datetime.utcnow().isoformat() + "Z"}


def save_index(index: Dict[str, Any]):
    """Save the session index."""
    index["updated"] = datetime.utcnow().isoformat() + "Z"
    INDEX_FILE.write_text(json.dumps(index, indent=2, default=str), encoding="utf-8")


# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------

def save_result(result_path: str, session_name: str, domain: str = "",
                tags: List[str] = None) -> Dict[str, Any]:
    """Save an analysis result to the history store."""
    ensure_history_dir()

    # Load the result
    result_data = json.loads(Path(result_path).read_text(encoding="utf-8"))

    timestamp = datetime.utcnow()
    filename = f"{timestamp.strftime('%Y-%m-%d')}_{session_name}.json"

    # Build the stored record
    record = {
        "session_name": session_name,
        "timestamp": timestamp.isoformat() + "Z",
        "source": result_path,
        "domain": domain,
        "tags": tags or [],
        "turn_count": result_data.get("_meta", {}).get("turn_count", 0),
        "dhs": result_data.get("dialectical_health", 0.0),
        "loop_strength": result_data.get("loop_strength", 0.0),
        "dominant_constellation": None,
        "result": result_data,
    }

    # Extract dominant constellation
    constellations = result_data.get("constellations", [])
    if constellations:
        dominant = max(constellations, key=lambda c: c.get("confidence", 0))
        record["dominant_constellation"] = dominant.get("detected")

    # Write the record
    record_path = HISTORY_DIR / filename
    record_path.write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")

    # Update index
    index = load_index()
    index["sessions"].append({
        "session_name": session_name,
        "filename": filename,
        "timestamp": record["timestamp"],
        "domain": domain,
        "tags": tags or [],
        "dhs": record["dhs"],
        "loop_strength": record["loop_strength"],
        "dominant_constellation": record["dominant_constellation"],
        "turn_count": record["turn_count"],
    })
    save_index(index)

    return {
        "status": "saved",
        "filename": filename,
        "path": str(record_path),
        "session_name": session_name,
        "dhs": record["dhs"],
    }


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------

def query_sessions(
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    domain: Optional[str] = None,
    tag: Optional[str] = None,
    constellation: Optional[str] = None,
    dhs_below: Optional[float] = None,
    dhs_above: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """Query sessions from the index with optional filters."""
    index = load_index()
    results = index.get("sessions", [])

    if from_date:
        from_dt = datetime.fromisoformat(from_date)
        results = [r for r in results if datetime.fromisoformat(r["timestamp"].rstrip("Z")) >= from_dt]

    if to_date:
        to_dt = datetime.fromisoformat(to_date)
        results = [r for r in results if datetime.fromisoformat(r["timestamp"].rstrip("Z")) <= to_dt]

    if domain:
        results = [r for r in results if r.get("domain", "").lower() == domain.lower()]

    if tag:
        results = [r for r in results if tag in r.get("tags", [])]

    if constellation:
        results = [r for r in results if r.get("dominant_constellation") == constellation.upper()]

    if dhs_below is not None:
        results = [r for r in results if r.get("dhs", 1.0) < dhs_below]

    if dhs_above is not None:
        results = [r for r in results if r.get("dhs", 0.0) > dhs_above]

    # Sort by timestamp
    results.sort(key=lambda r: r.get("timestamp", ""))

    return results


# ---------------------------------------------------------------------------
# Trend
# ---------------------------------------------------------------------------

def compute_trend(
    domain: Optional[str] = None,
    metric: str = "dhs",
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Compute trend data for a metric across sessions."""
    sessions = query_sessions(from_date=from_date, to_date=to_date, domain=domain)

    if not sessions:
        return {"error": "No sessions found matching criteria", "count": 0}

    values = []
    for s in sessions:
        if metric == "dhs":
            values.append(s.get("dhs", 0.0))
        elif metric == "loop":
            values.append(s.get("loop_strength", 0.0))
        else:
            values.append(s.get(metric, 0.0))

    # Slope calculation
    if len(values) >= 2:
        slope = (values[-1] - values[0]) / (len(values) - 1)
    else:
        slope = 0.0

    # Constellation distribution
    const_freq: Dict[str, int] = {}
    for s in sessions:
        c = s.get("dominant_constellation")
        if c:
            const_freq[c] = const_freq.get(c, 0) + 1

    return {
        "metric": metric,
        "domain": domain,
        "session_count": len(sessions),
        "date_range": {
            "from": sessions[0].get("timestamp"),
            "to": sessions[-1].get("timestamp"),
        },
        "values": [round(v, 3) for v in values],
        "labels": [s.get("session_name", "") for s in sessions],
        "min": round(min(values), 3),
        "max": round(max(values), 3),
        "mean": round(sum(values) / len(values), 3),
        "slope": round(slope, 4),
        "trend": "improving" if slope > 0.02 else ("declining" if slope < -0.02 else "stable"),
        "constellation_distribution": const_freq,
        "sessions": [
            {
                "name": s.get("session_name"),
                "date": s.get("timestamp", "")[:10],
                "dhs": s.get("dhs"),
                "loop": s.get("loop_strength"),
                "constellation": s.get("dominant_constellation"),
            }
            for s in sessions
        ],
    }


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def export_data(
    domain: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    fmt: str = "csv",
    output_path: Optional[str] = None,
) -> str:
    """Export session data to CSV or JSON."""
    sessions = query_sessions(from_date=from_date, to_date=to_date, domain=domain)

    if fmt == "json":
        data = json.dumps(sessions, indent=2, default=str)
    elif fmt == "csv":
        if not sessions:
            data = "No sessions found"
        else:
            from io import StringIO
            output = StringIO()
            fields = ["session_name", "timestamp", "domain", "dhs", "loop_strength",
                       "dominant_constellation", "turn_count", "tags"]
            writer = csv_module.DictWriter(output, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            for s in sessions:
                row = dict(s)
                row["tags"] = ";".join(row.get("tags", []))
                writer.writerow(row)
            data = output.getvalue()
    else:
        data = json.dumps(sessions, indent=2, default=str)

    if output_path:
        Path(output_path).write_text(data, encoding="utf-8")
        return f"Exported {len(sessions)} sessions to {output_path}"

    return data


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------

def list_sessions() -> List[Dict[str, Any]]:
    """List all stored sessions (summary view)."""
    index = load_index()
    sessions = index.get("sessions", [])
    return [
        {
            "name": s.get("session_name"),
            "date": s.get("timestamp", "")[:10],
            "domain": s.get("domain", ""),
            "dhs": s.get("dhs"),
            "constellation": s.get("dominant_constellation"),
            "turns": s.get("turn_count"),
        }
        for s in sessions
    ]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="ReNoUn History Store")
    subparsers = parser.add_subparsers(dest="command")

    # Save
    save_parser = subparsers.add_parser("save", help="Save an analysis result")
    save_parser.add_argument("--result", "-r", required=True, help="Result JSON file path")
    save_parser.add_argument("--name", "-n", required=True, help="Session name")
    save_parser.add_argument("--domain", "-d", default="", help="Domain tag (e.g., therapy, podcast)")
    save_parser.add_argument("--tags", "-t", default="", help="Comma-separated tags")

    # Query
    query_parser = subparsers.add_parser("query", help="Query stored sessions")
    query_parser.add_argument("--from", dest="from_date", help="Start date (YYYY-MM-DD)")
    query_parser.add_argument("--to", dest="to_date", help="End date (YYYY-MM-DD)")
    query_parser.add_argument("--domain", "-d", help="Filter by domain")
    query_parser.add_argument("--tag", help="Filter by tag")
    query_parser.add_argument("--constellation", help="Filter by constellation type")
    query_parser.add_argument("--dhs-below", type=float, help="Filter DHS below threshold")
    query_parser.add_argument("--dhs-above", type=float, help="Filter DHS above threshold")

    # Trend
    trend_parser = subparsers.add_parser("trend", help="Compute metric trends")
    trend_parser.add_argument("--domain", "-d", help="Filter by domain")
    trend_parser.add_argument("--metric", "-m", default="dhs", help="Metric to trend (dhs, loop)")
    trend_parser.add_argument("--from", dest="from_date", help="Start date")
    trend_parser.add_argument("--to", dest="to_date", help="End date")

    # Export
    export_parser = subparsers.add_parser("export", help="Export session data")
    export_parser.add_argument("--domain", "-d", help="Filter by domain")
    export_parser.add_argument("--from", dest="from_date", help="Start date")
    export_parser.add_argument("--to", dest="to_date", help="End date")
    export_parser.add_argument("--format", dest="fmt", choices=["csv", "json"], default="csv")
    export_parser.add_argument("--output", "-o", help="Output file path")

    # List
    subparsers.add_parser("list", help="List all stored sessions")

    args = parser.parse_args()

    if args.command == "save":
        tags = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else []
        result = save_result(args.result, args.name, args.domain, tags)
        print(json.dumps(result, indent=2))

    elif args.command == "query":
        results = query_sessions(
            from_date=args.from_date, to_date=args.to_date,
            domain=args.domain, tag=args.tag,
            constellation=args.constellation,
            dhs_below=args.dhs_below, dhs_above=args.dhs_above,
        )
        print(json.dumps(results, indent=2, default=str))

    elif args.command == "trend":
        result = compute_trend(
            domain=args.domain, metric=args.metric,
            from_date=args.from_date, to_date=args.to_date,
        )
        print(json.dumps(result, indent=2, default=str))

    elif args.command == "export":
        output = export_data(
            domain=args.domain,
            from_date=args.from_date, to_date=args.to_date,
            fmt=args.fmt, output_path=args.output,
        )
        print(output)

    elif args.command == "list":
        sessions = list_sessions()
        print(json.dumps(sessions, indent=2, default=str))

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
