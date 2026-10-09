"""
Minimal zero-copy HTTP client for NVIDIA Triton (KServe v2 protocol, binary tensor extension).

`tritonclient.http` serializes every request by copying the tensor (`tobytes()`) and pushing
it through a gevent HTTP stack. For the large tensors of this project (a 4-camera anomaly
batch is 38 MB) that costs ~75 ms of client CPU per call while holding the GIL, which is
stolen from the video threads. This client streams the NumPy buffer straight to the socket
over a persistent connection (~10 ms CPU for the same request) using only the standard library.
"""

from __future__ import annotations

import http.client
import json
import socket
import threading
from typing import Dict, List, Optional

import numpy as np

_DTYPE_TO_TRITON = {
    np.dtype(np.float32): "FP32",
    np.dtype(np.float16): "FP16",
    np.dtype(np.float64): "FP64",
    np.dtype(np.uint8): "UINT8",
    np.dtype(np.int8): "INT8",
    np.dtype(np.int32): "INT32",
    np.dtype(np.int64): "INT64",
    np.dtype(np.bool_): "BOOL",
}
_TRITON_TO_DTYPE = {v: k for k, v in _DTYPE_TO_TRITON.items()}


class TritonError(RuntimeError):
    pass


class TritonFastClient:
    def __init__(self, url: str = "localhost:8000", timeout: float = 10.0, connect_timeout: float = 3.0):
        for prefix in ("http://", "https://"):
            if url.lower().startswith(prefix):
                url = url[len(prefix):]
        url = url.rstrip("/")
        host, _, port = url.partition(":")
        self.host = host or "localhost"
        self.port = int(port) if port else 8000
        self.timeout = timeout
        self.connect_timeout = connect_timeout
        self._conn: Optional[http.client.HTTPConnection] = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------ connection
    def _connection(self) -> http.client.HTTPConnection:
        if self._conn is None:
            conn = http.client.HTTPConnection(self.host, self.port, timeout=self.connect_timeout)
            conn.connect()
            conn.sock.settimeout(self.timeout)
            try:
                conn.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            except OSError:
                pass
            self._conn = conn
        return self._conn

    def close(self):
        with self._lock:
            self._close_locked()

    def _close_locked(self):
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    # ---------------------------------------------------------------- health
    def _get_status(self, path: str) -> int:
        with self._lock:
            try:
                conn = self._connection()
                conn.request("GET", path)
                resp = conn.getresponse()
                resp.read()
                return resp.status
            except Exception:
                self._close_locked()
                raise

    def is_server_live(self) -> bool:
        try:
            return self._get_status("/v2/health/live") == 200
        except Exception:
            return False

    def is_model_ready(self, model_name: str, model_version: str = "") -> bool:
        path = f"/v2/models/{model_name}" + (f"/versions/{model_version}" if model_version else "") + "/ready"
        try:
            return self._get_status(path) == 200
        except Exception:
            return False

    # ------------------------------------------------------------- inference
    def infer(
        self,
        model_name: str,
        inputs: Dict[str, np.ndarray],
        outputs: List[str],
        model_version: str = "",
    ) -> Dict[str, np.ndarray]:
        """Runs one inference. `inputs` maps tensor names to C-contiguous arrays; returns name -> array."""
        in_meta = []
        buffers = []
        total = 0
        for name, arr in inputs.items():
            arr = np.ascontiguousarray(arr)
            dtype = _DTYPE_TO_TRITON.get(arr.dtype)
            if dtype is None:
                raise TritonError(f"Unsupported input dtype for '{name}': {arr.dtype}")
            in_meta.append({
                "name": name,
                "shape": list(arr.shape),
                "datatype": dtype,
                "parameters": {"binary_data_size": arr.nbytes},
            })
            buffers.append(memoryview(arr).cast("B"))
            total += arr.nbytes

        header = json.dumps({
            "inputs": in_meta,
            "outputs": [{"name": n, "parameters": {"binary_data": True}} for n in outputs],
        }).encode("utf-8")
        path = f"/v2/models/{model_name}" + (f"/versions/{model_version}" if model_version else "") + "/infer"

        with self._lock:
            try:
                conn = self._connection()
                conn.putrequest("POST", path)
                conn.putheader("Content-Type", "application/octet-stream")
                conn.putheader("Inference-Header-Content-Length", str(len(header)))
                conn.putheader("Content-Length", str(len(header) + total))
                conn.endheaders()
                conn.send(header)
                for buf in buffers:
                    conn.send(buf)  # zero-copy: the socket reads straight from the NumPy buffer
                resp = conn.getresponse()
                body = resp.read()
                header_len = resp.getheader("Inference-Header-Content-Length")
                status = resp.status
            except Exception:
                self._close_locked()
                raise

        if status != 200:
            try:
                message = json.loads(body.decode("utf-8", "replace")).get("error", "")
            except Exception:
                message = body[:200].decode("utf-8", "replace")
            raise TritonError(f"Triton inference failed ({status}): {message}")

        hlen = int(header_len) if header_len else len(body)
        meta = json.loads(body[:hlen].decode("utf-8"))
        result: Dict[str, np.ndarray] = {}
        offset = hlen
        for out in meta.get("outputs", []):
            dtype = _TRITON_TO_DTYPE.get(out.get("datatype"))
            shape = out.get("shape", [])
            size = (out.get("parameters") or {}).get("binary_data_size")
            if size is not None and dtype is not None:
                result[out["name"]] = np.frombuffer(body, dtype=dtype, count=size // dtype.itemsize, offset=offset).reshape(shape)
                offset += size
            elif "data" in out and dtype is not None:
                result[out["name"]] = np.asarray(out["data"], dtype=dtype).reshape(shape)
        return result
