"""
ReNoUn Financial Engine v1.0
Patent Pending #63/923,592

Applies the 17-channel Re/No/Un structural framework natively to financial
time series (OHLCV + optional orderbook + sentiment). Operates on numerical
data directly — no text encoding.

Channels:
  Recurrence (Re₁–Re₅): Market regime stability
  Novelty (No₁–No₆): Regime disruption detection
  Unity (Un₁–Un₆): Structural coherence

Output is compatible with the existing ReNoUn MCP ecosystem (renoun_compare,
renoun_steer, renoun_pattern_query).
"""

import math
import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ENGINE_VERSION = "finance-1.0"

# Constellation agent actions (same as conversation engine)
AGENT_ACTIONS = {
    "CLOSED_LOOP": {
        "agent_action": "explore_new_angle",
        "agent_guidance": "Market stuck in tight range — watch for breakout catalysts",
    },
    "HIGH_SYMMETRY": {
        "agent_action": "introduce_variation",
        "agent_guidance": "Algo-dominated structure — expect mean reversion",
    },
    "PATTERN_BREAK": {
        "agent_action": "support_integration",
        "agent_guidance": "Regime change detected — let new structure establish before acting",
    },
    "CONVERGENCE": {
        "agent_action": "maintain_trajectory",
        "agent_guidance": "Signals aligning — productive movement, don't fight the trend",
    },
    "SCATTERING": {
        "agent_action": "provide_structure",
        "agent_guidance": "Structural breakdown — reduce exposure, wait for clarity",
    },
    "REPEATED_DISRUPTION": {
        "agent_action": "slow_down",
        "agent_guidance": "Multiple failed breakouts — reduce position size, widen stops",
    },
    "DIP_AND_RECOVERY": {
        "agent_action": "acknowledge_shift",
        "agent_guidance": "Sell-off absorbed — structure restored, bias constructive",
    },
    "SURFACE_VARIATION": {
        "agent_action": "go_deeper",
        "agent_guidance": "Price moves but underlying dynamics unchanged — don't chase",
    },
}

# Financial interpretations for constellations
CONSTELLATION_DESCRIPTIONS = {
    "CLOSED_LOOP": "Market stuck in range, same regime recycling",
    "HIGH_SYMMETRY": "Overly predictable structure (algo-dominated)",
    "PATTERN_BREAK": "Genuine regime change (trend reversal, breakout)",
    "CONVERGENCE": "Market finding equilibrium, signals aligning",
    "SCATTERING": "Structural breakdown, signals contradicting",
    "REPEATED_DISRUPTION": "Multiple failed breakouts, whipsawing",
    "DIP_AND_RECOVERY": "Sell-off absorbed, structure restored",
    "SURFACE_VARIATION": "Price moves but underlying dynamics unchanged",
}

CONSTELLATION_LEGENDS = {
    "CLOSED_LOOP": "Re↑↑ No↓↓ Un↑↑",
    "HIGH_SYMMETRY": "Re₄↑ Un₄↑ Un₆↑ No₃↓",
    "PATTERN_BREAK": "Re↓ No₂+No₃↑↑ Un↓→↑",
    "CONVERGENCE": "Un₁-₆ rising",
    "SCATTERING": "Re₁+₂↓↓ No₅↑ Un↓↓",
    "REPEATED_DISRUPTION": "Re↓ No₁+₂ spikes Un↓",
    "DIP_AND_RECOVERY": "Re₄↓→↑ No₄ spike Un₄↑",
    "SURFACE_VARIATION": "No₁+₂↑ No₃+₄↓ Un₆↑",
}


# ---------------------------------------------------------------------------
# Data normalisation helpers
# ---------------------------------------------------------------------------

def _parse_klines(raw: Union[List[Dict], Dict]) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, Optional[np.ndarray], Optional[np.ndarray]]:
    """
    Parse various input formats into aligned numpy arrays.

    Returns:
        timestamps, opens, highs, lows, closes, volumes,
        taker_buy_volumes (or None), trades (or None)
    """
    # Handle wrapper dict
    ohlcv_list: List[Dict] = []
    if isinstance(raw, dict):
        if "ohlcv" in raw:
            ohlcv_list = raw["ohlcv"]
        elif "klines" in raw:
            ohlcv_list = raw["klines"]
        else:
            raise ValueError("Dict input must contain 'ohlcv' or 'klines' key")
    elif isinstance(raw, list):
        ohlcv_list = raw
    else:
        raise ValueError(f"Unsupported input type: {type(raw)}")

    if len(ohlcv_list) < 2:
        raise ValueError(f"Need at least 2 data points, got {len(ohlcv_list)}")

    n = len(ohlcv_list)
    timestamps = np.zeros(n)
    opens = np.zeros(n)
    highs = np.zeros(n)
    lows = np.zeros(n)
    closes = np.zeros(n)
    volumes = np.zeros(n)
    taker_buy_vols: Optional[np.ndarray] = None
    trade_counts: Optional[np.ndarray] = None

    # Detect format from first entry
    first = ohlcv_list[0]
    has_taker = "takerBuyVolume" in first or "taker_buy_volume" in first
    has_trades = "trades" in first or "trade_count" in first

    if has_taker:
        taker_buy_vols = np.zeros(n)
    if has_trades:
        trade_counts = np.zeros(n)

    for i, k in enumerate(ohlcv_list):
        # Timestamp
        ts = k.get("openTime") or k.get("timestamp") or k.get("open_time") or k.get("time", i)
        if isinstance(ts, (int, float)) and ts > 1e12:
            ts = ts / 1000.0  # ms → s
        timestamps[i] = float(ts)

        opens[i] = float(k.get("open", k.get("o", 0)))
        highs[i] = float(k.get("high", k.get("h", 0)))
        lows[i] = float(k.get("low", k.get("l", 0)))
        closes[i] = float(k.get("close", k.get("c", 0)))
        volumes[i] = float(k.get("volume", k.get("vol", k.get("v", 0))))

        if taker_buy_vols is not None:
            taker_buy_vols[i] = float(k.get("takerBuyVolume", k.get("taker_buy_volume", 0)))
        if trade_counts is not None:
            trade_counts[i] = float(k.get("trades", k.get("trade_count", 0)))

    return timestamps, opens, highs, lows, closes, volumes, taker_buy_vols, trade_counts


def _safe_std(arr: np.ndarray) -> float:
    """Standard deviation, returning 0.0 for arrays with <2 elements."""
    if len(arr) < 2:
        return 0.0
    return float(np.std(arr, ddof=1))


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def _rolling_windows(arr: np.ndarray, window: int) -> np.ndarray:
    """Return a 2D array of rolling windows. Shape: (n - window + 1, window)."""
    if len(arr) < window:
        return arr.reshape(1, -1)
    shape = (len(arr) - window + 1, window)
    strides = (arr.strides[0], arr.strides[0])
    return np.lib.stride_tricks.as_strided(arr, shape=shape, strides=strides)


def _autocorrelation(x: np.ndarray, lag: int = 1) -> float:
    """Compute autocorrelation at given lag."""
    if len(x) < lag + 2:
        return 0.0
    x = x - np.mean(x)
    var = np.var(x)
    if var < 1e-15:
        return 1.0  # constant series = perfect autocorrelation
    n = len(x)
    return float(np.sum(x[:n - lag] * x[lag:]) / (n * var))


def _zscore(value: float, mean: float, std: float) -> float:
    if std < 1e-15:
        return 0.0
    return (value - mean) / std


def _safe_buy_ratio(taker_buy_vols: np.ndarray, volumes: np.ndarray) -> np.ndarray:
    """Compute buy ratio without division warnings."""
    safe_vol = np.maximum(volumes, 1e-15)
    ratio = taker_buy_vols / safe_vol
    # Clamp to [0, 1] and replace any NaN with 0.5
    ratio = np.clip(ratio, 0.0, 1.0)
    ratio = np.where(np.isfinite(ratio), ratio, 0.5)
    return ratio


# ---------------------------------------------------------------------------
# Channel calculations
# ---------------------------------------------------------------------------

def _compute_returns(closes: np.ndarray) -> np.ndarray:
    """Log returns, handling edge cases."""
    safe = np.maximum(closes, 1e-10)
    return np.diff(np.log(safe))


def _compute_atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> np.ndarray:
    """Average True Range series."""
    n = len(closes)
    tr = np.zeros(n)
    tr[0] = highs[0] - lows[0]
    for i in range(1, n):
        tr[i] = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
    # EMA-style ATR
    atr = np.zeros(n)
    atr[0] = tr[0]
    alpha = 1.0 / max(period, 1)
    for i in range(1, n):
        atr[i] = atr[i - 1] * (1 - alpha) + tr[i] * alpha
    return atr


# ---- Recurrence channels ----

def _re1_price_pattern(returns: np.ndarray) -> float:
    """
    Re₁ Price Pattern: autocorrelation of returns AND volatility clustering.
    Raw return autocorrelation is near-zero for crypto (efficient markets),
    but |return| autocorrelation (volatility clustering) is persistent and
    meaningful — it captures whether the market has identifiable regimes.
    """
    if len(returns) < 4:
        return 0.5
    # Return autocorrelation (trend/mean-reversion)
    ac1_ret = abs(_autocorrelation(returns, 1))
    ac2_ret = abs(_autocorrelation(returns, 2))
    ret_ac = (ac1_ret + ac2_ret) / 2

    # Volatility clustering: autocorrelation of |returns|
    abs_ret = np.abs(returns)
    ac1_vol = abs(_autocorrelation(abs_ret, 1))
    ac2_vol = abs(_autocorrelation(abs_ret, 2))
    ac3_vol = abs(_autocorrelation(abs_ret, 3))
    vol_clustering = (ac1_vol + ac2_vol + ac3_vol) / 3

    # Blend: vol clustering is more persistent and meaningful
    return _clamp(0.3 * ret_ac + 0.7 * vol_clustering)


def _re2_volume_profile(volumes: np.ndarray) -> float:
    """
    Re₂ Volume Profile: recurrence of volume distribution.
    Measures how stable the volume profile is across successive windows
    using rank-correlation of volume patterns.
    """
    n = len(volumes)
    if n < 6:
        return 0.5

    # Use rank-based approach: split into non-overlapping windows,
    # compare rank distributions
    win = max(n // 5, 3)
    correlations = []
    for i in range(0, n - 2 * win + 1, win):
        w1 = volumes[i:i + win]
        w2 = volumes[i + win:i + 2 * win]
        if len(w2) < win:
            break
        # Rank correlation between sorted volume profiles
        r1 = np.argsort(np.argsort(w1)).astype(float)
        r2 = np.argsort(np.argsort(w2)).astype(float)
        s1, s2 = _safe_std(r1), _safe_std(r2)
        if s1 < 1e-15 or s2 < 1e-15:
            correlations.append(0.5)
        else:
            corr = np.corrcoef(r1, r2)[0, 1]
            correlations.append(0.0 if np.isnan(corr) else (corr + 1) / 2)

    if not correlations:
        return 0.5
    return _clamp(float(np.mean(correlations)))


def _re3_volatility_rhythm(atr: np.ndarray) -> float:
    """
    Re₃ Volatility Rhythm: consistency of volatility regime.
    Low coefficient of variation in ATR → rhythmic → high recurrence.
    """
    if len(atr) < 3:
        return 0.5
    mean_atr = np.mean(atr)
    if mean_atr < 1e-15:
        return 0.5
    cv = _safe_std(atr) / mean_atr
    # cv of 0 → perfect rhythm (1.0); cv of 1+ → chaotic (0.0)
    return _clamp(1.0 - cv)


def _re4_flow_pattern(
    taker_buy_vols: Optional[np.ndarray],
    volumes: np.ndarray,
) -> float:
    """
    Re₄ Flow Pattern: predictability of buy/sell pressure alternation.
    Measures autocorrelation of the buy-ratio series.
    """
    if taker_buy_vols is None:
        return 0.5  # graceful degradation

    n = len(volumes)
    if n < 4:
        return 0.5

    # Buy ratio per candle
    buy_ratio = _safe_buy_ratio(taker_buy_vols, volumes)
    # Center around 0.5
    centered = buy_ratio - 0.5
    ac = _autocorrelation(centered, 1)
    # High |ac| → predictable flow pattern
    return _clamp(abs(ac) * 1.5)  # scale up since flow ac is typically small


def _re5_microstructure(
    trade_counts: Optional[np.ndarray],
    taker_buy_vols: Optional[np.ndarray],
    volumes: np.ndarray,
) -> float:
    """
    Re₅ Microstructure: repeated orderbook imbalance patterns.
    Uses trade count consistency + buy-side imbalance stability.
    """
    if trade_counts is None and taker_buy_vols is None:
        return 0.5  # graceful degradation

    scores = []

    if trade_counts is not None and len(trade_counts) > 3:
        # Trade count consistency (low CV → recurrent)
        mean_tc = np.mean(trade_counts)
        if mean_tc > 0:
            cv = _safe_std(trade_counts) / mean_tc
            scores.append(_clamp(1.0 - cv * 0.5))

    if taker_buy_vols is not None and len(volumes) > 3:
        # Buy-side imbalance stability
        buy_ratio = _safe_buy_ratio(taker_buy_vols, volumes)
        cv = _safe_std(buy_ratio) / max(np.mean(buy_ratio), 1e-15)
        scores.append(_clamp(1.0 - cv))

    return float(np.mean(scores)) if scores else 0.5


# ---- Novelty channels ----

def _no1_price_novelty(returns: np.ndarray) -> float:
    """
    No₁ Price Novelty: unexpected price moves vs recent distribution.
    Fraction of returns that are outliers (|z| > 2) in a rolling window.
    """
    n = len(returns)
    if n < 5:
        return 0.5

    window = max(min(n // 3, 50), 5)
    outlier_count = 0
    total = 0

    for i in range(window, n):
        lookback = returns[i - window:i]
        mu = np.mean(lookback)
        sigma = _safe_std(lookback)
        z = abs(_zscore(returns[i], mu, sigma))
        if z > 2.0:
            outlier_count += 1
        total += 1

    if total == 0:
        return 0.5
    # Scale: 5% outliers → 0.25, 20% → 1.0
    raw = outlier_count / total
    return _clamp(raw * 5.0)


def _no2_volume_novelty(volumes: np.ndarray) -> float:
    """
    No₂ Volume Novelty: volume spikes/droughts vs baseline.
    """
    n = len(volumes)
    if n < 5:
        return 0.5

    window = max(min(n // 3, 50), 5)
    spike_count = 0
    total = 0

    for i in range(window, n):
        lookback = volumes[i - window:i]
        mu = np.mean(lookback)
        sigma = _safe_std(lookback)
        z = abs(_zscore(volumes[i], mu, sigma))
        if z > 2.0:
            spike_count += 1
        total += 1

    if total == 0:
        return 0.5
    raw = spike_count / total
    return _clamp(raw * 5.0)


def _no3_volatility_break(atr: np.ndarray) -> float:
    """
    No₃ Volatility Break: sudden regime changes in volatility.
    Detects ATR deviations relative to a rolling baseline.
    """
    n = len(atr)
    if n < 5:
        return 0.5

    window = max(min(n // 4, 40), 3)
    break_count = 0
    total = 0

    for i in range(window, n):
        lookback = atr[i - window:i]
        mu = np.mean(lookback)
        sigma = _safe_std(lookback)
        z = abs(_zscore(atr[i], mu, sigma))
        if z > 2.0:
            break_count += 1
        total += 1

    if total == 0:
        return 0.5
    # 5% breaks → 0.15; ~15% → 0.5; 30%+ → 1.0
    raw = break_count / total
    return _clamp(raw * 3.3)


def _no4_flow_reversal(
    taker_buy_vols: Optional[np.ndarray],
    volumes: np.ndarray,
) -> float:
    """
    No₄ Flow Reversal: unexpected shifts in buyer/seller dominance.
    Measures sign changes in (buy_ratio - 0.5) with magnitude.
    """
    if taker_buy_vols is None:
        return 0.5

    n = len(volumes)
    if n < 4:
        return 0.5

    buy_ratio = _safe_buy_ratio(taker_buy_vols, volumes)
    centered = buy_ratio - 0.5

    # Count sign changes weighted by magnitude
    reversals = 0.0
    for i in range(1, n):
        if centered[i] * centered[i - 1] < 0:
            # Sign change — weight by magnitude of the swing
            swing = abs(centered[i] - centered[i - 1])
            reversals += swing

    # Normalize by number of candles
    avg_reversal = reversals / (n - 1)
    # avg_reversal of 0.1 → 0.2; 0.25 → 0.5; 0.5 → 1.0
    return _clamp(avg_reversal * 2.0)


def _no5_microstructure_break(
    trade_counts: Optional[np.ndarray],
    taker_buy_vols: Optional[np.ndarray],
    volumes: np.ndarray,
) -> float:
    """
    No₅ Microstructure Break: orderbook structure changes.
    Detects regime shifts in the trade-count / buy-ratio relationship
    using rolling window z-scores (same methodology as No1/No2).
    """
    if trade_counts is None and taker_buy_vols is None:
        return 0.5

    n = len(volumes)
    if n < 8:
        return 0.5

    signals = []
    window = max(min(n // 4, 40), 4)

    if trade_counts is not None and len(trade_counts) > window:
        outliers = 0
        total = 0
        for i in range(window, len(trade_counts)):
            lb = trade_counts[i - window:i]
            mu, sig = np.mean(lb), _safe_std(lb)
            z = abs(_zscore(trade_counts[i], mu, sig))
            if z > 2.0:
                outliers += 1
            total += 1
        if total > 0:
            signals.append(_clamp(outliers / total * 5.0))

    if taker_buy_vols is not None:
        # Buy ratio regime shifts: measure how often the buy-ratio
        # deviates from its rolling mean
        buy_ratio = _safe_buy_ratio(taker_buy_vols, volumes)
        if len(buy_ratio) > window:
            outliers = 0
            total = 0
            for i in range(window, len(buy_ratio)):
                lb = buy_ratio[i - window:i]
                mu, sig = np.mean(lb), _safe_std(lb)
                z = abs(_zscore(buy_ratio[i], mu, sig))
                if z > 2.0:
                    outliers += 1
                total += 1
            if total > 0:
                signals.append(_clamp(outliers / total * 5.0))

    return float(np.mean(signals)) if signals else 0.5


def _no6_cross_signal_rarity(
    returns: np.ndarray,
    volumes: np.ndarray,
    atr: np.ndarray,
    taker_buy_vols: Optional[np.ndarray],
) -> float:
    """
    No₆ Cross-Signal Rarity: statistically rare combinations across signals.
    Measures how often multiple signals are simultaneously in extreme territory.
    """
    n = min(len(returns), len(volumes) - 1, len(atr) - 1)
    if n < 5:
        return 0.5

    # Trim to same length (returns is 1 shorter)
    ret = returns[:n]
    vol = volumes[1:n + 1]
    at = atr[1:n + 1]

    # Z-score each series
    def zseries(s: np.ndarray) -> np.ndarray:
        mu, sig = np.mean(s), _safe_std(s)
        if sig < 1e-15:
            return np.zeros_like(s)
        return (s - mu) / sig

    z_ret = zseries(ret)
    z_vol = zseries(vol)
    z_atr = zseries(at)

    signals = [z_ret, z_vol, z_atr]

    if taker_buy_vols is not None:
        buy_ratio = _safe_buy_ratio(taker_buy_vols[1:n + 1], vol)
        signals.append(zseries(buy_ratio))

    # Count candles where 2+ signals are in extreme territory (|z| > 1.5)
    extreme_count = 0
    for i in range(n):
        extremes = sum(1 for s in signals if abs(s[i]) > 1.5)
        if extremes >= 2:
            extreme_count += 1

    raw = extreme_count / n
    # 5% co-extreme → 0.25; 20% → 1.0
    return _clamp(raw * 5.0)


# ---- Unity channels ----

def _un1_price_volume_cohesion(
    returns: np.ndarray,
    volumes: np.ndarray,
) -> float:
    """
    Un₁ Price-Volume Cohesion: do price and volume tell the same story?
    Healthy market: big moves on big volume, small moves on small volume.
    """
    n = min(len(returns), len(volumes) - 1)
    if n < 4:
        return 0.5

    abs_ret = np.abs(returns[:n])
    vol = volumes[1:n + 1]

    # Rank correlation (Spearman-like)
    ret_ranks = np.argsort(np.argsort(abs_ret)).astype(float)
    vol_ranks = np.argsort(np.argsort(vol)).astype(float)

    # Pearson correlation of ranks
    if _safe_std(ret_ranks) < 1e-15 or _safe_std(vol_ranks) < 1e-15:
        return 0.5
    corr = np.corrcoef(ret_ranks, vol_ranks)[0, 1]
    if np.isnan(corr):
        return 0.5

    # Positive correlation → cohesive; map [0, 1] correlation to [0, 1]
    return _clamp((corr + 1) / 2)


def _un2_trend_cohesion(closes: np.ndarray) -> float:
    """
    Un₂ Trend Cohesion: are multi-timeframe signals aligned?
    Samples multiple points throughout the series and checks whether
    short/medium/long trend directions agree at each sample.
    """
    n = len(closes)
    if n < 6:
        return 0.5

    short = max(n // 10, 2)
    medium = max(n // 4, 3)
    long_ = max(n // 2, 4)

    # Sample at multiple points through the series
    sample_points = list(range(long_, n, max(n // 10, 1)))
    if not sample_points:
        sample_points = [n - 1]

    agreements = []
    for pt in sample_points:
        dirs = []
        for period in [short, medium, long_]:
            if pt - period >= 0:
                change = closes[pt] - closes[pt - period]
                dirs.append(np.sign(change))
        if len(dirs) < 2:
            continue
        # Pairwise agreement
        agree = 0
        total = 0
        for i in range(len(dirs)):
            for j in range(i + 1, len(dirs)):
                total += 1
                if dirs[i] == dirs[j]:
                    agree += 1
        if total > 0:
            agreements.append(agree / total)

    if not agreements:
        return 0.5
    return _clamp(float(np.mean(agreements)))


def _un3_volatility_cohesion(atr: np.ndarray) -> float:
    """
    Un₃ Volatility Cohesion: is volatility regime consistent?
    Measures how stable ATR is relative to its own level.
    Low CV of ATR → consistent regime → high cohesion.
    """
    if len(atr) < 4:
        return 0.5

    mean_atr = np.mean(atr)
    if mean_atr < 1e-15:
        return 0.5

    # CV of ATR itself: 0 → perfectly stable (1.0); CV ≥ 1.0 → chaotic (0.0)
    cv = _safe_std(atr) / mean_atr
    return _clamp(1.0 - cv)


def _un4_flow_cohesion(
    taker_buy_vols: Optional[np.ndarray],
    volumes: np.ndarray,
    returns: np.ndarray,
) -> float:
    """
    Un₄ Flow Cohesion: is order flow internally consistent?
    Bullish returns should align with buy-side dominance.
    """
    if taker_buy_vols is None:
        return 0.5

    n = min(len(returns), len(volumes) - 1)
    if n < 4:
        return 0.5

    buy_ratio = _safe_buy_ratio(taker_buy_vols[1:n + 1], volumes[1:n + 1])
    ret = returns[:n]

    # Agreement: positive return + buy_ratio > 0.5, or negative + < 0.5
    agreements = 0
    for i in range(n):
        if (ret[i] > 0 and buy_ratio[i] > 0.5) or \
           (ret[i] < 0 and buy_ratio[i] < 0.5) or \
           abs(ret[i]) < 1e-8:  # flat = neutral, don't penalise
            agreements += 1

    return _clamp(agreements / n)


def _un5_momentum_cohesion(returns: np.ndarray) -> float:
    """
    Un₅ Momentum Cohesion: do recent signals build on prior signals?
    Measures how consistently returns maintain their direction over
    successive windows.
    """
    n = len(returns)
    if n < 6:
        return 0.5

    window = max(n // 5, 3)
    # Split into windows and measure directional consistency
    window_means = []
    for i in range(0, n - window + 1, max(window // 2, 1)):
        w = returns[i:i + window]
        window_means.append(np.mean(w))

    if len(window_means) < 2:
        return 0.5

    # Consecutive windows with same sign → momentum cohesion
    same_direction = 0
    for i in range(1, len(window_means)):
        if window_means[i] * window_means[i - 1] > 0:
            same_direction += 1

    return _clamp(same_direction / (len(window_means) - 1))


def _un6_structural_symmetry(
    returns: np.ndarray,
    volumes: np.ndarray,
) -> float:
    """
    Un₆ Structural Symmetry: first-half vs second-half pattern mirroring.
    Compares summary statistics between halves (mean, std, skew, extremes)
    rather than raw distributions (which are always similar for IID-ish data).
    Also compares the windowed profile shapes using correlation.
    """
    n = min(len(returns), len(volumes) - 1)
    if n < 8:
        return 0.5

    mid = n // 2
    ret_h1 = returns[:mid]
    ret_h2 = returns[mid:2 * mid]

    def stat_similarity(a: np.ndarray, b: np.ndarray) -> float:
        """Compare summary statistics between two series."""
        if len(a) < 3 or len(b) < 3:
            return 0.5
        scores = []
        # Mean similarity
        combined_std = _safe_std(np.concatenate([a, b]))
        if combined_std > 1e-15:
            mean_diff = abs(np.mean(a) - np.mean(b)) / combined_std
            scores.append(_clamp(1.0 - mean_diff))
        # Std similarity
        sa, sb = _safe_std(a), _safe_std(b)
        if max(sa, sb) > 1e-15:
            std_ratio = min(sa, sb) / max(sa, sb)
            scores.append(std_ratio)
        # Skewness similarity
        sk_a = float(np.mean(((a - np.mean(a)) / max(_safe_std(a), 1e-15)) ** 3))
        sk_b = float(np.mean(((b - np.mean(b)) / max(_safe_std(b), 1e-15)) ** 3))
        scores.append(_clamp(1.0 - abs(sk_a - sk_b) / 2.0))
        # Extreme ratio (max/min magnitudes)
        max_a, max_b = np.max(np.abs(a)), np.max(np.abs(b))
        if max(max_a, max_b) > 1e-15:
            scores.append(min(max_a, max_b) / max(max_a, max_b))
        return float(np.mean(scores)) if scores else 0.5

    def profile_similarity(a: np.ndarray, b: np.ndarray, win: int) -> float:
        """Compare windowed profiles using correlation."""
        if len(a) < win * 2 or len(b) < win * 2:
            return 0.5
        # Create windowed mean profiles
        p1 = [np.mean(a[i:i + win]) for i in range(0, len(a) - win + 1, win)]
        p2 = [np.mean(b[i:i + win]) for i in range(0, len(b) - win + 1, win)]
        k = min(len(p1), len(p2))
        if k < 2:
            return 0.5
        p1, p2 = np.array(p1[:k]), np.array(p2[:k])
        s1, s2 = _safe_std(p1), _safe_std(p2)
        if s1 < 1e-15 or s2 < 1e-15:
            return 0.5
        corr = np.corrcoef(p1, p2)[0, 1]
        return _clamp((corr + 1) / 2) if not np.isnan(corr) else 0.5

    ret_stat = stat_similarity(ret_h1, ret_h2)
    win = max(mid // 5, 2)
    ret_prof = profile_similarity(ret_h1, ret_h2, win)

    vol_h1 = volumes[1:mid + 1]
    vol_h2 = volumes[mid + 1:2 * mid + 1]
    vol_stat = stat_similarity(vol_h1, vol_h2)

    return _clamp((ret_stat + ret_prof + vol_stat) / 3)


# ---------------------------------------------------------------------------
# DHS calculation
# ---------------------------------------------------------------------------

def _dd_stress_curve(dd: float) -> float:
    """Map a drawdown fraction to a raw stress value (0–0.95)."""
    if dd <= 0.0:
        return 0.0
    # Gentle below 12%, quadratic 12-35%, steep above 35%
    if dd <= 0.12:
        return dd * 0.5  # 5%→0.025, 10%→0.05, 12%→0.06
    if dd <= 0.35:
        t = (dd - 0.12) / 0.23  # 0→1
        return 0.06 + t * t * 0.59  # 0.06→0.65
    # Above 35%: steep linear
    return min(0.65 + (dd - 0.35) * 2.0, 0.95)


def _compute_drawdown_stress(closes: np.ndarray) -> float:
    """
    Compute drawdown stress from the CURRENT price position relative to
    the running peak within the analysis window.

    Uses current_dd (not historical max_dd) so that recovered drawdowns
    don't produce phantom stress. A 30% drawdown that recovered to -5%
    correctly produces only 5% stress.

    Recovery-aware: when price is bouncing off the trough, the stress
    decays proportionally to how much of the max drawdown has been
    recovered.  A 30% drawdown that has recovered 60% of the move
    (current_dd now 12%) gets an additional recovery discount:
        raw_stress(12%) × (1 - 0.4 × recovery_ratio)
    The 0.4 cap ensures we never fully dismiss stress during an active
    drawdown — there's always residual caution until price makes a new
    high (at which point current_dd = 0 and stress = 0 naturally).

    Returns 0.0 at or near highs, up to ~0.95 for extreme drawdowns (50%+).
    """
    if len(closes) < 3:
        return 0.0

    # Current drawdown from running peak (how far below ATH right now)
    peak = np.maximum.accumulate(closes)
    drawdown = (peak - closes) / (peak + 1e-15)
    current_dd = max(float(drawdown[-1]), 0.0)

    raw_stress = _dd_stress_curve(current_dd)
    if raw_stress < 1e-6:
        return 0.0

    # --- Recovery discount ---
    # max_dd = worst drawdown anywhere in the window
    # recovery_ratio = how much of that max drawdown has been recovered
    # (0 = still at trough, 1 = fully recovered to new high)
    max_dd = float(np.max(drawdown))
    if max_dd > 1e-6 and max_dd > current_dd:
        recovery_ratio = 1.0 - (current_dd / max_dd)
        # Discount stress by up to 40% based on recovery progress.
        # This means a 50% recovered drawdown gets ~20% stress discount,
        # and a 90% recovered drawdown gets ~36% discount.
        discount = min(0.4, 0.4 * recovery_ratio)
        raw_stress *= (1.0 - discount)

    return raw_stress


def _compute_vol_expansion_stress(atr: np.ndarray) -> float:
    """
    Compute volatility expansion stress — is ATR rising rapidly?

    Expanding volatility (ATR rising from its own recent baseline)
    indicates increasing risk even if other channels look healthy.
    """
    if len(atr) < 10:
        return 0.0

    # Compare recent ATR (last 20%) to earlier ATR (first 60%)
    split = max(len(atr) * 4 // 5, 5)
    baseline = atr[:split]
    recent = atr[split:]

    baseline_mean = np.mean(baseline)
    if baseline_mean < 1e-15:
        return 0.0

    recent_mean = np.mean(recent)
    expansion_ratio = recent_mean / baseline_mean

    # expansion_ratio of 1.0 = stable (no stress)
    # 1.5 = moderate expansion (0.25 stress)
    # 2.0 = significant expansion (0.50 stress)
    # 3.0+ = extreme expansion (0.80+ stress)
    if expansion_ratio <= 1.0:
        return 0.0
    return _clamp((expansion_ratio - 1.0) * 0.5)


def _compute_dhs(
    re_agg: float, no_agg: float, un_agg: float,
    closes: Optional[np.ndarray] = None,
    atr: Optional[np.ndarray] = None,
) -> float:
    """
    Dialectical Health Score for financial data.

    Base score from Re/No/Un balance (same logic as conversation engine),
    then two financial-specific stress modifiers:
      1. Drawdown stress — penalizes severe peak-to-current declines
      2. Volatility expansion — penalizes rapidly rising ATR

    These modifiers address the core limitation that an orderly selloff
    has "good structure" (moderate Re, coherent Un) but is NOT healthy
    from a risk perspective.
    """
    # --- Base DHS from Re/No/Un ---

    # Recurrence quality: peaks at ~0.45, penalises extremes
    re_quality = 1.0 - 2.0 * abs(re_agg - 0.45)
    re_quality = _clamp(re_quality)

    # Novelty quality: peaks at ~0.35, too much novelty = chaos
    no_quality = 1.0 - 2.0 * abs(no_agg - 0.35)
    no_quality = _clamp(no_quality)

    # Unity is directly beneficial
    un_quality = un_agg

    # Weighted combination
    base = 0.30 * re_quality + 0.25 * no_quality + 0.45 * un_quality

    # Penalty for extreme configurations
    if re_agg > 0.7 and no_agg < 0.15:
        base -= 0.15  # CLOSED_LOOP
    if re_agg < 0.2 and un_agg < 0.3:
        base -= 0.20  # SCATTERING
    if no_agg > 0.7 and un_agg < 0.3:
        base -= 0.15  # Chaos

    # --- Financial stress modifiers ---

    dd_stress = 0.0
    vol_stress = 0.0

    if closes is not None:
        dd_stress = _compute_drawdown_stress(closes)
    if atr is not None:
        vol_stress = _compute_vol_expansion_stress(atr)

    # Combined stress penalty (max ~0.50 penalty from drawdown + vol)
    # Drawdown is the primary signal; vol expansion amplifies it
    stress_penalty = dd_stress * 0.40 + vol_stress * 0.10
    # If both are high, add interaction term (active crash with rising ATR)
    if dd_stress > 0.3 and vol_stress > 0.2:
        stress_penalty += 0.05

    return _clamp(base - stress_penalty)


def _compute_loop_strength(re_agg: float, no_agg: float) -> float:
    """
    Loop strength: how much the market is stuck repeating.
    High recurrence + low novelty → high loop strength.
    """
    return _clamp(re_agg * (1.0 - no_agg))


# ---------------------------------------------------------------------------
# Constellation detection
# ---------------------------------------------------------------------------

# Each constellation has expected channel profiles:
#   "high" = value >= 0.6
#   "low"  = value <= 0.3
#   "spike" = value >= 0.4
#   "any"  = no constraint
CONSTELLATION_SIGNATURES = {
    "CLOSED_LOOP": {
        "re": {"Re1": "high", "Re2": "high", "Re3": "high", "Re4": "any", "Re5": "any"},
        "no": {"No1": "low", "No2": "low", "No3": "low", "No4": "low", "No5": "any", "No6": "low"},
        "un": {"Un1": "high", "Un2": "any", "Un3": "high", "Un4": "any", "Un5": "any", "Un6": "high"},
    },
    "HIGH_SYMMETRY": {
        "re": {"Re1": "any", "Re2": "any", "Re3": "high", "Re4": "high", "Re5": "high"},
        "no": {"No1": "any", "No2": "any", "No3": "low", "No4": "low", "No5": "low", "No6": "any"},
        "un": {"Un1": "any", "Un2": "any", "Un3": "any", "Un4": "high", "Un5": "any", "Un6": "high"},
    },
    "PATTERN_BREAK": {
        "re": {"Re1": "low", "Re2": "low", "Re3": "any", "Re4": "any", "Re5": "any"},
        "no": {"No1": "spike", "No2": "spike", "No3": "spike", "No4": "any", "No5": "any", "No6": "any"},
        "un": {"Un1": "any", "Un2": "any", "Un3": "any", "Un4": "any", "Un5": "any", "Un6": "any"},
    },
    "CONVERGENCE": {
        "re": {"Re1": "any", "Re2": "any", "Re3": "any", "Re4": "any", "Re5": "any"},
        "no": {"No1": "low", "No2": "low", "No3": "low", "No4": "low", "No5": "any", "No6": "any"},
        "un": {"Un1": "high", "Un2": "high", "Un3": "high", "Un4": "any", "Un5": "high", "Un6": "any"},
    },
    "SCATTERING": {
        "re": {"Re1": "low", "Re2": "low", "Re3": "any", "Re4": "any", "Re5": "any"},
        "no": {"No1": "any", "No2": "any", "No3": "any", "No4": "any", "No5": "spike", "No6": "any"},
        "un": {"Un1": "low", "Un2": "low", "Un3": "low", "Un4": "low", "Un5": "low", "Un6": "low"},
    },
    "REPEATED_DISRUPTION": {
        "re": {"Re1": "low", "Re2": "any", "Re3": "low", "Re4": "any", "Re5": "any"},
        "no": {"No1": "spike", "No2": "spike", "No3": "any", "No4": "any", "No5": "any", "No6": "any"},
        "un": {"Un1": "low", "Un2": "any", "Un3": "low", "Un4": "any", "Un5": "any", "Un6": "any"},
    },
    "DIP_AND_RECOVERY": {
        "re": {"Re1": "any", "Re2": "any", "Re3": "any", "Re4": "any", "Re5": "any"},
        "no": {"No1": "any", "No2": "any", "No3": "any", "No4": "spike", "No5": "any", "No6": "any"},
        "un": {"Un1": "any", "Un2": "any", "Un3": "any", "Un4": "high", "Un5": "high", "Un6": "any"},
    },
    "SURFACE_VARIATION": {
        "re": {"Re1": "any", "Re2": "any", "Re3": "high", "Re4": "any", "Re5": "any"},
        "no": {"No1": "spike", "No2": "spike", "No3": "low", "No4": "low", "No5": "any", "No6": "any"},
        "un": {"Un1": "any", "Un2": "any", "Un3": "any", "Un4": "any", "Un5": "any", "Un6": "high"},
    },
}


# Micro-timeframe (<=5m) signatures.  At sub-5m resolution, flow channels
# (No4, Un4, Un5) and price-recurrence channels (Re1, Re5, Re4) are always
# stuck at their floor/ceiling and carry no discriminating power.  The
# discriminating axes shift to volatility (Re3, Un3, No3), cross-signal
# rarity (No6), price/volume novelty (No1, No2), and structural symmetry
# (Un6).  These signatures test the same 8 constellations via the channels
# that actually vary at 1m/5m resolution.
MICRO_CONSTELLATION_SIGNATURES = {
    "CLOSED_LOOP": {
        "re": {"Re1": "any", "Re2": "high", "Re3": "high", "Re4": "any", "Re5": "any"},
        "no": {"No1": "low", "No2": "low", "No3": "low", "No4": "any", "No5": "any", "No6": "low"},
        "un": {"Un1": "any", "Un2": "any", "Un3": "high", "Un4": "any", "Un5": "any", "Un6": "high"},
    },
    "HIGH_SYMMETRY": {
        "re": {"Re1": "any", "Re2": "any", "Re3": "high", "Re4": "any", "Re5": "any"},
        "no": {"No1": "any", "No2": "any", "No3": "low", "No4": "any", "No5": "low", "No6": "any"},
        "un": {"Un1": "any", "Un2": "any", "Un3": "high", "Un4": "any", "Un5": "any", "Un6": "high"},
    },
    "PATTERN_BREAK": {
        "re": {"Re1": "any", "Re2": "any", "Re3": "low", "Re4": "any", "Re5": "any"},
        "no": {"No1": "spike", "No2": "spike", "No3": "spike", "No4": "any", "No5": "any", "No6": "spike"},
        "un": {"Un1": "any", "Un2": "any", "Un3": "low", "Un4": "any", "Un5": "any", "Un6": "any"},
    },
    "CONVERGENCE": {
        "re": {"Re1": "any", "Re2": "high", "Re3": "any", "Re4": "any", "Re5": "any"},
        "no": {"No1": "low", "No2": "low", "No3": "low", "No4": "any", "No5": "any", "No6": "any"},
        "un": {"Un1": "any", "Un2": "any", "Un3": "high", "Un4": "any", "Un5": "any", "Un6": "high"},
    },
    "SCATTERING": {
        "re": {"Re1": "any", "Re2": "low", "Re3": "low", "Re4": "any", "Re5": "any"},
        "no": {"No1": "spike", "No2": "any", "No3": "spike", "No4": "any", "No5": "spike", "No6": "spike"},
        "un": {"Un1": "any", "Un2": "any", "Un3": "low", "Un4": "any", "Un5": "any", "Un6": "low"},
    },
    "REPEATED_DISRUPTION": {
        "re": {"Re1": "any", "Re2": "any", "Re3": "low", "Re4": "any", "Re5": "any"},
        "no": {"No1": "spike", "No2": "any", "No3": "spike", "No4": "any", "No5": "spike", "No6": "any"},
        "un": {"Un1": "any", "Un2": "any", "Un3": "low", "Un4": "any", "Un5": "any", "Un6": "any"},
    },
    "DIP_AND_RECOVERY": {
        "re": {"Re1": "any", "Re2": "any", "Re3": "high", "Re4": "any", "Re5": "any"},
        "no": {"No1": "any", "No2": "any", "No3": "spike", "No4": "any", "No5": "any", "No6": "any"},
        "un": {"Un1": "any", "Un2": "any", "Un3": "high", "Un4": "any", "Un5": "any", "Un6": "high"},
    },
    "SURFACE_VARIATION": {
        "re": {"Re1": "any", "Re2": "any", "Re3": "high", "Re4": "any", "Re5": "any"},
        "no": {"No1": "spike", "No2": "spike", "No3": "low", "No4": "any", "No5": "any", "No6": "any"},
        "un": {"Un1": "any", "Un2": "any", "Un3": "any", "Un4": "any", "Un5": "any", "Un6": "high"},
    },
}


def _detect_constellations(channels: Dict, timeframe: str = "1h") -> List[Dict]:
    """
    Detect which of the 8 constellation patterns match the current channel values.
    Uses the same detection algorithm as the conversation engine:
    threshold-based matching with confidence = matched_checks / total_checks.

    At micro timeframes (<=5m), uses MICRO_CONSTELLATION_SIGNATURES which rely
    on channels that actually discriminate at sub-5m resolution (volatility,
    novelty, symmetry) instead of flow channels that saturate.
    """
    re_vals = {
        "Re1": channels["recurrence"]["Re1_price_pattern"],
        "Re2": channels["recurrence"]["Re2_volume_profile"],
        "Re3": channels["recurrence"]["Re3_volatility_rhythm"],
        "Re4": channels["recurrence"]["Re4_flow_pattern"],
        "Re5": channels["recurrence"]["Re5_microstructure"],
    }
    no_vals = {
        "No1": channels["novelty"]["No1_price_novelty"],
        "No2": channels["novelty"]["No2_volume_novelty"],
        "No3": channels["novelty"]["No3_volatility_break"],
        "No4": channels["novelty"]["No4_flow_reversal"],
        "No5": channels["novelty"]["No5_microstructure_break"],
        "No6": channels["novelty"]["No6_cross_signal_rarity"],
    }
    un_vals = {
        "Un1": channels["unity"]["Un1_price_volume_cohesion"],
        "Un2": channels["unity"]["Un2_trend_cohesion"],
        "Un3": channels["unity"]["Un3_volatility_cohesion"],
        "Un4": channels["unity"]["Un4_flow_cohesion"],
        "Un5": channels["unity"]["Un5_momentum_cohesion"],
        "Un6": channels["unity"]["Un6_structural_symmetry"],
    }

    detections = []

    # Select signature set based on timeframe
    micro_timeframes = {"1m", "2m", "3m", "5m"}
    sigs = MICRO_CONSTELLATION_SIGNATURES if timeframe in micro_timeframes else CONSTELLATION_SIGNATURES

    for name, sig in sigs.items():
        match_count = 0
        total_checks = 0

        # Check Recurrence profile
        for ch, expected in sig["re"].items():
            if expected == "any":
                continue
            total_checks += 1
            v = re_vals[ch]
            if expected == "high" and v >= 0.6:
                match_count += 1
            elif expected == "low" and v <= 0.3:
                match_count += 1
            elif expected == "spike" and v >= 0.4:
                match_count += 1

        # Check Novelty profile
        for ch, expected in sig["no"].items():
            if expected == "any":
                continue
            total_checks += 1
            v = no_vals[ch]
            if expected == "high" and v >= 0.6:
                match_count += 1
            elif expected == "low" and v <= 0.3:
                match_count += 1
            elif expected == "spike" and v >= 0.4:
                match_count += 1

        # Check Unity profile
        for ch, expected in sig["un"].items():
            if expected == "any":
                continue
            total_checks += 1
            v = un_vals[ch]
            if expected == "high" and v >= 0.6:
                match_count += 1
            elif expected == "low" and v <= 0.3:
                match_count += 1
            elif expected == "spike" and v >= 0.4:
                match_count += 1

        if total_checks > 0:
            confidence = match_count / total_checks
            if confidence >= 0.5:
                action_info = AGENT_ACTIONS.get(name, {})
                detections.append({
                    "detected": name,
                    "confidence": round(confidence, 3),
                    "channel_legend": CONSTELLATION_LEGENDS.get(name, ""),
                    "plain_description": CONSTELLATION_DESCRIPTIONS.get(name, ""),
                    "agent_action": action_info.get("agent_action", ""),
                    "agent_guidance": action_info.get("agent_guidance", ""),
                })

    # Sort by confidence descending
    detections.sort(key=lambda d: d["confidence"], reverse=True)
    return detections


# ---------------------------------------------------------------------------
# Novelty items (structural pivot points)
# ---------------------------------------------------------------------------

def _detect_novelty_items(
    returns: np.ndarray,
    volumes: np.ndarray,
    atr: np.ndarray,
    timestamps: np.ndarray,
) -> List[Dict]:
    """
    Detect structural pivot points — candles where multiple novelty signals fire.
    """
    n = min(len(returns), len(volumes) - 1, len(atr) - 1)
    if n < 5:
        return []

    window = max(min(n // 4, 30), 3)
    items = []

    for i in range(window, n):
        score = 0.0
        channels_hit = []

        # Check return outlier
        lookback_r = returns[i - window:i]
        mu_r, sig_r = np.mean(lookback_r), _safe_std(lookback_r)
        z_r = abs(_zscore(returns[i], mu_r, sig_r))
        if z_r > 2.0:
            score += z_r / 5.0
            channels_hit.append("No1_price_novelty")

        # Check volume outlier
        lookback_v = volumes[i + 1 - window:i + 1]
        mu_v, sig_v = np.mean(lookback_v), _safe_std(lookback_v)
        z_v = abs(_zscore(volumes[i + 1], mu_v, sig_v))
        if z_v > 2.0:
            score += z_v / 5.0
            channels_hit.append("No2_volume_novelty")

        # Check ATR outlier
        lookback_a = atr[i + 1 - window:i + 1]
        mu_a, sig_a = np.mean(lookback_a), _safe_std(lookback_a)
        z_a = abs(_zscore(atr[i + 1], mu_a, sig_a))
        if z_a > 2.0:
            score += z_a / 5.0
            channels_hit.append("No3_volatility_break")

        if score > 0.3 and len(channels_hit) >= 2:
            ts_val = timestamps[i + 1] if i + 1 < len(timestamps) else timestamps[-1]
            items.append({
                "index": int(i + 1),
                "timestamp": datetime.fromtimestamp(ts_val, tz=timezone.utc).isoformat(),
                "score": round(float(_clamp(score)), 3),
                "is_breakthrough": bool(score > 0.6),
                "breakthrough_channels": channels_hit,
            })

    # Sort by score, keep top 10
    items.sort(key=lambda x: x["score"], reverse=True)
    return items[:10]


# ---------------------------------------------------------------------------
# Summary generation
# ---------------------------------------------------------------------------

def _generate_summary(
    dhs: float,
    loop_strength: float,
    channels: Dict,
    constellations: List[Dict],
    n_points: int,
    symbol: str,
    timeframe: str,
) -> str:
    """Generate a plain-English structural summary."""
    # Health assessment
    if dhs >= 0.75:
        health = "excellent"
    elif dhs >= 0.55:
        health = "healthy"
    elif dhs >= 0.35:
        health = "below baseline"
    else:
        health = "distressed"

    parts = [
        f"Market structural health for {symbol} ({timeframe}, {n_points} candles): "
        f"DHS {dhs:.2f} ({health})."
    ]

    # Dominant constellation
    if constellations:
        top = constellations[0]
        parts.append(
            f"Primary pattern: {top['detected']} ({top['confidence']:.0%} confidence) "
            f"— {top['plain_description']}."
        )

    # Re/No/Un summary
    re_agg = channels["recurrence"]["aggregate"]
    no_agg = channels["novelty"]["aggregate"]
    un_agg = channels["unity"]["aggregate"]

    if re_agg > 0.6:
        parts.append("High recurrence indicates rigid, repeating market patterns.")
    elif re_agg < 0.3:
        parts.append("Low recurrence suggests volatile, unpredictable dynamics.")

    if un_agg < 0.35:
        parts.append("Low unity — market signals are contradicting each other.")
    elif un_agg > 0.65:
        parts.append("Strong unity — market signals are coherent and aligned.")

    if loop_strength > 0.6:
        parts.append(f"Loop strength {loop_strength:.2f} — market may be stuck in a range.")

    return " ".join(parts)


def _generate_recommendations(
    dhs: float,
    loop_strength: float,
    channels: Dict,
    constellations: List[Dict],
) -> List[str]:
    """Generate actionable structural observations."""
    recs = []

    if dhs < 0.35:
        recs.append("ALERT: Distressed market structure — reduce exposure and wait for clarity.")
    elif dhs < 0.55:
        recs.append("Below-baseline structure — exercise caution, signals may be unreliable.")

    if loop_strength > 0.6:
        recs.append(
            f"High loop strength ({loop_strength:.2f}) — market cycling in narrow regime. "
            "Watch for breakout."
        )

    re_agg = channels["recurrence"]["aggregate"]
    no_agg = channels["novelty"]["aggregate"]
    un_agg = channels["unity"]["aggregate"]

    if no_agg > 0.6 and un_agg < 0.4:
        recs.append(
            "High novelty with low unity indicates chaotic regime — "
            "many disruptions but no coherent direction."
        )

    if channels["unity"]["Un1_price_volume_cohesion"] < 0.35:
        recs.append(
            "Price-volume divergence detected — moves may lack conviction."
        )

    if channels["unity"]["Un2_trend_cohesion"] < 0.35:
        recs.append(
            "Multi-timeframe trend disagreement — conflicting signals across horizons."
        )

    if channels["novelty"]["No3_volatility_break"] > 0.6:
        recs.append(
            "Significant volatility regime breaks detected — risk parameters may need adjustment."
        )

    for c in constellations:
        if c["agent_guidance"]:
            recs.append(f"{c['detected']}: {c['agent_guidance']}")

    if not recs:
        recs.append("Market structure within normal parameters.")

    return recs


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def analyze_financial(
    data: Union[List[Dict], Dict],
    symbol: str = "UNKNOWN",
    timeframe: str = "unknown",
    window: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Analyse financial time series using the 17-channel Re/No/Un framework.

    Args:
        data: OHLCV data as list of dicts, or dict with 'ohlcv'/'klines' key.
              Each dict needs: open, high, low, close, volume.
              Optional: takerBuyVolume, trades, openTime/timestamp.
        symbol: Ticker symbol for metadata.
        timeframe: Candle timeframe (e.g. "1h", "1d") for metadata.
        window: If set, only analyse the last `window` candles.

    Returns:
        ReNoUn-compatible analysis result dict.
    """
    timestamps, opens, highs, lows, closes, volumes, taker_buy_vols, trade_counts = _parse_klines(data)

    # Apply windowing
    if window is not None and window < len(closes):
        sl = slice(-window, None)
        timestamps = timestamps[sl]
        opens = opens[sl]
        highs = highs[sl]
        lows = lows[sl]
        closes = closes[sl]
        volumes = volumes[sl]
        if taker_buy_vols is not None:
            taker_buy_vols = taker_buy_vols[sl]
        if trade_counts is not None:
            trade_counts = trade_counts[sl]

    n = len(closes)

    # Derived series
    returns = _compute_returns(closes)
    atr = _compute_atr(highs, lows, closes, period=min(14, max(n // 5, 2)))

    # --- Compute all 17 channels ---

    # Recurrence
    re1 = _re1_price_pattern(returns)
    re2 = _re2_volume_profile(volumes)
    re3 = _re3_volatility_rhythm(atr)
    re4 = _re4_flow_pattern(taker_buy_vols, volumes)
    re5 = _re5_microstructure(trade_counts, taker_buy_vols, volumes)
    re_agg = (re1 + re2 + re3 + re4 + re5) / 5.0

    # Novelty
    no1 = _no1_price_novelty(returns)
    no2 = _no2_volume_novelty(volumes)
    no3 = _no3_volatility_break(atr)
    no4 = _no4_flow_reversal(taker_buy_vols, volumes)
    no5 = _no5_microstructure_break(trade_counts, taker_buy_vols, volumes)
    no6 = _no6_cross_signal_rarity(returns, volumes, atr, taker_buy_vols)
    no_agg = (no1 + no2 + no3 + no4 + no5 + no6) / 6.0

    # Unity
    un1 = _un1_price_volume_cohesion(returns, volumes)
    un2 = _un2_trend_cohesion(closes)
    un3 = _un3_volatility_cohesion(atr)
    un4 = _un4_flow_cohesion(taker_buy_vols, volumes, returns)
    un5 = _un5_momentum_cohesion(returns)
    un6 = _un6_structural_symmetry(returns, volumes)
    un_agg = (un1 + un2 + un3 + un4 + un5 + un6) / 6.0

    # --- Build channel dict ---
    channels = {
        "recurrence": {
            "Re1_price_pattern": round(re1, 4),
            "Re2_volume_profile": round(re2, 4),
            "Re3_volatility_rhythm": round(re3, 4),
            "Re4_flow_pattern": round(re4, 4),
            "Re5_microstructure": round(re5, 4),
            "aggregate": round(re_agg, 4),
        },
        "novelty": {
            "No1_price_novelty": round(no1, 4),
            "No2_volume_novelty": round(no2, 4),
            "No3_volatility_break": round(no3, 4),
            "No4_flow_reversal": round(no4, 4),
            "No5_microstructure_break": round(no5, 4),
            "No6_cross_signal_rarity": round(no6, 4),
            "aggregate": round(no_agg, 4),
        },
        "unity": {
            "Un1_price_volume_cohesion": round(un1, 4),
            "Un2_trend_cohesion": round(un2, 4),
            "Un3_volatility_cohesion": round(un3, 4),
            "Un4_flow_cohesion": round(un4, 4),
            "Un5_momentum_cohesion": round(un5, 4),
            "Un6_structural_symmetry": round(un6, 4),
            "aggregate": round(un_agg, 4),
        },
    }

    # --- DHS & loop ---
    dd_stress = _compute_drawdown_stress(closes)
    vol_stress = _compute_vol_expansion_stress(atr)
    dhs = _compute_dhs(re_agg, no_agg, un_agg, closes=closes, atr=atr)
    loop = _compute_loop_strength(re_agg, no_agg)

    # --- Constellations ---
    constellations = _detect_constellations(channels, timeframe=timeframe)

    # --- Novelty items ---
    novelty_items = _detect_novelty_items(returns, volumes, atr, timestamps)

    # --- Summary & recommendations ---
    summary = _generate_summary(dhs, loop, channels, constellations, n, symbol, timeframe)
    recommendations = _generate_recommendations(dhs, loop, channels, constellations)

    # --- Result hash ---
    hash_input = f"{dhs}{re_agg}{no_agg}{un_agg}{n}{symbol}"
    result_hash = hashlib.md5(hash_input.encode()).hexdigest()[:8]

    return {
        "dialectical_health": round(dhs, 4),
        "loop_strength": round(loop, 4),
        "channels": channels,
        "stress": {
            "drawdown": round(dd_stress, 4),
            "vol_expansion": round(vol_stress, 4),
        },
        "constellations": constellations,
        "novelty_items": novelty_items,
        "summary": summary,
        "recommendations": recommendations,
        "result_hash": result_hash,
        "_meta": {
            "engine_version": ENGINE_VERSION,
            "data_points": n,
            "symbol": symbol,
            "timeframe": timeframe,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    }


def health_check_financial(
    data: Union[List[Dict], Dict],
    symbol: str = "UNKNOWN",
    timeframe: str = "unknown",
) -> Dict[str, Any]:
    """
    Fast structural triage for financial data.
    Returns DHS, dominant constellation, and one-line summary.
    """
    result = analyze_financial(data, symbol=symbol, timeframe=timeframe)

    constellation = "NONE"
    if result["constellations"]:
        constellation = result["constellations"][0]["detected"]

    if result["dialectical_health"] >= 0.75:
        assessment = "Excellent"
    elif result["dialectical_health"] >= 0.55:
        assessment = "Healthy"
    elif result["dialectical_health"] >= 0.35:
        assessment = "Below baseline"
    else:
        assessment = "Distressed"

    return {
        "dialectical_health": result["dialectical_health"],
        "pattern": constellation,
        "assessment": assessment,
        "loop_strength": result["loop_strength"],
        "summary": result["summary"],
        "_meta": result["_meta"],
    }


# ---------------------------------------------------------------------------
# CLI for quick testing
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) < 2:
        print("Usage: python renoun_finance.py <path-to-klines.json> [symbol] [timeframe]")
        print("  JSON should contain a 'klines' array or be a bare array of OHLCV dicts.")
        sys.exit(1)

    path = sys.argv[1]
    sym = sys.argv[2] if len(sys.argv) > 2 else "UNKNOWN"
    tf = sys.argv[3] if len(sys.argv) > 3 else "unknown"

    with open(path) as f:
        raw = json.load(f)

    klines = raw.get("klines", raw) if isinstance(raw, dict) else raw

    result = analyze_financial(klines, symbol=sym, timeframe=tf)

    print(json.dumps(result, indent=2))
