#!/usr/bin/env python3
"""
ReNoUn Email Sender.

Sends transactional emails (API key delivery, welcome, etc.)
using Resend (https://resend.com) — free tier: 100 emails/day.

Setup:
    1. Sign up at https://resend.com
    2. Verify your domain or use the sandbox (onboarding@resend.dev)
    3. Create an API key at https://resend.com/api-keys
    4. Set env var: RESEND_API_KEY="re_..."

    Optional: RESEND_FROM_EMAIL (default: "ReNoUn <noreply@harrisoncollab.com>")

Falls back gracefully: if Resend is not configured, emails are skipped
and logged to console instead.
"""

import os
import json
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CONFIG_FILE = Path.home() / ".renoun" / "config.json"


def _load_email_config() -> dict:
    file_config = {}
    if CONFIG_FILE.exists():
        try:
            file_config = json.loads(CONFIG_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass

    return {
        "api_key": os.environ.get("RESEND_API_KEY", file_config.get("resend_api_key", "")),
        "from_email": os.environ.get("RESEND_FROM_EMAIL", file_config.get("resend_from_email", "ReNoUn <noreply@harrisoncollab.com>")),
    }


EMAIL_CONFIG = _load_email_config()


def is_email_configured() -> bool:
    """Check if email sending is configured."""
    return bool(EMAIL_CONFIG["api_key"])


# ---------------------------------------------------------------------------
# Send via Resend API (stdlib only — no extra dependencies)
# ---------------------------------------------------------------------------

def _send_resend(to: str, subject: str, html: str) -> dict:
    """Send an email via Resend API using urllib (no dependencies)."""
    payload = json.dumps({
        "from": EMAIL_CONFIG["from_email"],
        "to": [to],
        "subject": subject,
        "html": html,
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=payload,
        headers={
            "Authorization": f"Bearer {EMAIL_CONFIG['api_key']}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode())
            return {"success": True, "id": result.get("id", "")}
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        return {"success": False, "error": f"HTTP {e.code}: {body}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Email Templates
# ---------------------------------------------------------------------------

def _welcome_email_html(raw_key: str, tier: str) -> str:
    """Generate the welcome email HTML with API key."""
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#FFFFF0;font-family:'Inter',-apple-system,Helvetica,Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#FFFFF0;padding:40px 20px;">
<tr><td align="center">
<table width="560" cellpadding="0" cellspacing="0" style="background:#FFFFFF;border-radius:12px;border:1px solid #E8E5DC;overflow:hidden;">

<!-- Header -->
<tr><td style="background:#0B1D3A;padding:32px 40px;text-align:center;">
  <h1 style="margin:0;color:#FFFFF0;font-size:24px;font-weight:700;letter-spacing:-0.02em;">ReNoUn</h1>
  <p style="margin:8px 0 0;color:#8B92A0;font-size:14px;">Structural Observability for AI Conversations</p>
</td></tr>

<!-- Body -->
<tr><td style="padding:40px;">
  <h2 style="margin:0 0 16px;color:#0B1D3A;font-size:20px;font-weight:600;">Welcome to ReNoUn Pro</h2>
  <p style="margin:0 0 24px;color:#4A5568;font-size:15px;line-height:1.6;">
    Your subscription is active. Here's your API key — store it securely, as it cannot be recovered.
  </p>

  <!-- API Key Box -->
  <div style="background:#F8F7F0;border:1px solid #E8E5DC;border-radius:8px;padding:16px 20px;margin:0 0 24px;">
    <p style="margin:0 0 6px;color:#8B92A0;font-size:12px;font-weight:500;text-transform:uppercase;letter-spacing:0.05em;">Your API Key</p>
    <code style="font-family:'JetBrains Mono',Consolas,monospace;font-size:13px;color:#0B1D3A;word-break:break-all;line-height:1.5;">{raw_key}</code>
  </div>

  <!-- Tier Info -->
  <div style="background:#F0F7ED;border:1px solid #D4E5CC;border-radius:8px;padding:16px 20px;margin:0 0 24px;">
    <p style="margin:0;color:#4A5568;font-size:14px;">
      <strong style="color:#7C9A6E;">&#10003; {tier.title()} Tier</strong> &mdash;
      Full access to analyze, health_check, compare, and pattern_query.
      1,000 requests/day, up to 500 turns per analysis.
    </p>
  </div>

  <!-- Quick Start -->
  <h3 style="margin:0 0 12px;color:#0B1D3A;font-size:16px;font-weight:600;">Quick Start</h3>
  <div style="background:#1a1a2e;border-radius:8px;padding:16px 20px;margin:0 0 24px;overflow-x:auto;">
    <pre style="margin:0;color:#e0e0e0;font-family:'JetBrains Mono',Consolas,monospace;font-size:12px;line-height:1.6;white-space:pre-wrap;">curl -X POST https://web-production-817e2.up.railway.app/v1/health-check \\
  -H "Authorization: Bearer {raw_key}" \\
  -H "Content-Type: application/json" \\
  -d '{{"utterances": [
    {{"speaker": "user", "text": "Hello"}},
    {{"speaker": "assistant", "text": "Hi there"}},
    {{"speaker": "user", "text": "How are you?"}}
  ]}}'</pre>
  </div>

  <p style="margin:0 0 8px;color:#4A5568;font-size:14px;">
    <strong>API Docs:</strong> <a href="https://web-production-817e2.up.railway.app/docs" style="color:#7C9A6E;">Interactive API Explorer</a>
  </p>
  <p style="margin:0;color:#4A5568;font-size:14px;">
    <strong>MCP Server:</strong> <code style="font-family:'JetBrains Mono',Consolas,monospace;font-size:12px;">pip install renoun-mcp</code>
  </p>
</td></tr>

<!-- Footer -->
<tr><td style="padding:24px 40px;border-top:1px solid #E8E5DC;text-align:center;">
  <p style="margin:0;color:#8B92A0;font-size:12px;">
    Harrison Collab &bull; <a href="https://harrisoncollab.com" style="color:#7C9A6E;">harrisoncollab.com</a>
    <br>Patent Pending #63/923,592
  </p>
</td></tr>

</table>
</td></tr>
</table>
</body>
</html>"""


def _agent_welcome_email_html(raw_key: str) -> str:
    """Generate the welcome email HTML for a free agent API key."""
    return """<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#0B1D3A;font-family:'Inter',-apple-system,Helvetica,Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#0B1D3A;padding:40px 20px;">
<tr><td align="center">
<table width="560" cellpadding="0" cellspacing="0" style="background:#0F2847;border-radius:12px;border:1px solid #1A3A5C;overflow:hidden;">

<!-- Header -->
<tr><td style="background:#0B1D3A;padding:32px 40px;text-align:center;border-bottom:1px solid #1A3A5C;">
  <h1 style="margin:0;color:#FFFFF0;font-size:24px;font-weight:700;letter-spacing:-0.02em;">ReNoUn</h1>
  <p style="margin:8px 0 0;color:#8B92A0;font-size:14px;">Structural Regime Classifier for Crypto Markets</p>
</td></tr>

<!-- Body -->
<tr><td style="padding:40px;">
  <h2 style="margin:0 0 16px;color:#FFFFF0;font-size:20px;font-weight:600;">Your free API key is ready</h2>
  <p style="margin:0 0 24px;color:#A0AEC0;font-size:15px;line-height:1.6;">
    You have <strong style="color:#FFFFF0;">50 free calls per day</strong> — no credit card required. Call the regime endpoint before any trade to know if conditions are bounded, active, or unstable.
  </p>

  <!-- API Key Box -->
  <div style="background:#162D4A;border:1px solid #1A3A5C;border-radius:8px;padding:16px 20px;margin:0 0 24px;">
    <p style="margin:0 0 6px;color:#8B92A0;font-size:12px;font-weight:500;text-transform:uppercase;letter-spacing:0.05em;">Your API Key</p>
    <code style="font-family:'JetBrains Mono',Consolas,monospace;font-size:13px;color:#7CDB8A;word-break:break-all;line-height:1.5;">""" + raw_key + """</code>
  </div>

  <p style="margin:0 0 8px;color:#A0AEC0;font-size:14px;">
    <strong style="color:#FFFFF0;">Store this key securely</strong> — it cannot be recovered.
  </p>

  <!-- Free Tier Info -->
  <div style="background:#162D4A;border:1px solid #1A3A5C;border-radius:8px;padding:16px 20px;margin:24px 0;">
    <p style="margin:0;color:#A0AEC0;font-size:14px;line-height:1.6;">
      <strong style="color:#7CDB8A;">&#10003; Free Tier</strong> — 50 calls/day<br>
      <strong style="color:#FFD700;">&#9889; Need more?</strong> — $0.02/call beyond free tier. We'll email you when you hit 50 calls so you can add a payment method.
    </p>
  </div>

  <!-- Quick Start -->
  <h3 style="margin:0 0 12px;color:#FFFFF0;font-size:16px;font-weight:600;">Quick Start</h3>
  <div style="background:#0B1D3A;border-radius:8px;padding:16px 20px;margin:0 0 24px;overflow-x:auto;">
    <pre style="margin:0;color:#e0e0e0;font-family:'JetBrains Mono',Consolas,monospace;font-size:12px;line-height:1.6;white-space:pre-wrap;">curl -H "Authorization: Bearer """ + raw_key + """" \\
  https://web-production-817e2.up.railway.app/v1/regime/live/BTCUSDT</pre>
  </div>

  <p style="margin:0 0 8px;color:#A0AEC0;font-size:14px;">
    <strong>Docs:</strong> <a href="https://harrisoncollab.com/agents" style="color:#7CDB8A;">harrisoncollab.com/agents</a>
  </p>
  <p style="margin:0;color:#A0AEC0;font-size:14px;">
    <strong>Dashboard:</strong> <a href="https://harrisoncollab.com/dashboard" style="color:#7CDB8A;">harrisoncollab.com/dashboard</a>
  </p>
</td></tr>

<!-- Footer -->
<tr><td style="padding:24px 40px;border-top:1px solid #1A3A5C;text-align:center;">
  <p style="margin:0;color:#8B92A0;font-size:12px;">
    Harrison Collab &bull; <a href="https://harrisoncollab.com" style="color:#7CDB8A;">harrisoncollab.com</a>
    <br>No other crypto signal service grades every prediction publicly.
  </p>
</td></tr>

</table>
</td></tr>
</table>
</body>
</html>"""


def _approaching_limit_email_html(email: str, daily_total: int, billing_url: str) -> str:
    """Generate the 40-call warning email HTML."""
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#0B1D3A;font-family:'Inter',-apple-system,Helvetica,Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#0B1D3A;padding:40px 20px;">
<tr><td align="center">
<table width="560" cellpadding="0" cellspacing="0" style="background:#0F2847;border-radius:12px;border:1px solid #1A3A5C;overflow:hidden;">

<!-- Header -->
<tr><td style="background:#0B1D3A;padding:24px 40px;text-align:center;border-bottom:1px solid #1A3A5C;">
  <h1 style="margin:0;color:#FFFFF0;font-size:22px;font-weight:700;">ReNoUn</h1>
</td></tr>

<!-- Body -->
<tr><td style="padding:40px;">
  <h2 style="margin:0 0 16px;color:#FFD700;font-size:20px;font-weight:600;">&#9889; Free daily limit reached</h2>
  <p style="margin:0 0 24px;color:#A0AEC0;font-size:15px;line-height:1.6;">
    You've used all {daily_total} free calls for today. To keep calling without interruption, add a payment method now. Beyond 50 calls, each call is just <strong style="color:#FFFFF0;">$0.02</strong>.
  </p>

  <!-- CTA -->
  <div style="text-align:center;margin:32px 0;">
    <a href="{billing_url}" style="display:inline-block;background:#7CDB8A;color:#0B1D3A;padding:14px 32px;border-radius:8px;font-size:16px;font-weight:700;text-decoration:none;">Add Payment Method</a>
  </div>

  <p style="margin:0;color:#8B92A0;font-size:13px;text-align:center;">
    You won't be charged anything until you exceed 50 calls in a day.<br>
    If you don't add a payment method, calls will stop at 50.
  </p>
</td></tr>

<!-- Footer -->
<tr><td style="padding:24px 40px;border-top:1px solid #1A3A5C;text-align:center;">
  <p style="margin:0;color:#8B92A0;font-size:12px;">
    Harrison Collab &bull; <a href="https://harrisoncollab.com" style="color:#7CDB8A;">harrisoncollab.com</a>
  </p>
</td></tr>

</table>
</td></tr>
</table>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def send_agent_welcome_email(to: str, raw_key: str) -> dict:
    """Send welcome email with free agent API key.

    Returns dict with success status. Falls back to console logging
    if email is not configured.
    """
    if not is_email_configured():
        print(f"[email] Resend not configured. Would send agent welcome email to {to}")
        print(f"[email] API key: {raw_key[:20]}...")
        return {"success": False, "reason": "email_not_configured"}

    html = _agent_welcome_email_html(raw_key)
    result = _send_resend(
        to=to,
        subject="Your ReNoUn API Key — 50 free calls/day",
        html=html,
    )

    if result["success"]:
        print(f"[email] Agent welcome email sent to {to} (id: {result['id']})")
    else:
        print(f"[email] Failed to send agent welcome to {to}: {result['error']}")

    return result


def send_limit_reached_email(to: str, daily_total: int, billing_url: str = "https://harrisoncollab.com/billing") -> dict:
    """Send the 50-call limit-reached email with Stripe billing link.

    Returns dict with success status.
    """
    if not is_email_configured():
        print(f"[email] Resend not configured. Would send limit-reached email to {to} ({daily_total}/50)")
        return {"success": False, "reason": "email_not_configured"}

    html = _approaching_limit_email_html(to, daily_total, billing_url)
    result = _send_resend(
        to=to,
        subject="ReNoUn: Free daily limit reached — add payment to continue",
        html=html,
    )

    if result["success"]:
        print(f"[email] Limit-reached email sent to {to} (id: {result['id']})")
    else:
        print(f"[email] Failed to send limit-reached email to {to}: {result['error']}")

    return result


def send_welcome_email(to: str, raw_key: str, tier: str = "pro") -> dict:
    """Send the welcome email with API key to a new subscriber.

    Returns dict with success status. Falls back to console logging
    if email is not configured.
    """
    if not is_email_configured():
        print(f"[email] Resend not configured. Would send welcome email to {to}")
        print(f"[email] API key: {raw_key[:20]}...")
        return {"success": False, "reason": "email_not_configured"}

    html = _welcome_email_html(raw_key, tier)
    result = _send_resend(
        to=to,
        subject="Your ReNoUn Pro API Key",
        html=html,
    )

    if result["success"]:
        print(f"[email] Welcome email sent to {to} (id: {result['id']})")
    else:
        print(f"[email] Failed to send to {to}: {result['error']}")

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    import argparse
    parser = argparse.ArgumentParser(description="ReNoUn Email Sender")
    sub = parser.add_subparsers(dest="command")

    test_cmd = sub.add_parser("test", help="Send a test welcome email")
    test_cmd.add_argument("--to", required=True, help="Recipient email")
    test_cmd.add_argument("--key", default="rn_live_test1234567890abcdef1234567890abcdef12345678", help="Test API key")

    sub.add_parser("status", help="Check email configuration")

    args = parser.parse_args()

    if args.command == "test":
        result = send_welcome_email(to=args.to, raw_key=args.key)
        print(json.dumps(result, indent=2))

    elif args.command == "status":
        config = _load_email_config()
        print(f"\nEmail Configuration")
        print(f"  Resend API Key: {'configured' if config['api_key'] else 'MISSING'}")
        print(f"  From Email:     {config['from_email']}")
        print(f"  Status:         {'READY' if config['api_key'] else 'NOT CONFIGURED'}")
        print()

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
