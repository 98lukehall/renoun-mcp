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
    POST /v1/steer         — Real-time inference steering with rolling windows
    GET  /v1/status        — Liveness + version info (no auth)
    POST /v1/billing/checkout   — Create Stripe Checkout session for pro subscription
    POST /v1/billing/webhook    — Stripe webhook receiver (auto-provisions keys)
    POST /v1/billing/portal     — Stripe Customer Portal (manage subscription)

Patent Pending #63/923,592 — core engine is proprietary.
"""

import logging
import os
import time
import traceback
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("renoun.api")

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from api_config import (
    API_HOST, API_PORT, CORS_ORIGINS,
    API_VERSION, API_TITLE, API_DESCRIPTION,
)
from auth import validate_key, is_tool_allowed, get_tier_config, create_agent_key, find_agent_key_by_email, count_agent_keys_by_email
from rate_limiter import limiter
from usage import log_request, metered_tracker
from analytics import record_pageview, record_provision, get_summary as get_analytics_summary
from email_sender import send_agent_welcome_email, send_limit_reached_email
from drip_scheduler import register_provision, start_drip_scheduler
from server import (
    tool_analyze, tool_health_check, tool_compare, tool_pattern_query, tool_steer,
    tool_finance_analyze,
    TOOL_VERSION, ENGINE_VERSION, SCHEMA_VERSION,
    TOOL_HANDLERS,
)
from regime_cache import regime_cache
from regime_service import analysis_to_regime_response, compute_portfolio_action, META_BLOCK

# Start news monitor background thread
try:
    from news_monitor import start_news_monitor
    start_news_monitor(interval_seconds=60)
except ImportError:
    pass  # news_monitor not available, regime works without it

# Start drip email scheduler background thread (checks every 15 minutes)
try:
    start_drip_scheduler(interval_seconds=900)
except Exception:
    pass  # Don't let drip scheduler failures block API startup


# ---------------------------------------------------------------------------
# FastAPI App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="ReNoUn Regime Classification API",
    description=(
        "Structural regime classification for crypto markets. "
        "100% bounded regime accuracy (126+ graded). "
        "Pre-trade risk check: returns regime (bounded/active/unstable) "
        "and action (proceed/reduce/avoid)."
    ),
    version="1.4.0",
    contact={"name": "Harrison Collab", "email": "98lukehall@gmail.com", "url": "https://harrisoncollab.com"},
    license_info={"name": "Proprietary — Patent Pending #63/923,592"},
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


@app.middleware("http")
async def add_agent_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Agent-Compatible"] = "true"
    response.headers["X-Agent-Free-Tier"] = "50/day"
    response.headers["X-Agent-Provision-URL"] = "/v1/keys/provision"
    response.headers["X-Agent-Docs"] = "https://harrisoncollab.com/agents"
    return response


# ---------------------------------------------------------------------------
# Auth Dependency
# ---------------------------------------------------------------------------

async def require_auth(request: Request) -> dict:
    """Extract and validate API key from Authorization header."""
    auth_header = request.headers.get("Authorization", "")

    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail={"error": {"type": "auth_error", "message": "Missing or malformed Authorization header. Use: Bearer rn_agent_... or rn_live_...", "action": "Add header: Authorization: Bearer <your-api-key>. Get a free key at /v1/keys/provision"}},
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
    """Check if the key has exceeded its rate limit.

    For free-tier keys, returns 402 with upgrade URL instead of a plain 429.
    """
    result = limiter.check(key_info["key_id"], key_info["tier"])
    if result:
        tier = key_info["tier"]
        if tier == "free":
            daily_limit = result.get("daily_limit", 20)
            raise HTTPException(
                status_code=402,
                detail={"error": {
                    "type": "free_limit_exhausted",
                    "message": f"Free tier daily limit reached ({daily_limit}/{daily_limit}). Upgrade to Pro for 1,000 calls/day at $4.99/mo.",
                    "upgrade_url": "https://harrisoncollab.com/billing.html",
                    "billing_url": "https://harrisoncollab.com/billing.html",
                    "action": "Upgrade to Pro at the billing URL, or wait for daily reset.",
                    "resets_at": "midnight UTC",
                }},
                headers={"Retry-After": str(result["retry_after"])},
            )
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


BILLING_URL = "https://harrisoncollab.com/billing.html"


def _record_agent_call(key_info: dict, endpoint: str) -> Optional[dict]:
    """Record a metered call for agent-tier keys.

    Returns a _billing warning dict to inject into the response at 40+ calls,
    or None if no warning needed.

    Raises HTTPException 402 if free tier exhausted and no billing on file.
    """
    if key_info["tier"] != "agent":
        return None

    tier_config = get_tier_config("agent")
    has_billing = key_info.get("has_billing", False)

    # Pre-check: block if past free tier and no billing
    usage = metered_tracker.get_usage(key_info["key_id"], tier_config)
    if usage["today"]["total_calls"] >= 50 and not has_billing:
        raise HTTPException(status_code=402, detail={
            "error": {
                "type": "free_limit_exhausted",
                "message": "Free daily limit reached (50/50). Add a payment method to continue.",
                "billing_url": BILLING_URL,
                "action": "Add a payment method at the billing URL, then retry.",
                "resets_at": "midnight UTC",
            }
        })

    result = metered_tracker.record_call(key_info["key_id"], endpoint, tier_config)

    # Send limit email at exactly 50 calls
    if result.get("send_limit_email"):
        owner = key_info.get("owner", "")
        if owner:
            try:
                send_limit_reached_email(to=owner, daily_total=result["daily_total"], billing_url=BILLING_URL)
            except Exception:
                pass  # Don't let email failures block API calls

    # Hard block: if this call just hit 51+ and no billing, reject
    if result["daily_total"] > 50 and not has_billing:
        raise HTTPException(status_code=402, detail={
            "error": {
                "type": "free_limit_exhausted",
                "message": "Free daily limit reached (50/50). Add a payment method to continue.",
                "billing_url": BILLING_URL,
                "action": "Add a payment method at the billing URL, then retry.",
                "resets_at": "midnight UTC",
            }
        })

    # Return billing warning for 40+ calls
    if result.get("warning") == "limit_reached":
        return {
            "warning": "free_limit_reached",
            "message": f"You've used all {result['daily_total']} free calls today. Add a payment method to continue at $0.02/call.",
            "daily_total": result["daily_total"],
            "free_remaining": 0,
            "billing_url": BILLING_URL,
        }
    elif result.get("warning") == "approaching_limit":
        return {
            "warning": "approaching_free_limit",
            "message": f"{result['daily_total']}/50 free calls used today. Add a payment method to avoid interruption.",
            "daily_total": result["daily_total"],
            "free_remaining": result["free_remaining"],
            "billing_url": BILLING_URL,
        }

    return None


# ---------------------------------------------------------------------------
# Request Models
# ---------------------------------------------------------------------------

class Utterance(BaseModel):
    speaker: str
    text: str
    index: Optional[int] = None

class AnalyzeRequest(BaseModel):
    utterances: list[Utterance] = Field(..., min_length=3)
    weights: Optional[list[float]] = Field(None, description="Per-turn weights 0.0-1.0")
    tags: Optional[list[dict]] = Field(None, description="Per-turn tags from pre_tag()")
    weighting_mode: str = Field("weight", description="weight|exclude|segment")

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

class SteerRequest(BaseModel):
    utterances: Optional[list[Utterance]] = Field(None, description="New turns to add to the session buffer")
    session_id: str = Field("default", description="Unique session identifier")
    action: str = Field("add_turns", description="add_turns|get_status|clear_session|list_sessions")
    window_size: Optional[int] = Field(None, description="Turns per analysis window (default 30)")
    session_ttl: Optional[int] = Field(None, description="Session TTL in seconds (default 3600)")

class FinanceAnalyzeRequest(BaseModel):
    klines: list[dict] = Field(..., min_length=10, description="OHLCV candle data")
    symbol: str = Field("UNKNOWN", description="Trading pair symbol")
    timeframe: str = Field("1h", description="Candle timeframe")
    include_exposure: bool = Field(True, description="Include exposure recommendation")


class RegimeRequest(BaseModel):
    symbol: str = Field("BTCUSDT", description="Trading pair symbol")
    timeframe: str = Field("1h", description="Candle timeframe")
    klines: list[dict] = Field(..., min_length=10, description="OHLCV candle data")
    include_full: bool = Field(False, description="Include full analysis in response")

class RegimeBatchRequest(BaseModel):
    symbols: list[str] = Field(..., min_length=1, max_length=10, description="Binance USDT pairs")
    timeframe: str = Field("1h", description="Candle timeframe")
    include_full: bool = Field(False, description="Include full analysis per asset")

class TraceEventRequest(BaseModel):
    agent_id: str = Field(..., description="Agent identifier")
    event_type: str = Field(..., description="Event type: user_message, assistant_message, tool_call, etc.")
    content: str = Field(..., description="Event content")
    timestamp: Optional[str] = Field(None, description="ISO 8601 timestamp")


class AgentMonitorRequest(BaseModel):
    action: str = Field("ingest", description="ingest|dashboard|configure|clear")
    session_id: str = Field("default", description="Session identifier for the agent workflow")
    events: Optional[list[TraceEventRequest]] = Field(None, description="Trace events to ingest")
    config: Optional[dict] = Field(None, description="Configuration overrides for thresholds and monitoring mode")


class AlignmentClassifyRequest(BaseModel):
    utterances: list[Utterance] = Field(..., min_length=4, description="Conversation turns (minimum 4)")
    include_bridge_signals: bool = Field(True, description="Include per-speaker revision traces, challenge detection, vocabulary adoption")
    include_renoun_raw: bool = Field(False, description="Include full ReNoUn channel-level analysis")


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

    # Log usage (also records analytics via log_request)
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
        "version": "1.4.0",
        "engine_version": ENGINE_VERSION,
        "tool_version": TOOL_VERSION,
        "schema_version": SCHEMA_VERSION,
        "agent_info": {
            "provision_url": "/v1/keys/provision",
            "free_tier": "50 calls/day",
            "regime_endpoint": "/v1/regime/live/{symbol}",
            "docs": "/docs",
            "accuracy": "100% bounded regime accuracy, 4700+ predictions graded",
        },
    }


# ---------------------------------------------------------------------------
# Analytics Endpoints
# ---------------------------------------------------------------------------

class PageviewRequest(BaseModel):
    page: str = Field(..., description="Page name, e.g. 'index', 'agents', 'pricing'")

@app.post("/v1/analytics/pageview")
async def analytics_pageview(body: PageviewRequest):
    """Record a landing page visit. No auth required."""
    record_pageview(body.page)
    return {"ok": True}


@app.get("/v1/analytics/summary")
async def analytics_summary(request: Request):
    """Analytics summary. Requires RENOUN_ADMIN_KEY."""
    admin_key = os.environ.get("RENOUN_ADMIN_KEY", "")
    if not admin_key:
        raise HTTPException(status_code=503, detail={
            "error": {"type": "not_configured", "message": "RENOUN_ADMIN_KEY not set on server."}
        })

    auth_header = request.headers.get("Authorization", "")
    provided_key = ""
    if auth_header.startswith("Bearer "):
        provided_key = auth_header[7:].strip()

    if provided_key != admin_key:
        raise HTTPException(status_code=403, detail={
            "error": {"type": "auth_error", "message": "Invalid admin key."}
        })

    return get_analytics_summary()


@app.get("/v1/debug/binance", tags=["Debug"])
async def debug_binance():
    """Test Binance API connectivity from this server. No auth required."""
    import requests as _requests
    from binance_client import BINANCE_ENDPOINTS

    results = {}
    for endpoint in BINANCE_ENDPOINTS:
        start = time.time()
        try:
            url = f"{endpoint}/api/v3/klines"
            resp = _requests.get(
                url,
                params={"symbol": "BTCUSDT", "interval": "1h", "limit": 1},
                timeout=10,
                headers={"User-Agent": "ReNoUn/1.0"},
            )
            elapsed = (time.time() - start) * 1000
            results[endpoint] = {
                "status": resp.status_code,
                "response_time_ms": round(elapsed, 1),
                "ok": resp.status_code == 200,
                "body_length": len(resp.content),
            }
        except Exception as e:
            elapsed = (time.time() - start) * 1000
            results[endpoint] = {
                "status": "error",
                "response_time_ms": round(elapsed, 1),
                "ok": False,
                "error": str(e),
            }

    return {"binance_connectivity": results}


@app.get("/v1/debug/news", tags=["Debug"])
async def debug_news():
    """Current news alert state for all tracked assets. No auth required."""
    try:
        from news_monitor import news_cache as _nc
        alerts = _nc.get_all()
        return {
            symbol: {
                "level": alert.level,
                "activity_score": alert.activity_score,
                "volume_spike": alert.volume_spike,
                "news_velocity": alert.news_velocity,
                "trending": alert.trending,
                "detail": alert.detail,
                "last_checked": alert.last_checked,
            }
            for symbol, alert in alerts.items()
        }
    except ImportError:
        return {"error": "News monitor not available"}


@app.post("/v1/analyze")
async def analyze(body: AnalyzeRequest, key_info: dict = Depends(require_auth)):
    """Full 17-channel structural analysis."""
    utterances = [u.model_dump(exclude_none=True) for u in body.utterances]
    arguments = {"utterances": utterances}
    if body.weights is not None:
        arguments["weights"] = body.weights
    if body.tags is not None:
        arguments["tags"] = body.tags
    if body.weighting_mode != "weight":
        arguments["weighting_mode"] = body.weighting_mode
    return _run_tool(
        tool_name="renoun_analyze",
        handler=tool_analyze,
        arguments=arguments,
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


@app.post("/v1/steer")
async def steer(body: SteerRequest, key_info: dict = Depends(require_auth)):
    """Real-time inference steering. Feed turns incrementally and get actionable signals."""
    arguments = {
        "action": body.action,
        "session_id": body.session_id,
    }
    turn_count = 0

    if body.utterances is not None:
        arguments["utterances"] = [u.model_dump(exclude_none=True) for u in body.utterances]
        turn_count = len(body.utterances)
    if body.window_size is not None:
        arguments["window_size"] = body.window_size
    if body.session_ttl is not None:
        arguments["session_ttl"] = body.session_ttl

    return _run_tool(
        tool_name="renoun_steer",
        handler=tool_steer,
        arguments=arguments,
        key_info=key_info,
        endpoint="/v1/steer",
        turn_count=turn_count,
    )


@app.post("/v1/finance/analyze")
async def finance_analyze(body: FinanceAnalyzeRequest, key_info: dict = Depends(require_auth)):
    """Structural analysis of financial OHLCV data with exposure recommendations."""
    arguments = {
        "klines": body.klines,
        "symbol": body.symbol,
        "timeframe": body.timeframe,
        "include_exposure": body.include_exposure,
    }
    return _run_tool(
        tool_name="renoun_finance_analyze",
        handler=tool_finance_analyze,
        arguments=arguments,
        key_info=key_info,
        endpoint="/v1/finance/analyze",
    )


# ---------------------------------------------------------------------------
# Regime Endpoints (Agent-Optimized)
# ---------------------------------------------------------------------------

def _run_regime_analysis(klines: list[dict], symbol: str, timeframe: str,
                          include_full: bool, key_info: dict, endpoint: str) -> JSONResponse:
    """Shared logic for regime endpoints: auth, analyze, translate, respond."""
    check_tool_access(key_info, "regime")
    check_rate_limit(key_info)

    start = time.time()
    analysis = tool_finance_analyze({
        "klines": klines,
        "symbol": symbol,
        "timeframe": timeframe,
        "include_exposure": True,
    })
    elapsed_ms = (time.time() - start) * 1000

    limiter.record(key_info["key_id"], key_info["tier"])
    billing_warn = _record_agent_call(key_info, endpoint)
    has_error = "error" in analysis
    log_request(
        key_id=key_info["key_id"], tier=key_info["tier"],
        endpoint=endpoint, response_time_ms=elapsed_ms,
        status_code=400 if has_error else 200,
        error=analysis["error"]["message"] if has_error else "",
    )

    if has_error:
        return JSONResponse(status_code=400, content=analysis)

    result = analysis_to_regime_response(analysis, symbol, timeframe, include_full, tier=key_info["tier"])
    if billing_warn:
        result["_billing"] = billing_warn
    usage = limiter.get_usage(key_info["key_id"], key_info["tier"])

    headers = {
        "X-ReNoUn-Regime": result["regime"],
        "X-ReNoUn-Action": result["action"],
        "X-RateLimit-Remaining": str(usage["remaining"]),
        "X-Response-Time-Ms": str(round(elapsed_ms, 2)),
    }
    stability = result.get("stability", {})
    if stability:
        headers["X-ReNoUn-Stability"] = str(stability.get("stability_score", ""))
        headers["X-ReNoUn-Halflife"] = str(int(stability.get("halflife_minutes", 0)))
        headers["X-ReNoUn-Urgency"] = stability.get("urgency", "")

    return JSONResponse(content=result, headers=headers)


@app.get("/v1/regime/live/{symbol}",
         summary="Live regime classification",
         description="Current structural regime for a Binance trading pair.",
         tags=["Regime"],
         responses={
             200: {"description": "Regime classification with action recommendation"},
             429: {"description": "Rate limit exceeded"},
         },
         openapi_extra={
             "x-agent-use-case": "Call before any crypto trade to check structural regime.",
             "x-agent-frequency": "Before each trade, or every 1-5 minutes for monitoring.",
             "x-agent-action-field": "action (proceed/reduce/avoid)",
         })
async def regime_live(
    symbol: str,
    timeframe: str = "1h",
    include_full: bool = False,
    key_info: dict = Depends(require_auth),
):
    """Live regime classification for a Binance symbol. Cached 60s."""
    check_tool_access(key_info, "regime_live")
    check_rate_limit(key_info)

    # Check cache
    cached = regime_cache.get(symbol, timeframe)
    if cached is not None:
        usage = limiter.get_usage(key_info["key_id"], key_info["tier"])
        limiter.record(key_info["key_id"], key_info["tier"])
        billing_warn = _record_agent_call(key_info, "/v1/regime/live")
        log_request(key_id=key_info["key_id"], tier=key_info["tier"],
                    endpoint="/v1/regime/live", status_code=200)
        resp = dict(cached)
        if billing_warn:
            resp["_billing"] = billing_warn
        headers = {
            "X-ReNoUn-Regime": cached["regime"],
            "X-ReNoUn-Action": cached["action"],
            "X-ReNoUn-Cache": "HIT",
            "X-RateLimit-Remaining": str(usage["remaining"]),
        }
        stability = cached.get("stability", {})
        if stability:
            headers["X-ReNoUn-Stability"] = str(stability.get("stability_score", ""))
            headers["X-ReNoUn-Halflife"] = str(int(stability.get("halflife_minutes", 0)))
            headers["X-ReNoUn-Urgency"] = stability.get("urgency", "")
        return JSONResponse(content=resp, headers=headers)

    # Cache miss — fetch from Binance
    try:
        from binance_client import fetch_klines
        klines = fetch_klines(symbol, interval=timeframe, limit=100)
    except Exception as e:
        logger.error(f"Binance fetch crashed for {symbol}: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=502, detail={
            "error": {"type": "upstream_error",
                      "message": f"Binance fetch failed for {symbol}: {str(e)}",
                      "action": "Try POST /v1/regime with your own klines instead."}
        })

    if not klines:
        raise HTTPException(status_code=502, detail={
            "error": {"type": "upstream_error",
                      "message": f"Failed to fetch klines for {symbol} from Binance. All endpoints returned empty data.",
                      "action": "Check symbol is a valid Binance pair (e.g. BTCUSDT). Or use POST /v1/regime with your own klines."}
        })

    try:
        start = time.time()
        analysis = tool_finance_analyze({
            "klines": klines, "symbol": symbol,
            "timeframe": timeframe, "include_exposure": True,
        })
        elapsed_ms = (time.time() - start) * 1000

        limiter.record(key_info["key_id"], key_info["tier"])
        billing_warn = _record_agent_call(key_info, "/v1/regime/live")

        if "error" in analysis:
            log_request(key_id=key_info["key_id"], tier=key_info["tier"],
                        endpoint="/v1/regime/live", response_time_ms=elapsed_ms,
                        status_code=400, error=analysis["error"]["message"])
            return JSONResponse(status_code=400, content=analysis)

        # Record DHS for momentum tracking before building response
        dhs_value = analysis.get("dialectical_health", 0.5)
        regime_cache.record_dhs(symbol, dhs_value)
        dhs_history = regime_cache.get_dhs_history(symbol)

        result = analysis_to_regime_response(
            analysis, symbol, timeframe, include_full,
            recent_dhs_values=dhs_history,
            tier=key_info["tier"],
        )
        regime_cache.set(symbol, timeframe, result)

        if billing_warn:
            result["_billing"] = billing_warn

        usage = limiter.get_usage(key_info["key_id"], key_info["tier"])
        log_request(key_id=key_info["key_id"], tier=key_info["tier"],
                    endpoint="/v1/regime/live", response_time_ms=elapsed_ms, status_code=200)

        headers = {
            "X-ReNoUn-Regime": result["regime"],
            "X-ReNoUn-Action": result["action"],
            "X-ReNoUn-Cache": "MISS",
            "X-RateLimit-Remaining": str(usage["remaining"]),
            "X-Response-Time-Ms": str(round(elapsed_ms, 2)),
        }
        stability = result.get("stability", {})
        if stability:
            headers["X-ReNoUn-Stability"] = str(stability.get("stability_score", ""))
            headers["X-ReNoUn-Halflife"] = str(int(stability.get("halflife_minutes", 0)))
            headers["X-ReNoUn-Urgency"] = stability.get("urgency", "")

        return JSONResponse(content=result, headers=headers)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unhandled error in regime_live for {symbol}: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail={
            "error": {"type": "internal_error",
                      "message": f"Analysis failed: {str(e)}",
                      "action": "This error has been logged. Try POST /v1/regime with your own klines."}
        })


@app.post("/v1/regime",
          summary="Regime from OHLCV data",
          description="Regime classification from your own OHLCV candle data.",
          tags=["Regime"],
          openapi_extra={
              "x-agent-use-case": "Regime check with data from any exchange (not just Binance).",
          })
async def regime_classify(body: RegimeRequest, key_info: dict = Depends(require_auth)):
    """Regime classification from user-provided OHLCV data."""
    return _run_regime_analysis(
        klines=body.klines, symbol=body.symbol, timeframe=body.timeframe,
        include_full=body.include_full, key_info=key_info, endpoint="/v1/regime",
    )


@app.post("/v1/regime/batch",
          summary="Multi-asset regime batch",
          description="Regime classification for multiple assets with portfolio-level aggregate.",
          tags=["Regime"],
          openapi_extra={
              "x-agent-use-case": "Portfolio risk assessment. Multi-asset position sizing.",
          })
async def regime_batch(body: RegimeBatchRequest, key_info: dict = Depends(require_auth)):
    """Regime classification for multiple assets with portfolio aggregate."""
    check_tool_access(key_info, "regime_batch")

    from binance_client import fetch_klines
    from datetime import datetime, timezone

    regimes = {}
    billing_warn = None
    for symbol in body.symbols:
        check_rate_limit(key_info)

        # Check cache first
        cached = regime_cache.get(symbol, body.timeframe)
        if cached is not None:
            regimes[symbol] = cached
            limiter.record(key_info["key_id"], key_info["tier"])
            billing_warn = _record_agent_call(key_info, "/v1/regime/batch")
            log_request(key_id=key_info["key_id"], tier=key_info["tier"],
                        endpoint="/v1/regime/batch", status_code=200)
            continue

        try:
            klines = fetch_klines(symbol, interval=body.timeframe, limit=100)
        except Exception as e:
            logger.error(f"Binance fetch crashed for {symbol} in batch: {e}")
            klines = []

        if not klines:
            regimes[symbol] = {
                "regime": "unstable", "action": "avoid", "dhs": 0.0, "exposure": 0.0,
                "constellation": "NONE", "error": f"Failed to fetch {symbol} from Binance",
            }
            limiter.record(key_info["key_id"], key_info["tier"])
            billing_warn = _record_agent_call(key_info, "/v1/regime/batch")
            continue

        try:
            analysis = tool_finance_analyze({
                "klines": klines, "symbol": symbol,
                "timeframe": body.timeframe, "include_exposure": True,
            })
        except Exception as e:
            logger.error(f"Analysis crashed for {symbol} in batch: {e}")
            logger.error(traceback.format_exc())
            regimes[symbol] = {
                "regime": "unstable", "action": "avoid", "dhs": 0.0, "exposure": 0.0,
                "constellation": "NONE", "error": f"Analysis failed for {symbol}: {str(e)}",
            }
            limiter.record(key_info["key_id"], key_info["tier"])
            billing_warn = _record_agent_call(key_info, "/v1/regime/batch")
            continue

        limiter.record(key_info["key_id"], key_info["tier"])
        billing_warn = _record_agent_call(key_info, "/v1/regime/batch")

        if "error" in analysis:
            regimes[symbol] = {
                "regime": "unstable", "action": "avoid", "dhs": 0.0, "exposure": 0.0,
                "constellation": "NONE", "error": analysis["error"]["message"],
            }
        else:
            result = analysis_to_regime_response(
                analysis, symbol, body.timeframe, body.include_full,
                tier=key_info["tier"],
            )
            regime_cache.set(symbol, body.timeframe, result)
            regimes[symbol] = result

        log_request(key_id=key_info["key_id"], tier=key_info["tier"],
                    endpoint="/v1/regime/batch", status_code=200)

    portfolio_action, portfolio_exposure, unstable_count = compute_portfolio_action(regimes)

    resp = {
        "regimes": regimes,
        "portfolio_action": portfolio_action,
        "portfolio_exposure": portfolio_exposure,
        "unstable_count": unstable_count,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "_meta": META_BLOCK,
    }
    if billing_warn:
        resp["_billing"] = billing_warn

    return JSONResponse(content=resp)


@app.post("/v1/agent/monitor")
async def agent_monitor(body: AgentMonitorRequest, key_info: dict = Depends(require_auth)):
    """Real-time structural health monitoring for AI agent sessions.

    Feed agent trace events incrementally and receive alerts when
    structural pathologies are detected (stuck loops, oversight loss,
    scattering, cascading errors).
    """
    arguments = {
        "action": body.action,
        "session_id": body.session_id,
    }
    turn_count = 0

    if body.events is not None:
        arguments["events"] = [e.model_dump(exclude_none=True) for e in body.events]
        turn_count = len(body.events)
    if body.config is not None:
        arguments["config"] = body.config

    return _run_tool(
        tool_name="renoun_agent_monitor",
        handler=TOOL_HANDLERS["renoun_agent_monitor"],
        arguments=arguments,
        key_info=key_info,
        endpoint="/v1/agent/monitor",
        turn_count=turn_count,
    )


@app.post("/v1/alignment/classify")
async def alignment_classify(body: AlignmentClassifyRequest, key_info: dict = Depends(require_auth)):
    """Structural alignment classification using the Life as Ground + ReNoUn bridge.

    Classifies conversations as INTEGRATIVELY_COHERENT, SUPPRESSIVELY_COHERENT,
    FRAGMENTED, or RIGID. Adds corrigibility scoring, challenge detection,
    and revision trace analysis on top of base ReNoUn analysis.
    """
    utterances = [u.model_dump(exclude_none=True) for u in body.utterances]
    arguments = {
        "utterances": utterances,
        "include_bridge_signals": body.include_bridge_signals,
        "include_renoun_raw": body.include_renoun_raw,
    }

    return _run_tool(
        tool_name="renoun_alignment_classify",
        handler=TOOL_HANDLERS["renoun_alignment_classify"],
        arguments=arguments,
        key_info=key_info,
        endpoint="/v1/alignment/classify",
        turn_count=len(utterances),
    )


# ---------------------------------------------------------------------------
# Billing Endpoints
# ---------------------------------------------------------------------------

from stripe_billing import create_checkout_session, create_metered_checkout_session, handle_webhook, create_portal_session, get_provisioned_key
from fastapi.responses import HTMLResponse


class CheckoutRequest(BaseModel):
    email: str = Field(..., description="Customer email for the subscription")


class MeteredCheckoutRequest(BaseModel):
    api_key: str = Field(..., description="Your existing rn_agent_... API key")


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


@app.post("/v1/billing/metered")
async def billing_metered(body: MeteredCheckoutRequest):
    """Add a payment method to an existing agent key for metered billing.

    Creates a Stripe Checkout session. After checkout, calls beyond 50/day
    are billed at $0.02 each instead of being blocked.
    """
    from auth import validate_key as _validate
    key_info = _validate(body.api_key)
    if not key_info:
        raise HTTPException(status_code=401, detail={
            "error": {"type": "auth_error", "message": "Invalid API key.", "action": "Provide a valid rn_agent_... key."}
        })
    if key_info["tier"] != "agent":
        raise HTTPException(status_code=400, detail={
            "error": {"type": "tier_error", "message": "Metered billing is only for agent-tier keys.", "action": "Use an rn_agent_... key."}
        })
    if key_info.get("has_billing"):
        raise HTTPException(status_code=409, detail={
            "error": {"type": "already_active", "message": "This key already has metered billing active.", "action": "Use /v1/billing/portal to manage your subscription."}
        })

    result = create_metered_checkout_session(
        customer_email=key_info["owner"],
        key_id=key_info["key_id"],
    )
    if "error" in result:
        raise HTTPException(status_code=500, detail={
            "error": {"type": "billing_error", "message": result["error"], "action": "Check Stripe configuration."}
        })
    return result


class UpgradeRequest(BaseModel):
    api_key: str = Field(default="", description="Your existing rn_live_... free-tier API key (optional if email provided)")
    email: str = Field(default="", description="Email for checkout (optional if api_key provided)")


@app.post("/v1/billing/upgrade")
async def billing_upgrade(body: UpgradeRequest):
    """Upgrade a free-tier key to Pro ($4.99/mo) or start a new Pro subscription.

    Accepts either an existing free-tier API key or an email address.
    Returns a Stripe Checkout URL for the Pro subscription.
    On successful payment, a pro API key is auto-provisioned.
    """
    customer_email = body.email

    # If an API key is provided, validate it and extract the email
    if body.api_key:
        from auth import validate_key as _validate
        key_info = _validate(body.api_key)
        if not key_info:
            raise HTTPException(status_code=401, detail={
                "error": {"type": "auth_error", "message": "Invalid API key.",
                          "action": "Provide a valid API key or use an email address instead."}
            })

        # Agent keys should use /v1/billing/metered instead
        if key_info["tier"] == "agent":
            raise HTTPException(status_code=400, detail={
                "error": {"type": "tier_error",
                          "message": "Agent keys use metered billing, not Pro subscriptions. Use /v1/billing/metered instead.",
                          "action": "POST to /v1/billing/metered with your agent key."}
            })

        # Pro/enterprise keys are already upgraded
        if key_info["tier"] in ("pro", "enterprise"):
            raise HTTPException(status_code=409, detail={
                "error": {"type": "already_upgraded",
                          "message": f"This key is already on the {key_info['tier']} tier.",
                          "action": "Use /v1/billing/portal to manage your subscription."}
            })

        customer_email = key_info.get("owner", "")
        if not customer_email:
            raise HTTPException(status_code=400, detail={
                "error": {"type": "validation_error",
                          "message": "No email associated with this key. Please provide an email address.",
                          "action": "Include an email in your request."}
            })

    if not customer_email:
        raise HTTPException(status_code=400, detail={
            "error": {"type": "validation_error",
                      "message": "Either api_key or email is required.",
                      "action": "Provide your API key or email address."}
        })

    metadata = {}
    if body.api_key:
        from auth import validate_key as _validate
        ki = _validate(body.api_key)
        if ki:
            metadata["existing_key_id"] = ki["key_id"]
            metadata["upgrade_from"] = ki["tier"]

    result = create_checkout_session(customer_email=customer_email, metadata=metadata)
    if "error" in result:
        raise HTTPException(status_code=500, detail={
            "error": {"type": "billing_error", "message": result["error"],
                      "action": "Check Stripe configuration."}
        })
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

    key_info = _validate(body.api_key)
    if not key_info:
        raise HTTPException(status_code=401, detail={"error": {"type": "auth_error", "message": "Invalid API key.", "action": "Provide a valid rn_agent_... or rn_live_... key."}})

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
# Agent Key Provisioning & Usage
# ---------------------------------------------------------------------------

import re

# In-memory rate limiting for provisioning endpoint
_provision_rate: dict = {}  # {ip: [timestamps]}

class ProvisionRequest(BaseModel):
    email: str = Field(..., description="Agent owner email")
    agent_name: str = Field(..., description="Name for this agent")


@app.post("/v1/keys/provision")
async def provision_agent_key(body: ProvisionRequest, request: Request):
    """Provision a free agent API key. No auth required.

    50 free calls/day, $0.02/call after that. No credit card needed to start.
    Idempotent: same email returns the same key.
    """
    # Validate email
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", body.email):
        raise HTTPException(status_code=400, detail={
            "error": {"type": "validation_error", "message": "Invalid email format.",
                      "action": "Provide a valid email address."}
        })

    # Rate limit provisioning: max 10 per IP per hour
    client_ip = request.client.host if request.client else "unknown"
    now = time.time()
    _provision_rate.setdefault(client_ip, [])
    _provision_rate[client_ip] = [t for t in _provision_rate[client_ip] if now - t < 3600]
    if len(_provision_rate[client_ip]) >= 10:
        raise HTTPException(status_code=429, detail={
            "error": {"type": "rate_limited",
                      "message": "Too many provisioning requests. Max 10 per hour.",
                      "action": "Wait before provisioning more keys."}
        })

    # Max 5 keys per email
    existing_count = count_agent_keys_by_email(body.email)
    if existing_count >= 5:
        raise HTTPException(status_code=429, detail={
            "error": {"type": "limit_reached",
                      "message": f"Maximum 5 agent keys per email ({existing_count} active).",
                      "action": "Revoke an existing key or use a different email."}
        })

    # Idempotent: check if email already has an agent key with same name
    from auth import _load_keys
    data = _load_keys()
    for entry in data["keys"]:
        if (entry.get("owner") == body.email and entry.get("agent_name") == body.agent_name
                and entry.get("tier") == "agent" and entry.get("active")):
            # Return existing — but we need the raw key, which we can't recover.
            # Return key_id and instructions instead.
            _provision_rate[client_ip].append(now)
            return {
                "api_key": f"(previously provisioned — key_id: {entry['key_id']})",
                "key_id": entry["key_id"],
                "tier": "agent",
                "note": "This email+agent_name already has an active key. If you lost the key, revoke and re-provision.",
                "free_daily": 50,
                "rate_limit_hourly": 1000,
                "daily_limit": 10000,
                "price_per_call": "$0.02 (beyond free tier)",
                "billing_url": "https://harrisoncollab.com/billing.html",
                "docs_url": "https://harrisoncollab.com/agents",
            }

    # Create new key
    key_data = create_agent_key(email=body.email, agent_name=body.agent_name)
    _provision_rate[client_ip].append(now)

    log_request(key_id=key_data["key_id"], tier="agent",
                endpoint="/v1/keys/provision", status_code=200)
    record_provision()

    # Send welcome email with the API key
    # Register for drip sequence (sends email 1 immediately, schedules 2 & 3)
    try:
        register_provision(
            email=body.email,
            api_key=key_data["raw_key"],
            key_id=key_data["key_id"],
        )
    except Exception:
        pass  # Don't let drip/email failures block provisioning

    return {
        "api_key": key_data["raw_key"],
        "tier": "agent",
        "free_daily": 50,
        "rate_limit_hourly": 1000,
        "daily_limit": 10000,
        "price_per_call": "$0.02 (beyond free tier)",
        "billing_url": BILLING_URL,
        "docs_url": "https://harrisoncollab.com/agents",
        "note": "You'll receive warnings at 40/50 calls. At 50, add a payment method to continue.",
        "quick_start": f"curl -H 'Authorization: Bearer {key_data['raw_key']}' https://api.harrisoncollab.com/v1/regime/live/BTCUSDT",
    }


@app.get("/v1/usage")
async def usage_dashboard(key_info: dict = Depends(require_auth)):
    """Check usage stats for your API key."""
    tier_config = get_tier_config(key_info["tier"])

    if key_info["tier"] == "agent":
        usage = metered_tracker.get_usage(key_info["key_id"], tier_config)
        monthly = metered_tracker.get_monthly_estimate(key_info["key_id"], tier_config)
        return {
            "tier": "agent",
            "today": usage["today"],
            "this_month": monthly,
            "by_endpoint": usage["by_endpoint"],
        }

    # Non-agent tiers: basic usage from rate limiter
    usage = limiter.get_usage(key_info["key_id"], key_info["tier"])
    return {
        "tier": key_info["tier"],
        "today": {
            "total_calls": usage["used"],
            "daily_limit": usage["limit"],
            "remaining": usage["remaining"],
        },
    }


# ---------------------------------------------------------------------------
# Webhook Endpoints
# ---------------------------------------------------------------------------

from webhooks import register_webhook, list_webhooks, delete_webhook, dispatch_webhook, get_webhook, sign_payload, VALID_EVENTS


class WebhookRegisterRequest(BaseModel):
    url: str = Field(..., description="URL to receive webhook payloads")
    symbols: list[str] = Field(..., min_length=1, max_length=10, description="Binance symbols to watch")
    events: list[str] = Field(..., min_length=1, description="Event types to subscribe to")
    secret: str = Field(..., description="Signing secret for HMAC-SHA256 verification")


@app.post("/v1/webhooks/register", tags=["Webhooks"])
async def webhook_register(body: WebhookRegisterRequest, key_info: dict = Depends(require_auth)):
    """Register a webhook for regime change notifications."""
    result = register_webhook(
        api_key_id=key_info["key_id"],
        url=body.url,
        symbols=body.symbols,
        events=body.events,
        secret=body.secret,
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail={"error": {"type": "webhook_error", "message": result["error"]}})
    return result


@app.get("/v1/webhooks", tags=["Webhooks"])
async def webhook_list(key_info: dict = Depends(require_auth)):
    """List all registered webhooks for this API key."""
    return {"webhooks": list_webhooks(key_info["key_id"])}


@app.delete("/v1/webhooks/{webhook_id}", tags=["Webhooks"])
async def webhook_delete(webhook_id: str, key_info: dict = Depends(require_auth)):
    """Deactivate a webhook."""
    if delete_webhook(key_info["key_id"], webhook_id):
        return {"deleted": True, "webhook_id": webhook_id}
    raise HTTPException(status_code=404, detail={"error": {"type": "not_found", "message": f"Webhook {webhook_id} not found."}})


@app.post("/v1/webhooks/{webhook_id}/test", tags=["Webhooks"])
async def webhook_test(webhook_id: str, key_info: dict = Depends(require_auth)):
    """Send a test payload to verify the webhook URL works."""
    wh = get_webhook(webhook_id)
    if not wh or wh["api_key_id"] != key_info["key_id"]:
        raise HTTPException(status_code=404, detail={"error": {"type": "not_found", "message": "Webhook not found."}})

    test_payload = {
        "event": "test",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "symbol": wh["symbols"][0] if wh["symbols"] else "BTCUSDT",
        "message": "This is a test webhook payload from ReNoUn.",
    }
    dispatch_webhook(wh, test_payload)
    return {"sent": True, "webhook_id": webhook_id, "url": wh["url"]}


# ---------------------------------------------------------------------------
# Agent Leaderboard
# ---------------------------------------------------------------------------

@app.get("/v1/agents/leaderboard", tags=["Agents"])
async def agent_leaderboard():
    """Public leaderboard of most active agents. No auth required."""
    from auth import _load_keys
    from datetime import datetime, timezone

    data = _load_keys()
    agents = []
    total_agents = 0

    for entry in data["keys"]:
        if entry.get("tier") != "agent" or not entry.get("active"):
            continue
        total_agents += 1
        if entry.get("public", True) is False:
            continue

        agents.append({
            "agent_name": entry.get("agent_name", "unnamed"),
            "member_since": entry.get("created_at", "")[:7],  # YYYY-MM
        })

    # Sort by name for now (usage tracking would require more state)
    agents.sort(key=lambda a: a["agent_name"])

    # Add rank
    for i, agent in enumerate(agents):
        agent["rank"] = i + 1

    return {
        "leaderboard": agents[:20],
        "stats": {
            "total_agents": total_agents,
            "regime_accuracy": "100% bounded",
        },
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Success / Welcome Page
# ---------------------------------------------------------------------------

WELCOME_PAGE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Welcome to ReNoUn Pro</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
*, *::before, *::after {{ margin: 0; padding: 0; box-sizing: border-box; }}
:root {{
  --bg: #FFFFF0; --bg-card: #FFFFFF; --border: #E8E5DC;
  --text: #0B1D3A; --text-dim: #4A5568; --text-muted: #8B92A0;
  --accent: #7C9A6E; --radius: 12px;
}}
body {{ font-family: 'Inter', -apple-system, sans-serif; background: var(--bg); color: var(--text); line-height: 1.6; min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 40px 20px; }}
a {{ color: var(--accent); text-decoration: none; }}
code {{ font-family: 'JetBrains Mono', monospace; }}
.card {{ background: var(--bg-card); border: 1px solid var(--border); border-radius: var(--radius); max-width: 600px; width: 100%; overflow: hidden; box-shadow: 0 4px 24px rgba(0,0,0,0.06); }}
.header {{ background: #0B1D3A; padding: 32px 40px; text-align: center; }}
.header h1 {{ color: #FFFFF0; font-size: 24px; font-weight: 700; letter-spacing: -0.02em; }}
.header p {{ color: #8B92A0; font-size: 14px; margin-top: 8px; }}
.body {{ padding: 40px; }}
.body h2 {{ font-size: 20px; font-weight: 600; margin-bottom: 16px; }}
.body p {{ color: var(--text-dim); font-size: 15px; margin-bottom: 20px; }}
.key-box {{ background: #F8F7F0; border: 1px solid var(--border); border-radius: 8px; padding: 16px 20px; margin-bottom: 24px; position: relative; }}
.key-box label {{ display: block; color: var(--text-muted); font-size: 12px; font-weight: 500; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 6px; }}
.key-box code {{ font-size: 13px; word-break: break-all; line-height: 1.5; }}
.key-box .copy-btn {{ position: absolute; top: 12px; right: 12px; background: var(--accent); color: white; border: none; border-radius: 6px; padding: 6px 14px; font-size: 12px; font-weight: 500; cursor: pointer; }}
.key-box .copy-btn:hover {{ background: #6A8A5E; }}
.tier-badge {{ display: inline-block; background: #F0F7ED; border: 1px solid #D4E5CC; border-radius: 8px; padding: 12px 20px; margin-bottom: 24px; color: var(--text-dim); font-size: 14px; }}
.tier-badge strong {{ color: var(--accent); }}
.code-block {{ background: #1a1a2e; border-radius: 8px; padding: 16px 20px; margin-bottom: 24px; overflow-x: auto; }}
.code-block pre {{ color: #e0e0e0; font-family: 'JetBrains Mono', monospace; font-size: 12px; line-height: 1.6; white-space: pre-wrap; margin: 0; }}
.links {{ font-size: 14px; color: var(--text-dim); }}
.links a {{ margin-right: 20px; }}
.footer {{ padding: 20px 40px; border-top: 1px solid var(--border); text-align: center; }}
.footer p {{ color: var(--text-muted); font-size: 12px; }}
.error-msg {{ text-align: center; padding: 60px 40px; }}
.error-msg h2 {{ color: var(--text-dim); font-weight: 500; }}
</style>
</head>
<body>
<div class="card">
<div class="header">
  <h1>ReNoUn</h1>
  <p>Structural Observability for AI Conversations</p>
</div>
{content}
<div class="footer">
  <p>Harrison Collab &bull; <a href="https://harrisoncollab.com">harrisoncollab.com</a> &bull; Patent Pending #63/923,592</p>
</div>
</div>
<script>
function copyKey() {{
  const key = document.getElementById('api-key').textContent;
  navigator.clipboard.writeText(key).then(() => {{
    const btn = document.querySelector('.copy-btn');
    btn.textContent = 'Copied!';
    setTimeout(() => btn.textContent = 'Copy', 2000);
  }});
}}
</script>
</body>
</html>"""


def _welcome_content(raw_key: str, tier: str) -> str:
    return f"""<div class="body">
  <h2>&#10003; Welcome to ReNoUn Pro</h2>
  <p>Your subscription is active. Here's your API key &mdash; store it securely, as it cannot be recovered.</p>
  <div class="key-box">
    <label>Your API Key</label>
    <code id="api-key">{raw_key}</code>
    <button class="copy-btn" onclick="copyKey()">Copy</button>
  </div>
  <div class="tier-badge">
    <strong>&#10003; {tier.title()} Tier</strong> &mdash; Full access to analyze, health_check, compare, and pattern_query. 1,000 req/day.
  </div>
  <h3 style="font-size:16px;font-weight:600;margin-bottom:12px;">Quick Start</h3>
  <div class="code-block"><pre>curl -X POST https://api.harrisoncollab.com/v1/health-check \\
  -H "Authorization: Bearer {raw_key}" \\
  -H "Content-Type: application/json" \\
  -d '{{"utterances": [
    {{"speaker": "user", "text": "Hello"}},
    {{"speaker": "assistant", "text": "Hi there"}},
    {{"speaker": "user", "text": "How are you?"}}
  ]}}'</pre></div>
  <div class="links">
    <a href="https://api.harrisoncollab.com/docs">API Docs</a>
    <a href="https://pypi.org/project/renoun-mcp/">pip install renoun-mcp</a>
    <a href="https://github.com/98lukehall/renoun-mcp">GitHub</a>
  </div>
</div>"""


def _error_content(message: str) -> str:
    return f"""<div class="error-msg">
  <h2>{message}</h2>
  <p style="color:#8B92A0;margin-top:16px;">If you just completed checkout, your API key has been emailed to you.<br>
  You can also contact <a href="mailto:98lukehall@gmail.com">support</a> for help.</p>
</div>"""


@app.get("/welcome", response_class=HTMLResponse)
async def welcome_page(session_id: str = ""):
    """Success page after Stripe checkout. Displays the provisioned API key."""
    if not session_id:
        content = _error_content("Missing session ID")
        return HTMLResponse(WELCOME_PAGE_HTML.format(content=content))

    key_data = get_provisioned_key(session_id)

    if key_data:
        content = _welcome_content(key_data["raw_key"], key_data["tier"])
    else:
        # Key might have been provisioned but server restarted, or session_id is invalid
        content = _error_content("Session not found or expired")

    return HTMLResponse(WELCOME_PAGE_HTML.format(content=content))


# ---------------------------------------------------------------------------
# Smithery server-card (MUST be outside try block — always available)
# ---------------------------------------------------------------------------

@app.get("/.well-known/mcp/server-card.json")
async def mcp_server_card():
    """MCP server card for Smithery discovery. No auth required."""
    return {
        "name": "renoun",
        "description": "Structural risk telemetry for crypto markets. Classifies regimes (bounded/active/unstable) with 100% bounded regime accuracy across 4700+ graded predictions. Estimates regime stability half-life. Pre-trade risk gate for trading agents.",
        "version": TOOL_VERSION,
        "homepage": "https://harrisoncollab.com",
        "repository": "https://github.com/98lukehall/renoun-mcp",
        "transport": {
            "type": "streamable-http",
            "url": "/mcp",
            "authentication": {
                "type": "bearer",
                "description": "API key (rn_agent_... or rn_live_...). Get a free key: POST /v1/keys/provision. 50 free calls/day.",
            },
        },
        "tools": [
            {
                "name": "renoun_analyze",
                "description": "Full 17-channel structural analysis of conversations. Returns DHS, 8 constellation patterns, breakthrough moments, and actionable recommendations.",
            },
            {
                "name": "renoun_health_check",
                "description": "Sub-50ms structural triage. Returns one health score, one pattern, one summary.",
            },
            {
                "name": "renoun_compare",
                "description": "Structural A/B test between two conversations. DHS delta, constellation transitions, channel shifts.",
            },
            {
                "name": "renoun_pattern_query",
                "description": "Longitudinal pattern history. Save, query, filter, and trend analysis results over time.",
            },
            {
                "name": "renoun_steer",
                "description": "Real-time inference steering. Rolling window monitoring with automatic signals when structural thresholds are crossed.",
            },
            {
                "name": "renoun_finance_analyze",
                "description": "Full 17-channel structural analysis of OHLCV data. Returns DHS, constellations, stress metrics, and exposure scalar. 100% bounded regime accuracy across 4700+ graded predictions.",
            },
            {
                "name": "renoun_agent_monitor",
                "description": "Real-time structural health monitoring for AI agent sessions. Feed trace events and receive alerts for stuck loops, oversight loss, scattering, and cascading errors.",
            },
            {
                "name": "renoun_alignment_classify",
                "description": "Structural alignment classification. Classifies conversations as integrative, suppressive, fragmented, or rigid with corrigibility scoring.",
            },
        ],
    }


# ---------------------------------------------------------------------------
# MCP HTTP Transport (for Smithery and other MCP-over-HTTP clients)
# ---------------------------------------------------------------------------
#
# Uses Streamable HTTP transport (POST-based) which is what Smithery and
# modern MCP clients expect. Handles GET, POST, DELETE on /mcp.
# ---------------------------------------------------------------------------

try:
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
    from starlette.types import ASGIApp, Receive, Scope, Send
    from server import build_mcp_server as _build_mcp_server, TOOL_DEFS

    _mcp_server = _build_mcp_server()
    _session_manager = StreamableHTTPSessionManager(
        app=_mcp_server,
        json_response=True,
        stateless=True,
    )

    async def _mcp_asgi_app(scope: Scope, receive: Receive, send: Send):
        """Raw ASGI app: auth check then delegate to MCP session manager."""
        import json as _json

        # Only handle http requests
        if scope["type"] != "http":
            return

        # Extract auth header from ASGI scope
        headers = dict(scope.get("headers", []))
        auth_value = headers.get(b"authorization", b"").decode()

        method = scope.get("method", "GET")

        # Unauthenticated GET → friendly discovery page (browsers, crawlers, agents)
        if not auth_value.startswith("Bearer ") and method == "GET":
            body = _json.dumps({
                "name": "ReNoUn MCP Server",
                "description": "Crypto regime classifier for trading agents. 100% bounded regime accuracy.",
                "protocol": "MCP (Model Context Protocol)",
                "transport": "streamable-http",
                "registry": "https://registry.modelcontextprotocol.io",
                "registry_name": "io.github.98lukehall/renoun",
                "tools": 9,
                "auth": {
                    "type": "bearer",
                    "provision": "POST /v1/keys/provision",
                    "free_tier": "50 calls/day, no credit card",
                    "example": "curl -X POST /v1/keys/provision -H 'Content-Type: application/json' -d '{\"email\":\"you@example.com\",\"tier\":\"agent\",\"agent_name\":\"my-agent\"}'"
                },
                "docs": "https://harrisoncollab.com/agents",
                "status": "https://api.harrisoncollab.com/v1/status"
            }, indent=2).encode()
            await send({"type": "http.response.start", "status": 200, "headers": [[b"content-type", b"application/json"]]})
            await send({"type": "http.response.body", "body": body})
            return

        if not auth_value.startswith("Bearer "):
            body = _json.dumps({"error": {"type": "auth_error", "message": "Missing Authorization header. Use: Bearer rn_agent_...", "action": "Add header: Authorization: Bearer <your-api-key>"}}).encode()
            await send({"type": "http.response.start", "status": 401, "headers": [[b"content-type", b"application/json"]]})
            await send({"type": "http.response.body", "body": body})
            return

        key_info = validate_key(auth_value[7:].strip())
        if not key_info:
            body = _json.dumps({"error": {"type": "auth_error", "message": "Invalid or revoked API key.", "action": "Check your API key or request a new one."}}).encode()
            await send({"type": "http.response.start", "status": 401, "headers": [[b"content-type", b"application/json"]]})
            await send({"type": "http.response.body", "body": body})
            return

        await _session_manager.handle_request(scope, receive, send)

    # Raw ASGI middleware class — intercepts /mcp BEFORE Starlette routing
    # so we get scope/receive/send directly (no 307 redirect, no Request wrapper)
    class _MCPInterceptMiddleware:
        """ASGI middleware that routes /mcp to MCP session manager."""
        def __init__(self, app: ASGIApp):
            self.app = app

        async def __call__(self, scope: Scope, receive: Receive, send: Send):
            if scope["type"] == "http" and scope.get("path", "").rstrip("/") == "/mcp":
                await _mcp_asgi_app(scope, receive, send)
            else:
                await self.app(scope, receive, send)

    app.add_middleware(_MCPInterceptMiddleware)

    @app.on_event("startup")
    async def _start_mcp_session_manager():
        app.state._mcp_manager_ctx = _session_manager.run()
        await app.state._mcp_manager_ctx.__aenter__()

    @app.on_event("shutdown")
    async def _stop_mcp_session_manager():
        if hasattr(app.state, '_mcp_manager_ctx'):
            await app.state._mcp_manager_ctx.__aexit__(None, None, None)

    print("MCP Streamable HTTP transport enabled at /mcp", flush=True)

except ImportError as _mcp_err:
    print(f"MCP library not available — HTTP transport disabled: {_mcp_err}", flush=True)


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
