"""Play a worker through a running gateway using a voice file instead of a microphone.

    python scripts/simulate_worker.py --device DC-D-100 --audio samples/avery/auth-1.wav \\
        "restart server one hundred" "restart server three hundred"

It speaks the same protocol as the earpiece: one `voice_auth` message, then `utterance`
text messages carrying the session id. Replies are printed (and read aloud with --speak).
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
from pathlib import Path

import websockets


def speak_aloud(text: str) -> None:
    import subprocess

    script = (
        "Add-Type -AssemblyName System.Speech;"
        "(New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak($args[0])"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", script, text], check=False)


async def run(args: argparse.Namespace) -> None:
    say = speak_aloud if args.speak else (lambda text: None)
    url = f"ws://{args.host}/ws/{args.device}"
    async with websockets.connect(url, max_size=8 * 1024 * 1024) as socket:
        await socket.recv()  # hello
        audio = base64.b64encode(args.audio.read_bytes()).decode()
        await socket.send(json.dumps({"type": "voice_auth", "audio_wav_base64": audio}))
        auth = json.loads(await socket.recv())
        print(f"[auth] {auth['spoken_message']}")
        if auth.get("similarity_score") is not None:
            print(f"       voice similarity {auth['similarity_score']}")
        say(auth["spoken_message"])
        if not auth["authenticated"]:
            raise SystemExit(1)
        print(f"       role={auth['role']} servers={auth['permissions']['servers']}")

        for text in args.commands:
            print(f"[you]  {text}")
            await socket.send(
                json.dumps({"type": "utterance", "text": text, "session_id": auth["session_id"]})
            )
            reply = json.loads(await socket.recv())
            print(f"[bot]  {reply['text']}")
            say(reply["text"])

        if args.wait:
            print(f"waiting {args.wait}s for the session to expire...")
            while True:
                message = json.loads(await asyncio.wait_for(socket.recv(), args.wait + 10))
                if message["type"] == "say":
                    print(f"[bot]  {message['text']}")
                    break
                print(f"[gateway] {message['type']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default="localhost:8080")
    parser.add_argument("--device", required=True, help="trusted device id, e.g. DC-D-100")
    parser.add_argument("--audio", type=Path, required=True, help="WAV file to sign in with")
    parser.add_argument("--speak", action="store_true", help="read replies aloud (Windows)")
    parser.add_argument("--wait", type=int, default=0, help="stay connected to watch expiry")
    parser.add_argument("commands", nargs="*", help="spoken commands, as text")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
