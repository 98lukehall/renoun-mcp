#!/usr/bin/env python3
"""
Shared fixtures for ReNoUn test suite.

Provides:
  - Isolated HOME directory for tests that use file-based state
  - Common test data (utterances, klines)
  - Helper assertion functions
"""

import os
import shutil
import tempfile

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def isolated_home(monkeypatch):
    """Provide an isolated HOME directory for tests that write to disk.

    Yields the temp directory path, cleans up after test.
    """
    tmpdir = tempfile.mkdtemp(prefix="renoun_test_")
    monkeypatch.setenv("HOME", tmpdir)
    yield tmpdir
    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture
def therapy_session():
    """A sample therapy conversation with 12 turns."""
    return [
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


@pytest.fixture
def improved_session():
    """A follow-up therapy session showing improvement."""
    return [
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


@pytest.fixture
def large_conversation():
    """A 40-turn conversation for testing window-filling behavior."""
    turns = []
    speakers = ["user", "assistant"]
    topics = [
        "I want to discuss project planning.",
        "Let me outline the key milestones.",
        "What about the timeline for phase one?",
        "We should allocate resources carefully.",
        "The budget constraints need attention.",
        "Can we prioritize the critical path?",
        "Testing should happen in parallel.",
        "Documentation is often overlooked.",
        "Stakeholder communication matters.",
        "Let me summarize what we agreed on.",
    ]
    for i in range(40):
        turns.append({
            "speaker": speakers[i % 2],
            "text": topics[i % len(topics)] + f" (turn {i})",
        })
    return turns


@pytest.fixture
def sample_klines():
    """Generate 50 synthetic OHLCV candles for finance tests."""
    import random
    random.seed(42)
    klines = []
    price = 100.0
    for _ in range(50):
        change = random.gauss(0, 0.02) * price
        open_p = price
        close_p = price + change
        high_p = max(open_p, close_p) * (1 + abs(random.gauss(0, 0.01)))
        low_p = min(open_p, close_p) * (1 - abs(random.gauss(0, 0.01)))
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
