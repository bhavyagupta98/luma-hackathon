"""Copy the pinned speaker model into its runtime folder so Windows needs no symlink privilege.

SpeechBrain links the model files into `<model>/.runtime/` with symlinks. A normal Windows
account cannot create symlinks (WinError 1314: "A required privilege is not held by the
client"), so loading the model fails. SpeechBrain skips linking when the file is already
present, so this copies the files there once. `.runtime/` is git-ignored and local.

    python scripts/prepare_model_runtime.py
"""

from __future__ import annotations

import shutil
from pathlib import Path

from luma_datacenter.config import voice_model_path

# (file in the model folder, name SpeechBrain looks for in .runtime/)
FILES = (
    ("hyperparams.yaml", "hyperparams.yaml"),
    ("embedding_model.ckpt", "embedding_model.ckpt"),
    ("mean_var_norm_emb.ckpt", "mean_var_norm_emb.ckpt"),
    ("classifier.ckpt", "classifier.ckpt"),
    ("label_encoder.txt", "label_encoder.ckpt"),
)


def main() -> None:
    model = Path(voice_model_path())
    runtime = model / ".runtime"
    runtime.mkdir(exist_ok=True)
    for source_name, target_name in FILES:
        source = model / source_name
        if not source.is_file():
            raise SystemExit(f"{source} is missing; run python scripts/download_voice_model.py")
        target = runtime / target_name
        if target.is_symlink():
            target.unlink()
        if not target.exists() or target.stat().st_size != source.stat().st_size:
            shutil.copyfile(source, target)
            print(f"copied {source_name} -> {target_name}")
    print(f"Model runtime ready in {runtime}")


if __name__ == "__main__":
    main()
