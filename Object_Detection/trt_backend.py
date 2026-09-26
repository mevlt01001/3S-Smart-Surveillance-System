"""
TensorRT execution backend and engine builder for decoupled YOLOE models.
Supports dynamic input shapes (variable batch size and variable number of classes).
"""

from __future__ import annotations
from pathlib import Path
from typing import Union, List, Tuple, Dict, Optional, Any
import subprocess
import shutil
import numpy as np
import torch

try:
    import tensorrt as trt
    TRT_AVAILABLE = True
except ImportError:
    trt = None
    TRT_AVAILABLE = False


def is_tensorrt_available() -> bool:
    """Returns True if TensorRT Python library is installed."""
    return TRT_AVAILABLE


class TensorRTBackend:
    """
    TensorRT execution backend using dynamic shape optimization profiles.
    Uses PyTorch CUDA tensors for zero-copy memory management, avoiding PyCUDA dependencies.
    """
    def __init__(self, engine_path: Union[str, Path], device: str = "cuda:0"):
        if not TRT_AVAILABLE:
            raise ImportError(
                "TensorRT kütüphanesi kurulu değil. TensorRT engine çalıştırmak için "
                "'pip install tensorrt' veya NVIDIA TensorRT paketlerini yükleyin."
            )

        self.engine_path = str(engine_path)
        if not Path(self.engine_path).is_file():
            raise FileNotFoundError(f"TensorRT engine dosyası bulunamadı: {self.engine_path}")

        self.device = torch.device(device)
        self.logger = trt.Logger(trt.Logger.WARNING)

        # Load serialized engine
        with open(self.engine_path, "rb") as f, trt.Runtime(self.logger) as runtime:
            self.engine = runtime.deserialize_cuda_engine(f.read())

        if self.engine is None:
            raise RuntimeError(f"TensorRT engine yüklenemedi: {self.engine_path}")

        self.context = self.engine.create_execution_context()
        self.stream = torch.cuda.Stream(device=self.device)

        # Inspect I/O bindings
        self.input_names = []
        self.output_names = []
        self._inspect_io()

    def _inspect_io(self):
        """Discovers input and output tensor names based on TensorRT version."""
        # TRT 10+ uses num_io_tensors
        if hasattr(self.engine, "num_io_tensors"):
            for i in range(self.engine.num_io_tensors):
                name = self.engine.get_tensor_name(i)
                mode = self.engine.get_tensor_mode(name)
                if mode == trt.TensorIOMode.INPUT:
                    self.input_names.append(name)
                elif mode == trt.TensorIOMode.OUTPUT:
                    self.output_names.append(name)
        else:
            # TRT 8.x
            for i in range(self.engine.num_bindings):
                name = self.engine.get_binding_name(i)
                if self.engine.binding_is_input(i):
                    self.input_names.append(name)
                else:
                    self.output_names.append(name)

    def infer(
        self,
        images: Union[np.ndarray, torch.Tensor],
        text_feats: Union[np.ndarray, torch.Tensor]
    ) -> np.ndarray:
        """
        Runs inference on TensorRT engine with dynamic shape allocation.
        Args:
            images: [batch, 3, 640, 640]
            text_feats: [batch, num_classes, 512]
        Returns:
            outputs: [batch, 4 + num_classes, 8400] as numpy array
        """
        # Convert to CUDA PyTorch tensors
        if isinstance(images, np.ndarray):
            images_t = torch.from_numpy(images).to(self.device).contiguous().float()
        else:
            images_t = images.to(self.device).contiguous().float()

        if isinstance(text_feats, np.ndarray):
            text_feats_t = torch.from_numpy(text_feats).to(self.device).contiguous().float()
        else:
            text_feats_t = text_feats.to(self.device).contiguous().float()

        # Match batch dimension
        if text_feats_t.shape[0] != images_t.shape[0]:
            text_feats_t = text_feats_t.expand(images_t.shape[0], -1, -1).contiguous()

        images_name = self.input_names[0]
        text_name = self.input_names[1]
        output_name = self.output_names[0]

        # Modern TRT 8.5+ / 10+ execute_v3
        if hasattr(self.context, "execute_v3"):
            self.context.set_input_shape(images_name, tuple(images_t.shape))
            self.context.set_input_shape(text_name, tuple(text_feats_t.shape))

            # Allocate output buffer
            out_shape = tuple(self.context.get_tensor_shape(output_name))
            output_t = torch.empty(out_shape, dtype=torch.float32, device=self.device)

            # Set tensor addresses
            self.context.set_tensor_address(images_name, images_t.data_ptr())
            self.context.set_tensor_address(text_name, text_feats_t.data_ptr())
            self.context.set_tensor_address(output_name, output_t.data_ptr())

            # Synchronous or Stream Execution
            self.context.execute_async_v3(self.stream.cuda_stream)
            self.stream.synchronize()
            return output_t.detach().cpu().numpy()
        else:
            # TRT 8.x legacy binding execution
            self.context.set_binding_shape(0, tuple(images_t.shape))
            self.context.set_binding_shape(1, tuple(text_feats_t.shape))
            out_shape = tuple(self.context.get_binding_shape(2))
            output_t = torch.empty(out_shape, dtype=torch.float32, device=self.device)

            bindings = [images_t.data_ptr(), text_feats_t.data_ptr(), output_t.data_ptr()]
            self.context.execute_async_v2(bindings=bindings, stream_handle=self.stream.cuda_stream)
            self.stream.synchronize()
            return output_t.detach().cpu().numpy()


def get_trtexec_command(
    onnx_path: str = "yoloe_decoupled_sim.onnx",
    engine_path: str = "yoloe_decoupled.engine",
    fp16: bool = True,
    min_classes: int = 1,
    opt_classes: int = 5,
    max_classes: int = 80,
    imgsz: int = 640,
) -> str:
    """Generates the recommended trtexec terminal command for building the engine."""
    fp16_flag = "--fp16 " if fp16 else ""
    return (
        f"trtexec --onnx={onnx_path} "
        f"--saveEngine={engine_path} "
        f"{fp16_flag}"
        f"--minShapes=images:1x3x{imgsz}x{imgsz},text_feats:1x{min_classes}x512 "
        f"--optShapes=images:1x3x{imgsz}x{imgsz},text_feats:1x{opt_classes}x512 "
        f"--maxShapes=images:1x3x{imgsz}x{imgsz},text_feats:1x{max_classes}x512"
    )


def build_engine_with_python_api(
    onnx_path: Union[str, Path],
    engine_path: Union[str, Path],
    fp16: bool = True,
    min_classes: int = 1,
    opt_classes: int = 5,
    max_classes: int = 80,
    imgsz: int = 640,
    verbose: bool = True,
) -> bool:
    """
    Builds a TensorRT engine using the native Python TensorRT API.
    """
    if not is_tensorrt_available():
        return False
    try:
        import tensorrt as trt
        logger = trt.Logger(trt.Logger.INFO if verbose else trt.Logger.WARNING)
        builder = trt.Builder(logger)
        network = builder.create_network(1 << int(trt.NetworkDefinitionCreationFlag.EXPLICIT_BATCH))
        parser = trt.OnnxParser(network, logger)
        config = builder.create_builder_config()

        with open(str(onnx_path), "rb") as f:
            if not parser.parse(f.read()):
                if verbose:
                    for error in range(parser.num_errors):
                        print(f"[TRT Parser Error] {parser.get_error(error)}")
                return False

        profile = builder.create_optimization_profile()
        profile.set_shape("images", (1, 3, imgsz, imgsz), (1, 3, imgsz, imgsz), (1, 3, imgsz, imgsz))
        profile.set_shape("text_feats", (1, min_classes, 512), (1, opt_classes, 512), (1, max_classes, 512))
        config.add_optimization_profile(profile)

        if fp16 and builder.platform_has_fast_fp16:
            config.set_flag(trt.BuilderFlag.FP16)

        if verbose:
            print(f"[TRT Python API] Engine derleniyor: {engine_path} ...")
        plan = builder.build_serialized_network(network, config)
        if plan is None:
            return False

        with open(str(engine_path), "wb") as f:
            f.write(plan)
        if verbose:
            print(f"[TRT Python API] Engine başarıyla oluşturuldu: {engine_path}")
        return True
    except Exception as e:
        if verbose:
            print(f"[TRT Python API] Derleme sırasında hata: {e}")
        return False


def build_engine_from_onnx(
    onnx_path: Union[str, Path],
    engine_path: Union[str, Path],
    fp16: bool = True,
    min_classes: int = 1,
    opt_classes: int = 5,
    max_classes: int = 80,
    imgsz: int = 640,
    verbose: bool = True,
) -> bool:
    """
    Builds a TensorRT engine using the Python API or `trtexec`.
    """
    if is_tensorrt_available():
        success = build_engine_with_python_api(
            onnx_path=onnx_path,
            engine_path=engine_path,
            fp16=fp16,
            min_classes=min_classes,
            opt_classes=opt_classes,
            max_classes=max_classes,
            imgsz=imgsz,
            verbose=verbose,
        )
        if success:
            return True

    trtexec_bin = shutil.which("trtexec")
    if not trtexec_bin:
        cmd = get_trtexec_command(str(onnx_path), str(engine_path), fp16, min_classes, opt_classes, max_classes, imgsz)
        if verbose:
            print(f"[TRT] 'trtexec' sistem yolunda bulunamadı. Lütfen şu komutu çalıştırın:\n{cmd}")
        return False

    cmd = [
        trtexec_bin,
        f"--onnx={onnx_path}",
        f"--saveEngine={engine_path}",
        f"--minShapes=images:1x3x{imgsz}x{imgsz},text_feats:1x{min_classes}x512",
        f"--optShapes=images:1x3x{imgsz}x{imgsz},text_feats:1x{opt_classes}x512",
        f"--maxShapes=images:1x3x{imgsz}x{imgsz},text_feats:1x{max_classes}x512",
    ]
    if fp16:
        cmd.append("--fp16")

    if verbose:
        print(f"[TRT] trtexec ile derleme başlatılıyor: {' '.join(cmd)}")

    ret = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if ret.returncode == 0:
        if verbose:
            print(f"[TRT] Engine başarıyla oluşturuldu: {engine_path}")
        return True
    else:
        if verbose:
            print(f"[TRT] Hata oluştu:\n{ret.stderr}")
        return False
