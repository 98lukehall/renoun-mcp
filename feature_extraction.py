#!/usr/bin/env python3
"""
ReNoUn ML Feature Extraction — Convert structural analysis into ML-ready feature vectors.

Transforms ReNoUn's 17-channel output into numpy arrays suitable for:
- Feeding into ML models as structural features alongside semantic embeddings
- Training data quality scoring (filter corpora by dialectical health)
- RLHF reward signal computation
- Real-time inference steering (detect stuck patterns, trigger strategy shifts)
- Labeling assistance (surface structurally significant moments in large datasets)

Usage:
    from feature_extraction import extract_features, extract_turn_features, extract_batch

    # Session-level features (1 vector per conversation)
    features = extract_features(renoun_output)
    # features.vector -> np.array of shape (N,)
    # features.names  -> list of feature names

    # Turn-level features (1 vector per turn)
    turn_features = extract_turn_features(renoun_output)
    # turn_features.matrix -> np.array of shape (turns, M)

    # Batch processing
    batch = extract_batch([output1, output2, ...])
    # batch.matrix -> np.array of shape (sessions, N)

Patent Pending #63/923,592 — core engine is proprietary.
"""

import json
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple

try:
    import numpy as np
except ImportError:
    np = None  # Graceful fallback for environments without numpy


# ---------------------------------------------------------------------------
# Feature name constants
# ---------------------------------------------------------------------------

CHANNEL_NAMES = [
    "Re1_lexical", "Re2_syntactic", "Re3_rhythmic", "Re4_turn_taking", "Re5_self_interruption",
    "No1_lexical", "No2_syntactic", "No3_rhythmic", "No4_turn_taking", "No5_self_interruption", "No6_vocabulary_rarity",
    "Un1_lexical", "Un2_syntactic", "Un3_rhythmic", "Un4_interactional", "Un5_anaphoric", "Un6_structural_symmetry",
]

AGGREGATE_NAMES = [
    "recurrence_agg", "novelty_agg", "unity_agg",
]

HEALTH_NAMES = [
    "dhs", "loop_strength",
]

CONSTELLATION_NAMES = [
    "constellation_CLOSED_LOOP", "constellation_HIGH_SYMMETRY", "constellation_PATTERN_BREAK",
    "constellation_CONVERGENCE", "constellation_SCATTERING", "constellation_REPEATED_DISRUPTION",
    "constellation_DIP_AND_RECOVERY", "constellation_SURFACE_VARIATION",
]

UNITY_METRIC_NAMES = [
    "inter_harmony", "inter_alignment", "inter_tension", "inter_reflection_bonus",
]

NOVELTY_STAT_NAMES = [
    "novelty_max", "novelty_mean", "novelty_std", "novelty_peak_position",
    "novelty_count_above_03", "novelty_count_above_05",
    "has_breakthrough",
]

WEIGHTED_NAMES = [
    "weighted_dhs", "avg_weight", "effective_turn_ratio", "divergence_count",
]

META_NAMES = [
    "turn_count", "speaker_count",
]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class SessionFeatures:
    """Feature vector for a single conversation session."""
    vector: Any  # np.ndarray or list
    names: List[str]
    session_id: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def dim(self) -> int:
        return len(self.names)

    def to_dict(self) -> Dict[str, float]:
        """Return {feature_name: value} dict."""
        v = self.vector if isinstance(self.vector, list) else self.vector.tolist()
        return dict(zip(self.names, v))

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


@dataclass
class TurnFeatures:
    """Feature matrix for per-turn analysis."""
    matrix: Any  # np.ndarray or list of lists, shape (turns, features)
    names: List[str]
    turn_count: int = 0

    def to_dicts(self) -> List[Dict[str, float]]:
        """Return list of {feature_name: value} dicts, one per turn."""
        rows = self.matrix if isinstance(self.matrix, list) else self.matrix.tolist()
        return [dict(zip(self.names, row)) for row in rows]


@dataclass
class BatchFeatures:
    """Feature matrix for multiple sessions."""
    matrix: Any  # np.ndarray or list of lists, shape (sessions, features)
    names: List[str]
    session_ids: List[str] = field(default_factory=list)

    def to_dicts(self) -> List[Dict[str, float]]:
        rows = self.matrix if isinstance(self.matrix, list) else self.matrix.tolist()
        return [dict(zip(self.names, row)) for row in rows]


# ---------------------------------------------------------------------------
# Channel extraction
# ---------------------------------------------------------------------------

def _extract_channels(channels: Dict[str, Any]) -> List[float]:
    """Extract 17 channel values in canonical order."""
    rec = channels.get("recurrence", {})
    nov = channels.get("novelty", {})
    uni = channels.get("unity", {})

    return [
        rec.get("Re1_lexical", 0.0),
        rec.get("Re2_syntactic", 0.0),
        rec.get("Re3_rhythmic", 0.0),
        rec.get("Re4_turn_taking", 0.0),
        rec.get("Re5_self_interruption", 0.0),
        nov.get("No1_lexical", 0.0),
        nov.get("No2_syntactic", 0.0),
        nov.get("No3_rhythmic", 0.0),
        nov.get("No4_turn_taking", 0.0),
        nov.get("No5_self_interruption", 0.0),
        nov.get("No6_vocabulary_rarity", 0.0),
        uni.get("Un1_lexical", 0.0),
        uni.get("Un2_syntactic", 0.0),
        uni.get("Un3_rhythmic", 0.0),
        uni.get("Un4_interactional", 0.0),
        uni.get("Un5_anaphoric", 0.0),
        uni.get("Un6_structural_symmetry", 0.0),
    ]


def _extract_aggregates(channels: Dict[str, Any]) -> List[float]:
    """Extract 3 aggregate scores."""
    return [
        channels.get("recurrence", {}).get("aggregate", 0.0),
        channels.get("novelty", {}).get("aggregate", 0.0),
        channels.get("unity", {}).get("aggregate", 0.0),
    ]


def _extract_constellations(constellations: List[Dict]) -> List[float]:
    """One-hot-ish encoding: confidence score for each constellation type, 0 if not detected."""
    all_types = [
        "CLOSED_LOOP", "HIGH_SYMMETRY", "PATTERN_BREAK", "CONVERGENCE",
        "SCATTERING", "REPEATED_DISRUPTION", "DIP_AND_RECOVERY", "SURFACE_VARIATION",
    ]
    detected = {c.get("detected", ""): c.get("confidence", 0.0) for c in constellations}
    return [detected.get(t, 0.0) for t in all_types]


def _extract_unity_metrics(unity_metrics: Dict[str, Any]) -> List[float]:
    """Extract inter-speaker dynamics."""
    inter = unity_metrics.get("inter_speaker", {})
    return [
        inter.get("harmony", 0.0),
        inter.get("alignment", 0.0),
        inter.get("tension", 0.0),
        inter.get("reflection_bonus", 0.0),
    ]


def _extract_novelty_stats(novelty_items: List[Dict]) -> List[float]:
    """Compute distributional statistics from novelty items."""
    if not novelty_items:
        return [0.0, 0.0, 0.0, 0.0, 0, 0, 0.0]

    scores = [item.get("score", 0.0) for item in novelty_items]
    max_score = max(scores)
    mean_score = sum(scores) / len(scores)

    # Standard deviation
    variance = sum((s - mean_score) ** 2 for s in scores) / len(scores)
    std_score = variance ** 0.5

    # Peak position (normalized 0-1, where in the conversation the max novelty occurs)
    max_idx = max(range(len(novelty_items)), key=lambda i: novelty_items[i].get("score", 0.0))
    peak_item = novelty_items[max_idx]
    peak_turn = peak_item.get("index", 0)
    total_turns = max(item.get("index", 0) for item in novelty_items) + 1
    peak_position = peak_turn / max(total_turns - 1, 1) if total_turns > 1 else 0.0

    # Count of high-novelty turns
    above_03 = sum(1 for s in scores if s > 0.3)
    above_05 = sum(1 for s in scores if s > 0.5)

    # Breakthrough detection
    has_breakthrough = 1.0 if any(item.get("score", 0) > 0.7 for item in novelty_items) else 0.0

    return [max_score, mean_score, std_score, peak_position, float(above_03), float(above_05), has_breakthrough]


def _extract_weighted(output: Dict[str, Any]) -> List[float]:
    """Extract weighted analysis features if present."""
    weighting = output.get("weighting", {})
    if not weighting or not weighting.get("weights_applied"):
        return [0.0, 1.0, 1.0, 0.0]  # defaults: no weighted DHS, full weight, all turns, no divergences

    total = weighting.get("total_turns", 1)
    effective = weighting.get("effective_turns", total)

    return [
        weighting.get("weighted_dhs", output.get("dialectical_health", 0.0)),
        weighting.get("avg_weight", 1.0),
        effective / max(total, 1),
        float(len(weighting.get("divergences", []))),
    ]


def _extract_meta(output: Dict[str, Any]) -> List[float]:
    """Extract metadata features."""
    meta = output.get("_meta", {})
    return [
        float(meta.get("turn_count", len(output.get("novelty_items", [])))),
        float(len(meta.get("speakers", []))),
    ]


# ---------------------------------------------------------------------------
# Public API — Session-level features
# ---------------------------------------------------------------------------

def extract_features(
    output: Dict[str, Any],
    include_channels: bool = True,
    include_aggregates: bool = True,
    include_constellations: bool = True,
    include_unity: bool = True,
    include_novelty_stats: bool = True,
    include_weighted: bool = True,
    include_meta: bool = True,
    session_id: str = "",
) -> SessionFeatures:
    """Extract a flat feature vector from a ReNoUn analysis output.

    Args:
        output: Dict from renoun_analyze (the full JSON response).
        include_*: Toggle feature groups on/off.
        session_id: Optional identifier for this session.

    Returns:
        SessionFeatures with .vector (np.array or list) and .names (list of str).
    """
    values = []
    names = []

    # Health scores (always included)
    values.extend([output.get("dialectical_health", 0.0), output.get("loop_strength", 0.0)])
    names.extend(HEALTH_NAMES)

    if include_channels:
        values.extend(_extract_channels(output.get("channels", {})))
        names.extend(CHANNEL_NAMES)

    if include_aggregates:
        values.extend(_extract_aggregates(output.get("channels", {})))
        names.extend(AGGREGATE_NAMES)

    if include_constellations:
        values.extend(_extract_constellations(output.get("constellations", [])))
        names.extend(CONSTELLATION_NAMES)

    if include_unity:
        values.extend(_extract_unity_metrics(output.get("unity_metrics", {})))
        names.extend(UNITY_METRIC_NAMES)

    if include_novelty_stats:
        values.extend(_extract_novelty_stats(output.get("novelty_items", [])))
        names.extend(NOVELTY_STAT_NAMES)

    if include_weighted:
        values.extend(_extract_weighted(output))
        names.extend(WEIGHTED_NAMES)

    if include_meta:
        values.extend(_extract_meta(output))
        names.extend(META_NAMES)

    vec = np.array(values, dtype=np.float32) if np else values

    return SessionFeatures(
        vector=vec,
        names=names,
        session_id=session_id,
        metadata={
            "result_hash": output.get("result_hash", ""),
            "engine_version": output.get("engine", {}).get("version", ""),
        },
    )


# ---------------------------------------------------------------------------
# Public API — Turn-level features
# ---------------------------------------------------------------------------

TURN_FEATURE_NAMES = [
    "novelty_score", "linear_score", "global_score", "self_insight_score",
    "divergence", "lexical", "sentiment", "length", "emergence", "new_word_ratio",
    "is_early_turn", "turn_position",
]


def extract_turn_features(output: Dict[str, Any]) -> TurnFeatures:
    """Extract per-turn feature vectors from novelty items.

    Returns:
        TurnFeatures with .matrix (np.array of shape (turns, features)) and .names.
    """
    novelty_items = output.get("novelty_items", [])
    meta = output.get("_meta", {})
    total_turns = meta.get("turn_count", len(novelty_items))

    # Sort by index to get chronological order
    sorted_items = sorted(novelty_items, key=lambda x: x.get("index", 0))

    rows = []
    for item in sorted_items:
        components = item.get("components", {})
        idx = item.get("index", 0)
        rows.append([
            item.get("score", 0.0),
            item.get("linear_score", 0.0),
            item.get("global_score", 0.0),
            item.get("self_insight_score", 0.0),
            components.get("divergence", 0.0),
            components.get("lexical", 0.0),
            components.get("sentiment", 0.0),
            components.get("length", 0.0),
            components.get("emergence", 0.0),
            components.get("new_word_ratio", 0.0),
            1.0 if item.get("is_early_turn", False) else 0.0,
            idx / max(total_turns - 1, 1) if total_turns > 1 else 0.0,
        ])

    matrix = np.array(rows, dtype=np.float32) if np and rows else rows

    return TurnFeatures(
        matrix=matrix,
        names=TURN_FEATURE_NAMES,
        turn_count=len(rows),
    )


# ---------------------------------------------------------------------------
# Public API — Batch processing
# ---------------------------------------------------------------------------

def extract_batch(
    outputs: List[Dict[str, Any]],
    session_ids: Optional[List[str]] = None,
    **kwargs,
) -> BatchFeatures:
    """Extract feature vectors from multiple sessions.

    Args:
        outputs: List of renoun_analyze output dicts.
        session_ids: Optional list of session identifiers.
        **kwargs: Passed to extract_features.

    Returns:
        BatchFeatures with .matrix (np.array of shape (sessions, features)).
    """
    ids = session_ids or [f"session_{i}" for i in range(len(outputs))]
    features_list = [extract_features(o, session_id=sid, **kwargs) for o, sid in zip(outputs, ids)]

    if not features_list:
        return BatchFeatures(matrix=[], names=[], session_ids=[])

    names = features_list[0].names
    rows = [f.vector.tolist() if hasattr(f.vector, 'tolist') else f.vector for f in features_list]
    matrix = np.array(rows, dtype=np.float32) if np else rows

    return BatchFeatures(matrix=matrix, names=names, session_ids=ids)


# ---------------------------------------------------------------------------
# Public API — RLHF reward signal
# ---------------------------------------------------------------------------

def compute_reward(
    output: Dict[str, Any],
    weights: Optional[Dict[str, float]] = None,
) -> float:
    """Compute a scalar reward signal from ReNoUn analysis for RLHF.

    Default weighting emphasizes:
    - Dialectical health (structural health is primary signal)
    - Novelty emergence (genuine new synthesis, not just variation)
    - Anti-loop (penalize stuck patterns)
    - Coherence (novelty without unity is chaos)

    Args:
        output: Dict from renoun_analyze.
        weights: Optional custom weights for reward components.
            Keys: "dhs", "novelty", "anti_loop", "unity", "emergence", "anti_surface"

    Returns:
        Float reward signal in [0.0, 1.0].
    """
    w = {
        "dhs": 0.30,
        "novelty": 0.15,
        "anti_loop": 0.15,
        "unity": 0.15,
        "emergence": 0.15,
        "anti_surface": 0.10,
    }
    if weights:
        w.update(weights)

    # Normalize weights
    total_w = sum(w.values())
    w = {k: v / total_w for k, v in w.items()}

    channels = output.get("channels", {})
    constellations = output.get("constellations", [])
    novelty_items = output.get("novelty_items", [])

    # Component scores
    dhs = output.get("dialectical_health", 0.5)

    novelty_agg = channels.get("novelty", {}).get("aggregate", 0.0)
    unity_agg = channels.get("unity", {}).get("aggregate", 0.0)
    loop = output.get("loop_strength", 0.5)
    anti_loop = 1.0 - loop

    # Emergence: proportion of high-novelty turns (score > 0.4)
    if novelty_items:
        scores = [item.get("score", 0.0) for item in novelty_items]
        emergence = sum(1 for s in scores if s > 0.4) / len(scores)
    else:
        emergence = 0.0

    # Anti-surface: penalize SURFACE_VARIATION constellation
    surface_penalty = 0.0
    for c in constellations:
        if c.get("detected") == "SURFACE_VARIATION":
            surface_penalty = c.get("confidence", 0.0)
    anti_surface = 1.0 - surface_penalty

    # Compute weighted reward
    reward = (
        w["dhs"] * dhs
        + w["novelty"] * novelty_agg
        + w["anti_loop"] * anti_loop
        + w["unity"] * unity_agg
        + w["emergence"] * emergence
        + w["anti_surface"] * anti_surface
    )

    return max(0.0, min(1.0, round(reward, 4)))


def compute_reward_components(output: Dict[str, Any]) -> Dict[str, float]:
    """Return individual reward components for debugging/analysis.

    Returns a dict with each component score (0-1) and the final composite reward.
    """
    channels = output.get("channels", {})
    constellations = output.get("constellations", [])
    novelty_items = output.get("novelty_items", [])

    dhs = output.get("dialectical_health", 0.5)
    novelty_agg = channels.get("novelty", {}).get("aggregate", 0.0)
    unity_agg = channels.get("unity", {}).get("aggregate", 0.0)
    loop = output.get("loop_strength", 0.5)

    if novelty_items:
        scores = [item.get("score", 0.0) for item in novelty_items]
        emergence = sum(1 for s in scores if s > 0.4) / len(scores)
    else:
        emergence = 0.0

    surface_confidence = 0.0
    for c in constellations:
        if c.get("detected") == "SURFACE_VARIATION":
            surface_confidence = c.get("confidence", 0.0)

    return {
        "dhs": round(dhs, 4),
        "novelty": round(novelty_agg, 4),
        "anti_loop": round(1.0 - loop, 4),
        "unity": round(unity_agg, 4),
        "emergence": round(emergence, 4),
        "anti_surface": round(1.0 - surface_confidence, 4),
        "composite_reward": compute_reward(output),
    }


# ---------------------------------------------------------------------------
# Public API — Training data quality scoring
# ---------------------------------------------------------------------------

def score_training_quality(output: Dict[str, Any]) -> Dict[str, Any]:
    """Score a conversation's quality as training data.

    Returns quality tier (gold/silver/bronze/reject) and reasoning.
    Useful for filtering corpora before model training.
    """
    dhs = output.get("dialectical_health", 0.0)
    loop = output.get("loop_strength", 0.0)
    novelty_items = output.get("novelty_items", [])
    constellations = output.get("constellations", [])
    channels = output.get("channels", {})

    novelty_agg = channels.get("novelty", {}).get("aggregate", 0.0)
    unity_agg = channels.get("unity", {}).get("aggregate", 0.0)

    # Count emergence signals
    high_novelty_count = sum(1 for item in novelty_items if item.get("score", 0) > 0.4)

    # Check for stuck patterns
    has_closed_loop = any(c.get("detected") == "CLOSED_LOOP" for c in constellations)
    has_scattering = any(c.get("detected") == "SCATTERING" for c in constellations)
    has_convergence = any(c.get("detected") == "CONVERGENCE" for c in constellations)

    # Scoring logic
    reasons = []

    if dhs >= 0.65 and not has_closed_loop and high_novelty_count >= 3 and unity_agg >= 0.4:
        tier = "gold"
        reasons.append("High DHS with genuine emergence and coherence")
        if has_convergence:
            reasons.append("Convergence pattern detected — productive resolution")
    elif dhs >= 0.50 and loop < 0.6 and novelty_agg > 0.3:
        tier = "silver"
        reasons.append("Healthy structural dynamics with moderate novelty")
        if has_closed_loop:
            reasons.append("Minor loop detected but not dominant")
    elif dhs >= 0.35 and not has_scattering:
        tier = "bronze"
        reasons.append("Below baseline but structurally intact")
        if loop > 0.6:
            reasons.append("Significant looping reduces training value")
    else:
        tier = "reject"
        if dhs < 0.35:
            reasons.append(f"DHS critically low ({dhs:.3f})")
        if has_scattering:
            reasons.append("Scattering pattern — structurally incoherent")
        if loop > 0.8:
            reasons.append("Extreme looping — no genuine progression")

    return {
        "tier": tier,
        "quality_score": compute_reward(output),
        "dhs": round(dhs, 3),
        "loop_strength": round(loop, 3),
        "emergence_count": high_novelty_count,
        "reasons": reasons,
    }


# ---------------------------------------------------------------------------
# CLI interface
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python3 feature_extraction.py <result.json> [--reward] [--quality] [--turns]")
        sys.exit(1)

    with open(sys.argv[1]) as f:
        data = json.load(f)

    flags = set(sys.argv[2:])

    if "--reward" in flags:
        components = compute_reward_components(data)
        print(json.dumps(components, indent=2))
    elif "--quality" in flags:
        quality = score_training_quality(data)
        print(json.dumps(quality, indent=2))
    elif "--turns" in flags:
        tf = extract_turn_features(data)
        for d in tf.to_dicts():
            print(json.dumps(d))
    else:
        sf = extract_features(data)
        print(f"Feature dimension: {sf.dim}")
        print(json.dumps(sf.to_dict(), indent=2))
