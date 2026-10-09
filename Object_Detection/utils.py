"""
Utility functions for Object_Detection module.
Includes preprocessing, postprocessing, NMS, box scaling, and result visualization.
"""

from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple, Union, Dict, Any
import cv2
import numpy as np

# NOTE: This module is imported by the always-on web backend, which only talks to Triton.
# It therefore must not import torch / ultralytics (≈650 MB RSS and seconds of start-up
# for nothing): NMS is implemented with NumPy + OpenCV below.


@dataclass
class DetectionBox:
    """Represents a single detected bounding box."""
    xyxy: List[int]       # [x1, y1, x2, y2] in original image coordinates
    conf: float           # Confidence score (0.0 to 1.0)
    cls_id: int           # Class index
    cls_name: str         # Class label / prompt text

    @property
    def center(self) -> Tuple[float, float]:
        """Returns center (cx, cy) of the bounding box."""
        return (
            (self.xyxy[0] + self.xyxy[2]) / 2.0,
            (self.xyxy[1] + self.xyxy[3]) / 2.0,
        )

    @property
    def area(self) -> float:
        """Returns area of the bounding box."""
        return max(0, self.xyxy[2] - self.xyxy[0]) * max(0, self.xyxy[3] - self.xyxy[1])

    def to_dict(self) -> Dict[str, Any]:
        return {
            "bbox": self.xyxy,
            "confidence": round(float(self.conf), 4),
            "class_id": int(self.cls_id),
            "class_name": str(self.cls_name),
        }


class DetectionResult:
    """Contains all detections for an image and provides visualization utilities."""
    def __init__(self, orig_img: np.ndarray, boxes: List[DetectionBox], classes: List[str]):
        self.orig_img = orig_img
        self.boxes = boxes
        self.classes = classes

    def __len__(self) -> int:
        return len(self.boxes)

    def __iter__(self):
        return iter(self.boxes)

    def __repr__(self) -> str:
        summary = ", ".join(f"{b.cls_name} ({b.conf:.2f})" for b in self.boxes)
        return f"<DetectionResult: {len(self.boxes)} objects [{summary}]>"

    def to_dict(self) -> List[Dict[str, Any]]:
        """Returns JSON-serializable list of detections."""
        return [b.to_dict() for b in self.boxes]

    def plot(self, line_width: int = 2, font_scale: float = 0.5) -> np.ndarray:
        """Draws bounding boxes and labels on a copy of the original image."""
        img = self.orig_img.copy()
        for b in self.boxes:
            x1, y1, x2, y2 = b.xyxy
            color = get_class_color(b.cls_id)
            label = f"{b.cls_name} {b.conf:.2f}"

            # Draw bounding box
            cv2.rectangle(img, (x1, y1), (x2, y2), color, line_width)

            # Draw label pill
            (tw, th), baseline = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, font_scale, 1)
            y_label_bottom = max(y1, th + baseline + 4)
            cv2.rectangle(
                img,
                (x1, y_label_bottom - th - baseline - 4),
                (x1 + tw + 6, y_label_bottom),
                color,
                -1,
            )
            cv2.putText(
                img,
                label,
                (x1 + 3, y_label_bottom - baseline - 2),
                cv2.FONT_HERSHEY_SIMPLEX,
                font_scale,
                (255, 255, 255),
                1,
                cv2.LINE_AA,
            )
        return img

    def save(self, filepath: Union[str, Path]) -> str:
        """Saves plotted image to the given path."""
        plotted = self.plot()
        filepath = str(filepath)
        cv2.imwrite(filepath, plotted)
        return filepath


def get_class_color(cls_id: int) -> Tuple[int, int, int]:
    """Generates distinct, consistent BGR colors for class IDs."""
    colors = [
        (46, 204, 113),   # Emerald Green
        (52, 152, 219),   # Blue
        (231, 76, 60),    # Red
        (241, 196, 15),   # Yellow
        (155, 89, 182),   # Purple
        (230, 126, 34),   # Orange
        (26, 188, 156),   # Turquoise
        (243, 156, 18),   # Amber
        (211, 84, 0),     # Pumpkin
        (142, 68, 173),   # Amethyst
        (39, 174, 96),    # Nephritis
        (41, 128, 185),   # Belize Hole
    ]
    return colors[cls_id % len(colors)]


def letterbox(
    im: np.ndarray,
    new_shape: Tuple[int, int] = (640, 640),
    color: Tuple[int, int, int] = (114, 114, 114),
    auto: bool = False,
    scaleFill: bool = False,
    scaleup: bool = True,
    stride: int = 32,
) -> Tuple[np.ndarray, float, Tuple[float, float]]:
    """Resize and pad image while meeting stride-multiple constraints."""
    shape = im.shape[:2]  # current shape [height, width]
    if isinstance(new_shape, int):
        new_shape = (new_shape, new_shape)

    # Scale ratio (new / old)
    r = min(new_shape[0] / shape[0], new_shape[1] / shape[1])
    if not scaleup:  # only scale down, do not scale up (for better val mAP)
        r = min(r, 1.0)

    # Compute padding
    ratio = r, r  # width, height ratios
    new_unpad = int(round(shape[1] * r)), int(round(shape[0] * r))
    dw, dh = new_shape[1] - new_unpad[0], new_shape[0] - new_unpad[1]  # wh padding
    if auto:  # minimum rectangle
        dw, dh = np.mod(dw, stride), np.mod(dh, stride)  # wh padding
    elif scaleFill:  # stretch
        dw, dh = 0.0, 0.0
        new_unpad = (new_shape[1], new_shape[0])
        ratio = new_shape[1] / shape[1], new_shape[0] / shape[0]

    dw /= 2  # divide padding into 2 sides
    dh /= 2

    if shape[::-1] != new_unpad:  # resize
        im = cv2.resize(im, new_unpad, interpolation=cv2.INTER_LINEAR)
    top, bottom = int(round(dh - 0.1)), int(round(dh + 0.1))
    left, right = int(round(dw - 0.1)), int(round(dw + 0.1))
    im = cv2.copyMakeBorder(im, top, bottom, left, right, cv2.BORDER_CONSTANT, value=color)  # add border
    return im, r, (dw, dh)


def preprocess_image(
    source: Union[str, Path, np.ndarray],
    imgsz: int = 640
) -> Tuple[np.ndarray, np.ndarray, Tuple[int, int]]:
    """
    Loads and preprocesses an image for inference.
    Returns:
        - input_tensor: float32 array with shape [1, 3, imgsz, imgsz] normalized to [0, 1]
        - orig_img: original BGR image
        - (h0, w0): original height and width
    """
    if isinstance(source, (str, Path)):
        source_str = str(source)
        orig_img = cv2.imread(source_str)
        if orig_img is None:
            raise FileNotFoundError(f"Görsel açılamadı veya bulunamadı: {source_str}")
    elif isinstance(source, np.ndarray):
        orig_img = source  # letterbox() below allocates a new array; the caller's frame is never modified
    else:
        # Support PIL Image
        orig_img = cv2.cvtColor(np.array(source), cv2.COLOR_RGB2BGR)

    h0, w0 = orig_img.shape[:2]
    img_lb, _, _ = letterbox(orig_img, new_shape=(imgsz, imgsz), auto=False)

    # Convert BGR to RGB, HWC to CHW, normalize to 0-1
    tensor = img_lb[:, :, ::-1].transpose(2, 0, 1)
    tensor = np.ascontiguousarray(tensor, dtype=np.float32) / 255.0
    tensor = np.expand_dims(tensor, axis=0)

    return tensor, orig_img, (h0, w0)


def scale_coords(
    coords: np.ndarray,
    img1_shape: Tuple[int, int],
    img0_shape: Tuple[int, int]
) -> np.ndarray:
    """
    Rescale coords (x1, y1, x2, y2) from img1_shape (letterboxed) to img0_shape (original).
    """
    gain = min(img1_shape[0] / img0_shape[0], img1_shape[1] / img0_shape[1])
    pad_x = (img1_shape[1] - img0_shape[1] * gain) / 2
    pad_y = (img1_shape[0] - img0_shape[0] * gain) / 2

    coords[:, [0, 2]] -= pad_x
    coords[:, [1, 3]] -= pad_y
    coords[:, :4] /= gain

    # Clip to bounds
    coords[:, [0, 2]] = np.clip(coords[:, [0, 2]], 0, img0_shape[1])
    coords[:, [1, 3]] = np.clip(coords[:, [1, 3]], 0, img0_shape[0])
    return coords


def _class_aware_nms(
    boxes_xyxy: np.ndarray,
    scores: np.ndarray,
    class_ids: np.ndarray,
    iou_thres: float,
    max_det: int = 300,
    max_wh: float = 7680.0,
) -> np.ndarray:
    """
    Greedy per-class NMS. Mirrors ultralytics' strategy: boxes are shifted by
    class_id * max_wh so different classes never suppress each other, then a single
    NMS pass runs over all boxes. Returns kept indices sorted by descending score.
    """
    if len(boxes_xyxy) == 0:
        return np.empty((0,), dtype=np.int64)
    offsets = class_ids.astype(np.float64)[:, None] * max_wh
    shifted = boxes_xyxy.astype(np.float64) + offsets
    xywh = np.empty_like(shifted)
    xywh[:, 0] = shifted[:, 0]
    xywh[:, 1] = shifted[:, 1]
    xywh[:, 2] = shifted[:, 2] - shifted[:, 0]
    xywh[:, 3] = shifted[:, 3] - shifted[:, 1]
    keep = cv2.dnn.NMSBoxes(xywh.tolist(), scores.astype(np.float64).tolist(), 0.0, float(iou_thres))
    keep = np.asarray(keep, dtype=np.int64).reshape(-1)
    if len(keep) > max_det:
        keep = keep[:max_det]
    return keep


def postprocess_detections(
    raw_output: Any,
    orig_shape: Tuple[int, int],
    classes: List[str],
    imgsz: int = 640,
    conf_thres: float = 0.25,
    iou_thres: float = 0.45,
    max_det: int = 300,
    max_nms: int = 30000,
) -> List[DetectionBox]:
    """
    Applies NMS and coordinate scaling to model output.
    raw_output: array (or torch tensor) of shape [1, 4 + nc (+ extra), num_anchors]
                with boxes as (cx, cy, w, h) in letterboxed pixels and per-class scores.
    """
    if not isinstance(raw_output, np.ndarray):
        # torch.Tensor (or anything array-like) without importing torch here
        if hasattr(raw_output, "detach"):
            raw_output = raw_output.detach().cpu().numpy()
        else:
            raw_output = np.asarray(raw_output)

    if raw_output.ndim == 2:
        raw_output = raw_output[None]

    nc = len(classes)
    boxes: List[DetectionBox] = []
    if raw_output.shape[0] == 0 or nc == 0:
        return boxes

    pred = raw_output[0]                       # [4 + nc (+nm), anchors]
    cls_scores = pred[4:4 + nc]                # [nc, anchors]
    conf = cls_scores.max(axis=0)
    candidates = np.flatnonzero(conf > conf_thres)
    if candidates.size == 0:
        return boxes

    conf = conf[candidates]
    cls_ids = cls_scores[:, candidates].argmax(axis=0)
    cx, cy, bw, bh = (pred[i, candidates].astype(np.float32) for i in range(4))
    xyxy = np.stack([cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2], axis=1)

    order = np.argsort(-conf, kind="stable")[:max_nms]
    xyxy, conf, cls_ids = xyxy[order], conf[order], cls_ids[order]

    keep = _class_aware_nms(xyxy, conf, cls_ids, iou_thres=iou_thres, max_det=max_det)
    if keep.size == 0:
        return boxes

    det_xyxy = scale_coords(xyxy[keep].copy(), (imgsz, imgsz), orig_shape)
    det_conf = conf[keep]
    det_cls = cls_ids[keep]

    for (x1, y1, x2, y2), score, cls_id in zip(det_xyxy, det_conf, det_cls):
        cls_idx = int(cls_id)
        cls_name = classes[cls_idx] if cls_idx < len(classes) else f"class_{cls_idx}"
        boxes.append(DetectionBox(
            xyxy=[int(round(float(x1))), int(round(float(y1))), int(round(float(x2))), int(round(float(y2)))],
            conf=float(score),
            cls_id=cls_idx,
            cls_name=cls_name,
        ))

    return boxes
