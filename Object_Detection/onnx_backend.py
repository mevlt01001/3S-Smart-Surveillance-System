"""
ONNXRuntime execution backend for decoupled YOLOE models.
Supports dynamic batch and dynamic number of classes.
"""

from __future__ import annotations
from pathlib import Path
from typing import Union, List, Optional
import numpy as np
import onnxruntime as ort


class ONNXBackend:
    """
    Manages ONNXRuntime inference session for decoupled YOLOE models.
    """
    def __init__(
        self,
        onnx_path: Union[str, Path],
        device: str = "cuda",
        providers: Optional[List[str]] = None,
    ):
        self.onnx_path = str(onnx_path)
        if not Path(self.onnx_path).is_file():
            raise FileNotFoundError(f"ONNX modeli bulunamadı: {self.onnx_path}")

        available_providers = ort.get_available_providers()

        if providers is None:
            if device.lower() in ("cuda", "gpu") and "CUDAExecutionProvider" in available_providers:
                providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
            elif "TensorrtExecutionProvider" in available_providers:
                providers = ["TensorrtExecutionProvider", "CUDAExecutionProvider", "CPUExecutionProvider"]
            else:
                providers = ["CPUExecutionProvider"]

        # Filter out unavailable providers
        valid_providers = [p for p in providers if p in available_providers]
        if not valid_providers:
            valid_providers = ["CPUExecutionProvider"]

        self.session = ort.InferenceSession(self.onnx_path, providers=valid_providers)
        self.active_providers = self.session.get_providers()

        self.input_names = [i.name for i in self.session.get_inputs()]
        self.output_names = [o.name for o in self.session.get_outputs()]

    def infer(self, images: np.ndarray, text_feats: np.ndarray, model_name=None) -> np.ndarray:
        """
        Runs inference on preprocessed images and text features.
        
        Args:
            images: [batch, 3, H, W] float32 array
            text_feats: [batch, num_classes, 512] float32 array
            
        Returns:
            outputs: [batch, 4 + num_classes, num_anchors] float32 array

        `model_name` is accepted for interface parity with the Triton backend (a local
        backend serves exactly one model) and is ignored.
        """
        assert images.ndim == 4, f"images shape must be 4D [B, 3, H, W], got {images.shape}"
        assert text_feats.ndim == 3, f"text_feats shape must be 3D [B, K, 512], got {text_feats.shape}"

        # If text_feats has batch=1 and images has batch > 1, repeat text_feats
        if text_feats.shape[0] != images.shape[0]:
            text_feats = np.repeat(text_feats, images.shape[0], axis=0)

        feeds = {
            self.input_names[0]: images.astype(np.float32),
            self.input_names[1]: text_feats.astype(np.float32),
        }

        outputs = self.session.run(self.output_names, feeds)
        return outputs[0]
