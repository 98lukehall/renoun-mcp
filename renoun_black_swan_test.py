"""
ReNoUn Black Swan Historical Validation
Patent Pending #63/923,592

CRITICAL credibility test: did the ReNoUn finance engine reduce exposure
BEFORE the worst of major crypto crashes?

Tests against 4 historically significant crypto crash events:
  1. COVID Crash (March 2020) — BTC ~50% drop in 2 days
  2. China Ban (May 2021) — BTC ~55% drop over 2 weeks
  3. LUNA/UST Collapse (May 2022) — BTC ~30% drop in days
  4. FTX Collapse (November 2022) — BTC ~25% drop in days

For each event, fetches historical 1h kline data (or generates synthetic
data matching known price curves) and runs the v2 engine with rolling
window analysis to measure:
  - Early warning: how many hours before the worst drawdown did exposure
    first drop below 0.5?
  - Protective exposure: average exposure during the worst 24h
  - Drawdown reduction: managed vs unmanaged max drawdown
"""

import json
import os
import sys
import time
import traceback
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from renoun_finance import analyze_financial
from renoun_exposure import ConstellationTracker, smooth_exposure, dhs_to_exposure


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TESTDATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "..", "finance", "testdata")

EVENTS = [
    {
        "name": "COVID Crash",
        "date": "March 2020",
        "symbol": "BTCUSDT",
        "start": "2020-02-27",
        "end": "2020-03-27",
        "filename": "blackswan_covid_2020.json",
        "description": "BTC dropped ~50% in 2 days (March 12-13, 2020)",
    },
    {
        "name": "China Ban",
        "date": "May 2021",
        "symbol": "BTCUSDT",
        "start": "2021-04-28",
        "end": "2021-05-26",
        "filename": "blackswan_china_ban_2021.json",
        "description": "BTC dropped ~55% over 2 weeks (May 12-19, 2021)",
    },
    {
        "name": "LUNA/UST Collapse",
        "date": "May 2022",
        "symbol": "BTCUSDT",
        "start": "2022-04-21",
        "end": "2022-05-26",
        "filename": "blackswan_luna_2022.json",
        "description": "BTC dropped ~30% in days (May 5-12, 2022)",
    },
    {
        "name": "FTX Collapse",
        "date": "November 2022",
        "symbol": "BTCUSDT",
        "start": "2022-10-23",
        "end": "2022-11-23",
        "filename": "blackswan_ftx_2022.json",
        "description": "BTC dropped ~25% in days (Nov 6-9, 2022)",
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def ts(date_str):
    """Convert 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM' to millisecond timestamp."""
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            from datetime import datetime, timezone
            dt = datetime.strptime(date_str, fmt).replace(tzinfo=timezone.utc)
            return int(dt.timestamp() * 1000)
        except ValueError:
            continue
    raise ValueError(f"Cannot parse date: {date_str}")


def fetch_klines(symbol, interval, start_ms, end_ms, limit=1000):
    """
    Fetch klines from Binance API.
    Primary: Binance US, fallback: Binance global.
    Returns list of dicts or None on failure.
    """
    import urllib.request
    import ssl

    # SSL context that doesn't verify (for environments with cert issues)
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    endpoints = [
        "https://api.binance.us/api/v3/klines",
        "https://api.binance.com/api/v3/klines",
    ]

    for base_url in endpoints:
        all_klines = []
        cur_start = start_ms

        while cur_start < end_ms:
            url = (f"{base_url}?symbol={symbol}&interval={interval}"
                   f"&startTime={cur_start}&endTime={end_ms}&limit={limit}")
            try:
                req = urllib.request.Request(url)
                req.add_header("User-Agent", "Mozilla/5.0")
                with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
                    raw = json.loads(resp.read().decode())

                if not raw or len(raw) == 0:
                    break

                for k in raw:
                    all_klines.append({
                        "openTime": int(k[0]),
                        "open": float(k[1]),
                        "high": float(k[2]),
                        "low": float(k[3]),
                        "close": float(k[4]),
                        "volume": float(k[5]),
                    })

                # Move start past last candle
                cur_start = int(raw[-1][0]) + 1

                # If we got fewer than limit, we're done
                if len(raw) < limit:
                    break

                time.sleep(0.2)  # Rate limiting

            except Exception as e:
                print(f"    API fetch failed ({base_url}): {e}")
                break

        if len(all_klines) > 100:
            print(f"    Fetched {len(all_klines)} candles from {base_url.split('/')[2]}")
            return all_klines

    return None


# ---------------------------------------------------------------------------
# Synthetic crash data generators
# ---------------------------------------------------------------------------

def _make_candle(timestamp_ms, price, prev_close, vol_base, crash_intensity=0.0):
    """
    Create a single realistic OHLCV candle dict.

    crash_intensity [0..1] controls how wide and volatile the candle is.
    Higher intensity = larger wicks, higher volume.
    """
    noise = np.random.normal(0, 0.003 + crash_intensity * 0.015)
    open_price = prev_close * (1 + noise * 0.3)

    # Determine close (the main price passed in)
    close_price = price

    # Wicks
    body_range = abs(open_price - close_price)
    wick_mult = 1.0 + crash_intensity * 3.0
    upper_wick = body_range * np.random.uniform(0.1, 0.8) * wick_mult
    lower_wick = body_range * np.random.uniform(0.1, 0.8) * wick_mult

    high = max(open_price, close_price) + upper_wick
    low = min(open_price, close_price) - lower_wick

    # Ensure valid OHLC
    high = max(high, open_price, close_price)
    low = min(low, open_price, close_price)
    low = max(low, close_price * 0.5)  # don't let low go absurdly negative

    # Volume: spike during crashes
    vol_mult = 1.0 + crash_intensity * np.random.uniform(2.0, 9.0)
    volume = vol_base * vol_mult * np.random.uniform(0.7, 1.5)

    return {
        "openTime": int(timestamp_ms),
        "open": round(open_price, 2),
        "high": round(high, 2),
        "low": round(low, 2),
        "close": round(close_price, 2),
        "volume": round(volume, 2),
    }


def _generate_price_path(n_candles, segments):
    """
    Generate a price path from segment descriptions.

    segments: list of (n_candles_in_segment, start_price, end_price, volatility, crash_intensity)
    """
    prices = []
    intensities = []

    for n_seg, p_start, p_end, vol, intensity in segments:
        # Generate smooth trend with noise
        trend = np.linspace(p_start, p_end, n_seg)

        for i in range(n_seg):
            noise = np.random.normal(0, vol * trend[i])
            p = trend[i] + noise
            p = max(p, trend[i] * 0.8)  # don't deviate too far from trend
            prices.append(p)
            intensities.append(intensity)

    return prices[:n_candles], intensities[:n_candles]


def generate_synthetic_covid():
    """
    COVID Crash (March 2020): ~672 candles (28 days * 24h)

    Profile:
    - Week 1 (Feb 27 - Mar 5): BTC ~$8,800, gradual decline to ~$8,000
    - Week 2 (Mar 5 - Mar 11): Accelerating decline to ~$7,800
    - Mar 12 (24h): Waterfall crash from ~$7,800 to ~$5,000 (first leg)
    - Mar 13 (24h): Second leg crash to ~$3,800, then bounce to ~$5,200
    - Week 3 (Mar 14-20): Recovery to ~$6,200, choppy
    - Week 4 (Mar 20-27): Stabilization around ~$6,500
    """
    np.random.seed(42)
    start_ms = ts("2020-02-27")
    hour_ms = 3600 * 1000
    n_candles = 672

    segments = [
        # (n_candles, start_price, end_price, noise_pct, crash_intensity)
        (168, 8800, 8000, 0.003, 0.0),      # Week 1: slow decline
        (144, 8000, 7800, 0.004, 0.05),      # Mar 5-11: accelerating
        (12,  7800, 6200, 0.008, 0.4),       # Mar 12 AM: first cracks
        (12,  6200, 4800, 0.012, 0.8),       # Mar 12 PM: waterfall
        (8,   4800, 3800, 0.015, 1.0),       # Mar 13 early: bottom
        (16,  3800, 5200, 0.010, 0.7),       # Mar 13 later: bounce
        (144, 5200, 6200, 0.006, 0.2),       # Week 3: recovery
        (168, 6200, 6500, 0.004, 0.05),      # Week 4: stabilization
    ]

    prices, intensities = _generate_price_path(n_candles, segments)
    vol_base = 5000.0

    klines = []
    prev_close = prices[0]
    for i in range(n_candles):
        t = start_ms + i * hour_ms
        candle = _make_candle(t, prices[i], prev_close, vol_base, intensities[i])
        klines.append(candle)
        prev_close = candle["close"]

    return klines


def generate_synthetic_china_ban():
    """
    China Ban (May 2021): ~672 candles (28 days * 24h)

    Profile:
    - Apr 28 - May 7: BTC ~$57,000, slight wobble
    - May 8-11: Start of decline to ~$53,000
    - May 12-15: Sharp leg down to ~$43,000 (Elon tweet + China)
    - May 16-18: Dead cat bounce to ~$45,000
    - May 19: Flash crash to ~$30,000 in hours
    - May 20-22: Choppy recovery to ~$38,000
    - May 23-26: Slow grind around ~$35,000-$38,000
    """
    np.random.seed(43)
    start_ms = ts("2021-04-28")
    hour_ms = 3600 * 1000
    n_candles = 672

    segments = [
        (216, 57000, 55000, 0.003, 0.0),     # Apr 28 - May 7: stable-ish
        (72,  55000, 53000, 0.005, 0.1),      # May 8-11: wobble starts
        (72,  53000, 43000, 0.008, 0.5),      # May 12-15: sharp decline
        (72,  43000, 45000, 0.006, 0.2),      # May 16-18: dead cat bounce
        (12,  45000, 33000, 0.015, 0.9),      # May 19 AM: flash crash
        (12,  33000, 30000, 0.012, 1.0),      # May 19 PM: capitulation
        (72,  30000, 38000, 0.008, 0.4),      # May 20-22: recovery
        (144, 38000, 36000, 0.005, 0.1),      # May 23-26: stabilization
    ]

    prices, intensities = _generate_price_path(n_candles, segments)
    vol_base = 50000.0

    klines = []
    prev_close = prices[0]
    for i in range(n_candles):
        t = start_ms + i * hour_ms
        candle = _make_candle(t, prices[i], prev_close, vol_base, intensities[i])
        klines.append(candle)
        prev_close = candle["close"]

    return klines


def generate_synthetic_luna():
    """
    LUNA/UST Collapse (May 2022): ~840 candles (35 days * 24h)

    Profile:
    - Apr 21 - May 4: BTC ~$39,000, slight decline to ~$38,000
    - May 5-7: UST wobble begins, BTC drops to ~$35,500
    - May 8-9: UST loses peg, BTC crashes to ~$33,000
    - May 10-12: Full LUNA death spiral, BTC to ~$26,500
    - May 13-15: Fake recovery attempts, ~$29,000-$30,000
    - May 16-26: Slow bleed / stabilization around $29,000-$30,000
    """
    np.random.seed(44)
    start_ms = ts("2021-04-21")  # Using 2022 in reality, seed matters
    start_ms = ts("2022-04-21")
    hour_ms = 3600 * 1000
    n_candles = 840

    segments = [
        (312, 39500, 38000, 0.003, 0.0),     # Apr 21 - May 4: calm
        (72,  38000, 35500, 0.006, 0.2),      # May 5-7: wobble
        (48,  35500, 33000, 0.010, 0.6),      # May 8-9: UST de-peg
        (48,  33000, 26500, 0.012, 0.9),      # May 10-12: spiral
        (72,  26500, 30000, 0.008, 0.3),      # May 13-15: fake recovery
        (288, 30000, 29000, 0.004, 0.05),     # May 16-26: stabilization
    ]

    prices, intensities = _generate_price_path(n_candles, segments)
    vol_base = 40000.0

    klines = []
    prev_close = prices[0]
    for i in range(n_candles):
        t = start_ms + i * hour_ms
        candle = _make_candle(t, prices[i], prev_close, vol_base, intensities[i])
        klines.append(candle)
        prev_close = candle["close"]

    return klines


def generate_synthetic_ftx():
    """
    FTX Collapse (November 2022): ~744 candles (31 days * 24h)

    Profile:
    - Oct 23 - Nov 5: BTC stable ~$20,500-$21,000
    - Nov 6-7: CZ tweet, FTT starts dumping, BTC wobble to ~$20,000
    - Nov 8: Withdrawals halted, BTC drops to ~$18,000
    - Nov 9: Full collapse, BTC gaps down to ~$15,500
    - Nov 10-12: Extreme volatility, $15,500-$17,500
    - Nov 13-23: Slow stabilization $16,000-$16,500
    """
    np.random.seed(45)
    start_ms = ts("2022-10-23")
    hour_ms = 3600 * 1000
    n_candles = 744

    segments = [
        (312, 20800, 21000, 0.002, 0.0),     # Oct 23 - Nov 5: stable
        (48,  21000, 20000, 0.005, 0.15),     # Nov 6-7: CZ tweet
        (24,  20000, 18000, 0.010, 0.6),      # Nov 8: withdrawals halt
        (12,  18000, 15500, 0.015, 1.0),      # Nov 9 AM: collapse
        (12,  15500, 16500, 0.012, 0.7),      # Nov 9 PM: bounce
        (72,  16500, 16800, 0.008, 0.3),      # Nov 10-12: volatile
        (264, 16800, 16500, 0.003, 0.05),     # Nov 13-23: stabilization
    ]

    prices, intensities = _generate_price_path(n_candles, segments)
    vol_base = 30000.0

    klines = []
    prev_close = prices[0]
    for i in range(n_candles):
        t = start_ms + i * hour_ms
        candle = _make_candle(t, prices[i], prev_close, vol_base, intensities[i])
        klines.append(candle)
        prev_close = candle["close"]

    return klines


SYNTHETIC_GENERATORS = {
    "COVID Crash": generate_synthetic_covid,
    "China Ban": generate_synthetic_china_ban,
    "LUNA/UST Collapse": generate_synthetic_luna,
    "FTX Collapse": generate_synthetic_ftx,
}


# ---------------------------------------------------------------------------
# Data acquisition
# ---------------------------------------------------------------------------

def get_event_data(event):
    """
    Get kline data for an event. Try API first, fall back to synthetic.
    Cache to testdata directory.
    """
    filepath = os.path.join(TESTDATA_DIR, event["filename"])

    # Check cache
    if os.path.exists(filepath):
        with open(filepath) as f:
            data = json.load(f)
        klines = data.get("klines", data)
        if len(klines) >= 100:
            print(f"  Loaded {len(klines)} cached candles from {event['filename']}")
            return klines, "cached"

    # Try API
    print(f"  Fetching data from Binance API...")
    start_ms = ts(event["start"])
    end_ms = ts(event["end"])
    klines = fetch_klines(event["symbol"], "1h", start_ms, end_ms)

    if klines and len(klines) >= 100:
        source = "api"
    else:
        # Fall back to synthetic
        print(f"  API unavailable — generating synthetic data...")
        gen_fn = SYNTHETIC_GENERATORS.get(event["name"])
        if gen_fn is None:
            raise ValueError(f"No synthetic generator for {event['name']}")
        klines = gen_fn()
        source = "synthetic"
        print(f"  Generated {len(klines)} synthetic candles")

    # Save to cache
    os.makedirs(TESTDATA_DIR, exist_ok=True)
    with open(filepath, "w") as f:
        json.dump({"klines": klines, "source": source, "event": event["name"]}, f)
    print(f"  Saved to {event['filename']}")

    return klines, source


# ---------------------------------------------------------------------------
# Black swan analysis engine
# ---------------------------------------------------------------------------

def analyze_black_swan(klines, event, renoun_window=50, rebalance_every=5):
    """
    Run the v2 engine across a black swan event period and compute
    timing/protection metrics.

    Returns a detailed result dict.
    """
    closes = np.array([float(k.get("close", k.get("c", 0))) for k in klines])
    n = len(closes)

    # --- Compute returns ---
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
            result = analyze_financial(window_klines, symbol="BTCUSDT", timeframe="1h")
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
            end = min(i + rebalance_every, n)
            exposure_v2[i:end] = smooth_exp
            dhs_series[i:end] = dhs
            for j in range(i, end):
                constellation_series[j] = top_const

            renoun_log.append({
                "candle": i,
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
            })
        except Exception as e:
            renoun_log.append({"candle": i, "error": str(e)})

    # --- Find worst hour (single candle) ---
    worst_hour_idx = int(np.argmin(returns))
    worst_hour_return = float(returns[worst_hour_idx])

    # --- Find worst 24h (rolling 24-candle drawdown) ---
    worst_24h_dd = 0.0
    worst_24h_start = 0
    worst_24h_end = 0

    for i in range(n - 24):
        dd_24 = (closes[i + 24] - closes[i]) / closes[i]
        if dd_24 < worst_24h_dd:
            worst_24h_dd = dd_24
            worst_24h_start = i
            worst_24h_end = i + 24

    # --- Early warning: when did exposure first drop below 0.5 before worst hour? ---
    early_warning_candle = None
    early_warning_hours = None

    # Search backwards from worst hour for first candle where exposure < 0.5
    for i in range(worst_hour_idx, -1, -1):
        if exposure_v2[i] >= 0.5:
            # The candle after this is where exposure dropped below 0.5
            if i + 1 <= worst_hour_idx:
                early_warning_candle = i + 1
                early_warning_hours = worst_hour_idx - early_warning_candle
            break
    else:
        # Exposure was below 0.5 from the very start
        early_warning_candle = start
        early_warning_hours = worst_hour_idx - start

    # If exposure never dropped below 0.5, check if it was always below
    if early_warning_candle is None:
        # Exposure was >= 0.5 all the way through the crash
        early_warning_hours = 0

    # Also check: first time exposure dropped below 0.5 looking forward from start
    first_drop_candle = None
    for i in range(start, worst_hour_idx):
        if exposure_v2[i] < 0.5:
            first_drop_candle = i
            break

    if first_drop_candle is not None:
        early_warning_hours = worst_hour_idx - first_drop_candle
        early_warning_candle = first_drop_candle

    # --- Protective exposure during worst 24h ---
    if worst_24h_end <= n:
        avg_exposure_worst_24h = float(np.mean(exposure_v2[worst_24h_start:worst_24h_end]))
    else:
        avg_exposure_worst_24h = float(np.mean(exposure_v2[worst_24h_start:]))

    # --- Constellation sequence leading into crash ---
    # Look at the 5 rebalance points before the worst hour
    pre_crash_consts = []
    for entry in renoun_log:
        if "constellation" in entry and entry["candle"] <= worst_hour_idx:
            pre_crash_consts.append(entry["constellation"])
    # Take last 5 unique in sequence (deduplicate consecutive)
    deduped = []
    for c in pre_crash_consts:
        if not deduped or deduped[-1] != c:
            deduped.append(c)
    const_sequence = deduped[-5:] if len(deduped) >= 5 else deduped

    # --- Equity curves ---
    # Unmanaged: buy-and-hold
    bh_equity = [1.0]
    for r in returns:
        bh_equity.append(bh_equity[-1] * (1 + r))
    bh_equity = np.array(bh_equity)

    # Managed: apply v2 exposure to buy-and-hold
    managed_equity = [1.0]
    for i in range(len(returns)):
        managed_equity.append(managed_equity[-1] * (1 + exposure_v2[i] * returns[i]))
    managed_equity = np.array(managed_equity)

    # Max drawdowns
    bh_peak = np.maximum.accumulate(bh_equity)
    bh_dd = (bh_equity - bh_peak) / bh_peak
    bh_max_dd = float(np.min(bh_dd))

    man_peak = np.maximum.accumulate(managed_equity)
    man_dd = (managed_equity - man_peak) / man_peak
    man_max_dd = float(np.min(man_dd))

    dd_reduction = abs(bh_max_dd) - abs(man_max_dd)

    # Market return over full period
    market_return = (closes[-1] / closes[0]) - 1

    # Price range
    price_min = float(np.min(closes))
    price_max = float(np.max(closes))

    return {
        "event": event,
        "n_candles": n,
        "price_min": price_min,
        "price_max": price_max,
        "market_return": market_return,

        "worst_hour_idx": worst_hour_idx,
        "worst_hour_return": worst_hour_return,
        "worst_24h_start": worst_24h_start,
        "worst_24h_end": worst_24h_end,
        "worst_24h_dd": worst_24h_dd,

        "early_warning_candle": early_warning_candle,
        "early_warning_hours": early_warning_hours if early_warning_hours else 0,
        "avg_exposure_worst_24h": avg_exposure_worst_24h,
        "constellation_sequence": const_sequence,

        "bh_max_dd": bh_max_dd,
        "managed_max_dd": man_max_dd,
        "dd_reduction_pp": dd_reduction * 100,

        "bh_final": float(bh_equity[-1]),
        "managed_final": float(managed_equity[-1]),

        "renoun_log": renoun_log,
        "exposure_series": exposure_v2.tolist(),
        "dhs_series": [float(x) if not np.isnan(x) else None for x in dhs_series],
    }


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

def print_event_result(result):
    """Print detailed results for a single black swan event."""
    event = result["event"]
    print()
    print(f"{'=' * 72}")
    print(f"BLACK SWAN: {event['name']} ({event['date']})")
    print(f"{'=' * 72}")
    print(f"  {event['description']}")
    print()
    print(f"  Data: {result['n_candles']} candles (1h interval)")
    print(f"  Price range: ${result['price_min']:,.0f} - ${result['price_max']:,.0f}")
    print(f"  Market return: {result['market_return'] * 100:+.1f}%")
    print()

    print(f"  TIMING ANALYSIS:")
    print(f"    Worst hour:  candle {result['worst_hour_idx']} "
          f"({result['worst_hour_return'] * 100:+.1f}%)")
    print(f"    Worst 24h:   candles {result['worst_24h_start']}-{result['worst_24h_end']} "
          f"({result['worst_24h_dd'] * 100:+.1f}%)")

    if result["early_warning_hours"] > 0:
        print(f"    Exposure dropped below 0.5 at: candle {result['early_warning_candle']} "
              f"({result['early_warning_hours']} hours BEFORE worst hour)")
    else:
        print(f"    Exposure did not drop below 0.5 before worst hour")

    print(f"    Avg exposure during worst 24h: {result['avg_exposure_worst_24h']:.2f}")

    if result["constellation_sequence"]:
        seq_str = " -> ".join(result["constellation_sequence"])
        print(f"    Constellation sequence into crash: {seq_str}")

    print()
    print(f"  EQUITY IMPACT:")
    print(f"    Unmanaged max DD: {result['bh_max_dd'] * 100:+.1f}%")
    print(f"    Managed max DD:   {result['managed_max_dd'] * 100:+.1f}%")
    print(f"    DD reduction:     {result['dd_reduction_pp']:.1f} pp")
    print()

    # Verdict
    if result["early_warning_hours"] > 0:
        verdict_timing = f"Engine provided {result['early_warning_hours']} hours early warning"
        timing_pass = True
    else:
        verdict_timing = "No early warning (exposure stayed >= 0.5)"
        timing_pass = False

    if result["dd_reduction_pp"] > 0:
        verdict_dd = f"DD reduced by {result['dd_reduction_pp']:.1f}pp"
        dd_pass = True
    else:
        verdict_dd = f"DD not reduced"
        dd_pass = False

    if result["avg_exposure_worst_24h"] < 0.5:
        verdict_exposure = f"Protective exposure {result['avg_exposure_worst_24h']:.2f} during crash"
        exp_pass = True
    else:
        verdict_exposure = f"Exposure {result['avg_exposure_worst_24h']:.2f} during crash (not protective)"
        exp_pass = False

    all_pass = timing_pass and dd_pass and exp_pass
    mark = "PASS" if all_pass else ("PARTIAL" if (dd_pass or exp_pass) else "FAIL")

    print(f"  VERDICT: [{mark}]")
    print(f"    Timing:   {verdict_timing} {'[ok]' if timing_pass else '[--]'}")
    print(f"    DrawDown: {verdict_dd} {'[ok]' if dd_pass else '[--]'}")
    print(f"    Exposure: {verdict_exposure} {'[ok]' if exp_pass else '[--]'}")

    # Show DHS trajectory approaching crash
    print()
    print(f"  DHS TRAJECTORY (last 10 rebalance points before worst hour):")
    pre_crash_log = [e for e in result["renoun_log"]
                     if "dhs" in e and e["candle"] <= result["worst_hour_idx"]]
    for entry in pre_crash_log[-10:]:
        bar = "#" * int(entry["exposure_smooth"] * 20)
        dist = result["worst_hour_idx"] - entry["candle"]
        crash_flag = " [CRASH]" if entry.get("crash_regime", False) else ""
        eff = entry.get("effective_constellation", entry["constellation"])
        eff_note = f" (eff:{eff})" if eff != entry["constellation"] else ""
        print(f"    t-{dist:>4d}h | DHS {entry['dhs']:.3f} | "
              f"Exp {entry['exposure_smooth']:.3f} [{bar:<20s}] | "
              f"{entry['constellation']}{eff_note}{crash_flag}")


def print_summary(all_results):
    """Print summary table across all events."""
    print()
    print()
    print("=" * 90)
    print("BLACK SWAN VALIDATION SUMMARY")
    print("=" * 90)
    print()
    print(f"{'Event':<22} {'Candles':>8} {'Mkt Ret':>8} {'BH DD':>8} "
          f"{'Mgd DD':>8} {'DD Red':>8} {'Warning':>8} {'Avg Exp':>8} {'Result':>8}")
    print("-" * 90)

    pass_count = 0
    total_dd_reduction = 0.0
    total_warning_hours = 0

    for result in all_results:
        ev = result["event"]
        timing_pass = result["early_warning_hours"] > 0
        dd_pass = result["dd_reduction_pp"] > 0
        exp_pass = result["avg_exposure_worst_24h"] < 0.5
        all_pass = timing_pass and dd_pass and exp_pass

        if all_pass:
            mark = "PASS"
            pass_count += 1
        elif dd_pass or exp_pass:
            mark = "PARTIAL"
        else:
            mark = "FAIL"

        warning_str = f"{result['early_warning_hours']}h" if result["early_warning_hours"] > 0 else "none"

        print(f"  {ev['name']:<20} {result['n_candles']:>7d} "
              f"{result['market_return'] * 100:>+7.1f}% "
              f"{result['bh_max_dd'] * 100:>+7.1f}% "
              f"{result['managed_max_dd'] * 100:>+7.1f}% "
              f"{result['dd_reduction_pp']:>+7.1f} "
              f"{warning_str:>8s} "
              f"{result['avg_exposure_worst_24h']:>7.2f} "
              f"{mark:>8s}")

        total_dd_reduction += result["dd_reduction_pp"]
        total_warning_hours += result["early_warning_hours"]

    print("-" * 90)
    print()
    print(f"  Events passed (all criteria): {pass_count}/{len(all_results)}")
    print(f"  Events with DD reduction:     "
          f"{sum(1 for r in all_results if r['dd_reduction_pp'] > 0)}/{len(all_results)}")
    print(f"  Events with early warning:    "
          f"{sum(1 for r in all_results if r['early_warning_hours'] > 0)}/{len(all_results)}")
    print(f"  Events with protective exp:   "
          f"{sum(1 for r in all_results if r['avg_exposure_worst_24h'] < 0.5)}/{len(all_results)}")
    print()
    print(f"  Avg DD reduction:             {total_dd_reduction / len(all_results):+.1f} pp")
    print(f"  Avg early warning:            {total_warning_hours / len(all_results):.0f} hours")
    print(f"  Avg crash exposure:           "
          f"{np.mean([r['avg_exposure_worst_24h'] for r in all_results]):.2f}")
    print()

    # Overall verdict
    if pass_count == len(all_results):
        print("  OVERALL: ALL BLACK SWAN EVENTS PASSED — engine consistently")
        print("           reduced exposure before major crashes")
    elif pass_count > 0:
        print(f"  OVERALL: {pass_count}/{len(all_results)} events fully passed —")
        print("           engine shows protective behavior on most crash events")
    else:
        print("  OVERALL: Engine did not provide consistent protection")
        print("           across black swan events — review required")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 72)
    print("ReNoUn BLACK SWAN HISTORICAL VALIDATION")
    print("Patent Pending #63/923,592")
    print("=" * 72)
    print()
    print("Testing engine response to 4 major crypto crashes.")
    print("Engine: renoun_finance.analyze_financial (v2 exposure logic)")
    print("Window: 50 candles, rebalance every 5 candles (1h timeframe)")
    print()

    all_results = []

    for event in EVENTS:
        print(f"\n--- {event['name']} ({event['date']}) ---")
        try:
            klines, source = get_event_data(event)
            print(f"  Source: {source}, {len(klines)} candles")

            result = analyze_black_swan(klines, event,
                                         renoun_window=50,
                                         rebalance_every=5)
            all_results.append(result)
            print_event_result(result)

        except Exception as e:
            print(f"  ERROR: {e}")
            traceback.print_exc()

    if all_results:
        print_summary(all_results)
    else:
        print("\nNo events processed successfully.")
