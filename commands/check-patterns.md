# /check-patterns

Quick structural health check — DHS and dominant constellation only.

## Core Functionality

Lightweight triage using the `renoun_health_check` MCP tool. Accepts the same input formats as /analyze but returns only essential metrics. Use for fast "is this conversation healthy?" checks.

## Expected Outputs

Surface-level only:
- Dialectical Health Score with assessment (excellent/healthy/below_baseline/distressed)
- Dominant constellation pattern with agent action
- Loop strength
- One-line structural summary

If DHS < 0.45, add a warning flag and suggest running /analyze for the full breakdown. Do not offer additional analysis unless the user asks.
