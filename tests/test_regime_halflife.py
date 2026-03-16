"""Tests for regime half-life and temporal stability estimation."""

import pytest
from regime_halflife import (
    compute_dhs_momentum,
    assess_unity_trend,
    assess_novelty_pressure,
    compute_persistence_factor,
    assess_sequence_risk,
    estimate_regime_stability,
    RegimeStability,
)


class TestDHSMomentum:
    def test_rising_dhs(self):
        values = [0.4, 0.5, 0.6, 0.7, 0.8]
        momentum = compute_dhs_momentum(values)
        assert momentum > 0

    def test_falling_dhs(self):
        values = [0.8, 0.7, 0.6, 0.5, 0.4]
        momentum = compute_dhs_momentum(values)
        assert momentum < 0

    def test_flat_dhs(self):
        values = [0.6, 0.6, 0.6, 0.6]
        momentum = compute_dhs_momentum(values)
        assert momentum == 0.0

    def test_single_value_returns_zero(self):
        assert compute_dhs_momentum([0.5]) == 0.0

    def test_empty_returns_zero(self):
        assert compute_dhs_momentum([]) == 0.0


class TestUnityTrend:
    def test_high_unity_stable(self):
        analysis = {"channels": {"unity": {"aggregate": 0.8, "Un1": 0.8, "Un2": 0.75, "Un3": 0.82, "Un4": 0.78, "Un5": 0.8, "Un6": 0.79}}}
        label, mag = assess_unity_trend(analysis)
        assert label == "stable"
        assert mag >= 0.7

    def test_low_unity_collapsing(self):
        analysis = {"channels": {"unity": {"aggregate": 0.3}}}
        label, mag = assess_unity_trend(analysis)
        assert label == "collapsing"

    def test_mid_unity_declining(self):
        analysis = {"channels": {"unity": {"aggregate": 0.45}}}
        label, mag = assess_unity_trend(analysis)
        assert label == "declining"

    def test_missing_channels_defaults(self):
        analysis = {}
        label, mag = assess_unity_trend(analysis)
        # Default aggregate is 0.5 → declining
        assert label == "declining"


class TestNoveltyPressure:
    def test_high_novelty(self):
        analysis = {"channels": {"novelty": {"aggregate": 0.9, "No3": 0.85, "No5": 0.9}}}
        pressure = assess_novelty_pressure(analysis)
        assert pressure > 0.7

    def test_low_novelty(self):
        analysis = {"channels": {"novelty": {"aggregate": 0.2, "No3": 0.15, "No5": 0.1}}}
        pressure = assess_novelty_pressure(analysis)
        assert pressure < 0.3

    def test_missing_channels(self):
        analysis = {}
        pressure = assess_novelty_pressure(analysis)
        assert 0.0 <= pressure <= 1.0


class TestPersistenceFactor:
    def test_increases_with_count(self):
        f1 = compute_persistence_factor(1, "CLOSED_LOOP")
        f5 = compute_persistence_factor(5, "CLOSED_LOOP")
        assert f5 > f1

    def test_bounded_cap_at_2_5(self):
        factor = compute_persistence_factor(20, "CLOSED_LOOP")
        assert factor == 2.5

    def test_unstable_cap_at_1_5(self):
        factor = compute_persistence_factor(20, "SCATTERING")
        assert factor == 1.5

    def test_active_cap_at_1_5(self):
        factor = compute_persistence_factor(20, "CONVERGENCE")
        assert factor == 1.5

    def test_zero_persistence(self):
        factor = compute_persistence_factor(0, "CLOSED_LOOP")
        assert factor == 1.0


class TestSequenceRisk:
    def test_destabilizing_sequence(self):
        risk, modifier = assess_sequence_risk(["CONVERGENCE", "SCATTERING"])
        assert risk > 0.5
        assert modifier < 1.0

    def test_stabilizing_sequence(self):
        risk, modifier = assess_sequence_risk(["PATTERN_BREAK", "CONVERGENCE"])
        assert risk == 0.0
        assert modifier > 1.0

    def test_unknown_sequence(self):
        risk, modifier = assess_sequence_risk(["CLOSED_LOOP", "NOMINAL"])
        assert risk == 0.0
        assert modifier == 1.0

    def test_short_sequence(self):
        risk, modifier = assess_sequence_risk(["CLOSED_LOOP"])
        assert risk == 0.0
        assert modifier == 1.0

    def test_empty_sequence(self):
        risk, modifier = assess_sequence_risk([])
        assert risk == 0.0
        assert modifier == 1.0

    def test_uses_last_pair(self):
        # First pair is stabilizing, but last pair is destabilizing
        risk, modifier = assess_sequence_risk(["PATTERN_BREAK", "CONVERGENCE", "SCATTERING"])
        assert risk > 0.5
        assert modifier < 1.0


class TestEstimateRegimeStability:
    def _base_analysis(self, unity_agg=0.6, novelty_agg=0.4):
        return {
            "channels": {
                "unity": {"aggregate": unity_agg},
                "novelty": {"aggregate": novelty_agg, "No3": novelty_agg, "No5": novelty_agg},
            },
        }

    def test_bounded_high_dhs_long_halflife(self):
        result = estimate_regime_stability(
            regime="bounded", constellation="HIGH_SYMMETRY",
            dhs=0.85, exposure=0.95,
            analysis_result=self._base_analysis(unity_agg=0.8, novelty_agg=0.2),
        )
        assert isinstance(result, RegimeStability)
        assert result.halflife_minutes > 200
        assert result.instability_risk == "low"
        assert result.urgency == "none"

    def test_unstable_low_dhs_short_halflife(self):
        result = estimate_regime_stability(
            regime="unstable", constellation="SCATTERING",
            dhs=0.25, exposure=0.3,
            analysis_result=self._base_analysis(unity_agg=0.3, novelty_agg=0.8),
        )
        assert result.halflife_minutes < 60
        assert result.instability_risk == "high"
        assert result.urgency == "exit_now"

    def test_active_with_destabilizing_sequence(self):
        result = estimate_regime_stability(
            regime="active", constellation="CONVERGENCE",
            dhs=0.6, exposure=0.7,
            analysis_result=self._base_analysis(),
            dominant_sequence=["CONVERGENCE", "SCATTERING"],
        )
        assert result.instability_risk in ("elevated", "high")
        assert result.sequence_risk > 0.5

    def test_halflife_never_below_5(self):
        result = estimate_regime_stability(
            regime="unstable", constellation="REPEATED_DISRUPTION",
            dhs=0.1, exposure=0.1,
            analysis_result=self._base_analysis(unity_agg=0.1, novelty_agg=0.95),
            recent_dhs_values=[0.5, 0.4, 0.3, 0.2, 0.1],
        )
        assert result.halflife_minutes >= 5.0

    def test_halflife_never_above_720(self):
        result = estimate_regime_stability(
            regime="bounded", constellation="HIGH_SYMMETRY",
            dhs=0.95, exposure=1.0,
            analysis_result=self._base_analysis(unity_agg=0.95, novelty_agg=0.05),
            persistence_count=20,
            recent_dhs_values=[0.8, 0.85, 0.9, 0.95],
        )
        assert result.halflife_minutes <= 720.0

    def test_15m_timeframe_shorter_halflife(self):
        kwargs = dict(
            regime="bounded", constellation="CLOSED_LOOP",
            dhs=0.7, exposure=0.9,
            analysis_result=self._base_analysis(),
        )
        result_1h = estimate_regime_stability(**kwargs, timeframe="1h")
        result_15m = estimate_regime_stability(**kwargs, timeframe="15m")
        assert result_15m.halflife_minutes < result_1h.halflife_minutes

    def test_urgency_none_for_stable(self):
        result = estimate_regime_stability(
            regime="bounded", constellation="HIGH_SYMMETRY",
            dhs=0.85, exposure=0.95,
            analysis_result=self._base_analysis(unity_agg=0.8, novelty_agg=0.2),
        )
        assert result.urgency == "none"
        assert result.exit_window_minutes is None

    def test_exit_window_present_for_prepare_exit(self):
        result = estimate_regime_stability(
            regime="unstable", constellation="SCATTERING",
            dhs=0.4, exposure=0.5,
            analysis_result=self._base_analysis(unity_agg=0.35, novelty_agg=0.7),
        )
        if result.urgency in ("prepare_exit", "exit_now"):
            assert result.exit_window_minutes is not None
            assert result.exit_window_minutes > 0

    def test_exit_window_absent_for_none_urgency(self):
        result = estimate_regime_stability(
            regime="bounded", constellation="HIGH_SYMMETRY",
            dhs=0.85, exposure=0.95,
            analysis_result=self._base_analysis(unity_agg=0.8, novelty_agg=0.2),
        )
        assert result.exit_window_minutes is None

    def test_missing_temporal_data_no_crash(self):
        """Stability estimation works even with empty analysis_result."""
        result = estimate_regime_stability(
            regime="bounded", constellation="NOMINAL",
            dhs=0.6, exposure=0.8,
            analysis_result={},
        )
        assert isinstance(result, RegimeStability)
        assert 0.0 <= result.stability_score <= 1.0

    def test_time_horizon_string(self):
        result = estimate_regime_stability(
            regime="bounded", constellation="CLOSED_LOOP",
            dhs=0.7, exposure=0.9,
            analysis_result=self._base_analysis(),
        )
        assert result.time_horizon in (
            "under 15 minutes", "15-30 minutes", "30-60 minutes",
            "1-2 hours", "2-4 hours", "4-8 hours", "8+ hours",
        )


class TestRegimeServiceIntegration:
    def test_response_includes_stability_block(self):
        from regime_service import analysis_to_regime_response

        analysis = {
            "dialectical_health": 0.7,
            "constellations": [{"detected": "CLOSED_LOOP", "confidence": 0.8}],
            "exposure": {"scalar": 0.9},
            "channels": {
                "unity": {"aggregate": 0.65},
                "novelty": {"aggregate": 0.4, "No3": 0.35, "No5": 0.4},
            },
        }
        result = analysis_to_regime_response(analysis, "BTCUSDT", "1h")
        assert "stability" in result
        stability = result["stability"]
        assert "halflife_minutes" in stability
        assert "stability_score" in stability
        assert "instability_risk" in stability
        assert "time_horizon" in stability
        assert "urgency" in stability

    def test_stability_with_missing_temporal(self):
        """No crash when analysis_result has no temporal or channel data."""
        from regime_service import analysis_to_regime_response

        analysis = {
            "dialectical_health": 0.5,
            "constellations": [],
            "exposure": {"scalar": 1.0},
        }
        result = analysis_to_regime_response(analysis, "ETHUSDT", "1h")
        assert "stability" in result
        assert result["stability"]["stability_score"] >= 0.0


class TestDHSHistoryCache:
    def test_record_and_retrieve(self):
        from regime_cache import RegimeCache

        cache = RegimeCache()
        cache.record_dhs("BTCUSDT", 0.7)
        cache.record_dhs("BTCUSDT", 0.75)
        history = cache.get_dhs_history("BTCUSDT")
        assert history == [0.7, 0.75]

    def test_max_history_cap(self):
        from regime_cache import RegimeCache

        cache = RegimeCache(max_dhs_history=3)
        for v in [0.1, 0.2, 0.3, 0.4, 0.5]:
            cache.record_dhs("BTC", v)
        history = cache.get_dhs_history("BTC")
        assert len(history) == 3
        assert history == [0.3, 0.4, 0.5]

    def test_clear_also_clears_history(self):
        from regime_cache import RegimeCache

        cache = RegimeCache()
        cache.record_dhs("BTC", 0.6)
        cache.clear()
        assert cache.get_dhs_history("BTC") == []

    def test_unknown_symbol_returns_empty(self):
        from regime_cache import RegimeCache

        cache = RegimeCache()
        assert cache.get_dhs_history("UNKNOWN") == []
