#!/usr/bin/env python3
"""
Comprehensive tests for ReNoUn Finance MCP tool.

Tests:
  1. Server handler (tool_finance_analyze) — happy path, structure, errors
  2. API endpoint (POST /v1/finance/analyze) — auth, tiers, validation

Run:
    python3 tests/test_finance.py
    # or
    pytest tests/test_finance.py -v
"""

import sys
import os
import json
import shutil
import tempfile

# Ensure we can import from the parent directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Isolate test state — set HOME before importing anything that uses it
_orig_home = os.environ.get("HOME")
_tmpdir = tempfile.mkdtemp(prefix="renoun_finance_test_")
os.environ["HOME"] = _tmpdir


# ---------------------------------------------------------------------------
# Lazy imports (deferred until test execution so HOME is set first)
# ---------------------------------------------------------------------------

_server_imported = False
_api_imported = False


def _ensure_server():
    global _server_imported
    if not _server_imported:
        from server import tool_finance_analyze  # noqa: F401
        _server_imported = True


def _ensure_api():
    global _api_imported
    if not _api_imported:
        from fastapi.testclient import TestClient  # noqa: F401
        from api import app  # noqa: F401
        from auth import create_key  # noqa: F401
        _api_imported = True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def assert_keys(data, keys, context=""):
    """Assert that all keys are present in data dict."""
    missing = [k for k in keys if k not in data]
    assert not missing, f"Missing keys in {context}: {missing}. Got: {list(data.keys())}"


def assert_type(value, expected_type, context=""):
    """Assert value is of expected type."""
    assert isinstance(value, expected_type), (
        f"{context}: expected {expected_type.__name__}, got {type(value).__name__}"
    )


def assert_range(value, low, high, context=""):
    """Assert value is within [low, high]."""
    assert low <= value <= high, (
        f"{context}: expected {low} <= {value} <= {high}"
    )


# ---------------------------------------------------------------------------
# Data generation
# ---------------------------------------------------------------------------

def generate_klines(n=50, start_price=100.0, volatility=0.02):
    """Generate synthetic OHLCV candle data for testing."""
    import random
    random.seed(42)
    klines = []
    price = start_price
    for i in range(n):
        change = random.gauss(0, volatility) * price
        open_p = price
        close_p = price + change
        high_p = max(open_p, close_p) * (1 + abs(random.gauss(0, volatility / 2)))
        low_p = min(open_p, close_p) * (1 - abs(random.gauss(0, volatility / 2)))
        volume = random.uniform(100, 1000)
        klines.append({
            "open": open_p,
            "high": high_p,
            "low": low_p,
            "close": close_p,
            "volume": volume,
        })
        price = close_p
    return klines


def generate_klines_with_taker(n=50, start_price=100.0, volatility=0.02):
    """Generate OHLCV + taker_buy_volume data."""
    import random
    random.seed(42)
    klines = []
    price = start_price
    for i in range(n):
        change = random.gauss(0, volatility) * price
        open_p = price
        close_p = price + change
        high_p = max(open_p, close_p) * (1 + abs(random.gauss(0, volatility / 2)))
        low_p = min(open_p, close_p) * (1 - abs(random.gauss(0, volatility / 2)))
        volume = random.uniform(100, 1000)
        taker_buy = volume * random.uniform(0.3, 0.7)
        klines.append({
            "open": open_p,
            "high": high_p,
            "low": low_p,
            "close": close_p,
            "volume": volume,
            "taker_buy_volume": taker_buy,
        })
        price = close_p
    return klines


def generate_trending_klines(n=50, start_price=100.0, trend=0.01):
    """Generate klines with a strong upward trend for predictable structure."""
    import random
    random.seed(99)
    klines = []
    price = start_price
    for i in range(n):
        change = trend * price + random.gauss(0, 0.005) * price
        open_p = price
        close_p = price + change
        high_p = max(open_p, close_p) * 1.005
        low_p = min(open_p, close_p) * 0.995
        volume = random.uniform(500, 1500)
        klines.append({
            "open": open_p,
            "high": high_p,
            "low": low_p,
            "close": close_p,
            "volume": volume,
        })
        price = close_p
    return klines


def generate_volatile_klines(n=50, start_price=100.0, volatility=0.08):
    """Generate highly volatile klines for stress testing."""
    import random
    random.seed(77)
    klines = []
    price = start_price
    for i in range(n):
        change = random.gauss(0, volatility) * price
        open_p = price
        close_p = price + change
        high_p = max(open_p, close_p) * (1 + abs(random.gauss(0, volatility)))
        low_p = min(open_p, close_p) * (1 - abs(random.gauss(0, volatility)))
        # Ensure low_p stays positive
        low_p = max(low_p, 0.01)
        volume = random.uniform(100, 5000)
        klines.append({
            "open": open_p,
            "high": high_p,
            "low": low_p,
            "close": close_p,
            "volume": volume,
        })
        price = max(close_p, 0.01)
    return klines


# Pre-generate test datasets
KLINES_50 = generate_klines(50)
KLINES_100 = generate_klines(100)
KLINES_WITH_TAKER = generate_klines_with_taker(50)
KLINES_TRENDING = generate_trending_klines(50)
KLINES_VOLATILE = generate_volatile_klines(50)
KLINES_MINIMAL = generate_klines(10)  # Minimum valid count


VALID_CONSTELLATIONS = {
    "CLOSED_LOOP", "HIGH_SYMMETRY", "PATTERN_BREAK", "CONVERGENCE",
    "SCATTERING", "REPEATED_DISRUPTION", "DIP_AND_RECOVERY", "SURFACE_VARIATION",
}

VALID_TIMEFRAMES = {"1m", "5m", "15m", "1h", "4h", "1d"}


# ---------------------------------------------------------------------------
# Server Handler Tests
# ---------------------------------------------------------------------------

class TestFinanceMCP:
    """Test tool_finance_analyze server handler."""

    # --- Happy Path ---

    def test_happy_path_basic(self):
        """Basic 50-candle analysis returns valid result."""
        from server import tool_finance_analyze
        result = tool_finance_analyze({"klines": KLINES_50})
        assert "error" not in result, f"Unexpected error: {result.get('error')}"
        assert_keys(result, [
            "dialectical_health", "loop_strength", "channels",
            "constellations", "stress", "_meta", "summary",
        ], "finance result")

    def test_happy_path_100_candles(self):
        """100-candle analysis returns valid result."""
        from server import tool_finance_analyze
        result = tool_finance_analyze({"klines": KLINES_100})
        assert "error" not in result, f"Unexpected error: {result.get('error')}"
        assert_keys(result, ["dialectical_health", "channels", "constellations"], "100 candle result")

    def test_happy_path_with_taker_volume(self):
        """Analysis with taker_buy_volume field works."""
        from server import tool_finance_analyze
        result = tool_finance_analyze({"klines": KLINES_WITH_TAKER})
        assert "error" not in result, f"Unexpected error: {result.get('error')}"
        assert_keys(result, ["dialectical_health", "channels"], "taker volume result")

    def test_happy_path_minimal_candles(self):
        """Exactly 10 candles (minimum) should succeed."""
        from server import tool_finance_analyze
        result = tool_finance_analyze({"klines": KLINES_MINIMAL})
        assert "error" not in result, f"Unexpected error: {result.get('error')}"

    def test_trending_data(self):
        """Trending data produces valid analysis."""
        from server import tool_finance_analyze
        result = tool_finance_analyze({"klines": KLINES_TRENDING})
        assert "error" not in result, f"Unexpected error: {result.get('error')}"
        assert 0.0 <= result["dialectical_health"] <= 1.0

    def test_volatile_data(self):
        """Highly volatile data produces valid analysis without crashing."""
        from server import tool_finance_analyze
        result = tool_finance_analyze({"klines": KLINES_VOLATILE})
        assert "error" not in result, f"Unexpected error: {result.get('error')}"
        assert 0.0 <= result["dialectical_health"] <= 1.0

    # --- DHS Value Validation ---

    def test_dhs_range(self):
        """DHS must be between 0.0 and 1.0."""
        from server import tool_finance_analyze
        result = tool_finance_analyze({"klines": KLINES_50})
        assert_range(result["dialectical_health"], 0.0, 1.0, "DHS")

    def test_dhs_is_float(self):
        """DHS should be a float."""
        from server import tool_finance_analyze
        result = tool_finance_analyze({"klines": KLINES_50})
        assert_type(result["dialectical_health"], float, "DHS type")

    def test_loop_strength_range(self):
        """loop_strength must be between 0.0 and 1.0."""
        from server import tool_finance_analyze
        result = tool_finance_analyze({"klines": KLINES_50})
        assert_range(result["loop_strength"], 0.0, 1.0, "loop_strength")

    # --- Channel Structure Validation ---

    def test_channels_top_level_keys(self):
        """Channels dict has recurrence, novelty, unity sections."""
        from server import tool_finance_analyze
        result = tool_finance_analyze({"klines": KLINES_50})
        channels = result["channels"]
        assert_keys(channels, ["recurrence", "novelty", "unity"], "channels")

    def test_recurrence_channels(self):
        """All 5 recurrence channels present with aggregate."""
        from server import tool_finance_analyze
        result = tool_finance_analyze({"klines": KLINES_50})
        rec = result["channels"]["recurrence"]
        expected_keys = [
            "Re1_price_pattern", "Re2_volume_profile", "Re3_volatility_rhythm",
            "Re4_flow_pattern", "Re5_microstructure", "aggregate",
        ]
        assert_keys(rec, expected_keys, "recurrence channels")

    def test_novelty_channels(self):
        """All 6 novelty channels present with aggregate."""
        from server import tool_finance_analyze
        result = tool_finance_analyze({"klines": KLINES_50})
        nov = result["channels"]["novelty"]
        expected_keys = [
            "No1_price_novelty", "No2_volume_novelty", "No3_volatility_break",
            "No4_flow_reversal", "No5_microstructure_break", "No6_cross_signal_rarity",
            "aggregate",
        ]
        assert_keys(nov, expected_keys, "novelty channels")

    def test_unity_channels(self):
        """All 6 unity channels present with aggregate."""
        from server import tool_finance_analyze
        result = tool_finance_analyze({"klines": KLINES_50})
        uni = result["channels"]["unity"]
        expected_keys = [
            "Un1_price_volume_cohesion", "Un2_trend_cohesion", "Un3_volatility_cohesion",
            "Un4_flow_cohesion", "Un5_momentum_cohesion", "Un6_structural_symmetry",
            "aggregate",
        ]
        assert_keys(uni, expected_keys, "unity channels")

    def test_all_channel_values_in_range(self):
        """Every individual channel value must be in [0.0, 1.0]."""
        from server import tool_finance_analyze
        result = tool_finance_analyze({"klines": KLINES_50})
        channels = result["channels"]
        for dimension in ["recurrence", "novelty", "unity"]:
            for key, value in channels[dimension].items():
                assert_range(value, 0.0, 1.0, f"channels.{dimension}.{key}")

    def test_17_channels_total(self):
        """Exactly 17 channels (5 Re + 6 No + 6 Un) plus 3 aggregates."""
        from server import tool_finance_analyze
        result = tool_finance_analyze({"klines": KLINES_50})
        channels = result["channels"]
        re_count = len([k for k in channels["recurrence"] if k != "aggregate"])
        no_count = len([k for k in channels["novelty"] if k != "aggregate"])
        un_count = len([k for k in channels["unity"] if k != "aggregate"])
        total = re_count + no_count + un_count
        assert total == 17, f"Expected 17 channels, got {total} (Re:{re_count} No:{no_count} Un:{un_count})"

    # --- Constellation Detection ---

    def test_constellations_is_list(self):
        """Constellations field is a list."""
        from server import tool_finance_analyze
        result = tool_finance_analyze({"klines": KLINES_50})
        assert_type(result["constellations"], list, "constellations type")

    def test_constellation_names_valid(self):
        """All detected constellations have valid pattern names."""
        from server import tool_finance_analyze
        result = tool_finance_analyze({"klines": KLINES_50})
        for c in result["constellations"]:
            assert c["detected"] in VALID_CONSTELLATIONS, (
                f"Unknown constellation: {c['detected']}. Valid: {VALID_CONSTELLATIONS}"
            )

    def test_constellation_structure(self):
        """Each constellation dict has required fields."""
        from server import tool_finance_analyze
        result = tool_finance_analyze({"klines": KLINES_100})
        for c in result["constellations"]:
            assert_keys(c, ["detected", "confidence"], f"constellation {c.get('detected', '?')}")
            assert_range(c["confidence"], 0.0, 1.0, f"constellation {c['detected']} confidence")

    def test_constellation_has_description_fields(self):
        """Each constellation includes plain_description and channel_legend."""
        from server import tool_finance_analyze
        result = tool_finance_analyze({"klines": KLINES_100})
        for c in result["constellations"]:
            assert_keys(c, ["plain_description", "channel_legend"],
                        f"constellation {c.get('detected', '?')} description fields")

    # --- Stress Field ---

    def test_stress_present(self):
        """Stress field is present with drawdown and vol_expansion."""
        from server import tool_finance_analyze
        result = tool_finance_analyze({"klines": KLINES_50})
        assert_keys(result, ["stress"], "result")
        assert_keys(result["stress"], ["drawdown", "vol_expansion"], "stress")

    def test_stress_values_are_floats(self):
        """Stress values are floats."""
        from server import tool_finance_analyze
        result = tool_finance_analyze({"klines": KLINES_50})
        assert_type(result["stress"]["drawdown"], float, "stress.drawdown")
        assert_type(result["stress"]["vol_expansion"], float, "stress.vol_expansion")

    def test_stress_drawdown_non_negative(self):
        """Drawdown stress should be >= 0."""
        from server import tool_finance_analyze
        result = tool_finance_analyze({"klines": KLINES_50})
        assert result["stress"]["drawdown"] >= 0.0, (
            f"Drawdown stress should be >= 0, got {result['stress']['drawdown']}"
        )

    # --- Exposure (include_exposure=True) ---

    def test_exposure_included_by_default(self):
        """Exposure field is present when include_exposure is not specified (default True)."""
        from server import tool_finance_analyze
        result = tool_finance_analyze({"klines": KLINES_50})
        assert "exposure" in result, "exposure field missing (should be included by default)"

    def test_exposure_explicit_true(self):
        """Exposure field is present when include_exposure=True."""
        from server import tool_finance_analyze
        result = tool_finance_analyze({"klines": KLINES_50, "include_exposure": True})
        assert "exposure" in result, "exposure field missing with include_exposure=True"

    def test_exposure_scalar_range(self):
        """Exposure scalar must be between 0.0 and 1.0."""
        from server import tool_finance_analyze
        result = tool_finance_analyze({"klines": KLINES_50, "include_exposure": True})
        exposure = result.get("exposure", {})
        if "error" not in exposure:
            assert_range(exposure["scalar"], 0.0, 1.0, "exposure.scalar")

    def test_exposure_has_interpretation(self):
        """Exposure includes interpretation string."""
        from server import tool_finance_analyze
        result = tool_finance_analyze({"klines": KLINES_50, "include_exposure": True})
        exposure = result.get("exposure", {})
        if "error" not in exposure:
            assert "interpretation" in exposure, "exposure missing interpretation"
            assert_type(exposure["interpretation"], str, "exposure.interpretation")

    def test_exposure_has_note(self):
        """Exposure includes a usage note."""
        from server import tool_finance_analyze
        result = tool_finance_analyze({"klines": KLINES_50, "include_exposure": True})
        exposure = result.get("exposure", {})
        if "error" not in exposure:
            assert "note" in exposure, "exposure missing note"

    def test_exposure_scalar_is_float(self):
        """Exposure scalar is a float."""
        from server import tool_finance_analyze
        result = tool_finance_analyze({"klines": KLINES_50, "include_exposure": True})
        exposure = result.get("exposure", {})
        if "error" not in exposure:
            assert_type(exposure["scalar"], float, "exposure.scalar type")

    # --- Exposure v2 enriched fields ---

    def test_exposure_raw_v1_present(self):
        """Exposure includes raw_v1 (unsmoothed exposure)."""
        from server import tool_finance_analyze
        result = tool_finance_analyze({"klines": KLINES_50, "include_exposure": True})
        exposure = result.get("exposure", {})
        if "error" not in exposure:
            assert "raw_v1" in exposure, "exposure missing raw_v1"
            assert_type(exposure["raw_v1"], float, "exposure.raw_v1 type")
            assert_range(exposure["raw_v1"], 0.0, 1.0, "exposure.raw_v1")

    def test_exposure_smoothed_v2_present(self):
        """Exposure includes smoothed_v2 (EMA-smoothed exposure)."""
        from server import tool_finance_analyze
        result = tool_finance_analyze({"klines": KLINES_50, "include_exposure": True})
        exposure = result.get("exposure", {})
        if "error" not in exposure:
            assert "smoothed_v2" in exposure, "exposure missing smoothed_v2"
            assert_type(exposure["smoothed_v2"], float, "exposure.smoothed_v2 type")
            assert_range(exposure["smoothed_v2"], 0.0, 1.0, "exposure.smoothed_v2")

    def test_exposure_scalar_equals_smoothed_v2(self):
        """scalar should equal smoothed_v2 (primary recommendation is the smoothed value)."""
        from server import tool_finance_analyze
        result = tool_finance_analyze({"klines": KLINES_50, "include_exposure": True})
        exposure = result.get("exposure", {})
        if "error" not in exposure:
            assert exposure["scalar"] == exposure["smoothed_v2"], (
                f"scalar ({exposure['scalar']}) != smoothed_v2 ({exposure['smoothed_v2']})"
            )

    def test_exposure_constellation_persistence_present(self):
        """Exposure includes constellation_persistence (run_length from tracker)."""
        from server import tool_finance_analyze
        result = tool_finance_analyze({"klines": KLINES_50, "include_exposure": True})
        exposure = result.get("exposure", {})
        if "error" not in exposure:
            assert "constellation_persistence" in exposure, "exposure missing constellation_persistence"
            assert_type(exposure["constellation_persistence"], int, "exposure.constellation_persistence type")
            assert exposure["constellation_persistence"] >= 1, (
                f"constellation_persistence must be >= 1 (first observation), got {exposure['constellation_persistence']}"
            )

    def test_exposure_constellation_churn_present(self):
        """Exposure includes constellation_churn (unique constellations / window)."""
        from server import tool_finance_analyze
        result = tool_finance_analyze({"klines": KLINES_50, "include_exposure": True})
        exposure = result.get("exposure", {})
        if "error" not in exposure:
            assert "constellation_churn" in exposure, "exposure missing constellation_churn"
            assert_type(exposure["constellation_churn"], float, "exposure.constellation_churn type")
            assert_range(exposure["constellation_churn"], 0.0, 1.0, "exposure.constellation_churn")

    def test_exposure_all_enriched_keys(self):
        """Exposure dict has all expected keys: scalar, raw_v1, smoothed_v2,
        constellation_persistence, constellation_churn, interpretation, note."""
        from server import tool_finance_analyze
        result = tool_finance_analyze({"klines": KLINES_50, "include_exposure": True})
        exposure = result.get("exposure", {})
        if "error" not in exposure:
            expected_keys = [
                "scalar", "raw_v1", "smoothed_v2",
                "constellation_persistence", "constellation_churn",
                "interpretation", "note",
            ]
            assert_keys(exposure, expected_keys, "exposure enriched")

    def test_exposure_volatile_data(self):
        """Exposure fields are valid even with highly volatile input data."""
        from server import tool_finance_analyze
        result = tool_finance_analyze({"klines": KLINES_VOLATILE, "include_exposure": True})
        exposure = result.get("exposure", {})
        if "error" not in exposure:
            assert_range(exposure["scalar"], 0.0, 1.0, "volatile exposure.scalar")
            assert_range(exposure["raw_v1"], 0.0, 1.0, "volatile exposure.raw_v1")
            assert_range(exposure["smoothed_v2"], 0.0, 1.0, "volatile exposure.smoothed_v2")
            assert exposure["constellation_persistence"] >= 1

    def test_exposure_trending_data(self):
        """Exposure fields are valid with strongly trending input data."""
        from server import tool_finance_analyze
        result = tool_finance_analyze({"klines": KLINES_TRENDING, "include_exposure": True})
        exposure = result.get("exposure", {})
        if "error" not in exposure:
            assert_range(exposure["scalar"], 0.0, 1.0, "trending exposure.scalar")
            assert_range(exposure["raw_v1"], 0.0, 1.0, "trending exposure.raw_v1")
            assert exposure["constellation_persistence"] >= 1

    # --- Exposure (include_exposure=False) ---

    def test_exposure_excluded(self):
        """Exposure field is absent when include_exposure=False."""
        from server import tool_finance_analyze
        result = tool_finance_analyze({"klines": KLINES_50, "include_exposure": False})
        assert "exposure" not in result, (
            f"exposure field should be absent with include_exposure=False, got: {result.get('exposure')}"
        )

    # --- Metadata ---

    def test_meta_present(self):
        """_meta block is present with expected fields."""
        from server import tool_finance_analyze
        result = tool_finance_analyze({"klines": KLINES_50})
        assert_keys(result, ["_meta"], "result")
        assert_keys(result["_meta"], ["data_points", "symbol", "timeframe", "timestamp"], "_meta")

    def test_meta_data_points(self):
        """_meta.data_points matches input candle count."""
        from server import tool_finance_analyze
        result = tool_finance_analyze({"klines": KLINES_50})
        assert result["_meta"]["data_points"] == 50, (
            f"Expected data_points=50, got {result['_meta']['data_points']}"
        )

    def test_default_symbol(self):
        """Default symbol is UNKNOWN when not specified."""
        from server import tool_finance_analyze
        result = tool_finance_analyze({"klines": KLINES_50})
        assert result["_meta"]["symbol"] == "UNKNOWN", (
            f"Expected symbol='UNKNOWN', got '{result['_meta']['symbol']}'"
        )

    def test_default_timeframe(self):
        """Default timeframe is 1h when not specified."""
        from server import tool_finance_analyze
        result = tool_finance_analyze({"klines": KLINES_50})
        assert result["_meta"]["timeframe"] == "1h", (
            f"Expected timeframe='1h', got '{result['_meta']['timeframe']}'"
        )

    def test_custom_symbol_passthrough(self):
        """Custom symbol is passed through to _meta."""
        from server import tool_finance_analyze
        result = tool_finance_analyze({"klines": KLINES_50, "symbol": "BTCUSDT"})
        assert result["_meta"]["symbol"] == "BTCUSDT", (
            f"Expected symbol='BTCUSDT', got '{result['_meta']['symbol']}'"
        )

    def test_custom_timeframe_passthrough(self):
        """Custom timeframe is passed through to _meta."""
        from server import tool_finance_analyze
        result = tool_finance_analyze({"klines": KLINES_50, "timeframe": "4h"})
        assert result["_meta"]["timeframe"] == "4h", (
            f"Expected timeframe='4h', got '{result['_meta']['timeframe']}'"
        )

    def test_timestamp_present(self):
        """_meta.timestamp is a non-empty string (ISO format)."""
        from server import tool_finance_analyze
        result = tool_finance_analyze({"klines": KLINES_50})
        ts = result["_meta"]["timestamp"]
        assert_type(ts, str, "_meta.timestamp")
        assert len(ts) > 0, "_meta.timestamp should not be empty"

    # --- Result Hash ---

    def test_result_hash_present(self):
        """result_hash is present and is a string."""
        from server import tool_finance_analyze
        result = tool_finance_analyze({"klines": KLINES_50})
        assert "result_hash" in result, "result_hash missing"
        assert_type(result["result_hash"], str, "result_hash")

    def test_result_hash_deterministic(self):
        """Same input produces same result_hash."""
        from server import tool_finance_analyze
        r1 = tool_finance_analyze({"klines": KLINES_50})
        r2 = tool_finance_analyze({"klines": KLINES_50})
        assert r1["result_hash"] == r2["result_hash"], (
            f"Hashes differ: {r1['result_hash']} != {r2['result_hash']}"
        )

    # --- Summary & Recommendations ---

    def test_summary_present(self):
        """Summary is a non-empty string."""
        from server import tool_finance_analyze
        result = tool_finance_analyze({"klines": KLINES_50})
        assert "summary" in result, "summary missing"
        assert_type(result["summary"], str, "summary")
        assert len(result["summary"]) > 0, "summary should not be empty"

    def test_recommendations_present(self):
        """Recommendations is a list."""
        from server import tool_finance_analyze
        result = tool_finance_analyze({"klines": KLINES_50})
        assert "recommendations" in result, "recommendations missing"
        assert_type(result["recommendations"], list, "recommendations")

    def test_novelty_items_present(self):
        """novelty_items is a list."""
        from server import tool_finance_analyze
        result = tool_finance_analyze({"klines": KLINES_50})
        assert "novelty_items" in result, "novelty_items missing"
        assert_type(result["novelty_items"], list, "novelty_items")

    # --- Error Cases ---

    def test_error_missing_klines(self):
        """Missing klines argument returns structured error."""
        from server import tool_finance_analyze
        result = tool_finance_analyze({})
        assert "error" in result, "Should return error for missing klines"
        assert_keys(result["error"], ["type", "message", "action"], "error structure")
        assert result["error"]["type"] == "missing_klines"

    def test_error_none_klines(self):
        """None klines returns structured error."""
        from server import tool_finance_analyze
        result = tool_finance_analyze({"klines": None})
        assert "error" in result, "Should return error for None klines"

    def test_error_empty_klines(self):
        """Empty klines list returns structured error."""
        from server import tool_finance_analyze
        result = tool_finance_analyze({"klines": []})
        assert "error" in result, "Should return error for empty klines"
        assert result["error"]["type"] in ("missing_klines", "insufficient_data"), (
            f"Expected missing_klines or insufficient_data, got {result['error']['type']}"
        )

    def test_error_insufficient_candles(self):
        """Fewer than 10 candles returns structured error."""
        from server import tool_finance_analyze
        short_klines = generate_klines(n=5)
        result = tool_finance_analyze({"klines": short_klines})
        assert "error" in result, "Should return error for < 10 candles"
        assert result["error"]["type"] == "insufficient_data"
        assert "10" in result["error"]["message"] or "5" in result["error"]["message"]

    def test_error_9_candles(self):
        """Exactly 9 candles (one below minimum) returns error."""
        from server import tool_finance_analyze
        nine_klines = generate_klines(n=9)
        result = tool_finance_analyze({"klines": nine_klines})
        assert "error" in result, "Should return error for 9 candles"

    def test_missing_close_field_defaults_to_zero(self):
        """Klines missing 'close' field default to 0 via _parse_klines .get() fallback.

        The parser uses k.get("close", k.get("c", 0)) so missing close
        silently defaults to zero. The analysis still runs but produces
        degenerate results. This test documents that behavior.
        """
        from server import tool_finance_analyze
        bad_klines = [{"open": 100, "high": 105, "low": 95, "volume": 500} for _ in range(15)]
        result = tool_finance_analyze({"klines": bad_klines})
        # Parser defaults missing close to 0 — analysis runs but with degenerate data
        # Either it returns an error from downstream analysis or produces a result
        assert "dialectical_health" in result or "error" in result

    def test_missing_volume_field_defaults_to_zero(self):
        """Klines missing 'volume' field default to 0 via _parse_klines .get() fallback.

        The parser uses k.get("volume", k.get("vol", k.get("v", 0))) so missing
        volume silently defaults to zero. This test documents that behavior.
        """
        from server import tool_finance_analyze
        bad_klines = [{"open": 100, "high": 105, "low": 95, "close": 102} for _ in range(15)]
        result = tool_finance_analyze({"klines": bad_klines})
        # Parser defaults missing volume to 0 — analysis runs with zero volumes
        assert "dialectical_health" in result or "error" in result

    def test_error_structured_format(self):
        """All errors follow the structured error format."""
        from server import tool_finance_analyze
        result = tool_finance_analyze({})
        assert "error" in result
        err = result["error"]
        assert_keys(err, ["type", "message", "action"], "structured error format")
        assert_type(err["type"], str, "error.type")
        assert_type(err["message"], str, "error.message")
        assert_type(err["action"], str, "error.action")

    # --- Multiple Timeframes ---

    def test_timeframe_1m(self):
        """1m timeframe analysis succeeds."""
        from server import tool_finance_analyze
        result = tool_finance_analyze({"klines": KLINES_50, "timeframe": "1m"})
        assert "error" not in result
        assert result["_meta"]["timeframe"] == "1m"

    def test_timeframe_5m(self):
        """5m timeframe analysis succeeds."""
        from server import tool_finance_analyze
        result = tool_finance_analyze({"klines": KLINES_50, "timeframe": "5m"})
        assert "error" not in result
        assert result["_meta"]["timeframe"] == "5m"

    def test_timeframe_1d(self):
        """1d timeframe analysis succeeds."""
        from server import tool_finance_analyze
        result = tool_finance_analyze({"klines": KLINES_50, "timeframe": "1d"})
        assert "error" not in result
        assert result["_meta"]["timeframe"] == "1d"

    # --- Idempotency ---

    def test_idempotent_results(self):
        """Same input produces identical DHS, loop_strength, and channels."""
        from server import tool_finance_analyze
        r1 = tool_finance_analyze({"klines": KLINES_50})
        r2 = tool_finance_analyze({"klines": KLINES_50})
        assert r1["dialectical_health"] == r2["dialectical_health"], "DHS not idempotent"
        assert r1["loop_strength"] == r2["loop_strength"], "loop_strength not idempotent"
        assert r1["channels"] == r2["channels"], "channels not idempotent"

    # --- Different Data Sizes ---

    def test_large_dataset(self):
        """200-candle analysis succeeds."""
        from server import tool_finance_analyze
        large = generate_klines(n=200)
        result = tool_finance_analyze({"klines": large})
        assert "error" not in result
        assert result["_meta"]["data_points"] == 200


# ---------------------------------------------------------------------------
# API Endpoint Tests
# ---------------------------------------------------------------------------

class TestFinanceAPI:
    """Test POST /v1/finance/analyze endpoint."""

    @staticmethod
    def _get_client_and_keys():
        from fastapi.testclient import TestClient
        from api import app
        from auth import create_key
        client = TestClient(app)
        free_key = create_key(tier="free", owner="finance-test-free")["raw_key"]
        pro_key = create_key(tier="pro", owner="finance-test-pro")["raw_key"]
        enterprise_key = create_key(tier="enterprise", owner="finance-test-enterprise")["raw_key"]
        return client, free_key, pro_key, enterprise_key

    @staticmethod
    def _auth(key):
        return {"Authorization": f"Bearer {key}"}

    # --- Authentication ---

    def test_no_auth_returns_401(self):
        """Request without auth token returns 401."""
        client, _, pro_key, _ = self._get_client_and_keys()
        r = client.post("/v1/finance/analyze", json={"klines": KLINES_50})
        assert r.status_code == 401, f"Expected 401, got {r.status_code}"

    def test_bad_key_returns_401(self):
        """Request with invalid key returns 401."""
        client, _, _, _ = self._get_client_and_keys()
        r = client.post("/v1/finance/analyze", json={"klines": KLINES_50},
                        headers=self._auth("rn_live_fake_key"))
        assert r.status_code == 401, f"Expected 401, got {r.status_code}"

    # --- Tier Access ---

    def test_free_tier_forbidden(self):
        """Free tier cannot access finance tool (returns 403)."""
        client, free_key, _, _ = self._get_client_and_keys()
        r = client.post("/v1/finance/analyze", json={"klines": KLINES_50},
                        headers=self._auth(free_key))
        assert r.status_code == 403, f"Expected 403 for free tier, got {r.status_code}"

    def test_pro_tier_allowed(self):
        """Pro tier can access finance tool."""
        client, _, pro_key, _ = self._get_client_and_keys()
        r = client.post("/v1/finance/analyze", json={"klines": KLINES_50},
                        headers=self._auth(pro_key))
        assert r.status_code == 200, f"Expected 200 for pro tier, got {r.status_code}: {r.text}"

    def test_enterprise_tier_allowed(self):
        """Enterprise tier can access finance tool."""
        client, _, _, enterprise_key = self._get_client_and_keys()
        r = client.post("/v1/finance/analyze", json={"klines": KLINES_50},
                        headers=self._auth(enterprise_key))
        assert r.status_code == 200, f"Expected 200 for enterprise tier, got {r.status_code}: {r.text}"

    # --- Happy Path ---

    def test_happy_path_response_structure(self):
        """200 response has valid result structure."""
        client, _, pro_key, _ = self._get_client_and_keys()
        r = client.post("/v1/finance/analyze", json={"klines": KLINES_50},
                        headers=self._auth(pro_key))
        assert r.status_code == 200
        data = r.json()
        assert_keys(data, ["dialectical_health", "channels", "constellations", "stress", "_meta"], "API response")
        assert 0.0 <= data["dialectical_health"] <= 1.0

    def test_exposure_in_api_response(self):
        """API response includes exposure field by default."""
        client, _, pro_key, _ = self._get_client_and_keys()
        r = client.post("/v1/finance/analyze", json={"klines": KLINES_50},
                        headers=self._auth(pro_key))
        assert r.status_code == 200
        data = r.json()
        assert "exposure" in data, "exposure missing from API response"

    def test_exposure_excluded_via_api(self):
        """API response excludes exposure when include_exposure=False."""
        client, _, pro_key, _ = self._get_client_and_keys()
        r = client.post("/v1/finance/analyze",
                        json={"klines": KLINES_50, "include_exposure": False},
                        headers=self._auth(pro_key))
        assert r.status_code == 200
        data = r.json()
        assert "exposure" not in data, "exposure should be absent with include_exposure=False"

    def test_custom_symbol_via_api(self):
        """Symbol passthrough works via API."""
        client, _, pro_key, _ = self._get_client_and_keys()
        r = client.post("/v1/finance/analyze",
                        json={"klines": KLINES_50, "symbol": "ETHUSDT", "timeframe": "4h"},
                        headers=self._auth(pro_key))
        assert r.status_code == 200
        data = r.json()
        assert data["_meta"]["symbol"] == "ETHUSDT"
        assert data["_meta"]["timeframe"] == "4h"

    # --- Validation Errors ---

    def test_insufficient_klines_via_api(self):
        """API rejects klines with fewer than 10 candles (Pydantic min_length=10)."""
        client, _, pro_key, _ = self._get_client_and_keys()
        short_klines = generate_klines(n=5)
        r = client.post("/v1/finance/analyze", json={"klines": short_klines},
                        headers=self._auth(pro_key))
        assert r.status_code == 422, f"Expected 422 for < 10 klines, got {r.status_code}"

    def test_missing_klines_field_via_api(self):
        """API rejects request with missing klines field."""
        client, _, pro_key, _ = self._get_client_and_keys()
        r = client.post("/v1/finance/analyze", json={},
                        headers=self._auth(pro_key))
        assert r.status_code == 422, f"Expected 422 for missing klines, got {r.status_code}"

    # --- Rate Limit Headers ---

    def test_rate_limit_headers_present(self):
        """Response includes rate limit headers."""
        client, _, pro_key, _ = self._get_client_and_keys()
        r = client.post("/v1/finance/analyze", json={"klines": KLINES_50},
                        headers=self._auth(pro_key))
        assert r.status_code == 200
        assert "x-ratelimit-remaining" in r.headers, "Missing x-ratelimit-remaining header"
        assert "x-ratelimit-limit" in r.headers, "Missing x-ratelimit-limit header"

    def test_response_time_header(self):
        """Response includes x-response-time-ms header."""
        client, _, pro_key, _ = self._get_client_and_keys()
        r = client.post("/v1/finance/analyze", json={"klines": KLINES_50},
                        headers=self._auth(pro_key))
        assert r.status_code == 200
        assert "x-response-time-ms" in r.headers, "Missing x-response-time-ms header"


# ---------------------------------------------------------------------------
# Direct Finance Module Tests
# ---------------------------------------------------------------------------

class TestFinanceModule:
    """Test renoun_finance.analyze_financial directly."""

    def test_direct_call(self):
        """Direct call to analyze_financial with basic klines."""
        from renoun_finance import analyze_financial
        result = analyze_financial(KLINES_50, symbol="TEST", timeframe="1h")
        assert_keys(result, ["dialectical_health", "loop_strength", "channels",
                             "constellations", "stress", "_meta"], "direct result")

    def test_direct_call_dict_input(self):
        """analyze_financial accepts dict with 'klines' key."""
        from renoun_finance import analyze_financial
        result = analyze_financial({"klines": KLINES_50}, symbol="TEST", timeframe="1h")
        assert "error" not in result or "dialectical_health" in result

    def test_windowed_analysis(self):
        """Window parameter limits analysis to last N candles."""
        from renoun_finance import analyze_financial
        result_full = analyze_financial(KLINES_100, symbol="TEST", timeframe="1h")
        result_windowed = analyze_financial(KLINES_100, symbol="TEST", timeframe="1h", window=30)
        assert result_windowed["_meta"]["data_points"] == 30, (
            f"Expected 30 data_points with window=30, got {result_windowed['_meta']['data_points']}"
        )
        # Windowed result should differ from full analysis
        assert result_full["dialectical_health"] != result_windowed["dialectical_health"] or \
               result_full["_meta"]["data_points"] != result_windowed["_meta"]["data_points"]

    def test_all_channels_finite(self):
        """No channel value should be NaN or inf."""
        import math
        from renoun_finance import analyze_financial
        result = analyze_financial(KLINES_50, symbol="TEST", timeframe="1h")
        channels = result["channels"]
        for dimension in ["recurrence", "novelty", "unity"]:
            for key, value in channels[dimension].items():
                assert math.isfinite(value), f"channels.{dimension}.{key} is not finite: {value}"

    def test_constant_price_data(self):
        """Constant price data (no volatility) does not crash."""
        from renoun_finance import analyze_financial
        flat_klines = [
            {"open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "volume": 500.0}
            for _ in range(20)
        ]
        result = analyze_financial(flat_klines, symbol="FLAT", timeframe="1h")
        assert "dialectical_health" in result, "Should handle constant price data"

    def test_single_spike(self):
        """Data with a single large price spike does not crash."""
        from renoun_finance import analyze_financial
        klines = generate_klines(n=30, volatility=0.01)
        # Inject a spike at candle 15
        klines[15] = {
            "open": klines[14]["close"],
            "high": klines[14]["close"] * 1.5,
            "low": klines[14]["close"] * 0.95,
            "close": klines[14]["close"] * 1.3,
            "volume": 5000.0,
        }
        result = analyze_financial(klines, symbol="SPIKE", timeframe="1h")
        assert "dialectical_health" in result, "Should handle price spike"
        assert 0.0 <= result["dialectical_health"] <= 1.0


# ---------------------------------------------------------------------------
# Cleanup & CLI runner
# ---------------------------------------------------------------------------

def cleanup():
    """Restore HOME and clean up temp dir."""
    if _orig_home:
        os.environ["HOME"] = _orig_home
    elif "HOME" in os.environ:
        del os.environ["HOME"]
    shutil.rmtree(_tmpdir, ignore_errors=True)


if __name__ == "__main__":
    import traceback
    import atexit
    atexit.register(cleanup)

    test_classes = [
        TestFinanceMCP,
        TestFinanceAPI,
        TestFinanceModule,
    ]

    passed = 0
    failed = 0
    errors = []

    for cls in test_classes:
        print(f"\n--- {cls.__name__} ---")
        instance = cls()
        methods = [m for m in dir(instance) if m.startswith("test_")]
        for method_name in sorted(methods):
            test_name = f"{cls.__name__}.{method_name}"
            try:
                if hasattr(instance, "setup_method"):
                    instance.setup_method()
                getattr(instance, method_name)()
                if hasattr(instance, "teardown_method"):
                    instance.teardown_method()
                print(f"  PASS  {test_name}")
                passed += 1
            except Exception as e:
                if hasattr(instance, "teardown_method"):
                    try:
                        instance.teardown_method()
                    except Exception:
                        pass
                print(f"  FAIL  {test_name}: {e}")
                errors.append((test_name, traceback.format_exc()))
                failed += 1

    print(f"\n{'='*60}")
    print(f"Results: {passed} passed, {failed} failed, {passed + failed} total")

    if errors:
        print(f"\nFailures:")
        for name, tb in errors:
            print(f"\n--- {name} ---")
            print(tb)
        sys.exit(1)
    else:
        print("\nAll tests passed.")
        sys.exit(0)
