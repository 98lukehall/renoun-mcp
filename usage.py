"""
ReNoUn API Usage Logger.

Appends usage events to $RENOUN_DATA_DIR/usage.log in JSONL format.
Each line is a complete JSON object — grep-friendly, easy to analyze.

Also provides metered billing tracking for agent-tier keys:
- Daily call counters (reset at midnight UTC)
- Free tier tracking (50 free/day)
- Stripe usage record reporting for billable calls
"""

import json
import os
import time
import threading
from pathlib import Path
from datetime import datetime, timezone


# Use persistent volume if available (Railway), fall back to home directory
_DATA_DIR = os.environ.get("RENOUN_DATA_DIR", str(Path.home() / ".renoun"))
USAGE_LOG = Path(_DATA_DIR) / "usage.log"


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


# ---------------------------------------------------------------------------
# Metered Usage Tracking (Agent Tier)
# ---------------------------------------------------------------------------

class MeteredUsageTracker:
    """In-memory daily usage tracking for agent-tier metered billing."""

    WARN_THRESHOLD = 40   # API response warning starts here
    LIMIT_THRESHOLD = 50  # Free tier cap — email sent here

    def __init__(self):
        self._lock = threading.Lock()
        # {key_id: {"date": "YYYY-MM-DD", "total": int, "by_endpoint": {str: int}}}
        self._daily = {}
        # Track whether we already sent the limit email today per key
        # {key_id: "YYYY-MM-DD"}
        self._limit_email_sent = {}

    def _get_today(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _get_counter(self, key_id: str) -> dict:
        today = self._get_today()
        if key_id not in self._daily or self._daily[key_id]["date"] != today:
            self._daily[key_id] = {"date": today, "total": 0, "by_endpoint": {}}
        return self._daily[key_id]

    def record_call(self, key_id: str, endpoint: str, tier_config: dict) -> dict:
        """Record a call for metered billing.

        Returns dict with:
          is_billable: bool — whether this call exceeds the free tier
          daily_total: int — total calls today
          daily_remaining: int — calls remaining before daily limit
          free_remaining: int — free calls remaining
          warning: str|None — "approaching_limit" at 40+, "limit_reached" at 50+
          send_limit_email: bool — True exactly once when total hits 50
        """
        with self._lock:
            counter = self._get_counter(key_id)
            counter["total"] += 1
            counter["by_endpoint"][endpoint] = counter["by_endpoint"].get(endpoint, 0) + 1

            free_daily = tier_config.get("free_daily", 50)
            daily_limit = tier_config.get("daily_limit", 10000)
            total = counter["total"]

            is_billable = total > free_daily

            # Report to Stripe if billable
            if is_billable:
                self._report_stripe_usage(key_id)

            # Determine warning level
            warning = None
            if total >= free_daily:
                warning = "limit_reached"
            elif total >= self.WARN_THRESHOLD:
                warning = "approaching_limit"

            # Should we send the limit email? Only once per key per day.
            send_limit_email = False
            if total == free_daily:
                today = self._get_today()
                if self._limit_email_sent.get(key_id) != today:
                    self._limit_email_sent[key_id] = today
                    send_limit_email = True

            return {
                "is_billable": is_billable,
                "daily_total": total,
                "daily_remaining": max(0, daily_limit - total),
                "free_remaining": max(0, free_daily - total),
                "warning": warning,
                "send_limit_email": send_limit_email,
            }

    def _report_stripe_usage(self, key_id: str):
        """Report a single usage event to Stripe Billing Meter (if configured).

        Uses the new Stripe Billing Meter API (stripe.billing.MeterEvent.create)
        which requires a Billing Meter with event_name='api_requests'.
        The customer is identified by their stripe_customer_id on the key.
        """
        try:
            import stripe
            if not os.environ.get("STRIPE_SECRET_KEY"):
                return
            # Look up Stripe customer ID for this key
            from auth import _load_keys
            data = _load_keys()
            customer_id = None
            for entry in data["keys"]:
                if entry["key_id"] == key_id and entry.get("stripe_customer_id"):
                    customer_id = entry["stripe_customer_id"]
                    break
            if customer_id:
                stripe.api_key = os.environ["STRIPE_SECRET_KEY"]
                stripe.billing.MeterEvent.create(
                    event_name="api_requests",
                    payload={
                        "stripe_customer_id": customer_id,
                        "value": "1",
                    },
                    timestamp=int(time.time()),
                )
        except Exception:
            pass  # Don't let Stripe errors block API calls

    def check_daily_limit(self, key_id: str, tier_config: dict):
        """Check if daily limit is reached. Returns error dict or None."""
        with self._lock:
            counter = self._get_counter(key_id)
            daily_limit = tier_config.get("daily_limit", 10000)

            if daily_limit != -1 and counter["total"] >= daily_limit:
                tomorrow = self._get_today()  # Will reset on next day
                return {
                    "error": {
                        "type": "daily_limit",
                        "message": f"Daily call limit reached ({daily_limit}). Resets at midnight UTC.",
                        "action": "Wait for reset or contact support for higher limits.",
                        "reset_at": f"{tomorrow}T00:00:00Z",
                    }
                }
            return None

    def get_usage(self, key_id: str, tier_config: dict) -> dict:
        """Get current usage stats for a key."""
        with self._lock:
            counter = self._get_counter(key_id)
            free_daily = tier_config.get("free_daily", 50)
            daily_limit = tier_config.get("daily_limit", 10000)
            total = counter["total"]
            billable = max(0, total - free_daily)
            price = tier_config.get("price_per_call", 0.02)

            return {
                "today": {
                    "total_calls": total,
                    "free_calls": min(total, free_daily),
                    "billable_calls": billable,
                    "estimated_cost": f"${billable * price:.2f}",
                    "daily_limit": daily_limit,
                    "remaining": max(0, daily_limit - total),
                },
                "by_endpoint": dict(counter["by_endpoint"]),
            }

    def get_monthly_estimate(self, key_id: str, tier_config: dict) -> dict:
        """Estimate monthly usage from today's stats."""
        with self._lock:
            counter = self._get_counter(key_id)
            free_daily = tier_config.get("free_daily", 50)
            price = tier_config.get("price_per_call", 0.02)
            total = counter["total"]
            billable = max(0, total - free_daily)

            # Simple projection: today's rate * 30
            return {
                "total_calls": total * 30,
                "billable_calls": billable * 30,
                "estimated_cost": f"${billable * 30 * price:.2f}",
            }


# Singleton
metered_tracker = MeteredUsageTracker()
