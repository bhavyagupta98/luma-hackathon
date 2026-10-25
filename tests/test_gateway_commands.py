from __future__ import annotations

import asyncio

import pytest

from luma_datacenter.gateway.commands import Command, parse_command, words_to_int
from luma_datacenter.gateway.sessions import SessionStore


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Restart server one hundred.", Command("restart", "SRV-100")),
        ("restart server 100", Command("restart", "SRV-100")),
        ("Please fix server number two hundred", Command("fix", "SRV-200")),
        ("reboot SRV-300", Command("restart", "SRV-300")),
        ("Restart S R V 100", Command("restart", "SRV-100")),
        ("fix server100", Command("fix", "SRV-100")),
        ("restart server one oh oh", Command("restart", "SRV-100")),
        ("fix server two fifty", Command("fix", "SRV-250")),
        ("restart server one hundred and twenty three", Command("restart", "SRV-123")),
        ("restart server A", Command("restart", "SRV-A")),
        ("Fix server A.", Command("fix", "SRV-A")),
        ("fix server ay", Command("fix", "SRV-A")),
        ("restart server bee", Command("restart", "SRV-B")),
        ("fix server charlie", Command("fix", "SRV-C")),
        ("fix server see", Command("fix", "SRV-C")),
        ("repair the server", Command("fix", None)),
        ("restart", Command("restart", None)),
    ],
)
def test_parse_command(text: str, expected: Command) -> None:
    assert parse_command(text) == expected


@pytest.mark.parametrize("text", ["what time is it", "start server one hundred", ""])
def test_unrelated_speech_is_not_a_command(text: str) -> None:
    assert parse_command(text) is None


def test_words_to_int() -> None:
    assert words_to_int(["twenty", "five"]) == 25
    assert words_to_int(["one", "hundred", "five"]) == 105
    assert words_to_int(["banana"]) is None
    assert words_to_int([]) is None


def make_session(store: SessionStore, operator_id: str = "OP-1"):
    return store.create(
        operator_id=operator_id,
        name="Test",
        device_id="DEV",
        organization_id="ORG",
        role="operator",
        scopes=["server:control"],
        servers=["SRV-1"],
    )


def test_session_is_cleared_after_its_ttl_and_the_worker_is_notified() -> None:
    async def scenario() -> None:
        expired: list[str] = []

        async def on_expire(session) -> None:
            expired.append(session.operator_id)

        store = SessionStore(0.2, on_expire=on_expire)
        first = make_session(store, "OP-1")
        await asyncio.sleep(0.1)
        second = make_session(store, "OP-2")
        assert store.get(first.id) is first
        assert store.active_count() == 2

        await asyncio.sleep(0.15)  # first is past its deadline, second is not
        assert store.get(first.id) is None
        assert store.get(second.id) is second
        assert expired == ["OP-1"]

        await asyncio.sleep(0.15)
        assert store.get(second.id) is None
        assert expired == ["OP-1", "OP-2"]
        assert store.active_count() == 0

    asyncio.run(scenario())


def test_reauthenticating_replaces_the_operators_old_session() -> None:
    async def scenario() -> None:
        store = SessionStore(5)
        old = make_session(store)
        new = make_session(store)
        assert store.get(old.id) is None
        assert store.get(new.id) is new
        assert store.get(None) is None
        store.end(new.id)
        assert store.active_count() == 0

    asyncio.run(scenario())
