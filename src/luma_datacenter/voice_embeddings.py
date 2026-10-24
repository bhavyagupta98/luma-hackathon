from __future__ import annotations

import io
import math
import threading
import wave
from array import array
from pathlib import Path
from typing import Protocol


class VoiceEmbeddingError(ValueError):
    pass


class VoiceEmbedder(Protocol):
    model_name: str

    def embed(self, audio: bytes) -> list[float]: ...


class SpeechBrainECAPAEmbedder:
    """Lazy local ECAPA-TDNN embedding inference for short PCM WAV clips."""

    model_name = "speechbrain/spkrec-ecapa-voxceleb@0f99f2d"

    def __init__(self, model_path: str | Path) -> None:
        self.model_path = Path(model_path)
        self._classifier = None
        self._lock = threading.Lock()

    def embed(self, audio: bytes) -> list[float]:
        waveform, sample_rate = self._decode_wav(audio)
        try:
            classifier = self._get_classifier()

            import torch
            import torchaudio.functional as audio_functions

            signal = torch.tensor(waveform, dtype=torch.float32).unsqueeze(0)
            if sample_rate != 16_000:
                signal = audio_functions.resample(signal, sample_rate, 16_000)
            with torch.inference_mode():
                embedding = classifier.encode_batch(signal, normalize=True)
            values = embedding.squeeze().detach().cpu().tolist()
        except VoiceEmbeddingError:
            raise
        except Exception as exc:
            raise VoiceEmbeddingError(
                "I can't verify your voice because the voice service is unavailable."
            ) from exc
        if not isinstance(values, list) or not values or not all(math.isfinite(v) for v in values):
            raise VoiceEmbeddingError("The voice model produced an invalid embedding")
        return [float(value) for value in values]

    def _get_classifier(self):
        if self._classifier is not None:
            return self._classifier
        with self._lock:
            if self._classifier is None:
                required = (
                    "hyperparams.yaml",
                    "embedding_model.ckpt",
                    "mean_var_norm_emb.ckpt",
                    "classifier.ckpt",
                    "label_encoder.txt",
                )
                missing = [name for name in required if not (self.model_path / name).is_file()]
                if missing:
                    raise VoiceEmbeddingError(
                        "Local voice model is incomplete; missing: " + ", ".join(missing)
                    )
                from speechbrain.inference.speaker import EncoderClassifier

                self._classifier = EncoderClassifier.from_hparams(
                    source=str(self.model_path),
                    savedir=str(self.model_path / ".runtime"),
                    overrides={"pretrained_path": str(self.model_path.resolve())},
                    run_opts={"device": "cpu"},
                )
        return self._classifier

    @staticmethod
    def _decode_wav(audio: bytes) -> tuple[list[float], int]:
        try:
            with wave.open(io.BytesIO(audio), "rb") as wav_file:
                channels = wav_file.getnchannels()
                sample_width = wav_file.getsampwidth()
                sample_rate = wav_file.getframerate()
                frame_count = wav_file.getnframes()
                frames = wav_file.readframes(frame_count)
        except (EOFError, wave.Error) as exc:
            raise VoiceEmbeddingError("Audio must be a valid PCM WAV recording") from exc

        if sample_width != 2:
            raise VoiceEmbeddingError("Audio must use 16-bit PCM samples")
        if channels not in (1, 2):
            raise VoiceEmbeddingError("Audio must be mono or stereo")
        duration = frame_count / sample_rate if sample_rate else 0
        if duration < 1 or duration > 15:
            raise VoiceEmbeddingError("Audio must be between 1 and 15 seconds long")

        samples = array("h")
        samples.frombytes(frames)
        if channels == 2:
            mono = [
                (samples[index] + samples[index + 1]) / 65_536
                for index in range(0, len(samples), 2)
            ]
        else:
            mono = [sample / 32_768 for sample in samples]
        return mono, sample_rate
