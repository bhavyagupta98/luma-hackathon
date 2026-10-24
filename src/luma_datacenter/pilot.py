from __future__ import annotations

import argparse
from pathlib import Path
from uuid import uuid4

from .models import ServerActionRequest
from .runtime import build_runtime


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run one backend-only voice-authenticated datacenter action"
    )
    parser.add_argument("--device", default="DC-D-100")
    parser.add_argument("--audio", required=True, type=Path)
    parser.add_argument("--server", default="SRV-100")
    parser.add_argument("--action", required=True, choices=("restart", "fix"))
    args = parser.parse_args()

    runtime = build_runtime()
    task = f"server.{args.action}"
    authentication = runtime.voice.authenticate(args.device, args.audio.read_bytes(), task)
    print(authentication.spoken_message)
    if not authentication.authenticated or authentication.authorization_signature is None:
        raise SystemExit(1)

    claims = runtime.voice.verify_token(authentication.authorization_signature)
    result = runtime.actions.execute(
        ServerActionRequest(
            request_id=str(uuid4()),
            operator_id=str(claims["sub"]),
            device_id=str(claims["device_id"]),
            organization_id=str(claims["organization_id"]),
            roles=tuple(str(value) for value in claims["roles"]),
            permissions=tuple(str(value) for value in claims["permissions"]),
            authorized_tasks=tuple(str(value) for value in claims["tasks"]),
            server_id=args.server,
            action=args.action,
            token_jti=str(claims["jti"]),
        )
    )
    print(result.spoken_message)
    raise SystemExit(0 if result.authorized else 1)


if __name__ == "__main__":
    main()
