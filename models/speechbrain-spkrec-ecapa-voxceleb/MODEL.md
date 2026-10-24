# Local Speaker Verification Model

- Upstream: `speechbrain/spkrec-ecapa-voxceleb`
- Revision: `0f99f2d0ebe89ac095bcc5903c4dd8f72b367286`
- Architecture: ECAPA-TDNN
- License declared upstream: Apache-2.0
- Intended use here: demo speaker embeddings and verification

Run `python scripts/download_voice_model.py` to fetch the pinned files and
verify the large checkpoint hashes. The application never downloads a model at
runtime; it fails closed when the local model directory is incomplete.

This model is not liveness detection and is not sufficient as production-grade
authentication. Its threshold must be evaluated using representative workers,
microphones, accents, background noise, and adversarial replay samples.
