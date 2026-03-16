#!/usr/bin/env python3
"""
Tests for ReNoUn Stripe billing integration.

Tests webhook handling, key provisioning, and tier changes
using mocked Stripe events (no real Stripe API calls).

Run:
    python3 tests/test_stripe.py
    # or
    pytest tests/test_stripe.py -v
"""

import sys
import os
import json
import shutil
import tempfile
import time
import hmac
import hashlib

# Ensure we can import from parent
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Isolate state
_orig_home = os.environ.get("HOME")
_tmpdir = tempfile.mkdtemp(prefix="renoun_stripe_test_")
os.environ["HOME"] = _tmpdir

# Set a test webhook secret before importing
TEST_WEBHOOK_SECRET = "whsec_test_secret_for_unit_tests"
os.environ["STRIPE_WEBHOOK_SECRET"] = TEST_WEBHOOK_SECRET
os.environ["STRIPE_SECRET_KEY"] = "sk_test_fake"
os.environ["STRIPE_PRICE_ID"] = "price_test_fake"

import auth as _auth_module
from pathlib import Path

# Save original KEYS_FILE and redirect to temp dir for isolation
_orig_keys_file = _auth_module.KEYS_FILE
_isolated_keys_file = Path(_tmpdir) / ".renoun" / "api_keys.json"
_auth_module.KEYS_FILE = _isolated_keys_file

from auth import create_key, _load_keys, list_keys
from stripe_billing import (
    handle_webhook,
    _link_key_to_stripe,
    _find_key_by_customer,
    _find_key_by_subscription,
    _downgrade_key,
    _handle_checkout_completed,
    _handle_payment_succeeded,
    _handle_subscription_change,
    _handle_payment_failed,
)


import pytest


@pytest.fixture(autouse=True, scope="module")
def _restore_auth_keys_file():
    """Restore auth.KEYS_FILE after all tests in this module complete."""
    yield
    _auth_module.KEYS_FILE = _orig_keys_file
    if _orig_home:
        os.environ["HOME"] = _orig_home


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_signed_payload(event_data: dict) -> tuple:
    """Create a properly signed Stripe webhook payload.

    Returns (payload_bytes, signature_header).
    """
    payload = json.dumps(event_data).encode()
    timestamp = str(int(time.time()))
    signed_payload = f"{timestamp}.{payload.decode()}"
    signature = hmac.new(
        TEST_WEBHOOK_SECRET.encode(),
        signed_payload.encode(),
        hashlib.sha256,
    ).hexdigest()
    sig_header = f"t={timestamp},v1={signature}"
    return payload, sig_header


def _make_checkout_event(customer_id: str, email: str, subscription_id: str) -> dict:
    """Build a checkout.session.completed event."""
    return {
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "customer": customer_id,
                "customer_email": email,
                "subscription": subscription_id,
            }
        }
    }


def _make_payment_succeeded_event(customer_id: str, subscription_id: str) -> dict:
    return {
        "type": "invoice.payment_succeeded",
        "data": {
            "object": {
                "customer": customer_id,
                "subscription": subscription_id,
            }
        }
    }


def _make_subscription_deleted_event(subscription_id: str) -> dict:
    return {
        "type": "customer.subscription.deleted",
        "data": {
            "object": {
                "id": subscription_id,
                "status": "canceled",
            }
        }
    }


def _make_payment_failed_event(customer_id: str, attempt: int = 1) -> dict:
    return {
        "type": "invoice.payment_failed",
        "data": {
            "object": {
                "customer": customer_id,
                "attempt_count": attempt,
            }
        }
    }


# ---------------------------------------------------------------------------
# Tests: Direct handler tests (no signature verification)
# ---------------------------------------------------------------------------

class TestCheckoutCompleted:

    def test_provisions_pro_key(self):
        result = _handle_checkout_completed({
            "customer": "cus_test_001",
            "customer_email": "test@example.com",
            "subscription": "sub_test_001",
        })
        assert result["action"] == "key_provisioned"
        assert result["tier"] == "pro"
        assert result["raw_key"].startswith("rn_live_")
        assert result["customer_email"] == "test@example.com"

    def test_key_linked_to_stripe(self):
        result = _handle_checkout_completed({
            "customer": "cus_test_002",
            "customer_email": "linked@example.com",
            "subscription": "sub_test_002",
        })
        key_id = result["key_id"]

        # Verify the link exists
        found = _find_key_by_customer("cus_test_002")
        assert found is not None
        assert found["key_id"] == key_id

        found2 = _find_key_by_subscription("sub_test_002")
        assert found2 is not None
        assert found2["key_id"] == key_id

    def test_duplicate_checkout_returns_existing(self):
        _handle_checkout_completed({
            "customer": "cus_test_003",
            "customer_email": "dup@example.com",
            "subscription": "sub_test_003",
        })
        result = _handle_checkout_completed({
            "customer": "cus_test_003",
            "customer_email": "dup@example.com",
            "subscription": "sub_test_003b",
        })
        assert result["action"] == "already_provisioned"


class TestPaymentSucceeded:

    def test_renewal_confirmed(self):
        # Set up a linked key
        key = create_key(tier="pro", owner="renew@test.com")
        _link_key_to_stripe(key["key_id"], "cus_renew", "sub_renew")

        result = _handle_payment_succeeded({
            "customer": "cus_renew",
            "subscription": "sub_renew",
        })
        assert result["action"] == "renewal_confirmed"
        assert result["key_id"] == key["key_id"]

    def test_renewal_no_key(self):
        result = _handle_payment_succeeded({
            "customer": "cus_unknown",
            "subscription": "sub_unknown",
        })
        assert result["action"] == "renewal_no_key_found"


class TestSubscriptionChange:

    def test_cancellation_downgrades_to_free(self):
        key = create_key(tier="pro", owner="cancel@test.com")
        _link_key_to_stripe(key["key_id"], "cus_cancel", "sub_cancel")

        result = _handle_subscription_change({
            "id": "sub_cancel",
            "status": "canceled",
        })
        assert result["action"] == "key_downgraded"
        assert result["new_tier"] == "free"

        # Verify the key is now free tier
        data = _load_keys()
        entry = next(e for e in data["keys"] if e["key_id"] == key["key_id"])
        assert entry["tier"] == "free"

    def test_active_update_keeps_pro(self):
        key = create_key(tier="pro", owner="update@test.com")
        _link_key_to_stripe(key["key_id"], "cus_update", "sub_update")

        result = _handle_subscription_change({
            "id": "sub_update",
            "status": "active",
        })
        assert result["action"] == "subscription_updated"

        # Key should still be pro
        data = _load_keys()
        entry = next(e for e in data["keys"] if e["key_id"] == key["key_id"])
        assert entry["tier"] == "pro"


class TestPaymentFailed:

    def test_logs_failure(self):
        result = _handle_payment_failed({
            "customer": "cus_fail",
            "attempt_count": 2,
        })
        assert result["action"] == "payment_failed"
        assert result["attempt_count"] == 2


class TestWebhookSignature:

    def test_valid_signature_accepted(self):
        """Test that handle_webhook accepts a properly signed payload."""
        event = _make_checkout_event("cus_sig_test", "sig@test.com", "sub_sig_test")
        payload, sig_header = _make_signed_payload(event)

        result = handle_webhook(payload, sig_header)
        # Should process successfully (not a signature error)
        assert "error" not in result or "signature" not in result.get("error", "").lower()

    def test_invalid_signature_rejected(self):
        """Test that handle_webhook rejects a bad signature."""
        event = _make_checkout_event("cus_bad", "bad@test.com", "sub_bad")
        payload = json.dumps(event).encode()
        bad_sig = "t=12345,v1=deadbeef"

        result = handle_webhook(payload, bad_sig)
        assert "error" in result

    def test_missing_webhook_secret(self):
        """Test behavior when webhook secret is not configured."""
        original = os.environ.get("STRIPE_WEBHOOK_SECRET")
        os.environ["STRIPE_WEBHOOK_SECRET"] = ""

        # Re-import to pick up empty config
        from stripe_billing import _load_stripe_config
        config = _load_stripe_config()

        # Directly test with empty secret
        from stripe_billing import STRIPE_CONFIG
        old_secret = STRIPE_CONFIG["webhook_secret"]
        STRIPE_CONFIG["webhook_secret"] = ""

        result = handle_webhook(b"{}", "")
        assert "error" in result

        # Restore
        STRIPE_CONFIG["webhook_secret"] = old_secret
        if original:
            os.environ["STRIPE_WEBHOOK_SECRET"] = original


class TestDowngradeKey:

    def test_downgrade_removes_stripe_link(self):
        key = create_key(tier="pro", owner="downgrade@test.com")
        _link_key_to_stripe(key["key_id"], "cus_dg", "sub_dg")

        _downgrade_key(key["key_id"])

        data = _load_keys()
        entry = next(e for e in data["keys"] if e["key_id"] == key["key_id"])
        assert entry["tier"] == "free"
        assert "stripe_customer_id" not in entry
        assert "stripe_subscription_id" not in entry


# ---------------------------------------------------------------------------
# Cleanup & CLI runner
# ---------------------------------------------------------------------------

def cleanup():
    # Restore auth.KEYS_FILE to prevent cross-test contamination
    _auth_module.KEYS_FILE = _orig_keys_file
    if _orig_home:
        os.environ["HOME"] = _orig_home
    elif "HOME" in os.environ:
        del os.environ["HOME"]
    shutil.rmtree(_tmpdir, ignore_errors=True)


if __name__ == "__main__":
    import traceback
    import atexit
    atexit.register(cleanup)

    test_classes = [
        TestCheckoutCompleted,
        TestPaymentSucceeded,
        TestSubscriptionChange,
        TestPaymentFailed,
        TestWebhookSignature,
        TestDowngradeKey,
    ]

    passed = 0
    failed = 0
    errors = []

    for cls in test_classes:
        instance = cls()
        methods = [m for m in dir(instance) if m.startswith("test_")]
        for method_name in sorted(methods):
            test_name = f"{cls.__name__}.{method_name}"
            try:
                getattr(instance, method_name)()
                print(f"  PASS  {test_name}")
                passed += 1
            except Exception as e:
                print(f"  FAIL  {test_name}: {e}")
                errors.append((test_name, traceback.format_exc()))
                failed += 1

    print(f"\n{'='*60}")
    print(f"Results: {passed} passed, {failed} failed, {passed + failed} total")

    if errors:
        print(f"\nFailures:")
        for name, tb in errors:
            print(f"\n--- {name} ---")
            print(tb)
        sys.exit(1)
    else:
        print("All tests passed.")
        sys.exit(0)
