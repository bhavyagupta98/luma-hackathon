from __future__ import annotations

from fastapi.testclient import TestClient

from luma_datacenter.gateway.app import app


def test_utterance_text_round_trips_to_a_spoken_reply() -> None:
    with TestClient(app).websocket_connect("/ws/DC-D-100") as earpiece:
        hello = earpiece.receive_json()
        assert hello["type"] == "hello"
        assert hello["device_id"] == "DC-D-100"

        earpiece.send_json({"type": "utterance", "text": "restart server one hundred"})
        reply = earpiece.receive_json()

    assert reply["type"] == "say"
    assert reply["text"]
    assert reply["lang"] == "en-US"
    assert reply["priority"] in {"info", "task", "warning", "emergency"}
    assert reply["id"].startswith("evt_")


def test_blank_utterances_and_acks_get_no_reply() -> None:
    with TestClient(app).websocket_connect("/ws/DC-D-100") as earpiece:
        earpiece.receive_json()
        earpiece.send_json({"type": "utterance", "text": "   "})
        earpiece.send_json({"type": "ack", "id": "evt_1"})
        earpiece.send_json({"type": "utterance", "text": "help"})
        reply = earpiece.receive_json()

    assert "restart" in reply["text"]


def test_gateway_serves_the_earpiece_page() -> None:
    client = TestClient(app)
    assert client.get("/api/health").json()["ok"] is True
    page = client.get("/ear.html")
    assert page.status_code == 200
    assert "ear.js" in page.text


def test_local_page_registers_ab_and_bg_with_exact_passphrase(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LUMA_DATABASE_PATH", str(tmp_path / "registration.db"))
    monkeypatch.setenv("LUMA_VOICE_SIGNING_KEY_PATH", str(tmp_path / "registration.pem"))
    client = TestClient(app)
    payload = {
        "transcript": "My voice is my badge. Authorize datacenter access.",
        "embedding": [1.0] + [0.0] * 511,
        "embedding_model": "Xenova/wavlm-base-plus-sv",
    }

    ab = client.post("/api/local-register-voice", json=payload | {"person": "AB"})
    bg = client.post("/api/local-register-voice", json=payload | {"person": "BG"})
    wrong = client.post(
        "/api/local-register-voice",
        json=payload | {"person": "AB", "transcript": "wrong phrase"},
    )

    assert ab.status_code == 200
    assert bg.status_code == 200
    assert bg.json()["role"] == "org_admin"
    assert wrong.status_code == 400
