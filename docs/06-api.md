# 06 — API başvurusu

Taban adres: `http://<sunucu>:8500`. Bütün gövdeler JSON'dur. Etkileşimli belge (Swagger) sunucu
çalışırken `/docs` adresindedir.

**Kimlik doğrulama yoktur.** API'ye ulaşabilen herkes her işlemi yapabilir.

## Genel kurallar

- Başarılı yanıtlar çoğunlukla `"success": true` içerir.
- Hata yanıtı: `{"detail": "<Türkçe açıklama>"}`. Arayüz bu metni olduğu gibi gösterir.

| Kod | Anlamı |
| :--- | :--- |
| 404 | Kamera, kural, olay ya da dosya bulunamadı. |
| 409 | Kural, hazırlanırken değiştirildi. |
| 422 | Geçersiz girdi (IP, port, etiket, boş başlık, canlı görüntü yok…). |
| 400 | Özet başlatılamadı (servis kapalı ya da olay yok). |
| 503 | Kural hazırlama servisine ulaşılamıyor. |

---

## Sistem

### `GET /api/health`
Canlılık denetimi. `{"ok": true, "time": 1791525513.68}`

### `GET /api/system/stats`
Analiz sunucusu ve ekran kartı durumu. 2 saniye önbelleklidir.

```json
{
  "triton": {
    "status": "READY",
    "url": "http://localhost:8000",
    "models_ready": ["safety_detector", "coco_detector", "yoloe_detector", "anomaly_detector"],
    "avg_gpu_latency_ms": 43.8,
    "object_detection_latency_ms": null,
    "anomaly_detection_latency_ms": 43.8
  },
  "gpu": {"available": true, "name": "NVIDIA GeForce GTX 1650 Ti", "vram_used_mb": 2728,
          "vram_total_mb": 4096, "utilization_gpu_pct": 10, "temperature_c": 55}
}
```

Süreler son 15 saniyede **ölçülmüşse** sayı, değilse `null` olur (o model o an çalışmıyordur).
`status` hazır değilken `"OFFLINE"` benzeri bir değer alır; arayüz yalnızca `"READY"` olup olmadığına bakar.

### `POST /api/onvif/scan?timeout=3.0`
Ağdaki ONVIF cihazlarını arar (WS-Discovery).

```json
{"success": true, "count": 2, "devices": [
  {"ip": "192.168.1.100", "port": 8891, "name": "Hikvision", "hardware": "DS-2CD2043G2-I"}
]}
```

---

## Kameralar

### `GET /api/cameras`
```json
{"success": true, "count": 1, "cameras": [{
  "id": "cam_192_168_1_100_8891",
  "ip": "192.168.1.100", "port": 8891, "rtsp_port": 554, "username": "admin",
  "name": "Depo girişi", "description": "",
  "manufacturer": "Hikvision", "model": "DS-2CD2043G2-I",
  "firmware_version": "V5.7.1 build 220510", "serial_number": "…",
  "status": "online", "status_message": "Bağlantı Aktif",
  "resolution": "1920x1080", "encoding": "H.264", "framerate": 30,
  "stream_uri": "rtsp://admin:…@192.168.1.100:8554/video7_1",
  "stream_live": true, "stream_connecting": false, "stream_standby": false,
  "stream_state": "live", "stream_fps": 25.0, "last_frame_age": 0.0
}]}
```

- `status`: `online` | `offline` | `auth_error` — cihazla son iletişimin sonucu.
- `stream_state`: `live` | `connecting` | `stalled` | `idle` — yayının anlık durumu.
- Şifre yanıtta **yer almaz**; `stream_uri` ise kimlik bilgisini içerir (arayüz gösterirken maskeler).

### `POST /api/cameras/add`
```json
{"ip": "192.168.1.150", "port": 80, "username": "admin", "password": "…", "name": "", "rtsp_port": 554}
```
Yalnızca `ip` zorunludur. Kameraya bağlanılamasa da kayıt oluşur; sonucu `camera.status` söyler.
Aynı `ip:port` yeniden gönderilirse var olan kayıt güncellenir. Yanıt: `{"success": true, "camera": {…}}`.
En fazla 45 saniye sürebilir. Hatalar: `422` (IP ya da port geçersiz).

### `PUT /api/cameras/{id}`
`{"name": "Yeni ad", "description": "Bu kamera …"}` — verilen alanlar değişir.

### `DELETE /api/cameras/{id}`
Kamerayı, kurallarını ve referans görüntülerini siler. `{"success": true, "removed_rules": 2}`

### `POST /api/cameras/{id}/reconnect`
Kamerayı kayıtlı bilgilerle yeniden yoklar. Yanıt `add` ile aynıdır.

### `GET /api/cameras/{id}/snapshot`
Güncel kare (JPEG). Sinyal yoksa durum kartı döner; **her zaman 200**. Önbelleklenmez. `HEAD` desteklenir.

### `GET /api/cameras/{id}/stream`
MJPEG (`multipart/x-mixed-replace; boundary=frame`). WebSocket kullanamayan istemciler içindir.

### `WS /api/cameras/{id}/ws?fps=0`
İkili iletiler; her ileti bir JPEG karesidir. Yeni kare çözüldüğü anda gönderilir. `fps` > 0 ise
hız o değerle sınırlanır (en çok 60). Kamera yoksa bağlantı `1008` koduyla kapatılır. Sinyal
kesikken saniyede bir durum kartı gönderilir.

---

## Canlı durum

### `GET /api/live/state`
Canlı duvarın tek sorgusu.

```json
{
  "success": true,
  "detector_ready": true,
  "fleet": {
    "total_cameras": 9, "critical_count": 0, "warning_count": 1, "normal_count": 8,
    "offline_count": 0, "connecting_count": 0, "standby_count": 0,
    "triton_model_ready": true, "analysis_enabled": true,
    "thresholds": {"normal": 25.0, "warning": 50.0},
    "cameras": [{
      "camera_id": "cam_192_168_1_100_8891", "name": "Depo girişi", "ip": "192.168.1.100",
      "score": 31.4, "tier": "warning", "label": "Şüpheli / Dikkat", "analyzed": true,
      "stream_live": true, "stream_connecting": false, "stream_standby": false, "stream_fps": 25.0
    }]
  },
  "detections": {
    "cam_192_168_1_100_8891": {
      "camera_id": "cam_192_168_1_100_8891", "timestamp": 1791525786.93,
      "has_rules": true, "stream_live": true, "detector_ready": true,
      "alarm": true, "alarm_text": "Depo girişi: baretsiz kişi",
      "detections_count": 1,
      "detections": [{"class_name": "NO-Hardhat", "confidence": 0.81,
                      "bbox_normalized": [0.41, 0.22, 0.52, 0.61],
                      "in_zone": true, "is_violation": true, "zone_name": "Depo girişi",
                      "rule_title": "Baret kontrolü"}],
      "change_results": [{"zone_id": "zone_cd", "zone_name": "Acil çıkış", "has_reference": true,
                          "ssim": 0.9949, "alarm": false, "alarm_level": "clear", "change_pct": 0.0}]
    }
  }
}
```

- `fleet.cameras[].tier`: `normal` | `warning` | `critical` | `offline`. Liste en acilden başlar.
- `analyzed`: kameranın 10 saniyeden taze bir skoru var mı.
- `thresholds.normal` uyarı seviyesi, `thresholds.warning` kritik seviyesidir.
- `bbox_normalized`: `[x1, y1, x2, y2]`, 0–1 aralığında.

### `GET /api/anomaly/status`
Yalnızca `fleet` bölümü.

### `GET /api/cameras/{id}/live-detections`
Yalnızca o kameranın `detections` kaydı: `{"success": true, "data": {…}}`

### `GET /api/change-detection/{kamera}/{bölge}`
Bölgenin durumu: `has_reference`, `reference_ts`, `last_ssim`, `alarm`, `alarm_level`, `alarm_since`,
`last_check_ts`. Referans yoksa `404`.

### `POST /api/change-detection/{kamera}/{bölge}/capture-reference`
O anki canlı kareyi bölgenin "boş" referansı olarak kaydeder. Hatalar: `404` (kamera ya da bölge
yok), `422` (canlı görüntü yok, bölge çok küçük).

### `DELETE /api/change-detection/{kamera}/{bölge}/reference`
Referansı siler; yenisi alınana kadar bölge değerlendirilmez.

---

## Kurallar

### `GET /api/rules?camera_id=&full=false`
```json
{"success": true, "count": 1, "compiler_available": true, "rules": [{
  "id": "rule_e1d406dd91", "title": "Baret kontrolü",
  "scope": "camera", "camera_id": "cam_192_168_1_100_8897", "camera_name": "Depo",
  "severity": "warning", "description": "Depo girişi: Baret takmayan biri girerse haber ver.",
  "enabled": true, "created_at": 1791524774.12, "updated_at": 1791524965.31,
  "compile_status": "compiled", "camera_missing": false,
  "zones": [{
    "id": "zone_1791524742354_ow88", "name": "Depo girişi",
    "description": "Baret takmayan biri girerse haber ver.",
    "zone_type": "detection",
    "points": [{"x": 0.2067, "y": 0.1519}, {"x": 0.61, "y": 0.15}, {"x": 0.6, "y": 0.8}],
    "color_idx": 0,
    "compile_meta": {"latency_ms": 1376.8, "status": "success", "model": "qwen3-vl-30b",
                     "compiled_at": "2026-10-09T05:46:15+00:00"},
    "plan_summary": {"model": "safety_detector", "classes": ["NO-Hardhat"],
                     "conditions": ["zone_presence"], "status": "success"}
  }]
}]}
```

- `scope`: `camera` (tek kamera) | `system` (bütün kameralar; `camera_id` `null`).
- `zone_type`: `detection` (kişi / nesne kuralı) | `change_detection` (engel / değişiklik).
- `compile_status`: `compiling` | `compiled` | `fallback` | `pending` | `unavailable` | `error` | `not_required`.
- `camera_missing`: kuralın kamerası silinmiş.
- `full=true`, `plan_summary` yerine planın tamamını (`detection_plan`, `compile_logs`,
  `raw_llm_response`) döndürür.

### `POST /api/rules`
```json
{"title": "Baret kontrolü", "scope": "camera", "camera_id": "cam_…", "camera_name": "Depo",
 "zones": [{"id": "zone_1", "name": "Depo girişi", "description": "Baret takmayan biri girerse haber ver.",
            "zone_type": "detection", "points": [{"x": 0.2, "y": 0.2}, {"x": 0.8, "y": 0.2}, {"x": 0.8, "y": 0.8}]}]}
```
Kuralı kaydeder ve bölge açıklamalarını **arka planda** derlemeye başlar; yanıt hemen döner ve
`compile_status` `compiling` olur. Sonucu görmek için listeyi yeniden isteyin. Hatalar: `422`
(başlık boş, kamera yok).

### `GET /api/rules/{id}`
Tek kural, planlarıyla birlikte.

### `PUT /api/rules/{id}`
Verilen alanları değiştirir: `title`, `enabled`, `scope`, `camera_id`, `camera_name`, `zones`, `description`.
`zones` gönderilirse açıklaması değişmeyen bölgelerin planı korunur; yalnızca yeni ya da değişen
bölgeler derlenir.

### `DELETE /api/rules/{id}`
Kuralı ve engel bölgelerinin referanslarını siler.

### `POST /api/rules/{id}/compile`
Bütün bölgeleri yeniden derler ve **bitene kadar bekler** (birkaç saniye). `{"success": true, "plans_count": 1}`.
Hatalar: `503`, `409`.

### `GET /api/rules/{id}/plan`
Tanılama: her bölgenin derlenmiş planı, derleme günlüğü ve modelin ham yanıtı.
`{"compile_status", "compile_error", "plans": [{"zone_id", "zone_name", "detection_plan", "compile_logs", "compile_meta", "raw_llm_response"}]}`

---

## Olaylar

Uç noktalar tarihsel nedenle `/api/anomaly/` altındadır; kural ihlallerini de kapsar.

### `GET /api/anomaly/journal?camera_id=&tier=&operator_label=&limit=250`
En yeniden eskiye olaylar ve sayaçlar. `limit` en çok 2000.

```json
{"success": true, "count": 1,
 "stats": {"total_events": 1, "critical_count": 1, "warning_count": 0, "normal_count": 0,
           "rule_violation_count": 0, "total_warnings": 1,
           "correct_count": 0, "false_positive_count": 0, "unlabeled_count": 1},
 "journal": [{
   "id": "anom_58361cda",
   "timestamp": 1791525040.45, "timestamp_str": "08:50:40", "date_str": "09.10.2026",
   "camera_id": "cam_192_168_1_100_8892", "camera_name": "Depo",
   "score": 99.3, "tier": "critical", "label": "Kritik Anomali",
   "anomaly_type": "Olağandışı hareket",
   "start_time_str": "08:50:39", "peak_time_str": "08:50:43", "end_time_str": "08:50:46",
   "duration_sec": 6.8, "is_ongoing": false,
   "snapshot_url": "/api/anomaly/snapshots/snap_anom_58361cda.jpg?v=1791525043",
   "clip_url": "/api/anomaly/clips/clip_anom_58361cda.mp4",
   "ai_status": "completed",
   "ai_headline": "Bir kişi, palet arabasıyla bir nesneyi düşürdü.",
   "ai_verdict": "confirmed",
   "ai_summary": "**Özet Başlık:** Bir kişi, palet arabasıyla bir nesneyi düşürdü.\n- …\n**Öneri:** …",
   "message": "Depo: Bir kişi, palet arabasıyla bir nesneyi düşürdü."
 }]}
```

Operatör karar verdiğinde kayda `operator_label` (`correct` / `false_positive`) eklenir; alan yoksa
olay incelenmemiştir. Alanların tam açıklaması [09 — Veri ve yapılandırma](09-veri-ve-yapilandirma.md) bölümündedir.

### `GET /api/anomaly/stats`
Yalnızca sayaçlar: `{"success": true, "stats": {…}}`

### `GET /api/anomaly/events-stream`
Server-Sent Events. Bağlanınca `{"type": "connected"}`, sonra:

| `type` | Ne zaman | Gövde |
| :--- | :--- | :--- |
| `new_anomaly` | Olay açıldı | `entry`: olayın tamamı |
| `update_anomaly` | Olay kapandı, özeti geldi, işaretlendi, videosu yazılamadı | `entry`: güncel hâli |
| `journal_cleared` | Bütün olaylar silindi | — |

15 saniye sessizlikte `: keep-alive` yorumu gönderilir.

### `POST /api/anomaly/{id}/label`
`{"label": "correct"}` — `correct` | `false_positive` | `unlabeled`. İsteğe bağlı `notes`, `operator_name`.
Yanıt: `{"success": true, "entry": {…}}`. Hatalar: `422` (etiket geçersiz), `404`.

### `POST /api/anomaly/{id}/summarize`
Özeti yeniden yazdırır. Hemen döner (`{"success": true, "status": "generating"}`); sonuç
`update_anomaly` bildirimiyle gelir. Hata: `400`.

### `GET /api/anomaly/{id}/frames`
Olay videosundan eşit aralıklı en çok 8 kare.
`{"success": true, "duration_sec": 6.8, "timestamps": [0.0, 0.85, …], "frames": ["<base64 JPEG>", …]}`

### `POST /api/anomaly/clear`
Bütün olayları videoları ve fotoğraflarıyla siler. Geri alınamaz.

### `POST /api/anomaly/simulate`
`{"camera_id": "cam_…", "score": 55}` — o skorla bir deneme olayı kaydeder (gösterim ve test için).

### `GET /api/anomaly/clips/{dosya}` · `GET /api/anomaly/snapshots/{dosya}`
Olay videosu (MP4, aralık istekleri desteklenir) ve olay fotoğrafı (JPEG, 7 gün önbelleklenebilir).
Video hâlâ kodlanıyorsa 3 saniyeye kadar beklenir. Yoksa `404`.

### `GET /api/anomaly/storage`
```json
{"clip_count": 1, "clip_mb": 0.4, "orphan_clip_count": 0, "orphan_clip_mb": 0.0,
 "snapshot_count": 1, "snapshot_mb": 0.01, "orphan_snapshot_count": 0,
 "journal_entries": 1, "max_storage_mb": 1000, "max_stored_clips": 500}
```
`orphan_*`: hiçbir olayın işaret etmediği dosyalar.

### `POST /api/anomaly/storage/cleanup-orphans`
Sahipsiz video ve fotoğrafları siler (120 saniyeden yeni olanlar hariç).
`{"success": true, "deleted_count": 3, "deleted_snapshots": 1, "freed_mb": 12.4}`

---

## Ayarlar

### `GET /api/settings`
`{"success": true, "settings": {"anomaly": {…}, "recording": {…}, "live_wall": {…}}}` — alanlar bölüm 09'da.

### `POST /api/settings`
Gövde: ayarların tamamı ya da bir bölümü. Değerler izin verilen aralığa çekilir, kaydedilir ve
çalışan servislere **hemen** uygulanır. Yanıt, uygulanan ayarların tamamıdır.

### `POST /api/settings/reset`
Varsayılanlara döner.

---

## Arayüz dosyaları

| Yol | İçerik |
| :--- | :--- |
| `/` | `index.html` |
| `/ui/css/*`, `/ui/js/*` | Arayüz dosyaları (`Cache-Control: no-cache`) |
| `/static/js/*.js` | Eski sürümden kalma önbellekli sayfalar için tek seferlik yenileme betiği |
| `/docs`, `/openapi.json` | FastAPI'nin ürettiği API belgesi |
