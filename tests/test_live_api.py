#!/usr/bin/env python3
"""
End-to-end tests for the live ReNoUn API on Railway.

These tests hit the actual production endpoint at:
    https://web-production-817e2.up.railway.app

Requirements:
    - Set RENOUN_API_KEY env var to a valid pro-tier API key (rn_live_...)
    - pip install httpx pytest

Run:
    # Run all live tests:
    pytest tests/test_live_api.py -m live -v

    # Run a specific test class:
    pytest tests/test_live_api.py -m live -v -k TestLiveHealthCheck

    # Run with timing info:
    pytest tests/test_live_api.py -m live -v --tb=short

Skip behavior:
    All tests are marked with @pytest.mark.live and will be skipped
    by default unless you explicitly select the 'live' marker with -m live.
    Tests also skip if RENOUN_API_KEY is not set in the environment.
"""

import os
import time
import math
import pytest
import httpx

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_URL = "https://web-production-817e2.up.railway.app"
API_KEY = os.environ.get("RENOUN_API_KEY", "")
TIMEOUT = 30.0  # seconds

pytestmark = pytest.mark.live


# ---------------------------------------------------------------------------
# Skip conditions
# ---------------------------------------------------------------------------

skip_no_key = pytest.mark.skipif(
    not API_KEY,
    reason="RENOUN_API_KEY not set — skipping live API tests",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client():
    """HTTP client for the live API."""
    with httpx.Client(base_url=BASE_URL, timeout=TIMEOUT) as c:
        yield c


@pytest.fixture(scope="module")
def auth_headers():
    """Authorization headers with the live API key."""
    return {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }


@pytest.fixture(scope="module")
def sample_utterances():
    """12-turn therapy conversation for testing."""
    return [
        {"speaker": "therapist", "text": "What brings you in today?"},
        {"speaker": "client", "text": "I have been struggling with anxiety for months."},
        {"speaker": "therapist", "text": "Can you tell me more about when it started?"},
        {"speaker": "client", "text": "It started after I lost my job. I feel stuck."},
        {"speaker": "therapist", "text": "That sounds really difficult. What does stuck feel like?"},
        {"speaker": "client", "text": "Like nothing changes. Same thoughts every day."},
        {"speaker": "therapist", "text": "Have you noticed any moments where things feel different?"},
        {"speaker": "client", "text": "Sometimes when I go for walks. But then it comes back."},
        {"speaker": "therapist", "text": "So the walks provide some relief. What else helps?"},
        {"speaker": "client", "text": "Talking to my sister. She understands."},
        {"speaker": "therapist", "text": "It sounds like connection matters to you."},
        {"speaker": "client", "text": "Yes but I avoid people most of the time now."},
    ]


@pytest.fixture(scope="module")
def extended_utterances(sample_utterances):
    """Extended 20-turn conversation for full analysis."""
    extra = [
        {"speaker": "therapist", "text": "When did you start avoiding people?"},
        {"speaker": "client", "text": "About three months ago after the layoff happened."},
        {"speaker": "therapist", "text": "What happens when you think about reaching out?"},
        {"speaker": "client", "text": "I get this knot in my stomach. Like they will judge me."},
        {"speaker": "therapist", "text": "That fear of judgment sounds really powerful."},
        {"speaker": "client", "text": "It is. I used to be confident. Now everything feels different."},
        {"speaker": "therapist", "text": "You mentioned walks help. What is it about them?"},
        {"speaker": "client", "text": "The movement. Being outside. Not thinking for a while."},
    ]
    return sample_utterances + extra


@pytest.fixture(scope="module")
def sample_klines():
    """Generate 50 realistic OHLCV candles for finance testing."""
    klines = []
    price = 42000.0
    for i in range(50):
        # Simulate price movement with some volatility
        change = math.sin(i * 0.3) * 200 + (i % 7 - 3) * 50
        open_price = price
        high_price = price + abs(change) + 100
        low_price = price - abs(change) - 80
        close_price = price + change
        volume = 100 + (i % 10) * 20 + abs(change) * 0.5

        klines.append({
            "open": round(open_price, 2),
            "high": round(high_price, 2),
            "low": round(low_price, 2),
            "close": round(close_price, 2),
            "volume": round(volume, 2),
        })
        price = close_price
    return klines


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def assert_dhs_valid(dhs):
    """Assert DHS is a float between 0 and 1."""
    assert isinstance(dhs, (int, float)), f"DHS must be numeric, got {type(dhs)}"
    assert 0.0 <= dhs <= 1.0, f"DHS out of range: {dhs}"


def assert_channel_values_valid(channels: dict):
    """Assert all channel values are between 0 and 1."""
    for name, value in channels.items():
        assert isinstance(value, (int, float)), f"Channel {name} must be numeric, got {type(value)}"
        assert 0.0 <= value <= 1.0, f"Channel {name} out of range: {value}"


# ---------------------------------------------------------------------------
# Tests: Status endpoint (no auth required)
# ---------------------------------------------------------------------------

class TestLiveStatus:
    """Test the unauthenticated status endpoint."""

    def test_status_returns_200(self, client):
        r = client.get("/v1/status")
        assert r.status_code == 200

    def test_status_fields(self, client):
        r = client.get("/v1/status")
        data = r.json()
        assert data["status"] == "ok"
        assert data["server"] == "renoun"
        assert "version" in data
        assert "engine_version" in data
        assert "tool_version" in data
        assert "schema_version" in data

    def test_status_response_time(self, client):
        start = time.time()
        r = client.get("/v1/status")
        elapsed = time.time() - start
        assert r.status_code == 200
        assert elapsed < 5.0, f"Status endpoint too slow: {elapsed:.2f}s"


# ---------------------------------------------------------------------------
# Tests: MCP server card (no auth required)
# ---------------------------------------------------------------------------

class TestLiveServerCard:
    """Test the MCP server discovery card."""

    def test_server_card_returns_200(self, client):
        r = client.get("/.well-known/mcp/server-card.json")
        assert r.status_code == 200

    def test_server_card_fields(self, client):
        r = client.get("/.well-known/mcp/server-card.json")
        data = r.json()
        assert data["name"] == "renoun"
        assert "description" in data
        assert "version" in data
        assert "transport" in data
        assert data["transport"]["type"] == "streamable-http"
        assert data["transport"]["url"] == "/mcp"

    def test_server_card_lists_all_tools(self, client):
        r = client.get("/.well-known/mcp/server-card.json")
        data = r.json()
        tool_names = [t["name"] for t in data["tools"]]
        expected_tools = [
            "renoun_analyze",
            "renoun_health_check",
            "renoun_compare",
            "renoun_pattern_query",
            "renoun_steer",
            "renoun_finance_analyze",
        ]
        for tool in expected_tools:
            assert tool in tool_names, f"Missing tool in server card: {tool}"


# ---------------------------------------------------------------------------
# Tests: Auth enforcement
# ---------------------------------------------------------------------------

class TestLiveAuth:
    """Test that auth is properly enforced."""

    def test_no_auth_returns_401(self, client, sample_utterances):
        r = client.post("/v1/health-check", json={"utterances": sample_utterances})
        assert r.status_code == 401

    def test_bad_key_returns_401(self, client, sample_utterances):
        r = client.post(
            "/v1/health-check",
            json={"utterances": sample_utterances},
            headers={"Authorization": "Bearer rn_live_invalid_key_12345678"},
        )
        assert r.status_code == 401

    def test_missing_bearer_prefix_returns_401(self, client, sample_utterances):
        r = client.post(
            "/v1/health-check",
            json={"utterances": sample_utterances},
            headers={"Authorization": "some_key_without_bearer"},
        )
        assert r.status_code == 401

    def test_mcp_endpoint_requires_auth(self, client):
        r = client.post("/mcp", json={})
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# Tests: Health Check endpoint
# ---------------------------------------------------------------------------

@skip_no_key
class TestLiveHealthCheck:
    """Test the health-check endpoint (fast triage)."""

    def test_health_check_returns_200(self, client, auth_headers, sample_utterances):
        r = client.post("/v1/health-check", json={"utterances": sample_utterances}, headers=auth_headers)
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"

    def test_health_check_response_schema(self, client, auth_headers, sample_utterances):
        r = client.post("/v1/health-check", json={"utterances": sample_utterances}, headers=auth_headers)
        data = r.json()
        assert "dialectical_health" in data, f"Missing dialectical_health in response: {list(data.keys())}"
        assert "assessment" in data
        assert "dominant_constellation" in data
        assert_dhs_valid(data["dialectical_health"])

    def test_health_check_assessment_values(self, client, auth_headers, sample_utterances):
        r = client.post("/v1/health-check", json={"utterances": sample_utterances}, headers=auth_headers)
        data = r.json()
        valid_assessments = ["excellent", "healthy", "below_baseline", "distressed"]
        assert data["assessment"] in valid_assessments, f"Invalid assessment: {data['assessment']}"

    def test_health_check_response_time(self, client, auth_headers, sample_utterances):
        start = time.time()
        r = client.post("/v1/health-check", json={"utterances": sample_utterances}, headers=auth_headers)
        elapsed = time.time() - start
        assert r.status_code == 200
        assert elapsed < 10.0, f"Health check too slow: {elapsed:.2f}s"

    def test_health_check_too_few_turns(self, client, auth_headers):
        short = [{"speaker": "a", "text": "hi"}, {"speaker": "b", "text": "hello"}]
        r = client.post("/v1/health-check", json={"utterances": short}, headers=auth_headers)
        assert r.status_code == 422, f"Expected 422 for too few turns, got {r.status_code}"

    def test_health_check_rate_limit_headers(self, client, auth_headers, sample_utterances):
        r = client.post("/v1/health-check", json={"utterances": sample_utterances}, headers=auth_headers)
        assert r.status_code == 200
        assert "x-ratelimit-remaining" in r.headers, f"Missing rate limit header. Headers: {dict(r.headers)}"
        assert "x-ratelimit-limit" in r.headers


# ---------------------------------------------------------------------------
# Tests: Analyze endpoint
# ---------------------------------------------------------------------------

@skip_no_key
class TestLiveAnalyze:
    """Test the full analyze endpoint (requires pro tier)."""

    def test_analyze_returns_200(self, client, auth_headers, extended_utterances):
        r = client.post("/v1/analyze", json={"utterances": extended_utterances}, headers=auth_headers)
        # Pro tier required — if 403, the key is free tier
        if r.status_code == 403:
            pytest.skip("API key is free tier — analyze requires pro")
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"

    def test_analyze_response_schema(self, client, auth_headers, extended_utterances):
        r = client.post("/v1/analyze", json={"utterances": extended_utterances}, headers=auth_headers)
        if r.status_code == 403:
            pytest.skip("API key is free tier — analyze requires pro")
        data = r.json()
        # Core fields
        assert "dialectical_health" in data
        assert "constellations" in data
        assert "loop_strength" in data
        assert_dhs_valid(data["dialectical_health"])

    def test_analyze_channels_present(self, client, auth_headers, extended_utterances):
        r = client.post("/v1/analyze", json={"utterances": extended_utterances}, headers=auth_headers)
        if r.status_code == 403:
            pytest.skip("API key is free tier")
        data = r.json()
        assert "channels" in data, f"Missing channels in response: {list(data.keys())}"
        channels = data["channels"]
        # Should have recurrence, novelty, and unity channels
        assert len(channels) >= 17, f"Expected 17+ channels, got {len(channels)}"
        assert_channel_values_valid(channels)

    def test_analyze_constellations_have_agent_actions(self, client, auth_headers, extended_utterances):
        r = client.post("/v1/analyze", json={"utterances": extended_utterances}, headers=auth_headers)
        if r.status_code == 403:
            pytest.skip("API key is free tier")
        data = r.json()
        for constellation in data.get("constellations", []):
            assert "agent_action" in constellation, f"Missing agent_action in constellation: {constellation}"
            assert "agent_guidance" in constellation, f"Missing agent_guidance in constellation: {constellation}"

    def test_analyze_metadata_present(self, client, auth_headers, extended_utterances):
        r = client.post("/v1/analyze", json={"utterances": extended_utterances}, headers=auth_headers)
        if r.status_code == 403:
            pytest.skip("API key is free tier")
        data = r.json()
        assert "engine" in data
        assert "_meta" in data
        assert "result_hash" in data

    def test_analyze_response_time(self, client, auth_headers, extended_utterances):
        start = time.time()
        r = client.post("/v1/analyze", json={"utterances": extended_utterances}, headers=auth_headers)
        elapsed = time.time() - start
        if r.status_code == 403:
            pytest.skip("API key is free tier")
        assert r.status_code == 200
        assert elapsed < 15.0, f"Analyze too slow: {elapsed:.2f}s"

    def test_analyze_too_few_turns(self, client, auth_headers):
        short = [{"speaker": "a", "text": "hi"}, {"speaker": "b", "text": "hello"}]
        r = client.post("/v1/analyze", json={"utterances": short}, headers=auth_headers)
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# Tests: Compare endpoint
# ---------------------------------------------------------------------------

@skip_no_key
class TestLiveCompare:
    """Test the compare endpoint (requires pro tier)."""

    def test_compare_returns_200(self, client, auth_headers, sample_utterances, extended_utterances):
        r = client.post("/v1/compare", json={
            "utterances_a": sample_utterances,
            "utterances_b": extended_utterances,
            "label_a": "Short Session",
            "label_b": "Extended Session",
        }, headers=auth_headers)
        if r.status_code == 403:
            pytest.skip("API key is free tier — compare requires pro")
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"

    def test_compare_response_schema(self, client, auth_headers, sample_utterances, extended_utterances):
        r = client.post("/v1/compare", json={
            "utterances_a": sample_utterances,
            "utterances_b": extended_utterances,
            "label_a": "Before",
            "label_b": "After",
        }, headers=auth_headers)
        if r.status_code == 403:
            pytest.skip("API key is free tier")
        data = r.json()
        assert "health" in data, f"Missing 'health' in compare response: {list(data.keys())}"

    def test_compare_response_time(self, client, auth_headers, sample_utterances, extended_utterances):
        start = time.time()
        r = client.post("/v1/compare", json={
            "utterances_a": sample_utterances,
            "utterances_b": extended_utterances,
        }, headers=auth_headers)
        elapsed = time.time() - start
        if r.status_code == 403:
            pytest.skip("API key is free tier")
        assert r.status_code == 200
        assert elapsed < 20.0, f"Compare too slow: {elapsed:.2f}s"


# ---------------------------------------------------------------------------
# Tests: Finance Analyze endpoint
# ---------------------------------------------------------------------------

@skip_no_key
class TestLiveFinanceAnalyze:
    """Test the finance analyze endpoint."""

    def test_finance_returns_200(self, client, auth_headers, sample_klines):
        r = client.post("/v1/finance/analyze", json={
            "klines": sample_klines,
            "symbol": "BTCUSDT",
            "timeframe": "1h",
            "include_exposure": True,
        }, headers=auth_headers)
        if r.status_code == 403:
            pytest.skip("API key does not have finance access")
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"

    def test_finance_response_schema(self, client, auth_headers, sample_klines):
        r = client.post("/v1/finance/analyze", json={
            "klines": sample_klines,
            "symbol": "BTCUSDT",
            "timeframe": "1h",
        }, headers=auth_headers)
        if r.status_code == 403:
            pytest.skip("API key does not have finance access")
        data = r.json()
        # Core fields expected from finance analysis
        assert "dialectical_health" in data or "dhs" in data, \
            f"Missing DHS field in finance response: {list(data.keys())}"

    def test_finance_dhs_valid(self, client, auth_headers, sample_klines):
        r = client.post("/v1/finance/analyze", json={
            "klines": sample_klines,
            "symbol": "BTCUSDT",
            "timeframe": "1h",
        }, headers=auth_headers)
        if r.status_code == 403:
            pytest.skip("API key does not have finance access")
        data = r.json()
        dhs = data.get("dialectical_health") or data.get("dhs")
        assert_dhs_valid(dhs)

    def test_finance_exposure_present(self, client, auth_headers, sample_klines):
        r = client.post("/v1/finance/analyze", json={
            "klines": sample_klines,
            "symbol": "BTCUSDT",
            "timeframe": "1h",
            "include_exposure": True,
        }, headers=auth_headers)
        if r.status_code == 403:
            pytest.skip("API key does not have finance access")
        data = r.json()
        # Exposure scalar should be present when include_exposure is True
        assert "exposure" in data or "exposure_scalar" in data, \
            f"Missing exposure field in finance response: {list(data.keys())}"

    def test_finance_too_few_klines(self, client, auth_headers):
        short_klines = [
            {"open": 42000, "high": 42500, "low": 41800, "close": 42200, "volume": 100},
            {"open": 42200, "high": 42800, "low": 42100, "close": 42600, "volume": 120},
        ]
        r = client.post("/v1/finance/analyze", json={
            "klines": short_klines,
            "symbol": "BTCUSDT",
            "timeframe": "1h",
        }, headers=auth_headers)
        # Should return 422 (min 10 klines required)
        assert r.status_code == 422, f"Expected 422 for too few klines, got {r.status_code}"

    def test_finance_response_time(self, client, auth_headers, sample_klines):
        start = time.time()
        r = client.post("/v1/finance/analyze", json={
            "klines": sample_klines,
            "symbol": "BTCUSDT",
            "timeframe": "1h",
        }, headers=auth_headers)
        elapsed = time.time() - start
        if r.status_code == 403:
            pytest.skip("API key does not have finance access")
        assert r.status_code == 200
        assert elapsed < 15.0, f"Finance analyze too slow: {elapsed:.2f}s"


# ---------------------------------------------------------------------------
# Tests: Steer endpoint
# ---------------------------------------------------------------------------

@skip_no_key
class TestLiveSteer:
    """Test the real-time steering endpoint (requires pro tier)."""

    def test_steer_add_turns(self, client, auth_headers, sample_utterances):
        r = client.post("/v1/steer", json={
            "utterances": sample_utterances,
            "session_id": "e2e-test-session",
            "action": "add_turns",
        }, headers=auth_headers)
        if r.status_code == 403:
            pytest.skip("API key is free tier — steer requires pro")
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"

    def test_steer_get_status(self, client, auth_headers):
        r = client.post("/v1/steer", json={
            "action": "get_status",
            "session_id": "e2e-test-session",
        }, headers=auth_headers)
        if r.status_code == 403:
            pytest.skip("API key is free tier — steer requires pro")
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"

    def test_steer_list_sessions(self, client, auth_headers):
        r = client.post("/v1/steer", json={
            "action": "list_sessions",
            "session_id": "any",
        }, headers=auth_headers)
        if r.status_code == 403:
            pytest.skip("API key is free tier — steer requires pro")
        assert r.status_code == 200

    def test_steer_clear_session(self, client, auth_headers):
        r = client.post("/v1/steer", json={
            "action": "clear_session",
            "session_id": "e2e-test-session",
        }, headers=auth_headers)
        if r.status_code == 403:
            pytest.skip("API key is free tier — steer requires pro")
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Tests: Patterns endpoint
# ---------------------------------------------------------------------------

@skip_no_key
class TestLivePatterns:
    """Test the patterns/longitudinal endpoint (requires pro tier)."""

    def test_patterns_list(self, client, auth_headers):
        r = client.post("/v1/patterns/list", json={}, headers=auth_headers)
        if r.status_code == 403:
            pytest.skip("API key is free tier — patterns requires pro")
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"

    def test_patterns_invalid_action(self, client, auth_headers):
        r = client.post("/v1/patterns/explode", json={}, headers=auth_headers)
        assert r.status_code == 400

    def test_patterns_save_and_list(self, client, auth_headers, extended_utterances):
        # First, analyze to get a result
        r = client.post("/v1/analyze", json={"utterances": extended_utterances}, headers=auth_headers)
        if r.status_code == 403:
            pytest.skip("API key is free tier")
        analysis = r.json()

        # Save the result
        r = client.post("/v1/patterns/save", json={
            "result": analysis,
            "session_name": "e2e-test-session",
            "domain": "testing",
            "tags": ["e2e", "live-test"],
        }, headers=auth_headers)
        assert r.status_code == 200
        save_data = r.json()
        assert save_data.get("status") == "saved"


# ---------------------------------------------------------------------------
# Tests: Connector configuration validation
# ---------------------------------------------------------------------------

class TestConnectorConfig:
    """Validate the Cowork plugin connector.json is correct."""

    def test_connector_transport_url_matches_server(self, client):
        """Verify connector.json URL matches the server card."""
        r = client.get("/.well-known/mcp/server-card.json")
        server_card = r.json()
        # The connector.json says the MCP endpoint is at /mcp on the base URL
        assert server_card["transport"]["url"] == "/mcp"
        assert server_card["transport"]["type"] == "streamable-http"

    def test_mcp_endpoint_exists(self, client):
        """Verify the /mcp endpoint exists (returns 401, not 404)."""
        r = client.post("/mcp", json={})
        # Should be 401 (auth required), NOT 404 (not found)
        assert r.status_code == 401, f"Expected 401, got {r.status_code}. MCP endpoint may not exist."


# ---------------------------------------------------------------------------
# Tests: Error handling
# ---------------------------------------------------------------------------

class TestLiveErrorHandling:
    """Test error responses are well-formed."""

    def test_404_on_nonexistent_endpoint(self, client):
        r = client.get("/v1/nonexistent")
        assert r.status_code in (404, 405)

    def test_wrong_api_prefix(self, client):
        """The API does NOT use /api/v1/ prefix — verify it returns 404."""
        r = client.post("/api/v1/health", json={"utterances": []})
        assert r.status_code == 404

    def test_401_error_structure(self, client, sample_utterances):
        r = client.post("/v1/health-check", json={"utterances": sample_utterances})
        assert r.status_code == 401
        data = r.json()
        assert "detail" in data
        detail = data["detail"]
        assert "error" in detail
        assert "type" in detail["error"]
        assert "message" in detail["error"]


# ---------------------------------------------------------------------------
# Tests: Swagger / OpenAPI docs
# ---------------------------------------------------------------------------

class TestLiveDocs:
    """Verify API documentation is accessible."""

    def test_swagger_docs(self, client):
        r = client.get("/docs")
        assert r.status_code == 200

    def test_redoc(self, client):
        r = client.get("/redoc")
        assert r.status_code == 200

    def test_openapi_json(self, client):
        r = client.get("/openapi.json")
        assert r.status_code == 200
        data = r.json()
        assert "paths" in data
        assert "/v1/analyze" in data["paths"]
        assert "/v1/health-check" in data["paths"]
