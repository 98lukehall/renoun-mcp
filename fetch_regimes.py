"""
Fetch diverse market regime data for comprehensive engine validation.

Targets specific historical periods with known market conditions:
- Bull runs, crashes, recoveries, choppy sideways
- Multiple assets, multiple timeframes

Uses Binance US API with startTime/endTime to target specific epochs.
"""

import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone

TESTDATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "finance", "testdata")
os.makedirs(TESTDATA, exist_ok=True)


def fetch_klines(symbol, interval, limit=1000, start_time=None, end_time=None):
    """Fetch klines from Binance US."""
    url = f"https://api.binance.us/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    if start_time:
        url += f"&startTime={start_time}"
    if end_time:
        url += f"&endTime={end_time}"

    req = urllib.request.Request(url, headers={"User-Agent": "ReNoUn-Fetch/1.0"})
    resp = urllib.request.urlopen(req, timeout=30)
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


def ts(date_str):
    """Convert 'YYYY-MM-DD' to millisecond timestamp."""
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


# Define market regime periods (approximate dates)
REGIMES = [
    # --- BTC major regimes ---
    {
        "label": "BTC_bull_2024Q1",
        "symbol": "BTCUSDT",
        "interval": "1h",
        "description": "BTC rally from 40k to 73k (Jan-Mar 2024)",
        "start": "2024-01-15",
        "end": "2024-03-15",
    },
    {
        "label": "BTC_crash_apr2024",
        "symbol": "BTCUSDT",
        "interval": "1h",
        "description": "BTC correction from 70k to 56k (Apr-May 2024)",
        "start": "2024-04-01",
        "end": "2024-05-15",
    },
    {
        "label": "BTC_chop_summer2024",
        "symbol": "BTCUSDT",
        "interval": "1h",
        "description": "BTC choppy sideways 55k-70k (Jun-Aug 2024)",
        "start": "2024-06-01",
        "end": "2024-08-15",
    },
    {
        "label": "BTC_rally_Q4_2024",
        "symbol": "BTCUSDT",
        "interval": "1h",
        "description": "BTC rally post-election 65k-100k+ (Oct-Dec 2024)",
        "start": "2024-10-01",
        "end": "2024-12-15",
    },
    {
        "label": "BTC_bull_2024Q1_15m",
        "symbol": "BTCUSDT",
        "interval": "15m",
        "description": "BTC rally 40k-73k at 15m resolution",
        "start": "2024-02-01",
        "end": "2024-02-18",  # ~1000 15m candles = ~10 days
    },
    {
        "label": "BTC_crash_apr2024_15m",
        "symbol": "BTCUSDT",
        "interval": "15m",
        "description": "BTC correction at 15m resolution",
        "start": "2024-04-10",
        "end": "2024-04-22",
    },

    # --- ETH major regimes ---
    {
        "label": "ETH_bull_2024Q1",
        "symbol": "ETHUSDT",
        "interval": "1h",
        "description": "ETH rally 2.2k to 4k (Jan-Mar 2024)",
        "start": "2024-01-15",
        "end": "2024-03-15",
    },
    {
        "label": "ETH_decline_2024H2",
        "symbol": "ETHUSDT",
        "interval": "1h",
        "description": "ETH decline 3.5k to 2.3k (Jul-Sep 2024)",
        "start": "2024-07-01",
        "end": "2024-09-15",
    },

    # --- SOL major regimes ---
    {
        "label": "SOL_bull_2024Q1",
        "symbol": "SOLUSDT",
        "interval": "1h",
        "description": "SOL rally 80 to 200+ (Jan-Mar 2024)",
        "start": "2024-01-15",
        "end": "2024-03-15",
    },
    {
        "label": "SOL_crash_apr2024",
        "symbol": "SOLUSDT",
        "interval": "1h",
        "description": "SOL correction 190 to 120 (Apr-May 2024)",
        "start": "2024-04-01",
        "end": "2024-05-15",
    },

    # --- Daily timeframe (longer periods) ---
    {
        "label": "BTC_2023_full",
        "symbol": "BTCUSDT",
        "interval": "1d",
        "description": "BTC full year 2023 (16k to 42k recovery)",
        "start": "2023-01-01",
        "end": "2023-12-31",
    },
    {
        "label": "BTC_2024_full",
        "symbol": "BTCUSDT",
        "interval": "1d",
        "description": "BTC full year 2024 (42k to 100k+)",
        "start": "2024-01-01",
        "end": "2024-12-31",
    },
    {
        "label": "ETH_2023_full",
        "symbol": "ETHUSDT",
        "interval": "1d",
        "description": "ETH full year 2023 (1.2k to 2.3k)",
        "start": "2023-01-01",
        "end": "2023-12-31",
    },

    # --- 4h timeframe ---
    {
        "label": "BTC_bull_2024Q1_4h",
        "symbol": "BTCUSDT",
        "interval": "4h",
        "description": "BTC rally at 4h resolution (Jan-May 2024)",
        "start": "2024-01-01",
        "end": "2024-05-15",
    },
    {
        "label": "BTC_chop_summer2024_4h",
        "symbol": "BTCUSDT",
        "interval": "4h",
        "description": "BTC choppy at 4h resolution (Jun-Oct 2024)",
        "start": "2024-06-01",
        "end": "2024-10-15",
    },
]


def main():
    print(f"Fetching {len(REGIMES)} market regime datasets...")
    print(f"Saving to: {TESTDATA}\n")

    for r in REGIMES:
        fname = f"{r['label']}_{r['interval']}.json"
        path = os.path.join(TESTDATA, fname)

        if os.path.exists(path):
            print(f"  SKIP {fname} (already exists)")
            continue

        print(f"  Fetching {r['label']} ({r['description']})...")
        try:
            klines = fetch_klines(
                r["symbol"], r["interval"],
                limit=1000,
                start_time=ts(r["start"]),
                end_time=ts(r["end"]),
            )

            if not klines:
                print(f"    WARNING: no data returned")
                continue

            closes = [k["close"] for k in klines]
            total_return = (closes[-1] - closes[0]) / closes[0] * 100
            peak = max(closes)
            trough = min(closes)
            max_dd = (trough - peak) / peak * 100 if peak > 0 else 0

            data = {
                "metadata": {
                    "symbol": r["symbol"],
                    "interval": r["interval"],
                    "description": r["description"],
                    "start": r["start"],
                    "end": r["end"],
                    "n_candles": len(klines),
                    "price_range": f"{min(closes):.2f} - {max(closes):.2f}",
                    "total_return_pct": round(total_return, 2),
                    "approx_max_dd_pct": round(max_dd, 2),
                },
                "klines": klines,
            }

            with open(path, "w") as f:
                json.dump(data, f)

            print(f"    {len(klines)} candles | {min(closes):.2f}-{max(closes):.2f} | "
                  f"return: {total_return:+.1f}% | DD: {max_dd:.1f}%")

            time.sleep(0.5)  # rate limit courtesy

        except Exception as e:
            print(f"    ERROR: {e}")

    print(f"\nDone. Files in {TESTDATA}")

    # List all available datasets
    files = sorted(os.listdir(TESTDATA))
    print(f"\nAll datasets ({len(files)}):")
    for f in files:
        if f.endswith(".json"):
            path = os.path.join(TESTDATA, f)
            with open(path) as fh:
                raw = json.load(fh)
            meta = raw.get("metadata", {})
            n = len(raw.get("klines", raw if isinstance(raw, list) else []))
            desc = meta.get("description", "")
            ret = meta.get("total_return_pct", "?")
            print(f"  {f:<45} {n:>5} candles  {ret:>+8}%  {desc}")


if __name__ == "__main__":
    main()
