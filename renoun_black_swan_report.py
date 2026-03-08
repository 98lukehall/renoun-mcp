"""
ReNoUn Black Swan Comprehensive Report Generator
Patent Pending #63/923,592

Generates structured per-event reports and a cross-event summary for the
ReNoUn finance engine's performance during major crypto crash events.

Outputs:
  - Per-event JSON results
  - Per-event human-readable reports
  - Cross-event SUMMARY.md with comparison table

Uses the same analysis engine as renoun_black_swan_test.py but produces
archival-quality reports with DHS trajectories, constellation sequences,
early warning metrics, and exposure timelines.
"""

import json
import os
import sys
import time
import traceback
from datetime import datetime, timezone

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from renoun_finance import analyze_financial
from renoun_exposure import ConstellationTracker, smooth_exposure, dhs_to_exposure


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TESTDATA_DIR = os.path.join(SCRIPT_DIR, "..", "finance", "testdata")
RESULTS_DIR = os.path.join(SCRIPT_DIR, "black_swan_results")


# ---------------------------------------------------------------------------
# Event definitions
# ---------------------------------------------------------------------------

EVENTS = [
    {
        "name": "COVID Crash 2020",
        "short_name": "COVID Crash",
        "date": "March 2020",
        "dir_name": "covid_crash_2020",
        "description": "BTC dropped ~50% in 2 days (March 12-13, 2020). "
                       "Global pandemic panic triggered the fastest crash in crypto history.",
        "btc_file": "blackswan_covid_2020.json",
        "eth_file": "blackswan_covid_eth_1h.json",
    },
    {
        "name": "China Ban May 2021",
        "short_name": "China Ban",
        "date": "May 2021",
        "dir_name": "may_2021_china_ban",
        "description": "BTC dropped ~55% over 2 weeks (May 12-19, 2021). "
                       "China mining ban + Elon Musk tweets triggered multi-wave selloff.",
        "btc_file": "blackswan_china_ban_2021.json",
        "eth_file": "blackswan_china_ban_eth_1h.json",
    },
    {
        "name": "LUNA/UST Collapse 2022",
        "short_name": "LUNA Collapse",
        "date": "May 2022",
        "dir_name": "luna_collapse_2022",
        "description": "BTC dropped ~30% in days (May 5-12, 2022). "
                       "LUNA/UST algorithmic stablecoin death spiral.",
        "btc_file": "blackswan_luna_2022.json",
        "eth_file": "blackswan_luna_eth_1h.json",
    },
    {
        "name": "FTX Collapse 2022",
        "short_name": "FTX Collapse",
        "date": "November 2022",
        "dir_name": "ftx_collapse_2022",
        "description": "BTC dropped ~25% in days (Nov 6-9, 2022). "
                       "FTX exchange insolvency and fraud revealed.",
        "btc_file": "blackswan_ftx_2022.json",
        "eth_file": "blackswan_ftx_eth_1h.json",
    },
]


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_klines(filename):
    """Load klines from testdata directory. Returns list of candle dicts or None."""
    filepath = os.path.join(TESTDATA_DIR, filename)
    if not os.path.exists(filepath):
        return None
    with open(filepath) as f:
        data = json.load(f)
    klines = data.get("klines", data)
    if not isinstance(klines, list) or len(klines) < 50:
        return None
    return klines


# ---------------------------------------------------------------------------
# Core analysis (mirrors renoun_black_swan_test.py with extended output)
# ---------------------------------------------------------------------------

def analyze_event(klines, symbol, renoun_window=50, rebalance_every=5):
    """
    Run the v2 engine across a black swan event period.

    Returns a detailed result dict with:
      - DHS trajectory
      - Early warning metrics
      - Constellation sequences
      - Managed vs unmanaged drawdown
      - Full exposure timeline
    """
    closes = np.array([float(k.get("close", k.get("c", 0))) for k in klines])
    timestamps = [int(k.get("openTime", 0)) for k in klines]
    n = len(closes)

    # Returns
    returns = np.diff(closes) / closes[:-1]

    # --- Run v2 engine with rolling window ---
    exposure_v2 = np.ones(n)
    dhs_series = np.full(n, np.nan)
    constellation_series = ["" for _ in range(n)]
    tracker = ConstellationTracker()
    prev_smooth_exp = 1.0

    renoun_log = []
    start = renoun_window

    for i in range(start, n, rebalance_every):
        window_klines = klines[max(0, i - renoun_window):i]
        try:
            result = analyze_financial(window_klines, symbol=symbol, timeframe="1h")
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
            smooth_exp = smooth_exposure(raw_exp, prev_smooth_exp)
            prev_smooth_exp = smooth_exp

            # Apply for next rebalance_every candles
            end_idx = min(i + rebalance_every, n)
            exposure_v2[i:end_idx] = smooth_exp
            dhs_series[i:end_idx] = dhs
            for j in range(i, end_idx):
                constellation_series[j] = top_const

            renoun_log.append({
                "candle_index": i,
                "timestamp": timestamps[i] if i < len(timestamps) else 0,
                "price": float(closes[i]),
                "dhs": round(dhs, 4),
                "constellation": top_const,
                "effective_constellation": eff_const,
                "loop_strength": round(loop, 4),
                "dd_stress": round(dd_stress, 4),
                "vol_stress": round(vol_stress, 4),
                "exposure_raw": round(raw_exp, 4),
                "exposure_smooth": round(smooth_exp, 4),
                "run_length": persist["run_length"],
                "churn": persist["churn"],
                "crash_regime": crash_reg,
            })
        except Exception as e:
            renoun_log.append({
                "candle_index": i,
                "error": str(e),
            })

    # --- Worst hour ---
    worst_hour_idx = int(np.argmin(returns))
    worst_hour_return = float(returns[worst_hour_idx])

    # --- Worst 24h rolling drawdown ---
    worst_24h_dd = 0.0
    worst_24h_start = 0
    worst_24h_end = 0

    for i in range(n - 24):
        dd_24 = (closes[i + 24] - closes[i]) / closes[i]
        if dd_24 < worst_24h_dd:
            worst_24h_dd = dd_24
            worst_24h_start = i
            worst_24h_end = i + 24

    # --- Early warning: first candle where exposure < 0.5 before worst hour ---
    early_warning_candle = None
    early_warning_hours = 0

    # Search backwards from worst hour
    for i in range(worst_hour_idx, -1, -1):
        if exposure_v2[i] >= 0.5:
            if i + 1 <= worst_hour_idx:
                early_warning_candle = i + 1
                early_warning_hours = worst_hour_idx - early_warning_candle
            break
    else:
        early_warning_candle = start
        early_warning_hours = worst_hour_idx - start

    # Also check forward search from start
    first_drop_candle = None
    for i in range(start, worst_hour_idx):
        if exposure_v2[i] < 0.5:
            first_drop_candle = i
            break

    if first_drop_candle is not None:
        early_warning_hours = worst_hour_idx - first_drop_candle
        early_warning_candle = first_drop_candle

    if early_warning_candle is None:
        early_warning_hours = 0

    # --- Avg exposure during worst 24h ---
    if worst_24h_end <= n:
        avg_exposure_worst_24h = float(np.mean(exposure_v2[worst_24h_start:worst_24h_end]))
    else:
        avg_exposure_worst_24h = float(np.mean(exposure_v2[worst_24h_start:]))

    # --- Constellation sequence leading into crash ---
    pre_crash_consts = []
    for entry in renoun_log:
        if "constellation" in entry and entry["candle_index"] <= worst_hour_idx:
            pre_crash_consts.append(entry["constellation"])
    deduped = []
    for c in pre_crash_consts:
        if not deduped or deduped[-1] != c:
            deduped.append(c)
    const_sequence_5 = deduped[-5:] if len(deduped) >= 5 else deduped

    # --- Equity curves ---
    bh_equity = [1.0]
    for r in returns:
        bh_equity.append(bh_equity[-1] * (1 + r))
    bh_equity = np.array(bh_equity)

    managed_equity = [1.0]
    for i in range(len(returns)):
        managed_equity.append(managed_equity[-1] * (1 + exposure_v2[i] * returns[i]))
    managed_equity = np.array(managed_equity)

    bh_peak = np.maximum.accumulate(bh_equity)
    bh_dd = (bh_equity - bh_peak) / bh_peak
    bh_max_dd = float(np.min(bh_dd))

    man_peak = np.maximum.accumulate(managed_equity)
    man_dd = (managed_equity - man_peak) / man_peak
    man_max_dd = float(np.min(man_dd))

    dd_reduction_pp = (abs(bh_max_dd) - abs(man_max_dd)) * 100

    market_return = (closes[-1] / closes[0]) - 1

    # --- Build exposure timeline for plotting ---
    exposure_timeline = []
    for i in range(n):
        exposure_timeline.append({
            "index": i,
            "timestamp": timestamps[i] if i < len(timestamps) else 0,
            "price": float(closes[i]),
            "dhs": float(dhs_series[i]) if not np.isnan(dhs_series[i]) else None,
            "exposure": float(exposure_v2[i]),
            "constellation": constellation_series[i],
        })

    # --- DHS trajectory tuples ---
    dhs_trajectory = []
    for entry in renoun_log:
        if "dhs" in entry:
            dhs_trajectory.append({
                "window_index": entry["candle_index"],
                "dhs": entry["dhs"],
                "exposure": entry["exposure_smooth"],
                "constellation": entry["constellation"],
                "effective_constellation": entry["effective_constellation"],
                "crash_regime": entry.get("crash_regime", False),
            })

    # --- Verdict ---
    timing_pass = early_warning_hours > 0
    dd_pass = dd_reduction_pp > 0
    exp_pass = avg_exposure_worst_24h < 0.5
    all_pass = timing_pass and dd_pass and exp_pass
    verdict = "PASS" if all_pass else ("PARTIAL" if (dd_pass or exp_pass) else "FAIL")

    return {
        "symbol": symbol,
        "n_candles": n,
        "price_start": float(closes[0]),
        "price_end": float(closes[-1]),
        "price_min": float(np.min(closes)),
        "price_max": float(np.max(closes)),
        "market_return_pct": round(market_return * 100, 2),

        "worst_hour_idx": worst_hour_idx,
        "worst_hour_return_pct": round(worst_hour_return * 100, 2),
        "worst_hour_timestamp": timestamps[worst_hour_idx] if worst_hour_idx < len(timestamps) else 0,
        "worst_24h_start": worst_24h_start,
        "worst_24h_end": worst_24h_end,
        "worst_24h_dd_pct": round(worst_24h_dd * 100, 2),

        "early_warning_candle": early_warning_candle,
        "early_warning_hours": early_warning_hours,
        "avg_exposure_worst_24h": round(avg_exposure_worst_24h, 4),

        "constellation_sequence_pre_crash": const_sequence_5,

        "unmanaged_max_dd_pct": round(bh_max_dd * 100, 2),
        "managed_max_dd_pct": round(man_max_dd * 100, 2),
        "dd_reduction_pp": round(dd_reduction_pp, 1),

        "bh_final_equity": round(float(bh_equity[-1]), 4),
        "managed_final_equity": round(float(managed_equity[-1]), 4),

        "timing_pass": timing_pass,
        "dd_pass": dd_pass,
        "exposure_pass": exp_pass,
        "verdict": verdict,

        "dhs_trajectory": dhs_trajectory,
        "exposure_timeline": exposure_timeline,
        "renoun_log": renoun_log,
    }


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------

def format_timestamp(ts_ms):
    """Convert millisecond timestamp to human-readable string."""
    if not ts_ms:
        return "N/A"
    try:
        dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return str(ts_ms)


def _render_ascii_chart(values, labels, width=60, height=15, title="",
                        marker_indices=None, marker_char="X"):
    """
    Render a simple ASCII chart.

    values: list of floats
    labels: list of strings (same length) for x-axis annotation
    width: chart width in columns
    height: chart height in rows
    marker_indices: set of indices to mark with marker_char
    """
    if not values:
        return ["    (no data)"]

    lines = []
    if title:
        lines.append(f"    {title}")
        lines.append("")

    v_min = min(values)
    v_max = max(values)
    v_range = v_max - v_min
    if v_range < 0.001:
        v_range = 0.1  # avoid division by zero

    # Sample values to fit width
    n = len(values)
    step = max(1, n // width)
    sampled_vals = [values[i] for i in range(0, n, step)][:width]
    sampled_labels = [labels[i] if labels else "" for i in range(0, n, step)][:width]
    sampled_indices = [i for i in range(0, n, step)][:width]

    if marker_indices is None:
        marker_indices = set()

    # Build rows (top to bottom)
    for row in range(height, -1, -1):
        threshold = v_min + (row / height) * v_range
        # Y-axis label
        if row == height:
            y_label = f"{v_max:.2f}"
        elif row == height // 2:
            y_label = f"{(v_min + v_max) / 2:.2f}"
        elif row == 0:
            y_label = f"{v_min:.2f}"
        else:
            y_label = ""

        row_chars = []
        for col_idx, val in enumerate(sampled_vals):
            orig_idx = sampled_indices[col_idx]
            normalized = (val - v_min) / v_range * height
            if abs(normalized - row) < 0.5 or (row == 0 and normalized < 0.5):
                if orig_idx in marker_indices:
                    row_chars.append(marker_char)
                else:
                    row_chars.append("#")
            elif normalized > row:
                row_chars.append("|")
            else:
                row_chars.append(" ")

        lines.append(f"    {y_label:>7s} |{''.join(row_chars)}")

    # X-axis
    lines.append(f"    {'':>7s} +{'-' * len(sampled_vals)}")

    return lines


def _render_exposure_timeline_summary(exposure_timeline, worst_24h_start,
                                       worst_24h_end, worst_hour_idx):
    """
    Render a compact exposure timeline summary showing phases.
    Groups consecutive candles by exposure level into phases.
    """
    lines = []
    lines.append("  EXPOSURE TIMELINE SUMMARY")

    if not exposure_timeline:
        lines.append("    (no data)")
        return lines

    # Define exposure phases
    def phase_label(exp):
        if exp >= 0.8:
            return "FULL (0.8-1.0)"
        elif exp >= 0.5:
            return "MODERATE (0.5-0.8)"
        elif exp >= 0.3:
            return "REDUCED (0.3-0.5)"
        else:
            return "MINIMAL (0.2-0.3)"

    # Build phases from timeline
    phases = []
    current_phase = None
    phase_start = 0

    for entry in exposure_timeline:
        idx = entry["index"]
        exp = entry["exposure"]
        pl = phase_label(exp)

        if pl != current_phase:
            if current_phase is not None:
                phases.append((phase_start, idx - 1, current_phase))
            current_phase = pl
            phase_start = idx

    if current_phase is not None:
        phases.append((phase_start, exposure_timeline[-1]["index"], current_phase))

    # Render phases
    lines.append(f"    {'Candles':>15s} | {'Duration':>10s} | {'Phase':<25s} | {'Context'}")
    lines.append(f"    {'':->15s}-+-{'':->10s}-+-{'':->25s}-+-{'':->20s}")

    for start, end, phase in phases:
        duration = end - start + 1
        # Context markers
        context = ""
        if start <= worst_hour_idx <= end:
            context = "<-- WORST HOUR"
        elif start <= worst_24h_start <= end or start <= worst_24h_end <= end:
            context = "<-- WORST 24H"
        elif worst_24h_start >= start and worst_24h_end <= end:
            context = "<-- WORST 24H"

        lines.append(f"    {start:>6d}-{end:<6d} | {duration:>8d}h | {phase:<25s} | {context}")

    lines.append("")
    return lines


def generate_text_report(event, results):
    """
    Generate human-readable text report for a single event.
    results is a dict mapping symbol -> analysis result.
    """
    lines = []
    lines.append("=" * 78)
    lines.append(f"ReNoUn Black Swan Report: {event['name']}")
    lines.append(f"Event Period: {event['date']}")
    lines.append(f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append("=" * 78)
    lines.append("")
    lines.append(f"Description: {event['description']}")
    lines.append("")

    for symbol, r in results.items():
        lines.append("-" * 78)
        lines.append(f"  Asset: {symbol}")
        lines.append("-" * 78)
        lines.append("")

        # Market overview
        lines.append("  MARKET OVERVIEW")
        lines.append(f"    Candles analyzed:  {r['n_candles']} (1h interval)")
        lines.append(f"    Price range:       ${r['price_min']:,.2f} - ${r['price_max']:,.2f}")
        lines.append(f"    Start price:       ${r['price_start']:,.2f}")
        lines.append(f"    End price:         ${r['price_end']:,.2f}")
        lines.append(f"    Market return:     {r['market_return_pct']:+.2f}%")
        lines.append("")

        # Crash metrics
        lines.append("  CRASH METRICS")
        lines.append(f"    Worst single hour: {r['worst_hour_return_pct']:+.2f}% "
                      f"(candle {r['worst_hour_idx']}, "
                      f"{format_timestamp(r['worst_hour_timestamp'])})")
        lines.append(f"    Worst 24h DD:      {r['worst_24h_dd_pct']:+.2f}% "
                      f"(candles {r['worst_24h_start']}-{r['worst_24h_end']})")
        lines.append("")

        # Early warning
        lines.append("  EARLY WARNING")
        if r["early_warning_hours"] > 0:
            lines.append(f"    Exposure < 0.5 at: candle {r['early_warning_candle']} "
                          f"({r['early_warning_hours']} hours BEFORE worst single-hour drop)")
        else:
            lines.append(f"    Exposure did not drop below 0.5 before worst hour")
        lines.append(f"    Avg exposure during worst 24h: {r['avg_exposure_worst_24h']:.4f}")

        # Early warning score: hours before the worst 24h window
        ew_before_24h = 0
        if r["early_warning_candle"] is not None and r["early_warning_candle"] < r["worst_24h_start"]:
            ew_before_24h = r["worst_24h_start"] - r["early_warning_candle"]
        lines.append(f"    Early warning vs worst 24h:    {ew_before_24h}h before worst 24h window started")
        lines.append("")

        # Constellation sequence
        lines.append("  PRE-CRASH CONSTELLATION SEQUENCE (last 5 unique before worst hour)")
        if r["constellation_sequence_pre_crash"]:
            seq = " -> ".join(r["constellation_sequence_pre_crash"])
            lines.append(f"    {seq}")
        else:
            lines.append(f"    (no constellations detected)")
        lines.append("")

        # Drawdown comparison
        lines.append("  DRAWDOWN COMPARISON")
        lines.append(f"    Unmanaged max DD:  {r['unmanaged_max_dd_pct']:+.2f}%")
        lines.append(f"    Managed max DD:    {r['managed_max_dd_pct']:+.2f}%")
        lines.append(f"    DD reduction:      {r['dd_reduction_pp']:+.1f} pp")
        lines.append("")
        lines.append(f"    Buy-and-hold final equity: {r['bh_final_equity']:.4f}")
        lines.append(f"    Managed final equity:      {r['managed_final_equity']:.4f}")
        lines.append("")

        # Verdict
        lines.append("  VERDICT")
        t_mark = "[PASS]" if r["timing_pass"] else "[FAIL]"
        d_mark = "[PASS]" if r["dd_pass"] else "[FAIL]"
        e_mark = "[PASS]" if r["exposure_pass"] else "[FAIL]"
        lines.append(f"    Overall: [{r['verdict']}]")
        lines.append(f"    Timing (early warning > 0h):    {t_mark}  ({r['early_warning_hours']}h)")
        lines.append(f"    Drawdown reduction (> 0 pp):    {d_mark}  ({r['dd_reduction_pp']:+.1f} pp)")
        lines.append(f"    Protective exposure (< 0.50):   {e_mark}  ({r['avg_exposure_worst_24h']:.4f})")
        lines.append("")

        # --- ASCII DHS Trajectory Chart ---
        dhs_vals = [e["dhs"] for e in r["renoun_log"] if "dhs" in e]
        dhs_candles = [e["candle_index"] for e in r["renoun_log"] if "dhs" in e]
        if dhs_vals:
            # Mark the worst hour position in the chart
            worst_set = set()
            for ci in dhs_candles:
                if abs(ci - r["worst_hour_idx"]) < 10:
                    worst_set.add(dhs_candles.index(ci) if ci in dhs_candles else -1)

            chart_lines = _render_ascii_chart(
                dhs_vals,
                [str(c) for c in dhs_candles],
                width=60,
                height=12,
                title=f"DHS Trajectory ({symbol}) -- X marks near worst hour",
                marker_indices=worst_set,
                marker_char="X",
            )
            lines.append("  DHS CHART (full event period)")
            lines.extend(chart_lines)
            lines.append("")

        # --- ASCII Exposure Chart ---
        exp_vals = [e["exposure_smooth"] for e in r["renoun_log"] if "exposure_smooth" in e]
        if exp_vals:
            exp_chart_lines = _render_ascii_chart(
                exp_vals,
                [str(e["candle_index"]) for e in r["renoun_log"] if "exposure_smooth" in e],
                width=60,
                height=10,
                title=f"Exposure Trajectory ({symbol}) -- 0.5 threshold shown",
            )
            lines.append("  EXPOSURE CHART (full event period)")
            lines.extend(exp_chart_lines)
            # Add 0.5 threshold reference
            lines.append(f"    {'':>7s}  (0.50 threshold = protective)")
            lines.append("")

        # --- Exposure Timeline Summary ---
        if r.get("exposure_timeline"):
            timeline_lines = _render_exposure_timeline_summary(
                r["exposure_timeline"],
                r["worst_24h_start"],
                r["worst_24h_end"],
                r["worst_hour_idx"],
            )
            lines.extend(timeline_lines)

        # DHS trajectory table — last 15 rebalance points before worst hour
        lines.append("  DHS TRAJECTORY TABLE (last 15 rebalance points before worst hour)")
        lines.append(f"    {'t-Xh':>8s} | {'DHS':>6s} | {'Exp':>6s} | {'Bar':<20s} | {'Constellation':<25s} | {'Regime'}")
        lines.append(f"    {'':->8s}-+-{'':->6s}-+-{'':->6s}-+-{'':->20s}-+-{'':->25s}-+-{'':->10s}")

        pre_crash_log = [e for e in r["renoun_log"]
                         if "dhs" in e and e["candle_index"] <= r["worst_hour_idx"]]
        for entry in pre_crash_log[-15:]:
            dist = r["worst_hour_idx"] - entry["candle_index"]
            eff = entry.get("effective_constellation", entry["constellation"])
            eff_note = f" (eff:{eff})" if eff != entry["constellation"] else ""
            crash_flag = "CRASH" if entry.get("crash_regime", False) else ""
            bar = "#" * int(entry["exposure_smooth"] * 20)
            lines.append(f"    t-{dist:>5d}h | {entry['dhs']:.4f} | {entry['exposure_smooth']:.4f} | "
                          f"{bar:<20s} | {entry['constellation']}{eff_note:<25s} | {crash_flag}")
        lines.append("")

    lines.append("=" * 78)
    lines.append("Engine: ReNoUn Finance v2 (crash regime + ConstellationTracker)")
    lines.append("Window: 50 candles, rebalance every 5 candles, 1h timeframe")
    lines.append("Exposure: asymmetric EMA smoothing + persistence scoring + 0.20 floor")
    lines.append("Patent Pending #63/923,592")
    lines.append("=" * 78)

    return "\n".join(lines)


def generate_summary_md(all_event_results):
    """
    Generate cross-event SUMMARY.md.

    all_event_results: list of (event_dict, {symbol: result_dict, ...})
    """
    lines = []
    lines.append("# ReNoUn Black Swan Validation Report")
    lines.append("")
    lines.append(f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append("")

    # --- Combined summary table (all events, all assets) ---
    lines.append("## Summary Table")
    lines.append("")
    lines.append("| Event | Asset | DD Unmanaged | DD Managed | Reduction | Early Warning (hours) | Pre-Crash Constellation | Result |")
    lines.append("|-------|-------|-------------|------------|-----------|----------------------|------------------------|--------|")

    all_results_flat = []
    btc_results = []
    eth_results = []

    for event, results in all_event_results:
        for symbol in ["BTCUSDT", "ETHUSDT"]:
            if symbol in results:
                r = results[symbol]
                all_results_flat.append(r)
                if symbol == "BTCUSDT":
                    btc_results.append(r)
                else:
                    eth_results.append(r)

                seq = " -> ".join(r["constellation_sequence_pre_crash"][-3:]) if r["constellation_sequence_pre_crash"] else "N/A"
                warning_str = f"{r['early_warning_hours']}h" if r["early_warning_hours"] > 0 else "none"
                lines.append(
                    f"| {event['short_name']} | "
                    f"{symbol} | "
                    f"{r['unmanaged_max_dd_pct']:+.1f}% | "
                    f"{r['managed_max_dd_pct']:+.1f}% | "
                    f"{r['dd_reduction_pp']:+.1f} pp | "
                    f"{warning_str} | "
                    f"{seq} | "
                    f"{r['verdict']} |"
                )

    lines.append("")

    # --- Key Findings ---
    lines.append("## Key Findings")
    lines.append("")

    if btc_results:
        avg_dd_red_btc = np.mean([r["dd_reduction_pp"] for r in btc_results])
        avg_warning_btc = np.mean([r["early_warning_hours"] for r in btc_results])
        events_with_warning_btc = sum(1 for r in btc_results if r["early_warning_hours"] > 0)
        events_with_prot_exp_btc = sum(1 for r in btc_results if r["avg_exposure_worst_24h"] < 0.5)
        events_pass_btc = sum(1 for r in btc_results if r["verdict"] == "PASS")
        events_partial_btc = sum(1 for r in btc_results if r["verdict"] == "PARTIAL")

        lines.append("### BTC Performance")
        lines.append("")
        lines.append(f"- {events_with_warning_btc}/{len(btc_results)} events showed early warning "
                      f"(exposure < 0.5 before worst hour)")
        lines.append(f"- Average DD reduction: {avg_dd_red_btc:+.1f} pp (BTC only)")
        lines.append(f"- Average early warning: {avg_warning_btc:.0f} hours")
        lines.append(f"- Events with protective exposure (avg < 0.5 during worst 24h): "
                      f"{events_with_prot_exp_btc}/{len(btc_results)}")
        lines.append(f"- Full PASS: {events_pass_btc}/{len(btc_results)}, "
                      f"PARTIAL: {events_partial_btc}/{len(btc_results)}")
        lines.append(f"- The crash regime flag improved multi-wave crash handling")
        lines.append("")

    if eth_results:
        avg_dd_red_eth = np.mean([r["dd_reduction_pp"] for r in eth_results])
        avg_warning_eth = np.mean([r["early_warning_hours"] for r in eth_results])
        events_pass_eth = sum(1 for r in eth_results if r["verdict"] == "PASS")
        events_partial_eth = sum(1 for r in eth_results if r["verdict"] == "PARTIAL")

        lines.append("### ETH Performance")
        lines.append("")
        lines.append(f"- Average DD reduction: {avg_dd_red_eth:+.1f} pp")
        lines.append(f"- Average early warning: {avg_warning_eth:.0f} hours")
        lines.append(f"- Full PASS: {events_pass_eth}/{len(eth_results)}, "
                      f"PARTIAL: {events_partial_eth}/{len(eth_results)}")
        lines.append("")

    if all_results_flat:
        avg_dd_all = np.mean([r["dd_reduction_pp"] for r in all_results_flat])
        lines.append("### Combined (All Assets)")
        lines.append("")
        lines.append(f"- Average DD reduction across all assets: {avg_dd_all:+.1f} pp")
        events_pass_all = sum(1 for r in all_results_flat if r["verdict"] == "PASS")
        events_partial_all = sum(1 for r in all_results_flat if r["verdict"] == "PARTIAL")
        lines.append(f"- Full PASS: {events_pass_all}/{len(all_results_flat)}, "
                      f"PARTIAL: {events_partial_all}/{len(all_results_flat)}")
        lines.append("")

    # Per-event DD reduction detail
    lines.append("### Per-Event DD Reduction Detail")
    lines.append("")
    for (event, results) in all_event_results:
        for symbol in ["BTCUSDT", "ETHUSDT"]:
            if symbol in results:
                r = results[symbol]
                sym_short = symbol.replace("USDT", "")
                lines.append(f"- **{event['short_name']} ({sym_short}):** {r['dd_reduction_pp']:+.1f} pp "
                              f"(unmanaged {r['unmanaged_max_dd_pct']:+.1f}% -> "
                              f"managed {r['managed_max_dd_pct']:+.1f}%)")
    lines.append("")

    # --- Methodology ---
    lines.append("## Methodology")
    lines.append("")
    lines.append("- Rolling window analysis with 50-candle windows, 5-candle rebalance steps")
    lines.append("- v2 exposure engine with asymmetric EMA smoothing + constellation persistence")
    lines.append("- Crash regime flag active (suppresses false DIP_AND_RECOVERY during multi-wave events)")
    lines.append("- Early warning = hours between first exposure < 0.5 and worst single-hour drawdown")
    lines.append("- DD reduction = |unmanaged max DD| - |managed max DD| in percentage points")
    lines.append("- Verdict criteria: PASS = early warning > 0h AND DD reduction > 0pp AND "
                  "avg exposure < 0.5 during worst 24h")
    lines.append("")
    lines.append("## Engine Details")
    lines.append("")
    lines.append("- **Engine:** ReNoUn Finance v2 (17-channel structural analysis)")
    lines.append("- **Patent:** Pending #63/923,592")
    lines.append("- **Exposure mapping:** DHS-tiered base + constellation mods + stress signals")
    lines.append("- **Smoothing:** Asymmetric EMA (alpha_down=0.6, alpha_up=0.3)")
    lines.append("- **Floor:** 0.20 (never fully flat)")
    lines.append("- **Crash regime penalty:** 0.5x exposure multiplier during multi-wave crash suppression")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main report generator
# ---------------------------------------------------------------------------

def run_report():
    """Generate the full black swan validation report."""
    print("=" * 78)
    print("ReNoUn BLACK SWAN COMPREHENSIVE REPORT GENERATOR")
    print("Patent Pending #63/923,592")
    print("=" * 78)
    print()
    print(f"Results directory: {RESULTS_DIR}")
    print(f"Test data directory: {TESTDATA_DIR}")
    print()

    all_event_results = []

    for event in EVENTS:
        print(f"\n{'='*60}")
        print(f"Processing: {event['name']} ({event['date']})")
        print(f"{'='*60}")

        event_results = {}
        event_dir = os.path.join(RESULTS_DIR, event["dir_name"])
        os.makedirs(event_dir, exist_ok=True)

        # --- BTC ---
        print(f"\n  Loading BTC data: {event['btc_file']}")
        btc_klines = load_klines(event["btc_file"])
        if btc_klines:
            print(f"  Loaded {len(btc_klines)} BTC candles")
            print(f"  Running analysis...")
            try:
                btc_result = analyze_event(btc_klines, "BTCUSDT")
                event_results["BTCUSDT"] = btc_result
                print(f"  BTC result: {btc_result['verdict']} "
                      f"(DD reduction: {btc_result['dd_reduction_pp']:+.1f} pp, "
                      f"early warning: {btc_result['early_warning_hours']}h)")
            except Exception as e:
                print(f"  BTC analysis failed: {e}")
                traceback.print_exc()
        else:
            print(f"  BTC data not found: {event['btc_file']}")

        # --- ETH ---
        print(f"\n  Loading ETH data: {event['eth_file']}")
        eth_klines = load_klines(event["eth_file"])
        if eth_klines:
            print(f"  Loaded {len(eth_klines)} ETH candles")
            print(f"  Running analysis...")
            try:
                eth_result = analyze_event(eth_klines, "ETHUSDT")
                event_results["ETHUSDT"] = eth_result
                print(f"  ETH result: {eth_result['verdict']} "
                      f"(DD reduction: {eth_result['dd_reduction_pp']:+.1f} pp, "
                      f"early warning: {eth_result['early_warning_hours']}h)")
            except Exception as e:
                print(f"  ETH analysis failed: {e}")
                traceback.print_exc()
        else:
            print(f"  ETH data not found: {event['eth_file']}")

        # --- Save per-event outputs ---
        if event_results:
            # JSON results
            for symbol, result in event_results.items():
                sym_lower = symbol.replace("USDT", "").lower()
                json_path = os.path.join(event_dir, f"{sym_lower}usdt_1h_results.json")

                # Create a serializable copy (exclude the huge exposure_timeline for JSON size)
                json_result = {k: v for k, v in result.items()
                               if k != "exposure_timeline"}
                # Add a trimmed timeline (every 5th point)
                json_result["exposure_timeline_sampled"] = result["exposure_timeline"][::5]

                with open(json_path, "w") as f:
                    json.dump(json_result, f, indent=2, default=str)
                print(f"  Saved: {json_path}")

            # Text report
            report_text = generate_text_report(event, event_results)
            # Determine report filename based on available symbols
            symbols_str = "_".join(s.replace("USDT", "").lower() for s in sorted(event_results.keys()))
            report_path = os.path.join(event_dir, f"{symbols_str}usdt_1h_report.txt")
            with open(report_path, "w") as f:
                f.write(report_text)
            print(f"  Saved: {report_path}")

            # Also save individual symbol reports if multiple symbols
            if len(event_results) > 1:
                for symbol, result in event_results.items():
                    sym_lower = symbol.replace("USDT", "").lower()
                    single_report = generate_text_report(event, {symbol: result})
                    single_path = os.path.join(event_dir, f"{sym_lower}usdt_1h_report.txt")
                    with open(single_path, "w") as f:
                        f.write(single_report)
                    print(f"  Saved: {single_path}")

        all_event_results.append((event, event_results))

    # --- Generate summary ---
    print(f"\n{'='*60}")
    print("Generating cross-event summary...")
    print(f"{'='*60}")

    summary_md = generate_summary_md(all_event_results)
    summary_path = os.path.join(RESULTS_DIR, "SUMMARY.md")
    with open(summary_path, "w") as f:
        f.write(summary_md)
    print(f"Saved: {summary_path}")

    # --- Print summary to console ---
    print()
    print()
    _print_console_summary(all_event_results)


def _print_console_summary(all_event_results):
    """Print a compact summary table to stdout."""
    print("=" * 100)
    print("BLACK SWAN VALIDATION SUMMARY")
    print("=" * 100)
    print()

    for asset in ["BTCUSDT", "ETHUSDT"]:
        asset_results = [(e, r[asset]) for e, r in all_event_results if asset in r]
        if not asset_results:
            continue

        print(f"  {asset}")
        print(f"  {'Event':<20s} {'Candles':>8s} {'BH DD':>10s} {'Mgd DD':>10s} "
              f"{'DD Red':>10s} {'Warning':>10s} {'Avg Exp':>10s} {'Result':>8s}")
        print(f"  {'-'*20} {'-'*8} {'-'*10} {'-'*10} {'-'*10} {'-'*10} {'-'*10} {'-'*8}")

        for event, r in asset_results:
            warning_str = f"{r['early_warning_hours']}h" if r["early_warning_hours"] > 0 else "none"
            print(f"  {event['short_name']:<20s} {r['n_candles']:>8d} "
                  f"{r['unmanaged_max_dd_pct']:>+9.1f}% "
                  f"{r['managed_max_dd_pct']:>+9.1f}% "
                  f"{r['dd_reduction_pp']:>+9.1f} "
                  f"{warning_str:>10s} "
                  f"{r['avg_exposure_worst_24h']:>10.4f} "
                  f"{r['verdict']:>8s}")

        # Aggregates
        results_list = [r for _, r in asset_results]
        avg_dd = np.mean([r["dd_reduction_pp"] for r in results_list])
        avg_warn = np.mean([r["early_warning_hours"] for r in results_list])
        avg_exp = np.mean([r["avg_exposure_worst_24h"] for r in results_list])
        n_pass = sum(1 for r in results_list if r["verdict"] == "PASS")
        n_partial = sum(1 for r in results_list if r["verdict"] == "PARTIAL")

        print(f"  {'':->20} {'':->8} {'':->10} {'':->10} {'':->10} {'':->10} {'':->10} {'':->8}")
        print(f"  {'AVERAGE':<20s} {'':>8s} {'':>10s} {'':>10s} "
              f"{avg_dd:>+9.1f} "
              f"{avg_warn:>9.0f}h "
              f"{avg_exp:>10.4f} "
              f"{n_pass}P/{n_partial}PT")
        print()

    print("=" * 100)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    run_report()
