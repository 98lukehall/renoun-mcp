"""
ReNoUn API Usage Logger.

Appends usage events to ~/.renoun/usage.log in JSONL format.
Each line is a complete JSON object — grep-friendly, easy to analyze.
"""

import json
import time
from pathlib import Path
from datetime import datetime


USAGE_LOG = Path.home() / ".renoun" / "usage.log"


def _ensure_log():
    """Ensure the log directory exists."""
    USAGE_LOG.parent.mkdir(parents=True, exist_ok=True)


def log_request(
    key_id: str,
    tier: str,
    endpoint: str,
    turn_count: int = 0,
    response_time_ms: float = 0,
    status_code: int = 200,
    error: str = "",
):
    """Log a single API request."""
    _ensure_log()
    entry = {
        "ts": datetime.utcnow().isoformat(),
        "epoch": time.time(),
        "key_id": key_id,
        "tier": tier,
        "endpoint": endpoint,
        "turn_count": turn_count,
        "response_time_ms": round(response_time_ms, 2),
        "status": status_code,
    }
    if error:
        entry["error"] = error

    with open(USAGE_LOG, "a") as f:
        f.write(json.dumps(entry, default=str) + "\n")
