from __future__ import annotations

from typing import Any


async def respond(device_id: str, text: str, *, lang: str = "en-US") -> dict[str, Any]:
    """Turn one transcribed utterance into the reply the earpiece should speak.

    Placeholder for the intent parser and backend handlers described under
    "Gateway dialogue" in docs/CONTRACT.md; it keeps the speech round trip
    testable end to end until they land.
    """
    if "help" in text.lower():
        reply = "Try: what's the status of my servers, or start server one hundred."
    else:
        reply = f"I heard: {text}."
    return {"text": reply, "lang": lang, "priority": "task", "earcon": "task"}
