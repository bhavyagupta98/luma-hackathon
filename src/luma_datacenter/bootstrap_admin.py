from __future__ import annotations

import argparse
from pathlib import Path

from .administration import bootstrap_admin
from .runtime import build_runtime


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Locally bootstrap an organization and its first voice admin"
    )
    parser.add_argument("--organization-id", required=True)
    parser.add_argument("--organization-name", required=True)
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--device-id", required=True)
    parser.add_argument(
        "--audio",
        action="append",
        required=True,
        type=Path,
        help="A 1–15 second, 16-bit PCM WAV; repeat for multiple samples",
    )
    args = parser.parse_args()

    runtime = build_runtime()
    try:
        bootstrap_admin(
            runtime.database,
            organization_id=args.organization_id,
            organization_name=args.organization_name,
            user_id=args.user_id,
            display_name=args.name,
            device_id=args.device_id,
        )
    except ValueError as exc:
        parser.exit(1, f"Bootstrap failed: {exc}\n")

    enrollment = runtime.voice.enroll(
        args.user_id, [audio_path.read_bytes() for audio_path in args.audio]
    )
    print(
        f"Created organization {args.organization_id} and administrator {args.user_id}."
    )
    print(enrollment.spoken_message)
    raise SystemExit(0 if enrollment.enrolled else 1)


if __name__ == "__main__":
    main()
