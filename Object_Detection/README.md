# Object_Detection Modülü

Bu modül, **YOLOE** açık sözlüklü (open-vocabulary) nesne tespiti modelini görsel omurga ve metin embedding'lerini birbirinden ayıran (**decoupled**) mimariyle sunar.

En büyük avantajı: **Tek bir TensorRT engine (`.engine`) veya ONNX modeli oluşturarak, modeli yeniden derlemeye veya grafiği değiştirmeye gerek kalmadan çalışma zamanında dilediğiniz metin promptlarını (`["person", "knife", "backpack", "shoes", ...]`) dinamik olarak tespit edebilmenizdir.**

---

## 🚀 Başka Bir Projede Kullanım (Entegrasyon)

Bu klasörü (`Object_Detection`) projenize dahil ettikten sonra doğrudan aşağıdaki şekilde kullanabilirsiniz:

```python
from Object_Detection import YOLODetector

# 1. Dedektörü başlatın (Yerel ONNX / TensorRT veya NVIDIA Triton Server!)
detector = YOLODetector(
    # Yerel Mod:
    model_path="yoloe-26l-seg_decoupled_sim.onnx", # veya "yoloe_decoupled.engine"
    
    # veya Triton Sunucu Modu:
    # backend="triton",
    # triton_url="localhost:8000",
    
    classes=["person", "bus", "shoes"],     # Başlangıç sınıfları
    conf_thres=0.25,
    iou_thres=0.45,
    device="cuda"
)

# 2. Görsel üzerinde tespit yapın (Dosya yolu, cv2 numpy array veya PIL Image)
results = detector.detect("bus.jpg")

# 3. Tespitleri okuyun
for box in results.boxes:
    print(f"{box.cls_name} ({box.conf:.2f}) -> {box.xyxy}")

# 4. Tespitleri görsel üzerine çizip kaydedin
results.save("tespit_sonucu.jpg")

# 5. İSTEDİĞİNİZ ANDA SINIFLARI DEĞİŞTİRİN (Engine'i yeniden yüklemeye GEREK YOK!)
detector.set_classes(["backpack", "sunglasses", "jacket"])
new_results = detector.detect("bus.jpg")
```

---

## 🔍 Ortam Teşhis ve Kontrol Aracı

Sisteminizdeki GPU, CUDA, Docker, NVIDIA Container Toolkit ve Triton Server durumunu tek raporda görmek için:
```bash
python Object_Detection/check_environment.py
```

---

## 🐳 NVIDIA Triton Inference Server (Docker ile Çalıştırma)

Model deposu (`model_repository`) ve konfigürasyon dosyası (`config.pbtxt`) hazır durumdadır.

### 0. Ön Koşul: Docker & NVIDIA Container Toolkit Kurulumu
Eğer sisteminizde Docker veya NVIDIA Container Toolkit henüz kurulu değilse, tek komutla kurabilirsiniz:
```bash
sudo bash Object_Detection/install_docker_prerequisites.sh
```

### Yöntem 1: Hazır Betik ile Başlatma
```bash
./Object_Detection/start_triton_docker.sh
```

### Yöntem 2: Docker Compose
```bash
docker compose -f Object_Detection/docker-compose.yml up -d
```

### Yöntem 3: Doğrudan `docker run`
```bash
docker run --gpus all --rm -it \
    --shm-size=1g --ulimit memlock=-1 --ulimit stack=67108864 \
    -p 8000:8000 -p 8001:8001 -p 8002:8002 \
    -v $(pwd)/Object_Detection/model_repository:/models \
    nvcr.io/nvidia/tritonserver:24.01-py3 \
    tritonserver --model-repository=/models --log-verbose=0
```

### Triton Üzerinden Hızlı Test:
```bash
python Object_Detection/triton_inference_test.py
```

---

## ⚡ TensorRT Engine Derleme (`trtexec`)

ONNX modelini yüksek performanslı bir TensorRT engine'e dönüştürmek için terminalde şu komutu çalıştırabilirsiniz:

```bash
trtexec --onnx=yoloe_decoupled_sim.onnx \
        --saveEngine=yoloe_decoupled.engine \
        --fp16 \
        --minShapes=images:1x3x640x640,text_feats:1x1x512 \
        --optShapes=images:1x3x640x640,text_feats:1x5x512 \
        --maxShapes=images:1x3x640x640,text_feats:1x80x512
```

> **Not:** `minShapes`, `optShapes` ve `maxShapes` profilleri sayesinde motor 1 sınıftan 80 sınıfa kadar dinamik sayıda sınıfı kabul eder.

---

## 📁 Modül Mimarisi

* `detector.py`: Ana `YOLODetector` API sınıfı.
* `text_encoder.py`: MobileCLIP ile metin prompt vektörlerini çıkaran ve önbelleğe (cache) alan sınıf.
* `onnx_backend.py`: ONNXRuntime çıkarım motoru.
* `trt_backend.py`: TensorRT sıfır kopyalı (zero-copy GPU buffer) çıkarım motoru ve `trtexec` oluşturucusu.
* `decoupled_model.py`: Saf YOLOE PyTorch modeli ile metin girişini ayıran sarmalayıcı ve ONNX export mantığı.
* `utils.py`: Letterbox boyutlandırma, kutu ölçekleme, NMS ve `DetectionResult` görselleştirme yardımcıları.
* `yolo_e_test.py`: Standalone test ve doğrulama betiği.
* `tests/`: 12 adet kapsamlı fonksiyonel ve uçtan uca birim testi (`run_tests.py` ile çalıştırılabilir).
