"""
ReNoUn API Configuration.

Reads from environment variables or ~/.renoun/config.json.
"""

import os
import json
from pathlib import Path

CONFIG_FILE = Path.home() / ".renoun" / "config.json"


def _load_file_config() -> dict:
    """Load config from file if it exists."""
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


_file_config = _load_file_config()

# API Server
API_HOST = os.environ.get("RENOUN_API_HOST", _file_config.get("api_host", "0.0.0.0"))
# Railway sets PORT; fallback to RENOUN_API_PORT or config file
API_PORT = int(os.environ.get("PORT", os.environ.get("RENOUN_API_PORT", _file_config.get("api_port", 8080))))

# CORS
CORS_ORIGINS = os.environ.get("RENOUN_CORS_ORIGINS", ",".join(_file_config.get("cors_origins", ["*"]))).split(",")

# API metadata
API_VERSION = "1.2.1"
API_TITLE = "ReNoUn Structural Analysis API"
API_DESCRIPTION = (
    "Structural observability for AI conversations. "
    "Detects loops, stuck states, breakthroughs, and convergence patterns "
    "across 17 channels without analyzing content."
)
