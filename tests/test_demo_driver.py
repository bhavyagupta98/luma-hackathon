"""The demo launcher (scripts/run_demo.py): URLs, Chrome flags, and the page-tapping driver.

The driver is tested against a fake Chrome DevTools endpoint (an HTTP /json list plus a websocket
that answers Runtime.evaluate), so no browser is started.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import websockets

ROOT = Path(__file__).resolve().parents[1]


def load_launcher():
    spec = importlib.util.spec_from_file_location("run_demo", ROOT / "scripts" / "run_demo.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


run_demo = load_launcher()


@contextmanager
def fake_chrome(*, overlay_visible: bool, with_page: bool = True):
    """A DevTools endpoint; yields (debug_port, list of every CDP call the driver made)."""
    calls: list[tuple[str, dict]] = []
    loop = asyncio.new_event_loop()
    ready = threading.Event()
    state: dict = {}

    async def handler(connection):
        async for raw in connection:
            request = json.loads(raw)
            calls.append((request["method"], request.get("params", {})))
            if request["method"] == "Runtime.evaluate":
                result = {"result": {"type": "boolean", "value": overlay_visible}}
            else:
                result = {}
            await connection.send(json.dumps({"id": request["id"], "result": result}))

    async def serve_websocket():
        stop = asyncio.Event()
        state["stop"] = lambda: loop.call_soon_threadsafe(stop.set)
        async with websockets.serve(handler, "127.0.0.1", 0) as server:
            state["ws_port"] = server.sockets[0].getsockname()[1]
            ready.set()
            await stop.wait()

    def run_loop():
        loop.run_until_complete(serve_websocket())
        loop.close()

    thread = threading.Thread(target=run_loop, daemon=True)
    thread.start()
    assert ready.wait(5)

    class ListPages(BaseHTTPRequestHandler):
        def do_GET(self):
            pages = [{"type": "service_worker", "webSocketDebuggerUrl": "ws://unused"}]
            if with_page:
                pages.append(
                    {
                        "type": "page",
                        "url": "http://localhost:8080/auth.html",
                        "webSocketDebuggerUrl": f"ws://127.0.0.1:{state['ws_port']}/page",
                    }
                )
            body = json.dumps(pages).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    http = ThreadingHTTPServer(("127.0.0.1", 0), ListPages)
    threading.Thread(target=http.serve_forever, daemon=True).start()
    try:
        yield http.server_address[1], calls
    finally:
        http.shutdown()
        state["stop"]()
        thread.join(5)


def test_driver_taps_a_page_that_is_waiting_behind_the_cover() -> None:
    with fake_chrome(overlay_visible=True) as (port, calls):
        tapped = asyncio.run(run_demo.PageDriver(port).tap_if_waiting())

    assert tapped is True
    assert [method for method, _ in calls] == [
        "Runtime.evaluate",
        "Input.dispatchMouseEvent",
        "Input.dispatchMouseEvent",
    ]
    assert [params["type"] for method, params in calls[1:]] == ["mousePressed", "mouseReleased"]
    assert all(params["button"] == "left" and params["clickCount"] == 1 for _, params in calls[1:])
    assert "overlay" in calls[0][1]["expression"]  # it asked the page about its cover


def test_driver_leaves_a_page_alone_once_it_has_started() -> None:
    with fake_chrome(overlay_visible=False) as (port, calls):
        tapped = asyncio.run(run_demo.PageDriver(port).tap_if_waiting())

    assert tapped is False
    assert [method for method, _ in calls] == ["Runtime.evaluate"]  # looked, did not click


def test_driver_copes_with_no_page_yet_and_with_chrome_not_running() -> None:
    with fake_chrome(overlay_visible=True, with_page=False) as (port, calls):
        assert asyncio.run(run_demo.PageDriver(port).tap_if_waiting()) is False
        assert calls == []
    # Nothing is listening on this port at all.
    assert asyncio.run(run_demo.PageDriver(1).tap_if_waiting()) is False


def test_demo_urls_open_the_voice_menu_or_go_straight_to_register_or_sign_in() -> None:
    menu = run_demo.demo_url(8080)
    assert menu.startswith("http://localhost:8080/?device=DC-D-100")
    assert "enroll" not in menu and "stt=browser" in menu and "tts=browser" in menu

    register = run_demo.demo_url(8080, start="register")
    assert register.startswith("http://localhost:8080/auth.html?")
    assert "enroll=1" in register and "device=DC-D-100" in register
    assert "stt=browser" in register and "tts=browser" in register

    sign_in = run_demo.demo_url(9000, start="signin", debug=True, on_device=True)
    assert sign_in.startswith("http://localhost:9000/auth.html?")
    assert "enroll" not in sign_in and "stt=" not in sign_in and "debug=1" in sign_in


def test_chrome_is_launched_with_the_flags_the_hands_free_demo_needs(tmp_path) -> None:
    args = run_demo.chrome_args("chrome.exe", "http://localhost:8080/x", tmp_path, 9222)

    assert args[0] == "chrome.exe"
    assert "--autoplay-policy=no-user-gesture-required" in args
    assert "--use-fake-ui-for-media-stream" in args
    assert "--remote-debugging-port=9222" in args
    assert f"--user-data-dir={tmp_path}" in args
    assert "--app=http://localhost:8080/x" in args


def test_chrome_location_can_be_overridden(monkeypatch, tmp_path) -> None:
    fake = tmp_path / "chrome.exe"
    fake.write_text("")
    monkeypatch.setenv("LUMA_CHROME", str(fake))
    assert run_demo.find_chrome() == str(fake)

    monkeypatch.setenv("LUMA_CHROME", str(tmp_path / "missing.exe"))
    assert run_demo.find_chrome() is None


@pytest.mark.parametrize("busy", [True, False])
def test_port_check_reports_whether_something_is_listening(busy) -> None:
    import socket

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        if busy:
            listener.listen()
            assert run_demo.port_open(port) is True
    if not busy:
        assert run_demo.port_open(port) is False
