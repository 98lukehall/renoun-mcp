#!/usr/bin/env python3
"""
Integration tests for ReNoUn HTTP API.

Tests all endpoints with authentication, rate limiting, and tier restrictions.
Uses FastAPI TestClient — no actual server needed.

Run:
    python3 tests/test_api.py
    # or
    pytest tests/test_api.py -v
"""

import sys
import os
import json
import shutil
import tempfile

# Ensure we can import from the parent directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Isolate test state — set HOME before importing anything that uses it
_orig_home = os.environ.get("HOME")
_tmpdir = tempfile.mkdtemp(prefix="renoun_api_test_")
os.environ["HOME"] = _tmpdir

from fastapi.testclient import TestClient
from api import app
from auth import create_key
from rate_limiter import limiter


# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------

SAMPLE_UTTERANCES = [
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

client = TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def auth_header(raw_key: str) -> dict:
    return {"Authorization": f"Bearer {raw_key}"}


def setup_keys():
    """Create test keys for each tier."""
    free = create_key(tier="free", owner="test-free")
    pro = create_key(tier="pro", owner="test-pro")
    enterprise = create_key(tier="enterprise", owner="test-enterprise")
    return free["raw_key"], pro["raw_key"], enterprise["raw_key"]


FREE_KEY, PRO_KEY, ENTERPRISE_KEY = setup_keys()


# ---------------------------------------------------------------------------
# Tests: Status endpoint (no auth)
# ---------------------------------------------------------------------------

class TestStatus:

    def test_status_no_auth(self):
        r = client.get("/v1/status")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert data["server"] == "renoun"
        assert "version" in data


# ---------------------------------------------------------------------------
# Tests: Authentication
# ---------------------------------------------------------------------------

class TestAuth:

    def test_no_auth_header(self):
        r = client.post("/v1/health-check", json={"utterances": SAMPLE_UTTERANCES})
        assert r.status_code == 401

    def test_bad_key(self):
        r = client.post("/v1/health-check", json={"utterances": SAMPLE_UTTERANCES}, headers=auth_header("rn_live_invalid"))
        assert r.status_code == 401

    def test_missing_bearer_prefix(self):
        r = client.post("/v1/health-check", json={"utterances": SAMPLE_UTTERANCES}, headers={"Authorization": PRO_KEY})
        assert r.status_code == 401

    def test_valid_key(self):
        r = client.post("/v1/health-check", json={"utterances": SAMPLE_UTTERANCES}, headers=auth_header(PRO_KEY))
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Tests: Tier restrictions
# ---------------------------------------------------------------------------

class TestTiers:

    def test_free_can_health_check(self):
        r = client.post("/v1/health-check", json={"utterances": SAMPLE_UTTERANCES}, headers=auth_header(FREE_KEY))
        assert r.status_code == 200

    def test_free_cannot_analyze(self):
        r = client.post("/v1/analyze", json={"utterances": SAMPLE_UTTERANCES}, headers=auth_header(FREE_KEY))
        assert r.status_code == 403

    def test_free_cannot_compare(self):
        r = client.post("/v1/compare", json={"utterances_a": SAMPLE_UTTERANCES, "utterances_b": SAMPLE_UTTERANCES}, headers=auth_header(FREE_KEY))
        assert r.status_code == 403

    def test_pro_can_analyze(self):
        r = client.post("/v1/analyze", json={"utterances": SAMPLE_UTTERANCES}, headers=auth_header(PRO_KEY))
        assert r.status_code == 200

    def test_pro_can_compare(self):
        r = client.post("/v1/compare", json={"utterances_a": SAMPLE_UTTERANCES, "utterances_b": SAMPLE_UTTERANCES}, headers=auth_header(PRO_KEY))
        assert r.status_code == 200

    def test_enterprise_all_access(self):
        r = client.post("/v1/analyze", json={"utterances": SAMPLE_UTTERANCES}, headers=auth_header(ENTERPRISE_KEY))
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Tests: Analyze endpoint
# ---------------------------------------------------------------------------

class TestAnalyze:

    def test_full_analysis(self):
        r = client.post("/v1/analyze", json={"utterances": SAMPLE_UTTERANCES}, headers=auth_header(PRO_KEY))
        assert r.status_code == 200
        data = r.json()
        assert "dialectical_health" in data
        assert "constellations" in data
        assert "loop_strength" in data
        assert 0.0 <= data["dialectical_health"] <= 1.0

    def test_agent_actions_present(self):
        r = client.post("/v1/analyze", json={"utterances": SAMPLE_UTTERANCES}, headers=auth_header(PRO_KEY))
        data = r.json()
        for c in data.get("constellations", []):
            assert "agent_action" in c
            assert "agent_guidance" in c

    def test_metadata_present(self):
        r = client.post("/v1/analyze", json={"utterances": SAMPLE_UTTERANCES}, headers=auth_header(PRO_KEY))
        data = r.json()
        assert "engine" in data
        assert "_meta" in data
        assert "result_hash" in data

    def test_too_few_turns(self):
        short = [{"speaker": "a", "text": "hi"}, {"speaker": "b", "text": "hello"}]
        r = client.post("/v1/analyze", json={"utterances": short}, headers=auth_header(PRO_KEY))
        assert r.status_code == 422  # Pydantic validation (minItems=3)

    def test_rate_limit_headers(self):
        r = client.post("/v1/analyze", json={"utterances": SAMPLE_UTTERANCES}, headers=auth_header(PRO_KEY))
        assert "x-ratelimit-remaining" in r.headers
        assert "x-ratelimit-limit" in r.headers


# ---------------------------------------------------------------------------
# Tests: Health Check endpoint
# ---------------------------------------------------------------------------

class TestHealthCheck:

    def test_basic_health_check(self):
        r = client.post("/v1/health-check", json={"utterances": SAMPLE_UTTERANCES}, headers=auth_header(PRO_KEY))
        assert r.status_code == 200
        data = r.json()
        assert "dialectical_health" in data
        assert "assessment" in data
        assert data["assessment"] in ["excellent", "healthy", "below_baseline", "distressed"]
        assert "dominant_constellation" in data


# ---------------------------------------------------------------------------
# Tests: Compare endpoint
# ---------------------------------------------------------------------------

class TestCompare:

    def test_compare_utterances(self):
        r = client.post("/v1/compare", json={
            "utterances_a": SAMPLE_UTTERANCES,
            "utterances_b": SAMPLE_UTTERANCES,
            "label_a": "Before",
            "label_b": "After",
        }, headers=auth_header(PRO_KEY))
        assert r.status_code == 200
        data = r.json()
        assert "health" in data

    def test_mixed_mode_rejected(self):
        r = client.post("/v1/compare", json={
            "result_a": {"dialectical_health": 0.5},
            "utterances_b": SAMPLE_UTTERANCES,
        }, headers=auth_header(PRO_KEY))
        # Should return 400 from the tool handler's structured error
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# Tests: Patterns endpoint
# ---------------------------------------------------------------------------

class TestPatterns:

    def test_list(self):
        r = client.post("/v1/patterns/list", json={}, headers=auth_header(PRO_KEY))
        assert r.status_code == 200

    def test_invalid_action(self):
        r = client.post("/v1/patterns/explode", json={}, headers=auth_header(PRO_KEY))
        assert r.status_code == 400

    def test_save_and_list(self):
        # First analyze
        r = client.post("/v1/analyze", json={"utterances": SAMPLE_UTTERANCES}, headers=auth_header(PRO_KEY))
        analysis = r.json()

        # Save
        r = client.post("/v1/patterns/save", json={
            "result": analysis,
            "session_name": "api-test",
            "domain": "therapy",
            "tags": ["test", "api"],
        }, headers=auth_header(PRO_KEY))
        assert r.status_code == 200
        assert r.json().get("status") == "saved"


# ---------------------------------------------------------------------------
# Tests: Rate Limiting
# ---------------------------------------------------------------------------

class TestRateLimiting:

    def test_rate_limit_enforced(self):
        """Create a key with tiny limit and exhaust it."""
        # We use the free tier (20/day limit) and manually set bucket near-limit
        from auth import create_key as _create, get_tier_config
        test_key_info = _create(tier="free", owner="rate-test")
        raw_key = test_key_info["raw_key"]
        key_id = test_key_info["key_id"]
        daily_limit = get_tier_config("free")["daily_limit"]

        # Manually set the bucket to one below limit
        limiter._buckets[key_id] = {
            "count": daily_limit - 1,
            "reset_at": __import__("time").time() + 86400,
        }

        # This should succeed (last allowed request)
        r = client.post("/v1/health-check", json={"utterances": SAMPLE_UTTERANCES}, headers=auth_header(raw_key))
        assert r.status_code == 200

        # This should be rate limited (over limit)
        r = client.post("/v1/health-check", json={"utterances": SAMPLE_UTTERANCES}, headers=auth_header(raw_key))
        assert r.status_code == 429
        assert "retry-after" in r.headers


# ---------------------------------------------------------------------------
# Cleanup & CLI runner
# ---------------------------------------------------------------------------

def cleanup():
    """Restore HOME and clean up temp dir."""
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
        TestStatus,
        TestAuth,
        TestTiers,
        TestAnalyze,
        TestHealthCheck,
        TestCompare,
        TestPatterns,
        TestRateLimiting,
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
