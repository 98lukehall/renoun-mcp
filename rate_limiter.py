"""
ReNoUn API Rate Limiter.

SQLite-backed rate limiting per API key.
Resets daily. Persists across restarts.
"""

import time
import logging
from typing import Optional
from auth import get_tier_config

logger = logging.getLogger(__name__)


class RateLimiter:
    """SQLite-backed rate limiter with daily reset per key."""

    def __init__(self):
        # Lazy import to avoid circular imports at module load time
        self._db = None

    def _get_db(self):
        """Lazy-load the database module."""
        if self._db is None:
            from db import get_connection
            self._db = get_connection
        return self._db()

    def _get_bucket(self, key_id: str, tier: str) -> dict:
        """Get or create a bucket for a key from SQLite."""
        now = time.time()
        today = time.strftime("%Y-%m-%d", time.gmtime(now))

        try:
            conn = self._get_db()
            row = conn.execute(
                "SELECT call_count, reset_at FROM rate_limits WHERE key_id = ? AND date = ?",
                (key_id, today),
            ).fetchone()

            if row is None:
                # New day / new key — insert a fresh row
                reset_at = now + 86400
                conn.execute(
                    "INSERT OR IGNORE INTO rate_limits (key_id, date, call_count, reset_at) VALUES (?, ?, 0, ?)",
                    (key_id, today, reset_at),
                )
                conn.commit()
                return {"count": 0, "reset_at": reset_at}

            reset_at = row["reset_at"]

            # If the reset time has passed, zero the count and push the window forward
            if now >= reset_at:
                new_reset = now + 86400
                conn.execute(
                    "UPDATE rate_limits SET call_count = 0, reset_at = ? WHERE key_id = ? AND date = ?",
                    (new_reset, key_id, today),
                )
                conn.commit()
                return {"count": 0, "reset_at": new_reset}

            return {"count": row["call_count"], "reset_at": reset_at}

        except Exception as e:
            logger.warning("RateLimiter._get_bucket failed: %s — allowing request", e)
            # Fail open: if the DB is broken, don't block requests
            return {"count": 0, "reset_at": now + 86400}

    def check(self, key_id: str, tier: str) -> Optional[dict]:
        """Check if request is allowed.

        Returns None if allowed.
        Returns dict with error info if rate limited.
        """
        config = get_tier_config(tier)
        daily_limit = config["daily_limit"]

        # Unlimited tier
        if daily_limit == -1:
            return None

        bucket = self._get_bucket(key_id, tier)

        if bucket["count"] >= daily_limit:
            retry_after = int(bucket["reset_at"] - time.time())
            return {
                "error": "rate_limited",
                "message": f"Daily limit of {daily_limit} requests exceeded for {tier} tier.",
                "retry_after": max(retry_after, 1),
                "daily_limit": daily_limit,
                "current_count": bucket["count"],
            }

        return None

    def record(self, key_id: str, tier: str):
        """Record a request (call after successful processing)."""
        now = time.time()
        today = time.strftime("%Y-%m-%d", time.gmtime(now))

        try:
            conn = self._get_db()
            # Upsert: increment if exists, insert with count=1 if not
            conn.execute(
                """INSERT INTO rate_limits (key_id, date, call_count, reset_at)
                   VALUES (?, ?, 1, ?)
                   ON CONFLICT(key_id, date) DO UPDATE SET call_count = call_count + 1""",
                (key_id, today, now + 86400),
            )
            conn.commit()
        except Exception as e:
            logger.warning("RateLimiter.record failed: %s", e)

    def get_usage(self, key_id: str, tier: str) -> dict:
        """Get current usage stats for a key."""
        config = get_tier_config(tier)
        bucket = self._get_bucket(key_id, tier)
        daily_limit = config["daily_limit"]
        return {
            "used": bucket["count"],
            "limit": daily_limit,
            "remaining": max(0, daily_limit - bucket["count"]) if daily_limit != -1 else -1,
            "resets_at": int(bucket["reset_at"]),
        }


# Singleton instance
limiter = RateLimiter()
