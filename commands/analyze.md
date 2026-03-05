# /analyze

Run the ReNoUn 17-channel structural analysis on a conversation, transcript, or any turn-based data.

## Core Functionality

Accepts conversation data in any format — pasted text with "Speaker: text" lines, JSON arrays of `{speaker, text}` objects, or file paths to JSON/CSV transcripts. Parses the input into utterances and runs the `renoun_analyze` MCP tool.

**Optional weighting:** Include `weights` (per-turn floats 0.0-1.0), `tags` (from pre-tagging), or `weighting_mode` (weight/exclude/segment) to control how much each turn contributes.

## Expected Outputs

Present results at the depth matching the user's intent:

**Surface** (quick checks): DHS score, dominant constellation, loop strength, one-line summary.

**Standard** (most requests): Surface plus top constellations with confidence, Re/No/Un aggregates, key novelty peaks with turn numbers, 2-3 structural observations, and agent action for each pattern.

**Deep** (full analysis): Standard plus complete 17-channel breakdown table, all constellations with channel legends, sequence analysis, and full recommendations.

## Key Requirements

Minimum 3 turns required. 10+ recommended for reliable channel values. 20+ for reliable constellation detection. After presenting results, offer to save for longitudinal tracking or compare with another session. If DHS < 0.45, flag structural concerns.
