from __future__ import annotations

import io
import math
import struct
import wave

from luma_datacenter.config import voice_model_path
from luma_datacenter.voice_embeddings import SpeechBrainECAPAEmbedder


def test_pinned_local_model_produces_a_finite_embedding_without_download() -> None:
    audio = io.BytesIO()
    with wave.open(audio, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16_000)
        wav_file.writeframes(
            b"".join(
                struct.pack("<h", int(8_000 * math.sin(2 * math.pi * 220 * index / 16_000)))
                for index in range(32_000)
            )
        )

    embedding = SpeechBrainECAPAEmbedder(voice_model_path()).embed(audio.getvalue())

    assert len(embedding) == 192
    assert all(math.isfinite(value) for value in embedding)
