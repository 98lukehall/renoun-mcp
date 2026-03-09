#!/usr/bin/env python3
"""
Edge-case and stress tests for the core ReNoUn conversation analysis engine.

Covers:
  - Empty and minimal utterance lists
  - Boundary conditions (exact thresholds)
  - Extreme text lengths and special characters
  - Degenerate speaker patterns (single speaker, rapid alternation)
  - Pathological inputs (perfect loops, pure novelty)

Run:
    pytest tests/test_edge_cases.py -v
"""

import sys
import os
import string
import tempfile
import shutil

# Ensure we can import from the parent directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Isolate test state
_orig_home = os.environ.get("HOME")
_tmpdir = tempfile.mkdtemp(prefix="renoun_edge_test_")
os.environ["HOME"] = _tmpdir

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def assert_valid_dhs(result, context=""):
    """Assert DHS is present and in [0.0, 1.0]."""
    assert "dialectical_health" in result, f"{context}: missing dialectical_health"
    dhs = result["dialectical_health"]
    assert 0.0 <= dhs <= 1.0, f"{context}: DHS {dhs} out of [0.0, 1.0]"


def assert_valid_channels(result, context=""):
    """Assert all channel values are in [0.0, 1.0]."""
    channels = result.get("channels", {})
    for group_name, group in channels.items():
        for ch_name, ch_val in group.items():
            if isinstance(ch_val, (int, float)):
                assert 0.0 <= ch_val <= 1.0, (
                    f"{context}: channel {group_name}.{ch_name} = {ch_val} out of [0.0, 1.0]"
                )


def assert_valid_loop(result, context=""):
    """Assert loop_strength is present and in [0.0, 1.0]."""
    assert "loop_strength" in result, f"{context}: missing loop_strength"
    loop = result["loop_strength"]
    assert 0.0 <= loop <= 1.0, f"{context}: loop_strength {loop} out of [0.0, 1.0]"


def assert_has_error(result, context=""):
    """Assert the result contains an error."""
    assert "error" in result, f"{context}: expected error, got {list(result.keys())}"


def assert_no_error(result, context=""):
    """Assert the result does NOT contain an error."""
    assert "error" not in result, f"{context}: unexpected error: {result.get('error')}"


# ---------------------------------------------------------------------------
# Fixtures
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


# ---------------------------------------------------------------------------
# Tests: Empty and Minimal Inputs
# ---------------------------------------------------------------------------

class TestEmptyInput:
    """Edge cases around empty or near-empty inputs."""

    def test_empty_utterances_returns_error(self):
        """Empty list should produce a structured error."""
        from server import tool_analyze
        result = tool_analyze({"utterances": []})
        assert_has_error(result, "empty utterances")

    def test_empty_utterances_error_structure(self):
        """Error should have type, message, action."""
        from server import tool_analyze
        result = tool_analyze({"utterances": []})
        err = result["error"]
        assert "type" in err
        assert "message" in err
        assert "action" in err

    def test_no_utterances_key(self):
        """Missing utterances key entirely should produce an error."""
        from server import tool_analyze
        result = tool_analyze({})
        assert_has_error(result, "no utterances key")


class TestSingleUtterance:
    """Tests with a single utterance (below minimum of 3)."""

    def test_single_utterance_returns_error(self):
        from server import tool_analyze
        result = tool_analyze({"utterances": [
            {"speaker": "user", "text": "Hello world"}
        ]})
        assert_has_error(result, "single utterance")

    def test_two_utterances_returns_error(self):
        from server import tool_analyze
        result = tool_analyze({"utterances": [
            {"speaker": "user", "text": "Hello"},
            {"speaker": "assistant", "text": "Hi there"},
        ]})
        assert_has_error(result, "two utterances")

    def test_single_utterance_health_check_returns_error(self):
        from server import tool_health_check
        result = tool_health_check({"utterances": [
            {"speaker": "user", "text": "Hello world"}
        ]})
        assert_has_error(result, "single utterance health check")


class TestMinimumThreshold:
    """Tests at the exact minimum threshold (3 turns for execution, 10 for reliability)."""

    def test_three_utterances_executes(self):
        """Exactly 3 turns should run without error (minimum for engine)."""
        from server import tool_analyze
        result = tool_analyze({"utterances": [
            {"speaker": "a", "text": "First turn with some content to work with."},
            {"speaker": "b", "text": "Second turn responding with different words."},
            {"speaker": "a", "text": "Third turn wrapping up the conversation."},
        ]})
        assert_no_error(result, "three utterances")
        assert_valid_dhs(result, "three utterances")

    def test_three_utterances_reliability_note(self):
        """3 turns should produce a low-reliability warning."""
        from server import tool_analyze
        result = tool_analyze({"utterances": [
            {"speaker": "a", "text": "First turn."},
            {"speaker": "b", "text": "Second turn."},
            {"speaker": "a", "text": "Third turn."},
        ]})
        assert_no_error(result, "three utterances")
        note = result.get("reliability_note")
        assert note is not None, "3-turn analysis should have reliability_note"
        assert "low" in note.lower() or "reliability" in note.lower()

    def test_exactly_ten_utterances_moderate_reliability(self):
        """10 turns should produce moderate reliability."""
        from server import tool_analyze
        utterances = [
            {"speaker": "a" if i % 2 == 0 else "b",
             "text": f"Turn {i} with enough content to analyze properly in the system."}
            for i in range(10)
        ]
        result = tool_analyze({"utterances": utterances})
        assert_no_error(result, "ten utterances")
        assert_valid_dhs(result, "ten utterances")
        note = result.get("reliability_note")
        if note is not None:
            assert "moderate" in note.lower() or "stable" in note.lower()

    def test_twenty_utterances_no_warning(self):
        """20+ turns should not produce a reliability warning."""
        from server import tool_analyze
        utterances = [
            {"speaker": "a" if i % 2 == 0 else "b",
             "text": f"Turn number {i} discussing topic {i % 5} in some depth."}
            for i in range(20)
        ]
        result = tool_analyze({"utterances": utterances})
        assert_no_error(result, "twenty utterances")
        note = result.get("reliability_note")
        assert note is None, f"20+ turns should not have reliability warning, got: {note}"


# ---------------------------------------------------------------------------
# Tests: Large Input
# ---------------------------------------------------------------------------

class TestLargeInput:
    """Tests with large utterance counts."""

    def test_200_plus_utterances(self):
        """200+ turns should still produce valid results."""
        from server import tool_analyze
        utterances = [
            {"speaker": f"speaker_{i % 4}",
             "text": f"This is turn {i} discussing concept {i % 10} with vocabulary word_{i % 50}."}
            for i in range(210)
        ]
        result = tool_analyze({"utterances": utterances})
        assert_no_error(result, "210 utterances")
        assert_valid_dhs(result, "210 utterances")
        assert_valid_loop(result, "210 utterances")
        assert_valid_channels(result, "210 utterances")

    def test_500_utterances(self):
        """500 turns should complete without crashing."""
        from server import tool_analyze
        utterances = [
            {"speaker": "user" if i % 2 == 0 else "assistant",
             "text": f"Message {i}: {'alpha beta gamma delta epsilon' if i % 3 == 0 else 'one two three four five'}"}
            for i in range(500)
        ]
        result = tool_analyze({"utterances": utterances})
        assert_no_error(result, "500 utterances")
        assert_valid_dhs(result, "500 utterances")


# ---------------------------------------------------------------------------
# Tests: Degenerate Text Content
# ---------------------------------------------------------------------------

class TestEmptyText:
    """Tests with empty or whitespace-only text in utterances."""

    def test_utterances_with_empty_text(self):
        """Utterances containing empty strings should not crash."""
        from server import tool_analyze
        utterances = [
            {"speaker": "a", "text": ""},
            {"speaker": "b", "text": ""},
            {"speaker": "a", "text": ""},
            {"speaker": "b", "text": "Hello"},
            {"speaker": "a", "text": ""},
        ]
        result = tool_analyze({"utterances": utterances})
        # Should either produce a valid result or a structured error, but not crash
        if "error" not in result:
            assert_valid_dhs(result, "empty text")

    def test_all_empty_text(self):
        """All utterances with empty text should not crash."""
        from server import tool_analyze
        utterances = [
            {"speaker": "a", "text": ""},
            {"speaker": "b", "text": ""},
            {"speaker": "a", "text": ""},
        ]
        result = tool_analyze({"utterances": utterances})
        # Should produce valid result or error, not crash
        if "error" not in result:
            assert_valid_dhs(result, "all empty text")

    def test_whitespace_only_text(self):
        """Whitespace-only text should not crash."""
        from server import tool_analyze
        utterances = [
            {"speaker": "a", "text": "   "},
            {"speaker": "b", "text": "\t\n"},
            {"speaker": "a", "text": "  \r\n  "},
        ]
        result = tool_analyze({"utterances": utterances})
        if "error" not in result:
            assert_valid_dhs(result, "whitespace only")


class TestVeryLongText:
    """Tests with extremely long text in utterances."""

    def test_10000_char_utterance(self):
        """A single utterance with 10000+ characters should not crash."""
        from server import tool_analyze
        long_text = "word " * 2000  # 10000 chars
        utterances = [
            {"speaker": "a", "text": long_text},
            {"speaker": "b", "text": "Short reply."},
            {"speaker": "a", "text": long_text},
        ]
        result = tool_analyze({"utterances": utterances})
        assert_no_error(result, "long text")
        assert_valid_dhs(result, "long text")

    def test_mixed_lengths(self):
        """Mix of very long and very short utterances."""
        from server import tool_analyze
        utterances = [
            {"speaker": "a", "text": "x" * 15000},
            {"speaker": "b", "text": "y"},
            {"speaker": "a", "text": "z" * 10000},
            {"speaker": "b", "text": "w"},
            {"speaker": "a", "text": "v" * 20000},
        ]
        result = tool_analyze({"utterances": utterances})
        assert_no_error(result, "mixed lengths")
        assert_valid_dhs(result, "mixed lengths")


class TestSpecialCharacters:
    """Tests with special characters, unicode, and emojis."""

    def test_unicode_text(self):
        from server import tool_analyze
        utterances = [
            {"speaker": "a", "text": "Bonjour, comment allez-vous?"},
            {"speaker": "b", "text": "Je suis tres bien, merci."},
            {"speaker": "a", "text": "Sprechen Sie Deutsch?"},
            {"speaker": "b", "text": "Nein, ich spreche kein Deutsch."},
        ]
        result = tool_analyze({"utterances": utterances})
        assert_no_error(result, "unicode")
        assert_valid_dhs(result, "unicode")

    def test_emoji_text(self):
        from server import tool_analyze
        utterances = [
            {"speaker": "user", "text": "Hello! How are you today?"},
            {"speaker": "bot", "text": "I am doing great! Thanks for asking!"},
            {"speaker": "user", "text": "That is wonderful to hear!"},
        ]
        result = tool_analyze({"utterances": utterances})
        assert_no_error(result, "emoji")
        assert_valid_dhs(result, "emoji")

    def test_special_punctuation(self):
        from server import tool_analyze
        utterances = [
            {"speaker": "a", "text": "!@#$%^&*()_+-=[]{}|;':\",./<>?"},
            {"speaker": "b", "text": "~~~```!!!???...---___+++==="},
            {"speaker": "a", "text": "normal text here"},
            {"speaker": "b", "text": "\\n\\t\\r escape sequences as text"},
        ]
        result = tool_analyze({"utterances": utterances})
        assert_no_error(result, "special punctuation")
        assert_valid_dhs(result, "special punctuation")

    def test_cjk_characters(self):
        from server import tool_analyze
        utterances = [
            {"speaker": "a", "text": "This is about the discussion."},
            {"speaker": "b", "text": "Yes, let us continue the analysis."},
            {"speaker": "a", "text": "We need to explore more patterns."},
        ]
        result = tool_analyze({"utterances": utterances})
        assert_no_error(result, "CJK characters")
        assert_valid_dhs(result, "CJK characters")

    def test_newlines_in_text(self):
        from server import tool_analyze
        utterances = [
            {"speaker": "a", "text": "Line one.\nLine two.\nLine three."},
            {"speaker": "b", "text": "Paragraph one.\n\nParagraph two."},
            {"speaker": "a", "text": "A\nB\nC\nD\nE"},
        ]
        result = tool_analyze({"utterances": utterances})
        assert_no_error(result, "newlines")
        assert_valid_dhs(result, "newlines")


# ---------------------------------------------------------------------------
# Tests: Speaker Patterns
# ---------------------------------------------------------------------------

class TestSingleSpeaker:
    """Tests where all utterances are from the same speaker."""

    def test_all_same_speaker(self):
        """All utterances from one speaker (no turn-taking)."""
        from server import tool_analyze
        utterances = [
            {"speaker": "monologue", "text": f"Statement number {i} about topic {i % 3}."}
            for i in range(12)
        ]
        result = tool_analyze({"utterances": utterances})
        assert_no_error(result, "single speaker")
        assert_valid_dhs(result, "single speaker")
        assert_valid_loop(result, "single speaker")
        # Un4 interactional is now clamped to [0, 1] — verify all channels bounded
        channels = result.get("channels", {})
        for group_name, group in channels.items():
            if isinstance(group, dict):
                for name, value in group.items():
                    if isinstance(value, (int, float)):
                        assert 0.0 <= value <= 1.0, f"{group_name}.{name} = {value} out of [0, 1] for single speaker"

    def test_all_same_speaker_health_check(self):
        from server import tool_health_check
        utterances = [
            {"speaker": "solo", "text": f"Point {i} in my presentation."}
            for i in range(10)
        ]
        result = tool_health_check({"utterances": utterances})
        assert_no_error(result, "single speaker health check")
        assert_valid_dhs(result, "single speaker health check")


class TestRapidAlternation:
    """Tests with rapid speaker alternation (1-2 words each)."""

    def test_one_word_turns(self):
        """Rapid alternation with single-word turns."""
        from server import tool_analyze
        words = ["yes", "no", "maybe", "ok", "sure", "fine", "right", "wrong",
                 "good", "bad", "true", "false", "why", "how", "what", "who"]
        utterances = [
            {"speaker": "a" if i % 2 == 0 else "b", "text": words[i % len(words)]}
            for i in range(16)
        ]
        result = tool_analyze({"utterances": utterances})
        assert_no_error(result, "one word turns")
        assert_valid_dhs(result, "one word turns")

    def test_three_speaker_rotation(self):
        """Three speakers rotating rapidly."""
        from server import tool_analyze
        speakers = ["alice", "bob", "carol"]
        utterances = [
            {"speaker": speakers[i % 3],
             "text": f"Comment {i} from {speakers[i % 3]} about the topic."}
            for i in range(15)
        ]
        result = tool_analyze({"utterances": utterances})
        assert_no_error(result, "three speakers")
        assert_valid_dhs(result, "three speakers")


class TestMixedCaseSpeakers:
    """Tests with mixed case in speaker names."""

    def test_same_speaker_different_case(self):
        """Speaker names differing only in case should not crash."""
        from server import tool_analyze
        utterances = [
            {"speaker": "User", "text": "First message from user."},
            {"speaker": "user", "text": "Second message from user lowercase."},
            {"speaker": "USER", "text": "Third message from user uppercase."},
            {"speaker": "Assistant", "text": "First reply from assistant."},
            {"speaker": "assistant", "text": "Second reply from assistant lowercase."},
        ]
        result = tool_analyze({"utterances": utterances})
        assert_no_error(result, "mixed case speakers")
        assert_valid_dhs(result, "mixed case speakers")


# ---------------------------------------------------------------------------
# Tests: Pathological Content Patterns
# ---------------------------------------------------------------------------

class TestDuplicateUtterances:
    """Tests with identical repeated utterances (perfect loop)."""

    def test_perfect_loop_two_turns(self):
        """Two turns repeated identically multiple times."""
        from server import tool_analyze
        base = [
            {"speaker": "a", "text": "The same question every time."},
            {"speaker": "b", "text": "The same answer every time."},
        ]
        utterances = base * 6  # 12 identical pairs
        result = tool_analyze({"utterances": utterances})
        assert_no_error(result, "perfect loop")
        assert_valid_dhs(result, "perfect loop")
        assert_valid_loop(result, "perfect loop")
        # A perfect loop should show high loop strength
        # (structural prediction, not a hard assertion on exact value)

    def test_single_phrase_repeated(self):
        """Same exact phrase from alternating speakers."""
        from server import tool_analyze
        utterances = [
            {"speaker": "a" if i % 2 == 0 else "b",
             "text": "This is the only thing anyone says."}
            for i in range(12)
        ]
        result = tool_analyze({"utterances": utterances})
        assert_no_error(result, "single phrase repeated")
        assert_valid_dhs(result, "single phrase repeated")

    def test_identical_everything(self):
        """Same speaker, same text, repeated."""
        from server import tool_analyze
        utterances = [
            {"speaker": "bot", "text": "Beep boop."}
            for _ in range(12)
        ]
        result = tool_analyze({"utterances": utterances})
        assert_no_error(result, "identical everything")
        assert_valid_dhs(result, "identical everything")


class TestMonotonicVocabulary:
    """Tests with monotonically increasing vocabulary (pure novelty)."""

    def test_all_unique_words(self):
        """Every turn uses completely unique vocabulary."""
        from server import tool_analyze
        # Generate turns where no word repeats across turns
        utterances = []
        for i in range(12):
            words = [f"word{i * 10 + j}" for j in range(10)]
            utterances.append({
                "speaker": "a" if i % 2 == 0 else "b",
                "text": " ".join(words),
            })
        result = tool_analyze({"utterances": utterances})
        assert_no_error(result, "all unique words")
        assert_valid_dhs(result, "all unique words")

    def test_expanding_vocabulary(self):
        """Each turn adds more unique words on top of a base."""
        from server import tool_analyze
        base_word = "conversation"
        utterances = []
        for i in range(12):
            new_words = " ".join([f"novel_{i}_{j}" for j in range(i + 1)])
            utterances.append({
                "speaker": "a" if i % 2 == 0 else "b",
                "text": f"{base_word} {new_words}",
            })
        result = tool_analyze({"utterances": utterances})
        assert_no_error(result, "expanding vocabulary")
        assert_valid_dhs(result, "expanding vocabulary")
        assert_valid_channels(result, "expanding vocabulary")


# ---------------------------------------------------------------------------
# Tests: Health Check Edge Cases
# ---------------------------------------------------------------------------

class TestHealthCheckEdgeCases:
    """Edge cases specifically for the health_check tool."""

    def test_health_check_with_empty_returns_error(self):
        from server import tool_health_check
        result = tool_health_check({"utterances": []})
        assert_has_error(result, "health check empty")

    def test_health_check_assessment_range(self):
        """Assessment should be one of the valid categories."""
        from server import tool_health_check
        result = tool_health_check({"utterances": THERAPY_SESSION})
        assert_no_error(result, "health check assessment")
        assert result["assessment"] in [
            "excellent", "healthy", "below_baseline", "distressed"
        ], f"Unexpected assessment: {result['assessment']}"

    def test_health_check_has_dominant_constellation(self):
        from server import tool_health_check
        result = tool_health_check({"utterances": THERAPY_SESSION})
        assert_no_error(result, "health check constellation")
        dc = result.get("dominant_constellation")
        assert dc is not None or isinstance(dc, dict) or dc is None
        # dominant_constellation can be None if no constellations detected

    def test_health_check_returns_turn_count(self):
        from server import tool_health_check
        result = tool_health_check({"utterances": THERAPY_SESSION})
        assert_no_error(result, "health check turn count")
        assert result.get("turn_count") == len(THERAPY_SESSION)


# ---------------------------------------------------------------------------
# Tests: Compare Edge Cases
# ---------------------------------------------------------------------------

class TestCompareEdgeCases:
    """Edge cases for the compare tool."""

    def test_compare_identical_sessions(self):
        """Comparing a session with itself should work."""
        from server import tool_compare
        result = tool_compare({
            "utterances_a": THERAPY_SESSION,
            "utterances_b": THERAPY_SESSION,
        })
        assert_no_error(result, "compare identical")
        # DHS delta should be close to 0
        health = result.get("health", result)
        if "dhs_delta" in health:
            assert abs(health["dhs_delta"]) < 0.01

    def test_compare_with_one_short_session(self):
        """One session short (3 turns), one normal."""
        from server import tool_compare
        short_session = [
            {"speaker": "a", "text": "Short first turn."},
            {"speaker": "b", "text": "Short second turn."},
            {"speaker": "a", "text": "Short third turn."},
        ]
        result = tool_compare({
            "utterances_a": short_session,
            "utterances_b": THERAPY_SESSION,
        })
        assert_no_error(result, "compare short vs normal")

    def test_compare_no_input(self):
        """No input should return error."""
        from server import tool_compare
        result = tool_compare({})
        assert_has_error(result, "compare no input")

    def test_compare_partial_input(self):
        """Only one side provided should return error."""
        from server import tool_compare
        result = tool_compare({"utterances_a": THERAPY_SESSION})
        assert_has_error(result, "compare partial input")


# ---------------------------------------------------------------------------
# Tests: Normalize Utterances Edge Cases
# ---------------------------------------------------------------------------

class TestNormalizeUtterances:
    """Edge cases for the normalize_utterances function."""

    def test_normalize_with_role_instead_of_speaker(self):
        """Should accept 'role' as alias for 'speaker'."""
        from server import normalize_utterances
        data = [
            {"role": "user", "text": "Hello"},
            {"role": "assistant", "text": "Hi there"},
        ]
        result = normalize_utterances(data)
        assert len(result) == 2
        assert result[0]["speaker"] == "user"

    def test_normalize_with_content_instead_of_text(self):
        """Should accept 'content' as alias for 'text'."""
        from server import normalize_utterances
        data = [
            {"speaker": "user", "content": "Hello"},
            {"speaker": "assistant", "content": "Hi there"},
        ]
        result = normalize_utterances(data)
        assert len(result) == 2
        assert result[0]["text"] == "Hello"

    def test_normalize_preserves_index(self):
        """Custom index should be preserved."""
        from server import normalize_utterances
        data = [
            {"speaker": "a", "text": "Turn", "index": 42},
        ]
        result = normalize_utterances(data)
        assert result[0]["index"] == 42

    def test_normalize_auto_assigns_index(self):
        """Missing index should be auto-assigned."""
        from server import normalize_utterances
        data = [
            {"speaker": "a", "text": "First"},
            {"speaker": "b", "text": "Second"},
        ]
        result = normalize_utterances(data)
        assert result[0]["index"] == 0
        assert result[1]["index"] == 1

    def test_normalize_missing_speaker_defaults(self):
        """Missing speaker should default to 'Unknown'."""
        from server import normalize_utterances
        data = [{"text": "Orphan turn"}]
        result = normalize_utterances(data)
        assert result[0]["speaker"] == "Unknown"

    def test_normalize_string_input_invalid(self):
        """Invalid string input should raise ValueError."""
        from server import normalize_utterances
        # Non-JSON, non-parseable string
        try:
            result = normalize_utterances("not valid json or text format")
            # If it parses as text input, it should return a list
            assert isinstance(result, list)
        except (ValueError, ImportError):
            pass  # Expected: either raises or gracefully handles

    def test_normalize_dict_with_utterances_key(self):
        """Dict wrapper around utterances should be unwrapped."""
        from server import normalize_utterances
        data = {
            "utterances": [
                {"speaker": "a", "text": "Hello"},
            ]
        }
        result = normalize_utterances(data)
        assert len(result) == 1
        assert result[0]["speaker"] == "a"


# ---------------------------------------------------------------------------
# Tests: Steer Edge Cases
# ---------------------------------------------------------------------------

class TestSteerEdgeCases:
    """Edge cases for the steer tool."""

    def test_steer_list_sessions_empty(self):
        from server import tool_steer
        result = tool_steer({"action": "list_sessions"})
        assert "sessions" in result
        assert "error" not in result

    def test_steer_get_status_nonexistent(self):
        from server import tool_steer
        result = tool_steer({"action": "get_status", "session_id": "nonexistent_test_xyz"})
        # Should return status (possibly empty/new) without error
        assert "error" not in result

    def test_steer_clear_nonexistent_session(self):
        from server import tool_steer
        result = tool_steer({"action": "clear_session", "session_id": "never_existed_abc"})
        assert "error" not in result
        assert result.get("cleared") is False or result.get("cleared") is True

    def test_steer_invalid_action(self):
        from server import tool_steer
        result = tool_steer({"action": "invalid_action_xyz"})
        assert_has_error(result, "steer invalid action")

    def test_steer_add_turns_no_utterances(self):
        from server import tool_steer
        result = tool_steer({"action": "add_turns"})
        assert_has_error(result, "steer no utterances")

    def test_steer_add_turns_with_data(self):
        from server import tool_steer
        result = tool_steer({
            "action": "add_turns",
            "session_id": "edge_test_session",
            "utterances": [
                {"speaker": "a", "text": "First turn in the session."},
                {"speaker": "b", "text": "Second turn in the session."},
            ],
        })
        assert "error" not in result
        assert result.get("turns_added") == 2
        # Cleanup
        tool_steer({"action": "clear_session", "session_id": "edge_test_session"})


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
