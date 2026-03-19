"""Tests for regime_drift.py — slow regime transition detection."""
import pytest

from regime_drift import compute_transition_warning, TransitionWarning


def _make_analysis(un_agg=0.6, no_agg=0.4, no3=0.4, no5=0.4):
    """Create a minimal analysis_result dict for testing."""
    return {
        "channels": {
            "unity": {
                "aggregate": un_agg,
                "Un1": un_agg, "Un2": un_agg, "Un3": un_agg,
                "Un4": un_agg, "Un5": un_agg, "Un6": un_agg,
            },
            "novelty": {
                "aggregate": no_agg,
                "No3": no3, "No5": no5,
            },
        },
        "temporal": {"dominant_sequence": []},
    }


class TestBoundedDrift:
    def test_stable_bounded_no_drift(self):
        """Bounded regime with stable DHS should show no drift."""
        tw = compute_transition_warning(
            regime="bounded",
            dhs=0.75,
            analysis_result=_make_analysis(un_agg=0.7, no_agg=0.3),
            recent_dhs_values=[0.74, 0.75, 0.75, 0.76],
        )
        assert tw.drift_score < 0.15
        assert tw.drifting_toward is None

    def test_declining_dhs_drifts_toward_active(self):
        """Bounded regime with declining DHS should drift toward active."""
        tw = compute_transition_warning(
            regime="bounded",
            dhs=0.58,
            analysis_result=_make_analysis(un_agg=0.45, no_agg=0.6),
            recent_dhs_values=[0.70, 0.68, 0.65, 0.62, 0.58],
        )
        assert tw.drifting_toward == "active"
        assert tw.drift_score > 0.15

    def test_sharply_declining_dhs_drifts_toward_unstable(self):
        """Bounded regime with DHS near floor drifts toward unstable."""
        tw = compute_transition_warning(
            regime="bounded",
            dhs=0.40,
            analysis_result=_make_analysis(un_agg=0.35, no_agg=0.7),
            recent_dhs_values=[0.55, 0.50, 0.47, 0.43, 0.40],
        )
        assert tw.drifting_toward == "unstable"
        assert tw.drift_score > 0.15


class TestActiveDrift:
    def test_declining_active_drifts_toward_unstable(self):
        """Active regime with declining DHS should drift toward unstable."""
        tw = compute_transition_warning(
            regime="active",
            dhs=0.42,
            analysis_result=_make_analysis(un_agg=0.4, no_agg=0.6),
            recent_dhs_values=[0.55, 0.52, 0.48, 0.45, 0.42],
        )
        assert tw.drifting_toward == "unstable"
        assert tw.drift_score > 0.15

    def test_rising_active_drifts_toward_bounded(self):
        """Active regime with rising DHS should drift toward bounded."""
        tw = compute_transition_warning(
            regime="active",
            dhs=0.70,
            analysis_result=_make_analysis(un_agg=0.7, no_agg=0.3),
            recent_dhs_values=[0.60, 0.63, 0.65, 0.68, 0.70],
        )
        assert tw.drifting_toward == "bounded"
        assert tw.drift_score > 0.15


class TestUnstableDrift:
    def test_recovering_unstable_drifts_toward_active(self):
        """Unstable regime with rising DHS should drift toward active."""
        tw = compute_transition_warning(
            regime="unstable",
            dhs=0.48,
            analysis_result=_make_analysis(un_agg=0.5, no_agg=0.4),
            recent_dhs_values=[0.35, 0.38, 0.42, 0.45, 0.48],
        )
        assert tw.drifting_toward == "active"
        assert tw.drift_score > 0.15


class TestTransitionMinutes:
    def test_stable_dhs_returns_none(self):
        """Stable DHS should return None for transition minutes."""
        tw = compute_transition_warning(
            regime="bounded",
            dhs=0.75,
            analysis_result=_make_analysis(),
            recent_dhs_values=[0.75, 0.75, 0.75],
        )
        assert tw.estimated_transition_minutes is None

    def test_declining_dhs_returns_positive_minutes(self):
        """Declining DHS should estimate positive transition minutes."""
        tw = compute_transition_warning(
            regime="bounded",
            dhs=0.60,
            analysis_result=_make_analysis(un_agg=0.5, no_agg=0.5),
            recent_dhs_values=[0.70, 0.67, 0.64, 0.62, 0.60],
        )
        if tw.estimated_transition_minutes is not None:
            assert tw.estimated_transition_minutes >= 5.0
            assert tw.estimated_transition_minutes <= 480.0


class TestDriftScoreBounds:
    def test_drift_score_clamped_to_0_1(self):
        """Drift score should always be between 0 and 1."""
        # Extreme case — very fast decline
        tw = compute_transition_warning(
            regime="bounded",
            dhs=0.36,
            analysis_result=_make_analysis(un_agg=0.3, no_agg=0.9, no3=0.9, no5=0.9),
            recent_dhs_values=[0.60, 0.55, 0.50, 0.43, 0.36],
            dominant_sequence=["CONVERGENCE", "SCATTERING"],
        )
        assert 0.0 <= tw.drift_score <= 1.0

    def test_no_data_returns_zero_drift(self):
        """No DHS history should return zero drift."""
        tw = compute_transition_warning(
            regime="bounded",
            dhs=0.70,
            analysis_result=_make_analysis(),
        )
        assert tw.drift_score == 0.0


class TestTierGating:
    """Tier gating is tested via regime_service, not here.
    These tests verify the warning computation itself works correctly."""

    def test_warning_returns_dataclass(self):
        tw = compute_transition_warning(
            regime="bounded", dhs=0.70,
            analysis_result=_make_analysis(),
        )
        assert isinstance(tw, TransitionWarning)
        assert isinstance(tw.drivers, list)
        assert isinstance(tw.detail, str)
