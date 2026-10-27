# 02 — Kurulum ve çalıştırma

## Gereksinimler

| Gereksinim | Not |
| :--- | :--- |
| Linux | Ubuntu 22.04 üzerinde sınanmıştır. |
| NVIDIA ekran kartı + sürücü | Modeller TensorRT ile çalışır. Geliştirme makinesi: GTX 1650 Ti (4 GB). |
| Docker + NVIDIA Container Toolkit | Analiz sunucusu (Triton) kapsayıcıda çalışır. Kurulum betiği: `sudo bash Object_Detection/install_docker_prerequisites.sh` |
| Python 3.10 | Depo kökündeki `.conda/` ortamı kullanılır. |
| ffmpeg | Olay videolarını kodlar ve videolardan kare okur. `sudo apt install ffmpeg` |
| Tarayıcı | Güncel Chrome / Edge. Firefox'ta sınanmamıştır. |

Ortamın durumunu tek raporda görmek için: `python Object_Detection/check_environment.py`

## İlk kurulum

### 1. Python ortamı

```bash
conda create -p ./.conda python=3.10 -y
```
```bash
./.conda/bin/pip install -r requirements.txt
```

### 2. Model dosyaları

Model ağırlıkları depoda **tutulmaz** (`.gitignore`). Her model, Triton model deposunda kendi dizinine konur:

```
Object_Detection/model_repository/
├── anomaly_detector/   config.pbtxt   1/model.plan      girdi: video_segment [3,16,224,224]  → logits [1]
├── safety_detector/    config.pbtxt   1/model.plan      girdi: images [3,640,640]            → output0 [14,N]
├── coco_detector/      config.pbtxt   1/model.plan      girdi: images [3,640,640]            → output0 [84,N]
└── yoloe_detector/     config.pbtxt   1/model.plan      girdi: images + text_feats [K,512]   → outputs [K+4,8400]
```

`model.plan`, TensorRT motorudur ve **üretildiği ekran kartına özeldir**; başka bir makineye kopyalanamaz.
Elinizde ONNX dosyaları varsa (`1/model.onnx`) motorları o makinede üretin:

```bash
./Object_Detection/convert_to_tensorrt.sh
```
```bash
./Object_Detection/apply_tensorrt_configs.sh
```

İlki ONNX dosyalarını kapsayıcı içindeki `trtexec` ile motora çevirir (4 GB'lık kartta 25–45 dakika),
ikincisi `config.pbtxt` dosyalarını TensorRT'ye göre günceller ve Triton'u yeniden başlatır.

### 3. Erişim anahtarı

Kural açıklamalarını çözümleyen ve olay özetlerini yazan dil modeli servisi bir anahtar ister.
Şablonu kopyalayıp anahtarı yazın:

```bash
cp .env.example .env
```

`.env` depoya girmez. Anahtar verilmezse sistem çalışır; yalnızca cümleyle tarif edilen kurallar
"Hazırlanamadı" görünür ve olaylar özetsiz kaydedilir. Listeden seçilen kurallar, engel / değişiklik
kuralları ve olağandışı hareket algılama bu servise ihtiyaç duymaz.

## Başlatma

Üç süreç vardır. Sırası önemlidir: web sunucusu açılırken analiz sunucusunu arar.

### 1. Analiz sunucusu

```bash
./Object_Detection/start_triton_docker.sh
```

Kapsayıcının adı `triton_yoloe_server`, HTTP portu `8000`. Modellerin yüklendiğini doğrulamak için:

```bash
curl -s localhost:8000/v2/health/ready -o /dev/null -w "%{http_code}\n"
```

### 2. Kamera simülatörü (yalnızca gerçek kamera yoksa)

```bash
cd Camera_System_Simulator && ./start.sh --dir ../TestVideoSet
```

Dizindeki her video bir kamera olur: görüntü `rtsp://<ip>:8554/<dosya adı>` adresinden, ONVIF servisi
`8891`'den başlayarak kamera başına bir porttan yayınlanır. Varsayılan hesap `admin` / `admin123`.
Simülatörün kendi Python ortamı vardır (`Camera_System_Simulator/venv`).

### 3. Web sunucusu

```bash
./WebInterface/run.sh
```

Arayüz **http://localhost:8500** adresinde açılır. Betik sunucuyu `--reload` ile başlatır:
`WebInterface/backend` altındaki bir Python dosyası değişince sunucu kendini yeniden başlatır.

Terminal kapandığında da çalışsın isterseniz:

```bash
setsid nohup ./WebInterface/run.sh > aegis.log 2>&1 < /dev/null &
```

## İlk kullanım

1. **Kameralar** sayfasında "Ağda kamera ara"ya basın, kameraların kullanıcı adı ve şifresini yazıp
   "Tümünü ekle"yi seçin. (Bulunamayan kamera için "Elle ekle".)
2. **Canlı İzleme**'de görüntülerin geldiğini doğrulayın.
3. **Ayarlar → Algılama**'da "Olağandışı hareketleri algıla" açık olsun.
4. İsterseniz **Kurallar**'dan bir bölge kuralı tanımlayın.
5. Arayüzü İngilizce kullanmak için **Ayarlar → Görünüm → English** (cihaz başına).

Ayrıntılar: [03 — Kullanım kılavuzu](03-kullanim-kilavuzu.md).

## Durdurma

```bash
pkill -f "uvicorn WebInterface.backend.server:app"
```
```bash
cd Camera_System_Simulator && ./stop.sh
```
```bash
docker stop triton_yoloe_server
```

Web sunucusu kapanırken açık video ve bildirim bağlantılarını kendisi sonlandırır; bir saniyenin
altında çıkar.

## Portlar

| Port | Süreç | Kullanım |
| :--- | :--- | :--- |
| 8500 | Web sunucusu | Arayüz ve API |
| 8000 | Triton | HTTP çıkarım (8001 gRPC, 8002 ölçümler) |
| 8554 | Simülatör (mediamtx) | RTSP |
| 8891–… | Simülatör | Kamera başına ONVIF |
| 3702/udp | — | ONVIF keşfi (WS-Discovery çok noktaya yayını) |

## İkinci bir örnek çalıştırma

Asıl veriye dokunmadan denemek için ayrı veri dizini ve port verin:

```bash
AEGIS_DATA_DIR=/tmp/aegis-deneme EVREN_API_KEY="" .conda/bin/python -m uvicorn WebInterface.backend.server:app --port 8502
```

`EVREN_API_KEY=""` dış servis çağrılarını kapatır. Aynı veri dizininde ikinci bir sunucu başlamaz;
açık bir hata iletisiyle çıkar (bkz. [04 — Mimari](04-mimari.md), "Tek örnek kilidi").

## Ağ notları

- Sunucu `0.0.0.0:8500` üzerinde dinler: aynı ağdaki herkes arayüze ulaşabilir. **Kimlik doğrulama
  yoktur**; yerel ağ dışına açmayın.
- Kamera keşfi, makinenin bütün etkin ağ kartlarından ayrı ayrı yapılır; kameralar farklı bir alt
  ağdaysa keşif onları bulamaz, "Elle ekle" kullanılır.
- Bir kamera, kaydedildiği andaki IP adresiyle saklanır. Kameranın adresi değişirse silip yeniden ekleyin.
  (Simülatör, başladığı andaki makine adresini duyurur; makinenin adresi değişirse simülatörü yeniden başlatın.)
