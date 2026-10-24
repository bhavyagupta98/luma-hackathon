from __future__ import annotations

import argparse
import wave
from pathlib import Path

import sounddevice


def main() -> None:
    parser = argparse.ArgumentParser(description="Record a local PCM WAV voice sample")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--seconds", type=float, default=5.0)
    parser.add_argument("--device", help="Input-device index or name")
    parser.add_argument("--list-devices", action="store_true")
    args = parser.parse_args()
    if args.list_devices:
        print(sounddevice.query_devices())
        return
    if args.output is None:
        parser.error("--output is required unless --list-devices is used")
    if not 1 <= args.seconds <= 15:
        parser.error("--seconds must be between 1 and 15")

    sample_rate = 16_000
    print(f"Recording for {args.seconds:g} seconds. Speak now...")
    try:
        recording = sounddevice.rec(
            int(args.seconds * sample_rate),
            samplerate=sample_rate,
            channels=1,
            dtype="int16",
            device=args.device,
        )
        sounddevice.wait()
    except sounddevice.PortAudioError as exc:
        raise SystemExit(
            "No microphone was available. Grant Terminal microphone access in macOS "
            "System Settings, or select one with --device."
        ) from exc

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(args.output), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(recording.tobytes())
    print(f"Saved {args.output}")


if __name__ == "__main__":
    main()
