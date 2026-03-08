"""
ReNoUn Live Streaming Monitor

Connects to Binance US websocket for real-time kline data, runs ReNoUn
structural analysis on a rolling window, and logs exposure decisions.

This provides genuine out-of-sample validation — the engine sees data
it has never been tuned on, in real time.

Usage:
    python renoun_stream.py                          # BTC 1m, 50-candle window
    python renoun_stream.py --symbol ETHUSDT --tf 1m
    python renoun_stream.py --symbol BTCUSDT --tf 5m --window 100
    python renoun_stream.py --symbols BTCUSDT,ETHUSDT,SOLUSDT  # multi-asset

Output:
    - Real-time DHS, constellation, exposure decisions
    - Rolling log saved to finance/stream_logs/<symbol>_<tf>_<timestamp>.jsonl
    - Summary stats printed on Ctrl+C
"""

import argparse
import json
import os
import signal
import sys
import time
from collections import deque
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from renoun_finance import analyze_financial

# Try websocket imports — fall back to REST polling if not available
try:
    import websocket
    HAS_WS = True
except ImportError:
    HAS_WS = False

try:
    import urllib.request
    HAS_HTTP = True
except ImportError:
    HAS_HTTP = False


# ---------------------------------------------------------------------------
# Exposure logic (same as backtest v2)
# ---------------------------------------------------------------------------

class ConstellationTracker:
    def __init__(self):
        self.history = []
        self.current = None
        self.run_length = 0

    def update(self, constellation):
        self.history.append(constellation)
        if constellation == self.current:
            self.run_length += 1
        else:
            self.current = constellation
            self.run_length = 1

        if self.run_length >= 3:
            persistence_mult = 1.0
        elif self.run_length == 2:
            persistence_mult = 0.8
        else:
            persistence_mult = 0.5

        recent = self.history[-5:]
        churn = len(set(recent)) / max(len(recent), 1)

        return {
            "persistence_mult": persistence_mult,
            "run_length": self.run_length,
            "churn": round(churn, 2),
        }


def smooth_exposure(raw_exp, prev_smooth, alpha_down=0.6, alpha_up=0.3):
    alpha = alpha_down if raw_exp < prev_smooth else alpha_up
    return alpha * raw_exp + (1 - alpha) * prev_smooth


def dhs_to_exposure(dhs, constellation, loop, dd_stress=0.0, vol_stress=0.0,
                    persistence_mult=1.0):
    if dhs >= 0.80:
        base = 1.0
    elif dhs >= 0.65:
        base = 0.5 + (dhs - 0.65) / 0.15 * 0.5
    elif dhs >= 0.50:
        base = 0.25 + (dhs - 0.50) / 0.15 * 0.25
    elif dhs >= 0.35:
        base = 0.1
    else:
        base = 0.0

    mods = {
        "CONVERGENCE": 0.0, "HIGH_SYMMETRY": -0.05, "DIP_AND_RECOVERY": 0.0,
        "SURFACE_VARIATION": -0.1, "CLOSED_LOOP": -0.1, "PATTERN_BREAK": -0.2,
        "REPEATED_DISRUPTION": -0.25, "SCATTERING": -0.4,
    }
    mod = mods.get(constellation, 0.0) * persistence_mult

    if loop > 0.5:
        mod -= 0.05
    if dd_stress > 0.5:
        mod -= 0.3
    elif dd_stress > 0.3:
        mod -= 0.15
    elif dd_stress > 0.1:
        mod -= 0.05
    if vol_stress > 0.3:
        mod -= 0.15
    elif vol_stress > 0.15:
        mod -= 0.05

    return max(0.0, min(1.0, base + mod))


# ---------------------------------------------------------------------------
# Stream monitor
# ---------------------------------------------------------------------------

class ReNoUnStreamMonitor:
    def __init__(self, symbol, timeframe, window_size, rebalance_every, log_dir):
        self.symbol = symbol.upper()
        self.timeframe = timeframe
        self.window_size = window_size
        self.rebalance_every = rebalance_every
        self.log_dir = log_dir

        self.buffer = deque(maxlen=window_size + 50)  # extra room
        self.candle_count = 0
        self.tracker = ConstellationTracker()
        self.prev_smooth_exp = 1.0
        self.decisions = []
        self.start_time = datetime.now(timezone.utc)

        # Log file
        os.makedirs(log_dir, exist_ok=True)
        ts = self.start_time.strftime("%Y%m%d_%H%M%S")
        self.log_path = os.path.join(log_dir, f"{self.symbol}_{timeframe}_{ts}.jsonl")
        self.log_file = open(self.log_path, "w")

        print(f"[ReNoUn Stream] {self.symbol} {timeframe}")
        print(f"  Window: {window_size} candles, rebalance every {rebalance_every}")
        print(f"  Log: {self.log_path}")
        print(f"  Waiting for {window_size} candles to fill buffer...")
        print()

    def add_candle(self, kline):
        """Add a completed candle and maybe run analysis."""
        self.buffer.append(kline)
        self.candle_count += 1

        # Only analyze when we have enough data and it's a rebalance point
        if len(self.buffer) < self.window_size:
            if self.candle_count % 10 == 0:
                sys.stdout.write(f"\r  Buffering: {len(self.buffer)}/{self.window_size} candles")
                sys.stdout.flush()
            return

        if self.candle_count % self.rebalance_every != 0:
            return

        # Run analysis on trailing window
        window = list(self.buffer)[-self.window_size:]
        try:
            result = analyze_financial(window, symbol=self.symbol, timeframe=self.timeframe)

            dhs = result["dialectical_health"]
            top_const = result["constellations"][0]["detected"] if result["constellations"] else "NONE"
            loop = result["loop_strength"]
            dd_stress = result.get("stress", {}).get("drawdown", 0.0)
            vol_stress = float(result.get("stress", {}).get("vol_expansion", 0.0))

            persist = self.tracker.update(top_const)
            raw_exp = dhs_to_exposure(dhs, top_const, loop, dd_stress, vol_stress,
                                       persistence_mult=persist["persistence_mult"])
            smooth_exp = smooth_exposure(raw_exp, self.prev_smooth_exp)
            self.prev_smooth_exp = smooth_exp

            close = float(window[-1].get("close", window[-1].get("c", 0)))

            decision = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "candle": self.candle_count,
                "price": close,
                "dhs": round(dhs, 3),
                "constellation": top_const,
                "loop": round(loop, 3),
                "dd_stress": round(dd_stress, 4),
                "vol_stress": round(vol_stress, 4),
                "exposure_raw": round(raw_exp, 3),
                "exposure_smooth": round(smooth_exp, 3),
                "run_length": persist["run_length"],
                "churn": persist["churn"],
            }
            self.decisions.append(decision)

            # Write to log
            self.log_file.write(json.dumps(decision) + "\n")
            self.log_file.flush()

            # Print live
            bar = "█" * int(smooth_exp * 20) + "░" * (20 - int(smooth_exp * 20))
            stress = ""
            if dd_stress > 0.1:
                stress += f" DD={dd_stress:.2f}"
            if vol_stress > 0.1:
                stress += f" VOL={vol_stress:.2f}"

            # Color-code DHS
            if dhs >= 0.65:
                dhs_fmt = f"\033[92m{dhs:.3f}\033[0m"  # green
            elif dhs >= 0.45:
                dhs_fmt = f"\033[93m{dhs:.3f}\033[0m"  # yellow
            else:
                dhs_fmt = f"\033[91m{dhs:.3f}\033[0m"  # red

            print(f"  [{self.candle_count:5d}] {close:>10.2f}  DHS={dhs_fmt}  "
                  f"{top_const:<22} exp={smooth_exp:.2f} {bar}{stress}")

        except Exception as e:
            print(f"  [{self.candle_count:5d}] ERROR: {e}")

    def summary(self):
        """Print session summary."""
        if not self.decisions:
            print("\n  No decisions recorded.")
            return

        import numpy as np
        dhs_vals = [d["dhs"] for d in self.decisions]
        exp_vals = [d["exposure_smooth"] for d in self.decisions]
        consts = [d["constellation"] for d in self.decisions]

        from collections import Counter
        const_dist = Counter(consts)

        duration = (datetime.now(timezone.utc) - self.start_time).total_seconds()

        print(f"\n{'='*60}")
        print(f"SESSION SUMMARY — {self.symbol} {self.timeframe}")
        print(f"{'='*60}")
        print(f"  Duration: {duration/60:.1f} minutes ({self.candle_count} candles)")
        print(f"  Decisions: {len(self.decisions)}")
        print(f"  DHS:  mean={np.mean(dhs_vals):.3f}  min={np.min(dhs_vals):.3f}  max={np.max(dhs_vals):.3f}")
        print(f"  Exp:  mean={np.mean(exp_vals):.2f}  min={np.min(exp_vals):.2f}  max={np.max(exp_vals):.2f}")
        print(f"  Constellations:")
        for c, cnt in const_dist.most_common():
            pct = cnt / len(consts) * 100
            print(f"    {c:<22} {cnt:>3} ({pct:.0f}%)")
        print(f"\n  Log saved: {self.log_path}")

    def close(self):
        self.log_file.close()


# ---------------------------------------------------------------------------
# Data sources
# ---------------------------------------------------------------------------

def poll_binance_klines(symbol, interval, limit=1):
    """Fetch the latest closed klines from Binance US REST API."""
    url = f"https://api.binance.us/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    req = urllib.request.Request(url, headers={"User-Agent": "ReNoUn-Stream/1.0"})
    resp = urllib.request.urlopen(req, timeout=10)
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


def seed_buffer(symbol, interval, count):
    """Pre-fill buffer with historical candles."""
    print(f"  Seeding buffer with {count} historical candles...")
    return poll_binance_klines(symbol, interval, limit=count)


# ---------------------------------------------------------------------------
# Polling mode (no websocket dependency)
# ---------------------------------------------------------------------------

def run_polling(monitor, interval_seconds):
    """
    Poll Binance REST API for new candles. Simpler than websocket,
    works without extra dependencies.
    """
    print(f"  Polling mode: checking every {interval_seconds}s")
    print(f"  Press Ctrl+C to stop and see summary.\n")

    last_close_time = None

    # Seed buffer with extra candles so first analysis triggers immediately
    seed_count = monitor.window_size + monitor.rebalance_every
    seed = seed_buffer(monitor.symbol, monitor.timeframe, seed_count)
    for k in seed[:-1]:  # skip the last (still open) candle
        monitor.add_candle(k)
    if seed:
        last_close_time = seed[-2]["closeTime"] if len(seed) > 1 else None
    print()

    try:
        while True:
            time.sleep(interval_seconds)
            try:
                klines = poll_binance_klines(monitor.symbol, monitor.timeframe, limit=2)
                for k in klines:
                    # Only process candles that have closed
                    if last_close_time is not None and k["closeTime"] <= last_close_time:
                        continue
                    # Check if candle is closed (closeTime is in the past)
                    now_ms = int(time.time() * 1000)
                    if k["closeTime"] < now_ms:
                        monitor.add_candle(k)
                        last_close_time = k["closeTime"]
            except Exception as e:
                print(f"  [poll error] {e}")

    except KeyboardInterrupt:
        pass


# ---------------------------------------------------------------------------
# Websocket mode
# ---------------------------------------------------------------------------

def run_websocket(monitor):
    """Connect to Binance US kline websocket stream."""
    stream = f"{monitor.symbol.lower()}@kline_{monitor.timeframe}"
    url = f"wss://stream.binance.us:9443/ws/{stream}"

    print(f"  WebSocket: {url}")
    print(f"  Press Ctrl+C to stop and see summary.\n")

    # Seed buffer with extra candles so we get an immediate first analysis
    seed_count = monitor.window_size + monitor.rebalance_every
    seed = seed_buffer(monitor.symbol, monitor.timeframe, seed_count)
    for k in seed[:-1]:  # skip last (still open)
        monitor.add_candle(k)
    print()

    def on_message(ws, message):
        data = json.loads(message)
        k = data.get("k", {})
        if k.get("x"):  # candle closed
            kline = {
                "openTime": k["t"], "open": float(k["o"]), "high": float(k["h"]),
                "low": float(k["l"]), "close": float(k["c"]), "volume": float(k["v"]),
                "closeTime": k["T"], "quoteVolume": float(k["q"]), "trades": k["n"],
                "takerBuyVolume": float(k["V"]), "takerBuyQuoteVolume": float(k["Q"])
            }
            monitor.add_candle(kline)

    def on_error(ws, error):
        print(f"  [ws error] {error}")

    def on_close(ws, close_status, close_msg):
        print(f"  [ws closed] {close_status} {close_msg}")

    def on_open(ws):
        print(f"  [ws connected] Listening for {monitor.symbol} {monitor.timeframe}...")

    ws = websocket.WebSocketApp(url,
                                 on_message=on_message,
                                 on_error=on_error,
                                 on_close=on_close,
                                 on_open=on_open)

    try:
        ws.run_forever()
    except KeyboardInterrupt:
        ws.close()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

INTERVAL_SECONDS = {
    "1m": 15,   # poll every 15s for 1m candles
    "3m": 30,
    "5m": 60,
    "15m": 120,
    "1h": 300,
    "4h": 600,
}


def main():
    parser = argparse.ArgumentParser(description="ReNoUn Live Stream Monitor")
    parser.add_argument("--symbol", default="BTCUSDT", help="Trading pair (default: BTCUSDT)")
    parser.add_argument("--symbols", default=None, help="Comma-separated pairs for multi-asset mode")
    parser.add_argument("--tf", default="1m", help="Timeframe (default: 1m)")
    parser.add_argument("--window", type=int, default=50, help="Analysis window size (default: 50)")
    parser.add_argument("--rebalance", type=int, default=5, help="Rebalance every N candles (default: 5)")
    parser.add_argument("--mode", choices=["poll", "ws"], default="poll",
                        help="Data mode: poll (REST) or ws (WebSocket, needs websocket-client)")
    parser.add_argument("--log-dir", default=None, help="Log directory (default: finance/stream_logs)")
    args = parser.parse_args()

    log_dir = args.log_dir or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "finance", "stream_logs"
    )

    symbols = args.symbols.split(",") if args.symbols else [args.symbol]

    if len(symbols) == 1:
        # Single-asset mode
        monitor = ReNoUnStreamMonitor(
            symbol=symbols[0],
            timeframe=args.tf,
            window_size=args.window,
            rebalance_every=args.rebalance,
            log_dir=log_dir,
        )

        def handle_sigint(sig, frame):
            monitor.summary()
            monitor.close()
            sys.exit(0)
        signal.signal(signal.SIGINT, handle_sigint)

        if args.mode == "ws" and HAS_WS:
            run_websocket(monitor)
        elif args.mode == "ws" and not HAS_WS:
            print("  websocket-client not installed. Falling back to polling mode.")
            print("  Install with: pip install websocket-client")
            poll_interval = INTERVAL_SECONDS.get(args.tf, 60)
            run_polling(monitor, poll_interval)
        else:
            poll_interval = INTERVAL_SECONDS.get(args.tf, 60)
            run_polling(monitor, poll_interval)

        monitor.summary()
        monitor.close()

    else:
        # Multi-asset mode — run monitors sequentially on seed data
        # (true parallel would need threads, keep it simple for now)
        print(f"Multi-asset snapshot mode: {', '.join(symbols)}")
        print(f"Seeding {args.window} candles per asset and running analysis...\n")

        for sym in symbols:
            monitor = ReNoUnStreamMonitor(
                symbol=sym.strip(),
                timeframe=args.tf,
                window_size=args.window,
                rebalance_every=args.rebalance,
                log_dir=log_dir,
            )

            seed_count = args.window + args.rebalance
            seed = seed_buffer(sym.strip(), args.tf, seed_count)
            for k in seed[:-1]:
                monitor.add_candle(k)
            print()

            monitor.summary()
            monitor.close()
            print()


if __name__ == "__main__":
    main()
