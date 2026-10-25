"""The overheat scenario over the real gateway websocket: alert, directions, and the fix."""

from __future__ import annotations

import pytest
from test_gateway_flow import build_runtime, open_earpiece, running_gateway, say, sign_in

from luma_datacenter.gateway.guidance import Guide


@pytest.fixture
def runtime(tmp_path):
    return build_runtime(tmp_path)


def command_page(client, device: str, speaker: str):
    """Sign in on one connection, then open a second one as the command page does."""
    session = sign_in(open_earpiece(client, device), speaker)["session_id"]
    return open_earpiece(client, device), session


def test_the_alert_arrives_by_itself_once_the_worker_is_on_the_command_page(runtime) -> None:
    with running_gateway(runtime, 60, guide=Guide(alert_delay=0.2)) as client:
        page, _ = command_page(client, "DC-D-100", "avery")

        alert = page.receive_json()  # nobody asked for it

    assert alert["type"] == "say"
    assert alert["priority"] == "warning" and alert["earcon"] == "warn"
    assert alert["text"] == (
        "Alert. Server B in Hall B is overheating, 41 degrees. "
        "Do you need directions to get there?"
    )


def test_a_whole_spoken_walk_from_the_alert_to_the_fix(runtime) -> None:
    with running_gateway(runtime, 60, guide=Guide(alert_delay=0.2)) as client:
        page, session = command_page(client, "DC-D-100", "avery")
        page.receive_json()  # the alert

        def tell(text: str) -> str:
            return say(page, text, session)["text"]

        assert tell("yes").startswith("You are at the main entrance. We start from here. Step one")
        assert tell("repeat").startswith("Step one of four.")
        assert tell("done").startswith("Step two of four.")
        assert tell("next").startswith("Step three of four.")
        assert tell("next").startswith("Step four of four.")
        assert tell("next").startswith("You have arrived at rack fourteen.")
        done = say(page, "Fix server B.", session)
        assert done["text"] == (
            "Task successful. Server B is cooling down. Alert cleared. Good work."
        )
        assert done["earcon"] == "success"
        # The alert is finished; ordinary commands carry on as before.
        assert tell("next").startswith("I can restart a server")


def test_declining_directions_still_lets_the_worker_run_commands(runtime) -> None:
    with running_gateway(runtime, 60, guide=Guide(alert_delay=0.2)) as client:
        page, session = command_page(client, "DC-D-100", "avery")
        page.receive_json()

        assert say(page, "no thanks", session)["text"] == (
            "Okay. The alert stays open. Say directions whenever you need them."
        )
        assert say(page, "fix server A", session)["text"] == "Task successful."
        assert say(page, "directions", session)["text"].startswith("You are at the main entrance.")


def test_a_command_spoken_instead_of_answering_is_still_run(runtime) -> None:
    with running_gateway(runtime, 60, guide=Guide(alert_delay=0.2)) as client:
        page, session = command_page(client, "DC-D-100", "avery")
        page.receive_json()

        reply = say(page, "fix server B", session)

        assert reply["text"].startswith("Task successful. Server B is cooling down")


def test_only_workers_assigned_to_the_server_are_alerted(runtime) -> None:
    with running_gateway(runtime, 60, guide=Guide(alert_delay=0.0)) as client:
        avery_page, _ = command_page(client, "DC-D-100", "avery")
        command_page(client, "DC-D-200", "jordan")  # Jordan only controls SRV-300

        avery_page.receive_json()  # the timed alert for Avery
        # Asking for an alert now reaches nobody: Avery has had hers, Jordan has no stake in B.
        assert client.post("/api/scenario/overheat").json() == {"ok": True, "alerted": []}


def test_the_developer_trigger_alerts_everyone_signed_in_and_responsible(runtime) -> None:
    with running_gateway(runtime, 60, guide=Guide(alert_delay=3600)) as client:
        avery_page, _ = command_page(client, "DC-D-100", "avery")
        command_page(client, "DC-D-200", "jordan")

        assert client.post("/api/scenario/overheat").json() == {"ok": True, "alerted": ["DC-D-100"]}
        assert avery_page.receive_json()["text"].startswith("Alert. Server B in Hall B")


def test_without_the_scenario_nothing_is_pushed_and_the_trigger_is_off(runtime) -> None:
    with running_gateway(runtime, 60) as client:
        page, session = command_page(client, "DC-D-100", "avery")

        assert client.post("/api/scenario/overheat").json()["ok"] is False
        # The usual replies are unchanged.
        assert say(page, "yes", session)["text"].startswith("I can restart a server")


def test_a_worker_who_expires_is_not_left_mid_walk(runtime) -> None:
    guide = Guide(alert_delay=0.2)
    with running_gateway(runtime, 1.0, guide=guide) as client:
        page, session = command_page(client, "DC-D-100", "avery")
        page.receive_json()
        say(page, "yes", session)
        assert guide.active(session)

        assert page.receive_json()["type"] == "session_expired"
        page.receive_json()  # the spoken notice

    assert not guide.active(session)
