"""
Unified YOLODetector class for open-vocabulary object detection.
Supports both TensorRT engine and ONNXRuntime backends with dynamic text prompts.
"""

from __future__ import annotations
from pathlib import Path
from typing import Union, List, Optional, Any, Set
import numpy as np

from .utils import preprocess_image, postprocess_detections, DetectionResult
from .triton_backend import TritonBackend
from .text_feature_cache import CachedTextEncoder

# torch / ultralytics / onnxruntime / tensorrt backed modules (text_encoder, onnx_backend,
# trt_backend, decoupled_model) are imported lazily inside the code paths that need them,
# so a Triton-only deployment never loads them.


SAFETY_CLASSES = [
    "Hardhat", "Mask", "NO-Hardhat", "NO-Mask", "NO-Safety Vest",
    "Person", "Safety Cone", "Safety Vest", "machinery", "vehicle"
]

COCO_CLASSES = [
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck", "boat",
    "traffic light", "fire hydrant", "stop sign", "parking meter", "bench", "bird", "cat",
    "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra", "giraffe", "backpack",
    "umbrella", "handbag", "tie", "suitcase", "frisbee", "skis", "snowboard", "sports ball",
    "kite", "baseball bat", "baseball glove", "skateboard", "surfboard", "tennis racket",
    "bottle", "wine glass", "cup", "fork", "knife", "spoon", "bowl", "banana", "apple",
    "sandwich", "orange", "broccoli", "carrot", "hot dog", "pizza", "donut", "cake",
    "chair", "couch", "potted plant", "bed", "dining table", "toilet", "tv", "laptop",
    "mouse", "remote", "keyboard", "cell phone", "microwave", "oven", "toaster", "sink",
    "refrigerator", "book", "clock", "vase", "scissors", "teddy bear", "hair drier", "toothbrush"
]


class YOLODetector:
    """
    Main Multi-Model Object Detection class with NVIDIA Triton support.
    
    Can route inference dynamically to:
    1. 'safety_detector': Specialized Construction & PPE model (10 classes)
    2. 'coco_detector': General COCO 80-class model
    3. 'yoloe_detector': Open-vocabulary decoupled model with 4-5 sub-class expansion
    
    Allows changing detection prompts dynamically at runtime with ZERO engine recompilation.
    """
    def __init__(
        self,
        model_path: Union[str, Path] = "yoloe-26l-seg_decoupled_sim.onnx",
        text_model_path: Union[str, Path] = "yoloe-26l-seg.pt",
        classes: Optional[List[str]] = None,
        device: str = "cuda",
        conf_thres: float = 0.25,
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

        # 1. Text prompt encoder for open-vocabulary detection.
        #    Created lazily and backed by a disk cache: the YOLOE text tower is only
        #    loaded (in a helper process) the first time a new class list is requested.
        self._text_encoder = None

        # 2. Select backend
        self.backend_type = backend.lower() if backend else None
        self.backend = None
        self._init_backend()

        # 3. Set initial classes if provided
        self.current_classes: List[str] = []
        self.current_text_feats: Optional[np.ndarray] = None
        if classes:
            self.set_classes(classes)

    @property
    def text_encoder(self):
        if self._text_encoder is None:
            self._text_encoder = CachedTextEncoder(self.text_model_path, device="cpu")
        return self._text_encoder

    @text_encoder.setter
    def text_encoder(self, value):
        self._text_encoder = value

    def reconnect(self) -> bool:
        """Re-creates the inference backend (e.g. after Triton restarted) keeping caches intact."""
        try:
            self._init_backend()
            return bool(self.backend and self.backend.is_alive())
        except Exception:
            return False

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
                    ready_models = triton_candidate.get_ready_models()
                    print(f"[YOLODetector] Triton sunucusu ({self.triton_url}) aktif. Hazır Modeller: {ready_models}")
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
                    "Yerel çıkarım motorunu kullanmak için: YOLODetector(backend='auto') veya YOLODetector(backend='onnx')"
                )
            return

        from .onnx_backend import ONNXBackend
        from .trt_backend import TensorRTBackend, is_tensorrt_available
        from .decoupled_model import export_decoupled_onnx

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
                    "Python kütüphanesi ortamda bulunamadı."
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
        Extracts and caches the corresponding text features for open-vocabulary detection.
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
        model_name: Optional[str] = None,
        classes: Optional[List[str]] = None,
        conf_thres: Optional[float] = None,
        iou_thres: Optional[float] = None,
    ) -> DetectionResult:
        """
        Runs object detection on the provided image using either Triton multi-model
        or local engine backend.
        
        Args:
            source: Image filepath, BGR numpy array, or PIL Image.
            model_name: (Optional) 'safety_detector' | 'coco_detector' | 'yoloe_detector'
            classes: (Optional) Override current classes for open-vocabulary inference.
            conf_thres: (Optional) Override confidence threshold.
            iou_thres: (Optional) Override NMS IoU threshold.
            
        Returns:
            DetectionResult instance with detected boxes, labels, and plotting helpers.
        """
        conf = conf_thres if conf_thres is not None else self.conf_thres
        iou = iou_thres if iou_thres is not None else self.iou_thres

        # 1. Preprocess
        input_tensor, orig_img, orig_shape = preprocess_image(source, imgsz=self.imgsz)

        # 2. Determine target model & classes
        chosen_model = (model_name or self.triton_model_name).lower().strip()
        filter_classes: Optional[Set[str]] = None

        if self.backend_type != "triton" and chosen_model in ("safety_detector", "safety", "coco_detector", "coco"):
            raise ValueError(
                f"'{chosen_model}' yalnızca Triton sunucusunda çalışır. Yerel {self.backend_type} motoru "
                "sadece açık sözlüklü YOLOE modelini (yoloe_detector) sunar."
            )

        if chosen_model in ("safety_detector", "safety"):
            active_model = "safety_detector"
            model_vocab = SAFETY_CLASSES
            if classes:
                filter_classes = {c.strip().lower() for c in classes}
            raw_output = self.backend.infer(input_tensor, model_name=active_model)

        elif chosen_model in ("coco_detector", "coco"):
            active_model = "coco_detector"
            model_vocab = COCO_CLASSES
            if classes:
                filter_classes = {c.strip().lower() for c in classes}
            raw_output = self.backend.infer(input_tensor, model_name=active_model)

        else:
            # yoloe_detector (Open-Vocabulary Decoupled)
            active_model = "yoloe_detector"
            active_classes = classes if classes is not None else self.current_classes
            if not active_classes:
                raise ValueError("YOLOE için hiçbir sınıf belirtilmedi! Lütfen classes parametresi verin.")

            model_vocab = active_classes
            if classes is not None and classes != self.current_classes:
                text_feats = self.text_encoder.encode(active_classes, to_numpy=True)
            else:
                if self.current_text_feats is None:
                    self.set_classes(active_classes)
                text_feats = self.current_text_feats

            raw_output = self.backend.infer(input_tensor, text_feats=text_feats, model_name=active_model)

        # 3. Postprocess (NMS + coordinate scaling)
        boxes = postprocess_detections(
            raw_output,
            orig_shape=orig_shape,
            classes=model_vocab,
            imgsz=self.imgsz,
            conf_thres=conf,
            iou_thres=iou,
        )

        # 4. Filter to requested classes if applicable (for fixed-vocabulary models)
        if filter_classes is not None:
            boxes = [b for b in boxes if b.cls_name.strip().lower() in filter_classes]

        output_classes = list(classes) if classes else model_vocab
        return DetectionResult(orig_img=orig_img, boxes=boxes, classes=output_classes)

    def detect_with_plan(
        self,
        source: Union[str, Path, np.ndarray, Any],
        plan: Any,
        conf_thres: Optional[float] = None,
        iou_thres: Optional[float] = None,
    ) -> DetectionResult:
        """
        Executes detection directly from a compiled DetectionPlan.
        Uses plan.selected_model / plan.triton_model_name and plan.get_yoloe_classes().
        """
        target_model = getattr(plan, "triton_model_name", None) or getattr(plan, "selected_model", "yoloe_detector")
        # For open-vocab YOLOE, classes are required.
        # For fixed-vocabulary models (safety_detector, coco_detector), keep full vocabulary
        # so surrounding context (persons, hardhats, machinery) is also captured for the video wall.
        if target_model in ("safety_detector", "coco_detector"):
            classes = None
        else:
            classes = plan.get_yoloe_classes() if hasattr(plan, "get_yoloe_classes") else None

        return self.detect(
            source=source,
            model_name=target_model,
            classes=classes,
            conf_thres=conf_thres,
            iou_thres=iou_thres,
        )

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
        from .trt_backend import build_engine_from_onnx
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
        from .trt_backend import get_trtexec_command
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
