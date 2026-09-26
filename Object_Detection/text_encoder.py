"""
Text prompt encoder for YOLOE open-vocabulary object detection.
Extracts normalized semantic text embeddings using MobileCLIP text model with caching.
"""

from __future__ import annotations
from typing import List, Union, Dict, Optional
import numpy as np
import torch
from ultralytics import YOLO


class PromptTextEncoder:
    """
    Extracts and caches text positional embeddings for YOLOE models.
    """
    def __init__(self, model_or_path: Union[str, YOLO] = "yoloe-26l-seg.pt", device: str = "cpu"):
        self.device = device
        if isinstance(model_or_path, YOLO):
            self.model = model_or_path
        else:
            self.model = YOLO(str(model_or_path))
        
        self.embed_dim = 512
        self._cache: Dict[tuple, np.ndarray] = {}

    def encode(self, classes: List[str], to_numpy: bool = True) -> Union[np.ndarray, torch.Tensor]:
        """
        Encodes a list of class names into a text feature tensor of shape [1, num_classes, 512].
        Args:
            classes: List of prompt strings, e.g. ["person", "backpack", "shoes"]
            to_numpy: If True returns numpy array, else torch.Tensor
        Returns:
            Embeddings of shape [1, len(classes), 512]
        """
        assert len(classes) > 0, "En az bir sınıf ismi belirtilmelidir."
        
        cache_key = tuple(classes)
        if cache_key in self._cache:
            cached = self._cache[cache_key]
            return cached.copy() if to_numpy else torch.from_numpy(cached)

        # without_reprta=True: YOLOE contrastive adapter layer (reprta) is kept inside the exported ONNX model
        with torch.no_grad():
            pe = self.model.model.get_text_pe(classes, without_reprta=True)
            if isinstance(pe, torch.Tensor):
                pe_np = pe.detach().cpu().numpy().astype(np.float32)
            else:
                pe_np = np.asarray(pe, dtype=np.float32)

        # Cache the result
        self._cache[cache_key] = pe_np

        if to_numpy:
            return pe_np.copy()
        return torch.from_numpy(pe_np)

    def clear_cache(self) -> None:
        """Clears cached embeddings."""
        self._cache.clear()

    @property
    def cache_size(self) -> int:
        return len(self._cache)
