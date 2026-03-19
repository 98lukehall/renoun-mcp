"""Tests for news_monitor.py — news-driven structural alert system."""
import threading
import time
from unittest.mock import patch, MagicMock

import pytest

from news_monitor import (
    NewsAlert,
    NewsAlertCache,
    compute_alert,
    check_volume_spike,
    check_news_velocity,
    check_trending,
    ASSET_MAP,
    NEWS_BASELINE,
)


# ── NewsAlertCache ─────────────────────────────────────────────────

class TestNewsAlertCache:
    def test_get_returns_default_for_unknown_symbol(self):
        cache = NewsAlertCache()
        alert = cache.get("UNKNOWN")
        assert alert.level == "none"
        assert alert.activity_score == 0.0

    def test_set_and_get(self):
        cache = NewsAlertCache()
        alert = NewsAlert(level="elevated", activity_score=0.5, detail="test")
        cache.set("BTCUSDT", alert)
        result = cache.get("BTCUSDT")
        assert result.level == "elevated"
        assert result.activity_score == 0.5

    def test_get_all(self):
        cache = NewsAlertCache()
        cache.set("BTCUSDT", NewsAlert(level="none"))
        cache.set("ETHUSDT", NewsAlert(level="elevated"))
        all_alerts = cache.get_all()
        assert len(all_alerts) == 2
        assert "BTCUSDT" in all_alerts
        assert "ETHUSDT" in all_alerts

    def test_thread_safety(self):
        """Concurrent reads and writes should not raise."""
        cache = NewsAlertCache()
        errors = []

        def writer():
            try:
                for i in range(100):
                    cache.set("BTCUSDT", NewsAlert(activity_score=float(i)))
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for _ in range(100):
                    cache.get("BTCUSDT")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer), threading.Thread(target=reader)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0


# ── Alert Level Thresholds ─────────────────────────────────────────

class TestAlertLevels:
    @patch("news_monitor.check_volume_spike", return_value=1.0)
    @patch("news_monitor.check_news_velocity", return_value=0.0)
    def test_normal_activity_returns_none(self, mock_news, mock_vol):
        alert = compute_alert("BTCUSDT")
        assert alert.level == "none"
        assert alert.activity_score == 0.0

    @patch("news_monitor.check_volume_spike", return_value=3.5)
    @patch("news_monitor.check_news_velocity", return_value=1.0)
    @patch("news_monitor.check_trending", return_value=False)
    def test_volume_spike_triggers_elevated(self, mock_trend, mock_news, mock_vol):
        alert = compute_alert("BTCUSDT")
        assert alert.level == "elevated"

    @patch("news_monitor.check_volume_spike", return_value=6.0)
    @patch("news_monitor.check_news_velocity", return_value=5.0)
    @patch("news_monitor.check_trending", return_value=False)
    def test_high_activity_triggers_extreme(self, mock_trend, mock_news, mock_vol):
        alert = compute_alert("BTCUSDT")
        assert alert.level == "extreme"

    @patch("news_monitor.check_volume_spike", return_value=2.5)
    @patch("news_monitor.check_news_velocity", return_value=1.0)
    @patch("news_monitor.check_trending", return_value=True)
    def test_trending_plus_volume_triggers_extreme(self, mock_trend, mock_news, mock_vol):
        alert = compute_alert("BTCUSDT")
        assert alert.level == "extreme"


# ── Scoring ────────────────────────────────────────────────────────

class TestScoring:
    def test_volume_score_5x_equals_1(self):
        """5x volume spike should give vol_score = 1.0."""
        vol_spike = 5.0
        vol_score = min((vol_spike - 1.0) / 4.0, 1.0)
        assert vol_score == 1.0

    def test_volume_score_1x_equals_0(self):
        """1x volume (normal) should give vol_score = 0.0."""
        vol_spike = 1.0
        vol_score = min((vol_spike - 1.0) / 4.0, 1.0)
        assert vol_score == 0.0

    def test_news_score_5x_baseline_equals_1(self):
        """5x baseline news velocity should give news_score = 1.0."""
        news_ratio = 5.0
        news_score = min(news_ratio / 5.0, 1.0)
        assert news_score == 1.0

    def test_news_score_1x_baseline_equals_02(self):
        """1x baseline should give news_score = 0.2."""
        news_ratio = 1.0
        news_score = min(news_ratio / 5.0, 1.0)
        assert news_score == pytest.approx(0.2)


# ── Graceful Degradation ──────────────────────────────────────────

class TestGracefulDegradation:
    @patch("news_monitor.check_volume_spike", return_value=1.0)
    @patch("news_monitor.check_news_velocity", return_value=0.0)
    def test_all_sources_fail_returns_none_level(self, mock_news, mock_vol):
        """When sources return default/zero values, alert should be none."""
        alert = compute_alert("BTCUSDT")
        assert alert.level == "none"

    def test_unknown_symbol_returns_default(self):
        alert = compute_alert("FAKEUSD")
        assert alert.level == "none"
        assert alert.activity_score == 0.0


# ── Data Source Mocking ───────────────────────────────────────────

class TestDataSources:
    @patch("news_monitor.requests.get")
    def test_check_news_velocity_parses_response(self, mock_get):
        now = time.time()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "Data": [
                {"published_on": now - 60},      # 1 min ago
                {"published_on": now - 300},     # 5 min ago
                {"published_on": now - 7200},    # 2 hours ago (outside window)
            ]
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        count = check_news_velocity("BTC")
        assert count == 2.0  # Only 2 articles within 30 min

    @patch("news_monitor.requests.get")
    def test_check_trending_parses_response(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "coins": [
                {"item": {"id": "bitcoin"}},
                {"item": {"id": "solana"}},
            ]
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        assert check_trending("bitcoin") is True
        assert check_trending("ethereum") is False

    @patch("news_monitor.requests.get", side_effect=Exception("timeout"))
    def test_check_trending_returns_false_on_error(self, mock_get):
        assert check_trending("bitcoin") is False

    @patch("news_monitor.requests.get", side_effect=Exception("timeout"))
    def test_check_news_velocity_returns_0_on_error(self, mock_get):
        assert check_news_velocity("BTC") == 0.0
