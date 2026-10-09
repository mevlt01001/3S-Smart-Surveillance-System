# 05 — Sunucu modülleri

Dizin: `WebInterface/backend/`. Çalıştırma: `uvicorn WebInterface.backend.server:app`.

```
backend/
├── __init__.py              OpenCV ortam ayarları
├── server.py                Uygulama: açılış, kapanış, ara katmanlar, yönlendiricilerin bağlanması
├── paths.py                 Veri dizini, güvenli yazım, tek örnek kilidi, kapanma işareti
├── api/                     HTTP katmanı (iş mantığı içermez)
│   ├── schemas.py           İstek gövdeleri
│   ├── system.py            /api/health, /api/system/stats, /api/onvif/scan
│   ├── cameras.py           /api/cameras/…  (kayıt, fotoğraf, MJPEG, WebSocket)
│   ├── live.py              /api/live/state, /api/change-detection/…
│   ├── rules.py             /api/rules/…
│   ├── events.py            /api/anomaly/…  (günlük, kanıt dosyaları, SSE)
│   ├── settings.py          /api/settings
│   └── frontend.py          Arayüz dosyalarının sunumu
├── camera_service.py        Kamera kayıtları ve canlı kare kaynağı
├── onvif_core.py            ONVIF keşfi ve cihaz sorguları
├── onvif_auth.py            WS-Security kimlik başlığı
├── anomaly_service.py       Anomali döngüsü; skor → olay
├── live_detection_service.py  Kural döngüsü; tespit → ihlal
├── change_detector.py       Engel / değişiklik bölgeleri (SSIM)
├── rule_compilation.py      Kural açıklamalarının arka planda derlenmesi
├── rules_service.py         Kural kayıtları
├── settings_service.py      Ayarlar: varsayılanlar, sınırlar, kalıcılık
├── event_journal.py         Olay günlüğü
├── evidence_store.py        Olay videoları ve fotoğrafları
├── event_stream.py          Canlı bildirim (SSE) yayıncısı
└── system_stats.py          Analiz sunucusu ve ekran kartı durumu
```

Bağımlılık yönü tek taraflıdır: `api/` → servisler → `paths`. Servisler `api/` altından bir şey
içe aktarmaz.

---

## `server.py`

Uygulamayı kurar; uç nokta içermez.

- `acquire_instance_lock()` çağrısı servis içe aktarmalarından önce gelir (sıra önemlidir).
- `QuietPollingFilter`: arayüzün sık yaptığı başarılı sorguları erişim günlüğünden çıkarır.
- `lifespan`: `SIGINT`/`SIGTERM` işleyicilerini sarar (önce `SHUTTING_DOWN`), kapanışta servis
  döngülerini durdurur ve kamera işçilerini kapatır.
- Ara katmanlar: GZip (≥ 1 KB), CORS (her kaynağa açık).

## `paths.py`

| Ad | İşlev |
| :--- | :--- |
| `DATA_DIR`, `data_path(*parçalar)` | Veri dizini (`AEGIS_DATA_DIR`, varsayılan bu paket dizini). |
| `atomic_write_json(yol, nesne)` | Geçici dosya + yeniden adlandırma ile yazım. |
| `acquire_instance_lock(wait_sec=20)` | `.aegis.lock` üzerinde `flock`; süre `AEGIS_LOCK_WAIT_SEC` ile değişir. Alamazsa `RuntimeError`. |
| `SHUTTING_DOWN` | `threading.Event`; uzun ömürlü her döngü denetler. |

## `camera_service.py`

İki sınıf ve tekil `camera_service` nesnesi.

### `CameraLiveWorker`

Bir kameranın yayınını çözen iş parçacığı.

| Sabit | Değer | Anlamı |
| :--- | :--- | :--- |
| `STREAM_STALE_SEC` | 3.0 | Bu kadar süre kare gelmezse yayın "takılmış" sayılır. |
| `WORKER_IDLE_SEC` | 120.0 | Tüketen yoksa bağlantı bu süre sonunda bırakılır. |
| `MAX_OUTPUT_FPS` | 30.0 | Kamera başına işlenen en yüksek kare hızı. |

Durumlar: `connecting` → `live` ⇄ `stalled`, kullanılmayınca `idle`. Önemli davranışlar:

- `is_live()` için oturumda en az iki kare gelmiş olmalıdır; ilk kare çoğu zaman çözücünün
  tamponundan gelen eski bir karedir.
- Okuma 4 saniyeden uzun takılırsa oturum bırakılır; çözücünün sonradan boşalttığı bayat kareler
  "canlı" diye sunulmaz.
- Bir adres çalışınca hatırlanır; kaydedilmiş IP'ye ulaşılamazsa aynı yol `localhost` üzerinden denenir
  (sunucuyla aynı makinedeki yayınlar için).
- `add_listener` / `remove_listener`: yeni karede çağrılacak işlevler (WebSocket dağıtımı bunu kullanır).
- `get_frame_info`, `get_frame_at(ts)`, `get_clip_frames(süre)`, `get_clip_frames_range(baş, son)`,
  `get_ai_frames(adet)`, `get_bgr_frame()`.

### `CameraService`

| Yöntem | İşlev |
| :--- | :--- |
| `get_all()`, `get_by_id(id)` | Kamera kayıtları (şifre dâhil; yalnızca sunucu içinde kullanılır). |
| `public_view(kamera)` | Şifresi çıkarılmış ve yayın durumu eklenmiş kopya; API bunu döndürür. |
| `probe_and_register(ip, port, …)` | ONVIF ile bağlanır, cihaz ve yayın bilgisini okur, kaydeder, işçiyi başlatır. Cihaza ulaşılamasa da kayıt oluşur (`status`: `offline` / `auth_error`). |
| `update_camera`, `delete_camera` | Ad / açıklama güncelleme; silme (işçiyi durdurur). |
| `get_stream_health(id)` | `stream_live`, `stream_connecting`, `stream_standby`, `stream_state`, `stream_fps`, `last_frame_age`. |
| `get_camera_snapshot(id)` | Güncel JPEG ya da durum kartı ("BAĞLANIYOR", "SİNYAL YOK"). |
| `iter_frames(id, max_fps)` | Zaman uyumsuz üreteç: her yeni karede JPEG verir; sinyal yokken saniyede bir durum kartı. |
| `mjpeg_stream_generator(id)` | Aynı karelerin `multipart/x-mixed-replace` biçimi. |
| `set_clip_window(sn)` | Kare tamponunun uzunluğu (anomali servisi ayarlara göre belirler). |
| `sync_stream_status()` | Bekçi: 8 saniyedir kare gelmeyen kamerayı `offline` yapar; ilk bağlantıda 20 sn tanır. `auth_error` durumunu ezmez. |
| `shutdown()` | Bütün işçileri durdurur. |

Kamera kimliği `cam_<ip, noktalar alt çizgi>_<onvif portu>` biçimindedir; aynı adres yeniden
eklenirse aynı kayıt güncellenir.

## `onvif_core.py`, `onvif_auth.py`

- `run_multi_nic_ws_discovery(timeout)`: etkin her ağ kartından `239.255.255.250:3702` adresine
  WS-Discovery sorgusu gönderir, yanıt veren cihazları döndürür.
- `ONVIFClient`: cihaz bilgisi, profiller, yayın adresi (`GetStreamUri`), fotoğraf adresi.
  Önce şifresiz `GetSystemDateAndTime` ile kameranın saati okunur; kimlik başlığındaki zaman damgası
  kameranın saatine göre üretilir (saat farkı kimlik doğrulamayı bozmasın diye).
- `generate_ws_security_header(kullanıcı, şifre, saat_farkı)`: `PasswordDigest` başlığı.

## `anomaly_service.py`

Tekil `anomaly_service`. Dosyanın başındaki sabitler:

| Sabit | Değer | Anlamı |
| :--- | :--- | :--- |
| `CYCLE_SEC` | 0.25 | Bir tur süresi; her kamera saniyede ~4 kez puanlanır. |
| `MAX_BATCH_SIZE` | 8 | Tek istekte en çok kamera. |
| `SCORE_FRESH_SEC` | 10 | Bundan eski skor gösterilmez. |
| `RULE_CLIP_SEC` | 5 | Kural ihlalinde geriye dönük video süresi. |
| `RULE_VIOLATION_SCORE` | 75 | Kural ihlali kaydına yazılan sabit skor. |

| Yöntem | İşlev |
| :--- | :--- |
| `_run()` | Döngü: sessiz olayları kapat → analiz açık mı → sunucuya bağlan → `_score`. |
| `_pending_clips(kameralar)` | Yeni karesi olan kameraların son 16 karesi. |
| `_score(kameralar)` | Grupları modele gönderir; logit → sigmoid → 0–100 skor. |
| `_apply_score` | Skoru yumuşatır (yalnızca eşiğin altında), sınıflar, `_track_incident`'e verir. |
| `_track_incident`, `_close_incident` | Olayı açar, sürdürür, kapatır (bkz. bölüm 08). |
| `_process_evidence` | Video kodlama ve özet iş parçacıklarını başlatır. |
| `rule_violated(kamera, kural, başlık, ileti, önem)` | Kural döngüsünün her ihlal karesinde çağırdığı giriş noktası: olayı açar ya da açık tutar; `_close_silent_incidents` kapatır (bkz. bölüm 08, B.6). |
| `simulate_anomaly(kamera, skor)` | Deneme olayı kaydeder (API: `/api/anomaly/simulate`). |
| `summarize_entry(id)`, `get_entry_frames(id)` | Özeti yeniden yazdırır; videodan kare döndürür. |
| `clear_events()` | Bütün olayları kanıtlarıyla siler. |
| `get_fleet_summary()` | Her kameranın durumu ve sayaçlar. |
| `get_storage_stats()`, `delete_orphan_clips()` | Disk kullanımı; hiçbir olaya bağlı olmayan dosyaların silinmesi. |
| `reload_settings()` | Ayar değişince çağrılır; sunucu adresi değiştiyse yeniden bağlanır. |

`last_latency_ms` ve `last_inference_ts`, `system_stats` tarafından okunur.

## `event_journal.py`

Tekil `event_journal`. Olay listesini bellekte tutar; her değişikliği diske yazar ve `event_stream`
üzerinden duyurur. Döndürdüğü kayıtlar kopyadır.

| Yöntem | İşlev | Yayınladığı bildirim |
| :--- | :--- | :--- |
| `add(kayıt, kapasite)` | Başa ekler; kapasiteyi aşan en eski kayıtları kanıtlarıyla atar. | `new_anomaly` |
| `update(id, **alanlar)` | Alanları değiştirir; kayıt yoksa `None`. | `update_anomaly` |
| `set_label(id, etiket, not, operatör)` | Operatör kararı; geçersiz etikette `ValueError`. | `update_anomaly` |
| `expire_clips(adlar)` | Videosu kotadan silinen kayıtları işaretler (`clip_expired`). | — |
| `clear()` | Hepsini siler, silinenleri döndürür. | `journal_cleared` |
| `get(id)`, `list(…)`, `stats()`, `referenced_files()` | Okuma. | — |

Açılışta, yarıda kalmış kayıtları onarır: `is_ongoing` → kapatılır ve `interrupted` işaretlenir;
`ai_status: generating` → `interrupted`.

## `evidence_store.py`

Durumsuz işlevler. Günlüğü tanımaz; hangi dosyaların kullanıldığını çağıran söyler.

| İşlev | İşlev |
| :--- | :--- |
| `save_snapshot(id, jpeg, taken_at)` | `snap_<id>.jpg`; dönen adres `?v=<zaman>` ile damgalanır. |
| `encode_clip(id, kareler)` | JPEG'leri ffmpeg'e borulayıp `clip_<id>.mp4` üretir (H.264 baseline, `+faststart`). Kare hızı yakalama zamanlarından hesaplanır. |
| `footage_seconds(kareler)` | Karelerin kapsadığı gerçek süre. `MIN_CLIP_SECONDS` (1 sn) altı video sayılmaz. |
| `enforce_quota(en_çok_adet, en_çok_mb)` | En eski videoları siler; silinenlerin adlarını döndürür. |
| `usage(kullanılan_videolar, kullanılan_fotoğraflar)` | Disk kullanımı ve sahipsiz dosya sayıları. |
| `delete_unreferenced_clips`, `delete_unreferenced_snapshots` | Sahipsiz dosyaları siler; 120 sn'den yeni olanlara dokunmaz. |
| `delete_files_of(kayıt)` | Bir olayın video ve fotoğrafını siler. |

## `event_stream.py`

Tekil `event_stream`: `subscribe()` (olay döngüsünden), `unsubscribe(kuyruk)`,
`publish(olay)` (herhangi bir iş parçacığından). Kuyruk 256 iletiyle sınırlıdır; takılan istemci en
eski iletisini kaybeder.

## `live_detection_service.py`

Tekil `live_detection_service`. Döngü, etkin kuralı olan ve yeni kare getiren kameraları işler.

- `_ensure_detector()`: `YOLODetector`'ı Triton'a bağlar; başarısızlıkta artan aralıklarla yeniden dener.
- `_get_plan(kural, bölge)`: saklanan planı doğrular ve `(kural, bölge, updated_at)` anahtarıyla
  önbelleğe alır. Yalnızca "kişi" arayan planlar `coco_detector`'a yönlendirilir.
- `_process_camera(kamera)`: bölge türüne göre `change_detector.check_frame` ya da tespit +
  nesne takibi (`ObjectTracker`, kamera ve model başına bir tane) + `ConditionEvaluator.evaluate`.
  Aynı karede aynı model ve sınıflar için tespit ve takip bir kez yapılır. Bir kural ancak
  `RULE_CONFIRM_SEC` boyunca kesintisiz ihlal edildiyse alarm sayılır ve `rule_violated` çağrılır.
- `get_detections(camera_id=None)`: son durum — `alarm`, `alarm_text`, `detections`
  (`track_id`, `class_name`, `confidence`, `bbox_normalized`, `in_zone`, `is_violation`), `change_results`.
- Sabitler: `MIN_CYCLE_SEC` 0.08, `IDLE_SLEEP_SEC` 0.5, `RULE_CONFIRM_SEC` 1.0, `TRACKER_IDLE_SEC` 60.

## `change_detector.py`

Tekil `change_detector`. Bölgenin referans görüntüsünü `change_refs/` altında saklar.

- `capture_reference(kamera, bölge, kare, noktalar, …)`: çokgeni maskeleyip 160×120'ye küçültür, kaydeder.
- `check_frame(…)`: canlı kareyi aynı biçime getirip referansla SSIM hesaplar.
  SSIM < 0,72 → `alarm`; < 0,88 → `warning` (değişen alan %10'u geçerse alarm sayılır); değilse `clear`.
- `get_zone_state`, `delete_reference`, `delete_camera_references`.

## `rule_compilation.py`

`Rule_Generator_LLM.compiler.RuleCompiler` ile HTTP katmanı arasındaki köprü.

| İşlev | İşlev |
| :--- | :--- |
| `is_available()` | Derleyici kurulabildi mi (anahtar ve bağımlılıklar var mı). |
| `start(kural_id)` | Planı eksik bölgeleri arka planda derler. Kural bu sırada değiştiyse sonuç atılır. |
| `recompile(bölgeler)` | Bütün bölgeleri yeniden derler (engelleyen çağrı). |
| `keep_unchanged_plans(eski, yeni)` | Açıklaması değişmeyen bölgenin planını korur. |
| `apply_manual_plans(bölgeler)` | Listeden tanımlanan (`manual`) bölgelerin planını hemen kurar; geçersiz seçimde `ValueError`. |
| `compiled_changes(kural, bölgeler, planlar)` | Derleme sonrası saklanacaklar: bölgeler ve (kullanıcı formdan saat vermediyse) cümleden okunan çalışma saatleri. |
| `status_of(kural)` | `compiling`, `error`, `unsupported`, `not_required`, `compiled`, `fallback`, `pending`, `unavailable`. |
| `rule_view(kural, slim)` | API gösterimi (`schedule_text`, `active_now` dahil); `slim` planın yerine kısa `plan_summary` koyar. |

## `reports.py`

`build_report(olaylar, gün, now, capacity)`: olay günlüğünden rapor sayılarını hesaplayan saf işlev
(durum, dosya ya da servis içe aktarması yok; bu yüzden çalışan sistem olmadan sınanabilir). Uç
noktası `api/reports.py`. Alanlar bölüm 06'dadır.

## `rules_service.py`, `settings_service.py`

- `rules_service`: `get_all(camera_id)`, `get_by_id`, `create_rule`, `update_rule`, `delete_rule`,
  `delete_rules_for_camera`. Dosya dışarıdan değiştirilirse (`mtime`) yeniden yükler.
- `settings_service`: `get_all()`, `get_section(ad)`, `update(değişiklikler)`, `reset_defaults()`.
  `_sanitize()` her değeri izin verilen aralığa çeker; aralıklar bölüm 09'dadır.

## `system_stats.py`

`get_system_telemetry()`: Triton'un hazır olup olmadığı ve hazır modeller, son 15 saniyede **ölçülmüş**
analiz süreleri (yoksa `null`), `nvidia-smi` ile ekran kartı adı, bellek, yük ve sıcaklık. Sonuç 2
saniye önbelleklenir.

## `api/` katmanı

Her modül bir `APIRouter` tanımlar; `api/__init__.py` bunları `routers` listesinde toplar. Kurallar:

- Yönlendirici doğrulama yapar, servisi çağırır, yanıtı biçimler; iş mantığı yazmaz.
- Bulunamayan kaynak `404`, geçersiz girdi `422`, çakışma `409`, erişilemeyen servis `503`.
  Hata iletileri Türkçedir ve arayüzde olduğu gibi gösterilir (`detail` alanı).
- Engelleyen çağrılar `asyncio.to_thread` ile yapılır.
