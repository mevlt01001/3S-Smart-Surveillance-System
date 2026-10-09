# AegisVision — Web Arayüzü ve Sunucu

> Bu dosya web katmanının kısa özetidir. Ayrıntılı belgeler depo kökündeki [`docs/`](../docs/README.md) dizinindedir.

IP kameraları ağda bulan, canlı izleten, olağandışı hareketleri ve tanımlı kural ihlallerini videosuyla kaydeden güvenlik izleme sisteminin web katmanı.

---

## 1. Çalıştırma

```bash
./WebInterface/run.sh
```

Arayüz **http://localhost:8500** adresinde açılır.

| Ortam değişkeni | Varsayılan | Açıklama |
| :--- | :--- | :--- |
| `AEGIS_DATA_DIR` | `WebInterface/backend` | Kamera, kural, ayar ve olay kayıtlarının, videoların ve fotoğrafların tutulduğu dizin. Başka bir dizin vererek asıl veriye dokunmadan ikinci bir örnek çalıştırabilirsiniz. Aynı dizinde ikinci bir sunucu başlamaz. |
| `EVREN_API_KEY`, `EVREN_BASE_URL`, `EVREN_VLM_MODEL` | anahtar boş | Kural açıklamalarını çözümleyen ve olay özetlerini yazan dil modeli servisi. Anahtar depo kökündeki `.env` dosyasına yazılır (şablon: `.env.example`). Anahtar yoksa dış çağrı yapılmaz: kurallar "Hazırlanamadı" görünür, olaylar özetsiz kaydedilir. |

---

## 2. Arayüz

Beş sayfa vardır; menü sırası günlük kullanım sıklığına göredir.

| Sayfa | Ne yapılır |
| :--- | :--- |
| **Canlı İzleme** | Kamera duvarı (1 / 4 / 6 / 12'li düzen). Alarm veren kameranın çerçevesi renklenir, köşesinde nedeni yazar. "Yalnızca alarmdakiler" ile sorunlu kameralar süzülür. Bir kameraya tıklayınca büyür ve son 30 dakikasının olayları görünür. |
| **Olaylar** | Kaydedilen her olayın videosu, fotoğrafı ve yazılı özeti. Arama; kamera, zaman, tür ve inceleme durumuna göre süzme; "Doğru / Hatalı alarm" kararı; dışa aktarma (CSV). Yeni olaylar sayfa yenilenmeden listeye düşer. |
| **Kurallar** | Kamera görüntüsünde bölge çizip orada ne olunca haber verileceğini düz cümleyle yazma. İki tür bölge: kişi / nesne kuralı ve engel / değişiklik izleme. |
| **Kameralar** | Ağda kamera arama, adresle ekleme, ad ve açıklama düzenleme, yeniden bağlanma, silme. |
| **Ayarlar** | Algılama hassasiyeti, canlı izleme tercihleri, kayıt süresi ve disk alanı. Kurulumla ilgili değerler "Gelişmiş" bölümündedir. |

Sol alttaki durum satırı sistemin çalışıp çalışmadığını tek cümleyle söyler; sunucu bağlantısı koparsa ekranın üstünde uyarı çıkar. Teknik ayrıntılar (yayın adresi, çözünürlük, ekran kartı durumu, analiz süreleri) gündelik ekranlarda yer almaz; kamera bilgi penceresinde ve Ayarlar → Gelişmiş altında bulunur.

---

## 3. Kod Yapısı

```
WebInterface/
├── run.sh                      Sunucuyu başlatır
├── backend/
│   ├── server.py               Uygulama: açılış / kapanış, ara katmanlar, yönlendiricilerin bağlanması
│   ├── api/                    HTTP katmanı — konu başına bir modül, iş mantığı içermez
│   │   ├── cameras.py  live.py  rules.py  events.py  settings.py  system.py
│   │   ├── frontend.py         Arayüz dosyalarının sunumu
│   │   └── schemas.py          İstek gövdeleri
│   ├── camera_service.py       Kamera kayıtları, kamera başına tek RTSP işçisi, canlı kare dağıtımı
│   ├── anomaly_service.py      Olağandışı hareket analizi; skorları olaya çevirir, kural ihlallerini kaydeder
│   ├── event_journal.py        Olay günlüğü (kalıcı liste, operatör kararları, sayaçlar)
│   ├── evidence_store.py       Olay videoları ve fotoğrafları (kodlama, kota, kullanılmayan dosyalar)
│   ├── event_stream.py         Açık sayfalara canlı olay bildirimi (SSE)
│   ├── live_detection_service.py  Kuralların canlı görüntü üzerinde değerlendirilmesi
│   ├── rule_compilation.py     Kural açıklamalarının arka planda algılama planına çevrilmesi
│   ├── change_detector.py      Engel / değişiklik bölgeleri (referans görüntüyle karşılaştırma)
│   ├── rules_service.py  settings_service.py  system_stats.py
│   ├── onvif_core.py  onvif_auth.py   Kamera keşfi ve ONVIF iletişimi
│   └── paths.py                Veri dizini, güvenli dosya yazma, tek örnek kilidi
├── frontend/
│   ├── index.html              Sayfa iskeleti (satır içi stil veya betik yoktur)
│   ├── css/                    base → components → layout, ardından sayfa başına bir dosya
│   └── js/
│       ├── main.js  router.js  shell.js     Giriş noktası, sayfa geçişleri, her zaman görünen parçalar
│       ├── api.js                           Sunucuyla konuşan tek yer
│       ├── ui.js  labels.js                 Ortak bileşenler ve sade dil karşılıkları
│       ├── live.js  stream.js  overlay.js   Canlı izleme, video akışı, görüntü üstü çizimler
│       ├── events.js  event-detail.js       Olay listesi ve olay penceresi
│       ├── rules.js  zone-editor.js         Kural listesi / formu ve bölge çizim aracı
│       └── cameras.js  settings.js
└── tests/system_check.py       Uçtan uca sistem testi
```

Kurallar:

* Her sayfa modülü aynı arayüzü sunar: `mount(params)`, `unmount()` ve gerekiyorsa `canLeave()`. Sayfa görünür değilken zamanlayıcısı ve açık bağlantısı kalmaz.
* Sayfalar sunucu adresi kurmaz, `fetch` çağırmaz; yalnızca `api.js` işlevlerini kullanır.
* Tıklamalar `data-action` nitelikleri üzerinden tek dinleyiciyle ele alınır; genel (`window.*`) işlev ve satır içi `onclick` yoktur.
* Kullanıcıdan veya sunucudan gelen her metin `escapeHTML` ile kaçışlanarak sayfaya yazılır.
* Arayüz derleme adımı gerektirmez; tarayıcının kendi ES modülleri kullanılır. Dosyalar `/ui/...` adresinden `Cache-Control: no-cache` ile sunulur, tarayıcı her açılışta güncelliğini sorar.

---

## 4. Sistem Testi

```bash
.conda/bin/python WebInterface/tests/system_check.py
```

Betik kendi portunda ve **geçici bir veri dizininde** ayrı bir sunucu başlatır (dış servis çağrıları kapalı), HTTP / WebSocket / olay akışı yüzeyinin tamamını sınar ve arkasını temizler; asıl veriye dokunmaz. Arayüz için de şunları doğrular: `index.html`'in andığı her dosya vardır, betiklerin aradığı her öğe sayfada bulunur, yinelenen kimlik yoktur. Kamera simülatörü çalışıyorsa canlı video kontrolleri de (akış hızı, sinyal kaybı, değişiklik izleme, olay fotoğrafı) yürütülür; çalışmıyorsa `SKIP` olarak raporlanır. Çıkış kodu yalnızca bütün kontroller geçtiyse `0` olur.

---

## 5. Kameralara Bağlanma (ONVIF)

### A. Çoklu Ağ Arayüzü (Multi-NIC) WS-Discovery
Linux ana makinelerde birden fazla ağ kartı bulunur (`wlo1` = Wi-Fi `192.168.1.114`, `eno2` = Ethernet, Docker köprüleri).
Sistem:
1. Tüm aktif ve IPv4 adresine sahip fiziksel ağ arayüzlerini tespit eder.
2. Her arayüz üzerinden `IP_MULTICAST_IF` soket opsiyonu ile standard `239.255.255.250:3702` UDP çok noktaya yayın (multicast) probe paketlerini iletir.
3. Hem `dn:NetworkVideoTransmitter` hem `tds:Device` SOAP zarflarını göndererek eski ve yeni nesil tüm kameraları kapsar.

### B. WS-Security Saat Senkronizasyonu ($\Delta t$) ve PasswordDigest
Fiziksel kameraların donanım saati sunucudan farklı olduğunda kimlik doğrulama reddedilir (`401 Unauthorized` veya `wsse:FailedAuthentication`).
Sistem:
1. Şifresiz standart `GetSystemDateAndTime` çağrısıyla kameranın UTC saatini okur.
2. $\Delta t = t_{kamera} - t_{istemci}$ saat farkını hesaplar.
3. Tüm isteklerde bu farkı ekleyerek geçerli `wsu:Created` zaman damgası üretir:
   $$\text{PasswordDigest} = \text{Base64}\Big(\text{SHA-1}\big(\text{Ham Nonce Baytları} + \text{UTC Tarih} + \text{Şifre}\big)\Big)$$

### C. Canlı görüntü
Tarayıcılar `rtsp://` adresini doğrudan oynatamaz. Her kamera için tek bir arka plan işçisi yayını çözer; canlı izleme, analiz ve olay videoları aynı kare kaynağını paylaşır. Kareler tarayıcıya WebSocket üzerinden kameranın kendi hızında iletilir; yavaş kalan istemci kare atlar ama geride kalmaz.

---

## 6. API

Etkileşimli belge sunucu çalışırken `http://localhost:8500/docs` adresindedir.

| Konu | Uç noktalar |
| :--- | :--- |
| Sistem | `GET /api/health`, `GET /api/system/stats`, `POST /api/onvif/scan` |
| Kameralar | `GET /api/cameras`, `POST /api/cameras/add`, `PUT` / `DELETE /api/cameras/{id}`, `POST /api/cameras/{id}/reconnect`, `GET /api/cameras/{id}/snapshot`, `GET /api/cameras/{id}/stream` (MJPEG), `WS /api/cameras/{id}/ws` |
| Canlı durum | `GET /api/live/state`, `GET /api/cameras/{id}/live-detections`, `GET /api/change-detection/{kamera}/{bölge}`, `POST …/capture-reference`, `DELETE …/reference` |
| Kurallar | `GET` / `POST /api/rules`, `GET` / `PUT` / `DELETE /api/rules/{id}`, `GET /api/rules/{id}/plan` (tanılama), `POST /api/rules/{id}/compile` |
| Olaylar | `GET /api/anomaly/journal`, `GET /api/anomaly/stats`, `GET /api/anomaly/status`, `GET /api/anomaly/events-stream` (SSE), `POST /api/anomaly/{id}/label`, `POST /api/anomaly/{id}/summarize`, `GET /api/anomaly/{id}/frames`, `POST /api/anomaly/clear`, `POST /api/anomaly/simulate`, `GET /api/anomaly/clips/{dosya}`, `GET /api/anomaly/snapshots/{dosya}`, `GET /api/anomaly/storage`, `POST /api/anomaly/storage/cleanup-orphans` |
| Ayarlar | `GET` / `POST /api/settings`, `POST /api/settings/reset` |
