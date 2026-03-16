"""Tests for the agent leaderboard endpoint."""

import pytest
import auth
from auth import create_agent_key


@pytest.fixture
def client(tmp_path, monkeypatch):
    keys_file = tmp_path / "api_keys.json"
    monkeypatch.setattr(auth, "KEYS_FILE", keys_file)

    from fastapi.testclient import TestClient
    from api import app
    return TestClient(app)


class TestLeaderboard:
    def test_returns_valid_json(self, client):
        resp = client.get("/v1/agents/leaderboard")
        assert resp.status_code == 200
        data = resp.json()
        assert "leaderboard" in data
        assert "stats" in data
        assert "updated_at" in data

    def test_agents_appear_in_list(self, client):
        create_agent_key("lb1@test.com", "alpha-bot")
        create_agent_key("lb2@test.com", "beta-bot")

        resp = client.get("/v1/agents/leaderboard")
        data = resp.json()
        names = [a["agent_name"] for a in data["leaderboard"]]
        assert "alpha-bot" in names
        assert "beta-bot" in names
        assert data["stats"]["total_agents"] == 2

    def test_non_public_excluded_from_list(self, client):
        # Create a public agent
        create_agent_key("pub@test.com", "public-bot")
        # Create a non-public agent (set public=false in the key entry)
        key_data = create_agent_key("priv@test.com", "private-bot")
        # Manually set public=false
        data = auth._load_keys()
        for e in data["keys"]:
            if e["key_id"] == key_data["key_id"]:
                e["public"] = False
        auth._save_keys(data)

        resp = client.get("/v1/agents/leaderboard")
        result = resp.json()
        names = [a["agent_name"] for a in result["leaderboard"]]
        assert "public-bot" in names
        assert "private-bot" not in names
        # But both counted in stats
        assert result["stats"]["total_agents"] == 2

    def test_agent_headers_on_response(self, client):
        resp = client.get("/v1/agents/leaderboard")
        assert resp.headers.get("X-Agent-Compatible") == "true"
        assert resp.headers.get("X-Agent-Free-Tier") == "50/day"
