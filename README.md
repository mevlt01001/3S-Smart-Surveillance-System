# Smart Surveillance System (AegisVision)

IP kameraları tek arayüzde toplayan, olağandışı hareketleri ve düz cümleyle tanımlanan kural
ihlallerini yakalayıp videosu, fotoğrafı ve birkaç cümlelik özetiyle kaydeden güvenlik izleme sistemi.

- **Canlı izleme:** 1 / 4 / 6 / 12'li kamera duvarı; alarm veren kamera vurgulanır.
- **Olağandışı hareket algılama:** kural tanımlamadan çalışır (kavga, panik, koşma…).
- **Kural bölgeleri:** görüntüde bölge çizin, ne olunca haber almak istediğinizi yazın
  ("Baret takmayan biri girerse", "Gece 22:00 ile 06:00 arasında biri girerse") ya da listeden seçin.
  Sistem yapamadığı bir isteği söyler; kurallar yalnızca belirlediğiniz saatlerde çalışabilir.
- **Engel izleme:** acil çıkış, yangın dolabı gibi boş kalması gereken yerler.
- **Olay kaydı:** olay boyunca tek video, olay anı fotoğrafı, yazılı özet, operatör kararı.
- **Raporlar:** güne, kurala ve kameraya göre olay sayıları, hatalı alarm oranı; yazdırılabilir.

## Arayüz

| Canlı izleme | Olaylar |
| --- | --- |
| ![Canlı izleme duvarı](docs/images/canli-izleme.jpg) | ![Olay listesi](docs/images/olaylar.jpg) |
| Kamera duvarı; düzen, bölge ve tespit katmanları üst çubuktan seçilir. | Kaydedilen olaylar; arama, süzme ve tek tıkla doğru / hatalı kararı. |

| Olay penceresi | Kural düzenleyici |
| --- | --- |
| ![Olay penceresi](docs/images/olay-penceresi.jpg) | ![Kural düzenleyici](docs/images/kural-duzenleyici.jpg) |
| Olay videosu, kısa yazılı özet ve operatör kararı. | Görüntüde bölge çizilir, ne olunca haber verileceği düz cümleyle yazılır. |

| Kameralar | Ayarlar |
| --- | --- |
| ![Kameralar](docs/images/kameralar.jpg) | ![Ayarlar](docs/images/ayarlar.jpg) |
| Ağda kamera arama, elle ekleme, durum ve düzenleme. | Algılama hassasiyeti, kayıt süresi ve depolama alanı. |

Görüntüler `Camera_System_Simulator` ile oynatılan test videolarından alınmıştır.

## Hızlı başlangıç

Gereksinimler: Linux, NVIDIA ekran kartı, Docker + NVIDIA Container Toolkit, Python 3.10, ffmpeg.
Ayrıntılar ve model dosyalarının kurulumu: [docs/02-kurulum.md](docs/02-kurulum.md).

```bash
conda create -p ./.conda python=3.10 -y && ./.conda/bin/pip install -r requirements.txt
```
```bash
cp .env.example .env        # dil modeli servisinin anahtarını yazın (isteğe bağlı)
```
```bash
./Object_Detection/start_triton_docker.sh                        # 1. analiz sunucusu
```
```bash
cd Camera_System_Simulator && ./start.sh --dir ../TestVideoSet   # 2. gerçek kamera yoksa
```
```bash
./WebInterface/run.sh                                            # 3. http://localhost:8500
```

Arayüzde: **Kameralar → Ağda kamera ara → Tümünü ekle**, sonra **Canlı İzleme**.

## Belgeler

| | |
| :--- | :--- |
| [Genel bakış](docs/01-genel-bakis.md) | Sistem ne yapar, parçaları, terimler |
| [Kurulum ve çalıştırma](docs/02-kurulum.md) | Gereksinimler, modeller, başlatma, portlar |
| [Kullanım kılavuzu](docs/03-kullanim-kilavuzu.md) | Arayüzün beş sayfası, adım adım |
| [Mimari](docs/04-mimari.md) | Süreçler, iş parçacıkları, veri akışı, tasarım kararları |
| [Sunucu modülleri](docs/05-backend.md) | `WebInterface/backend` modül başvurusu |
| [API başvurusu](docs/06-api.md) | Bütün uç noktalar, örnek istek ve yanıtlar |
| [Arayüz kodu](docs/07-frontend.md) | `WebInterface/frontend` yapısı ve kuralları |
| [Kurallar ve analiz](docs/08-kurallar-ve-analiz.md) | Kural derleme, koşul türleri, olay yaşam döngüsü, özetler |
| [Veri ve yapılandırma](docs/09-veri-ve-yapilandirma.md) | Dosyalar, kayıt biçimleri, ayarlar, ortam değişkenleri |
| [Geliştirme ve test](docs/10-gelistirme-ve-test.md) | Geliştirme düzeni, sistem testi, sık yapılan değişiklikler |
| [Sorun giderme](docs/11-sorun-giderme.md) | Belirtiye göre çözümler, bilinen sınırlar |

## Depo düzeni

| Dizin | İçerik |
| :--- | :--- |
| `WebInterface/` | **Ürün:** web sunucusu (`backend/`), arayüz (`frontend/`), sistem testi (`tests/`). |
| `Rule_Generator_LLM/` | Kural derleyici, nesne takibi, koşul değerlendirici, olay özetleyici, dil modeli servis ayarları. |
| `Object_Detection/` | Nesne tespiti kitaplığı ve Triton model deposu. |
| `Anomaly_Detection/` | Anomali modelinin eğitim kodu (git alt modülü; çalışan sistemin parçası değil). |
| `Camera_System_Simulator/` | Geliştirme için sahte kameralar (RTSP + ONVIF). |
| `TestVideoSet/` | Simülatörün yayınladığı örnek videolar (depoda tutulmaz). |
| `docs/` | Belgeler. |

## Veri akışı

```
kamera (RTSP) ──► camera_service ──► tarayıcı (WebSocket ile canlı görüntü)
                       │
                       ├─► anomaly_service ──► Triton: anomaly_detector ──► skor ──► olay
                       │
                       └─► live_detection_service ──► Triton: nesne tespiti ──► kural değerlendirme ──► olay

olay ──► event_journal (kayıt) + evidence_store (video, fotoğraf) + vlm_summarizer (kısa özet)
     ──► event_stream ──► açık sayfalar
```

## Test

```bash
.conda/bin/python WebInterface/tests/system_check.py --sim-ip <bu makinenin IP adresi>
```

Kendi portunda, geçici veriyle ayrı bir sunucu başlatır ve arayüzle API'nin tamamını sınar (134
denetim); çalışan sisteme dokunmaz. Her değişiklikten sonra koşulmalıdır.

Sistemin **ne kadar doğru çalıştığını** ölçmek ayrı bir iştir: `WebInterface/tests/accuracy_check.py`
etiketli test videolarını sisteme kamera gibi oynatır ve yakalanan olayı, kaçanı, yanlış alarmı sayar
(bkz. [docs/10](docs/10-gelistirme-ve-test.md#doğruluk-ölçümü)).

Aynı test her push'ta GitHub Actions üzerinde de koşar (`.github/workflows/ci.yml`); orada kamera ve
ekran kartı olmadığı için canlı video bölümü atlanır, kalan 112 denetim çalışır.

`Object_Detection/run_tests.py` model yükler ve birkaç GB bellek ister; canlı sistem çalışırken koşmayın.

## Devralan geliştirici için

- **Erişim anahtarı.** Anahtar yalnızca `.env` dosyasındadır ve depoya girmez. Ancak daha önce
  kullanılan anahtar **git geçmişinde durmaktadır**; yenilenmelidir.
- **Kimlik doğrulama yok.** Arayüz ve API ağdaki herkese açıktır; yerel ağ dışına açılmadan önce ele alınmalı.
- **Veri JSON dosyalarında.** Tek sunucu için tasarlanmıştır (atomik yazım, dizin kilidi); çok
  sunuculu kurulum için veritabanına taşınması gerekir.
- **Hâlâ uzun olan işlevler.** `Rule_Generator_LLM/compiler.py: _normalize_plan_data` (~230 satır),
  `live_detection_service.py: _process_camera` (~190 satır), `camera_service.py: probe_and_register`
  (~125 satır). Çalışıyorlar; ilk ikisi yalnızca gerçek model yanıtlarıyla sınanabildiği için
  bölünmeleri ayrı bir iş olarak ele alınmalı.
- **Sınanmayanlar.** Gerçek donanım kameraları, Firefox, günlerce kesintisiz çalışma.
  Tam liste: [docs/11-sorun-giderme.md](docs/11-sorun-giderme.md), "Bilinen sınırlar".
