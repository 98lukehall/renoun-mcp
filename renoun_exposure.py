"""
ReNoUn Exposure Logic (shared module)

Constellation persistence tracking, exposure smoothing, and DHS-to-exposure
mapping used by backtest, stream, and score modules.

This is the single source of truth — don't duplicate this logic.
"""


class ConstellationTracker:
    """
    Tracks how many consecutive windows a constellation has persisted.
    Brief flickers (1 window) get reduced weight; sustained patterns
    (3+ windows) get full weight.
    """
    def __init__(self):
        self.history = []
        self.current = None
        self.run_length = 0
        self.crash_regime = False
        self.crash_cooldown = 0  # windows remaining in crash regime

    def update(self, constellation: str):
        """Record new constellation, return persistence multiplier."""
        self.history.append(constellation)

        if constellation == self.current:
            self.run_length += 1
        else:
            self.current = constellation
            self.run_length = 1

        # --- Crash regime tracking ---
        # Enter crash regime when PATTERN_BREAK or SCATTERING is detected
        if constellation in ("PATTERN_BREAK", "SCATTERING"):
            self.crash_regime = True
            self.crash_cooldown = 5  # suppress recovery for 5 windows

        # Determine effective constellation for exposure purposes:
        # During crash regime, override DIP_AND_RECOVERY to prevent
        # premature exposure ramp-up during multi-wave crashes.
        effective_constellation = constellation
        if self.crash_regime and constellation == "DIP_AND_RECOVERY":
            effective_constellation = "PATTERN_BREAK"

        # Decrement cooldown (after using crash_regime flag above)
        if self.crash_cooldown > 0:
            self.crash_cooldown -= 1
        if self.crash_cooldown <= 0:
            self.crash_regime = False

        # Persistence multiplier:
        #   1 window  -> 0.5 (half weight -- might be noise)
        #   2 windows -> 0.8
        #   3+ windows -> 1.0 (confirmed pattern)
        if self.run_length >= 3:
            persistence_mult = 1.0
        elif self.run_length == 2:
            persistence_mult = 0.8
        else:
            persistence_mult = 0.5

        # Churn: unique constellations in last 5 readings
        recent = self.history[-5:]
        churn = len(set(recent)) / max(len(recent), 1)

        return {
            "constellation": constellation,
            "effective_constellation": effective_constellation,
            "run_length": self.run_length,
            "persistence_mult": persistence_mult,
            "churn": round(churn, 2),
            "crash_regime": self.crash_regime,
        }


def smooth_exposure(raw_exp: float, prev_smooth: float,
                    alpha_down: float = 0.6, alpha_up: float = 0.3) -> float:
    """
    EMA-blend new exposure with previous smoothed value.

    Asymmetric alphas:
    - alpha_down (0.6): react quickly to risk-off signals (fast de-risk)
    - alpha_up (0.3): ramp back up slowly (avoid whipsaw re-entry)
    """
    if raw_exp < prev_smooth:
        alpha = alpha_down  # fast reduction
    else:
        alpha = alpha_up    # slow recovery
    return alpha * raw_exp + (1 - alpha) * prev_smooth


def dhs_to_exposure(dhs: float, constellation: str, loop_strength: float,
                    dd_stress: float = 0.0, vol_stress: float = 0.0,
                    persistence_mult: float = 1.0,
                    crash_regime: bool = False) -> float:
    """
    Map structural health to position-size multiplier [0.0 - 1.0].

    Core risk management logic:
    - High DHS + orderly constellation -> full exposure
    - Low DHS or dangerous constellation -> reduce/cut exposure
    - Stress signals provide direct risk cuts
    - persistence_mult scales constellation mods (brief = reduced impact)
    """
    # Base exposure from DHS (tiered)
    if dhs >= 0.80:
        base = 1.0
    elif dhs >= 0.65:
        base = 0.5 + (dhs - 0.65) / 0.15 * 0.5   # 0.5 -> 1.0
    elif dhs >= 0.50:
        base = 0.25 + (dhs - 0.50) / 0.15 * 0.25  # 0.25 -> 0.5
    elif dhs >= 0.35:
        base = 0.1
    else:
        base = 0.2  # distressed = minimal, but never fully flat

    # Constellation adjustments (scaled by persistence)
    constellation_mods = {
        "CONVERGENCE": 0.0,
        "HIGH_SYMMETRY": -0.05,
        "DIP_AND_RECOVERY": 0.0,
        "SURFACE_VARIATION": -0.1,
        "CLOSED_LOOP": -0.1,
        "PATTERN_BREAK": -0.2,
        "REPEATED_DISRUPTION": -0.25,
        "SCATTERING": -0.4,
    }
    mod = constellation_mods.get(constellation, 0.0) * persistence_mult

    # High loop strength -> slight reduction (stuck market, breakout risk)
    if loop_strength > 0.5:
        mod -= 0.05

    # Direct stress signals
    if dd_stress > 0.5:
        mod -= 0.3   # heavy cut during active crash
    elif dd_stress > 0.3:
        mod -= 0.15  # moderate cut during drawdown
    elif dd_stress > 0.1:
        mod -= 0.05  # slight caution

    # Vol expansion stress
    if vol_stress > 0.3:
        mod -= 0.15
    elif vol_stress > 0.15:
        mod -= 0.05

    exposure = max(0.20, min(1.0, base + mod))  # floor at 0.20 — never fully flat

    # Crash regime penalty: cap exposure during multi-wave crash suppression
    if crash_regime:
        exposure = exposure * 0.5

    return max(0.20, exposure)


def run_engine_on_window(klines, analyze_fn, symbol, timeframe,
                         tracker, prev_smooth):
    """
    Run ReNoUn on a window of klines and return exposure decision.

    Returns (decision_dict, new_prev_smooth) or (None, prev_smooth) on error.
    """
    try:
        result = analyze_fn(klines, symbol=symbol, timeframe=timeframe)
        dhs = result["dialectical_health"]
        consts = result.get("constellations", [])
        top_const = consts[0]["detected"] if consts else "NONE"
        loop = result["loop_strength"]
        dd_stress = result.get("stress", {}).get("drawdown", 0.0)
        vol_stress = float(result.get("stress", {}).get("vol_expansion", 0.0))

        persist = tracker.update(top_const)
        eff_const = persist.get("effective_constellation", top_const)
        crash_reg = persist.get("crash_regime", False)
        raw_exp = dhs_to_exposure(dhs, eff_const, loop, dd_stress, vol_stress,
                                   persistence_mult=persist["persistence_mult"],
                                   crash_regime=crash_reg)
        smooth_exp = smooth_exposure(raw_exp, prev_smooth)

        decision = {
            "dhs": round(dhs, 3),
            "constellation": top_const,
            "effective_constellation": eff_const,
            "loop": round(loop, 3),
            "dd_stress": round(dd_stress, 4),
            "vol_stress": round(vol_stress, 4),
            "exposure_raw": round(raw_exp, 3),
            "exposure_smooth": round(smooth_exp, 3),
            "run_length": persist["run_length"],
            "churn": persist["churn"],
            "crash_regime": crash_reg,
        }
        return decision, smooth_exp
    except Exception:
        return None, prev_smooth
