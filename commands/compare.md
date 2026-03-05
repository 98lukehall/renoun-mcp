# /compare

Compare structural patterns across two conversations to identify shifts, transitions, and health trends.

## Core Functionality

Accepts two conversations as pasted text, file paths, JSON arrays, or previously saved session names. Runs `renoun_compare` MCP tool with either raw utterances or pre-analyzed results.

**Two-session mode:** Returns DHS delta, constellation transitions, and top channel shifts between sessions.

**Multi-session mode:** When comparing stored sessions over time, shows DHS trajectory, constellation frequency distribution, and stability assessment.

## Expected Outputs

Health trajectory table with DHS, loop strength, and Re/No/Un deltas. Constellation transition (e.g., CLOSED_LOOP -> CONVERGENCE) with structural interpretation. Top 3 channel shifts by magnitude with direction. One-paragraph structural summary of what changed and why it matters.

## Key Requirements

Both inputs must have 3+ turns. If raw transcripts are provided, analysis runs automatically before comparison. Highlight whether changes represent genuine structural improvement or surface variation only.
