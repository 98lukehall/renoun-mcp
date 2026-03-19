"""
ReNoUn Risk Gate Strategy for Freqtrade
========================================

A structural risk overlay that checks market regime before every trade.
Works with ANY Freqtrade strategy as a pre-trade filter.

How it works:
  - Before every trade entry, calls the ReNoUn regime API
  - GREEN  (bounded)  → full position, normal entry
  - YELLOW (active)   → scaled position via exposure scalar
  - RED    (unstable) → trade blocked entirely

Setup:
  1. Get a free API key: POST https://web-production-817e2.up.railway.app/v1/keys/provision
     Body: {"email": "you@example.com", "agent_name": "freqtrade"}

  2. Add to your Freqtrade config.json:
     "renoun_api_key": "rn_agent_YOUR_KEY"

  3. Drop this file in user_data/strategies/
  4. Run: freqtrade trade --strategy ReNoUnRiskGate

Standalone or composable:
  - Use directly: has simple EMA crossover entries built in
  - Or subclass it: override populate_entry/exit_trend in your own strategy
    and inherit the risk gate from confirm_trade_entry + custom_stake_amount

Docs: https://harrisoncollab.com/agents
Dashboard: https://harrisoncollab.com/dashboard
"""

import logging
import time
from datetime import datetime, timezone
from functools import lru_cache
from typing import Optional

import requests
from freqtrade.strategy import IStrategy, stoploss_from_open
from freqtrade.persistence import Trade
import freqtrade.vendor.qtpylib.indicators as qtpylib
import talib.abstract as ta
from pandas import DataFrame


logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ReNoUn API Client
# ---------------------------------------------------------------------------

RENOUN_BASE = "https://web-production-817e2.up.railway.app"
REGIME_CACHE_SECONDS = 60  # Cache regime for 60s (API-side cache is also 60s)

# In-memory cache: {symbol: (timestamp, response)}
_regime_cache: dict = {}


def check_regime(symbol: str, api_key: str, timeout: int = 10) -> dict:
    """
    Call the ReNoUn regime API for a trading pair.

    Returns dict with keys:
      regime: "bounded" | "active" | "unstable"
      action: "proceed" | "reduce" | "avoid"
      exposure: float (0.0 - 1.0)
      dhs: float (0.0 - 1.0)
      constellation: str
      stability: dict with halflife_minutes, urgency, etc.

    Returns a safe fallback on any error (action=reduce, exposure=0.5).
    """
    # Check cache
    now = time.time()
    if symbol in _regime_cache:
        cached_at, cached_resp = _regime_cache[symbol]
        if now - cached_at < REGIME_CACHE_SECONDS:
            return cached_resp

    # Map Freqtrade pair format (BTC/USDT) to Binance format (BTCUSDT)
    binance_symbol = symbol.replace("/", "")

    try:
        resp = requests.get(
            f"{RENOUN_BASE}/v1/regime/live/{binance_symbol}",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()

        # Cache it
        _regime_cache[symbol] = (now, data)
        return data

    except requests.RequestException as e:
        logger.warning(f"ReNoUn API error for {symbol}: {e}. Using safe fallback.")
        return {
            "regime": "active",
            "action": "reduce",
            "exposure": 0.5,
            "dhs": 0.5,
            "constellation": "UNKNOWN",
            "stability": {
                "halflife_minutes": 60,
                "stability_score": 0.5,
                "instability_risk": "moderate",
                "urgency": "watch",
            },
        }


# ---------------------------------------------------------------------------
# Freqtrade Strategy
# ---------------------------------------------------------------------------

class ReNoUnRiskGate(IStrategy):
    """
    Freqtrade strategy with ReNoUn structural risk gating.

    The stoplight:
      GREEN  (bounded)  → trade at full size
      YELLOW (active)   → trade at reduced size (exposure scalar)
      RED    (unstable) → no trade

    Entry logic: simple EMA 8/21 crossover (replace with your own).
    The value is in the risk gate, not the entries.
    """

    # --- Strategy settings ---
    INTERFACE_VERSION = 3
    timeframe = "1h"

    # ROI: let winners run, the risk gate handles the losers
    minimal_roi = {
        "0": 0.05,     # 5% take profit
        "120": 0.03,   # 3% after 2h
        "240": 0.01,   # 1% after 4h
    }

    stoploss = -0.03  # 3% stoploss (tight — we trust the regime filter)
    trailing_stop = True
    trailing_stop_positive = 0.01
    trailing_stop_positive_offset = 0.02
    trailing_only_offset_is_reached = True

    # --- ReNoUn settings ---
    # Set renoun_api_key in your config.json
    # Block trades when regime is unstable
    renoun_block_unstable = True
    # Scale position size by exposure scalar for active regimes
    renoun_scale_active = True
    # Minimum exposure scalar to allow a trade (below this, skip)
    renoun_min_exposure = 0.3
    # Exit immediately if urgency is "exit_now"
    renoun_honor_exit_urgency = True

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        self.renoun_api_key = config.get("renoun_api_key", "")
        if not self.renoun_api_key:
            logger.warning(
                "ReNoUn API key not set. Add 'renoun_api_key' to config.json. "
                "Get a free key: POST %s/v1/keys/provision", RENOUN_BASE
            )

    # ------------------------------------------------------------------
    # Entry signals (simple EMA crossover — replace with your own logic)
    # ------------------------------------------------------------------

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["ema_fast"] = ta.EMA(dataframe, timeperiod=8)
        dataframe["ema_slow"] = ta.EMA(dataframe, timeperiod=21)
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                qtpylib.crossed_above(dataframe["ema_fast"], dataframe["ema_slow"])
                & (dataframe["rsi"] < 70)
                & (dataframe["volume"] > 0)
            ),
            "enter_long",
        ] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                qtpylib.crossed_below(dataframe["ema_fast"], dataframe["ema_slow"])
                | (dataframe["rsi"] > 80)
            ),
            "exit_long",
        ] = 1
        return dataframe

    # ------------------------------------------------------------------
    # THE RISK GATE — this is where ReNoUn does its job
    # ------------------------------------------------------------------

    def confirm_trade_entry(
        self,
        pair: str,
        order_type: str,
        amount: float,
        rate: float,
        time_in_force: str,
        current_time: datetime,
        entry_tag: Optional[str],
        side: str,
        **kwargs,
    ) -> bool:
        """
        Called before every trade entry. This is the stoplight.

        Returns False to block the trade entirely.
        """
        if not self.renoun_api_key:
            return True  # No key configured, let everything through

        regime = check_regime(pair, self.renoun_api_key)
        action = regime.get("action", "proceed")
        regime_type = regime.get("regime", "bounded")
        exposure = regime.get("exposure", 1.0)
        urgency = regime.get("stability", {}).get("urgency", "none")
        constellation = regime.get("constellation", "UNKNOWN")
        dhs = regime.get("dhs", 0.5)

        # RED — block unstable regimes
        if self.renoun_block_unstable and action == "avoid":
            logger.info(
                f"RENOUN BLOCKED {pair}: {regime_type} regime "
                f"({constellation}, DHS={dhs:.2f}). Trade skipped."
            )
            return False

        # YELLOW — check if exposure is too low to bother
        if action == "reduce" and exposure < self.renoun_min_exposure:
            logger.info(
                f"RENOUN BLOCKED {pair}: exposure too low "
                f"({exposure:.2f} < {self.renoun_min_exposure}). Trade skipped."
            )
            return False

        # Check urgency — don't enter if exit is imminent
        if urgency in ("exit_now", "prepare_exit"):
            logger.info(
                f"RENOUN BLOCKED {pair}: urgency={urgency}. "
                f"Regime transition imminent. Trade skipped."
            )
            return False

        # GREEN or acceptable YELLOW — allow
        logger.info(
            f"RENOUN ALLOWED {pair}: {regime_type} ({constellation}, "
            f"DHS={dhs:.2f}, exposure={exposure:.2f}, urgency={urgency})"
        )
        return True

    def custom_stake_amount(
        self,
        pair: str,
        current_time: datetime,
        current_rate: float,
        proposed_stake: float,
        min_stake: Optional[float],
        max_stake: float,
        leverage: float,
        entry_tag: Optional[str],
        side: str,
        **kwargs,
    ) -> float:
        """
        Scale position size by the ReNoUn exposure scalar.

        Bounded regime → full size
        Active regime  → reduced by exposure scalar (e.g., 0.7 = 70% size)
        """
        if not self.renoun_api_key or not self.renoun_scale_active:
            return proposed_stake

        regime = check_regime(pair, self.renoun_api_key)
        exposure = regime.get("exposure", 1.0)
        action = regime.get("action", "proceed")

        if action == "reduce":
            scaled = proposed_stake * exposure
            logger.info(
                f"RENOUN SCALED {pair}: {proposed_stake:.4f} → "
                f"{scaled:.4f} (exposure={exposure:.2f})"
            )
            return max(scaled, min_stake or 0)

        return proposed_stake

    # confirm_trade_exit always returns True — regime-aware exits
    # are handled by custom_exit below, which can initiate exits proactively.

    def custom_exit(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs,
    ) -> Optional[str]:
        """
        Force exit if ReNoUn says exit_now, regardless of strategy signals.
        """
        if not self.renoun_api_key or not self.renoun_honor_exit_urgency:
            return None

        regime = check_regime(pair, self.renoun_api_key)
        urgency = regime.get("stability", {}).get("urgency", "none")

        if urgency == "exit_now":
            halflife = regime.get("stability", {}).get("halflife_minutes", 0)
            logger.warning(
                f"RENOUN EXIT_NOW {pair}: structure fragmenting, "
                f"halflife={halflife:.0f}m. Forcing exit at {current_profit:.2%} P/L."
            )
            return "renoun_exit_now"

        return None
