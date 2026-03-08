#!/usr/bin/env python3
"""
ReNoUn API Key Management.

Manages API keys with tiered access control.
Keys stored in ~/.renoun/api_keys.json.

Usage:
    python3 auth.py create --tier pro --owner "user@email.com"
    python3 auth.py list
    python3 auth.py revoke --key-id rn_abc123
"""

import json
import hashlib
import secrets
import argparse
from pathlib import Path
from datetime import datetime
from typing import Optional


KEYS_FILE = Path.home() / ".renoun" / "api_keys.json"
KEY_PREFIX = "rn_live_"

# Tier definitions
TIERS = {
    "free": {
        "tools": ["renoun_health_check"],
        "daily_limit": 20,
        "max_turns": 200,
        "rate_limits": {
            "renoun_health_check": 10,       # calls/min
            "renoun_finance_analyze": 10,    # calls/min
        },
    },
    "pro": {
        "tools": ["renoun_analyze", "renoun_health_check", "renoun_compare", "renoun_pattern_query", "renoun_steer", "renoun_finance_analyze"],
        "daily_limit": 1000,
        "max_turns": 500,
        "price": "$4.99/mo",
        "rate_limits": {
            "renoun_analyze": 60,            # calls/min
            "renoun_health_check": 120,      # calls/min
            "renoun_compare": 60,            # calls/min
            "renoun_pattern_query": 60,      # calls/min
            "renoun_steer": 120,             # calls/min
            "renoun_finance_analyze": 100,   # calls/min
        },
    },
    "enterprise": {
        "tools": ["renoun_analyze", "renoun_health_check", "renoun_compare", "renoun_pattern_query", "renoun_steer", "renoun_finance_analyze"],
        "daily_limit": -1,  # unlimited
        "max_turns": -1,  # unlimited
        "rate_limits": {
            "renoun_finance_analyze": -1,    # unlimited
        },
    },
}


def _ensure_keys_file():
    """Ensure the keys file and parent directory exist."""
    KEYS_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not KEYS_FILE.exists():
        KEYS_FILE.write_text(json.dumps({"keys": []}, indent=2))


def _load_keys() -> dict:
    """Load all API keys from storage."""
    _ensure_keys_file()
    return json.loads(KEYS_FILE.read_text())


def _save_keys(data: dict):
    """Save API keys to storage."""
    _ensure_keys_file()
    KEYS_FILE.write_text(json.dumps(data, indent=2, default=str))


def _hash_key(raw_key: str) -> str:
    """Hash an API key for storage."""
    return hashlib.sha256(raw_key.encode()).hexdigest()


def create_key(tier: str = "free", owner: str = "") -> dict:
    """Create a new API key.

    Returns dict with raw_key (show once), key_id, tier, owner.
    """
    if tier not in TIERS:
        raise ValueError(f"Invalid tier: {tier}. Must be one of: {list(TIERS.keys())}")

    raw_key = KEY_PREFIX + secrets.token_hex(24)
    key_id = KEY_PREFIX + secrets.token_hex(8)

    data = _load_keys()
    entry = {
        "key_id": key_id,
        "key_hash": _hash_key(raw_key),
        "tier": tier,
        "owner": owner,
        "created_at": datetime.utcnow().isoformat(),
        "active": True,
    }
    data["keys"].append(entry)
    _save_keys(data)

    return {"raw_key": raw_key, "key_id": key_id, "tier": tier, "owner": owner}


def validate_key(raw_key: str) -> Optional[dict]:
    """Validate an API key. Returns key metadata if valid, None if invalid."""
    if not raw_key or not raw_key.startswith(KEY_PREFIX):
        return None

    key_hash = _hash_key(raw_key)
    data = _load_keys()

    for entry in data["keys"]:
        if entry["key_hash"] == key_hash and entry["active"]:
            return {
                "key_id": entry["key_id"],
                "tier": entry["tier"],
                "owner": entry.get("owner", ""),
                "created_at": entry.get("created_at", ""),
            }
    return None


def get_tier_config(tier: str) -> dict:
    """Get the configuration for a tier."""
    return TIERS.get(tier, TIERS["free"])


def is_tool_allowed(tier: str, tool_name: str) -> bool:
    """Check if a tool is allowed for a given tier."""
    config = get_tier_config(tier)
    return tool_name in config["tools"]


def get_rate_limit(tier: str, tool_name: str) -> int:
    """Get the per-minute rate limit for a tool in a given tier.

    Returns:
        int: calls per minute. -1 means unlimited.
             Defaults to 60 if no specific limit is configured.
    """
    config = get_tier_config(tier)
    rate_limits = config.get("rate_limits", {})
    return rate_limits.get(tool_name, 60)  # default 60/min if not specified


def revoke_key(key_id: str) -> bool:
    """Revoke an API key by key_id."""
    data = _load_keys()
    for entry in data["keys"]:
        if entry["key_id"] == key_id:
            entry["active"] = False
            _save_keys(data)
            return True
    return False


def list_keys() -> list:
    """List all API keys (without hashes)."""
    data = _load_keys()
    return [
        {
            "key_id": e["key_id"],
            "tier": e["tier"],
            "owner": e.get("owner", ""),
            "active": e["active"],
            "created_at": e.get("created_at", ""),
        }
        for e in data["keys"]
    ]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="ReNoUn API Key Management")
    sub = parser.add_subparsers(dest="command")

    # create
    create_cmd = sub.add_parser("create", help="Create a new API key")
    create_cmd.add_argument("--tier", choices=list(TIERS.keys()), default="free")
    create_cmd.add_argument("--owner", default="", help="Owner email or identifier")

    # list
    sub.add_parser("list", help="List all API keys")

    # revoke
    revoke_cmd = sub.add_parser("revoke", help="Revoke an API key")
    revoke_cmd.add_argument("--key-id", required=True, help="Key ID to revoke")

    args = parser.parse_args()

    if args.command == "create":
        result = create_key(tier=args.tier, owner=args.owner)
        print(f"\nAPI Key Created")
        print(f"  Key:   {result['raw_key']}")
        print(f"  ID:    {result['key_id']}")
        print(f"  Tier:  {result['tier']}")
        print(f"  Owner: {result['owner'] or '(none)'}")
        print(f"\n  Store this key securely — it cannot be recovered.\n")

    elif args.command == "list":
        keys = list_keys()
        if not keys:
            print("No API keys found.")
        else:
            print(f"\n{'Key ID':<30} {'Tier':<12} {'Active':<8} {'Owner'}")
            print("-" * 80)
            for k in keys:
                print(f"{k['key_id']:<30} {k['tier']:<12} {str(k['active']):<8} {k['owner']}")
            print()

    elif args.command == "revoke":
        if revoke_key(args.key_id):
            print(f"Key {args.key_id} revoked.")
        else:
            print(f"Key {args.key_id} not found.")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
