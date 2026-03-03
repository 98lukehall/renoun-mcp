#!/usr/bin/env python3
"""
ReNoUn Stripe Billing Integration.

Handles:
  - Creating Stripe Checkout sessions for pro subscriptions
  - Processing webhook events (payment succeeded, subscription changes)
  - Auto-provisioning API keys on successful payment
  - Handling cancellations and downgrades

Setup:
  1. Create a Stripe account at https://stripe.com
  2. Create a Product ("ReNoUn Pro") with a $4.99/mo recurring Price
  3. Set up a webhook endpoint pointing to https://your-domain.com/v1/billing/webhook
  4. Add env vars: STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET, STRIPE_PRICE_ID

Usage:
    python3 stripe_billing.py setup   # Print setup checklist
    python3 stripe_billing.py status  # Check Stripe connection
"""

import os
import json
import argparse
from pathlib import Path
from typing import Optional

import stripe

from auth import create_key, revoke_key, list_keys, _load_keys, _save_keys, validate_key


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CONFIG_FILE = Path.home() / ".renoun" / "config.json"


def _load_stripe_config() -> dict:
    """Load Stripe config from env vars or config file."""
    file_config = {}
    if CONFIG_FILE.exists():
        try:
            file_config = json.loads(CONFIG_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass

    return {
        "secret_key": os.environ.get("STRIPE_SECRET_KEY", file_config.get("stripe_secret_key", "")),
        "webhook_secret": os.environ.get("STRIPE_WEBHOOK_SECRET", file_config.get("stripe_webhook_secret", "")),
        "price_id": os.environ.get("STRIPE_PRICE_ID", file_config.get("stripe_price_id", "")),
        "success_url": os.environ.get("STRIPE_SUCCESS_URL", file_config.get("stripe_success_url", "https://renoun.dev/welcome?session_id={CHECKOUT_SESSION_ID}")),
        "cancel_url": os.environ.get("STRIPE_CANCEL_URL", file_config.get("stripe_cancel_url", "https://renoun.dev/pricing")),
    }


STRIPE_CONFIG = _load_stripe_config()

if STRIPE_CONFIG["secret_key"]:
    stripe.api_key = STRIPE_CONFIG["secret_key"]


# ---------------------------------------------------------------------------
# Customer ↔ Key Mapping
# ---------------------------------------------------------------------------
# Stored in ~/.renoun/api_keys.json alongside the key entries.
# Each key entry gets a "stripe_customer_id" and "stripe_subscription_id" field.

def _link_key_to_stripe(key_id: str, customer_id: str, subscription_id: str):
    """Link a ReNoUn API key to a Stripe customer and subscription."""
    data = _load_keys()
    for entry in data["keys"]:
        if entry["key_id"] == key_id:
            entry["stripe_customer_id"] = customer_id
            entry["stripe_subscription_id"] = subscription_id
            break
    _save_keys(data)


def _find_key_by_customer(customer_id: str) -> Optional[dict]:
    """Find an active API key linked to a Stripe customer."""
    data = _load_keys()
    for entry in data["keys"]:
        if entry.get("stripe_customer_id") == customer_id and entry["active"]:
            return entry
    return None


def _find_key_by_subscription(subscription_id: str) -> Optional[dict]:
    """Find an active API key linked to a Stripe subscription."""
    data = _load_keys()
    for entry in data["keys"]:
        if entry.get("stripe_subscription_id") == subscription_id and entry["active"]:
            return entry
    return None


def _downgrade_key(key_id: str):
    """Downgrade a key from pro to free tier."""
    data = _load_keys()
    for entry in data["keys"]:
        if entry["key_id"] == key_id:
            entry["tier"] = "free"
            entry.pop("stripe_customer_id", None)
            entry.pop("stripe_subscription_id", None)
            break
    _save_keys(data)


# ---------------------------------------------------------------------------
# Checkout Session
# ---------------------------------------------------------------------------

def create_checkout_session(customer_email: str, metadata: Optional[dict] = None) -> dict:
    """Create a Stripe Checkout session for a pro subscription.

    Returns dict with checkout_url and session_id.
    """
    if not STRIPE_CONFIG["secret_key"]:
        return {"error": "Stripe not configured. Set STRIPE_SECRET_KEY."}
    if not STRIPE_CONFIG["price_id"]:
        return {"error": "Stripe Price ID not configured. Set STRIPE_PRICE_ID."}

    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            payment_method_types=["card"],
            customer_email=customer_email,
            line_items=[{
                "price": STRIPE_CONFIG["price_id"],
                "quantity": 1,
            }],
            success_url=STRIPE_CONFIG["success_url"],
            cancel_url=STRIPE_CONFIG["cancel_url"],
            metadata=metadata or {},
        )
        return {
            "checkout_url": session.url,
            "session_id": session.id,
        }
    except stripe.StripeError as e:
        return {"error": f"Stripe error: {str(e)}"}


# ---------------------------------------------------------------------------
# Webhook Handler
# ---------------------------------------------------------------------------

def handle_webhook(payload: bytes, sig_header: str) -> dict:
    """Process a Stripe webhook event.

    Args:
        payload: Raw request body bytes
        sig_header: Stripe-Signature header value

    Returns:
        dict with action taken and details
    """
    if not STRIPE_CONFIG["webhook_secret"]:
        return {"error": "Webhook secret not configured. Set STRIPE_WEBHOOK_SECRET."}

    # Verify signature
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_CONFIG["webhook_secret"]
        )
    except stripe.SignatureVerificationError:
        return {"error": "Invalid webhook signature.", "status": 400}
    except ValueError:
        return {"error": "Invalid payload.", "status": 400}

    event_type = event["type"]
    data = event["data"]["object"]

    # ---- Checkout completed: provision API key ----
    if event_type == "checkout.session.completed":
        return _handle_checkout_completed(data)

    # ---- Subscription payment succeeded (renewal) ----
    elif event_type == "invoice.payment_succeeded":
        return _handle_payment_succeeded(data)

    # ---- Subscription cancelled or expired ----
    elif event_type in ("customer.subscription.deleted", "customer.subscription.updated"):
        return _handle_subscription_change(data)

    # ---- Payment failed ----
    elif event_type == "invoice.payment_failed":
        return _handle_payment_failed(data)

    return {"action": "ignored", "event_type": event_type}


def _handle_checkout_completed(session: dict) -> dict:
    """New subscription: create a pro API key and link it to the customer."""
    customer_id = session.get("customer", "")
    customer_email = session.get("customer_email", session.get("customer_details", {}).get("email", ""))
    subscription_id = session.get("subscription", "")

    # Check if customer already has an active key
    existing = _find_key_by_customer(customer_id)
    if existing:
        return {
            "action": "already_provisioned",
            "key_id": existing["key_id"],
            "customer_id": customer_id,
        }

    # Create new pro key
    result = create_key(tier="pro", owner=customer_email)
    key_id = result["key_id"]

    # Link to Stripe
    _link_key_to_stripe(key_id, customer_id, subscription_id)

    return {
        "action": "key_provisioned",
        "key_id": key_id,
        "tier": "pro",
        "customer_id": customer_id,
        "customer_email": customer_email,
        "note": "API key created. Deliver raw_key to customer via email or success page.",
        "raw_key": result["raw_key"],
    }


def _handle_payment_succeeded(invoice: dict) -> dict:
    """Subscription renewal: confirm key is still active."""
    customer_id = invoice.get("customer", "")
    subscription_id = invoice.get("subscription", "")

    existing = _find_key_by_subscription(subscription_id)
    if existing:
        return {
            "action": "renewal_confirmed",
            "key_id": existing["key_id"],
            "customer_id": customer_id,
        }

    return {"action": "renewal_no_key_found", "customer_id": customer_id}


def _handle_subscription_change(subscription: dict) -> dict:
    """Subscription cancelled or changed: downgrade or revoke key."""
    subscription_id = subscription.get("id", "")
    status = subscription.get("status", "")

    existing = _find_key_by_subscription(subscription_id)
    if not existing:
        return {"action": "subscription_change_no_key_found", "subscription_id": subscription_id}

    key_id = existing["key_id"]

    # If cancelled or unpaid, downgrade to free
    if status in ("canceled", "unpaid", "past_due", "incomplete_expired"):
        _downgrade_key(key_id)
        return {
            "action": "key_downgraded",
            "key_id": key_id,
            "new_tier": "free",
            "reason": status,
        }

    # Active subscription update (e.g., plan change) — keep pro
    return {
        "action": "subscription_updated",
        "key_id": key_id,
        "status": status,
    }


def _handle_payment_failed(invoice: dict) -> dict:
    """Payment failed: log it, Stripe handles retries."""
    customer_id = invoice.get("customer", "")
    attempt_count = invoice.get("attempt_count", 0)

    return {
        "action": "payment_failed",
        "customer_id": customer_id,
        "attempt_count": attempt_count,
        "note": "Stripe will retry automatically. Key stays active until subscription is cancelled.",
    }


# ---------------------------------------------------------------------------
# Customer Portal
# ---------------------------------------------------------------------------

def create_portal_session(customer_id: str, return_url: str = "") -> dict:
    """Create a Stripe Customer Portal session for subscription management.

    Lets customers update payment method, cancel, or view invoices.
    """
    if not STRIPE_CONFIG["secret_key"]:
        return {"error": "Stripe not configured."}

    if not return_url:
        return_url = STRIPE_CONFIG.get("success_url", "https://renoun.dev")

    try:
        session = stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url=return_url,
        )
        return {"portal_url": session.url}
    except stripe.StripeError as e:
        return {"error": f"Stripe error: {str(e)}"}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="ReNoUn Stripe Billing")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("setup", help="Print Stripe setup checklist")
    sub.add_parser("status", help="Check Stripe connection")

    args = parser.parse_args()

    if args.command == "setup":
        print("""
ReNoUn Stripe Setup Checklist
==============================

1. Create a Stripe account: https://stripe.com

2. In Stripe Dashboard, create a Product:
   - Name: "ReNoUn Pro"
   - Price: $4.99/month (recurring)
   - Copy the Price ID (starts with price_...)

3. Set up a Webhook endpoint:
   - URL: https://your-domain.com/v1/billing/webhook
   - Events to listen for:
     * checkout.session.completed
     * invoice.payment_succeeded
     * invoice.payment_failed
     * customer.subscription.deleted
     * customer.subscription.updated
   - Copy the Webhook Signing Secret (starts with whsec_...)

4. Set environment variables:
   export STRIPE_SECRET_KEY="sk_live_..."
   export STRIPE_WEBHOOK_SECRET="whsec_..."
   export STRIPE_PRICE_ID="price_..."

   Or add to ~/.renoun/config.json:
   {
       "stripe_secret_key": "sk_live_...",
       "stripe_webhook_secret": "whsec_...",
       "stripe_price_id": "price_..."
   }

5. Start the API server:
   python3 api.py

6. Test with Stripe CLI (dev):
   stripe listen --forward-to localhost:8080/v1/billing/webhook
   stripe trigger checkout.session.completed
""")

    elif args.command == "status":
        config = _load_stripe_config()
        print(f"\nStripe Configuration Status")
        print(f"  Secret Key:     {'configured' if config['secret_key'] else 'MISSING'}")
        print(f"  Webhook Secret: {'configured' if config['webhook_secret'] else 'MISSING'}")
        print(f"  Price ID:       {config['price_id'] or 'MISSING'}")
        print(f"  Success URL:    {config['success_url']}")
        print(f"  Cancel URL:     {config['cancel_url']}")

        if config["secret_key"]:
            try:
                stripe.api_key = config["secret_key"]
                account = stripe.Account.retrieve()
                print(f"  Account:        {account.get('business_profile', {}).get('name', account.get('id', 'connected'))}")
                print(f"  Status:         CONNECTED")
            except stripe.StripeError as e:
                print(f"  Status:         ERROR — {e}")
        else:
            print(f"  Status:         NOT CONFIGURED")
        print()

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
