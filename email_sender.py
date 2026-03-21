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

def _metered_billing_email_html(raw_key: str) -> str:
    """Generate the metered billing confirmation email HTML."""
    return f"""<!DOCTYPE html>
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
  <h2 style="margin:0 0 16px;color:#FFFFF0;font-size:20px;font-weight:600;">Metered billing active</h2>
  <p style="margin:0 0 24px;color:#A0AEC0;font-size:15px;line-height:1.6;">
    Your payment method has been added. Calls beyond 50/day are now billed at <strong style="color:#FFFFF0;">$0.02 each</strong>, invoiced monthly via Stripe.
  </p>

  <!-- Billing Info -->
  <div style="background:#162D4A;border:1px solid #1A3A5C;border-radius:8px;padding:16px 20px;margin:0 0 24px;">
    <p style="margin:0;color:#A0AEC0;font-size:14px;line-height:1.6;">
      <strong style="color:#7CDB8A;">&#10003; 50 free calls/day</strong> — always included<br>
      <strong style="color:#7CDB8A;">&#10003; $0.02/call</strong> — beyond free tier<br>
      <strong style="color:#7CDB8A;">&#10003; Cancel anytime</strong> — reverts to free tier
    </p>
  </div>

  <!-- Quick Start -->
  <h3 style="margin:0 0 12px;color:#FFFFF0;font-size:16px;font-weight:600;">Quick Start</h3>
  <div style="background:#0B1D3A;border-radius:8px;padding:16px 20px;margin:0 0 24px;overflow-x:auto;">
    <pre style="margin:0;color:#e0e0e0;font-family:'JetBrains Mono',Consolas,monospace;font-size:12px;line-height:1.6;white-space:pre-wrap;">curl -H "Authorization: Bearer {raw_key}" \\
  https://api.harrisoncollab.com/v1/regime/live/BTCUSDT</pre>
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
  https://api.harrisoncollab.com/v1/regime/live/BTCUSDT</pre>
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


def send_metered_billing_email(to: str, raw_key: str) -> dict:
    """Send confirmation email when metered billing is activated.

    Returns dict with success status. Falls back to console logging
    if email is not configured.
    """
    if not is_email_configured():
        print(f"[email] Resend not configured. Would send metered billing email to {to}")
        print(f"[email] API key: {raw_key[:20]}...")
        return {"success": False, "reason": "email_not_configured"}

    html = _metered_billing_email_html(raw_key)
    result = _send_resend(
        to=to,
        subject="ReNoUn — Metered billing active",
        html=html,
    )

    if result["success"]:
        print(f"[email] Metered billing email sent to {to} (id: {result['id']})")
    else:
        print(f"[email] Failed to send to {to}: {result['error']}")

    return result


# ---------------------------------------------------------------------------
# Drip Email Templates (Onboarding Sequence)
# ---------------------------------------------------------------------------

_DRIP_DARK_HEADER = """<!DOCTYPE html>
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
</td></tr>"""

_DRIP_DARK_FOOTER = """
<!-- Footer -->
<tr><td style="padding:24px 40px;border-top:1px solid #1A3A5C;text-align:center;">
  <p style="margin:0;color:#8B92A0;font-size:12px;">
    Harrison Collab &bull; <a href="https://harrisoncollab.com" style="color:#7CDB8A;">harrisoncollab.com</a>
    <br>Patent Pending #63/923,592
  </p>
</td></tr>

</table>
</td></tr>
</table>
</body>
</html>"""


def _drip_email_1_html(api_key: str) -> str:
    """Drip email 1: 'Your ReNoUn API Key' — sent immediately on provision.

    Shows the key, a copy-paste curl command, response field explanations,
    and the stoplight regime metaphor.
    """
    return _DRIP_DARK_HEADER + f"""

<!-- Body -->
<tr><td style="padding:40px;">
  <h2 style="margin:0 0 16px;color:#FFFFF0;font-size:20px;font-weight:600;">Your ReNoUn API Key</h2>
  <p style="margin:0 0 24px;color:#A0AEC0;font-size:15px;line-height:1.6;">
    You have <strong style="color:#FFFFF0;">50 free calls per day</strong> — no credit card required.
    Call the regime endpoint before any trade to know whether conditions are bounded, active, or unstable.
  </p>

  <!-- API Key Box -->
  <div style="background:#162D4A;border:1px solid #1A3A5C;border-radius:8px;padding:16px 20px;margin:0 0 24px;">
    <p style="margin:0 0 6px;color:#8B92A0;font-size:12px;font-weight:500;text-transform:uppercase;letter-spacing:0.05em;">Your API Key</p>
    <code style="font-family:'JetBrains Mono',Consolas,monospace;font-size:13px;color:#7CDB8A;word-break:break-all;line-height:1.5;">{api_key}</code>
  </div>

  <p style="margin:0 0 24px;color:#A0AEC0;font-size:14px;">
    <strong style="color:#FFFFF0;">Store this key securely</strong> — it cannot be recovered.
  </p>

  <!-- Try It Now -->
  <h3 style="margin:0 0 12px;color:#FFFFF0;font-size:16px;font-weight:600;">Try it right now</h3>
  <p style="margin:0 0 12px;color:#A0AEC0;font-size:14px;line-height:1.6;">
    Copy-paste this into your terminal:
  </p>
  <div style="background:#0B1D3A;border-radius:8px;padding:16px 20px;margin:0 0 24px;overflow-x:auto;">
    <pre style="margin:0;color:#e0e0e0;font-family:'JetBrains Mono',Consolas,monospace;font-size:12px;line-height:1.6;white-space:pre-wrap;">curl -H "Authorization: Bearer {api_key}" \\
  https://api.harrisoncollab.com/v1/regime/live/BTCUSDT</pre>
  </div>

  <!-- Response Fields -->
  <h3 style="margin:0 0 12px;color:#FFFFF0;font-size:16px;font-weight:600;">What the response means</h3>
  <table width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 24px;">
    <tr>
      <td style="padding:8px 12px;color:#7CDB8A;font-family:'JetBrains Mono',Consolas,monospace;font-size:13px;font-weight:600;border-bottom:1px solid #1A3A5C;width:140px;">regime</td>
      <td style="padding:8px 12px;color:#A0AEC0;font-size:14px;border-bottom:1px solid #1A3A5C;">Current structural state: <em>bounded</em>, <em>active</em>, or <em>unstable</em></td>
    </tr>
    <tr>
      <td style="padding:8px 12px;color:#7CDB8A;font-family:'JetBrains Mono',Consolas,monospace;font-size:13px;font-weight:600;border-bottom:1px solid #1A3A5C;">action</td>
      <td style="padding:8px 12px;color:#A0AEC0;font-size:14px;border-bottom:1px solid #1A3A5C;">What to do: <em>proceed</em>, <em>reduce</em>, or <em>avoid</em></td>
    </tr>
    <tr>
      <td style="padding:8px 12px;color:#7CDB8A;font-family:'JetBrains Mono',Consolas,monospace;font-size:13px;font-weight:600;border-bottom:1px solid #1A3A5C;">exposure_scalar</td>
      <td style="padding:8px 12px;color:#A0AEC0;font-size:14px;border-bottom:1px solid #1A3A5C;">Position sizing multiplier (1.0 = full, 0.5 = half, 0.0 = flat)</td>
    </tr>
    <tr>
      <td style="padding:8px 12px;color:#7CDB8A;font-family:'JetBrains Mono',Consolas,monospace;font-size:13px;font-weight:600;">dhs</td>
      <td style="padding:8px 12px;color:#A0AEC0;font-size:14px;">Dialogue Health Score (0.0&ndash;1.0) &mdash; overall structural quality</td>
    </tr>
  </table>

  <!-- Stoplight -->
  <h3 style="margin:0 0 12px;color:#FFFFF0;font-size:16px;font-weight:600;">The stoplight</h3>
  <table width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 24px;">
    <tr>
      <td style="padding:10px 16px;border-radius:6px 6px 0 0;background:#162D4A;border-bottom:1px solid #1A3A5C;">
        <span style="display:inline-block;width:14px;height:14px;border-radius:50%;background:#7CDB8A;vertical-align:middle;margin-right:10px;"></span>
        <strong style="color:#7CDB8A;font-size:14px;">Bounded &rarr; Proceed</strong>
        <p style="margin:4px 0 0 24px;color:#A0AEC0;font-size:13px;">Structural patterns are stable. Normal position sizing.</p>
      </td>
    </tr>
    <tr>
      <td style="padding:10px 16px;background:#162D4A;border-bottom:1px solid #1A3A5C;">
        <span style="display:inline-block;width:14px;height:14px;border-radius:50%;background:#FFD700;vertical-align:middle;margin-right:10px;"></span>
        <strong style="color:#FFD700;font-size:14px;">Active &rarr; Reduce</strong>
        <p style="margin:4px 0 0 24px;color:#A0AEC0;font-size:13px;">Transitional regime. Cut exposure 50%.</p>
      </td>
    </tr>
    <tr>
      <td style="padding:10px 16px;border-radius:0 0 6px 6px;background:#162D4A;">
        <span style="display:inline-block;width:14px;height:14px;border-radius:50%;background:#FF5555;vertical-align:middle;margin-right:10px;"></span>
        <strong style="color:#FF5555;font-size:14px;">Unstable &rarr; Avoid</strong>
        <p style="margin:4px 0 0 24px;color:#A0AEC0;font-size:13px;">Structural breakdown detected. Go flat or don&rsquo;t enter.</p>
      </td>
    </tr>
  </table>

  <p style="margin:0;color:#A0AEC0;font-size:14px;">
    <strong>Docs:</strong> <a href="https://harrisoncollab.com/agents" style="color:#7CDB8A;">harrisoncollab.com/agents</a>
    &nbsp;&bull;&nbsp;
    <strong>Dashboard:</strong> <a href="https://harrisoncollab.com/dashboard" style="color:#7CDB8A;">harrisoncollab.com/dashboard</a>
  </p>
</td></tr>""" + _DRIP_DARK_FOOTER


def _drip_email_2_html(api_key: str) -> str:
    """Drip email 2: 'Wire ReNoUn into your stack' — sent day 2.

    Integration guides for LangChain, FreqTrade, raw API batch endpoint, and MCP.
    """
    return _DRIP_DARK_HEADER + f"""

<!-- Body -->
<tr><td style="padding:40px;">
  <h2 style="margin:0 0 16px;color:#FFFFF0;font-size:20px;font-weight:600;">Wire ReNoUn into your stack</h2>
  <p style="margin:0 0 24px;color:#A0AEC0;font-size:15px;line-height:1.6;">
    Your API key is live. Here are four ways to integrate regime-aware risk gating into your workflow.
  </p>

  <!-- LangChain -->
  <div style="background:#162D4A;border:1px solid #1A3A5C;border-radius:8px;padding:20px;margin:0 0 20px;">
    <h3 style="margin:0 0 10px;color:#7CDB8A;font-size:15px;font-weight:600;">1. LangChain</h3>
    <div style="background:#0B1D3A;border-radius:6px;padding:14px 16px;overflow-x:auto;">
      <pre style="margin:0;color:#e0e0e0;font-family:'JetBrains Mono',Consolas,monospace;font-size:12px;line-height:1.6;white-space:pre-wrap;">pip install langchain-renoun</pre>
    </div>
    <div style="background:#0B1D3A;border-radius:6px;padding:14px 16px;margin-top:8px;overflow-x:auto;">
      <pre style="margin:0;color:#e0e0e0;font-family:'JetBrains Mono',Consolas,monospace;font-size:12px;line-height:1.6;white-space:pre-wrap;">from langchain_renoun import ReNoUnRegimeTool

tool = ReNoUnRegimeTool(api_key="{api_key}")
result = tool.invoke("BTCUSDT")</pre>
    </div>
    <p style="margin:8px 0 0;color:#8B92A0;font-size:12px;">
      Drop it into any LangChain agent &mdash; the tool auto-describes itself for function calling.
    </p>
  </div>

  <!-- FreqTrade -->
  <div style="background:#162D4A;border:1px solid #1A3A5C;border-radius:8px;padding:20px;margin:0 0 20px;">
    <h3 style="margin:0 0 10px;color:#7CDB8A;font-size:15px;font-weight:600;">2. FreqTrade Strategy</h3>
    <p style="margin:0 0 8px;color:#A0AEC0;font-size:14px;line-height:1.6;">
      A drop-in FreqTrade strategy that gates every entry through the regime endpoint.
    </p>
    <p style="margin:0;color:#A0AEC0;font-size:14px;">
      <a href="https://github.com/harrison-collab/renoun-freqtrade-strategy" style="color:#7CDB8A;">github.com/harrison-collab/renoun-freqtrade-strategy</a>
    </p>
  </div>

  <!-- Raw API: Batch -->
  <div style="background:#162D4A;border:1px solid #1A3A5C;border-radius:8px;padding:20px;margin:0 0 20px;">
    <h3 style="margin:0 0 10px;color:#7CDB8A;font-size:15px;font-weight:600;">3. Raw API &mdash; Batch Multiple Pairs</h3>
    <p style="margin:0 0 10px;color:#A0AEC0;font-size:14px;line-height:1.6;">
      Check multiple symbols in one call with the portfolio endpoint:
    </p>
    <div style="background:#0B1D3A;border-radius:6px;padding:14px 16px;overflow-x:auto;">
      <pre style="margin:0;color:#e0e0e0;font-family:'JetBrains Mono',Consolas,monospace;font-size:12px;line-height:1.6;white-space:pre-wrap;">curl -X POST \\
  https://api.harrisoncollab.com/v1/regime/portfolio \\
  -H "Authorization: Bearer {api_key}" \\
  -H "Content-Type: application/json" \\
  -d '{{"symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT"]}}'</pre>
    </div>
    <p style="margin:8px 0 0;color:#8B92A0;font-size:12px;">
      Returns regime, action, and exposure_scalar for each pair &mdash; one call, one count against your quota.
    </p>
  </div>

  <!-- MCP -->
  <div style="background:#162D4A;border:1px solid #1A3A5C;border-radius:8px;padding:20px;margin:0 0 24px;">
    <h3 style="margin:0 0 10px;color:#7CDB8A;font-size:15px;font-weight:600;">4. MCP (Model Context Protocol)</h3>
    <p style="margin:0;color:#A0AEC0;font-size:14px;line-height:1.6;">
      ReNoUn is listed in MCP registries for agent discovery. Any MCP-compatible agent
      (Claude, GPT with plugins, custom agents) can discover and connect automatically.
    </p>
    <div style="background:#0B1D3A;border-radius:6px;padding:14px 16px;margin-top:10px;overflow-x:auto;">
      <pre style="margin:0;color:#e0e0e0;font-family:'JetBrains Mono',Consolas,monospace;font-size:12px;line-height:1.6;white-space:pre-wrap;">pip install renoun-mcp</pre>
    </div>
  </div>

  <p style="margin:0;color:#A0AEC0;font-size:14px;">
    <strong>Full API docs:</strong> <a href="https://api.harrisoncollab.com/docs" style="color:#7CDB8A;">Interactive API Explorer</a>
  </p>
</td></tr>""" + _DRIP_DARK_FOOTER


def _drip_email_3_html(api_key: str, calls_made: int) -> str:
    """Drip email 3: 'Your first week with ReNoUn' — sent day 5.

    Shows usage stats, provides tailored guidance based on low vs high usage,
    links to metered billing and Telegram channel.
    """
    # Determine usage tier and build the appropriate section
    if calls_made < 10:
        usage_color = "#FF5555"
        usage_label = "Getting started"
        usage_section = f"""
  <div style="background:#162D4A;border:1px solid #1A3A5C;border-radius:8px;padding:20px;margin:0 0 24px;">
    <h3 style="margin:0 0 10px;color:#FFD700;font-size:15px;font-weight:600;">Haven't tried it yet?</h3>
    <p style="margin:0 0 12px;color:#A0AEC0;font-size:14px;line-height:1.6;">
      The simplest integration is a single curl before you trade. Add this to a cron job or
      your bot's pre-trade check:
    </p>
    <div style="background:#0B1D3A;border-radius:6px;padding:14px 16px;overflow-x:auto;">
      <pre style="margin:0;color:#e0e0e0;font-family:'JetBrains Mono',Consolas,monospace;font-size:12px;line-height:1.6;white-space:pre-wrap;">REGIME=$(curl -s -H "Authorization: Bearer {api_key}" \\
  https://api.harrisoncollab.com/v1/regime/live/BTCUSDT \\
  | python3 -c "import sys,json; print(json.load(sys.stdin)['action'])")

if [ "$REGIME" = "avoid" ]; then
  echo "Unstable regime — skipping trade"
  exit 0
fi</pre>
    </div>
    <p style="margin:10px 0 0;color:#8B92A0;font-size:12px;">
      That's it. One call. If the regime says <em>avoid</em>, skip the trade. You just dodged every unstable window.
    </p>
  </div>"""
    else:
        usage_color = "#7CDB8A"
        usage_label = "Active user"
        usage_section = f"""
  <div style="background:#162D4A;border:1px solid #1A3A5C;border-radius:8px;padding:20px;margin:0 0 24px;">
    <h3 style="margin:0 0 10px;color:#7CDB8A;font-size:15px;font-weight:600;">You're getting value. Here's how power users integrate.</h3>
    <p style="margin:0 0 12px;color:#A0AEC0;font-size:14px;line-height:1.6;">
      Power users don't just check regime &mdash; they use <code style="color:#7CDB8A;font-family:'JetBrains Mono',Consolas,monospace;font-size:12px;">exposure_scalar</code>
      to dynamically size positions:
    </p>
    <div style="background:#0B1D3A;border-radius:6px;padding:14px 16px;overflow-x:auto;">
      <pre style="margin:0;color:#e0e0e0;font-family:'JetBrains Mono',Consolas,monospace;font-size:12px;line-height:1.6;white-space:pre-wrap;">import requests

resp = requests.get(
    "https://api.harrisoncollab.com/v1/regime/live/BTCUSDT",
    headers={{"Authorization": "Bearer {api_key}"}},
).json()

# Scale your position by the regime's exposure scalar
base_size = 1000  # $1000 base position
actual_size = base_size * resp["exposure_scalar"]
# bounded=1.0x, active=0.5x, unstable=0.0x</pre>
    </div>
    <p style="margin:10px 0 0;color:#8B92A0;font-size:12px;">
      Also check out the <strong>portfolio endpoint</strong> to batch-check all your pairs in a single call.
    </p>
  </div>"""

    return _DRIP_DARK_HEADER + f"""

<!-- Body -->
<tr><td style="padding:40px;">
  <h2 style="margin:0 0 16px;color:#FFFFF0;font-size:20px;font-weight:600;">Your first week with ReNoUn</h2>

  <!-- Usage Stats -->
  <div style="background:#162D4A;border:1px solid #1A3A5C;border-radius:8px;padding:20px;margin:0 0 24px;">
    <table width="100%" cellpadding="0" cellspacing="0">
      <tr>
        <td style="text-align:center;padding:12px;">
          <p style="margin:0;color:#FFFFF0;font-size:36px;font-weight:700;">{calls_made}</p>
          <p style="margin:4px 0 0;color:#8B92A0;font-size:12px;text-transform:uppercase;letter-spacing:0.05em;">API calls made</p>
        </td>
        <td style="text-align:center;padding:12px;">
          <p style="margin:0;color:#FFFFF0;font-size:36px;font-weight:700;">50</p>
          <p style="margin:4px 0 0;color:#8B92A0;font-size:12px;text-transform:uppercase;letter-spacing:0.05em;">Free daily limit</p>
        </td>
        <td style="text-align:center;padding:12px;">
          <p style="margin:0;color:{usage_color};font-size:14px;font-weight:600;">{usage_label}</p>
          <p style="margin:4px 0 0;color:#8B92A0;font-size:12px;text-transform:uppercase;letter-spacing:0.05em;">Status</p>
        </td>
      </tr>
    </table>
  </div>

  {usage_section}

  <!-- Metered Billing CTA -->
  <div style="background:#162D4A;border:1px solid #1A3A5C;border-radius:8px;padding:20px;margin:0 0 24px;">
    <h3 style="margin:0 0 10px;color:#FFD700;font-size:15px;font-weight:600;">&#9889; Need more than 50 calls/day?</h3>
    <p style="margin:0 0 16px;color:#A0AEC0;font-size:14px;line-height:1.6;">
      Add a payment method for metered billing at <strong style="color:#FFFFF0;">$0.02 per call</strong> beyond your 50 free daily calls.
      No subscription. No minimum. Pay only for what you use.
    </p>
    <div style="text-align:center;">
      <a href="https://harrisoncollab.com/billing" style="display:inline-block;background:#7CDB8A;color:#0B1D3A;padding:12px 28px;border-radius:8px;font-size:15px;font-weight:700;text-decoration:none;">Add Payment Method</a>
    </div>
  </div>

  <!-- Telegram -->
  <div style="background:#162D4A;border:1px solid #1A3A5C;border-radius:8px;padding:20px;margin:0 0 24px;">
    <h3 style="margin:0 0 10px;color:#FFFFF0;font-size:15px;font-weight:600;">Join the Telegram channel</h3>
    <p style="margin:0;color:#A0AEC0;font-size:14px;line-height:1.6;">
      Get real-time regime signals, portfolio actions, and structural alerts delivered straight to Telegram.
      No API calls needed &mdash; just follow the channel.
    </p>
    <p style="margin:10px 0 0;">
      <a href="https://t.me/renaboreturn" style="color:#7CDB8A;font-size:14px;font-weight:600;">t.me/renaboreturn &rarr;</a>
    </p>
  </div>

  <p style="margin:0;color:#A0AEC0;font-size:14px;">
    <strong>Docs:</strong> <a href="https://harrisoncollab.com/agents" style="color:#7CDB8A;">harrisoncollab.com/agents</a>
    &nbsp;&bull;&nbsp;
    <strong>Dashboard:</strong> <a href="https://harrisoncollab.com/dashboard" style="color:#7CDB8A;">harrisoncollab.com/dashboard</a>
  </p>
</td></tr>""" + _DRIP_DARK_FOOTER


# ---------------------------------------------------------------------------
# Drip Email Senders
# ---------------------------------------------------------------------------

def send_drip_email_1(email: str, api_key: str) -> dict:
    """Send drip email 1: 'Your ReNoUn API Key' — immediate on provision.

    Returns dict with success status.
    """
    if not is_email_configured():
        print(f"[email] Resend not configured. Would send drip 1 to {email}")
        return {"success": False, "reason": "email_not_configured"}

    html = _drip_email_1_html(api_key)
    result = _send_resend(
        to=email,
        subject="Your ReNoUn API Key — 50 free calls/day",
        html=html,
    )

    if result["success"]:
        print(f"[email] Drip 1 sent to {email} (id: {result['id']})")
    else:
        print(f"[email] Failed to send drip 1 to {email}: {result['error']}")

    return result


def send_drip_email_2(email: str, api_key: str) -> dict:
    """Send drip email 2: 'Wire ReNoUn into your stack' — day 2.

    Returns dict with success status.
    """
    if not is_email_configured():
        print(f"[email] Resend not configured. Would send drip 2 to {email}")
        return {"success": False, "reason": "email_not_configured"}

    html = _drip_email_2_html(api_key)
    result = _send_resend(
        to=email,
        subject="Wire ReNoUn into your stack — LangChain, FreqTrade, MCP",
        html=html,
    )

    if result["success"]:
        print(f"[email] Drip 2 sent to {email} (id: {result['id']})")
    else:
        print(f"[email] Failed to send drip 2 to {email}: {result['error']}")

    return result


def send_drip_email_3(email: str, api_key: str, calls_made: int) -> dict:
    """Send drip email 3: 'Your first week with ReNoUn' — day 5.

    Returns dict with success status.
    """
    if not is_email_configured():
        print(f"[email] Resend not configured. Would send drip 3 to {email}")
        return {"success": False, "reason": "email_not_configured"}

    html = _drip_email_3_html(api_key, calls_made)
    result = _send_resend(
        to=email,
        subject=f"Your first week with ReNoUn — {calls_made} calls and counting",
        html=html,
    )

    if result["success"]:
        print(f"[email] Drip 3 sent to {email} (id: {result['id']})")
    else:
        print(f"[email] Failed to send drip 3 to {email}: {result['error']}")

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
    test_cmd.add_argument("--key", default="rn_agent_test1234567890abcdef1234567890abcdef12345678", help="Test API key")

    sub.add_parser("status", help="Check email configuration")

    args = parser.parse_args()

    if args.command == "test":
        result = send_agent_welcome_email(to=args.to, raw_key=args.key)
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
