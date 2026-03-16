"""Tests for webhook registration, management, and dispatch."""

import json
import pytest
import webhooks as wh_module
from webhooks import (
    register_webhook, list_webhooks, delete_webhook, get_webhook,
    sign_payload, get_matching_webhooks, VALID_EVENTS,
    _increment_failures,
)


@pytest.fixture(autouse=True)
def isolated_webhooks(tmp_path, monkeypatch):
    """Redirect webhooks file to temp location."""
    wh_file = tmp_path / "webhooks.json"
    monkeypatch.setattr(wh_module, "WEBHOOKS_FILE", wh_file)
    return wh_file


class TestWebhookRegistration:
    def test_register_creates_record(self):
        result = register_webhook(
            api_key_id="key_1", url="https://example.com/hook",
            symbols=["BTCUSDT"], events=["regime_change"], secret="s3cret",
        )
        assert "webhook_id" in result
        assert result["url"] == "https://example.com/hook"
        assert result["active"] is True

    def test_max_5_webhooks_per_key(self):
        for i in range(5):
            result = register_webhook(
                api_key_id="key_limit", url=f"https://example.com/hook{i}",
                symbols=["BTCUSDT"], events=["regime_change"], secret="s3cret",
            )
            assert "error" not in result

        result = register_webhook(
            api_key_id="key_limit", url="https://example.com/hook6",
            symbols=["BTCUSDT"], events=["regime_change"], secret="s3cret",
        )
        assert "error" in result

    def test_invalid_event_rejected(self):
        result = register_webhook(
            api_key_id="key_1", url="https://example.com/hook",
            symbols=["BTCUSDT"], events=["invalid_event"], secret="s3cret",
        )
        assert "error" in result

    def test_max_10_symbols(self):
        result = register_webhook(
            api_key_id="key_1", url="https://example.com/hook",
            symbols=[f"SYM{i}USDT" for i in range(11)],
            events=["regime_change"], secret="s3cret",
        )
        assert "error" in result


class TestWebhookSignature:
    def test_hmac_signature(self):
        payload = b'{"event": "regime_change"}'
        sig = sign_payload(payload, "my_secret")
        assert len(sig) == 64  # hex-encoded SHA256
        # Verify deterministic
        assert sign_payload(payload, "my_secret") == sig
        # Different secret = different sig
        assert sign_payload(payload, "other_secret") != sig


class TestWebhookManagement:
    def test_list_webhooks(self):
        register_webhook("key_a", "https://a.com", ["BTCUSDT"], ["regime_change"], "s")
        register_webhook("key_b", "https://b.com", ["ETHUSDT"], ["dhs_crash"], "s")

        a_hooks = list_webhooks("key_a")
        b_hooks = list_webhooks("key_b")
        assert len(a_hooks) == 1
        assert len(b_hooks) == 1
        assert a_hooks[0]["url"] == "https://a.com"

    def test_delete_webhook(self):
        result = register_webhook("key_del", "https://del.com", ["BTCUSDT"], ["regime_change"], "s")
        wh_id = result["webhook_id"]

        assert delete_webhook("key_del", wh_id) is True
        hooks = list_webhooks("key_del")
        assert hooks[0]["active"] is False

    def test_delete_wrong_key_fails(self):
        result = register_webhook("key_own", "https://own.com", ["BTCUSDT"], ["regime_change"], "s")
        wh_id = result["webhook_id"]
        assert delete_webhook("key_other", wh_id) is False

    def test_auto_deactivation_after_10_failures(self):
        result = register_webhook("key_fail", "https://fail.com", ["BTCUSDT"], ["regime_change"], "s")
        wh_id = result["webhook_id"]

        for _ in range(10):
            _increment_failures(wh_id)

        wh = get_webhook(wh_id)
        assert wh["active"] is False

    def test_matching_webhooks(self):
        register_webhook("k1", "https://a.com", ["BTCUSDT", "ETHUSDT"], ["regime_change"], "s")
        register_webhook("k2", "https://b.com", ["BTCUSDT"], ["dhs_crash"], "s")
        register_webhook("k3", "https://c.com", ["SOLUSDT"], ["regime_change"], "s")

        matches = get_matching_webhooks("BTCUSDT", "regime_change")
        assert len(matches) == 1
        assert matches[0]["url"] == "https://a.com"

        matches2 = get_matching_webhooks("BTCUSDT", "dhs_crash")
        assert len(matches2) == 1
        assert matches2[0]["url"] == "https://b.com"


class TestWebhookAPI:
    @pytest.fixture
    def client(self, tmp_path, monkeypatch):
        import auth
        keys_file = tmp_path / "api_keys.json"
        monkeypatch.setattr(auth, "KEYS_FILE", keys_file)

        from auth import create_agent_key
        key_data = create_agent_key("wh@test.com", "wh-bot")
        self._api_key = key_data["raw_key"]

        from fastapi.testclient import TestClient
        from api import app
        return TestClient(app)

    def _auth(self):
        return {"Authorization": f"Bearer {self._api_key}"}

    def test_register_via_api(self, client):
        resp = client.post("/v1/webhooks/register", json={
            "url": "https://test.com/hook",
            "symbols": ["BTCUSDT"],
            "events": ["regime_change"],
            "secret": "test_secret",
        }, headers=self._auth())
        assert resp.status_code == 200
        assert "webhook_id" in resp.json()

    def test_list_via_api(self, client):
        client.post("/v1/webhooks/register", json={
            "url": "https://test.com/hook",
            "symbols": ["BTCUSDT"],
            "events": ["regime_change"],
            "secret": "test_secret",
        }, headers=self._auth())

        resp = client.get("/v1/webhooks", headers=self._auth())
        assert resp.status_code == 200
        assert len(resp.json()["webhooks"]) == 1

    def test_test_ping(self, client):
        reg = client.post("/v1/webhooks/register", json={
            "url": "https://test.com/hook",
            "symbols": ["BTCUSDT"],
            "events": ["regime_change"],
            "secret": "test_secret",
        }, headers=self._auth())
        wh_id = reg.json()["webhook_id"]

        resp = client.post(f"/v1/webhooks/{wh_id}/test", headers=self._auth())
        assert resp.status_code == 200
        assert resp.json()["sent"] is True
