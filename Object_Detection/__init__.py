"""
Object_Detection Package: Decoupled Open-Vocabulary Object Detection for TensorRT & ONNX.

The public API is unchanged, but heavyweight members (anything that pulls in torch /
ultralytics / tensorrt) are imported lazily on first access. Importing the package for
Triton-based inference therefore costs a few MB instead of ~650 MB of RSS.
"""

from importlib import import_module

from .detector import YOLODetector
from .utils import DetectionResult, DetectionBox, letterbox, preprocess_image, postprocess_detections
from .triton_backend import TritonBackend

_LAZY_ATTRS = {
    "PromptTextEncoder": ".text_encoder",
    "DecoupledYOLOE": ".decoupled_model",
    "export_decoupled_onnx": ".decoupled_model",
    "is_tensorrt_available": ".trt_backend",
    "TensorRTBackend": ".trt_backend",
    "get_trtexec_command": ".trt_backend",
    "build_engine_from_onnx": ".trt_backend",
    "ONNXBackend": ".onnx_backend",
}


def __getattr__(name):
    module_name = _LAZY_ATTRS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module_name, __name__), name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(list(globals().keys()) + list(_LAZY_ATTRS.keys()))


__all__ = [
    "YOLODetector",
    "DetectionResult",
    "DetectionBox",
    "PromptTextEncoder",
    "DecoupledYOLOE",
    "export_decoupled_onnx",
    "is_tensorrt_available",
    "TensorRTBackend",
    "ONNXBackend",
    "TritonBackend",
    "get_trtexec_command",
    "build_engine_from_onnx",
    "letterbox",
    "preprocess_image",
    "postprocess_detections",
]
