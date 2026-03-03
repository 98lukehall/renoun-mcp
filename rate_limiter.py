"""
ReNoUn API Rate Limiter.

In-memory token bucket rate limiting per API key.
Resets daily. No external dependencies (no Redis).
"""

import time
from typing import Optional
from auth import get_tier_config


class RateLimiter:
    """In-memory rate limiter with daily reset per key."""

    def __init__(self):
        # {key_id: {"count": int, "reset_at": float}}
        self._buckets: dict = {}

    def _get_bucket(self, key_id: str, tier: str) -> dict:
        """Get or create a bucket for a key."""
        now = time.time()

        if key_id not in self._buckets:
            self._buckets[key_id] = {
                "count": 0,
                "reset_at": now + 86400,  # 24 hours from first request
            }

        bucket = self._buckets[key_id]

        # Reset if expired
        if now >= bucket["reset_at"]:
            bucket["count"] = 0
            bucket["reset_at"] = now + 86400

        return bucket

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
        bucket = self._get_bucket(key_id, tier)
        bucket["count"] += 1

    def get_usage(self, key_id: str, tier: str) -> dict:
        """Get current usage stats for a key."""
        config = get_tier_config(tier)
        bucket = self._get_bucket(key_id, tier)
        return {
            "used": bucket["count"],
            "limit": config["daily_limit"],
            "remaining": max(0, config["daily_limit"] - bucket["count"]) if config["daily_limit"] != -1 else -1,
            "resets_at": int(bucket["reset_at"]),
        }


# Singleton instance
limiter = RateLimiter()
