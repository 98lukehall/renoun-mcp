#!/usr/bin/env python3
"""
ReNoUn Drip Email Scheduler.

Tracks when API keys were provisioned and manages a 3-email onboarding
drip sequence:

  Email 1: Immediately on provision  — "Your ReNoUn API Key"
  Email 2: ~48 hours after provision — "Wire ReNoUn into your stack"
  Email 3: ~120 hours (5 days) after — "Your first week with ReNoUn"

State is persisted to $RENOUN_DATA_DIR/drip_state.json so that pending
drips survive server restarts.

Usage:
    # Called from the provision endpoint (api.py):
    from drip_scheduler import register_provision, check_and_send_drips

    # On provision:
    register_provision(email, api_key, key_id)  # sends email 1 immediately

    # Periodically (e.g., every 15 minutes via cron or background thread):
    check_and_send_drips()
"""

import json
import os
import time
import threading
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

from email_sender import send_drip_email_1, send_drip_email_2, send_drip_email_3


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_DATA_DIR = os.environ.get("RENOUN_DATA_DIR", str(Path.home() / ".renoun"))
DRIP_STATE_FILE = Path(_DATA_DIR) / "drip_state.json"

# Drip timing (in seconds)
DRIP_2_DELAY = 48 * 3600    # 48 hours
DRIP_3_DELAY = 120 * 3600   # 120 hours (5 days)

_lock = threading.Lock()


# ---------------------------------------------------------------------------
# State Management
# ---------------------------------------------------------------------------

def _ensure_state_file():
    """Ensure the drip state directory and file exist."""
    DRIP_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not DRIP_STATE_FILE.exists():
        DRIP_STATE_FILE.write_text(json.dumps({"entries": []}, indent=2))


def _load_state() -> dict:
    """Load drip state from disk."""
    _ensure_state_file()
    try:
        return json.loads(DRIP_STATE_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {"entries": []}


def _save_state(state: dict):
    """Save drip state to disk."""
    _ensure_state_file()
    DRIP_STATE_FILE.write_text(json.dumps(state, indent=2))


def _find_entry(state: dict, email: str, key_id: str) -> Optional[dict]:
    """Find a drip entry by email and key_id."""
    for entry in state["entries"]:
        if entry["email"] == email and entry["key_id"] == key_id:
            return entry
    return None


# ---------------------------------------------------------------------------
# Usage Counting
# ---------------------------------------------------------------------------

def _count_calls_for_key(key_id: str) -> int:
    """Count total API calls for a key from the usage log.

    Reads the JSONL usage log and counts entries matching the key_id.
    Excludes the provision call itself.
    """
    usage_log = Path(_DATA_DIR) / "usage.log"
    if not usage_log.exists():
        return 0

    count = 0
    try:
        with open(usage_log, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if entry.get("key_id") == key_id and entry.get("endpoint") != "/v1/keys/provision":
                        count += 1
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass

    return count


# ---------------------------------------------------------------------------
# Registration (called on provision)
# ---------------------------------------------------------------------------

def register_provision(email: str, api_key: str, key_id: str) -> dict:
    """Register a new key provision and immediately send drip email 1.

    Args:
        email: The key owner's email address.
        api_key: The raw API key string (for inclusion in emails).
        key_id: The key_id (hash) for usage tracking.

    Returns:
        dict with registration status and email 1 result.
    """
    now = time.time()

    with _lock:
        state = _load_state()

        # Check if already registered (idempotent)
        existing = _find_entry(state, email, key_id)
        if existing:
            return {
                "status": "already_registered",
                "provisioned_at": existing["provisioned_at"],
                "drips_sent": existing["drips_sent"],
            }

        # Create new entry
        entry = {
            "email": email,
            "key_id": key_id,
            "api_key": api_key,
            "provisioned_at": now,
            "provisioned_at_iso": datetime.fromtimestamp(now, tz=timezone.utc).isoformat(),
            "drips_sent": [],
            "completed": False,
        }

        state["entries"].append(entry)
        _save_state(state)

    # Send drip email 1 immediately (outside lock to avoid blocking)
    result = _send_drip_1(entry)

    return {
        "status": "registered",
        "provisioned_at": now,
        "drip_1_result": result,
    }


# ---------------------------------------------------------------------------
# Individual Drip Senders
# ---------------------------------------------------------------------------

def _send_drip_1(entry: dict) -> dict:
    """Send drip email 1 and mark it in state."""
    try:
        result = send_drip_email_1(email=entry["email"], api_key=entry["api_key"])
    except Exception as e:
        result = {"success": False, "error": str(e)}

    with _lock:
        state = _load_state()
        stored = _find_entry(state, entry["email"], entry["key_id"])
        if stored and 1 not in stored["drips_sent"]:
            stored["drips_sent"].append(1)
            stored["drip_1_sent_at"] = time.time()
            _save_state(state)

    return result


def _send_drip_2(entry: dict) -> dict:
    """Send drip email 2 and mark it in state."""
    try:
        result = send_drip_email_2(email=entry["email"], api_key=entry["api_key"])
    except Exception as e:
        result = {"success": False, "error": str(e)}

    with _lock:
        state = _load_state()
        stored = _find_entry(state, entry["email"], entry["key_id"])
        if stored and 2 not in stored["drips_sent"]:
            stored["drips_sent"].append(2)
            stored["drip_2_sent_at"] = time.time()
            _save_state(state)

    return result


def _send_drip_3(entry: dict) -> dict:
    """Send drip email 3 with usage stats and mark it in state."""
    calls_made = _count_calls_for_key(entry["key_id"])

    try:
        result = send_drip_email_3(
            email=entry["email"],
            api_key=entry["api_key"],
            calls_made=calls_made,
        )
    except Exception as e:
        result = {"success": False, "error": str(e)}

    with _lock:
        state = _load_state()
        stored = _find_entry(state, entry["email"], entry["key_id"])
        if stored and 3 not in stored["drips_sent"]:
            stored["drips_sent"].append(3)
            stored["drip_3_sent_at"] = time.time()
            stored["drip_3_calls_made"] = calls_made
            stored["completed"] = True
            _save_state(state)

    return result


# ---------------------------------------------------------------------------
# Periodic Check (called by scheduler / cron / background thread)
# ---------------------------------------------------------------------------

def check_and_send_drips() -> dict:
    """Check all pending drip entries and send any due emails.

    Call this periodically (e.g., every 15 minutes). It is safe to call
    frequently — drips are only sent once per entry.

    Returns:
        dict with counts of emails sent and any errors.
    """
    now = time.time()
    results = {"checked": 0, "drip_2_sent": 0, "drip_3_sent": 0, "errors": []}

    with _lock:
        state = _load_state()
        # Take a snapshot of pending entries
        pending = [
            dict(e) for e in state["entries"]
            if not e.get("completed", False)
        ]

    results["checked"] = len(pending)

    for entry in pending:
        elapsed = now - entry["provisioned_at"]
        drips_sent = entry.get("drips_sent", [])

        # Drip 2: send at ~48 hours
        if 2 not in drips_sent and elapsed >= DRIP_2_DELAY:
            try:
                result = _send_drip_2(entry)
                if result.get("success"):
                    results["drip_2_sent"] += 1
                else:
                    results["errors"].append({
                        "email": entry["email"],
                        "drip": 2,
                        "error": result.get("error", result.get("reason", "unknown")),
                    })
            except Exception as e:
                results["errors"].append({
                    "email": entry["email"],
                    "drip": 2,
                    "error": str(e),
                })

        # Drip 3: send at ~120 hours (5 days)
        if 3 not in drips_sent and 2 in drips_sent and elapsed >= DRIP_3_DELAY:
            try:
                result = _send_drip_3(entry)
                if result.get("success"):
                    results["drip_3_sent"] += 1
                else:
                    results["errors"].append({
                        "email": entry["email"],
                        "drip": 3,
                        "error": result.get("error", result.get("reason", "unknown")),
                    })
            except Exception as e:
                results["errors"].append({
                    "email": entry["email"],
                    "drip": 3,
                    "error": str(e),
                })

    if results["drip_2_sent"] or results["drip_3_sent"]:
        print(f"[drip] Sent {results['drip_2_sent']} drip-2 and {results['drip_3_sent']} drip-3 emails")

    if results["errors"]:
        print(f"[drip] {len(results['errors'])} error(s): {results['errors']}")

    return results


# ---------------------------------------------------------------------------
# Background Scheduler (optional — starts a thread that checks every 15 min)
# ---------------------------------------------------------------------------

_scheduler_thread: Optional[threading.Thread] = None


def start_drip_scheduler(interval_seconds: int = 900):
    """Start a background thread that calls check_and_send_drips() periodically.

    Args:
        interval_seconds: How often to check (default: 900 = 15 minutes).
    """
    global _scheduler_thread

    if _scheduler_thread is not None and _scheduler_thread.is_alive():
        print("[drip] Scheduler already running")
        return

    def _loop():
        print(f"[drip] Scheduler started (interval: {interval_seconds}s)")
        while True:
            try:
                check_and_send_drips()
            except Exception as e:
                print(f"[drip] Scheduler error: {e}")
            time.sleep(interval_seconds)

    _scheduler_thread = threading.Thread(target=_loop, daemon=True, name="drip-scheduler")
    _scheduler_thread.start()


# ---------------------------------------------------------------------------
# Status / Debug
# ---------------------------------------------------------------------------

def get_drip_status() -> dict:
    """Get summary of all drip entries for debugging."""
    with _lock:
        state = _load_state()

    total = len(state["entries"])
    completed = sum(1 for e in state["entries"] if e.get("completed"))
    pending = total - completed

    return {
        "total_entries": total,
        "completed": completed,
        "pending": pending,
        "entries": [
            {
                "email": e["email"],
                "key_id": e["key_id"][:12] + "...",
                "provisioned_at": e.get("provisioned_at_iso", "unknown"),
                "drips_sent": e.get("drips_sent", []),
                "completed": e.get("completed", False),
            }
            for e in state["entries"]
        ],
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    import argparse
    parser = argparse.ArgumentParser(description="ReNoUn Drip Email Scheduler")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("status", help="Show drip state summary")
    sub.add_parser("check", help="Run check_and_send_drips() once")

    run_cmd = sub.add_parser("run", help="Start background scheduler")
    run_cmd.add_argument("--interval", type=int, default=900, help="Check interval in seconds")

    args = parser.parse_args()

    if args.command == "status":
        status = get_drip_status()
        print(json.dumps(status, indent=2))

    elif args.command == "check":
        results = check_and_send_drips()
        print(json.dumps(results, indent=2))

    elif args.command == "run":
        print(f"Starting drip scheduler (interval: {args.interval}s)")
        print("Press Ctrl+C to stop.")
        start_drip_scheduler(interval_seconds=args.interval)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nStopped.")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
