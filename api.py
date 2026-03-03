#!/usr/bin/env python3
"""
ReNoUn HTTP API Server.

FastAPI server exposing the ReNoUn 17-channel engine as a REST API
with API key authentication, rate limiting, and usage logging.

Usage:
    python3 api.py                              # Start on default port 8080
    uvicorn api:app --host 0.0.0.0 --port 8080  # Start with uvicorn directly

Endpoints:
    POST /v1/analyze       — Full 17-channel structural analysis
    POST /v1/health-check  — Fast structural triage
    POST /v1/compare       — Structural A/B test between conversations
    POST /v1/patterns/{action} — Save, query, list, or trend session history
    GET  /v1/status        — Liveness + version info (no auth)
    POST /v1/billing/checkout   — Create Stripe Checkout session for pro subscription
    POST /v1/billing/webhook    — Stripe webhook receiver (auto-provisions keys)
    POST /v1/billing/portal     — Stripe Customer Portal (manage subscription)

Patent Pending #63/923,592 — core engine is proprietary.
"""

import time
from typing import Optional

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from api_config import (
    API_HOST, API_PORT, CORS_ORIGINS,
    API_VERSION, API_TITLE, API_DESCRIPTION,
)
from auth import validate_key, is_tool_allowed, get_tier_config
from rate_limiter import limiter
from usage import log_request
from server import (
    tool_analyze, tool_health_check, tool_compare, tool_pattern_query,
    TOOL_VERSION, ENGINE_VERSION, SCHEMA_VERSION,
)


# ---------------------------------------------------------------------------
# FastAPI App
# ---------------------------------------------------------------------------

app = FastAPI(
    title=API_TITLE,
    description=API_DESCRIPTION,
    version=API_VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Auth Dependency
# ---------------------------------------------------------------------------

async def require_auth(request: Request) -> dict:
    """Extract and validate API key from Authorization header."""
    auth_header = request.headers.get("Authorization", "")

    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail={"error": {"type": "auth_error", "message": "Missing or malformed Authorization header. Use: Bearer rn_live_...", "action": "Add header: Authorization: Bearer <your-api-key>"}},
        )

    raw_key = auth_header[7:].strip()
    key_info = validate_key(raw_key)

    if not key_info:
        raise HTTPException(
            status_code=401,
            detail={"error": {"type": "auth_error", "message": "Invalid or revoked API key.", "action": "Check your API key or request a new one."}},
        )

    return key_info


def check_tool_access(key_info: dict, tool_name: str):
    """Check if the authenticated key has access to this tool."""
    if not is_tool_allowed(key_info["tier"], tool_name):
        tier = key_info["tier"]
        config = get_tier_config(tier)
        allowed = ", ".join(config["tools"])
        raise HTTPException(
            status_code=403,
            detail={"error": {"type": "tier_error", "message": f"Tool '{tool_name}' not available on {tier} tier. Available: {allowed}", "action": f"Upgrade to pro tier for full access."}},
        )


def check_rate_limit(key_info: dict):
    """Check if the key has exceeded its rate limit."""
    result = limiter.check(key_info["key_id"], key_info["tier"])
    if result:
        raise HTTPException(
            status_code=429,
            detail={"error": {"type": "rate_limited", "message": result["message"], "action": "Wait and retry, or upgrade your tier."}},
            headers={"Retry-After": str(result["retry_after"])},
        )


def check_turn_limit(key_info: dict, turn_count: int):
    """Check if utterance count exceeds tier limit."""
    config = get_tier_config(key_info["tier"])
    max_turns = config["max_turns"]
    if max_turns != -1 and turn_count > max_turns:
        raise HTTPException(
            status_code=400,
            detail={"error": {"type": "tier_error", "message": f"Turn count {turn_count} exceeds {key_info['tier']} tier limit of {max_turns}.", "action": "Reduce turns or upgrade tier."}},
        )


# ---------------------------------------------------------------------------
# Request Models
# ---------------------------------------------------------------------------

class Utterance(BaseModel):
    speaker: str
    text: str
    index: Optional[int] = None

class AnalyzeRequest(BaseModel):
    utterances: list[Utterance] = Field(..., min_length=3)

class HealthCheckRequest(BaseModel):
    utterances: list[Utterance] = Field(..., min_length=3)

class CompareRequest(BaseModel):
    result_a: Optional[dict] = None
    result_b: Optional[dict] = None
    utterances_a: Optional[list[Utterance]] = None
    utterances_b: Optional[list[Utterance]] = None
    label_a: str = "Session A"
    label_b: str = "Session B"

class PatternQueryRequest(BaseModel):
    result: Optional[dict] = None
    session_name: Optional[str] = None
    domain: Optional[str] = None
    tags: Optional[list[str]] = None
    from_date: Optional[str] = None
    to_date: Optional[str] = None
    constellation: Optional[str] = None
    tag: Optional[str] = None
    dhs_below: Optional[float] = None
    dhs_above: Optional[float] = None
    metric: str = "dhs"


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _run_tool(tool_name: str, handler, arguments: dict, key_info: dict, endpoint: str, turn_count: int = 0):
    """Common wrapper: auth check, rate limit, execute, log, return."""
    check_tool_access(key_info, tool_name)
    check_rate_limit(key_info)
    if turn_count > 0:
        check_turn_limit(key_info, turn_count)

    start = time.time()
    result = handler(arguments)
    elapsed_ms = (time.time() - start) * 1000

    # Record rate limit usage
    limiter.record(key_info["key_id"], key_info["tier"])

    # Determine status
    has_error = "error" in result
    status_code = 400 if has_error else 200

    # Log usage
    log_request(
        key_id=key_info["key_id"],
        tier=key_info["tier"],
        endpoint=endpoint,
        turn_count=turn_count,
        response_time_ms=elapsed_ms,
        status_code=status_code,
        error=result["error"]["message"] if has_error else "",
    )

    # Add rate limit info to response headers
    usage = limiter.get_usage(key_info["key_id"], key_info["tier"])

    if has_error:
        return JSONResponse(status_code=400, content=result, headers={
            "X-RateLimit-Remaining": str(usage["remaining"]),
            "X-RateLimit-Limit": str(usage["limit"]),
        })

    return JSONResponse(content=result, headers={
        "X-RateLimit-Remaining": str(usage["remaining"]),
        "X-RateLimit-Limit": str(usage["limit"]),
        "X-Response-Time-Ms": str(round(elapsed_ms, 2)),
    })


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/v1/status")
async def status():
    """Liveness check and version info. No auth required."""
    return {
        "status": "ok",
        "server": "renoun",
        "version": API_VERSION,
        "engine_version": ENGINE_VERSION,
        "tool_version": TOOL_VERSION,
        "schema_version": SCHEMA_VERSION,
    }


@app.post("/v1/analyze")
async def analyze(body: AnalyzeRequest, key_info: dict = Depends(require_auth)):
    """Full 17-channel structural analysis."""
    utterances = [u.model_dump(exclude_none=True) for u in body.utterances]
    return _run_tool(
        tool_name="renoun_analyze",
        handler=tool_analyze,
        arguments={"utterances": utterances},
        key_info=key_info,
        endpoint="/v1/analyze",
        turn_count=len(utterances),
    )


@app.post("/v1/health-check")
async def health_check(body: HealthCheckRequest, key_info: dict = Depends(require_auth)):
    """Fast structural triage."""
    utterances = [u.model_dump(exclude_none=True) for u in body.utterances]
    return _run_tool(
        tool_name="renoun_health_check",
        handler=tool_health_check,
        arguments={"utterances": utterances},
        key_info=key_info,
        endpoint="/v1/health-check",
        turn_count=len(utterances),
    )


@app.post("/v1/compare")
async def compare(body: CompareRequest, key_info: dict = Depends(require_auth)):
    """Structural A/B test between two conversations."""
    arguments = {}
    turn_count = 0

    if body.result_a is not None:
        arguments["result_a"] = body.result_a
    if body.result_b is not None:
        arguments["result_b"] = body.result_b
    if body.utterances_a is not None:
        arguments["utterances_a"] = [u.model_dump(exclude_none=True) for u in body.utterances_a]
        turn_count += len(body.utterances_a)
    if body.utterances_b is not None:
        arguments["utterances_b"] = [u.model_dump(exclude_none=True) for u in body.utterances_b]
        turn_count += len(body.utterances_b)
    arguments["label_a"] = body.label_a
    arguments["label_b"] = body.label_b

    return _run_tool(
        tool_name="renoun_compare",
        handler=tool_compare,
        arguments=arguments,
        key_info=key_info,
        endpoint="/v1/compare",
        turn_count=turn_count,
    )


@app.post("/v1/patterns/{action}")
async def patterns(action: str, body: PatternQueryRequest, key_info: dict = Depends(require_auth)):
    """Query or manage longitudinal pattern history."""
    if action not in ("save", "list", "query", "trend"):
        raise HTTPException(status_code=400, detail={"error": {"type": "invalid_action", "message": f"Invalid action: {action}. Must be save, list, query, or trend.", "action": "Use one of: save, list, query, trend"}})

    arguments = {"action": action}
    if body.result is not None:
        arguments["result"] = body.result
    if body.session_name:
        arguments["session_name"] = body.session_name
    if body.domain:
        arguments["domain"] = body.domain
    if body.tags:
        arguments["tags"] = body.tags
    if body.from_date:
        arguments["from_date"] = body.from_date
    if body.to_date:
        arguments["to_date"] = body.to_date
    if body.constellation:
        arguments["constellation"] = body.constellation
    if body.tag:
        arguments["tag"] = body.tag
    if body.dhs_below is not None:
        arguments["dhs_below"] = body.dhs_below
    if body.dhs_above is not None:
        arguments["dhs_above"] = body.dhs_above
    arguments["metric"] = body.metric

    return _run_tool(
        tool_name="renoun_pattern_query",
        handler=tool_pattern_query,
        arguments=arguments,
        key_info=key_info,
        endpoint=f"/v1/patterns/{action}",
    )


# ---------------------------------------------------------------------------
# Billing Endpoints
# ---------------------------------------------------------------------------

from stripe_billing import create_checkout_session, handle_webhook, create_portal_session


class CheckoutRequest(BaseModel):
    email: str = Field(..., description="Customer email for the subscription")


class PortalRequest(BaseModel):
    api_key: str = Field(..., description="Your ReNoUn API key (rn_live_...)")
    return_url: str = Field(default="", description="URL to return to after portal session")


@app.post("/v1/billing/checkout")
async def billing_checkout(body: CheckoutRequest):
    """Create a Stripe Checkout session for a $4.99/mo pro subscription.

    Returns a checkout_url — redirect the customer there to complete payment.
    On successful payment, a pro API key is auto-provisioned and delivered.
    No auth required (this is how new customers get their first key).
    """
    result = create_checkout_session(customer_email=body.email)
    if "error" in result:
        raise HTTPException(status_code=500, detail={"error": {"type": "billing_error", "message": result["error"], "action": "Check Stripe configuration."}})
    return result


@app.post("/v1/billing/webhook")
async def billing_webhook(request: Request):
    """Stripe webhook receiver. Handles payment events and auto-provisions/downgrades keys.

    Events handled:
      - checkout.session.completed → provisions pro API key
      - invoice.payment_succeeded → confirms renewal
      - invoice.payment_failed → logs failure (Stripe retries automatically)
      - customer.subscription.deleted/updated → downgrades key to free tier
    """
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    result = handle_webhook(payload, sig_header)

    if "error" in result:
        status = result.pop("status", 400)
        raise HTTPException(status_code=status, detail={"error": {"type": "webhook_error", "message": result["error"]}})

    # Log the webhook event
    log_request(
        key_id=result.get("key_id", "webhook"),
        tier="system",
        endpoint="/v1/billing/webhook",
        status_code=200,
    )

    return result


@app.post("/v1/billing/portal")
async def billing_portal(body: PortalRequest):
    """Create a Stripe Customer Portal session for managing subscriptions.

    Lets customers update payment method, cancel, or view invoices.
    Requires a valid API key to look up the associated Stripe customer.
    """
    from auth import validate_key as _validate
    from stripe_billing import _find_key_by_customer

    key_info = _validate(body.api_key)
    if not key_info:
        raise HTTPException(status_code=401, detail={"error": {"type": "auth_error", "message": "Invalid API key.", "action": "Provide a valid rn_live_... key."}})

    # Find the Stripe customer linked to this key
    from auth import _load_keys
    data = _load_keys()
    customer_id = None
    for entry in data["keys"]:
        if entry["key_id"] == key_info["key_id"] and entry.get("stripe_customer_id"):
            customer_id = entry["stripe_customer_id"]
            break

    if not customer_id:
        raise HTTPException(status_code=404, detail={"error": {"type": "not_found", "message": "No Stripe subscription linked to this key.", "action": "This key was not created through Stripe checkout."}})

    result = create_portal_session(customer_id, return_url=body.return_url)
    if "error" in result:
        raise HTTPException(status_code=500, detail={"error": {"type": "billing_error", "message": result["error"]}})
    return result


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    print(f"\nReNoUn API Server v{API_VERSION}")
    print(f"  Engine: v{ENGINE_VERSION}")
    print(f"  Docs:   http://{API_HOST}:{API_PORT}/docs")
    print(f"  Status: http://{API_HOST}:{API_PORT}/v1/status\n")
    uvicorn.run(app, host=API_HOST, port=API_PORT)
