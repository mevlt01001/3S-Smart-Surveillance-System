"""
Unified YOLODetector class for open-vocabulary object detection.
Supports both TensorRT engine and ONNXRuntime backends with dynamic text prompts.
"""

from __future__ import annotations
from pathlib import Path
from typing import Union, List, Optional, Tuple, Dict, Any
import numpy as np

from .utils import preprocess_image, postprocess_detections, DetectionResult, DetectionBox
from .text_encoder import PromptTextEncoder
from .onnx_backend import ONNXBackend
from .trt_backend import TensorRTBackend, is_tensorrt_available, get_trtexec_command, build_engine_from_onnx
from .triton_backend import TritonBackend
from .decoupled_model import export_decoupled_onnx


class YOLODetector:
    """
    Main Object Detection class.
    
    Can be initialized with:
    - an NVIDIA Triton Server (backend="triton", triton_url="localhost:8000")
    - a TensorRT engine (.engine)
    - a decoupled ONNX model (.onnx)
    - an Ultralytics PyTorch model (.pt) - auto-exports to decoupled ONNX if needed.
    
    Allows changing detection prompts dynamically at runtime with ZERO engine recompilation.
    """
    def __init__(
        self,
        model_path: Union[str, Path] = "yoloe-26l-seg_decoupled_sim.onnx",
        text_model_path: Union[str, Path] = "yoloe-26l-seg.pt",
        classes: Optional[List[str]] = None,
        device: str = "cuda",
        conf_thres: float = 0.20,
        iou_thres: float = 0.45,
        imgsz: int = 640,
        backend: Optional[str] = None,
        triton_url: str = "localhost:8000",
        triton_model_name: str = "yoloe_detector",
        triton_protocol: str = "http",
    ):
        self.model_path = Path(model_path)
        self.text_model_path = Path(text_model_path)
        self.device = device
        self.conf_thres = conf_thres
        self.iou_thres = iou_thres
        self.imgsz = imgsz
        self.triton_url = triton_url
        self.triton_model_name = triton_model_name
        self.triton_protocol = triton_protocol

        # 1. Initialize text prompt encoder
        self.text_encoder = PromptTextEncoder(self.text_model_path, device="cpu")

        # 2. Select backend
        self.backend_type = backend.lower() if backend else None
        self.backend = None
        self._init_backend()

        # 3. Set initial classes if provided
        self.current_classes: List[str] = []
        self.current_text_feats: Optional[np.ndarray] = None
        if classes:
            self.set_classes(classes)

    def _init_backend(self):
        # 1. Auto selection mode
        if self.backend_type in ("auto", None):
            try:
                triton_candidate = TritonBackend(
                    url=self.triton_url,
                    model_name=self.triton_model_name,
                    protocol=self.triton_protocol,
                )
                if triton_candidate.is_alive():
                    self.backend = triton_candidate
                    self.backend_type = "triton"
                    print(f"[YOLODetector] Triton sunucusu ({self.triton_url}) aktif algılandı. Triton modu devrede.")
                    return
            except Exception:
                pass

        # 2. Explicit Triton backend
        if self.backend_type == "triton" or str(self.model_path).lower() in ("triton", "triton://"):
            self.backend = TritonBackend(
                url=self.triton_url,
                model_name=self.triton_model_name,
                protocol=self.triton_protocol,
            )
            self.backend_type = "triton"
            if not self.backend.is_alive():
                raise ConnectionError(
                    f"NVIDIA Triton sunucusuna ({self.triton_url}) bağlanılamadı. Sunucu şu an çevrimdışı.\n"
                    "Triton'u başlatmak için:\n"
                    "  ./Object_Detection/start_triton_docker.sh\n"
                    "Docker kurulu değilse kurulum için:\n"
                    "  sudo bash Object_Detection/install_docker_prerequisites.sh\n"
                    "Yerel çıkarım motorunu kullanmak için: YOLODetector(backend='auto') veya YOLODetector(backend='onnx')"
                )
            return

        suffix = self.model_path.suffix.lower()

        # Auto-export if a .pt file is provided and no onnx/engine exists
        if suffix == ".pt":
            onnx_target = self.model_path.with_name(f"{self.model_path.stem}_decoupled_sim.onnx")
            if not onnx_target.exists():
                print(f"[YOLODetector] .pt dosyası algılandı, decoupled ONNX oluşturuluyor: {onnx_target}")
                export_decoupled_onnx(self.model_path, output_path=onnx_target, imgsz=self.imgsz)
            self.model_path = onnx_target
            suffix = ".onnx"

        # Check if corresponding .engine exists when tensorrt is available
        potential_engine = self.model_path.with_suffix(".engine")
        if (suffix == ".engine" or (self.backend_type in ("auto", "tensorrt", None) and potential_engine.exists())) and is_tensorrt_available():
            engine_to_use = self.model_path if suffix == ".engine" else potential_engine
            self.backend = TensorRTBackend(engine_to_use, device=self.device)
            self.backend_type = "tensorrt"
            return

        if suffix == ".engine" or self.backend_type == "tensorrt":
            if not is_tensorrt_available():
                raise ImportError(
                    f"'{self.model_path}' bir TensorRT engine dosyasıdır ancak 'tensorrt' "
                    "Python kütüphanesi ortamda bulunamadı. Lütfen 'pip install tensorrt' kurun "
                    "veya ONNX modelini kullanın."
                )
            self.backend = TensorRTBackend(self.model_path, device=self.device)
            self.backend_type = "tensorrt"

        elif suffix == ".onnx" or self.backend_type in ("onnx", "auto", None):
            self.backend = ONNXBackend(self.model_path, device=self.device)
            self.backend_type = "onnx"

        else:
            raise ValueError(f"Desteklenmeyen model uzantısı: {suffix}. Lütfen .engine veya .onnx kullanın.")

    def set_classes(self, classes: List[str]) -> np.ndarray:
        """
        Dynamically updates the detection target classes.
        Extracts and caches the corresponding text features for the backend.
        
        Args:
            classes: List of object names to detect, e.g. ["person", "backpack", "shoes"]
        """
        assert len(classes) > 0, "En az bir sınıf ismi belirtilmelidir."
        self.current_classes = list(classes)
        self.current_text_feats = self.text_encoder.encode(self.current_classes, to_numpy=True)
        return self.current_text_feats

    def get_classes(self) -> List[str]:
        """Returns currently active classes."""
        return list(self.current_classes)

    def detect(
        self,
        source: Union[str, Path, np.ndarray, Any],
        classes: Optional[List[str]] = None,
        conf_thres: Optional[float] = None,
        iou_thres: Optional[float] = None,
    ) -> DetectionResult:
        """
        Runs object detection on the provided image with the current or overridden classes.
        
        Args:
            source: Image filepath, BGR numpy array, or PIL Image.
            classes: (Optional) Override current classes for this single inference.
            conf_thres: (Optional) Override confidence threshold.
            iou_thres: (Optional) Override NMS IoU threshold.
            
        Returns:
            DetectionResult instance with detected boxes, labels, and plotting helpers.
        """
        active_classes = classes if classes is not None else self.current_classes
        if not active_classes:
            raise ValueError("Tespit için hiçbir sınıf tanımlanmadı! Lütfen detector.set_classes(...) çağırın.")

        if classes is not None and classes != self.current_classes:
            text_feats = self.text_encoder.encode(active_classes, to_numpy=True)
        else:
            if self.current_text_feats is None:
                self.set_classes(active_classes)
            text_feats = self.current_text_feats

        conf = conf_thres if conf_thres is not None else self.conf_thres
        iou = iou_thres if iou_thres is not None else self.iou_thres

        # 1. Preprocess
        input_tensor, orig_img, orig_shape = preprocess_image(source, imgsz=self.imgsz)

        # 2. Run model backend inference
        raw_output = self.backend.infer(input_tensor, text_feats)

        # 3. Postprocess (NMS + coordinate scaling)
        boxes = postprocess_detections(
            raw_output,
            orig_shape=orig_shape,
            classes=active_classes,
            imgsz=self.imgsz,
            conf_thres=conf,
            iou_thres=iou,
        )

        return DetectionResult(orig_img=orig_img, boxes=boxes, classes=active_classes)

    def __call__(self, *args, **kwargs) -> DetectionResult:
        """Shorthand for detect()."""
        return self.detect(*args, **kwargs)

    def export_engine(
        self,
        engine_path: Union[str, Path] = "yoloe_decoupled.engine",
        fp16: bool = True,
        min_classes: int = 1,
        opt_classes: int = 5,
        max_classes: int = 80,
    ) -> bool:
        """
        Builds a TensorRT engine from the current ONNX model using trtexec if available.
        """
        onnx_file = self.model_path if self.model_path.suffix.lower() == ".onnx" else "yoloe_decoupled_sim.onnx"
        return build_engine_from_onnx(
            onnx_path=onnx_file,
            engine_path=engine_path,
            fp16=fp16,
            min_classes=min_classes,
            opt_classes=opt_classes,
            max_classes=max_classes,
            imgsz=self.imgsz,
        )

    def get_trtexec_cmd(
        self,
        engine_path: str = "yoloe_decoupled.engine",
        fp16: bool = True,
        min_classes: int = 1,
        opt_classes: int = 5,
        max_classes: int = 80,
    ) -> str:
        """Returns the trtexec shell command to build the TensorRT engine."""
        onnx_file = str(self.model_path) if self.model_path.suffix.lower() == ".onnx" else "yoloe_decoupled_sim.onnx"
        return get_trtexec_command(
            onnx_path=onnx_file,
            engine_path=engine_path,
            fp16=fp16,
            min_classes=min_classes,
            opt_classes=opt_classes,
            max_classes=max_classes,
            imgsz=self.imgsz,
        )
