from __future__ import annotations

from fastapi.testclient import TestClient

from luma_datacenter.gateway.app import app


def test_utterance_text_round_trips_to_a_spoken_reply() -> None:
    with TestClient(app).websocket_connect("/ws/DC-D-100") as earpiece:
        hello = earpiece.receive_json()
        assert hello["type"] == "hello"
        assert hello["device_id"] == "DC-D-100"

        earpiece.send_json({"type": "utterance", "text": "start server one hundred"})
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

    assert "status" in reply["text"]


def test_gateway_serves_the_earpiece_page() -> None:
    client = TestClient(app)
    assert client.get("/api/health").json()["ok"] is True
    page = client.get("/ear.html")
    assert page.status_code == 200
    assert "ear.js" in page.text
