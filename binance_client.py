"""
Binance public market data client.

Fetches OHLCV klines from Binance's public API (no auth required).
Extracted from signal_bot for use by the API server in production.
"""

import logging
from typing import Dict, List

import requests

logger = logging.getLogger("renoun.binance")

BINANCE_ENDPOINTS = [
    "https://data-api.binance.vision", # Data API — works from US/Railway IPs
    "https://api.binance.com",         # Global (451 from US IPs)
    "https://api1.binance.com",        # Backup 1 (451 from US IPs)
    "https://api2.binance.com",        # Backup 2 (451 from US IPs)
]
KLINES_PATH = "/api/v3/klines"

HEADERS = {"User-Agent": "ReNoUn/1.0"}


def fetch_klines(symbol: str, interval: str = "1h", limit: int = 100) -> List[Dict]:
    """
    Fetch OHLCV klines from Binance public API.
    Tries multiple endpoints with fallback.
    Returns list of dicts compatible with ReNoUn finance engine.
    """
    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": limit,
    }

    last_error = None
    for base in BINANCE_ENDPOINTS:
        url = f"{base}{KLINES_PATH}"
        try:
            resp = requests.get(url, params=params, timeout=15, headers=HEADERS)
            resp.raise_for_status()
            raw = resp.json()
            logger.info(f"Binance fetch OK: {base} for {symbol} ({len(raw)} klines)")
            break
        except requests.RequestException as e:
            last_error = e
            logger.warning(f"Binance endpoint failed: {base} — {e}")
            continue
    else:
        # All endpoints failed
        logger.error(f"All Binance endpoints failed for {symbol}: {last_error}")
        return []

    # Binance kline format:
    # [open_time, open, high, low, close, volume, close_time,
    #  quote_volume, trades, taker_buy_base_vol, taker_buy_quote_vol, ignore]
    klines = []
    for k in raw:
        klines.append({
            "timestamp": k[0] / 1000,  # ms → seconds
            "open": float(k[1]),
            "high": float(k[2]),
            "low": float(k[3]),
            "close": float(k[4]),
            "volume": float(k[5]),
            "taker_buy_volume": float(k[9]),
        })

    return klines
