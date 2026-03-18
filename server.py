#!/usr/bin/env python3
"""
ReNoUn MCP Server — Model Context Protocol server for structural analysis.

Exposes the ReNoUn 17-channel engine as MCP tools that any MCP-compatible
agent can discover and invoke.

Tools:
    renoun_analyze       — Full structural analysis on conversation turns
    renoun_compare       — Structural diff between two analysis results
    renoun_health_check  — Lightweight DHS + constellation check
    renoun_pattern_query — Query longitudinal pattern history
    renoun_steer         — Real-time inference steering with rolling windows

Usage:
    python3 server.py          # Start MCP server on stdio (or JSON-RPC fallback)

Requirements:
    pip install mcp numpy

Patent Pending #63/923,592 — core engine is proprietary and closed-source.
This server wraps the engine as a black box.
"""

import sys
import os
import json
import hashlib
import asyncio
import threading
from pathlib import Path
from typing import Any, Optional
from datetime import datetime

TOOL_VERSION = "1.4.0"
ENGINE_VERSION = "4.1"
SCHEMA_VERSION = "1.1"

# Tracks whether we're using local engine or remote API
_USE_REMOTE_API = False
_remote_client = None

# ---------------------------------------------------------------------------
# Engine import
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent


def _build_core_search_paths() -> list:
    """Build ordered search paths for core.py.

    Priority:
    1. RENOUN_CORE_PATH environment variable (explicit override)
    2. ~/.renoun/config.json core_path field
    3. Standard filesystem locations (dev fallback)
    """
    paths = []

    # 1. Environment variable — highest priority
    env_path = os.environ.get("RENOUN_CORE_PATH")
    if env_path:
        p = Path(env_path)
        # Accept either a direct path to core.py or a directory containing it
        if p.is_file():
            paths.append(p)
        elif p.is_dir():
            paths.append(p / "core.py")

    # 2. Config file
    config_path = Path.home() / ".renoun" / "config.json"
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
            cp = config.get("core_path")
            if cp:
                p = Path(cp)
                if p.is_file():
                    paths.append(p)
                elif p.is_dir():
                    paths.append(p / "core.py")
        except (json.JSONDecodeError, OSError):
            pass  # Config unreadable — skip silently

    # 3. Standard filesystem locations (dev fallback)
    paths.extend([
        SCRIPT_DIR / "core.py",
        SCRIPT_DIR.parent / "core.py",
        SCRIPT_DIR.parent / "renoun-plugin" / "core.py",  # legacy fallback
        SCRIPT_DIR.parent / "ReNoUn_podcast_corpus" / "core.py",
        SCRIPT_DIR.parent / "ReNoUn_therapy_analysis" / "core.py",
        SCRIPT_DIR.parent / "renoun-studio" / "core.py",
        Path.home() / ".renoun" / "core.py",
    ])

    return paths


CORE_SEARCH_PATHS = _build_core_search_paths()


def find_and_import_core():
    for path in CORE_SEARCH_PATHS:
        if path.exists():
            sys.path.insert(0, str(path.parent))
            from core import ReNoUnEngineV4
            return ReNoUnEngineV4
    raise ImportError(
        "ReNoUn core engine (core.py) not found. Searched:\n" +
        "\n".join(f"  - {p}" for p in CORE_SEARCH_PATHS) +
        "\n\nFix: Set RENOUN_CORE_PATH=/path/to/core.py or add core_path to ~/.renoun/config.json"
    )

# Ensure local directory is on path for renoun_analyze, renoun_compare, renoun_store imports
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

# ---------------------------------------------------------------------------
# MCP Server Implementation
# ---------------------------------------------------------------------------

try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, TextContent
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False


def create_engine():
    """Create a ReNoUn engine instance.

    Tries local core.py first. If not found, checks for remote API config
    and returns None (tool handlers use _remote_client instead).
    """
    global _USE_REMOTE_API, _remote_client

    try:
        EngineClass = find_and_import_core()
        return EngineClass()
    except ImportError:
        # No local engine — try remote API fallback
        from api_client import is_api_configured, RemoteAPIClient

        if is_api_configured():
            if _remote_client is None:
                _remote_client = RemoteAPIClient()
                _USE_REMOTE_API = True
                print("ReNoUn: Using remote API (core.py not found locally)", file=sys.stderr)
            return None  # Signal to tool handlers to use _remote_client
        else:
            raise ImportError(
                "ReNoUn core engine (core.py) not found locally, and no API key configured.\n\n"
                "Option 1 — Local engine:\n"
                "  Set RENOUN_CORE_PATH=/path/to/core.py\n\n"
                "Option 2 — Remote API (subscription required):\n"
                "  Set RENOUN_API_KEY=rn_live_your_key_here\n"
                "  Get your key at https://harrisoncollab.com\n"
            )


def normalize_utterances(data: Any) -> list:
    """Normalize input data to utterance format."""
    if isinstance(data, str):
        # Try JSON parse
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            # Parse as text
            from renoun_analyze import parse_text_input
            return parse_text_input(data)

    if isinstance(data, dict) and "utterances" in data:
        data = data["utterances"]

    if not isinstance(data, list):
        raise ValueError("Input must be a list of utterance objects")

    utterances = []
    for i, item in enumerate(data):
        utterances.append({
            "index": item.get("index", i),
            "speaker": item.get("speaker", item.get("role", "Unknown")),
            "text": item.get("text", item.get("content", "")),
        })
    return utterances


# ---------------------------------------------------------------------------
# Tool Implementations
# ---------------------------------------------------------------------------

def _compute_result_hash(output: dict) -> str:
    """Deterministic SHA-256 hash of analytical fields."""
    hashable = {
        "dialectical_health": output.get("dialectical_health"),
        "loop_strength": output.get("loop_strength"),
        "channels": output.get("channels"),
    }
    canonical = json.dumps(hashable, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _reliability_note(turn_count: int) -> Optional[str]:
    """Return reliability assessment based on turn count."""
    if turn_count < 10:
        return (
            f"Low reliability — {turn_count} turns analyzed. "
            "ReNoUn requires 10+ turns for stable channel values and "
            "20+ turns for reliable constellation detection."
        )
    elif turn_count < 20:
        return (
            f"Moderate reliability — {turn_count} turns analyzed. "
            "Channel values are stable. Constellation detection improves with 20+ turns."
        )
    return None


def _structured_error(error_type: str, message: str, action: str) -> dict:
    """Return a structured error payload."""
    return {"error": {"type": error_type, "message": message, "action": action}}


# ---------------------------------------------------------------------------
# Agent Action Mappings
# ---------------------------------------------------------------------------
# Injected into every constellation in MCP output so agents know
# what to DO, not just what was observed.

AGENT_ACTIONS = {
    "CLOSED_LOOP": {
        "agent_action": "explore_new_angle",
        "agent_guidance": "Current approach is cycling. Try different framing or topic.",
    },
    "HIGH_SYMMETRY": {
        "agent_action": "introduce_variation",
        "agent_guidance": "Interaction overly structured. Consider open-ended prompts.",
    },
    "PATTERN_BREAK": {
        "agent_action": "support_integration",
        "agent_guidance": "A shift happened. Help process before moving on.",
    },
    "CONVERGENCE": {
        "agent_action": "maintain_trajectory",
        "agent_guidance": "Productive movement occurring. Do not disrupt.",
    },
    "SCATTERING": {
        "agent_action": "provide_structure",
        "agent_guidance": "Coherence low. Offer grounding, summarize, or simplify.",
    },
    "REPEATED_DISRUPTION": {
        "agent_action": "slow_down",
        "agent_guidance": "Multiple disruptions without recovery. Reduce pace.",
    },
    "DIP_AND_RECOVERY": {
        "agent_action": "acknowledge_shift",
        "agent_guidance": "Disruption processed successfully. Note resilience.",
    },
    "SURFACE_VARIATION": {
        "agent_action": "go_deeper",
        "agent_guidance": "New words, same dynamics. Push past surface change.",
    },
}


def _inject_agent_actions(output: dict) -> dict:
    """Inject agent_action and agent_guidance into every constellation in output."""
    for constellation in output.get("constellations", []):
        detected = constellation.get("detected", "")
        mapping = AGENT_ACTIONS.get(detected, {})
        constellation["agent_action"] = mapping.get("agent_action", "observe")
        constellation["agent_guidance"] = mapping.get("agent_guidance", "No specific action recommended.")
    return output


def tool_analyze(arguments: dict) -> dict:
    """Full 17-channel structural analysis."""
    try:
        engine = create_engine()
    except ImportError as e:
        return _structured_error("engine_not_found", str(e), "Set RENOUN_CORE_PATH or RENOUN_API_KEY")

    try:
        utterances = normalize_utterances(arguments.get("utterances", []))
    except (ValueError, KeyError) as e:
        return _structured_error("parse_error", str(e), "Provide utterances as [{speaker, text}, ...]")

    if len(utterances) < 3:
        return _structured_error("insufficient_data", f"Only {len(utterances)} turns provided.", "Minimum 3 turns required. 10+ recommended for reliable results.")

    # Remote API fallback
    if engine is None and _remote_client is not None:
        try:
            return _remote_client.analyze(utterances)
        except Exception as e:
            return _structured_error("api_error", str(e), "Check your API key and network connection.")

    # Check for optional weighting parameters
    weights = arguments.get("weights")
    tags = arguments.get("tags")
    weighting_mode = arguments.get("weighting_mode", "weight")

    if weights is not None or tags is not None:
        # Weighted analysis path
        try:
            from weighted_analysis import weighted_analyze
            output = weighted_analyze(
                utterances,
                weights=weights,
                tags=tags,
                mode=weighting_mode,
                engine=engine,
            )
        except (ValueError, TypeError) as e:
            return _structured_error("weighting_error", str(e), "Check weights/tags array length and values.")
    else:
        # Standard unweighted path
        result = engine.score(utterances)
        output = result.to_dict()

    turn_count = len(utterances)
    timestamp = datetime.utcnow().isoformat() + "Z"

    output["engine"] = {
        "version": ENGINE_VERSION,
        "schema_version": SCHEMA_VERSION,
        "tool_version": TOOL_VERSION,
        "analysis_timestamp": timestamp,
    }
    output["result_hash"] = _compute_result_hash(output)
    output["reliability_note"] = _reliability_note(turn_count)

    # Inject agent actions into constellation output
    _inject_agent_actions(output)

    output["_meta"] = {
        "engine_version": ENGINE_VERSION,
        "schema_version": SCHEMA_VERSION,
        "tool_version": TOOL_VERSION,
        "timestamp": timestamp,
        "turn_count": turn_count,
        "speakers": list(set(u.get("speaker", "Unknown") for u in utterances)),
        "min_turns_warning": turn_count < 10,
    }
    return output


def tool_health_check(arguments: dict) -> dict:
    """Lightweight health check — DHS + dominant constellation only."""
    try:
        engine = create_engine()
    except ImportError as e:
        return _structured_error("engine_not_found", str(e), "Set RENOUN_CORE_PATH or RENOUN_API_KEY")

    try:
        utterances = normalize_utterances(arguments.get("utterances", []))
    except (ValueError, KeyError) as e:
        return _structured_error("parse_error", str(e), "Provide utterances as [{speaker, text}, ...]")

    if len(utterances) < 3:
        return _structured_error("insufficient_data", f"Only {len(utterances)} turns provided.", "Minimum 3 turns required. 10+ recommended.")

    # Remote API fallback
    if engine is None and _remote_client is not None:
        try:
            return _remote_client.health_check(utterances)
        except Exception as e:
            return _structured_error("api_error", str(e), "Check your API key and network connection.")

    result = engine.score(utterances)
    turn_count = len(utterances)

    dominant = None
    if result.constellations:
        best = max(result.constellations, key=lambda c: c.confidence)
        mapping = AGENT_ACTIONS.get(best.detected, {})
        dominant = {
            "pattern": best.detected,
            "confidence": round(best.confidence, 3),
            "description": best.plain_description,
            "agent_action": mapping.get("agent_action", "observe"),
            "agent_guidance": mapping.get("agent_guidance", "No specific action recommended."),
        }

    return {
        "dialectical_health": round(result.dialectical_health, 3),
        "assessment": (
            "excellent" if result.dialectical_health >= 0.75 else
            "healthy" if result.dialectical_health >= 0.55 else
            "below_baseline" if result.dialectical_health >= 0.35 else
            "distressed"
        ),
        "loop_strength": round(result.loop_strength, 3),
        "dominant_constellation": dominant,
        "turn_count": turn_count,
        "summary": result.summary,
        "reliability_note": _reliability_note(turn_count),
        "engine": {"version": ENGINE_VERSION, "tool_version": TOOL_VERSION},
    }


def tool_compare(arguments: dict) -> dict:
    """Compare two analysis results structurally."""
    # Remote API fallback — send the whole request to the API
    if _USE_REMOTE_API and _remote_client is not None:
        try:
            return _remote_client.compare(arguments)
        except Exception as e:
            return _structured_error("api_error", str(e), "Check your API key and network connection.")

    result_a = arguments.get("result_a")
    result_b = arguments.get("result_b")
    utts_a = arguments.get("utterances_a")
    utts_b = arguments.get("utterances_b")

    has_results = bool(result_a and result_b)
    has_utterances = bool(utts_a and utts_b)

    # Reject mixed modes — must be one or the other
    if has_results and has_utterances:
        return _structured_error(
            "ambiguous_input",
            "Both result pairs and utterance pairs provided.",
            "Provide EITHER result_a/result_b OR utterances_a/utterances_b, not both."
        )

    if not has_results and not has_utterances:
        # Check for partial input to give a better error
        if result_a or result_b:
            return _structured_error("incomplete_input", "Only one result provided.", "Provide both result_a and result_b.")
        if utts_a or utts_b:
            return _structured_error("incomplete_input", "Only one utterance set provided.", "Provide both utterances_a and utterances_b.")
        return _structured_error("missing_input", "No input provided.", "Provide result_a/result_b or utterances_a/utterances_b.")

    if has_utterances:
        result_a = tool_analyze({"utterances": utts_a})
        result_b = tool_analyze({"utterances": utts_b})
        # Check for analysis errors
        if "error" in result_a:
            return _structured_error("analysis_failed", f"Failed to analyze utterances_a: {result_a['error']}", "Check utterances_a data.")
        if "error" in result_b:
            return _structured_error("analysis_failed", f"Failed to analyze utterances_b: {result_b['error']}", "Check utterances_b data.")

    try:
        from renoun_compare import compare_pair
        return compare_pair(result_a, result_b,
                           arguments.get("label_a", "Session A"),
                           arguments.get("label_b", "Session B"))
    except ImportError:
        # Inline minimal comparison
        dhs_a = result_a.get("dialectical_health", 0)
        dhs_b = result_b.get("dialectical_health", 0)
        return {
            "dhs_a": dhs_a,
            "dhs_b": dhs_b,
            "dhs_delta": round(dhs_b - dhs_a, 3),
            "trend": "improving" if dhs_b > dhs_a + 0.05 else ("declining" if dhs_b < dhs_a - 0.05 else "stable"),
        }


def tool_pattern_query(arguments: dict) -> dict:
    """Query and manage longitudinal pattern history."""
    # Remote API fallback
    if _USE_REMOTE_API and _remote_client is not None:
        action = arguments.get("action", "list")
        try:
            return _remote_client.pattern_query(action, arguments)
        except Exception as e:
            return _structured_error("api_error", str(e), "Check your API key and network connection.")

    try:
        from renoun_store import query_sessions, compute_trend, list_sessions, save_result, ensure_history_dir

        action = arguments.get("action", "list")

        if action == "list":
            return {"sessions": list_sessions()}

        elif action == "query":
            results = query_sessions(
                from_date=arguments.get("from_date"),
                to_date=arguments.get("to_date"),
                domain=arguments.get("domain"),
                tag=arguments.get("tag"),
                constellation=arguments.get("constellation"),
                dhs_below=arguments.get("dhs_below"),
                dhs_above=arguments.get("dhs_above"),
            )
            return {"sessions": results, "count": len(results)}

        elif action == "trend":
            return compute_trend(
                domain=arguments.get("domain"),
                metric=arguments.get("metric", "dhs"),
                from_date=arguments.get("from_date"),
                to_date=arguments.get("to_date"),
            )

        elif action == "save":
            # Save an analysis result to history
            result_data = arguments.get("result")
            # Handle case where result is passed as a JSON string
            if isinstance(result_data, str):
                try:
                    result_data = json.loads(result_data)
                except (json.JSONDecodeError, TypeError):
                    pass
            session_name = arguments.get("session_name")

            if not result_data:
                return _structured_error("missing_input", "No result data provided.", "Include 'result' field with a renoun_analyze output object.")
            if not session_name:
                return _structured_error("missing_input", "No session_name provided.", "Include 'session_name' to identify this session.")

            domain = arguments.get("domain", "")
            tags_raw = arguments.get("tags", "")
            tags = [t.strip() for t in tags_raw.split(",") if t.strip()] if isinstance(tags_raw, str) else (tags_raw or [])

            # Write result to a temp file, then save via store
            ensure_history_dir()
            import tempfile
            with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
                json.dump(result_data, f, default=str)
                tmp_path = f.name

            try:
                save_output = save_result(tmp_path, session_name, domain, tags)
                return save_output
            finally:
                os.unlink(tmp_path)

        else:
            return _structured_error("unknown_action", f"Unknown action: {action}.", "Use list, query, trend, or save.")

    except ImportError:
        return _structured_error("module_not_found", "Pattern history module not available.", "Ensure renoun_store.py is accessible in the plugin scripts directory.")


# ---------------------------------------------------------------------------
# MCP Server Setup
# ---------------------------------------------------------------------------

# Tool definitions as plain dicts (always available)
# Synced with tool_definition.json v1.1.0
TOOL_DEFS = [
    {
        "name": "renoun_analyze",
        "description": (
            "Deep structural analysis of a conversation. Detects loops, stuck states, "
            "breakthroughs, and convergence patterns across 17 channels — without reading "
            "the content. Returns a health score (0-1), pattern classifications (8 types "
            "including CLOSED_LOOP, PATTERN_BREAK, CONVERGENCE, SURFACE_VARIATION), "
            "breakthrough moments, and actionable next steps. Use this to understand why "
            "a conversation succeeded or failed structurally. Minimum 10 turns for reliable results."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "utterances": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "speaker": {"type": "string", "description": "Speaker identifier (e.g., 'user', 'assistant', 'Alice')"},
                            "text": {"type": "string", "description": "What the speaker said"},
                            "index": {"type": "integer", "description": "Turn number (0-indexed). Auto-assigned if omitted."},
                        },
                        "required": ["speaker", "text"],
                    },
                    "description": "Conversation turns in order. Speaker/text pairs.",
                    "minItems": 3,
                },
                "weights": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Optional per-turn weights (0.0-1.0). Controls how much each turn contributes to analysis. Omit for uniform weighting.",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "Optional per-turn tags from pre_tag(). Each tag has phase, mode, speech_act, and weight fields.",
                },
                "weighting_mode": {
                    "type": "string",
                    "enum": ["weight", "exclude", "segment"],
                    "default": "weight",
                    "description": "How to apply weights: 'weight' (post-process scores), 'exclude' (remove low-weight turns), 'segment' (analyze groups separately).",
                },
            },
            "required": ["utterances"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "dialectical_health": {"type": "number", "description": "Structural health score (0.0-1.0). Below 0.45 = stuck or fragmented. 0.55-0.75 = healthy. Above 0.75 = excellent convergence."},
                "loop_strength": {"type": "number", "description": "How much the conversation recycles the same patterns (0.0-1.0). Above 0.7 = heavily looping."},
                "channels": {"type": "object", "description": "17-channel breakdown: 5 recurrence (stability), 6 novelty (disruption), 6 unity (coherence) measurements."},
                "constellations": {
                    "type": "array",
                    "description": "Structural patterns detected. Each includes pattern name, confidence, description, and agent_action (what to do about it).",
                    "items": {
                        "type": "object",
                        "properties": {
                            "detected": {"type": "string", "enum": ["CLOSED_LOOP", "HIGH_SYMMETRY", "PATTERN_BREAK", "CONVERGENCE", "SCATTERING", "REPEATED_DISRUPTION", "DIP_AND_RECOVERY", "SURFACE_VARIATION"]},
                            "confidence": {"type": "number", "description": "Match confidence (0.0-1.0). Above 0.6 = strong detection."},
                            "agent_action": {"type": "string", "enum": ["explore_new_angle", "introduce_variation", "support_integration", "maintain_trajectory", "provide_structure", "slow_down", "acknowledge_shift", "go_deeper"]},
                            "agent_guidance": {"type": "string", "description": "One-line explanation of what the agent should consider doing."},
                        },
                    },
                },
                "novelty_items": {"type": "array", "description": "Breakthrough moments — turns where the conversation structurally shifted."},
                "summary": {"type": "string", "description": "One-paragraph structural narrative."},
                "recommendations": {"type": "array", "description": "Actionable structural observations."},
            },
        },
    },
    {
        "name": "renoun_health_check",
        "description": (
            "Fast structural triage. Is this conversation stuck, healthy, or falling apart? "
            "Returns one score, one pattern, one summary. Use this for quick checks before "
            "deciding whether to run full analysis. Sub-50ms."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "utterances": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "speaker": {"type": "string", "description": "Speaker identifier (e.g., 'user', 'assistant')"},
                            "text": {"type": "string", "description": "What the speaker said"},
                        },
                        "required": ["speaker", "text"],
                    },
                    "description": "Conversation turns in order. Speaker/text pairs. Minimum 3, recommend 10+.",
                    "minItems": 3,
                }
            },
            "required": ["utterances"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "dialectical_health": {"type": "number", "description": "0.0-1.0. Quick read: below 0.45 = problem, above 0.55 = fine."},
                "assessment": {"type": "string", "enum": ["excellent", "healthy", "below_baseline", "distressed"], "description": "Plain-language health bucket."},
                "loop_strength": {"type": "number", "description": "0.0-1.0. How circular is the conversation."},
                "dominant_constellation": {
                    "type": "object",
                    "description": "The strongest structural pattern detected, with agent_action.",
                    "properties": {
                        "pattern": {"type": "string", "description": "Constellation pattern name."},
                        "confidence": {"type": "number", "description": "Match confidence 0.0-1.0."},
                        "description": {"type": "string", "description": "Plain-language pattern description."},
                        "agent_action": {"type": "string", "description": "Recommended agent action."},
                        "agent_guidance": {"type": "string", "description": "One-line guidance for the agent."},
                    },
                },
                "summary": {"type": "string", "description": "One-line structural read."},
            },
        },
    },
    {
        "name": "renoun_compare",
        "description": (
            "Structural A/B test between two conversations. Did the second session improve "
            "over the first? Which channels shifted? Did the pattern change from stuck to "
            "converging? Use for prompt iteration testing, session-over-session tracking, or "
            "comparing different agent strategies. Provide either pre-analyzed results or raw turns."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "result_a": {"type": "object", "description": "First analysis result (output of renoun_analyze)"},
                "result_b": {"type": "object", "description": "Second analysis result"},
                "utterances_a": {"type": "array", "description": "First conversation turns (alternative to result_a)"},
                "utterances_b": {"type": "array", "description": "Second conversation turns"},
                "label_a": {"type": "string", "default": "Session A"},
                "label_b": {"type": "string", "default": "Session B"},
            },
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "health": {"type": "object", "description": "DHS comparison with delta and trend (improving/declining/stable)."},
                "constellation_transition": {"type": "object", "description": "Pattern shift between sessions (e.g., CLOSED_LOOP -> CONVERGENCE)."},
                "top_shifts": {"type": "array", "description": "The 5 channels that changed most between sessions, with direction and magnitude."},
            },
        },
    },
    {
        "name": "renoun_pattern_query",
        "description": (
            "Query structural patterns across sessions over time. How has conversation health "
            "trended this month? Which sessions were stuck? When did convergence patterns start "
            "appearing? Supports save, list, filtered queries, and trend computation against "
            "locally stored history."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["save", "list", "query", "trend"],
                    "description": "save = persist an analysis result. list = show all stored sessions. query = filter by criteria. trend = compute metric trajectory over time.",
                },
                "result": {"type": "object", "description": "For save: the analysis result to persist."},
                "session_name": {"type": "string", "description": "For save: name for this session."},
                "domain": {"type": "string", "description": "Filter or tag by domain (e.g., therapy, sales, support)."},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "For save: tags for this session."},
                "from_date": {"type": "string", "description": "Filter: start date (YYYY-MM-DD)."},
                "to_date": {"type": "string", "description": "Filter: end date (YYYY-MM-DD)."},
                "constellation": {"type": "string", "description": "Filter: only sessions with this dominant pattern."},
                "tag": {"type": "string", "description": "Filter: only sessions with this tag."},
                "dhs_below": {"type": "number", "description": "Filter: only sessions with health below this value."},
                "dhs_above": {"type": "number", "description": "Filter: only sessions with health above this value."},
                "metric": {"type": "string", "default": "dhs", "description": "For trend: which metric to track (dhs or loop)."},
            },
            "required": ["action"],
        },
    },
    {
        "name": "renoun_steer",
        "description": (
            "Real-time inference steering. Monitor a live conversation and get actionable signals "
            "when the model should change strategy. Maintains rolling window buffers per session, "
            "runs structural analysis on each window, and emits SteeringSignals when thresholds "
            "are crossed (DHS drop, loop persistence, scattering). Use add_turns to feed conversation "
            "data incrementally; signals are emitted automatically when windows fill."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "utterances": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "speaker": {"type": "string", "description": "Speaker identifier"},
                            "text": {"type": "string", "description": "What the speaker said"},
                        },
                        "required": ["speaker", "text"],
                    },
                    "description": "New conversation turns to add to the session buffer.",
                },
                "session_id": {
                    "type": "string",
                    "default": "default",
                    "description": "Unique session identifier. Tracks state across calls.",
                },
                "action": {
                    "type": "string",
                    "enum": ["add_turns", "get_status", "clear_session", "list_sessions"],
                    "default": "add_turns",
                    "description": "add_turns = append turns and analyze. get_status = session state. clear_session = remove session. list_sessions = show all active.",
                },
                "window_size": {
                    "type": "integer",
                    "default": 30,
                    "description": "Turns per analysis window. Default 30.",
                },
                "session_ttl": {
                    "type": "integer",
                    "default": 3600,
                    "description": "Session time-to-live in seconds. Default 3600 (1 hour).",
                },
            },
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "turns_added": {"type": "integer"},
                "total_turns": {"type": "integer"},
                "windows_analyzed": {"type": "integer"},
                "dhs_trend": {"type": "string", "enum": ["improving", "declining", "stable", "unknown"]},
                "signal": {
                    "type": ["object", "null"],
                    "description": "Steering signal if thresholds triggered. Null if no signal.",
                    "properties": {
                        "action": {"type": "string", "description": "Recommended agent action (e.g., explore_new_angle, provide_structure)."},
                        "guidance": {"type": "string", "description": "Human-readable guidance for the agent."},
                        "urgency": {"type": "string", "enum": ["HIGH", "MEDIUM", "INFO"]},
                        "confidence": {"type": "number"},
                        "triggered_by": {"type": "array", "items": {"type": "string"}},
                        "dhs_current": {"type": "number"},
                        "dhs_previous": {"type": "number"},
                        "dhs_delta": {"type": "number"},
                        "reward_signal": {"type": "number"},
                        "constellation": {"type": "string"},
                        "recommendations": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
        },
    },
    {
        "name": "renoun_finance_analyze",
        "description": (
            "Structural analysis of financial OHLCV data using ReNoUn's 17-channel engine. "
            "Returns DHS (Dialectical Health Score), constellation patterns, stress levels, "
            "and exposure recommendations. Validated drawdown reduction on 31/31 datasets "
            "across 9 crypto assets and 5 timeframes. Use as a risk overlay — reduces "
            "exposure during structural disorder."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "klines": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "Array of OHLCV candle objects. Each must have: open, high, low, close, volume. Optional: taker_buy_volume, timestamp.",
                    "minItems": 10,
                },
                "symbol": {"type": "string", "default": "UNKNOWN", "description": "Trading pair symbol (e.g., BTCUSDT)."},
                "timeframe": {
                    "type": "string",
                    "enum": ["1m", "5m", "15m", "1h", "4h", "1d"],
                    "default": "1h",
                    "description": "Candle timeframe for annualization and micro-constellation detection.",
                },
                "include_exposure": {
                    "type": "boolean",
                    "default": True,
                    "description": "Include v2 exposure recommendation (smoothed + persistence-weighted).",
                },
                "include_temporal": {
                    "type": "boolean",
                    "default": False,
                    "description": "Include temporal constellation sequencing — windowed analysis showing constellation transitions, persistence counting, and temporal channel patterns. Enables reports like '3rd consecutive CLOSED_LOOP'.",
                },
                "temporal_window_size": {
                    "type": "integer",
                    "default": 30,
                    "description": "Candles per temporal analysis window (only used when include_temporal=true).",
                    "minimum": 10,
                },
                "temporal_step_size": {
                    "type": "integer",
                    "default": 15,
                    "description": "Window advancement step in candles (only used when include_temporal=true).",
                    "minimum": 5,
                },
            },
            "required": ["klines"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "dialectical_health": {"type": "number", "description": "Structural health score (0.0-1.0) applied to financial OHLCV data."},
                "loop_strength": {"type": "number", "description": "How much the price action recycles the same structural patterns (0.0-1.0)."},
                "constellations": {
                    "type": "array",
                    "description": "Structural patterns detected in the financial data.",
                    "items": {"type": "object", "properties": {"detected": {"type": "string"}, "confidence": {"type": "number"}}},
                },
                "stress": {
                    "type": "object",
                    "description": "Market stress indicators including drawdown and volatility expansion.",
                    "properties": {"drawdown": {"type": "number"}, "vol_expansion": {"type": "number"}},
                },
                "exposure": {
                    "type": "object",
                    "description": "Exposure recommendation based on structural analysis.",
                    "properties": {
                        "scalar": {"type": "number", "description": "Final smoothed exposure value (0.0-1.0). Use this as primary signal."},
                        "raw_v1": {"type": "number", "description": "Raw DHS-to-exposure before smoothing."},
                        "smoothed_v2": {"type": "number", "description": "After asymmetric EMA smoothing."},
                        "constellation_persistence": {"type": "integer", "description": "Windows current constellation has persisted."},
                        "constellation_churn": {"type": "number", "description": "Unique constellations in last 5 windows (0.0-1.0)."},
                        "crash_regime": {"type": "boolean", "description": "Whether crash regime is active."},
                        "interpretation": {"type": "string", "description": "Human-readable exposure recommendation."},
                        "note": {"type": "string", "description": "Context about stateless vs session-aware tracking."},
                    },
                },
            },
        },
    },
    {
        "name": "renoun_agent_monitor",
        "description": (
            "Real-time structural health monitoring for AI agent sessions. "
            "Feed agent trace events incrementally and receive alerts when "
            "structural pathologies are detected (stuck loops, oversight loss, "
            "scattering, cascading errors). Supports per-agent and per-swarm monitoring."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["ingest", "dashboard", "configure", "clear", "self_check"],
                    "default": "ingest",
                    "description": (
                        "ingest = feed trace events. dashboard = get current health state. "
                        "configure = update thresholds. clear = reset session. "
                        "self_check = proprioceptive signal — returns behavioral guidance "
                        "based on the agent's own structural health. Use this for agent "
                        "self-regulation (every ~30 turns)."
                    ),
                },
                "session_id": {
                    "type": "string",
                    "default": "default",
                    "description": "Unique session identifier for the agent workflow being monitored.",
                },
                "events": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "agent_id": {"type": "string"},
                            "event_type": {
                                "type": "string",
                                "enum": [
                                    "user_message", "assistant_message", "tool_call",
                                    "tool_result", "tool_error", "think", "agent_handoff",
                                    "file_write", "file_read", "bash_command", "bash_result",
                                ],
                            },
                            "content": {"type": "string"},
                            "timestamp": {"type": "string"},
                        },
                        "required": ["agent_id", "event_type", "content"],
                    },
                    "description": "Array of trace events to ingest.",
                },
                "config": {
                    "type": "object",
                    "description": "Optional configuration overrides for thresholds and monitoring mode.",
                },
            },
            "required": ["action"],
        },
    },
    {
        "name": "renoun_alignment_classify",
        "description": (
            "Structural alignment classification using the Life as Ground + ReNoUn bridge. "
            "Classifies conversations as INTEGRATIVELY_COHERENT, SUPPRESSIVELY_COHERENT, "
            "FRAGMENTED, or RIGID. Adds corrigibility scoring, challenge detection, "
            "and revision trace analysis on top of base ReNoUn analysis."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "utterances": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "speaker": {"type": "string"},
                            "text": {"type": "string"},
                        },
                        "required": ["speaker", "text"],
                    },
                    "description": "Conversation turns. Minimum 4, recommended 10+.",
                    "minItems": 4,
                },
                "include_bridge_signals": {
                    "type": "boolean",
                    "default": True,
                    "description": "Include per-speaker revision traces, challenge detection, vocabulary adoption.",
                },
                "include_renoun_raw": {
                    "type": "boolean",
                    "default": False,
                    "description": "Include full ReNoUn channel-level analysis.",
                },
            },
            "required": ["utterances"],
        },
    },
    {
        "name": "renoun_recovery_analyze",
        "description": (
            "Adaptive Recovery Analysis — measures how systems RESPOND to structural "
            "perturbation. The dynamic complement to static DHS. Detects perturbation events "
            "in a DHS trajectory, classifies outcomes (RECOVERED, REORGANIZED, COLLAPSED, "
            "STAGNATED, ONGOING), and computes an Adaptive Capacity Score (0-1). "
            "Works on any windowed analysis output: feed it the 'windows' from sequential "
            "renoun_analyze or renoun_finance_analyze calls. "
            "Key metrics: recovery rate, recovery surplus (positive = antifragile), "
            "recovery time, constellation sequences during perturbation-recovery cycles. "
            "Validated on financial crash data (COVID, LUNA, FTX) and conversation trajectories."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "windows": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "dhs": {"type": "number", "description": "Dialectical Health Score for this window (0.0-1.0)"},
                            "constellations": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Detected constellation patterns in this window",
                            },
                        },
                        "required": ["dhs"],
                    },
                    "description": (
                        "Array of analysis windows, each with at least a 'dhs' field. "
                        "Typically produced by running renoun_analyze or renoun_finance_analyze "
                        "on sliding windows of data. Minimum 5 windows for meaningful results."
                    ),
                    "minItems": 2,
                },
                "drop_threshold": {
                    "type": "number",
                    "description": (
                        "Minimum DHS drop to count as a perturbation. "
                        "Set to 'auto' (omit this field) to auto-calibrate from 1σ of the trajectory. "
                        "Default: auto-calibrated."
                    ),
                },
                "recovery_fraction": {
                    "type": "number",
                    "default": 0.85,
                    "description": "Fraction of drop that must be recovered to count as RECOVERED (0-1). Default 0.85.",
                },
                "baseline_lookback": {
                    "type": "integer",
                    "default": 3,
                    "description": "Number of prior windows used to compute rolling baseline. Default 3.",
                },
                "max_lookforward": {
                    "type": "integer",
                    "default": 12,
                    "description": "Maximum windows after trough to look for recovery. Default 12.",
                },
            },
            "required": ["windows"],
        },
    },
]



# ---------------------------------------------------------------------------
# Steering Tool
# ---------------------------------------------------------------------------

_steering_monitor = None
_steering_lock = threading.Lock()


def _get_steering_monitor(config: Optional[dict] = None):
    """Lazy-init singleton SteeringMonitor."""
    global _steering_monitor
    if _steering_monitor is None:
        with _steering_lock:
            if _steering_monitor is None:
                from steering import SteeringMonitor, start_cleanup_thread
                _steering_monitor = SteeringMonitor(config)
                start_cleanup_thread(_steering_monitor)
    return _steering_monitor


def tool_steer(arguments: dict) -> dict:
    """Real-time inference steering — monitor live conversations and emit strategy signals.

    Actions:
        add_turns (default) — Append turns and run analysis if window is full.
        get_status           — Return session state and window history.
        clear_session        — Remove a session.
        list_sessions        — List all active sessions.
    """
    action = arguments.get("action", "add_turns")
    session_id = arguments.get("session_id", "default")

    # Optional per-call config overrides
    config_overrides = {}
    if "window_size" in arguments:
        config_overrides["window_size"] = arguments["window_size"]
    if "session_ttl" in arguments:
        config_overrides["session_ttl"] = arguments["session_ttl"]

    monitor = _get_steering_monitor(config_overrides if config_overrides else None)

    if action == "list_sessions":
        return {
            "sessions": monitor.list_sessions(),
            "active_count": monitor.active_session_count,
        }

    if action == "clear_session":
        existed = monitor.clear_session(session_id)
        return {"cleared": existed, "session_id": session_id}

    if action == "get_status":
        return monitor.get_session_status(session_id)

    if action == "add_turns":
        utterances = arguments.get("utterances")
        if not utterances:
            return _structured_error(
                "missing_input",
                "No utterances provided.",
                "Include 'utterances' array of {speaker, text} objects.",
            )

        # Normalize turns
        try:
            turns = normalize_utterances(utterances)
        except (ValueError, KeyError) as e:
            return _structured_error("parse_error", str(e), "Provide utterances as [{speaker, text}, ...]")

        signal = monitor.add_turns(
            session_id=session_id,
            new_turns=turns,
            analyze_fn=lambda args: tool_analyze(args),
            health_fn=lambda args: tool_health_check(args),
        )

        status = monitor.get_session_status(session_id)

        result = {
            "session_id": session_id,
            "turns_added": len(turns),
            "total_turns": status.get("total_turns", 0),
            "windows_analyzed": status.get("windows_analyzed", 0),
            "dhs_trend": status.get("dhs_trend", "unknown"),
        }

        if signal:
            result["signal"] = signal
        else:
            result["signal"] = None
            result["message"] = (
                "Turns buffered. No steering signal triggered."
                if status.get("windows_analyzed", 0) > 0
                else f"Turns buffered ({status.get('buffer_size', 0)} in buffer). Waiting for window_size threshold."
            )

        return result

    return _structured_error(
        "unknown_action",
        f"Unknown action: {action}.",
        "Use add_turns, get_status, clear_session, or list_sessions.",
    )


# ---------------------------------------------------------------------------
# Finance Tool
# ---------------------------------------------------------------------------

_finance_trackers = {}


def tool_finance_analyze(arguments: dict) -> dict:
    """Structural analysis of financial OHLCV data with exposure recommendations."""
    klines = arguments.get("klines")
    if not klines:
        return _structured_error("missing_klines", "klines array is required.", "Provide an array of OHLCV candle objects.")

    if len(klines) < 10:
        return _structured_error("insufficient_data", f"Need at least 10 candles, got {len(klines)}.", "Provide more OHLCV data.")

    symbol = arguments.get("symbol", "UNKNOWN")
    timeframe = arguments.get("timeframe", "1h")
    include_exposure = arguments.get("include_exposure", True)

    include_temporal = arguments.get("include_temporal", False)
    temporal_window_size = arguments.get("temporal_window_size", 30)
    temporal_step_size = arguments.get("temporal_step_size", 15)

    try:
        if include_temporal and len(klines) >= temporal_window_size:
            from adapters.finance import analyze_with_temporal
            result = analyze_with_temporal(
                klines, symbol=symbol, timeframe=timeframe,
                window_size=temporal_window_size,
                step_size=temporal_step_size,
            )
        else:
            from renoun_finance import analyze_financial
            result = analyze_financial(klines, symbol=symbol, timeframe=timeframe)
    except ImportError:
        return _structured_error("module_not_found", "renoun_finance module not available.", "Ensure renoun_finance.py is in the server directory.")
    except Exception as e:
        return _structured_error("analysis_error", f"Finance analysis failed: {str(e)}", "Check kline data format.")

    if include_exposure:
        try:
            from renoun_exposure import ConstellationTracker, smooth_exposure, dhs_to_exposure

            dhs = result["dialectical_health"]
            consts = result.get("constellations", [])
            top_const = consts[0]["detected"] if consts else "NONE"
            loop = result["loop_strength"]
            dd_stress = result.get("stress", {}).get("drawdown", 0.0)
            vol_stress = float(result.get("stress", {}).get("vol_expansion", 0.0))

            # Stateless per-call: use fresh tracker (no session memory)
            tracker = ConstellationTracker()
            persist = tracker.update(top_const)
            eff_const = persist.get("effective_constellation", top_const)
            crash_reg = persist.get("crash_regime", False)

            # v1: raw exposure from DHS + constellation + stress (no smoothing)
            raw_exp = dhs_to_exposure(dhs, eff_const, loop, dd_stress, vol_stress,
                                       persistence_mult=persist["persistence_mult"],
                                       crash_regime=crash_reg)

            # v2: smoothed exposure (asymmetric EMA against a default of 1.0)
            # For stateless per-call, prev_smooth defaults to 1.0 (full exposure)
            # so the smoothing only reduces from full. In sequential calls,
            # callers should track prev_smooth externally.
            smoothed_exp = smooth_exposure(raw_exp, prev_smooth=1.0)

            # Use the smoothed value as the primary scalar
            scalar = round(smoothed_exp, 3)

            # Interpretation with richer context
            if smoothed_exp >= 0.8:
                interp = f"Full exposure — healthy structure ({top_const})"
            elif smoothed_exp >= 0.5:
                interp = f"Moderate exposure — {top_const} detected, some caution warranted"
            elif smoothed_exp >= 0.3:
                interp = f"Reduced exposure — {top_const} signals structural degradation"
            else:
                interp = f"Minimal exposure — {top_const} indicates significant structural disorder"

            # Add stress context to interpretation
            stress_notes = []
            if dd_stress > 0.3:
                stress_notes.append(f"drawdown stress {dd_stress:.2f}")
            if vol_stress > 0.15:
                stress_notes.append(f"vol expansion {vol_stress:.2f}")
            if stress_notes:
                interp += f" (active stress: {', '.join(stress_notes)})"

            result["exposure"] = {
                "scalar": scalar,
                "raw_v1": round(raw_exp, 3),
                "smoothed_v2": scalar,
                "constellation_persistence": persist["run_length"],
                "constellation_churn": persist["churn"],
                "crash_regime": crash_reg,
                "interpretation": interp,
                "note": (
                    "Stateless per-call — persistence=1, churn=0.2 are defaults from fresh tracker. "
                    "For session-aware smoothing with real persistence tracking, use renoun_steer "
                    "or make sequential calls and track prev_smooth externally."
                ),
            }
        except ImportError:
            result["exposure"] = {"error": "renoun_exposure module not available"}

    return result


def _tool_agent_monitor(arguments: dict) -> dict:
    """Wrapper for agent_monitor.tool_agent_monitor to handle import.

    Routes 'self_check' action to the proprioceptive engine for
    agent self-regulation. All other actions route to the standard
    agent monitor.
    """
    action = arguments.get("action", "ingest")

    # Route self_check to proprioceptive engine
    if action == "self_check":
        try:
            from proprioceptive import tool_self_check
            # Map to proprioceptive action
            prop_args = {**arguments}
            prop_args["action"] = prop_args.get("self_check_action", "check")
            return tool_self_check(prop_args)
        except ImportError as e:
            return {"error": f"proprioceptive module not available: {e}"}
        except Exception as e:
            return _structured_error("self_check_error", str(e), "Check proprioceptive.py is present")

    try:
        from agent_monitor import tool_agent_monitor
        return tool_agent_monitor(arguments)
    except ImportError as e:
        return {"error": f"agent_monitor module not available: {e}"}
    except Exception as e:
        return _structured_error("agent_monitor_error", str(e), "Check agent_monitor.py is present")


def _tool_alignment_classify(arguments: dict) -> dict:
    """Wrapper for alignment_api.handle_alignment_classify."""
    try:
        from alignment_api import handle_alignment_classify
        return handle_alignment_classify(arguments)
    except ImportError as e:
        return {"error": f"alignment_api module not available: {e}"}
    except Exception as e:
        return _structured_error("alignment_classify_error", str(e), "Check alignment_api.py is present")


def tool_recovery_analyze(arguments: dict) -> dict:
    """Adaptive Recovery Analysis — measures system response to structural perturbation."""
    windows = arguments.get("windows")
    if not windows:
        return _structured_error("missing_windows", "windows array is required.",
                                 "Provide an array of window objects with at least 'dhs' fields.")

    if len(windows) < 2:
        return _structured_error("insufficient_data", f"Need at least 2 windows, got {len(windows)}.",
                                 "Provide more analysis windows.")

    # Validate window format
    for i, w in enumerate(windows):
        if 'dhs' not in w:
            return _structured_error("invalid_window", f"Window {i} missing 'dhs' field.",
                                     "Each window must have a 'dhs' field (0.0-1.0).")
        if not isinstance(w.get('constellations'), list):
            w['constellations'] = []

    try:
        from recovery import analyze_recovery, calibrate_threshold
        import math

        # Auto-calibrate threshold if not provided
        drop_threshold = arguments.get("drop_threshold")
        if drop_threshold is None:
            dhs_values = [w['dhs'] for w in windows]
            drop_threshold = calibrate_threshold(dhs_values)

        profile = analyze_recovery(
            windows,
            drop_threshold=drop_threshold,
            recovery_fraction=arguments.get("recovery_fraction", 0.85),
            baseline_lookback=arguments.get("baseline_lookback", 3),
            max_lookforward=arguments.get("max_lookforward", 12),
            stabilization_window=arguments.get("stabilization_window", 3),
            stabilization_tolerance=arguments.get("stabilization_tolerance", 0.01),
        )

        # Build result
        result = {
            "n_windows": profile.n_windows,
            "dhs_mean": round(profile.dhs_mean, 4),
            "dhs_std": round(profile.dhs_std, 4),
            "dhs_trajectory": [round(d, 4) for d in profile.dhs_trajectory],
            "n_perturbations": profile.n_perturbations,
            "challenge_level": profile.challenge_level,
            "drop_threshold_used": round(drop_threshold, 4),
            "recovery_rate": round(profile.recovery_rate, 4) if not math.isnan(profile.recovery_rate) else None,
            "reorganization_ratio": round(profile.reorganization_ratio, 4) if not math.isnan(profile.reorganization_ratio) else None,
            "adaptive_capacity": round(profile.adaptive_capacity, 4) if not math.isnan(profile.adaptive_capacity) else None,
            "mean_recovery_time": profile.mean_recovery_time,
            "mean_drop_magnitude": round(profile.mean_drop_magnitude, 4),
            "mean_recovery_surplus": round(profile.mean_recovery_surplus, 4) if profile.mean_recovery_surplus is not None else None,
            "mean_recovery_horizon": round(profile.mean_recovery_horizon, 2) if profile.mean_recovery_horizon is not None else None,
            "outcome_counts": profile.outcome_counts,
            "assessment": profile.assessment,
            "perturbation_events": [
                {
                    "onset_index": e.onset_index,
                    "trough_index": e.trough_index,
                    "resolution_index": e.resolution_index,
                    "pre_dhs": round(e.pre_dhs, 4),
                    "trough_dhs": round(e.trough_dhs, 4),
                    "post_dhs": round(e.post_dhs, 4) if e.post_dhs is not None else None,
                    "drop_magnitude": round(e.drop_magnitude, 4),
                    "recovery_time": e.recovery_time,
                    "recovery_surplus": round(e.recovery_surplus, 4) if e.recovery_surplus is not None else None,
                    "recovery_horizon": round(e.recovery_horizon, 2) if e.recovery_horizon is not None else None,
                    "outcome": e.outcome.value,
                    "constellation_sequence": e.constellation_sequence,
                }
                for e in profile.perturbation_events
            ],
            "recovery_constellations": profile.recovery_constellations,
            "failure_constellations": profile.failure_constellations,
        }

        return result

    except ImportError:
        return _structured_error("module_not_found", "recovery module not available.",
                                 "Ensure recovery.py is in the server directory.")
    except Exception as e:
        return _structured_error("analysis_error", f"Recovery analysis failed: {str(e)}",
                                 "Check window data format.")


TOOL_HANDLERS = {
    "renoun_analyze": tool_analyze,
    "renoun_health_check": tool_health_check,
    "renoun_compare": tool_compare,
    "renoun_pattern_query": tool_pattern_query,
    "renoun_steer": tool_steer,
    "renoun_finance_analyze": tool_finance_analyze,
    "renoun_recovery_analyze": tool_recovery_analyze,
    "renoun_agent_monitor": _tool_agent_monitor,
    "renoun_alignment_classify": _tool_alignment_classify,
}

# ---------------------------------------------------------------------------
# MCP Tool Annotations
# ---------------------------------------------------------------------------

TOOL_ANNOTATIONS = {
    "renoun_analyze": {
        "title": "Full Structural Analysis",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
    "renoun_health_check": {
        "title": "Quick Health Check",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
    "renoun_compare": {
        "title": "Structural A/B Comparison",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
    "renoun_pattern_query": {
        "title": "Pattern History Query",
        "readOnlyHint": False,  # save action writes data
        "destructiveHint": False,
        "idempotentHint": False,  # save creates new entries
        "openWorldHint": False,
    },
    "renoun_steer": {
        "title": "Real-Time Inference Steering",
        "readOnlyHint": False,  # maintains session state
        "destructiveHint": False,
        "idempotentHint": False,  # each call advances the buffer
        "openWorldHint": False,
    },
    "renoun_finance_analyze": {
        "title": "Financial Risk Analysis",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
    "renoun_agent_monitor": {
        "title": "Agent Session Monitor",
        "readOnlyHint": False,  # maintains session state
        "destructiveHint": False,
        "idempotentHint": False,  # each call advances the buffer
        "openWorldHint": False,
    },
    "renoun_alignment_classify": {
        "title": "Alignment Classification",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
    "renoun_recovery_analyze": {
        "title": "Adaptive Recovery Analysis",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
}

# Build MCP Tool objects only if the library is available
if MCP_AVAILABLE:
    from mcp.types import ToolAnnotations
    TOOLS = [
        Tool(
            name=d["name"],
            description=d["description"],
            inputSchema=d["inputSchema"],
            annotations=ToolAnnotations(**TOOL_ANNOTATIONS.get(d["name"], {})),
        )
        for d in TOOL_DEFS
    ]
else:
    TOOLS = TOOL_DEFS  # Use plain dicts for standalone mode


# ---------------------------------------------------------------------------
# MCP Prompts
# ---------------------------------------------------------------------------

MCP_PROMPTS = [
    {
        "name": "check-conversation-health",
        "description": "Analyze the structural health of a conversation to see if it's stuck, looping, or progressing.",
        "arguments": [
            {"name": "conversation", "description": "Paste the conversation text (alternating speaker lines)", "required": True},
        ],
    },
    {
        "name": "compare-sessions",
        "description": "Compare two conversation sessions to see if the second improved over the first.",
        "arguments": [
            {"name": "session_a", "description": "First conversation text", "required": True},
            {"name": "session_b", "description": "Second conversation text", "required": True},
        ],
    },
    {
        "name": "detect-surface-variation",
        "description": "Check if a conversation has surface variation — responses that sound different but are structurally identical.",
        "arguments": [
            {"name": "conversation", "description": "Paste the conversation to check for surface variation", "required": True},
        ],
    },
]


def build_mcp_server() -> "Server":
    """Build and configure the MCP server."""
    server = Server("renoun")

    @server.list_tools()
    async def list_tools():
        return TOOLS

    @server.call_tool()
    async def call_tool(name: str, arguments: dict):
        handler = TOOL_HANDLERS.get(name)
        if not handler:
            return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]

        try:
            result = handler(arguments)
            return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]
        except Exception as e:
            return [TextContent(type="text", text=json.dumps({"error": str(e)}))]

    # Register prompts
    if MCP_AVAILABLE:
        from mcp.types import Prompt, PromptArgument, PromptMessage, TextContent as PromptTextContent

        @server.list_prompts()
        async def list_prompts():
            return [
                Prompt(
                    name=p["name"],
                    description=p["description"],
                    arguments=[PromptArgument(**a) for a in p["arguments"]],
                )
                for p in MCP_PROMPTS
            ]

        @server.get_prompt()
        async def get_prompt(name: str, arguments: dict | None = None):
            if name == "check-conversation-health":
                return {
                    "messages": [
                        PromptMessage(
                            role="user",
                            content=PromptTextContent(
                                type="text",
                                text=f"Use renoun_analyze to check the structural health of this conversation and tell me if it's stuck, looping, or making progress:\n\n{arguments.get('conversation', '')}",
                            ),
                        )
                    ]
                }
            elif name == "compare-sessions":
                return {
                    "messages": [
                        PromptMessage(
                            role="user",
                            content=PromptTextContent(
                                type="text",
                                text=f"Use renoun_compare to structurally compare these two sessions. Did the second improve?\n\nSession A:\n{arguments.get('session_a', '')}\n\nSession B:\n{arguments.get('session_b', '')}",
                            ),
                        )
                    ]
                }
            elif name == "detect-surface-variation":
                return {
                    "messages": [
                        PromptMessage(
                            role="user",
                            content=PromptTextContent(
                                type="text",
                                text=f"Use renoun_analyze to check this conversation for surface variation — where responses sound different but are structurally the same. Look for SURFACE_VARIATION constellation:\n\n{arguments.get('conversation', '')}",
                            ),
                        )
                    ]
                }
            return {"messages": []}

    return server


# ---------------------------------------------------------------------------
# Standalone mode (no MCP library) — JSON-RPC over stdio
# ---------------------------------------------------------------------------

async def standalone_server():
    """Minimal JSON-RPC server for environments without the mcp library."""
    import io

    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await asyncio.get_event_loop().connect_read_pipe(lambda: protocol, sys.stdin)

    while True:
        line = await reader.readline()
        if not line:
            break

        try:
            request = json.loads(line.decode())
        except json.JSONDecodeError:
            continue

        method = request.get("method", "")
        req_id = request.get("id")
        params = request.get("params", {})

        if method == "tools/list":
            result = {
                "tools": [
                    {
                        "name": t.get("name") if isinstance(t, dict) else t.name,
                        "description": t.get("description") if isinstance(t, dict) else t.description,
                        "inputSchema": t.get("inputSchema") if isinstance(t, dict) else t.inputSchema,
                        **({"outputSchema": t.get("outputSchema") if isinstance(t, dict) else getattr(t, "outputSchema", None)}
                           if (t.get("outputSchema") if isinstance(t, dict) else getattr(t, "outputSchema", None)) else {}),
                    }
                    for t in TOOLS
                ]
            }
        elif method == "tools/call":
            tool_name = params.get("name", "")
            arguments = params.get("arguments", {})
            handler = TOOL_HANDLERS.get(tool_name)
            if handler:
                try:
                    tool_result = handler(arguments)
                    result = {"content": [{"type": "text", "text": json.dumps(tool_result, indent=2, default=str)}]}
                except Exception as e:
                    result = {"content": [{"type": "text", "text": json.dumps({"error": str(e)})}], "isError": True}
            else:
                result = {"content": [{"type": "text", "text": f"Unknown tool: {tool_name}"}], "isError": True}
        elif method == "initialize":
            result = {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "renoun", "version": TOOL_VERSION},
            }
        else:
            result = {}

        response = {"jsonrpc": "2.0", "id": req_id, "result": result}
        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main():
    if MCP_AVAILABLE:
        server = build_mcp_server()
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())
    else:
        print("MCP library not installed. Running standalone JSON-RPC mode.", file=sys.stderr)
        print("Install with: pip install mcp", file=sys.stderr)
        await standalone_server()


def main_sync():
    """Synchronous entry point for CLI (used by pyproject.toml console_scripts)."""
    asyncio.run(main())


if __name__ == "__main__":
    main_sync()
