from __future__ import annotations

import itertools
import logging
import mimetypes
import os
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from ..config import project_root
from .dialogue import respond

logger = logging.getLogger(__name__)

app = FastAPI(title="Luma voice gateway")
connections: dict[str, WebSocket] = {}
_event_ids = itertools.count(1)


def say_message(
    text: str,
    *,
    lang: str = "en-US",
    priority: str = "task",
    earcon: str = "task",
    from_id: str = "assistant",
) -> dict[str, Any]:
    """Build a gateway -> earpiece `say` message (see docs/CONTRACT.md)."""
    return {
        "type": "say",
        "id": f"evt_{next(_event_ids)}",
        "text": text,
        "priority": priority,
        "earcon": earcon,
        "lang": lang,
        "from": from_id,
    }


@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {"ok": True, "backend": os.environ.get("LUMA_GATEWAY_BACKEND", "mcp")}


@app.websocket("/ws/{device_id}")
async def earpiece(websocket: WebSocket, device_id: str) -> None:
    await websocket.accept()
    connections[device_id] = websocket
    await websocket.send_json({"type": "hello", "device_id": device_id, "operator": None})
    try:
        while True:
            message = await websocket.receive_json()
            if message.get("type") != "utterance":
                continue
            text = str(message.get("text", "")).strip()
            if not text:
                continue
            lang = str(message.get("lang") or "en-US")
            logger.info("heard %s: %s", device_id, text)
            try:
                reply = await respond(device_id, text, lang=lang)
            except Exception:
                logger.exception("dialogue failed for %s", device_id)
                reply = {
                    "text": "Sorry, something went wrong. Please say that again.",
                    "lang": lang,
                    "earcon": "error",
                }
            await websocket.send_json(say_message(**reply))
    except WebSocketDisconnect:
        pass
    finally:
        # A reconnect may already have replaced this socket.
        if connections.get(device_id) is websocket:
            del connections[device_id]


# Windows registries often map .js to text/plain, which browsers refuse for ES modules.
mimetypes.add_type("text/javascript", ".js")
# Mounted last so the API and WebSocket routes take precedence.
app.mount("/", StaticFiles(directory=project_root() / "frontend", html=True), name="frontend")


def main() -> None:
    import uvicorn

    try:
        from dotenv import load_dotenv
    except ImportError:
        pass
    else:
        load_dotenv()
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(
        app,
        host=os.environ.get("LUMA_GATEWAY_HOST", "0.0.0.0"),
        port=int(os.environ.get("LUMA_GATEWAY_PORT", "8080")),
    )


if __name__ == "__main__":
    main()
