"""
ReNoUn Analytics Tracker.

SQLite-backed analytics for tracking:
- Landing page visits (pageviews)
- Key provisions per day
- API calls per endpoint per day
- Unique keys making calls per day

Stores data in $RENOUN_DATA_DIR/renoun.db.
No external dependencies.
"""

import json
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)


def _get_db():
    """Lazy-load database connection."""
    from db import get_connection
    return get_connection()


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def record_pageview(page: str):
    """Record a landing page visit."""
    try:
        conn = _get_db()
        day = _today()
        conn.execute(
            """INSERT INTO pageviews (date, page, count) VALUES (?, ?, 1)
               ON CONFLICT(date, page) DO UPDATE SET count = count + 1""",
            (day, page),
        )
        conn.commit()
    except Exception as e:
        logger.warning("record_pageview failed: %s", e)


def record_provision():
    """Record a key provision event."""
    try:
        conn = _get_db()
        day = _today()
        conn.execute(
            """INSERT INTO daily_stats (date, provisions, unique_keys) VALUES (?, 1, '[]')
               ON CONFLICT(date) DO UPDATE SET provisions = provisions + 1""",
            (day,),
        )
        conn.commit()
    except Exception as e:
        logger.warning("record_provision failed: %s", e)


def record_api_call(endpoint: str, key_id: str):
    """Record an API call for a given endpoint and key."""
    try:
        conn = _get_db()
        day = _today()

        # Increment call count for this endpoint + key combo
        conn.execute(
            """INSERT INTO api_calls (date, endpoint, key_id, count) VALUES (?, ?, ?, 1)
               ON CONFLICT(date, endpoint, key_id) DO UPDATE SET count = count + 1""",
            (day, endpoint, key_id or ""),
        )

        # Track unique keys per day in daily_stats
        if key_id:
            row = conn.execute(
                "SELECT unique_keys FROM daily_stats WHERE date = ?", (day,)
            ).fetchone()

            if row is None:
                conn.execute(
                    "INSERT INTO daily_stats (date, provisions, unique_keys) VALUES (?, 0, ?)",
                    (day, json.dumps([key_id])),
                )
            else:
                keys = json.loads(row["unique_keys"])
                if key_id not in keys:
                    keys.append(key_id)
                    conn.execute(
                        "UPDATE daily_stats SET unique_keys = ? WHERE date = ?",
                        (json.dumps(keys), day),
                    )

        conn.commit()
    except Exception as e:
        logger.warning("record_api_call failed: %s", e)


def get_summary() -> dict:
    """Get analytics summary: today, last 7 days, all-time totals."""
    try:
        conn = _get_db()
        today = _today()

        # --- Today's data ---
        today_pageviews = {}
        for row in conn.execute(
            "SELECT page, count FROM pageviews WHERE date = ?", (today,)
        ):
            today_pageviews[row["page"]] = row["count"]

        today_api_calls = {}
        for row in conn.execute(
            "SELECT endpoint, SUM(count) as total FROM api_calls WHERE date = ? GROUP BY endpoint",
            (today,),
        ):
            today_api_calls[row["endpoint"]] = row["total"]

        today_stats_row = conn.execute(
            "SELECT provisions, unique_keys FROM daily_stats WHERE date = ?", (today,)
        ).fetchone()
        today_provisions = today_stats_row["provisions"] if today_stats_row else 0
        today_unique_keys = (
            json.loads(today_stats_row["unique_keys"]) if today_stats_row else []
        )

        # --- Last 7 days ---
        last_7 = {}
        for i in range(7):
            day = (datetime.now(timezone.utc) - timedelta(days=i)).strftime("%Y-%m-%d")

            pv_row = conn.execute(
                "SELECT SUM(count) as total FROM pageviews WHERE date = ?", (day,)
            ).fetchone()
            pv = pv_row["total"] if pv_row and pv_row["total"] else 0

            calls_row = conn.execute(
                "SELECT SUM(count) as total FROM api_calls WHERE date = ?", (day,)
            ).fetchone()
            calls = calls_row["total"] if calls_row and calls_row["total"] else 0

            stats_row = conn.execute(
                "SELECT provisions, unique_keys FROM daily_stats WHERE date = ?", (day,)
            ).fetchone()
            prov = stats_row["provisions"] if stats_row else 0
            keys = json.loads(stats_row["unique_keys"]) if stats_row else []

            # Only include days that have data
            if pv or calls or prov or keys:
                last_7[day] = {
                    "pageviews": pv,
                    "provisions": prov,
                    "api_calls": calls,
                    "unique_keys": len(keys),
                }

        # --- All-time totals ---
        total_pv_row = conn.execute("SELECT SUM(count) as total FROM pageviews").fetchone()
        total_pageviews = total_pv_row["total"] if total_pv_row and total_pv_row["total"] else 0

        total_prov_row = conn.execute("SELECT SUM(provisions) as total FROM daily_stats").fetchone()
        total_provisions = total_prov_row["total"] if total_prov_row and total_prov_row["total"] else 0

        total_calls_row = conn.execute("SELECT SUM(count) as total FROM api_calls").fetchone()
        total_api_calls = total_calls_row["total"] if total_calls_row and total_calls_row["total"] else 0

        # Gather all unique keys across all time
        all_unique_keys = set()
        for row in conn.execute("SELECT unique_keys FROM daily_stats"):
            for k in json.loads(row["unique_keys"]):
                all_unique_keys.add(k)

        days_tracked_row = conn.execute("SELECT COUNT(DISTINCT date) as cnt FROM daily_stats").fetchone()
        # Also count days from pageviews and api_calls
        pv_days_row = conn.execute("SELECT COUNT(DISTINCT date) as cnt FROM pageviews").fetchone()
        ac_days_row = conn.execute("SELECT COUNT(DISTINCT date) as cnt FROM api_calls").fetchone()
        days_tracked = max(
            days_tracked_row["cnt"] if days_tracked_row else 0,
            pv_days_row["cnt"] if pv_days_row else 0,
            ac_days_row["cnt"] if ac_days_row else 0,
        )

        return {
            "today": {
                "date": today,
                "pageviews": today_pageviews,
                "pageviews_total": sum(today_pageviews.values()),
                "provisions": today_provisions,
                "api_calls": today_api_calls,
                "api_calls_total": sum(today_api_calls.values()),
                "unique_keys": len(today_unique_keys),
            },
            "last_7_days": last_7,
            "all_time": {
                "total_pageviews": total_pageviews,
                "total_provisions": total_provisions,
                "total_api_calls": total_api_calls,
                "total_unique_keys": len(all_unique_keys),
                "days_tracked": days_tracked,
            },
        }

    except Exception as e:
        logger.warning("get_summary failed: %s", e)
        # Return empty structure on error so the API never crashes
        today = _today()
        return {
            "today": {
                "date": today,
                "pageviews": {},
                "pageviews_total": 0,
                "provisions": 0,
                "api_calls": {},
                "api_calls_total": 0,
                "unique_keys": 0,
            },
            "last_7_days": {},
            "all_time": {
                "total_pageviews": 0,
                "total_provisions": 0,
                "total_api_calls": 0,
                "total_unique_keys": 0,
                "days_tracked": 0,
            },
        }
