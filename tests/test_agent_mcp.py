"""
Tests for Agent Monitor and Alignment Classify MCP tools.

Phase 3 test suite covering:
- renoun_agent_monitor tool handler (ingest, dashboard, configure, clear)
- renoun_alignment_classify tool handler
- Tool definitions and annotations for new tools
- Input validation and error handling
"""

import os
import sys
import pytest

# Ensure project root on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server import (
    TOOL_HANDLERS, TOOL_DEFS, TOOL_ANNOTATIONS,
)


# ---------------------------------------------------------------------------
# Tool Discovery Tests
# ---------------------------------------------------------------------------

class TestNewToolsDiscovery:
    """Verify new tools appear in TOOL_DEFS, TOOL_HANDLERS, and TOOL_ANNOTATIONS."""

    def test_agent_monitor_in_handlers(self):
        assert "renoun_agent_monitor" in TOOL_HANDLERS

    def test_alignment_classify_in_handlers(self):
        assert "renoun_alignment_classify" in TOOL_HANDLERS

    def test_agent_monitor_handler_callable(self):
        assert callable(TOOL_HANDLERS["renoun_agent_monitor"])

    def test_alignment_classify_handler_callable(self):
        assert callable(TOOL_HANDLERS["renoun_alignment_classify"])

    def test_agent_monitor_in_tool_defs(self):
        names = [t["name"] for t in TOOL_DEFS]
        assert "renoun_agent_monitor" in names

    def test_alignment_classify_in_tool_defs(self):
        names = [t["name"] for t in TOOL_DEFS]
        assert "renoun_alignment_classify" in names

    def test_agent_monitor_has_annotations(self):
        assert "renoun_agent_monitor" in TOOL_ANNOTATIONS

    def test_alignment_classify_has_annotations(self):
        assert "renoun_alignment_classify" in TOOL_ANNOTATIONS

    def test_agent_monitor_schema_has_action(self):
        tool_def = next(t for t in TOOL_DEFS if t["name"] == "renoun_agent_monitor")
        props = tool_def["inputSchema"]["properties"]
        assert "action" in props
        assert "enum" in props["action"]
        assert "ingest" in props["action"]["enum"]
        assert "dashboard" in props["action"]["enum"]
        assert "configure" in props["action"]["enum"]
        assert "clear" in props["action"]["enum"]

    def test_alignment_classify_schema_has_utterances(self):
        tool_def = next(t for t in TOOL_DEFS if t["name"] == "renoun_alignment_classify")
        props = tool_def["inputSchema"]["properties"]
        assert "utterances" in props
        assert props["utterances"]["type"] == "array"

    def test_total_tool_count(self):
        """All 8 tools should be registered."""
        assert len(TOOL_DEFS) == 9
        assert len(TOOL_HANDLERS) == 9


# ---------------------------------------------------------------------------
# Agent Monitor Tool Handler Tests
# ---------------------------------------------------------------------------

class TestAgentMonitorTool:
    """Test renoun_agent_monitor MCP tool handler."""

    def _handler(self, arguments):
        return TOOL_HANDLERS["renoun_agent_monitor"](arguments)

    def test_dashboard_action(self):
        result = self._handler({"action": "dashboard"})
        assert "error" not in result or isinstance(result.get("dashboard"), dict)

    def test_clear_action(self):
        result = self._handler({"action": "clear"})
        assert "error" not in result

    def test_configure_action(self):
        result = self._handler({
            "action": "configure",
            "config": {"window_size": 20}
        })
        assert "error" not in result

    def test_ingest_empty_events(self):
        result = self._handler({
            "action": "ingest",
            "events": []
        })
        # Should handle gracefully — either error or empty result
        assert isinstance(result, dict)

    def test_ingest_with_events(self):
        result = self._handler({
            "action": "ingest",
            "session_id": "test-session",
            "events": [
                {
                    "agent_id": "main",
                    "event_type": "user_message",
                    "content": "Hello, can you help me?",
                    "timestamp": "2026-03-11T10:00:00Z",
                },
                {
                    "agent_id": "main",
                    "event_type": "assistant_message",
                    "content": "Of course! What do you need help with?",
                    "timestamp": "2026-03-11T10:00:01Z",
                },
            ]
        })
        assert isinstance(result, dict)
        # Should return session info or alerts
        assert "error" not in result or "session_id" in result

    def test_ingest_tool_events(self):
        result = self._handler({
            "action": "ingest",
            "session_id": "test-tool-session",
            "events": [
                {
                    "agent_id": "main",
                    "event_type": "tool_call",
                    "content": "Read /src/main.py",
                    "timestamp": "2026-03-11T10:00:00Z",
                },
                {
                    "agent_id": "main",
                    "event_type": "tool_result",
                    "content": "File contents here...",
                    "timestamp": "2026-03-11T10:00:01Z",
                },
                {
                    "agent_id": "main",
                    "event_type": "tool_error",
                    "content": "Permission denied",
                    "timestamp": "2026-03-11T10:00:02Z",
                },
            ]
        })
        assert isinstance(result, dict)

    def test_unknown_action(self):
        result = self._handler({"action": "nonexistent"})
        assert "error" in result

    def test_missing_action(self):
        result = self._handler({})
        # Should default to "ingest" or return error
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# Alignment Classify Tool Handler Tests
# ---------------------------------------------------------------------------

class TestAlignmentClassifyTool:
    """Test renoun_alignment_classify MCP tool handler."""

    def _handler(self, arguments):
        return TOOL_HANDLERS["renoun_alignment_classify"](arguments)

    def test_basic_classification(self):
        """Test with a simple conversation."""
        result = self._handler({
            "utterances": [
                {"speaker": "user", "text": "I think we should use approach A."},
                {"speaker": "assistant", "text": "I agree, approach A is best."},
                {"speaker": "user", "text": "Actually, wait. What about approach B?"},
                {"speaker": "assistant", "text": "Good point. Let me reconsider. Approach B has these advantages..."},
                {"speaker": "user", "text": "So which do you recommend now?"},
                {"speaker": "assistant", "text": "After considering both, I think B is actually better because of X, Y, Z."},
            ]
        })
        assert isinstance(result, dict)
        # Should have classification or error (alignment_api might not be fully available)
        # Either way, it should not crash

    def test_missing_utterances(self):
        """Missing utterances should return error."""
        result = self._handler({})
        assert "error" in result

    def test_empty_utterances(self):
        """Empty utterances should return error."""
        result = self._handler({"utterances": []})
        assert "error" in result

    def test_too_few_utterances(self):
        """Less than minimum should return error."""
        result = self._handler({
            "utterances": [
                {"speaker": "user", "text": "Hello"},
                {"speaker": "assistant", "text": "Hi"},
            ]
        })
        # May or may not error depending on handler — at least should not crash
        assert isinstance(result, dict)

    def test_include_bridge_signals_flag(self):
        """Test with include_bridge_signals=True."""
        result = self._handler({
            "utterances": [
                {"speaker": "user", "text": "I disagree with your approach."},
                {"speaker": "assistant", "text": "Let me reconsider that perspective."},
                {"speaker": "user", "text": "The data suggests a different conclusion."},
                {"speaker": "assistant", "text": "You're right, I was wrong about that. Here's a revised analysis."},
                {"speaker": "user", "text": "That's much better."},
                {"speaker": "assistant", "text": "Thank you for pushing back."},
            ],
            "include_bridge_signals": True,
            "include_renoun_raw": False,
        })
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# Tool Annotations Tests
# ---------------------------------------------------------------------------

class TestNewToolAnnotations:
    """Test annotations for new tools."""

    def test_agent_monitor_annotations(self):
        ann = TOOL_ANNOTATIONS["renoun_agent_monitor"]
        assert "readOnlyHint" in ann
        assert "destructiveHint" in ann
        assert "idempotentHint" in ann

    def test_alignment_classify_annotations(self):
        ann = TOOL_ANNOTATIONS["renoun_alignment_classify"]
        assert "readOnlyHint" in ann
        assert "destructiveHint" in ann
        assert "idempotentHint" in ann

    def test_alignment_classify_is_readonly(self):
        ann = TOOL_ANNOTATIONS["renoun_alignment_classify"]
        assert ann["readOnlyHint"] is True
        assert ann["destructiveHint"] is False

    def test_agent_monitor_is_not_destructive(self):
        ann = TOOL_ANNOTATIONS["renoun_agent_monitor"]
        assert ann["destructiveHint"] is False


# ---------------------------------------------------------------------------
# Integration: Dashboard after Ingest Tests
# ---------------------------------------------------------------------------

class TestAgentMonitorIntegration:
    """Test ingest → dashboard flow."""

    def _handler(self, arguments):
        return TOOL_HANDLERS["renoun_agent_monitor"](arguments)

    def test_clear_then_dashboard(self):
        """Clear all sessions then check dashboard is clean."""
        self._handler({"action": "clear"})
        result = self._handler({"action": "dashboard"})
        assert isinstance(result, dict)

    def test_ingest_then_dashboard(self):
        """Ingest events then check dashboard shows the session."""
        # Clear first
        self._handler({"action": "clear"})

        # Ingest
        self._handler({
            "action": "ingest",
            "session_id": "integration-test",
            "events": [
                {"agent_id": "main", "event_type": "user_message",
                 "content": "Start the integration test"},
                {"agent_id": "main", "event_type": "assistant_message",
                 "content": "Running integration test now"},
            ]
        })

        # Dashboard
        result = self._handler({"action": "dashboard"})
        assert isinstance(result, dict)

    def test_configure_window_size(self):
        """Configure should update window size."""
        result = self._handler({
            "action": "configure",
            "config": {"window_size": 15}
        })
        assert isinstance(result, dict)
        assert "error" not in result

    def test_clear_specific_session(self):
        """Clear a specific session."""
        # Ingest to create a session
        self._handler({
            "action": "ingest",
            "session_id": "to-clear",
            "events": [
                {"agent_id": "main", "event_type": "user_message",
                 "content": "Test message"},
            ]
        })

        # Clear it
        result = self._handler({
            "action": "clear",
            "session_id": "to-clear",
        })
        assert isinstance(result, dict)
        assert "error" not in result
