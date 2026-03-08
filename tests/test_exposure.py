#!/usr/bin/env python3
"""
Tests for renoun_exposure module.

Covers:
  - ConstellationTracker: state management, persistence, churn, history
  - smooth_exposure: asymmetric EMA blending
  - dhs_to_exposure: tiered base, constellation mods, stress, floor/ceiling
  - run_engine_on_window: integration with mock analyze_fn

Run:
    python3 tests/test_exposure.py
    # or
    pytest tests/test_exposure.py -v
"""

import sys
import os

# Ensure we can import from the parent directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from renoun_exposure import ConstellationTracker, smooth_exposure, dhs_to_exposure, run_engine_on_window


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def assert_approx(actual, expected, tol=1e-6, context=""):
    """Assert two floats are approximately equal."""
    assert abs(actual - expected) < tol, (
        f"{context}: expected {expected}, got {actual} (diff={abs(actual - expected)})"
    )


def assert_in_range(value, lo, hi, context=""):
    """Assert value is within [lo, hi]."""
    assert lo <= value <= hi, (
        f"{context}: expected {value} in [{lo}, {hi}]"
    )


def make_mock_analyze_fn(dhs=0.7, constellation="CONVERGENCE", loop=0.3,
                         dd_stress=0.0, vol_stress=0.0):
    """Create a mock analyze function that returns a fixed result."""
    def analyze_fn(klines, symbol="TEST", timeframe="1h"):
        return {
            "dialectical_health": dhs,
            "constellations": [{"detected": constellation, "confidence": 0.8}],
            "loop_strength": loop,
            "stress": {
                "drawdown": dd_stress,
                "vol_expansion": vol_stress,
            },
        }
    return analyze_fn


def make_failing_analyze_fn():
    """Create a mock analyze function that always raises."""
    def analyze_fn(klines, symbol="TEST", timeframe="1h"):
        raise RuntimeError("Analysis failed")
    return analyze_fn


# ---------------------------------------------------------------------------
# ConstellationTracker Tests
# ---------------------------------------------------------------------------

class TestConstellationTrackerInit:
    """Test ConstellationTracker initial state."""

    def test_initial_current_is_none(self):
        tracker = ConstellationTracker()
        assert tracker.current is None

    def test_initial_run_length_is_zero(self):
        tracker = ConstellationTracker()
        assert tracker.run_length == 0

    def test_initial_history_is_empty(self):
        tracker = ConstellationTracker()
        assert tracker.history == []


class TestConstellationTrackerUpdate:
    """Test ConstellationTracker.update() behavior."""

    def test_single_update_sets_current(self):
        tracker = ConstellationTracker()
        tracker.update("CONVERGENCE")
        assert tracker.current == "CONVERGENCE"

    def test_single_update_sets_run_length_to_one(self):
        tracker = ConstellationTracker()
        tracker.update("CONVERGENCE")
        assert tracker.run_length == 1

    def test_single_update_appends_to_history(self):
        tracker = ConstellationTracker()
        tracker.update("CONVERGENCE")
        assert tracker.history == ["CONVERGENCE"]

    def test_same_constellation_increments_run_length(self):
        tracker = ConstellationTracker()
        tracker.update("CONVERGENCE")
        tracker.update("CONVERGENCE")
        assert tracker.run_length == 2

    def test_same_constellation_three_times(self):
        tracker = ConstellationTracker()
        tracker.update("CONVERGENCE")
        tracker.update("CONVERGENCE")
        tracker.update("CONVERGENCE")
        assert tracker.run_length == 3
        assert tracker.current == "CONVERGENCE"

    def test_different_constellation_resets_run_length(self):
        tracker = ConstellationTracker()
        tracker.update("CONVERGENCE")
        tracker.update("CONVERGENCE")
        assert tracker.run_length == 2
        tracker.update("SCATTERING")
        assert tracker.run_length == 1
        assert tracker.current == "SCATTERING"

    def test_alternating_constellations_run_length_stays_one(self):
        tracker = ConstellationTracker()
        for name in ["CONVERGENCE", "SCATTERING", "CONVERGENCE", "SCATTERING"]:
            tracker.update(name)
        assert tracker.run_length == 1

    def test_history_records_all_updates(self):
        tracker = ConstellationTracker()
        sequence = ["CONVERGENCE", "CONVERGENCE", "SCATTERING", "CLOSED_LOOP"]
        for name in sequence:
            tracker.update(name)
        assert tracker.history == sequence

    def test_history_length_grows(self):
        tracker = ConstellationTracker()
        for i in range(10):
            tracker.update("CONVERGENCE")
        assert len(tracker.history) == 10


class TestConstellationTrackerPersistence:
    """Test persistence_mult calculation."""

    def test_one_window_persistence_half(self):
        tracker = ConstellationTracker()
        result = tracker.update("CONVERGENCE")
        assert_approx(result["persistence_mult"], 0.5, context="1 window persistence")

    def test_two_windows_persistence_point_eight(self):
        tracker = ConstellationTracker()
        tracker.update("CONVERGENCE")
        result = tracker.update("CONVERGENCE")
        assert_approx(result["persistence_mult"], 0.8, context="2 window persistence")

    def test_three_windows_persistence_one(self):
        tracker = ConstellationTracker()
        tracker.update("CONVERGENCE")
        tracker.update("CONVERGENCE")
        result = tracker.update("CONVERGENCE")
        assert_approx(result["persistence_mult"], 1.0, context="3 window persistence")

    def test_four_windows_persistence_still_one(self):
        tracker = ConstellationTracker()
        for _ in range(4):
            result = tracker.update("CONVERGENCE")
        assert_approx(result["persistence_mult"], 1.0, context="4 window persistence")

    def test_persistence_resets_on_change(self):
        tracker = ConstellationTracker()
        tracker.update("CONVERGENCE")
        tracker.update("CONVERGENCE")
        tracker.update("CONVERGENCE")
        # Now change constellation
        result = tracker.update("SCATTERING")
        assert_approx(result["persistence_mult"], 0.5, context="reset persistence")

    def test_return_dict_has_required_keys(self):
        tracker = ConstellationTracker()
        result = tracker.update("CONVERGENCE")
        for key in ["constellation", "run_length", "persistence_mult", "churn"]:
            assert key in result, f"Missing key: {key}"

    def test_return_dict_constellation_matches(self):
        tracker = ConstellationTracker()
        result = tracker.update("CLOSED_LOOP")
        assert result["constellation"] == "CLOSED_LOOP"


class TestConstellationTrackerChurn:
    """Test churn tracking: unique constellations in last 5 readings."""

    def test_single_constellation_low_churn(self):
        tracker = ConstellationTracker()
        for _ in range(5):
            result = tracker.update("CONVERGENCE")
        # 1 unique / 5 readings = 0.2
        assert_approx(result["churn"], 0.2, context="single constellation churn")

    def test_all_different_high_churn(self):
        tracker = ConstellationTracker()
        names = ["CONVERGENCE", "SCATTERING", "CLOSED_LOOP", "PATTERN_BREAK", "SURFACE_VARIATION"]
        for name in names:
            result = tracker.update(name)
        # 5 unique / 5 readings = 1.0
        assert_approx(result["churn"], 1.0, context="all different churn")

    def test_churn_uses_last_five_only(self):
        tracker = ConstellationTracker()
        # First 3 different
        tracker.update("CONVERGENCE")
        tracker.update("SCATTERING")
        tracker.update("CLOSED_LOOP")
        # Then 5 same -- last 5 window is all same
        for _ in range(5):
            result = tracker.update("PATTERN_BREAK")
        # Last 5 are all PATTERN_BREAK -> 1 unique / 5 = 0.2
        assert_approx(result["churn"], 0.2, context="churn last-5 window")

    def test_churn_with_fewer_than_five(self):
        tracker = ConstellationTracker()
        tracker.update("CONVERGENCE")
        result = tracker.update("SCATTERING")
        # 2 unique / 2 readings = 1.0
        assert_approx(result["churn"], 1.0, context="churn with 2 items")

    def test_churn_partial_window(self):
        tracker = ConstellationTracker()
        tracker.update("CONVERGENCE")
        tracker.update("CONVERGENCE")
        result = tracker.update("SCATTERING")
        # 2 unique / 3 readings = 0.67
        assert_approx(result["churn"], 0.67, tol=0.01, context="churn 3-item window")


# ---------------------------------------------------------------------------
# smooth_exposure Tests
# ---------------------------------------------------------------------------

class TestSmoothExposure:
    """Test asymmetric EMA smoothing."""

    def test_smoothing_down_uses_alpha_down(self):
        # raw < prev -> alpha_down = 0.6
        # result = 0.6 * 0.2 + 0.4 * 0.8 = 0.12 + 0.32 = 0.44
        result = smooth_exposure(0.2, 0.8)
        assert_approx(result, 0.44, context="smoothing down")

    def test_smoothing_up_uses_alpha_up(self):
        # raw > prev -> alpha_up = 0.3
        # result = 0.3 * 0.8 + 0.7 * 0.2 = 0.24 + 0.14 = 0.38
        result = smooth_exposure(0.8, 0.2)
        assert_approx(result, 0.38, context="smoothing up")

    def test_no_change_returns_same(self):
        # raw == prev -> alpha_up (since not raw < prev), but result same
        # 0.3 * 0.5 + 0.7 * 0.5 = 0.15 + 0.35 = 0.5
        result = smooth_exposure(0.5, 0.5)
        assert_approx(result, 0.5, context="no change")

    def test_extreme_zero(self):
        # raw=0.0, prev=1.0 -> alpha_down=0.6
        # 0.6 * 0.0 + 0.4 * 1.0 = 0.4
        result = smooth_exposure(0.0, 1.0)
        assert_approx(result, 0.4, context="extreme zero")

    def test_extreme_one(self):
        # raw=1.0, prev=0.0 -> alpha_up=0.3
        # 0.3 * 1.0 + 0.7 * 0.0 = 0.3
        result = smooth_exposure(1.0, 0.0)
        assert_approx(result, 0.3, context="extreme one")

    def test_both_zero(self):
        result = smooth_exposure(0.0, 0.0)
        assert_approx(result, 0.0, context="both zero")

    def test_both_one(self):
        result = smooth_exposure(1.0, 1.0)
        assert_approx(result, 1.0, context="both one")

    def test_custom_alpha_down(self):
        # raw < prev, custom alpha_down=0.9
        # 0.9 * 0.1 + 0.1 * 0.8 = 0.09 + 0.08 = 0.17
        result = smooth_exposure(0.1, 0.8, alpha_down=0.9)
        assert_approx(result, 0.17, context="custom alpha_down")

    def test_custom_alpha_up(self):
        # raw > prev, custom alpha_up=0.9
        # 0.9 * 0.8 + 0.1 * 0.1 = 0.72 + 0.01 = 0.73
        result = smooth_exposure(0.8, 0.1, alpha_up=0.9)
        assert_approx(result, 0.73, context="custom alpha_up")

    def test_asymmetry_down_reacts_faster(self):
        """Smoothing down (de-risk) should move more than smoothing up."""
        prev = 0.5
        # Going down: alpha_down=0.6 -> 0.6*0.2 + 0.4*0.5 = 0.32
        down_result = smooth_exposure(0.2, prev)
        # Going up same magnitude: alpha_up=0.3 -> 0.3*0.8 + 0.7*0.5 = 0.59
        up_result = smooth_exposure(0.8, prev)
        # Distance from prev going down should be larger relative to raw distance
        down_movement = abs(down_result - prev) / abs(0.2 - prev)  # 0.18/0.3 = 0.6
        up_movement = abs(up_result - prev) / abs(0.8 - prev)      # 0.09/0.3 = 0.3
        assert down_movement > up_movement, "De-risk should react faster than recovery"


# ---------------------------------------------------------------------------
# dhs_to_exposure Tests
# ---------------------------------------------------------------------------

class TestDhsToExposureBase:
    """Test base exposure tiers from DHS value alone (neutral constellation)."""

    def test_dhs_high_full_exposure(self):
        # DHS >= 0.80 -> base 1.0
        result = dhs_to_exposure(0.85, "CONVERGENCE", 0.0)
        assert_approx(result, 1.0, context="DHS 0.85")

    def test_dhs_exactly_080(self):
        result = dhs_to_exposure(0.80, "CONVERGENCE", 0.0)
        assert_approx(result, 1.0, context="DHS 0.80 boundary")

    def test_dhs_095(self):
        result = dhs_to_exposure(0.95, "CONVERGENCE", 0.0)
        assert_approx(result, 1.0, context="DHS 0.95")

    def test_dhs_065_lower_bound(self):
        # DHS 0.65: base = 0.5 + (0.65-0.65)/0.15 * 0.5 = 0.5
        result = dhs_to_exposure(0.65, "CONVERGENCE", 0.0)
        assert_approx(result, 0.5, context="DHS 0.65 lower bound")

    def test_dhs_079_upper_mid_tier(self):
        # DHS 0.79: base = 0.5 + (0.79-0.65)/0.15 * 0.5 = 0.5 + 0.14/0.15*0.5
        #         = 0.5 + 0.4667 = 0.9667
        result = dhs_to_exposure(0.79, "CONVERGENCE", 0.0)
        assert_approx(result, 0.9667, tol=0.01, context="DHS 0.79")

    def test_dhs_072_mid_tier(self):
        # DHS 0.72: base = 0.5 + (0.72-0.65)/0.15 * 0.5 = 0.5 + 0.2333 = 0.7333
        result = dhs_to_exposure(0.72, "CONVERGENCE", 0.0)
        assert_approx(result, 0.7333, tol=0.01, context="DHS 0.72")

    def test_dhs_050_lower_mid_tier(self):
        # DHS 0.50: base = 0.25 + (0.50-0.50)/0.15 * 0.25 = 0.25
        result = dhs_to_exposure(0.50, "CONVERGENCE", 0.0)
        assert_approx(result, 0.25, context="DHS 0.50 lower bound")

    def test_dhs_064_upper_lower_mid_tier(self):
        # DHS 0.64: base = 0.25 + (0.64-0.50)/0.15 * 0.25 = 0.25 + 0.2333 = 0.4833
        result = dhs_to_exposure(0.64, "CONVERGENCE", 0.0)
        assert_approx(result, 0.4833, tol=0.01, context="DHS 0.64")

    def test_dhs_035_low_tier(self):
        # DHS 0.35-0.49: base = 0.1
        result = dhs_to_exposure(0.40, "CONVERGENCE", 0.0)
        assert_approx(result, 0.20, context="DHS 0.40 -> floor 0.20")
        # base=0.1 but floor is 0.20, so clamped

    def test_dhs_035_exact(self):
        result = dhs_to_exposure(0.35, "CONVERGENCE", 0.0)
        # base = 0.1, floored to 0.20
        assert_approx(result, 0.20, context="DHS 0.35 exact")

    def test_dhs_049(self):
        result = dhs_to_exposure(0.49, "CONVERGENCE", 0.0)
        # base = 0.1, floored to 0.20
        assert_approx(result, 0.20, context="DHS 0.49")

    def test_dhs_below_035_distressed(self):
        # DHS < 0.35: base = 0.2
        result = dhs_to_exposure(0.20, "CONVERGENCE", 0.0)
        assert_approx(result, 0.20, context="DHS 0.20 distressed")

    def test_dhs_zero(self):
        result = dhs_to_exposure(0.0, "CONVERGENCE", 0.0)
        assert_approx(result, 0.20, context="DHS 0.0")

    def test_linear_interpolation_065_080(self):
        """Verify linear interpolation within 0.65-0.80 tier."""
        low = dhs_to_exposure(0.65, "CONVERGENCE", 0.0)
        mid = dhs_to_exposure(0.725, "CONVERGENCE", 0.0)
        high = dhs_to_exposure(0.80, "CONVERGENCE", 0.0)
        assert low < mid < high, f"Not monotonic: {low}, {mid}, {high}"

    def test_linear_interpolation_050_065(self):
        """Verify linear interpolation within 0.50-0.65 tier."""
        low = dhs_to_exposure(0.50, "CONVERGENCE", 0.0)
        mid = dhs_to_exposure(0.575, "CONVERGENCE", 0.0)
        high = dhs_to_exposure(0.64, "CONVERGENCE", 0.0)
        assert low < mid < high, f"Not monotonic: {low}, {mid}, {high}"


class TestDhsToExposureConstellationMods:
    """Test constellation modifier effects on exposure."""

    def test_convergence_no_reduction(self):
        # CONVERGENCE mod is 0.0
        result = dhs_to_exposure(0.85, "CONVERGENCE", 0.0)
        assert_approx(result, 1.0, context="CONVERGENCE no mod")

    def test_dip_and_recovery_no_reduction(self):
        # DIP_AND_RECOVERY mod is 0.0
        result = dhs_to_exposure(0.85, "DIP_AND_RECOVERY", 0.0)
        assert_approx(result, 1.0, context="DIP_AND_RECOVERY no mod")

    def test_high_symmetry_slight_reduction(self):
        # HIGH_SYMMETRY mod = -0.05 * persistence_mult
        result = dhs_to_exposure(0.85, "HIGH_SYMMETRY", 0.0, persistence_mult=1.0)
        assert_approx(result, 0.95, context="HIGH_SYMMETRY mod")

    def test_surface_variation_reduction(self):
        # SURFACE_VARIATION mod = -0.1
        result = dhs_to_exposure(0.85, "SURFACE_VARIATION", 0.0, persistence_mult=1.0)
        assert_approx(result, 0.90, context="SURFACE_VARIATION mod")

    def test_closed_loop_reduction(self):
        # CLOSED_LOOP mod = -0.1
        result = dhs_to_exposure(0.85, "CLOSED_LOOP", 0.0, persistence_mult=1.0)
        assert_approx(result, 0.90, context="CLOSED_LOOP mod")

    def test_pattern_break_reduction(self):
        # PATTERN_BREAK mod = -0.2
        result = dhs_to_exposure(0.85, "PATTERN_BREAK", 0.0, persistence_mult=1.0)
        assert_approx(result, 0.80, context="PATTERN_BREAK mod")

    def test_repeated_disruption_reduction(self):
        # REPEATED_DISRUPTION mod = -0.25
        result = dhs_to_exposure(0.85, "REPEATED_DISRUPTION", 0.0, persistence_mult=1.0)
        assert_approx(result, 0.75, context="REPEATED_DISRUPTION mod")

    def test_scattering_heavy_reduction(self):
        # SCATTERING mod = -0.4
        result = dhs_to_exposure(0.85, "SCATTERING", 0.0, persistence_mult=1.0)
        assert_approx(result, 0.60, context="SCATTERING mod")

    def test_unknown_constellation_no_mod(self):
        result = dhs_to_exposure(0.85, "UNKNOWN_THING", 0.0, persistence_mult=1.0)
        assert_approx(result, 1.0, context="unknown constellation")

    def test_none_constellation_no_mod(self):
        result = dhs_to_exposure(0.85, "NONE", 0.0, persistence_mult=1.0)
        assert_approx(result, 1.0, context="NONE constellation")


class TestDhsToExposurePersistence:
    """Test persistence_mult scaling of constellation modifiers."""

    def test_persistence_half_halves_mod(self):
        # SCATTERING mod = -0.4, persistence 0.5 -> effective mod = -0.2
        # base = 1.0, result = 0.8
        result = dhs_to_exposure(0.85, "SCATTERING", 0.0, persistence_mult=0.5)
        assert_approx(result, 0.80, context="persistence 0.5")

    def test_persistence_point_eight(self):
        # SCATTERING mod = -0.4, persistence 0.8 -> effective mod = -0.32
        # base = 1.0, result = 0.68
        result = dhs_to_exposure(0.85, "SCATTERING", 0.0, persistence_mult=0.8)
        assert_approx(result, 0.68, context="persistence 0.8")

    def test_persistence_full(self):
        # SCATTERING mod = -0.4, persistence 1.0 -> effective mod = -0.4
        # base = 1.0, result = 0.6
        result = dhs_to_exposure(0.85, "SCATTERING", 0.0, persistence_mult=1.0)
        assert_approx(result, 0.60, context="persistence 1.0")

    def test_persistence_zero_negates_mod(self):
        # persistence 0.0 -> no constellation effect
        result = dhs_to_exposure(0.85, "SCATTERING", 0.0, persistence_mult=0.0)
        assert_approx(result, 1.0, context="persistence 0.0")


class TestDhsToExposureLoopStrength:
    """Test loop_strength effect on exposure."""

    def test_low_loop_no_effect(self):
        result = dhs_to_exposure(0.85, "CONVERGENCE", 0.3)
        assert_approx(result, 1.0, context="loop 0.3")

    def test_loop_at_threshold_no_effect(self):
        result = dhs_to_exposure(0.85, "CONVERGENCE", 0.5)
        assert_approx(result, 1.0, context="loop 0.5 at threshold")

    def test_high_loop_reduces_exposure(self):
        # loop > 0.5 -> mod -= 0.05
        result = dhs_to_exposure(0.85, "CONVERGENCE", 0.7)
        assert_approx(result, 0.95, context="loop 0.7")

    def test_very_high_loop(self):
        result = dhs_to_exposure(0.85, "CONVERGENCE", 1.0)
        assert_approx(result, 0.95, context="loop 1.0")

    def test_loop_combined_with_constellation(self):
        # SCATTERING -0.4 + loop -0.05 = -0.45, base=1.0, result=0.55
        result = dhs_to_exposure(0.85, "SCATTERING", 0.7, persistence_mult=1.0)
        assert_approx(result, 0.55, context="scattering + high loop")


class TestDhsToExposureStress:
    """Test drawdown and volatility stress effects."""

    def test_no_stress(self):
        result = dhs_to_exposure(0.85, "CONVERGENCE", 0.0, dd_stress=0.0, vol_stress=0.0)
        assert_approx(result, 1.0, context="no stress")

    def test_dd_stress_light(self):
        # dd_stress > 0.1 -> mod -= 0.05
        result = dhs_to_exposure(0.85, "CONVERGENCE", 0.0, dd_stress=0.15)
        assert_approx(result, 0.95, context="light dd stress")

    def test_dd_stress_moderate(self):
        # dd_stress > 0.3 -> mod -= 0.15
        result = dhs_to_exposure(0.85, "CONVERGENCE", 0.0, dd_stress=0.4)
        assert_approx(result, 0.85, context="moderate dd stress")

    def test_dd_stress_heavy(self):
        # dd_stress > 0.5 -> mod -= 0.3
        result = dhs_to_exposure(0.85, "CONVERGENCE", 0.0, dd_stress=0.6)
        assert_approx(result, 0.70, context="heavy dd stress")

    def test_dd_stress_at_boundaries(self):
        # 0.1 exactly: not > 0.1, so no cut
        result = dhs_to_exposure(0.85, "CONVERGENCE", 0.0, dd_stress=0.1)
        assert_approx(result, 1.0, context="dd stress at 0.1 boundary")

        # 0.3 exactly: > 0.1 tier, mod -= 0.05 (not > 0.3)
        # Wait -- dd_stress=0.3 is NOT > 0.3, so falls to elif > 0.1
        result = dhs_to_exposure(0.85, "CONVERGENCE", 0.0, dd_stress=0.3)
        assert_approx(result, 0.95, context="dd stress at 0.3 boundary")

        # 0.5 exactly: > 0.3 tier, mod -= 0.15
        result = dhs_to_exposure(0.85, "CONVERGENCE", 0.0, dd_stress=0.5)
        assert_approx(result, 0.85, context="dd stress at 0.5 boundary")

    def test_vol_stress_moderate(self):
        # vol_stress > 0.15 -> mod -= 0.05
        result = dhs_to_exposure(0.85, "CONVERGENCE", 0.0, vol_stress=0.2)
        assert_approx(result, 0.95, context="moderate vol stress")

    def test_vol_stress_high(self):
        # vol_stress > 0.3 -> mod -= 0.15
        result = dhs_to_exposure(0.85, "CONVERGENCE", 0.0, vol_stress=0.5)
        assert_approx(result, 0.85, context="high vol stress")

    def test_vol_stress_at_boundaries(self):
        # 0.15 exactly: not > 0.15
        result = dhs_to_exposure(0.85, "CONVERGENCE", 0.0, vol_stress=0.15)
        assert_approx(result, 1.0, context="vol stress at 0.15 boundary")

        # 0.3 exactly: > 0.15 tier, mod -= 0.05
        result = dhs_to_exposure(0.85, "CONVERGENCE", 0.0, vol_stress=0.3)
        assert_approx(result, 0.95, context="vol stress at 0.3 boundary")

    def test_combined_dd_and_vol_stress(self):
        # dd > 0.5 -> -0.3, vol > 0.3 -> -0.15 => total mod = -0.45
        # base=1.0, result=0.55
        result = dhs_to_exposure(0.85, "CONVERGENCE", 0.0, dd_stress=0.6, vol_stress=0.5)
        assert_approx(result, 0.55, context="combined stress")

    def test_all_penalties_combined(self):
        # SCATTERING(-0.4) + loop>0.5(-0.05) + dd>0.5(-0.3) + vol>0.3(-0.15)
        # total mod = -0.9, base=1.0, raw=0.1 -> floored to 0.20
        result = dhs_to_exposure(
            0.85, "SCATTERING", 0.8,
            dd_stress=0.6, vol_stress=0.5, persistence_mult=1.0,
        )
        assert_approx(result, 0.20, context="all penalties -> floor")


class TestDhsToExposureFloorCeiling:
    """Test that result is always within [0.20, 1.0]."""

    def test_floor_never_below_020(self):
        # Maximum penalties scenario
        result = dhs_to_exposure(
            0.10, "SCATTERING", 1.0,
            dd_stress=0.9, vol_stress=0.9, persistence_mult=1.0,
        )
        assert_approx(result, 0.20, context="floor enforcement")

    def test_ceiling_never_above_1(self):
        # Best case scenario -- no penalties, high DHS
        result = dhs_to_exposure(0.99, "CONVERGENCE", 0.0)
        assert result <= 1.0, f"Exceeded ceiling: {result}"

    def test_floor_with_low_dhs_and_scattering(self):
        result = dhs_to_exposure(0.30, "SCATTERING", 0.8, persistence_mult=1.0)
        assert result >= 0.20, f"Below floor: {result}"
        assert_approx(result, 0.20, context="low dhs + scattering")

    def test_many_random_combinations_respect_bounds(self):
        """Brute-force check that bounds hold across many inputs."""
        import itertools
        dhs_vals = [0.0, 0.2, 0.35, 0.5, 0.65, 0.8, 1.0]
        constellations = [
            "CONVERGENCE", "SCATTERING", "CLOSED_LOOP",
            "PATTERN_BREAK", "REPEATED_DISRUPTION", "NONE",
        ]
        loops = [0.0, 0.5, 0.7, 1.0]
        stresses = [0.0, 0.2, 0.4, 0.6]

        for dhs in dhs_vals:
            for const in constellations:
                for loop in loops:
                    for dd in stresses:
                        for vol in stresses:
                            result = dhs_to_exposure(
                                dhs, const, loop,
                                dd_stress=dd, vol_stress=vol,
                                persistence_mult=1.0,
                            )
                            assert 0.20 <= result <= 1.0, (
                                f"Out of bounds: {result} for dhs={dhs}, "
                                f"const={const}, loop={loop}, dd={dd}, vol={vol}"
                            )


# ---------------------------------------------------------------------------
# run_engine_on_window Tests
# ---------------------------------------------------------------------------

class TestRunEngineOnWindow:
    """Test the full engine pipeline with mock analyze functions."""

    def test_returns_tuple(self):
        tracker = ConstellationTracker()
        analyze_fn = make_mock_analyze_fn()
        result = run_engine_on_window(
            klines=[], analyze_fn=analyze_fn,
            symbol="TEST", timeframe="1h",
            tracker=tracker, prev_smooth=1.0,
        )
        assert isinstance(result, tuple), f"Expected tuple, got {type(result)}"
        assert len(result) == 2, f"Expected 2 elements, got {len(result)}"

    def test_decision_dict_has_required_keys(self):
        tracker = ConstellationTracker()
        analyze_fn = make_mock_analyze_fn()
        decision, _ = run_engine_on_window(
            klines=[], analyze_fn=analyze_fn,
            symbol="TEST", timeframe="1h",
            tracker=tracker, prev_smooth=1.0,
        )
        required_keys = [
            "dhs", "constellation", "loop", "dd_stress", "vol_stress",
            "exposure_raw", "exposure_smooth", "run_length", "churn",
        ]
        for key in required_keys:
            assert key in decision, f"Missing key in decision: {key}"

    def test_decision_values_are_rounded(self):
        tracker = ConstellationTracker()
        analyze_fn = make_mock_analyze_fn(dhs=0.72345678)
        decision, _ = run_engine_on_window(
            klines=[], analyze_fn=analyze_fn,
            symbol="TEST", timeframe="1h",
            tracker=tracker, prev_smooth=1.0,
        )
        # dhs should be rounded to 3 decimal places
        dhs_str = str(decision["dhs"])
        decimal_places = len(dhs_str.split(".")[-1]) if "." in dhs_str else 0
        assert decimal_places <= 3, f"DHS has too many decimal places: {decision['dhs']}"

    def test_new_prev_smooth_is_float(self):
        tracker = ConstellationTracker()
        analyze_fn = make_mock_analyze_fn()
        _, new_smooth = run_engine_on_window(
            klines=[], analyze_fn=analyze_fn,
            symbol="TEST", timeframe="1h",
            tracker=tracker, prev_smooth=1.0,
        )
        assert isinstance(new_smooth, float), f"Expected float, got {type(new_smooth)}"

    def test_tracker_updated(self):
        tracker = ConstellationTracker()
        analyze_fn = make_mock_analyze_fn(constellation="SCATTERING")
        run_engine_on_window(
            klines=[], analyze_fn=analyze_fn,
            symbol="TEST", timeframe="1h",
            tracker=tracker, prev_smooth=1.0,
        )
        assert tracker.current == "SCATTERING"
        assert tracker.run_length == 1
        assert len(tracker.history) == 1

    def test_constellation_in_decision_matches(self):
        tracker = ConstellationTracker()
        analyze_fn = make_mock_analyze_fn(constellation="CLOSED_LOOP")
        decision, _ = run_engine_on_window(
            klines=[], analyze_fn=analyze_fn,
            symbol="TEST", timeframe="1h",
            tracker=tracker, prev_smooth=1.0,
        )
        assert decision["constellation"] == "CLOSED_LOOP"

    def test_dhs_in_decision_matches(self):
        tracker = ConstellationTracker()
        analyze_fn = make_mock_analyze_fn(dhs=0.55)
        decision, _ = run_engine_on_window(
            klines=[], analyze_fn=analyze_fn,
            symbol="TEST", timeframe="1h",
            tracker=tracker, prev_smooth=1.0,
        )
        assert_approx(decision["dhs"], 0.55, context="decision dhs")

    def test_exposure_smooth_uses_smoothing(self):
        tracker = ConstellationTracker()
        # High DHS, good constellation -> raw exposure = 1.0
        analyze_fn = make_mock_analyze_fn(dhs=0.85, constellation="CONVERGENCE", loop=0.0)
        decision, new_smooth = run_engine_on_window(
            klines=[], analyze_fn=analyze_fn,
            symbol="TEST", timeframe="1h",
            tracker=tracker, prev_smooth=0.5,
        )
        # raw=1.0 (but halved by persistence_mult=0.5 for first window? No, CONVERGENCE mod is 0.0)
        # Actually: base=1.0, CONVERGENCE mod=0.0*0.5=0.0, loop=0.0, no stress -> raw=1.0
        # smooth = alpha_up * 1.0 + (1-alpha_up) * 0.5 = 0.3 + 0.35 = 0.65
        assert_approx(decision["exposure_raw"], 1.0, tol=0.01, context="raw exposure")
        assert_approx(new_smooth, 0.65, tol=0.01, context="smoothed exposure")

    def test_error_returns_none_and_preserves_prev(self):
        tracker = ConstellationTracker()
        analyze_fn = make_failing_analyze_fn()
        decision, new_smooth = run_engine_on_window(
            klines=[], analyze_fn=analyze_fn,
            symbol="TEST", timeframe="1h",
            tracker=tracker, prev_smooth=0.75,
        )
        assert decision is None, "Decision should be None on error"
        assert_approx(new_smooth, 0.75, context="prev_smooth preserved on error")

    def test_error_does_not_modify_tracker(self):
        tracker = ConstellationTracker()
        analyze_fn = make_failing_analyze_fn()
        run_engine_on_window(
            klines=[], analyze_fn=analyze_fn,
            symbol="TEST", timeframe="1h",
            tracker=tracker, prev_smooth=0.75,
        )
        assert tracker.current is None, "Tracker should not be modified on error"
        assert tracker.run_length == 0
        assert tracker.history == []

    def test_stress_values_propagate(self):
        tracker = ConstellationTracker()
        analyze_fn = make_mock_analyze_fn(dd_stress=0.6, vol_stress=0.4)
        decision, _ = run_engine_on_window(
            klines=[], analyze_fn=analyze_fn,
            symbol="TEST", timeframe="1h",
            tracker=tracker, prev_smooth=1.0,
        )
        assert_approx(decision["dd_stress"], 0.6, context="dd_stress propagated")
        assert_approx(decision["vol_stress"], 0.4, context="vol_stress propagated")

    def test_multiple_windows_sequential(self):
        """Run multiple windows and verify tracker state evolves."""
        tracker = ConstellationTracker()
        prev_smooth = 1.0

        # Window 1: good conditions
        fn1 = make_mock_analyze_fn(dhs=0.85, constellation="CONVERGENCE")
        d1, prev_smooth = run_engine_on_window(
            klines=[], analyze_fn=fn1,
            symbol="TEST", timeframe="1h",
            tracker=tracker, prev_smooth=prev_smooth,
        )
        assert tracker.run_length == 1

        # Window 2: same constellation
        d2, prev_smooth = run_engine_on_window(
            klines=[], analyze_fn=fn1,
            symbol="TEST", timeframe="1h",
            tracker=tracker, prev_smooth=prev_smooth,
        )
        assert tracker.run_length == 2

        # Window 3: different constellation, bad
        fn3 = make_mock_analyze_fn(dhs=0.40, constellation="SCATTERING")
        d3, prev_smooth = run_engine_on_window(
            klines=[], analyze_fn=fn3,
            symbol="TEST", timeframe="1h",
            tracker=tracker, prev_smooth=prev_smooth,
        )
        assert tracker.run_length == 1
        assert tracker.current == "SCATTERING"
        assert len(tracker.history) == 3
        # Exposure should have dropped
        assert d3["exposure_raw"] < d1["exposure_raw"]

    def test_no_constellations_in_result(self):
        """When analyze returns empty constellations, should use 'NONE'."""
        tracker = ConstellationTracker()

        def analyze_fn(klines, symbol="TEST", timeframe="1h"):
            return {
                "dialectical_health": 0.7,
                "constellations": [],
                "loop_strength": 0.3,
                "stress": {"drawdown": 0.0, "vol_expansion": 0.0},
            }

        decision, _ = run_engine_on_window(
            klines=[], analyze_fn=analyze_fn,
            symbol="TEST", timeframe="1h",
            tracker=tracker, prev_smooth=1.0,
        )
        assert decision["constellation"] == "NONE"

    def test_missing_stress_keys(self):
        """When stress dict is missing keys, should default to 0.0."""
        tracker = ConstellationTracker()

        def analyze_fn(klines, symbol="TEST", timeframe="1h"):
            return {
                "dialectical_health": 0.7,
                "constellations": [{"detected": "CONVERGENCE", "confidence": 0.8}],
                "loop_strength": 0.3,
                "stress": {},
            }

        decision, _ = run_engine_on_window(
            klines=[], analyze_fn=analyze_fn,
            symbol="TEST", timeframe="1h",
            tracker=tracker, prev_smooth=1.0,
        )
        assert decision is not None
        assert_approx(decision["dd_stress"], 0.0, context="missing dd_stress defaults 0")
        assert_approx(decision["vol_stress"], 0.0, context="missing vol_stress defaults 0")

    def test_missing_stress_dict_entirely(self):
        """When stress dict is missing entirely, should default to 0.0."""
        tracker = ConstellationTracker()

        def analyze_fn(klines, symbol="TEST", timeframe="1h"):
            return {
                "dialectical_health": 0.7,
                "constellations": [{"detected": "CONVERGENCE", "confidence": 0.8}],
                "loop_strength": 0.3,
            }

        decision, _ = run_engine_on_window(
            klines=[], analyze_fn=analyze_fn,
            symbol="TEST", timeframe="1h",
            tracker=tracker, prev_smooth=1.0,
        )
        assert decision is not None
        assert_approx(decision["dd_stress"], 0.0, context="no stress dict dd")
        assert_approx(decision["vol_stress"], 0.0, context="no stress dict vol")


# ---------------------------------------------------------------------------
# CLI runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import traceback

    test_classes = [
        TestConstellationTrackerInit,
        TestConstellationTrackerUpdate,
        TestConstellationTrackerPersistence,
        TestConstellationTrackerChurn,
        TestSmoothExposure,
        TestDhsToExposureBase,
        TestDhsToExposureConstellationMods,
        TestDhsToExposurePersistence,
        TestDhsToExposureLoopStrength,
        TestDhsToExposureStress,
        TestDhsToExposureFloorCeiling,
        TestRunEngineOnWindow,
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
                if hasattr(instance, "setup_method"):
                    instance.setup_method()
                getattr(instance, method_name)()
                if hasattr(instance, "teardown_method"):
                    instance.teardown_method()
                print(f"  PASS  {test_name}")
                passed += 1
            except Exception as e:
                if hasattr(instance, "teardown_method"):
                    try:
                        instance.teardown_method()
                    except Exception:
                        pass
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
