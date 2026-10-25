"""Generate local demo voice files with the Windows speech synthesizer (SAPI).

Each installed Windows voice acts as a different person, so enrollment and
authentication can be tested without a microphone. Output goes to `samples/`
(git-ignored):

    samples/<speaker>/enroll-1.wav .. enroll-3.wav   enrollment phrases
    samples/<speaker>/auth-1.wav .. auth-2.wav       sign-in phrases (never used to enroll)

Speakers: avery (David, OP-100), jordan (Zira, OP-200), alice (Hazel, new hire).
Run: python scripts/make_demo_voices.py [--output samples]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

SPEAKERS = {
    "avery": "Microsoft David Desktop",
    "jordan": "Microsoft Zira Desktop",
    "alice": "Microsoft Hazel Desktop",
}
PHRASES = {
    "enroll-1": "My voice is my badge. Verify me.",
    "enroll-2": "Server room access for the night shift.",
    "enroll-3": "The quick brown fox jumps over the lazy dog.",
    "auth-1": "Good morning, this is my voice. Please let me in to the data center.",
    "auth-2": "I am here to work on the servers. Please verify my voice.",
}

POWERSHELL = r"""
Add-Type -AssemblyName System.Speech
$jobs = [Console]::In.ReadToEnd() | ConvertFrom-Json
$format = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(
    16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,
    [System.Speech.AudioFormat.AudioChannel]::Mono)
foreach ($job in $jobs) {
    $synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
    $synth.SelectVoice($job.voice)
    $synth.Rate = 0
    $synth.SetOutputToWaveFile($job.path, $format)
    $synth.Speak($job.text)
    $synth.Dispose()
}
"""


def generate(output: Path) -> list[Path]:
    """Write every demo clip under `output` and return their paths."""
    jobs = []
    for speaker, voice in SPEAKERS.items():
        (output / speaker).mkdir(parents=True, exist_ok=True)
        for name, text in PHRASES.items():
            path = (output / speaker / f"{name}.wav").resolve()
            jobs.append({"voice": voice, "text": text, "path": str(path)})
    subprocess.run(
        ["powershell", "-NoProfile", "-Command", POWERSHELL],
        input=json.dumps(jobs),
        text=True,
        check=True,
    )
    return [Path(job["path"]) for job in jobs]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, default=Path("samples"))
    args = parser.parse_args()
    if sys.platform != "win32":
        sys.exit("This needs the Windows speech synthesizer; record clips with luma-record-voice.")
    paths = generate(args.output)
    print(f"Wrote {len(paths)} clips under {args.output}/")


if __name__ == "__main__":
    main()
