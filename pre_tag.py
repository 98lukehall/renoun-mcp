#!/usr/bin/env python3
"""
ReNoUn Pre-Tagger — Optional turn-level content tagging and weighting.

Produces per-turn metadata (phase, mode, speech_act, weight) that the weighted
analysis wrapper uses to focus structural analysis on substantive turns.

Two modes:
  - pre_tag(): Uses Anthropic API for LLM-based tagging (ANTHROPIC_API_KEY required)
  - pre_tag_cheap(): Heuristic-only, no API call, instant

Uses only stdlib (urllib.request) — no anthropic SDK dependency.
"""

import os
import re
import json
import urllib.request
import urllib.error
from typing import Optional


# ---------------------------------------------------------------------------
# Heuristic tagger (no LLM)
# ---------------------------------------------------------------------------

# Patterns that indicate low-substance turns
_CODE_PATTERN = re.compile(
    r'(```|`[^`]+`|def |class |import |function |const |let |var |<[a-z]+[\s>]|{[^}]*}|=>|\bpx\b|\bcss\b|\bhtml\b)',
    re.IGNORECASE,
)
_URL_PATTERN = re.compile(r'https?://\S+|www\.\S+')
_ADMIN_PATTERN = re.compile(
    r'\b(fix|update|change|set|move|adjust|rename|deploy|push|merge|commit|install|run|build|compile)\b',
    re.IGNORECASE,
)
_ACK_PATTERN = re.compile(
    r'^(ok|okay|sure|yes|yeah|got it|done|thanks|thank you|right|yep|uh huh|mm|hmm|alright|sounds good|will do|on it)[\s.!?]*$',
    re.IGNORECASE,
)


def _heuristic_phase(index: int, total: int) -> str:
    """Estimate conversation phase from position."""
    ratio = index / max(total - 1, 1)
    if ratio < 0.1:
        return "opening"
    elif ratio > 0.9:
        return "closing"
    elif ratio < 0.3:
        return "exploration"
    else:
        return "working"


def _heuristic_mode(text: str) -> str:
    """Estimate mode from text content."""
    if _CODE_PATTERN.search(text) or _URL_PATTERN.search(text):
        return "task"
    if _ADMIN_PATTERN.search(text) and len(text.split()) < 15:
        return "task"
    return "philosophical"


def _heuristic_speech_act(text: str) -> str:
    """Estimate speech act from text."""
    stripped = text.strip()
    if stripped.endswith("?"):
        return "question"
    if _ACK_PATTERN.match(stripped):
        return "acknowledgment"
    if _ADMIN_PATTERN.search(stripped) and len(stripped.split()) < 12:
        return "direction"
    return "assertion"


def _heuristic_weight(text: str) -> float:
    """Compute weight based on heuristics.

    - Short turns (<10 words): 0.5
    - Code/URL heavy turns: 0.3
    - Pure acknowledgments: 0.2
    - Everything else: 1.0
    """
    stripped = text.strip()
    words = stripped.split()
    word_count = len(words)

    if _ACK_PATTERN.match(stripped):
        return 0.2
    if _CODE_PATTERN.search(stripped) or _URL_PATTERN.search(stripped):
        return 0.3
    if word_count < 10:
        return 0.5
    return 1.0


def pre_tag_cheap(utterances: list[dict]) -> list[dict]:
    """Tag each utterance using heuristics only. No API call.

    Returns list of tag dicts with index, phase, mode, speech_act, weight.
    """
    total = len(utterances)
    tags = []
    for i, utt in enumerate(utterances):
        text = utt.get("text", "")
        tags.append({
            "index": utt.get("index", i),
            "phase": _heuristic_phase(i, total),
            "mode": _heuristic_mode(text),
            "speech_act": _heuristic_speech_act(text),
            "weight": round(_heuristic_weight(text), 2),
        })
    return tags


# ---------------------------------------------------------------------------
# LLM tagger (Anthropic API via urllib)
# ---------------------------------------------------------------------------

_ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"

_SYSTEM_PROMPT = """You are a conversation tagger. For each turn, output a JSON object with these fields:
- "index": the turn number (0-indexed, matching input)
- "phase": one of "opening", "exploration", "working", "closing", "administrative"
- "mode": one of "philosophical", "emotional", "task", "relational", "meta"
- "speech_act": one of "question", "assertion", "reflection", "direction", "acknowledgment"
- "weight": float 0.0-1.0, how substantive/meaningful this turn is for the conversation's core purpose. Administrative noise (fixing CSS, deployment commands, simple acknowledgments) gets low weight. Deep exploration, questions, reflections get high weight.

Return ONLY a JSON array of these objects. No explanation, no markdown fences, just the array."""


def _build_user_prompt(utterances: list[dict]) -> str:
    """Format utterances for the LLM."""
    lines = []
    for i, utt in enumerate(utterances):
        speaker = utt.get("speaker", "Unknown")
        text = utt.get("text", "")
        lines.append(f"[{i}] {speaker}: {text}")
    return "\n".join(lines)


def _call_anthropic(utterances: list[dict], model: str, api_key: str) -> list[dict]:
    """Call Anthropic API to tag utterances. Uses urllib only."""
    payload = {
        "model": model,
        "max_tokens": 4096,
        "system": _SYSTEM_PROMPT,
        "messages": [
            {"role": "user", "content": _build_user_prompt(utterances)},
        ],
    }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        _ANTHROPIC_API_URL,
        data=data,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "User-Agent": "renoun-mcp-pretag/1.2.0",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Anthropic API error ({e.code}): {body}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Cannot reach Anthropic API: {e.reason}")

    # Extract text content from response
    content_blocks = result.get("content", [])
    text_content = ""
    for block in content_blocks:
        if block.get("type") == "text":
            text_content += block.get("text", "")

    if not text_content.strip():
        raise RuntimeError("Anthropic API returned empty response")

    # Parse JSON from response (strip markdown fences if present)
    cleaned = text_content.strip()
    if cleaned.startswith("```"):
        # Remove markdown code fences
        lines = cleaned.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        cleaned = "\n".join(lines).strip()

    try:
        tags = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Failed to parse LLM response as JSON: {e}\nResponse: {cleaned[:500]}")

    if not isinstance(tags, list):
        raise RuntimeError(f"Expected JSON array from LLM, got {type(tags).__name__}")

    # Validate and normalize
    valid_phases = {"opening", "exploration", "working", "closing", "administrative"}
    valid_modes = {"philosophical", "emotional", "task", "relational", "meta"}
    valid_acts = {"question", "assertion", "reflection", "direction", "acknowledgment"}

    normalized = []
    for i, tag in enumerate(tags):
        normalized.append({
            "index": tag.get("index", i),
            "phase": tag.get("phase", "working") if tag.get("phase") in valid_phases else "working",
            "mode": tag.get("mode", "task") if tag.get("mode") in valid_modes else "task",
            "speech_act": tag.get("speech_act", "assertion") if tag.get("speech_act") in valid_acts else "assertion",
            "weight": max(0.0, min(1.0, float(tag.get("weight", 1.0)))),
        })

    return normalized


def pre_tag(utterances: list[dict], model: str = "claude-sonnet-4-20250514") -> list[dict]:
    """Tag each utterance with content-level metadata and a weight.

    Uses Anthropic API if ANTHROPIC_API_KEY is set.
    Falls back to heuristic tagger if no API key.

    Args:
        utterances: List of {speaker, text} dicts.
        model: Anthropic model to use for tagging.

    Returns:
        List of tag dicts with index, phase, mode, speech_act, weight.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")

    if not api_key:
        return pre_tag_cheap(utterances)

    try:
        return _call_anthropic(utterances, model, api_key)
    except Exception:
        # LLM call failed — fall back to heuristics
        return pre_tag_cheap(utterances)
