"""
Regime temporal stability estimation.

Estimates how long the current structural regime will persist
based on DHS dynamics, channel trends, constellation persistence,
and historical transition patterns.

This is structural stability measurement, NOT price prediction.

Patent Pending #63/923,592
"""

import math
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass


@dataclass
class RegimeStability:
    """Stability estimate for the current regime."""

    # Core output
    halflife_minutes: float          # Estimated minutes until 50% transition probability
    stability_score: float           # 0.0-1.0 composite (1.0 = maximally stable)
    instability_risk: str            # "low" | "moderate" | "elevated" | "high"
    time_horizon: str                # Human-readable: "2-4 hours", "15-30 minutes", etc.

    # Components (what's driving the estimate)
    dhs_momentum: float              # DHS slope: positive = stabilizing, negative = destabilizing
    unity_trend: str                 # "rising" | "stable" | "declining" | "collapsing"
    novelty_pressure: float          # 0.0-1.0, recent novelty spike intensity
    persistence_factor: float        # Multiplier from constellation persistence count
    sequence_risk: float             # 0.0-1.0, risk from known destabilizing sequences

    # Actionable interpretation
    urgency: str                     # "none" | "watch" | "prepare_exit" | "exit_now"
    exit_window_minutes: Optional[float]  # If regime is degrading, estimated safe exit window


# ── Historical transition probabilities ─────────────────────────────────
# Derived from 240+ graded predictions. These are empirical base rates
# for how long each regime type persists before transitioning.

BASE_HALFLIFE_MINUTES = {
    "bounded": 240.0,    # 4 hours — bounded regimes are the most stable
    "active":  120.0,    # 2 hours — active regimes are transitional
    "unstable": 45.0,    # 45 minutes — unstable regimes resolve quickly
}

# Constellation-specific modifiers (multiply base halflife)
CONSTELLATION_HALFLIFE_MODIFIER = {
    "CLOSED_LOOP":          1.4,   # Very stable — locked in
    "HIGH_SYMMETRY":        1.6,   # Extremely stable — equilibrium
    "CONVERGENCE":          0.7,   # Active but directional — will resolve
    "SURFACE_VARIATION":    1.1,   # Choppy but holding
    "DIP_AND_RECOVERY":     0.6,   # Recovery underway — transitional
    "SCATTERING":           0.5,   # Actively fragmenting — short-lived
    "REPEATED_DISRUPTION":  0.4,   # Chronic instability — very short-lived
    "PATTERN_BREAK":        0.5,   # Regime shift in progress
    "NOMINAL":              1.0,   # No modification
}

# Known destabilizing sequences and their risk multipliers
DESTABILIZING_SEQUENCES = {
    ("CLOSED_LOOP", "PATTERN_BREAK"):        0.6,
    ("CONVERGENCE", "SCATTERING"):           0.3,
    ("PATTERN_BREAK", "SCATTERING"):         0.3,
    ("REPEATED_DISRUPTION", "SCATTERING"):   0.2,
    ("SURFACE_VARIATION", "PATTERN_BREAK"):  0.5,
}

# Known stabilizing sequences
STABILIZING_SEQUENCES = {
    ("PATTERN_BREAK", "CONVERGENCE"):        1.5,
    ("DIP_AND_RECOVERY", "CONVERGENCE"):     1.4,
    ("PATTERN_BREAK", "DIP_AND_RECOVERY"):   1.3,
    ("CLOSED_LOOP", "HIGH_SYMMETRY"):        1.8,
}

# Timeframe scaling factors (relative to 1h baseline)
TIMEFRAME_SCALE = {
    "1m": 1/60, "3m": 3/60, "5m": 5/60, "15m": 0.25, "30m": 0.5,
    "1h": 1.0, "2h": 2.0, "4h": 4.0, "6h": 6.0, "8h": 8.0,
    "12h": 12.0, "1d": 24.0, "3d": 72.0, "1w": 168.0,
}


def compute_dhs_momentum(dhs_values: List[float]) -> float:
    """
    Compute DHS slope from recent values using simple linear regression.

    Positive = DHS trending up (stabilizing).
    Negative = DHS trending down (destabilizing).
    If only 1 value or empty, return 0.0 (no trend data).
    """
    if len(dhs_values) < 2:
        return 0.0

    n = len(dhs_values)
    x_mean = (n - 1) / 2.0
    y_mean = sum(dhs_values) / n

    numerator = 0.0
    denominator = 0.0
    for i, y in enumerate(dhs_values):
        dx = i - x_mean
        numerator += dx * (y - y_mean)
        denominator += dx * dx

    if denominator == 0:
        return 0.0

    slope = numerator / denominator
    # Clamp to [-1, 1] range for sanity
    return max(-1.0, min(1.0, slope))


def assess_unity_trend(analysis_result: dict) -> Tuple[str, float]:
    """
    Assess unity dimension trend from full analysis.

    Returns (trend_label, trend_magnitude).
    trend_label: "rising" | "stable" | "declining" | "collapsing"
    """
    channels = analysis_result.get("channels", {})
    unity = channels.get("unity", {})
    un_agg = unity.get("aggregate", 0.5)

    # Check individual unity channels for directional signal
    un_values = []
    for key in ["Un1", "Un2", "Un3", "Un4", "Un5", "Un6"]:
        val = unity.get(key)
        if val is not None:
            un_values.append(val)

    # Use the spread of unity values as a secondary signal
    if un_values:
        spread = max(un_values) - min(un_values)
    else:
        spread = 0.0

    if un_agg >= 0.7:
        return ("stable", un_agg) if spread < 0.3 else ("rising", un_agg)
    elif un_agg >= 0.6:
        return ("rising", un_agg) if spread < 0.25 else ("stable", un_agg)
    elif un_agg >= 0.4:
        return ("declining", un_agg)
    else:
        return ("collapsing", un_agg)


def assess_novelty_pressure(analysis_result: dict) -> float:
    """
    Compute novelty pressure score (0.0-1.0).

    High novelty pressure = structural disruption incoming.
    Weight: No_agg * 0.4 + No3 * 0.3 + No5 * 0.3
    """
    channels = analysis_result.get("channels", {})
    novelty = channels.get("novelty", {})
    no_agg = novelty.get("aggregate", 0.5)
    no3 = novelty.get("No3", no_agg)  # Rhythmic novelty
    no5 = novelty.get("No5", no_agg)  # Self-interruption novelty

    pressure = no_agg * 0.4 + no3 * 0.3 + no5 * 0.3
    return max(0.0, min(1.0, pressure))


def compute_persistence_factor(persistence_count: int, constellation: str) -> float:
    """
    Compute halflife multiplier from constellation persistence.

    Longer persistence = more stable (higher multiplier) for bounded regimes.
    For unstable regimes, persistence means entrenchment but with a lower cap.
    """
    from regime_service import REGIME_MAP

    regime_type = REGIME_MAP.get(constellation, ("bounded", 2.0, ""))[0]

    if regime_type == "bounded":
        factor = 1.0 + (persistence_count * 0.15)
        return min(factor, 2.5)
    elif regime_type == "unstable":
        factor = 1.0 + (persistence_count * 0.1)
        return min(factor, 1.5)
    else:  # active
        factor = 1.0 + (persistence_count * 0.08)
        return min(factor, 1.5)


def assess_sequence_risk(dominant_sequence: List[str]) -> Tuple[float, float]:
    """
    Check recent constellation sequence against known patterns.

    Returns (sequence_risk, sequence_modifier).
    sequence_risk: 0.0-1.0 (0 = no risk, 1 = cascading instability)
    sequence_modifier: multiplier for halflife (< 1.0 = shortening, > 1.0 = lengthening)
    """
    if len(dominant_sequence) < 2:
        return (0.0, 1.0)

    # Check last pair
    last_pair = (dominant_sequence[-2], dominant_sequence[-1])

    if last_pair in DESTABILIZING_SEQUENCES:
        modifier = DESTABILIZING_SEQUENCES[last_pair]
        risk = 1.0 - modifier  # Lower modifier = higher risk
        return (risk, modifier)

    if last_pair in STABILIZING_SEQUENCES:
        modifier = STABILIZING_SEQUENCES[last_pair]
        risk = 0.0
        return (risk, modifier)

    return (0.0, 1.0)


def _halflife_to_time_horizon(halflife: float) -> str:
    """Convert halflife minutes to human-readable time horizon."""
    if halflife < 15:
        return "under 15 minutes"
    elif halflife < 30:
        return "15-30 minutes"
    elif halflife < 60:
        return "30-60 minutes"
    elif halflife < 120:
        return "1-2 hours"
    elif halflife < 240:
        return "2-4 hours"
    elif halflife < 480:
        return "4-8 hours"
    else:
        return "8+ hours"


def estimate_regime_stability(
    regime: str,
    constellation: str,
    dhs: float,
    exposure: float,
    analysis_result: dict,
    persistence_count: int = 0,
    dominant_sequence: Optional[List[str]] = None,
    recent_dhs_values: Optional[List[float]] = None,
    timeframe: str = "1h",
) -> RegimeStability:
    """
    Main entry point. Estimate regime temporal stability.

    Combines DHS dynamics, channel trends, constellation persistence,
    and sequence patterns into a single stability estimate.
    """
    if dominant_sequence is None:
        dominant_sequence = []
    if recent_dhs_values is None:
        recent_dhs_values = []

    # 1. Base halflife from regime type
    halflife = BASE_HALFLIFE_MINUTES.get(regime, 120.0)

    # 2. Constellation modifier
    constellation_mod = CONSTELLATION_HALFLIFE_MODIFIER.get(constellation, 1.0)
    halflife *= constellation_mod

    # 3. DHS momentum
    momentum = compute_dhs_momentum(recent_dhs_values)

    # 4. Unity trend
    unity_label, unity_mag = assess_unity_trend(analysis_result)

    # 5. Novelty pressure
    novelty_press = assess_novelty_pressure(analysis_result)

    # 6. Persistence factor
    persist_factor = compute_persistence_factor(persistence_count, constellation)
    halflife *= persist_factor

    # 7. Sequence risk
    seq_risk, seq_modifier = assess_sequence_risk(dominant_sequence)
    halflife *= seq_modifier

    # 9. DHS level adjustment
    if dhs > 0.75:
        halflife *= 1.3
    elif dhs >= 0.55:
        pass  # no adjustment
    elif dhs >= 0.35:
        halflife *= 0.7
    else:
        halflife *= 0.4

    # 10. Novelty pressure adjustment
    if novelty_press > 0.7:
        halflife *= (1.0 - novelty_press * 0.3)

    # 11. DHS momentum adjustment
    halflife *= (1.0 + momentum * 0.5)

    # 12. Clamp halflife
    halflife = max(5.0, min(720.0, halflife))

    # 13. Timeframe scaling
    scale = TIMEFRAME_SCALE.get(timeframe, 1.0)
    halflife *= scale
    # Re-clamp after scaling
    halflife = max(5.0, min(720.0, halflife))

    # 14. Stability score via sigmoid-like curve
    stability_score = 1.0 - (1.0 / (1.0 + math.exp(halflife / 120.0 - 2.0)))
    stability_score = max(0.0, min(1.0, stability_score))

    # 15. Instability risk
    if stability_score >= 0.7:
        instability_risk = "low"
    elif stability_score >= 0.5:
        instability_risk = "moderate"
    elif stability_score >= 0.3:
        instability_risk = "elevated"
    else:
        instability_risk = "high"

    # 16. Urgency
    if stability_score >= 0.7 and regime != "unstable":
        urgency = "none"
    elif stability_score >= 0.5:
        urgency = "watch"
    elif stability_score >= 0.3 or (regime == "unstable" and halflife > 30):
        urgency = "prepare_exit"
    else:
        urgency = "exit_now"

    # 17. Exit window
    exit_window = None
    if urgency in ("prepare_exit", "exit_now"):
        exit_window = halflife * 0.3

    # 18. Time horizon
    time_horizon = _halflife_to_time_horizon(halflife)

    return RegimeStability(
        halflife_minutes=halflife,
        stability_score=stability_score,
        instability_risk=instability_risk,
        time_horizon=time_horizon,
        dhs_momentum=momentum,
        unity_trend=unity_label,
        novelty_pressure=novelty_press,
        persistence_factor=persist_factor,
        sequence_risk=seq_risk,
        urgency=urgency,
        exit_window_minutes=exit_window,
    )
