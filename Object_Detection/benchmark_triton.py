"""
NVIDIA Triton Inference Server Performans ve Dynamic Batching Testi.
Hem sıralı (tek kamera) hem de eşzamanlı (çoklu kamera akışı) istekleri test ederek
Triton'un dinamik batchleme (dynamic batching) performansını ölçer.
"""

import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import numpy as np
import requests

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import cv2
import tritonclient.http as httpclient
from Object_Detection import YOLODetector
from Object_Detection.utils import preprocess_image


def get_triton_batch_stats(triton_url: str = "localhost:8000"):
    """Fetches real dynamic batching execution statistics from Triton Server."""
    try:
        url = f"http://{triton_url}/v2/models/yoloe_detector/stats"
        resp = requests.get(url, timeout=3)
        if resp.status_code == 200:
            data = resp.json()
            model_stats = data.get("model_stats", [{}])[0]
            batch_stats = model_stats.get("batch_stats", [])
            return batch_stats
    except Exception:
        pass
    return []


def run_benchmark(
    num_requests: int = 100,
    concurrency: int = 4,
    image_path: str = "bus.jpg",
    triton_url: str = "localhost:8000",
    classes = ["person", "bus", "forklift", "shoes"],
):
    print("=" * 70)
    print(f"  NVIDIA Triton Inference Server: Sıralı vs Eşzamanlı (Batching) Testi")
    print(f"  Toplam İstek: {num_requests} | Eşzamanlı İstemci (Kamera) Sayısı: {concurrency}")
    print("=" * 70)

    # 1. Dedektörü başlat
    detector = YOLODetector(
        backend="triton",
        triton_url=triton_url,
        classes=classes,
    )
    print(f"🟢 Triton bağlantısı aktif ({triton_url}).")

    # 2. Görseli ve tensörleri hazırla
    img_bgr = cv2.imread(str(image_path))
    assert img_bgr is not None, f"Görsel açılamadı: {image_path}"
    img_tensor, orig_img, orig_shape = preprocess_image(img_bgr, imgsz=640)
    text_feats = detector.current_text_feats

    # 3. Isınma (Warmup)
    print("\n[Adım 1/3] Isınma (Warmup) yapılıyor (5 istek)...")
    for _ in range(5):
        _ = detector.backend.infer(img_tensor, text_feats)
    print("           🟢 GPU hazır.")

    # -------------------------------------------------------------
    # 4. TEST 1: SIRALI TEST (Sequential - Tek Kamera / Tek Akış)
    # -------------------------------------------------------------
    print(f"\n[Adım 2/3] TEST 1: SIRALI İSTEKLER (Sequential - Kuyruk Boş, Batch=1)")
    print(f"           (Her istek bir öncekinin bitmesini bekler)")
    seq_latencies = []
    t_seq_start = time.perf_counter()

    for i in range(1, num_requests + 1):
        t0 = time.perf_counter()
        _ = detector.backend.infer(img_tensor, text_feats)
        t1 = time.perf_counter()
        lat = (t1 - t0) * 1000
        seq_latencies.append(lat)
        if i % 25 == 0 or i == num_requests:
            print(f"           İstek {i:3d}/{num_requests} -> {lat:.1f} ms")

    seq_total_sec = time.perf_counter() - t_seq_start
    seq_fps = num_requests / seq_total_sec

    # -------------------------------------------------------------
    # 5. TEST 2: EŞZAMANLI TEST (Concurrent - Çoklu Kamera / Dynamic Batching)
    # -------------------------------------------------------------
    print(f"\n[Adım 3/3] TEST 2: EŞZAMANLI İSTEKLER (Concurrent - {concurrency} Paralel İstemci)")
    print(f"           (İstekler aynı anda gelir, Triton Dynamic Batching kuyruğunda birikir)")

    thread_local = threading.local()

    def get_thread_client():
        if not hasattr(thread_local, "client"):
            thread_local.client = httpclient.InferenceServerClient(url=triton_url)
        return thread_local.client

    def send_concurrent_request(req_id):
        client = get_thread_client()
        inp1 = httpclient.InferInput("images", img_tensor.shape, "FP32")
        inp1.set_data_from_numpy(img_tensor)
        inp2 = httpclient.InferInput("text_feats", text_feats.shape, "FP32")
        inp2.set_data_from_numpy(text_feats)
        out = httpclient.InferRequestedOutput("outputs")

        t0 = time.perf_counter()
        _ = client.infer("yoloe_detector", inputs=[inp1, inp2], outputs=[out])
        t1 = time.perf_counter()
        return (t1 - t0) * 1000

    conc_start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        conc_latencies = list(executor.map(send_concurrent_request, range(num_requests)))
    conc_total_sec = time.perf_counter() - conc_start
    conc_fps = num_requests / conc_total_sec

    # 6. Triton Sunucusundan Gerçek Batch İstatistiklerini Çek
    batch_stats = get_triton_batch_stats(triton_url)

    # 7. Sonuç Raporu
    print("\n" + "=" * 70)
    print("                     KARŞILAŞTIRMA RAPORU")
    print("=" * 70)
    print(f"{'Metrik':<30} | {'1. Sıralı Mod (Tek Kamera)':<20} | {'2. Eşzamanlı Mod (' + str(concurrency) + ' Kamera)':<20}")
    print("-" * 70)
    print(f"{'Toplam Süre':<30} | {seq_total_sec:6.2f} saniye{'':<7} | {conc_total_sec:6.2f} saniye")
    print(f"{'İşlem Hızı (FPS)':<30} | {seq_fps:6.2f} FPS{'':<10} | {conc_fps:6.2f} FPS")
    print(f"{'Ortalama Gecikme':<30} | {np.mean(seq_latencies):6.2f} ms{'':<11} | {np.mean(conc_latencies):6.2f} ms")
    print(f"{'Medyan Gecikme (p50)':<30} | {np.median(seq_latencies):6.2f} ms{'':<11} | {np.median(conc_latencies):6.2f} ms")
    print(f"{'En Hızlı İstek (Min)':<30} | {np.min(seq_latencies):6.2f} ms{'':<11} | {np.min(conc_latencies):6.2f} ms")
    print(f"{'p95 Gecikme':<30} | {np.percentile(seq_latencies, 95):6.2f} ms{'':<11} | {np.percentile(conc_latencies, 95):6.2f} ms")
    print("=" * 70)

    if batch_stats:
        print("\n📊 TRITON SUNUCUSU DYNAMIC BATCHING DAĞILIMI:")
        print("   (Triton'un GPU'ya gönderdiği gerçek batch büyüklükleri ve sayıları)")
        for b in batch_stats:
            bsize = b.get("batch_size", 0)
            bcount = b.get("compute_infer", {}).get("count", 0)
            avg_ns = b.get("compute_infer", {}).get("ns", 0) / max(1, bcount)
            print(f"   * Batch Büyüklüğü: {bsize:<2} -> {bcount:4d} kez çalıştırıldı (Ortalama GPU Süresi: {avg_ns/1e6:.1f} ms)")
        print("=" * 70)


if __name__ == "__main__":
    run_benchmark(num_requests=100, concurrency=4)
