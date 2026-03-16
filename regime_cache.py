"""
60-second TTL cache for live regime checks.
Prevents hammering Binance if 100 agents all check BTC in the same minute.
"""

import time
import threading
from typing import List, Optional


class RegimeCache:
    def __init__(self, ttl_seconds=60, max_dhs_history=10):
        self._cache = {}  # {(symbol, timeframe): (result_dict, timestamp)}
        self._ttl = ttl_seconds
        self._dhs_history = {}  # {symbol: [dhs_values]} — rolling last N
        self._max_history = max_dhs_history
        self._lock = threading.Lock()

    def get(self, symbol: str, timeframe: str) -> Optional[dict]:
        """Return cached result if fresh, else None."""
        with self._lock:
            key = (symbol, timeframe)
            if key not in self._cache:
                return None
            result, ts = self._cache[key]
            if time.time() - ts > self._ttl:
                del self._cache[key]
                return None
            return result

    def set(self, symbol: str, timeframe: str, result: dict):
        """Cache a result."""
        with self._lock:
            self._cache[(symbol, timeframe)] = (result, time.time())

    def record_dhs(self, symbol: str, dhs: float):
        """Append DHS to rolling history for momentum calculation."""
        with self._lock:
            if symbol not in self._dhs_history:
                self._dhs_history[symbol] = []
            self._dhs_history[symbol].append(dhs)
            if len(self._dhs_history[symbol]) > self._max_history:
                self._dhs_history[symbol] = self._dhs_history[symbol][-self._max_history:]

    def get_dhs_history(self, symbol: str) -> List[float]:
        """Get rolling DHS history for a symbol."""
        with self._lock:
            return list(self._dhs_history.get(symbol, []))

    def clear(self):
        """Clear all cached entries."""
        with self._lock:
            self._cache.clear()
            self._dhs_history.clear()


# Module-level singleton
regime_cache = RegimeCache()
