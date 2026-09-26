"""
NVIDIA Triton Inference Server backend for decoupled YOLOE models.
Supports communicating with Triton over HTTP/REST or gRPC.
"""

from __future__ import annotations
from typing import Union, Optional, List
import numpy as np

try:
    import tritonclient.http as httpclient
    TRITON_HTTP_AVAILABLE = True
except (ImportError, RuntimeError):
    httpclient = None
    TRITON_HTTP_AVAILABLE = False

try:
    import tritonclient.grpc as grpcclient
    TRITON_GRPC_AVAILABLE = True
except (ImportError, RuntimeError):
    grpcclient = None
    TRITON_GRPC_AVAILABLE = False



class TritonBackend:
    """
    Client backend that sends inference requests to a remote or local NVIDIA Triton Server.
    """
    def __init__(
        self,
        url: str = "localhost:8000",
        model_name: str = "yoloe_detector",
        model_version: str = "1",
        protocol: str = "http",
        verbose: bool = False,
        network_timeout: float = 300.0,
        connection_timeout: float = 60.0,
    ):
        self.url = url
        self.model_name = model_name
        self.model_version = model_version
        self.protocol = protocol.lower()

        if self.protocol == "http":
            if not TRITON_HTTP_AVAILABLE:
                raise ImportError("tritonclient[http] kurulu değil. 'pip install tritonclient[http]' çalıştırın.")
            self.client = httpclient.InferenceServerClient(
                url=self.url,
                verbose=verbose,
                network_timeout=network_timeout,
                connection_timeout=connection_timeout,
            )
            self._InferInput = httpclient.InferInput
            self._InferRequestedOutput = httpclient.InferRequestedOutput
        elif self.protocol == "grpc":
            if not TRITON_GRPC_AVAILABLE:
                raise ImportError("tritonclient[grpc] kurulu değil. 'pip install tritonclient[grpc]' çalıştırın.")
            self.client = grpcclient.InferenceServerClient(url=self.url, verbose=verbose)
            self._InferInput = grpcclient.InferInput
            self._InferRequestedOutput = grpcclient.InferRequestedOutput
        else:
            raise ValueError(f"Geçersiz protokol: {self.protocol}. 'http' veya 'grpc' olmalıdır.")

    def is_alive(self) -> bool:
        """Checks if the Triton server is online."""
        try:
            return self.client.is_server_live()
        except Exception:
            return False

    def is_model_ready(self) -> bool:
        """Checks if the YOLOE model is loaded and ready on Triton."""
        try:
            return self.client.is_model_ready(model_name=self.model_name, model_version=self.model_version)
        except Exception:
            return False

    def infer(self, images: np.ndarray, text_feats: np.ndarray) -> np.ndarray:
        """
        Sends images and text features to Triton Inference Server.
        
        Args:
            images: [batch, 3, 640, 640] float32 array
            text_feats: [batch, num_classes, 512] float32 array
            
        Returns:
            outputs: [batch, 4 + num_classes, 8400] float32 array
        """
        assert images.ndim == 4, f"images boyutu 4D olmalıdır: {images.shape}"
        assert text_feats.ndim == 3, f"text_feats boyutu 3D olmalıdır: {text_feats.shape}"

        # Broadcast batch dimension if needed
        if text_feats.shape[0] != images.shape[0]:
            text_feats = np.repeat(text_feats, images.shape[0], axis=0)

        images = np.ascontiguousarray(images, dtype=np.float32)
        text_feats = np.ascontiguousarray(text_feats, dtype=np.float32)

        # 1. Inputs
        inp_img = self._InferInput("images", images.shape, "FP32")
        inp_img.set_data_from_numpy(images)

        inp_txt = self._InferInput("text_feats", text_feats.shape, "FP32")
        inp_txt.set_data_from_numpy(text_feats)

        # 2. Outputs
        out_req = self._InferRequestedOutput("outputs")

        # 3. Request
        response = self.client.infer(
            model_name=self.model_name,
            model_version=self.model_version,
            inputs=[inp_img, inp_txt],
            outputs=[out_req],
        )

        return response.as_numpy("outputs")
