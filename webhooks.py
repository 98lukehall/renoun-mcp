"""
Webhook registration and dispatch for regime change notifications.

Storage: JSON file at $RENOUN_DATA_DIR/webhooks.json (default: ~/.renoun/)
Dispatch: Background thread with HMAC-SHA256 signing and retry logic.
Architecture: Signal bot reads webhooks.json directly (shared filesystem).
"""

import json
import hmac
import hashlib
import os
import secrets
import threading
import time
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

import requests as http_requests  # avoid conflict with fastapi Request


# Use persistent volume if available (Railway), fall back to home directory
_DATA_DIR = os.environ.get("RENOUN_DATA_DIR", str(Path.home() / ".renoun"))
WEBHOOKS_FILE = Path(_DATA_DIR) / "webhooks.json"

VALID_EVENTS = [
    "regime_change",
    "dhs_crash",
    "unstable_detected",
    "recovery",
]


def _ensure_file():
    WEBHOOKS_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not WEBHOOKS_FILE.exists():
        # Migrate from legacy location if it exists
        legacy = Path.home() / ".renoun" / "webhooks.json"
        if legacy.exists() and legacy != WEBHOOKS_FILE:
            import shutil
            shutil.copy2(legacy, WEBHOOKS_FILE)
            print(f"[webhooks] Migrated from {legacy} to {WEBHOOKS_FILE}")
        else:
            WEBHOOKS_FILE.write_text(json.dumps({"webhooks": []}, indent=2))


def _load() -> dict:
    _ensure_file()
    return json.loads(WEBHOOKS_FILE.read_text())


def _save(data: dict):
    _ensure_file()
    WEBHOOKS_FILE.write_text(json.dumps(data, indent=2, default=str))


def register_webhook(api_key_id: str, url: str, symbols: list[str],
                     events: list[str], secret: str) -> dict:
    """Register a new webhook. Returns webhook record."""
    # Validate events
    for e in events:
        if e not in VALID_EVENTS:
            return {"error": f"Invalid event: {e}. Valid: {VALID_EVENTS}"}

    if len(symbols) > 10:
        return {"error": "Maximum 10 symbols per webhook."}

    data = _load()

    # Check limit: max 5 per key
    existing = [w for w in data["webhooks"] if w["api_key_id"] == api_key_id and w["active"]]
    if len(existing) >= 5:
        return {"error": "Maximum 5 webhooks per API key."}

    webhook_id = "wh_" + secrets.token_hex(8)
    record = {
        "webhook_id": webhook_id,
        "api_key_id": api_key_id,
        "url": url,
        "symbols": symbols,
        "events": events,
        "secret": secret,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "active": True,
        "consecutive_failures": 0,
    }
    data["webhooks"].append(record)
    _save(data)

    return {
        "webhook_id": webhook_id,
        "url": url,
        "symbols": symbols,
        "events": events,
        "active": True,
        "created_at": record["created_at"],
    }


def list_webhooks(api_key_id: str) -> list[dict]:
    """List all webhooks for an API key."""
    data = _load()
    return [
        {
            "webhook_id": w["webhook_id"],
            "url": w["url"],
            "symbols": w["symbols"],
            "events": w["events"],
            "active": w["active"],
            "created_at": w["created_at"],
        }
        for w in data["webhooks"]
        if w["api_key_id"] == api_key_id
    ]


def delete_webhook(api_key_id: str, webhook_id: str) -> bool:
    """Deactivate a webhook. Returns True if found."""
    data = _load()
    for w in data["webhooks"]:
        if w["webhook_id"] == webhook_id and w["api_key_id"] == api_key_id:
            w["active"] = False
            _save(data)
            return True
    return False


def get_webhook(webhook_id: str) -> Optional[dict]:
    """Get a webhook record by ID."""
    data = _load()
    for w in data["webhooks"]:
        if w["webhook_id"] == webhook_id:
            return w
    return None


def sign_payload(payload_bytes: bytes, secret: str) -> str:
    """HMAC-SHA256 sign a payload."""
    return hmac.new(secret.encode(), payload_bytes, hashlib.sha256).hexdigest()


def dispatch_webhook(webhook: dict, payload: dict):
    """Send webhook payload with signing and retry. Runs in background thread."""
    def _send():
        body = json.dumps(payload)
        body_bytes = body.encode()
        signature = sign_payload(body_bytes, webhook["secret"])

        headers = {
            "Content-Type": "application/json",
            "X-ReNoUn-Signature": signature,
            "X-ReNoUn-Event": payload.get("event", "unknown"),
        }

        delays = [5, 30, 120]  # retry backoff
        success = False

        for attempt in range(3):
            try:
                resp = http_requests.post(
                    webhook["url"], data=body_bytes, headers=headers, timeout=5,
                )
                if resp.status_code < 400:
                    success = True
                    _reset_failures(webhook["webhook_id"])
                    break
            except Exception:
                pass

            if attempt < 2:
                time.sleep(delays[attempt])

        if not success:
            _increment_failures(webhook["webhook_id"])

    thread = threading.Thread(target=_send, daemon=True)
    thread.start()
    return thread


def _reset_failures(webhook_id: str):
    data = _load()
    for w in data["webhooks"]:
        if w["webhook_id"] == webhook_id:
            w["consecutive_failures"] = 0
            _save(data)
            return


def _increment_failures(webhook_id: str):
    data = _load()
    for w in data["webhooks"]:
        if w["webhook_id"] == webhook_id:
            w["consecutive_failures"] = w.get("consecutive_failures", 0) + 1
            if w["consecutive_failures"] >= 10:
                w["active"] = False  # auto-deactivate
            _save(data)
            return


def get_matching_webhooks(symbol: str, event: str) -> list[dict]:
    """Find all active webhooks matching a symbol and event type."""
    data = _load()
    return [
        w for w in data["webhooks"]
        if w["active"]
        and symbol in w["symbols"]
        and event in w["events"]
    ]


def fire_regime_change(symbol: str, previous: dict, current: dict):
    """Fire regime_change webhooks for a symbol transition."""
    payload = {
        "event": "regime_change",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "previous": previous,
        "current": current,
    }

    # Fire regime_change
    for wh in get_matching_webhooks(symbol, "regime_change"):
        dispatch_webhook(wh, payload)

    # Fire unstable_detected if entering unstable
    if current.get("regime") == "unstable":
        for wh in get_matching_webhooks(symbol, "unstable_detected"):
            dispatch_webhook(wh, {**payload, "event": "unstable_detected"})

    # Fire dhs_crash if DHS < 0.35
    if current.get("dhs", 1.0) < 0.35:
        for wh in get_matching_webhooks(symbol, "dhs_crash"):
            dispatch_webhook(wh, {**payload, "event": "dhs_crash"})

    # Fire recovery if exiting unstable
    if previous.get("regime") == "unstable" and current.get("regime") != "unstable":
        for wh in get_matching_webhooks(symbol, "recovery"):
            dispatch_webhook(wh, {**payload, "event": "recovery"})
