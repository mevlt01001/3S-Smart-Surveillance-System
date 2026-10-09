"""
Torch-free text-embedding provider for YOLOE open-vocabulary prompts.

Embeddings for a class list never change for a given text model, so they are cached
in memory and on disk. On a cache miss the MobileCLIP text tower is run in a short-lived
helper process: the long-running service (web backend) never has to load torch itself,
and a class list that was seen once costs nothing on later runs.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

_PKG_DIR = Path(__file__).resolve().parent
CACHE_DIR = Path(os.getenv("AEGIS_TEXT_FEAT_CACHE") or (_PKG_DIR / ".text_feat_cache"))


def resolve_model_path(model_path) -> Path:
    """Resolves a weights path given relative to either the CWD or the project root."""
    p = Path(model_path)
    if p.is_absolute() or p.exists():
        return p
    candidate = _PKG_DIR.parent / p
    return candidate if candidate.exists() else p


class CachedTextEncoder:
    """Drop-in replacement for PromptTextEncoder.encode() that avoids importing torch in-process."""

    embed_dim = 512

    def __init__(self, model_path="yoloe-26l-seg.pt", device: str = "cpu", timeout: float = 180.0):
        self.model_path = resolve_model_path(model_path)
        self.device = device
        self.timeout = timeout
        self._cache: Dict[tuple, np.ndarray] = {}
        self._lock = threading.Lock()
        self._inprocess_encoder = None

    def _disk_path(self, classes: List[str]) -> Path:
        try:
            stat = self.model_path.stat()
            model_tag = f"{self.model_path.name}:{stat.st_size}:{int(stat.st_mtime)}"
        except OSError:
            model_tag = self.model_path.name
        digest = hashlib.sha1(json.dumps([model_tag, list(classes)], ensure_ascii=False).encode("utf-8")).hexdigest()
        return CACHE_DIR / f"{digest}.npy"

    def encode(self, classes: List[str], to_numpy: bool = True):
        assert len(classes) > 0, "En az bir sınıf ismi belirtilmelidir."
        key = tuple(classes)
        with self._lock:
            feats = self._cache.get(key)
            if feats is None:
                feats = self._load_or_compute(list(classes))
                self._cache[key] = feats
        if to_numpy:
            return feats.copy()
        import torch  # only reached by callers that explicitly ask for tensors
        return torch.from_numpy(feats)

    def _load_or_compute(self, classes: List[str]) -> np.ndarray:
        path = self._disk_path(classes)
        if path.exists():
            try:
                feats = np.load(path)
                if feats.ndim == 3 and feats.shape[1] == len(classes):
                    return feats.astype(np.float32)
            except Exception:
                pass

        feats = self._compute_in_subprocess(classes, path)
        if feats is None:
            feats = self._compute_in_process(classes)
            try:
                CACHE_DIR.mkdir(parents=True, exist_ok=True)
                tmp = path.with_suffix(f".{os.getpid()}.tmp.npy")
                np.save(tmp, feats)
                os.replace(tmp, path)
            except Exception:
                pass
        return feats

    def _compute_in_subprocess(self, classes: List[str], out_path: Path) -> Optional[np.ndarray]:
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            env = dict(os.environ)
            env["PYTHONPATH"] = os.pathsep.join([str(_PKG_DIR.parent), env.get("PYTHONPATH", "")])
            proc = subprocess.run(
                [sys.executable, "-m", "Object_Detection.text_feature_cache",
                 str(self.model_path), str(out_path), json.dumps(list(classes), ensure_ascii=False)],
                capture_output=True, text=True, timeout=self.timeout, env=env, cwd=str(_PKG_DIR.parent),
            )
            if proc.returncode == 0 and out_path.exists():
                return np.load(out_path).astype(np.float32)
            print(f"[CachedTextEncoder] Yardımcı süreç başarısız ({proc.returncode}): {proc.stderr.strip()[-400:]}")
        except Exception as e:
            print(f"[CachedTextEncoder] Yardımcı süreç çalıştırılamadı: {e}")
        return None

    def _compute_in_process(self, classes: List[str]) -> np.ndarray:
        if self._inprocess_encoder is None:
            from .text_encoder import PromptTextEncoder
            self._inprocess_encoder = PromptTextEncoder(str(self.model_path), device=self.device)
        return self._inprocess_encoder.encode(classes, to_numpy=True).astype(np.float32)

    def clear_cache(self) -> None:
        self._cache.clear()

    @property
    def cache_size(self) -> int:
        return len(self._cache)


def _main(argv: List[str]) -> int:
    model_path, out_path, classes_json = argv[1], Path(argv[2]), argv[3]
    classes = json.loads(classes_json)
    from Object_Detection.text_encoder import PromptTextEncoder
    feats = PromptTextEncoder(model_path, device="cpu").encode(classes, to_numpy=True).astype(np.float32)
    tmp = out_path.with_suffix(f".{os.getpid()}.tmp.npy")
    np.save(tmp, feats)
    os.replace(tmp, out_path)
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
