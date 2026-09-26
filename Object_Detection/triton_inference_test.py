"""
NVIDIA Triton Inference Server Test Betiği.
Triton container'ı çalışırken veya test amaçlı hızlı inference testi yapmak için kullanılır.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Object_Detection import YOLODetector
from Object_Detection.triton_backend import TritonBackend


def run_triton_test(
    image_path: str = "warehouse2.png",
    triton_url: str = "localhost:8000",
    classes = ["head"]
):
    print("=" * 60)
    print("  NVIDIA Triton Inference Server Testi")
    print("=" * 60)

    # 1. Triton sunucu durumunu kontrol et
    backend = TritonBackend(url=triton_url, model_name="yoloe_detector", protocol="http")
    is_live = backend.is_alive()
    print(f"Triton Sunucu Durumu ({triton_url}): {'🟢 AKTİF (Online)' if is_live else '🔴 ÇEVRİMDIŞI (Offline)'}")

    if not is_live:
        print("\n⚠️ Triton sunucusu şu an çalışmıyor.")
        
        import shutil
        docker_available = shutil.which("docker") is not None
        if not docker_available:
            print("\n❌ Sisteminizde Docker bulunamadı!")
            print("NVIDIA Triton Server'ı GPU ile çalıştırabilmek için Docker ve NVIDIA Container Toolkit gereklidir.")
            print("Tek komutla otomatik kurulum yapmak için şu komutu çalıştırabilirsiniz:")
            print("\n  👉  sudo bash Object_Detection/install_docker_prerequisites.sh\n")
            print("Kurulum tamamlandıktan sonra sunucuyu başlatmak için:")
            print("  ./Object_Detection/start_triton_docker.sh")
        else:
            print("Triton sunucusunu başlatmak için şu komutu çalıştırabilirsiniz:")
            print("  ./Object_Detection/start_triton_docker.sh")

        print("\n" + "-" * 60)
        print("💡 Triton çevrimdışı iken YEREL ÇIKARIM (ONNX/GPU) testini çalıştırmak için:")
        print("   python dummy_main.py")
        print("-" * 60)
        return False

    # 2. Triton üzerinden YOLODetector ile tespit yap
    print(f"\n[Inference] Triton üzerinden tespit yapılıyor: {image_path} (Sınıflar: {classes})...")
    detector = YOLODetector(
        backend="triton",
        triton_url=triton_url,
        classes=classes,
        conf_thres=0.25,
    )

    results = detector.detect(image_path)
    print(f"\n✅ Triton üzerinden {len(results)} nesne tespit edildi:")
    for b in results.boxes:
        print(f" - {b.cls_name} (%{b.conf * 100:.1f}) -> {b.xyxy}")

    output_file = "output_triton_detected.jpg"
    results.save(output_file)
    print(f"\nSonuç görseli kaydedildi: {output_file}")
    return True

if __name__ == "__main__":
    run_triton_test()
