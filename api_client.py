"""
ReNoUn Remote API Client — Fallback engine for when core.py is not available locally.

When users install renoun-mcp via pip, they don't have the proprietary core.py engine.
This module provides a transparent wrapper that calls the hosted ReNoUn API instead,
so the MCP server works identically — users just need an API key.

Configuration (in order of priority):
    1. RENOUN_API_KEY and RENOUN_API_URL environment variables
    2. ~/.renoun/config.json with api_key and api_url fields

Patent Pending #63/923,592 — the core engine runs server-side only.
"""

import os
import json
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional

DEFAULT_API_URL = "https://web-production-817e2.up.railway.app"


def _load_config() -> dict:
    """Load config from ~/.renoun/config.json if it exists."""
    config_path = Path.home() / ".renoun" / "config.json"
    if config_path.exists():
        try:
            return json.loads(config_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def get_api_config() -> tuple[Optional[str], Optional[str]]:
    """Return (api_url, api_key) from env vars or config file.

    Returns (None, None) if no API key is configured.
    """
    # Environment variables take priority
    api_key = os.environ.get("RENOUN_API_KEY")
    api_url = os.environ.get("RENOUN_API_URL")

    # Fall back to config file
    if not api_key:
        config = _load_config()
        api_key = config.get("api_key")
        if not api_url:
            api_url = config.get("api_url")

    if not api_url:
        api_url = DEFAULT_API_URL

    return (api_url, api_key) if api_key else (None, None)


def is_api_configured() -> bool:
    """Check whether remote API fallback is available."""
    _, api_key = get_api_config()
    return api_key is not None


class APIError(Exception):
    """Raised when the remote API returns an error."""

    def __init__(self, status_code: int, message: str, error_type: str = "api_error"):
        self.status_code = status_code
        self.message = message
        self.error_type = error_type
        super().__init__(f"API error ({status_code}): {message}")


class RemoteAPIClient:
    """HTTP client for the hosted ReNoUn API.

    Uses only stdlib (urllib) to avoid adding dependencies to the pip package.
    """

    def __init__(self, api_url: Optional[str] = None, api_key: Optional[str] = None):
        if api_url and api_key:
            self.api_url = api_url.rstrip("/")
            self.api_key = api_key
        else:
            url, key = get_api_config()
            if not url or not key:
                raise ValueError(
                    "ReNoUn API not configured. Set RENOUN_API_KEY environment variable "
                    "or add api_key to ~/.renoun/config.json"
                )
            self.api_url = url.rstrip("/")
            self.api_key = key

    def _request(self, endpoint: str, payload: dict) -> dict:
        """Make an authenticated POST request to the API."""
        url = f"{self.api_url}{endpoint}"
        data = json.dumps(payload).encode("utf-8")

        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
                "User-Agent": "renoun-mcp-client/1.2.0",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            try:
                error_data = json.loads(body)
                if "detail" in error_data:
                    detail = error_data["detail"]
                    if isinstance(detail, dict) and "error" in detail:
                        err = detail["error"]
                        raise APIError(e.code, err.get("message", str(detail)), err.get("type", "api_error"))
                    raise APIError(e.code, str(detail))
                if "error" in error_data:
                    err = error_data["error"]
                    raise APIError(e.code, err.get("message", str(err)), err.get("type", "api_error"))
            except (json.JSONDecodeError, KeyError):
                pass
            raise APIError(e.code, body)
        except urllib.error.URLError as e:
            raise APIError(0, f"Cannot reach API at {self.api_url}: {e.reason}")

    def analyze(self, utterances: list[dict]) -> dict:
        """Call /v1/analyze — full 17-channel structural analysis."""
        return self._request("/v1/analyze", {"utterances": utterances})

    def health_check(self, utterances: list[dict]) -> dict:
        """Call /v1/health-check — fast structural triage."""
        return self._request("/v1/health-check", {"utterances": utterances})

    def compare(self, arguments: dict) -> dict:
        """Call /v1/compare — structural A/B test."""
        return self._request("/v1/compare", arguments)

    def pattern_query(self, action: str, arguments: dict) -> dict:
        """Call /v1/patterns/{action} — session history."""
        return self._request(f"/v1/patterns/{action}", arguments)

    def status(self) -> dict:
        """Check API availability (unauthenticated)."""
        url = f"{self.api_url}/v1/status"
        req = urllib.request.Request(url, headers={"User-Agent": "renoun-mcp-client/1.2.0"})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            return {"status": "unreachable", "error": str(e)}
