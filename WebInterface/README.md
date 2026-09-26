# AegisVision AI - Akıllı Kamera & Gözetim Sistemi (Web Arayüzü)

Bu dizin, fiziksel IP kameraların (Hikvision, Dahua, Axis, Bosch, Hanwha, Uniview vb.) ONVIF Profile S/G/T standartlarıyla otomatik taranmasını, yönetilmesini ve canlı önizlenmesini sağlayan ticari web kontrol merkezini içerir.

---

## 1. Hızlı Başlatma

Sistemi tek komutla başlatmak için terminalden:

```bash
./WebInterface/run.sh
```

Sunucu varsayılan olarak **`http://localhost:8500`** üzerinde ayağa kalkar. Tarayıcınızdan bu adrese giderek arayüze erişebilirsiniz.

---

## 2. Arayüz ve Tasarım

* **Renk Paleti:** Açık amber turuncusu (`#FF8533` / `#FFA05C`), koyu arduvaz siyahı zemin (`#0A0D14`) ve modern cam efektleri (glassmorphism).
* **Sol Navigasyon Barı:**
  * 🏠 **Kameralar (Home):** [Aktif] Kamera filo yönetimi, canlı önizleme, ONVIF radar taraması.
  * 📺 **Canlı İzleme:** [Yakında] Gelecek aşamada entegre edilecek.
  * 🎯 **Nesne Tespiti:** [Yakında] Triton YOLOE açık-sözlü tespit modülü.
  * 🚨 **Anomali İzleme:** [Yakında] Triton S3D video anomali tespit modülü.
  * ⚙️ **Ayarlar:** [Yakında] Sistem konfigürasyonu.
* **Donanım ve Triton Telemetrisi:** Sol alt panelde gerçek zamanlı GPU kullanımı (`GTX 1650 Ti`, VRAM, Sıcaklık) ve Triton Inference Server sağlık durumu (`READY`) gösterilir.

---

## 3. Gerçek Dünya ONVIF Standartları ve Çalışma Mantığı

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

### C. Profil Tespiti (Profile S / G / T)
Kameranın yetenekleri ONVIF standartlarına göre ayrıştırılır ve kart üzerinde rozet olarak gösterilir:
* **Profile S:** IP video akışı, H.264 kodlama, RTSP URL.
* **Profile T:** Gelişmiş video akışı, H.265 (HEVC) kodlama, analitik alarmlar.
* **Profile G:** Dahili SD kart ve yerel depolama/kayıt oynatma.

### D. Canlı Önizleme Motoru (Flicker-Free Snapshot Polling)
Tarayıcıların doğrudan `rtsp://` protokolünü oynatamaması nedeniyle:
* Sistem öncelikle kameranın ONVIF `GetSnapshotUri` HTTP adresinden doğrudan JPEG çeker.
* Kamera sadece RTSP modundaysa, arka planda OpenCV TCP transport ile RTSP akışından anlık kare yakalar.
* Tarayıcıda 1.5 - 2 saniyede bir preloader ile titreşimsiz (flicker-free) akıcı canlı kartlar sağlanır.

---

## 4. REST API Uç Noktaları

| Yöntem | Endpoint | Açıklama |
| :--- | :--- | :--- |
| `GET` | `/api/system/stats` | GPU telemetrisi ve Triton Server durumunu döner |
| `GET` | `/api/onvif/interfaces` | Taranan aktif fiziksel ağ kartlarını listeler |
| `POST`| `/api/onvif/scan` | WS-Discovery multicast taramasını tetikler |
| `GET` | `/api/cameras` | Kayıtlı tüm kameraları döner |
| `POST`| `/api/cameras/add` | ONVIF üzerinden bağlanıp yeni kamera kaydeder |
| `DELETE`| `/api/cameras/{id}` | Kamerayı sistemden siler |
| `GET` | `/api/cameras/{id}/snapshot` | Kameranın anlık canlı JPEG görüntüsünü döner |
| `POST`| `/api/cameras/{id}/reconnect` | Kameranın bağlantısını ve durumunu tazeler |
| `GET` | `/api/rules` | Tanımlı tüm mekansal kuralları listeler |
| `POST`| `/api/rules` | Poligon koordinatları ve doğal dil açıklaması ile kural oluşturur |
| `GET` | `/api/rules/{id}` | Tek bir kuralın detaylarını getirir |
| `PUT` | `/api/rules/{id}` | Kural durumunu (Aktif/Pasif) veya parametrelerini günceller |
| `DELETE`| `/api/rules/{id}` | Kuralı sistemden siler |

---

## 5. İkinci Ekran: Kurallar & Bölgeler (Rules & Zones)

Arayüzün sol menüsünden **"Kurallar & Bölgeler"** sekmesine geçilerek:
* **Kamera Bazlı (Camera-Wise) Çizim:** İstenilen kamera seçilerek live snapshot üzerinde tıklamalarla serbest poligon (ihlal alanı / güvenlik bölgesi) çizilir.
* **Sistem Geneli (System-Wise) Kural:** Belirli bir kameraya bağlı olmaksızın tüm kameralara ve sisteme uygulanacak genel güvenlik kuralları tanımlanabilir.
* **Doğal Dil Yönergesi:** Kullanıcı poligon alanına ne tür ihlallerde nasıl tepki verileceğini serbest metinle (veya hazır şablon butonlarıyla) tanımlar.
* **Mekansal Koordinat Çözünürlük Bağımsızlığı:** Çizilen poligonlar $0.0 - 1.0$ normalize koordinatlarla saklanır, böylece 720p, 1080p veya 4K çözünürlük değişimlerinde alanlar tam oturur.
* **Kural Listesi:** Tanımlanan kurallar açma/kapatma (toggle switch), editöre geri yükleme ve silme seçenekleriyle yönetilir.
