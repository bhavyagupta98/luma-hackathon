from __future__ import annotations

import os
from pathlib import Path


def database_path() -> Path:
    """Return the configured SQLite path, defaulting to local runtime data."""
    return Path(os.environ.get("LUMA_DATABASE_PATH", "data/luma_datacenter.db"))


def backend_mcp_url() -> str:
    """Return the backend Streamable HTTP endpoint used by the voice gateway."""
    return os.environ.get("LUMA_BACKEND_MCP_URL", "http://127.0.0.1:8000/mcp")


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def voice_model_path() -> Path:
    return Path(
        os.environ.get(
            "LUMA_VOICE_MODEL_PATH",
            str(project_root() / "models" / "speechbrain-spkrec-ecapa-voxceleb"),
        )
    )


def voice_signing_key_path() -> Path:
    return Path(os.environ.get("LUMA_VOICE_SIGNING_KEY_PATH", "data/voice-auth-ed25519.pem"))


def voice_token_issuer() -> str:
    return os.environ.get("LUMA_VOICE_TOKEN_ISSUER", "luma-voice-auth")


def voice_token_audience() -> str:
    return os.environ.get("LUMA_VOICE_TOKEN_AUDIENCE", "luma-datacenter-backend")


def voice_token_ttl_seconds() -> int:
    return int(os.environ.get("LUMA_VOICE_TOKEN_TTL_SECONDS", "60"))


def voice_match_threshold() -> float:
    return float(os.environ.get("LUMA_VOICE_MATCH_THRESHOLD", "0.25"))
