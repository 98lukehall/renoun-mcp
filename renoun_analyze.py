#!/usr/bin/env python3
"""
ReNoUn Analysis Script — Plugin execution layer.

Accepts conversation data in multiple formats, runs the ReNoUn v4.1 engine,
and outputs structured JSON results.

Usage:
    python3 renoun_analyze.py --input transcript.json --format auto
    python3 renoun_analyze.py --input transcript.csv --format csv
    echo "Speaker: text..." | python3 renoun_analyze.py --format text
    python3 renoun_analyze.py --monitor --window 30 --input transcript.json

The engine (core.py) is imported as a black box. This script handles:
- Input format detection and normalization
- Engine invocation
- Output formatting

Patent Pending #63/923,592 — core engine is proprietary.
"""

import sys
import os
import json
import csv
import re
import hashlib
import argparse
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime

TOOL_VERSION = "1.0.0"
ENGINE_VERSION = "4.1"
SCHEMA_VERSION = "1.0"

# ---------------------------------------------------------------------------
# Engine import — resolve core.py from multiple possible locations
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
PLUGIN_DIR = SCRIPT_DIR.parent

# Search order for core.py:
# 1. RENOUN_CORE_PATH env var (explicit override)
# 2. ~/.renoun/config.json core_path field
# 3. Standard filesystem locations (dev fallback)
def _build_core_search_paths() -> list:
    paths = []

    # 1. Environment variable
    env_path = os.environ.get("RENOUN_CORE_PATH")
    if env_path:
        p = Path(env_path)
        paths.append(p if p.is_file() else p / "core.py")

    # 2. Config file
    config_path = Path.home() / ".renoun" / "config.json"
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
            cp = config.get("core_path")
            if cp:
                p = Path(cp)
                paths.append(p if p.is_file() else p / "core.py")
        except (json.JSONDecodeError, OSError):
            pass

    # 3. Standard locations
    paths.extend([
        PLUGIN_DIR / "core.py",
        PLUGIN_DIR.parent / "core.py",
        PLUGIN_DIR.parent / "ReNoUn_podcast_corpus" / "core.py",
        PLUGIN_DIR.parent / "ReNoUn_therapy_analysis" / "core.py",
        PLUGIN_DIR.parent / "renoun-studio" / "core.py",
        Path.home() / ".renoun" / "core.py",
    ])
    return paths


CORE_SEARCH_PATHS = _build_core_search_paths()

def find_core():
    """Locate core.py and add its directory to sys.path."""
    for path in CORE_SEARCH_PATHS:
        if path.exists():
            sys.path.insert(0, str(path.parent))
            return path
    return None

core_path = find_core()
if core_path is None:
    print(json.dumps({
        "error": {"type": "engine_not_found", "message": "core.py not found in any expected location.",
                  "action": "Set RENOUN_CORE_PATH=/path/to/core.py or add core_path to ~/.renoun/config.json"},
        "searched": [str(p) for p in CORE_SEARCH_PATHS]
    }), file=sys.stderr)
    sys.exit(1)

from core import ReNoUnEngineV4

# Also try to import novelty_dual_pass if available (engine handles fallback)
try:
    import novelty_dual_pass
except ImportError:
    pass


# ---------------------------------------------------------------------------
# Input Parsing
# ---------------------------------------------------------------------------

def parse_json_input(data: str) -> List[Dict[str, Any]]:
    """Parse JSON input — array of {speaker, text} objects."""
    parsed = json.loads(data)
    if isinstance(parsed, dict) and "utterances" in parsed:
        parsed = parsed["utterances"]
    if not isinstance(parsed, list):
        raise ValueError("JSON input must be an array of utterance objects")

    utterances = []
    for i, item in enumerate(parsed):
        utt = {
            "index": item.get("index", i),
            "speaker": item.get("speaker", item.get("role", item.get("Speaker", "Unknown"))),
            "text": item.get("text", item.get("content", item.get("Text", ""))),
        }
        if "start" in item:
            utt["start"] = item["start"]
        if "end" in item:
            utt["end"] = item["end"]
        utterances.append(utt)
    return utterances


def parse_csv_input(data: str) -> List[Dict[str, Any]]:
    """Parse CSV input — expects speaker and text columns."""
    reader = csv.DictReader(data.strip().splitlines())

    # Normalize column names
    fieldnames = reader.fieldnames or []
    col_map = {}
    for f in fieldnames:
        fl = f.lower().strip()
        if fl in ("speaker", "role", "name", "participant"):
            col_map["speaker"] = f
        elif fl in ("text", "content", "utterance", "message", "transcript"):
            col_map["text"] = f
        elif fl in ("index", "turn", "turn_number", "id"):
            col_map["index"] = f

    if "speaker" not in col_map or "text" not in col_map:
        raise ValueError(
            f"CSV must have speaker and text columns. Found: {fieldnames}. "
            f"Accepted speaker columns: speaker, role, name, participant. "
            f"Accepted text columns: text, content, utterance, message, transcript."
        )

    utterances = []
    for i, row in enumerate(reader):
        utt = {
            "index": int(row.get(col_map.get("index", ""), i)) if col_map.get("index") else i,
            "speaker": row[col_map["speaker"]].strip(),
            "text": row[col_map["text"]].strip(),
        }
        utterances.append(utt)
    return utterances


def parse_text_input(data: str) -> List[Dict[str, Any]]:
    """
    Parse plain text conversation.
    Supports formats:
        Speaker Name: text
        Speaker Name - text
        [Speaker Name] text
        Speaker Name> text
        SPEAKER NAME: text
    """
    patterns = [
        re.compile(r'^([A-Za-z][A-Za-z0-9_ ]{0,30}):\s+(.+)$'),       # Name: text
        re.compile(r'^([A-Za-z][A-Za-z0-9_ ]{0,30})\s*-\s+(.+)$'),     # Name - text
        re.compile(r'^\[([A-Za-z][A-Za-z0-9_ ]{0,30})\]\s*(.+)$'),     # [Name] text
        re.compile(r'^([A-Za-z][A-Za-z0-9_ ]{0,30})>\s*(.+)$'),        # Name> text
    ]

    utterances = []
    current_speaker = None
    current_text = []

    for line in data.strip().splitlines():
        line = line.strip()
        if not line:
            continue

        matched = False
        for pattern in patterns:
            m = pattern.match(line)
            if m:
                # Save previous utterance
                if current_speaker and current_text:
                    utterances.append({
                        "index": len(utterances),
                        "speaker": current_speaker,
                        "text": " ".join(current_text),
                    })
                current_speaker = m.group(1).strip()
                current_text = [m.group(2).strip()]
                matched = True
                break

        if not matched and current_speaker:
            # Continuation line
            current_text.append(line)

    # Don't forget the last utterance
    if current_speaker and current_text:
        utterances.append({
            "index": len(utterances),
            "speaker": current_speaker,
            "text": " ".join(current_text),
        })

    if not utterances:
        raise ValueError(
            "Could not parse any speaker turns from the text. "
            "Expected format: 'Speaker: text' or 'Speaker - text' or '[Speaker] text'"
        )

    return utterances


def detect_format(data: str) -> str:
    """Auto-detect input format."""
    stripped = data.strip()
    if stripped.startswith("[") or stripped.startswith("{"):
        return "json"
    # Check for CSV header
    first_line = stripped.split("\n")[0]
    if "," in first_line and any(
        col in first_line.lower() for col in ("speaker", "role", "text", "content")
    ):
        return "csv"
    return "text"


def load_input(input_path: Optional[str], fmt: str) -> List[Dict[str, Any]]:
    """Load and parse input from file or stdin."""
    if input_path and input_path != "-":
        path = Path(input_path)
        if not path.exists():
            raise FileNotFoundError(f"Input file not found: {input_path}")
        data = path.read_text(encoding="utf-8")
    else:
        data = sys.stdin.read()

    if not data.strip():
        raise ValueError("Empty input — no data to analyze")

    if fmt == "auto":
        fmt = detect_format(data)

    if fmt == "json":
        return parse_json_input(data)
    elif fmt == "csv":
        return parse_csv_input(data)
    elif fmt == "text":
        return parse_text_input(data)
    else:
        raise ValueError(f"Unknown format: {fmt}")


# ---------------------------------------------------------------------------
# Agent Action Mappings
# ---------------------------------------------------------------------------

AGENT_ACTIONS = {
    "CLOSED_LOOP": {"agent_action": "explore_new_angle", "agent_guidance": "Current approach is cycling. Try different framing or topic."},
    "HIGH_SYMMETRY": {"agent_action": "introduce_variation", "agent_guidance": "Interaction overly structured. Consider open-ended prompts."},
    "PATTERN_BREAK": {"agent_action": "support_integration", "agent_guidance": "A shift happened. Help process before moving on."},
    "CONVERGENCE": {"agent_action": "maintain_trajectory", "agent_guidance": "Productive movement occurring. Do not disrupt."},
    "SCATTERING": {"agent_action": "provide_structure", "agent_guidance": "Coherence low. Offer grounding, summarize, or simplify."},
    "REPEATED_DISRUPTION": {"agent_action": "slow_down", "agent_guidance": "Multiple disruptions without recovery. Reduce pace."},
    "DIP_AND_RECOVERY": {"agent_action": "acknowledge_shift", "agent_guidance": "Disruption processed successfully. Note resilience."},
    "SURFACE_VARIATION": {"agent_action": "go_deeper", "agent_guidance": "New words, same dynamics. Push past surface change."},
}


def inject_agent_actions(output: Dict[str, Any]) -> Dict[str, Any]:
    """Inject agent_action and agent_guidance into every constellation."""
    for constellation in output.get("constellations", []):
        detected = constellation.get("detected", "")
        mapping = AGENT_ACTIONS.get(detected, {})
        constellation["agent_action"] = mapping.get("agent_action", "observe")
        constellation["agent_guidance"] = mapping.get("agent_guidance", "No specific action recommended.")
    return output


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def compute_result_hash(output: Dict[str, Any]) -> str:
    """Deterministic SHA-256 hash of the analysis result for auditing."""
    # Hash only the stable analytical fields, not metadata
    hashable = {
        "dialectical_health": output.get("dialectical_health"),
        "loop_strength": output.get("loop_strength"),
        "channels": output.get("channels"),
    }
    canonical = json.dumps(hashable, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def run_analysis(utterances: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Run the ReNoUn engine and return structured results."""
    engine = ReNoUnEngineV4()
    result = engine.score(utterances)

    output = result.to_dict()

    turn_count = len(utterances)

    # Engine metadata block
    output["engine"] = {
        "version": ENGINE_VERSION,
        "schema_version": SCHEMA_VERSION,
        "tool_version": TOOL_VERSION,
        "analysis_timestamp": datetime.utcnow().isoformat() + "Z",
    }

    # Inject agent actions into constellation output
    inject_agent_actions(output)

    # Result hash for deterministic comparison and auditing
    output["result_hash"] = compute_result_hash(output)

    # Reliability note — always present, agents can branch on this
    if turn_count < 10:
        output["reliability_note"] = (
            f"Low reliability — {turn_count} turns analyzed. "
            "ReNoUn requires 10+ turns for stable channel values and "
            "20+ turns for reliable constellation detection. "
            "Treat these results as indicative, not definitive."
        )
    elif turn_count < 20:
        output["reliability_note"] = (
            f"Moderate reliability — {turn_count} turns analyzed. "
            "Channel values are stable. Constellation detection improves with 20+ turns."
        )
    else:
        output["reliability_note"] = None  # Explicitly null — full reliability

    # Legacy _meta block (preserved for backward compat, enhanced)
    output["_meta"] = {
        "engine_version": ENGINE_VERSION,
        "schema_version": SCHEMA_VERSION,
        "tool_version": TOOL_VERSION,
        "timestamp": output["engine"]["analysis_timestamp"],
        "turn_count": turn_count,
        "speakers": list(set(u.get("speaker", "Unknown") for u in utterances)),
        "min_turns_warning": turn_count < 10,
    }

    return output


def run_monitor(utterances: List[Dict[str, Any]], window_size: int) -> List[Dict[str, Any]]:
    """Run rolling window analysis for monitoring mode."""
    engine = ReNoUnEngineV4()
    results = []

    total = len(utterances)
    if total <= window_size:
        # Single window
        result = engine.score(utterances)
        output = result.to_dict()
        output["_window"] = {"start": 0, "end": total - 1, "size": total}
        results.append(output)
    else:
        # Rolling windows, step by half window
        step = max(1, window_size // 2)
        for start in range(0, total - window_size + 1, step):
            end = start + window_size
            window = utterances[start:end]
            # Re-index
            for i, u in enumerate(window):
                u["index"] = i
            result = engine.score(window)
            output = result.to_dict()
            output["_window"] = {"start": start, "end": end - 1, "size": window_size}
            results.append(output)

    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="ReNoUn Structural Analysis")
    parser.add_argument("--input", "-i", help="Input file path (or - for stdin)", default=None)
    parser.add_argument("--format", "-f", choices=["json", "csv", "text", "auto"], default="auto",
                        help="Input format (default: auto-detect)")
    parser.add_argument("--monitor", action="store_true", help="Rolling window monitoring mode")
    parser.add_argument("--window", type=int, default=30, help="Monitor window size (default: 30)")
    parser.add_argument("--output", "-o", help="Output file path (default: stdout)", default=None)
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")

    args = parser.parse_args()

    try:
        utterances = load_input(args.input, args.format)
    except FileNotFoundError as e:
        print(json.dumps({"error": {"type": "input_not_found", "message": str(e), "action": "Check file path and try again."}}), file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        print(json.dumps({"error": {"type": "parse_error", "message": str(e), "action": "Check input format. Accepted: JSON array, CSV with speaker/text columns, or 'Speaker: text' plain text."}}), file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(json.dumps({"error": {"type": "input_error", "message": str(e), "action": "Verify input data and format."}}), file=sys.stderr)
        sys.exit(1)

    try:
        if args.monitor:
            output = run_monitor(utterances, args.window)
        else:
            output = run_analysis(utterances)
    except Exception as e:
        print(json.dumps({"error": {"type": "engine_error", "message": f"Analysis failed: {str(e)}", "action": "Verify core.py is accessible and numpy is installed."}}), file=sys.stderr)
        sys.exit(1)

    indent = 2 if args.pretty else None
    result_json = json.dumps(output, indent=indent, default=str)

    if args.output:
        Path(args.output).write_text(result_json, encoding="utf-8")
    else:
        print(result_json)


if __name__ == "__main__":
    main()
