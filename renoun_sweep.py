"""
Parameter sweep: find the exposure configuration that maximizes DD reduction
while minimizing Sharpe loss across all 31 datasets.

Tests different:
  - DHS threshold bands (how aggressive to de-risk)
  - Constellation penalty scales (how much constellations matter)
  - EMA alphas (how fast to de-risk / re-enter)
  - Minimum exposure floor (never go fully flat?)
"""

import json
import os
import sys
import numpy as np
from itertools import product

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from renoun_finance import analyze_financial
from renoun_exposure import ConstellationTracker, smooth_exposure


# ---------------------------------------------------------------------------
# Parameterized exposure function
# ---------------------------------------------------------------------------

def dhs_to_exposure_param(dhs, constellation, loop, dd_stress, vol_stress,
                          persistence_mult, config):
    """
    Parameterized version of dhs_to_exposure for sweep testing.

    config dict keys:
      - dhs_full: DHS threshold for full exposure (default 0.80)
      - dhs_high: DHS threshold for high exposure (default 0.65)
      - dhs_mid:  DHS threshold for mid exposure (default 0.50)
      - dhs_low:  DHS threshold for low exposure (default 0.35)
      - const_scale: multiplier for constellation penalties (default 1.0)
      - min_exposure: floor (default 0.0)
      - stress_scale: multiplier for stress penalties (default 1.0)
    """
    dhs_full = config.get("dhs_full", 0.80)
    dhs_high = config.get("dhs_high", 0.65)
    dhs_mid = config.get("dhs_mid", 0.50)
    dhs_low = config.get("dhs_low", 0.35)
    const_scale = config.get("const_scale", 1.0)
    min_exp = config.get("min_exposure", 0.0)
    stress_scale = config.get("stress_scale", 1.0)

    # Base exposure from DHS
    if dhs >= dhs_full:
        base = 1.0
    elif dhs >= dhs_high:
        base = 0.5 + (dhs - dhs_high) / (dhs_full - dhs_high) * 0.5
    elif dhs >= dhs_mid:
        base = 0.25 + (dhs - dhs_mid) / (dhs_high - dhs_mid) * 0.25
    elif dhs >= dhs_low:
        base = 0.1
    else:
        base = max(min_exp, 0.0)

    # Constellation mods (scaled)
    mods = {
        "CONVERGENCE": 0.0, "HIGH_SYMMETRY": -0.05, "DIP_AND_RECOVERY": 0.0,
        "SURFACE_VARIATION": -0.1, "CLOSED_LOOP": -0.1, "PATTERN_BREAK": -0.2,
        "REPEATED_DISRUPTION": -0.25, "SCATTERING": -0.4,
    }
    mod = mods.get(constellation, 0.0) * persistence_mult * const_scale

    if loop > 0.5:
        mod -= 0.05 * const_scale

    # Stress mods (scaled)
    if dd_stress > 0.5:
        mod -= 0.3 * stress_scale
    elif dd_stress > 0.3:
        mod -= 0.15 * stress_scale
    elif dd_stress > 0.1:
        mod -= 0.05 * stress_scale

    if vol_stress > 0.3:
        mod -= 0.15 * stress_scale
    elif vol_stress > 0.15:
        mod -= 0.05 * stress_scale

    return max(min_exp, min(1.0, base + mod))


# ---------------------------------------------------------------------------
# Run one config on one dataset
# ---------------------------------------------------------------------------

def score_config(klines, symbol, timeframe, config, window=50, rebalance=5):
    """
    Run engine with given config, return DD improvement and Sharpe improvement
    vs unmanaged baseline.
    """
    closes = np.array([float(k.get("close", k.get("c", 0))) for k in klines])
    n = len(closes)

    if n < window + rebalance + 10:
        return None

    returns = np.diff(closes) / closes[:-1]

    alpha_down = config.get("alpha_down", 0.6)
    alpha_up = config.get("alpha_up", 0.3)

    tracker = ConstellationTracker()
    prev_smooth = 1.0
    exposure = np.ones(n)

    for i in range(window, n - rebalance, rebalance):
        wk = klines[max(0, i - window):i]
        try:
            result = analyze_financial(wk, symbol=symbol, timeframe=timeframe)
            dhs = result["dialectical_health"]
            consts = result.get("constellations", [])
            top_const = consts[0]["detected"] if consts else "NONE"
            loop = result["loop_strength"]
            dd_stress = result.get("stress", {}).get("drawdown", 0.0)
            vol_stress = float(result.get("stress", {}).get("vol_expansion", 0.0))

            persist = tracker.update(top_const)
            raw_exp = dhs_to_exposure_param(
                dhs, top_const, loop, dd_stress, vol_stress,
                persist["persistence_mult"], config
            )
            smooth_exp = smooth_exposure(raw_exp, prev_smooth, alpha_down, alpha_up)
            prev_smooth = smooth_exp

            end = min(i + rebalance, n)
            exposure[i:end] = smooth_exp
        except Exception:
            pass

    # Unmanaged equity
    eq_u = [1.0]
    for r in returns:
        eq_u.append(eq_u[-1] * (1 + r))
    eq_u = np.array(eq_u)

    # Managed equity
    eq_m = [1.0]
    for i in range(len(returns)):
        eq_m.append(eq_m[-1] * (1 + exposure[i] * returns[i]))
    eq_m = np.array(eq_m)

    ppy = {"1m": 525600, "5m": 105120, "15m": 35040, "1h": 8760,
           "4h": 2190, "1d": 365}.get(timeframe, 8760)

    def _dd(eq):
        peak = np.maximum.accumulate(eq)
        return float(np.min((eq - peak) / peak))

    def _sharpe(eq):
        r = np.diff(eq) / eq[:-1]
        return float(np.mean(r) / np.std(r) * np.sqrt(ppy)) if np.std(r) > 1e-15 else 0.0

    dd_u = _dd(eq_u)
    dd_m = _dd(eq_m)
    sh_u = _sharpe(eq_u)
    sh_m = _sharpe(eq_m)

    return {
        "dd_improvement": abs(dd_u) - abs(dd_m),  # positive = managed better
        "sharpe_improvement": sh_m - sh_u,         # positive = managed better
        "avg_exposure": float(np.mean(exposure)),
        "dd_managed": dd_m,
        "dd_unmanaged": dd_u,
    }


# ---------------------------------------------------------------------------
# Sweep
# ---------------------------------------------------------------------------

def main():
    testdata = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "finance", "testdata")

    # Load all datasets
    datasets = []
    for fname in sorted(os.listdir(testdata)):
        if not fname.endswith(".json"):
            continue
        path = os.path.join(testdata, fname)
        parts = fname.replace(".json", "").split("_")
        sym = parts[0]
        # Find the timeframe part
        tf = "1h"
        for p in parts:
            if p in ("1m", "5m", "15m", "1h", "4h", "1d"):
                tf = p
                break

        with open(path) as f:
            raw = json.load(f)
        klines = raw.get("klines", raw) if isinstance(raw, dict) else raw
        datasets.append((fname, klines, sym, tf))

    print(f"Loaded {len(datasets)} datasets")

    # Define parameter grid
    configs = []

    # Baseline (current v2)
    configs.append(("v2_baseline", {
        "dhs_full": 0.80, "dhs_high": 0.65, "dhs_mid": 0.50, "dhs_low": 0.35,
        "const_scale": 1.0, "min_exposure": 0.0, "stress_scale": 1.0,
        "alpha_down": 0.6, "alpha_up": 0.3,
    }))

    # Less aggressive (wider neutral band)
    configs.append(("wider_neutral", {
        "dhs_full": 0.75, "dhs_high": 0.55, "dhs_mid": 0.40, "dhs_low": 0.30,
        "const_scale": 1.0, "min_exposure": 0.0, "stress_scale": 1.0,
        "alpha_down": 0.6, "alpha_up": 0.3,
    }))

    # Minimum floor (never fully flat)
    configs.append(("min_floor_10", {
        "dhs_full": 0.80, "dhs_high": 0.65, "dhs_mid": 0.50, "dhs_low": 0.35,
        "const_scale": 1.0, "min_exposure": 0.10, "stress_scale": 1.0,
        "alpha_down": 0.6, "alpha_up": 0.3,
    }))

    configs.append(("min_floor_20", {
        "dhs_full": 0.80, "dhs_high": 0.65, "dhs_mid": 0.50, "dhs_low": 0.35,
        "const_scale": 1.0, "min_exposure": 0.20, "stress_scale": 1.0,
        "alpha_down": 0.6, "alpha_up": 0.3,
    }))

    # Reduced constellation penalties
    configs.append(("half_const", {
        "dhs_full": 0.80, "dhs_high": 0.65, "dhs_mid": 0.50, "dhs_low": 0.35,
        "const_scale": 0.5, "min_exposure": 0.0, "stress_scale": 1.0,
        "alpha_down": 0.6, "alpha_up": 0.3,
    }))

    # Faster re-entry
    configs.append(("fast_reentry", {
        "dhs_full": 0.80, "dhs_high": 0.65, "dhs_mid": 0.50, "dhs_low": 0.35,
        "const_scale": 1.0, "min_exposure": 0.0, "stress_scale": 1.0,
        "alpha_down": 0.6, "alpha_up": 0.5,
    }))

    # Combined: wider + floor + faster re-entry
    configs.append(("combined_v3a", {
        "dhs_full": 0.75, "dhs_high": 0.55, "dhs_mid": 0.40, "dhs_low": 0.30,
        "const_scale": 0.7, "min_exposure": 0.10, "stress_scale": 1.0,
        "alpha_down": 0.6, "alpha_up": 0.4,
    }))

    # Aggressive combined
    configs.append(("combined_v3b", {
        "dhs_full": 0.70, "dhs_high": 0.50, "dhs_mid": 0.40, "dhs_low": 0.25,
        "const_scale": 0.5, "min_exposure": 0.15, "stress_scale": 0.8,
        "alpha_down": 0.5, "alpha_up": 0.45,
    }))

    # Only react to extreme signals
    configs.append(("extreme_only", {
        "dhs_full": 0.60, "dhs_high": 0.45, "dhs_mid": 0.35, "dhs_low": 0.25,
        "const_scale": 0.6, "min_exposure": 0.20, "stress_scale": 1.2,
        "alpha_down": 0.7, "alpha_up": 0.4,
    }))

    # Stress-focused (heavy stress response, light structure response)
    configs.append(("stress_focused", {
        "dhs_full": 0.70, "dhs_high": 0.50, "dhs_mid": 0.40, "dhs_low": 0.30,
        "const_scale": 0.3, "min_exposure": 0.15, "stress_scale": 1.5,
        "alpha_down": 0.7, "alpha_up": 0.35,
    }))

    print(f"Testing {len(configs)} configurations\n")

    # Run sweep
    results = {}
    for config_name, config in configs:
        dd_improvements = []
        sharpe_improvements = []
        dd_wins = 0
        sharpe_wins = 0
        avg_exposures = []

        for fname, klines, sym, tf in datasets:
            w = 50
            r = 5
            if tf == "1d":
                w, r = 60, 10
            elif tf == "4h":
                w, r = 100, 15
            elif tf == "15m":
                w, r = 60, 10

            res = score_config(klines, sym, tf, config, window=w, rebalance=r)
            if res is None:
                continue

            dd_improvements.append(res["dd_improvement"])
            sharpe_improvements.append(res["sharpe_improvement"])
            avg_exposures.append(res["avg_exposure"])
            if res["dd_improvement"] > 0:
                dd_wins += 1
            if res["sharpe_improvement"] > 0:
                sharpe_wins += 1

        n = len(dd_improvements)
        results[config_name] = {
            "n": n,
            "dd_wins": dd_wins,
            "sharpe_wins": sharpe_wins,
            "dd_win_rate": dd_wins / n if n > 0 else 0,
            "sharpe_win_rate": sharpe_wins / n if n > 0 else 0,
            "avg_dd_imp": np.mean(dd_improvements) if dd_improvements else 0,
            "avg_sharpe_imp": np.mean(sharpe_improvements) if sharpe_improvements else 0,
            "median_dd_imp": np.median(dd_improvements) if dd_improvements else 0,
            "median_sharpe_imp": np.median(sharpe_improvements) if sharpe_improvements else 0,
            "avg_exposure": np.mean(avg_exposures) if avg_exposures else 0,
        }

        dd_rate = f"{dd_wins}/{n}"
        sh_rate = f"{sharpe_wins}/{n}"
        print(f"  {config_name:<20}  DD: {dd_rate:>5}  Sharpe: {sh_rate:>5}  "
              f"avgDD: {results[config_name]['avg_dd_imp']*100:>+5.2f}pp  "
              f"avgSh: {results[config_name]['avg_sharpe_imp']:>+6.3f}  "
              f"avgExp: {results[config_name]['avg_exposure']:>.2f}")

    # Summary
    print(f"\n{'='*90}")
    print(f"SWEEP SUMMARY")
    print(f"{'='*90}")
    print(f"  {'Config':<20} {'DD Win%':>8} {'Sh Win%':>8} {'AvgDD':>8} {'AvgSh':>8} {'MedDD':>8} {'MedSh':>8} {'AvgExp':>7}")
    print(f"  {'-'*80}")

    # Sort by a composite score: DD win rate * 0.4 + Sharpe win rate * 0.4 + avg DD improvement * 0.2
    ranked = sorted(results.items(),
                    key=lambda x: (x[1]["dd_win_rate"] * 0.3 +
                                   x[1]["sharpe_win_rate"] * 0.4 +
                                   min(x[1]["avg_dd_imp"] * 10, 0.3)),
                    reverse=True)

    for name, r in ranked:
        print(f"  {name:<20} {r['dd_win_rate']*100:>7.0f}% {r['sharpe_win_rate']*100:>7.0f}% "
              f"{r['avg_dd_imp']*100:>+7.2f}pp {r['avg_sharpe_imp']:>+7.3f} "
              f"{r['median_dd_imp']*100:>+7.2f}pp {r['median_sharpe_imp']:>+7.3f} "
              f"{r['avg_exposure']:>6.2f}")


if __name__ == "__main__":
    main()
