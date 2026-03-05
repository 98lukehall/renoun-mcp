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
from pathlib import Path
from typing import Any, Optional
from datetime import datetime

TOOL_VERSION = "1.2.2"
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
]

TOOL_HANDLERS = {
    "renoun_analyze": tool_analyze,
    "renoun_health_check": tool_health_check,
    "renoun_compare": tool_compare,
    "renoun_pattern_query": tool_pattern_query,
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
