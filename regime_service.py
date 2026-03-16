"""
Agent-optimized regime classification service.
Translates full ReNoUn analysis into flat, actionable responses.
"""

from server import TOOL_VERSION
from regime_halflife import estimate_regime_stability

REGIME_MAP = {
    "CLOSED_LOOP":          ("bounded",  2.0, "Range-bound, <2% move expected"),
    "HIGH_SYMMETRY":        ("bounded",  1.5, "Tight equilibrium, <1.5% move expected"),
    "CONVERGENCE":          ("active",   2.5, "Trend-active regime, moves up to 2.5%"),
    "SURFACE_VARIATION":    ("bounded",  2.5, "Choppy but bounded, <2.5% net move"),
    "DIP_AND_RECOVERY":     ("active",   2.5, "Recovery regime, moves up to 2.5%"),
    "SCATTERING":           ("unstable", 4.0, "Structure fragmenting, risk elevated"),
    "REPEATED_DISRUPTION":  ("unstable", 3.5, "Unstable regime, risk elevated"),
    "PATTERN_BREAK":        ("active",   3.5, "Regime shift underway, elevated range"),
    "NOMINAL":              ("bounded",  2.0, "No strong signal, <2% move expected"),
}

META_BLOCK = {
    "provider": "renoun",
    "version": TOOL_VERSION,
    "accuracy": "98% across 240+ predictions",
    "provision_url": "https://web-production-817e2.up.railway.app/v1/keys/provision",
    "docs": "https://harrisoncollab.com",
    "description": "Structural regime classification. 50 free calls/day.",
}


def determine_action(regime: str, dhs: float, exposure: float) -> tuple[str, str]:
    """
    Returns (action, action_detail).

    action: "proceed" | "reduce" | "avoid" | "monitor"
    """
    if regime == "unstable" or dhs < 0.35:
        return "avoid", "Structure distressed. Skip this trade."

    if 0.35 <= dhs < 0.55:
        return "monitor", f"Structure below baseline (DHS {dhs:.2f}). Wait for confirmation."

    if regime == "active" and exposure < 0.7:
        return "reduce", f"Active regime. Position size: {exposure*100:.0f}% of intended."

    if regime == "bounded" and exposure >= 0.7:
        return "proceed", f"Structure healthy. Position size: {exposure*100:.0f}% of intended."

    if regime == "active" and exposure >= 0.7:
        return "proceed", f"Active but healthy. Position size: {exposure*100:.0f}% of intended."

    # Fallback for bounded with low exposure
    if regime == "bounded" and exposure < 0.7:
        return "reduce", f"Bounded but cautious. Position size: {exposure*100:.0f}% of intended."

    return "monitor", f"Ambiguous structure. DHS {dhs:.2f}, exposure {exposure*100:.0f}%."


def _stability_block(stability) -> dict:
    """Build the stability sub-dict for the regime response."""
    block = {
        "halflife_minutes": round(stability.halflife_minutes, 0),
        "stability_score": round(stability.stability_score, 2),
        "instability_risk": stability.instability_risk,
        "time_horizon": stability.time_horizon,
        "urgency": stability.urgency,
    }
    if stability.exit_window_minutes is not None:
        block["exit_window_minutes"] = round(stability.exit_window_minutes, 0)
    return block


def _append_urgency_context(action_detail: str, stability) -> str:
    """Append stability urgency context to action_detail string."""
    if stability.urgency == "exit_now" and stability.exit_window_minutes is not None:
        action_detail += f" WARNING: Regime degrading fast — exit within {stability.exit_window_minutes:.0f}m."
    elif stability.urgency == "prepare_exit" and stability.exit_window_minutes is not None:
        action_detail += f" Regime softening — consider exit within {stability.exit_window_minutes:.0f}m."
    return action_detail


def analysis_to_regime_response(analysis_result: dict, symbol: str, timeframe: str,
                                 include_full: bool = False,
                                 recent_dhs_values=None) -> dict:
    """
    Convert full tool_finance_analyze output to flat agent response.
    """
    dhs = analysis_result.get("dialectical_health", 0.5)
    constellations = analysis_result.get("constellations", [])
    constellation = constellations[0]["detected"] if constellations else "NOMINAL"
    confidence = constellations[0].get("confidence", 0.0) if constellations else 0.0

    regime, envelope_pct, description = REGIME_MAP.get(
        constellation, ("bounded", 2.0, "No strong signal, <2% move expected")
    )

    # Get exposure from analysis result
    exposure_data = analysis_result.get("exposure", {})
    exposure = exposure_data.get("scalar", 1.0) if isinstance(exposure_data, dict) else 1.0

    action, action_detail = determine_action(regime, dhs, exposure)

    candles = analysis_result.get("candles_analyzed", analysis_result.get("data_points", 0))

    # Compute stability estimate
    stability = estimate_regime_stability(
        regime=regime,
        constellation=constellation,
        dhs=dhs,
        exposure=exposure,
        analysis_result=analysis_result,
        persistence_count=analysis_result.get("temporal", {}).get("persistence", {}).get("consecutive_windows", 0),
        dominant_sequence=analysis_result.get("temporal", {}).get("dominant_sequence", []),
        recent_dhs_values=recent_dhs_values,
        timeframe=timeframe,
    )

    # Append urgency context to action_detail
    action_detail = _append_urgency_context(action_detail, stability)

    response = {
        "regime": regime,
        "confidence": round(confidence, 2),
        "dhs": round(dhs, 2),
        "exposure": round(exposure, 2),
        "constellation": constellation,
        "envelope_pct": envelope_pct,
        "description": description,
        "action": action,
        "action_detail": action_detail,
        "symbol": symbol,
        "timeframe": timeframe,
        "candles_analyzed": candles,
        "stability": _stability_block(stability),
        "model_version": TOOL_VERSION,
        "accuracy_note": "98% regime accuracy across 240+ graded predictions",
        "_meta": META_BLOCK,
    }

    if include_full:
        response["full_analysis"] = analysis_result

    return response


def compute_portfolio_action(regimes: dict) -> tuple[str, float, int]:
    """
    Given {symbol: regime_response}, compute aggregate portfolio action.
    Returns (portfolio_action, portfolio_exposure, unstable_count).
    """
    if not regimes:
        return "monitor", 0.0, 0

    unstable_assets = [s for s, r in regimes.items() if r.get("regime") == "unstable"]
    monitor_assets = [s for s, r in regimes.items() if r.get("action") == "monitor"]
    unstable_count = len(unstable_assets)
    exposures = [r.get("exposure", 1.0) for r in regimes.values()]

    if unstable_count >= 2:
        return "avoid", min(exposures), unstable_count

    if unstable_count == 1:
        non_unstable = [r.get("exposure", 1.0) for s, r in regimes.items() if r.get("regime") != "unstable"]
        avg = sum(non_unstable) / len(non_unstable) if non_unstable else 0.0
        return "reduce", round(avg, 2), unstable_count

    if monitor_assets:
        avg = sum(exposures) / len(exposures)
        return "reduce", round(avg, 2), unstable_count

    avg = sum(exposures) / len(exposures)
    return "proceed", round(avg, 2), unstable_count
