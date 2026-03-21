"""
ReNoUn Analytics Tracker.

Simple JSON-file-based analytics for tracking:
- Landing page visits (pageviews)
- Key provisions per day
- API calls per endpoint per day
- Unique keys making calls per day

Stores data in $RENOUN_DATA_DIR/analytics.json as a date-keyed structure.
No external dependencies.
"""

import json
import os
import threading
from pathlib import Path
from datetime import datetime, timezone, timedelta


_DATA_DIR = os.environ.get("RENOUN_DATA_DIR", str(Path.home() / ".renoun"))
ANALYTICS_FILE = Path(_DATA_DIR) / "analytics.json"

_lock = threading.Lock()


def _ensure_file():
    """Ensure analytics file and directory exist."""
    ANALYTICS_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not ANALYTICS_FILE.exists():
        ANALYTICS_FILE.write_text(json.dumps({}, indent=2))


def _load() -> dict:
    """Load analytics data."""
    _ensure_file()
    try:
        return json.loads(ANALYTICS_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _save(data: dict):
    """Save analytics data."""
    _ensure_file()
    ANALYTICS_FILE.write_text(json.dumps(data, indent=2, default=str))


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _ensure_day(data: dict, day: str) -> dict:
    """Ensure a day entry exists with all required fields."""
    if day not in data:
        data[day] = {
            "pageviews": {},
            "provisions": 0,
            "api_calls": {},
            "unique_keys": [],
        }
    day_data = data[day]
    # Ensure all fields exist (for backwards compat)
    day_data.setdefault("pageviews", {})
    day_data.setdefault("provisions", 0)
    day_data.setdefault("api_calls", {})
    day_data.setdefault("unique_keys", [])
    return day_data


def record_pageview(page: str):
    """Record a landing page visit."""
    with _lock:
        data = _load()
        day = _today()
        day_data = _ensure_day(data, day)
        day_data["pageviews"][page] = day_data["pageviews"].get(page, 0) + 1
        _save(data)


def record_provision():
    """Record a key provision event."""
    with _lock:
        data = _load()
        day = _today()
        day_data = _ensure_day(data, day)
        day_data["provisions"] += 1
        _save(data)


def record_api_call(endpoint: str, key_id: str):
    """Record an API call for a given endpoint and key."""
    with _lock:
        data = _load()
        day = _today()
        day_data = _ensure_day(data, day)
        day_data["api_calls"][endpoint] = day_data["api_calls"].get(endpoint, 0) + 1
        if key_id and key_id not in day_data["unique_keys"]:
            day_data["unique_keys"].append(key_id)
        _save(data)


def get_summary() -> dict:
    """Get analytics summary: today, last 7 days, all-time totals."""
    with _lock:
        data = _load()

    today = _today()
    today_data = _ensure_day(data, today) if today in data else {
        "pageviews": {}, "provisions": 0, "api_calls": {}, "unique_keys": []
    }

    # Last 7 days
    last_7 = {}
    total_pageviews = 0
    total_provisions = 0
    total_api_calls = 0
    all_unique_keys = set()

    for i in range(7):
        day = (datetime.now(timezone.utc) - timedelta(days=i)).strftime("%Y-%m-%d")
        if day in data:
            day_data = data[day]
            pv = sum(day_data.get("pageviews", {}).values())
            prov = day_data.get("provisions", 0)
            calls = sum(day_data.get("api_calls", {}).values())
            keys = day_data.get("unique_keys", [])
            last_7[day] = {
                "pageviews": pv,
                "provisions": prov,
                "api_calls": calls,
                "unique_keys": len(keys),
            }

    # All-time totals
    for day_str, day_data in data.items():
        total_pageviews += sum(day_data.get("pageviews", {}).values())
        total_provisions += day_data.get("provisions", 0)
        total_api_calls += sum(day_data.get("api_calls", {}).values())
        for k in day_data.get("unique_keys", []):
            all_unique_keys.add(k)

    return {
        "today": {
            "date": today,
            "pageviews": today_data.get("pageviews", {}),
            "pageviews_total": sum(today_data.get("pageviews", {}).values()),
            "provisions": today_data.get("provisions", 0),
            "api_calls": today_data.get("api_calls", {}),
            "api_calls_total": sum(today_data.get("api_calls", {}).values()),
            "unique_keys": len(today_data.get("unique_keys", [])),
        },
        "last_7_days": last_7,
        "all_time": {
            "total_pageviews": total_pageviews,
            "total_provisions": total_provisions,
            "total_api_calls": total_api_calls,
            "total_unique_keys": len(all_unique_keys),
            "days_tracked": len(data),
        },
    }
