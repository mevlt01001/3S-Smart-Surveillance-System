"""
Utility functions for Object_Detection module.
Includes preprocessing, postprocessing, NMS, box scaling, and result visualization.
"""

from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple, Union, Optional, Dict, Any
import cv2
import numpy as np
import torch
from ultralytics.utils.nms import non_max_suppression


@dataclass
class DetectionBox:
    """Represents a single detected bounding box."""
    xyxy: List[int]       # [x1, y1, x2, y2] in original image coordinates
    conf: float           # Confidence score (0.0 to 1.0)
    cls_id: int           # Class index
    cls_name: str         # Class label / prompt text

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
        orig_img = source.copy()
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


def postprocess_detections(
    raw_output: Union[np.ndarray, torch.Tensor],
    orig_shape: Tuple[int, int],
    classes: List[str],
    imgsz: int = 640,
    conf_thres: float = 0.25,
    iou_thres: float = 0.45,
    max_det: int = 300,
) -> List[DetectionBox]:
    """
    Applies NMS and coordinate scaling to model output.
    raw_output: tensor or array of shape [1, 4 + nc, 8400]
    """
    if isinstance(raw_output, np.ndarray):
        raw_output = torch.from_numpy(raw_output)

    if raw_output.ndim == 2:
        raw_output = raw_output.unsqueeze(0)

    nc = len(classes)
    # Perform NMS
    preds = non_max_suppression(
        raw_output,
        conf_thres=conf_thres,
        iou_thres=iou_thres,
        nc=nc,
        max_det=max_det,
    )

    boxes: List[DetectionBox] = []
    if len(preds) == 0 or len(preds[0]) == 0:
        return boxes

    det = preds[0].cpu().numpy()
    # det: [N, 6] -> [x1, y1, x2, y2, conf, cls_id]
    det[:, :4] = scale_coords(det[:, :4], (imgsz, imgsz), orig_shape)

    for row in det:
        x1, y1, x2, y2, conf, cls_id = row
        cls_idx = int(cls_id)
        cls_name = classes[cls_idx] if cls_idx < len(classes) else f"class_{cls_idx}"
        boxes.append(DetectionBox(
            xyxy=[int(round(x1)), int(round(y1)), int(round(x2)), int(round(y2))],
            conf=float(conf),
            cls_id=cls_idx,
            cls_name=cls_name,
        ))

    return boxes
