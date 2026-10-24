from __future__ import annotations

import re
from typing import Any
from uuid import uuid4

from ..backend_client import BackendClient, make_backend_client

_SERVER_COMMAND = re.compile(
    r"\b(?P<action>restart|reboot|fix|repair)\s+(?:the\s+)?server\s+(?P<server>[\w-]+)", re.I
)
_NUMBER_WORDS = {"one": "100", "two": "200", "three": "300", "hundred": "100"}


async def respond(
    device_id: str,
    text: str,
    *,
    authorization_signature: str = "",
    lang: str = "en-US",
    backend: BackendClient | None = None,
) -> dict[str, Any]:
    """Parse the two pilot commands and delegate every decision to the MCP backend."""
    if "help" in text.lower():
        return {
            "text": "Try saying restart server one hundred, or fix server two hundred.",
            "lang": lang, "priority": "task", "earcon": "task",
        }
    match = _SERVER_COMMAND.search(text)
    if match is None:
        return {
            "text": "I can only restart or fix a server. Please say the server number.",
            "lang": lang, "priority": "task", "earcon": "error",
        }
    if not authorization_signature:
        return {
            "text": "Your session has expired. Please authenticate your voice again.",
            "lang": lang, "priority": "task", "earcon": "error", "reauthenticate": True,
        }
    action = "restart" if match.group("action").lower() in {"restart", "reboot"} else "fix"
    raw_server = match.group("server").upper()
    server_id = (
        raw_server
        if raw_server.startswith("SRV-")
        else f"SRV-{_NUMBER_WORDS.get(raw_server.lower(), raw_server)}"
    )
    result = await (backend or make_backend_client()).call(
        "execute_task",
        task=f"server.{action}",
        request_id=f"gateway-{device_id}-{uuid4()}",
        authorization_signature=authorization_signature,
        server_id=server_id,
    )
    return {
        "text": str(result.get("spoken_message") or "The task could not be completed."),
        "lang": lang,
        "priority": "task",
        "earcon": "success" if result.get("authorized") else "error",
        "reauthenticate": result.get("code") in {
            "AUTHENTICATION_REQUIRED", "AUTHENTICATION_EXPIRED", "AUTHORIZATION_SIGNATURE_INVALID"
        },
    }
