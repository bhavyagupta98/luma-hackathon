"""The overheat scenario's spoken dialogue, as plain text in and text out."""

from __future__ import annotations

import pytest

from luma_datacenter.gateway.guidance import DEVICE_LOCATIONS, NEXT_STEP, PLACES, Guide, route

S = "session-1"


def started(device: str = "DC-D-100") -> tuple[Guide, str]:
    guide = Guide()
    alert = guide.alert(S, device)
    assert alert is not None
    return guide, alert


def test_the_alert_names_the_server_and_asks_about_directions() -> None:
    _, alert = started()

    assert alert == (
        "Alert. Server B in Hall B is overheating, 41 degrees. "
        "Do you need directions to get there?"
    )


def test_the_worker_is_only_alerted_once_per_session() -> None:
    guide, _ = started()

    assert guide.alert(S, "DC-D-100") is None
    assert guide.alert("another-session", "DC-D-100") is not None


@pytest.mark.parametrize(
    "answer", ["yes", "Yeah, please.", "sure", "directions", "I need directions"]
)
def test_saying_yes_starts_from_where_the_worker_checked_in(answer: str) -> None:
    guide, _ = started("DC-D-100")

    reply = guide.reply(S, answer)

    assert reply.startswith("You are at the main entrance. We start from here. Step one of four.")
    assert "Walk straight down the main corridor" in reply
    assert reply.endswith("Say next when done.")


def test_the_starting_point_depends_on_where_the_worker_signed_in() -> None:
    dock, _ = started("DC-D-200")
    room, _ = started("DC-D-ALICE")

    assert dock.reply(S, "yes").startswith(
        "You are at the loading dock. We start from here. Step one of three."
    )
    assert room.reply(S, "yes").startswith(
        "You are at the break room. We start from here. Step one of four."
    )


@pytest.mark.parametrize(
    "answer", ["no", "No thanks", "not now", "I know the way", "I don't need directions"]
)
def test_saying_no_keeps_the_alert_open_and_directions_can_be_asked_for_later(answer: str) -> None:
    guide, _ = started()

    assert guide.reply(S, answer) == (
        "Okay. The alert stays open. Say directions whenever you need them."
    )
    assert guide.reply(S, "what time is it") is None  # nothing to do with the scenario
    assert guide.reply(S, "directions").startswith("You are at the main entrance.")


def test_an_unclear_answer_asks_again() -> None:
    guide, _ = started()

    assert guide.reply(S, "hmm banana") == "Do you need directions to the server? Say yes or no."


def test_a_full_walk_with_a_repeat_and_a_step_back_ends_at_the_rack() -> None:
    guide, _ = started()
    guide.reply(S, "yes")

    assert guide.reply(S, "repeat").startswith(
        "Step one of four. Walk straight down the main corridor"
    )
    assert guide.reply(S, "done").startswith("Step two of four. Go through the double doors")
    assert guide.reply(S, "say that again").startswith("Step two of four.")
    assert guide.reply(S, "next").startswith("Step three of four. Turn left.")
    assert guide.reply(S, "go back").startswith("Going back. Step two of four.")
    assert guide.reply(S, "okay").startswith("Step three of four.")
    assert guide.reply(S, "next").startswith("Step four of four. Walk down the aisle.")
    arrived = guide.reply(S, "I'm there")
    assert arrived == (
        "You have arrived at rack fourteen. Server B should show an amber light. "
        "Say fix server B to start the cooling reset."
    )
    assert guide.reply(S, "what") == (
        "You are at rack fourteen. Say fix server B to start the cooling reset."
    )
    assert guide.reply(S, "uh") == "Say fix server B when you are ready."


def test_where_am_i_reports_the_place_reached_so_far() -> None:
    guide, _ = started()
    guide.reply(S, "yes")

    assert guide.reply(S, "where am I").startswith("You should be at the main entrance.")
    guide.reply(S, "next")
    assert guide.reply(S, "where am I").startswith("You should be at the double doors to Hall B.")
    guide.reply(S, "next")
    assert guide.reply(S, "where am I").startswith("You should be at the front of Hall B.")


def test_the_worker_can_correct_their_location_and_the_route_restarts_from_there() -> None:
    guide, _ = started("DC-D-100")
    guide.reply(S, "yes")
    guide.reply(S, "next")

    reply = guide.reply(S, "actually I'm at the loading dock")

    assert reply.startswith("Got it. You are at the loading dock. Step one of three.")
    assert "service corridor" in reply
    assert guide.reply(S, "next").startswith("Step two of three. Aisle three is the first aisle")


def test_saying_wrong_location_asks_where_they_are() -> None:
    guide, _ = started()
    guide.reply(S, "yes")

    assert guide.reply(S, "that's the wrong location") == (
        "Where are you? Say main entrance, loading dock, or break room."
    )
    assert guide.reply(S, "banana") == "Say main entrance, loading dock, or break room."
    assert guide.reply(S, "the break room").startswith("Got it. You are at the break room.")


def test_stop_ends_the_directions_but_they_can_be_restarted() -> None:
    guide, _ = started()
    guide.reply(S, "yes")

    assert guide.reply(S, "stop") == (
        "Okay, directions stopped. Say directions any time you need them."
    )
    assert guide.reply(S, "next") is None  # not navigating any more
    assert guide.reply(S, "directions").startswith("You are at the main entrance.")


def test_unrecognized_speech_mid_walk_explains_what_can_be_said() -> None:
    guide, _ = started()
    guide.reply(S, "yes")

    assert guide.reply(S, "purple monkey") == (
        "Say next when you are there, repeat to hear it again, or stop."
    )


def test_fixing_the_overheating_server_ends_the_alert() -> None:
    guide, _ = started()
    guide.reply(S, "yes")

    assert guide.resolved(S, "SRV-100") is None  # a different server
    assert guide.resolved(S, "SRV-200") == (
        "Task successful. Server B is cooling down. Alert cleared. Good work."
    )
    assert not guide.active(S)
    assert guide.reply(S, "next") is None


def test_forgetting_a_session_clears_its_state() -> None:
    guide, _ = started()

    guide.forget(S)

    assert not guide.active(S)
    assert guide.alert(S, "DC-D-100") is not None  # a new session can be alerted again


def test_every_check_in_point_has_a_route_to_the_rack() -> None:
    for device, place in DEVICE_LOCATIONS.items():
        steps = route(place)
        assert steps and steps[-1][0] == "rack_14", device
    assert route("nowhere") is None
    assert all(target in PLACES for target, _ in NEXT_STEP.values())
    assert all(len(text) < 110 for _, text in NEXT_STEP.values())  # short enough to say quickly
