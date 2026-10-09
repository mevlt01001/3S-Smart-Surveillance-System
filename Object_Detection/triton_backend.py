"""
NVIDIA Triton Inference Server backend for decoupled YOLOE models.
Supports communicating with Triton over HTTP/REST or gRPC.
"""

from __future__ import annotations
import time
from typing import Optional, List
import numpy as np

try:
    import tritonclient.http as httpclient
    TRITON_HTTP_AVAILABLE = True
except (ImportError, RuntimeError):
    httpclient = None
    TRITON_HTTP_AVAILABLE = False

from .triton_fast_client import TritonFastClient

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
        network_timeout: float = 10.0,
        connection_timeout: float = 3.0,
    ):
        self.url = url
        self.model_name = model_name
        self.model_version = model_version
        self.protocol = protocol.lower()
        # Smoothed round-trip latency of real requests; None until the first inference ran
        self.last_latency_ms: Optional[float] = None

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
            # Inference itself goes through the zero-copy client (tritonclient stays for admin calls)
            self._fast = TritonFastClient(self.url, timeout=network_timeout, connect_timeout=connection_timeout)
        elif self.protocol == "grpc":
            if not TRITON_GRPC_AVAILABLE:
                raise ImportError("tritonclient[grpc] kurulu değil. 'pip install tritonclient[grpc]' çalıştırın.")
            self.client = grpcclient.InferenceServerClient(url=self.url, verbose=verbose)
            self._fast = None
            self._InferInput = grpcclient.InferInput
            self._InferRequestedOutput = grpcclient.InferRequestedOutput
        else:
            raise ValueError(f"Geçersiz protokol: {self.protocol}. 'http' veya 'grpc' olmalıdır.")

    def _record_latency(self, lat_ms: float) -> None:
        prev = self.last_latency_ms
        self.last_latency_ms = round(lat_ms if prev is None else 0.25 * lat_ms + 0.75 * prev, 1)

    def is_alive(self) -> bool:
        """Checks if the Triton server is online."""
        try:
            return self.client.is_server_live()
        except Exception:
            return False

    def is_model_ready(self, model_name: Optional[str] = None) -> bool:
        """Checks if the requested model is loaded and ready on Triton."""
        m_name = model_name or self.model_name
        try:
            return self.client.is_model_ready(model_name=m_name, model_version=self.model_version)
        except Exception:
            return False

    def get_ready_models(self) -> List[str]:
        """Returns a list of all models currently READY on the Triton server."""
        try:
            if hasattr(self.client, "get_model_repository_index"):
                index = self.client.get_model_repository_index()
                return [m.get("name") for m in index if m.get("state") == "READY"]
        except Exception:
            pass
        # Fallback check standard models
        ready = []
        for name in ["safety_detector", "coco_detector", "yoloe_detector", "anomaly_detector"]:
            if self.is_model_ready(name):
                ready.append(name)
        return ready

    def infer(
        self,
        images: np.ndarray,
        text_feats: Optional[np.ndarray] = None,
        model_name: Optional[str] = None,
    ) -> np.ndarray:
        """
        Sends inference requests to Triton Inference Server.
        Supports:
          - safety_detector: images -> output0
          - coco_detector: images -> output0
          - yoloe_detector: images + text_feats -> outputs

        Args:
            images: [batch, 3, 640, 640] float32 array
            text_feats: (Optional for YOLOE) [batch, num_classes, 512] float32 array
            model_name: (Optional) Override target model name

        Returns:
            outputs: [batch, channels, anchors] float32 array
        """
        target_model = (model_name or self.model_name).strip()
        assert images.ndim == 4, f"images boyutu 4D olmalıdır: {images.shape}"
        images = np.ascontiguousarray(images, dtype=np.float32)

        # 1. safety_detector or coco_detector (Pure Vision YOLO Models)
        if target_model in ("safety_detector", "coco_detector") or text_feats is None:
            if self._fast is not None:
                t0 = time.perf_counter()
                out = self._fast.infer(target_model, {"images": images}, ["output0"], model_version=self.model_version)
                self._record_latency((time.perf_counter() - t0) * 1000.0)
                return out["output0"]

            inp_img = self._InferInput("images", images.shape, "FP32")
            inp_img.set_data_from_numpy(images)

            out_req = self._InferRequestedOutput("output0")

            t0 = time.perf_counter()
            response = self.client.infer(
                model_name=target_model,
                model_version=self.model_version,
                inputs=[inp_img],
                outputs=[out_req],
            )
            lat_ms = (time.perf_counter() - t0) * 1000.0
            self._record_latency(lat_ms)
            return response.as_numpy("output0")

        # 2. yoloe_detector (Decoupled Open-Vocabulary Model)
        assert text_feats.ndim == 3, f"text_feats boyutu 3D olmalıdır: {text_feats.shape}"

        # Broadcast batch dimension if needed
        if text_feats.shape[0] != images.shape[0]:
            text_feats = np.repeat(text_feats, images.shape[0], axis=0)

        text_feats = np.ascontiguousarray(text_feats, dtype=np.float32)

        if self._fast is not None:
            t0 = time.perf_counter()
            out = self._fast.infer(
                target_model, {"images": images, "text_feats": text_feats}, ["outputs"],
                model_version=self.model_version,
            )
            self._record_latency((time.perf_counter() - t0) * 1000.0)
            return out["outputs"]

        inp_img = self._InferInput("images", images.shape, "FP32")
        inp_img.set_data_from_numpy(images)

        inp_txt = self._InferInput("text_feats", text_feats.shape, "FP32")
        inp_txt.set_data_from_numpy(text_feats)

        out_req = self._InferRequestedOutput("outputs")

        t0 = time.perf_counter()
        response = self.client.infer(
            model_name=target_model,
            model_version=self.model_version,
            inputs=[inp_img, inp_txt],
            outputs=[out_req],
        )
        lat_ms = (time.perf_counter() - t0) * 1000.0
        self._record_latency(lat_ms)

        return response.as_numpy("outputs")

