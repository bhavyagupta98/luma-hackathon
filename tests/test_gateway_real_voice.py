"""End-to-end with real audio: Windows text-to-speech voices as different workers,
the pinned ECAPA speaker model, the real database, and the gateway websocket protocol.

Skipped where torch or the Windows speech synthesizer is unavailable.
"""

from __future__ import annotations

import base64
import importlib.util
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("torch")
pytest.importorskip("speechbrain")
if sys.platform != "win32":
    pytest.skip("voice files need the Windows speech synthesizer", allow_module_level=True)

from luma_datacenter.gateway.app import create_app  # noqa: E402
from luma_datacenter.models import UserRegistrationRequest  # noqa: E402
from luma_datacenter.runtime import build_runtime  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DENIED = "You are not allowed to do this task."


def _load_generator():
    spec = importlib.util.spec_from_file_location(
        "make_demo_voices", ROOT / "scripts" / "make_demo_voices.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def voices(tmp_path_factory) -> Path:
    output = tmp_path_factory.mktemp("voices")
    _load_generator().generate(output)
    return output


@pytest.fixture(scope="module")
def runtime(tmp_path_factory, voices):
    runtime = build_runtime(tmp_path_factory.mktemp("db") / "real.db")
    for operator_id, speaker in (("OP-100", "avery"), ("OP-200", "jordan")):
        enrolled = runtime.voice.enroll(
            operator_id, [(voices / speaker / f"enroll-{n}.wav").read_bytes() for n in (1, 2, 3)]
        )
        assert enrolled.enrolled, enrolled.spoken_message
    return runtime


@pytest.fixture(scope="module")
def client(runtime):
    with TestClient(create_app(runtime, session_ttl_seconds=60)) as test_client:
        yield test_client


def clip(voices: Path, speaker: str, name: str) -> str:
    return base64.b64encode((voices / speaker / f"{name}.wav").read_bytes()).decode()


def sign_in(websocket, voices: Path, speaker: str, name: str = "auth-1") -> dict:
    websocket.send_json({"type": "voice_auth", "audio_wav_base64": clip(voices, speaker, name)})
    result = websocket.receive_json()
    assert result["type"] == "auth_result"
    return result


def command(websocket, text: str, session_id: str) -> str:
    websocket.send_json({"type": "utterance", "text": text, "session_id": session_id})
    return websocket.receive_json()["text"]


def test_enrolled_workers_sign_in_with_their_own_voice(client, voices) -> None:
    with client.websocket_connect("/ws/DC-D-100") as avery:
        avery.receive_json()
        result = sign_in(avery, voices, "avery", "auth-1")
        assert result["authenticated"], result
        assert result["spoken_message"] == "Avery Chen is authenticated."
        assert result["permissions"]["servers"] == ["SRV-100", "SRV-200"]
        print(f"\navery on DC-D-100 score: {result['similarity_score']}")
        # A second, different phrase from the same voice also matches.
        assert sign_in(avery, voices, "avery", "auth-2")["authenticated"]

    with client.websocket_connect("/ws/DC-D-200") as jordan:
        jordan.receive_json()
        result = sign_in(jordan, voices, "jordan", "auth-1")
        assert result["authenticated"], result
        assert result["role"] == "operator"
        print(f"jordan on DC-D-200 score: {result['similarity_score']}")


@pytest.mark.parametrize("speaker", ["jordan", "alice"])
def test_someone_elses_voice_is_refused_on_averys_device(client, voices, speaker) -> None:
    with client.websocket_connect("/ws/DC-D-100") as earpiece:
        earpiece.receive_json()
        result = sign_in(earpiece, voices, speaker)
        print(f"\n{speaker} on DC-D-100 score: {result['similarity_score']}")
        assert result["authenticated"] is False
        assert result["code"] == "VOICE_NOT_MATCHED"
        assert result["spoken_message"] == "You are not registered."
        assert "session_id" not in result


def test_spoken_tasks_are_checked_against_server_assignments(client, voices, runtime) -> None:
    with client.websocket_connect("/ws/DC-D-200") as jordan:
        jordan.receive_json()
        session = sign_in(jordan, voices, "jordan")["session_id"]
        assert command(jordan, "Restart server one hundred.", session) == DENIED
        assert command(jordan, "Fix server three hundred.", session) == "Task successful."

    with client.websocket_connect("/ws/DC-D-100") as avery:
        avery.receive_json()
        session = sign_in(avery, voices, "avery")["session_id"]
        assert command(avery, "Restart server one hundred.", session) == "Task successful."
        assert command(avery, "Restart server three hundred.", session) == DENIED


def test_onboarding_a_new_worker_by_voice(client, voices, runtime) -> None:
    admin = runtime.voice.authenticate("DC-D-100", (voices / "avery" / "auth-2.wav").read_bytes())
    assert admin.authenticated, admin.spoken_message
    claims = runtime.voice.verify_token(admin.authentication_token)
    added = runtime.administration.add_user(
        UserRegistrationRequest(
            request_id="real-voice-onboard-alice",
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
    assert added.approved, added.spoken_message

    with client.websocket_connect("/ws/DC-D-ALICE") as alice:
        alice.receive_json()
        assert sign_in(alice, voices, "alice")["code"] == "VOICE_NOT_ENROLLED"

        enrolled = runtime.voice.enroll(
            "OP-ALICE", [(voices / "alice" / f"enroll-{n}.wav").read_bytes() for n in (1, 2, 3)]
        )
        assert enrolled.enrolled

        result = sign_in(alice, voices, "alice", "auth-1")
        assert result["authenticated"], result
        assert result["spoken_message"] == "Alice Smith is authenticated."
        assert result["permissions"]["servers"] == ["SRV-100"]
        session = result["session_id"]
        assert command(alice, "restart server one hundred", session) == "Task successful."
        assert command(alice, "restart server two hundred", session) == DENIED

    # Alice's new voice profile does not unlock the admin's device.
    with client.websocket_connect("/ws/DC-D-100") as avery_device:
        avery_device.receive_json()
        assert sign_in(avery_device, voices, "alice")["authenticated"] is False
