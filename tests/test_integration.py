#!/usr/bin/env python3
"""
Integration test for ReNoUn MCP Server.

Tests the full pipeline as an MCP client would experience it:
  1. tools/list — verifies all 4 tools are discoverable
  2. renoun_analyze — full analysis on sample conversation
  3. renoun_health_check — fast triage on same data
  4. renoun_compare — structural diff between two sessions
  5. renoun_pattern_query — save, list, query, trend cycle

Run:
    python3 tests/test_integration.py
    # or
    pytest tests/test_integration.py -v
"""

import sys
import os
import json
import shutil
import tempfile

# Ensure we can import from the parent directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------

THERAPY_SESSION = [
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

IMPROVED_SESSION = [
    {"speaker": "therapist", "text": "How have things been since last time?"},
    {"speaker": "client", "text": "Actually better. I started walking every morning."},
    {"speaker": "therapist", "text": "That's a real shift. What prompted it?"},
    {"speaker": "client", "text": "Our conversation about relief. I realized I had tools."},
    {"speaker": "therapist", "text": "You recognized your own resources. How does that feel?"},
    {"speaker": "client", "text": "Empowering. Like I have some control."},
    {"speaker": "therapist", "text": "And the anxiety — has it changed?"},
    {"speaker": "client", "text": "Still there but I can see through it now."},
    {"speaker": "therapist", "text": "See through it — say more about that."},
    {"speaker": "client", "text": "I notice when the loop starts. That changes everything."},
    {"speaker": "therapist", "text": "Noticing the loop is itself a kind of freedom."},
    {"speaker": "client", "text": "Yes. I feel like I'm moving forward for the first time."},
]


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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestToolDiscovery:
    """Test that all tools are discoverable via TOOL_DEFS."""

    def test_tool_count(self):
        from server import TOOL_DEFS
        assert len(TOOL_DEFS) == 6, f"Expected 6 tools, got {len(TOOL_DEFS)}"

    def test_tool_names(self):
        from server import TOOL_DEFS
        names = {t["name"] for t in TOOL_DEFS}
        expected = {"renoun_analyze", "renoun_health_check", "renoun_compare", "renoun_pattern_query", "renoun_steer", "renoun_finance_analyze"}
        assert names == expected, f"Tool name mismatch: {names} != {expected}"

    def test_all_have_input_schema(self):
        from server import TOOL_DEFS
        for t in TOOL_DEFS:
            assert "inputSchema" in t, f"{t['name']} missing inputSchema"

    def test_output_schemas_present(self):
        from server import TOOL_DEFS
        # analyze, health_check, compare should have outputSchema
        for name in ["renoun_analyze", "renoun_health_check", "renoun_compare"]:
            td = next(t for t in TOOL_DEFS if t["name"] == name)
            assert "outputSchema" in td, f"{name} missing outputSchema"

    def test_handlers_registered(self):
        from server import TOOL_HANDLERS
        expected = {"renoun_analyze", "renoun_health_check", "renoun_compare", "renoun_pattern_query", "renoun_steer", "renoun_finance_analyze"}
        assert set(TOOL_HANDLERS.keys()) == expected

    def test_version_constants(self):
        from server import TOOL_VERSION, ENGINE_VERSION, SCHEMA_VERSION
        assert TOOL_VERSION == "1.3.1"
        assert SCHEMA_VERSION == "1.1"

    # --- renoun_steer discovery regression (investigated 3+ sessions) ---
    # Root cause: server-side registration is correct in all code paths.
    # The bug is client-side or MCP library version-specific — not in server.py.
    # These tests prove the tool IS discoverable server-side.

    def test_steer_in_tool_defs(self):
        """renoun_steer must be present in TOOL_DEFS (raw definition list)."""
        from server import TOOL_DEFS
        names = {t["name"] for t in TOOL_DEFS}
        assert "renoun_steer" in names, (
            f"renoun_steer missing from TOOL_DEFS. Found: {names}"
        )

    def test_steer_in_tool_handlers(self):
        """renoun_steer must have a handler function in TOOL_HANDLERS."""
        from server import TOOL_HANDLERS
        assert "renoun_steer" in TOOL_HANDLERS, (
            f"renoun_steer missing from TOOL_HANDLERS. Found: {set(TOOL_HANDLERS.keys())}"
        )

    def test_steer_handler_is_callable(self):
        """renoun_steer handler must be callable."""
        from server import TOOL_HANDLERS
        handler = TOOL_HANDLERS["renoun_steer"]
        assert callable(handler), f"renoun_steer handler is not callable: {type(handler)}"

    def test_steer_in_tools(self):
        """renoun_steer must appear in the final TOOLS list (what clients see)."""
        from server import TOOLS
        names = set()
        for t in TOOLS:
            name = t.get("name") if isinstance(t, dict) else getattr(t, "name", None)
            names.add(name)
        assert "renoun_steer" in names, (
            f"renoun_steer missing from TOOLS. Found: {names}"
        )

    def test_steer_in_tool_annotations(self):
        """renoun_steer must have annotations defined."""
        from server import TOOL_ANNOTATIONS
        assert "renoun_steer" in TOOL_ANNOTATIONS, (
            f"renoun_steer missing from TOOL_ANNOTATIONS. Found: {set(TOOL_ANNOTATIONS.keys())}"
        )

    def test_steer_has_input_schema(self):
        """renoun_steer definition must include inputSchema."""
        from server import TOOL_DEFS
        steer_def = next(t for t in TOOL_DEFS if t["name"] == "renoun_steer")
        assert "inputSchema" in steer_def, "renoun_steer missing inputSchema"
        schema = steer_def["inputSchema"]
        assert "properties" in schema, "renoun_steer inputSchema missing properties"
        assert "action" in schema["properties"], "renoun_steer inputSchema missing 'action' property"

    def test_steer_tools_list_json_rpc_format(self):
        """Simulate the standalone JSON-RPC tools/list response and verify steer is present.

        This reproduces exactly what a client would see via the standalone_server
        tools/list handler (line 1218-1230 of server.py).
        """
        from server import TOOLS
        tools_list = [
            {
                "name": t.get("name") if isinstance(t, dict) else t.name,
                "description": t.get("description") if isinstance(t, dict) else t.description,
                "inputSchema": t.get("inputSchema") if isinstance(t, dict) else t.inputSchema,
            }
            for t in TOOLS
        ]
        names = {t["name"] for t in tools_list}
        assert "renoun_steer" in names, (
            f"renoun_steer missing from JSON-RPC tools/list output. Found: {names}"
        )

    def test_steer_handler_responds_to_list_sessions(self):
        """renoun_steer handler must respond to list_sessions action without error."""
        from server import TOOL_HANDLERS
        handler = TOOL_HANDLERS["renoun_steer"]
        result = handler({"action": "list_sessions"})
        assert "error" not in result, f"list_sessions returned error: {result}"
        assert "sessions" in result, f"list_sessions missing 'sessions' key: {result}"

    def test_steer_parity_with_other_tools(self):
        """All 6 tools must appear in TOOL_DEFS, TOOL_HANDLERS, TOOLS, and TOOL_ANNOTATIONS.

        This is the comprehensive parity check that ensures no tool is missing
        from any registration structure. If any tool (including renoun_steer)
        is missing from any structure, this test fails.
        """
        from server import TOOL_DEFS, TOOL_HANDLERS, TOOLS, TOOL_ANNOTATIONS

        expected = {"renoun_analyze", "renoun_health_check", "renoun_compare",
                    "renoun_pattern_query", "renoun_steer", "renoun_finance_analyze"}

        defs_names = {t["name"] for t in TOOL_DEFS}
        handler_names = set(TOOL_HANDLERS.keys())
        tools_names = {t.get("name") if isinstance(t, dict) else t.name for t in TOOLS}
        annotation_names = set(TOOL_ANNOTATIONS.keys())

        assert defs_names == expected, f"TOOL_DEFS mismatch: {defs_names - expected} extra, {expected - defs_names} missing"
        assert handler_names == expected, f"TOOL_HANDLERS mismatch: {handler_names - expected} extra, {expected - handler_names} missing"
        assert tools_names == expected, f"TOOLS mismatch: {tools_names - expected} extra, {expected - tools_names} missing"
        assert annotation_names == expected, f"TOOL_ANNOTATIONS mismatch: {annotation_names - expected} extra, {expected - annotation_names} missing"


class TestAnalyze:
    """Test renoun_analyze tool handler."""

    def test_basic_analysis(self):
        from server import tool_analyze
        result = tool_analyze({"utterances": THERAPY_SESSION})

        # Core fields
        assert_keys(result, ["dialectical_health", "loop_strength", "channels", "constellations", "summary"], "analyze")
        assert 0.0 <= result["dialectical_health"] <= 1.0
        assert 0.0 <= result["loop_strength"] <= 1.0

    def test_metadata_blocks(self):
        from server import tool_analyze
        result = tool_analyze({"utterances": THERAPY_SESSION})

        assert_keys(result, ["engine", "_meta", "result_hash", "reliability_note"], "analyze metadata")
        assert_keys(result["engine"], ["version", "schema_version", "tool_version", "analysis_timestamp"], "engine block")
        assert_keys(result["_meta"], ["tool_version", "schema_version", "timestamp"], "meta block")
        assert len(result["result_hash"]) == 64  # SHA-256 hex

    def test_agent_actions_injected(self):
        from server import tool_analyze
        result = tool_analyze({"utterances": THERAPY_SESSION})

        for c in result.get("constellations", []):
            assert "agent_action" in c, f"Constellation {c.get('detected')} missing agent_action"
            assert "agent_guidance" in c, f"Constellation {c.get('detected')} missing agent_guidance"

    def test_minimum_turns_reliability_note(self):
        from server import tool_analyze
        short = [{"speaker": "a", "text": "hi"}, {"speaker": "b", "text": "hello"}, {"speaker": "a", "text": "bye"}]
        result = tool_analyze({"utterances": short})
        # Should have a reliability warning for < 10 turns
        assert result.get("reliability_note") is not None

    def test_empty_utterances_error(self):
        from server import tool_analyze
        result = tool_analyze({"utterances": []})
        assert "error" in result

    def test_structured_error_format(self):
        from server import tool_analyze
        result = tool_analyze({"utterances": []})
        assert_keys(result["error"], ["type", "message", "action"], "structured error")


class TestHealthCheck:
    """Test renoun_health_check tool handler."""

    def test_basic_health_check(self):
        from server import tool_health_check
        result = tool_health_check({"utterances": THERAPY_SESSION})

        assert_keys(result, ["dialectical_health", "assessment", "loop_strength", "dominant_constellation", "summary"], "health_check")
        assert result["assessment"] in ["excellent", "healthy", "below_baseline", "distressed"]

    def test_agent_action_on_dominant(self):
        from server import tool_health_check
        result = tool_health_check({"utterances": THERAPY_SESSION})
        dc = result["dominant_constellation"]
        assert "agent_action" in dc, "dominant_constellation missing agent_action"
        assert "agent_guidance" in dc, "dominant_constellation missing agent_guidance"


class TestCompare:
    """Test renoun_compare tool handler."""

    def test_compare_raw_utterances(self):
        from server import tool_compare
        result = tool_compare({
            "utterances_a": THERAPY_SESSION,
            "utterances_b": IMPROVED_SESSION,
            "label_a": "Session 1",
            "label_b": "Session 2",
        })

        assert_keys(result, ["health", "top_shifts", "constellation_transition"], "compare")
        assert_keys(result["health"], ["dhs_a", "dhs_b", "dhs_delta", "trend"], "compare health")

    def test_mixed_mode_rejected(self):
        from server import tool_compare
        result = tool_compare({
            "result_a": {"dialectical_health": 0.5},
            "utterances_b": IMPROVED_SESSION,
        })
        assert "error" in result, "Mixed mode should be rejected"

    def test_no_input_error(self):
        from server import tool_compare
        result = tool_compare({})
        assert "error" in result


class TestPatternQuery:
    """Test renoun_pattern_query tool handler with isolated history dir."""

    def setup_method(self):
        """Create a temp history dir for each test."""
        self._orig_home = os.environ.get("HOME")
        self._tmpdir = tempfile.mkdtemp(prefix="renoun_test_")
        os.environ["HOME"] = self._tmpdir

    def teardown_method(self):
        """Restore HOME and clean up."""
        if self._orig_home:
            os.environ["HOME"] = self._orig_home
        elif "HOME" in os.environ:
            del os.environ["HOME"]
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_list_empty(self):
        from server import tool_pattern_query
        result = tool_pattern_query({"action": "list"})
        # Should return without error (empty or count=0)
        assert "error" not in result or result.get("total_sessions", 0) == 0

    def test_save_and_list(self):
        from server import tool_analyze, tool_pattern_query

        # Analyze first
        analysis = tool_analyze({"utterances": THERAPY_SESSION})
        assert "error" not in analysis

        # Save
        save_result = tool_pattern_query({
            "action": "save",
            "result": analysis,
            "session_name": "integration-test",
            "domain": "therapy",
            "tags": ["test", "integration"],
        })
        assert save_result.get("status") == "saved", f"Save failed: {save_result}"

        # List should now have 1 session
        list_result = tool_pattern_query({"action": "list"})
        sessions = list_result.get("sessions", [])
        assert len(sessions) >= 1, f"Expected at least 1 session, got {len(sessions)}"

    def test_query_by_domain(self):
        from server import tool_analyze, tool_pattern_query

        analysis = tool_analyze({"utterances": THERAPY_SESSION})
        tool_pattern_query({
            "action": "save",
            "result": analysis,
            "session_name": "domain-test",
            "domain": "therapy",
        })

        # Query for therapy
        result = tool_pattern_query({"action": "query", "domain": "therapy"})
        assert "error" not in result

    def test_trend(self):
        from server import tool_analyze, tool_pattern_query

        # Save two sessions for trend
        for i, utts in enumerate([THERAPY_SESSION, IMPROVED_SESSION]):
            analysis = tool_analyze({"utterances": utts})
            tool_pattern_query({
                "action": "save",
                "result": analysis,
                "session_name": f"trend-test-{i}",
                "domain": "therapy",
            })

        result = tool_pattern_query({"action": "trend", "metric": "dhs"})
        assert "error" not in result

    def test_invalid_action(self):
        from server import tool_pattern_query
        result = tool_pattern_query({"action": "explode"})
        assert "error" in result


class TestStandaloneProtocol:
    """Test the JSON-RPC standalone server response format."""

    def test_tools_list_format(self):
        from server import TOOLS
        tools_list = [
            {
                "name": t.get("name") if isinstance(t, dict) else t.name,
                "description": t.get("description") if isinstance(t, dict) else t.description,
                "inputSchema": t.get("inputSchema") if isinstance(t, dict) else t.inputSchema,
                **({"outputSchema": t.get("outputSchema") if isinstance(t, dict) else getattr(t, "outputSchema", None)}
                   if (t.get("outputSchema") if isinstance(t, dict) else getattr(t, "outputSchema", None)) else {}),
            }
            for t in TOOLS
        ]
        assert len(tools_list) == 6
        for t in tools_list:
            assert "name" in t
            assert "description" in t
            assert "inputSchema" in t


# ---------------------------------------------------------------------------
# CLI runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import traceback

    test_classes = [
        TestToolDiscovery,
        TestAnalyze,
        TestHealthCheck,
        TestCompare,
        TestPatternQuery,
        TestStandaloneProtocol,
    ]

    passed = 0
    failed = 0
    errors = []

    for cls in test_classes:
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
        print("All tests passed.")
        sys.exit(0)
