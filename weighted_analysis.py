#!/usr/bin/env python3
"""
ReNoUn Weighted Analysis Wrapper.

Sits between callers and engine.score() to apply optional per-turn weights.
The engine itself is never modified — weights are applied as pre/post-processing.

Three modes:
  - "weight":   Run engine on ALL turns, post-process DHS using weights
  - "exclude":  Remove low-weight turns before engine scoring
  - "segment":  Split into substantive/administrative groups, score each separately

Patent Pending #63/923,592 — core engine is proprietary.
This wrapper only processes inputs/outputs around it.
"""

from typing import Optional


def _extract_weights(
    weights: Optional[list[float]] = None,
    tags: Optional[list[dict]] = None,
    turn_count: int = 0,
) -> list[float]:
    """Resolve weights from explicit weights, tags, or uniform default.

    Returns a list of floats, one per turn.
    """
    if weights is not None:
        if len(weights) != turn_count:
            raise ValueError(
                f"Weight count ({len(weights)}) must match utterance count ({turn_count})"
            )
        return [max(0.0, min(1.0, w)) for w in weights]

    if tags is not None:
        if len(tags) != turn_count:
            raise ValueError(
                f"Tag count ({len(tags)}) must match utterance count ({turn_count})"
            )
        return [max(0.0, min(1.0, float(t.get("weight", 1.0)))) for t in tags]

    # Uniform weights — backwards compatible
    return [1.0] * turn_count


def _weighted_dhs(base_dhs: float, weights: list[float]) -> float:
    """Recompute DHS as a weighted score.

    Scales the base DHS toward 0.5 for low average weight (more administrative
    noise = less confident in the structural health reading).
    """
    if not weights:
        return base_dhs

    avg_weight = sum(weights) / len(weights)
    # Blend: at avg_weight=1.0, use full DHS. At avg_weight=0.0, use 0.5 (neutral).
    return base_dhs * avg_weight + 0.5 * (1.0 - avg_weight)


def _find_divergences(output: dict, weights: list[float]) -> list[dict]:
    """Find cases where structural signal disagrees with weight.

    E.g., high novelty on a low-weight turn (a "noise" turn caused a structural shift).
    """
    divergences = []
    novelty_items = output.get("novelty_items", [])

    for item in novelty_items:
        idx = item.get("index", -1)
        if 0 <= idx < len(weights):
            w = weights[idx]
            score = item.get("score", 0)
            if w < 0.4 and score > 0.5:
                divergences.append({
                    "index": idx,
                    "type": "high_novelty_low_weight",
                    "weight": round(w, 3),
                    "novelty_score": round(score, 3),
                    "note": "Structurally significant turn was tagged as low-substance. "
                            "The structural shift may be driven by format change, not content.",
                })
            elif w > 0.8 and score < 0.1:
                divergences.append({
                    "index": idx,
                    "type": "low_novelty_high_weight",
                    "weight": round(w, 3),
                    "novelty_score": round(score, 3),
                    "note": "Substantive turn had no structural impact. "
                            "Content may be important but structurally redundant.",
                })

    return divergences


def apply_weights(
    utterances: list[dict],
    weights: list[float],
    mode: str = "weight",
    threshold: float = 0.1,
) -> list[dict]:
    """Apply weights to utterances before engine scoring.

    Args:
        utterances: List of {speaker, text} dicts.
        weights: Per-turn weights (0.0-1.0).
        mode: "exclude" removes turns below threshold; "weight" and "segment" return
              utterances unchanged (processing happens elsewhere).
        threshold: Weight threshold for exclude mode.

    Returns:
        Modified utterance list (only different in "exclude" mode).
    """
    if mode == "exclude":
        filtered = []
        for i, (utt, w) in enumerate(zip(utterances, weights)):
            if w >= threshold:
                new_utt = dict(utt)
                new_utt["index"] = len(filtered)
                new_utt["_original_index"] = utt.get("index", i)
                filtered.append(new_utt)
        return filtered

    # "weight" and "segment" modes don't modify utterances for the main engine call
    return utterances


def weighted_analyze(
    utterances: list[dict],
    weights: Optional[list[float]] = None,
    tags: Optional[list[dict]] = None,
    mode: str = "weight",
    threshold: float = 0.1,
    engine=None,
) -> dict:
    """Full analysis with optional weighting.

    If weights provided: use them directly.
    If tags provided: extract weights from tags.
    If neither: uniform weights (backwards compatible, identical to unweighted).

    Args:
        utterances: Conversation turns.
        weights: Optional per-turn weights (0.0-1.0).
        tags: Optional per-turn tags from pre_tag() (weight extracted automatically).
        mode: "weight" (default), "exclude", or "segment".
        threshold: Weight cutoff for exclude/segment modes (default 0.1).
        engine: ReNoUnEngineV4 instance. If None, imports and creates one.

    Returns:
        Standard ReNoUn output dict with additional "weighting" section.
    """
    if engine is None:
        from server import create_engine
        engine = create_engine()

    resolved_weights = _extract_weights(weights, tags, len(utterances))

    # Check if all weights are uniform — skip weighting overhead
    is_uniform = all(w == 1.0 for w in resolved_weights)
    if is_uniform:
        result = engine.score(utterances)
        return result.to_dict()

    if mode == "exclude":
        return _analyze_exclude(utterances, resolved_weights, threshold, engine)
    elif mode == "segment":
        return _analyze_segment(utterances, resolved_weights, threshold, engine)
    else:
        return _analyze_weighted(utterances, resolved_weights, engine)


def _analyze_weighted(
    utterances: list[dict],
    weights: list[float],
    engine,
) -> dict:
    """Weight mode: run engine on all turns, post-process with weights."""
    result = engine.score(utterances)
    output = result.to_dict()

    effective_turns = sum(1 for w in weights if w > 0.5)
    excluded_indices = [i for i, w in enumerate(weights) if w < 0.1]

    output["weighting"] = {
        "mode": "weight",
        "weights_applied": True,
        "original_dhs": round(output.get("dialectical_health", 0.5), 3),
        "weighted_dhs": round(_weighted_dhs(output.get("dialectical_health", 0.5), weights), 3),
        "effective_turns": effective_turns,
        "total_turns": len(utterances),
        "excluded_indices": excluded_indices,
        "avg_weight": round(sum(weights) / len(weights), 3),
        "divergences": _find_divergences(output, weights),
    }

    # Replace top-level DHS with weighted version
    output["dialectical_health"] = output["weighting"]["weighted_dhs"]

    return output


def _analyze_exclude(
    utterances: list[dict],
    weights: list[float],
    threshold: float,
    engine,
) -> dict:
    """Exclude mode: remove low-weight turns, score remainder."""
    filtered = apply_weights(utterances, weights, mode="exclude", threshold=threshold)
    excluded_indices = [i for i, w in enumerate(weights) if w < threshold]

    if len(filtered) < 3:
        # Not enough turns after filtering — fall back to weighted mode
        output = _analyze_weighted(utterances, weights, engine)
        output["weighting"]["mode"] = "exclude_fallback"
        output["weighting"]["note"] = (
            f"Only {len(filtered)} turns remained after excluding weight < {threshold}. "
            "Fell back to weighted mode on all turns."
        )
        return output

    result = engine.score(filtered)
    output = result.to_dict()

    output["weighting"] = {
        "mode": "exclude",
        "weights_applied": True,
        "threshold": threshold,
        "original_turn_count": len(utterances),
        "analyzed_turn_count": len(filtered),
        "excluded_indices": excluded_indices,
        "excluded_turns": [
            {"index": i, "speaker": utterances[i].get("speaker", ""), "weight": round(weights[i], 3)}
            for i in excluded_indices
        ],
    }

    return output


def _analyze_segment(
    utterances: list[dict],
    weights: list[float],
    threshold: float,
    engine,
) -> dict:
    """Segment mode: analyze substantive and administrative turns separately."""
    substantive = []
    administrative = []

    for i, (utt, w) in enumerate(zip(utterances, weights)):
        entry = dict(utt)
        entry["_original_index"] = utt.get("index", i)
        if w >= 0.5:
            entry["index"] = len(substantive)
            substantive.append(entry)
        else:
            entry["index"] = len(administrative)
            administrative.append(entry)

    output = {
        "weighting": {
            "mode": "segment",
            "weights_applied": True,
            "substantive_count": len(substantive),
            "administrative_count": len(administrative),
            "threshold": 0.5,
        },
    }

    # Score substantive turns
    if len(substantive) >= 3:
        result_sub = engine.score(substantive)
        output["substantive"] = result_sub.to_dict()
        # Use substantive DHS as the primary score
        output["dialectical_health"] = output["substantive"]["dialectical_health"]
        output["loop_strength"] = output["substantive"]["loop_strength"]
    else:
        output["substantive"] = None
        output["weighting"]["note_substantive"] = (
            f"Only {len(substantive)} substantive turns — too few for separate analysis."
        )

    # Score administrative turns
    if len(administrative) >= 3:
        result_admin = engine.score(administrative)
        output["administrative"] = result_admin.to_dict()
    else:
        output["administrative"] = None
        output["weighting"]["note_administrative"] = (
            f"Only {len(administrative)} administrative turns — too few for separate analysis."
        )

    # Compute divergence between segments if both were analyzed
    if output.get("substantive") and output.get("administrative"):
        sub_dhs = output["substantive"]["dialectical_health"]
        admin_dhs = output["administrative"]["dialectical_health"]
        output["weighting"]["segment_comparison"] = {
            "substantive_dhs": round(sub_dhs, 3),
            "administrative_dhs": round(admin_dhs, 3),
            "dhs_delta": round(sub_dhs - admin_dhs, 3),
            "interpretation": (
                "Substantive turns are structurally healthier"
                if sub_dhs > admin_dhs + 0.1
                else "Administrative turns are structurally healthier"
                if admin_dhs > sub_dhs + 0.1
                else "Both segments have similar structural health"
            ),
        }

    # If neither segment had enough turns, fall back to full analysis
    if output.get("substantive") is None and output.get("administrative") is None:
        return _analyze_weighted(utterances, weights, engine)

    return output
