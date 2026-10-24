from __future__ import annotations

import argparse
import base64
import binascii
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from mcp.server import MCPServer

from .models import ServerActionRequest, UserRegistrationRequest
from .policy import AUTHENTICATION_TASK, FUNCTIONAL_TASKS, USER_ADD_TASK
from .runtime import build_runtime
from .voice_embeddings import VoiceEmbedder
from .voice_tokens import VoiceTokenError, VoiceTokenSigner

TaskName = Literal["authenticate", "server.start", "server.stop", "user.add"]


def build_backend_server(
    path: str | Path | None = None,
    *,
    voice_embedder: VoiceEmbedder | None = None,
    voice_signer: VoiceTokenSigner | None = None,
) -> MCPServer:
    runtime = build_runtime(path, voice_embedder=voice_embedder, voice_signer=voice_signer)
    actions = runtime.actions
    administration = runtime.administration
    voice = runtime.voice
    signer = runtime.signer
    mcp = MCPServer(
        "luma-datacenter-backend",
        version="0.4.0",
        instructions=(
            "Call execute_task. Authenticate voice for exactly one requested task, then pass "
            "the returned signature to that task. Always speak spoken_message."
        ),
    )

    def authenticate(device_id: str, audio_base64: str, requested_task: str) -> dict[str, Any]:
        if requested_task not in FUNCTIONAL_TASKS:
            result = voice.reject_request(
                device_id,
                "TASK_NOT_SUPPORTED",
                "I don't recognize the task you want to authorize.",
            )
        elif len(audio_base64) > 3_000_000:
            result = voice.reject_invalid_audio(
                device_id, "That audio recording was too large. Please try a shorter recording."
            )
        else:
            try:
                audio = base64.b64decode(audio_base64, validate=True)
            except (binascii.Error, ValueError):
                result = voice.reject_invalid_audio(
                    device_id, "I couldn't read that audio recording. Please try again."
                )
            else:
                result = voice.authenticate(device_id, audio, requested_task)

        authorization = None
        if result.authenticated:
            authorization = {
                "signature": result.authorization_signature,
                "roles": list(result.roles),
                "permissions": list(result.permissions),
                "tasks": list(result.tasks),
                "expires_at": result.expires_at,
            }
        return {
            "task": AUTHENTICATION_TASK,
            "authorized": result.authenticated,
            "code": result.code,
            "spoken_message": result.spoken_message,
            "authorization": authorization,
            "identity": {
                "operator_id": result.operator_id if result.authenticated else None,
                "device_id": result.device_id,
                "organization_id": result.organization_id if result.authenticated else None,
            },
        }

    def verified_claims(signature: str) -> dict[str, Any] | None:
        try:
            return voice.verify_token(signature)
        except VoiceTokenError:
            return None

    @mcp.tool()
    def execute_task(
        task: TaskName,
        request_id: str | None = None,
        requested_task: str = "",
        device_id: str = "",
        voice_audio_base64: str = "",
        authorization_signature: str = "",
        server_id: str = "",
        organization_id: str = "",
        user_id: str = "",
        display_name: str = "",
        role: str = "",
        user_device_id: str = "",
        server_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Authenticate voice or execute one signed datacenter task.

        Authentication needs device_id, voice_audio_base64, and requested_task.
        Server tasks need authorization_signature and server_id. User addition needs
        the signature and all organization, user, role, device, and server fields.
        """
        resolved_id = request_id or f"generated-{uuid4()}"
        if task == AUTHENTICATION_TASK:
            return authenticate(device_id, voice_audio_base64, requested_task)

        claims = verified_claims(authorization_signature)
        if claims is None:
            message = (
                "Your voice verification expired or was invalid. Please verify your voice again."
            )
            if task in {"server.start", "server.stop"}:
                result = actions.reject_unverified(
                    resolved_id, server_id, task.removeprefix("server."), message
                )
                return {
                    "task": task,
                    "request_id": result.request_id,
                    "authorized": False,
                    "code": result.code,
                    "spoken_message": result.spoken_message,
                    "data": {"server_id": result.server_id, "server_status": None},
                }
            result = administration.reject_unverified(
                request_id=resolved_id,
                organization_id=organization_id,
                user_id=user_id,
                display_name=display_name,
                role=role.strip().lower(),
                device_id=user_device_id,
                server_ids=tuple(server_ids or ()),
            )
            return {
                "task": USER_ADD_TASK,
                "request_id": result.request_id,
                "authorized": False,
                "code": result.code,
                "spoken_message": result.spoken_message,
                "data": {"user_id": result.user_id},
            }
        roles = tuple(str(value) for value in claims["roles"])
        permissions = tuple(str(value) for value in claims["permissions"])
        tasks = tuple(str(value) for value in claims["tasks"])

        if task in {"server.start", "server.stop"}:
            action = task.removeprefix("server.")
            result = actions.execute(
                ServerActionRequest(
                    request_id=resolved_id,
                    operator_id=str(claims["sub"]),
                    device_id=str(claims["device_id"]),
                    organization_id=str(claims["organization_id"]),
                    roles=roles,
                    permissions=permissions,
                    authorized_tasks=tasks,
                    server_id=server_id,
                    action=action,
                    token_jti=str(claims["jti"]),
                )
            )
            return {
                "task": task,
                "request_id": result.request_id,
                "authorized": result.authorized,
                "code": result.code,
                "spoken_message": result.spoken_message,
                "data": {"server_id": result.server_id, "server_status": result.server_status},
            }

        normalized_servers = tuple(
            dict.fromkeys(value.strip() for value in (server_ids or []) if value.strip())
        )
        result = administration.add_user(
            UserRegistrationRequest(
                request_id=resolved_id,
                actor_operator_id=str(claims["sub"]),
                actor_device_id=str(claims["device_id"]),
                actor_organization_id=str(claims["organization_id"]),
                actor_roles=roles,
                actor_permissions=permissions,
                actor_authorized_tasks=tasks,
                token_jti=str(claims["jti"]),
                organization_id=organization_id,
                user_id=user_id,
                display_name=display_name,
                role=role.strip().lower(),
                device_id=user_device_id,
                server_ids=normalized_servers,
            )
        )
        return {
            "task": USER_ADD_TASK,
            "request_id": result.request_id,
            "authorized": result.approved,
            "code": result.code,
            "spoken_message": result.spoken_message,
            "data": {
                "organization_id": result.organization_id,
                "user_id": result.user_id,
                "role": result.role,
                "device_id": result.device_id,
            },
        }

    @mcp.tool()
    def verify_authorization_signature(authorization_signature: str = "") -> dict[str, Any]:
        """Verify a backend signature without consuming it or executing a task."""
        try:
            claims = voice.verify_token(authorization_signature)
        except VoiceTokenError:
            return {
                "authorized": False,
                "code": "AUTHORIZATION_SIGNATURE_INVALID",
                "spoken_message": "Your authorization expired or was invalid. Please try again.",
            }
        return {
            "authorized": True,
            "code": "AUTHORIZATION_SIGNATURE_VALID",
            "spoken_message": "Your authorization is valid.",
            "operator_id": claims["sub"],
            "device_id": claims["device_id"],
            "organization_id": claims["organization_id"],
            "roles": claims["roles"],
            "permissions": claims["permissions"],
            "tasks": claims["tasks"],
            "expires_at": claims["exp"],
        }

    @mcp.tool()
    def list_server_action_events(limit: int = 50) -> dict[str, Any]:
        """List simulated server-control attempts for developers and auditors."""
        events = actions.list_events(limit)
        return {"events": events, "count": len(events)}

    @mcp.tool()
    def list_voice_auth_events(limit: int = 50) -> dict[str, Any]:
        """List voice-authentication attempts for developers and auditors."""
        events = voice.list_events(limit)
        return {"events": events, "count": len(events)}

    @mcp.tool()
    def list_user_admin_events(limit: int = 50) -> dict[str, Any]:
        """List organization user-add attempts for developers and auditors."""
        events = administration.list_events(limit)
        return {"events": events, "count": len(events)}

    @mcp.tool()
    def describe_task_contract() -> dict[str, Any]:
        """Describe task inputs and signed role/permission/task authorization."""
        return {
            "flow": [
                "Authenticate for exactly one requested_task.",
                "Speak spoken_message and stop on refusal.",
                "Use authorization.signature once for that same functional task.",
            ],
            "tasks": {
                "authenticate": ["device_id", "voice_audio_base64", "requested_task"],
                "server.start": ["authorization_signature", "request_id", "server_id"],
                "server.stop": ["authorization_signature", "request_id", "server_id"],
                "user.add": [
                    "authorization_signature",
                    "request_id",
                    "organization_id",
                    "user_id",
                    "display_name",
                    "role",
                    "user_device_id",
                    "server_ids",
                ],
            },
            "authorization": {"roles": [], "permissions": [], "tasks": []},
            "roles": ["org_admin", "operator"],
        }

    @mcp.tool()
    def describe_pilot() -> dict[str, Any]:
        """Describe the seeded datacenter pilot and security boundary."""
        return {
            "operator_id": "OP-100",
            "device_id": "DC-D-100",
            "organization_id": "ORG-DEMO",
            "role": "org_admin",
            "start_target": {"server_id": "SRV-100", "initial_status": "stopped"},
            "stop_target": {"server_id": "SRV-200", "initial_status": "running"},
            "tasks": sorted(FUNCTIONAL_TASKS),
            "model": voice.embedder.model_name,
            "token_algorithm": "EdDSA",
            "token_key_id": signer.key_id,
            "token_ttl_seconds": signer.ttl_seconds,
            "limitations": [
                "Every server and action is simulated in local SQLite.",
                "Speaker verification is not production-grade identity proof.",
                "Replay and synthetic-voice detection are not implemented.",
            ],
        }

    return mcp


server = build_backend_server()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the datacenter backend MCP server")
    parser.add_argument("--transport", choices=("stdio", "streamable-http"), default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    try:
        if args.transport == "stdio":
            server.run()
        else:
            server.run(
                transport="streamable-http",
                host=args.host,
                port=args.port,
                json_response=True,
                stateless_http=True,
            )
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
