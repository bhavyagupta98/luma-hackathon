from __future__ import annotations

import argparse
from pathlib import Path

from .runtime import build_runtime


def main() -> None:
    parser = argparse.ArgumentParser(description="Enroll an operator's local voice profile")
    parser.add_argument(
        "--operator", required=True, help="Seeded operator ID, for example OP-100"
    )
    parser.add_argument(
        "--audio",
        action="append",
        required=True,
        type=Path,
        help="A 1–15 second, mono or stereo, 16-bit PCM WAV file; repeat for more samples",
    )
    args = parser.parse_args()

    service = build_runtime().voice
    samples = [path.read_bytes() for path in args.audio]
    result = service.enroll(args.operator, samples)
    print(result.spoken_message)
    raise SystemExit(0 if result.enrolled else 1)


if __name__ == "__main__":
    main()
