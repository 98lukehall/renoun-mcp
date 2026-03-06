#!/usr/bin/env python3
"""
ReNoUn Real-Time Inference Steering — Monitor live conversations and signal strategy changes.

Maintains rolling window buffers per session, runs structural analysis on each window,
compares consecutive windows, and emits SteeringSignals when thresholds are crossed.

Usage:
    from steering import SteeringMonitor

    monitor = SteeringMonitor()
    signal = monitor.add_turns(
        session_id="session_123",
        new_turns=[{"speaker": "user", "text": "..."}],
        analyze_fn=tool_analyze,
        health_fn=tool_health_check,
    )
    if signal:
        print(signal["urgency"], signal["action"], signal["guidance"])

Patent Pending #63/923,592 — core engine is proprietary.
This module uses tool outputs as black boxes without modifying the engine.
"""

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_CONFIG = {
    "window_size": 30,
    "max_windows": 5,
    "session_ttl": 3600,
    "dhs_drop_threshold": 0.15,
    "reward_drop_threshold": 0.20,
    "closed_loop_persistence": 2,
    "min_turns_for_analysis": 3,
}

# Constellation → agent action mapping (mirrors server.py AGENT_ACTIONS)
AGENT_ACTIONS = {
    "CLOSED_LOOP": {
        "action": "explore_new_angle",
        "guidance": "Conversation is recycling. Try a different framing, introduce a new topic, or ask an unexpected question.",
    },
    "HIGH_SYMMETRY": {
        "action": "introduce_variation",
        "guidance": "Exchange is too predictable. Consider open-ended prompts or challenge an assumption.",
    },
    "PATTERN_BREAK": {
        "action": "support_integration",
        "guidance": "A structural shift just happened. Help process before moving on.",
    },
    "CONVERGENCE": {
        "action": "maintain_trajectory",
        "guidance": "Productive movement detected. Don't disrupt — keep the current approach.",
    },
    "SCATTERING": {
        "action": "provide_structure",
        "guidance": "Conversation is fragmenting. Offer grounding — summarize, simplify, or anchor to a concrete question.",
    },
    "REPEATED_DISRUPTION": {
        "action": "slow_down",
        "guidance": "Too many shifts too fast. Reduce pace and let each point land before moving on.",
    },
    "DIP_AND_RECOVERY": {
        "action": "acknowledge_shift",
        "guidance": "A disruption was followed by recovery. Note the resilience and build on it.",
    },
    "SURFACE_VARIATION": {
        "action": "go_deeper",
        "guidance": "New words, same dynamics. Push past surface change — ask why, not what.",
    },
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class WindowSnapshot:
    """Analysis snapshot for a single rolling window."""
    window_num: int
    turn_range: tuple  # (start_index, end_index)
    turn_count: int
    dhs: float
    loop_strength: float
    dominant_constellation: Optional[str]
    constellation_confidence: float
    reward: float
    analysis_hash: str
    timestamp: str


@dataclass
class SessionState:
    """Per-session state for steering monitor."""
    session_id: str
    buffer: List[Dict[str, Any]] = field(default_factory=list)
    windows: deque = field(default_factory=lambda: deque(maxlen=5))
    signal_history: List[Dict] = field(default_factory=list)
    total_turns_added: int = 0
    windows_analyzed: int = 0
    created_at: str = ""
    last_updated: str = ""
    ttl: int = 3600

    def is_expired(self) -> bool:
        if not self.last_updated:
            return False
        last = datetime.fromisoformat(self.last_updated.replace("Z", "+00:00"))
        elapsed = (datetime.utcnow() - last.replace(tzinfo=None)).total_seconds()
        return elapsed > self.ttl


# ---------------------------------------------------------------------------
# SteeringMonitor
# ---------------------------------------------------------------------------

class SteeringMonitor:
    """Monitors live conversations and emits steering signals."""

    def __init__(self, config: Optional[Dict] = None):
        self.config = {**DEFAULT_CONFIG, **(config or {})}
        self.sessions: Dict[str, SessionState] = {}
        self._lock = threading.Lock()
        self._cleanup_running = False

    def add_turns(
        self,
        session_id: str,
        new_turns: List[Dict[str, Any]],
        analyze_fn: Callable,
        health_fn: Optional[Callable] = None,
    ) -> Optional[Dict[str, Any]]:
        """Add turns to a session and run analysis if window is full.

        Args:
            session_id: Unique session identifier.
            new_turns: List of {speaker, text} dicts.
            analyze_fn: Callable that takes {"utterances": [...]} and returns analysis dict.
            health_fn: Optional callable for quick health check.

        Returns:
            SteeringSignal dict if thresholds triggered, None otherwise.
        """
        now = datetime.utcnow().isoformat() + "Z"

        with self._lock:
            if session_id not in self.sessions:
                self.sessions[session_id] = SessionState(
                    session_id=session_id,
                    created_at=now,
                    last_updated=now,
                    ttl=self.config["session_ttl"],
                    windows=deque(maxlen=self.config["max_windows"]),
                )
            session = self.sessions[session_id]

        # Append turns to buffer (outside lock for minimal contention)
        for i, turn in enumerate(new_turns):
            turn_with_index = dict(turn)
            turn_with_index["index"] = session.total_turns_added + i
            session.buffer.append(turn_with_index)

        session.total_turns_added += len(new_turns)
        session.last_updated = now

        window_size = self.config["window_size"]
        min_turns = self.config["min_turns_for_analysis"]

        # Check if we have enough turns for a window
        if len(session.buffer) < min_turns:
            return None

        # If buffer is large enough for a window, analyze it
        if len(session.buffer) >= window_size:
            # Extract current window
            window_turns = session.buffer[-window_size:]
            # Trim buffer to prevent unbounded growth (keep overlap for context)
            if len(session.buffer) > window_size * 2:
                session.buffer = session.buffer[-window_size:]
        elif session.windows_analyzed == 0 and len(session.buffer) >= min_turns:
            # First analysis: use whatever we have if >= min_turns
            window_turns = session.buffer[:]
        else:
            return None

        # Re-index turns for the analysis window
        indexed_turns = []
        for i, turn in enumerate(window_turns):
            indexed_turns.append({
                "speaker": turn.get("speaker", "unknown"),
                "text": turn.get("text", ""),
                "index": i,
            })

        # Run analysis
        try:
            analysis_result = analyze_fn({"utterances": indexed_turns})
        except Exception:
            return None

        # Extract key metrics
        dhs = analysis_result.get("dialectical_health", 0.5)
        loop_strength = analysis_result.get("loop_strength", 0.5)

        # Get dominant constellation
        constellations = analysis_result.get("constellations", [])
        dominant = None
        confidence = 0.0
        if constellations:
            top = max(constellations, key=lambda c: c.get("confidence", 0))
            dominant = top.get("detected")
            confidence = top.get("confidence", 0.0)

        # Compute reward signal
        reward = 0.5
        try:
            from feature_extraction import compute_reward
            reward = compute_reward(analysis_result)
        except (ImportError, Exception):
            pass

        # Create window snapshot
        start_idx = session.total_turns_added - len(window_turns)
        snapshot = WindowSnapshot(
            window_num=session.windows_analyzed,
            turn_range=(start_idx, session.total_turns_added),
            turn_count=len(window_turns),
            dhs=dhs,
            loop_strength=loop_strength,
            dominant_constellation=dominant,
            constellation_confidence=confidence,
            reward=reward,
            analysis_hash=analysis_result.get("result_hash", ""),
            timestamp=now,
        )

        # Get previous window for comparison
        previous = session.windows[-1] if session.windows else None

        with self._lock:
            session.windows.append(snapshot)
            session.windows_analyzed += 1

        # Evaluate thresholds
        signal = self._evaluate(snapshot, previous, session)

        if signal:
            with self._lock:
                session.signal_history.append(signal)
                # Keep last 20 signals
                if len(session.signal_history) > 20:
                    session.signal_history = session.signal_history[-20:]

        return signal

    def _evaluate(
        self,
        current: WindowSnapshot,
        previous: Optional[WindowSnapshot],
        session: SessionState,
    ) -> Optional[Dict[str, Any]]:
        """Evaluate thresholds and generate steering signal if triggered."""
        triggers = []
        urgency = "INFO"
        recommendations = []

        # --- HIGH urgency checks ---

        # DHS drop
        if previous and (previous.dhs - current.dhs) > self.config["dhs_drop_threshold"]:
            triggers.append("dhs_drop")
            urgency = "HIGH"
            recommendations.append(
                f"DHS dropped {previous.dhs:.3f} → {current.dhs:.3f} "
                f"(Δ{current.dhs - previous.dhs:+.3f}). Structural health declining."
            )

        # SCATTERING detection
        if current.dominant_constellation == "SCATTERING":
            triggers.append("scattering_detected")
            urgency = "HIGH"
            recommendations.append("Conversation is structurally fragmenting. Provide grounding.")

        # --- MEDIUM urgency checks ---

        # CLOSED_LOOP persistence
        persistence = self.config["closed_loop_persistence"]
        if len(session.windows) >= persistence:
            recent = list(session.windows)[-persistence:]
            if all(w.dominant_constellation == "CLOSED_LOOP" for w in recent):
                triggers.append("closed_loop_persistent")
                if urgency != "HIGH":
                    urgency = "MEDIUM"
                recommendations.append(
                    f"CLOSED_LOOP detected in {persistence} consecutive windows. "
                    "The conversation is cycling. Break the pattern."
                )

        # Reward drop
        if previous and (previous.reward - current.reward) > self.config["reward_drop_threshold"]:
            triggers.append("reward_drop")
            if urgency not in ("HIGH",):
                urgency = "MEDIUM"
            recommendations.append(
                f"Reward signal dropped {previous.reward:.3f} → {current.reward:.3f}. "
                "Quality of structural dynamics declining."
            )

        # --- INFO checks ---

        if current.dominant_constellation == "PATTERN_BREAK" and "dhs_drop" not in triggers:
            triggers.append("pattern_break")
            recommendations.append("Structural shift detected. Support integration before moving on.")

        if current.dominant_constellation == "CONVERGENCE":
            triggers.append("convergence")
            recommendations.append("Productive convergence detected. Maintain current trajectory.")

        if current.dominant_constellation == "SURFACE_VARIATION" and not triggers:
            triggers.append("surface_variation")
            recommendations.append("New content but unchanged dynamics. Push deeper.")

        # --- Build signal ---

        if not triggers:
            return None

        # Get action from constellation
        constellation = current.dominant_constellation or "SURFACE_VARIATION"
        agent_info = AGENT_ACTIONS.get(constellation, AGENT_ACTIONS["SURFACE_VARIATION"])

        signal = {
            "action": agent_info["action"],
            "guidance": agent_info["guidance"],
            "urgency": urgency,
            "confidence": round(current.constellation_confidence, 3),
            "triggered_by": triggers,
            "dhs_current": round(current.dhs, 3),
            "dhs_previous": round(previous.dhs, 3) if previous else None,
            "dhs_delta": round(current.dhs - previous.dhs, 3) if previous else None,
            "reward_signal": round(current.reward, 4),
            "constellation": constellation,
            "window_number": current.window_num,
            "recommendations": recommendations,
            "timestamp": current.timestamp,
        }

        return signal

    def get_session_status(self, session_id: str) -> Dict[str, Any]:
        """Return current session state and statistics."""
        with self._lock:
            session = self.sessions.get(session_id)

        if not session:
            return {"exists": False, "session_id": session_id}

        windows_data = []
        for w in session.windows:
            windows_data.append({
                "window_num": w.window_num,
                "turn_range": w.turn_range,
                "dhs": round(w.dhs, 3),
                "loop_strength": round(w.loop_strength, 3),
                "constellation": w.dominant_constellation,
                "reward": round(w.reward, 4),
                "timestamp": w.timestamp,
            })

        # DHS trajectory
        dhs_values = [w.dhs for w in session.windows]
        dhs_trend = "stable"
        if len(dhs_values) >= 2:
            delta = dhs_values[-1] - dhs_values[0]
            if delta > 0.05:
                dhs_trend = "improving"
            elif delta < -0.05:
                dhs_trend = "declining"

        return {
            "exists": True,
            "session_id": session_id,
            "total_turns": session.total_turns_added,
            "buffer_size": len(session.buffer),
            "windows_analyzed": session.windows_analyzed,
            "window_history": windows_data,
            "dhs_trend": dhs_trend,
            "recent_signals": session.signal_history[-5:],
            "created_at": session.created_at,
            "last_updated": session.last_updated,
        }

    def clear_session(self, session_id: str) -> bool:
        """Remove a session. Returns True if session existed."""
        with self._lock:
            if session_id in self.sessions:
                del self.sessions[session_id]
                return True
            return False

    def expire_old_sessions(self) -> int:
        """Remove expired sessions. Returns count of removed sessions."""
        with self._lock:
            expired = [sid for sid, s in self.sessions.items() if s.is_expired()]
            for sid in expired:
                del self.sessions[sid]
            return len(expired)

    def list_sessions(self) -> List[Dict[str, Any]]:
        """Return summary of all active sessions."""
        with self._lock:
            return [
                {
                    "session_id": s.session_id,
                    "total_turns": s.total_turns_added,
                    "windows_analyzed": s.windows_analyzed,
                    "last_updated": s.last_updated,
                    "latest_dhs": round(s.windows[-1].dhs, 3) if s.windows else None,
                    "latest_constellation": s.windows[-1].dominant_constellation if s.windows else None,
                }
                for s in self.sessions.values()
            ]

    @property
    def active_session_count(self) -> int:
        return len(self.sessions)


# ---------------------------------------------------------------------------
# Background cleanup thread
# ---------------------------------------------------------------------------

_cleanup_thread_started = False
_cleanup_lock = threading.Lock()


def start_cleanup_thread(monitor: SteeringMonitor, interval: int = 300):
    """Start a daemon thread that periodically cleans expired sessions."""
    global _cleanup_thread_started

    with _cleanup_lock:
        if _cleanup_thread_started:
            return
        _cleanup_thread_started = True

    def _loop():
        while True:
            time.sleep(interval)
            try:
                monitor.expire_old_sessions()
            except Exception:
                pass

    t = threading.Thread(target=_loop, daemon=True, name="renoun-steering-cleanup")
    t.start()
