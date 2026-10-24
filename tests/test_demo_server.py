from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from luma_datacenter.demo_server import app, build_demo_cases


def test_narrated_demo_runs_real_backend_acceptance_cases(tmp_path: Path) -> None:
    cases = build_demo_cases(tmp_path)

    assert len(cases) == 8
    assert all(case["passed"] for case in cases)
    assert {case["code"] for case in cases} >= {
        "VOICE_AUTHENTICATED",
        "SERVER_ACTION_APPROVED",
        "SERVER_NOT_ASSIGNED",
        "VOICE_NOT_MATCHED",
        "AUTHENTICATION_REQUIRED",
    }
    assert all(case["system"] for case in cases)
    assert {case["speaker"] for case in cases} == {"AB", "BG", "UNKNOWN"}


def test_demo_page_and_api_are_served() -> None:
    client = TestClient(app)
    assert "Play full demo" in client.get("/demo.html").text
    response = client.post("/api/demo/cases")
    assert response.status_code == 200
    assert response.json()["all_passed"] is True
