"""
Tests for agent tier, metered billing, key provisioning, and usage tracking.
"""

import tempfile
from pathlib import Path

import pytest
import auth
from auth import TIERS, create_agent_key, validate_key, find_agent_key_by_email, count_agent_keys_by_email, AGENT_KEY_PREFIX
from usage import MeteredUsageTracker


@pytest.fixture
def isolated_keys(tmp_path, monkeypatch):
    """Redirect auth.KEYS_FILE to a temp location for test isolation."""
    keys_file = tmp_path / "api_keys.json"
    monkeypatch.setattr(auth, "KEYS_FILE", keys_file)
    return keys_file


# ---------------------------------------------------------------------------
# Agent Tier Config
# ---------------------------------------------------------------------------

class TestAgentTierConfig:
    def test_agent_tier_exists(self):
        assert "agent" in TIERS

    def test_agent_tier_has_correct_fields(self):
        tier = TIERS["agent"]
        assert tier["free_daily"] == 50
        assert tier["daily_limit"] == 10000
        assert tier["rate_limit"] == 1000
        assert tier["price_per_call"] == 0.02
        assert tier["metered"] is True

    def test_agent_tier_tools(self):
        tier = TIERS["agent"]
        assert "renoun_finance_analyze" in tier["tools"]
        assert "regime" in tier["tools"]
        assert "regime_live" in tier["tools"]
        assert "regime_batch" in tier["tools"]


# ---------------------------------------------------------------------------
# Agent Key Creation & Validation
# ---------------------------------------------------------------------------

class TestAgentKeyManagement:
    def test_create_agent_key(self, isolated_keys):
        result = create_agent_key("test@test.com", "my-bot")
        assert result["raw_key"].startswith(AGENT_KEY_PREFIX)
        assert result["tier"] == "agent"
        assert result["agent_name"] == "my-bot"

    def test_validate_agent_key(self, isolated_keys):
        result = create_agent_key("test@test.com", "my-bot")
        validated = validate_key(result["raw_key"])
        assert validated is not None
        assert validated["tier"] == "agent"

    def test_find_by_email(self, isolated_keys):
        create_agent_key("find@test.com", "bot-1")
        found = find_agent_key_by_email("find@test.com")
        assert found is not None
        assert found["tier"] == "agent"

    def test_find_by_email_not_found(self, isolated_keys):
        found = find_agent_key_by_email("nobody@test.com")
        assert found is None

    def test_count_keys_by_email(self, isolated_keys):
        create_agent_key("counttest@test.com", "bot-1")
        create_agent_key("counttest@test.com", "bot-2")
        assert count_agent_keys_by_email("counttest@test.com") == 2


# ---------------------------------------------------------------------------
# Metered Usage Tracking
# ---------------------------------------------------------------------------

class TestMeteredUsage:
    def test_free_tier_first_50_not_billable(self):
        tracker = MeteredUsageTracker()
        tier_config = TIERS["agent"]

        for i in range(50):
            result = tracker.record_call("test_key", "/v1/regime/live", tier_config)
            assert result["is_billable"] is False

    def test_51st_call_is_billable(self):
        tracker = MeteredUsageTracker()
        tier_config = TIERS["agent"]

        for i in range(50):
            tracker.record_call("test_key", "/v1/regime/live", tier_config)

        result = tracker.record_call("test_key", "/v1/regime/live", tier_config)
        assert result["is_billable"] is True
        assert result["daily_total"] == 51

    def test_daily_limit_check(self):
        tracker = MeteredUsageTracker()
        tier_config = {"free_daily": 2, "daily_limit": 5, "price_per_call": 0.02}

        for i in range(5):
            tracker.record_call("test_key", "/v1/regime/live", tier_config)

        error = tracker.check_daily_limit("test_key", tier_config)
        assert error is not None
        assert error["error"]["type"] == "daily_limit"

    def test_under_daily_limit_no_error(self):
        tracker = MeteredUsageTracker()
        tier_config = TIERS["agent"]

        tracker.record_call("test_key", "/v1/regime/live", tier_config)
        error = tracker.check_daily_limit("test_key", tier_config)
        assert error is None

    def test_usage_stats(self):
        tracker = MeteredUsageTracker()
        tier_config = TIERS["agent"]

        for i in range(60):
            tracker.record_call("test_key", "/v1/regime/live", tier_config)

        usage = tracker.get_usage("test_key", tier_config)
        assert usage["today"]["total_calls"] == 60
        assert usage["today"]["free_calls"] == 50
        assert usage["today"]["billable_calls"] == 10
        assert usage["today"]["estimated_cost"] == "$0.20"

    def test_by_endpoint_tracking(self):
        tracker = MeteredUsageTracker()
        tier_config = TIERS["agent"]

        for _ in range(3):
            tracker.record_call("test_key", "/v1/regime/live", tier_config)
        for _ in range(2):
            tracker.record_call("test_key", "/v1/regime", tier_config)

        usage = tracker.get_usage("test_key", tier_config)
        assert usage["by_endpoint"]["/v1/regime/live"] == 3
        assert usage["by_endpoint"]["/v1/regime"] == 2


# ---------------------------------------------------------------------------
# API Endpoint Tests
# ---------------------------------------------------------------------------

class TestProvisioningEndpoint:
    @pytest.fixture(autouse=True)
    def _setup(self, isolated_keys):
        """Each test gets its own isolated keys file."""
        from api import _provision_rate
        _provision_rate.clear()

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from api import app
        return TestClient(app)

    def test_provision_new_key(self, client):
        resp = client.post("/v1/keys/provision", json={
            "email": "brand-new-agent@test.com",
            "agent_name": "test-bot-unique",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["api_key"].startswith("rn_agent_")
        assert data["tier"] == "agent"
        assert data["free_daily"] == 50

    def test_provision_idempotent(self, client):
        resp1 = client.post("/v1/keys/provision", json={
            "email": "idem-unique@test.com",
            "agent_name": "same-bot",
        })
        resp2 = client.post("/v1/keys/provision", json={
            "email": "idem-unique@test.com",
            "agent_name": "same-bot",
        })
        assert resp1.status_code == 200
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert "key_id" in data2

    def test_provision_invalid_email(self, client):
        resp = client.post("/v1/keys/provision", json={
            "email": "notanemail",
            "agent_name": "bot",
        })
        assert resp.status_code == 400

    def test_provision_max_keys_per_email(self, client):
        for i in range(5):
            resp = client.post("/v1/keys/provision", json={
                "email": "maxkeys-unique@test.com",
                "agent_name": f"bot-unique-{i}",
            })
            assert resp.status_code == 200

        resp = client.post("/v1/keys/provision", json={
            "email": "maxkeys-unique@test.com",
            "agent_name": "bot-6-too-many",
        })
        assert resp.status_code == 429


class TestUsageEndpoint:
    @pytest.fixture
    def agent_client(self, isolated_keys):
        key_data = create_agent_key("usage@test.com", "usage-bot")
        self._api_key = key_data["raw_key"]
        from fastapi.testclient import TestClient
        from api import app
        return TestClient(app)

    def test_usage_returns_stats(self, agent_client):
        resp = agent_client.get("/v1/usage", headers={
            "Authorization": f"Bearer {self._api_key}",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["tier"] == "agent"
        assert "today" in data
        assert "total_calls" in data["today"]
