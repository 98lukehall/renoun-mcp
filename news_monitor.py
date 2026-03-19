#!/usr/bin/env python3
"""
News-driven structural alert monitor.

Detects abnormal activity in crypto news and volume that may precede
structural regime changes. Runs as a background thread, checking every 60s.

This is NOT sentiment analysis. It's velocity anomaly detection:
- How many news articles in the last 30 minutes vs baseline?
- Is volume spiking without structural degradation?
- Are normally-stable assets suddenly trending?

The flag supplements structural analysis — it doesn't replace it.

Patent Pending #63/923,592
"""

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Optional

import requests

logger = logging.getLogger("renoun.news_monitor")


@dataclass
class NewsAlert:
    """Alert state for a single asset."""
    level: str = "none"              # "none" | "elevated" | "extreme"
    activity_score: float = 0.0      # 0.0-1.0 composite
    volume_spike: float = 1.0        # Current volume vs 30min avg (1.0 = normal)
    news_velocity: float = 0.0       # Articles per 30min
    trending: bool = False           # Appeared in trending unexpectedly
    last_checked: Optional[str] = None  # ISO timestamp
    sources_checked: int = 0         # How many sources responded
    detail: str = ""                 # Human-readable summary


class NewsAlertCache:
    """Thread-safe in-memory cache for news alerts."""

    def __init__(self):
        self._alerts: Dict[str, NewsAlert] = {}
        self._lock = threading.Lock()

    def set(self, symbol: str, alert: NewsAlert):
        with self._lock:
            self._alerts[symbol] = alert

    def get(self, symbol: str) -> NewsAlert:
        with self._lock:
            return self._alerts.get(symbol, NewsAlert())

    def get_all(self) -> Dict[str, NewsAlert]:
        with self._lock:
            return dict(self._alerts)


# Module-level singleton
news_cache = NewsAlertCache()


# ── Data Source Checkers ────────────────────────────────────────────

# Map Binance symbols to CoinGecko/CryptoCompare identifiers
ASSET_MAP = {
    "BTCUSDT": {"coingecko": "bitcoin", "cc": "BTC", "display": "BTC"},
    "ETHUSDT": {"coingecko": "ethereum", "cc": "ETH", "display": "ETH"},
    "SOLUSDT": {"coingecko": "solana", "cc": "SOL", "display": "SOL"},
    "XRPUSDT": {"coingecko": "ripple", "cc": "XRP", "display": "XRP"},
    "DOGEUSDT": {"coingecko": "dogecoin", "cc": "DOGE", "display": "DOGE"},
}

# Normal baselines (articles per 30 minutes during quiet periods)
NEWS_BASELINE = {
    "BTC": 3.0,
    "ETH": 2.0,
    "SOL": 1.0,
    "XRP": 1.0,
    "DOGE": 0.5,
}

HEADERS = {"User-Agent": "ReNoUn/1.0"}


def check_volume_spike(symbol: str) -> float:
    """
    Compare last 5 minutes of volume against 30-minute rolling average.
    Returns ratio (1.0 = normal, 3.0 = 3x normal volume).
    """
    try:
        from binance_client import BINANCE_ENDPOINTS, KLINES_PATH

        params = {"symbol": symbol, "interval": "1m", "limit": 30}

        for base in BINANCE_ENDPOINTS:
            try:
                resp = requests.get(
                    f"{base}{KLINES_PATH}",
                    params=params, timeout=5, headers=HEADERS
                )
                resp.raise_for_status()
                raw = resp.json()
                break
            except requests.RequestException:
                continue
        else:
            return 1.0

        if len(raw) < 10:
            return 1.0

        volumes = [float(k[5]) for k in raw]
        avg_30m = sum(volumes) / len(volumes)
        avg_5m = sum(volumes[-5:]) / 5

        if avg_30m == 0:
            return 1.0

        return avg_5m / avg_30m

    except Exception as e:
        logger.debug(f"Volume check failed for {symbol}: {e}")
        return 1.0


def check_news_velocity(cc_symbol: str) -> float:
    """
    Check CryptoCompare for recent news article count.
    Returns articles in last 30 minutes.
    """
    try:
        resp = requests.get(
            "https://min-api.cryptocompare.com/data/v2/news/",
            params={"lang": "EN", "categories": cc_symbol},
            timeout=5,
            headers=HEADERS,
        )
        resp.raise_for_status()
        data = resp.json()

        articles = data.get("Data", [])
        now = time.time()
        thirty_min_ago = now - (30 * 60)

        recent_count = sum(
            1 for a in articles
            if a.get("published_on", 0) >= thirty_min_ago
        )
        return float(recent_count)

    except Exception as e:
        logger.debug(f"News velocity check failed for {cc_symbol}: {e}")
        return 0.0


def check_trending(coingecko_id: str) -> bool:
    """
    Check if an asset is in CoinGecko's trending list.
    BTC/ETH in trending is unusual and signals something is happening.
    """
    try:
        resp = requests.get(
            "https://api.coingecko.com/api/v3/search/trending",
            timeout=5,
            headers=HEADERS,
        )
        resp.raise_for_status()
        data = resp.json()

        trending_ids = [
            coin.get("item", {}).get("id", "")
            for coin in data.get("coins", [])
        ]
        return coingecko_id in trending_ids

    except Exception as e:
        logger.debug(f"Trending check failed: {e}")
        return False


# ── Alert Computation ───────────────────────────────────────────────

def compute_alert(symbol: str) -> NewsAlert:
    """Run all checks for a symbol and compute composite alert."""
    asset_info = ASSET_MAP.get(symbol)
    if not asset_info:
        return NewsAlert()

    cc_symbol = asset_info["cc"]
    cg_id = asset_info["coingecko"]
    display = asset_info["display"]

    sources_ok = 0

    # Check 1: Volume spike
    vol_spike = check_volume_spike(symbol)
    if vol_spike != 1.0:
        sources_ok += 1

    # Check 2: News velocity
    news_vel = check_news_velocity(cc_symbol)
    baseline = NEWS_BASELINE.get(cc_symbol, 1.0)
    news_ratio = news_vel / baseline if baseline > 0 else 0.0
    sources_ok += 1

    # Check 3: Trending (only if other signals suggest something)
    trending = False
    if vol_spike >= 2.0 or news_ratio >= 2.0:
        trending = check_trending(cg_id)
        sources_ok += 1

    # Composite score
    vol_score = min((vol_spike - 1.0) / 4.0, 1.0)   # 5x = 1.0
    news_score = min(news_ratio / 5.0, 1.0)           # 5x baseline = 1.0
    trend_score = 0.3 if trending else 0.0

    activity_score = (vol_score * 0.5) + (news_score * 0.3) + (trend_score * 0.2)
    activity_score = max(0.0, min(1.0, activity_score))

    # Determine alert level
    if activity_score >= 0.7 or (vol_spike >= 5.0) or (trending and vol_spike >= 2.0):
        level = "extreme"
    elif activity_score >= 0.3 or vol_spike >= 3.0 or news_ratio >= 3.0:
        level = "elevated"
    else:
        level = "none"

    # Detail string
    details = []
    if vol_spike >= 2.0:
        details.append(f"volume {vol_spike:.1f}x normal")
    if news_ratio >= 2.0:
        details.append(f"news {news_ratio:.1f}x baseline ({int(news_vel)} articles/30m)")
    if trending:
        details.append(f"{display} trending on CoinGecko")

    return NewsAlert(
        level=level,
        activity_score=round(activity_score, 3),
        volume_spike=round(vol_spike, 2),
        news_velocity=round(news_vel, 1),
        trending=trending,
        last_checked=datetime.now(timezone.utc).isoformat(),
        sources_checked=sources_ok,
        detail="; ".join(details) if details else "normal activity",
    )


# ── Background Monitor Thread ──────────────────────────────────────

def _monitor_loop(interval_seconds: int = 60):
    """Background loop that checks all tracked assets every interval."""
    while True:
        for symbol in ASSET_MAP:
            try:
                alert = compute_alert(symbol)
                news_cache.set(symbol, alert)

                if alert.level != "none":
                    logger.warning(
                        f"NEWS ALERT {symbol}: {alert.level} — {alert.detail}"
                    )
            except Exception as e:
                logger.error(f"News monitor error for {symbol}: {e}")

        time.sleep(interval_seconds)


_monitor_thread: Optional[threading.Thread] = None


def start_news_monitor(interval_seconds: int = 60):
    """Start the background news monitor thread."""
    global _monitor_thread
    if _monitor_thread is not None and _monitor_thread.is_alive():
        return

    _monitor_thread = threading.Thread(
        target=_monitor_loop,
        args=(interval_seconds,),
        daemon=True,
        name="renoun-news-monitor",
    )
    _monitor_thread.start()
    logger.info(f"News monitor started (checking every {interval_seconds}s)")


def stop_news_monitor():
    """Stop the background monitor (for testing)."""
    global _monitor_thread
    _monitor_thread = None
