"""
Binance public market data client.

Fetches OHLCV klines from Binance's public API (no auth required).
Extracted from signal_bot for use by the API server in production.
"""

from typing import Dict, List

import requests

BINANCE_BASE = "https://data-api.binance.vision"
KLINES_ENDPOINT = "/api/v3/klines"


def fetch_klines(symbol: str, interval: str = "1h", limit: int = 100) -> List[Dict]:
    """
    Fetch OHLCV klines from Binance public API.
    Returns list of dicts compatible with ReNoUn finance engine.
    """
    url = f"{BINANCE_BASE}{KLINES_ENDPOINT}"
    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": limit,
    }

    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        raw = resp.json()
    except requests.RequestException as e:
        print(f"  ERROR fetching {symbol}: {e}")
        return []

    klines = []
    for k in raw:
        klines.append({
            "timestamp": k[0] / 1000,
            "open": float(k[1]),
            "high": float(k[2]),
            "low": float(k[3]),
            "close": float(k[4]),
            "volume": float(k[5]),
            "taker_buy_volume": float(k[9]),
        })

    return klines
