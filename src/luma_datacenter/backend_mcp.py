from __future__ import annotations

import argparse
import base64
import binascii
from pathlib import Path
from typing import Any
from uuid import uuid4

from mcp.server import MCPServer

from .models import ServerActionRequest, UserRegistrationRequest
from .runtime import build_runtime
from .voice_embeddings import VoiceEmbedder
from .voice_tokens import VoiceTokenError, VoiceTokenSigner


def build_backend_server(
    path: str | Path | None = None,
    *,
    voice_embedder: VoiceEmbedder | None = None,
    voice_signer: VoiceTokenSigner | None = None,
) -> MCPServer:
    runtime = build_runtime(path, voice_embedder=voice_embedder, voice_signer=voice_signer)
    action_service = runtime.actions
    administration_service = runtime.administration
    voice_service = runtime.voice
    signer = runtime.signer
    mcp = MCPServer(
        "luma-datacenter-backend",
        version="0.3.0",
        instructions=(
            "Authenticate a datacenter operator's voice and control only seeded, simulated "
            "server power state. Speak spoken_message after every result."
        ),
    )

    @mcp.tool()
    def authenticate_voice(device_id: str = "", audio_base64: str = "") -> dict[str, Any]:
        """Verify an enrolled operator voice and issue a signed one-action token."""
        if len(audio_base64) > 3_000_000:
            return voice_service.reject_invalid_audio(
                device_id, "That audio recording was too large. Please try a shorter recording."
            ).to_dict()
        try:
            audio = base64.b64decode(audio_base64, validate=True)
        except (binascii.Error, ValueError):
            return voice_service.reject_invalid_audio(
                device_id, "I couldn't read that audio recording. Please try again."
            ).to_dict()
        return voice_service.authenticate(device_id, audio).to_dict()

    @mcp.tool()
    def execute_server_action(
        authentication_token: str = "",
        request_id: str | None = None,
        server_id: str = "",
        action: str = "",
    ) -> dict[str, Any]:
        """Start or stop one simulated server using a signed voice-authentication token."""
        resolved_request_id = request_id or f"generated-{uuid4()}"
        normalized_action = action.strip().lower()
        try:
            claims = voice_service.verify_token(authentication_token)
        except VoiceTokenError:
            return action_service.reject_unverified(
                resolved_request_id,
                server_id,
                normalized_action,
                "Your voice verification expired or was invalid. Please verify your voice again.",
            ).to_dict()
        return action_service.execute(
            ServerActionRequest(
                request_id=resolved_request_id,
                operator_id=str(claims["sub"]),
                device_id=str(claims["device_id"]),
                organization_id=str(claims["organization_id"]),
                scope=str(claims["scope"]),
                server_id=server_id,
                action=normalized_action,
                token_jti=str(claims["jti"]),
            )
        ).to_dict()

    @mcp.tool()
    def add_organization_user(
        authentication_token: str,
        request_id: str,
        organization_id: str,
        user_id: str,
        display_name: str,
        role: str,
        device_id: str,
        server_ids: list[str],
    ) -> dict[str, Any]:
        """Add an admin or operator using a fresh organization-admin voice token."""
        normalized_role = role.strip().lower()
        normalized_servers = tuple(dict.fromkeys(server_id.strip() for server_id in server_ids))
        try:
            claims = voice_service.verify_token(authentication_token)
        except VoiceTokenError:
            return administration_service.reject_unverified(
                request_id=request_id,
                organization_id=organization_id,
                user_id=user_id,
                display_name=display_name,
                role=normalized_role,
                device_id=device_id,
                server_ids=normalized_servers,
            ).to_dict()
        return administration_service.add_user(
            UserRegistrationRequest(
                request_id=request_id,
                actor_operator_id=str(claims["sub"]),
                actor_device_id=str(claims["device_id"]),
                actor_organization_id=str(claims["organization_id"]),
                actor_scope=str(claims["scope"]),
                token_jti=str(claims["jti"]),
                organization_id=organization_id,
                user_id=user_id,
                display_name=display_name,
                role=normalized_role,
                device_id=device_id,
                server_ids=normalized_servers,
            )
        ).to_dict()

    @mcp.tool()
    def verify_voice_authentication(authentication_token: str = "") -> dict[str, Any]:
        """Verify a backend-issued voice token without executing a server action."""
        try:
            claims = voice_service.verify_token(authentication_token)
        except VoiceTokenError:
            return {
                "authenticated": False,
                "code": "VOICE_TOKEN_INVALID",
                "spoken_message": (
                    "Your voice verification expired or was invalid. Please try again."
                ),
            }
        return {
            "authenticated": True,
            "code": "VOICE_TOKEN_VALID",
            "spoken_message": "Voice verification is valid.",
            "operator_id": claims["sub"],
            "device_id": claims["device_id"],
            "organization_id": claims["organization_id"],
            "role": claims["role"],
            "scope": claims["scope"],
            "expires_at": claims["exp"],
        }

    @mcp.tool()
    def list_server_action_events(limit: int = 50) -> dict[str, Any]:
        """List simulated server-control attempts for developers and auditors."""
        events = action_service.list_events(limit)
        return {"events": events, "count": len(events)}

    @mcp.tool()
    def list_voice_auth_events(limit: int = 50) -> dict[str, Any]:
        """List voice-authentication attempts for developers and auditors."""
        events = voice_service.list_events(limit)
        return {"events": events, "count": len(events)}

    @mcp.tool()
    def list_user_admin_events(limit: int = 50) -> dict[str, Any]:
        """List organization user-add attempts for developers and auditors."""
        events = administration_service.list_events(limit)
        return {"events": events, "count": len(events)}

    @mcp.tool()
    def describe_user_registration() -> dict[str, Any]:
        """Return every required field and the supported organization roles."""
        return {
            "required_fields": [
                "authentication_token",
                "request_id",
                "organization_id",
                "user_id",
                "display_name",
                "role",
                "device_id",
                "server_ids",
            ],
            "roles": ["org_admin", "operator"],
            "post_registration": (
                "The new user must record and enroll their own voice before signing in."
            ),
        }

    @mcp.tool()
    def describe_pilot() -> dict[str, Any]:
        """Describe the seeded datacenter pilot and its security boundary."""
        return {
            "operator_id": "OP-100",
            "device_id": "DC-D-100",
            "organization_id": "ORG-DEMO",
            "role": "org_admin",
            "start_target": {"server_id": "SRV-100", "initial_status": "stopped"},
            "stop_target": {"server_id": "SRV-200", "initial_status": "running"},
            "allowed_actions": ["start", "stop"],
            "model": voice_service.embedder.model_name,
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
