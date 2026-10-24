from __future__ import annotations

import argparse
import json
from pathlib import Path

from .runtime import build_runtime


def main() -> None:
    parser = argparse.ArgumentParser(description="Enroll an operator's local voice profile")
    parser.add_argument(
        "--operator", required=True, help="Seeded operator ID, for example OP-100"
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--audio",
        action="append",
        type=Path,
        help="A 1–15 second, mono or stereo, 16-bit PCM WAV file; repeat for more samples",
    )
    source.add_argument(
        "--profile",
        type=Path,
        help="Browser enrollment JSON downloaded by auth.html?enroll=1",
    )
    args = parser.parse_args()

    service = build_runtime().voice
    if args.profile:
        profile = json.loads(args.profile.read_text())
        if profile.get("operator_id") != args.operator:
            parser.error("Profile operator_id does not match --operator")
        result = service.enroll_embedding(
            args.operator,
            [float(value) for value in profile.get("centroid", [])],
            str(profile.get("embedding_model") or ""),
        )
    else:
        samples = [path.read_bytes() for path in args.audio]
        result = service.enroll(args.operator, samples)
    print(result.spoken_message)
    raise SystemExit(0 if result.enrolled else 1)


if __name__ == "__main__":
    main()
