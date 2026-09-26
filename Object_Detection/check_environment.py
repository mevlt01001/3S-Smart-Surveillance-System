"""
Ortam ve Çıkarım Altyapısı Teşhis Aracı (Diagnostic Tool).
GPU, CUDA, TensorRT, Docker, NVIDIA Container Toolkit ve Triton Server durumunu kontrol eder.
"""

import sys
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def check_gpu():
    print("1. [GPU & CUDA Durumu]")
    try:
        import torch
        if torch.cuda.is_available():
            name = torch.cuda.get_device_name(0)
            mem = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
            print(f"   🟢 GPU: {name} ({mem:.2f} GB VRAM)")
            print(f"   🟢 PyTorch CUDA: Aktif (CUDA {torch.version.cuda})")
            return True
        else:
            print("   🔴 GPU: CUDA algılanamadı (CPU modunda).")
            return False
    except ImportError:
        print("   🟡 PyTorch kütüphanesi bulunamadı.")
        return False


def check_onnxruntime():
    print("\n2. [ONNX Runtime & Sağlayıcılar]")
    try:
        import onnxruntime as ort
        providers = ort.get_available_providers()
        print(f"   Mevcut Sağlayıcılar: {providers}")
        if "CUDAExecutionProvider" in providers:
            print("   🟢 CUDAExecutionProvider: AKTİF (GPU Hızlandırma)")
        else:
            print("   🟡 CUDAExecutionProvider: YOK (CPU modunda çalışıyor)")
        if "TensorrtExecutionProvider" in providers:
            print("   🟢 TensorrtExecutionProvider: AKTİF")
        else:
            print("   ⚪ TensorrtExecutionProvider: Yok")
    except ImportError:
        print("   🔴 ONNX Runtime kurulu değil.")


def check_tensorrt():
    print("\n3. [Yerel TensorRT Durumu]")
    try:
        import tensorrt as trt
        print(f"   🟢 TensorRT Python Paketi: {trt.__version__}")
    except ImportError:
        print("   🟡 TensorRT Python paketi kurulu değil.")

    trtexec = shutil.which("trtexec")
    if trtexec:
        print(f"   🟢 trtexec komutu: {trtexec}")
    else:
        print("   🟡 trtexec komutu sistem PATH'inde bulunamadı.")


def check_docker():
    print("\n4. [Docker & Konteyner Durumu]")
    docker_bin = shutil.which("docker")
    if docker_bin:
        print(f"   🟢 Docker CLI: {docker_bin}")
        # Daemon çalışıyor mu?
        try:
            res = subprocess.run(["docker", "info"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)
            if res.returncode == 0:
                print("   🟢 Docker Daemon: Çalışıyor")
            else:
                print("   🟡 Docker Daemon: Çalışmıyor veya yetki gerekli (kullanıcıyı docker grubuna ekleyin)")
        except Exception:
            print("   🟡 Docker Daemon durumu sorgulanamadı.")
    else:
        print("   🔴 Docker: KURULU DEĞİL ('docker' komutu bulunamadı)")

    ctk_bin = shutil.which("nvidia-ctk") or shutil.which("nvidia-container-toolkit")
    if ctk_bin:
        print(f"   🟢 NVIDIA Container Toolkit: {ctk_bin}")
    else:
        print("   🔴 NVIDIA Container Toolkit: KURULU DEĞİL")


def check_triton(url: str = "localhost:8000"):
    print("\n5. [NVIDIA Triton Server Durumu]")
    try:
        from Object_Detection.triton_backend import TritonBackend
        backend = TritonBackend(url=url, model_name="yoloe_detector", protocol="http")
        live = backend.is_alive()
        if live:
            print(f"   🟢 Triton Sunucusu ({url}): AKTİF")
            ready = backend.is_model_ready()
            print(f"   {'🟢' if ready else '🟡'} 'yoloe_detector' Modeli: {'HAZIR' if ready else 'YÜKLENİYOR / HAZIR DEĞİL'}")
        else:
            print(f"   🔴 Triton Sunucusu ({url}): ÇEVRİMDIŞI")
    except Exception as e:
        print(f"   🔴 Triton kontrol hatası: {e}")


def main():
    print("=" * 60)
    print("    Akıllı Gözetim Sistemi - Ortam Teşhis Raporu")
    print("=" * 60)
    check_gpu()
    check_onnxruntime()
    check_tensorrt()
    check_docker()
    check_triton()
    print("=" * 60)


if __name__ == "__main__":
    main()
