from __future__ import annotations

import asyncio
import base64
import binascii
import itertools
import logging
import mimetypes
import os
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from ..config import project_root
from ..runtime import RuntimeServices, build_runtime
from .commands import parse_command
from .guidance import Guide
from .sessions import SESSION_TTL_SECONDS, Session, SessionStore
from .tasks import TaskService

logger = logging.getLogger(__name__)

MAX_AUDIO_BASE64_CHARS = 3_000_000  # the backend's own limit for one authentication clip

HELP_MESSAGE = (
    "I can restart a server or fix a server. Say, for example, restart server one hundred."
)
NOT_AUTHENTICATED_MESSAGE = "Please authenticate with your voice first."
VOICE_REFUSED_MESSAGE = "You are not registered."
UNCLEAR_AUDIO_MESSAGE = "I couldn't hear you clearly. Please try again."
EXPIRED_MESSAGE = "Your session has expired. Please authenticate again."


LOOPBACK_HOSTS = ("127.0.0.1", "::1", "localhost")
MAX_ENROLLMENT_CLIPS = 5
MAX_NAME_LENGTH = 60


def clean_name(raw: str) -> str | None:
    """A spoken name made safe to store and read aloud, or None if it isn't a plausible name."""
    name = " ".join(raw.split())
    if not 1 <= len(name) <= MAX_NAME_LENGTH or not name[0].isalpha():
        return None
    if not all(char.isalpha() or char in " .'-" for char in name):
        return None
    return name


def create_app(
    runtime: RuntimeServices | None = None,
    *,
    session_ttl_seconds: float = SESSION_TTL_SECONDS,
    frontend_dir=None,
    allow_enrollment: bool = False,
    enrollment_hosts: tuple[str, ...] = LOOPBACK_HOSTS,
    guide: Guide | None = None,
) -> FastAPI:
    """Build the voice gateway.

    Protocol (see docs/CONTRACT.md): the earpiece opens `/ws/{device_id}`, sends
    `voice_auth` once with a recorded WAV, then `utterance` text with the returned
    `session_id`. The session is cleared `session_ttl_seconds` after authentication.

    `allow_enrollment` is a demo convenience, off by default: it lets a browser on one of
    `enrollment_hosts` (this computer) record a voice profile for the device's operator.
    Production enrollment stays local-only (`luma-enroll-voice`).

    `guide` turns on the overheat scenario (see guidance.py): a spoken alert shortly after a
    worker is inside, then voice-only directions to the rack.
    """
    runtime = runtime or build_runtime()
    tasks = TaskService(runtime.database)
    connections: dict[str, WebSocket] = {}
    event_ids = itertools.count(1)

    def say(
        text: str,
        *,
        lang: str = "en-US",
        priority: str = "task",
        earcon: str = "task",
        from_id: str = "assistant",
    ) -> dict[str, Any]:
        return {
            "type": "say",
            "id": f"evt_{next(event_ids)}",
            "text": text,
            "priority": priority,
            "earcon": earcon,
            "lang": lang,
            "from": from_id,
        }

    async def expire(session: Session) -> None:
        """Tell the worker's earpiece that their session was cleared."""
        websocket = connections.get(session.device_id)
        logger.info("session expired for %s", session.operator_id)
        if guide is not None:
            guide.forget(session.id)
        if websocket is None:
            return
        try:
            await websocket.send_json({"type": "session_expired", "session_id": session.id})
            await websocket.send_json(say(EXPIRED_MESSAGE, priority="warning", earcon="warn"))
        except Exception:  # the socket may have closed at the same moment
            logger.debug("could not notify %s of expiry", session.device_id, exc_info=True)

    sessions = SessionStore(session_ttl_seconds, on_expire=expire)

    app = FastAPI(title="Luma voice gateway")
    app.state.runtime = runtime
    app.state.sessions = sessions
    app.state.tasks = tasks

    background: set[asyncio.Task] = set()

    async def send_alert(device_id: str, session_id: str, delay: float) -> bool:
        """Speak the overheat alert to a signed-in worker responsible for that server."""
        await asyncio.sleep(delay)
        session = sessions.get(session_id)
        websocket = connections.get(device_id)
        if guide is None or session is None or websocket is None:
            return False
        if guide.server_id not in session.servers:
            return False  # not this worker's server
        text = guide.alert(session.id, device_id)
        if text is None:
            return False
        logger.info("overheat alert for %s on %s", session.operator_id, guide.server_id)
        await websocket.send_json(say(text, priority="warning", earcon="warn"))
        return True

    def schedule_alert(device_id: str, delay: float) -> None:
        session = sessions.for_device(device_id)
        if guide is None or session is None:
            return
        task = asyncio.get_running_loop().create_task(send_alert(device_id, session.id, delay))
        background.add(task)
        task.add_done_callback(background.discard)

    @app.post("/api/scenario/overheat")
    async def trigger_overheat() -> dict[str, Any]:
        """Developer trigger: alert every signed-in, connected worker right now."""
        if guide is None:
            return {"ok": False, "reason": "the overheat scenario is not enabled"}
        alerted = [
            device_id
            for device_id in list(connections)
            if (session := sessions.for_device(device_id)) is not None
            and await send_alert(device_id, session.id, 0)
        ]
        return {"ok": True, "alerted": alerted}

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return {"ok": True, "active_sessions": sessions.active_count()}

    @app.get("/api/servers")
    async def servers() -> dict[str, Any]:
        return {"servers": tasks.list_servers()}

    async def authenticate(device_id: str, message: dict[str, Any]) -> dict[str, Any]:
        audio_b64 = str(message.get("audio_wav_base64") or "")
        voice = runtime.voice
        if len(audio_b64) > MAX_AUDIO_BASE64_CHARS:
            result = voice.reject_invalid_audio(
                device_id, "That audio recording was too large. Please try a shorter recording."
            )
        else:
            try:
                audio = base64.b64decode(audio_b64, validate=True)
            except (binascii.Error, ValueError):
                audio = b""
            if audio:
                # Speaker verification is CPU-bound; keep the event loop responsive.
                result = await asyncio.to_thread(voice.authenticate, device_id, audio)
            else:
                result = voice.reject_invalid_audio(
                    device_id, "I couldn't read that audio recording. Please try again."
                )

        if not result.authenticated:
            return {
                "type": "auth_result",
                "authenticated": False,
                "code": result.code,
                # Whatever the reason (wrong voice, not enrolled, unknown device) the worker hears
                # the same thing; `code` says why, for logs and debugging.
                "spoken_message": (
                    UNCLEAR_AUDIO_MESSAGE
                    if result.code == "INVALID_AUDIO"
                    else VOICE_REFUSED_MESSAGE
                ),
                "similarity_score": result.similarity_score,
            }

        operator_id = str(result.operator_id)
        organization_id = str(result.organization_id)
        with runtime.database.connect() as connection:
            row = connection.execute(
                "SELECT name FROM operators WHERE id = ?", (operator_id,)
            ).fetchone()
        name = str(row["name"]) if row else operator_id
        # Scopes come from the backend's signed token claims, not from a client-supplied role.
        scopes = str(voice.verify_token(str(result.authentication_token))["scope"]).split()
        servers = tasks.permissions_for(operator_id, organization_id)
        session = sessions.create(
            operator_id=operator_id,
            name=name,
            device_id=device_id,
            organization_id=organization_id,
            role=str(result.role),
            scopes=scopes,
            servers=servers,
        )
        return {
            "type": "auth_result",
            "authenticated": True,
            "code": result.code,
            "spoken_message": f"{name} is authenticated.",
            "similarity_score": result.similarity_score,
            "session_id": session.id,
            "expires_in": sessions.ttl_seconds,
            "operator": {"id": operator_id, "name": name, "role": session.role},
            "role": session.role,
            "permissions": {"scopes": scopes, "servers": servers},
        }

    async def enroll(
        device_id: str, websocket: WebSocket, message: dict[str, Any]
    ) -> dict[str, Any]:
        def refuse(code: str, text: str) -> dict[str, Any]:
            return {
                "type": "enroll_result",
                "enrolled": False,
                "code": code,
                "spoken_message": text,
            }

        if not allow_enrollment:
            return refuse("ENROLLMENT_DISABLED", "Voice enrollment from the browser is turned off.")
        host = websocket.client.host if websocket.client else ""
        if host not in enrollment_hosts:
            return refuse(
                "ENROLLMENT_NOT_ALLOWED",
                "Voice enrollment is only allowed on the gateway computer.",
            )
        clips = message.get("clips")
        if not isinstance(clips, list) or not 1 <= len(clips) <= MAX_ENROLLMENT_CLIPS:
            return refuse("INVALID_AUDIO", "Please record your voice samples again.")
        try:
            samples = [
                base64.b64decode(str(clip)[:MAX_AUDIO_BASE64_CHARS], validate=True)
                for clip in clips
            ]
        except (binascii.Error, ValueError):
            return refuse("INVALID_AUDIO", "I couldn't read those recordings. Please try again.")
        new_name = None
        if message.get("name") is not None:
            new_name = clean_name(str(message["name"]))
            if new_name is None:
                return refuse(
                    "INVALID_NAME", "I couldn't use that name. Please say your name again."
                )
        with runtime.database.connect() as connection:
            row = connection.execute(
                """
                SELECT operators.id, operators.name FROM datacenter_devices
                JOIN operators ON operators.id = datacenter_devices.operator_id
                WHERE datacenter_devices.id = ? AND datacenter_devices.trusted = 1
                """,
                (device_id,),
            ).fetchone()
        if row is None:
            return refuse("DEVICE_NOT_AUTHORIZED", "This device is not authorized for enrollment.")
        result = await asyncio.to_thread(runtime.voice.enroll, row["id"], samples)
        logger.info("browser enrollment for %s: %s", row["id"], result.code)
        name = str(row["name"])
        if result.enrolled and new_name and new_name != name:
            # The name is only changed once the voice itself has been enrolled.
            with runtime.database.transaction() as connection:
                connection.execute(
                    "UPDATE operators SET name = ? WHERE id = ?", (new_name, row["id"])
                )
            logger.info("operator %s is now named %s", row["id"], new_name)
            name = new_name
        return {
            "type": "enroll_result",
            "enrolled": result.enrolled,
            "code": result.code,
            "operator": {"id": row["id"], "name": name},
            "spoken_message": (
                f"{name}, you are enrolled." if result.enrolled else result.spoken_message
            ),
        }

    def handle_utterance(device_id: str, message: dict[str, Any]) -> dict[str, Any]:
        text = str(message.get("text", "")).strip()
        session = sessions.get(message.get("session_id"))
        if session is None or session.device_id != device_id:
            return say(NOT_AUTHENTICATED_MESSAGE, priority="warning", earcon="error")
        command = parse_command(text)
        if command is None:
            reply = guide.reply(session.id, text) if guide is not None else None
            return say(reply or HELP_MESSAGE)
        result = tasks.execute(session, command)
        logger.info(
            "%s %s %s -> %s", session.operator_id, command.task, command.server_id, result.code
        )
        if result.allowed and guide is not None:
            finished = guide.resolved(session.id, result.server_id or "")
            if finished:
                return say(finished, earcon="success")
        return say(
            result.spoken_message,
            earcon="success" if result.allowed else "error",
            priority="task" if result.allowed else "warning",
        )

    @app.websocket("/ws/{device_id}")
    async def earpiece(websocket: WebSocket, device_id: str) -> None:
        await websocket.accept()
        connections[device_id] = websocket
        await websocket.send_json({"type": "hello", "device_id": device_id})
        if guide is not None:
            # A worker who is already signed in has just reached the command page.
            schedule_alert(device_id, guide.alert_delay)
        try:
            while True:
                message = await websocket.receive_json()
                kind = message.get("type")
                if kind == "voice_auth":
                    await websocket.send_json(await authenticate(device_id, message))
                elif kind == "voice_enroll":
                    await websocket.send_json(await enroll(device_id, websocket, message))
                elif kind == "utterance" and str(message.get("text", "")).strip():
                    logger.info("heard %s: %s", device_id, message["text"])
                    await websocket.send_json(handle_utterance(device_id, message))
        except WebSocketDisconnect:
            pass
        finally:
            # A reconnect may already have replaced this socket.
            if connections.get(device_id) is websocket:
                del connections[device_id]

    # Windows registries often map .js to text/plain, which browsers refuse for ES modules.
    mimetypes.add_type("text/javascript", ".js")
    # Mounted last so the API and WebSocket routes take precedence.
    app.mount(
        "/",
        StaticFiles(directory=frontend_dir or project_root() / "frontend", html=True),
        name="frontend",
    )
    return app


def main() -> None:
    import uvicorn

    try:
        from dotenv import load_dotenv
    except ImportError:
        pass
    else:
        load_dotenv()
    logging.basicConfig(level=logging.INFO)
    ttl = float(os.environ.get("LUMA_SESSION_TTL_SECONDS", SESSION_TTL_SECONDS))
    guide = None
    if os.environ.get("LUMA_SCENARIO") == "overheat":
        guide = Guide(alert_delay=float(os.environ.get("LUMA_SCENARIO_ALERT_DELAY", "8")))
    uvicorn.run(
        create_app(
            session_ttl_seconds=ttl,
            allow_enrollment=os.environ.get("LUMA_ALLOW_BROWSER_ENROLL") == "1",
            guide=guide,
        ),
        host=os.environ.get("LUMA_GATEWAY_HOST", "0.0.0.0"),
        port=int(os.environ.get("LUMA_GATEWAY_PORT", "8080")),
    )


if __name__ == "__main__":
    main()
