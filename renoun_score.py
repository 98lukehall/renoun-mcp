"""
ReNoUn Decision Scorer (v2)

Validates the engine's exposure decisions against actual outcomes.
Three complementary scoring methods:

  1. Per-decision scoring (hit rate, direction alignment)
  2. Cumulative equity scoring (DD reduction, Sharpe improvement)
  3. Tail protection scoring (insurance value — asymmetric risk metrics)

The key insight: a risk overlay that costs 0.01% per calm window but saves
3% during crashes shows NEGATIVE per-decision correlation while being
extremely valuable. The equity and tail metrics capture this correctly.

Usage:
    python renoun_score.py --simulate BTCUSDT 1m     # simulate on fresh data
    python renoun_score.py --file path/to/data.json   # score on local data
    python renoun_score.py                            # score all local datasets
"""

import argparse
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
# Per-decision scoring (original method)
# ---------------------------------------------------------------------------

def score_decisions(decisions, closes, rebalance_every, lookahead_candles=None):
    """
    Grade each exposure decision against the forward return.
    Returns scored decisions and aggregate metrics.
    """
    if lookahead_candles is None:
        lookahead_candles = rebalance_every

    scored = []
    for d in decisions:
        candle_idx = d["candle"]
        if candle_idx + lookahead_candles >= len(closes):
            continue

        entry_price = closes[candle_idx]
        exit_price = closes[candle_idx + lookahead_candles]
        fwd_return = (exit_price - entry_price) / entry_price

        fwd_slice = closes[candle_idx:candle_idx + lookahead_candles + 1]
        fwd_peak = np.maximum.accumulate(fwd_slice)
        fwd_dd = np.min((fwd_slice - fwd_peak) / (fwd_peak + 1e-15))

        fwd_rets = np.diff(fwd_slice) / fwd_slice[:-1]
        fwd_vol = float(np.std(fwd_rets)) if len(fwd_rets) > 1 else 0.0

        exp = d.get("exposure_smooth", d.get("exposure_v2", d.get("exposure", 0.5)))

        if exp >= 0.5 and fwd_return > 0:
            direction = "correct"
        elif exp < 0.5 and fwd_return <= 0:
            direction = "correct"
        else:
            direction = "incorrect"

        scored.append({
            **d,
            "fwd_return": round(float(fwd_return) * 100, 4),
            "fwd_max_dd": round(float(fwd_dd) * 100, 4),
            "fwd_vol": round(float(fwd_vol) * 100, 4),
            "direction": direction,
        })

    if not scored:
        return scored, {}

    exposures = np.array([s.get("exposure_smooth", s.get("exposure_v2", s.get("exposure", 0.5))) for s in scored])
    fwd_returns = np.array([s["fwd_return"] for s in scored])
    directions = [s["direction"] for s in scored]

    if np.std(exposures) > 1e-10 and np.std(fwd_returns) > 1e-10:
        corr = float(np.corrcoef(exposures, fwd_returns)[0, 1])
    else:
        corr = 0.0

    correct = sum(1 for d in directions if d == "correct")
    hit_rate = correct / len(directions)

    low_exp_mask = exposures < 0.5
    high_exp_mask = exposures >= 0.5
    low_exp_returns = fwd_returns[low_exp_mask] if low_exp_mask.any() else np.array([0.0])
    high_exp_returns = fwd_returns[high_exp_mask] if high_exp_mask.any() else np.array([0.0])

    metrics = {
        "n_decisions": len(scored),
        "hit_rate": round(hit_rate, 3),
        "exp_fwd_return_corr": round(corr, 3),
        "avg_exposure": round(float(np.mean(exposures)), 3),
        "low_exp_count": int(low_exp_mask.sum()),
        "high_exp_count": int(high_exp_mask.sum()),
        "low_exp_avg_return": round(float(np.mean(low_exp_returns)), 4),
        "high_exp_avg_return": round(float(np.mean(high_exp_returns)), 4),
    }

    return scored, metrics


# ---------------------------------------------------------------------------
# Cumulative equity scoring (bridges the gap to backtest results)
# ---------------------------------------------------------------------------

def score_equity(decisions, closes, rebalance_every, timeframe="1m"):
    """
    Build equity curves for managed vs unmanaged exposure.
    This directly answers: does the engine reduce DD and improve Sharpe?

    Compares:
    - Unmanaged: fully exposed to all price moves (exposure = 1.0)
    - Managed: exposure modulated by engine decisions

    Returns equity curves and performance stats.
    """
    n = len(closes)
    returns = np.diff(closes) / closes[:-1]

    # Build per-candle exposure from decisions
    exposure = np.ones(n)
    for d in decisions:
        candle_idx = d["candle"]
        exp = d.get("exposure_smooth", d.get("exposure_v2", d.get("exposure", 1.0)))
        end = min(candle_idx + rebalance_every, n)
        exposure[candle_idx:end] = exp

    # Equity: unmanaged (full exposure)
    eq_unmanaged = [1.0]
    for r in returns:
        eq_unmanaged.append(eq_unmanaged[-1] * (1 + r))
    eq_unmanaged = np.array(eq_unmanaged)

    # Equity: managed
    eq_managed = [1.0]
    for i in range(len(returns)):
        eq_managed.append(eq_managed[-1] * (1 + exposure[i] * returns[i]))
    eq_managed = np.array(eq_managed)

    ppy = {"1m": 525600, "5m": 105120, "15m": 35040, "1h": 8760,
           "4h": 2190, "1d": 365}.get(timeframe, 8760)

    def _stats(eq, label):
        total_return = (eq[-1] / eq[0]) - 1
        rets = np.diff(eq) / eq[:-1]
        sharpe = float(np.mean(rets) / np.std(rets) * np.sqrt(ppy)) if np.std(rets) > 1e-15 else 0.0
        peak = np.maximum.accumulate(eq)
        dd = (eq - peak) / peak
        max_dd = float(np.min(dd))
        vol = float(np.std(rets) * np.sqrt(ppy))
        return {
            "name": label,
            "total_return": round(float(total_return) * 100, 2),
            "sharpe": round(sharpe, 3),
            "max_drawdown": round(max_dd * 100, 2),
            "volatility": round(vol * 100, 2),
            "final_equity": round(float(eq[-1]), 4),
        }

    stats_unmanaged = _stats(eq_unmanaged, "Unmanaged")
    stats_managed = _stats(eq_managed, "Managed")

    dd_improvement = abs(stats_unmanaged["max_drawdown"]) - abs(stats_managed["max_drawdown"])
    sharpe_improvement = stats_managed["sharpe"] - stats_unmanaged["sharpe"]

    return {
        "unmanaged": stats_unmanaged,
        "managed": stats_managed,
        "dd_improvement_pp": round(dd_improvement, 2),
        "sharpe_improvement": round(sharpe_improvement, 3),
        "dd_improved": dd_improvement > 0,
        "sharpe_improved": sharpe_improvement > 0,
    }


# ---------------------------------------------------------------------------
# Tail protection scoring (asymmetric risk metrics)
# ---------------------------------------------------------------------------

def score_tail_protection(decisions, closes, rebalance_every, tail_pct=0.1):
    """
    The key question for a risk overlay: when the worst outcomes happened,
    was exposure already reduced?

    Measures:
    - Tail exposure: avg exposure during the worst tail_pct of forward returns
    - Calm exposure: avg exposure during the best tail_pct of forward returns
    - Insurance ratio: (calm_exp - tail_exp) / calm_exp
      > 0 = engine reduces exposure before bad outcomes (working as intended)
      = 0 = engine doesn't differentiate
      < 0 = engine increases exposure before bad outcomes (anti-correlated)
    - Tail cost: how much return was foregone by being cautious during non-tail
    - Tail savings: how much loss was avoided during actual tail events
    """
    scored = []
    for d in decisions:
        candle_idx = d["candle"]
        if candle_idx + rebalance_every >= len(closes):
            continue
        entry = closes[candle_idx]
        exit_ = closes[candle_idx + rebalance_every]
        fwd_ret = (exit_ - entry) / entry
        exp = d.get("exposure_smooth", d.get("exposure_v2", d.get("exposure", 1.0)))
        scored.append({"exposure": exp, "fwd_return": fwd_ret})

    if len(scored) < 20:
        return {"error": "Not enough decisions for tail analysis"}

    exposures = np.array([s["exposure"] for s in scored])
    fwd_returns = np.array([s["fwd_return"] for s in scored])

    n_tail = max(1, int(len(scored) * tail_pct))

    # Sort by forward return to find tails
    sorted_idx = np.argsort(fwd_returns)
    worst_idx = sorted_idx[:n_tail]     # worst outcomes
    best_idx = sorted_idx[-n_tail:]     # best outcomes

    tail_exp = float(np.mean(exposures[worst_idx]))
    calm_exp = float(np.mean(exposures[best_idx]))
    mid_exp = float(np.mean(exposures[sorted_idx[n_tail:-n_tail]]))

    # Insurance ratio: how much less exposure during worst vs best
    if calm_exp > 1e-6:
        insurance_ratio = (calm_exp - tail_exp) / calm_exp
    else:
        insurance_ratio = 0.0

    # Savings during tail: what was the avg loss, and how much was avoided?
    tail_returns = fwd_returns[worst_idx]
    avg_tail_loss = float(np.mean(tail_returns))
    avg_tail_exposure = float(np.mean(exposures[worst_idx]))
    # Loss if fully exposed vs loss with managed exposure
    savings_per_tail = avg_tail_loss * (1.0 - avg_tail_exposure)

    # Cost during calm: return foregone by not being fully exposed
    calm_returns = fwd_returns[best_idx]
    avg_calm_gain = float(np.mean(calm_returns))
    avg_calm_exposure = float(np.mean(exposures[best_idx]))
    cost_per_calm = avg_calm_gain * (1.0 - avg_calm_exposure)

    # Value ratio: savings / cost (> 1.0 = worth the insurance)
    value_ratio = abs(savings_per_tail / cost_per_calm) if abs(cost_per_calm) > 1e-10 else float('inf')

    return {
        "n_decisions": len(scored),
        "n_tail": n_tail,
        "tail_pct": tail_pct,
        "tail_avg_exposure": round(tail_exp, 3),
        "calm_avg_exposure": round(calm_exp, 3),
        "mid_avg_exposure": round(mid_exp, 3),
        "insurance_ratio": round(insurance_ratio, 3),
        "avg_tail_loss_pct": round(avg_tail_loss * 100, 4),
        "avg_calm_gain_pct": round(avg_calm_gain * 100, 4),
        "tail_savings_pct": round(savings_per_tail * 100, 4),
        "calm_cost_pct": round(cost_per_calm * 100, 4),
        "value_ratio": round(value_ratio, 2),
    }


# ---------------------------------------------------------------------------
# Simulate-and-score on historical data
# ---------------------------------------------------------------------------

def simulate_and_score(klines, symbol, timeframe, window=50, rebalance=5):
    """
    Run the engine on historical data with a rolling window, then score.
    Returns decisions, per-decision metrics, equity metrics, and tail metrics.
    """
    closes = np.array([float(k.get("close", k.get("c", 0))) for k in klines])
    n = len(closes)

    if n < window + rebalance + 10:
        raise ValueError(f"Need at least {window + rebalance + 10} candles, got {n}")

    tracker = ConstellationTracker()
    prev_smooth = 1.0
    decisions = []

    for i in range(window, n - rebalance, rebalance):
        wk = klines[max(0, i - window):i]
        decision, prev_smooth = run_engine_on_window(
            wk, analyze_financial, symbol, timeframe, tracker, prev_smooth
        )
        if decision is not None:
            decision["candle"] = i
            decision["price"] = float(closes[i])
            decisions.append(decision)

    scored, per_decision = score_decisions(decisions, closes, rebalance)
    equity = score_equity(decisions, closes, rebalance, timeframe)
    tail = score_tail_protection(decisions, closes, rebalance)

    return {
        "scored": scored,
        "per_decision": per_decision,
        "equity": equity,
        "tail": tail,
    }


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

def print_results(results, symbol, timeframe, show_individual=True):
    per_dec = results["per_decision"]
    eq = results["equity"]
    tail = results["tail"]

    print(f"\n{'='*85}")
    print(f"  DECISION SCORECARD -- {symbol} {timeframe}")
    print(f"{'='*85}")

    # --- Equity scoring (the most important section) ---
    print(f"\n  EQUITY IMPACT (cumulative compounding):")
    u = eq["unmanaged"]
    m = eq["managed"]
    print(f"    {'':>18} {'Return':>9} {'Sharpe':>8} {'Max DD':>9} {'Vol':>8}")
    print(f"    {'Unmanaged':>18} {u['total_return']:>+8.2f}% {u['sharpe']:>7.3f} {u['max_drawdown']:>+8.2f}% {u['volatility']:>7.2f}%")
    print(f"    {'Managed':>18} {m['total_return']:>+8.2f}% {m['sharpe']:>7.3f} {m['max_drawdown']:>+8.2f}% {m['volatility']:>7.2f}%")
    dd_mark = "+" if eq["dd_improved"] else "x"
    sh_mark = "+" if eq["sharpe_improved"] else "x"
    print(f"    [{dd_mark}] DD improvement:    {eq['dd_improvement_pp']:>+.2f} pp")
    print(f"    [{sh_mark}] Sharpe improvement: {eq['sharpe_improvement']:>+.3f}")

    # --- Tail protection (asymmetric value) ---
    if "error" not in tail:
        print(f"\n  TAIL PROTECTION (worst {tail['tail_pct']*100:.0f}% of outcomes):")
        print(f"    Exposure during worst {tail['n_tail']} windows:  {tail['tail_avg_exposure']:.3f}")
        print(f"    Exposure during best {tail['n_tail']} windows:   {tail['calm_avg_exposure']:.3f}")
        print(f"    Exposure during middle windows:      {tail['mid_avg_exposure']:.3f}")
        ins = tail['insurance_ratio']
        if ins > 0.05:
            print(f"    Insurance ratio: {ins:+.3f}  (engine reduces exposure before bad outcomes)")
        elif ins < -0.05:
            print(f"    Insurance ratio: {ins:+.3f}  (engine INCREASES exposure before bad outcomes)")
        else:
            print(f"    Insurance ratio: {ins:+.3f}  (no clear differentiation)")
        print(f"    Avg tail loss: {tail['avg_tail_loss_pct']:+.4f}%  |  Savings from reduced exposure: {tail['tail_savings_pct']:+.4f}%")
        print(f"    Avg calm gain: {tail['avg_calm_gain_pct']:+.4f}%  |  Cost of caution:               {tail['calm_cost_pct']:+.4f}%")
        vr = tail['value_ratio']
        if vr > 1.5:
            print(f"    Value ratio: {vr:.2f}x  (tail savings >> calm costs -- insurance is worth it)")
        elif vr > 1.0:
            print(f"    Value ratio: {vr:.2f}x  (tail savings > calm costs -- marginally worth it)")
        elif vr > 0:
            print(f"    Value ratio: {vr:.2f}x  (calm costs > tail savings -- insurance costs more than it saves)")
        else:
            print(f"    Value ratio: {vr:.2f}x")

    # --- Per-decision metrics (context, not primary) ---
    if per_dec:
        print(f"\n  PER-DECISION METRICS (individual windows -- use as context, not primary):")
        print(f"    Decisions: {per_dec['n_decisions']}  |  Hit rate: {per_dec['hit_rate']*100:.1f}%  |  "
              f"Exp-return corr: {per_dec['exp_fwd_return_corr']:+.3f}")
        print(f"    Avg exposure: {per_dec['avg_exposure']:.2f}  |  "
              f"Low-exp: {per_dec['low_exp_count']}  |  High-exp: {per_dec['high_exp_count']}")

    # --- Individual decisions ---
    scored = results["scored"]
    if show_individual and scored:
        print(f"\n  {'#':>4} {'Price':>10} {'DHS':>6} {'Constellation':<22} {'Exp':>5} {'FwdRet':>8} {'FwdDD':>8} {'Dir':>4}")
        print(f"  {'-'*78}")
        for s in scored:
            mark = "+" if s["direction"] == "correct" else "x"
            print(f"  {s['candle']:>4} {s['price']:>10.2f} {s['dhs']:>5.3f} {s['constellation']:<22} "
                  f"{s['exposure_smooth']:>5.2f} {s['fwd_return']:>+7.3f}% {s['fwd_max_dd']:>+7.3f}% {mark:>3}")


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------

def verdict(results):
    """Summarize: is the engine adding value?"""
    eq = results["equity"]
    tail = results.get("tail", {})

    dd_ok = eq["dd_improved"]
    sharpe_ok = eq["sharpe_improved"]
    tail_ok = tail.get("insurance_ratio", 0) > 0.05

    score = sum([dd_ok, sharpe_ok, tail_ok])
    if score == 3:
        return "STRONG -- DD reduction + Sharpe improvement + tail protection"
    elif score == 2:
        return "POSITIVE -- engine adds value on 2/3 dimensions"
    elif score == 1:
        return "MARGINAL -- engine adds value on 1/3 dimensions"
    else:
        return "NEGATIVE -- engine not adding value on this data"


# ---------------------------------------------------------------------------
# Fetch live data
# ---------------------------------------------------------------------------

def fetch_klines(symbol, interval, limit):
    import urllib.request
    url = f"https://api.binance.us/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    req = urllib.request.Request(url, headers={"User-Agent": "ReNoUn-Score/2.0"})
    resp = urllib.request.urlopen(req, timeout=15)
    raw = json.loads(resp.read())
    klines = []
    for k in raw:
        klines.append({
            "openTime": k[0], "open": float(k[1]), "high": float(k[2]),
            "low": float(k[3]), "close": float(k[4]), "volume": float(k[5]),
            "closeTime": k[6], "quoteVolume": float(k[7]), "trades": k[8],
            "takerBuyVolume": float(k[9]), "takerBuyQuoteVolume": float(k[10])
        })
    return klines


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="ReNoUn Decision Scorer v2")
    parser.add_argument("--simulate", nargs=2, metavar=("SYMBOL", "TIMEFRAME"),
                        help="Simulate on fresh live data")
    parser.add_argument("--file", type=str, help="Score on a local JSON data file")
    parser.add_argument("--window", type=int, default=50, help="Analysis window (default: 50)")
    parser.add_argument("--rebalance", type=int, default=5, help="Rebalance interval (default: 5)")
    parser.add_argument("--candles", type=int, default=500, help="Candles to fetch (default: 500)")
    parser.add_argument("--no-details", action="store_true", help="Hide individual decisions")
    args = parser.parse_args()

    def run_on_klines(klines, symbol, tf, label=""):
        closes = [k.get("close", k.get("c", 0)) for k in klines]
        print(f"\n  {label}{symbol} {tf}: {len(klines)} candles, "
              f"range {min(closes):.2f} - {max(closes):.2f}")
        results = simulate_and_score(klines, symbol, tf,
                                      window=args.window, rebalance=args.rebalance)
        print_results(results, symbol, tf, show_individual=not args.no_details)
        v = verdict(results)
        print(f"\n  VERDICT: {v}\n")
        return results

    if args.simulate:
        symbol, tf = args.simulate
        symbol = symbol.upper()
        print(f"Fetching {args.candles} {tf} candles for {symbol}...")
        klines = fetch_klines(symbol, tf, args.candles)
        run_on_klines(klines, symbol, tf)

    elif args.file:
        with open(args.file) as f:
            raw = json.load(f)
        klines = raw.get("klines", raw) if isinstance(raw, dict) else raw
        # Try to infer symbol/timeframe from filename
        basename = os.path.basename(args.file).replace(".json", "")
        parts = basename.split("_")
        symbol = parts[0] if parts else "UNKNOWN"
        tf = parts[1] if len(parts) > 1 else "1h"
        run_on_klines(klines, symbol, tf)

    else:
        # Default: run on all local test datasets
        testdata = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "finance", "testdata")
        if not os.path.isdir(testdata):
            print(f"No testdata directory at {testdata}")
            print("Use --simulate BTCUSDT 1m or --file path/to/data.json")
            return

        datasets = []
        for fname in sorted(os.listdir(testdata)):
            if not fname.endswith(".json"):
                continue
            parts = fname.replace(".json", "").split("_")
            if len(parts) >= 2:
                sym = parts[0]
                tf = parts[1]
                datasets.append((os.path.join(testdata, fname), sym, tf))

        if not datasets:
            print("No JSON files found in testdata/")
            return

        print(f"Found {len(datasets)} datasets in {testdata}")

        # Summary table
        summary = []
        for path, sym, tf in datasets:
            with open(path) as f:
                raw = json.load(f)
            klines = raw.get("klines", raw) if isinstance(raw, dict) else raw

            # Timeframe-specific params
            w = args.window
            r = args.rebalance
            if tf == "1d":
                w, r = 60, 10
            elif tf == "4h":
                w, r = 100, 15

            results = simulate_and_score(klines, sym, tf, window=w, rebalance=r)
            eq = results["equity"]
            tail = results.get("tail", {})
            v = verdict(results)

            label = f"{sym} {tf}"
            summary.append({
                "label": label,
                "dd_imp": eq["dd_improvement_pp"],
                "sh_imp": eq["sharpe_improvement"],
                "ins_ratio": tail.get("insurance_ratio", 0),
                "value_ratio": tail.get("value_ratio", 0),
                "hit_rate": results["per_decision"].get("hit_rate", 0),
                "verdict": v,
            })
            # Print full results for each
            print_results(results, sym, tf, show_individual=False)
            print(f"  VERDICT: {v}")

        # Cross-dataset summary
        print(f"\n{'='*95}")
        print(f"  CROSS-DATASET SUMMARY")
        print(f"{'='*95}")
        print(f"  {'Dataset':<16} {'DD Imp':>8} {'Sh Imp':>8} {'InsRatio':>9} {'ValRatio':>9} {'HitRate':>8} {'Verdict'}")
        print(f"  {'-'*90}")
        for s in summary:
            dd_mark = "+" if s["dd_imp"] > 0 else "-"
            sh_mark = "+" if s["sh_imp"] > 0 else "-"
            ins_mark = "+" if s["ins_ratio"] > 0.05 else "-"
            print(f"  {s['label']:<16} {dd_mark}{abs(s['dd_imp']):>6.2f}pp {sh_mark}{abs(s['sh_imp']):>6.3f} "
                  f"{s['ins_ratio']:>+8.3f} {s['value_ratio']:>8.2f}x {s['hit_rate']*100:>7.1f}% "
                  f"{s['verdict'].split(' -- ')[0]}")

        dd_wins = sum(1 for s in summary if s["dd_imp"] > 0)
        sh_wins = sum(1 for s in summary if s["sh_imp"] > 0)
        ins_wins = sum(1 for s in summary if s["ins_ratio"] > 0.05)
        total = len(summary)
        print(f"\n  DD improved: {dd_wins}/{total}  |  Sharpe improved: {sh_wins}/{total}  |  "
              f"Tail protection: {ins_wins}/{total}")


if __name__ == "__main__":
    main()
