# 01 — Genel bakış

## Sistem ne yapar

Smart Surveillance System, ağdaki IP kameraları tek bir web arayüzünde toplar ve görüntüyü iki yoldan sürekli inceler:

1. **Olağandışı hareket algılama.** Her kameranın son karelerini bir anomali modeline verir. Kavga, panik,
   koşma gibi olağan akışa uymayan hareketlerde olay kaydı açar.
2. **Kural denetimi.** Kullanıcı bir kameranın görüntüsünde bölge çizer ve o bölgede ne olunca haber
   almak istediğini düz cümleyle yazar ("Baret takmayan biri girerse"). Sistem bu cümleyi bir kez
   algılama planına çevirir, sonra her karede planı uygular.

Her olay; videosu, olay anı fotoğrafı ve birkaç cümlelik yazılı özetiyle kaydedilir. Operatör olayı
izleyip "doğru alarm" ya da "hatalı alarm" olarak işaretler.

## Temel yetenekler

| Yetenek | Açıklama |
| :--- | :--- |
| Kamera keşfi | Ağdaki ONVIF kameraları otomatik bulur; adres yazarak da eklenebilir. |
| Canlı izleme | 1 / 4 / 6 / 12'li kamera duvarı; kameranın kendi kare hızında, gecikmesiz. |
| Alarm vurgusu | Alarm veren kameranın çerçevesi renklenir, köşesinde nedeni yazar. |
| Olağandışı hareket | Kural tanımlamadan çalışır; hassasiyeti iki eşikle ayarlanır. |
| Kural bölgeleri | Çokgen bölge + düz cümle ya da listeden seçim; kişi / nesne kuralı ve engel / değişiklik izleme. Kurala çalışma saati verilebilir; sistem yapamadığı isteği söyler. |
| Olay kaydı | Olay boyunca tek video, olay anı fotoğrafı, yazılı özet, operatör kararı. |
| Dışa aktarma | Süzülmüş olay listesi CSV olarak indirilir. |
| Raporlar | Güne, kurala ve kameraya göre olay sayıları, hatalı alarm oranı, ihlallerin toplam süresi; yazdırılabilir. |
| Disk yönetimi | Kayıtlar için kota; dolunca en eski videolar silinir. |
| Diller | Arayüz Türkçe (varsayılan) ya da İngilizce, cihaz başına seçilir; açık, lacivert ve koyu tema. |

## Parçalar

```
┌───────────────┐   RTSP    ┌──────────────────────────────────────────┐   HTTP    ┌──────────────┐
│ IP kameralar  │──────────►│ Web sunucusu (WebInterface/backend)      │──────────►│ Analiz       │
│ (veya         │   ONVIF   │  • kamera işçileri (kamera başına 1)     │  tensörler│ sunucusu     │
│  simülatör)   │◄──────────│  • anomali döngüsü                       │◄──────────│ (Triton, GPU)│
└───────────────┘           │  • kural döngüsü                         │   skorlar └──────────────┘
                            │  • olay günlüğü, video / fotoğraf kaydı  │
                            │  • HTTP API + arayüz dosyaları           │   HTTPS   ┌──────────────┐
                            └───────────────┬──────────────────────────┘──────────►│ Dil modeli   │
                                            │ HTTP / WebSocket / SSE                │ servisi      │
                                            ▼                                       │ (EVREN)      │
                                   ┌─────────────────┐                              └──────────────┘
                                   │ Tarayıcı        │
                                   └─────────────────┘
```

| Parça | Dizin | Görev |
| :--- | :--- | :--- |
| Web sunucusu | `WebInterface/backend/` | Kameralardan görüntü alır, analizi yürütür, olayları kaydeder, API sunar. |
| Arayüz | `WebInterface/frontend/` | Tarayıcıda çalışan altı sayfalık uygulama. |
| Kural motoru | `Rule_Generator_LLM/` | Cümleyi plana çevirir, nesneleri kareler arasında izler, planı değerlendirir, olay özetini yazar. |
| Tespit kitaplığı | `Object_Detection/` | Triton'a nesne tespiti isteği gönderen `YOLODetector` ve model deposu. |
| Analiz sunucusu | Docker: `triton_yoloe_server` | Dört modeli GPU üzerinde çalıştırır. |
| Dil modeli servisi | dış servis | Kural derleme ve olay özeti. Erişilemezse sistemin geri kalanı çalışır. |
| Simülatör | `Camera_System_Simulator/` | Geliştirme için video dosyalarını kamera gibi yayınlar. |
| Model eğitimi | `Anomaly_Detection/` | Anomali modelinin eğitim kodu (alt modül); çalışan sistemin parçası değildir. |

## Analiz sunucusundaki modeller

| Model adı | Girdi | Ne için |
| :--- | :--- | :--- |
| `anomaly_detector` | 16 karelik klip, 224×224 | Olağandışı hareket skoru (0–100). |
| `safety_detector` | tek kare | İş güvenliği sınıfları: baret, yelek, maske ve bunların yokluğu, kişi, araç, iş makinesi, koni. |
| `coco_detector` | tek kare | Genel nesneler (80 COCO sınıfı): kişi, araba, çanta… |
| `yoloe_detector` | tek kare + sınıf adları | Serbest sözcüklü tespit: yukarıdaki listelerde olmayan nesneler (forklift, palet…). |

Hangi kuralın hangi modeli kullanacağına kural derleyici karar verir (bkz. bölüm 08).

## Terimler

| Terim | Anlamı |
| :--- | :--- |
| Olay | Kaydedilmiş bir alarm: olağandışı hareket ya da kural ihlali. |
| Seviye (`tier`) | Olayın önemi: `warning` (Uyarı) ya da `critical` (Kritik). Kameralar için ayrıca `normal` ve `offline`. |
| Skor | Anomali modelinin 0–100 arasındaki çıktısı. Eşikler bu sayıya uygulanır. |
| Bölge (`zone`) | Görüntü üzerinde çizilen çokgen. Köşeler 0–1 aralığında saklanır, çözünürlükten bağımsızdır. |
| Algılama planı | Bir bölge açıklamasının derlenmiş hâli: hangi model, hangi sınıflar, hangi koşul. |
| Referans görüntü | Engel / değişiklik bölgesinin "boş" hâli; canlı görüntü bununla karşılaştırılır. |
| Kanıt | Bir olayın videosu (klip) ve fotoğrafı. |
| Kamera işçisi | Bir kameranın RTSP yayınını çözen arka plan iş parçacığı. |
| Veri dizini | Kamera, kural, ayar ve olay kayıtlarının tutulduğu dizin (`AEGIS_DATA_DIR`). |
