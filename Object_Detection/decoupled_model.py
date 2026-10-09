"""
Decoupled YOLOE PyTorch Module and ONNX Exporter.
Allows decoupling the vision backbone/neck/head from the text embeddings,
producing a two-input ONNX model compatible with TensorRT.
"""

from __future__ import annotations
from pathlib import Path
from typing import Union
import torch
import onnxslim
from ultralytics import YOLO


class DecoupledYOLOE(torch.nn.Module):
    """
    Wraps Ultralytics YOLOE model to receive image and text features dynamically as separate inputs.
    
    Inputs:
        - images: [batch, 3, 640, 640]
        - text_feats: [batch, num_classes, 512]
    Output:
        - outputs: [batch, 4 + num_classes, 8400]
    """
    def __init__(self, base_model: torch.nn.Module, export_task: str = "detect"):
        super().__init__()
        self.base_model = base_model
        self.export_task = export_task

    def forward(self, images: torch.Tensor, text_feats: torch.Tensor) -> torch.Tensor:
        b = images.shape[0]
        if text_feats.shape[0] != b:
            text_feats = text_feats.expand(b, -1, -1)

        # Pass tpe=text_feats directly to predict/contrastive head
        out = self.base_model(images, tpe=text_feats)
        y = out[0] if isinstance(out, tuple) else out
        nc = text_feats.shape[1]

        if self.export_task == "detect":
            # Slice bounding boxes (4) and class scores (nc)
            return y[:, :4 + nc, :]
        else:
            return out


def export_decoupled_onnx(
    model_or_path: Union[str, Path, YOLO] = "yoloe-26l-seg.pt",
    output_path: Union[str, Path] = "yoloe_decoupled_sim.onnx",
    device: str = "cuda" if torch.cuda.is_available() else "cpu",
    imgsz: int = 640,
    opset: int = 17,
    simplify: bool = True,
    verbose: bool = True,
) -> str:
    """
    Exports a YOLOE checkpoint into a decoupled ONNX model with dynamic class support.
    """
    output_path = Path(output_path)
    raw_onnx = output_path.with_name(f"{output_path.stem}_raw.onnx")

    if isinstance(model_or_path, YOLO):
        yolo_model = model_or_path
    else:
        yolo_model = YOLO(str(model_or_path))

    core_model = yolo_model.model.to(device).eval()

    # Configure export flags on submodules to eliminate internal dictionary / debug outputs
    for m in core_model.modules():
        if hasattr(m, "export"):
            m.export = True
        if hasattr(m, "format"):
            m.format = "onnx"

    wrapped = DecoupledYOLOE(core_model, export_task="detect").to(device).eval()

    dummy_image = torch.randn(1, 3, imgsz, imgsz, device=device)
    dummy_text_feats = torch.randn(1, 3, 512, device=device)

    if verbose:
        print(f"[Export] Decoupled ONNX modeli oluşturuluyor -> {raw_onnx}")

    torch.onnx.export(
        wrapped,
        (dummy_image, dummy_text_feats),
        str(raw_onnx),
        opset_version=opset,
        input_names=["images", "text_feats"],
        output_names=["outputs"],
        dynamic_axes={
            "images": {0: "batch"},
            "text_feats": {0: "batch", 1: "num_classes"},
            "outputs": {0: "batch", 1: "channels", 2: "num_detections"},
        },
        dynamo=False,
    )

    if simplify:
        if verbose:
            print(f"[Export] Model onnxslim ile optimize ediliyor -> {output_path}")
        onnxslim.slim(str(raw_onnx), output_model=str(output_path))
        if raw_onnx.exists() and raw_onnx != output_path:
            raw_onnx.unlink()
        final_file = str(output_path)
    else:
        final_file = str(raw_onnx)

    if verbose:
        print(f"[Export] Tamamlandı: {final_file}")

    return final_file
