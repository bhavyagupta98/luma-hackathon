"""Prepare the local demo database from the generated voice files.

    python scripts/make_demo_voices.py          # once: writes samples/
    python scripts/demo_setup.py                # enroll Avery (OP-100) and Jordan (OP-200)
    python scripts/demo_setup.py --onboard      # also add Alice by voice and enroll her

Onboarding follows the production rules: the admin (Avery) authenticates by voice, that
one-time signed token authorizes `add_organization_user`, and the new worker then enrolls
their own voice. Run it with the gateway stopped (it uses the same SQLite file).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from luma_datacenter.models import UserRegistrationRequest
from luma_datacenter.runtime import build_runtime

ENROLLED = {"OP-100": "avery", "OP-200": "jordan"}


def clips(samples: Path, speaker: str, prefix: str) -> list[bytes]:
    paths = sorted((samples / speaker).glob(f"{prefix}-*.wav"))
    if not paths:
        sys.exit(f"No {prefix} clips for {speaker} in {samples}/ - run scripts/make_demo_voices.py")
    return [path.read_bytes() for path in paths]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--samples", type=Path, default=Path("samples"))
    parser.add_argument("--onboard", action="store_true", help="add Alice as a new operator")
    args = parser.parse_args()

    runtime = build_runtime()
    for operator_id, speaker in ENROLLED.items():
        result = runtime.voice.enroll(operator_id, clips(args.samples, speaker, "enroll"))
        print(f"{operator_id} ({speaker}): {result.spoken_message}")

    if not args.onboard:
        return
    admin = runtime.voice.authenticate("DC-D-100", clips(args.samples, "avery", "auth")[0])
    if not admin.authenticated:
        sys.exit(f"Admin voice check failed: {admin.spoken_message}")
    claims = runtime.voice.verify_token(str(admin.authentication_token))
    added = runtime.administration.add_user(
        UserRegistrationRequest(
            request_id="demo-onboard-alice",
            actor_operator_id=claims["sub"],
            actor_device_id=claims["device_id"],
            actor_organization_id=claims["organization_id"],
            actor_scope=claims["scope"],
            token_jti=claims["jti"],
            organization_id="ORG-DEMO",
            user_id="OP-ALICE",
            display_name="Alice Smith",
            role="operator",
            device_id="DC-D-ALICE",
            server_ids=("SRV-100",),
        )
    )
    print(f"add user: {added.spoken_message}")
    enrolled = runtime.voice.enroll("OP-ALICE", clips(args.samples, "alice", "enroll"))
    print(f"OP-ALICE (alice): {enrolled.spoken_message}")


if __name__ == "__main__":
    main()
