"""
ReNoUn Risk Management Backtest (v2)

Walk-forward test: use the finance engine's structural signals to modulate
position sizing and compare against naive buy-and-hold.

The engine does NOT predict direction. It tells you whether market structure
is orderly (safe to be sized up) or disordered (reduce exposure).

v2 additions:
  - Exposure smoothing (EMA blend) to prevent whipsaw on noisy transitions
  - Constellation persistence scoring — weight constellations by how long
    they've persisted, so brief flickers don't trigger full position changes
  - Fourth strategy: Momentum + ReNoUn v2 (smoothed + persistence)

Strategy:
  - Every N candles, run ReNoUn on the trailing window
  - Map DHS + constellation to a position-size multiplier (0.0 - 1.0)
  - Smooth the exposure via EMA with asymmetric alpha (fast down, slow up)
  - Weight constellation severity by persistence count
  - Apply that multiplier to a simple momentum signal (just SMA cross)
  - Compare equity curves: ReNoUn-managed vs unmanaged vs buy-and-hold
"""

import json
import os
import sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from renoun_finance import analyze_financial
from renoun_exposure import (
    ConstellationTracker, smooth_exposure, dhs_to_exposure, run_engine_on_window
)


# ---------------------------------------------------------------------------
# Simple momentum signal (SMA crossover — just a vehicle for testing risk)
# ---------------------------------------------------------------------------

def sma(prices, period):
    """Simple moving average."""
    out = np.full(len(prices), np.nan)
    for i in range(period - 1, len(prices)):
        out[i] = np.mean(prices[i - period + 1:i + 1])
    return out


def momentum_signal(closes, fast=20, slow=50):
    """
    Returns +1 (long) or -1 (short/flat) for each candle.
    Simple SMA crossover — deliberately basic. The point isn't
    to test the signal, it's to test whether ReNoUn exposure
    management improves risk-adjusted returns.
    """
    sma_fast = sma(closes, fast)
    sma_slow = sma(closes, slow)
    signals = np.zeros(len(closes))
    for i in range(len(closes)):
        if np.isnan(sma_fast[i]) or np.isnan(sma_slow[i]):
            signals[i] = 0  # no position until both SMAs available
        elif sma_fast[i] > sma_slow[i]:
            signals[i] = 1  # long
        else:
            signals[i] = -1  # short/flat
    return signals


# ---------------------------------------------------------------------------
# Walk-forward backtest
# ---------------------------------------------------------------------------

def run_backtest(klines, symbol="TEST", timeframe="1h",
                 renoun_window=100, rebalance_every=25,
                 sma_fast=20, sma_slow=50):
    """
    Walk-forward backtest comparing four strategies:
    1. Buy-and-hold
    2. Momentum (unmanaged) — full position based on SMA cross
    3. Momentum + ReNoUn v1 — raw exposure from DHS + constellation
    4. Momentum + ReNoUn v2 — v1 + exposure smoothing + constellation persistence
    """
    # Parse prices
    closes = np.array([float(k.get("close", k.get("c", 0))) for k in klines])
    n = len(closes)

    if n < renoun_window + sma_slow + 10:
        raise ValueError(f"Need at least {renoun_window + sma_slow + 10} candles, got {n}")

    # Compute returns
    returns = np.diff(closes) / closes[:-1]  # simple returns

    # Compute momentum signals
    signals = momentum_signal(closes, sma_fast, sma_slow)

    # Walk-forward ReNoUn exposure (v1 raw + v2 smoothed)
    exposure_v1 = np.ones(n)       # v1: raw exposure
    exposure_v2 = np.ones(n)       # v2: smoothed + persistence
    renoun_log = []
    tracker = ConstellationTracker()
    prev_smooth_exp = 1.0          # EMA state for v2

    start = renoun_window
    for i in range(start, n, rebalance_every):
        window_klines = klines[max(0, i - renoun_window):i]
        try:
            result = analyze_financial(window_klines, symbol=symbol, timeframe=timeframe)
            dhs = result["dialectical_health"]
            top_const = result["constellations"][0]["detected"] if result["constellations"] else "NONE"
            loop = result["loop_strength"]
            dd_stress = result.get("stress", {}).get("drawdown", 0.0)
            vol_stress = float(result.get("stress", {}).get("vol_expansion", 0.0))

            # --- v1: raw exposure ---
            exp_v1 = dhs_to_exposure(dhs, top_const, loop, dd_stress, vol_stress)

            # --- v2: persistence-weighted + smoothed ---
            persist = tracker.update(top_const)
            exp_v2_raw = dhs_to_exposure(dhs, top_const, loop, dd_stress, vol_stress,
                                          persistence_mult=persist["persistence_mult"])
            exp_v2 = smooth_exposure(exp_v2_raw, prev_smooth_exp)
            prev_smooth_exp = exp_v2

            # Apply exposures for the next rebalance_every candles
            end = min(i + rebalance_every, n)
            exposure_v1[i:end] = exp_v1
            exposure_v2[i:end] = exp_v2

            renoun_log.append({
                "candle": i,
                "dhs": round(dhs, 3),
                "constellation": top_const,
                "loop": round(loop, 3),
                "dd_stress": round(dd_stress, 3),
                "vol_stress": round(vol_stress, 3),
                "exposure_v1": round(exp_v1, 3),
                "exposure_v2": round(exp_v2, 3),
                "run_length": persist["run_length"],
                "churn": persist["churn"],
            })
        except Exception as e:
            # On error, maintain previous exposure
            renoun_log.append({"candle": i, "error": str(e)})

    # --- Compute equity curves ---
    # Strategy 1: Buy and hold
    bh_equity = [1.0]
    for r in returns:
        bh_equity.append(bh_equity[-1] * (1 + r))
    bh_equity = np.array(bh_equity)

    # Strategy 2: Momentum (unmanaged)
    mom_equity = [1.0]
    for i in range(len(returns)):
        pos = signals[i]
        mom_equity.append(mom_equity[-1] * (1 + pos * returns[i]))
    mom_equity = np.array(mom_equity)

    # Strategy 3: Momentum + ReNoUn v1 (raw)
    v1_equity = [1.0]
    for i in range(len(returns)):
        pos = signals[i] * exposure_v1[i]
        v1_equity.append(v1_equity[-1] * (1 + pos * returns[i]))
    v1_equity = np.array(v1_equity)

    # Strategy 4: Momentum + ReNoUn v2 (smoothed + persistence)
    v2_equity = [1.0]
    for i in range(len(returns)):
        pos = signals[i] * exposure_v2[i]
        v2_equity.append(v2_equity[-1] * (1 + pos * returns[i]))
    v2_equity = np.array(v2_equity)

    # Annualization factor by timeframe
    ppy = {"1m": 525600, "5m": 105120, "15m": 35040, "1h": 8760,
           "4h": 2190, "1d": 365}.get(timeframe, 8760)

    return {
        "n_candles": n,
        "n_rebalances": len(renoun_log),
        "buy_hold": _compute_stats(bh_equity, "Buy & Hold", ppy),
        "momentum": _compute_stats(mom_equity, "Momentum", ppy),
        "renoun_v1": _compute_stats(v1_equity, "ReNoUn v1 (raw)", ppy),
        "renoun_v2": _compute_stats(v2_equity, "ReNoUn v2 (smooth)", ppy),
        "renoun_log": renoun_log,
        "exposure_v1": exposure_v1.tolist(),
        "exposure_v2": exposure_v2.tolist(),
    }


def _compute_stats(equity, name, periods_per_year=8760):
    """Compute performance statistics for an equity curve."""
    total_return = (equity[-1] / equity[0]) - 1

    # Daily/candle returns
    rets = np.diff(equity) / equity[:-1]

    # Sharpe ratio (annualized)
    if np.std(rets) > 1e-15:
        sharpe = np.mean(rets) / np.std(rets) * np.sqrt(periods_per_year)
    else:
        sharpe = 0.0

    # Max drawdown
    peak = np.maximum.accumulate(equity)
    drawdown = (equity - peak) / peak
    max_dd = float(np.min(drawdown))

    # Calmar ratio (return / max drawdown)
    calmar = abs(total_return / max_dd) if abs(max_dd) > 1e-15 else 0.0

    # Win rate
    win_rate = np.sum(rets > 0) / len(rets) if len(rets) > 0 else 0

    # Volatility (annualized)
    vol = float(np.std(rets) * np.sqrt(periods_per_year))

    return {
        "name": name,
        "total_return": round(float(total_return) * 100, 2),
        "sharpe": round(float(sharpe), 3),
        "max_drawdown": round(float(max_dd) * 100, 2),
        "calmar": round(float(calmar), 3),
        "volatility": round(vol * 100, 2),
        "win_rate": round(float(win_rate) * 100, 1),
        "final_equity": round(float(equity[-1]), 4),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    testdata = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "finance", "testdata")

    datasets = [
        # 1-minute (micro)
        ("BTC 1m",  os.path.join(testdata, "BTCUSDT_1m_1000.json"),  "BTCUSDT", "1m"),
        ("ETH 1m",  os.path.join(testdata, "ETHUSDT_1m_1000.json"),  "ETHUSDT", "1m"),
        ("SOL 1m",  os.path.join(testdata, "SOLUSDT_1m_1000.json"),  "SOLUSDT", "1m"),
        # 15-minute
        ("BTC 15m", os.path.join(testdata, "BTCUSDT_15m_1000.json"), "BTCUSDT", "15m"),
        # Hourly
        ("BTC 1h",  os.path.join(testdata, "BTCUSDT_1h_1000.json"),  "BTCUSDT", "1h"),
        ("ETH 1h",  os.path.join(testdata, "ETHUSDT_1h_1000.json"),  "ETHUSDT", "1h"),
        ("SOL 1h",  os.path.join(testdata, "SOLUSDT_1h_1000.json"),  "SOLUSDT", "1h"),
        ("XRP 1h",  os.path.join(testdata, "XRPUSDT_1h_1000.json"),  "XRPUSDT", "1h"),
        ("DOGE 1h", os.path.join(testdata, "DOGEUSDT_1h_1000.json"), "DOGEUSDT", "1h"),
        # Multi-hour
        ("BTC 4h",  os.path.join(testdata, "BTCUSDT_4h_1000.json"),  "BTCUSDT", "4h"),
        ("BTC 1d",  os.path.join(testdata, "BTCUSDT_1d_1000.json"),  "BTCUSDT", "1d"),
    ]

    print("=" * 90)
    print("ReNoUn RISK MANAGEMENT BACKTEST (v1 vs v2)")
    print("=" * 90)
    print()
    print("v1: raw DHS → exposure mapping")
    print("v2: v1 + constellation persistence scoring + asymmetric EMA smoothing")
    print()

    all_results = {}

    for label, path, sym, tf in datasets:
        with open(path) as f:
            raw = json.load(f)
        klines = raw.get("klines", raw) if isinstance(raw, dict) else raw

        # Timeframe-specific parameters
        if tf == "1m":
            result = run_backtest(klines, symbol=sym, timeframe=tf,
                                  renoun_window=50, rebalance_every=5,
                                  sma_fast=3, sma_slow=10)
        elif tf == "15m":
            result = run_backtest(klines, symbol=sym, timeframe=tf,
                                  renoun_window=60, rebalance_every=10,
                                  sma_fast=8, sma_slow=25)
        elif tf == "1d":
            result = run_backtest(klines, symbol=sym, timeframe=tf,
                                  renoun_window=60, rebalance_every=10,
                                  sma_fast=10, sma_slow=30)
        elif tf == "4h":
            result = run_backtest(klines, symbol=sym, timeframe=tf,
                                  renoun_window=100, rebalance_every=15,
                                  sma_fast=15, sma_slow=40)
        else:
            result = run_backtest(klines, symbol=sym, timeframe=tf)

        all_results[label] = result

    # --- Cross-dataset summary ---
    strats = ["buy_hold", "momentum", "renoun_v1", "renoun_v2"]
    print(f"{'Dataset':<12} {'Strategy':<22} {'Return':>8} {'Sharpe':>8} {'Max DD':>8} {'Vol':>8} {'Calmar':>8}")
    print("-" * 90)

    for label, result in all_results.items():
        for strat_key in strats:
            s = result[strat_key]
            marker = " ◄" if strat_key == "renoun_v2" else ""
            print(f"  {label:<10} {s['name']:<22} {s['total_return']:>+7.2f}% {s['sharpe']:>7.3f} "
                  f"{s['max_drawdown']:>+7.2f}% {s['volatility']:>7.2f}% {s['calmar']:>7.3f}{marker}")
        print()

    # v1 vs v2 head-to-head
    print("=" * 90)
    print("v1 vs v2 HEAD-TO-HEAD (vs Momentum baseline)")
    print("=" * 90)
    print(f"{'Dataset':<12} {'v1_DD':>8} {'v2_DD':>8} {'v1_DDimp':>8} {'v2_DDimp':>8}  "
          f"{'v1_Sh':>8} {'v2_Sh':>8} {'v1_ShImp':>8} {'v2_ShImp':>8}  v2>v1?")
    print("-" * 100)

    v2_dd_wins = 0
    v2_sh_wins = 0
    total = len(all_results)

    for label, result in all_results.items():
        m = result["momentum"]
        v1 = result["renoun_v1"]
        v2 = result["renoun_v2"]
        v1_dd = m["max_drawdown"] - v1["max_drawdown"]
        v2_dd = m["max_drawdown"] - v2["max_drawdown"]
        v1_sh = v1["sharpe"] - m["sharpe"]
        v2_sh = v2["sharpe"] - m["sharpe"]

        v2_better_dd = abs(v2["max_drawdown"]) < abs(v1["max_drawdown"])
        v2_better_sh = v2["sharpe"] > v1["sharpe"]
        if v2_better_dd: v2_dd_wins += 1
        if v2_better_sh: v2_sh_wins += 1

        verdict = ""
        if v2_better_dd and v2_better_sh: verdict = "v2 ✓✓"
        elif v2_better_dd: verdict = "v2 DD"
        elif v2_better_sh: verdict = "v2 Sh"
        else: verdict = "v1"

        print(f"  {label:<10} {v1['max_drawdown']:>+7.2f}% {v2['max_drawdown']:>+7.2f}% {v1_dd:>+7.2f} {v2_dd:>+7.2f}  "
              f"{v1['sharpe']:>+7.3f} {v2['sharpe']:>+7.3f} {v1_sh:>+7.3f} {v2_sh:>+7.3f}  {verdict}")

    print(f"\nv2 better DD: {v2_dd_wins}/{total}    v2 better Sharpe: {v2_sh_wins}/{total}")
