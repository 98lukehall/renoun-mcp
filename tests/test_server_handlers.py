#!/usr/bin/env python3
"""
Server tool handler edge-case tests for the ReNoUn MCP Server.

Covers:
  - Invalid tool name dispatch
  - Missing required parameters
  - Extra unexpected parameters
  - Invalid parameter types (string where number expected)
  - Tool handler return structure validation
  - TOOL_HANDLERS and TOOL_DEFS consistency

Run:
    pytest tests/test_server_handlers.py -v
"""

import sys
import os
import tempfile
import shutil

# Ensure we can import from the parent directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Isolate test state
_orig_home = os.environ.get("HOME")
_tmpdir = tempfile.mkdtemp(prefix="renoun_server_handler_test_")
os.environ["HOME"] = _tmpdir

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def assert_has_error(result, context=""):
    """Assert the result contains an error."""
    assert "error" in result, f"{context}: expected error, got {list(result.keys())}"


def assert_no_error(result, context=""):
    """Assert the result does NOT contain an error."""
    assert "error" not in result, f"{context}: unexpected error: {result.get('error')}"


def assert_valid_dhs(result, context=""):
    """Assert DHS is present and in [0.0, 1.0]."""
    assert "dialectical_health" in result, f"{context}: missing dialectical_health"
    dhs = result["dialectical_health"]
    assert 0.0 <= dhs <= 1.0, f"{context}: DHS {dhs} out of [0.0, 1.0]"


SAMPLE_UTTERANCES = [
    {"speaker": "therapist", "text": "What brings you in today?"},
    {"speaker": "client", "text": "I have been struggling with anxiety for months."},
    {"speaker": "therapist", "text": "Can you tell me more about when it started?"},
    {"speaker": "client", "text": "It started after I lost my job. I feel stuck."},
    {"speaker": "therapist", "text": "That sounds really difficult. What does stuck feel like?"},
    {"speaker": "client", "text": "Like nothing changes. Same thoughts every day."},
    {"speaker": "therapist", "text": "Have you noticed any moments where things feel different?"},
    {"speaker": "client", "text": "Sometimes when I go for walks. But then it comes back."},
    {"speaker": "therapist", "text": "So the walks provide some relief. What else helps?"},
    {"speaker": "client", "text": "Talking to my sister. She understands."},
    {"speaker": "therapist", "text": "It sounds like connection matters to you."},
    {"speaker": "client", "text": "Yes but I avoid people most of the time now."},
]

SAMPLE_KLINES = [
    {"open": 100 + i, "high": 105 + i, "low": 95 + i, "close": 102 + i, "volume": 500 + i * 10}
    for i in range(20)
]


# ---------------------------------------------------------------------------
# Tests: Invalid Tool Name
# ---------------------------------------------------------------------------

class TestInvalidToolName:
    """Tests for dispatching to a non-existent tool."""

    def test_unknown_tool_not_in_handlers(self):
        """Requesting an unknown tool name should not be in TOOL_HANDLERS."""
        from server import TOOL_HANDLERS
        assert "renoun_nonexistent" not in TOOL_HANDLERS
        assert "invalid_tool" not in TOOL_HANDLERS
        assert "" not in TOOL_HANDLERS

    def test_all_handlers_are_callable(self):
        """Every handler in TOOL_HANDLERS should be callable."""
        from server import TOOL_HANDLERS
        for name, handler in TOOL_HANDLERS.items():
            assert callable(handler), f"Handler for {name} is not callable"

    def test_handler_names_match_tool_defs(self):
        """Handler names should exactly match TOOL_DEFS names."""
        from server import TOOL_HANDLERS, TOOL_DEFS
        handler_names = set(TOOL_HANDLERS.keys())
        def_names = {t["name"] for t in TOOL_DEFS}
        assert handler_names == def_names, (
            f"Mismatch: handlers={handler_names - def_names}, defs={def_names - handler_names}"
        )


# ---------------------------------------------------------------------------
# Tests: Missing Required Parameters
# ---------------------------------------------------------------------------

class TestMissingParameters:
    """Tests for calling handlers with missing required parameters."""

    def test_analyze_no_arguments(self):
        """tool_analyze with empty dict should error (no utterances)."""
        from server import tool_analyze
        result = tool_analyze({})
        assert_has_error(result, "analyze no args")

    def test_analyze_empty_utterances(self):
        """tool_analyze with empty utterances list should error."""
        from server import tool_analyze
        result = tool_analyze({"utterances": []})
        assert_has_error(result, "analyze empty utterances")

    def test_health_check_no_arguments(self):
        """tool_health_check with empty dict should error."""
        from server import tool_health_check
        result = tool_health_check({})
        assert_has_error(result, "health_check no args")

    def test_health_check_empty_utterances(self):
        """tool_health_check with empty utterances should error."""
        from server import tool_health_check
        result = tool_health_check({"utterances": []})
        assert_has_error(result, "health_check empty utterances")

    def test_compare_no_arguments(self):
        """tool_compare with empty dict should error."""
        from server import tool_compare
        result = tool_compare({})
        assert_has_error(result, "compare no args")

    def test_compare_only_a(self):
        """tool_compare with only utterances_a should error."""
        from server import tool_compare
        result = tool_compare({"utterances_a": SAMPLE_UTTERANCES})
        assert_has_error(result, "compare only a")

    def test_compare_only_b(self):
        """tool_compare with only utterances_b should error."""
        from server import tool_compare
        result = tool_compare({"utterances_b": SAMPLE_UTTERANCES})
        assert_has_error(result, "compare only b")

    def test_compare_only_result_a(self):
        """tool_compare with only result_a should error."""
        from server import tool_compare
        result = tool_compare({"result_a": {"dialectical_health": 0.5}})
        assert_has_error(result, "compare only result_a")

    def test_pattern_query_no_action(self):
        """tool_pattern_query with no action defaults to 'list'."""
        from server import tool_pattern_query
        result = tool_pattern_query({})
        # Default action is "list" which should not error
        assert "error" not in result or "sessions" in result

    def test_pattern_query_save_no_result(self):
        """tool_pattern_query save without result should error."""
        from server import tool_pattern_query
        result = tool_pattern_query({"action": "save"})
        assert_has_error(result, "pattern save no result")

    def test_pattern_query_save_no_session_name(self):
        """tool_pattern_query save without session_name should error."""
        from server import tool_pattern_query
        result = tool_pattern_query({
            "action": "save",
            "result": {"dialectical_health": 0.5},
        })
        assert_has_error(result, "pattern save no session name")

    def test_finance_no_klines(self):
        """tool_finance_analyze without klines should error."""
        from server import tool_finance_analyze
        result = tool_finance_analyze({})
        assert_has_error(result, "finance no klines")

    def test_finance_empty_klines(self):
        """tool_finance_analyze with empty klines should error."""
        from server import tool_finance_analyze
        result = tool_finance_analyze({"klines": []})
        assert_has_error(result, "finance empty klines")

    def test_steer_add_turns_no_utterances(self):
        """tool_steer add_turns without utterances should error."""
        from server import tool_steer
        result = tool_steer({"action": "add_turns"})
        assert_has_error(result, "steer no utterances")


# ---------------------------------------------------------------------------
# Tests: Extra Unexpected Parameters
# ---------------------------------------------------------------------------

class TestExtraParameters:
    """Tests that extra parameters are safely ignored."""

    def test_analyze_extra_params(self):
        """Extra params in analyze should be ignored."""
        from server import tool_analyze
        result = tool_analyze({
            "utterances": SAMPLE_UTTERANCES,
            "extra_field": "should be ignored",
            "unknown_param": 42,
        })
        assert_no_error(result, "analyze extra params")
        assert_valid_dhs(result, "analyze extra params")

    def test_health_check_extra_params(self):
        """Extra params in health_check should be ignored."""
        from server import tool_health_check
        result = tool_health_check({
            "utterances": SAMPLE_UTTERANCES,
            "verbose": True,
            "format": "json",
        })
        assert_no_error(result, "health_check extra params")
        assert_valid_dhs(result, "health_check extra params")

    def test_compare_extra_params(self):
        """Extra params in compare should be ignored."""
        from server import tool_compare
        result = tool_compare({
            "utterances_a": SAMPLE_UTTERANCES,
            "utterances_b": SAMPLE_UTTERANCES,
            "extra": "value",
        })
        assert_no_error(result, "compare extra params")

    def test_finance_extra_params(self):
        """Extra params in finance analyze should be ignored."""
        from server import tool_finance_analyze
        result = tool_finance_analyze({
            "klines": SAMPLE_KLINES,
            "extra": "test",
            "debug": True,
        })
        assert_no_error(result, "finance extra params")

    def test_pattern_query_extra_params(self):
        """Extra params in pattern_query should be ignored."""
        from server import tool_pattern_query
        result = tool_pattern_query({
            "action": "list",
            "extra": "ignored",
        })
        # Should not error
        assert "error" not in result or "sessions" in result

    def test_steer_extra_params(self):
        """Extra params in steer should be ignored."""
        from server import tool_steer
        result = tool_steer({
            "action": "list_sessions",
            "extra_param": "ignored",
        })
        assert "error" not in result


# ---------------------------------------------------------------------------
# Tests: Invalid Parameter Types
# ---------------------------------------------------------------------------

class TestInvalidParameterTypes:
    """Tests with wrong types for parameters."""

    def test_analyze_utterances_as_string(self):
        """Utterances passed as a string instead of list."""
        from server import tool_analyze
        # Should attempt to parse as JSON or text
        result = tool_analyze({"utterances": "not a list"})
        # Should either parse successfully or return a structured error
        # (normalize_utterances handles string input)

    def test_analyze_utterances_as_number(self):
        """Utterances passed as a number."""
        from server import tool_analyze
        result = tool_analyze({"utterances": 42})
        assert_has_error(result, "utterances as number")

    def test_analyze_utterances_as_dict(self):
        """Utterances passed as a dict instead of list."""
        from server import tool_analyze
        result = tool_analyze({"utterances": {"speaker": "a", "text": "hello"}})
        assert_has_error(result, "utterances as dict")

    def test_finance_klines_as_string(self):
        """Klines passed as a string."""
        from server import tool_finance_analyze
        result = tool_finance_analyze({"klines": "not a list"})
        assert_has_error(result, "klines as string")

    def test_finance_klines_as_number(self):
        """Klines passed as a number -- server handler does not guard against
        non-iterable klines before calling len(), so this raises TypeError.
        This documents the current behavior (potential hardening opportunity)."""
        from server import tool_finance_analyze
        with pytest.raises(TypeError):
            tool_finance_analyze({"klines": 42})

    def test_finance_timeframe_as_number(self):
        """Timeframe passed as number instead of string -- should be coerced or handled."""
        from server import tool_finance_analyze
        result = tool_finance_analyze({
            "klines": SAMPLE_KLINES,
            "timeframe": 60,
        })
        # Should not crash -- timeframe is metadata only
        assert_no_error(result, "timeframe as number")

    def test_pattern_query_action_as_number(self):
        """Action passed as number."""
        from server import tool_pattern_query
        result = tool_pattern_query({"action": 42})
        assert_has_error(result, "action as number")

    def test_steer_utterances_as_dict(self):
        """Steer utterances passed as dict instead of list."""
        from server import tool_steer
        result = tool_steer({
            "action": "add_turns",
            "utterances": {"speaker": "a", "text": "hello"},
        })
        # Should handle gracefully -- normalize_utterances handles dict with utterances key
        # But a single dict is not valid unless it has "utterances" key
        # The handler should error or attempt to parse


# ---------------------------------------------------------------------------
# Tests: Error Structure
# ---------------------------------------------------------------------------

class TestErrorStructure:
    """Tests that error responses have consistent structure."""

    def test_analyze_error_has_type(self):
        from server import tool_analyze
        result = tool_analyze({"utterances": []})
        err = result["error"]
        assert "type" in err, "Error missing 'type'"
        assert isinstance(err["type"], str)

    def test_analyze_error_has_message(self):
        from server import tool_analyze
        result = tool_analyze({"utterances": []})
        err = result["error"]
        assert "message" in err, "Error missing 'message'"
        assert isinstance(err["message"], str)
        assert len(err["message"]) > 0

    def test_analyze_error_has_action(self):
        from server import tool_analyze
        result = tool_analyze({"utterances": []})
        err = result["error"]
        assert "action" in err, "Error missing 'action'"
        assert isinstance(err["action"], str)

    def test_health_check_error_structure(self):
        from server import tool_health_check
        result = tool_health_check({"utterances": []})
        err = result["error"]
        assert "type" in err
        assert "message" in err
        assert "action" in err

    def test_compare_error_structure(self):
        from server import tool_compare
        result = tool_compare({})
        err = result["error"]
        assert "type" in err
        assert "message" in err
        assert "action" in err

    def test_finance_error_structure(self):
        from server import tool_finance_analyze
        result = tool_finance_analyze({})
        err = result["error"]
        assert "type" in err
        assert "message" in err
        assert "action" in err

    def test_pattern_query_error_structure(self):
        from server import tool_pattern_query
        result = tool_pattern_query({"action": "nonexistent"})
        err = result["error"]
        assert "type" in err
        assert "message" in err
        assert "action" in err


# ---------------------------------------------------------------------------
# Tests: Return Structure for Successful Calls
# ---------------------------------------------------------------------------

class TestSuccessfulReturnStructure:
    """Verify that successful calls return all expected fields."""

    def test_analyze_return_keys(self):
        """tool_analyze should return core analysis keys."""
        from server import tool_analyze
        result = tool_analyze({"utterances": SAMPLE_UTTERANCES})
        assert_no_error(result, "analyze return")
        required = [
            "dialectical_health", "loop_strength", "channels",
            "constellations", "summary", "engine", "_meta",
            "result_hash", "reliability_note",
        ]
        for key in required:
            assert key in result, f"Missing key: {key}"

    def test_analyze_engine_metadata(self):
        """Engine metadata should have version fields."""
        from server import tool_analyze
        result = tool_analyze({"utterances": SAMPLE_UTTERANCES})
        eng = result["engine"]
        assert "version" in eng
        assert "schema_version" in eng
        assert "tool_version" in eng
        assert "analysis_timestamp" in eng

    def test_analyze_meta_block(self):
        """_meta should contain turn_count and speakers."""
        from server import tool_analyze
        result = tool_analyze({"utterances": SAMPLE_UTTERANCES})
        meta = result["_meta"]
        assert "turn_count" in meta
        assert meta["turn_count"] == len(SAMPLE_UTTERANCES)
        assert "speakers" in meta
        assert len(meta["speakers"]) > 0

    def test_analyze_result_hash_is_sha256(self):
        """result_hash should be a 64-char hex string (SHA-256)."""
        from server import tool_analyze
        result = tool_analyze({"utterances": SAMPLE_UTTERANCES})
        h = result["result_hash"]
        assert isinstance(h, str)
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_analyze_constellations_have_agent_actions(self):
        """Every constellation should have agent_action and agent_guidance."""
        from server import tool_analyze
        result = tool_analyze({"utterances": SAMPLE_UTTERANCES})
        for c in result.get("constellations", []):
            assert "agent_action" in c, f"Constellation {c.get('detected')} missing agent_action"
            assert "agent_guidance" in c, f"Constellation {c.get('detected')} missing agent_guidance"

    def test_health_check_return_keys(self):
        """tool_health_check should return expected keys."""
        from server import tool_health_check
        result = tool_health_check({"utterances": SAMPLE_UTTERANCES})
        assert_no_error(result, "health_check return")
        required = [
            "dialectical_health", "assessment", "loop_strength",
            "dominant_constellation", "summary",
        ]
        for key in required:
            assert key in result, f"Missing key: {key}"

    def test_health_check_assessment_valid(self):
        """Assessment should be one of the four valid values."""
        from server import tool_health_check
        result = tool_health_check({"utterances": SAMPLE_UTTERANCES})
        valid = {"excellent", "healthy", "below_baseline", "distressed"}
        assert result["assessment"] in valid, f"Invalid assessment: {result['assessment']}"

    def test_compare_return_keys(self):
        """tool_compare should return health and shift information."""
        from server import tool_compare
        result = tool_compare({
            "utterances_a": SAMPLE_UTTERANCES,
            "utterances_b": SAMPLE_UTTERANCES,
        })
        assert_no_error(result, "compare return")
        # Should have health or top-level dhs fields
        assert "health" in result or "dhs_a" in result, (
            f"Compare missing health data: {list(result.keys())}"
        )

    def test_finance_return_keys(self):
        """tool_finance_analyze should return expected keys."""
        from server import tool_finance_analyze
        result = tool_finance_analyze({"klines": SAMPLE_KLINES})
        assert_no_error(result, "finance return")
        required = [
            "dialectical_health", "loop_strength", "channels",
            "stress", "constellations",
        ]
        for key in required:
            assert key in result, f"Missing key: {key}"


# ---------------------------------------------------------------------------
# Tests: Tool Definitions (TOOL_DEFS)
# ---------------------------------------------------------------------------

class TestToolDefinitions:
    """Tests for TOOL_DEFS structure and consistency."""

    def test_all_tools_have_description(self):
        """Every tool should have a description."""
        from server import TOOL_DEFS
        for t in TOOL_DEFS:
            assert "description" in t, f"{t['name']} missing description"
            assert len(t["description"]) > 10, f"{t['name']} description too short"

    def test_all_tools_have_input_schema(self):
        """Every tool should have inputSchema."""
        from server import TOOL_DEFS
        for t in TOOL_DEFS:
            assert "inputSchema" in t, f"{t['name']} missing inputSchema"
            assert isinstance(t["inputSchema"], dict)

    def test_input_schemas_have_type_object(self):
        """All inputSchemas should be type: object."""
        from server import TOOL_DEFS
        for t in TOOL_DEFS:
            schema = t["inputSchema"]
            assert schema.get("type") == "object", (
                f"{t['name']} inputSchema type is {schema.get('type')}, expected 'object'"
            )

    def test_input_schemas_have_properties(self):
        """All inputSchemas should have properties."""
        from server import TOOL_DEFS
        for t in TOOL_DEFS:
            schema = t["inputSchema"]
            assert "properties" in schema, f"{t['name']} inputSchema missing properties"

    def test_tool_count(self):
        """Should have exactly 9 tools (6 core + agent_monitor + alignment_classify + recovery_analyze)."""
        from server import TOOL_DEFS
        assert len(TOOL_DEFS) == 9, f"Expected 9 tools, got {len(TOOL_DEFS)}"


# ---------------------------------------------------------------------------
# Tests: Tool Annotations
# ---------------------------------------------------------------------------

class TestToolAnnotations:
    """Tests for TOOL_ANNOTATIONS."""

    def test_all_tools_have_annotations(self):
        """Every tool should have annotations."""
        from server import TOOL_ANNOTATIONS, TOOL_DEFS
        for t in TOOL_DEFS:
            assert t["name"] in TOOL_ANNOTATIONS, (
                f"{t['name']} missing from TOOL_ANNOTATIONS"
            )

    def test_annotations_have_required_fields(self):
        """Annotations should have title and hint fields."""
        from server import TOOL_ANNOTATIONS
        for name, ann in TOOL_ANNOTATIONS.items():
            assert "title" in ann, f"{name} annotation missing title"
            assert "readOnlyHint" in ann, f"{name} annotation missing readOnlyHint"

    def test_analyze_tools_are_readonly(self):
        """Analysis tools should be marked as readOnly."""
        from server import TOOL_ANNOTATIONS
        readonly_tools = [
            "renoun_analyze", "renoun_health_check",
            "renoun_compare", "renoun_finance_analyze",
        ]
        for name in readonly_tools:
            ann = TOOL_ANNOTATIONS.get(name, {})
            assert ann.get("readOnlyHint") is True, (
                f"{name} should be readOnlyHint=True"
            )

    def test_analyze_tools_are_idempotent(self):
        """Analysis tools should be marked as idempotent."""
        from server import TOOL_ANNOTATIONS
        idempotent_tools = [
            "renoun_analyze", "renoun_health_check",
            "renoun_compare", "renoun_finance_analyze",
        ]
        for name in idempotent_tools:
            ann = TOOL_ANNOTATIONS.get(name, {})
            assert ann.get("idempotentHint") is True, (
                f"{name} should be idempotentHint=True"
            )


# ---------------------------------------------------------------------------
# Tests: Determinism
# ---------------------------------------------------------------------------

class TestDeterminism:
    """Tests that identical inputs produce identical outputs."""

    def test_analyze_deterministic(self):
        """Same input should produce same DHS."""
        from server import tool_analyze
        r1 = tool_analyze({"utterances": SAMPLE_UTTERANCES})
        r2 = tool_analyze({"utterances": SAMPLE_UTTERANCES})
        assert_no_error(r1)
        assert_no_error(r2)
        assert r1["dialectical_health"] == r2["dialectical_health"]
        assert r1["loop_strength"] == r2["loop_strength"]

    def test_analyze_same_result_hash(self):
        """Same input should produce same result hash."""
        from server import tool_analyze
        r1 = tool_analyze({"utterances": SAMPLE_UTTERANCES})
        r2 = tool_analyze({"utterances": SAMPLE_UTTERANCES})
        assert r1["result_hash"] == r2["result_hash"]

    def test_health_check_deterministic(self):
        """Same input should produce same health check output."""
        from server import tool_health_check
        r1 = tool_health_check({"utterances": SAMPLE_UTTERANCES})
        r2 = tool_health_check({"utterances": SAMPLE_UTTERANCES})
        assert r1["dialectical_health"] == r2["dialectical_health"]
        assert r1["assessment"] == r2["assessment"]

    def test_finance_deterministic(self):
        """Same klines should produce same DHS."""
        from server import tool_finance_analyze
        r1 = tool_finance_analyze({"klines": SAMPLE_KLINES})
        r2 = tool_finance_analyze({"klines": SAMPLE_KLINES})
        assert_no_error(r1)
        assert_no_error(r2)
        assert r1["dialectical_health"] == r2["dialectical_health"]


# ---------------------------------------------------------------------------
# Tests: Cross-Handler Consistency
# ---------------------------------------------------------------------------

class TestCrossHandlerConsistency:
    """Tests that analyze and health_check produce consistent results."""

    def test_dhs_matches_between_analyze_and_health_check(self):
        """DHS from analyze and health_check should match for same input."""
        from server import tool_analyze, tool_health_check
        analyze_result = tool_analyze({"utterances": SAMPLE_UTTERANCES})
        health_result = tool_health_check({"utterances": SAMPLE_UTTERANCES})
        assert_no_error(analyze_result)
        assert_no_error(health_result)
        assert abs(analyze_result["dialectical_health"] - health_result["dialectical_health"]) < 0.001

    def test_loop_strength_matches(self):
        """loop_strength from analyze and health_check should match."""
        from server import tool_analyze, tool_health_check
        analyze_result = tool_analyze({"utterances": SAMPLE_UTTERANCES})
        health_result = tool_health_check({"utterances": SAMPLE_UTTERANCES})
        assert abs(analyze_result["loop_strength"] - health_result["loop_strength"]) < 0.001

    def test_compare_self_shows_stable(self):
        """Comparing a session with itself should show stable trend."""
        from server import tool_compare
        result = tool_compare({
            "utterances_a": SAMPLE_UTTERANCES,
            "utterances_b": SAMPLE_UTTERANCES,
        })
        assert_no_error(result)
        health = result.get("health", result)
        if "dhs_delta" in health:
            assert abs(health["dhs_delta"]) < 0.01
        if "trend" in health:
            assert health["trend"] == "stable"


# ---------------------------------------------------------------------------
# Tests: Version Constants
# ---------------------------------------------------------------------------

class TestVersionConstants:
    """Tests for version string consistency."""

    def test_tool_version_format(self):
        """TOOL_VERSION should be a semver-like string."""
        from server import TOOL_VERSION
        parts = TOOL_VERSION.split(".")
        assert len(parts) == 3, f"TOOL_VERSION should be x.y.z, got {TOOL_VERSION}"
        for p in parts:
            assert p.isdigit(), f"TOOL_VERSION part '{p}' is not numeric"

    def test_schema_version_format(self):
        """SCHEMA_VERSION should be a version string."""
        from server import SCHEMA_VERSION
        assert "." in SCHEMA_VERSION

    def test_engine_version_exists(self):
        """ENGINE_VERSION should be a non-empty string."""
        from server import ENGINE_VERSION
        assert isinstance(ENGINE_VERSION, str)
        assert len(ENGINE_VERSION) > 0


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

def teardown_module():
    """Restore HOME and clean up temp directory."""
    if _orig_home:
        os.environ["HOME"] = _orig_home
    elif "HOME" in os.environ:
        del os.environ["HOME"]
    shutil.rmtree(_tmpdir, ignore_errors=True)
