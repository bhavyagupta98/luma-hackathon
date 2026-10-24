from __future__ import annotations

import itertools
import logging
import mimetypes
import os
from typing import Any

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..backend_client import make_backend_client
from ..config import project_root
from ..runtime import build_runtime
from .dialogue import respond

logger = logging.getLogger(__name__)

app = FastAPI(title="Luma voice gateway")
connections: dict[str, WebSocket] = {}
_event_ids = itertools.count(1)
REGISTRATION_PASSPHRASE = "my voice is my badge authorize datacenter access"


class LocalVoiceRegistration(BaseModel):
    person: str
    transcript: str
    embedding: list[float]
    embedding_model: str


def _normalized_words(value: str) -> str:
    normalized = "".join(
        character if character.isalnum() else " " for character in value.lower()
    )
    return " ".join(normalized.split())


def say_message(
    text: str,
    *,
    lang: str = "en-US",
    priority: str = "task",
    earcon: str = "task",
    from_id: str = "assistant",
    reauthenticate: bool = False,
) -> dict[str, Any]:
    """Build a gateway -> earpiece `say` message (see docs/CONTRACT.md)."""
    message = {
        "type": "say",
        "id": f"evt_{next(_event_ids)}",
        "text": text,
        "priority": priority,
        "earcon": earcon,
        "lang": lang,
        "from": from_id,
    }
    if reauthenticate:
        message["reauthenticate"] = True
    return message


@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {"ok": True, "backend": os.environ.get("LUMA_GATEWAY_BACKEND", "mcp")}


@app.post("/api/local-register-voice")
async def local_register_voice(
    registration: LocalVoiceRegistration, request: Request
) -> dict[str, Any]:
    """Enroll exactly the two local demo administrators; never expose on a remote host."""
    if request.client is None or request.client.host not in {"127.0.0.1", "::1", "testclient"}:
        raise HTTPException(403, "Voice enrollment is available only from this laptop.")
    person = registration.person.strip().upper()
    if person not in {"AB", "BG"}:
        raise HTTPException(400, "Only AB and BG may be registered on this demo page.")
    if _normalized_words(registration.transcript) != REGISTRATION_PASSPHRASE:
        raise HTTPException(400, "The exact passphrase was not detected. Please try again.")
    if len(registration.embedding) != 512:
        raise HTTPException(400, "The voice embedding is invalid.")

    runtime = build_runtime()
    operator_id = "OP-100" if person == "AB" else "OP-BG"
    device_id = "DC-D-100" if person == "AB" else "DC-D-BG"
    with runtime.database.transaction() as connection:
        if person == "AB":
            connection.execute("UPDATE operators SET name='AB', active=1 WHERE id='OP-100'")
        else:
            connection.execute(
                "INSERT OR IGNORE INTO operators (id, name, active) VALUES (?, ?, 1)",
                (operator_id, person),
            )
            connection.execute(
                """INSERT OR REPLACE INTO organization_memberships
                   (organization_id, operator_id, role) VALUES ('ORG-DEMO', ?, 'org_admin')""",
                (operator_id,),
            )
            connection.execute(
                """INSERT OR REPLACE INTO datacenter_devices
                   (id, operator_id, trusted) VALUES (?, ?, 1)""",
                (device_id, operator_id),
            )
            connection.execute(
                "INSERT OR REPLACE INTO device_contexts VALUES (?, 'ORG-DEMO')", (device_id,)
            )
            for server_id in ("SRV-100", "SRV-200", "SRV-300"):
                connection.execute(
                    "INSERT OR REPLACE INTO server_assignments VALUES (?, ?, 1)",
                    (operator_id, server_id),
                )
    result = runtime.voice.enroll_embedding(
        operator_id, registration.embedding, registration.embedding_model
    )
    if not result.enrolled:
        raise HTTPException(400, result.spoken_message)
    return {
        "registered": True,
        "person": person,
        "operator_id": operator_id,
        "device_id": device_id,
        "role": "org_admin",
        "spoken_message": f"{person} voice registration complete.",
    }


@app.websocket("/ws/{device_id}")
async def earpiece(websocket: WebSocket, device_id: str) -> None:
    await websocket.accept()
    connections[device_id] = websocket
    await websocket.send_json({"type": "hello", "device_id": device_id, "operator": None})
    try:
        while True:
            message = await websocket.receive_json()
            if message.get("type") == "voice_auth":
                result = await make_backend_client().call(
                    "execute_task",
                    task="authenticate",
                    device_id=device_id,
                    voice_embedding=message.get("embedding") or [],
                    embedding_model=str(message.get("embedding_model") or ""),
                )
                authorization = result.get("authorization") or {}
                identity = result.get("identity") or {}
                await websocket.send_json(
                    {
                        "type": "auth_result",
                        "authenticated": bool(result.get("authorized")),
                        "code": result.get("code"),
                        "spoken_message": result.get("spoken_message"),
                        "operator": {
                            "id": identity.get("operator_id"),
                            "name": result.get("display_name") or identity.get("operator_id"),
                            "roles": authorization.get("roles", []),
                            "permissions": authorization.get("permissions", []),
                        } if result.get("authorized") else None,
                        "similarity_score": result.get("similarity_score"),
                        "authentication_token": authorization.get("signature"),
                        "expires_at": authorization.get("expires_at"),
                    }
                )
                continue
            if message.get("type") != "utterance":
                continue
            text = str(message.get("text", "")).strip()
            if not text:
                continue
            lang = str(message.get("lang") or "en-US")
            logger.info("heard %s: %s", device_id, text)
            try:
                reply = await respond(
                    device_id, text, lang=lang,
                    authorization_signature=str(message.get("authentication_token") or ""),
                )
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
