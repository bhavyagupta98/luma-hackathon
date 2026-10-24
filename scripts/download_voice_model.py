from __future__ import annotations

import hashlib
from pathlib import Path

from huggingface_hub import hf_hub_download

REPOSITORY = "speechbrain/spkrec-ecapa-voxceleb"
REVISION = "0f99f2d0ebe89ac095bcc5903c4dd8f72b367286"
FILES = {
    "hyperparams.yaml": None,
    "embedding_model.ckpt": "0575cb64845e6b9a10db9bcb74d5ac32b326b8dc90352671d345e2ee3d0126a2",
    "mean_var_norm_emb.ckpt": None,
    "classifier.ckpt": "fd9e3634fe68bd0a427c95e354c0c677374f62b3f434e45b78599950d860d535",
    "label_encoder.txt": None,
}
DESTINATION = Path(__file__).resolve().parents[1] / "models" / "speechbrain-spkrec-ecapa-voxceleb"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as model_file:
        for chunk in iter(lambda: model_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    DESTINATION.mkdir(parents=True, exist_ok=True)
    for filename, expected_hash in FILES.items():
        downloaded = Path(
            hf_hub_download(
                repo_id=REPOSITORY,
                filename=filename,
                revision=REVISION,
                local_dir=DESTINATION,
            )
        )
        if expected_hash is not None and sha256(downloaded) != expected_hash:
            raise RuntimeError(f"Checksum mismatch for {filename}")
        print(f"ready: {downloaded.relative_to(DESTINATION.parent.parent)}")


if __name__ == "__main__":
    main()
