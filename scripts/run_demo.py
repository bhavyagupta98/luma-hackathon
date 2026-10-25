"""One-command, hands-free demo launcher.

    python scripts/run_demo.py            # voice menu: say "register voice" or "sign in"
    python scripts/run_demo.py register   # skip the menu and start registering
    python scripts/run_demo.py signin     # skip the menu and start signing in
    python scripts/run_demo.py --fresh    # forget the demo operator's voice first (clean start)

It starts the gateway if it is not running, then opens Chrome in a clean app window with the
autoplay and microphone-prompt switches the demo needs, and keeps a small driver running. Browsers
refuse to play sound or open the microphone until the page gets one click, so the driver clicks
the page by itself whenever it is showing its "Tap to start" cover (the first page, and again after
each page change). The presenter never touches the screen.

Everything the presenter does is spoken: choose "register voice" or "sign in", say your name and
three phrases, then (once inside) commands such as "fix server A". Press Ctrl+C here to stop.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import websockets

ROOT = Path(__file__).resolve().parents[1]
DEVICE = "DC-D-100"
SCENARIO_PORT = 8090
# True while the page is showing its "Tap to start" cover.
WAITING_JS = "(() => { const o = document.getElementById('overlay'); return !!o && !o.hidden; })()"
CHROME_PATHS = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
)


def find_chrome() -> str | None:
    """The Chrome executable: $LUMA_CHROME if set, else the usual install locations."""
    override = os.environ.get("LUMA_CHROME")
    if override:
        return override if Path(override).is_file() else None
    return next((path for path in CHROME_PATHS if Path(path).is_file()), None)


def demo_url(
    port: int, *, start: str = "menu", debug: bool = False, on_device: bool = False
) -> str:
    """Where the window opens: the spoken menu ("menu"), or straight into "register"/"signin"."""
    query = {"device": DEVICE}
    if start == "register":
        query["enroll"] = "1"
    if not on_device:
        # Chrome's own speech engines respond instantly; the on-device models add seconds.
        query.update(stt="browser", tts="browser")
    if debug:
        query["debug"] = "1"
    page = "" if start == "menu" else "auth.html"
    return f"http://localhost:{port}/{page}?{urllib.parse.urlencode(query)}"


def chrome_args(chrome: str, url: str, profile: Path, debug_port: int) -> list[str]:
    return [
        chrome,
        f"--user-data-dir={profile}",
        f"--remote-debugging-port={debug_port}",
        "--remote-allow-origins=*",
        "--autoplay-policy=no-user-gesture-required",
        "--use-fake-ui-for-media-stream",  # allow the microphone without a prompt (real device)
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-features=Translate",
        "--start-fullscreen",
        f"--app={url}",
    ]


def port_open(port: int) -> bool:
    with socket.socket() as probe:
        probe.settimeout(0.5)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def start_gateway(port: int, extra_env: dict[str, str] | None = None) -> subprocess.Popen | None:
    """Start the gateway with the demo settings, unless something already answers on the port."""
    if port_open(port):
        print(f"Using the gateway already running on port {port}.")
        return None
    env = dict(os.environ)
    env.update(
        LUMA_GATEWAY_PORT=str(port),
        LUMA_VOICE_MATCH_THRESHOLD=env.get("LUMA_VOICE_MATCH_THRESHOLD", "0.6"),
        LUMA_ALLOW_BROWSER_ENROLL="1",  # demo only: lets the page register a voice
    )
    env.update(extra_env or {})
    process = subprocess.Popen(
        [sys.executable, "-m", "luma_datacenter.gateway.app"], cwd=ROOT, env=env
    )
    for _ in range(90):
        if port_open(port):
            return process
        if process.poll() is not None:
            break
        time.sleep(1)
    process.terminate()
    raise SystemExit("The gateway did not start. Run `luma-gateway` to see why.")


def forget_demo_voice() -> None:
    """Delete the demo operator's voice profile so the next sign-in says 'not registered'."""
    from luma_datacenter.config import database_path

    with sqlite3.connect(database_path()) as connection:
        removed = connection.execute(
            """
            DELETE FROM operator_voice_profiles WHERE operator_id IN
              (SELECT operator_id FROM datacenter_devices WHERE id = ?)
            """,
            (DEVICE,),
        ).rowcount
    print("Forgot the demo voice." if removed else "No demo voice was registered.")


class PageDriver:
    """Clicks the page whenever it is waiting behind its "Tap to start" cover."""

    def __init__(self, debug_port: int) -> None:
        self.debug_port = debug_port

    def _pages(self) -> list[dict]:
        url = f"http://127.0.0.1:{self.debug_port}/json"
        with urllib.request.urlopen(url, timeout=2) as response:
            return [t for t in json.load(response) if t.get("type") == "page"]

    @staticmethod
    async def _call(socket_, counter: list[int], method: str, params: dict | None = None):
        counter[0] += 1
        request_id = counter[0]
        await socket_.send(json.dumps({"id": request_id, "method": method, "params": params or {}}))
        while True:  # skip protocol events until our reply arrives
            message = json.loads(await socket_.recv())
            if message.get("id") == request_id:
                return message.get("result", {})

    async def tap_if_waiting(self) -> bool:
        """Click the first page that shows the cover. Returns whether a click was sent."""
        try:
            pages = await asyncio.to_thread(self._pages)
        except OSError:
            return False  # Chrome is not ready yet
        for page in pages:
            async with websockets.connect(
                page["webSocketDebuggerUrl"], open_timeout=3, max_size=None
            ) as socket_:
                counter = [0]
                evaluated = await self._call(
                    socket_,
                    counter,
                    "Runtime.evaluate",
                    {"expression": WAITING_JS, "returnByValue": True},
                )
                if not evaluated.get("result", {}).get("value"):
                    continue
                for kind in ("mousePressed", "mouseReleased"):
                    await self._call(
                        socket_,
                        counter,
                        "Input.dispatchMouseEvent",
                        {"type": kind, "x": 240, "y": 240, "button": "left", "clickCount": 1},
                    )
                return True
        return False

    async def run(self, chrome: subprocess.Popen, interval: float = 0.8) -> None:
        while chrome.poll() is None:
            try:
                if await self.tap_if_waiting():
                    print("  (tapped the page to start it)")
            except Exception as error:  # a page may be mid-navigation; try again next tick
                print(f"  (driver: {error})", file=sys.stderr)
            await asyncio.sleep(interval)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("start", nargs="?", choices=("menu", "register", "signin"), default="menu")
    parser.add_argument("--port", type=int, help="gateway port (8080, or 8090 with --scenario)")
    parser.add_argument("--debug-port", type=int, help="Chrome debugging port")
    parser.add_argument(
        "--scenario",
        action="store_true",
        help="the overheat-alert demo on its own port (8090): alert, then spoken directions",
    )
    parser.add_argument("--fresh", action="store_true", help="forget the demo voice first")
    parser.add_argument("--debug", action="store_true", help="show the on-screen log")
    parser.add_argument("--on-device", action="store_true", help="use the on-device speech models")
    parser.add_argument("--no-server", action="store_true", help="do not start the gateway")
    parser.add_argument("--no-click", action="store_true", help="do not tap the page for you")
    args = parser.parse_args()

    chrome = find_chrome()
    if chrome is None:
        sys.exit("Chrome was not found. Set LUMA_CHROME to its chrome.exe path.")
    if args.fresh:
        forget_demo_voice()
    args.port = args.port or (SCENARIO_PORT if args.scenario else 8080)
    args.debug_port = args.debug_port or (9223 if args.scenario else 9222)
    scenario_env = {
        "LUMA_SCENARIO": "overheat",
        "LUMA_SCENARIO_ALERT_DELAY": "8",
        "LUMA_SESSION_TTL_SECONDS": "300",  # the walk to the rack takes longer than a minute
    }
    gateway = None if args.no_server else start_gateway(
        args.port, scenario_env if args.scenario else None
    )

    url = demo_url(args.port, start=args.start, debug=args.debug, on_device=args.on_device)
    # A clean, git-ignored profile keeps flags and permissions tidy (one per demo).
    profile = ROOT / (".demo-chrome-profile-scenario" if args.scenario else ".demo-chrome-profile")
    print(f"Opening Chrome: {url}")
    print("Speak when you hear the tone. Press Ctrl+C here to stop.")
    browser = subprocess.Popen(chrome_args(chrome, url, profile, args.debug_port))
    try:
        if args.no_click:
            browser.wait()
        else:
            asyncio.run(PageDriver(args.debug_port).run(browser))
    except KeyboardInterrupt:
        pass
    finally:
        if gateway is not None:
            gateway.terminate()


if __name__ == "__main__":
    main()
