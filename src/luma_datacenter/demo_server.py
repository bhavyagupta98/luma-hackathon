from __future__ import annotations

import argparse
import tempfile
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .config import project_root
from .models import ServerActionRequest
from .runtime import build_runtime
from .voice_embeddings import VoiceEmbeddingError
from .voice_tokens import VoiceTokenSigner


class DemoAudioEmbedder:
    model_name = "demo-browser-embedding"

    def embed(self, audio: bytes) -> list[float]:
        raise VoiceEmbeddingError("The playback demo uses deterministic test embeddings.")


app = FastAPI(title="Luma narrated test demo")


def _action(runtime, claims: dict[str, Any], task: str, server_id: str):
    return runtime.actions.execute(
        ServerActionRequest(
            request_id=f"demo-{uuid4()}",
            operator_id=str(claims["sub"]),
            device_id=str(claims["device_id"]),
            organization_id=str(claims["organization_id"]),
            roles=tuple(claims["roles"]),
            permissions=tuple(claims["permissions"]),
            authorized_tasks=tuple(claims["tasks"]),
            server_id=server_id,
            action=task.removeprefix("server."),
            token_jti=str(claims["jti"]),
        )
    )


def build_demo_cases(directory: Path) -> list[dict[str, Any]]:
    database_path = directory / f"demo-{uuid4()}.db"
    signer = VoiceTokenSigner(
        directory / f"demo-{uuid4()}.pem",
        issuer="luma-demo",
        audience="luma-demo-backend",
        ttl_seconds=60,
    )
    runtime = build_runtime(
        database_path, voice_embedder=DemoAudioEmbedder(), voice_signer=signer
    )
    with runtime.database.transaction() as connection:
        connection.execute("UPDATE operators SET name='AB' WHERE id='OP-100'")
        connection.execute("INSERT INTO operators VALUES ('OP-BG', 'BG', 1)")
        connection.execute(
            """INSERT INTO organization_memberships
               VALUES ('ORG-DEMO', 'OP-BG', 'org_admin', CURRENT_TIMESTAMP)"""
        )
        connection.execute("INSERT INTO datacenter_devices VALUES ('DC-D-BG', 'OP-BG', 1)")
        connection.execute("INSERT INTO device_contexts VALUES ('DC-D-BG', 'ORG-DEMO')")
        connection.execute("INSERT INTO server_assignments VALUES ('OP-BG', 'SRV-300', 1)")
    runtime.voice.enroll_embedding(
        "OP-100", [1.0, 0.0, 0.0], DemoAudioEmbedder.model_name, threshold=0.8
    )
    runtime.voice.enroll_embedding(
        "OP-BG", [0.0, 1.0, 0.0], DemoAudioEmbedder.model_name, threshold=0.8
    )
    authentication = runtime.voice.authenticate_embedding(
        "DC-D-100", [0.99, 0.01, 0.0], DemoAudioEmbedder.model_name
    )
    if not authentication.authorization_signature:
        raise RuntimeError(authentication.spoken_message)
    claims = runtime.voice.verify_token(authentication.authorization_signature)
    bg_authentication = runtime.voice.authenticate_embedding(
        "DC-D-BG", [0.01, 0.99, 0.0], DemoAudioEmbedder.model_name
    )
    if not bg_authentication.authorization_signature:
        raise RuntimeError(bg_authentication.spoken_message)
    bg_claims = runtime.voice.verify_token(bg_authentication.authorization_signature)
    restart = _action(runtime, claims, "server.restart", "SRV-100")
    fix = _action(runtime, claims, "server.fix", "SRV-200")
    bg_restart = _action(runtime, bg_claims, "server.restart", "SRV-300")
    blocked = _action(runtime, bg_claims, "server.restart", "SRV-100")
    wrong_voice = runtime.voice.authenticate_embedding(
        "DC-D-100", [0.0, 0.0, 1.0], DemoAudioEmbedder.model_name
    )
    expired = runtime.actions.reject_unverified(
        f"demo-expired-{uuid4()}", "SRV-100", "restart",
        "Your session expired. Please authenticate your voice again.",
    )
    return [
        {
            "title": "Voice authentication succeeds",
            "worker": "My voice is my badge. Authorize datacenter access.",
            "system": authentication.spoken_message,
            "speaker": "AB",
            "code": authentication.code,
            "passed": authentication.authenticated,
        },
        {
            "title": "Assigned server restart succeeds",
            "worker": "Restart server one hundred.",
            "system": restart.spoken_message,
            "speaker": "AB",
            "code": restart.code,
            "passed": restart.authorized,
        },
        {
            "title": "Assigned server repair succeeds",
            "worker": "Fix server two hundred.",
            "system": fix.spoken_message,
            "speaker": "AB",
            "code": fix.code,
            "passed": fix.authorized,
        },
        {
            "title": "Second enrolled voice authenticates",
            "worker": "My voice is my badge. Authorize datacenter access.",
            "system": bg_authentication.spoken_message,
            "speaker": "BG",
            "code": bg_authentication.code,
            "passed": bg_authentication.authenticated,
        },
        {
            "title": "BG restarts an assigned server",
            "worker": "Restart server three hundred.",
            "system": bg_restart.spoken_message,
            "speaker": "BG",
            "code": bg_restart.code,
            "passed": bg_restart.authorized,
        },
        {
            "title": "BG is refused on AB's server",
            "worker": "Restart server one hundred.",
            "system": blocked.spoken_message,
            "speaker": "BG",
            "code": blocked.code,
            "passed": not blocked.authorized,
        },
        {
            "title": "Different voice is refused",
            "worker": "Authenticate my voice.",
            "system": wrong_voice.spoken_message,
            "speaker": "UNKNOWN",
            "code": wrong_voice.code,
            "passed": not wrong_voice.authenticated,
        },
        {
            "title": "Expired session is refused",
            "worker": "Sixty seconds later, restart server one hundred.",
            "system": expired.spoken_message,
            "speaker": "AB",
            "code": expired.code,
            "passed": not expired.authorized,
        },
    ]


_demo_directory = tempfile.TemporaryDirectory(prefix="luma-narrated-demo-")


@app.post("/api/demo/cases")
async def demo_cases() -> dict[str, Any]:
    cases = build_demo_cases(Path(_demo_directory.name))
    return {"cases": cases, "count": len(cases), "all_passed": all(c["passed"] for c in cases)}


app.mount("/", StaticFiles(directory=project_root() / "frontend", html=True), name="frontend")


def main() -> None:
    import uvicorn

    parser = argparse.ArgumentParser(description="Run the narrated Luma test-case demo")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8090)
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
