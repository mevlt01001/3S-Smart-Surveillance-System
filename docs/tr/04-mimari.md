# 04 — Mimari

## Süreçler

| Süreç | Nasıl başlar | Durum bilgisi |
| :--- | :--- | :--- |
| Web sunucusu (uvicorn + FastAPI) | `WebInterface/run.sh` | Veri dizinindeki JSON dosyaları ve kanıt dosyaları |
| Analiz sunucusu (Triton) | `Object_Detection/start_triton_docker.sh` | Yok (durumsuz) |
| Dil modeli servisi | Dış servis | — |
| Tarayıcı | — | Tema ve dil tercihleri (`localStorage`) |

Web sunucusu tek süreçtir ve bütün iş mantığını içerir. Ölçekleme birden çok süreçle değil, süreç
içindeki iş parçacıklarıyla yapılır; bu yüzden aynı veri dizininde ikinci bir sunucu çalıştırılamaz.

## Web sunucusunun içi

```
                               ┌────────────────────────── asyncio olay döngüsü ──────────────────────────┐
                               │  api/*  (HTTP yönlendiricileri, WebSocket, SSE)                           │
                               └───────▲──────────────▲───────────────▲──────────────────▲─────────────────┘
                                       │ kareler      │ durum         │ olaylar          │ bildirim
┌──────────────┐ kareler ┌─────────────┴───┐  ┌───────┴────────┐ ┌────┴───────────┐ ┌────┴─────────┐
│ CameraLive   ├────────►│ camera_service  │  │ anomaly_service│ │ event_journal  │ │ event_stream │
│ Worker × N   │         │ (kayıt + dağıtım)│  │ (skor → olay)  ├►│ (kalıcı liste) ├►│ (SSE)        │
│ iş parçacığı │         └──────┬──────────┘  └───────┬────────┘ └────────────────┘ └──────────────┘
└──────────────┘                │ kareler             │ video, fotoğraf
                                ▼                     ▼
                       ┌──────────────────────┐ ┌────────────────┐
                       │ live_detection_service│ │ evidence_store │
                       │ (kurallar → ihlal)    │ │ (ffmpeg, kota) │
                       └──────────────────────┘ └────────────────┘
```

### İş parçacıkları

| İş parçacığı | Sayı | Ne yapar |
| :--- | :--- | :--- |
| Olay döngüsü | 1 | HTTP isteklerini, WebSocket ve SSE bağlantılarını yürütür. Engelleyen iş burada yapılmaz. |
| `CameraLiveWorker` | kamera başına 1 | RTSP yayınını çözer, kareleri bellekte tutar, bekleyenleri uyarır. |
| Kamera bekçisi | 1 | Kare gelmeyen kameraları çevrimdışı işaretler. |
| `AnomalyWorker` | 1 | Kameraları gruplar hâlinde anomali modeline gönderir, olayları açıp kapatır. |
| `LiveDetectionWorker` | 1 | Etkin kuralı olan kameralarda nesne tespiti ve kural değerlendirmesi yapar. |
| `RuleCompile_*` | kural başına, geçici | Bir kuralın açıklamasını dil modeliyle plana çevirir. |
| `Clip-*`, `Summary-*` | olay başına, geçici | Videoyu ffmpeg ile kodlar; özeti dil modelinden ister. |

Uzun süren ve engelleyen her iş (model çağrısı, ffmpeg, dosya taraması) ya kendi iş parçacığında ya
da `asyncio.to_thread` ile olay döngüsünün dışında yapılır; canlı görüntü hiçbir zaman bunları beklemez.

## Bir karenin yolculuğu

1. **Yakalama.** `CameraLiveWorker` yayını OpenCV/FFmpeg ile TCP üzerinden, düşük gecikme
   seçenekleriyle açar. Kaynak 30 kare/sn'den hızlıysa fazlası atılır.
2. **Tek sefer işleme.** Her kare bir kez JPEG'e çevrilir (canlı görüntü ve olay videosu bunu
   kullanır) ve bir kez 224×224 RGB'ye küçültülür (anomali modeli bunu kullanır).
3. **Bellekte tutma.** JPEG'ler zaman damgasıyla bir halka tamponda tutulur. Tamponun uzunluğu,
   kesilebilecek en uzun olay videosuna göre ayarlanır (en uzun video + iki pay + birleştirme
   süresi + 8 sn).
4. **Dağıtım.** Yeni kare geldiğinde bekleyen WebSocket bağlantıları olay döngüsü üzerinden uyandırılır
   (`loop.call_soon_threadsafe`); sorgulama yoktur. Yavaş kalan istemci aradaki kareleri atlar.
5. **Analiz.** Anomali döngüsü ve kural döngüsü yalnızca **yeni kare gelmiş** kameraları işler.

Bir kamerayı ne izleyen ne de analiz eden varsa işçisi 120 saniye sonra bağlantıyı bırakır
("Hazır" durumu) ve ilk istekte yeniden bağlanır.

## Bir olayın yolculuğu

### Olağandışı hareket

```
skor ≥ uyarı seviyesi ──► olay açılır (kayıt + fotoğraf, "sürüyor") ──► arayüze bildirim
        │
        ├─ skor yüksek kaldıkça: en yüksek an güncellenir
        ├─ sakinlik < birleştirme süresi: olay sürer
        ├─ süre ≥ en uzun video: olay kapatılır, hareket sürüyorsa yenisi açılır
        ▼
sakinlik > birleştirme süresi ──► olay kapatılır:
        • kesin saatler, en yüksek anın fotoğrafı, kayıt güncellenir ──► arayüze bildirim
        • video: tampondaki kareler [başlangıç − pay, bitiş + pay] ──► ffmpeg ──► kota denetimi
        • özet: aynı karelerden sekizi ──► dil modeli ──► kayıt güncellenir ──► arayüze bildirim
```

### Kural ihlali

Kural döngüsü, bir kural en az 1 saniyedir ihlal ediliyorsa her karede
`anomaly_service.rule_violated` çağırır. İlk çağrı, son 5 saniyenin kareleriyle bir olay kaydı
açar (aynı video / özet yolu); sonraki çağrılar yalnızca olayı açık tutar. Kural 10 saniye
ihlal edilmeyince olay, gerçek bitiş saati ve süresiyle kapatılır. Bir saat süren ihlal bu yüzden
tek olaydır.

## Tasarım kararları

**Tek kaynak, çok tüketici.** Canlı görüntü, anomali analizi, kural analizi ve olay videosu aynı
kamera işçisinin karelerini paylaşır. Kamera başına tek RTSP bağlantısı açılır.

**Sorgulama yerine olay.** Canlı kareler WebSocket üzerinden itilir; olay listesi SSE ile güncellenir.
Arayüzün düzenli sorguladığı tek şey durumdur (`/api/live/state` 400 ms'de bir, `/api/system/stats`
5 sn'de bir).

**Gerçeği gösterme.** Sunucu ölçmediği değeri bildirmez: analiz süresi son 15 saniyede ölçülmediyse
`null`, anomali skoru 10 saniyeden eskiyse yok sayılır. Sinyali kesilen kamera `offline` olarak
bildirilir; donmuş kare "canlı" diye gösterilmez.

**Sunucu `torch` yüklemez.** Web sunucusu modelleri kendisi çalıştırmaz; Triton'a tensör gönderir.
`Object_Detection` paketinin torch isteyen üyeleri yalnızca istenince yüklenir. Bu sayede sunucu
açılışta ~110 MB bellek kullanır.

**Kopyasız Triton istemcisi.** Dört kameralık bir anomali isteği 38 MB'tır.
`Object_Detection/triton_fast_client.py` NumPy tamponunu kopyalamadan sokete yazar.

**Güvenli yazım.** JSON dosyaları geçici dosyaya yazılıp yeniden adlandırılır (`paths.atomic_write_json`);
çökme ya da eşzamanlı okuma yarım dosya görmez. Videolar da `tmp_` önekiyle kodlanıp bitince adlandırılır.

**Tek örnek kilidi.** Sunucu açılırken veri dizinindeki `.aegis.lock` dosyasını kilitler. Aynı dizinde
ikinci bir sunucu, kayıtları bellekten yeniden yazarak birbirinin verisini ezerdi; ikinci süreç
20 saniye bekler (yeniden başlatma durumu), kilit boşalmazsa açık bir iletiyle çıkar.

**Hızlı kapanma.** Tarayıcılar video ve bildirim bağlantılarını süresiz açık tutar ve ASGI sunucusu
açık bağlantıları bekler. `SIGINT`/`SIGTERM` gelince önce `paths.SHUTTING_DOWN` işaretlenir; bütün
uzun ömürlü döngüler bunu görüp çıkar.

**Arayüz önbelleği.** Arayüz dosyaları `/ui/` altından `Cache-Control: no-cache` ile sunulur: tarayıcı
her açılışta sorar, değişmeyen dosya için `304` alır. Böylece yeni sürüm eski önbellekle karışmaz.

**Dil istemcide.** Arayüz Türkçe yazılır ve tarayıcıda tek bir katalogdan çevrilir; sunucunun dili
bilmesi yalnızca istek üzerine kendisinin yazdığı birkaç cümle (kural planları, çalışma saatleri) için
gerekir ve bunu `Accept-Language` başlığından okur. Saklanan metinler çevrilmez.
Ayrıntı: [07 — Frontend](07-frontend.md), "Arayüz dili".

## Açılış sırası

`server.py` içe aktarılırken:

1. `backend/__init__.py` OpenCV'nin ortam ayarlarını yapar (OpenCV bunları ilk içe aktarmada okur).
2. `acquire_instance_lock()` veri dizinini kilitler — servisler kayıtları yüklemeden **önce**.
3. Servis modülleri içe aktarılır; her biri modül düzeyinde tek bir nesne oluşturur
   (`camera_service`, `anomaly_service`, …), kayıtlarını yükler ve iş parçacığını başlatır.
4. Yönlendiriciler ve arayüz uygulamaya bağlanır.

Servislerin modül düzeyinde tekil nesneler olması bilinçli bir sadeliktir; karşılığında bir servisi
içe aktarmak onu başlatır. Testler bu yüzden sunucuyu ayrı bir süreçte, geçici veri diziniyle çalıştırır.

## Başarım ölçüleri

Geliştirme makinesinde (8 kamera, GTX 1650 Ti) ölçülen değerler:

| Ölçü | Değer |
| :--- | :--- |
| Sunucu belleği | 580–700 MB (kamera başına 60 sn'lik kare tamponuyla) |
| İş parçacığı sayısı | ~45 |
| İşlemci (8 kamera izlenirken) | ~%125–135 (bir çekirdek = %100) |
| Tarayıcıya ulaşan kare hızı | Kaynağın hızı (25 → 25, 30 → 30 kare/sn) |
| API yanıt süresi (p95) | 8–11 ms |
| Anomali analizi | Kamera başına ~45–65 ms, saniyede ~4 değerlendirme |
| Kapanma | < 1 sn |
