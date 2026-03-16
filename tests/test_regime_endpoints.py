"""
Tests for regime endpoints, regime_service, and regime_cache.
"""

import time
import pytest

from regime_cache import RegimeCache
from regime_service import (
    determine_action,
    analysis_to_regime_response,
    compute_portfolio_action,
    REGIME_MAP,
)


# ---------------------------------------------------------------------------
# determine_action tests
# ---------------------------------------------------------------------------

class TestDetermineAction:
    def test_unstable_returns_avoid(self):
        action, detail = determine_action("unstable", 0.60, 0.50)
        assert action == "avoid"

    def test_low_dhs_returns_avoid(self):
        action, detail = determine_action("bounded", 0.30, 0.95)
        assert action == "avoid"

    def test_dhs_below_baseline_returns_monitor(self):
        action, detail = determine_action("bounded", 0.45, 0.80)
        assert action == "monitor"

    def test_active_low_exposure_returns_reduce(self):
        action, detail = determine_action("active", 0.70, 0.50)
        assert action == "reduce"

    def test_bounded_high_exposure_returns_proceed(self):
        action, detail = determine_action("bounded", 0.75, 0.90)
        assert action == "proceed"

    def test_active_high_exposure_returns_proceed(self):
        action, detail = determine_action("active", 0.75, 0.80)
        assert action == "proceed"

    def test_bounded_low_exposure_returns_reduce(self):
        action, detail = determine_action("bounded", 0.70, 0.50)
        assert action == "reduce"


# ---------------------------------------------------------------------------
# analysis_to_regime_response tests
# ---------------------------------------------------------------------------

class TestAnalysisToRegimeResponse:
    @pytest.fixture
    def mock_analysis(self):
        return {
            "dialectical_health": 0.83,
            "constellations": [{"detected": "CLOSED_LOOP", "confidence": 0.87}],
            "exposure": {"scalar": 0.95, "interpretation": "healthy"},
            "candles_analyzed": 100,
        }

    def test_produces_flat_format(self, mock_analysis):
        result = analysis_to_regime_response(mock_analysis, "BTCUSDT", "1h")
        assert result["regime"] == "bounded"
        assert result["constellation"] == "CLOSED_LOOP"
        assert result["symbol"] == "BTCUSDT"
        assert result["timeframe"] == "1h"
        assert result["dhs"] == 0.83
        assert result["exposure"] == 0.95
        assert result["action"] == "proceed"
        assert "_meta" in result
        assert "full_analysis" not in result

    def test_include_full_nests_analysis(self, mock_analysis):
        result = analysis_to_regime_response(mock_analysis, "BTCUSDT", "1h", include_full=True)
        assert "full_analysis" in result
        assert result["full_analysis"]["dialectical_health"] == 0.83

    def test_include_full_false_omits(self, mock_analysis):
        result = analysis_to_regime_response(mock_analysis, "BTCUSDT", "1h", include_full=False)
        assert "full_analysis" not in result

    def test_no_constellations_defaults_nominal(self):
        analysis = {"dialectical_health": 0.60, "constellations": [], "exposure": {"scalar": 0.8}}
        result = analysis_to_regime_response(analysis, "ETHUSDT", "4h")
        assert result["constellation"] == "NOMINAL"
        assert result["regime"] == "bounded"

    def test_meta_block_present(self, mock_analysis):
        result = analysis_to_regime_response(mock_analysis, "BTCUSDT", "1h")
        meta = result["_meta"]
        assert meta["provider"] == "renoun"
        assert "provision_url" in meta

    def test_all_regime_map_entries_valid(self):
        for pattern, (regime, envelope, desc) in REGIME_MAP.items():
            assert regime in ("bounded", "active", "unstable")
            assert isinstance(envelope, (int, float))
            assert isinstance(desc, str)


# ---------------------------------------------------------------------------
# compute_portfolio_action tests
# ---------------------------------------------------------------------------

class TestComputePortfolioAction:
    def test_two_unstable_returns_avoid(self):
        regimes = {
            "BTCUSDT": {"regime": "unstable", "action": "avoid", "exposure": 0.1},
            "ETHUSDT": {"regime": "unstable", "action": "avoid", "exposure": 0.15},
            "SOLUSDT": {"regime": "bounded", "action": "proceed", "exposure": 0.9},
        }
        action, exposure, count = compute_portfolio_action(regimes)
        assert action == "avoid"
        assert count == 2
        assert exposure == 0.1  # min of all

    def test_one_unstable_returns_reduce(self):
        regimes = {
            "BTCUSDT": {"regime": "unstable", "action": "avoid", "exposure": 0.1},
            "ETHUSDT": {"regime": "bounded", "action": "proceed", "exposure": 0.9},
            "SOLUSDT": {"regime": "bounded", "action": "proceed", "exposure": 0.8},
        }
        action, exposure, count = compute_portfolio_action(regimes)
        assert action == "reduce"
        assert count == 1

    def test_all_bounded_returns_proceed(self):
        regimes = {
            "BTCUSDT": {"regime": "bounded", "action": "proceed", "exposure": 0.95},
            "ETHUSDT": {"regime": "bounded", "action": "proceed", "exposure": 0.90},
        }
        action, exposure, count = compute_portfolio_action(regimes)
        assert action == "proceed"
        assert count == 0

    def test_monitor_assets_returns_reduce(self):
        regimes = {
            "BTCUSDT": {"regime": "bounded", "action": "monitor", "exposure": 0.5},
            "ETHUSDT": {"regime": "bounded", "action": "proceed", "exposure": 0.9},
        }
        action, exposure, count = compute_portfolio_action(regimes)
        assert action == "reduce"

    def test_empty_regimes(self):
        action, exposure, count = compute_portfolio_action({})
        assert action == "monitor"


# ---------------------------------------------------------------------------
# RegimeCache tests
# ---------------------------------------------------------------------------

class TestRegimeCache:
    def test_set_and_get(self):
        cache = RegimeCache(ttl_seconds=60)
        data = {"regime": "bounded", "dhs": 0.8}
        cache.set("BTCUSDT", "1h", data)
        assert cache.get("BTCUSDT", "1h") == data

    def test_get_miss(self):
        cache = RegimeCache(ttl_seconds=60)
        assert cache.get("BTCUSDT", "1h") is None

    def test_expired_entry(self):
        cache = RegimeCache(ttl_seconds=0)  # instant expiry
        cache.set("BTCUSDT", "1h", {"regime": "bounded"})
        time.sleep(0.01)
        assert cache.get("BTCUSDT", "1h") is None

    def test_clear(self):
        cache = RegimeCache(ttl_seconds=60)
        cache.set("BTCUSDT", "1h", {"regime": "bounded"})
        cache.clear()
        assert cache.get("BTCUSDT", "1h") is None


# ---------------------------------------------------------------------------
# API endpoint tests (using FastAPI TestClient)
# ---------------------------------------------------------------------------

class TestRegimeAPI:
    @pytest.fixture
    def client(self, isolated_home):
        """Create a test client with a valid API key."""
        from auth import create_key
        key_data = create_key(tier="pro", owner="test@test.com")
        self._api_key = key_data["raw_key"]

        from fastapi.testclient import TestClient
        from api import app
        return TestClient(app)

    def _auth_headers(self):
        return {"Authorization": f"Bearer {self._api_key}"}

    def test_regime_post_with_klines(self, client, sample_klines):
        resp = client.post("/v1/regime", json={
            "symbol": "TESTUSDT",
            "timeframe": "1h",
            "klines": sample_klines,
            "include_full": False,
        }, headers=self._auth_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert data["regime"] in ("bounded", "active", "unstable")
        assert data["action"] in ("proceed", "reduce", "avoid", "monitor")
        assert data["symbol"] == "TESTUSDT"
        assert "_meta" in data
        assert "X-ReNoUn-Regime" in resp.headers
        assert "X-ReNoUn-Action" in resp.headers

    def test_regime_post_include_full(self, client, sample_klines):
        resp = client.post("/v1/regime", json={
            "symbol": "TESTUSDT",
            "timeframe": "1h",
            "klines": sample_klines,
            "include_full": True,
        }, headers=self._auth_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert "full_analysis" in data

    def test_regime_post_include_full_false(self, client, sample_klines):
        resp = client.post("/v1/regime", json={
            "symbol": "TESTUSDT",
            "timeframe": "1h",
            "klines": sample_klines,
            "include_full": False,
        }, headers=self._auth_headers())
        assert resp.status_code == 200
        assert "full_analysis" not in resp.json()

    def test_regime_headers_present(self, client, sample_klines):
        resp = client.post("/v1/regime", json={
            "symbol": "TESTUSDT",
            "timeframe": "1h",
            "klines": sample_klines,
        }, headers=self._auth_headers())
        assert "X-ReNoUn-Regime" in resp.headers
        assert "X-ReNoUn-Action" in resp.headers
